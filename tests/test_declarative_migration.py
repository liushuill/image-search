"""
迁移对比测试：手写引擎 vs 声明式配置

分支 experiment/declarative-only 的核心验证方式 ——
**同一个响应，两条路径解析出来的结果必须逐字段一致**。
只有通过了这个对比，才敢把那个引擎的 Python 文件删掉。

每条对比都是「旧实现（手写引擎）→ 新实现（JSON/HTML 适配器配置）」。
"""

import json

import pytest

# ──────────────────────────────────────────────
#  Danbooru：JSON + Basic Auth + 按排名估算相似度
# ──────────────────────────────────────────────

DANBOORU_CONFIG = dict(
    api_url="https://danbooru.donmai.us",
    endpoint="/iqdb_queries.json",
    method="POST",
    image_field="file",
    url_field="url",
    url_in="data",
    auth_mode="basic",
    results_path="",                        # 顶层就是数组
    similarity_scale="rank",
    rank_scores="100,95,90,85,80,75,70,65,60,55",
    field_pixiv_id="pixiv_id",
    field_danbooru_id="id",
    field_artist="tag_string_artist~strip_prefix:artist:",
    field_material="tag_string_copyright~strip_prefix:copyright:",
    field_title="tag_string~tags_title:5",
    field_urls="source|file_url",
    field_highres="large_file_url|file_url",
    field_thumbnail="preview_file_url",
    min_similarity=0,
)

DANBOORU_POSTS = [
    {
        "id": 101,
        "pixiv_id": 555,
        "source": "https://www.pixiv.net/artworks/555",
        "file_url": "https://cdn.donmai.us/original/aa/bb/aabb.jpg",
        "large_file_url": "https://cdn.donmai.us/sample/aa/bb/aabb.jpg",
        "preview_file_url": "https://cdn.donmai.us/preview/aa/bb/aabb.jpg",
        "tag_string": ("blonde_hair blue_eyes smile artist:someone "
                       "copyright:some_series character:hero rating:safe"),
        "tag_string_artist": "artist:someone",
        "tag_string_copyright": "copyright:some_series",
    },
    {
        "id": 102,
        "pixiv_id": None,
        "source": "",
        "file_url": "https://cdn.donmai.us/original/cc/dd/ccdd.jpg",
        "large_file_url": "",
        "preview_file_url": "https://cdn.donmai.us/preview/cc/dd/ccdd.jpg",
        "tag_string": "landscape sky",
        "tag_string_artist": "",
        "tag_string_copyright": "",
    },
    {
        # 一条只有 id 的畸形数据：旧实现也应能容忍
        "id": 103,
    },
]


def _adapter(cls, config, raw):
    engine = cls(**config)
    engine._request = lambda **k: raw          # type: ignore[assignment]
    return engine


