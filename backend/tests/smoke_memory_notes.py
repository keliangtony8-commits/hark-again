# 冒烟：v2.21 大脑 (az) 记忆笔记——memory_notes 规则 + memory_note 工具 + search_memory 合并 + 上下文目录 + REST + 迁移。模拟模型。
# - 路径：去 / memory/ .md、kind 默认文件夹、两层上限、坏字符、大小写不敏感唯一、只给名字唯一同名才认；
# - write/append/edit（唯一、replace_all、找不到）/move（标题跟名字走）/delete；正文超长报错不截断；篇数上限；
# - 目录：上下文 STABLE 段有目录不含正文、超过 INDEX_MAX 提示还有；没有笔记不出现；
# - search：词全中优先、两字词重合、片段；search_memory 带“笔记里相关的”和 detail；
# - 一轮对话：模型 memory_note append 新建 → edit → read（结果给全文）→ 错误路径 failed；
# - REST：POST/GET/PATCH/DELETE，409 重名、422 坏路径；迁移 down/up。
# 运行：python tests/smoke_memory_notes.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, memory_notes as mn
from app.agent import runner
from app.agent.context import build_system_prompt
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, MemoryNote, Message

LOOP = asyncio.new_event_loop()
def run(c):
    return LOOP.run_until_complete(c)
async def no_embed(texts):
    raise RuntimeError("no embeddings")
llm.embed = no_embed

# --- 路径规则 ---
assert mn.normalize("/memory/people/张三.md") == "people/张三"
assert mn.normalize("张三", "contact") == "people/张三" and mn.normalize("学校", "place") == "locations/学校"
assert mn.normalize("考研计划", "project") == "考研计划" and mn.normalize("work/abc", "contact") == "work/abc"
assert mn.normalize(" people / 李四 ") == "people/李四"
for bad in ["", "/", "a//b", "../x", ".hidden", "a/b/c", "a:b", "x" * 41]:
    try:
        mn.normalize(bad)
        raise AssertionError(bad)
    except mn.NoteError:
        pass
assert mn.kind_for("people/张三", None) == "contact" and mn.kind_for("locations/x", None) == "place"
assert mn.kind_for("x", "bogus") == "misc" and mn.kind_for("x", "event") == "event"
assert mn.first_line("\n# 张三\n- 同学") == "张三" and mn.first_line("") == ""
assert mn.first_line("a" * 100).endswith("…")

async def go(fn, *a, **k):
    async with SessionLocal() as db:
        return await fn(db, *a, **k)

n = run(go(mn.create, "张三", "# 张三\n- 本科室友\n- 生日 3 月 5 日", kind="contact"))
assert n.path == "people/张三" and n.kind == "contact" and n.title == "张三"
try:
    run(go(mn.create, "People/张三"))
    raise AssertionError("dup")
except mn.NoteError as e:
    assert "已经有" in str(e)
assert run(go(mn.find, "PEOPLE/张三")).id == n.id
assert run(go(mn.find, "张三")).id == n.id            # 只给名字，唯一同名
assert run(go(mn.find, "张三", "contact")).id == n.id
assert run(go(mn.find, "王五")) is None and run(go(mn.find, "a//b")) is None

# write：覆盖返回旧正文
n2, prev = run(go(mn.write, "people/张三", "# 张三\n- 本科室友\n- 生日 3 月 5 日\n- 在深圳工作"))
assert prev.startswith("# 张三") and n2.body.endswith("深圳工作")
n3, prev = run(go(mn.write, "考研计划", "目标：浙大计算机", title="考研", kind="project"))
assert prev is None and n3.title == "考研" and n3.kind == "project"
# append
n4, created = run(go(mn.append, "考研计划", "- 10 月开始刷题"))
assert not created and n4.body == "目标：浙大计算机\n- 10 月开始刷题"
_, created = run(go(mn.append, "学校", "在杭州", kind="place"))
assert created
try:
    run(go(mn.append, "学校", "  "))
    raise AssertionError
except mn.NoteError:
    pass
# edit
n5, k = run(go(mn.edit, "people/张三", "深圳", "广州"))
assert k == 1 and "广州工作" in n5.body
for old in ["上海", "", "- "]:
    try:
        run(go(mn.edit, "people/张三", old, "x"))
        raise AssertionError(old)
    except mn.NoteError as e:
        assert ("没找到" in str(e)) or ("不能为空" in str(e)) or ("出现了" in str(e)), e
n6, k = run(go(mn.edit, "people/张三", "- ", "* ", replace_all=True))
assert k == 3 and "* 本科室友" in n6.body
# 超长不截断
try:
    run(go(mn.write, "people/张三", "x" * (mn.BODY_MAX + 1)))
    raise AssertionError
except mn.NoteError as e:
    assert "最多" in str(e)
assert run(go(mn.find, "people/张三")).body.startswith("# 张三")
# move：标题等于名字时跟着改
m, was = run(go(mn.move, "张三", "people/张老三"))
assert was == "people/张三" and m.path == "people/张老三" and m.title == "张老三" and m.kind == "contact"
m, _ = run(go(mn.move, "考研计划", "考研"))
assert m.title == "考研" and m.kind == "project"
try:
    run(go(mn.move, "考研", "people/张老三"))
    raise AssertionError
except mn.NoteError:
    pass
# delete
run(go(mn.create, "临时"))
assert run(go(mn.delete, "临时")).path == "临时" and run(go(mn.find, "临时")) is None

