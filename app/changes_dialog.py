from __future__ import annotations
import difflib
from typing import Optional
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialogButtonBox, QAbstractItemView,
)


def paired_diff(
    old_keys: list[str],
    new_keys: list[str],
    old_display: Optional[list[str]] = None,
    new_display: Optional[list[str]] = None,
) -> list[tuple[Optional[str], Optional[str]]]:
    """行単位のシーケンス差分を「変更前/変更後」の行ペアに変換する。
    同一性の判定は old_keys/new_keys で行い、実際に表示するテキストは
    old_display/new_display(省略時はキーをそのまま表示に使う)から取る。
    これにより、"同じキーだが表示だけ変わる"ケース(例: ページラベルの表示反映)を
    差分として検出しないようにできる。
    置換ブロックは位置で単純に対応付ける(意味的に完全に正しい対応ではないが、
    抜粋表示としては十分)。"""
    old_display = old_keys if old_display is None else old_display
    new_display = new_keys if new_display is None else new_display
    sm = difflib.SequenceMatcher(None, old_keys, new_keys)
    pairs: list[tuple[Optional[str], Optional[str]]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old_chunk, new_chunk = old_display[i1:i2], new_display[j1:j2]
        for k in range(max(len(old_chunk), len(new_chunk))):
            pairs.append((
                old_chunk[k] if k < len(old_chunk) else None,
                new_chunk[k] if k < len(new_chunk) else None,
            ))
    return pairs


class ChangesDialog(QDialog):
    """未保存の変更点を「変更前/変更後」の2列で見やすく表示するモーダル。"""

    # このアプリはライトテーマ固定(黒文字)なので、それに合わせた薄いパステル背景にする
    _REMOVED_BG = QColor("#ffdcdc")  # 変更前セル(削除/置換前)の背景
    _ADDED_BG = QColor("#d9f5da")    # 変更後セル(追加/置換後)の背景

    def __init__(
        self,
        toc_pairs: list[tuple[Optional[str], Optional[str]]],
        label_pairs: list[tuple[Optional[str], Optional[str]]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("変更点")
        self.resize(900, 600)
        layout = QVBoxLayout(self)

        sections = [("目次", toc_pairs), ("ページラベル", label_pairs)]
        shown = False
        for title, pairs in sections:
            if not pairs:
                continue
            shown = True
            layout.addWidget(self._build_section(title, pairs))

        if not shown:
            layout.addWidget(QLabel("変更点はありません。"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _build_section(self, title: str, pairs: list[tuple[Optional[str], Optional[str]]]) -> QGroupBox:
        box = QGroupBox(title)
        vbox = QVBoxLayout(box)
        table = QTableWidget(len(pairs), 2)
        table.setHorizontalHeaderLabels(["変更前", "変更後"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setWordWrap(True)
        for row, (old, new) in enumerate(pairs):
            old_item = QTableWidgetItem(old or "")
            new_item = QTableWidgetItem(new or "")
            if old is not None:
                old_item.setBackground(self._REMOVED_BG)
            if new is not None:
                new_item.setBackground(self._ADDED_BG)
            table.setItem(row, 0, old_item)
            table.setItem(row, 1, new_item)
        table.resizeRowsToContents()
        vbox.addWidget(table)
        return box
