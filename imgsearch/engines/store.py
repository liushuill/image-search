"""
引擎配置的存储层

``EngineStore`` 是引擎配置的**唯一数据源**。旧实现里每个窗口各 new 一个
``EngineManager``，各自持一份列表却共写同一份 config.json，
后写覆盖先写（lost update）——这正是「界面出错」的来源。
现在统一经 :func:`get_store` 取进程内唯一实例。

同时修复：
  - 改名走 remove+add → 会清空自定义引擎的 module_path/class_name（缺陷 #2）
  - 改名后被甩到搜索顺序最后（缺陷 #3）
  - 改名触发 3 次全量写盘，中途失败留下半改状态（缺陷 #4）
  - 内置引擎默认值因大小写不匹配而补不上（缺陷 #5）
  - ``0`` 被当成空值（"0 = 无限制"名不副实）（缺陷 #6）
"""

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from imgsearch import secrets
from imgsearch.config import get, save_configs
from imgsearch.engines import registry
from imgsearch.engines.registry import (
    canonical_name,
    invalidate_engine_cache,
    is_builtin as _registry_is_builtin,
    resolve_engine_class,
    schema_for,
)
from imgsearch.engines.schema import ConfigError, Schema, check_cross_fields

_CONFIG_KEY = "search_engines"
# 引擎配置的结构版本，用于「字段默认值变更后需要重刷」这类迁移
_VERSION_KEY = "search_engines_version"
_SCHEMA_VERSION = 3

# 结构性字段：不进 settings
_STRUCTURAL_KEYS = ("name", "enabled", "priority", "module_path", "class_name", "settings")

# 由 store 统一管理、不属于引擎参数的字段
_MANAGED_KEYS = ("enabled", "priority")


class EngineNotFoundError(LookupError):
    """找不到指定引擎（或它的类无法解析）"""


# ──────────────────────────────────────────────
#  引擎配置
# ──────────────────────────────────────────────


@dataclass
class EngineConfig:
    """
    单个搜索引擎的配置。

    - 结构性字段（name / enabled / priority / module_path / class_name）是显式属性
    - 引擎参数统一放在 ``settings`` 里，字段集合由该类声明的 CONFIG_SCHEMA 决定

    这样「加一个引擎」只写引擎文件即可，不需要回来改这个数据类。
    """

    name: str
    enabled: bool = True
    priority: int = 0
    module_path: str = ""
    class_name: str = ""
    settings: Dict[str, Any] = dc_field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:
        """
        让 ``ec.api_key`` / ``ec.timeout`` 这类旧写法继续可用。

        仅在常规属性查找失败时触发；下划线开头的名字直接抛 AttributeError，
        避免与 dataclass、copy、pickle 的内部协议互相干扰。
        """
        if item.startswith("_"):
            raise AttributeError(item)
        settings = self.__dict__.get("settings") or {}
        if item in settings:
            return settings[item]
        raise AttributeError(item)

    # ── 便捷访问 ──

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value

    @property
    def is_builtin(self) -> bool:
        return _registry_is_builtin(self.name)

    @property
    def display_name(self) -> str:
        cls = resolve_engine_class(self)
        if cls is not None:
            return getattr(cls, "DISPLAY_NAME", "") or self.name
        return self.name

    def schema(self) -> Schema:
        return schema_for(self)

    def to_engine_kwargs(self, proxies: Optional[dict] = None) -> Dict[str, Any]:
        """
        组装构造引擎实例所需的关键字参数。

        敏感/可回退字段在值为空时从 ``.env`` 补（Field.env_var）。
        """
        kwargs: Dict[str, Any] = {}
        for f in self.schema():
            if f.key in _MANAGED_KEYS:
                continue
            value = self.settings.get(f.key, f.default)
            if (value is None or value == "") and f.env_var:
                value = secrets.get(f.env_var, "") or ""
            kwargs[f.key] = value
        kwargs["proxies"] = proxies
        return kwargs

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": bool(self.enabled),
            "priority": int(self.priority),
            "module_path": self.module_path,
            "class_name": self.class_name,
            "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "EngineConfig":
        """
        反序列化，并兼容旧版**扁平**格式。

        旧格式把 api_url / api_key / timeout 等直接放在顶层；
        新格式收进 settings。这里把顶层剩余键整体并入 settings，
        所以旧配置无需手工迁移，且自定义引擎的未知字段也不会丢。
        """
        raw = dict(raw or {})
        name = raw.pop("name", "")
        enabled = raw.pop("enabled", True)
        priority = raw.pop("priority", 0)
        module_path = raw.pop("module_path", "")
        class_name = raw.pop("class_name", "")
        settings = raw.pop("settings", None)

        merged: Dict[str, Any] = dict(settings) if isinstance(settings, dict) else {}
        # 旧扁平格式的剩余键（也包含任何我们不认识的自定义字段）
        for k, v in raw.items():
            merged.setdefault(k, v)

        return cls(
            name=str(name or ""),
            enabled=bool(enabled),
            priority=int(priority or 0),
            module_path=str(module_path or ""),
            class_name=str(class_name or ""),
            settings=merged,
        )


