"""
打开文件 / 目录 / 网址

回归：Windows 上用 ``QDesktopServices.openUrl(QUrl.fromLocalFile(目录))``
会失败 —— 实测报错：

    qt.qpa.services: ShellExecute 'file:///C:/Users/.../output' failed (error 5)

原因是对「目录」这条路径，Qt 的 file:// URL 方式不可靠；
Windows 的原生做法是 ``os.startfile(原生路径)``。
"""

import os
from pathlib import Path

import pytest


from imgsearch_gui import shell_open


def _startfile_denied(path):
    """模拟 ``os.startfile`` 被拒（低完整性会话里的真实表现）。

    为什么兜底链的用例**必须**显式屏蔽第一级：

    - 在 POSIX 上 ``os.startfile`` 根本不存在（抛 AttributeError），链路自然往下走；
    - 但在**真 Windows 的正常桌面**上，它对目录**真的会成功** ——
      于是 ``open_path`` 在第一级就 return 了，后面被测的 explorer / Qt 分支
      一步都走不到，测试反而失败（实测：真 Windows 上挂 2 项）。

    这也是"测试只在某些宿主上通过"的典型陷阱：断言的对象不是被测分支，
    而是宿主的能力。
    """
    raise OSError(13, "Access is denied（模拟 ShellExecute 被 UIPI 拒绝）")


class TestOpenPath:
    def test_windows_dir_uses_shell_execute_with_native_path(self, monkeypatch):
        """
        目录走 Win32 ShellExecuteW，且必须传**原生路径**（不是 file:// URL）。

        为什么不走 os.startfile：实测同机 Python 3.9 成功、3.14 失败。
        """
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "_shell_execute",
                            lambda text: calls.append(text) or True)

        assert shell_open.open_path(r"C:\Users\a\output") is True
        assert calls == [r"C:\Users\a\output"]

    def test_windows_file_uses_startfile(self, monkeypatch):
        """文件仍走 os.startfile（文件关联不需要 shell，实测可用）"""
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "_is_dir", lambda t: False)
        monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)

        assert shell_open.open_path(r"C:\x\a.png") is True
        assert calls == [r"C:\x\a.png"]

    def test_windows_falls_back_to_qt_on_error(self, monkeypatch):
        opened = []
        monkeypatch.setattr(os, "name", "nt")

        def boom(path):
            raise OSError("no handler")

        monkeypatch.setattr(os, "startfile", boom, raising=False)
        monkeypatch.setattr(shell_open, "_explorer_launch", lambda *a: False)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url.toString()) or True)
        assert shell_open.open_path("C:/x") is True
        assert opened, "应当退回 Qt"

    def test_windows_dir_falls_back_to_explorer(self, tmp_path, monkeypatch):
        """ShellExecuteW 失败 → 用 explorer 打开目录；成功时不再走 Qt"""
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        # 第一级必须屏蔽：真 Windows 上它会把目录打开成功，后面就测不到了
        monkeypatch.setattr(os, "startfile", _startfile_denied, raising=False)
        monkeypatch.setattr(shell_open, "_is_dir", lambda t: True)
        monkeypatch.setattr(shell_open, "_shell_execute", lambda text: False)
        monkeypatch.setattr(shell_open, "has_shell", lambda: True)
        monkeypatch.setattr(
            shell_open, "_explorer_launch",
            lambda text, is_dir: calls.append((text, is_dir)) or True)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: pytest.fail("explorer 成功时不该再走 Qt"))

        assert shell_open.open_dir(tmp_path) is True
        assert calls and calls[0][1] is True

    def test_posix_uses_qt(self, monkeypatch):
        opened = []
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url.toString()) or True)
        assert shell_open.open_path("/tmp") is True
        assert opened and opened[0].startswith("file://")

    def test_empty_path_is_rejected(self):
        assert shell_open.open_path("") is False
        assert shell_open.open_path(None) is False


