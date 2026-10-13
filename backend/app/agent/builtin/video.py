"""视频字幕工具：analyze_video 读一个 YouTube / B 站视频的字幕，search_transcript 在读过的字幕里找。
规则在 app/video_transcript.py，联网在 app/video_sources.py。只读、可并行——所以不碰 ctx.db（共用的会话不能并发），
每次自己开一个短会话存取字幕。"""
from ... import video_sources, video_transcript as vt
from ...db import SessionLocal
from ..tools import ToolContext, ToolResult, tool

_LANGS = {"type": "array", "items": {"type": "string"},
          "description": "想要的字幕语言代码，按偏好排（如 [\"zh-Hans\", \"en\"]）；不填 = 中文优先，其次英文，再其次随便哪条"}


def _fail(e: vt.VideoError) -> ToolResult:
    return ToolResult(f"没读成：{e}", failed=str(e).split("。")[0][:80])


@tool("analyze_video", "正在读视频字幕",
      "读一个公开视频（YouTube、B 站，含 youtu.be / shorts / b23.tv 短链）的字幕，用来总结、回答视频里讲了什么、"
      "找某句话在几分几秒。短视频直接给带时间点的全文；长视频给分段摘录和编号，细节再用 search_transcript 查。"
      "同一段对话里读过的视频不会重新联网。没有字幕的视频读不了（会给你视频描述）。",
      {"type": "object", "properties": {"url": {"type": "string", "description": "视频页链接"}, "languages": _LANGS},
       "required": ["url"]}, parallel=True, deferred=True)
async def analyze_video(ctx: ToolContext, url: str, languages: list[str] | None = None) -> ToolResult:
    video = vt.parse(url)
    if video is None:
        return ToolResult("认不出这个视频链接。只支持 YouTube（watch / youtu.be / shorts / live）和 B 站（BV / av / b23.tv）。"
                          "别的网页用 web_fetch 或 browser_open。", failed="不是支持的视频链接")
    langs = [x for x in (languages or []) if isinstance(x, str)] or None
    t = None
    if video.platform != "b23":
        async with SessionLocal() as db:
            t = await vt.find(db, ctx.conversation_id, video.url, langs)
    if t is None:
        try:
            t = await video_sources.fetch(video, langs)
        except vt.VideoError as e:
            return _fail(e)
        async with SessionLocal() as db:
            t = await vt.save(db, ctx.conversation_id, t)
    return ToolResult(vt.for_model(t), detail=f"{t.title or t.video.id} · {vt.ts(t.duration)}")


@tool("search_transcript", "正在查视频字幕",
      "在这段对话里 analyze_video 读过的视频字幕里查：给 query 按关键词找（多个词空格隔开，命中多的在前，带前后文和时间点链接），"
      "或给 start / end（分:秒 或秒数）按时间读一段。总结长视频的某一部分、核对原话时用。",
      {"type": "object", "properties": {
          "video": {"type": "string", "description": "analyze_video 给的编号（vt_xxxxxx），或者视频链接"},
          "query": {"type": "string", "description": "关键词；整句用引号括起来"},
          "start": {"type": "string", "description": "从哪个时间点读，如 12:30"},
          "end": {"type": "string", "description": "读到哪个时间点（不含），如 15:00"}},
       "required": ["video"]}, parallel=True, deferred=True)
async def search_transcript(ctx: ToolContext, video: str, query: str = "", start: str = "",
                            end: str = "") -> ToolResult:
    async with SessionLocal() as db:
        t = await vt.find(db, ctx.conversation_id, video)
    if t is None:
        return ToolResult("这段对话里还没读过这个视频的字幕，先用 analyze_video 读一次（给链接）。", failed="没读过这个视频")
    try:
        lo, hi = vt.parse_ts(start), vt.parse_ts(end)
        if query.strip():
            hits, total = vt.search(t, query)
            if not hits:
                return ToolResult(f"《{t.title}》的字幕里没有“{query}”。换个说法（字幕可能是自动识别的，同音字多），"
                                  "或者按时间读一段。", detail=f"{query} · 0 处")
            body = "\n\n".join(f"[{vt.ts(a)}] {b}\n{t.video.link(a)}" for a, b in hits)
            more = f"（共 {total} 句命中，这里列最相关的 {len(hits)} 处）" if total > len(hits) else ""
            return ToolResult(f"《{t.title}》里找到 {len(hits)} 处{more}：\n\n{body}", detail=f"{query} · {len(hits)} 处")
        if lo is None and hi is None:
            return ToolResult("给 query 关键词，或者给 start / end 时间段。", failed="没给要查什么")
        text, cut = vt.window(t, lo, hi)
    except vt.VideoError as e:
        return _fail(e)
    span = f"{vt.ts(lo or 0)}–{vt.ts(hi) if hi is not None else '结尾'}"
    if not text:
        return ToolResult(f"《{t.title}》{span} 这段没有字幕（视频时长 {vt.ts(t.duration)}）。", detail=span)
    tail = "\n…（这段太长，截到这里；缩小时间段再读）" if cut else ""
    return ToolResult(f"《{t.title}》{span}：\n{text}{tail}", detail=span)
