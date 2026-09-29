"""
图库记录层测试

最重要的一条：**文件被移动后，仍能凭内容认出「这张搜过了」**。

用户的真实工作流是「搜完 → 下载原图 → 把图统一移到『搜集过的』目录」，
路径不断变化。如果按路径索引，这个功能就完全失效。
"""

import os

import pytest
from PIL import Image

from imgsearch.engines.base import SearchResult
from imgsearch.library import LibraryError, fingerprint_file


class TestFingerprint:
    def test_returns_hash_and_dims(self, pattern_image):
        p = pattern_image("a.png", seed=1, size=(120, 80))
        fp = fingerprint_file(str(p))
        assert len(fp.dhash) == 16
        assert (fp.width, fp.height) == (120, 80)
        assert fp.size > 0

    def test_same_content_same_hash(self, pattern_image, tmp_path):
        a = pattern_image("a.png", seed=3)
        b = tmp_path / "改了个名.png"
        b.write_bytes(a.read_bytes())
        assert fingerprint_file(str(a)).dhash == fingerprint_file(str(b)).dhash

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(LibraryError, match="文件不存在"):
            fingerprint_file(str(tmp_path / "没有这个.png"))

    def test_non_image_raises(self, tmp_path):
        bad = tmp_path / "假图.png"
        bad.write_text("not an image", encoding="utf-8")
        with pytest.raises(LibraryError, match="无法读取图片内容"):
            fingerprint_file(str(bad))


class TestUpsert:
    def test_insert_then_dedupe(self, library, pattern_image):
        """同一内容不应产生第二条记录"""
        db, store = library
        a = pattern_image("a.png", seed=5)
        rec1 = store.upsert_image(str(a))
        rec2 = store.upsert_image(str(a))
        assert rec1.id == rec2.id
        assert store.count_images() == 1

    def test_records_live_in_unknown_root(self, library, pattern_image):
        """图片不在任何已登记根路径下也要能入库（root_id 为空）"""
        db, store = library
        a = pattern_image("孤图.png", seed=6)
        rec = store.upsert_image(str(a))
        assert rec.root_id is None
        assert store.count_images() == 1


class TestContentIdentityAcrossMoves:
    """核心回归：路径变了，身份不变"""

    def test_lookup_after_move(self, library, pattern_image, tmp_path):
        db, store = library
        src = pattern_image("原位置.png", seed=7)
        rec = store.upsert_image(str(src))
        store.save_results(rec.id, [SearchResult(source="t", similarity=95.0,
                                                pixiv_id="123")])

        # 用户搜完把图移到了别处
        moved = tmp_path / "搜集过的" / "移过来的.png"
        moved.parent.mkdir()
        src.rename(moved)

        match = store.lookup(str(moved))
        assert match is not None, "文件移动后认不出来了"
        assert match.kind == "exact"
        assert match.record.id == rec.id
        assert store.has_results(rec.id)
        assert store.load_results(rec.id)[0].pixiv_id == "123"

    def test_lookup_after_rename_only(self, library, pattern_image, tmp_path):
        db, store = library
        src = pattern_image("原名.png", seed=8)
        store.upsert_image(str(src))
        renamed = tmp_path / "新名.png"
        src.rename(renamed)
        assert store.lookup(str(renamed)) is not None

    def test_upsert_after_move_updates_path_not_duplicates(
            self, library, pattern_image, tmp_path):
        """移动后再入库应更新「最后已知位置」，而不是新建记录"""
        db, store = library
        src = pattern_image("a.png", seed=9)
        rec = store.upsert_image(str(src))
        moved = tmp_path / "new" / "a.png"
        moved.parent.mkdir()
        src.rename(moved)

        again = store.upsert_image(str(moved))
        assert again.id == rec.id
        assert store.count_images() == 1
        assert again.abs_path == os.path.realpath(str(moved))
        assert again.missing is False

    def test_lookup_works_for_file_outside_any_root(
            self, library, pattern_image, tmp_path):
        db, store = library
        src = pattern_image("a.png", seed=10)
        store.upsert_image(str(src))
        outside = tmp_path / "完全在别处" / "x.png"
        outside.parent.mkdir()
        src.rename(outside)
        assert store.lookup(str(outside)) is not None

    def test_unknown_image_returns_none(self, library, pattern_image):
        db, store = library
        assert store.lookup(str(pattern_image("没搜过的.png", seed=99))) is None


