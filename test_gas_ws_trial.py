# -*- coding: utf-8 -*-
"""
磨き上げの試験 段 T0 の試験（通信なし）: 表の形の検査と展開・判定の部品（手で作った状態で通る例・落ちる例）・
ゴミ箱へ送る守り 3 つ・試験用のエンジン（本番と別）・試験場でないファイルへの seed が断られる・公開の検査。
"""

import copy
import json
import re
import socket
import subprocess
from pathlib import Path

import pytest

import gas_workspace as gw
import gas_ws_judge as J
import gas_ws_tables as T
import gas_ws_trial as TR

HERE = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("本物の通信に出ようとしました（試験は通信なし）")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


# ================================================================ 表の形
def test_six_tables_exist_and_pass_validation():
    names = T.table_names()
    assert names == ["meibo_base", "meibo_dirty", "meibo_quirk", "uriage_base", "uriage_dirty", "uriage_quirk"]
    for n in names:
        t = T.load_table(n)
        assert T.validate_table(t) == [], n
        assert t["notes"] and t["kind"] in ("base", "dirty", "quirk")


def test_expand_sizes_formulas_and_totals():
    sizes = {"meibo_base": 21, "meibo_dirty": 21, "meibo_quirk": 23, "uriage_base": 22, "uriage_dirty": 22, "uriage_quirk": 23}
    for n, rows in sizes.items():
        assert len(T.expand_sheet(T.load_table(n)["sheets"][0])) == rows, n
    g = T.expand_sheet(T.load_table("meibo_base")["sheets"][0])
    assert g[3][0] == {"text": "0014"} and g[3][1] == "会員14" and g[3][3] == {"text": "090-0000-0014"}      # {n} {n:0000}
    assert g[-1][0] == "合計" and g[-1][5] == "=SUM(F2:F20)"                                                      # 合計行
    u = T.expand_sheet(T.load_table("uriage_base")["sheets"][0])
    assert u[3][6] == "=E4*F4" and u[-1][4] == "=SUM(E2:E21)" and u[-1][6] == "=SUM(G2:G21)"                      # {r}
    q = T.expand_sheet(T.load_table("uriage_quirk")["sheets"][0])
    assert q[0][4] == "金額内訳" and q[1][0] == "日付" and q[-1][4] == "=SUM(E3:E22)"                              # 2 段の見出し
    d = T.expand_sheet(T.load_table("meibo_dirty")["sheets"][0])
    assert d[17][1] == " 山田 太郎 " and d[18][0] == {"text": "0019"} and d[19][0] == {"text": "0019"}           # 下の方の汚れ
    ud = T.expand_sheet(T.load_table("uriage_dirty")["sheets"][0])
    assert ud[9] == [None] * 7 and ud[2][4] == {"text": "12"}                                                    # 空行・文字の数字


def test_seed_payload_encodes_cells_for_the_engine():
    p = T.seed_payload(T.load_table("meibo_base"))
    row = p["sheets"][0]["grid"][1]
    assert row[0] == {"s": "0012"} and row[4] == {"d": "2024-04-01"} and row[5] == 12000
    assert p["sheets"][0]["grid"][-1][5] == {"f": "=SUM(F2:F20)"}
    assert p["sheets"][0]["frozen"] == {"rows": 1, "cols": 0} and p["sheets"][0]["formats"][0]["bold"] is True
    assert T.encode_cell(None) is None and T.encode_cell("ふつう") == "ふつう" and T.encode_cell(5) == 5


def test_validation_catches_bad_tables():
    base = T.load_table("meibo_base")

    def with_cell(cell):
        t = copy.deepcopy(base)
        t["sheets"][0]["values"][1][0] = cell
        return T.validate_table(t)
    assert any("化ける" in x for x in with_cell("001"))                    # 文字の数字は {"text"} で
    assert any("化ける" in x for x in with_cell("2024/4/5"))
    assert any("化ける" in x for x in with_cell("12,000"))
    assert any("化ける" in x for x in with_cell("1-2"))
    assert with_cell({"text": "001"}) == []
    assert any("今日で変わる" in x for x in with_cell("=TODAY()"))
    assert any("今日で変わる" in x for x in with_cell("=A1+RAND()"))
    t = copy.deepcopy(base); t["sheets"][0]["tables"] = []
    assert any("tables" in x for x in T.validate_table(t))               # 表の範囲の欄が無い
    t = copy.deepcopy(base); t["sheets"][0]["tables"][0]["total_row"] = 99
    assert any("合計行" in x for x in T.validate_table(t))
    t = copy.deepcopy(base); del t["notes"]
    assert any("notes" in x for x in T.validate_table(t))
    t = copy.deepcopy(base); t["name"] = "名簿"
    assert any("ASCII" in x for x in T.validate_table(t))
    t = copy.deepcopy(base); t["sheets"][0]["values"][1][0] = {"date": "2024/04/01"}
    assert any("YYYY-MM-DD" in x for x in T.validate_table(t))


