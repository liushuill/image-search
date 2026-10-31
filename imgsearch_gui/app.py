"""
GUI 启动入口

    python -m imgsearch_gui
    ./run-gui.sh
"""

import sys
from pathlib import Path

# 允许直接运行（不依赖安装）
_REPO = str(Path(__file__).resolve().parent.parent)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from PySide6 import QtWidgets                          # noqa: E402

from imgsearch_gui import style                        # noqa: E402


def create_app(argv=None) -> QtWidgets.QApplication:
    app = QtWidgets.QApplication(argv or sys.argv)
    app.setApplicationName("image-search")
    app.setApplicationDisplayName("二次元图片溯源")
    app.setOrganizationName("image-search")
    app.setStyle("Fusion")
    app.setStyleSheet(style.QSS)

    from imgsearch_gui.assets import window_icon
    icon = window_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    wire_quit_cleanup(app)
    warn_if_low_integrity()
    return app


def warn_if_low_integrity() -> None:
    """
    启动时检查本进程的完整性级别，Low 就明确警告。

    ⚠️ 这条必须放在 **GUI 进程**里，而不是 bootstrap：实测那次 bootstrap 跑在
    系统 Python（Medium）上，而真正跑界面的 venv python 是 Low —— 放在
    bootstrap 里永远不会触发。

    低完整性（沙箱/受限会话）会带来一串"看起来像代码 bug"的怪象：
    打开文件夹一律 ShellExecute error 5、explorer 子进程 0xC0000142。
    """
    from imgsearch_gui import shell_open

    level = shell_open.process_integrity()
    if level != "Low":
        return
    import sys as _sys
    print(
        "[image-search] ⚠️ 当前进程运行在低完整性（S-1-16-4096）环境中。\n"
        "[image-search]    症状：打开文件夹会失败（ShellExecute error 5），\n"
        "[image-search]          explorer 子进程起不来（0xC0000142）。\n"
        "[image-search]    原因：这个 venv 是在低完整性会话里创建的，\n"
        "[image-search]          或者它所在的**上级目录**带 Low 标签（会被继承）。\n"
        "[image-search]    处理：把项目整个移到普通目录（如 C:\\Users\\你\\image-search）\n"
        "[image-search]          再重建 .venv —— 只删 .venv 不挪目录是不行的。",
        file=_sys.stderr, flush=True)


def wire_quit_cleanup(app: QtWidgets.QApplication) -> None:
    """
    退出前停掉后台缩略图线程。

    ⚠️ QThread 还在跑就被销毁，Qt 会直接 abort 整个进程
    （实测 exit 134 / 核心转储；pytest 里表现为一大段 "Extension modules:"）。
    这个清理以前**只在测试收尾里手动调过**，真实运行时没人接 ——
    关窗口时正好在加载缩略图就会崩。所以这里接到 aboutToQuit 上。
    """
    from imgsearch_gui.widgets.thumbnails import stop_all_loaders

    app.aboutToQuit.connect(stop_all_loaders)


def main() -> int:
    app = create_app()
    from imgsearch_gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
