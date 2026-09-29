"""
导出对话框测试（offscreen）

覆盖：格式勾选项来自注册表、状态联动、记住上次选择、以及**真实跑一次导出**。
"""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore  # noqa: E402

from imgsearch.engines.base import SearchResult  # noqa: E402
from imgsearch.exporters import all_formats, format_keys, from_results  # noqa: E402


def records(n=2):
    return from_results(
        [SearchResult(source="sauceNAO", similarity=93.3, pixiv_id=str(1000 + i),
                      pixiv_page=i, artist=f"画师{i}", title=f"标题{i}",
                      ext_urls=[f"https://example.com/{i}"])
         for i in range(n)],
        file="/图库/a.png", dhash="deadbeefdeadbeef",
    )


class TestDialogConstruction:
    def test_checkboxes_come_from_registry(self, qapp):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            assert list(dlg._boxes) == format_keys()
            assert len(dlg._boxes) == len(all_formats())
        finally:
            dlg.close()

    def test_default_selection(self, qapp):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            assert dlg.selected_formats() == ["urls", "html", "csv"]
        finally:
            dlg.close()

    def test_shows_record_count(self, qapp):
        from PySide6 import QtWidgets
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records(5))
        try:
            texts = [w.text() for w in dlg.findChildren(QtWidgets.QLabel)]
            assert any("5 条记录" in t for t in texts)
        finally:
            dlg.close()

    def test_default_template_from_config(self, qapp):
        from imgsearch.exporters import DEFAULT_NAME_TEMPLATE
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            assert dlg.template_edit.text() == DEFAULT_NAME_TEMPLATE
        finally:
            dlg.close()


class TestStateWiring:
    def test_thumb_option_follows_html_checkbox(self, qapp):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            dlg._boxes["html"].setChecked(True)
            assert dlg.thumb_combo.isEnabled() is True
            dlg._boxes["html"].setChecked(False)
            assert dlg.thumb_combo.isEnabled() is False
        finally:
            dlg.close()

    def test_export_disabled_without_selection(self, qapp):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            for cb in dlg._boxes.values():
                cb.setChecked(False)
            assert dlg.export_btn.isEnabled() is False
            assert dlg.export_btn.toolTip()
            dlg._boxes["urls"].setChecked(True)
            assert dlg.export_btn.isEnabled() is True
        finally:
            dlg.close()

    def test_remembers_choices(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records())
        try:
            for cb in dlg._boxes.values():
                cb.setChecked(False)
            dlg._boxes["json"].setChecked(True)
            dlg.outdir_edit.setText("/tmp/某个目录")
            dlg.template_edit.setText("{artist}")
            dlg._remember()
        finally:
            dlg.close()

        saved = cfg.load_config()
        assert saved["export_formats"] == ["json"]
        assert saved["export_outdir"] == "/tmp/某个目录"
        assert saved["export_name_template"] == "{artist}"

    def test_restores_remembered_selection(self, qapp):
        import imgsearch.config as cfg
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        cfg.load_config()["export_formats"] = ["jsonl"]
        dlg = ExportDialog(records())
        try:
            assert dlg.selected_formats() == ["jsonl"]
        finally:
            dlg.close()


class TestRealExportThroughWorker:
    """真的跑一次导出，确认文件产出与剪贴板都到位"""

    def _run(self, qapp, dlg):
        from imgsearch_gui.workers import ExportWorker
        box = {}
        worker = ExportWorker(
            dlg.records, ",".join(dlg.selected_formats()),
            outdir=dlg.outdir_edit.text(), name_template="{pixiv_id}",
        )
        worker.done.connect(lambda w, c: box.update(written=w, clip=c))
        worker.failed.connect(lambda m: box.update(error=m))
        worker.finished.connect(qapp.quit)
        QtCore.QTimer.singleShot(20000, qapp.quit)
        worker.start()
        qapp.exec()
        return box

    def test_writes_files(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records(3))
        try:
            dlg.outdir_edit.setText(str(tmp_path))
            for cb in dlg._boxes.values():
                cb.setChecked(False)
            dlg._boxes["urls"].setChecked(True)
            dlg._boxes["csv"].setChecked(True)

            box = self._run(qapp, dlg)
            assert "error" not in box, box.get("error")
            written = [Path(p) for p in box["written"]]
            assert len(written) == 2
            assert all(p.is_file() for p in written)
            assert {p.suffix for p in written} == {".txt", ".csv"}
        finally:
            dlg.close()

    def test_clipboard_text_returned(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records(2))
        try:
            dlg.outdir_edit.setText(str(tmp_path))
            for cb in dlg._boxes.values():
                cb.setChecked(False)
            dlg._boxes["clipboard"].setChecked(True)

            box = self._run(qapp, dlg)
            assert "error" not in box, box.get("error")
            assert box["written"] == []              # 虚拟格式不落盘
            assert box["clip"].count("https://") >= 2
        finally:
            dlg.close()

    def test_html_report_written(self, qapp, tmp_path):
        from imgsearch_gui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(records(2))
        try:
            dlg.outdir_edit.setText(str(tmp_path))
            for cb in dlg._boxes.values():
                cb.setChecked(False)
            dlg._boxes["html"].setChecked(True)
            dlg.thumb_combo.setCurrentIndex(
                dlg.thumb_combo.findData("none"))

            box = self._run(qapp, dlg)
            assert "error" not in box, box.get("error")
            html = Path(box["written"][0]).read_text(encoding="utf-8")
            assert html.lstrip().startswith("<!DOCTYPE html>")
            assert "画师0" in html
        finally:
            dlg.close()

    def test_bad_format_reports_clearly(self, qapp, tmp_path):
        from imgsearch_gui.workers import ExportWorker
        box = {}
        worker = ExportWorker(records(1), "不存在的格式", outdir=str(tmp_path))
        worker.failed.connect(lambda m: box.update(error=m))
        worker.finished.connect(qapp.quit)
        QtCore.QTimer.singleShot(10000, qapp.quit)
        worker.start()
        qapp.exec()
        assert "未知导出格式" in box.get("error", "")


class TestPageIntegration:
    def test_search_page_export_button_follows_results(self, qapp):
        from imgsearch.service import SearchOutcome
        from imgsearch_gui.pages.search_page import SearchPage

        page = SearchPage()
        # 还没有结果 → 不能导出
        assert page.export_btn.isEnabled() is False

        page._on_done(SearchOutcome(
            results=[SearchResult(source="x", similarity=90.0)],
            dhash="abc",
        ))
        assert page.export_btn.isEnabled() is True
        assert page.copy_btn.isEnabled() is True

    def test_library_page_has_export_button(self, qapp):
        from PySide6 import QtWidgets
        from imgsearch_gui.pages.library_page import LibraryPage
        page = LibraryPage()
        texts = [b.text() for b in page.findChildren(QtWidgets.QPushButton)]
        assert any("导出" in t for t in texts)

    def test_library_export_empty_gives_hint(self, qapp, monkeypatch):
        from PySide6 import QtWidgets
        from imgsearch_gui.pages import library_page as mod
        told = []
        monkeypatch.setattr(QtWidgets.QMessageBox, "information",
                            lambda *a, **k: told.append(a[2] if len(a) > 2 else ""))
        page = mod.LibraryPage()
        page._export()
        assert told and "还没有任何搜索结果" in told[0]
