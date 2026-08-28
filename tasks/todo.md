# mopdf タスク管理

## Phase 1: PDF閲覧・目次・ページラベル表示 ✅

- [x] 環境セットアップ (requirements.txt, ディレクトリ構成)
- [x] pdf_document.py（モデル層）: get/set TOC, ページラベル, レンダリング
- [x] pdf_viewer.py（右ペイン）: 遅延レンダリング, スクロール連動
- [x] toc_panel.py（目次ツリー）: 階層表示, ページジャンプ
- [x] page_label_panel.py（ページラベル一覧）
- [x] main_window.py / main.py: レイアウト, ドラッグ&ドロップ, ステータスバー
- [x] 動作確認・git初回コミット

## Phase 2: 目次編集機能 ✅

- [x] 目次エントリの追加・削除・並び替え・階層変更
- [x] タイトルのインライン編集（ダブルクリック）
- [x] ページ番号の指定（手動 or 現在ページを使用）
- [x] PDFテキスト選択 → 目次タイトルに取り込み
- [x] CSVファイルから目次を一括インポート
- [x] 書き出し（Ctrl+S 上書き保存 / Ctrl+Shift+S 別名保存）
- [x] 未保存状態のタイトルバー表示（*）

## Phase 3: ページラベル編集機能 ✅

- [x] ページラベル範囲の追加・削除・編集
- [x] スタイル選択UI（アラビア数字 / ローマ数字 / 英字）
- [x] プレビュー連動

## パフォーマンス改善 ✅

- [x] 200ページPDFのロード遅延改善（3秒→大幅短縮）
  - `get_all_page_sizes()` で全ページサイズを1パスで取得
  - `_rebuild()` で全ページを `PageWidget` として直接生成（load: ~0.07s）
  - 代替案メモ: 軽量 `QWidget` プレースホルダー方式（load: ~0.03s、メモリ効率↑）もあり。ページ数が増えたときの選択肢として。
- [x] レンダリング非同期化（UIスレッドフリーズ解消）
  - `app/render_worker.py` を新規作成（`QRunnable` + `QThreadPool`）
  - `_render_visible()` を非同期版に置き換え（`RenderWorker` をキューに投入）
  - `_pending_cancels` + `_render_generation` でキャンセル・世代管理
  - ページ切り替え・ドキュメントクローズ時に進行中ジョブをキャンセル

## Phase 4: 仕上げ

- [x] PyInstallerでスタンドアローン.appにパッケージング
- [x] アイコン設定（仮アイコン、後で差し替え予定）
- [x] 最近使ったファイル履歴

## 目次のプレーンテキスト（.txt）インポート ✅

- [x] `toc_panel.py`: `_parse_txt_list()` を追加（1行1タイトル、level=1、page=None、空行スキップ）
- [x] `toc_panel.py`: `_import_csv_from_path` を `_import_toc_from_path` にリネームし拡張子で.csv/.txtを振り分け
- [x] `toc_panel.py`: メニュー用ファイルダイアログのフィルタに.txtを追加
- [x] `toc_panel.py`: drag&drop（`dragEnterEvent`/`dropEvent`/`eventFilter`）に.txt許可を追加
- [x] `main_window.py`: サブメニュータイトル「CSVインポート」→「インポート」
- [x] 動作確認（headless Qt(offscreen)でパーサ・ディスパッチ・CSV回帰を検証）

### レビュー

- `_parse_txt_list()` は行を `strip()` するのみでタイトルを加工しない方針（ユーザー確認済み）。空行はスキップ、他は全てlevel=1・page=Noneでフラットに取り込む。
- `.csv`/`.txt` の振り分けは拡張子ベース。`_IMPORTABLE_EXTS = (".csv", ".txt")` をdrag&dropの許可判定にも共通利用し、CSV専用だった箇所を1箇所に集約。
- headless(offscreen QPA)でのスクリプト検証: (1) 空行混じりのtxtから4件が正しくlevel=1/page=Noneで抽出される (2) `_import_toc_from_path` 経由でツリーに反映される (3) 既存CSVインポート（level/title/page 3列形式）が従来通り動作する、の3点を確認。実GUIでのメニュークリック・実ドラッグ操作は未確認（環境上offscreenのみ）。
- ページラベルパネル（CSV専用）は変更なし。

