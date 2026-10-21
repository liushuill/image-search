"""
三个「预览」改进的测试

1. 批量识别前：图片清单 + 可勾选排除
2. 图库页：缩略图墙
3. 搜索结果：缩略图列
"""

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore  # noqa: E402

from imgsearch.engines.base import SearchResult  # noqa: E402


def make_images(directory, names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"\xff\xd8\xff")
    return directory


class TestBatchFileList:
    """批量识别前要能看清「这次会跑哪些」，并能排除个别图"""

    def _dialog(self, tmp_path, names=("a.jpg", "b.jpg", "c.png")):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, names)
        return BatchDialog(str(tmp_path))

    def test_lists_every_image(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path)
        try:
            assert dlg.file_list.count() == 3
            assert len(dlg.selected_paths()) == 3       # 默认全选
            assert "3 / 3" in dlg.selection_label.text()
        finally:
            dlg.close()

    def test_unchecking_excludes_from_run(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path)
        try:
            dlg.file_list.item(1).setCheckState(QtCore.Qt.Unchecked)
            assert len(dlg.selected_paths()) == 2
            assert "2 / 3" in dlg.selection_label.text()
        finally:
            dlg.close()

    def test_no_selection_blocks_start(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path)
        try:
            dlg._check_all(False)
            assert dlg.selected_paths() == []
            assert dlg.start_btn.isEnabled() is False
            assert "一张都没勾" in dlg.selection_label.text()
        finally:
            dlg.close()

    def test_select_all_only_affects_visible(self, qapp, tmp_path):
        """
        筛选后点「全不选」只应影响可见项 ——
        否则用户会以为"我只取消了这几张"，实际把隐藏的也改了。
        """
        dlg = self._dialog(tmp_path, ("aa.jpg", "ab.jpg", "zz.jpg"))
        try:
            dlg.filter_edit.setText("a")        # 只剩 aa / ab 可见
            assert len(dlg._visible_items()) == 2
            dlg._check_all(False)
            # zz.jpg 被隐藏，应保持勾选
            assert len(dlg.selected_paths()) == 1
        finally:
            dlg.close()

    def test_invert(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path)
        try:
            dlg.file_list.item(0).setCheckState(QtCore.Qt.Unchecked)
            dlg._invert()
            assert len(dlg.selected_paths()) == 1
        finally:
            dlg.close()

    def test_filter_does_not_change_checks(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path)
        try:
            dlg.filter_edit.setText("zzz")      # 无匹配
            assert len(dlg._visible_items()) == 0
            assert len(dlg.selected_paths()) == 3    # 勾选不受影响
        finally:
            dlg.close()

    def test_limit_shortens_the_list(self, qapp, tmp_path):
        dlg = self._dialog(tmp_path, tuple(f"{i}.jpg" for i in range(10)))
        try:
            dlg.limit.setValue(4)
            assert dlg.file_list.count() == 4
        finally:
            dlg.close()

    def test_recursive_toggle_changes_list(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, ("top.jpg",))
        make_images(tmp_path / "sub", ("deep.jpg",))
        dlg = BatchDialog(str(tmp_path))
        try:
            assert dlg.file_list.count() == 2
            dlg.recursive.setChecked(False)
            assert dlg.file_list.count() == 1
        finally:
            dlg.close()

    def test_empty_directory_disables_start(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        tmp_path.mkdir(exist_ok=True)
        dlg = BatchDialog(str(tmp_path))
        try:
            assert dlg.file_list.count() == 0
            assert dlg.start_btn.isEnabled() is False
        finally:
            dlg.close()


class TestBatchExplicitPaths:
    """run_batch 必须尊重界面传来的清单（勾掉的图不该因为重新扫描又回来）"""

    def test_explicit_paths_win_over_scan(self, tmp_path, monkeypatch):
        from imgsearch import batch as B
        from imgsearch.service import SearchOutcome

        make_images(tmp_path, ("a.jpg", "b.jpg", "c.jpg"))
        seen = []
        monkeypatch.setattr(B, "search_with_cache",
                            lambda p, **k: seen.append(p) or SearchOutcome(
                                results=[], dhash="x"))
        store = _OneUsableEngine()
        monkeypatch.setattr(B, "_engines", lambda *_: store)

        chosen = [str(tmp_path / "a.jpg"), str(tmp_path / "c.jpg")]
        report = B.run_batch(tmp_path, paths=chosen, engine_store=store)
        assert report.total == 2
        assert len(seen) == 2
        assert not any(p.endswith("b.jpg") for p in seen)

    def test_paths_ignore_recursive_and_limit(self, tmp_path, monkeypatch):
        from imgsearch import batch as B
        from imgsearch.service import SearchOutcome
        make_images(tmp_path, ("a.jpg", "b.jpg", "c.jpg"))
        monkeypatch.setattr(B, "search_with_cache",
                            lambda p, **k: SearchOutcome(results=[], dhash="x"))
        store = _OneUsableEngine()
        monkeypatch.setattr(B, "_engines", lambda *_: store)
        report = B.run_batch(tmp_path, paths=[str(tmp_path / "a.jpg")],
                             limit=99, recursive=False, engine_store=store)
        assert report.total == 1


class _FakeCfg:
    name = "fake"
    display_name = "Fake"

    def get(self, key, default=None):
        return default


class _FakeEngine:
    def quota_state(self):
        return []

    def request_interval(self):
        return 0.0


class _OneUsableEngine:
    def get_enabled(self):
        return [_FakeCfg()]

    def build_engine(self, config):
        return _FakeEngine()


class TestThumbnailLoader:
    def test_stable_key_ignores_token(self):
        """
        实测：SauceNAO 的缩略图链接带 ?auth=…，当场有效、过一会儿 403。
        路径部分是稳定的，所以缓存键要去掉查询串 ——
        否则重新搜索同一张图会再下一次。
        """
        from imgsearch_gui.widgets.thumbnails import stable_url_key
        base = "https://img3.saucenao.com/booru/d/4/abc_0.jpg"
        assert stable_url_key(base + "?auth=AAA&exp=1") == base
        assert stable_url_key(base + "?auth=BBB&exp=2") == base
        assert stable_url_key(base) == base

    def test_same_cache_path_for_rotating_token(self):
        """存储归核心层管（清理页也在核心层，不能反向依赖 Qt）"""
        from imgsearch.library.thumbs import url_thumb_path
        assert url_thumb_path("https://x/y.jpg?auth=1") == \
            url_thumb_path("https://x/y.jpg?auth=2")

    def test_gui_loader_delegates_storage_to_core(self):
        """界面模块不该自己实现缓存路径 —— 否则与清理页看到的两套"""
        import imgsearch_gui.widgets.thumbnails as mod
        assert not hasattr(mod, "_url_cache_path")
        assert mod.url_thumb_path is __import__(
            "imgsearch.library.thumbs", fromlist=["x"]).url_thumb_path

    def test_loader_starts_thread_lazily(self, qapp):
        """构造加载器不该起线程 —— 否则忘了收尾的地方会 abort 整个进程"""
        from imgsearch_gui.widgets.thumbnails import ThumbnailLoader
        loader = ThumbnailLoader()
        try:
            assert loader._worker is None
            loader.request("k", url="https://example.invalid/x.jpg")
            assert loader._worker is not None
        finally:
            loader.stop()

    def test_loader_dedupes_same_key(self, qapp):
        from imgsearch_gui.widgets.thumbnails import ThumbnailLoader
        loader = ThumbnailLoader()
        try:
            loader.request("k", url="https://example.invalid/x.jpg")
            loader.request("k", url="https://example.invalid/x.jpg")
            assert loader._worker._queue.qsize() <= 1
        finally:
            loader.stop()

    def test_forget_allows_rerequest(self, qapp):
        from imgsearch_gui.widgets.thumbnails import ThumbnailLoader
        loader = ThumbnailLoader()
        try:
            loader.request("k", url="https://example.invalid/x.jpg")
            assert "k" in loader._asked
            loader.forget("k")
            assert "k" not in loader._asked
        finally:
            loader.stop()


class TestResultTableThumbnails:
    def _table(self):
        from imgsearch_gui.widgets.result_table import ResultTable
        return ResultTable()

    def test_has_a_thumb_column_first(self):
        from imgsearch_gui.widgets.result_table import COLUMNS, COL_THUMB
        assert COL_THUMB == 0
        assert COLUMNS[0] == "预览"
        assert len(COLUMNS) == 8

    def test_placeholder_when_no_thumbnail_url(self, qapp):
        from imgsearch_gui.widgets.result_table import COL_THUMB
        t = self._table()
        try:
            t.set_results([SearchResult(source="X", similarity=10.0)])
            widget = t.cellWidget(0, COL_THUMB)
            assert widget.text() == "—"
        finally:
            t._thumbs.stop()

    def test_shows_waiting_then_loads(self, qapp):
        from imgsearch_gui.widgets.result_table import COL_THUMB
        t = self._table()
        try:
            t.set_results([SearchResult(
                source="IQDB", similarity=46.0,
                thumbnail="https://iqdb.org/danbooru/8/6/3/"
                          "86343289002701f07695519e9749b9e9.jpg")])
            assert t.cellWidget(0, COL_THUMB).text() == "…"
        finally:
            t._thumbs.stop()

    def test_row_height_fits_the_thumbnail(self, qapp):
        from imgsearch_gui.widgets.result_table import ROW_HEIGHT
        t = self._table()
        try:
            t.set_results([SearchResult(source="X", similarity=10.0)])
            assert t.rowHeight(0) >= ROW_HEIGHT
        finally:
            t._thumbs.stop()

    def test_failed_thumbnail_is_explained(self, qapp):
        """
        取不到必须说清楚 —— 否则占位永远停在「…」，
        用户分不清是还在加载还是已经失败。
        """
        from imgsearch_gui.widgets.result_table import COL_THUMB, THUMB_FAILED
        t = self._table()
        try:
            t.set_results([SearchResult(
                source="X", similarity=10.0,
                thumbnail="https://img3.saucenao.com/booru/expired.jpg?auth=old")])
            key = t._stable_key("https://img3.saucenao.com/booru/expired.jpg?auth=old")
            t._on_thumb_failed(key)                 # 直接触发失败回调
            assert t.cellWidget(0, COL_THUMB).text() == THUMB_FAILED
            assert "过期" in THUMB_FAILED
        finally:
            t._thumbs.stop()

    def test_reuses_already_loaded_pixmap(self, qapp):
        """同一个图源出现多次时，后出现的不该再转一次「…」"""
        from PySide6 import QtGui
        from imgsearch_gui.widgets.result_table import COL_THUMB
        t = self._table()
        try:
            url = "https://x/y.jpg"
            key = t._stable_key(url)
            pix = QtGui.QPixmap(4, 4)
            t._pixmaps[key] = pix
            t.set_results([SearchResult(source="X", similarity=1, thumbnail=url)])
            widget = t.cellWidget(0, COL_THUMB)
            assert not widget.pixmap().isNull()
            assert widget.text() == ""
        finally:
            t._thumbs.stop()


class TestLibraryBrowser:
    """
    缩略图墙现在是**独立页面**（侧栏「浏览」），不再是弹窗 ——
    弹窗要开/关，也没法反复对照。
    """

    def _page(self, library):
        from imgsearch_gui.pages.library_browser_page import LibraryBrowserPage
        page = LibraryBrowserPage()
        # 页面自己会 open_library()；测试里直接注入 fixture 的库
        db, store = library
        page._db, page._store = db, store
        return page

    def test_lists_images(self, qapp, library, pattern_image):
        db, store = library
        for i in range(3):
            store.upsert_image(str(pattern_image(f"p{i}.png", seed=300 + i)))
        page = self._page(library)
        try:
            page.reload()
            assert page.model.rowCount() == 3
            assert "共 3 张" in page.status.text()
        finally:
            page._thumbs.stop()

    def test_search_filters(self, qapp, library, pattern_image):
        db, store = library
        # ⚠️ seed 必须不同：相同 seed 的图 dHash 相同，
        # 会被 upsert_image 视为同一张图（内容才是身份），于是只留一条记录
        for name, seed in (("alpha.png", 310), ("beta.png", 311)):
            store.upsert_image(str(pattern_image(name, seed=seed)))
        page = self._page(library)
        try:
            page.reload()
            page.search_edit.setText("alpha")
            assert page.model.rowCount() == 1
            page.search_edit.clear()
            assert page.model.rowCount() == 2
        finally:
            page._thumbs.stop()

    def test_item_carries_dhash_and_path(self, qapp, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("one.png", seed=320)))
        page = self._page(library)
        try:
            page.reload()
            item = page.model.item(0)
            assert item.data(QtCore.Qt.UserRole) == rec.dhash
            assert item.data(QtCore.Qt.UserRole + 1) == rec.abs_path
        finally:
            page._thumbs.stop()

    def test_missing_files_flagged(self, qapp, library, pattern_image):
        db, store = library
        p = pattern_image("gone.png", seed=330)
        store.upsert_image(str(p))
        import os
        os.remove(p)
        store.roots.refresh_missing()
        page = self._page(library)
        try:
            page.reload()
            assert "已不在原位置" in page.model.item(0).toolTip()
        finally:
            page._thumbs.stop()

    def test_empty_library_is_graceful(self, qapp, library):
        page = self._page(library)
        try:
            page.reload()
            assert page.model.rowCount() == 0
            assert "图库里还没有图片" in page.status.text()
        finally:
            page._thumbs.stop()


