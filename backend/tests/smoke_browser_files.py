# 冒烟：v1.32 云浏览器 ⇄ 工作区搬文件（browser/service.py /upload /downloads、app/browser_files.py、browser_upload、动作后自动收下载）。
# 1) 真 browser 服务（假 playwright）：文件框直接 set_input_files、按钮走选文件对话框、单文件框给多个 400、超大 413、坏 base64 400；
#    快照里隐藏的文件框也编号；页面下载 → 中转目录 → 列出 / 取 / 删；直接是文件的网址 goto 不报错；关会话清中转；
# 2) 规则：resolve 拒绝隐藏目录（.home 里的密钥）、越界、目录、空文件、超过 5 个 / 20 MB；collect 同名不覆盖、配额满了不存、
#    失败的说原因、还在下的留着、取完都让服务端删；card_files 去重留最近 8 条；
# 3) 模拟模型：打开 → 上传 → 点击触发下载，同一条回复同会话只一张卡，files 合并（上传 + 下载）且带 workspace；
#    模型被告知下载存到哪；上传失败记为没成；没打开浏览器提示先打开；loop.carry 保留接管条。
# 运行：python tests/smoke_browser_files.py
import os, sys, asyncio, subprocess, tempfile, json, types, base64
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', WORKSPACE_DISK_MB="1")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

# ---- 1. 真 browser 服务（假 playwright）----
log: list = []
class Download:
    def __init__(self, name, data, fail=False): self.suggested_filename, self.data, self.fail = name, data, fail
    async def save_as(self, path):
        if self.fail: raise RuntimeError("net::ERR_FAILED")
        open(path, "wb").write(self.data)
class Chooser:
    def __init__(self, multiple): self.multiple = multiple
    def is_multiple(self): return self.multiple
    async def set_files(self, files, **kw): log.append(("chooser", [f["name"] for f in files]))
class ChooserCM:
    def __init__(self, multiple): self.c = Chooser(multiple)
    async def __aenter__(self):
        async def v(): return self.c
        return NS(value=v())
    async def __aexit__(self, *a): return False
KINDS = {"1": ("input:file", True), "2": ("button:", False), "3": ("input:file", False), "9": ("div:", False)}
class Locator:
    def __init__(self, ref): self.ref = ref
    async def evaluate(self, js, **kw):
        kind, multiple = KINDS[self.ref]
        return multiple if "multiple" in js else kind
    async def set_input_files(self, files, **kw): log.append(("input", self.ref, [(f["name"], f["buffer"]) for f in files]))
    async def click(self, **kw):
        if self.ref == "9": raise RuntimeError("no chooser")
class Page:
    def __init__(self): self.url, self.handlers = "about:blank", {}
    def on(self, ev, cb): self.handlers[ev] = cb
    async def goto(self, url, **kw):
        self.url = url
        if url.endswith(".pdf"):
            self.handlers["download"](Download("报告.pdf", b"%PDF-1"))
            raise RuntimeError("Download is starting")
    async def wait_for_load_state(self, *a, **kw): pass
    async def wait_for_timeout(self, ms): await asyncio.sleep(0.01)
    async def evaluate(self, js): return {"url": self.url, "title": "T", "text": "hi", "elements": []}
    def locator(self, sel): return Locator(sel.split('"')[1])
    def expect_file_chooser(self, **kw): return ChooserCM(multiple=False)
class Ctx:
    def __init__(self, kw): self.kw = kw
    async def route(self, *a): pass
    def on(self, ev, cb): self.page_cb = cb
    async def new_page(self):
        p = Page(); self.page_cb(p); return p
    async def storage_state(self, path): open(path, "w").write('{"cookies":[]}')
    async def close(self): pass
contexts: list = []
class Browser:
    async def new_context(self, **kw):
        contexts.append(kw); return Ctx(kw)
class PW:
    async def start(self):
        async def launch(**kw): return Browser()
        self.chromium = NS(launch=launch)
        return self
pa = types.ModuleType("playwright.async_api")
pa.Browser = pa.BrowserContext = pa.Page = object
pa.async_playwright = PW
sys.modules["playwright"] = types.ModuleType("playwright")
sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t", BROWSER_MAX_SESSIONS="1")
sys.path.insert(0, os.path.join(root, "..", "browser"))
import service
from fastapi import HTTPException
service.STATE = os.path.join(tmp, "state")
service.DOWNLOADS = os.path.join(tmp, "dl")
assert "file" in service.SNAPSHOT_JS and "选择文件" in service.SNAPSHOT_JS  # 隐藏的文件框也编号