## 目次: ページ番号連続入力モード ✅

タイトルのみインポートした目次に対して、ページ番号だけを連続して素早く入力したいという要望から実装。

- [x] `toc_panel.py`: ツールバーに「#」トグルボタン追加（連続入力モードON/OFF）
- [x] `PageLineDelegate`: Enterキー押下時に `on_enter(index)` コールバックを呼ぶよう拡張（Tab処理をしていた`TitleDelegate`と対称の作り）
- [x] `_on_page_enter`: モード中、Enterで確定したら `itemBelow()` で次の行のページ列に自動で移動して編集開始
- [x] 増分スピンボックス追加（`_spin_increment`, `+0`〜`+999`, 最小値`-1`を`setSpecialValueText("OFF")`で表現）
  - `+1`以上: 前の行のページ番号+増分を次の提案としてエディタに自動入力（選択状態、Enterのみで確定/上書きも可）
  - `+0`: 前の行と同じページ番号を提案（インクリメントなし）
  - `OFF`: 提案を出さない（従来通り毎回手入力）
- [x] 最終行まで到達したら自動でモードOFF
- [x] `clear()` でモード状態をリセット（ドキュメント切り替え時の混線防止）
- [x] 実GUI（`PySide6.QtTest`で実クリック・実キー入力）で連続入力・増分・OFFの全パターンを確認、スクリーンショットで目視確認済み

## TOC項目クリックによる意図しないページジャンプの防止 ✅

**背景**: 目次パネルで項目（タイトル/ページ番号セル）をクリックすると即座に `page_jump_requested` が発火し、PDFプレビューがそのページへ移動する。目次ページを表示したまま、既存項目（タイトルやページ番号）を修正したり、連続入力モードの起点として選択したりしたい場面でも無条件にジャンプしてしまい、見ていたページに戻すのが面倒という問題。

**検討した案と却下理由**:

- 列（タイトル/ページ番号）で判定を分ける → タイトル列を編集したい場合に同じ問題が残るため却下
- Alt+クリックで抑制 → 修飾キーを覚える必要がある
- 選択済み項目への再クリックで編集（Finder方式） → 初回クリック（未選択の項目をいきなり編集したい場合）には効かないため却下。想定フローの「既にページ番号が入っている項目を直したい」は初回クリックが前提になるケースが多く、これでは解決しない

**採用する方針**: シングルクリックの瞬間には即ジャンプさせず、少し（`QTimer`で`_JUMP_DELAY_MS`だけ）遅延させる。その間に同じ項目への2回目のクリック（ダブルクリック=編集開始）が来たら、保留中のジャンプをキャンセルする。当初はシステムのダブルクリック判定時間（`QApplication.doubleClickInterval()`、環境によって500ms程度）を使っていたが、単発クリックの反応が遅く感じるとのフィードバックを受けて固定値`200ms`に変更（`_JUMP_DELAY_MS`）。トレードオフとして、200msより遅いダブルクリックは編集開始前にジャンプが起きうる。

- [x] `TocPanel`に保留中ジャンプの状態（`_pending_jump_item`）を保持する変数を追加
- [x] `_on_item_clicked`: 即時 `emit` せず、`QTimer.singleShot(_JUMP_DELAY_MS, ...)` で遅延実行するよう変更（`_resolve_pending_jump`で解決、削除済みitemは`RuntimeError`を捕捉して無視）
- [x] `_on_item_double_clicked`: `_cancel_pending_jump(item)` を呼んでから既存の編集開始処理を行う
- [x] `_toggle_page_edit_mode`（「#」連続入力モード開始時の`editItem`呼び出し）でも `_cancel_pending_jump(item)` を呼ぶ（選択→即#ボタンで起点にするフローに対応）
- [x] `itemSelectionChanged`に`_cancel_stale_pending_jump`を追加接続し、保留中に選択が別項目に移った場合に保留ジャンプを破棄（stale jump防止）
- [x] `clear()` / `_build_tree_from_entries()`（undo・インポート・rebuild経由）でも保留ジャンプをリセットし、削除済みアイテム参照を残さないようにした
- [x] 実GUI（`PySide6.QtTest`の実クリック + ハンドラ直接呼び出しでダブルクリック順序を再現）で以下を確認:
  1. 単発クリック→`doubleClickInterval()`経過後に正しくジャンプする
  2. クリック直後にダブルクリックとして確定（編集開始）→ジャンプが一切起きない
  3. クリック直後に別項目へ選択が移る→古い保留ジャンプは破棄され、新しい項目のみ後でジャンプする
  4. クリック直後に「#」連続入力モードを起動→ジャンプが起きない
  5. 既存の連続入力モード（Enter連続移動・増分提案）に回帰がないことを再確認

