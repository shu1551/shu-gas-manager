---
name: gas-manager
description: Google Apps Script (GAS) のプロジェクトを clasp やブラウザを使わず、MCP サーバー gas-manager（または CLI gas.py）で直接・爆速・安全に読み書き・関数スコープ置換・複数ファイル一括更新・深層健康診断・リモート関数実行・実機ベンチマーク関所・本番バージョン比較・デプロイするときのスキル。「GASを直して」「Webアプリを更新して」「スクリプトを診断して」「GASの関数をテスト実行して」「高速なGASを作って」など Google Apps Script の話が出たら使う。
---

# ガスマネージャー (`gas-manager`) 操作スキル

Google Apps Script (GAS) はローカルにファイルを落とさず（`clasp pull/push` を使わず）、`gas-manager` の MCP ツールで Google Apps Script API をメモリ直撃して操作する。

## 1. 最速・最短手数の基本原則（初動遅延の完全撲滅・最短2ターン完結）

**【超重要】通常のコード改修・UI調整は「最短2ターン」で完結させます。**
- **ターン 1**: `outline` / `get_function` / `get_file` で修正対象をピンポイント取得（余計なファイル閲覧や長考は禁止）。
- **ターン 2**: `patch_function` または `patch_code`（＋`deploy=True`）で一撃反映。
- **報告**: 完了報告は成否と変更箇所を3〜5行以内で即座に返却。
- **不要な重量級ツールの連打厳禁**: 指示されていない `inspect_ui`、`verify_frontend`、`diagnose`、`ledger` などの重いツールを勝手に回すことは全面禁止。

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
5. **深層健康診断（`diagnose`）とフロント実機シミュレーション（`verify_frontend`）は必要時・指示時のみ**:
   - 通常のピンポイント修正・UI/CSS調整では、`patch_code` / `patch_function` に内蔵された「自動構文検査」だけで十分安全に完了します（毎回の診断実行は遅延の原因となるため不要）。
   - 大規模な改修後や全体的な不具合調査、または「健康診断して」「フロントをテストして」と明示指示された時のみ、`diagnose(project)` や `verify_frontend(project)` を実行してください。
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
  - 死にコード一括削除 (レントゲン解析で検出された孤立関数を自動安全削除): `clean_dead(project="...", dry_run=False)` / CLI: `py gas.py clean-dead <project> [--dry-run]`
  - Webクローン化 (外部Webページを解析し自立型GAS Webアプリとしてクローン・デプロイ): `clone_web(url="...", project="...")` / CLI: `py gas.py clone-web <url> [project]`
  - レントゲン解析 (E2Eコールパス・幽霊関数・死にコード検知): `xray(project="...", filename="Index")` / CLI: `py gas.py xray <project>`

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


## 5. UI/CSS改修の爆速一撃モード（最速・最短手数の原則）

フロントエンド（HTML/CSS/JS）の改善・見た目のブラッシュアップを行う際は、多段の対話往復や重い検査の連打を排し、以下の**「爆速一撃モード」**で完走する：

1. **`dry_run` スキップと `deploy=True` の一撃同時直撃**:
   - `patch_code` には「自動バックアップ」と「構文自動検査」が備わっているため、UI/CSS修正では `dry_run` を挟まず初手から `patch_code(project, filename, patches=..., deploy=True)` を実行する。
   - `verify=True`（フロント実機シミュレーション）や `inspect_ui`（Chromiumレンダリング）は普段は不要（明示指示された時のみ使用）。パッチ適用・自動デプロイのみを1回のツール呼び出しで最速（1〜2秒）で完結させる。
2. **特定済みプロジェクトの点呼ゼロ秒化**:
   - 会話セッション内で一度特定したプロジェクトは、プロジェクトID一覧（`list_projects`）やファイル一覧（`list_files`）の再取得を一切スキップし、0秒で該当ファイル・対象セレクタへ直撃する。
3. **「作って即提示」スタイル（手戻りゼロの最速プロトタイピング）**:
   - 方針が見えた時点で直ちにコード反映＆デプロイまで済ませ、「最新バージョンを実機（ブラウザ）で見ていただきながら微調整する」型で進め、人間の待ち時間を最小化する。


## 6. 参考画像からのデザイン一撃着せ替えプロトコル（0秒インポート）

ユーザーから「こんなデザインにして」「この画像の雰囲気を取り入れて」とスクショ画像が提示された際は、以下の最速プロトコルで直ちに実機反映する：

1. **視覚パラメータの0秒逆算**:
   - 提示画像から以下のデザイン値を即座に抽出・数値化する：
     - 背景色（アプリ全体 `--bg-body` / コンテナ `--bg-container` / テーブル領域 `--table-area-bg`）
     - カード色・枠線（`--card-bg`, `--card-border`）
     - カード角丸・すき間（`--card-radius: Xpx`, `--card-gap: Ypx`）
     - ホバー色・枠線（`--card-hover-bg`, `--card-hover-border`）
     - 選択行アクティブ枠（`--card-selected-bg`, `--card-selected-border`）
     - テキスト階層（主文字色 `--text-main` / 補足文字色 `--text-muted`）
2. **CSS変数（`:root` / `body.dark-mode`）の一撃置換**:
   - 構造コードは一切触らず、先頭のCSS変数ブロックのみをピンポイントで置換する。
   - `patch_code(project, "Index", patches=..., deploy=True)`（または `dev=True`）を一発発火。
3. **即座の実機提示**:
   - パッチ完了後、3行以内で「反映したデザインパラメータ」を伝え、ブラウザのリロードを促して実物で確認いただく。


