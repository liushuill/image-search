"""
图库页 / 清理页测试

不止验证「能构造」，而是把**真正会写数据库的路径**走通：
添加路径、移除路径并清理数据、预演、执行清理并核对 VACUUM 后的真实回收量。

Qt 的模态对话框（QMessageBox / QFileDialog）会阻塞测试，所以按需打桩。
"""

import os

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from imgsearch.engines.base import SearchResult  # noqa: E402
from imgsearch.library import LibraryDB, LibraryStore, RootManager  # noqa: E402
from imgsearch.library import thumbs  # noqa: E402


# ── 打桩辅助 ────────────────────────────────────


@pytest.fixture
def no_dialogs(monkeypatch):
    """
    把模态弹窗打桩掉，并记录它们说了什么。

    Returns:
        {"information": [...], "warning": [...], "question": "yes"}
    """
    calls = {"information": [], "warning": [], "critical": []}

    monkeypatch.setattr(QtWidgets.QMessageBox, "information",
                        lambda *a, **k: calls["information"].append(a[2] if len(a) > 2 else ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *a, **k: calls["warning"].append(a[2] if len(a) > 2 else ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical",
                        lambda *a, **k: calls["critical"].append(a[2] if len(a) > 2 else ""))
    # 确认框一律「是」
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec",
                        lambda self: QtWidgets.QMessageBox.Yes)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        lambda *a, **k: QtWidgets.QMessageBox.Yes)
    return calls


@pytest.fixture
def seeded(library, pattern_image, tmp_path):
    """
    造一个已登记根路径、且里面有图有结果的图库。

    Returns:
        (根路径, [ImageRecord, ...])
    """
    db, store = library
    root_dir = tmp_path / "库A"
    root_dir.mkdir()
    root = RootManager(db).add(str(root_dir), label="库A")

    recs = []
    for i in range(3):
        img = pattern_image(root_dir / f"p{i}.png", seed=700 + i)
        rec = store.upsert_image(str(img))
        store.save_results(rec.id, [SearchResult(source="t", similarity=90.0,
                                                pixiv_id=str(3000 + i))])
        thumbs.ensure(rec.dhash, str(img))
        recs.append(rec)
    return root, recs


# ── 图库页：移除路径时的清理询问 ────────────────


class TestRemovePathDialog:
    """删路径时是否清理持久化数据 —— 需求里的第 3 条"""

    def test_defaults_to_keep_everything(self, qapp, seeded):
        from imgsearch_gui.pages.library_page import RemovePathDialog
        root, recs = seeded
        with LibraryDB() as db:
            store = LibraryStore(db)
            dlg = RemovePathDialog(db, store, root)
            try:
                # 默认应是「仅移除登记」——破坏性选项绝不能是默认
                assert dlg.purge_mode == "none"
                assert "保留" in dlg.preview.text()
            finally:
                dlg.close()

    def test_preview_shows_counts_per_mode(self, qapp, seeded):
        from imgsearch_gui.pages.library_page import RemovePathDialog
        root, recs = seeded
        with LibraryDB() as db:
            store = LibraryStore(db)
            dlg = RemovePathDialog(db, store, root)
            try:
                for mode, box in dlg._radios:
                    box.setChecked(True)
                    assert dlg.purge_mode == mode
                    text = dlg.preview.text()
                    if mode == "results":
                        assert "搜索结果" in text and "3" in text
                    elif mode == "all":
                        assert "图片记录" in text and "3" in text
                    elif mode == "thumbs":
                        assert "缩略图" in text
            finally:
                dlg.close()