## ページラベル変更時に目次のページ表示を保つか選べるように ✅

**背景**: 目次(TOC)は常に物理ページ番号で保持しており、ページラベルを変更しても目次側の参照ページは動かない仕様だった。物理ページベースで作った目次には正しい挙動だが、書籍の印刷ページ番号を基準に手作業で作った目次の場合、ページラベルを後から正しく設定した際に目次側も追従してほしいことがある。汎用の「再解決」コマンドではなく、ページラベル編集は稀な操作という前提で、編集直後に一度だけ確認する方式を採用。

- [x] `toc_panel.py`: `remap_entry_pages(page_map)` を追加（旧物理ページ→新物理ページのマッピングに従いエントリを更新、Undo対応、`toc_modified`発火）
- [x] `main_window.py`: `_on_page_labels_modified` を拡張。編集バースト開始時に目次エントリの表示テキストをスナップショットし、700msデバウンス後に表示が変わるエントリがあれば確認
- [x] 確認ダイアログを「更新する」（デフォルト、物理ページ固定・表示だけ更新）／「ページ番号を維持する」（物理ページを移動して表示を保つ）／「キャンセル」（このバースト中の編集を全て巻き戻す）の3択に設計
- [x] `_revert_page_labels`: キャンセル時に`self._doc`・ページラベルパネルのテーブル・目次パネルの表示・ビューアの表示を編集開始前の状態に戻す
- [x] 実機確認: 追加時は確認が出る／削除でラベルが完全に無くなる場合は移動先が存在せず確認自体が省略される（意図通りと確認済み）／キャンセルで編集前に戻る

## 大きいPDFに小さいPDFをドロップするとクラッシュする問題を修正 ✅

**背景**: 400ページ程度の目次付きPDFの上に6ページのPDFをドロップすると再現性のあるセグフォルトが発生。詳細は`tasks/lessons.md`の同日エントリを参照。

- [x] `~/Library/Logs/DiagnosticReports/`のクラッシュレポート(.ips)を解析し、`QTreeView::viewportEvent`→`QAbstractItemDelegate::helpEvent`での`EXC_BAD_ACCESS`と特定
- [x] `toc_panel.py`: `_build_tree_from_entries`/`remap_entry_pages`の`self._tree.model().blockSignals(True/False)`を、自前ハンドラ(`rowsInserted/rowsRemoved/rowsMoved`)のみを対象にした`disconnect`/`reconnect`方式に変更
- [x] headless(offscreen QPA)テストで、再構築中に`toc_modified`が過剰発火しないこと・通常編集では発火することを確認
- [x] 実機確認: 同じ手順でクラッシュしなくなったことを確認済み
- [x] 予防的修正: `pdf_document.py`/`render_worker.py`の全fitz呼び出しを`FITZ_LOCK`(`threading.RLock`)で直列化（今回のクラッシュの直接原因ではないが、MuPDFのスレッド安全性のリスクを潰す保険）

## 目次ツリーの矢印キー修飾子を再設計 ✅

**背景**: Shift+矢印が「並び替え・階層変更」に割り当てられていたが、ツリーは既に`ExtendedSelection`モードであり、Shift+矢印はQtの標準慣習では「複数選択の範囲拡張」であるべきという指摘から再設計。役割分担をShift=複数選択、Cmd(Ctrl)=編集操作、Alt+↑/↓=ページ表示追従に変更。

