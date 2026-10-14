"""品牌与版本的唯一同步入口（v2.86，home-redesign §K）。

唯一来源只有两个文件：brand/brand.json（产品名）和 VERSION（语义化版本 大版本.功能轮.修复）。
本脚本把它们写进所有手写过名字 / 版本的地方，别处不许手改：
  Android label、iOS CFBundleDisplayName/CFBundleName、App pubspec version 与 lib/brand.dart、
  网页 index.html <title>、manifest name/short_name、package.json version 与 src/brand.ts、后端 app/version.py。
构建号 = 版本数字化（2.86.0 → 28600）：确定、单调递增，不随提交变化，所以跑两次没有改动（幂等）。

用法（在 assistant/ 下）：
  python3 brand/sync.py            写入
  python3 brand/sync.py --check    只检查，有不一致就列出并退出 1（scripts/check_version.sh 用）
  python3 brand/sync.py --icons    写入并重新生成图标（brand/make_icons.py，需要 Pillow）
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def load() -> tuple[str, str, int]:
    name = json.load(open(os.path.join(ROOT, "brand", "brand.json"), encoding="utf-8"))["name"].strip()
    version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
    m = VERSION_RE.match(version)
    if not name or not m:
        sys.exit(f"brand.json 的 name 不能为空、VERSION 必须是 X.Y.Z（现在是 {version!r}）")
    major, minor, patch = (int(x) for x in m.groups())
    if minor > 99 or patch > 99:
        sys.exit("功能轮和修复号都不能超过 99（构建号按 major*10000+minor*100+patch 算）")
    return name, version, major * 10000 + minor * 100 + patch


def _sub(text: str, pattern: str, repl: str, path: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"{path}：找不到要替换的位置（{pattern}）")
    return new


def plan(name: str, version: str, build: int) -> dict[str, str]:
    """每个目标文件 → 应有的完整内容。"""
    out: dict[str, str] = {}

    def edit(rel: str, *subs: tuple[str, str]) -> None:
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for pat, repl in subs:
            text = _sub(text, pat, repl, rel)
        out[rel] = text

    edit("app/android/app/src/main/AndroidManifest.xml", (r'android:label="[^"]*"', f'android:label="{name}"'))
    edit("app/ios/Runner/Info.plist",
         (r"(<key>CFBundleDisplayName</key>\s*<string>)[^<]*(</string>)", rf"\g<1>{name}\g<2>"),
         (r"(<key>CFBundleName</key>\s*<string>)[^<]*(</string>)", rf"\g<1>{name}\g<2>"))
    edit("app/pubspec.yaml", (r"^version: .*$", f"version: {version}+{build}"))
    edit("frontend/index.html", (r"<title>[^<]*</title>", f"<title>{name}</title>"))
    manifest = json.load(open(os.path.join(ROOT, "frontend/public/manifest.webmanifest"), encoding="utf-8"))
    manifest["name"] = manifest["short_name"] = name
    out["frontend/public/manifest.webmanifest"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    edit("frontend/package.json", (r'^(  "version": )"[^"]*"', rf'\g<1>"{version}"'))

    head = "由 brand/sync.py 生成，别手改：改名字改 brand/brand.json，改版本改 VERSION，再跑 python3 brand/sync.py。"
    out["app/lib/brand.dart"] = (
        f"// {head}\n"
        f"const appName = '{name}';\n"
        f"const appVersion = '{version}';\n"
        f"const appBuild = {build};\n")
    out["frontend/src/brand.ts"] = (
        f"// {head}\n"
        f'export const appName = "{name}";\n'
        f'export const appVersion = "{version}";\n'
        f"export const appBuild = {build};\n")
    # 后端：MIN_CLIENT 是手写常量（只在协议不兼容时提高），保留文件里现有的值
    vpath = os.path.join(ROOT, "backend/app/version.py")
    min_client = "2.86.0"
    if os.path.exists(vpath):
        m = re.search(r'^MIN_CLIENT = "([^"]+)"', open(vpath, encoding="utf-8").read(), re.M)
        if m:
            min_client = m.group(1)
    out["backend/app/version.py"] = (
        f'"""{head}\n'
        'MIN_CLIENT 例外：手写，只在新服务器和旧客户端协议不兼容时提高（GET /api/version 发给客户端，低于它的客户端提示更新）。"""\n'
        f'APP_NAME = "{name}"\n'
        f'VERSION = "{version}"\n'
        f"BUILD = {build}\n"
        f'MIN_CLIENT = "{min_client}"\n')
    return out


def main() -> None:
    check = "--check" in sys.argv
    name, version, build = load()
    stale = []
    for rel, want in plan(name, version, build).items():
        path = os.path.join(ROOT, rel)
        have = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if have == want:
            continue
        stale.append(rel)
        if not check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(want)
    if check:
        if stale:
            print("和 brand.json / VERSION 不一致（跑 python3 brand/sync.py）：\n  " + "\n  ".join(stale))
            sys.exit(1)
        print(f"{name} {version} ({build}) 一致")
        return
    print(f"{name} {version} ({build})：" + ("更新了 " + "、".join(stale) if stale else "全部已一致"))
    if "--icons" in sys.argv:
        os.chdir(ROOT)
        import runpy
        runpy.run_path(os.path.join(ROOT, "brand", "make_icons.py"))


if __name__ == "__main__":
    main()
