"""
批量识别

把「一个目录里的图逐个识别出来」做成可安全重跑的动作。关键是三件事：

1. **先查缓存再联网** —— 走 :func:`~imgsearch.service.search_with_cache`，
   已识别过的图直接命中缓存，**零配额消耗**。于是「重跑 = 接着上次跑」，
   天然支持断点续跑，也不会重复烧掉每日额度。
2. **结果写入图库** —— 否则跑完就什么都没留下（旧版 batch 正是如此）。
3. **联网前判断额度** —— 额度用尽时怎么办由配置项
   ``batch_quota_policy`` 决定，而不是写死在代码里：

   - ``stop``（默认）：停下来并说明还剩多少。不会不知情地拿弱引擎的结果。
   - ``fallback``：继续用其他引擎（覆盖可能差很多），
     但报告里会指明哪些结果来自降级引擎。

⚠️ 为什么需要这个策略项：auto 模式的引擎循环用 ``except Exception``
兜底后继续下一个引擎，而 ``QuotaExceeded`` 正是其子类 ——
于是额度耗尽会**被静默吞掉**，剩下的图全部悄悄换了弱引擎。
批量场景下这个默认行为特别危险。
"""

import contextlib
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from imgsearch.engines.quota import QuotaExceeded
from imgsearch.service import search_with_cache


def _engines(engine_store=None):
    """
    取引擎库。

    ⚠️ 这里只涉及**引擎库**（谁还有什么额度），不带图库 ——
    `search_with_cache` 自己会打开图库，传进来只会造成"store"指代不清。
    """
    if engine_store is not None:
        return engine_store
    from imgsearch.engines.store import get_store
    return get_store()

# 支持的图片扩展名（含 WebP / AVIF —— 溯源引擎基本都吃）
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif",
                    ".jfif", ".tif", ".tiff")

QUOTA_POLICIES = ("stop", "fallback")
DEFAULT_QUOTA_POLICY = "stop"


# ──────────────────────────────────────────────
#  数据模型
# ──────────────────────────────────────────────


@dataclass
class BatchPlan:
    """开始之前能给出的"要花多少"预览"""

    directory: str = ""
    total: int = 0            # 目录里找到的图片数
    selected: int = 0         # 本次计划处理的数量（受 limit 限制）
    recursive: bool = True
    quota_notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"目录：{self.directory}",
                 f"找到图片：{self.total} 张"
                 + ("（含子目录）" if self.recursive else "（仅当前目录）")]
        if self.selected != self.total:
            lines.append(f"本次处理：前 {self.selected} 张")
        lines.extend(self.quota_notes)
        return "\n".join(lines)


@dataclass
class BatchProgress:
    """每张图的进度（GUI 用它更新界面）"""

    index: int
    total: int
    path: str
    status: str                # cached / success / no_match / error / skipped
    message: str = ""
    engine: str = ""

    @property
    def percent(self) -> int:
        return int(self.index * 100 / self.total) if self.total else 0


@dataclass
class BatchReport:
    """跑完之后的结果"""

    directory: str = ""
    total: int = 0
    cached: int = 0            # 命中缓存（未消耗配额）
    searched: int = 0          # 真的联网搜了（消耗了配额）
    success: int = 0           # 联网搜索且找到结果
    no_match: int = 0          # 联网搜索但没找到
    failed: int = 0
    stopped: str = ""          # ""=跑完 / cancelled / quota / no_engine
    stopped_detail: str = ""
    engine_usage: Dict[str, int] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.cached + self.searched + self.failed

    def summary(self) -> str:
        lines = [
            f"处理 {self.processed}/{self.total} 张",
            f"  · 命中缓存（零配额）：{self.cached}",
            f"  · 联网搜索（耗配额）：{self.searched}"
            f"　（找到 {self.success} / 未找到 {self.no_match}）",
        ]
        if self.failed:
            lines.append(f"  · 失败：{self.failed}")
        if self.engine_usage:
            used = "、".join(f"{k} {v} 次" for k, v in
                            sorted(self.engine_usage.items(),
                                   key=lambda kv: -kv[1]))
            lines.append(f"  · 各引擎用量：{used}")
        if self.stopped == "quota":
            lines.append(f"⏸ 因额度用尽提前停止：{self.stopped_detail}")
            lines.append("   已识别的结果都已入库；明天再点一次会自动接着跑。")
        elif self.stopped == "no_engine":
            lines.append(f"⏸ 没有可用引擎：{self.stopped_detail}")
        elif self.stopped == "cancelled":
            lines.append("⏹ 已取消（已识别的结果都已入库）")
        return "\n".join(lines)


# ──────────────────────────────────────────────
#  扫描与预览
# ──────────────────────────────────────────────


