# 冒烟：v2.30 浏览器截图存成文件交给用户（本地 E2E B5：模型想“截图给用户”只能去 image_search 冒充）。
# 1) 浏览器服务 /screen：默认 JPEG q60 视口不变；format=png；full=整页；整页太高 → clip 到 RENDER_PNG_MAX_H + X-Shot-Cut；坏 format 400；没会话 404。
# 2) 规则 app/browser_shot.py：默认 screenshots/<网站>.png；目录 / 结尾 / 无后缀 / .jpg；坏后缀、越界、隐藏目录拒绝；不覆盖 (2)；宽高解析；配额满。
# 3) 模拟模型：browser_open → browser_screenshot → 文件存进工作区 + 文件卡交付 + 时间线 change/detail；show=false 不交付；
#    没打开提示；服务坏了 → down 卡；描述里 image_search 指向 browser_screenshot。
# 运行：python tests/smoke_browser_screenshot.py
import os, sys, asyncio, subprocess, tempfile, json, types, struct
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', WORKSPACE_DISK_MB="1")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

def png(w, h): return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + b"\x00" * 20
def jpg(w, h): return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x00" * 10 + b"\xff\xd9"

# ---- 1. 浏览器服务 /screen（假 playwright）----
pa = types.ModuleType("playwright.async_api"); pa.Browser = pa.BrowserContext = pa.Page = object; pa.async_playwright = object
sys.modules["playwright"] = types.ModuleType("playwright"); sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t")
sys.path.insert(0, os.path.join(root, "..", "browser"))
import service
from fastapi import HTTPException
shots: list = []
class Page:
    height = 900
    viewport_size = {"width": 1280, "height": 800}
    async def evaluate(self, js): return self.height
    async def screenshot(self, **kw):
        shots.append(kw); return png(1280, 800) if kw["type"] == "png" else jpg(1280, 800)
async def svc():
    page = Page()
    service._browser = None
    service._sessions["a-com"] = (None, page)
    r = await service.screen("a-com")
    assert shots[-1] == {"type": "jpeg", "quality": 60} and r.media_type == "image/jpeg" and r.headers["x-shot-cut"] == "0", shots
    await service.screen("a-com", format="png")
    assert shots[-1] == {"type": "png"}
    await service.screen("a-com", format="png", full=True)
    assert shots[-1] == {"type": "png", "full_page": True}
    page.height = service.RENDER_PNG_MAX_H + 1
    r = await service.screen("a-com", format="jpeg", full=True, quality=200)
    assert shots[-1]["clip"] == {"x": 0, "y": 0, "width": 1280, "height": service.RENDER_PNG_MAX_H} and shots[-1]["quality"] == 95
    assert r.headers["x-shot-cut"] == "1"
    for kw, code in [({"format": "gif"}, 400), ({}, 404)]:
        try:
            await service.screen("a-com" if kw else "nope", **kw); raise AssertionError(kw)
        except HTTPException as e:
            assert e.status_code == code, (kw, e.status_code)
    del service._sessions["a-com"]
asyncio.run(svc())
print("ok: service /screen")

# ---- 2. 规则 ----
from app import browser_shot, browser_client, quota, storage, workspaces
from pathlib import Path
ME = workspaces.PERSONAL
wd = storage.project_dir(ME); wd.mkdir(parents=True, exist_ok=True)
T = browser_shot.target
rel = lambda p: p.relative_to(wd).as_posix()
assert (rel(T(wd, "example.com")[0]), T(wd, "example.com")[1]) == ("screenshots/example.com.png", "png")
assert rel(T(wd, "")[0]) == "screenshots/page.png"
assert rel(T(wd, "a b/c", "shots/")[0]) == "shots/a-b-c.png"
assert rel(T(wd, "x.com", "/workspace/out/首页")[0]) == "out/首页.png"
assert T(wd, "x.com", "a.JPG")[1] == "jpeg" and T(wd, "x.com", "a.jpeg")[1] == "jpeg"
(wd / "pics").mkdir()
assert rel(T(wd, "x.com", "pics")[0]) == "pics/x.com.png"
for bad, word in [("a.gif", ".png / .jpg"), ("../x.png", "工作区外面"), ("/etc/x.png", "工作区外面"), (".home/x.png", "隐藏目录")]:
    try:
        T(wd, "x.com", bad); raise AssertionError(bad)
    except browser_shot.ShotError as e:
        assert word in str(e), (bad, str(e))
