---
name: gas-manager
description: Google Apps Script (GAS) のプロジェクトを clasp やブラウザを使わず、MCP サーバー gas-manager で直接・高速・安全に読み書き・ピンポイント修正・深層診断・実機ベンチマーク・本番デプロイするスキル。
---

# ガスマネージャー (`gas-manager`) 操作スキル

Google Apps Script (GAS) および Google スプレッドシート／ドキュメントの操作は、`gas-manager` の MCP ツール（`call_mcp_tool`）を活用して安全かつ効率的に行います。

## 1. 基本方針（棚優先・独自スクリプト自作禁止インターロック）

- **既存棚の最優先活用（自作禁止）**:
  - **スプレッドシート・文書の操作**: 使い捨ての GAS コードや独自スクリプトを自作せず、必ず 2 号機ツール（`ws_do` / `ws_look` / `ws_find` / `ws_undo`・全 177 棚）を優先します。
  - **GAS コードの改善・修正**: 1 手目は必ず `gas_shelf(project=..., query=頼み文そのまま)` で既存 33 棚を優先し、棚に無い修正のみ `get_function` → `patch_function` へ進みます。
- **まとめ棚（マイマクロ）の活用**: 複数棚を束ねた定型処理は別概念を作らず、マイマクロ内で `shelf([{shelf:"..."}, ...])` または `shelf("棚名", {...})` を呼ぶ「まとめ棚」として組めます（MCP からは `gas('combo quick <id> list|run <名前>')` で操作可能）。
- **ピンポイント修正と安全確認**: コード修正時は対象の関数や差分を確認した上で、正確に変更を反映します。
- **デプロイ管理**: 既存の特定デプロイ URL を更新する場合は、`deploy(project=..., deployment_id="AKfy...")` または `gas('push ... --deploy')` を使用します。

## 2. 推奨される操作フロー

### パターンA: ローカル編集と同期
1. ローカルファイルを編集後、`gas('push <project> <local_dir> --deploy')` を実行してクラウド反映・デプロイを行います。
2. 必要に応じて `gas('pull <project> <local_dir>')` で最新のクラウド状態とローカルを同期します。

### パターンB: クラウド上のピンポイント修正
1. `gas_shelf(project=..., query=...)` を 1 手目に実行します（E01/E02 は `apply` 省略で即反映）。
2. 棚で対応できない場合のみ `gas('outline <project>')` や `get_function` で対象関数を確認し、`patch_function`（複数箇所は `gas('batch ...')`）で安全に反映します。
3. 変更完了後、必要に応じて `deploy` で本番反映します。

### パターンC: スプレッドシート付属（コンテナバインド）スクリプトの利用
スプレッドシートやドキュメントに付属するスクリプトは Google Drive の通常一覧検索から除外される仕様です。
初回のみスクリプトIDとプロジェクト名を紐付けることで、以降は名前だけで操作可能になります。
- **ユーザーからの指示例**: 「スクリプトID `xxxx` を『〇〇』として登録して」「このID `xxxx` をプロジェクト『〇〇』に追加して」
- **対応フロー**: `gas('alias <プロジェクト名> <script_id>')` を実行。以降は `gas('files <プロジェクト名>')` 等で通常プロジェクト同様に直接操作可能になります。登録済み一覧は `gas('aliases')` で確認できます。

### パターンD: GASコンボ（シートを言葉で直すアドオン）とマイマクロ
「GASコンボを入れて」「アドオンを使いたい」と頼まれたら、AI が次の順に進めます。人が押すのは Google の画面の 3 か所だけです。
1. `gas('setup --open')` で点検します。
   - `needs_login`: AI が `gas('login')` を撃ちます（clasp も Node.js も要りません）。ブラウザに出る Google の許可だけ人に押してもらいます。
   - `needs_api_enable`: 開いた設定画面で「Google Apps Script API」をオンにしてもらいます。
