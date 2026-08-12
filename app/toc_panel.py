from __future__ import annotations
import csv
import io
import re
from typing import Optional
from PySide6.QtCore import Qt, Signal, QModelIndex, QTimer, QEvent, QItemSelectionModel
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QAbstractItemView, QStyledItemDelegate,
    QLineEdit, QFileDialog, QMessageBox, QApplication, QSpinBox,
)

from .pdf_document import PdfDocument, TocEntry

INSERT_BELOW_SELECTED = "below_selected"  # 目次ツリーで選択中の項目の下に挿入
INSERT_PAGE_ORDER = "page_order"          # 既存項目のページ番号順で適切な位置に挿入


class TitleDelegate(QStyledItemDelegate):
    """タイトル列のデリゲート。Tab で同行のページ番号列編集に移る。"""

    def __init__(self, on_tab, parent=None):
        super().__init__(parent)
        self._on_tab = on_tab
        self._current_index = QModelIndex()

    def createEditor(self, parent, option, index):
        self._current_index = index
        return super().createEditor(parent, option, index)

    def eventFilter(self, editor, event):
        if (event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Tab):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
            self._on_tab(self._current_index)
            return True
        return super().eventFilter(editor, event)


class PageLineDelegate(QStyledItemDelegate):
    """ページ番号列のインライン編集をQLineEditで行うデリゲート。
    整数・論理ラベル・'?'（未設定）を受け付ける。
    Enterキー押下時は on_enter(index) を呼び出す（連続入力モード用）。"""

    def __init__(self, get_display_text, resolve_page, on_enter=None, get_seed_text=None, parent=None):
        super().__init__(parent)
        self._get_display_text = get_display_text  # (page0: int | None) -> str
        self._resolve_page = resolve_page           # (text: str) -> int | None
        self._on_enter = on_enter                   # (index: QModelIndex) -> None
        self._get_seed_text = get_seed_text          # (index: QModelIndex) -> str | None
        self._current_index = QModelIndex()

    def createEditor(self, parent, option, index):
        self._current_index = index
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        return editor

    def eventFilter(self, editor, event):
        if (event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
            if self._on_enter is not None:
                self._on_enter(self._current_index)
            return True
        return super().eventFilter(editor, event)

    def setEditorData(self, editor, index):
        seed_text = self._get_seed_text(index) if self._get_seed_text else None
        if seed_text is not None:
            editor.setText(seed_text)
        else:
            page0 = index.sibling(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            editor.setText(self._get_display_text(page0))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        if text in ("?", ""):
            page_val = -1  # sentinel: 未設定
        else:
            resolved = self._resolve_page(text)
            page_val = resolved if resolved is not None else -1
        model.setData(index, page_val, Qt.ItemDataRole.UserRole + 1)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class TocPanel(QWidget):
    page_jump_requested = Signal(int)   # 0-indexed 物理ページ番号
    toc_modified = Signal()             # 編集が行われたとき

    _MAX_HISTORY = 50
    _NO_SUGGESTION = -1  # 増分スピンボックスの最小値: 提案を出さない(OFF)
    _JUMP_DELAY_MS = 200  # クリック時のページジャンプを遅らせる時間(ダブルクリック判定待ち)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._current_page: int = 0     # MainWindowから更新される
        self._pending_item: Optional[QTreeWidgetItem] = None  # 追加直後・未確定のアイテム
        self._pending_jump_item: Optional[QTreeWidgetItem] = None  # ダブルクリック判定待ちのジャンプ
        self._page_edit_mode: bool = False  # ページ番号連続入力モード
        self._page_increment: int = self._NO_SUGGESTION  # 連続入力モードでEnterのみ押した際の加算ページ数
        self._pending_seq_seed: Optional[int] = None  # 次に開くエディタへの提案値(0-indexed)
        self._history: list[list[TocEntry]] = []
        self._staged_snapshot: Optional[list[TocEntry]] = None  # _add_entry用
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ヘッダー
        header = QLabel("目次")
        header.setStyleSheet(
            "font-weight: bold; padding: 6px 8px;"
            "background: #e8e8e8; border-bottom: 1px solid #ccc;"
        )
        layout.addWidget(header)

        # ツールバー
        toolbar = QWidget()
        toolbar.setStyleSheet("background: #f5f5f5; border-bottom: 1px solid #ddd;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(4, 2, 4, 2)
        tb_layout.setSpacing(2)

        self._btn_add    = self._make_btn("＋", "現在のページにエントリを追加")
        self._btn_del    = self._make_btn("－", "選択したエントリを削除")
        self._btn_up     = self._make_btn("↑", "上へ移動")
        self._btn_down   = self._make_btn("↓", "下へ移動")
        self._btn_left   = self._make_btn("←", "階層を上げる")
        self._btn_right  = self._make_btn("→", "階層を下げる")
        for btn in [self._btn_add, self._btn_del, self._btn_up,
                    self._btn_down, self._btn_left, self._btn_right]:
            tb_layout.addWidget(btn)

        self._btn_page_mode = QPushButton("#")
        self._btn_page_mode.setToolTip(
            "ページ番号連続入力モード\n"
            "ONの間、Enterで次の行のページ番号入力に自動で移動します"
        )
        self._btn_page_mode.setCheckable(True)
        self._btn_page_mode.setFixedWidth(32)
        self._btn_page_mode.setFixedHeight(24)
        self._btn_page_mode.setStyleSheet("font-size: 12px;")
        tb_layout.addWidget(self._btn_page_mode)

        self._spin_increment = QSpinBox()
        self._spin_increment.setRange(self._NO_SUGGESTION, 999)
        self._spin_increment.setSpecialValueText("OFF")
        self._spin_increment.setValue(self._page_increment)
        self._spin_increment.setPrefix("+")
        self._spin_increment.setEnabled(False)
        self._spin_increment.setFixedWidth(52)
        self._spin_increment.setFixedHeight(24)
        self._spin_increment.setToolTip(
            "ページ番号連続入力モードで、Enterのみ押したときに\n"
            "前の行から自動で加算するページ数\n"
            "+0: 前の行と同じページ番号を提案（インクリメントなし）\n"
            "OFF: 提案を表示せず、毎回手入力する"
        )
        tb_layout.addWidget(self._spin_increment)

        tb_layout.addStretch()
        layout.addWidget(toolbar)

        # ツリー（Shift+矢印: 複数選択, Cmd/Ctrl+矢印: 並び替え・階層変更, Alt+↑/↓: ページ表示追従）
        self._tree = self._make_tree()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setColumnWidth(0, 220)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, self._tree.header().ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, self._tree.header().ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(16)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)

        # 列0: タイトル編集可(Tab→列1へ), 列1: デリゲートでSpinBox
        self._tree.setItemDelegateForColumn(
            0, TitleDelegate(
                on_tab=lambda idx: QTimer.singleShot(
                    0, lambda: self._tree.editItem(self._tree.itemFromIndex(idx), 1)
                ),
                parent=self,
            )
        )
        self._tree.setItemDelegateForColumn(
            1, PageLineDelegate(
                self._get_page_display_text, self._resolve_page,
                on_enter=self._on_page_enter,
                get_seed_text=self._get_page_edit_seed_text,
                parent=self,
            )
        )

        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.model().rowsInserted.connect(self._emit_modified)
        self._tree.model().rowsRemoved.connect(self._emit_modified)
        self._tree.model().rowsMoved.connect(self._emit_modified)
        self._tree.installEventFilter(self)
        layout.addWidget(self._tree)

        # ボタン接続
        self._btn_add.clicked.connect(self._add_entry)
        self._btn_del.clicked.connect(self._delete_entry)
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        self._btn_left.clicked.connect(self._indent_left)
        self._btn_right.clicked.connect(self._indent_right)
        self._btn_page_mode.toggled.connect(self._toggle_page_edit_mode)
        self._spin_increment.valueChanged.connect(self._on_increment_changed)

        self._tree.itemSelectionChanged.connect(self._update_button_states)
        self._tree.itemSelectionChanged.connect(self._cancel_stale_pending_jump)
        self._update_button_states()

    # ------------------------------------------------------------------
    # 公開API
    # ------------------------------------------------------------------

    def load(self, doc: PdfDocument) -> None:
        self._doc = doc
        self._rebuild()

    def clear(self) -> None:
        self._doc = None
        self._tree.clear()
        self._btn_page_mode.setChecked(False)
        self._pending_seq_seed = None
        self._pending_jump_item = None
        self._update_button_states()

    def refresh_page_labels(self) -> None:
        """全エントリのページラベル表示を更新する。"""
        def walk(item: QTreeWidgetItem) -> None:
            self._refresh_page_label(item)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))

    def set_current_page(self, page_index: int) -> None:
        self._current_page = page_index

    def get_toc(self) -> list[TocEntry]:
        """ツリーの現在の状態からTocEntryリストを生成"""
        result = []

        def walk(item: QTreeWidgetItem, level: int) -> None:
            page = item.data(0, Qt.ItemDataRole.UserRole)
            title = item.text(0)
            result.append(TocEntry(level=level, title=title, page=page))
            for i in range(item.childCount()):
                walk(item.child(i), level + 1)

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i), 1)
        return result

    def add_entry_with_title(self, title: str, page_index: int,
                              insert_mode: str = INSERT_BELOW_SELECTED) -> None:
        """テキスト選択などから外部にエントリを追加する"""
        self._add_entry(title=title, page_index=page_index, insert_mode=insert_mode)

    # ------------------------------------------------------------------
    # 内部: ツリー構築
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._history.clear()
        self._staged_snapshot = None
        entries = self._doc.get_toc() if self._doc else []
        self._build_tree_from_entries(entries)

    def _build_tree_from_entries(self, entries: list[TocEntry]) -> None:
        self._pending_jump_item = None
        self._tree.blockSignals(True)
        self._tree.clear()
        stack: list[QTreeWidgetItem] = []
        for entry in entries:
            item = self._make_item(entry.title, entry.page)
            depth = entry.level - 1
            while len(stack) > depth:
                stack.pop()
            if stack:
                stack[-1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            stack.append(item)
        if entries:
            self._tree.expandAll()
        self._tree.blockSignals(False)
        self._update_button_states()

    def _get_page_display_text(self, page0: Optional[int]) -> str:
        """0-indexed物理ページ番号またはNoneを表示文字列に変換する。
        ページラベルが存在するドキュメントでラベルのないページは (n) 形式で表示する。"""
        if page0 is None:
            return "?"
        if self._doc is None:
            return str(page0 + 1)
        label = self._doc.get_page_label_for(page0)
        if label:
            return label
        if self._doc.get_page_labels():
            return f"({page0 + 1})"
        return str(page0 + 1)

    def _make_item(self, title: str, page: Optional[int]) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, title)
        item.setData(0, Qt.ItemDataRole.UserRole, page)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable |
            Qt.ItemFlag.ItemIsEditable |
            Qt.ItemFlag.ItemIsDragEnabled |
            Qt.ItemFlag.ItemIsDropEnabled
        )
        self._refresh_page_label(item)
        return item

    def _refresh_page_label(self, item: QTreeWidgetItem) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setText(1, self._get_page_display_text(page))

    # ------------------------------------------------------------------
    # アンドゥ
    # ------------------------------------------------------------------

    def _push_history(self) -> None:
        self._history.append(self.get_toc())
        if len(self._history) > self._MAX_HISTORY:
            self._history.pop(0)

    def _undo(self) -> None:
        if not self._history:
            return
        snapshot = self._history.pop()
        self._build_tree_from_entries(snapshot)
        self._emit_modified()

    # ------------------------------------------------------------------
    # 編集操作
    # ------------------------------------------------------------------

    def _add_entry(self, *, title: str = "（無題）", page_index: Optional[int] = None,
                    before: bool = False, insert_mode: str = INSERT_BELOW_SELECTED) -> None:
        if self._doc is None:
            return
        if page_index is None:
            page_index = self._current_page
        snapshot = self.get_toc()

        item = self._make_item(title, page_index)
        if insert_mode == INSERT_PAGE_ORDER and page_index is not None:
            self._insert_item_by_page_order(item, page_index)
        else:
            selected = self._tree.currentItem()
            if selected:
                parent = selected.parent()
                if parent:
                    idx = parent.indexOfChild(selected)
                    parent.insertChild(idx if before else idx + 1, item)
                else:
                    idx = self._tree.indexOfTopLevelItem(selected)
                    self._tree.insertTopLevelItem(idx if before else idx + 1, item)
            else:
                self._tree.addTopLevelItem(item)

        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)
        # editItem が前のエディタを同期的に閉じて _pending_item/_staged_snapshot を
        # クリアする場合があるため、editItem 呼び出し後に設定する
        self._pending_item = item
        self._staged_snapshot = snapshot

    def _insert_item_by_page_order(self, item: QTreeWidgetItem, page_index: int) -> None:
        """既存項目をget_toc()と同じ先行順（DFS）で走査し、page_index以下で
        最後に見つかった項目の直後・同じ階層に挿入する。該当項目がなければ
        末尾のトップレベル項目として追加する。"""
        target: Optional[QTreeWidgetItem] = None

        def walk(node: QTreeWidgetItem) -> None:
            nonlocal target
            page = node.data(0, Qt.ItemDataRole.UserRole)
            if page is not None and page <= page_index:
                target = node
            for i in range(node.childCount()):
                walk(node.child(i))

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))

        if target is None:
            self._tree.addTopLevelItem(item)
            return

        parent = target.parent()
        if parent:
            parent.insertChild(parent.indexOfChild(target) + 1, item)
        else:
            self._tree.insertTopLevelItem(self._tree.indexOfTopLevelItem(target) + 1, item)

    def _delete_item(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))

    def _delete_entry(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        self._push_history()
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))

    def _container_ops(self, parent: Optional[QTreeWidgetItem]):
        """親アイテム（またはトップレベルなら`None`）に応じて、子リスト操作用の
        (件数取得, インデックス取得, 取り出し, 挿入) の4関数を返す。"""
        if parent is not None:
            return parent.childCount, parent.indexOfChild, parent.takeChild, parent.insertChild
        return (self._tree.topLevelItemCount, self._tree.indexOfTopLevelItem,
                self._tree.takeTopLevelItem, self._tree.insertTopLevelItem)

    def _move_selected(self, delta: int) -> None:
        """選択中のルート項目を親ごとにまとめ、塊として1段ずつ上下に動かす。
        delta=-1で上, +1で下。"""
        roots = self._selected_root_items()
        if not roots:
            return
        self._push_history()
        groups: dict[Optional[QTreeWidgetItem], list[QTreeWidgetItem]] = {}
        for item in roots:
            groups.setdefault(item.parent(), []).append(item)
        for parent, items in groups.items():
            count_fn, index_of, take, insert = self._container_ops(parent)
            ordered = items if delta < 0 else list(reversed(items))
            boundary = -1 if delta < 0 else count_fn()
            for item in ordered:
                idx = index_of(item)
                target = idx + delta
                moves = target > boundary if delta < 0 else target < boundary
                if moves:
                    take(idx)
                    insert(target, item)
                    boundary = target
                else:
                    boundary = idx
        self._select_items(roots)
        self._emit_modified()

    def _move_up(self) -> None:
        self._move_selected(-1)

    def _move_down(self) -> None:
        self._move_selected(1)

    def _selected_root_items(self) -> list[QTreeWidgetItem]:
        """選択中のアイテムのうち、祖先も選択されているものを除いた「ルート」のみを
        ツリー表示順（上から下）で返す。祖先ごと動く子孫アイテムは個別に処理しない。"""
        selected = self._tree.selectedItems()
        selected_ids = {id(it) for it in selected}
        roots = []
        for item in selected:
            node = item.parent()
            while node is not None and id(node) not in selected_ids:
                node = node.parent()
            if node is None:
                roots.append(item)
        roots.sort(key=self._item_order_key)
        return roots

    def _item_order_key(self, item: QTreeWidgetItem) -> tuple[int, ...]:
        """アイテムをツリー表示順（上から下）で比較できるパス表現を返す。"""
        path = []
        node = item
        while node is not None:
            parent = node.parent()
            if parent:
                path.append(parent.indexOfChild(node))
            else:
                path.append(self._tree.indexOfTopLevelItem(node))
            node = parent
        return tuple(reversed(path))

    def _select_items(self, items: list[QTreeWidgetItem]) -> None:
        self._tree.clearSelection()
        for item in items:
            item.setSelected(True)
        if items:
            # setCurrentItem()の既定動作は、ツリーがフォーカスを持つ状態だと選択を
            # currentItemの1件だけに潰してしまう。NoUpdateで直前のselectedを維持する。
            self._tree.setCurrentItem(items[-1], 0, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _indent_left(self) -> None:
        """選択中の項目を1段上の階層に移動する（親の兄弟になる）。
        複数選択時は各項目に適用する。"""
        roots = [it for it in self._selected_root_items() if it.parent() is not None]
        if not roots:
            return  # 全てトップレベル
        self._push_history()
        # 兄弟同士の相対順序を保つため、下側の項目から処理する
        for item in reversed(roots):
            self._indent_left_single(item)
        self._select_items(roots)
        self._emit_modified()

    def _indent_left_single(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        if parent is None:
            return
        grandparent = parent.parent()
        idx_in_parent = parent.indexOfChild(item)
        parent.takeChild(idx_in_parent)
        if grandparent:
            idx = grandparent.indexOfChild(parent)
            grandparent.insertChild(idx + 1, item)
        else:
            idx = self._tree.indexOfTopLevelItem(parent)
            self._tree.insertTopLevelItem(idx + 1, item)

    def _indent_right(self) -> None:
        """選択中の項目を1段下の階層に移動する（直前の兄弟の子になる）。
        複数選択時は各項目に適用する。"""
        roots = self._selected_root_items()
        movable = []
        for item in roots:
            parent = item.parent()
            idx = parent.indexOfChild(item) if parent else self._tree.indexOfTopLevelItem(item)
            if idx > 0:
                movable.append(item)
        if not movable:
            return
        self._push_history()
        # 前の兄弟を親にしていくため、上側の項目から処理する
        for item in movable:
            prev = self._indent_right_single(item)
            prev.setExpanded(True)
        self._select_items(movable)
        self._emit_modified()

    def _indent_right_single(self, item: QTreeWidgetItem) -> QTreeWidgetItem:
        parent = item.parent()
        if parent:
            idx = parent.indexOfChild(item)
            prev = parent.child(idx - 1)
            parent.takeChild(idx)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            prev = self._tree.topLevelItem(idx - 1)
            self._tree.takeTopLevelItem(idx)
        prev.addChild(item)
        return prev

    def export_csv(self, path: str) -> None:
        """目次をCSVファイルに書き出す。"""
        toc = self.get_toc()
        has_labels = self._doc is not None and bool(self._doc.get_page_labels())
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["level", "title", "page"])
            for entry in toc:
                writer.writerow([entry.level, entry.title,
                                  self._page_str_for_export(entry.page, has_labels)])

    def _page_str_for_export(self, page: Optional[int], has_labels: bool) -> str:
        """0-indexed物理ページ番号またはNoneをCSV用のページ文字列に変換する。"""
        if page is None:
            return "?"
        if not has_labels:
            return str(page + 1)
        label = self._doc.get_page_label_for(page)
        if label:
            return label
        return f"({page + 1})"

    def _export_csv(self) -> None:
        default = ""
        if self._doc is not None and self._doc.path is not None:
            default = str(self._doc.path.with_suffix("")) + "_toc.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "目次をCSVに保存", default, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            self.export_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "CSVエラー", f"書き出しに失敗しました:\n{e}")

    def _import_csv(self) -> None:
        if self._pending_item is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "目次ファイルを開く", "",
            "CSV/Text Files (*.csv *.txt);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return
        self._import_toc_from_path(path)

    def _import_toc_from_path(self, path: str) -> None:
        is_txt = path.lower().endswith(".txt")
        try:
            if is_txt:
                entries, warnings = self._parse_txt_list(path), []
            else:
                entries, warnings = self._parse_csv_with_warnings(path)
        except Exception as e:
            QMessageBox.critical(self, "インポートエラー", f"読み込みに失敗しました:\n{e}")
            return

        if not entries:
            QMessageBox.information(self, "インポート", "有効なエントリが見つかりませんでした。")
            return

        if self._tree.topLevelItemCount() > 0:
            reply = QMessageBox.question(
                self, "確認",
                "既存の目次を上書きしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._push_history()
        self._build_tree_from_entries(entries)
        self._emit_modified()

        if warnings:
            QMessageBox.warning(
                self, "インポート警告",
                "一部のページ番号を解決できませんでした。\n"
                "該当エントリを未設定（?）でインポートしました。\n\n"
                + "\n".join(warnings)
                + "\n\nUIで該当エントリを確認・修正してください。"
            )

    def _parse_csv_with_warnings(self, path: str) -> tuple[list[TocEntry], list[str]]:
        """CSV形式: level,title,page を読み込む。
        page は論理ページラベル / (n)形式 / 整数（1-indexed物理）/ '?'（未設定）を受け付ける。
        解決できないページは未設定としてロードし警告を返す。
        """
        entries: list[TocEntry] = []
        warnings: list[str] = []

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row_num, row in enumerate(reader, 1):
                if not row or row[0].strip().startswith("#"):
                    continue
                if row[0].strip().lower() == "level":
                    continue  # ヘッダー行をスキップ
                if len(row) < 3:
                    continue  # カラム不足は黙ってスキップ
                try:
                    level = int(row[0].strip())
                except ValueError:
                    continue
                if level < 1:
                    continue
                title = row[1].strip()
                page_str = row[2].strip()

                # ページ解決
                if page_str == "?":
                    page0: Optional[int] = None
                else:
                    page0 = self._resolve_page(page_str)
                    if page0 is None:
                        warnings.append(f"行{row_num}: ページ '{page_str}' が見つかりません（未設定でロード）")
                    elif self._doc is not None and page0 >= self._doc.page_count:
                        clamped = self._doc.page_count - 1
                        warnings.append(
                            f"行{row_num}: ページ {page0 + 1} は範囲外です"
                            f"（最終ページ {self._doc.page_count} を使用）"
                        )
                        page0 = clamped

                entries.append(TocEntry(level=level, title=title, page=page0))

        return entries, warnings

    def _parse_txt_list(self, path: str) -> list[TocEntry]:
        """プレーンテキスト形式: 1行1タイトルを読み込む。
        階層・ページ番号を持たず、全件level=1・ページ未設定として取り込む。"""
        entries: list[TocEntry] = []
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                title = line.strip()
                if not title:
                    continue
                entries.append(TocEntry(level=1, title=title, page=None))
        return entries

    # ------------------------------------------------------------------
    # ドラッグ&ドロップ（目次インポート）
    # ------------------------------------------------------------------

    _IMPORTABLE_EXTS = (".csv", ".txt")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._doc is None or self._pending_item is not None:
            return
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(self._IMPORTABLE_EXTS):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self._import_toc_from_path(urls[0].toLocalFile())

    def eventFilter(self, obj, event) -> bool:
        # self._tree は InternalMove 用に WA_AcceptDrops が立っており、外部からの
        # ファイルドロップがツリーに奪われて親に伝播しないため、ここで横取りする。
        if obj is self._tree:
            etype = event.type()
            if etype in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                urls = event.mimeData().urls()
                if urls and urls[0].toLocalFile().lower().endswith(self._IMPORTABLE_EXTS):
                    if self._doc is not None and self._pending_item is None:
                        event.acceptProposedAction()
                    return True
            elif etype == QEvent.Type.Drop:
                urls = event.mimeData().urls()
                if urls and urls[0].toLocalFile().lower().endswith(self._IMPORTABLE_EXTS):
                    self._import_toc_from_path(urls[0].toLocalFile())
                    return True
        return super().eventFilter(obj, event)

    def _resolve_page(self, page_str: str) -> Optional[int]:
        """ページ文字列を0-indexed物理ページ番号に解決する。解決不能な場合はNoneを返す。"""
        # パターン1: 論理ページラベルに一致するものを優先的に探す。
        # ローマ数字の前付けなどページラベルが混在するPDFでは、
        # 入力した数字を物理ページ番号として即決めてしまうと
        # 別のラベル体系のページを指してしまうため、まずラベル一致を試みる。
        if self._doc is not None:
            result = self._doc.find_page_by_label(page_str)
            if result >= 0:
                return result

        # パターン2: (n)形式 → 1-indexed物理ページ
        m = re.match(r'^\((\d+)\)$', page_str)
        if m:
            n = int(m.group(1))
            return max(0, n - 1)

        # パターン3: 整数のみ → 1-indexed物理ページ（ラベルに一致しない場合のフォールバック）
        try:
            n = int(page_str)
            return max(0, n - 1)
        except ValueError:
            pass

        return None

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            # Alt+クリックは選択のみ行い、表示ページは変更しない
            self._cancel_pending_jump()
            return
        # ダブルクリック(編集開始)の前半である可能性があるため、少し待ってからジャンプする。
        # その間に同じ項目が編集開始されたり、選択が別の項目に移ったりした場合は
        # ジャンプをキャンセルする(_cancel_pending_jump系)。
        self._pending_jump_item = item
        QTimer.singleShot(
            self._JUMP_DELAY_MS,
            lambda: self._resolve_pending_jump(item),
        )

    def _resolve_pending_jump(self, item: QTreeWidgetItem) -> None:
        if self._pending_jump_item is not item:
            return
        self._pending_jump_item = None
        try:
            page = item.data(0, Qt.ItemDataRole.UserRole)
        except RuntimeError:
            return  # 遅延中に項目が削除された
        if page is not None:
            self.page_jump_requested.emit(page)

    def _cancel_pending_jump(self, item: Optional[QTreeWidgetItem] = None) -> None:
        if item is None or self._pending_jump_item is item:
            self._pending_jump_item = None

    def _cancel_stale_pending_jump(self) -> None:
        if self._pending_jump_item is not None and self._tree.currentItem() is not self._pending_jump_item:
            self._pending_jump_item = None

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        self._cancel_pending_jump(item)
        if column == 0:
            self._push_history()
            self._tree.editItem(item, 0)
        elif column == 1:
            self._push_history()
            self._tree.editItem(item, 1)

    def _toggle_page_edit_mode(self, checked: bool) -> None:
        self._page_edit_mode = checked
        self._pending_seq_seed = None
        self._spin_increment.setEnabled(checked)
        if not checked:
            return
        item = self._tree.currentItem()
        if item is None and self._tree.topLevelItemCount() > 0:
            item = self._tree.topLevelItem(0)
        if item is None:
            return
        self._cancel_pending_jump(item)
        self._tree.setCurrentItem(item)
        self._push_history()
        self._tree.editItem(item, 1)

    def _on_increment_changed(self, value: int) -> None:
        self._page_increment = value

    def _on_page_enter(self, index: QModelIndex) -> None:
        """ページ番号連続入力モード中、ページ列でEnterが押されたら次の行のページ列に移る。
        次のエディタには前の行のページ+加算値を提案として表示する。"""
        if not self._page_edit_mode:
            return
        item = self._tree.itemFromIndex(index)
        if item is None:
            return
        next_item = self._tree.itemBelow(item)
        if next_item is None:
            self._btn_page_mode.setChecked(False)
            return
        last_page0 = item.data(0, Qt.ItemDataRole.UserRole)
        self._pending_seq_seed = self._compute_seed_page(last_page0)
        self._tree.setCurrentItem(next_item)
        self._push_history()
        QTimer.singleShot(0, lambda: self._tree.editItem(next_item, 1))

    def _compute_seed_page(self, last_page0: Optional[int]) -> Optional[int]:
        if last_page0 is None or self._page_increment == self._NO_SUGGESTION:
            return None
        seed = last_page0 + self._page_increment
        if self._doc is not None and self._doc.page_count:
            seed = min(seed, self._doc.page_count - 1)
        return seed

    def _get_page_edit_seed_text(self, index: QModelIndex) -> Optional[str]:
        """連続入力モードで次のエディタを開く際の提案テキスト。使ったら消費する。"""
        if not self._page_edit_mode or self._pending_seq_seed is None:
            return None
        text = self._get_page_display_text(self._pending_seq_seed)
        self._pending_seq_seed = None
        return text

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 1:
            # SpinBoxデリゲートがUserRole+1に列1として書いた値を読み、列0のUserRole(ページ)に反映
            page = item.data(1, Qt.ItemDataRole.UserRole + 1)
            if page is not None:
                item.setData(0, Qt.ItemDataRole.UserRole, None if page == -1 else page)
                item.setData(1, Qt.ItemDataRole.UserRole + 1, None)
            self._refresh_page_label(item)
        self._emit_modified()

    def _emit_modified(self, *args) -> None:
        self.toc_modified.emit()

    def _update_button_states(self) -> None:
        has_doc = self._doc is not None
        has_sel = bool(self._tree.selectedItems())
        self._btn_add.setEnabled(has_doc)
        self._btn_del.setEnabled(has_sel)
        self._btn_up.setEnabled(has_sel)
        self._btn_down.setEnabled(has_sel)
        self._btn_left.setEnabled(has_sel)
        self._btn_right.setEnabled(has_sel)
        self._btn_page_mode.setEnabled(has_doc)
        self._spin_increment.setEnabled(has_doc and self._page_edit_mode)

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()

        def keyPressEvent(event):
            from PySide6.QtWidgets import QApplication
            if QApplication.focusWidget() is not tree:
                QTreeWidget.keyPressEvent(tree, event); return
            if event.matches(QKeySequence.StandardKey.Undo):
                self._undo(); return
            mods = event.modifiers()
            key = event.key()
            if mods & Qt.KeyboardModifier.ControlModifier:
                if key == Qt.Key.Key_Up:
                    self._move_up(); return
                if key == Qt.Key.Key_Down:
                    self._move_down(); return
                if key == Qt.Key.Key_Left:
                    self._indent_left(); return
                if key == Qt.Key.Key_Right:
                    self._indent_right(); return
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not (mods & Qt.KeyboardModifier.ShiftModifier):
                QTreeWidget.keyPressEvent(tree, event)
                if not (mods & Qt.KeyboardModifier.AltModifier):
                    item = tree.currentItem()
                    if item is not None:
                        page = item.data(0, Qt.ItemDataRole.UserRole)
                        if page is not None:
                            self.page_jump_requested.emit(page)
                return
            if mods & Qt.KeyboardModifier.ShiftModifier and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._add_entry(before=True); return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = tree.currentItem()
                if item is not None:
                    self._push_history()
                    tree.editItem(item, 1 if self._page_edit_mode else 0)
                    return
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if tree.currentItem() is not None:
                    self._delete_entry()
                    return
            QTreeWidget.keyPressEvent(tree, event)

        def closeEditor(editor, hint):
            from PySide6.QtWidgets import QAbstractItemDelegate
            if (hint == QAbstractItemDelegate.EndEditHint.RevertModelCache
                    and self._pending_item is not None):
                self._delete_item(self._pending_item)
                self._pending_item = None
                self._staged_snapshot = None
            else:
                if self._staged_snapshot is not None:
                    # 新規追加が確定: 追加前のスナップショットを履歴に積む
                    self._history.append(self._staged_snapshot)
                    if len(self._history) > self._MAX_HISTORY:
                        self._history.pop(0)
                    self._staged_snapshot = None
                self._pending_item = None
            QTreeWidget.closeEditor(tree, editor, hint)

        tree.keyPressEvent = keyPressEvent
        tree.closeEditor = closeEditor
        return tree

    @staticmethod
    def _make_btn(text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setFixedWidth(32)
        btn.setFixedHeight(24)
        btn.setStyleSheet("font-size: 12px;")
        return btn
