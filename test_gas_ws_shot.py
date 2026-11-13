# -*- coding: utf-8 -*-
"""L2b・模範の再生・撮り置き（段 T1）の試験。通信なし（偽の試験用エンジンと偽の AI）"""

import json

import pytest

import gas_workspace as gw
import gas_ws_shot as S
import gas_ws_tables as T
from test_gas_ws_trial import mk, snap, BASE, TI


def test_twenty_cases_exist_each_with_model_that_validates_and_expectation():
    cases = S.load_cases()
    ids = [c["id"] for c in cases]
    assert len(cases) >= 20 and len(set(ids)) == len(ids)
    m = gw.WorkspaceManager(client=object(), state_path=S.HERE / "x_unused_shot.json")
    for c in cases:
        assert c["layer"] == "L2b" and len(c["turns"]) == 1
        if c["model"]:
            want_kind = "doc" if any(isinstance(o, dict) and o.get("shelf", "").startswith("doc.") for o in c["model"]) else "sheet"
            assert m.validate_ops(c["model"]) == want_kind, c["id"]
        t = c["turns"][0]
        assert t["approve"] in ("ある", "まだ") and t["askback"] in ("要る", "要らない", "どちらでも"), c["id"]
        assert ("模範と同じ" in t["expect"]) or ("条件" in t["expect"]) or ("保留" in t["expect"]), c["id"]
        assert c["table"] in T.table_names() and c["kind"]
    # 消す台本は approve=ある（名指し）で、4 本以上
    assert sum(1 for c in cases if c["turns"][0]["approve"] == "ある") >= 4


def test_parse_answer_reads_the_three_shapes_and_rejects_the_rest():
    assert S.parse_answer('{"ops":[{"shelf":"tidy"}],"ok":false}') == {"ops": [{"shelf": "tidy"}], "ok": False}
    assert S.parse_answer('```json\n{"質問":"どの列ですか"}\n```') == {"質問": "どの列ですか"}
    assert S.parse_answer('はい。{"無い":"棚が無い"} です') == {"無い": "棚が無い"}
    assert S.parse_answer("わかりません") is None and S.parse_answer('{"x":1}') is None and S.parse_answer("") is None


def test_prompt_carries_description_look_candidates_and_request():
    p = S.build_prompt("3行目を消して", "シート: 売上（21行×7列）", "棚の候補（1 本）…", description="ws_do の説明です")
    for want in ("ws_do の説明です", "シート: 売上（21行×7列）", "棚の候補（1 本）", "3行目を消して", '"質問"', '"無い"', '"ok"'):
        assert want in p
    assert "shelf" in S.ws_do_description() and "api" in S.ws_do_description()          # 本番の説明そのまま


class FakeEng:
    """seq の返事を、撃たれた ops から作る偽の試験用エンジン。after は ops → 撃った後の状態、res は ops → do の結果"""

    def __init__(self, before, after_fn, res_fn=None, restore=True):
        self.before, self.after_fn, self.res_fn, self.restore = before, after_fn, res_fn, restore
        self.calls = []

    def seed(self, fid, table):
        return {"ok": True}

    def trial_post(self, action, **kw):
        assert action == "seq"
        self.calls.append(kw)
        step = [s for s in kw["steps"] if s.get("name") == "do"][0]
        ops, ok = step["do"], step["ok"]
        res = self.res_fn(ops, ok) if self.res_fn else {"ok": True, "changed": ["x"], "blocked": False, "arg": False, "backup": 1, "error_brief": "", "restored": True, "notes": [], "error": None}
        B = self.after_fn(ops) if res["ok"] else self.before
        return {"ok": True, "snaps": {"A": self.before, "B": B, "C": self.before if self.restore else B}, "steps": [{"name": "do", "res": res, "wide": False}, {"name": "undo", "undo": []}]}


BEFORE = snap(mk(BASE))
SORTED = snap(mk([BASE[0], BASE[4], BASE[1], BASE[3], BASE[2], BASE[5]]))


def case_sort(**over):
    c = {"id": "x-1", "table": "meibo_base", "kind": "並べる", "layer": "L2b", "model": [{"shelf": "sort", "col": "会費", "desc": True}],
         "turns": [{"say": "並べて", "approve": "まだ", "askback": "要らない", "expect": {"条件": [{"並び": {"列": "金額", "向き": "降順"}}]}}], "may_change": [], "max_calls": 4}
    c.update(over)
    return c


