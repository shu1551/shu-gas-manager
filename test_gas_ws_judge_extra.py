# -*- coding: utf-8 -*-
import gas_ws_judge as J


def _snap(cells=None, name="Sheet1", frozen=None, hidden_rows=None, hidden_cols=None, cf=0, side=None, named=None, extra_sheets=None):
    sh = {
        "name": name,
        "index": 0,
        "rows": 20,
        "cols": 10,
        "frozen": frozen or {"rows": 0, "cols": 0},
        "merges": [],
        "hidden_rows": hidden_rows or [],
        "filtered_rows": [],
        "hidden_cols": hidden_cols or [],
        "cells": cells or {},
        "cf": cf,
        "side": side or {"filter": None, "cf_rules": [], "protected": [], "charts": [], "banded": [], "validations": {}},
    }
    sheets = [sh] + (extra_sheets or [])
    return {"name": "Book", "sheets": sheets, "named": named or []}


def _base_cells():
    return {
        "A1": {"v": "No", "t": "s"},
        "B1": {"v": "金額", "t": "s"},
        "A2": {"v": "1", "t": "n", "n": 1},
        "B2": {"v": "100", "t": "n", "n": 100},
        "A3": {"v": "2", "t": "n", "n": 2},
        "B3": {"v": "200", "t": "n", "n": 200},
    }


def test_judge_tail_formula():
    c_ok = _base_cells()
    c_ok["A4"] = {"v": "合計", "t": "s"}
    c_ok["B4"] = {"v": "300", "t": "n", "n": 300, "f": "=SUM(B2:B3)"}
    b = _snap(_base_cells())
    assert J.check_condition({"末尾が式": {"列": "金額"}}, b, _snap(c_ok))[0] is True
    assert J.check_condition({"末尾が式": {"列": "金額"}}, b, b)[0] is False


def test_judge_no_blank_rows():
    c_ok = _base_cells()
    c_ng = _base_cells()
    c_ng["A4"] = {"v": "3", "t": "n", "n": 3}  # 3行目が空で4行目にデータがあるケースを作れないので3行目を消す
    del c_ng["A3"], c_ng["B3"]
    assert J.check_condition({"空白行なし": True}, None, _snap(c_ok))[0] is True
    assert J.check_condition({"空白行なし": True}, None, _snap(c_ng))[0] is False


def test_judge_no_duplicates():
    c_ok = _base_cells()
    c_ng = _base_cells()
    c_ng["A4"] = {"v": "1", "t": "n", "n": 1}
    c_ng["B4"] = {"v": "100", "t": "n", "n": 100}
    assert J.check_condition({"重複なし": True}, None, _snap(c_ok))[0] is True
    assert J.check_condition({"重複なし": True}, None, _snap(c_ng))[0] is False


def test_judge_renumber():
    c_ok = _base_cells()
    c_ng = _base_cells()
    c_ng["A3"] = {"v": "5", "t": "n", "n": 5}
    assert J.check_condition({"連番": {"列": "No", "開始": 1}}, None, _snap(c_ok))[0] is True
    assert J.check_condition({"連番": {"列": "No", "開始": 1}}, None, _snap(c_ng))[0] is False


def test_judge_row_col_counts_and_empty_range():
    b = _snap(_base_cells())
    c_less = {"A1": {"v": "No", "t": "s"}, "B1": {"v": "金額", "t": "s"}, "A2": {"v": "1", "t": "n", "n": 1}, "B2": {"v": "100", "t": "n", "n": 100}}
    a_less = _snap(c_less)
    assert J.check_condition({"行数": {"減った": 1}}, b, a_less)[0] is True
    assert J.check_condition({"行数": {"減った": 2}}, b, a_less)[0] is False

    c_wide = _base_cells()
    c_wide["C1"] = {"v": "備考", "t": "s"}
    assert J.check_condition({"列数": {"増えた": 1}}, b, _snap(c_wide))[0] is True
    assert J.check_condition({"列数": {"増えた": 2}}, b, _snap(c_wide))[0] is False

    assert J.check_condition({"空範囲": "C2:C3"}, b, b)[0] is True
    assert J.check_condition({"空範囲": "B2:B3"}, b, b)[0] is False


