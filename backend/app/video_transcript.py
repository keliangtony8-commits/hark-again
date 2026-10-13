"""视频字幕（v2.03，唯一规则）：哪些链接算视频、选哪条字幕、给模型看多少、怎么在字幕里找、存在哪。

联网取字幕在 app/video_sources.py；这里不碰网络。字幕按对话存（video_transcripts 表），同一段对话里
analyze_video 读过的视频，search_transcript 可以按编号（vt_xxxxxx）或原链接再查，不再联网、不重付全文 token。
"""
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import delete, select

from .models import VideoTranscript

INLINE_MAX = 12000     # 全文不超过这么多字就整份给模型；超了只给分段摘录 + 让它按需搜
PARA_S = 30            # 全文按多少秒一段（每段一个时间点）
WINDOWS = 16           # 长字幕摘录分几段
WINDOW_CHARS = 300     # 每段摘录多少字
HITS_MAX = 12          # 一次搜索最多回几处
RANGE_MAX = 8000       # 按时间读一段最多多少字
SEGMENTS_MAX = 20000   # 一条字幕最多存多少句
STORE_MAX = 400_000    # 一条字幕最多存多少字
KEEP = 20              # 每段对话最多留几条字幕（最旧的先丢）
DEFAULT_LANGS = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "zh-HK", "en", "en-US", "en-GB")

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
             "youtube-nocookie.com", "www.youtube-nocookie.com"}
_BV = re.compile(r"^(BV[0-9A-Za-z]{10})$")
_AV = re.compile(r"^av(\d{1,12})$", re.I)
_REF = re.compile(r"^vt_[0-9a-f]{6}$")


class VideoError(Exception):
    """给模型看的中文原因。"""


@dataclass(frozen=True)
class Video:
    platform: str        # youtube | bilibili | b23（短链，取字幕前先解开）
    id: str              # YouTube 11 位 id；B 站 BV… 或 av123；b23 短码
    page: int = 1        # B 站分 P

    @property
    def url(self) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/watch?v={self.id}"
        if self.platform == "bilibili":
            return f"https://www.bilibili.com/video/{self.id}" + (f"?p={self.page}" if self.page > 1 else "")
        return f"https://b23.tv/{self.id}"

    def link(self, seconds: float) -> str:
        """跳到某个时间点的链接（给用户引用时间点用）。"""
        t = max(0, int(seconds))
        if self.platform == "youtube":
            return f"https://youtu.be/{self.id}?t={t}"
        if self.platform == "bilibili":
            return f"https://www.bilibili.com/video/{self.id}?" + (f"p={self.page}&" if self.page > 1 else "") + f"t={t}"
        return self.url


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Track:
    """一条可选字幕（取之前）。"""
    language: str        # 语言代码（zh-Hans / en / ai-zh …）
    name: str            # 显示名（中文（简体）/ English (auto-generated)）
    generated: bool      # 自动生成（YouTube asr / B 站 AI 字幕）
    url: str


@dataclass
class Transcript:
    video: Video
    title: str
    author: str
    duration: float
    language: str
    language_name: str
    generated: bool
    segments: list[Segment]
    available: list[str] = field(default_factory=list)   # 其他可选字幕的显示名
    ref: str = ""        # 存库后的编号 vt_xxxxxx