class TestOpenDir:
    def test_missing_dir_returns_false(self, tmp_path):
        """目录不存在时静默返回 False，而不是弹一个看不懂的系统错误"""
        assert shell_open.open_dir(tmp_path / "nope") is False

    def test_missing_dir_records_reason(self, tmp_path):
        """失败原因要能取到 —— 界面直接显示它，而不是只说「打不开」"""
        shell_open.open_dir(tmp_path / "nope")
        assert "目录不存在" in shell_open.last_error()

    def test_existing_dir_is_opened(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url) or True)
        assert shell_open.open_dir(tmp_path) is True
        assert opened


class TestErrorReporting:
    def test_success_clears_last_error(self, tmp_path, monkeypatch):
        shell_open.open_dir(tmp_path / "nope")           # 先制造一次失败
        assert shell_open.last_error()
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl", lambda url: True)
        assert shell_open.open_dir(tmp_path) is True
        assert shell_open.last_error() == ""

    def test_all_methods_failing_reports_each_step(self, monkeypatch):
        """每一级的失败原因都要留下来，否则没法判断到底卡在哪"""
        monkeypatch.setattr(os, "name", "nt")

        def boom(path):
            raise OSError("error 5")

        monkeypatch.setattr(os, "startfile", boom, raising=False)
        monkeypatch.setattr(shell_open, "_explorer_launch", lambda *a: False)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl", lambda url: False)

        assert shell_open.open_path("C:/x") is False
        err = shell_open.last_error()
        assert "os.startfile" in err
        assert "error 5" in err


class TestNoShellSession:
    """
    回归：无桌面外壳的会话（低完整性/服务/容器）里打开**文件夹**

    实测（Windows 11，S-1-16-4096，tasklist 里没有 explorer.exe）：
    打开目录一律 error 5，而打开文件成功。更糟的是 `Popen(["explorer", 路径])`
    会返回成功、随后 explorer 以 0xc0000142 立刻死掉 ——
    若把它当成功，用户看到的是「点了没反应」。
    """

    def test_dir_without_shell_fails_with_explanation(self, tmp_path, monkeypatch):
        # 不要 patch pathlib.Path：PosixPath 在真 Windows 上会抛
        # UnsupportedOperation。改 patch 产品代码里的 _is_dir。
        monkeypatch.setattr(os, "name", "nt")
        # 同上：不屏蔽第一级的话，真 Windows 上它会把目录打开成功
        monkeypatch.setattr(os, "startfile", _startfile_denied, raising=False)
        monkeypatch.setattr(shell_open, "_is_dir", lambda t: True)
        monkeypatch.setattr(shell_open, "_shell_execute", lambda text: False)
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: pytest.fail("没有 shell 时不该再去调 Qt，只会制造噪声"))

        assert shell_open.open_dir(tmp_path) is False
        err = shell_open.last_error()
        assert "Explorer" in err and "文件夹" in err

    def test_file_without_shell_still_tries_startfile(self, monkeypatch):
        """文件走文件关联，不需要 shell —— 这条不能一并否掉"""
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "_is_dir", lambda t: False)
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)

        assert shell_open.open_path(r"C:\x\a.png") is True
        assert calls == [r"C:\x\a.png"]

    def test_explorer_is_never_used_without_shell(self, monkeypatch):
        """无 shell 时绝不能调 explorer —— 它必然立刻死，属于假阳性来源"""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(
            shell_open.subprocess, "Popen",
            lambda *a, **k: pytest.fail("没有 shell 时不该调 explorer"))
        shell_open._explorer_launch("C:/x", True)
        assert "没有 Explorer" in shell_open.last_error()

    def test_explorer_exit_code_1_counts_as_success(self, monkeypatch):
        """
        实测：explorer 成功打开文件夹时退出码是 **1**（把请求交给已有实例后自己退出）。
        所以不能拿 ==0 判断成功，否则正常工作也会被报成失败。
        """
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "has_shell", lambda: True)

        class Proc:
            returncode = 1

            def wait(self, timeout=None):
                return self.returncode

        monkeypatch.setattr(shell_open.subprocess, "Popen", lambda *a, **k: Proc())
        assert shell_open._explorer_launch("C:/x", True) is True
        assert shell_open.last_error() == ""

    def test_explorer_dying_immediately_is_a_failure(self, tmp_path, monkeypatch):
        """0xC0000142 这种 DLL 初始化失败才算真失败"""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "has_shell", lambda: True)

        class Proc:
            returncode = 0xc0000142

            def wait(self, timeout=None):
                return self.returncode

        monkeypatch.setattr(shell_open.subprocess, "Popen", lambda *a, **k: Proc())
        assert shell_open._explorer_launch(str(tmp_path), True) is False
        assert "立即退出" in shell_open.last_error()