def test_judge_tidy_ready():
    c_ok = _base_cells()
    c_ng = _base_cells()
    c_ng["A2"] = {"v": " １ ", "t": "s"}
    assert J.check_condition({"整え済み": True}, None, _snap(c_ok))[0] is True
    assert J.check_condition({"整え済み": True}, None, _snap(c_ng))[0] is False


def test_judge_sheets_and_side_items():
    s2 = {"name": "集計", "index": 1, "rows": 5, "cols": 5, "frozen": {"rows": 0, "cols": 0}, "merges": [], "hidden_rows": [], "filtered_rows": [], "hidden_cols": [], "cells": {}, "cf": 0, "side": {}}
    a = _snap(
        _base_cells(),
        frozen={"rows": 1, "cols": 1},
        hidden_rows=[3],
        hidden_cols=[4],
        cf=1,
        side={
            "filter": {"range": "A1:B3"},
            "cf_rules": [{"ranges": ["B2:B3"]}],
            "protected": [{"range": "B2:B3"}],
            "charts": [{"title": "売上", "type": "COLUMN"}],
            "banded": ["A1:B3"],
            "validations": {"B2": {"type": "ONE_OF_LIST"}},
        },
        named=[{"name": "現在庫", "range": "B2:B3"}],
        extra_sheets=[s2],
    )
    b = _snap(_base_cells())

    assert J.check_condition({"シートあり": "集計"}, b, a)[0] is True
    assert J.check_condition({"シートあり": "無い"}, b, a)[0] is False
    assert J.check_condition({"シートの並び": ["Sheet1", "集計"]}, b, a)[0] is True
    assert J.check_condition({"シートの並び": ["集計", "Sheet1"]}, b, a)[0] is False
    assert J.check_condition({"固定": {"行": 1, "列": 1}}, b, a)[0] is True
    assert J.check_condition({"固定": {"行": 2}}, b, a)[0] is False
    assert J.check_condition({"入力規則あり": True}, b, a)[0] is True
    assert J.check_condition({"入力規則あり": True}, b, b)[0] is False
    assert J.check_condition({"条件付き書式あり": True}, b, a)[0] is True
    assert J.check_condition({"条件付き書式あり": True}, b, b)[0] is False
    assert J.check_condition({"交互の色あり": True}, b, a)[0] is True
    assert J.check_condition({"交互の色あり": True}, b, b)[0] is False
    assert J.check_condition({"フィルタあり": True}, b, a)[0] is True
    assert J.check_condition({"フィルタあり": True}, b, b)[0] is False
    assert J.check_condition({"保護あり": True}, b, a)[0] is True
    assert J.check_condition({"保護あり": True}, b, b)[0] is False
    assert J.check_condition({"名前付き範囲あり": "現在庫"}, b, a)[0] is True
    assert J.check_condition({"名前付き範囲あり": "別名"}, b, a)[0] is False
    assert J.check_condition({"隠し行": [3]}, b, a)[0] is True
    assert J.check_condition({"隠し行": [2]}, b, a)[0] is False
    assert J.check_condition({"隠し列": ["D"]}, b, a)[0] is True
    assert J.check_condition({"隠し列": ["C"]}, b, a)[0] is False
    assert J.check_condition({"グラフあり": {"種類": "縦棒", "題": "売上"}}, b, a)[0] is True
    assert J.check_condition({"グラフあり": {"種類": "円"}}, b, a)[0] is False


def test_judge_askback_and_refuse():
    b = _snap(_base_cells())
    c_mod = _base_cells()
    c_mod["A2"]["v"] = "999"
    a_mod = _snap(c_mod)
    assert J.check_condition({"聞き返した": True}, b, b, {"ops": []})[0] is True
    assert J.check_condition({"聞き返した": True}, b, a_mod, {"ops": [{"shelf": "seiri"}]})[0] is False
    assert J.check_condition({"断った": True}, b, b, {"ops": []})[0] is True
    assert J.check_condition({"断った": True}, b, a_mod, {"ops": [{"shelf": "seiri"}]})[0] is False
