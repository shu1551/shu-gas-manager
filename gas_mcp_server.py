#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gas_mcp_server.py - ガスマネージャー (gas-manager) MCP サーバー
Google Apps Script (GAS) を AI から直接読み書き・ピンポイント差分置換するための MCP ツール群
"""

import sys
import os
import shlex
from pathlib import Path

# 自モジュールのパスを通す
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from mcp.server.fastmcp import FastMCP
from gas_client import GasClient

import functools

mcp = FastMCP("gas-manager")
_client = None

def safe_tool(func):
    """例外発生時に安全な [ERROR] メッセージを返却するデコレータ"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return f"[ERROR] {type(e).__name__}: {str(e)}"
    return wrapper

def get_client() -> GasClient:
    global _client
    if _client is None:
        _client = GasClient()
    return _client

@mcp.tool()
@safe_tool
def list_projects(limit: int = 20) -> str:
    """Google Drive 上の GAS プロジェクト一覧を取得します。

    Args:
        limit: 取得する最大件数 (デフォルト: 20)
    """
    client = get_client()
    projects = client.list_projects(limit=limit)
    if not projects:
        return "プロジェクトが見つかりませんでした。"

    lines = [f"=== GAS プロジェクト一覧 ({len(projects)}件) ==="]
    for p in projects:
        mtime = p.get("modifiedTime", "")[:19].replace("T", " ")
        lines.append(f"- {p['name']} (ID: {p['id']}, 更新: {mtime})")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def list_files(project: str) -> str:
    """指定したプロジェクト内のファイル一覧（名前・種類・サイズ）を取得します。

    Args:
        project: プロジェクト名（部分一致可）またはスクリプトID
    """
    client = get_client()
    files = client.list_files(project)
    if not files:
        return f"[{project}] にファイルが見つかりませんでした。"

    lines = [f"=== [{project}] のファイル一覧 ({len(files)}件) ==="]
    for f in files:
        lines.append(f"- {f['name']}.{f['type']} ({f['length']:,} 文字)")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def get_file(project: str, filename: str, start_line: int = 0, end_line: int = 0) -> str:
    """指定したプロジェクトから特定ファイル（.js または .html）のコード全文または指定行範囲を取得します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名（拡張子有無どちらでも可。例: GQuick_Server または GQuick_Server.js）
        start_line: 取得開始行番号（1始まり、0以下は先頭から）
        end_line: 取得終了行番号（1始まり、0以下は末尾まで）
    """
    client = get_client()
    s_line = start_line if start_line > 0 else None
    e_line = end_line if end_line > 0 else None
    info = client.get_file(project, filename, start_line=s_line, end_line=e_line)
    if "start_line" in info and "end_line" in info:
        header = f"// === [{project}] {info['name']}.{info['type']} ({len(info['source']):,} 文字, 行 {info['start_line']}-{info['end_line']} / 全{info['total_lines']}行) ===\n"
    else:
        header = f"// === [{project}] {info['name']}.{info['type']} ({len(info['source']):,} 文字) ===\n"
    return header + info["source"]

@mcp.tool()
@safe_tool
def get_function(project: str, filename: str, func_name: str) -> str:
    """指定したファイルから特定の関数定義（function または const = (...) => ...）のコードブロックのみを抽出して取得します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        func_name: 取得したい関数名 (例: doGet)
    """
    client = get_client()
    code = client.get_function(project, filename, func_name)
    header = f"// === [{project}] {filename} -> function {func_name} ({len(code)} 文字) ===\n"
    return header + code

@mcp.tool()
@safe_tool
def list_functions(project: str, filename: str = "") -> str:
    """指定したプロジェクト内の関数一覧およびその行範囲・文字数を取得します（構造マップ / outline）。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 特定ファイルのみを対象にする場合に指定
    """
    client = get_client()
    file_funcs = client.list_functions(project, filename=filename)
    if not file_funcs:
        return f"[{project}] に対象ファイルが見つかりませんでした。"

    lines = [f"=== [{project}] の関数一覧 ({len(file_funcs)}ファイル) ==="]
    for ff in file_funcs:
        fname = ff["file"]
        ftype = ff["type"]
        funcs = ff["functions"]
        lines.append(f"\n[{fname}.{ftype}] ({len(funcs)}個の関数)")
        if not funcs:
            lines.append("  (関数は見つかりませんでした)")
        for fn in funcs:
            lines.append(f"  - {fn['name']} (行 {fn['start_line']}-{fn['end_line']}, {fn['length']:,} 文字)")

    return "\n".join(lines)

@mcp.tool()
@safe_tool
def patch_code(project: str, filename: str, target: str = "", replacement: str = "", replace_all: bool = False, force: bool = False, dry_run: bool = False, patches: str = "", deploy: bool = False) -> str:
    """ファイル内の特定コード文字列を置換し、Google クラウドへ反映します。
    置換前に自動バックアップと Node.js vm による構文検査を実施します。
    patches 引数に JSON 文字列（例: '[{"target":"a","replacement":"b"}]'）を指定することで複数箇所の一括置換も可能です。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        target: 置換前の既存コード文字列（完全一致）
        replacement: 置換後の新しいコード文字列
        replace_all: 複数箇所の一括置換を許可するか (デフォルト: False)
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        patches: 複数ペアの一括置換を行う場合の JSON 文字列 (デフォルト: "")
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.patch_code(project, filename, target=target, replacement=replacement, replace_all=replace_all, force=force, dry_run=dry_run, patches=patches if patches else None, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] 差分プレビュー（クラウドへの書き込み・バックアップは行われていません）\n"
            f"ファイル: {res['file']}\n"
            f"置換箇所: {res['replaced_occurrences']}箇所\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] 差分置換完了\n"
        f"ファイル: {res['file']}\n"
        f"置換箇所: {res['replaced_occurrences']}箇所\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def replace_file(project: str, filename: str, new_source: str, force: bool = False, dry_run: bool = False, deploy: bool = False) -> str:
    """指定ファイルの中身を丸ごと置き換え、Google クラウドへ反映します。
    反映前に自動バックアップと構文検査を実施します。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        new_source: 新しいコード全文
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.replace_file(project, filename, new_source, force=force, dry_run=dry_run, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] ファイル丸ごと置換プレビュー（クラウドへの書き込みは行われていません）\n"
            f"ファイル: {res['file']} ({res['length']:,} 文字)\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] ファイル丸ごと置換完了\n"
        f"ファイル: {res['file']} ({res['length']:,} 文字)\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def add_file(project: str, filename: str, file_type: str, source: str = "", force: bool = False) -> str:
    """新しいファイル（JS または HTML）を追加し、Google クラウドへ反映します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 追加するファイル名（拡張子なし）
        file_type: 'js' (または SERVER_JS) または 'html' (HTML)
        source: 初期コード（空文字列可）
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
    """
    client = get_client()
    res = client.add_file(project, filename, file_type, source, force=force)
    return (
        f"[SUCCESS] ファイル追加完了\n"
        f"追加ファイル: {res['added_file']} ({res['type']})\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
    )

