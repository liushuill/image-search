"""
用系统默认程序打开文件、目录或网址

**为什么需要这一层：**

`QDesktopServices.openUrl(QUrl.fromLocalFile(路径))` 在 Linux 上工作良好，
但在 **Windows 上打开「目录」并不可靠**：

    qt.qpa.services: ShellExecute 'file:///C:/.../output' failed (error 5)

error 5 = 拒绝访问。Qt 把本地路径转成 `file://` URL 再交给 ShellExecute。

更麻烦的是：实测发现**有的机器上连 ``os.startfile`` 也会失败**
（同样的 error 5），而此时路径本身完全正常 —— 在终端里点同一个
`file://` 链接却能打开。也就是说，这是**特定进程**调用 ShellExecute
被拒，而不是路径有问题。

所以这里做三级兜底，只要有一条成功就算打开：

1. ``os.startfile(原生路径)`` —— 最快，绝大多数机器可用
2. ``explorer 路径`` / ``explorer /select,路径``
   —— 直接拉资源管理器，**绕开 ShellExecute 的动词解析**，
      在 1 失败的那些机器上通常有效
3. ``QDesktopServices.openUrl`` —— 最后的跨平台兜底

失败时把每一级的原因记在 :func:`last_error` 里，界面可以原样显示，
而不是只给用户一句「打不开」。
"""

import os
import subprocess
from pathlib import Path

from PySide6 import QtCore, QtGui

# 最近一次失败的原因（成功时清空）。给界面用，避免只说「打不开」。
_last_error = ""


def last_error() -> str:
    """最近一次打开失败的原因；成功则为空字符串"""
    return _last_error


def _ok() -> bool:
    global _last_error
    _last_error = ""
    return True


def _fail(step: str, exc: BaseException) -> bool:
    global _last_error
    prev = f"{_last_error}；" if _last_error else ""
    _last_error = f"{prev}{step}: {type(exc).__name__}: {exc}"
    return False


def _explorer_launch(text: str, is_dir: bool) -> bool:
    """
    直接用资源管理器打开（Windows）。

    为什么需要这一条：ShellExecute 在某些进程里对目录会被拒（error 5），
    而 ``explorer <路径>`` 走的是另一条路径，通常不受影响。
    """
    args = ["explorer", text] if is_dir else ["explorer", f"/select,{text}"]
    try:
        subprocess.Popen(args, close_fds=True)
        return _ok()
    except OSError as exc:                              # pragma: no cover
        return _fail("explorer", exc)


def open_path(target) -> bool:
    """
    用系统默认程序打开一个文件或目录。

    Returns:
        是否成功发起。失败时用 :func:`last_error` 取原因。
    """
    text = str(target or "").strip()
    if not text:
        _fail("open_path", ValueError("路径为空"))
        return False

    is_dir = Path(text).is_dir()
    tried = False

    if os.name == "nt":
        tried = True
        try:
            os.startfile(text)              # type: ignore[attr-defined]
            return _ok()
        except (OSError, AttributeError) as exc:
            _fail("os.startfile", exc)
        # 第二级：直接拉资源管理器，绕开 ShellExecute 的动词解析
        if _explorer_launch(text, is_dir):
            return True

    if QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(text)):
        return _ok()

    if not tried:
        _fail("QDesktopServices", OSError("返回 False（系统没有关联程序或调用被拒）"))
    return False


def open_dir(target) -> bool:
    """
    打开一个目录（不存在时返回 False，并记录原因）。

    单独的入口而不是让调用方自己判断：目录不存在时 ``os.startfile`` 会抛
    OSError，静默失败比弹一个看不懂的系统错误更好。
    """
    path = Path(target)
    if not path.is_dir():
        _fail("open_dir", FileNotFoundError(f"目录不存在：{path}"))
        return False
    return open_path(path)


def open_url(url: str) -> bool:
    """
    用默认浏览器打开网址。

    这里仍然用 Qt：URL 不是本地路径，没必要按平台分流。
    """
    text = (url or "").strip()
    if not text:
        _fail("open_url", ValueError("网址为空"))
        return False
    if QtGui.QDesktopServices.openUrl(QtCore.QUrl(text)):
        return _ok()
    # 浏览器也可能被同样的策略挡住，退回标准库再试一次
    import webbrowser

    try:
        if webbrowser.open(text):
            return _ok()
    except Exception as exc:                            # noqa: BLE001
        return _fail("webbrowser", exc)
    return _fail("open_url", OSError("无法打开网址"))


def reveal_in_folder(target) -> bool:
    """
    在文件管理器里选中某个文件。

    Windows 用 ``explorer /select,``；其他平台退化为打开所在目录。
    """
    path = Path(target)
    if not path.exists():
        _fail("reveal_in_folder", FileNotFoundError(f"路径不存在：{path}"))
        return False

    if os.name == "nt":
        if _explorer_launch(str(path), False):
            return True

    parent = path.parent if path.parent.is_dir() else path
    return open_path(parent)