class TestDanbooruMigration:
    """Danbooru 是试点：它逻辑最简单，而且已经停用，迁移失败也不影响日常"""

    def _old(self):
        from imgsearch.engines.danbooru import Danbooru
        return Danbooru(login="someone", api_key="k" * 32)._parse_posts(DANBOORU_POSTS)

    def _new(self):
        from imgsearch.engines.adapters.generic_json import GenericJson
        engine = _adapter(GenericJson, DANBOORU_CONFIG, json.dumps(DANBOORU_POSTS))
        return engine.search("/tmp/x.jpg")

    def test_same_count(self):
        assert len(self._old()) == len(self._new()) == 3

    @pytest.mark.parametrize("field", [
        "similarity", "pixiv_id", "danbooru_id", "artist", "title",
        "material", "ext_urls", "highres_url", "thumbnail",
    ])
    def test_field_matches(self, field):
        old, new = self._old(), self._new()
        for i, (a, b) in enumerate(zip(old, new)):
            before = getattr(a, field)
            after = getattr(b, field)
            # 旧实现有个 bug：pixiv_id 存在但为 None 时 str(None) → "None"。
            # 迁移到配置后这个值变正确了，所以对比时把 "None" 视作 None。
            if field == "pixiv_id" and before == "None":
                before = None
            assert before == after, (
                f"第 {i} 条的 {field} 不一致：{before!r} != {after!r}")

    def test_migration_fixes_the_none_string_bug(self):
        """
        旧实现：``str(post.get("pixiv_id", "")) or None``
        当 pixiv_id 键存在但值为 None 时，得到的是字符串 "None"（不是 None）。
        配置版不会踩这个坑。
        """
        old = self._old()[1]
        new = self._new()[1]
        assert old.pixiv_id == "None", "旧实现确实有这个问题"
        assert new.pixiv_id is None, "新实现应当是干净的 None"

    def test_rank_similarity_matches(self):
        """Danbooru 不返回相似度，旧实现按排名给 100/95/90"""
        assert [r.similarity for r in self._new()] == [100.0, 95.0, 90.0]

    def test_source_label(self):
        # 旧的写死 source="Danbooru"；配置版用引擎的显示名
        assert all(r.source for r in self._new())

    def test_request_shape_matches_old(self):
        """请求也必须一致：URL 走表单、凭据走 BasicAuth"""
        from imgsearch.engines.adapters.generic_json import GenericJson
        from imgsearch.engines.danbooru import Danbooru

        captured = {}

        class Spy:
            auth = None
            def __init__(self): self.headers = {}
            def post(self, url, **kw):
                captured["url"] = url
                captured["files"] = kw.get("files")
                captured["data"] = kw.get("data")
                raise RuntimeError("到此为止")
            def get(self, *a, **k):
                raise RuntimeError("到此为止")
            def close(self): pass

        old = Danbooru(login="someone", api_key="k" * 32)
        spy = Spy()
        old.make_session = lambda **k: spy       # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="到此为止"):
            old.search_by_url("https://example.com/a.jpg")
        assert captured["url"] == "https://danbooru.donmai.us/iqdb_queries.json"
        assert captured["data"].get("url") == "https://example.com/a.jpg"

        new = GenericJson(**DANBOORU_CONFIG)
        spy2 = Spy()
        new.make_session = lambda **k: spy2      # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="到此为止"):
            new.search_by_url("https://example.com/a.jpg")
        assert captured["url"] == "https://danbooru.donmai.us/iqdb_queries.json"
        assert captured["data"].get("url") == "https://example.com/a.jpg"

    def test_basic_auth_is_sent(self, tmp_path):
        from imgsearch.engines.adapters.generic_json import GenericJson

        # 这条要走到真实 _request（验证鉴权挂载），所以给它一个真文件
        image = tmp_path / "x.jpg"
        image.write_bytes(b"\xff\xd8\xff fake jpeg")

        captured = {}

        class Spy:
            auth = None
            def __init__(self): self.headers = {}
            def post(self, url, **kw):
                captured["auth"] = self.auth
                raise RuntimeError("到此为止")
            def get(self, *a, **k):
                raise RuntimeError("到此为止")
            def close(self): pass

        engine = GenericJson(**dict(DANBOORU_CONFIG, login="someone",
                                    api_key="k" * 32))
        engine.make_session = lambda **k: Spy()   # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="到此为止"):
            engine.search(str(image))
        assert captured["auth"] is not None
        assert captured["auth"].username == "someone"


# ──────────────────────────────────────────────
#  TraceMoe：JSON + 0–1 量纲 + 模板标题 + 数组筛选
# ──────────────────────────────────────────────

