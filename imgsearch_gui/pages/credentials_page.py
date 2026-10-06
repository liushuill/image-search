"""
凭据页

**凭据只在这里填写**：填完保存，程序负责写进 ``.env`` 并设成 600。
你不需要打开或手动编辑那个文件。

为什么引擎页不再提供凭据输入框：过去那里也能改 api_key，值会写进
``config.json`` —— 而那个文件是**入库**的，等于把密钥写回版本历史；
更麻烦的是引擎级的值优先于 ``.env``，于是「凭据页显示的值」和
「实际生效的值」可能不是同一个。现在凭据只有 ``.env`` 一个落点。

清单来自「引擎 schema ∪ 已知清单」，因此自定义引擎声明的凭据会自动出现。
"""

import os
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch import secrets
from imgsearch.service import declared_secrets
from imgsearch_gui import style

# 已知凭据的友好文案与获取入口（其余由引擎 schema 的 help 兜底）
# ⚠️ 这里**只放界面专属的信息**（获取地址）——名称、说明、是否必填
# 一律来自引擎 schema（见 service.declared_secrets）。
# 同一个事实写两处会立刻分叉：之前就出现过凭据页显示「可选」
# 而引擎 required=True 的情况，用户照着跳过然后撞报错。
LINKS = {
    "SAUCENAO_KEY": "https://saucenao.com/user.php?page=account",
    "DANBOORU_API_KEY": "https://danbooru.donmai.us/profile",
}


class CredentialRow(QtWidgets.QFrame):
    """一条凭据：标题 + 当前状态 + 输入框 + 操作"""

    changed = QtCore.Signal()

    def __init__(self, name: str, title: str = "", desc: str = "",
                 required: bool = False, mask: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.name = name
        # mask=False 的值（如用户名）明文显示 —— 打码后没法核对有没有打错
        self.mask = mask
        # 名称与说明来自引擎 schema；链接是界面专属信息
        title = title or name
        link = LINKS.get(name, "")
        self.title = title

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(title)
        lbl.setObjectName("SectionTitle")
        head.addWidget(lbl)

        # 必填与否必须看得见 —— 否则用户会跳过必填项然后撞上运行时报错
        badge = QtWidgets.QLabel("必填" if required else "可选")
        badge.setObjectName("FieldHelp")
        badge.setStyleSheet(
            f"color:{style.WARN if required else style.MUTED};"
        )
        head.addWidget(badge)

        env_lbl = QtWidgets.QLabel(f"（.env 变量名：{name}）")
        env_lbl.setObjectName("FieldHelp")
        head.addWidget(env_lbl)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("FieldHelp")
        head.addWidget(self.status)
        head.addStretch(1)
        lay.addLayout(head)

        if desc:
            d = QtWidgets.QLabel(desc)
            d.setObjectName("FieldHelp")
            d.setWordWrap(True)
            lay.addWidget(d)

        if link:
            a = QtWidgets.QLabel(f'<a href="{link}">获取地址：{link}</a>')
            a.setObjectName("FieldHelp")
            a.setOpenExternalLinks(True)
            a.setWordWrap(True)
            lay.addWidget(a)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit.setPlaceholderText("在此粘贴，保存后会写入 .env（权限 600）")
        self.edit.textChanged.connect(lambda _: self.changed.emit())
        row.addWidget(self.edit, 1)

        self.reveal = QtWidgets.QToolButton()
        self.reveal.setText("显示")
        self.reveal.setCheckable(True)
        self.reveal.setCursor(QtCore.Qt.PointingHandCursor)

        def _toggle(on: bool) -> None:
            self.edit.setEchoMode(QtWidgets.QLineEdit.Normal if on
                                  else QtWidgets.QLineEdit.Password)
            self.reveal.setText("隐藏" if on else "显示")

        self.reveal.toggled.connect(_toggle)
        row.addWidget(self.reveal)

        self.clear_btn = QtWidgets.QPushButton("清除")
        self.clear_btn.setObjectName("Danger")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)

        if link:
            open_btn = QtWidgets.QPushButton("获取")
            open_btn.setToolTip(link)
            open_btn.clicked.connect(
                lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(link))
            )
            row.addWidget(open_btn)

        lay.addLayout(row)
        self.refresh_status()

    # ── 状态 ────────────────────────────────────

    def current_source(self) -> str:
        """这个凭据的值来自哪里（真实环境变量优先于 .env）"""
        if os.environ.get(self.name):
            return "环境变量"
        if secrets.load().get(self.name):
            return ".env"
        return ""

    def refresh_status(self) -> None:
        source = self.current_source()
        if secrets.is_set(self.name):
            shown = secrets.masked(self.name) if self.mask \
                else (secrets.get(self.name) or "")
            self.status.setText(f"　✅ 已设置（{source}）：{shown}")
            self.status.setStyleSheet(f"color:{style.OK};")
        else:
            self.status.setText("　✗ 未设置")
            self.status.setStyleSheet(f"color:{style.MUTED};")

    def pending_value(self) -> str:
        return self.edit.text().strip()

    def _clear(self) -> None:
        self.edit.clear()
        if secrets.unset(self.name):
            self.refresh_status()
            self.changed.emit()


