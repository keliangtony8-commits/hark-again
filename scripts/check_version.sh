#!/usr/bin/env bash
# 版本检查（v2.86）：名字/版本各处与 brand/brand.json + VERSION 一致；给了 tag 参数时还要求 tag 与 VERSION 对得上。
# 提交前：bash scripts/check_version.sh v2.86   （runsmokes 里不带参数跑）
# v2.90.2：补丁版用全版本号打 tag（v2.90.1 就是这么打的），所以 vX.Y 和 vX.Y.Z 都收。
set -euo pipefail
cd "$(dirname "$0")/.."
python3 brand/sync.py --check
if [ $# -ge 1 ]; then
  want="v$(cut -d. -f1,2 VERSION)"
  full="v$(tr -d '[:space:]' < VERSION)"
  case "$1" in
    "$want"|"$full") echo "tag $1 与 VERSION $full 一致" ;;
    *) echo "tag $1 与 VERSION $full 不一致（应为 $want 或 $full）"; exit 1 ;;
  esac
fi
