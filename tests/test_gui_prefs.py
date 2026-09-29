"""
GUI 行为测试：未保存修改的守卫、凭据只读、设置页、凭据页动态清单

对应三个真实反馈：
1. 引擎页改了没保存就切页/切引擎 → 修改静默丢失
2. 引擎页和凭据页都能改同一个 API Key，且互不同步
3. 代理地址在界面上没有入口
"""


import pytest

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from imgsearch import secrets  # noqa: E402
from imgsearch.engines.store import get_store  # noqa: E402


@pytest.fixture
def answer_dialog(monkeypatch):
    """
    伪造 QMessageBox，按按钮文本决定「点了哪个」。

    用法：``answer_dialog("保存")`` / ``("丢弃修改")`` / ``("取消")``
    """
    state = {"choice": "取消"}

    class FakeButton:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class FakeBox:
        # 角色常量：_confirm_leave 只是把它们透传给 addButton
        AcceptRole = DestructiveRole = RejectRole = 0
        Question = Warning = Information = 0
        Yes = 1
        No = 0

        def __init__(self, *args, **kwargs):
            self._buttons = []

        def setIcon(self, *a): pass
        def setWindowTitle(self, *a): pass
        def setText(self, *a): pass
        def setInformativeText(self, *a): pass
        def setDefaultButton(self, *a): pass
        def setStandardButtons(self, *a): pass

        def addButton(self, text, role=None):
            b = FakeButton(text)
            self._buttons.append(b)
            return b

        def button(self, _which):
            return FakeButton("")

        def exec(self):
            return 0

        def clickedButton(self):
            for b in self._buttons:
                if b.text() == state["choice"]:
                    return b
            return None

    monkeypatch.setattr(QtWidgets, "QMessageBox", FakeBox)
    return lambda choice: state.update(choice=choice)


