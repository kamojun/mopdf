from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QGroupBox, QLabel, QWidget,
    QHBoxLayout, QDialogButtonBox, QScrollArea, QMenu,
)

from .toc_panel import TocPanel
from .page_label_panel import PageLabelPanel

# メニューにもツリー/表にも属さない、単発のQShortcutで実装されているもの。
# 増減がほぼ見込めない1件のみのため、他のセクションと違いここに直接書く。
_MISC_SHORTCUTS_HELP: list[tuple[str, str]] = [
    ("Esc", "テキスト選択モードをキャンセル"),
    ("Ctrl+Z", "元に戻す（目次・ページラベル共通）"),
    ("Ctrl+Shift+Z", "やり直す（目次・ページラベル共通）"),
]

_KEYCAP_STYLE = (
    "background: #f5f5f5; border: 1px solid #ccc; border-radius: 4px;"
    "padding: 2px 8px; font-family: Menlo, Consolas, monospace; font-size: 12px;"
)


class ShortcutsDialog(QDialog):
    """アプリのキーボードショートカットを一覧表示するモーダル。

    メニュー由来のショートカットは親ウィンドウのメニューバーから実行時に
    自動収集する（メニュー変更時に一覧が古くならないようにするため）。
    目次ツリー/ページラベル表のキー操作はQActionを持たない生の
    keyPressEvent/eventFilterで実装されているため、TocPanel/PageLabelPanel
    側に定義された定数（TREE_SHORTCUTS_HELP/TABLE_SHORTCUTS_HELP）をそのまま表示する。
    """

    def __init__(self, main_window, parent=None) -> None:
        super().__init__(parent or main_window)
        self.setWindowTitle("キーボードショートカット")
        self.resize(560, 600)

        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        menu_shortcuts = self._collect_menu_shortcuts(main_window)
        sections = [
            ("アプリ全体", menu_shortcuts + _MISC_SHORTCUTS_HELP),
            ("目次パネル", TocPanel.TREE_SHORTCUTS_HELP),
            ("ページラベルパネル", PageLabelPanel.TABLE_SHORTCUTS_HELP),
        ]
        for title, entries in sections:
            if entries:
                content_layout.addWidget(self._build_section(title, entries))
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    @staticmethod
    def _collect_menu_shortcuts(main_window) -> list[tuple[str, str]]:
        """メニューバーを再帰的に走査し、ショートカット付きQActionを収集する。"""
        result: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def visit(menu: QMenu) -> None:
            for action in menu.actions():
                submenu = action.menu()
                if submenu is not None:
                    visit(submenu)
                    continue
                key = action.shortcut().toString()
                text = action.text().replace("&", "").rstrip(".").strip()
                if key and text and (key, text) not in seen:
                    seen.add((key, text))
                    result.append((key, text))

        menubar = main_window.menuBar()
        for action in menubar.actions():
            submenu = action.menu()
            if submenu is not None:
                visit(submenu)
        return result

    @staticmethod
    def _build_section(title: str, entries: list[tuple[str, str]]) -> QGroupBox:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        for row, (keys, description) in enumerate(entries):
            grid.addLayout(ShortcutsDialog._build_keycap_row(keys), row, 0)
            grid.addWidget(QLabel(description), row, 1)
        return box

    @staticmethod
    def _build_keycap_row(keys: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        for i, chord in enumerate(keys.split(" / ")):
            if i > 0:
                sep = QLabel("/")
                sep.setStyleSheet("color: #999;")
                row.addWidget(sep)
            for j, token in enumerate(chord.split("+")):
                if j > 0:
                    row.addWidget(QLabel("+"))
                cap = QLabel(token.strip())
                cap.setStyleSheet(_KEYCAP_STYLE)
                row.addWidget(cap)
        row.addStretch()
        return row
