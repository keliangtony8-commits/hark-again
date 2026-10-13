# Copyright 2026 Google LLC / OpenAI / DeepSeek
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from (modified):
#   google-gemini/gemini-cli packages/core/src/tools/exit-plan-mode.ts + policy/policies/plan.toml +
#     prompts/snippets.ts renderPlanningWorkflow (Apache-2.0): 计划模式下只放只读工具（策略层硬拦，不靠模型自觉）、
#     exit_plan_mode 交给用户批准、批准后“约束立即解除”的转场提示、驳回时让模型问要改哪里、子助手也只读；
#   openai/codex codex-rs/collaboration-mode-templates/templates/plan.md (Apache-2.0): 提示词骨架——先查后问、
#     “可以跑不改东西的命令，不能做改东西的事”、方案要“决策完备”、紧凑的几节结构；
#   deepseek-ai/deepseek-harness packages/plan/plan-mode/src/index.ts (MIT): 状态按对话持久化、用户随时切换、
#     切换后下一轮先告诉模型一句、exit 工具常驻（不在计划模式就拒）让工具目录不变（不打断前缀缓存）、
#     方案必须以 # 标题开头。
"""计划模式（只读规划）——唯一规则。

一个对话可以切到“计划模式”（conversations.mode = plan）：这期间助手只看不改——读文件、搜索、跑只读命令、
派只读子助手去查；想动手就必须先把方案用 exit_plan_mode 交给用户批准。批准后这一轮立刻退出计划模式按方案做，
对话也切回普通模式；用户点“再改改”就留在计划模式，等他说要改哪里。

谁调用：runner（系统提示 + 切换提示 + ToolContext.plan）、loop（每次工具调用前 refusal；批准后 lift 掉系统提示里的规则）、
subagent（子助手继承只读）、builtin/plan_mode.py（exit_plan_mode）、routes/conversations（PATCH mode）。
"""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import plan as checklist, readonly_command
from .storage import safe_join

DEFAULT = "default"
PLAN = "plan"
MODES = (DEFAULT, PLAN)
TOOL = "exit_plan_mode"
PLAN_MAX = 20_000   # 方案正文上限（字）：再长就是没收敛
TITLE_MAX = 40
HISTORY_MAX = 4000  # 写进历史的方案正文上限（之后几轮模型还能照着做）

# 计划模式下照常可用的工具：只读、不改工作区 / 服务器 / 外部账号的。其余一律拒（Gemini plan.toml：默认 deny，再逐个放行）。
READ_TOOLS = frozenset({
    "read_file", "read_many_files", "list_files", "glob", "grep", "web_search", "web_fetch", "image_search", "job_status", "mcp_tools",
    "use_skill", "ask_user", "day_overview", "delegate",
    "deferred_tool",  # 只看目录 / 说明；call 在 loop 里先拆成对目标工具的调用，再按目标工具判
    "get_current_time", "convert_time", "resolve_relative_date", "analyze_video", "search_transcript", "search_history", "search_memory",
    "billing_status",  # v2.39 只读查花费 / 额度
    "browser_open", "browser_read", "browser_look", "browser_scroll",  # 看网页；点、填、登录、上传都不行
    "show_table", "show_links", "show_stats", "show_draft", "show_summary", "show_images", "show_products",
    TOOL,
})
COMMAND_TOOLS = frozenset({"run_command"})  # 只读脚本放行（readonly_command），其余拒

PROMPT = f"""# 当前处于计划模式（只读规划）
用户把这个对话切到了计划模式：先把事情想清楚、和用户对齐，拿到批准之前不动手。

## 规则（严格）
- 只做“不改东西”的事：读文件、搜索、看网页、跑只读命令（ls、cat、grep、find、git status/log/diff……），可以派子助手去查。
- 不做“改东西”的事：写/改/删文件、装包、跑会改动的命令、操作外部账号、建定时任务、发消息……这些工具在计划模式下会被直接拒绝。
- 用户语气再像命令（“直接改吧”）也不改变模式：把它当成“请规划怎么做”；想动手就用 {TOOL} 交方案请他批准。
- 只是提问（“X 是怎么工作的？”）就直接回答，不用出方案。
- 不要用 update_plan 代替方案；它是执行时的进度清单。

## 怎么做
1. 先查后问：能从工作区、网页查到的事实自己查，别问用户。
2. 只问真正影响方案的取舍（目标和验收标准、范围、约束、偏好）；给 2–4 个具体选项并推荐一个，可以用 ask_user。
3. 方案要“决策完备”：照着做的人不用再做决定。紧凑几节：概要、要改的地方（按模块/行为分组，必要时点名文件）、怎么验证、假设和默认值。
4. 和用户大致对齐后，调用 {TOOL}(plan=完整 Markdown，以“# 标题”开头) 交给用户批准。批准了才能动手；没批准就问他想改哪里，改完再交一版完整的。
"""

