# 学びの記録

## 2026-08-29

### macOSでダブルクリック起動が二重起動する原因は同一bundle idの複数コピー

- **状況**: パッケージング済み`mopdf.app`（`dist/mopdf.app`）をFinderでダブルクリックしてPDFを2つ開いたら、ウィンドウが2個（＝プロセスが2個）できた。`main.py`の`Application.event()`は`QFileOpenEvent`受信時に既存の`self.window`へ`open_pdf()`するだけで新規ウィンドウは作らないコードなので、一見コードのバグに見えた
- **切り分け**: `open -a dist/mopdf.app file.pdf`を2回実行（Finderのダブルクリックと同じLaunch Services経路）→ `ps aux`で確認すると同一PIDのまま増えず、コード自体は正しく動作することを確認
- **原因**: `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -dump | grep -i "mopdf.app"` で調べたところ、`~/Desktop/mopdf.app`（8/15、過去のパッケージング検証で持ち出した残骸）と`dist/mopdf.app`の2つが同じbundle id(`com.kamojun.mopdf`)で別パス登録されていた。macOSの「既存プロセスへ回す」判定はバンドルパス単位のため、ダブルクリックのたびにどちらへ解決されるかで新規プロセスが増える
- **ルール**: macOSアプリの「ダブルクリックで既存ウィンドウに切り替わるはずが二重起動する」系の不具合は、まずコードを疑う前に`lsregister -dump | grep -i "<appname>.app"`で同一bundle idの重複登録（Desktop等に持ち出した古いコピー）を確認する。再現テストは`open -a <path> <file>`＋`ps aux`でプロセス数を見れば、Finderの実操作なしでも検証できる

## 2026-08-15

### QTreeWidgetで`model().blockSignals(True)`を使うとQt内部配線ごと止まりクラッシュする

- **状況**: 「400ページくらいの目次付きPDFの上に6ページのPDFをドロップすると落ちる」という再現性ありのセグフォルト報告。`~/Library/Logs/DiagnosticReports/`の`.ips`クラッシュレポートを解析すると、`QTreeView::viewportEvent`→`QAbstractItemDelegate::helpEvent`（ツールチップ処理）で`EXC_BAD_ACCESS`（"possible pointer authentication failure" = ダングリングポインタ疑い）だった。fitz(PyMuPDF)側の問題ではなかった
- **原因**: `toc_panel.py`の`_build_tree_from_entries`が、自前のシグナル(`itemChanged`, `rowsInserted/rowsRemoved/rowsMoved`)を止める目的で`self._tree.model().blockSignals(True)`を使っていた。しかしこれは自前のシグナルだけでなく、Qt内部で`QTreeView`（`QAbstractItemView`）がホバー中の項目（ツールチップ判定用）などの内部状態を無効化するために listen している内部配線まで止めてしまう。大きい目次を`clear()`した際、内部状態が更新されないまま、少し遅れて配送されるツールチップの`QHelpEvent`が削除済みの`QTreeWidgetItem`を参照してクラッシュした
- **修正**: `model().blockSignals()`をやめ、自前で登録しているハンドラ(`rowsInserted/rowsRemoved/rowsMoved`→`_emit_modified`)だけを一時的に`disconnect`/`reconnect`する方式に変更（`itemChanged`は`self._tree.blockSignals()`で足りる。こちらはウィジェット自身の外部向けシグナルのみで、Qt内部配線とは別物なので安全）
- **ルール**: `QTreeWidget`/`QTableWidget`などの`.model()`が返す内部モデルに対して`blockSignals(True)`を使わない。自前のシグナルだけ止めたいなら、そのシグナル/スロットの組を個別に`disconnect`/`reconnect`する。ウィジェット自身への`blockSignals()`（`itemChanged`等の外部向け便利シグナルのみ）は問題ない
- **副次的な学び**: セグフォルトの原因調査は、まず`~/Library/Logs/DiagnosticReports/`の`.ips`クラッシュレポートを確認する。シンボリケート済みのスタックトレースが残っており、`json.loads`で2番目の行（改行区切り）をパースすれば`faultingThread`のフレーム一覧が読める。的外れな仮説（このときは先にMuPDFのマルチスレッド競合を疑ったが、ヘッドレスのストレステストで再現せず、クラッシュレポートを見て初めてQTreeWidget側だと判明した）で消耗する前に、まずログを見るべきだった

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

