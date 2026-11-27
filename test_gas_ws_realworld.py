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
        mode = parts[0].strip()
        ask = parts[1].strip()
        exp = parts[2].strip() if len(parts) >= 3 else ""
        cases.append((lineno, mode, ask, exp))
    return cases


@pytest.mark.parametrize("lineno, mode, ask, exp", _load_cases())
def test_ask_realworld_tsv(lineno, mode, ask, exp):
    p = A.plan(ask, FINDER, "sheet", REALWORLD_TABLE, ["シート1"], "シート1")
    if mode == "R":
        assert not p.fire and p.read_only is True and not p.ops, f"L{lineno} [{ask}] fire={p.fire} read_only={p.read_only} ops={p.ops}"
        return
    want_fire = mode == "1"
    assert p.fire is want_fire, f"L{lineno} [{ask}] fire={p.fire} want={want_fire} read_only={p.read_only} reasons={p.reasons} missing={p.missing} ops={p.ops}"
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


def test_two_tier_header_direct_and_plan():
    import gas_ws_direct as D

    def _c(v):
        if v == "":
            return {}
        if isinstance(v, (int, float)):
            return {"formattedValue": str(v), "effectiveValue": {"numberValue": v}}
        return {"formattedValue": str(v), "effectiveValue": {"stringValue": str(v)}}

    rows = [
        ["月別売上", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["部門", "上期", "", "", "下期", "", "", "年計"],
        ["", "4月", "5月", "6月", "10月", "11月", "12月", ""],
        ["第一営業部", 1200, 1350, 1100, 1500, 1650, 1800, 8600],
        ["第二営業部", 900, 950, 1020, 980, 1100, 1250, 6200],
        ["合計", 2100, 2300, 2120, 2480, 2750, 3050, 14800],
    ]
    merges = [
        {"startRowIndex": 2, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 1},
        {"startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 1, "endColumnIndex": 4},
        {"startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 4, "endColumnIndex": 7},
        {"startRowIndex": 2, "endRowIndex": 4, "startColumnIndex": 7, "endColumnIndex": 8},
    ]
    tb = D._find_table_direct([{"values": [_c(x) for x in r]} for r in rows], merges=merges)
    assert tb["header_row"] == 3 and tb.get("header_rows") == 2 and tb["data"] == "5-6" and tb["total_row"] == 7
    assert [c["name"] for c in tb["columns"]] == ["部門", "上期・4月", "上期・5月", "上期・6月", "下期・10月", "下期・11月", "下期・12月", "年計"]

    p18 = A.plan("上期と下期の小計の列を足して", FINDER, "sheet", tb, ["月別"], "月別")
    assert p18.fire and p18.ops == [
        {"shelf": "calc.col", "name": "上期小計", "expr": "上期・4月+上期・5月+上期・6月"},
        {"shelf": "calc.col", "name": "下期小計", "expr": "下期・10月+下期・11月+下期・12月"},
    ]
    p20 = A.plan("部門ごとの月の推移を折れ線グラフにして", FINDER, "sheet", tb, ["月別"], "月別")
    assert p20.fire and p20.ops == [{"shelf": "chart.new", "type": "line", "range": "A4:G6", "transpose": True}]
    pf = A.plan("見出し行を固定して", FINDER, "sheet", tb, ["月別"], "月別")
    assert pf.fire and pf.ops == [{"shelf": "freeze", "rows": 4}]
