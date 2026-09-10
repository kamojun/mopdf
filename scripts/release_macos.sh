#!/usr/bin/env bash
#
# macOS配布用ビルド: 署名 → 公証(notarization) → staple → 検証 → zip作成
#
#   ./scripts/release_macos.sh 0.1.1
#
# 事前準備（初回のみ）:
#   1. Developer ID Application 証明書をキーチェーンに入れておく
#      （Xcode → Settings → Accounts → Manage Certificates… → + → Developer ID Application）
#   2. App用パスワードを appleid.apple.com で発行し、notarytoolに保存する
#      xcrun notarytool store-credentials "mopdf-notary" \
#        --apple-id "<Apple ID>" --team-id "<TEAM_ID>" --password "<App用パスワード>"
#
# 環境変数で上書きできるもの:
#   MOPDF_CODESIGN_IDENTITY  署名に使う証明書名（未指定ならDeveloper ID Applicationを自動検出）
#   MOPDF_NOTARY_PROFILE     notarytoolのプロファイル名（既定: mopdf-notary）

set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "usage: $0 <version>   (例: $0 0.1.1)" >&2
    exit 1
fi

NOTARY_PROFILE="${MOPDF_NOTARY_PROFILE:-mopdf-notary}"
ARCH="$(uname -m)"
APP="dist/mopdf.app"
ZIP="dist/mopdf-v${VERSION}-macos-${ARCH}.zip"
UPLOAD_ZIP="dist/mopdf-notarize-upload.zip"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# --- 署名に使う証明書を決める --------------------------------------------------
step "証明書を確認"
if [ -z "${MOPDF_CODESIGN_IDENTITY:-}" ]; then
    # 未検出なら grep が終了コード1を返す。set -e + pipefail の下では
    # そのままだと下の案内文を出す前にスクリプトが落ちるので || true で受ける
    MOPDF_CODESIGN_IDENTITY="$(
        security find-identity -v -p codesigning \
            | grep "Developer ID Application" \
            | head -1 \
            | sed -E 's/.*"(.*)".*/\1/' || true
    )"
fi
if [ -z "$MOPDF_CODESIGN_IDENTITY" ]; then
    cat >&2 <<'MSG'
Developer ID Application 証明書が見つかりません。

「Apple Development」証明書では配布できません（公証で弾かれます）。
Xcode → Settings → Accounts → Manage Certificates… → 左下の + →
"Developer ID Application" を選んで作成してください。
MSG
    exit 1
fi
echo "  使用する証明書: $MOPDF_CODESIGN_IDENTITY"
export MOPDF_CODESIGN_IDENTITY

# --- notarytoolの認証情報が保存済みか先に確認する -------------------------------
# ビルドに数分かかるので、認証切れならここで落としたい
step "notarytoolの認証情報を確認 (プロファイル: $NOTARY_PROFILE)"
# notarytool 1.1.2 の history に --limit は無い（付けると Unknown option で落ちる）
if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    cat >&2 <<MSG
notarytoolのプロファイル "$NOTARY_PROFILE" が使えません。
下記を実行して認証情報を保存してください（App用パスワードは appleid.apple.com で発行）:

  xcrun notarytool store-credentials "$NOTARY_PROFILE" \\
    --apple-id "<Apple ID>" --team-id "<TEAM_ID>" --password "<App用パスワード>"
MSG
    exit 1
fi
echo "  OK"

# --- ビルド -------------------------------------------------------------------
step "ビルド (署名あり)"
pyinstaller --noconfirm --clean mopdf.spec

step "署名を検証"
codesign --verify --deep --strict --verbose=2 "$APP"

# codesignの出力は一度変数に受ける。パイプで grep -q に渡すと、grepが一致した
# 時点で終了するせいでcodesign側がSIGPIPEで死に（終了コード141）、pipefailが
# それを拾ってパイプライン全体が失敗扱いになる。署名は正常なのに検証が落ちる
SIGN_INFO="$(codesign -d --verbose=2 "$APP" 2>&1)"
grep -E "Authority|TeamIdentifier|flags|Timestamp" <<<"$SIGN_INFO" | sed 's/^/  /' || true

# Hardened Runtimeが付いているか（公証の必須要件）
if ! grep -q "flags=.*runtime" <<<"$SIGN_INFO"; then
    echo "Hardened Runtime が有効になっていません。公証に通りません。" >&2
    exit 1
fi
echo "  Hardened Runtime: 有効"

# --- 公証 ---------------------------------------------------------------------
# 提出用のzipは転送用の入れ物にすぎない。公証チケットは .app 側にstapleする
step "公証用にzip化して提出（数分かかります）"
rm -f "$UPLOAD_ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$UPLOAD_ZIP"

set +e
SUBMIT_OUT="$(xcrun notarytool submit "$UPLOAD_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait 2>&1)"
SUBMIT_RC=$?
set -e
echo "$SUBMIT_OUT"

if [ $SUBMIT_RC -ne 0 ] || ! grep -q "status: Accepted" <<<"$SUBMIT_OUT"; then
    SUBMISSION_ID="$(grep -m1 -Eo '[0-9a-f-]{36}' <<<"$SUBMIT_OUT" || true)"
    echo "" >&2
    echo "公証に失敗しました。詳細ログ:" >&2
    if [ -n "$SUBMISSION_ID" ]; then
        xcrun notarytool log "$SUBMISSION_ID" --keychain-profile "$NOTARY_PROFILE" >&2 || true
    fi
    exit 1
fi
rm -f "$UPLOAD_ZIP"

# --- staple -------------------------------------------------------------------
# チケットを .app に貼り付ける。これでオフラインでも検証が通る
step "公証チケットをstaple"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

# --- 最終検証 -----------------------------------------------------------------
# staple後の .app を、Gatekeeperが実際に使う判定で確認する
step "Gatekeeperの判定を確認"
spctl -a -vvv -t install "$APP"

# --- 配布用zip ----------------------------------------------------------------
# staple後に固め直すこと。staple前のzipにはチケットが入っていない
step "配布用zipを作成"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

printf '\n\033[1m完了\033[0m\n'
echo "  ファイル : $ZIP"
echo "  サイズ   : $(du -h "$ZIP" | cut -f1)"
echo "  SHA-256  : $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
echo ""
echo "GitHub Releases にこのzipを添付してください。"
echo "利用者はダウンロードしてダブルクリックするだけで起動できます（xattr不要）。"
