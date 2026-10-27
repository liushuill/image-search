"""
图库子命令的 CLI

单独成模块，避免 :mod:`imgsearch.cli` 继续膨胀；由 cli.py 注册进来。
"""

import sys
from typing import Optional

from imgsearch.library import (
    LibraryDB,
    LibraryError,
    LibraryStore,
    PurgeOptions,
    collect_stats,
    execute_purge,
    format_bytes,
    plan_purge,
    purge_orphan_thumbs,
)
from imgsearch.library.paths import RootManager


def add_parser(subparsers) -> None:
    """注册 ``library`` 子命令"""
    p = subparsers.add_parser(
        "library",
        help="本地图库：登记图库路径、查看占用、清理持久化数据",
        description=(
            "本地图库以 dHash 内容为身份、路径只作「最后已知位置」。\n"
            "因此文件在目录间移动后，仍能认出「这张搜过了」并复用缓存结果。"
        ),
    )
    p.add_argument(
        "action",
        choices=["add", "list", "remove", "relocate", "find", "stats",
                 "clean", "forget", "refresh", "sql"],
        help="add 登记路径 | list 路径列表 | remove 移除路径 | relocate 重新指定位置 | "
             "find 查这张图搜过没 | stats 占用总览 | clean 清理 | forget 忘记某张图 | "
             "refresh 刷新文件存在状态 | sql 直接查数据库",
    )
    p.add_argument("target", nargs="?", help="路径 / 根路径 id / 图片文件")
    p.add_argument("extra", nargs="?", help="relocate 时的新路径")
    p.add_argument("--label", default="", help="别名（add 时使用）")

    # remove / clean 的清理选项
    p.add_argument("--purge", choices=["none", "results", "thumbs", "all"],
                   default=None,
                   help="remove 时顺带清理：none 仅解除登记 / results 搜索结果 / "
                        "thumbs 缩略图 / all 该路径全部数据")
    p.add_argument("--results", action="store_true", help="clean 时清理搜索结果记录")
    p.add_argument("--thumbs", action="store_true", help="clean 时清理缓存缩略图")
    p.add_argument("--images", action="store_true",
                   help="clean 时连同图片记录一起删（结果级联删除）")
    p.add_argument("--orphans", action="store_true",
                   help="clean 时清理孤立缩略图（数据库里已无对应记录）")
    p.add_argument("--yes", "-y", action="store_true", help="跳过二次确认")
    # library sql 的选项
    p.add_argument("--write", action="store_true",
                   help="sql：允许写操作（默认只读，防手滑改坏）")
    p.add_argument("--tables", action="store_true",
                   help="sql：列出所有表与行数（不需要会 SQL）")
    p.add_argument("--schema", action="store_true",
                   help="sql：列出字段定义；可跟一个表名只看那张表")
    p.add_argument("--db", default=None, help="覆盖数据库文件路径（默认 data/image_metadata.db）")


# ──────────────────────────────────────────────
#  展示辅助
# ──────────────────────────────────────────────



def _print_root_table(store: LibraryStore, db: LibraryDB) -> None:
    roots = RootManager(db).list()
    if not roots:
        print("📭 尚未登记任何图库路径")
        print("   添加：imgsearch library add /path/to/图库")
        return

    print(f"\n📚 图库路径（{len(roots)} 个）")
    print("=" * 88)
    print(f"  {'id':<4}{'状态':<8}{'图片':<8}{'已搜':<8}{'结果':<8}{'缩略':<8}路径")
    print("-" * 88)
    for root in roots:
        mark = "✅" if root.exists else "⚠️ 失效"
        images = store.count_images(root_id=root.id)
        resolved = store.count_resolved(root_id=root.id)
        results = store.count_results(root_id=root.id)
        print(f"  {root.id:<4}{mark:<8}{images:<8}{resolved:<8}{results:<8}"
              f"{'':<8}{root.display}")
        if root.label:
            print(f"      {root.path}")
    print()
    print("💡 imgsearch library stats          查看占用明细")
    print("   imgsearch library remove <id> --purge all   移除并清空该路径数据")


def _cmd_add(args, store: LibraryStore, db: LibraryDB) -> None:
    if not args.target:
        print("❌ 用法：imgsearch library add <路径> [--label 别名]")
        sys.exit(1)
    root = RootManager(db).add(args.target, label=args.label)
    print(f"✅ 已登记图库路径：{root.display}")
    if not root.exists:
        print("   ⚠️ 该路径当前不存在（外接盘未挂载？）。记录仍会保留，")
        print("      等它可用后可用 `library refresh` 重新检查。")


def _cmd_list(args, store: LibraryStore, db: LibraryDB) -> None:
    _print_root_table(store, db)


