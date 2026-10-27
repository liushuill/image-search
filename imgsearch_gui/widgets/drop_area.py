"""
拖拽区：把图片拖进来即开始搜索
"""

from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


def image_paths_from_mime(mime: QtCore.QMimeData) -> List[str]:
    """从拖拽数据里挑出图片文件路径"""
    return classify_drop(mime)[0]


def classify_drop(mime: QtCore.QMimeData):
    """
    把拖进来的东西分类，并给出**该说的话**。

    Returns:
        ``(可用的图片路径列表, 给用户的提示；空串表示不用提示)``

    为什么需要提示：拖拽失败时**什么都不发生**是最糟的反馈 ——
    用户分不清是"卡住了"还是"拖错了"。实测遇到的几种情况：

    - 从网页拖图（尤其 Pixiv 那种没加载完的）→ 拖进来的是一个 **html 文件**
      或一个 http 链接；我们的原则是"不下载"，所以只能提示先下载
    - 拖文件夹 → 这不是单张搜索的入口，应引导去图库页登记
    - 拖多个文件 → 一次只处理第一张（语义不变，但要说清）
    - 拖非图片文件 → 说明支持的格式
    """
    if not mime.hasUrls():
        return [], "拖进来的不是文件，无法直接搜索"

    files, dirs, remote, others = [], 0, 0, 0
    for url in mime.urls():
        if not url.isLocalFile():
            remote += 1
            continue
        path = Path(url.toLocalFile())
        if path.is_dir():
            dirs += 1
        elif path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            files.append(str(path))
        else:
            others += 1

    if files:
        if len(files) > 1:
            return files, f"一次只处理第一张（你选了 {len(files)} 张）"
        return files, ""
    if dirs:
        return [], "这是文件夹 —— 请到「图库」页面添加文件夹，再批量识别"
    if remote:
        return [], ("这是网页上的图片链接，不是本地文件 —— "
                    "请先把图片下载下来，再拖进来")
    if others:
        return [], "不是支持的图片格式（jpg / png / webp / bmp / gif / tiff）"
    return [], ""


class DropArea(QtWidgets.QFrame):
    """可点击选择、也可拖入图片的区域"""

    dropped = QtCore.Signal(list)      # List[str] 图片路径
    hint = QtCore.Signal(str)          # 没搜成时给用户一句话（空串不发）
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
        # ⚠️ 必须允许换行：窗口左栏宽度有限，而 150% 缩放下这两行文本比
        #    虚线框还宽。QLabel 默认是**裁掉**多出来的部分（不是省略号），
        #    实机表现为「拖图片拖到这里」——首字被切掉，看着像 bug。
        self._title.setWordWrap(True)

        self._hint = QtWidgets.QLabel("或点击选择文件　·　支持 jpg / png / webp / bmp / gif / tiff")
        self._hint.setObjectName("DropHint")
        self._hint.setAlignment(QtCore.Qt.AlignCenter)
        self._hint.setWordWrap(True)

        lay.addWidget(self._title)
        lay.addWidget(self._hint)

    # ── 拖拽 ────────────────────────────────────

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        # 只要有 URL 就接受 —— 这样「拖了但用不了」时才有机会给出提示。
        # 完全不接受的话，用户看到的是"拖不进去"，一样莫名。
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self._set_active(False)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self._set_active(False)
        paths, note = classify_drop(event.mimeData())
        event.acceptProposedAction()
        if paths:
            self.dropped.emit(paths)
        if note:
            self.hint.emit(note)

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
