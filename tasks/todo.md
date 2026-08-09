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
