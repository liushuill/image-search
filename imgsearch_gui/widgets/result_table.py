"""
搜索结果表格
"""

from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.engines.base import SearchResult
from imgsearch_gui import style

COLUMNS = ["预览", "相似度", "引擎", "Pixiv ID", "画师", "标题 / 作品",
           "站点 ID", "来源链接"]
(COL_THUMB, COL_SIM, COL_ENGINE, COL_PIXIV, COL_ARTIST,
 COL_TITLE, COL_IDS, COL_URL) = range(8)

# 缩略图显示边长与行高
THUMB_SIZE = 72
ROW_HEIGHT = THUMB_SIZE + 14

# 图源缩略图取不到时的占位说明。
# ⚠️ 不是所有图源都能取：SauceNAO 的缩略图链接带 ?auth=… 令牌，
# **当场取有效、过一会儿再取会 403**（实测）。所以历史记录里的旧链接
# 注定失败 —— 这时给一个明确说明，而不是空白让人以为坏掉了。
THUMB_FAILED = "取不到\n（链接已过期）"


def site_ids(r: SearchResult) -> str:
    """把各站点的 ID 汇总成一行"""
    parts = []
    for label, value in (("Danbooru", r.danbooru_id), ("Gelbooru", r.gelbooru_id),
                         ("Twitter", r.twitter_id)):
        if value:
            parts.append(f"{label}={value}")
    parts.extend(f"{k}={v}" for k, v in (r.extra_ids or {}).items())
    return ", ".join(parts)


def best_url(r: SearchResult) -> str:
    """挑一条最有代表性的链接"""
    if r.pixiv_id:
        return f"https://www.pixiv.net/artworks/{r.pixiv_id}"
    if r.ext_urls:
        return r.ext_urls[0]
    return r.highres_url or ""


def result_urls(results: List[SearchResult]) -> List[str]:
    """把结果里所有可下载/可跳转的链接去重后展开（含多图页码）"""
    seen, out = set(), []

    def _add(u: str) -> None:
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    for r in results:
        if r.pixiv_id:
            _add(f"https://www.pixiv.net/artworks/{r.pixiv_id}")
        for u in (r.ext_urls or []):
            _add(u)
    return out


