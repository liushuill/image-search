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
import re
import time
from pathlib import Path
from typing import List, Optional

# 项目以包的形式运行（python -m imgsearch），无需注入 sys.path
from imgsearch import secrets
from imgsearch.config import get, save_config, load_config, is_secret_key, PROJECT_DIR
from imgsearch.engines.registry import resolve_engine_class
from imgsearch.engines.schema import ConfigError
from imgsearch.engines.store import (
    EngineConfig,
    EngineNotFoundError,
    EngineStore,
    get_store,
)
from imgsearch.links.pixiv import PixivUrlGenerator
from imgsearch.processor.image_utils import (
    SUPPORTED_FORMATS,
    is_image_file,
    get_image_info,
    get_file_hash,
)


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

    # 验证引擎名称
    engine = args.engine
    if engine != "auto":
        store = get_store()
        ec = store.get(engine)
        if ec is None:
            known = store.names()
            print(f"❌ 未配置该搜索引擎: {engine}")
            print(f"   可用引擎: auto, {', '.join(known) if known else '(无)'}")
            sys.exit(1)
        if resolve_engine_class(ec) is None:
            print(f"❌ 引擎 '{ec.name}' 的类无法解析（自定义引擎请检查 module_path / class_name）")
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
    # 指定单个引擎时错误会向上抛（auto 模式则在内部跳过并继续），
    # 这里统一转成可读提示，不让用户看到原始 traceback。
    try:
        results = search_image(image_path, engine=engine,
                               min_similarity=args.min_similarity)
    except EngineNotFoundError as e:
        print(f"\n❌ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 搜索失败（引擎 {engine}）：")
        for line in str(e).strip().splitlines():
            print(f"   {line}")
        print("\n💡 排查建议：")
        print("   · 查看该引擎配置： imgsearch engines show " + engine)
        print("   · 网络/代理是否可用： imgsearch config show")
        sys.exit(1)

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


def _resolve_proxies() -> Optional[dict]:
    """
    读取代理配置。

    配置了代理但探测不可用时**自动降级为直连** —— 只影响本次运行，
    不修改配置（代理不是常开，见 HANDOVER）。

    Returns:
        requests 格式的 proxies，未配置或不可用返回 None
    """
    proxy_str = get("proxy", "")
    if not proxy_str:
        return None

    proxies = {"http": proxy_str, "https": proxy_str}
    from imgsearch.config import check_proxy
    if not check_proxy(proxies):
        print(f"  ⚠️ 代理 {proxy_str} 不可用，已自动降级为直连")
        print(f"    如需更换代理: imgsearch config set proxy YOUR_PROXY")
        return None
    return proxies


def _needs_proxy(ec) -> Optional[bool]:
    """
    按引擎的 proxy_mode 决定路由。

    Returns:
        True 强制走代理 / False 强制直连 / None 跟随全局设置
    """
    mode = str(ec.get("proxy_mode", "auto") or "auto").strip().lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return None


def _is_network_error(exc: BaseException) -> bool:
    """
    判断是否属于「根本没连上服务器」的失败。

    这类失败不消耗对方的配额，因此没必要等 request_delay 再试下一个引擎 ——
    否则网络不通时会变成「引擎数 × 8 秒」的干等。
    """
    import requests
    return isinstance(exc, (
        ConnectionError, TimeoutError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.SSLError,
    ))