CHILD_NOTE = "（用户处于计划模式：你只能做只读的查找和分析，改动类工具会被拒绝。把发现交回给主助手即可。）"

LIFTED = "计划已批准，计划模式已退出。之前“只读、只规划”的约束立即解除：现在按批准的方案动手做，从第一步开始；"
LIFTED_FREE = "步骤多就先用 update_plan 列成清单。"
LIFTED_SEEDED = ("方案里的步骤已经列成进度清单（用户在聊天里看得到，第 1 步已标进行中）。做完一步就用 update_plan 传完整清单："
                 "把它标 completed、下一步标 in_progress；步骤写得不合适可以改，并在 explanation 里说为什么。")
REJECTED = "用户没有批准这个方案，仍在计划模式。别动手，也别马上再交一版：先问他想改哪里（或等他说），改好后再用 exit_plan_mode 交完整的新方案。"
NOT_ACTIVE = f"现在不在计划模式，不需要 {TOOL}：直接做就行（高风险操作照常会请用户批准）。"


@dataclass
class State:
    """一轮里的计划模式状态（ToolContext.plan）。并行副本共用同一个对象；子助手拿一份只读副本（can_exit=False）。"""
    active: bool = False
    lifted: bool = False   # 方案刚被批准：loop 下一次调模型前把系统提示里的规则拿掉（拿掉后置回 False）
    can_exit: bool = True
    exited: bool = False   # 这一轮里方案被批准过：runner 收尾推 conversation.mode，客户端关掉“计划”钮

    def lift(self) -> None:
        self.active, self.lifted, self.exited = False, True, True


def valid(mode: object) -> bool:
    return mode in MODES


def normalize(mode: object) -> str:
    return mode if mode in MODES else DEFAULT


def notice(seen: str | None, mode: str) -> str | None:
    """用户在两轮之间切换了模式：这一轮先告诉模型一句（deepseek narration；第一次进来、没变过都不说）。"""
    if seen is None or seen == mode:
        return None
    return "用户刚把这个对话切到了计划模式。" if mode == PLAN else "用户刚把这个对话切回了普通模式：计划模式的只读限制已解除，可以动手了。"


def refusal(name: str, args: dict, state: State | None) -> str | None:
    """计划模式下这次调用该不该拒：None = 放行；否则是给模型的理由。不在计划模式时只拦 exit_plan_mode。"""
    if state is None or not state.active:
        return NOT_ACTIVE if name == TOOL else None
    if name == TOOL and not state.can_exit:
        return "子助手不能交方案；把发现交回给主助手。"
    if name in READ_TOOLS:
        return None
    if name in COMMAND_TOOLS:
        if readonly_command.is_read_only(str(args.get("command") or "")):
            return None
        return ("计划模式下只能跑只读命令（ls、cat、head、grep、rg、find（不带 -exec/-delete）、wc、git status/log/diff/show、"
                "sed -n 'Np' 等，用 && || ; | 连接；不能有重定向、$变量、子 shell）。这条命令可能改东西，没有执行。"
                f"需要它就写进方案，用 {TOOL} 请用户批准后再做。")
    if name == "update_plan":
        return f"计划模式下不用 update_plan：把方案写完整，用 {TOOL} 交给用户批准。"
    return f"现在是计划模式（只读），{name} 会改东西，没有执行。把这一步写进方案，用 {TOOL} 请用户批准后再做。"


def heading(plan: str) -> str | None:
    """方案的第一个 Markdown 标题（deepseek firstHeading）。"""
    for line in plan.split("\n"):
        if m := re.match(r"^#{1,6}\s+(.+?)\s*$", line):
            return m.group(1)
    return None


class PlanTextError(ValueError):
    pass


