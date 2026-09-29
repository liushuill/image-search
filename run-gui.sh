#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# image-search 图形界面启动器（Linux / macOS）
#
#   ./run-gui.sh
#
# 首次运行会自动创建 .venv 并安装 PySide6。
# 已实测在 KDE Wayland 下使用原生 wayland 平台插件（不走 XWayland）。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

for CANDIDATE in python3 python; do
    if command -v "$CANDIDATE" >/dev/null 2>&1; then
        exec "$CANDIDATE" "$REPO_DIR/bootstrap.py" gui "$@"
    fi
done

echo "❌ 找不到 Python 3。请先安装：sudo apt install python3 python3-venv" >&2
exit 1
