# 冒烟：v2.54 E2E 第十轮 B25 沙盒绝对路径 /workspace/… 在所有文件工具里都认（storage.sandbox_rel 唯一入口，safe_join 用它），
# display_file 一个都没交出去 → failed（步骤出错，模型不会以为交了 / 以为“交付工具不可用”）。无迁移。
# 运行：python tests/smoke_sandbox_paths.py
import os, sys, asyncio, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import storage, deliver, attachment_save, browser_shot
from app.agent.tools import load_builtin, REGISTRY
assert storage.sandbox_rel("/workspace/uploads/a.docx") == "uploads/a.docx"
assert storage.sandbox_rel("/workspace") == "" and storage.sandbox_rel("/workspace/") == ""
assert storage.sandbox_rel("/workspaces/x") is None and storage.sandbox_rel("uploads/a") is None and storage.sandbox_rel("/etc/passwd") is None
root = storage.project_dir("me").resolve()
(root / "uploads").mkdir(); (root / "uploads" / "简历_已改.docx").write_bytes(b"PK\x03\x04docx")
assert storage.safe_join(root, "/workspace/uploads/简历_已改.docx") == root / "uploads" / "简历_已改.docx"
assert storage.safe_join(root, "uploads/简历_已改.docx") == root / "uploads" / "简历_已改.docx"
try:
    storage.safe_join(root, "/workspace/../etc"); raise SystemExit("越界没拦")
except ValueError:
    pass
d = deliver.deliver("me", "/workspace/uploads/简历_已改.docx")
assert d.block["name"] == "简历_已改.docx", d
# 以前三处各写一遍的判断，现在都走 sandbox_rel：行为不变
assert attachment_save.target(root, "a.txt", "/workspace/docs/a.txt") == root / "docs" / "a.txt"
load_builtin()
tool = REGISTRY["display_file"]
ctx = NS(workspace="me")
r = asyncio.run(tool.run(ctx, paths=["/workspace/uploads/简历_已改.docx"]))
assert r.blocks and not r.failed, r
r = asyncio.run(tool.run(ctx, paths=["/workspace/nope.docx"]))
assert not r.blocks and r.failed == "没有交付" and "不存在" in r.content, r
r = asyncio.run(tool.run(ctx, paths=["uploads/简历_已改.docx", "nope.docx"]))
assert len(r.blocks) == 1 and not r.failed and "没有交付 nope.docx" in r.content, r
print("smoke_sandbox_paths OK")
