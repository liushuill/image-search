"""结构化格式：JSON（整齐数组）与 JSONL（一行一条，便于流式处理）"""

import json
from typing import Any, Dict, List, Sequence

from imgsearch.exporters.base import ExportRecord, Format, register


def record_to_dict(r: ExportRecord) -> Dict[str, Any]:
    """结构化表示：字段完整、容器保持原形（不像 CSV 那样摊成字符串）"""
    return {
        "file": r.file,
        "dhash": r.dhash,
        "status": r.status,
        "engine": r.engine,
        "similarity": round(r.similarity, 2),
        "pixiv": {
            "id": r.pixiv_id,
            "page": r.pixiv_page,
            "filename": r.pixiv_filename,
            "page_url": r.pixiv_page_url,
        },
        "artist": r.artist,
        "artist_id": r.artist_id,
        "title": r.title,
        "material": r.material,
        "urls": r.all_urls,
        "highres_url": r.highres_url,
        "ids": r.ids,
        "detail": r.detail,
        "searched_at": r.searched_at,
        "from_cache": r.from_cache,
    }


def render(records: Sequence[ExportRecord], **_) -> str:
    payload: List[Dict[str, Any]] = [record_to_dict(r) for r in records]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_jsonl(records: Sequence[ExportRecord], **_) -> str:
    lines = [json.dumps(record_to_dict(r), ensure_ascii=False) for r in records]
    return "\n".join(lines) + ("\n" if lines else "")


register(Format(
    key="json", label="JSON（数组）", ext="json", render=render,
    help="字段完整、容器保持结构；适合脚本消费",
))
register(Format(
    key="jsonl", label="JSONL（一行一条）", ext="jsonl", render=render_jsonl,
    help="流式处理友好，大结果集不必一次读进内存",
))
