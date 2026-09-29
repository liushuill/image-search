"""
本地图库

以 **dHash 内容**为身份、路径只作「最后已知位置」的图片元数据仓库。
文件在目录间移动后仍能认出「这张搜过了」，从而复用缓存结果、节省搜索配额。

典型用法::

    from imgsearch.library import LibraryDB, LibraryStore

    with LibraryDB() as db:
        store = LibraryStore(db)
        match = store.lookup("某张图.jpg")        # 这张搜过了吗
        if match and store.has_results(match.record.id):
            results = store.load_results(match.record.id)   # 直接复用
"""

from imgsearch.library.cleanup import (
    LibraryStats,
    PurgeOptions,
    PurgePlan,
    PurgeResult,
    RootStats,
    collect_stats,
    execute_purge,
    format_bytes,
    known_dhashes,
    plan_purge,
    purge_orphan_thumbs,
)
from imgsearch.library.db import SCHEMA_VERSION, LibraryDB
from imgsearch.library.errors import LibraryError
from imgsearch.library.paths import Root, RootManager, normalize_path
from imgsearch.library.store import (
    Fingerprint,
    ImageRecord,
    LibraryStore,
    Match,
    fingerprint_file,
)

__all__ = [
    "LibraryDB", "SCHEMA_VERSION",
    "LibraryStore", "ImageRecord", "Match", "Fingerprint", "fingerprint_file",
    "Root", "RootManager", "normalize_path",
    "LibraryError",
    "LibraryStats", "RootStats", "PurgeOptions", "PurgePlan", "PurgeResult",
    "collect_stats", "plan_purge", "execute_purge", "purge_orphan_thumbs",
    "known_dhashes", "format_bytes",
]
