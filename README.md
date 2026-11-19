# ガスマネージャー (gas-manager)
**今ある表と文書を、どの AI からでも、頼み 1 つで、安全に直す**

Google Drive 上にあるスプレッドシートやドキュメントを、AI（Claude / Gemini）・Python・CLI から直接・高速・安全に編集・修復・集計・自動化するための統合管理ツール（MCP サーバー ＆ CLI）です。

### 🌟 3 つの強み
1. **今ある物をその場で直す**：Google Drive にある、人が現場で毎日触っている本物のスプレッドシートと文書を直接操作します。
2. **安全（壊さない・元に戻せる）**：書き換え前に自動で控えを取り、`ws_undo` で寸分違わず元の状態に戻せます。場所が曖昧な消去指示は撃たずに聞き返します。
3. **どの AI からでも**：標準 MCP 規格に対応。Claude・Gemini（Antigravity）など、どの AI クライアントからでもワンフレーズで指示できます。

> **Claude Sheets（ブラウザ内表計算）との違い**
> - **相手の違い**：Claude Sheets は白紙からブラウザ画面内で表を作るツール。GAS マネージャーは **Drive にある既存の業務ファイル** を直接直します。
> - **安全性の違い**：GAS マネージャーは変更前の自動バックアップ・指紋比較・`ws_undo` によるロールバックを備えています。
> - **道具の軽さ**：`GAS_MCP_ONLY=ws` を指定すれば、わずか 4 つの道具（`ws_look` / `ws_find` / `ws_do` / `ws_undo`）・説明 720 文字で AI のコンテキストを圧迫せず軽快に動作します。

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

**表（スプレッドシート・文書）を直すだけなら、この起こし方が速くて安い**: `env` に `GAS_MCP_ONLY=ws` を足すと、道具は Workspace の 4 本（`ws_do`・`ws_look`・`ws_find`・`ws_undo`）だけになります。AI が読む道具の説明が 59 本分から 4 本分に減り、頼み 1 つの返事が早くなります。AI は `ws_do(ask="使う人の頼みの文")` を 1 回撃つだけで、道具が棚を当てて引数を組み、控えを取ってから書きます。

```json
{
  "mcpServers": {
    "gas-ws": {
      "command": "python",
      "args": ["C:/path/to/gas-manager/gas_mcp_server.py"],
      "env": { "GAS_MCP_ONLY": "ws" }
    }
  }
}
```
※ リポジトリ内の [`SKILL.md`](./SKILL.md) を AI エージェントのスキルフォルダに配置すると、AI が最短手数（`outline` → `get_function` → `patch_function` / `batch_patch` → `diagnose`）で動くようになります。

---

## 🚀 主な特徴（設計と品質管理）

1. **ローカルファイル不要・Google Apps Script API 直結（0.2秒キャッシュ応答）**:
   - `~/.clasprc.json` の OAuth2 認証トークンを利用して直接 REST API を実行（`requests.Session` の HTTP Keep-Alive 接続）。
   - ローカルディスクに作業ファイルを一切書き出さず、クラウド上の GAS をメモリ上で直接読み書きします。
   - プロジェクト一覧・コンテンツ・デプロイURL・構文検査結果の永続キャッシュにより、連続操作時は **0.2秒台** で応答します。
2. **関数スコープ限定パッチ (`patch_function`) ＆ 複数ファイル1回通信アトミック更新 (`batch_patch`)**:
   - 特定の関数ブロック内だけにスコープを絞って安全に差分置換する `patch_function`（他関数の同名コードとの衝突を回避）、関数丸ごと置換 `replace_function`、関数追加 `add_function`、関数削除 `delete_function` を完備。
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
   - さらに Google クラウド上の過去バージョン履歴（`versions`）を直接参照し、**「いま稼働中の本番バージョンと現在の最新コード（HEAD）の差分」をデプロイ前に直接表示する `diff-prod`（`diff_version`）** や、クラウド過去版からの直接ロールバック（`restore-version`）を完備しています。

6. **書き換え後の「壊したか自動復元」と「GASドック / 高速化レシピ棚」**:
   - 関数削除やパッチ適用時に、HTML側の RPC リンク切れや重複関数などの破壊的不整合をインメモリで瞬時に検知。新しく不整合が発生した場合は直前の状態へ自動復元します。
   - `dock`（GASドック）により100点満点の健康点と具体的な直す手処方箋を提示し、`recipe`（高速化レシピ棚）によりループ内 appendRow の一括配列化（R01）や CacheService 包装（R04）を自動適用できます。

8. **スプレッドシート付属スクリプト（コンテナバインド）の名前呼び出し対応**:
   - Google Drive の仕様上、スプレッドシート等の拡張機能から作成されたスクリプトは Drive API のファイル一覧検索から除外されます。
   - 本ツールではエイリアス（別名マッピング）機能により、一度スクリプト ID と名前を紐付けることで、スタンドアロンプロジェクトと同様に「名前指定」で一覧表示・編集・診断・デプロイがシームレスに行えます。

