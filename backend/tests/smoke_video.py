# 冒烟：v2.03 大脑 (aq) 视频字幕——app/video_transcript.py（规则 + 存取）+ app/video_sources.py（YouTube 移植
# youtube-transcript-api，B 站自写）+ analyze_video / search_transcript。模拟模型 + 假网络（httpx.MockTransport），迁移 0047。
# - 链接：watch / youtu.be / shorts / embed / live / m. / music. / nocookie；B 站 BV / av / ?p= / m.；b23.tv；别的 → None；
# - 选字幕：偏好顺序、同语言人工优先、zh 认 zh-CN、ai-zh 当 zh、都不在偏好里 → 人工 → 自动；
# - 时间：ts / parse_ts（分:秒、时:分:秒、秒数、全角冒号、负数 / 乱写报错）；分段（中文不加空格）；
# - 给模型：短 → 全文带时间点；长 → 均匀分段摘录 + 编号 + 让它 search；搜索：多词命中多的在前、合并相邻、上下文、总数；
#   按时间读：区间、截断、end ≤ start 报错；
# - YouTube：正常（标题 / 作者 / 时长 / 其他字幕、&fmt=srv3 去掉、HTML 标签去掉）、consent 种 cookie、recaptcha、
#   机器人检测、年龄限制、不存在、放不了带 subreason、没字幕给描述、&exp=xpe、429、内网跳转被拦；
# - B 站：AI 字幕（自动生成）、分 P 标题与越界、没公开字幕给简介、code -404、412 风控（退到分 P 列表；也被拦才报错）、b23 短链解开；
# - 存取：同对话同视频同语言替换、KEEP、别的对话看不到、按链接 + 语言找；
# - 一轮对话：analyze_video → search_transcript → 时间线摘要；同对话再读同一视频不联网；计划模式 / 子助手可用；迁移上下行。
# 运行：python tests/smoke_video.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from app import llm, plan_mode, video_sources, video_transcript as vt, web_guard
from app.agent import runner, subagent
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, VideoTranscript
from sqlalchemy import func, select

async def fake_resolve(host):
    return ["10.0.0.5"] if host == "evil.example" else ["93.184.216.34"]
web_guard.resolve = fake_resolve
web_guard.RATE_MAX = 10_000

def err(fn, *a, **k):
    try:
        fn(*a, **k)
    except vt.VideoError as e:
        return str(e)
    raise AssertionError("no error")

# --- 链接 ---
Y = "dQw4w9WgXcQ"
for u in (f"https://www.youtube.com/watch?v={Y}&t=10", f"youtube.com/watch?v={Y}", f"https://youtu.be/{Y}?si=x",
          f"https://m.youtube.com/watch?v={Y}", f"https://music.youtube.com/watch?v={Y}", f"https://www.youtube.com/shorts/{Y}",
          f"https://www.youtube.com/embed/{Y}", f"https://www.youtube.com/live/{Y}", f"https://www.youtube-nocookie.com/embed/{Y}"):
    assert vt.parse(u) == vt.Video("youtube", Y), u
for u in ("https://www.youtube.com/watch?v=short", "https://www.youtube.com/@chan", "https://youtu.be/", "https://example.com/watch?v=" + Y,
          "", "not a url", "https://www.bilibili.com/read/cv1", "https://www.bilibili.com/video/BV123"):
    assert vt.parse(u) is None, u
assert vt.parse("https://www.bilibili.com/video/BV1GJ411x7h7/?spm=x") == vt.Video("bilibili", "BV1GJ411x7h7")
assert vt.parse("https://m.bilibili.com/video/BV1GJ411x7h7?p=3") == vt.Video("bilibili", "BV1GJ411x7h7", 3)
assert vt.parse("https://www.bilibili.com/video/AV170001?p=0") == vt.Video("bilibili", "av170001", 1)
assert vt.parse("https://b23.tv/AbC123x") == vt.Video("b23", "AbC123x")
v = vt.Video("youtube", Y)
assert v.link(75.9) == f"https://youtu.be/{Y}?t=75"
assert vt.Video("bilibili", "BV1GJ411x7h7", 2).link(5) == "https://www.bilibili.com/video/BV1GJ411x7h7?p=2&t=5"
assert vt.Video("bilibili", "BV1GJ411x7h7", 2).url.endswith("?p=2")