p = wd / "screenshots" / "x.com.png"; p.parent.mkdir(parents=True); p.write_bytes(b"old")
assert browser_shot.free(p).name == "x.com (2).png"
assert browser_shot.dims(png(10, 20)) == (10, 20) and browser_shot.dims(jpg(30, 40)) == (30, 40) and browser_shot.dims(b"xx") == (None, None)
s = browser_shot.save(ME, browser_shot.free(p), png(10, 20), "png", False, False, first=p)
assert s.rel == "screenshots/x.com (2).png" and s.renamed and (s.width, s.height) == (10, 20) and p.read_bytes() == b"old"
assert "原名已被占用" in browser_shot.for_model(s, True) and "不用再贴图" in browser_shot.for_model(s, True)
assert "read_file" in browser_shot.for_model(s, False) and browser_shot.detail(s) == "screenshots/x.com (2).png · 10×20"
cut = browser_shot.Shot("a.png", 5, "png", None, None, True, True, False)
assert "整页长图" in browser_shot.for_model(cut, True) and str(browser_shot.MAX_H) in browser_shot.for_model(cut, True)
assert browser_shot.MAX_H == service.RENDER_PNG_MAX_H
for data, word in [(b"", "空的"), (b"0" * (2 * 1024 * 1024), "没有存")]:
    try:
        browser_shot.save(ME, wd / "big.png", data, "png", False, False); raise AssertionError(word)
    except browser_shot.ShotError as e:
        assert word in str(e), str(e)
assert not (wd / "big.png").exists()
for f in (wd / "screenshots").iterdir(): f.unlink()
quota.forget(ME)
print("ok: rules")

# ---- 3. 模拟模型 ----
from app import llm
from app.agent import loop
from app.agent.tools import ToolContext, load_builtin, REGISTRY
from app.turn_changes import Tracker
from app.db import SessionLocal
from app.models import Conversation

calls: list = []
async def fake_snapshot(session, method, path, body=None):
    return {"title": "Example Domain", "url": "https://example.com/", "text": "Example Domain", "restored": False, "elements": []}
down = {"on": False}
async def fake_call(session, method, path, json=None):
    calls.append(path)
    if down["on"]:
        raise browser_client.BrowserDown("云浏览器没能启动：缺少系统库 libnss3.so。马上重试也没用；请告诉用户需要管理员修复。")
    full = "full=true" in path
    return NS(status_code=200, content=png(1280, 3000 if full else 800), headers={"x-shot-cut": "0"})
browser_client.snapshot_call = fake_snapshot
browser_client.call = fake_call
async def no_downloads(session): return []
browser_client.downloads = no_downloads

script: list = []
model_saw: list[str] = []
n = [0]
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            n[0] += 1
            yield chunk(tool=[NS(index=0, id=f"c{n[0]}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
desc = {t.name: t.description for t in REGISTRY.values()} if isinstance(REGISTRY, dict) else {t.name: t.description for t in REGISTRY}
assert "browser_screenshot" in desc["image_search"] and "browser_screenshot" in desc["browser_look"]

async def turn(cid, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        if not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=cid, changes=Tracker())
        return [e async for e in loop.run("sys", [{"role": "user", "content": "截个图给我"}], ctx)]
def tool_msgs():
    return [m["content"] for m in json.loads(model_saw[-1]) if m["role"] == "tool"]
def statuses(evs, name):
    return [e for e in evs if type(e).__name__ == "ToolStatus" and e.name == name and e.state != "running"]

async def model_turns():
    evs = await turn("s1", ("browser_open", {"url": "https://example.com"}), ("browser_screenshot", {}), "截好了")
    assert calls[-1] == "/screen?format=png&full=false", calls
    f = wd / "screenshots" / "example.com.png"
    assert f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    msg = tool_msgs()[-1]
    assert "已把当前画面截图存到 screenshots/example.com.png" in msg and "1280×800" in msg, msg
    files = [b for b in evs[-1].blocks if b["type"] == "file"]
    assert len(files) == 1 and files[0]["name"] == "example.com.png", evs[-1].blocks
    st = statuses(evs, "browser_screenshot")[-1]
    assert st.state == "done" and "screenshots/example.com.png · 1280×800" in json.dumps(st.__dict__, ensure_ascii=False), st
    # 第二张整页 + 不交付 + jpg：不覆盖第一张
    evs = await turn("s1", ("browser_screenshot", {"full_page": True, "show": False}), ("browser_screenshot", {"path": "a/首页.jpg"}), "好")
    assert calls[-2] == "/screen?format=png&full=true" and calls[-1].startswith("/screen?format=jpeg&full=false&quality=85"), calls
    assert (wd / "screenshots" / "example.com (2).png").exists() and (wd / "a" / "首页.jpg").exists()
    msgs = tool_msgs()
    assert "整页长图" in msgs[-2] and "没有交给用户" in msgs[-2] and "1280×3000" in msgs[-2], msgs
    assert len([b for b in evs[-1].blocks if b["type"] == "file"]) == 1
    # 坏后缀 → 没成，不调服务
    k = len(calls)
    evs = await turn("s1", ("browser_screenshot", {"path": "x.gif"}), "不行")
    assert len(calls) == k and "没截成" in tool_msgs()[-1] and statuses(evs, "browser_screenshot")[-1].state == "error"
    # 没打开浏览器
    await turn("s2", ("browser_screenshot", {}), "好")
    assert "还没打开浏览器" in tool_msgs()[-1]
    # 服务坏了 → down 卡
    down["on"] = True
    evs = await turn("s1", ("browser_screenshot", {}), "坏了")
    cards = [b for b in evs[-1].blocks if b["type"] == "browser"]
    assert cards and cards[-1].get("down") == "缺少系统库 libnss3.so", evs[-1].blocks
asyncio.run(model_turns())
print("ok: model turns")
print("ALL OK")
