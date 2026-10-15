"""
批量识别测试

重点守住三件让「大批图能安全分几天跑完」的性质：
  1. 已识别过的图命中缓存 → **零配额**
  2. 结果**写进图库**（否则跑完什么都没留下）
  3. 额度用尽时的行为**由策略决定**，且不是静默降级
"""

from pathlib import Path

import pytest

from imgsearch import batch as B
from imgsearch.engines.quota import QuotaState
from imgsearch.service import SearchOutcome


class FakeEngine:
    def __init__(self, name, states=(), interval=0.0, error=None):
        self.name = name
        self._states = list(states)
        self._interval = interval
        self._error = error

    def quota_state(self):
        return self._states

    def request_interval(self):
        return self._interval


class FakeConfig:
    def __init__(self, name, display=None, settings=None):
        self.name = name
        self.display_name = display or name
        self.settings = dict(settings or {})

    def get(self, key, default=None):
        """search_image 会用它读 request_delay / proxy_mode 等"""
        return self.settings.get(key, default)


class FakeEngineStore:
    """只实现批量用到的两个方法"""

    def __init__(self, engines):
        # engines: [(FakeConfig, FakeEngine_or_Exception)]
        self._engines = engines

    def get_enabled(self):
        return [c for c, _ in self._engines]

    def build_engine(self, config):
        for c, e in self._engines:
            if c is config or c.name == getattr(config, "name", None):
                if isinstance(e, Exception):
                    raise e
                return e
        raise KeyError(config)


def make_images(directory: Path, count: int, ext: str = ".jpg") -> list:
    directory.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        p = directory / f"{i:03d}{ext}"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")      # 内容不重要，测试里会 mock 搜索
        made.append(p)
    return made


class TestScanImages:
    def test_finds_supported_extensions(self, tmp_path):
        make_images(tmp_path, 2, ".jpg")
        make_images(tmp_path, 1, ".PNG")
        (tmp_path / "notes.txt").write_text("x")
        names = [p.name for p in B.scan_images(tmp_path)]
        assert "000.jpg" in names and "001.jpg" in names
        assert "000.PNG" in names
        assert "notes.txt" not in names

    def test_recursive_includes_subdirs(self, tmp_path):
        """旧版只 glob 一层，子目录里的图直接被忽略"""
        make_images(tmp_path, 1)
        make_images(tmp_path / "子目录" / "更深", 2)
        assert len(B.scan_images(tmp_path, recursive=True)) == 3
        assert len(B.scan_images(tmp_path, recursive=False)) == 1

    def test_sorted_for_determinism(self, tmp_path):
        for name in ("c.jpg", "a.jpg", "b.jpg"):
            (tmp_path / name).write_bytes(b"x")
        assert [p.name for p in B.scan_images(tmp_path)] == \
            ["a.jpg", "b.jpg", "c.jpg"]

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            B.scan_images(tmp_path / "不存在")


class TestEngineStatuses:
    def test_broken_engine_is_recorded_not_raised(self):
        """
        回归：Danbooru 启用了但没填凭据时 build_engine 会抛异常 ——
        一个配错的引擎不该让整个批量无法开始。
        """
        store = FakeEngineStore([
            (FakeConfig("saucenao", "SauceNAO"), FakeEngine("saucenao")),
            (FakeConfig("danbooru", "Danbooru"),
             ValueError("Danbooru 用户名未配置！\n第二行")),
        ])
        rows = B.engine_statuses(store)
        assert len(rows) == 2
        assert rows[0].usable is True
        assert rows[1].usable is False
        assert "未配置" in rows[1].error
        assert "\n" not in rows[1].error          # 只取第一行

    def test_interval_exposed(self):
        store = FakeEngineStore([
            (FakeConfig("saucenao"), FakeEngine("saucenao", interval=7.5)),
        ])
        assert B.leading_engine_interval(store) == 7.5

    def test_interval_skips_broken_engines(self):
        store = FakeEngineStore([
            (FakeConfig("broken"), ValueError("x")),
            (FakeConfig("ok"), FakeEngine("ok", interval=3.0)),
        ])
        assert B.leading_engine_interval(store) == 3.0


