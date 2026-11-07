#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gas_mcp_server.py - ガスマネージャー (gas-manager) MCP サーバー
Google Apps Script (GAS) を AI から直接読み書き・ピンポイント差分置換するための MCP ツール群
"""

import sys
import os
import re
import shlex
import json
from pathlib import Path

# 自モジュールのパスを通す
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from mcp.server.fastmcp import FastMCP
try:
    import gas_local_extras
except ImportError:
    gas_local_extras = None

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

@mcp.tool()
@safe_tool
def reload_tools() -> str:
    """常駐MCPサーバーのツール定義および GasClient ロジックをメモリ上でホットリロードします。
    サーバープロセスを再起動することなく、最新の Python コードを即座に反映します。
    """
    global _client
    import importlib
    import gas_client

    importlib.reload(gas_client)
    if "gas_local_extras" in sys.modules:
        import gas_local_extras
        importlib.reload(gas_local_extras)

    if _client is not None:
        old_client = _client
        new_client = gas_client.GasClient(
            clasprc_path=str(old_client.clasprc_path),
            backup_dir=str(old_client.backup_dir)
        )
        new_client.cache_file = old_client.cache_file
        new_client._cache_data = getattr(old_client, "_cache_data", {})
        new_client._content_cache = getattr(old_client, "_content_cache", {})
        new_client._synced_sids = getattr(old_client, "_synced_sids", set())
        new_client._dock_cache = getattr(old_client, "_dock_cache", {})
        new_client._diag_cache = getattr(old_client, "_diag_cache", {})
        new_client._xray_cache = getattr(old_client, "_xray_cache", {})
        new_client._access_token = getattr(old_client, "_access_token", None)
        new_client._token_expiry = getattr(old_client, "_token_expiry", 0)
        _client = new_client

    return "[SUCCESS] gas-manager ホットリロード完了: gas_client を再読み込みし、最新ロジックを反映しました。"

def get_client() -> GasClient:
    global _client
    if _client is None:
        _client = GasClient()
    return _client

@mcp.tool()
@safe_tool
def list_projects(limit: int = 20, refresh: bool = False) -> str:
    """Google Drive 上の GAS プロジェクト一覧を取得します。

    Args:
        limit: 取得する最大件数 (デフォルト: 20)
        refresh: キャッシュを無視して最新のプロジェクト一覧を再取得するか (デフォルト: False)
    """
    client = get_client()
    projects = client.list_projects(limit=limit, refresh=refresh)
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
def patch_code(project: str, filename: str, target: str = "", replacement: str = "", replace_all: bool = False, force: bool = False, dry_run: bool = False, patches: str = "", deploy: bool = False, verify: bool = False, dev: bool = False, fast: bool = False) -> str:
    """ファイル内の特定コード文字列を置換し、Google クラウドへ反映します。
    置換前に自動バックアップと Node.js vm による構文検査を実施します。
    patches 引数に JSON 文字列（例: '[{"target":"a","replacement":"b"}]'）を指定することで複数箇所の一括置換も可能です。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。
    verify=True を指定すると、反映直後にフロントエンド実機シミュレーション（verify_frontend）まで一括実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        target: 置換前の既存コード文字列（一致する文字列）
        replacement: 置換後の新しいコード文字列
        replace_all: 複数箇所の一括置換を許可するか (デフォルト: False)
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        patches: 複数ペアの一括置換を行う場合の JSON 文字列 (デフォルト: "")
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
        verify: 反映完了後にフロントエンド実機シミュレーションを一括実行するか (デフォルト: False)
    """
    client = get_client()
    kwargs = dict(
        target=target, replacement=replacement, replace_all=replace_all,
        force=force, dry_run=dry_run, patches=patches if patches else None, deploy=deploy
    )
    if fast:
        kwargs["fast"] = True
    if verify:
        kwargs["verify"] = True
    if dev:
        kwargs["dev"] = True
    res = client.patch_code(project, filename, **kwargs)
    diff_out = f"\n--- 差分 (Diff) ---\n{res['diff']}" if res.get("diff") else ""
    dep_msg = ""
    if res.get("deployment"):
        dep = res["deployment"]
        dep_msg = f"\n本番デプロイ完了: Version {dep.get('versionNumber', 'N/A')} (URL: {dep.get('webAppUrl', 'N/A')})"
    elif res.get("dev_mode"):
        dep_msg = f"\nHEAD即時反映 (dev): {res.get('dev_url', 'N/A')} (バージョン採番スキップ・高速完了)"
    verify_msg = ""
    if res.get("verify"):
        v = res["verify"]
        if v.get("status") == "success":
            verify_msg = f"\nフロント検証: [SUCCESS] 検証成功 (IndexedDB: {v.get('indexeddb_count', 0)}件)"
        else:
            verify_msg = f"\nフロント検証: [WARN] {v.get('message', '検証警告あり')}"

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
        f"{verify_msg}"
    )

@mcp.tool()
@safe_tool
def replace_file(project: str, filename: str, new_source: str, force: bool = False, dry_run: bool = False, deploy: bool = False, fast: bool = False) -> str:
    """指定ファイルの中身を丸ごと置き換え、Google クラウドへ反映します。
    反映前に自動バックアップと構文検査を実施します。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: ファイル名
        new_source: 新しいコード全文
        force: 構文エラーを無視して強制反映するか (デフォルト: False)
        dry_run: クラウドへの反映を行わず差分のみ確認するか (デフォルト: False)
        deploy: 反映完了後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    kwargs = dict(force=force, dry_run=dry_run, deploy=deploy)
    if fast:
        kwargs["fast"] = True
    res = client.replace_file(project, filename, new_source, **kwargs)
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
def deploy(project: str, description: str = "Auto deployed via MCP", deployment_id: str | None = None, refresh: bool = False) -> str:
    """新バージョンを作成し、既存の Web アプリデプロイを更新（再デプロイ）します。

    Args:
        project: プロジェクト名またはスクリプトID
        description: バージョンの説明文
        deployment_id: 更新対象の特定デプロイID（省略時は最新デプロイを自動検出）
        refresh: デプロイIDキャッシュを破棄して再取得するか (デフォルト: False)
    """
    client = get_client()
    res = client.deploy(project, description=description, deployment_id=deployment_id, refresh=refresh)
    return (
        f"[SUCCESS] 本番デプロイ完了 (Version {res['versionNumber']})\n"
        f"Deployment ID: {res.get('deploymentId', 'N/A')}\n"
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

# ローカル拡張（Qクイック専用等）が存在する場合のみ add_channel ツールを登録
if gas_local_extras and hasattr(gas_local_extras, "register_mcp"):
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
        res = gas_local_extras.add_qquick_channel(client, project, channel, channel_name=channel_name)
        if res.get("status") == "already_exists":
            return f"[INFO] チャンネル {res['channelId']} は既に登録されています。\nURL: {res.get('webAppUrl', '')}"
        name_str = f"\nチャンネル名: {res['channelName']}" if res.get("channelName") else ""
        total_str = f"\n現在の登録総数: {res['totalChannels']}件" if res.get("totalChannels") else ""
        return f"[SUCCESS] チャンネル追加完了\nチャンネルID: {res['channelId']}{name_str}{total_str}\nURL: {res.get('webAppUrl', '')}"

@mcp.tool()
@safe_tool
def patch_function(project: str, filename: str, func_name: str, target: str = "", replacement: str = "", replace_all: bool = False, force: bool = False, dry_run: bool = False, patches: str = "", deploy: bool = False, fast: bool = False) -> str:
    """指定ファイル内の特定関数スコープ内に限定してコード置換を行います（他関数にある同一コードの誤爆を物理的に防止）。
    置換前の自動バックアップ、構文検査、diff 出力を完備しています。
    patches 引数に JSON 文字列（例: '[{"target":"a","replacement":"b"}]'）を指定することで複数箇所の一括置換も可能です。
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。

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
    kwargs = dict(target=target, replacement=replacement, replace_all=replace_all, force=force, dry_run=dry_run, patches=patches if patches else None, deploy=deploy)
    if fast:
        kwargs["fast"] = True
    res = client.patch_function(project, filename, func_name, **kwargs)
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
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。

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
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。

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
def batch_patch(project: str, operations: str, force: bool = False, dry_run: bool = False, deploy: bool = False, fast: bool = False) -> str:
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
    kwargs = dict(force=force, dry_run=dry_run, deploy=deploy)
    if fast:
        kwargs["fast"] = True
    res = client.batch_patch(project, ops_data, **kwargs)
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
    deploy=True を指定すると、反映直後に本番Webアプリの更新デプロイまで同時に実行します。

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
        return f"Version {target_v} と現在の最新HEADコードに差分はありません（一致）。"
    return f"=== Version {target_v} と最新HEADコードの差分 ({len(changed)}ファイル変更: {', '.join(changed)}) ===\n{res['diff']}"

@mcp.tool()
@safe_tool
def restore_version(project: str, version_number: int, filename: str = "", deploy: bool = False) -> str:
    """クラウド上の不変バージョン（スナップショット）からプロジェクト全体または特定ファイルを復元します。
    復元直前の状態はローカル安全スナップショットとして自動退避されます。
    deploy=True を指定すると、復元直後に本番Webアプリの更新デプロイまで同時に実行します。

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
def benchmark_function(project: str, func_name: str, args: str = "", target_ms: int = 1000, iterations: int = 1, expected: str = "") -> str:
    """任意の GAS サーバー関数を実行計測し、ミリ秒速度・期待値照合・ループ内API警告を判定するベンチマーク関所を実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        func_name: 計測対象の関数名
        args: 引数の JSON 文字列 (例: '[10, "test"]')
        target_ms: 目標所要ミリ秒 (既定: 1000)
        iterations: 試行回数 (既定: 1)
        expected: 期待値 (文字列またはJSON)
    """
    client = get_client()
    parsed_args = []
    if args:
        try:
            val = json.loads(args)
            parsed_args = val if isinstance(val, list) else [val]
        except Exception:
            parsed_args = [args]
    exp_val = None
    if expected:
        try:
            exp_val = json.loads(expected)
        except Exception:
            exp_val = expected
    res = client.benchmark_function(project, func_name, args=parsed_args, target_ms=target_ms, iterations=iterations, expected=exp_val)
    lines = [
        f"=== GAS ベンチマーク関所: [{project}] -> {func_name} ===",
        f"判定: [{res.get('verdict', 'FAILED')}] (スコア: {res.get('score', 0)}/100点)",
        f"実行速度: 平均 {res.get('avg_ms', 0)}ms (最小 {res.get('min_ms', 0)}ms / 最大 {res.get('max_ms', 0)}ms) | 目標: {res.get('target_ms', target_ms)}ms 以内 ({res.get('iterations', 0)}回計測)"
    ]
    if res.get("expected_checked"):
        lines.append(f"期待値照合: {'一致 (OK)' if res.get('expected_match') else '不一致 (NG)'}")
    if "result" in res and res.get("status") == "success":
        lines.append(f"戻り値: {json.dumps(res['result'], ensure_ascii=False)}")
    if res.get("logs"):
        lines.append("--- 実行ログ ---")
        for lg in res["logs"]:
            lines.append(f"  {lg}")
    if res.get("prescriptions"):
        lines.append("--- カイゼン処方箋 (Next Actions) ---")
        for pr in res["prescriptions"]:
            lines.append(f"  * {pr}")
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
def push_project(project: str = "", local_dir: str = ".", force: bool = False, dry_run: bool = False, delete_missing: bool = False, deploy: bool = False, desc: str = "Pushed via MCP", deployment_id: str = "") -> str:
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
    dep_id_arg = deployment_id.strip() if deployment_id else None
    res = client.push(project, local_dir=local_dir, force=force, dry_run=dry_run, delete_missing=delete_missing, deploy=deploy, deploy_desc=desc, deployment_id=dep_id_arg)
    if res.get("status") == "no_changes":
        return "差分はありません（ローカルとクラウドは一致しています）。"

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

    # 4d. 未使用の関数引数
    unused_params = diag.get("unused_params", [])
    lines.append(f"[未使用の関数引数 (入力値無視の疑い)] ({len(unused_params)}件):")
    if unused_params:
        for up in unused_params:
            lines.append(f"  - {up['file']}:{up['line']} 関数 '{up['function']}' の引数 '{up['param']}': {up.get('reason', '')}")
    else:
        lines.append("  なし (未参照の引数は検出されませんでした)")
    lines.append("")

    # 4e. フロントエンド・キャッシュ・DOM警告
    fe_warns = diag.get("frontend_warnings", [])
    lines.append(f"[フロントエンド・キャッシュ警告] ({len(fe_warns)}件):")
    if fe_warns:
        for fw in fe_warns:
            lines.append(f"  - {fw['file']} 行 {fw['line']} [{fw['kind']}]: {fw['reason']}")
    else:
        lines.append("  なし (IndexedDBゾンビや同期描画ブロック等は検出されませんでした)")
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
def verify_frontend(project: str, filename: str = "Index", test_js: str = "") -> str:
    """指定した HTML ファイル内の JavaScript ロジックを Node.js vm 模擬環境（インメモリ IndexedDB / DOM / RPC プロキシ）上で実機実行・検証します。
    IndexedDB の保存・削除や、同期マージ処理が正しく動作しているか（ゾンビ化しないか）をテストできます。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象の HTML ファイル名 (既定: "Index")
        test_js: 検証用に追加実行する非同期 JS 式/ブロック (例: "await saveToDB([{id:'1'}]); return (await loadFromDB()).length;")
    """
    client = get_client()
    res = client.verify_frontend(project, filename=filename, test_js=test_js)

    status_str = "[SUCCESS] 検証成功" if res.get("success") else "[FAILED] 検証失敗"
    lines = [
        f"=== フロントエンド実機シミュレーション: [{project}] ({res.get('file', filename)}) ===",
        f"判定: {status_str}"
    ]
    if res.get("error"):
        lines.append(f"エラー: {res['error']}")
    if res.get("test_result") is not None:
        lines.append(f"test_result: {res['test_result']}")
    lines.append(f"IndexedDB レコード数: {res.get('db_records_count', 0)}件")
    if res.get("rpc_calls"):
        lines.append(f"google.script.run 呼出: {len(res['rpc_calls'])}件")
        for c in res["rpc_calls"][:5]:
            chain_str = ".".join([str(p[0]) if isinstance(p, list) else str(p) for p in c.get("chain", [])])
            lines.append(f"  - {chain_str}({c.get('args', [])})")
    if res.get("alerts"):
        lines.append(f"alert 出力: {len(res['alerts'])}件: {res['alerts']}")
    if res.get("confirms"):
        lines.append(f"confirm 出力: {len(res['confirms'])}件: {res['confirms']}")

    return "\n".join(lines)

@mcp.tool()
@safe_tool
def inspect_ui(
    project: str = "",
    filename: str = "Index",
    url: str = "",
    theme: str = "",
    all_themes: bool = False,
    actions_json: str = "",
    screenshot: bool = True,
    check_contrast: bool = True,
    check_axe: bool = True,
    baseline: str = "",
    device: str = "desktop",
    width: int = 1280,
    height: int = 800
) -> str:
    """GAS Webアプリの実機画面をヘッドレスブラウザでレンダリングし、
    スクリーンショット撮影（目視裏取り）、WCAG コントラスト比、axe-core 総合品質、および画像差分（Visual Regression）を自動監査します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象の HTML ファイル名 (既定: "Index")
        url: WebアプリのURL (省略時はGASソースをモック展開してローカル実機レンダリング)
        theme: テーマ指定 ("white", "dark", "green" 等)
        all_themes: True の場合、代表3テーマ (white / dark / green) を一括撮影・監査
        actions_json: 操作リストのJSON文字列 (例: '[{"click":"#btnSettings"}]')
        screenshot: スクリーンショットを撮影するか (既定: True)
        check_contrast: WCAG コントラスト比の自動監査を行うか (既定: True)
        check_axe: Google/MS標準 axe-core によるプロ級アクセシビリティ自動監査を行うか (既定: True)
        baseline: 比較元の基準スクリーンショット画像パス (指定時は画像差分・変化率を自動判定)
        width: ビューポート幅 (既定: 1280)
        height: ビューポート高さ (既定: 800)
    """
    client = get_client()
    actions = None
    if actions_json and actions_json.strip():
        import ast
        try:
            actions = json.loads(actions_json)
        except Exception:
            try:
                actions = ast.literal_eval(actions_json)
            except Exception:
                actions = [{"eval": actions_json.strip()}]
        if isinstance(actions, dict):
            actions = [actions]

    res = client.inspect_ui(
        script_id=project or None,
        filename=filename,
        url=url or None,
        theme=theme or None,
        all_themes=all_themes,
        actions=actions,
        screenshot=screenshot,
        check_contrast=check_contrast,
        check_axe=check_axe,
        baseline_screenshot=baseline or None,
        width=width,
        height=height
    )

    lines = [
        f"=== GAS Webアプリ実機画面監査 (inspect_ui): [{project or url}] ===",
        f"総合判定: {'[PASS] 合格' if res.get('contrast_passed') else '[WARNING] コントラスト不適合あり'}",
        f"検査対象要素数: {res.get('total_elements_checked', 0)}件",
        f"テストテーマ: {', '.join(res.get('themes_tested', []))}"
    ]

    dangers = res.get("dangers", [])
    warnings = res.get("warnings", [])

    if dangers:
        lines.append(f"\n【重大な視認性不具合 (不可視・コントラスト比 2.5:1 未満)】: {len(dangers)}件")
        for d in dangers[:5]:
            lines.append(f"  - [{d.get('theme', 'default')}] {d.get('selector')}: \"{d.get('text')}\" (比率 {d.get('ratio')}:1, 文字 {d.get('fg')} / 背景 {d.get('bg')})")

    if warnings:
        lines.append(f"\n【軽微なコントラスト警告 (4.5:1 未満)】: {len(warnings)}件")
        for w in warnings[:5]:
            lines.append(f"  - [{w.get('theme', 'default')}] {w.get('selector')}: \"{w.get('text')}\" (比率 {w.get('ratio')}:1, 文字 {w.get('fg')} / 背景 {w.get('bg')})")

    axe_violations = res.get("axe_violations", [])
    if axe_violations:
        lines.append(f"\n【axe-core アクセシビリティ・UI品質警告 ({len(axe_violations)}件)】:")
        for av in axe_violations[:5]:
            lines.append(f"  - [{av.get('theme')}] {av.get('id')} ({av.get('impact')}): {av.get('help')} ({av.get('nodes_count')}要素)")

    v_diff = res.get("visual_diff")
    if v_diff:
        if v_diff.get("has_diff"):
            lines.append(f"\n【画像差分 (Visual Diff 検知)】: 差分率 {v_diff.get('diff_ratio_pct')}% ({v_diff.get('diff_pixels'):,} px)")
            if v_diff.get("diff_image"):
                lines.append(f"  - 差分ヒートマップ: {v_diff.get('diff_image')}")
        else:
            lines.append("\n【画像差分 (Visual Diff)】: 差分なし (一致)")

    if res.get("screenshots"):
        lines.append(f"\n【実機スクリーンショット物証 ({len(res['screenshots'])}枚)】:")
        for s in res["screenshots"]:
            lines.append(f"  - {s}")

    return "\n".join(lines)

@mcp.tool()
@safe_tool
def clean_dead(project: str, dry_run: bool = True, names: str = "", force: bool = False, deploy: bool = False) -> str:
    """レントゲン解析で検出された孤立死にコードを名指しで安全に削除します。
    ※ dry_run=True が既定です。先に dry_run で確認し、消す関数名を names に渡して dry_run=False で実行してください。

    Args:
        project: プロジェクト名またはスクリプトID
        dry_run: プレビューのみ表示するか（デフォルト: True）
        names: 削除する関数名（カンマ区切り文字列またはリスト）
        force: 保留 (suspect) の関数も強制削除するか（デフォルト: False）
        deploy: 削除後に新バージョンをデプロイするか（デフォルト: False）
    """
    client = get_client()
    names_list = [n.strip() for n in names.split(",") if n.strip()] if isinstance(names, str) and names else (names if isinstance(names, list) else None)
    res = client.clean_dead(project, dry_run=dry_run, names=names_list, force=force, deploy=deploy)
    return res.get("markdown_report") or res.get("message", "")


@mcp.tool()
@safe_tool
def clone_web(url: str, project: str = "", deploy: bool = False, access: str = "MYSELF") -> str:
    """指定した外部 Web ページを解析し、自立型 GAS Web アプリとして自動作成します。写してよいのは自分が作ったページ・権利のあるページだけです。
    デプロイ直後に自動でレントゲン解析（xray）を実行し、クローン後のアプリの健全性を報告します。

    Args:
        url: クローン元の Web ページ URL
        project: 作成する GAS プロジェクト名（省略時はページの title を使用）
        deploy: 本番デプロイを行うかどうか（デフォルト: False）
        access: Webアプリ公開範囲（デフォルト: MYSELF）
    """
    client = get_client()
    res = client.clone_web(url, project_name=project or None, deploy=deploy, access=access)
    return res.get("markdown_report") or res.get("message", "")


@mcp.tool()
@safe_tool
def xray(project: str, filename: str = "Index") -> str:
    """指定した GAS プロジェクトのフロントエンド（HTML）とバックエンド（SERVER_JS）を深層リバースエンジニアリング（レントゲン解析）します。
    UI要素から発火するイベント、フロントJS関数、裏で叩かれるGAS API（google.script.run）のE2Eコールパスをマッピングし、
    未定義RPC（本番クラッシュ確定）、孤立した死にコード、未実装UI、IndexedDB/ストレージキーを1秒で暴きます。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象のHTMLファイル名（拡張子なし、デフォルト: Index）
    """
    client = get_client()
    res = client.xray(project, filename=filename)
    return res["markdown_report"]


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
def trace_rpc(
    target: str,
    filename: str = "Index",
    duration: float = 5.0,
    actions: str = "",
    mock_file: str = ""
) -> str:
    """REA observe_web_execution 思想:
    GAS Webアプリの実行時 RPC 通信 (google.script.run) を自動スパイ＆キャプチャ。
    引数、戻り値、所要時間を全件記録し、ローカルオフラインテスト用 mock fixtures を自動生成します。

    Args:
        target: プロジェクト名、スクリプトID、またはWebアプリURL
        filename: 対象HTMLファイル名 (デフォルト: Index)
        duration: 観測待機秒数 (デフォルト: 5.0秒)
        actions: 実行操作JSON (例: '[{"click": "#btn"}]')
        mock_file: モック保存ファイル名 (省略時は .mocks/{id}_mock.json)
    """
    client = get_client()
    acts = None
    if actions:
        import json
        try:
            acts = json.loads(actions)
        except Exception:
            pass
    url = target if target.startswith("http") else None
    pid = None if url else target
    res = client.trace_rpc(pid, filename=filename, url=url, duration_sec=duration, actions=acts, mock_file=mock_file or None)
    if not res.get("success"):
        return f"[ERROR] {res.get('error')}"
    lines = [
        f"=== 🕵️ GAS 実行時RPC通信スパイ (trace_rpc): [{res['target']}] ===",
        f"キャプチャ総数: {res['total_captured']}件 | ユニークRPC: {len(res['unique_rpcs'])}種類 ({', '.join(res['unique_rpcs']) if res['unique_rpcs'] else 'なし'})"
    ]
    if res.get("mock_file"):
        lines.append(f"モックファイル保存: {res['mock_file']} ({res.get('mock_count', 0)}件保存)")
    if res.get("traces"):
        lines.append("\n--- 📡 RPC 通信履歴 ---")
        for t in res["traces"]:
            status = f"{t.get('duration_ms', 0)}ms" if not t.get("error") else f"ERR: {t.get('error')}"
            src = f"[{t.get('source', '')}]"
            lines.append(f"  {src:<8} {t.get('rpc')}({t.get('args', [])}) -> {status}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def diff_behavior(
    project: str,
    target: str = "",
    version: int = None,
    filename: str = "Index"
) -> str:
    """REA find_changed_behavior 思想:
    GASプロジェクトのコード変更による「振る舞いの変化・破壊的変更」を自動監査。
    引数不足や削除関数のフロント呼び出しをデプロイ前に事前検知・ブロックします。

    Args:
        project: プロジェクト名またはスクリプトID
        target: 比較対象の別プロジェクトID (省略時は直近バックアップまたは指定バージョン)
        version: 比較対象の過去バージョン番号
        filename: 対象HTMLファイル名 (デフォルト: Index)
    """
    client = get_client()
    res = client.diff_behavior(project, base_version=version, target_script_id=target or None, filename=filename)
    if not res.get("success"):
        return f"[ERROR] {res.get('error')}"
    status_icon = "🟢 [PASS] 安全" if res["status"] == "PASS" else ("🔴 [BREAKING] 破壊的変更あり" if res["status"] == "BREAKING" else "🟡 [WARNING] 警告あり")
    lines = [
        f"=== 🔍 振る舞い差分・破壊的変更監査 (diff_behavior): [{res['script_id']}] ===",
        f"判定: {status_icon}",
        f"破壊的変更: {res['breaking_count']}件 | 警告: {res['warning_count']}件 | 安全な変更: {res['safe_count']}件"
    ]
    if res.get("breaking_changes"):
        lines.append("\n🚨 【重大な破壊的変更 (デプロイ事故の危険)】:")
        for b in res["breaking_changes"]:
            lines.append(f"  - {b['message']}")
    if res.get("safe_changes"):
        lines.append("\n✨ 【安全な変更】:")
        for s in res["safe_changes"]:
            lines.append(f"  - {s['message']}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def ledger(
    project: str,
    filename: str = "Index"
) -> str:
    """REA build_reconstruction_obligation_ledger 思想:
    GAS Webアプリの「モダン再構築・健全性義務台帳」を自動生成。
    IndexedDBキャッシュ、ダークモード、レスポンシブ、オプティミスティックUIなど必須7大要件の充足率を自動採点します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象HTMLファイル名 (デフォルト: Index)
    """
    client = get_client()
    res = client.build_ledger(project, filename=filename)
    if not res.get("success"):
        return f"[ERROR] {res.get('error')}"
    grade_icons = {"GOLD": "🥇 [GOLD]", "SILVER": "🥈 [SILVER]", "BRONZE": "🥉 [BRONZE]", "NEEDS_MODERNIZATION": "⚠️ [要改善]"}
    lines = [
        f"=== 📋 モダンGAS再構築・健全性義務台帳 (ledger): [{res['script_id']}] ===",
        f"総合スコア: {res['score']}% {grade_icons.get(res['grade'], '')}",
        f"達成要件: {res['passed_requirements']}/{res['total_requirements']} 項目クリア\n"
    ]
    for c in res["checklist"]:
        st = "✅" if c["passed"] else "❌"
        lines.append(f"  {st} {c['title']}")
        lines.append(f"     判定理由: {c['detail']}")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def gas_dock(
    project: str,
    filename: str = "Index"
) -> str:
    """GASドック（diagnose + xray 統合診断、健康点算出、直す手処方箋）。
    プロジェクトの健康診断・レントゲン解析・RPC契約検査を一括実行し、100点満点スコアと処方箋を返します。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象HTMLファイル名 (デフォルト: Index)
    """
    client = get_client()
    res = client.gas_dock(project, filename=filename)
    return res.get("markdown_report", "")

@mcp.tool()
@safe_tool
def gas_recipe(
    project: str = "",
    filename: str = "",
    func_name: str = "",
    recipe_id: str = "",
    apply: bool = False,
    deploy: bool = False,
    ask: str = "",
    list_only: bool = False
) -> str:
    """GAS高速化レシピ棚（全12レシピ: appendRow一括化・getValues2次元配列化・UrlFetch並列化・CacheService包装等）の検出・プレビュー・自動変換を行います。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象ファイル名 (省略時は全SERVER_JS)
        func_name: 対象関数名 (省略時はファイル内全走査)
        recipe_id: レシピID ("R01"〜"R12" またはレシピ名)
        apply: 実際にプロジェクトへコード変換を反映するか (デフォルト: False でプレビュー)
        deploy: 反映後に本番Webアプリを自動デプロイするか (デフォルト: False)
        ask: 「頼みの文」による自然言語判定クエリ (例: "appendRowをまとめたい")
        list_only: 全12レシピの一覧のみ表示するか (デフォルト: False)
    """
    client = get_client()
    res = client.gas_recipe(
        script_id=project,
        filename=filename,
        func_name=func_name,
        recipe_id=recipe_id,
        apply=apply,
        deploy=deploy,
        ask=ask,
        list_only=list_only
    )
    return res.get("markdown_report", "")

@mcp.tool()
@safe_tool
def design_skin(
    project: str,
    filename: str = "Index",
    preset: str = "linear",
    deploy: bool = False
) -> str:
    """HTMLファイルにデザインプリセット（CSS変数・タイポグラフィ・グリッド・シャドウ）を反映・着せ替えします。

    Args:
        project: プロジェクト名またはスクリプトID
        filename: 対象HTMLファイル名 (デフォルト: Index)
        preset: デザインプリセット ("linear" / "glass" / "notion" / "emerald")
        deploy: 反映後に本番Webアプリを自動デプロイするか (デフォルト: False)
    """
    client = get_client()
    res = client.design_skin(project, filename=filename, preset=preset, deploy=deploy)
    if not res.get("success"):
        return f"[ERROR] デザイン着せ替え失敗: {res.get('error')}"
    
    dep_str = " (本番Webアプリへ自動デプロイ完了)" if res.get("deployed") else ""
    return (
        f"=== 🎨 GAS デザイン着せ替え (design-skin): [{res.get('project')}] ===\n"
        f"プリセット: {res.get('preset_name')} ({res.get('preset')})\n"
        f"特徴: {res.get('desc')}\n"
        f"反映ファイル: {res.get('filename')}.html (置換箇所: {res.get('patches_applied')}箇所){dep_str}\n"
        f"状態: 正常反映 (視覚レイヤーの反映完了)"
    )

@mcp.tool()
@safe_tool
def gas_scaffold(
    project: str = "",
    scaffold_id: str = "",
    filename: str = "Index",
    server_file: str = "Code",
    apply: bool = False,
    deploy: bool = False,
    list_only: bool = False
) -> str:
    """上級GASアーキテクチャ骨格棚（S01〜S05: Promise化RPC・SWR即時描画・楽観UI・サーバー統一応答・一括注入）のプレビューおよび安全注入を行います。

    Args:
        project: プロジェクト名またはスクリプトID
        scaffold_id: 骨格棚ID ("S01"〜"S05" または部品名)
        filename: 対象HTMLファイル名 (デフォルト: Index)
        server_file: 対象サーバー側ファイル名 (デフォルト: Code)
        apply: 実際にプロジェクトへ注入するか (デフォルト: False でプレビュー)
        deploy: 反映後に本番Webアプリを自動デプロイするか (デフォルト: False)
        list_only: カタログ一覧のみ表示するか (デフォルト: False)
    """
    client = get_client()
    res = client.gas_scaffold(
        script_id=project,
        scaffold_id=scaffold_id,
        filename=filename,
        server_file=server_file,
        apply=apply,
        deploy=deploy,
        list_only=list_only
    )
    return res.get("markdown_report", "")

@mcp.tool()
@safe_tool
def gas_shelf(
    project: str = "",
    query: str = "",
    shelf_id: str = "",
    filename: str = "Index",
    func_name: str = "",
    apply: bool = False,
    deploy: bool = False,
    list_only: bool = False,
    check_only: bool = False
) -> str:
    """GAS 先撃ち総合棚ルーター（全25棚直結・頼み文からの自動判定・棚当て検査・自動ディスパッチ）を実行します。

    Args:
        project: プロジェクト名またはスクリプトID
        query: 日本語・自然言語の頼み文 (例: "シートに追記するのを速くして", "GASドックで診断して")
        shelf_id: 直接指定する棚ID ("R01"〜"R12", "S01"〜"S05", "K01"〜"K04", "D01"〜"D04")
        filename: 対象HTMLファイル名 (デフォルト: Index)
        func_name: 対象関数名 (レシピ適用時など)
        apply: 実際にプロジェクトへ変更を反映するか (デフォルト: False でプレビュー)
        deploy: 反映後に本番Webアプリを自動デプロイするか (デフォルト: False)
        list_only: 全25棚の一覧カタログのみ表示するか (デフォルト: False)
        check_only: 全25棚のゴールデン頼み文検査 (--check) を実行するか (デフォルト: False)
    """
    client = get_client()
    res = client.gas_shelf(
        script_id=project,
        query=query,
        shelf_id=shelf_id,
        filename=filename,
        func_name=func_name,
        apply=apply,
        deploy=deploy,
        list_only=list_only,
        check_only=check_only
    )
    return res.get("markdown_report", "")

@mcp.tool()
@safe_tool
def gas(command: str) -> str:
    """ガスマネージャー (GAS Manager) 統合コマンド窓口。
    CLI と同じコマンド形式（例: 'files MyProject', 'outline MyProject', 'patch-func MyProject main myFunc old new' 等）で
    コマンドで GAS 操作を実行します。

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
            "  inspect-ui <p_or_url> [f] [--all] - Webアプリ実機画面撮影＆コントラスト監査（screenshot）\n"
            "  dock <project> [filename]         - GASドック（総合診断・100点満点・処方箋）\n"
            "  recipe [p] [--id Rxx] [--ask 文]  - 高速化レシピ棚（全12レシピ検出・自動変換）\n"
            "  sync <project> [--force]          - デスクトップ常駐型ハイブリッド同期\n"
            "  reload                            - 常駐MCPサーバーのホットリロード\n"
            "  py-outline <file>                 - Pythonコード内関数一覧取得\n"
            "  py-func <file> <func>             - Pythonコード内関数定義抽出\n"
            "  py-patch <file> <func> <t> <r>    - Pythonコード内安全ピンポイント置換\n"
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

    if sub in ("clean-dead", "clean_dead", "cleandead"):
        if len(parts) < 2:
            return "プロジェクト名を指定してください: clean-dead <project> [--apply] [--names func1,func2] [--force] [--deploy]"
        p_name = parts[1]
        is_apply = "--apply" in parts
        is_dry = not is_apply
        do_dep = "--deploy" in parts
        do_force = "--force" in parts
        names_str = ""
        for i, pt in enumerate(parts):
            if pt in ("--names", "--name") and i + 1 < len(parts):
                names_str = parts[i + 1]
        return clean_dead(project=p_name, dry_run=is_dry, names=names_str, force=do_force, deploy=do_dep)

    if sub in ("clone-web", "clone_web", "clone"):
        if len(parts) < 2:
            return "クローン元の URL を指定してください: clone-web <url> [project_name] [--deploy] [--access MYSELF|ANYONE]"
        target_url = parts[1]
        p_name = parts[2] if len(parts) > 2 and not parts[2].startswith("--") else ""
        do_deploy = "--deploy" in parts
        access_val = "MYSELF"
        for i, pt in enumerate(parts):
            if pt == "--access" and i + 1 < len(parts):
                access_val = parts[i + 1]
        return clone_web(url=target_url, project=p_name, deploy=do_deploy, access=access_val)

    if sub in ("xray", "x-ray", "blueprint"):
        if len(parts) < 2:
            return "プロジェクト名を指定してください: xray <project> [filename]"
        fname = parts[2] if len(parts) > 2 else "Index"
        return xray(parts[1], filename=fname)

    if sub in ("diagnose", "diag"):
        if len(parts) < 2:
            return "プロジェクト名またはIDを指定してください: diagnose <project>"
        return diagnose(parts[1])

    if sub in ("verify-ui", "verify_frontend"):
        if len(parts) < 2:
            return "プロジェクト名を指定してください: verify-ui <project> [filename] [--test-js '...']"
        project = parts[1]
        fname = "Index"
        t_js = ""
        i = 2
        while i < len(parts):
            if parts[i] in ("--test-js", "--js") and i + 1 < len(parts):
                t_js = parts[i + 1]
                i += 2
            elif not parts[i].startswith("-"):
                fname = parts[i]
                i += 1
            else:
                i += 1
        return verify_frontend(project, filename=fname, test_js=t_js)

    if sub in ("inspect-ui", "inspect_ui", "screenshot"):
        if len(parts) < 2:
            return "プロジェクト名またはURLを指定してください: inspect-ui <project_or_url> [filename] [--all-themes] [--theme <theme>] [--actions '<json>']"
        target_arg = parts[1]
        p_name = "" if re.match(r"^https?://", target_arg, re.IGNORECASE) else target_arg
        u_str = target_arg if re.match(r"^https?://", target_arg, re.IGNORECASE) else ""
        fname = "Index"
        th = ""
        all_th = False
        acts_json = ""
        c_axe = True
        base_img = ""
        i = 2
        while i < len(parts):
            if parts[i] in ("--all-themes", "--all"):
                all_th = True
                i += 1
            elif parts[i] in ("--no-axe",):
                c_axe = False
                i += 1
            elif parts[i] in ("--baseline", "--diff") and i + 1 < len(parts):
                base_img = parts[i + 1]
                i += 2
            elif parts[i] in ("--theme", "-t") and i + 1 < len(parts):
                th = parts[i + 1]
                i += 2
            elif parts[i] in ("--actions", "--act") and i + 1 < len(parts):
                acts_json = parts[i + 1]
                i += 2
            elif not parts[i].startswith("-"):
                fname = parts[i]
                i += 1
            else:
                i += 1
        return inspect_ui(project=p_name, filename=fname, url=u_str, theme=th, all_themes=all_th, actions_json=acts_json, check_axe=c_axe, baseline=base_img)

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
            return "引数が不足しています: patch <project> <filename> <target> <replacement> [-a] [--force] [--dry-run] [--deploy] [--verify] [--dev]"
        return patch_code(
            non_flags[0], non_flags[1], non_flags[2], non_flags[3],
            replace_all=("-a" in parts or "--all" in parts),
            force=("--force" in parts),
            dry_run=("--dry-run" in parts),
            deploy=("--deploy" in parts),
            verify=("--verify" in parts),
            dev=("--dev" in parts)
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
        if not gas_local_extras or not hasattr(gas_local_extras, "add_qquick_channel"):
            return "add-channel は利用できません（gas_local_extras が未導入です）"
        non_flags = [p for p in parts[1:] if not p.startswith("-")]
        if len(non_flags) < 2:
            return "引数が不足しています: add-channel <project> <channel_id_or_url> [channel_name]"
        ch_name = non_flags[2] if len(non_flags) >= 3 else ""
        client = get_client()
        res = gas_local_extras.add_qquick_channel(client, non_flags[0], non_flags[1], channel_name=ch_name)
        if res.get("status") == "already_exists":
            return f"[INFO] チャンネル {res['channelId']} は既に登録されています。\nURL: {res.get('webAppUrl', '')}"
        name_str = f"\nチャンネル名: {res['channelName']}" if res.get("channelName") else ""
        total_str = f"\n現在の登録総数: {res['totalChannels']}件" if res.get("totalChannels") else ""
        return f"[SUCCESS] チャンネル追加完了\nチャンネルID: {res['channelId']}{name_str}{total_str}\nURL: {res.get('webAppUrl', '')}"

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

    if sub in ("bench", "benchmark"):
        if len(parts) < 3:
            return "引数が不足しています: bench <project> <func_name> [args] [--target-ms <ms>] [--expected <val>]"
        project = parts[1]
        func_name = parts[2]
        args_str = ""
        target_ms = 1000
        expected_str = ""
        i = 3
        while i < len(parts):
            if parts[i] == "--target-ms" and i + 1 < len(parts):
                try:
                    target_ms = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif parts[i] == "--expected" and i + 1 < len(parts):
                expected_str = parts[i + 1]
                i += 2
            elif not args_str and not parts[i].startswith("-"):
                args_str = parts[i]
                i += 1
            else:
                i += 1
        return benchmark_function(project, func_name, args=args_str, target_ms=target_ms, expected=expected_str)

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

    if sub == "trace-rpc":
        if len(parts) < 2:
            return "プロジェクト名またはURLを指定してください: trace-rpc <target> [filename] [--duration <sec>]"
        tgt = parts[1]
        fn = parts[2] if len(parts) > 2 and not parts[2].startswith("-") else "Index"
        dur = 5.0
        i = 2
        while i < len(parts):
            if parts[i] in ("--duration", "-d") and i + 1 < len(parts):
                dur = float(parts[i+1])
                i += 2
            else:
                i += 1
        return trace_rpc(target=tgt, filename=fn, duration=dur)

    if sub == "diff-behavior":
        if len(parts) < 2:
            return "プロジェクト名を指定してください: diff-behavior <project> [--target <target_id>] [--version <ver>]"
        proj = parts[1]
        tgt = ""
        ver = None
        i = 2
        while i < len(parts):
            if parts[i] in ("--target", "-t") and i + 1 < len(parts):
                tgt = parts[i+1]
                i += 2
            elif parts[i] in ("--version", "-v") and i + 1 < len(parts):
                ver = int(parts[i+1])
                i += 2
            else:
                i += 1
        return diff_behavior(project=proj, target=tgt, version=ver)

    if sub == "ledger":
        if len(parts) < 2:
            return "プロジェクト名を指定してください: ledger <project> [filename]"
        proj = parts[1]
        fn = parts[2] if len(parts) > 2 else "Index"
        return ledger(project=proj, filename=fn)

    
    if sub == "skin":
        if len(parts) < 2:
            return "プロジェクトを指定してください: skin <project> [preset] [filename] [--deploy]"
        proj = parts[1]
        pst = "linear"
        fn = "Index"
        dep = False
        i = 2
        while i < len(parts):
            if parts[i] in ("--deploy", "-d"):
                dep = True
                i += 1
            elif parts[i] in ("linear", "glass", "notion", "emerald", "saas", "apple", "minimal", "fintech", "stripe"):
                pst = parts[i]
                i += 1
            else:
                fn = parts[i]
                i += 1
        return design_skin(project=proj, filename=fn, preset=pst, deploy=dep)

    if sub in ("scaffold", "gas-scaffold", "gas_scaffold"):
        list_flag = "--list" in parts or "-l" in parts
        project = ""
        s_id = ""
        fname = "Index"
        s_file = "Code"
        apply_flag = False
        deploy_flag = False
        i = 1
        while i < len(parts):
            if parts[i] in ("--list", "-l"):
                list_flag = True
                i += 1
            elif parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif parts[i] == "--server-file" and i + 1 < len(parts):
                s_file = parts[i + 1]
                i += 2
            elif parts[i] in ("--id", "-i") and i + 1 < len(parts):
                s_id = parts[i + 1]
                i += 2
            elif parts[i] == "--apply":
                apply_flag = True
                i += 1
            elif parts[i] == "--deploy":
                deploy_flag = True
                i += 1
            elif not project and not parts[i].startswith("-"):
                project = parts[i]
                i += 1
            elif not s_id and not parts[i].startswith("-"):
                s_id = parts[i]
                i += 1
            else:
                i += 1
        return gas_scaffold(project=project, scaffold_id=s_id, filename=fname, server_file=s_file, apply=apply_flag, deploy=deploy_flag, list_only=list_flag)

    if sub in ("shelf", "seiri", "gas-shelf", "gas_shelf"):
        check_flag = "--check" in parts or "-c" in parts
        list_flag = "--list" in parts or "-l" in parts
        project = ""
        s_id = ""
        fname = "Index"
        fn_name = ""
        apply_flag = False
        deploy_flag = False
        query_words = []
        i = 1
        while i < len(parts):
            if parts[i] in ("--check", "-c"):
                check_flag = True
                i += 1
            elif parts[i] in ("--list", "-l"):
                list_flag = True
                i += 1
            elif parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif parts[i] == "--func" and i + 1 < len(parts):
                fn_name = parts[i + 1]
                i += 2
            elif parts[i] in ("--id", "-i") and i + 1 < len(parts):
                s_id = parts[i + 1]
                i += 2
            elif parts[i] == "--apply":
                apply_flag = True
                i += 1
            elif parts[i] == "--deploy":
                deploy_flag = True
                i += 1
            elif not project and not parts[i].startswith("-"):
                project = parts[i]
                i += 1
            elif not parts[i].startswith("-"):
                query_words.append(parts[i])
                i += 1
            else:
                i += 1

        query_str = " ".join(query_words).strip()
        return gas_shelf(project=project, query=query_str, shelf_id=s_id, filename=fname, func_name=fn_name, apply=apply_flag, deploy=deploy_flag, list_only=list_flag, check_only=check_flag)

    if sub in ("dock", "gas-dock", "gas_dock"):
        if len(parts) < 2:
            return "プロジェクト名を指定してください: dock <project> [-f <filename>]"
        proj = parts[1]
        fname = "Index"
        i = 2
        while i < len(parts):
            if parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            else:
                i += 1
        return gas_dock(project=proj, filename=fname)

    if sub in ("recipe", "gas-recipe", "gas_recipe"):
        list_flag = "--list" in parts or "-l" in parts
        project = ""
        r_id = ""
        fname = ""
        fn_name = ""
        apply_flag = False
        deploy_flag = False
        ask_words = []
        i = 1
        while i < len(parts):
            if parts[i] in ("--list", "-l"):
                list_flag = True
                i += 1
            elif parts[i] in ("-f", "--file") and i + 1 < len(parts):
                fname = parts[i + 1]
                i += 2
            elif parts[i] == "--func" and i + 1 < len(parts):
                fn_name = parts[i + 1]
                i += 2
            elif parts[i] in ("--id", "-i") and i + 1 < len(parts):
                r_id = parts[i + 1]
                i += 2
            elif parts[i] == "--ask" and i + 1 < len(parts):
                ask_words.append(parts[i + 1])
                i += 2
            elif parts[i] == "--apply":
                apply_flag = True
                i += 1
            elif parts[i] == "--deploy":
                deploy_flag = True
                i += 1
            elif not project and not parts[i].startswith("-"):
                project = parts[i]
                i += 1
            elif not parts[i].startswith("-"):
                ask_words.append(parts[i])
                i += 1
            else:
                i += 1
        ask_str = " ".join(ask_words).strip()
        return gas_recipe(project=project, filename=fname, func_name=fn_name, recipe_id=r_id, apply=apply_flag, deploy=deploy_flag, ask=ask_str, list_only=list_flag)

    if sub in ("sync", "sync-project", "sync_project"):
        if len(parts) < 2:
            return "プロジェクト名を指定してください: sync <project> [--force]"
        proj = parts[1]
        force_flag = "--force" in parts or "-f" in parts
        client = get_client()
        res = client.sync_project(proj, force=force_flag)
        lines = [
            f"=== 🔄 GAS ハイブリッド同期 (sync): [{res.get('script_id')}] ===",
            f"状態: {'同期完了 (クラウドから更新)' if res.get('updated_from_cloud') else '同期済み (ローカルキャッシュ利用・通信ゼロ)'}",
            f"更新時刻: {res.get('modifiedTime', 'N/A')}",
        ]
        if "file_count" in res:
            lines.append(f"ファイル数: {res.get('file_count')} 個")
        return "\n".join(lines)

    if sub in ("reload", "reload-tools", "reload_tools"):
        return reload_tools()

    if sub in ("py-outline", "py_outline"):
        if len(parts) < 2:
            return "Pythonファイルパスを指定してください: py-outline <file_path>"
        items = GasClient.py_outline(parts[1])
        lines = [
            f"=== 🐍 Python 関数一覧 (py-outline): [{parts[1]}] (計 {len(items)} 個) ===",
            "| 行範囲 | 種別 | 名前 | 行数 | 文字数 |",
            "| --- | --- | --- | --- | --- |"
        ]
        for it in items:
            kind = "メソッド" if it["is_method"] else "関数"
            lines.append(f"| L{it['start_line']}-L{it['end_line']} | {kind} | {it['name']} | {it['lines_count']}行 | {it['chars_count']}文字 |")
        return "\n".join(lines)

    if sub in ("py-func", "py_func", "py-get"):
        if len(parts) < 3:
            return "引数を指定してください: py-func <file_path> <func_spec>"
        res = GasClient.py_get_function(parts[1], parts[2])
        return res.get("markdown_report", res.get("source", ""))

    if sub in ("py-patch", "py_patch"):
        if len(parts) < 3:
            return "引数を指定してください: py-patch <file_path> <func_spec> [target] [replacement] [--code <code>] [--all]"
        f_path = parts[1]
        f_spec = parts[2]
        is_all = "--all" in parts or "-a" in parts
        new_c = ""
        target_str = ""
        repl_str = ""
        rem_parts = [p for p in parts[3:] if p not in ("--all", "-a")]
        if "--code" in rem_parts:
            c_idx = rem_parts.index("--code")
            if c_idx + 1 < len(rem_parts):
                new_c = rem_parts[c_idx + 1]
        elif len(rem_parts) >= 2:
            target_str = rem_parts[0]
            repl_str = rem_parts[1]
        res = GasClient.py_patch_function(f_path, f_spec, target=target_str, replacement=repl_str, new_code=new_c, replace_all=is_all)
        return res.get("markdown_report", "")

    return f"不明なコマンドです: '{sub}'。'help' で使い方を確認してください。"

@mcp.tool()
@safe_tool
def py_outline(file_path: str) -> str:
    """Pythonファイル内の関数・クラスメソッド一覧（行範囲・文字数・種別）をAST高速解析で抽出します。

    Args:
        file_path: 対象のPythonファイルパス (例: "gas_client.py")
    """
    items = GasClient.py_outline(file_path)
    lines = [
        f"=== 🐍 Python 関数一覧 (py_outline): [{file_path}] (計 {len(items)} 個) ===",
        "| 行範囲 | 種別 | 名前 | 行数 | 文字数 |",
        "| --- | --- | --- | --- | --- |"
    ]
    for it in items:
        kind = "メソッド" if it["is_method"] else "関数"
        lines.append(f"| L{it['start_line']}-L{it['end_line']} | {kind} | {it['name']} | {it['lines_count']}行 | {it['chars_count']}文字 |")
    return "\n".join(lines)

@mcp.tool()
@safe_tool
def py_get_function(file_path: str, func_spec: str) -> str:
    """Pythonファイルから指定された関数・メソッドの定義（デコレータ含む）をAST高速特定で抽出します。

    Args:
        file_path: 対象のPythonファイルパス (例: "gas_client.py")
        func_spec: 関数名またはクラス.メソッド名 (例: "reload_tools", "GasClient.gas_dock")
    """
    res = GasClient.py_get_function(file_path, func_spec)
    return res.get("markdown_report", res.get("source", ""))

@mcp.tool()
@safe_tool
def py_patch_function(
    file_path: str,
    func_spec: str,
    target: str = "",
    replacement: str = "",
    new_code: str = "",
    replace_all: bool = False
) -> str:
    """Pythonファイル内の指定関数スコープ限定でコード置換を行います。置換後に自動で構文検査（compile）を行い、構文エラー時は自動ロールバックします。

    Args:
        file_path: 対象のPythonファイルパス (例: "gas_client.py")
        func_spec: 関数名またはクラス.メソッド名 (例: "reload_tools", "GasClient.gas_dock")
        target: 置換前の文字列 (部分一致)
        replacement: 置換後の文字列
        new_code: 関数定義丸ごと差し替える場合の全コード (省略可)
        replace_all: 関数内で一致する全箇所を置換するか (既定: False で1箇所目のみ)
    """
    res = GasClient.py_patch_function(
        file_path, func_spec,
        target=target,
        replacement=replacement,
        new_code=new_code,
        replace_all=replace_all
    )
    return res.get("markdown_report", "")

if __name__ == "__main__":
    mcp.run()