- [x] `_move_up`/`_move_down`を`_move_selected(delta)`に統合し、`_indent_left`/`_indent_right`と同様に複数選択（`_selected_root_items()`）に対応。親ごとにグループ化し、境界(boundary)を追跡しながら塊として1段ずつ動かすアルゴリズムを追加（新規ヘルパー`_container_ops(parent)`でQTreeWidgetItemとQTreeWidgetトップレベルのメソッド差異を吸収）
- [x] `keyPressEvent`: Shiftブロックを削除しネイティブの範囲選択・展開折りたたみに委譲。Ctrlブロックを新設し並び替え・階層変更（Up/Down/Left/Right）を割り当て。Altブロックを新設し、Up/Downでネイティブ移動後に`page_jump_requested`を直接emit。Shift+Enter（挿入）のみ維持
- [x] **既存バグを発見・修正**: `_select_items`の末尾`setCurrentItem(items[-1])`が、ツリーがフォーカスを持つ状態では複数選択を1件に潰してしまう（Qtの既定挙動）。`QItemSelectionModel.SelectionFlag.NoUpdate`を渡すよう修正し、`_indent_left`/`_indent_right`の複数選択後の選択保持も合わせて直った

## 閉じる時の確認ダイアログを3択+詳細表示に変更 ✅

**背景**: `_confirm_discard()`が`QMessageBox`の「はい/いいえ」＋「詳細を表示...」のみで、実際に保存する手段がなく「Yes/Noが何を意味するか分かりにくい」との指摘。「保存して閉じる」「保存せずに閉じる」「キャンセル」の3択＋独立した「詳細表示」に作り直した（デザインはユーザー確認済み、Mac風=右端が「保存して閉じる」で強調/デフォルト）。同じ`_confirm_discard()`を使う「別のPDFを開く」系3箇所にも波及するため、ボタン文言の動詞を呼び出し元で切り替え可能にした。

- [x] `_save()`をbool返却に変更（成功True/失敗・未オープンFalse）。既存の「保存」メニューへの影響なし
- [x] `_confirm_discard(action_label: str = "閉じる")`に変更。`QMessageBox`ではなく独自`QDialog`を組み立て、ボタン順序(キャンセル/保存せずに{action_label}/保存して{action_label})と「詳細表示」の小さめ・独立配置(左寄せ・上段)を確実に制御（QMessageBoxのButtonRole自動レイアウトはプラットフォーム依存で確実な制御ができないため採用しなかった）
- [x] `_open_file_dialog`/`_open_recent`/`dropEvent`に`_confirm_discard("開く")`を渡し、「保存して開く」「保存せずに開く」に文言を統一
- [x] 実機確認: スクリーンショットでボタン並び・詳細表示の位置/サイズを確認。プログラム的にボタンクリックを発火させ、詳細表示→ChangesDialog表示→確認ダイアログ継続、保存して閉じる→実際に保存されbaseline/`_unsaved`がリセット、action_label="開く"でのボタン文言切り替えをそれぞれ確認
- [x] 実GUI（`PySide6.QtTest`で実キー入力、`QT_QPA_PLATFORM=offscreen`）で以下を確認: 無修飾矢印はジャンプなし / Alt+↑↓はカーソル移動+ジャンプ / Shift+↑↓は範囲選択のみで並び替えなし / Ctrl+↑↓は複数選択を親ごとに独立して一括移動（境界での停止、親をまたぐ場合の独立動作を含む）/ Ctrl+←→で階層変更 / Shift+Enterの挿入維持 / Ctrl+Zでundo

## macOSスタンドアローン.appへのパッケージング ✅

**背景**: Phase 4で計画していたPyInstallerパッケージングに着手。`python main.py`実行前提だったのを、Python環境なしでダブルクリック起動できる`mopdf.app`にした。配布は当面自分用＋将来的にGitHub公開を想定（コード署名・公証は今回スコープ外、未署名アプリとして「右クリック→開く」起動が前提）。

