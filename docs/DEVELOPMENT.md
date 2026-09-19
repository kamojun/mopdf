# 開発者向けメモ

ビルドと配布（リリース）の手順をまとめています。アプリの使い方は [README](../README.md) を参照してください。

## macOS向けスタンドアローンアプリのビルド

Python環境なしで起動できる `mopdf.app` をPyInstallerでビルドできます。

```bash
pip install -r requirements-dev.txt
pyinstaller mopdf.spec
open dist/mopdf.app
```

- `dist/mopdf.app` が生成されます。アイコンを更新する場合は `assets/icon.png` を差し替えて `python scripts/make_icon.py` を再実行してください（Pillowが必要です）。
- 自分でビルドした `mopdf.app` はそのまま起動できます（隔離属性が付かないため、Gatekeeperの確認は出ません）。この手順ではad-hoc署名になります。

## 配布用ビルド（署名・公証つき）

Releasesで配布しているzipは、次のスクリプトで作っています（通常は後述のGitHub Actionsが実行します）。

```bash
./scripts/release_macos.sh 0.1.1
```

ビルド → 署名 → 公証（notarization）→ staple → Gatekeeper判定の確認 → 配布用zip作成までを一括で行います。実行には次の2つが必要です。

- **Developer ID Application 証明書**（Apple Developer Programの加入が必要）。Xcode → Settings → Accounts → Manage Certificates… → ＋ → Developer ID Application で作成します。開発用の「Apple Development」証明書では配布できません
- **notarytoolの認証情報**。[appleid.apple.com](https://appleid.apple.com/) でApp用パスワードを発行し、次のコマンドで保存します（`--password` を省略すると安全なプロンプトで入力できます）

  ```bash
  xcrun notarytool store-credentials "mopdf-notary" \
    --apple-id "<Apple ID>" --team-id "<Team ID>"
  ```

アプリのバージョン（`Info.plist`）はスクリプトの引数から設定されます（`mopdf.spec` は環境変数 `MOPDF_VERSION` を読み、未設定なら `0.0.0`）。

`mopdf.spec` は環境変数 `MOPDF_CODESIGN_IDENTITY` が設定されているときだけ署名を行います。未設定なら従来どおりad-hoc署名なので、開発中の `pyinstaller mopdf.spec` の挙動は変わりません。署名時はPyInstallerが `--options=runtime`（Hardened Runtime）と `--timestamp` を自動で付与します。どちらも公証の必須要件です。

Hardened RuntimeはCPython/Qtが必要とする動作を既定で禁止するため、`entitlements.plist` で例外を指定しています。

なお配布用zipは `ditto -c -k --sequesterRsrc --keepParent` で固めます（`zip`コマンドはアプリバンドル内のシンボリックリンクを壊すことがあります）。**staple の後に固めること** — 公証チケットは `.app` に貼り付けられるため、staple前に作ったzipにはチケットが入りません。

## GitHub Actions による自動リリース

`vX.Y.Z` 形式のタグをpushすると、[.github/workflows/release.yml](../.github/workflows/release.yml) が上記のスクリプトをGitHubのmacOSランナー（Apple Silicon）で実行し、できたzipを**下書き**のReleaseに添付します。

```bash
git tag v0.1.2
git push origin v0.1.2
```

1. GitHubのActionsタブで、Environment `release` の承認待ちになったジョブを「Approve」する
2. ビルド・署名・公証が終わると（初回は公証に時間がかかることがあります）、Releasesに下書きができる
3. 下書きの「変更点」を書いて公開する

失敗した場合は、原因を直したうえで下書きとタグを削除し（`git push --delete origin v0.1.2 && git tag -d v0.1.2`）、付け直します。

### 初回の準備

1. **証明書の書き出し**: キーチェーンアクセス →「ログイン」→「自分の証明書」で「Developer ID Application: …」を選び（秘密鍵ごと）、右クリック →「書き出す」で `.p12` 形式・パスワード付きで保存します。
2. **App Store Connect APIキーの発行**: [App Store Connect](https://appstoreconnect.apple.com/) →「ユーザとアクセス」→「統合」→「App Store Connect API」で**チームキー**をアクセス権「Developer」で作成します。`.p8` ファイルは一度しかダウンロードできません。Key ID と Issuer ID を控えておきます。
3. **Environmentの作成**: GitHubのリポジトリ → Settings → Environments →「New environment」で `release` を作成し、次を設定します。
   - Required reviewers: 自分
   - Deployment branches and tags: 「Selected branches and tags」→「Add deployment branch or tag rule」で、**Ref type を「Tag」に切り替えて** `v*` を追加（初期値の「Branch」のままだとブランチ名のルールになり、タグからの実行が "not allowed to deploy to release due to environment protection rules" で弾かれる）
4. **Secretsの登録**: 作成した Environment `release` の「Environment secrets」に次の6つを登録します。

   | 名前 | 値 |
   | --- | --- |
   | `BUILD_CERTIFICATE_BASE64` | `base64 -i 証明書.p12 \| pbcopy` でコピーした文字列 |
   | `P12_PASSWORD` | `.p12` 書き出し時のパスワード |
   | `KEYCHAIN_PASSWORD` | 任意のランダム文字列（ランナー上の一時キーチェーン用） |
   | `NOTARY_API_KEY_BASE64` | `base64 -i AuthKey_XXXX.p8 \| pbcopy` でコピーした文字列 |
   | `NOTARY_API_KEY_ID` | APIキーの Key ID |
   | `NOTARY_API_ISSUER_ID` | APIキーの Issuer ID |

   登録後は手元の `.p12` を削除し、`pbcopy < /dev/null` でクリップボードを空にしておきます（`.p8` は安全な場所に保管）。
