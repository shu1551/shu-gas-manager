---
name: gas-manager
description: Google Apps Script (GAS) のプロジェクトを clasp やブラウザを使わず、MCP サーバー gas-manager（または CLI gas.py）で直接・爆速・安全に読み書き・関数スコープ置換・複数ファイル一括更新・深層健康診断・リモート関数実行・実機ベンチマーク関所・本番バージョン比較・デプロイするときのスキル。「GASを直して」「Webアプリを更新して」「スクリプトを診断して」「GASの関数をテスト実行して」「高速なGASを作って」など Google Apps Script の話が出たら使う。
---

# ガスマネージャー (`gas-manager`) 操作スキル

Google Apps Script (GAS) はローカルにファイルを落とさず（`clasp pull/push` を使わず）、`gas-manager` の MCP ツールで Google Apps Script API をメモリ直撃して操作する。

## 1. 最速・最短手数の基本原則

1. **全文取得（`get_file` 全文）より先に構造把握（`outline` / `grep`）**:
   - いきなり長いファイル全文を読まず、まず `gas("outline <project>")`（または `list_functions`）や `gas("grep <project> <keyword>")`（または `search_code`）で対象ファイルと関数名・行番号を特定する。
2. **関数スコープ限定パッチ（`patch_function`）と複数ファイル一括更新（`batch_patch`）の徹底**:
   - 1つの関数内の一部を直すときは、ファイル全体の `patch_code` よりも、対象関数内だけにスコープを絞る **`patch_function(project, filename, func_name, target, replacement)`** を優先する（他関数にある同名変数や `return res;` との衝突を100%回避できる）。
   - 関数全体を書き換えるときは `replace_function`、新規関数追加は `add_function`、不要関数削除は `delete_function` を使う。
   - サーバー（`.gs`）とフロント（`.html`）など**複数ファイルを同時に直すときは `batch_patch(project, operations)`** を使い、1回のAPI通信・1回のバックアップ・一括構文検査でアトミックに反映する（逐次呼び出しによる通信ロスと半端な更新を防止）。
3. **デプロイ前の本番差分確認（`diff_version` / `diff-prod`）と `--dev` 検証**:
   - 本番デプロイ（`deploy=True`）の前に、現在稼働中の本番バージョンと HEAD の差分を確認したい場合は `diff_version(project)`（CLI: `py gas.py diff-prod <project>`）を実行する。
   - 再デプロイせずに最新 HEAD コードの `doGet` / `doPost` を試すときは `call_webapp(url="<project>", dev=True)` を使う。
4. **任意のサーバー関数の単体リモート実行・ログ回収（`run_function` / `run`）**:
   - 新しく書いた関数やロジックを実機テストしたいときは、`run_function(project, func_name, args)`（CLI: `py gas.py run <project> <func_name> '[引数]'`）を使う。GCP設定不要で V8 ランタイム上の戻り値・`console.log` / `Logger.log`・例外スタックトレースを直接回収できる。
5. **改修前後の深層健康診断（`diagnose`）とフロント実機シミュレーション（`verify_frontend`）**:
   - 改修後は `diagnose(project)` を 1 回撃ち、以下の項目を一括裏取りする：
     1. 全ファイル構文検査（Node.js `vm.Script` 一括バッチ検査）
     2. マニフェスト（`appsscript.json`）構文・設定検査
     3. トップレベル関数名・グローバル変数（`const`/`let`/`class`）の重複衝突
     4. HTML `google.script.run` の未定義サーバー関数呼び出し・末尾 `_` エラー・動的ブラケット呼出・引数個数ミスマッチ警告
     5. `HtmlService` テンプレートファイル欠落（リンク切れ）
     6. ループ内の重い GAS API 呼び出し（`getAttachments`・`getPlainBody`・`base64Encode`・1セル操作等）
     7. サーバー関数の未使用引数（UI入力値の無視バグ）
     8. フロントエンド・キャッシュ・DOM警告（IndexedDB put のみのゾンビキャッシュ、iframe `document.write` 同期描画ブロック、未定義インラインイベント）
   - **HTML / クライアント JS を改修した際の必須関所**:
     - 単なる静的構文チェックだけでなく、`verify_frontend(project, filename="Index", test_js="...")`（CLI: `py gas.py verify-ui <project> [file] --test-js "..."`）を実行し、インメモリ IndexedDB / DOM / RPC 環境上でデータの保存・削除・再読込ライフサイクルが破綻せず正しく永続化・パージされることを必ず実機検証する。
