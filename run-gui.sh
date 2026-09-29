#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# image-search 图形界面启动器（Linux）
#
#   ./run-gui.sh
#
# 首次运行会自动创建 .venv 并安装 GUI 依赖（PySide6 / Qt6）。
# 已实测在 KDE Wayland 下使用原生 wayland 平台插件（不走 XWayland）。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
VENV="$REPO_DIR/.venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
    echo "首次运行：正在创建虚拟环境 .venv ..." >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    echo "正在安装依赖（首次约 2–3 分钟，PySide6 较大）..." >&2
    "$VENV/bin/pip" install --quiet -r "$REPO_DIR/requirements-gui.txt"
    "$VENV/bin/pip" install --quiet --no-deps -e "$REPO_DIR" 2>/dev/null || true
fi

# 缺 PySide6 时补装（例如先用了 CLI 版，venv 里只有运行时依赖）
if ! "$PY" -c "import PySide6" >/dev/null 2>&1; then
    echo "正在安装 GUI 依赖 PySide6 ..." >&2
    "$VENV/bin/pip" install --quiet PySide6
fi

export PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m imgsearch_gui "$@"
