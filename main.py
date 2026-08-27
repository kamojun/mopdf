import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent
from app.main_window import MainWindow


class Application(QApplication):
    """macOSの「このアプリケーションで開く」/ Finderでのダブルクリックに対応するため、
    QFileOpenEventを捕捉してPDFを開く。"""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.window: MainWindow | None = None

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.FileOpen and self.window is not None:
            self.window.open_pdf(event.file())
            return True
        return super().event(event)


def main() -> None:
    app = Application(sys.argv)
    app.setApplicationName("mopdf")

    window = MainWindow()
    app.window = window
    window.show()

    # コマンドライン引数でPDFを直接開く
    if len(sys.argv) > 1:
        window.open_pdf(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
