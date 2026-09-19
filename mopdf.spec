# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("fitz")

# 配布用に署名する場合のみ、環境変数で証明書を指定する。
#   MOPDF_CODESIGN_IDENTITY="Developer ID Application: ... (TEAMID)" pyinstaller mopdf.spec
# 未設定なら従来どおりad-hoc署名になる（開発中のビルドはこれでよい）。
# identityを渡すとPyInstallerがcodesignに --options=runtime (Hardened Runtime) と
# --timestamp を自動で付与する。どちらも公証(notarization)の必須要件。
# BUNDLEはEXEからこの2つを引き継いで .app 全体を署名するので、EXEにだけ渡せばよい。
CODESIGN_IDENTITY = os.environ.get("MOPDF_CODESIGN_IDENTITY") or None
ENTITLEMENTS_FILE = "entitlements.plist" if CODESIGN_IDENTITY else None

# アプリのバージョン。配布用ビルドでは scripts/release_macos.sh が引数から設定する
# （CIではタグ名から）。開発中のビルドは 0.0.0 のままでよい。
VERSION = os.environ.get("MOPDF_VERSION") or "0.0.0"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pymupdf.table.to_pandas() が関数内で `import pandas` する（未使用の機能・
    # try/exceptで囲まれている）。このアプリではテーブル抽出機能を使わないが、
    # PyInstallerの静的解析はこの未到達コードパスも辿ってしまい、開発環境に
    # たまたま入っている pandas/scipy/torch などの巨大な科学計算スタックを
    # 丸ごとバンドルしようとする。明示的に除外する。
    excludes=[
        "pandas",
        "scipy",
        "numpy",
        "torch",
        "functorch",
        "networkx",
        "sympy",
        "matplotlib",
        "IPython",
        "jedi",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mopdf",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="mopdf",
)

app = BUNDLE(
    coll,
    name="mopdf.app",
    icon="assets/icon.icns",
    bundle_identifier="com.kamojun.mopdf",
    version=VERSION,
    info_plist={
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "PDF Document",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }
        ],
    },
)
