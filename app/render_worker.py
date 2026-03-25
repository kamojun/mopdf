from __future__ import annotations
import threading
import fitz
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage


class RenderSignals(QObject):
    finished = Signal(int, QImage, int)  # (page_index, image, generation)


class RenderWorker(QRunnable):
    def __init__(self, path: str, page_index: int, zoom: float,
                 generation: int, cancel: threading.Event) -> None:
        super().__init__()
        self.signals = RenderSignals()
        self._path = path
        self._page_index = page_index
        self._zoom = zoom
        self._generation = generation
        self._cancel = cancel

    def run(self) -> None:
        if self._cancel.is_set():
            return
        try:
            doc = fitz.open(self._path)
        except Exception:
            return
        try:
            if self._page_index >= doc.page_count:
                return
            page = doc[self._page_index]
            mat = fitz.Matrix(self._zoom, self._zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888).copy()
        except Exception:
            return
        finally:
            doc.close()
        if not self._cancel.is_set():
            self.signals.finished.emit(self._page_index, img, self._generation)
