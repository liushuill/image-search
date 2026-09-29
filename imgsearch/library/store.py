"""
图库记录层

核心能力：**凭内容认出「这张搜过了」**，并复用缓存的结果。

用户的文件会在目录之间移动（搜完 → 下载原图 → 移到「搜集过的」），
所以查找以 dHash 为键，路径只是附带信息：

    rec = store.lookup(path)          # 算 dHash → 命中已有记录
    if rec and store.has_results(rec.id):
        results = store.load_results(rec.id)   # 直接复用，不再消耗配额

匹配分三档，如实告知调用方，避免把「相似」当成「同一张」：

  - ``exact``    dHash 相同且尺寸相同  → 基本就是同一张（可能被重新编码过）
  - ``scaled``   dHash 距离很小但尺寸不同 → 同一张画的缩放版
  - ``similar``  dHash 距离在阈值内但尺寸相同 → 视觉接近，需人工确认
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from imgsearch.engines.base import SearchResult
from imgsearch.library.db import LibraryDB
from imgsearch.library.errors import LibraryError
from imgsearch.library.paths import Root, RootManager, normalize_path
from imgsearch.processor.image_utils import get_file_hash, get_image_info, hamming_distance

# 近似匹配时最多扫描多少条记录。
# 个人图库（几千~几万张）全表扫描只是毫秒级；这里加个上限是为了
# 在超大库上不至于卡死，超出时只做精确匹配。
MAX_SIMILAR_SCAN = 20000


def _bind(value):
    """把任意值变成 SQLite 能绑定的标量（容器转成 JSON 字符串）"""
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, bool):
        return int(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)

# 默认的 dHash 汉明距离阈值：64 位哈希下 0–6 属于「很可能是同一张」
DEFAULT_MAX_DISTANCE = 6


@dataclass
class ImageRecord:
    """一张图片在图库中的记录"""

    id: int
    dhash: str
    width: int = 0
    height: int = 0
    size: int = 0
    mtime: float = 0.0
    root_id: Optional[int] = None
    abs_path: str = ""
    rel_path: str = ""
    first_seen: str = ""
    last_seen: str = ""
    missing: bool = False

    @property
    def exists(self) -> bool:
        return bool(self.abs_path) and os.path.isfile(self.abs_path)

    @property
    def dimensions(self) -> str:
        return f"{self.width}x{self.height}" if self.width else ""


@dataclass
class Match:
    """一次内容匹配的结果"""

    record: ImageRecord
    kind: str          # exact / scaled / similar
    distance: int = 0

    @property
    def is_same_image(self) -> bool:
        """是否可视为「同一张图」（含缩放版）"""
        return self.kind in ("exact", "scaled")


class LibraryStore:
    """图库记录的读写"""

    def __init__(self, db: LibraryDB):
        self.db = db
        self.roots = RootManager(db)

    # ── 查找 ────────────────────────────────────

    @staticmethod
    def _row_to_image(row) -> ImageRecord:
        return ImageRecord(
            id=row["id"],
            dhash=row["dhash"],
            width=row["width"],
            height=row["height"],
            size=row["size"],
            mtime=row["mtime"],
            root_id=row["root_id"],
            abs_path=row["abs_path"],
            rel_path=row["rel_path"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            missing=bool(row["missing"]),
        )

    def get_image(self, image_id: int) -> Optional[ImageRecord]:
        row = self.db.query_one("SELECT * FROM images WHERE id = ?", (image_id,))
        return self._row_to_image(row) if row else None

    def get_by_path(self, file_path: str) -> Optional[ImageRecord]:
        target = normalize_path(file_path)
        row = self.db.query_one("SELECT * FROM images WHERE abs_path = ?", (target,))
        return self._row_to_image(row) if row else None

    def find_by_dhash(self, dhash: str, width: int = 0, height: int = 0) -> Optional[Match]:
        """
        精确匹配：dHash 相同（尺寸也相同则视为 exact，否则 scaled）。

        Args:
            dhash: 目标图片的 dHash
            width / height: 目标图片尺寸，用于区分 exact / scaled
        """
        if not dhash:
            return None
        rows = self.db.query("SELECT * FROM images WHERE dhash = ?", (dhash,))
        if not rows:
            return None

        best = None
        for row in rows:
            rec = self._row_to_image(row)
            same_dims = (not width or not height
                         or (rec.width == width and rec.height == height))
            kind = "exact" if same_dims else "scaled"
            # exact 优先
            if best is None or (kind == "exact" and best.kind != "exact"):
                best = Match(record=rec, kind=kind, distance=0)
        return best

    def find_similar(self, dhash: str, max_distance: int = DEFAULT_MAX_DISTANCE,
                     width: int = 0, height: int = 0) -> Optional[Match]:
        """
        近似匹配：dHash 汉明距离在阈值内。

        用于识别「被压缩/改过尺寸的同一张图」—— 正是原始需求里
        「质量被压缩、想找原图」要解决的问题。
        """
        if not dhash:
            return None

        total = self.db.scalar("SELECT COUNT(*) FROM images")
        if total > MAX_SIMILAR_SCAN:
            # 库太大，放弃近似匹配（精确匹配仍然可用）
            return None

        rows = self.db.query("SELECT * FROM images WHERE dhash != ''")
        best: Optional[Match] = None
        for row in rows:
            dist = hamming_distance(dhash, row["dhash"])
            if dist < 0:
                continue
            if dist > max_distance:
                continue
            if best is not None and dist >= best.distance:
                continue
            rec = self._row_to_image(row)
            if width and height and rec.width == width and rec.height == height:
                kind = "similar"
            else:
                kind = "scaled"
            best = Match(record=rec, kind=kind, distance=dist)
        return best

    def lookup(self, file_path: str, max_distance: int = DEFAULT_MAX_DISTANCE,
               allow_similar: bool = True) -> Optional[Match]:
        """
        便捷入口：给一个文件路径，算出内容指纹后在图库里找。

        这是「这张图搜过了吗」的实现。**不要求文件在已登记的根路径下** ——
        文件被移到任何地方都能命中。

        Raises:
            LibraryError: 读不出图片内容（非图片或已损坏）
        """
        fingerprint = fingerprint_file(file_path)
        exact = self.find_by_dhash(fingerprint.dhash, fingerprint.width, fingerprint.height)
        if exact is not None:
            return exact
        if allow_similar:
            return self.find_similar(fingerprint.dhash, max_distance,
                                     fingerprint.width, fingerprint.height)
        return None

    # ── 记录 ────────────────────────────────────

    def upsert_image(self, file_path: str,
                     root: Optional[Root] = None) -> ImageRecord:
        """
        把一张图登记进图库（已存在则更新「最后已知位置」）。

        已存在时**不会**新建记录 —— 即便文件被移到了别处，
        也是更新原记录的路径，从而保住它已缓存的结果。
        """
        fingerprint = fingerprint_file(file_path)
        abs_path = normalize_path(file_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        match = self.find_by_dhash(fingerprint.dhash, fingerprint.width, fingerprint.height)
        if match is not None:
            rec = match.record
            self._touch(rec.id, abs_path, root, now, fingerprint)
            return self.get_image(rec.id)

        if root is None:
            containing = self.roots.roots_containing(abs_path)
            root = containing[0] if containing else None

        rel_path = ""
        root_id = None
        if root is not None:
            root_id = root.id
            try:
                rel_path = os.path.relpath(abs_path, root.path)
            except ValueError:
                rel_path = ""

        with self.db.transaction():
            cur = self.db.conn.execute(
                "INSERT INTO images(dhash, width, height, size, mtime, root_id,"
                " abs_path, rel_path, first_seen, last_seen, missing)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (fingerprint.dhash, fingerprint.width, fingerprint.height,
                 fingerprint.size, fingerprint.mtime, root_id,
                 abs_path, rel_path, now, now),
            )
        return self.get_image(cur.lastrowid)

    def _touch(self, image_id: int, abs_path: str, root: Optional[Root],
               now: str, fingerprint: "Fingerprint") -> None:
        """更新「最后已知位置」与体积信息"""
        root_id = root.id if root is not None else None
        rel_path = ""
        if root is not None:
            try:
                rel_path = os.path.relpath(abs_path, root.path)
            except ValueError:
                rel_path = ""

        if root_id is None:
            containing = self.roots.roots_containing(abs_path)
            if containing:
                root_id = containing[0].id
                try:
                    rel_path = os.path.relpath(abs_path, containing[0].path)
                except ValueError:
                    rel_path = ""

        with self.db.transaction():
            self.db.conn.execute(
                "UPDATE images SET abs_path = ?, rel_path = ?, root_id = ?,"
                " size = ?, mtime = ?, last_seen = ?, missing = 0 WHERE id = ?",
                (abs_path, rel_path, root_id, fingerprint.size,
                 fingerprint.mtime, now, image_id),
            )

    def save_results(self, image_id: int, results: Sequence[SearchResult],
                     replace: bool = True) -> int:
        """
        保存某张图的搜索结果。

        Args:
            replace: True 时先清掉该图已有结果（同一张图重搜 = 覆盖），
                     False 时追加。

        Returns:
            写入的结果条数
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction():
            if replace:
                self.db.conn.execute("DELETE FROM results WHERE image_id = ?", (image_id,))
            for r in results:
                # SearchResult.__post_init__ 已做归一化；这里再兜一层，
                # 保证任何值都能安全绑定（宁可存成字符串，也不要整条失败）
                self.db.conn.execute(
                    "INSERT INTO results(image_id, engine, similarity, pixiv_id, pixiv_page,"
                    " artist, artist_id, title, material, ext_urls, highres_url, thumbnail,"
                    " danbooru_id, gelbooru_id, twitter_id, extra_ids, detail, fetched_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (image_id, _bind(r.source), float(r.similarity or 0),
                     _bind(r.pixiv_id), int(r.pixiv_page or 0),
                     _bind(r.artist), _bind(r.artist_id), _bind(r.title),
                     _bind(r.material),
                     json.dumps(list(r.ext_urls or []), ensure_ascii=False),
                     _bind(r.highres_url), _bind(r.thumbnail),
                     _bind(r.danbooru_id), _bind(r.gelbooru_id),
                     _bind(r.twitter_id),
                     json.dumps(dict(r.extra_ids or {}), ensure_ascii=False),
                     _bind(r.detail), now),
                )
        return len(results)

    def load_results(self, image_id: int) -> List[SearchResult]:
        """把缓存的结果还原成 SearchResult，形状与刚搜出来的一致"""
        rows = self.db.query(
            "SELECT * FROM results WHERE image_id = ? ORDER BY similarity DESC, id",
            (image_id,),
        )
        return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row) -> SearchResult:
        def _json(text, fallback):
            try:
                return json.loads(text) if text else fallback
            except (json.JSONDecodeError, TypeError):
                return fallback

        return SearchResult(
            source=row["engine"],
            similarity=float(row["similarity"] or 0),
            pixiv_id=row["pixiv_id"],
            pixiv_page=int(row["pixiv_page"] or 0),
            artist=row["artist"],
            artist_id=row["artist_id"],
            title=row["title"],
            material=row["material"],
            ext_urls=_json(row["ext_urls"], []),
            highres_url=row["highres_url"],
            thumbnail=row["thumbnail"],
            danbooru_id=row["danbooru_id"],
            gelbooru_id=row["gelbooru_id"],
            twitter_id=row["twitter_id"],
            extra_ids=_json(row["extra_ids"], {}),
            detail=row["detail"],
        )

    def has_results(self, image_id: int) -> bool:
        return self.db.scalar(
            "SELECT COUNT(*) FROM results WHERE image_id = ?", (image_id,)
        ) > 0

    # ── 统计 ────────────────────────────────────

    def count_images(self, root_id: Optional[int] = None, only_missing: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM images"
        where, params = [], []
        if root_id is not None:
            where.append("root_id = ?")
            params.append(root_id)
        if only_missing:
            where.append("missing = 1")
        if where:
            sql += " WHERE " + " AND ".join(where)
        return self.db.scalar(sql, tuple(params))

    def count_resolved(self, root_id: Optional[int] = None) -> int:
        """已有搜索结果的图片数"""
        sql = ("SELECT COUNT(DISTINCT i.id) FROM images i"
               " JOIN results r ON r.image_id = i.id")
        params: tuple = ()
        if root_id is not None:
            sql += " WHERE i.root_id = ?"
            params = (root_id,)
        return self.db.scalar(sql, params)

    def count_results(self, root_id: Optional[int] = None) -> int:
        sql = "SELECT COUNT(*) FROM results"
        params: tuple = ()
        if root_id is not None:
            sql = ("SELECT COUNT(*) FROM results r JOIN images i ON i.id = r.image_id"
                   " WHERE i.root_id = ?")
            params = (root_id,)
        return self.db.scalar(sql, params)


# ──────────────────────────────────────────────
#  内容指纹
# ──────────────────────────────────────────────


@dataclass
class Fingerprint:
    """一张图的内容指纹（与路径无关）"""

    dhash: str
    width: int = 0
    height: int = 0
    size: int = 0
    mtime: float = 0.0


def fingerprint_file(file_path: str) -> Fingerprint:
    """
    计算文件的内容指纹（dHash + 尺寸 + 体积）。

    **这就是图片的身份**：文件改名、移动、重新压缩都不会改变它
    （重新压缩/缩放只会让 dHash 略有变化，落在近似匹配的阈值内）。

    Raises:
        LibraryError: 文件不存在或不是可读的图片
    """
    path = Path(file_path)
    if not path.is_file():
        raise LibraryError(f"文件不存在：{file_path}")

    dhash = get_file_hash(str(path))
    if not dhash:
        raise LibraryError(f"无法读取图片内容（不是图片或已损坏）：{file_path}")

    info = get_image_info(str(path)) or {}
    stat = path.stat()
    return Fingerprint(
        dhash=dhash,
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        size=stat.st_size,
        mtime=stat.st_mtime,
    )