- [x] `main.py`: `QApplication`を`Application`にサブクラス化し、`QEvent.Type.FileOpen`を捕捉して`window.open_pdf()`を呼ぶよう対応（macOSの「このアプリケーションで開く」/ Finderダブルクリックで、起動中のアプリにファイルを渡すケースに対応。既存の`sys.argv`起点の起動はそのまま維持）
- [x] `scripts/make_icon.py`: Pillowで仮アイコン（角丸正方形+"mo"）を生成し`iconutil`で`.icns`化するスクリプトを追加。`assets/icon.png`/`assets/icon.icns`を生成済み。本アイコンができたら`icon.png`を差し替えて再実行すればよい
- [x] `mopdf.spec`を新規作成。`collect_all("fitz")`でPyMuPDFのネイティブ拡張を確実にバンドルし、`BUNDLE`で`.app`化（`bundle_identifier="com.kamojun.mopdf"`、`CFBundleDocumentTypes`で`public.pdf`相当のUTIを`LSHandlerRank: Alternate`として関連付け）
- [x] **ハマりどころ**: 初回ビルドで`.app`が723MBになった。原因は`pymupdf.table.to_pandas()`（未使用の任意機能、`import pandas`はtry/except付きの遅延importでtable.py内）をPyInstallerの静的解析が到達可能コードとして辿り、開発機のグローバルPython環境にたまたま入っていたpandas/scipy/torch/networkx/matplotlib/IPython/jedi等の科学計算スタック一式を丸ごとバンドルしていたため。`mopdf.spec`の`Analysis(excludes=[...])`でこれらを明示的に除外し、167MBまで削減（アプリ自体はこれらの機能を一切使わないため機能への影響なし）
- [x] `.gitignore`: `*.spec`を無条件ignoreしていたのを`!mopdf.spec`で例外化（手動保守する設定ファイルのため追跡対象に）
- [x] `requirements-dev.txt`を新規追加（`-r requirements.txt` + `PyInstaller>=6.0`）。ビルド専用依存を実行時依存と分離
- [x] READMEに「macOS向けスタンドアローンアプリのビルド」節を追記（ビルド手順、Gatekeeper未署名のため初回は右クリック→開くが必要な旨）
- [x] ビルド確認: `pyinstaller mopdf.spec`が成功し`dist/mopdf.app`が生成されることを確認
- [x] 実機確認: 合成テストPDF（3ページ、目次3件）をCLI引数で渡して`open dist/mopdf.app --args test.pdf`起動→スクリーンショットで、コンソールウィンドウなし・メニューバーに「mopdf」表示・目次パネルに3件のChapter表示・PDF本文が正しくレンダリングされることを確認（PyMuPDFのネイティブバンドルが機能している実質的な検証）
- [ ] 未検証（今回スコープ外・ユーザー判断でテスト省略）: Cmd+S保存、QFileOpenEvent経由のダブルクリック/Open With起動、最近使ったファイル（QSettings）の永続化。いずれもコード上は妥当だが実機の自動UI操作は本セッションの環境でAccessibility権限がなく実施できなかった

## 目次のcut/paste移動機能

- [ ] 目次エントリをcutして別の場所にpasteで移動できる機能を追加

## 目次・ページラベルのUndo履歴を一本化 ✅

**背景**: 目次(TOC)編集には`toc_panel.py`内で完結したUndo（`Ctrl+Z`、`_history`、`TocPanel`のツリーがフォーカスを持つ時だけ動作）があったが、ページラベル編集にはUndoが一切なかった。別々の履歴として実装すると、(1) 「ページラベル変更時に目次のページ表示を保つ」機能（`remap_entry_pages`）が目次側の履歴に別途1件積んでしまい1つの操作が2つの履歴に分裂する、(2) 既存の`_pending_old_page_labels`/`_revert_page_labels`という専用の「元に戻す」ロジックと汎用Undoが重複する、という2つの問題が判明したため、`MainWindow`に履歴を1本化した。

