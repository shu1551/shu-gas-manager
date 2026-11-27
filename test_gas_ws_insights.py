# -*- coding: utf-8 -*-
"""gas_ws_insights・書式重複スキップ・曖昧空白確認のユニットテスト。"""

import gas_ws_direct as D
import gas_ws_insights as I


def test_insight_type1_calc_col_and_type2_discount_and_type4_sum():
    tb = {
        "header_row": 3,
        "first_col": "A",
        "last_col": "I",
        "data": "4-6",
        "total_row": 7,
        "columns": [
            {"col": "A", "name": "日付", "number": False},
            {"col": "E", "name": "数量", "number": True},
            {"col": "F", "name": "単価", "number": True},
            {"col": "G", "name": "売上金額", "number": True},
            {"col": "I", "name": "備考", "number": False},
        ],
    }
    vals = [
        ["売上明細", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", ""],
        ["日付", "部門", "担当", "商品", "数量", "単価", "売上金額", "進捗率", "備考"],
        ["2026/11/01", "第一", "佐藤", "A", 5, 1000, 5000, 1.0, ""],
        ["2026/11/02", "第二", "鈴木", "B", 4, 2000, 8000, 0.25, "値引あり"],
        ["2026/11/03", "第一", "高橋", "C", 3, 3000, 9000, 1.0, ""],
        ["合計", "", "", "", 12, "", 22000, "", ""],
    ]
    forms = [
        [""] * 9,
        [""] * 9,
        [""] * 9,
        [""] * 9,
        [""] * 9,
        [""] * 9,
        ["", "", "", "", "=SUM(E4:E6)", "", "=SUM(G4:G6)", "", ""],
    ]
    ins = I.analyze_table_insights(tb, vals, forms, side=["フィルタ: A3:I6"], max_items=5)
    joined = "\n".join(ins)
    assert "SUBTOTAL" in joined
    assert "数式ではなく値で入っています" in joined
    assert "値引あり" in joined


def test_insight_type6_email_phone_date_and_type7_months():
    tb_roster = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "D",
        "data": "2-3",
        "total_row": None,
        "columns": [
            {"col": "A", "name": "氏名", "number": False},
            {"col": "B", "name": "電話番号", "number": False},
            {"col": "C", "name": "入社日", "number": False},
            {"col": "D", "name": "メール", "number": False},
        ],
    }
    vals_r = [
        ["氏名", "電話番号", "入社日", "メール"],
        ["佐藤 一郎", "090-1111-2222", "2021/04/01", "sato@example.com"],
        ["渡辺 さくら", "090 9999 0000", "R5.4.1", "watanabe@example"],
    ]
    ins_r = I.analyze_table_insights(tb_roster, vals_r, max_items=5)
    joined_r = "\n".join(ins_r)
    assert "メールアドレス" in joined_r
    assert "書式が不揃いな番号" in joined_r
    assert "日付表記の揺れ" in joined_r

    tb_month = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "G",
        "data": "2-3",
        "total_row": None,
        "columns": [
            {"col": "A", "name": "部門", "number": False},
            {"col": "B", "name": "上期・4月", "number": True},
            {"col": "C", "name": "上期・5月", "number": True},
            {"col": "D", "name": "上期・6月", "number": True},
            {"col": "E", "name": "下期・10月", "number": True},
            {"col": "F", "name": "下期・11月", "number": True},
            {"col": "G", "name": "下期・12月", "number": True},
        ],
    }
    vals_m = [
        ["部門", "4月", "5月", "6月", "10月", "11月", "12月"],
        ["第一", 100, 200, 300, 400, 500, 600],
        ["第二", 110, 210, 310, 410, 510, 610],
    ]
    ins_m = I.analyze_table_insights(tb_month, vals_m, max_items=3)
    assert any("他の月が欠けています" in x for x in ins_m)


def test_format_already_applied():
    ent = {
        "cells": {
            (3, 1): {
                "effectiveFormat": {
                    "backgroundColorStyle": {"rgbColor": {"red": 0.12, "green": 0.31, "blue": 0.47}},
                    "textFormat": {
                        "bold": True,
                        "foregroundColorStyle": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
            (3, 2): {
                "effectiveFormat": {
                    "backgroundColorStyle": {"rgbColor": {"red": 0.12, "green": 0.31, "blue": 0.47}},
                    "textFormat": {
                        "bold": True,
                        "foregroundColorStyle": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
        }
    }
    op = {"shelf": "format", "header": True, "bg": "濃青", "color": "白", "bold": True, "align": "center"}
    assert D.DirectRunner._format_already_applied(ent, 3, 1, 3, 2, op, False) is True
    op_diff = {"shelf": "format", "header": True, "bg": "赤"}
    assert D.DirectRunner._format_already_applied(ent, 3, 1, 3, 2, op_diff, False) is False


def test_trim_and_zen_separated_and_ops_filter():
    tb = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "C",
        "data": "2-3",
        "total_row": None,
        "columns": [
            {"col": "A", "name": "顧客名", "number": False},
            {"col": "B", "name": "金額", "number": True},
            {"col": "C", "name": "状態", "number": False},
        ],
    }
    vals = [
        ["顧客名", "金額", "状態"],
        ["青葉物産 ", 90000, "キャンセル"],
        ["北斗工業", 30000, "確定"],
    ]
    # ws_look (opsなし): 空白のみ（全角数字とは言わない）、キャンセルも出る
    ins_look = I.analyze_table_insights(tb, vals, max_items=5)
    j = "\n".join(ins_look)
    assert "前後の空白が含まれています" in j
    assert "全角数字" not in j
    assert "キャンセル" in j

    # ws_do (cf.add のみ): 無関係な雑音は出さない
    ins_cf = I.analyze_table_insights(tb, vals, ops=[{"shelf": "cf.add"}], max_items=5)
    assert ins_cf == []


def test_ambiguous_tidy_with_sheet_name_like_col():
    import gas_ws_ask as A
    import gas_ws_find as F

    tb = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "F",
        "data": "2-9",
        "columns": [{"col": "A", "name": "顧客コード"}, {"col": "B", "name": "会社名"}],
    }
    p = A.plan("顧客の表を整えて", F.Finder(), "sheet", tb)
    assert not p.fire
    assert len(p.choices) == 3
    assert p.choices[0]["ops"] == [{"shelf": "tidy"}]
