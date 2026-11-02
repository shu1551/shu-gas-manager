#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gas.py - ガスマネージャー CLI
Google Apps Script (GAS) をコマンドラインから直接操作するツール
"""

import sys
import os
import argparse
import json
from pathlib import Path

# UTF-8 出力の安定化
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import unicodedata

# 自モジュールの読み込み
sys.path.insert(0, str(Path(__file__).parent))
from gas_client import GasClient

def _str_width(s):
    """East Asian Width を考慮した表示幅計算（全角2、半角1）"""
    w = 0
    for ch in str(s):
        status = unicodedata.east_asian_width(ch)
        w += 2 if status in ('F', 'W', 'A') else 1
    return w

def _pad_string(s, target_width):
    """表示幅を揃えるためのスペースパディング"""
    s_str = str(s)
    current_w = _str_width(s_str)
    pad = max(0, target_width - current_w)
    return s_str + (" " * pad)

def print_table(headers, rows):
    if not rows:
        print("(データなし)")
        return
    col_widths = [_str_width(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], _str_width(val))

    header_line = "  ".join([_pad_string(h, col_widths[i]) for i, h in enumerate(headers)])
    sep_line = "  ".join(["-" * w for w in col_widths])
    print(header_line)
    print(sep_line)
    for row in rows:
        row_line = "  ".join([_pad_string(v, col_widths[i]) for i, v in enumerate(row)])
        print(row_line)

def main():
    parser = argparse.ArgumentParser(description="ガスマネージャー (GAS Manager) CLI")
    subparsers = parser.add_subparsers(dest="command", help="実行コマンド")

    # 0. setup (初期設定＆診断)
    setup_p = subparsers.add_parser("setup", help="動作環境・認証トークン・API接続状態の点検とセットアップ案内")
    setup_p.add_argument("--open", action="store_true", help="設定ページ (Google Apps Script API) を自動でブラウザ起動")

    # 1. list (projects)
    list_p = subparsers.add_parser("list", help="GAS プロジェクト一覧表示")
    list_p.add_argument("-n", "--limit", type=int, default=20, help="取得件数 (デフォルト: 20)")

    # 2. files
    files_p = subparsers.add_parser("files", help="プロジェクト内のファイル一覧表示")
    files_p.add_argument("project", help="プロジェクト名またはスクリプトID")

    # 2c. outline (関数構造マップ)
    outline_p = subparsers.add_parser("outline", aliases=["funcs"], help="プロジェクト内の関数一覧・構造マップ")
    outline_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    outline_p.add_argument("-f", "--file", default="", help="対象ファイルを限定する場合に指定")

    # 2d. diagnose (健康診断)
    diag_p = subparsers.add_parser("diagnose", aliases=["diag"], help="GAS プロジェクト健康診断（構文・重複・リンク切れ・エントリーポイント）")
    diag_p.add_argument("project", help="プロジェクト名またはスクリプトID")

    # 2b. grep (プロジェクト横断検索)
    grep_p = subparsers.add_parser("grep", help="プロジェクト内のコード横断検索")
    grep_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    grep_p.add_argument("pattern", help="検索文字列または正規表現")
    grep_p.add_argument("-r", "--regex", action="store_true", help="正規表現検索を行う")
    grep_p.add_argument("-f", "--file", default="", help="対象ファイルを限定する場合に指定")
    grep_p.add_argument("-e", "--exclude", default="", help="除外するファイル名（カンマ区切り可）")
    grep_p.add_argument("-n", "--max-hits", type=int, default=100, help="最大ヒット件数 (デフォルト: 100)")

    # 3. get
    get_p = subparsers.add_parser("get", help="ファイル全文取得（行範囲指定対応）")
    get_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    get_p.add_argument("filename", help="ファイル名")
    get_p.add_argument("-s", "--start-line", type=int, default=None, help="取得開始行番号 (デフォルト: 先頭)")
    get_p.add_argument("-e", "--end-line", type=int, default=None, help="取得終了行番号 (デフォルト: 末尾)")

    # 4. func
    func_p = subparsers.add_parser("func", help="特定関数のコードブロック抽出")
    func_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    func_p.add_argument("filename", help="ファイル名")
    func_p.add_argument("func_name", help="関数名")

    # 5. patch
    patch_p = subparsers.add_parser("patch", help="ファイル内コード置換")
    patch_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    patch_p.add_argument("filename", help="ファイル名")
    patch_p.add_argument("target", help="置換対象文字列")
    patch_p.add_argument("replacement", help="置換後文字列")
    patch_p.add_argument("-a", "--all", action="store_true", help="複数箇所すべてを置換")
    patch_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    patch_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    patch_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 5a. patch-func (関数内限定置換)
    pf_p = subparsers.add_parser("patch-func", help="関数スコープ内限定のコード置換")
    pf_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    pf_p.add_argument("filename", help="ファイル名")
    pf_p.add_argument("func_name", help="対象関数名")
    pf_p.add_argument("target", help="置換対象文字列")
    pf_p.add_argument("replacement", help="置換後文字列")
    pf_p.add_argument("-a", "--all", action="store_true", help="複数箇所すべてを置換")
    pf_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    pf_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    pf_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 5b. replace-func (関数丸ごと置換)
    rf_p = subparsers.add_parser("replace-func", help="指定ファイル内の特定関数を丸ごと置換")
    rf_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    rf_p.add_argument("filename", help="ファイル名")
    rf_p.add_argument("func_name", help="置換対象関数名")
    rf_p.add_argument("code_or_file", help="新しい関数コード（直接文字列またはコードファイルパス）")
    rf_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    rf_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    rf_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 5c. add-func (関数追加)
    af_p = subparsers.add_parser("add-func", help="関数追加（既存重複チェック付き）")
    af_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    af_p.add_argument("filename", help="ファイル名")
    af_p.add_argument("code_or_file", help="追加する関数コード（直接文字列またはファイルパス）")
    af_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    af_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    af_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 5d. del-func (関数削除)
    df_p = subparsers.add_parser("del-func", help="関数削除")
    df_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    df_p.add_argument("filename", help="ファイル名")
    df_p.add_argument("func_name", help="削除対象関数名")
    df_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    df_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    df_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 5e. batch (一括アトミック更新)
    batch_p = subparsers.add_parser("batch", help="複数操作の一括アトミック合成反映（1回通信）")
    batch_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    batch_p.add_argument("ops_json_or_file", help="操作リストの JSON 文字列またはファイルパス")
    batch_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    batch_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    batch_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 6. replace
    rep_p = subparsers.add_parser("replace", help="ファイル丸ごと置換")
    rep_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    rep_p.add_argument("filename", help="ファイル名")
    rep_p.add_argument("file_path", help="新しい内容が書かれたローカルファイルパス")
    rep_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    rep_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    rep_p.add_argument("--deploy", action="store_true", help="修正完了後に本番Webアプリを自動デプロイ")

    # 7. add
    add_p = subparsers.add_parser("add", help="ファイル追加")
    add_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    add_p.add_argument("filename", help="追加するファイル名（拡張子なし）")
    add_p.add_argument("type", choices=["js", "html", "SERVER_JS", "HTML"], help="ファイル種別")
    add_p.add_argument("-s", "--source", default="", help="初期ソースコード")
    add_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")

    # 8. delete
    del_p = subparsers.add_parser("delete", help="ファイル削除")
    del_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    del_p.add_argument("file", help="削除ファイル名")

    # 8a. backups (バックアップ一覧)
    bak_p = subparsers.add_parser("backups", help="バックアップ一覧表示")
    bak_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    bak_p.add_argument("-n", "--limit", type=int, default=10, help="取得件数 (デフォルト: 10)")

    # 8b. restore (バックアップ復元)
    res_p = subparsers.add_parser("restore", help="バックアップから復元")
    res_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    res_p.add_argument("backup_file", help="バックアップファイル名")
    res_p.add_argument("-f", "--file", default="", help="特定ファイルのみ戻す場合に指定")

    # 8c. diff (バックアップとの差分比較)
    diff_p = subparsers.add_parser("diff", help="バックアップとの差分比較")
    diff_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    diff_p.add_argument("backup_file", nargs="?", default="", help="バックアップファイル名（省略時は最新）")
    diff_p.add_argument("-f", "--file", default="", help="特定ファイルのみ比較")

    # 9. deploy
    dep_p = subparsers.add_parser("deploy", help="新バージョン作成＆再デプロイ")
    dep_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    dep_p.add_argument("-d", "--desc", default="Auto deployed via CLI", help="バージョン説明")
    dep_p.add_argument("-r", "--refresh", action="store_true", help="デプロイIDキャッシュを再取得")

    # 9b. deployments (deps)
    deps_p = subparsers.add_parser("deployments", aliases=["deps"], help="デプロイ一覧表示")
    deps_p.add_argument("project", help="プロジェクト名またはスクリプトID")

    # 9c. versions
    ver_p = subparsers.add_parser("versions", help="クラウド不変バージョン一覧表示")
    ver_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    ver_p.add_argument("-n", "--limit", type=int, default=20, help="取得件数 (デフォルト: 20)")

    # 9d. diff-prod (diff-version)
    dp_p = subparsers.add_parser("diff-prod", aliases=["diff-version"], help="本番バージョンと最新HEADコードの差分比較")
    dp_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    dp_p.add_argument("-v", "--version", type=int, default=None, help="比較対象バージョン番号（省略時は最新デプロイ）")
    dp_p.add_argument("-f", "--file", default="", help="特定ファイルのみ比較")

    # 9e. restore-version
    rv_p = subparsers.add_parser("restore-version", help="クラウド上不変バージョンから復元")
    rv_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    rv_p.add_argument("version", type=int, help="復元したいバージョン番号")
    rv_p.add_argument("-f", "--file", default="", help="特定ファイルのみ復元")
    rv_p.add_argument("--deploy", action="store_true", help="復元直後に本番デプロイ")

    # 9f. run
    run_p = subparsers.add_parser("run", help="GAS関数リモート実行＆ログ・エラートレース回収")
    run_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    run_p.add_argument("func_name", help="実行対象のGAS関数名")
    run_p.add_argument("args_json", nargs="?", default="", help="関数引数（JSON配列または文字列）")
    run_p.add_argument("--keep-runner", action="store_true", help="実行ランナーを削除せず残す")
    run_p.add_argument("--fast", action="store_true", help="キャッシュ優先＆ランナー常駐による超高速実行（約0.3秒）")

    # 9f-2. bench (benchmark)
    bench_p = subparsers.add_parser("bench", aliases=["benchmark"], help="GAS関数の実機ベンチマーク計測＆健康診断（100点満点採点・カイゼン処方箋）")
    bench_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    bench_p.add_argument("func_name", help="ベンチマーク対象のGAS関数名")
    bench_p.add_argument("args_json", nargs="?", default="", help="関数引数（JSON配列または文字列）")
    bench_p.add_argument("-t", "--target-ms", type=int, default=1000, help="合格ラインの目標ミリ秒 (デフォルト: 1000)")
    bench_p.add_argument("-n", "--iterations", type=int, default=1, help="計測反復回数 (デフォルト: 1)")
    bench_p.add_argument("-e", "--expected", default="", help="期待する戻り値（指定時は一致検証を実施）")
    bench_p.add_argument("--no-fast", action="store_true", help="高速モードを無効化")

    # 9g. clean-runner
    cr_p = subparsers.add_parser("clean-runner", help="プロジェクト内の実行ランナー (__gm_exec_) および doGet フックを除去")
    cr_p.add_argument("project", help="プロジェクト名またはスクリプトID")

    # 9h. pull
    pull_p = subparsers.add_parser("pull", help="クラウドの GAS プロジェクトをローカルフォルダへ書き出し")
    pull_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    pull_p.add_argument("local_dir", nargs="?", default=".", help="保存先ローカルフォルダ（デフォルト: カレント）")
    pull_p.add_argument("--clean", action="store_true", help="クラウドに存在しないローカルファイルを削除")

    # 9i. push
    push_p = subparsers.add_parser("push", help="ローカルフォルダのコードをクラウドへ一括反映")
    push_p.add_argument("project", nargs="?", default="", help="プロジェクト名またはスクリプトID（省略時は .gas-sync.json を使用）")
    push_p.add_argument("local_dir", nargs="?", default=".", help="対象ローカルフォルダ（デフォルト: カレント）")
    push_p.add_argument("--dry-run", action="store_true", help="クラウド反映を行わず差分のみ確認")
    push_p.add_argument("--force", action="store_true", help="構文エラーを無視して強制反映")
    push_p.add_argument("--delete-missing", action="store_true", help="ローカルに無いクラウドファイルを削除")
    push_p.add_argument("--deploy", action="store_true", help="反映直後に本番デプロイ")
    push_p.add_argument("-m", "--desc", default="Pushed via GasClient", help="デプロイ説明文")

    # 9j. status
    st_p = subparsers.add_parser("status", aliases=["sync-status"], help="ローカルとクラウドの差分状態を確認")
    st_p.add_argument("project", nargs="?", default="", help="プロジェクト名またはスクリプトID（省略時は .gas-sync.json を使用）")
    st_p.add_argument("local_dir", nargs="?", default=".", help="対象ローカルフォルダ（デフォルト: カレント）")

    # 10. add-channel
    ch_p = subparsers.add_parser("add-channel", help="Qクイック等へチャンネル追加")
    ch_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    ch_p.add_argument("channel", help="チャンネルIDまたはURL")
    ch_p.add_argument("-n", "--name", default="", help="チャンネル名")

    # 11. webapp
    web_p = subparsers.add_parser("webapp", help="Webアプリ直接呼び出し")
    web_p.add_argument("url", help="WebアプリURL または プロジェクト名/スクリプトID")
    web_p.add_argument("-p", "--params", default="", help="クエリパラメータ")
    web_p.add_argument("-b", "--body", default="", help="POST本文")
    web_p.add_argument("-m", "--method", default="GET", choices=["GET", "POST"], help="HTTPメソッド")
    web_p.add_argument("-k", "--key", default="", help="秘密キー")
    web_p.add_argument("--auth", action="store_true", help="OAuth Bearer トークンを付与")
    web_p.add_argument("--dev", action="store_true", help="最新 HEAD デプロイを優先し Bearer 認証で直接呼び出し")

    # 12. verify-ui
    vui_p = subparsers.add_parser("verify-ui", help="HTML フロントエンド JavaScript 実機シミュレーション")
    vui_p.add_argument("project", help="プロジェクト名またはスクリプトID")
    vui_p.add_argument("file", nargs="?", default="Index", help="対象 HTML ファイル名 (既定: Index)")
    vui_p.add_argument("--test-js", default="", help="検証用に追加実行する非同期 JS 式/ブロック")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    # setup コマンドは ~/.clasprc.json が無い環境でも動作可能にするため GasClient() の前で実行
    if args.command == "setup":
        res = GasClient.check_setup(open_browser=args.open)
        status_icons = {
            "ready": "[READY]",
            "needs_login": "[SETUP REQUIRED]",
            "needs_api_enable": "[ACTION REQUIRED]",
            "error": "[ERROR]"
        }
        print(f"=== GAS Manager セットアップ診断 {status_icons.get(res['status'], '')} ===")
        print(f"{res['message']}\n")
        if res.get("steps"):
            print("【状態 / 手順】")
            for st in res["steps"]:
                print(f"  {st}")
        return

    client = GasClient()

    try:
        if args.command == "list":
            projects = client.list_projects(limit=args.limit)
            headers = ["プロジェクト名", "ID", "最終更新"]
            rows = []
            for p in projects:
                mtime = p.get("modifiedTime", "")[:19].replace("T", " ")
                rows.append([p.get("name", ""), p.get("id", ""), mtime])
            print(f"=== GAS プロジェクト一覧 ({len(rows)}件) ===")
            print_table(headers, rows)

        elif args.command == "files":
            sid = client.resolve_script_id(args.project)
            files = client.list_files(sid)
            headers = ["ファイル名", "種別", "サイズ"]
            rows = []
            for f in files:
                rows.append([f["name"], f["type"], f"{f['length']:,} 文字"])
            print(f"=== [{sid}] 内のファイル一覧 ({len(rows)}件) ===")
            print_table(headers, rows)

        elif args.command in ("outline", "funcs"):
            file_funcs = client.list_functions(args.project, filename=args.file)
            print(f"=== [{args.project}] の関数一覧 ({len(file_funcs)}ファイル) ===")
            for ff in file_funcs:
                fname = ff["file"]
                ftype = ff["type"]
                funcs = ff["functions"]
                print(f"\n[{fname}.{ftype}] ({len(funcs)}個の関数)")
                if not funcs:
                    print("  (関数は見つかりませんでした)")
                for fn in funcs:
                    print(f"  - {fn['name']} (行 {fn['start_line']}-{fn['end_line']}, {fn['length']:,} 文字)")

        elif args.command in ("diagnose", "diag"):
            diag = client.diagnose(args.project)
            status_str = "正常 (HEALTHY)" if diag["status"] == "healthy" else f"警告あり (WARNING: {diag['issues_count']}件の問題)"
            print(f"=== GAS プロジェクト健康診断: [{args.project}] ===")
            print(f"判定: {status_str}")
            print(f"ファイル数: {diag['file_count']} | 総関数数: {diag['total_functions']} | 検出された問題: {diag['issues_count']}件\n")

            print(f"[構文エラー] ({len(diag['syntax_errors'])}件):")
            if diag["syntax_errors"]:
                for se in diag["syntax_errors"]:
                    print(f"  - [{se['file']}.{se['type']}] {se['error']}")
            else:
                print("  なし (全ファイル構文チェック合格)")
            print()

            print(f"[重複関数・グローバル衝突] ({len(diag['duplicate_functions'])}件):")
            if diag["duplicate_functions"]:
                for df in diag["duplicate_functions"]:
                    loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in df["locations"]])
                    print(f"  - 関数 '{df['name']}' が {len(df['locations'])} 箇所で定義されています: ({loc_str})")
            else:
                print("  なし (グローバル名前空間での関数名衝突はありません)")
            print()

            dup_globals = diag.get("duplicate_globals", [])
            print(f"[グローバル変数・クラス衝突 (const/let/class)] ({len(dup_globals)}件):")
            if dup_globals:
                for dg in dup_globals:
                    loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in dg["locations"]])
                    print(f"  - 識別子 '{dg['name']}' が複数ファイルで重複定義されています: ({loc_str})")
            else:
                print("  なし (グローバル変数の衝突はありません)")
            print()

            print(f"[HTML RPC リンク切れ (google.script.run)] ({len(diag['broken_rpc_calls'])}件):")
            if diag["broken_rpc_calls"]:
                for rpc in diag["broken_rpc_calls"]:
                    print(f"  - {rpc['file']} 行 {rpc['line']}: サーバー関数 '{rpc['target_function']}' -> {rpc.get('reason', '関数が見つかりません')}")
            else:
                print("  なし (全ての google.script.run 呼び出し先関数が存在します)")
            print()

            rpc_arity = diag.get("rpc_arity_warnings", [])
            print(f"[RPC 引数不一致警告] ({len(rpc_arity)}件):")
            if rpc_arity:
                for ra in rpc_arity:
                    print(f"  - {ra['file']} 行 {ra['line']}: 関数 '{ra['target_function']}' (期待: {ra.get('expected', 'N/A')}, 呼出: {ra.get('actual', 'N/A')}) -> {ra.get('reason', '')}")
            else:
                print("  なし (RPC引数の不一致はありません)")
            print()

            print(f"[HTML テンプレートリンク切れ (HtmlService)] ({len(diag['broken_html_templates'])}件):")
            if diag["broken_html_templates"]:
                for tpl in diag["broken_html_templates"]:
                    print(f"  - {tpl['file']} 行 {tpl['line']}: {tpl['reason']}")
            else:
                print("  なし (全てのテンプレート参照先 HTML が存在します)")
            print()

            perf_warns = diag.get("performance_warnings", [])
            print(f"[パフォーマンス警告 (ループ内同期API)] ({len(perf_warns)}件):")
            if perf_warns:
                for pw in perf_warns:
                    print(f"  - {pw['file']} 行 {pw['line']}: {pw['api']} -> {pw.get('reason', '')}")
            else:
                print("  なし (ループ内での過剰な同期API呼出は検出されませんでした)")
            print()

            unused_fn = diag.get("unused_functions", [])
            print(f"[未参照・未使用の疑いがある関数] ({len(unused_fn)}件):")
            if unused_fn:
                for uf in unused_fn:
                    print(f"  - [{uf['file']}:{uf['line']}] {uf['name']}")
            else:
                print("  なし (全関数が参照されているかエントリーポイントです)")
            print()

            unused_params = diag.get("unused_params", [])
            print(f"[未使用の関数引数 (入力値無視の疑い)] ({len(unused_params)}件):")
            if unused_params:
                for up in unused_params:
                    print(f"  - {up['file']}:{up['line']} 関数 '{up['function']}' の引数 '{up['param']}': {up.get('reason', '')}")
            else:
                print("  なし (未参照の引数は検出されませんでした)")
            print()

            fe_warns = diag.get("frontend_warnings", [])
            print(f"[フロントエンド・キャッシュ警告] ({len(fe_warns)}件):")
            if fe_warns:
                for fw in fe_warns:
                    print(f"  - {fw['file']} 行 {fw['line']} [{fw['kind']}]: {fw['reason']}")
            else:
                print("  なし (IndexedDBゾンビや同期描画ブロック等は検出されませんでした)")
            print()

            print("[検出されたエントリーポイント]:")
            if diag["entry_points"]:
                for ep_name, locs in diag["entry_points"].items():
                    loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in locs])
                    print(f"  - {ep_name} -> {loc_str}")
            else:
                print("  (doGet/doPost/onOpen 等のエントリーポイント未検出)")

            if diag.get("manifest"):
                mf = diag["manifest"]
                print()
                print("[マニフェスト設定 (appsscript.json)]:")
                print(f"  - Runtime: {mf.get('runtimeVersion', 'V8')}")
                print(f"  - TimeZone: {mf.get('timeZone', 'N/A')}")
                if mf.get("webapp"):
                    wa = mf["webapp"]
                    print(f"  - WebApp: access={wa.get('access', 'N/A')}, executeAs={wa.get('executeAs', 'N/A')}")

        elif args.command in ("verify-ui", "verify_frontend"):
            res = client.verify_frontend(args.project, filename=args.file, test_js=args.test_js)
            status_tag = "[SUCCESS]" if res.get("success") else "[FAILED]"
            print(f"=== フロントエンド実機シミュレーション: [{args.project}] ({res.get('file', args.file)}) ===")
            print(f"判定: {status_tag}")
            if res.get("error"):
                print(f"エラー: {res['error']}")
            if res.get("test_result") is not None:
                print(f"test_result: {res['test_result']}")
            print(f"IndexedDB レコード数: {res.get('db_records_count', 0)}件")
            if res.get("rpc_calls"):
                print(f"google.script.run 呼出: {len(res['rpc_calls'])}件")
                for c in res["rpc_calls"][:5]:
                    chain_str = ".".join([str(p[0]) if isinstance(p, list) else str(p) for p in c.get("chain", [])])
                    print(f"  - {chain_str}({c.get('args', [])})")
            if res.get("alerts"):
                print(f"alert 出力: {len(res['alerts'])}件: {res['alerts']}")
            if res.get("confirms"):
                print(f"confirm 出力: {len(res['confirms'])}件: {res['confirms']}")

        elif args.command == "grep":
            res = client.search_code(args.project, args.pattern, regex=args.regex, filename=args.file, exclude=args.exclude, max_hits=args.max_hits)
            print(f"Total hits: {res['total_hits']}")
            for hit in res["hits"]:
                print(f"  {hit}")

        elif args.command == "get":
            info = client.get_file(args.project, args.filename, start_line=args.start_line, end_line=args.end_line)
            if "start_line" in info and "end_line" in info:
                print(f"// === [{args.project}] {info['name']}.{info['type']} ({len(info['source']):,} 文字, 行 {info['start_line']}-{info['end_line']} / 全{info['total_lines']}行) ===")
            else:
                print(f"// === [{args.project}] {info['name']}.{info['type']} ({len(info['source']):,} 文字) ===")
            print(info["source"])

        elif args.command == "func":
            code = client.get_function(args.project, args.filename, args.func_name)
            print(f"// === [{args.project}] {args.filename} -> function {args.func_name} ({len(code):,} 文字) ===")
            print(code)

        elif args.command == "patch":
            res = client.patch_code(args.project, args.filename, args.target, args.replacement, replace_all=args.all, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} 置換対象: {res['file']}, 置換箇所: {res['replaced_occurrences']}箇所, 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "patch-func":
            res = client.patch_function(args.project, args.filename, args.func_name, args.target, args.replacement, replace_all=args.all, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} 関数内置換: {res['file']} -> {res['function']}, 置換箇所: {res['replaced_occurrences']}箇所, 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "replace-func":
            # code_or_file がファイル実在する場合はファイルから読み込み
            if Path(args.code_or_file).exists():
                with open(args.code_or_file, "r", encoding="utf-8") as f:
                    new_code = f.read()
            else:
                new_code = args.code_or_file

            res = client.replace_function(args.project, args.filename, args.func_name, new_code, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} 関数置換: {res['file']} -> {res['function']}, 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "add-func":
            if Path(args.code_or_file).exists():
                with open(args.code_or_file, "r", encoding="utf-8") as f:
                    new_code = f.read()
            else:
                new_code = args.code_or_file

            res = client.add_function(args.project, args.filename, new_code, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} 関数追加: {res['file']} -> {res['function']}, 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "del-func":
            res = client.delete_function(args.project, args.filename, args.func_name, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} 関数削除: {res['file']} -> {res['deleted_function']}, 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "batch":
            if Path(args.ops_json_or_file).exists():
                with open(args.ops_json_or_file, "r", encoding="utf-8") as f:
                    ops_data = json.load(f)
            else:
                ops_data = json.loads(args.ops_json_or_file)

            res = client.batch_patch(args.project, ops_data, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} アトミック一括反映完了 ({len(res.get('applied_operations', []))}操作, 変更ファイル: {', '.join(res.get('changed_files', []))})")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "replace":
            with open(args.file_path, "r", encoding="utf-8") as f:
                new_src = f.read()
            res = client.replace_file(args.project, args.filename, new_src, force=args.force, dry_run=args.dry_run, deploy=args.deploy)
            prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
            print(f"{prefix} ファイル置換: {res['file']} ({res['length']:,} 文字), 構文: {res.get('syntax_check', 'N/A')}")
            if res.get("backup_file"):
                print(f"バックアップ: {res['backup_file']}")
            if res.get("diff"):
                print("--- 差分 (Diff) ---")
                print(res["diff"])
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "add":
            res = client.add_file(args.project, args.filename, args.type, source=args.source, force=args.force)
            print(f"[SUCCESS] ファイル追加: {res['added_file']} ({res['type']}), 構文: {res.get('syntax_check', 'N/A')}")
            print(f"バックアップ: {res['backup_file']}")

        elif args.command == "delete":
            res = client.delete_file(args.project, args.file)
            print(f"[SUCCESS] ファイル削除: {res['deleted_file']}")
            print(f"バックアップ: {res['backup_file']}")

        elif args.command == "backups":
            baks = client.list_backups(args.project, limit=args.limit)
            print(f"=== バックアップ一覧 ({len(baks)}件) ===")
            for b in baks:
                print(f"- {b['backup_file']} ({b['timestamp']}, {b['file_count']}ファイル, {b['size_bytes']:,} bytes)")

        elif args.command == "restore":
            res = client.restore_backup(args.project, args.backup_file, filename=args.file)
            print(f"[SUCCESS] 復元完了 (範囲: {res['restored_scope']})")
            print(f"直前退避スナップショット: {res['safety_backup']}")

        elif args.command == "diff":
            res = client.diff_backup(args.project, backup_file=args.backup_file, filename=args.file)
            changed = res.get("changed_files", [])
            if not changed:
                print("差分はありません（現在のコードと一致しています）")
            else:
                print(f"=== バックアップ [{res['backup_file']}] との差分 ({len(changed)}ファイル変更: {', '.join(changed)}) ===")
                print(res["diff"])

        elif args.command == "deploy":
            res = client.deploy(args.project, description=args.desc, refresh=args.refresh)
            print(f"[SUCCESS] 本番デプロイ完了 (Version: {res['versionNumber']})")
            print(f"WebアプリURL: {res.get('webAppUrl', 'N/A')}")

        elif args.command in ("deployments", "deps"):
            deps = client.list_deployments(args.project)
            headers = ["デプロイID", "Version", "更新日時", "WebアプリURL", "説明"]
            rows = []
            for d in deps:
                rows.append([
                    d.get("deploymentId", ""),
                    d.get("versionNumber", ""),
                    d.get("updateTime", "")[:19].replace("T", " "),
                    d.get("webAppUrl", ""),
                    d.get("description", "")
                ])
            print(f"=== [{args.project}] のデプロイ一覧 ({len(rows)}件) ===")
            print_table(headers, rows)

        elif args.command == "versions":
            vers = client.list_versions(args.project, limit=args.limit)
            headers = ["Version", "作成日時", "説明"]
            rows = []
            for v in vers:
                rows.append([
                    v.get("versionNumber", ""),
                    v.get("createTime", "")[:19].replace("T", " "),
                    v.get("description", "")
                ])
            print(f"=== [{args.project}] の不変バージョン一覧 ({len(rows)}件) ===")
            print_table(headers, rows)

        elif args.command in ("diff-prod", "diff-version"):
            res = client.diff_version(args.project, version_number=args.version, filename=args.file)
            changed = res.get("changed_files", [])
            target_v = res.get("target_version", "HEAD")
            if not changed:
                print(f"Version {target_v} と現在の最新HEADコードに差分はありません")
            else:
                print(f"=== Version {target_v} と最新HEADコードの差分 ({len(changed)}ファイル変更: {', '.join(changed)}) ===")
                print(res["diff"])

        elif args.command == "restore-version":
            res = client.restore_version(args.project, args.version, filename=args.file, deploy=args.deploy)
            print(f"[SUCCESS] バージョン {res['target_version']} から復元完了 (範囲: {res['restored_scope']})")
            print(f"直前退避スナップショット: {res['safety_backup']}")
            if res.get("deployment"):
                dep = res["deployment"]
                print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command == "run":
            parsed_args = []
            if args.args_json:
                try:
                    val = json.loads(args.args_json)
                    parsed_args = val if isinstance(val, list) else [val]
                except Exception:
                    parsed_args = [args.args_json]
            res = client.run_function(args.project, args.func_name, args=parsed_args, keep_runner=args.keep_runner, fast=args.fast)
            status_tag = "[SUCCESS]" if res.get("status") == "success" else "[FAILED]"
            dur = res.get("duration_ms", 0)
            print(f"{status_tag} 関数実行: {res.get('function', args.func_name)} (所要時間: {dur}ms)")
            if "result" in res:
                print(f"戻り値: {json.dumps(res['result'], ensure_ascii=False, indent=2)}")
            if res.get("logs"):
                print("--- 実行ログ ---")
                for lg in res["logs"]:
                    print(f"  {lg}")
            if res.get("error"):
                print(f"エラー: {res['error']}")

        elif args.command in ("bench", "benchmark"):
            parsed_args = []
            if args.args_json:
                try:
                    val = json.loads(args.args_json)
                    parsed_args = val if isinstance(val, list) else [val]
                except Exception:
                    parsed_args = [args.args_json]
            res = client.benchmark_function(
                args.project, args.func_name, args=parsed_args,
                target_ms=args.target_ms, iterations=args.iterations,
                expected=args.expected if args.expected != "" else None,
                fast=not args.no_fast
            )
            print(f"=== GAS ベンチマーク関所: [{args.project}] -> {args.func_name} ===")
            print(f"判定: [{res.get('verdict', 'FAILED')}] (スコア: {res.get('score', 0)}/100点)")
            print(f"実行速度: 平均 {res.get('avg_ms', 0)}ms (最小 {res.get('min_ms', 0)}ms / 最大 {res.get('max_ms', 0)}ms) | 目標: {res.get('target_ms', args.target_ms)}ms 以内 ({res.get('iterations', 0)}回計測)")
            if res.get("expected_checked"):
                print(f"期待値照合: {'一致 (OK)' if res.get('expected_match') else '不一致 (NG)'}")
            if "result" in res and res.get("status") == "success":
                print(f"戻り値: {json.dumps(res['result'], ensure_ascii=False)}")
            if res.get("logs"):
                print("--- 実行ログ ---")
                for lg in res["logs"]:
                    print(f"  {lg}")
            if res.get("prescriptions"):
                print("--- カイゼン処方箋 (Next Actions) ---")
                for pr in res["prescriptions"]:
                    print(f"  * {pr}")

        elif args.command == "clean-runner":
            res = client.clean_runner(args.project)
            if res.get("modified"):
                print(f"[SUCCESS] 実行ランナーを除去しました (プロジェクト: {res['script_id']})")
                if res.get("backup_file"):
                    print(f"事前バックアップ: {res['backup_file']}")
            else:
                print(f"[INFO] 実行ランナーは設置されていません（クリーン状態です）")

        elif args.command == "pull":
            res = client.pull(args.project, local_dir=args.local_dir, clean=args.clean)
            print(f"[SUCCESS] プロジェクト [{res['script_id']}] から {res['count']} ファイルを取得しました -> {res['local_dir']}")
            for pf in res["pulled_files"]:
                print(f"  - {pf}")

        elif args.command == "push":
            res = client.push(args.project, local_dir=args.local_dir, force=args.force, dry_run=args.dry_run, delete_missing=args.delete_missing, deploy=args.deploy, deploy_desc=args.desc)
            if res.get("status") == "no_changes":
                print("差分はありません（ローカルとクラウドは完全に一致しています）")
            else:
                prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
                print(f"{prefix} プッシュ完了: {len(res.get('changed_files', []))}ファイル変更 ({', '.join(res.get('changed_files', []))})")
                if res.get("backup_file"):
                    print(f"事前バックアップ: {res['backup_file']}")
                if res.get("diff"):
                    print("--- 差分 (Diff) ---")
                    print(res["diff"])
                if res.get("deployment"):
                    dep = res["deployment"]
                    print(f"本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")

        elif args.command in ("status", "sync-status"):
            res = client.sync_status(args.project, local_dir=args.local_dir)
            print(f"=== 同期状態: [{res['script_id']}] <-> {res['local_dir']} ===")
            print(f"変更 (Modified): {len(res['modified'])}件 ({', '.join(res['modified']) if res['modified'] else 'なし'})")
            print(f"新規 (Added): {len(res['added'])}件 ({', '.join(res['added']) if res['added'] else 'なし'})")
            print(f"クラウドのみ (Remote Only): {len(res['remote_only'])}件 ({', '.join(res['remote_only']) if res['remote_only'] else 'なし'})")
            print(f"未変更 (Unchanged): {len(res['unchanged'])}件")
            if res.get("diff"):
                print("\n--- 差分 (Diff) ---")
                print(res["diff"])

        elif args.command == "add-channel":
            res = client.add_qquick_channel(args.project, args.channel, channel_name=args.name)
            print(f"[{res['status'].upper()}] チャンネル: {res.get('channelName', '')} ({res.get('channelId', '')})")
            if res.get("webAppUrl"):
                print(f"URL: {res['webAppUrl']}")

        elif args.command == "webapp":
            res = client.call_webapp(args.url, params=args.params, body=args.body, method=args.method, key=args.key, use_auth=args.auth, dev=args.dev)
            print(res)

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
