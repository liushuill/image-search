"""
EngineStore 测试：加载/迁移、增删改查、原子写入、单一数据源
"""

import pytest

from imgsearch.engines.schema import ConfigError
from imgsearch.engines.store import (
    EngineConfig,
    EngineNotFoundError,
    EngineStore,
    get_store,
    reset_store,
)


class TestDefaults:
    def test_fresh_install_creates_all_builtins(self, store):
        names = store.names()
        for expected in ("sauceNAO", "iqdb", "ascii2d", "traceMoe", "danbooru"):
            assert expected in names, expected

    def test_default_order_matches_declared_order(self, store):
        assert store.names() == ["sauceNAO", "iqdb", "ascii2d", "traceMoe", "danbooru"]

    def test_engines_that_need_credentials_are_off_by_default(self, store):
        assert store.get("sauceNAO").enabled is True
        assert store.get("iqdb").enabled is True
        # 需要账号 → 默认关闭，避免开箱即报错
        assert store.get("danbooru").enabled is False
        # 实测已不可用 / 只适合动画截图 → 默认关闭
        assert store.get("ascii2d").enabled is False
        assert store.get("traceMoe").enabled is False

    def test_priorities_are_sequential(self, store):
        assert [e.priority for e in store.list_all()] == [1, 2, 3, 4, 5]

    def test_settings_filled_from_schema(self, store):
        ec = store.get("sauceNAO")
        for key in ("api_url", "api_key", "min_similarity", "proxy_mode",
                    "request_delay", "timeout", "long_limit", "db", "numres"):
            assert key in ec.settings, key


class TestMigration:
    def test_from_legacy_string_list(self, write_config, store):
        write_config({"search_engines": ["sauceNAO", "ascii2d"]})
        s = EngineStore()
        assert s.get("sauceNAO") is not None
        assert s.get("ascii2d") is not None
        # 升级新增的内置引擎会被补进来
        assert s.get("iqdb") is not None

    def test_from_legacy_flat_dict(self, write_config):
        """旧格式把 api_url / timeout 等直接放在顶层，应被收进 settings"""
        write_config({"search_engines": [{
            "name": "sauceNAO", "enabled": True, "priority": 1,
            "api_url": "https://custom.example/search",
            "api_key": "", "timeout": 45, "request_delay": 3.0,
            "headers": {"X-Test": "1"}, "params": {"db": 5},
            "long_limit": 20, "long_window": 3600,
        }]})
        s = EngineStore()
        ec = s.get("sauceNAO")
        assert ec.get("api_url") == "https://custom.example/search"
        assert ec.get("timeout") == 45
        assert ec.get("headers") == {"X-Test": "1"}
        assert ec.get("long_limit") == 20

    def test_name_is_canonicalized(self, write_config):
        """缺陷 #5 关联：配置里写 "Danbooru" 也要能吃到内置默认值"""
        write_config({"search_engines": [
            {"name": "Danbooru", "enabled": True, "priority": 1},
        ]})
        s = EngineStore()
        ec = s.get("danbooru")
        assert ec is not None
        assert ec.name == "danbooru"
        assert "login" in ec.settings

    def test_user_order_is_preserved_and_new_engines_appended(self, write_config):
        write_config({"search_engines": [
            {"name": "danbooru", "enabled": True, "priority": 1},
            {"name": "sauceNAO", "enabled": True, "priority": 2},
        ]})
        s = EngineStore()
        names = s.names()
        assert names[0] == "danbooru"
        assert names[1] == "sauceNAO"
        # 新的内置引擎追加在后面，不插队
        assert names.index("iqdb") > 1

    def test_duplicate_names_are_deduped(self, write_config):
        write_config({"search_engines": [
            {"name": "sauceNAO", "priority": 1},
            {"name": "SauceNAO", "priority": 2},
        ]})
        s = EngineStore()
        assert s.names().count("sauceNAO") == 1

    def test_stale_builtin_keys_are_pruned(self, write_config):
        """
        内置引擎里不属于其 schema 的旧键会被清掉。

        回归：旧配置给 ascii2d 存了 long_limit=100/long_window=0，
        而 ascii2d 根本没有限流逻辑 —— 留着只会困惑界面并误伤校验。
        """
        write_config({"search_engines": [{
            "name": "ascii2d", "enabled": True, "priority": 1,
            "long_limit": 100, "long_window": 0, "short_limit": 4, "short_window": 0,
        }]})
        s = EngineStore()
        ec = s.get("ascii2d")
        assert "long_limit" not in ec.settings
        assert "bypass_cfw" in ec.settings

    def test_custom_engine_unknown_keys_are_kept(self, write_config):
        """自定义引擎的扩展字段不能被清理"""
        write_config({"search_engines": [{
            "name": "mine", "enabled": True, "priority": 1,
            "module_path": "my_engines.mine", "class_name": "Mine",
            "my_custom_option": "keep-me",
        }]})
        s = EngineStore()
        assert s.get("mine").settings["my_custom_option"] == "keep-me"


