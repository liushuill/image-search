"""
导出子命令的 CLI

单独成模块，避免 :mod:`imgsearch.cli` 继续膨胀；由 cli.py 注册进来。
"""

import time
from pathlib import Path
from typing import List, Optional, Sequence

from imgsearch.config import OUTPUT_DIR
from imgsearch.exporters import (
    ExportRecord,
    all_formats,
    format_keys,
    from_csv,
    from_library,
    parse_format_list,
    write_outputs,
)
from imgsearch.exporters.clipboard_format import copy_to_clipboard


def add_parser(subparsers) -> None:
    """注册 ``export`` 子命令"""
    p = subparsers.add_parser(
        "export",
        help="把结果导出成多种格式（URL 列表 / CSV / JSON / HTML 报告 / 剪贴板）",
        description=(
            "导出**不下载任何文件**，只输出地址。可一次勾选多种格式。\n"
            "数据来源：本地图库（已经搜过的）或一个 CSV 文件。"
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--library", nargs="?", const="", metavar="根路径id",
                     help="从本地图库导出；可跟一个已登记根路径的 id 限定范围")
    src.add_argument("--csv", metavar="文件", help="从 CSV 导出（兼容旧版 batch 的列名）")

    p.add_argument(
        "--formats", "-f", default="all",
        help=f"要产出哪些格式，逗号分隔（默认 all）。可用：{', '.join(format_keys())}",
    )
    p.add_argument("--outdir", "-o", default=None,
                   help="输出目录（默认 output/）")
    p.add_argument("--stem", default=None,
                   help="输出文件名前缀（默认按时间戳生成，避免互相覆盖）")
    p.add_argument(
        "--name-template", default=None,
        help="文件名模板，占位符：{pixiv_id} {page} {artist} {title} "
             "{similarity} {engine} {dhash} {file} {ext}",
    )
    p.add_argument("--thumbnails", choices=["embed", "link", "none"], default="embed",
                   help="HTML 报告里的缩略图：embed 内嵌（单文件可离线看，默认）"
                        "/ link 用远程地址 / none 不显示")
    p.add_argument("--per-result", action="store_true",
                   help="每张图的每条结果各占一行（默认每张图一行，取最佳结果）")
    p.add_argument("--limit", type=int, default=None, help="最多导出多少张图")
    p.add_argument("--id-column", default="pixiv_id", help="CSV 里 Pixiv ID 的列名")
    p.add_argument("--page-column", default="pixiv_page", help="CSV 里页码的列名")


# ──────────────────────────────────────────────
#  共同实现（search --export 也用它）
# ──────────────────────────────────────────────


def export_records(records: Sequence[ExportRecord], formats_text: str,
                   *, outdir=None, stem: Optional[str] = None,
                   name_template: Optional[str] = None,
                   thumbnails: str = "embed"):
    """
    渲染并写出所选格式。

    **刻意不做 UI 相关的事**（不设置剪贴板、不打印），
    这样 CLI 与 GUI 都能用同一段逻辑，只是后续处理不同。

    Returns:
        ``(写入的文件路径列表, 剪贴板文本或 "")``
    """
    formats = parse_format_list(formats_text)
    out_dir = Path(outdir) if outdir else Path(OUTPUT_DIR)
    stem = stem or time.strftime("image-search-%Y%m%d-%H%M%S")

    written = write_outputs(formats, records, out_dir, stem=stem,
                            name_template=name_template or "",
                            thumbnails=thumbnails)

    clipboard_text = ""
    for fmt in formats:
        if fmt.key == "clipboard":
            clipboard_text = fmt.render(records)

    return written, clipboard_text


def _handle_clipboard(text: str) -> None:
    """CLI 场景下把文本放进系统剪贴板；没有工具就打印出来"""
    if copy_to_clipboard(text):
        print("  📋 已复制到系统剪贴板")
        return
    print("  📋 没有可用的剪贴板工具（wl-copy / xclip / xsel / clip）")
    print("     以下内容可直接复制：")
    print("-" * 50)
    print(text.rstrip())
    print("-" * 50)


def _print_written(written: Sequence[Path]) -> None:
    if not written:
        return
    print(f"\n✅ 已导出 {len(written)} 个文件：")
    for path in written:
        try:
            size = path.stat().st_size
            size_text = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        except OSError:
            size_text = "?"
        print(f"     {path}　（{size_text}）")


def _format_help() -> str:
    lines = []
    for fmt in all_formats():
        tag = "（不写文件）" if fmt.virtual else f".{fmt.ext}"
        lines.append(f"     {fmt.key:<10} {tag:<14} {fmt.label}")
    return "\n".join(lines)


def run(args) -> int:
    """执行 export 子命令"""
    try:
        records = _collect(args)
    except Exception as e:                                # noqa: BLE001
        print(f"❌ 收集数据失败：{type(e).__name__}: {e}")
        return 1

    if not records:
        print("📭 没有可导出的数据。")
        print("   · 图库为空时先搜索几张图：imgsearch search 图片.jpg")
        print("   · 或指定 --csv 一个已有的结果表")
        return 0

    print(f"📦 待导出 {len(records)} 条记录")
    try:
        written, clipboard_text = export_records(
            records, args.formats, outdir=args.outdir, stem=args.stem,
            name_template=args.name_template, thumbnails=args.thumbnails)
    except ValueError as e:                               # 格式名写错
        print(f"❌ {e}")
        print("\n可用格式：")
        print(_format_help())
        return 1

    _print_written(written)
    if clipboard_text:
        _handle_clipboard(clipboard_text)
    print("\n💡 导出的是**地址**，不含图片文件本身。")
    return 0


def _collect(args) -> List[ExportRecord]:
    if args.csv:
        if not Path(args.csv).is_file():
            raise FileNotFoundError(f"CSV 不存在：{args.csv}")
        print(f"📄 读取 CSV：{args.csv}")
        return from_csv(args.csv, id_column=args.id_column,
                        page_column=args.page_column)

    # --library（const="" 表示不带 id）
    from imgsearch.service import open_library
    db, store = open_library()
    if store is None:
        raise RuntimeError("图库不可用（可在「设置」页确认是否启用）")

    root_id = None
    if args.library:
        if not str(args.library).isdigit():
            raise ValueError(f"--library 需要根路径 id（数字），收到：{args.library}")
        root_id = int(args.library)
        if store.roots.get(root_id) is None:
            raise ValueError(f"未找到根路径 id={root_id}（用 `imgsearch library list` 查看）")

    scope = "全部路径" if root_id is None else f"根路径 id={root_id}"
    print(f"📚 从本地图库导出（{scope}）")
    return from_library(store, root_id=root_id, per_image=not args.per_result,
                        limit=args.limit)