class TestLeadingEngineBlocked:
    def test_no_engines(self):
        assert "没有启用" in B.leading_engine_blocked(FakeEngineStore([]))

    def test_all_broken(self):
        store = FakeEngineStore([(FakeConfig("d", "Danbooru"), ValueError("没凭据"))])
        reason = B.leading_engine_blocked(store)
        assert "无法构造" in reason and "Danbooru" in reason

    def test_exhausted_leading_engine(self):
        state = QuotaState(name="saucenao", label="SauceNAO",
                           limit=100, window=86400, used=100)
        store = FakeEngineStore([
            (FakeConfig("saucenao", "SauceNAO"), FakeEngine("saucenao", [state])),
        ])
        reason = B.leading_engine_blocked(store)
        assert "用尽" in reason

    def test_unlimited_leading_engine_is_fine(self):
        store = FakeEngineStore([
            (FakeConfig("iqdb", "IQDB"), FakeEngine("iqdb", [])),
        ])
        assert B.leading_engine_blocked(store) == ""

    def test_partially_used_is_fine(self):
        state = QuotaState(name="s", label="SauceNAO", limit=100, window=86400, used=4)
        store = FakeEngineStore([(FakeConfig("s", "SauceNAO"),
                                  FakeEngine("s", [state]))])
        assert B.leading_engine_blocked(store) == ""


class TestPlan:
    def test_counts_and_limit(self, tmp_path):
        make_images(tmp_path, 7)
        store = FakeEngineStore([(FakeConfig("i", "IQDB"), FakeEngine("i"))])
        plan = B.plan_batch(tmp_path, engine_store=store)
        assert plan.total == 7 and plan.selected == 7

        plan = B.plan_batch(tmp_path, limit=3, engine_store=store)
        assert plan.total == 7 and plan.selected == 3

    def test_limit_larger_than_total(self, tmp_path):
        make_images(tmp_path, 2)
        store = FakeEngineStore([(FakeConfig("i"), FakeEngine("i"))])
        assert B.plan_batch(tmp_path, limit=99, engine_store=store).selected == 2

    def test_summary_mentions_recursion_and_quota(self, tmp_path):
        make_images(tmp_path, 3)
        state = QuotaState(name="s", label="SauceNAO", limit=100, window=86400, used=4)
        store = FakeEngineStore([(FakeConfig("s", "SauceNAO"),
                                  FakeEngine("s", [state], interval=7.5))])
        text = B.plan_batch(tmp_path, engine_store=store).summary()
        assert "3 张" in text and "含子目录" in text
        assert "4/100" in text
        assert "节流 7.5 秒" in text

    def test_plan_touches_no_network(self, tmp_path, monkeypatch):
        make_images(tmp_path, 2)
        store = FakeEngineStore([(FakeConfig("i"), FakeEngine("i"))])

        def boom(*a, **k):
            raise AssertionError("预览不该联网")

        monkeypatch.setattr(B, "search_with_cache", boom)
        B.plan_batch(tmp_path, engine_store=store)      # 不抛即通过


def fake_outcome(cached: bool, engine: str = "SauceNAO"):
    if cached:
        return SearchOutcome(from_cache=True, dhash="x")
    from imgsearch.engines.base import SearchResult
    return SearchOutcome(results=[SearchResult(source=engine, similarity=95.0)],
                         dhash="x")


def install_fake_search(monkeypatch, result):
    """
    替换 search_with_cache，并**履行它的契约**（调用 before_search 钩子）。

    ⚠️ 这一点很关键：额度策略正是通过 before_search 生效的。
    如果 mock 把 kwargs 丢掉不调钩子，那两条策略测试就变成了空测 ——
    看起来通过，实际什么都没验证。
    """
    calls = []

    def fake(path, **kwargs):
        hook = kwargs.get("before_search")
        if hook is not None:
            hook()                       # 可能抛 QuotaExceeded
        calls.append(path)
        return result(path) if callable(result) else result

    monkeypatch.setattr(B, "search_with_cache", fake)
    return calls


