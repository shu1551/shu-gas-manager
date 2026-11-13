# -*- coding: utf-8 -*-
"""
広い削除は ok=True でも道具の側で 1 回止まる（試験設計書 第 3.5 節 (1)・第 13 章の決定）の試験。エンジンの JS を node でそのまま動かす。
  ・同じ相手・同じ ops が直前（10 分以内）に 1 回止まっていなければ、ok=True でも止める。ok なしの下見も 1 回目に数える（ふつうの流れは今と同じ 2 往復）
  ・止めた ops の指紋だけを覚え、同じ ops が ok=True で来たら 1 回だけ通す。10 分たつと忘れる。ほかの ops には効かない
  ・広さの目安: シートの値のある範囲を全部覆う・表の外まで及ぶ・明細の半分より多い行
  ・シートごと消す・api の消す型・表の外／半分超の rows.delete は広い削除、ふつうの削除（狭い）は今までどおり ok だけで通る
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
const store = {};
const ctxv = vm.createContext({ console, store,
  PropertiesService: { getScriptProperties: function () { return { getProperty: function (k) { return store[k] === undefined ? null : store[k]; }, setProperty: function (k, v) { store[k] = v; }, deleteProperty: function (k) { delete store[k]; } }; } },
  DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext('var __now = 1000000; Date.now = function () { return __now; }; var __out = null;\n' + input.script, ctxv);
console.log(JSON.stringify(ctxv.__out));
"""


