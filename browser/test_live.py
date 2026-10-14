"""实时画面（v2.89 §M）冒烟测试，不需要真 Chromium：python3 browser/test_live.py
1) live.py 纯规则：分辨率分桶、输入清洗、latest-frame-wins、新连接补最后一帧。
2) WS /sessions/{name}/live（假 Playwright + 假 CDP）：鉴权 4401、没开 4404、open=1 用存档重开并回到最后网址、
   首帧、输入落到页面（坐标 × 视口、弹框 accept、存登录）、改宽度重挂 screencast、最后一人走停推、
   有人看不被空闲回收、会话被关 → 观看者收 4404。"""
import asyncio, base64, os, sys, tempfile, time, types

calls: list = []


class Mouse:
    async def click(self, x, y): calls.append(("click", x, y))
    async def move(self, x, y, steps=1): calls.append(("move", x, y))
    async def down(self): calls.append(("down",))
    async def up(self): calls.append(("up",))
    async def wheel(self, dx, dy): calls.append(("wheel", dx, dy))


class Keyboard:
    async def type(self, text, delay=0): calls.append(("type", text))
    async def press(self, key): calls.append(("press", key))


class Page:
    def __init__(self): self.url, self.mouse, self.keyboard = "about:blank", Mouse(), Keyboard()
    def on(self, *a): pass
    def is_closed(self): return False
    async def goto(self, url, **kw): calls.append(("goto", url)); self.url = url
    async def go_back(self, **kw): calls.append(("back",))
    async def reload(self, **kw): calls.append(("reload",))
    async def close(self): pass


class CDP:
    def __init__(self): self.h = None
    def on(self, ev, fn): self.h = fn
    async def detach(self): calls.append(("detach",))
    async def send(self, method, params=None):
        calls.append((method, (params or {}).get("maxWidth")))
        if method == "Page.startScreencast":
            asyncio.get_running_loop().call_soon(self.h, {"data": base64.b64encode(b"jpeg-1").decode(), "sessionId": 1})


class Ctx:
    def __init__(self): self.pages = []
    async def route(self, *a): pass
    def on(self, *a): pass
    async def new_page(self):
        p = Page(); self.pages = [p]; return p
    async def new_cdp_session(self, page): return CDP()
    async def storage_state(self, path): calls.append(("save",))
    async def close(self): pass


class Browser:
    def is_connected(self): return True
    async def new_context(self, **kw): return Ctx()


class PW:
    async def start(self):
        async def launch(**kw): return Browser()
        self.chromium = types.SimpleNamespace(launch=launch)
        return self


pa = types.ModuleType("playwright.async_api")
pa.Browser = pa.BrowserContext = pa.Page = object
pa.async_playwright = PW
sys.modules["playwright"] = types.ModuleType("playwright")
sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t")
sys.path.insert(0, os.path.dirname(__file__))
import live  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()