6. **ローカルフォルダ双方向同期（`pull` / `push` / `sync_status`）**:
   - Git管理やVSCode編集を行いたい場合は、双方向同期コマンドを使う。
   - `pull(project, local_dir)`（CLI: `py gas.py pull <project> [dir]`）: クラウドの全コードを `.gs` / `.html` / `appsscript.json` としてローカルへ書き出す。
   - `sync_status(project, local_dir)`（CLI: `py gas.py status`）: ローカルとクラウドの差分（変更・追加・クラウドのみ・未変更・diff）を確認。
   - `push(project, local_dir, deploy=...)`（CLI: `py gas.py push`）: ローカルの変更を一括Node構文検査＆自動バックアップを経てクラウドへアトミック反映。差分が0件の場合はAPI通信をスキップしミリ秒で即返却。

## 2. 代表的なワークフロー

### 既存 GAS プロジェクトの調査・改修・実機テスト（最短 2〜3 ターン）
- **ターン 1（特定・取得）**:
  - `gas("outline <project>")` または `get_function(project="...", filename="...", func_name="...")`
- **ターン 2（反映）**:
  - 単一関数修正: `patch_function(project="...", filename="...", func_name="...", target="...", replacement="...")`
  - 複数ファイル一括修正: `batch_patch(project="...", operations=[...])`
- **ターン 3（実機テスト・健康診断・本番デプロイ）**:
  - 関数単体テスト・ベンチマーク関所: `benchmark_function(project="...", func_name="...", args="[...]")`
  - 健康診断: `diagnose(project="...")`
  - 本番反映: `deploy(project="...", description="...")`

### 万一のロールバック（ローカル退避 ＆ Googleクラウド版履歴の二重保険）
- 直前のローカル退避との差分・復元: `diff_backup(project="...")` / `restore_backup(project="...", backup_file="...")`
- Googleクラウド上の過去バージョン一覧・差分・復元: `list_versions(project="...")` / `diff_version(project="...", version_number=...)` / `restore_version(project="...", version_number=...)`

## 3. 「怪物GAS」の極限設計4大鉄則（最初からこの水準で組むこと）

素朴なループ処理や1セル操作を厳禁とし、初手から以下の極限アーキテクチャで実装する：

1. **シート操作のメモリ2次元配列一括化**:
   - ループ内での `.getValue()` / `.setValue()` / `.appendRow()` / `.getBackground()` 連打は絶対厳禁。
   - 必ず `getDataRange().getValues()` で2次元配列としてメモリへ一括取得し、メモリ上で高速計算・フィルタリングを行った上で、`sheet.getRange(startRow, startCol, arr.length, arr[0].length).setValues(arr)` で一撃代入する。
2. **外部HTTP通信の `UrlFetchApp.fetchAll` 並列一括化**:
   - ループ内での直列 `UrlFetchApp.fetch(url)` 連打は厳禁。
   - リクエスト配列 `const reqs = urls.map(u => ({ url: u, muteHttpExceptions: true }));` を組み立て、`UrlFetchApp.fetchAll(reqs)` で並列一括送信する（数10件の通信を1秒台に短縮）。
3. **プロパティ・キャッシュの一括取得**:
   - ループ内での `PropertiesService.getScriptProperties().getProperty(k)` や `CacheService.getScriptCache().get(k)` は厳禁。
   - ループの外で `getProperties()` / `getAll(keys)` により辞書として1回で一括取得し、ループ内はメモリ参照のみとする。
4. **6分実行制限を突破する「継続トークン＆自己増殖トリガー」**:
   - 万単位の重いバッチ処理では `const t0 = Date.now();` で経過時間を監視し、280,000ms（4分40秒）を超えたら現在のインデックスを `PropertiesService` に保存し、`ScriptApp.newTrigger(fnName).timeBased().after(60 * 1000).create()` で次走トリガーを予約して安全終了する。

## 4. 実機ベンチマーク関所（`bench`）による自律カイゼンループ

「動くはず」の推測納品を厳禁とし、実機計測と診断が一体化した **`benchmark_function`（CLI/統合窓口: `gas("bench <project> <func_name> [args] --target-ms <目標ms> --expected <期待値>")`）** を関所として自律ループを回す：

1. **実装・改修**: `patch_function` / `add_function` で対象関数を実装する。
2. **実機ベンチマーク関所**: `benchmark_function(project="...", func_name="...", args="[...]", target_ms=500, expected="...")` を実行する。
3. **自律カイゼン反復（人間への途中確認不要）**:
   - 判定が `[FAILED]`（実行例外・期待値不一致）または `[NEEDS_IMPROVEMENT]`（目標速度超過・ループ内APIボトルネック警告あり）の場合は、出力された **「カイゼン処方箋 (Next Actions)」** に従って直ちに `patch_function` で修正し、再度 `benchmark_function` を叩く。
   - 判定が **`[PASS] (スコア: 100/100点)`** に到達するまで自律的にループを回し切り、合格した実測ミリ秒とスコアを添えて完了報告する。
