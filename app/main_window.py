from __future__ import annotations
from pathlib import Path
from typing import Optional
from PySide6.QtCore import Qt, QSize, QSettings, QTimer
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QShortcut, QKeySequence, QCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QFileDialog,
    QStatusBar, QLabel, QMessageBox, QMenu, QInputDialog,
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QStyle, QCheckBox
)

from .pdf_document import PdfDocument, TocEntry, PageLabelRange
from .pdf_viewer import PdfViewer
from .toc_panel import TocPanel, INSERT_BELOW_SELECTED, INSERT_PAGE_ORDER
from .page_label_panel import PageLabelPanel
from .changes_dialog import ChangesDialog, paired_diff
from .shortcuts_dialog import ShortcutsDialog


class MainWindow(QMainWindow):
    _MAX_RECENT = 10
    _UNSAVED_CHECK_INTERVAL_MS = 5000  # 未保存アスタリスクをバックグラウンドで確認する間隔
    _LABEL_CHANGE_DEBOUNCE_MS = 700  # ページラベル連続編集をまとめるデバウンス間隔
    _MAX_HISTORY = 50  # 目次・ページラベル共通のUndo履歴の最大件数

    def __init__(self) -> None:
        super().__init__()
        self._doc = PdfDocument()
        self._unsaved = False
        self._toc_baseline: list[TocEntry] = []
        self._page_label_baseline: list[PageLabelRange] = []
        self._current_page = 0
        self._pdf_filename: Optional[str] = None
        self._settings = QSettings("mopdf", "mopdf")
        self._recent_files: list[str] = self._settings.value("recentFiles", [], type=list)
        self._select_mode_active: bool = False  # テキスト選択モードが有効かどうか
        self._pending_old_label_texts: Optional[dict[int, str]] = None
        self._pending_old_page_labels: Optional[list[PageLabelRange]] = None
        self._edit_history: list[tuple[list[TocEntry], list[PageLabelRange]]] = []

        self._setup_ui()
        self._setup_menu()
        self.setAcceptDrops(True)

        self._unsaved_check_timer = QTimer(self)
        self._unsaved_check_timer.setInterval(self._UNSAVED_CHECK_INTERVAL_MS)
        self._unsaved_check_timer.timeout.connect(self._periodic_unsaved_check)
        self._unsaved_check_timer.start()

        # ページラベル編集は複数フィールドにまたがって連続発火しうるため、
        # 一連の編集が落ち着いてから1回だけ「表示を保つか」を確認する
        self._label_change_timer = QTimer(self)
        self._label_change_timer.setSingleShot(True)
        self._label_change_timer.setInterval(self._LABEL_CHANGE_DEBOUNCE_MS)
        self._label_change_timer.timeout.connect(self._process_pending_label_change)

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("mopdf")
        self.resize(1200, 800)
        self.setMinimumSize(QSize(800, 600))

        # 左ペイン: 目次 + ページラベル を縦に分割
        self._toc_panel = TocPanel()
        self._page_label_panel = PageLabelPanel()

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self._toc_panel)
        left_splitter.addWidget(self._page_label_panel)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 1)

        # 右ペイン: PDFビューア
        self._viewer = PdfViewer()
        self._viewer.page_changed.connect(self._on_page_changed)
        self._viewer.text_selected.connect(self._on_text_selected)
        self._viewer.select_mode_requested.connect(self._on_select_mode_requested)
        self._viewer.page_jump_dialog_requested.connect(self._on_page_jump_dialog_requested)
        self._viewer.page_label_requested.connect(self._page_label_panel.add_range_at_page)

        # 左右分割
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self._viewer)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([300, 900])

        self.setCentralWidget(main_splitter)

        # ステータスバー
        self._status_label = QLabel("PDFを開いてください")
        statusbar = QStatusBar()
        statusbar.addWidget(self._status_label)
        self.setStatusBar(statusbar)

        # 目次クリック → ページジャンプ
        self._toc_panel.page_jump_requested.connect(self._viewer.scroll_to_page)
        # 目次編集 → 未保存フラグ
        self._toc_panel.toc_modified.connect(self._mark_unsaved)
        # 目次編集の直前スナップショット → 統合Undo履歴に積む(ラベルは現在の状態をそのまま添える)
        self._toc_panel.history_checkpoint_requested.connect(
            lambda snapshot: self._push_history(snapshot, self._doc.get_page_labels())
        )
        # ページラベル編集 → 即時反映 + 未保存フラグ
        self._page_label_panel.page_labels_modified.connect(self._on_page_labels_modified)
        self._page_label_panel.page_jump_requested.connect(self._viewer.scroll_to_page)

        # ビューアのページ変更 → TocPanel に現在ページを通知
        self._viewer.page_changed.connect(self._toc_panel.set_current_page)

        # Escapeキーでテキスト選択モードをキャンセル
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.activated.connect(self._cancel_select_mode)

        # Ctrl+Z: 目次・ページラベル共通のUndo(どちらにフォーカスがあっても効く)
        self._undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self._undo_shortcut.activated.connect(self._undo)

    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("ファイル")

        open_action = QAction("開く...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)

        self._recent_menu = QMenu("最近使ったファイル", self)
        file_menu.addMenu(self._recent_menu)
        self._update_recent_menu()

        file_menu.addSeparator()

        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save)
        file_menu.addAction(save_action)

        save_as_action = QAction("別名で保存...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._save_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        csv_export_menu = QMenu("CSVエクスポート", self)
        self._action_export_toc = QAction("目次をエクスポート...", self)
        self._action_export_toc.triggered.connect(self._export_toc_csv)
        self._action_export_toc.setEnabled(False)
        csv_export_menu.addAction(self._action_export_toc)
        self._action_export_labels = QAction("ページラベルをエクスポート...", self)
        self._action_export_labels.triggered.connect(self._export_labels_csv)
        self._action_export_labels.setEnabled(False)
        csv_export_menu.addAction(self._action_export_labels)
        self._action_export_both = QAction("両方エクスポート...", self)
        self._action_export_both.triggered.connect(self._export_both_csv)
        self._action_export_both.setEnabled(False)
        csv_export_menu.addAction(self._action_export_both)
        file_menu.addMenu(csv_export_menu)

        import_menu = QMenu("インポート", self)
        self._action_import_toc = QAction("目次をインポート...", self)
        self._action_import_toc.triggered.connect(self._import_toc_csv)
        self._action_import_toc.setEnabled(False)
        import_menu.addAction(self._action_import_toc)
        self._action_paste_toc = QAction("目次をクリップボードから貼り付け", self)
        self._action_paste_toc.setShortcut("Ctrl+V")
        self._action_paste_toc.triggered.connect(lambda: self._toc_panel.paste_from_clipboard())
        self._action_paste_toc.setEnabled(False)
        import_menu.addAction(self._action_paste_toc)
        self._action_import_labels = QAction("ページラベルをインポート...", self)
        self._action_import_labels.triggered.connect(self._import_labels_csv)
        self._action_import_labels.setEnabled(False)
        import_menu.addAction(self._action_import_labels)
        file_menu.addMenu(import_menu)

        file_menu.addSeparator()

        settings_action = QAction("設定...", self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self._open_settings_dialog)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("終了", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = menubar.addMenu("編集")
        self._action_show_changes = QAction("変更点を表示...", self)
        self._action_show_changes.setShortcut("Ctrl+D")
        self._action_show_changes.triggered.connect(self._show_changes_dialog)
        self._action_show_changes.setEnabled(False)
        edit_menu.addAction(self._action_show_changes)

        help_menu = menubar.addMenu("ヘルプ")
        shortcuts_action = QAction("キーボードショートカット...", self)
        shortcuts_action.setShortcut("Ctrl+/")
        shortcuts_action.triggered.connect(self._show_shortcuts_dialog)
        help_menu.addAction(shortcuts_action)

    # ------------------------------------------------------------------
    # ファイルを開く
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        if not self._confirm_discard("開く"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "PDFを開く", "", "PDF Files (*.pdf)"
        )
        if path:
            self.open_pdf(path)

    def _add_to_recent(self, path: str) -> None:
        abspath = str(Path(path).resolve())
        if abspath in self._recent_files:
            self._recent_files.remove(abspath)
        self._recent_files.insert(0, abspath)
        self._recent_files = self._recent_files[:self._MAX_RECENT]
        self._settings.setValue("recentFiles", self._recent_files)
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        existing = [p for p in self._recent_files if Path(p).exists()]
        if not existing:
            no_action = QAction("（履歴なし）", self)
            no_action.setEnabled(False)
            self._recent_menu.addAction(no_action)
            return
        for i, path in enumerate(existing):
            label = f"&{i + 1}  {Path(path).name}  [{path}]" if i < 9 else f"   {Path(path).name}  [{path}]"
            action = QAction(label, self)
            action.setData(path)
            action.triggered.connect(self._open_recent)
            self._recent_menu.addAction(action)

    def _open_recent(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        path = action.data()
        if not Path(path).exists():
            QMessageBox.warning(self, "ファイルが見つかりません", f"ファイルが見つかりません:\n{path}")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._settings.setValue("recentFiles", self._recent_files)
            self._update_recent_menu()
            return
        if not self._confirm_discard("開く"):
            return
        self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            self._doc.open(path)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"PDFを開けませんでした:\n{e}")
            return

        self._add_to_recent(path)
        self._pdf_filename = Path(path).name
        self._viewer.load(self._doc)
        self._toc_panel.load(self._doc)
        self._page_label_panel.load(self._doc)
        for action in (self._action_export_toc, self._action_export_labels,
                       self._action_export_both, self._action_import_toc,
                       self._action_paste_toc, self._action_import_labels,
                       self._action_show_changes):
            action.setEnabled(True)

        self._toc_baseline = self._toc_panel.get_toc()
        self._page_label_baseline = self._page_label_panel.get_page_labels()
        self._unsaved = False
        self._edit_history = []
        self._update_title()
        self._update_status(0)

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _save(self) -> bool:
        if not self._doc.is_open:
            return False
        toc = self._toc_panel.get_toc()
        self._doc.set_toc(toc)
        labels = self._page_label_panel.get_page_labels()
        self._doc.set_page_labels(labels)
        try:
            self._doc.save()
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました:\n{e}")
            return False
        self._toc_baseline = toc
        self._page_label_baseline = labels
        self._unsaved = False
        self._update_title()
        return True

    def _save_as(self) -> None:
        if not self._doc.is_open:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "別名で保存", "", "PDF Files (*.pdf)"
        )
        if not path:
            return
        toc = self._toc_panel.get_toc()
        self._doc.set_toc(toc)
        labels = self._page_label_panel.get_page_labels()
        self._doc.set_page_labels(labels)
        keep_protection = self._settings.value("saveAsKeepProtection", False, type=bool)
        try:
            self._doc.save(path, keep_protection=keep_protection)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました:\n{e}")
            return
        # 保存先を新しいファイルとして開き直す
        self.open_pdf(path)

    def _open_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        layout = QVBoxLayout(dialog)

        checkbox = QCheckBox("別名で保存するとき、元のPDFの保護(パスワード・権限制限)を維持する")
        checkbox.setChecked(self._settings.value("saveAsKeepProtection", False, type=bool))
        layout.addWidget(checkbox)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        dialog.setMinimumWidth(360)

        def accept() -> None:
            self._settings.setValue("saveAsKeepProtection", checkbox.isChecked())
            dialog.accept()

        ok_btn.clicked.connect(accept)
        dialog.exec()

    # ------------------------------------------------------------------
    # CSVエクスポート
    # ------------------------------------------------------------------

    def _export_toc_csv(self) -> None:
        if not self._doc.is_open:
            return
        self._toc_panel._export_csv()

    def _export_labels_csv(self) -> None:
        if not self._doc.is_open:
            return
        self._page_label_panel._export_csv()

    def _export_both_csv(self) -> None:
        if not self._doc.is_open:
            return
        self._toc_panel._export_csv()
        self._page_label_panel._export_csv()

    def _import_toc_csv(self) -> None:
        if not self._doc.is_open:
            return
        self._toc_panel._import_csv()

    def _import_labels_csv(self) -> None:
        if not self._doc.is_open:
            return
        self._page_label_panel._import_csv()

    # ------------------------------------------------------------------
    # テキスト選択モード
    # ------------------------------------------------------------------

    def _jump_to_page_text(self, text: str) -> None:
        """ページ番号またはページラベルの文字列を解決してそのページへ移動する。"""
        text = text.strip()
        if not text:
            return

        # まずページラベルで検索
        page_index = self._doc.find_page_by_label(text)

        # 見つからなければ整数（1-based物理ページ番号）として解釈
        if page_index < 0:
            try:
                phys = int(text)
                page_index = phys - 1
            except ValueError:
                return

        page_index = max(0, min(page_index, self._doc.page_count - 1))
        self._viewer.scroll_to_page(page_index)

    def _on_page_jump_dialog_requested(self) -> None:
        if not self._doc.is_open:
            return
        text, ok = QInputDialog.getText(self, "ページへ移動", "ページ番号またはラベル:")
        if ok:
            self._jump_to_page_text(text)

    def _on_select_mode_requested(self) -> None:
        self._select_mode_active = True
        self._viewer.set_select_mode(True)

    def _cancel_select_mode(self) -> None:
        if not self._select_mode_active:
            return
        self._select_mode_active = False
        self._viewer.set_select_mode(False)

    def _on_text_selected(self, text: str, page_index: int) -> None:
        self._select_mode_active = False
        self._viewer.set_select_mode(False)

        menu = QMenu(self)
        below_action = menu.addAction("選択されている項目の下に挿入")
        page_order_action = menu.addAction("ページ番号順の位置に挿入")
        chosen = menu.exec(QCursor.pos())
        if chosen is below_action:
            mode = INSERT_BELOW_SELECTED
        elif chosen is page_order_action:
            mode = INSERT_PAGE_ORDER
        else:
            return  # ポップアップをキャンセル → 追加しない

        self._toc_panel.add_entry_with_title(text, page_index, insert_mode=mode)

    # ------------------------------------------------------------------
    # ドラッグ&ドロップ
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            if not self._confirm_discard("開く"):
                return
            self.open_pdf(urls[0].toLocalFile())

    # ------------------------------------------------------------------
    # 未保存状態管理
    # ------------------------------------------------------------------

    def _on_page_labels_modified(self) -> None:
        if self._doc.is_open:
            if self._pending_old_label_texts is None:
                self._pending_old_label_texts = self._snapshot_toc_label_texts()
                self._pending_old_page_labels = self._doc.get_page_labels()
                # バースト最初の1回だけ、編集前の状態を統合Undo履歴に積む
                self._push_history(self._toc_panel.get_toc(), self._pending_old_page_labels)
            self._doc.set_page_labels(self._page_label_panel.get_page_labels())
            self._viewer.refresh_page_labels()
            self._toc_panel.refresh_page_labels()
            self._update_status(self._current_page)
            self._label_change_timer.start()
        self._mark_unsaved()

    def _snapshot_toc_label_texts(self) -> dict[int, str]:
        """目次エントリが指す各物理ページの、変更前のページラベル表示テキストを記録する。"""
        pages = {e.page for e in self._toc_panel.get_toc() if e.page is not None}
        return {p: self._doc.get_page_label_for(p) for p in pages}

    def _process_pending_label_change(self) -> None:
        """ページラベル編集が一段落した後、目次の表示が変わったエントリがあれば
        物理ページを移動して表示を保つかどうかを確認する。"""
        old_texts = self._pending_old_label_texts
        self._pending_old_label_texts = None
        self._pending_old_page_labels = None
        if not old_texts or not self._doc.is_open:
            return
        page_map: dict[int, int] = {}
        for old_page, old_text in old_texts.items():
            if not old_text:
                continue  # ラベル未設定ページはfind_page_by_labelが誤マッチしうるため除外
            if self._doc.get_page_label_for(old_page) == old_text:
                continue  # このページの表示は変わっていない
            candidate = self._doc.find_page_by_label(old_text)
            if candidate >= 0:
                page_map[old_page] = candidate
        if not page_map:
            return
        box = QMessageBox(self)
        box.setWindowTitle("ページラベルの変更")
        box.setText(
            f"ページラベルの変更により、目次の{len(page_map)}件のページ表示が変わります。"
        )
        btn_update = box.addButton("更新する", QMessageBox.ButtonRole.AcceptRole)
        btn_keep = box.addButton("ページ番号を維持する", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_update)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_keep:
            self._toc_panel.remap_entry_pages(page_map)
        elif clicked is btn_cancel:
            self._undo()

    def _push_history(self, toc_snapshot: list[TocEntry], label_snapshot: list[PageLabelRange]) -> None:
        self._edit_history.append((toc_snapshot, label_snapshot))
        if len(self._edit_history) > self._MAX_HISTORY:
            self._edit_history.pop(0)

    def _undo(self) -> None:
        if not self._edit_history or not self._doc.is_open:
            return
        # 進行中のページラベル編集バーストがあれば破棄する
        # (undoが復元した状態と食い違う比較・ダイアログが後から出ないように)
        self._pending_old_label_texts = None
        self._pending_old_page_labels = None
        self._label_change_timer.stop()

        toc_snapshot, label_snapshot = self._edit_history.pop()
        self._toc_panel._build_tree_from_entries(toc_snapshot)
        self._doc.set_page_labels(label_snapshot)
        self._page_label_panel._rebuild()
        self._viewer.refresh_page_labels()
        self._toc_panel.refresh_page_labels()
        self._update_status(self._current_page)
        self._recompute_unsaved_state()

    def _mark_unsaved(self) -> None:
        if not self._unsaved:
            self._unsaved = True
            self._update_title()

    def _periodic_unsaved_check(self) -> None:
        """バックグラウンドタイマーから定期的に呼ばれる。既に未保存扱いの時だけ、
        実際にベースラインと一致しているか確かめてアスタリスクを更新する
        (何も編集していなければ比較のしようがないのでスキップする)。"""
        if self._unsaved:
            self._recompute_unsaved_state()

    def _recompute_unsaved_state(self) -> None:
        """現在の内容をベースライン(最後の保存/読込時点)と比較して未保存状態を更新する。
        編集して元の内容に戻した場合は未保存表示も解除される。
        コストがあるので、編集の都度ではなく背景タイマーと閉じる確認の直前だけで呼ぶ。"""
        dirty = (
            self._toc_panel.get_toc() != self._toc_baseline
            or self._page_label_panel.get_page_labels() != self._page_label_baseline
        )
        if dirty != self._unsaved:
            self._unsaved = dirty
            self._update_title()

    def _update_title(self) -> None:
        name = self._pdf_filename or "mopdf"
        prefix = "* " if self._unsaved else ""
        self.setWindowTitle(f"{prefix}mopdf — {name}" if self._pdf_filename else "mopdf")
        if self._pdf_filename:
            self.setWindowTitle(f"{prefix}{name} — mopdf")

    def _compute_diff_pairs(self):
        """目次・ページラベルそれぞれの「変更前/変更後」ペアを計算する。
        目次は diff_keys(階層・タイトル・物理ページ)で同一性を判定し、表示だけ
        describe_entries(ラベル付き)を使う。これにより、ページラベルの割り当てだけを
        変更した場合は目次側の変更として検出されない(実質同じ内容とみなす)。"""
        toc_pairs = paired_diff(
            self._toc_panel.diff_keys(self._toc_baseline),
            self._toc_panel.diff_keys(self._toc_panel.get_toc()),
            self._toc_panel.describe_entries(self._toc_baseline),
            self._toc_panel.describe_entries(self._toc_panel.get_toc()),
        )
        label_pairs = paired_diff(
            self._page_label_panel.describe_ranges(self._page_label_baseline),
            self._page_label_panel.describe_ranges(self._page_label_panel.get_page_labels()),
        )
        return toc_pairs, label_pairs

    @staticmethod
    def _pairs_to_lines(pairs: list[tuple[Optional[str], Optional[str]]]) -> list[str]:
        lines = []
        for old, new in pairs:
            if old is not None:
                lines.append(f"- {old}")
            if new is not None:
                lines.append(f"+ {new}")
        return lines

    def _build_change_summary(self) -> str:
        """未保存の変更点を「【目次】」「【ページラベル】」ごとの差分テキストにまとめる。"""
        toc_pairs, label_pairs = self._compute_diff_pairs()
        sections = []
        if toc_pairs:
            sections.append("【目次】\n" + "\n".join(self._pairs_to_lines(toc_pairs)))
        if label_pairs:
            sections.append("【ページラベル】\n" + "\n".join(self._pairs_to_lines(label_pairs)))
        return "\n\n".join(sections)

    def _show_changes_dialog(self) -> None:
        """目次・ページラベルの変更点を「変更前/変更後」の左右比較モーダルで表示する。
        メニューからいつでも呼べる他、閉じる確認ダイアログの「詳細を表示...」からも呼ばれる。"""
        if self._unsaved:
            self._recompute_unsaved_state()
        toc_pairs, label_pairs = self._compute_diff_pairs()
        ChangesDialog(toc_pairs, label_pairs, self).exec()

    def _show_shortcuts_dialog(self) -> None:
        ShortcutsDialog(self).exec()

    def _confirm_discard(self, action_label: str = "閉じる") -> bool:
        """未保存の変更がある場合は確認ダイアログを出す。続行する場合True。
        action_label は「保存して{action_label}」のように文言に埋め込む動詞
        (例: closeEventからは「閉じる」、別のPDFを開く系の呼び出しからは「開く」)。"""
        # アスタリスクは「触ったら即True」の軽量フラグなので、実際に閉じる直前だけ
        # ベースラインとの内容比較を行って確定させる(何も変わっていなければ警告しない)。
        if self._unsaved:
            self._recompute_unsaved_state()
        if not self._unsaved:
            return True

        dialog = QDialog(self)
        dialog.setWindowTitle("未保存の変更")
        layout = QVBoxLayout(dialog)

        top_row = QHBoxLayout()
        icon_label = QLabel()
        icon_pixmap = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxQuestion
        ).pixmap(32, 32)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        top_row.addWidget(icon_label)

        text_col = QVBoxLayout()
        message_label = QLabel("保存されていない変更があります。続けますか？")
        message_label.setWordWrap(True)
        text_col.addWidget(message_label)

        summary = self._build_change_summary()
        if summary:
            lines = summary.split("\n")
            max_lines = 12
            if len(lines) > max_lines:
                shown = "\n".join(lines[:max_lines]) + f"\n…ほか{len(lines) - max_lines}行"
            else:
                shown = summary
            summary_label = QLabel(shown)
            summary_label.setWordWrap(True)
            text_col.addWidget(summary_label)
        top_row.addLayout(text_col, 1)
        layout.addLayout(top_row)

        if summary:
            details_row = QHBoxLayout()
            details_row.setContentsMargins(24, 4, 0, 0)
            details_btn = QPushButton("詳細表示")
            details_btn.setFlat(True)
            details_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
            details_btn.clicked.connect(self._show_changes_dialog)
            details_row.addWidget(details_btn)
            details_row.addStretch(1)
            layout.addLayout(details_row)

        layout.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("キャンセル")
        discard_btn = QPushButton(f"保存せずに{action_label}")
        save_btn = QPushButton(f"保存して{action_label}")
        save_btn.setDefault(True)
        save_btn.setAutoDefault(True)
        for btn in (cancel_btn, discard_btn, save_btn):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)
        dialog.setMinimumWidth(380)

        result = {"action": "cancel"}

        def choose(action: str) -> None:
            result["action"] = action
            dialog.accept()

        cancel_btn.clicked.connect(lambda: choose("cancel"))
        discard_btn.clicked.connect(lambda: choose("discard"))
        save_btn.clicked.connect(lambda: choose("save"))

        dialog.exec()
        if result["action"] == "save":
            return self._save()
        return result["action"] == "discard"

    # ------------------------------------------------------------------
    # ステータスバー
    # ------------------------------------------------------------------

    def _on_page_changed(self, page_index: int) -> None:
        self._current_page = page_index
        self._update_status(page_index)

    def _update_status(self, page_index: int) -> None:
        if not self._doc.is_open:
            self._status_label.setText("PDFを開いてください")
            return
        label = self._doc.get_page_label_for(page_index)
        total = self._doc.page_count
        if label:
            phys = f"({page_index + 1}/{total})"
            text = f"ページ {label} {phys}"
        else:
            text = f"ページ {page_index + 1}/{total}"
        self._status_label.setText(text)

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._doc.close()
        super().closeEvent(event)
