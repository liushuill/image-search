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


class TestOpenPath:
    def test_windows_uses_startfile_with_native_path(self, monkeypatch):
        """Windows 上必须传**原生路径**，不能是 file:// URL —— 这正是 bug 的成因"""
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)

        assert shell_open.open_path(r"C:\Users\a\output") is True
        assert calls == [r"C:\Users\a\output"]

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

    def test_windows_tries_explorer_between_startfile_and_qt(self, monkeypatch):
        """
        实测有机器连 os.startfile 都返回 error 5，但 explorer 能打开。
        所以中间必须夹一层 explorer，且成功时不再走 Qt。
        """
        calls = []
        monkeypatch.setattr(os, "name", "nt")

        def boom(path):
            raise OSError("error 5")

        monkeypatch.setattr(os, "startfile", boom, raising=False)
        monkeypatch.setattr(
            shell_open, "_explorer_launch",
            lambda text, is_dir: calls.append((text, is_dir)) or True)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: pytest.fail("explorer 成功时不该再走 Qt"))

        assert shell_open.open_path(r"C:\Users\a\output") is True
        assert calls == [(r"C:\Users\a\output", False)]

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
        # ⚠️ pathlib.Path 的工厂会**在调用时**按 os.name 选 WindowsPath，
        #    于是 Path("/tmp/...") 变成 WindowsPath、is_dir() 直接 False。
        #    所以这里把 shell_open 里的 Path 固定成 PosixPath。
        import pathlib as _pl
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "Path", _pl.PosixPath)
        monkeypatch.setattr(os, "startfile",
                            lambda p: (_ for _ in ()).throw(OSError("error 5")),
                            raising=False)
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: pytest.fail("没有 shell 时不该再去调 Qt，只会制造噪声"))

        assert shell_open.open_dir(tmp_path) is False
        err = shell_open.last_error()
        assert "Explorer" in err and "文件夹" in err

    def test_file_without_shell_still_tries_startfile(self, tmp_path, monkeypatch):
        """文件走文件关联，不需要 shell —— 这条不能一并否掉"""
        import pathlib as _pl
        calls = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "Path", _pl.PosixPath)
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)

        f = tmp_path / "a.png"
        f.write_bytes(b"x")
        assert shell_open.open_path(str(f)) is True
        assert calls == [str(f)]

    def test_explorer_is_never_used_without_shell(self, monkeypatch):
        """无 shell 时绝不能调 explorer —— 它必然立刻死，属于假阳性来源"""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(shell_open, "has_shell", lambda: False)
        monkeypatch.setattr(
            shell_open.subprocess, "Popen",
            lambda *a, **k: pytest.fail("没有 shell 时不该调 explorer"))
        shell_open._explorer_launch("C:/x", True)
        assert "没有 Explorer" in shell_open.last_error()

    def test_explorer_dying_immediately_is_a_failure(self, tmp_path, monkeypatch):
        """explorer 立即以非 0 退出 = 没打开，不能报成功"""
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
        monkeypatch.setattr(shell_open, "_shell_context", lambda: "（GetShellWindow=0，无桌面外壳）")
        shell_open.open_path("C:/x")
        assert "GetShellWindow=0" in shell_open.last_error()


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