- [x] `toc_panel.py`: `history_checkpoint_requested = Signal(list)`を追加。`_push_history()`の中身を`self.history_checkpoint_requested.emit(self.get_toc())`に変更（呼び出し箇所11箇所は無変更）。新規追加時の`_staged_snapshot`確定処理（`closeEditor`内）も同シグナル経由に変更。`_history`/`_MAX_HISTORY`/`_undo()`を削除し、ツリーの`keyPressEvent`が独自に処理していたCtrl+Zの横取りを削除
- [x] `main_window.py`: `_edit_history: list[tuple[list[TocEntry], list[PageLabelRange]]]`を新設し、目次・ページラベル双方のシグナルをここに集約。`_toc_panel.history_checkpoint_requested`接続時はその瞬間の現在のラベル状態を一緒に積む。ページラベル編集は既存の`_on_page_labels_modified()`のバースト検出（`_pending_old_label_texts is None`の最初の1回だけ）にそのまま便乗し、バーストごとに1件だけ積む（複数フィールド編集が1回のUndoでまとまって戻る）
- [x] `main_window.py`: `_undo()`を新設。目次・ページラベル両方を復元し、進行中のページラベル編集バーストがあれば破棄してから復元する。`_process_pending_label_change()`の「キャンセル」分岐は`self._undo()`を呼ぶだけに簡素化し、専用だった`_revert_page_labels()`は削除
- [x] `main_window.py`: `_setup_ui()`にグローバル`QShortcut(QKeySequence.StandardKey.Undo)`を追加（`self._escape_shortcut`と同じパターン）。目次ツリー・ページラベル表のどちらにフォーカスがあっても同じCtrl+Zで効く。`open_pdf()`で`_edit_history`をクリア
- [x] `shortcuts_dialog.py`: `Ctrl+Z`の説明を`TocPanel.TREE_SHORTCUTS_HELP`から、メニューにもツリーにも属さない単発`QShortcut`向けの`_MISC_SHORTCUTS_HELP`に移設
- [x] headless(offscreen QPA)スクリプトで確認: (1) 目次のみ編集→undoで目次だけ戻りラベルは無関係 (2) ページラベルのみ編集(1バースト・複数フィールド変更)→undoで1回にまとまって戻り目次は無関係 (3) 追加時の`_staged_snapshot`が`closeEditor`確定経由で正しく積まれる (4) 「ページラベル変更で目次のページ表示を保つか」ダイアログの「キャンセル」が`_undo()`を正しく呼ぶ (5) 新しいPDFを開くと履歴がクリアされる (6) 単一ウィンドウをアクティブにした状態で、ページラベル表にフォーカスがある状態から実際のCtrl+Zキーイベント(`QTest.keyClick`)を送って目次の削除が正しく取り消されることを確認（複数ウィンドウ同時存在時は`WindowShortcut`コンテキストがheadless環境で不安定になり発火しないことがあったが、これはテスト環境固有の問題で実装のバグではないと判断）
- [ ] Redo機能は今回のスコープ外（`Cmd+Shift+Z`等で再実行できるようにする）は将来の課題として残す

## 目次内検索・フィルター

- [ ] 目次パネルにタイトル文字列で検索し該当行にジャンプ/フィルター表示できるボックスを追加

## PDF表示の拡大縮小・フィット ✅

**背景**: ページ数可変のPDFビューアでは幅基準フィットだと縦長/横長ページが混在した際にノンブル（ページ下部のラベル）が見切れることがあるため、デフォルトはページ高さ基準の自動フィットを採用。手動ズームは「明示的に操作するまでは自動フィットのまま」という直感的な挙動にした。

- [x] `pdf_viewer.py`: `zoom_in`/`zoom_out`/`reset_zoom`（実際のサイズ=100%）/`fit_to_window`を追加
- [x] デフォルトはウィンドウ高さに合わせた自動フィット。手動ズーム操作後は以後ウィンドウをリサイズしても倍率を維持し、「ウィンドウに合わせる」で自動フィットに復帰できる
- [x] トラックパッドのピンチ操作（`QEvent.Type.NativeGesture` / `ZoomNativeGesture`）に対応。連続イベントをタイマーでまとめてから1回だけ適用し、全ページ再生成が毎ティック走らないようにした
- [x] ズーム変更前後で表示位置がなるべく保たれるよう、変更前のページ内スクロール位置を基準に復元
- [x] `main_window.py`: 表示メニューに拡大/縮小/実際のサイズ/ウィンドウに合わせるを追加、ステータスバーに現在のズーム%を表示
- [x] `_action_zoom_in`/`_action_zoom_out`は`setAutoRepeat(False)`（長押しで毎ティック全ページ再生成されるのを防ぐ）

## ページ番号ラベルのクリックによるページジャンプ ✅