2. `ready` になったら `gas('combo addon')` を 1 回撃ちます（本体のライブラリとアドオンを、その人の Drive に作ります）。
3. 返事の `install_guide` を上から 1 段ずつ案内します（1 段言ったら押せたかを聞いて次へ。詰まったらその段の `if_stuck` を言う。全部を一度に並べない）。中身は、`editor` を開く →「デプロイ」→「デプロイをテスト」→「Google Workspace アドオン」の段の「インストール」→「完了」→ シートの右端の ⚡ → 初回の許可（「確認されていません」は「詳細」→「〜に移動」）です。
4. 拡張をまだ入れていない人には、返事の `chrome_extension.install_guide` を同じく 1 段ずつ手ほどきします（任意・おすすめ）。chrome://extensions →「デベロッパー モード」をオン →「パッケージ化されていない拡張機能を読み込む」→ `chrome_extension.folder`（`ws_browser_ext`）→ パズルのアイコンでピン留め → シートで拡張のアイコンか Alt+G で右のサイドパネルに GASコンボが開きます。入れ済みなら要りません（ファイルが変わると、サイドパネルを開いたときに拡張が自分で入れ直します）。なお `ws_browser_ext`（`sidepanel.js` + `direct_bridge.js`）が入っていれば、**サイドパネル・アドオン「操作窓」・シート内サイドバー**の 3 入口すべてで `127.0.0.1:18766/resolve` 経由のローカル直結 AI が動作します（`combo watch` は既定で直結専用・GAS 郵便受けポーリング停止。従来の郵便受け併用が必要なときのみ `--postbox` 指定）。
5. 「GASコンボのテンプレートを作って」と頼まれたとき（シートをコピーするだけで使いたい人・人に配りたいときも）は `gas('combo template')` を 1 回撃ち、返事の `install_guide` を同じく 1 段ずつ手ほどきします（`copy_url` を開く →「コピーを作成」→ メニューの「⚡ GASコンボ」→「操作窓（サイドバー）を開く」→ 初回の許可）。そのコピーの中だけで使えます。また拡張機能が使えない環境でも、シート内サイドバー／操作窓の設定タブから Gemini / Claude API キーを設定すれば同様に利用できます。
6. **マイマクロ（まとめ棚）**: マイマクロは `// 説明`・`// 棚: 言い方1, 言い方2` を頭につけて保存すると、`comboRunAsk` の自然文からも自動で呼び出せます。内部では `shelf([{shelf:"..."}, ...])` や `shelf("棚名", {...})` で既存の 177 棚を束ねられます。MCP からは `gas('combo quick <script_id> list')` で一覧確認、`gas('combo quick <script_id> run <macro_name>')` で実行できます。

## 3. GAS設計のベストプラクティス

1. **スプレッドシート**: ループ内の `getValue/setValue` 連打を避け、`getValues()` → メモリ処理 → `setValues()` で一括代入。
2. **外部通信**: 直列の `UrlFetchApp.fetch()` ではなく `fetchAll()` を検討。
3. **プロパティ・キャッシュ**: ループ外で `getProperties()` を取るなど通信回数を抑える。

## 4. 主要ツール一覧（標準露出 10 ツール＋統合窓口 `gas`）

標準起動時はトークン節約のため下記 **10 本** が MCP ツールとして直接露出しています（`GAS_MCP_ALL_TOOLS=1` で全機能個別露出）。

### 直接 MCP ツール（10 本）

| カテゴリ | MCP ツール | 役割・主な引数 |
| :--- | :--- | :--- |
| **GAS 1号機** | `gas_shelf` | **先撃ち総合棚ルーター**（全 33 棚: R01〜R13 / S01〜S08 / K01〜K04 / D01〜D06 / E01〜E02）。まず `project` と `query` を渡す |
| **GAS 1号機** | `gas` | **統合コマンド窓口** (`gas('help')` で一覧)。一覧・構造・診断・同期・ベンチ・コンボ・棚育成を一括実行 |
| **GAS 1号機** | `get_function` | `(project, filename, func_name)` で指定関数のコードを抽出 |
| **GAS 1号機** | `patch_function` | `(project, filename, func_name, target, replacement, deploy=False)` で構文検査付きピンポイント置換 |
| **GAS 1号機** | `deploy` | `(project, description, deployment_id=...)` で本番 Web アプリを更新デプロイ |
| **GAS 1号機** | `reload_tools` | 常駐 MCP サーバーのコードをメモリ上で再読込 |
| **Workspace 2号機** | `ws_look` | **状態確認＋棚引き** (`target="", sheet="", range="", image=False, ask=""`) |
| **Workspace 2号機** | `ws_find` | **棚札の検索 (通信なし)** (`ask="", kind="sheet"|"doc"`) |
| **Workspace 2号機** | `ws_do` | **作成・修正の実行** (`ask="", ops="", target="", ok=False`)。まず `ask` に頼み文そのままを渡す |
| **Workspace 2号機** | `ws_undo` | **直前・過去へ巻き戻し** (`to="", list=False, ok=False`) |