## 7. Webアプリ特化「プロのデザイン鑑識眼（見る目）」の6大解剖掟

参考画像やUIデザインの要望を受けた際、表面的な色合わせだけの「素人AI実装」を厳禁とし、プロのWebデザイナーの視点から以下の**6大視覚レイヤー**へ強制分解して読み解き、洗練されたSaaSクオリティ（Linear/Notion/Stripe級）へと昇華させる：

1. **タイポグラフィの階層秩序（Typography Hierarchy）**:
   - 主役（件名・タイトル）: `font-weight: 500〜600`、明瞭な主文字色（`#0f172a` / `#f8fafc`）。
   - 準主役（差出人・タグ）: `font-weight: 500`、中間のコントラスト。
   - 脇役（日付・付随メタ）: 控えめな文字色（`--text-muted`）、フォントサイズ 11.5〜12px、微小な字間（`letter-spacing: 0.02em`）。
   - ※単調な原色黒（#000000）を排し、品のあるスレート系タイポグラフィで視線を自然に誘導する。
2. **余白の呼吸とリズム（Spacing & 8px Grid）**:
   - 窮屈さを消すカード内パディング（左右 14〜16px、上下 10〜12px）。
   - アイテム同士の美しい隙間（`border-spacing: 0 8px` / `gap: 8px`）。
   - 8pxの倍数を基調とした秩序あるスペーシングにより、情報密度と見やすさを両立する。
3. **微細ボーダーと半透明サーフェス（Subtle Borders & Elevation）**:
   - パキッとした無骨な不透明線を排し、背景に溶け込む半透明ボーダー（ダークモード: `rgba(255, 255, 255, 0.08)`、ライトモード: `#e2e8f0`）を採用。
   - 外枠コンテナとカード背景の明度差をわずか 5〜8% に抑え、落ち着いた上質感を演出する。
4. **繊細な陰影と空気感（Soft Shadows）**:
   - ベタっとした濃い黒影を厳禁とし、空気感のある繊細な多層シャドウを敷く：
     `box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px -1px rgba(0, 0, 0, 0.02);`
5. **角丸の調和秩序（Border Radius Hierarchy）**:
   - 外枠コンテナ: `12px`
   - アイテム行・カード: `8px`
   - ボタン・入力ボックス: `6px`
   - バッジ・タグ: `4px` または `9999px`（完全カプセル型）
   - 要素の面積に合わせた自然な丸みのグラデーションを守る。
6. **マイクロインタラクション（Micro-interactions）**:
   - 静止画のような瞬間切り替えを排し、`transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);` でしっとり追従。
   - ホバー時にカードがほんのり 1px 浮遊する `transform: translateY(-1px);`。
   - 選択アクティブ時は、鮮やかなスカイブルー枠（`border: 2px solid #38bdf8`）と微弱なハイライトで直感的な操作感を実現する。

## 8. 実機画面監査とコントラスト自動監査（inspect-ui: 明示指示時のみ）

**【重要・速度最優先の掟】`inspect_ui`（Playwright実機レンダリング・全ボタン踏破・コントラスト監査）は重量級ツールです。通常のコード修正・UI改修時に勝手に実行することは厳禁とします。「画面を確認して」「コントラストをチェックして」「スクショを撮って」とユーザーから明示指示された時のみ実行してください。**

1. **指示があった場合の実行方法**:
   - `gas("inspect-ui <project> [file] [--theme <theme>] [--all-themes]")`
   - Playwright による Chromium ヘッドレス実機レンダリングにより、以下を自動検証する：
     - **WCAG 2.1 コントラスト監査**: 文字色・背景色のコントラスト比を計算し、視認性不具合を検出。
     - **全ボタン踏破・画面遷移**: 画面内のボタンクリックと表示変化を追跡。
     - **スクリーンショット撮影**: 実画面の画像を保存し、ユーザーへ提示。


## 9. REA思想の高度解析武器群 (trace-rpc, diff-behavior, ledger 等: 明示指示時のみ)

※以下の高度解析ツール群は、通常のコード改修時には呼び出さず、ユーザーから調査・解析・大掃除・移行を明示指示された時のみ使用します（AIによる勝手な自動実行を厳禁）。

1. **`trace_rpc`（実行時RPC通信スパイ ＆ 完全オフラインモック生成）**:
   - `gas("trace-rpc <project_or_url> [file] [--duration <sec>]")`
   - 実機ブラウザでアプリを操作中、`google.script.run` でやり取りされた通信を記録し、ローカルモックを作成。

2. **`diff_behavior`（破壊的変更・スキーマ不整合検知）**:
   - `gas("diff-behavior <project> [--target <target_id>] [--version <ver>]")`
   - コード変更による「振る舞いの変化・破壊的変更」を静的AST解析で監査。大規模リファクタリング時に使用。

3. **`ledger`（モダンGAS再構築・健全性義務台帳）**:
   - `gas("ledger <project> [file]")`
   - Webアプリとして備えるべき必須要件の充足状況をチェックリスト化し、スコアを算出。

4. **`clean_dead`（死にコード一括削除）**:
   - `gas("clean-dead <project>")`
   - 画面から使われていない孤立サーバー関数を一括安全削除。

5. **`clone_web`（Webサイトクローン化）**:
   - `gas("clone-web <url>")`
   - 外部Webページを解析し自立型GAS Webアプリとしてクローン・デプロイ。

6. **`xray`（深層レントゲン解析）**:
   - `gas("xray <project>")`
   - E2Eコールパス、未定義RPC、死にコードを可視化。
