# ガスマネージャー (gas-manager)

Google Apps Script (GAS) のプロジェクトを `clasp push/pull` やブラウザ画面を使わず、AI（Claude / Gemini）・Python・CLI から**メモリ直結・爆速・安全に読み書き・関数スコープ置換・複数ファイル一括更新・深層健康診断・関数リモート実行・本番バージョン比較・デプロイ**するための統合管理ツール（FastMCP サーバー ＆ CLI）です。

📖 **背景・設計思想の記事（Qiita）**:
- [claspでやるのが馬鹿らしくなってきた ── Python MCPでGASを直撃したら、修正が爆速になってコードの質まで上がった話](https://qiita.com/shu15511551/items/228dfa134c76e15ab1a8)

---

## ⚡ はじめての方へ（1分セットアップ）

ガスマネージャーは、Google公式の `clasp` の認証トークン（`~/.clasprc.json`）をそのまま利用して Google Apps Script API / Drive API と直接高速通信します。面倒な GCP プロジェクト作成や OAuth 同意画面の設定は一切不要です。

```bash
# 1. Python 依存パッケージのインストール
pip install -r requirements.txt

# 2. セットアップ診断＆設定ページの自動起動
py gas.py setup --open
```
または、AIアシスタントに「**`py gas.py setup --open` を実行して初期設定を案内して**」と伝えるだけでOKです。

### 必要な準備（たったの2ステップ）
1. **clasp のログイン**（すでに `clasp login` 済みの方は不要です）:
   ```bash
   npm install -g @google/clasp
   clasp login
   ```
   ブラウザで Google アカウントへのアクセスを許可します（`~/.clasprc.json` にトークンが保存されます。新旧どちらの `clasp` 形式にも自動対応しています）。
2. **Google Apps Script API の有効化**:
   `--open` オプションによりブラウザで [Google Apps Script ユーザー設定](https://script.google.com/home/usersettings) が自動で開きます。
   画面内の **「Google Apps Script API」を『オン』** に切り替えてください。

---

## 🤖 MCP サーバー登録方法（Claude / Gemini / Cursor）

お使いの AI クライアントの設定ファイル（`claude_desktop_config.json` / `.mcp.json` / `mcp_config.json` 等）に以下を追加するだけで、AI が直接 GAS を操作できるようになります。

```json
{
  "mcpServers": {
    "gas-manager": {
      "command": "python",
      "args": ["C:/path/to/gas-manager/gas_mcp_server.py"]
    }
  }
}
```
※ Windows 環境で `py` ランチャーをお使いの場合は `"command": "py"` でも動作します。
※ リポジトリ内の [`SKILL.md`](./SKILL.md) を AI エージェントのスキルフォルダに配置すると、AI が最短手数（`outline` → `get_function` → `patch_function` / `batch_patch` → `diagnose`）で動くようになります。

---

## 🚀 主な特徴（なぜ爆速・高品質なのか）

1. **ローカルファイル不要・Google Apps Script API 直結（0.2秒キャッシュ応答）**:
   - `~/.clasprc.json` の OAuth2 認証トークンを利用して直接 REST API を実行（`requests.Session` の HTTP Keep-Alive 接続）。
   - ローカルディスクに作業ファイルを一切書き出さず、クラウド上の GAS をメモリ上で直接読み書きします。
   - プロジェクト一覧・コンテンツ・デプロイURL・構文検査結果の永続キャッシュにより、連続操作時は **0.2秒台** で応答します。
2. **関数スコープ限定パッチ (`patch_function`) ＆ 複数ファイル1回通信アトミック更新 (`batch_patch`)**:
   - 特定の関数ブロック内だけにスコープを絞って安全に差分置換する `patch_function`（他関数の同名コードとの衝突を100%回避）、関数丸ごと置換 `replace_function`、関数追加 `add_function`、関数削除 `delete_function` を完備。
   - サーバー（`.gs`）とフロント（`.html`）など複数ファイル・複数箇所の修正をメモリ上で合成し、一括構文検査を通した上で**1回のAPI通信でアトミックに反映する `batch_patch`** を搭載。
3. **GCP設定不要の「GAS関数リモート実行＆ログ・エラートレース回収 (`run` / `run_function`)」**:
   - 面倒な GCP Execution API 設定を一切行わずに、任意のサーバー関数を引数付きでリモート実行し、**戻り値・`console.log` / `Logger.log` の出力・例外発生時の行番号付きスタックトレース**を直接手元に回収できます。
   - また `--dev`（`dev=True`）により、再デプロイ不要で最新 `HEAD` コードの Web アプリ動作を即座にテスト可能です。
4. **GAS 特有の「ランタイム地雷」を網羅する深層健康診断 (`diagnose`)**:
   - Node.js `vm.Script` の1回起動バッチ検査（約0.1秒）に加え、単一ファイル検査では見抜けない GAS 特有のバグを徹底検出：
     - 全 `.gs` ファイル間のトップレベル **`const` / `let` / `class` グローバル重複衝突**
     - 全 `.gs` ファイル間のトップレベル**関数名重複衝突**
     - HTML `<script>` 内の `google.script.run` の**未定義関数呼び出し・プライベート関数（末尾 `_`）呼び出し・引数個数ミスマッチ**
     - `HtmlService.createTemplateFromFile` 等の**テンプレートリンク切れ**
     - **ループ（`for`/`while`/`forEach`/`map`）内の重い GAS API 呼び出し**（`UrlFetchApp.fetch` や `getValue`/`setValue` 連打による6分制限・クォータ枯渇地雷）
     - `appsscript.json`（マニフェスト）の構文・設定検査および**未使用関数（デッドコード候補）**の洗い出し
5. **二重のロールバック安全網（ローカル退避 `.backups/` ＆ Googleクラウド版履歴 `versions`）**:
   - 全ての書き込み直前にローカルの `.backups/` へ自動スナップショット退避（`diff` / `restore` で即比較・復元）。
   - さらに Google クラウド上の過去バージョン履歴（`versions`）を直接参照し、**「いま稼働中の本番バージョンと現在の最新コード（HEAD）の差分」をデプロイ前に一撃表示する `diff-prod`（`diff_version`）** や、クラウド過去版からの直接ロールバック（`restore-version`）を完備しています。

---

## 💻 CLI の主な使い方

```bash
# 0. 初期設定＆動作環境診断（未導入時も安全に実行可能）
py gas.py setup --open

# 1. プロジェクト一覧・ファイル一覧・関数構造マップ
py gas.py list
py gas.py files "MyProject"
py gas.py outline "MyProject"

# 2. プロジェクト深層健康診断（構文・グローバル衝突・RPC・ループ内重いAPI・デッドコード）
py gas.py diagnose "MyProject"

# 3. コード検索・ファイル取得・特定関数ブロック抽出
py gas.py grep "MyProject" "fetch" -e "appsscript"
py gas.py get "MyProject" main.js -s 1 -e 50
py gas.py func "MyProject" main.js doGet

# 4. 関数スコープ限定パッチ・関数追加・関数削除・関数丸ごと置換
py gas.py patch-func "MyProject" main.js doGet "置換前" "置換後"
py gas.py add-func "MyProject" main.js "function newHelper(x) { return x * 2; }"
py gas.py del-func "MyProject" main.js oldUnusedFunc
py gas.py replace-func "MyProject" main.js doGet new_func.js --deploy

# 5. 複数ファイル・複数箇所の1回通信アトミック一括更新
py gas.py batch "MyProject" ops.json --deploy

# 6. 任意のサーバー関数をリモート実行して戻り値と console.log / Logger.log を回収
py gas.py run "MyProject" myTargetFunc "[10, \"test\"]"

# 7. 本番稼働バージョン（Googleクラウド版履歴）との差分比較・復元
py gas.py versions "MyProject"
py gas.py diff-prod "MyProject"
py gas.py restore-version "MyProject" 21

# 8. ローカルバックアップ一覧・直近バックアップとの差分比較・復元
py gas.py backups "MyProject"
py gas.py diff "MyProject"
py gas.py restore "MyProject" backup_xxx.json -f main.js

# 9. デプロイ一覧確認 ＆ Webアプリの本番デプロイ
py gas.py deployments "MyProject"
py gas.py deploy "MyProject" -d "本番リリース"

# 10. Webアプリ直接呼び出し（--dev を付けると再デプロイ不要で最新HEADを実行）
py gas.py webapp "MyProject" -p "action=status"
py gas.py webapp "MyProject" -p "action=status" --dev
```

---

## 🛠️ MCP ツール一覧

FastMCP による MCP サーバー（`gas_mcp_server.py`）を提供しています。

| ツール名 | 説明 |
| :--- | :--- |
| `gas(command)` | **【統合窓口】** CLI と同じコマンド形式（`files`, `outline`, `diagnose`, `get`, `grep`, `deps`, `versions`, `diff`, `diff-prod`, `run`, `patch-func` 等）を一撃実行 |
| `setup_check` | 動作環境（Node.js・認証情報・Google API 疎通状態）の点検と導入案内 |
| `diagnose` | 深層健康診断（一括高速構文検査・関数/変数グローバル衝突・RPC/プライベート関数/引数検査・テンプレート欠落・ループ内API警告・未使用関数） |
| `list_projects` | Google Drive 上の GAS プロジェクト一覧取得 |
| `list_files` | プロジェクト内ファイル一覧（名前・種別・サイズ）取得 |
| `list_functions` | プロジェクト内（または指定ファイル内）の関数構造マップ・行範囲抽出 |
| `get_file` | ファイル全文または指定行範囲（`start_line`, `end_line`）のコード取得 |
| `get_function` | 特定関数の定義ブロック抽出（テンプレート文字列・HTML `<script>` 対応） |
| `patch_function` | **特定関数のスコープ内限定**での安全なピンポイント差分置換（Excel の `patch_procedure` 相当） |
| `replace_function` | 関数定義ブロック丸ごと置換（Excel の `replace_procedure` 相当・一撃デプロイ対応） |
| `add_function` | 新規関数の安全な追加（同名関数の重複防止ガード・構文検査付き） |
| `delete_function` | 指定関数の定義ブロック削除（構文検査・自動バックアップ付き） |
| `batch_patch` | **複数ファイル・複数関数の1回通信アトミック一括更新**（一括構文検査・トランザクション保護） |
| `patch_code` | ファイル内の文字列差分置換（複数一括置換 `patches`・自動デプロイ対応） |
| `replace_file` | ファイル丸ごと置換（diff・構文検査・自動バックアップ・自動デプロイ対応） |
| `add_file` | 新規ファイル追加（SERVER_JS / HTML 構文検査対応） |
| `delete_file` | ファイル削除（自動バックアップ付き） |
| `run_function` | **任意のGASサーバー関数を引数付きでリモート実行**し、戻り値・`console.log` / `Logger.log`・エラースタックトレースを回収 |
| `list_versions` | Google クラウド上の過去バージョン履歴一覧取得 |
| `diff_version` | **稼働中の本番バージョン（または指定バージョン）と現在の HEAD コードの差分比較** |
| `restore_version` | Google クラウド上の指定過去バージョンからの復元（全体または個別ファイル） |
| `list_backups` | ローカル自動バックアップ一覧取得 |
| `diff_backup` | ローカルバックアップ（省略時は直近）と現在の HEAD コードの差分比較 |
| `restore_backup` | ローカルバックアップからの復元（全体または個別ファイル・直前安全退避付き） |
| `search_code` | プロジェクト横断高速コード検索 (grep / 正規表現対応) |
| `list_deployments` | デプロイ一覧・バージョン番号・WebアプリURLの取得 |
| `deploy` | 新バージョン作成と本番 Web アプリ更新（未デプロイ時は新規デプロイ自動作成・404時自動救済） |
| `call_webapp` | GAS Webアプリ（doGet/doPost）直接呼び出し（プロジェクト名指定・`dev=True` 最新HEAD実行対応） |
| `add_channel` | Qクイック等の登録チャンネル管理 API 直撃追加 |

---

## 🧪 テスト・公開前機械検査の実行

実機通信をモック化した純 Python オフライン単体テスト（`test_gas_offline.py`）および公開前検査スクリプト（`publish_check.py`）を同梱しています。約 1.5 秒で全機能と安全性を検証できます。

```bash
py publish_check.py
```

---

## ライセンス

[MIT License](./LICENSE)
