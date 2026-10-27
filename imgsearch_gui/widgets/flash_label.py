"""
带背景动效的提示标签

搜索页右上角那行状态文字。不同语义用**不同的动效**，而不是统一一个动画：

| 语义 | 颜色 | 动效 | 为什么 |
|---|---|---|---|
| 进行中 | 蓝 | 平滑、缓慢升起后微降 | 长时间停留，不能吵；兼作"它在跑"的指示 |
| 成功 | 绿 | 平滑（同上） | 结果本身已经足够醒目，再闪就过了 |
| 提醒 | 橙 | 平滑但**更快更亮** | 需要被注意到，但不必像错误那样刺眼 |
| 失败 | 红 | **闪**（明灭数次） | 真的要你停下来看日志 |

前两档是"渐变"，后两档一快一闪 —— 强度递增。
"""

from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from imgsearch_gui import style


@dataclass(frozen=True)
class Profile:
    """一段背景动效的参数"""

    duration_ms: int
    rise: float          # 前多大比例用来升到峰值（越小越"蹿"）
    peak: float          # 峰值不透明度
    base: float          # 落定后的稳定不透明度
    blinks: int = 0      # >0 表示改用明灭模式（红）

    @property
    def blinking(self) -> bool:
        return self.blinks > 0


# 三档：平滑 / 加快 / 明灭
SMOOTH = Profile(duration_ms=900, rise=0.35, peak=0.34, base=0.15)
QUICK = Profile(duration_ms=500, rise=0.15, peak=0.52, base=0.16)
BLINK = Profile(duration_ms=750, rise=0.0, peak=0.55, base=0.0, blinks=3)

# 颜色 → 动效。用色值而不是名字做键，调用方传 style.XXX 即可
PROFILES = {
    style.ACCENT: SMOOTH,     # 进行中：蓝
    style.OK: SMOOTH,         # 成功：绿
    style.WARN: QUICK,        # 提醒：橙（快）
    style.ERR: BLINK,         # 失败：红（闪）
}
DEFAULT_PROFILE = QUICK


def profile_for(tint: str) -> Profile:
    """这个背景色该用哪档动效"""
    return PROFILES.get(tint, DEFAULT_PROFILE)


def alpha_at(t: float, profile: Profile = QUICK) -> float:
    """
    动画进度 ``t``（0→1）对应的背景不透明度。

    渐变（蓝/绿/橙）：
      - 前 ``rise`` 段：0 → 峰值（easeOut，起步快）
      - 之后：峰值 → 稳定底色（easeOutCubic，尾部拖得久）

    明灭（红）：
      - ``blinks`` 次硬切换，亮/暗各半 —— 明显的"闪"而不是"渐变"
    """
    t = max(0.0, min(1.0, float(t)))

    if profile.blinking:
        if t >= 1.0:
            return 0.0                       # 闪完停在关闭状态
        phase = (t * profile.blinks) % 1.0
        return profile.peak if phase < 0.5 else 0.0

    if t < profile.rise:
        k = t / profile.rise if profile.rise else 1.0
        eased = 1.0 - (1.0 - k) ** 2          # easeOutQuad
        return profile.peak * eased

    if profile.rise >= 1.0:
        return profile.base
    k = (t - profile.rise) / (1.0 - profile.rise)
    remaining = (1.0 - k) ** 3                # easeOutCubic：衰减越来越慢
    return profile.base + (profile.peak - profile.base) * remaining


class FlashLabel(QtWidgets.QLabel):
    """文字 + 一次背景动效；渐变档结束后停在稳定底色，明灭档回到透明。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._text_color = style.MUTED
        self._tint = style.WARN
        self._profile = profile_for(self._tint)
        self._alpha = 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self._profile.duration_ms)
        self._anim.valueChanged.connect(self._on_tick)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Linear)   # 曲线由 alpha_at 负责
        self._apply()

    # ── 对外 ────────────────────────────────────

    def set_text(self, text: str, color: str = None, flash: bool = False,
                 tint: str = None) -> None:
        """
        设置文字。

        Args:
            color: 文字颜色，省略则沿用上一次
            flash: 是否播一次背景动效
            tint: 背景色（决定动效档位），省略则沿用上一次
        """
        self.setText(text)
        if color:
            self._text_color = color
        if tint:
            self._tint = tint
            self._profile = profile_for(tint)
        if flash:
            self._anim.stop()
            self._anim.setDuration(self._profile.duration_ms)
            self._alpha = 0.0
            self._anim.start()
        else:
            self._anim.stop()
            self._alpha = 0.0
            self._apply()

    def clear_tint(self) -> None:
        self._anim.stop()
        self._alpha = 0.0
        self._apply()

    # ── 内部 ────────────────────────────────────

    def _on_tick(self, t: float) -> None:
        self._alpha = alpha_at(t, self._profile)
        self._apply()

    def _apply(self) -> None:
        if self._alpha <= 0.001:
            self.setStyleSheet(f"color:{self._text_color};")
            return
        r, g, b = _rgb(self._tint)
        self.setStyleSheet(
            f"color:{self._text_color};"
            f"background:rgba({r},{g},{b},{self._alpha:.3f});"
            "border-radius:6px; padding:2px 8px;"
        )


def _rgb(hex_color: str):
    """``#d97706`` → ``(217, 119, 6)``"""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
