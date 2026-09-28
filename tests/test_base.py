"""
SearchResult 和 SearchEngine 基类测试
"""

from imgsearch.engines.base import SearchResult, SearchEngine


class TestSearchResult:
    """SearchResult 数据类测试"""

    def test_default_values(self):
        result = SearchResult(source="test", similarity=80.0)
        assert result.source == "test"
        assert result.similarity == 80.0
        assert result.pixiv_id is None
        assert result.pixiv_page == 0
        assert result.ext_urls == []
        assert result.highres_url is None

    def test_is_valid_with_similarity(self):
        result = SearchResult(source="test", similarity=50.0)
        assert result.is_valid() is True

    def test_is_valid_with_pixiv_id(self):
        result = SearchResult(source="test", similarity=0, pixiv_id="123456")
        assert result.is_valid() is True

    def test_is_valid_with_ext_urls(self):
        result = SearchResult(source="test", similarity=0, ext_urls=["https://example.com"])
        assert result.is_valid() is True

    def test_is_valid_all_empty(self):
        result = SearchResult(source="test", similarity=0)
        assert result.is_valid() is False

    def test_short_summary_full(self):
        result = SearchResult(
            source="test", similarity=85.5,
            pixiv_id="74267012", artist="画师A", title="作品B",
        )
        summary = result.short_summary()
        assert "Pixiv ID: 74267012" in summary
        assert "画师: 画师A" in summary
        assert "标题: 作品B" in summary
        assert "85.5%" in summary

    def test_short_summary_empty(self):
        result = SearchResult(source="test", similarity=0)
        assert result.short_summary() == "未找到匹配结果"

    def test_pixiv_image_id_without_page(self):
        result = SearchResult(source="test", similarity=0, pixiv_id="74267012")
        assert result.pixiv_image_id() == "74267012_p0.jpg"

    def test_pixiv_image_id_with_page(self):
        result = SearchResult(source="test", similarity=0, pixiv_id="74267012", pixiv_page=2)
        assert result.pixiv_image_id() == "74267012_p2.jpg"

    def test_pixiv_image_id_none(self):
        result = SearchResult(source="test", similarity=0)
        assert result.pixiv_image_id() is None


class TestSearchEngine:
    """SearchEngine 基类测试"""

    def test_default_init(self):
        engine = SearchEngine()
        assert engine.timeout == 30
        assert engine.proxies is None
        assert engine.api_url == ""
        assert engine.headers == {}
        assert engine.params == {}
        assert engine.api_key == ""
        assert engine.bypass_cfw is False

    def test_custom_init(self):
        engine = SearchEngine(
            timeout=60,
            proxies={"http": "http://proxy:8080"},
            api_url="https://api.example.com",
            headers={"User-Agent": "test"},
            params={"db": 999},
            api_key="secret123",
            bypass_cfw=True,
        )
        assert engine.timeout == 60
        assert engine.proxies == {"http": "http://proxy:8080"}
        assert engine.api_url == "https://api.example.com"
        assert engine.headers == {"User-Agent": "test"}
        assert engine.params == {"db": 999}
        assert engine.api_key == "secret123"
        assert engine.bypass_cfw is True

    def test_search_not_implemented(self):
        engine = SearchEngine()
        try:
            engine.search("test.jpg")
            assert False, "应该抛出 NotImplementedError"
        except NotImplementedError:
            pass

    def test_search_by_url_not_implemented(self):
        engine = SearchEngine()
        try:
            engine.search_by_url("https://example.com/image.jpg")
            assert False, "应该抛出 NotImplementedError"
        except NotImplementedError:
            pass

    def test_name(self):
        engine = SearchEngine()
        assert engine.name() == "SearchEngine"