---

## ⚡ GASコンボ（シートの右の枠から、言葉で直す）

スプレッドシートの右の枠に「タイトルの文字の色を赤に」のように書くと、棚に当たる頼みは AI を通さずにその場で直します。棚に当たらない頼みだけを AI に回します。

**テンプレート版（いちばん手軽）**
```bash
py gas.py combo template
```
- 返ってきた `copy_url` を開いて「コピーを作成」→ 開き直すとメニューに「⚡ GASコンボ」が出ます → 初回だけ権限を許可すれば使えます（つなぎコード貼り・アドイン導入・デプロイ操作が不要で、サイドバーから Sheets API 直結 0.3〜0.6 秒で動きます）。
- 2 回目以降は同じテンプレートに入れ直します（新しく作り直すときだけ `--new`、名前を変えるときは `--title 名前`）。
- 人に配るときは、本体のライブラリ（`shu-gas-combo-engine`）とテンプレートの共有を「リンクを知っている全員（閲覧者）」にする必要があります（道具は共有設定を変えません）。

**入れ方（1 人 1 回・どのシートでも使える）＝アドイン版（おすすめ）**
```bash
py gas.py combo addon
```
- AI（Claude Code・Antigravity 等）に「GASコンボを入れて」と頼めば、点検・clasp の導入とログイン・`combo addon` まで AI が進めます。人が押すのは Google の画面の許可・API のオン・「インストール」の 3 か所だけです。
- 初回は、本体のライブラリ `shu-gas-combo-engine` と、アドインのプロジェクト「GASコンボ（アドイン）」を**ご自分の Drive に作ります**。
- 返事の `editor` を開き、「デプロイ」→「デプロイをテスト」→「インストール」を 1 回だけ押します。
- あとは、どのスプレッドシートでも、右の枠の ⚡「GASコンボ」から使えます（シートにコードは入れません。初回に権限の許可が 1 回出ます）。
- 道具を直したら、もう一度 `py gas.py combo addon` を撃つだけで入れ直しになります（テスト デプロイは最新のコードで動きます）。
- **1 回で開く（おすすめ）**：Chrome 拡張 `ws_browser_ext/` を入れておくと、拡張のアイコン（または Alt+G）で、ブラウザの右のサイドパネルに GASコンボが開きます。今開いているシートが相手で、タブを替えると相手も替わります（画面の番地は `combo addon` が拡張のフォルダに書きます。書いたあと、chrome://extensions で拡張を「再読み込み」）。
- 右の枠の「操作窓を開く」でも、前のサイドバーと同じ画面が別の小さな窓で開きます。入力欄のカーソルが残るので、音声入力→Enter を続けられ、棚に当たる頼みは 0.3〜0.5 秒です（Sheets API を画面から直接叩きます）。
- 右の枠のカードから直接撃つこともできます（0.5〜1 秒。ボタンのたびにカードが描き直されます）。

**速い版（シートごと）＝つなぎコード版**
```bash
py gas.py combo connect <スプレッドシートの URL または ID>
```
- そのシートに、ライブラリへつなぐ 30 行ほどのコード（`コード.gs`）を置きます。シートを開き直すとメニューに「⚡ GASコンボ」が出ます。
- サイドバーから Sheets API を直接叩くので、棚に当たる頼みは 0.3〜0.6 秒です。

**使い方**
- 頼みを書いて「実行」。「直前を取り消す」で戻せます。
- 「控え」に印を付けると、書く前に控えを取る道（少し遅い）になります。印が無いときは、サイドバーが直前の状態を覚えて戻します。
- 消す・上書きする頼みは、「確認なし」に印を付けたときだけ撃ちます。

**AI の頭（棚に当たらない頼み）**
- **郵便受け（既定）**：PC で `py gas.py combo watch <スクリプトID>` を動かしておくと、`claude -p` など手元の AI が答えます。API 鍵は要りません。
- **API 鍵**：設定のタブで Gemini / Claude の API 鍵を入れます。鍵は**使う人ごとの置き場（UserProperties）**に入り、画面には有無だけが出ます。

**ブラウザ連動（任意）**：`ws_browser_ext/` を Chrome の「パッケージ化されていない拡張機能を読み込む」で入れると、Python の操作窓（`GAS操作窓を開く.bat`）が、今開いているシートと選択範囲をボタン無しで受け取ります。受けるのは自分の PC（127.0.0.1）の中だけです。

## 💡 スプレッドシート付属スクリプト（コンテナバインド）の利用方法

Googleスプレッドシート・ドキュメント・フォーム等の「拡張機能 > Apps Script」で作成されたスクリプトを操作したい場合、初回のみスクリプト ID を登録することで、以降はプロジェクト名で自由に操作できるようになります。

