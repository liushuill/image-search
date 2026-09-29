"""
设置页

放应用级配置 —— 之前这些只能通过 CLI 的 ``config set`` 改，
界面上没有任何入口（比如代理地址）。
"""

from PySide6 import QtCore, QtWidgets

from imgsearch.config import DB_PATH, THUMBS_DIR, get, load_config, save_configs
from imgsearch_gui import style
from imgsearch_gui.workers import ProxyProbe

# Clash Verge / mihomo 的常见本机端口（写进占位符，省得每次想）
PROXY_HINT = "http://127.0.0.1:7897"


class SettingsPage(QtWidgets.QWidget):
    """应用设置"""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe: ProxyProbe | None = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("设置")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch(1)
        reload_btn = QtWidgets.QPushButton("重新读取")
        reload_btn.clicked.connect(self.reload)
        head.addWidget(reload_btn)
        outer.addLayout(head)

        hint = QtWidgets.QLabel(
            "应用级配置。引擎各自的代理策略在「引擎」页里设（auto / 强制走 / 强制不走）。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 网络 ──
        net = self._card("网络 / 代理")
        lay = net.layout()

        self.proxy_edit = QtWidgets.QLineEdit()
        self.proxy_edit.setPlaceholderText(PROXY_HINT)
        lay.addWidget(self._label("代理地址（留空 = 不使用代理）"))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.proxy_edit, 1)
        self.probe_btn = QtWidgets.QPushButton("测试代理")
        self.probe_btn.clicked.connect(self._test_proxy)
        row.addWidget(self.probe_btn)
        lay.addLayout(row)

        note = QtWidgets.QLabel(
            f"本机 Clash Verge / mihomo 常见端口是 {PROXY_HINT}。"
            "代理**不是常开**也没关系：探测不通时程序会自动降级为直连，"
            "只影响本次运行、不会改这里的配置。"
        )
        note.setObjectName("FieldHelp")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.check_url_edit = QtWidgets.QLineEdit()
        self.check_url_edit.setPlaceholderText("https://www.google.com/generate_204")
        lay.addWidget(self._label("代理探活地址"))
        lay.addWidget(self.check_url_edit)
        cnote = QtWidgets.QLabel(
            "默认用 Google 的 generate_204：只有「能经代理访问到墙外」才说明代理真的有用。"
        )
        cnote.setObjectName("FieldHelp")
        cnote.setWordWrap(True)
        lay.addWidget(cnote)

        self.proxy_result = QtWidgets.QLabel()
        self.proxy_result.setObjectName("FieldHelp")
        self.proxy_result.setWordWrap(True)
        lay.addWidget(self.proxy_result)
        outer.addWidget(net)

        # ── 本地图库 ──
        lib = self._card("本地图库")
        llay = lib.layout()

        self.use_library = QtWidgets.QCheckBox("搜索前先查图库缓存，搜索后自动记入")
        self.use_library.setToolTip(
            "图库以图片内容（dHash）识别，因此文件换了位置也能命中。"
            "命中时直接复用缓存结果，不消耗搜索配额。"
        )
        llay.addWidget(self.use_library)

        self.cache_thumbs = QtWidgets.QCheckBox("为已入库的图片生成缩略图缓存")
        self.cache_thumbs.setToolTip(
            "缩略图按内容存放，用于预览与报告。可在「清理」页单独清掉这一类。"
        )
        llay.addWidget(self.cache_thumbs)

        paths = QtWidgets.QLabel(
            f"数据库：{DB_PATH}\n缩略图目录：{THUMBS_DIR}"
        )
        paths.setObjectName("FieldHelp")
        paths.setWordWrap(True)
        paths.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        llay.addWidget(paths)
        # ⚠️ 必须挂进布局：否则局部变量 lib 出了作用域就被 GC，
        # 它里面的复选框会变成「已删除的 C++ 对象」，点保存直接崩。
        outer.addWidget(lib)

        # ── 保存条 ──
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("FieldHelp")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        outer.addStretch(1)

        bar = QtWidgets.QHBoxLayout()
        bar.addStretch(1)
        self.save_btn = QtWidgets.QPushButton("保存设置")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        outer.addLayout(bar)

        self.reload()

    # ── 小工具 ──────────────────────────────────

    @staticmethod
    def _label(text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    @staticmethod
    def _card(title: str) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        t = QtWidgets.QLabel(title)
        t.setObjectName("SectionTitle")
        lay.addWidget(t)
        return card

    # ── 读取 / 保存 ─────────────────────────────

    def reload(self) -> None:
        load_config()
        self.proxy_edit.setText(str(get("proxy", "") or ""))
        self.check_url_edit.setText(str(get("proxy_check_url", "") or ""))
        self.use_library.setChecked(bool(get("use_library", True)))
        self.cache_thumbs.setChecked(bool(get("cache_thumbnails", True)))
        self.message.setText("")
        self.proxy_result.setText("")

    def save(self) -> None:
        save_configs(
            proxy=self.proxy_edit.text().strip(),
            proxy_check_url=self.check_url_edit.text().strip()
            or "https://www.google.com/generate_204",
            use_library=self.use_library.isChecked(),
            cache_thumbnails=self.cache_thumbs.isChecked(),
        )
        self.message.setStyleSheet(f"color:{style.OK};")
        self.message.setText("✅ 已保存。引擎页的「代理」下拉会按新的全局设置生效。")
        self.changed.emit()

    # ── 测试代理 ────────────────────────────────

    def _test_proxy(self) -> None:
        if self._probe is not None:
            return
        self.probe_btn.setEnabled(False)
        self.proxy_result.setStyleSheet(f"color:{style.MUTED};")
        self.proxy_result.setText("正在探测…")

        # 用界面上当前填的值测（不必先保存），更符合直觉
        probe = ProxyProbe(self.proxy_edit.text(), self.check_url_edit.text())
        probe.done.connect(self._on_probe)
        probe.finished.connect(probe.deleteLater)
        self._probe = probe
        probe.start()

    def _on_probe(self, ok: bool, message: str) -> None:
        self.proxy_result.setStyleSheet(
            f"color:{style.OK if ok else style.WARN};"
        )
        self.proxy_result.setText(("✅ " if ok else "⚠️ ") + message)
        self.probe_btn.setEnabled(True)
        self._probe = None

    def showEvent(self, event) -> None:          # noqa: D102
        super().showEvent(event)
        self.reload()
