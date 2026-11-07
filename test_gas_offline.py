# -*- coding: utf-8 -*-
"""
test_gas_offline.py - gas-manager オフライン・純Python単体テスト
実機 GAS への通信をモックし、ミリ秒単位でロジック・安全性・関数抽出・構文検査を検証します。
"""

import pytest
from unittest.mock import MagicMock, patch
import json
import time
import os
from pathlib import Path
from gas_client import GasClient
import gas_mcp_server

@pytest.fixture
def mock_client(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "refresh_token": "dummy_refresh_token"
            }
        }
    }), encoding="utf-8")
    backup_dir = tmp_path / ".backups"

    with patch.object(GasClient, "get_access_token", return_value="dummy_access_token"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        client.cache_file = tmp_path / ".cache.json"
        client._cache_data = {"projects": {}, "deployments": {}}
        yield client

def test_add_channel_success_and_already_exists(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="mock_script_id")
    mock_client.resolve_youtube_channel_id = MagicMock(return_value=("UC1234567890123456789012", "TestChannel"))

    res_mock_success = MagicMock()
    res_mock_success.status_code = 200
    res_mock_success.json.return_value = {"action": "added", "name": "TestChannel", "total": 10}

    res_mock_exists = MagicMock()
    res_mock_exists.status_code = 200
    res_mock_exists.json.return_value = {"action": "already_exists", "name": "TestChannel", "total": 10}

    mock_client._cache_data["deployments"]["mock_script_id"] = {"id": "dep_1", "url": "https://script.google.com/macros/s/xxx/exec"}

    # 1. 成功時
    mock_client._request_with_retry = MagicMock(return_value=res_mock_success)
    res = mock_client.add_qquick_channel("mock_script_id", "UC1234567890123456789012")
    assert res["status"] == "success"
    assert res["channelId"] == "UC1234567890123456789012"
    assert res["channelName"] == "TestChannel"
    assert res["totalChannels"] == 10

    # MCP レスポンス検証
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        mcp_msg = gas_mcp_server.add_channel("mock_script_id", "UC1234567890123456789012")
        assert "[SUCCESS]" in mcp_msg
        assert "UC1234567890123456789012" in mcp_msg
        assert "10" in mcp_msg

    # 2. already_exists 時
    mock_client._request_with_retry = MagicMock(return_value=res_mock_exists)
    res_ex = mock_client.add_qquick_channel("mock_script_id", "UC1234567890123456789012")
    assert res_ex["status"] == "already_exists"

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        mcp_msg_ex = gas_mcp_server.add_channel("mock_script_id", "UC1234567890123456789012")
        assert "[INFO]" in mcp_msg_ex
        assert "UC1234567890123456789012" in mcp_msg_ex

def test_resolve_script_id_multiple_partial_matches(mock_client):
    mock_client.list_projects = MagicMock(return_value=[
        {"name": "G-Quick-NEXT", "id": "id_next"},
        {"name": "G-Quick-SIMPLE", "id": "id_simple"}
    ])

    with pytest.raises(ValueError) as excinfo:
        mock_client.resolve_script_id("G-Quick")

    err = str(excinfo.value)
    assert "(2件)" in err or "(2" in err
    assert "G-Quick-NEXT" in err
    assert "G-Quick-SIMPLE" in err

def test_resolve_script_id_cache_does_not_mask_duplicates(mock_client):
    # 以前のキャッシュがあっても、新規に重複プロジェクトが存在する場合は警告停止すること
    mock_client._cache_data["projects"]["G-Quick"] = "id_old"
    mock_client.list_projects = MagicMock(return_value=[
        {"name": "G-Quick-NEXT", "id": "id_next"},
        {"name": "G-Quick-SIMPLE", "id": "id_simple"}
    ])

    with pytest.raises(ValueError) as excinfo:
        mock_client.resolve_script_id("G-Quick")
    assert "複数あります" in str(excinfo.value)

def test_patch_code_multiple_occurrences(mock_client):
    content = {
        "files": [
            {
                "name": "code",
                "type": "SERVER_JS",
                "source": "var x = 1;\nvar x = 1;\n"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # replace_all=False で ValueError
    with pytest.raises(ValueError) as excinfo:
        mock_client.patch_code("dummy_id", "code", "var x = 1;", "var x = 2;", replace_all=False)
    assert "2" in str(excinfo.value)

    # replace_all=True で2箇所置換＆ diff 生成確認
    res = mock_client.patch_code("dummy_id", "code", "var x = 1;", "var x = 2;", replace_all=True)
    assert res["status"] == "success"
    assert res["replaced_occurrences"] == 2
    assert "-var x = 1;" in res["diff"]
    assert "+var x = 2;" in res["diff"]

def test_mcp_safe_tool_decorator():
    @gas_mcp_server.safe_tool
    def bad_tool():
        raise KeyError("test_key_error")

    res = bad_tool()
    assert res == "[ERROR] KeyError: 'test_key_error'"

def test_syntax_validation_and_force(mock_client):
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "broken", "type": "SERVER_JS", "source": "var x = 1;"}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 壊れたコード (構文エラー)
    bad_code = "function broken( {"

    # force=False の場合 ValueError で停止
    with patch.object(mock_client, "_validate_syntax", side_effect=ValueError("構文エラー")):
        with pytest.raises(ValueError):
            mock_client.patch_code("dummy_id", "broken", "var x = 1;", bad_code, force=False)

    # force=True の場合 PUT が呼ばれて完了
    with patch.object(mock_client, "_validate_syntax", return_value="skipped"):
        res = mock_client.patch_code("dummy_id", "broken", "var x = 1;", bad_code, force=True)
        assert res["status"] == "success"

    # Node 未存在環境でのシミュレーション
    with patch("subprocess.run", side_effect=FileNotFoundError):
        status = mock_client._validate_syntax("test", "var a = 1;")
        assert "skipped" in status

def test_syntax_validation_safe_filename(mock_client):
    # ファイル名にシングルクォートや特殊文字があっても安全に検査できること
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        status = mock_client._validate_syntax("user's \"script\" & <tag>", "var a = 1;")
        assert status == "valid"
        cmd = mock_run.call_args[0][0]
        # json.dumps によりエスケープされた引数が渡されていること
        assert "user's \\\"script\\\" & <tag>.gs" in cmd[2]

def test_backup_cleanup_30_limit(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "refresh_token": "dummy_refresh_token"
            }
        }
    }), encoding="utf-8")
    backup_dir = tmp_path / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(GasClient, "get_access_token", return_value="dummy"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        sid = "test_script_id_123456"
        sid_short = sid[:12]

        # 31個のバックアップを作成
        past_time = time.time() - 86400 * 2
        for i in range(31):
            f = backup_dir / f"backup_{sid_short}_20261031_0000{i:02d}.json"
            f.write_text(json.dumps({"files": []}), encoding="utf-8")
            os.utime(f, (past_time + i, past_time + i))

        assert len(list(backup_dir.glob(f"backup_{sid_short}_*.json"))) == 31

        # cleanup 実行
        client._cleanup_old_backups(sid, keep=30)
        remaining = list(backup_dir.glob(f"backup_{sid_short}_*.json"))
        assert len(remaining) == 30
        assert not (backup_dir / f"backup_{sid_short}_20261031_000000.json").exists()

def test_restore_backup(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "refresh_token": "dummy_refresh_token"
            }
        }
    }), encoding="utf-8")
    backup_dir = tmp_path / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(GasClient, "get_access_token", return_value="dummy"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        sid = "dummy_sid_1234567890123"
        client.resolve_script_id = MagicMock(return_value=sid)

        # バックアップファイルを1つ作成
        bak_file = backup_dir / f"backup_{sid[:12]}_20261031_120000.json"
        bak_data = {
            "files": [
                {"name": "file1", "type": "SERVER_JS", "source": "original_content"}
            ]
        }
        bak_file.write_text(json.dumps(bak_data), encoding="utf-8")

        # 現在のコンテンツ
        client.get_content = MagicMock(return_value={
            "files": [
                {"name": "file1", "type": "SERVER_JS", "source": "modified_content"}
            ]
        })
        client._put_content = MagicMock()

        # 復元実行
        res = client.restore_backup(sid, bak_file.name, filename="file1")
        assert res["status"] == "success"
        assert res["restored_file"] == "file1"
        client._put_content.assert_called_once()
        put_files = client._put_content.call_args[0][1]
        assert put_files[0]["source"] == "original_content"

def test_dry_run_no_put_and_no_backup(mock_client):
    content = {
        "files": [{"name": "code", "type": "SERVER_JS", "source": "var a = 1;"}]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()
    mock_client._save_backup = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.patch_code("dummy_id", "code", "var a = 1;", "var a = 2;", dry_run=True)
    assert res["status"] == "dry_run"
    assert "+var a = 2;" in res["diff"]
    mock_client._put_content.assert_not_called()
    mock_client._save_backup.assert_not_called()

def test_get_function_5_forms(mock_client):
    source_js = """
// 1. コメント内の波括弧 {無視}
function func1(a = (1 + 2), b = "}") {
    return a;
}

// 2. 文字列内の閉じ波括弧
const func2 = (x, y) => {
    const s = "}";
    return s;
};

// 3. テンプレート文字列内の波括弧
async function func3() {
    const t = `${1 + 1} {test}`;
    const complex = `nested ${ { a: 1 }.a } ok`;
    return t;
}

// 4. 引数に括弧を持つ既定値
const func4 = function(cb = () => 1) {
    return cb();
};

// 5. アロー関数 (引数括弧なし)
const func5 = x => {
    return x * 2;
};
"""
    source_html = """
<!DOCTYPE html>
<html>
<body>
<script>
function funcHtml(msg) {
    alert(msg);
}
</script>
</body>
</html>
"""
    mock_client.get_file = MagicMock(side_effect=lambda sid, fname: {
        "name": fname,
        "type": "HTML" if fname.endswith(".html") else "SERVER_JS",
        "source": source_html if fname.endswith(".html") else source_js
    })

    # 形1
    f1 = mock_client.get_function("dummy", "test.js", "func1")
    assert f1.startswith("function func1(a = (1 + 2), b = \"}\") {")
    assert f1.endswith("return a;\n}")
    assert "func2" not in f1

    # 形2 (セミコロン含む)
    f2 = mock_client.get_function("dummy", "test.js", "func2")
    assert f2.startswith("const func2 = (x, y) => {")
    assert f2.strip().endswith("};")
    assert "func3" not in f2

    # 形3 (テンプレート文字列・後続関数を含まないことの厳格検証！)
    f3 = mock_client.get_function("dummy", "test.js", "func3")
    assert f3.startswith("async function func3() {")
    assert f3.endswith("return t;\n}")
    assert "func4" not in f3, "致命的バグ: func3 の抽出に後続の func4 が含まれています！"

    # 形4
    f4 = mock_client.get_function("dummy", "test.js", "func4")
    assert f4.startswith("const func4 = function(cb = () => 1) {")
    assert f4.strip().endswith("};")
    assert "func5" not in f4

    # 形5 (引数括弧なしアロー関数)
    f5 = mock_client.get_function("dummy", "test.js", "func5")
    assert f5.startswith("const func5 = x => {")
    assert f5.strip().endswith("};")

    # 形6 (HTML 内 <script>)
    f_html = mock_client.get_function("dummy", "index.html", "funcHtml")
    assert f_html.startswith("function funcHtml(msg) {")
    assert f_html.endswith("alert(msg);\n}")

def test_replace_function_offline(mock_client):
    source_js = "function target() {\n    return 1;\n}\nfunction next() {}\n"
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "main", "type": "SERVER_JS", "source": source_js}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    new_func = "function target() {\n    return 999;\n}"
    res = mock_client.replace_function("dummy_id", "main", "target", new_func)
    assert res["status"] == "success"
    assert "-    return 1;" in res["diff"]
    assert "+    return 999;" in res["diff"]
    # next() が壊れずに残っていること
    put_files = mock_client._put_content.call_args[0][1]
    assert "function next() {}" in put_files[0]["source"]

def test_search_code_offline(mock_client):
    mock_client.get_content = MagicMock(return_value={
        "files": [
            {"name": "file1", "type": "SERVER_JS", "source": "var hello = 'world';\nvar test = 1;\n"},
            {"name": "file2", "type": "SERVER_JS", "source": "function hello() {}\n"}
        ]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.search_code("dummy_id", "hello")
    assert res["total_hits"] == 2
    assert "file1:1: var hello = 'world';" in res["hits"]
    assert "file2:1: function hello() {}" in res["hits"]

def test_call_webapp_cutoff_4000_and_post_no_retry(mock_client):
    # 4000文字超のレスポンス切り詰め
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.headers = {"Content-Type": "text/plain"}
    mock_res.text = "A" * 5000

    mock_client._request_with_retry = MagicMock(return_value=mock_res)
    res = mock_client.call_webapp("https://script.google.com/test", method="GET")
    assert len(res["text"]) < 5000
    assert "4000" in res["text"] or "1000" in res["text"]

    # POST 呼び出し時に max_retries=0, retry_5xx=False が渡されていることの検証
    mock_client.call_webapp("https://script.google.com/test", method="POST", body={"test": 1})
    call_args = mock_client._request_with_retry.call_args
    assert call_args[1]["max_retries"] == 0
    assert call_args[1]["retry_5xx"] is False

def test_no_question_mark_corruption():
    # 全 py ファイルに ? が連続して文字化けしている箇所が 0件 であることの恒久回帰防止テスト
    manager_dir = Path(__file__).resolve().parent
    triple_q = "?" * 3
    for py_file in manager_dir.glob("*.py"):
        if py_file.name.startswith("test_client") or py_file.name == "publish_check.py":
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        assert triple_q not in text, f"{py_file.name} に文字化けが残っています！"

def test_get_function_ignores_commented_out_and_strings(mock_client):
    source_js = """
// // comment function targetFunc() { old }
/*
function targetFunc() {
    block_comment_old
}
*/
const dummyStr = "function targetFunc() { in_string }";
const regexWithBrace = /[{]/g;

function targetFunc(a, b) {
    const r = /}/g;
    return 'real_result';
}

function nextFunc() {
    return 123;
}
"""
    mock_client.get_file = MagicMock(return_value={
        "name": "code",
        "type": "SERVER_JS",
        "source": source_js
    })
    func = mock_client.get_function("dummy", "code", "targetFunc")
    assert func.startswith("function targetFunc(a, b) {")
    assert func.endswith("return 'real_result';\n}")
    assert "old" not in func
    assert "in_string" not in func
    assert "nextFunc" not in func

def test_get_function_arrow_expression_body_and_class_method(mock_client):
    source_js = """
const addNum = (x, y) => x + y;
const square = x => x * x;

class Calculator {
    multiply(a, b) {
        return a * b;
    }
}
"""
    mock_client.get_file = MagicMock(return_value={
        "name": "code",
        "type": "SERVER_JS",
        "source": source_js
    })

    f_add = mock_client.get_function("dummy", "code", "addNum")
    assert f_add == "const addNum = (x, y) => x + y;"

    f_sq = mock_client.get_function("dummy", "code", "square")
    assert f_sq == "const square = x => x * x;"

    f_mul = mock_client.get_function("dummy", "code", "multiply")
    assert f_mul.startswith("multiply(a, b) {")
    assert f_mul.endswith("return a * b;\n    }")

def test_html_multiple_scripts(mock_client):
    html_source = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.example.com/lib.js"></script>
    <script>
        function firstScriptFunc() {
            return 1;
        }
    </script>
</head>
<body>
    <script>
        function targetClientFunc(msg) {
            console.log(msg);
        }
    </script>
</body>
</html>
"""
    mock_client.get_file = MagicMock(return_value={
        "name": "index",
        "type": "HTML",
        "source": html_source
    })
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "index", "type": "HTML", "source": html_source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. 2つ目の script 内の関数を取得
    func = mock_client.get_function("dummy", "index.html", "targetClientFunc")
    assert "function targetClientFunc(msg) {" in func
    assert "console.log(msg);" in func

    # 2. 関数置換
    new_func = "function targetClientFunc(msg) {\n            alert(msg);\n        }"
    res = mock_client.replace_function("dummy_id", "index.html", "targetClientFunc", new_func)
    assert res["status"] == "success"
    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "alert(msg);" in put_source
    assert "firstScriptFunc" in put_source

def test_match_file_type_disambiguation(mock_client):
    files = [
        {"name": "page", "type": "SERVER_JS", "source": "// server js"},
        {"name": "page", "type": "HTML", "source": "<!-- html -->"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 拡張子なし 'page' は曖昧性エラー
    with pytest.raises(ValueError) as exc:
        mock_client.get_file("dummy", "page")
    assert "同名のファイルが複数存在します" in str(exc.value)

    # 'page.html' は HTML を取得
    f_html = mock_client.get_file("dummy", "page.html")
    assert f_html["type"] == "HTML"

    # 'page.gs' は SERVER_JS を取得
    f_js = mock_client.get_file("dummy", "page.gs")
    assert f_js["type"] == "SERVER_JS"

    # 削除時も 'page.html' を指定すれば HTML のみが削除される
    del_res = mock_client.delete_file("dummy", "page.html")
    assert del_res["status"] == "success"
    rem_files = mock_client._put_content.call_args[0][1]
    assert len(rem_files) == 1
    assert rem_files[0]["type"] == "SERVER_JS"

def test_patch_code_crlf_lf_auto_normalization(mock_client):
    source_lf = "function test() {\n    return 1;\n}\n"
    target_crlf = "function test() {\r\n    return 1;\r\n}"
    repl_crlf = "function test() {\r\n    return 2;\r\n}"

    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "main", "type": "SERVER_JS", "source": source_lf}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.patch_code("dummy_id", "main", target_crlf, repl_crlf)
    assert res["status"] == "success"
    put_files = mock_client._put_content.call_args[0][1]
    assert "return 2;" in put_files[0]["source"]

def test_youtube_channel_at_handle(mock_client):
    with patch.object(mock_client, "_request_with_retry") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<meta itemprop="channelId" content="UC1234567890123456789012"><meta name="title" content="My Channel - YouTube">'
        mock_req.return_value = mock_resp

        cid, cname = mock_client.resolve_youtube_channel_id("@my_custom_handle")
        assert cid == "UC1234567890123456789012"
        assert cname == "My Channel"
        assert mock_req.call_args[0][1] == "https://www.youtube.com/@my_custom_handle"

def test_put_content_empty_files_protection(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    with pytest.raises(ValueError) as exc:
        mock_client._put_content("dummy_id", [])
    assert "保護エラー" in str(exc.value)

def test_add_file_appsscript_protection(mock_client):
    mock_client.get_content = MagicMock(return_value={"files": []})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    with pytest.raises(ValueError) as exc:
        mock_client.add_file("dummy_id", "appsscript.json", "js")
    assert "マニフェストファイル 'appsscript' は新規追加できません" in str(exc.value)

def test_call_webapp_json_string_auto_detection(mock_client):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.headers = {"Content-Type": "application/json"}
    mock_res.json.return_value = {"ok": True}
    mock_res.text = '{"ok": true}'

    mock_client._request_with_retry = MagicMock(return_value=mock_res)
    # JSON 文字列として渡された場合
    res = mock_client.call_webapp("https://script.google.com/test", method="POST", body='{"action":"test_json"}')
    call_args = mock_client._request_with_retry.call_args
    # json パラメータとして辞書が渡されていること
    assert call_args[1]["json"] == {"action": "test_json"}
    assert res["data"] == {"ok": True}

def test_search_code_exclude(mock_client):
    mock_client.get_content = MagicMock(return_value={
        "files": [
            {"name": "appsscript", "type": "JSON", "source": '"timeZone": "Asia/Tokyo"'},
            {"name": "main", "type": "SERVER_JS", "source": 'const tz = "Asia/Tokyo";'}
        ]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. 除外なしでは 2件 ヒット
    res_all = mock_client.search_code("dummy_id", "Asia/Tokyo")
    assert res_all["total_hits"] == 2

    # 2. appsscript を除外すると 1件 ヒット
    res_ex = mock_client.search_code("dummy_id", "Asia/Tokyo", exclude="appsscript")
    assert res_ex["total_hits"] == 1
    assert "main:1:" in res_ex["hits"][0]

def test_find_function_span_with_escaped_backslashes(mock_client):
    source = (
        "function targetFunc() {\n"
        "  const val = '\\\\\\\''; // 3 backslashes followed by quote\n"
        "  return { status: 'ok' };\n"
        "}\n"
        "function nextFunc() { return 123; }"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "code", "type": "SERVER_JS", "source": source}]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    code = mock_client.get_function("dummy_id", "code", "targetFunc")
    assert "return { status: 'ok' };" in code
    assert "nextFunc" not in code
    assert code.strip().endswith("}")

def test_add_file_same_name_different_type(mock_client):
    mock_client.get_content = MagicMock(return_value={
        "files": [
            {"name": "index", "type": "SERVER_JS", "source": "function doGet() {}"}
        ]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client._put_content = MagicMock()

    # 1. 同名で HTML なら追加成功
    res = mock_client.add_file("dummy_id", "index", "html", "<h1>Hello</h1>")
    assert res["status"] == "success"
    assert res["added_file"] == "index"
    assert res["type"] == "HTML"
    mock_client._put_content.assert_called_once()

    # 2. 同名で SERVER_JS (同種別) ならエラー
    with pytest.raises(ValueError) as exc:
        mock_client.add_file("dummy_id", "index", "js", "function other() {}")
    assert "同名のファイルが既に存在します" in str(exc.value)

def test_patch_code_batch_patches(mock_client):
    content = {
        "files": [
            {
                "name": "code",
                "type": "SERVER_JS",
                "source": "const a = 1;\nconst b = 2;\nconst c = 3;\n"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    patches = [
        {"target": "const a = 1;", "replacement": "const a = 10;"},
        {"target": "const b = 2;", "replacement": "const b = 20;"}
    ]
    res = mock_client.patch_code("dummy_id", "code", patches=patches)
    assert res["status"] == "success"
    assert res["replaced_occurrences"] == 2
    assert "-const a = 1;" in res["diff"]
    assert "+const a = 10;" in res["diff"]
    assert "-const b = 2;" in res["diff"]
    assert "+const b = 20;" in res["diff"]

    # 1回の PUT で両方が置換されていることを確認
    mock_client._put_content.assert_called_once()
    put_files = mock_client._put_content.call_args[0][1]
    assert "const a = 10;" in put_files[0]["source"]
    assert "const b = 20;" in put_files[0]["source"]
    assert "const c = 3;" in put_files[0]["source"]

def test_get_file_line_range(mock_client):
    source = "line 1\nline 2\nline 3\nline 4\nline 5\n"
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "range_test", "type": "SERVER_JS", "source": source}]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. start_line=2, end_line=4 指定時
    res = mock_client.get_file("dummy_id", "range_test", start_line=2, end_line=4)
    assert res["source"] == "line 2\nline 3\nline 4\n"
    assert res["start_line"] == 2
    assert res["end_line"] == 4
    assert res["total_lines"] == 5

    # 2. 未指定時（後方互換性: 全文取得）
    res_all = mock_client.get_file("dummy_id", "range_test")
    assert res_all["source"] == source
    assert res_all["total_lines"] == 5
    assert "start_line" not in res_all

    # 3. MCP ツールの出力検証
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 範囲指定あり
        msg = gas_mcp_server.get_file("dummy_id", "range_test", start_line=2, end_line=3)
        assert "行 2-3 / 全5行" in msg
        assert "line 2\nline 3\n" in msg
        assert "line 1" not in msg

        # 範囲指定なし (デフォルト 0, 0)
        msg_default = gas_mcp_server.get_file("dummy_id", "range_test")
        assert "全5行" not in msg_default
        assert "line 1\nline 2\nline 3\nline 4\nline 5\n" in msg_default

def test_resolve_script_id_cache_hits_when_few_projects(mock_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "files": [
            {"id": "id_prj1", "name": "ProjectAlpha", "modifiedTime": "2026-10-31T00:00:00Z"},
            {"id": "id_prj2", "name": "ProjectBeta", "modifiedTime": "2026-10-31T00:00:00Z"}
        ]
    }
    mock_client._request_with_retry = MagicMock(return_value=mock_resp)

    # 1回目の解決
    sid1 = mock_client.resolve_script_id("ProjectAlpha")
    assert sid1 == "id_prj1"
    assert mock_client._request_with_retry.call_count == 1

    # 2回目の解決（プロジェクト総数が2件でもキャッシュヒットし、通信は1回のみ）
    sid2 = mock_client.resolve_script_id("ProjectBeta")
    assert sid2 == "id_prj2"
    assert mock_client._request_with_retry.call_count == 1

def test_patch_code_empty_target_raises_error(mock_client):
    content = {
        "files": [{"name": "code", "type": "SERVER_JS", "source": "var x = 1;"}]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # target="" で呼んだ場合は ValueError で安全に拒否される
    with pytest.raises(ValueError) as exc:
        mock_client.patch_code("dummy_id", "code", target="", replacement="malicious")
    assert "target" in str(exc.value)

    # patches=[{"target": "", "replacement": "..."}] でも同様に拒否される
    with pytest.raises(ValueError) as exc:
        mock_client.patch_code("dummy_id", "code", patches=[{"target": "", "replacement": "test"}])
    assert "target" in str(exc.value)

def test_list_functions_js_and_html(mock_client):
    js_source = (
        "function funcOne(a) {\n"
        "  return a + 1;\n"
        "}\n"
        "const funcTwo = (b) => {\n"
        "  return b * 2;\n"
        "};\n"
    )
    html_source = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "<script>\n"
        "function htmlFuncA() {\n"
        "  return 1;\n"
        "}\n"
        "</script>\n"
        "</head>\n"
        "<body>\n"
        "<script>\n"
        "const htmlFuncB = () => 2;\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [
            {"name": "main", "type": "SERVER_JS", "source": js_source},
            {"name": "page", "type": "HTML", "source": html_source}
        ]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. client.list_functions
    res = mock_client.list_functions("dummy_id")
    assert len(res) == 2

    main_funcs = next(f for f in res if f["file"] == "main")["functions"]
    assert len(main_funcs) == 2
    assert main_funcs[0]["name"] == "funcOne"
    assert main_funcs[0]["start_line"] == 1
    assert main_funcs[1]["name"] == "funcTwo"
    assert main_funcs[1]["start_line"] == 4

    html_funcs = next(f for f in res if f["file"] == "page")["functions"]
    assert len(html_funcs) == 2
    assert html_funcs[0]["name"] == "htmlFuncA"
    assert html_funcs[0]["start_line"] == 5
    assert html_funcs[1]["name"] == "htmlFuncB"
    assert html_funcs[1]["start_line"] == 12

    # 2. MCP list_functions
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        msg = gas_mcp_server.list_functions("dummy_id")
        assert "=== [dummy_id] の関数一覧 (2ファイル) ===" in msg
        assert "[main.SERVER_JS] (2個の関数)" in msg
        assert "funcOne (行 1-3" in msg
        assert "[page.HTML] (2個の関数)" in msg
        assert "htmlFuncA (行 5-7" in msg

def test_patch_and_replace_with_auto_deploy(mock_client):
    content = {
        "files": [
            {"name": "code", "type": "SERVER_JS", "source": "function testFn() {\n  var a = 1;\n}"}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.deploy = MagicMock(return_value={
        "versionNumber": 42,
        "webAppUrl": "https://script.google.com/macros/s/xxx/exec",
        "description": "Auto deployed via GasClient"
    })

    # patch_code with deploy=True, verify=True
    mock_client.verify_frontend = MagicMock(return_value={"status": "success", "indexeddb_count": 5})
    res_patch = mock_client.patch_code("dummy_id", "code", "var a = 1;", "var a = 2;", deploy=True, verify=True)
    assert res_patch["status"] == "success"
    assert "deployment" in res_patch
    assert res_patch["deployment"]["versionNumber"] == 42
    assert "verify" in res_patch
    assert res_patch["verify"]["status"] == "success"
    mock_client.deploy.assert_called_once()
    mock_client.verify_frontend.assert_called_once()

    # replace_function with deploy=True
    mock_client.deploy.reset_mock()
    res_rf = mock_client.replace_function("dummy_id", "code", "testFn", "function testFn() {\n  var a = 99;\n}", deploy=True)
    assert res_rf["status"] == "success"
    assert "deployment" in res_rf
    assert res_rf["deployment"]["versionNumber"] == 42
    mock_client.deploy.assert_called_once()

    # replace_file with deploy=True
    mock_client.deploy.reset_mock()
    res_rf_file = mock_client.replace_file("dummy_id", "code", "function testFn() {\n  var a = 100;\n}", deploy=True)
    assert res_rf_file["status"] == "success"
    assert "deployment" in res_rf_file
    assert res_rf_file["deployment"]["versionNumber"] == 42
    mock_client.deploy.assert_called_once()

def test_html_script_syntax_validation(mock_client):
    valid_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<script>\n"
        "  const token = <?= JSON.stringify(data) ?>;\n"
        "  <? if (user) { ?>\n"
        "  console.log('Logged in');\n"
        "  <? } ?>\n"
        "  function init() { return token; }\n"
        "</script>\n"
        "</html>\n"
    )
    status = mock_client._validate_syntax("index", valid_html, file_type="HTML")
    assert status == "valid"

    broken_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<script>\n"
        "  function broken( {\n"
        "</script>\n"
        "</html>\n"
    )
    with pytest.raises(ValueError) as exc:
        mock_client._validate_syntax("index", broken_html, file_type="HTML")
    assert "構文エラーが検出されました [index.html]" in str(exc.value)

def test_disk_content_cache_persistence(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "dummy_client_id",
                "client_secret": "dummy_client_secret",
                "refresh_token": "dummy_refresh_token"
            }
        }
    }), encoding="utf-8")
    backup_dir = tmp_path / ".backups"
    cache_file = tmp_path / ".cache.json"

    sid = "test_script_id_disk_cache"
    data = {"files": [{"name": "persisted", "type": "SERVER_JS", "source": "var p = 1;"}]}

    # 1つ目のインスタンスで get_content を呼ぶ (API 通信発生)
    with patch.object(GasClient, "get_access_token", return_value="dummy_token"):
        client1 = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        client1.cache_file = cache_file
        client1.resolve_script_id = MagicMock(return_value=sid)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        client1._request_with_retry = MagicMock(return_value=mock_resp)

        res1 = client1.get_content(sid)
        assert client1._request_with_retry.call_count == 1
        assert res1["files"][0]["name"] == "persisted"

    # 2つ目のインスタンスで同じキャッシュファイルを参照して呼ぶ (ディスクキャッシュにより通信なし)
    with patch.object(GasClient, "get_access_token", return_value="dummy_token"):
        client2 = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        client2.cache_file = cache_file
        client2.resolve_script_id = MagicMock(return_value=sid)
        client2._request_with_retry = MagicMock()

        res2 = client2.get_content(sid)
        assert client2._request_with_retry.call_count == 0
        assert res2["files"][0]["name"] == "persisted"

def test_mcp_unified_gas_command(mock_client):
    content = {
        "files": [
            {"name": "code", "type": "SERVER_JS", "source": "function hello() { return 'world'; }"}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. help
        help_msg = gas_mcp_server.gas("help")
        assert "=== gas 統合コマンド一覧 ===" in help_msg

        # 2. files
        files_msg = gas_mcp_server.gas("files dummy_id")
        assert "code.SERVER_JS" in files_msg

        # 3. outline
        outline_msg = gas_mcp_server.gas("outline dummy_id")
        assert "hello (行 1-1" in outline_msg

        # 4. 未知のコマンド
        unknown_msg = gas_mcp_server.gas("unknown_cmd")
        assert "不明なコマンドです" in unknown_msg

def test_html_non_js_script_tag_ignored(mock_client):
    html_mixed = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<script type="application/json">\n'
        '{"invalid": "json", syntax error here :}\n'
        "</script>\n"
        '<script type="text/template">\n'
        '<div><%= item %></div>\n'
        "</script>\n"
        "<script>\n"
        "function validFunc() {\n"
        "  return 'ok';\n"
        "}\n"
        "</script>\n"
        "</head>\n"
        "</html>\n"
    )

    # 1. _validate_syntax が非JSタグを無視して valid を返すこと
    status = mock_client._validate_syntax("index", html_mixed, file_type="HTML")
    assert status == "valid"

    # 2. list_functions が非JSタグ内の誤検出を起こさず validFunc のみを抽出すること
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "index", "type": "HTML", "source": html_mixed}]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    res = mock_client.list_functions("dummy_id")
    funcs = res[0]["functions"]
    assert len(funcs) == 1
    assert funcs[0]["name"] == "validFunc"

def test_mcp_gas_command_flags(mock_client):
    content = {
        "files": [
            {"name": "main", "type": "SERVER_JS", "source": "function hello() {}\nconst abc = 1;"},
            {"name": "appsscript", "type": "JSON", "source": '"timeZone": "Asia/Tokyo"'}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. grep フラグ付き (正規表現 -r と 除外 -e)
        grep_msg = gas_mcp_server.gas("grep dummy_id [a-z]+ -r -e appsscript")
        assert "横断検索結果" in grep_msg
        assert "main:1:" in grep_msg
        assert "appsscript" not in grep_msg

        # 2. outline フラグ付き (-f)
        outline_msg = gas_mcp_server.gas("outline dummy_id -f main")
        assert "[main.SERVER_JS]" in outline_msg
        assert "hello (行 1-1" in outline_msg

def test_diagnose_healthy_project(mock_client):
    content = {
        "files": [
            {
                "name": "Server",
                "type": "SERVER_JS",
                "source": (
                    "// HtmlService.createTemplateFromFile('commented_out_missing');\n"
                    "function doGet(e) {\n"
                    "  return HtmlService.createTemplateFromFile('index').evaluate();\n"
                    "}\n"
                    "function renderIndexHtml() {\n"
                    "  return HtmlService.createTemplateFromFile('index.html').evaluate();\n"
                    "}\n"
                    "function apiGetData() {\n"
                    "  const inner = () => { return 1; };\n"
                    "  return inner();\n"
                    "}\n"
                )
            },
            {
                "name": "index",
                "type": "HTML",
                "source": (
                    "<!DOCTYPE html>\n"
                    "<html>\n"
                    "<body>\n"
                    "<script>\n"
                    "google.script.run\n"
                    "  .withSuccessHandler(function(res) { console.log(res); })\n"
                    "  .withFailureHandler(err => alert(err))\n"
                    "  .apiGetData();\n"
                    "</script>\n"
                    "</body>\n"
                    "</html>\n"
                )
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    assert diag["status"] == "healthy"
    assert diag["issues_count"] == 0
    assert len(diag["syntax_errors"]) == 0
    assert len(diag["duplicate_functions"]) == 0
    assert len(diag["broken_rpc_calls"]) == 0
    assert len(diag["broken_html_templates"]) == 0
    assert "doGet" in diag["entry_points"]
    assert diag["total_functions"] == 4  # doGet, renderIndexHtml, apiGetData, inner

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        msg = gas_mcp_server.diagnose("dummy_id")
        assert "判定: 正常 (HEALTHY)" in msg
        assert "問題: 0件" in msg

        gas_msg = gas_mcp_server.gas("diagnose dummy_id")
        assert "判定: 正常 (HEALTHY)" in gas_msg

def test_diagnose_detects_all_issues(mock_client):
    content = {
        "files": [
            {
                "name": "server1",
                "type": "SERVER_JS",
                "source": (
                    "function sharedFunction() {\n"
                    "  return 'from server1';\n"
                    "}\n"
                    "function render() {\n"
                    "  return HtmlService.createTemplateFromFile('missing_template').evaluate();\n"
                    "}\n"
                )
            },
            {
                "name": "server2",
                "type": "SERVER_JS",
                "source": (
                    "function sharedFunction() {\n"
                    "  return 'from server2 (conflict)';\n"
                    "}\n"
                )
            },
            {
                "name": "syntax_err",
                "type": "SERVER_JS",
                "source": "function badSyntax() { const a = ; }"
            },
            {
                "name": "index",
                "type": "HTML",
                "source": (
                    "<!DOCTYPE html>\n"
                    "<html>\n"
                    "<head>\n"
                    "<script>\n"
                    "google.script.run\n"
                    "  .withSuccessHandler(function(r){ (function nested(){ return r; })(); })\n"
                    "  .apiNonExistentFunc();\n"
                    "</script>\n"
                    "</head>\n"
                    "</html>\n"
                )
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    assert diag["status"] == "warning"
    assert diag["issues_count"] == 4

    # 1. 構文エラー
    assert len(diag["syntax_errors"]) == 1
    assert diag["syntax_errors"][0]["file"] == "syntax_err"

    # 2. トップレベル重複衝突
    assert len(diag["duplicate_functions"]) == 1
    assert diag["duplicate_functions"][0]["name"] == "sharedFunction"
    assert len(diag["duplicate_functions"][0]["locations"]) == 2

    # 3. RPCリンク切れ
    assert len(diag["broken_rpc_calls"]) == 1
    assert diag["broken_rpc_calls"][0]["target_function"] == "apiNonExistentFunc"
    assert diag["broken_rpc_calls"][0]["file"] == "index"

    # 4. テンプレートリンク切れ
    assert len(diag["broken_html_templates"]) == 1
    assert diag["broken_html_templates"][0]["template_name"] == "missing_template"
    assert diag["broken_html_templates"][0]["file"] == "server1"

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        msg = gas_mcp_server.diagnose("dummy_id")
        assert "警告あり (WARNING: 4件の問題)" in msg
        assert "syntax_err" in msg
        assert "sharedFunction" in msg
        assert "apiNonExistentFunc" in msg
        assert "missing_template" in msg

def test_check_setup_wizard(tmp_path):
    # 1. .clasprc.json が存在しない場合: 例外で落ちずに needs_login を返すこと
    non_existent = tmp_path / "non_existent_clasprc.json"
    res_no_login = GasClient.check_setup(clasprc_path=str(non_existent), open_browser=False)
    assert res_no_login["status"] == "needs_login"
    assert res_no_login["clasprc_found"] is False
    assert "npm install -g @google/clasp" in "".join(res_no_login["steps"])

    # 2. .clasprc.json が存在し API 疎通が成功する場合: ready を返すこと
    valid_clasprc = tmp_path / "valid_clasprc.json"
    valid_clasprc.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "dummy",
                "client_secret": "dummy",
                "refresh_token": "dummy_refresh"
            }
        }
    }), encoding="utf-8")

    with patch.object(GasClient, "get_access_token", return_value="dummy_token"), \
         patch.object(GasClient, "list_projects", return_value=[{"name": "test_proj", "id": "id1"}]):
        res_ready = GasClient.check_setup(clasprc_path=str(valid_clasprc), open_browser=False)
        assert res_ready["status"] == "ready"
        assert res_ready["clasprc_found"] is True
        assert res_ready["api_connected"] is True
        assert "セットアップ完了" in res_ready["message"]

    # 3. MCP setup_check および gas("setup") の呼び出し確認
    with patch.object(GasClient, "check_setup", return_value=res_ready):
        mcp_msg = gas_mcp_server.setup_check(open_browser=False)
        assert "[READY]" in mcp_msg
        assert "セットアップ完了" in mcp_msg

        gas_msg = gas_mcp_server.gas("setup")
        assert "[READY]" in gas_msg

def test_clasprc_three_formats(tmp_path):
    backup_dir = tmp_path / ".backups"

    # フォーマット1: tokens.default (新clasp形式)
    f1 = tmp_path / "f1.json"
    f1.write_text(json.dumps({
        "tokens": {
            "default": {
                "client_id": "cid1",
                "client_secret": "sec1",
                "refresh_token": "ref1"
            }
        }
    }), encoding="utf-8")

    # フォーマット2: token (旧clasp / Qiita記事形式)
    f2 = tmp_path / "f2.json"
    f2.write_text(json.dumps({
        "token": {
            "client_id": "cid2",
            "client_secret": "sec2",
            "refresh_token": "ref2"
        }
    }), encoding="utf-8")

    # フォーマット3: 直下フラット形式
    f3 = tmp_path / "f3.json"
    f3.write_text(json.dumps({
        "client_id": "cid3",
        "client_secret": "sec3",
        "refresh_token": "ref3"
    }), encoding="utf-8")

    with patch.object(GasClient, "get_access_token", return_value="dummy_token"), \
         patch.object(GasClient, "list_projects", return_value=[]):
        for fpath, expected_ref in [(f1, "ref1"), (f2, "ref2"), (f3, "ref3")]:
            client = GasClient(clasprc_path=str(fpath), backup_dir=str(backup_dir))
            assert client._token_data.get("refresh_token") == expected_ref
            setup_res = GasClient.check_setup(clasprc_path=str(fpath), open_browser=False)
            assert setup_res["clasprc_found"] is True
            assert setup_res["status"] == "ready"

def test_list_deployments_and_resolve_webapp_url(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="sid_123")
    mock_client.get_deployments = MagicMock(return_value=[
        {
            "deploymentId": "dep_head",
            "deploymentConfig": {"versionNumber": 1, "description": "v1 initial"},
            "updateTime": "2026-01-01T00:00:00Z",
            "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/v1/exec"}}]
        },
        {
            "deploymentId": "dep_latest",
            "deploymentConfig": {"versionNumber": 2, "description": "v2 update"},
            "updateTime": "2026-02-01T00:00:00Z",
            "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/v2/exec"}}]
        }
    ])

    # 1. list_deployments 整形検証
    deps = mock_client.list_deployments("sid_123")
    assert len(deps) == 2
    assert deps[0]["deploymentId"] == "dep_head"
    assert deps[0]["versionNumber"] == "1"
    assert deps[0]["webAppUrl"] == "https://script.google.com/macros/s/v1/exec"
    assert deps[1]["deploymentId"] == "dep_latest"
    assert deps[1]["versionNumber"] == "2"

    # MCP list_deployments 検証
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        mcp_deps = gas_mcp_server.list_deployments("sid_123")
        assert "dep_latest" in mcp_deps
        assert "v2 update" in mcp_deps

    # 2. resolve_webapp_url (最新の末尾優先でキャッシュされること)
    url = mock_client.resolve_webapp_url("sid_123")
    assert url == "https://script.google.com/macros/s/v2/exec"
    assert mock_client._cache_data.get("deployments", {}).get("sid_123", {}).get("url") == url

    # 3. キャッシュヒット時は通信0回
    mock_client.get_deployments.reset_mock()
    url_cached = mock_client.resolve_webapp_url("sid_123")
    assert url_cached == url
    mock_client.get_deployments.assert_not_called()

    # 4. call_webapp にプロジェクト名を渡した際に自動で resolve_webapp_url されてリクエスト
    res_mock = MagicMock()
    res_mock.status_code = 200
    res_mock.headers = {"Content-Type": "application/json"}
    res_mock.json.return_value = {"ok": True}
    res_mock.text = '{"ok": true}'
    mock_client._request_with_retry = MagicMock(return_value=res_mock)

    call_res = mock_client.call_webapp("sid_123", params={"action": "test"})
    assert call_res["status_code"] == 200
    assert call_res["data"] == {"ok": True}
    assert mock_client._request_with_retry.call_args[0][1] == "https://script.google.com/macros/s/v2/exec"

def test_diff_backup_offline(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {"default": {"client_id": "cid", "client_secret": "sec", "refresh_token": "ref"}}
    }), encoding="utf-8")
    backup_dir = tmp_path / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # バックアップJSON作成
    sid = "test_script_id_12345678901234567890"
    bak_file = backup_dir / f"backup_{sid[:12]}_20260101_120000_000000.json"
    bak_file.write_text(json.dumps({
        "files": [
            {"name": "main", "type": "SERVER_JS", "source": "function hello() {\n  return 1;\n}\n"},
            {"name": "index", "type": "HTML", "source": "<h1>Hello</h1>\n"}
        ]
    }), encoding="utf-8")

    with patch.object(GasClient, "get_access_token", return_value="dummy_token"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(backup_dir))
        client.resolve_script_id = MagicMock(return_value=sid)

        # ケースA: 現在のコードに差分がある場合
        client.get_content = MagicMock(return_value={
            "files": [
                {"name": "main", "type": "SERVER_JS", "source": "function hello() {\n  return 2;\n}\n"},
                {"name": "index", "type": "HTML", "source": "<h1>Hello</h1>\n"}
            ]
        })

        diff_res = client.diff_backup(sid, backup_file=bak_file.name)
        assert diff_res["backup_file"] == bak_file.name
        assert diff_res["changed_files"] == ["main.gs"]
        assert "-  return 1;" in diff_res["diff"]
        assert "+  return 2;" in diff_res["diff"]
        assert "a/main.gs (backup)" in diff_res["diff"]
        assert "b/main.gs (current)" in diff_res["diff"]

        # MCP diff_backup の検証
        with patch("gas_mcp_server.get_client", return_value=client):
            mcp_diff = gas_mcp_server.diff_backup(sid)
            assert "main.gs" in mcp_diff
            assert "+  return 2;" in mcp_diff

            # gas("diff ...") 統合窓口の検証
            gas_diff = gas_mcp_server.gas(f"diff {sid}")
            assert "main.gs" in gas_diff

        # ケースB: 差分がない場合
        client.get_content = MagicMock(return_value={
            "files": [
                {"name": "main", "type": "SERVER_JS", "source": "function hello() {\n  return 1;\n}\n"},
                {"name": "index", "type": "HTML", "source": "<h1>Hello</h1>\n"}
            ]
        })
        diff_no_change = client.diff_backup(sid, backup_file=bak_file.name)
        assert diff_no_change["changed_files"] == []
        assert diff_no_change["diff"] == ""

        with patch("gas_mcp_server.get_client", return_value=client):
            mcp_no_diff = gas_mcp_server.diff_backup(sid)
            assert "差分はありません" in mcp_no_diff

def test_diagnose_manifest_and_batch_syntax(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. appsscript.json 正常時
    content_ok = {
        "files": [
            {
                "name": "appsscript",
                "type": "JSON",
                "source": json.dumps({
                    "timeZone": "Asia/Tokyo",
                    "runtimeVersion": "V8",
                    "webapp": {"access": "ANYONE_ANONYMOUS", "executeAs": "USER_DEPLOYING"},
                    "exceptionLogging": "STACKDRIVER"
                })
            },
            {
                "name": "Code",
                "type": "SERVER_JS",
                "source": "function doGet() { return HtmlService.createHtmlOutput('ok'); }"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content_ok)
    diag_ok = mock_client.diagnose("dummy_id")
    assert "manifest" in diag_ok
    assert diag_ok["manifest"]["timeZone"] == "Asia/Tokyo"
    assert diag_ok["manifest"]["runtimeVersion"] == "V8"
    assert diag_ok["manifest"]["webapp"]["access"] == "ANYONE_ANONYMOUS"

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        mcp_diag = gas_mcp_server.diagnose("dummy_id")
        assert "[マニフェスト設定 (appsscript.json)]:" in mcp_diag
        assert "Asia/Tokyo" in mcp_diag

    # 2. appsscript.json が不正な JSON の場合 (JSON構文エラー)
    content_bad = {
        "files": [
            {
                "name": "appsscript",
                "type": "JSON",
                "source": "{ timeZone: 'broken_no_quotes' }"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content_bad)
    diag_bad = mock_client.diagnose("dummy_id")
    assert diag_bad["issues_count"] >= 1
    syntax_err_files = [se["file"] for se in diag_bad["syntax_errors"]]
    assert "appsscript" in syntax_err_files

def test_deploy_creates_new_when_no_existing_deployment(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_deployments = MagicMock(return_value=[])  # 既存デプロイなし
    mock_client.create_version = MagicMock(return_value=1)

    # POST /deployments で新規作成されるレスポンス
    res_create = MagicMock()
    res_create.status_code = 200
    res_create.json.return_value = {
        "deploymentId": "new_dep_id_999",
        "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/new_url/exec"}}]
    }
    mock_client._request_with_retry = MagicMock(return_value=res_create)

    res = mock_client.deploy("dummy_id", description="First deploy")
    assert res["status"] == "success"
    assert res["deploymentId"] == "new_dep_id_999"
    assert res["versionNumber"] == 1
    assert res["webAppUrl"] == "https://script.google.com/macros/s/new_url/exec"

    # POST メソッドで呼ばれたことを確認
    call_args = mock_client._request_with_retry.call_args
    assert call_args[0][0] == "POST"
    assert "/deployments" in call_args[0][1]
    assert call_args[1]["json"]["versionNumber"] == 1

def test_projects_list_disk_cache(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(json.dumps({
        "tokens": {"default": {"client_id": "cid", "client_secret": "sec", "refresh_token": "ref"}}
    }), encoding="utf-8")
    cache_file = tmp_path / ".cache.json"

    with patch.object(GasClient, "get_access_token", return_value="dummy_token"):
        # 1つ目のクライアント: API通信を行いディスクキャッシュへ保存
        client1 = GasClient(clasprc_path=str(clasprc), backup_dir=str(tmp_path / ".backups"))
        client1.cache_file = cache_file

        mock_api_res = MagicMock()
        mock_api_res.status_code = 200
        mock_api_res.json.return_value = {
            "files": [
                {"id": "proj_1", "name": "Project Alpha", "modifiedTime": "2026-01-01T00:00:00Z"},
                {"id": "proj_2", "name": "Project Beta", "modifiedTime": "2026-01-02T00:00:00Z"}
            ]
        }
        client1._request_with_retry = MagicMock(return_value=mock_api_res)

        projects1 = client1.list_projects(limit=10)
        assert len(projects1) == 2
        assert client1._request_with_retry.call_count == 1
        assert cache_file.exists()

        # 2つ目のクライアント: 新規インスタンスだが同じ .cache.json を読み、API通信0回で返却
        client2 = GasClient(clasprc_path=str(clasprc), backup_dir=str(tmp_path / ".backups"))
        client2.cache_file = cache_file
        client2._cache_data = client2._load_cache()
        client2._request_with_retry = MagicMock()

        projects2 = client2.list_projects(limit=10)
        assert len(projects2) == 2
        assert projects2[0]["name"] == "Project Alpha"
        # APIリクエストが呼ばれていないこと（ディスクキャッシュヒット）
        client2._request_with_retry.assert_not_called()

def test_mcp_gas_new_subcommands(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="sid_mcp")
    mock_client.get_deployments = MagicMock(return_value=[
        {
            "deploymentId": "dep_mcp",
            "deploymentConfig": {"versionNumber": 5, "description": "mcp test"},
            "updateTime": "2026-03-01T00:00:00Z",
            "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/mcp/exec"}}]
        }
    ])
    mock_client.restore_backup = MagicMock(return_value={
        "status": "success",
        "restored_scope": "project_all",
        "restored_files_count": 3,
        "safety_backup": "safety.json"
    })

    res_mock = MagicMock()
    res_mock.status_code = 200
    res_mock.headers = {"Content-Type": "application/json"}
    res_mock.json.return_value = {"msg": "hello from webapp"}
    res_mock.text = '{"msg": "hello from webapp"}'
    mock_client._request_with_retry = MagicMock(return_value=res_mock)

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. gas("deps ...")
        deps_msg = gas_mcp_server.gas("deps sid_mcp")
        assert "dep_mcp" in deps_msg
        assert "mcp test" in deps_msg

        # 2. gas("restore ...")
        restore_msg = gas_mcp_server.gas("restore sid_mcp dummy_bak.json")
        assert "[SUCCESS] プロジェクト全体復元完了" in restore_msg
        assert "safety.json" in restore_msg

        # 3. gas("webapp ...")
        webapp_msg = gas_mcp_server.gas("webapp https://script.google.com/macros/s/mcp/exec action=ping")
        assert "[SUCCESS HTTP 200]" in webapp_msg
        assert "hello from webapp" in webapp_msg


# ==========================================
# 4大深層アップグレード（深層機能強化）の包括的テスト
# ==========================================

def test_patch_function_scope_isolation(mock_client):
    source = (
        "function firstFunc() {\n"
        "    const count = 10;\n"
        "    return count;\n"
        "}\n\n"
        "function targetFunc() {\n"
        "    const count = 10;\n"
        "    return count * 2;\n"
        "}\n"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # targetFunc 内の count = 10 のみを count = 99 に置換
    res = mock_client.patch_function("dummy_id", "Code", "targetFunc", "const count = 10;", "const count = 99;")
    assert res["status"] == "success"
    assert res["replaced_occurrences"] == 1

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    # firstFunc は変更されていないこと
    assert "function firstFunc() {\n    const count = 10;" in put_source
    # targetFunc は置換されていること
    assert "function targetFunc() {\n    const count = 99;" in put_source

def test_patch_function_patches_json(mock_client):
    source = (
        "function calc() {\n"
        "    let a = 1;\n"
        "    let b = 2;\n"
        "    return a + b;\n"
        "}\n"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    patches_json = json.dumps([
        {"target": "let a = 1;", "replacement": "let a = 100;"},
        {"target": "let b = 2;", "replacement": "let b = 200;"}
    ])
    res = mock_client.patch_function("dummy_id", "Code", "calc", patches=patches_json)
    assert res["status"] == "success"
    assert res["replaced_occurrences"] == 2

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "let a = 100;" in put_source
    assert "let b = 200;" in put_source

def test_patch_function_in_html_script(mock_client):
    source = (
        "<!DOCTYPE html><html><head><script>\n"
        "function onBtnClick() {\n"
        "    console.log('old');\n"
        "}\n"
        "</script></head><body></body></html>"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Index", "type": "HTML", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.patch_function("dummy_id", "Index", "onBtnClick", "console.log('old');", "console.log('new');")
    assert res["status"] == "success"

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "console.log('new');" in put_source
    assert "<!DOCTYPE html>" in put_source

def test_add_function_and_duplicate_guard(mock_client):
    source = "function hello() { return 'hello'; }\n"
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. 既存関数と同名の場合は拒否
    with pytest.raises(ValueError) as exc:
        mock_client.add_function("dummy_id", "Code", "function hello() { return 'dup'; }")
    assert "既に" in str(exc.value)

    # 2. 新規関数の追加
    res = mock_client.add_function("dummy_id", "Code", "function world() {\n    return 'world';\n}")
    assert res["status"] == "success"
    assert res["function"] == "world"

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "function hello()" in put_source
    assert "function world()" in put_source

def test_add_function_html(mock_client):
    source = "<html><head><script>\nfunction init() {}\n</script></head><body></body></html>"
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "page", "type": "HTML", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.add_function("dummy_id", "page", "function onClick() { alert(1); }")
    assert res["status"] == "success"

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "function onClick()" in put_source
    assert "</script>" in put_source

def test_delete_function(mock_client):
    source = (
        "function keepMe() {\n    return 1;\n}\n\n"
        "function removeMe() {\n    return 2;\n}\n\n"
        "function end() {\n    return 3;\n}\n"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": source}]
    })
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.delete_function("dummy_id", "Code", "removeMe")
    assert res["status"] == "success"
    assert res["deleted_function"] == "removeMe"

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "keepMe" in put_source
    assert "end" in put_source
    assert "removeMe" not in put_source

def test_delete_function_not_found(mock_client):
    source = "function a() {}"
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": source}]
    })
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    with pytest.raises(ValueError) as exc:
        mock_client.delete_function("dummy_id", "Code", "nonExistent")
    assert "見つかりません" in str(exc.value)

def test_batch_patch_success(mock_client):
    files = [
        {"name": "CodeA", "type": "SERVER_JS", "source": "function funcA() { return 'A'; }\nfunction funcA2() { return 1; }"},
        {"name": "CodeB", "type": "SERVER_JS", "source": "function funcB() { return 'B'; }"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    ops = [
        {"op": "patch_function", "file": "CodeA", "function": "funcA", "target": "'A'", "replacement": "'AA'"},
        {"op": "add_function", "file": "CodeA", "code": "function funcA3() { return 3; }"},
        {"op": "delete_function", "file": "CodeA", "function": "funcA2"},
        {"op": "patch", "file": "CodeB", "target": "'B'", "replacement": "'BB'"}
    ]
    res = mock_client.batch_patch("dummy_id", ops)
    assert res["status"] == "success"
    assert len(res["applied_operations"]) == 4
    assert set(res["changed_files"]) == {"CodeA", "CodeB"}

    # 通信は1回だけ行われたこと
    assert mock_client._put_content.call_count == 1
    put_files = mock_client._put_content.call_args[0][1]
    code_a = next(f["source"] for f in put_files if f["name"] == "CodeA")
    code_b = next(f["source"] for f in put_files if f["name"] == "CodeB")

    assert "'AA'" in code_a
    assert "funcA3" in code_a
    assert "funcA2" not in code_a
    assert "'BB'" in code_b

def test_batch_patch_dry_run(mock_client):
    files = [{"name": "Code", "type": "SERVER_JS", "source": "function x() { return 1; }"}]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    ops = [{"op": "patch", "file": "Code", "target": "1", "replacement": "2"}]
    res = mock_client.batch_patch("dummy_id", ops, dry_run=True)
    assert res["status"] == "dry_run"
    assert "diff" in res
    # クラウド反映は行われないこと
    mock_client._put_content.assert_not_called()

def test_batch_patch_syntax_error_rollback(mock_client):
    files = [{"name": "Code", "type": "SERVER_JS", "source": "function x() { return 1; }"}]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 意図的な構文エラーを起こす操作
    ops = [{"op": "patch", "file": "Code", "target": "return 1;", "replacement": "return {"}]
    with pytest.raises(ValueError) as exc:
        mock_client.batch_patch("dummy_id", ops)
    assert "構文エラー" in str(exc.value)
    # 反映は阻止されること
    mock_client._put_content.assert_not_called()

def test_list_versions_and_content_cache(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 1. list_versions
    mock_res_v = MagicMock()
    mock_res_v.status_code = 200
    mock_res_v.json.return_value = {
        "versions": [
            {"versionNumber": 2, "description": "Release v2", "createTime": "2026-02-01T00:00:00Z"},
            {"versionNumber": 1, "description": "Initial", "createTime": "2026-01-01T00:00:00Z"}
        ]
    }
    mock_client._request_with_retry = MagicMock(return_value=mock_res_v)

    vers = mock_client.list_versions("dummy_id")
    assert len(vers) == 2
    assert vers[0]["versionNumber"] == 2

    # 2. get_version_content (不変キャッシュの検証)
    mock_res_c = MagicMock()
    mock_res_c.status_code = 200
    mock_res_c.json.return_value = {
        "files": [{"name": "main", "type": "SERVER_JS", "source": "// v2 source"}]
    }
    mock_client._request_with_retry = MagicMock(return_value=mock_res_c)

    content1 = mock_client.get_version_content("dummy_id", 2)
    assert content1["files"][0]["source"] == "// v2 source"
    assert mock_client._request_with_retry.call_count == 1

    # 2回目の取得: API通信をスキップしキャッシュから返却
    mock_client._request_with_retry = MagicMock()
    content2 = mock_client.get_version_content("dummy_id", 2)
    assert content2["files"][0]["source"] == "// v2 source"
    mock_client._request_with_retry.assert_not_called()

def test_diff_version_and_restore_version(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    # HEAD content
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": "function test() { return 20; }"}]
    })
    # Version 1 content
    mock_client.get_version_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": "function test() { return 10; }"}]
    })
    mock_client._put_content = MagicMock()

    # 1. diff_version
    diff_res = mock_client.diff_version("dummy_id", version_number=1)
    assert diff_res["target_version"] == 1
    assert any("Code" in f for f in diff_res["changed_files"])
    assert "-function test() { return 10; }" in diff_res["diff"]
    assert "+function test() { return 20; }" in diff_res["diff"]

    # 2. restore_version
    restore_res = mock_client.restore_version("dummy_id", version_number=1)
    assert restore_res["status"] == "success"
    assert restore_res["target_version"] == 1

    put_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "return 10;" in put_source

def test_resolve_webapp_url_dev_mode(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_deployments = MagicMock(return_value=[
        {
            "deploymentId": "dep_prod",
            "deploymentConfig": {"versionNumber": 5, "description": "Production"},
            "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/prod_url/exec"}}]
        },
        {
            "deploymentId": "dep_dev",
            "deploymentConfig": {"versionNumber": 0, "description": "@HEAD dev deployment"},
            "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/dev_url/dev"}}]
        }
    ])
    # 本番URLの解決
    url_prod = mock_client.resolve_webapp_url("dummy_id", dev=False)
    assert "prod_url" in url_prod

    # 開発モード（dev=True）の解決: versionNumber=0 または @HEAD のURLが選ばれる
    url_dev = mock_client.resolve_webapp_url("dummy_id", dev=True)
    assert "dev_url" in url_dev

def test_run_function_zero_footprint(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/macros/s/dev/exec")
    initial_files = [
        {"name": "appsscript", "type": "JSON", "source": "{}"},
        {"name": "Code", "type": "SERVER_JS", "source": "function myCalc(a, b) { return a + b; }"}
    ]
    curr_files = [dict(f) for f in initial_files]
    def fake_get_content(sid, use_cache=True):
        return {"files": [dict(f) for f in curr_files]}
    def fake_put_content(sid, flist):
        nonlocal curr_files
        curr_files = [dict(f) for f in flist]
        return {"files": curr_files}
    mock_client.get_content = MagicMock(side_effect=fake_get_content)
    mock_client._put_content = MagicMock(side_effect=fake_put_content)

    # executions.run API のモック
    exec_res = MagicMock()
    exec_res.status_code = 200
    exec_res.headers = {"Content-Type": "application/json"}
    exec_res.json.return_value = {
        "ok": True,
        "result": 42,
        "logs": ["[LOG] calculation done"],
        "elapsed_ms": 15
    }
    mock_client._request_with_retry = MagicMock(return_value=exec_res)

    res = mock_client.run_function("dummy_id", "myCalc", args=[20, 22], cleanup=True)
    assert res["status"] == "success"
    assert res["result"] == 42
    assert res["logs"] == ["[LOG] calculation done"]
    assert res["duration_ms"] == 15

    # 1回目はランナー注入で put_content、2回目はランナー削除で put_content
    assert mock_client._put_content.call_count == 2
    # 最終的なファイル群にランナーファイルが残っていないこと（ゼロフットプリント）
    final_files = mock_client._put_content.call_args[0][1]
    assert all("_runner" not in f["name"] for f in final_files)

def test_run_function_with_error(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/macros/s/dev/exec")
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": "function badFunc() {}"}]
    })
    mock_client._put_content = MagicMock()

    exec_res = MagicMock()
    exec_res.status_code = 200
    exec_res.headers = {"Content-Type": "application/json"}
    exec_res.json.return_value = {
        "ok": False,
        "error": "Script error: ReferenceError: x is not defined",
        "stack": "Code:2 (badFunc)",
        "logs": [],
        "elapsed_ms": 5
    }
    mock_client._request_with_retry = MagicMock(return_value=exec_res)

    res = mock_client.run_function("dummy_id", "badFunc", cleanup=True)
    assert res["status"] == "error"
    assert "ReferenceError" in res["error"]

def test_diagnose_deep_duplicate_globals(mock_client):
    files = [
        {"name": "FileA", "type": "SERVER_JS", "source": "const API_KEY = 'AAA';\nclass Service {}"},
        {"name": "FileB", "type": "SERVER_JS", "source": "const API_KEY = 'BBB';\nlet client = null;"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    assert diag["status"] == "warning"
    dup_names = [dg["name"] for dg in diag["duplicate_globals"]]
    assert "API_KEY" in dup_names
    assert diag["issues_count"] >= 1

def test_diagnose_rpc_private_and_arity(mock_client):
    files = [
        {
            "name": "Server",
            "type": "SERVER_JS",
            "source": (
                "function privateApi_() { return 1; }\n"
                "function calculate(x, y) { return x + y; }\n"
            )
        },
        {
            "name": "Index",
            "type": "HTML",
            "source": (
                "<script>\n"
                "google.script.run.privateApi_();\n"
                "google.script.run.calculate(1);\n"
                "</script>"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    # 1. 末尾 _ プライベート関数のRPC呼出検出
    broken_targets = [r["target_function"] for r in diag["broken_rpc_calls"]]
    assert "privateApi_" in broken_targets

    # 2. 引数不一致警告（calculate は2個期待だが1個しか渡していない）
    arity_targets = [a["target_function"] for a in diag["rpc_arity_warnings"]]
    assert "calculate" in arity_targets

def test_diagnose_performance_warnings(mock_client):
    files = [
        {
            "name": "Worker",
            "type": "SERVER_JS",
            "source": (
                "function syncItems(ids) {\n"
                "    for (let i = 0; i < ids.length; i++) {\n"
                "        UrlFetchApp.fetch('https://api.example.com/' + ids[i]);\n"
                "    }\n"
                "}\n"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    assert len(diag["performance_warnings"]) >= 1
    assert "UrlFetchApp.fetch" in diag["performance_warnings"][0]["api"]

def test_diagnose_unused_functions(mock_client):
    files = [
        {
            "name": "Main",
            "type": "SERVER_JS",
            "source": (
                "function doGet() { return render(); }\n"
                "function render() { return 'ok'; }\n"
                "function orphanedLegacyFunction() { return 404; }\n"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    unused_names = [uf["name"] for uf in diag["unused_functions"]]
    # doGet はエントリーポイントなので除外、render は doGet から呼ばれる
    assert "doGet" not in unused_names
    assert "render" not in unused_names
    # orphanedLegacyFunction は未使用として検出
    assert "orphanedLegacyFunction" in unused_names

def test_mcp_patch_function_and_batch_patch(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="sid_mcp")
    mock_client.patch_function = MagicMock(return_value={
        "status": "success",
        "file": "Code",
        "function": "myFn",
        "replaced_occurrences": 1,
        "backup_file": "Code.bak.json",
        "syntax_check": "valid"
    })
    mock_client.batch_patch = MagicMock(return_value={
        "status": "success",
        "applied_operations": [{"op": "patch"}],
        "changed_files": ["Code"],
        "backup_file": "batch.bak.json",
        "syntax_check": "valid"
    })

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. MCP patch_function
        p_res = gas_mcp_server.patch_function("sid_mcp", "Code", "myFn", "target", "replacement")
        assert "[SUCCESS] 関数内置換完了" in p_res
        assert "myFn" in p_res

        # 2. MCP batch_patch
        b_res = gas_mcp_server.batch_patch("sid_mcp", '[{"op":"patch"}]')
        assert "[SUCCESS] アトミック一括反映完了" in b_res
        assert "1操作" in b_res

def test_mcp_versions_and_diff_version(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="sid_mcp")
    mock_client.list_versions = MagicMock(return_value=[
        {"versionNumber": 3, "description": "Release v3", "createTime": "2026-03-01T00:00:00Z"}
    ])
    mock_client.diff_version = MagicMock(return_value={
        "target_version": 3,
        "changed_files": ["main"],
        "diff": "-old\n+new"
    })
    mock_client.restore_version = MagicMock(return_value={
        "status": "success",
        "target_version": 3,
        "restored_scope": "project_all",
        "safety_backup": "safety.json"
    })

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. list_versions
        vers_msg = gas_mcp_server.list_versions("sid_mcp")
        assert "Version 3" in vers_msg

        # 2. diff_version
        diff_msg = gas_mcp_server.diff_version("sid_mcp", version_number=3)
        assert "Version 3" in diff_msg
        assert "+new" in diff_msg

        # 3. restore_version
        res_msg = gas_mcp_server.restore_version("sid_mcp", version_number=3)
        assert "[SUCCESS] バージョン 3 から復元完了" in res_msg

def test_mcp_run_function_and_gas_subcommands(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="sid_mcp")
    mock_client.run_function = MagicMock(return_value={
        "status": "success",
        "function": "addNumbers",
        "result": 15,
        "logs": ["[LOG] sum = 15"],
        "duration_ms": 25
    })
    mock_client.patch_function = MagicMock(return_value={
        "status": "success",
        "file": "Code",
        "function": "f",
        "replaced_occurrences": 1,
        "backup_file": "b.json",
        "syntax_check": "valid"
    })

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. MCP run_function
        run_msg = gas_mcp_server.run_function("sid_mcp", "addNumbers", args="[5, 10]")
        assert "[SUCCESS] 関数実行: addNumbers" in run_msg
        assert "15" in run_msg
        assert "25ms" in run_msg

        # 2. gas("run ...")
        cmd_run_msg = gas_mcp_server.gas("run sid_mcp addNumbers [5,10]")
        assert "[SUCCESS] 関数実行: addNumbers" in cmd_run_msg

        # 3. gas("patch-func ...")
        cmd_pf_msg = gas_mcp_server.gas("patch-func sid_mcp Code f old new")
        assert "[SUCCESS] 関数内置換完了" in cmd_pf_msg


def test_diagnose_local_const_not_flagged_as_global(mock_client):
    content = {
        "files": [
            {
                "name": "file1",
                "type": "SERVER_JS",
                "source": "function f1() { const msg = 'hello'; const localX = 1; return localX; }\n"
            },
            {
                "name": "file2",
                "type": "SERVER_JS",
                "source": "function f2() { const msg = 'world'; const localX = 2; return localX; }\n"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    diag = mock_client.diagnose("dummy_id")
    assert len(diag["duplicate_globals"]) == 0


# ==========================================
# 永続キャッシュ・超高速実行・双方向同期の包括的テスト
# ==========================================

def test_deployments_list_and_dev_url_cache(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "deployments": [
            {
                "deploymentId": "dep_prod",
                "deploymentConfig": {"versionNumber": 1, "description": "Prod v1"},
                "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/prod/exec"}}]
            },
            {
                "deploymentId": "dep_dev",
                "deploymentConfig": {"versionNumber": 0, "description": "@HEAD dev"},
                "entryPoints": [{"webApp": {"url": "https://script.google.com/macros/s/dev/dev"}}]
            }
        ]
    }
    mock_client._request_with_retry = MagicMock(return_value=mock_res)

    # 1. 初回: API 呼び出しを行いメモリ＆ディスクキャッシュへ保存
    deps1 = mock_client.get_deployments("dummy_id", use_cache=True)
    assert len(deps1) == 2
    assert mock_client._request_with_retry.call_count == 1
    assert "dummy_id" in mock_client._cache_data.get("deployments_list", {})

    # 2. 2回目: API通信0回でキャッシュから即返却
    mock_client._request_with_retry = MagicMock()
    deps2 = mock_client.get_deployments("dummy_id", use_cache=True)
    assert len(deps2) == 2
    mock_client._request_with_retry.assert_not_called()

    # 3. resolve_webapp_url(dev=True) で dev_url がキャッシュされ0ms返却
    url_dev1 = mock_client.resolve_webapp_url("dummy_id", dev=True)
    assert "dev/dev" in url_dev1
    # キャッシュされた dev_url を次回は API 呼び出しなしで即返却
    mock_client.get_deployments = MagicMock()
    url_dev2 = mock_client.resolve_webapp_url("dummy_id", dev=True)
    assert url_dev2 == url_dev1
    mock_client.get_deployments.assert_not_called()

    # 4. deploy() 実行時に deployments キャッシュが無効化されること
    dep_res = MagicMock()
    dep_res.status_code = 200
    dep_res.json.return_value = {"deploymentId": "dep_new", "versionNumber": 2}
    mock_client._request_with_retry = MagicMock(return_value=dep_res)
    mock_client.deploy("dummy_id", description="New deploy")
    assert "dummy_id" not in mock_client._cache_data.get("deployments_list", {})
    assert "dummy_id" not in getattr(mock_client, "_deployments_list_cache", {})

def test_version_content_disk_cache(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "files": [{"name": "main", "type": "SERVER_JS", "source": "// version 5 immutable source"}]
    }
    mock_client._request_with_retry = MagicMock(return_value=mock_res)

    # 初回取得: API経由で取得しコンテンツ専用ディスクキャッシュ (.content_cache.json) へ保存
    content1 = mock_client.get_version_content("dummy_id", 5)
    assert content1["files"][0]["source"] == "// version 5 immutable source"
    assert "ver:dummy_id:5" in mock_client._load_disk_content_cache()

    # メモリキャッシュを意図的にクリアしてもディスクキャッシュからAPI通信なしで即返却
    mock_client._version_content_cache.clear()
    mock_client._request_with_retry = MagicMock()

    content2 = mock_client.get_version_content("dummy_id", 5)
    assert content2["files"][0]["source"] == "// version 5 immutable source"
    mock_client._request_with_retry.assert_not_called()

def test_run_function_fast_mode_and_clean_runner(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/macros/s/dev/dev")

    # ランナーが既に設置されている状態のファイル
    runner_source = (
        "function doGet(e) { if (e && e.parameter && e.parameter.__gm_run) return __gm_exec_(e); }\n\n"
        "function __gm_exec_(e) { return ContentService.createTextOutput(JSON.stringify({ok:true,result:'fast_result',elapsed_ms:10})); }\n\n"
        "function calc() { return 100; }\n"
    )
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": runner_source}]
    })
    mock_client._put_content = MagicMock()

    mock_web_res = MagicMock()
    mock_web_res.status_code = 200
    mock_web_res.headers = {"Content-Type": "application/json"}
    mock_web_res.json.return_value = {"ok": True, "result": "fast_result", "elapsed_ms": 10}
    mock_web_res.text = '{"ok": true, "result": "fast_result", "elapsed_ms": 10}'
    mock_client._request_with_retry = MagicMock(return_value=mock_web_res)

    # 1. run_function(fast=True): すでにランナーがあるので _put_content は呼ばれず高速実行
    res = mock_client.run_function("dummy_id", "calc", fast=True)
    assert res["status"] == "success"
    assert res["result"] == "fast_result"
    # PUT content は0回（ランナー注入スキップ）
    mock_client._put_content.assert_not_called()

    # 2. clean_runner: ランナーコードと doGet フックを消去
    clean_res = mock_client.clean_runner("dummy_id")
    assert clean_res["status"] == "cleaned"
    assert clean_res["modified"] is True
    assert mock_client._put_content.call_count == 1

    cleaned_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "__gm_exec_" not in cleaned_source
    assert "calc" in cleaned_source

    # 3. 2回目の clean_runner: 既にクリーンなので _put_content 呼ばれず modified=False
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": cleaned_source}]
    })
    mock_client._put_content = MagicMock()
    clean_res2 = mock_client.clean_runner("dummy_id")
    assert clean_res2["status"] == "clean"
    assert clean_res2["modified"] is False
    mock_client._put_content.assert_not_called()

def test_pull_and_sync_metadata(mock_client, tmp_path):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value={
        "files": [
            {"name": "appsscript", "type": "JSON", "source": '{"timeZone":"Asia/Tokyo"}'},
            {"name": "Code", "type": "SERVER_JS", "source": "function hello() { return 1; }"},
            {"name": "utils/helper", "type": "SERVER_JS", "source": "function help() { return 2; }"},
            {"name": "Index", "type": "HTML", "source": "<h1>Hello</h1>"}
        ]
    })

    local_dir = tmp_path / "my_project"
    res = mock_client.pull("dummy_id", local_dir=str(local_dir), clean=True)
    assert res["status"] == "success"
    assert res["count"] == 4

    # ファイルの実体確認
    assert (local_dir / "appsscript.json").read_text(encoding="utf-8") == '{"timeZone":"Asia/Tokyo"}'
    assert (local_dir / "Code.gs").read_text(encoding="utf-8") == "function hello() { return 1; }"
    assert (local_dir / "utils" / "helper.gs").read_text(encoding="utf-8") == "function help() { return 2; }"
    assert (local_dir / "Index.html").read_text(encoding="utf-8") == "<h1>Hello</h1>"

    # .gas-sync.json メタデータの確認
    sync_file = local_dir / ".gas-sync.json"
    assert sync_file.exists()
    meta = json.loads(sync_file.read_text(encoding="utf-8"))
    assert meta["script_id"] == "dummy_id"
    assert "Code.gs" in meta["files"]

def test_sync_status_and_push(mock_client, tmp_path):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    initial_files = [
        {"name": "appsscript", "type": "JSON", "source": '{"timeZone":"Asia/Tokyo"}'},
        {"name": "Code", "type": "SERVER_JS", "source": "function hello() { return 1; }"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": list(initial_files)})
    mock_client._put_content = MagicMock()

    local_dir = tmp_path / "work_dir"
    mock_client.pull("dummy_id", local_dir=str(local_dir))

    # 1. 変更なしの状態での push: API通信スキップで即 no_changes
    mock_client._put_content = MagicMock()
    push_res = mock_client.push(local_dir=str(local_dir))
    assert push_res["status"] == "no_changes"
    mock_client._put_content.assert_not_called()

    # 2. ローカルでファイルを修正および追加
    (local_dir / "Code.gs").write_text("function hello() { return 999; }", encoding="utf-8")
    (local_dir / "NewModule.gs").write_text("function brandNew() { return 'ok'; }", encoding="utf-8")

    # sync_status の確認
    st = mock_client.sync_status(local_dir=str(local_dir))
    assert "Code.gs" in st["modified"]
    assert "NewModule.gs" in st["added"]
    assert "-function hello() { return 1; }" in st["diff"]
    assert "+function hello() { return 999; }" in st["diff"]

    # 3. dry-run の検証: クラウド反映されずに差分のみ返却
    mock_client._put_content = MagicMock()
    dry_res = mock_client.push(local_dir=str(local_dir), dry_run=True)
    assert dry_res["status"] == "dry_run"
    assert "Code.gs" in dry_res["changed_files"]
    mock_client._put_content.assert_not_called()

    # 4. push の本番反映: 構文検査を経て1回の _put_content でアトミック反映
    push_res2 = mock_client.push(local_dir=str(local_dir))
    assert push_res2["status"] == "success"
    assert mock_client._put_content.call_count == 1
    put_files = mock_client._put_content.call_args[0][1]
    put_names = [f["name"] for f in put_files]
    assert "Code" in put_names
    assert "NewModule" in put_names
    assert "appsscript" in put_names

def test_push_syntax_error_guard(mock_client, tmp_path):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value={
        "files": [{"name": "Code", "type": "SERVER_JS", "source": "function ok() {}"}]
    })
    mock_client._put_content = MagicMock()

    local_dir = tmp_path / "bad_syntax_dir"
    local_dir.mkdir()
    (local_dir / ".gas-sync.json").write_text(json.dumps({"script_id": "dummy_id"}), encoding="utf-8")
    # 意図的な構文エラー
    (local_dir / "Code.gs").write_text("function broken( { return ;", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        mock_client.push(local_dir=str(local_dir), force=False)
    assert "構文エラー" in str(exc.value)
    # クラウド反映は阻止されること
    mock_client._put_content.assert_not_called()

def test_mcp_sync_tools_and_clean_runner(mock_client, tmp_path):
    mock_client.resolve_script_id = MagicMock(return_value="sid_mcp")
    mock_client.pull = MagicMock(return_value={
        "status": "success",
        "script_id": "sid_mcp",
        "local_dir": str(tmp_path),
        "pulled_files": ["Code.gs"],
        "count": 1
    })
    mock_client.clean_runner = MagicMock(return_value={
        "status": "cleaned",
        "modified": True,
        "script_id": "sid_mcp",
        "backup_file": "clean.bak.json"
    })

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # 1. MCP pull_project
        p_res = gas_mcp_server.pull_project("sid_mcp", local_dir=str(tmp_path))
        assert "[SUCCESS]" in p_res
        assert "Code.gs" in p_res

        # 2. MCP clean_runner
        c_res = gas_mcp_server.clean_runner("sid_mcp")
        assert "[SUCCESS] 実行ランナーを除去しました" in c_res

        # 3. gas("clean-runner ...")
        cmd_c_res = gas_mcp_server.gas("clean-runner sid_mcp")
        assert "[SUCCESS] 実行ランナーを除去しました" in cmd_c_res


def test_pull_push_crlf_and_folder_arg_auto_detect(mock_client, tmp_path):
    sid = "1234567890123456789012345678901234"
    content = {
        "files": [
            {"name": "appsscript", "type": "JSON", "source": "{\r\n  \"timeZone\": \"Asia/Tokyo\"\r\n}\r\n"},
            {"name": "main", "type": "SERVER_JS", "source": "function hello() {\r\n  return 1;\r\n}\r\n"}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()

    sync_dir = tmp_path / "my_sync_project"
    pull_res = mock_client.pull(sid, local_dir=str(sync_dir))
    assert pull_res["count"] == 2

    # ローカルファイルを Windows CRLF で上書き保存しても内容が同じなら unchanged になること
    main_gs = sync_dir / "main.gs"
    with open(main_gs, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("function hello() {\n  return 1;\n}\n")

    # 第1引数にフォルダパスのみを渡しても .gas-sync.json から自動解決されること
    st = mock_client.sync_status(str(sync_dir))
    assert st["script_id"] == sid
    assert len(st["modified"]) == 0
    assert len(st["unchanged"]) == 2

    push_res = mock_client.push(str(sync_dir))
    assert push_res["status"] == "no_changes"
    mock_client._put_content.assert_not_called()


def test_batch_patch_same_name_gs_and_html_and_duplicate_add_guard(mock_client):
    sid = "1234567890123456789012345678901234"
    content = {
        "files": [
            {"name": "index", "type": "SERVER_JS", "source": "function doGet() { return 1; }\n"},
            {"name": "index", "type": "HTML", "source": "<html><script>function init() { return 1; }</script></html>\n"}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()

    # 同名 index.gs と index.html を同時に batch_patch しても衝突せず成功すること
    res = mock_client.batch_patch(sid, [
        {"op": "patch_function", "file": "index.gs", "function": "doGet", "target": "return 1;", "replacement": "return 2;"},
        {"op": "patch_function", "file": "index.html", "function": "init", "target": "return 1;", "replacement": "return 2;"}
    ])
    assert res["status"] == "success"
    assert len(res["changed_files"]) == 2

    # batch_patch 内の add_function でも既存関数の重複追加が阻止されること
    with pytest.raises(ValueError, match="既に"):
        mock_client.batch_patch(sid, [
            {"op": "add_function", "file": "index.gs", "code": "function doGet() { return 99; }"}
        ])


def test_mcp_gas_gateway_full_subcommands_and_flags(mock_client):
    mock_client.patch_code = MagicMock(return_value={
        "status": "dry_run", "file": "Code", "replaced_occurrences": 2, "syntax_check": "valid", "diff": "+x"
    })
    mock_client.patch_function = MagicMock(return_value={
        "status": "dry_run", "file": "Code", "function": "fn", "replaced_occurrences": 1, "syntax_check": "valid", "diff": "+y"
    })
    mock_client.replace_function = MagicMock(return_value={
        "status": "dry_run", "file": "Code", "function": "fn", "syntax_check": "valid", "diff": "+z"
    })

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        m1 = gas_mcp_server.gas("patch myproj Code old new -a --dry-run")
        assert "[DRY-RUN]" in m1
        mock_client.patch_code.assert_called_once_with("myproj", "Code", target="old", replacement="new", replace_all=True, force=False, dry_run=True, patches=None, deploy=False)

        m2 = gas_mcp_server.gas("patch-func myproj Code fn old new --dry-run")
        assert "[DRY-RUN]" in m2
        mock_client.patch_function.assert_called_once_with("myproj", "Code", "fn", target="old", replacement="new", replace_all=False, force=False, dry_run=True, patches=None, deploy=False)

        m3 = gas_mcp_server.gas("replace-func myproj Code fn 'function fn(){}' --dry-run")
        assert "[DRY-RUN]" in m3
        mock_client.replace_function.assert_called_once_with("myproj", "Code", "fn", "function fn(){}", force=False, dry_run=True, deploy=False)


def test_benchmark_function_pass_and_needs_improvement_and_failed(mock_client):
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    # 1. ループ内 getValue がある低速コード -> NEEDS_IMPROVEMENT ＆ 処方箋生成
    slow_files = [
        {
            "name": "SheetWorker",
            "type": "SERVER_JS",
            "source": (
                "function sumSheet() {\n"
                "  var s = SpreadsheetApp.getActiveSheet();\n"
                "  var total = 0;\n"
                "  for (var i = 1; i <= 100; i++) {\n"
                "    total += s.getRange(i, 1).getValue();\n"
                "  }\n"
                "  return total;\n"
                "}\n"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": slow_files})
    mock_client.run_function = MagicMock(return_value={
        "status": "success",
        "function": "sumSheet",
        "result": 5050,
        "logs": ["[LOG] done"],
        "duration_ms": 1800
    })

    b1 = mock_client.benchmark_function("dummy_id", "sumSheet", target_ms=500, expected=5050)
    assert b1["verdict"] == "NEEDS_IMPROVEMENT"
    assert b1["score"] < 100
    assert b1["expected_match"] is True
    assert any("getValues()" in p for p in b1["prescriptions"])
    assert any("速度超過" in p for p in b1["prescriptions"])

    # 2. 配列一括化＋UrlFetchApp.fetchAll に改修した高速コード -> PASS (100点)
    fast_files = [
        {
            "name": "SheetWorker",
            "type": "SERVER_JS",
            "source": (
                "function sumSheet() {\n"
                "  var vals = SpreadsheetApp.getActiveSheet().getDataRange().getValues();\n"
                "  var reqs = vals.map(function(r){ return {url: 'https://example.com/' + r[0]}; });\n"
                "  UrlFetchApp.fetchAll(reqs);\n"
                "  return 5050;\n"
                "}\n"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": fast_files})
    mock_client.run_function = MagicMock(return_value={
        "status": "success",
        "function": "sumSheet",
        "result": 5050,
        "logs": [],
        "duration_ms": 120
    })

    b2 = mock_client.benchmark_function("dummy_id", "sumSheet", target_ms=500, expected=5050)
    assert b2["verdict"] == "PASS"
    assert b2["score"] == 100
    assert len(b2["performance_warnings"]) == 0

    # 3. 期待値不一致 -> FAILED (0点)
    b3 = mock_client.benchmark_function("dummy_id", "sumSheet", target_ms=500, expected=9999)
    assert b3["verdict"] == "FAILED"
    assert b3["score"] == 0
    assert b3["expected_match"] is False

    # 4. MCP benchmark_function ＆ gas("bench ...") 統合コマンド検証
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        mcp_out = gas_mcp_server.gas("bench dummy_id sumSheet --target-ms 500 --expected 5050")
        assert "[PASS] (スコア: 100/100点)" in mcp_out
        assert "120.0ms" in mcp_out



def test_diagnose_105_dynamic_rpc_and_heavy_apis_and_frontend_warnings(mock_client):
    server_js = """
    function deleteMessage(id) {
        return id;
    }
    function restoreMessage(id) {
        return id;
    }
    function replyToEmail(threadId, toAddress, subjectText, bodyText) {
        return bodyText;
    }
    function heavyLoop(threads) {
        threads.forEach(t => {
            const atts = t.getAttachments();
            const pb = t.getPlainBody();
            const b64 = Utilities.base64Encode("abc");
        });
    }
    """
    html_code = """
    <html><body>
    <button onclick="nonExistentFunc()">Click</button>
    <script>
    function runDynamicRpc(id, actionType) {
        const gasMethod = (actionType === 'delete') ? 'deleteMessage' : 'restoreMessage';
        google.script.run.withFailureHandler(() => {})[gasMethod](id, null, true);
    }
    function renderIframe() {
        doc.write("<div>test</div>");
    }
    async function saveToDB(items) {
        const db = await openDB();
        const tx = db.transaction('store', 'readwrite');
        items.forEach(i => tx.objectStore('store').put(i));
    }
    </script>
    </body></html>
    """
    files = [
        {"name": "appsscript", "type": "JSON", "source": "{}"},
        {"name": "コード", "type": "SERVER_JS", "source": server_js},
        {"name": "Index", "type": "HTML", "source": html_code}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")

    assert diag["status"] == "warning"
    assert diag["issues_count"] > 0

    assert len(diag["broken_rpc_calls"]) == 0
    assert len(diag["rpc_arity_warnings"]) == 2
    arity_fns = [ra["target_function"] for ra in diag["rpc_arity_warnings"]]
    assert "deleteMessage" in arity_fns
    assert "restoreMessage" in arity_fns

    perf_apis = [pw["api"] for pw in diag["performance_warnings"]]
    assert any("getAttachments" in a for a in perf_apis)
    assert any("getPlainBody" in a for a in perf_apis)
    assert any("base64Encode" in a for a in perf_apis)

    unused_p_names = [up["param"] for up in diag["unused_params"]]
    assert "toAddress" in unused_p_names
    assert "subjectText" in unused_p_names

    fe_kinds = [fw["kind"] for fw in diag["frontend_warnings"]]
    assert "indexeddb_no_clear_or_delete" in fe_kinds
    assert "iframe_document_write" in fe_kinds
    assert "broken_inline_handler" in fe_kinds


def test_diagnose_105_2_loop_boundary_and_guarded_apis_no_false_positives(mock_client):
    server_js = """
    function replyToEmail(threadId, attachmentFiles) {
        if (attachmentFiles && attachmentFiles.length > 0) {
            const mapped = attachmentFiles.map(att => {
                return { name: att.name, size: att.size };
            });
        }
        // ループの外（後ろ）にある thread.getMessages() は誤爆しないこと
        const thread = GmailApp.getThreadById(threadId);
        const msgs = thread.getMessages();
        return msgs.length;
    }

    function checkAttachments(msgs) {
        for (let j = 0; j < msgs.length; j++) {
            const m = msgs[j];
            // break 付きの早期終了ループ内の getAttachments は誤爆しないこと
            const atts = m.getAttachments();
            if (atts.length > 0) {
                break;
            }
        }
    }

    function fallbackBody(msg) {
        // body ? '' : msg.getPlainBody() のフォールバックは誤爆しないこと
        const body = msg.getBody();
        const plain = body ? '' : msg.getPlainBody();
        return plain;
    }
    """
    files = [
        {"name": "appsscript", "type": "JSON", "source": "{}"},
        {"name": "コード", "type": "SERVER_JS", "source": server_js}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    diag = mock_client.diagnose("dummy_id")
    perf_apis = [pw["api"] for pw in diag["performance_warnings"]]
    assert not any("getMessages" in a for a in perf_apis)
    assert not any("getAttachments" in a for a in perf_apis)
    assert not any("getPlainBody" in a for a in perf_apis)
    assert len(diag["performance_warnings"]) == 0


def test_verify_frontend_indexeddb_lifecycle(mock_client):
    broken_html = """
    <html><body><script>
    function openDB() {
        return new Promise(resolve => {
            const req = indexedDB.open('test_db', 1);
            req.onsuccess = e => resolve(e.target.result);
        });
    }
    async function saveToDB(items) {
        const db = await openDB();
        const tx = db.transaction('store', 'readwrite');
        items.forEach(i => tx.objectStore('store').put(i));
    }
    async function loadFromDB() {
        const db = await openDB();
        return new Promise(resolve => {
            const req = db.transaction('store', 'readonly').objectStore('store').getAll();
            req.onsuccess = e => resolve(e.target.result);
        });
    }
    </script></body></html>
    """
    mock_client.get_content = MagicMock(return_value={"files": [{"name": "Index", "type": "HTML", "source": broken_html}]})
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    test_js_check = """
    await saveToDB([{id:'1'}, {id:'2'}]);
    await saveToDB([{id:'1'}]);
    const r = await loadFromDB();
    if (r.length !== 1) {
        throw new Error('Zombie records detected: count=' + r.length);
    }
    return r.length;
    """
    res_broken = mock_client.verify_frontend("dummy_id", "Index", test_js=test_js_check)
    assert res_broken["success"] is False
    assert "Zombie records detected" in res_broken["error"]

    fixed_html = broken_html.replace(
        "items.forEach(i => tx.objectStore('store').put(i));",
        "const st = tx.objectStore('store'); st.clear(); items.forEach(i => st.put(i));"
    )
    mock_client.get_content = MagicMock(return_value={"files": [{"name": "Index", "type": "HTML", "source": fixed_html}]})

    res_fixed = mock_client.verify_frontend("dummy_id", "Index", test_js=test_js_check)
    assert res_fixed["success"] is True
    assert res_fixed["test_result"] == 1
    assert res_fixed["db_records_count"] == 1


def test_patch_code_with_dev_mode_and_cache_ttl(mock_client):
    content = {
        "files": [
            {"name": "Index", "type": "HTML", "source": "<div>hello</div>"}
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/macros/s/dummy_id/dev")
    mock_client.deploy = MagicMock()

    # patch_code with dev=True (deploy は呼ばれず、dev_url が返ること)
    res = mock_client.patch_code("dummy_id", "Index", "<div>hello</div>", "<div>world</div>", dev=True)
    assert res["status"] == "success"
    assert res.get("dev_mode") is True
    assert res.get("dev_url") == "https://script.google.com/macros/s/dummy_id/dev"
    mock_client.deploy.assert_not_called()
    mock_client.resolve_webapp_url.assert_called_once_with("dummy_id", dev=True)


def test_inspect_ui_offline_and_mcp_command(mock_client):
    content = {
        "files": [
            {
                "name": "Index",
                "type": "HTML",
                "source": "<html><body><h1 style='color:#ffffff;background:#000000;'>OK Title</h1></body></html>"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    # 実機 Playwright の inspect_ui を直接実行テスト
    res = mock_client.inspect_ui("dummy_id", filename="Index", theme="white", screenshot=False, check_contrast=True)
    assert res["success"] is True
    assert res["contrast_passed"] is True
    assert res["total_elements_checked"] >= 1
    assert len(res["dangers"]) == 0

    # gas_mcp_server 経由のコマンド呼び出し
    with patch("gas_mcp_server.get_client", return_value=mock_client):
        out = gas_mcp_server.gas("inspect-ui dummy_id Index --theme dark")
        assert "inspect_ui" in out
        assert "[PASS]" in out


def test_xray_offline_and_mcp_command(mock_client):
    content = {
        "files": [
            {
                "name": "Index",
                "type": "HTML",
                "source": """<!DOCTYPE html>
<html>
<body>
  <button id="sendBtn" onclick="handleClick()">送信</button>
  <button id="deadBtn">未実装</button>
  <script>
    function handleClick() {
      google.script.run.withSuccessHandler(res => console.log(res)).serverApiFunc();
    }
  </script>
</body>
</html>"""
            },
            {
                "name": "Code",
                "type": "SERVER_JS",
                "source": """function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index');
}

function serverApiFunc() {
  return "OK";
}

function unusedServerFunc(dummy) {
  return "Dead";
}
"""
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")

    res = mock_client.xray("dummy_id", filename="Index")
    assert res["status"] == "healthy"
    assert len(res["ghost_rpcs"]) == 0
    assert len(res["dead_server_functions"]) == 1
    assert res["dead_server_functions"][0]["name"] == "unusedServerFunc"
    assert len(res["ui_call_paths"]) == 2
    assert res["ui_call_paths"][0]["front_handler"] == "handleClick"
    assert res["ui_call_paths"][0]["rpc_calls"] == ["serverApiFunc"]
    assert res["ui_call_paths"][1]["front_handler"] == "(none)"
    assert "レントゲン解析" in res["markdown_report"]

    with patch("gas_mcp_server.get_client", return_value=mock_client):
        # MCP ツール関数 xray
        out = gas_mcp_server.xray("dummy_id")
        assert "serverApiFunc" in out
        assert "unusedServerFunc" in out

        # gas() コマンドディスパッチャ
        out_gas = gas_mcp_server.gas("xray dummy_id")
        assert "serverApiFunc" in out_gas


def test_clone_web_offline(mock_client):
    mock_html = "<html><head><title>Test Tool</title></head><body><h1>Hello</h1></body></html>"
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = mock_html
        mock_resp.status_code = 200
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        mock_client.create_project = MagicMock(return_value={"scriptId": "new_sid", "title": "Test Tool"})
        mock_client.resolve_script_id = MagicMock(side_effect=ValueError("Not found"))
        mock_client._put_content = MagicMock()
        mock_client.deploy = MagicMock(return_value={"webAppUrl": "https://script.google.com/macros/s/new_sid/exec"})
        mock_client.xray = MagicMock(return_value={"markdown_report": "🟢 [HEALTHY]"})

        res = mock_client.clone_web("https://example.com/tool", project_name="Test Tool", deploy=True)
        assert res["status"] == "success"
        assert res["script_id"] == "new_sid"
        assert res["webapp_url"] == "https://script.google.com/macros/s/new_sid/exec"
        mock_client.create_project.assert_called_once_with("Test Tool")
        mock_client._put_content.assert_called_once()
        mock_client.deploy.assert_called_once()


def test_clean_dead_offline(mock_client):
    mock_client.xray = MagicMock(return_value={
        "dead_server_functions": [
            {"name": "deadFn", "file": "Code", "line": 5}
        ],
        "markdown_report": "🟢 [HEALTHY]"
    })
    content = {
        "files": [
            {
                "name": "Code",
                "type": "SERVER_JS",
                "source": "function liveFn() {\n  return 1;\n}\n\nfunction deadFn() {\n  return 2;\n}\n"
            }
        ]
    }
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client._save_backup = MagicMock(return_value="backup/path")
    mock_client._put_content = MagicMock()
    mock_client._validate_syntax = MagicMock(return_value="valid")

    # dry-run テスト
    res_dry = mock_client.clean_dead("dummy_id", dry_run=True)
    assert res_dry["status"] == "dry_run"
    assert res_dry["deleted_count"] == 1
    mock_client._put_content.assert_not_called()

    # 本番削除テスト（名指しで削除）
    res = mock_client.clean_dead("dummy_id", dry_run=False, names=["deadFn"])
    assert res["status"] == "success"
    assert res["deleted_count"] == 1
    mock_client._put_content.assert_called_once()


def test_trace_rpc_offline(mock_client, tmp_path):
    """REA trace_rpc のオフライン検証"""
    html_content = """
    <!DOCTYPE html>
    <html>
      <body>
        <script>
          window.addEventListener('load', () => {
            google.script.run.withSuccessHandler(res => {
              document.body.setAttribute('data-loaded', 'true');
            }).getUserInfo();
          });
        </script>
      </body>
    </html>
    """
    mock_file = tmp_path / "mock.json"
    res = mock_client.trace_rpc(
        filename=str(tmp_path / "index.html"),
        duration_sec=0.5,
        mock_data={"getUserInfo": {"user": "test_user"}},
        save_mock=True,
        mock_file=str(mock_file)
    )
    # playwright があればキャプチャ成功
    if res.get("success"):
        assert res["total_captured"] >= 1
        assert "getUserInfo" in res["unique_rpcs"]
        assert mock_file.exists()


def test_diff_behavior_offline(mock_client):
    """REA diff_behavior の破壊的変更検知検証"""
    # ベース: 旧バージョン
    base_content = {
        "files": [
            {"name": "Code", "type": "SERVER_JS", "source": "function deleteMsg(id) {}\nfunction getList(cnt) {}"},
            {"name": "Index", "type": "HTML", "source": "<script>google.script.run.deleteMsg(1); google.script.run.getList(10);</script>"}
        ]
    }
    # 現在: deleteMsg が削除され、getList の必須引数が 1 -> 2 に増加
    curr_content = {
        "files": [
            {"name": "Code", "type": "SERVER_JS", "source": "function getList(cnt, mode) {}"},
            {"name": "Index", "type": "HTML", "source": "<script>google.script.run.deleteMsg(1); google.script.run.getList(10);</script>"}
        ]
    }
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value=curr_content)
    mock_client.get_version_content = MagicMock(return_value=base_content)

    res = mock_client.diff_behavior("dummy_id", base_version=1)
    assert res["success"] is True
    assert res["status"] == "BREAKING"
    assert res["breaking_count"] >= 1
    # 削除関数呼び出しと引数不足の検知確認
    types = [b["type"] for b in res["breaking_changes"]]
    assert "REMOVED_FUNCTION_CALLED" in types or "INSUFFICIENT_ARGUMENTS" in types


def test_build_ledger_offline(mock_client):
    """REA build_ledger のモダン要件採点検証"""
    modern_content = {
        "files": [
            {
                "name": "Code",
                "type": "SERVER_JS",
                "source": "function doGet() {}\nfunction getData() {\n  try {\n    return { success: true };\n  } catch(e) {\n    return { error: e.message };\n  }\n}"
            },
            {
                "name": "Index",
                "type": "HTML",
                "source": """
                <!DOCTYPE html>
                <html>
                  <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                      :root { --bg: #fff; }
                      body.dark-mode { --bg: #000; }
                      @media (max-width: 600px) { body { font-size: 14px; } }
                    </style>
                  </head>
                  <body>
                    <span id="syncBadge">同期中</span>
                    <script>
                      const req = indexedDB.open('test_db', 1);
                      function load() {
                        google.script.run.withSuccessHandler(r => {}).withFailureHandler(e => {}).getData();
                      }
                    </script>
                  </body>
                </html>
                """
            }
        ]
    }
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value=modern_content)

    res = mock_client.build_ledger("dummy_id")
    assert res["success"] is True
    assert res["score"] == 100
    assert res["grade"] == "GOLD"
    assert res["passed_requirements"] == 7



def test_design_skin_presets_and_injection(mock_client):
    """skin コマンドの全プリセット適用と6大視覚レイヤーCSS変数注入の検証"""
    base_html = """<!DOCTYPE html>
    <html>
      <head>
        <style>
          :root {
            --bg: #000;
            --text: #fff;
          }
          [data-theme="light"] {
            --bg: #fff;
            --text: #000;
          }
        </style>
      </head>
      <body><h1>App</h1></body>
    </html>
    """
    sample_content = {
        "files": [
            {"name": "appsscript", "type": "JSON", "source": "{}"},
            {"name": "Index", "type": "HTML", "source": base_html}
        ]
    }
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value=sample_content)
    mock_client.patch_code = MagicMock(return_value={"success": True})

    # 1. linear プリセット
    res_linear = mock_client.design_skin("dummy_id", preset="linear")
    assert res_linear["success"] is True
    assert res_linear["preset"] == "linear"
    assert "Linear" in res_linear["preset_name"]

    # patch_code への引数検証
    called_kwargs = mock_client.patch_code.call_args[1]
    import json
    patches = json.loads(called_kwargs["patches"])
    assert len(patches) == 2  # :root と [data-theme="light"]
    # 6大視覚レイヤーのキーワード検証
    root_replacement = patches[0]["replacement"]
    assert "--font-sans" in root_replacement
    assert "--surface" in root_replacement
    assert "--shadow-float" in root_replacement
    assert "--radius-container" in root_replacement
    assert "--transition-fast" in root_replacement

    # 2. glass プリセット
    res_glass = mock_client.design_skin("dummy_id", preset="glass")
    assert res_glass["success"] is True
    assert res_glass["preset"] == "glass"
    assert "--glass-blur" in json.loads(mock_client.patch_code.call_args[1]["patches"])[0]["replacement"]

    # 3. notion プリセット
    res_notion = mock_client.design_skin("dummy_id", preset="notion")
    assert res_notion["success"] is True
    assert res_notion["preset"] == "notion"

    # 4. emerald プリセット
    res_emerald = mock_client.design_skin("dummy_id", preset="emerald")
    assert res_emerald["success"] is True
    assert res_emerald["preset"] == "emerald"
    assert "#10b981" in json.loads(mock_client.patch_code.call_args[1]["patches"])[0]["replacement"]


def test_design_skin_no_root_fallback(mock_client):
    """既存 :root が無いHTMLでも <style> の直後に自動生成されることを検証"""
    raw_html = """<!DOCTYPE html>
    <html>
      <head>
        <style>
          body { margin: 0; }
        </style>
      </head>
      <body>Hello</body>
    </html>"""
    content = {
        "files": [
            {"name": "Index", "type": "HTML", "source": raw_html}
        ]
    }
    mock_client.resolve_script_id = MagicMock(return_value="dummy_id")
    mock_client.get_content = MagicMock(return_value=content)
    mock_client.patch_code = MagicMock(return_value={"success": True})

    res = mock_client.design_skin("dummy_id", preset="linear")
    assert res["success"] is True
    patches = json.loads(mock_client.patch_code.call_args[1]["patches"])
    assert len(patches) >= 1
    assert ":root" in patches[0]["replacement"]


# --- 106: clean_dead と clone_web の安全化テスト ---

def test_xray_and_clean_dead_suspect_protection(mock_client):
    """指示書106: 模擬プロジェクトで dead_server_functions が trulyDead の1件だけで、残りが suspect または entry_point であることを検証"""
    server_code = """
function onOpen() { SpreadsheetApp.getUi().createMenu('秀').addItem('集計', 'runSummary').addToUi(); }
function runSummary() { return 1; }
function setup() { ScriptApp.newTrigger('dailySync').timeBased().everyDays(1).create(); }
function dailySync() { return 2; }
/** @customfunction */
function MYTAX(x) { return x * 1.1; }
function toRow(r) { return r; }
function useCallback(rows) { return rows.map(toRow); }
function onFormSubmit(e) { return e; }
function trulyDead(a) { return a; }
"""
    files = [
        {"name": "コード", "type": "SERVER_JS", "source": server_code},
        {"name": "Index", "type": "HTML", "source": "<html><body></body></html>"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="mock_id_106")

    # 1. xray 実行
    xray_res = mock_client.xray("mock_id_106")
    dead_names = [d["name"] for d in xray_res["dead_server_functions"]]
    assert dead_names == ["trulyDead"]

    classification = xray_res["server_classification"]
    assert classification["onOpen"] == "entry_point"
    assert classification["onFormSubmit"] == "entry_point"
    assert classification["runSummary"] == "suspect"
    assert classification["setup"] == "suspect"
    assert classification["dailySync"] == "suspect"
    assert classification["MYTAX"] == "suspect"
    assert classification["toRow"] == "suspect"
    assert classification["useCallback"] == "suspect"
    assert classification["trulyDead"] == "dead_code"

    # 2. clean_dead(dry_run=True) の検証
    clean_res = mock_client.clean_dead("mock_id_106", dry_run=True)
    assert clean_res["status"] == "dry_run"
    assert clean_res["deleted_count"] == 1
    assert [d["name"] for d in clean_res["dead_functions"]] == ["trulyDead"]
    notice_text = "Apps Script の画面で作ったトリガー・シートの式から呼ぶ関数は、コードからは見えません。消す前に［トリガー］画面とシートの式を確かめてください。"
    assert notice_text in clean_res["markdown_report"]


def test_clean_dead_apply_requires_names(mock_client):
    """指示書106: clean_dead の本番 apply で names の名指しがない場合は何も消さない"""
    server_code = "function trulyDead(a) { return a; }"
    files = [
        {"name": "コード", "type": "SERVER_JS", "source": server_code},
        {"name": "Index", "type": "HTML", "source": "<html></html>"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="mock_id_106")
    mock_client._put_content = MagicMock()

    # dry_run=False で names=None または空
    res = mock_client.clean_dead("mock_id_106", dry_run=False, names=None)
    assert res["status"] == "error"
    assert "dry_run で出た名前から選んで names に渡してください" in res["message"]
    mock_client._put_content.assert_not_called()


def test_clean_dead_suspect_protection_without_force(mock_client):
    """指示書106: suspect の関数を名指ししても force=True なしでは消さない"""
    server_code = """
function setup() { ScriptApp.newTrigger('dailySync').timeBased().everyDays(1).create(); }
function dailySync() { return 2; }
function trulyDead(a) { return a; }
"""
    files = [
        {"name": "コード", "type": "SERVER_JS", "source": server_code},
        {"name": "Index", "type": "HTML", "source": "<html></html>"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="mock_id_106")
    mock_client._put_content = MagicMock()
    mock_client._save_backup = MagicMock(return_value="mock_backup.json")

    # dailySync (suspect) を名指し、force=False ➔ エラーで消さない
    res = mock_client.clean_dead("mock_id_106", dry_run=False, names=["dailySync"], force=False)
    assert res["status"] == "error"
    assert "suspect" in res["message"]
    mock_client._put_content.assert_not_called()

    # trulyDead (dead_code) を名指し ➔ 正常削除
    res_ok = mock_client.clean_dead("mock_id_106", dry_run=False, names=["trulyDead"], force=False)
    assert res_ok["status"] == "success"
    assert res_ok["deleted_count"] == 1
    mock_client._put_content.assert_called_once()


def test_clone_web_defaults_myself_and_no_deploy(mock_client):
    """指示書106: clone_web の既定が access: 'MYSELF' で未デプロイであることを検証"""
    mock_client.resolve_script_id = MagicMock(side_effect=ValueError("not found"))
    mock_client.create_project = MagicMock(return_value={"scriptId": "new_cloned_id"})
    mock_client._put_content = MagicMock()
    mock_client.deploy = MagicMock()
    mock_client.xray = MagicMock(return_value={"markdown_report": "OK"})

    mock_bundle = {
        "title": "Test LP",
        "server_code": "function doGet() {}",
        "html": "<html><body>Hello</body></html>",
        "inlined_css_count": 1,
        "inlined_js_count": 0,
        "rewritten_links_count": 0,
        "total_html_length": 100
    }
    with patch.object(mock_client, "_bundle_web_page", return_value=mock_bundle):
        res = mock_client.clone_web("https://example.com/lp")

    assert res["status"] == "success"
    assert res["access"] == "MYSELF"
    assert res["webapp_url"] is None
    mock_client.deploy.assert_not_called()

    # _put_content に渡されたマニフェストを検証
    put_files = mock_client._put_content.call_args[0][1]
    manifest_file = next(f for f in put_files if f["name"] == "appsscript")
    manifest_data = json.loads(manifest_file["source"])
    assert manifest_data["webapp"]["access"] == "MYSELF"


# --- 107: ランナーと認証トークンの穴を塞ぐテスト ---

def test_107_1_deploy_cleans_runner_before_versioning(mock_client):
    """指示書107-1: deploy() は HEAD に __gm_exec_ が残っていれば版を作る前に clean_runner で取り除く"""
    runner_code = "function doGet(e) { return __gm_exec_(e); }\nfunction __gm_exec_(e) { return 1; }"
    files = [
        {"name": "appsscript", "type": "JSON", "source": "{}"},
        {"name": "コード", "type": "SERVER_JS", "source": runner_code}
    ]
    mock_client.resolve_script_id = MagicMock(return_value="mock_id_107")
    mock_client.create_version = MagicMock(return_value=1)
    mock_client.get_deployments = MagicMock(return_value=[{"deploymentId": "dep1", "deploymentConfig": {"versionNumber": 1}}])
    mock_client._request_with_retry = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"deploymentId": "dep1"}))

    cleaned = False
    def fake_get_content(sid, use_cache=True):
        nonlocal cleaned
        if cleaned:
            return {"files": [{"name": "コード", "type": "SERVER_JS", "source": "function doGet(e) { return 1; }"}]}
        return {"files": [{"name": "コード", "type": "SERVER_JS", "source": runner_code}]}

    def fake_clean_runner(sid):
        nonlocal cleaned
        cleaned = True

    mock_client.get_content = MagicMock(side_effect=fake_get_content)
    mock_client.clean_runner = MagicMock(side_effect=fake_clean_runner)

    res = mock_client.deploy("mock_id_107")
    mock_client.clean_runner.assert_called_once_with("mock_id_107")
    assert mock_client.create_version.called


def test_107_2_runner_allows_only_project_functions(mock_client):
    """指示書107-2: ランナーに許可一覧が埋め込まれ、eval などの未許可関数実行は ok: false になる"""
    server_code = "function myAllowedFunc() { return 42; }"
    files = [
        {"name": "コード", "type": "SERVER_JS", "source": server_code}
    ]
    mock_client.get_content = MagicMock(return_value={"files": files})
    mock_client.resolve_script_id = MagicMock(return_value="mock_id_107")
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/test")
    mock_client._save_backup = MagicMock()
    mock_client._put_content = MagicMock()

    # run_function を実行して差し込まれるコードを採取
    mock_client.call_webapp = MagicMock(return_value={"data": {"ok": True}})
    mock_client.run_function("mock_id_107", "myAllowedFunc")

    put_files = mock_client._put_content.call_args_list[0][0][1]
    injected_js = next(f["source"] for f in put_files if "function __gm_exec_" in f["source"])

    assert 'var allowed = ["myAllowedFunc"];' in injected_js
    assert "allowed.indexOf(fnName) === -1" in injected_js

    # Node.js で実際に eval を渡して ok:false になることを検証
    import subprocess
    node_test_script = f"""
    const ContentService = {{ MimeType: {{ JSON: 'json' }}, createTextOutput: str => ({{ setMimeType: () => JSON.parse(str) }}) }};
    const Logger = {{ log: () => {{}} }};
    {injected_js}
    const res = __gm_exec_({{ parameter: {{ __gm_run: 'eval', __gm_args: '["1+1"]' }} }});
    if (res.ok === false && res.error.includes('許可されていません')) {{
        process.exit(0);
    }} else {{
        process.exit(1);
    }}
    """
    proc = subprocess.run(["node", "-e", node_test_script], capture_output=True, text=True)
    assert proc.returncode == 0, f"Node.js runner test failed: {proc.stderr}"


def test_107_3_benchmark_function_defaults_keep_runner_false(mock_client):
    """指示書107-3: benchmark_function の既定でランナーを残さない (keep_runner=False)"""
    import inspect
    sig = inspect.signature(mock_client.benchmark_function)
    assert sig.parameters["keep_runner"].default is False
    assert sig.parameters["fast"].default is False


def test_107_4_call_webapp_token_destination_restriction(mock_client):
    """指示書107-4: call_webapp で use_auth=True のとき、script.google.com 以外は例外になり送信されない"""
    mock_client._request_with_retry = MagicMock()

    # 1. 外部ホストへの use_auth ➔ 例外
    with pytest.raises(ValueError) as exc1:
        mock_client.call_webapp("https://evil.example.com/x", use_auth=True)
    assert "認証つきで呼べるのは Apps Script の Web アプリだけです" in str(exc1.value)
    mock_client._request_with_retry.assert_not_called()

    # 2. http:// (平文) ➔ 例外
    with pytest.raises(ValueError) as exc2:
        mock_client.call_webapp("http://script.google.com/macros/s/xxx/exec", use_auth=True)
    assert "認証つきで呼べるのは Apps Script の Web アプリだけです" in str(exc2.value)
    mock_client._request_with_retry.assert_not_called()

    # 3. 正当な https://script.google.com/ ➔ 送信される
    mock_resp = MagicMock(status_code=200, headers={"Content-Type": "application/json"}, text='{"ok":true}', json=lambda: {"ok": True})
    mock_client._request_with_retry.return_value = mock_resp
    res = mock_client.call_webapp("https://script.google.com/macros/s/xxx/exec", use_auth=True)
    assert mock_client._request_with_retry.called


def test_107_5_restore_backup_mismatched_script_id_protection(mock_client, tmp_path):
    """指示書107-5: 別の scriptId の控えを restore_backup すると例外になり _put_content が呼ばれない"""
    mock_client.resolve_script_id = MagicMock(return_value="TARGET_PROJECT_12345")
    mock_client._put_content = MagicMock()

    # 別プロジェクトのバックアップファイルを作成
    wrong_backup = tmp_path / "backup_OTHERPROJECT_20261104_120000.json"
    wrong_backup.write_text(json.dumps({"files": [{"name": "Code", "type": "SERVER_JS", "source": "function x(){}"}]}), encoding="utf-8")

    # force=False ➔ 例外
    with pytest.raises(ValueError) as exc:
        mock_client.restore_backup("TARGET_PROJECT_12345", str(wrong_backup), force=False)
    assert "この控えは別のプロジェクトのものです" in str(exc.value)
    mock_client._put_content.assert_not_called()

    # force=True ➔ 復元可能
    mock_client.get_content = MagicMock(return_value={"files": []})
    mock_client._save_backup = MagicMock(return_value="safety.json")
    res = mock_client.restore_backup("TARGET_PROJECT_12345", str(wrong_backup), force=True)
    assert res["status"] == "success"
    mock_client._put_content.assert_called_once()


def test_107_6_writing_methods_use_cache_false(mock_client):
    """指示書107-6: 書き込む手が get_content(sid, use_cache=False) で取り直していることを検証"""
    mock_client.resolve_script_id = MagicMock(return_value="mock_sid")
    mock_client._save_backup = MagicMock(return_value="backup.json")
    mock_client._put_content = MagicMock()
    mock_client._validate_syntax = MagicMock(return_value="valid")

    recorded_calls = []
    base_files = [{"name": "Code", "type": "SERVER_JS", "source": "function myFunc() { return 1; }"}]

    def fake_get_content(sid, use_cache=True):
        recorded_calls.append(use_cache)
        return {"files": copy.deepcopy(base_files)}

    import copy
    mock_client.get_content = MagicMock(side_effect=fake_get_content)

    # 1. patch_code
    recorded_calls.clear()
    mock_client.patch_code("mock_sid", "Code", target="return 1;", replacement="return 2;")
    assert recorded_calls == [False]

    # 2. patch_function
    recorded_calls.clear()
    mock_client.patch_function("mock_sid", "Code", "myFunc", target="return 1;", replacement="return 3;")
    assert recorded_calls == [False]

    # 3. replace_function
    recorded_calls.clear()
    mock_client.replace_function("mock_sid", "Code", "myFunc", code="function myFunc() { return 4; }")
    assert recorded_calls == [False]

    # 4. add_function
    recorded_calls.clear()
    mock_client.add_function("mock_sid", "Code", code="function newFunc() { return 5; }")
    assert recorded_calls == [False]

    # 5. delete_function
    recorded_calls.clear()
    mock_client.delete_function("mock_sid", "Code", "myFunc")
    assert recorded_calls == [False]

    # 6. batch_patch
    recorded_calls.clear()
    mock_client.batch_patch("mock_sid", operations=[{"file": "Code", "type": "patch", "target": "return 1;", "replacement": "return 6;"}])
    assert recorded_calls == [False]

    # 7. replace_file
    recorded_calls.clear()
    mock_client.replace_file("mock_sid", "Code", new_source="function myFunc() { return 7; }")
    assert recorded_calls == [False]

    # 8. add_file
    recorded_calls.clear()
    mock_client.add_file("mock_sid", "NewFile", file_type="SERVER_JS", source="function a(){}")
    assert recorded_calls == [False]

    # 9. delete_file
    recorded_calls.clear()
    mock_client.delete_file("mock_sid", "Code")
    assert recorded_calls == [False]



def test_108_1_run_function_preserves_external_changes_during_execution(mock_client):
    """指示書108-1: run_function 実行中に別ファイルが書き換わっても、後片付けで消えずに残る"""
    mock_client.resolve_script_id = MagicMock(return_value="mock_sid")
    mock_client._save_backup = MagicMock()
    mock_client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/test")

    current_files = [
        {"name": "Code", "type": "SERVER_JS", "source": "function myFunc() { return 1; }\nfunction doGet(e) { return ContentService.createTextOutput('ok'); }"}
    ]

    import copy
    def fake_get_content(sid, use_cache=True):
        return {"files": copy.deepcopy(current_files)}

    def fake_put_content(sid, flist):
        nonlocal current_files
        current_files = copy.deepcopy(flist)
        return {"files": current_files}

    mock_client.get_content = MagicMock(side_effect=fake_get_content)
    mock_client._put_content = MagicMock(side_effect=fake_put_content)

    def on_call_webapp(*args, **kwargs):
        # 実行中（call_webapp 処理中）に外部で別ファイルが追加・編集された模擬
        current_files.append({
            "name": "ExternalEdit",
            "type": "SERVER_JS",
            "source": "function userEdit() { return 999; }"
        })
        return {"data": {"ok": True, "result": 1}}

    mock_client.call_webapp = MagicMock(side_effect=on_call_webapp)

    res = mock_client.run_function("mock_sid", "myFunc")
    assert res.get("status") == "success"

    # 後片付けの後も外部変更 ExternalEdit が残っていること
    assert any(f["name"] == "ExternalEdit" and "userEdit" in f["source"] for f in current_files)
    # かつランナー (__gm_exec_) は除去されていること
    assert not any("__gm_exec_" in f["source"] for f in current_files)


def test_108_2_restore_backup_invalid_filename_format_protection(mock_client, tmp_path):
    """指示書108-2: backup_<12字>_ の形でない控えを戻そうとすると例外になり _put_content が呼ばれない"""
    mock_client.resolve_script_id = MagicMock(return_value="TARGET_PROJECT_12345")
    mock_client._put_content = MagicMock()

    # 形の合わないファイル名（名前変更された控え）
    custom_backup = tmp_path / "renamed_backup_file.json"
    custom_backup.write_text(json.dumps({"files": [{"name": "Code", "type": "SERVER_JS", "source": "function x(){}"}]}), encoding="utf-8")

    # force=False ➔ 例外になり _put_content は呼ばれない
    with pytest.raises(ValueError) as exc:
        mock_client.restore_backup("TARGET_PROJECT_12345", str(custom_backup), force=False)
    assert "控えの持ち主が分かりません" in str(exc.value)
    mock_client._put_content.assert_not_called()

    # force=True ➔ 復元可能
    mock_client.get_content = MagicMock(return_value={"files": []})
    mock_client._save_backup = MagicMock(return_value="safety.json")
    res = mock_client.restore_backup("TARGET_PROJECT_12345", str(custom_backup), force=True)
    assert res["status"] == "success"
    mock_client._put_content.assert_called_once()


def test_108_3_clone_web_warning_for_anyone_anonymous(mock_client):
    """指示書108-3: clone_web で access が ANYONE_ANONYMOUS のとき警告が出ること"""
    mock_client.resolve_script_id = MagicMock(return_value="mock_sid")
    mock_client._put_content = MagicMock()
    mock_client.deploy = MagicMock(return_value={"webAppUrl": "https://script.google.com/test"})
    mock_client.xray = MagicMock(return_value={"markdown_report": "レントゲン正常"})
    mock_client._fetch_and_bundle = MagicMock(return_value={
        "server_code": "function doGet(){}",
        "html": "<h1>Test</h1>",
        "total_html_length": 100,
        "inlined_css_count": 0,
        "inlined_js_count": 0,
        "rewritten_links_count": 0
    })

    res = mock_client.clone_web("https://example.com", access="ANYONE_ANONYMOUS", deploy=True)
    assert "⚠️ 写したページを誰でも見られる形で公開しました" in res["markdown_report"]


def test_108_4_cleanup_old_backups_preserves_backups_within_24h(mock_client, tmp_path):
    """指示書108-4: 24時間以内の控えが 40 個あっても 1 個も消えないこと"""
    mock_client.backup_dir = tmp_path
    sid = "MOCK_PROJECT_12345"
    sid_prefix = sid[:12]

    now = time.time()
    # 24時間以内（10分前〜20時間前）のファイルを 40 個作成
    created_within_24h = []
    for i in range(40):
        f = tmp_path / f"backup_{sid_prefix}_20261104_{i:04d}.json"
        f.write_text("{}", encoding="utf-8")
        # タイムスタンプを 24時間以内（i * 30分前）に設定
        mtime = now - (i * 1800)
        os.utime(f, (mtime, mtime))
        created_within_24h.append(f)

    # 24時間より古いファイル（48時間前〜）を 35 個作成
    created_older = []
    for i in range(35):
        f = tmp_path / f"backup_{sid_prefix}_20261101_{i:04d}.json"
        f.write_text("{}", encoding="utf-8")
        mtime = now - (86400 * 2 + i * 3600)
        os.utime(f, (mtime, mtime))
        created_older.append(f)

    # keep=30 でクリーンアップ実行
    mock_client._cleanup_old_backups(sid, keep=30)

    # 1. 24時間以内の 40 個は 1 個も消えていないこと
    remaining_within_24h = [f for f in created_within_24h if f.exists()]
    assert len(remaining_within_24h) == 40

    # 2. 24時間より古い 35 個は最新 30 個に絞られ、古い 5 個が削除されていること
    remaining_older = [f for f in created_older if f.exists()]
    assert len(remaining_older) == 30



def test_109_1_xray_scans_multiple_html_files_for_rpcs(mock_client):
    """指示書109-1: 複数HTMLファイルに分かれたプロジェクトで、別ファイルのRPC呼び出しを誤爆（死にコード判定）しない"""
    mock_client.resolve_script_id = MagicMock(return_value="mock_sid")

    # index.html (メイン画面・RPC呼び出しなし) と script.html (分割JSコンポーネント・RPC呼び出しあり)
    mock_files = [
        {
            "name": "Code",
            "type": "SERVER_JS",
            "source": """
function doGet(e) {
  return HtmlService.createTemplateFromFile('index').evaluate();
}

function fetchUserEmails(count) {
  return ["mail1", "mail2"];
}
"""
        },
        {
            "name": "index",
            "type": "HTML",
            "source": """
<!DOCTYPE html>
<html>
<head><?!= include('script'); ?></head>
<body><h1>Dashboard</h1></body>
</html>
"""
        },
        {
            "name": "script",
            "type": "HTML",
            "source": """
<script>
function loadData() {
  google.script.run
    .withSuccessHandler(function(res) { console.log(res); })
    .fetchUserEmails(10);
}
</script>
"""
        }
    ]

    mock_client.get_content = MagicMock(return_value={"files": mock_files})

    res = mock_client.xray("mock_sid")
    # 1. script.html 側の RPC呼び出しが認識されていること
    assert res["server_classification"].get("fetchUserEmails") == "public_rpc"
    # 2. fetchUserEmails が死にコード（dead_server_functions）に誤爆判定されていないこと
    dead_names = [d["name"] for d in res["dead_server_functions"]]
    assert "fetchUserEmails" not in dead_names
    # 3. 死にコードが 0 件であること
    assert len(res["dead_server_functions"]) == 0


def test_109_2_xray_treats_include_as_entry_point(mock_client):
    """指示書109-2: GAS標準のテンプレート展開関数 include が死にコードに誤爆判定されない"""
    mock_client.resolve_script_id = MagicMock(return_value="mock_sid")

    mock_files = [
        {
            "name": "Code",
            "type": "SERVER_JS",
            "source": """
function doGet() {
  return HtmlService.createTemplateFromFile('Index').evaluate();
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
"""
        },
        {
            "name": "Index",
            "type": "HTML",
            "source": "<html><body><?!= include('css'); ?></body></html>"
        }
    ]

    mock_client.get_content = MagicMock(return_value={"files": mock_files})

    res = mock_client.xray("mock_sid")
    dead_names = [d["name"] for d in res["dead_server_functions"]]
    assert "include" not in dead_names
    assert len(res["dead_server_functions"]) == 0


def test_pick_latest_deployment_prefers_newest_version():
    from gas_client import GasClient
    deps = [
        {"deploymentId": "HEAD", "deploymentConfig": {}},
        {"deploymentId": "old7", "deploymentConfig": {"versionNumber": 7}, "updateTime": "2026-04-15T19:00:00Z"},
        {"deploymentId": "new16", "deploymentConfig": {"versionNumber": 16}, "updateTime": "2026-05-10T04:00:00Z"},
        {"deploymentId": "mid15", "deploymentConfig": {"versionNumber": 15}, "updateTime": "2026-04-16T22:00:00Z"},
    ]
    assert GasClient._pick_latest_deployment(deps)["deploymentId"] == "new16"
    assert GasClient._pick_latest_deployment([{"deploymentId": "HEAD", "deploymentConfig": {}}]) is None


def test_002_tokenize_and_extract_functions_cache(mock_client):
    source = "function hello() { return 'world'; }\nfunction add(a, b) { return a + b; }"
    toks1, mask1 = mock_client._tokenize_js(source)
    toks2, mask2 = mock_client._tokenize_js(source)
    assert toks1 == toks2
    assert mask1 == mask2
    toks1.append((0, 0, 'DUMMY'))
    assert toks1 != mock_client._tokenize_js(source)[0]

    funcs1 = mock_client._extract_functions_from_js(source)
    funcs2 = mock_client._extract_functions_from_js(source)
    assert funcs1 == funcs2
    assert len(funcs1) == 2
    funcs1[0]["name"] = "corrupted"
    assert mock_client._extract_functions_from_js(source)[0]["name"] == "hello"


def test_002_subprocess_no_window_flag(mock_client, monkeypatch):
    import subprocess
    captured_kwargs = {}

    def fake_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    monkeypatch.setattr(subprocess, "run", fake_run)
    mock_client._syntax_cache.clear()
    mock_client._validate_syntax("test_file", "function test() {}", file_type="SERVER_JS")
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert captured_kwargs.get("creationflags") == subprocess.CREATE_NO_WINDOW


def test_003_gas_dock_scoring_and_prescriptions(mock_client):
    import copy
    clean_diag = {
        "status": "healthy",
        "script_id": "dummy_sid",
        "issues_count": 0,
        "file_count": 1,
        "total_functions": 1,
        "syntax_errors": [],
        "duplicate_functions": [],
        "duplicate_globals": [],
        "broken_rpc_calls": [],
        "broken_html_templates": [],
        "rpc_arity_warnings": [],
        "performance_warnings": [],
        "unused_params": [],
        "frontend_warnings": [],
        "unused_functions": [],
        "entry_points": {"doGet": [{"file": "Code", "line": 1}]},
        "manifest": {}
    }
    score, grade, pres = mock_client._compute_dock_score_and_prescriptions("dummy", clean_diag, xr=None)
    assert score == 100
    assert grade == "A"
    assert len(pres) == 0

    dead_diag = copy.deepcopy(clean_diag)
    dead_diag["unused_functions"] = [{"name": f"deadFunc{i}", "file": "Code", "line": i} for i in range(10)]
    score, grade, pres = mock_client._compute_dock_score_and_prescriptions("dummy", dead_diag, xr=None)
    assert score == 85
    assert grade == "B"
    assert any("clean-dead" in p["action"] for p in pres)

    warn_diag = copy.deepcopy(clean_diag)
    warn_diag["broken_rpc_calls"] = [{"file": "Index", "line": 10, "function": "missingRpc"}]
    warn_diag["performance_warnings"] = [{"file": "Code", "line": 20, "api": "appendRow", "reason": "ループ内 appendRow"}]
    score, grade, pres = mock_client._compute_dock_score_and_prescriptions("dummy", warn_diag, xr=None)
    assert score == 65
    assert grade == "C"
    actions = [p["action"] for p in pres]
    assert any("add-func" in a for a in actions)
    assert any("recipe" in a for a in actions)


def test_004_auto_rollback_on_broken_rpc_when_deleting_or_renaming_function(mock_client):
    import copy
    files = [
        {"name": "Code", "type": "SERVER_JS", "source": "function fetchData() { return 1; }\nfunction other() { return 2; }"},
        {"name": "Index", "type": "HTML", "source": "<html><script>google.script.run.fetchData();</script></html>"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    with pytest.raises(ValueError) as exc:
        mock_client.delete_function("dummy_sid", "Code", "fetchData")
    assert "【壊したか自動復元】" in str(exc.value)
    assert "RPCリンク切れ" in str(exc.value)
    last_call_files = mock_client._put_content.call_args[0][1]
    code_file = next(f for f in last_call_files if f["name"] == "Code")
    assert "function fetchData" in code_file["source"]


def test_004_auto_rollback_on_duplicate_top_level_function(mock_client):
    import copy
    files = [
        {"name": "FileA", "type": "SERVER_JS", "source": "function helperFn() { return 'A'; }"},
        {"name": "FileB", "type": "SERVER_JS", "source": "function otherFn() { return 'B'; }"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    with pytest.raises(ValueError) as exc:
        mock_client.add_function("dummy_sid", "FileB", "function helperFn() { return 'duplicate'; }")
    assert "【壊したか自動復元】" in str(exc.value)
    assert "重複定義" in str(exc.value)

    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    res = mock_client.add_function("dummy_sid", "FileB", "function helperFn() { return 'duplicate'; }", force=True)
    assert res["status"] == "success"


def test_004_pre_existing_broken_rpc_does_not_false_trigger(mock_client):
    import copy
    files = [
        {"name": "Code", "type": "SERVER_JS", "source": "function goodFn() { return 1; }"},
        {"name": "Index", "type": "HTML", "source": "<html><script>google.script.run.alreadyBroken();</script></html>"}
    ]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    res = mock_client.patch_function("dummy_sid", "Code", "goodFn", target="1", replacement="2")
    assert res["status"] == "success"
    assert mock_client._put_content.call_count == 1


def test_005_gas_recipe_detect_and_apply_append_row(mock_client):
    import copy
    source = (
        "function addRows(sheet) {\n"
        "  for (let i = 0; i < 10; i++) {\n"
        "    sheet.appendRow([i, 'item' + i]);\n"
        "  }\n"
        "}"
    )
    files = [{"name": "Code", "type": "SERVER_JS", "source": source}]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    res = mock_client.gas_recipe("dummy_sid", filename="Code", apply=False)
    assert len(res["detections"]) >= 1
    r01 = next(d for d in res["detections"] if d["recipe_id"] == "R01")
    assert "append_row_batch" in r01["recipe_name"]
    assert "setValues" in r01["transformed_code"]
    assert "__batchRows" in r01["transformed_code"]

    res_apply = mock_client.gas_recipe("dummy_sid", filename="Code", apply=True)
    assert len(res_apply["applied_results"]) >= 1
    assert mock_client._put_content.call_count == 1
    saved_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "__batchRows.push([i, 'item' + i])" in saved_source
    assert "setValues(__batchRows)" in saved_source


def test_005_gas_recipe_detect_and_apply_cache_wrap(mock_client):
    import copy
    source = (
        "function getMasterData(sheetName) {\n"
        "  const ss = SpreadsheetApp.getActiveSpreadsheet();\n"
        "  const sheet = ss.getSheetByName(sheetName);\n"
        "  return sheet.getDataRange().getValues();\n"
        "}"
    )
    files = [{"name": "Code", "type": "SERVER_JS", "source": source}]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    res = mock_client.gas_recipe("dummy_sid", filename="Code", apply=False)
    assert len(res["detections"]) >= 1
    r04 = next(d for d in res["detections"] if d["recipe_id"] == "R04")
    assert "cache_service_wrap" in r04["recipe_name"]
    assert "CacheService.getScriptCache()" in r04["transformed_code"]

    res_apply = mock_client.gas_recipe("dummy_sid", filename="Code", func_name="getMasterData", apply=True)
    assert len(res_apply["applied_results"]) >= 1
    assert mock_client._put_content.call_count == 1
    saved_source = mock_client._put_content.call_args[0][1][0]["source"]
    assert "CacheService.getScriptCache()" in saved_source
    assert "__cache.put(" in saved_source


def test_006_recipe_catalog_12_items_and_natural_language_match(mock_client):
    res = mock_client.list_recipes()
    assert res["count"] == 12
    assert len(res["recipes"]) == 12
    ids = [r["id"] for r in res["recipes"]]
    for i in range(1, 13):
        assert f"R{i:02d}" in ids

    m1 = mock_client.match_recipe_by_text("メールのスレッド取得が遅い")
    assert len(m1) > 0
    assert m1[0]["id"] == "R06"

    m2 = mock_client.match_recipe_by_text("シートに1行ずつ追記")
    assert len(m2) > 0
    assert m2[0]["id"] == "R01"

    m3 = mock_client.match_recipe_by_text("排他ロックと6分制限")
    assert len(m3) > 0
    assert m3[0]["id"] == "R12"


def test_006_detect_r05_r06_r07_r08_r10_r11_and_apply_r06_r12(mock_client):
    import copy
    files = [
        {
            "name": "Code",
            "type": "SERVER_JS",
            "source": (
                "function processProps() {\n"
                "  for (let i = 0; i < 10; i++) {\n"
                "    const val = PropertiesService.getScriptProperties().getProperty('key_' + i);\n"
                "  }\n"
                "}\n\n"
                "function fetchMail() {\n"
                "  const threads = GmailApp.search('label:unread');\n"
                "  for (let i = 0; i < threads.length; i++) {\n"
                "    const msgs = threads[i].getMessages();\n"
                "  }\n"
                "}\n\n"
                "function styleCells() {\n"
                "  const sheet = SpreadsheetApp.getActiveSheet();\n"
                "  for (let i = 1; i <= 10; i++) {\n"
                "    sheet.getRange(i, 1).setBackground('#ff0000');\n"
                "  }\n"
                "}\n\n"
                "function deleteOld() {\n"
                "  const sheet = SpreadsheetApp.getActiveSheet();\n"
                "  for (let i = 10; i >= 1; i--) {\n"
                "    sheet.deleteRow(i);\n"
                "  }\n"
                "}\n\n"
                "function searchDrive() {\n"
                "  const files = DriveApp.getFiles();\n"
                "  while (files.hasNext()) {\n"
                "    const f = files.next();\n"
                "    if (f.getName() === 'test') {}\n"
                "  }\n"
                "}\n\n"
                "function batchWrite() {\n"
                "  const sheet = SpreadsheetApp.getActiveSheet();\n"
                "  for (let i = 0; i < 5; i++) {\n"
                "    sheet.appendRow([i]);\n"
                "  }\n"
                "}\n"
            )
        },
        {
            "name": "Index",
            "type": "HTML",
            "source": (
                "<html><script>\n"
                "function load() {\n"
                "  google.script.run.withSuccessHandler(res => {\n"
                "    google.script.run.withSuccessHandler(sub => {}).other();\n"
                "  }).first();\n"
                "}\n"
                "</script></html>"
            )
        }
    ]
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")

    res = mock_client.gas_recipe("dummy_sid")
    detected_ids = {d["recipe_id"] for d in res["detections"]}
    assert "R05" in detected_ids
    assert "R06" in detected_ids
    assert "R07" in detected_ids
    assert "R08" in detected_ids
    assert "R10" in detected_ids
    assert "R11" in detected_ids

    # R06 自動適用検証
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    res_r06 = mock_client.gas_recipe("dummy_sid", filename="Code", func_name="fetchMail", recipe_id="R06", apply=True)
    assert len(res_r06["applied_results"]) == 1
    assert res_r06["applied_results"][0]["recipe_id"] == "R06"
    applied_source_r06 = mock_client._put_content.call_args[0][1][0]["source"]
    assert "GmailApp.getMessagesForThreads(threads)" in applied_source_r06
    assert "__threadMsgs[i]" in applied_source_r06

    # R12 自動適用検証
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    res_r12 = mock_client.gas_recipe("dummy_sid", filename="Code", func_name="batchWrite", recipe_id="R12", apply=True)
    assert len(res_r12["applied_results"]) == 1
    assert res_r12["applied_results"][0]["recipe_id"] == "R12"
    applied_source_r12 = mock_client._put_content.call_args[0][1][0]["source"]
    assert "LockService.getScriptLock()" in applied_source_r12
    assert "tryLock(10000)" in applied_source_r12
    assert "releaseLock()" in applied_source_r12


def test_007_fast_write_mode_skips_get_content_network_call(mock_client):
    import copy
    files = [{"name": "Code", "type": "SERVER_JS", "source": "function test() { return 1; }"}]
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()

    # fast=False (既定) では use_cache=False が渡る
    mock_client.replace_function("dummy_sid", "Code", "test", "function test() { return 2; }")
    mock_client.get_content.assert_called_with("dummy_sid", use_cache=False)

    # fast=True では use_cache=True が渡る
    mock_client.get_content.reset_mock()
    mock_client.replace_function("dummy_sid", "Code", "test", "function test() { return 3; }", fast=True)
    mock_client.get_content.assert_called_with("dummy_sid", use_cache=True)


def test_007_deploy_after_put_skips_redundant_get_content(mock_client):
    import copy
    from unittest.mock import call
    files = [{"name": "Code", "type": "SERVER_JS", "source": "function hello() { return 'world'; }"}]
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client.get_content = MagicMock(side_effect=lambda sid, use_cache=True: {"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()
    mock_client.create_version = MagicMock(return_value=2)
    mock_client.get_deployments = MagicMock(return_value=[{"deploymentId": "dep1", "deploymentConfig": {"versionNumber": 1}, "entryPoints": []}])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"versionNumber": 2, "deploymentId": "dep1"}
    mock_client._request_with_retry = MagicMock(return_value=mock_resp)

    # patch_function(..., deploy=True) を実行
    res = mock_client.patch_function("dummy_sid", "Code", "hello", target="'world'", replacement="'fast'", deploy=True)
    assert res["status"] == "success"

    # get_content の全呼び出し履歴を確認: 1回目は書き込み用(use_cache=False)、2回目の deploy 内は直前キャッシュ再利用(use_cache=True)
    calls = mock_client.get_content.call_args_list
    assert len(calls) == 2
    assert calls[0] == call("dummy_sid", use_cache=False)
    assert calls[1] == call("dummy_sid", use_cache=True)


def test_008_rpc_property_mismatch_detection_and_auto_rollback(mock_client):
    import copy
    files = [
        {
            "name": "Code",
            "type": "SERVER_JS",
            "source": (
                "function getUserInfo() {\n"
                "  return { userName: 'Alice', role: 'admin' };\n"
                "}\n\n"
                "function fetchSpreadsheetData() {\n"
                "  const ss = SpreadsheetApp.getActiveSpreadsheet();\n"
                "  return ss.getDataRange().getValues();\n"
                "}\n"
            )
        },
        {
            "name": "Index",
            "type": "HTML",
            "source": (
                "<html><script>\n"
                "function load() {\n"
                "  google.script.run.withSuccessHandler(function(res) {\n"
                "    console.log(res.userName);\n"
                "  }).getUserInfo();\n\n"
                "  google.script.run.withSuccessHandler(res => {\n"
                "    console.log(res.length);\n"
                "  }).fetchSpreadsheetData();\n"
                "}\n"
                "</script></html>"
            )
        }
    ]
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client.get_content = MagicMock(return_value={"files": copy.deepcopy(files)})
    mock_client._put_content = MagicMock()

    # 1. 正常状態での check_rpc_contracts
    contracts = mock_client.check_rpc_contracts("dummy_sid")
    assert contracts["status"] == "healthy"
    assert len(contracts["rpc_property_mismatches"]) == 0
    # missing_failure_handlers: 2件 (getUserInfo, fetchSpreadsheetData で withFailureHandler 未設定)
    assert len(contracts["missing_failure_handlers"]) == 2
    # unprotected_server_rpcs: 1件 (fetchSpreadsheetData は SpreadsheetApp を呼ぶが try/catch なし)
    assert len(contracts["unprotected_server_rpcs"]) == 1
    assert contracts["unprotected_server_rpcs"][0]["rpc"] == "fetchSpreadsheetData"

    # 2. gas_dock での契約ズレ・減点検証
    dock_res = mock_client.gas_dock("dummy_sid")
    assert any(p["category"] == "通信エラー防御" for p in dock_res["prescriptions"])
    assert any(p["category"] == "サーバー例外防御" for p in dock_res["prescriptions"])

    # 3. サーバー側を return { fullName: 'Alice', role: 'admin' }; に patch_function -> 壊したか自動復元
    with pytest.raises(ValueError) as excinfo:
        mock_client.patch_function(
            "dummy_sid", "Code", "getUserInfo",
            target="userName: 'Alice'",
            replacement="fullName: 'Alice'"
        )
    assert "壊したか自動復元" in str(excinfo.value)
    assert "RPC戻り値プロパティ契約の不一致が新規発生" in str(excinfo.value)
    assert "getUserInfo.userName" in str(excinfo.value)


def test_009_gas_scaffold_catalog_and_apply_full_architecture(mock_client):
    import copy
    # 1. カタログ取得
    res_list = mock_client.gas_scaffold(list_only=True)
    assert res_list["count"] == 5
    ids = [s["id"] for s in res_list["scaffolds"]]
    assert ids == ["S01", "S02", "S03", "S04", "S05"]

    # 2. S05 (full_architecture) の注入
    files = [
        {"name": "Code", "type": "SERVER_JS", "source": "function doGet() { return HtmlService.createHtmlOutputFromFile('Index'); }"},
        {"name": "Index", "type": "HTML", "source": "<html><head></head><body><h1>Hello</h1><script>\nconsole.log('init');\n</script></body></html>"}
    ]
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client.get_content = MagicMock(side_effect=lambda sid, use_cache=False: {"files": copy.deepcopy(files)})

    def fake_put(sid, new_files):
        files.clear()
        files.extend(copy.deepcopy(new_files))
    mock_client._put_content = MagicMock(side_effect=fake_put)

    res_apply = mock_client.gas_scaffold(script_id="dummy_sid", scaffold_id="S05", apply=True)
    assert res_apply["status"] == "success"
    assert res_apply["applied"] is True

    # Index.html に S01, S02, S03 の主要関数が存在することを確認
    html_f = next(f for f in files if f["name"] == "Index")
    assert "callServer" in html_f["source"]
    assert "createSwrStore" in html_f["source"]
    assert "runOptimistic" in html_f["source"]
    assert "/* @gas-scaffold:S01 */" in html_f["source"]
    assert "/* @gas-scaffold:S02 */" in html_f["source"]
    assert "/* @gas-scaffold:S03 */" in html_f["source"]

    # Code.gs に S04 (runSafeRpc_) が存在することを確認
    code_f = next(f for f in files if f["name"] == "Code")
    assert "runSafeRpc_" in code_f["source"]
    assert "/* @gas-scaffold:S04 */" in code_f["source"]

    # 3. 2回目の apply=True 呼び出しで二重注入が防止されること
    res_apply2 = mock_client.gas_scaffold(script_id="dummy_sid", scaffold_id="S05", apply=True)
    assert res_apply2["status"] == "already_applied"
    assert res_apply2["applied"] is False
    assert len(res_apply2["skipped_parts"]) >= 4


def test_010_unified_shelf_25_catalog_and_golden_check(mock_client):
    import copy
    from gas_client import GAS_UNIFIED_SHELVES

    # 1. 全25棚（R:12 + S:5 + K:4 + D:4 = 25棚）の検証
    assert len(GAS_UNIFIED_SHELVES) == 25
    categories = [s["category"] for s in GAS_UNIFIED_SHELVES]
    assert categories.count("SPEEDUP") == 12
    assert categories.count("SCAFFOLD") == 5
    assert categories.count("DESIGN") == 4
    assert categories.count("DIAG") == 4

    # 2. check_shelves によるゴールデン頼み文全問一致検証
    chk = mock_client.check_shelves()
    assert chk["passed"] is True
    assert chk["total"] >= 30
    assert chk["matched"] == chk["total"]
    assert chk["mismatches"] == []

    # 3. gas_shelf 直結ディスパッチの検証 (D01: gas_dock, D03: clean_dead)
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client.gas_dock = MagicMock(return_value={"status": "healthy", "markdown_report": "dock report"})
    mock_client.clean_dead = MagicMock(return_value={"status": "success", "markdown_report": "clean report"})

    res_dock = mock_client.gas_shelf("dummy_sid", query="ガスドックで健康診断して")
    assert res_dock["status"] == "success"
    assert res_dock["matched_shelf"]["id"] == "D01"
    mock_client.gas_dock.assert_called_once_with("dummy_sid", filename="Index")

    res_clean = mock_client.gas_shelf("dummy_sid", query="使っていない関数を掃除して")
    assert res_clean["status"] == "success"
    assert res_clean["matched_shelf"]["id"] == "D03"
    mock_client.clean_dead.assert_called_once_with("dummy_sid", dry_run=True, deploy=False)

def test_011_hybrid_sync_and_cached_writes(mock_client):
    """指示書011: 初回クラウド突き合わせ＋同期後キャッシュ自動活用＋解析キャッシュ永続化"""
    import copy
    files = [{"name": "Code", "type": "SERVER_JS", "source": "function test() { return 1; }"}]
    mock_client.resolve_script_id = MagicMock(return_value="dummy_sid")
    mock_client._put_content = MagicMock()
    mock_client._synced_sids = set()

    # 1. 初回書き込み: 未同期 (dummy_sid not in _synced_sids) では fast=False で use_cache=False (クラウド突き合わせ)
    mock_client.get_content = MagicMock(side_effect=lambda sid, use_cache=True: {"files": copy.deepcopy(files)})
    mock_client.replace_function("dummy_sid", "Code", "test", "function test() { return 2; }", fast=False)
    mock_client.get_content.assert_called_with("dummy_sid", use_cache=False)

    # 2. 同期後: _synced_sids に sid が入った状態では fast=False でも自動的に use_cache=True (通信カット)
    mock_client._synced_sids.add("dummy_sid")
    mock_client.get_content.reset_mock()
    mock_client.patch_code("dummy_sid", "Code", target="return 1;", replacement="return 10;", fast=False)
    mock_client.get_content.assert_called_with("dummy_sid", use_cache=True)

    mock_client.get_content.reset_mock()
    mock_client.replace_file("dummy_sid", "Code", "function test() { return 99; }", fast=False)
    mock_client.get_content.assert_called_with("dummy_sid", use_cache=True)

    # 3. sync_project の動作検証
    with patch.object(mock_client, "_request_with_retry") as mock_req:
        res_mock = MagicMock()
        res_mock.status_code = 200
        res_mock.json.return_value = {"files": copy.deepcopy(files)}
        mock_req.return_value = res_mock

        mock_client._synced_sids.clear()
        sync_res = mock_client.sync_project("dummy_sid")
        assert sync_res["synced"] is True
        assert sync_res["updated_from_cloud"] is True
        assert "dummy_sid" in mock_client._synced_sids

    # 4. gas_dock の解析キャッシュ永続化検証
    mock_client._force_dock_cache = True
    mock_client._dock_cache.clear()
    mock_client.get_content = MagicMock(side_effect=lambda sid, use_cache=True: {"files": copy.deepcopy(files)})

    with patch.object(GasClient, "diagnose", return_value={"status": "healthy", "issues_count": 0, "syntax_errors": []}) as mock_d,          patch.object(GasClient, "xray", return_value={"front_functions_count": 0, "ui_elements_count": 0, "ghost_rpcs": []}):
        dock_res = mock_client.gas_dock("dummy_sid")
        assert dock_res["score"] == 100
        assert dock_res["status"] == "healthy"

        # dock_reports に保存されたか確認
        dock_reports = mock_client._cache_data.get("dock_reports", {})
        assert len(dock_reports) >= 1
        key = list(dock_reports.keys())[0]
        assert key.startswith("dummy_sid:Index:")
        assert dock_reports[key]["score"] == 100

        # メモリキャッシュをクリアして再実行 -> ディスクキャッシュから即座に返却され diagnose は呼ばれない
        mock_client._dock_cache.clear()
        mock_d.reset_mock()
        dock_res_cached = mock_client.gas_dock("dummy_sid")
        assert dock_res_cached["score"] == 100
        mock_d.assert_not_called()

def test_012_reload_tools_and_py_ast_self_patch(tmp_path):
    """指示書012: 常駐MCPホットリロード (reload_tools) と Python AST 自己整備 (py_outline, py_get_function, py_patch_function)"""
    from gas_client import GasClient
    import gas_mcp_server

    # 1. 一時 Python ファイルの準備
    dummy_py = tmp_path / "dummy_service.py"
    dummy_code = '''# -*- coding: utf-8 -*-
def top_level_calc(x, y):
    # calc comment
    return x + y

class MathService:
    @property
    def version(self):
        return "1.0.0"

    def multiply(self, a, b):
        res = a * b
        return res
'''
    dummy_py.write_text(dummy_code, encoding="utf-8")

    # 2. py_outline の検証
    outline = GasClient.py_outline(str(dummy_py))
    assert len(outline) == 3
    names = [it["name"] for it in outline]
    assert names == ["top_level_calc", "MathService.version", "MathService.multiply"]
    assert outline[0]["lines_count"] == 3
    assert outline[1]["lines_count"] == 3
    assert outline[2]["lines_count"] == 3

    # 3. py_get_function の検証
    fn_top = GasClient.py_get_function(str(dummy_py), "top_level_calc")
    assert fn_top["name"] == "top_level_calc"
    assert "return x + y" in fn_top["source"]

    fn_method = GasClient.py_get_function(str(dummy_py), "MathService.multiply")
    assert fn_method["name"] == "MathService.multiply"
    assert "res = a * b" in fn_method["source"]

    # 短縮名での探索も動作すること
    fn_short = GasClient.py_get_function(str(dummy_py), "multiply")
    assert fn_short["name"] == "MathService.multiply"

    # 4. py_patch_function の検証（正常置換）
    patch_res = GasClient.py_patch_function(
        str(dummy_py),
        "MathService.multiply",
        target="res = a * b",
        replacement="res = (a * b) + 1"
    )
    assert patch_res["status"] == "success"
    assert patch_res["replaced_occurrences"] == 1
    assert "MathService.multiply" in patch_res["name"]

    # 置換後のファイル内容確認
    new_src = dummy_py.read_text(encoding="utf-8")
    assert "res = (a * b) + 1" in new_src
    assert "return x + y" in new_src

    # 5. py_patch_function の検証（構文エラー時の書き込み拒否関所）
    with pytest.raises(ValueError) as excinfo:
        GasClient.py_patch_function(
            str(dummy_py),
            "MathService.multiply",
            target="res = (a * b) + 1",
            replacement="res = (a * b) +"
        )
    assert "構文エラー" in str(excinfo.value)

    # 構文エラー時はファイルが一切変更されずロールバックされていること
    unmodified_src = dummy_py.read_text(encoding="utf-8")
    assert "res = (a * b) + 1" in unmodified_src

    # 6. gas_mcp_server.reload_tools の検証
    reload_msg = gas_mcp_server.reload_tools()
    assert "[SUCCESS]" in reload_msg
    assert "ホットリロード完了" in reload_msg

