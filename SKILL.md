---
name: gas-manager
description: Google Apps Script (GAS) のプロジェクトを clasp やブラウザを使わず、MCP サーバー gas-manager（または CLI gas.py）で直接・爆速・安全に読み書き・関数スコープ置換・複数ファイル一括更新・深層健康診断・リモート関数実行・本番バージョン比較・デプロイするときのスキル。「GASを直して」「Webアプリを更新して」「スクリプトを診断して」「GASの関数をテスト実行して」など Google Apps Script の話が出たら使う。
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
5. **改修前後の深層健康診断（`diagnose`）**:
   - 改修後は `diagnose(project)` を 1 回撃ち、以下の **9 項目** を一括裏取りする：
     1. 全ファイル構文検査（Node.js `vm.Script` 一括バッチ検査）
     2. マニフェスト（`appsscript.json`）構文・設定検査
     3. トップレベル関数名のファイル間重複衝突
     4. トップレベル `const` / `let` / `class` のファイル間重複衝突
     5. HTML `google.script.run` の未定義サーバー関数呼び出し（リンク切れ）
     6. HTML `google.script.run` のプライベート関数（末尾 `_`）呼び出しエラー
     7. HTML `google.script.run` の引数個数ミスマッチ警告
     8. `HtmlService` テンプレートファイル欠落（リンク切れ）
     9. ループ（`for`/`while`/`forEach`/`map`）内の重い GAS API 呼び出し（6分制限・クォータ枯渇地雷）と未使用関数（デッドコード）


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
  - 関数単体テスト: `run_function(project="...", func_name="...", args=[...])`
  - 健康診断: `diagnose(project="...")`
  - 本番反映: `deploy(project="...", description="...")`

### 万一のロールバック（ローカル退避 ＆ Googleクラウド版履歴の二重保険）
- 直前のローカル退避との差分・復元: `diff_backup(project="...")` / `restore_backup(project="...", backup_file="...")`
- Googleクラウド上の過去バージョン一覧・差分・復元: `list_versions(project="...")` / `diff_version(project="...", version_number=...)` / `restore_version(project="...", version_number=...)`
