"""
引擎类注册表与解析

修复的两类缺陷：

1. **缓存键错误**（旧实现以「引擎名」为键）
   改了 ``module_path`` / ``class_name`` 之后，旧类仍被缓存命中，
   表现为「配置改了不生效，重启才好」。
   现在动态引擎一律以 ``(module_path, class_name)`` 为键 —— 键随配置走。

2. **名称大小写口径不一致**
   旧实现 ``is_builtin()`` 做小写归一，``_ensure_builtin_defaults()`` 不做，
   于是配置里的 ``"Danbooru"`` 永远拿不到内置默认值。
   现在所有名称比较统一走 :func:`_norm`。

另外：内置引擎采用**自动发现** —— 往 ``imgsearch/engines/`` 放一个模块、
在其中定义一个带 ``NAME`` 的 SearchEngine 子类，就会被自动注册。
"""

import importlib
import pkgutil
import sys
from typing import Dict, List, Optional, Tuple, Type

from imgsearch.engines.schema import COMMON_SCHEMA, Schema

# 内置引擎：注册名 → 类
_REGISTRY: Dict[str, Type] = {}
# 动态加载缓存：(module_path, class_name) → 类
_DYNAMIC_CACHE: Dict[Tuple[str, str], Type] = {}

# 包内非引擎模块，自动发现时跳过
_SKIP_MODULES = {
    "base", "schema", "registry", "store", "presets",
    "config", "__init__", "__main__",
    # 实验分支 experiment/declarative-only：
    # 下面这些已改由 adapters/presets.py 的配置预设提供，
    # 模块保留仅作对照/回滚，不再自动注册成内置引擎。
    "danbooru",
    "tracemoe",
}

_builtins_loaded = False


def _norm(name: str) -> str:
    """名称比较统一走这里，避免大小写不一致导致的分支错乱"""
    return (name or "").strip().lower()


# ── 注册 ────────────────────────────────────────────────────


def register_engine_class(name: str, cls: Type) -> None:
    """注册一个引擎类（内置引擎由自动发现调用）"""
    if name:
        _REGISTRY[name] = cls


def ensure_builtins_loaded() -> None:
    """
    导入并注册全部内置引擎（幂等）。

    任何会用到引擎解析的入口都会先走到这里，因此调用方不需要
    记得手动 ``register_engine_class``（旧实现就是这么漏掉的）。

    采用自动发现：新增引擎 = 往 engines/ 放一个文件，无需改动本文件。
    """
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True

    import imgsearch.engines as pkg
    from imgsearch.engines.base import SearchEngine

    for info in pkgutil.iter_modules(pkg.__path__):
        name = info.name
        if name.startswith("_") or name in _SKIP_MODULES:
            continue
        try:
            module = importlib.import_module(f"{pkg.__name__}.{name}")
        except Exception as e:  # 单个引擎坏了不该拖垮整个工具
            print(f"  ⚠️ 内置引擎模块 {name} 加载失败：{e}")
            continue
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, SearchEngine)
                    and obj is not SearchEngine and getattr(obj, "NAME", "")):
                register_engine_class(obj.NAME, obj)


# ── 查询 ────────────────────────────────────────────────────


def registered_names() -> List[str]:
    """已注册的引擎名（保持注册顺序）"""
    ensure_builtins_loaded()
    return list(_REGISTRY.keys())


def ordered_builtin_names() -> List[str]:
    """
    按各引擎声明的 ``DEFAULT_ORDER`` 排序的引擎名。

    出厂默认顺序用它，而不是用模块发现顺序（那只是字母序，
    排出来的搜索顺序没有道理 —— 例如 Danbooru 会排在 SauceNAO 前面）。
    """
    ensure_builtins_loaded()
    return sorted(
        _REGISTRY.keys(),
        key=lambda n: (getattr(_REGISTRY[n], "DEFAULT_ORDER", 100), n),
    )


def find_builtin(name: str) -> Optional[Type]:
    """按名称取内置引擎类（大小写不敏感）"""
    ensure_builtins_loaded()
    if name in _REGISTRY:
        return _REGISTRY[name]
    target = _norm(name)
    for reg_name, cls in _REGISTRY.items():
        if _norm(reg_name) == target:
            return cls
    return None


def is_builtin(name: str) -> bool:
    """是否为内置引擎（大小写不敏感）"""
    return find_builtin(name) is not None