class TestLibraryPage:
    def test_empty_state_message(self, qapp):
        from imgsearch_gui.pages.library_page import LibraryPage
        page = LibraryPage()
        assert page.table.rowCount() == 0
        assert "尚未登记" in page.summary.text()

    def test_lists_roots_with_counts(self, qapp, seeded):
        from imgsearch_gui.pages.library_page import LibraryPage
        root, recs = seeded
        page = LibraryPage()
        assert page.table.rowCount() == 1
        assert page.table.item(0, 1).text() == "库A"
        assert page.table.item(0, 3).text() == "3"      # 图片
        assert page.table.item(0, 4).text() == "3"      # 已搜
        assert page.table.item(0, 5).text() == "3"      # 结果
        assert page.table.item(0, 6).text() == "3"      # 缩略图
        assert "共 1 条路径" in page.summary.text()

    def test_missing_path_is_flagged_not_deleted(self, qapp, seeded, tmp_path):
        """路径失效只标记、证据保留 —— 不能默默删数据"""
        import shutil
        from imgsearch_gui.pages.library_page import LibraryPage
        root, recs = seeded
        shutil.rmtree(root.path)                        # 模拟目录被搬走

        page = LibraryPage()
        assert "路径不存在" in page.table.item(0, 0).text()
        # 记录还在
        with LibraryDB() as db:
            assert LibraryStore(db).count_images() == 3

    def test_buttons_disabled_without_selection(self, qapp, seeded):
        from imgsearch_gui.pages.library_page import LibraryPage
        page = LibraryPage()
        page.table.clearSelection()
        page._update_buttons()
        assert page.btn_remove.isEnabled() is False
        page.table.selectRow(0)
        page._update_buttons()
        assert page.btn_remove.isEnabled() is True

    def test_add_rejects_nested_path(self, qapp, seeded, monkeypatch, no_dialogs, tmp_path):
        """嵌套会让同一张图被记两次，必须在添加时就拒绝并说明原因"""
        from imgsearch_gui.pages import library_page as mod
        root, recs = seeded
        child = tmp_path / "库A" / "子目录"
        child.mkdir()

        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(child)))
        monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("", True)))

        page = mod.LibraryPage()
        page._add()
        assert no_dialogs["warning"], "嵌套路径应弹出提示"
        assert "重叠" in no_dialogs["warning"][0]
        with LibraryDB() as db:
            assert len(RootManager(db).list()) == 1, "冲突的路径不该被登记"

    def test_add_accepts_valid_path(self, qapp, monkeypatch, no_dialogs, tmp_path):
        from imgsearch_gui.pages import library_page as mod
        fresh = tmp_path / "新库"
        fresh.mkdir()
        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(fresh)))
        monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("新库别名", True)))

        page = mod.LibraryPage()
        page._add()
        assert page.table.rowCount() == 1
        assert page.table.item(0, 1).text() == "新库别名"

    def test_remove_with_purge_all_clears_data(self, qapp, seeded, monkeypatch,
                                               no_dialogs):
        """移除路径 + 清空全部数据：记录/结果/缩略图都应清干净"""
        from imgsearch_gui.pages import library_page as mod
        root, recs = seeded

        # 让移除对话框直接返回「清空全部数据」
        monkeypatch.setattr(mod.RemovePathDialog, "exec",
                            lambda self: QtWidgets.QDialog.Accepted)
        monkeypatch.setattr(mod.RemovePathDialog, "purge_mode",
                            property(lambda self: "all"))

        page = mod.LibraryPage()
        page.table.selectRow(0)
        page._remove()

        assert page.table.rowCount() == 0
        with LibraryDB() as db:
            store = LibraryStore(db)
            assert store.count_images() == 0
            assert store.count_results() == 0
            assert RootManager(db).list() == []
        assert thumbs.stats()["count"] == 0
        assert no_dialogs["information"], "应报告清理结果"

    def test_remove_keeping_data_works(self, qapp, seeded, monkeypatch, no_dialogs):
        from imgsearch_gui.pages import library_page as mod
        root, recs = seeded
        monkeypatch.setattr(mod.RemovePathDialog, "exec",
                            lambda self: QtWidgets.QDialog.Accepted)
        monkeypatch.setattr(mod.RemovePathDialog, "purge_mode",
                            property(lambda self: "none"))

        page = mod.LibraryPage()
        page.table.selectRow(0)
        page._remove()

        with LibraryDB() as db:
            assert len(RootManager(db).list()) == 0
            assert LibraryStore(db).count_images() == 3, "选了「保留」就不该删数据"
        assert thumbs.stats()["count"] == 3

    def test_cancelled_removal_changes_nothing(self, qapp, seeded, monkeypatch, no_dialogs):
        from imgsearch_gui.pages import library_page as mod
        root, recs = seeded
        monkeypatch.setattr(mod.RemovePathDialog, "exec",
                            lambda self: QtWidgets.QDialog.Rejected)

        page = mod.LibraryPage()
        page.table.selectRow(0)
        page._remove()
        with LibraryDB() as db:
            assert len(RootManager(db).list()) == 1
            assert LibraryStore(db).count_images() == 3

    def test_relocate_rewrites_records(self, qapp, seeded, monkeypatch, no_dialogs, tmp_path):
        from imgsearch_gui.pages import library_page as mod
        root, recs = seeded
        moved = tmp_path / "搬走的库"
        moved.mkdir()
        for f in (tmp_path / "库A").iterdir():
            f.rename(moved / f.name)

        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(moved)))
        page = mod.LibraryPage()
        page.table.selectRow(0)
        page._relocate()

        with LibraryDB() as db:
            store = LibraryStore(db)
            r = RootManager(db).get(root.id)
            assert r.path == os.path.realpath(str(moved))
            rec = store.get_image(recs[0].id)
            assert rec.abs_path.startswith(os.path.realpath(str(moved)))
        assert no_dialogs["information"]


# ── 清理页 ──────────────────────────────────────


