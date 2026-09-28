"""
auto 搜索的降级与阈值行为测试

用假引擎替换真实网络调用，精确验证「按权重顺序降级」「按引擎校准的阈值」
「proxy_mode 路由」这些判定规则。
"""

import pytest

from imgsearch.engines.base import SearchResult
from imgsearch.engines.store import EngineStore


class FakeEngine:
    """返回预设相似度的假引擎"""

    def __init__(self, name, similarities=(0,), error=None):
        self.name = name
        self.similarities = list(similarities)
        self.error = error
        self.calls = 0
        self.proxies_seen = "unset"

    def search(self, image_path):
        self.calls += 1
        if self.error:
            raise self.error
        return [SearchResult(source=self.name, similarity=s) for s in self.similarities]


@pytest.fixture
def rig(monkeypatch):
    """
    搭建一个可控的搜索环境。

    Returns:
        (search_image, store, engines_dict)
    """
    import imgsearch.cli as cli
    import imgsearch.config as cfg

    store = EngineStore()
    # 只留两个引擎，阈值分别是 60 / 45
    for name in ("ascii2d", "traceMoe", "danbooru"):
        store.set_enabled(name, False)
    store.update("sauceNAO", min_similarity=60, request_delay=0)
    store.update("iqdb", min_similarity=45, request_delay=0)

    engines = {}

    def fake_build(self, name_or_config, proxies=None):
        ec = store.get(name_or_config) if isinstance(name_or_config, str) else name_or_config
        eng = engines[ec.name]
        eng.proxies_seen = proxies
        return eng

    monkeypatch.setattr(EngineStore, "build_engine", fake_build)
    monkeypatch.setattr(cli, "get_store", lambda refresh=False: store)
    # cli 里是 `from imgsearch.config import get`，必须打在 cli 的命名空间上
    monkeypatch.setattr(cli, "get", lambda key, default=None: (
        "" if key == "proxy" else cfg.load_config().get(key, default)
    ))
    return cli.search_image, store, engines


class TestThreshold:
    def test_confident_hit_returns_immediately(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [95.2, 62.0])
        engines["iqdb"] = FakeEngine("iqdb", [53.0])

        results = search_image("x.png")

        assert results[0].similarity == 95.2
        assert engines["iqdb"].calls == 0, "达标后不该再试后面的引擎"

    def test_weak_hit_falls_through_to_next_engine(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [50.0])   # < 60 阈值
        engines["iqdb"] = FakeEngine("iqdb", [53.0])           # >= 45 阈值

        results = search_image("x.png")

        assert engines["sauceNAO"].calls == 1
        assert engines["iqdb"].calls == 1
        assert results[0].source == "iqdb", "低置信度结果不该直接胜出"

    def test_thresholds_are_per_engine_not_global(self, rig):
        """
        关键：IQDB 的 53% 在它自己的刻度上算命中。
        若用统一的 60% 阈值，IQDB 会被永久误杀。
        """
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [])      # 无匹配
        engines["iqdb"] = FakeEngine("iqdb", [53.0])

        results = search_image("x.png")
        assert results[0].source == "iqdb"

    def test_all_below_threshold_returns_best_margin(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [50.0])   # margin -10
        engines["iqdb"] = FakeEngine("iqdb", [43.0])           # margin -2  ← 更接近阈值

        results = search_image("x.png")
        assert results[0].source == "iqdb"

    def test_zero_override_disables_threshold(self, rig):
        """min_similarity=0 → 第一个有结果的引擎即采用"""
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [1.0])
        engines["iqdb"] = FakeEngine("iqdb", [99.0])

        results = search_image("x.png", min_similarity=0)

        assert results[0].source == "sauceNAO"
        assert engines["iqdb"].calls == 0

    def test_explicit_engine_ignores_threshold(self, rig):
        """-e 指定引擎时不套阈值：用户已经明确要用它"""
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [5.0])

        results = search_image("x.png", engine="sauceNAO")
        assert results[0].similarity == 5.0


