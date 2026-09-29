"""
搜索结果表格
"""

from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.engines.base import SearchResult
from imgsearch_gui import style

COLUMNS = ["相似度", "引擎", "Pixiv ID", "画师", "标题 / 作品", "站点 ID", "来源链接"]
COL_SIM, COL_ENGINE, COL_PIXIV, COL_ARTIST, COL_TITLE, COL_IDS, COL_URL = range(7)


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

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
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

        self._results: List[SearchResult] = []
        self.doubleClicked.connect(self._open_current)

    # ── 填充 ────────────────────────────────────

    def set_results(self, results: List[SearchResult]) -> None:
        self._results = list(results)
        self.setRowCount(0)
        for r in self._results:
            row = self.rowCount()
            self.insertRow(row)

            sim = QtWidgets.QTableWidgetItem(f"{r.similarity:.1f}%")
            sim.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # 按数值排序用
            sim.setData(QtCore.Qt.UserRole, float(r.similarity or 0))
            if r.similarity >= 85:
                sim.setForeground(QtGui.QColor(style.OK))
            elif r.similarity < 60:
                sim.setForeground(QtGui.QColor(style.MUTED))
            self.setItem(row, COL_SIM, sim)

            self.setItem(row, COL_ENGINE, QtWidgets.QTableWidgetItem(r.source or ""))

            pixiv = r.pixiv_image_id() if r.pixiv_id else ""
            self.setItem(row, COL_PIXIV, QtWidgets.QTableWidgetItem(pixiv or ""))

            self.setItem(row, COL_ARTIST, QtWidgets.QTableWidgetItem(r.artist or ""))

            title = " / ".join(x for x in (r.title, r.material) if x)
            item = QtWidgets.QTableWidgetItem(title)
            if r.detail:
                item.setToolTip(r.detail)
            self.setItem(row, COL_TITLE, item)

            self.setItem(row, COL_IDS, QtWidgets.QTableWidgetItem(site_ids(r)))

            url = best_url(r)
            link = QtWidgets.QTableWidgetItem(url)
            link.setToolTip(url)
            if url:
                link.setForeground(QtGui.QColor(style.ACCENT))
            self.setItem(row, COL_URL, link)

        self.resizeRowsToContents()

    def results(self) -> List[SearchResult]:
        return list(self._results)

    def urls(self) -> List[str]:
        return result_urls(self._results)

    # ── 交互 ────────────────────────────────────

    def _open_current(self, index: QtCore.QModelIndex) -> None:
        url = self.item(index.row(), COL_URL).text()
        if url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

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
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        elif chosen is act_copy_url:
            QtWidgets.QApplication.clipboard().setText(self.item(row, COL_URL).text())
        elif chosen is act_copy_row:
            cells = [self.item(row, c).text() if self.item(row, c) else ""
                     for c in range(self.columnCount())]
            QtWidgets.QApplication.clipboard().setText("\t".join(cells))