def run_turn(case, answer, eng):
    return S.run_ai_turn(eng, "FID", case, answer, SORTED, None, [])


@pytest.fixture(autouse=True)
def _patch_tables(monkeypatch, request):
    """試験用の表の代わりに、手で作った状態を使う（TI は表の範囲）"""
    real = T.load_table
    monkeypatch.setattr(S.T, "load_table", lambda n: {"name": n, "sheets": [{"name": "名簿", "tables": TI["名簿"], "values": [[1]], "hidden": {"rows": [], "cols": []}}], "named": []})
    monkeypatch.setattr(S.T, "seed_payload", lambda t: {"sheets": []})
    monkeypatch.setattr(S.T, "table_info", lambda t: TI)
    if "lint" not in request.node.name:
        monkeypatch.setattr(S, "lint_case", lambda case, guard=None: [])         # 撃つ前の検査は専用の試験で見る
    yield


def test_correct_answer_is_marked_circle():
    eng = FakeEng(BEFORE, lambda ops: SORTED)
    r = run_turn(case_sort(), {"ops": [{"shelf": "sort", "col": "会費", "desc": True}], "ok": False}, eng)
    assert r["mark"] == "◎" and r["got"] == ["sort"] and r["F"] == ""


def test_askback_is_right_only_when_the_script_wants_it():
    eng = FakeEng(BEFORE, lambda ops: SORTED)
    c = case_sort()
    assert run_turn(c, {"質問": "どの列ですか"}, eng)["F"] == "F8"                            # 聞かなくてよいのを聞いた
    c["turns"][0]["askback"] = "要る"
    assert run_turn(c, {"質問": "どの列ですか"}, eng)["mark"] == "△"
    assert run_turn(c, {"ops": [{"shelf": "tidy"}], "ok": False}, eng)["F"] == "F7"          # 聞くべきを撃った
    assert run_turn(case_sort(), {"無い": "x"}, eng)["F"] == "F6"
    assert run_turn(case_sort(), None, eng)["F"] == "F3"                                     # 読めない返事


def test_wrong_shelf_bad_args_and_wrong_state_are_told_apart():
    eng = FakeEng(BEFORE, lambda ops: BEFORE)                                                # 何も変わらない
    r = run_turn(case_sort(), {"ops": [{"shelf": "tidy"}], "ok": False}, eng)
    assert r["mark"] == "×" and r["F"] == "F2"                                              # 期待の棚が入っていない
    r = run_turn(case_sort(), {"ops": [{"shelf": "sort", "col": "会費"}], "ok": False}, eng)
    assert r["F"] == "F4"                                                                    # 棚は合うが状態が違う
    r = run_turn(case_sort(), {"ops": [{"shelf": "sort", "nokey": 1}], "ok": False}, eng)
    assert r["F"] == "F3" and "引数の検査" in r["why"]                                       # 引数の形違い（撃つ前に止まる）
    assert eng.calls == [eng.calls[0], eng.calls[1]] or len(eng.calls) == 2


def test_ok_true_on_a_script_that_needs_no_approval_is_f12_and_stopped_unapproved_delete_is_f8():
    eng = FakeEng(BEFORE, lambda ops: SORTED)
    r = run_turn(case_sort(), {"ops": [{"shelf": "sort", "col": "会費", "desc": True}], "ok": True}, eng)
    assert r["F"] == "F12" and r["mark"] == "×"                                              # approve=まだ の台詞で ok=True
    blocked = lambda ops, ok: {"ok": False, "changed": [], "blocked": True, "arg": False, "backup": 0, "error_brief": "削除します（ok=True が要ります）", "restored": True, "notes": [], "error": "x"}
    c = case_sort()
    c["turns"][0]["approve"] = "ある"
    r = run_turn(c, {"ops": [{"shelf": "rows.delete", "rows": [3]}], "ok": False}, FakeEng(BEFORE, lambda ops: BEFORE, blocked))
    assert r["F"] == "F8" and "名指し" in r["why"]                                           # 名指しなのに承認待ち（数だけ出す）
    r = run_turn(case_sort(), {"ops": [{"shelf": "rows.delete", "rows": [3]}], "ok": True}, FakeEng(BEFORE, lambda ops: BEFORE, blocked))
    assert r["F"] == "F12"                                                                   # 承認が要らない頼みで ok=True（道具が止めても F12）


