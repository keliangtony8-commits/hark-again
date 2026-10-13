"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_tabs_chromium.py
直接调 service.py 的接口函数：链接在新标签页打开 → 快照是新页 + tab.opened；后退到头 → 关掉回原页（returned）；
window.open 后网站自己 window.close → 退回（closed）；渲染进程崩了（chrome://crash 模拟 OOM）→ 原网址重开（crashed）。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()

PAGES = {
    "/": "<title>列表</title><a href='/item' target='_blank'>商品一</a>"
         "<button onclick=\"window.open('/pop')\">弹窗</button>",
    "/item": "<title>商品一</title><p>价格 99 元</p>",
    "/pop": "<title>弹窗</title><button onclick='window.close()'>关闭</button>",
}


async def serve(r, w):
    req = await r.readuntil(b"\r\n\r\n")
    path = req.split(b" ")[1].decode()
    body = ("<meta charset=utf-8>" + PAGES.get(path, "<title>404</title>")).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


def ref(snap, name):
    return next(e["ref"] for e in snap["elements"] if e["name"] == name)


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    s = await service.goto("s", service.GotoIn(url=base + "/"))
    assert s["title"] == "列表" and "tab" not in s, s.get("tab")
    # 1. target=_blank → 新标签页
    s = await service.act("s", service.ActIn(action="click", ref=ref(s, "商品一")))
    assert s["title"] == "商品一", s["title"]
    assert s["tab"]["kind"] == "opened" and s["tab"]["tabs"] == 2 and s["tab"]["from"] == base + "/", s["tab"]
    # 1b. 拿旧页的编号点新页：马上说清楚（不等 8 秒超时）
    import time as _t; t0 = _t.time()
    try:
        await service.act("s", service.ActIn(action="click", ref="2"))
        raise AssertionError("应该报编号不在")
    except service.HTTPException as e:
        assert "没有编号 2" in e.detail and "browser_back" in e.detail and _t.time() - t0 < 3, e.detail
    # 2. 弹出页后退到头 → 关掉回原页
    s = await service.act("s", service.ActIn(action="back"))
    assert s["title"] == "列表" and s["tab"]["kind"] == "returned" and s["tab"]["tabs"] == 1, (s["title"], s.get("tab"))
    # 3. window.open → 网站 window.close → 退回
    s = await service.act("s", service.ActIn(action="click", ref=ref(s, "弹窗")))
    assert s["title"] == "弹窗" and s["tab"]["kind"] == "opened"
    s = await service.act("s", service.ActIn(action="click", ref=ref(s, "关闭")))
    assert s["title"] == "列表" and s["tab"]["kind"] == "closed", (s["title"], s.get("tab"))
    # 4. 渲染进程崩了 → 原网址重开
    page = service._sessions["s"][1]
    try:
        await page.goto("chrome://crash", timeout=5000)
    except Exception:
        pass
    await asyncio.sleep(0.5)
    assert id(page) in service._tabs["s"].crashed, "没收到 crash 事件"
    s = await service.snapshot("s")
    assert s["title"] == "列表" and s["tab"] == {"kind": "crashed", "url": base + "/"}, (s["title"], s.get("tab"))
    # 实时画面也在新页上
    r = await service.screen("s")
    assert r.body[:2] == b"\xff\xd8"
    # 5. 同一网址 60 秒内又崩 → 不再重开
    page = service._sessions["s"][1]
    try:
        await page.goto("chrome://crash", timeout=5000)
    except Exception:
        pass
    await asyncio.sleep(0.5)
    s = await service.snapshot("s")
    assert s["tab"]["kind"] == "crash_loop" and s["url"] == "about:blank", (s["url"], s.get("tab"))
    print("✓ 真 Chromium：新标签页跟过去、后退回原页、网站关页退回、崩溃重开 / 防循环")
    await service._browser.close()
    srv.close()

asyncio.run(main())
