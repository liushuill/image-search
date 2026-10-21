"""
SauceNAO 模块测试

测试搜索结果的解析逻辑，使用 mock 数据模拟 API 响应。
"""

from tests.legacy.saucenao import SauceNAO


# ── Mock API 响应数据 ────────────────────────────────────

# 模拟 Pixiv 结果
PIXIV_API_RESPONSE = {
    "header": {
        "account": {
            "long_remaining": 95,
            "short_remaining": 3,
        },
    },
    "results": [
        {
            "header": {
                "similarity": "95.82",
                "index_id": 5,
                "thumbnail": "https://img.saucenao.com/thumb.jpg",
            },
            "data": {
                "ext_urls": ["https://www.pixiv.net/artworks/74267012"],
                "pixiv_id": 74267012,
                "member_name": "画师A",
                "member_id": 123456,
                "title": "作品标题A",
                "material": "作品出处",
                "pixiv_page": 0,
            },
        },
        {
            "header": {
                "similarity": "80.15",
                "index_id": 5,
                "thumbnail": "https://img.saucenao.com/thumb2.jpg",
            },
            "data": {
                "ext_urls": ["https://www.pixiv.net/artworks/85714285"],
                "pixiv_id": 85714285,
                "member_name": "画师B",
                "member_id": 789012,
                "title": "作品标题B",
                "pixiv_page": 1,
            },
        },
    ],
}

# 模拟非 Pixiv 结果（如 Twitter/Danbooru）
MIXED_API_RESPONSE = {
    "header": {
        "account": {
            "long_remaining": -1,
            "short_remaining": -1,
        },
    },
    "results": [
        {
            "header": {"similarity": "90.0", "index_id": 5},
            "data": {
                "ext_urls": ["https://twitter.com/user/status/12345"],
                "twitter_user_id": "54321",
            },
        },
        {
            "header": {"similarity": "70.0", "index_id": 999},
            "data": {
                "ext_urls": ["https://danbooru.donmai.us/posts/67890"],
                "source": "danbooru",
            },
        },
    ],
}

# 模拟空结果
EMPTY_API_RESPONSE = {
    "header": {"account": {}},
    "results": [],
}


# ── 测试类 ────────────────────────────────────────────────

class TestSauceNAOParseResults:
    """_parse_results 单元测试"""

    def _make_engine(self) -> SauceNAO:
        return SauceNAO(api_key="test_key")

    def test_parse_pixiv_results(self):
        """测试解析 Pixiv 结果"""
        engine = self._make_engine()
        results = engine._parse_results(PIXIV_API_RESPONSE)

        assert len(results) == 2

        # 第一个结果
        r1 = results[0]
        assert r1.source == "SauceNAO"
        assert r1.similarity == 95.82
        assert r1.pixiv_id == "74267012"
        assert r1.artist == "画师A"
        assert r1.artist_id == "123456"
        assert r1.title == "作品标题A"
        assert r1.material == "作品出处"
        assert r1.pixiv_page == 0
        # highres_url 构造逻辑：
        # 1. 先检查 data_raw.get("source") → None
        # 2. 然后走 _pixiv_id_to_path: f"https://i.pximg.net/img-original/img/{id}_p0.jpg"
        assert r1.highres_url == "https://i.pximg.net/img-original/img/74267012_p0.jpg"
        assert "pixiv.net" in r1.ext_urls[0]

        # 第二个结果
        r2 = results[1]
        assert r2.similarity == 80.15
        assert r2.pixiv_id == "85714285"
        assert r2.pixiv_page == 1
        assert r2.highres_url == "https://i.pximg.net/img-original/img/85714285_p0.jpg"

    def test_parse_mixed_results(self):
        """测试解析混合结果（Twitter + Danbooru）"""
        engine = self._make_engine()
        results = engine._parse_results(MIXED_API_RESPONSE)

        assert len(results) == 2

        # Twitter 结果 (similarity 更高, 排前面)
        r1 = results[0]
        assert r1.similarity == 90.0
        assert "twitter.com" in r1.ext_urls[0]
        assert r1.twitter_id == "54321"

        # Danbooru 结果
        r2 = results[1]
        assert r2.similarity == 70.0
        assert "danbooru" in r2.ext_urls[0]

    def test_parse_empty_results(self):
        """测试解析空结果"""
        engine = self._make_engine()
        results = engine._parse_results(EMPTY_API_RESPONSE)
        assert len(results) == 0

    def test_sort_by_similarity(self):
        """测试按相似度降序排列"""
        unsorted = {
            "header": {"account": {}},
            "results": [
                {
                    "header": {"similarity": "50.0", "index_id": 5},
                    "data": {"ext_urls": ["https://pixiv.net/artworks/1"], "pixiv_id": 1},
                },
                {
                    "header": {"similarity": "90.0", "index_id": 5},
                    "data": {"ext_urls": ["https://pixiv.net/artworks/2"], "pixiv_id": 2},
                },
                {
                    "header": {"similarity": "70.0", "index_id": 5},
                    "data": {"ext_urls": ["https://pixiv.net/artworks/3"], "pixiv_id": 3},
                },
            ],
        }
        engine = self._make_engine()
        results = engine._parse_results(unsorted)
        similarities = [r.similarity for r in results]
        assert similarities == [90.0, 70.0, 50.0], f"实际顺序: {similarities}"


class TestSauceNAOBuildPixivUrl:
    """_build_pixiv_url 单元测试"""

    def _make_engine(self) -> SauceNAO:
        return SauceNAO(api_key="test_key")

    def test_build_pixiv_url_from_ext_urls(self):
        """测试从 ext_urls 中的 pixiv 作品页 URL 构建 URL"""
        engine = self._make_engine()
        data = {"ext_urls": ["https://www.pixiv.net/artworks/74267012"], "pixiv_page": 0}
        url = engine._build_pixiv_url(data, "74267012")
        assert url == "https://www.pixiv.net/artworks/74267012"

    def test_build_pixiv_url_none(self):
        """测试没有 ext_urls 且 pixiv_id 为空时返回 None"""
        engine = self._make_engine()
        url = engine._build_pixiv_url({}, None)
        assert url is None


class TestSauceNAOPixivIdToPath:
    """_pixiv_id_to_path 静态方法测试"""

    def test_valid_id(self):
        assert SauceNAO._pixiv_id_to_path("74267012") == "74267012_p0.jpg"

    def test_empty_id(self):
        assert SauceNAO._pixiv_id_to_path("") == "_p0.jpg"
