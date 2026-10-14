#!/usr/bin/env bash
# 版本检查（v2.86）：名字/版本各处与 brand/brand.json + VERSION 一致；给了 tag 参数时还要求 tag = v<VERSION 前两段>。
# 提交前：bash scripts/check_version.sh v2.86   （runsmokes 里不带参数跑）
set -euo pipefail
cd "$(dirname "$0")/.."
python3 brand/sync.py --check
if [ $# -ge 1 ]; then
  want="v$(cut -d. -f1,2 VERSION)"
  [ "$1" = "$want" ] || { echo "tag $1 与 VERSION $(cat VERSION) 不一致（应为 $want）"; exit 1; }
  echo "tag $1 与 VERSION 一致"
fi
