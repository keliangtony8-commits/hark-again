"""组装模型看到的一切：系统提示（人设 + 记忆 + 技能目录 + 项目规则）和对话历史。
这是控制 token 成本的唯一阀门。"""
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import agent_mentions, command_env, init_command, llm, memory_store, project_brief, prompt_cache, skill_mentions, skills_store, turn_journal, user_shell, vision, workspace_instructions, workspaces
from ..blocks import blocks_to_text
from ..config import settings
from ..connectors.providers import PROVIDERS
from ..models import Connection, Conversation, McpServer, Message, Project, Secret
from ..storage import is_text, project_file, upload_path
from ..prompt_cache import STABLE, VOLATILE
from . import parallel, tool_trace

ATTACH_CHARS = 6000     # 每个文本附件最多带多少字给模型
FOLD_TARGET = 0.5       # 需要折叠时，把原文压到预算的这个比例：留出余量，不必每轮都调一次摘要
SUMMARY_MSG_CHARS = 3000  # 喂给摘要模型的每条旧消息最多多少字（控制摘要本身的成本）

log = logging.getLogger(__name__)


async def build_system_prompt(db: AsyncSession, project_id: str | None, query: str = "") -> prompt_cache.Prompt:
    """query：用户最新一句话，用来挑相关记忆。
    返回 Prompt：稳定段在前、每轮会变的段（时间、相关记忆）在后，前缀逐字不变才能命中供应商的提示缓存
    （规则在 app/prompt_cache.py）。调用方要加段用 .add(STABLE|VOLATILE, text)，最后 .text()。"""
    p = prompt_cache.Prompt()
    p.add(STABLE, settings.system_prompt)
    p.add(STABLE, parallel.prompt())  # 只读查询可以同一步一起发（agent/parallel.py）

    skills = skills_store.enabled_skills()
    if skills:  # 只放启用的目录，正文按需 use_skill 读取
        p.add(STABLE, "可用技能：\n" + "\n".join(f"- {s.id}：{s.name}——{s.description}" for s in skills))

    # 只告诉模型“能调哪些服务”，不给任何凭证内容（按名字排序：库里的返回顺序不保证，乱序会打掉缓存）
    access = sorted(f"- {PROVIDERS[c.provider].name}（{c.account}）：{', '.join(PROVIDERS[c.provider].api_hosts)}"
                    for c in (await db.scalars(select(Connection))).all() if c.provider in PROVIDERS)
    access += sorted(f"- {s.name}：{', '.join(s.hosts)}" for s in (await db.scalars(select(Secret))).all()
                     if s.kind != command_env.KIND)
    if access:
        p.add(STABLE, "这些服务已授权，用 api_request 直接调用（认证自动附加；具体用法先看对应技能）：\n" + "\n".join(access))
    if env_line := command_env.prompt(await command_env.names(db)):  # 沙盒命令里能用的环境变量（只给名字）
        p.add(STABLE, env_line)
    servers = sorted(s.name for s in (await db.scalars(select(McpServer))).all())
    if servers:
        p.add(STABLE, "用户的 MCP 服务器（先 mcp_tools 再 mcp_call）：" + "、".join(servers))

    if project_id and (proj := await db.get(Project, project_id)):
        p.add(STABLE, f"当前在项目「{proj.name}」中，{workspaces.prompt_line(proj.id)}"
              + (f"\n项目规则：\n{proj.rules}" if proj.rules.strip() else ""))
        p.add(STABLE, project_brief.prompt_section(proj))
    else:
        p.add(STABLE, workspaces.prompt_line(workspaces.PERSONAL))
    # 工作区根目录的 AGENTS.md 一类规则文件（子目录的由文件工具碰到时追加）；规则在 app/workspace_instructions.py
    p.add(STABLE, workspace_instructions.baseline(workspaces.of(project_id)).text)

    # —— 以下每轮都可能变：放最后 ——
    now = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d %A %H:%M")
    p.add(VOLATILE, f"现在是 {now}（{settings.timezone}）。")
    mems = await memory_store.relevant(db, query)
    if mems:
        p.add(VOLATILE, "关于用户你已知道（# 后是引用，改/删时传给 update_memory / forget）：\n"
              + "\n".join(memory_store.context_line(m) for m in mems))
    return p


