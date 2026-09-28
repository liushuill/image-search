"""
搜索引擎配置管理

每个搜索引擎独立配置，通过数字权重（priority）排序。
支持增删启禁，每个引擎可独立设置 api_url / api_key / headers / params / 超时等。

预留的引擎配置字段:
  - api_url:       API 地址（请求端点）
  - api_key:       API 密钥 / 令牌（写入时会替换内置引擎的空值从全局配置读取）
  - headers:       自定义 HTTP 请求头（键值对）
  - params:        自定义 URL 查询参数（键值对）
  - request_delay: 请求间隔（秒）
  - timeout:       请求超时（秒）
"""

import importlib
from dataclasses import dataclass, asdict, field
from typing import List, Optional

from imgsearch.config import get, save_config


# ──────────────────────────────────────────────
#  引擎配置数据模型
# ──────────────────────────────────────────────


@dataclass
class EngineConfig:
    """单个搜索引擎的完整配置"""

    name: str                       # 引擎名称，如 "sauceNAO"、"ascii2d"
    enabled: bool = True            # 是否启用
    priority: int = 0               # 权重（数字越小越优先，自动调整）

    # ── 引擎级连接配置 ──────────────────────────
    api_url: str = ""               # API 请求地址
    api_key: str = ""               # API 密钥（密码字段，显示时脱敏）
    headers: dict = field(default_factory=dict)   # 自定义 HTTP 头
    params: dict = field(default_factory=dict)    # 自定义 URL 参数
    request_delay: float = 8.0      # 每次搜索后的等待间隔（秒）
    timeout: int = 30               # 请求超时（秒）

    # ── 引擎级速率限制 ──────────────────────────
    long_limit: int = 100           # 长期限额（窗口内最多请求次数）
    short_limit: int = 4            # 短期限额（窗口内最多请求次数）
    long_window: int = 86400        # 长期窗口时长（秒，默认 24h）
    short_window: int = 30          # 短期窗口时长（秒，默认 30s）

    # ── 反爬绕过 ────────────────────────────────
    bypass_cfw: bool = False        # 启用 Cloudflare 反爬绕过（仅 Ascii2D）

    # ── 自定义引擎动态加载 ──────────────────────
    module_path: str = ""           # 自定义引擎的模块路径，如 "my_engines.custom"
    class_name: str = ""            # 自定义引擎的类名，如 "MyEngine"


# ──────────────────────────────────────────────
#  内置引擎及默认配置
# ──────────────────────────────────────────────

_BUILTIN_ENGINES = ["sauceNAO", "ascii2d", "danbooru"]

_CONFIG_KEY = "search_engines"

# 内置引擎的出厂默认配置
_BUILTIN_DEFAULTS = {
    "sauceNAO": dict(
        api_url="https://saucenao.com/search.php",
        api_key="",  # 运行时从全局 saucenao_key 读取
        headers={},
        params={"db": 999, "output_type": 2},
        request_delay=8.0,
        timeout=30,
        long_limit=100,
        short_limit=4,
        long_window=86400,   # 24h
        short_window=30,     # 30s
        bypass_cfw=False,
    ),
    "ascii2d": dict(
        api_url="https://ascii2d.net",
        api_key="",
        headers={},
        params={},
        request_delay=3.0,
        timeout=30,
        long_limit=0,    # 无限制
        short_limit=0,   # 无限制
        long_window=0,   # 无窗口限制
        short_window=0,  # 无窗口限制
        bypass_cfw=False,
    ),
    "danbooru": dict(
        api_url="https://danbooru.donmai.us",
        api_key="",  # 运行时从 params.login 读取
        headers={},
        params={"login": ""},
        request_delay=8.0,
        timeout=30,
        long_limit=0,    # 无限制
        short_limit=0,   # 无限制
        long_window=0,   # 无窗口限制
        short_window=0,  # 无窗口限制
        bypass_cfw=False,
    ),
}

_DEFAULT_ENGINES = [
    EngineConfig(name="sauceNAO", enabled=True, priority=1,
                 **_BUILTIN_DEFAULTS["sauceNAO"]),
    EngineConfig(name="ascii2d", enabled=True, priority=2,
                 **_BUILTIN_DEFAULTS["ascii2d"]),
    EngineConfig(name="danbooru", enabled=True, priority=3,
                 **_BUILTIN_DEFAULTS["danbooru"]),
]

