#!/usr/bin/env bash
# 在 4G 小内存 VPS 上编 Android release APK（实测 2026-10-14：约 9 分钟，arm64 20.6MB）。
# 稳妥要点：加 4G 交换区；编译期间暂停 browser/searxng 容器（结束必恢复）；
# 单个 Gradle JVM（Xmx1800m，禁用 Gradle/Kotlin 守护进程，workers=2，不并行）；
# systemd MemoryMax=3G + nice 19 + ionice idle，避免把整台机器拖死。
# 用法：先在本机 `tar czf app.tgz app` 并传到 /root/app.tgz，然后
#   nohup bash deploy/build-apk.sh > /root/vbuild.log 2>&1 &
# 产物：/root/toyuis-<版本>-arm64.apk（只留最新一份）
# 结束时（成功或失败）自动清掉能再生成的缓存（HANDOFF 第二节第 17 条）：gradle 缓存（留 wrapper）、
# /root/.pub-cache、/opt/apkbuild/src、本脚本临时加的 /swapfile2、/root/app.tgz。SDK / Flutter / JDK 不动。
# 注意：机器上同一时间只能有一个构建在跑（先 pgrep -fa gradle 确认）。
set -u
A=${A:-/opt/apkbuild}
OUT_DIR=${OUT_DIR:-/root}
PUB_CACHE_DIR=${PUB_CACHE_DIR:-/root/.pub-cache}
APP_TGZ=${APP_TGZ:-/root/app.tgz}
COMPOSE_DIR=${COMPOSE_DIR:-/opt/assistant/app}

# 取出 APK（只留最新一份），再删能再生成的缓存。只认上面这几个路径，绝不碰 sdk / flutter / jdk。
apk_cleanup() {
  local apk="$A/src/app/build/app/outputs/flutter-apk/app-arm64-v8a-release.apk" ver
  if [ -f "$apk" ]; then
    ver=$(sed -n 's/^version: *\([0-9.]*\).*/\1/p' "$A/src/app/pubspec.yaml" 2>/dev/null); ver=${ver:-unknown}
    rm -f "$OUT_DIR"/toyuis-*-arm64.apk
    cp "$apk" "$OUT_DIR/toyuis-$ver-arm64.apk" && echo "APK：$OUT_DIR/toyuis-$ver-arm64.apk"
  fi
  if [ -d "$A/gradle" ]; then find "$A/gradle" -mindepth 1 -maxdepth 1 ! -name wrapper -exec rm -rf {} +; fi
  rm -rf "$PUB_CACHE_DIR" "$A/src"
  rm -f "$APP_TGZ"
  if [ "${SWAP_ADDED:-0}" = 1 ]; then swapoff /swapfile2 2>/dev/null; rm -f /swapfile2; fi
  echo CACHE_CLEANED
}
[ "${BUILD_APK_LIB_ONLY:-0}" = 1 ] && return 0 2>/dev/null

if pgrep -f 'GradleWrapperMain|GradleMain' >/dev/null; then echo "另一个 Gradle 正在跑，先停掉它"; exit 1; fi
SWAP_ADDED=0
if ! swapon --show | grep -q /swapfile2; then
  SWAP_ADDED=1
  fallocate -l 4G /swapfile2 && chmod 600 /swapfile2 && mkswap /swapfile2 >/dev/null && swapon /swapfile2
fi
(cd "$COMPOSE_DIR" && docker compose stop browser searxng >/dev/null 2>&1)
trap '(cd "$COMPOSE_DIR" && docker compose start browser searxng >/dev/null 2>&1); echo CONTAINERS_RESTORED; apk_cleanup' EXIT

inner() {
  set -euo pipefail
  mkdir -p $A; cd $A
  apt-get install -y -qq unzip xz-utils git >/dev/null
  if [ ! -x $A/jdk/bin/java ]; then
    curl -fsSL -o jdk.tgz "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
    mkdir -p jdk && tar xzf jdk.tgz -C jdk --strip-components=1 && rm jdk.tgz
  fi
  export JAVA_HOME=$A/jdk PATH=$A/jdk/bin:$PATH ANDROID_HOME=$A/sdk ANDROID_SDK_ROOT=$A/sdk
  if [ ! -x $A/sdk/cmdline-tools/latest/bin/sdkmanager ]; then
    curl -fsSL -o ct.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
    mkdir -p sdk/cmdline-tools && unzip -q ct.zip -d sdk/cmdline-tools && mv sdk/cmdline-tools/cmdline-tools sdk/cmdline-tools/latest && rm ct.zip
  fi
  yes | sdk/cmdline-tools/latest/bin/sdkmanager --licenses >/dev/null || true
  [ -d flutter ] || git clone -q --depth 1 -b stable https://github.com/flutter/flutter.git
  export PATH=$A/flutter/bin:$PATH GRADLE_USER_HOME=$A/gradle
  git config --global --add safe.directory '*'
  flutter config --no-analytics --android-sdk $A/sdk >/dev/null
  rm -rf src && mkdir src && tar xzf "$APP_TGZ" -C src
  cd src/app && flutter pub get >/dev/null
  export GRADLE_OPTS="-Xmx1800m -Dorg.gradle.daemon=false -Dkotlin.compiler.execution.strategy=in-process -Dkotlin.daemon.enabled=false"
  printf "\norg.gradle.jvmargs=-Xmx1800m -XX:MaxMetaspaceSize=512m\norg.gradle.workers.max=2\nkotlin.compiler.execution.strategy=in-process\nkotlin.daemon.enabled=false\norg.gradle.parallel=false\n" >> android/gradle.properties
  flutter build apk --release --split-per-abi --target-platform android-arm64
  ls -la build/app/outputs/flutter-apk/
  echo BUILD_DONE
}
export -f inner; export A APP_TGZ
systemd-run --scope -p MemoryMax=3G nice -n 19 ionice -c3 bash -c inner