def _cmd_remove(args, store: LibraryStore, db: LibraryDB) -> None:
    if not args.target:
        print("❌ 用法：imgsearch library remove <路径|id> [--purge none|results|thumbs|all]")
        sys.exit(1)
    roots = RootManager(db)
    root = roots.get(int(args.target)) if args.target.isdigit() else roots.get(args.target)
    if root is None:
        print(f"❌ 未找到该图库路径：{args.target}")
        sys.exit(1)

    purge = args.purge or "none"
    if purge != "none":
        options = _options_for(purge, root.id)
        plan = plan_purge(db, store, options)
        print(plan.describe())
        if not args.yes and not _confirm():
            print("已取消（路径未移除）")
            return
        result = execute_purge(db, store, options)
        roots.remove(root.id)
        print(f"✅ 已移除图库路径并清理：{root.display}")
        print(result.describe())
    else:
        if not args.yes and not _confirm(
            f"仅解除登记、保留 {store.count_images(root_id=root.id)} 条图片记录，继续？"
        ):
            print("已取消")
            return
        roots.remove(root.id)
        print(f"✅ 已移除图库路径：{root.display}（持久化数据保留）")
        print("   如需清理：imgsearch library clean --path "
              f"{root.id} --images --thumbs")


def _options_for(purge: str, root_id: Optional[int]) -> PurgeOptions:
    if purge == "results":
        return PurgeOptions(root_id=root_id, results=True)
    if purge == "thumbs":
        return PurgeOptions(root_id=root_id, thumbs=True)
    if purge == "all":
        return PurgeOptions(root_id=root_id, images=True, thumbs=True)
    return PurgeOptions(root_id=root_id)


def _cmd_relocate(args, store: LibraryStore, db: LibraryDB) -> None:
    if not args.target or not args.extra:
        print("❌ 用法：imgsearch library relocate <id> <新路径>")
        sys.exit(1)
    updated = RootManager(db).relocate(int(args.target), args.extra)
    print(f"✅ 已把根路径 {args.target} 指向：{args.extra}")
    print(f"   顺带改写了 {updated} 条记录的路径（无需重新扫描）")


def _cmd_find(args, store: LibraryStore, db: LibraryDB) -> None:
    if not args.target:
        print("❌ 用法：imgsearch library find <图片文件>")
        sys.exit(1)
    try:
        match = store.lookup(args.target)
    except LibraryError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if match is None:
        print("🔍 图库里没有这张图（按内容比对的，与文件名/路径无关）")
        print("   用 `imgsearch search <图片>` 搜索后会记入图库")
        return

    rec = match.record
    kind = {"exact": "同一张", "scaled": "同一张（不同尺寸版本）",
            "similar": "视觉相近（需人工确认）"}[match.kind]
    print(f"\n✅ 图库里有这张图 · 判定：{kind}"
          + (f"（dHash 距离 {match.distance}）" if match.distance else ""))
    print(f"   记录 id     : {rec.id}")
    print(f"   dHash       : {rec.dhash}")
    print(f"   尺寸        : {rec.dimensions or '未知'}")
    print(f"   首次入库    : {rec.first_seen}")
    print(f"   最后见到    : {rec.last_seen}")
    print(f"   最后已知位置: {rec.abs_path}" + ("   ⚠️ 文件已不在此处" if rec.missing else ""))
    if not rec.exists and not rec.missing:
        print("                 ⚠️ 文件已不在该位置（可能被移动了）")

    if store.has_results(rec.id):
        print()
        print("── 缓存的搜索结果（可直接复用，不消耗配额）──")
        from imgsearch.cli import print_results
        print_results(store.load_results(rec.id))
    else:
        print("\n   （该图还没有搜索结果）")


def _cmd_stats(args, store: LibraryStore, db: LibraryDB) -> None:
    stats = collect_stats(db, store)
    print("\n📊 图库占用总览")
    print("=" * 72)
    print(f"  图片记录    : {stats.images} 条（其中 {stats.resolved} 条已有结果，"
          f"{stats.missing} 条文件已不在原位置）")
    print(f"  搜索结果    : {stats.results} 条")
    print(f"  数据库文件  : {format_bytes(stats.db_bytes)}")
    print(f"  缩略图缓存  : {stats.thumbs_total} 个，{format_bytes(stats.thumbs_bytes)}"
          + (f"（含孤立 {stats.orphan_thumbs} 个 / {format_bytes(stats.orphan_thumbs_bytes)}）"
             if stats.orphan_thumbs else ""))
    print(f"  合计占用    : {format_bytes(stats.total_bytes)}")

    if stats.roots:
        print()
        print(f"  {'id':<4}{'状态':<8}{'图片':<8}{'已搜':<8}{'结果':<8}{'缩略图':<10}路径")
        print("  " + "-" * 76)
        for rs in stats.roots:
            mark = "✅" if rs.root.exists else "⚠️ 失效"
            print(f"  {rs.root.id:<4}{mark:<8}{rs.images:<8}{rs.resolved:<8}"
                  f"{rs.results:<8}{rs.thumbs:<10}{rs.root.display}")
    print()
    print("💡 清理：imgsearch library clean --path <id> --images --thumbs")
    print("   （删除后会自动 VACUUM 回收数据库文件空间）")
    if stats.orphan_thumbs:
        print("   孤立缩略图：imgsearch library clean --orphans")


