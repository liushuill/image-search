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
        # 顺序由 DEFAULT_ORDER 决定；两个声明式适配器排在最后（90/91）
        assert store.names() == ["sauceNAO", "iqdb", "ascii2d", "traceMoe",
                                 "danbooru", "genericJson", "genericHtml"]

    def test_engines_that_need_credentials_are_off_by_default(self, store):
        assert store.get("sauceNAO").enabled is True
        assert store.get("iqdb").enabled is True
        # 需要账号 → 默认关闭，避免开箱即报错
        assert store.get("danbooru").enabled is False
        # 实测已不可用 / 只适合动画截图 → 默认关闭
        assert store.get("ascii2d").enabled is False
        assert store.get("traceMoe").enabled is False

    def test_priorities_are_sequential(self, store):
        # 权重从 1 连续排下来；引擎增减时这里跟着变是正常的，
        # 重点是不能有空洞或重复
        priorities = [e.priority for e in store.list_all()]
        assert priorities == list(range(1, len(priorities) + 1))

    def test_settings_filled_from_schema(self, store):
        ec = store.get("sauceNAO")
        # 通用字段 + 适配器的运行时字段都在
        for key in ("api_url", "api_key", "min_similarity", "proxy_mode",
                    "request_delay", "timeout", "long_limit", "short_limit"):
            assert key in ec.settings, key
        # SauceNAO 专属参数（db / numres / output_type）现在走「自定义查询参数」
        assert ec.settings["params"]["db"] == 999
        assert ec.settings["params"]["numres"] == 5


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
        assert ec.get("timeout") == 45
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
        # 顺序由 DEFAULT_ORDER 决定；两个声明式适配器排在最后（90/91）
        assert store.names() == ["sauceNAO", "iqdb", "ascii2d", "traceMoe",
                                 "danbooru", "genericJson", "genericHtml"]

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
        store.update("sauceNAO", long_limit=0, long_window=0,
                     short_limit=0, short_window=0, api_key="k")
        eng = store.build_engine("sauceNAO")
        # 「0 = 不限制」通过公开接口验证：不建配额对象、不做节流。
        # （适配器没有 _long_limit / _quota.unlimited 这类内部属性）
        assert eng.quota_state() == []
        assert eng.request_interval() == 0.0


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


class TestSchemaVersionMigration:
    """
    回归：改字段默认值对「已落盘的配置」无效。

    `_apply_schema_defaults` 只在键不存在时补默认值（否则会把用户故意设的
    0/False 顶掉），代价是先落盘的旧默认值永远留着。所以默认值变更要靠
    版本号显式重刷一次。
    """

    def _legacy(self, write_config, **overrides):
        settings = {"min_similarity": 0, "proxy_mode": "on"}
        settings.update(overrides)
        write_config({"search_engines": [
            {"name": "iqdb", "enabled": True, "priority": 1, "settings": dict(settings)},
            {"name": "traceMoe", "enabled": True, "priority": 2, "settings": dict(settings)},
            {"name": "sauceNAO", "enabled": True, "priority": 3, "settings": dict(settings)},
        ]})

    def test_stale_defaults_are_refreshed(self, write_config):
        self._legacy(write_config)
        s = EngineStore()
        # 各引擎实测校准过的默认值应生效
        assert s.get("iqdb").get("min_similarity") == 65
        assert s.get("traceMoe").get("min_similarity") == 85
        assert s.get("sauceNAO").get("min_similarity") == 60
        assert s.get("iqdb").get("proxy_mode") == "auto"

    def test_version_is_stamped(self, write_config):
        from imgsearch.engines.store import _SCHEMA_VERSION, _VERSION_KEY
        import imgsearch.config as cfg
        self._legacy(write_config)
        EngineStore()
        assert cfg.load_config().get(_VERSION_KEY) == _SCHEMA_VERSION

    def test_migration_runs_only_once(self, write_config):
        """迁移后用户自己设的值不能被下一次加载重置"""
        self._legacy(write_config)
        s = EngineStore()
        s.update("iqdb", min_similarity=33)
        s.update("sauceNAO", proxy_mode="off")

        again = EngineStore()
        assert again.get("iqdb").get("min_similarity") == 33, "迁移重复执行，覆盖了用户设置"
        assert again.get("sauceNAO").get("proxy_mode") == "off"

    def test_custom_engines_are_untouched(self, write_config):
        """自定义引擎的字段可能是它自己的扩展，迁移不能乱动"""
        write_config({"search_engines": [
            {"name": "mine", "enabled": True, "priority": 1,
             "module_path": "m", "class_name": "C",
             "settings": {"min_similarity": 7}},
        ]})
        s = EngineStore()
        assert s.get("mine").get("min_similarity") == 7

    def test_fresh_install_gets_calibrated_defaults(self, store):
        # 阈值按真实图库实测校准：真实命中在 87–97%，噪声在 45% 以下
        assert store.get("iqdb").get("min_similarity") == 65
        assert store.get("traceMoe").get("min_similarity") == 85
        assert store.get("sauceNAO").get("min_similarity") == 60


