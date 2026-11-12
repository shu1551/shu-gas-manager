# -*- coding: utf-8 -*-
"""
戻しの拡張（脇の状態）の試験。エンジンの JS を node でそのまま動かし、Google の部品は偽物（呼び出しを数える・記録する）にする。
  ・触る: に出た項目だけを記録する（フィルタだけは常に・無いシートでは何もしない＝API を呼ばない）
  ・戻すときは「今ある物を消してから、記録のとおりに付け直す」（消す→付ける→隠しの順）
  ・保護の編集者が戻せないときは、一覧なしで付け直して知らせる
  ・台帳に残す形（脇の状態は別プロパティ）と、台帳から落ちたとき一緒に消える
実機の A・B（14 項目）は ws_trial/side_probe.py。
"""

import json
import subprocess

import pytest

import gas_workspace as gw


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _node_ok(), reason="node が無い")

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = {}, deleted = [], getCalls = [], batchCalls = [];
const Sheets = { Spreadsheets: {
  get: function (id, params) { getCalls.push(params); return JSON.parse(JSON.stringify(input.getResponse(params))); },
  batchUpdate: function (body, id) { batchCalls.push(body.requests); if (ctxv.throwOnEditors && JSON.stringify(body.requests).indexOf('editors') >= 0) throw new Error('editors'); return {}; } } };