def _cmd_clean(args, store: LibraryStore, db: LibraryDB) -> None:
    if args.orphans:
        if not args.yes and not _confirm("清理孤立缩略图？"):
            print("已取消")
            return
        removed = purge_orphan_thumbs(db)
        print(f"✅ 已清理孤立缩略图：{removed} 个")
        return

    root_id = int(args.target) if (args.target and args.target.isdigit()) else None
    if args.target and root_id is None:
        root = RootManager(db).get(args.target)
        root_id = root.id if root else None
        if root is None:
            print(f"❌ 未找到该图库路径：{args.target}")
            sys.exit(1)

    options = PurgeOptions(
        root_id=root_id,
        results=args.results or args.images,
        thumbs=args.thumbs,
        images=args.images,
    )
    if options.is_empty():
        print("❌ 请指定清理内容：--results / --thumbs / --images / --orphans")
        print("   例：imgsearch library clean --path 3 --images --thumbs")
        sys.exit(1)

    plan = plan_purge(db, store, options)
    print()
    print(plan.describe())
    print()
    if not args.yes and not _confirm("确认执行？"):
        print("已取消")
        return

    result = execute_purge(db, store, options)
    print("✅ 清理完成")
    print(result.describe())


def _cmd_forget(args, store: LibraryStore, db: LibraryDB) -> None:
    """忘记某张图的记录（按内容找，然后删）"""
    if not args.target:
        print("❌ 用法：imgsearch library forget <图片文件>")
        sys.exit(1)
    try:
        match = store.lookup(args.target)
    except LibraryError as e:
        print(f"❌ {e}")
        sys.exit(1)
    if match is None:
        print("🔍 图库里没有这张图")
        return
    rec = match.record
    if not args.yes and not _confirm(f"删除记录 id={rec.id} 及其搜索结果？"):
        print("已取消")
        return
    from imgsearch.library import thumbs
    thumbs.remove(rec.dhash)
    with db.transaction():
        db.conn.execute("DELETE FROM images WHERE id = ?", (rec.id,))
    print(f"✅ 已忘记该图（id={rec.id}）")


def _cmd_refresh(args, store: LibraryStore, db: LibraryDB) -> None:
    root_id = int(args.target) if (args.target and args.target.isdigit()) else None
    missing = RootManager(db).refresh_missing(root_id)
    print(f"✅ 已重新检查文件状态：{missing} 条记录的文件已不在最后已知位置")
    print("   （记录未删除 —— 仍可凭 dHash 命中缓存；可用 relocate 指定新位置）")


def _confirm(question: str = "确认执行？") -> bool:
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


# ──────────────────────────────────────────────
#  library sql —— 直接查数据库
# ──────────────────────────────────────────────

# 只读模式下允许的语句开头（防止手滑改坏数据）
_READ_ONLY_OK = ("select", "with", "explain", "pragma", "values")

_SQL_CHEATSHEET = """可用表：
  images   —— 图片记录（身份是 dhash，路径只是「最后已知位置」）
  results  —— 每条搜索命中（引擎 / 相似度 / Pixiv ID / 画师 / 链接）
  roots    —— 你登记的图库根路径
  meta     —— 内部元信息（schema 版本）

常用查询（直接照抄，把中文说明删掉即可）：
  # 有哪些图片已经有出处了
  SELECT i.dhash, r.pixiv_id, r.artist, ROUND(r.similarity,1) AS 相似度, i.abs_path
  FROM results r JOIN images i ON i.id = r.image_id
  WHERE r.pixiv_id IS NOT NULL ORDER BY r.similarity DESC;

  # 按站点统计命中数
  SELECT engine, COUNT(*) AS 条数, ROUND(AVG(similarity),1) AS 平均相似度
  FROM results GROUP BY engine ORDER BY 条数 DESC;

  # 按画师统计
  SELECT artist, COUNT(*) AS 张数 FROM results
  WHERE artist IS NOT NULL GROUP BY artist ORDER BY 张数 DESC LIMIT 20;

  # 还没搜出结果的图片
  SELECT dhash, abs_path FROM images
  WHERE id NOT IN (SELECT image_id FROM results);

  # 文件已不在原位置（被移动过）的记录
  SELECT dhash, abs_path FROM images WHERE missing = 1;

用法：
  imgsearch library sql --tables          列出表与行数
  imgsearch library sql --schema          列出字段定义
  imgsearch library sql "SELECT ..."      执行查询（默认只读）
  imgsearch library sql --write "UPDATE ..."   允许写操作
"""


