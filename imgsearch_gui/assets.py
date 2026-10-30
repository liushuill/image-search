"""
程序图标的查找与加载

图标文件放在仓库根的 ``assets/``。打包后位置会变，所以统一走 :func:`asset_path`：

| 运行方式 | 图标实际在 |
|---|---|
| 源码运行 | `<仓库>/assets/` |
| PyInstaller onedir | `<安装目录>/_internal/assets/` |
| PyInstaller onefile | `sys._MEIPASS/assets/` |
"""

import sys
from pathlib import Path

from imgsearch.config import APP_DIR

# 窗口图标用 256px 的 PNG（Qt 会在各种尺寸下自行缩放）；
# .ico 只给 Windows 的 exe 用（`--icon`），运行时不加载它。
WINDOW_ICON = "ImageSearch-256.png"


def _candidate_roots():
    """按优先级列出可能存放 assets/ 的目录"""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)      # onefile 解压目录
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):            # onedir
        roots.append(Path(sys.executable).resolve().parent / "_internal")
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(APP_DIR)                        # 源码运行
    return roots


def asset_path(name: str) -> Path:
    """
    找到 ``assets/<name>``；找不到时返回源码运行时的那个路径（调用方可据此报错）。

    为什么不缓存：测试会临时替换 ``APP_DIR`` / ``sys._MEIPASS``，
    缓存之后反而测不准。
    """
    for root in _candidate_roots():
        candidate = root / "assets" / name
        if candidate.is_file():
            return candidate
    return APP_DIR / "assets" / name


def window_icon():
    """
    返回窗口图标（``QIcon``）；文件缺失时返回一个空 QIcon，不抛异常。

    图标不该成为启动失败的原因 —— 缺了就退回 Qt 默认图标。
    """
    from PySide6 import QtGui

    path = asset_path(WINDOW_ICON)
    if not path.is_file():
        return QtGui.QIcon()
    return QtGui.QIcon(str(path))