const ctxv = vm.createContext({ console, Sheets, SpreadsheetApp: { flush: function () {} }, Utilities: { sleep: function () {} }, store, deleted, getCalls, batchCalls, __input: input,
  PropertiesService: { getScriptProperties: function () { return { getProperty: function (k) { return store[k] === undefined ? null : store[k]; }, setProperty: function (k, v) { store[k] = v; }, deleteProperty: function (k) { deleted.push(k); delete store[k]; } }; } },
  DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext('var __responses = null;', ctxv);
ctxv.__input.getResponse = null;
console.log('loaded');
"""


def _engine_files():
    return [t for _, t in gw._engine_texts()]


def _run(script_js, **data):
    """script_js は vm の中で実行され、結果を __out に入れる。data は __input に入る"""
    prog = HARNESS.replace("console.log('loaded');", "") + r"""
input.getResponse = new Function('params', input.getResponseSrc || 'return {};');
ctxv.__input = input;
vm.runInContext(input.script, ctxv);
console.log(JSON.stringify(ctxv.__out));
"""
    payload = {"files": _engine_files(), "script": "var __out = null;\n" + script_js, "getResponseSrc": data.pop("get_src", "return {};")}
    payload.update(data)
    r = subprocess.run(["node", "-e", prog], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


FAKE_SHEET = """
function fakeSheet(id, name, filter) { return { getSheetId: function () { return id; }, getName: function () { return name; }, getFilter: function () { return filter ? {} : null; }, getMaxRows: function () { return 100; }, getMaxColumns: function () { return 26; } }; }
"""


def test_side_items_come_only_from_touch_list():
    out = _run(FAKE_SHEET + """
      CATALOG['x.hide'] = { kind: 'sheet', touch: ['値', '隠し', 'グループ'], backup: ['今'], danger: '' };
      CATALOG['x.keep'] = { kind: 'sheet', touch: ['値', 'フィルタ', '書式'], backup: ['今'], danger: '' };
      __out = { hide: sideItems_([{ shelf: 'x.hide' }, { shelf: 'x.keep' }]).sort(), none: sideItems_([{ shelf: 'x.keep' }]), unknown: sideItems_([{ shelf: 'nothing' }]) };
    """)
    assert out == {"hide": ["グループ", "隠し"], "none": [], "unknown": []}


def test_capture_calls_no_api_without_items_or_filter_and_only_the_filter_when_present():
    out = _run(FAKE_SHEET + """
      var bk1 = [{ id: 1 }];
      captureSide_({ getId: function () { return 'S'; } }, [fakeSheet(1, '名簿', false)], bk1, []);
      var c0 = getCalls.length;
      var bk2 = [{ id: 1 }];
      captureSide_({ getId: function () { return 'S'; } }, [fakeSheet(1, '名簿', true)], bk2, []);
      __out = { noCall: c0, calls: getCalls.length, params: getCalls[0], side1: bk1[0].side || null, side2: bk2[0].side };
    """, get_src="return { sheets: [{ properties: { sheetId: 1 }, basicFilter: { range: { sheetId: 1, startRowIndex: 0 }, criteria: { '1': { hiddenValues: ['x'] } } } }] };")
    assert out["noCall"] == 0 and out["side1"] is None                      # フィルタの無いシートでは何もしない
    assert out["calls"] == 1 and out["params"]["fields"] == "sheets(properties(sheetId),basicFilter)" and "ranges" not in out["params"]
    assert out["side2"] == {"filter": {"range": {"sheetId": 1, "startRowIndex": 0}, "criteria": {"1": {"hiddenValues": ["x"]}}}}


def test_capture_all_items_reads_with_the_needed_fields_and_hidden_rows_in_a_separate_call():
    out = _run(FAKE_SHEET + """
      var bk = [{ id: 1 }];
      captureSide_({ getId: function () { return 'S'; } }, [fakeSheet(1, '名簿', false)], bk, ['隠し', 'グループ', '保護', '名前', 'タブ色', 'グラフ']);
      __out = { calls: getCalls.length, p0: getCalls[0], p1: getCalls[1], side: bk[0].side, book: bk.book };
    """, get_src="""
      if (params.ranges) return { sheets: [{ properties: { sheetId: 1 }, data: [{ rowMetadata: [{}, { hiddenByUser: true }, { hiddenByUser: true }, {}, { hiddenByUser: true }] }, { columnMetadata: [{}, {}, { hiddenByUser: true }] }] }] };
      return { sheets: [{ properties: { sheetId: 1, hidden: true, tabColorStyle: { rgbColor: { red: 1 } } },
        rowGroups: [{ range: { sheetId: 1, dimension: 'ROWS', startIndex: 9, endIndex: 12 }, depth: 1 }], columnGroups: [],
        protectedRanges: [{ protectedRangeId: 7, range: { sheetId: 1 }, warningOnly: true, editors: { users: ['a@x'] } }],
        charts: [{ chartId: 5, spec: { title: '試験' }, position: { overlayPosition: {} } }] }],
        namedRanges: [{ namedRangeId: 'n', name: '金額列', range: { sheetId: 1 } }] };
    """)
    assert out["calls"] == 2
    p0, p1 = out["p0"], out["p1"]
    assert "ranges" not in p0 and "includeGridData" not in p0                       # 保護・グラフ・名前付き範囲は範囲を絞らずに読む（絞ると重なる物しか返らない）
    for piece in ("hidden", "tabColorStyle", "rowGroups", "columnGroups", "protectedRanges", "charts", "namedRanges"):
        assert piece in p0["fields"], piece
    assert p1["includeGridData"] is True and p1["ranges"] == ["'名簿'!A:A", "'名簿'!1:1"] and "hiddenByUser" in p1["fields"]
    s = out["side"]
    assert s["hidden"] is True and s["hr"] == [[1, 3], [4, 5]] and s["hc"] == [[2, 3]]                  # 隠した行・列は「連なり」で記録
    assert s["tab"] == {"rgbColor": {"red": 1}} and s["rg"][0]["depth"] == 1 and s["cg"] == []
    assert s["prot"] == [{"range": {"sheetId": 1}, "warningOnly": True, "editors": {"users": ["a@x"]}}]   # protectedRangeId は記録しない
    assert s["charts"] == [{"spec": {"title": "試験"}, "position": {"overlayPosition": {}}}]
    assert out["book"] == {"named": [{"name": "金額列", "range": {"sheetId": 1}}]}


def test_side_record_is_kept_in_its_own_property_and_dropped_with_the_ledger_entry():
    out = _run(FAKE_SHEET + """
      var bk = [{ id: 1, name: '名簿', tab: 'ws1_1', side: { filter: { a: 1 } } }]; bk.book = { named: [] };
      var rec = packSide_(bk, ['名前']);
      var stripped = stripSide_(bk);
      setJson_('SIDE_5', rec);
      var it = { n: 5, hasSide: true, sheets: stripped };
      var loaded = loadSide_(it);
      var l = { seq: 0, items: [] };
      for (var i = 1; i <= LEDGER_MAX + 2; i++) l.items.push({ n: i, hasSide: i === 1, what: 'x' });
      ledgerSave_(l);
      __out = { rec: rec, noSideInStripped: !('side' in stripped[0]), loadedSide: loaded[0].side, loadedBook: loaded.book, nothing: packSide_([{ id: 1 }], []), deleted: deleted.slice(), kept: l.items.length, max: LEDGER_MAX };
    """)
    assert out["rec"] == {"sheets": {"1": {"filter": {"a": 1}}}, "book": {"named": []}, "items": ["名前"]}
    assert out["noSideInStripped"] and out["loadedSide"] == {"filter": {"a": 1}} and out["loadedBook"] == {"named": []}
    assert out["nothing"] is None                                                 # 記録する物が無ければ何も作らない
    assert out["deleted"] == ["SIDE_1"] and out["kept"] == out["max"]               # 台帳から落ちた記録の脇の状態も消える


RESTORE_GET = """
  var r = { sheets: [{ properties: { sheetId: 1 }, rowGroups: [{ range: { sheetId: 1, dimension: 'ROWS', startIndex: 0, endIndex: 2 }, depth: 1 }], columnGroups: [],
    protectedRanges: [{ protectedRangeId: 5 }], charts: [{ chartId: 9 }] }], namedRanges: [{ namedRangeId: 'n1' }] };
  return r;
"""

RESTORE_BK = """
  var bk = [{ id: 1, side: { hr: [[8, 9]], hc: [[2, 3]], tab: { rgbColor: { red: 1 } }, hidden: true,
    rg: [{ range: { sheetId: 1, dimension: 'ROWS', startIndex: 9, endIndex: 12 }, depth: 1, collapsed: true }], cg: [],
    prot: [{ range: { sheetId: 1 }, warningOnly: false, editors: { users: ['a@x'] } }], charts: [{ spec: { title: '試験' }, position: { overlayPosition: {} } }] } }];
  bk.book = { named: [{ name: '金額列', range: { sheetId: 1 } }] };
  var ss = { getId: function () { return 'S'; }, getSheets: function () { return [fakeSheet(1, '名簿', false)]; } };
"""


def test_restore_deletes_what_is_there_then_adds_the_record_then_matches_hidden():
    out = _run(FAKE_SHEET + RESTORE_BK + """
      var notes = []; restoreSide_(ss, bk, notes);
      __out = { reqs: batchCalls[0].map(function (q) { return Object.keys(q)[0]; }), calls: batchCalls.length, notes: notes, getFields: getCalls[0].fields, all: batchCalls[0] };
    """, get_src=RESTORE_GET)
    kinds = out["reqs"]
    assert out["calls"] == 1                                                         # 1 回の batchUpdate
    dels = [i for i, k in enumerate(kinds) if k.startswith("delete")]
    adds = [i for i, k in enumerate(kinds) if k.startswith("add") or k == "updateDimensionGroup" or k == "setBasicFilter"]
    assert dels and max(dels) < min(adds)                                            # 消してから付け直す
    assert "setBasicFilter" not in kinds                                             # フィルタは batchUpdate でなく SpreadsheetApp で付け直す（隠す行が反映される）
    assert set(kinds) >= {"deleteDimensionGroup", "deleteProtectedRange", "deleteEmbeddedObject", "deleteNamedRange", "addDimensionGroup", "updateDimensionGroup",
                          "addProtectedRange", "addChart", "addNamedRange", "updateSheetProperties", "updateDimensionProperties"}
    assert kinds[-1] == "updateSheetProperties"                                      # シートの隠しは最後に合わせる
    dp = [q["updateDimensionProperties"] for q in out["all"] if "updateDimensionProperties" in q]
    rows = [d for d in dp if d["range"]["dimension"] == "ROWS"]
    assert rows[0]["properties"] == {"hiddenByUser": False} and rows[0]["range"]["endIndex"] == 100               # 全部出してから
    assert rows[1]["properties"] == {"hiddenByUser": True} and [rows[1]["range"]["startIndex"], rows[1]["range"]["endIndex"]] == [8, 9]   # 記録した行を隠す
    assert "rowGroups" in out["getFields"] and "protectedRanges(protectedRangeId)" in out["getFields"] and "namedRanges(namedRangeId)" in out["getFields"]
    assert out["notes"] == []


def test_restore_protection_without_editors_when_they_cannot_be_restored():
    out = _run(FAKE_SHEET + RESTORE_BK + """
      throwOnEditors = true;
      var notes = []; restoreSide_(ss, bk, notes);
      __out = { calls: batchCalls.length, second: JSON.stringify(batchCalls[1]), first: JSON.stringify(batchCalls[0]), notes: notes };
    """, get_src=RESTORE_GET)
    assert out["calls"] == 2 and "editors" in out["first"] and "editors" not in out["second"] and "addProtectedRange" in out["second"]
    assert out["notes"] == ["保護の「編集できる人」の一覧は戻せませんでした（保護そのものは付け直しました）"]


def test_restore_does_nothing_when_nothing_was_recorded_and_other_errors_still_raise():
    out = _run(FAKE_SHEET + """
      var ss = { getId: function () { return 'S'; } };
      restoreSide_(ss, [{ id: 1 }], []); restoreSide_(ss, [], []);
      __out = { gets: getCalls.length, batches: batchCalls.length };
    """)
    assert out == {"gets": 0, "batches": 0}
    out = _run(FAKE_SHEET + """
      var ss = { getId: function () { return 'S'; } };
      Sheets.Spreadsheets.batchUpdate = function () { throw new Error('boom'); };
      var bk = [{ id: 1, side: { tab: null } }];
      __out = null; try { restoreSide_(ss, bk, []); __out = 'no error'; } catch (e) { __out = String(e.message); }
    """)
    assert out == "boom"                                                              # 編集者の件以外の失敗は握りつぶさない（do の失敗は呼び側が控えから戻す）


def test_shelf_touch_items_that_matter_exist_in_the_catalog_vocabulary():
    import gas_ws_catalog as C
    for item in ("隠し", "グループ", "保護", "名前", "タブ色", "グラフ", "フィルタ"):
        assert item in C.TOUCH_ITEMS


FILTER_SHEET = """
var created = [];
function fsheet(id) {
  var cur = { f: { remove: function () { created.push('remove'); } } };
  return { getSheetId: function () { return id; }, getMaxRows: function () { return 100; }, getMaxColumns: function () { return 26; }, getFilter: function () { return cur.f; },
    getRange: function (r, c, nr, nc) { return { createFilter: function () { created.push('create ' + r + ',' + c + ',' + nr + ',' + nc); return { setColumnFilterCriteria: function (col, crit) { created.push('crit ' + col + ' ' + JSON.stringify(crit)); } }; } }; } };
}
var SpreadsheetApp = { flush: function () { created.push('flush'); }, newFilterCriteria: function () { var o = { hv: null, setHiddenValues: function (v) { o.hv = v; return o; }, build: function () { return { hidden: o.hv }; } }; return o; } };
"""


def test_filter_is_rebuilt_with_spreadsheetapp_so_hidden_rows_apply_and_unsupported_criteria_are_noted():
    out = _run(FAKE_SHEET + FILTER_SHEET + """
      var ss = { getId: function () { return 'S'; }, getSheets: function () { return [fsheet(1)]; } };
      var notes = [];
      restoreSide_(ss, [{ id: 1, side: { filter: { range: { sheetId: 1, startRowIndex: 0, endRowIndex: 20, startColumnIndex: 0, endColumnIndex: 6 }, criteria: { '1': { hiddenValues: ['会員14'] } } } } }], notes);
      var n2 = [];
      restoreSide_(ss, [{ id: 1, side: { filter: { range: { sheetId: 1, startRowIndex: 0, endRowIndex: 20, startColumnIndex: 0, endColumnIndex: 6 }, criteria: { '2': { condition: { type: 'TEXT_EQ' } } } } } }], n2);
      __out = { log: created, notes: notes, n2: n2, batches: batchCalls.length };
    """)
    assert out["log"][:3] == ["remove", "create 1,1,20,6", 'crit 2 {"hidden":["会員14"]}']        # 範囲は A1:F20・B 列（0 始まりの 1 → 2 列目）の隠す値
    assert out["notes"] == [] and out["batches"] == 0                                               # フィルタだけなら batchUpdate は撃たない
    assert len(out["n2"]) == 1 and "条件式・色" in out["n2"][0]


def test_transient_internal_error_is_retried_once_but_other_errors_are_not():
    out = _run(FAKE_SHEET + """
      var ss = { getId: function () { return 'S'; } };
      var calls = 0;
      Sheets.Spreadsheets.batchUpdate = function (b) { calls++; if (calls === 1) throw new Error('Internal error encountered.'); return {}; };
      var notes = []; restoreSide_(ss, [{ id: 1, side: { tab: null } }], notes);
      var c1 = calls;
      calls = 0;
      Sheets.Spreadsheets.batchUpdate = function (b) { calls++; throw new Error('Internal error encountered.'); };
      var again = null; try { restoreSide_(ss, [{ id: 1, side: { tab: null } }], []); } catch (e) { again = String(e.message); }
      __out = { c1: c1, notes: notes, twice: calls, again: again };
    """)
    assert out["c1"] == 2 and out["notes"] == []                                      # 一時的な内部エラーは 1 回だけ撃ち直す
    assert out["twice"] == 2 and "Internal error" in out["again"]                    # 続けて出れば（撃ち直しは 1 回まで）エラーとして返す


def test_chart_that_the_api_cannot_add_is_rebuilt_with_spreadsheetapp_or_reported():
    out = _run(FAKE_SHEET + """
      var made = [];
      function chartSheet() {
        var sh = fakeSheet(1, '名簿', false);
        sh.getRange = function (r, c, nr, nc) { return 'R' + r + ',' + c + ',' + nr + ',' + nc; };
        sh.newChart = function () { var o = { calls: [] };
          ['setChartType', 'addRange', 'setPosition', 'setOption'].forEach(function (m) { o[m] = function () { o.calls.push([m].concat([].slice.call(arguments))); return o; }; });
          o.build = function () { return o; }; return o; };
        sh.insertChart = function (c) { made.push(c.calls); };
        return sh;
      }
      var Charts = { ChartType: { COLUMN: 'COLUMN', PIE: 'PIE' } };
      var sh1 = chartSheet();
      var ss = { getId: function () { return 'S'; }, getSheets: function () { return [sh1]; } };
      var log = [];
      Sheets.Spreadsheets.get = function () { return { sheets: [{ properties: { sheetId: 1 }, charts: [{ chartId: 9 }] }] }; };
      Sheets.Spreadsheets.batchUpdate = function (b) {
        var kinds = b.requests.map(function (q) { return Object.keys(q)[0]; });
        log.push(kinds);
        if (kinds.indexOf('addChart') >= 0) throw new Error('Internal error encountered.');
        return {};
      };
      var column = { spec: { title: '試験', basicChart: { chartType: 'COLUMN', domains: [{ domain: { sourceRange: { sources: [{ sheetId: 1, startRowIndex: 0, endRowIndex: 20, startColumnIndex: 5, endColumnIndex: 6 }] } } }] } },
                     position: { overlayPosition: { anchorCell: { sheetId: 1, rowIndex: 1, columnIndex: 7 } } } };
      var notes = [];
      restoreSide_(ss, [{ id: 1, side: { charts: [column] } }], notes);
      var n2 = [];
      restoreSide_(ss, [{ id: 1, side: { charts: [{ spec: { scorecardChart: {} }, position: {} }] } }], n2);
      __out = { log: log, made: made, notes: notes, n2: n2 };
    """)
    log = out["log"]
    assert "addChart" in log[0] and log[1] == log[0] and "addChart" not in log[2]       # 通らない → 撃ち直し → 消す物を先に通す
    assert out["made"][0] == [["setChartType", "COLUMN"], ["addRange", "R1,6,20,1"], ["setPosition", 2, 8, 0, 0], ["setOption", "title", "試験"]]
    assert out["notes"] == []
    assert len(out["n2"]) == 1 and "グラフを付け直せませんでした" in out["n2"][0]                # 作れない形は知らせる