def _render(blocks: list[dict], current: bool = False) -> str:
    """把一条消息转成给模型的文本：文本附件内联内容，图片给（缓存的）描述，其他文件只给名字；
    `$技能` 点名的技能给当前正文（skill_mentions.render）；`@子助手` 当前给提示（agent_mentions）；`/init` 当前这一问换成提示词、更早的只留一句（init_command）。"""
    if (note := init_command.of(blocks)) is not None:
        said = init_command.render(note) if current else init_command.record(note)
        blocks = [{"type": "text", "text": said}, *blocks[1:]]
    text = blocks_to_text([b for b in blocks if b.get("type") not in ("file", "skill", "agent")])
    for b in blocks:
        if b.get("type") == "skill":
            text += "\n\n" + skill_mentions.render(b)
    if agent := next((b for b in blocks if b.get("type") == "agent"), None):  # `@子助手` / 追问：当前给提示、更早一句记录（agent_mentions）
        text += "\n\n" + agent_mentions.render(current, agent)
    for b in blocks:
        if b.get("type") != "file":
            continue
        if vision.is_image(b):
            text += "\n\n" + vision.placeholder(b)
            continue
        if b.get("source") == "project":
            text += "\n\n" + _project_ref(b)
            continue
        path = upload_path(b["id"]) if b.get("source") == "upload" else None
        if path and is_text(b["name"]):
            body = path.read_text(encoding="utf-8", errors="replace")[:ATTACH_CHARS]
            text += f"\n\n[附件 {b['name']}]\n{body}"
        else:
            text += f"\n\n[附件 {b['name']}（{b.get('mime')}，{b.get('size', 0)} B，暂不能读取内容）]"
    return text


async def render_now(blocks: list[dict], model: str | None = None) -> str | list[dict]:
    """一条“当前这一问”给模型的内容（回答途中补充带附件时用，steering）：和 build_history 对当前这一问的处理一致——
    能看图的模型给文字 + 原图，不能看图的先补描述（缓存）再给文字。"""
    pixels = vision.accepts_images(model or settings.default_model)
    if not pixels and any(vision.is_image(b) for b in blocks):
        await vision.describe_missing(blocks)
    text = _render(blocks, current=True)
    return vision.content_with_images(text, blocks) if pixels else text


def _project_ref(b: dict) -> str:
    """用户在消息里点名的项目文件：按当前磁盘内容给（文本内联到 ATTACH_CHARS，其余提示用文件工具）。"""
    rel, ws = b.get("id", ""), b.get("project_id") or ""
    what = "个人工作区文件" if workspaces.is_personal(ws) else "项目文件"
    path = project_file(ws, rel)
    if path is None:
        return f"[用户引用的{what} {rel}（已不在工作区里）]"
    if is_text(path.name):
        body = path.read_text(encoding="utf-8", errors="replace")
        more = "\n…（后面还有，需要时用 read_file 读全文）" if len(body) > ATTACH_CHARS else ""
        return f"[用户引用的{what} {rel}]\n{body[:ATTACH_CHARS]}{more}"
    kind = "图片" if b.get("mime", "").startswith("image/") else b.get("mime")
    return f"[用户引用的{what} {rel}（{kind}，{path.stat().st_size} B）——要看内容用 read_file]"


@dataclass
class History:
    """模型看到的对话：summary = 更早内容的滚动摘要（放进系统提示），messages = 最近的原文。"""
    summary: str
    messages: list[dict]


def _window_start(sizes: list[int], budget: int, floor: int) -> int:
    """从末尾往前装原文，装不下为止；返回第一条原文的下标。至少从 floor 开始（不早于它就够了）。"""
    total, k = 0, len(sizes)
    while k > 0 and total + sizes[k - 1] <= budget:
        k -= 1
        total += sizes[k]
    return min(k, floor)


SUMMARY_PROMPT = (
    "你在给一段长对话做滚动摘要，供助手以后接着聊时参考。把【已有摘要】和【新增对话】合并成一份新摘要：\n"
    "保留用户的目标、做过的决定、给出的事实与偏好、未完成的事项、关键数字/名称/链接；去掉寒暄和重复。\n"
    "用第三人称、要点式中文，不超过 800 字。只输出摘要本身。"
)


async def _fold(previous: str, rows: list[tuple[str, str]]) -> str:
    convo = "\n\n".join(f"{'用户' if role == 'user' else '助手'}：{text[:SUMMARY_MSG_CHARS]}" for role, text in rows)
    return await llm.complete([
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": f"【已有摘要】\n{previous or '（无）'}\n\n【新增对话】\n{convo}"},
    ], model=settings.summary_model)


