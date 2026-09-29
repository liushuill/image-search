"""
凭据文件（.env）测试

这是安全相关的模块：读写凭据、原子写、权限收紧、跨平台差异。
"""

import os
import stat

import pytest

from imgsearch import secrets


class TestReadWrite:
    def test_set_then_get(self):
        secrets.set("SAUCENAO_KEY", "abc123")
        assert secrets.get("SAUCENAO_KEY") == "abc123"

    def test_unset(self):
        secrets.set("SAUCENAO_KEY", "abc123")
        assert secrets.unset("SAUCENAO_KEY") is True
        assert secrets.get("SAUCENAO_KEY") is None
        assert secrets.unset("SAUCENAO_KEY") is False

    def test_is_set(self):
        assert secrets.is_set("SAUCENAO_KEY") is False
        secrets.set("SAUCENAO_KEY", "x")
        assert secrets.is_set("SAUCENAO_KEY") is True

    def test_update_existing_key(self):
        secrets.set("SAUCENAO_KEY", "first")
        secrets.set("SAUCENAO_KEY", "second")
        assert secrets.get("SAUCENAO_KEY") == "second"
        # 不该留下重复行
        text = secrets.ENV_FILE.read_text(encoding="utf-8")
        assert text.count("SAUCENAO_KEY=") == 1

    def test_other_keys_survive(self):
        secrets.set("SAUCENAO_KEY", "a")
        secrets.set("DANBOORU_LOGIN", "b")
        secrets.set("SAUCENAO_KEY", "c")
        assert secrets.get("DANBOORU_LOGIN") == "b"

    def test_comments_are_preserved(self):
        secrets.ensure_env_file()
        text = secrets.ENV_FILE.read_text(encoding="utf-8")
        assert "# image-search" in text
        secrets.set("SAUCENAO_KEY", "x")
        assert "# image-search" in secrets.ENV_FILE.read_text(encoding="utf-8")

    def test_value_with_spaces_is_quoted_and_readable(self):
        secrets.set("SAUCENAO_KEY", "has space")
        secrets.invalidate_cache()
        assert secrets.get("SAUCENAO_KEY") == "has space"

    def test_empty_value_reads_as_unset(self):
        secrets.set("SAUCENAO_KEY", "")
        assert secrets.get("SAUCENAO_KEY") is None
        assert secrets.get("SAUCENAO_KEY", "fallback") == "fallback"


class TestPrecedence:
    def test_real_env_var_wins_over_file(self, monkeypatch):
        """真实环境变量优先，便于临时覆盖"""
        secrets.set("SAUCENAO_KEY", "from-file")
        monkeypatch.setenv("SAUCENAO_KEY", "from-env")
        assert secrets.get("SAUCENAO_KEY") == "from-env"

    def test_falls_back_to_file(self, monkeypatch):
        monkeypatch.delenv("SAUCENAO_KEY", raising=False)
        secrets.set("SAUCENAO_KEY", "from-file")
        assert secrets.get("SAUCENAO_KEY") == "from-file"


class TestFileHandling:
    def test_ensure_env_file_creates(self):
        assert secrets.ensure_env_file() is True
        assert secrets.ENV_FILE.exists()
        # 再次调用不该重复创建
        assert secrets.ensure_env_file() is False

    def test_permissions_are_600_on_posix(self):
        if os.name == "nt":
            pytest.skip("POSIX 权限位")
        secrets.set("SAUCENAO_KEY", "x")
        mode = stat.S_IMODE(secrets.ENV_FILE.stat().st_mode)
        assert mode == 0o600

    def test_write_is_atomic_no_temp_left_behind(self):
        secrets.set("SAUCENAO_KEY", "x")
        leftovers = list(secrets.ENV_FILE.parent.glob(".env.tmp*"))
        assert leftovers == [], f"残留临时文件：{leftovers}"

    def test_corrupt_lines_are_skipped(self):
        secrets.ENV_FILE.write_text(
            "# comment\nBADLINE\nSAUCENAO_KEY=ok\n\nexport DANBOORU_LOGIN=user\n",
            encoding="utf-8",
        )
        secrets.invalidate_cache()
        assert secrets.get("SAUCENAO_KEY") == "ok"
        assert secrets.get("DANBOORU_LOGIN") == "user"

    def test_quoted_and_unquoted_both_parse(self):
        secrets.ENV_FILE.write_text(
            'A="quoted value"\nB=plain\n', encoding="utf-8"
        )
        secrets.invalidate_cache()
        assert secrets.get("A") == "quoted value"
        assert secrets.get("B") == "plain"


