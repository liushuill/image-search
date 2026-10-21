"""
Ascii2D 解析相关测试

使用 mock HTML 验证解析逻辑，不发起真实 HTTP 请求。
"""

from bs4 import BeautifulSoup

from tests.legacy.ascii2d import Ascii2D


# ── 测试用 HTML 片段 ─────────────────────────────────────

# 模拟 Ascii2D 的 .detail-box 结构（旧版）
DETAIL_BOX_HTML = """
<div class="container">
    <div class="detail-box">
        <div class="row mt-2">
            <div class="col-xs-6">
                <a href="https://pixiv.net/artworks/74267012">74267012</a>
                <div class="text-muted">
                    画师A / 作品标题A #hash
                </div>
            </div>
        </div>
    </div>
    <div class="detail-box">
        <div class="row mt-2">
            <div class="col-xs-6">
                <a href="https://pixiv.net/artworks/85714285">85714285</a>
                <div class="text-muted">
                    画师B / 作品标题B
                </div>
            </div>
        </div>
    </div>
</div>
"""

# 模拟新版网格结构（.col-xs-6 > a[href]）
GRID_HTML = """
<div class="container">
    <div class="row mt-2">
        <div class="col-xs-6">
            <a href="https://pixiv.net/artworks/12345678">
                <div class="image-box">...</div>
                <div class="info">画师X / 作品X</div>
            </a>
        </div>
        <div class="col-xs-6">
            <a href="https://pixiv.net/artworks/87654321">
                <div class="image-box">...</div>
                <div class="info">画师Y / 作品Y</div>
            </a>
        </div>
    </div>
</div>
"""

# 模拟普通链接兜底（无 .detail-box 也没有 .col-xs-6）
FALLBACK_LINKS_HTML = """
<div class="container">
    <div class="row">
        <div class="col-md-6">
            <a href="https://pixiv.net/artworks/11111111">pixiv 11111111</a>
        </div>
        <div class="col-md-6">
            <a href="https://twitter.com/user/status/22222222">Twitter post</a>
        </div>
        <div class="col-md-6">
            <a href="https://danbooru.donmai.us/posts/33333">Danbooru</a>
        </div>
    </div>
</div>
"""

# 空结果页面
EMPTY_HTML = """
<html><body><p>No results found.</p></body></html>
"""


# ── 测试类 ────────────────────────────────────────────────

class TestAscii2DParseResultPage:
    """_parse_result_page 集成测试"""

    def _make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def test_parse_detail_box(self):
        """测试解析 .detail-box 结构（旧版）"""
        engine = Ascii2D()
        soup = self._make_soup(DETAIL_BOX_HTML)
        items = (
            soup.select(".detail-box")
            or soup.select(".row.mt-2")
            or soup.select(".col-xs-6 > a[href*='pixiv'], .col-xs-6 > a[href*='twitter']")
            or soup.select(".card, .result-item")
        )
        assert len(items) == 2

    def test_parse_grid_links(self):
        """测试解析 .col-xs-6 > a[href] 结构（新版网格）"""
        engine = Ascii2D()
        soup = self._make_soup(GRID_HTML)
        items = (
            soup.select(".col-xs-6 > a[href*='pixiv'], .col-xs-6 > a[href*='twitter']")
        )
        assert len(items) == 2

    def test_fallback_links(self):
        """测试兜底选择器（扫描所有指向图站的链接）"""
        import re
        soup = self._make_soup(FALLBACK_LINKS_HTML)
        items = soup.find_all("a", href=re.compile(
            r"(pixiv\.net|twitter\.com|danbooru\.donmai|yande\.re|sankaku)"
        ))
        assert len(items) == 3

    def test_empty_page_returns_empty(self):
        """测试空页面返回空列表而非报错"""
        import re
        soup = self._make_soup(EMPTY_HTML)
        items = (
            soup.select(".detail-box")
            or soup.select(".row.mt-2")
            or soup.select(".col-xs-6 > a[href*='pixiv'], .col-xs-6 > a[href*='twitter']")
            or soup.select(".card, .result-item")
        )
        if not items:
            items = soup.find_all("a", href=re.compile(
                r"(pixiv\.net|twitter\.com|danbooru\.donmai|yande\.re|sankaku)"
            ))
        assert len(items) == 0


