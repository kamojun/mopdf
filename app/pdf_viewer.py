from __future__ import annotations
import threading
from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QPoint, QThreadPool, Slot, QEvent
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QCursor, QFont
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QLabel, QSizePolicy, QFrame, QRubberBand, QMenu
)

from .pdf_document import PdfDocument
from .render_worker import RenderWorker

RENDER_BUFFER = 2  # 表示ページの前後何ページを先読みするか
# PageWidgetのQSS margin:8pxがレイアウトに追加する外側余白の合計(全方向8pxなので幅・高さ共通)。
# borderはsetFixedSizeの内側に収まるため含めない。
PAGE_LAYOUT_MARGIN = 16


class PageWidget(QLabel):
    """1ページ分の表示ウィジェット。テキスト選択モード時はドラッグで矩形選択できる。"""

    text_selected = Signal(str, int)  # (抽出テキスト, 0-indexed page)
    select_mode_requested = Signal()  # 右クリックメニューの「テキスト選択し目次追加」
    page_jump_dialog_requested = Signal()  # 右クリックメニューの「ページへ移動」
    page_label_requested = Signal(int)  # 右クリックメニューの「この位置にページラベル追加」(0-indexed page)

    def __init__(self, page_index: int, width: int, height: int,
                 doc: PdfDocument, zoom: float) -> None:
        super().__init__()
        self.page_index = page_index
        self._doc = doc
        self._zoom = zoom
        self._select_mode = False

        self._origin = QPoint()
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._label_rect = QRect()

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width, height)
        self.setStyleSheet("background: #e0e0e0; border: 1px solid #ccc; margin: 8px;")
        self.setMouseTracking(True)

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
        if label:
            phys = f"({self.page_index + 1}/{total})"
            display = f"{label} {phys}"
        else:
            display = f"{self.page_index + 1}/{total}"
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
        self._label_rect = QRect(bg_x, bg_y, bg_w, bg_h)
        painter.fillRect(bg_x, bg_y, bg_w, bg_h, QColor(0, 0, 0, 150))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bg_x, bg_y, bg_w, bg_h, Qt.AlignmentFlag.AlignCenter, display)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if not self._select_mode and event.button() == Qt.MouseButton.LeftButton \
                and self._label_rect.contains(event.pos()):
            self.page_jump_dialog_requested.emit()
        elif self._select_mode and event.button() == Qt.MouseButton.LeftButton:
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
        elif not self._select_mode:
            self.setCursor(QCursor(
                Qt.CursorShape.PointingHandCursor if self._label_rect.contains(event.pos())
                else Qt.CursorShape.ArrowCursor
            ))
            super().mouseMoveEvent(event)
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

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        select_action = menu.addAction("テキスト選択し目次追加")
        menu.addSeparator()
        jump_action = menu.addAction("ページへ移動")
        label_action = menu.addAction("この位置にページラベル追加")
        chosen = menu.exec(event.globalPos())
        if chosen is select_action:
            self.select_mode_requested.emit()
        elif chosen is jump_action:
            self.page_jump_dialog_requested.emit()
        elif chosen is label_action:
            self.page_label_requested.emit(self.page_index)


