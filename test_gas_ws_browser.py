# -*- coding: utf-8 -*-
"""test_gas_ws_browser.py - gas_ws_browser および WorkspaceManager ブラウザ連動のテスト"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gas_ws_browser
import gas_workspace


def test_save_and_load_browser_active_heartbeat_vs_change(tmp_path):
    p = tmp_path / ".ws_browser_active.json"
    t0 = 1000.0
    r1 = gas_ws_browser.save_browser_active(
        {"id": "ss_aaa", "kind": "sheet", "name": "売上表", "sheet": "Sheet1", "selection": "A1", "ts": t0},
        path=p,
        source="ext",
    )
    assert r1 is not None
    assert r1["changed_at"] == t0
    assert r1["seen_at"] == t0

    # 4秒後の同一内容ハートビート → seen_at のみ更新、changed_at は維持
    r2 = gas_ws_browser.save_browser_active(
        {"id": "ss_aaa", "kind": "sheet", "name": "売上表", "sheet": "Sheet1", "selection": "A1", "ts": t0 + 4.0},
        path=p,
        source="ext",
    )
    assert r2["seen_at"] == t0 + 4.0
    assert r2["changed_at"] == t0

    # タブ切替直後の partial 更新で同じ ID の場合、sheet / selection は維持される
    r3 = gas_ws_browser.save_browser_active(
        {"id": "ss_aaa", "kind": "sheet", "name": "売上表", "partial": True, "ts": t0 + 5.0},
        path=p,
        source="ext",
    )
    assert r3["sheet"] == "Sheet1"
    assert r3["selection"] == "A1"

    # 別シートへ切り替え（シグネチャ変化）→ changed_at 更新
    r4 = gas_ws_browser.save_browser_active(
        {"id": "ss_aaa", "kind": "sheet", "name": "売上表", "sheet": "Sheet2", "selection": "B2", "ts": t0 + 8.0},
        path=p,
        source="ext",
    )
    assert r4["changed_at"] == t0 + 8.0

    # 期限切れチェック
    assert gas_ws_browser.load_browser_active(path=p, max_age_sec=10.0) is None
    loaded = gas_ws_browser.load_browser_active(path=p, max_age_sec=None)
    assert loaded is not None
    assert loaded["id"] == "ss_aaa"
    assert loaded["sheet"] == "Sheet2"


def test_mcp_sync_server_endpoints_and_origin_guard(tmp_path):
    p = tmp_path / ".ws_browser_active.json"
    srv = gas_ws_browser.start_mcp_sync_server(port=0, path=p)
    assert srv is not None
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        # GET /ping
        with urllib.request.urlopen(f"{base}/ping", timeout=2) as res:
            body = json.loads(res.read().decode("utf-8"))
        assert body["ok"] is True
        assert body["app"] == "gas-manager-mcp"

        # POST /sync（許可された拡張 Origin）
        req = urllib.request.Request(
            f"{base}/sync",
            data=json.dumps({"id": "ss_sync_1", "kind": "sheet", "name": "テスト表", "sheet": "明細", "selection": "C3"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"chrome-extension://{gas_ws_browser.EXT_FIXED_ID}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as res:
            assert json.loads(res.read().decode("utf-8"))["ok"] is True

        # GET /active
        with urllib.request.urlopen(f"{base}/active", timeout=2) as res:
            act = json.loads(res.read().decode("utf-8"))
        assert act["id"] == "ss_sync_1"
        assert act["sheet"] == "明細"
        assert act["selection"] == "C3"

        # 不正な外部 Origin からの POST は 403
        bad_req = urllib.request.Request(
            f"{base}/sync",
            data=b'{"id":"evil"}',
            headers={"Content-Type": "application/json", "Origin": "https://evil.example.com"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(bad_req, timeout=2)
        assert ei.value.code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_parse_window_title():
    r1 = gas_ws_browser.parse_window_title("GASマネージャー_作成速度テスト - Google スプレッドシート - Google Chrome")
    assert r1 == {
        "name": "GASマネージャー_作成速度テスト",
        "kind": "sheet",
        "window_title": "GASマネージャー_作成速度テスト - Google スプレッドシート - Google Chrome",
    }

    r2 = gas_ws_browser.parse_window_title("議事録2026 - Google Docs")
    assert r2 == {
        "name": "議事録2026",
        "kind": "doc",
        "window_title": "議事録2026 - Google Docs",
    }

    assert gas_ws_browser.parse_window_title("無題 - メモ帳") is None


def test_resolve_target_browser_priority_and_override(tmp_path, monkeypatch):
    state_p = tmp_path / ".ws_state.json"
    active_p = tmp_path / ".ws_browser_active.json"
    mgr = gas_workspace.WorkspaceManager(state_path=state_p, browser_detect=True)

    now = time.time()
    gas_ws_browser.save_browser_active(
        {"id": "ss_browser_1", "kind": "sheet", "name": "ブラウザ表", "sheet": "集計", "selection": "D4", "ts": now},
        path=active_p,
        source="ext",
    )

    # 1. 初回・記憶なし → 拡張の相手を自動採用
    tgt, is_new = mgr.resolve_target("", "sheet", {})
    assert is_new is False
    assert tgt["id"] == "ss_browser_1"
    assert tgt["sheet"] == "集計"

    # 1b. 直前に名指し・作業中の記憶あり → ブラウザ連動より記憶を優先する
    st = {"target": {"id": "ss_old", "kind": "sheet", "name": "古い表"}, "target_set_at": now - 60.0}
    tgt_kept, _ = mgr.resolve_target("", "sheet", st)
    assert tgt_kept["id"] == "ss_old"

    # 2. 明示指定で別ファイルを記憶した直後（ハートビートのみでは上書きしない）
    st_explicit = {"target": {"id": "ss_manual", "kind": "sheet", "name": "手指定表"}, "target_set_at": now + 10.0}
    tgt2, _ = mgr.resolve_target("", "sheet", st_explicit)
    assert tgt2["id"] == "ss_manual"

    # 3. target="browser" を渡せば明示指定後でもブラウザの相手を強制取得
    tgt3, _ = mgr.resolve_target("browser", "sheet", st_explicit)
    assert tgt3["id"] == "ss_browser_1"

    # 4. 拡張が期限切れのときは Windows ウィンドウフォールバック
    active_p.unlink()
    monkeypatch.setattr(
        gas_ws_browser,
        "detect_window_targets",
        lambda: [{"name": "窓から見つけた表", "kind": "sheet", "window_title": "窓から見つけた表 - Google スプレッドシート"}],
    )
    monkeypatch.setattr(
        mgr,
        "_search_name",
        lambda name, kind: {"id": "ss_win_1", "name": name, "kind": kind},
    )
    tgt4, _ = mgr.resolve_target("", "sheet", {})
    assert tgt4["id"] == "ss_win_1"
    assert tgt4["_source"] == "window_title"


def test_look_recent_and_inspect_active(tmp_path, monkeypatch):
    state_p = tmp_path / ".ws_state.json"
    active_p = tmp_path / ".ws_browser_active.json"
    mgr = gas_workspace.WorkspaceManager(state_path=state_p, browser_detect=False)

    gas_ws_browser.save_browser_active(
        {"id": "ss_now", "kind": "sheet", "name": "今開いてる表", "sheet": "Sheet1", "selection": "A1:B5"},
        path=active_p,
        source="mcp-sync",
    )
    monkeypatch.setattr(gas_ws_browser, "detect_window_targets", lambda: [])

    info = mgr.inspect_active_target()
    assert "今開いてる表" in info
    assert "A1:B5" in info
    assert "ss_now" in info

    monkeypatch.setattr(
        mgr,
        "recent_files",
        lambda limit=10, kind=None: [
            {"id": "ss_r1", "name": "最近の表", "kind": "sheet", "viewedByMeTime": "2026-11-27T04:00:00Z", "modifiedTime": "", "url": "https://docs.google.com/spreadsheets/d/ss_r1/edit"}
        ],
    )
    rec_text = mgr.look(target="recent")
    assert "最近の表" in rec_text
    assert "ss_r1" in rec_text


def test_save_browser_active_cleans_tmp_on_replace_contention(tmp_path, monkeypatch):
    p = tmp_path / ".ws_browser_active.json"
    orig_replace = Path.replace
    calls = {"n": 0}

    def flaky_replace(self, target):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("locked by another process")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    res = gas_ws_browser.save_browser_active({"id": "ss_retry", "kind": "sheet", "name": "リトライ表"}, path=p)
    assert res is not None
    assert calls["n"] == 3
    assert list(tmp_path.glob("*.tmp")) == []

    # 全滅しても .tmp ファイルは残さない
    def always_fail(self, target):
        raise PermissionError("locked permanently")

    monkeypatch.setattr(Path, "replace", always_fail)
    res2 = gas_ws_browser.save_browser_active({"id": "ss_fail", "kind": "sheet", "name": "失敗表"}, path=p)
    assert res2 is not None
    assert list(tmp_path.glob("*.tmp")) == []


def test_diagnose_browser_sync_detects_duplicate_path(tmp_path, monkeypatch):
    monkeypatch.setattr(gas_ws_browser, "_ping_local_port", lambda port, timeout=0.3: (port == 18767, {"ok": True}))
    ud = tmp_path / "UserData"
    (ud / "Default").mkdir(parents=True)
    sp = {
        "extensions": {
            "settings": {
                gas_ws_browser.EXT_FIXED_ID: {
                    "path": r"C:\ext\ws_browser_ext",
                    "disable_reasons": [],
                },
                "goijgkhoglobipicgjpmpkjnglbfikff": {
                    "path": r"C:\ext\ws_browser_ext",
                    "disable_reasons": [4],
                },
            }
        }
    }
    (ud / "Default" / "Secure Preferences").write_text(json.dumps(sp, ensure_ascii=False), encoding="utf-8")

    diag = gas_ws_browser.diagnose_browser_sync(chrome_user_data=ud)
    assert diag["mcp_sync_ok"] is True
    assert diag["watch_ok"] is False
    assert diag["ext_registered"] is True
    assert len(diag["duplicate_ids"]) == 1
    assert diag["duplicate_ids"][0]["id"] == "goijgkhoglobipicgjpmpkjnglbfikff"
    assert any("競合" in h for h in diag["hints"])


def test_direct_look_sheet_table_side_and_range(tmp_path, monkeypatch):
    import gas_ws_direct

    state_p = tmp_path / ".ws_state.json"
    mgr = gas_workspace.WorkspaceManager(state_path=state_p, browser_detect=False)
    dr = gas_ws_direct.DirectRunner(mgr)

    st = {"direct_token": {"token": "tok_test", "until": time.time() + 3600}}

    meta_resp = {
        "spreadsheetId": "ss_1",
        "properties": {"title": "売上テスト"},
        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/ss_1/edit",
        "namedRanges": [],
        "sheets": [
            {
                "properties": {"sheetId": 0, "title": "売上表", "gridProperties": {"rowCount": 100, "columnCount": 10}},
                "basicFilter": {"range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 5, "startColumnIndex": 0, "endColumnIndex": 3}},
                "bandedRanges": [{"range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 5, "startColumnIndex": 0, "endColumnIndex": 3}}],
                "protectedRanges": [],
                "rowGroups": [],
                "columnGroups": [],
                "charts": [],
            },
            {
                "properties": {"sheetId": 1, "title": "元データ", "gridProperties": {"rowCount": 50, "columnCount": 5}},
            },
        ],
    }

    def cell_str(s):
        return {"formattedValue": s, "effectiveValue": {"stringValue": s}}

    def cell_date(s, serial):
        return {"formattedValue": s, "effectiveValue": {"numberValue": serial}, "effectiveFormat": {"numberFormat": {"type": "DATE"}}}

    def cell_num(s, n, formula=""):
        c = {"formattedValue": s, "effectiveValue": {"numberValue": n}, "effectiveFormat": {"numberFormat": {"type": "NUMBER"}}}
        if formula:
            c["userEnteredValue"] = {"formulaValue": formula}
        return c

    detail_resp = {
        "sheets": [
            {
                "properties": {"sheetId": 0, "title": "売上表"},
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowMetadata": [],
                        "columnMetadata": [],
                        "rowData": [
                            {"values": [{"formattedValue": "プルダウン", "effectiveValue": {"stringValue": "プルダウン"}, "dataValidation": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "A"}, {"userEnteredValue": "B"}]}}}]},
                            {"values": [cell_str("日付"), cell_str("品名"), cell_str("金額")]},
                            {"values": [cell_date("2026/11/27", 46353), cell_str("商品X"), cell_num("1,000", 1000)]},
                            {"values": [cell_date("2026/11/28", 46354), cell_str("商品Y"), cell_num("2,000", 2000)]},
                            {"values": [cell_str("合計"), cell_str(""), cell_num("3,000", 3000, "=SUM(C3:C4)")]},
                        ],
                    }
                ],
            }
        ]
    }
    others_resp = {"valueRanges": [{"values": [["見出し1", "見出し2"], ["a", 1], ["b", 2]]}]}

    def fake_call(st_arg, method, url, **kw):
        if url.endswith("/values:batchGet"):
            return others_resp
        params = kw.get("params")
        if isinstance(params, list):
            return detail_resp
        return meta_resp

    monkeypatch.setattr(dr, "_call", fake_call)
    res = dr.look(st, {"id": "ss_1", "kind": "sheet"}, sheet="", range_str="A2:C5")
    assert res is not None
    assert res["ok"] is True
    assert res["target"]["sheet"] == "売上表"
    assert res["sheets"] == [{"name": "売上表", "rows": 5, "cols": 3}, {"name": "元データ", "rows": 3, "cols": 2}]
    tb = res["table"]
    assert tb["header_row"] == 2
    assert tb["first_col"] == "A"
    assert tb["last_col"] == "C"
    assert tb["data"] == "3-4"
    assert tb["total_row"] == 5
    # 日付列は数値判定されないこと
    assert tb["columns"] == [
        {"col": "A", "name": "日付", "number": False},
        {"col": "B", "name": "品名", "number": False},
        {"col": "C", "name": "金額", "number": True},
    ]
    assert any(s.startswith("入力規則:") and "プルダウン（A/B）" in s for s in res["side"])
    assert "交互の色: A2:C5" in res["side"]
    assert "フィルタ: A2:C5" in res["side"]
    assert res["values"][3][2] == "3,000"
    assert res["formulas"][3][2] == "=SUM(C3:C4)"


def test_reload_tools_covers_gas_dispatch_and_get_ws():
    import ast
    src = (HERE / "gas_mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_gas_dispatch" in funcs
    assert "_get_ws" in funcs
    assert "gas" in funcs and "get_ws" in funcs
    gas_calls = [c.func.id for c in ast.walk(funcs["gas"]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    ws_calls = [c.func.id for c in ast.walk(funcs["get_ws"]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    assert "_gas_dispatch" in gas_calls
    assert "_get_ws" in ws_calls
