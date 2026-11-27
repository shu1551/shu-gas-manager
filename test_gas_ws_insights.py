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
    assert p.choices[0]["ops"][0]["shelf"] == "seiri"


def test_diagnose_workbook_8_types_and_verify_and_diff():
    payload = [
        {
            "sheet": "受注",
            "table": {
                "header_row": 1,
                "first_col": "A",
                "last_col": "E",
                "data": "2-4",
                "total_row": 5,
                "columns": [
                    {"col": "A", "name": "顧客名", "number": False},
                    {"col": "B", "name": "数量", "number": True},
                    {"col": "C", "name": "単価", "number": True},
                    {"col": "D", "name": "金額", "number": True},
                    {"col": "E", "name": "備考", "number": False},
                ],
            },
            "values": [
                ["顧客名", "数量", "単価", "金額", "備考"],
                ["青葉物産 ", 2, 1000, 2000, "10%引き"],
                ["北斗工業", 3, 2000, 5000, ""],
                ["北斗工業", 1, 1000, 1000, "キャンセル"],
                ["合計", 6, "", 8000, ""],
            ],
            "formulas": [
                [""] * 5,
                [""] * 5,
                [""] * 5,
                [""] * 5,
                ["", "=SUM(B2:B4)", "", "=SUM(D2:D4)", ""],
            ],
            "side": [],
        },
        {
            "sheet": "集計",
            "table": None,
            "values": [["#REF!"]],
            "formulas": [["=存在しないシート!A1"]],
            "side": [],
        },
    ]
    findings = I.diagnose_workbook(payload)
    tags = {f["tag"] for f in findings}
    assert "cross_sheet_ref" in tags
    assert "calc_mismatch" in tags
    assert "note_contradiction" in tags
    assert "status_in_total" in tags
    assert "key_whitespace_split" in tags

    # 検算
    ver = I.verify_after_do(payload[0]["table"], payload[0]["values"], payload[0]["formulas"])
    assert ver["ok"] is True
    assert any("D5 = 8,000" in c for c in ver["checks"])

    # 差分
    diffs = I.diff_cell_values({(3, 4): "5,000"}, {(3, 4): "6,000"})
    assert diffs == ["D3: 5,000 → 6,000"]


