"""
主窗口：左侧导航 + 右侧页面
"""

from PySide6 import QtCore, QtWidgets

from imgsearch import secrets
from imgsearch.engines.store import get_store
from imgsearch_gui.pages.credentials_page import CredentialsPage
from imgsearch_gui.pages.engines_page import EnginesPage
from imgsearch_gui.pages.search_page import SearchPage


class NavButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAutoExclusive(True)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("image-search · 二次元图片溯源")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 侧栏 ──
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(196)
        sl = QtWidgets.QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        t = QtWidgets.QLabel("image-search")
        t.setObjectName("SidebarTitle")
        sl.addWidget(t)
        st = QtWidgets.QLabel("二次元图片溯源")
        st.setObjectName("SidebarSubtitle")
        sl.addWidget(st)

        self.pages = QtWidgets.QStackedWidget()
        self._navs = []

        specs = [
            ("搜索", SearchPage, True),
            ("引擎", EnginesPage, True),
            ("凭据", CredentialsPage, True),
            ("图库", None, False),
            ("清理", None, False),
        ]
        for index, (name, cls, enabled) in enumerate(specs):
            btn = NavButton(name)
            if enabled:
                page = cls()
                self.pages.addWidget(page)
                btn.clicked.connect(lambda _=False, i=index: self.pages.setCurrentIndex(i))
            else:
                btn.setEnabled(False)
                btn.setToolTip("下一轮实现")
                btn.setText(f"{name}（即将推出）")
            sl.addWidget(btn)
            self._navs.append(btn)

        sl.addStretch(1)

        self.sidebar_foot = QtWidgets.QLabel()
        self.sidebar_foot.setObjectName("SidebarFoot")
        self.sidebar_foot.setWordWrap(True)
        sl.addWidget(self.sidebar_foot)

        root.addWidget(sidebar)

        # ── 内容区 ──
        content = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(content)
        cl.setContentsMargins(18, 14, 18, 12)
        cl.setSpacing(0)
        cl.addWidget(self.pages, 1)
        root.addWidget(content, 1)

        # ── 底部状态条 ──
        bar = QtWidgets.QStatusBar()
        bar.setObjectName("StatusBar")
        self.setStatusBar(bar)
        self._status_label = QtWidgets.QLabel()
        bar.addPermanentWidget(self._status_label)

        # 页面联动：引擎/凭据变化后刷新搜索页与状态条
        self.engines_page = self.pages.widget(1)
        self.credentials_page = self.pages.widget(2)
        self.search_page = self.pages.widget(0)
        self.engines_page.changed.connect(self._on_config_changed)
        self.credentials_page.saved.connect(self._on_config_changed)

        self._navs[0].setChecked(True)
        self.refresh_status()

    # ── 状态 ────────────────────────────────────

    def _on_config_changed(self) -> None:
        self.search_page.reload_engines()
        self.refresh_status()

    def refresh_status(self) -> None:
        store = get_store()
        enabled = [e for e in store.get_enabled()]
        self.sidebar_foot.setText(
            f"已启用 {len(enabled)} 个引擎\n"
            + "\n".join(f"· {e.display_name}" for e in enabled[:6])
        )

        parts = [f"凭据：{'✅ 已配置' if secrets.is_set('SAUCENAO_KEY') else '❌ 未配置'}"]
        try:
            from imgsearch.library import LibraryDB, LibraryStore
            with LibraryDB() as db:
                st = LibraryStore(db)
                parts.append(f"图库：{st.count_images()} 张（已搜 {st.count_resolved()}）")
        except Exception:                                  # noqa: BLE001
            parts.append("图库：不可用")
        from imgsearch.config import get
        proxy = get("proxy", "")
        parts.append(f"代理：{proxy or '未设置'}")
        self._status_label.setText("　|　".join(parts))
