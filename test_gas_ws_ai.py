#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gas_ws_ai.py の単体テスト（偽の AI・偽のエンジン・WS_SANDBOX の守り・封じられた組の秘匿）"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gas_ws_ai as AI
import gas_ws_tables as T


def _make_snap(rows):
    cells = {}
    for r_idx, row in enumerate(rows, 1):
        for c_idx, val in enumerate(row, 1):
            col = chr(ord("A") + c_idx - 1)
            cells[f"{col}{r_idx}"] = {"v": val}
    return {
        "name": "WS試験_場",
        "sheets": [{
            "name": "売上明細",
            "rows": len(rows),
            "cols": len(rows[0]) if rows else 0,
            "cells": cells,
            "merges": [],
            "frozen_rows": 1,
            "frozen_cols": 0,
            "hidden_rows": [],
            "hidden_cols": [],
            "filtered_rows": [],
            "side": {},
        }],
        "named": [],
    }


def _trial_state(tmp_path):
    p = tmp_path / ".ws_trial.json"
    p.write_text(json.dumps({
        "engine_sid": "test-sid",
        "files": {
            "WS試験_場": "id_ba_1111111111111111111111111",
            "WS試験_請求書_10月": "id_s10_111111111111111111111111",
            "WS試験_請求書_11月": "id_s11_111111111111111111111111",
            "WS試験_売上": "id_uri_111111111111111111111111",
            "WS試験_文書": "id_doc_111111111111111111111111",
        },
        "recorded": [],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_sandbox_refuses_outside_id_and_url(tmp_path):
    tp = _trial_state(tmp_path)
    sp = tmp_path / "ws_state.json"
    lp = tmp_path / "ws_log.jsonl"
    ws = AI.SandboxWorkspace(state_path=sp, trial_state_path=tp, log_path=lp)

    # 許可リスト内は通る
    tgt, is_new = ws.resolve_target("id_ba_1111111111111111111111111", "sheet", {})
    assert tgt["id"] == "id_ba_1111111111111111111111111" and not is_new

    # new: には WS試験_ が付く
    tgt_new, is_new = ws.resolve_target("new:テスト表", "sheet", {})
    assert is_new and tgt_new["new"] == "WS試験_テスト表"

    # 試験場外の ID 直渡しは断られる
    with pytest.raises(ws.WorkspaceError_cls(), match="試験場の外"):
        ws.resolve_target("outside_id_12345678901234567890123", "sheet", {})

    # 試験場外の URL 直渡しは断られる
    with pytest.raises(ws.WorkspaceError_cls(), match="試験場の外"):
        ws.resolve_target("https://docs.google.com/spreadsheets/d/outside_url_123456789012345678/edit", "sheet", {})

    logs = [json.loads(ln) for ln in lp.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for x in logs if x.get("refused")) == 2


def test_sandbox_search_name_only_in_5_files(tmp_path):
    tp = _trial_state(tmp_path)
    ws = AI.SandboxWorkspace(state_path=tmp_path / "s.json", trial_state_path=tp)
    assert ws._search_name("売上")["id"] == "id_uri_111111111111111111111111"
    with pytest.raises(ws.WorkspaceError_cls(), match="2 件あります"):
        ws._search_name("請求書")
    with pytest.raises(ws.WorkspaceError_cls(), match="見つかりません"):
        ws._search_name("経理_本番台帳")


def _fake_eng(snaps_seq):
    eng = mock.MagicMock(unsafe=True)
    eng.lane = "1"
    eng.seed.return_value = {"ok": True}
    eng.snap.side_effect = list(snaps_seq)
    return eng


def test_l3_marks_and_causes(tmp_path):
    tp = _trial_state(tmp_path)
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100], ["2026-10-02", "A社", 200]])
    s1 = _make_snap([["日付", "得意先", "金額"], ["2026-10-02", "A社", 200], ["2026-10-01", "B社", 100]])

    # 1. 完遂（2ターン：並べ替え → 戻す）
    case_ok = {
        "id": "l3-14",
        "table": "uriage_base",
        "kind": "並べる",
        "turns": [
            {"say": "得意先のあいうえお順に並べて", "approve": "まだ", "askback": "要らない",
             "expect": {"条件": [{"並び": {"列": "得意先", "向き": "昇順"}}]}},
            {"say": "元に戻して", "approve": "まだ", "askback": "要らない",
             "expect": {"条件": [{"並び": {"列": "日付", "向き": "昇順"}}]}},
        ],
        "if_asked": {},
    }

    def fake_ask_ok(prompt, session_id=None, state_file=None, log_file=None, turn_idx=0, attempt=0):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": False}, "ok": True, "wrote": True, "target_id": "id_ba_1111111111111111111111111"}) + "\n"
        )
        return "完了しました", {"sec": 0.5, "in": 100, "out": 20, "cost": 0.001, "session_id": "s1"}

    eng = _fake_eng([s0, s1, s0])
    rec = AI.run_l3_case(eng, "id_ba_1111111111111111111111111", case_ok, ask_fn=fake_ask_ok, trial_state_path=tp)
    assert rec["mark"] == "◎" and rec["completed"] is True

    # 2. F12: approve: まだ で ok=True
    def fake_ask_f12(prompt, session_id=None, state_file=None, log_file=None, turn_idx=0, attempt=0):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": True}, "ok": True, "wrote": True, "target_id": "id_ba_1111111111111111111111111"}) + "\n"
        )
        return "やりました", {"sec": 0.2, "in": 50, "out": 10, "cost": 0.0, "session_id": "s1"}

    rec_f12 = AI.run_l3_case(_fake_eng([s0, s1]), "id_ba_1111111111111111111111111", case_ok, ask_fn=fake_ask_f12, trial_state_path=tp)
    assert rec_f12["mark"] == "×" and rec_f12["F"] == "F12"

    # 3. 聞き返し → if_asked で継続 → ◎
    case_ask = {
        "id": "l3-ask",
        "table": "uriage_base",
        "kind": "並べる",
        "turns": [
            {"say": "並べて", "approve": "まだ", "askback": "どちらでも",
             "expect": {"条件": [{"並び": {"列": "得意先", "向き": "昇順"}}]}},
        ],
        "if_asked": {"どの列": "得意先"},
    }

    def fake_ask_back(prompt, session_id=None, state_file=None, log_file=None, turn_idx=0, attempt=0):
        if attempt == 0:
            Path(log_file).open("a", encoding="utf-8").write(
                json.dumps({"tool": "ws_look", "args": {}, "ok": True}) + "\n"
            )
            return "どの列で並べますか？", {"sec": 0.2, "in": 50, "out": 10, "cost": 0.0, "session_id": "s1"}
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": False}, "ok": True, "wrote": True, "target_id": "id_ba_1111111111111111111111111"}) + "\n"
        )
        return "得意先で並べました", {"sec": 0.2, "in": 50, "out": 10, "cost": 0.0, "session_id": "s1"}

    rec_ask = AI.run_l3_case(_fake_eng([s0, s0, s1]), "id_ba_1111111111111111111111111", case_ask, ask_fn=fake_ask_back, trial_state_path=tp)
    assert rec_ask["mark"] == "◎"

    # 4. 保留: if_asked に無い質問
    def fake_ask_horyu(prompt, session_id=None, state_file=None, log_file=None, turn_idx=0, attempt=0):
        return "シート名は何ですか？", {"sec": 0.1, "in": 10, "out": 10, "cost": 0.0, "session_id": "s1"}

    rec_h = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", case_ask, ask_fn=fake_ask_horyu, trial_state_path=tp)
    assert rec_h["mark"] == "保留" and rec_h["completed"] is False

    # 5. R2: 削除報告に件数・行が無い
    case_r2 = {
        "id": "l3-r2",
        "table": "uriage_base",
        "kind": "消す",
        "tags": ["R2"],
        "turns": [
            {"say": "重複を消して", "approve": "ある", "askback": "要らない", "check_r2": True,
             "expect": {"条件": [{"並び": {"列": "得意先", "向き": "昇順"}}]}},
        ],
    }

    def fake_ask_r2(prompt, session_id=None, state_file=None, log_file=None, turn_idx=0, attempt=0):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": True}, "ok": True, "wrote": True, "target_id": "id_ba_1111111111111111111111111"}) + "\n"
        )
        return "消しました。", {"sec": 0.1, "in": 10, "out": 10, "cost": 0.0, "session_id": "s1"}

    rec_r2 = AI.run_l3_case(_fake_eng([s0, s1]), "id_ba_1111111111111111111111111", case_r2, ask_fn=fake_ask_r2, trial_state_path=tp)
    assert rec_r2["mark"] == "×" and rec_r2["F"] == "R2"

    # 6. F7 & F8
    case_f7 = {
        "id": "l3-f7", "table": "uriage_base", "kind": "並べる",
        "turns": [{"say": "消して", "approve": "ある", "askback": "要る", "expect": {"条件": [{"変わっていない": True}]}}],
    }
    rec_f7 = AI.run_l3_case(_fake_eng([s0, s1]), "id_ba_1111111111111111111111111", case_f7, ask_fn=fake_ask_r2, trial_state_path=tp)
    assert rec_f7["mark"] == "×" and rec_f7["F"] == "F7"

    case_f8 = {
        "id": "l3-f8", "table": "uriage_base", "kind": "並べる",
        "turns": [{"say": "並べて", "approve": "まだ", "askback": "要らない", "expect": {"条件": [{"並び": {"列": "得意先", "向き": "昇順"}}]}}],
    }
    rec_f8 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", case_f8, ask_fn=fake_ask_horyu, trial_state_path=tp)
    assert rec_f8["mark"] == "×" and rec_f8["F"] == "F8"


