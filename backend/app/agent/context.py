"""组装模型看到的一切：系统提示（人设 + 记忆 + 技能目录 + 项目规则）和对话历史。
这是控制 token 成本的唯一阀门。"""
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm, memory_store, project_brief, skills_store, vision
from ..blocks import blocks_to_text
from ..config import settings
from ..connectors.providers import PROVIDERS
from ..models import Connection, Conversation, McpServer, Message, Project, Secret
from ..storage import is_text, upload_path

ATTACH_CHARS = 6000     # 每个文本附件最多带多少字给模型
FOLD_TARGET = 0.5       # 需要折叠时，把原文压到预算的这个比例：留出余量，不必每轮都调一次摘要
SUMMARY_MSG_CHARS = 3000  # 喂给摘要模型的每条旧消息最多多少字（控制摘要本身的成本）

log = logging.getLogger(__name__)


async def build_system_prompt(db: AsyncSession, project_id: str | None, query: str = "") -> str:
    """query：用户最新一句话，用来挑相关记忆。"""
    now = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d %A %H:%M")
    parts = [settings.system_prompt, f"现在是 {now}（{settings.timezone}）。"]

    mems = await memory_store.relevant(db, query)
    if mems:
        parts.append("关于用户你已知道（# 后是引用，改/删时传给 update_memory / forget）：\n"
                     + "\n".join(memory_store.context_line(m) for m in mems))

    skills = skills_store.enabled_skills()
    if skills:  # 只放启用的目录，正文按需 use_skill 读取
        parts.append("可用技能：\n" + "\n".join(f"- {s.id}：{s.name}——{s.description}" for s in skills))

    # 只告诉模型“能调哪些服务”，不给任何凭证内容
    access = [f"- {PROVIDERS[c.provider].name}（{c.account}）：{', '.join(PROVIDERS[c.provider].api_hosts)}"
              for c in (await db.scalars(select(Connection))).all() if c.provider in PROVIDERS]
    access += [f"- {s.name}：{', '.join(s.hosts)}" for s in (await db.scalars(select(Secret))).all()]
    if access:
        parts.append("这些服务已授权，用 api_request 直接调用（认证自动附加；具体用法先看对应技能）：\n" + "\n".join(access))
    servers = (await db.scalars(select(McpServer))).all()
    if servers:
        parts.append("用户的 MCP 服务器（先 mcp_tools 再 mcp_call）：" + "、".join(s.name for s in servers))

    if project_id and (p := await db.get(Project, project_id)):
        parts.append(f"当前在项目「{p.name}」中，可以用文件工具和 run_command 操作项目工作区。"
                     + (f"\n项目规则：\n{p.rules}" if p.rules.strip() else ""))
        parts.append(project_brief.prompt_section(p))
    return "\n\n".join(parts)


def _render(blocks: list[dict]) -> str:
    """把一条消息转成给模型的文本：文本附件内联内容，图片给（缓存的）描述，其他文件只给名字。"""
    text = blocks_to_text([b for b in blocks if b.get("type") != "file"])
    for b in blocks:
        if b.get("type") != "file":
            continue
        if vision.is_image(b):
            text += "\n\n" + vision.placeholder(b)
            continue
        path = upload_path(b["id"]) if b.get("source") == "upload" else None
        if path and is_text(b["name"]):
            body = path.read_text(encoding="utf-8", errors="replace")[:ATTACH_CHARS]
            text += f"\n\n[附件 {b['name']}]\n{body}"
        else:
            text += f"\n\n[附件 {b['name']}（{b.get('mime')}，{b.get('size', 0)} B，暂不能读取内容）]"
    return text


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


async def build_history(db: AsyncSession, conversation_id: str, model: str | None = None) -> History:
    """预算内的最近原文 + 更早内容的摘要。model = 这一轮用的别名（决定当前这一问的图片发原图还是发描述）。

    不变式：最后一条用户消息（当前这一问）及其后的内容永远是原文，所以重答/编辑只动原文区，摘要不受影响。
    原文超预算时，把摘要之后、窗口之前的消息折叠进摘要（压到 FOLD_TARGET，留余量），用便宜模型一次调用。
    摘要失败不影响聊天：退化为按预算硬截断，下一轮再试。"""
    conv = await db.get(Conversation, conversation_id)
    rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                             .order_by(Message.created_at))).all()
    texts = [_render(m.blocks) for m in rows]
    sizes = [len(t) for t in texts]
    last_user = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].role == "user"), len(rows) - 1)
    budget = settings.history_chars

    ids, roles = [m.id for m in rows], [m.role for m in rows]  # 先取出来：失败时 rollback 会让 ORM 对象过期
    blocks = [m.blocks for m in rows]
    summary = conv.summary if conv else ""
    upto = conv.summary_upto if conv else None
    covered = ids.index(upto) + 1 if upto in ids else 0
    if covered == 0:
        summary = ""  # 指向的消息没了：作废

    start = _window_start(sizes, budget, last_user)
    if start > covered and conv is not None:  # 摘要和原文窗口之间有缺口：折叠
        target = max(start, _window_start(sizes, int(budget * FOLD_TARGET), last_user))
        try:
            summary = await _fold(summary, [(roles[i], texts[i]) for i in range(covered, target)])
            conv.summary, conv.summary_upto = summary, ids[target - 1]
            await db.commit()
            covered = target
        except Exception as e:  # noqa: BLE001 — 摘要只是省钱/保连贯，不能拖垮这一轮
            log.warning("summary fold failed for %s: %s", conversation_id, e)
            await db.rollback()
            covered = start
    elif conv is not None and covered == 0 and upto:
        conv.summary, conv.summary_upto = "", None
        await db.commit()
    first = max(start, covered)

    # 图片：当前这一问且模型能看图 → 原图；其余（更早的、或模型不能看图）→ 文字描述（缺的现在补，之后走缓存）
    pixels = vision.accepts_images(model or settings.default_model)
    def raw(i: int) -> bool:
        return pixels and i >= last_user and roles[i] == "user"
    need = [b for i in range(first, len(rows)) if not raw(i) for b in blocks[i]]
    if any(vision.is_image(b) for b in need):
        await vision.describe_missing(need)
        texts[first:] = [_render(blocks[i]) for i in range(first, len(rows))]
    return History(summary=summary, messages=[
        {"role": roles[i], "content": vision.content_with_images(texts[i], blocks[i]) if raw(i) else texts[i]}
        for i in range(first, len(rows))])
