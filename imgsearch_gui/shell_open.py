"""
用系统默认程序打开文件、目录或网址

**为什么需要这一层：**

`QDesktopServices.openUrl(QUrl.fromLocalFile(路径))` 在 Linux 上工作良好，
但在 **Windows 上打开「目录」会失败**：

    qt.qpa.services: ShellExecute 'file:///C:/.../output' failed (error 5)

error 5 = 拒绝访问。Qt 把本地路径转成 `file://` URL 再交给 ShellExecute，
对目录这条路径并不可靠（对普通文件通常没事）。

Windows 的原生做法是 ``os.startfile(路径)``（内部就是 ShellExecute，
但传的是**原生路径**而不是 URL）。所以这里按平台分流：

- Windows：``os.startfile``，失败再退回 Qt（例如路径不存在时给个一致的静默）
- 其他平台：``QDesktopServices``（Linux 走 xdg-open，macOS 走 open）

⚠️ **打开文件夹**统一走 :func:`open_path`，不要直接调 `QDesktopServices` ——
那正是这个 bug 的来源。
"""

import os
from pathlib import Path

from PySide6 import QtCore, QtGui


def open_path(target) -> bool:
    """
    用系统默认程序打开一个文件或目录。

    Args:
        target: 路径（``str`` 或 ``Path``）

    Returns:
        是否成功发起。失败返回 False，调用方可据此提示用户。
    """
    text = str(target or "").strip()
    if not text:
        return False

    if os.name == "nt":
        # Windows：用原生路径 + os.startfile，不要转成 file:// URL
        try:
            os.startfile(text)                      # type: ignore[attr-defined]
            return True
        except (OSError, AttributeError):
            # OSError：路径不存在 / 没有关联程序
            # AttributeError：某些解释器/环境没有 os.startfile
            # 退回 Qt 试一次，让行为与其他平台尽量一致
            pass

    return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(text))


def open_dir(target) -> bool:
    """
    打开一个目录（不存在时返回 False）。

    单独的入口而不是让调用方自己判断：目录不存在时 ``os.startfile`` 会抛
    OSError，静默失败比弹一个看不懂的系统错误更好。
    """
    path = Path(target)
    if not path.is_dir():
        return False
    return open_path(path)


def open_url(url: str) -> bool:
    """
    用默认浏览器打开网址。

    这里仍然用 Qt：URL 不是本地路径，没必要按平台分流。
    """
    text = (url or "").strip()
    if not text:
        return False
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl(text))


def reveal_in_folder(target) -> bool:
    """
    在文件管理器里选中某个文件（Windows 用 ``explorer /select,``）。

    其他平台没有统一的「选中」语义，退化为打开所在目录。
    """
    path = Path(target)
    if not path.exists():
        return False

    if os.name == "nt":
        try:
            import subprocess
            subprocess.Popen(["explorer", f"/select,{path}"])
            return True
        except OSError:
            pass

    parent = path.parent if path.parent.is_dir() else path
    return open_path(parent)
