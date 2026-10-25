"""
用系统默认程序打开文件、目录或网址

**为什么需要这一层：**

`QDesktopServices.openUrl(QUrl.fromLocalFile(路径))` 在 Linux 上工作良好，
但在 **Windows 上打开「目录」并不可靠**：

    qt.qpa.services: ShellExecute 'file:///C:/.../output' failed (error 5)

error 5 = 拒绝访问。Qt 把本地路径转成 `file://` URL 再交给 ShellExecute。

⚠️ **一个尚未查清的边界（2026-10）**：

有用户报告打开文件夹报 ``ShellExecute ... failed (error 5)``，而路径本身正常。
诊断发现**那次运行的会话**没有桌面外壳：低完整性（``S-1-16-4096``）、
``tasklist`` 里没有 ``explorer.exe``。打开**文件夹**必须请正在运行的 Explorer
代劳，没有它 → UIPI 拒绝 → ``error 5``；打开**文件**走文件关联直接起子进程，
不需要 shell，所以成功。

但报告者的桌面是 Medium 完整性 —— 两者不是同一个上下文，**到底是哪次运行
落在了无 shell 的会话里尚未确认**。所以：
- 「Windows 上 ``os.startfile(目录)`` 不可靠」这个说法**没有证据**，已撤回；
- 普通桌面下的行为**仍未实测**；
- 本模块先探测 :func:`has_shell`，无 shell 时给出准确原因，
  不再把「explorer 起来就死」当成"打开成功"（那是假阳性，用户看到的是"点了没反应"）。

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


def _shell_context() -> str:
    """
    失败信息里附带的环境线索。

    这条是为了让「打不开文件夹」的报告能自证环境：如果 GetShellWindow 是 0，
    说明当前会话没有桌面外壳（低完整性/服务/沙箱），那失败跟路径、跟代码都无关。
    否则就是另一回事，需要继续查。
    """
    if os.name != "nt":
        return ""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetShellWindow()      # type: ignore[attr-defined]
    except Exception:                                     # noqa: BLE001
        return ""
    return f"（GetShellWindow={hwnd}，{'有' if hwnd else '无'}桌面外壳）"


def _fail(step: str, exc: BaseException) -> bool:
    global _last_error
    prev = f"{_last_error}；" if _last_error else ""
    _last_error = f"{prev}{step}: {type(exc).__name__}: {exc}"
    return False


def has_shell() -> bool:
    """
    Windows：当前会话有没有桌面外壳（Explorer）。

    为什么需要判断：**打开「文件夹」不是普通进程能独立完成的事** ——
    它要请正在运行的 Explorer 代劳。如果会话里根本没有 Explorer
    （低完整性/服务会话/容器/无桌面），这一步一律被 UIPI 拒绝，
    表现为 ``ShellExecute ... failed (error 5)``。

    实测（Windows 11，S-1-16-4096 低完整性、tasklist 里没有 explorer.exe）：
    - 打开**目录** → 全部 winerror=5
    - 打开**文件** → 成功（走文件关联，直接起子进程，不需要 shell）
    - ``Popen(["explorer", 目录])`` 返回成功，但 explorer 立刻以
      ``0xc0000142 (STATUS_DLL_INIT_FAILED)`` 退出

    所以「有没有 shell」必须显式判断，不能靠"调用没抛异常"来推断成功。

    ``GetShellWindow()`` 在普通桌面上返回非 0 的窗口句柄，无 shell 时为 0。
    非 Windows 一律返回 True（Linux/macOS 没有这个概念）。
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetShellWindow())   # type: ignore[attr-defined]
    except Exception:                                     # noqa: BLE001
        return True          # 探测不了就假定有，别把正常用户挡在外面


def _explorer_launch(text: str, is_dir: bool) -> bool:
    """
    直接用资源管理器打开（Windows）。

    ⚠️ 只在**确实有 shell** 时才用。而且 ``Popen`` 成功不代表打开成功 ——
    无 shell 的会话里 explorer 会起来后立刻死掉（0xc0000142），
    若把 Popen 成功当成成功，用户会看到"点了没反应"，比报错更难查。
    """
    if not has_shell():
        return _fail("explorer", OSError("当前会话没有 Explorer 桌面外壳"))
    args = ["explorer", text] if is_dir else ["explorer", f"/select,{text}"]
    try:
        proc = subprocess.Popen(args, close_fds=True)
    except OSError as exc:                              # pragma: no cover
        return _fail("explorer", exc)
    # explorer 正常时会把请求交给已在运行的实例后**自己退出**（退出码常为 1），
    # 所以不能靠退出码判断。这里只拦「立刻就死且退出码异常」的情况。
    try:
        code = proc.wait(timeout=0.6)
    except subprocess.TimeoutExpired:
        return _ok()                    # 还在跑，认为已经交出去了
    if code == 0:
        return _ok()
    return _fail("explorer", OSError(f"explorer 立即退出，code={code}"))


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

    # 目录 + 没有 shell：这条路根本走不通，直接说清楚。
    # 不再去调 os.startfile / Qt —— 它们只会各抛一次 error 5，
    # 在控制台留下噪声，还让用户以为是自己路径的问题。
    if is_dir and not has_shell():
        return _fail("open_path", OSError(
            "当前会话没有 Explorer 桌面外壳（低完整性/无桌面会话），"
            "无法打开文件夹；文件仍然可以直接打开"))

    tried = False

    if os.name == "nt":
        tried = True
        try:
            os.startfile(text)              # type: ignore[attr-defined]
            return _ok()
        except (OSError, AttributeError) as exc:
            _fail("os.startfile", exc)
        # 第二级：直接拉资源管理器（仅在有 shell 时有意义）
        if _explorer_launch(text, is_dir):
            return True

    if QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(text)):
        return _ok()

    if not tried:
        _fail("QDesktopServices", OSError("返回 False（系统没有关联程序或调用被拒）"))
    # 附上环境线索：有/无桌面外壳会决定接下来的排查方向
    global _last_error
    ctx = _shell_context()
    if ctx:
        _last_error = f"{_last_error} {ctx}"
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

    if os.name == "nt" and has_shell():
        if _explorer_launch(str(path), False):
            return True

    parent = path.parent if path.parent.is_dir() else path
    return open_path(parent)
