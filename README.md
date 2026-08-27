# mopdf

PDFの**目次（Table of Contents）** と **ページラベル** をGUIで編集・保存できるデスクトップアプリです。

## 機能

- **PDF閲覧** — スクロール連動の遅延レンダリング、ドラッグ&ドロップでファイルを開く
- **目次編集** — 階層ツリーで表示、エントリの追加・削除・並び替え・階層変更、テキスト選択モード（PDF上でドラッグしてタイトルを取得）、アンドゥ（Cmd+Z）、CSV入出力
- **ページラベル編集** — アラビア数字・ローマ数字・英字など複数スタイル、プレフィックス・開始番号の指定、CSV入出力
- **ファイル操作** — 上書き保存・別名保存、最近使ったファイル履歴

## インストール

```bash
git clone https://github.com/kamojun/mopdf.git
cd mopdf
pip install -r requirements.txt
```

**依存関係**

- Python 3.10+
- [PyMuPDF](https://pymupdf.readthedocs.io/) >= 1.23.0
- [PySide6](https://doc.qt.io/qtforpython/) >= 6.6.0

## 使い方

```bash
python main.py
```

PDFファイルをドラッグ&ドロップするか、メニューから「開く」で読み込んでください。

## macOS向けスタンドアローンアプリのビルド

Python環境なしで起動できる `mopdf.app` をPyInstallerでビルドできます。

```bash
pip install -r requirements-dev.txt
pyinstaller mopdf.spec
open dist/mopdf.app
```

- `dist/mopdf.app` が生成されます。`assets/icon.png` を差し替えて `python scripts/make_icon.py` を再実行すればアイコンを更新できます（現状は仮アイコン）。
- 未署名・未公証のアプリのため、初回起動時はFinderで`mopdf.app`を**右クリック→「開く」**を選んでください（ダブルクリックだけだとGatekeeperにブロックされます）。