# ================================================================ 判定の部品
def mk(rows, name="名簿", frozen=0, hidden=(), filtered=(), index=1, merges=(), bg=None, nfs=None, formulas=None, errors=()):
    """手で作った撮った状態。rows は行ごとの文字（1 行目から）。bg は {A1: '#ffff00'}（見えている背景）、formulas は {E3: '=A1'}"""
    cells = {}
    for r, row in enumerate(rows, 1):
        for c, v in enumerate(row, 1):
            if v in ("", None):
                continue
            a1 = f"{J.col_letter(c)}{r}"
            cells[a1] = {"v": str(v), "t": "n" if isinstance(v, (int, float)) else "s", "nf": (nfs or {}).get(a1, ""), "e": {"bg": "#ffffff", "fg": "#000000", "b": False},
                         "u": {"bg": "#ffffff", "fg": "#000000", "b": False}, "bd": False}
            if isinstance(v, (int, float)):
                cells[a1]["n"] = v
    for a1, color in (bg or {}).items():
        cells.setdefault(a1, {"v": "", "t": "", "nf": "", "u": {"bg": "#ffffff", "fg": "#000000", "b": False}, "bd": False})["e"] = {"bg": color, "fg": "#000000", "b": False}
    for a1, f in (formulas or {}).items():
        cells[a1]["f"] = f
    for a1 in errors:
        cells[a1] = {"v": "#REF!", "t": "e", "nf": "", "e": {"bg": "#ffffff", "fg": "#000000", "b": False}, "u": {"bg": "#ffffff", "fg": "#000000", "b": False}, "bd": False}
    return {"name": name, "index": index, "rows": 100, "cols": 10, "frozen": {"rows": frozen, "cols": 0}, "merges": list(merges), "hidden_rows": list(hidden),
            "filtered_rows": list(filtered), "hidden_cols": [], "cells": cells}


def snap(*sheets):
    return {"name": "WS試験_場", "sheets": list(sheets)}


TI = {"名簿": [{"header_rows": [1], "first_col": "A", "last_col": "C", "data": "2-5", "total_row": 6, "key": "A"}]}
BASE = [["番号", "部署", "金額"], [1, "営業", 300], [2, "総務", 100], [3, "営業", 200], [4, "開発", 400], ["合計", "", 1000]]


def test_color_family_rounds_names_and_hex():
    assert J.color_family("#ffff00") == "黄" and J.color_family("#fff2cc") != "赤" and J.color_family("#ff0000") == "赤"
    assert J.color_family("#1f4e79") == "青" and J.color_family("#9e9e9e") == "灰" and J.color_family("#ffffff") == "白" and J.color_family(None) == "白"
    assert J.color_family("黄色") == "黄" and J.color_family("グレー") == "灰" and J.color_family("#FFE699") == "黄"


def test_compare_golden_same_changed_and_row_order():
    before = snap(mk(BASE))
    sorted_ = [BASE[0], BASE[4], BASE[1], BASE[3], BASE[2], BASE[5]]
    model, actual = snap(mk(sorted_)), snap(mk(sorted_))
    assert J.compare_golden(before, actual, model, "並べる")[0]                                    # 模範と同じ
    other = [BASE[0], BASE[1], BASE[2], BASE[3], BASE[4], BASE[5]]
    ok, d = J.compare_golden(before, snap(mk(other)), model, "並べる")
    assert not ok and any("値" in x for x in d)                                                    # 並びが違えば落ちる
    ties = [BASE[0], BASE[4], BASE[1], BASE[3], BASE[2], BASE[5]]
    swapped = [BASE[0], BASE[4], BASE[3], BASE[1], BASE[2], BASE[5]]
    assert not J.compare_golden(before, snap(mk(swapped)), snap(mk(ties)), "並べる")[0]
    assert J.compare_golden(before, snap(mk(swapped)), snap(mk(ties)), "並べる", mode="並びを問わない")[0]   # 行の集まりとして同じ
    wrong = [BASE[0], BASE[4], BASE[1], BASE[3], [2, "総務", 999], BASE[5]]
    assert not J.compare_golden(before, snap(mk(wrong)), snap(mk(ties)), "並べる", mode="並びを問わない")[0]


def test_compare_golden_extent_rule_and_new_sheet_mode():
    before = snap(mk(BASE))
    model = snap(mk(BASE + [["", "", ""]]))
    longer = snap(mk(BASE + [["x", "y", 1]]))
    assert not J.compare_golden(before, longer, snap(mk(BASE)), "値を直す・計算")[0]               # 行を足す・消す頼みでなければ行数の違いは外れ
    ok, _ = J.compare_golden(before, longer, longer, "行や列を足す・消す")
    assert ok
    rows = [["部署", "金額"], ["営業", 500], ["総務", 100]]
    model2 = snap(mk(BASE), mk(rows, name="集計", index=2))
    actual_ok = snap(mk(BASE), mk([["金額", "部署"], [100, "総務"], [500, "営業"]], name="まとめ", index=2))       # 場所・列の順・名前を問わない
    actual_ng = snap(mk(BASE), mk([["金額", "部署"], [100, "総務"], [999, "営業"]], name="まとめ", index=2))
    assert J.compare_golden(before, actual_ok, model2, "値を直す・計算", mode="新しいシートに含む")[0]
    assert not J.compare_golden(before, actual_ng, model2, "値を直す・計算", mode="新しいシートに含む")[0]
    assert not J.compare_golden(before, before, model2, "値を直す・計算", mode="新しいシートに含む")[0]


