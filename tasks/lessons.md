# 学びの記録

## 2026-06-07

### QVBoxLayout.setAlignment(AlignHCenter) はサイズ不揃いの大量ウィジェットでレイアウトを壊す

- **状況**: 「表紙の表示位置がおかしい。最初に下にスクロールしないと何も出てこない」というバグ。527ページPDFで調査したところ、1ページ目のウィジェットが本来 `y=0` のはずが `y≈63355`（コンテナ高650,997pxの中央寄せ位置）に配置されていた。連続ページ間の間隔が常に約995pxの定数になっており、各ページ本来の高さ（1140〜1340px）と無関係だった
- **原因**: `self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)` を `QVBoxLayout` 自体に設定すると、Qt は子の実際の `setFixedSize` を無視して「コンテナ高 ÷ 項目数」の均等割り高さで配置を計算し、さらにその塊を上下中央寄せしてしまう（PySide6/Qt6 の実機検証で確認）
- **修正**: レイアウト全体ではなく、`addWidget(pw, 0, Qt.AlignmentFlag.AlignHCenter)` で個々のウィジェットに対して水平中央寄せを指定する
- **ルール**: `QVBoxLayout`/`QHBoxLayout` に大量のサイズ不揃いウィジェットを積む場合、`layout.setAlignment()` は使わず `addWidget(widget, stretch, alignment)` の第3引数で個別指定する。レイアウト全体への `setAlignment` は「項目数が少ない」「サイズが揃っている」場合は問題にならないため気づきにくい

## 2026-03-21

### Qt のキーイベントでモディファイアチェックは & を使う

- **状況**: `event.modifiers() == ShiftModifier` が Shift+↑ で失敗。実際の値は `ShiftModifier | KeypadModifier`
- **ルール**: Qtのmodifiersチェックは `==` でなく `& ` を使う。複数のモディファイアが同時に立つことがある。

### 遅延レンダリングは最初から設計に入れる

- **状況**: PDFロード時に全ページを一括レンダリングしていた → 10-20秒の待機が発生
- **修正**: プレースホルダーを即座に配置し、スクロール位置に応じて必要なページだけレンダリング
- **ルール**: ページ数が可変なビューアは最初から遅延レンダリングで設計する。全件一括処理はアンチパターン。

## 2026-03-25

### Qt レイアウト未計算時に pos().y() を使ってはいけない

- **状況**: `QTimer.singleShot(0, _render_visible)` で呼んだ時点では Qt のレイアウトが未計算。全ウィジェットの `pos().y()` が `0` になり、可視範囲判定が全ページにマッチして全242ページが一気にレンダリングされた
- **ルール**: レイアウト直後にウィジェット座標を使う処理は、座標が確定しているか確認する。ページサイズなど既知の数値から累積計算するほうが確実。

### UIスレッドブロックの調査は計測コードで段階的に絞り込む

- **状況**: 「10秒かかる」という報告に対し、fitz 初期化・TOC読み込み・レンダリングのどれが遅いか不明だった
- **方法**: `open_pdf()` の各ステップに `time.time()` を挟んで計測 → `open_pdf` 自体は 0.08s で完了 → バックグラウンドの `render_page()` に計測追加 → 全ページが並列実行されていると判明
- **ルール**: 「遅い」の原因追及は、まず UIスレッドがブロックされているか確認する。非同期化後も「全件エンキュー」という別の問題が潜んでいることがある。

### PDF保存時は garbage=4 でフルリライトする

- **状況**: xrefテーブルが壊れたPDFを `fitz.open()` で開き、オプションなしで `save()` すると破損を引き継ぐ
- **修正**: フルリライト時は `garbage=4, clean=True` を指定してxrefを完全再構築する
- **ルール**: `incremental=True` が失敗したらフルリライト。その際必ず `garbage=4` を付ける。

### 一時ファイル経由の保存は mkstemp + os.replace を使う

- **状況**: `tempfile.mktemp()` はパスを返すだけでファイルを作らない。例外時に一時ファイルが残留する。`shutil.move()` も例外時クリーンアップがない。
- **修正**: `tempfile.mkstemp()` でファイルを作成し、`os.replace()` でアトミックに置換。例外時は `os.unlink()` でクリーンアップ。
- **ルール**: 上書き保存は「一時ファイル→replace」パターンで実装する。

### QComboBox エディタはsetAutoFillBackground(True) が必要

- **状況**: QTableWidget のセルに QComboBox エディタを開くと、セルのテキストが透けて見えて重なって表示される
- **修正**: `createEditor()` で `cb.setAutoFillBackground(True)` を設定する
- **ルール**: QTableWidget の delegate でエディタを使う場合、背景を不透明にしないとテキストが二重に見える。

### 壊れたPDFを render_worker で開く際の IndexError

- **状況**: MuPDF が xref を修復できない場合、`fitz.open()` は成功するが `page_count == 0` になる。`doc[0]` で IndexError。
- **修正**: `run()` 内で `page_index >= doc.page_count` を確認してから `doc[page_index]` にアクセス。例外全体を try/except で包む。
- **ルール**: ワーカースレッドで PDF を開く時はページ数を確認してからアクセスする。

### QThreadPool で重い処理を非同期化するパターン（PySide6）

- **構成**: `QRunnable` + 別クラスの `QObject`（シグナル用）の組み合わせ
- **スレッド安全**: PyMuPDF は同一 `fitz.Document` をマルチスレッドで共有しない。ワーカーごとに `fitz.open()` して使い捨てる。
- **キャンセル**: `threading.Event` を各ジョブに持たせ、スクロールで範囲外になったら `event.set()`
- **結果の廃棄**: PDF切り替え時に `_render_generation` をインクリメントし、古い世代の結果を `_on_render_finished` で捨てる
