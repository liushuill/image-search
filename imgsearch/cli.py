"""
二次元图片溯源工具

功能:
  - 以图搜图，查找图片来源（Pixiv/Danbooru/Twitter 等）
  - 搜索并生成 Pixiv 图片链接
  - 从 CSV 导出 Pixiv URL
  - 批量处理整个目录
  - 自定义搜索引擎及顺序

使用:
  imgsearch search <图片路径>               # 搜索出处
  imgsearch search <图片路径> --url         # 搜索并生成 Pixiv URL
  imgsearch search <图片路径> -e ascii2d    # 指定搜索引擎
  imgsearch export-urls <csv文件>            # 从 CSV 生成 Pixiv URL
  imgsearch batch <目录路径>                 # 批量搜索

搜索引擎管理:
  imgsearch engines list                     # 查看所有引擎及权重
  imgsearch engines add my_engine           # 添加自定义引擎
  imgsearch engines remove my_engine        # 删除自定义引擎
  imgsearch engines toggle ascii2d           # 启用/禁用引擎
  imgsearch engines move sauceNAO --down     # 向下移动引擎
  imgsearch engines move ascii2d --up        # 向上移动引擎
  imgsearch engines reset                    # 恢复默认引擎列表
  imgsearch engines config sauceNAO          # 查看引擎详细配置
  imgsearch engines config sauceNAO --api-key KEY   # 设置 API Key
  imgsearch engines config sauceNAO --api-url https://...  # 设置 API 地址
  imgsearch engines config sauceNAO --header "User-Agent:xxx"  # 自定义请求头
  imgsearch engines config sauceNAO --param "db:999"           # 自定义参数
  imgsearch engines config sauceNAO --request-delay 5.0 --timeout 60  # 超时设置

配置:
  imgsearch config set saucenao_key <KEY>  # 设置 API Key
  imgsearch config set proxy <PROXY>       # 设置代理
  imgsearch config show                    # 查看配置
"""

import io
import os
import sys

# 强制 stdout/stderr 使用 UTF-8 编码，确保中文和特殊字符正常显示
# 仅在编码不是 utf-8 时才重新包装，避免重复导入时报错
if getattr(sys.stdout, 'encoding', '').upper() != 'UTF-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if getattr(sys.stderr, 'encoding', '').upper() != 'UTF-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import csv
import json
import time
from pathlib import Path
from typing import List, Optional

# 项目以包的形式运行（python -m imgsearch），无需注入 sys.path
from imgsearch import secrets
from imgsearch.config import get, save_config, load_config, is_secret_key
from imgsearch.engines.config import (
    EngineConfig, EngineManager, _BUILTIN_ENGINES,
    resolve_engine_class, register_engine_class,
)
from imgsearch.engines.saucenao import SauceNAO
from imgsearch.engines.ascii2d import Ascii2D
from imgsearch.engines.danbooru import Danbooru
from imgsearch.links.pixiv import PixivUrlGenerator
from imgsearch.processor.image_utils import (
    SUPPORTED_FORMATS,
    is_image_file,
    get_image_info,
    get_file_hash,
)
from imgsearch.utils.network import download_file


def _print_secrets():
    """打印凭据状态（值一律脱敏）"""
    print("凭据状态 (.env / 环境变量，不落 config.json):")
    for name, configured, desc in secrets.describe():
        mark = "✅" if configured else "❌"
        print(f"  {mark} {name:<18} {secrets.masked(name):<22} {desc}")
    if not any(c for _, c, _ in secrets.describe()):
        print()
        print("  💡 初始化：cp .env.example .env && chmod 600 .env")
    print(f"  📄 文件：{secrets.ENV_FILE}")