class TestShellContextInError:
    def test_error_carries_shell_window_state(self, monkeypatch):
        """失败信息要能自证环境：GetShellWindow=0 说明是无 shell 会话"""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(shell_open, "_shell_context",
                            lambda: "（GetShellWindow=0（无桌面外壳）；Python 3.14.5）")
        shell_open.open_path("C:/x")
        err = shell_open.last_error()
        assert "GetShellWindow=0" in err and "Python 3.14.5" in err


class TestIntegrityDetection:
    def test_posix_has_no_integrity(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        assert shell_open.process_integrity() == ""

    def test_gui_warns_only_on_low(self, monkeypatch, capsys):
        import imgsearch_gui.app as app_mod
        from imgsearch_gui import shell_open as so

        monkeypatch.setattr(so, "process_integrity", lambda: "Medium")
        app_mod.warn_if_low_integrity()
        assert "低完整性" not in capsys.readouterr().err

        monkeypatch.setattr(so, "process_integrity", lambda: "Low")
        app_mod.warn_if_low_integrity()
        err = capsys.readouterr().err
        assert "低完整性" in err and "C0000142".upper() in err.upper()


class TestShellContext:
    def test_context_includes_integrity(self, monkeypatch):
        """失败信息要带进程完整性 —— 这是区分"代码 bug"和"Low 环境"的关键"""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "process_integrity", lambda: "Low")
        ctx = shell_open._shell_context()
        assert "进程完整性=Low" in ctx
        assert "Python" in ctx

    def test_context_is_empty_on_posix(self, monkeypatch):
        # ⚠️ 这条断言的是「POSIX 上不产生线索」。真 Windows 上 _shell_context()
        #    必然返回内容（GetShellWindow / Python 版本 / 完整性），所以不能
        #    依赖宿主平台 —— 把 os.name 切成 posix 才测得到这条分支。
        monkeypatch.setattr(os, "name", "posix")
        assert shell_open._shell_context() == ""


class TestOpenUrl:
    def test_uses_qt_with_raw_url(self, monkeypatch):
        opened = []
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url.toString()) or True)
        assert shell_open.open_url("https://www.pixiv.net/artworks/1") is True
        assert opened == ["https://www.pixiv.net/artworks/1"]

    def test_empty_url_rejected(self):
        assert shell_open.open_url("") is False
        assert shell_open.open_url(None) is False


class TestGuiGoesThroughTheHelper:
    """
    守一条纪律：GUI 里打开**本地路径**必须走 shell_open。

    只要有人再写 `QUrl.fromLocalFile`，Windows 上就会重新踩这个坑，
    所以用一条静态检查把它挡住。
    """

    def test_no_direct_fromlocalfile_in_gui(self):
        root = Path(__file__).resolve().parent.parent / "imgsearch_gui"
        offenders = []
        for py in root.rglob("*.py"):
            if py.name == "shell_open.py":
                continue
            if "QUrl.fromLocalFile" in py.read_text(encoding="utf-8"):
                offenders.append(py.name)
        assert not offenders, f"这些文件应改用 shell_open：{offenders}"
