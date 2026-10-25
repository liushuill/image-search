"""
搜索页：拖入图片 → 展示结果 → 复制/导出链接
"""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.engines.store import get_store
from imgsearch_gui import style
from imgsearch_gui.widgets.drop_area import DropArea, IMAGE_SUFFIXES
from imgsearch_gui.widgets.result_table import ResultTable
from imgsearch_gui.workers import SearchWorker

PREVIEW_W = 232


class SearchPage(QtWidgets.QWidget):
    """单图搜索"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: SearchWorker | None = None
        self._image_path: str = ""
        # 最近一次搜索的完整结果（导出时需要 dhash 与是否来自缓存）
        self._last_outcome = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        title = QtWidgets.QLabel("搜索")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        hint = QtWidgets.QLabel(
            "把图片拖进来即开始搜索。图库以内容（dHash）识别图片 —— "
            "同一张图换个位置再搜会直接命中缓存，不消耗配额。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # ── 左栏 ──
        left = QtWidgets.QWidget()
        left.setFixedWidth(PREVIEW_W + 20)
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

        self.drop = DropArea()
        self.drop.dropped.connect(lambda paths: self.start_search(paths[0]))
        self.drop.clicked.connect(self._pick_file)
        ll.addWidget(self.drop)

        self.preview = QtWidgets.QLabel("尚无图片")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(150)
        self.preview.setObjectName("Card")
        self.preview.setWordWrap(True)
        ll.addWidget(self.preview)

        self.file_label = QtWidgets.QLabel("")
        self.file_label.setObjectName("FieldHelp")
        self.file_label.setWordWrap(True)
        ll.addWidget(self.file_label)

        # 选项
        opts = QtWidgets.QFrame()
        opts.setObjectName("Card")
        ol = QtWidgets.QVBoxLayout(opts)
        ol.setContentsMargins(12, 10, 12, 10)
        ol.setSpacing(8)

        ol.addWidget(self._label("搜索引擎"))
        self.engine_combo = QtWidgets.QComboBox()
        # ⚠️ 默认策略下，下拉框会被左栏宽度压窄，
        #    「自动（按权重依次尝试）」末尾的字会被裁掉（实测差 9px）。
        #    这里按最长的条目文字实测宽度定最小宽度（见 _fit_engine_combo）。
        ol.addWidget(self.engine_combo)

        self.refresh_check = QtWidgets.QCheckBox("重新搜索（忽略图库缓存）")
        self.refresh_check.setToolTip("勾选后会联网重新搜索，消耗搜索配额")
        ol.addWidget(self.refresh_check)

        ol.addWidget(self._label("最低相似度（留空用各引擎自己的阈值）"))
        self.min_sim = QtWidgets.QSpinBox()
        self.min_sim.setRange(-1, 100)
        self.min_sim.setSpecialValueText("默认")
        self.min_sim.setValue(-1)
        ol.addWidget(self.min_sim)
        ll.addWidget(opts)

        self.search_btn = QtWidgets.QPushButton("开始搜索")
        self.search_btn.setObjectName("Primary")
        self.search_btn.clicked.connect(lambda: self.start_search(self._image_path))
        self.search_btn.setEnabled(False)
        ll.addWidget(self.search_btn)

        ll.addStretch(1)
        body.addWidget(left)

        # ── 右栏 ──
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        # 状态条
        status = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("等待图片…")
        self.status.setObjectName("PageHint")
        status.addWidget(self.status, 1)

        self.copy_btn = QtWidgets.QPushButton("复制全部链接")
        self.copy_btn.clicked.connect(self._copy_urls)
        self.copy_btn.setEnabled(False)
        status.addWidget(self.copy_btn)

        self.export_btn = QtWidgets.QPushButton("导出结果…")
        self.export_btn.setToolTip("勾选多种格式一次产出（URL 列表 / CSV / JSON / HTML 报告）")
        self.export_btn.clicked.connect(self._export_results)
        self.export_btn.setEnabled(False)
        status.addWidget(self.export_btn)

        self.open_btn = QtWidgets.QPushButton("打开选中链接")
        self.open_btn.clicked.connect(self._open_selected)
        self.open_btn.setEnabled(False)
        status.addWidget(self.open_btn)
        rl.addLayout(status)

        self.table = ResultTable()
        self.table.itemSelectionChanged.connect(
            lambda: self.open_btn.setEnabled(bool(self.table.selectedItems()))
        )
        rl.addWidget(self.table, 1)

        # 日志（引擎的实时进度）
        log_head = QtWidgets.QHBoxLayout()
        log_head.addWidget(self._label("搜索过程"))
        log_head.addStretch(1)
        self.log_toggle = QtWidgets.QToolButton()
        self.log_toggle.setText("展开")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        log_head.addWidget(self.log_toggle)
        rl.addLayout(log_head)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName("LogView")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(0)
        self.log.setVisible(False)
        rl.addWidget(self.log)

        body.addWidget(right, 1)
        self.reload_engines()

    # ── 小工具 ──────────────────────────────────

    @staticmethod
    def _label(text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("SectionHint")
        return lbl

    def _toggle_log(self, on: bool) -> None:
        self.log.setVisible(on)
        self.log.setFixedHeight(160 if on else 0)
        self.log_toggle.setText("收起" if on else "展开")

    def reload_engines(self) -> None:
        """引擎列表变化后刷新下拉框"""
        current = self.engine_combo.currentData()
        self.engine_combo.clear()
        self.engine_combo.addItem("自动（按权重依次尝试）", "auto")
        for ec in get_store().list_all():
            mark = "" if ec.enabled else "（已禁用）"
            self.engine_combo.addItem(f"{ec.display_name} {mark}".strip(), ec.name)
        # 还原选择
        if current:
            idx = self.engine_combo.findData(current)
            if idx >= 0:
                self.engine_combo.setCurrentIndex(idx)
        self._fit_engine_combo()

    def _fit_engine_combo(self) -> None:
        """
        让引擎下拉框至少能装下最长的那条文字。

        单纯调 setSizeAdjustPolicy 不行：它的 sizeHint 只按「字符数」估，
        而中文是宽字符，估出来偏小（实测要 235px，估成 146px）。
        """
        fm = self.engine_combo.fontMetrics()
        widths = [fm.horizontalAdvance(self.engine_combo.itemText(i))
                  for i in range(self.engine_combo.count())]
        if not widths:
            return
        need = max(widths) + 44          # +44：下拉箭头、内边距、边框
        self.engine_combo.setMinimumWidth(max(need, 180))

    # ── 选图 ────────────────────────────────────

    def _pick_file(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(IMAGE_SUFFIXES))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择图片", "", f"图片 ({patterns});;所有文件 (*)"
        )
        if path:
            self.start_search(path)

    def _set_preview(self, path: str) -> None:
        self._image_path = path
        self.search_btn.setEnabled(True)
        p = Path(path)
        self.file_label.setText(f"{p.name}\n{p.parent}")

        pix = QtGui.QPixmap(path)
        if pix.isNull():
            self.preview.setText("无法预览此文件")
            self.preview.setPixmap(QtGui.QPixmap())
            return
        scaled = pix.scaled(PREVIEW_W, 300, QtCore.Qt.KeepAspectRatio,
                            QtCore.Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)
        self.preview.setText("")
        self.preview.setToolTip(f"{pix.width()}×{pix.height()}")

    # ── 搜索 ────────────────────────────────────

    def start_search(self, path: str) -> None:
        if not path:
            return
        if self._worker is not None:
            QtWidgets.QMessageBox.information(self, "请稍候", "已有搜索在进行中。")
            return

        self._set_preview(path)
        self.table.set_results([])
        self.copy_btn.setEnabled(False)
        self.status.setText("正在搜索…")
        self.status.setStyleSheet(f"color:{style.MUTED};")
        self.log.clear()
        self._append_log(f"开始搜索：{path}")

        min_sim = self.min_sim.value()
        worker = SearchWorker(
            path,
            engine=self.engine_combo.currentData() or "auto",
            refresh=self.refresh_check.isChecked(),
            min_similarity=None if min_sim < 0 else min_sim,
        )
        worker.progress.connect(self._append_log)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker

        self.search_btn.setEnabled(False)
        self.drop.set_busy(True, Path(path).name)
        worker.start()

    def _append_log(self, line: str) -> None:
        if not line.strip():
            return
        self.log.appendPlainText(line)

    def _on_done(self, outcome) -> None:
        self._last_outcome = outcome
        self.table.set_results(outcome.results)
        self.copy_btn.setEnabled(bool(outcome.results))
        self.export_btn.setEnabled(bool(outcome.results))

        if outcome.from_cache:
            self.status.setText(
                f"📚 图库命中（{outcome.match_kind}）· 结果来自缓存，未消耗搜索配额"
            )
            self.status.setStyleSheet(f"color:{style.OK}; font-weight:600;")
        elif outcome.results:
            top = outcome.results[0]
            self.status.setText(
                f"✅ 找到 {len(outcome.results)} 条结果"
                f"（最佳：{top.source} {top.similarity:.1f}%）"
                + ("　已记入图库" if outcome.record_id else "")
            )
            self.status.setStyleSheet(f"color:{style.OK}; font-weight:600;")
        else:
            self.status.setText("未找到匹配结果")
            self.status.setStyleSheet(f"color:{style.WARN}; font-weight:600;")

    def _on_failed(self, message: str) -> None:
        self.status.setText("搜索失败 —— 详见下方过程日志")
        self.status.setStyleSheet(f"color:{style.ERR}; font-weight:600;")
        self._toggle_log(True)
        self.log_toggle.setChecked(True)

    def _on_finished(self) -> None:
        self._worker = None
        self.search_btn.setEnabled(bool(self._image_path))
        self.drop.set_busy(False)

    def _export_results(self) -> None:
        """把当前结果导出成多种格式"""
        outcome = self._last_outcome
        if outcome is None or not outcome.results:
            return
        from imgsearch.exporters import from_results
        from imgsearch_gui.dialogs.export_dialog import ExportDialog

        records = from_results(outcome.results, file=self._image_path,
                              dhash=outcome.dhash,
                              from_cache=outcome.from_cache)
        ExportDialog(records, self, title="导出搜索结果").exec()

    # ── 结果操作 ────────────────────────────────

    def _copy_urls(self) -> None:
        urls = self.table.urls()
        if not urls:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(urls))
        self.status.setText(f"已复制 {len(urls)} 条链接到剪贴板")

    def _open_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        for row in sorted(rows):
            item = self.table.item(row, 6)
            if item and item.text():
                from imgsearch_gui.shell_open import open_url
                open_url(item.text())