# --- search ---
hits = run(go(mn.search, "室友 生日"))
assert [h.note.path for h in hits] == ["people/张老三"] and "室友" in hits[0].snippet
hits = run(go(mn.search, "浙大"))
assert [h.note.path for h in hits] == ["考研"]
assert run(go(mn.search, "火星")) == [] and run(go(mn.search, "")) == []
assert "memory_note read" in mn.search_text(run(go(mn.search, "杭州")))

# --- 上下文目录 ---
def ptext(q="hi"):
    async def g():
        async with SessionLocal() as db:
            return (await build_system_prompt(db, None, q)).text()
    return run(g())
pt = ptext()
assert "用户的记忆笔记" in pt and "- people/张老三：张三" in pt and "- 考研：目标：浙大计算机" in pt, pt[-800:]
assert "10 月开始刷题" not in pt  # 正文不进上下文
assert "memory_note" in settings.system_prompt and "可能过时" in settings.system_prompt

# --- 工具 ---
load_builtin()
t = REGISTRY["memory_note"]
assert not t.deferred and not t.parallel
script: list = []
tool_msgs: list[dict] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
rnd = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    rnd[0] += 1
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"r{rnd[0]}c{i}", function=NS(name=nm, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (nm, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, text, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = run(turn("c1", "我妈妈叫李华，生日 6 月 1 日，在老家开花店", [
    [("memory_note", {"action": "append", "path": "妈妈", "kind": "contact", "body": "# 妈妈（李华）\n- 生日 6 月 1 日"})],
    [("memory_note", {"action": "edit", "path": "people/妈妈", "old": "- 生日 6 月 1 日", "new": "- 生日 6 月 1 日\n- 在老家开花店"})],
    [("memory_note", {"action": "read", "path": "妈妈"}), ],
    [("memory_note", {"action": "read", "path": "爸爸"})],
    [("memory_note", {"action": "fly"})],
    [("memory_note", {"action": "list"})],
    "记下了。"]))
steps = [s for s in reply.steps if s["tool"] == "memory_note"]
assert steps[0]["state"] == "done" and steps[0]["detail"] == "people/妈妈 · 新建了", steps[0]
assert steps[1]["detail"] == "people/妈妈 · 改了 1 处", steps[1]
assert steps[2]["detail"] == "people/妈妈" and "在老家开花店" in tool_msgs[2]["content"] and "（人，" in tool_msgs[2]["content"]
assert steps[3]["state"] == "error" and "没有这篇" in steps[3]["note"], steps[3]
assert steps[4]["state"] == "error"
assert steps[5]["detail"] == "4 篇" and "people/妈妈" in tool_msgs[5]["content"], tool_msgs[5]

# search_memory 也搜笔记
reply = run(turn("c2", "我妈开什么店", [[("search_memory", {"query": "花店"})], "花店。"]))
s = [x for x in reply.steps if x["tool"] == "search_memory"][0]
assert s["detail"] == "花店 · 0 条 + 1 篇笔记", s
assert "笔记里相关的" in tool_msgs[-1]["content"] and "people/妈妈" in tool_msgs[-1]["content"]

# 目录上限
async def many():
    async with SessionLocal() as db:
        for i in range(mn.INDEX_MAX):
            db.add(MemoryNote(path=f"x{i:02d}", title=f"x{i:02d}", kind="misc", body=f"第 {i} 篇"))
        await db.commit()
run(many())
pt = ptext()
assert f"还有 {4 + mn.INDEX_MAX - mn.INDEX_MAX} 篇没列出" in pt, pt[-300:]

# 篇数上限
old_max = mn.NOTES_MAX
mn.NOTES_MAX = 4 + mn.INDEX_MAX
try:
    run(go(mn.create, "满了"))
    raise AssertionError
except mn.NoteError as e:
    assert "最多" in str(e)
mn.NOTES_MAX = old_max

# --- REST ---
from fastapi.testclient import TestClient
from app.main import app
from app.auth import require_user
app.dependency_overrides[require_user] = lambda: "u"
with TestClient(app) as c:
    r = c.post("/api/memory-notes", json={"path": "王老师", "kind": "contact", "body": "导师"})
    assert r.status_code == 200 and r.json()["path"] == "people/王老师", r.text
    nid = r.json()["id"]
    assert c.post("/api/memory-notes", json={"path": "people/王老师"}).status_code == 409
    assert c.post("/api/memory-notes", json={"path": "a/b/c"}).status_code == 422
    lst = c.get("/api/memory-notes").json()
    assert lst[0]["id"] == nid and "updated_at" in lst[0] and "body" in lst[0]
    r = c.patch(f"/api/memory-notes/{nid}", json={"body": "导师，研究 NLP", "title": "王老师（导师）"})
    assert r.json()["body"] == "导师，研究 NLP" and r.json()["title"] == "王老师（导师）"
    assert c.patch(f"/api/memory-notes/{nid}", json={"path": "people/妈妈"}).status_code == 409
    assert c.patch(f"/api/memory-notes/{nid}", json={"body": "x" * (mn.BODY_MAX + 1)}).status_code == 422
    assert c.get(f"/api/memory-notes/{nid}").json()["path"] == "people/王老师"
    assert c.delete(f"/api/memory-notes/{nid}").status_code == 200
    assert c.get(f"/api/memory-notes/{nid}").status_code == 404

# --- 迁移 ---
subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0053"], cwd=root, check=True, capture_output=True)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
print("smoke_memory_notes OK")