def scan_images(directory, *, recursive: bool = True) -> List[Path]:
    """
    列出目录里的图片，按路径排序（保证多次运行顺序一致）。

    ⚠️ 旧版 batch 只做 ``glob("*.jpg")``，子目录里的图全被忽略。
    """
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"目录不存在：{directory}")

    found: List[Path] = []
    walker = root.rglob("*") if recursive else root.glob("*")
    for path in walker:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            found.append(path)
    return sorted(found)


@dataclass
class EngineStatus:
    """一个已启用引擎的可用性快照"""

    config: object = None
    states: List[object] = field(default_factory=list)
    error: str = ""
    interval: float = 0.0

    @property
    def usable(self) -> bool:
        return not self.error

    @property
    def display_name(self) -> str:
        return getattr(self.config, "display_name", "") or getattr(
            self.config, "name", "")

    @property
    def exhausted(self) -> bool:
        return any(getattr(s, "exhausted", False) for s in self.states)


def engine_statuses(engine_store=None) -> List[EngineStatus]:
    """
    已启用引擎的可用性快照，按优先级排序。

    ⚠️ 构造引擎可能失败（例如 Danbooru 启用了但没填凭据）—— 这里吞掉异常
    并记下原因，否则一个配错的引擎会让整个批量无法开始。
    """
    rows = []
    engines = _engines(engine_store)
    for ec in engines.get_enabled():
        try:
            engine = engines.build_engine(ec)
            rows.append(EngineStatus(
                config=ec,
                states=list(engine.quota_state()),
                interval=float(engine.request_interval() or 0.0),
            ))
        except Exception as e:                            # noqa: BLE001
            message = str(e).splitlines()[0] if str(e) else type(e).__name__
            rows.append(EngineStatus(config=ec, error=message))
    return rows


def leading_engine_blocked(engine_store=None) -> str:
    """
    优先级最高的「可用引擎」是否因额度耗尽而不可用。

    Returns:
        阻塞原因说明；没被阻塞则返回空字符串
    """
    statuses = engine_statuses(engine_store)
    if not statuses:
        return "没有启用任何搜索引擎"

    usable = [st for st in statuses if st.usable]
    if not usable:
        return "所有已启用的引擎都无法构造：" + "；".join(
            f"{st.display_name}（{st.error}）" for st in statuses)

    lead = usable[0]
    for state in lead.states:
        if getattr(state, "exhausted", False):
            return f"{state.label or lead.display_name} 的额度已用尽（{state.summary()}）"
    return ""


def leading_engine_interval(engine_store=None) -> float:
    """主引擎（优先级最高的可用引擎）声明的请求间隔；0 表示不节流"""
    for status in engine_statuses(engine_store):
        if status.usable:
            return status.interval
    return 0.0


def describe_quotas(engine_store=None) -> List[str]:
    """给预览用的一行行额度说明"""
    notes = []
    for status in engine_statuses(engine_store):
        if not status.usable:
            notes.append(f"  ⚠️ {status.display_name}：无法使用（{status.error}）")
            continue
        if not status.states:
            notes.append(f"  · {status.display_name}：无限制")
            continue
        for state in status.states:
            notes.append(f"  · {state.summary()}")
    if any(st.usable and st.interval > 0 for st in engine_statuses(engine_store)):
        pace = max(st.interval for st in engine_statuses(engine_store)
                   if st.usable)
        notes.append(f"  ⏱ 逐张节流 {pace:.1f} 秒（避免触发短期速率限制而被降级）")
    return notes


def plan_batch(directory, *, recursive: bool = True,
               limit: Optional[int] = None,
               engine_store=None) -> BatchPlan:
    """
    预览：目录里有多少图、本次打算处理多少、各引擎还剩多少额度。

    **不消耗任何配额**，也不读图片内容（只统计文件）。
    """
    paths = scan_images(directory, recursive=recursive)
    selected = len(paths) if limit is None or limit <= 0 else min(limit, len(paths))
    return BatchPlan(
        directory=str(directory),
        total=len(paths),
        selected=selected,
        recursive=recursive,
        quota_notes=describe_quotas(engine_store),
    )


# ──────────────────────────────────────────────
#  执行
# ──────────────────────────────────────────────