def search_image(image_path: str, engine: str = "auto",
                 min_similarity: Optional[int] = None) -> List:
    """
    搜索图片来源

    auto 模式的判定规则：
      1. 按权重顺序依次尝试「已启用」的引擎
      2. 某引擎的最高相似度 >= **该引擎自己的**阈值 → 立即采用
      3. 未达阈值 → 记为候选，继续试下一个引擎
      4. 全部试完仍无一达标 → 返回置信度相对最高的一组，并明确标注低置信度

    ⚠️ 阈值按引擎校准，不用统一数字：各引擎的相似度量纲不同
    （同一张图 IQDB 报 53%、SauceNAO 报 95%），一刀切会误杀刻度偏保守的引擎。

    Args:
        image_path: 图片路径
        engine: "auto"，或具体引擎名（指定引擎时不降级、不套阈值）
        min_similarity: 覆盖本次运行的阈值（0-100）

    Returns:
        搜索结果列表（SearchResult）

    Raises:
        EngineNotFoundError: 指定的引擎不存在或没有启用任何引擎
    """
    store = get_store()
    target = (engine or "auto").strip()

    if target == "auto":
        engine_order = store.get_enabled()
        if not engine_order:
            raise EngineNotFoundError(
                "没有启用任何搜索引擎。\n"
                "  查看：imgsearch engines list\n"
                "  启用：imgsearch engines toggle <名称>"
            )
    else:
        ec = store.get(target)
        if ec is None:
            raise EngineNotFoundError(f"未找到引擎：{target}")
        engine_order = [ec]

    # 全局代理只探活一次：探测本身最长 5 秒，不能每个引擎都探一遍
    global_proxies = _resolve_proxies()

    results: List = []
    fallback = None            # (超出阈值的幅度, 结果, 引擎)
    warned_offline = False
    sent_to_network = False

    for ec in engine_order:
        # 只有「上一次真的把请求发到了服务器」才需要等间隔
        if sent_to_network:
            delay = float(ec.get("request_delay", 8.0) or 0)
            if delay > 0:
                print(f"  ⏳ 等待 {delay} 秒后切换到下一引擎...")
                time.sleep(delay)

        want_proxy = _needs_proxy(ec)
        if want_proxy is False:
            proxies = None
        else:
            proxies = global_proxies
            if want_proxy is True and not proxies:
                print(f"  ⚠️ {ec.display_name} 设为强制走代理，但代理不可用，将直连尝试")

        sent_to_network = False
        try:
            print(f"  🌐 正在使用 {ec.display_name} 搜索...")
            # 参数与类型由引擎的 CONFIG_SCHEMA 决定，此处不再逐字段拼装
            eng = store.build_engine(ec, proxies=proxies)
            results = eng.search(image_path)
            sent_to_network = True
        except Exception as e:
            if target != "auto":
                raise
            lines = [ln for ln in str(e).strip().splitlines() if ln.strip()]
            print(f"  ⚠️ 跳过 {ec.display_name}：{lines[0] if lines else e}")
            for line in lines[1:]:
                print(f"     {line}")
            if _is_network_error(e) and not warned_offline:
                warned_offline = True
                print("  💡 连不上，可能是网络问题：")
                print("       · 查看代理配置：imgsearch config show")
                print("       · 只让该引擎走代理：")
                print(f"         imgsearch engines config {ec.name} --set proxy_mode=on")
            continue

        if not results:
            print(f"  · {ec.display_name}：无匹配")
            continue

        # 指定了具体引擎就不套阈值 —— 用户已明确要求用它
        if target != "auto":
            return results

        threshold = (min_similarity if min_similarity is not None
                     else int(ec.get("min_similarity", 60) or 0))
        best = max(r.similarity for r in results)

        if best >= threshold:
            if threshold > 0:
                print(f"  ✓ {ec.display_name}：最高 {best:.1f}%（阈值 {threshold}%），采用")
            return results

        print(f"  · {ec.display_name}：最高 {best:.1f}% 低于阈值 {threshold}%，继续尝试下一个")
        margin = best - threshold
        if fallback is None or margin > fallback[0]:
            fallback = (margin, results, ec)

    if fallback is not None:
        _, results, ec = fallback
        print()
        print("  ⚠️ 没有任何引擎达到各自的相似度阈值。")
        print(f"     以下为置信度相对最高的一组（来自 {ec.display_name}），请自行核对。")
        print("     若确认可用，可调低该引擎阈值：")
        print(f"       imgsearch engines config {ec.name} --set min_similarity=40")
        return results

    return results


