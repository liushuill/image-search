"""
批量识别界面测试（offscreen）

对应的核心行为在 tests/test_batch.py；这里只管界面这一层：
预览（零消耗）、选项联动、以及与设置的读写。
"""

import pytest

pytest.importorskip("PySide6")



def make_images(directory, count):
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (directory / f"{i:03d}.jpg").write_bytes(b"\xff\xd8\xff")
    return directory


class TestBatchDialogPreview:
    def test_shows_counts_and_quota(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 5)
        dlg = BatchDialog(str(tmp_path))
        try:
            text = dlg.plan_label.text()
            assert "5" in text
            assert "配额" in text or "SauceNAO" in text
            assert dlg.start_btn.isEnabled() is True
        finally:
            dlg.close()

    def test_preview_uses_html_not_markdown(self, qapp, tmp_path):
        """QLabel 不渲染 **粗体**，会原样显示星号"""
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 3)
        dlg = BatchDialog(str(tmp_path))
        try:
            assert "**" not in dlg.plan_label.text()
            assert "<b>" in dlg.plan_label.text()
        finally:
            dlg.close()

    def test_empty_directory_disables_start(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        tmp_path.mkdir(exist_ok=True)
        dlg = BatchDialog(str(tmp_path))
        try:
            assert dlg.start_btn.isEnabled() is False
            assert "没有图片" in dlg.plan_label.text()
        finally:
            dlg.close()

    def test_missing_directory_disables_start(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        dlg = BatchDialog(str(tmp_path / "不存在"))
        try:
            assert dlg.start_btn.isEnabled() is False
            assert "❌" in dlg.plan_label.text()
        finally:
            dlg.close()

    def test_limit_changes_plan(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 8)
        dlg = BatchDialog(str(tmp_path))
        try:
            dlg.limit.setValue(3)
            dlg.refresh_plan()
            assert "3" in dlg.plan_label.text()
        finally:
            dlg.close()

    def test_recursive_toggle_affects_count(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 2)
        make_images(tmp_path / "子目录", 3)
        dlg = BatchDialog(str(tmp_path))
        try:
            dlg.recursive.setChecked(True)
            dlg.refresh_plan()
            assert "5" in dlg.plan_label.text()

            dlg.recursive.setChecked(False)
            dlg.refresh_plan()
            assert "2" in dlg.plan_label.text()
        finally:
            dlg.close()

    def test_limit_zero_means_unlimited(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 4)
        dlg = BatchDialog(str(tmp_path))
        try:
            dlg.limit.setValue(0)          # 0 = 不限
            dlg.refresh_plan()
            assert dlg.start_btn.isEnabled() is True
            assert "本次计划" not in dlg.plan_label.text()   # 全都要处理
        finally:
            dlg.close()

    def test_policy_defaults_from_config(self, qapp, tmp_path):
        import imgsearch.config as cfg
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 1)
        cfg.load_config()["batch_quota_policy"] = "fallback"
        dlg = BatchDialog(str(tmp_path))
        try:
            assert dlg.policy.currentData() == "fallback"
        finally:
            dlg.close()

    def test_saucenao_pace_is_explained(self, qapp, tmp_path):
        """用户要能看见「为什么会慢」，否则会以为卡住了"""
        from PySide6 import QtWidgets
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        make_images(tmp_path, 1)
        dlg = BatchDialog(str(tmp_path))
        try:
            labels = " ".join(w.text() for w in dlg.findChildren(QtWidgets.QLabel))
            assert "节流" in labels
        finally:
            dlg.close()


class TestBatchDialogCancel:
    def test_reject_while_running_requests_stop(self, qapp, tmp_path, monkeypatch):
        """正在跑时关窗不该直接把线程丢下"""
        from imgsearch_gui.dialogs import batch_dialog as mod
        make_images(tmp_path, 2)
        dlg = mod.BatchDialog(str(tmp_path))
        try:
            cancelled = {"n": 0}

            class FakeWorker:
                def cancel(self):
                    cancelled["n"] += 1

            dlg._worker = FakeWorker()
            dlg.reject()                     # 走 _cancel 分支而不是关闭
            assert cancelled["n"] == 1
            assert dlg.isVisible() is False or dlg._worker is not None
        finally:
            dlg._worker = None
            dlg.close()

    def test_cancel_marks_worker(self, qapp, tmp_path):
        from imgsearch_gui.workers import BatchWorker
        worker = BatchWorker(str(tmp_path))
        assert worker.cancelled is False
        worker.cancel()
        assert worker.cancelled is True


class TestSettingsBatchControls:
    def test_loads_saved_values(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        data = cfg.load_config()
        data["batch_quota_policy"] = "fallback"
        data["batch_limit"] = 7
        data["batch_recursive"] = False

        page = SettingsPage()
        assert page.batch_policy.currentData() == "fallback"
        assert page.batch_limit.value() == 7
        assert page.batch_recursive.isChecked() is False

    def test_defaults(self, qapp):
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        assert page.batch_policy.currentData() == "stop"
        assert page.batch_limit.value() == 20
        assert page.batch_recursive.isChecked() is True

    def test_save_persists(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page.batch_policy.setCurrentIndex(
            page.batch_policy.findData("fallback"))
        page.batch_limit.setValue(33)
        page.batch_recursive.setChecked(False)
        page.save()

        saved = cfg.load_config()
        assert saved["batch_quota_policy"] == "fallback"
        assert saved["batch_limit"] == 33
        assert saved["batch_recursive"] is False

    def test_zero_limit_means_unlimited_in_config(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page.batch_limit.setValue(0)
        page.save()
        assert cfg.load_config()["batch_limit"] == 0


class TestLibraryPageBatchEntry:
    def test_has_batch_button(self, qapp):
        from PySide6 import QtWidgets
        from imgsearch_gui.pages.library_page import LibraryPage
        page = LibraryPage()
        texts = [b.text() for b in page.findChildren(QtWidgets.QPushButton)]
        assert any("识别" in t for t in texts)

    def test_batch_without_selection_asks_for_directory(self, qapp, monkeypatch):
        """没选中已登记路径时，让用户挑一个目录"""
        from PySide6 import QtWidgets
        from imgsearch_gui.pages.library_page import LibraryPage
        import imgsearch_gui.dialogs.batch_dialog as batch_mod

        page = LibraryPage()
        called = {}

        class FakeDialog:
            """替身：真实对话框会 exec() 阻塞，测试里只记录参数"""

            def __init__(self, directory, parent=None):
                called["dir"] = directory

            def exec(self):
                called["exec"] = True
                return 0

        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                            lambda *a, **k: "/某目录")
        monkeypatch.setattr(batch_mod, "BatchDialog", FakeDialog)
        page._batch_search()
        assert called.get("dir") == "/某目录"
        assert called.get("exec") is True

    def test_batch_cancelled_when_no_directory_chosen(self, qapp, monkeypatch):
        from PySide6 import QtWidgets
        from imgsearch_gui.pages.library_page import LibraryPage
        import imgsearch_gui.dialogs.batch_dialog as batch_mod

        page = LibraryPage()
        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                            lambda *a, **k: "")
        monkeypatch.setattr(batch_mod, "BatchDialog",
                            lambda *a, **k: pytest.fail("不该打开对话框"))
        page._batch_search()      # 不抛即通过