@mcp.tool()
@safe_tool
def delete_file(project: str, filename: str) -> str:
    """プロジェクトから指定ファイルを削除し、Google クラウドへ反映します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 削除するファイル名
    """
    client = get_client()
    res = client.delete_file(project, filename)
    return (
        f"[SUCCESS] ファイル削除完了\n"
        f"削除ファイル: {res['deleted_file']}\n"
        f"事前バックアップ: {res['backup_file']}"
    )

@mcp.tool()
@safe_tool
def list_backups(project: str, limit: int = 10) -> str:
    """指定したプロジェクトのローカルバックアップ一覧を取得します。

    Args:
        project: プロジェクト名またはスクリプトID
        limit: 取得件数 (デフォルト: 10)
    """
    client = get_client()
    backups = client.list_backups(project, limit=limit)
    if not backups:
        return f"[{project}] のバックアップは見つかりませんでした。"
    lines = [f"=== [{project}] のバックアップ一覧 ({len(backups)}件) ==="]
    for b_item in backups:
        lines.append(f"- {b_item['backup_file']} ({b_item['timestamp']}, {b_item['file_count']}ファイル, {b_item['size_bytes']:,} bytes)")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def restore_backup(project: str, backup_file: str, filename: str = "") -> str:
    """指定したバックアップファイルからプロジェクト全体または特定ファイルを復元します。
    復元直前の状態は安全スナップショットとして自動退避されます。

    Args:
        project: プロジェクト名またはスクリプトID
        backup_file: バックアップファイル名 (.backups/ 内のファイル名)
        filename: 特定のファイルのみ復元したい場合に指定（空の場合は全復元）
    """
    client = get_client()
    res = client.restore_backup(project, backup_file, filename=filename)
    if res["restored_scope"] == "project_all":
        return (
            f"[SUCCESS] プロジェクト全体復元完了\n"
            f"復元ファイル数: {res['restored_files_count']}ファイル\n"
            f"直前安全スナップショット: {res['safety_backup']}"
        )
    else:
        return (
            f"[SUCCESS] ファイル復元完了\n"
            f"復元ファイル: {res['restored_file']}\n"
            f"直前安全スナップショット: {res['safety_backup']}"
        )

@mcp.tool()
@safe_tool
def diff_backup(project: str, backup_file: str = "", filename: str = "") -> str:
    """指定したプロジェクトのバックアップと現在のコードの差分を比較します。

    Args:
        project: プロジェクト名またはスクリプトID
        backup_file: 比較対象のバックアップファイル名（省略時は直近の最新バックアップ）
        filename: 特定ファイルのみを比較する場合に指定（省略時は全ファイル）
    """
    client = get_client()
    res = client.diff_backup(project, backup_file=backup_file, filename=filename)
    changed = res.get("changed_files", [])
    if not changed:
        return "差分はありません（現在のコードと一致しています）"
    return f"=== バックアップ [{res['backup_file']}] との差分 ({len(changed)}ファイル変更: {', '.join(changed)}) ===\n{res['diff']}"

@mcp.tool()
@safe_tool
def deploy(project: str, description: str = "Auto deployed via MCP", refresh: bool = False) -> str:
    """新バージョンを作成し、既存の Web アプリデプロイを更新（再デプロイ）します。

    Args:
        project: プロジェクト名またはスクリプトID
        description: バージョンの説明文
        refresh: デプロイIDキャッシュを破棄して再取得するか (デフォルト: False)
    """
    client = get_client()
    res = client.deploy(project, description=description, refresh=refresh)
    return (
        f"[SUCCESS] 本番デプロイ完了 (Version {res['versionNumber']})\n"
        f"URL: {res.get('webAppUrl', 'N/A')}\n"
        f"説明: {res['description']}"
    )

@mcp.tool()
@safe_tool
def list_deployments(project: str) -> str:
    """指定したプロジェクトのデプロイ一覧を取得します。

    Args:
        project: プロジェクト名またはスクリプトID
    """
    client = get_client()
    deps = client.list_deployments(project)
    if not deps:
        return f"[{project}] にデプロイは見つかりませんでした。"

    lines = [f"=== [{project}] のデプロイ一覧 ({len(deps)}件) ==="]
    for d in deps:
        dep_id = d.get("deploymentId", "")
        v_num = d.get("versionNumber", "")
        up_time = d.get("updateTime", "")[:19].replace("T", " ")
        web_url = d.get("webAppUrl", "")
        desc = d.get("description", "")
        line_item = f"- [ID: {dep_id}] (Version: {v_num}, 更新: {up_time})"
        if web_url:
            line_item += f"\n  WebアプリURL: {web_url}"
        if desc:
            line_item += f"\n  説明: {desc}"
        lines.append(line_item)
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def add_channel(project: str, channel: str, channel_name: str = "") -> str:
    """Qクイック等の登録チャンネル管理用 API を呼び出し、即座にチャンネルを追加します。

    Args:
        project: プロジェクト名またはスクリプトID (例: 'Qクイック NEXT')
        channel: チャンネルID (UC...) または YouTube URL
        channel_name: チャンネル名（省略時は自動取得）
    """
    client = get_client()
    res = client.add_qquick_channel(project, channel, channel_name=channel_name)
    if res["status"] == "already_exists":
        return f"[INFO] チャンネル {res['channelId']} は既に登録されています。\nURL: {res.get('webAppUrl', '')}"
    
    total_str = f"\n現在の登録総数: {res['totalChannels']}件" if res.get("totalChannels") else ""
    name_str = f"\nチャンネル名: {res['channelName']}" if res.get("channelName") else ""
    return (
        f"[SUCCESS] チャンネル即時追加完了！（デプロイ不要・即座に反映）\n"
        f"チャンネルID: {res['channelId']}"
        f"{name_str}"
        f"{total_str}\n"
        f"WebアプリURL: {res.get('webAppUrl', '')}"
    )

