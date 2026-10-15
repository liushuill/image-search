"""
图库清理测试

关键回归：**清理后磁盘空间必须真的变小**。

SQLite 的 DELETE 只把页标记为可复用，文件不会缩小；而 WAL 模式下
VACUUM 的产物又先落在 -wal 里 —— 不 checkpoint 的话磁盘占用
看起来不降反升。这是「清了半天发现文件没变小」的根因。
"""

import pytest

from imgsearch.engines.base import SearchResult
from imgsearch.library import (
    LibraryError,
    PurgeOptions,
    RootManager,
    collect_stats,
    execute_purge,
    plan_purge,
    purge_orphan_thumbs,
)
from imgsearch.library import thumbs


def _populate(db, store, pattern_image, root_dir, count=4,
              with_results=True, seed_base=100):
    """
    在指定根目录下造 count 张图并入库。

    ⚠️ seed_base 必须各目录不同：否则两个目录会生成**内容相同**的图，
    被 dHash 判重合并成一条记录（去重是对的，但那不是这些测试想验的东西）。
    """
    recs = []
    for i in range(count):
        img = pattern_image(root_dir / f"p{i}.png", seed=seed_base + i)
        rec = store.upsert_image(str(img))
        if with_results:
            store.save_results(rec.id, [
                SearchResult(source="t", similarity=90.0, pixiv_id=str(1000 + i))
            ])
        thumbs.ensure(rec.dhash, str(img))
        recs.append(rec)
    return recs


