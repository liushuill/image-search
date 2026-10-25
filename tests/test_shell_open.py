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
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url.toString()) or True)
        assert shell_open.open_path("C:/x") is True
        assert opened, "应当退回 Qt"

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

    def test_existing_dir_is_opened(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(
            shell_open.QtGui.QDesktopServices, "openUrl",
            lambda url: opened.append(url) or True)
        assert shell_open.open_dir(tmp_path) is True
        assert opened


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
