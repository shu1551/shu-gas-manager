# -*- coding: utf-8 -*-
"""
test_gas_ws_realworld.py - ws_exam/ask_realworld.tsv を数秒で全件通す実戦回帰テスト＋外れ収集確認
"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gas_ws_ask as A
import gas_ws_find as F
import gas_workspace as W

FINDER = F.Finder()
TSV_PATH = HERE / "ws_exam" / "ask_realworld.tsv"

# 3行目見出し・日付/文字/数値/進捗率の標準テーブル
REALWORLD_TABLE = {
    "header_row": 3,
    "first_col": "A",
    "last_col": "I",
    "data": "4-9",
    "title_a1": "A1",
    "columns": [
        {"col": "A", "name": "日付", "number": False},
        {"col": "B", "name": "部門", "number": False},
        {"col": "C", "name": "担当者", "number": False},
        {"col": "D", "name": "商品名", "number": False},
        {"col": "E", "name": "数量", "number": True},
        {"col": "F", "name": "単価", "number": True},
        {"col": "G", "name": "売上金額", "number": True},
        {"col": "H", "name": "進捗率", "number": True},
        {"col": "I", "name": "備考", "number": False},
    ],
}


def _load_cases():
    cases = []
    for lineno, raw in enumerate(TSV_PATH.read_text(encoding="utf-8").splitlines(), 1):
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = raw.split("\t")
        want_fire = parts[0].strip() == "1"
        ask = parts[1].strip()
        exp = parts[2].strip() if len(parts) >= 3 else ""
        cases.append((lineno, want_fire, ask, exp))
    return cases


@pytest.mark.parametrize("lineno, want_fire, ask, exp", _load_cases())
def test_ask_realworld_tsv(lineno, want_fire, ask, exp):
    p = A.plan(ask, FINDER, "sheet", REALWORLD_TABLE, ["シート1"], "シート1")
    assert p.fire is want_fire, f"L{lineno} [{ask}] fire={p.fire} want={want_fire} reasons={p.reasons} missing={p.missing} ops={p.ops}"
    if want_fire and exp:
        expected_ops = json.loads(exp)
        assert len(p.ops) == len(expected_ops), f"L{lineno} [{ask}] ops={p.ops}"
        for actual, want in zip(p.ops, expected_ops):
            for k, v in want.items():
                assert actual.get(k) == v, f"L{lineno} [{ask}] key={k} actual={actual} want={want}"
            if want.get("shelf") == "filter.where" and want.get("when") in ("gt", "ge", "lt", "le"):
                assert "equals" not in actual
    elif not want_fire and exp:
        msg = " ".join(p.reasons + p.missing)
        assert exp in msg, f"L{lineno} [{ask}] expected '{exp}' in '{msg}'"


def test_freeze_uses_table_header_row():
    t2 = dict(REALWORLD_TABLE, header_row=2, data="3-9")
    p = A.plan("見出し行を固定して", FINDER, "sheet", t2, ["シート1"], "シート1")
    assert p.fire and p.ops == [{"shelf": "freeze", "rows": 2}]


def test_ask_misses_logging_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.delenv("WS_NO_MISS_LOG", raising=False)
    state_p = tmp_path / ".ws_state.json"
    state_p.write_text(
        json.dumps(
            {
                "target": {"id": "ss_1", "name": "テスト表", "kind": "sheet", "sheet": "Sheet1"},
                "table_cache": {"id": "ss_1", "sheet": "Sheet1", "sheets": ["Sheet1"], "table": REALWORLD_TABLE},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mgr = W.WorkspaceManager(state_path=state_p, browser_detect=False)
    monkeypatch.setattr(mgr, "_look", lambda **kw: "")

    res = mgr.do(ask="進捗率が未定未満の行だけフィルタで表示して", target="")
    assert "撃っていません" in res
    miss_file = tmp_path / ".ws_ask_misses.tsv"
    lines1 = [ln for ln in miss_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines1) == 1 and "進捗率が未定未満の行だけフィルタで表示して" in lines1[0]

    # 連続同一の失敗は重複追記しない
    mgr.do(ask="進捗率が未定未満の行だけフィルタで表示して", target="")
    lines2 = [ln for ln in miss_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines2) == 1