def run_batch(directory, *, recursive: bool = True,
              limit: Optional[int] = None,
              quota_policy: str = DEFAULT_QUOTA_POLICY,
              engine_store=None,
              on_progress: Optional[Callable[[BatchProgress], None]] = None,
              on_record: Optional[Callable[[Path, object], None]] = None,
              should_stop: Optional[Callable[[], bool]] = None,
              quiet: bool = True) -> BatchReport:
    """
    逐个识别目录里的图片。

    Args:
        directory: 要识别的目录
        recursive: 是否递归子目录
        limit: 本次最多处理多少张
        quota_policy: ``stop`` / ``fallback``，见模块文档
        engine_store: 引擎库（测试可注入）；默认取进程内单例
        on_progress: 每张图处理完回调一次
        on_record: 每张图处理完回调 ``(path, SearchOutcome)``，
            供调用方收集"本次刚搜到的"结果用于导出
        should_stop: 返回 True 时中止（用于「取消」按钮）
        quiet: 压制引擎/服务的逐条打印，只通过 on_progress 汇报

    Returns:
        :class:`BatchReport`
    """
    if quota_policy not in QUOTA_POLICIES:
        raise ValueError(f"未知额度策略：{quota_policy}（可用：{', '.join(QUOTA_POLICIES)}）")

    paths = scan_images(directory, recursive=recursive)
    if limit is not None and limit > 0:
        paths = paths[:limit]

    report = BatchReport(directory=str(directory), total=len(paths))

    # 先把惰性导入做完，再进入 redirect_stdout —— 否则首次导入发生在
    # 被重定向的 stdout 之下，任何依赖「当前 stdout 是谁」的模块级代码
    # 都会以奇怪的方式失败（见 cli._force_utf8 的注释）。
    import imgsearch.cli
    imgsearch.cli.search_image          # 触发模块完成导入（属性访问即用途）

    # 逐张节流：短期限额（如 SauceNAO 的 4 次/30 秒）是服务端判定的，
    # 连续猛打会在第 5 张就被 429，然后被 auto 循环**静默降级**到弱引擎。
    # 按主引擎声明的间隔放慢，就能让主引擎真的被每一张用到。
    interval = leading_engine_interval(engine_store)
    last_request_at = 0.0

    def wait_for_slot() -> bool:
        """按速率限制等待；返回 False 表示等待期间被取消。

        只读取外层的 last_request_at（不赋值），因此不需要 nonlocal。
        """
        if interval <= 0 or last_request_at <= 0:
            return True
        remaining = interval - (time.monotonic() - last_request_at)
        # 分小片睡，这样"取消"按钮能及时响应，而不是干等 7.5 秒
        while remaining > 0:
            if should_stop is not None and should_stop():
                return False
            chunk = min(0.25, remaining)
            time.sleep(chunk)
            remaining -= chunk
        return True

    def gate() -> None:
        """联网前调用：按策略决定是否中止"""
        if quota_policy == "fallback":
            return
        reason = leading_engine_blocked(engine_store)
        if reason:
            raise QuotaExceeded(reason)

    for index, path in enumerate(paths, 1):
        if should_stop is not None and should_stop():
            report.stopped = "cancelled"
            break

        status, message, engine_name = "success", "", ""
        outcome = None
        try:
            # 先等够间隔再联网（只在真的会联网时才等：缓存命中不需要）
            if not wait_for_slot():
                report.stopped = "cancelled"
                break
            swallow = contextlib.redirect_stdout(io.StringIO()) if quiet \
                else contextlib.nullcontext()
            with swallow:
                outcome = search_with_cache(
                    str(path),
                    on_progress=None,
                    before_search=gate,
                )

            if outcome.from_cache:
                status, message = "cached", "命中缓存，未消耗配额"
                report.cached += 1
            else:
                report.searched += 1
                last_request_at = time.monotonic()
                engines = [r.source for r in outcome.results if r.source]
                engine_name = engines[0] if engines else ""
                if engine_name:
                    report.engine_usage[engine_name] = \
                        report.engine_usage.get(engine_name, 0) + 1
                if outcome.results:
                    report.success += 1
                    status = "success"
                else:
                    report.no_match += 1
                    status, message = "no_match", "未找到匹配"

        except QuotaExceeded as e:
            report.stopped = "quota"
            report.stopped_detail = str(e)
            break
        except KeyboardInterrupt:
            report.stopped = "cancelled"
            break
        except Exception as e:                            # noqa: BLE001
            report.failed += 1
            status = "error"
            message = f"{type(e).__name__}: {e}"
            report.failures.append(f"{path.name}: {message}")

        if on_record is not None and outcome is not None:
            on_record(path, outcome)

        if on_progress is not None:
            on_progress(BatchProgress(index=index, total=len(paths),
                                      path=str(path), status=status,
                                      message=message, engine=engine_name))

    # 全部引擎都不可用时，从头就是跑不动的 —— 给一个明确的停止原因
    if not report.stopped and report.total and report.searched == 0 \
            and report.cached == 0 and report.failed == 0:
        report.stopped = "no_engine"
        report.stopped_detail = leading_engine_blocked(engine_store) or "没有可用引擎"

    return report
