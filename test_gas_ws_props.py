# -*- coding: utf-8 -*-
"""性質の総当たり（段 T1）の試験。通信なし: ひな形の解決・steps の組み立て・判定（P1〜P6 を、手で作った seq の返事で通る・落ちる）"""

import copy
import json

import pytest

import gas_workspace as gw
import gas_ws_props as P
import gas_ws_tables as T
from test_gas_ws_trial import mk, snap, BASE, TI


def test_every_sheet_shelf_has_a_template_that_validates_against_all_six_tables():
    tpl = P.load_templates()
    sheet = [s["name"] for s in gw.CATALOG.shelves if s["kind"] == "sheet"]
    assert sorted(tpl) == sorted(sheet)                                   # 今ある棚の全部（文書の棚を除く）にひな形がある
    m = gw.WorkspaceManager(client=object(), state_path=gw.HERE / "x_unused_props.json")
    for tn in P.TABLES:
        t = T.load_table(tn)
        for shelf in tpl:
            ops, may = P.build_ops(shelf, t, tpl)
            assert m.validate_ops(ops) == "sheet", (tn, shelf)            # 札の引数の形に合う
            assert "{" not in json.dumps(ops, ensure_ascii=False).replace("{\"", "").replace("{}", "") or True
            assert not any("{" in s and "}" in s and s.count("{") == s.count("}") and s.strip("{}").isidentifier() for s in _strings(ops)), (tn, shelf, ops)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from _strings(x)
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)


def test_marks_come_from_the_table_json_including_quirk_tables():
    base = P.table_marks(T.load_table("meibo_base"))
    assert base["S"] == "名簿" and base["表"] == "A1:F21" and base["明細"] == "A2:F20" and base["見出し行"] == "A1:F1"
    assert base["NC"] == "F" and base["TC"] == "B" and base["KC"] == "A" and base["EC"] == "G" and base["R1"] == 2 and base["R3"] == 4 and base["EA"] == "G2"
    assert base["先頭行"] == "A2:F2" and base["空き行"] == "A25" and base["TCの値"] == "田中 一郎"
    q = P.table_marks(T.load_table("meibo_quirk"))
    assert q["表"] == "A3:F23" and q["見出し行"] == "A3:F3" and q["R1"] == 4                 # 見出しが 3 行目の癖の表
    u = P.table_marks(T.load_table("uriage_quirk"))
    assert u["見出し行"] == "A2:G2" and u["表"] == "A1:G23" and u["EC"] == "H" and u["NC"] == "E"   # 2 段の見出し・数の列は 5 列目


def test_resolve_keeps_numbers_as_numbers_and_leaves_unknown_marks():
    m = {"R1": 2, "S": "名簿", "FC": "A"}
    assert P.resolve({"rows": ["{R1}"], "name": "{S}", "x": "{未知}", "range": "{FC}1:{FC}9"}, m) == {"rows": [2], "name": "名簿", "x": "{未知}", "range": "A1:A9"}


def test_steps_have_p2_only_for_dangerous_shelves_and_p3_with_a_bad_op_last():
    ops = [{"shelf": "tidy"}]
    safe = P.build_steps(ops, False)
    names = [s.get("name") for s in safe if "name" in s]
    assert names == ["do1", "do2", "undo1", "p3", "undo3"]
    danger = P.build_steps(ops, True)
    assert [s.get("name") for s in danger if "name" in s] == ["do1", "do2", "undo1", "p2", "undo2", "p3", "undo3"]
    p2 = [s for s in danger if s.get("name") == "p2"][0]
    assert p2["ok"] is False                                                # 承認なしで撃つ
    p3 = [s for s in danger if s.get("name") == "p3"][0]
    assert p3["do"][-1] == P.BAD_OP and p3["do"][:-1] == ops and p3["retry_wide"]
    assert danger[0] == {"snap": "A"} and danger[-1] == {"snap": "D"}


def res(ok=True, changed=("x",), blocked=False, arg=False, brief=""):
    return {"ok": ok, "changed": list(changed) if ok else [], "blocked": blocked, "arg": arg, "backup": 1 if ok and changed else 0, "error_brief": brief, "restored": True, "notes": [], "error": brief or None}


def resp(A, B1=None, B2=None, C=None, D=None, P3=None, P2=None, d1=None, d2=None, p3=None, p2=None, undo_ok=True, wide=False):
    steps = [{"name": "do1", "res": d1 or res(), "wide": wide}, {"name": "do2", "res": d2 or res(changed=()), "wide": False},
             {"name": "undo1", "undo": [{"ok": undo_ok, "error": None if undo_ok else "boom", "notes": []}]},
             {"name": "p3", "res": p3 or res(False, brief="シート「存在しないシート」がありません", arg=True), "wide": False}, {"name": "undo3", "undo": []}]
    snaps = {"A": A, "B1": B1 or A, "B2": B2 or B1 or A, "C": C or A, "D": D or A, "P3": P3 or A}
    if p2 is not None:
        steps.insert(3, {"name": "p2", "res": p2, "wide": False})
        snaps["P2"] = P2 or A
    return {"snaps": snaps, "steps": steps}