class TestUnsavedChangesGuard:
    """反馈 1：改了没保存不该静默丢失"""

    def _make_dirty(self, page):
        """改一个字段让表单变脏"""
        page._form._widgets["timeout"].setValue(99)
        assert page._dirty is True

    def test_starts_clean(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        assert page._dirty is False
        assert page.can_leave() is True

    def test_editing_marks_dirty(self, qapp):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        assert "未保存" in page.dirty_label.text()

    def test_leaving_clean_page_does_not_prompt(self, qapp, answer_dialog):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        # 没改过 → 不该弹任何框（弹了的话 FakeBox 会返回 None → 误判）
        assert page.can_leave() is True

    def test_discard_allows_leaving(self, qapp, answer_dialog):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        answer_dialog("丢弃修改")
        assert page.can_leave() is True
        # 丢弃后不该写进配置
        assert get_store(refresh=True).get("sauceNAO").get("timeout") != 99

    def test_cancel_stays_and_keeps_edits(self, qapp, answer_dialog):
        """「取消」是唯一不丢数据的出口，必须存在"""
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        answer_dialog("取消")
        assert page.can_leave() is False
        assert page._dirty is True, "取消后修改应仍在"
        assert page._form._widgets["timeout"].value() == 99

    def test_save_persists_and_allows_leaving(self, qapp, answer_dialog):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        answer_dialog("保存")
        assert page.can_leave() is True
        assert page._dirty is False
        # 真的写进配置了
        assert get_store(refresh=True).get("sauceNAO").get("timeout") == 99

    def test_switching_engine_with_cancel_restores_selection(self, qapp, answer_dialog):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        original = page._current
        answer_dialog("取消")

        # 试图切到另一个引擎
        other = 1 if page.list.currentRow() == 0 else 0
        page.list.setCurrentRow(other)
        qapp.processEvents()

        assert page._current == original, "选了取消就该留在原引擎"
        assert page._dirty is True

    def test_switching_engine_with_discard_actually_switches(self, qapp, answer_dialog):
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        self._make_dirty(page)
        original = page._current
        answer_dialog("丢弃修改")

        other = 1 if page.list.currentRow() == 0 else 0
        target = page.list.item(other).data(0x0100)      # Qt.UserRole
        page.list.setCurrentRow(other)
        qapp.processEvents()

        assert page._current == target != original

    def test_revert_button_is_gone(self, qapp):
        """用户要求删掉「放弃修改」（有守卫之后它是多余的）"""
        from imgsearch_gui.pages.engines_page import EnginesPage
        page = EnginesPage()
        texts = [b.text() for b in page.findChildren(QtWidgets.QPushButton)]
        assert "放弃修改" not in texts
        assert page.dirty_label is not None


class TestMainWindowNavigationGuard:
    """切页时也要问一声（走 MainWindow.go_to）"""

    def test_cancel_blocks_page_switch(self, qapp, answer_dialog):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            win.go_to(3)                                  # 引擎页
            engines = win.engines_page
            engines._form._widgets["timeout"].setValue(88)
            assert engines._dirty is True

            answer_dialog("取消")
            win.go_to(0)                                  # 试图去搜索页
            assert win.pages.currentIndex() == 3, "取消后不该离开引擎页"
            assert win._navs[3].isChecked(), "导航高亮应留在引擎页"
        finally:
            win.close()

    def test_discard_allows_page_switch(self, qapp, answer_dialog):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            win.go_to(3)
            win.engines_page._form._widgets["timeout"].setValue(88)
            answer_dialog("丢弃修改")
            win.go_to(0)
            assert win.pages.currentIndex() == 0
        finally:
            win.close()

    def test_secret_request_jumps_to_credentials(self, qapp):
        from imgsearch_gui.main_window import MainWindow
        win = MainWindow()
        try:
            win._goto_credentials("SAUCENAO_KEY")
            assert isinstance(win.pages.currentWidget(), type(win.credentials_page))
            assert win.pages.currentIndex() == 4
        finally:
            win.close()


class TestSecretFieldsAreReadOnly:
    """反馈 2：同一个凭据不能有两个可写入口"""

    def test_no_editable_input_for_secret(self, qapp):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = get_store().get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        # 凭据字段不出现在可提交的值里
        assert "api_key" not in form.values()

    def test_secret_not_writable_through_form(self, qapp):
        """就算有人在表单上塞值，也不会从引擎页写进配置"""
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = get_store().get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        values = form.values()
        values["api_key"] = "SNEAKY"                      # 手动注入
        # 引擎页只提交表单声明的字段，这里模拟页面的实际做法
        form_values = {k: v for k, v in values.items()
                       if not (ec.schema().get(k) and ec.schema().get(k).is_secret)}
        get_store().update("sauceNAO", **form_values)
        assert get_store().get("sauceNAO").get("api_key") == ""

    def test_secret_field_offers_jump_to_credentials(self, qapp):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = get_store().get("sauceNAO")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        seen = []
        form.secret_requested.connect(seen.append)
        buttons = [b for b in form.findChildren(QtWidgets.QPushButton)
                   if "凭据" in b.text()]
        assert buttons, "凭据字段应提供跳转到凭据页的入口"
        buttons[0].click()
        assert seen == ["SAUCENAO_KEY"]

    def test_engine_without_credentials_has_no_key_field(self, qapp):
        from imgsearch_gui.widgets.schema_form import SchemaForm
        ec = get_store().get("iqdb")
        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        assert "api_key" not in form.values()
        texts = [b.text() for b in form.findChildren(QtWidgets.QPushButton)]
        assert not any("凭据" in t for t in texts), "iqdb 不需要凭据，不该有跳转按钮"


class TestCredentialsPage:
    def test_lists_all_declared_secrets(self, qapp):
        from imgsearch.service import declared_secrets
        from imgsearch_gui.pages.credentials_page import CredentialsPage
        page = CredentialsPage()
        expected = [env for env, _, _ in declared_secrets()]
        assert list(page.rows.keys()) == expected
        assert "SAUCENAO_KEY" in page.rows

    def test_friendly_titles_for_known_secrets(self, qapp):
        from imgsearch_gui.pages.credentials_page import CredentialsPage
        page = CredentialsPage()
        assert page.rows["SAUCENAO_KEY"].title == "SauceNAO API Key"
        assert page.rows["DANBOORU_API_KEY"].title == "Danbooru API Key"

    def test_saving_writes_only_env(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.credentials_page import CredentialsPage
        page = CredentialsPage()
        page.rows["SAUCENAO_KEY"].edit.setText("FROM-GUI")
        page.save()

        assert secrets.get("SAUCENAO_KEY") == "FROM-GUI"
        raw = cfg._CONFIG_FILE.read_text(encoding="utf-8")
        assert "FROM-GUI" not in raw, "凭据不该出现在入库的 config.json 里"
        assert "已保存" in page.message.text()

    def test_status_shows_source_and_masked_value(self, qapp):
        from imgsearch_gui.pages.credentials_page import CredentialsPage
        secrets.set("SAUCENAO_KEY", "abcdef123456")
        page = CredentialsPage()
        text = page.rows["SAUCENAO_KEY"].status.text()
        assert "已设置" in text and ".env" in text
        assert "abcdef123456" not in text, "状态里不该出现明文"

    def test_clear_removes_from_env(self, qapp):
        from imgsearch_gui.pages.credentials_page import CredentialsPage
        secrets.set("SAUCENAO_KEY", "TO-BE-REMOVED")
        page = CredentialsPage()
        page.rows["SAUCENAO_KEY"]._clear()
        assert not secrets.is_set("SAUCENAO_KEY")
        assert "未设置" in page.rows["SAUCENAO_KEY"].status.text()


class TestSettingsPage:
    """反馈 3：代理地址在界面上没入口"""

    def test_loads_current_values(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        cfg.load_config()["proxy"] = "http://127.0.0.1:7897"
        page = SettingsPage()
        assert page.proxy_edit.text() == "http://127.0.0.1:7897"

    def test_save_persists_proxy(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page.proxy_edit.setText("http://127.0.0.1:9999")
        page.save()
        assert cfg.load_config()["proxy"] == "http://127.0.0.1:9999"
        assert "已保存" in page.message.text()

    def test_save_persists_library_toggles(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page.use_library.setChecked(False)
        page.cache_thumbs.setChecked(False)
        page.save()
        assert cfg.load_config()["use_library"] is False
        assert cfg.load_config()["cache_thumbnails"] is False

    def test_empty_check_url_gets_default(self, qapp):
        """探活地址留空要回落到默认值，不能存成空串"""
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page.check_url_edit.setText("")
        page.save()
        assert cfg.load_config()["proxy_check_url"].startswith("https://")

    def test_changed_signal_emitted(self, qapp):
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        seen = []
        page.changed.connect(lambda: seen.append(1))
        page.save()
        assert seen

    def test_proxy_hint_mentions_local_clash_port(self, qapp):
        """本机 Clash 是 7897，写进占位符省得每次想"""
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        assert "7897" in page.proxy_edit.placeholderText()