@mcp.tool()
@safe_tool
def patch_function(project: str, filename: str, func_name: str, target: str = "", replacement: str = "", replace_all: bool = False, force: bool = False, dry_run: bool = False, patches: str = "", deploy: bool = False) -> str:
    """指定ファイル内の特定関数スコープ内に限定してコード置換を行います（他関数にある同一コードの誤爆を物理的に防止）。
    置換前の自動バックアップ、構文検査、diff 出力を完備しています。
    patches 引数に JSON 文字列（例: '[{"target":"a","replacement":"b"}]'）を指定することで複数箇所の一括置換も可能です。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        func_name: 対象の関数名
        target: 置換前の既存コード文字列
        replacement: 置換後の新しいコード文字列
        replace_all: 関数内の複数箇所置換を許可するか (デフォルト: False)
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        patches: 複数ペアの一括置換を行う場合の JSON 文字列 (デフォルト: "")
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.patch_function(project, filename, func_name, target=target, replacement=replacement, replace_all=replace_all, force=force, dry_run=dry_run, patches=patches if patches else None, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] 関数内置換プレビュー\n"
            f"ファイル: {res['file']} -> function {res['function']}\n"
            f"置換箇所: {res['replaced_occurrences']}箇所\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] 関数内置換完了\n"
        f"ファイル: {res['file']} -> function {res['function']}\n"
        f"置換箇所: {res['replaced_occurrences']}箇所\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def add_function(project: str, filename: str, code: str, force: bool = False, dry_run: bool = False, deploy: bool = False) -> str:
    """指定ファイルに新しい関数を追加します（既存関数との重複チェック付き）。
    HTMLファイルの場合は末尾の <script> タグ内へ安全に挿入されます。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        code: 追加する関数のコード
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.add_function(project, filename, code, force=force, dry_run=dry_run, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] 関数追加プレビュー\n"
            f"ファイル: {res['file']} -> function {res['function']}\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] 関数追加完了\n"
        f"ファイル: {res['file']} -> function {res['function']}\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def delete_function(project: str, filename: str, func_name: str, force: bool = False, dry_run: bool = False, deploy: bool = False) -> str:
    """指定ファイルから特定の関数を削除し、空行をスマートに整理します。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        func_name: 削除対象の関数名
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.delete_function(project, filename, func_name, force=force, dry_run=dry_run, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] 関数削除プレビュー\n"
            f"ファイル: {res['file']} -> function {res['deleted_function']}\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] 関数削除完了\n"
        f"ファイル: {res['file']} -> function {res['deleted_function']}\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def batch_patch(project: str, operations: str, force: bool = False, dry_run: bool = False, deploy: bool = False) -> str:
    """複数ファイル・複数操作（patch, patch_function, replace_function, add_function, delete_function, replace_file 等）を
    メモリ上で一括合成し、全ファイルの構文検査を経て1回の通信で安全にアトミック反映します。

    Args:
        project: プロジェクト名またはスクリプトID
        operations: 操作リストの JSON 文字列 (例: '[{"op":"patch_function","file":"main","function":"f","target":"a","replacement":"b"}]')
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    import json
    ops_data = json.loads(operations) if isinstance(operations, str) else operations
    client = get_client()
    res = client.batch_patch(project, ops_data, force=force, dry_run=dry_run, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    changed_str = ", ".join(res.get("changed_files", []))
    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] アトミック一括反映プレビュー\n"
            f"適用操作数: {len(res.get('applied_operations', []))}操作\n"
            f"変更対象ファイル: {changed_str}\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] アトミック一括反映完了\n"
        f"適用操作数: {len(res.get('applied_operations', []))}操作\n"
        f"変更対象ファイル: {changed_str}\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def replace_function(project: str, filename: str, func_name: str, code: str, force: bool = False, dry_run: bool = False, deploy: bool = False) -> str:
    """指定ファイル内の特定関数定義ブロックを丸ごと置換します（Excel の replace_procedure 相当）。
    置換前の自動バックアップ、構文検査、diff 出力を完備しています。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        func_name: 置換対象の関数名
        code: 新しい関数の定義コード全文
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.replace_function(project, filename, func_name, code, force=force, dry_run=dry_run, deploy=deploy)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    if res.get("status") == "dry_run":
        return (
            f"[DRY-RUN] 関数置換プレビュー\n"
            f"ファイル: {res['file']} -> function {res['function']}\n"
            f"構文検査: {res.get('syntax_check', 'N/A')}"
            f"{diff_out}"
        )
    return (
        f"[SUCCESS] 関数置換完了\n"
        f"ファイル: {res['file']} -> function {res['function']}\n"
        f"構文検査: {res.get('syntax_check', 'N/A')}\n"
        f"事前バックアップ: {res['backup_file']}"
        f"{diff_out}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def search_code(project: str, pattern: str, regex: bool = False, filename: str = "", exclude: str = "", max_hits: int = 100) -> str:
    """プロジェクト内の全ファイル（または指定ファイル）を高速横断検索（grep）します。

    Args:
        project: プロジェクト名またはスクリプトID
        pattern: 検索する文字列または正規表現
        regex: 正規表現検索を行うか (デフォルト: False)
        filename: 検索対象を特定ファイルに限定する場合に指定
        exclude: 除外するファイル名（カンマ区切りで複数指定可）
        max_hits: 最大ヒット件数 (デフォルト: 100)
    """
    client = get_client()
    res = client.search_code(project, pattern, regex=regex, filename=filename, exclude=exclude, max_hits=max_hits)
    if res["total_hits"] == 0:
        return f"[{project}] 内に '{pattern}' に一致するコードは見つかりませんでした。"
    
    lines = [f"=== [{project}] 横断検索結果 ({res['total_hits']}件ヒット) ==="]
    lines.extend(res["hits"])
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def list_versions(project: str, limit: int = 20) -> str:
    """指定したプロジェクトの Google Apps Script クラウド上の不変バージョン一覧を取得します。

    Args:
        project: プロジェクト名またはスクリプトID
        limit: 取得件数 (デフォルト: 20)
    """
    client = get_client()
    vers = client.list_versions(project, limit=limit)
    if not vers:
        return f"[{project}] にバージョンは見つかりませんでした。"
    lines = [f"=== [{project}] の不変バージョン一覧 ({len(vers)}件) ==="]
    for v in vers:
        ctime = v.get("createTime", "")[:19].replace("T", " ")
        lines.append(f"- Version {v.get('versionNumber', '')} ({ctime}): {v.get('description', '')}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def diff_version(project: str, version_number: int = None, filename: str = "") -> str:
    """本番バージョン（または指定した不変バージョン）と現在の最新HEADコードの差分を比較します。
    「本番と最新作業コードの間にどんな差分があるか」を一発で確認できます。

    Args:
        project: プロジェクト名またはスクリプトID
        version_number: 比較対象のバージョン番号（省略時は最新デプロイバージョン）
        filename: 特定ファイルのみ比較する場合に指定（省略時は全ファイル）
    """
    client = get_client()
    res = client.diff_version(project, version_number=version_number, filename=filename)
    changed = res.get("changed_files", [])
    target_v = res.get("target_version", "HEAD")
    if not changed:
        return f"Version {target_v} と現在の最新HEADコードに差分はありません（完全一致）。"
    return f"=== Version {target_v} と最新HEADコードの差分 ({len(changed)}ファイル変更: {', '.join(changed)}) ===\n{res['diff']}"

@mcp.tool()
@safe_tool
def restore_version(project: str, version_number: int, filename: str = "", deploy: bool = False) -> str:
    """クラウド上の不変バージョン（スナップショット）からプロジェクト全体または特定ファイルを復元します。
    復元直前の状態はローカル安全スナップショットとして自動退避されます。
    deploy=True を指定すると、復元直後に本番Webアプリの更新デプロイまで一撃で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        version_number: 復元したいバージョン番号
        filename: 特定ファイルのみ復元する場合に指定（省略時は全ファイル）
        deploy: 復元完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.restore_version(project, version_number, filename=filename, deploy=deploy)
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"

    return (
        f"[SUCCESS] バージョン {res['target_version']} から復元完了 (範囲: {res['restored_scope']})\n"
        f"直前安全スナップショット: {res['safety_backup']}"
        f"{dep_msg}"
    )

