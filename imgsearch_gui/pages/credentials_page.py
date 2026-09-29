"""
凭据页

**你不需要打开或编辑 .env**：在这里填，程序负责写进 ``.env`` 并设成 600。

每一栏都会明确告诉你三件事：
  1. 现在到底有没有配上（值一律脱敏显示）
  2. 这个值是从哪来的（真实环境变量 / .env / 配置文件）
  3. 留空时会不会自动回退到别处
"""

import os
import stat
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from imgsearch import secrets
from imgsearch_gui import style

# 每个凭据的展示名与用途说明（名称要和 secrets.KNOWN_SECRETS 对齐）
DISPLAY = {
    "SAUCENAO_KEY": (
        "SauceNAO API Key",
        "SauceNAO 是 Pixiv 覆盖最好的引擎，必填。免费注册后在账号页获取。",
        "https://saucenao.com/user.php?page=account",
    ),
    "DANBOORU_LOGIN": (
        "Danbooru 用户名",
        "Danbooru 引擎需要账号。注意 IQDB 引擎无需账号也能查 Danbooru 的帖子。",
        "https://danbooru.donmai.us/profile",
    ),
    "DANBOORU_API_KEY": (
        "Danbooru API Key",
        "在 Danbooru 个人资料页可以找到。",
        "https://danbooru.donmai.us/profile",
    ),
}


class CredentialRow(QtWidgets.QFrame):
    """一条凭据：标题 + 当前状态 + 输入框 + 操作"""

    changed = QtCore.Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.name = name
        title, desc, link = DISPLAY.get(name, (name, "", ""))

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(title)
        lbl.setObjectName("SectionTitle")
        head.addWidget(lbl)

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
        """这个凭据的值来自哪里"""
        if os.environ.get(self.name):
            return "环境变量"
        if secrets.load().get(self.name):
            return ".env"
        return ""

    def refresh_status(self) -> None:
        source = self.current_source()
        value = secrets.get(self.name)
        if value:
            self.status.setText(f"　✅ 已设置（{source}）：{secrets.masked(self.name)}")
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
    """凭据管理"""

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
            "在这里填写即可 —— 保存后程序会写进 .env 并设为仅自己可读（600）。"
            "你不需要打开或手动编辑那个文件。"
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

        # ── 各凭据 ──
        self.rows = {}
        for name in secrets.KNOWN_SECRETS:
            row = CredentialRow(name)
            row.changed.connect(self._update_save_state)
            self.rows[name] = row
            outer.addWidget(row)

        outer.addStretch(1)

        # ── 保存条 ──
        bar = QtWidgets.QHBoxLayout()
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("FieldHelp")
        bar.addWidget(self.message, 1)

        self.save_btn = QtWidgets.QPushButton("保存凭据")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        outer.addLayout(bar)

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
        if path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
            warn = "" if mode == 0o600 else f"　⚠️ 权限是 {oct(mode)}，应为 0o600"
            self.path_label.setText(f"凭据文件：{path}{warn}")
        else:
            self.path_label.setText(
                f"凭据文件：{path}（尚未创建，保存时会自动生成并设为 600）"
            )

    def _update_save_state(self) -> None:
        pending = [r for r in self.rows.values() if r.pending_value()]
        self.save_btn.setEnabled(bool(pending))
        if pending:
            self.message.setText(
                f"待保存 {len(pending)} 项："
                + "、".join(DISPLAY.get(r.name, (r.name,))[0] for r in pending)
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
                self.message.setText(f"❌ 保存 {row.name} 失败：{e}")
                self.message.setStyleSheet(f"color:{style.ERR};")
                return
            changed.append(row.name)

        secrets.invalidate_cache()
        for row in self.rows.values():
            row.edit.clear()
            row.refresh_status()
        self._update_info()
        self._update_save_state()

        self.message.setStyleSheet(f"color:{style.OK};")
        self.message.setText(
            "✅ 已保存：" + "、".join(DISPLAY.get(n, (n,))[0] for n in changed)
            + f"　（写入 {secrets.ENV_FILE}，权限 600）"
        )
        self.saved.emit()

    def _reveal(self) -> None:
        path = Path(secrets.ENV_FILE)
        target = path.parent if path.parent.is_dir() else Path.home()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(target)))
