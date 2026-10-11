# 冒烟：v0.91 建议卡配图 + 原页链接（offer_on_home image / url，迁移 0021）。不联网：探图用假函数。
# - 好图 + 原页 → 卡上 image_url / link_url；接口 /api/cards 带回；manage_home list 标“有配图 · 原页”；
# - 图打不开 → 卡照放、不带图、告诉模型；图地址不是 http(s) → 同样不带图（不拒卡）；
# - 原页链接不是 http(s) → 整张拒绝（中文原因），不建卡；
# - 同标题重新提议没给图/链接 → 清掉（新的一件事）；接口新建拒绝非 http(s) 配图（422）。
# 运行：python tests/smoke_offer_media.py
import os, sys, asyncio, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.agent.builtin import home as home_tool
from app.auth import require_user
from app.db import SessionLocal
from app.routes.resources import routers

probed: list[str] = []
async def fake_probe(client, url):
    probed.append(url)
    return "good" in url
home_tool.probe_image = fake_probe
load_builtin()
schema = REGISTRY["offer_on_home"].parameters["properties"]
assert "image" in schema and "url" in schema, schema

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content
cards = lambda: {x["title"]: x for x in c.get("/api/cards").json() if x["kind"] == "action" and not x["dismissed"]}

IMG, PAGE = "https://shop.example.com/good/airpods.jpg", "https://shop.example.com/item/42"
# 1) 好图 + 原页
out = asyncio.run(call("offer_on_home", title="耳机降价了", reason="比上周低 120 元。", prompt="去 shop.example.com 买 AirPods，≤ 899 元",
                       label="帮我下单", image=IMG, url=PAGE))
assert out.startswith("已放到 Home") and "没放图" not in out, out
card = cards()["耳机降价了"]
assert card["image_url"] == IMG and card["link_url"] == PAGE, card
assert probed == [IMG]
listing = asyncio.run(call("manage_home", action="list"))
assert "· 有配图 · 原页 https://shop.example.com/item/42" in listing, listing

# 2) 打不开的图 / 非 http 图 → 照放、不带图
out = asyncio.run(call("offer_on_home", title="续费校园网", prompt="续费", image="https://x.example.com/bad.png"))
assert "配图打不开" in out and cards()["续费校园网"]["image_url"] is None, out
out = asyncio.run(call("offer_on_home", title="看展", prompt="订票", image="data:image/png;base64,xx"))
assert "不是真实网址" in out and cards()["看展"]["image_url"] is None, out
assert len(probed) == 2  # data: 不去探

# 3) 原页链接不合格 → 拒卡
out = asyncio.run(call("offer_on_home", title="坏链接", prompt="x", url="javascript:alert(1)"))
assert "原页链接" in out and "坏链接" not in cards(), out

# 4) 同标题重提不带图 → 清掉
out = asyncio.run(call("offer_on_home", title="耳机降价了", prompt="再看看价格"))
assert out.startswith("已更新 Home"), out
card = cards()["耳机降价了"]
assert card["image_url"] is None and card["link_url"] is None, card

# 5) 接口
r = c.post("/api/cards", json={"kind": "action", "title": "接口卡", "image_url": "ftp://a/b.png"})
assert r.status_code == 422, r.text
r = c.post("/api/cards", json={"kind": "action", "title": "接口卡", "image_url": IMG, "link_url": PAGE})
assert r.status_code == 200 and r.json()["image_url"] == IMG, r.json()
print("ok")
