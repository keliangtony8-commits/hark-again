#!/usr/bin/env bash
# build-apk.sh 结尾清理的离线测试（不编译、不碰真 /opt /root）：bash deploy/tests/test_build_apk_cleanup.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo "✗ $*" >&2; exit 1; }

export A="$TMP/apkbuild" OUT_DIR="$TMP/root" PUB_CACHE_DIR="$TMP/root/.pub-cache" APP_TGZ="$TMP/root/app.tgz" BUILD_APK_LIB_ONLY=1 SWAP_ADDED=0
mkdir -p "$A"/{sdk,flutter,jdk/bin} "$A/gradle"/{wrapper,caches,daemon} "$A/src/app/build/app/outputs/flutter-apk" "$PUB_CACHE_DIR/hosted"
printf 'name: assistant\nversion: 3.0.1+30001\n' > "$A/src/app/pubspec.yaml"
echo apk > "$A/src/app/build/app/outputs/flutter-apk/app-arm64-v8a-release.apk"
echo old > "$OUT_DIR/toyuis-2.93.0-arm64.apk"; echo keep > "$OUT_DIR/v293.tgz"; echo tgz > "$APP_TGZ"
touch "$A/sdk/x" "$A/flutter/x" "$A/jdk/bin/java" "$A/gradle/wrapper/w"

# shellcheck source=../build-apk.sh
source "$HERE/../build-apk.sh"
apk_cleanup >/dev/null

[[ "$(cat "$OUT_DIR/toyuis-3.0.1-arm64.apk")" == apk ]] || fail "APK 应拷到 OUT_DIR 并带版本号"
[[ ! -e "$OUT_DIR/toyuis-2.93.0-arm64.apk" ]] || fail "旧 APK 应删（只留最新一份）"
[[ -e "$OUT_DIR/v293.tgz" ]] || fail "部署代码包不能删"
[[ ! -e "$A/src" && ! -e "$PUB_CACHE_DIR" && ! -e "$APP_TGZ" ]] || fail "src / pub-cache / app.tgz 应删"
[[ -e "$A/gradle/wrapper/w" && ! -e "$A/gradle/caches" && ! -e "$A/gradle/daemon" ]] || fail "gradle 只留 wrapper"
[[ -e "$A/sdk/x" && -e "$A/flutter/x" && -e "$A/jdk/bin/java" ]] || fail "SDK / Flutter / JDK 绝不能删"

# 构建失败（没有 APK）也照样清缓存、不动已有 APK
mkdir -p "$A/src" "$A/gradle/caches"; echo prev > "$OUT_DIR/toyuis-3.0.1-arm64.apk"
apk_cleanup >/dev/null
[[ "$(cat "$OUT_DIR/toyuis-3.0.1-arm64.apk")" == prev ]] || fail "没编出 APK 时不应删上一份"
[[ ! -e "$A/src" && ! -e "$A/gradle/caches" ]] || fail "失败也要清缓存"
echo "✓ build-apk 清理测试通过"