### `gas(command)` 経由の主な機能

| 目的 | コマンド例 | 備考 |
| :--- | :--- | :--- |
| **プロジェクト・ファイル一覧** | `gas('list')` / `gas('files <p>')` | Google Drive 上の GAS 一覧・ファイル一覧 |
| **構造・コード取得・検索** | `gas('outline <p>')` / `gas('get <p> <f>')` / `gas('grep <p> <pat>')` | 関数構造マップ・コード取得・横断検索 |
| **一括修正・同期** | `gas('batch <p> <ops_json>')` / `gas('push <p> <dir> --deploy')` / `gas('pull <p> <dir>')` | アトミック一括置換・ローカル同期 |
| **診断・レシピ・骨格・UI** | `gas('dock <p>')` / `gas('recipe <p>')` / `gas('scaffold <p>')` / `gas('skin <p>')` / `gas('xray <p>')` | 総合診断・高速化・骨格・デザイン・レントゲン |
| **実行・ベンチ・復元** | `gas('run <p> <fn>')` / `gas('bench <p> <fn>')` / `gas('diff-prod <p>')` / `gas('restore-version <p> <v>')` | リモート実行・速度計測・本番差分・バージョン復元 |
| **別名・環境点検** | `gas('alias <名> <id>')` / `gas('aliases')` / `gas('setup --open')` | コンテナバインド紐付け・認証点検 |
| **GASコンボ＆マイマクロ** | `gas('combo addon')` / `gas('combo template')` / `gas('combo quick <id> list|run <名>')` | 配備・マイマクロ一覧/実行・言い方登録 (`combo phrase`) |
| **Workspace 棚育成・検査** | `gas('ws-check')` / `gas('ws-misses [limit]')` | 全 177 棚の札/ガード検査・外れ/api逃げ集計 |

#### Workspace 最速 1 発直撃ルール（長考・無駄な往復の禁止）
1. **スキーマ `.json` の読み込み省略**: 上表の通り引数は確定しているため、`ws_look.json` や `ws_do.json` を `read_file` せず初手から直接 `call_mcp_tool` を呼び出します。
2. **`ws_look` は 1 回で済ませる**: スプレッドシートの中身確認は `ws_look(target=..., range="A1:Z30")` の **1 回のみ** で完了させます。頼まれていない別シートまで連続で `ws_look` して「今の相手シート」を勝手に切り替えないでください。
3. **`ws_do` は考え込まず 1 発で棚にかける**:
   - `ws_do(ask="ユーザーの頼みの文そのまま")` で撃つ際、AI が勝手に括弧 `（A1）` 等の余計な語を足して文を改変しないでください。
   - 書式変更（`format` 棚）など型が自明な操作は、`ops='[{"shelf":"format","title":true,"color":"青"}]'` または `ask` で即座に 1 発実行し、成功後に確認の `ws_look` は撃たずに即答してください。

## 5. 道具の使い分け指針

- **スプレッドシート・文書の中身や書式を直接操作したい場合**:
  → **Workspace 操作 4 道具 (`ws_look` / `ws_find` / `ws_do` / `ws_undo`)** を使用（使い捨てコードは書かない）。
- **GAS コード全体の高速化・健康診断・デザイン刷新・骨格導入・文字/定数置換を行いたい場合**:
  → **`gas_shelf`**（全 33 棚）を 1 手目として使用。
- **特定ファイルのコード確認・ピンポイント修正・バージョン管理・マイマクロ操作・棚検査を行いたい場合**:
  → **`get_function` / `patch_function` / `deploy` / `gas(...)`** を使用。
