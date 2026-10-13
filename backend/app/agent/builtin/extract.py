"""结构化提取：从一段文字 / 工作区文件 / 网页 / 这段对话里，按 JSON Schema 抽出数据（规则全在 app/extract.py）。
用便宜模型做（EXTRACT_MODEL，空 = summary_model），原文不进主助手的上下文：长网页、PDF、日志里抽表格最省 token。"""
import asyncio
import json

from sqlalchemy import select

from ... import documents, extract, file_seen, llm, web_page
from ...blocks import blocks_to_text
from ...config import settings
from ...db import SessionLocal
from ...models import Message
from ...storage import looks_text, mime_of, project_dir, safe_join
from ..tools import ToolContext, ToolResult, tool

FILE_MAX = web_page.MAX_BYTES


def _fail(why: str) -> ToolResult:
    return ToolResult(f"没提取：{why}", failed=why)


def _file_text(ctx: ToolContext, path: str) -> tuple[str, str]:
    """(正文, 来源名)。PDF / Office 走 documents（同 read_file，前 50 页），HTML / JSON 走 web_page.to_text，其它文本原样；二进制拒绝。"""
    p = safe_join(project_dir(ctx.workspace), path)
    file_seen.observe(file_seen.owner_of(ctx.conversation_id, ctx.task_id), p)  # 读过：之后 save_to 覆盖它才被允许
    if not p.is_file():
        raise extract.ExtractError(f"{path} 不存在。")
    size = p.stat().st_size
    cap = documents.FILE_MAX if documents.kind_of(p.name) else FILE_MAX
    if size > cap:
        raise extract.ExtractError(f"{path} 太大（{size} B，上限 {cap // (1024 * 1024)} MB），先用 run_command 截出需要的部分。")
    body = p.read_bytes()
    mime = mime_of(p.name)
    if documents.kind_of(p.name, body[:8]) or documents.is_old(p.name):  # PDF / Office：同 read_file（app/documents.py）
        try:
            doc = documents.read(body, p.name)
        except documents.DocError as e:
            raise extract.ExtractError(str(e)) from e
        if not doc.text:
            raise extract.ExtractError(doc.header(path))
        return doc.text, documents.LABEL[doc.kind]
    if mime in ("application/pdf", "text/html", "application/json") or body[:5] == b"%PDF-":
        try:
            kind, text, _ = web_page.to_text(body, mime, p.name)
        except web_page.FetchError as e:
            raise extract.ExtractError(str(e)) from e
        if kind == "binary":
            raise extract.ExtractError(f"{path} 不是文字文件。")
        return text, {"pdf": "PDF", "html": "网页文件", "json": "JSON 文件"}.get(kind, "文件")
    if not looks_text(p):
        raise extract.ExtractError(f"{path} 不是文本文件（{size} B），先用 run_command 转成文字。")
    return body.decode("utf-8", errors="replace"), "文件"


async def _conversation_text(cid: str | None) -> str:
    """这段对话到目前为止的文字（用户 / 助手交替）。并行工具不能共用 ctx.db，自己开一个会话。"""
    if not cid:
        raise extract.ExtractError("现在不在一段对话里，没有对话内容可提取。")
    async with SessionLocal() as db:
        rows = (await db.execute(select(Message.role, Message.blocks).where(Message.conversation_id == cid)
                                 .order_by(Message.created_at))).all()
    lines = [f"{'用户' if r == 'user' else '助手'}：{t}" for r, b in rows if (t := blocks_to_text(b or []).strip())]
    return "\n\n".join(lines)


async def _source(ctx: ToolContext, text: str, path: str, url: str, conversation: bool,
                  max_age: int | None) -> tuple[str, str]:
    given = [n for n, v in (("text", text.strip()), ("path", path.strip()), ("url", url.strip()),
                            ("conversation", conversation)) if v]
    if len(given) != 1:
        raise extract.ExtractError("text、path、url、conversation 四个来源只能给一个（现在给了 "
                                   f"{len(given)} 个）。")
    if text.strip():
        return text, "文字"
    if path.strip():
        return await asyncio.to_thread(_file_text, ctx, path.strip())
    if url.strip():
        try:
            page = await web_page.fetch(url, max_age=max_age, limit=extract.SOURCE_MAX)
        except web_page.FetchError as e:
            raise extract.ExtractError(str(e)) from e
        if page.status >= 400:
            raise extract.ExtractError(f"网页返回 HTTP {page.status}，没有可提取的正文。")
        if page.kind == "binary":
            raise extract.ExtractError(page.text)
        return page.text, {"pdf": "PDF", "json": "JSON"}.get(page.kind, "网页")
    return await _conversation_text(ctx.conversation_id), "这段对话"


async def _call(messages: list[dict]) -> str:
    return await llm.complete(messages, model=settings.extract_model or settings.summary_model, kind="extract",
                              max_tokens=extract.OUTPUT_TOKENS)


@tool("extract_data", "正在提取数据",
      "按 JSON Schema 从一段文字、工作区文件（txt/csv/日志/PDF/HTML）、网页或这段对话里抽出结构化数据，"
      "保证交回的 JSON 合法并符合 schema（不符合会自动带着错误重抽）。原文由便宜模型读，不进你的上下文："
      "长网页 / PDF / 日志里抽表格、联系人、价格、订单、日期时用它，比 read_file 全文再自己整理省很多 token。"
      "四个来源（text / path / url / conversation）只给一个。schema 根 type 用 object 或 array；"
      "要落盘给脚本用就给 save_to（.json 路径，覆盖已有文件前要先 read_file 过）。",
      {"type": "object", "properties": {
          "instruction": {"type": "string", "description": "要抽什么、有什么讲究，如“每个商品的名称、价格（元）和库存”"},
          "schema": {"type": "object", "description": "输出的 JSON Schema（draft-07；$schema 写 2020-12 则按 2020-12）"},
          "text": {"type": "string", "description": "直接给原文"},
          "path": {"type": "string", "description": "工作区里的文件路径"},
          "url": {"type": "string", "description": "网页 / PDF 地址"},
          "conversation": {"type": "boolean", "description": "从这段对话的内容里抽"},
          "save_to": {"type": "string", "description": "把结果（缩进 JSON）存到工作区这个路径"},
          "max_age_seconds": {"type": "integer", "minimum": 0, "description": "url 来源能接受多旧的缓存（秒）"}},
       "required": ["instruction", "schema"]}, parallel=lambda a: not a.get("save_to"), deferred=True)  # 要落盘就不和别的工具并行（同 write_file）
async def extract_data(ctx: ToolContext, instruction: str, schema, text: str = "", path: str = "", url: str = "",
                       conversation: bool = False, save_to: str = "", max_age_seconds: int | None = None) -> ToolResult:
    try:
        extract.check_schema(schema)  # 先查 schema，免得白读一遍网页
        source, label = await _source(ctx, text or "", path or "", url or "", bool(conversation), max_age_seconds)
        res = await extract.run(source, instruction, schema, _call)
    except extract.ExtractError as e:
        return _fail(str(e))
    out = ToolResult(extract.for_model(res), detail=extract.detail(res, label),
                     failed="" if res.value is not None else "没拿到合法 JSON")
    if save_to.strip() and res.value is not None:
        from .workspace import write_file  # 落盘走 write_file 的同一套规则（读过才许覆盖、配额、改动卡）
        w = await write_file(ctx, save_to.strip(), json.dumps(res.value, ensure_ascii=False, indent=2) + "\n")
        out.content += f"\n\n{'已存到 ' + save_to.strip() if not w.failed else '没存成：' + w.content}"
        out.change = w.change
    return out
