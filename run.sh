#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# image-search CLI 启动器（Linux / macOS）
#
#   ./run.sh search 图片.jpg
#   ./run.sh search 图片.jpg --url
#   ./run.sh batch ./待查目录
#   ./run.sh engines list
#   ./run.sh config show
#
# 首次运行会自动创建 .venv 并安装依赖。
# ⚠️ 不污染系统 Python —— Debian/Ubuntu 有 PEP 668 (EXTERNALLY-MANAGED) 保护，
#    直接 pip install 到系统环境会被拒绝。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# 解析脚本真实路径（穿透软链接），据此定位仓库根
REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
VENV="$REPO_DIR/.venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
    echo "首次运行：正在创建虚拟环境 .venv ..." >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    echo "正在安装依赖（首次约 1–2 分钟）..." >&2
    "$VENV/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
    # 可选：注册 imgsearch 命令（失败不影响使用，下面用 PYTHONPATH 兜底）
    "$VENV/bin/pip" install --quiet --no-deps -e "$REPO_DIR" 2>/dev/null \
        || echo "提示：editable 安装未完成，不影响使用。" >&2
    echo "依赖安装完成。" >&2
fi

if [ ! -f "$REPO_DIR/.env" ]; then
    echo "提示：尚未配置凭据。可执行  cp .env.example .env && chmod 600 .env  后填入 SAUCENAO_KEY" >&2
fi

# 用 PYTHONPATH 而非 cd：保留调用者传入的相对路径语义
export PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m imgsearch "$@"