def cmd_search(args):
    """处理 search 子命令"""
    image_path = args.path
    file_path = Path(image_path)

    if not file_path.exists():
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    if not is_image_file(image_path):
        print(f"❌ 不支持的图片格式: {image_path}")
        print(f"   支持的格式: {', '.join(sorted(SUPPORTED_FORMATS))}")
        sys.exit(1)

    # 验证引擎名称（动态 choices：通过 resolve_engine_class 解析）
    engine = args.engine
    if engine != "auto":
        mgr = EngineManager()
        ec = mgr.get_by_name(engine)
        if ec is None:
            # 即使不在配置中，尝试构造一个临时 EngineConfig 检查动态加载
            ec = EngineConfig(name=engine, enabled=True, priority=0)
        engine_cls = resolve_engine_class(ec)
        if engine_cls is None:
            known = [e.name for e in mgr.list_all()]
            print(f"❌ 未知搜索引擎: {engine}")
            print(f"   可用引擎: auto, {', '.join(sorted(set(known)))}")
            sys.exit(1)

    # 获取图片信息
    img_info = get_image_info(image_path)
    if img_info:
        print(f"📷 图片信息: {img_info['width']}x{img_info['height']}, "
              f"{img_info['format']}, {img_info['size_bytes'] / 1024:.1f} KB")

    # 计算文件哈希
    file_hash = get_file_hash(image_path)
    if file_hash:
        print(f"🔑 文件哈希: {file_hash}")

    print(f"\n🔍 正在搜索: {file_path.name}")
    print("=" * 50)

    # 搜索
    results = search_image(image_path, engine=engine)

    if not results:
        print("\n❌ 未找到匹配结果")
        sys.exit(0)

    # 显示结果
    print_results(results)

    # 生成 URL
    if args.url:
        generator = PixivUrlGenerator()
        urls = generator.generate_from_results(results)
        if urls:
            print("\n📋 生成的 Pixiv URL 列表:")
            print("-" * 50)
            for url in urls:
                print(f"  {url}")
            print("-" * 50)
            print(f"  ✅ 共 {len(urls)} 个 URL")


def cmd_batch(args):
    """处理 batch 子命令"""
    dir_path = args.directory
    dir_path = Path(dir_path)

    if not dir_path.is_dir():
        print(f"❌ 目录不存在: {dir_path}")
        sys.exit(1)

    # 收集所有图片
    image_files = []
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]:
        image_files.extend(dir_path.glob(f"*{ext}"))
        image_files.extend(dir_path.glob(f"*{ext.upper()}"))

    if not image_files:
        print(f"❌ 目录中没有找到图片文件: {dir_path}")
        sys.exit(1)

    # 支持的图片前缀
    print(f"\n📁 找到 {len(image_files)} 个图片文件")
    print("=" * 50)

    # 统计
    success_count = 0
    fail_count = 0
    results_log = []

    # log_entry 公共基座（各分支用 dict unpacking 覆盖差异字段）
    _LOG_ENTRY_BASE = dict(
        source=None, similarity=None,
        pixiv_id=None, pixiv_page=None, pixiv_image_id=None,
        artist=None, artist_id=None, title=None,
        material=None, ext_url=None, highres_url=None,
        danbooru_id=None, gelbooru_id=None, twitter_id=None,
        error=None,
    )

    for i, img_path in enumerate(image_files, 1):
        print(f"\n[{i}/{len(image_files)}] 处理: {img_path.name}")
        print("-" * 40)

        try:
            results = search_image(str(img_path))
            if results:
                success_count += 1
                best = results[0]
                log_entry = dict(
                    _LOG_ENTRY_BASE,
                    file=str(img_path), status="success",
                    source=best.source,
                    similarity=best.similarity,
                    pixiv_id=best.pixiv_id,
                    pixiv_page=best.pixiv_page,
                    pixiv_image_id=best.pixiv_image_id(),
                    artist=best.artist,
                    artist_id=best.artist_id,
                    title=best.title,
                    material=best.material,
                    ext_url=best.ext_urls[0] if best.ext_urls else None,
                    highres_url=best.highres_url,
                    danbooru_id=best.danbooru_id,
                    gelbooru_id=best.gelbooru_id,
                    twitter_id=best.twitter_id,
                )
                print_results([best])
            else:
                fail_count += 1
                log_entry = dict(
                    _LOG_ENTRY_BASE,
                    file=str(img_path), status="no_match",
                )
                print("  ❌ 未找到匹配")

        except Exception as e:
            fail_count += 1
            log_entry = dict(
                _LOG_ENTRY_BASE,
                file=str(img_path), status="error",
                error=str(e),
            )
            print(f"  ❌ 搜索失败: {e}")

        results_log.append(log_entry)

        # 搜索间隔，避免触发 SauceNAO 限流 (4次/30秒)
        if i < len(image_files):
            delay = get("request_delay", 8.0)
            print(f"  ⏳ 等待 {delay} 秒后继续下一张...")
            time.sleep(delay)

    # 打印统计
    print("\n" + "=" * 50)
    print(f"📊 批量搜索完成:")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ❌ 失败: {fail_count}")
    print(f"   📁 总计: {len(image_files)}")

    # 保存 JSON 日志
    log_path_json = dir_path / "search_results.json"
    try:
        with open(log_path_json, "w", encoding="utf-8") as f:
            json.dump(results_log, f, ensure_ascii=False, indent=2)
        print(f"   📝 JSON 结果已保存: {log_path_json}")
    except Exception as e:
        print(f"   ⚠️ 保存 JSON 日志失败: {e}")

    # 保存 CSV 日志（便于 Excel 查看）
    log_path_csv = dir_path / "search_results.csv"
    try:
        fieldnames = [
            "file", "status", "source", "similarity",
            "pixiv_id", "pixiv_page", "pixiv_image_id",
            "artist", "artist_id", "title", "material",
            "ext_url", "highres_url",
            "danbooru_id", "gelbooru_id", "twitter_id", "error",
        ]
        with open(log_path_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results_log)
        print(f"   📊 CSV 结果已保存: {log_path_csv}")
    except Exception as e:
        print(f"   ⚠️ 保存 CSV 日志失败: {e}")