def test_damage_is_f9_even_if_the_expectation_is_met():
    damaged = snap(mk([BASE[0], BASE[4], BASE[1], BASE[3], BASE[2], BASE[5]], errors=["D2"]))
    eng = FakeEng(BEFORE, lambda ops: damaged)
    r = run_turn(case_sort(), {"ops": [{"shelf": "sort", "col": "会費", "desc": True}], "ok": False}, eng)
    assert r["F"] == "F9" and "エラー" in r["why"]


def test_golden_passes_for_a_good_model_and_fails_with_m_for_a_bad_one():
    c = case_sort()
    eng = FakeEng(BEFORE, lambda ops: SORTED)
    resp, after = S.run_model(eng, "FID", c)
    assert after is SORTED and S.judge_model(c, resp) == (True, [])
    assert eng.calls[0]["steps"][1]["retry_wide"] is True                                    # 模範は広い削除の止めを通す
    bad_eng = FakeEng(BEFORE, lambda ops: BEFORE)
    resp, _ = S.run_model(bad_eng, "FID", c)
    ok, why = S.judge_model(c, resp)
    assert not ok and why
    refused = FakeEng(BEFORE, lambda ops: BEFORE, lambda ops, ok: {"ok": False, "changed": [], "blocked": False, "arg": True, "backup": 0, "error_brief": "引数違い", "restored": True, "notes": [], "error": "x"})
    resp, _ = S.run_model(refused, "FID", c)
    assert "模範が通らない" in S.judge_model(c, resp)[1][0]
    unrestored = FakeEng(BEFORE, lambda ops: SORTED, restore=False)
    resp, _ = S.run_model(unrestored, "FID", c)
    assert "戻した後の指紋" in "；".join(S.judge_model(c, resp)[1])


