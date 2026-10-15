"""
图库浏览器：缩略图墙

图库页原本只有路径列表与占用统计，看不到图。
这个对话框把已入库的图片铺成缩略图墙，便于「按图找」。

缩略图复用 `imgsearch.library.thumbs`（按内容 dHash 命名，与其他功能同一份缓存），
生成在后台线程，界面不会卡。
"""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch_gui import style
from imgsearch_gui.widgets.thumbnails import ThumbnailLoader

ICON_SIZE = 128
GRID_SIZE = QtCore.QSize(ICON_SIZE + 24, ICON_SIZE + 46)


class LibraryBrowserDialog(QtWidgets.QDialog):
    """图库缩略图墙"""

    def __init__(self, db, store, roots, parent=None):
        super().__init__(parent)
        self.setWindowTitle("浏览图库")
        self.resize(960, 680)
        self.db = db
        self.store = store
        self.roots = roots
        self._records: list = []

        self._thumbs = ThumbnailLoader(self)
        self._thumbs.ready.connect(self._on_thumb)
        self._thumbs.failed.connect(self._on_thumb_failed)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(10)

        # ── 工具条 ──
        tools = QtWidgets.QHBoxLayout()

        self.root_combo = QtWidgets.QComboBox()
        self.root_combo.addItem("全部路径", None)
        for root in self.roots:
            self.root_combo.addItem(Path(root.path).name or root.path, root.id)
        self.root_combo.currentIndexChanged.connect(self.reload)
        tools.addWidget(QtWidgets.QLabel("范围："))
        tools.addWidget(self.root_combo)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("按文件名或 dHash 筛选…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.reload)
        tools.addWidget(self.search_edit, 1)

        self.only_missing = QtWidgets.QCheckBox("只看文件不在的")
        self.only_missing.toggled.connect(self.reload)
        tools.addWidget(self.only_missing)
        outer.addLayout(tools)

        # ── 缩略图墙 ──
        self.list = QtWidgets.QListView()
        self.list.setObjectName("Card")
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setIconSize(QtCore.QSize(ICON_SIZE, ICON_SIZE))
        self.list.setGridSize(GRID_SIZE)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.doubleClicked.connect(lambda idx: self._open_selected())
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.model = QtGui.QStandardItemModel(self.list)
        self.list.setModel(self.model)

        self._placeholder = self._make_placeholder()
        outer.addWidget(self.list, 1)

        # ── 底部 ──
        bar = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("FieldHelp")
        bar.addWidget(self.status)
        bar.addStretch(1)

        open_btn = QtWidgets.QPushButton("打开所选")
        open_btn.clicked.connect(self._open_selected)
        bar.addWidget(open_btn)

        dir_btn = QtWidgets.QPushButton("打开所在目录")
        dir_btn.clicked.connect(self._open_dir)
        bar.addWidget(dir_btn)

        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

        self.reload()

    # ── 数据 ────────────────────────────────────

    def reload(self) -> None:
        """按当前筛选重新铺墙"""
        root_id = self.root_combo.currentData()
        try:
            records = self.store.list_images(
                root_id=root_id,
                search=self.search_edit.text().strip(),
                only_missing=self.only_missing.isChecked(),
            )
        except Exception as e:                            # noqa: BLE001
            self.status.setText(f"读取图库失败：{e}")
            return

        self._records = records
        self.model.clear()
        self._thumbs.clear()

        for rec in records:
            item = QtGui.QStandardItem(Path(rec.abs_path).name or rec.dhash)
            item.setEditable(False)
            item.setIcon(QtGui.QIcon(self._placeholder))
            item.setToolTip(
                f"{rec.abs_path}\n{rec.dimensions}　{rec.dhash}"
                + ("\n⚠️ 文件已不在原位置" if rec.missing else "")
            )
            # 缩略图按内容缓存，因此键用 dhash
            item.setData(rec.dhash, QtCore.Qt.UserRole)
            item.setData(rec.abs_path, QtCore.Qt.UserRole + 1)
            if rec.missing:
                item.setForeground(QtGui.QColor(style.MUTED))
            self.model.appendRow(item)
            self._thumbs.request(rec.dhash, path=rec.abs_path, dhash=rec.dhash,
                                 size=ICON_SIZE)

        total = self.store.count_images(root_id=root_id)
        self.status.setText(
            f"共 {total} 张，当前显示 {len(records)} 张"
            + ("（筛选生效）" if len(records) != total else "")
            + "　·　双击打开图片"
        )

    # ── 缩略图 ──────────────────────────────────

    @staticmethod
    def _make_placeholder() -> QtGui.QPixmap:
        """没有缩略图时的灰底占位，避免一行空白看起来像坏了"""
        pix = QtGui.QPixmap(ICON_SIZE, ICON_SIZE)
        pix.fill(QtGui.QColor(style.CARD_ALT if hasattr(style, "CARD_ALT")
                              else "#e5e7eb"))
        return pix

    def _items_by_dhash(self) -> dict:
        out = {}
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            out.setdefault(item.data(QtCore.Qt.UserRole), []).append(item)
        return out

    def _on_thumb(self, key: str, pixmap) -> None:
        icon = QtGui.QIcon(pixmap)
        for item in self._items_by_dhash().get(key, []):
            item.setIcon(icon)

    def _on_thumb_failed(self, key: str) -> None:
        # 本地图取不到通常是文件已被移走/删除 —— 说清楚而不是留空白
        for item in self._items_by_dhash().get(key, []):
            item.setToolTip(item.toolTip() + "\n⚠️ 缩略图生成失败（文件可能已被移动或删除）")

    # ── 操作 ────────────────────────────────────

    def _selected_records(self) -> list:
        chosen = []
        for index in self.list.selectionModel().selectedIndexes():
            item = self.model.itemFromIndex(index)
            path = item.data(QtCore.Qt.UserRole + 1)
            chosen.append(path)
        return chosen

    def _open_selected(self) -> None:
        for path in self._selected_records():
            if Path(path).is_file():
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _open_dir(self) -> None:
        for path in self._selected_records():
            parent = Path(path).parent
            if parent.is_dir():
                QtGui.QDesktopServices.openUrl(
                    QtCore.QUrl.fromLocalFile(str(parent)))
                return

    def _menu(self, pos) -> None:
        if not self.list.selectionModel().selectedIndexes():
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("打开图片", self._open_selected)
        menu.addAction("打开所在目录", self._open_dir)
        menu.addAction("复制路径", self._copy_paths)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _copy_paths(self) -> None:
        paths = self._selected_records()
        if paths:
            QtWidgets.QApplication.clipboard().setText("\n".join(paths))
            self.status.setText(f"已复制 {len(paths)} 条路径到剪贴板")

    def closeEvent(self, event) -> None:  # noqa: D102
        self._thumbs.stop()
        super().closeEvent(event)

    def reject(self) -> None:  # noqa: D102
        self._thumbs.stop()
        super().reject()