def check_plan(plan: object) -> tuple[str, str]:
    """方案正文 → (正文, 标题)。必须以 “# 标题” 开头（deepseek），不能空、不能太长。"""
    text = str(plan or "").strip()
    if not re.match(r"^#\s+\S", text):
        raise PlanTextError("方案要是完整的 Markdown，并以一行“# 标题”开头。")
    if len(text) > PLAN_MAX:
        raise PlanTextError(f"方案太长（{len(text)} 字，上限 {PLAN_MAX}）：收敛到要点再交。")
    title = (heading(text) or "方案").strip()
    return text, title[:TITLE_MAX]


def review_card(plan: str, title: str, workspace: str = "", path: str = "") -> dict:
    """交给用户批准的方案卡（kernel 补 id/state；state pending → approved / rejected / expired）。
    workspace/path = 批准后存到哪（客户端在“已批准”时显示、点开文件）。"""
    return {"type": "plan_review", "title": title, "plan": plan, "state": "pending", "workspace": workspace, "path": path}


def lift_prompt(messages: list[dict]) -> bool:
    """方案批准后：把系统提示里的计划模式规则拿掉（换掉 messages[0]，不改原 dict）。返回是否改了。"""
    if not messages or messages[0].get("role") != "system":
        return False
    content = messages[0].get("content")
    if not isinstance(content, str) or PROMPT not in content:
        return False
    messages[0] = {**messages[0], "content": content.replace(PROMPT, "").replace("\n\n\n", "\n\n").strip()}
    return True


def history_text(block: dict) -> str:
    """方案卡进历史的样子：之后几轮模型还看得到批准的方案原文（Gemini approvedPlanPath 的作用）。"""
    state = {"pending": "等用户批准", "approved": "用户已批准", "rejected": "用户没批准，要改", "expired": "没等到答复"}
    plan = str(block.get("plan") or "")
    if len(plan) > HISTORY_MAX:
        plan = plan[:HISTORY_MAX] + "\n…（后面略）"
    return f"[方案「{block.get('title') or '方案'}」——{state.get(block.get('state'), '')}]\n{plan}"


# ---- 批准的方案存成工作区文件（Gemini approvedPlanPath + renderApprovedPlanSection，modified）----
# Gemini 把批准的方案留在 plans 目录、记下路径，之后每轮系统提示都说“有一份批准的方案，照它做、动手前先读、要改先问再更新它；
# 计划模式下默认在它上面改，用户要新方案或换了件事才另起一份”。我们的方案正文在 exit_plan_mode 的参数里，所以批准时由服务器
# 写进工作区 plans/（用户在文件里看得到、能改能删；删掉 = 不再按它做），路径记在 conversations.plan_path。
PLANS_DIR = "plans"
SLUG_MAX = 40
READ_MAX = 256 * 1024  # 读回旧方案找标题时最多读这么多字节


def plan_slug(title: str) -> str:
    """文件名里的标题部分：保留字母数字、汉字和 -，其余换成 -；空了用 plan。"""
    slug = re.sub(r"[^\w-]+", "-", title, flags=re.UNICODE).replace("_", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:SLUG_MAX].strip("-")
    return slug or "plan"


def _title_of(p: Path) -> str | None:
    try:
        if not p.is_file():
            return None
        with p.open("rb") as f:
            text = f.read(READ_MAX).decode("utf-8", errors="replace")
    except OSError:
        return None
    t = heading(text)
    return t.strip()[:TITLE_MAX] if t else None


def plan_file(root: Path, title: str, previous: str | None, day: date) -> str:
    """这份方案该存到哪（工作区相对路径）。上一份批准的方案还在、标题相同 → 原地更新它（在旧方案上改）；
    否则 plans/<日期>-<标题>.md，重名加 -2、-3……"""
    if previous:
        try:
            if _title_of(safe_join(root, previous)) == title:
                return previous
        except ValueError:
            pass
    base = f"{PLANS_DIR}/{day.isoformat()}-{plan_slug(title)}"
    rel, n = f"{base}.md", 2
    while (root / rel).exists():
        rel, n = f"{base}-{n}.md", n + 1
    return rel


def approved_path(root: Path, path: str | None) -> str | None:
    """记下的方案文件还在（没被用户删）→ 路径；否则 None（不再按它做）。"""
    if not path:
        return None
    try:
        p = safe_join(root, path)
    except ValueError:
        return None
    return path if p.is_file() else None


