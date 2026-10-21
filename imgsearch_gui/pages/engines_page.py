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
    secret_requested = QtCore.Signal(str)     # 请求跳到「凭据」页填写某个凭据

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = get_store()
        self._current: str = ""
        self._form: SchemaForm | None = None
        self._probe: ProbeWorker | None = None
        # 有未保存修改时为 True；切换引擎或切换页面都会先问一句
        self._dirty = False
        # 程序性改动列表/选中时置位，避免把「我们自己造成的选中变化」当成用户操作
        self._loading = False

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

        self.usage_label = QtWidgets.QLabel()
        self.usage_label.setObjectName("FieldHelp")
        self.usage_label.setWordWrap(True)
        self.usage_label.setVisible(False)
        rl.addWidget(self.usage_label)

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

        bar.addStretch(1)

        self.dirty_label = QtWidgets.QLabel()
        self.dirty_label.setObjectName("FieldHelp")
        bar.addWidget(self.dirty_label)

        self.save_btn = QtWidgets.QPushButton("保存")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(lambda: self._save())
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
        self._loading = True
        self.list.clear()
        for ec in self.store.list_all():
            item = QtWidgets.QListWidgetItem(self._label_for(ec))
            item.setData(QtCore.Qt.UserRole, ec.name)
            if not ec.enabled:
                item.setForeground(QtGui.QColor(style.MUTED))
            self.list.addItem(item)

        # 选中原来那个（或第一个）
        try:
            for i in range(self.list.count()):
                if self.list.item(i).data(QtCore.Qt.UserRole) == target:
                    self.list.setCurrentRow(i)
                    break
            else:
                if self.list.count():
                    self.list.setCurrentRow(0)
        finally:
            self._loading = False

        # ⚠️ 上面用 _loading 挡住了「选中变化」事件，否则会被当成用户切换而弹窗。
        # 代价是初次加载也不会触发 _on_select，所以这里**必须显式加载一次**，
        # 否则引擎页打开时右侧是空的。
        item = self.list.currentItem()
        if item is not None:
            self._load_detail(item.data(QtCore.Qt.UserRole))
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
        if current is None or self._loading:
            return
        name = current.data(QtCore.Qt.UserRole)
        if name == self._current:
            return

        if self._dirty and not self._confirm_leave():
            # 用户选了「取消」 → 把选中项退回原来那个（用 _loading 防止递归）
            self._loading = True
            try:
                for i in range(self.list.count()):
                    if self.list.item(i).data(QtCore.Qt.UserRole) == self._current:
                        self.list.setCurrentRow(i)
                        break
            finally:
                self._loading = False
            return

        self._load_detail(name)

    # ── 未保存修改的守卫 ────────────────────────

    def can_leave(self) -> bool:
        """
        页面切换前的钩子（由 MainWindow 调用）。

        Returns:
            True 表示可以离开
        """
        return self._confirm_leave()

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True
        self.dirty_label.setText("● 有未保存的修改")
        self.dirty_label.setStyleSheet(f"color:{style.WARN};")

    def _clear_dirty(self) -> None:
        self._dirty = False
        self.dirty_label.setText("")

    def _confirm_leave(self) -> bool:
        """
        有未保存修改时问一句：保存 / 丢弃修改 / 取消（返回修改）。

        「取消」= 不离开，让用户接着改 —— 这是三者里唯一不会丢数据的出口，
        所以它必须存在（只给「保存/丢弃」会逼用户在没想好时二选一）。
        """
        if not self._dirty:
            return True

        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle("有未保存的修改")
        box.setText(f"「{self._current}」的配置已改动，但还没保存。")
        box.setInformativeText("离开前要先保存吗？")
        btn_save = box.addButton("保存", QtWidgets.QMessageBox.AcceptRole)
        btn_discard = box.addButton("丢弃修改", QtWidgets.QMessageBox.DestructiveRole)
        box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()

        clicked = box.clickedButton()
        if clicked is btn_save:
            # 保存失败（校验不过）时留在原地继续改
            return self._save(quiet=True)
        if clicked is btn_discard:
            self._clear_dirty()
            return True
        return False

    def _clear_detail(self) -> None:
        self._current = ""
        self.detail_head.setText("没有可配置的引擎")
        self.detail_meta.setText("")
        self.usage_label.setText("")
        self.usage_label.setVisible(False)
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
        # 凭据需求（统一模板里每个引擎都必须声明 AUTH_MODE）
        # ⚠️ 用 auth_mode_for(配置)：适配器的凭据需求由实例配置决定，
        # 读类属性会把 danbooru（basic）显示成「无需凭据」
        mode = cls.auth_mode_for(ec.settings) if cls is not None else ""
        if mode:
            bits.append("凭据：" + {"required": "必须", "optional": "可选",
                                    "none": "无需"}.get(mode, mode))
        if not ec.is_builtin:
            bits.append(f"模块：{ec.module_path or '(未设置)'}::{ec.class_name or '(未设置)'}")
        if cls is None:
            bits.append("⚠️ 引擎类当前无法解析，下列为已保存的值")
        self.detail_meta.setText("　·　".join(bits))

        # 使用须知单独一行：它通常较长，混在「·」分隔的一行里会读不动。
        # 用 ec.usage_note —— 配置预设（danbooru）的注意事项在预设里，
        # 而不在它现在用的适配器类上
        usage = ec.usage_note
        self.usage_label.setText(f"ℹ️ {usage}" if usage else "")
        self.usage_label.setVisible(bool(usage))

        form = SchemaForm(ec.schema(), ec.settings, engine_name=ec.name)
        form.changed.connect(self._mark_dirty)
        form.secret_requested.connect(self.secret_requested)
        self._set_form(form)
        self._clear_dirty()
        self.save_btn.setEnabled(True)
        self.test_btn.setEnabled(True)

    def _save(self, quiet: bool = False) -> bool:
        """
        保存当前表单。

        Returns:
            True 表示保存成功。失败时错误已显示在表单顶部，调用方应留在原地。
        """
        if self._form is None or not self._current:
            return False
        self._form.clear_error()
        values = self._form.values()
        try:
            self.store.update(self._current, **values)
        except ConfigError as e:
            # store 已做类型转换与校验，这里只负责把话讲清楚
            self._form.show_error(str(e))
            return False
        except Exception as e:                            # noqa: BLE001
            self._form.show_error(f"保存失败：{e}")
            return False
        self._clear_dirty()
        self.changed.emit()
        if not quiet:
            self.refresh(keep=self._current)
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "已保存")
        return True

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
