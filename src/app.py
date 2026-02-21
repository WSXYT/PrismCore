"""应用工厂 — 配置日志并创建主窗口。"""

import sys
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from src.views.main_window import MainWindow
from src.utils.constants import APP_NAME


def setup_logging():
    """初始化日志配置。传入 --debug 启用 DEBUG 级别。"""
    level = logging.DEBUG if "--debug" in sys.argv else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def create_app() -> tuple[QApplication, MainWindow]:
    """创建并配置 QApplication 和主窗口。"""
    setup_logging()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    return app, window
