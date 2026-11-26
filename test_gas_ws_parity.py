# -*- coding: utf-8 -*-
"""Python (gas_ws_find / gas_ws_ask / gas_ws_direct) と JS (combo_planner_template.js / combo_sidebar_template.html) のパリティ検証。"""

import json
import re
import subprocess
from pathlib import Path

import pytest

import gas_ws_ask as A
import gas_ws_combo as C
import gas_ws_direct as D
import gas_ws_find as F

HERE = Path(__file__).resolve().parent
NODE_AVAILABLE = subprocess.run(["node", "--version"], capture_output=True).returncode == 0
needs_node = pytest.mark.skipif(not NODE_AVAILABLE, reason="Node.js が必要です")

SAMPLE_TABLE = {
    "header_row": 1,
    "first_col": "A",
    "last_col": "E",
    "data": "2-20",
    "title_a1": "A1",
    "columns": [
        {"col": "A", "name": "部署"},
        {"col": "B", "name": "社員番号"},
        {"col": "C", "name": "氏名"},
        {"col": "D", "name": "日付"},
        {"col": "E", "name": "金額"},
    ],
}

PARITY_SHEET_ASKS = [
    "タイトルの色を赤に変えてください",
    "タイトルの本当の色を青に変えてください",
    "タイトルの持ちの色を赤に変えてください",
    "見出しを太字にして背景を青にして",
    "金額の列を桁区切りにして",
    "日付の表示形式を曜日付きにする",
    "表示形式を数値(標準)にする",
    "A1の背景色を消して",
    "A列の幅を広げて",
    "列幅を中身に合わせて自動調整して",
    "1行目を固定して",
    "行の固定を解除して",
    "表にフィルタを設定して",
    "フィルタを解除して",
    "金額の大きい順に並べ替えて",
    "部署ごと、同部署内は社員番号の昇順に並べ替え",
    "部署ごとにかためて並べてもらって、同じ部署の中は社員番号の若い順でお願いします",
    "部署が変わる行の下に区切り線を引いて",
    "日付の文字列を日付に変換する",
    "重複を黄色で印",
    "重複した行を削除して",
    "表に交互の色を付けて",
    "1行おきのしましまを消して",
    "B2:E10に罫線を引いて",
    "グリッド線を非表示にして",
    "シート一覧を教えて",
    "他のシートがあるか確認したい",
    "全シートの目次シートを作って",
    "集計用のシートを追加して",
    "シート1の名前を売上に変更して",
    "売上シートを複製して",
    "売上シートを隠して",
    "隠してある売上シートを再表示して",
    "売上シートのタブを赤色に変えて",
    "3行目を削除して",
    "5行目の上に2行挿入して",
    "B列を非表示にして",
    "B5に「確認済み」とメモを付けて",
    "B5のメモを消して",
    "金額列をマイナス赤字の表示にして",
    "シート全体のフォントをメイリオに統一して",
    "金額の合計を表の一番下に出して",
]

PARITY_DOC_ASKS = [
    "見出し一覧を見せて",
    "先頭に目次を入れて",
    "「山田」を「山田（総務）」に置換して",
    "ページ番号を入れて",
    "行間を1.5にして",
]


def _run_js_planner(cases):
    cat_data = C.build_combo_catalog_data()
    planner_src = (HERE / "combo_planner_template.js").read_text(encoding="utf-8")
    phrases_json = json.dumps(C.load_combo_phrases(), ensure_ascii=False)
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = vm.createContext({
  COMBO_CATALOG_DATA: payload.cat,
  COMBO_PHRASES: payload.phrases,
  console, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Date
});
vm.runInContext(payload.planner, ctx);
const out = payload.cases.map(item => {
  const found = ctx.ComboPlanner.find(item.ask, item.kind);
  const planned = ctx.ComboPlanner.plan(item.ask, item.kind, item.table, item.sheets, item.curSheet);
  return {
    ask: item.ask,
    top: found.picks.length ? found.picks[0].name : '',
    fire: !!planned.fire,
    opShelves: (planned.ops || []).map(o => o.shelf)
  };
});
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps(
            {"cat": cat_data, "phrases": json.loads(phrases_json), "planner": planner_src, "cases": cases},
            ensure_ascii=False,
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}"
    return json.loads(proc.stdout.strip())


def test_shared_defs_parity_between_python_and_js():
    """ws_shared_defs.json / gas_ws_direct.py / combo_sidebar_template.html の色・定数定義が一致すること。"""
    defs = json.loads((HERE / "ws_shared_defs.json").read_text(encoding="utf-8"))
    assert D.COLOR_MAP == defs["color_map"]
    assert D.NONE_WORDS == set(defs["none_words"])
    assert D.ERR_LABEL == defs["err_label"]

    sidebar = (HERE / "combo_sidebar_template.html").read_text(encoding="utf-8")
    m = re.search(r"var DIRECT_COLOR_MAP\s*=\s*(\{[\s\S]*?\});", sidebar)
    assert m, "DIRECT_COLOR_MAP が見つかりません"
    js_cmap = json.loads(m.group(1))
    assert js_cmap == defs["color_map"]

    files = C.build_combo_files(combo_lite=True)
    built_sidebar = next(f["source"] for f in files if f["name"] == "ComboSidebar")
    m2 = re.search(r"var DIRECT_COLOR_MAP\s*=\s*(\{[^;]*\});", built_sidebar)
    assert m2, "ビルド済み ComboSidebar に DIRECT_COLOR_MAP が注入されていません"
    assert json.loads(m2.group(1)) == defs["color_map"]


@needs_node
def test_planner_parity_between_python_and_js():
    """Python (gas_ws_find/ask) と JS (ComboPlanner) が主要47フレーズで同一の1位棚・ops棚を返すこと。"""
    finder = F.Finder()
    cases = [
        {"ask": a, "kind": "sheet", "table": SAMPLE_TABLE, "sheets": ["売上", "集計"], "curSheet": "売上"}
        for a in PARITY_SHEET_ASKS
    ] + [
        {"ask": a, "kind": "doc", "table": None, "sheets": [], "curSheet": ""}
        for a in PARITY_DOC_ASKS
    ]
    js_results = _run_js_planner(cases)
    for item, js_r in zip(cases, js_results):
        py_picks, _, _ = finder.find(item["ask"], item["kind"])
        py_top = py_picks[0]["name"] if py_picks else ""
        assert js_r["top"] == py_top, f"[{item['ask']}] 1位棚不一致: py={py_top} vs js={js_r['top']}"

        py_plan = A.plan(item["ask"], finder, item["kind"], item["table"], item["sheets"], item["curSheet"])
        py_op_shelves = [o.get("shelf") for o in py_plan.ops]
        assert js_r["opShelves"] == py_op_shelves, (
            f"[{item['ask']}] ops棚不一致: py={py_op_shelves} vs js={js_r['opShelves']}"
        )
        assert js_r["fire"] == py_plan.fire, (
            f"[{item['ask']}] fire判定不一致: py={py_plan.fire}({py_plan.reasons}/{py_plan.missing}) vs js={js_r['fire']}"
        )