@dataclass
class _Snapshot:
    """一个对话此刻的历史视图（build_history / context_state / compact_now 共用，规则只写一处）。"""
    conv: Conversation | None
    ids: list[str]
    roles: list[str]
    blocks: list[list[dict]]
    notes: list[str]
    texts: list[str]   # 给模型 / 摘要的文本：助手回复附一行工具摘要（tool_trace.digest）
    plain: list[str]   # 同上但不带工具摘要：重放完整轨迹的回复用它（摘要和轨迹不重复）
    digests: list[str]  # 每条的工具摘要行（用户消息为空）
    traces: list[list[dict]]  # 能重放的工具轨迹（只有最近 history_trace_turns 条带轨迹的回复非空）
    last_user: int
    summary: str
    covered: int  # 摘要已覆盖前多少条
    stale: bool   # 摘要指向的消息没了（被重答删掉）：作废
    skip: list[bool]  # 不单独给模型的消息（用户命令 “!ls” 本身：已并进后面那条结果记录）


async def _snapshot(db: AsyncSession, conversation_id: str) -> _Snapshot:
    conv = await db.get(Conversation, conversation_id)
    rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                             .order_by(Message.created_at))).all()
    shells = [user_shell.reply_block(m.blocks) if m.role == "assistant" else None for m in rows]
    notes = [turn_journal.history_note(m.status, m.steps) if m.role == "assistant" and not shells[i] else ""
             for i, m in enumerate(rows)]  # 被打断/停下的回复附说明
    last_user = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].role == "user"), len(rows) - 1)
    plain = [_render(m.blocks, i == last_user) + notes[i] for i, m in enumerate(rows)]
    roles = [m.role for m in rows]
    skip = [False] * len(rows)
    for i, b in enumerate(shells):  # 用户自己跑的命令（!命令）：命令 + 结果合成一条“用户那边发生的事”（Codex <user_shell_command>）
        if b is None:
            continue
        plain[i], roles[i] = user_shell.record(b), "user"
        if i > 0 and rows[i - 1].role == "user" and user_shell.command_of(rows[i - 1].blocks):
            plain[i - 1], skip[i - 1] = "", True  # 那条 “!ls” 本身不再单独给模型
    digests = [tool_trace.digest(m.steps) if m.role == "assistant" else "" for m in rows]
    texts = [p + d for p, d in zip(plain, digests)]
    traces = _traces(rows)
    ids = [m.id for m in rows]  # 先取出来：失败时 rollback 会让 ORM 对象过期
    summary = conv.summary if conv else ""
    upto = conv.summary_upto if conv else None
    covered = ids.index(upto) + 1 if upto in ids else 0
    return _Snapshot(conv, ids, roles, [m.blocks for m in rows], notes, texts, plain, digests, traces, last_user,
                     summary if covered else "", covered, bool(upto) and covered == 0, skip)


def _traces(rows) -> list[list[dict]]:
    """从后往前，最近 history_trace_turns 条带合法轨迹的助手回复保留轨迹（Codex：工具调用留在历史里），其余为空。"""
    out: list[list[dict]] = [[] for _ in rows]
    left = settings.history_trace_turns
    for i in range(len(rows) - 1, -1, -1):
        if left <= 0:
            break
        m = rows[i]
        if m.role == "assistant" and tool_trace.valid(m.trace):
            out[i] = m.trace
            left -= 1
    return out


def _sizes(snap: "_Snapshot") -> list[int]:
    """每条消息重放时占多少字：带轨迹的按 正文 + 轨迹 算，其余按 texts 算。"""
    return [len(snap.plain[i]) + tool_trace.size(t) if t else len(snap.texts[i]) for i, t in enumerate(snap.traces)]