# --- 选字幕 ---
T = lambda lang, gen=False: vt.Track(lang, lang, gen, "u-" + lang)
tr = [T("en", True), T("en"), T("ja"), T("zh-CN", True)]
assert vt.pick(tr).language == "zh-CN"                        # 默认中文优先（自动也行）
assert vt.pick(tr, ["en"]).generated is False                 # 同语言人工优先
assert vt.pick(tr, ["ko"]).language == "en" and not vt.pick(tr, ["ko"]).generated  # 不在偏好 → 任一人工
assert vt.pick([T("ko", True)], ["en"]).language == "ko"
assert vt.pick([T("ai-zh", True)]).language == "ai-zh"
assert vt.pick([T("zh-TW"), T("zh-Hans")]).language == "zh-Hans"
assert vt.pick([T("en-US")], ["en"]).language == "en-US"
assert vt.pick([]) is None

# --- 时间 / 分段 ---
assert vt.ts(0) == "0:00" and vt.ts(75.9) == "1:15" and vt.ts(3725) == "1:02:05"
assert vt.parse_ts("5:30") == 330 and vt.parse_ts("1:02:03") == 3723 and vt.parse_ts("90") == 90 and vt.parse_ts(12) == 12
assert vt.parse_ts("5：30") == 330 and vt.parse_ts("") is None and vt.parse_ts(None) is None
assert "认不出" in err(vt.parse_ts, "五分钟") and "负数" in err(vt.parse_ts, -1) and err(vt.parse_ts, True)
S = vt.Segment
assert vt.tidy([S(5, 4, "  b  "), S(1, 2, "a\n x"), S(3, 4, " ")]) == [S(1, 2, "a x"), S(5, 5, "b")]
p = vt.paragraphs([S(0, 1, "你好"), S(2, 3, "世界"), S(4, 5, "hello"), S(31, 32, "next")])
assert p == [(0, "你好世界 hello"), (31, "next")], p

def make(n, every=5, text="第{i}句话 apple" ):
    segs = [S(i * every, i * every + every, text.format(i=i)) for i in range(n)]
    return vt.Transcript(vt.Video("youtube", Y), "标题", "作者", n * every, "zh-Hans", "中文（简体）", False, segs,
                         ["English"], ref="vt_abcdef")
short = make(20)
out = vt.for_model(short)
assert out.startswith("《标题》 — 作者 · 时长 1:40 · 字幕：中文（简体）（人工字幕） · 编号 vt_abcdef"), out
assert "其他字幕：English" in out and "全文：" in out and "[0:30]" in out and f"youtu.be/{Y}?t=<秒数>" in out
long = make(3000, text="第{i}句话说了很多很多内容" * 3)
out = vt.for_model(long)
assert "字幕很长" in out and "search_transcript" in out and "vt_abcdef" in out and len(out) < 9000, len(out)
assert out.count("\n[") == vt.WINDOWS, out.count("\n[")
segs = [S(0, 5, "intro"), S(5, 10, "apple pie"), S(10, 15, "middle"), S(15, 20, "banana"), S(20, 25, "x"),
        S(25, 30, "y"), S(30, 35, "apple banana"), S(35, 40, "end")]
t = vt.Transcript(vt.Video("youtube", Y), "t", "", 40, "en", "English", True, segs)
hits, total = vt.search(t, "Apple banana")
assert total == 3 and [h[0] for h in hits] == [0, 25], hits      # 第 3 句离第 1 句太近，并进同一处
assert [h[0] for h in hits] == sorted(h[0] for h in hits)
assert any("apple banana" in h[1] and "y" in h[1] for h in hits)           # 带前后文
assert len(vt.search(t, "apple banana", limit=1)[0]) == 1
assert vt.search(t, "apple banana", limit=1)[0][0][0] == 25.0               # 命中两个词的最先
assert vt.search(t, '"apple pie"')[1] == 1
assert "关键词" in err(vt.search, t, "  ")
text, cut = vt.window(t, 10, 20)
assert text == "[0:10] middle banana" and not cut, text
assert vt.window(t, 12, None)[0].startswith("[0:10] middle")                 # 正在说的那句也算
assert vt.window(t, 100, None) == ("", False)
assert "晚" in err(vt.window, t, 20, 10)
assert vt.window(long, 0, None)[1] is True

# --- 假网络 ---
calls: list[str] = []
YT_TRACKS = [{"baseUrl": "https://www.youtube.com/api/timedtext?v=X&lang=en&fmt=srv3", "languageCode": "en",
              "name": {"runs": [{"text": "English"}]}},
             {"baseUrl": "https://www.youtube.com/api/timedtext?v=X&lang=zh-Hans&kind=asr", "languageCode": "zh-Hans",
              "kind": "asr", "name": {"runs": [{"text": "中文（自动生成）"}]}}]