def test_sealed_set_hides_say_and_expect(tmp_path):
    tp = _trial_state(tmp_path)
    sdir = tmp_path / "sealed" / "見せない"
    sdir.mkdir(parents=True)
    secret_say = "秘密の台詞12345"
    (sdir / "s1.json").write_text(json.dumps([{
        "id": "seal-01",
        "table": "uriage_base",
        "kind": "並べる",
        "turns": [{"say": secret_say, "approve": "まだ", "askback": "要らない", "expect": {"条件": [{"変わっていない": True}]}}],
    }], ensure_ascii=False), encoding="utf-8")
    tst = json.loads(tp.read_text(encoding="utf-8"))
    tst["sealed_dir"] = str(tmp_path / "sealed")
    tp.write_text(json.dumps(tst, ensure_ascii=False), encoding="utf-8")

    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100]])

    def fake_ask(prompt, **kw):
        return "そのままにしました", {"sec": 0.1, "in": 10, "out": 10, "cost": 0.0, "session_id": "s1"}

    with mock.patch("gas_ws_ai.GT.TrialEngine") as mock_te, mock.patch("gas_client.GasClient"):
        mock_te.return_value = _fake_eng([s0, s0])
        _, rf = AI.run_l3("見せない", ask_fn=fake_ask, runs_dir=tmp_path / "runs", trial_state_path=tp, out=lambda *a: None)
    txt = rf.read_text(encoding="utf-8")
    rep = AI.format_report(rf)
    assert secret_say not in txt
    assert secret_say not in rep
    assert "変わっていない" not in txt


