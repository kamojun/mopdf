from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLineEdit, QLabel, QCheckBox, QDialogButtonBox,
)

from .toc_panel import TocPanel


class TocEntryDialog(QDialog):
    """テキスト選択から目次を追加する際に、タイトルと飛び先ページを指定するダイアログ。
    ページ欄は目次のページ欄と同じ規則(TocPanel.resolve_page)で解決し、結果を随時表示する。"""

    def __init__(self, title: str, page_index: int, page_label: str, toc_panel: TocPanel,
                 page_count: int, insert_below: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("目次に追加")
        self.setMinimumWidth(420)
        self._toc_panel = toc_panel
        self._page_count = page_count
        self._resolved: Optional[int] = None

        self._title_edit = QLineEdit(title)
        self._page_edit = QLineEdit(self._initial_page_text(page_index, page_label))
        self._result_label = QLabel()
        self._below_check = QCheckBox("選択されている項目の下に挿入")
        self._below_check.setChecked(insert_below)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("タイトル:", self._title_edit)
        # 解決結果は入力欄の横に並べ、入力しながら目で追えるようにする
        self._page_edit.setMaximumWidth(140)
        page_row = QHBoxLayout()
        page_row.addWidget(self._page_edit)
        page_row.addWidget(self._result_label, 1)
        layout.addRow("ページ:", page_row)
        layout.addRow("", self._below_check)
        layout.addRow(self._buttons)

        self._title_edit.textChanged.connect(self._update)
        self._page_edit.textChanged.connect(self._update)
        self._update()

        # タイトル欄から開始し、Enterでページ欄へ進む(ページ欄でのEnterはOK)
        self._title_edit.installEventFilter(self)
        self._title_edit.setFocus()

    def eventFilter(self, obj, event) -> bool:
        # QLineEditはEnterを無視して親に渡すため、そのままだとダイアログのOKが押されてしまう
        if obj is self._title_edit and event.type() == QEvent.Type.KeyPress \
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._page_edit.setFocus()
            self._page_edit.selectAll()
            return True
        return super().eventFilter(obj, event)

    def _initial_page_text(self, page_index: int, page_label: str) -> str:
        """選択したページを指す入力文字列。ラベルが重複していて別ページに解決される場合は
        物理ページ番号、それも別ページのラベルと衝突するなら(n)形式にする。"""
        for text in (page_label, str(page_index + 1)):
            if text and self._toc_panel.resolve_page(text) == page_index:
                return text
        return f"({page_index + 1})"

    def _update(self) -> None:
        page = self._toc_panel.resolve_page(self._page_edit.text().strip())
        if page is not None and not 0 <= page < self._page_count:
            page = None
        self._resolved = page
        if page is None:
            self._result_label.setText("該当するページがありません")
            self._result_label.setStyleSheet("color: #c00;")
        else:
            self._result_label.setText(f"→ {self._toc_panel.format_page_for_display(page)}")
            self._result_label.setStyleSheet("color: #555;")
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(page is not None and bool(self._title_edit.text().strip()))

    def title(self) -> str:
        return self._title_edit.text().strip()

    def page_index(self) -> int:
        assert self._resolved is not None
        return self._resolved

    def insert_below(self) -> bool:
        """チェックボックスの状態。記憶して次回の初期値にする。"""
        return self._below_check.isChecked()