state = {"player": None, "html": None, "xml": None}
XML = ('<?xml version="1.0"?><transcript><text start="0.5" dur="2">Hello &amp;amp; &lt;b&gt;welcome&lt;/b&gt;</text>'
       '<text start="3" dur="2">we talk about apples</text><text start="40" dur="1"></text>'
       '<text start="61" dur="3">bye</text></transcript>')

def player(**over):
    d = {"playabilityStatus": {"status": "OK"},
         "videoDetails": {"title": "Apple talk", "author": "Chan", "lengthSeconds": "64", "shortDescription": "desc here"},
         "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": YT_TRACKS}}}
    d.update(over)
    return d

def handler(req: httpx.Request) -> httpx.Response:
    u = str(req.url)
    calls.append(u)
    h = req.url.host
    if h == "www.youtube.com" and req.url.path == "/watch":
        html = state["html"]
        if callable(html):
            html = html(req)
        return httpx.Response(200, text=html if html is not None else 'x "INNERTUBE_API_KEY": "KEY123" y')
    if h == "www.youtube.com" and req.url.path.startswith("/youtubei/v1/player"):
        assert req.url.params["key"] == "KEY123"
        body = json.loads(req.content)
        assert body["context"]["client"]["clientName"] == "ANDROID" and body["videoId"]
        p = state["player"]
        if isinstance(p, int):
            return httpx.Response(p)
        return httpx.Response(200, json=p if p is not None else player())
    if h == "www.youtube.com" and req.url.path == "/api/timedtext":
        assert "fmt=srv3" not in u
        return httpx.Response(200, text=state["xml"] or XML)
    if h == "api.bilibili.com" and req.url.path == "/x/web-interface/view":
        assert req.headers.get("referer") == "https://www.bilibili.com/"
        bv = req.url.params.get("bvid") or req.url.params.get("aid")
        if bv == "BV1xx411c7mD":
            return httpx.Response(200, json={"code": -404, "message": "啥都木有"})
        if bv in ("BV1zz411c7mZ", "BV1ww411c7mW"):
            return httpx.Response(412)
        return httpx.Response(200, json={"code": 0, "data": {
            "title": "B 站视频", "owner": {"name": "UP"}, "duration": 200, "desc": "简介内容",
            "pages": [{"cid": 11, "part": "上", "duration": 100}, {"cid": 22, "part": "下", "duration": 100}]}})
    if h == "api.bilibili.com" and req.url.path == "/x/player/pagelist":
        if req.url.params.get("bvid") == "BV1zz411c7mZ":
            return httpx.Response(412)
        return httpx.Response(200, json={"code": 0, "data": [{"cid": 33, "page": 1, "part": "唯一一P", "duration": 90}]})
    if h == "api.bilibili.com" and req.url.path == "/x/player/v2":
        cid = req.url.params["cid"]
        if req.url.params.get("bvid") == "BV1yy411c7mY":
            return httpx.Response(200, json={"code": 0, "data": {"subtitle": {"subtitles": []}}})
        return httpx.Response(200, json={"code": 0, "data": {"subtitle": {"subtitles": [
            {"lan": "ai-zh", "lan_doc": "中文（自动生成）", "subtitle_url": f"//aisubtitle.hdslb.com/s{cid}.json"}]}}})
    if h == "aisubtitle.hdslb.com":
        return httpx.Response(200, json={"body": [{"from": 0, "to": 2, "content": "大家好"}, {"from": 2, "to": 4, "content": "今天讲苹果"}]})
    if h == "b23.tv":
        if req.url.path == "/evil1":
            return httpx.Response(302, headers={"location": "http://evil.example/x"})
        if req.url.path == "/nothing":
            return httpx.Response(302, headers={"location": "https://www.bilibili.com/read/cv1"})
        return httpx.Response(302, headers={"location": "https://www.bilibili.com/video/BV1GJ411x7h7?p=2&share=1"})
    return httpx.Response(404)
video_sources.transport = httpx.MockTransport(handler)
F = lambda v, langs=None: asyncio.run(video_sources.fetch(v, langs))
def ferr(v, langs=None):
    try:
        F(v, langs)
    except vt.VideoError as e:
        return str(e)
    raise AssertionError("no error")

