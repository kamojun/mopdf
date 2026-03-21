from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QLabel, QSizePolicy, QFrame
)

from .pdf_document import PdfDocument

RENDER_BUFFER = 2  # 表示ページの前後何ページを先読みするか


class PageWidget(QLabel):
    def __init__(self, page_index: int, width: int, height: int) -> None:
        super().__init__()
        self.page_index = page_index
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width, height)
        self.setStyleSheet("background: #e0e0e0; border: 1px solid #ccc; margin: 8px;")


class PdfViewer(QScrollArea):
    page_changed = Signal(int)  # 0-indexed 現在ページ

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._zoom: float = 1.5
        self._page_widgets: list[PageWidget] = []
        self._rendered: set[int] = set()

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet("background: #525659;")

        # スクロール後に少し待ってからレンダリング（連続スクロール中の無駄な描画を防ぐ）
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._render_visible)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._rebuild()

    def clear(self) -> None:
        self._doc = None
        self._clear_pages()

    def scroll_to_page(self, page_index: int) -> None:
        if 0 <= page_index < len(self._page_widgets):
            self.ensureWidgetVisible(self._page_widgets[page_index])

    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._clear_pages()
        if self._doc is None:
            return

        # プレースホルダーを配置（レンダリングなし → 即座に完了）
        for i in range(self._doc.page_count):
            w, h = self._doc.get_page_size(i, self._zoom)
            pw = PageWidget(i, w, h)
            self._layout.addWidget(pw)
            self._page_widgets.append(pw)

        # レイアウト確定後に見えているページをレンダリング
        QTimer.singleShot(0, self._render_visible)

    def _clear_pages(self) -> None:
        for pw in self._page_widgets:
            self._layout.removeWidget(pw)
            pw.deleteLater()
        self._page_widgets.clear()
        self._rendered.clear()

    def _visible_page_range(self) -> tuple[int, int]:
        """現在ビューポートに表示されているページの範囲（バッファ込み）を返す"""
        if not self._page_widgets:
            return (0, 0)
        scroll_top = self.verticalScrollBar().value()
        scroll_bottom = scroll_top + self.viewport().height()

        first = len(self._page_widgets) - 1
        last = 0
        for i, pw in enumerate(self._page_widgets):
            top = pw.pos().y()
            bottom = top + pw.height()
            if bottom >= scroll_top and top <= scroll_bottom:
                first = min(first, i)
                last = max(last, i)

        first = max(0, first - RENDER_BUFFER)
        last = min(len(self._page_widgets) - 1, last + RENDER_BUFFER)
        return (first, last)

    def _render_visible(self) -> None:
        if self._doc is None:
            return
        first, last = self._visible_page_range()
        for i in range(first, last + 1):
            if i not in self._rendered:
                img = self._doc.render_page(i, self._zoom)
                self._page_widgets[i].setPixmap(QPixmap.fromImage(img))
                self._page_widgets[i].setStyleSheet(
                    "background: white; border: 1px solid #ccc; margin: 8px;"
                )
                self._rendered.add(i)

    def _on_scroll(self) -> None:
        self._render_timer.start()
        self._update_current_page()

    def _update_current_page(self) -> None:
        if not self._page_widgets:
            return
        viewport_center_y = self.verticalScrollBar().value() + self.viewport().height() // 2
        best = 0
        for i, pw in enumerate(self._page_widgets):
            widget_center = pw.pos().y() + pw.height() // 2
            if abs(widget_center - viewport_center_y) < abs(
                self._page_widgets[best].pos().y() + self._page_widgets[best].height() // 2 - viewport_center_y
            ):
                best = i
        self.page_changed.emit(best)