class CredentialsPage(QtWidgets.QWidget):
    """凭据管理（写入 .env）"""

    saved = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        title = QtWidgets.QLabel("凭据")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        hint = QtWidgets.QLabel(
            "凭据只在这里填写 —— 保存后程序会写进 .env 并设为仅自己可读（600），"
            "你不需要打开或手动编辑那个文件。\n"
            "引擎页的凭据字段是只读的：那里只显示「有没有、值是什么（脱敏）」，"
            "避免同一个密钥出现两个来源、彼此不一致。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 文件位置与权限（让「东西存哪了」一眼可见）──
        info = QtWidgets.QFrame()
        info.setObjectName("Card")
        il = QtWidgets.QHBoxLayout(info)
        il.setContentsMargins(14, 10, 14, 10)
        self.path_label = QtWidgets.QLabel()
        self.path_label.setObjectName("FieldHelp")
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        il.addWidget(self.path_label, 1)

        reveal_btn = QtWidgets.QPushButton("打开所在目录")
        reveal_btn.clicked.connect(self._reveal)
        il.addWidget(reveal_btn)

        refresh_btn = QtWidgets.QPushButton("重新读取")
        refresh_btn.clicked.connect(self.reload)
        il.addWidget(refresh_btn)
        outer.addWidget(info)

        # ── 凭据行容器（单独一个盒子，便于整块重建）──
        self.rows_box = QtWidgets.QWidget()
        self.rows_layout = QtWidgets.QVBoxLayout(self.rows_box)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)
        outer.addWidget(self.rows_box)

        outer.addStretch(1)

        # ── 保存条 ──
        bar = QtWidgets.QHBoxLayout()
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("FieldHelp")
        self.message.setWordWrap(True)
        bar.addWidget(self.message, 1)

        self.save_btn = QtWidgets.QPushButton("保存凭据")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        outer.addLayout(bar)

        self.rows = {}
        self.rebuild()

    # ── 构建 ────────────────────────────────────

    def rebuild(self) -> None:
        """
        按当前凭据清单重建所有行。

        引擎页新增带凭据的自定义引擎后，这里要能看到它 ——
        所以清单每次都重新算。
        """
        secrets.invalidate_cache()
        specs = declared_secrets()
        wanted = [c.env_name for c in specs]
        if wanted == list(self.rows.keys()):
            self.reload()
            return

        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.rows = {}
        for spec in specs:
            row = CredentialRow(spec.env_name, title=spec.title,
                                desc=spec.description,
                                required=spec.required, mask=spec.mask)
            row.changed.connect(self._update_save_state)
            self.rows[spec.env_name] = row
            self.rows_layout.addWidget(row)
        self.reload()

    # ── 读取 / 保存 ─────────────────────────────

    def reload(self) -> None:
        secrets.invalidate_cache()
        for row in self.rows.values():
            row.edit.clear()
            row.refresh_status()
        self._update_info()
        self._update_save_state()

    def _update_info(self) -> None:
        path = Path(secrets.ENV_FILE)
        note, needs_attention = secrets.permission_status()
        mark = "⚠️ " if needs_attention else ""
        self.path_label.setText(f"凭据文件：{path}\n{mark}{note}")
        self.path_label.setStyleSheet(
            f"color:{style.WARN if needs_attention else style.MUTED};"
        )

    def _update_save_state(self) -> None:
        pending = [r for r in self.rows.values() if r.pending_value()]
        self.save_btn.setEnabled(bool(pending))
        if pending:
            self.message.setStyleSheet(f"color:{style.MUTED};")
            self.message.setText(
                f"待保存 {len(pending)} 项：" + "、".join(r.title for r in pending)
            )
        else:
            self.message.setText("")

    def save(self) -> None:
        changed = []
        for row in self.rows.values():
            value = row.pending_value()
            if not value:
                continue
            try:
                secrets.set(row.name, value)
            except Exception as e:                        # noqa: BLE001
                self.message.setStyleSheet(f"color:{style.ERR};")
                self.message.setText(f"❌ 保存 {row.title} 失败：{e}")
                return
            changed.append(row.name)

        secrets.invalidate_cache()
        for row in self.rows.values():
            row.edit.clear()
            row.refresh_status()
        self._update_info()
        self._update_save_state()

        self.message.setStyleSheet(f"color:{style.OK};")
        titles = [self.rows[n].title for n in changed if n in self.rows]
        self.message.setText(
            "✅ 已保存：" + "、".join(titles)
            + f"　（写入 {secrets.ENV_FILE}，权限 600）"
        )
        self.saved.emit()

    def _reveal(self) -> None:
        path = Path(secrets.ENV_FILE)
        target = path.parent if path.parent.is_dir() else Path.home()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(target)))

    def showEvent(self, event) -> None:          # noqa: D102
        super().showEvent(event)
        self.rebuild()