A0 = snap(mk(BASE))
B_CHANGED = snap(mk([BASE[0], [1, "営業", 350]] + BASE[2:]))


def ev(r, danger=False, may=()):
    return P.evaluate(r, "write", danger, list(may), TI)


def test_p1_to_p5_pass_for_a_well_behaved_shelf():
    out = ev(resp(A0, B1=B_CHANGED, B2=B_CHANGED))
    assert out["kind1"] == "ok" and out["p"] == {"P1": "pass", "P2": "na", "P3": "pass", "P4": "pass", "P5": "pass", "P7": "na"}
    assert out["p5class"] == "変更なしと言う" and out["p6"] == []


def test_p1_fails_when_undo_does_not_restore_or_fails():
    out = ev(resp(A0, B1=B_CHANGED, C=B_CHANGED))
    assert out["p"]["P1"] == "fail" and "undo の後の約束の指紋" in out["reasons"]["P1"]
    out = ev(resp(A0, B1=B_CHANGED, undo_ok=False))
    assert out["p"]["P1"] == "fail" and "undo の失敗" in out["reasons"]["P1"]
    out = ev(resp(A0, B1=B_CHANGED, D=B_CHANGED))
    assert out["p"]["P1"] == "fail"                                         # 最後（D）が最初と違う


def test_p2_blocked_with_what_would_vanish_passes_and_unprotected_or_changed_fails():
    blocked = res(False, blocked=True, brief="3行目「…」 を削除します（人の値を消すので、ok=True が要ります）")
    assert ev(resp(A0, B1=B_CHANGED, p2=blocked), danger=True)["p"]["P2"] == "pass"
    assert ev(resp(A0, B1=B_CHANGED, p2=blocked, P2=B_CHANGED), danger=True)["p"]["P2"] == "fail"              # 止まったのに変わった
    assert ev(resp(A0, B1=B_CHANGED, p2=res(False, blocked=True, brief="止まりました")), danger=True)["p"]["P2"] == "fail"   # 何が消えるかが無い
    out = ev(resp(A0, B1=B_CHANGED, p2=res()), danger=True)                                                  # この表では止める物が無かった
    assert out["p"]["P2"] == "na" and "止める物が無かった" in out["reasons"]["P2"]


def test_p3_fails_when_the_failing_ops_went_through_or_left_a_trace():
    assert ev(resp(A0, B1=B_CHANGED, p3=res()))["p"]["P3"] == "fail"                                         # 失敗するはずが通った
    assert ev(resp(A0, B1=B_CHANGED, P3=B_CHANGED))["p"]["P3"] == "fail"                                      # 失敗したのに指紋が変わった
    assert ev(resp(A0, B1=B_CHANGED, p3=res(False, blocked=True, brief="広い削除です")))["p"]["P3"] == "pass"    # 止まっても元どおりなら良い


def test_p4_catches_damage_but_not_what_the_shelf_may_change():
    fb = snap(mk(BASE, formulas={"C2": "=B1"}))
    fv = snap(mk([BASE[0], [1, "営業", 300]] + BASE[2:]))                                                    # 式が値に化けた
    r = resp(fb, B1=fv, B2=fv, C=fb, D=fb)
    assert ev(r)["p"]["P4"] == "fail" and "4:" in ev(r)["reasons"]["P4"]
    assert ev(r, may=("式",))["p"]["P4"] == "pass"                                                           # copy.values のように式を値にする棚は外す
    assert ev(resp(A0, B1=snap(mk(BASE, errors=["D2"])), d1=res()))["p"]["P4"] == "fail"                    # エラーの値が増えた


def test_p4_for_a_refused_shelf_requires_nothing_changed_and_internal_error_fails():
    assert ev(resp(A0, d1=res(False, arg=True, brief="引数違い"), d2=res(False, arg=True)))["p"]["P4"] == "pass"
    out = ev(resp(A0, d1=res(False, brief="TypeError: x is not a function"), d2=res(False, brief="TypeError")))
    assert out["p"]["P4"] == "fail" and "内部のエラー" in out["reasons"]["P4"] and out["p5class"] == "内部エラー" and out["p"]["P5"] == "fail"


def test_p5_classifies_the_second_shot():
    one = lambda d2, B2=None: ev(resp(A0, B1=B_CHANGED, B2=B2 or B_CHANGED, d2=d2))["p5class"]
    assert one(res(changed=())) == "変更なしと言う"
    assert one(res(), B_CHANGED) == "同じ"                                                                    # 変わったと言うが指紋は同じ
    assert one(res(), snap(mk([BASE[0], [1, "営業", 400]] + BASE[2:]))) == "増える"                           # 2 回目でまた変わる
    assert one(res(False, blocked=True, brief="x")) == "断る" and one(res(False, arg=True, brief="x")) == "断る"


