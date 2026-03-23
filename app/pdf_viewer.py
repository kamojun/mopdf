from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QPoint
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QCursor, QFont
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QLabel, QSizePolicy, QFrame, QRubberBand
)

from .pdf_document import PdfDocument

RENDER_BUFFER = 2  # 表示ページの前後何ページを先読みするか


class PageWidget(QLabel):
    """1ページ分の表示ウィジェット。テキスト選択モード時はドラッグで矩形選択できる。"""

    text_selected = Signal(str, int)  # (抽出テキスト, 0-indexed page)

    def __init__(self, page_index: int, width: int, height: int,
                 doc: PdfDocument, zoom: float) -> None:
        super().__init__()
        self.page_index = page_index
        self._doc = doc
        self._zoom = zoom
        self._select_mode = False

        self._origin = QPoint()
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width, height)
        self.setStyleSheet("background: #e0e0e0; border: 1px solid #ccc; margin: 8px;")

    def set_select_mode(self, enabled: bool) -> None:
        self._select_mode = enabled
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor))

    def refresh_label(self) -> None:
        self.update()  # type: ignore[misc]

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._doc is None or self.pixmap() is None or self.pixmap().isNull():
            return
        label = self._doc.get_page_label_for(self.page_index)
        total = self._doc.page_count
        phys = f"({self.page_index + 1}/{total})"
        display = f"{label} {phys}" if label else phys
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        padding = 5
        text_rect = fm.boundingRect(display)
        bg_w = text_rect.width() + padding * 2
        bg_h = text_rect.height() + padding * 2
        bg_x = (self.width() - bg_w) // 2
        bg_y = self.height() - bg_h - 14
        painter.fillRect(bg_x, bg_y, bg_w, bg_h, QColor(0, 0, 0, 150))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bg_x, bg_y, bg_w, bg_h, Qt.AlignmentFlag.AlignCenter, display)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if self._select_mode and event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._origin, self._origin))
            self._rubber_band.show()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._select_mode and not self._origin.isNull():
            self._rubber_band.setGeometry(
                QRect(self._origin, event.pos()).normalized()
            )
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._select_mode and not self._origin.isNull():
            rect = QRect(self._origin, event.pos()).normalized()
            self._rubber_band.hide()
            self._origin = QPoint()

            if rect.width() > 4 and rect.height() > 4:
                text = self._doc.get_text_in_rect(
                    self.page_index,
                    (rect.x(), rect.y(), rect.right(), rect.bottom()),
                    self._zoom,
                )
                if text:
                    self.text_selected.emit(text, self.page_index)
        else:
            super().mouseReleaseEvent(event)


class PdfViewer(QScrollArea):
    page_changed = Signal(int)          # 0-indexed 現在ページ
    text_selected = Signal(str, int)    # (抽出テキスト, 0-indexed page)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._zoom: float = 1.5
        self._page_widgets: list[PageWidget] = []
        self._rendered: set[int] = set()
        self._select_mode: bool = False

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet("background: #525659;")

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

    def set_select_mode(self, enabled: bool) -> None:
        self._select_mode = enabled
        for pw in self._page_widgets:
            pw.set_select_mode(enabled)

    def refresh_page_labels(self) -> None:
        """ページラベル表示を再描画する（ドキュメントのラベルが更新された後に呼ぶ）。"""
        for pw in self._page_widgets:
            pw.refresh_label()

    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._clear_pages()
        if self._doc is None:
            return

        for i in range(self._doc.page_count):
            w, h = self._doc.get_page_size(i, self._zoom)
            pw = PageWidget(i, w, h, self._doc, self._zoom)
            pw.set_select_mode(self._select_mode)
            pw.text_selected.connect(self.text_selected)
            self._layout.addWidget(pw)
            self._page_widgets.append(pw)

        QTimer.singleShot(0, self._render_visible)

    def _clear_pages(self) -> None:
        for pw in self._page_widgets:
            self._layout.removeWidget(pw)
            pw.deleteLater()
        self._page_widgets.clear()
        self._rendered.clear()

    def _visible_page_range(self) -> tuple[int, int]:
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