class TestSecretsNeverTouchConfig:
    """
    回归：凭据曾经能被写进 config.json —— 而那个文件是**入库**的，
    等于把密钥写回版本历史（正是 P1 阶段刚清理掉的问题）。

    更隐蔽的后果：引擎级的值优先于 .env，于是
    「凭据页显示的值」和「实际生效的值」可能不是同一个。
    """

    def test_update_routes_secret_to_env(self, store):
        from imgsearch import secrets
        store.update("sauceNAO", api_key="SECRET-VALUE")
        # 配置里只留空占位
        assert store.get("sauceNAO").get("api_key") == ""
        # 值进了 .env
        assert secrets.get("SAUCENAO_KEY") == "SECRET-VALUE"

    def test_secret_never_appears_in_config_file(self, store):
        import imgsearch.config as cfg
        store.update("sauceNAO", api_key="SECRET-VALUE")
        assert "SECRET-VALUE" not in cfg._CONFIG_FILE.read_text(encoding="utf-8")

    def test_secret_still_reaches_the_engine(self, store):
        store.update("sauceNAO", api_key="SECRET-VALUE")
        assert store.build_engine("sauceNAO").api_key == "SECRET-VALUE"

    def test_secret_is_stripped(self, store):
        """粘贴时常带上换行/空格；带空白跑起来会认证失败"""
        from imgsearch import secrets
        store.update("sauceNAO", api_key="  KEY-WITH-WHITESPACE\n")
        assert secrets.get("SAUCENAO_KEY") == "KEY-WITH-WHITESPACE"

    def test_empty_value_does_not_wipe_env(self, store):
        """清空配置字段不该把 .env 里的凭据一起抹掉"""
        from imgsearch import secrets
        store.update("sauceNAO", api_key="KEEP-ME")
        store.update("sauceNAO", api_key="")
        assert secrets.get("SAUCENAO_KEY") == "KEEP-ME"

    def test_save_blanks_any_smuggled_value(self, write_config):
        """兜底：哪怕有值被直接塞进 settings，落盘前也会被清空"""
        import imgsearch.config as cfg
        write_config({
            "search_engines": [{"name": "sauceNAO", "enabled": True, "priority": 1,
                                "settings": {"api_key": "SMUGGLED"}}],
            "search_engines_version": 5,
        })
        EngineStore().save()
        assert "SMUGGLED" not in cfg._CONFIG_FILE.read_text(encoding="utf-8")

    def test_legacy_secret_in_config_is_migrated_to_env(self, write_config):
        """v4 迁移：把已经写进 config.json 的凭据搬到 .env"""
        import imgsearch.config as cfg
        from imgsearch import secrets
        write_config({
            "search_engines": [{"name": "sauceNAO", "enabled": True, "priority": 1,
                                "settings": {"api_key": "LEGACY-KEY"}}],
            "search_engines_version": 3,
        })
        s = EngineStore()
        assert secrets.get("SAUCENAO_KEY") == "LEGACY-KEY"
        assert s.get("sauceNAO").get("api_key") == ""
        assert "LEGACY-KEY" not in cfg._CONFIG_FILE.read_text(encoding="utf-8")

    def test_migration_strips_whitespace(self, write_config):
        from imgsearch import secrets
        write_config({
            "search_engines": [{"name": "sauceNAO", "enabled": True, "priority": 1,
                                "settings": {"api_key": "PADDED-KEY\n"}}],
            "search_engines_version": 3,
        })
        EngineStore()
        assert secrets.get("SAUCENAO_KEY") == "PADDED-KEY"