class TestCleanupPage:
    def test_cards_reflect_real_usage(self, qapp, seeded):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        assert "KB" in page.card_db.value_label.text() or "B" in page.card_db.value_label.text()
        assert "3 个" in page.card_thumbs.value_label.text()
        assert page.path_combo.count() == 1
        assert page.table.rowCount() == 1

    def test_run_disabled_until_preview(self, qapp, seeded):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        assert page.btn_run.isEnabled() is False, "没预演就不该能执行"
        page.cb_results.setChecked(True)
        assert page.btn_run.isEnabled() is False
        page._plan()
        assert page.btn_run.isEnabled() is True

    def test_changing_scope_invalidates_preview(self, qapp, seeded):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        page.cb_results.setChecked(True)
        page._plan()
        assert page.btn_run.isEnabled() is True
        # 改范围后必须重新预演
        page.cb_thumbs.setChecked(True)
        assert page.btn_run.isEnabled() is False

    def test_empty_selection_explains_itself(self, qapp, seeded):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        page._plan()
        assert "至少勾选一项" in page.preview.toPlainText()
        assert page.btn_run.isEnabled() is False

    def test_plan_does_not_touch_data(self, qapp, seeded):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        page.cb_results.setChecked(True)
        page._plan()
        with LibraryDB() as db:
            assert LibraryStore(db).count_results() == 3, "预演不该改数据"
        assert "预演" in page.preview.toPlainText()

    def test_execute_results_only_keeps_records(self, qapp, seeded, no_dialogs):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        page.cb_results.setChecked(True)
        page._plan()
        page._run()

        with LibraryDB() as db:
            store = LibraryStore(db)
            assert store.count_results() == 0
            assert store.count_images() == 3, "只清结果时图片记录必须保留"
            # dHash 索引仍在：还能认出「这张搜过了」
            assert store.lookup(store.get_image(1).abs_path) is not None
        assert "清理结果" in page.preview.toPlainText()

    def test_execute_images_scope_reports_real_reclaim(self, qapp, seeded, no_dialogs):
        """
        关键回归：报告里的「回收」必须是磁盘实测值。

        SQLite 的 DELETE 不缩小文件；WAL 模式下 VACUUM 的产物又先落在 -wal。
        必须 checkpoint → VACUUM → checkpoint 才真的还回磁盘。
        """
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        page.cb_images.setChecked(True)          # 会连动勾上 results / thumbs
        assert page.cb_results.isChecked() and page.cb_thumbs.isChecked()
        page._plan()
        page._run()

        text = page.preview.toPlainText()
        assert "清理结果" in text
        assert "→" in text, "结果里应给出清理前后的体积对比"
        with LibraryDB() as db:
            store = LibraryStore(db)
            assert store.count_images() == 0
            assert store.count_results() == 0
        assert thumbs.stats()["count"] == 0

    def test_scope_limited_to_selected_path(self, qapp, library, pattern_image,
                                            tmp_path, no_dialogs):
        """按路径清理不能误伤别的路径"""
        db, store = library
        roots = RootManager(db)
        a = tmp_path / "库A"
        b = tmp_path / "库B"
        a.mkdir()
        b.mkdir()
        ra = roots.add(str(a))
        rb = roots.add(str(b))
        for i in range(2):
            img = pattern_image(a / f"a{i}.png", seed=800 + i)
            rec = store.upsert_image(str(img))
            store.save_results(rec.id, [SearchResult(source="t", similarity=90.0)])
        for i in range(3):
            img = pattern_image(b / f"b{i}.png", seed=900 + i)
            rec = store.upsert_image(str(img))
            store.save_results(rec.id, [SearchResult(source="t", similarity=90.0)])

        from imgsearch_gui.pages.cleanup_page import CleanupPage
        page = CleanupPage()
        idx = page.path_combo.findData(ra.id)
        assert idx >= 0
        page.path_combo.setCurrentIndex(idx)
        page.rb_pick.setChecked(True)
        page.cb_images.setChecked(True)
        page._plan()
        page._run()

        with LibraryDB() as db2:
            st = LibraryStore(db2)
            assert st.count_images(root_id=ra.id) == 0
            assert st.count_images(root_id=rb.id) == 3, "另一条路径被误删了"

    def test_orphan_thumbs_cleanup(self, qapp, seeded, no_dialogs):
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        root, recs = seeded
        # 直接删掉一条记录，缩略图就成了孤儿
        with LibraryDB() as db:
            with db.transaction():
                db.conn.execute("DELETE FROM images WHERE id = ?", (recs[0].id,))
        page = CleanupPage()
        assert "1 个" in page.card_orphan.value_label.text()

        page._clean_orphans()
        assert "删除 1 个" in page.preview.toPlainText()
        assert thumbs.stats()["count"] == 2

    def test_cancelled_execution_keeps_data(self, qapp, seeded, monkeypatch):
        from imgsearch_gui.pages import cleanup_page as mod
        page = mod.CleanupPage()
        page.cb_results.setChecked(True)
        page._plan()

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec",
                            lambda self: QtWidgets.QMessageBox.No)
        page._run()
        with LibraryDB() as db:
            assert LibraryStore(db).count_results() == 3, "取消后数据应原样保留"

    def test_unattributed_records_are_shown(self, qapp, pattern_image, library):
        """登记路径之前搜索过的图片不属于任何路径，必须显式呈现"""
        from imgsearch_gui.pages.cleanup_page import CleanupPage
        db, store = library
        img = pattern_image("孤图.png", seed=999)
        store.upsert_image(str(img))            # 未登记任何根路径

        page = CleanupPage()
        rows = page.table.rowCount()
        assert rows == 1
        assert "未归属" in page.table.item(0, 2).text()