### 検証は勝手に走らせず、必要かを聞く

- **状況**: メニュー項目の並び順を入れ替えるだけの自明な変更に対して、offscreen QPA + QTest でE2E検証を始めてしまった。検証スクリプトの実行と試行錯誤に時間がかかり、変更内容に見合わなかった。
- **ルール**: 変更が自明なとき（表示文言・並び順・定数の変更など、ロジックが動かないもの）は検証を省き、変更内容だけ報告する。ロジックを変えた場合でも、時間のかかる検証を始める前に「検証しますか」と一度聞く。CLAUDE.mdの「完了前に必ず検証する」は挙動が変わる変更に対する原則で、自明な変更にまで機械的に適用しない。

### コミットはmainに直接行う

- **状況**: main上で「commit」と言われた際に、汎用ルール（デフォルトブランチ上ならまずブランチを切る）に従って作業ブランチを作成してしまった。
- **ルール**: mopdfは個人プロジェクトで履歴も全てmainへの直線的なコミット。ブランチは切らずmainに直接コミットする。ブランチを切るのはPRを作る場合か、ユーザーが指定した場合のみ。

### 同じ作業の続きは新規コミットせず、未プッシュのコミットに畳む

- **状況**: READMEをコミットした直後、ユーザーの指摘を受けて同じREADMEを書き直し、それを別コミットとして積んでしまった。「さっきのcommitに追加」と指摘され、2つのコミットをsquashし直すことになった。
- **ルール**: 直前のコミットと同じ作業の続き（指摘を受けた手直し、書き漏らしの追加）は、未プッシュであれば新しいコミットを作らず `git reset --soft` / `--amend` で畳む。コミットメッセージとtasks/todo.mdの記述も、途中経過ではなく**最終形**を説明する内容に書き直す。別コミットにするのは、独立した意味を持つ変更のときだけ。
- **補足**: 手直しの前に自発的にコミットしないこと自体も有効。ユーザーが「commit」と言っていないタイミングで先にコミットしてしまうと、この畳み直しが発生する。

### amend前に必ずHEADと作業ツリーを確認する（別セッションが動いている前提で）

- **状況**: 上のルールに従って `git add -A && git commit --amend` を実行したが、その間にユーザーが**別セッションで**同じリポジトリを操作していた。(1) 自分のコミットは既にユーザーによってamendされ、**pushされていた**、(2) 作業ツリーには公証対応の作業中ファイル（`entitlements.plist`・`scripts/release_macos.sh`・`mopdf.spec`・todo.md）が未コミットで置かれていた。結果、**公開済みコミットを書き換え**、かつ**他人の作業中ファイルを自分のコミットに巻き込んだ**。`git reset --mixed origin/main` で復旧（ファイルの中身は無傷）。
- **ルール**:
  - `--amend` / `reset --soft` の直前に必ず `git status -sb` と `git log -1` を取り、**(a) HEADが自分の作ったコミットのままか (b) `ahead` のままで `behind`/同期していないか** を確認する。少しでも違えば畳まず、新規コミットにするかユーザーに聞く。
  - **`git add -A` を使わない。** 自分が編集したファイルだけをパス指定でstageする。`-A` は他の作業中ファイルを黙って巻き込む。
  - 一度pushされたコミットは書き換えない。畳んでよいのは未プッシュのものだけ。
- **補足**: このプロジェクトはユーザーが並行して別セッションで作業することがある。リポジトリの状態は**自分の直前の操作の続きとは限らない**前提で扱う。
