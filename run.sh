#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# image-search 命令行启动器（Linux / macOS）
#
#   ./run.sh search 图片.jpg
#   ./run.sh engines list
#
# 真正的引导逻辑在 bootstrap.py 里 —— 两个平台共用同一套，
# 避免「Linux 那份修了、Windows 那份忘了」。这里只是找到 Python 并转交。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

# 找一个可用的 Python 3（不同发行版的命令名不一样）
for CANDIDATE in python3 python; do
    if command -v "$CANDIDATE" >/dev/null 2>&1; then
        exec "$CANDIDATE" "$REPO_DIR/bootstrap.py" cli "$@"
    fi
done

echo "❌ 找不到 Python 3。请先安装：sudo apt install python3 python3-venv" >&2
exit 1
