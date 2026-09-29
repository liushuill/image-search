"""
本地图库 —— 数据库层

## 为什么以「内容」而不是「路径」作为身份

用户的实际工作流是：**搜完一批图 → 下载原图 → 把图统一移到「搜集过的」目录**。
也就是说文件路径会不断变化。

如果按路径索引，文件一移走索引就全部失效。所以这里：

  - 图片身份 = ``dhash``（dHash 感知哈希），路径只是**可变的「最后已知位置」**
  - 文件移到任何地方，都能凭 dHash 认出「这张搜过了」，直接复用缓存结果
    —— 不必再消耗 SauceNAO 配额（免费版只有 100 次/天）

``root_id`` 保留的是**发现时所在的根路径**，属于弱归属：
删掉某个根路径时可以据此决定要不要顺带清理它名下的记录，
但记录本身不会因为路径变化而丢失。
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List, Optional

from imgsearch.config import DB_PATH

# 数据库结构版本。改动表结构或需要重刷数据时 +1，并在 _migrate 里处理。
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 手动登记的图库根路径（可多个，分布在不同磁盘）
CREATE TABLE IF NOT EXISTS roots (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    path     TEXT    NOT NULL UNIQUE,
    label    TEXT    NOT NULL DEFAULT '',
    added_at TEXT    NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1
);

-- 图片：身份是 dhash，路径只是最后已知位置
CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dhash      TEXT    NOT NULL,
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL DEFAULT 0,
    mtime      REAL    NOT NULL DEFAULT 0,
    root_id    INTEGER REFERENCES roots(id) ON DELETE SET NULL,
    abs_path   TEXT    NOT NULL DEFAULT '',
    rel_path   TEXT    NOT NULL DEFAULT '',
    first_seen TEXT    NOT NULL,
    last_seen  TEXT    NOT NULL,
    -- 最后已知位置上文件已不存在（移动/删除/改名），记录仍然保留
    missing    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_images_dhash ON images(dhash);
CREATE INDEX IF NOT EXISTS idx_images_root  ON images(root_id);
CREATE INDEX IF NOT EXISTS idx_images_abs   ON images(abs_path);

-- 每个引擎对一张图的一条搜索结果
CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id    INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    engine      TEXT    NOT NULL,
    similarity  REAL    NOT NULL DEFAULT 0,
    pixiv_id    TEXT,
    pixiv_page  INTEGER NOT NULL DEFAULT 0,
    artist      TEXT,
    artist_id   TEXT,
    title       TEXT,
    material    TEXT,
    ext_urls    TEXT    NOT NULL DEFAULT '[]',
    highres_url TEXT,
    thumbnail   TEXT,
    danbooru_id TEXT,
    gelbooru_id TEXT,
    twitter_id  TEXT,
    extra_ids   TEXT    NOT NULL DEFAULT '{}',
    detail      TEXT,
    fetched_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_image ON results(image_id);
CREATE INDEX IF NOT EXISTS idx_results_pixiv ON results(pixiv_id);
CREATE INDEX IF NOT EXISTS idx_results_engine ON results(engine);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class LibraryDB:
    """图库数据库连接（建议用 ``with`` 管理生命周期）"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else Path(DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        # 外键必须显式打开：删 root / image 时的级联行为依赖它
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL：允许「一边搜索写入、一边界面读取」
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    # ── 生命周期 ────────────────────────────────

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "LibraryDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 建表与迁移 ──────────────────────────────

    def _init_schema(self) -> None:
        with self.transaction():
            self.conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """按 meta.schema_version 做增量迁移"""
        current = int(self.get_meta("schema_version", 0) or 0)
        if current == SCHEMA_VERSION:
            return

        # 未来新增版本时在此按 current 逐级迁移，例如：
        #   if current < 2: self.conn.execute("ALTER TABLE images ADD COLUMN ...")

        self.set_meta("schema_version", SCHEMA_VERSION)

    # ── 基础访问 ────────────────────────────────

    @contextmanager
    def transaction(self):
        """事务上下文；异常时回滚"""
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.transaction():
            return self.conn.execute(sql, params)

    def scalar(self, sql: str, params: tuple = (), default: Any = 0) -> Any:
        row = self.query_one(sql, params)
        if row is None or row[0] is None:
            return default
        return row[0]

    # ── meta ────────────────────────────────────

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    # ── 占用统计 ────────────────────────────────

    def size_on_disk(self) -> int:
        """
        数据库真实磁盘占用 = 主库文件 + WAL。

        刻意**不含** ``-shm``：那是进程内的共享内存索引（固定 ~32KB
        暂存文件），不是数据，最后一个连接关闭时会消失；算进去会让人
        以为「清理后空间没变」。
        """
        total = 0
        for suffix in ("", "-wal"):
            f = self.path.with_name(self.path.name + suffix)
            if f.exists():
                total += f.stat().st_size
        return total

    def checkpoint(self, mode: str = "TRUNCATE") -> None:
        """
        把 WAL 内容并入主库并截断 WAL 文件。

        ⚠️ 这一条是「清理要真的释放空间」的关键：WAL 模式下
        DELETE / VACUUM 的结果都会先落在 ``-wal`` 里，
        不 checkpoint 的话磁盘占用看起来不降反升。
        """
        try:
            row = self.query_one(f"PRAGMA wal_checkpoint({mode})")
            if row is not None and row[0]:
                # busy=1：有别的连接在读，退回 PASSIVE 尽力而为
                self.query_one("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass
