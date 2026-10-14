# YouTube 部分 Copyright (c) 2018 Jonas Depoix — MIT License (modified).
# Ported from jdepoix/youtube-transcript-api youtube_transcript_api/_transcripts.py + _settings.py (MIT), modified:
#   同步 requests → 异步 httpx（经 app/web_guard.client，每一跳都查内网）；异常类换成一个 VideoError（中文原因）；
#   保留：watch 页取 INNERTUBE_API_KEY、consent 页种 CONSENT cookie 再取一次、recaptcha 判被拦、ANDROID 客户端
#   上下文调 player 接口、playabilityStatus 的几种失败（机器人检测 / 年龄限制 / 不存在 / 放不了 + subreason）、
#   captionTracks 去掉 &fmt=srv3、&exp=xpe 要 PoToken、429 判 IP 被拦、XML <text start dur> 去 HTML 标签。
#   另从 player 的 videoDetails 取标题 / 作者 / 时长。
# B 站部分是自己写的：x/web-interface/view 取标题 / 分 P 的 cid，x/player/v2 取字幕列表（AI 字幕 ai-zh 记为自动生成）。
"""视频字幕的联网部分：只负责“把一个 Video 变成 Transcript”。选字幕、整理、存取的规则全在 app/video_transcript.py。"""
import re
from html import unescape
from xml.etree import ElementTree

import httpx

from . import web_guard
from .video_transcript import Segment, Track, Transcript, Video, VideoError, parse, pick, tidy

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/player?key={api_key}"
INNERTUBE_CONTEXT = {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}}
BOT_DETECTED = "Sign in to confirm you’re not a bot"
AGE_RESTRICTED = "This video may be inappropriate for some users."
VIDEO_UNAVAILABLE = "This video is unavailable"
CONSENT_ACTION = 'action="https://consent.youtube.com/s"'
BLOCKED = ("YouTube 拦下了服务器这次请求（机房 IP 常被当成机器人）。稍后再试；急的话请用户把字幕文件或视频描述发过来，"
           "或者用 browser_open 打开视频页看描述。")
BILI_VIEW = "https://api.bilibili.com/x/web-interface/view"
BILI_PLAYER = "https://api.bilibili.com/x/player/v2"
BILI_PAGES = "https://api.bilibili.com/x/player/pagelist"   # 视频信息接口被风控（412）时退到它：只有分 P，没有作者 / 简介
_HTML_TAG = re.compile(r"<[^>]*>")

transport: httpx.AsyncBaseTransport | None = None   # 测试换成 MockTransport


def _client(headers: dict) -> httpx.AsyncClient:
    return web_guard.client(transport=transport, timeout=TIMEOUT, follow_redirects=True,
                            headers={"User-Agent": UA, **headers})


async def fetch(video: Video, languages: list[str] | None = None) -> Transcript:
    """联网取字幕。所有失败都是 VideoError（中文原因，可以原样给模型）。"""
    wait = web_guard.rate_wait(video.url)
    if wait > 0:
        raise VideoError(f"一分钟内读这个网站太多次了，{int(wait) + 1} 秒后再试。")
    try:
        if video.platform == "b23":
            video = await _unshorten(video)
        if video.platform == "youtube":
            return await _youtube(video, languages)
        if video.platform == "bilibili":
            return await _bilibili(video, languages)
    except web_guard.Blocked as e:
        raise VideoError(f"这个地址不允许访问：{e}") from e
    except httpx.TimeoutException as e:
        raise VideoError(f"读取超时（{TIMEOUT} 秒），视频网站很慢，稍后再试。") from e
    except httpx.HTTPError as e:
        raise VideoError(f"连不上视频网站（{e.__class__.__name__}）。") from e
    raise VideoError("只支持 YouTube 和 B 站的视频链接。")


async def _unshorten(video: Video) -> Video:
    async with _client({}) as c:
        r = await c.get(video.url)
    real = parse(str(r.url))
    if real is None or real.platform == "b23":
        raise VideoError("这个 b23.tv 短链没有跳到 B 站视频页。")
    return real


# —— YouTube（移植 youtube-transcript-api） ——

def _raise_http(r: httpx.Response) -> httpx.Response:
    if r.status_code == 429:
        raise VideoError(BLOCKED)
    if r.status_code >= 400:
        raise VideoError(f"YouTube 返回 HTTP {r.status_code}。")
    return r


