"""
引擎配置页

左边是引擎列表（含「为什么不能用」的提示），右边是按各引擎自己的
CONFIG_SCHEMA 自动生成的配置表单 —— 新增引擎不用改这里一行代码。

「测试」按钮做的是**不消耗搜索配额**的检查：配置自检 + 端点连通性。
"""

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch.engines.registry import resolve_engine_class
from imgsearch.engines.schema import ConfigError
from imgsearch.engines.store import get_store
from imgsearch import secrets
from imgsearch_gui import style
from imgsearch_gui.widgets.schema_form import SchemaForm
from imgsearch_gui.workers import ProbeWorker


class EnginesPage(QtWidgets.QWidget):
    """搜索引擎配置"""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = get_store()
        self._current: str = ""
        self._form: SchemaForm | None = None
        self._probe: ProbeWorker | None = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("搜索引擎")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch(1)

        for text, slot in (("添加自定义引擎", self._add_engine),
                           ("生成模板", self._scaffold),
                           ("恢复默认", self._reset)):
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(slot)
            head.addWidget(btn)
        outer.addLayout(head)

        hint = QtWidgets.QLabel(
            "按权重从上到下依次尝试，第一个达到该引擎相似度阈值的即被采用。"
            "「测试」只做配置自检与端点连通性检查，不会消耗搜索配额。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer.addWidget(split, 1)

        # ── 左：列表 ──
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("Card")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)

        ops = QtWidgets.QHBoxLayout()
        for text, slot, tip in (
            ("启用 / 禁用", self._toggle, "关闭后按顺序搜索时会跳过它"),
            ("上移", lambda: self._move(-1), "提高权重（更早被尝试）"),
            ("下移", lambda: self._move(1), "降低权重"),
            ("重命名", self._rename, "改名会保留顺序与模块绑定"),
            ("删除", self._remove, "内置引擎不可删除，只能禁用"),
        ):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            if tip:
                b.setToolTip(tip)
            ops.addWidget(b)
        ll.addLayout(ops)
        split.addWidget(left)

        # ── 右：详情 ──
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        self.detail_head = QtWidgets.QLabel("请选择左侧的引擎")
        self.detail_head.setObjectName("PageTitle")
        rl.addWidget(self.detail_head)

        self.detail_meta = QtWidgets.QLabel()
        self.detail_meta.setObjectName("FieldHelp")
        self.detail_meta.setWordWrap(True)
        rl.addWidget(self.detail_meta)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.form_host = QtWidgets.QWidget()
        self.form_layout = QtWidgets.QVBoxLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 0, 8, 0)
        self.scroll.setWidget(self.form_host)
        rl.addWidget(self.scroll, 1)

        # 测试结果
        self.probe_view = QtWidgets.QPlainTextEdit()
        self.probe_view.setObjectName("LogView")
        self.probe_view.setReadOnly(True)
        self.probe_view.setFixedHeight(120)
        self.probe_view.setVisible(False)
        rl.addWidget(self.probe_view)

        bar = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("测试该引擎")
        self.test_btn.clicked.connect(self._test)
        bar.addWidget(self.test_btn)

        self.revert_btn = QtWidgets.QPushButton("放弃修改")
        self.revert_btn.clicked.connect(lambda: self._load_detail(self._current))
        bar.addWidget(self.revert_btn)
        bar.addStretch(1)

        self.save_btn = QtWidgets.QPushButton("保存")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save)
        bar.addWidget(self.save_btn)
        rl.addLayout(bar)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 5)

        self.refresh()

    # ── 列表 ────────────────────────────────────

    def refresh(self, keep: str = "") -> None:
        self.store = get_store(refresh=True)
        target = keep or self._current
        self.list.clear()
        for ec in self.store.list_all():
            item = QtWidgets.QListWidgetItem(self._label_for(ec))
            item.setData(QtCore.Qt.UserRole, ec.name)
            if not ec.enabled:
                item.setForeground(QtGui.QColor(style.MUTED))
            self.list.addItem(item)

        # 选中原来那个（或第一个）
        for i in range(self.list.count()):
            if self.list.item(i).data(QtCore.Qt.UserRole) == target:
                self.list.setCurrentRow(i)
                return
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._clear_detail()

    def _label_for(self, ec) -> str:
        icon = "●" if ec.enabled else "○"
        note = self._note_for(ec)
        text = f"{icon}  #{ec.priority}  {ec.display_name}"
        return f"{text}    {note}" if note else text

    def _note_for(self, ec) -> str:
        """把「为什么不能用」直接摆出来，不等搜索时才报错"""
        if not ec.enabled:
            return ""
        if resolve_engine_class(ec) is None:
            if not ec.is_builtin and not (ec.module_path and ec.class_name):
                return "⚠️ 未绑定模块"
            return "⚠️ 引擎类无法解析"
        missing = []
        for f in ec.schema():
            if f.key in ("enabled", "priority"):
                continue
            value = ec.get(f.key, f.default)
            if isinstance(value, str):
                value = value.strip()
            if value:
                continue
            if f.env_var and secrets.is_set(f.env_var):
                continue
            if f.required or f.env_var:
                missing.append(f.label)
        return f"⚠️ 缺少 {', '.join(missing)}" if missing else ""

    def _on_select(self, current, _previous) -> None:
        if current is None:
            return
        self._load_detail(current.data(QtCore.Qt.UserRole))

    def _clear_detail(self) -> None:
        self._current = ""
        self.detail_head.setText("没有可配置的引擎")
        self.detail_meta.setText("")
        self._set_form(None)
        self.save_btn.setEnabled(False)
        self.test_btn.setEnabled(False)

    def _set_form(self, form) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._form = form
        if form is not None:
            self.form_layout.addWidget(form)

    # ── 详情 ────────────────────────────────────

    def _load_detail(self, name: str) -> None:
        ec = self.store.get(name)
        if ec is None:
            self._clear_detail()
            return
        self._current = name
        self.probe_view.setVisible(False)

        cls = resolve_engine_class(ec)
        self.detail_head.setText(ec.display_name)

        bits = [
            f"配置名：{ec.name}",
            f"权重：#{ec.priority}",
            "类型：" + ("内置" if ec.is_builtin else "自定义"),
            "状态：" + ("已启用" if ec.enabled else "已禁用"),
        ]
        if not ec.is_builtin:
            bits.append(f"模块：{ec.module_path or '(未设置)'}::{ec.class_name or '(未设置)'}")
        if cls is None:
            bits.append("⚠️ 引擎类当前无法解析，下列为已保存的值")
        self.detail_meta.setText("　·　".join(bits))

        form = SchemaForm(ec.schema(), ec.settings)
        self._set_form(form)
        self.save_btn.setEnabled(True)
        self.test_btn.setEnabled(True)

    def _save(self) -> None:
        if self._form is None or not self._current:
            return
        self._form.clear_error()
        values = self._form.values()
        try:
            self.store.update(self._current, **values)
        except ConfigError as e:
            # store 已做类型转换与校验，这里只负责把话讲清楚
            self._form.show_error(str(e))
            return
        except Exception as e:                            # noqa: BLE001
            self._form.show_error(f"保存失败：{e}")
            return
        self.changed.emit()
        self.refresh(keep=self._current)
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "已保存")

    # ── 操作 ────────────────────────────────────

    def _toggle(self) -> None:
        if not self._current:
            return
        self.store.toggle(self._current)
        self.changed.emit()
        self.refresh(keep=self._current)

    def _move(self, delta: int) -> None:
        if not self._current:
            return
        if not self.store.move(self._current, delta):
            return
        self.changed.emit()
        self.refresh(keep=self._current)

    def _rename(self) -> None:
        if not self._current:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "重命名引擎", "新名称：", text=self._current
        )
        if not ok or not new_name.strip():
            return
        try:
            self.store.rename(self._current, new_name.strip())
        except ConfigError as e:
            QtWidgets.QMessageBox.warning(self, "无法重命名", str(e))
            return
        self.changed.emit()
        self.refresh(keep=new_name.strip())

    def _remove(self) -> None:
        if not self._current:
            return
        ec = self.store.get(self._current)
        if ec is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "删除引擎",
            f"确定删除「{ec.display_name}」？\n（内置引擎不可删除，只能禁用）",
        ) != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.store.remove(self._current)
        except ConfigError as e:
            QtWidgets.QMessageBox.warning(self, "无法删除", str(e))
            return
        self._current = ""
        self.changed.emit()
        self.refresh()

    def _add_engine(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "添加引擎", "引擎名称（配置名）：")
        if not ok or not name.strip():
            return
        name = name.strip()
        module, ok2 = QtWidgets.QInputDialog.getText(
            self, "添加引擎",
            "模块路径（内置引擎留空即可；自定义引擎如 my_engines.mysite）：",
        )
        class_name = ""
        if ok2 and module.strip():
            class_name, _ = QtWidgets.QInputDialog.getText(
                self, "添加引擎", "类名（如 Mysite）："
            )
        try:
            self.store.add(name, module_path=module.strip(), class_name=class_name.strip())
        except ConfigError as e:
            QtWidgets.QMessageBox.warning(self, "无法添加", str(e))
            return
        self.changed.emit()
        self.refresh(keep=name)

    def _scaffold(self) -> None:
        """生成自定义引擎模板：加引擎 = 写一个文件"""
        name, ok = QtWidgets.QInputDialog.getText(
            self, "生成自定义引擎模板", "引擎名称（英文，如 mysite）："
        )
        if not ok or not name.strip():
            return
        from imgsearch.cli import _scaffold_custom_engine
        try:
            _scaffold_custom_engine(name.strip())
        except SystemExit:
            pass
        QtWidgets.QMessageBox.information(
            self, "已生成模板",
            "模板已生成到 my_engines/ 下。\n"
            "实现 search() 后，用「添加自定义引擎」把它登记进来即可。",
        )

    def _reset(self) -> None:
        if QtWidgets.QMessageBox.question(
            self, "恢复默认",
            "恢复默认引擎列表？自定义引擎会被清除（图库数据不受影响）。",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self.store.reset()
        self._current = ""
        self.changed.emit()
        self.refresh()

    # ── 测试 ────────────────────────────────────

    def _test(self) -> None:
        if not self._current or self._probe is not None:
            return
        self.probe_view.setVisible(True)
        self.probe_view.setPlainText(f"正在检查「{self._current}」…\n")
        self.test_btn.setEnabled(False)

        worker = ProbeWorker(self._current)
        worker.done.connect(self._on_probe)
        worker.finished.connect(worker.deleteLater)
        self._probe = worker
        worker.start()

    def _on_probe(self, checks) -> None:
        lines = []
        for ok, text in checks:
            lines.append(("  ✅ " if ok else "  ❌ ") + text)
        self.probe_view.setPlainText("\n".join(lines))
        # 全部通过时移除「正在探测」那行
        self.test_btn.setEnabled(True)
        self._probe = None
