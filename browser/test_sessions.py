"""会话上限冒烟测试（不需要真 Chromium）：python3 browser/test_sessions.py
BROWSER_MAX_SESSIONS=1 时开第二个会话会先存好第一个的登录状态再关掉它。"""
import asyncio, os, sys, tempfile, types

saved, closed = [], []


class Page(str):
    def on(self, *a): pass


class Ctx:
    def __init__(self, n): self.n = n
    async def route(self, *a): pass
    def on(self, *a): pass
    async def new_page(self): return Page(f"page-{self.n}")
    async def storage_state(self, path): saved.append(os.path.basename(path))
    async def close(self): closed.append(self.n)


class Browser:
    n = 0
    async def new_context(self, **kw):
        Browser.n += 1
        return Ctx(Browser.n)


class PW:
    chromium = types.SimpleNamespace(launch=None)
    async def start(self):
        async def launch(**kw): return Browser()
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

asyncio.run(main())
