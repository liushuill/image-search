"""
pytest 全局配置

1. 把项目根目录加入 sys.path，使测试能直接 import 各模块
2. **隔离运行环境**：把 config.json / data / .env 全部重定向到临时目录，
   因此测试绝不会读写你真实的配置、配额与凭据
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """
    把一切「会落盘的状态」重定向到 tmp_path。

    旧测试用「备份真实 config.json 再还原」的做法，一旦测试中途崩溃
    就会留下被改过的真实配置，而且密钥会被写进真实 .env。
    直接换路径更干净：测试全程碰不到你的实际文件。
    """
    import imgsearch.config as cfg
    import imgsearch.engines.quota as quota
    import imgsearch.engines.registry as registry
    import imgsearch.engines.store as store_mod
    import imgsearch.secrets as secrets

    config_file = tmp_path / "config.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(cfg, "_CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DATA_DIR", data_dir)
    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cfg, "CACHE_DIR", data_dir / "cache")
    monkeypatch.setattr(cfg, "DB_PATH", data_dir / "image_metadata.db")
    monkeypatch.setattr(quota, "DATA_DIR", data_dir)

    monkeypatch.setattr(secrets, "ENV_FILE", tmp_path / ".env")
    secrets.invalidate_cache()

    cfg._config = None
    store_mod.reset_store()
    registry._reset_registry_for_tests()

    yield

    cfg._config = None
    secrets.invalidate_cache()
    store_mod.reset_store()
    registry._reset_registry_for_tests()


@pytest.fixture
def store():
    """一个干净的 EngineStore（配置来自 tmp_path，与真实配置无关）"""
    from imgsearch.engines.store import EngineStore
    return EngineStore()


@pytest.fixture
def write_config():
    """直接写 config.json 的辅助函数（用于构造迁移场景）"""
    import json
    import imgsearch.config as cfg

    def _write(payload):
        cfg._CONFIG_FILE.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        cfg._config = None

    return _write
