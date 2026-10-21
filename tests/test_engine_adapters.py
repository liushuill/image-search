"""
声明式适配器测试（JSON / HTML 两类）

设计目标：**不写代码就能接一个新站点**。所以这里全部离线跑 ——
用固定的响应文本验证「映射表 → SearchResult」这条链路，
不依赖任何真实站点（真实站点的验证在开发时做过，见 README）。
"""

import json

import pytest

from imgsearch.engines.adapters import dom
from imgsearch.engines.adapters.paths import dig, dig_any, dig_links, dig_str

# ──────────────────────────────────────────────
#  路径解析
# ──────────────────────────────────────────────


class TestJsonPaths:
    DATA = {"results": [{"header": {"similarity": "95.2", "thumbnail": "t"},
                         "data": {"creator": ["A", "B"], "ext_urls": ["u1", "u2"],
                                  "title": {"chinese": "", "native": "作品"}}}]}

    def test_simple_and_nested(self):
        assert dig(self.DATA, "results")[0]["header"]["similarity"] == "95.2"
        assert dig(self.DATA, "results[0].header.similarity") == "95.2"

    def test_missing_returns_none(self):
        assert dig(self.DATA, "nope.x") is None
        assert dig(self.DATA, "results[9].header") is None

    def test_empty_path_returns_root(self):
        assert dig(self.DATA, "") is self.DATA

    def test_array_to_text(self):
        assert dig_str(self.DATA, "results[0].data.creator") == "A, B"

    def test_fallback_chain(self):
        path = ("results[0].data.title.chinese|"
                "results[0].data.title.native|"
                "results[0].data.title.romaji")
        assert dig_any(self.DATA, path) == "作品"

    def test_fallback_chain_all_empty(self):
        assert dig_any(self.DATA, "a|b|c") == ""

    def test_collect_links_from_array(self):
        assert dig_links(self.DATA, "results[0].data.ext_urls") == ["u1", "u2"]

    def test_collect_links_from_single_string(self):
        assert dig_links(self.DATA, "results[0].header.thumbnail") == ["t"]

    def test_collect_links_from_multiple_paths(self):
        got = dig_links(self.DATA, "results[0].data.ext_urls|results[0].header.thumbnail")
        assert got == ["u1", "u2", "t"]


# ──────────────────────────────────────────────
#  HTML 选择器
# ──────────────────────────────────────────────


class TestHtmlSelectors:
    HTML = """
    <div id="pages">
      <table><th>Your image</th><td class="image">
        <a href="//x.com/self"><img src="//x.com/self.jpg"></a></td>
        <td>1914×1276</td></table>
      <table><th>Possible match</th><td class="image">
        <a href="//k.com/1"><img src="//t.com/1.jpg"></a></td>
        <td>1664×2432 42% similarity</td></table>
    </div>"""

    def _rows(self):
        soup = dom.parse_html(self.HTML)
        container = dom.scoped(soup, "#pages")
        return dom.select_all(container, "table")

    def test_extract_text_and_attr(self):
        row = self._rows()[1]
        assert dom.extract(row, "td.image img@src") == "//t.com/1.jpg"
        assert dom.extract_links(row, "td.image a@href") == ["//k.com/1"]

    def test_self_selector_takes_whole_row_text(self):
        row = self._rows()[1]
        text = dom.extract(row, ":self")
        assert "42% similarity" in text

    def test_extract_returns_empty_for_missing(self):
        row = self._rows()[1]
        assert dom.extract(row, "td.nope") == ""

    def test_split_spec(self):
        assert dom.split_spec("td a@href") == ("td a", "href")
        assert dom.split_spec("td a") == ("td a", "text")
        assert dom.split_spec("") == ("", "text")

    def test_fallback_chain_in_links(self):
        row = self._rows()[1]
        got = dom.extract_links(row, "td.nope@href|td.image a@href")
        assert got == ["//k.com/1"]


# ──────────────────────────────────────────────
#  JSON 适配器
# ──────────────────────────────────────────────


JSON_SAMPLE = {
    "results": [
        {"header": {"similarity": "95.2", "thumbnail": "https://t/1.jpg"},
         "data": {"pixiv_id": 111, "creator": "画师A", "title": "标题A",
                  "ext_urls": ["//pixiv.net/a"]}},
        {"header": {"similarity": "61.0", "thumbnail": "https://t/2.jpg"},
         "data": {"creator": "画师B", "ext_urls": ["https://x/b"]}},
        {"header": {"similarity": "10.0"}, "data": {}},     # 没任何有用信息 → 丢弃
    ]
}


