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
  - `_rebuild()` で軽量 `QWidget` プレースホルダーを生成（PageWidget は不要）
  - スクロール時に `_ensure_page_widget()` で必要分だけ PageWidget に昇格
- [x] レンダリング非同期化（UIスレッドフリーズ解消）
  - `app/render_worker.py` を新規作成（`QRunnable` + `QThreadPool`）
  - `_render_visible()` を非同期版に置き換え（`RenderWorker` をキューに投入）
  - `_pending_cancels` + `_render_generation` でキャンセル・世代管理
  - ページ切り替え・ドキュメントクローズ時に進行中ジョブをキャンセル

## Phase 4: 仕上げ

- [ ] PyInstallerでスタンドアローン.appにパッケージング
- [ ] アイコン設定
- [ ] 最近使ったファイル履歴