def test_compare_golden_visible_rows_format_and_structure_faces():
    before = snap(mk(BASE))
    hid = snap(mk(BASE, filtered=[3, 5]))
    assert J.compare_golden(before, hid, snap(mk(BASE, hidden=[3, 5])), "絞る")[0]                  # 隠しでもフィルタでも、見えていなければ同じ
    assert not J.compare_golden(before, snap(mk(BASE, filtered=[3])), snap(mk(BASE, hidden=[3, 5])), "絞る")[0]
    y = snap(mk(BASE, bg={"B2": "#ffff00"}))
    y2 = snap(mk(BASE, bg={"B2": "#ffe699"}))                                                      # 色は名前の仲間に丸める
    r = snap(mk(BASE, bg={"B2": "#ff0000"}))
    assert J.compare_golden(before, y2, y, "見た目")[0] and not J.compare_golden(before, r, y, "見た目")[0]
    f1 = snap(mk(BASE, frozen=1))
    assert not J.compare_golden(before, before, f1, "構成")[0] and J.compare_golden(before, f1, f1, "構成")[0]
    two = lambda order: snap(mk(BASE, index=order[0]), mk(BASE, name="B", index=order[1]))
    assert not J.compare_golden(two((1, 2)), two((1, 2)), two((2, 1)), "構成")[0]                    # シートの並び
    head = snap(mk([["番号", "部署", "金額"]] + BASE[1:]))
    assert J.compare_golden(before, head, head, "行や列を足す・消す", tinfo=TI)[0]


def test_conditions_pass_and_fail():
    after = snap(mk([BASE[0], BASE[4], BASE[1], BASE[3], BASE[2], BASE[5]], formulas={"C6": "=SUM(C2:C5)"}, bg={"A2": "#ffff00", "B2": "#ffff00"}))
    before = snap(mk(BASE))
    ok = lambda c: J.check_condition(c, before, after, TI)[0]
    assert ok({"値": {"C6": 1000, "B2": "開発"}}) and not ok({"値": {"C6": 999}}) and not ok({"値": {"B2": "営業"}})       # 値・表示
    assert ok({"式である": ["C6"]}) and not ok({"式である": ["C2"]})                                                    # 式である
    assert ok({"並び": {"列": "金額", "向き": "降順"}}) and not ok({"並び": {"列": "金額", "向き": "昇順"}}) and not ok({"並び": {"列": "なし", "向き": "降順"}})
    assert ok({"見えている書式": {"範囲": "A2:B2", "背景": "黄"}}) and not ok({"見えている書式": {"範囲": "A2:C2", "背景": "黄"}}) and not ok({"見えている書式": {"範囲": "A2:B2", "背景": "赤"}})
    filt = snap(mk(BASE, filtered=[3, 5]))
    assert J.check_condition({"見えている行": {"列": "部署", "だけ": "営業"}}, before, filt, TI)[0]
    assert not J.check_condition({"見えている行": {"列": "部署", "だけ": "総務"}}, before, filt, TI)[0]
    assert not J.check_condition({"見えている行": {"列": "部署", "だけ": "営業"}}, before, before, TI)[0]               # 絞っていない
    assert J.check_condition({"変わっていない": "全部"}, before, snap(mk(BASE)))[0]
    assert not J.check_condition({"変わっていない": "全部"}, before, snap(mk(BASE, frozen=1)))[0]
    assert ok({"どれか": [{"値": {"C6": 1}}, {"値": {"C6": 1000}}]}) and not ok({"どれか": [{"値": {"C6": 1}}, {"値": {"C6": 2}}]})
    # 条件付き書式で付いた色（見えている書式 e.bg）は撮れた物として読むが、約束の指紋（素の書式 u）には入らない
    fp = lambda s: J.promise_fingerprints(s)[0]["名簿"]
    plain = snap(mk(BASE))
    cf = snap(mk(BASE, bg={"B2": "#ffff00"}))
    assert fp(plain) == fp(cf)
    s3 = mk(BASE); s3["cells"]["B2"]["u"] = {"bg": "#ffff00", "fg": "#000000", "b": False}
    assert fp(plain) != fp(snap(s3))


def test_check_expect_model_and_conditions():
    before = snap(mk(BASE))
    ok, why = J.check_expect({"模範と同じ": {"面": "既定", "比べ方": "そのまま"}}, before, before, before, "値を直す・計算", TI)
    assert ok and why == []
    ok, why = J.check_expect({"条件": [{"値": {"C6": 5}}, {"変わっていない": "全部"}]}, before, before, None, "値を直す・計算", TI)
    assert not ok and len(why) == 1


def test_always_rules_1_4_5_pass_and_fail():
    two = lambda a, b: snap(mk(a, name="名簿", index=1), mk(BASE, name="売上", index=2) if b is None else mk(b, name="売上", index=2))
    before = two(BASE, None)
    assert J.check_rules(before, two(BASE, None), touched=["名簿"]) == []
    changed_other = two(BASE, [BASE[0], [9, "x", 9]])
    assert any(x.startswith("1:") for x in J.check_rules(before, changed_other, touched=["名簿"]))        # 関係ないシートが動いた
    assert J.check_rules(before, changed_other, touched=["名簿", "売上"]) == []
    fb = snap(mk(BASE, formulas={"C2": "=B1"}))
    fv = snap(mk([BASE[0], [1, "営業", 300]] + BASE[2:]))                                                     # 式だった列が値になった
    assert any(x.startswith("4:") for x in J.check_rules(fb, fv, tinfo=TI))
    keep = snap(mk(BASE, formulas={"C2": "=B1", "C3": "=B1"}))
    assert J.check_rules(fb, keep, tinfo=TI) == []
    assert J.check_rules(fb, fv, may_change=("式",), tinfo=TI) == []
    eb, ea = snap(mk(BASE)), snap(mk(BASE, errors=["D2"]))
    assert any(x.startswith("5:") for x in J.check_rules(eb, ea)) and J.check_rules(ea, ea) == [] and J.check_rules(eb, ea, may_change=("エラー",)) == []
    ordered = lambda i: snap(mk(BASE, index=i[0]), mk(BASE, name="売上", index=i[1]))
    assert any("並び" in x for x in J.check_rules(ordered((1, 2)), ordered((2, 1)), touched=["名簿", "売上"]))