class TestFallback:
    def test_engine_error_is_skipped(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", error=ValueError("未配置 Key"))
        engines["iqdb"] = FakeEngine("iqdb", [80.0])

        results = search_image("x.png")
        assert results[0].source == "iqdb"

    def test_explicit_engine_reraises_error(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", error=ValueError("未配置 Key"))
        with pytest.raises(ValueError, match="未配置 Key"):
            search_image("x.png", engine="sauceNAO")

    def test_empty_results_continue(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [])
        engines["iqdb"] = FakeEngine("iqdb", [70.0])

        results = search_image("x.png")
        assert results[0].source == "iqdb"

    def test_no_results_at_all(self, rig):
        search_image, store, engines = rig
        engines["sauceNAO"] = FakeEngine("sauceNAO", [])
        engines["iqdb"] = FakeEngine("iqdb", [])
        assert search_image("x.png") == []

    def test_unknown_engine_raises(self, rig):
        from imgsearch.engines.store import EngineNotFoundError
        search_image, store, engines = rig
        with pytest.raises(EngineNotFoundError):
            search_image("x.png", engine="nope")

    def test_no_enabled_engines_raises(self, rig, monkeypatch):
        from imgsearch.engines.store import EngineNotFoundError
        search_image, store, engines = rig
        for name in store.names():
            store.set_enabled(name, False)
        with pytest.raises(EngineNotFoundError, match="没有启用"):
            search_image("x.png")

    def test_order_follows_priority(self, rig):
        search_image, store, engines = rig
        store.move("iqdb", -1)          # iqdb 提到最前
        engines["iqdb"] = FakeEngine("iqdb", [90.0])
        engines["sauceNAO"] = FakeEngine("sauceNAO", [95.0])

        results = search_image("x.png")
        assert results[0].source == "iqdb", "应遵循用户设定的权重顺序"


class TestProxyRouting:
    def test_off_never_uses_proxy(self, rig, monkeypatch):
        import imgsearch.cli as cli
        import imgsearch.config as cfg
        search_image, store, engines = rig
        monkeypatch.setattr(cfg, "check_proxy", lambda *a, **k: True)
        monkeypatch.setattr(cli, "get", lambda key, default=None: (
            "http://127.0.0.1:7897" if key == "proxy"
            else cfg.load_config().get(key, default)
        ))
        store.update("sauceNAO", proxy_mode="off")
        engines["sauceNAO"] = FakeEngine("sauceNAO", [90.0])

        search_image("x.png", engine="sauceNAO")
        assert engines["sauceNAO"].proxies_seen is None

    def test_on_uses_proxy(self, rig, monkeypatch):
        import imgsearch.cli as cli
        import imgsearch.config as cfg
        search_image, store, engines = rig
        monkeypatch.setattr(cfg, "check_proxy", lambda *a, **k: True)
        monkeypatch.setattr(cli, "get", lambda key, default=None: (
            "http://127.0.0.1:7897" if key == "proxy"
            else cfg.load_config().get(key, default)
        ))
        store.update("sauceNAO", proxy_mode="on")
        engines["sauceNAO"] = FakeEngine("sauceNAO", [90.0])

        search_image("x.png", engine="sauceNAO")
        assert engines["sauceNAO"].proxies_seen == {
            "http": "http://127.0.0.1:7897",
            "https": "http://127.0.0.1:7897",
        }

    def test_auto_follows_global_and_downgrades_when_dead(self, rig, monkeypatch):
        """代理不是常开：探测失败应自动降级为直连，而不是直接失败"""
        import imgsearch.cli as cli
        import imgsearch.config as cfg
        search_image, store, engines = rig
        monkeypatch.setattr(cfg, "check_proxy", lambda *a, **k: False)
        monkeypatch.setattr(cli, "get", lambda key, default=None: (
            "http://127.0.0.1:7897" if key == "proxy"
            else cfg.load_config().get(key, default)
        ))
        store.update("sauceNAO", proxy_mode="auto")
        engines["sauceNAO"] = FakeEngine("sauceNAO", [90.0])

        search_image("x.png", engine="sauceNAO")
        assert engines["sauceNAO"].proxies_seen is None