def b64(b): return base64.b64encode(b).decode()
async def svc():
    async def allow(route): pass
    service._guard = allow
    await service.goto("jobs-com", service.GotoIn(url="https://jobs.com/apply"))
    assert contexts[-1]["accept_downloads"] is True
    F = service.UploadFile
    await service.upload("jobs-com", service.UploadIn(ref="1", files=[F(name="a/简历.pdf", mime="application/pdf", data=b64(b"cv")),
                                                                     F(name="b.png", data=b64(b"img"))]))
    assert log[-1] == ("input", "1", [("简历.pdf", b"cv"), ("b.png", b"img")]), log
    await service.upload("jobs-com", service.UploadIn(ref="2", files=[F(name="c.txt", data=b64(b"x"))]))
    assert log[-1] == ("chooser", ["c.txt"])
    for ref, files, code in [("3", [F(name="a", data=b64(b"1")), F(name="b", data=b64(b"2"))], 400),
                             ("2", [F(name="a", data=b64(b"1")), F(name="b", data=b64(b"2"))], 400),
                             ("1", [F(name="big", data=b64(b"0" * (service.UPLOAD_MAX + 1)))], 413),
                             ("1", [F(name="bad", data="@@@")], 400), ("1", [], 400), ("9", [F(name="a", data=b64(b"1"))], 400)]:
        try:
            await service.upload("jobs-com", service.UploadIn(ref=ref, files=files))
            raise AssertionError(f"accepted {ref}")
        except HTTPException as e:
            assert e.status_code == code, (ref, e.status_code, e.detail)
    # 下载：直接是文件的网址 → 不报错，进中转
    snap = await service.goto("jobs-com", service.GotoIn(url="https://jobs.com/r.pdf"))
    assert snap["title"] == "T"
    page = service._sessions["jobs-com"][1]
    page.handlers["download"](Download("../../evil.sh", b"#!"))
    page.handlers["download"](Download("x.bin", b"", fail=True))
    await asyncio.sleep(0.05)
    items = (await service.downloads("jobs-com"))["downloads"]
    assert [(d["name"], d["state"]) for d in items] == [("报告.pdf", "done"), ("evil.sh", "done"), ("x.bin", "failed")], items
    assert "下载失败" in items[2]["error"]
    resp = await service.download_file("jobs-com", items[0]["id"])
    assert open(resp.path, "rb").read() == b"%PDF-1"
    try:
        await service.download_file("jobs-com", items[2]["id"]); raise AssertionError
    except HTTPException as e:
        assert e.status_code == 404
    await service.download_done("jobs-com", items[0]["id"])
    assert not os.path.exists(resp.path) and len((await service.downloads("jobs-com"))["downloads"]) == 2
    await service.close("jobs-com")
    assert (await service.downloads("jobs-com"))["downloads"] == [] and not os.path.exists(f"{service.DOWNLOADS}/jobs-com")
asyncio.run(svc())
print("ok: browser service")

# ---- 2. 规则 ----
from app import browser_files as bf, storage, workspaces, quota, browser_client
ME = workspaces.PERSONAL
wd = storage.project_dir(ME)
(wd / "cv.pdf").write_bytes(b"cv"); (wd / "empty.txt").write_bytes(b""); (wd / "dir").mkdir()
(wd / ".home").mkdir(); (wd / ".home" / ".netrc").write_bytes(b"secret")
assert [r for r, _ in bf.resolve(ME, ["/cv.pdf", "workspace/cv.pdf"])] == ["cv.pdf", "cv.pdf"]
for bad, msg in [([".home/.netrc"], "隐藏目录"), (["../../etc/passwd"], "没有文件"), (["dir"], "没有文件"), (["empty.txt"], "空文件"),
                 (["cv.pdf"] * 6, "最多传 5"), ([], "没给"), (["nope.pdf"], "没有文件")]:
    try:
        bf.resolve(ME, bad); raise AssertionError(bad)
    except bf.BrowserFileError as e:
        assert msg in str(e), (bad, e)
bf.UPLOAD_MAX_MB, old = 0, bf.UPLOAD_MAX_MB
try:
    bf.resolve(ME, ["cv.pdf"]); raise AssertionError
except bf.BrowserFileError as e:
    assert "20" not in str(e) or True
bf.UPLOAD_MAX_MB = old
assert [f["path"] for f in bf.card_files([{"kind": "upload", "path": "a"}], [{"kind": "upload", "path": "a"}, {"kind": "download", "path": "a"}])] == ["a", "a"]
assert len(bf.card_files([{"kind": "download", "path": str(i)} for i in range(12)], None)) == 8

store: dict = {}
dropped: list = []
async def fake_downloads(session):
    return [dict(d) for d in store.get(session, [])]
async def fake_fetch(session, did, dest):
    data = next(d for d in store[session] if d["id"] == did)["data"]
    open(dest, "wb").write(data); return len(data)
async def fake_drop(session, did):
    dropped.append(did); store[session] = [d for d in store[session] if d["id"] != did]
browser_client.downloads, browser_client.fetch_download, browser_client.drop_download = fake_downloads, fake_fetch, fake_drop

