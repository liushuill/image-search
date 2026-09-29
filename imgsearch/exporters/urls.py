"""纯 URL 列表（一行一个）—— 最通用的兜底格式，可直接喂给 AriaNg 等"""

from typing import Sequence

from imgsearch.exporters.base import ExportRecord, Format, register


def render(records: Sequence[ExportRecord], **_) -> str:
    lines = []
    for record in records:
        lines.extend(record.all_urls)
    return "\n".join(lines) + ("\n" if lines else "")


register(Format(
    key="urls", label="URL 列表（一行一个）", ext="txt", render=render,
    help="最通用：AriaNg / aria2c -i / IDM 的批量导入都能吃",
))