async def _youtube(video: Video, languages: list[str] | None) -> Transcript:
    async with _client({"Accept-Language": "en-US"}) as c:
        html = await _video_html(c, video.id)
        api_key = _api_key(html)
        r = _raise_http(await c.post(INNERTUBE_API_URL.format(api_key=api_key),
                                     json={"context": INNERTUBE_CONTEXT, "videoId": video.id}))
        try:
            data = r.json()
        except ValueError as e:
            raise VideoError("YouTube 返回的数据看不懂（页面可能改版了）。") from e
        _assert_playability(data.get("playabilityStatus") or {})
        details = data.get("videoDetails") or {}
        title, author = str(details.get("title") or ""), str(details.get("author") or "")
        duration = _num(details.get("lengthSeconds"))
        captions = (data.get("captions") or {}).get("playerCaptionsTracklistRenderer")
        if not captions or "captionTracks" not in captions:
            desc = str(details.get("shortDescription") or "").strip()
            raise VideoError(f"《{title or video.id}》没有字幕（作者关掉了，或者还没生成）。"
                             + (f"视频描述：{desc[:1500]}" if desc else ""))
        tracks = []
        for cap in captions.get("captionTracks") or []:
            try:
                name = cap["name"]["runs"][0]["text"]
            except (KeyError, IndexError, TypeError):
                name = str((cap.get("name") or {}).get("simpleText") or cap.get("languageCode") or "")
            tracks.append(Track(language=str(cap.get("languageCode") or ""), name=name,
                                generated=cap.get("kind", "") == "asr",
                                url=str(cap.get("baseUrl") or "").replace("&fmt=srv3", "")))
        track = pick(tracks, languages)
        if track is None or not track.url:
            raise VideoError(f"《{title or video.id}》没有能读的字幕。")
        if "&exp=xpe" in track.url:
            raise VideoError("YouTube 这条字幕要求浏览器验证（PoToken），暂时读不了。")
        body = _raise_http(await c.get(track.url)).text
    segments = tidy(parse_xml(body))
    if not segments:
        raise VideoError(f"《{title or video.id}》的字幕是空的。")
    return Transcript(video=video, title=title, author=author, duration=duration or segments[-1].end,
                      language=track.language, language_name=track.name, generated=track.generated,
                      segments=segments, available=[t.name for t in tracks if t is not track])


async def _video_html(c: httpx.AsyncClient, video_id: str) -> str:
    html = await _html(c, video_id)
    if CONSENT_ACTION in html:
        m = re.search('name="v" value="(.*?)"', html)
        if m is None:
            raise VideoError("YouTube 要求先同意 cookie 条款，自动同意失败。")
        c.cookies.set("CONSENT", "YES+" + m.group(1), domain=".youtube.com")
        html = await _html(c, video_id)
        if CONSENT_ACTION in html:
            raise VideoError("YouTube 要求先同意 cookie 条款，自动同意失败。")
    return html


async def _html(c: httpx.AsyncClient, video_id: str) -> str:
    return unescape(_raise_http(await c.get(WATCH_URL.format(video_id=video_id))).text)


