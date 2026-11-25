# -*- coding: utf-8 -*-
"""
汎用の手 api（段 5）の試験。通信なし。
  ・型の表（gas_ws_api.py）: 表に無い型は断る・戻らない欄は断る・消す型の一覧・使った型の記録と「2 回以上」
  ・エンジンの api（node でそのまま）: A1→GridRange・シート名→ID・色→Color の変換／消す型は ok が要る／控えるシートを requests から決める／増えたシートを記録
  ・札・MCP の説明・手順書の頭の行（「棚に無ければ api」）
実機（試験用のエンジンで型を撃って ws_undo で戻す）の確かめは、非公開の試験の道具の側にある。
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

import gas_workspace as gw
import gas_ws_api as A
import gas_ws_catalog as C

HERE = Path(__file__).resolve().parent


# ================================================================ 型の表
def test_table_has_about_twenty_types_each_with_known_touch_items():
    assert 18 <= len(A.TYPES) <= 28
    for name, spec in A.TYPES.items():
        assert spec["touch"], name
        for item in spec["touch"]:
            assert item in C.TOUCH_ITEMS, (name, item)
    assert set(A.danger_types()) == {"deleteRange", "deleteDimension", "deleteConditionalFormatRule"}
    assert all(t.startswith("delete") for t in A.danger_types())                  # 消す型は delete…
    assert "deleteSheet" not in A.TYPES and "deleteNamedRange" not in A.TYPES      # 表に載せていない型は断る


def test_check_requests_refuses_unknown_types_and_unrestorable_fields():
    assert A.check_requests([{"repeatCell": {"range": "A1", "fields": "userEnteredFormat.backgroundColor"}}]) == []
    p = A.check_requests([{"deleteSheet": {"sheetId": 1}}])
    assert len(p) == 1 and "表にありません" in p[0] and "repeatCell" in p[0]
    assert A.check_requests([]) and A.check_requests("x") and A.check_requests([{"a": {}, "b": {}}]) and A.check_requests([{"repeatCell": "x"}])
    # 戻らない物（グリッド線・右から左・行の高さ）は断る。列の幅・隠しは通す
    assert A.check_requests([{"updateSheetProperties": {"properties": {}, "fields": "gridProperties.hideGridlines"}}])
    assert A.check_requests([{"updateSheetProperties": {"properties": {}, "fields": "gridProperties.frozenRowCount"}}]) == []
    assert A.check_requests([{"updateDimensionProperties": {"range": {"dimension": "ROWS"}, "properties": {}, "fields": "pixelSize"}}])
    assert A.check_requests([{"updateDimensionProperties": {"range": {"dimension": "COLUMNS"}, "properties": {}, "fields": "pixelSize"}}]) == []
    assert A.check_requests([{"updateDimensionProperties": {"range": {"dimension": "ROWS"}, "properties": {}, "fields": "hiddenByUser"}}]) == []


def test_touch_items_are_the_union_over_the_types():
    assert A.touch_items(["repeatCell", "addBanding"]) == ["値", "書式", "交互の色"]
    assert A.touch_items(["nothing"]) == []


def test_types_gs_is_generated_from_the_table_only():
    gs = A.build_types_gs()
    obj = json.loads(gs[gs.index("{", gs.index("var API_TYPES")):gs.rindex("}") + 1])
    assert set(obj) == set(A.TYPES) and obj["deleteRange"]["danger"] is True and obj["repeatCell"]["danger"] is False
    assert obj["updateSheetProperties"]["deny"][0]["fields"] == ["hideGridlines", "rightToLeft"]
    assert "ApiTypes" in [n for n, _ in gw._engine_texts()]
    body = gw.WorkspaceManager(client=object(), state_path=HERE / "x_unused.json")._engine_files()[1]["source"]
    assert "var API_TYPES" in body and body.index("var API_TYPES") < body.index("SHELF['api']")        # 型の表が棚より先に入る


def test_uses_are_logged_and_types_used_twice_or_more_are_listed(tmp_path):
    p = tmp_path / "uses.tsv"
    ops = [{"shelf": "api", "requests": [{"repeatCell": {}}, {"addBanding": {}}], "why": "しましまにして"}, {"shelf": "tidy"}]
    assert A.log_uses(ops, p, today="2026-11-13") == 2
    A.log_uses([{"shelf": "api", "requests": [{"repeatCell": {}}], "why": "赤くして"}], p, today="2026-11-14")
    A.log_uses([{"shelf": "tidy"}], p)                                     # api でなければ記録しない
    rows = p.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "2026-11-13\trepeatCell\tしましまにして" and len(rows) == 3
    assert A.used_types(p) == [("repeatCell", 2, "しましまにして")]          # 2 回以上使われた型だけ
    assert A.used_types(p, min_count=1)[1][0] == "addBanding"
    assert A.used_types(tmp_path / "none.tsv") == []


def test_validate_ops_runs_the_api_check_and_log_happens_only_on_success(tmp_path):
    m = gw.WorkspaceManager(client=object(), state_path=tmp_path / "s.json")
    with pytest.raises(gw.WorkspaceError, match="表にありません"):
        m.validate_ops([{"shelf": "api", "requests": [{"deleteSheet": {"sheetId": 1}}]}])
    with pytest.raises(gw.WorkspaceError, match="requests"):
        m.validate_ops([{"shelf": "api"}])
    assert m.validate_ops([{"shelf": "api", "requests": [{"repeatCell": {"range": "A1", "fields": "userEnteredFormat"}}], "why": "x"}]) == "sheet"
    assert m.api_uses_path == A.USES_FILE
    m.api_uses_path = tmp_path / "u.tsv"
    # do が成功した回だけ記録する（失敗・止めた回は記録しない）
    class C_:
        def __init__(self, res):
            self.res = res

        def call_webapp(self, url, **kw):
            return {"status_code": 200, "data": dict(self.res, version=m.engine_version())}
    st = {"engine_sid": "E" * 40, "engine_deploy_id": "DEP_1", "engine_url": "https://script.google.com/macros/s/x/exec", "engine_ver": m.engine_version(), "target": {"id": "A" * 44, "kind": "sheet", "name": "n"}}
    m._save(st)
    ops = [{"shelf": "api", "requests": [{"repeatCell": {"range": "A1", "fields": "userEnteredFormat"}}], "why": "青く"}]
    m._client = C_({"ok": False, "error": "x", "blocked": True, "target": {"id": "A" * 44, "name": "n", "kind": "sheet"}})
    m.do(ops)
    assert not (tmp_path / "u.tsv").exists()
    m._client = C_({"ok": True, "target": {"id": "A" * 44, "name": "n", "kind": "sheet", "url": "u", "sheet": "s"}, "changed": ["api x"], "notes": [], "remaining": [], "backup": 5})
    m.do(ops)
    assert (tmp_path / "u.tsv").read_text(encoding="utf-8").strip().endswith("repeatCell\t青く")


# ================================================================ 札・説明・手順書
def test_api_card_and_head_lines_say_use_api_when_there_is_no_shelf():
    s = gw.CATALOG.by_name["api"]
    assert s["danger"] == "消す" and [a["name"] for a in s["args"]] == ["requests", "why"] and s["searchable"]
    assert "batchUpdate" in s["words"] and len(s["words"]) <= 8
    import gas_ws_find as F
    for head in (F.HEAD_OK, F.HEAD_WEAK, F.HEAD_NONE):
        assert "api（Sheets API の batchUpdate" in head
    mcp = (HERE / "gas_mcp_server.py").read_text(encoding="utf-8")
    assert "棚に無ければ api（Sheets API の batchUpdate）" in mcp and 'shelf="api"' in mcp
    assert "棚に無ければ `api`" in (HERE / "WORKSPACE.md").read_text(encoding="utf-8")
    import gas_ws_check as K
    lines = K.mcp_doc_lines()
    assert all(n <= 4 for n in lines.values()) and sum(lines.values()) <= 16          # 説明の量は増やさない
    assert len(K.doc_shelf_names(gw.CATALOG)) <= 5


def test_common_files_still_have_no_shelf_names_after_api():
    assert C.find_hardcoded_names(gw.CATALOG) == []
    common = (HERE / "workspace_engine.gs").read_text(encoding="utf-8")
    for w in ("API_TYPES", "repeatCell", "apiScan_", "apiWalk_"):
        assert w not in common, w
    assert "var DYNAMIC = {};" in common


# ================================================================ エンジンの api（node）
def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const batches = [];
const mkSheet = function (name, id) { return { getName: function () { return name; }, getSheetId: function () { return id; } }; };
let sheets = [mkSheet('名簿', 11), mkSheet('売上', 22)];
const ss = { getId: function () { return 'S'; }, getSheets: function () { return sheets; }, getSheetByName: function (n) { return sheets.filter(function (s) { return s.getName() === n; })[0] || null; } };
const store = {};
const ctxv = vm.createContext({ console, batches, ss, mkSheet, PropertiesService: { getScriptProperties: function () { return { getProperty: function (k) { return store[k] === undefined ? null : store[k]; }, setProperty: function (k, v) { store[k] = v; }, deleteProperty: function (k) { delete store[k]; } }; } }, setSheets: function (a) { sheets = a; },
  Sheets: { Spreadsheets: { batchUpdate: function (b) { batches.push(b.requests); if (ctxv.__after) ctxv.__after(); return {}; } } },
  DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext('var __out = null;\n' + input.script, ctxv);
console.log(JSON.stringify(ctxv.__out));
"""