class TestLibraryStoreListImages:
    def test_filters_and_order(self, library, pattern_image):
        db, store = library
        for name, seed in (("aaa.png", 340), ("bbb.png", 341)):
            store.upsert_image(str(pattern_image(name, seed=seed)))
        assert len(store.list_images()) == 2
        assert len(store.list_images(search="aaa")) == 1
        assert len(store.list_images(search="AAA")) == 1      # 大小写不敏感
        assert len(store.list_images(search="zzz")) == 0
        assert len(store.list_images(limit=1)) == 1

    def test_dhash_searchable(self, library, pattern_image):
        db, store = library
        rec = store.upsert_image(str(pattern_image("d.png", seed=350)))
        assert len(store.list_images(search=rec.dhash[:6])) == 1

    def test_only_resolved(self, library, pattern_image):
        db, store = library
        a = store.upsert_image(str(pattern_image("r1.png", seed=360)))
        store.upsert_image(str(pattern_image("r2.png", seed=361)))
        store.save_results(a.id, [SearchResult(source="x", similarity=90.0)])
        assert len(store.list_images(only_resolved=True)) == 1
        assert len(store.list_images()) == 2

    def test_scope_by_root(self, library, pattern_image, tmp_path):
        from imgsearch.library import RootManager
        db, store = library
        ra = tmp_path / "A"
        rb = tmp_path / "B"
        ra.mkdir()
        rb.mkdir()
        roots = RootManager(db)
        root_a = roots.add(str(ra))
        roots.add(str(rb))
        store.upsert_image(str(pattern_image(ra / "x.png", seed=370)))
        store.upsert_image(str(pattern_image(rb / "y.png", seed=371)))
        assert len(store.list_images(root_id=root_a.id)) == 1

    def test_only_missing(self, library, pattern_image):
        db, store = library
        import os
        p = pattern_image("m.png", seed=380)
        store.upsert_image(str(p))
        store.upsert_image(str(pattern_image("keep.png", seed=381)))
        os.remove(p)
        store.roots.refresh_missing()
        assert len(store.list_images(only_missing=True)) == 1