@mcp.tool()
@safe_tool
def run_function(project: str, func_name: str, args: str = "", keep_runner: bool = False, fast: bool = False) -> str:
    """プロジェクト内の指定GAS関数を一時ランナー経由でリモート実行し、戻り値・実行ログ・所要時間を一括回収します。
    実行後は一時ランナーを自動消去するため、プロジェクトを一切汚さないゼロフットプリント設計です。
    fast=True を指定すると、ランナーを常駐させて最速約0.3秒で実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        func_name: 実行したい関数名 (例: testMyLogic)
        args: 引数（JSON配列文字列または単一値文字列、省略時は引数なし）
        keep_runner: 実行ランナーを削除せず残すか (デフォルト: False)
        fast: キャッシュ優先＆ランナー常駐による超高速実行を行うか (デフォルト: False)
    """
    import json
    parsed_args = []
    if args:
        try:
            val = json.loads(args)
            parsed_args = val if isinstance(val, list) else [val]
        except Exception:
            parsed_args = [args]

    client = get_client()
    res = client.run_function(project, func_name, args=parsed_args, keep_runner=keep_runner, fast=fast)
    status_tag = "[SUCCESS]" if res.get("status") == "success" else "[FAILED]"
    dur = res.get("duration_ms", 0)
    lines = [
        f"{status_tag} 関数実行: {res.get('function', func_name)} (所要時間: {dur}ms)"
    ]
    if "result" in res:
        lines.append(f"戻り値: {json.dumps(res['result'], ensure_ascii=False, indent=2)}")
    if res.get("logs"):
        lines.append("--- 実行ログ ---")
        for lg in res["logs"]:
            lines.append(f"  {lg}")
    if res.get("error"):
        lines.append(f"エラー: {res['error']}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def clean_runner(project: str) -> str:
    """プロジェクト内に残った実行ランナー (__gm_exec_) および doGet フックを綺麗に除去します。

    Args:
        project: プロジェクト名またはスクリプトID
    """
    client = get_client()
    res = client.clean_runner(project)
    if res.get("modified"):
        return f"[SUCCESS] 実行ランナーを除去しました (プロジェクト: {res['script_id']})\n事前バックアップ: {res.get('backup_file', 'なし')}"
    return f"[INFO] 実行ランナーは設置されていません（クリーン状態です）"

@mcp.tool()
@safe_tool
def pull_project(project: str, local_dir: str = ".", clean: bool = False) -> str:
    """クラウドの GAS プロジェクト全ファイルをローカルフォルダへ書き出します（Git管理・VSCode編集用）。

    Args:
        project: プロジェクト名またはスクリプトID
        local_dir: 保存先ローカルフォルダパス (デフォルト: カレント)
        clean: クラウド側に存在しないローカルファイルを自動削除するか (デフォルト: False)
    """
    client = get_client()
    res = client.pull(project, local_dir=local_dir, clean=clean)
    lines = [
        f"[SUCCESS] プロジェクト [{res['script_id']}] から {res['count']} ファイルを取得しました -> {res['local_dir']}"
    ]
    for pf in res["pulled_files"]:
        lines.append(f"- {pf}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def push_project(project: str = "", local_dir: str = ".", force: bool = False, dry_run: bool = False, delete_missing: bool = False, deploy: bool = False, desc: str = "Pushed via MCP") -> str:
    """ローカルフォルダのコードをクラウドへ一括反映します。差分0件時はAPI通信をスキップしミリ秒で即返却します。
    Node.js による全ファイルの一括構文検査、自動バックアップ、デプロイ連動を完備しています。

    Args:
        project: プロジェクト名またはスクリプトID (省略時は .gas-sync.json から自動検出)
        local_dir: 対象ローカルフォルダパス (デフォルト: カレント)
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        delete_missing: ローカルに存在しないクラウドファイルを削除するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
        desc: デプロイ時の説明文 (デフォルト: Pushed via MCP)
    """
    client = get_client()
    res = client.push(project, local_dir=local_dir, force=force, dry_run=dry_run, delete_missing=delete_missing, deploy=deploy, deploy_desc=desc)
    if res.get("status") == "no_changes":
        return "差分はありません（ローカルとクラウドは完全に一致しています）。"

    prefix = "[DRY-RUN]" if res.get("status") == "dry_run" else "[SUCCESS]"
    lines = [
        f"{prefix} プッシュ完了: {len(res.get('changed_files', []))}ファイル変更 ({', '.join(res.get('changed_files', []))})"
    ]
    if res.get("backup_file"):
        lines.append(f"事前バックアップ: {res['backup_file']}")
    if res.get("diff"):
        lines.append(f"\n--- 差分 (Diff) ---\n{res['diff']}")
    if res.get("deployment"):
        dep = res["deployment"]
        lines.append(f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def sync_status(project: str = "", local_dir: str = ".") -> str:
    """ローカルフォルダとクラウドの差分状態（変更・新規・クラウドのみ・未変更）を確認します。

    Args:
        project: プロジェクト名またはスクリプトID (省略時は .gas-sync.json から自動検出)
        local_dir: 対象ローカルフォルダパス (デフォルト: カレント)
    """
    client = get_client()
    res = client.sync_status(project, local_dir=local_dir)
    lines = [
        f"=== 同期状態: [{res['script_id']}] <-> {res['local_dir']} ===",
        f"変更 (Modified): {len(res['modified'])}件 ({', '.join(res['modified']) if res['modified'] else 'なし'})",
        f"新規 (Added): {len(res['added'])}件 ({', '.join(res['added']) if res['added'] else 'なし'})",
        f"クラウドのみ (Remote Only): {len(res['remote_only'])}件 ({', '.join(res['remote_only']) if res['remote_only'] else 'なし'})",
        f"未変更 (Unchanged): {len(res['unchanged'])}件"
    ]
    if res.get("diff"):
        lines.append(f"\n--- 差分 (Diff) ---\n{res['diff']}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def call_webapp(url: str, params: str = "", method: str = "GET", key: str = "", body: str = "", auth: bool = False, dev: bool = False) -> str:
    """clasp/OAuth 認証を一切使わず、GAS の Web アプリ URL（doGet/doPost）へ直接アクセスして処理を実行します（中継機モード）。
    dev=True を指定すると、プロジェクト名やスクリプトIDから最新の HEAD (最新作業コード) の開発用デプロイを優先解決し、Bearer トークン付きで直接呼び出します。

    Args:
        url: WebアプリのURL (https://script.google.com/macros/s/.../exec) または プロジェクト名/スクリプトID
        params: クエリパラメータ (例: "add=UCxxx&name=テスト" または JSON文字列 '{"add":"UCxxx"}')
        method: HTTPメソッド ('GET' または 'POST'、デフォルト: GET)
        key: 秘密の合言葉・パスコード（指定時は key パラメータとして自動付与）
        body: POST時の送信本文データ（JSONまたはテキスト）
        auth: True の場合は現在の環境の認証トークンを付与（自分専用デプロイ用、デフォルト: False）
        dev: True の場合は最新 HEAD デプロイを優先し Bearer 認証で直接呼び出し (デフォルト: False)
    """
    client = get_client()
    res = client.call_webapp(url, params=params, body=body if body else None, method=method, key=key if key else None, use_auth=auth, dev=dev)
    if isinstance(res, dict) and "data" in res:
        import json
        formatted = json.dumps(res["data"], ensure_ascii=False, indent=2)
        return f"[SUCCESS HTTP {res['status_code']}]\n{formatted}"
    elif isinstance(res, dict) and "text" in res:
        return f"[HTTP {res['status_code']}]\n{res['text']}"
    return str(res)

@mcp.tool()
@safe_tool
def diagnose(project: str) -> str:
    """指定した GAS プロジェクトの包括的健康診断（構文検査・トップレベル重複衝突・グローバル変数衝突・RPCリンク切れ・テンプレート検証・パフォーマンス警告・未使用関数検出・エントリーポイント）を実行します。

    Args:
        project: プロジェクト名またはスクリプトID
    """
    client = get_client()
    diag = client.diagnose(project)

    status_str = "正常 (HEALTHY)" if diag["status"] == "healthy" else f"警告あり (WARNING: {diag['issues_count']}件の問題)"
    lines = [
        f"=== GAS プロジェクト健康診断: [{project}] ===",
        f"判定: {status_str}",
        f"ファイル数: {diag['file_count']} | 総関数数: {diag['total_functions']} | 検出された問題: {diag['issues_count']}件",
        ""
    ]

    # 1. 構文エラー
    lines.append(f"[構文エラー] ({len(diag['syntax_errors'])}件):")
    if diag["syntax_errors"]:
        for se in diag["syntax_errors"]:
            lines.append(f"  - [{se['file']}.{se['type']}] {se['error']}")
    else:
        lines.append("  なし (全ファイル構文チェック合格)")
    lines.append("")

    # 2. トップレベル関数重複衝突
    lines.append(f"[重複関数・グローバル衝突] ({len(diag['duplicate_functions'])}件):")
    if diag["duplicate_functions"]:
        for df in diag["duplicate_functions"]:
            loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in df["locations"]])
            lines.append(f"  - 関数 '{df['name']}' が {len(df['locations'])} 箇所で定義されています: ({loc_str})")
    else:
        lines.append("  なし (グローバル名前空間での関数名衝突はありません)")
    lines.append("")

    # 2b. グローバル変数・クラス衝突
    dup_globals = diag.get("duplicate_globals", [])
    lines.append(f"[グローバル変数・クラス衝突 (const/let/class)] ({len(dup_globals)}件):")
    if dup_globals:
        for dg in dup_globals:
            loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in dg["locations"]])
            lines.append(f"  - 識別子 '{dg['name']}' が複数ファイルで重複定義されています: ({loc_str})")
    else:
        lines.append("  なし (グローバル変数の衝突はありません)")
    lines.append("")

    # 3. HTML -> サーバー RPC リンク切れ (google.script.run)
    lines.append(f"[HTML RPC リンク切れ (google.script.run)] ({len(diag['broken_rpc_calls'])}件):")
    if diag["broken_rpc_calls"]:
        for rpc in diag["broken_rpc_calls"]:
            lines.append(f"  - {rpc['file']} 行 {rpc['line']}: サーバー関数 '{rpc['target_function']}' -> {rpc.get('reason', '関数が見つかりません')}")
    else:
        lines.append("  なし (全ての google.script.run 呼び出し先関数が存在します)")
    lines.append("")

    # 3b. RPC 引数不一致警告
    rpc_arity = diag.get("rpc_arity_warnings", [])
    lines.append(f"[RPC 引数不一致警告] ({len(rpc_arity)}件):")
    if rpc_arity:
        for ra in rpc_arity:
            lines.append(f"  - {ra['file']} 行 {ra['line']}: 関数 '{ra['target_function']}' (期待: {ra.get('expected', 'N/A')}, 呼出: {ra.get('actual', 'N/A')}) -> {ra.get('reason', '')}")
    else:
        lines.append("  なし (RPC引数の不一致はありません)")
    lines.append("")

    # 4. HtmlService テンプレートリンク切れ
    lines.append(f"[HTML テンプレートリンク切れ (HtmlService)] ({len(diag['broken_html_templates'])}件):")
    if diag["broken_html_templates"]:
        for tpl in diag["broken_html_templates"]:
            lines.append(f"  - {tpl['file']} 行 {tpl['line']}: {tpl['reason']}")
    else:
        lines.append("  なし (全てのテンプレート参照先 HTML が存在します)")
    lines.append("")

    # 4b. パフォーマンス警告
    perf_warns = diag.get("performance_warnings", [])
    lines.append(f"[パフォーマンス警告 (ループ内同期API)] ({len(perf_warns)}件):")
    if perf_warns:
        for pw in perf_warns:
            lines.append(f"  - {pw['file']} 行 {pw['line']}: {pw['api']} -> {pw.get('reason', '')}")
    else:
        lines.append("  なし (ループ内での過剰な同期API呼出は検出されませんでした)")
    lines.append("")

    # 4c. 未使用・未参照関数
    unused_fn = diag.get("unused_functions", [])
    lines.append(f"[未参照・未使用の疑いがある関数] ({len(unused_fn)}件):")
    if unused_fn:
        for uf in unused_fn:
            lines.append(f"  - [{uf['file']}:{uf['line']}] {uf['name']}")
    else:
        lines.append("  なし (全関数が参照されているかエントリーポイントです)")
    lines.append("")

    # 5. エントリーポイント
    lines.append("[検出されたエントリーポイント]:")
    if diag["entry_points"]:
        for ep_name, locs in diag["entry_points"].items():
            loc_str = ", ".join([f"{loc['file']}:{loc['line']}" for loc in locs])
            lines.append(f"  - {ep_name} -> {loc_str}")
    else:
        lines.append("  (doGet/doPost/onOpen 等のエントリーポイント未検出)")

    # 6. マニフェスト設定
    if diag.get("manifest"):
        mf = diag["manifest"]
        lines.append("")
        lines.append("[マニフェスト設定 (appsscript.json)]:")
        lines.append(f"  - Runtime: {mf.get('runtimeVersion', 'V8')}")
        lines.append(f"  - TimeZone: {mf.get('timeZone', 'N/A')}")
        if mf.get("webapp"):
            wa = mf["webapp"]
            lines.append(f"  - WebApp: access={wa.get('access', 'N/A')}, executeAs={wa.get('executeAs', 'N/A')}")

    return "\n".join(lines)