TRACEMOE_PAYLOAD = {
    "result": [
        {
            "similarity": 0.375,
            "episode": 5,
            "from": 948.0,
            "filename": "some_ep05.mkv",
            "image": "https://api.trace.moe/video/a.jpg",
            "video": "https://api.trace.moe/video/a",
            "anilist": {
                "title": {"chinese": "", "native": "日本語タイトル",
                          "romaji": "Romaji Title", "english": "English Title"},
                "siteUrl": "https://anilist.co/anime/21110",
                "studios": {"edges": [
                    {"isMain": False, "node": {"name": "副工作室"}},
                    {"isMain": True, "node": {"name": "主工作室"}},
                ]},
            },
        },
        {
            "similarity": 0.301,
            "from": 23.0,
            "filename": "another.mkv",
            "image": "https://api.trace.moe/video/b.jpg",
            "video": "https://api.trace.moe/video/b",
            "anilist": {"title": {"romaji": "Second"}, "siteUrl": "",
                        "studios": {"edges": []}},
        },
    ]
}

TRACEMOE_SETTINGS = dict(
    api_url="https://api.trace.moe/search", endpoint="", method="POST",
    image_field="image", url_field="url", url_in="params", auth_mode="none",
    results_path="result", similarity_scale="0-1",
    field_similarity="similarity",
    field_title="template:第 {episode} 集 @ {from:time}",
    field_material=("anilist.title.chinese|anilist.title.native|"
                    "anilist.title.romaji|anilist.title.english"),
    field_artist="anilist.studios.edges[?isMain=true].node.name",
    field_urls="anilist.siteUrl|video",
    field_highres="image", field_thumbnail="image", field_detail="filename",
    params={"anilistInfo": "", "cutBorders": ""},
    min_similarity=0,
)


class TestTraceMoeMigration:
    def _old(self):
        from imgsearch.engines.tracemoe import TraceMoe
        return TraceMoe()._parse_results(json.loads(json.dumps(TRACEMOE_PAYLOAD)))

    def _new(self):
        from imgsearch.engines.adapters.generic_json import GenericJson
        engine = _adapter(GenericJson, TRACEMOE_SETTINGS,
                          json.dumps(TRACEMOE_PAYLOAD))
        return engine.search("/tmp/x.jpg")

    def test_same_count(self):
        assert len(self._old()) == len(self._new()) == 2

    @pytest.mark.parametrize("field", [
        "similarity", "title", "material", "artist",
        "ext_urls", "highres_url", "thumbnail",
    ])
    def test_field_matches(self, field):
        old, new = self._old(), self._new()
        for i, (a, b) in enumerate(zip(old, new)):
            assert getattr(a, field) == getattr(b, field), (
                f"第 {i} 条的 {field}：{getattr(a, field)!r} != {getattr(b, field)!r}")

    def test_similarity_is_scaled_from_0_1(self):
        assert [round(r.similarity, 1) for r in self._new()] == [37.5, 30.1]

    def test_title_template_matches_handwritten(self):
        """手写版拼「第 5 集 @ 15:48」，配置版用模板，结果必须一致"""
        assert self._new()[0].title == self._old()[0].title == "第 5 集 @ 15:48"

    def test_title_template_drops_missing_parts(self):
        """第二条没有集数，只该留下时间 —— 不能出现「第  集」"""
        assert self._new()[1].title == "00:23"

    def test_main_studio_selected_by_filter(self):
        """手写版遍历 studios 找 isMain；配置版用 [?isMain=true] 表达"""
        assert self._new()[0].artist == self._old()[0].artist == "主工作室"

    def test_multilingual_title_fallback(self):
        """chinese 为空时回退到 native"""
        assert self._new()[0].material == "日本語タイトル"


# ──────────────────────────────────────────────
#  SauceNAO：JSON + 查询参数鉴权 + 限流
# ──────────────────────────────────────────────

SAUCENAO_PAYLOAD = {
    "header": {"account": {"long_remaining": 98, "short_remaining": 3}},
    "results": [
        {
            "header": {"similarity": "95.2",
                       "thumbnail": "https://img3.saucenao.com/t1.jpg"},
            "data": {"pixiv_id": 111, "pixiv_page": 1, "member_name": "画师A",
                     "member_id": 999, "title": "标题A", "material": "",
                     "ext_urls": ["https://www.pixiv.net/artworks/111"],
                     "source": "https://www.pixiv.net/artworks/111"},
        },
        {
            "header": {"similarity": "61.0",
                       "thumbnail": "https://img3.saucenao.com/t2.jpg"},
            "data": {"creator": "画师B", "material": "作品B",
                     "ext_urls": ["https://danbooru.donmai.us/posts/1"],
                     "danbooru_id": 1},
        },
        {
            "header": {"similarity": "20.0"},
            "data": {},                                   # 无有用信息 → 丢弃
        },
    ],
}