def pure():
    w = live.effective_max_width
    assert w([]) == live.MAX_DIMENSION and w([0, None]) == live.MAX_DIMENSION
    assert w([390]) == 480 and w([390, 1000]) == 1120 and w([100]) == live.MIN_DIMENSION and w([5000]) == live.MAX_DIMENSION
    p = live.parse
    assert p('{"t":"mouse","x":2,"y":-1}') == {"t": "mouse", "kind": "click", "x": 1.0, "y": 0.0}
    assert p('{"t":"mouse","kind":"drag","x":0,"y":0}') is None
    assert p('{"t":"mouse","kind":"down","x":"nan","y":0.2}') == {"t": "mouse", "kind": "down", "x": 0.5, "y": 0.2}
    assert p('{"t":"wheel","dy":99999}') == {"t": "wheel", "x": 0.5, "y": 0.5, "dx": 0.0, "dy": live.SCROLL_MAX}
    assert p('{"t":"text","text":""}') is None and len(p('{"t":"text","text":"%s"}' % ("a" * 9000))["text"]) == live.TEXT_MAX
    assert p('{"t":"key","key":"Enter"}') == {"t": "key", "key": "Enter"} and p('{"t":"key","key":"Control+W"}') is None
    assert p('{"t":"nav","action":"forward"}') is None and p('{"t":"nav","action":"back"}')["action"] == "back"
    assert p('{"t":"view","px":390.7}') == {"t": "view", "px": 390}
    assert p("not json") is None and p("[1]") is None and p('{"t":"rm -rf"}') is None

    async def frames():
        hub, v = live.Hub(), live.Viewer()
        hub.deliver(b"a")
        hub.join(v)  # 新连接补最后一帧
        assert await v.next() == b"a"
        for f in (b"b", b"c", b"d"):  # 网慢：只拿最新那帧
            hub.deliver(f)
        assert await v.next() == b"d"
        v.offer(hub.last)  # 同一帧不发第二次
        t = asyncio.ensure_future(v.next())
        await asyncio.sleep(0)
        assert not t.done()
        hub.close_all()
        assert await t is None and not hub.viewers
    asyncio.run(frames())
    print("✓ live.py 规则通过")


def wire():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    c = TestClient(service.app)
    H = {"Authorization": "Bearer t"}

    def code(url, headers=H):
        try:
            with c.websocket_connect(url, headers=headers) as ws:
                ws.receive_bytes()
        except WebSocketDisconnect as e:
            return e.code
        raise AssertionError("应当被关")

    assert code("/sessions/a-com/live", {}) == live.CLOSE_UNAUTHORIZED
    assert code("/sessions/a-com/live") == live.CLOSE_NOT_OPEN  # 没开、没说重开
    open(service._last_url_path("a-com"), "w").write("https://a.com/cart")
    with c.websocket_connect("/sessions/a-com/live?open=1", headers=H) as ws:
        assert ws.receive_bytes() == b"jpeg-1"  # 重开 → 回到最后网址 → 首帧
        assert ("goto", "https://a.com/cart") in calls and ("Page.startScreencast", 1280) in calls
        calls.clear()
        ws.send_text('{"t":"view","px":390}')
        ws.send_text('{"t":"mouse","x":0.5,"y":0.25}')
        ws.send_text('{"t":"wheel","dy":640}')
        ws.send_text('{"t":"text","text":"hi"}')
        ws.send_text('{"t":"nav","action":"reload"}')
        ws.send_text('{"t":"mouse","kind":"drag"}')  # 看不懂：丢掉，不断线
        ws.send_text('{"t":"key","key":"Enter"}')
        deadline = time.time() + 3
        while ("press", "Enter") not in calls and time.time() < deadline:
            time.sleep(0.02)
        assert ("Page.startScreencast", 480) in calls, calls  # 手机宽 390 → 480 桶，重挂
        assert ("click", 640.0, 200.0) in calls and ("wheel", 0.0, 640.0) in calls and ("type", "hi") in calls
        assert ("reload",) in calls and ("press", "Enter") in calls and ("save",) in calls
        assert service._watched_now("a-com")
        service._used["a-com"] = time.time() - service.IDLE - 10  # 很久没“操作”，但有人在看
        assert service._idle_out(time.time()) == []
        calls.clear()
    deadline = time.time() + 2
    while service._watched_now("a-com") and time.time() < deadline:
        time.sleep(0.02)
    assert not service._watched_now("a-com") and ("Page.stopScreencast", None) in calls  # 最后一人走：停推
    # 看着的时候会话被关 → 收到 4404
    with c.websocket_connect("/sessions/a-com/live", headers=H) as ws:
        assert ws.receive_bytes() == b"jpeg-1"
        c.delete("/sessions/a-com", headers=H)
        try:
            ws.receive_bytes()
            raise AssertionError("应当被关")
        except WebSocketDisconnect as e:
            assert e.code == live.CLOSE_NOT_OPEN
    assert "a-com" not in service._sessions
    print("✓ 实时画面 WS 通过")


pure()
wire()
