from __future__ import annotations
from pathlib import Path
from typing import Optional
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QFileDialog,
    QStatusBar, QLabel, QMessageBox
)

from .pdf_document import PdfDocument
from .pdf_viewer import PdfViewer
from .toc_panel import TocPanel
from .page_label_panel import PageLabelPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._doc = PdfDocument()
        self._setup_ui()
        self._setup_menu()
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("mopdf")
        self.resize(1200, 800)
        self.setMinimumSize(QSize(800, 600))

        # 左ペイン: 目次 + ページラベル を縦に分割
        self._toc_panel = TocPanel()
        self._page_label_panel = PageLabelPanel()

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self._toc_panel)
        left_splitter.addWidget(self._page_label_panel)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 1)

        # 右ペイン: PDFビューア
        self._viewer = PdfViewer()
        self._viewer.page_changed.connect(self._on_page_changed)

        # 左右分割
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self._viewer)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([300, 900])

        self.setCentralWidget(main_splitter)

        # ステータスバー
        self._status_label = QLabel("PDFを開いてください")
        statusbar = QStatusBar()
        statusbar.addWidget(self._status_label)
        self.setStatusBar(statusbar)

        # 目次クリック → ページジャンプ
        self._toc_panel.page_jump_requested.connect(self._viewer.scroll_to_page)

    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("ファイル")

        open_action = QAction("開く...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction("終了", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ------------------------------------------------------------------
    # ファイルを開く
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "PDFを開く", "", "PDF Files (*.pdf)"
        )
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            self._doc.open(path)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"PDFを開けませんでした:\n{e}")
            return

        self._viewer.load(self._doc)
        self._toc_panel.load(self._doc)
        self._page_label_panel.load(self._doc)

        filename = Path(path).name
        self.setWindowTitle(f"mopdf — {filename}")
        self._update_status(0)

    # ------------------------------------------------------------------
    # ドラッグ&ドロップ
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.open_pdf(urls[0].toLocalFile())

    # ------------------------------------------------------------------
    # ステータスバー更新
    # ------------------------------------------------------------------

    def _on_page_changed(self, page_index: int) -> None:
        self._update_status(page_index)

    def _update_status(self, page_index: int) -> None:
        if not self._doc.is_open:
            self._status_label.setText("PDFを開いてください")
            return
        label = self._doc.get_page_label_for(page_index)
        total = self._doc.page_count
        self._status_label.setText(
            f"ページ {label}  （{page_index + 1} / {total}）"
        )

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._doc.close()
        super().closeEvent(event)