def _display_width(text: str) -> int:
    """
    按终端显示宽度算长度：中文/日文是全角，占 2 列。

    不然中文列会错位 —— 这类工具最容易让人一眼看出「没做细」。
    """
    import unicodedata
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - _display_width(text))


def _print_rows(columns, rows, limit: int = 200) -> None:
    """打印成对齐的表格"""
    if not columns:
        print("（该语句没有返回结果集）")
        return
    if not rows:
        print("（0 行）")
        return

    cells = [[("" if v is None else str(v)) for v in tuple(r)] for r in rows[:limit]]
    widths = [max(_display_width(c), *( _display_width(r[i]) for r in cells ))
              for i, c in enumerate(columns)]

    print("  " + "  ".join(_pad(c, widths[i]) for i, c in enumerate(columns)))
    print("  " + "  ".join("-" * widths[i] for i in range(len(columns))))
    for r in cells:
        print("  " + "  ".join(_pad(r[i], widths[i]) for i in range(len(columns))))
    if len(rows) > limit:
        print(f"  …（共 {len(rows)} 行，只显示前 {limit} 行；可用 LIMIT 收窄）")


def _cmd_sql(args, store: LibraryStore, db: LibraryDB) -> None:
    # ① --tables：列出表与行数
    if args.tables:
        names = [r["name"] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = [(n, db.scalar(f"SELECT COUNT(*) FROM {n}")) for n in names]
        _print_rows(["表", "行数"], rows)
        print("\n  💡 看字段：imgsearch library sql --schema <表名>")
        print("     直接查：imgsearch library sql \"SELECT * FROM images LIMIT 5\"")
        return

    # ② --schema：列出字段定义
    if args.schema:
        target = (args.target or "").strip()
        sql = ("SELECT name, sql FROM sqlite_master WHERE type='table'"
               " AND name NOT LIKE 'sqlite_%'")
        params = ()
        if target:
            sql += " AND name = ?"
            params = (target,)
        tables = db.query(sql + " ORDER BY name", params)
        if not tables:
            print(f"❌ 没有这张表：{target}")
            return
        for t in tables:
            print(f"\n  【{t['name']}】")
            for line in (t["sql"] or "").splitlines()[1:]:
                line = line.strip().rstrip(",")
                if line and not line.startswith(")"):
                    print(f"    {line}")
        return

    # ③ 没给 SQL 也没给选项 → 速查
    statement = (args.target or "").strip()
    if not statement:
        print(_SQL_CHEATSHEET)
        return

    readonly = not args.write
    head = statement.lstrip("( 	").lower()
    if readonly and not head.startswith(_READ_ONLY_OK):
        print("❌ 默认只读：这条语句看起来会修改数据。")
        print("   如果确实要改，加上 --write：")
        print(f'     imgsearch library sql --write "{statement[:60]}..."')
        sys.exit(1)

    if ";" in statement.rstrip().rstrip(";"):
        if readonly:
            print("❌ 默认只读模式下只接受单条语句。")
            sys.exit(1)
        print("  ⚠️ 将按多语句执行（--write 已开启）")
        with db.transaction():
            db.conn.executescript(statement)
        print("✅ 已执行")
        return

    if readonly:
        # 双保险：即使语句被绕过筛查，SQLite 也拒绝写
        db.conn.execute("PRAGMA query_only = ON")

    try:
        cur = db.conn.execute(statement)
    except Exception as e:                                # noqa: BLE001
        print(f"❌ SQL 执行失败：{type(e).__name__}: {e}")
        sys.exit(1)

    if cur.description:
        _print_rows([d[0] for d in cur.description], cur.fetchall())
    else:
        print(f"✅ 已执行（影响 {cur.rowcount} 行）")


def run(args, store: LibraryStore, db: LibraryDB) -> None:
    """执行 library 子命令（store/db 由 cli.py 传入，保证同一连接）"""
    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "remove": _cmd_remove,
        "relocate": _cmd_relocate,
        "find": _cmd_find,
        "stats": _cmd_stats,
        "clean": _cmd_clean,
        "forget": _cmd_forget,
        "refresh": _cmd_refresh,
        "sql": _cmd_sql,
    }
    handlers[args.action](args, store, db)
