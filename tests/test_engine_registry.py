"""
引擎类注册表测试

重点覆盖两个曾经的缺陷：
  - 动态缓存以「引擎名」为键 → 改了 module_path/class_name 不生效
  - 名称大小写口径不一致 → "Danbooru" 拿不到内置默认值
"""

import pytest

from imgsearch.engines.registry import (
    canonical_name,
    ensure_builtins_loaded,
    find_builtin,
    invalidate_engine_cache,
    is_builtin,
    ordered_builtin_names,
    registered_names,
    resolve_engine_class,
    schema_for_class,
)
from imgsearch.engines.store import EngineConfig


class TestBuiltinDiscovery:
    def test_builtins_are_registered(self):
        ensure_builtins_loaded()
        names = registered_names()
        # danbooru 已改由配置预设提供（见 adapters/presets.py），
        # 不再是注册表里的类 —— 其余四个仍是
        # 所有站点专属引擎都已改成配置预设；注册表里只剩两个通用适配器
        for expected in ("genericJson", "genericHtml"):
            assert expected in names, expected
        # danbooru / traceMoe 已由配置预设提供，不再是注册表里的类
        for moved in ("danbooru", "traceMoe"):
            assert moved not in names, f"{moved} 现在是配置预设，不该再注册成类"

    def test_danbooru_is_provided_by_preset(self):
        """配置预设接管后，它依然是一个可用的引擎（只是由适配器承载）"""
        from imgsearch.engines.adapters.presets import by_name
        from imgsearch.engines.store import EngineStore

        preset = by_name("danbooru")
        assert preset is not None
        assert preset.class_name == "GenericJson"
        ec = EngineStore().get("danbooru")
        assert ec is not None
        assert ec.class_name == "GenericJson"

    def test_ordered_names_follow_declared_order(self):
        """默认顺序取自各引擎的 DEFAULT_ORDER，而不是模块字母序"""
        order = ordered_builtin_names()
        assert order.index("genericJson") < order.index("genericHtml")


class TestNameNormalization:
    @pytest.mark.parametrize("name", ["genericJson", "GenericJson",
                                      "GENERICJSON", "genericjson"])
    def test_is_builtin_is_case_insensitive(self, name):
        assert is_builtin(name) is True

    @pytest.mark.parametrize("name", ["genericJson", "GenericJson", "GENERICJSON"])
    def test_find_builtin_is_case_insensitive(self, name):
        assert find_builtin(name).NAME == "genericJson"

    def test_canonical_name_normalizes_builtin(self):
        """配置里写 "GenericJson" 应归一为注册名 "genericJson" """
        assert canonical_name("GenericJson") == "genericJson"
        assert canonical_name("GENERICJSON") == "genericJson"

    def test_canonical_name_normalizes_preset(self):
        """配置预设也参与归一化：老配置里写 "SauceNAO" 仍应认得出"""
        assert canonical_name("SauceNAO") == "sauceNAO"
        assert canonical_name("SAUCENAO") == "sauceNAO"

    def test_canonical_name_leaves_custom_alone(self):
        assert canonical_name("MyOwnEngine") == "MyOwnEngine"

    def test_unknown_is_not_builtin(self):
        assert is_builtin("nope") is False
        assert find_builtin("nope") is None