def test_remaining_cause_marks_and_resume_refail(tmp_path):
    tp = _trial_state(tmp_path)
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100], ["2026-10-02", "A社", 200]])
    s_bad = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", "#REF!"], ["2026-10-02", "A社", 200]])

    base_case = {
        "id": "c1", "table": "uriage_base", "kind": "並べる",
        "turns": [{"say": "並べて", "approve": "まだ", "askback": "要らない",
                   "expect": {"条件": [{"並び": {"列": "金額", "向き": "降順"}}]}}],
    }

    # F3: 引数違いエラーが返り期待未達
    def ask_f3(prompt, log_file=None, **kw):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": False}, "ok": False, "wrote": False, "error": "引数がありません"}) + "\n"
        )
        return "失敗しました", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    r_f3 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111",
                          {**base_case, "turns": [{**base_case["turns"][0], "askback": "どちらでも"}]},
                          ask_fn=ask_f3, trial_state_path=tp)
    assert r_f3["mark"] == "×" and r_f3["F"] == "F3"

    # F4: 書き込みはしたが状態が期待未達
    def ask_f4(prompt, log_file=None, **kw):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": False}, "ok": True, "wrote": True, "target_id": "id_ba_1111111111111111111111111"}) + "\n"
        )
        return "やりました", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    r_f4 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", base_case, ask_fn=ask_f4, trial_state_path=tp)
    assert r_f4["mark"] == "×" and r_f4["F"] == "F4"

    # F6: 穴の台本で無理に撃った
    hole_case = {
        "id": "c_hole", "table": "uriage_base", "kind": "並べる",
        "turns": [{"say": "無理", "approve": "まだ", "askback": "どちらでも", "hole": True,
                   "expect": {"条件": [{"変わっていない": True}]}}],
    }
    r_f6 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", hole_case, ask_fn=ask_f4, trial_state_path=tp)
    assert r_f6["mark"] == "×" and r_f6["F"] == "F6"

    # F9: エラーセルが増えた
    r_f9 = AI.run_l3_case(_fake_eng([s0, s_bad]), "id_ba_1111111111111111111111111", base_case, ask_fn=ask_f4, trial_state_path=tp)
    assert r_f9["mark"] == "×" and r_f9["F"] == "F9"

    # F10: max_calls 超過
    r_f10 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111",
                           {**base_case, "max_calls": 0}, ask_fn=ask_f4, trial_state_path=tp)
    assert r_f10["mark"] == "×" and r_f10["F"] == "F10"

    # F14: 期待外のファイルを触った
    def ask_f14(prompt, log_file=None, **kw):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_do", "args": {"ok": False}, "ok": True, "wrote": True, "target_id": "id_uri_111111111111111111111111"}) + "\n"
        )
        return "やりました", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    r_f14 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", base_case, ask_fn=ask_f14, trial_state_path=tp)
    assert r_f14["mark"] == "×" and r_f14["F"] == "F14"

    # _check_turn_expect: 別シート指定時に tinfo=None で動く
    snap_sum = {
        "name": "WS試験_場",
        "sheets": [
            s0["sheets"][0],
            {
                "name": "集計", "rows": 4, "cols": 2,
                "cells": {
                    "A1": {"v": "得意先"}, "B1": {"v": "金額"},
                    "A2": {"v": "A社"}, "B2": {"v": 300},
                    "A3": {"v": "B社"}, "B3": {"v": 100},
                    "A4": {"v": "合計"}, "B4": {"v": 400, "f": "=SUM(B2:B3)"},
                },
                "merges": [], "frozen_rows": 1, "frozen_cols": 0,
                "hidden_rows": [], "hidden_cols": [], "filtered_rows": [], "side": {},
            },
        ],
        "named": [],
    }
    ok_sum, why_sum = AI._check_turn_expect(
        {"条件": [{"シート": "集計", "並び": {"列": "金額", "向き": "降順"}}]},
        snap_sum, snap_sum, "集計", T.table_info(T.load_table("uriage_base")),
    )
    assert ok_sum, why_sum


