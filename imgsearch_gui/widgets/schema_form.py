"""
Schema 驱动的配置表单

**这是「加一个引擎不用改界面」的关键**：字段、类型、默认值、说明、单位、
可选值全部读自引擎声明的 ``CONFIG_SCHEMA``，界面按类型自动选控件：

    bool   → 复选框          int / float → 数字框（带上下限）
    secret → 密码框 + .env 回退提示
    kv     → key=value 文本域（复用 schema 的解析）
    choices→ 下拉框          其余 → 单行输入

保存时不在这里做类型转换 —— 一律交给 ``EngineStore.update()``，
它按 schema 转换并校验，保证界面与 CLI 走的是同一套规则。
"""

from typing import Any, Dict

from PySide6 import QtCore, QtWidgets

from imgsearch import secrets
from imgsearch.engines.schema import (
    BOOL, FLOAT, INT, KV, SECRET, TEXT, env_var_for,
)
from imgsearch_gui import style


class SchemaForm(QtWidgets.QWidget):
    """
    按 schema 生成引擎配置表单。

    ⚠️ **凭据字段在这里是只读的**：只显示「当前从哪读到、值是什么（脱敏）」，
    并给一个跳转到「凭据」页的按钮。

    原因：引擎页曾允许直接编辑 api_key，值会写进 config.json ——
    而那个文件是**入库**的，等于把密钥写回版本历史；更糟的是引擎级的值
    优先于 .env，于是「凭据页显示的值」和「实际生效的值」可能不是同一个。
    凭据只应有 .env 一个落点。
    """

    changed = QtCore.Signal()
    secret_requested = QtCore.Signal(str)      # 环境变量名 → 请求跳去凭据页

    def __init__(self, schema, settings: Dict[str, Any], engine_name: str = "",
                 parent=None):
        super().__init__(parent)
        self.schema = schema
        self.engine_name = engine_name
        self._widgets: Dict[str, QtWidgets.QWidget] = {}
        self._rows: Dict[str, QtWidgets.QWidget] = {}      # 键 → 该字段的整行容器
        self._labels: Dict[str, str] = {}

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # 顶部错误横幅（保存失败时显示）
        self._banner = QtWidgets.QLabel()
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)
        self._banner.setStyleSheet(
            f"background:#fef2f2; color:{style.ERR}; border:1px solid #fecaca;"
            "border-radius:6px; padding:8px 10px;"
        )
        outer.addWidget(self._banner)

        basic = QtWidgets.QWidget()
        basic_lay = QtWidgets.QVBoxLayout(basic)
        basic_lay.setContentsMargins(0, 0, 0, 0)
        basic_lay.setSpacing(14)
        outer.addWidget(basic)

        advanced_box = QtWidgets.QGroupBox("高级设置")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        adv_lay = QtWidgets.QVBoxLayout(advanced_box)
        adv_lay.setSpacing(14)
        outer.addWidget(advanced_box)

        has_advanced = False
        for f in schema:
            if f.key in ("enabled", "priority"):
                continue
            target = adv_lay if f.advanced else basic_lay
            if f.advanced:
                has_advanced = True
            target.addWidget(self._build_row(f, settings.get(f.key, f.default)))
        advanced_box.setVisible(has_advanced)
        outer.addStretch(1)

    # ── 构建单个字段 ────────────────────────────

    def _build_row(self, f, value) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        label = QtWidgets.QLabel(f.label + (f"（{f.unit}）" if f.unit else ""))
        label.setObjectName("SectionTitle")
        lay.addWidget(label)

        widget = self._build_widget(f, value)
        lay.addWidget(widget)

        if f.help:
            help_lbl = QtWidgets.QLabel(f.help)
            help_lbl.setObjectName("FieldHelp")
            help_lbl.setWordWrap(True)
            lay.addWidget(help_lbl)

        # 敏感字段：把「留空会回退到哪里」明确写出来，避免用户以为没生效
        if f.is_secret:
            hint = QtWidgets.QLabel()
            hint.setObjectName("FieldHelp")
            hint.setWordWrap(True)
            if f.env_var:
                if secrets.is_set(f.env_var):
                    hint.setText(f"留空则使用 .env 中的 {f.env_var}"
                                 f"（当前：{secrets.masked(f.env_var)}）")
                else:
                    hint.setText(f"留空则尝试读取 .env 中的 {f.env_var}（尚未设置）")
            lay.addWidget(hint)

        self._widgets[f.key] = widget
        self._rows[f.key] = row
        self._labels[f.key] = f.label
        return row

    def _build_widget(self, f, value) -> QtWidgets.QWidget:
        if f.type == BOOL:
            w = QtWidgets.QCheckBox("启用")
            w.setChecked(bool(value))
            w.toggled.connect(self.changed)
            return w

        if f.choices:
            w = QtWidgets.QComboBox()
            w.addItems(list(f.choices))
            if value in f.choices:
                w.setCurrentText(str(value))
            w.currentTextChanged.connect(self.changed)
            return w

        if f.type == INT:
            w = QtWidgets.QSpinBox()
            w.setRange(int(f.minimum if f.minimum is not None else -2_000_000_000),
                       int(f.maximum if f.maximum is not None else 2_000_000_000))
            try:
                w.setValue(int(value))
            except (TypeError, ValueError):
                pass
            w.valueChanged.connect(self.changed)
            return w

        if f.type == FLOAT:
            w = QtWidgets.QDoubleSpinBox()
            w.setDecimals(2)
            w.setSingleStep(0.5)
            w.setRange(float(f.minimum if f.minimum is not None else -1e9),
                       float(f.maximum if f.maximum is not None else 1e9))
            try:
                w.setValue(float(value))
            except (TypeError, ValueError):
                pass
            w.valueChanged.connect(self.changed)
            return w

        if f.type == KV:
            w = QtWidgets.QPlainTextEdit()
            w.setPlaceholderText("每行一条：key=value")
            w.setFixedHeight(84)
            if isinstance(value, dict):
                w.setPlainText("\n".join(f"{k}={v}" for k, v in value.items()))
            elif value:
                w.setPlainText(str(value))
            w.textChanged.connect(self.changed)
            return w

        if f.type == SECRET:
            # 只读：凭据只在「凭据」页维护，落点是 .env
            holder = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(holder)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)

            env_name = env_var_for(self.engine_name, f)
            status = QtWidgets.QLabel()
            status.setObjectName("FieldHelp")
            if secrets.is_set(env_name):
                source = (".env" if secrets.load().get(env_name) else "环境变量")
                status.setText(f"✅ 已配置（{source}）：{secrets.masked(env_name)}")
                status.setStyleSheet(f"color:{style.OK};")
            else:
                status.setText(f"✗ 未配置（.env 的 {env_name} 为空）")
                status.setStyleSheet(f"color:{style.MUTED};")
            h.addWidget(status, 1)

            go = QtWidgets.QPushButton("去「凭据」页填写")
            go.clicked.connect(lambda: self.secret_requested.emit(env_name))
            h.addWidget(go)
            return holder

        # STR / TEXT
        if f.type == TEXT:
            w = QtWidgets.QPlainTextEdit()
            w.setFixedHeight(72)
            w.setPlainText(str(value or ""))
            w.textChanged.connect(self.changed)
            return w

        w = QtWidgets.QLineEdit(str(value if value is not None else ""))
        if f.placeholder:
            w.setPlaceholderText(f.placeholder)
        w.textChanged.connect(self.changed)
        return w

    # ── 取值 ────────────────────────────────────

    def values(self) -> Dict[str, Any]:
        """
        收集当前界面上的值（不做类型转换，交给 EngineStore.update）。

        凭据字段**不在其中** —— 它们由「凭据」页写入 .env，
        引擎页既不读也不写，避免出现两个真值来源。
        """
        out: Dict[str, Any] = {}
        for key, w in self._widgets.items():
            f = self.schema.get(key)
            if f is not None and f.is_secret:
                continue
            if isinstance(w, QtWidgets.QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QtWidgets.QComboBox):
                out[key] = w.currentText()
            elif isinstance(w, QtWidgets.QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                out[key] = w.value()
            elif isinstance(w, QtWidgets.QPlainTextEdit):
                out[key] = w.toPlainText()
            elif isinstance(w, QtWidgets.QLineEdit):
                out[key] = w.text()
            elif hasattr(w, "value_widget"):
                out[key] = w.value_widget.text()      # type: ignore[attr-defined]
        return out

    def reset_to(self, settings: Dict[str, Any]) -> None:
        """用给定配置重填表单"""
        self.clear_error()
        for key, w in self._widgets.items():
            f = self.schema.get(key)
            if f is not None and f.is_secret:
                continue
            v = settings.get(key, "")
            if isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QtWidgets.QComboBox):
                if v in [w.itemText(i) for i in range(w.count())]:
                    w.setCurrentText(str(v))
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                try:
                    w.setValue(type(w.value())(v or 0))
                except (TypeError, ValueError):
                    pass
            elif isinstance(w, QtWidgets.QPlainTextEdit):
                w.setPlainText("\n".join(f"{k}={val}" for k, val in v.items())
                               if isinstance(v, dict) else str(v or ""))
            elif isinstance(w, QtWidgets.QLineEdit):
                w.setText(str(v if v is not None else ""))
            elif hasattr(w, "value_widget"):
                w.value_widget.setText(str(v or ""))  # type: ignore[attr-defined]

    # ── 错误显示 ────────────────────────────────

    def show_error(self, message: str) -> None:
        """显示错误；若消息里提到某个字段，顺带高亮那一行"""
        self._banner.setText(message)
        self._banner.setVisible(True)
        for key, label in self._labels.items():
            if label and label in message:
                self._highlight(self._rows[key])
                break

    def clear_error(self) -> None:
        # 隐藏不够：文字留着会让下一次 show_error 之前的读取拿到旧内容
        self._banner.setText("")
        self._banner.setVisible(False)
        for row in self._rows.values():
            row.setStyleSheet("")

    @staticmethod
    def _highlight(row: QtWidgets.QWidget) -> None:
        row.setStyleSheet(
            "background:#fffbeb; border:1px solid #fde68a; border-radius:6px;"
        )