# 已知引擎名称到类的映射（内置引擎 + 动态加载缓存）
_ENGINE_CLASS_CACHE: dict = {}


def resolve_engine_class(ec: EngineConfig) -> Optional[type]:
    """
    根据 EngineConfig 解析引擎类。

    优先级：
    1. 有 module_path + class_name → importlib 动态导入
    2. 名称在 _ENGINE_CLASS_CACHE 中 → 直接返回
    3. 否则返回 None

    Args:
        ec: 引擎配置对象

    Returns:
        引擎类，如果无法解析则返回 None
    """
    cache_key = ec.name

    # 检查缓存
    if cache_key in _ENGINE_CLASS_CACHE:
        return _ENGINE_CLASS_CACHE[cache_key]

    # 优先使用 module_path + class_name 动态导入
    if ec.module_path and ec.class_name:
        try:
            module = importlib.import_module(ec.module_path)
            cls = getattr(module, ec.class_name)
            _ENGINE_CLASS_CACHE[cache_key] = cls
            return cls
        except ImportError as e:
            print(f"  ⚠️ 加载自定义引擎 '{ec.name}' 失败：找不到模块 '{ec.module_path}'")
            print(f"    └─ 请确保模块文件存在且 Python 可访问该路径")
            print(f"    └─ 详细错误: {e}")
            return None
        except AttributeError as e:
            print(f"  ⚠️ 加载自定义引擎 '{ec.name}' 失败：模块中找不到类 '{ec.class_name}'")
            print(f"    └─ 请检查模块 '{ec.module_path}' 中是否定义了名为 '{ec.class_name}' 的类")
            print(f"    └─ 该类必须继承自 SearchEngine 并实现 search() 方法")
            print(f"    └─ 详细错误: {e}")
            return None

    return None


def register_engine_class(name: str, cls: type):
    """
    注册引擎类到缓存（供 main.py 内置引擎使用）。

    Args:
        name: 引擎名称
        cls: 引擎类
    """
    _ENGINE_CLASS_CACHE[name] = cls


# ──────────────────────────────────────────────
#  引擎管理器
# ──────────────────────────────────────────────


