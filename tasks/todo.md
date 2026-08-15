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

- [ ] PyInstallerでスタンドアローン.appにパッケージング
- [ ] アイコン設定
- [ ] 最近使ったファイル履歴

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
- [x] 実GUI（`PySide6.QtTest`で実キー入力、`QT_QPA_PLATFORM=offscreen`）で以下を確認: 無修飾矢印はジャンプなし / Alt+↑↓はカーソル移動+ジャンプ / Shift+↑↓は範囲選択のみで並び替えなし / Ctrl+↑↓は複数選択を親ごとに独立して一括移動（境界での停止、親をまたぐ場合の独立動作を含む）/ Ctrl+←→で階層変更 / Shift+Enterの挿入維持 / Ctrl+Zでundo
