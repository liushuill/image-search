"""界面配色与样式表"""

# ── 配色 ──────────────────────────────────────
BG = "#f9fafb"
CARD = "#ffffff"
SIDEBAR_BG = "#1f2937"
SIDEBAR_TEXT = "#e5e7eb"
SIDEBAR_MUTED = "#9ca3af"
ACCENT = "#3b82f6"
ACCENT_DARK = "#2563eb"
OK = "#16a34a"
WARN = "#d97706"
ERR = "#dc2626"
TEXT = "#111827"
MUTED = "#6b7280"
BORDER = "#e5e7eb"
HOVER = "#f3f4f6"

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}

/* ── 侧栏 ── */
#Sidebar {{
    background: {SIDEBAR_BG};
    border: none;
}}
#SidebarTitle {{
    color: #ffffff;
    font-size: 15px;
    font-weight: 600;
    padding: 18px 16px 6px 16px;
    background: transparent;
}}
#SidebarSubtitle {{
    color: {SIDEBAR_MUTED};
    font-size: 11px;
    padding: 0 16px 14px 16px;
    background: transparent;
}}
#NavButton {{
    background: transparent;
    color: {SIDEBAR_TEXT};
    border: none;
    border-left: 3px solid transparent;
    padding: 11px 16px;
    text-align: left;
    font-size: 13px;
}}
#NavButton:hover {{
    background: rgba(255, 255, 255, 0.07);
}}
#NavButton:checked {{
    background: rgba(59, 130, 246, 0.18);
    border-left: 3px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
#SidebarFoot {{
    color: {SIDEBAR_MUTED};
    font-size: 11px;
    padding: 8px 16px 14px 16px;
    background: transparent;
}}

/* ── 卡片 ── */
#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#PageTitle {{
    font-size: 19px;
    font-weight: 600;
    padding: 2px 0 2px 0;
    background: transparent;
}}
#PageHint {{
    color: {MUTED};
    font-size: 12px;
    background: transparent;
}}
#SectionTitle {{
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#FieldHelp {{
    color: {MUTED};
    font-size: 11px;
    background: transparent;
}}
#SectionHint {{
    color: {MUTED};
    font-size: 11px;
    background: transparent;
}}

/* ── 按钮 ── */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:disabled {{ color: #9ca3af; background: {BG}; }}
QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#Primary:disabled {{ background: #93c5fd; border-color: #93c5fd; }}
QPushButton#Danger {{ color: {ERR}; }}
QPushButton#Danger:hover {{ background: #fef2f2; }}

/* ── 输入 ── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {BG};
    color: {MUTED};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QCheckBox {{ spacing: 8px; background: transparent; }}

/* ── 表格 ── */
QTableWidget, QTableView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    selection-background-color: #dbeafe;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {BG};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 5px 6px; }}

/* ── 拖拽区 ── */
#DropArea {{
    background: {CARD};
    border: 2px dashed {BORDER};
    border-radius: 10px;
}}
#DropAreaActive {{
    background: #eff6ff;
    border: 2px dashed {ACCENT};
    border-radius: 10px;
}}
#DropTitle {{ font-size: 14px; font-weight: 600; background: transparent; }}
#DropHint {{ color: {MUTED}; font-size: 12px; background: transparent; }}

/* ── 日志 ── */
#LogView {{
    background: #0f172a;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 6px;
}}

/* ── 标签页 ── */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background: {CARD}; }}
QTabBar::tab {{
    background: transparent; border: none; padding: 7px 14px; color: {MUTED};
}}
QTabBar::tab:selected {{ color: {TEXT}; font-weight: 600;
    border-bottom: 2px solid {ACCENT}; }}

/* ── 滚动条 ── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #cbd5e1; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #cbd5e1; border-radius: 5px; min-width: 28px; }}

/* ── 状态条 ── */
#StatusBar {{ background: {CARD}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
#StatusOK {{ color: {OK}; font-weight: 600; background: transparent; }}
#StatusWarn {{ color: {WARN}; font-weight: 600; background: transparent; }}
#StatusErr {{ color: {ERR}; font-weight: 600; background: transparent; }}

QToolTip {{
    background: #111827; color: #f9fafb;
    border: none; padding: 5px 7px; border-radius: 4px;
}}
"""
