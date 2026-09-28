"""
EngineConfig 和 EngineManager 测试

注意：这些测试会读写实际的 config.json。
测试会自动保存和恢复原始配置，避免影响正常使用。
"""

import json
import os
import copy
from dataclasses import asdict

import pytest

from imgsearch import secrets
from imgsearch.config import _CONFIG_FILE, _config, load_config, save_config
from imgsearch.engines.config import (
    EngineConfig,
    EngineManager,
    resolve_engine_class,
    register_engine_class,
    _ENGINE_CLASS_CACHE,
    _CONFIG_KEY,
)


# ── 辅助函数 ─────────────────────────────────────────────

def _reset_config_and_cache():
    """重置 config 缓存和引擎类缓存"""
    import imgsearch.config as config_module
    config_module._config = None
    _ENGINE_CLASS_CACHE.clear()


def _init_empty_mgr() -> EngineManager:
    """
    创建一个空引擎 Manager。
    
    注意：save_config([], ...) 会被 _load() 识别为空列表并重置为出厂默认值，
    因此这里写入占位引擎，然后通过 remove 清空。
    """
    placeholder = asdict(EngineConfig(name="__test_placeholder__"))
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"search_engines": [placeholder]}, f, ensure_ascii=False, indent=2)
    _reset_config_and_cache()
    mgr = EngineManager()
    mgr.remove("__test_placeholder__")
    return mgr


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def backup_and_restore_config():
    """
    自动备份和恢复 config.json 与 .env，确保测试不污染实际配置。

    注意 .env 也要备份：敏感键（如 saucenao_key）的 save_config()
    会被转发到 .env，不还原就会覆盖掉真实凭据。
    """
    original_config_content = None
    if _CONFIG_FILE.exists():
        original_config_content = _CONFIG_FILE.read_text(encoding="utf-8")
    original_global_config = copy.deepcopy(_config)

    original_env_content = None
    if secrets.ENV_FILE.exists():
        original_env_content = secrets.ENV_FILE.read_text(encoding="utf-8")
    secrets.invalidate_cache()

    yield  # 测试执行

    # 恢复全局缓存
    import imgsearch.config as config_module
    config_module._config = original_global_config
    # 恢复 config.json 内容
    if original_config_content is not None:
        _CONFIG_FILE.write_text(original_config_content, encoding="utf-8")
    elif _CONFIG_FILE.exists():
        _CONFIG_FILE.unlink()
    # 恢复 .env 内容并丢弃缓存
    if original_env_content is not None:
        secrets.ENV_FILE.write_text(original_env_content, encoding="utf-8")
        try:
            os.chmod(secrets.ENV_FILE, 0o600)
        except OSError:
            pass
    elif secrets.ENV_FILE.exists():
        secrets.ENV_FILE.unlink()
    secrets.invalidate_cache()
    # 清空引擎类缓存
    _ENGINE_CLASS_CACHE.clear()


# ── EngineConfig 测试 ────────────────────────────────────

class TestEngineConfig:
    def test_default_values(self):
        ec = EngineConfig(name="test")
        assert ec.name == "test"
        assert ec.enabled is True
        assert ec.priority == 0
        assert ec.api_url == ""
        assert ec.api_key == ""
        assert ec.headers == {}
        assert ec.params == {}
        assert ec.request_delay == 8.0
        assert ec.timeout == 30
        assert ec.long_limit == 100
        assert ec.short_limit == 4
        assert ec.long_window == 86400
        assert ec.short_window == 30
        assert ec.bypass_cfw is False
        assert ec.module_path == ""
        assert ec.class_name == ""

    def test_custom_values(self):
        ec = EngineConfig(
            name="my_engine", enabled=False, priority=5,
            api_url="https://api.example.com", api_key="key123",
            headers={"X-Custom": "1"}, params={"db": 999},
            request_delay=2.0, timeout=60,
            long_limit=200, short_limit=10,
            long_window=43200, short_window=15,
            bypass_cfw=True,
            module_path="my_engines.custom", class_name="CustomEngine",
        )
        assert ec.name == "my_engine"
        assert ec.enabled is False
        assert ec.priority == 5
        assert ec.api_key == "key123"
        assert ec.bypass_cfw is True
        assert ec.module_path == "my_engines.custom"
        assert ec.class_name == "CustomEngine"


