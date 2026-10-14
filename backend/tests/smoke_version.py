# 冒烟：v2.86 品牌与版本唯一来源（brand/brand.json + VERSION → brand/sync.py；GET /api/version）。
# sync --check 通过（仓库里所有名字/版本与来源一致）、再跑一次无改动（幂等）；/api/version 公开、字段齐、与 VERSION 一致；
# 系统提示自称 Toyuis；两步验证 issuer = 产品名；git 最新 tag 若指向 HEAD 必须等于 VERSION 前两段。
# 运行：python tests/smoke_version.py
import os, sys, subprocess, json
os.environ.update(DATABASE_URL="sqlite+aiosqlite:///:memory:", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.join(here, "..")
repo = os.path.abspath(os.path.join(root, ".."))
sys.path.insert(0, root)

r = subprocess.run([sys.executable, "brand/sync.py", "--check"], cwd=repo, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
version = open(os.path.join(repo, "VERSION")).read().strip()
name = json.load(open(os.path.join(repo, "brand/brand.json")))["name"]

from app import version as v
assert (v.APP_NAME, v.VERSION) == (name, version), (v.APP_NAME, v.VERSION)
major, minor, patch = map(int, version.split("."))
assert v.BUILD == major * 10000 + minor * 100 + patch

from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
body = c.get("/api/version").json()        # 不带 token
assert body == {"name": name, "version": version, "build": v.BUILD, "min_client": v.MIN_CLIENT}, body
assert tuple(map(int, v.MIN_CLIENT.split("."))) <= (major, minor, patch)  # 服务器自己的客户端总是兼容
assert app.title == name

from app.config import settings
assert settings.system_prompt.startswith(f"你是 {name}"), settings.system_prompt[:20]
from app import two_factor as tf
assert tf.ISSUER == name and f"issuer={name}" in tf.uri("ABC", "u")

# 写进各端的产品名
for rel, needle in [("app/android/app/src/main/AndroidManifest.xml", f'android:label="{name}"'),
                    ("frontend/index.html", f"<title>{name}</title>"),
                    ("app/lib/brand.dart", f"appName = '{name}'"), ("frontend/src/brand.ts", f'appName = "{name}"'),
                    ("app/pubspec.yaml", f"version: {version}+{v.BUILD}")]:
    assert needle in open(os.path.join(repo, rel), encoding="utf-8").read(), rel

# tag 与 VERSION 一致：指向 HEAD 的 tag 对 HEAD 里提交的 VERSION（工作区改了还没提交时不算；没有 git 或老提交没有 VERSION 时跳过）
t = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=repo, capture_output=True, text=True)
committed = subprocess.run(["git", "show", "HEAD:VERSION"], cwd=repo, capture_output=True, text=True)
if t.returncode == 0 and committed.returncode == 0:
    cm, cn, _ = committed.stdout.strip().split(".")
    for tag in t.stdout.split():
        assert tag == f"v{cm}.{cn}", f"tag {tag} 与提交里的 VERSION {committed.stdout.strip()} 不一致"
print("smoke_version OK")
