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

    wire_quit_cleanup(app)
    return app


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
