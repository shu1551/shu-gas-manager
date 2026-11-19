---
name: gas-manager
description: Google Apps Script (GAS) のプロジェクトを clasp やブラウザを使わず、MCP サーバー gas-manager で直接・高速・安全に読み書き・ピンポイント修正・深層診断・実機ベンチマーク・本番デプロイするスキル。
---

# ガスマネージャー (`gas-manager`) 操作スキル

Google Apps Script (GAS) のプロジェクト操作は、`gas-manager` の MCP ツール（`call_mcp_tool`）を活用して安全かつ効率的に行います。

## 1. 基本方針

- **MCP ツールの優先活用**: GAS の読み書き・関数確認・デプロイは、提供されている `gas-manager` の MCP ツールを活用します。
- **ピンポイント修正と安全確認**: コード修正時は対象の関数や差分を確認した上で、正確に変更を反映します。
- **デプロイ管理**: 既存の特定デプロイURLを更新する場合は、`deploy(project=..., deployment_id="AKfy...")` または `push_project(..., deploy=True, deployment_id="AKfy...")` を使用します。

## 2. 推奨される操作フロー

### パターンA: ローカル編集と同期
1. ローカルファイルを編集後、`push_project(project=..., local_dir="...", deploy=True)` を実行してクラウド反映・デプロイを行います。
2. 必要に応じて `pull_project(project=..., local_dir="...")` で最新のクラウド状態とローカルを同期します。

### パターンB: クラウド上のピンポイント修正
1. `list_functions` や `get_function` で対象関数のコードと行範囲を確認します。
2. 単一関数の修正は `patch_function`、複数箇所の修正は `batch_patch` を使用して安全に反映します。
3. 変更完了後、必要に応じて `deploy` で本番反映します。

### パターンC: スプレッドシート付属（コンテナバインド）スクリプトの利用
スプレッドシートやドキュメントに付属するスクリプトは Google Drive の通常一覧検索から除外される仕様です。
初回のみスクリプトIDとプロジェクト名を紐付けることで、以降は名前だけで操作可能になります。
- **ユーザーからの指示例**: 「スクリプトID `xxxx` を『〇〇』として登録して」「このID `xxxx` をプロジェクト『〇〇』に追加して」
- **対応フロー**: MCP ツール `set_alias(name="プロジェクト名", script_id="xxxx")` を実行。以降は `list_files(project="プロジェクト名")` 等で通常プロジェクト同様に直接操作可能になります。登録済み一覧は `list_aliases()` で確認できます。

### パターンD: GASコンボ（シートを言葉で直すアドオン）を入れる
「GASコンボを入れて」「アドオンを使いたい」と頼まれたら、AI が次の順に進めます。人が押すのは Google の画面の 3 か所だけです。
1. `gas('setup --open')` で点検します。
   - `needs_login`: AI がターミナルで `npm install -g @google/clasp` と `clasp login` を撃ち（Node.js が無いと手順に ⓪ が出るので、`winget install OpenJS.NodeJS.LTS` 等を先に撃つ）、ブラウザに出る許可だけ人に押してもらいます。
   - `needs_api_enable`: 開いた設定画面で「Google Apps Script API」をオンにしてもらいます。
2. `ready` になったら `gas('combo addon')` を 1 回撃ちます（本体のライブラリとアドオンを、その人の Drive に作ります）。
3. 返事の `install_guide` を上から 1 段ずつ案内します（1 段言ったら押せたかを聞いて次へ。詰まったらその段の `if_stuck` を言う。全部を一度に並べない）。中身は、`editor` を開く →「デプロイ」→「デプロイをテスト」→「Google Workspace アドオン」の段の「インストール」→「完了」→ シートの右端の ⚡ → 初回の許可（「確認されていません」は「詳細」→「〜に移動」）です。
4. 返事の `chrome_extension.how` をそのまま案内します（任意・おすすめ）。chrome://extensions で「デベロッパー モード」をオン →「パッケージ化されていない拡張機能を読み込む」→ 返事の `chrome_extension.folder`（`ws_browser_ext`）を選んでもらいます。入れてあるなら何もしなくてかまいません（ファイルが変わると、サイドパネルを開いたときに拡張が自分で入れ直します）。あとは拡張のアイコンか Alt+G で、Chrome の右のサイドパネルに GASコンボが開きます。

## 3. GAS設計のベストプラクティス

1. **スプレッドシート**: ループ内の `getValue/setValue` 連打を避け、`getValues()` → メモリ処理 → `setValues()` で一括代入。
2. **外部通信**: 直列の `UrlFetchApp.fetch()` ではなく `fetchAll()` を検討。
3. **プロパティ・キャッシュ**: ループ外で `getProperties()` を取るなど通信回数を抑える。

## 4. 主要ツール一覧