# ── EngineManager 测试 ────────────────────────────────────

class TestEngineManager:
    def test_init_empty(self):
        """空列表 → 恢复出厂默认（sauceNAO + ascii2d + danbooru 共 3 个）"""
        save_config(_CONFIG_KEY, [])
        _reset_config_and_cache()
        mgr = EngineManager()
        assert len(mgr.list_all()) == 3

    def test_add_engine(self):
        mgr = _init_empty_mgr()
        ok = mgr.add("test_engine")
        assert ok is True
        engines = mgr.list_all()
        assert len(engines) == 1
        assert engines[0].name == "test_engine"
        assert engines[0].enabled is True

    def test_add_duplicate(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        ok = mgr.add("test_engine")
        assert ok is False

    def test_remove_custom_engine(self):
        mgr = _init_empty_mgr()
        mgr.add("my_engine")
        assert mgr.remove("my_engine") is True
        assert len(mgr.list_all()) == 0

    def test_remove_nonexistent(self):
        mgr = _init_empty_mgr()
        assert mgr.remove("nonexistent") is False

    def test_remove_builtin(self):
        mgr = EngineManager()
        assert mgr.remove("sauceNAO") is False
        assert mgr.get_by_name("sauceNAO") is not None

    def test_toggle_engine(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        result = mgr.toggle("test_engine")
        assert result is False
        assert mgr.get_by_name("test_engine").enabled is False
        result = mgr.toggle("test_engine")
        assert result is True

    def test_toggle_nonexistent(self):
        mgr = EngineManager()
        assert mgr.toggle("nonexistent") is None

    def test_set_enabled(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        assert mgr.set_enabled("test_engine", False) is True
        assert mgr.get_by_name("test_engine").enabled is False

    def test_get_enabled(self):
        mgr = _init_empty_mgr()
        mgr.add("eng1", enabled=True)
        mgr.add("eng2", enabled=False)
        mgr.add("eng3", enabled=True)
        enabled = mgr.get_enabled()
        assert len(enabled) == 2
        assert {e.name for e in enabled} == {"eng1", "eng3"}

    def test_move_engine_up(self):
        mgr = _init_empty_mgr()
        mgr.add("eng_a")
        mgr.add("eng_b")
        mgr.add("eng_c")
        mgr.move("eng_b", -1)
        names = [e.name for e in mgr.list_all()]
        assert names == ["eng_b", "eng_a", "eng_c"], f"实际顺序: {names}"

    def test_move_engine_down(self):
        mgr = _init_empty_mgr()
        mgr.add("eng_a")
        mgr.add("eng_b")
        mgr.add("eng_c")
        mgr.move("eng_a", 1)
        names = [e.name for e in mgr.list_all()]
        assert names == ["eng_b", "eng_a", "eng_c"], f"实际顺序: {names}"

    def test_move_boundary_up(self):
        mgr = _init_empty_mgr()
        mgr.add("eng_a")
        mgr.add("eng_b")
        assert mgr.move("eng_a", -1) is False

    def test_move_boundary_down(self):
        mgr = _init_empty_mgr()
        mgr.add("eng_a")
        mgr.add("eng_b")
        assert mgr.move("eng_b", 1) is False

    def test_update_config(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        ok = mgr.update_config("test_engine", api_key="new_key", timeout=60, bypass_cfw=True)
        assert ok is True
        ec = mgr.get_by_name("test_engine")
        assert ec.api_key == "new_key"
        assert ec.timeout == 60
        assert ec.bypass_cfw is True

    def test_update_config_nonexistent(self):
        mgr = _init_empty_mgr()
        assert mgr.update_config("nonexistent", api_key="x") is False

    def test_update_config_unknown_field(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        ok = mgr.update_config("test_engine", nonexistent_field="value")
        assert ok is True

    def test_reset_engines(self):
        _reset_config_and_cache()
        mgr = EngineManager()
        mgr.add("eng_a")
        mgr.add("eng_b")
        mgr.reset()
        engines = mgr.list_all()
        assert len(engines) == 3
        assert engines[0].name == "sauceNAO"
        assert engines[1].name == "ascii2d"
        assert engines[2].name == "danbooru"

    def test_get_by_name_nonexistent(self):
        mgr = EngineManager()
        assert mgr.get_by_name("nonexistent") is None

    def test_get_by_name_case_insensitive(self):
        mgr = _init_empty_mgr()
        mgr.add("MyEngine")
        assert mgr.get_by_name("myengine") is not None
        assert mgr.get_by_name("MYENGINE") is not None

    def test_get_resolved_api_key(self):
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        mgr.update_config("test_engine", api_key="my_key")
        assert mgr.get_resolved_api_key("test_engine") == "my_key"

    def test_get_resolved_api_key_fallback(self):
        """测试引擎 api_key 为空时回退到全局 saucenao_key"""
        # 先创建空管理器，再设置全局 key（避免被 _init_empty_mgr 覆盖）
        mgr = _init_empty_mgr()
        mgr.add("test_engine")
        mgr.update_config("test_engine", api_key="")
        # 设置全局 key
        save_config("saucenao_key", "global_key")
        _reset_config_and_cache()
        # 重新加载
        mgr2 = EngineManager()
        assert mgr2.get_resolved_api_key("test_engine") == "global_key"

    def test_priority_auto_renumber(self):
        mgr = _init_empty_mgr()
        mgr.add("eng_a")
        mgr.add("eng_b")
        mgr.add("eng_c")
        priorities = [e.priority for e in mgr.list_all()]
        assert priorities == [1, 2, 3], f"实际优先级: {priorities}"

    def test_list_all_order(self):
        mgr = _init_empty_mgr()
        mgr.add("z_engine")
        mgr.add("a_engine")
        mgr.add("m_engine")
        names = [e.name for e in mgr.list_all()]
        assert names == ["z_engine", "a_engine", "m_engine"]

    def test_is_builtin(self):
        mgr = EngineManager()
        assert mgr.is_builtin("sauceNAO") is True
        assert mgr.is_builtin("ascii2d") is True
        assert mgr.is_builtin("custom_engine") is False

    def test_get_names(self):
        mgr = EngineManager()
        names = mgr.get_names()
        assert "sauceNAO" in names
        assert "ascii2d" in names

    def test_save_and_reload(self):
        mgr = _init_empty_mgr()
        mgr.add("persist_engine")
        mgr.update_config("persist_engine", api_key="saved_key")
        _reset_config_and_cache()
        mgr2 = EngineManager()
        ec = mgr2.get_by_name("persist_engine")
        assert ec is not None
        assert ec.api_key == "saved_key"


# ── resolve_engine_class 测试 ────────────────────────────

class TestResolveEngineClass:
    def setup_method(self):
        _ENGINE_CLASS_CACHE.clear()

    def test_register_and_resolve(self):
        class FakeEngine:
            pass
        register_engine_class("fake", FakeEngine)
        ec = EngineConfig(name="fake")
        cls = resolve_engine_class(ec)
        assert cls is FakeEngine

    def test_resolve_nonexistent(self):
        ec = EngineConfig(name="nonexistent")
        cls = resolve_engine_class(ec)
        assert cls is None

    def test_resolve_custom_module_not_found(self):
        ec = EngineConfig(
            name="custom",
            module_path="nonexistent_module_xyz",
            class_name="MyEngine",
        )
        cls = resolve_engine_class(ec)
        assert cls is None

    def test_cache_hit(self):
        class CachedEngine:
            pass
        _ENGINE_CLASS_CACHE["cached"] = CachedEngine
        ec = EngineConfig(name="cached")
        cls = resolve_engine_class(ec)
        assert cls is CachedEngine
