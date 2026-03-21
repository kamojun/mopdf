from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)

from .pdf_document import PdfDocument, PageLabelRange, STYLE_LABELS


class PageLabelPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("ページラベル")
        header.setStyleSheet(
            "font-weight: bold; padding: 6px 8px; background: #e8e8e8; border-bottom: 1px solid #ccc;"
        )
        layout.addWidget(header)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["開始ページ", "スタイル", "プレフィックス", "開始番号"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._rebuild()

    def clear(self) -> None:
        self._doc = None
        self._table.setRowCount(0)

    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._table.setRowCount(0)
        if self._doc is None:
            return

        ranges = self._doc.get_page_labels()
        if not ranges:
            self._table.setRowCount(1)
            item = QTableWidgetItem("（ページラベルなし）")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._table.setItem(0, 0, item)
            self._table.setSpan(0, 0, 1, 4)
            return

        self._table.setRowCount(len(ranges))
        for row, r in enumerate(ranges):
            # 開始ページ: 物理番号(1-indexed表示) と 論理ラベルを併記
            phys_label = self._doc.get_page_label_for(r.start_page)
            start_text = f"p.{r.start_page + 1}  →  {phys_label}"
            self._set_item(row, 0, start_text)
            self._set_item(row, 1, STYLE_LABELS.get(r.style, r.style))
            self._set_item(row, 2, r.prefix if r.prefix else "—")
            self._set_item(row, 3, str(r.first_num))

    def _set_item(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, col, item)
