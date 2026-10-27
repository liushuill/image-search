"""
提示文字的背景动效

需求：不同语义用不同强度 —— 蓝/绿平滑、橙更快、红闪。
所以这里的断言是"档位之间的相对关系"，而不是固定数值。
"""

import pytest

pytest.importorskip("PySide6")

from imgsearch_gui import style                              # noqa: E402
from imgsearch_gui.widgets import flash_label as fl          # noqa: E402


class TestProfiles:
    def test_colors_map_to_expected_profiles(self):
        assert fl.profile_for(style.ACCENT) is fl.SMOOTH   # 进行中
        assert fl.profile_for(style.OK) is fl.SMOOTH       # 成功
        assert fl.profile_for(style.WARN) is fl.QUICK      # 提醒
        assert fl.profile_for(style.ERR) is fl.BLINK       # 失败

    def test_unknown_color_falls_back(self):
        assert fl.profile_for("#123456") is fl.DEFAULT_PROFILE

    def test_orange_is_faster_and_brighter_than_smooth(self):
        assert fl.QUICK.duration_ms < fl.SMOOTH.duration_ms
        assert fl.QUICK.peak > fl.SMOOTH.peak

    def test_smooth_does_not_flash(self):
        assert not fl.SMOOTH.blinking
        values = [fl.alpha_at(i / 100, fl.SMOOTH) for i in range(101)]
        # 单调先升后降，不出现明灭
        peak_i = values.index(max(values))
        assert all(a <= b + 1e-9 for a, b in zip(values[:peak_i], values[peak_i:][0:1]))
        assert peak_i > 0


class TestAlphaCurve:
    def test_starts_transparent(self):
        for prof in (fl.SMOOTH, fl.QUICK):
            assert fl.alpha_at(0.0, prof) == 0.0

    def test_rise_is_fast_for_quick(self):
        assert fl.alpha_at(fl.QUICK.rise * 0.99, fl.QUICK) > fl.QUICK.peak * 0.9

    def test_settles_on_base(self):
        for prof in (fl.SMOOTH, fl.QUICK):
            assert abs(fl.alpha_at(1.0, prof) - prof.base) < 1e-9
            assert prof.base > 0.05          # 底色要留着，让人知道这里有提示

    def test_monotonic_after_peak(self):
        for prof in (fl.SMOOTH, fl.QUICK):
            values = [fl.alpha_at(prof.rise + i / 50 * (1 - prof.rise), prof)
                      for i in range(51)]
            assert all(a >= b - 1e-9 for a, b in zip(values, values[1:]))

    def test_peak_is_readable(self):
        for prof in (fl.SMOOTH, fl.QUICK):
            assert prof.peak <= 0.6

    def test_blink_alternates(self):
        """红是"闪"：同一次动画里要有多次明灭，而不是渐变"""
        values = [fl.alpha_at(i / 200, fl.BLINK) for i in range(201)]
        on_off_transitions = sum(
            1 for a, b in zip(values, values[1:]) if (a > 0) != (b > 0))
        assert on_off_transitions >= 4

    def test_blink_ends_transparent(self):
        assert fl.alpha_at(1.0, fl.BLINK) == 0.0

    def test_clamps_out_of_range(self):
        assert fl.alpha_at(-1, fl.QUICK) == 0.0
        assert abs(fl.alpha_at(2, fl.QUICK) - fl.QUICK.base) < 1e-9


class TestFlashLabel:
    def test_flash_applies_background(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("提示", flash=True)
            label._on_tick(0.6)
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

    def test_tint_selects_profile_and_color(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("正在搜索…", flash=True, tint=style.ACCENT)
            assert label._profile is fl.SMOOTH
            label._on_tick(0.5)
            assert "59,130,246" in label.styleSheet()      # ACCENT 的 rgb

            label.set_text("失败", flash=True, tint=style.ERR)
            assert label._profile is fl.BLINK
            label._on_tick(0.1)                            # 明灭相位亮着
            assert "220,38,38" in label.styleSheet()       # ERR 的 rgb
        finally:
            label.close()

    def test_tint_persists_between_calls(self, qapp):
        label = fl.FlashLabel("x")
        try:
            label.set_text("a", flash=True, tint=style.OK)
            label._on_tick(0.5)
            label.set_text("b", flash=True)
            label._on_tick(0.5)
            assert "22,163,74" in label.styleSheet()       # OK 的 rgb
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