**背景**: 各ページ下部のページ番号ラベルは表示専用で、該当ページへ直接移動する手段がなかった。既存の「ページへ移動」ダイアログをクリックの入口として再利用。

- [x] `pdf_viewer.py`: `PageWidget`にラベル描画時の矩形(`_label_rect`)を保持し、`mousePressEvent`でラベル領域クリックを検出したら`page_jump_dialog_requested`をemit（テキスト選択モード中は従来通り矩形選択を優先）
- [x] ラベル領域にホバーすると`PointingHandCursor`に切り替え（`setMouseTracking(True)`）

## 本アイコンへの差し替え・コード署名

- [ ] `assets/icon.png`が仮アイコン（角丸正方形+"mo"）のまま。本アイコンができたら差し替えて`scripts/make_icon.py`を再実行する
- [ ] 配布用`.app`が未署名でGatekeeper警告が出る。Apple Developer証明書での署名・notarizationを行う

## ショートカット一覧表示 ✅

**背景**: キーボードショートカットが増えてきたが一覧できる場所がなかった。実装時に「ショートカットを変えたら一覧側も直し忘れる」二重管理を避けるため、メニュー由来のものは`QAction`から実行時に自動収集し、目次ツリー/ページラベル表のような生の`keyPressEvent`/`eventFilter`で実装されているキー操作だけは実装のすぐ隣に唯一の説明リストを置いてダイアログがそれをimportする方針にした（目次ツリーの入力処理はTab横取り回避などQtの癖に対処した壊れやすいコードで過去にsegfaultも起きているため、`QAction`化などロジック自体には手を入れない）。

- [x] `toc_panel.py`: `_make_tree`直上に`TocPanel.TREE_SHORTCUTS_HELP`（クラス属性）を追加
- [x] `page_label_panel.py`: `eventFilter`直上に`PageLabelPanel.TABLE_SHORTCUTS_HELP`（クラス属性）を追加
- [x] `app/shortcuts_dialog.py`を新規作成。`ShortcutsDialog`が`main_window.menuBar()`を再帰的に走査してショートカット付き`QAction`を自動収集（メニュー変更時に一覧が自動追従することを実際に確認済み）、それに上記2つの定数＋単発の`Esc`（`_MISC_SHORTCUTS_HELP`、増減がほぼ無い1件のみなので例外的に直書き）を合わせて`QGroupBox`ごとに表示。キー文字列は`+`/`/`で分割し角丸のキーキャップ風`QLabel`として表示
- [x] `main_window.py`: 「ヘルプ」メニューを新設し「キーボードショートカット...」（Ctrl+/）を追加、`_show_shortcuts_dialog`から`ShortcutsDialog(self).exec()`を呼ぶ
- [x] headless(offscreen QPA)で以下を確認: メニュー一覧の自動収集内容が正しいこと／`QAction.setShortcut`を変えると一覧に自動反映されること／目次パネル10件・ページラベルパネル1件のショートカット定数が正しく読めること／ダイアログのスクリーンショットでキーキャップ表示・3セクションとも崩れず表示されることを確認

## リリース前安全性検証: 暗号化PDFの拒否と保護維持設定 ✅

**背景**: リリース前に「PDFを壊さない・元に戻せなくなるのを防ぐ」観点でコードを検証。実験の結果、(1) パスワード保護PDF(`needs_pass=1`)を開くと`viewer.load()`内部で未処理例外が発生し中途半端に壊れた状態になる、(2)「別名で保存」（常に`_full_rewrite()`経由）は暗号化・権限情報を一切保持しないため、オーナーパスワードのみ（印刷禁止など）のPDFの保護が別名保存すると黙って消える、という2点が判明。個人利用前提のため「別名保存時のデフォルトは保護を外す、必要なら設定でオプトイン」という方針を採用。