class EngineManager:
    """搜索引擎配置管理器（CRUD）"""

    def __init__(self):
        self._engines: List[EngineConfig] = []
        self._load()

    # ── 字段过滤（兼容旧配置） ──────────────────

    _ENGINE_FIELDS = {f.name for f in EngineConfig.__dataclass_fields__.values()}

    # ── 加载与保存 ──────────────────────────────

    def _load(self):
        """从 config.json 加载引擎列表"""
        raw = get(_CONFIG_KEY, None)
        if raw is None:
            self._engines = list(_DEFAULT_ENGINES)
            self._save()
        elif isinstance(raw, list) and raw and isinstance(raw[0], str):
            # 兼容旧格式：["sauceNAO", "ascii2d"] → 新格式
            self._engines = [
                EngineConfig(name=name, enabled=True, priority=i + 1,
                             **_BUILTIN_DEFAULTS.get(name, {}))
                for i, name in enumerate(raw)
            ]
            self._save()
        elif isinstance(raw, list) and not raw:
            # 空列表 → 回退到出厂默认
            self._engines = list(_DEFAULT_ENGINES)
            self._save()
        else:
            self._engines = [
                EngineConfig(**{k: v for k, v in s.items() if k in self._ENGINE_FIELDS})
                for s in raw
            ]
            # 确保内置引擎有默认配置（用户可能手动删除了字段）
            self._ensure_builtin_defaults()

    def _save(self):
        """保存引擎列表到 config.json"""
        self._renumber()  # 保存前自动重新编号
        raw = [asdict(e) for e in self._engines]
        save_config(_CONFIG_KEY, raw)

    def _ensure_builtin_defaults(self):
        """确保内置引擎的配置项齐全（填充缺失字段为默认值）"""
        changed = False
        for e in self._engines:
            if e.name in _BUILTIN_DEFAULTS:
                defaults = _BUILTIN_DEFAULTS[e.name]
                for k, v in defaults.items():
                    if not hasattr(e, k) or getattr(e, k) in (None, ""):
                        setattr(e, k, v)
                        changed = True
        if changed:
            self._save()

    # ── 自动重新编号 ────────────────────────────

    def _renumber(self):
        """按当前顺序自动调整 priority 为 1, 2, 3, ..."""
        for i, e in enumerate(self._engines):
            if e.priority != i + 1:
                e.priority = i + 1

    # ── 查询 ────────────────────────────────────

    def list_all(self) -> List[EngineConfig]:
        """获取所有引擎（按 priority 排序）"""
        return sorted(self._engines, key=lambda e: e.priority)

    def get_enabled(self) -> List[EngineConfig]:
        """获取所有启用的引擎（按 priority 排序）"""
        return sorted(
            [e for e in self._engines if e.enabled],
            key=lambda e: e.priority,
        )

    def get_by_name(self, name: str) -> Optional[EngineConfig]:
        """按名称查找引擎"""
        for e in self._engines:
            if e.name.lower() == name.lower():
                return e
        return None

    def get_names(self) -> List[str]:
        """获取所有引擎名称"""
        return [e.name for e in self._engines]

    def is_builtin(self, name: str) -> bool:
        """是否为内置引擎"""
        return name.lower() in (b.lower() for b in _BUILTIN_ENGINES)

    def get_resolved_api_key(self, name: str) -> str:
        """
        获取引擎的最终 API Key。
        如果引擎自身的 api_key 为空，则回退到全局 saucenao_key 配置。
        """
        e = self.get_by_name(name)
        if e and e.api_key:
            return e.api_key
        return get("saucenao_key", "")

    # ── CRUD ────────────────────────────────────

    def add(self, name: str, enabled: bool = True) -> bool:
        """
        添加新引擎

        Args:
            name: 引擎名称
            enabled: 是否启用

        Returns:
            是否添加成功（名称重复时返回 False）
        """
        if any(e.name.lower() == name.lower() for e in self._engines):
            return False
        # 新引擎优先级自动排到最后
        max_pri = max((e.priority for e in self._engines), default=0)
        self._engines.append(EngineConfig(name=name, enabled=enabled, priority=max_pri + 1))
        self._save()
        return True

    def remove(self, name: str) -> bool:
        """
        删除引擎（仅允许删除非内置引擎）

        Args:
            name: 引擎名称

        Returns:
            是否删除成功
        """
        if self.is_builtin(name):
            return False  # 内置引擎不可删除
        for i, e in enumerate(self._engines):
            if e.name.lower() == name.lower():
                self._engines.pop(i)
                self._save()
                return True
        return False

    def toggle(self, name: str) -> Optional[bool]:
        """
        切换引擎启用/禁用状态

        Args:
            name: 引擎名称

        Returns:
            切换后的状态，未找到返回 None
        """
        for e in self._engines:
            if e.name.lower() == name.lower():
                e.enabled = not e.enabled
                self._save()
                return e.enabled
        return None

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """设置引擎启用/禁用状态"""
        for e in self._engines:
            if e.name.lower() == name.lower():
                e.enabled = enabled
                self._save()
                return True
        return False

    def move(self, name: str, direction: int) -> bool:
        """
        移动引擎位置（调整 priority）

        Args:
            name: 引擎名称
            direction: -1 向上移动，1 向下移动

        Returns:
            是否移动成功
        """
        engines = sorted(self._engines, key=lambda e: e.priority)
        idx = next((i for i, e in enumerate(engines) if e.name.lower() == name.lower()), None)
        if idx is None:
            return False
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(engines):
            return False
        engines[idx], engines[new_idx] = engines[new_idx], engines[idx]
        self._engines = engines
        self._save()
        return True

    def update_config(self, name: str, **kwargs) -> bool:
        """
        更新引擎的配置字段

        Args:
            name: 引擎名称
            **kwargs: 要更新的字段名和值

        Returns:
            是否更新成功
        """
        for e in self._engines:
            if e.name.lower() == name.lower():
                for k, v in kwargs.items():
                    if hasattr(e, k):
                        setattr(e, k, v)
                self._save()
                return True
        return False

    def reset(self):
        """恢复默认引擎列表"""
        self._engines = list(_DEFAULT_ENGINES)
        self._save()
