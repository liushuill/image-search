"""
布局回归：文字不能被裁掉

来源：Windows 实测发现「拖拽区首字被裁」（已修）。顺着查 Linux 上的同类问题，
发现三处，这里各留一条回归测试：

1. **批量识别对话框** —— 内容总高约 1040px，1080p 屏幕上可用区也就 1040，
   卡在临界点；再小一点的屏幕（1366×768）会把日志区压成一行。
2. **搜索页的引擎下拉** —— 「自动（按权重依次尝试）」被压窄 9px，末尾的字被切。
3. **结果表的列头** —— 两个 Stretch 列会被压到比列头还窄，
   列头被截成「题 / 作,」这种。

另外补一条：退出时必须停掉缩略图线程，否则 QThread 被销毁时进程 abort。
"""

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets          # noqa: E402


@pytest.fixture
def clean_store(store):
    """确保引擎列表可预测（默认 5 个内置引擎）"""
    return store


class TestBatchDialogLayout:
    def _make(self, tmp_path):
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog
        return BatchDialog(str(tmp_path))

    def test_content_is_scrollable(self, tmp_path, qapp):
        """内容必须能滚动 —— 否则小屏幕上只能压扁某个控件"""
        dlg = self._make(tmp_path)
        try:
            scrolls = dlg.findChildren(QtWidgets.QScrollArea)
            assert scrolls, "批量对话框应当有滚动区"
            assert any(s.widget() is not None for s in scrolls)
        finally:
            dlg.close()

    def test_default_size_fits_screen(self, tmp_path, qapp):
        """开窗尺寸不得超过屏幕可用区的 92%"""
        dlg = self._make(tmp_path)
        try:
            screen = qapp.primaryScreen()
            if screen is None:
                pytest.skip("没有屏幕信息")
            avail = screen.availableGeometry()
            assert dlg.height() <= int(avail.height() * 0.92) + 2
            assert dlg.width() <= int(avail.width() * 0.92) + 2
        finally:
            dlg.close()

    def test_log_keeps_its_minimum_height(self, tmp_path, qapp):
        """
        日志区曾经被压到 30px（只显示最顶上一行）——
        它的 minimumHeight 是 140，必须真的给到。
        """
        dlg = self._make(tmp_path)
        try:
            dlg.show()
            for _ in range(5):
                qapp.processEvents()
            assert dlg.log.height() >= 140, f"日志区只有 {dlg.log.height()}px"
        finally:
            dlg.close()


class TestSearchPageCombo:
    def test_combo_does_not_overflow_its_card(self, qapp, store):
        """
        组合框要**跟随栏宽**，不能为了不裁字把自己撑宽。

        走过的弯路：按最长引擎名给组合框设 minimumWidth（339px），
        比左栏（252px）还宽 → 溢出卡片、边框被压没，看起来像布局坏了。
        """
        from imgsearch_gui.pages.search_page import SearchPage
        page = SearchPage()
        try:
            combo = page.engine_combo
            card = combo.parent()
            assert combo.width() <= card.width(), (
                f"下拉 {combo.width()}px 溢出卡片 {card.width()}px")
            assert combo.minimumWidth() <= 64, "不该靠最小宽度撑开"
        finally:
            page.close()

    def test_popup_is_wide_enough_for_longest_name(self, qapp, store):
        """完整名字由**弹出列表**负责显示，组合框里可以被省略"""
        from imgsearch_gui.pages.search_page import SearchPage
        page = SearchPage()
        try:
            combo = page.engine_combo
            fm = combo.fontMetrics()
            need = max(fm.horizontalAdvance(combo.itemText(i))
                       for i in range(combo.count()))
            assert combo.view().minimumWidth() >= need
        finally:
            page.close()

    def test_tooltip_shows_full_current_text(self, qapp, store):
        """组合框里的文字可能被省略号截断，tooltip 要能看全"""
        from imgsearch_gui.pages.search_page import SearchPage
        page = SearchPage()
        try:
            combo = page.engine_combo
            assert combo.toolTip() == combo.currentText()
        finally:
            page.close()


class TestResultTableHeader:
    def test_sections_never_narrower_than_header_text(self, qapp, store):
        from imgsearch_gui.widgets.result_table import ResultTable
        table = ResultTable()
        try:
            header = table.horizontalHeader()
            model = table.model()
            fm = header.fontMetrics()
            longest = max(
                fm.horizontalAdvance(str(model.headerData(
                    c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) or ""))
                for c in range(model.columnCount()))
            assert header.minimumSectionSize() >= longest
        finally:
            table.close()

    def test_every_text_cell_has_tooltip(self, qapp, store):
        """单元格被省略号截断时，悬停要能看到全文"""
        from imgsearch.engines.base import SearchResult
        from imgsearch_gui.widgets.result_table import (
            COL_ARTIST, COL_ENGINE, COL_IDS, COL_PIXIV, ResultTable)

        table = ResultTable()
        try:
            table.set_results([SearchResult(
                source="SauceNAO（Pixiv 覆盖最好）", similarity=95.0,
                pixiv_id="74267012", artist="某画师", danbooru_id="3920114",
                ext_urls=["https://www.pixiv.net/artworks/74267012"])])
            for col in (COL_ENGINE, COL_PIXIV, COL_ARTIST, COL_IDS):
                item = table.item(0, col)
                if item and item.text():
                    assert item.toolTip(), f"第 {col} 列没有 tooltip"
        finally:
            table.close()


class TestQuitCleanup:
    def test_about_to_quit_stops_thumbnail_threads(self, qapp, monkeypatch):
        """
        退出时必须停掉缩略图线程。

        以前 stop_all_loaders 只在测试收尾里手动调用，真实运行时没人接 ——
        关窗口时正好在加载缩略图，进程会 abort（exit 134）。
        """
        import imgsearch_gui.app as app_mod
        import imgsearch_gui.widgets.thumbnails as thumbs

        called = []
        monkeypatch.setattr(thumbs, "stop_all_loaders", lambda: called.append(1))
        app_mod.wire_quit_cleanup(qapp)
        qapp.aboutToQuit.emit()
        assert called, "aboutToQuit 应当触发 stop_all_loaders"