def make_json(**kw):
    from imgsearch.engines.adapters.generic_json import GenericJson
    settings = dict(api_url="https://api.example", endpoint="/search",
                    results_path="results", similarity_scale="0-100",
                    field_similarity="header.similarity",
                    field_pixiv_id="data.pixiv_id",
                    field_artist="data.creator",
                    field_title="data.title",
                    field_urls="data.ext_urls",
                    field_thumbnail="header.thumbnail")
    settings.update(kw)
    return GenericJson(**settings)


class TestJsonAdapter:
    def _parse(self, payload, **kw):
        adapter = make_json(**kw)
        adapter._request = lambda **k: json.dumps(payload)     # type: ignore
        return adapter.search("/tmp/x.jpg")

    def test_maps_fields(self):
        got = self._parse(JSON_SAMPLE)
        assert len(got) == 2                       # 第三条被丢弃
        top = got[0]
        assert top.similarity == 95.2
        assert top.pixiv_id == "111"
        assert top.artist == "画师A"
        assert top.title == "标题A"
        assert top.thumbnail == "https://t/1.jpg"

    def test_sorted_by_similarity(self):
        got = self._parse(JSON_SAMPLE)
        assert [r.similarity for r in got] == [95.2, 61.0]

    def test_protocol_relative_urls_are_absolutized(self):
        """``//pixiv.net/a`` 这种写法很多图库都用，不补 在结果表里点不开"""
        got = self._parse(JSON_SAMPLE)
        assert got[0].ext_urls[0] == "https://pixiv.net/a"

    def test_scale_0_1(self):
        payload = {"result": [{"similarity": 0.875, "url": "u"}]}
        got = self._parse(payload, results_path="result",
                          similarity_scale="0-1",
                          field_similarity="similarity",
                          field_urls="url")
        assert got[0].similarity == pytest.approx(87.5)

    def test_scale_none(self):
        payload = {"result": [{"url": "u"}]}
        got = self._parse(payload, results_path="result",
                          similarity_scale="none", field_urls="url")
        assert got[0].similarity == 0.0

    def test_bare_array_when_no_results_path(self):
        payload = [{"url": "u1"}, {"url": "u2"}]
        got = self._parse(payload, results_path="", field_urls="url")
        assert len(got) == 2

    def test_single_key_object_wrapping_array(self):
        """有些站点把数组包在单键对象里，不该要求用户去猜路径"""
        payload = {"data": [{"url": "u"}]}
        got = self._parse(payload, results_path="", field_urls="url")
        assert len(got) == 1

    def test_fallback_chain_for_title(self):
        payload = {"r": [{"t": {"cn": "", "jp": "日本語", "en": "English"}}]}
        got = self._parse(payload, results_path="r",
                          field_title="t.cn|t.jp|t.en")
        assert got[0].title == "日本語"

    def test_non_json_response_is_reported(self):
        adapter = make_json()
        adapter._request = lambda **k: "<html>not json</html>"   # type: ignore
        with pytest.raises(RuntimeError, match="不是 JSON"):
            adapter.search("/tmp/x.jpg")

    def test_empty_response(self):
        assert self._parse({"results": []}) == []


# ──────────────────────────────────────────────
#  HTML 适配器
# ──────────────────────────────────────────────


HTML_SAMPLE = """
<div id="pages">
  <table><th>Your image</th>
    <td class="image"><a href="//x.com/self"><img src="//x.com/self.jpg"></a></td>
    <td>1914×1276</td></table>
  <table><th>No relevant matches</th><td>try another service</td></table>
  <table><th>Possible match</th>
    <td class="image"><a href="//konachan.com/post/show/1">
      <img src="//t.com/1.jpg"></a></td>
    <td>1664×2432 42% similarity</td></table>
  <table><th>Possible match</th>
    <td class="image"><a href="//anime-pictures.net/2">
      <img src="//t.com/2.jpg"></a></td>
    <td>1200×850 40% similarity</td></table>
</div>"""


def make_html(**kw):
    from imgsearch.engines.adapters.generic_html import GenericHtml
    settings = dict(api_url="https://iqdb.example", endpoint="/",
                    container_selector="#pages", row_selector="table",
                    row_must_contain="similarity",
                    similarity_scale="percent-text",
                    field_similarity=":self",
                    field_urls="td.image a@href",
                    field_thumbnail="td.image img@src")
    settings.update(kw)
    return GenericHtml(**settings)