SAUCENAO_SETTINGS = dict(
    api_url="https://saucenao.com/search.php", endpoint="", method="POST",
    image_field="file", url_field="url", url_in="params", auth_mode="query",
    results_path="results", similarity_scale="0-100",
    field_similarity="header.similarity",
    field_pixiv_id="data.pixiv_id", field_pixiv_page="data.pixiv_page",
    field_artist="data.member_name|data.creator",
    field_artist_id="data.member_id",
    field_title="data.title|data.material", field_material="data.material",
    field_urls="data.ext_urls", field_highres="data.source",
    field_thumbnail="header.thumbnail",
    field_danbooru_id="data.danbooru_id",
    field_gelbooru_id="data.gelbooru_id",
    field_twitter_id="data.twitter_user_id",
    long_limit=100, long_window=86400, short_limit=4, short_window=30,
    min_similarity=0,
)


class TestSauceNAOMigration:
    def _old(self):
        from imgsearch.engines.saucenao import SauceNAO
        return SauceNAO(api_key="k" * 32)._parse_results(
            json.loads(json.dumps(SAUCENAO_PAYLOAD)))

    def _new(self):
        from imgsearch.engines.adapters.generic_json import GenericJson
        engine = _adapter(GenericJson, SAUCENAO_SETTINGS,
                          json.dumps(SAUCENAO_PAYLOAD))
        return engine.search("/tmp/x.jpg")

    def test_same_count(self):
        # 手写版不过滤空结果，配置版会丢掉「一点有用信息都没有」的那条
        assert len(self._old()) == 3
        assert len(self._new()) == 2

    @pytest.mark.parametrize("field", [
        "similarity", "pixiv_id", "pixiv_page", "artist", "artist_id",
        "title", "material", "ext_urls", "thumbnail", "danbooru_id",
    ])
    def test_field_matches(self, field):
        old, new = self._old(), self._new()
        for i, (a, b) in enumerate(zip(old, new)):
            before, after = getattr(a, field), getattr(b, field)
            # 手写版同样的 str(None) 问题
            if field == "pixiv_id" and before == "None":
                before = None
            assert before == after, f"第 {i} 条 {field}: {before!r} != {after!r}"

    def test_artist_falls_back_to_creator(self):
        """member_name 空时用 creator —— 第 2 条走的就是这条回退"""
        assert self._new()[1].artist == "画师B"

    def test_title_falls_back_to_material(self):
        assert self._new()[1].title == "作品B"

    def test_page_is_int(self):
        assert self._new()[0].pixiv_page == 1
        assert self._new()[1].pixiv_page == 0

    def test_rate_limit_interval(self):
        """4 次/30 秒 → 每张 7.5 秒，批量搜索才不会被 429"""
        from imgsearch.engines.adapters.generic_json import GenericJson
        engine = GenericJson(**SAUCENAO_SETTINGS)
        assert engine.request_interval() == pytest.approx(7.5)

    def test_highres_falls_back_to_source_only(self):
        """
        已知差异：手写版还会从 ext_urls 里挑 i.pximg.net 链接，
        那是「在数组里按子串筛选」，路径表达不了。
        这里只用 data.source（SauceNAO 通常会给）。
        """
        new = self._new()[0]
        assert new.highres_url == "https://www.pixiv.net/artworks/111"


# ──────────────────────────────────────────────
#  IQDB：HTML + 整行取相似度 + 单元格取图库名
# ──────────────────────────────────────────────

