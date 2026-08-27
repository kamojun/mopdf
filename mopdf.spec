# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("fitz")

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
    version="0.1.0",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
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
