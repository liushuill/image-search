"""
滑动窗口限流计数器

SauceNAO（4 次/30 秒、100 次/24 小时）与 TraceMoe（实测 100 次/60 秒）
都是「N 次 / M 秒」的滑动窗口限额。把这段逻辑集中一处，
避免两份实现各自出错（旧实现把限额与窗口的判断散落在引擎内部）。

计数落盘到 ``data/`` 下，因此**跨进程也认账** —— CLI 反复调用不会绕过限流。
时钟可注入（``now``），便于测试。
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from imgsearch.config import DATA_DIR


@dataclass
class QuotaState:
    """
    某一层滑动窗口的额度状态。

    存在的理由：**配额文件是按引擎各自命名的**（SauceNAO 用的是历史文件名
    ``saucenao_quota.json``，而不是通用的 ``quota_saucenao.json``），
    所以外面不能自己重建一个计数器去读状态 —— 那样会读到另一个空文件，
    于是"剩余 100 次"永远不变。必须由引擎自己报。
    """

    name: str
    label: str = ""
    limit: int = 0
    window: int = 0
    used: int = 0
    reset_in: int = 0

    @property
    def unlimited(self) -> bool:
        return self.limit <= 0 or self.window <= 0

    @property
    def remaining(self) -> int:
        """剩余次数；不限制时返回 -1"""
        if self.unlimited:
            return -1
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return not self.unlimited and self.remaining <= 0

    def summary(self) -> str:
        if self.unlimited:
            return f"{self.label or self.name}：无限制"
        text = f"{self.label or self.name}：{self.used}/{self.limit}"
        if self.reset_in:
            hours = self.reset_in / 3600
            text += f"（约 {hours:.1f} 小时后释放）" if hours >= 1 else f"（{self.reset_in} 秒后释放）"
        return text


class QuotaExceeded(RuntimeError):
    """限额已用尽。消息面向用户，可直接展示。"""


class SlidingWindowQuota:
    """
    滑动窗口计数器。

    ``limit <= 0`` 或 ``window <= 0`` 都表示**不限制** ——
    这与配置界面上「0 = 无限制」的说明一致。
    """

    def __init__(self, name: str, limit: int, window: int,
                 path: Optional[Path] = None,
                 now: Optional[Callable[[], float]] = None,
                 label: str = ""):
        self.name = name
        self.limit = int(limit or 0)
        self.window = int(window or 0)
        self.label = label or name
        self.path = Path(path) if path else (DATA_DIR / f"quota_{name}.json")
        self._now = now or time.time
        self._timestamps: List[float] = []
        self._load()

    # ── 状态 ────────────────────────────────────

    @property
    def unlimited(self) -> bool:
        return self.limit <= 0 or self.window <= 0

    def _prune(self) -> bool:
        """移除已过期的时间戳；返回是否有变化"""
        if self.window <= 0:
            return False
        cutoff = self._now() - self.window
        before = len(self._timestamps)
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        return len(self._timestamps) != before

    def used(self) -> int:
        self._prune()
        return len(self._timestamps)

    def remaining(self) -> int:
        """剩余可用次数；不限制时返回 -1"""
        if self.unlimited:
            return -1
        return max(0, self.limit - self.used())

    def state(self) -> "QuotaState":
        """当前额度状态（供批量识别等功能做决策与展示）"""
        return QuotaState(name=self.name, label=self.label, limit=self.limit,
                          window=self.window, used=self.used(),
                          reset_in=self.reset_in())

    def reset_in(self) -> int:
        """距离最早一次请求过期还有多少秒；不适用时返回 0"""
        if self.unlimited or not self._timestamps:
            return 0
        self._prune()
        if not self._timestamps:
            return 0
        return max(0, int(self.window - (self._now() - min(self._timestamps))))

    # ── 检查与记录 ──────────────────────────────

    def check(self) -> None:
        """
        检查是否还能再发一次请求。

        Raises:
            QuotaExceeded: 限额已用尽
        """
        if self.unlimited:
            return
        self._prune()
        if len(self._timestamps) >= self.limit:
            secs = self.reset_in()
            mins = secs // 60
            window_desc = (
                f"{self.window // 3600}h" if self.window >= 3600
                else f"{self.window}s"
            )
            raise QuotaExceeded(
                f"\n❌ {self.label} 限额已用尽（{self.limit} 次/{window_desc}）\n"
                f"   当前窗口内已用：{len(self._timestamps)} 次\n"
                f"   最早一次请求将在约 {mins} 分钟后过期释放\n"
                f"   💡 可在引擎配置中调整限额与窗口"
            )

    def record(self) -> None:
        """记录一次请求"""
        self._timestamps.append(self._now())
        self._save()

    # ── 持久化 ──────────────────────────────────

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                ts = data.get("timestamps", [])
                if isinstance(ts, list):
                    self._timestamps = [float(t) for t in ts]
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                self._timestamps = []
        if self._prune():
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"timestamps": self._timestamps}),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"  ⚠️ 无法保存配额文件 {self.path}: {e}")

    def summary(self) -> str:
        """一行状态，供日志展示"""
        if self.unlimited:
            return f"{self.label}: 未限流"
        return f"{self.label}: 窗口内已用 {self.used()}/{self.limit}，剩余 {self.remaining()}"