# 注册内置引擎到动态加载缓存
register_engine_class("sauceNAO", SauceNAO)
register_engine_class("ascii2d", Ascii2D)
register_engine_class("danbooru", Danbooru)


def search_image(
    image_path: str,
    engine: str = "auto",
) -> List:
    """
    搜索图片来源

    Args:
        image_path: 图片路径
        engine: 搜索引擎 (auto 表示按配置顺序依次尝试，或指定具体引擎名)

    Returns:
        搜索结果列表（SearchResult 对象）
    """
    proxies = None
    proxy_str = get("proxy", "")
    if proxy_str:
        proxies = {"http": proxy_str, "https": proxy_str}
        # 检测代理是否可用，不可用则降级为直连（不清除配置，仅运行时降级）
        from imgsearch.config import check_proxy
        if not check_proxy(proxies):
            print(f"  ⚠️ 代理 {proxy_str} 不可用，已自动降级为直连")
            print(f"    如需更换代理，请运行: imgsearch config set proxy YOUR_PROXY")
            proxies = None

    results = []
    mgr = EngineManager()

    if engine == "auto":
        # 从 EngineManager 获取已启用的引擎列表（自动按 priority 排序）
        engine_order = mgr.get_enabled()
    else:
        # 只尝试指定的引擎（查找 EngineConfig 以获取配置）
        ec = mgr.get_by_name(engine)
        if ec is None:
            # 未在配置中找到，回退到默认
            engine_order = [EngineConfig(name=engine, enabled=True, priority=0)]
        else:
            engine_order = [ec]

    for idx, ec in enumerate(engine_order):
        engine_name = ec.name
        # 先查缓存/内置映射，再尝试动态导入
        engine_cls = resolve_engine_class(ec)
        if engine_cls is None:
            print(f"  ⚠️ 未知搜索引擎: {engine_name}，已跳过")
            print(f"    如需添加自定义引擎，请配置 module_path + class_name")
            continue

        # 引擎间请求间隔（避免触发限流）
        if idx > 0:
            delay = getattr(ec, "request_delay", 8.0)
            print(f"  ⏳ 等待 {delay} 秒后切换到下一引擎...")
            time.sleep(delay)

        try:
            print(f"  🌐 正在使用 {engine_name} 搜索...")

            # 解析引擎自身的 API Key，如果为空则回退到全局配置
            api_key = ec.api_key or mgr.get_resolved_api_key(engine_name) or get("saucenao_key", "")
            timeout = getattr(ec, "timeout", 30) or 30

            # 从配置读取所有通用参数
            api_url = getattr(ec, "api_url", "") or ""
            headers = getattr(ec, "headers", None) or {}
            params = getattr(ec, "params", None) or {}

            # 统一构造引擎实例（各引擎 __init__ 通过 **kwargs 吸收自身需要的参数）
            kwargs = dict(
                api_key=api_key, timeout=timeout, proxies=proxies,
                api_url=api_url, headers=headers, params=params,
                bypass_cfw=getattr(ec, "bypass_cfw", False),
            )

            if engine_name == "sauceNAO":
                long_limit = getattr(ec, "long_limit", 100) or 100
                short_limit = getattr(ec, "short_limit", 4) or 4
                long_window = getattr(ec, "long_window", 86400)
                short_window = getattr(ec, "short_window", 30)
                kwargs.update(
                    long_limit=long_limit, short_limit=short_limit,
                    long_window=long_window, short_window=short_window,
                )

            eng = engine_cls(**kwargs)

            results = eng.search(image_path)
            if results:
                return results
        except Exception as e:
            print(f"  ⚠️ {engine_name} 搜索失败: {e}")
            if engine != "auto":
                raise

    return results


