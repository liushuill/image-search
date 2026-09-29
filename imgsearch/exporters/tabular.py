"""
CSV 表格

列名尽量沿用旧版的命名（file / status / source / ext_url …），
以免既有的表格与脚本失效；新列都是追加的。

两处刻意的取舍：
  · ``similarity`` 存**数值**而不是 ``"12.3%"`` —— 否则 Excel 里没法排序
    （旧版两个写入路径一个存数值一个存字符串，这里统一）
  · ``extra_ids`` 用 ``k=v; k=v`` 而不是 JSON —— 便于在表格里直接看
    （JSON/JSONL 格式里仍然是结构化对象）
"""

import csv
import io
from typing import Sequence

from imgsearch.exporters.base import ExportRecord, Format, register

COLUMNS = [
    "file", "dhash", "status", "source", "similarity",
    "pixiv_id", "pixiv_page", "pixiv_image_id",
    "artist", "artist_id", "title", "material",
    "ext_url", "all_urls", "highres_url",
    "danbooru_id", "gelbooru_id", "twitter_id", "extra_ids",
    "detail", "searched_at", "cached",
]


def record_to_row(r: ExportRecord) -> dict:
    return {
        "file": r.file,
        "dhash": r.dhash,
        "status": r.status,
        "source": r.engine,
        "similarity": f"{r.similarity:.2f}".rstrip("0").rstrip(".") if r.similarity else "",
        "pixiv_id": r.pixiv_id,
        "pixiv_page": r.pixiv_page if r.pixiv_id else "",
        "pixiv_image_id": r.pixiv_filename,
        "artist": r.artist,
        "artist_id": r.artist_id,
        "title": r.title,
        "material": r.material,
        "ext_url": r.all_urls[0] if r.all_urls else "",
        "all_urls": " | ".join(r.all_urls),
        "highres_url": r.highres_url,
        "danbooru_id": r.ids.get("danbooru", ""),
        "gelbooru_id": r.ids.get("gelbooru", ""),
        "twitter_id": r.ids.get("twitter", ""),
        "extra_ids": "; ".join(f"{k}={v}" for k, v in r.ids.items()
                              if k not in ("danbooru", "gelbooru", "twitter")),
        "detail": r.detail,
        "searched_at": r.searched_at,
        "cached": "是" if r.from_cache else "",
    }


def render(records: Sequence[ExportRecord], **_) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(record_to_row(r))
    return buf.getvalue()


register(Format(
    key="csv", label="CSV 表格", ext="csv", render=render,
    help="便于 Excel 查看与二次处理；similarity 是数值，可直接排序",
))
