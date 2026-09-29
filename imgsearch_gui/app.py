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
    return app


def main() -> int:
    app = create_app()
    from imgsearch_gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
