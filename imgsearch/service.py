"""
搜索服务：图库缓存 + 联网搜索 + 结果入库

抽出来的目的：**CLI 与 GUI 共用同一套流程**。
否则两边各写一份「先查缓存、没命中才联网、完事入库」，
迟早出现行为不一致（一边复用了缓存、另一边又去烧配额）。

进度与说明统一用 ``print()`` 输出：CLI 直接看到；
GUI 通过 stdout 桥接转成信号（见 ``imgsearch_gui.workers``）。
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from imgsearch import secrets
from imgsearch.config import get
from imgsearch.engines.base import SearchResult
from imgsearch.library import LibraryDB, LibraryError, LibraryStore


@dataclass
class SearchOutcome:
    """一次搜索的完整结果"""

    results: List[SearchResult] = field(default_factory=list)
    from_cache: bool = False           # 结果来自图库缓存（未消耗配额）
    record_id: Optional[int] = None    # 图库记录 id（未入库时为 None）
    match_kind: Optional[str] = None   # exact / scaled / similar
    library_error: Optional[str] = None

    @property
    def found(self) -> bool:
        return bool(self.results)


def declared_secrets() -> List[tuple]:
    """
    所有需要填写的凭据：``[(环境变量名, 展示名, 说明), ...]``

    来源 = ``secrets.KNOWN_SECRETS`` ∪ 各引擎 schema 里声明的 SECRET 字段。
    这样**自定义引擎新增的凭据也会自动出现在「凭据」页**，
    不必回来改界面或这份列表。

    这里是凭据的唯一定义处：引擎页只读、凭据页负责写入 .env。
    """
    from imgsearch.engines.schema import env_var_for
    from imgsearch.engines.store import get_store

    known = dict(secrets.KNOWN_SECRETS)
    out: List[tuple] = []
    seen = set()

    for env_name, desc in known.items():
        out.append((env_name, env_name, desc))
        seen.add(env_name)

    try:
        store = get_store()
    except Exception:                                     # noqa: BLE001
        return out

    for ec in store.list_all():
        try:
            schema = ec.schema()
        except Exception:                                 # noqa: BLE001
            continue
        for f in schema:
            if not f.is_secret:
                continue
            env_name = env_var_for(ec.name, f)
            if env_name in seen:
                continue
            seen.add(env_name)
            out.append((env_name, f"{ec.display_name} · {f.label}",
                        f.help or f"由引擎「{ec.display_name}」使用"))
    return out


def open_library(enabled: Optional[bool] = None):
    """
    打开图库。

    图库属于「锦上添花」：它坏了不该让搜索也用不了，
    因此这里吞掉异常并返回 (None, None)，只提示一次。
    """
    if enabled is None:
        enabled = bool(get("use_library", True))
    if not enabled:
        return None, None
    try:
        db = LibraryDB()
        return db, LibraryStore(db)
    except Exception as e:
        print(f"  ⚠️ 图库不可用（{e}），本次不查缓存、不记录")
        return None, None


def lookup_cache(store: LibraryStore, image_path: str):
    """
    查「这张图搜过了吗」。

    Returns:
        (Match, 缓存的 SearchResult 列表)；未命中或还没有结果时为 (Match|None, [])
    """
    try:
        match = store.lookup(image_path)
    except LibraryError as e:
        print(f"  ⚠️ 图库查找失败：{e}")
        return None, []
    if match is None:
        return None, []
    if not store.has_results(match.record.id):
        print(f"  📚 图库里有这张图（id={match.record.id}），"
              f"但还没有搜索结果 —— 继续联网搜索")
        return match, []
    return match, store.load_results(match.record.id)


def describe_match(match) -> str:
    """把判定档位翻成人话"""
    return {
        "exact": "同一张",
        "scaled": "同一张（不同尺寸的版本）",
        "similar": "视觉相近（可能不是同一张）",
    }.get(match.kind, match.kind)


def report_cache_hit(match, results: List[SearchResult]) -> None:
    """命中缓存时的统一说明"""
    rec = match.record
    print(f"\n📚 图库命中：这张图搜过了 —— {describe_match(match)}")
    print(f"   记录 id={rec.id} · dHash={rec.dhash}"
          + (f" · 距离 {match.distance}" if match.distance else ""))
    print(f"   首次入库 {rec.first_seen}")
    if match.kind == "similar":
        print("   ⚠️ 只是视觉相近；要确认请勾选「重新搜索」")
    print("   —— 结果来自本地缓存，未消耗任何搜索配额 ——")


def record_to_library(store: LibraryStore, image_path: str,
                      results: List[SearchResult]) -> Optional[int]:
    """
    把搜索结果记入图库（含缩略图缓存）。

    失败不打断主流程 —— 搜索本身已经成功了。
    """
    try:
        rec = store.upsert_image(image_path)
        store.save_results(rec.id, results)
        if get("cache_thumbnails", True):
            from imgsearch.library import thumbs
            thumbs.ensure(rec.dhash, image_path)
        print(f"\n📚 已记入图库（记录 id={rec.id}）—— 下次同图可直接复用结果")
        return rec.id
    except Exception as e:
        print(f"\n  ⚠️ 记入图库失败：{e}")
        return None


def search_with_cache(
    image_path: str,
    *,
    engine: str = "auto",
    refresh: bool = False,
    min_similarity: Optional[int] = None,
    use_library: Optional[bool] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> SearchOutcome:
    """
    完整流程：查图库缓存 → 未命中则联网搜索 → 结果入库。

    Args:
        image_path: 图片路径
        engine: "auto" 或具体引擎名
        refresh: True 时忽略缓存，强制重新搜索（会消耗配额）
        min_similarity: 覆盖相似度阈值
        use_library: 是否使用图库；None 时读配置
        on_progress: 可选进度回调（GUI 用；CLI 不需要）

    Returns:
        SearchOutcome
    """
    outcome = SearchOutcome()

    db, store = open_library(use_library)
    if store is not None:
        outcome.library_error = None
        if not refresh:
            match, cached = lookup_cache(store, image_path)
            if match is not None and cached:
                outcome.results = cached
                outcome.from_cache = True
                outcome.record_id = match.record.id
                outcome.match_kind = match.kind
                report_cache_hit(match, cached)
                return outcome

    # 联网搜索（延迟导入，避免服务模块反向依赖 cli）
    from imgsearch.cli import search_image

    results = search_image(image_path, engine=engine, min_similarity=min_similarity)
    outcome.results = results

    if store is not None and results:
        outcome.record_id = record_to_library(store, image_path, results)

    return outcome
