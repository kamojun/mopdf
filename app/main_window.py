from __future__ import annotations
from pathlib import Path
from typing import Optional
from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QFileDialog,
    QStatusBar, QLabel, QMessageBox, QToolBar, QPushButton, QLineEdit, QMenu
)

from .pdf_document import PdfDocument
from .pdf_viewer import PdfViewer
from .toc_panel import TocPanel
from .page_label_panel import PageLabelPanel


class MainWindow(QMainWindow):
    _MAX_RECENT = 10

    def __init__(self) -> None:
        super().__init__()
        self._doc = PdfDocument()
        self._unsaved = False
        self._current_page = 0
        self._pdf_filename: Optional[str] = None
        self._settings = QSettings("mopdf", "mopdf")
        self._recent_files: list[str] = self._settings.value("recentFiles", [], type=list)

        self._setup_ui()
        self._setup_menu()
        self.setAcceptDrops(True)

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
        # ページラベル編集 → 即時反映 + 未保存フラグ
        self._page_label_panel.page_labels_modified.connect(self._on_page_labels_modified)
        self._page_label_panel.page_jump_requested.connect(self._viewer.scroll_to_page)

        # ビューアのページ変更 → TocPanel に現在ページを通知
        self._viewer.page_changed.connect(self._toc_panel.set_current_page)

        # テキスト選択モードトグルボタン（ツールバー）
        toolbar = QToolBar("ツール")
        toolbar.setMovable(False)
        self._btn_select_mode = QPushButton("📄 テキスト選択モード")
        self._btn_select_mode.setCheckable(True)
        self._btn_select_mode.setEnabled(False)
        self._btn_select_mode.setToolTip("PDFテキストを選択して目次エントリのタイトルに使用")
        self._btn_select_mode.toggled.connect(self._on_select_mode_toggled)
        toolbar.addWidget(self._btn_select_mode)

        toolbar.addSeparator()

        self._page_input = QLineEdit()
        self._page_input.setPlaceholderText("ページへ移動...")
        self._page_input.setFixedWidth(130)
        self._page_input.setEnabled(False)
        self._page_input.returnPressed.connect(self._on_page_jump_input)
        toolbar.addWidget(self._page_input)

        self.addToolBar(toolbar)

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
        self._action_import_labels = QAction("ページラベルをインポート...", self)
        self._action_import_labels.triggered.connect(self._import_labels_csv)
        self._action_import_labels.setEnabled(False)
        import_menu.addAction(self._action_import_labels)
        file_menu.addMenu(import_menu)

        file_menu.addSeparator()

        quit_action = QAction("終了", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ------------------------------------------------------------------
    # ファイルを開く
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        if not self._confirm_discard():
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
        if not self._confirm_discard():
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
        self._btn_select_mode.setEnabled(True)
        self._page_input.setEnabled(True)
        for action in (self._action_export_toc, self._action_export_labels,
                       self._action_export_both, self._action_import_toc,
                       self._action_import_labels):
            action.setEnabled(True)

        self._unsaved = False
        self._update_title()
        self._update_status(0)

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not self._doc.is_open:
            return
        toc = self._toc_panel.get_toc()
        self._doc.set_toc(toc)
        labels = self._page_label_panel.get_page_labels()
        self._doc.set_page_labels(labels)
        try:
            self._doc.save()
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました:\n{e}")
            return
        self._unsaved = False
        self._update_title()

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
        try:
            self._doc.save(path)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました:\n{e}")
            return
        # 保存先を新しいファイルとして開き直す
        self.open_pdf(path)

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

    def _on_page_jump_input(self) -> None:
        if not self._doc.is_open:
            return
        text = self._page_input.text().strip()
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
        self._page_input.clear()
        self._viewer.setFocus()

    def _on_select_mode_toggled(self, enabled: bool) -> None:
        self._viewer.set_select_mode(enabled)
        if enabled:
            self._btn_select_mode.setStyleSheet("background: #ffe066; font-weight: bold;")
        else:
            self._btn_select_mode.setStyleSheet("")

    def _on_text_selected(self, text: str, page_index: int) -> None:
        self._toc_panel.add_entry_with_title(text, page_index)
        # 選択後はモードを解除
        self._btn_select_mode.setChecked(False)

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
            if not self._confirm_discard():
                return
            self.open_pdf(urls[0].toLocalFile())

    # ------------------------------------------------------------------
    # 未保存状態管理
    # ------------------------------------------------------------------

    def _on_page_labels_modified(self) -> None:
        if self._doc.is_open:
            self._doc.set_page_labels(self._page_label_panel.get_page_labels())
            self._viewer.refresh_page_labels()
            self._toc_panel.refresh_page_labels()
            self._update_status(self._current_page)
        self._mark_unsaved()

    def _mark_unsaved(self) -> None:
        if not self._unsaved:
            self._unsaved = True
            self._update_title()

    def _update_title(self) -> None:
        name = self._pdf_filename or "mopdf"
        prefix = "* " if self._unsaved else ""
        self.setWindowTitle(f"{prefix}mopdf — {name}" if self._pdf_filename else "mopdf")
        if self._pdf_filename:
            self.setWindowTitle(f"{prefix}{name} — mopdf")

    def _confirm_discard(self) -> bool:
        """未保存の変更がある場合は確認ダイアログを出す。続行する場合True。"""
        if not self._unsaved:
            return True
        reply = QMessageBox.question(
            self, "未保存の変更",
            "保存されていない変更があります。続けますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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
