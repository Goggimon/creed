import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

GUI_DIR = Path(__file__).resolve().parent
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))

from components.insignia import draw_creed_insignia
from main_window import MainWindow


def build_app_icon() -> QIcon:
    pixmap = QPixmap(256, 256)
    pixmap.fill(QColor("#080B0F"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    draw_creed_insignia(painter, 128, 128, 190, 0.85)
    painter.end()
    return QIcon(pixmap)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CREED")
    app.setApplicationDisplayName("CREED")
    icon = build_app_icon()
    app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