def test_diff_list_reads_changes_as_text():
    a, b = snap(mk(BASE)), snap(mk([BASE[0], [1, "営業", 350]] + BASE[2:]))
    d = J.diff_list(a, b)
    assert d == ["名簿!C2 '300' → '350'"]
    assert J.diff_list(a, a) == [] and "シートが消えた" in J.diff_list(a, snap(mk(BASE, name="別")))[-1]


# ================================================================ ゴミ箱へ送る守り
class FakeDrive:
    def __init__(self, files):
        self.files, self.trashed = files, []

    def get(self, fid, fields=None):
        return self.files.get(fid)

    def trash(self, fid):
        self.trashed.append(fid)


FOLDER = "FOLDER"


def meta(fid, name, parents=(FOLDER,)):
    return {"id": fid, "name": name, "parents": list(parents)}


def test_trash_guard_needs_all_three_conditions():
    rec = {"a", "b", "c", "d"}
    assert TR.trash_guard(meta("a", "WS試験_作った物"), rec, FOLDER) == (True, [])
    ok, why = TR.trash_guard(meta("z", "WS試験_作った物"), rec, FOLDER)               # 記録した ID でない
    assert not ok and any("記録" in w for w in why)
    ok, why = TR.trash_guard(meta("b", "請求書_10月"), rec, FOLDER)                    # 名前が WS試験_ でない
    assert not ok and any("WS試験_" in w for w in why)
    ok, why = TR.trash_guard(meta("c", "WS試験_作った物", parents=("OTHER",)), rec, FOLDER)   # フォルダの外
    assert not ok and any("フォルダ" in w for w in why)
    ok, why = TR.trash_guard(meta("d", "WS試験_場"), rec, FOLDER, protected_ids={"d"})       # 試験場の 5 つ・控えのブックは送らない
    assert not ok and any("送らない" in w for w in why)
    assert TR.trash_guard(None, rec, FOLDER) == (False, ["ファイルが見つからない"])


def test_trash_recorded_sends_only_eligible_and_lists_the_rest():
    files = {"ok1": meta("ok1", "WS試験_新1"), "bad_name": meta("bad_name", "いらない物"), "outside": meta("outside", "WS試験_新2", ("X",)),
             "prot": meta("prot", "WS試験_場"), "gone": None}
    d = FakeDrive(files)
    sent, kept = TR.trash_recorded(d, ["ok1", "bad_name", "outside", "prot", "gone", "notrec"], FOLDER, protected_ids={"prot"})
    # 記録した ID だけを見る（記録に無い notrec は触らない）
    assert d.trashed == ["ok1"] and sent == ["WS試験_新1"]
    assert {k[0] for k in kept} >= {"いらない物", "WS試験_新2", "WS試験_場"}
    # 3 つのどれかが欠ければ送らずに一覧に出す。記録に無い ID は呼び出しの対象にも入らない
    d2 = FakeDrive({"x": meta("x", "WS試験_x")})
    sent2, kept2 = TR.trash_recorded(d2, [], FOLDER)
    assert d2.trashed == [] and sent2 == [] and kept2 == []


# ================================================================ 試験用のエンジン（本番と別）
def test_trial_engine_is_a_separate_project_with_trial_gs_after_shelves(tmp_path):
    eng = TR.TrialEngine(client=object(), state_path=tmp_path / "t.json", prod_state_path=tmp_path / "prod.json")
    assert eng.engine_title == "shu-workspace-engine-test" and eng.engine_title != gw.ENGINE_TITLE
    files = eng._engine_files()
    assert [f["name"] for f in files] == ["appsscript", "Engine"]
    body = files[1]["source"]
    assert body.index("SHELF['table.new']") < body.index("var TRIAL_PREFIX") and "EXTRA_ACTIONS['seed']" in body
    assert eng.engine_version() in body and "+t" in eng.engine_version()
    # 棚の指紋（共通部と棚）は本番の作りと同じ。Trial.gs を直しても棚の指紋は変わらない
    prod = gw.WorkspaceManager(client=object(), state_path=tmp_path / "p.json")
    assert eng.shelf_version() == prod.engine_version()
    split = eng._engine_files(split=True)
    assert [f["name"] for f in split][-1] == "Trial"
    # 本番の道具が作るエンジンには Trial.gs が入らない
    assert "TRIAL_PREFIX" not in prod._engine_files()[1]["source"] and "Trial" not in [f["name"] for f in prod._engine_files(split=True)]


