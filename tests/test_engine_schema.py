"""
Schema 层测试：字段声明、类型转换、校验

这里覆盖了旧实现最典型的一类错误：值在界面与配置之间来回转换时被改坏，
其中最关键的是 **0 被当成空值**。
"""

import pytest

from imgsearch.engines.schema import (
    BOOL, COMMON_SCHEMA, FLOAT, INT, KV, RATE_LIMIT_SCHEMA, SECRET, STR,
    ConfigError, Field, Schema, check_cross_fields, coerce, validate,
)


class TestCoerce:
    def test_str(self):
        assert coerce(Field("k", "K", STR, ""), 123) == "123"

    def test_int_from_string(self):
        assert coerce(Field("k", "K", INT, 0), " 42 ") == 42

    def test_int_invalid_raises(self):
        with pytest.raises(ConfigError, match="必须是整数"):
            coerce(Field("k", "数量", INT, 0), "abc")

    def test_float_from_string(self):
        assert coerce(Field("k", "K", FLOAT, 0.0), "3.5") == 3.5

    def test_empty_falls_back_to_default(self):
        assert coerce(Field("k", "K", INT, 7), "") == 7
        assert coerce(Field("k", "K", INT, 7), None) == 7
        assert coerce(Field("k", "K", STR, "d"), "") == "d"

    def test_zero_is_not_treated_as_empty(self):
        """核心回归：0 是合法取值，不能被默认值顶掉"""
        assert coerce(Field("k", "K", INT, 100), 0) == 0
        assert coerce(Field("k", "K", INT, 100), "0") == 0
        assert coerce(Field("k", "K", FLOAT, 8.0), 0) == 0.0

    def test_bool_matrix(self):
        f = Field("k", "K", BOOL, False)
        for raw in (True, "true", "True", "1", "yes", "on", "是", "启用"):
            assert coerce(f, raw) is True, raw
        for raw in (False, "false", "0", "no", "off", "否", ""):
            assert coerce(f, raw) is False, raw

    def test_kv_from_dict(self):
        f = Field("k", "K", KV, {})
        assert coerce(f, {"a": 1, "b": None}) == {"a": "1", "b": ""}

    def test_kv_from_text(self):
        f = Field("k", "K", KV, {})
        assert coerce(f, "a=1\nb = 2\n\n# 注释\n") == {"a": "1", "b": "2"}

    def test_kv_bad_line_raises(self):
        with pytest.raises(ConfigError, match="key=value"):
            coerce(Field("k", "K", KV, {}), "a=1\nbogus")


class TestValidate:
    def test_required_empty_raises(self):
        with pytest.raises(ConfigError, match="不能为空"):
            validate(Field("k", "用户名", STR, "", required=True), "")

    def test_required_secret_may_be_empty(self):
        """凭据可以留空（表示回退到 .env）"""
        validate(Field("k", "Key", SECRET, "", required=True), "")

    def test_minimum(self):
        f = Field("k", "限额", INT, 0, minimum=0)
        validate(f, 0)          # 边界值合法
        with pytest.raises(ConfigError, match="不能小于 0"):
            validate(f, -1)

    def test_maximum(self):
        f = Field("k", "相似度", INT, 0, maximum=100)
        validate(f, 100)
        with pytest.raises(ConfigError, match="不能大于 100"):
            validate(f, 101)

    def test_choices(self):
        f = Field("k", "代理", STR, "auto", choices=("auto", "on", "off"))
        validate(f, "on")
        with pytest.raises(ConfigError, match="只能是以下之一"):
            validate(f, "bogus")


