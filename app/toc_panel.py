from __future__ import annotations
import csv
import io
import re
from typing import Optional
from PySide6.QtCore import Qt, Signal, QModelIndex, QTimer, QEvent
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QAbstractItemView, QStyledItemDelegate,
    QLineEdit, QFileDialog, QMessageBox, QApplication,
)

from .pdf_document import PdfDocument, TocEntry


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
    整数・論理ラベル・'?'（未設定）を受け付ける。"""

    def __init__(self, get_display_text, resolve_page, parent=None):
        super().__init__(parent)
        self._get_display_text = get_display_text  # (page0: int | None) -> str
        self._resolve_page = resolve_page           # (text: str) -> int | None

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        return editor

    def setEditorData(self, editor, index):
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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._current_page: int = 0     # MainWindowから更新される
        self._pending_item: Optional[QTreeWidgetItem] = None  # 追加直後・未確定のアイテム
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
        tb_layout.addStretch()
        layout.addWidget(toolbar)

        # ツリー（Shift+矢印でボタン操作と同等のショートカット）
        self._tree = self._make_tree()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setColumnWidth(0, 220)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, self._tree.header().ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, self._tree.header().ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(16)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
            1, PageLineDelegate(self._get_page_display_text, self._resolve_page, self)
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

        self._tree.itemSelectionChanged.connect(self._update_button_states)
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

    def add_entry_with_title(self, title: str, page_index: int) -> None:
        """テキスト選択などから外部にエントリを追加する"""
        self._add_entry(title=title, page_index=page_index)

    # ------------------------------------------------------------------
    # 内部: ツリー構築
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._history.clear()
        self._staged_snapshot = None
        entries = self._doc.get_toc() if self._doc else []
        self._build_tree_from_entries(entries)

    def _build_tree_from_entries(self, entries: list[TocEntry]) -> None:
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

    def _add_entry(self, *, title: str = "（無題）", page_index: Optional[int] = None, before: bool = False) -> None:
        if self._doc is None:
            return
        if page_index is None:
            page_index = self._current_page
        snapshot = self.get_toc()

        item = self._make_item(title, page_index)
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

    def _move_up(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        self._push_history()
        parent = item.parent()
        if parent:
            idx = parent.indexOfChild(item)
            if idx > 0:
                parent.takeChild(idx)
                parent.insertChild(idx - 1, item)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx > 0:
                self._tree.takeTopLevelItem(idx)
                self._tree.insertTopLevelItem(idx - 1, item)
        self._tree.setCurrentItem(item)
        self._emit_modified()

    def _move_down(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        self._push_history()
        parent = item.parent()
        if parent:
            idx = parent.indexOfChild(item)
            if idx < parent.childCount() - 1:
                parent.takeChild(idx)
                parent.insertChild(idx + 1, item)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx < self._tree.topLevelItemCount() - 1:
                self._tree.takeTopLevelItem(idx)
                self._tree.insertTopLevelItem(idx + 1, item)
        self._tree.setCurrentItem(item)
        self._emit_modified()

    def _indent_left(self) -> None:
        """1段上の階層に移動（親の兄弟になる）"""
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent is None:
            return  # 既にトップレベル
        self._push_history()
        grandparent = parent.parent()
        idx_in_parent = parent.indexOfChild(item)
        parent.takeChild(idx_in_parent)
        if grandparent:
            idx = grandparent.indexOfChild(parent)
            grandparent.insertChild(idx + 1, item)
        else:
            idx = self._tree.indexOfTopLevelItem(parent)
            self._tree.insertTopLevelItem(idx + 1, item)
        self._tree.setCurrentItem(item)
        self._emit_modified()

    def _indent_right(self) -> None:
        """1段下の階層に移動（直前の兄弟の子になる）"""
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent:
            idx = parent.indexOfChild(item)
            if idx == 0:
                return
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx == 0:
                return
        self._push_history()
        if parent:
            prev = parent.child(idx - 1)
            parent.takeChild(idx)
            prev.addChild(item)
        else:
            prev = self._tree.topLevelItem(idx - 1)
            self._tree.takeTopLevelItem(idx)
            prev.addChild(item)
        prev.setExpanded(True)
        self._tree.setCurrentItem(item)
        self._emit_modified()

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
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_jump_requested.emit(page)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self._push_history()
            self._tree.editItem(item, 0)
        elif column == 1:
            self._push_history()
            self._tree.editItem(item, 1)

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
        has_sel = self._tree.currentItem() is not None
        self._btn_add.setEnabled(has_doc)
        self._btn_del.setEnabled(has_sel)
        self._btn_up.setEnabled(has_sel)
        self._btn_down.setEnabled(has_sel)
        self._btn_left.setEnabled(has_sel)
        self._btn_right.setEnabled(has_sel)

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
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                key = event.key()
                if key == Qt.Key.Key_Up:
                    self._move_up(); return
                if key == Qt.Key.Key_Down:
                    self._move_down(); return
                if key == Qt.Key.Key_Left:
                    self._indent_left(); return
                if key == Qt.Key.Key_Right:
                    self._indent_right(); return
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._add_entry(before=True); return
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = tree.currentItem()
                if item is not None:
                    self._push_history()
                    tree.editItem(item, 0)
                    return
            elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
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