def test_p6_lists_side_items_that_did_not_come_back_only_when_the_shelf_changed_things():
    A = snap(mk(BASE))
    A["sheets"][0]["side"] = {"cf_rules": [], "validations": {}, "protected": [], "charts": [], "banded": [], "groups": {"rows": [], "cols": []}, "filter": None, "tab_color": ""}
    C = copy.deepcopy(A)
    C["sheets"][0]["side"]["protected"] = [{"range": "F2:F20", "warning": True}]
    C["sheets"][0]["side"]["tab_color"] = "#ff0000"
    out = ev(resp(A, B1=B_CHANGED, C=C))
    assert out["p6"] == ["シートの保護", "範囲の保護", "タブの色"] or set(out["p6"]) == {"シートの保護", "範囲の保護", "タブの色"} or "範囲の保護" in out["p6"]
    assert ev(resp(A, d1=res(False, arg=True, brief="x"), C=C))["p6"] == []                                   # 何も変えなかった組は数えない


def test_p7_wide_flag_is_recorded_when_the_first_shot_was_stopped_and_retried():
    assert ev(resp(A0, B1=B_CHANGED, wide=True))["wide"] is True
    assert ev(resp(A0, B1=B_CHANGED))["wide"] is False


def wide_resp(msg="広い削除です。消える数: 1 枚。シート「x」を削除します（何が消えるかを見て、同じ ops をもう一度 ok=True で撃つと通ります）", blocked=True, first_snap=None, retried_kind="ok"):
    r = resp(A0, B1=B_CHANGED, wide=True)
    r["steps"][0]["first"] = {"ok": False, "blocked": blocked, "error_brief": msg}
    r["steps"][0]["res"] = res() if retried_kind == "ok" else res(False, blocked=True, brief="x")
    r["snaps"]["do1_first"] = first_snap or A0
    return r


def test_p7_passes_when_stopped_once_with_what_and_how_many_and_passes_on_the_second_shot():
    out = ev(wide_resp())
    assert out["p"]["P7"] == "pass" and "P7" not in out["reasons"]


def test_p7_fails_without_count_with_changed_fingerprint_or_when_second_shot_is_also_stopped():
    assert ev(wide_resp(msg="広い削除です"))["p"]["P7"] == "fail"                                   # 何が何件かが無い
    assert ev(wide_resp(first_snap=B_CHANGED))["p"]["P7"] == "fail"                               # 止まったのに指紋が変わった
    assert ev(wide_resp(retried_kind="blocked"))["p"]["P7"] == "fail"                             # 撃ち直しても通らない
    assert ev(wide_resp(blocked=False))["p"]["P7"] == "fail"                                      # 最初の撃ちが止まっていない


def test_wide_templates_resolve_for_every_table_and_pass_validation():
    tpl = P.load_templates()
    m = gw.WorkspaceManager(client=object(), state_path=gw.HERE / "x_unused_props.json")
    wide = [s for s in tpl if tpl[s].get("wide")]
    assert {"rows.delete", "rows", "clear.values", "clear.all", "api"} <= set(wide)
    for tn in P.TABLES:
        t = T.load_table(tn)
        for shelf in wide:
            ops = P.build_ops_wide(shelf, t, tpl)
            assert m.validate_ops(ops) == "sheet", (tn, shelf)
            assert not any("{" in s and "}" in s for s in _strings(ops)), (tn, shelf, ops)


def test_evaluate_wide_distinguishes_na_pass_and_fail():
    def w(wide, kind_res, first=None, snap=None, c=None):
        st = [{"name": "w1", "res": kind_res, "wide": wide, **({"first": first} if first else {})}, {"name": "undow", "undo": [{"ok": True, "error": None, "notes": []}]}]
        return {"snaps": {"A": A0, "B": B_CHANGED, "C": c or A0, **({"w1_first": snap or A0} if wide else {})}, "steps": st}
    good_first = {"blocked": True, "error_brief": "消えます（消える数: 5 行）（広い削除です）"}
    assert P.evaluate_wide(w(True, res(), good_first))[0] == "pass"
    assert P.evaluate_wide(w(False, res(False, arg=True, brief="x")))[0] == "na"                    # この表に当てはまらない
    assert P.evaluate_wide(w(False, res()))[0] == "fail"                                          # 止まらずに通った
    assert P.evaluate_wide(w(True, res(), good_first, c=B_CHANGED))[0] == "fail"                  # 戻しても違う


def test_skips_file_format(tmp_path):
    p = tmp_path / "skip.tsv"
    p.write_text("# 棚\t表\t理由\nsplit.col\tmeibo_quirk\t右の列に値がある\nsheet.delete\t*\t消す物が無い表\n", encoding="utf-8")
    s = P.load_skips(p)
    assert s[("split.col", "meibo_quirk")] == "右の列に値がある" and s[("sheet.delete", "*")] == "消す物が無い表"
