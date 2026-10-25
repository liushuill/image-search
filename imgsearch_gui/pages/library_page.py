"""
图库页：手动登记根路径、查看状态与占用、移除时询问是否清理持久化数据

三条要点（对应需求）：

1. **工具不依赖工作目录** —— 路径是配置项，可以登记任意多个、跨磁盘
2. **删路径时询问是否清理持久化文件** —— 弹窗里给出四个档位，
   并把每个档位**会删掉多少条、多少体积**当场算出来（见 :class:`RemovePathDialog`）
3. **失效路径只标记、不删数据** —— 目录改名/外接盘未挂载时标红，
   可用「重新指定位置」把记录一起搬过去
"""

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.library import (
    LibraryDB,
    LibraryError,
    LibraryStore,
    PurgeOptions,
    RootManager,
    execute_purge,
    format_bytes,
    plan_purge,
)
from imgsearch_gui import style

# 移除路径时的清理档位：(值, 标题, 说明)
PURGE_MODES = [
    ("none", "仅移除登记，保留持久化数据",
     "记录都还在。之后再搜同一张图仍会命中缓存。"),
    ("results", "同时删除该路径的搜索结果",
     "图片记录与 dHash 索引保留 —— 「这张搜过了」依然能判断，只是需要重新搜一次拿结果。"),
    ("thumbs", "同时删除该路径的缓存缩略图",
     "只清掉为报告/预览生成的图片副本，搜索结果不受影响。"),
    ("all", "清空该路径的全部数据",
     "图片记录 + 搜索结果 + 缩略图一起删。这是最彻底的档位。"),
]


def _options_for(mode: str, root_id: int) -> PurgeOptions:
    if mode == "results":
        return PurgeOptions(root_id=root_id, results=True)
    if mode == "thumbs":
        return PurgeOptions(root_id=root_id, thumbs=True)
    if mode == "all":
        return PurgeOptions(root_id=root_id, images=True, thumbs=True)
    return PurgeOptions(root_id=root_id)


class RemovePathDialog(QtWidgets.QDialog):
    """
    移除图库路径前的询问。

    每个档位都会**当场算出**影响范围（多少条记录 / 多少体积），
    避免用户在不知情的情况下点掉数据。
    """

    def __init__(self, db: LibraryDB, store: LibraryStore, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("移除图库路径")
        self.setMinimumWidth(560)
        self.db = db
        self.store = store
        self.root = root
        self._mode = "none"

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)

        head = QtWidgets.QLabel("确定移除这条图库路径吗？")
        head.setObjectName("SectionTitle")
        lay.addWidget(head)

        path_lbl = QtWidgets.QLabel(root.display if not root.label else f"{root.label}　{root.path}")
        path_lbl.setObjectName("FieldHelp")
        path_lbl.setWordWrap(True)
        path_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(path_lbl)

        note = QtWidgets.QLabel(
            "移除只是「不再登记这条路径」。是否顺带清理它名下的持久化数据，由你决定："
        )
        note.setObjectName("FieldHelp")
        note.setWordWrap(True)
        lay.addWidget(note)

        self._radios = []
        for mode, title, desc in PURGE_MODES:
            box = QtWidgets.QRadioButton(title)
            if mode == "none":
                box.setChecked(True)
            box.toggled.connect(self._on_change)
            lay.addWidget(box)

            d = QtWidgets.QLabel("　　" + desc)
            d.setObjectName("FieldHelp")
            d.setWordWrap(True)
            lay.addWidget(d)
            self._radios.append((mode, box))

        # 影响范围预览
        self.preview = QtWidgets.QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            f"background:{style.BG}; border:1px solid {style.BORDER};"
            "border-radius:6px; padding:8px 10px;"
        )
        lay.addWidget(self.preview)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.button(QtWidgets.QDialogButtonBox.Ok).setText("确定移除")
        btns.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        # 清理数据是不可逆动作，默认焦点放在「取消」上更稳
        btns.button(QtWidgets.QDialogButtonBox.Cancel).setDefault(True)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._update_preview()

    @property
    def purge_mode(self) -> str:
        for mode, box in self._radios:
            if box.isChecked():
                return mode
        return "none"

    def _on_change(self, _checked: bool) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        mode = self.purge_mode
        if mode == "none":
            images = self.store.count_images(root_id=self.root.id)
            self.preview.setText(
                f"将保留：图片记录 {images} 条及其全部搜索结果与缩略图"
            )
            return
        try:
            plan = plan_purge(self.db, self.store,
                              _options_for(mode, self.root.id))
        except LibraryError as e:
            self.preview.setText(f"无法计算影响范围：{e}")
            return
        self.preview.setText(plan.describe())