def parse(url: str) -> Video | None:
    """一个链接是不是我们认得的视频页。认不出 → None（不是视频 / 不支持的平台）。"""
    u = (url or "").strip()
    if not u:
        return None
    if "://" not in u:
        u = "https://" + u
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    parts = [x for x in p.path.split("/") if x]
    q = parse_qs(p.query)
    if host in _YT_HOSTS:
        vid = ""
        if parts[:1] == ["watch"]:
            vid = (q.get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v", "e"):
            vid = parts[1]
        return Video("youtube", vid) if _YT_ID.match(vid) else None
    if host == "youtu.be":
        vid = parts[0] if parts else ""
        return Video("youtube", vid) if _YT_ID.match(vid) else None
    if host in ("bilibili.com", "www.bilibili.com", "m.bilibili.com"):
        if len(parts) >= 2 and parts[0] == "video":
            vid = parts[1]
            page = _page((q.get("p") or ["1"])[0])
            if _BV.match(vid):
                return Video("bilibili", vid, page)
            m = _AV.match(vid)
            if m:
                return Video("bilibili", f"av{m.group(1)}", page)
        return None
    if host == "b23.tv" and parts and re.fullmatch(r"[0-9A-Za-z]{4,16}", parts[0]):
        return Video("b23", parts[0])
    return None


def _page(v: str) -> int:
    try:
        n = int(v)
    except ValueError:
        return 1
    return n if 1 <= n <= 1000 else 1


def pick(tracks: list[Track], languages: list[str] | None = None) -> Track | None:
    """选哪条字幕（移植 youtube-transcript-api TranscriptList.find_transcript）：按语言偏好顺序，同一语言人工字幕
    优先于自动生成；偏好里一个都没有 → 任一人工字幕 → 任一自动字幕。语言比较不分大小写，B 站 ai-zh 当 zh。"""
    if not tracks:
        return None
    prefs = [x.strip().lower() for x in (languages or []) if x and x.strip()] or [x.lower() for x in DEFAULT_LANGS]

    def code(t: Track) -> str:
        c = t.language.lower()
        return c[3:] if c.startswith("ai-") else c

    for want in prefs:
        for generated in (False, True):
            for t in tracks:
                if t.generated == generated and code(t) == want:
                    return t
        for generated in (False, True):   # zh 也认 zh-CN；en 也认 en-US
            for t in tracks:
                if t.generated == generated and code(t).split("-")[0] == want.split("-")[0] and "-" not in want:
                    return t
    for generated in (False, True):
        for t in tracks:
            if t.generated == generated:
                return t
    return tracks[0]


def tidy(segments: list[Segment]) -> list[Segment]:
    """去空句、压空白、按开始时间排；条数和总字数都封顶。"""
    out, total = [], 0
    for s in sorted(segments, key=lambda x: x.start):
        text = re.sub(r"\s+", " ", s.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(s.start))
        end = max(start, float(s.end))
        total += len(text)
        if len(out) >= SEGMENTS_MAX or total > STORE_MAX:
            break
        out.append(Segment(start, end, text))
    return out


def ts(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_ts(v) -> float | None:
    """'1:02:03' / '5:30' / '90' / 90 → 秒；空 → None；写错 → VideoError。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise VideoError("时间点要写成 分:秒（如 5:30）或秒数。")
    if isinstance(v, (int, float)):
        if v < 0:
            raise VideoError("时间点不能是负数。")
        return float(v)
    s = str(v).strip().replace("：", ":")
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", s):
        raise VideoError(f"认不出时间点“{v}”，写成 分:秒（如 5:30）、时:分:秒 或秒数。")
    total = 0.0
    for x in s.split(":"):
        total = total * 60 + float(x)
    return total


def text_len(t: Transcript) -> int:
    return sum(len(s.text) for s in t.segments)


def paragraphs(segments: list[Segment], every: float = PARA_S) -> list[tuple[float, str]]:
    """按时间每 every 秒合成一段：[(段首时间, 文字)]。中文句子之间不加空格。"""
    out: list[tuple[float, list[str]]] = []
    for s in segments:
        if not out or s.start - out[-1][0] >= every:
            out.append((s.start, [s.text]))
        else:
            out[-1][1].append(s.text)
    return [(start, _join(texts)) for start, texts in out]


def _join(texts: list[str]) -> str:
    buf = ""
    for t in texts:
        if buf and not (_cjk(buf[-1]) and _cjk(t[0])):
            buf += " "
        buf += t
    return buf


def _cjk(ch: str) -> bool:
    return "\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef"


def header(t: Transcript) -> str:
    kind = "自动生成" if t.generated else "人工字幕"
    head = f"《{t.title or '（无标题）'}》"
    if t.author:
        head += f" — {t.author}"
    bits = [f"时长 {ts(t.duration)}" if t.duration else "", f"字幕：{t.language_name or t.language}（{kind}）",
            f"编号 {t.ref}" if t.ref else ""]
    line = head + " · " + " · ".join(b for b in bits if b)
    if t.available:
        line += "\n其他字幕：" + "、".join(t.available[:8])
    line += f"\n链接：{t.video.url}；引用时间点给用户时用 {t.video.link(0).rsplit('t=', 1)[0]}t=<秒数>"
    return line


def for_model(t: Transcript) -> str:
    """analyze_video 的结果：短字幕给全文（带时间点），长字幕给均匀分段摘录 + 怎么继续查。"""
    paras = paragraphs(t.segments)
    full = "\n".join(f"[{ts(a)}] {b}" for a, b in paras)
    if len(full) <= INLINE_MAX:
        return header(t) + "\n\n全文：\n" + full
    end = t.segments[-1].end if t.segments else t.duration
    span = max(end, t.duration, 1.0) / WINDOWS
    lines = []
    for i in range(WINDOWS):
        lo, hi = i * span, (i + 1) * span
        seg = [s for s in t.segments if lo <= s.start < hi]
        if not seg:
            continue
        text = _join([s.text for s in seg])
        lines.append(f"[{ts(seg[0].start)}] {text[:WINDOW_CHARS]}{'…' if len(text) > WINDOW_CHARS else ''}")
    return (header(t) + f"\n\n字幕很长（约 {text_len(t)} 字），下面是按时间均匀取的 {len(lines)} 段开头。"
            f"要细节就用 search_transcript（video=\"{t.ref or t.video.url}\"）按关键词找，或给 start / end 读某一段，"
            "不要凭这些片段猜没出现的内容。\n\n" + "\n".join(lines))


def _terms(query: str) -> list[str]:
    q = (query or "").strip().lower()
    quoted = re.findall(r'"([^"]+)"|“([^”]+)”', q)
    terms = [a or b for a, b in quoted]
    q = re.sub(r'"[^"]+"|“[^”]+”', " ", q)
    terms += [x for x in re.split(r"[\s,，、]+", q) if x]
    return [x.strip() for x in terms if x.strip()]


def search(t: Transcript, query: str, limit: int = HITS_MAX) -> tuple[list[tuple[float, str]], int]:
    """按关键词找：任一词出现即算命中，命中词多的在前，同分按时间；前后各带一句上下文，相邻命中合并。
    返回 ([(时间, 带上下文的文字)], 命中总句数)。"""
    terms = _terms(query)
    if not terms:
        raise VideoError("要给关键词，或者用 start / end 按时间读一段。")
    segs = t.segments
    scored = []
    for i, s in enumerate(segs):
        low = s.text.lower()
        n = sum(1 for w in terms if w in low)
        if n:
            scored.append((-n, s.start, i))
    total = len(scored)
    scored.sort()
    picked: list[int] = []
    for _, _, i in scored:
        if any(abs(i - j) <= 2 for j in picked):
            continue
        picked.append(i)
        if len(picked) >= limit:
            break
    hits = []
    for i in sorted(picked):
        lo, hi = max(0, i - 1), min(len(segs), i + 2)
        hits.append((segs[lo].start, _join([s.text for s in segs[lo:hi]])))
    return hits, total


def window(t: Transcript, start: float | None, end: float | None) -> tuple[str, bool]:
    """按时间读一段（含 start，不含 end）；超过 RANGE_MAX 截断。返回 (带时间点的文字, 截断了)。"""
    lo = start or 0.0
    hi = end if end is not None else float("inf")
    if hi <= lo:
        raise VideoError("end 要比 start 晚。")
    seg = [s for s in t.segments if lo <= s.start < hi or (s.start < lo < s.end)]
    if not seg:
        return "", False
    text = "\n".join(f"[{ts(a)}] {b}" for a, b in paragraphs(seg))
    return text[:RANGE_MAX], len(text) > RANGE_MAX


# —— 存取 ——

def new_ref() -> str:
    return "vt_" + secrets.token_hex(3)


def _dump(segments: list[Segment]) -> str:
    return json.dumps([[round(s.start, 2), round(s.end, 2), s.text] for s in segments], ensure_ascii=False)


def _load_segments(text: str) -> list[Segment]:
    try:
        rows = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, list) and len(r) == 3 and isinstance(r[2], str):
            try:
                out.append(Segment(float(r[0]), float(r[1]), r[2]))
            except (TypeError, ValueError):
                continue
    return out


def _of(row: VideoTranscript) -> Transcript:
    try:
        available = json.loads(row.available or "[]")
    except ValueError:
        available = []
    return Transcript(video=Video(row.platform, row.video_id, row.page), title=row.title, author=row.author,
                      duration=row.duration, language=row.language, language_name=row.language_name,
                      generated=row.generated, segments=_load_segments(row.segments),
                      available=[str(x) for x in available if isinstance(x, str)], ref=row.id)


async def save(db, conversation_id: str | None, t: Transcript) -> Transcript:
    """存下（同一对话同一视频同一语言的旧记录换掉），每段对话只留最近 KEEP 条。会 commit。"""
    q = delete(VideoTranscript).where(VideoTranscript.conversation_id == conversation_id,
                                      VideoTranscript.platform == t.video.platform,
                                      VideoTranscript.video_id == t.video.id,
                                      VideoTranscript.page == t.video.page,
                                      VideoTranscript.language == t.language)
    await db.execute(q)
    row = VideoTranscript(id=new_ref(), conversation_id=conversation_id, platform=t.video.platform,
                          video_id=t.video.id, page=t.video.page, title=(t.title or "")[:200],
                          author=(t.author or "")[:100], duration=float(t.duration or 0), language=t.language[:32],
                          language_name=(t.language_name or "")[:64], generated=bool(t.generated),
                          available=json.dumps(t.available[:20], ensure_ascii=False), segments=_dump(t.segments),
                          created_at=datetime.now(timezone.utc))
    db.add(row)
    await db.flush()
    keep = (await db.execute(select(VideoTranscript.id).where(VideoTranscript.conversation_id == conversation_id)
                             .order_by(VideoTranscript.created_at.desc()).limit(KEEP))).scalars().all()
    await db.execute(delete(VideoTranscript).where(VideoTranscript.conversation_id == conversation_id,
                                                   VideoTranscript.id.not_in(keep)))
    await db.commit()
    t.ref = row.id
    return t


async def find(db, conversation_id: str | None, ref: str, languages: list[str] | None = None) -> Transcript | None:
    """按编号或链接找这段对话里存过的字幕。链接 → 同一视频最新那条（给了语言偏好就要语言对得上）。"""
    ref = (ref or "").strip()
    if _REF.match(ref):
        row = await db.get(VideoTranscript, ref)
        return _of(row) if row is not None and row.conversation_id == conversation_id else None
    v = parse(ref)
    if v is None or v.platform == "b23":
        return None
    rows = (await db.execute(select(VideoTranscript).where(
        VideoTranscript.conversation_id == conversation_id, VideoTranscript.platform == v.platform,
        VideoTranscript.video_id == v.id, VideoTranscript.page == v.page)
        .order_by(VideoTranscript.created_at.desc()))).scalars().all()
    if languages:
        wants = [x.strip().lower() for x in languages if x and x.strip()]
        rows = [r for r in rows if r.language.lower().removeprefix("ai-") in wants
                or r.language.lower().removeprefix("ai-").split("-")[0] in wants]
    return _of(rows[0]) if rows else None
