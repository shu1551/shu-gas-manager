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
- **対応フロー**: `aliases.json` に `{"プロジェクト名": "スクリプトID"}` を登録。次回以降は `list_files(project="プロジェクト名")` 等で通常プロジェクト同様に直接操作可能になります。

## 3. GAS設計のベストプラクティス

1. **スプレッドシート操作の配列一括処理**:
   - ループ内での `.getValue()` / `.setValue()` 連打は避け、`getValues()` で配列取得・メモリ上で処理した後に `setValues()` で一括代入を行います。
2. **外部通信の並列化**:
   - 複数リクエストを行う場合は、ループ内の直列 `UrlFetchApp.fetch()` ではなく `UrlFetchApp.fetchAll()` の活用を検討します。
3. **プロパティ・キャッシュの最適化**:
   - プロパティへの頻繁なアクセスはループ外で `getProperties()` を取得するなど、通信回数を抑えます。

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
| **バージョン復元** | `diff_version` / `restore_version(project, version_number)` | 差分確認・スナップショット復元 |
| **環境診断** | `setup_check(open_browser=False)` | 認証・API接続状態の確認 |