### AI アシスタントへの伝え方
以下のように伝えるだけで、AI が自動で登録・紐付けを行い、以降は名前だけで操作可能になります。

> **伝え方の例:**
> - 「スクリプトID `xxxxxxxx` を **〇〇クイック** として登録して」
> - 「このID `xxxxxxxx` をプロジェクト一覧に **案件管理シート** という名前で追加して」

### コマンドまたは手動で登録する場合
CLI コマンドから直接登録できます：
```bash
py gas.py alias set "案件管理シート" "1AbCdEfGhIjKlMnOpQrStUvWxYz_0123456789-AbCdEfGhIjKlMnOpQrSt"
py gas.py alias list
```
または、リポジトリ直下の `aliases.json` に直接記述することも可能です（Git にはコミットされないよう除外設定されています）。

```json
{
  "案件管理シート": "1AbCdEfGhIjKlMnOpQrStUvWxYz_0123456789-AbCdEfGhIjKlMnOpQrSt"
}
```

登録後は、CLI や MCP ツールから `py gas.py files "案件管理シート"` や `list_files(project="案件管理シート")` のように名前だけで即座にアクセスできます。

```bash
# 0. 初期設定＆動作環境診断（未導入時も安全に実行可能）
py gas.py setup --open

# 1. プロジェクト一覧・ファイル一覧・関数構造マップ
py gas.py list
py gas.py files "MyProject"
py gas.py outline "MyProject"

# 2. プロジェクト深層健康診断（構文・グローバル衝突・RPC・ループ内重いAPI・デッドコード）
py gas.py diagnose "MyProject"

# 2b. GASドック（100点満点の健康点採点・直す手処方箋の自動案内）
py gas.py dock "MyProject"

# 2c. 高速化レシピ棚（頻出パターンの検出・コード変換案・自動適用）
py gas.py recipe "MyProject"
py gas.py recipe "MyProject" --func addData --apply

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

# 11. HTML フロントエンド実機シミュレーション（インメモリ IndexedDB / DOM / RPC 環境で検証）
py gas.py verify-ui "MyProject" Index --test-js "await saveToDB([{id:'1'}]); return (await loadFromDB()).length;"
```

---

## 🛠️ MCP ツール一覧

FastMCP による MCP サーバー（`gas_mcp_server.py`）を提供しています。

| ツール名 | 説明 |
| :--- | :--- |
| `gas(command)` | **【統合窓口】** CLI と同じコマンド形式（`files`, `outline`, `diagnose`, `get`, `grep`, `deps`, `versions`, `diff`, `diff-prod`, `run`, `patch-func` 等）を実行 |
| `setup_check` | 動作環境（Node.js・認証情報・Google API 疎通状態）の点検と導入案内 |
| `diagnose` | 深層健康診断（一括高速構文検査・関数/変数グローバル衝突・RPC/プライベート関数/引数検査・テンプレート欠落・ループ内API警告・未使用関数） |
| `list_projects` | Google Drive 上の GAS プロジェクト一覧取得 |
| `list_files` | プロジェクト内ファイル一覧（名前・種別・サイズ）取得 |
| `list_functions` | プロジェクト内（または指定ファイル内）の関数構造マップ・行範囲抽出 |
| `get_file` | ファイル全文または指定行範囲（`start_line`, `end_line`）のコード取得 |
| `get_function` | 特定関数の定義ブロック抽出（テンプレート文字列・HTML `<script>` 対応） |
| `patch_function` | **特定関数のスコープ内限定**での安全なピンポイント差分置換（Excel の `patch_procedure` 相当） |
| `replace_function` | 関数定義ブロック丸ごと置換（Excel の `replace_procedure` 相当・自動デプロイ対応） |
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
| `verify_frontend` | **HTML 内 JavaScript 実機シミュレーション**（インメモリ IndexedDB / DOM / google.script.run スパイ環境で保存・削除・再読込ライフサイクルを検証） |

---

## 🧪 テスト・公開前機械検査の実行

実機通信をモック化した純 Python オフライン単体テスト（`test_gas_offline.py`）および公開前検査スクリプト（`publish_check.py`）を同梱しています。約 1.5 秒で全機能と安全性を検証できます。

```bash
py publish_check.py
```

---

## 🔄 からくりポケット（AI自律開発ループ）

設計役AI（大型モデル）が `queue/` に作成した番号付き指示書を、作業役AI（高速モデル）が「合格の条件（関所テスト）」をクリアしながら自律的に完走させる開発ループシステムを同梱しています。
ダウンロード後すぐに、自律協調開発の基盤として利用可能です。

- 詳しい決まりやテンプレート: [`queue/README.md`](./queue/README.md)

---

## ライセンス

[MIT License](./LICENSE)