class TestBrowserPageLifecycle:
    """
    浏览页是独立页面（不是弹窗），所以它必须在**每次被展示时**刷新 ——
    用户可能刚搜完图、刚批量识别过，或在清理页删过东西。
    """

    def test_on_shown_loads_the_library(self, qapp, library, pattern_image, monkeypatch):
        from imgsearch_gui.pages import library_browser_page as mod

        db, store = library
        for i in range(2):
            store.upsert_image(str(pattern_image(f"x{i}.png", seed=600 + i)))

        page = mod.LibraryBrowserPage()
        try:
            # on_shown 会自己 open_library()，测试里把它指到 fixture 的库
            monkeypatch.setattr("imgsearch.service.open_library",
                                lambda *a, **k: (db, store))
            monkeypatch.setattr(
                "imgsearch.library.paths.RootManager.list",
                lambda self: [])
            page.on_shown()
            assert page.model.rowCount() == 2
            assert "共 2 张" in page.status.text()
        finally:
            page._thumbs.stop()

    def test_on_shown_prevents_stale_data(self, qapp, library, pattern_image, monkeypatch):
        """切走再切回，必须看到新数据而不是上次的快照"""
        from imgsearch_gui.pages import library_browser_page as mod

        db, store = library
        store.upsert_image(str(pattern_image("first.png", seed=610)))

        page = mod.LibraryBrowserPage()
        try:
            monkeypatch.setattr("imgsearch.service.open_library",
                                lambda *a, **k: (db, store))
            monkeypatch.setattr(
                "imgsearch.library.paths.RootManager.list",
                lambda self: [])
            page.on_shown()
            assert page.model.rowCount() == 1

            store.upsert_image(str(pattern_image("second.png", seed=611)))
            page.on_shown()
            assert page.model.rowCount() == 2, "再次进入应当刷新"
        finally:
            page._thumbs.stop()

    def test_shows_hint_when_library_disabled(self, qapp, monkeypatch):
        from imgsearch_gui.pages import library_browser_page as mod

        page = mod.LibraryBrowserPage()
        try:
            monkeypatch.setattr("imgsearch.service.open_library",
                                lambda *a, **k: (None, None))
            page.on_shown()
            assert "图库未启用" in page.status.text() or "无法打开" in page.status.text()
        finally:
            page._thumbs.stop()


class TestNavigationRefreshesBrowser:
    """
    主窗口切页时要调用新页面的 on_shown ——
    否则浏览页会一直显示"切到本页时会自动读取图库"的占位。
    """

    def test_go_to_calls_on_shown(self, qapp, monkeypatch):
        from imgsearch_gui.main_window import MainWindow
        from imgsearch_gui.pages import library_browser_page as mod

        called = {"n": 0}
        original = mod.LibraryBrowserPage.on_shown

        def spy(self):
            called["n"] += 1
            original(self)

        monkeypatch.setattr(mod.LibraryBrowserPage, "on_shown", spy)
        win = MainWindow()
        try:
            index = win.pages.indexOf(win.browser_page)
            win.go_to(index)
            qapp.processEvents()
            assert called["n"] >= 1
        finally:
            win.close()

    def test_browser_page_is_in_the_nav(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            names = [b.text() for b in win._navs]
            assert "浏览" in names
            assert win.pages.indexOf(win.browser_page) > 0
        finally:
            win.close()

    def test_library_page_button_navigates(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            win.go_to(win.pages.indexOf(win.library_page))
            win.library_page.browse_requested.emit()
            qapp.processEvents()
            assert win.pages.currentWidget() is win.browser_page
        finally:
            win.close()
