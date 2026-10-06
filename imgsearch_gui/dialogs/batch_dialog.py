"""
批量识别对话框

流程刻意分成两步：**先预览（零消耗）再确认开始**。
因为一次批量会真的花掉每日搜索额度，用户应该先看到"要处理多少、还剩多少额度"。
"""

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from imgsearch.batch import DEFAULT_QUOTA_POLICY, plan_batch
from imgsearch.config import get
from imgsearch_gui.workers import BatchWorker

_STATUS_TEXT = {
    "cached": "♻️ 命中缓存",
    "success": "✅ 已识别",
    "no_match": "❔ 未找到",
    "error": "⚠️ 失败",
}


class BatchDialog(QtWidgets.QDialog):
    """批量识别一个目录里的图片"""

    def __init__(self, directory: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量识别")
        self.setMinimumWidth(680)
        self.directory = directory
        self._worker: BatchWorker | None = None
        self.report = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(12)

        head = QtWidgets.QLabel("把整个目录里的图逐个识别出来")
        head.setObjectName("SectionTitle")
        outer.addWidget(head)

        # ⚠️ 用 HTML 而不是 Markdown：QLabel 不渲染 **粗体**，
        # 那样会原样显示星号。setText 含标签时会自动按富文本处理。
        hint = QtWidgets.QLabel(
            "会<b>先查缓存</b>：已识别过的图直接跳过、不消耗配额。<br>"
            "因此随时中断都可以，分几天跑也行 —— 下次会自动接着跑。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 预览（零消耗）──
        plan_box = QtWidgets.QGroupBox("预览（尚未消耗任何配额）")
        pl = QtWidgets.QVBoxLayout(plan_box)
        self.plan_label = QtWidgets.QLabel("正在统计…")
        self.plan_label.setObjectName("FieldHelp")
        self.plan_label.setWordWrap(True)
        self.plan_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        pl.addWidget(self.plan_label)
        outer.addWidget(plan_box)

        # ── 选项 ──
        opt = QtWidgets.QGroupBox("本次选项")
        form = QtWidgets.QFormLayout(opt)

        self.limit = QtWidgets.QSpinBox()
        self.limit.setRange(0, 1000000)
        self.limit.setSpecialValueText("不限")
        self.limit.setSuffix(" 张")
        self.limit.setValue(int(get("batch_limit", 20) or 0))
        self.limit.setToolTip("一次最多识别多少张。先跑少量试水更稳妥。")
        form.addRow("本次最多识别", self.limit)

        self.policy = QtWidgets.QComboBox()
        self.policy.addItem("额度用尽就停下（推荐）", "stop")
        self.policy.addItem("继续用其他引擎（质量可能下降）", "fallback")
        saved = str(get("batch_quota_policy", DEFAULT_QUOTA_POLICY) or "stop")
        idx = self.policy.findData(saved)
        self.policy.setCurrentIndex(idx if idx >= 0 else 0)
        self.policy.setToolTip(
            "默认值可在「设置」页修改。\n"
            "额度按引擎各自计算（SauceNAO 免费版 100 次/天）。"
        )
        form.addRow("额度用尽时", self.policy)

        self.recursive = QtWidgets.QCheckBox("包含子目录")
        self.recursive.setChecked(bool(get("batch_recursive", True)))
        form.addRow("", self.recursive)

        pace = QtWidgets.QLabel(
            "为避免触发短期速率限制（SauceNAO 4 次/30 秒）而被降级，<br>"
            "识别会按引擎的速率<b>逐张节流</b>，因此速度不会很快。"
        )
        pace.setObjectName("FieldHelp")
        pace.setWordWrap(True)
        form.addRow("", pace)
        outer.addWidget(opt)

        # ── 进度 ──
        self.bar = QtWidgets.QProgressBar()
        self.bar.setValue(0)
        outer.addWidget(self.bar)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName("LogView")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        outer.addWidget(self.log)

        bar = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("重新预览")
        self.preview_btn.clicked.connect(self.refresh_plan)
        bar.addWidget(self.preview_btn)
        bar.addStretch(1)

        self.close_btn = QtWidgets.QPushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        bar.addWidget(self.close_btn)

        self.start_btn = QtWidgets.QPushButton("开始识别")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start)
        bar.addWidget(self.start_btn)
        outer.addLayout(bar)

        self.refresh_plan()

    # ── 预览 ────────────────────────────────────

    def refresh_plan(self) -> None:
        if self._worker is not None:
            return
        try:
            plan = plan_batch(self.directory, recursive=self.recursive.isChecked(),
                              limit=self.limit.value() or None)
        except NotADirectoryError as e:
            self.plan_label.setText(f"❌ {e}")
            self.start_btn.setEnabled(False)
            return

        lines = [f"目录：{plan.directory}",
                 f"找到图片 <b>{plan.total}</b> 张"
                 + ("（含子目录）" if plan.recursive else "（仅当前目录）")]
        if plan.selected != plan.total:
            lines.append(f"本次计划处理 <b>{plan.selected}</b> 张")
        lines.extend(plan.quota_notes)
        self.plan_label.setText("<br>".join(lines))
        self.start_btn.setEnabled(plan.total > 0 and plan.selected > 0)
        if plan.total == 0:
            self.plan_label.setText(self.plan_label.text() + "\n（目录里没有图片）")

    # ── 执行 ────────────────────────────────────

    def _start(self) -> None:
        if self._worker is not None:
            return
        limit = self.limit.value() or None

        self.log.clear()
        self.bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.limit.setEnabled(False)
        self.policy.setEnabled(False)
        self.recursive.setEnabled(False)
        self.log.appendPlainText(f"开始识别：{self.directory}")

        worker = BatchWorker(
            self.directory,
            recursive=self.recursive.isChecked(),
            limit=limit,
            policy=self.policy.currentData() or "stop",
        )
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

        # 运行期间「关闭」变成「取消」
        self.close_btn.setText("取消")
        try:
            self.close_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.close_btn.clicked.connect(self._cancel)

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.log.appendPlainText("⏹ 正在停止…（等待当前这张结束）")
        else:
            self.reject()

    def _on_progress(self, item) -> None:
        self.bar.setValue(item.percent)
        name = Path(item.path).name
        text = _STATUS_TEXT.get(item.status, item.status)
        extra = f"　{item.engine}" if item.engine else ""
        note = f"　{item.message}" if item.message and item.status != "success" else ""
        self.log.appendPlainText(f"[{item.index}/{item.total}] {text}　{name}{extra}{note}")

    def _on_done(self, report) -> None:
        self.report = report
        self.bar.setValue(100)
        self.log.appendPlainText("")
        self.log.appendPlainText(report.summary())

    def _on_failed(self, message: str) -> None:
        self.log.appendPlainText(f"❌ 批量识别失败：{message}")

    def _on_finished(self) -> None:
        self._worker = None
        self.limit.setEnabled(True)
        self.policy.setEnabled(True)
        self.recursive.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.close_btn.setText("关闭")
        try:
            self.close_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.close_btn.clicked.connect(self.reject)

    def reject(self) -> None:  # noqa: D102
        # 正在跑就先请求停止，别让窗口直接消失把线程丢下
        if self._worker is not None:
            self._cancel()
            return
        super().reject()
