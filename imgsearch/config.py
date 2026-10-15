"""
配置管理模块

职责分工（重要）：
  - 本模块只管**非敏感**配置，落盘在仓库根的 ``config.json``
  - 凭据（API Key 等）一律走 :mod:`imgsearch.secrets`（``.env`` / 环境变量），
    **绝不写进 config.json，绝不入库**

``get()`` / ``save_config()`` 对已知敏感键做了透明转发，
因此老代码里的 ``get("saucenao_key")`` 依然可用，但读写实际发生在 ``.env``。
"""

import json
import os
from pathlib import Path

# 仓库根目录。本文件位于 imgsearch/ 下，故取上级目录。
# ⚠️ 这里必须用 resolve().parent.parent：若写成 Path(__file__).parent，
# 配置与 data/output 目录会错位到 imgsearch/ 内部。
PROJECT_DIR = Path(__file__).resolve().parent.parent

# 输出目录（导出的结果 / 可选下载的高清原图）
OUTPUT_DIR = PROJECT_DIR / "output"
# 数据目录
DATA_DIR = PROJECT_DIR / "data"
# 缓存目录
CACHE_DIR = DATA_DIR / "cache"
# 数据库路径（SQLite 图库）
DB_PATH = DATA_DIR / "image_metadata.db"
# 缩略图缓存目录（按内容哈希分桶存放，与文件路径无关）
THUMBS_DIR = DATA_DIR / "thumbs"

_CONFIG_FILE = PROJECT_DIR / "config.json"

# 敏感键 → 环境变量名。这些键永不落 config.json，读写都转交 secrets。
_SECRET_KEYS = {
    "saucenao_key": "SAUCENAO_KEY",
    "danbooru_login": "DANBOORU_LOGIN",
    "danbooru_api_key": "DANBOORU_API_KEY",
}

# 批量识别的默认行为
#   batch_quota_policy: 引擎额度用尽时
#       "stop"     → 停下来报告还剩多少（默认；不会不知情地拿弱引擎凑数）
#       "fallback" → 继续用其他引擎，但报告里指明降级来源
#   batch_limit: 一次最多识别多少张（0 = 不限）。默认给个安全值，
#       免得手一滑就用光当天全部额度
#   batch_recursive: 是否递归子目录
_BATCH_DEFAULTS = {
    "batch_quota_policy": "stop",
    "batch_limit": 20,
    "batch_recursive": True,
}

_DEFAULT_CONFIG = {
    "proxy": "",
    # 代理探活地址（需要一条「经代理访问外网」的通路来验证代理是否真的可用）
    "proxy_check_url": "https://www.google.com/generate_204",
    # 搜索引擎列表由 EngineStore 管理，此处仅作为初始值
    "search_engines": [],
    # 本地图库：搜索前先查缓存（命中就不再消耗配额），搜索后自动记录
    "use_library": True,
    # 是否为已入库的图生成缩略图缓存（清理页可单独清掉这一类）
    "cache_thumbnails": True,
    # 批量识别（见下方 _BATCH_DEFAULTS 的说明）
    **_BATCH_DEFAULTS,
    # 图源缩略图缓存的上限（MB）；0 = 不限制。
    # 这是整套缓存里唯一会无界增长的东西 —— 每看一次新图的结果就多几条，
    # 所以给一个默认上限并按「最久未用」淘汰。
    "url_thumb_cache_mb": 100,
}

_config = None


def _ensure_dirs():
    """确保必要的目录存在"""
    for d in [OUTPUT_DIR, DATA_DIR, CACHE_DIR, THUMBS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_config():
    """加载配置文件（带进程内缓存）"""
    global _config
    if _config is not None:
        return _config

    _config = _DEFAULT_CONFIG.copy()

    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            if isinstance(user_config, dict):
                _config.update(user_config)
        except (json.JSONDecodeError, OSError):
            pass

    _ensure_dirs()
    return _config


def _write_config_atomic(config: dict) -> None:
    """
    原子写入 config.json。

    先写临时文件再 os.replace，避免中途失败留下半个文件
    （原实现直接覆盖写，写到一半崩溃会毁掉整份配置）。
    """
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_FILE.parent / (_CONFIG_FILE.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, _CONFIG_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_config(key: str, value):
    """
    保存单个配置项。

    敏感键会被转发到 ``.env``（见 :mod:`imgsearch.secrets`），不落 config.json。
    """
    env_name = _SECRET_KEYS.get(key)
    if env_name is not None:
        from imgsearch import secrets
        secrets.set(env_name, value if value is not None else "")
        return

    config = load_config()
    config[key] = value
    _write_config_atomic(config)


def save_configs(**kwargs):
    """一次写入多个非敏感配置项（只落盘一次）"""
    config = load_config()
    for k, v in kwargs.items():
        if k in _SECRET_KEYS:
            save_config(k, v)
            continue
        config[k] = v
    _write_config_atomic(config)


def get(key: str, default=None):
    """获取配置项（敏感键自动从 .env / 环境变量读取）"""
    env_name = _SECRET_KEYS.get(key)
    if env_name is not None:
        from imgsearch import secrets
        return secrets.get(env_name, default)
    return load_config().get(key, default)


def is_secret_key(key: str) -> bool:
    """该配置键是否为凭据（读写会被转发到 .env，不落 config.json）"""
    return key in _SECRET_KEYS


def secret_env_name(key: str):
    """配置键对应的环境变量名，非凭据返回 None"""
    return _SECRET_KEYS.get(key)


def get_proxies():
    """获取代理配置（requests 格式），未配置返回 None"""
    proxy = get("proxy", "")
    if proxy:
        return {"http": proxy, "https": proxy}
    return None


# 代理探活结果缓存：(代理串, 时间戳, 结果)。断网时每张图都探一次 5 秒太亏。
_proxy_probe_cache = {"key": None, "at": 0.0, "ok": False}
_PROXY_PROBE_TTL = 30.0


def check_proxy(proxies: dict = None, timeout: int = 5) -> bool:
    """
    测试代理是否可用。

    注意：探活地址默认是 ``https://www.google.com/generate_204``，
    因为只有「能经代理访问到墙外」才说明代理真的有用。
    可用 ``proxy_check_url`` 配置项替换。

    Args:
        proxies: 代理配置
        timeout: 超时秒数

    Returns:
        代理是否可用
    """
    if not proxies:
        return False

    import time
    key = str(sorted(proxies.items()))
    now = time.time()
    if (_proxy_probe_cache["key"] == key
            and now - _proxy_probe_cache["at"] < _PROXY_PROBE_TTL):
        return _proxy_probe_cache["ok"]

    try:
        import requests
        resp = requests.get(
            get("proxy_check_url", "https://www.google.com/generate_204"),
            proxies=proxies,
            timeout=timeout,
        )
        ok = resp.status_code in (200, 204)
    except Exception:
        ok = False

    _proxy_probe_cache.update(key=key, at=now, ok=ok)
    return ok


# 首次加载（同时确保目录存在）
load_config()