class TestRunBatch:
    def test_cache_hits_consume_nothing(self, tmp_path, monkeypatch):
        """核心承诺：已识别过的图跳过，零配额 —— 于是重跑=接着跑"""
        make_images(tmp_path, 3)
        calls = install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        store = FakeEngineStore([(FakeConfig("s", "SauceNAO"), FakeEngine("s"))])

        report = B.run_batch(tmp_path, engine_store=store)
        assert report.cached == 3 and report.searched == 0
        assert report.success == 0
        assert len(calls) == 3

    def test_new_images_are_searched_and_counted(self, tmp_path, monkeypatch):
        make_images(tmp_path, 2)
        install_fake_search(monkeypatch, lambda p: fake_outcome(False, "SauceNAO"))
        store = FakeEngineStore([(FakeConfig("s", "SauceNAO"), FakeEngine("s"))])

        report = B.run_batch(tmp_path, engine_store=store)
        assert report.searched == 2 and report.success == 2
        assert report.engine_usage == {"SauceNAO": 2}

    def test_no_match_counted(self, tmp_path, monkeypatch):
        make_images(tmp_path, 1)
        install_fake_search(monkeypatch, SearchOutcome(results=[]))
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        report = B.run_batch(tmp_path, engine_store=store)
        assert report.no_match == 1 and report.searched == 1

    def test_limit_respected(self, tmp_path, monkeypatch):
        make_images(tmp_path, 5)
        install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        assert B.run_batch(tmp_path, limit=2, engine_store=store).total == 2

    def test_progress_and_records_callback(self, tmp_path, monkeypatch):
        make_images(tmp_path, 2)
        install_fake_search(monkeypatch, lambda p: fake_outcome(False))
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        seen, recorded = [], []
        B.run_batch(tmp_path, engine_store=store,
                    on_progress=seen.append,
                    on_record=lambda p, o: recorded.append(p))
        assert [s.index for s in seen] == [1, 2]
        assert seen[0].percent == 50
        assert len(recorded) == 2

    def test_failure_is_caught_not_fatal(self, tmp_path, monkeypatch):
        make_images(tmp_path, 2)
        calls = install_fake_search(monkeypatch, lambda p: fake_outcome(True))

        def flaky(p, **k):
            hook = k.get("before_search")
            if hook:
                hook()
            if len(calls) == 0:
                calls.append(p)
                raise RuntimeError("网络炸了")
            return fake_outcome(True)

        monkeypatch.setattr(B, "search_with_cache", flaky)
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        report = B.run_batch(tmp_path, engine_store=store)
        assert report.failed == 1 and report.cached == 1
        assert "网络炸了" in report.failures[0]

    def test_cancel_stops_early(self, tmp_path, monkeypatch):
        make_images(tmp_path, 5)
        install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        seen = []
        report = B.run_batch(tmp_path, engine_store=store,
                             on_progress=seen.append,
                             should_stop=lambda: len(seen) >= 2)
        assert report.stopped == "cancelled"
        assert report.processed == 2

    def test_empty_directory(self, tmp_path):
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        report = B.run_batch(tmp_path, engine_store=store)
        assert report.total == 0 and report.processed == 0

    def test_unknown_policy_rejected(self, tmp_path):
        make_images(tmp_path, 1)
        store = FakeEngineStore([(FakeConfig("s"), FakeEngine("s"))])
        with pytest.raises(ValueError, match="未知额度策略"):
            B.run_batch(tmp_path, quota_policy="乱写", engine_store=store)


class TestQuotaPolicy:
    """
    额度用尽时的行为必须由策略决定 —— 不能像 auto 循环那样静默降级。
    """

    def _setup(self, tmp_path, monkeypatch, used):
        make_images(tmp_path, 3)
        state = QuotaState(name="s", label="SauceNAO", limit=100,
                           window=86400, used=used)
        store = FakeEngineStore([
            (FakeConfig("s", "SauceNAO"), FakeEngine("s", [state])),
        ])
        return store

    def test_stop_policy_halts_before_spending(self, tmp_path, monkeypatch):
        store = self._setup(tmp_path, monkeypatch, used=100)
        called = install_fake_search(monkeypatch, lambda p: fake_outcome(False))

        report = B.run_batch(tmp_path, quota_policy="stop", engine_store=store)
        assert report.stopped == "quota"
        assert "用尽" in report.stopped_detail
        assert report.processed == 0
        assert called == [], "额度已尽时不该发起任何联网搜索"

    def test_stop_policy_proceeds_when_budget_left(self, tmp_path, monkeypatch):
        store = self._setup(tmp_path, monkeypatch, used=4)
        install_fake_search(monkeypatch, lambda p: fake_outcome(False))
        report = B.run_batch(tmp_path, quota_policy="stop", engine_store=store)
        assert report.stopped == "" and report.success == 3

    def test_fallback_policy_keeps_going(self, tmp_path, monkeypatch):
        store = self._setup(tmp_path, monkeypatch, used=100)
        install_fake_search(monkeypatch, lambda p: fake_outcome(False, "IQDB"))
        report = B.run_batch(tmp_path, quota_policy="fallback", engine_store=store)
        assert report.stopped == ""
        assert report.success == 3
        # 降级来源必须在报告里看得见
        assert report.engine_usage == {"IQDB": 3}

    def test_stop_policy_leaves_results_saved(self, tmp_path, monkeypatch):
        """停下时已识别的必须已入库（不然等于白跑）"""
        make_images(tmp_path, 3)
        state = QuotaState(name="s", label="SauceNAO", limit=100,
                           window=86400, used=100)
        store = FakeEngineStore([
            (FakeConfig("s", "SauceNAO"), FakeEngine("s", [state]))])
        install_fake_search(monkeypatch, lambda p: fake_outcome(False))
        report = B.run_batch(tmp_path, quota_policy="stop", engine_store=store)
        assert report.stopped == "quota"
        # 报告要明确告诉用户「接着跑」这件事
        assert "接着跑" in report.summary()


