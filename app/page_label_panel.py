from __future__ import annotations
import csv
from typing import Optional
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QPushButton, QSpinBox, QComboBox, QLineEdit,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QFileDialog, QMessageBox,
)
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QPainter

from .pdf_document import PdfDocument, PageLabelRange, STYLE_LABELS

# スタイルコードとラベルの対応（逆引き用）
LABEL_TO_STYLE = {v: k for k, v in STYLE_LABELS.items()}
STYLE_ORDER = ["D", "r", "R", "a", "A", ""]  # ComboBoxの順序

COL_START = 0
COL_STYLE = 1
COL_PREFIX = 2
COL_FIRST = 3


class PageLabelDelegate(QStyledItemDelegate):
    """列ごとに適切なエディタを提供するDelegate。"""

    def __init__(self, panel: "PageLabelPanel") -> None:
        super().__init__(panel)
        self._panel = panel

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem,
                     index: QModelIndex) -> Optional[QWidget]:
        col = index.column()
        if col == COL_START:
            sb = QSpinBox(parent)
            sb.setMinimum(1)
            sb.setMaximum(self._panel._doc.page_count if self._panel._doc else 9999)
            return sb
        if col == COL_STYLE:
            cb = QComboBox(parent)
            for code in STYLE_ORDER:
                cb.addItem(STYLE_LABELS[code], code)
            return cb
        if col == COL_PREFIX:
            return QLineEdit(parent)
        if col == COL_FIRST:
            sb = QSpinBox(parent)
            sb.setMinimum(1)
            sb.setMaximum(99999)
            return sb
        return None

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        col = index.column()
        raw = index.data(Qt.ItemDataRole.UserRole)
        if col == COL_START and isinstance(editor, QSpinBox):
            editor.setValue(raw + 1 if raw is not None else 1)
        elif col == COL_STYLE and isinstance(editor, QComboBox):
            idx = STYLE_ORDER.index(raw) if raw in STYLE_ORDER else 0
            editor.setCurrentIndex(idx)
        elif col == COL_PREFIX and isinstance(editor, QLineEdit):
            editor.setText(raw or "")
        elif col == COL_FIRST and isinstance(editor, QSpinBox):
            editor.setValue(raw if raw is not None else 1)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if option.state & QStyle.StateFlag.State_Editing:
            return
        super().paint(painter, option, index)

    def setModelData(self, editor: QWidget, model, index: QModelIndex) -> None:
        col = index.column()
        if col == COL_START and isinstance(editor, QSpinBox):
            model.setData(index, editor.value() - 1, Qt.ItemDataRole.UserRole)
            model.setData(index, str(editor.value()), Qt.ItemDataRole.DisplayRole)
        elif col == COL_STYLE and isinstance(editor, QComboBox):
            code = editor.currentData()
            model.setData(index, code, Qt.ItemDataRole.UserRole)
            model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)
        elif col == COL_PREFIX and isinstance(editor, QLineEdit):
            text = editor.text()
            model.setData(index, text, Qt.ItemDataRole.UserRole)
            model.setData(index, text if text else "—", Qt.ItemDataRole.DisplayRole)
        elif col == COL_FIRST and isinstance(editor, QSpinBox):
            model.setData(index, editor.value(), Qt.ItemDataRole.UserRole)
            model.setData(index, str(editor.value()), Qt.ItemDataRole.DisplayRole)


