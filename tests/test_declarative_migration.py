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