class TestHtmlAdapter:
    def _parse(self, raw, **kw):
        adapter = make_html(**kw)
        adapter._request = lambda **k: raw                    # type: ignore
        return adapter.search("/tmp/x.jpg")

    def test_maps_rows(self):
        got = self._parse(HTML_SAMPLE)
        assert len(got) == 2
        assert [r.similarity for r in got] == [42.0, 40.0]
        assert got[0].ext_urls == ["https://konachan.com/post/show/1"]
        assert got[0].thumbnail == "https://t.com/1.jpg"

    def test_row_filter_excludes_noise_rows(self):
        """「Your image」「No relevant matches」也是 table，不该算结果"""
        got = self._parse(HTML_SAMPLE)
        assert all(r.similarity > 0 for r in got)

    def test_all_filtered_out_returns_empty_not_error(self):
        """
        有元素但全被过滤掉 = 站点确实没有匹配结果，这是**正常情况**。
        误报成「选择器写错」会把正常结果当成故障。
        """
        assert self._parse(HTML_SAMPLE, row_must_contain="都不包含的词") == []

    def test_no_matching_elements_is_an_error_with_diagnostics(self):
        """一个元素都找不到 = 选择器错或站点改版 → 必须报错（否则静默返回空）"""
        with pytest.raises(RuntimeError) as ei:
            self._parse("<html><body><div>完全没有结果表格</div></body></html>")
        msg = str(ei.value)
        assert "找不到任何匹配" in msg
        assert "页面标题" in msg          # 诊断信息：区分"选择器错"与"站点拒绝"
        assert "整页 table 数" in msg

    def test_missing_row_selector_is_reported(self):
        with pytest.raises(RuntimeError, match="单条结果"):
            self._parse(HTML_SAMPLE, row_selector="")

    def test_percent_text_ignores_dimension_numbers(self):
        """IQDB 的行里还有 1664×2432，不能把那个当成相似度"""
        got = self._parse(HTML_SAMPLE)
        assert all(r.similarity <= 100 for r in got)
        assert got[0].similarity == 42.0

    def test_container_optional(self):
        """没有明显容器时，留空就在整页里找"""
        html = ('<table><td class="image"><a href="//k.com/1">'
                '<img src="//t/1.jpg"></a></td><td>88% similarity</td></table>')
        got = self._parse(html, container_selector="")
        assert len(got) == 1 and got[0].similarity == 88.0


# ──────────────────────────────────────────────
#  注册与模板一致性
# ──────────────────────────────────────────────


class TestAdapterRegistration:
    def test_both_are_registered_as_builtin_engines(self):
        from imgsearch.engines.store import get_store
        names = [ec.name for ec in get_store().list_all()]
        assert "genericJson" in names
        assert "genericHtml" in names

    def test_disabled_by_default(self):
        """适配器要用户自己填映射，默认不该启用"""
        from imgsearch.engines.adapters.generic_html import GenericHtml
        from imgsearch.engines.adapters.generic_json import GenericJson
        for cls in (GenericJson, GenericHtml):
            assert cls.ENABLED_BY_DEFAULT is False
            assert cls.AUTH_MODE == "none"

    def test_each_has_a_usage_note(self):
        from imgsearch.engines.adapters.generic_html import GenericHtml
        from imgsearch.engines.adapters.generic_json import GenericJson
        for cls in (GenericJson, GenericHtml):
            assert cls.USAGE_NOTE

    def test_mapping_fields_present(self):
        from imgsearch.engines.adapters.declarative import MAPPED_FIELDS
        for cls in (__import__("imgsearch.engines.adapters.generic_json",
                               fromlist=["x"]).GenericJson,
                    __import__("imgsearch.engines.adapters.generic_html",
                               fromlist=["x"]).GenericHtml):
            keys = {f.key for f in cls.CONFIG_SCHEMA}
            for key, _label, _e, _ in MAPPED_FIELDS:
                assert key in keys, f"{cls.NAME} 缺少映射字段 {key}"

    def test_can_add_multiple_instances(self, store):
        """同一个类挂多个实例 —— 「A 站 + B 站」不用写两个文件"""
        store.add("booruA", module_path="imgsearch.engines.adapters.generic_json",
                  class_name="GenericJson")
        store.add("booruB", module_path="imgsearch.engines.adapters.generic_json",
                  class_name="GenericJson")
        from imgsearch.engines.registry import resolve_engine_class
        assert resolve_engine_class(store.get("booruA")) is not None
        assert resolve_engine_class(store.get("booruB")) is not None
        assert store.get("booruA").name != store.get("booruB").name


# ──────────────────────────────────────────────
#  字段变换与运行时能力（把内置引擎改造成配置的前提）
# ──────────────────────────────────────────────