def test_cross_sheet_diagnosis_and_planner_fixes():
    import gas_ws_ask as A
    import gas_ws_find as F

    # 1. 他シートの壊れ（SUMIF照合ずれで0、社員表不在、月列空欄、期間ずれ）
    payload = [
        {
            "sheet": "経費",
            "table": {
                "header_row": 1,
                "first_col": "A",
                "last_col": "D",
                "data": "2-3",
                "columns": [
                    {"col": "A", "name": "申請日", "number": False},
                    {"col": "B", "name": "申請者", "number": False},
                    {"col": "C", "name": "部署", "number": False},
                    {"col": "D", "name": "金額", "number": True},
                ],
            },
            "values": [
                ["申請日", "申請者", "部署", "金額"],
                ["2026/11/01", "佐藤", "開発部", 5000],
                ["2026/10/30", "中村", "営業部", 3000],
            ],
            "formulas": [[""] * 4] * 3,
            "side": [],
        },
        {
            "sheet": "社員",
            "table": {
                "header_row": 1,
                "first_col": "A",
                "last_col": "B",
                "data": "2-2",
                "columns": [
                    {"col": "A", "name": "社員番号", "number": False},
                    {"col": "B", "name": "氏名", "number": False},
                ],
            },
            "values": [["社員番号", "氏名"], ["E001", "佐藤"]],
            "formulas": [[""] * 2] * 2,
            "side": [],
        },
        {
            "sheet": "予算",
            "table": {
                "header_row": 1,
                "first_col": "A",
                "last_col": "D",
                "data": "2-3",
                "columns": [
                    {"col": "A", "name": "部署", "number": False},
                    {"col": "B", "name": "4月", "number": True},
                    {"col": "C", "name": "12月", "number": True},
                    {"col": "D", "name": "実績", "number": True},
                ],
            },
            "values": [
                ["部署", "4月", "12月", "実績"],
                ["開発", 10000, "", 0],
                ["営業部", 20000, "", 3000],
            ],
            "formulas": [
                ["", "", "", ""],
                ["", "", "", "=SUMIF(経費!C:C,A2,経費!D:D)"],
                ["", "", "", "=SUMIF(経費!C:C,A3,経費!D:D)"],
            ],
            "side": [],
        },
    ]
    findings = I.diagnose_workbook(payload)
    texts = "\n".join(f["text"] for f in findings)
    assert "表記がずれています" in texts
    assert "登録のない人がいます" in texts
    assert "空欄です" in texts
    assert "対象月の範囲がずれています" in texts

    # 2. 全体系 seiri で列名部分一致しない
    tb_emp = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "F",
        "data": "2-7",
        "columns": [{"col": "A", "name": "社員番号"}, {"col": "B", "name": "氏名"}],
    }
    p_s = A.plan("社員の表をきれいにして", F.Finder(), "sheet", tb_emp)
    assert p_s.choices and p_s.choices[0]["ops"][0]["shelf"] == "seiri"

    # 3. 2列揃っているときは summary せず chart.new（年計と実績を並べるケースも含む）
    tb_bud = {
        "header_row": 1,
        "first_col": "A",
        "last_col": "I",
        "data": "3-6",
        "columns": [
            {"col": "A", "name": "部署"},
            {"col": "H", "name": "年計", "number": True},
            {"col": "I", "name": "実績", "number": True},
        ],
    }
    p_c = A.plan("部署ごとの予算と実績を棒グラフで並べて", F.Finder(), "sheet", tb_bud)
    assert p_c.fire
    assert all(o["shelf"] != "summary" for o in p_c.ops)
    assert p_c.ops[0]["shelf"] == "chart.new"

    # 4. 「見て」「チェックして」は読むだけ
    p_ro1 = A.plan("社員番号が重複していないか見て", F.Finder(), "sheet", tb_emp)
    assert not p_ro1.fire and p_ro1.read_only
    p_ro2 = A.plan("この表、提出前にチェックして", F.Finder(), "sheet", tb_emp)
    assert not p_ro2.fire and p_ro2.read_only

    # 5. 日付1日ずれ検算
    ver_d = I.verify_after_do(
        tb_emp,
        [["社員番号", "入社日"], ["E001", "2022/03/31"]],
        ops=[{"shelf": "date.fix"}],
        before_map={(2, 2): "2022/04/01"},
        after_map={(2, 2): "2022/03/31"},
    )
    assert not ver_d["ok"] and any("ずれています" in m for m in ver_d["mismatch"])

    # 6. 2段見出しで「予算と実績を並べて」が 1行目始まりの複数列 chart.new になること
    tb_2row = {
        "header_row": 1,
        "header_rows": 2,
        "first_col": "A",
        "last_col": "I",
        "data": "3-6",
        "columns": [
            {"col": "A", "name": "部署"},
            {"col": "G", "name": "下期・12月", "number": True},
            {"col": "H", "name": "年計", "number": True},
            {"col": "I", "name": "実績", "number": True},
        ],
    }
    p_2c = A.plan("部署ごとの予算と実績を棒グラフで並べて", F.Finder(), "sheet", tb_2row)
    assert p_2c.fire and p_2c.ops == [{"shelf": "chart.new", "type": "column", "range": "A1:A6,H1:I6"}]

    # 7. filter.where の「承認待ち」復元 と write セル番地優先
    tb_exp = {"header_row": 1, "first_col": "A", "last_col": "H", "data": "3-15", "columns": [{"col": "G", "name": "承認"}]}
    p_fw = A.plan("承認待ちの行だけ表示して", F.Finder(), "sheet", tb_exp)
    assert p_fw.fire and p_fw.ops[0]["equals"] == "承認待ち"

    p_wr = A.plan("社員のD2を2022/04/01にして", F.Finder(), "sheet", tb_emp)
    assert p_wr.fire and p_wr.ops[0]["shelf"] == "write" and p_wr.ops[0]["cells"] == {"D2": "2022/04/01"}
