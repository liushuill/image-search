"""
新建引擎向导

它是「配置化」这条路的入口：用户不写代码，选 JSON/HTML + 填映射表。
所以这里守两件事：

1. **创建出来的引擎真的能用**（module_path/class_name 指向适配器、映射进去了）
2. **「测试」必须能看到原始响应** —— 没有它，用户分不清
   「映射写错了」还是「站点没返回」
"""

from imgsearch_gui.dialogs.new_engine_dialog import NewEngineDialog


def _fill(dlg, *, name="mybooru", url="https://booru.example",
          endpoint="/posts.json"):
    dlg.name_edit.setText(name)
    dlg.url_edit.setText(url)
    dlg.endpoint_edit.setText(endpoint)
    return dlg


class TestBuild:
    def test_defaults_to_json(self, qapp):
        dlg = NewEngineDialog()
        try:
            assert dlg.type_combo.currentData() == "json"
            assert "results_path" in dlg._form._widgets
            assert "row_selector" not in dlg._form._widgets
        finally:
            dlg.close()

    def test_switch_to_html_swaps_fields(self, qapp):
        dlg = NewEngineDialog()
        try:
            dlg.type_combo.setCurrentIndex(1)
            qapp.processEvents()
            assert "row_selector" in dlg._form._widgets
            assert "container_selector" in dlg._form._widgets
            assert "results_path" not in dlg._form._widgets
        finally:
            dlg.close()

    def test_only_essential_fields_are_shown(self, qapp):
        """45 个字段全塞进来会把人吓退 —— 向导只放「先跑通」必需的"""
        dlg = NewEngineDialog()
        try:
            keys = set(dlg._form._widgets)
            assert "field_artist" in keys
            assert "similarity_scale" in keys
            # 这些属于后续在引擎页调
            for advanced in ("long_limit", "cloudflare_bypass", "auth_mode",
                             "follow_redirect", "rank_scores", "api_key"):
                assert advanced not in keys, advanced
        finally:
            dlg.close()


class TestCollect:
    def test_values_include_basics_and_mapping(self, qapp):
        dlg = _fill(NewEngineDialog())
        try:
            dlg._form._widgets["results_path"].setText("posts")
            values = dlg._collect()
            assert values["api_url"] == "https://booru.example"
            assert values["endpoint"] == "/posts.json"
            assert values["results_path"] == "posts"
        finally:
            dlg.close()


class TestCreate:
    def test_creates_engine_pointing_at_adapter(self, qapp):
        dlg = _fill(NewEngineDialog())
        try:
            dlg._form._widgets["results_path"].setText("posts")
            dlg._create()
            assert dlg.created_name == "mybooru"

            from imgsearch.engines.store import get_store
            ec = get_store().get("mybooru")
            assert ec is not None
            assert ec.class_name == "GenericJson"
            assert "adapters.generic_json" in ec.module_path
            assert ec.settings["results_path"] == "posts"
            assert ec.settings["api_url"] == "https://booru.example"
        finally:
            dlg.close()

    def test_created_engine_actually_works(self, qapp, monkeypatch):
        """向导的产物要能直接 build + 解析 —— 否则「创建成功」是假的"""
        import json

        dlg = _fill(NewEngineDialog())
        try:
            dlg._form._widgets["results_path"].setText("posts")
            dlg._form._widgets["field_similarity"].setText("score")
            dlg._form._widgets["field_artist"].setText(
                "tag_string_artist~strip_prefix:artist:")
            dlg._create()
        finally:
            dlg.close()

        from imgsearch.engines.adapters import generic_json as mod
        from imgsearch.engines.store import get_store

        engine = get_store().build_engine("mybooru")
        assert engine is not None
        monkeypatch.setattr(
            mod.GenericJson, "_request",
            lambda self, **kw: json.dumps(
                {"posts": [{"score": "91.0",
                            "tag_string_artist": "artist:someone"}]}))
        got = engine.search("/tmp/x.jpg")
        assert len(got) == 1
        assert got[0].similarity == 91.0
        assert got[0].artist == "someone"

    def test_html_type_creates_html_adapter(self, qapp):
        dlg = _fill(NewEngineDialog(), name="mysite")
        try:
            dlg.type_combo.setCurrentIndex(1)
            qapp.processEvents()
            dlg._form._widgets["row_selector"].setText("table")
            dlg._create()
            from imgsearch.engines.store import get_store
            ec = get_store().get("mysite")
            assert ec.class_name == "GenericHtml"
            assert ec.settings["row_selector"] == "table"
        finally:
            dlg.close()

    def test_duplicate_name_is_rejected(self, qapp, monkeypatch):
        warned = []
        monkeypatch.setattr(
            "imgsearch_gui.dialogs.new_engine_dialog.QtWidgets.QMessageBox.warning",
            lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""))
        dlg = _fill(NewEngineDialog(), name="sauceNAO")
        try:
            dlg._create()
            assert warned, "重名必须提示"
            assert dlg.created_name == ""
        finally:
            dlg.close()

    def test_empty_name_is_rejected(self, qapp, monkeypatch):
        warned = []
        monkeypatch.setattr(
            "imgsearch_gui.dialogs.new_engine_dialog.QtWidgets.QMessageBox.warning",
            lambda *a, **k: warned.append(True))
        dlg = _fill(NewEngineDialog(), name="")
        try:
            dlg._create()
            assert warned
        finally:
            dlg.close()