| 目的 | MCP ツール | 備考 |
| :--- | :--- | :--- |
| **プロジェクト一覧** | `list_projects` | Google Drive 上の GAS プロジェクト取得 |
| **ファイル一覧** | `list_files(project)` | プロジェクト内のファイル一覧・種別・サイズ |
| **ファイル内容取得** | `get_file(project, filename, start_line, end_line)` | 指定ファイルのコード取得 |
| **構造把握** | `list_functions(project, filename)` | 関数名・行番号・文字数の outline 取得 |
| **関数コード取得** | `get_function(project, filename, func_name)` | 対象関数ブロックのみ抽出 |
| **単一関数修正** | `patch_function(project, filename, func_name, target, replacement)` | 構文検査付きのピンポイント置換 |
| **複数ファイル修正** | `batch_patch(project, operations=[...], deploy=True)` | 複数ファイル・関数の一括更新 |
| **ローカル同期 (送信)** | `push_project(project, local_dir, deploy=True, deployment_id=...)` | クラウド同期＋デプロイ |
| **ローカル同期 (取得)** | `pull_project(project, local_dir)` | クラウドから最新コードを一括取得 |
| **実機ベンチマーク** | `benchmark_function(project, func_name, args, target_ms=500)` | 関数の実機実行速度を計測 |
| **本番デプロイ** | `deploy(project, description, deployment_id=...)` | 本番Webアプリへ即座に更新反映 |
| **別名登録 (エイリアス)** | `set_alias(name, script_id)` / `list_aliases()` | スプレッドシート付属スクリプトの登録・確認 |
| **バージョン復元** | `diff_version` / `restore_version(project, version_number)` | 差分確認・スナップショット復元 |
| **環境診断** | `setup_check(open_browser=False)` | 認証・API接続状態の確認 |
| **統合コマンド窓口** | `gas(command)` | CLI互換コマンド（files, outline, diagnose, func等）の一括実行 |

### Workspace 操作 4 道具（2号機）

スプレッドシートやドキュメントを会話形式で安全に作成・編集・整形するツール群です。実行前に自動で控え（バックアップ）を取り、失敗時は自動でロールバックします。

| 道具 | 役割 | 正確な引数定義（`.json` の事前 `read_file` 不要・即呼び出し可） |
| :--- | :--- | :--- |
| `ws_look` | **状態確認＋棚引き** | `target: str = ""`, `sheet: str = ""`, `range: str = ""`, `image: bool = False`, `ask: str = ""` |
| `ws_find` | **棚札の検索 (通信なし)** | `ask: str = ""`, `kind: str = ""` (`"sheet"` \| `"doc"`) |
| `ws_do` | **作成・修正の実行** | `ask: str = ""`, `ops: str = ""` (JSON配列文字列), `target: str = ""`, `ok: bool = False` |
| `ws_undo` | **直前・過去へ巻き戻し** | `to: str = ""`, `list: bool = False`, `ok: bool = False` |

#### Workspace 最速 1 発直撃ルール（長考・無駄な往復の禁止）
1. **スキーマ `.json` の読み込み省略**: 上表の通り引数は確定しているため、`ws_look.json` や `ws_do.json` を `read_file` せず初手から直接 `call_mcp_tool` を呼び出します。
2. **`ws_look` は 1 回で済ませる**: スプレッドシートの中身確認は `ws_look(target=..., range="A1:Z30")` の **1 回のみ** で完了させます。頼まれていない別シートまで連続で `ws_look` して「今の相手シート」を勝手に切り替えないでください。
3. **`ws_do` は考え込まず 1 発で棚にかける**:
   - `ws_do(ask="ユーザーの頼みの文そのまま")` で撃つ際、AI が勝手に括弧 `（A1）` 等の余計な語を足して文を改変しないでください。
   - 書式変更（`format` 棚）など型が自明な操作は、`ops='[{"shelf":"format","title":true,"color":"青"}]'`（引数: `range`, `col`, `header`, `title`, `bold`, `italic`, `color`, `bg`, `size`, `font`, `number_format`, `align`, `valign`, `wrap`, `borders`, `merge`）または `ask` で即座に 1 発実行し、成功後に確認の `ws_look` は撃たずに即答してください。

### GAS 棚ルーター群（高速化・診断・骨格）

GAS プロジェクト全体の品質向上、高速化、リファクタリング、UIデザインを一括・安全に行う専用ルーター群です。

| 道具 | 役割 | 特徴・使い分け |
| :--- | :--- | :--- |
| `gas_shelf` | **先撃ち総合棚ルーター** | 自然言語 `query` から全25棚（レシピ・骨格・診断）を自動判定・自動ディスパッチ。迷ったらまずこれ |
| `gas_dock` | **統合人間ドック診断** | diagnose + xray + RPC契約検査を統合し、100点満点スコアと処方箋（改善手順）を提示 |
| `gas_recipe` | **高速化レシピ棚** | 全12レシピ（R01: appendRow一括化、R02: 2次元配列化、UrlFetch並列化等）の検出・プレビュー・自動適用 |
| `design_skin` | **デザイン着せ替え** | WebアプリHTMLに高品質CSS/UIプリセット（linear, glass, notion, emerald）を即座に反映 |
| `gas_scaffold` | **上級アーキテクチャ骨格** | S01〜S05（Promise化RPC、SWR即時描画、楽観UI等）の堅牢な設計パターンを安全注入 |

## 5. 道具の使い分け指針

- **スプレッドシート・文書の中身や書式を直接操作したい場合**:
  → **Workspace 操作 4 道具 (`ws_look` / `ws_find` / `ws_do` / `ws_undo`)** を使用。
- **GAS コード全体の高速化・健康診断・デザイン刷新・骨格導入を行いたい場合**:
  → **GAS 棚ルーター群 (`gas_shelf` / `gas_dock` / `gas_recipe` / `design_skin` / `gas_scaffold`)** を使用。
- **特定ファイルのコード確認・ピンポイント修正・バージョン管理・デプロイを行いたい場合**:
  → **GAS 1号機ツール (`get_function`, `patch_function`, `deploy`, `gas`)** を使用。