class TestFieldTransforms:
    def test_strip_prefix(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        assert apply_transforms("artist:someone", ["strip_prefix:artist:"]) == "someone"

    def test_strip_prefix_not_present_keeps_value(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        assert apply_transforms("someone", ["strip_prefix:artist:"]) == "someone"

    def test_strip_suffix(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        assert apply_transforms("foo.jpg", ["strip_suffix:.jpg"]) == "foo"

    def test_regex_first_group(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        url = "https://www.pixiv.net/artworks/12345"
        assert apply_transforms(url, [r"regex:artworks/(\d+)"]) == "12345"

    def test_regex_no_match_becomes_empty(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        assert apply_transforms("nope", [r"regex:artworks/(\d+)"]) == ""

    def test_regex_without_group_uses_whole_match(self):
        from imgsearch.engines.adapters.declarative import apply_transforms
        assert apply_transforms("abc123", [r"regex:c\d+"]) == "c123"

    def test_split_transform(self):
        from imgsearch.engines.adapters.declarative import split_transform
        assert split_transform("data.x~strip_prefix:a:") == ("data.x", ["strip_prefix:a:"])
        assert split_transform("data.x") == ("data.x", [])

    def test_transform_applied_end_to_end(self):
        """`tag_string_artist` 里带 `artist:` 前缀 —— 配置能把它剥掉"""
        payload = {"r": [{"tag_string_artist": "artist:someone", "id": 1}]}
        adapter = make_json(results_path="r", field_artist="tag_string_artist~strip_prefix:artist:",
                            field_urls="photo_url", similarity_scale="none")
        adapter._request = lambda **k: json.dumps(payload)      # type: ignore
        got = adapter.search("/tmp/x.jpg")
        assert got[0].artist == "someone"


class TestRankSimilarity:
    """有些站点（Danbooru）不返回相似度，只能按排名估算"""

    def _parse(self, n, **kw):
        payload = {"r": [{"id": i, "u": f"u{i}"} for i in range(n)]}
        adapter = make_json(results_path="r", similarity_scale="rank",
                            field_urls="u", **kw)
        adapter._request = lambda **k: json.dumps(payload)      # type: ignore
        return adapter.search("/tmp/x.jpg")

    def test_default_table(self):
        got = self._parse(4)
        assert [r.similarity for r in got] == [100.0, 95.0, 90.0, 85.0]

    def test_custom_table(self):
        got = self._parse(3, rank_scores="50,40,30")
        assert [r.similarity for r in got] == [50.0, 40.0, 30.0]

    def test_beyond_table_uses_last(self):
        got = self._parse(4, rank_scores="50,40")
        assert [r.similarity for r in got] == [50.0, 40.0, 40.0, 40.0]
        # 注意：rank 模式下结果本来就按站点给的顺序，不重排

    def test_empty_table_is_safe(self):
        got = self._parse(2, rank_scores=",,,")
        assert all(r.similarity == 0.0 for r in got)


class TestRuntimeCapabilities:
    def test_rate_limit_fields_present_in_both_adapters(self):
        from imgsearch.engines.adapters.generic_html import GenericHtml
        from imgsearch.engines.adapters.generic_json import GenericJson
        for cls in (GenericJson, GenericHtml):
            keys = {f.key for f in cls.CONFIG_SCHEMA}
            for key in ("long_limit", "long_window", "short_limit",
                        "short_window", "cloudflare_bypass", "follow_redirect",
                        "step2_delay", "rank_scores"):
                assert key in keys, f"{cls.NAME} 缺少 {key}"

    def test_request_interval_from_short_window(self):
        """SauceNAO 是 4 次/30 秒 → 每张间隔 7.5 秒"""
        adapter = make_json(short_limit=4, short_window=30)
        assert adapter.request_interval() == pytest.approx(7.5)

    def test_request_interval_unlimited(self):
        adapter = make_json(short_limit=0, short_window=30)
        assert adapter.request_interval() == 0.0

    def test_quota_state_empty_when_unlimited(self):
        adapter = make_json(long_limit=0)
        assert adapter.quota_state() == []

    def test_quota_state_reports_when_limited(self, monkeypatch, tmp_path):
        from imgsearch.engines import quota as quota_mod
        monkeypatch.setattr(quota_mod, "_QUOTA_DIR", tmp_path, raising=False)
        adapter = make_json(long_limit=100, long_window=86400)
        adapter._quota = None
        states = adapter.quota_state()
        assert len(states) == 1
        assert states[0].limit == 100
