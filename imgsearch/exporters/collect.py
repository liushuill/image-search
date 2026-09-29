"""
把各种来源的数据收集成统一的 :class:`ExportRecord`

三个来源：

- **搜索结果**：刚搜完，直接导出（GUI 里勾选若干条）
- **本地图库**：把「已经搜过的」批量导出 —— 这是省配额之后的自然延伸
- **CSV**：兼容旧版 ``batch`` 产出的表格，便于沿用既有文件
"""

import csv
from typing import Any, Dict, Iterable, List, Optional, Sequence

from imgsearch.engines.base import SearchResult
from imgsearch.exporters.base import ExportRecord

# 图库 results 表里没有「引擎之外」的字段，这里集中做一次映射
_ID_KEYS = ("danbooru", "gelbooru", "twitter", "anilist", "mal", "yandere_re",
            "konachan", "sankaku", "e_shuushu", "zerochan", "anime_pictures")


def _ids_of(result: SearchResult) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    for key in _ID_KEYS:
        value = getattr(result, f"{key}_id", None) or (result.extra_ids or {}).get(key)
        if value:
            ids[key] = str(value)
    return ids


def result_to_record(result: SearchResult, *, file: str = "", dhash: str = "",
                     status: str = "success", searched_at: str = "",
                     from_cache: bool = False) -> ExportRecord:
    """单条 SearchResult → ExportRecord"""
    ids = _ids_of(result)
    return ExportRecord(
        file=file,
        dhash=dhash,
        status=status,
        engine=result.source or "",
        similarity=float(result.similarity or 0),
        pixiv_id=str(result.pixiv_id or ""),
        pixiv_page=int(result.pixiv_page or 0),
        artist=result.artist or "",
        artist_id=str(result.artist_id or ""),
        title=result.title or "",
        material=result.material or "",
        urls=list(result.ext_urls or []),
        highres_url=result.highres_url or "",
        thumbnail=result.thumbnail or "",
        ids=ids,
        detail=result.detail or "",
        searched_at=searched_at,
        from_cache=from_cache,
    )


def from_results(results: Sequence[SearchResult], *, file: str = "",
                 dhash: str = "", searched_at: str = "",
                 from_cache: bool = False) -> List[ExportRecord]:
    """一次搜索的多条结果 → 多条记录"""
    return [result_to_record(r, file=file, dhash=dhash,
                             searched_at=searched_at, from_cache=from_cache)
            for r in results]


# ──────────────────────────────────────────────
#  本地图库
# ──────────────────────────────────────────────


