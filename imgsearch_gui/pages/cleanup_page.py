"""
清理页

两个维度自由组合：

  按**路径**：全部路径 / 指定某一条
  按**类别**：搜索结果记录 / 缓存缩略图 / 图片记录（连结果一起删）

外加「孤立缩略图」——数据库里已无对应记录、却还留在磁盘上的缓存。

⚠️ 关键：执行后显示的是 **VACUUM 之后真实回收的体积**。
SQLite 的 DELETE 只把页标记为可复用、文件不会缩小；WAL 模式下 VACUUM 的
产物又先落在 ``-wal`` 里 —— 不做 checkpoint 的话磁盘占用看起来不降反升。
所以这里先「预演」把要删什么、约多少算清楚，再从磁盘验证回收量。
"""

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.library import (
    LibraryDB,
    LibraryError,
    LibraryStore,
    PurgeOptions,
    RootManager,
    collect_stats,
    execute_purge,
    format_bytes,
    plan_purge,
    purge_orphan_thumbs,
)
from imgsearch_gui import style


class CleanupPage(QtWidgets.QWidget):
    """持久化数据的统计与清理"""

    changed = QtCore.Signal()

    HEADERS = ["id", "状态", "路径", "图片", "已搜", "结果", "缩略图", "缩略图占用"]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("清理")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch(1)
        refresh = QtWidgets.QPushButton("重新统计")
        refresh.clicked.connect(self.reload)
        head.addWidget(refresh)
        outer.addLayout(head)

        hint = QtWidgets.QLabel(
            "先「预演」看清要删什么，再执行。执行后会做 VACUUM 回收数据库文件空间，"
            "并报告**真实释放的体积**。图片原文件不会被删除 —— 只动本工具的持久化数据。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 总览卡片 ──
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(10)
        self.card_db = self._card("数据库文件")
        self.card_thumbs = self._card("缩略图缓存")
        self.card_total = self._card("合计占用")
        self.card_orphan = self._card("孤立缩略图")
        for c in (self.card_db, self.card_thumbs, self.card_total, self.card_orphan):
            cards.addWidget(c)
        outer.addLayout(cards)

        # ── 按路径明细 ──
        table_label = QtWidgets.QLabel("按路径明细")
        table_label.setObjectName("SectionTitle")
        outer.addWidget(table_label)

        self.table = QtWidgets.QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        for i in (0, 1, 3, 4, 5, 6, 7):
            h.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        outer.addWidget(self.table, 1)

        # ── 清理范围 ──
        scope = QtWidgets.QFrame()
        scope.setObjectName("Card")
        sl = QtWidgets.QVBoxLayout(scope)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(8)

        sl.addWidget(self._section("清理哪些路径"))
        self.rb_all = QtWidgets.QRadioButton("全部路径")
        self.rb_all.setChecked(True)
        self.rb_all.toggled.connect(self._invalidate)
        self.rb_pick = QtWidgets.QRadioButton("只清理选中的路径：")
        self.rb_pick.toggled.connect(self._invalidate)
        sl.addWidget(self.rb_all)

        pick = QtWidgets.QHBoxLayout()
        pick.addWidget(self.rb_pick)
        self.path_combo = QtWidgets.QComboBox()
        self.path_combo.setMinimumWidth(280)
        self.path_combo.currentIndexChanged.connect(self._invalidate)
        pick.addWidget(self.path_combo, 1)
        pick.addStretch(1)
        sl.addLayout(pick)

        sl.addWidget(self._section("清理什么"))
        self.cb_results = QtWidgets.QCheckBox("搜索结果记录")
        self.cb_results.toggled.connect(self._invalidate)
        self.cb_results.setToolTip(
            "删掉引擎返回的源地址/画师/相似度等元数据。"
            "dHash 索引会保留，所以「这张搜过了」依然能判断，只是要重新搜一次拿结果。"
        )
        sl.addWidget(self.cb_results)

        self.cb_thumbs = QtWidgets.QCheckBox("缓存缩略图")
        self.cb_thumbs.toggled.connect(self._invalidate)
        self.cb_thumbs.setToolTip("为预览与报告生成的图片副本，通常不影响功能。")
        sl.addWidget(self.cb_thumbs)

        self.cb_images = QtWidgets.QCheckBox("图片记录（会连同结果与缩略图一起删）")
        self.cb_images.setToolTip(
            "把图库里这些图片的记录整体抹掉。勾选它时前两项自动包含。"
            "这是「清空某条路径全部数据」的档位。"
        )
        self.cb_images.toggled.connect(self._on_images_toggled)
        sl.addWidget(self.cb_images)

        outer.addWidget(scope)

        # ── 操作条 ──
        bar = QtWidgets.QHBoxLayout()
        self.btn_orphans = QtWidgets.QPushButton("清理孤立缩略图")
        self.btn_orphans.setToolTip("数据库里已无对应记录、却还留在磁盘上的缓存")
        self.btn_orphans.clicked.connect(self._clean_orphans)
        bar.addWidget(self.btn_orphans)

        bar.addStretch(1)
        self.btn_plan = QtWidgets.QPushButton("预演")
        self.btn_plan.setToolTip("只统计不动手，看清要删什么")
        self.btn_plan.clicked.connect(self._plan)
        bar.addWidget(self.btn_plan)

        self.btn_run = QtWidgets.QPushButton("执行清理")
        self.btn_run.setObjectName("Primary")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        bar.addWidget(self.btn_run)
        outer.addLayout(bar)

        # ── 预演/结果面板 ──
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setObjectName("LogView")
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(132)
        outer.addWidget(self.preview)

        self._pending: PurgeOptions | None = None
        self.reload()

    # ── 小工具 ──────────────────────────────────

    @staticmethod
    def _section(text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    @staticmethod
    def _card(title: str) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(2)
        t = QtWidgets.QLabel(title)
        t.setObjectName("FieldHelp")
        v = QtWidgets.QLabel("—")
        v.setStyleSheet("font-size:17px; font-weight:600;")
        card.value_label = v          # type: ignore[attr-defined]
        lay.addWidget(t)
        lay.addWidget(v)
        return card

    def _with_library(self, fn):
        with LibraryDB() as db:
            return fn(db, LibraryStore(db))

    def _on_images_toggled(self, on: bool) -> None:
        if on:
            self.cb_results.setChecked(True)
            self.cb_thumbs.setChecked(True)
        self._invalidate()

    def _on_row_selected(self) -> None:
        rid = self._selected_root_id()
        if rid is not None:
            idx = self.path_combo.findData(rid)
            if idx >= 0:
                self.path_combo.setCurrentIndex(idx)
                self.rb_pick.setChecked(True)
        self._invalidate()

    def _selected_root_id(self):
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(QtCore.Qt.UserRole)

    def _invalidate(self, *_args) -> None:
        """
        范围变了，之前的预演作废，必须重新预演才能执行。

        ⚠️ 所有范围控件都要连到这里（复选框 / 单选 / 下拉）。
        只连一部分的话，界面显示的范围与实际执行的范围可能不一致 ——
        用户勾了 A、执行的是之前预演的 B。
        """
        self._pending = None
        self.btn_run.setEnabled(False)

    def showEvent(self, event) -> None:          # noqa: D102
        # 每次切到本页都重新统计：搜索页刚入库的图片能立刻反映出来
        super().showEvent(event)
        self.reload()

    # ── 数据 ────────────────────────────────────

    def reload(self) -> None:
        def build(db, store):
            return collect_stats(db, store), RootManager(db).list()

        stats, roots = self._with_library(build)

        self.card_db.value_label.setText(format_bytes(stats.db_bytes))
        self.card_thumbs.value_label.setText(
            f"{stats.thumbs_total} 个 · {format_bytes(stats.thumbs_bytes)}"
        )
        self.card_total.value_label.setText(format_bytes(stats.total_bytes))
        self.card_orphan.value_label.setText(
            f"{stats.orphan_thumbs} 个 · {format_bytes(stats.orphan_thumbs_bytes)}"
        )
        self.card_orphan.value_label.setStyleSheet(
            f"font-size:17px; font-weight:600;"
            f"color:{style.WARN if stats.orphan_thumbs else style.TEXT};"
        )

        # 路径下拉框（保留当前选择）
        keep = self.path_combo.currentData()
        self.path_combo.clear()
        for rs in stats.roots:
            mark = "" if rs.root.exists else "（路径不存在）"
            self.path_combo.addItem(f"#{rs.root.id} {rs.root.display}{mark}", rs.root.id)
        if keep is not None:
            idx = self.path_combo.findData(keep)
            if idx >= 0:
                self.path_combo.setCurrentIndex(idx)

        # 明细表
        self.table.setRowCount(0)
        for rs in stats.roots:
            i = self.table.rowCount()
            self.table.insertRow(i)

            id_item = QtWidgets.QTableWidgetItem(str(rs.root.id))
            id_item.setData(QtCore.Qt.UserRole, rs.root.id)
            self.table.setItem(i, 0, id_item)

            st = QtWidgets.QTableWidgetItem("✅" if rs.root.exists else "⚠️ 失效")
            if not rs.root.exists:
                st.setForeground(QtGui.QColor(style.WARN))
            self.table.setItem(i, 1, st)

            path_item = QtWidgets.QTableWidgetItem(rs.root.display)
            path_item.setToolTip(rs.root.path)
            self.table.setItem(i, 2, path_item)

            for col, value in ((3, rs.images), (4, rs.resolved),
                               (5, rs.results), (6, rs.thumbs)):
                it = QtWidgets.QTableWidgetItem(str(value))
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(i, col, it)

            size_it = QtWidgets.QTableWidgetItem(format_bytes(rs.thumbs_bytes))
            size_it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, 7, size_it)

        # 不属于任何已登记路径的记录
        unattributed = stats.images - sum(rs.images for rs in stats.roots)
        self._unattributed = max(0, unattributed)
        if unattributed:
            i = self.table.rowCount()
            self.table.insertRow(i)
            id_item = QtWidgets.QTableWidgetItem("—")
            id_item.setData(QtCore.Qt.UserRole, None)
            self.table.setItem(i, 0, id_item)
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(""))
            note = QtWidgets.QTableWidgetItem("（未归属任何已登记路径）")
            note.setToolTip("在登记路径之前搜索过的图片。清理时选「全部路径」才会覆盖它们。")
            self.table.setItem(i, 2, note)
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(str(unattributed)))

        self._invalidate()

    # ── 操作 ────────────────────────────────────

    def _current_options(self) -> PurgeOptions:
        root_id = self.path_combo.currentData() if self.rb_pick.isChecked() else None
        return PurgeOptions(
            root_id=root_id,
            results=self.cb_results.isChecked() or self.cb_images.isChecked(),
            thumbs=self.cb_thumbs.isChecked(),
            images=self.cb_images.isChecked(),
        )

    def _plan(self) -> None:
        options = self._current_options()
        if options.is_empty():
            self.preview.setPlainText(
                "请至少勾选一项要清理的内容（搜索结果 / 缩略图 / 图片记录）。"
            )
            self._pending = None
            self.btn_run.setEnabled(False)
            return
        try:
            plan = self._with_library(lambda db, store: plan_purge(db, store, options))
        except LibraryError as e:
            self.preview.setPlainText(f"无法预演：{e}")
            self._pending = None
            self.btn_run.setEnabled(False)
            return

        lines = ["── 预演（尚未改动任何数据）──", plan.describe()]
        if plan.images == 0 and plan.results == 0 and plan.thumbs == 0:
            lines.append("")
            lines.append("这个范围内没有可清理的内容。")
        self.preview.setPlainText("\n".join(lines))
        self._pending = options
        self.btn_run.setEnabled(not self._is_empty_plan(plan))

    @staticmethod
    def _is_empty_plan(plan) -> bool:
        return plan.images == 0 and plan.results == 0 and plan.thumbs == 0

    def _run(self) -> None:
        if self._pending is None:
            return
        options = self._pending

        # 二次确认，把预演结论原样摆出来
        try:
            plan = self._with_library(lambda db, store: plan_purge(db, store, options))
        except LibraryError as e:
            QtWidgets.QMessageBox.warning(self, "无法清理", str(e))
            return

        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("确认清理")
        box.setText("以下数据会被删除，且<b>不可撤销</b>：")
        box.setInformativeText(plan.describe())
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        box.button(QtWidgets.QMessageBox.Yes).setText("确认删除")
        box.button(QtWidgets.QMessageBox.No).setText("取消")
        if box.exec() != QtWidgets.QMessageBox.Yes:
            return

        try:
            result = self._with_library(
                lambda db, store: execute_purge(db, store, options)
            )
        except LibraryError as e:
            QtWidgets.QMessageBox.warning(self, "清理失败", str(e))
            return

        self.preview.setPlainText(
            "── 清理结果 ──\n" + result.describe()
            + "\n\n（数据库文件已 VACUUM 回收；上面的「回收」是从磁盘实测的体积差）"
        )
        self._pending = None
        self.btn_run.setEnabled(False)
        self.changed.emit()
        self.reload()

    def _clean_orphans(self) -> None:
        count = self._with_library(lambda db, store: purge_orphan_thumbs(db))
        if count == 0:
            self.preview.setPlainText("没有孤立缩略图需要清理。")
            return
        self.preview.setPlainText(f"── 已清理孤立缩略图 ──\n  删除 {count} 个")
        self.changed.emit()
        self.reload()
