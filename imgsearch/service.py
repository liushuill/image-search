"""
搜索服务：图库缓存 + 联网搜索 + 结果入库

抽出来的目的：**CLI 与 GUI 共用同一套流程**。
否则两边各写一份「先查缓存、没命中才联网、完事入库」，
迟早出现行为不一致（一边复用了缓存、另一边又去烧配额）。

进度与说明统一用 ``print()`` 输出：CLI 直接看到；
GUI 通过 stdout 桥接转成信号（见 ``imgsearch_gui.workers``）。
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict

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
    dhash: str = ""                    # 内容指纹，导出时用
    library_error: Optional[str] = None

    @property
    def found(self) -> bool:
        return bool(self.results)


@dataclass(frozen=True)
class CredentialSpec:
    """
    一条待填写的凭据。

    用 dataclass 而不是元组：这个形状已经改过两次（先是三元组，
    后来加 required），元组每加一个字段就要改所有解包处。
    """

    env_name: str
    title: str
    description: str = ""
    required: bool = False
    mask: bool = True
    # 归属哪个引擎（凭据页按它分组）；空串表示「其他/全局」
    group: str = ""


def _env_name_for(ec, f) -> str:
    """一个 secret 字段实际落在哪个环境变量上（与 store 用同一实现）"""
    from imgsearch.engines.store import env_name_for_config
    return env_name_for_config(ec, f)


def declared_secrets() -> List[CredentialSpec]:
    """
    所有需要填写的凭据。

    **引擎 schema 是唯一权威来源**：展示名、说明、是否必填、是否打码都来自它。
    ``secrets.KNOWN_SECRETS`` 只作兜底 —— 引擎不可用时仍能在界面上列出来。

    ⚠️ 优先级方向很关键。反过来（KNOWN_SECRETS 优先）会出这种问题：
    同一份凭据两处都有描述，界面显示了旧那份「可选」，
    而引擎其实 required=True —— 用户照着跳过，然后撞上运行时报错。
    """
    from imgsearch.engines.store import get_store

    declared: Dict[str, CredentialSpec] = {}

    # ① 已知清单兜底（不知是否必填，先按可选）
    for env_name, desc in secrets.KNOWN_SECRETS.items():
        declared[env_name] = CredentialSpec(
            env_name=env_name, title=env_name, description=desc)

    # ② 引擎 schema 覆盖它（信息更具体）
    try:
        store = get_store()
    except Exception:                                     # noqa: BLE001
        store = None

    if store is not None:
    
        for ec in store.list_all():
            try:
                schema = ec.schema()
            except Exception:                             # noqa: BLE001
                continue
            secrets_of_engine = [f for f in schema if f.is_secret]
            if not secrets_of_engine:
                continue

            # 关掉「使用 API Key」的引擎不该在凭据页占位置 ——
            # 这个开关的用途正是「我不打算给这个引擎填凭据」。
            # ⚠️ 必须「先删掉兜底条目」而不是简单 continue：
            # KNOWN_SECRETS 那一步已经把它们加进去了，只跳过引擎的话
            # 条目会残留（就是漏了这一步才出的 bug）。
            # 适配器的凭据需求看实例配置（auth_mode）：
            # none → 不显示；query/basic → 显示且标为必填
            cls = None
            try:
                from imgsearch.engines.registry import resolve_engine_class
                cls = resolve_engine_class(ec)
            except Exception:                             # noqa: BLE001
                cls = None
            mode = (cls.auth_mode_for(ec.settings)
                    if cls is not None and hasattr(cls, "auth_mode_for")
                    else getattr(cls, "AUTH_MODE", "required") if cls else "required")

            if (not ec.get("use_api_key", True)) or mode == "none":
                # ⚠️ 必须用与「添加」时**完全相同**的变量名解析，
                # 否则 pop 的是派生名、留下的是实际名，凭据会残留
                for f in secrets_of_engine:
                    declared.pop(_env_name_for(ec, f), None)
                continue

            for f in secrets_of_engine:
                env_name = _env_name_for(ec, f)
                declared[env_name] = CredentialSpec(
                    env_name=env_name,
                    title=f.label,
                    description=f.help or f"由引擎「{ec.display_name}」使用",
                    # 适配器：能走到这里说明 auth_mode != none，两项都必需
                    required=bool(getattr(f, "required", False)) or mode == "required",
                    mask=bool(getattr(f, "mask", True)),
                    group=ec.display_name,
                )

    return list(declared.values())


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
                      results: List[SearchResult]):
    """
    把搜索结果记入图库（含缩略图缓存）。

    失败不打断主流程 —— 搜索本身已经成功了。

    Returns:
        写入的 :class:`ImageRecord`；失败返回 None
    """
    try:
        rec = store.upsert_image(image_path)
        store.save_results(rec.id, results)
        if get("cache_thumbnails", True):
            from imgsearch.library import thumbs
            thumbs.ensure(rec.dhash, image_path)
        print(f"\n📚 已记入图库（记录 id={rec.id}）—— 下次同图可直接复用结果")
        return rec
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
    before_search: Optional[Callable[[], None]] = None,
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
        before_search: 缓存未命中、**即将联网（要花配额）之前**调用的钩子。
            批量识别用它来判断额度是否还够，不够就抛
            :class:`~imgsearch.engines.quota.QuotaExceeded` 中止。
            放在这里是因为只有这个函数知道"接下来真的要花钱了"——
            在调用方判断会重复算一次指纹。

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
                outcome.dhash = match.record.dhash
                report_cache_hit(match, cached)
                return outcome

    # 联网搜索（延迟导入，避免服务模块反向依赖 cli）
    from imgsearch.cli import search_image

    if before_search is not None:
        before_search()

    results = search_image(image_path, engine=engine, min_similarity=min_similarity)
    outcome.results = results

    if store is not None and results:
        rec = record_to_library(store, image_path, results)
        if rec is not None:
            outcome.record_id = rec.id
            outcome.dhash = rec.dhash

    return outcome
