"""会话上限冒烟测试（不需要真 Chromium）：python3 browser/test_sessions.py
BROWSER_MAX_SESSIONS=1 时开第二个会话会先存好第一个的登录状态再关掉它。"""
import asyncio, os, sys, tempfile, types

saved, closed = [], []


class Page(str):
    url = "about:blank"
    def on(self, *a): pass
    def is_closed(self): return False


class Ctx:
    def __init__(self, n): self.n = n
    async def route(self, *a): pass
    def on(self, *a): pass
    pages: list = []
    async def new_page(self):
        p = Page(f"page-{self.n}")
        self.pages = [p]
        return p
    async def storage_state(self, path): saved.append(os.path.basename(path))
    async def close(self): closed.append(self.n)


class Browser:
    n = 0
    alive = True
    def is_connected(self): return self.alive
    async def new_context(self, **kw):
        Browser.n += 1
        return Ctx(Browser.n)


launch_fail: list[str] = []  # 非空 → 下次 launch 抛这条错（模拟缺系统库）
launches = [0]


class PW:
    chromium = types.SimpleNamespace(launch=None)
    async def start(self):
        async def launch(**kw):
            launches[0] += 1
            if launch_fail:
                raise RuntimeError(launch_fail[0])
            return Browser()
        self.chromium = types.SimpleNamespace(launch=launch)
        return self


pa = types.ModuleType("playwright.async_api")
pa.Browser = pa.BrowserContext = pa.Page = object
pa.async_playwright = PW
sys.modules["playwright"] = types.ModuleType("playwright")
sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t", BROWSER_MAX_SESSIONS="1")
sys.path.insert(0, os.path.dirname(__file__))
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()


async def main():
    assert service.MAX_SESSIONS == 1
    assert await service._session("a") == "page-1"
    assert await service._session("a") == "page-1"      # 同名复用
    assert await service._session("b") == "page-2"      # 超出上限 → 关 a
    assert list(service._sessions) == ["b"], service._sessions
    assert saved == ["a.json"] and closed == [1], (saved, closed)
    assert "a" not in service._used
    print("✓ 浏览器会话上限测试通过")
    # 登录标记：没登录过 → expired 不记；登录 → 过期 → 再登录清掉过期；列表不把 .meta.json 当会话；forget 一起删
    assert service._set_meta("c", "expired") == {"signed_in": None, "expired": None}
    m = service._set_meta("c", "signed_in")
    assert m["signed_in"] and m["expired"] is None
    m2 = service._set_meta("c", "expired")
    assert m2["expired"] and m2["signed_in"] == m["signed_in"]
    assert service._set_meta("c", "expired")["expired"] == m2["expired"]  # 过期时间只记第一次
    open(service._state_path("c"), "w").write('{"cookies": []}')
    names = [x["name"] for x in (await service.sessions())["sessions"]]
    assert sorted(names) == ["b", "c"], names
    c = next(x for x in (await service.sessions())["sessions"] if x["name"] == "c")
    assert c["expired"] == m2["expired"] and c["signed_in"] == m["signed_in"]
    assert service._set_meta("c", "signed_in")["expired"] is None
    await service.close("c", forget=True)
    assert not os.path.exists(service._meta_path("c")) and service._meta("c") == {"signed_in": None, "expired": None}
    print("✓ 登录标记测试通过")
    await launch_tests()


async def launch_tests():
    """Chromium 起不来 → 503 + 一句原因（不是 500）；30 秒内不再硬试；进程死了 → 会话作废、重起。"""
    from fastapi import HTTPException
    r = service.launch_reason
    assert "libatk-1.0.so.0" in r("BrowserType.launch: Target page, context or browser has been closed\n"
                                  "chrome: error while loading shared libraries: libatk-1.0.so.0: cannot open shared object file")
    assert "缺少系统库" in r("Host system is missing dependencies to run browsers.")
    assert "版本" in r("BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium-1134/chrome-linux/chrome")
    assert "内存" in r("spawn ENOMEM")
    assert "boom" in r("╔══╗\nboom happened\n╚══╝") and "重试也没用" in r("x")
    # 现在的浏览器“崩了”：会话作废，下次重起新进程
    service._browser.alive = False
    launch_fail.append("chrome: error while loading shared libraries: libnss3.so: cannot open shared object file")
    for _ in range(2):  # 第二次在冷却期里，不再真去 launch
        try:
            await service._session("d")
            raise AssertionError("应当 503")
        except HTTPException as e:
            assert e.status_code == 503 and "libnss3.so" in e.detail, e.detail
    assert launches[0] == 2 and service._sessions == {} and service._browser is None, launches
    try:
        await service.screen("b")  # 会话已作废 → 404，不是对死页面截图的 500
        raise AssertionError("应当 404")
    except HTTPException as e:
        assert e.status_code == 404
    launch_fail.clear()
    service._launch_error = (0, "")  # 冷却过了
    assert (await service._session("d")).startswith("page-") and launches[0] == 3 and service._launch_error is None
    print("✓ 浏览器起不来 / 崩溃恢复测试通过")

asyncio.run(main())
