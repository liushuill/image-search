"""
提示文字的「闪一下」背景

需求原文：一开始亮度较快提升，然后缓缓降低到一个能看清文字的色号。
所以曲线要满足三条：快速升起、缓慢回落、**落点仍然可读**（不是回到 0）。
"""

import pytest

pytest.importorskip("PySide6")

from imgsearch_gui.widgets import flash_label as fl     # noqa: E402


class TestAlphaCurve:
    def test_starts_transparent(self):
        assert fl.alpha_at(0.0) == 0.0

    def test_rises_fast(self):
        """前 12% 就要冲到峰值附近 —— 慢了就"闪"不起来"""
        at_rise_end = fl.alpha_at(fl.RISE_FRACTION * 0.99)
        assert at_rise_end > fl.PEAK_ALPHA * 0.9

    def test_peak_is_single(self):
        peak = max(fl.alpha_at(i / 100) for i in range(101))
        assert peak <= fl.PEAK_ALPHA + 1e-9

    def test_decays_slowly_to_readable_base(self):
        """回落后停在 BASE，而不是 0 —— 要"能看清文字"的底色"""
        assert abs(fl.alpha_at(1.0) - fl.BASE_ALPHA) < 1e-9
        assert fl.BASE_ALPHA > 0.05

    def test_monotonic_after_peak(self):
        """峰值之后只能往下走，不能反弹"""
        values = [fl.alpha_at(0.15 + i / 50 * 0.85) for i in range(51)]
        assert all(a >= b - 1e-9 for a, b in zip(values, values[1:]))

    def test_clamps_out_of_range(self):
        assert fl.alpha_at(-1) == 0.0
        assert abs(fl.alpha_at(2) - fl.BASE_ALPHA) < 1e-9

    def test_peak_is_readable(self):
        """峰值也不能把字淹掉（<0.6 时深色文字仍清晰）"""
        assert fl.PEAK_ALPHA <= 0.6


class TestFlashLabel:
    def test_flash_applies_background(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("提示", flash=True)
            label._on_tick(0.6)                  # 直接推到衰减中段
            css = label.styleSheet()
            assert "background:rgba(" in css
            assert "color:" in css               # 文字颜色必须保留
        finally:
            label.close()

    def test_non_flash_clears_background(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("提示", flash=True)
            label._on_tick(0.6)
            label.set_text("普通状态")
            assert "background" not in label.styleSheet()
        finally:
            label.close()

    def test_tint_color_can_be_overridden(self, qapp):
        """进行中用蓝、失败用红 —— 背景色按语义切换"""
        label = fl.FlashLabel("x")
        try:
            label.set_text("正在搜索…", flash=True, tint="#3b82f6")
            label._on_tick(0.5)
            assert "59,130,246" in label.styleSheet()      # style.ACCENT
            label.set_text("失败", flash=True, tint="#dc2626")
            label._on_tick(0.5)
            assert "220,38,38" in label.styleSheet()       # style.ERR
        finally:
            label.close()

    def test_tint_persists_between_calls(self, qapp):
        """不传 tint 时沿用上一次 —— 避免每次都写一遍"""
        label = fl.FlashLabel("x")
        try:
            label.set_text("a", flash=True, tint="#3b82f6")
            label._on_tick(0.5)
            label.set_text("b", flash=True)
            label._on_tick(0.5)
            assert "59,130,246" in label.styleSheet()
        finally:
            label.close()

    def test_clear_tint(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("提示", flash=True)
            label._on_tick(0.6)
            label.clear_tint()
            assert "background" not in label.styleSheet()
        finally:
            label.close()
