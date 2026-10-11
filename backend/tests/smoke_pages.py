# 冒烟：Pages 下线 / 重新发布 / 改名（/api/pages）。无模型调用、无数据库表（元数据在 meta.json，无迁移）。
# 新页默认已发布、公开可看且 no-cache；下线 → 公开 404（与不存在相同）、列表仍在、链接不变；
# 智能体改写下线页 → 内容更新但仍下线、工具结果提示用户重新发布；重新发布 → 能看到新内容；
# 改名不动 updated（顺序不变）；空标题 422、不存在 404、非法 slug 404；老 meta 没 published 视为已发布。
# 运行：python tests/smoke_pages.py
import os, sys, json, asyncio, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, PUBLIC_URL="https://me.example")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import pages_store
from app.auth import require_user
from app.routes import pages as rp
from app.agent.builtin import pages as tool_pages

app = FastAPI(); app.include_router(rp.router); app.include_router(rp.public)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

a = pages_store.save("Trip Plan", "<h1>v1</h1>")
b = pages_store.save("Menu", "<h1>menu</h1>")
slug = a["slug"]
lst = c.get("/api/pages").json()
assert [p["id"] for p in lst] == [b["slug"], slug], lst
assert lst[1] == {"slug": slug, "title": "Trip Plan", "updated": a["updated"], "published": True, "id": slug,
                  "url": f"https://me.example/p/{slug}/"}, lst[1]

r = c.get(f"/p/{slug}/")
assert r.status_code == 200 and "v1" in r.text and r.headers["cache-control"] == "no-cache", r.headers
assert "sandbox" in r.headers["content-security-policy"]

# 下线
r = c.patch(f"/api/pages/{slug}", json={"published": False}).json()
assert r["published"] is False and r["url"] == f"https://me.example/p/{slug}/" and r["updated"] == a["updated"], r
gone = c.get(f"/p/{slug}/"); missing = c.get("/p/nope-000000/")
assert gone.status_code == 404 and missing.status_code == 404 and gone.text == missing.text
assert c.get(f"/p/{slug}").status_code == 404
assert [p["published"] for p in c.get("/api/pages").json()] == [True, False]

# 智能体改写下线页：保持下线，提示用户
from app.agent.tools import ToolContext
res = asyncio.run(tool_pages.publish_page(ToolContext(db=None), title="Trip Plan", html="<h1>v2</h1>", slug=slug))
assert "下线" in res.content and "重新发布" in res.content, res.content
assert pages_store.get(slug)["published"] is False and c.get(f"/p/{slug}/").status_code == 404
res2 = asyncio.run(tool_pages.publish_page(ToolContext(db=None), title="Menu", html="<h1>menu2</h1>", slug=b["slug"]))
assert res2.content.startswith("已发布") and pages_store.get(b["slug"])["published"] is True

# 重新发布：同一链接，新内容
r = c.patch(f"/api/pages/{slug}", json={"published": True}).json()
assert r["published"] is True
assert "v2" in c.get(f"/p/{slug}/").text

# 改名：不动 updated，顺序不变；只传 title 不动发布状态
before = [p["id"] for p in c.get("/api/pages").json()]
u0 = pages_store.get(slug)["updated"]
r = c.patch(f"/api/pages/{slug}", json={"title": "  东京五日  "}).json()
assert r["title"] == "东京五日" and r["updated"] == u0 and r["published"] is True, r
assert [p["id"] for p in c.get("/api/pages").json()] == before

assert c.patch(f"/api/pages/{slug}", json={"title": "  "}).status_code == 422
assert c.patch("/api/pages/nope-000000", json={"published": False}).status_code == 404
assert c.patch("/api/pages/BAD..slug", json={"published": False}).status_code == 404

# 老 meta（没有 published 字段）= 已发布
d = pages_store.PAGES / b["slug"]
m = json.loads((d / "meta.json").read_text()); m.pop("published"); (d / "meta.json").write_text(json.dumps(m))
assert pages_store.get(b["slug"])["published"] is True and c.get(f"/p/{b['slug']}/").status_code == 200

# 删除仍可用
assert c.delete(f"/api/pages/{slug}").json() == {"ok": True}
assert c.get(f"/p/{slug}/").status_code == 404 and len(c.get("/api/pages").json()) == 1
print("smoke_pages ok")