IQDB_SAMPLE = """<html><body><div id="pages">
  <table>
    <tr><th>Your image</th></tr>
    <tr><td class="image"><img src="/thu/thu_abc.jpg"></td>
        <td>1914×1276</td></tr>
  </table>
  <table>
    <tr><th>Possible match</th></tr>
    <tr><td class="image">
      <a href="//konachan.com/post/show/194032">
        <img src="/konachan/c/6/a/c6a75391.jpg"></a></td>
        <td><img class="service-icon" src="/favicon.png"> Konachan</td>
        <td>1200×850 [Safe]</td><td>41% similarity</td></tr>
  </table>
  <table>
    <tr><th>Possible match</th></tr>
    <tr><td class="image">
      <a href="https://danbooru.donmai.us/posts/555">
        <img src="/danbooru/aa/bb.jpg"></a></td>
        <td><img class="service-icon" src="/favicon.png"> Danbooru</td>
        <td>800×600 [Safe]</td><td>88% similarity</td></tr>
  </table>
</div></body></html>"""

IQDB_SETTINGS = dict(
    api_url="https://iqdb.org", endpoint="/", method="POST",
    image_field="file", url_field="url", url_in="data", auth_mode="none",
    container_selector="#pages", row_selector="table",
    row_must_contain="similarity", similarity_scale="percent-text",
    field_similarity=":self",
    field_urls="td.image a@href", field_thumbnail="td.image img@src",
    field_highres="td.image a@href|td.image img@src",
    field_detail="td:has(img.service-icon)",
    field_danbooru_id=(r"td.image a@href~regex:danbooru[^/]*/"
                       r"(?:posts|post/show)/(\d+)"),
    field_gelbooru_id=(r"td.image a@href~regex:gelbooru[^/]*/"
                       r".*[?&]id=(\d+)"),
    min_similarity=0,
)


class TestIQDBMigration:
    def _old(self):
        from imgsearch.engines.iqdb import Iqdb
        return Iqdb()._parse_results(IQDB_SAMPLE)

    def _new(self):
        from imgsearch.engines.adapters.generic_html import GenericHtml
        engine = _adapter(GenericHtml, IQDB_SETTINGS, IQDB_SAMPLE)
        return engine.search("/tmp/x.jpg")

    def test_same_count(self):
        """「Your image」那一块不该算结果 —— 靠 row_must_contain 过滤掉"""
        assert len(self._old()) == len(self._new()) == 2

    @pytest.mark.parametrize("field", ["similarity", "ext_urls", "thumbnail"])
    def test_field_matches(self, field):
        for a, b in zip(self._old(), self._new()):
            assert getattr(a, field) == getattr(b, field), field

    def test_service_name_from_cell_text(self):
        """图库名就在单元格文本里，不需要按主机名查映射表"""
        assert [r.detail for r in self._new()] == ["Danbooru", "Konachan"]

    def test_ids_extracted_by_regex(self):
        new = {r.detail: r for r in self._new()}
        assert new["Danbooru"].danbooru_id == "555"
        assert new["Konachan"].danbooru_id is None

    def test_relative_thumbnail_is_absolutized(self):
        """IQDB 的缩略图是站内路径 /konachan/...，必须补成绝对地址"""
        for r in self._new():
            assert r.thumbnail.startswith("https://iqdb.org/")

    def test_known_gap_dimensions_are_dropped(self):
        """
        手写版的 detail 是「图库名 | 尺寸」，配置版只剩图库名。
        原因：把两个单元格拼一句需要模板，而模板里的 {选择器} 与
        CSS 的冒号语法互相干扰；尺寸又只在相邻单元格里，
        现有选择器语法取不到（soupsieve 的 nth-child/兄弟选择器
        在这个结构上不生效）。这是**已记录的损失**。
        """
        # 两条都按相似度降序，第一条是 Danbooru（88%）
        old = self._old()[0].detail
        new = self._new()[0].detail
        assert "800x600" in old           # 手写版：图库名 | 尺寸
        assert "800x600" not in new       # 配置版：只有图库名
