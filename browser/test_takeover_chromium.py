"""真 Chromium 端到端（v2.89 实时画面 + 接管；需要 playwright + chromium，没有就跳过）：python3 browser/test_takeover_chromium.py
CDP screencast 真的推出 JPEG 帧、按观看宽度缩小；接管输入（live.parse → service._input，和 WS 同一条路）真的落到网页上：
点中一个很小的按钮；滚轮滚到页底；长按拖动滑块（down → move → up）；后退 / 刷新；看不懂的输入被丢掉。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import json  # noqa: E402
import live  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()

W, H = service.VIEW["width"], service.VIEW["height"]
PAGE = """<title>表单</title><style>body{margin:0}</style>
<button id=tiny style="position:fixed;left:600px;top:20px;width:8px;height:8px;padding:0"
 onclick="document.getElementById('out').dataset.tiny='1'"></button>
<div id=track style="position:fixed;left:100px;top:300px;width:400px;height:40px;background:#ddd">
 <div id=knob style="position:absolute;left:0;top:0;width:40px;height:40px;background:#333"></div></div>
<script>
let drag=null;const k=document.getElementById('knob');
k.onmousedown=e=>{drag=e.clientX-k.offsetLeft};
onmousemove=e=>{if(drag!==null)k.style.left=Math.max(0,Math.min(360,e.clientX-drag))+'px'};
onmouseup=()=>{if(drag!==null){document.getElementById('out').dataset.slid=k.style.left;drag=null}};
</script>
<div style="height:5000px"></div><p id=out>底部</p><a href="/two">下一页</a>"""


async def serve(r, w):
    head = await r.readuntil(b"\r\n\r\n")
    page = "<title>第二页</title>两" if b"GET /two" in head else PAGE
    body = ("<meta charset=utf-8>" + page).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


async def inp(**m):
    cmd = live.parse(json.dumps(m))
    assert cmd is not None, m
    await service._input("t", cmd)


async def ev(js):
    page = await service._session("t")
    return await page.evaluate(js)


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    await service.goto("t", service.GotoIn(url=base + "/"))

    # 8×8 像素的小按钮：坐标换算准就点得中
    # 推流：有人看 → 首帧是 JPEG；手机宽 390 → 帧宽 ≤480；没人看 → 停
    lv = service._live.setdefault("t", service._Live())
    v = live.Viewer()
    v.px = 390
    lv.hub.join(v)
    await service._cast("t")
    frame = await asyncio.wait_for(v.next(), 10)
    assert frame[:2] == b"\xff\xd8", frame[:4]  # JPEG
    width = int.from_bytes(frame[frame.index(b"\xff\xc0") + 7:][:2], "big")
    assert 0 < width <= 480, width
    lv.hub.leave(v)
    await service._cast("t")
    assert lv.cdp is None

    await inp(t="mouse", x=604 / W, y=24 / H)
    assert await ev("document.getElementById('out').dataset.tiny") == "1"

    # 长按拖动滑块：down → 多次 move → up
    await inp(t="mouse", kind="down", x=120 / W, y=320 / H)
    for px in (180, 260, 340, 420):
        await inp(t="mouse", kind="move", x=px / W, y=320 / H)
    await inp(t="mouse", kind="up", x=440 / W, y=320 / H)
    slid = await ev("document.getElementById('out').dataset.slid")
    assert slid and int(slid.rstrip("px")) >= 300, slid

    # 滚轮：每次最多 SCROLL_MAX，两次大甩就到底
    await inp(t="wheel", dy=99999)
    await asyncio.sleep(0.3)
    y1 = await ev("scrollY")
    assert y1 == live.SCROLL_MAX, y1
    await inp(t="wheel", dy=99999)
    await asyncio.sleep(0.3)
    assert await ev("innerHeight + scrollY >= document.body.scrollHeight - 2")
    await inp(t="wheel", dy=-500)
    await asyncio.sleep(0.3)
    assert await ev("scrollY") < y1 + live.SCROLL_MAX

    # 后退 / 刷新
    page = await service._session("t")
    await page.goto(base + "/two")
    await inp(t="nav", action="back")
    assert await ev("document.title") == "表单"
    await ev("document.getElementById('out').dataset.tiny='x'")
    await inp(t="nav", action="reload")
    assert await ev("document.getElementById('out').dataset.tiny") is None

    assert live.parse('{"t":"mouse","kind":"drag"}') is None and live.parse('{"t":"nav","action":"forward"}') is None
    srv.close()
    print("test_takeover_chromium ok")


asyncio.run(main())