def print_results(results: List):
    """打印搜索结果"""
    print()
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r.source}")
        if r.similarity > 0:
            print(f"      相似度: {r.similarity:.1f}%")
        if r.pixiv_id:
            pixiv_img = r.pixiv_image_id()
            print(f"      📌 Pixiv: {pixiv_img}")
            print(f"      🔗 https://www.pixiv.net/artworks/{r.pixiv_id}")
        if r.artist:
            print(f"      🎨 画师: {r.artist}")
        if r.title:
            print(f"      📄 标题: {r.title}")
        if r.ext_urls:
            print(f"      🔗 来源: {r.ext_urls[0]}")
        if r.material:
            print(f"      📺 作品: {r.material}")
        print()


def main():
    parser = argparse.ArgumentParser(
        prog="imgsearch",
        description="🎨 二次元图片溯源工具 - 查找图片来源",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
调用方式:
  ./run.sh <子命令>        # Linux（首次自动建 venv 装依赖）
  run.bat <子命令>         # Windows
  python -m imgsearch <子命令>

使用示例:
  %(prog)s search ./image.jpg                    # 搜索图片出处
  %(prog)s search ./image.jpg --url              # 搜索并生成 Pixiv 链接
  %(prog)s search ./image.jpg -e ascii2d         # 指定搜索引擎
  %(prog)s batch ./wating_for_search/             # 批量搜索目录
  %(prog)s export-urls ./search_results.csv       # 从 CSV 生成 Pixiv URL
  %(prog)s export-urls ./search_results.csv --source pixiv.re  # 指定模板
  %(prog)s export-urls ./search_results.csv --output urls.txt  # 输出到文件
  %(prog)s source list                            # 查看所有 URL 模板
  %(prog)s source add myproxy https://.../{pixiv_id}_p{page}.jpg  # 添加模板
  %(prog)s source remove pixiv.cat                # 删除模板
  %(prog)s source toggle pixiv.re                 # 启用/禁用模板
  %(prog)s source reset                           # 恢复默认模板
  %(prog)s engines list                           # 查看所有引擎及权重
  %(prog)s engines add my_engine                  # 添加自定义引擎
  %(prog)s engines remove my_engine               # 删除自定义引擎
  %(prog)s engines toggle ascii2d                 # 启用/禁用引擎
  %(prog)s engines move sauceNAO --down           # 向下移动引擎
  %(prog)s engines move ascii2d --up              # 向上移动引擎
  %(prog)s engines reset                          # 恢复默认引擎列表
  %(prog)s config show                            # 查看配置
  %(prog)s config set saucenao_key YOUR_KEY       # 设置 API Key
  %(prog)s config set proxy http://127.0.0.1:7890 # 设置代理
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # search 子命令
    search_parser = subparsers.add_parser("search", help="搜索单张图片来源")
    search_parser.add_argument("path", help="图片文件路径")
    search_parser.add_argument(
        "--engine", "-e",
        default="auto",
        help="搜索引擎 (默认: auto, 按配置顺序依次尝试；也可指定具体引擎名称)",
    )
    search_parser.add_argument(
        "--url", "-u",
        action="store_true",
        help="搜索后生成 Pixiv 图片 URL",
    )

    # batch 子命令
    batch_parser = subparsers.add_parser("batch", help="批量搜索目录中的图片")
    batch_parser.add_argument("directory", help="图片目录路径")

    # config 子命令
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_parser.add_argument("action", choices=["show", "secrets", "set"], help="操作")
    config_parser.add_argument("key", nargs="?", help="配置键名 (saucenao_key / proxy)")
    config_parser.add_argument("value", nargs="?", help="配置值")

    # export-urls 子命令
    export_parser = subparsers.add_parser("export-urls", help="从 CSV 生成 Pixiv URL")
    export_parser.add_argument("csv_path", help="CSV 文件路径（必须有 pixiv_id 列）")
    export_parser.add_argument(
        "--output", "-o",
        default="",
        help="输出 txt 文件路径（默认只打印到控制台）",
    )
    export_parser.add_argument(
        "--source", "-s",
        default="",
        help="指定 URL 模板名称（默认使用优先级最高的启用模板）",
    )
    export_parser.add_argument(
        "--id-column", default="pixiv_id",
        help="CSV 中 Pixiv ID 的列名 (默认: pixiv_id)",
    )
    export_parser.add_argument(
        "--page-column", default="pixiv_page",
        help="CSV 中页码的列名 (默认: pixiv_page)",
    )

    # source 子命令
    source_parser = subparsers.add_parser("source", help="管理 Pixiv URL 模板")
    source_parser.add_argument("action", choices=["list", "add", "remove", "toggle", "reset"], help="操作")
    source_parser.add_argument("name", nargs="?", help="模板名称")
    source_parser.add_argument("base_url", nargs="?", help="URL 模板，支持 {pixiv_id} 和 {page} 占位符 (add 时使用)")
    source_parser.add_argument("--priority", type=int, default=None, help="优先级 (add 时使用，数字越小越优先)")

    # engines 子命令：管理搜索引擎列表及顺序
    engines_parser = subparsers.add_parser("engines", help="管理搜索引擎列表及顺序")
    engines_parser.add_argument("action", choices=["list", "add", "remove", "toggle", "reset", "move", "config"], help="操作")
    engines_parser.add_argument("name", nargs="?", help="引擎名称")
    engines_parser.add_argument("--up", action="store_true", help="向上移动（move 时使用）")
    engines_parser.add_argument("--down", action="store_true", help="向下移动（move 时使用）")
    # engines config 子选项
    engines_parser.add_argument("--api-url", type=str, default=None, help="API 地址（config 时使用）")
    engines_parser.add_argument("--api-key", type=str, default=None, help="API 密钥（config 时使用）")
    engines_parser.add_argument("--request-delay", type=float, default=None, help="请求间隔秒数（config 时使用）")
    engines_parser.add_argument("--timeout", type=int, default=None, help="请求超时秒数（config 时使用）")
    engines_parser.add_argument("--long-limit", type=int, default=None, help="长期限额（窗口内次数，0=无限制）")
    engines_parser.add_argument("--short-limit", type=int, default=None, help="短期限额（窗口内次数，0=无限制）")
    engines_parser.add_argument("--long-window", type=int, default=None, help="长期窗口时长秒数（默认 86400 = 24h）")
    engines_parser.add_argument("--short-window", type=int, default=None, help="短期窗口时长秒数（默认 30 = 30s）")
    engines_parser.add_argument("--header", action="append", default=None,
                                help="自定义请求头, 格式 key:value（可重复使用）")
    engines_parser.add_argument("--param", action="append", default=None,
                                help="自定义查询参数, 格式 key:value（可重复使用）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "config":
        if args.action == "show":
            config = load_config()
            # config.json 中已不再存放任何凭据；此处脱敏仅为防御旧版残留字段
            safe_config = {
                k: ("***" if "key" in k.lower() and v else v)
                for k, v in config.items()
            }
            print("当前配置 (config.json):")
            print(json.dumps(safe_config, ensure_ascii=False, indent=2))
            print()
            _print_secrets()
        elif args.action == "secrets":
            _print_secrets()
        elif args.action == "set":
            if not args.key or not args.value:
                print("❌ 请指定 key 和 value")
                print("示例: imgsearch config set saucenao_key YOUR_KEY")
                sys.exit(1)
            save_config(args.key, args.value)
            target = ".env（权限 600，不入库）" if is_secret_key(args.key) else "config.json"
            print(f"✅ {args.key} 已设置 → {target}")
        return

    if args.command == "search":
        cmd_search(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "export-urls":
        cmd_export_urls(args)
    elif args.command == "source":
        cmd_source(args)
    elif args.command == "engines":
        cmd_engines(args)


# ──────────────────────────────────────────────
#  export-urls 子命令
# ──────────────────────────────────────────────


def cmd_export_urls(args):
    """处理 export-urls 子命令：从 CSV 生成 Pixiv URL"""
    csv_path = args.csv_path

    if not Path(csv_path).exists():
        print(f"❌ CSV 文件不存在: {csv_path}")
        sys.exit(1)

    print(f"📄 正在读取: {csv_path}")
    print("=" * 50)

    try:
        generator = PixivUrlGenerator()
        source_name = args.source if args.source else None
        urls = generator.generate_from_csv(
            csv_path=csv_path,
            output_path=args.output if args.output else None,
            source_name=source_name,
            id_column=args.id_column,
            page_column=args.page_column,
        )

        print(f"\n📋 生成的 Pixiv URL（共 {len(urls)} 个）:")
        print("-" * 50)
        for url in urls:
            print(f"  {url}")
        print("-" * 50)

        if args.output:
            print(f"✅ 已保存到: {args.output}")
        print(f"💡 可将这些 URL 粘贴到下载工具中批量下载")

    except Exception as e:
        print(f"❌ 生成失败: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────
#  source 子命令
# ──────────────────────────────────────────────


def cmd_source(args):
    """处理 source 子命令"""
    downloader = PixivUrlGenerator()

    if args.action == "list":
        sources = downloader.list_sources()
        if not sources:
            print("📭 暂无下载源")
            return
        print(f"\n📋 Pixiv 下载源列表 ({len(sources)} 个):")
        print("=" * 60)
        print(f"  {'名称':<16} {'状态':<8} {'优先级':<6}  URL 模板")
        print("-" * 60)
        for s in sources:
            status = "✅ 启用" if s.enabled else "❌ 禁用"
            url_preview = s.base_url[:50] + "..." if len(s.base_url) > 50 else s.base_url
            print(f"  {s.name:<16} {status:<8} {s.priority:<6}  {url_preview}")
        print()

    elif args.action == "add":
        if not args.name or not args.base_url:
            print("❌ 请指定名称和 URL 模板")
            print("   示例: imgsearch source add myproxy https://example.com/{pixiv_id}_p{page}.jpg")
            sys.exit(1)
        ok = downloader.add_source(args.name, args.base_url, priority=args.priority)
        if ok:
            print(f"✅ 已添加下载源: {args.name}")
        else:
            print(f"❌ 添加失败，名称已存在: {args.name}")
            sys.exit(1)

    elif args.action == "remove":
        if not args.name:
            print("❌ 请指定要删除的源名称")
            print(f"   示例: imgsearch source remove pixiv.cat")
            sys.exit(1)
        ok = downloader.remove_source(args.name)
        if ok:
            print(f"✅ 已删除下载源: {args.name}")
        else:
            print(f"❌ 未找到下载源: {args.name}")
            sys.exit(1)

    elif args.action == "toggle":
        if not args.name:
            print("❌ 请指定要切换的源名称")
            print(f"   示例: imgsearch source toggle pixiv.cat")
            sys.exit(1)
        new_state = downloader.toggle_source(args.name)
        if new_state is None:
            print(f"❌ 未找到下载源: {args.name}")
            sys.exit(1)
        status = "启用" if new_state else "禁用"
        print(f"✅ 已{status}下载源: {args.name}")

    elif args.action == "reset":
        default_sources = PixivUrlGenerator.get_default_sources()
        save_config("pixiv_sources", default_sources)
        print("✅ 已恢复默认 URL 模板列表")
        print(f"   共 {len(default_sources)} 个模板")


# ──────────────────────────────────────────────
#  engines 子命令
# ──────────────────────────────────────────────


def cmd_engines(args):
    """处理 engines 子命令：管理搜索引擎列表及顺序"""
    mgr = EngineManager()

    if args.action == "list":
        engines = mgr.list_all()
        if not engines:
            print("📭 暂无搜索引擎配置")
            return

        enabled = [e for e in engines if e.enabled]
        disabled = [e for e in engines if not e.enabled]

        print(f"\n🔍 搜索引擎列表 ({len(engines)} 个):")
        print("=" * 60)
        print(f"  {'权重':<6} {'名称':<16} {'状态':<8} {'类型':<10}")
        print("-" * 60)
        for e in engines:
            status = "✅ 启用" if e.enabled else "❌ 禁用"
            etype = "📦 内置" if mgr.is_builtin(e.name) else "🔧 自定义"
            print(f"  {e.priority:<6} {e.name:<16} {status:<8} {etype:<10}")
        print()
        print(f"  ✅ 启用: {len(enabled)} 个 | ❌ 禁用: {len(disabled)} 个")
        print()
        print("💡 操作示例:")
        print("   imgsearch engines add my_engine        # 添加自定义引擎")
        print("   imgsearch engines remove my_engine     # 删除自定义引擎")
        print("   imgsearch engines toggle sauceNAO      # 启用/禁用引擎")
        print("   imgsearch engines move ascii2d --up    # 向上移动")
        print("   imgsearch engines move sauceNAO --down # 向下移动")
        print("   imgsearch engines reset                # 恢复默认")

    elif args.action == "add":
        name = args.name
        if not name:
            print("❌ 请指定引擎名称")
            print("   示例: imgsearch engines add my_engine")
            sys.exit(1)

        ok = mgr.add(name)
        if ok:
            print(f"✅ 已添加自定义引擎: {name}")
            _print_engine_list(mgr)
        else:
            print(f"❌ 添加失败，引擎名称已存在: {name}")
            sys.exit(1)

    elif args.action == "remove":
        name = args.name
        if not name:
            print("❌ 请指定要删除的引擎名称")
            print("   示例: imgsearch engines remove my_engine")
            sys.exit(1)

        if mgr.is_builtin(name):
            print(f"❌ 内置引擎不可删除: {name}")
            print("   你可以使用 `toggle` 来禁用它")
            sys.exit(1)

        ok = mgr.remove(name)
        if ok:
            print(f"✅ 已删除引擎: {name}")
            _print_engine_list(mgr)
        else:
            print(f"❌ 未找到引擎: {name}")
            sys.exit(1)

    elif args.action == "toggle":
        name = args.name
        if not name:
            print("❌ 请指定引擎名称")
            print("   示例: imgsearch engines toggle sauceNAO")
            sys.exit(1)

        new_state = mgr.toggle(name)
        if new_state is None:
            print(f"❌ 未找到引擎: {name}")
            sys.exit(1)
        status = "启用" if new_state else "禁用"
        print(f"✅ 已{status}引擎: {name}")
        print(f"   权重: {mgr.get_by_name(name).priority}")

    elif args.action == "reset":
        mgr.reset()
        print("✅ 已恢复默认搜索引擎列表")
        _print_engine_list(mgr)

    elif args.action == "move":
        name = args.name
        if not name:
            print("❌ 请指定引擎名称")
            print("   示例: imgsearch engines move sauceNAO --down")
            sys.exit(1)

        if args.up and args.down:
            print("❌ 不能同时指定 --up 和 --down")
            sys.exit(1)

        direction = None
        if args.up:
            direction = -1
        elif args.down:
            direction = 1
        else:
            print("❌ 请指定移动方向: --up 或 --down")
            print("   示例: imgsearch engines move sauceNAO --down")
            sys.exit(1)

        ok = mgr.move(name, direction)
        if not ok:
            print(f"❌ 无法移动引擎: {name}（已在边界或未找到）")
            sys.exit(1)

        dir_text = "上" if direction == -1 else "下"
        print(f"✅ 已向{dir_text}移动引擎: {name}")
        _print_engine_list(mgr)

    elif args.action == "config":
        name = args.name
        if not name:
            print("❌ 请指定引擎名称")
            print("   示例: imgsearch engines config sauceNAO --api-key YOUR_KEY")
            sys.exit(1)

        engine = mgr.get_by_name(name)
        if engine is None:
            print(f"❌ 未找到引擎: {name}")
            sys.exit(1)

        # 收集要更新的字段
        kwargs = {}
        if args.api_url is not None:
            kwargs["api_url"] = args.api_url
        if args.api_key is not None:
            kwargs["api_key"] = args.api_key
        if args.request_delay is not None:
            kwargs["request_delay"] = args.request_delay
        if args.timeout is not None:
            kwargs["timeout"] = args.timeout
        if args.long_limit is not None:
            kwargs["long_limit"] = args.long_limit
        if args.short_limit is not None:
            kwargs["short_limit"] = args.short_limit
        if args.long_window is not None:
            kwargs["long_window"] = args.long_window
        if args.short_window is not None:
            kwargs["short_window"] = args.short_window

        # 处理 --header key:value（可重复）
        if args.header:
            headers = engine.headers.copy()
            for h in args.header:
                if ":" in h:
                    k, v = h.split(":", 1)
                    headers[k.strip()] = v.strip()
                else:
                    print(f"  ⚠️ 无效 header 格式（应为 key:value）: {h}")
            kwargs["headers"] = headers

        # 处理 --param key:value（可重复）
        if args.param:
            params = engine.params.copy()
            for p in args.param:
                if ":" in p:
                    k, v = p.split(":", 1)
                    params[k.strip()] = v.strip()
                else:
                    print(f"  ⚠️ 无效 param 格式（应为 key:value）: {p}")
            kwargs["params"] = params

        if not kwargs:
            # 没有要更新的字段，显示当前配置
            print(f"\n⚙ 引擎配置: {name}")
            print("=" * 50)
            print(f"  API 地址:      {engine.api_url or '(未设置)'}")
            print(f"  API Key:       {'***' if engine.api_key else '(未设置)'}")
            print(f"  请求间隔(秒):  {engine.request_delay}")
            print(f"  超时(秒):      {engine.timeout}")
            long_limit = getattr(engine, "long_limit", 100) or 100
            short_limit = getattr(engine, "short_limit", 4) or 4
            long_window = getattr(engine, "long_window", 86400)
            short_window = getattr(engine, "short_window", 30)
            print(f"  长期限额(次):  {long_limit}  (0=无限制)")
            print(f"  短期限额(次):  {short_limit}  (0=无限制)")
            print(f"  长期窗口(秒):  {long_window}  (默认 86400 = 24h)")
            print(f"  短期窗口(秒):  {short_window}  (默认 30 = 30s)")
            print(f"  自定义 Headers: {json.dumps(engine.headers, ensure_ascii=False) if engine.headers else '(无)'}")
            print(f"  自定义 Params:  {json.dumps(engine.params, ensure_ascii=False) if engine.params else '(无)'}")
            return

        ok = mgr.update_config(name, **kwargs)
        if ok:
            print(f"✅ 已更新引擎配置: {name}")
            print(f"   更新的字段: {', '.join(kwargs.keys())}")
        else:
            print(f"❌ 更新配置失败: {name}")
            sys.exit(1)


def _print_engine_list(mgr: EngineManager):
    """打印当前引擎列表"""
    engines = mgr.list_all()
    print(f"\n📋 当前引擎顺序:")
    for e in engines:
        status = "✅" if e.enabled else "❌"
        etype = "📦" if mgr.is_builtin(e.name) else "🔧"
        print(f"   {e.priority}. {etype} {status} {e.name}")
    print()


if __name__ == "__main__":
    main()