class TestCrud:
    def test_add_and_remove(self, store):
        store.add("mine")
        assert store.get("mine") is not None
        assert store.remove("mine") is True
        assert store.get("mine") is None

    def test_add_duplicate_raises(self, store):
        store.add("mine")
        with pytest.raises(ConfigError, match="已存在"):
            store.add("MINE")

    def test_add_empty_name_raises(self, store):
        with pytest.raises(ConfigError, match="不能为空"):
            store.add("   ")

    def test_add_with_position(self, store):
        store.add("mine", position=0)
        assert store.names()[0] == "mine"

    def test_remove_builtin_raises(self, store):
        with pytest.raises(ConfigError, match="内置引擎不可删除"):
            store.remove("sauceNAO")

    def test_remove_missing_returns_false(self, store):
        assert store.remove("nope") is False

    def test_get_is_case_insensitive(self, store):
        assert store.get("SAUCENAO") is not None
        assert store.get("SauceNAO") is not None

    def test_toggle(self, store):
        assert store.toggle("sauceNAO") is False
        assert store.get("sauceNAO").enabled is False
        assert store.toggle("sauceNAO") is True

    def test_toggle_missing_returns_none(self, store):
        assert store.toggle("nope") is None

    def test_move(self, store):
        before = store.names()
        assert store.move(before[1], -1) is True
        assert store.names()[0] == before[1]

    def test_move_at_boundary_returns_false(self, store):
        assert store.move(store.names()[0], -1) is False

    def test_update_coerces_types(self, store):
        store.update("sauceNAO", timeout="45", request_delay="2.5",
                     db="5", min_similarity="70")
        ec = store.get("sauceNAO")
        assert ec.get("timeout") == 45 and isinstance(ec.get("timeout"), int)
        assert ec.get("request_delay") == 2.5
        assert ec.get("db") == 5
        assert ec.get("min_similarity") == 70

    def test_update_invalid_value_raises_and_does_not_write(self, store):
        with pytest.raises(ConfigError, match="必须是整数"):
            store.update("sauceNAO", timeout="abc")
        assert store.get("sauceNAO").get("timeout") == 30   # 原值未变

    def test_update_rejects_out_of_choices(self, store):
        with pytest.raises(ConfigError, match="只能是以下之一"):
            store.update("sauceNAO", proxy_mode="sometimes")

    def test_update_cross_field_check(self, store):
        with pytest.raises(ConfigError, match="长期窗口必须大于 0"):
            store.update("sauceNAO", long_limit=100, long_window=0)

    def test_update_nonexistent_returns_false(self, store):
        assert store.update("nope", timeout=1) is False

    def test_set_module(self, store):
        store.add("mine")
        assert store.set_module("mine", "my_engines.mine", "Mine") is True
        ec = store.get("mine")
        assert (ec.module_path, ec.class_name) == ("my_engines.mine", "Mine")

    def test_reset_restores_defaults(self, store):
        store.add("mine")
        store.remove("mine")
        store.reset()
        assert store.names() == ["sauceNAO", "iqdb", "ascii2d", "traceMoe", "danbooru"]

    def test_persistence_round_trip(self, store):
        store.add("mine")
        store.update("mine", timeout=99)
        again = EngineStore()
        assert again.get("mine").get("timeout") == 99


class TestZeroIsPreserved:
    """缺陷 #6 回归：0 表示「无限制」，绝不能被默认值顶掉"""

    def test_update_keeps_zero(self, store):
        store.update("sauceNAO", long_limit=0, long_window=0,
                     short_limit=0, short_window=0)
        ec = store.get("sauceNAO")
        assert ec.get("long_limit") == 0
        assert ec.get("long_window") == 0

    def test_zero_survives_reload(self, store):
        store.update("sauceNAO", long_limit=0, long_window=0)
        again = EngineStore()
        assert again.get("sauceNAO").get("long_limit") == 0

    def test_zero_reaches_engine_kwargs(self, store):
        store.update("sauceNAO", long_limit=0, long_window=0, api_key="k")
        kwargs = store.get("sauceNAO").to_engine_kwargs()
        assert kwargs["long_limit"] == 0
        assert kwargs["long_window"] == 0

    def test_zero_reaches_engine_instance(self, store):
        store.update("sauceNAO", long_limit=0, long_window=0, api_key="k")
        eng = store.build_engine("sauceNAO")
        assert eng._long_limit == 0
        assert eng._long_window == 0
        assert eng._quota.unlimited is True


class TestSingletons:
    """缺陷 #7 回归：多个实例各持一份列表 → 后写覆盖先写"""

    def test_get_store_returns_same_instance(self):
        assert get_store() is get_store()

    def test_reset_store_forces_reload(self):
        first = get_store()
        reset_store()
        assert get_store() is not first

    def test_external_change_is_not_clobbered(self, store):
        """
        旧实现里第二个实例的修改会被第一个实例的下一次保存静默覆盖。
        现在每次改动前会先同步磁盘上的最新状态。
        """
        store.add("eng_a")

        other = EngineStore()          # 模拟「另一个窗口 / 另一个进程」
        other.add("eng_b")

        store.add("eng_c")             # 旧实例继续改动

        final = EngineStore()
        assert {"eng_a", "eng_b", "eng_c"} <= set(final.names()), \
            "外部改动被覆盖了 → reload_if_changed 没生效"