def _run(script):
    files = [t for _, t in gw._engine_texts()]
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps({"files": files, "script": script}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


TRY = """
function attempt(ctx, wide) { try { guardDelete_(ctx, 'シート「x」を削除します', wide); return 'pass'; } catch (e) { return e.isBlocked ? 'blocked: ' + e.message : 'error ' + e.message; } }
function mk(ok, key) { return { ok: ok, wideKey: key || 'k1' }; }
"""


def test_preview_without_ok_counts_as_the_first_stop_so_the_normal_flow_stays_two_round_trips():
    out = _run(TRY + """
      var a = attempt(mk(false), true);       // 下見（ok なし）
      var b = attempt(mk(true), true);        // 承認の後（ok=True）→ 通る
      var c = attempt(mk(true), true);        // 通した後の同じ ops は、また止まる（指紋は 1 回きり）
      __out = { a: a, b: b, c: c };
    """)
    assert out["a"].startswith("blocked") and "広い削除" in out["a"] and "「消してよい」の承認" in out["a"]
    assert out["b"] == "pass"
    assert out["c"].startswith("blocked") and "もう一度 ok=True" in out["c"]


def test_ok_true_from_the_start_is_stopped_once_then_passes_when_the_same_ops_comes_again():
    out = _run(TRY + """
      var a = attempt(mk(true), true), b = attempt(mk(true), true);
      __out = { a: a, b: b };
    """)
    assert out["a"].startswith("blocked") and "「消してよい」の承認" not in out["a"]          # ok は付いているので、見て確かめてもう一度、とだけ言う
    assert out["b"] == "pass"


def test_other_ops_and_expired_stops_do_not_count():
    out = _run(TRY + """
      attempt(mk(false, 'ops-A'), true);
      var other = attempt(mk(true, 'ops-B'), true);                 // 止まったのは ops-A だけ。ops-B は別
      var same = (function () { __now += 11 * 60 * 1000; return attempt(mk(true, 'ops-A'), true); })();   // 10 分を過ぎると覚えていない
      var fresh = (function () { return attempt(mk(true, 'ops-A'), true); })();   // 止まった直後なので通る
      __out = { other: other, same: same, fresh: fresh, kept: Object.keys(JSON.parse(store['WIDE'])) };
    """)
    assert out["other"].startswith("blocked") and out["same"].startswith("blocked") and out["fresh"] == "pass"
    assert "ops-A" not in out["kept"]


def test_old_stops_are_forgotten_so_the_record_does_not_grow():
    out = _run(TRY + """
      for (var i = 0; i < 30; i++) { attempt(mk(false, 'k' + i), true); __now += 60 * 1000; }
      __out = { n: Object.keys(JSON.parse(store['WIDE'])).length };
    """)
    assert out["n"] <= 11                                                                       # 10 分より古い物は消える


def test_narrow_deletes_keep_the_old_rule_ok_only_and_do_not_leave_a_record():
    out = _run(TRY + """
      var a = attempt(mk(false), false), b = attempt(mk(true), false), c = attempt(mk(true), false);
      __out = { a: a, b: b, c: c, rec: store['WIDE'] || null };
    """)
    assert out["a"].startswith("blocked") and "ok=True が要ります" in out["a"] and out["b"] == "pass" and out["c"] == "pass"
    assert out["rec"] is None


def test_wide_measures_whole_data_range_outside_table_and_more_than_half_the_rows():
    out = _run("""
      var table = { headerRow: 1, firstCol: 1, lastCol: 6, firstData: 2, lastData: 20, totalRow: 21 };
      findTable_ = function () { return table; };
      var rg = function (r1, c1, r2, c2) { return { getRow: function () { return r1; }, getColumn: function () { return c1; }, getLastRow: function () { return r2; }, getLastColumn: function () { return c2; } }; };
      var sh = { getDataRange: function () { return rg(1, 1, 21, 6); } };
      __out = {
        whole: wideRange_(sh, rg(1, 1, 21, 6)), wholeBig: wideRange_(sh, rg(1, 1, 1000, 26)),
        inside: wideRange_(sh, rg(2, 2, 10, 4)), insideEdge: wideRange_(sh, rg(2, 6, 20, 6)),
        belowTable: wideRange_(sh, rg(2, 2, 25, 4)), rightOfTable: wideRange_(sh, rg(2, 2, 10, 8)), aboveHeader: (function () { var keep = table.headerRow; table.headerRow = 3; var r = wideRange_({ getDataRange: function () { return rg(1, 1, 30, 10); } }, rg(1, 1, 5, 3)); table.headerRow = keep; return r; })(),
        rows9: wideRowCount_(table, 9), rows10: wideRowCount_(table, 10), noTable: wideRowCount_(null, 99)
      };
    """)
    assert out["whole"] and out["wholeBig"]                                  # シートの値のある範囲を全部覆う
    assert not out["inside"] and not out["insideEdge"]                       # 表の中だけ（ふつうの消去）は狭い
    assert out["belowTable"] and out["rightOfTable"] and out["aboveHeader"]  # 表の外まで及ぶ
    assert not out["rows9"] and out["rows10"] and not out["noTable"]        # 明細 19 行のうち 9 行は狭い・10 行（半分より多い）は広い


def test_every_wide_shelf_passes_wide_to_guard_delete_and_cards_still_match_the_guard():
    import re
    from pathlib import Path
    src = {p.name: p.read_text(encoding="utf-8") for p in (Path(gw.HERE) / "ws_shelves").glob("*.gs")}
    assert "guardDelete_(ctx, 'シート「' + op.name + '」を削除します', true, '1 枚')" in src["sheet_sheet.gs"]
    assert src["sheet_range.gs"].count("wideRange_(sh, rg),") == 2                       # clear.values・clear.all
    assert "wideRowCount_(" in src["sheet_filter.gs"] and "wideRowCount_(tw, nums.length)" in src["sheet_rows.gs"]
    assert "を撃ちます（' + info.danger.length + ' 件）', true, info.danger.length + ' 件')" in src["api.gs"]           # api の消す型
    import gas_ws_catalog as C
    assert C.check(gw.CATALOG) == []                                                    # 札の「危ない: 消す」と本文の守りの一致は崩れていない


def test_stop_message_puts_what_and_how_many_first_so_a_long_list_cannot_push_it_out():
    out = _run(TRY + """
      var long = ''; for (var i = 0; i < 40; i++) long += i + '行目「あいう」、';
      try { guardDelete_(mk(true, 'long'), long, true, '40 行'); __out = 'pass'; } catch (e) { __out = e.message; }
    """)
    assert out.startswith("広い削除です。消える数: 40 行。") and len(out) < 330 and "もう一度 ok=True" in out
