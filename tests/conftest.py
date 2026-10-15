"""
pytest 全局配置

1. 把项目根目录加入 sys.path，使测试能直接 import 各模块
2. **隔离运行环境**：把 config.json / data / .env 全部重定向到临时目录，
   因此测试绝不会读写你真实的配置、配额与凭据
"""

import os
import sys
from pathlib import Path

import pytest

# ⚠️ 必须在导入 PySide6 之前设置：GUI 测试要能在无显示环境下跑（也便于进 CI）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    import imgsearch.library.db as lib_db
    import imgsearch.library.thumbs as lib_thumbs
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

    # 这两个模块用 `from ... import X` 绑定了名字，必须打在它们自己的命名空间上，
    # 否则测试仍会写到真实的 data/ 目录
    monkeypatch.setattr(lib_db, "DB_PATH", data_dir / "image_metadata.db")
    monkeypatch.setattr(lib_thumbs, "THUMBS_DIR", data_dir / "thumbs")

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


@pytest.fixture
def pattern_image(tmp_path):
    """
    生成有结构的测试图。

    ⚠️ 不能用纯色图：纯色图的 dHash 全部为 0，彼此无法区分，
    会把「按内容判重」的测试变成永远命中。

    ⚠️ 相对路径一律落到 tmp_path：否则图片会写进仓库根目录造成污染，
    而且后续 rename 可能跨设备失败。
    """
    def _make(path, seed=0, size=(90, 70)):
        from PIL import Image, ImageDraw
        p = Path(path)
        if not p.is_absolute():
            p = tmp_path / p
        p.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", size, "white")
        d = ImageDraw.Draw(img)
        for i in range(6):
            x = (seed * 17 + i * 13) % size[0]
            d.rectangle((x, 0, x + 6 + (seed % 7), size[1]),
                        fill=((i * 40 + seed * 11) % 256, (seed * 30) % 256, 120))
        img.save(p)
        return p
    return _make


@pytest.fixture
def library():
    """
    一个独立的图库（db + store）。

    ⚠️ 刻意用 `LibraryDB()` 而非显式路径：这样它和「被测代码自己打开的图库」
    （service.open_library → LibraryDB()）指向**同一个**文件。
    否则测试往里写、被测代码却去读另一个空库，缓存测试会永远「未命中」
    并真的发起网络请求。
    """
    from imgsearch.library import LibraryDB, LibraryStore
    with LibraryDB() as db:
        yield db, LibraryStore(db)


@pytest.fixture(scope="session")
def qapp():
    """
    整个测试会话共用一个 QApplication（Qt 只允许存在一个）。

    ⚠️ 收尾必须停掉所有后台缩略图线程。pytest 不会让 QApplication 走
    正常退出流程，因此 aboutToQuit 收不到；而 QThread 在还在跑的时候被
    销毁，Qt 会直接 abort 整个进程（表现为 pytest exit 134 + 一大段
    "Extension modules:" 的崩溃转储，很难看出真正原因）。
    """
    pytest.importorskip("PySide6")
    from imgsearch_gui.app import create_app
    app = create_app([])
    yield app

    from imgsearch_gui.widgets.thumbnails import stop_all_loaders
    stop_all_loaders()