t = F(vt.Video("youtube", Y))
assert (t.title, t.author, t.duration, t.language, t.generated) == ("Apple talk", "Chan", 64.0, "zh-Hans", True), t
assert [s.text for s in t.segments] == ["Hello & welcome", "we talk about apples", "bye"] and t.segments[0].end == 2.5
assert t.available == ["English"]
t = F(vt.Video("youtube", Y), ["en"])
assert t.language == "en" and not t.generated and t.language_name == "English"
# consent：第一次给 consent 页，带上 cookie 再来就好
def consent(req):
    if "CONSENT=YES+abc" in req.headers.get("cookie", ""):
        return '"INNERTUBE_API_KEY": "KEY123"'
    return '<form action="https://consent.youtube.com/s"><input name="v" value="abc"></form>'
state["html"] = consent
assert F(vt.Video("youtube", Y)).title == "Apple talk"
state["html"] = '<form action="https://consent.youtube.com/s"></form>'
assert "cookie" in ferr(vt.Video("youtube", Y))
state["html"] = '<div class="g-recaptcha"></div>'
assert "拦下" in ferr(vt.Video("youtube", Y))
state["html"] = "<html>nothing</html>"
assert "改版" in ferr(vt.Video("youtube", Y))
state["html"] = None
state["player"] = player(playabilityStatus={"status": "LOGIN_REQUIRED", "reason": video_sources.BOT_DETECTED})
assert "拦下" in ferr(vt.Video("youtube", Y))
state["player"] = player(playabilityStatus={"status": "LOGIN_REQUIRED", "reason": video_sources.AGE_RESTRICTED})
assert "年龄" in ferr(vt.Video("youtube", Y))
state["player"] = player(playabilityStatus={"status": "ERROR", "reason": video_sources.VIDEO_UNAVAILABLE})
assert "不存在" in ferr(vt.Video("youtube", Y))
state["player"] = player(playabilityStatus={"status": "UNPLAYABLE", "reason": "Private video", "errorScreen": {
    "playerErrorMessageRenderer": {"subreason": {"runs": [{"text": "Sign in"}]}}}})
assert ferr(vt.Video("youtube", Y)) == "视频放不了：Private video（Sign in）"
state["player"] = player(captions={})
e = ferr(vt.Video("youtube", Y))
assert "没有字幕" in e and "desc here" in e, e
state["player"] = player(captions={"playerCaptionsTracklistRenderer": {"captionTracks": [
    {**YT_TRACKS[0], "baseUrl": YT_TRACKS[0]["baseUrl"] + "&exp=xpe"}]}})
assert "PoToken" in ferr(vt.Video("youtube", Y))
state["player"] = 429
assert "拦下" in ferr(vt.Video("youtube", Y))
state["player"] = None
state["xml"] = "<transcript></transcript>"
assert "空" in ferr(vt.Video("youtube", Y))
state["xml"] = None
# B 站
t = F(vt.Video("bilibili", "BV1GJ411x7h7", 2))
assert t.title == "B 站视频（P2 下）" and t.author == "UP" and t.duration == 100 and t.generated and t.language == "ai-zh"
assert [s.text for s in t.segments] == ["大家好", "今天讲苹果"] and any("s22.json" in c for c in calls)
assert "只有 2 P" in ferr(vt.Video("bilibili", "BV1GJ411x7h7", 3))
e = ferr(vt.Video("bilibili", "BV1yy411c7mY"))
assert "没有公开字幕" in e and "简介内容" in e, e
assert "视频不存在" in ferr(vt.Video("bilibili", "BV1xx411c7mD"))
assert "风控" in ferr(vt.Video("bilibili", "BV1zz411c7mZ"))
t = F(vt.Video("bilibili", "BV1ww411c7mW"))                              # 视频信息被风控 → 退到分 P 列表
assert t.title == "唯一一P" and t.author == "" and t.duration == 90 and any("s33.json" in c for c in calls)
assert F(vt.Video("bilibili", "av170001")).title.startswith("B 站视频")
assert any("aid=170001" in c for c in calls)
t = F(vt.Video("b23", "AbC123x"))
assert t.video == vt.Video("bilibili", "BV1GJ411x7h7", 2), t.video
assert "不允许" in ferr(vt.Video("b23", "evil1"))
assert not any("evil.example" in c for c in calls)                     # 内网那一跳根本没发出去
assert "没有跳到" in ferr(vt.Video("b23", "nothing"))

