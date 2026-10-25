"""
导出对话框

一次勾选多种格式，选定目录与文件名模板，导出后列出产出文件。
它本身不实现任何导出逻辑 —— 全部交给 :mod:`imgsearch.exporters`，
界面只负责收集选择与展示结果。
"""

from pathlib import Path

from PySide6 import QtWidgets

from imgsearch.config import OUTPUT_DIR, get, save_config
from imgsearch.exporters import (
    DEFAULT_NAME_TEMPLATE,
    ExportRecord,
    all_formats,
    format_keys,
)
from imgsearch_gui.workers import ExportWorker

# 首次打开时默认勾这几个（最常用的一组），之后记住用户的选择
DEFAULT_FORMATS = ["urls", "csv", "html"]

PLACEHOLDERS = ("{pixiv_id}", "{page}", "{artist}", "{title}",
                "{similarity}", "{engine}", "{dhash}", "{file}", "{ext}")


class ExportDialog(QtWidgets.QDialog):
    """导出结果（多格式一次产出）"""

    def __init__(self, records, parent=None, *, title: str = "导出结果"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self.records: list[ExportRecord] = list(records)
        self._worker: ExportWorker | None = None
        self.written: list[str] = []

        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(12)

        head = QtWidgets.QLabel(f"共 {len(self.records)} 条记录")
        head.setObjectName("SectionTitle")
        outer.addWidget(head)

        hint = QtWidgets.QLabel(
            "导出的是<b>地址</b>，不含图片文件本身。可同时勾选多种格式，一次产出。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 格式 ──
        fmt_box = QtWidgets.QGroupBox("要产出哪些格式")
        fmt_lay = QtWidgets.QVBoxLayout(fmt_box)
        self._boxes = {}
        saved = get("export_formats", DEFAULT_FORMATS) or DEFAULT_FORMATS
        if isinstance(saved, str):
            saved = [s.strip() for s in saved.split(",") if s.strip()]
        for fmt in all_formats():
            cb = QtWidgets.QCheckBox(f"{fmt.label}　（.{fmt.ext}）"
                                     if not fmt.virtual else f"{fmt.label}")
            cb.setChecked(fmt.key in saved)
            if fmt.help:
                cb.setToolTip(fmt.help)
            cb.toggled.connect(self._update_state)
            fmt_lay.addWidget(cb)
            self._boxes[fmt.key] = cb
        outer.addWidget(fmt_box)

        # ── 输出位置与命名 ──
        opt_box = QtWidgets.QGroupBox("输出")
        form = QtWidgets.QFormLayout(opt_box)

        row = QtWidgets.QHBoxLayout()
        self.outdir_edit = QtWidgets.QLineEdit(
            str(get("export_outdir", "") or OUTPUT_DIR))
        row.addWidget(self.outdir_edit, 1)
        browse = QtWidgets.QPushButton("选择…")
        browse.clicked.connect(self._pick_dir)
        row.addWidget(browse)
        holder = QtWidgets.QWidget()
        holder.setLayout(row)
        form.addRow("输出目录", holder)

        self.template_edit = QtWidgets.QLineEdit(
            str(get("export_name_template", "") or DEFAULT_NAME_TEMPLATE))
        self.template_edit.setToolTip("占位符：" + "  ".join(PLACEHOLDERS))
        form.addRow("文件名模板", self.template_edit)

        ph = QtWidgets.QLabel("可用占位符：" + "  ".join(PLACEHOLDERS))
        ph.setObjectName("FieldHelp")
        ph.setWordWrap(True)
        form.addRow("", ph)

        self.thumb_combo = QtWidgets.QComboBox()
        self.thumb_combo.addItem("内嵌（单文件可离线看，推荐）", "embed")
        self.thumb_combo.addItem("用远程地址（文件更小）", "link")
        self.thumb_combo.addItem("不显示缩略图", "none")
        saved_thumb = str(get("export_thumbnails", "embed") or "embed")
        idx = self.thumb_combo.findData(saved_thumb)
        if idx >= 0:
            self.thumb_combo.setCurrentIndex(idx)
        form.addRow("HTML 报告里的缩略图", self.thumb_combo)
        outer.addWidget(opt_box)

        # ── 进度 / 结果 ──
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName("LogView")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        outer.addWidget(self.log)

        bar = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("打开输出目录")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_outdir)
        bar.addWidget(self.open_btn)
        bar.addStretch(1)

        self.close_btn = QtWidgets.QPushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        bar.addWidget(self.close_btn)

        self.export_btn = QtWidgets.QPushButton("开始导出")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self._run)
        bar.addWidget(self.export_btn)
        outer.addLayout(bar)

        self._update_state()

    # ── 状态 ────────────────────────────────────

    def selected_formats(self) -> list:
        return [k for k, cb in self._boxes.items() if cb.isChecked()]

    def _update_state(self) -> None:
        chosen = self.selected_formats()
        self.export_btn.setEnabled(bool(chosen) and self._worker is None)
        # 只有勾了 HTML 才需要缩略图选项
        self.thumb_combo.setEnabled("html" in chosen)
        if not chosen:
            self.export_btn.setToolTip("请至少勾选一种格式")
        else:
            self.export_btn.setToolTip("")

    def _pick_dir(self) -> None:
        current = self.outdir_edit.text().strip() or str(OUTPUT_DIR)
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择输出目录", current)
        if chosen:
            self.outdir_edit.setText(chosen)

    def _open_outdir(self) -> None:
        # ⚠️ 必须走 shell_open：Windows 上用 file:// URL 打开目录
        # 会 ShellExecute 失败（error 5），os.startfile 才可靠
        from imgsearch_gui.shell_open import open_dir

        target = self.outdir_edit.text().strip() or str(OUTPUT_DIR)
        if not open_dir(target):
            QtWidgets.QMessageBox.information(
                self, "打不开目录", f"目录不存在或无法打开：\n{target}")

    def _remember(self) -> None:
        save_config("export_formats", self.selected_formats())
        save_config("export_outdir", self.outdir_edit.text().strip())
        save_config("export_name_template", self.template_edit.text().strip())
        save_config("export_thumbnails", self.thumb_combo.currentData())

    # ── 执行 ────────────────────────────────────

    def _run(self) -> None:
        if self._worker is not None:
            return
        chosen = self.selected_formats()
        if not chosen:
            return
        self._remember()

        self.written = []
        self.log.clear()
        self.open_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.log.appendPlainText(f"正在导出 {len(self.records)} 条记录…")

        worker = ExportWorker(
            self.records, ",".join(chosen),
            outdir=self.outdir_edit.text().strip() or None,
            name_template=self.template_edit.text().strip(),
            thumbnails=self.thumb_combo.currentData() or "embed",
        )
        worker.progress.connect(self.log.appendPlainText)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def _on_done(self, written, clipboard_text: str) -> None:
        self.written = list(written)
        for path in written:
            try:
                size = Path(path).stat().st_size
                size_text = (f"{size / 1024:.1f} KB" if size < 1024 * 1024
                             else f"{size / 1024 / 1024:.1f} MB")
            except OSError:
                size_text = "?"
            self.log.appendPlainText(f"✅ {path}　（{size_text}）")

        if clipboard_text:
            QtWidgets.QApplication.clipboard().setText(clipboard_text)
            self.log.appendPlainText(
                f"📋 已复制 {len(clipboard_text.splitlines())} 行到剪贴板")

        if not written and not clipboard_text:
            self.log.appendPlainText("（没有产出任何内容）")
        self.open_btn.setEnabled(bool(written))

    def _on_failed(self, message: str) -> None:
        self.log.appendPlainText(f"❌ 导出失败：{message}")
        # 格式名之类的问题，把可用项列出来方便纠正
        self.log.appendPlainText("可用格式：" + ", ".join(format_keys()))

    def _on_finished(self) -> None:
        self._worker = None
        self._update_state()
