"""
HTML 缩略图墙报告

- **单文件、可离线打开**：缩略图默认以 base64 内嵌，因此把 .html 发给别人也能看
  （``thumbnails="link"`` 则改用远程地址，适合结果很多、不想让文件变大的场景）
- 纯内联 CSS + 十几行原生 JS（带一个筛选框），不依赖任何外部资源
- ⚠️ 所有来自外部的文本（画师名、标题、路径）都经过 HTML 转义 ——
  它们来自第三方接口，直接拼进 HTML 会破坏页面结构

导出**不下载原图**，只给出链接。
"""

import base64
import html
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional, Sequence

from imgsearch.exporters.base import ExportRecord, Format, register

# 内嵌缩略图的体积上限（单张）。超过就退回远程地址，避免报告变成几十 MB。
MAX_EMBED_BYTES = 400 * 1024


def _local_thumb(record: ExportRecord) -> Optional[Path]:
    """找到（必要时生成）该记录的本地缩略图"""
    if not record.dhash:
        return None
    from imgsearch.library import thumbs

    if thumbs.exists(record.dhash):
        return thumbs.path_for(record.dhash)
    if record.file and Path(record.file).is_file():
        return thumbs.ensure(record.dhash, record.file)
    return None


def _img_src(record: ExportRecord, mode: str) -> str:
    if mode == "none":
        return ""
    if mode in ("embed", "auto"):
        path = _local_thumb(record)
        if path is not None:
            try:
                data = path.read_bytes()
                if len(data) <= MAX_EMBED_BYTES:
                    return ("data:image/jpeg;base64,"
                            + base64.b64encode(data).decode("ascii"))
            except OSError:
                pass
    return record.thumbnail or ""


def _badge_class(similarity: float) -> str:
    if similarity >= 85:
        return "hi"
    if similarity >= 60:
        return "mid"
    return "lo"


def _card(record: ExportRecord, index: int, mode: str) -> str:
    e = html.escape
    src = _img_src(record, mode)

    thumb_html = (
        f'<img loading="lazy" src="{src}" alt="">' if src
        else '<div class="noimg">无缩略图</div>'
    )

    rows: List[str] = []
    if record.artist:
        rows.append(f'<div class="row"><b>画师</b>{e(record.artist)}</div>')
    if record.title_text:
        rows.append(f'<div class="row"><b>标题</b>{e(record.title_text)}</div>')
    if record.ids:
        rows.append(f'<div class="row"><b>站点</b>{e(record.ids_text)}</div>')
    if record.detail:
        rows.append(f'<div class="row"><b>备注</b>{e(record.detail)}</div>')

    links = []
    for url in record.all_urls[:6]:
        label = "Pixiv 作品页" if "pixiv.net/artworks" in url else _short_host(url)
        links.append(f'<a href="{e(url)}" target="_blank" rel="noreferrer">{e(label)}</a>')
    if record.highres_url:
        links.append(f'<a href="{e(record.highres_url)}" target="_blank" '
                     f'rel="noreferrer">高清直链</a>')

    file_line = ""
    if record.file:
        file_line = f'<div class="file" title="{e(record.file)}">{e(Path(record.file).name)}</div>'

    search_text = e(" ".join(filter(None, [
        record.artist, record.title_text, record.ids_text, record.file, record.dhash,
    ]))).lower()

    return f'''<article class="card" data-search="{search_text}">
  <div class="thumb">{thumb_html}<span class="sim {_badge_class(record.similarity)}">{record.similarity:.0f}%</span></div>
  <div class="body">
    <div class="engine">{e(record.engine or "—")}{"　· 缓存" if record.from_cache else ""}</div>
    {''.join(rows)}
    {file_line}
    <div class="links">{''.join(links) or '<span class="muted">无链接</span>'}</div>
  </div>
</article>'''


def _short_host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url


_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px;background:#f9fafb;color:#111827;
     font:14px/1.5 -apple-system,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#6b7280;font-size:13px;margin-bottom:16px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
.stat{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;font-size:13px}
.stat b{display:block;font-size:18px}
#q{width:100%;max-width:380px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:6px;
   margin-bottom:16px;font-size:14px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;
      display:flex;flex-direction:column}
.thumb{position:relative;background:#0f172a;aspect-ratio:4/3;display:flex;
       align-items:center;justify-content:center}
.thumb img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.noimg{color:#64748b;font-size:12px}
.sim{position:absolute;top:8px;right:8px;padding:2px 7px;border-radius:999px;
     font-size:12px;font-weight:600;color:#fff}
.sim.hi{background:#16a34a}.sim.mid{background:#d97706}.sim.lo{background:#6b7280}
.body{padding:10px 12px;display:flex;flex-direction:column;gap:5px}
.engine{font-size:12px;color:#6b7280}
.row{font-size:13px;word-break:break-word}
.row b{color:#6b7280;font-weight:600;margin-right:6px;font-size:12px}
.file{font-size:11px;color:#9ca3af;word-break:break-all}
.links{display:flex;flex-wrap:wrap;gap:8px;margin-top:2px}
.links a{color:#3b82f6;text-decoration:none;font-size:12px}
.links a:hover{text-decoration:underline}
.muted{color:#9ca3af;font-size:12px}
footer{margin-top:24px;color:#9ca3af;font-size:12px}
"""

_JS = """
const q=document.getElementById('q');
q.addEventListener('input',()=>{
  const t=q.value.trim().toLowerCase();
  document.querySelectorAll('.card').forEach(c=>{
    c.style.display = !t || c.dataset.search.includes(t) ? '' : 'none';
  });
});
"""


def render(records: Sequence[ExportRecord], *, thumbnails: str = "embed",
           title: str = "图片溯源结果", **_) -> str:
    e = html.escape
    by_engine = Counter(r.engine or "未知" for r in records)
    with_pixiv = sum(1 for r in records if r.pixiv_id)

    stats = [
        ("结果条数", str(len(records))),
        ("含 Pixiv", str(with_pixiv)),
    ]
    stats += [(name, str(count)) for name, count in by_engine.most_common(6)]

    cards = "\n".join(_card(r, i, thumbnails) for i, r in enumerate(records, 1))
    generated = time.strftime("%Y-%m-%d %H:%M")

    if not records:
        cards = '<p class="muted">没有可导出的结果。</p>'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{e(title)}</h1>
<div class="sub">生成于 {generated}　·　共 {len(records)} 条结果</div>
<div class="stats">
{''.join(f'<div class="stat"><b>{e(v)}</b>{e(k)}</div>' for k, v in stats)}
</div>
<input id="q" type="search" placeholder="筛选：画师 / 标题 / 站点 ID / 文件名 / dHash">
<div class="grid">
{cards}
</div>
<footer>由 image-search 生成　·　点击链接可跳转到来源页面（需要联网）</footer>
<script>{_JS}</script>
</body>
</html>
'''


register(Format(
    key="html", label="HTML 缩略图墙报告", ext="html", render=render,
    help="单文件、可离线打开；缩略图默认内嵌，因此发给别人也能看",
))
