"""
滑动窗口限流计数器测试

用可注入的时钟，避免测试依赖真实时间（也不用 sleep）。
"""

import pytest

from imgsearch.engines.quota import QuotaExceeded, SlidingWindowQuota


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(tmp_path, limit, window, clock):
    return SlidingWindowQuota(
        name="t", limit=limit, window=window,
        path=tmp_path / "quota.json", now=clock, label="测试引擎",
    )


class TestUnlimited:
    def test_zero_limit_is_unlimited(self, tmp_path):
        q = make(tmp_path, 0, 60, FakeClock())
        assert q.unlimited is True
        assert q.remaining() == -1
        for _ in range(50):
            q.check()
            q.record()
        q.check()   # 不应抛异常

    def test_zero_window_is_unlimited(self, tmp_path):
        """窗口为 0 时无法计算释放时刻，按不限制处理（否则会算出负数）"""
        q = make(tmp_path, 5, 0, FakeClock())
        assert q.unlimited is True
        for _ in range(10):
            q.check()
            q.record()


class TestWindow:
    def test_check_passes_below_limit(self, tmp_path):
        clock = FakeClock()
        q = make(tmp_path, 3, 60, clock)
        for _ in range(3):
            q.check()
            q.record()
        assert q.used() == 3

    def test_check_raises_at_limit(self, tmp_path):
        clock = FakeClock()
        q = make(tmp_path, 2, 60, clock)
        q.check(); q.record()
        q.check(); q.record()
        with pytest.raises(QuotaExceeded) as exc:
            q.check()
        msg = str(exc.value)
        assert "测试引擎" in msg
        assert "2 次/60s" in msg

    def test_expired_entries_are_released(self, tmp_path):
        clock = FakeClock()
        q = make(tmp_path, 2, 60, clock)
        q.check(); q.record()
        q.check(); q.record()
        with pytest.raises(QuotaExceeded):
            q.check()

        clock.advance(61)          # 窗口滑过去
        q.check()                  # 应重新可用
        assert q.used() == 0

    def test_sliding_not_fixed(self, tmp_path):
        """滑动窗口：只释放真正过期的那几条"""
        clock = FakeClock()
        q = make(tmp_path, 2, 60, clock)
        q.record()                 # t=0
        clock.advance(30)
        q.record()                 # t=30
        clock.advance(31)          # t=61，第一条过期，第二条还在
        assert q.used() == 1
        q.check()                  # 还有额度

    def test_reset_in(self, tmp_path):
        clock = FakeClock()
        q = make(tmp_path, 2, 60, clock)
        q.record()
        assert 55 <= q.reset_in() <= 60

    def test_remaining(self, tmp_path):
        clock = FakeClock()
        q = make(tmp_path, 3, 60, clock)
        assert q.remaining() == 3
        q.record()
        assert q.remaining() == 2


class TestPersistence:
    def test_counts_persist_across_instances(self, tmp_path):
        """跨进程有效：CLI 反复调用不能绕过限流"""
        clock = FakeClock()
        path = tmp_path / "quota.json"

        a = SlidingWindowQuota("t", 3, 60, path=path, now=clock)
        a.record(); a.record()

        b = SlidingWindowQuota("t", 3, 60, path=path, now=clock)
        assert b.used() == 2
        b.record()
        with pytest.raises(QuotaExceeded):
            b.check()

    def test_corrupt_file_does_not_crash(self, tmp_path):
        path = tmp_path / "quota.json"
        path.write_text("{ not json", encoding="utf-8")
        q = SlidingWindowQuota("t", 3, 60, path=path, now=FakeClock())
        assert q.used() == 0

    def test_legacy_file_format_is_readable(self, tmp_path):
        """沿用旧版 saucenao_quota.json 的 {"timestamps": [...]} 结构"""
        import json
        clock = FakeClock()
        path = tmp_path / "quota.json"
        path.write_text(json.dumps({"timestamps": [clock.now, clock.now]}),
                        encoding="utf-8")
        q = SlidingWindowQuota("t", 5, 3600, path=path, now=clock)
        assert q.used() == 2