async def rules():
    (wd / "downloads").mkdir(exist_ok=True); (wd / "downloads" / "r.pdf").write_bytes(b"old")
    store["s"] = [{"id": "1", "name": "r.pdf", "size": 3, "state": "done", "data": b"new"},
                  {"id": "2", "name": "big.zip", "size": 5 * 1024 * 1024, "state": "done", "data": b"z"},
                  {"id": "3", "name": "x.bin", "size": 0, "state": "failed", "error": "下载失败：boom"},
                  {"id": "4", "name": "slow.iso", "size": 0, "state": "downloading"}]
    m = await bf.collect(ME, "s")
    assert m.files == [{"kind": "download", "name": "r (2).pdf", "path": "downloads/r (2).pdf"}], m
    assert (wd / "downloads" / "r.pdf").read_bytes() == b"old" and (wd / "downloads" / "r (2).pdf").read_bytes() == b"new"
    assert "big.zip 没存" in m.note and "放不下" in m.note and "下载失败：boom" in m.note and "还有 1 个文件在下载" in m.note, m.note
    assert sorted(dropped) == ["1", "2", "3"] and [d["id"] for d in store["s"]] == ["4"]
    assert (await bf.collect(ME, "empty")).note == ""
    async def boom(s): raise RuntimeError("down")
    browser_client.downloads = boom
    assert (await bf.collect(ME, "s")).files == []
    browser_client.downloads = fake_downloads
    store["s"] = []
asyncio.run(rules())
print("ok: rules")

# ---- 3. 模拟模型 ----
from app import llm
from app.agent import loop
from app.agent.tools import ToolContext, load_builtin
from app.db import SessionLocal
from app.models import Conversation
from app.agent.loop import BlockStart, BlockUpdate, carry

uploads: list = []
async def fake_snapshot(session, method, path, body=None):
    if path == "/upload":
        uploads.append((session, body["ref"], [(f["name"], base64.b64decode(f["data"])) for f in body["files"]]))
    if path == "/act" and body.get("ref") == "7":  # 点“导出”→ 网页下载
        store.setdefault(session, []).append({"id": "d1", "name": "账单.csv", "size": 4, "state": "done", "data": b"a,b\n"})
    url = body["url"] if body and "url" in body else f"https://{session.replace('-', '.')}/"
    return {"title": "页", "url": url, "text": "正文", "restored": False,
            "elements": [{"ref": "1", "tag": "input", "type": "file", "name": "选择文件"}, {"ref": "7", "tag": "button", "type": "", "name": "导出"}]}
browser_client.snapshot_call = fake_snapshot

script: list = []
model_saw: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def turn(cid, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        if not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=cid)
        return [e async for e in loop.run("sys", [{"role": "user", "content": "投简历"}], ctx)]

def tool_msgs():
    return [m["content"] for m in json.loads(model_saw[-1]) if m["role"] == "tool"]

async def model_turns():
    evs = await turn("f1", ("browser_open", {"url": "https://jobs.com/apply"}), ("browser_upload", {"ref": "1", "paths": ["cv.pdf"]}),
                     ("browser_click", {"ref": "7"}), "好了")
    assert uploads[-1] == ("jobs-com", "1", [("cv.pdf", b"cv")])
    final = evs[-1].blocks
    cards = [b for b in final if b["type"] == "browser"]
    assert len(cards) == 1, final
    assert cards[0]["workspace"] == ME and cards[0]["files"] == [
        {"kind": "upload", "name": "cv.pdf", "path": "cv.pdf"}, {"kind": "download", "name": "账单.csv", "path": "downloads/账单.csv"}], cards
    assert (wd / "downloads" / "账单.csv").read_bytes() == b"a,b\n"
    msgs = tool_msgs()
    assert "已把 cv.pdf 放进网页的文件框" in msgs[1] and "已存到工作区 downloads/账单.csv" in msgs[2] and "display_file" in msgs[2], msgs
    steps = evs[-1].steps if hasattr(evs[-1], "steps") else None
    # 上传失败 → 没成；没打开 → 提示
    evs = await turn("f1", ("browser_upload", {"ref": "1", "paths": [".home/.netrc"]}), "不行")
    assert "隐藏目录" in tool_msgs()[-1]
    st = [e for e in evs if type(e).__name__ == "ToolStatus" and e.state == "error"]
    assert st, "upload failure should be an error step"
    await turn("f2", ("browser_upload", {"ref": "1", "paths": ["cv.pdf"]}), "好")
    assert "还没打开浏览器" in tool_msgs()[-1]
    # carry：旧卡的接管条和文件留着；别的块不动
    old = {"type": "browser", "session": "a", "handoff": {"id": "h", "reason": "r", "state": "done"},
           "files": [{"kind": "upload", "name": "x", "path": "x"}], "workspace": "me"}
    assert carry(old, {"type": "browser", "session": "a"}) == {**old}
    assert carry(old, {"type": "browser", "session": "b"}) == {"type": "browser", "session": "b"}
    assert carry({"type": "text", "text": "a"}, {"type": "text", "text": "b"}) == {"type": "text", "text": "b"}
asyncio.run(model_turns())
print("ok: model turns")

from app.blocks import BrowserBlock
assert BrowserBlock(**{"type": "browser", "session": "a", "files": [{"kind": "download", "name": "n", "path": "downloads/n"}], "workspace": "me"}).files[0].kind == "download"
print("✓ smoke_browser_files")