class ResultTable(QtWidgets.QTableWidget):
    """展示 SearchResult 列表"""

    def _init_thumbnails(self) -> None:
        """缩略图：后台加载 + 按图源去重 + 记住已到的图"""
        from imgsearch_gui.widgets.thumbnails import ThumbnailLoader, stable_url_key

        self._stable_key = stable_url_key
        self._thumbs = ThumbnailLoader(self)
        self._thumbs.ready.connect(self._on_thumb)
        self._thumbs.failed.connect(self._on_thumb_failed)
        self._thumb_labels: dict = {}      # key -> [QLabel, ...]
        self._pixmaps: dict = {}           # key -> QPixmap（后注册的能立刻拿到）
        self._pending: set = set()

    def _on_thumb(self, key: str, pixmap) -> None:
        self._pixmaps[key] = pixmap
        self._pending.discard(key)
        for label in self._thumb_labels.get(key, []):
            label.setPixmap(pixmap)
            label.setText("")

    def _on_thumb_failed(self, key: str) -> None:
        self._pending.discard(key)
        for label in self._thumb_labels.get(key, []):
            label.setText(THUMB_FAILED)
            label.setStyleSheet(f"color:{style.MUTED};font-size:11px;")

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
        self._init_thumbnails()
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)
        self.setSortingEnabled(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_SIM, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_ENGINE, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_PIXIV, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_ARTIST, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TITLE, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(COL_IDS, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_URL, QtWidgets.QHeaderView.Stretch)
        # ⚠️ Stretch 的两列（标题 / 来源链接）在窗口变窄时会被压到比列头还窄，
        #    列头就被截成「题 / 作,」这种。给所有列一个下限：
        #    宁可出现横向滚动条，也不要字被切掉。
        # 最长的列头是「标题 / 作品」(72px)，加内边距取 88
        fm = header.fontMetrics()
        model = self.model()
        need = max([fm.horizontalAdvance(str(model.headerData(
            c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) or ""))
            for c in range(model.columnCount())] or [0]) + 16
        header.setMinimumSectionSize(max(need, 64))

        self._results: List[SearchResult] = []
        self.doubleClicked.connect(self._open_current)

    # ── 填充 ────────────────────────────────────

    def set_results(self, results: List[SearchResult]) -> None:
        self._results = list(results)
        # 清掉上一批的标签登记（图还在 _pixmaps 里，重复出现时无需再取）
        self._thumb_labels = {}
        self.setRowCount(0)
        for r in self._results:
            row = self.rowCount()
            self.insertRow(row)
            self._set_thumb_cell(row, r)

            sim = QtWidgets.QTableWidgetItem(f"{r.similarity:.1f}%")
            sim.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # 按数值排序用
            sim.setData(QtCore.Qt.UserRole, float(r.similarity or 0))
            if r.similarity >= 85:
                sim.setForeground(QtGui.QColor(style.OK))
            elif r.similarity < 60:
                sim.setForeground(QtGui.QColor(style.MUTED))
            self.setItem(row, COL_SIM, sim)

            self._put(row, COL_ENGINE, r.source or "")

            pixiv = r.pixiv_image_id() if r.pixiv_id else ""
            self._put(row, COL_PIXIV, pixiv or "")

            self._put(row, COL_ARTIST, r.artist or "")

            title = " / ".join(x for x in (r.title, r.material) if x)
            item = self._put(row, COL_TITLE, title)
            if r.detail:
                item.setToolTip(r.detail + (f"\n{title}" if title else ""))
            self.setItem(row, COL_TITLE, item)

            self._put(row, COL_IDS, site_ids(r))

            url = best_url(r)
            link = QtWidgets.QTableWidgetItem(url)
            link.setToolTip(url)
            if url:
                link.setForeground(QtGui.QColor(style.ACCENT))
            self.setItem(row, COL_URL, link)

        self.resizeRowsToContents()
        # 缩略图列需要固定行高（resizeRowsToContents 会把它压扁）
        for row in range(self.rowCount()):
            self.setRowHeight(row, max(ROW_HEIGHT, self.rowHeight(row)))

    def _put(self, row: int, col: int, text: str) -> QtWidgets.QTableWidgetItem:
        """
        放一个文字单元格，并把全文设为 tooltip。

        为什么需要：窗口不宽时列会被压窄，长文字（引擎名、站点 ID）会被省略号
        截断。上一版只给标题和链接加了 tooltip，其余列看不到全文。
        """
        item = QtWidgets.QTableWidgetItem(text)
        if text:
            item.setToolTip(text)
        self.setItem(row, col, item)
        return item

    def _set_thumb_cell(self, row: int, r: SearchResult) -> None:
        """把缩略图放进单元格（先放占位，图到了再替换）"""
        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setFixedSize(THUMB_SIZE, THUMB_SIZE)

        url = (r.thumbnail or "").strip()
        if not url:
            label.setText("—")
            label.setToolTip("该引擎没有提供缩略图")
            label.setStyleSheet(f"color:{style.MUTED};")
        else:
            key = self._stable_key(url)
            # 先查已到的图，避免重复设置时闪一下占位
            cached = self._pixmaps.get(key)
            if cached is not None:
                label.setPixmap(cached)
            elif key in self._pending:
                label.setText("…")
            else:
                label.setText("…")
                self._pending.add(key)
                self._thumbs.request(key, url=url)
            self._thumb_labels.setdefault(key, []).append(label)
            label.setToolTip(url)

        self.setCellWidget(row, COL_THUMB, label)

    def results(self) -> List[SearchResult]:
        return list(self._results)

    def urls(self) -> List[str]:
        return result_urls(self._results)

    # ── 交互 ────────────────────────────────────

    def _open_current(self, index: QtCore.QModelIndex) -> None:
        url = self.item(index.row(), COL_URL).text()
        if url:
            from imgsearch_gui.shell_open import open_url
            open_url(url)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        row = item.row()
        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction("用浏览器打开链接")
        act_copy_url = menu.addAction("复制链接")
        act_copy_row = menu.addAction("复制整行")
        chosen = menu.exec(event.globalPos())
        if chosen is act_open:
            url = self.item(row, COL_URL).text()
            if url:
                from imgsearch_gui.shell_open import open_url
            open_url(url)
        elif chosen is act_copy_url:
            QtWidgets.QApplication.clipboard().setText(self.item(row, COL_URL).text())
        elif chosen is act_copy_row:
            cells = [self.item(row, c).text() if self.item(row, c) else ""
                     for c in range(self.columnCount())]
            QtWidgets.QApplication.clipboard().setText("\t".join(cells))
