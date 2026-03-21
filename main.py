import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("mopdf")

    window = MainWindow()
    window.show()

    # コマンドライン引数でPDFを直接開く
    if len(sys.argv) > 1:
        window.open_pdf(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