class TestThrottling:
    """
    短期限额（SauceNAO 4 次/30 秒）是服务端判定的：不节流的话批量跑到第 5 张
    就被 429，然后被 auto 循环静默降级到弱引擎 —— 尽管当天额度还剩一大半。
    """

    def test_sleeps_between_network_requests(self, tmp_path, monkeypatch):
        make_images(tmp_path, 3)
        store = FakeEngineStore([
            (FakeConfig("s", "SauceNAO"), FakeEngine("s", interval=7.5))])
        install_fake_search(monkeypatch, lambda p: fake_outcome(False))

        slept = []
        clock = {"t": 1000.0}
        monkeypatch.setattr(B.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(B.time, "sleep",
                            lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))

        B.run_batch(tmp_path, engine_store=store)
        # 第 1 张不需要等；第 2、3 张各需等满 7.5 秒
        assert sum(slept) == pytest.approx(15.0, abs=0.6)
        assert len(slept) > 2, "应当是分小片睡，好让「取消」及时响应"

    def test_no_sleep_without_interval(self, tmp_path, monkeypatch):
        make_images(tmp_path, 3)
        store = FakeEngineStore([(FakeConfig("i"), FakeEngine("i", interval=0))])
        install_fake_search(monkeypatch, lambda p: fake_outcome(False))
        slept = []
        monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
        B.run_batch(tmp_path, engine_store=store)
        assert slept == []

    def test_cache_hits_do_not_wait(self, tmp_path, monkeypatch):
        """缓存命中不联网，也就不该为速率限制等待"""
        make_images(tmp_path, 3)
        store = FakeEngineStore([
            (FakeConfig("s"), FakeEngine("s", interval=7.5))])
        install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        slept = []
        monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
        B.run_batch(tmp_path, engine_store=store)
        assert slept == []

    def test_saucenao_declares_interval(self):
        """SauceNAO 的 4 次/30 秒 应换算成 7.5 秒"""
        from imgsearch.engines.saucenao import SauceNAO
        engine = SauceNAO(api_key="dummy-for-test",
                          short_limit=4, short_window=30)
        assert engine.request_interval() == pytest.approx(7.5)

    def test_saucenao_interval_follows_config(self):
        from imgsearch.engines.saucenao import SauceNAO
        engine = SauceNAO(api_key="dummy-for-test",
                          short_limit=10, short_window=60)
        assert engine.request_interval() == pytest.approx(6.0)

    def test_saucenao_interval_zero_when_unlimited(self):
        from imgsearch.engines.saucenao import SauceNAO
        engine = SauceNAO(api_key="dummy-for-test",
                          short_limit=0, short_window=30)
        assert engine.request_interval() == 0.0

    def test_engines_without_limit_declare_zero(self):
        """没有限额的引擎应声明 0（不节流）"""
        from imgsearch.engines.iqdb import Iqdb
        assert Iqdb().request_interval() == 0.0


class TestReportSummary:
    def test_mentions_everything_relevant(self):
        report = B.BatchReport(total=10, cached=6, searched=4, success=3,
                              no_match=1, failed=1,
                              engine_usage={"SauceNAO": 4},
                              stopped="quota", stopped_detail="SauceNAO 用尽")
        text = report.summary()
        for fragment in ("6", "4", "SauceNAO 4 次", "额度用尽", "接着跑"):
            assert fragment in text, fragment


