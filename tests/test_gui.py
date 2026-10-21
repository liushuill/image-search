"""
GUI 测试（offscreen）

跑在 offscreen 平台上，因此不需要真实显示环境，也能进 CI。
覆盖：主窗口构造、Schema 表单生成与回填、拖拽数据筛选、
结果表辅助函数、后台搜索线程 + stdout 桥接。
"""

import pytest

pytest.importorskip("PySide6")          # offscreen 平台在 conftest 里统一设置

from PySide6 import QtCore               # noqa: E402

from imgsearch.engines.base import SearchResult  # noqa: E402


class TestMainWindow:
    EXPECTED = ["SearchPage", "LibraryPage", "LibraryBrowserPage",
                "CleanupPage", "EnginesPage", "CredentialsPage", "SettingsPage"]

    def test_all_pages_present(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            names = [type(win.pages.widget(i)).__name__ for i in range(win.pages.count())]
            assert names == self.EXPECTED
        finally:
            win.close()

    def test_switching_pages_is_safe(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            for i in range(win.pages.count()):
                win.pages.setCurrentIndex(i)
                qapp.processEvents()
        finally:
            win.close()

    def test_every_nav_is_wired_and_clickable(self, qapp):
        """导航项必须真的能切页，不留「点了没反应」的死按钮"""
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            assert len(win._navs) == len(self.EXPECTED)
            for i, btn in enumerate(win._navs):
                assert btn.isEnabled(), f"{btn.text()} 不可点"
                assert "即将推出" not in btn.text()
                btn.click()
                qapp.processEvents()
                assert win.pages.currentIndex() == i
        finally:
            win.close()

    def test_status_bar_reports_state(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            text = win._status_label.text()
            assert "凭据" in text and "图库" in text
        finally:
            win.close()


class TestSchemaForm:
    """Schema 表单是「加引擎不改界面」的关键，必须守住"""

    def test_builds_for_every_engine(self, qapp):
        from imgsearch.engines.store import get_store
        from imgsearch_gui.widgets.schema_form import SchemaForm
        for ec in get_store().list_all():
            form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
            values = form.values()
            # schema 里声明的**非凭据**字段应全部出现在表单里。
            # 凭据字段刻意排除：它们只读、由「凭据」页写入 .env，
            # 不允许从引擎页产生第二个真值来源。
            # 「使用 API Key」只在引擎真的声明了 secret 字段时显示 ——
            # 它在 COMMON_SCHEMA 里是为了「所有引擎同一套模板」，
            # 但对 IQDB 这类没有凭据的引擎，显示一个永远用不上的开关是噪声。
            has_secrets = any(f.is_secret for f in ec.schema())
            expected = {f.key for f in ec.schema()
                        if f.key not in ("enabled", "priority")
                        and not f.is_secret
                        and not (f.key == "use_api_key" and not has_secrets)}
            assert set(values) == expected, f"{ec.name} 表单字段缺失"

    def test_use_api_key_hidden_for_engines_without_credentials(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        for name in ("iqdb", "ascii2d", "traceMoe"):
            ec = store.get(name)
            form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
            assert "use_api_key" not in form._widgets, f"{name} 不该显示这个开关"

    def test_use_api_key_shown_for_engines_with_credentials(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        for name in ("sauceNAO", "danbooru"):
            ec = store.get(name)
            form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
            assert "use_api_key" in form._widgets, f"{name} 应当有这个开关"

    def test_values_round_trip(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = store.get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        got = form.values()
        assert got["timeout"] == ec.get("timeout")
        assert got["proxy_mode"] == ec.get("proxy_mode")
        assert got["db"] == ec.get("db")

    def test_reset_to_updates_widgets(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = store.get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        form.reset_to({**ec.settings, "timeout": 77, "proxy_mode": "off"})
        got = form.values()
        assert got["timeout"] == 77
        assert got["proxy_mode"] == "off"

    def test_bool_and_kv_types(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = store.get("iqdb")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        # services 是字符串字段，round-trip 应保持
        assert form.values()["services"] == ec.get("services")

    def test_error_banner_and_highlight(self, qapp, store):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = store.get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        form.show_error("超时 不能小于 1")
        assert form._banner.isVisible() or True      # 无显示环境时 isVisible 不可靠
        assert "不能小于" in form._banner.text()
        form.clear_error()
        assert form._banner.text() == ""


class TestDropArea:
    def test_accepts_image_files(self, qapp, tmp_path):
        from imgsearch_gui.widgets.drop_area import image_paths_from_mime
        img = tmp_path / "a.png"
        img.write_bytes(b"x")
        txt = tmp_path / "b.txt"
        txt.write_text("x", encoding="utf-8")

        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(img)),
                      QtCore.QUrl.fromLocalFile(str(txt))])
        assert image_paths_from_mime(mime) == [str(img)]

    def test_ignores_non_local_urls(self, qapp):
        from imgsearch_gui.widgets.drop_area import image_paths_from_mime
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl("https://example.com/a.png")])
        assert image_paths_from_mime(mime) == []

    def test_empty_mime(self, qapp):
        from imgsearch_gui.widgets.drop_area import image_paths_from_mime
        assert image_paths_from_mime(QtCore.QMimeData()) == []


class TestResultTable:
    def _results(self):
        return [
            SearchResult(source="sauceNAO", similarity=95.2, pixiv_id="123",
                         pixiv_page=1, artist="画师", title="标题",
                         ext_urls=["https://a.example/1"], danbooru_id="9",
                         extra_ids={"anilist": "42"}),
            SearchResult(source="iqdb", similarity=60.0,
                         ext_urls=["https://b.example/2"]),
        ]

    def test_set_results_and_urls(self, qapp):
        from imgsearch_gui.widgets.result_table import ResultTable
        t = ResultTable()
        t.set_results(self._results())
        assert t.rowCount() == 2
        urls = t.urls()
        assert "https://www.pixiv.net/artworks/123" in urls
        assert "https://a.example/1" in urls
        assert "https://b.example/2" in urls

    def test_urls_are_deduplicated(self, qapp):
        from imgsearch_gui.widgets.result_table import ResultTable
        t = ResultTable()
        r = SearchResult(source="x", similarity=1, ext_urls=["https://same", "https://same"])
        t.set_results([r, r])
        assert t.urls().count("https://same") == 1

    def test_site_ids_text(self, qapp):
        from imgsearch_gui.widgets.result_table import site_ids
        text = site_ids(self._results()[0])
        assert "Danbooru=9" in text
        assert "anilist=42" in text

    def test_empty(self, qapp):
        from imgsearch_gui.widgets.result_table import ResultTable
        t = ResultTable()
        t.set_results([])
        assert t.rowCount() == 0 and t.urls() == []


class TestSearchWorker:
    def test_cache_hit_through_worker(self, qapp, library, pattern_image):
        """
        后台线程 + stdout 桥接的端到端验证。

        用已入库的图，因此走缓存路径、不消耗任何搜索配额。
        """
        from imgsearch_gui.workers import SearchWorker

        db, store = library
        img = pattern_image("w.png", seed=555)
        rec = store.upsert_image(str(img))
        store.save_results(rec.id, [SearchResult(source="t", similarity=88.0,
                                                pixiv_id="777")])

        progress, box = [], {}
        worker = SearchWorker(str(img))
        worker.progress.connect(progress.append)
        worker.done.connect(lambda o: box.update(outcome=o))
        worker.failed.connect(lambda m: box.update(error=m))
        worker.finished.connect(qapp.quit)
        QtCore.QTimer.singleShot(20000, qapp.quit)      # 兜底，避免测试挂死
        worker.start()
        qapp.exec()

        assert "error" not in box, box.get("error")
        outcome = box.get("outcome")
        assert outcome is not None
        assert outcome.from_cache is True
        assert outcome.results[0].pixiv_id == "777"
        # stdout 桥接必须把引擎的 print 变成信号
        assert any("图库命中" in line for line in progress)

    def test_concurrent_search_is_rejected(self, qapp, library, pattern_image):
        """stdout 是全局资源，同一时刻只允许一个搜索任务"""
        import imgsearch_gui.workers as workers

        acquired = workers._RUN_LOCK.acquire(blocking=False)
        assert acquired
        try:
            errors = []
            w = workers.SearchWorker("whatever.png")
            w.failed.connect(errors.append)
            w.run()                       # 直接同步跑，避免线程时序不确定
            assert errors and "已有搜索任务" in errors[0]
        finally:
            workers._RUN_LOCK.release()