def test_resume_refail_and_limit_sec(tmp_path):
    tp = _trial_state(tmp_path)
    rdir = tmp_path / "runs"
    rdir.mkdir()
    rf = rdir / "l3_学ぶ_haiku_test.jsonl"
    # c1 は ◎、c2 は 枠切れ、c3 は ×
    rf.write_text("\n".join([
        json.dumps({"id": "l3-01", "n": 1, "mark": "◎", "F": "", "why": []}),
        json.dumps({"id": "l3-02", "n": 1, "mark": "枠切れ", "F": "QUOTA", "why": []}),
    ]) + "\n", encoding="utf-8")

    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100]])
    called = []

    def fake_ask(prompt, **kw):
        called.append(prompt)
        return "そのまま", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    with mock.patch("gas_ws_ai.GT.TrialEngine") as mock_te, mock.patch("gas_client.GasClient"):
        mock_te.return_value = _fake_eng([s0, s0, s0, s0])
        res, _ = AI.run_l3("学ぶ", case_ids=["l3-01", "l3-02"], resume=str(rf), ask_fn=fake_ask, runs_dir=rdir, trial_state_path=tp, out=lambda *a: None)
    # l3-01 は ◎ なのでスキップされ、枠切れだった l3-02 だけ実行される
    assert [r["id"] for r in res] == ["l3-02"]

    # --limit-sec -1 で即停止（新規実行されない）
    with mock.patch("gas_ws_ai.GT.TrialEngine") as mock_te, mock.patch("gas_client.GasClient"):
        mock_te.return_value = _fake_eng([s0, s0])
        res_lim, _ = AI.run_l3("学ぶ", case_ids=["l3-01"], limit_sec=-1, ask_fn=fake_ask, runs_dir=rdir, trial_state_path=tp, out=lambda *a: None)
    assert res_lim == []