def _api_key(html: str) -> str:
    m = re.search(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"', html)
    if m:
        return m.group(1)
    if 'class="g-recaptcha"' in html:
        raise VideoError(BLOCKED)
    raise VideoError("YouTube 页面看不懂（可能改版了），读不到字幕。")


def _assert_playability(st: dict) -> None:
    status = st.get("status")
    if status in (None, "OK"):
        return
    reason = str(st.get("reason") or "")
    if status == "LOGIN_REQUIRED":
        if reason == BOT_DETECTED:
            raise VideoError(BLOCKED)
        if reason == AGE_RESTRICTED:
            raise VideoError("这个视频有年龄限制，要登录才能看，读不到字幕。")
    if status == "ERROR" and reason == VIDEO_UNAVAILABLE:
        raise VideoError("视频不存在或已下架，检查一下链接。")
    runs = (((st.get("errorScreen") or {}).get("playerErrorMessageRenderer") or {})
            .get("subreason") or {}).get("runs") or []
    sub = "".join(str(r.get("text", "")) for r in runs if isinstance(r, dict))
    raise VideoError("视频放不了：" + (reason or status) + (f"（{sub}）" if sub else ""))


def parse_xml(raw: str) -> list[Segment]:
    """YouTube timedtext XML（<transcript><text start dur>…</text>）→ 句子。坏 XML → 空。"""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []
    out = []
    for el in root:
        if el.text is None:
            continue
        start = _num(el.attrib.get("start"))
        dur = _num(el.attrib.get("dur", "0.0"))
        out.append(Segment(start, start + dur, _HTML_TAG.sub("", unescape(el.text))))
    return out


def _num(v) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


# —— B 站 ——

_BILI_ERR = {-400: "请求有误", -403: "没有权限", -404: "视频不存在", 62002: "视频不可见", 62004: "视频审核中",
             62012: "仅 UP 主自己可见"}


async def _bilibili(video: Video, languages: list[str] | None) -> Transcript:
    key = {"bvid": video.id} if video.id.startswith("BV") else {"aid": video.id[2:]}
    async with _client({"Referer": "https://www.bilibili.com/"}) as c:
        view = await _bili_view(c, key)
        pages = view.get("pages") or []
        if video.page > max(1, len(pages)):
            raise VideoError(f"这个视频只有 {len(pages)} P，没有第 {video.page} P。")
        page = pages[video.page - 1] if pages else {"cid": view.get("cid"), "part": "", "duration": view.get("duration")}
        cid = page.get("cid")
        if not cid:
            raise VideoError("B 站没给这个视频的分 P 信息，读不到字幕。")
        title = str(view.get("title") or "")
        if not title and page.get("part"):
            title = f"P{video.page} {page.get('part')}"
        if len(pages) > 1 and page.get("part") and title:
            title += f"（P{video.page} {page.get('part')}）"
        author = str((view.get("owner") or {}).get("name") or "")
        duration = _num(page.get("duration") or view.get("duration"))
        player = await _bili_json(c, BILI_PLAYER, {**key, "cid": cid})
        subs = ((player.get("subtitle") or {}).get("subtitles")) or []
        tracks = []
        for s in subs:
            url = str(s.get("subtitle_url") or "")
            if url.startswith("//"):
                url = "https:" + url
            lan = str(s.get("lan") or "")
            if url.startswith(("http://", "https://")):
                tracks.append(Track(language=lan, name=str(s.get("lan_doc") or lan),
                                    generated=lan.lower().startswith("ai-") or s.get("type") == 1, url=url))
        if not tracks:
            desc = str(view.get("desc") or "").strip()
            raise VideoError(f"《{title or video.id}》没有公开字幕（B 站的 AI 字幕常常要登录才给）。"
                             + (f"视频简介：{desc[:1500]}" if desc and desc != "-" else ""))
        track = pick(tracks, languages)
        r = await c.get(track.url)
        if r.status_code >= 400:
            raise VideoError(f"B 站字幕文件返回 HTTP {r.status_code}。")
        try:
            body = r.json().get("body") or []
        except (ValueError, AttributeError) as e:
            raise VideoError("B 站字幕文件看不懂。") from e
    segments = tidy([Segment(_num(x.get("from")), _num(x.get("to")), str(x.get("content") or ""))
                     for x in body if isinstance(x, dict)])
    if not segments:
        raise VideoError(f"《{title or video.id}》的字幕是空的。")
    return Transcript(video=video, title=title, author=author, duration=duration or segments[-1].end,
                      language=track.language, language_name=track.name, generated=track.generated,
                      segments=segments, available=[t.name for t in tracks if t is not track])


async def _bili_view(c: httpx.AsyncClient, key: dict) -> dict:
    try:
        return await _bili_json(c, BILI_VIEW, key)
    except _Risk:
        pages = await _bili_json(c, BILI_PAGES, key)
        if not isinstance(pages, list) or not pages:
            raise VideoError("B 站拦下了服务器这次请求（风控），稍后再试。")
        return {"title": str(pages[0].get("part") or "") if len(pages) == 1 else "", "pages": pages}


class _Risk(VideoError):
    pass


async def _bili_json(c: httpx.AsyncClient, url: str, params: dict) -> dict:
    r = await c.get(url, params=params)
    if r.status_code == 412:
        raise _Risk("B 站拦下了服务器这次请求（风控），稍后再试。")
    if r.status_code >= 400:
        raise VideoError(f"B 站返回 HTTP {r.status_code}。")
    try:
        j = r.json()
    except ValueError as e:
        raise VideoError("B 站返回的数据看不懂。") from e
    code = j.get("code", 0)
    if code != 0:
        raise VideoError(f"B 站说：{_BILI_ERR.get(code) or j.get('message') or code}。")
    data = j.get("data")
    return data if isinstance(data, (dict, list)) else {}
