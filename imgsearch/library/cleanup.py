"""
图库清理

## 两个维度，按需组合

用户要的清理粒度是一个 2×N 的矩阵：

  按**路径**：这条路径名下的全部数据一键清空（删路径时的可选动作）
  按**类别**：清空所有搜索结果记录 / 清空所有缓存缩略图

## ⚠️ 为什么必须 VACUUM

SQLite 删除行之后**数据库文件不会自动缩小** —— 空间只是被标记为可复用。
用户清了 500 MB 记录却发现 ``.db`` 文件纹丝不动，是典型的「清了个寂寞」。
所以每次真正删完数据都要 ``VACUUM`` 回收，并把**前/后体积**报出来，
让「清理」这件事有可验证的结果。

## 先算后做

:func:`plan_purge` 只统计不动手，供界面在确认框里显示
「将删除 N 条记录 / M 个缩略图（约 X MB）」，避免误操作。
"""

import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Set

from imgsearch.library import thumbs
from imgsearch.library.db import LibraryDB
from imgsearch.library.errors import LibraryError
from imgsearch.library.paths import Root, RootManager
from imgsearch.library.store import LibraryStore


# ──────────────────────────────────────────────
#  统计
# ──────────────────────────────────────────────


@dataclass
class RootStats:
    """单个根路径的明细"""

    root: Root
    images: int = 0
    resolved: int = 0
    missing: int = 0
    results: int = 0
    thumbs: int = 0
    thumbs_bytes: int = 0

    @property
    def pending(self) -> int:
        """已入库但还没有搜索结果的图片数"""
        return max(0, self.images - self.resolved)


@dataclass
class LibraryStats:
    """整库总览"""

    db_bytes: int = 0
    images: int = 0
    resolved: int = 0
    missing: int = 0
    results: int = 0
    roots: List[RootStats] = field(default_factory=list)
    thumbs_total: int = 0
    thumbs_bytes: int = 0
    orphan_thumbs: int = 0
    orphan_thumbs_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.db_bytes + self.thumbs_bytes


def _format_bytes(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} TB"


def format_bytes(n: int) -> str:
    """人类可读的体积（对外暴露，CLI 与 GUI 共用）"""
    return _format_bytes(n)


def known_dhashes(db: LibraryDB, root_id: Optional[int] = None) -> Set[str]:
    """库中已知的内容哈希（可选限定某个根路径）"""
    if root_id is None:
        rows = db.query("SELECT DISTINCT dhash FROM images WHERE dhash != ''")
    else:
        rows = db.query(
            "SELECT DISTINCT dhash FROM images WHERE dhash != '' AND root_id = ?",
            (root_id,),
        )
    return {r["dhash"] for r in rows}


def _thumbs_stats_for(dhashes: Set[str]) -> tuple:
    """给定哈希集合，统计已存在的缩略图数量与体积"""
    count = 0
    total = 0
    for d in dhashes:
        try:
            p = thumbs.path_for(d)
        except LibraryError:
            continue
        if p.is_file():
            count += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return count, total


def collect_stats(db: LibraryDB, store: LibraryStore) -> LibraryStats:
    """汇总整库占用，供界面与 CLI 展示"""
    stats = LibraryStats(
        db_bytes=db.size_on_disk(),
        images=store.count_images(),
        resolved=store.count_resolved(),
        missing=store.count_images(only_missing=True),
        results=store.count_results(),
    )

    for root in RootManager(db).list():
        rs = RootStats(
            root=root,
            images=store.count_images(root_id=root.id),
            resolved=store.count_resolved(root_id=root.id),
            missing=store.count_images(root_id=root.id, only_missing=True),
            results=store.count_results(root_id=root.id),
        )
        rs.thumbs, rs.thumbs_bytes = _thumbs_stats_for(known_dhashes(db, root.id))
        stats.roots.append(rs)

    t = thumbs.stats()
    stats.thumbs_total = t["count"]
    stats.thumbs_bytes = t["bytes"]

    # 孤立缩略图：数据库里已经没有对应记录，却还留在磁盘上
    all_known = known_dhashes(db)
    orphan_count = 0
    orphan_bytes = 0
    for f in thumbs.iter_files():
        if f.stem not in all_known:
            orphan_count += 1
            try:
                orphan_bytes += f.stat().st_size
            except OSError:
                pass
    stats.orphan_thumbs = orphan_count
    stats.orphan_thumbs_bytes = orphan_bytes

    return stats


# ──────────────────────────────────────────────
#  清理
# ──────────────────────────────────────────────


@dataclass
class PurgeOptions:
    """
    清理范围。

    - ``root_id=None`` 表示**所有路径**；否则只动指定路径
    - ``images=True`` 会连同图片记录一起删（结果级联删除）
    - 只清结果、保留图片记录时，dHash 索引仍在，
      所以「这张搜过了」的判断依然有效，只是需要重新搜一次拿结果
    """

    root_id: Optional[int] = None
    results: bool = False
    thumbs: bool = False
    images: bool = False

    def is_empty(self) -> bool:
        return not (self.results or self.thumbs or self.images)