def test_trial_commands_refuse_the_production_engine(tmp_path):
    prod = tmp_path / "prod.json"
    prod.write_text(json.dumps({"engine_sid": "P" * 40}), encoding="utf-8")
    st = tmp_path / "t.json"
    st.write_text(json.dumps({"engine_sid": "P" * 40, "engine_url": "u", "engine_ver": "x"}), encoding="utf-8")
    eng = TR.TrialEngine(client=object(), state_path=st, prod_state_path=prod)
    with pytest.raises(TR.TrialError, match="本番のエンジンと同じ"):
        eng.trial_post("snap", id="x")
    with pytest.raises(TR.TrialError, match="本番のエンジンと同じ"):
        eng.seed("x", T.load_table("meibo_base"))
    ok = tmp_path / "t2.json"
    ok.write_text(json.dumps({"engine_sid": "T" * 40}), encoding="utf-8")
    TR.TrialEngine(client=object(), state_path=ok, prod_state_path=prod).assert_not_prod()


def test_common_engine_has_no_trial_content_only_an_empty_hook():
    common = (HERE / "workspace_engine.gs").read_text(encoding="utf-8")
    assert "var EXTRA_ACTIONS = {};" in common
    for word in ("seed", "TRIAL", "WS試験", "trial_config", "poke", "fault"):
        assert not re.search(r"" + word + r"", common), word
    for p in (HERE / "ws_shelves").glob("*.gs"):
        assert "EXTRA_ACTIONS" not in p.read_text(encoding="utf-8")


# ================================================================ Trial.gs（node でそのまま動かす）
def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