def from_library(store, *, root_id: Optional[int] = None,
                 only_resolved: bool = True, per_image: bool = True,
                 limit: Optional[int] = None) -> List[ExportRecord]:
    """
    从本地图库批量导出。

    Args:
        store: :class:`~imgsearch.library.store.LibraryStore`
        root_id: 只导出某条已登记路径下的（None = 全部）
        only_resolved: 只导出有搜索结果的
        per_image: True → 每张图一条记录（取相似度最高的结果，
                   但**合并全部结果里的链接**，尽量不丢信息）
                   False → 每条结果一条记录
        limit: 上限（按图片数）

    ⚠️ ``per_image`` 模式会合并链接：同一张图可能有多个来源（Pixiv / Danbooru /
    Twitter），只保留最高相似度那一条会丢掉其余的。
    """
    db = store.db
    sql = ("SELECT i.id AS image_id, i.dhash, i.abs_path, i.last_seen,"
           " r.* FROM images i JOIN results r ON r.image_id = i.id")
    where, params = [], []
    if root_id is not None:
        where.append("i.root_id = ?")
        params.append(root_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY i.id, r.similarity DESC"

    rows = db.query(sql, tuple(params))

    by_image: Dict[int, List[Any]] = {}
    order: List[int] = []
    for row in rows:
        key = row["image_id"]
        if key not in by_image:
            by_image[key] = []
            order.append(key)
        by_image[key].append(row)

    if not only_resolved:
        # 补上没有任何结果的图片
        sql2 = ("SELECT id AS image_id, dhash, abs_path, last_seen FROM images"
                " WHERE id NOT IN (SELECT image_id FROM results)")
        params2: tuple = ()
        if root_id is not None:
            sql2 += " AND root_id = ?"
            params2 = (root_id,)
        for row in db.query(sql2, params2):
            if row["image_id"] not in by_image:
                by_image[row["image_id"]] = []
                order.append(row["image_id"])

    if limit is not None:
        order = order[:limit]

    records: List[ExportRecord] = []
    for image_id in order:
        image_rows = by_image[image_id]
        if not image_rows:
            records.append(ExportRecord(status="no_match"))
            continue

        head = image_rows[0]
        base = dict(file=head["abs_path"] or "", dhash=head["dhash"] or "",
                    searched_at=head["last_seen"] or "")

        if not per_image:
            for row in image_rows:
                records.append(_lib_row(store, row, base))
            continue

        best = _lib_row(store, image_rows[0], base)
        # 合并其余结果里的链接与 ID —— 只留最高相似度那条会丢来源
        seen = set(best.urls)
        for row in image_rows[1:]:
            extra = _lib_row(store, row, base)
            for url in extra.urls:
                if url not in seen:
                    seen.add(url)
                    best.urls.append(url)
            for key, value in extra.ids.items():
                best.ids.setdefault(key, value)
        records.append(best)

    return records


def _lib_row(store, row, base: dict) -> ExportRecord:
    """
    图库 results 行 → ExportRecord。

    ⚠️ 刻意绕一圈 ``store.row_to_result()`` 而不是直接读列：
    这样导出看到的数据与「刚搜出来」的完全一致，
    包括 ``SearchResult.__post_init__`` 里那些归一化
    （比如从 ext_urls 补出缺失的 pixiv_id）。
    否则导出会变成一个"少了点东西"的平行世界。
    """
    return result_to_record(
        store.row_to_result(row), status="cached", from_cache=True, **base
    )


# ──────────────────────────────────────────────
#  CSV（兼容旧版 batch 的产出）
# ──────────────────────────────────────────────


def from_csv(path, *, id_column: str = "pixiv_id",
             page_column: str = "pixiv_page") -> List[ExportRecord]:
    """
    读取 CSV（兼容旧版 ``batch`` 的列名，缺列不影响）。

    ⚠️ 旧版 CSV 的 ``similarity`` 可能是 ``"95.2%"`` 这样的字符串，
    这里统一解析成数值。
    """
    records: List[ExportRecord] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            records.append(ExportRecord(
                file=(row.get("file") or "").strip(),
                dhash=(row.get("dhash") or "").strip(),
                status=(row.get("status") or "success").strip(),
                engine=(row.get("source") or row.get("engine") or "").strip(),
                similarity=_parse_similarity(row.get("similarity")),
                pixiv_id=(row.get(id_column) or "").strip(),
                pixiv_page=_parse_int(row.get(page_column)),
                artist=(row.get("artist") or "").strip(),
                artist_id=(row.get("artist_id") or "").strip(),
                title=(row.get("title") or "").strip(),
                material=(row.get("material") or "").strip(),
                urls=[u for u in _split_urls(row.get("all_urls")
                                             or row.get("ext_url") or "")],
                highres_url=(row.get("highres_url") or "").strip(),
                ids=_parse_ids(row),
                detail=(row.get("detail") or "").strip(),
                searched_at=(row.get("searched_at") or "").strip(),
                from_cache=(row.get("cached") or "").strip() != "",
            ))
    return records


def _parse_similarity(value) -> float:
    if not value:
        return 0.0
    text = str(value).strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _split_urls(text: str) -> Iterable[str]:
    for part in str(text or "").replace(";", " ").split("|"):
        for piece in part.split():
            piece = piece.strip()
            if piece.startswith("http"):
                yield piece


def _parse_ids(row: dict) -> Dict[str, str]:
    ids = {}
    for key in _ID_KEYS:
        value = (row.get(f"{key}_id") or "").strip()
        if value:
            ids[key] = value
    # extra_ids 列是 "k=v; k=v"
    for chunk in (row.get("extra_ids") or "").split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            if k.strip() and v.strip():
                ids.setdefault(k.strip(), v.strip())
    return ids