class TestStats:
    def test_empty(self, library):
        db, store = library
        stats = collect_stats(db, store)
        assert stats.images == 0
        assert stats.results == 0
        assert stats.roots == []

    def test_per_root_counts(self, library, pattern_image, tmp_path):
        db, store = library
        a = tmp_path / "库A"
        b = tmp_path / "库B"
        a.mkdir()
        b.mkdir()
        roots = RootManager(db)
        ra = roots.add(str(a))
        rb = roots.add(str(b))

        _populate(db, store, pattern_image, a, count=3, seed_base=100)
        _populate(db, store, pattern_image, b, count=2, seed_base=200)

        stats = collect_stats(db, store)
        assert stats.images == 5
        assert stats.results == 5
        by_id = {rs.root.id: rs for rs in stats.roots}
        assert by_id[ra.id].images == 3
        assert by_id[rb.id].images == 2
        assert by_id[ra.id].thumbs == 3

    def test_pending_counts_unresolved(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=3, with_results=False)
        stats = collect_stats(db, store)
        assert stats.images == 3
        assert stats.resolved == 0
        assert stats.roots[0].pending == 3

    def test_orphan_thumbs_detected(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        recs = _populate(db, store, pattern_image, d, count=2)

        # 直接删掉一条记录，缩略图就成了孤儿
        with db.transaction():
            db.conn.execute("DELETE FROM images WHERE id = ?", (recs[0].id,))

        stats = collect_stats(db, store)
        assert stats.orphan_thumbs == 1
        assert stats.thumbs_total == 2


class TestPlan:
    def test_plan_does_not_modify(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=3)

        before_images = store.count_images()
        plan = plan_purge(db, store, PurgeOptions(images=True, thumbs=True))
        assert plan.images == 3
        assert plan.results == 3
        assert plan.thumbs == 3
        assert store.count_images() == before_images, "预演不该改动数据"

    def test_empty_options_rejected(self, library):
        db, store = library
        with pytest.raises(LibraryError, match="没有选择任何要清理的内容"):
            plan_purge(db, store, PurgeOptions())
        with pytest.raises(LibraryError, match="没有选择任何要清理的内容"):
            execute_purge(db, store, PurgeOptions())

    def test_plan_description_is_readable(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=2)
        text = plan_purge(db, store, PurgeOptions(images=True, thumbs=True)).describe()
        assert "全部路径" in text
        assert "图片记录" in text


class TestPurgeResultsOnly:
    def test_results_removed_images_kept(self, library, pattern_image, tmp_path):
        """只清结果：图片记录与 dHash 索引保留，所以「搜过没」依然能判断"""
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        recs = _populate(db, store, pattern_image, d, count=3)

        result = execute_purge(db, store, PurgeOptions(results=True))
        assert result.results_removed == 3
        assert store.count_results() == 0
        assert store.count_images() == 3, "图片记录不该被删"
        assert store.has_results(recs[0].id) is False

        # dHash 索引仍在：还能认出「这张搜过了」
        assert store.lookup(recs[0].abs_path) is not None

    def test_thumbs_survive_when_not_requested(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=2)
        execute_purge(db, store, PurgeOptions(results=True))
        assert thumbs.stats()["count"] == 2


class TestPurgeImages:
    def test_images_and_results_removed_with_thumbs(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=4)

        result = execute_purge(db, store, PurgeOptions(images=True, thumbs=True))
        assert result.images_removed == 4
        assert result.results_removed == 4
        assert result.thumbs_removed == 4
        assert store.count_images() == 0
        assert store.count_results() == 0
        assert thumbs.stats()["count"] == 0

    def test_scope_limited_to_one_root(self, library, pattern_image, tmp_path):
        """按路径清理不能误伤别的路径"""
        db, store = library
        a = tmp_path / "库A"
        b = tmp_path / "库B"
        a.mkdir()
        b.mkdir()
        roots = RootManager(db)
        ra = roots.add(str(a))
        rb = roots.add(str(b))

        _populate(db, store, pattern_image, a, count=3, seed_base=100)
        _populate(db, store, pattern_image, b, count=2, seed_base=200)

        result = execute_purge(db, store,
                               PurgeOptions(root_id=ra.id, images=True, thumbs=True))
        assert result.images_removed == 3
        assert store.count_images(root_id=ra.id) == 0
        assert store.count_images(root_id=rb.id) == 2, "另一条路径的数据被误删了"
        assert thumbs.stats()["count"] == 2

    def test_foreign_key_cascade(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=2)
        execute_purge(db, store, PurgeOptions(images=True))
        assert store.count_results() == 0


class TestThumbsPurge:
    def test_purge_all_thumbs_keeps_records(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        _populate(db, store, pattern_image, d, count=3)

        result = execute_purge(db, store, PurgeOptions(thumbs=True))
        assert result.thumbs_removed == 3
        assert thumbs.stats()["count"] == 0
        assert store.count_images() == 3

    def test_orphan_cleanup(self, library, pattern_image, tmp_path):
        db, store = library
        d = tmp_path / "库"
        d.mkdir()
        RootManager(db).add(str(d))
        recs = _populate(db, store, pattern_image, d, count=3)
        with db.transaction():
            db.conn.execute("DELETE FROM images WHERE id = ?", (recs[0].id,))
        assert purge_orphan_thumbs(db) == 1
        assert thumbs.stats()["count"] == 2


class TestSpaceIsActuallyReclaimed:
    """
    关键回归：报告里说「回收了 X」必须是真话。

    SQLite 的 DELETE 只标记页可复用；WAL 模式下 VACUUM 的结果
    又先落在 -wal。必须 checkpoint → VACUUM → checkpoint 才真正还回磁盘。
    """

    def _inflate(self, db, rows=4000):
        with db.transaction():
            for i in range(rows):
                cur = db.conn.execute(
                    "INSERT INTO images(dhash, abs_path, first_seen, last_seen, size)"
                    " VALUES(?, ?, '2026-01-01', '2026-01-01', 123456)",
                    (f"synth{i:07d}", f"/very/long/path/to/some/collection/{i}.jpg"),
                )
                db.conn.execute(
                    "INSERT INTO results(image_id, engine, similarity, ext_urls,"
                    " artist, title, detail, fetched_at)"
                    " VALUES(?, 'synth', 88.0,"
                    " '[\"https://www.pixiv.net/artworks/12345678\"]',"
                    " 'artist_name', 'artwork title', 'padding detail', '2026-01-01')",
                    (cur.lastrowid,),
                )

    def test_database_file_shrinks_after_purge(self, library):
        db, store = library
        self._inflate(db)
        before = db.size_on_disk()
        assert before > 500_000, f"数据量太小，看不出效果：{before}"

        result = execute_purge(db, store, PurgeOptions(images=True))

        after = db.size_on_disk()
        assert result.images_removed == 4000
        assert after < before, f"文件没变小：{before} → {after}"
        assert result.db_bytes_freed > 0, "报告的回收量为 0，说明没有真正 VACUUM"
        assert result.db_bytes_after == after

    def test_wal_is_checkpointed(self, library):
        """WAL 必须被截断，否则磁盘占用看起来不降反升"""
        db, store = library
        self._inflate(db)
        execute_purge(db, store, PurgeOptions(images=True))
        wal = db.path.with_name(db.path.name + "-wal")
        wal_size = wal.stat().st_size if wal.exists() else 0
        assert wal_size < 100_000, f"WAL 未截断：{wal_size} 字节"

    def test_results_only_purge_also_reclaims(self, library):
        db, store = library
        self._inflate(db)
        before = db.size_on_disk()
        result = execute_purge(db, store, PurgeOptions(results=True))
        assert result.results_removed == 4000
        assert db.size_on_disk() < before

    def test_reported_bytes_match_reality(self, library):
        db, store = library
        self._inflate(db)
        before = db.size_on_disk()
        result = execute_purge(db, store, PurgeOptions(images=True))
        assert result.db_bytes_before == before
        assert result.db_bytes_after == db.size_on_disk()


class TestDuplicateContentAcrossRoots:
    """
    同一份内容出现在两个根路径下时的行为。

    记录以 dHash 为身份，所以**只存一条**，归属先入库的那条路径。
    这是有意的：避免同一张图被统计两次。代价是清理某个路径时，
    这条共享记录也会被删 —— 另一路径下的副本需要重新搜索。

    嵌套根路径已被禁止，所以不会出现「父子路径必然重复」的情况；
    这里覆盖的是用户手工在两个目录各放了一份副本的场景。
    """

    def test_same_content_in_two_roots_creates_one_record(
            self, library, pattern_image, tmp_path):
        db, store = library
        a = tmp_path / "库A"
        b = tmp_path / "库B"
        a.mkdir()
        b.mkdir()
        roots = RootManager(db)
        ra = roots.add(str(a))
        rb = roots.add(str(b))

        # 同一 seed → 同一内容，分别放进两个根路径
        img_a = pattern_image(a / "同一个.png", seed=777)
        img_b = pattern_image(b / "同一个.png", seed=777)

        rec_a = store.upsert_image(str(img_a))
        rec_b = store.upsert_image(str(img_b))

        assert rec_a.id == rec_b.id, "同一内容应只产生一条记录"
        assert store.count_images() == 1
        # 归属最后入库时所在的那条路径
        assert rec_b.root_id == rb.id

        # 因此按库A清理不会动到这条记录（它已归到库B名下）
        plan = plan_purge(db, store, PurgeOptions(root_id=ra.id, images=True))
        assert plan.images == 0


class TestUrlThumbnailCache:
    """
    图源缩略图缓存：整套缓存里**唯一会无界增长**的东西
    （每看一次新图的结果就多几条），所以必须有上限与清理入口。
    """

    def _make(self, count=5, size=10240, base="https://e/{}.jpg"):
        """造 count 个缓存文件，访问时间依次递增（越大越新）"""
        import os
        import time
        from imgsearch.library.thumbs import url_thumb_path

        paths = []
        for i in range(count):
            p = url_thumb_path(base.format(i))
            p.write_bytes(b"x" * size)
            ts = time.time() - (count - i) * 100
            os.utime(p, (ts, ts))
            paths.append(p)
        return paths

    def test_stable_key_ignores_token(self):
        """
        实测：SauceNAO 的缩略图链接带 ?auth=…，当场取 200、过一会儿 403。
        路径部分稳定，所以缓存键要去掉查询串。
        """
        from imgsearch.library.thumbs import stable_url_key, url_thumb_path
        base = "https://img3.saucenao.com/booru/d/4/abc_0.jpg"
        assert stable_url_key(base + "?auth=A&exp=1") == base
        assert url_thumb_path(base + "?auth=A") == url_thumb_path(base + "?auth=B")

    def test_stats_counts_files_and_bytes(self):
        from imgsearch.library import thumbs
        self._make(3, 1000)
        st = thumbs.url_stats()
        assert st["count"] == 3
        assert st["bytes"] >= 3000

    def test_trim_evicts_oldest_first(self):
        from imgsearch.library import thumbs
        paths = self._make(10, 10240)
        result = thumbs.trim_url_cache(max_bytes=50 * 1024)
        assert result["removed"] == 5
        alive = {p.name for p in thumbs.iter_url_files()}
        assert paths[0].name not in alive, "最旧的应当先被淘汰"
        assert paths[-1].name in alive, "最新的应当保留"
        assert result["bytes"] <= 50 * 1024

    def test_trim_zero_means_unlimited(self):
        from imgsearch.library import thumbs
        self._make(4, 10240)
        assert thumbs.trim_url_cache(max_bytes=0)["removed"] == 0
        assert thumbs.url_stats()["count"] == 4

    def test_trim_under_cap_does_nothing(self):
        from imgsearch.library import thumbs
        self._make(2, 1000)
        result = thumbs.trim_url_cache(max_bytes=10 * 1024 * 1024)
        assert result["removed"] == 0
        assert result["kept"] == 2

    def test_trim_reads_config(self):
        import imgsearch.config as cfg
        from imgsearch.library import thumbs
        cfg.load_config()["url_thumb_cache_mb"] = 0        # 0 = 不限制
        self._make(3, 10240)
        assert thumbs.trim_url_cache()["removed"] == 0

    def test_purge_all(self):
        from imgsearch.library import thumbs
        self._make(4, 100)
        result = thumbs.purge_url_cache()
        assert result["removed"] == 4
        assert thumbs.url_stats()["count"] == 0

    def test_purge_selected_urls_only(self):
        from imgsearch.library import thumbs
        paths = self._make(3, 100, base="https://e/{}.jpg")
        target = "https://e/1.jpg"
        result = thumbs.purge_url_cache([target])
        assert result["removed"] == 1
        alive = {p.name for p in thumbs.iter_url_files()}
        assert paths[1].name not in alive
        assert paths[0].name in alive and paths[2].name in alive

    def test_default_config_value(self):
        from imgsearch.config import _DEFAULT_CONFIG
        assert _DEFAULT_CONFIG["url_thumb_cache_mb"] == 100


class TestCleanupIncludesUrlThumbs:
    def _seed_url_cache(self, count=3):
        from imgsearch.library.thumbs import url_thumb_path
        paths = []
        for i in range(count):
            p = url_thumb_path(f"https://e/{i}.jpg")
            p.write_bytes(b"y" * 500)
            paths.append(p)
        return paths

    def test_stats_expose_it(self, library):
        db, store = library
        self._seed_url_cache(3)
        stats = collect_stats(db, store)
        assert stats.url_thumbs == 3
        assert stats.url_thumbs_bytes > 0
        # 合计占用要含它 —— 否则用户在总览里看不到这块
        assert stats.total_bytes >= stats.url_thumbs_bytes

    def test_empty_options_detects_it(self):
        assert PurgeOptions(url_thumbs=True).is_empty() is False

    def test_plan_matches_execution(self, library):
        """预演数字必须与执行一致（否则用户按预演做决定会被骗）"""
        db, store = library
        self._seed_url_cache(4)
        options = PurgeOptions(url_thumbs=True)
        plan = plan_purge(db, store, options)
        assert plan.url_thumbs == 4
        assert plan.estimated_free_bytes >= plan.url_thumbs_bytes

        result = execute_purge(db, store, options)
        assert result.url_thumbs_removed == plan.url_thumbs
        assert collect_stats(db, store).url_thumbs == 0

    def test_plan_describe_mentions_it(self, library):
        db, store = library
        self._seed_url_cache(2)
        text = plan_purge(db, store, PurgeOptions(url_thumbs=True)).describe()
        assert "图源缩略图缓存" in text

    def test_result_describe_mentions_it(self, library):
        db, store = library
        self._seed_url_cache(1)
        result = execute_purge(db, store, PurgeOptions(url_thumbs=True))
        assert "图源缩略图缓存" in result.describe()

    def test_other_options_do_not_delete_url_cache(self, library):
        """只清结果不该顺手把图源缓存也删了 —— 那是用户没选的范围"""
        db, store = library
        self._seed_url_cache(3)
        execute_purge(db, store, PurgeOptions(results=True))
        assert collect_stats(db, store).url_thumbs == 3

    def test_root_scoped_purge_only_touches_that_root(self, library, pattern_image,
                                                      tmp_path):
        """
        按路径清理时，只删该路径名下结果引用的图源缓存。

        ⚠️ 图源缓存按 URL 索引、与根路径无直接关系，所以要**从结果记录反查**——
        而且必须在删除结果行之前反查。
        """
        from imgsearch.engines.base import SearchResult
        from imgsearch.library import RootManager

        db, store = library
        base = tmp_path / "scope"
        a = base / "A"
        b = base / "B"
        a.mkdir(parents=True, exist_ok=True)
        b.mkdir(parents=True, exist_ok=True)
        roots = RootManager(db)
        ra = roots.add(str(a))
        roots.add(str(b))

        # ⚠️ 目录名必须与上面登记的根路径**大小写一致**：
        # Linux 区分大小写，base/a 不在 base/A 之下，root_id 会是 None。
        for name, urls, seed in (("A", ["https://e/a1.jpg", "https://e/a2.jpg"], 500),
                                 ("B", ["https://e/b1.jpg"], 501)):
            img = pattern_image(base / name / f"{name}.png", seed=seed)
            rec = store.upsert_image(str(img))
            store.save_results(rec.id, [
                SearchResult(source="x", similarity=90.0, thumbnail=u)
                for u in urls
            ])
        self._seed_url_cache(0)                    # 清掉无关的，只留下面造的
        from imgsearch.library.thumbs import url_thumb_path
        for u in ("https://e/a1.jpg", "https://e/a2.jpg", "https://e/b1.jpg"):
            url_thumb_path(u).write_bytes(b"z" * 200)

        plan = plan_purge(db, store, PurgeOptions(root_id=ra.id, url_thumbs=True))
        assert plan.url_thumbs == 2, "只该看到 A 名下的两个"

        result = execute_purge(db, store,
                               PurgeOptions(root_id=ra.id, url_thumbs=True))
        assert result.url_thumbs_removed == 2
        remaining = {p.name for p in thumbs.iter_url_files()}
        assert url_thumb_path("https://e/b1.jpg").name in remaining, "B 的不该被删"