@dataclass
class PurgePlan:
    """清理前的预演：要动多少东西、能释放多少空间"""

    options: PurgeOptions
    images: int = 0
    results: int = 0
    thumbs: int = 0
    thumbs_bytes: int = 0
    db_bytes_before: int = 0

    @property
    def estimated_free_bytes(self) -> int:
        return self.thumbs_bytes

    def describe(self) -> str:
        scope = "全部路径" if self.options.root_id is None else f"路径 id={self.options.root_id}"
        lines = [f"清理范围：{scope}"]
        if self.options.images:
            lines.append(f"  · 图片记录：{self.images} 条（其搜索结果会一并删除）")
        elif self.options.results:
            lines.append(f"  · 搜索结果：{self.results} 条（图片记录保留）")
        if self.options.thumbs:
            lines.append(f"  · 缓存缩略图：{self.thumbs} 个（{_format_bytes(self.thumbs_bytes)}）")
        lines.append(f"  · 当前数据库文件：{_format_bytes(self.db_bytes_before)}"
                     f"（清理后会自动 VACUUM 回收）")
        return "\n".join(lines)


@dataclass
class PurgeResult:
    """清理结果（含 VACUUM 前后的真实体积变化）"""

    images_removed: int = 0
    results_removed: int = 0
    thumbs_removed: int = 0
    db_bytes_before: int = 0
    db_bytes_after: int = 0

    @property
    def db_bytes_freed(self) -> int:
        return max(0, self.db_bytes_before - self.db_bytes_after)

    def describe(self) -> str:
        lines = []
        if self.images_removed:
            lines.append(f"  已删除图片记录：{self.images_removed} 条")
        if self.results_removed:
            lines.append(f"  已删除搜索结果：{self.results_removed} 条")
        if self.thumbs_removed:
            lines.append(f"  已删除缩略图：{self.thumbs_removed} 个")
        lines.append(f"  数据库文件：{_format_bytes(self.db_bytes_before)}"
                     f" → {_format_bytes(self.db_bytes_after)}"
                     f"（回收 {_format_bytes(self.db_bytes_freed)}）")
        return "\n".join(lines) if lines else "  没有需要清理的内容"


def plan_purge(db: LibraryDB, store: LibraryStore,
               options: PurgeOptions) -> PurgePlan:
    """预演一次清理，不修改任何数据"""
    if options.is_empty():
        raise LibraryError("没有选择任何要清理的内容")

    plan = PurgePlan(options=options, db_bytes_before=db.size_on_disk())
    root_id = options.root_id

    if options.images:
        plan.images = store.count_images(root_id=root_id)
        plan.results = store.count_results(root_id=root_id)
    elif options.results:
        plan.results = store.count_results(root_id=root_id)

    if options.thumbs:
        # 缩略图按内容存放；要删的是「本次涉及的图片」对应的那些
        if options.images or options.results:
            dhashes = known_dhashes(db, root_id)
        else:
            dhashes = {f.stem for f in thumbs.iter_files()}
        plan.thumbs, plan.thumbs_bytes = _thumbs_stats_for(dhashes)

    return plan


def execute_purge(db: LibraryDB, store: LibraryStore,
                  options: PurgeOptions) -> PurgeResult:
    """
    执行清理。

    顺序：先取出要删的 dHash（缩略图按内容存，必须在删记录**之前**取），
    再删数据库行，最后删缩略图文件并 VACUUM 回收。
    """
    if options.is_empty():
        raise LibraryError("没有选择任何要清理的内容")

    root_id = options.root_id
    result = PurgeResult(db_bytes_before=db.size_on_disk())

    # 1) 删记录前先记下涉及的 dHash
    dhashes: Set[str] = set()
    if options.thumbs and (options.images or options.results):
        dhashes = known_dhashes(db, root_id)

    # 2) 删数据库行
    with db.transaction():
        if options.images:
            if root_id is None:
                result.results_removed = store.count_results()
                cur = db.conn.execute("DELETE FROM images")
            else:
                result.results_removed = store.count_results(root_id=root_id)
                cur = db.conn.execute("DELETE FROM images WHERE root_id = ?", (root_id,))
            result.images_removed = cur.rowcount if cur.rowcount > 0 else 0

        elif options.results:
            if root_id is None:
                cur = db.conn.execute("DELETE FROM results")
            else:
                cur = db.conn.execute(
                    "DELETE FROM results WHERE image_id IN"
                    " (SELECT id FROM images WHERE root_id = ?)",
                    (root_id,),
                )
            result.results_removed = cur.rowcount if cur.rowcount > 0 else 0

    # 3) 删缩略图
    if options.thumbs:
        if options.images or options.results:
            result.thumbs_removed = thumbs.remove_many(dhashes)
        else:
            result.thumbs_removed = thumbs.purge_all()

    # 4) 真正把空间还回磁盘
    if result.images_removed or result.results_removed:
        _compact(db)

    result.db_bytes_after = db.size_on_disk()
    return result


def _compact(db: LibraryDB) -> None:
    """
    把清理结果真正落到磁盘：**先并 WAL → VACUUM → 再并 WAL**。

    顺序不能反，也不能省：

      1. DELETE 只把页标记为可复用，文件不会变小 → 需要 VACUUM
      2. 但 WAL 模式下 VACUUM 的产物先写进 ``-wal``，
         不 checkpoint 的话磁盘占用反而**看起来变大**了
      3. 所以最后再 checkpoint 一次并截断 WAL，空间才算真的回来

    这就是「清了 500MB 却发现文件没变小」的根因。
    """
    db.checkpoint("TRUNCATE")
    try:
        # VACUUM 不能在事务里执行
        db.conn.isolation_level = None
        db.conn.execute("VACUUM")
    except sqlite3.Error:
        pass
    finally:
        db.conn.isolation_level = ""
    db.checkpoint("TRUNCATE")


def purge_orphan_thumbs(db: LibraryDB) -> int:
    """
    清理孤立缩略图（数据库里已无对应记录）并回收。

    典型来源：清空了搜索结果但没同时清缩略图，之后又删过记录。
    """
    removed = thumbs.purge_orphans(known_dhashes(db))
    return removed
