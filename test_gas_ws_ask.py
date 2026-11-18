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


def test_words_inside_quotes_are_not_read_as_columns():
    p = plan("グラフのタイトルを『得意先別売上』に")
    assert all("range" not in o and "col" not in o for o in p.ops), p.ops


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
    p = plan("B2の値を『確定』に書き換えて")       # A1セル番地＋書き換えは write が勝って撃つ
    assert p.fire and p.ops[0]["shelf"] == "write" and p.ops[0]["cells"] == {"B2": "確定"}


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


def test_title_font_color_and_format_asks():
    # タイトルは1行目・見出しは3行目の表で検証
    t = {"header_row": 3, "first_col": "A", "last_col": "G", "data": "4-8", "total_row": 9, "columns": []}
    for ask, exp_color in (
        ("タイトルの文字の色を赤に変えてください", "赤"),
        ("タイトルの文字色を青にして", "青"),
        ("タイトルの文字色を緑色に変えて", "緑"),
        ("タイトルの文字を水色に変えて", "水色"),
        ("タイトルの文字色を#FF6600にして", "#FF6600"),
        ("タイトルの文字色を#A1B2C3にして", "#A1B2C3"),
        ("タイトルの文字色をnavyに", "navy"),
    ):
        p = plan(ask, table=t)
        assert p.fire and p.ops == [{"shelf": "format", "title": True, "color": exp_color}], (ask, p.ops, p.reasons)

    # 複数色（文字色と背景色の両方）が混ざらず振り分けられること
    p = plan("タイトルを白文字で青い背景に", table=t)
    assert p.fire and p.ops == [{"shelf": "format", "title": True, "color": "白", "bg": "青"}], p.ops
    p = plan("タイトルの文字の色を赤に、背景を薄い黄色にして", table=t)
    assert p.fire and p.ops == [{"shelf": "format", "title": True, "color": "赤"}, {"shelf": "format", "bg": "薄黄", "title": True}], p.ops

    # 文字色以外のタイトル書式変更
    assert plan("タイトルを太字にして", table=t).ops == [{"shelf": "format", "bold": True, "title": True}]
    assert plan("タイトルの文字サイズを16ptにして", table=t).ops == [{"shelf": "format", "title": True, "size": 16}]
    assert plan("タイトルを中央揃えにして", table=t).ops == [{"shelf": "format", "title": True, "align": "center"}]

    # グラフタイトル・タブ色など他棚への競合が起きないこと
    p_chart = plan("今あるグラフのタイトルを分類別在庫に変えて", table=t)
    assert p_chart.fire and p_chart.ops[0]["shelf"] == "chart.new" and p_chart.ops[0]["title"] == "分類別在庫"
    p_tab = plan("売上シートのタブを赤にして", table=t)
    assert p_tab.fire and p_tab.ops[0]["shelf"] == "sheet.color" and p_tab.ops[0]["color"] == "赤"

    # シート名＋括弧補足（(A1)等）があっても calc.col と割れず、sheet 引数付きで1発で組めること
    p_sh = A.plan(
        "GASマネージャー速度検証_部門別売上表 シートのタイトル（A1）の文字色を青に変えてください。",
        FD, "sheet", t, ["GASマネージャー速度検証_部門別売上表", "集計"], cur_sheet="集計"
    )
    assert p_sh.fire and p_sh.ops == [{
        "shelf": "format", "title": True, "color": "青", "sheet": "GASマネージャー速度検証_部門別売上表"
    }], (p_sh.ops, p_sh.reasons)

    # 直前のスコープ（last_scope）を引き継いで「文字色を緑に変えて」「持ち色を青に変えて」が1発で発火すること
    p_follow1 = A.plan("文字色を緑に変えてください。", FD, "sheet", t, ["売上"], cur_sheet="売上", last_scope={"title": True})
    assert p_follow1.fire and p_follow1.ops == [{"shelf": "format", "color": "緑", "title": True}], (p_follow1.ops, p_follow1.reasons)
    p_follow2 = A.plan("持ち色を青に変えてください。", FD, "sheet", t, ["売上"], cur_sheet="売上", last_scope={"range": "A1:G1"})
    assert p_follow2.fire and p_follow2.ops == [{"shelf": "format", "color": "青", "range": "A1:G1"}], (p_follow2.ops, p_follow2.reasons)

    # 2文構成で1文目が指定不足のとき、2文目の補足（色・サイズ等）を合流して1発で発火すること
    p_split1 = plan("タイトルの文字の色を変えてください。赤にしてください。", table=t)
    assert p_split1.fire and p_split1.ops == [{"shelf": "format", "title": True, "color": "赤"}], (p_split1.ops, p_split1.reasons)
    p_split2 = plan("見出しの背景の色を変えてください。薄い青にしてください。", table=t)
    assert p_split2.fire and p_split2.ops == [{"shelf": "format", "header": True, "bg": "薄青"}], (p_split2.ops, p_split2.reasons)
    p_split3 = plan("タイトルの文字サイズを変えてください。16ptにしてください。", table=t)
    assert p_split3.fire and p_split3.ops == [{"shelf": "format", "title": True, "size": 16}], (p_split3.ops, p_split3.reasons)

    # range に 'シート名'!A1:G1 が渡されたときに sheet と range に自動分離されること
    normed = gw.CATALOG.normalize_op({"shelf": "format", "range": "'GASマネージャー速度検証_部門別売上表'!A1:G1", "color": "#0000FF"})
    assert normed == {"shelf": "format", "sheet": "GASマネージャー速度検証_部門別売上表", "range": "A1:G1", "color": "#0000FF"}