NODE_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = {};
const names = input.names;
const ctxv = vm.createContext({ console, store,
  PropertiesService: { getScriptProperties: function () { return { getProperty: function (k) { return store[k] === undefined ? null : store[k]; }, setProperty: function (k, v) { store[k] = v; } }; } },
  SpreadsheetApp: { openById: function (id) { if (!(id in names)) throw new Error('開けません'); return { getName: function () { return names[id]; }, getId: function () { return id; }, setSpreadsheetLocale: function () {}, setSpreadsheetTimeZone: function () {} }; } },
  DocumentApp: new Proxy({ openById: function (id) { return { getName: function () { return names[id]; } }; } }, { get: function (t, k) { return k in t ? t[k] : new Proxy({}, { get: function () { return 1; } }); } }),
  Utilities: { formatDate: function () { return ''; } }, __input: input });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext(`
  var __out = {};
  function tryRun(f) { try { return { ok: true, res: f() }; } catch (e) { return { ok: false, err: String(e.message || e) }; } }
  __out.cfg = EXTRA_ACTIONS['trial_config']({ ids: ['SB1'], docs: [] });
  __out.cfgBad = EXTRA_ACTIONS['trial_config']({ ids: ['NOTPREFIX'], docs: [] });
  __out.unregistered = tryRun(function () { return EXTRA_ACTIONS['seed']({ id: 'OUTSIDE', sheets: [{ name: 'a', grid: [[1]] }] }); });
  __out.snapUnregistered = tryRun(function () { return EXTRA_ACTIONS['snap']({ id: 'OUTSIDE' }); });
  __out.trialUnregistered = tryRun(function () { return EXTRA_ACTIONS['trial']({ id: 'OUTSIDE', ops: [] }); });
  __out.wrongName = tryRun(function () { store['TRIAL_CFG'] = JSON.stringify({ ids: ['NOTPREFIX'], docs: [] }); return EXTRA_ACTIONS['seed']({ id: 'NOTPREFIX', sheets: [{ name: 'a', grid: [[1]] }] }); });
  __out.registeredEmpty = tryRun(function () { store['TRIAL_CFG'] = JSON.stringify({ ids: ['SB1'], docs: [] }); return EXTRA_ACTIONS['seed']({ id: 'SB1', sheets: [] }); });
  __out.prefix = BK_BOOK_NAME;
  __out.pure = {
    hex: [trialHex_({ red: 1, green: 1, blue: 0 }, '#ffffff'), trialHex_(null, '#ffffff'), trialHex_({ red: 0.12156862745, green: 0.30588235294, blue: 0.4745098039 }, '#000000')],
    cells: [trialCell_(null), trialCell_(12), trialCell_('x'), trialCell_({ f: '=A1' }), trialCell_({ s: '0012' }), trialCell_({ d: '2024-04-01' }).nf],
    checks: [trialCheckCell_(12, 12, ''), trialCheckCell_(12, '12', ''), trialCheckCell_({ s: '0012' }, '0012', ''), trialCheckCell_({ s: '0012' }, 12, ''), trialCheckCell_('abc', 'abc', ''),
      trialCheckCell_({ f: '=A1' }, 3, '=A1'), trialCheckCell_({ f: '=A1' }, 3, ''), trialCheckCell_(null, '', ''), trialCheckCell_(null, 'x', ''),
      trialCheckCell_({ d: '2024-04-01' }, new Date(2024, 3, 1), ''), trialCheckCell_({ d: '2024-04-01' }, '2024/4/1', ''), trialCheckCell_('2024/4/5', 45387, '')],
    snap: trialSnapSheet_(__input.apiSheet)
  };
  __out = JSON.stringify(__out);
`, ctxv);
console.log(ctxv.__out);
"""

API_SHEET = {
    "properties": {"sheetId": 7, "title": "名簿", "index": 0, "gridProperties": {"rowCount": 100, "columnCount": 6, "frozenRowCount": 1, "frozenColumnCount": 0}},
    "merges": [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 3}],
    "conditionalFormats": [{"ranges": []}],
    "data": [{"rowMetadata": [{}, {"hiddenByUser": True}, {"hiddenByFilter": True}, {}], "columnMetadata": [{"pixelSize": 100}, {"pixelSize": 80, "hiddenByUser": True}],
              "rowData": [
                  {"values": [{"formattedValue": "見出し", "userEnteredValue": {"stringValue": "見出し"}, "effectiveValue": {"stringValue": "見出し"},
                               "userEnteredFormat": {"backgroundColor": {"red": 0.12156862745, "green": 0.30588235294, "blue": 0.4745098039}, "textFormat": {"bold": True}},
                               "effectiveFormat": {"backgroundColor": {"red": 0.12156862745, "green": 0.30588235294, "blue": 0.4745098039}, "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                                                   "borders": {"top": {"style": "SOLID"}}}}]},
                  {"values": [{"formattedValue": "45,800", "userEnteredValue": {"formulaValue": "=SUM(A1:A3)"}, "effectiveValue": {"numberValue": 45800},
                               "effectiveFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 0}, "numberFormat": {"pattern": "#,##0"}}}]},      # 条件付き書式の色（素の書式は無い）
                  {"values": [{}]}]}],
}


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_trial_gs_refuses_non_sandbox_files_and_pure_parts_work():
    texts = [t for _, t in gw._engine_texts()] + [(HERE / "ws_trial" / "Trial.gs").read_text(encoding="utf-8")]
    payload = {"files": texts, "names": {"SB1": "WS試験_場", "NOTPREFIX": "請求書_10月", "OUTSIDE": "WS試験_場"}, "apiSheet": API_SHEET}
    r = subprocess.run(["node", "-e", NODE_HARNESS], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    assert out["cfg"]["ok"] is True and out["cfgBad"]["ok"] is False and "WS試験_" in out["cfgBad"]["error"]       # 名前が WS試験_ でないファイルは登録できない
    for k in ("unregistered", "snapUnregistered", "trialUnregistered"):
        assert out[k]["ok"] is False and "試験場のファイルではありません（登録されていない ID）" in out[k]["err"], k   # 試験場でないファイルへの seed・snap・trial は断られる
    assert out["wrongName"]["ok"] is False and "名前が WS試験_ で始まらない" in out["wrongName"]["err"]                 # 登録されていても名前が違えば断る
    assert out["registeredEmpty"]["ok"] is False and "sheets が空" in out["registeredEmpty"]["err"]                    # 試験場なら先へ進む
    assert out["prefix"] == "WS試験_控え"                                                                              # 試験用の控えのブックの名前（本番の控えと別）
    p = out["pure"]
    assert p["hex"] == ["#ffff00", "#ffffff", "#1f4e79"]
    assert p["cells"][:5] == [{"v": "", "nf": ""}, {"v": 12, "nf": ""}, {"v": "x", "nf": ""}, {"v": "=A1", "nf": ""}, {"v": "0012", "nf": "@"}] and p["cells"][5] == "yyyy-mm-dd"
    c = p["checks"]
    assert c[0] == "" and "数のはず" in c[1] and c[2] == "" and "文字のままのはず" in c[3] and c[4] == ""
    assert c[5] == "" and "式でない" in c[6] and c[7] == "" and "空のはず" in c[8] and c[9] == "" and "日付のはず" in c[10] and "文字のはず" in c[11]   # 化けたセルを見つける
    s = p["snap"]
    assert s["name"] == "名簿" and s["frozen"] == {"rows": 1, "cols": 0} and s["merges"] == ["A1:C1"] and s["hidden_rows"] == [2] and s["filtered_rows"] == [3] and s["hidden_cols"] == [2]
    assert s["cells"]["A1"]["e"] == {"bg": "#1f4e79", "fg": "#ffffff", "b": True} and s["cells"]["A1"]["bd"] is True
    cf = s["cells"]["A2"]
    assert cf["e"]["bg"] == "#ffff00" and cf["u"]["bg"] == "#ffffff" and cf["f"] == "=SUM(A1:A3)" and cf["n"] == 45800 and cf["nf"] == "#,##0" and cf["t"] == "n"   # 重ねた後の色は e・素の書式は u


# ================================================================ init（偽の Google）
class _Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._d, self.text = status, data, text

    def json(self):
        return self._d


class FakeGoogle:
    """GasClient の代わり。Drive・GAS プロジェクトの作成・エンジンの Web アプリを偽物で返す（呼び出しを記録する）"""

    def __init__(self, authorized=False):
        self.authorized = authorized
        self.files = {}
        self.calls = []
        self.posts = []
        self.put = []
        self.created = []
        self.n = 0

    def _headers(self):
        return {"Authorization": "Bearer fake"}

    def _request_with_retry(self, method, url, headers=None, params=None, json=None, **kw):
        self.calls.append((method, url, params))
        if url.endswith("/drive/v3/files") and method == "GET":
            q = params["q"]
            if "google-apps.script" in q:
                return _Resp(200, {"files": []})
            m = re.search(r"name='([^']*)'", q)
            hits = [f for f in self.files.values() if f["name"] == m.group(1) and not f.get("trashed")]
            return _Resp(200, {"files": hits})
        if url.endswith("/drive/v3/files") and method == "POST":
            self.n += 1
            f = {"id": f"F{self.n:03d}" + "x" * 20, "name": json["name"], "mimeType": json["mimeType"], "parents": json.get("parents", [])}
            self.files[f["id"]] = f
            return _Resp(200, f)
        fid = url.rsplit("/", 1)[-1]
        return _Resp(200, self.files[fid]) if fid in self.files else _Resp(404, {})

    def create_project(self, title):
        self.created.append(title)
        return {"scriptId": "T" * 40}

    def _put_content(self, sid, files):
        self.put.append((sid, files))

    def deploy(self, sid, description=""):
        return {"webAppUrl": "x"}

    def resolve_webapp_url(self, sid, refresh=False, dev=False):
        return "https://script.google.com/macros/s/AKfycbTEST/exec"

    def call_webapp(self, url, params=None, body=None, method="GET", key=None, timeout=15, use_auth=False, dev=False, no_rerun=False):
        self.posts.append(body)
        if not self.authorized:
            return {"status_code": 200, "text": "Authorization needed"}
        a = body["action"]
        base = {"version": self._ver}
        if a == "ping":
            return {"status_code": 200, "data": dict(base, ok=True)}
        if a == "trial_config":
            self.config = body
            return {"status_code": 200, "data": dict(base, ok=True, ids=len(body["ids"]), docs=len(body["docs"]))}
        if a == "trial_info":
            return {"status_code": 200, "data": dict(base, ok=True, ledger_items=0)}
        return {"status_code": 200, "data": dict(base, ok=False, error="知らない")}


def test_init_creates_folder_and_files_then_stops_for_authorization(tmp_path):
    g = FakeGoogle(authorized=False)
    st = tmp_path / ".ws_trial.json"
    prod = tmp_path / ".ws_state.json"
    prod.write_text(json.dumps({"engine_sid": "P" * 40, "target": {"id": "keep"}}), encoding="utf-8")
    g._ver = "x"
    out = []
    rc = TR.init(client=g, out=out.append, state_path=st)
    assert rc == 2                                                      # 許可が要る所で止まる
    text = "\n".join(out)
    assert "https://script.google.com/macros/s/AKfycbTEST/dev" in text and "権限を確認" in text and "init" in text
    s = TR.load_state(st)
    assert s["folder_id"] and set(s["files"]) == set(TR.SANDBOX_SHEETS + TR.SANDBOX_DOCS + [TR.BACKUP_BOOK])
    assert all(f["parents"] == [s["folder_id"]] for f in g.files.values() if f["mimeType"] != TR.MIME_FOLDER)      # 全部フォルダ WS試験 の中
    assert all(f["name"].startswith("WS試験") for f in g.files.values())
    assert g.created == ["shu-workspace-engine-test"]                  # 試験用のエンジンは別のプロジェクト
    assert s["engine_sid"] == "T" * 40
    assert json.loads(prod.read_text(encoding="utf-8")) == {"engine_sid": "P" * 40, "target": {"id": "keep"}}      # 本番の状態に触らない
    assert all(p["action"] == "ping" for p in g.posts)                 # 許可の前に撃ったのは ping だけ


def test_init_after_authorization_registers_the_sandbox_and_is_repeatable(tmp_path):
    g = FakeGoogle(authorized=False)
    st = tmp_path / ".ws_trial.json"
    g._ver = "x"
    TR.init(client=g, out=lambda s: None, state_path=st)
    n_files = len(g.files)
    g.authorized = True
    eng = TR.TrialEngine(client=g, state_path=st)
    g._ver = eng.engine_version()
    out = []
    assert TR.init(client=g, out=out.append, state_path=st) == 0
    assert len(g.files) == n_files and g.created == ["shu-workspace-engine-test"]      # 作り直さない
    s = TR.load_state(st)
    assert g.config["ids"] == [s["files"][n] for n in TR.SANDBOX_SHEETS] and g.config["docs"] == [s["files"]["WS試験_文書"]]
    assert g.config["bk_book"] == s["files"][TR.BACKUP_BOOK]
    assert "本番のエンジンとは別のプロジェクト" in "\n".join(out) and s["engine_checked"]["ids"] == 4


# ================================================================ 公開の検査・語の数
def test_publish_check_keeps_trial_things_out_of_public_files():
    pc = (HERE / "publish_check.py").read_text(encoding="utf-8")
    ns = {"__file__": str(HERE / "publish_check.py")}
    exec(compile(pc.split("def main():")[0], "publish_check", "exec"), ns)
    public = ns["PUBLIC_FILES"]
    assert not any("ws_trial" in f or "Trial" in f or f in ("gas_ws_trial.py", "gas_ws_judge.py", "gas_ws_tables.py", "test_gas_ws_trial.py") for f in public)
    pats = [re.compile(p) for p, _ in ns["FORBID_PATTERNS"]]
    for sample in ("ws_trial/Trial.gs", "Trial.gs", ".ws_trial.json", "WS試験_場"):
        assert any(p.search(sample) for p in pats), sample
    for f in public:                       # 公開物に試験用の物が出てこない
        p = HERE / f
        if p.is_file() and f not in (".gitignore", "publish_check.py"):
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in pats:
                assert not pat.search(text), (f, pat.pattern)
    ig = (HERE / ".gitignore").read_text(encoding="utf-8")
    assert ".ws_trial.json" in ig and "ws_trial/runs/" in ig


def test_words_over_limit_counts_cards_with_more_than_eight_words():
    assert TR.words_over_limit() == [] or all(c > 8 for _, c in TR.words_over_limit())
    cat = gw.CATALOG
    fake = copy.deepcopy(cat)
    fake.shelves[0]["words"] = [f"語{i:02d}" for i in range(9)]
    assert TR.words_over_limit(fake) == [(fake.shelves[0]["name"], 9)]


# ================================================================ check（偽の Google で流れだけ確かめる。実機は許可の後）
class FakeGoogle2(FakeGoogle):
    def _request_with_retry(self, method, url, headers=None, params=None, json=None, **kw):
        fid = url.rsplit("/", 1)[-1]
        if method == "PATCH" and fid in self.files:
            f = self.files[fid]
            if params and params.get("addParents"):
                f["parents"] = [params["addParents"]]
            if json and json.get("trashed"):
                f["trashed"] = True
            return _Resp(200, f)
        if method == "GET" and fid in self.files and "modifiedTime" in str((params or {}).get("fields", "")):
            return _Resp(200, dict(self.files[fid], modifiedTime="2026-11-12T00:00:00Z"))
        return super()._request_with_retry(method, url, headers=headers, params=params, json=json, **kw)

    def call_webapp(self, url, params=None, body=None, method="GET", key=None, timeout=15, use_auth=False, dev=False, no_rerun=False):
        if "PRODENGINE" in url:                                                  # 本番のエンジン: 読むだけ（list）
            self.prod_posts = getattr(self, "prod_posts", []) + [body["action"]]
            return {"status_code": 200, "data": {"ok": True, "ledger": [{"n": 1}, {"n": 2}]}}
        a = body["action"]
        if a == "seed":
            registered = body["id"] in getattr(self, "config", {}).get("ids", [])
            if not registered:
                return {"status_code": 200, "data": {"ok": False, "error": "試験場のファイルではありません（登録されていない ID）: " + body["id"], "version": self._ver}}
            return {"status_code": 200, "data": {"ok": True, "sheets": 1, "version": self._ver}}
        if a == "snap":
            cell = {"v": "12,000", "t": "n", "nf": "#,##0", "e": {"bg": "#ffff00", "fg": "#000000", "b": False}, "u": {"bg": "#ffffff", "fg": "#000000", "b": False}, "bd": True}
            return {"status_code": 200, "data": {"ok": True, "snap": {"name": "x", "sheets": [{"name": "名簿", "cells": {"F2": cell}}]}, "version": self._ver}}
        if a == "trial":
            return {"status_code": 200, "data": {"ok": True, "a": {"sheets": []}, "b": {"sheets": []}, "do": {"ok": True, "backup": 1}, "backups_added": 1, "undo": {"ok": True}, "version": self._ver}}
        if a == "do":
            self.n += 1
            f = {"id": f"E{self.n:03d}" + "x" * 20, "name": body["target"]["new"], "mimeType": TR.MIME_SHEET, "parents": []}
            self.files[f["id"]] = f
            return {"status_code": 200, "data": {"ok": True, "created": {"id": f["id"], "name": f["name"]}, "version": self._ver}}
        return super().call_webapp(url, params, body, method, key, timeout, use_auth, dev, no_rerun)


def test_check_flow_with_fake_google_never_touches_production_and_trashes_only_guarded_files(tmp_path):
    g = FakeGoogle2(authorized=True)
    st = tmp_path / ".ws_trial.json"
    prod = tmp_path / ".ws_state.json"
    prod.write_text(json.dumps({"engine_sid": "P" * 40, "engine_url": "https://script.google.com/macros/s/PRODENGINE/dev"}), encoding="utf-8")
    g.files["PRODBK"] = {"id": "PRODBK", "name": "GASマネージャー_控え", "mimeType": TR.MIME_SHEET, "parents": []}
    eng = TR.TrialEngine(client=g, state_path=st, prod_state_path=prod)
    g._ver = eng.engine_version()
    assert TR.init(client=g, out=lambda s: None, state_path=st) == 0
    out = []
    rc = TR.check(client=g, out=out.append, state_path=st, prod_state_path=prod, memo_path=tmp_path / "memo.md")
    text = "\n".join(out)
    assert rc == 0, text
    for want in ("試験場でないファイルへの seed が断られる", "条件付き書式で付けた色が effectiveFormat で撮れる", "ゴミ箱へ送る（守り 3 つを満たす物だけ）",
                 "本番のエンジンの台帳が試験の前後で同じ", "本番の控えのブックが試験の前後で同じ", "trial（流し込む→撮る→撃つ→撮る→戻す→撮る）が 1 回の POST で通る"):
        assert "[OK] " + want in text, want
    s = TR.load_state(st)
    protected = set(s["files"].values())
    trashed = {f["name"] for f in g.files.values() if f.get("trashed")}
    assert trashed and all(n.startswith("WS試験_") for n in trashed)
    assert not any(g.files[i].get("trashed") for i in protected)                       # 試験場の 5 つ・控えのブックは送らない
    assert g.files["PRODBK"].get("trashed") is None                                    # 本番の控えのブックには触らない
    assert set(g.prod_posts) == {"list"}                                              # 本番のエンジンへ撃ったのは list（読むだけ）だけ
    memo = (tmp_path / "memo.md").read_text(encoding="utf-8")
    assert "条件付き書式" in memo and "[NG]" not in memo