class LibraryPage(QtWidgets.QWidget):
    # 请求切到「浏览」页（由主窗口接住并 go_to）
    browse_requested = QtCore.Signal()
    """图库路径管理"""

    changed = QtCore.Signal()

    HEADERS = ["状态", "别名", "路径", "图片", "已搜", "结果", "缩略图", "缩略图占用"]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("图库")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch(1)
        for text, slot, tip in (
            ("添加路径", self._add, "登记一个图库根路径（可多个、可跨磁盘）"),
            ("刷新文件状态", self._refresh_files, "重新检查文件是否还在最后已知位置"),
        ):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            b.setToolTip(tip)
            head.addWidget(b)
        outer.addLayout(head)

        hint = QtWidgets.QLabel(
            "图库以内容（dHash）识别图片，路径只是「最后已知位置」。"
            "因此文件在不同目录之间移动后，仍能认出「这张搜过了」并复用缓存结果。"
            "路径之间不允许嵌套 —— 否则同一张图会被记录两次。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

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
        self.table.itemSelectionChanged.connect(self._update_buttons)
        outer.addWidget(self.table, 1)

        ops = QtWidgets.QHBoxLayout()
        self.btn_relocate = QtWidgets.QPushButton("重新指定位置")
        self.btn_relocate.setToolTip("目录被改名/搬走后，指向新位置并顺带改写记录路径（无需重新扫描）")
        self.btn_relocate.clicked.connect(self._relocate)
        ops.addWidget(self.btn_relocate)

        self.btn_label = QtWidgets.QPushButton("改别名")
        self.btn_label.clicked.connect(self._set_label)
        ops.addWidget(self.btn_label)

        self.btn_open = QtWidgets.QPushButton("打开目录")
        self.btn_open.clicked.connect(self._open_dir)
        ops.addWidget(self.btn_open)

        self.btn_batch = QtWidgets.QPushButton("识别未搜索的图…")
        self.btn_batch.setToolTip(
            "把选中路径（未选中则全部）下的图片逐个识别，结果写入图库。\n"
            "已识别过的会命中缓存跳过，不消耗配额。"
        )
        self.btn_batch.clicked.connect(self._batch_search)
        ops.addWidget(self.btn_batch)

        self.btn_export = QtWidgets.QPushButton("导出图库…")
        self.btn_export.setToolTip("把已经搜过的批量导出（勾选多条路径时以选中的为准）")
        self.btn_export.clicked.connect(self._export)
        ops.addWidget(self.btn_export)

        ops.addStretch(1)
        self.btn_remove = QtWidgets.QPushButton("移除路径")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.clicked.connect(self._remove)
        ops.addWidget(self.btn_remove)
        outer.addLayout(ops)

        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("FieldHelp")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)

        self.reload()

    def showEvent(self, event) -> None:          # noqa: D102
        # 每次切到本页都重新统计：搜索页刚入库的图片能立刻反映出来
        super().showEvent(event)
        self.reload()

    # ── 数据 ────────────────────────────────────

    def _with_library(self, fn):
        """短连接执行一次操作（避免长期持有句柄读到陈旧状态）"""
        with LibraryDB() as db:
            return fn(db, LibraryStore(db))

    def reload(self) -> None:
        def build(db, store):
            roots = RootManager(db).list()
            rows = []
            for r in roots:
                rows.append({
                    "root": r,
                    "images": store.count_images(root_id=r.id),
                    "resolved": store.count_resolved(root_id=r.id),
                    "results": store.count_results(root_id=r.id),
                    "thumbs": _thumbs_for(db, r.id),
                    "bytes": _thumbs_bytes_for(db, r.id),
                })
            total_images = store.count_images()
            total_results = store.count_results()
            return rows, total_images, total_results

        rows, total_images, total_results = self._with_library(build)

        self.table.setRowCount(0)
        for row in rows:
            r = row["root"]
            i = self.table.rowCount()
            self.table.insertRow(i)

            status = "✅ 正常" if r.exists else "⚠️ 路径不存在"
            status_item = QtWidgets.QTableWidgetItem(status)
            if not r.exists:
                status_item.setForeground(QtGui.QColor(style.WARN))
                status_item.setToolTip("外接盘未挂载，或目录被改名/移动。"
                                       "记录不会被删除，可用「重新指定位置」指到新位置。")
            self.table.setItem(i, 0, status_item)

            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(r.label or ""))
            path_item = QtWidgets.QTableWidgetItem(r.path)
            path_item.setToolTip(r.path)
            self.table.setItem(i, 2, path_item)

            for col, value in ((3, row["images"]), (4, row["resolved"]),
                               (5, row["results"]), (6, row["thumbs"])):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(i, col, item)

            size_item = QtWidgets.QTableWidgetItem(format_bytes(row["bytes"]))
            size_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, 7, size_item)

            # 把 id 挂在第一列，用于后续操作
            self.table.item(i, 0).setData(QtCore.Qt.UserRole, r.id)

        if not rows:
            self.summary.setText(
                "尚未登记任何图库路径。点「添加路径」登记一个（例如你的图片库根目录）。"
            )
        else:
            self.summary.setText(
                f"共 {len(rows)} 条路径　·　图片记录 {total_images} 条　"
                f"搜索结果 {total_results} 条"
            )
        self._update_buttons()

    def _selected_root_id(self):
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(QtCore.Qt.UserRole)

    def _selected_root(self):
        rid = self._selected_root_id()
        if rid is None:
            return None
        return self._with_library(lambda db, store: RootManager(db).get(rid))

    def _update_buttons(self) -> None:
        has = self._selected_root_id() is not None
        for b in (self.btn_relocate, self.btn_label, self.btn_open, self.btn_remove):
            b.setEnabled(has)

    # ── 操作 ────────────────────────────────────

    def _add(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择图库根目录", str(QtCore.QDir.home())
        )
        if not path:
            return
        # 允许登记尚未挂载的外接盘：先问一句是不是就要用当前这个路径
        label, ok = QtWidgets.QInputDialog.getText(
            self, "图库路径别名", "给这条路径起个别名（可留空）："
        )
        if not ok:
            return
        try:
            self._with_library(
                lambda db, store: RootManager(db).add(path, label=label.strip())
            )
        except LibraryError as e:
            # 嵌套/重复登记会走到这里，消息本身就是给人看的
            QtWidgets.QMessageBox.warning(self, "无法添加", str(e))
            return
        self.changed.emit()
        self.reload()

    def _remove(self) -> None:
        root = self._selected_root()
        if root is None:
            return

        def run(db, store):
            dlg = RemovePathDialog(db, store, root, parent=self)
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return None
            mode = dlg.purge_mode
            if mode != "none":
                options = _options_for(mode, root.id)
                result = execute_purge(db, store, options)
                RootManager(db).remove(root.id)
                return mode, result
            RootManager(db).remove(root.id)
            return mode, None

        try:
            outcome = self._with_library(run)
        except LibraryError as e:
            QtWidgets.QMessageBox.warning(self, "清理失败", str(e))
            return
        if outcome is None:
            return

        mode, result = outcome
        if result is not None:
            QtWidgets.QMessageBox.information(
                self, "已移除并清理",
                f"已移除：{root.display}\n\n" + result.describe()
            )
        self.changed.emit()
        self.reload()

    def _relocate(self) -> None:
        root = self._selected_root()
        if root is None:
            return
        new_path = QtWidgets.QFileDialog.getExistingDirectory(
            self, f"为「{root.display}」指定新位置", root.path
        )
        if not new_path:
            return
        try:
            updated = self._with_library(
                lambda db, store: RootManager(db).relocate(root.id, new_path)
            )
        except LibraryError as e:
            QtWidgets.QMessageBox.warning(self, "无法重新指定", str(e))
            return
        QtWidgets.QMessageBox.information(
            self, "已重新指定",
            f"路径已指向：\n{new_path}\n\n"
            f"顺带改写了 {updated} 条记录的路径，无需重新扫描。"
        )
        self.reload()

    def _set_label(self) -> None:
        root = self._selected_root()
        if root is None:
            return
        label, ok = QtWidgets.QInputDialog.getText(
            self, "改别名", "别名：", text=root.label
        )
        if not ok:
            return
        self._with_library(
            lambda db, store: RootManager(db).set_label(root.id, label.strip())
        )
        self.reload()

    def _batch_search(self) -> None:
        """
        批量识别。

        需要一个**目录**：优先用选中的已登记根路径；
        没选中就让用户挑一个（也允许挑一个还没登记的目录 ——
        识别结果照样会按图库身份记下来）。
        """
        from imgsearch_gui.dialogs.batch_dialog import BatchDialog

        directory = ""
        root_id = self._selected_root_id()
        if root_id is not None:
            root = self._with_library(
                lambda db, store: store.roots.get(root_id))
            if root is not None:
                directory = root.path

        if not directory:
            directory = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择要批量识别的目录",
                str(QtCore.QDir.home()))
            if not directory:
                return

        BatchDialog(directory, self).exec()

    def _export(self) -> None:
        """
        导出图库。

        选中某条根路径时只导出它；没有选中则导出全部。
        """
        from imgsearch.exporters import from_library
        from imgsearch_gui.dialogs.export_dialog import ExportDialog

        root_id = self._selected_root_id()
        scope = "全部路径" if root_id is None else "选中的路径"

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            records = self._with_library(
                lambda db, store: from_library(store, root_id=root_id)
            )
        except Exception as e:                            # noqa: BLE001
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "无法导出",
                                          f"收集图库数据失败：{e}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if not records:
            QtWidgets.QMessageBox.information(
                self, "没有可导出的数据",
                f"{scope}下还没有任何搜索结果。\n"
                "先搜索几张图，或用「搜索」页搜完再回来。"
            )
            return

        ExportDialog(records, self,
                     title=f"导出图库（{scope}）").exec()

    def _open_dir(self) -> None:
        root = self._selected_root()
        if root is None:
            return
        from imgsearch_gui.shell_open import open_dir

        target = root.path if root.exists else str(QtCore.QDir.home())
        open_dir(target)

    def _refresh_files(self) -> None:
        missing = self._with_library(
            lambda db, store: RootManager(db).refresh_missing()
        )
        QtWidgets.QMessageBox.information(
            self, "已刷新",
            f"重新检查完成：{missing} 条记录的文件已不在最后已知位置。\n\n"
            "记录没有被删除 —— 仍可凭 dHash 命中缓存；"
            "若目录被改名/移动，用「重新指定位置」指过去即可。"
        )
        self.reload()


# ── 小工具：按内容哈希统计某路径的缩略图 ──


def _thumbs_for(db: LibraryDB, root_id: int) -> int:
    from imgsearch.library import thumbs
    from imgsearch.library.cleanup import known_dhashes

    count = 0
    for d in known_dhashes(db, root_id):
        if thumbs.exists(d):
            count += 1
    return count


def _thumbs_bytes_for(db: LibraryDB, root_id: int) -> int:
    from imgsearch.library import thumbs
    from imgsearch.library.cleanup import known_dhashes

    total = 0
    for d in known_dhashes(db, root_id):
        try:
            p = thumbs.path_for(d)
        except LibraryError:
            continue
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total