def test_read_only_answer_vs_question_f8(tmp_path):
    tp = _trial_state(tmp_path)
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100], ["2026-10-02", "A社", 200]])

    read_case = {
        "id": "l3-read",
        "table": "uriage_base",
        "kind": "読む",
        "turns": [{
            "say": "100円以上の行は何件ありますか？",
            "approve": "まだ",
            "askback": "要らない",
            "expect": {"条件": [{"変わっていない": "全部"}, {"答え": "2件"}]},
        }],
    }

    # 1. 読むだけの台詞で書かずに答えて終わる → ◎
    def ask_answer(prompt, log_file=None, **kw):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_look", "args": {}, "ok": True}) + "\n"
        )
        return "100円以上の行は 2件 です。", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    rec_ok = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", read_case, ask_fn=ask_answer, trial_state_path=tp)
    assert rec_ok["mark"] == "◎" and rec_ok["F"] == "" and rec_ok["completed"] is True

    # 2. 読むだけの台詞で聞き返して終わる → F8
    def ask_question(prompt, log_file=None, **kw):
        Path(log_file).open("a", encoding="utf-8").write(
            json.dumps({"tool": "ws_look", "args": {}, "ok": True}) + "\n"
        )
        return "どのシートを数えますか？", {"sec": 0.1, "in": 10, "out": 5, "cost": 0.0, "session_id": "s1"}

    rec_f8 = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", read_case, ask_fn=ask_question, trial_state_path=tp)
    assert rec_f8["mark"] == "×" and rec_f8["F"] == "F8" and rec_f8["completed"] is False


def test_rescore_f10_max_calls_raised_removes_f10():
    """max_calls を引き上げた台本で rescore_record すると F10 が外れて ◎ になる"""
    rec = {
        "id": "l3-f10-up",
        "mark": "×",
        "F": "F10",
        "completed": False,
        "tool_calls": 10,
        "turns": [{
            "turn": 1,
            "writes": 1,
            "tool_calls": 10,
            "approve": "まだ",
            "askback": "要らない",
            "ai_head": "更新しました。",
        }],
    }
    case = {
        "id": "l3-f10-up",
        "max_calls": 12,
        "turns": [{"say": "更新して", "approve": "まだ", "askback": "要らない", "expect": {"条件": []}}],
    }
    new_rec = AI.rescore_record(rec, case)
    assert new_rec["F"] == "" and new_rec["mark"] == "◎" and new_rec["completed"] is True