- [x] `pdf_document.py`: `open()`を「新しいファイルを検証してから成功時のみ既存ドキュメントを差し替える」順序に再構成。`needs_pass=1`のPDFは`ValueError`を送出して拒否（副次的に、従来あった「新規オープン失敗時に`self._doc`が閉じた無効なドキュメントを指したまま残る」バグも同時に解消）
- [x] `main_window.open_pdf()`の既存`try/except`がこの`ValueError`をそのまま拾い`QMessageBox`でエラー表示することを確認（`main_window.py`側の変更は不要だった）
- [x] `pdf_document.py`: `save()`/`_full_rewrite()`に`keep_protection`パラメータを追加。`True`の場合`encryption=fitz.PDF_ENCRYPT_KEEP`と`permissions=self._doc.permissions`を両方明示的に渡す（`encryption=KEEP`だけでは権限ビットが`4095`=フルアクセスにリセットされてしまうことを実験で確認したため）。同一パスへの上書き保存（Ctrl+S、`incremental`失敗時のフォールバック含む）は常に`keep_protection=True`固定
- [x] `main_window.py`: `_open_settings_dialog()`を新設（チェックボックス1つ「別名で保存するとき、元のPDFの保護を維持する」、`QSettings`キー`saveAsKeepProtection`でデフォルト`False`）。メニューに`QAction.MenuRole.PreferencesRole`付きで追加（macOSのアプリメニューに自動配置される）
- [x] `main_window.py`: `_save_as()`が設定値を読んで`keep_protection`を渡すよう変更
- [x] headless(offscreen QPA)スクリプトで以下を確認: (1) パスワード保護PDFが`open()`で拒否され`is_open=False`のまま／`MainWindow.open_pdf()`で未処理例外が伝播せずエラーダイアログ経路に乗る (2) オーナーパスワードのみのPDFで通常の上書き保存は保護を維持（回帰） (3) 別名保存はデフォルト(`keep_protection=False`)で保護が外れる (4) 設定ONなら別名保存でも元のオーナーパスワード・権限ビットが維持される(`authenticate`で確認) (5) 設定ダイアログのチェック状態が`QSettings`に永続化され再読み込み後も反映される (6) 非暗号化PDFの開く/上書き保存/別名保存が従来通り動作する
- [x] 検証時に発見した副次的な事実（実装はスコープ外のまま`project_pdf_save_safety.md`にメモ）: ページラベル編集にはUndoが未実装（TOC編集のみCtrl+Zあり）、保存前のバックアップ機構なし、同一パス上書きの通常保存自体は今回の検証で問題なしと確認

## 目次ゼロからの新規入力フロー: Enterキーでタイトル⇄ページ番号を連続入力 ✅

**背景**: 目次のないPDFに最初から目次を作っていくフローで、タイトル入力→Enter→ページ番号入力→Enter→次のタイトル…と、マウスに触れず連続入力したいという要望。既存の「ページ番号連続入力モード」（`#`トグル）はタイトルが埋まっている目次にページ番号だけ後付けするための別機能で、今回の「まっさらな状態から作る」フローとは別物として扱った。

- [x] `TitleDelegate`: Tabのみ拾っていたキー判定に`Key_Return`/`Key_Enter`を追加（コンストラクタ引数も`on_tab`→`on_advance`にリネーム）。タイトル編集中のEnterはTabと同じ「同じ行のページ番号列編集へ移動」に統一
- [x] `_on_page_enter`: 既存の連続入力モード（`_page_edit_mode`）分岐はそのまま残し、通常時（モードOFF）の新しい分岐を追加。`itemBelow()`で次の項目を判定し、あれば次の項目のタイトル列編集へ、なければ`_add_entry(before=False)`で新規項目を作成してそのタイトル編集へ
- [x] headless(offscreen QPA, `PySide6.QtTest`で実キー入力)で以下を確認: (1) タイトルEnterでページ列編集に切り替わる (2) 末尾項目でページEnter→新規項目作成・タイトル編集に移る、を繰り返せる (3) 途中の項目でページEnterを再度押すと新規作成せず次の項目のタイトル編集に移る (4) Escapeでの新規項目キャンセル（既存機能）に回帰なし
- [x] 副次的な発見: Escapeで新規項目をキャンセルする際に`QAbstractItemView::commitData called with an editor that does not belong to this view`というQt警告が出るが、これは今回の変更と無関係の既存挙動（変更前のコードでも「+」ボタン→Escapeのみで再現）。実害はなく（項目は正しく削除される）、今回のスコープ外として未修正
