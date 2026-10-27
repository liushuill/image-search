"""
带「闪一下」背景的提示标签

用法场景：搜索页右上角那条状态/提示。拖拽失败之类的事情如果毫无视觉变化，
用户很容易以为"没反应"。所以给这行字加一层背景色：**亮起来很快，然后缓缓落到
一个还能看清文字的颜色**，让它一眼被注意到，又不会长时间刺眼。

设计要点：
- 颜色按语义选：橙（`WARN`）= 提醒 / 蓝（`ACCENT`）= 进行中 / 红（`ERR`）= 失败
- 峰值不遮字：透明度最高只到 0.55，文字颜色保持原样
- 落到的底色（0.16）仍然保留，让人知道"这里有一句提示"
"""

from PySide6 import QtCore, QtWidgets

from imgsearch_gui import style

# 动画曲线参数（抽成常量，测试可以直接引用）
DURATION_MS = 750      # 总时长
RISE_FRACTION = 0.12   # 前 12% 用来"快速亮起来"（≈90ms）
PEAK_ALPHA = 0.55      # 峰值不透明度
BASE_ALPHA = 0.16      # 回落后的稳定底色：浅到不影响读字


def alpha_at(t: float) -> float:
    """
    动画进度 ``t``（0→1）对应的背景不透明度。

    - 前 :data:`RISE_FRACTION` 段：从 0 快升到峰值（easeOut，越快越接近峰值）
    - 之后：从峰值**缓降**到稳定底色（easeOutCubic，尾部很慢）

    这两段的形状就是需求里说的「一开始亮度较快提升，然后缓缓降低」。
    """
    t = max(0.0, min(1.0, float(t)))
    if t < RISE_FRACTION:
        k = t / RISE_FRACTION
        eased = 1.0 - (1.0 - k) ** 2          # easeOutQuad：起步快、接近峰值时变缓
        return PEAK_ALPHA * eased
    k = (t - RISE_FRACTION) / (1.0 - RISE_FRACTION)
    # k=0 时是峰值，k=1 时落到稳定底色；(1-k)^3 让衰减越来越慢（尾部拖得久）
    remaining = (1.0 - k) ** 3
    return BASE_ALPHA + (PEAK_ALPHA - BASE_ALPHA) * remaining


class FlashLabel(QtWidgets.QLabel):
    """文字 + 可选的一次背景闪动；闪完停在稳定底色上。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._text_color = style.MUTED
        self._tint = style.WARN          # 默认橙色（提醒类）；可按需换成蓝/红
        self._alpha = 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(DURATION_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
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
            flash: 是否播一次背景闪动（播完停在稳定底色）
            tint: 背景色，省略则沿用上一次（默认 `style.WARN` 橙）。
                  语义：橙=提醒、蓝=进行中、红=失败。
        """
        self.setText(text)
        if color:
            self._text_color = color
        if tint:
            self._tint = tint
        if flash:
            self._anim.stop()
            self._anim.start()
        else:
            self._alpha = 0.0
            self._apply()

    def clear_tint(self) -> None:
        """去掉背景（例如开始新一轮搜索时）"""
        self._anim.stop()
        self._alpha = 0.0
        self._apply()

    # ── 内部 ────────────────────────────────────

    def _on_tick(self, t: float) -> None:
        self._alpha = alpha_at(t)
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