class PdfViewer(QScrollArea):
    ZOOM_MIN = 0.25
    ZOOM_MAX = 4.0
    ZOOM_STEP = 0.1
    DEFAULT_ZOOM = 1.5  # フィット計算が不可能な場合のフォールバックとしてのみ使用

    page_changed = Signal(int)          # 0-indexed 現在ページ
    text_selected = Signal(str, int)    # (抽出テキスト, 0-indexed page)
    select_mode_requested = Signal()  # 右クリックメニューの「テキスト選択し目次追加」
    page_jump_dialog_requested = Signal()  # 右クリックメニューの「ページへ移動」
    page_label_requested = Signal(int)  # 右クリックメニューの「この位置にページラベル追加」(0-indexed page)
    zoom_changed = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._zoom: float = self.DEFAULT_ZOOM
        self._auto_fit: bool = True  # ウィンドウの高さにページを合わせる自動フィットが有効か
        self._page_widgets: list[PageWidget] = []
        self._page_sizes: list[tuple[int, int]] = []
        self._rendered: set[int] = set()
        self._select_mode: bool = False

        self._render_pool = QThreadPool.globalInstance()
        self._render_pool.setMaxThreadCount(3)
        self._pending_cancels: dict[int, threading.Event] = {}
        self._render_generation: int = 0

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
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

        self._pinch_zoom_pending: float = 0.0
        self._pinch_zoom_timer = QTimer(self)
        self._pinch_zoom_timer.setSingleShot(True)
        self._pinch_zoom_timer.setInterval(120)
        self._pinch_zoom_timer.timeout.connect(self._apply_pending_pinch_zoom)

        self._resize_fit_timer = QTimer(self)
        self._resize_fit_timer.setSingleShot(True)
        self._resize_fit_timer.setInterval(150)
        self._resize_fit_timer.timeout.connect(self.fit_to_window)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._auto_fit = True
        self._zoom = self._compute_fit_height_zoom(0) or self.DEFAULT_ZOOM
        self._rebuild()
        self.zoom_changed.emit(self._zoom)

    def clear(self) -> None:
        for event in self._pending_cancels.values():
            event.set()
        self._pending_cancels.clear()
        self._render_generation += 1
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
            if isinstance(pw, PageWidget):
                pw.refresh_label()

    # ------------------------------------------------------------------
    # ズーム
    # ------------------------------------------------------------------

    def zoom_in(self) -> None:
        self._auto_fit = False
        self._apply_zoom(self._zoom + self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._auto_fit = False
        self._apply_zoom(self._zoom - self.ZOOM_STEP)

    def reset_zoom(self) -> None:
        self._auto_fit = False
        self._apply_zoom(1.0)  # 100% = fitz.Matrix(1,1)の実寸

    def fit_to_window(self) -> None:
        if self._doc is None:
            return
        anchor = self._capture_scroll_anchor()
        page_index = anchor[0] if anchor else 0
        new_zoom = self._compute_fit_height_zoom(page_index)
        if new_zoom is None:
            return
        self._auto_fit = True
        self._apply_zoom(new_zoom)

    def _apply_zoom(self, new_zoom: float) -> None:
        if self._doc is None:
            return
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        anchor = self._capture_scroll_anchor()
        self._zoom = new_zoom
        self._rebuild(preserve_anchor=anchor)
        self.zoom_changed.emit(self._zoom)

    def _compute_fit_height_zoom(self, page_index: int) -> Optional[float]:
        if self._doc is None or self._doc.page_count == 0:
            return None
        page_index = max(0, min(page_index, self._doc.page_count - 1))
        page_height_pts = self._doc.get_page_size(page_index, zoom=1.0)[1]
        available = self.viewport().height() - PAGE_LAYOUT_MARGIN
        if page_height_pts <= 0 or available <= 0:
            return None
        return max(self.ZOOM_MIN, min(self.ZOOM_MAX, available / page_height_pts))

    def _capture_scroll_anchor(self) -> Optional[tuple[int, float]]:
        if not self._page_sizes:
            return None
        scroll_top = self.verticalScrollBar().value()
        y = 0
        for i, (w, h) in enumerate(self._page_sizes):
            if y + h > scroll_top:
                fraction = (scroll_top - y) / h if h else 0.0
                return (i, fraction)
            y += h
        return (len(self._page_sizes) - 1, 0.0)

    def _apply_scroll_anchor(self, anchor: tuple[int, float]) -> None:
        if not self._page_sizes:
            return
        page_index, fraction = anchor
        page_index = min(page_index, len(self._page_sizes) - 1)
        y = sum(h for _, h in self._page_sizes[:page_index])
        y += fraction * self._page_sizes[page_index][1]
        self.verticalScrollBar().setValue(int(y))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit and self._doc is not None:
            self._resize_fit_timer.start()

    def event(self, event) -> bool:
        if (event.type() == QEvent.Type.NativeGesture
                and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
                and self._doc is not None):
            self._pinch_zoom_pending += event.value()
            self._pinch_zoom_timer.start()
            return True
        return super().event(event)

    def _apply_pending_pinch_zoom(self) -> None:
        delta = self._pinch_zoom_pending
        self._pinch_zoom_pending = 0.0
        if delta:
            self._auto_fit = False
            self._apply_zoom(self._zoom * (1.0 + delta))

    # ------------------------------------------------------------------

    def _rebuild(self, preserve_anchor: Optional[tuple[int, float]] = None) -> None:
        # 進行中のレンダリングをすべてキャンセル
        for event in self._pending_cancels.values():
            event.set()
        self._pending_cancels.clear()
        self._render_generation += 1

        self._clear_pages()
        if preserve_anchor is None:
            self.verticalScrollBar().setValue(0)
        if self._doc is None:
            return

        # 全ページサイズを一括取得（PyMuPDFを1パスで回す）
        self._page_sizes = self._doc.get_all_page_sizes(self._zoom)

        # PageWidget を直接生成（初期状態はpixmap未設定の灰色）
        assert self._doc is not None
        for i, (w, h) in enumerate(self._page_sizes):
            pw = PageWidget(i, w, h, self._doc, self._zoom)
            pw.set_select_mode(self._select_mode)
            pw.text_selected.connect(self.text_selected)
            pw.select_mode_requested.connect(self.select_mode_requested)
            pw.page_jump_dialog_requested.connect(self.page_jump_dialog_requested)
            pw.page_label_requested.connect(self.page_label_requested)
            self._layout.addWidget(pw, 0, Qt.AlignmentFlag.AlignHCenter)
            self._page_widgets.append(pw)

        def _finish() -> None:
            if preserve_anchor is not None:
                self._apply_scroll_anchor(preserve_anchor)
            self._render_visible()

        QTimer.singleShot(0, _finish)

    def _ensure_page_widget(self, i: int) -> PageWidget:
        return self._page_widgets[i]  # type: ignore[return-value]

    def _clear_pages(self) -> None:
        for pw in self._page_widgets:
            self._layout.removeWidget(pw)
            pw.deleteLater()
        self._page_widgets.clear()
        self._page_sizes.clear()
        self._rendered.clear()

    def _visible_page_range(self) -> tuple[int, int]:
        if not self._page_sizes:
            return (0, 0)
        scroll_top = self.verticalScrollBar().value()
        scroll_bottom = scroll_top + self.viewport().height()

        first = len(self._page_sizes) - 1
        last = 0
        y = 0
        for i, (w, h) in enumerate(self._page_sizes):
            if y + h >= scroll_top and y <= scroll_bottom:
                first = min(first, i)
                last = max(last, i)
            y += h

        first = max(0, first - RENDER_BUFFER)
        last = min(len(self._page_sizes) - 1, last + RENDER_BUFFER)
        return (first, last)

    def _render_visible(self) -> None:
        if self._doc is None or self._doc.path is None:
            return
        first, last = self._visible_page_range()

        # 範囲外ページのキャンセル
        for idx in list(self._pending_cancels):
            if idx < first or idx > last:
                self._pending_cancels.pop(idx).set()

        # 未レンダリング・未投入ページをエンキュー
        for i in range(first, last + 1):
            if i not in self._rendered and i not in self._pending_cancels:
                self._enqueue_render(i)

    def _enqueue_render(self, page_index: int) -> None:
        cancel = threading.Event()
        self._pending_cancels[page_index] = cancel
        worker = RenderWorker(
            path=str(self._doc.path),
            page_index=page_index,
            zoom=self._zoom,
            generation=self._render_generation,
            cancel=cancel,
        )
        worker.signals.finished.connect(self._on_render_finished)
        self._render_pool.start(worker)

    @Slot(int, QImage, int)
    def _on_render_finished(self, page_index: int, img: QImage, generation: int) -> None:
        if generation != self._render_generation:
            return
        self._pending_cancels.pop(page_index, None)
        if page_index >= len(self._page_widgets):
            return
        pw = self._ensure_page_widget(page_index)
        pw.setPixmap(QPixmap.fromImage(img))
        pw.setStyleSheet("background: white; border: 1px solid #ccc; margin: 8px;")
        self._rendered.add(page_index)

    def _on_scroll(self) -> None:
        self._render_timer.start()
        self._update_current_page()

    def _update_current_page(self) -> None:
        if not self._page_sizes:
            return
        viewport_center_y = self.verticalScrollBar().value() + self.viewport().height() // 2
        best = 0
        y = 0
        best_dist = float('inf')
        for i, (w, h) in enumerate(self._page_sizes):
            dist = abs(y + h // 2 - viewport_center_y)
            if dist < best_dist:
                best_dist = dist
                best = i
            y += h
        self.page_changed.emit(best)
