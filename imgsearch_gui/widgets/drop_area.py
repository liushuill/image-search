"""
拖拽区：把图片拖进来即开始搜索
"""

from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


def image_paths_from_mime(mime: QtCore.QMimeData) -> List[str]:
    """从拖拽数据里挑出图片文件路径"""
    if not mime.hasUrls():
        return []
    out = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            out.append(str(path))
    return out


class DropArea(QtWidgets.QFrame):
    """可点击选择、也可拖入图片的区域"""

    dropped = QtCore.Signal(list)      # List[str] 图片路径
    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setCursor(QtCore.Qt.PointingHandCursor)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        lay.setSpacing(6)

        self._title = QtWidgets.QLabel("把图片拖到这里")
        self._title.setObjectName("DropTitle")
        self._title.setAlignment(QtCore.Qt.AlignCenter)

        self._hint = QtWidgets.QLabel("或点击选择文件　·　支持 jpg / png / webp / bmp / gif / tiff")
        self._hint.setObjectName("DropHint")
        self._hint.setAlignment(QtCore.Qt.AlignCenter)

        lay.addWidget(self._title)
        lay.addWidget(self._hint)

    # ── 拖拽 ────────────────────────────────────

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self._set_active(False)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self._set_active(False)
        paths = image_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.dropped.emit(paths)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.clicked.emit()

    def _set_active(self, active: bool) -> None:
        self.setObjectName("DropAreaActive" if active else "DropArea")
        # 改了 objectName 需要重新应用样式表
        self.style().unpolish(self)
        self.style().polish(self)

    def set_busy(self, busy: bool, name: str = "") -> None:
        if busy:
            self._title.setText(f"正在搜索：{name}" if name else "正在搜索…")
            self._hint.setText("多引擎会依次尝试，请稍候（进度见下方日志）")
        else:
            self._title.setText("把图片拖到这里")
            self._hint.setText("或点击选择文件　·　支持 jpg / png / webp / bmp / gif / tiff")