class TestMasking:
    def test_masked_hides_middle(self):
        secrets.set("SAUCENAO_KEY", "abcdef1234567890")
        masked = secrets.masked("SAUCENAO_KEY")
        assert "abcdef1234567890" not in masked
        assert masked.startswith("abcd") and masked.endswith("7890")

    def test_masked_short_value_reveals_nothing(self):
        """短凭据必须完全隐藏 —— 露出前 2 位等于泄露大部分内容"""
        secrets.set("DANBOORU_LOGIN", "ab")
        assert secrets.masked("DANBOORU_LOGIN") == "****"

    def test_masked_medium_value_reveals_nothing(self):
        secrets.set("DANBOORU_LOGIN", "hunter2!")          # 8 位
        assert secrets.masked("DANBOORU_LOGIN") == "****"

    def test_masked_long_value_shows_ends_only(self):
        secrets.set("SAUCENAO_KEY", "0123456789abcdef")    # 16 位
        masked = secrets.masked("SAUCENAO_KEY")
        assert masked == "0123****cdef"
        assert "456789ab" not in masked

    def test_masked_unset(self):
        assert "未设置" in secrets.masked("SAUCENAO_KEY")


class TestPermissionStatus:
    """
    跨平台差异：Windows 没有 POSIX 权限位，
    拿 0o600 去比对会给出一个用户无法「修好」的假告警。
    """

    def test_missing_file(self):
        note, warn = secrets.permission_status()
        assert "尚未创建" in note and warn is False

    def test_posix_correct_mode(self):
        if os.name == "nt":
            pytest.skip("POSIX 权限位")
        secrets.set("SAUCENAO_KEY", "x")
        note, warn = secrets.permission_status()
        assert "600" in note and warn is False

    def test_posix_loose_mode_warns(self):
        if os.name == "nt":
            pytest.skip("POSIX 权限位")
        secrets.set("SAUCENAO_KEY", "x")
        os.chmod(secrets.ENV_FILE, 0o644)
        note, warn = secrets.permission_status()
        assert warn is True and "644" in note

    def test_windows_branch_does_not_warn(self):
        """Windows 上必须不告警 —— 否则是在提示一个不存在的问题"""
        secrets.set("SAUCENAO_KEY", "x")
        note, warn = secrets.permission_status(is_windows=True)
        assert warn is False
        assert "Windows" in note and "POSIX" in note

    def test_windows_branch_missing_file_still_reports(self):
        note, warn = secrets.permission_status(is_windows=True)
        assert "尚未创建" in note and warn is False


class TestInitHint:
    def test_posix_hint_uses_chmod(self):
        assert "chmod 600" in secrets.init_hint()

    def test_windows_hint_uses_copy(self):
        assert secrets.IS_WINDOWS is False        # 本机是 POSIX
        # 直接验证 Windows 那条分支的语义：不该出现 chmod
        hint_posix = secrets.init_hint()
        assert "cp " in hint_posix


class TestDeclaredSecrets:
    """凭据清单来自「已知清单 ∪ 引擎 schema」，自定义引擎的凭据也要出现"""

    def test_contains_known_and_uniqueness(self):
        from imgsearch.service import declared_secrets
        specs = declared_secrets()
        names = [n for n, _, _ in specs]
        assert "SAUCENAO_KEY" in names
        assert len(names) == len(set(names)), "清单里有重复项"

    def test_titles_are_human_readable(self):
        from imgsearch.service import declared_secrets
        for name, title, desc in declared_secrets():
            assert title and name
            assert title != "None"