def _run(script):
    files = [t for _, t in gw._engine_texts()]
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps({"files": files, "script": script}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


CTX = "var ctx = { wideKey: 'k1', ss: ss, ok: false, sheetName: '', changed: [], notes: [], createdSheets: [] };\n"
needs_node = pytest.mark.skipif(not _node_ok(), reason="node が無い")


@needs_node
def test_engine_converts_a1_sheet_names_and_colors_before_firing():
    out = _run(CTX + """
      SHELF['api'](ctx, { shelf: 'api', why: '青く', requests: [
        { repeatCell: { range: 'A1:C1', cell: { userEnteredFormat: { backgroundColor: '#4285F4', textFormat: { foregroundColor: '赤' } } }, fields: 'userEnteredFormat' } },
        { repeatCell: { range: '売上!B2:B20', cell: {}, fields: 'x' } },
        { repeatCell: { range: "'名簿'!A:A", cell: {}, fields: 'x' } },
        { repeatCell: { range: '3:5', cell: {}, fields: 'x' } },
        { copyPaste: { source: 'A1:B2', destination: '売上!D1', pasteType: 'PASTE_NORMAL' } },
        { addConditionalFormatRule: { rule: { ranges: ['A1:A9', '売上!C2:C3'], booleanRule: { condition: { type: 'NUMBER_GREATER', values: [{ userEnteredValue: '5' }] }, format: { backgroundColor: 'yellow' } } }, index: 0 } },
        { updateDimensionProperties: { range: { sheetId: '売上', dimension: 'COLUMNS', startIndex: 0, endIndex: 1 }, properties: { hiddenByUser: true }, fields: 'hiddenByUser' } },
        { addChart: { chart: { spec: {}, position: { overlayPosition: { anchorCell: 'H2' } } } } }
      ] });
      __out = { b: batches[0], changed: ctx.changed, cur: ctx.curSheet };
    """)
    b = out["b"]
    assert b[0]["repeatCell"]["range"] == {"sheetId": 11, "startColumnIndex": 0, "startRowIndex": 0, "endColumnIndex": 3, "endRowIndex": 1}      # 既定は今のシート（先頭）
    fmt = b[0]["repeatCell"]["cell"]["userEnteredFormat"]
    assert fmt["backgroundColor"] == pytest.approx({"red": 0x42 / 255, "green": 0x85 / 255, "blue": 0xF4 / 255})
    assert fmt["textFormat"]["foregroundColor"]["red"] > 0.7 and fmt["textFormat"]["foregroundColor"]["blue"] < 0.3                       # 色の名前（赤）
    assert b[1]["repeatCell"]["range"] == {"sheetId": 22, "startColumnIndex": 1, "startRowIndex": 1, "endColumnIndex": 2, "endRowIndex": 20}  # シート名の接頭辞
    assert b[2]["repeatCell"]["range"] == {"sheetId": 11, "startColumnIndex": 0, "endColumnIndex": 1}                                    # 列全体（引用符つき）
    assert b[3]["repeatCell"]["range"] == {"sheetId": 11, "startRowIndex": 2, "endRowIndex": 5}                                           # 行全体
    assert b[4]["copyPaste"]["source"]["sheetId"] == 11 and b[4]["copyPaste"]["destination"] == {"sheetId": 22, "startColumnIndex": 3, "startRowIndex": 0, "endColumnIndex": 4, "endRowIndex": 1}
    rg = b[5]["addConditionalFormatRule"]["rule"]
    assert [r["sheetId"] for r in rg["ranges"]] == [11, 22] and rg["booleanRule"]["format"]["backgroundColor"]["red"] > 0.9               # ranges[] の A1 と、色の名前
    assert b[6]["updateDimensionProperties"]["range"] == {"sheetId": 22, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}          # DimensionRange はシート名だけ ID に
    assert b[7]["addChart"]["chart"]["position"]["overlayPosition"]["anchorCell"] == {"sheetId": 11, "rowIndex": 1, "columnIndex": 7}      # anchorCell も A1 で
    assert out["changed"] == ["api repeatCell・copyPaste・addConditionalFormatRule・updateDimensionProperties・addChart を撃った（8 件）：青く"] and out["cur"] == "名簿"


@needs_node
def test_engine_refuses_unknown_types_and_bad_ranges_and_missing_sheets():
    out = _run(CTX + """
      var r = {};
      var go = function (k, requests) { r[k] = null; try { SHELF['api'](ctx, { shelf: 'api', requests: requests }); r[k] = 'no error'; } catch (e) { r[k] = String(e.message); } };
      go('unknown', [{ deleteSheet: { sheetId: 1 } }]);
      go('shape', [{ repeatCell: {}, addBanding: {} }]);
      go('deny', [{ updateSheetProperties: { properties: {}, fields: 'gridProperties.hideGridlines' } }]);
      go('badRange', [{ repeatCell: { range: 'ほげ', fields: 'x' } }]);
      go('noSheet', [{ repeatCell: { range: '存在しない!A1', fields: 'x' } }]);
      go('empty', []);
      __out = { r: r, fired: batches.length };
    """)
    r = out["r"]
    assert "表にありません" in r["unknown"] and "形です" in r["shape"] and "戻らない物" in r["deny"] and "読めません" in r["badRange"] and "シート「存在しない」がありません" in r["noSheet"]
    assert "配列" in r["empty"]
    assert out["fired"] == 0                                                                    # 断った物は 1 つも撃たない


@needs_node
def test_engine_stops_delete_types_without_ok_and_fires_with_ok_after_one_stop():
    out = _run(CTX + """
      var ops = { shelf: 'api', requests: [{ repeatCell: { range: 'A1', fields: 'x' } }, { deleteDimension: { range: { sheetId: '名簿', dimension: 'ROWS', startIndex: 2, endIndex: 3 } } }] };
      var blocked = null; try { SHELF['api'](ctx, ops); } catch (e) { blocked = { msg: String(e.message), isBlocked: !!e.isBlocked }; }
      var fired0 = batches.length;
      ctx.ok = true; SHELF['api'](ctx, ops);       // ok なしの下見が 1 回目に数えられるので、同じ ops を ok=True で撃てば通る
      var again = null; try { SHELF['api'](ctx, ops); again = 'no error'; } catch (e) { again = String(e.message); }    // 通した後の 3 回目は、また止まる（指紋は 1 回きり）
      __out = { blocked: blocked, fired0: fired0, fired1: batches.length, again: again };
    """)
    assert out["blocked"]["isBlocked"] and "deleteDimension" in out["blocked"]["msg"] and "ok=True" in out["blocked"]["msg"]
    assert out["fired0"] == 0 and out["fired1"] == 1                                            # ok なしでは 1 つも撃たない
    assert "広い削除" in out["again"] and "もう一度 ok=True" in out["again"]


@needs_node
def test_engine_decides_backup_sheets_and_touch_items_from_the_requests():
    out = _run("""
      var mk = function (extra) { return { ss: ss, sheetName: '', changed: [], notes: [], createdSheets: [], ok: true }; };
      var names = function (op) { return touchedSheets_(mk(), [op]).map(function (s) { return s.getName(); }); };
      __out = {
        none: names({ shelf: 'api', requests: [{ repeatCell: { range: 'A1', fields: 'x' } }] }),
        named: names({ shelf: 'api', requests: [{ repeatCell: { range: '売上!A1', fields: 'x' } }] }),
        byName: names({ shelf: 'api', requests: [{ updateSheetProperties: { properties: { sheetId: '売上' }, fields: 'title' } }] }),
        byId: names({ shelf: 'api', requests: [{ addBanding: { bandedRange: { range: { sheetId: 22 } } } }] }),
        unknownId: names({ shelf: 'api', requests: [{ addBanding: { bandedRange: { range: { sheetId: 999 } } } }] }),
        two: names({ shelf: 'api', requests: [{ repeatCell: { range: '名簿!A1', fields: 'x' } }, { copyPaste: { source: '名簿!A1', destination: '売上!A1' } }] }).sort(),
        all: names({ shelf: 'api', requests: [{ findReplace: { find: 'a', replacement: 'b', allSheets: true } }] }).sort(),
        items: sideItems_([{ shelf: 'api', requests: [{ addProtectedRange: {} }, { addChart: {} }, { repeatCell: {} }] }]).sort(),
        itemsNone: sideItems_([{ shelf: 'api', requests: [{ repeatCell: {} }] }]),
        card: CATALOG['api'].touch
      };
    """)
    assert out["none"] == ["名簿"] and out["named"] == ["売上"] and out["byName"] == ["売上"] and out["byId"] == ["売上"]
    assert out["unknownId"] == ["名簿", "売上"]                                                  # 決められなければ全部を控える
    assert sorted(out["two"]) == sorted(["売上", "名簿"]) and sorted(out["all"]) == sorted(["売上", "名簿"])
    assert out["items"] == ["グラフ", "保護"] and out["itemsNone"] == []                          # 触る物は型の表から（記録するのは触る物だけ）
    assert not any(x in out["card"] for x in ("値", "書式", "シート構成", "固定"))               # 札は指紋で「変更なし」にしない側（api は必ず変更として数える）


@needs_node
def test_engine_records_sheets_added_by_the_call_so_failure_and_undo_remove_them():
    out = _run(CTX + """
      __after = function () { setSheets([mkSheet('名簿', 11), mkSheet('売上', 22), mkSheet('新しい', 33)]); };
      SHELF['api'](ctx, { shelf: 'api', requests: [{ updateSheetProperties: { properties: { sheetId: 11, title: '名簿' }, fields: 'title' } }] });
      __out = { created: ctx.createdSheets };
    """)
    assert out["created"] == ["新しい"]


@needs_node
def test_api_never_counts_as_noop():
    out = _run("""
      var ctx = { kind: 'sheet', createdSheets: [], changed: ['api repeatCell を撃った'] };
      __out = { noop: isNoop_([{ shelf: 'api' }], { sheets: [{ id: 1 }], before: { 1: { rows: 1, cols: 1, d: 'a' } }, after: { 1: { rows: 1, cols: 1, d: 'a' } } }, ctx) };
    """)
    assert out["noop"] is False                           # 指紋が同じでも（隠し・保護 等は指紋に出ない）変更なしにしない