def canonical_name(name: str) -> str:
    """
    把配置里写的引擎名归一为注册名。

    例如配置写 ``"Danbooru"``、注册名是 ``"danbooru"`` → 返回 ``"danbooru"``。
    非内置引擎原样返回。
    """
    cls = find_builtin(name)
    if cls is None:
        # 配置预设（如 danbooru）不再注册成类，但名字归一化仍要工作 ——
        # 老配置里可能写着 "Danbooru"
        try:
            from imgsearch.engines.adapters.presets import by_name
            preset = by_name(name)
            if preset is not None:
                return preset.name
        except Exception:                                 # noqa: BLE001
            pass
        return name
    for reg_name, reg_cls in _REGISTRY.items():
        if reg_cls is cls:
            return reg_name
    return name


# ── Schema ──────────────────────────────────────────────────


def schema_for_class(cls: Optional[Type]) -> Schema:
    """取引擎类的配置 schema（没有则退回通用 schema）"""
    if cls is None:
        return COMMON_SCHEMA
    return getattr(cls, "CONFIG_SCHEMA", None) or COMMON_SCHEMA


def schema_for(ec) -> Schema:
    """
    取某个引擎配置对应的 schema。

    自定义引擎若无法解析（模块缺失等），则按它已存的设置**临时拼一个 schema**，
    这样界面仍能显示与编辑已有字段，而不是空白。
    """
    cls = resolve_engine_class(ec)
    if cls is not None:
        return schema_for_class(cls)

    settings = getattr(ec, "settings", {}) or {}
    extra = tuple(
        COMMON_SCHEMA.get(k) or _infer_field(k, v)
        for k, v in settings.items()
    )
    return COMMON_SCHEMA.extend(Schema(*extra))


def _infer_field(key: str, value):
    """为未知字段推断一个宽松的声明，保证界面能编辑它"""
    from imgsearch.engines.schema import BOOL, FLOAT, INT, KV, Field

    if isinstance(value, bool):
        return Field(key, key, BOOL, value)
    if isinstance(value, int):
        return Field(key, key, INT, value)
    if isinstance(value, float):
        return Field(key, key, FLOAT, value)
    if isinstance(value, dict):
        return Field(key, key, KV, value)
    return Field(key, key, "str", value if value is not None else "")


# ── 解析 ────────────────────────────────────────────────────


def resolve_engine_class(ec) -> Optional[Type]:
    """
    解析 EngineConfig 对应的引擎类。

    顺序：
      1. 配了 ``module_path`` + ``class_name`` → 动态导入
         （以 ``(module_path, class_name)`` 为缓存键）
      2. 否则查内置注册表（大小写不敏感）
    """
    ensure_builtins_loaded()

    module_path = (getattr(ec, "module_path", "") or "").strip()
    class_name = (getattr(ec, "class_name", "") or "").strip()
    engine_name = getattr(ec, "name", "") or ""

    if module_path and class_name:
        key = (module_path, class_name)
        cached = _DYNAMIC_CACHE.get(key)
        if cached is not None:
            return cached

        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            print(f"  ⚠️ 加载自定义引擎 '{engine_name}' 失败：找不到模块 '{module_path}'")
            print("    └─ 请确认模块文件存在，且位于 Python 可导入的路径下")
            print(f"    └─ 详细错误: {e}")
            return None
        except Exception as e:
            # 模块本身能定位、但导入过程中抛错（语法错误 / 缺依赖）。
            # 必须与「找不到模块」区分开，否则会把人误导到错的方向。
            print(f"  ⚠️ 自定义引擎 '{engine_name}' 的模块 '{module_path}' 导入时出错：")
            print(f"    └─ {type(e).__name__}: {e}")
            return None

        cls = getattr(module, class_name, None)
        if cls is None:
            print(f"  ⚠️ 加载自定义引擎 '{engine_name}' 失败：模块中没有类 '{class_name}'")
            print("    └─ 该类必须继承 SearchEngine 并实现 search() 方法")
            return None

        _DYNAMIC_CACHE[key] = cls
        return cls

    return find_builtin(engine_name)


def invalidate_engine_cache() -> None:
    """
    清空动态引擎缓存，并把相关模块从 ``sys.modules`` 移除。

    保存配置后调用：这样即便只是改了自定义引擎**文件内容**
    （module_path / class_name 没变，缓存键不变），重新搜索时
    也会真正重新导入，而不是继续用旧的类对象。
    """
    for module_path, _cls_name in list(_DYNAMIC_CACHE.keys()):
        sys.modules.pop(module_path, None)
    _DYNAMIC_CACHE.clear()


# ── 测试辅助 ────────────────────────────────────────────────


def _reset_registry_for_tests() -> None:
    """清空注册表与缓存（仅供测试使用）"""
    global _builtins_loaded
    _REGISTRY.clear()
    _DYNAMIC_CACHE.clear()
    _builtins_loaded = False
