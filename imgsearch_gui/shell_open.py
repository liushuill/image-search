"""
用系统默认程序打开文件、目录或网址

**为什么需要这一层：**

`QDesktopServices.openUrl(QUrl.fromLocalFile(路径))` 在 Linux 上工作良好，
但在 **Windows 上打开「目录」并不可靠**：

    qt.qpa.services: ShellExecute 'file:///C:/.../output' failed (error 5)

error 5 = 拒绝访问。Qt 把本地路径转成 `file://` URL 再交给 ShellExecute。

⚠️ **根因：在低完整性会话里创建的 venv（2026-10 实测）**

现象：打开文件夹报 ``ShellExecute ... failed (error 5)``，同一台机器上换一个
Python 就正常。排查到底发现根本不是 Python 版本的问题，而是：

    venv 是由**低完整性进程**（沙箱/受限会话）创建的
    → venv/Scripts/python.exe 的文件 ACL 带 "Mandatory Label/Low"
    → 用它启动的进程运行在 Low 完整性（S-1-16-4096）
    → 低完整性进程不能向中完整性的 Explorer 发窗口消息（UIPI）
    → ShellExecute 一律返回 5（拒绝访问）
    → 连 `explorer` 子进程都以 0xC0000142（DLL 初始化失败）起不来

对照实测（同一个 3.14.5）：
- venv 里的 python：startfile 失败、ShellExecuteW 返回 5、explorer 0xC0000142
- 同版本的 base 解释器：全部成功（ShellExecuteW 返回 42）

**解法不是改代码，而是重建 venv**：在**普通终端**（Medium）里删掉 .venv
重新运行 bootstrap。程序会在失败信息里带上进程完整性，便于一眼看出这种情况。

结构上仍保留三级：``os.startfile`` → Win32 ``ShellExecuteW``（能拿返回码）
→ ``explorer``（``/select,``），并探测 ``GetShellWindow()`` 判断有没有桌面外壳。
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
    import sys as _sys
    parts = []
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetShellWindow()      # type: ignore[attr-defined]
        parts.append(f"GetShellWindow={hwnd}（{'有' if hwnd else '无'}桌面外壳）")
    except Exception:                                     # noqa: BLE001
        parts.append("GetShellWindow=探测失败")
    # 解释器也带上：同一个 startfile 在不同 Python 版本/不同 venv 下表现可能不同，
    # 报错时能直接看出是不是"用了另一个解释器"
    parts.append(f"Python {_sys.version.split()[0]}")
    parts.append(f"{_sys.executable}")
    level = process_integrity()
    if level:
        parts.append(f"进程完整性={level}")
    return "（" + "；".join(parts) + "）"

def process_integrity() -> str:
    """
    当前进程的完整性级别：``"Low"`` / ``"Medium"`` / ``"High"`` / ``""``。

    为什么需要：实测遇到过一类极难查的故障 —— **venv 所在目录带 Low 标签**，
    继承下来后 venv 里的 python 也跑在 Low 完整性，于是打开文件夹一律
    ``ShellExecute`` error 5、``explorer`` 子进程 0xC0000142，而测试、渲染、
    CLI 全部正常，看起来像"代码有 bug"。

    实现：先用 ctypes 直接读进程令牌（不依赖 whoami 能否启动 —— 这次就踩过
    它在 GUI 进程里拿不到输出的坑），失败再退回 ``whoami /groups``。
    """
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        advapi = ctypes.windll.advapi32            # type: ignore[attr-defined]
        kernel = ctypes.windll.kernel32            # type: ignore[attr-defined]
        token = wintypes.HANDLE()
        if advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008,
                                   ctypes.byref(token)):
            try:
                size = wintypes.DWORD(0)
                advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
                if size.value:
                    buf = ctypes.create_string_buffer(size.value)
                    if advapi.GetTokenInformation(token, 25, buf, size,
                                                  ctypes.byref(size)):
                        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                        advapi.GetSidSubAuthorityCount.restype = ctypes.c_void_p
                        pcount = advapi.GetSidSubAuthorityCount(sid)
                        count = ctypes.cast(
                            pcount, ctypes.POINTER(ctypes.c_ubyte))[0]
                        advapi.GetSidSubAuthority.restype = ctypes.c_void_p
                        psub = advapi.GetSidSubAuthority(sid, count - 1)
                        rid = ctypes.cast(psub, ctypes.POINTER(wintypes.DWORD))[0]
                        names = {0x1000: "Low", 0x2000: "Medium",
                                 0x3000: "High"}
                        return names.get(rid, f"0x{rid:04x}")
            finally:
                kernel.CloseHandle(token)
    except Exception:                                     # noqa: BLE001
        pass

    try:                                    # 兜底：ctypes 不可用时再问 whoami
        import re as _re
        out = subprocess.run(["whoami", "/groups"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = _re.search(r"S-1-16-(\d+)", out)
    if not m:
        return ""
    return {"4096": "Low", "8192": "Medium", "12288": "High"}.get(
        m.group(1), "S-1-16-" + m.group(1))



def _fail(step: str, exc: BaseException) -> bool:
    global _last_error
    prev = f"{_last_error}；" if _last_error else ""
    _last_error = f"{prev}{step}: {type(exc).__name__}: {exc}"
    return False


def _is_dir(text) -> bool:
    """
    判断是不是目录。

    抽成函数是为了**可测试**：测试要模拟「Windows 上路径是目录」时，
    只能去 patch pathlib.Path —— 而 ``Path`` 的工厂会在调用时按 ``os.name``
    选 WindowsPath/PosixPath，于是 PosixPath 在真 Windows 上直接抛
    ``UnsupportedOperation``（真实 CI 上就炸过）。patch 这个函数两个平台都能跑。
    """
    return Path(text).is_dir()


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


def _shell_execute(text: str) -> bool:
    """
    直接调 Win32 ``ShellExecuteW``（不经过 ``os.startfile``）。

    为什么不用 ``os.startfile`` 打开**目录**：实测同一台 Windows 上，
    Python **3.9** 的 ``os.startfile(目录)`` 成功，而 **3.14**（本程序 venv 用的
    版本）失败。3.14 给 ``startfile`` 加了 ``operation`` / ``arguments`` /
    ``show_cmd`` 等参数，实现与旧版不同；与其猜它哪里变了，不如直接调底层 API ——
    这正是 ``os.startfile`` 内部做的事，而且能拿到返回码判断成败。

    ``ShellExecuteW`` 返回值 > 32 表示成功（其余是错误码，如 2=找不到文件、
    5=拒绝访问、31=没有关联程序）。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(      # type: ignore[attr-defined]
            None, "open", text, None, None, 1)         # 1 = SW_SHOWNORMAL
    except Exception as exc:                            # noqa: BLE001
        return _fail("ShellExecuteW", exc)
    if rc > 32:
        return _ok()
    return _fail("ShellExecuteW", OSError(f"返回 {rc}（>32 才算成功）"))


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
    # explorer 正常时会把请求交给已在运行的实例，然后**自己退出**。
    # 实测：成功时退出码是 **1**（不是 0），所以不能拿 ==0 判断成功。
    # 真正失败的样子是 0xC0000142（DLL 初始化失败，低完整性会话里常见）。
    try:
        code = proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        return _ok()                    # 还在跑，认为已经交出去了
    if code in (0, 1):
        return _ok()
    return _fail("explorer", OSError(f"explorer 立即退出，code={code:#x}"))


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

    is_dir = _is_dir(text)

    tried = False

    if os.name == "nt":
        tried = True

        # 第一级：os.startfile（文件和目录在**正常进程**里都好用）
        try:
            os.startfile(text)              # type: ignore[attr-defined]
            return _ok()
        except (OSError, AttributeError) as exc:
            _fail("os.startfile", exc)

        # 第二级：直接调 Win32（os.startfile 内部也是它，但这里能拿到返回码）
        if _shell_execute(text):
            return _ok()

        # 第三级：目录还能试试直接拉资源管理器
        if is_dir:
            if not has_shell():
                _fail("open_path", OSError(
                    "当前会话没有 Explorer 桌面外壳（低完整性/无桌面会话），"
                    "无法打开文件夹；文件仍然可以直接打开"))
                return False
            if _explorer_launch(text, True):
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
    if not _is_dir(path):
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
