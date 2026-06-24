#!/usr/bin/env bash
# 一键重建产业链研究库门户，并在浏览器打开。
# 用法: ./build.sh        （重建并打开 index.html）
#       ./build.sh -n     （只重建，不打开）
set -euo pipefail
cd "$(dirname "$0")"

python3 build.py

if [[ "${1:-}" != "-n" ]] && command -v open >/dev/null 2>&1; then
  open index.html
fi
