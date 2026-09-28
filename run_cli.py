#!/usr/bin/env python3
"""
CLI 入口 shim

    python run_cli.py search 图片.jpg

等价于 ``python -m imgsearch``。存在的意义：
  - 在仓库根目录直接运行，无需设置 PYTHONPATH
  - 供 PyInstaller 之类需要「单文件入口脚本」的打包工具使用
"""

import sys
from pathlib import Path

# 确保仓库根在 sys.path 上（直接运行本文件时通常已满足）
_REPO_DIR = str(Path(__file__).resolve().parent)
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)

from imgsearch.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
