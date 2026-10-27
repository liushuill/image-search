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

        # 内容放进滚动区：设置项会越加越多，窗口高度不够时
        # 之前会把里面的输入框压扁（下拉框甚至只剩 14px，文字画不出来）。
        # 引擎页早已这么做了，这里保持一致。
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._content = QtWidgets.QWidget()
        content_lay = QtWidgets.QVBoxLayout(self._content)
        content_lay.setContentsMargins(0, 0, 8, 0)
        content_lay.setSpacing(12)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)

        hint = QtWidgets.QLabel(
            "应用级配置。引擎各自的代理策略在「引擎」页里设（auto / 强制走 / 强制不走）。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        content_lay.addWidget(hint)

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
            "代理不是常开也没关系：探测不通时程序会自动降级为直连，"
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
        content_lay.addWidget(net)

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
        content_lay.addWidget(lib)

        # ── 批量识别 ──
        batch = self._card("批量识别")
        blay = batch.layout()

        self.batch_policy = QtWidgets.QComboBox()
        self.batch_policy.addItem("停下来，报告还剩多少（推荐）", "stop")
        self.batch_policy.addItem("继续用其他引擎（结果质量可能下降）", "fallback")
        self.batch_policy.setToolTip(
            "SauceNAO 免费额度是 100 次/天。额度用尽时：\n"
            "· 停下来 —— 不会不知情地拿覆盖较差的引擎凑数，\n"
            "  已识别的都已入库，明天再点一次会自动接着跑\n"
            "· 继续 —— 换用其他引擎把剩下的跑完，\n"
            "  报告里会注明哪些结果来自降级引擎"
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("额度用尽时："))
        row.addWidget(self.batch_policy, 1)
        holder = QtWidgets.QWidget()
        holder.setLayout(row)
        blay.addWidget(holder)

        self.batch_limit = QtWidgets.QSpinBox()
        self.batch_limit.setRange(0, 100000)
        self.batch_limit.setSpecialValueText("不限")
        self.batch_limit.setSuffix(" 张")
        self.batch_limit.setToolTip(
            "一次批量最多识别多少张（0 = 不限）。\n"
            "默认给个安全值，免得手一滑就用光当天全部额度。"
        )
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("单次上限："))
        row2.addWidget(self.batch_limit)
        row2.addStretch(1)
        holder2 = QtWidgets.QWidget()
        holder2.setLayout(row2)
        blay.addWidget(holder2)

        self.batch_recursive = QtWidgets.QCheckBox("包含子目录")
        blay.addWidget(self.batch_recursive)

        self.url_cache_mb = QtWidgets.QSpinBox()
        self.url_cache_mb.setRange(0, 100000)
        self.url_cache_mb.setSpecialValueText("不限制")
        self.url_cache_mb.setSuffix(" MB")
        self.url_cache_mb.setToolTip(
            "图源缩略图缓存的上限（0 = 不限制）。\n"
            "超出后按「最久未用」自动淘汰。\n\n"
            "这是唯一会无界增长的东西：每看一次新图的结果就多几条，"
            "所以默认给 100 MB。\n"
            "也可以在「清理」页手动清空。"
        )
        row3 = QtWidgets.QHBoxLayout()
        row3.addWidget(QtWidgets.QLabel("图源缩略图缓存上限："))
        row3.addWidget(self.url_cache_mb)
        row3.addStretch(1)
        holder3 = QtWidgets.QWidget()
        holder3.setLayout(row3)
        blay.addWidget(holder3)

        note = QtWidgets.QLabel(
            "批量识别会<b>先查缓存</b>：已识别过的图直接跳过、不消耗配额，"
            "因此随时中断、分几天跑都可以。"
        )
        note.setObjectName("FieldHelp")
        note.setWordWrap(True)
        blay.addWidget(note)
        content_lay.addWidget(batch)

        # ── 保存条 ──
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("FieldHelp")
        self.message.setWordWrap(True)
        content_lay.addWidget(self.message)
        content_lay.addStretch(1)

        bar = QtWidgets.QHBoxLayout()
        self.licenses_btn = QtWidgets.QPushButton("第三方许可")
        self.licenses_btn.setToolTip(
            "查看本项目使用的第三方组件及其许可（Qt 为 LGPL-3.0）")
        self.licenses_btn.clicked.connect(self._show_licenses)
        bar.addWidget(self.licenses_btn)
        bar.addStretch(1)
        self.save_btn = QtWidgets.QPushButton("保存设置")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        outer.addLayout(bar)

        self.reload()

    # ── 第三方许可 ──────────────────────────────

    def _show_licenses(self) -> None:
        """
        显示第三方组件许可。

        Qt 用 LGPL-3.0：分发编译产物时必须有「显著告知」——用户需知道
        程序用到了 Qt、且该 Qt 的使用受 LGPL 约束。程序内这个入口就是那条告知。
        """
        from imgsearch.config import APP_DIR

        text = ""
        # 这是**只读资源**，跟着程序走（打包后在 _internal/ 里），
        # 与用户数据目录无关
        for candidate in (APP_DIR / "THIRD_PARTY_NOTICES.md",
                          APP_DIR / "_internal" / "THIRD_PARTY_NOTICES.md"):
            if candidate.is_file():
                try:
                    text = candidate.read_text(encoding="utf-8")
                    break
                except OSError:
                    continue
        if not text:
            text = ("找不到 THIRD_PARTY_NOTICES.md。\n\n"
                    "本项目使用 Qt / PySide6（LGPL-3.0）、Pillow、requests、"
                    "lxml、BeautifulSoup、cloudscraper 等第三方组件，"
                    "许可全文见仓库中的 LICENSES/ 目录。")

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("第三方许可")
        dlg.resize(760, 640)
        lay = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QPlainTextEdit(text)
        view.setReadOnly(True)
        lay.addWidget(view, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        close = QtWidgets.QPushButton("关闭")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

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

        policy = str(get("batch_quota_policy", "stop") or "stop")
        idx = self.batch_policy.findData(policy)
        self.batch_policy.setCurrentIndex(idx if idx >= 0 else 0)
        self.batch_limit.setValue(int(get("batch_limit", 20) or 0))
        self.batch_recursive.setChecked(bool(get("batch_recursive", True)))
        self.url_cache_mb.setValue(int(get("url_thumb_cache_mb", 100) or 0))
        self.message.setText("")
        self.proxy_result.setText("")

    def save(self) -> None:
        save_configs(
            proxy=self.proxy_edit.text().strip(),
            proxy_check_url=self.check_url_edit.text().strip()
            or "https://www.google.com/generate_204",
            use_library=self.use_library.isChecked(),
            cache_thumbnails=self.cache_thumbs.isChecked(),
            batch_quota_policy=self.batch_policy.currentData(),
            batch_limit=self.batch_limit.value(),
            batch_recursive=self.batch_recursive.isChecked(),
            url_thumb_cache_mb=self.url_cache_mb.value(),
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
