# -*- coding: utf-8 -*-
"""ws_do(ask=…)：頼みの文 1 つから ops を組む（通信なし）"""
import json

import gas_workspace as gw
import gas_ws_ask as A
import gas_ws_catalog as cat_mod

FD = gw.WorkspaceManager(state_path=None).finder

URIAGE = {"header_row": 1, "first_col": "A", "last_col": "G", "data": "2-21", "total_row": 22,
          "columns": [{"col": c, "name": n, "number": False} for c, n in
                      zip("ABCDEFG", ["日付", "伝票番号", "得意先", "品名", "数量", "単価", "金額"])]}


def plan(ask, table=URIAGE, kind="sheet"):
    return A.plan(ask, FD, kind, table, ["売上"], cur_sheet="売上")


def test_clear_asks_fire_with_built_args():
    p = plan("金額の大きい順に並べて")
    assert p.fire and p.ops == [{"shelf": "sort", "desc": True, "col": "金額"}]
    p = plan("3行目から5行目を消して")
    assert p.fire and p.ops[0]["rows"] == [3, 4, 5]
    p = plan("見出しを太字にして青い背景にして")
    assert p.fire and p.ops[0]["bold"] is True and p.ops[0]["bg"] == "青" and p.ops[0]["header"] is True
    p = plan("金額が1000以上のセルを黄色くして")
    assert p.fire and p.ops[0] == {"shelf": "cf.add", "when": "ge", "value": "1000", "bg": "黄", "range": "G2:G21"}
    p = plan("C列とD列の間に空の列を足して")
    assert p.fire and p.ops[0]["at"] == "D"
    p = plan("A列とB列を入れ替えて")
    assert p.fire and (p.ops[0]["from"], p.ops[0]["to"]) == ("A", "B")


def test_two_clauses_make_two_ops():
    p = plan("1行おきに色を付けて、売上の棒グラフも作って")
    assert p.fire and [o["shelf"] for o in p.ops] == ["banding.add", "chart.new"]


def test_vague_or_dangerous_without_a_named_place_do_not_fire():
    for ask in ("いらない行を消して", "古いデータを消して", "この辺の列を消して", "どこかの金額を直して"):
        p = plan(ask)
        assert not p.fire, ask
    assert "日付" in json.dumps(plan("日付の古い順に並べ替えて").ops, ensure_ascii=False)   # 「古い順」は曖昧ではない


def test_out_of_scope_and_split_asks_do_not_fire():
    assert not plan("このシートをPDFにしてメールで送って").fire
    assert not plan("会社の角印の画像をシートの右下に貼り付けて").fire
    p = plan("B2の値を『確定』に書き換えて")       # 置換の棚より、書く棚の決めが当たっている＝割れたとして撃たない
    assert not p.fire


def test_unfired_text_shows_missing_and_cards():
    p = plan("会員番号がダブってる行を消して")
    text = A.render_unfired(p, FD)
    assert text.startswith("撃っていません") and "ws_do(ops=" in text


def test_ask_rules_parse_and_reject_bad_forms():
    args = {"desc": {"name": "desc", "type": "真偽"}, "value": {"name": "value", "type": "文字"}}
    r = cat_mod.parse_ask_rules("desc=true<大きい順|降順 ; value~([0-9]+)以上", args)
    assert r[0] == {"arg": "desc", "value": True, "words": ["大きい順", "降順"]} and r[1]["re"] == "([0-9]+)以上"
    for bad in ("nope=1<語", "desc~大きい", "desc~(", "desc 大きい"):
        try:
            cat_mod.parse_ask_rules(bad, args)
            assert False, bad
        except cat_mod.CatalogError:
            pass


def test_shelf_dicts_stay_json_serializable():
    json.dumps(gw.CATALOG.shelves, ensure_ascii=False)


def test_mcp_ws_only_mode_and_description_size(monkeypatch):
    import ast
    from pathlib import Path
    src = (Path(__file__).parent / "gas_mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = {n.name: ast.get_docstring(n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in A_WS}
    assert set(docs) == set(A_WS) and sum(len(d) for d in docs.values()) <= 1500
    assert docs["ws_do"].index("ask=") < docs["ws_do"].index("ops=")
    assert 'GAS_MCP_ONLY' in src


A_WS = ("ws_do", "ws_look", "ws_find", "ws_undo")