# --- 存取 ---
async def store():
    async with SessionLocal() as db:
        for cid in ("c1", "c2"):
            db.add(Conversation(id=cid, title="t"))
        await db.commit()
        a = await vt.save(db, "c1", make(10))
        assert a.ref.startswith("vt_") and len(a.ref) == 9
        b = await vt.save(db, "c1", make(12))                            # 同视频同语言 → 换掉
        assert await db.get(VideoTranscript, a.ref) is None
        got = await vt.find(db, "c1", b.ref)
        assert got and len(got.segments) == 12 and got.available == ["English"] and got.title == "标题"
        assert await vt.find(db, "c2", b.ref) is None                    # 别的对话看不到
        assert (await vt.find(db, "c1", f"https://youtu.be/{Y}")).ref == b.ref
        assert await vt.find(db, "c1", f"https://youtu.be/{Y}", ["en"]) is None
        assert (await vt.find(db, "c1", f"https://youtu.be/{Y}", ["zh"])).ref == b.ref
        assert await vt.find(db, "c1", "vt_zzzzzz") is None and await vt.find(db, "c1", "https://b23.tv/AbC123x") is None
        for i in range(vt.KEEP + 3):
            x = make(3); x.video = vt.Video("youtube", f"{i:011d}")
            await vt.save(db, "c2", x)
        n = (await db.execute(select(func.count()).select_from(VideoTranscript).where(VideoTranscript.conversation_id == "c2"))).scalar()
        assert n == vt.KEEP, n
        assert await vt.find(db, "c2", "https://youtu.be/00000000000") is None   # 最旧的丢了
        assert await vt.find(db, "c1", b.ref)                                    # c1 不受影响
asyncio.run(store())

# --- 一轮对话 ---
load_builtin()
for n in ("analyze_video", "search_transcript"):
    assert n in REGISTRY and REGISTRY[n].parallel and n in plan_mode.READ_TOOLS and n in subagent.CHILD_TOOLS
assert "analyze_video" in settings.system_prompt

script: list = []
tool_msgs: list[dict] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    rnd = len(script)
    if callable(step):
        step = step()
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(tool_msgs)}_{rnd}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

def ref_from_tools():
    ref = next(m["content"].split("编号 ")[1][:9] for m in tool_msgs if "编号 vt_" in m["content"])
    return [("search_transcript", {"video": ref, "query": "apples"}),
            ("search_transcript", {"video": ref, "start": "1:00"}),
            ("search_transcript", {"video": ref, "start": "五分"})]

async def turn(text, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = await db.get(Conversation, "c3")
        if conv is None:
            conv = Conversation(id="c3", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c3", role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return await runner.run_turn(db, conv)

calls.clear()
reply = asyncio.run(turn(f"总结一下 https://youtu.be/{Y} 里讲了什么", [
    [("analyze_video", {"url": f"https://youtu.be/{Y}"}), ("analyze_video", {"url": "https://example.com/v"})],
    ref_from_tools, "讲了苹果。"]))
st = reply.steps
assert st[0]["tool"] == "analyze_video" and st[0]["state"] == "done" and st[0]["detail"] == "Apple talk · 1:04", st[0]
assert st[1]["state"] == "error" and "不是支持的视频链接" in st[1]["note"], st[1]
assert st[2]["detail"] == "apples · 1 处" and st[2]["state"] == "done", st[2]
assert st[3]["detail"] == "1:00–结尾" and st[4]["state"] == "error", st[3:]
contents = " | ".join(m["content"] for m in tool_msgs)
assert "全文：" in contents and "we talk about apples" in contents and f"https://youtu.be/{Y}?t=0" in contents, contents
assert "[1:01] bye" in contents and "认不出时间点" in contents
n_calls = len(calls)
assert n_calls == 3, calls                                                   # watch + player + timedtext
reply = asyncio.run(turn("再看看那个视频", [[("analyze_video", {"url": f"https://www.youtube.com/watch?v={Y}"})], "好"]))
assert reply.steps[0]["state"] == "done" and len(calls) == n_calls          # 同对话不再联网
reply = asyncio.run(turn("英文字幕", [[("analyze_video", {"url": f"https://youtu.be/{Y}", "languages": ["en"]})], "好"]))
assert len(calls) == n_calls + 3                                             # 换语言 → 重新取
reply = asyncio.run(turn("没读过的", [[("search_transcript", {"video": "https://youtu.be/AAAAAAAAAAA", "query": "x"})], "好"]))
assert reply.steps[0]["state"] == "error"

# --- 迁移上下行 ---
r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0046"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print("smoke_video OK")