def test_browser_selection_scope_and_pronouns():
    # 1. 範囲選択中 (B3:D10)
    sc_rng = A.parse_selection_scope("B3:D10")
    assert sc_rng["range"] == "B3:D10" and sc_rng["cols"] == ["B", "C", "D"] and sc_rng["from_browser"] is True

    p1 = A.plan("文字色を赤にして", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rng)
    assert p1.fire and p1.ops == [{"shelf": "format", "color": "赤", "range": "B3:D10"}], p1.ops

    p2 = A.plan("ここにチェックボックスを入れて", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rng)
    assert p2.fire and p2.ops == [{"shelf": "checkbox", "range": "B3:D10", "ok": True}], p2.ops

    p2_bare = A.plan("チェックボックスを入れて", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rng)
    assert p2_bare.fire and p2_bare.ops == [{"shelf": "checkbox", "range": "B3:D10", "ok": True}], p2_bare.ops

    p3 = A.plan("選択範囲の書式を消して", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rng)
    assert p3.fire and p3.ops == [{"shelf": "clear.format", "range": "B3:D10"}], p3.ops

    # 2. 単一セル選択中 (C5)
    sc_cell = A.parse_selection_scope("C5")
    assert sc_cell["cell"] == "C5" and sc_cell["range"] == "C5" and sc_cell["col"] == "C"

    p4 = A.plan("ここに『確定』を入れて", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_cell)
    assert p4.fire and p4.ops == [{"shelf": "write", "cells": {"C5": "確定"}}], (p4.ops, p4.reasons, p4.missing)

    p5 = A.plan("ここの値を『完了』に書き換えて", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_cell)
    assert p5.fire and p5.ops == [{"shelf": "write", "cells": {"C5": "完了"}}], p5.ops

    # 単一セル (A1) にカーソルがあるだけでも「1行おきに色を付けて」は表全体（rangeなし）で動くこと
    sc_a1 = A.parse_selection_scope("A1")
    p6 = A.plan("1行おきに色を付けて", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_a1)
    assert p6.fire and p6.ops == [{"shelf": "banding.add"}], p6.ops

    # 別の場所を明示したとき（「タイトルを太字にして」）はブラウザ選択範囲に上書きされないこと
    p7 = A.plan("タイトルを太字にして", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rng)
    assert p7.fire and p7.ops == [{"shelf": "format", "bold": True, "title": True}], p7.ops

    # 3. 行選択 (4:6) / 列選択 (C:D)
    sc_rows = A.parse_selection_scope("4:6")
    p8 = A.plan("この行を消して", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_rows)
    assert p8.fire and p8.ops == [{"shelf": "rows.delete", "rows": [4, 5, 6], "ok": True}], p8.ops

    sc_cols = A.parse_selection_scope("C:D")
    p9 = A.plan("この列を隠して", FD, "sheet", URIAGE, ["売上"], cur_sheet="売上", last_scope=sc_cols)
    assert p9.fire and p9.ops == [{"shelf": "cols.hide", "cols": ["C", "D"]}], p9.ops


A_WS = ("ws_do", "ws_look", "ws_find", "ws_undo")