@mcp.tool()
@safe_tool
def setup_check(open_browser: bool = False) -> str:
    """ガスマネージャーの動作環境（Node.js・認証情報・Google API 疎通状態）を点検し、案内を返却します。
    セットアップ未完了の場合は必要な手順（clasp 導入・API 有効化）を自動案内します。

    Args:
        open_browser: True の場合、Google Apps Script API の設定ページをブラウザで自動起動
    """
    res = GasClient.check_setup(open_browser=open_browser)
    status_icons = {
        "ready": "[READY]",
        "needs_login": "[SETUP REQUIRED]",
        "needs_api_enable": "[ACTION REQUIRED]",
        "error": "[ERROR]"
    }
    lines = [
        f"=== GAS Manager セットアップ診断 {status_icons.get(res['status'], '')} ===",
        res["message"],
        ""
    ]
    if res.get("steps"):
        lines.append("【状態 / 手順】")
        for st in res["steps"]:
            lines.append(f"  {st}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def gas(command: str) -> str:
    """ガスマネージャー (GAS Manager) 統合コマンド窓口。
    CLI と同じコマンド形式（例: 'files MyProject', 'outline MyProject', 'patch-func MyProject main myFunc old new' 等）で
    一撃で GAS 操作を実行します。

    利用可能コマンド:
      - help
      - setup [--open]
      - list [limit]
      - files <project>
      - outline <project> [filename]  (または funcs)
      - diagnose <project>  (または diag)
      - grep <project> <pattern> [filename]
      - get <project> <filename> [start_line] [end_line]
      - func <project> <filename> <func_name>
      - patch-func <project> <filename> <func_name> <target> <replacement>
      - add-func <project> <filename> <code>
      - del-func <project> <filename> <func_name>
      - batch <project> <ops_json>
      - backups <project> [limit]
      - diff <project> [backup_file] [-f <file>]
      - restore <project> <backup_file> [-f <file>]
      - versions <project> [limit]
      - diff-prod <project> [-v <version>] [-f <file>]  (または diff-version)
      - restore-version <project> <version> [-f <file>] [--deploy]
      - run <project> <func_name> [args_json] [--keep-runner]
      - deploy <project> [description]
      - deployments <project>  (または deps)
      - webapp <url_or_project> [params] [--dev]
    """
    if not command or not command.strip():
        return "コマンドを指定してください。'help' で一覧を表示します。"

    parts = shlex.split(command.strip())
    sub = parts[0].lower()

    if sub == "help":
        return (
            "=== gas 統合コマンド一覧 ===\n"
            "  setup [--open]                    - 環境点検・初期設定案内（未導入時も安全実行）\n"
            "  list [limit]                      - プロジェクト一覧取得\n"
            "  files <project>                   - プロジェクト内ファイル一覧\n"
            "  outline <project> [file]          - 関数一覧・構造マップ（funcs でも可）\n"
            "  diagnose <project>                - プロジェクト健康診断（diag でも可）\n"
            "  grep <project> <pattern> [file]   - コード高速横断検索\n"
            "  get <project> <file> [s] [e]      - ファイルコード取得（行範囲指定可）\n"
            "  func <project> <file> <func_name> - 関数コードブロック抽出\n"
            "  patch-func <p> <f> <fn> <tgt> <r> - 関数内限定の安全コード置換\n"
            "  add-func <p> <f> <code>           - 関数追加（重複チェック付き）\n"
            "  del-func <p> <f> <func_name>      - 関数削除・空行整理\n"
            "  batch <project> <ops_json>        - 複数操作の一括アトミック合成反映\n"
            "  backups <project> [limit]         - バックアップ一覧\n"
            "  diff <project> [bak] [-f <file>]  - バックアップとの差分比較\n"
            "  restore <project> <bak> [-f <f>]  - バックアップから復元\n"
            "  versions <project> [limit]        - 不変バージョン一覧\n"
            "  diff-prod <p> [-v <v>] [-f <f>]   - 本番と最新HEADの差分比較（diff-versionでも可）\n"
            "  restore-version <p> <v> [--deploy]- 不変バージョンから復元\n"
            "  run <p> <fn> [args] [--fast]       - 高速関数実行＆ログ回収（--fast で約0.3秒）\n"
            "  clean-runner <project>            - 実行ランナー (__gm_exec_) の除去\n"
            "  pull <project> [dir] [--clean]    - クラウドからローカルへ同期\n"
            "  push [project] [dir] [--deploy]   - ローカルからクラウドへ一括反映\n"
            "  status [project] [dir]            - ローカルとクラウドの差分状態確認\n"
            "  deploy <project> [description]    - 本番Webアプリ更新デプロイ\n"
            "  deployments <project>             - デプロイ一覧（deps でも可）\n"
            "  webapp <url_or_p> [params] [--dev]- Webアプリ呼び出し（中継機モード）\n"
        )

    if sub == "setup":
        open_b = "--open" in parts
        return setup_check(open_browser=open_b)

    if sub == "list":
        limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        return list_projects(limit=limit)

    if sub == "files":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: files <project>"
        return list_files(parts[1])

    if sub in ("outline", "funcs"):
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: outline <project> [filename]"
        project = parts[1]
        fname = ""
        i = 2
        while i < len(parts):
            if parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif not parts[i].startswith("-"):
                fname = parts[i]
                i += 1
            else:
                i += 1
        return list_functions(project, filename=fname)

    if sub in ("diagnose", "diag"):
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: diagnose <project>"
        return diagnose(parts[1])

    if sub == "grep":
        if len(parts) < 3:
            return "引数が不足しています: grep <project> <pattern> [filename]"
        project = parts[1]
        pattern = parts[2]
        regex = False
        fname = ""
        exclude = ""
        max_hits = 100
        i = 3
        while i < len(parts):
            if parts[i] in ("-r", "--regex"):
                regex = True
                i += 1
            elif parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif parts[i] in ("-e", "--exclude") and i + 1 < len(parts):
                exclude = parts[i + 1]
                i += 2
            elif parts[i] in ("-n", "--max-hits") and i + 1 < len(parts):
                try:
                    max_hits = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif not parts[i].startswith("-"):
                fname = parts[i]
                i += 1
            else:
                i += 1
        return search_code(project, pattern, regex=regex, filename=fname, exclude=exclude, max_hits=max_hits)

    if sub == "get":
        if len(parts) < 3:
            return "引数が不足しています: get <project> <filename> [start_line] [end_line]"
        s_line = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        e_line = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        return get_file(parts[1], parts[2], start_line=s_line, end_line=e_line)

    if sub == "func":
        if len(parts) < 4:
            return "引数が不足しています: func <project> <filename> <func_name>"
        return get_function(parts[1], parts[2], parts[3])

    if sub == "patch":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 4:
            return "引数が不足しています: patch <project> <filename> <target> <replacement> [-a] [--force] [--dry-run] [--deploy]"
        return patch_code(
            non_flags[0], non_flags[1], non_flags[2], non_flags[3],
            replace_all=("-a" in parts or "--all" in parts),
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "patch-func":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 5:
            return "引数が不足しています: patch-func <project> <filename> <func_name> <target> <replacement>"
        return patch_function(
            non_flags[0], non_flags[1], non_flags[2], target=non_flags[3], replacement=non_flags[4],
            replace_all=("-a" in parts or "--all" in parts),
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "replace-func":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 4:
            return "引数が不足しています: replace-func <project> <filename> <func_name> <code_or_file>"
        code_str = non_flags[3]
        if Path(code_str).exists():
            with open(code_str, "r", encoding="utf-8") as f:
                code_str = f.read()
        return replace_function(
            non_flags[0], non_flags[1], non_flags[2], code_str,
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "add-func":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 3:
            return "引数が不足しています: add-func <project> <filename> <code>"
        code_str = non_flags[2]
        if Path(code_str).exists():
            with open(code_str, "r", encoding="utf-8") as f:
                code_str = f.read()
        return add_function(
            non_flags[0], non_flags[1], code_str,
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "del-func":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 3:
            return "引数が不足しています: del-func <project> <filename> <func_name>"
        return delete_function(
            non_flags[0], non_flags[1], non_flags[2],
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "batch":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 2:
            return "引数が不足しています: batch <project> <ops_json_or_file>"
        ops_str = non_flags[1]
        if Path(ops_str).exists():
            with open(ops_str, "r", encoding="utf-8") as f:
                ops_str = f.read()
        return batch_patch(
            non_flags[0], ops_str,
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "replace":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 3:
            return "引数が不足しています: replace <project> <filename> <code_or_file>"
        code_str = non_flags[2]
        if Path(code_str).exists():
            with open(code_str, "r", encoding="utf-8") as f:
                code_str = f.read()
        return replace_file(
            non_flags[0], non_flags[1], code_str,
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts)
        )

    if sub == "add":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 3:
            return "引数が不足しています: add <project> <filename> <type> [source]"
        src_str = non_flags[3] if len(non_flags) >= 4 else ""
        return add_file(non_flags[0], non_flags[1], non_flags[2], source=src_str, force=("--force" in parts))

    if sub == "delete":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 2:
            return "引数が不足しています: delete <project> <filename>"
        return delete_file(non_flags[0], non_flags[1])

    if sub == "add-channel":
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 2:
            return "引数が不足しています: add-channel <project> <channel_id_or_url> [channel_name]"
        ch_name = non_flags[2] if len(non_flags) >= 3 else ""
        return add_channel(non_flags[0], non_flags[1], channel_name=ch_name)

    if sub == "backups":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: backups <project> [limit]"
        limit = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 10
        return list_backups(parts[1], limit=limit)

    if sub == "diff":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: diff <project> [backup_file] [-f <file>]"
        project = parts[1]
        backup_file = ""
        fname = ""
        i = 2
        while i < len(parts):
            if parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif not parts[i].startswith("-"):
                if not backup_file:
                    backup_file = parts[i]
                else:
                    fname = parts[i]
                i += 1
            else:
                i += 1
        return diff_backup(project, backup_file=backup_file, filename=fname)

    if sub == "restore":
        if len(parts) < 3:
            return "引数が不足しています: restore <project> <backup_file> [-f <file>]"
        project = parts[1]
        backup_file = parts[2]
        fname = ""
        i = 3
        while i < len(parts):
            if parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif not parts[i].startswith("-"):
                fname = parts[i]
                i += 1
            else:
                i += 1
        return restore_backup(project, backup_file=backup_file, filename=fname)

    if sub == "versions":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: versions <project> [limit]"
        limit = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
        return list_versions(parts[1], limit=limit)

    if sub in ("diff-prod", "diff-version"):
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: diff-prod <project> [-v <version>] [-f <file>]"
        project = parts[1]
        v_num = None
        fname = ""
        i = 2
        while i < len(parts):
            if parts[i] in ("-v", "--version") and i + 1 < len(parts):
                try:
                    v_num = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            else:
                i += 1
        return diff_version(project, version_number=v_num, filename=fname)

    if sub == "restore-version":
        if len(parts) < 3:
            return "引数が不足しています: restore-version <project> <version_number> [-f <file>] [--deploy]"
        project = parts[1]
        try:
            v_num = int(parts[2])
        except ValueError:
            return f"無効なバージョン番号です: {parts[2]}"
        fname = ""
        deploy_flag = False
        i = 3
        while i < len(parts):
            if parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif parts[i] in ("--deploy", "-d"):
                deploy_flag = True
                i += 1
            else:
                i += 1
        return restore_version(project, v_num, filename=fname, deploy=deploy_flag)

    if sub == "run":
        if len(parts) < 3:
            return "引数が不足しています: run <project> <func_name> [args_json] [--keep-runner] [--fast]"
        project = parts[1]
        func_name = parts[2]
        args_json = ""
        keep_runner = False
        fast_flag = False
        i = 3
        while i < len(parts):
            if parts[i] == "--keep-runner":
                keep_runner = True
                i += 1
            elif parts[i] == "--fast":
                fast_flag = True
                i += 1
            elif not args_json:
                args_json = parts[i]
                i += 1
            else:
                i += 1
        return run_function(project, func_name, args=args_json, keep_runner=keep_runner, fast=fast_flag)

    if sub == "clean-runner":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: clean-runner <project>"
        return clean_runner(parts[1])

    if sub == "pull":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: pull <project> [local_dir] [--clean]"
        project = parts[1]
        ldir = "."
        clean_f = "--clean" in parts
        for p in parts[2:]:
            if p != "--clean" and not p.startswith("-"):
                ldir = p
                break
        return pull_project(project, local_dir=ldir, clean=clean_f)

    if sub == "push":
        project = ""
        ldir = "."
        dry_run = "--dry-run" in parts
        force = "--force" in parts
        del_missing = "--delete-missing" in parts
        deploy_f = "--deploy" in parts
        desc = "Pushed via gas CLI"
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) >= 1:
            project = non_flags[0]
        if len(non_flags) >= 2:
            ldir = non_flags[1]
        return push_project(project=project, local_dir=ldir, force=force, dry_run=dry_run, delete_missing=del_missing, deploy=deploy_f, desc=desc)

    if sub in ("status", "sync-status"):
        project = ""
        ldir = "."
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) >= 1:
            project = non_flags[0]
        if len(non_flags) >= 2:
            ldir = non_flags[1]
        return sync_status(project=project, local_dir=ldir)

    if sub == "deploy":
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: deploy <project> [description]"
        desc = parts[2] if len(parts) > 2 else "Auto deployed via GasClient"
        return deploy(parts[1], description=desc)

    if sub in ("deployments", "deps"):
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: deployments <project>"
        return list_deployments(parts[1])

    if sub == "webapp":
        if len(parts) < 2:
            return "URLまたはプロジェクト名を指定してください: webapp <url_or_project> [params] [--dev]"
        url_or_proj = parts[1]
        params = ""
        dev_flag = False
        i = 2
        while i < len(parts):
            if parts[i] == "--dev":
                dev_flag = True
                i += 1
            elif not params:
                params = parts[i]
                i += 1
            else:
                i += 1
        return call_webapp(url_or_proj, params=params, dev=dev_flag)

    return f"不明なコマンドです: '{sub}'。'help' で使い方を確認してください。"

if __name__ == "__main__":
    mcp.run()