def print_results(results: List):
    """打印搜索结果"""
    print()
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r.source}   相似度 {r.similarity:.1f}%")
        if r.pixiv_id:
            print(f"      📌 Pixiv: {r.pixiv_image_id()}")
            print(f"      🔗 https://www.pixiv.net/artworks/{r.pixiv_id}")
        if r.artist:
            print(f"      🎨 画师: {r.artist}")
        if r.material:
            print(f"      📺 作品: {r.material}")
        if r.title:
            print(f"      📄 标题: {r.title}")
        if r.detail:
            print(f"      📝 {r.detail}")
        site_ids = []
        for label, value in (("Danbooru", r.danbooru_id), ("Gelbooru", r.gelbooru_id),
                             ("Twitter", r.twitter_id)):
            if value:
                site_ids.append(f"{label}={value}")
        site_ids.extend(f"{k}={v}" for k, v in r.extra_ids.items())
        if site_ids:
            print(f"      🆔 {', '.join(site_ids)}")
        # 全部来源链接（旧实现只打印第一条，其余静默丢弃）
        for url in r.ext_urls:
            print(f"      🔗 {url}")
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
    search_parser.add_argument(
        "--min-similarity", type=int, default=None, metavar="0-100",
        help="覆盖相似度阈值：低于此值的结果视为不可信，继续尝试下一个引擎。"
             "0 = 不设阈值（第一个有结果的引擎即采用）",
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
    engines_parser.add_argument(
        "action",
        choices=["list", "show", "add", "remove", "rename", "toggle",
                 "reset", "move", "config", "new"],
        help="list 列表 | show 查看配置 | new 生成自定义引擎模板 | "
             "add/remove/rename/toggle/move/reset/config 管理",
    )
    engines_parser.add_argument("name", nargs="?", help="引擎名称")
    engines_parser.add_argument("new_name", nargs="?", help="新名称（rename 时使用）")
    engines_parser.add_argument("--up", action="store_true", help="向上移动（move 时使用）")
    engines_parser.add_argument("--down", action="store_true", help="向下移动（move 时使用）")
    # 通用配置路径：--set key=value（可重复），对任何 schema 字段都有效
    engines_parser.add_argument("--set", action="append", default=None, metavar="KEY=VALUE",
                                help="设置任意配置字段，格式 key=value（可重复使用）")
    # 自定义引擎的模块绑定
    engines_parser.add_argument("--module", type=str, default=None,
                                help="自定义引擎的模块路径，如 my_engines.my_engine")
    engines_parser.add_argument("--class-name", type=str, default=None,
                                help="自定义引擎的类名，如 MyEngine")
    # 以下专用 flag 保留以兼容旧用法
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
    store = get_store()
    action = args.action

    # ── 不需要引擎名的动作 ──
    if action == "list":
        _print_engine_list(store)
        return

    if action == "reset":
        store.reset()
        print("✅ 已恢复默认搜索引擎列表")
        _print_engine_list(store)
        return

    if action == "new":
        _scaffold_custom_engine(args.name)
        return

    # ── 以下动作都需要引擎名 ──
    name = args.name
    if not name:
        print(f"❌ 请指定引擎名称：imgsearch engines {action} <名称>")
        sys.exit(1)

    try:
        if action == "show":
            _show_engine_config(store, name)

        elif action == "add":
            ec = store.add(name,
                           module_path=args.module or "",
                           class_name=args.class_name or "")
            print(f"✅ 已添加引擎: {ec.name}（权重 #{ec.priority}）")
            if not store.is_builtin(ec.name) and not (ec.module_path and ec.class_name):
                print("   ⚠️ 自定义引擎需要模块绑定，否则无法解析。补上：")
                print(f"      imgsearch engines config {ec.name} "
                      f"--module my_engines.{ec.name} --class MyEngine")
                print(f"      或用 `imgsearch engines new {ec.name}` 生成模板")
            _print_engine_list(store)

        elif action == "remove":
            store.remove(name)
            print(f"✅ 已删除引擎: {name}")
            _print_engine_list(store)

        elif action == "rename":
            new_name = args.new_name
            if not new_name:
                print("❌ 请指定新名称：imgsearch engines rename <旧名> <新名>")
                sys.exit(1)
            if store.get(name) is None:
                print(f"❌ 未找到引擎: {name}")
                sys.exit(1)
            store.rename(name, new_name)
            print(f"✅ 已改名: {name} → {new_name}")
            print("   （顺序、模块绑定与全部配置均原样保留）")

        elif action == "toggle":
            new_state = store.toggle(name)
            if new_state is None:
                print(f"❌ 未找到引擎: {name}")
                sys.exit(1)
            print(f"✅ 已{'启用' if new_state else '禁用'}引擎: {name}")

        elif action == "move":
            if args.up and args.down:
                print("❌ 不能同时指定 --up 和 --down")
                sys.exit(1)
            direction = -1 if args.up else (1 if args.down else None)
            if direction is None:
                print("❌ 请指定方向: --up 或 --down")
                sys.exit(1)
            if not store.move(name, direction):
                print(f"❌ 无法移动: {name}（已在边界或未找到）")
                sys.exit(1)
            print(f"✅ 已向{'上' if direction == -1 else '下'}移动: {name}")
            _print_engine_list(store)

        elif action == "config":
            _update_engine_config(store, name, args)

    except ConfigError as e:
        print(f"❌ {e}")
        sys.exit(1)


def _fmt_field_value(f, value) -> str:
    """把字段值格式化成可读文本（凭据脱敏）"""
    from imgsearch.engines.schema import BOOL, KV

    if f is not None and f.is_secret:
        if not value:
            if f.env_var and secrets.is_set(f.env_var):
                return f"(留空 → 使用 .env 的 {f.env_var}：{secrets.masked(f.env_var)})"
            return "(未设置)"
        return "••••••••"

    if value is None or value == "":
        if f is not None and f.env_var and secrets.is_set(f.env_var):
            return f"(留空 → 使用 .env 的 {f.env_var})"
        return "(未设置)"

    if f is not None and f.type == KV:
        return json.dumps(value, ensure_ascii=False) if value else "(无)"
    if f is not None and f.type == BOOL:
        return "是" if value else "否"

    text = str(value)
    if f is not None and f.unit:
        text = f"{text} {f.unit}"
    return text


def _show_engine_config(store: EngineStore, name: str) -> None:
    """
    显示某引擎的全部 schema 字段与当前值。

    这就是 GUI 配置表单的 CLI 版本：字段、类型、说明、默认值
    全部来自引擎声明的 CONFIG_SCHEMA，因此新增引擎会自动出现在这里。
    """
    ec = store.get(name)
    if ec is None:
        print(f"❌ 未找到引擎: {name}")
        sys.exit(1)

    cls = resolve_engine_class(ec)
    schema = ec.schema()

    print(f"\n⚙ {ec.display_name}（配置名：{ec.name}）")
    print("=" * 64)
    print(f"  类型     {'📦 内置' if ec.is_builtin else '🔧 自定义'}")
    print(f"  权重     #{ec.priority}")
    print(f"  状态     {'✅ 启用' if ec.enabled else '❌ 禁用'}")
    if not ec.is_builtin:
        print(f"  模块     {ec.module_path or '(未设置)'}")
        print(f"  类名     {ec.class_name or '(未设置)'}")
    if cls is None:
        print("  ⚠️ 引擎类当前无法解析，以下为配置里已保存的值")
    print("-" * 64)

    for f in schema:
        if f.key in ("enabled", "priority"):
            continue
        value = ec.get(f.key, f.default)
        marker = "[高级] " if f.advanced else ""
        print(f"  {f.label} ({f.key})")
        print(f"      {marker}{_fmt_field_value(f, value)}")
        if f.help:
            print(f"      💡 {f.help}")

    print()
    print("💡 修改：")
    keys = [k for k in schema.keys() if k not in ("enabled", "priority")]
    example = next((k for k in keys if k != "api_url"), keys[0] if keys else "api_url")
    print(f"   imgsearch engines config {ec.name} --set {example}=值")
    print("   （--set 可重复；字段名见上方括号内）")


def _update_engine_config(store: EngineStore, name: str, args) -> None:
    """
    更新引擎配置。

    主路径是通用的 ``--set key=value``（可重复），对**任何** schema 字段都有效 ——
    这样新增引擎不需要回来给 CLI 加 flag。
    原有的专用 flag（--api-key / --timeout …）保留以兼容旧用法。
    """
    ec = store.get(name)
    if ec is None:
        print(f"❌ 未找到引擎: {name}")
        sys.exit(1)

    updates = {}

    for item in (args.set or []):
        if "=" not in item:
            print(f"  ⚠️ --set 需要 key=value 格式，已跳过: {item}")
            continue
        k, v = item.split("=", 1)
        updates[k.strip()] = v.strip()

    for flag in ("api_url", "api_key", "request_delay", "timeout",
                 "long_limit", "short_limit", "long_window", "short_window"):
        v = getattr(args, flag, None)
        if v is not None:
            updates[flag] = v

    if args.header:
        headers = dict(ec.get("headers", {}) or {})
        for h in args.header:
            if ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
            else:
                print(f"  ⚠️ 无效 header（应为 key:value）: {h}")
        updates["headers"] = headers

    if args.param:
        params = dict(ec.get("params", {}) or {})
        for p in args.param:
            if ":" in p:
                k, v = p.split(":", 1)
                params[k.strip()] = v.strip()
            else:
                print(f"  ⚠️ 无效 param（应为 key:value）: {p}")
        updates["params"] = params

    if args.module is not None or args.class_name is not None:
        store.set_module(
            name,
            args.module if args.module is not None else ec.module_path,
            args.class_name if args.class_name is not None else ec.class_name,
        )
        print(f"✅ 已更新模块绑定 → {ec.module_path}::{ec.class_name}")

    if not updates:
        _show_engine_config(store, name)
        return

    # store.update 会按 schema 做类型转换与校验；非法值在这里就报错，
    # 不会留下写了一半的配置
    store.update(name, **updates)

    print(f"✅ 已更新 {ec.display_name}:")
    schema = ec.schema()
    for key in updates:
        f = schema.get(key)
        label = f.label if f else key
        print(f"   {label} = {_fmt_field_value(f, ec.get(key))}")


# 自定义引擎模板：复制即可用，"加一个引擎"不再需要研究内部结构
_CUSTOM_ENGINE_TEMPLATE = '''\
"""
自定义搜索引擎：{name}

由 `imgsearch engines new {name}` 生成。按需修改三处：
  1. CONFIG_SCHEMA   —— 声明要暴露到界面上的配置字段
  2. DEFAULT_API_URL —— 站点地址
  3. search()        —— 实际的请求与解析
"""

from typing import List

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.schema import COMMON_SCHEMA, INT, Field, Schema


class {cls}(SearchEngine):
    """{name} 搜索引擎"""

    # 配置里使用的稳定标识（改名会影响已有配置，请谨慎）
    NAME = "{name}"
    DISPLAY_NAME = "{name}"

    # 站点地址；用户可在「API 地址」里覆盖
    DEFAULT_API_URL = "https://example.com/search"

    # 需要账号才能用的话改成 False
    ENABLED_BY_DEFAULT = True

    # 配置字段：界面与 CLI 都按这张表自动生成
    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            Field("some_option", "示例选项", INT, 10,
                  help="这里写给人看的说明", minimum=0),
        ),
    )

    def search(self, image_path: str) -> List[SearchResult]:
        """上传图片文件搜索"""
        self.opt_int("some_option", 10)   # 读配置：0 是合法值，不会被默认值覆盖
        raise NotImplementedError("请实现 search()")

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """通过图片 URL 搜索（可选）"""
        raise NotImplementedError("请实现 search_by_url()")

    # 可用属性：
    #   self.timeout / self.api_url / self.proxies / self.headers / self.params
    # 限流（"N 次 / M 秒" 滑动窗口，跨进程有效）：
    #   from imgsearch.engines.quota import SlidingWindowQuota
    #   self._quota = SlidingWindowQuota("myengine", limit=60, window=60)
    #   self._quota.check(); ...; self._quota.record()
'''


def _scaffold_custom_engine(name: str) -> None:
    """生成一个自定义引擎模板到 my_engines/ 下"""
    if not name:
        print("❌ 用法：imgsearch engines new <名称>")
        sys.exit(1)

    safe = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    if not safe or safe[0].isdigit():
        print(f"❌ 名称需为合法的 Python 标识符（字母/数字/下划线），当前: {name}")
        sys.exit(1)

    cls_name = "".join(part.capitalize() for part in safe.split("_")) or "MyEngine"
    pkg_dir = PROJECT_DIR / "my_engines"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    init_file = pkg_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            '"""自定义搜索引擎目录（本目录下的模块可被动态加载）"""\n',
            encoding="utf-8",
        )

    target = pkg_dir / f"{safe}.py"
    if target.exists():
        print(f"❌ 文件已存在，未覆盖: {target}")
        sys.exit(1)

    target.write_text(
        _CUSTOM_ENGINE_TEMPLATE.format(name=safe, cls=cls_name),
        encoding="utf-8",
    )

    print(f"✅ 已生成模板: {target}")
    print()
    print("接下来：")
    print("  1. 编辑该文件，实现 search()")
    print("  2. 注册到引擎列表：")
    print(f"     imgsearch engines add {safe} "
          f"--module my_engines.{safe} --class {cls_name}")
    print("  3. 查看 / 调整配置：")
    print(f"     imgsearch engines show {safe}")