def test_run_shot_records_each_script_with_ai_meta_and_summarizes(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(S, "look_path", lambda t, d=None: tmp_path / f"{t}.txt")
    (tmp_path / "meibo_base.txt").write_text("シート: 名簿", encoding="utf-8")
    cases = [case_sort(id="x-1"), case_sort(id="x-2")]
    eng = FakeEng(BEFORE, lambda ops: SORTED)
    answers = iter(['{"ops":[{"shelf":"sort","col":"会費","desc":true}],"ok":false}', '{"質問":"どの列？"}'])
    ask = lambda prompt: (next(answers), {"sec": 2.0, "in": 1200, "out": 80, "cost": 0.001})
    out = []
    results, rf = S.run_shot(eng, "FID", cases, model="haiku", ask_fn=ask, out=out.append, run_file=tmp_path / "r.jsonl")
    assert [r["mark"] for r in results] == ["◎", "×"] and results[1]["F"] == "F8"
    rows = [json.loads(x) for x in rf.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["ai"]["in"] == 1200 and rows[0]["l0_has_model"] in (True, False)
    sm = S.summarize(results)
    assert sm["n"] == 2 and sm["ok"] == 1 and sm["rate"] == 50.0 and sm["in_tokens"] == 2400 and sm["out_tokens"] == 160 and sm["sec_each"] == 2.0 and sm["F"] == {"F8": 1}
    # --resume: 終わった台本は飛ばす
    again, _ = S.run_shot(eng, "FID", cases, model="haiku", ask_fn=lambda p: pytest.fail("再び AI を呼んだ"), out=lambda s: None, run_file=rf, resume=True)
    assert again == []


def test_run_shot_marks_m_without_asking_the_ai_when_the_model_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RUNS_DIR", tmp_path)
    eng = FakeEng(BEFORE, lambda ops: BEFORE)                                                # 模範が何も変えない＝期待を満たさない
    results, _ = S.run_shot(eng, "FID", [case_sort()], ask_fn=lambda p: pytest.fail("AI を呼んではいけない"), out=lambda s: None, run_file=tmp_path / "m.jsonl")
    assert results[0]["mark"] == "M" and results[0]["F"] == "M"


def test_post_failure_is_recorded_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(S, "SEQ_WAIT", 0)          # 待ち直しの秒は 0（試験を遅くしない）

    class Boom(FakeEng):
        def trial_post(self, action, **kw):
            raise RuntimeError("Service invoked too many times")
    results, _ = S.run_shot(Boom(BEFORE, lambda o: BEFORE), "FID", [case_sort()], ask_fn=lambda p: ("{}", {}), out=lambda s: None, run_file=tmp_path / "p.jsonl")
    assert results[0]["F"] == "POST" and results[0]["post_fail"] is True


def test_capture_looks_writes_the_real_look_format_without_the_file_id(tmp_path):
    class E:
        def seed(self, fid, t):
            return {"ok": True}

        def _post(self, body):
            assert body["action"] == "look" and body["target"]["id"] == "FILEID123"
            return {"ok": True, "target": {"id": "FILEID123", "name": "WS試験_場", "kind": "sheet", "url": "https://docs.google.com/spreadsheets/d/FILEID123/edit"}, "sheets": [{"name": "名簿", "rows": 21, "cols": 6}],
                    "table": {"header_row": 1, "first_col": "A", "last_col": "F", "data": "2-20", "total_row": 21, "columns": [{"col": "A", "name": "会員番号", "number": False}]}}
    out = []
    S.capture_looks(E(), "FILEID123", ["meibo_base"], looks_dir=tmp_path, out=out.append)
    text = (tmp_path / "meibo_base.txt").read_text(encoding="utf-8")
    assert "FILEID123" not in text and "<試験場>" in text and "シート: 名簿（21行×6列）" in text and "表: 見出し 1 行目" in text


def test_run_golden_runs_lanes_in_parallel_records_and_refail_picks_only_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RUNS_DIR", tmp_path)
    import time
    monkeypatch.setattr(S, "STAGGER", 0)
    cases = [case_sort(id=f"g-{i}") for i in range(4)]

    class Slow(FakeEng):
        def trial_post(self, action, **kw):
            time.sleep(0.05)
            return super().trial_post(action, **kw)
    good, bad = Slow(BEFORE, lambda ops: SORTED), Slow(BEFORE, lambda ops: BEFORE)
    good.lane, bad.lane = "1", "2"
    out = []
    results, rf = S.run_golden(good, "F1", cases, workers=[(good, "F1"), (bad, "F2")], out=out.append, run_file=tmp_path / "golden_t.jsonl")
    assert len(results) == 4 and good.calls and bad.calls                                      # 2 本とも使った
    rows = [json.loads(x) for x in rf.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4 and {r["mark"] for r in rows} == {"○", "M"}
    left = S.refail_cases(cases, "golden_", runs_dir=tmp_path)
    assert sorted(c["id"] for c in left) == sorted(r["id"] for r in rows if r["mark"] == "M")


def test_lint_catches_empty_ops_missing_column_overwrite_and_docs_without_shooting(monkeypatch):
    monkeypatch.undo()
    import copy
    cases = {c["id"]: c for c in S.load_cases()}
    nocol = copy.deepcopy(cases["mei-01"]); nocol["id"] = "x-col"; nocol["model"][0]["col"] = "存在しない列"
    over = copy.deepcopy(cases["kei-05"]); over["id"] = "x-over"; over["model"][0]["range"] = "E5:E24"      # 値のあるセルに、承認なしで書く
    cases["x-col"], cases["x-over"] = nocol, over
    bad = S.lint_cases(list(cases.values()))
    assert bad["x-col"][0].startswith("列名") and bad["x-over"][0].startswith("上書き")
    assert bad["kik-09"][0].startswith("模範なし") and bad["gij-05"][0].startswith("文書")     # 文書に当たる棚が無い頼み（検索）だけが対象外
    assert "gij-01" not in bad and "t1-01" not in bad and "kik-23" not in bad                  # 文書の台本は撃てる・split の by（space）は列名ではない
    assert S.lint_mark(bad["x-col"]) == "L" and S.lint_mark(bad["kik-09"]) == "–" and S.lint_mark(bad["gij-05"]) == "–"
    run, skipped = S.split_by_lint(list(cases.values()), keep_modelless=True)
    assert "kik-09" in [c["id"] for c in run] and "x-col" in [c["id"] for c, _ in skipped]


def test_ai_saying_none_is_right_when_the_script_expects_a_refusal():
    c = case_sort()
    c["turns"][0]["expect"] = {"条件": [{"断った": True}]}
    assert S.run_ai_turn(None, "FID", c, {"無い": "棚が無い"}, None, None, [])["mark"] == "△"