class TestSchema:
    def test_defaults_are_coerced(self):
        s = Schema(Field("a", "A", INT, "5"), Field("b", "B", BOOL, True))
        assert s.defaults() == {"a": 5, "b": True}

    def test_extend_overrides_same_key(self):
        """同名字段后声明者覆盖先声明者（引擎据此覆写通用默认值）"""
        base = Schema(Field("x", "X", INT, 1))
        derived = base.extend(Schema(Field("x", "X", INT, 99)))
        assert derived.get("x").default == 99
        assert base.get("x").default == 1, "extend 不应改动原 schema"

    def test_extend_keeps_order_and_adds(self):
        base = Schema(Field("a", "A"), Field("b", "B"))
        derived = base.extend(Schema(Field("c", "C")))
        assert derived.keys() == ["a", "b", "c"]

    def test_coerce_all_fills_defaults(self):
        s = Schema(Field("a", "A", INT, 5), Field("b", "B", INT, 6))
        assert s.coerce_all({"a": "9"}) == {"a": 9, "b": 6}

    def test_coerce_all_keeps_unknown_keys(self):
        """自定义引擎的扩展字段必须原样保留"""
        s = Schema(Field("a", "A", INT, 5))
        out = s.coerce_all({"a": 1, "custom_thing": {"deep": [1, 2]}})
        assert out["custom_thing"] == {"deep": [1, 2]}

    def test_common_schema_has_expected_keys(self):
        keys = COMMON_SCHEMA.keys()
        for k in ("api_url", "min_similarity", "proxy_mode",
                  "request_delay", "timeout", "headers", "params"):
            assert k in keys, k

    def test_api_key_is_declared_per_engine_not_globally(self):
        """
        回归：api_key 刻意**不放在通用 schema 里**。

        曾经它挂在 COMMON_SCHEMA 上且没声明 env_var —— 于是
        env_var_for() 派生出一个 IMGSEARCH_<引擎>_<字段> 的名字，
        而引擎代码读的是 SAUCENAO_KEY 这种固定名，
        凭据「搬过去了却读不到」，表现为「配了 key 却仍说未配置」。
        """
        from imgsearch.engines.registry import find_builtin, schema_for_class
        from imgsearch.engines.store import EngineStore
        from imgsearch.service import _env_name_for

        assert "api_key" not in COMMON_SCHEMA

        # 需要凭据的**内置类**：必须声明 api_key，且 env_var 与引擎代码读的一致
        f = schema_for_class(find_builtin("sauceNAO")).get("api_key")
        assert f is not None and f.is_secret
        assert f.env_var == "SAUCENAO_KEY"

        # 需要凭据的**配置预设**（danbooru）：字段来自适配器 schema，
        # 变量名由预设指定，最终必须落到 DANBOORU_API_KEY
        store = EngineStore()
        ec = store.get("danbooru")
        f = ec.schema().get("api_key")
        assert f is not None and f.is_secret
        assert _env_name_for(ec, f) == "DANBOORU_API_KEY"

        # 不需要凭据的引擎：不该挂着无用的 api_key 字段
        for name in ("iqdb", "traceMoe", "ascii2d"):
            assert schema_for_class(find_builtin(name)).get("api_key") is None, name

    def test_env_var_for_falls_back_to_derived_name(self):
        """没声明 env_var 的自定义引擎字段也要有一个稳定落点"""
        from imgsearch.engines.schema import env_var_for
        f = Field("api_key", "Key", SECRET, "")
        assert env_var_for("my engine", f) == "IMGSEARCH_MY_ENGINE_API_KEY"
        assert env_var_for("x", Field("api_key", "K", SECRET, "", env_var="FOO")) == "FOO"

    def test_proxy_mode_is_enum(self):
        assert COMMON_SCHEMA.get("proxy_mode").choices == ("auto", "on", "off")


class TestCrossFields:
    def test_limit_without_window_is_rejected(self):
        """限额 > 0 但窗口 = 0 → 次数只增不减，永远不释放"""
        s = COMMON_SCHEMA.extend(RATE_LIMIT_SCHEMA)
        with pytest.raises(ConfigError, match="长期窗口必须大于 0"):
            check_cross_fields(s, {"long_limit": 100, "long_window": 0})

    def test_unlimited_is_allowed(self):
        s = COMMON_SCHEMA.extend(RATE_LIMIT_SCHEMA)
        check_cross_fields(s, {"long_limit": 0, "long_window": 0})

    def test_skipped_when_schema_lacks_the_fields(self):
        """
        引擎没声明这两个字段时不该被误伤。

        回归：ascii2d 没有限流逻辑，但旧配置里残留了 long_limit=100 /
        long_window=0；若不加这道判断，用户连改 API 地址都会被拒绝。
        """
        check_cross_fields(COMMON_SCHEMA, {"long_limit": 100, "long_window": 0})