class PageLabelPanel(QWidget):
    page_labels_modified = Signal()
    page_jump_requested = Signal(int)  # 0-indexed physical page

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

        # ツールバー
        toolbar = QWidget()
        toolbar.setStyleSheet("background: #f5f5f5; border-bottom: 1px solid #ddd;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(4, 2, 4, 2)
        tb_layout.setSpacing(2)
        self._btn_add = QPushButton("＋")
        self._btn_add.setToolTip("範囲を追加")
        self._btn_add.setFixedWidth(32)
        self._btn_add.setEnabled(False)
        self._btn_del = QPushButton("－")
        self._btn_del.setToolTip("選択した範囲を削除")
        self._btn_del.setFixedWidth(32)
        self._btn_del.setEnabled(False)
        tb_layout.addWidget(self._btn_add)
        tb_layout.addWidget(self._btn_del)
        tb_layout.addStretch()
        layout.addWidget(toolbar)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["開始ページ", "スタイル", "プレフィックス", "開始番号"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setItemDelegate(PageLabelDelegate(self))
        layout.addWidget(self._table)

        self._btn_add.clicked.connect(self._add_range)
        self._btn_del.clicked.connect(self._delete_range)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.installEventFilter(self)

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._btn_add.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._rebuild()

    def clear(self) -> None:
        self._doc = None
        self._btn_add.setEnabled(False)
        self._btn_del.setEnabled(False)
        self._table.setRowCount(0)

    def get_page_labels(self) -> list[PageLabelRange]:
        """テーブルの現在の状態からPageLabelRangeリストを生成。"""
        result = []
        for row in range(self._table.rowCount()):
            start_item = self._table.item(row, COL_START)
            style_item = self._table.item(row, COL_STYLE)
            prefix_item = self._table.item(row, COL_PREFIX)
            first_item = self._table.item(row, COL_FIRST)
            if start_item is None:
                continue
            start_page = start_item.data(Qt.ItemDataRole.UserRole)
            style = style_item.data(Qt.ItemDataRole.UserRole) if style_item else "D"
            prefix = prefix_item.data(Qt.ItemDataRole.UserRole) if prefix_item else ""
            first_num = first_item.data(Qt.ItemDataRole.UserRole) if first_item else 1
            if start_page is None:
                continue
            result.append(PageLabelRange(
                start_page=start_page,
                style=style or "",
                prefix=prefix or "",
                first_num=first_num if first_num is not None else 1,
            ))
        return sorted(result, key=lambda r: r.start_page)

    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        if self._doc is None:
            self._table.blockSignals(False)
            return

        ranges = self._doc.get_page_labels()
        self._table.setRowCount(len(ranges))
        for row, r in enumerate(ranges):
            self._populate_row(row, r)

        self._table.blockSignals(False)

    def _populate_row(self, row: int, r: PageLabelRange) -> None:
        # 開始ページ（表示: 1-indexed, UserRole: 0-indexed）
        start_item = QTableWidgetItem(str(r.start_page + 1))
        start_item.setData(Qt.ItemDataRole.UserRole, r.start_page)
        start_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_START, start_item)

        # スタイル
        style_item = QTableWidgetItem(STYLE_LABELS.get(r.style, r.style))
        style_item.setData(Qt.ItemDataRole.UserRole, r.style)
        style_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_STYLE, style_item)

        # プレフィックス
        prefix_item = QTableWidgetItem(r.prefix if r.prefix else "—")
        prefix_item.setData(Qt.ItemDataRole.UserRole, r.prefix)
        prefix_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_PREFIX, prefix_item)

        # 開始番号
        first_item = QTableWidgetItem(str(r.first_num))
        first_item.setData(Qt.ItemDataRole.UserRole, r.first_num)
        first_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_FIRST, first_item)

    def export_csv(self, path: str) -> None:
        """ページラベルをCSVファイルに書き出す。"""
        labels = self.get_page_labels()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["start_page", "style", "prefix", "first_num"])
            for r in labels:
                writer.writerow([r.start_page + 1, r.style, r.prefix, r.first_num])

    def _export_csv(self) -> None:
        default = ""
        if self._doc is not None and self._doc.path is not None:
            default = str(self._doc.path.with_suffix("")) + "_pagelabels.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "ページラベルをCSVに保存", default, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            self.export_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "CSVエラー", f"書き出しに失敗しました:\n{e}")

    def _add_range(self) -> None:
        if self._doc is None:
            return
        row = self._table.rowCount()
        self._table.setRowCount(row + 1)
        self._table.blockSignals(True)
        # デフォルト: 次の物理ページ（0-indexed）
        start_page = row  # 既存行数がそのまま次のページになる（簡易）
        self._populate_row(row, PageLabelRange(start_page=start_page, style="D", prefix="", first_num=1))
        self._table.blockSignals(False)
        self.page_labels_modified.emit()

    def _delete_range(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self._table.blockSignals(True)
        for row in rows:
            self._table.removeRow(row)
        self._table.blockSignals(False)
        self.page_labels_modified.emit()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if not self._table.isPersistentEditorOpen(self._table.currentIndex()):
                    self._delete_range()
                    return True
        return super().eventFilter(obj, event)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        start_item = self._table.item(row, COL_START)
        if start_item is None:
            return
        page = start_item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_jump_requested.emit(page)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.page_labels_modified.emit()
