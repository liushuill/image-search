"""
数据目录的决策：源码运行 vs 打包运行

打包成 exe 后，程序目录可能在 ``Program Files``（只读）或升级时被整体替换，
数据必须落到用户目录；而源码运行时必须保持原样（数据就在仓库里）。
这条分支写错了，症状是"升级后图库全没了"或"装完根本写不了配置"。
"""

import sys

import pytest

import imgsearch.config as cfg


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """把进程伪装成 PyInstaller 打包后的样子"""
    exe = tmp_path / "dist" / "ImageSearch"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    monkeypatch.delenv("IMGSEARCH_DATA_DIR", raising=False)
    return exe.parent


class TestSourceRun:
    def test_data_lives_beside_the_repo(self, monkeypatch):
        """源码运行：保持原行为，数据就在仓库目录"""
        monkeypatch.delenv("IMGSEARCH_DATA_DIR", raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert cfg._resolve_data_root() == cfg.APP_DIR

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("IMGSEARCH_DATA_DIR", str(tmp_path))
        assert cfg._resolve_data_root() == tmp_path.resolve()


class TestFrozen:
    def test_windows_uses_localappdata(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_is_windows", lambda: True)
        monkeypatch.setattr(cfg, "_is_macos", lambda: False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        monkeypatch.delenv("APPDATA", raising=False)
        root = cfg._resolve_data_root()
        assert root == (tmp_path / "Local" / "image-search").resolve()

    def test_windows_falls_back_to_appdata(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_is_windows", lambda: True)
        monkeypatch.setattr(cfg, "_is_macos", lambda: False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert cfg._resolve_data_root() == (tmp_path / "Roaming" / "image-search").resolve()

    def test_linux_respects_xdg(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_is_windows", lambda: False)
        monkeypatch.setattr(cfg, "_is_macos", lambda: False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert cfg._resolve_data_root() == (tmp_path / "xdg" / "image-search").resolve()

    def test_linux_defaults_to_local_share(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_is_windows", lambda: False)
        monkeypatch.setattr(cfg, "_is_macos", lambda: False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        root = cfg._resolve_data_root()
        assert root == (tmp_path / ".local" / "share" / "image-search").resolve()

    def test_macos_uses_application_support(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_is_windows", lambda: False)
        monkeypatch.setattr(cfg, "_is_macos", lambda: True)
        monkeypatch.setenv("HOME", str(tmp_path))
        root = cfg._resolve_data_root()
        assert root == (tmp_path / "Library" / "Application Support"
                        / "image-search").resolve()

    def test_portable_marker_keeps_data_beside_exe(self, frozen, monkeypatch):
        """exe 旁边有 portable.txt 时，数据就留在 exe 旁（便携版）"""
        (frozen / "portable.txt").write_text("", encoding="utf-8")
        monkeypatch.setattr(cfg, "_is_windows", lambda: True)
        monkeypatch.setattr(cfg, "_is_macos", lambda: False)
        monkeypatch.setenv("LOCALAPPDATA", "C:/should/not/be/used")
        assert cfg._resolve_data_root() == frozen.resolve()

    def test_env_override_beats_frozen(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setenv("IMGSEARCH_DATA_DIR", str(tmp_path / "custom"))
        assert cfg._resolve_data_root() == (tmp_path / "custom").resolve()


class TestConstantsFollowRoot:
    def test_all_writable_paths_are_under_data_root(self, monkeypatch, tmp_path):
        """数据根换了，config.json / .env / data / output 都要跟着走"""
        import importlib

        monkeypatch.setenv("IMGSEARCH_DATA_DIR", str(tmp_path))
        try:
            reloaded = importlib.reload(cfg)
            root = tmp_path.resolve()
            assert reloaded.DATA_ROOT == root
            assert reloaded._CONFIG_FILE == root / "config.json"
            assert reloaded.ENV_FILE == root / ".env"
            assert reloaded.DATA_DIR == root / "data"
            assert reloaded.CACHE_DIR == root / "data" / "cache"
            assert reloaded.DB_PATH == root / "data" / "image_metadata.db"
            assert reloaded.THUMBS_DIR == root / "data" / "thumbs"
            assert reloaded.OUTPUT_DIR == root / "output"
            assert reloaded.PLUGIN_DIR == root / "my_engines"
        finally:
            monkeypatch.delenv("IMGSEARCH_DATA_DIR")
            importlib.reload(cfg)

    def test_app_dir_never_moves(self):
        """只读资源根（代码所在处）不受数据目录影响"""
        assert cfg.APP_DIR.name or cfg.APP_DIR.is_dir()
        assert (cfg.APP_DIR / "imgsearch").is_dir()


class TestSecretsUsesSameEnvFile:
    def test_secrets_does_not_compute_its_own_path(self):
        """
        凭据文件只能有一处定义。

        静态检查（运行期比不了：conftest 会把 secrets.ENV_FILE 换到临时目录）：
        secrets.py 里不应再出现 `Path(__file__)` 这种自己算根目录的写法。
        """
        import pathlib as _pl

        src = (_pl.Path(cfg.APP_DIR) / "imgsearch" / "secrets.py").read_text(
            encoding="utf-8")
        assert "ENV_FILE" in src
        assert "from imgsearch.config import" in src
        assert "Path(__file__)" not in src, "secrets.py 不该自己算项目根"
