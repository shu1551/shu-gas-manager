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


# ---------------------------------------------------------------- 表の様子・聞き返し・別解
import gas_ws_check as chk


def test_prompt_carries_the_sample_look_like_ws_look():
    seen = []
    qs = [q for q in ex.select_questions(30) if q[1] == "合計のとこ太字で黄色に" or q[0] == ["format"]][:1]
    ex.evaluate(qs, lambda p: seen.append(p) or "[]", extras={})
    p = seen[0]
    assert "【今の相手の様子（ws_look の返事）】" in p and "シート: 売上（21行×5列）" in p
    assert "見出し 1 行目・1〜5 列・明細 2-20 行目・合計行 21 行目" in p and "列: A=番号(数値)、B=日付、C=部署、D=名前、E=金額(数値)" in p
    assert p.index("今の相手の様子") < p.index("【棚の候補】") < p.index("【頼み】") and "質問: …" in p


def test_doc_questions_get_a_sample_document_instead():
    seen = []
    qs = [q for q in ex.select_questions(30) if q[0][0].startswith("doc.")][:1]
    ex.evaluate(qs, lambda p: seen.append(p) or "[]", extras={})
    assert "見出し: 1:#会議の記録" in seen[0] and "シート: 売上" not in seen[0]
    assert "シート: 売上" in ex.sample_look("sheet") and "決定事項" in ex.sample_look("doc")


def test_ask_back_counts_only_when_the_question_is_marked():
    qs = [(["cols.delete"], "この列いらないから消して", "t:1"), (["tidy"], "この表、見やすくして", "t:2")]
    extras = {"この列いらないから消して": {"ask_ok": True, "alts": []}}
    results, stats = ex.evaluate(qs, lambda p: "質問: どの列を消しますか？", extras=extras)
    assert results[0]["shelf_ok"] and results[0]["valid"] and results[0]["asked"]            # 印のある問: 聞き返しも正解
    assert not results[1]["shelf_ok"] and not results[1]["valid"] and "聞き返しを正解に数えない" in results[1]["why"]
    assert stats["asked"] == 1 and stats["shelf_ok"] == 1
    assert "うち聞き返し 1 問" in ex.report(results, stats)[0]
    # 印のある問でも、ops で答えて合っていれば（棚が合い検査を通れば）これまでどおり正解
    results, stats = ex.evaluate(qs[:1], lambda p: '[{"shelf":"cols.delete","cols":["C"]}]', extras=extras)
    assert results[0]["shelf_ok"] and results[0]["valid"] and not results[0].get("asked")
    # 全角コロンの質問も読む
    assert ex.ASK_BACK.match("質問：どの列ですか")


def test_alternative_answer_one_shelf_with_arguments_counts():
    q = [(["seiri", "renumber"], "C列の重複消して連番ふり直して", "t:1")]
    extras = {"C列の重複消して連番ふり直して": {"ask_ok": False, "alts": chk.parse_alternatives("seiri{renumber,dedupe}")}}
    one = '[{"shelf":"seiri","dedupe":true,"renumber":"A"}]'
    results, stats = ex.evaluate(q, lambda p: one, extras=extras)
    assert results[0]["shelf_ok"] and results[0]["valid"] and stats["pass"]
    # 引数が足りなければ別解にならない（renumber だけ・seiri だけ）
    for bad in ('[{"shelf":"seiri","renumber":"A"}]', '[{"shelf":"seiri","dedupe":true}]', '[{"shelf":"renumber","col":"A"}]'):
        r, _ = ex.evaluate(q, lambda p, b=bad: b, extras=extras)
        assert not r[0]["shelf_ok"], bad
    # 別解が無ければ、これまでどおり 2 本そろわないと正解にならない
    r, _ = ex.evaluate(q, lambda p: one, extras={})
    assert not r[0]["shelf_ok"]
    r, _ = ex.evaluate(q, lambda p: '[{"shelf":"seiri"},{"shelf":"renumber","col":"A"}]', extras={})
    assert r[0]["shelf_ok"] and r[0]["valid"]


def test_parse_alternatives_and_question_bank_marks():
    assert chk.parse_alternatives("seiri{renumber,dedupe}") == [[("seiri", ["renumber", "dedupe"])]]
    assert chk.parse_alternatives("a.b+c|d{x}") == [[("a.b", []), ("c", [])], [("d", ["x"])]]
    assert chk.parse_alternatives("") == []
    ex_ = chk.load_extras()
    for ask in ("この列いらないから消して", "この行いらないから消して", "この列を右に動かして", "この行を上に動かして"):
        assert ex_[ask]["ask_ok"] is True
    assert ex_["C列の重複消して連番ふり直して"]["alts"] == [[("seiri", ["renumber", "dedupe"])]]
    # 印（?）があっても、問題集は棚の名前として読む（引く試験・ws-check がそのまま通る）
    qs = {ask: exp for exp, ask, _ in chk.load_questions()}
    assert qs["この列いらないから消して"] == ["cols.delete"]
    assert chk.run(write=False)[0] == []


def test_select_questions_still_includes_marked_and_alternative_questions():
    asks = {q[1] for q in ex.select_questions(200)}
    assert "この列いらないから消して" in asks and "C列の重複消して連番ふり直して" in asks
