"""
导出层 —— 数据模型、模板与格式注册表

设计：把「结果」先摊平成与界面无关的 :class:`ExportRecord`，各格式只负责
把记录渲染成文本/字节。好处：

- 格式实现是**纯函数**（记录 → 字符串），因此极易测试
- 同一次导出可以一次产出多个格式，彼此不会读到不一致的数据
- 「复制到剪贴板」复用 url 渲染器，不必再写一份

导出**不下载任何文件**，只输出地址（按用户要求）。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Sequence

# ──────────────────────────────────────────────
#  统一记录
# ──────────────────────────────────────────────


@dataclass
class ExportRecord:
    """
    一行导出数据。

    刻意用「摊平」的字段而不是嵌套 SearchResult —— CSV/表格/报告都按行处理，
    摊平后再给各格式用最省事；转换只在 :mod:`imgsearch.exporters.collect` 里做一次。
    """

    file: str = ""                       # 原图路径（本地）
    dhash: str = ""                      # 内容指纹（图库身份）
    status: str = "success"              # success / no_match / error / cached
    engine: str = ""                     # 命中的引擎
    similarity: float = 0.0
    pixiv_id: str = ""
    pixiv_page: int = 0
    artist: str = ""
    artist_id: str = ""
    title: str = ""
    material: str = ""
    urls: List[str] = field(default_factory=list)     # 全部来源链接（去重）
    highres_url: str = ""
    thumbnail: str = ""                  # 远程缩略图地址（本地缓存缺失时的兜底）
    ids: Dict[str, str] = field(default_factory=dict)  # 各站点 ID
    detail: str = ""
    searched_at: str = ""
    from_cache: bool = False             # 结果是否来自图库缓存

    # ── 派生 ────────────────────────────────────

    @property
    def pixiv_filename(self) -> str:
        """如 74267012_p0.jpg"""
        if not self.pixiv_id:
            return ""
        return f"{self.pixiv_id}_p{self.pixiv_page}.jpg"

    @property
    def pixiv_page_url(self) -> str:
        return f"https://www.pixiv.net/artworks/{self.pixiv_id}" if self.pixiv_id else ""

    @property
    def all_urls(self) -> List[str]:
        """Pixiv 作品页 + 全部来源，去重且保持顺序"""
        seen, out = set(), []
        for url in ([self.pixiv_page_url] if self.pixiv_id else []) + list(self.urls):
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out

    @property
    def ids_text(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.ids.items())

    @property
    def title_text(self) -> str:
        return " / ".join(x for x in (self.title, self.material) if x)

    def template_values(self) -> Dict[str, str]:
        """文件名模板可用到的占位符"""
        return {
            "pixiv_id": self.pixiv_id or "",
            "page": str(self.pixiv_page or 0),
            "artist": self.artist or "",
            "title": self.title or self.material or "",
            "similarity": f"{self.similarity:.1f}",
            "engine": self.engine or "",
            "dhash": self.dhash or "",
            "file": Path(self.file).stem if self.file else "",
            "ext": "jpg",
        }


# ──────────────────────────────────────────────
#  文件名模板
# ──────────────────────────────────────────────

DEFAULT_NAME_TEMPLATE = "{pixiv_id}_p{page}.{ext}"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    清理文件名中的非法字符。

    同时覆盖 Windows 与 POSIX 的非法集（Windows 更严），
    并去掉结尾的点与空格（Windows 上会静默丢失）。
    """
    cleaned = _ILLEGAL.sub(replacement, name or "")
    # 合并连续的替换符，避免 "<>:" 变成 "___" 这种没意义的文件名
    cleaned = re.sub(re.escape(replacement) + r"+", replacement, cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    # 全是替换符 = 原始名字没有任何可用字符
    if not cleaned or set(cleaned) <= {replacement}:
        return "untitled"
    return cleaned


def render_name(template: str, record: ExportRecord,
                need_ext: bool = True) -> str:
    """
    按模板生成文件名（不含目录）。

    模板里未知的占位符原样保留 —— 静默丢字段比留个 ``{unknown}`` 更难排查。
    """
    template = template or DEFAULT_NAME_TEMPLATE
    values = record.template_values()
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    if need_ext:
        out = out.replace("{ext}", values["ext"])
    return sanitize_filename(out)


# ──────────────────────────────────────────────
#  格式注册表
# ──────────────────────────────────────────────


@dataclass(frozen=True)
class Format:
    """一种导出格式"""

    key: str
    label: str
    ext: str
    render: Callable[..., str]
    binary: bool = False
    # 虚拟格式：有渲染结果但不写成文件（如「复制到剪贴板」）
    virtual: bool = False
    help: str = ""


_REGISTRY: Dict[str, Format] = {}
_ORDER: List[str] = []


def register(fmt: Format) -> Format:
    """注册一种格式（由各格式模块在导入时调用）"""
    if fmt.key not in _REGISTRY:
        _ORDER.append(fmt.key)
    _REGISTRY[fmt.key] = fmt
    return fmt


def get(key: str) -> Format:
    if key not in _REGISTRY:
        raise KeyError(f"未知导出格式：{key}（可用：{', '.join(_ORDER)}）")
    return _REGISTRY[key]


def all_formats() -> List[Format]:
    """按注册顺序返回全部格式（CLI 与 GUI 的勾选项都来自这里）"""
    return [_REGISTRY[k] for k in _ORDER]


def format_keys() -> List[str]:
    return list(_ORDER)


def parse_format_list(text: str) -> List[Format]:
    """
    解析 ``urls,csv`` 这样的格式列表。

    Raises:
        ValueError: 含未知格式（消息里列出可用项）
    """
    keys = [k.strip().lower() for k in re.split(r"[,\s]+", text or "") if k.strip()]
    if not keys:
        raise ValueError("没有指定导出格式")
    if "all" in keys:
        return all_formats()
    out = []
    for key in keys:
        if key not in _REGISTRY:
            raise ValueError(
                f"未知导出格式：{key}（可用：{', '.join(_ORDER)}, all）"
            )
        out.append(_REGISTRY[key])
    return out


def write_outputs(formats: Sequence[Format], records: Sequence[ExportRecord],
                  outdir: Path, stem: str = "image-search",
                  name_template: str = "", **options) -> List[Path]:
    """
    把记录渲染成多个文件（一次产出多种格式）。

    Returns:
        实际写入的文件路径
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    for fmt in formats:
        if fmt.virtual:
            continue
        path = outdir / f"{stem}.{fmt.ext}"
        text = fmt.render(records, name_template=name_template, **options)
        if fmt.binary:
            path.write_bytes(text)                     # type: ignore[arg-type]
        else:
            # utf-8-sig 让 Excel 正确识别中文；其余格式用普通 utf-8
            encoding = "utf-8-sig" if fmt.ext == "csv" else "utf-8"
            path.write_text(text, encoding=encoding, newline="")  # type: ignore[arg-type]
        written.append(path)
    return written