class TestTestButton:
    """「测试」的核心价值：让用户看到原始响应"""

    def test_shows_raw_response_and_parsed_fields(self, qapp, tmp_path, monkeypatch):
        image = tmp_path / "x.jpg"
        image.write_bytes(b"\xff\xd8 fake")

        from imgsearch.engines.adapters import generic_json as mod

        raw = ('{"posts": [{"score": "88.5", "tag_string_artist": "artist:someone"}]}')

        def fake_request(self, **kw):
            return raw

        monkeypatch.setattr(mod.GenericJson, "_request", fake_request)
        dlg = _fill(NewEngineDialog())
        try:
            dlg._form._widgets["results_path"].setText("posts")
            dlg._form._widgets["field_similarity"].setText("score")
            dlg._form._widgets["field_artist"].setText(
                "tag_string_artist~strip_prefix:artist:")
            dlg.image_edit.setText(str(image))
            dlg._test()
            text = dlg.test_output.toPlainText()
            assert "响应原文" in text
            assert "88.5" in text                 # 原始响应里能看到
            assert "解析结果：1 条" in text
            assert "someone" in text              # 抽出来的画师
        finally:
            dlg.close()

    def test_reports_parse_failure_instead_of_crashing(self, qapp, tmp_path, monkeypatch):
        image = tmp_path / "x.jpg"
        image.write_bytes(b"\xff\xd8 fake")
        from imgsearch.engines.adapters import generic_html as mod

        monkeypatch.setattr(mod.GenericHtml, "_request",
                            lambda self, **kw: "<html><body>没有结果</body></html>")
        dlg = _fill(NewEngineDialog(), name="h")
        try:
            dlg.type_combo.setCurrentIndex(1)
            qapp.processEvents()
            dlg._form._widgets["row_selector"].setText("table")
            dlg.image_edit.setText(str(image))
            dlg._test()
            text = dlg.test_output.toPlainText()
            assert "请求成功" in text
            assert "解析失败" in text          # 不是崩溃，是可读的错误
        finally:
            dlg.close()

    def test_requires_an_image(self, qapp, monkeypatch):
        informed = []
        monkeypatch.setattr(
            "imgsearch_gui.dialogs.new_engine_dialog.QtWidgets.QMessageBox.information",
            lambda *a, **k: informed.append(True))
        dlg = NewEngineDialog()
        try:
            dlg._test()
            assert informed, "没选图应当提示而不是发请求"
        finally:
            dlg.close()


class TestWizardReachable:
    def test_engines_page_has_button(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        try:
            texts = [b.text() for b in page.findChildren(qt_button())]
            assert "新建引擎…" in texts
        finally:
            page.close()


def qt_button():
    from PySide6 import QtWidgets
    return QtWidgets.QPushButton
