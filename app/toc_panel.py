from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLabel
)

from .pdf_document import PdfDocument, TocEntry


class TocPanel(QWidget):
    page_jump_requested = Signal(int)  # 0-indexed 物理ページ番号

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("目次")
        header.setStyleSheet(
            "font-weight: bold; padding: 6px 8px; background: #e8e8e8; border-bottom: 1px solid #ccc;"
        )
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setColumnWidth(0, 220)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, self._tree.header().ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, self._tree.header().ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(16)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._rebuild()

    def clear(self) -> None:
        self._doc = None
        self._tree.clear()

    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._tree.clear()
        if self._doc is None:
            return

        entries = self._doc.get_toc()
        if not entries:
            placeholder = QTreeWidgetItem(["（目次なし）"])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tree.addTopLevelItem(placeholder)
            return

        stack: list[QTreeWidgetItem] = []  # スタックで階層を管理
        for entry in entries:
            item = QTreeWidgetItem()
            item.setText(0, entry.title)
            item.setText(1, self._doc.get_page_label_for(entry.page))
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setData(0, Qt.ItemDataRole.UserRole, entry.page)

            depth = entry.level - 1
            # スタックを適切な深さに調整
            while len(stack) > depth:
                stack.pop()

            if stack:
                stack[-1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)

            stack.append(item)

        self._tree.expandAll()

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_jump_requested.emit(page)