def approved_prompt(path: str, planning: bool) -> str:
    """系统提示里的“批准的方案”一节（稳定段：只在批准新方案时变）。"""
    if planning:
        return (f"# 已批准的方案\n这个对话之前批准过一份方案：{path}。默认在这份方案上继续改（交新版时用同一个 # 标题，会更新这份文件）；"
                "只有用户明确要“新方案”，或者这次是完全不同的事，才换个标题另起一份。")
    return (f"# 已批准的方案\n用户批准过的方案存在工作区 {path}，它是这件事的依据。接着做之前，如果上下文里已经看不到方案原文，先 read_file 读它；"
            "中途发现新需求或要换做法，先和用户确认，再更新这个文件，让它和实际做法一致。")


# ---- 批准的方案 → 进度清单（v1.73）----
# Gemini 的转场提示让模型批准后自己用 write_todos 把方案拆成清单；Codex 的 plan 模板要求方案“决策完备”（步骤写在方案里）。
# 两者合起来：方案里本来就写了步骤，批准时由服务器直接把它们种成 update_plan 清单（省一次模型调用，用户立刻看到进度卡），
# 之后照常由模型用 update_plan 打勾。认不出清楚的步骤（没有编号列表、太多、重复）就不种，退回“让模型自己列”。
STEP_HEAD = re.compile(r"步骤|实施|执行|做法|流程|计划|阶段|todo|steps?|implementation|tasks?|phases?", re.I)
_ORDERED = re.compile(r"^(\d{1,2})[.)、]\s+(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$")
_HEAD = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _step_text(raw: str) -> str:
    """一条列表项 → 清单里的一句：去掉复选框、链接、行内代码记号；开头加粗的短语（“**改 runner**：……”）就只用它；太长截断。"""
    t = re.sub(r"^\[[ xX]\]\s+", "", raw.strip())
    if m := re.match(r"^(\*\*|__)(.+?)\1", t):
        t = m.group(2)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(\*\*|__|`)", "", t)
    t = " ".join(t.split()).rstrip("：:;；。. ")
    if len(t) > checklist.CONTENT_MAX:
        t = t[:checklist.CONTENT_MAX - 1].rstrip() + "…"
    return t


def _groups(text: str) -> list[tuple[str, str, list[str]]]:
    """方案里每一组顶格列表：(所在小节标题, ordered|bullet, 各项原文)。缩进的子项、续行、空行不打断一组；
    标题、顶格正文、换了列表种类、代码块会结束一组。"""
    out: list[tuple[str, str, list[str]]] = []
    head, kind, items, fenced = "", "", [], False

    def close():
        nonlocal kind, items
        if items:
            out.append((head, kind, items))
        kind, items = "", []

    for line in text.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            close()
            continue
        if fenced or not line.strip() or line[0] in " \t":
            continue
        if m := _HEAD.match(line):
            close()
            head = m.group(1)
            continue
        m, k = _ORDERED.match(line), "ordered"
        if not m:
            m, k = _BULLET.match(line), "bullet"
        if not m:
            close()
            continue
        if kind and k != kind:
            close()
        kind = k
        items.append(m.group(m.lastindex))
    close()
    return out


def plan_steps(text: str) -> list[str]:
    """批准的方案里的执行步骤（认不清就 []）。挑选顺序：步骤类小节里的编号列表 → 步骤类小节里的圆点列表 → 全文第一组编号列表。
    要 2 到 ITEMS_MAX 步、去重后不变，才算。"""
    groups = _groups(text)
    picks = [g for g in groups if STEP_HEAD.search(g[0]) and g[1] == "ordered"] \
        + [g for g in groups if STEP_HEAD.search(g[0]) and g[1] == "bullet"] \
        + [g for g in groups if g[1] == "ordered"]
    for _, _, items in picks:
        steps = [s for s in (_step_text(i) for i in items) if s]
        if 2 <= len(steps) <= checklist.ITEMS_MAX and len(set(steps)) == len(steps) == len(items):
            return steps
    return []


def seed_items(steps: list[str]) -> list[dict]:
    """种进清单的样子：第 1 步进行中，其余待做（plan.normalize 同一套校验）。"""
    items, _ = checklist.normalize([{"content": s, "status": "in_progress" if n == 0 else "pending"}
                                    for n, s in enumerate(steps)])
    return items