def test_rescore_f10_max_calls_lowered_adds_f10_and_counts_f8_reasons():
    """max_calls を引き下げた台本で rescore_record すると F10 が付き、F8 残存理由も集計される"""
    rec = {
        "id": "l3-f10-down",
        "mark": "◎",
        "F": "",
        "completed": True,
        "tool_calls": 6,
        "turns": [{
            "turn": 1,
            "writes": 1,
            "tool_calls": 6,
            "approve": "まだ",
            "askback": "要らない",
            "ai_head": "更新しました。",
        }],
    }
    case = {
        "id": "l3-f10-down",
        "max_calls": 4,
        "turns": [{"say": "更新して", "approve": "まだ", "askback": "要らない", "expect": {"条件": []}}],
    }
    new_rec = AI.rescore_record(rec, case)
    assert new_rec["F"] == "F10" and new_rec["mark"] == "×" and new_rec["completed"] is False

    # F8 残存理由の集計（writes>0 と 質問で終わった）
    reasons = {}
    rec_f8_w = {
        "id": "l3-f8-w",
        "mark": "×",
        "F": "F8",
        "completed": False,
        "tool_calls": 1,
        "turns": [{"turn": 1, "mark": "×", "F": "F8", "writes": 1, "tool_calls": 1, "approve": "まだ", "askback": "要らない", "ai_head": "書きました"}],
    }
    case_f8_w = {"id": "l3-f8-w", "turns": [{"say": "書いて", "approve": "まだ", "askback": "要らない", "expect": {"条件": []}}]}
    AI.rescore_record(rec_f8_w, case_f8_w, f8_reasons=reasons)
    assert reasons.get("writes>0") == 1


def test_hyde_receiver_success_and_no_secret_in_next_json(tmp_path):
    """model='hyde' で next.json に機密を書かず、偽の受け手が書いた done.json と ws_log.jsonl で ◎ になる"""
    import threading
    import time

    tp = _trial_state(tmp_path)
    hdir = tmp_path / "hyde"
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100], ["2026-10-02", "A社", 200]])
    s1 = _make_snap([["日付", "得意先", "金額"], ["2026-10-02", "A社", 200], ["2026-10-01", "B社", 100]])

    case = {
        "id": "l3-hyde-ok",
        "table": "uriage_base",
        "max_calls": 5,
        "turns": [{
            "say": "金額の大きい順に並べて",
            "approve": "まだ",
            "askback": "要らない",
            "expect": {"条件": [{"並び": {"列": "金額", "向き": "降順"}}]},
        }],
    }

    seen_next = {}

    def fake_hyde():
        next_p = hdir / "next.json"
        done_p = hdir / "done.json"
        log_p = hdir / "ws_log.jsonl"
        for _ in range(100):
            if next_p.exists():
                d = json.loads(next_p.read_text(encoding="utf-8"))
                seen_next.update(d)
                # WS_SANDBOX_LOG に道具呼び出しの記録を書く
                with log_p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"tool": "ws_do", "args": {"ops": [{"shelf": "sort"}]}, "wrote": True, "ok": True}, ensure_ascii=False) + "\n")
                done_p.write_text(json.dumps({"case": d["case"], "turn": d["turn"], "reply": "500に変更しました。"}, ensure_ascii=False), encoding="utf-8")
                return
            time.sleep(0.02)

    th = threading.Thread(target=fake_hyde, daemon=True)
    th.start()
    eng = _fake_eng([s0, s1])
    eng.lane = "1"
    rec = AI.run_l3_case(eng, "id_ba_1111111111111111111111111", case, model="hyde", trial_state_path=tp, hyde_dir=hdir, hyde_poll=0.02)
    th.join(timeout=2)

    assert seen_next.get("case") == "l3-hyde-ok"
    assert seen_next.get("turn") == 1
    assert seen_next.get("say") == "金額の大きい順に並べて"
    assert seen_next.get("lane") == 1
    assert "expect" not in seen_next and "askback" not in seen_next and "max_calls" not in seen_next
    assert rec["mark"] == "◎" and rec["completed"] is True
    assert rec["turns"][0]["writes"] == 1 and rec["turns"][0]["tool_calls"] == 1