class TestResolve:
    def test_resolve_builtin(self):
        ec = EngineConfig(name="GENERICJSON")
        assert resolve_engine_class(ec).NAME == "genericJson"

    def test_resolve_builtin_case_insensitive(self):
        ec = EngineConfig(name="GENERICJSON")
        assert resolve_engine_class(ec).NAME == "genericJson"

    def test_resolve_preset_engine(self):
        """配置预设靠 module_path/class_name 解析，与名称无关"""
        ec = EngineConfig(name="whatever",
                          module_path="imgsearch.engines.adapters.generic_json",
                          class_name="GenericJson")
        assert resolve_engine_class(ec).NAME == "genericJson"

    def test_resolve_unknown_returns_none(self):
        assert resolve_engine_class(EngineConfig(name="nope")) is None

    def test_resolve_missing_module_returns_none(self):
        ec = EngineConfig(name="mine", module_path="definitely_missing_xyz",
                          class_name="Whatever")
        assert resolve_engine_class(ec) is None

    def test_resolve_missing_class_returns_none(self, tmp_path, monkeypatch):
        (tmp_path / "ok_mod.py").write_text("class SomethingElse: pass\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        ec = EngineConfig(name="mine", module_path="ok_mod", class_name="NotThere")
        assert resolve_engine_class(ec) is None

    def test_resolve_module_with_import_error_returns_none(self, tmp_path, monkeypatch):
        """模块能定位但导入就抛错 → 也是 None，且不应把异常漏出去"""
        (tmp_path / "broken_mod.py").write_text(
            "raise RuntimeError('boom')\n", encoding="utf-8"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        ec = EngineConfig(name="mine", module_path="broken_mod", class_name="X")
        assert resolve_engine_class(ec) is None


class TestDynamicCacheKeying:
    """
    缺陷 #1 回归：旧实现以引擎名为键，
    于是「同一个引擎改了 module_path」仍然命中旧类。
    """

    def _make(self, tmp_path, monkeypatch):
        (tmp_path / "fa.py").write_text(
            "class EngineA:\n    NAME = 'a'\n", encoding="utf-8")
        (tmp_path / "fb.py").write_text(
            "class EngineB:\n    NAME = 'b'\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))

    def test_changing_module_path_takes_effect_immediately(self, tmp_path, monkeypatch):
        self._make(tmp_path, monkeypatch)
        ec = EngineConfig(name="mine", module_path="fa", class_name="EngineA")
        assert resolve_engine_class(ec).__name__ == "EngineA"

        # 同一个 EngineConfig、同一个引擎名，只改模块绑定
        ec.module_path = "fb"
        ec.class_name = "EngineB"
        assert resolve_engine_class(ec).__name__ == "EngineB", \
            "改了 module_path 却仍返回旧类 → 缓存键错了"

    def test_same_name_different_module_do_not_collide(self, tmp_path, monkeypatch):
        self._make(tmp_path, monkeypatch)
        a = EngineConfig(name="mine", module_path="fa", class_name="EngineA")
        b = EngineConfig(name="mine", module_path="fb", class_name="EngineB")
        assert resolve_engine_class(a).__name__ == "EngineA"
        assert resolve_engine_class(b).__name__ == "EngineB"

    def test_invalidate_drops_cached_module(self, tmp_path, monkeypatch):
        """改了引擎文件内容（路径没变）时，失效缓存后应重新导入"""
        mod = tmp_path / "fc.py"
        mod.write_text("class E:\n    VERSION = 1\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))

        ec = EngineConfig(name="mine", module_path="fc", class_name="E")
        assert resolve_engine_class(ec).VERSION == 1

        # ⚠️ 第二版必须与第一版字节数不同：CPython 用 (mtime, size)
        # 判断 .pyc 是否过期，同一秒内写入且长度相同的改动会被当成「没改」
        mod.write_text("class E:\n    VERSION = 2  # 第二版\n", encoding="utf-8")
        invalidate_engine_cache()
        assert resolve_engine_class(ec).VERSION == 2


class TestSchemaLookup:
    def test_schema_for_class(self):
        cls = find_builtin("genericJson")
        schema = schema_for_class(cls)
        # 适配器自带运行时字段（限流、反爬、字段映射…）
        for key in ("long_limit", "cloudflare_bypass", "results_path",
                    "field_artist"):
            assert key in schema, key
        # 而通用 schema 本身不含这些站点专属字段
        from imgsearch.engines.schema import COMMON_SCHEMA
        assert "results_path" not in COMMON_SCHEMA

    def test_schema_for_class_none_falls_back_to_common(self):
        from imgsearch.engines.schema import COMMON_SCHEMA
        assert schema_for_class(None) is COMMON_SCHEMA

    def test_each_engine_declares_only_what_it_uses(self):
        """schema 驱动：引擎不该带上自己用不到的字段"""
        assert "long_limit" not in schema_for_class(find_builtin("ascii2d"))
        assert "results_path" in schema_for_class(find_builtin("genericJson"))
        # danbooru 现在是适配器配置：它的 schema 来自配置而不是类
        from imgsearch.engines.store import EngineStore
        danbooru_schema = EngineStore().get("danbooru").schema()
        assert "login" in {f.key for f in danbooru_schema}
        assert "tag_string" not in {f.key for f in danbooru_schema}
        assert "results_path" in schema_for_class(find_builtin("genericJson"))
        # traceMoe 现在是适配器配置，它的 schema 来自配置
        from imgsearch.engines.store import EngineStore
        assert "cut_borders" not in {f.key for f in EngineStore().get("traceMoe").schema()}
