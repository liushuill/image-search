"""
图库浏览页：缩略图墙

原来是「图库」页里的一个弹窗，用起来要开/关模态框，也不方便反复对照。
改成独立页面后：侧栏一键直达、切回来会自动刷新、窗口大小随主窗口。

缩略图复用 `imgsearch.library.thumbs`（按内容 dHash 命名，与其他功能同一份缓存），
在后台线程生成，界面不会卡。
"""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch_gui import style
from imgsearch_gui.widgets.thumbnails import ThumbnailLoader

ICON_SIZE = 128
GRID_SIZE = QtCore.QSize(ICON_SIZE + 24, ICON_SIZE + 46)


class LibraryBrowserPage(QtWidgets.QWidget):
    """缩略图墙（主窗口的一个页面）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list = []
        self._roots: list = []
        self._db = None
        self._store = None

        self._thumbs = ThumbnailLoader(self)
        self._thumbs.ready.connect(self._on_thumb)
        self._thumbs.failed.connect(self._on_thumb_failed)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        head = QtWidgets.QLabel("图库浏览")
        head.setObjectName("PageTitle")
        outer.addWidget(head)

        hint = QtWidgets.QLabel(
            "已入库的图片铺成缩略图墙。双击打开图片，右键可打开所在目录或复制路径。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 工具条 ──
        tools = QtWidgets.QHBoxLayout()

        self.root_combo = QtWidgets.QComboBox()
        self.root_combo.setMinimumWidth(180)
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

        refresh_btn = QtWidgets.QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload)
        tools.addWidget(refresh_btn)
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
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
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
        outer.addLayout(bar)

        self._show_placeholder("切到本页时会自动读取图库")

    # ── 生命周期 ────────────────────────────────

    def on_shown(self) -> None:
        """
        每次切到本页时调用（由主窗口触发）。

        必须刷新：用户可能刚搜完图、刚批量识别过、或在「清理」页删过东西。
        """
        self._open_library()
        self._reload_roots()
        self.reload()

    def _open_library(self) -> bool:
        from imgsearch.service import open_library

        db, store = open_library()
        self._db, self._store = db, store
        return store is not None

    def _reload_roots(self) -> None:
        self._roots = []
        if self._db is None:
            return
        try:
            from imgsearch.library.paths import RootManager
            self._roots = RootManager(self._db).list()
        except Exception:                                 # noqa: BLE001
            self._roots = []

        current = self.root_combo.currentData()
        self.root_combo.blockSignals(True)
        self.root_combo.clear()
        self.root_combo.addItem("全部路径", None)
        for root in self._roots:
            self.root_combo.addItem(Path(root.path).name or root.path, root.id)
        if current is not None:
            idx = self.root_combo.findData(current)
            if idx >= 0:
                self.root_combo.setCurrentIndex(idx)
        self.root_combo.blockSignals(False)

    # ── 数据 ────────────────────────────────────

    def reload(self) -> None:
        if self._store is None:
            self._show_placeholder(
                "图库未启用或无法打开。可在「设置」页启用本地图库。")
            return

        root_id = self.root_combo.currentData()
        try:
            records = self._store.list_images(
                root_id=root_id,
                search=self.search_edit.text().strip(),
                only_missing=self.only_missing.isChecked(),
            )
        except Exception as e:                            # noqa: BLE001
            self._show_placeholder(f"读取图库失败：{e}")
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
            item.setData(rec.dhash, QtCore.Qt.UserRole)
            item.setData(rec.abs_path, QtCore.Qt.UserRole + 1)
            if rec.missing:
                item.setForeground(QtGui.QColor(style.MUTED))
            self.model.appendRow(item)
            self._thumbs.request(rec.dhash, path=rec.abs_path, dhash=rec.dhash,
                                 size=ICON_SIZE)

        try:
            total = self._store.count_images(root_id=root_id)
        except Exception:                                 # noqa: BLE001
            total = len(records)

        if not records:
            self.status.setText(
                "图库里还没有图片。先搜索几张，或到「图库」页用"
                "「识别未搜索的图…」批量识别。")
        else:
            self.status.setText(
                f"共 {total} 张，当前显示 {len(records)} 张"
                + ("（筛选生效）" if len(records) != total else "")
                + "　·　双击打开图片"
            )

    def _show_placeholder(self, message: str) -> None:
        self.model.clear()
        self.status.setText(message)

    # ── 缩略图 ──────────────────────────────────

    @staticmethod
    def _make_placeholder() -> QtGui.QPixmap:
        """没有缩略图时的灰底占位，避免一片空白看起来像坏了"""
        pix = QtGui.QPixmap(ICON_SIZE, ICON_SIZE)
        pix.fill(QtGui.QColor(getattr(style, "CARD_ALT", "#e5e7eb")))
        return pix

    def _items_by_dhash(self) -> dict:
        out: dict = {}
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            out.setdefault(item.data(QtCore.Qt.UserRole), []).append(item)
        return out

    def _on_thumb(self, key: str, pixmap) -> None:
        icon = QtGui.QIcon(pixmap)
        for item in self._items_by_dhash().get(key, []):
            item.setIcon(icon)

    def _on_thumb_failed(self, key: str) -> None:
        # 本地图取不到通常是文件被移走/删除 —— 说清楚而不是留空白
        for item in self._items_by_dhash().get(key, []):
            item.setToolTip(
                item.toolTip() + "\n⚠️ 缩略图生成失败（文件可能已被移动或删除）")

    # ── 操作 ────────────────────────────────────

    def _selected_records(self) -> list:
        chosen = []
        for index in self.list.selectionModel().selectedIndexes():
            item = self.model.itemFromIndex(index)
            chosen.append(item.data(QtCore.Qt.UserRole + 1))
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
