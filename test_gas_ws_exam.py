# -*- coding: utf-8 -*-
"""段 2: AI を通した試験の数え方（偽の AI＝決まった返事を返す関数。本物の AI も通信も使わない）"""

import io
import json
import socket
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import gas_workspace as gw
import gas_ws_exam as ex


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("本物の通信・AI の呼び出しに出ようとしました（試験は偽の AI だけ）")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)


def _example_for(shelf):
    return json.dumps([gw.CATALOG.by_name[shelf]["examples"][0][1]], ensure_ascii=False)


def _perfect_ai(questions):
    """頼みの文から、期待の棚の札の例を返す偽の AI"""
    table = {}
    for exp, ask, _ in questions:
        table[ask] = "[" + ",".join(_example_for(e)[1:-1] for e in exp) + "]"

    def fn(prompt):
        ask = prompt.split("【頼み】\n", 1)[1].strip()
        return table[ask]
    return fn


def test_select_questions_is_deterministic_and_spreads_over_shelves():
    a = ex.select_questions(30)
    assert a == ex.select_questions(30) and len(a) == 30
    shelves = {q[0][0] for q in a}
    assert len(shelves) >= 27 - 3                       # 棚ごとにまんべんなく（1 巡目で各棚から 1 問）
    assert all(q[0][0] not in ("(なし)", "(案内)") for q in a)
    assert len(ex.select_questions(5)) == 5


def test_prompt_contains_find_reply_and_ask():
    p = ex.build_prompt("3行目を消して", "棚の候補（1 本）…")
    assert "棚の候補（1 本）" in p and "【頼み】\n3行目を消して" in p and "[]" in p


def test_parse_ops_from_replies():
    assert ex.parse_ops_from('[{"shelf":"tidy"}]') == [{"shelf": "tidy"}]
    assert ex.parse_ops_from('```json\n[{"shelf":"tidy"}]\n```') == [{"shelf": "tidy"}]
    assert ex.parse_ops_from('はい。\n[{"shelf":"tidy"}]\n以上です') == [{"shelf": "tidy"}]
    assert ex.parse_ops_from('{"shelf":"tidy"}') == [{"shelf": "tidy"}]
    assert ex.parse_ops_from("わかりません") is None
    assert ex.parse_ops_from("[]") == []


def test_perfect_fake_ai_scores_full_marks():
    qs = ex.select_questions(30)
    results, stats = ex.evaluate(qs, _perfect_ai(qs))
    assert stats["n"] == 30 and stats["shelf_ok"] == 30 and stats["valid"] == 30
    assert stats["shelf_pct"] == 100 and stats["valid_pct"] == 100 and stats["pass"] is True
    assert "目安どおり" in ex.report(results, stats)[0] and len(ex.report(results, stats)) == 1


def test_counting_wrong_shelf_invalid_args_unreadable_empty_and_exception():
    qs = ex.select_questions(10)
    good = _perfect_ai(qs)
    seen = []

    def fn(prompt):
        i = len(seen)
        seen.append(i)
        if i == 0:
            return '[{"shelf":"tidy"}]'                       # 棚が違う（検査は通る）。期待が tidy の問に当たれば当たってしまうので別の棚を選ぶ
        if i == 1:
            return '[{"shelf":"' + qs[1][0][0] + '","zzz":1}]'  # 棚は合うが引数が合わない
        if i == 2:
            return "ちょっとわかりません"                         # 読めない
        if i == 3:
            return "[]"                                       # 棚にありません、と答えた
        if i == 4:
            raise RuntimeError("timeout")                      # AI が答えなかった
        return good(prompt)

    # 0 問目は期待が tidy でないことを確かめてから使う
    assert qs[0][0] != ["tidy"]
    results, stats = ex.evaluate(qs, fn)
    assert [r["shelf_ok"] for r in results[:5]] == [False, True, False, False, False]
    assert [r["valid"] for r in results[:5]] == [True, False, False, False, False]
    assert "引数「zzz」はありません" in results[1]["why"]
    assert "読めません" in results[2]["why"] and "棚にありません" in results[3]["why"] and "AI の呼び出しに失敗" in results[4]["why"]
    assert stats["shelf_ok"] == 6 and stats["valid"] == 6 and stats["pass"] is False
    rep = ex.report(results, stats)
    assert "目安を下回りました" in rep[0] and "下回った問" in rep[1] and len(rep) == 2 + 5


def test_threshold_is_ninety_percent_each():
    qs = ex.select_questions(10)
    good = _perfect_ai(qs)
    n = [0]

    def one_wrong(prompt):
        n[0] += 1
        return '[{"shelf":"tidy"}]' if n[0] == 1 and qs[0][0] != ["tidy"] else good(prompt)
    _, stats = ex.evaluate(qs, one_wrong)
    assert stats["shelf_pct"] == 90 and stats["valid_pct"] == 100 and stats["pass"] is True     # 9/10 は目安どおり
    n[0] = 0

    def two_wrong(prompt):
        n[0] += 1
        return '[{"shelf":"tidy"}]' if n[0] <= 2 and qs[n[0] - 1][0] != ["tidy"] else good(prompt)
    _, stats = ex.evaluate(qs, two_wrong)
    assert stats["shelf_pct"] == 80 and stats["pass"] is False


def test_exam_never_fires_a_shelf_or_touches_files(monkeypatch):
    called = []
    monkeypatch.setattr(gw.WorkspaceManager, "do", lambda *a, **k: called.append("do"))
    monkeypatch.setattr(gw.WorkspaceManager, "_post", lambda *a, **k: called.append("post"))
    qs = ex.select_questions(8)
    ex.evaluate(qs, _perfect_ai(qs))
    assert called == []


def test_main_prints_report_and_returns_zero(monkeypatch):
    qs = ex.select_questions(6)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ex.main(n=6, ask_fn=_perfect_ai(qs))
    assert rc == 0 and "AI を通した試験 6 問" in buf.getvalue()


def test_cli_without_ai_flag_does_not_call_ai(monkeypatch):
    import gas
    monkeypatch.setattr(sys, "argv", ["gas.py", "ws-exam"])
    monkeypatch.setattr(ex, "claude_code_ask", lambda *a, **k: pytest.fail("AI を呼んではいけない"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        gas.main()
    assert "--ai" in buf.getvalue()


def test_default_ai_is_headless_claude_code_sonnet(monkeypatch):
    assert ex.DEFAULT_MODEL == "sonnet" and ex.DEFAULT_N == 30
    seen = {}

    class R:
        returncode = 0
        stdout = '[{"shelf":"tidy"}]'.encode("utf-8")
        stderr = b""

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ex.claude_code_ask("頼み") == '[{"shelf":"tidy"}]'
    assert Path(seen["cmd"][0]).stem.lower() == "claude" and seen["cmd"][1:4] == ["-p", "--model", "sonnet"] and seen["input"] == "頼み".encode("utf-8")
