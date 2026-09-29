"""
主窗口：左侧导航 + 右侧页面
"""

from PySide6 import QtCore, QtWidgets

from imgsearch import secrets
from imgsearch.engines.store import get_store
from imgsearch_gui.pages.credentials_page import CredentialsPage
from imgsearch_gui.pages.engines_page import EnginesPage
from imgsearch_gui.pages.cleanup_page import CleanupPage
from imgsearch_gui.pages.library_page import LibraryPage
from imgsearch_gui.pages.search_page import SearchPage
from imgsearch_gui.pages.settings_page import SettingsPage


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
        # 初始尺寸按屏幕可用区域自适应。
        # ⚠️ 写死 1180x760 在 150% 缩放的 1080p 笔记本上会超出屏幕
        # （逻辑可用区只有约 1280x720），底部控件会被挤到屏幕外。
        self._apply_initial_geometry()

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
            ("搜索", SearchPage),
            ("图库", LibraryPage),
            ("清理", CleanupPage),
            ("引擎", EnginesPage),
            ("凭据", CredentialsPage),
            ("设置", SettingsPage),
        ]
        for index, (name, cls) in enumerate(specs):
            page = cls()
            self.pages.addWidget(page)
            btn = NavButton(name)
            # ⚠️ 不直接 setCurrentIndex：先问当前页面「能离开吗」
            # （引擎页有未保存修改时会弹保存/丢弃/取消）
            btn.clicked.connect(lambda _=False, i=index: self.go_to(i))
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

        # 页面联动
        self.search_page = self.pages.widget(0)
        self.library_page = self.pages.widget(1)
        self.cleanup_page = self.pages.widget(2)
        self.engines_page = self.pages.widget(3)
        self.credentials_page = self.pages.widget(4)
        self.settings_page = self.pages.widget(5)

        # 引擎/凭据/设置变化 → 刷新搜索页的引擎下拉与状态条
        self.engines_page.changed.connect(self._on_config_changed)
        self.credentials_page.saved.connect(self._on_credentials_changed)
        self.settings_page.changed.connect(self._on_config_changed)
        # 图库/清理互相影响（清掉数据后统计要跟着变）
        self.library_page.changed.connect(self._on_library_changed)
        self.cleanup_page.changed.connect(self._on_library_changed)
        # 引擎页的只读凭据字段可以一键跳到凭据页
        self.engines_page.secret_requested.connect(self._goto_credentials)

        self._navs[0].setChecked(True)
        self.refresh_status()

    # ── 窗口几何 ────────────────────────────────

    # 偏好的初始尺寸与最小尺寸（放不下时会自动让步，见下）
    _PREFERRED_SIZE = (1180, 760)
    _PREFERRED_MIN = (820, 560)

    def _apply_initial_geometry(self) -> None:
        """
        按屏幕可用区域挑一个放得下的初始尺寸，调整最小尺寸并居中。

        ⚠️ 写死 1180x760 在 150% 缩放的 1080p 笔记本上会超出可用区
        （逻辑区域只剩约 1280x720），底部按钮会被挤到屏幕外看不见。

        ⚠️ 最小尺寸也要跟着屏幕收窄：否则在小屏上「最小尺寸」本身就比屏幕大，
        窗口必然超出 —— 能不能放下比"保证最小可用尺寸"更重要。
        """
        pref_w, pref_h = self._PREFERRED_SIZE
        pref_min_w, pref_min_h = self._PREFERRED_MIN

        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(pref_min_w, pref_min_h)
            self.resize(pref_w, pref_h)
            return

        available = screen.availableGeometry()
        min_w = min(pref_min_w, available.width())
        min_h = min(pref_min_h, available.height())
        self.setMinimumSize(min_w, min_h)

        width = max(min_w, min(pref_w, available.width() - 40))
        height = max(min_h, min(pref_h, available.height() - 40))
        self.resize(width, height)
        self.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 2),
        )

    # ── 状态 ────────────────────────────────────

    # ── 导航 ────────────────────────────────────

    def go_to(self, index: int) -> None:
        """
        切换页面。

        先问当前页面「能离开吗」—— 引擎页有未保存修改时会弹
        保存 / 丢弃修改 / 取消，选「取消」就留在原地。
        """
        if index == self.pages.currentIndex():
            self._sync_nav(index)
            return
        current = self.pages.currentWidget()
        can_leave = getattr(current, "can_leave", None)
        if callable(can_leave) and not can_leave():
            # 用户选择留下：把导航高亮拨回当前页
            self._sync_nav(self.pages.currentIndex())
            return
        self.pages.setCurrentIndex(index)
        self._sync_nav(index)

    def _sync_nav(self, index: int) -> None:
        for i, btn in enumerate(self._navs):
            btn.setChecked(i == index)

    def _goto_credentials(self, env_name: str = "") -> None:
        """从引擎页跳来填凭据"""
        self.go_to(4)
        row = self.credentials_page.rows.get(env_name)
        if row is not None:
            row.edit.setFocus()

    # ── 联动 ────────────────────────────────────

    def _on_config_changed(self) -> None:
        self.search_page.reload_engines()
        self.refresh_status()

    def _on_credentials_changed(self) -> None:
        # 凭据变了：引擎页那些只读状态（"已配置 / 未配置"）要跟着更新
        self.engines_page.refresh(keep=self.engines_page._current)
        self._on_config_changed()

    def _on_library_changed(self) -> None:
        self.library_page.reload()
        self.cleanup_page.reload()
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