class TestRename:
    """缺陷 #2 / #3 / #4 回归：旧实现用 remove+add 实现改名"""

    def _prepare(self, store):
        store.add("mine", module_path="my_engines.mine", class_name="Mine")
        store.add("other")
        store.update("mine", timeout=77, api_url="https://x.example/s")
        return store.names().index("mine"), store.names().index("other")

    def test_rename_preserves_module_binding(self, store):
        self._prepare(store)
        assert store.rename("mine", "renamed") is True
        ec = store.get("renamed")
        assert ec.module_path == "my_engines.mine", "改名把模块绑定弄丢了（缺陷 #2）"
        assert ec.class_name == "Mine"

    def test_rename_preserves_other_settings(self, store):
        self._prepare(store)
        store.rename("mine", "renamed")
        assert store.get("renamed").get("timeout") == 77
        assert store.get("renamed").get("api_url") == "https://x.example/s"

    def test_rename_keeps_position(self, store):
        idx_mine, idx_other = self._prepare(store)
        store.rename("mine", "renamed")
        names = store.names()
        assert names.index("renamed") == idx_mine, "改名把引擎甩到列表末尾了（缺陷 #3）"
        assert names.index("other") == idx_other

    def test_rename_keeps_priority(self, store):
        store.add("mine")
        before = store.get("mine").priority
        store.rename("mine", "renamed")
        assert store.get("renamed").priority == before

    def test_rename_writes_config_once(self, store, monkeypatch):
        """
        旧实现 remove+add 各写一次盘，中途失败会留下半改状态（缺陷 #4）。
        现在只写一次。
        """
        import imgsearch.config as cfg

        store.add("mine")
        calls = []
        real = cfg._write_config_atomic

        def counting(config):
            calls.append(dict(config))
            real(config)

        monkeypatch.setattr(cfg, "_write_config_atomic", counting)
        store.rename("mine", "renamed")
        assert len(calls) == 1, f"改名写了 {len(calls)} 次盘，应为 1 次"

    def test_rename_to_existing_raises(self, store):
        store.add("mine")
        store.add("other")
        with pytest.raises(ConfigError, match="已存在"):
            store.rename("mine", "other")

    def test_rename_builtin_raises(self, store):
        with pytest.raises(ConfigError, match="内置引擎不可改名"):
            store.rename("sauceNAO", "newname")

    def test_rename_same_name_is_noop(self, store):
        store.add("mine")
        assert store.rename("mine", "mine") is False

    def test_rename_missing_returns_false(self, store):
        assert store.rename("nope", "x") is False


class TestBuildEngine:
    def test_build_unknown_raises(self, store):
        with pytest.raises(EngineNotFoundError):
            store.build_engine("nope")

    def test_build_unresolvable_custom_raises(self, store):
        store.add("mine", module_path="missing_mod_xyz", class_name="X")
        with pytest.raises(EngineNotFoundError, match="无法解析"):
            store.build_engine("mine")

    def test_build_injects_proxies(self, store):
        store.update("iqdb", proxy_mode="on")
        eng = store.build_engine("iqdb", proxies={"http": "http://p:1"})
        assert eng.proxies == {"http": "http://p:1"}

    def test_build_resolves_env_fallback_for_secrets(self, store):
        """api_key 留空时回退到 .env（Field.env_var）"""
        import imgsearch.secrets as secrets
        secrets.set("SAUCENAO_KEY", "from-env")
        store.update("sauceNAO", api_key="")
        eng = store.build_engine("sauceNAO")
        assert eng.api_key == "from-env"


class TestEngineConfigCompat:
    def test_attribute_access_reads_settings(self):
        """旧代码里的 ec.api_key / ec.timeout 必须继续可用"""
        ec = EngineConfig(name="x", settings={"api_key": "k", "timeout": 60})
        assert ec.api_key == "k"
        assert ec.timeout == 60

    def test_unknown_attribute_raises(self):
        ec = EngineConfig(name="x")
        with pytest.raises(AttributeError):
            ec.no_such_field

    def test_to_dict_round_trip(self):
        ec = EngineConfig(name="x", enabled=False, priority=3,
                          module_path="m", class_name="C",
                          settings={"timeout": 12})
        again = EngineConfig.from_dict(ec.to_dict())
        assert again == ec

    def test_from_dict_migrates_flat_format(self):
        ec = EngineConfig.from_dict({
            "name": "x", "enabled": True, "priority": 1,
            "timeout": 45, "api_url": "https://a.example",
        })
        assert ec.get("timeout") == 45
        assert ec.get("api_url") == "https://a.example"

    def test_display_name_uses_class(self):
        assert EngineConfig(name="sauceNAO").display_name.startswith("SauceNAO")
        assert EngineConfig(name="mine").display_name == "mine"