async def build_history(db: AsyncSession, conversation_id: str, model: str | None = None) -> History:
    """预算内的最近原文 + 更早内容的摘要。model = 这一轮用的别名（决定当前这一问的图片发原图还是发描述）。

    不变式：最后一条用户消息（当前这一问）及其后的内容永远是原文，所以重答/编辑只动原文区，摘要不受影响。
    原文超预算时，把摘要之后、窗口之前的消息折叠进摘要（压到 FOLD_TARGET，留余量），用便宜模型一次调用。
    摘要失败不影响聊天：退化为按预算硬截断，下一轮再试。"""
    snap = await _snapshot(db, conversation_id)
    conv, ids, roles, blocks, notes, texts = snap.conv, snap.ids, snap.roles, snap.blocks, snap.notes, snap.texts
    last_user, summary, covered = snap.last_user, snap.summary, snap.covered
    sizes = _sizes(snap)
    budget = settings.history_chars

    start = _window_start(sizes, budget, last_user)
    if start > covered and conv is not None:  # 摘要和原文窗口之间有缺口：折叠
        target = max(start, _window_start(sizes, int(budget * FOLD_TARGET), last_user))
        try:
            summary = await _fold(summary, [(roles[i], texts[i]) for i in range(covered, target) if not snap.skip[i]])
            conv.summary, conv.summary_upto = summary, ids[target - 1]
            await db.commit()
            covered = target
        except Exception as e:  # noqa: BLE001 — 摘要只是省钱/保连贯，不能拖垮这一轮
            log.warning("summary fold failed for %s: %s", conversation_id, e)
            await db.rollback()
            covered = start
    elif conv is not None and snap.stale:
        conv.summary, conv.summary_upto = "", None
        await db.commit()
    first = max(start, covered)

    # 图片：当前这一问且模型能看图 → 原图；其余（更早的、或模型不能看图）→ 文字描述（缺的现在补，之后走缓存）
    pixels = vision.accepts_images(model or settings.default_model)
    def raw(i: int) -> bool:
        return pixels and i >= last_user and roles[i] == "user"
    n = len(ids)
    need = [b for i in range(first, n) if not raw(i) for b in blocks[i]]
    plain, traces = snap.plain, snap.traces
    if any(vision.is_image(b) for b in need):
        await vision.describe_missing(need)
        for i in range(first, n):
            plain[i] = _render(blocks[i], i == last_user) + notes[i]
            texts[i] = plain[i] + snap.digests[i]
    out: list[dict] = []
    for i in range(first, n):
        if snap.skip[i]:
            continue
        if traces[i]:  # 最近几条回复：工具调用 + 结果原样放回，接着是回复文字
            out += tool_trace.replay(traces[i], plain[i])
        else:
            out.append({"role": roles[i], "content": vision.content_with_images(texts[i], blocks[i]) if raw(i) else texts[i]})
    return History(summary=summary, messages=out)


# —— 手动整理上文（Codex /compact、Gemini /compress 的对应物；嫁接 Gemini compressCommand：忙时拒绝、报前后大小、
#    摘要反而更长（INFLATED）就不换）。和自动折叠同一份摘要、同一个不变式：当前这一问及其后永远是原文。 ——

class CompactBusy(Exception):
    """这个对话正在回复：等这一轮结束再整理（否则这一轮的历史和摘要会对不上）。"""


def _state(snap: _Snapshot) -> dict:
    """对话记忆的现状：下一轮发给模型的原文有多大、多少条已压成摘要、还能不能手动整理。"""
    sizes = _sizes(snap)
    covered = snap.covered
    budget = settings.history_chars
    first = max(_window_start(sizes, budget, snap.last_user), covered)
    return {
        "messages": len(snap.ids),
        "summarized": covered,
        "raw": len(snap.ids) - first,
        "raw_chars": sum(sizes[first:]),
        "budget": budget,
        "summary": snap.summary,
        "compactable": max(0, snap.last_user - covered),
        # 工作区根目录的规则文件（每轮都进系统提示）：客户端在“对话记忆”里列出来
        "instructions": workspace_instructions.summary(workspaces.of(snap.conv.project_id if snap.conv else None)),
    }


async def context_state(db: AsyncSession, conversation_id: str) -> dict:
    return _state(await _snapshot(db, conversation_id))


async def compact_now(db: AsyncSession, conversation_id: str) -> dict:
    """把摘要之后、最后一问之前的原文全部并进滚动摘要。返回 {**state, "status", "before", "after"}：
    status = compressed | noop（没什么可整理）| inflated（摘要比原文还长，没换）；before/after = 原文 + 摘要的字数。
    正在回复 → CompactBusy；摘要模型出错 → 原样抛出（摘要和原文都不动）。"""
    if await turn_journal.busy(db, conversation_id):
        raise CompactBusy()
    snap = await _snapshot(db, conversation_id)
    if snap.conv is None:
        raise LookupError(conversation_id)
    before = len(snap.summary) + sum(len(t) for t in snap.texts[snap.covered:])
    target = snap.last_user
    if target - snap.covered < 1:
        return {**_state(snap), "status": "noop", "before": before, "after": before}
    folded = snap.texts[snap.covered:target]
    summary = await _fold(snap.summary, [(snap.roles[i], snap.texts[i]) for i in range(snap.covered, target) if not snap.skip[i]])
    if len(summary) >= len(snap.summary) + sum(len(t) for t in folded):
        return {**_state(snap), "status": "inflated", "before": before, "after": before}
    snap.conv.summary, snap.conv.summary_upto = summary, snap.ids[target - 1]
    await db.commit()
    snap = await _snapshot(db, conversation_id)
    after = len(snap.summary) + sum(len(t) for t in snap.texts[snap.covered:])
    return {**_state(snap), "status": "compressed", "before": before, "after": after}
