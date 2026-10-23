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
    /* 布局被挤压时的下限：低于这个高度连文字都画不出来
       （下拉框曾被压到 14px，看起来就是「空的」） */
    min-height: 16px;
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
/* 勾选框：给它**自己的**白底 + 边框，做成一个「可点的控件」
   而不是一行普通文字。
   原因：页面底色是浅灰、卡片是白，勾选框原来透明 —— 放在灰色区域时
   它和描述文字长得一样，看不出「这里能勾」。 */
QToolButton#SectionToggle {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-size: 12px;
    font-weight: 600;
    padding: 2px 0;
}}
QToolButton#SectionToggle:hover {{ color: {TEXT}; }}

QCheckBox {{
    spacing: 8px;
    background: {CARD};
    /* 比卡片边框稍深一档：白底在白卡片上才看得出这是一块「可点的区域」 */
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 5px 10px;
}}
QCheckBox:hover {{ border-color: {ACCENT}; }}
QCheckBox:disabled {{ color: {MUTED}; background: {BG}; border-color: {BORDER}; }}

/* ⚠️ 给 QCheckBox 设了 border 之后，Qt 就**不再画原生指示器**
   （实测：只改 background 还能画，一加 border 就消失，加 padding 更是彻底没有）。
   所以这里必须自己把那个方框画出来，否则未勾选的选项看起来只是一行文字。
   代价：勾选态是「实心蓝方块」而不是对勾 —— 在 QSS 里画对勾需要图片资源。 */
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid #9ca3af;
    border-radius: 3px;
    background: {CARD};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: {BG}; border-color: #d1d5db; }}
QCheckBox::indicator:checked:disabled {{ background: #93c5fd; border-color: #93c5fd; }}

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
