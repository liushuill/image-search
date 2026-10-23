#!/usr/bin/env python3
"""
GUI 入口 shim

    python run_gui.py

等价于 ``python -m imgsearch_gui``。存在的意义与 ``run_cli.py`` 相同：
在仓库根目录直接运行不必设 PYTHONPATH，也给 PyInstaller 之类
「需要单文件入口脚本」的打包工具一个明确的入口。

（旧的 tkinter 版 ``gui.py`` 已删除：PySide6 版完全取代了它。）
"""

import sys
from pathlib import Path

# 允许从仓库根目录直接运行，无需先 pip install
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from imgsearch_gui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