class TestSecretEnvNameReconciliation:
    """
    回归：v4 迁移曾经把凭据搬到派生名 IMGSEARCH_<引擎>_<字段> 上，
    而引擎代码读的是 SAUCENAO_KEY / DANBOORU_API_KEY ——
    结果「搬过去了却读不到」，症状是配了 key 仍报未配置。
    """

    def _seed(self, write_config, version=4):
        write_config({
            "search_engines": [{"name": "sauceNAO", "enabled": True, "priority": 1,
                                "settings": {}}],
            "search_engines_version": version,
        })

    def test_derived_name_is_moved_to_declared(self, write_config):
        from imgsearch import secrets
        secrets.set("IMGSEARCH_SAUCENAO_API_KEY", "WRONG-PLACE")
        self._seed(write_config)

        EngineStore()

        assert secrets.get("SAUCENAO_KEY") == "WRONG-PLACE"
        assert not secrets.load().get("IMGSEARCH_SAUCENAO_API_KEY"), \
            "派生名上的残留没清掉"

    def test_conflict_prefers_derived_name(self, write_config):
        """
        冲突时以派生名为准：它来自 v4 迁移，源头是当时**实际生效**的
        引擎级设置；正确名上那个旧值正是被盖住的那个。
        """
        from imgsearch import secrets
        secrets.set("SAUCENAO_KEY", "OLD-INEFFECTIVE")
        secrets.set("IMGSEARCH_SAUCENAO_API_KEY", "EFFECTIVE")
        self._seed(write_config)

        EngineStore()

        assert secrets.get("SAUCENAO_KEY") == "EFFECTIVE"

    def test_no_legacy_value_leaves_env_alone(self, write_config):
        from imgsearch import secrets
        secrets.set("SAUCENAO_KEY", "UNTOUCHED")
        self._seed(write_config)

        EngineStore()

        assert secrets.get("SAUCENAO_KEY") == "UNTOUCHED"

    def test_engine_reads_the_key_after_reconciliation(self, write_config):
        """最终目的：引擎真的能拿到它"""
        from imgsearch import secrets
        secrets.set("IMGSEARCH_SAUCENAO_API_KEY", "FIXED-KEY")
        self._seed(write_config)

        store = EngineStore()

        assert store.build_engine("sauceNAO").api_key == "FIXED-KEY"


class TestResultFieldNormalization:
    """
    回归：SauceNAO 在不同索引下会把 creator / material 返回成**列表**
    （如 ``["aldehyde"]``）。不归一的话写进 SQLite 会抛
    "type 'list' is not supported"，导致**整条图库入库失败**。
    """

    def test_list_fields_are_normalized(self):
        from imgsearch.engines.base import SearchResult
        r = SearchResult(source="sauceNAO", similarity=93.3,
                         artist=["aldehyde"],
                         material=["dance dance revolution", "maimai (game)"],
                         title=["t"], ext_urls="https://x", extra_ids={"anilist": 42})
        assert r.artist == "aldehyde"
        assert r.material == "dance dance revolution, maimai (game)"
        assert r.ext_urls == ["https://x"]        # 单个字符串 → 列表
        assert r.extra_ids == {"anilist": "42"}   # 值统一成字符串

    def test_empty_list_becomes_none(self):
        from imgsearch.engines.base import SearchResult
        assert SearchResult(source="x", similarity=1, artist=[]).artist is None
        assert SearchResult(source="x", similarity=1, artist="   ").artist is None

    def test_page_and_similarity_coerced(self):
        from imgsearch.engines.base import SearchResult
        r = SearchResult(source="x", similarity="88.5", pixiv_page="2")
        assert r.similarity == 88.5 and r.pixiv_page == 2
        bad = SearchResult(source="x", similarity="oops", pixiv_page="oops")
        assert bad.similarity == 0.0 and bad.pixiv_page == 0

    def test_engine_with_list_field_can_be_recorded(self, library, pattern_image):
        """端到端：字段是列表时入库必须成功"""
        from imgsearch.engines.base import SearchResult
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=1234)))
        store.save_results(rec.id, [SearchResult(
            source="sauceNAO", similarity=93.3, artist=["aldehyde"],
            material=["tag one", "tag two"], ext_urls=["https://x"],
            extra_ids={"anilist": 42},
        )])
        loaded = store.load_results(rec.id)
        assert len(loaded) == 1
        assert loaded[0].artist == "aldehyde"
        assert loaded[0].material == "tag one, tag two"

    def test_save_results_survives_smuggled_container(self, library, pattern_image):
        """兜底：即使有人绕过 __post_init__ 塞了容器，也不该整条失败"""
        from imgsearch.engines.base import SearchResult
        db, store = library
        rec = store.upsert_image(str(pattern_image("b.png", seed=1235)))
        r = SearchResult(source="x", similarity=1)
        r.artist = {"weird": "dict"}          # 手动破坏
        store.save_results(rec.id, [r])
        assert len(store.load_results(rec.id)) == 1