# ──────────────────────────────────────────────
#  存储
# ──────────────────────────────────────────────


class EngineStore:
    """引擎配置的读写与增删改查"""

    def __init__(self, *, autoload: bool = True):
        self._engines: List[EngineConfig] = []
        self._loaded_mtime: Optional[int] = None
        # 上一次写盘的内容快照。mtime 粒度可能粗到毫秒，
        # 连续两次写盘会撞在同一刻度上，只靠 mtime 会漏判外部改动。
        self._last_saved = None
        if autoload:
            self.load()

    # ── 读 ───────────────────────────────────────

    def __len__(self) -> int:
        return len(self._engines)

    def __iter__(self):
        return iter(self.list_all())

    def list_all(self) -> List[EngineConfig]:
        """全部引擎，按 priority 升序"""
        return sorted(self._engines, key=lambda e: e.priority)

    def get_enabled(self) -> List[EngineConfig]:
        """启用的引擎，按 priority 升序"""
        return [e for e in self.list_all() if e.enabled]

    def get(self, name: str) -> Optional[EngineConfig]:
        """按名称查找（大小写不敏感）"""
        if not name:
            return None
        target = name.strip().lower()
        for e in self._engines:
            if e.name.strip().lower() == target:
                return e
        return None

    # 旧名，保留以便平滑迁移
    get_by_name = get

    def names(self) -> List[str]:
        return [e.name for e in self.list_all()]

    def is_builtin(self, name: str) -> bool:
        return _registry_is_builtin(name)

    # ── 加载 / 保存 ──────────────────────────────

    def load(self) -> None:
        """从 config.json 载入，必要时迁移旧格式并补全 schema 默认值"""
        raw = get(_CONFIG_KEY, None)
        stored_version = int(get(_VERSION_KEY, 0) or 0)
        self._engines = self._migrate(raw)
        migrated = self._migrate_schema_version(stored_version)
        self._loaded_mtime = self._current_mtime()

        # ⚠️ 这里必须用显式循环，不能写成 any(... for e in ...)：
        # any() 遇到第一个 True 就短路，排在后面的引擎就不会被补默认值了。
        changed = migrated
        for e in self._engines:
            if self._prune_stale_settings(e):
                changed = True
            if self._apply_schema_defaults(e):
                changed = True
        if changed:
            self.save()

    def _migrate_schema_version(self, stored_version: int) -> bool:
        """
        按版本号重刷那些「只补缺失键」覆盖不到的字段。

        ``_apply_schema_defaults`` 只在键**不存在**时补默认值（这样才不会
        把用户故意设的 0 / False 顶掉）。代价是：一旦某个字段先以旧默认值
        落盘，之后我们再调整默认值就对它无效了 —— 升级上来的配置会一直用旧的。

        所以字段默认值有变更时，在这里按版本号显式重刷一次。
        只处理内置引擎：自定义引擎的字段可能是它自己的扩展，不能乱动。

        v0 → v2：首次引入 min_similarity 与 proxy_mode。
        v2 → v3：用真实图库实测重新校准了 min_similarity（iqdb 45 → 65）。
        """
        if stored_version >= _SCHEMA_VERSION:
            return False

        for e in self._engines:
            if not e.is_builtin:
                continue
            if stored_version < 2:
                # 这两个字段是 v2 新增的，任何已存在的值都只是中间态默认值
                for key in ("min_similarity", "proxy_mode"):
                    e.settings.pop(key, None)
            elif stored_version < 3:
                # 阈值被重新校准过，让 schema 里的新默认值生效
                e.settings.pop("min_similarity", None)

        return True

    def _prune_stale_settings(self, ec: EngineConfig) -> bool:
        """
        丢弃**内置**引擎里已不属于其 schema 的旧字段。

        例：旧版给 ascii2d 存了 long_limit / long_window，而 ascii2d
        根本没有限流逻辑。留着只会在界面上造成困惑，还会误伤跨字段校验。

        自定义引擎一律保留 —— 那些键可能是它自己的扩展字段，我们无从判断。
        """
        if not ec.is_builtin:
            return False
        schema_keys = set(ec.schema().keys())
        stale = [k for k in ec.settings if k not in schema_keys]
        for k in stale:
            del ec.settings[k]
        return bool(stale)

    def _migrate(self, raw: Any) -> List[EngineConfig]:
        """把各种历史格式归一成 List[EngineConfig]"""
        # 1) 首次运行（键不存在）
        if raw is None:
            engines = self._defaults()
            self._engines = engines
            self.save()
            return engines

        # 2) 空前 或 旧版字符串列表 ["sauceNAO", "ascii2d"]
        if isinstance(raw, list) and raw and isinstance(raw[0], str):
            engines = []
            for i, name in enumerate(raw):
                ec = EngineConfig(name=name, enabled=True, priority=i + 1)
                self._apply_schema_defaults(ec)
                engines.append(ec)
            engines = self._append_missing_builtins(engines)
            self._engines = engines
            self.save()
            return engines

        # 3) 空列表 → 出厂默认
        if isinstance(raw, list) and not raw:
            engines = self._defaults()
            self._engines = engines
            self.save()
            return engines

        # 4) 正常列表
        if not isinstance(raw, list):
            engines = self._defaults()
            self._engines = engines
            self.save()
            return engines

        engines = [EngineConfig.from_dict(item) for item in raw if isinstance(item, dict)]
        # 名称归一 + 去重（大小写不同视为同一个）
        seen = set()
        deduped = []
        for e in engines:
            key = e.name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            e.name = canonical_name(e.name) if self.is_builtin(e.name) else e.name
            deduped.append(e)
        # 升级新增的内置引擎自动补进来
        deduped = self._append_missing_builtins(deduped)
        self._renumber(deduped)
        return deduped

    def _defaults(self) -> List[EngineConfig]:
        """
        出厂默认引擎列表。

        顺序取自各引擎声明的 ``DEFAULT_ORDER``。声明了
        ``ENABLED_BY_DEFAULT = False`` 的引擎（如需要账号的 Danbooru）
        仍会出现在列表里，但默认关闭 —— 避免开箱跑 `auto` 时一路报「未配置」。
        """
        registry.ensure_builtins_loaded()
        engines: List[EngineConfig] = []
        for name in registry.ordered_builtin_names():
            cls = registry.find_builtin(name)
            enabled = bool(getattr(cls, "ENABLED_BY_DEFAULT", True))
            ec = EngineConfig(name=name, enabled=enabled, priority=len(engines) + 1)
            self._apply_schema_defaults(ec)
            engines.append(ec)
        return engines

    def _append_missing_builtins(self, engines: List[EngineConfig]) -> List[EngineConfig]:
        """
        补上本次升级新增、但配置里还没有的内置引擎。

        否则用户升级后新引擎不会出现，只有 `engines reset` 一条路 ——
        而那会连同用户的自定义配置一起清掉。
        已有条目的顺序与配置一律保留，新引擎追加在末尾。
        """
        registry.ensure_builtins_loaded()
        existing = {e.name.strip().lower() for e in engines}
        for name in registry.ordered_builtin_names():
            if name.strip().lower() in existing:
                continue
            cls = registry.find_builtin(name)
            ec = EngineConfig(
                name=name,
                enabled=bool(getattr(cls, "ENABLED_BY_DEFAULT", True)),
                priority=len(engines) + 1,
            )
            self._apply_schema_defaults(ec)
            engines.append(ec)
        return engines

    def save(self) -> None:
        """写回 config.json（原子写）"""
        self._renumber(self._engines)
        payload = [e.to_dict() for e in self._engines]
        # 一次写入，避免版本号与内容不一致的中间状态
        save_configs(**{_CONFIG_KEY: payload, _VERSION_KEY: _SCHEMA_VERSION})
        self._last_saved = payload
        self._loaded_mtime = self._current_mtime()
        # 配置变了，动态引擎类可能也要重新解析（例如改了 module_path，
        # 或只是改了自定义引擎的文件内容）
        invalidate_engine_cache()

    def _apply_schema_defaults(self, ec: EngineConfig) -> bool:
        """
        补全 schema 中声明、但 settings 里缺失的字段。

        ⚠️ 只在**键不存在**时补。绝不因为值是 0 / False / "" 就覆盖 ——
        限额字段用 0 表示「无限制」，用真假值判断会把它换成默认值（缺陷 #6）。
        """
        changed = False
        for f in ec.schema():
            if f.key in _MANAGED_KEYS:
                continue
            if f.key not in ec.settings:
                ec.settings[f.key] = f.default
                changed = True
        return changed

    @staticmethod
    def _renumber(engines: List[EngineConfig]) -> None:
        for i, e in enumerate(engines):
            e.priority = i + 1

    @staticmethod
    def _current_mtime() -> Optional[int]:
        try:
            from imgsearch.config import _CONFIG_FILE
            return _CONFIG_FILE.stat().st_mtime_ns
        except OSError:
            return None

    def reload_if_changed(self) -> bool:
        """
        若 config.json 被本进程之外改动过，则重新载入。

        旧实现会在这种情况下静默覆盖别人的修改；现在改为先同步再改。
        Returns:
            是否发生了重新载入
        """
        mtime = self._current_mtime()
        if self._loaded_mtime is None:
            return False

        changed = mtime != self._loaded_mtime
        if not changed and self._last_saved is not None:
            # mtime 没变也要比对内容：粒度粗时它不可靠
            changed = get(_CONFIG_KEY, None) != self._last_saved

        if changed:
            self.load()
            return True
        return False

    # ── 增删改 ───────────────────────────────────

    def add(self, name: str, enabled: bool = True,
            module_path: str = "", class_name: str = "",
            position: Optional[int] = None) -> EngineConfig:
        """
        添加引擎。

        Args:
            position: 插入位置（0 起）；默认追加到最后

        Raises:
            ConfigError: 名称为空或已存在
        """
        self.reload_if_changed()
        name = (name or "").strip()
        if not name:
            raise ConfigError("引擎名称不能为空")
        if self.get(name) is not None:
            raise ConfigError(f"引擎名称已存在：{name}")

        ec = EngineConfig(
            name=name, enabled=enabled, priority=0,
            module_path=module_path, class_name=class_name,
        )
        self._apply_schema_defaults(ec)

        if position is None:
            self._engines.append(ec)
        else:
            self._engines.insert(max(0, min(position, len(self._engines))), ec)
        self.save()
        return ec

    def remove(self, name: str) -> bool:
        """删除引擎（内置引擎不可删除，只能禁用）"""
        self.reload_if_changed()
        ec = self.get(name)
        if ec is None:
            return False
        if ec.is_builtin:
            raise ConfigError(
                f"内置引擎不可删除：{ec.name}\n"
                f"如需停用，请关闭它的「启用」开关。"
            )
        self._engines.remove(ec)
        self.save()
        return True

    def rename(self, old_name: str, new_name: str) -> bool:
        """
        **原地**改名。

        旧实现走 remove + add，会连带丢掉 module_path / class_name
        并把引擎甩到列表末尾。这里只改 name 一个字段，
        priority、模块绑定、全部 settings 原样保留，且只写盘一次。
        """
        self.reload_if_changed()
        new_name = (new_name or "").strip()
        if not new_name:
            raise ConfigError("引擎名称不能为空")

        ec = self.get(old_name)
        if ec is None:
            return False
        if new_name.lower() == ec.name.strip().lower():
            return False
        if self.get(new_name) is not None:
            raise ConfigError(f"引擎名称已存在：{new_name}")
        if ec.is_builtin:
            raise ConfigError(f"内置引擎不可改名：{ec.name}")

        ec.name = new_name
        self.save()
        return True

    def set_enabled(self, name: str, enabled: bool) -> bool:
        self.reload_if_changed()
        ec = self.get(name)
        if ec is None:
            return False
        ec.enabled = bool(enabled)
        self.save()
        return True

    def toggle(self, name: str) -> Optional[bool]:
        """切换启用状态；未找到返回 None"""
        self.reload_if_changed()
        ec = self.get(name)
        if ec is None:
            return None
        ec.enabled = not ec.enabled
        self.save()
        return ec.enabled

    def move(self, name: str, direction: int) -> bool:
        """
        调整顺序（-1 上移 / +1 下移）。
        Returns:
            是否移动成功（已在边界或未找到返回 False）
        """
        self.reload_if_changed()
        ordered = self.list_all()
        idx = next((i for i, e in enumerate(ordered) if e is self.get(name)), None)
        if idx is None:
            return False
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(ordered):
            return False
        ordered[idx], ordered[new_idx] = ordered[new_idx], ordered[idx]
        self._engines = ordered
        self.save()
        return True

    def update(self, name: str, **values: Any) -> bool:
        """
        更新引擎配置。

        值会按 schema 做**类型转换 + 校验**，非法时抛 ConfigError
        （消息可直接展示给用户），不会留下写了一半的配置。

        Raises:
            ConfigError: 值非法或跨字段校验失败
        """
        self.reload_if_changed()
        ec = self.get(name)
        if ec is None:
            return False

        schema = ec.schema()
        pending = dict(ec.settings)

        for key, raw in values.items():
            f = schema.get(key)
            if f is None:
                # 未知键原样写入（自定义引擎的扩展字段）
                pending[key] = raw
                continue
            from imgsearch.engines.schema import coerce, validate
            converted = coerce(f, raw)
            validate(f, converted)
            pending[key] = converted

        check_cross_fields(schema, pending)

        # 结构性字段
        for key in ("enabled", "priority", "module_path", "class_name"):
            if key in values:
                setattr(ec, key, values[key])

        if "name" in values and values["name"] != ec.name:
            return self.rename(ec.name, values["name"])

        ec.settings = pending
        self.save()
        return True

    def update_settings(self, name: str, mapping: Dict[str, Any]) -> bool:
        """批量更新设置（``update`` 的字典版本）"""
        return self.update(name, **(mapping or {}))

    def set_module(self, name: str, module_path: str, class_name: str) -> bool:
        """设置自定义引擎的模块绑定（改名不会碰这两个字段）"""
        self.reload_if_changed()
        ec = self.get(name)
        if ec is None:
            return False
        ec.module_path = (module_path or "").strip()
        ec.class_name = (class_name or "").strip()
        self.save()
        return True

    def reset(self) -> None:
        """恢复出厂默认引擎列表"""
        self.reload_if_changed()
        self._engines = self._defaults()
        self.save()

    # ── 构造引擎实例 ─────────────────────────────

    def build_engine(self, name_or_config, proxies: Optional[dict] = None):
        """
        按配置构造引擎实例。

        Args:
            name_or_config: 引擎名或 EngineConfig
            proxies: 代理配置

        Raises:
            EngineNotFoundError: 引擎不存在或其类无法解析
        """
        ec = (self.get(name_or_config)
              if isinstance(name_or_config, str) else name_or_config)
        if ec is None:
            raise EngineNotFoundError(f"未找到引擎：{name_or_config}")

        cls = resolve_engine_class(ec)
        if cls is None:
            raise EngineNotFoundError(
                f"引擎 '{ec.name}' 的类无法解析。\n"
                f"  └─ 内置引擎：检查名称是否正确\n"
                f"  └─ 自定义引擎：检查 module_path / class_name 是否指向一个\n"
                f"     继承 SearchEngine 并实现 search() 的类"
            )

        return cls(**ec.to_engine_kwargs(proxies=proxies))


# ──────────────────────────────────────────────
#  进程内唯一实例
# ──────────────────────────────────────────────

_store: Optional[EngineStore] = None


def get_store(refresh: bool = False) -> EngineStore:
    """
    取进程内唯一的引擎配置源。

    所有界面与命令都必须经这里拿 store，否则会重现
    「多个实例各持一份列表互相覆盖」的老问题。
    """
    global _store
    if _store is None or refresh:
        _store = EngineStore()
    return _store


def reset_store() -> None:
    """丢弃单例（测试，或 config.json 被外部替换后使用）"""
    global _store
    _store = None