class TestPerceptualMatch:
    """识别「同一张图被压缩/缩放过」—— 对应原始需求里的质量压缩问题"""

    def test_downscaled_and_recompressed_is_detected(
            self, library, pattern_image, tmp_path):
        db, store = library
        src = pattern_image("原图.png", seed=11, size=(400, 300))
        store.upsert_image(str(src))

        small = tmp_path / "压缩版.jpg"
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((im.width // 2, im.height // 2), Image.LANCZOS)
            im.save(small, quality=30)

        match = store.lookup(str(small))
        assert match is not None, "压缩+缩放后的版本没认出来"
        assert match.kind in ("scaled", "similar")
        assert match.is_same_image or match.kind == "similar"

    def test_different_image_not_matched(self, library, pattern_image):
        db, store = library
        store.upsert_image(str(pattern_image("a.png", seed=20)))
        other = pattern_image("b.png", seed=21)
        match = store.lookup(str(other), max_distance=2)
        assert match is None, "不相关的图不应被当成同一张"

    def test_exact_beats_similar(self, library, pattern_image, tmp_path):
        db, store = library
        a = pattern_image("a.png", seed=30)
        store.upsert_image(str(a))
        exact = store.find_by_dhash(fingerprint_file(str(a)).dhash)
        assert exact.kind == "exact"


class TestResults:
    def test_save_and_load_round_trip(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=40)))
        original = [
            SearchResult(source="sauceNAO", similarity=95.2, pixiv_id="123",
                         pixiv_page=2, artist="画师", artist_id="9", title="标题",
                         material="出处", ext_urls=["https://a", "https://b"],
                         highres_url="https://h", thumbnail="https://t",
                         danbooru_id="1", gelbooru_id="2", twitter_id="3",
                         extra_ids={"anilist": "42"}, detail="备注"),
        ]
        store.save_results(rec.id, original)
        loaded = store.load_results(rec.id)

        assert len(loaded) == 1
        r = loaded[0]
        assert (r.source, r.similarity, r.pixiv_id, r.pixiv_page) == ("sauceNAO", 95.2, "123", 2)
        assert r.artist == "画师" and r.title == "标题" and r.material == "出处"
        assert r.ext_urls == ["https://a", "https://b"]
        assert r.extra_ids == {"anilist": "42"}
        assert r.detail == "备注"

    def test_replace_not_append(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=41)))
        store.save_results(rec.id, [SearchResult(source="x", similarity=10)])
        store.save_results(rec.id, [SearchResult(source="y", similarity=20)])
        loaded = store.load_results(rec.id)
        assert len(loaded) == 1 and loaded[0].source == "y"

    def test_append_mode(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=42)))
        store.save_results(rec.id, [SearchResult(source="x", similarity=10)])
        store.save_results(rec.id, [SearchResult(source="y", similarity=20)], replace=False)
        assert len(store.load_results(rec.id)) == 2

    def test_results_ordered_by_similarity(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=43)))
        store.save_results(rec.id, [
            SearchResult(source="a", similarity=50),
            SearchResult(source="b", similarity=90),
            SearchResult(source="c", similarity=70),
        ])
        assert [r.similarity for r in store.load_results(rec.id)] == [90, 70, 50]

    def test_has_results(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=44)))
        assert store.has_results(rec.id) is False
        store.save_results(rec.id, [SearchResult(source="x", similarity=1)])
        assert store.has_results(rec.id) is True

    def test_deleting_image_cascades_results(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("a.png", seed=45)))
        store.save_results(rec.id, [SearchResult(source="x", similarity=1)])
        with db.transaction():
            db.conn.execute("DELETE FROM images WHERE id = ?", (rec.id,))
        assert store.count_results() == 0


class TestCounts:
    def test_counts(self, library, pattern_image):
        db, store = library
        a = store.upsert_image(str(pattern_image("a.png", seed=50)))
        store.upsert_image(str(pattern_image("b.png", seed=51)))
        store.save_results(a.id, [
            SearchResult(source="x", similarity=1),
            SearchResult(source="y", similarity=2),
        ])
        assert store.count_images() == 2
        assert store.count_resolved() == 1
        assert store.count_results() == 2