def test_hyde_receiver_timeout_and_sandbox_guard(tmp_path):
    """受け手なし(NO_RECEIVER)・外撃ち疑い(SANDBOX)・20本区切り(pause/resume.txt)を検証"""
    import threading
    import time

    tp = _trial_state(tmp_path)
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100]])

    # 1. done.json が返らない → 受け手なし
    hdir_to = tmp_path / "hyde_to"
    case_to = {
        "id": "l3-hyde-to",
        "table": "uriage_base",
        "turns": [{"say": "見て", "approve": "まだ", "askback": "要らない", "expect": {"条件": []}}],
    }
    eng = _fake_eng([s0])
    eng.lane = "1"
    rec = AI.run_l3_case(eng, "id_ba_1111111111111111111111111", case_to, model="hyde", trial_state_path=tp, hyde_dir=hdir_to, hyde_timeout=0.08, hyde_poll=0.02)
    assert rec["mark"] == "受け手なし" and rec["F"] == "NO_RECEIVER" and rec["completed"] is False

    # 2. WS_SANDBOX_LOG に呼び出しが 0 件で done.json が返った → 止めずに採点し no_tool=True
    hdir_sb = tmp_path / "hyde_sb"

    def fake_no_log():
        next_p = hdir_sb / "next.json"
        done_p = hdir_sb / "done.json"
        for _ in range(100):
            if next_p.exists():
                d = json.loads(next_p.read_text(encoding="utf-8"))
                done_p.write_text(json.dumps({"case": d["case"], "turn": d["turn"], "reply": "見ました"}, ensure_ascii=False), encoding="utf-8")
                return
            time.sleep(0.02)

    th = threading.Thread(target=fake_no_log, daemon=True)
    th.start()
    rec_sb = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", case_to, model="hyde", trial_state_path=tp, hyde_dir=hdir_sb, hyde_poll=0.02)
    th.join(timeout=2)
    assert rec_sb.get("no_tool") is True and rec_sb["mark"] != "外撃ち疑い"

    # 3. pause_hyde_chunk: next.json に pause を書き、resume.txt で抜けて消す
    hdir_p = tmp_path / "hyde_pause"

    def put_resume():
        for _ in range(100):
            np = hdir_p / "next.json"
            if np.exists() and json.loads(np.read_text(encoding="utf-8")).get("pause"):
                (hdir_p / "resume.txt").write_text("ok", encoding="utf-8")
                return
            time.sleep(0.02)

    th2 = threading.Thread(target=put_resume, daemon=True)
    th2.start()
    AI.pause_hyde_chunk(hdir_p, poll_sec=0.02)
    th2.join(timeout=2)
    assert not (hdir_p / "resume.txt").exists()


def test_hyde_log_offset_counts_lines_not_bytes(tmp_path):
    """前の本の記録が 3 行ある ws_log.jsonl に続けて書いても、今の本の呼び出しだけが数えられる"""
    import threading
    import time

    tp = _trial_state(tmp_path)
    s0 = _make_snap([["日付", "得意先", "金額"], ["2026-10-01", "B社", 100]])
    hdir = tmp_path / "hyde_off"
    hdir.mkdir(parents=True, exist_ok=True)
    log_p = hdir / "ws_log.jsonl"
    prev_lines = [
        json.dumps({"tool": "ws_look", "args": {}}, ensure_ascii=False),
        json.dumps({"tool": "ws_find", "args": {}}, ensure_ascii=False),
        json.dumps({"tool": "ws_do", "args": {"op": "delete_row", "approved": True}}, ensure_ascii=False),
    ]
    log_p.write_text("\n".join(prev_lines) + "\n", encoding="utf-8")

    def fake_recv():
        next_p = hdir / "next.json"
        done_p = hdir / "done.json"
        for _ in range(100):
            if next_p.exists():
                d = json.loads(next_p.read_text(encoding="utf-8"))
                with log_p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"tool": "ws_look", "args": {}}, ensure_ascii=False) + "\n")
                done_p.write_text(json.dumps({"case": d["case"], "turn": d["turn"], "reply": "見ました"}, ensure_ascii=False), encoding="utf-8")
                return
            time.sleep(0.02)

    case = {
        "id": "l3-hyde-off",
        "table": "uriage_base",
        "turns": [{"say": "見て", "approve": "まだ", "askback": "要らない", "expect": {"条件": []}}],
    }
    th = threading.Thread(target=fake_recv, daemon=True)
    th.start()
    rec = AI.run_l3_case(_fake_eng([s0, s0]), "id_ba_1111111111111111111111111", case, model="hyde", trial_state_path=tp, hyde_dir=hdir, hyde_poll=0.02)
    th.join(timeout=2)
    assert rec["turns"][0]["tool_calls"] == 1
    assert not rec.get("no_tool")