def _print_engine_list(store: EngineStore) -> None:
    """打印当前引擎列表及顺序"""
    engines = store.list_all()
    if not engines:
        print("📭 暂无搜索引擎配置（imgsearch engines reset 可恢复默认）")
        return

    enabled = sum(1 for e in engines if e.enabled)
    print(f"\n🔍 搜索引擎（共 {len(engines)} 个，启用 {enabled} 个）")
    print("=" * 74)
    print(f"  {'权重':<6}{'引擎':<26}{'状态':<6}{'类型':<8}备注")
    print("-" * 74)
    for e in engines:
        status = "✅ 启用" if e.enabled else "❌ 禁用"
        etype = "内置" if e.is_builtin else "自定义"
        print(f"  #{e.priority:<5}{e.display_name:<26}{status:<6}{etype:<8}{_engine_note(e)}")
    print()
    print("💡 imgsearch engines show <名称>                     查看某引擎全部配置")
    print("   imgsearch engines config <名称> --set key=value   修改配置")
    print("   imgsearch engines toggle|move|rename|remove|add <名称>")
    print("   imgsearch engines new <名称>                       生成自定义引擎模板")


def _engine_note(e: EngineConfig) -> str:
    """一行备注：把「为什么不能用」直接摆出来，而不是等搜索时才报错"""
    if resolve_engine_class(e) is None:
        if not e.is_builtin and not (e.module_path and e.class_name):
            return "⚠️ 未绑定模块（--module/--class）"
        return "⚠️ 引擎类无法解析"
    if not e.enabled:
        return ""

    missing = []
    for f in e.schema():
        if f.key in ("enabled", "priority"):
            continue
        value = e.get(f.key, f.default)
        if isinstance(value, str):
            value = value.strip()
        if value:
            continue
        if f.env_var and secrets.is_set(f.env_var):
            continue
        if f.required or f.env_var:
            missing.append(f.label)
    return f"⚠️ 缺少 {', '.join(missing)}" if missing else ""


if __name__ == "__main__":
    main()
