"""
图标查找：源码运行 / onedir / onefile 三种位置

打包后 assets/ 的位置会变（`_internal/` 或 `sys._MEIPASS`），
找错了就是"窗口没有图标"，而 Qt 不会报错 —— 只能靠测试盯住。
"""

import sys

import pytest

pytest.importorskip("PySide6")

import imgsearch_gui.assets as assets        # noqa: E402


class TestSourceRun:
    def test_finds_icon_in_repo(self):
        path = assets.asset_path(assets.WINDOW_ICON)
        assert path.is_file()
        assert path.parent.name == "assets"

    def test_ico_ships_for_windows(self):
        """exe 图标（--icon 用）必须一起入库"""
        assert assets.asset_path("ImageSearch.ico").is_file()

    def test_all_sizes_present(self):
        for size in (16, 24, 32, 48, 64, 128, 256, 512):
            assert assets.asset_path(f"ImageSearch-{size}.png").is_file()


class TestFrozen:
    def test_onedir_looks_inside_internal(self, tmp_path, monkeypatch):
        exe = tmp_path / "dist" / "ImageSearch"
        internal = exe.parent / "_internal" / "assets"
        internal.mkdir(parents=True)
        (internal / "ImageSearch-256.png").write_bytes(b"x")
        exe.write_text("")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe), raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

        assert assets.asset_path("ImageSearch-256.png").parent == internal

    def test_onefile_prefers_meipass(self, tmp_path, monkeypatch):
        meipass = tmp_path / "tmp_mei123"
        (meipass / "assets").mkdir(parents=True)
        (meipass / "assets" / "ImageSearch-256.png").write_bytes(b"x")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        assert assets.asset_path("ImageSearch-256.png").parent.parent == meipass

    def test_missing_file_returns_repo_path(self, monkeypatch, tmp_path):
        """找不到时返回一个可预期的路径，而不是抛异常"""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "x"), raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        got = assets.asset_path("nope.png")
        assert got.name == "nope.png"
        assert "assets" in got.parts


class TestWindowIcon:
    def test_loads_real_icon(self, qapp):
        icon = assets.window_icon()
        assert not icon.isNull()

    def test_missing_icon_does_not_raise(self, monkeypatch, tmp_path):
        """图标丢了也不该让程序起不来"""
        monkeypatch.setattr(assets, "WINDOW_ICON", "definitely-missing.png")
        icon = assets.window_icon()
        assert icon.isNull()