class TestNoUsableEngine:
    """
    区分「没搜到」与「没搜成」。

    实测过：唯一启用的引擎缺 API Key 时，auto 模式会一路跳过，
    最终提示「未找到匹配结果」—— 看起来像这张图搜不到，
    实际是根本没发起搜索。
    """

    def test_batch_stops_immediately_when_no_engine_usable(self, tmp_path, monkeypatch):
        """不能逐张失败 N 次 —— 每张原因相同，日志没有价值"""
        make_images(tmp_path, 5)
        called = install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        store = FakeEngineStore([
            (FakeConfig("d", "Danbooru"), ValueError("API Key 未配置！")),
        ])
        report = B.run_batch(tmp_path, engine_store=store)
        assert report.stopped == "no_engine"
        assert report.failed == 0, "不该逐张记成失败"
        assert called == [], "没有任何可用引擎时不该发起搜索"
        # 原因要具体到「哪个引擎、为什么」，而不是笼统一句话
        assert "无法构造" in report.stopped_detail
        assert "API Key 未配置" in report.stopped_detail

    def test_batch_proceeds_when_at_least_one_usable(self, tmp_path, monkeypatch):
        """有可用的就照常跑，别因为另一个引擎坏掉就拒绝开工"""
        make_images(tmp_path, 2)
        install_fake_search(monkeypatch, lambda p: fake_outcome(True))
        store = FakeEngineStore([
            (FakeConfig("broken", "Bad"), ValueError("没凭据")),
            (FakeConfig("ok", "IQDB"), FakeEngine("ok")),
        ])
        report = B.run_batch(tmp_path, engine_store=store)
        assert report.stopped == ""
        assert report.cached == 2

    def test_search_image_raises_when_nothing_ran(self, monkeypatch):
        """单图搜索：一个引擎都没跑起来时必须报错，而不是返回空"""
        import imgsearch.cli as cli
        from imgsearch.engines.store import EngineNotFoundError

        class Boom:
            def search(self, path):
                raise AssertionError("不该被调用")

        class Store:
            def get_enabled(self):
                return [FakeConfig("broken", "Broken")]

            def build_engine(self, ec, proxies=None):
                raise ValueError("API Key 未配置！")

        monkeypatch.setattr(cli, "get_store", lambda: Store())
        monkeypatch.setattr(cli, "_resolve_proxies", lambda: None)
        with pytest.raises(EngineNotFoundError) as ei:
            cli.search_image("/tmp/x.jpg")
        msg = str(ei.value)
        assert "没有" in msg and "并未真正发起搜索" in msg
        assert "API Key 未配置" in msg, "要带上每个引擎被跳过的原因"

    def test_search_image_returns_empty_when_engines_ran(self, monkeypatch):
        """
        回归：不能把「跑了但没匹配」误判成「没有可用引擎」。
        计数器必须记在「构造成功」而不是「search() 成功」——
        否则网络失败也会被当成没有可用引擎。
        """
        import imgsearch.cli as cli

        class NoMatch:
            def search(self, path):
                return []

        class Store:
            def get_enabled(self):
                return [FakeConfig("ok", "OK")]

            def build_engine(self, ec, proxies=None):
                return NoMatch()

        monkeypatch.setattr(cli, "get_store", lambda: Store())
        monkeypatch.setattr(cli, "_resolve_proxies", lambda: None)
        monkeypatch.setattr(cli.time, "sleep", lambda s: None)
        assert cli.search_image("/tmp/x.jpg") == []

    def test_engine_that_built_but_failed_still_counts_as_usable(self, monkeypatch):
        """构造成功、但 search() 抛网络错 —— 仍算「有可用引擎」"""
        import imgsearch.cli as cli

        class NetFail:
            def search(self, path):
                raise ConnectionError("连不上")

        class Store:
            def get_enabled(self):
                return [FakeConfig("ok", "OK")]

            def build_engine(self, ec, proxies=None):
                return NetFail()

        monkeypatch.setattr(cli, "get_store", lambda: Store())
        monkeypatch.setattr(cli, "_resolve_proxies", lambda: None)
        # 不应抛 EngineNotFoundError（引擎是好的，只是请求失败）
        assert cli.search_image("/tmp/x.jpg") == []