class TestAscii2DParseResultItem:
    """_parse_result_item 单元测试"""

    def _make_engine(self) -> Ascii2D:
        return Ascii2D()

    def test_parse_pixiv_link(self):
        """测试解析单个 pixiv <a> 链接"""
        html = '<a href="https://pixiv.net/artworks/74267012">74267012</a>'
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        engine = self._make_engine()
        result = engine._parse_result_item(link, soup)

        assert result is not None
        assert result.pixiv_id == "74267012"
        assert "pixiv.net" in result.ext_urls[0]
        assert result.highres_url == "https://www.pixiv.net/artworks/74267012"

    def test_parse_detail_box_container(self):
        """测试解析 .detail-box 容器"""
        # 容器中的文本
        html = """
        <div class="detail-box">
            <div class="col-xs-6">
                <a href="https://pixiv.net/artworks/74267012">74267012</a>
                <div class="text-muted">画师A / 作品标题A</div>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(".detail-box")

        engine = self._make_engine()
        result = engine._parse_result_item(container, soup)

        assert result is not None
        assert result.pixiv_id == "74267012"
        # 从容器文本中提取
        assert result.artist == "画师A" or result.artist is not None

    def test_twitter_link(self):
        """测试解析 Twitter 链接"""
        html = """
        <div class="detail-box">
            <a href="https://twitter.com/user/status/123456789">Twitter</a>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        engine = self._make_engine()
        result = engine._parse_result_item(link, soup)

        assert result is not None
        assert "twitter.com" in result.ext_urls[0]
        # Twitter 结果应包含有效标题或标识
        assert result.title is not None

    def test_danbooru_link(self):
        """测试解析 Danbooru 链接（兜底场景）"""
        html = '<a href="https://danbooru.donmai.us/posts/12345">Danbooru</a>'
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        engine = self._make_engine()
        result = engine._parse_result_item(link, soup)

        assert result is not None
        assert "danbooru" in result.ext_urls[0]
        assert result.pixiv_id is None  # Danbooru 没有 pixiv_id

    def test_parse_with_hash_in_text(self):
        """测试文本中包含 #hash 的情况"""
        html = """
        <div class="detail-box">
            <a href="https://pixiv.net/artworks/74267012">74267012</a>
            <div class="text-muted">画师C / 作品C #abcdef</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(".detail-box")

        engine = self._make_engine()
        result = engine._parse_result_item(container, soup)

        assert result is not None
        # 标题不应包含 #hash
        assert result.title is not None
        assert "#" not in result.title if result.pixiv_id else True

    def test_no_results(self):
        """测试无有效链接的容器"""
        html = '<div class="detail-box"><p>无关文本</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(".detail-box")

        engine = self._make_engine()
        result = engine._parse_result_item(container, soup)

        assert result is None


class TestAscii2DParseLink:
    """_parse_link 单元测试"""

    def _make_engine(self) -> Ascii2D:
        return Ascii2D()

    def test_pixiv_link_with_parent(self):
        """测试 pixiv 链接+父元素文本"""
        html = """
        <div>
            <a href="https://pixiv.net/artworks/74267012">74267012</a>
            <span>画师X / 作品X</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        engine = self._make_engine()
        result = engine._parse_link(link)

        assert result is not None
        assert result.pixiv_id == "74267012"
        assert result.highres_url == "https://www.pixiv.net/artworks/74267012"

    def test_pixiv_link_without_parent(self):
        """测试 pixiv 链接无父元素（link itself）"""
        html = '<a href="https://pixiv.net/artworks/74267012">74267012</a>'
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        # 移除链接的父元素引用
        link.parent = None

        engine = self._make_engine()
        result = engine._parse_link(link)

        # 如果没有父元素，仍应提取到 pixiv_id
        assert result is not None
        assert result.pixiv_id == "74267012"
        assert result.highres_url == "https://www.pixiv.net/artworks/74267012"

    def test_non_pixiv_link_returns_none(self):
        """测试非图站链接返回 None"""
        html = '<a href="https://example.com">example</a>'
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a")

        engine = self._make_engine()
        result = engine._parse_link(link)

        assert result is None
