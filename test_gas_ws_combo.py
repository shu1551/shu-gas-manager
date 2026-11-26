# -*- coding: utf-8 -*-
"""
test_gas_ws_combo.py - GASコンボ（GASネイティブ版）オフライン単体・統合テスト

以下を検証する（通信なし）:
1. build_combo_files() による 5 ファイル生成、HTML/JS インライン展開、openTarget_ パッチ、HARDCODE_FILES 不変
2. Node.js 上での ComboPlanner.plan と Python gas_ws_ask.plan の対等比較（35問以上）
3. Node.js vm モック環境での ComboServer（comboInit / comboLook / comboFind / comboRunAsk / comboRunOps / comboUndo / 郵便受け）
4. install_combo / gas.py CLI / gas_mcp_server.gas("combo ...") の統合ルーティング
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import gas_mcp_server
import gas_workspace as gw
import gas_ws_ask as A
import gas_ws_catalog as cat_mod
import gas_ws_combo as combo_mod
from gas_client import GasClient

HERE = Path(__file__).resolve().parent

URIAGE = {
    "header_row": 1,
    "first_col": "A",
    "last_col": "G",
    "data": "2-21",
    "total_row": 22,
    "columns": [
        {"col": c, "name": n, "number": (c in "EFG")}
        for c, n in zip("ABCDEFG", ["日付", "伝票番号", "得意先", "品名", "数量", "単価", "金額"])
    ],
}

TITLE_TABLE = {
    "header_row": 3,
    "first_col": "A",
    "last_col": "G",
    "data": "4-8",
    "total_row": 9,
    "columns": [
        {"col": c, "name": n, "number": (c in "DEFG")}
        for c, n in zip("ABCDEFG", ["部門", "担当者", "品目", "1月", "2月", "3月", "合計"])
    ],
}


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


needs_node = pytest.mark.skipif(not _node_ok(), reason="node が無い")


def _run_node_json(js_script, payload):
    proc = subprocess.run(
        ["node", "-e", js_script],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


# ---------------------------------------------------------------- 1. バンドル生成・インライン展開・構文検査


def test_build_combo_files_structure_and_inlining():
    files = combo_mod.build_combo_files(target_ss_id="TEST_SS_12345")
    assert [f["name"] for f in files] == ["appsscript", "Engine", "ComboPlanner", "ComboServer", "ComboSidebar"]
    assert [f["type"] for f in files] == ["JSON", "SERVER_JS", "SERVER_JS", "SERVER_JS", "HTML"]

    by_name = {f["name"]: f for f in files}

    # appsscript manifest (既定は enabledAdvancedServices なしで V8 Isolate 起動高速化)
    manifest = json.loads(by_name["appsscript"]["source"])
    assert manifest["runtimeVersion"] == "V8"
    assert manifest["timeZone"] == "Asia/Tokyo"
    assert manifest["webapp"] == {"executeAs": "USER_DEPLOYING", "access": "MYSELF"}
    assert manifest["dependencies"] == {}
    for scope in (
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/script.container.ui",
        "https://www.googleapis.com/auth/script.external_request",
    ):
        assert scope in manifest["oauthScopes"]

    # Engine: openTarget_ のみメモリ上でパッチされ、Sheets ガードも注入されていること
    eng_src = by_name["Engine"]["source"]
    assert "SpreadsheetApp.getActiveSpreadsheet()" in eng_src
    assert "comboOpenSs_" in eng_src
    assert "typeof Sheets === 'undefined'" in eng_src
    assert f"var ENGINE_VERSION = '{gw.WorkspaceManager(state_path=None).engine_version()}';" in eng_src
    orig_engine = (HERE / "workspace_engine.gs").read_text(encoding="utf-8")
    assert "comboOpenSs_" not in orig_engine

    # ComboPlanner: COMBO_CATALOG_JSON 遅延初期化 + ComboPlanner が定義されている
    planner_src = by_name["ComboPlanner"]["source"]
    assert planner_src.startswith("var COMBO_CATALOG_JSON = ")
    assert "COMBO_CATALOG_DATA" in planner_src
    assert "var ComboPlanner = (function ()" in planner_src

    # ComboServer: DEFAULT_TARGET_SS_ID が差し込まれている
    server_src = by_name["ComboServer"]["source"]
    assert 'var DEFAULT_TARGET_SS_ID = "TEST_SS_12345";' in server_src

    # ComboSidebar: プレースホルダーがインライン展開され、元のプレースホルダー文字列が残っていない
    html_src = by_name["ComboSidebar"]["source"]
    assert "/*__COMBO_CATALOG_DATA__*/" not in html_src
    assert "/*__COMBO_PLANNER_JS__*/" not in html_src
    assert "var COMBO_CATALOG_DATA = " in html_src
    assert "var ComboPlanner = (function ()" in html_src
    assert 'id="askInput"' in html_src
    assert 'id="btnUndo"' in html_src
    assert "google.script.run" in html_src

    # HARDCODE_FILES が汚れていないこと
    assert cat_mod.find_hardcoded_names(gw.CATALOG) == []


@needs_node
def test_generated_js_and_sidebar_scripts_syntax_valid(tmp_path):
    files = combo_mod.build_combo_files(target_ss_id="SS_SYNTAX")
    by_name = {f["name"]: f["source"] for f in files}

    for name in ("Engine", "ComboPlanner", "ComboServer"):
        p = tmp_path / f"{name}.js"
        p.write_text(by_name[name], encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert proc.returncode == 0, f"{name}.js syntax error: {proc.stderr}"

    # ComboSidebar 内の <script> ブロックもすべて構文エラーがないこと
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", by_name["ComboSidebar"], flags=re.IGNORECASE)
    assert len(scripts) >= 1
    for idx, sc in enumerate(scripts):
        p = tmp_path / f"sidebar_{idx}.js"
        p.write_text(sc, encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert proc.returncode == 0, f"ComboSidebar <script> #{idx} syntax error: {proc.stderr}"


# ---------------------------------------------------------------- 2. Node.js ComboPlanner.plan vs Python gas_ws_ask.plan (35問以上)


@needs_node
def test_combo_planner_parity_with_python_across_35_prompts():
    files = combo_mod.build_combo_files()
    planner_js = next(f["source"] for f in files if f["name"] == "ComboPlanner")

    # Python と完全一致を検証する 34 ケース
    parity_cases = [
        # タイトル色・書式
        ("タイトルの文字の色を赤に変えてください。", TITLE_TABLE, ["部門別売上表"], "部門別売上表", None),
        ("タイトルの文字色を青にして", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字色を緑色に変えて", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字を水色に変えて", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字色を#FF6600にして", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字色をnavyに", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルを白文字で青い背景に", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字の色を赤に、背景を薄い黄色にして", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルを太字にして", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルの文字サイズを16ptにして", TITLE_TABLE, ["売上"], "売上", None),
        ("タイトルを中央揃えにして", TITLE_TABLE, ["売上"], "売上", None),
        ("GASマネージャー速度検証_部門別売上表 シートのタイトル（A1）の文字色を青に変えてください。", TITLE_TABLE, ["GASマネージャー速度検証_部門別売上表", "集計"], "集計", None),
        # 見出し・書式・2文補足
        ("見出しを太字にして青い背景にして", URIAGE, ["売上"], "売上", None),
        ("タイトルの文字の色を変えてください。赤にしてください。", TITLE_TABLE, ["売上"], "売上", None),
        ("見出しの背景の色を変えてください。薄い青にしてください。", TITLE_TABLE, ["売上"], "売上", None),
        # 列幅・固定・縞・整える
        ("列幅を自動調整して", URIAGE, ["売上"], "売上", None),
        ("見出しの行を固定して", URIAGE, ["売上"], "売上", None),
        ("1行おきに色を付けて", URIAGE, ["売上"], "売上", None),
        ("1行おきに色を付けて、売上の棒グラフも作って", URIAGE, ["売上"], "売上", None),
        # 合計行・並べ替え・フィルタ・条件付き書式
        ("合計行を入れて", URIAGE, ["売上"], "売上", None),
        ("金額の大きい順に並べて", URIAGE, ["売上"], "売上", None),
        ("日付の古い順に並べ替えて", URIAGE, ["売上"], "売上", None),
        ("金額が1000以上のセルを黄色くして", URIAGE, ["売上"], "売上", None),
        ("金額が5000以上の行だけ絞り込んで", URIAGE, ["売上"], "売上", None),
        # 行・列操作・書き込み
        ("3行目から5行目を消して", URIAGE, ["売上"], "売上", None),
        ("C列とD列の間に空の列を足して", URIAGE, ["売上"], "売上", None),
        ("A列とB列を入れ替えて", URIAGE, ["売上"], "売上", None),
        ("B2の値を『確定』に書き換えて", URIAGE, ["売上"], "売上", None),
        # 選択範囲・代名詞連動
        ("文字色を赤にして", URIAGE, ["売上"], "売上", A.parse_selection_scope("B3:D10")),
        ("ここにチェックボックスを入れて", URIAGE, ["売上"], "売上", A.parse_selection_scope("B3:D10")),
        ("選択範囲の書式を消して", URIAGE, ["売上"], "売上", A.parse_selection_scope("B3:D10")),
        ("ここに『確定』を入れて", URIAGE, ["売上"], "売上", A.parse_selection_scope("C5")),
        ("この行を消して", URIAGE, ["売上"], "売上", A.parse_selection_scope("4:6")),
        ("この列を隠して", URIAGE, ["売上"], "売上", A.parse_selection_scope("C:D")),
        # 曖昧・棚外（撃たない）
        ("いらない行を消して", URIAGE, ["売上"], "売上", None),
        ("このシートをPDFにしてメールで送って", URIAGE, ["売上"], "売上", None),
    ]

    finder = gw.WorkspaceManager(state_path=None).finder
    py_results = []
    js_inputs = []
    for ask, table, sheets, cur_sheet, scope in parity_cases:
        p = A.plan(ask, finder, "sheet", table, sheets, cur_sheet=cur_sheet, last_scope=scope)
        py_results.append({
            "ask": ask,
            "fire": p.fire,
            "ops": p.ops,
            "missing": p.missing,
        })
        js_inputs.append({
            "ask": ask,
            "kind": "sheet",
            "table": table,
            "sheets": sheets,
            "curSheet": cur_sheet,
            "lastScope": scope,
        })

    node_code = (
        "const vm = require('vm'), fs = require('fs');\n"
        "const data = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "const ctx = vm.createContext({});\n"
        "vm.runInContext(data.plannerJs, ctx);\n"
        "const out = data.cases.map(c => {\n"
        "  const p = ctx.ComboPlanner.plan(c.ask, c.kind, c.table, c.sheets, c.curSheet, c.lastScope);\n"
        "  return { ask: c.ask, fire: !!p.fire, ops: p.ops, missing: p.missing, previewText: p.previewText };\n"
        "});\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    js_results = _run_node_json(node_code, {"plannerJs": planner_js, "cases": js_inputs})
    assert len(js_results) == len(py_results)

    for py_r, js_r in zip(py_results, js_results):
        assert js_r["fire"] == py_r["fire"], f"fire mismatch on {py_r['ask']}: py={py_r} js={js_r}"
        assert js_r["ops"] == py_r["ops"], f"ops mismatch on {py_r['ask']}: py={py_r['ops']} js={js_r['ops']}"
        assert js_r["missing"] == py_r["missing"], f"missing mismatch on {py_r['ask']}: py={py_r['missing']} js={js_r['missing']}"
        if js_r["fire"]:
            assert js_r["previewText"].startswith("棚ヒット: ")
        else:
            assert js_r["previewText"].startswith("未確定: ")


@needs_node
def test_combo_planner_honest_color_and_find_ask():
    """「本当の色」「ほんとの色」「字の色」のタイトル色ヒット＆ComboPlanner.ask を検証。"""
    files = combo_mod.build_combo_files()
    planner_js = next(f["source"] for f in files if f["name"] == "ComboPlanner")

    node_code = (
        "const vm = require('vm'), fs = require('fs');\n"
        "const data = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "const ctx = vm.createContext({});\n"
        "vm.runInContext(data.plannerJs, ctx);\n"
        "const prompts = [\n"
        "  'タイトルの本当の色を赤に変えてください。',\n"
        "  'タイトルの本当の色を青に変えてください。',\n"
        "  'タイトルのほんとの色を緑に変えて',\n"
        "  'タイトルの字の色を#FF0000にして',\n"
        "  'タイトルの文字を赤',\n"
        "  'タイトルの文字を青色に',\n"
        "  'タイトルは青',\n"
        "  'タイトルの色は青。',\n"
        "  'タイトルを赤に'\n"
        "];\n"
        "const plans = prompts.map(a => ctx.ComboPlanner.plan(a, 'sheet', data.table, ['売上'], '売上', null));\n"
        "const asks = [\n"
        "  ctx.ComboPlanner.ask('', 'sheet'),\n"
        "  ctx.ComboPlanner.ask('分類:入力', 'sheet'),\n"
        "  ctx.ComboPlanner.ask('棚:format', 'sheet'),\n"
        "  ctx.ComboPlanner.ask('並べ替え', 'sheet')\n"
        "];\n"
        "process.stdout.write(JSON.stringify({ plans, asks }));\n"
    )
    out = _run_node_json(node_code, {"plannerJs": planner_js, "table": TITLE_TABLE})
    expected_colors = ["赤", "青", "緑", "#FF0000", "赤", "青", "青", "青", "赤"]
    for p, col in zip(out["plans"], expected_colors):
        assert p["fire"] is True, p
        assert p["ops"] == [{"shelf": "format", "title": True, "color": col}], p

    assert "分類:" in out["asks"][0] or "棚" in out["asks"][0]

    # 当たらない頼みに近い候補（消す棚は出さない）→ 覚えたら一発で当たる
    node_sg = (
        "const vm = require('vm'), fs = require('fs');\n"
        "const data = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "const ctx = vm.createContext({});\n"
        "vm.runInContext(data.plannerJs, ctx);\n"
        "const P = ctx.ComboPlanner;\n"
        "const miss = P.plan('表題の字を赤くしといて', 'sheet', data.table, ['売上'], '売上', null);\n"
        "const del = P.plan('いらない行を消して', 'sheet', data.table, ['売上'], '売上', null);\n"
        "P.learn('表題の字を赤くしといて', miss.suggest);\n"
        "const hit = P.plan('表題の字を赤くしといて。', 'sheet', data.table, ['売上'], '売上', null);\n"
        "process.stdout.write(JSON.stringify({ miss, del, hit }));\n"
    )
    sg = _run_node_json(node_sg, {"plannerJs": planner_js, "table": TITLE_TABLE})
    assert sg["miss"]["fire"] is False
    assert sg["miss"]["suggest"] == [{"shelf": "format", "title": True, "color": "赤"}]
    assert not sg["del"].get("suggest")
    assert sg["hit"]["fire"] is True and sg["hit"]["learned"] is True
    assert sg["hit"]["ops"] == sg["miss"]["suggest"]
    assert "validation.list" in out["asks"][1]
    assert "format" in out["asks"][2]
    assert "sort" in out["asks"][3]


# ---------------------------------------------------------------- 3. ComboServer VM モック結合テスト


@needs_node
def test_combo_server_vm_end_to_end():
    files = combo_mod.build_combo_files(target_ss_id="MOCK_SS_1")
    by_name = {f["name"]: f["source"] for f in files}

    node_driver = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const propsStore = {};
const cacheStore = {};

// 最小限の Spreadsheet モック（A1 タイトル + 3行目ヘッダ + 4-5行目データ）
const grid = [
  ['部門別売上表', '', '', ''],
  ['', '', '', ''],
  ['部門', '1月', '2月', '合計'],
  ['営業部', 100, 200, '=SUM(B4:C4)'],
  ['開発部', 300, 400, '=SUM(B5:C5)']
];
const bgs = grid.map(r => r.map(() => '#ffffff'));
const fcolors = grid.map(r => r.map(() => '#000000'));
fcolors[0][0] = '#0000ff';
const weights = grid.map(r => r.map(() => 'normal'));
weights[0][0] = 'bold';
const styles = grid.map(r => r.map(() => 'normal'));
const sizes = grid.map(r => r.map(() => 10));
sizes[0][0] = 14;
const aligns = grid.map(r => r.map(() => 'general'));
const numFmts = grid.map(r => r.map(() => 'General'));
const colWidths = { 1: 100, 2: 100, 3: 100, 4: 100 };
let frozenRows = 0, frozenCols = 0;

function makeRange(r, c, nr, nc) {
  function colA1(n) {
    let s = '';
    while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
    return s;
  }
  function a1() {
    if (nr === 1 && nc === 1) return colA1(c) + r;
    return colA1(c) + r + ':' + colA1(c + nc - 1) + (r + nr - 1);
  }
  const slice = (arr) => arr.slice(r - 1, r - 1 + nr).map(row => row.slice(c - 1, c - 1 + nc));
  const write = (arr, valOrMatrix) => {
    if (Array.isArray(valOrMatrix)) {
      for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) arr[r - 1 + i][c - 1 + j] = valOrMatrix[i][j];
    } else {
      for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) arr[r - 1 + i][c - 1 + j] = valOrMatrix;
    }
    return rangeObj;
  };
  const rangeObj = {
    getRow: () => r, getColumn: () => c, getNumRows: () => nr, getNumColumns: () => nc,
    getA1Notation: a1,
    getValues: () => slice(grid),
    getDisplayValues: () => slice(grid).map(row => row.map(v => String(v))),
    getFormulas: () => slice(grid).map(row => row.map(v => (typeof v === 'string' && v.startsWith('=')) ? v : '')),
    getBackgrounds: () => slice(bgs),
    getFontColors: () => slice(fcolors),
    getFontWeights: () => slice(weights),
    getFontStyles: () => slice(styles),
    getFontSizes: () => slice(sizes),
    getHorizontalAlignments: () => slice(aligns),
    getNumberFormats: () => slice(numFmts),
    setValues: (m) => write(grid, m),
    setValue: (v) => write(grid, v),
    setBackgrounds: (m) => write(bgs, m),
    setBackground: (v) => write(bgs, v),
    setFontColors: (m) => write(fcolors, m),
    setFontColor: (v) => write(fcolors, v),
    setFontWeights: (m) => write(weights, m),
    setFontWeight: (v) => write(weights, v),
    setFontStyles: (m) => write(styles, m),
    setFontStyle: (v) => write(styles, v),
    setFontSizes: (m) => write(sizes, m),
    setFontSize: (v) => write(sizes, v),
    setHorizontalAlignments: (m) => write(aligns, m),
    setHorizontalAlignment: (v) => write(aligns, v),
    setNumberFormats: (m) => write(numFmts, m),
    setNumberFormat: (v) => write(numFmts, v),
    setVerticalAlignment: () => rangeObj,
    setBorder: () => rangeObj,
    setWrap: () => rangeObj,
    clearFormat: () => rangeObj,
    clearContent: () => rangeObj,
    merge: () => rangeObj,
    breakApart: () => rangeObj
  };
  return rangeObj;
}

function parseA1(a1Str) {
  const s = String(a1Str).trim().toUpperCase();
  const colToNum = (col) => { let n = 0; for (let i = 0; i < col.length; i++) n = n * 26 + (col.charCodeAt(i) - 64); return n; };
  const m = s.match(/^([A-Z]+)([0-9]+)(?::([A-Z]+)([0-9]+))?$/);
  if (!m) return [1, 1, 1, 1];
  const c1 = colToNum(m[1]), r1 = parseInt(m[2], 10);
  const c2 = m[3] ? colToNum(m[3]) : c1, r2 = m[4] ? parseInt(m[4], 10) : r1;
  return [r1, c1, r2 - r1 + 1, c2 - c1 + 1];
}

const mockSheet = {
  getSheetId: () => 101,
  getName: () => '売上表',
  getParent: () => mockSs,
  getDataRange: () => makeRange(1, 1, grid.length, grid[0].length),
  getLastRow: () => grid.length,
  getLastColumn: () => grid[0].length,
  getFrozenRows: () => frozenRows,
  getFrozenColumns: () => frozenCols,
  setFrozenRows: (n) => { frozenRows = n; },
  setFrozenColumns: (n) => { frozenCols = n; },
  getColumnWidth: (c) => colWidths[c] || 100,
  setColumnWidth: (c, w) => { colWidths[c] = w; },
  autoResizeColumn: (c) => { colWidths[c] = 120; },
  autoResizeColumns: (c, n) => { for (let i = c; i < c + n; i++) colWidths[i] = 120; },
  getActiveRange: () => makeRange(1, 1, 1, 1),
  getRange: (a, b, c, d) => {
    if (typeof a === 'string') { const p = parseA1(a); return makeRange(p[0], p[1], p[2], p[3]); }
    return makeRange(a, b, c || 1, d || 1);
  },
  getCharts: () => [],
  getBandings: () => [],
  getFilter: () => null
};

const mockSs = {
  getId: () => 'MOCK_SS_1',
  getName: () => 'テストブック',
  getUrl: () => 'https://docs.google.com/spreadsheets/d/MOCK_SS_1/edit',
  getSheets: () => [mockSheet],
  getActiveSheet: () => mockSheet,
  getActiveRange: () => makeRange(1, 1, 1, 1),
  getSheetByName: (name) => name === '売上表' ? mockSheet : null,
  toast: () => {}
};

const sandbox = {
  console,
  SpreadsheetApp: {
    getActiveSpreadsheet: () => mockSs,
    openById: () => mockSs,
    flush: () => {},
    getUi: () => ({ createMenu: () => ({ addItem: function(){return this;}, addToUi: function(){} }), showSidebar: () => {} })
  },
  DocumentApp: new Proxy({}, { get: () => new Proxy({}, { get: () => 1 }) }),
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (k) => (k in propsStore ? propsStore[k] : null),
      setProperty: (k, v) => { propsStore[k] = String(v); },
      deleteProperty: (k) => { delete propsStore[k]; }
    }),
    getUserProperties: () => ({
      getProperty: (k) => (('u:' + k) in propsStore ? propsStore['u:' + k] : null),
      setProperty: (k, v) => { propsStore['u:' + k] = String(v); },
      deleteProperty: (k) => { delete propsStore['u:' + k]; }
    })
  },
  CacheService: {
    getScriptCache: () => ({
      get: (k) => (k in cacheStore ? cacheStore[k] : null),
      put: (k, v) => { cacheStore[k] = String(v); },
      remove: (k) => { delete cacheStore[k]; }
    })
  },
  Utilities: {
    computeDigest: () => [1, 2, 3, 4],
    DigestAlgorithm: { MD5: 'MD5' },
    newBlob: (s) => ({ getBytes: () => Buffer.from(String(s), 'utf8'), getDataAsString: () => String(s) }),
    gzip: (b) => b,
    ungzip: (b) => b,
    base64Encode: (buf) => Buffer.from(buf).toString('base64'),
    base64Decode: (s) => Buffer.from(s, 'base64')
  },
  Session: { getActiveUser: () => ({ getEmail: () => 'test@example.com' }) }
};

const ctx = vm.createContext(sandbox);
vm.runInContext(payload.engine + '\n' + payload.planner + '\n' + payload.server, ctx);

const rInit = ctx.comboInit({});
const rLook = ctx.comboLook({});
const rFind = ctx.comboFind({ ask: '文字色', kind: 'sheet' });
const rAskRed = ctx.comboRunAsk({ ask: 'タイトルの文字の色を赤に変えてください。', backup: false, fastUndo: true });
const colorAfterRed = fcolors[0][0];
const rUndo = ctx.comboUndo({});
const colorAfterUndo = fcolors[0][0];
const rAskHonest = ctx.comboRunAsk({ ask: 'タイトルの本当の色を緑に変えてください。', backup: false, fastUndo: true });
const colorAfterHonest = fcolors[0][0];
const rUndo2 = ctx.comboUndo({});
const colorFinal = fcolors[0][0];

// 当たらない頼み → 近い候補 →［はい］で覚える → 次は一発で撃つ
const rMiss = ctx.comboRunAsk({ ask: 'タイトルをどーんと赤に', backup: false, fastUndo: true });
const rLearn = ctx.comboLearn({ ask: 'タイトルをどーんと赤に', ops: rMiss.plan && rMiss.plan.suggest, key: ctx.ComboPlanner.learnKey('タイトルをどーんと赤に') });
const rLearned = ctx.comboGetLearned({});
const rHitLearned = ctx.comboRunAsk({ ask: 'タイトルをどーんと赤に。', backup: false, fastUndo: true });
const bgAfterLearned = fcolors[0][0];
ctx.comboUndo({});

// 郵便受けフロー
const rPb = ctx.comboRunAsk({ ask: 'この表の傾向を日本語で説明して', aiAuto: true });
const rPoll = ctx.comboPostboxPoll();
const reqId = rPoll.queue[0].reqId;
const rDeliv = ctx.comboPostboxDeliver({ reqId, action: 'reply', message: '売上が順調です。' });
const rSidePoll = ctx.comboPollSelection({});

process.stdout.write(JSON.stringify({
  rInit, rLook, rFind, rAskRed, colorAfterRed, rUndo, colorAfterUndo,
  rAskHonest, colorAfterHonest, rUndo2, colorFinal,
  rPb, rPoll, rDeliv, rSidePoll, rMiss, rLearn, rLearned, rHitLearned, bgAfterLearned
}));
"""
    res = _run_node_json(
        node_driver,
        {
            "engine": by_name["Engine"],
            "planner": by_name["ComboPlanner"],
            "server": by_name["ComboServer"],
        },
    )

    assert res["rInit"]["ok"] is True
    assert res["rInit"]["table"]["header_row"] == 3
    assert res["rLook"]["ok"] is True
    assert "部門別売上表" in res["rLook"]["text"] or "売上表" in res["rLook"]["text"]
    assert res["rFind"]["ok"] is True and "format" in res["rFind"]["text"]

    assert res["rAskRed"]["ok"] is True
    assert res["colorAfterRed"].lower() in ("#ff0000", "#cc0000", "red")
    assert res["rUndo"]["ok"] is True and res["rUndo"]["fast"] is True
    assert res["colorAfterUndo"].lower() == "#0000ff"

    assert res["rAskHonest"]["ok"] is True
    assert res["colorAfterHonest"].lower() != "#0000ff"
    assert res["rUndo2"]["ok"] is True
    assert res["colorFinal"].lower() == "#0000ff"

    assert res["rMiss"]["unfired"] is True and "近い候補" in res["rMiss"]["text"]
    assert res["rLearn"]["ok"] is True and len(res["rLearned"]["learned"]) == 1
    assert res["rHitLearned"]["ok"] is True and res["rHitLearned"]["source"] == "shelf"
    assert res["bgAfterLearned"].lower() != "#0000ff"

    assert res["rPb"]["pendingPostbox"] is True
    assert res["rPoll"]["count"] == 1
    assert res["rDeliv"]["ok"] is True
    assert len(res["rSidePoll"]["postboxDone"]) == 1
    assert "売上が順調です" in res["rSidePoll"]["postboxDone"][0]["text"]


# ---------------------------------------------------------------- 4. install_combo / CLI / MCP 統合


def test_install_combo_and_mcp_routing(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(
        json.dumps({"tokens": {"default": {"client_id": "c", "client_secret": "s", "refresh_token": "r"}}}),
        encoding="utf-8",
    )
    with patch.object(GasClient, "get_access_token", return_value="dummy"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(tmp_path / ".bak"))
    client.resolve_script_id = MagicMock(return_value="SID_MOCK_999")
    client._put_content = MagicMock()
    client.run_function = MagicMock(side_effect=[
        {"ok": True, "result": {"ok": True, "targetId": "SS_MOCK_1"}},  # comboSetTestTarget
        {"ok": True, "result": {"ok": True, "text": "[棚ヒット] format(title=true, color=\"赤\")", "gasMs": 240}},
        {"ok": True, "result": {"ok": True, "text": "戻した: A1 を取り消しました", "gasMs": 190}},
        {"ok": True, "result": {"ok": True, "text": "対象: テスト › Sheet1", "gasMs": 210}},
    ])

    with patch("gas_mcp_server.get_client", return_value=client):
        out_inst = gas_mcp_server.gas("combo install SID_MOCK_999 --ss SS_MOCK_1")
        inst_obj = json.loads(out_inst)
        assert inst_obj["ok"] is True
        assert inst_obj["scriptId"] == "SID_MOCK_999"
        assert inst_obj["targetSsId"] == "SS_MOCK_1"
        assert inst_obj["testTargetSaved"] is True
        assert client._put_content.call_count == 1
        pushed_files = client._put_content.call_args[0][1]
        assert [f["name"] for f in pushed_files] == ["appsscript", "Engine", "ComboPlanner", "ComboServer", "ComboSidebar"]

        out_ask = gas_mcp_server.gas("combo ask SID_MOCK_999 タイトルの文字の色を赤に変えてください。")
        assert "棚ヒット" in out_ask and "240ms" in out_ask

        out_undo = gas_mcp_server.gas("combo undo SID_MOCK_999")
        assert "戻した" in out_undo

        out_look = gas_mcp_server.gas("combo look SID_MOCK_999")
        assert "対象:" in out_look

        out_help = gas_mcp_server.gas("combo help")
        assert "combo install" in out_help


def test_gas_cli_dispatches_combo(monkeypatch):
    import gas as gas_cli
    called = {}

    def fake_run_cli(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(combo_mod, "_run_cli", fake_run_cli)
    monkeypatch.setattr(sys, "argv", ["gas.py", "combo", "ask", "SID_1", "タイトルの文字の色を赤に"])
    with pytest.raises(SystemExit) as exc:
        gas_cli.main()
    assert exc.value.code == 0
    assert called["argv"] == ["ask", "SID_1", "タイトルの文字の色を赤に"]


def test_install_combo_detects_authorization_needed(tmp_path):
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(
        json.dumps({"tokens": {"default": {"client_id": "c", "client_secret": "s", "refresh_token": "r"}}}),
        encoding="utf-8",
    )
    with patch.object(GasClient, "get_access_token", return_value="dummy"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(tmp_path / ".bak"))
    client.resolve_script_id = MagicMock(return_value="SID_AUTH")
    client._put_content = MagicMock()
    client.resolve_webapp_url = MagicMock(return_value="https://script.google.com/macros/s/MOCK_DEP/exec")
    auth_resp = {"ok": False, "raw": "<html><head><title>Authorization needed</title></head></html>"}
    client.run_function = MagicMock(return_value=auth_resp)

    res = combo_mod.install_combo("SID_AUTH", target_ss_id="SS_1", client=client)
    assert res["ok"] is True
    assert res["testTargetSaved"] is False
    assert res["authNeeded"] is True
    assert "https://script.google.com/macros/s/MOCK_DEP/exec" in res["testTargetError"]

    with pytest.raises(RuntimeError) as exc:
        combo_mod._unwrap_run_result(auth_resp, client=client, sid="SID_AUTH")
    assert "https://script.google.com/macros/s/MOCK_DEP/exec" in str(exc.value)


@needs_node
def test_include_extra_scopes_false_and_extra_actions_fast_path():
    files_3 = combo_mod.build_combo_files(target_ss_id="SS_3", include_extra_scopes=False)
    by_name = {f["name"]: f for f in files_3}
    manifest = json.loads(by_name["appsscript"]["source"])
    assert manifest["oauthScopes"] == [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]
    assert manifest["webapp"] == {"executeAs": "USER_DEPLOYING", "access": "MYSELF"}

    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const propsStore = {}, cacheStore = {};
const getterCalls = { getValues: 0, getFormulas: 0, getBackgrounds: 0, getFontColors: 0, getName: 0, getUrl: 0 };
const fcolors = [['#0000ff', '#000000'], ['#000000', '#000000'], ['#000000', '#000000'], ['#000000', '#000000']];
const grid = [['タイトル', ''], ['', ''], ['部門', '金額'], ['A', 100]];
function mkRange(r, c, nr, nc) {
  const slice = (arr) => arr.slice(r - 1, r - 1 + nr).map(row => row.slice(c - 1, c - 1 + nc));
  const write = (arr, v) => {
    if (Array.isArray(v)) { for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j]=v[i][j]; }
    else { for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j]=v; }
    return obj;
  };
  const obj = {
    getRow: () => r, getColumn: () => c, getNumRows: () => nr, getNumColumns: () => nc,
    getA1Notation: () => (nr === 1 && nc === 1 ? 'A' + r : 'A' + r + ':B' + (r + nr - 1)),
    getValues: () => { getterCalls.getValues++; return slice(grid); },
    getFormulas: () => { getterCalls.getFormulas++; return slice(grid).map(row => row.map(() => '')); },
    getBackgrounds: () => { getterCalls.getBackgrounds++; return slice(grid).map(row => row.map(() => '#ffffff')); },
    getFontColors: () => { getterCalls.getFontColors++; return slice(fcolors); },
    setFontColors: (m) => write(fcolors, m),
    setFontColor: (v) => write(fcolors, v),
  };
  return obj;
}
const mockSh = {
  getSheetId: () => 1, getName: () => '売上', getParent: () => mockSs,
  getDataRange: () => mkRange(1, 1, 4, 2), getLastRow: () => 4, getLastColumn: () => 2,
  getFrozenRows: () => 0, getFrozenColumns: () => 0,
  getActiveRange: () => mkRange(1, 1, 1, 1),
  getRange: (a, b, c, d) => typeof a === 'string' ? mkRange(1, 1, 1, 1) : mkRange(a, b, c || 1, d || 1),
};
const mockSs = {
  getId: () => 'SS_3',
  getName: () => { getterCalls.getName++; return 'テスト'; },
  getUrl: () => { getterCalls.getUrl++; return 'https://example.com'; },
  getSheets: () => [mockSh], getActiveSheet: () => mockSh, getActiveRange: () => mkRange(1, 1, 1, 1),
  getSheetByName: (n) => n === '売上' ? mockSh : null,
};
const ctx = vm.createContext({
  SpreadsheetApp: { getActiveSpreadsheet: () => mockSs, openById: () => mockSs, flush: () => {} },
  DocumentApp: new Proxy({}, { get: () => new Proxy({}, { get: () => 1 }) }),
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...propsStore }),
      getProperty: k => (k in propsStore ? propsStore[k] : null),
      setProperty: (k, v) => { propsStore[k] = String(v); },
      deleteProperty: k => { delete propsStore[k]; }
    }),
    getScriptProperties: () => ({
      getProperties: () => ({ ...propsStore }),
      getProperty: k => (k in propsStore ? propsStore[k] : null),
      setProperty: (k, v) => { propsStore[k] = String(v); },
      deleteProperty: k => { delete propsStore[k]; }
    })
  },
  CacheService: { getScriptCache: () => ({
    get: k => (k in cacheStore ? cacheStore[k] : null),
    put: (k, v) => { cacheStore[k] = String(v); },
    remove: k => { delete cacheStore[k]; }
  }) },
  Utilities: { computeDigest: () => [1,2,3], DigestAlgorithm: { MD5: 'MD5' }, newBlob: (s) => ({ getBytes: () => Buffer.from(String(s), 'utf8') }), base64Encode: (b) => Buffer.from(b).toString('base64') }
});
vm.runInContext(payload.engine + '\n' + payload.planner + '\n' + payload.server, ctx);
const initRes = ctx.EXTRA_ACTIONS.combo_init({});
// 以降の getter カウントをリセットしてキャッシュ済み fast-path（デフォルト backup=false, fastUndo なし）を計測
Object.keys(getterCalls).forEach(k => getterCalls[k] = 0);
const rFastNoUndo = ctx.EXTRA_ACTIONS.combo_ask({
  ask: 'タイトルの文字の色を赤に変えてください。',
  ops: [{ shelf: 'format', title: true, color: '赤' }],
  targetName: 'テスト',
  sheets: ['売上'],
  table: initRes.table,
  sheet: '売上',
  selection: 'A1',
  backup: false
});
const fastNoUndoGetters = Object.assign({}, getterCalls);
const afterRedNoUndo = fcolors[0][0];

// fastUndo: true のときは 1 getter のみ取得して復元可能
Object.keys(getterCalls).forEach(k => getterCalls[k] = 0);
const rAsk = ctx.EXTRA_ACTIONS.combo_ask({ ask: 'タイトルの文字の色を青に変えてください。', sheet: '売上', selection: 'A1', backup: false, fastUndo: true });
const askGetters = Object.assign({}, getterCalls);
const afterBlue = fcolors[0][0];
const rUndo = ctx.EXTRA_ACTIONS.combo_undo({});
const afterUndo = fcolors[0][0];
process.stdout.write(JSON.stringify({
  keys: Object.keys(ctx.EXTRA_ACTIONS),
  fastNoUndoGetters,
  rFastNoUndo,
  afterRedNoUndo,
  getterCalls: askGetters,
  rAsk,
  afterBlue,
  rUndo,
  afterUndo
}));
"""
    res = _run_node_json(
        node_code,
        {"engine": by_name["Engine"]["source"], "planner": by_name["ComboPlanner"]["source"], "server": by_name["ComboServer"]["source"]},
    )
    assert {"combo_init", "combo_look", "combo_find", "combo_ask", "combo_ops", "combo_undo", "combo_poll", "combo_set_target"} <= set(res["keys"])
    assert res["rFastNoUndo"]["ok"] is True
    assert res["fastNoUndoGetters"] == {"getValues": 0, "getFormulas": 0, "getBackgrounds": 0, "getFontColors": 0, "getName": 0, "getUrl": 0}
    assert res["rAsk"]["ok"] is True
    assert res["afterBlue"].lower() in ("#0000ff", "blue")
    assert res["getterCalls"] == {"getValues": 0, "getFormulas": 0, "getBackgrounds": 0, "getFontColors": 1, "getName": 0, "getUrl": 0}
    assert res["rUndo"]["ok"] is True
    assert res["afterUndo"].lower() in ("#ff0000", "#cc0000", "red")


@needs_node
def test_combo_lite_bundle_and_connector_defaults(tmp_path):
    """combo_lite=True で ComboPlanner/doc/Sheets拡張を外しても全シート操作と軽量フォールバックが動作することを検証。"""
    files = combo_mod.build_combo_files(combo_lite=True)
    assert [f["name"] for f in files] == ["appsscript", "Engine", "ComboServer", "ComboSidebar"]
    by_name = {f["name"]: f["source"] for f in files}

    manifest = json.loads(by_name["appsscript"])
    assert manifest["dependencies"] == {}
    assert "https://www.googleapis.com/auth/documents" not in manifest["oauthScopes"]

    # Engine に Sheets 遅延 REST シムが入り、doPost / actLook_ / actRender_ が除外されていること
    eng = by_name["Engine"]
    assert "function doPost(" not in eng
    assert "function actLook_(" not in eng
    assert "function actRender_(" not in eng
    assert "sheets.googleapis.com/v4/spreadsheets/" in eng

    # 構文エラーなし
    for name in ("Engine", "ComboServer"):
        p = tmp_path / f"lite_{name}.js"
        p.write_text(eng if name == "Engine" else by_name[name], encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert proc.returncode == 0, f"lite {name}.js syntax error: {proc.stderr}"

    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", by_name["ComboSidebar"], flags=re.IGNORECASE)
    assert len(scripts) >= 1
    for idx, sc in enumerate(scripts):
        p = tmp_path / f"lite_sidebar_{idx}.js"
        p.write_text(sc, encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert proc.returncode == 0, f"lite ComboSidebar <script> #{idx} syntax error: {proc.stderr}"

    # ComboPlanner なしの VM 環境でも comboInit / ops付き comboRunAsk / comboFind / comboUndo が動作
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const propsStore = {}, cacheStore = {};
const fcolors = [['#0000ff', '#000000'], ['#000000', '#000000'], ['#000000', '#000000'], ['#000000', '#000000']];
const grid = [['タイトル', ''], ['', ''], ['部門', '金額'], ['A', 100]];
function mkRange(r, c, nr, nc) {
  const slice = (arr) => arr.slice(r - 1, r - 1 + nr).map(row => row.slice(c - 1, c - 1 + nc));
  const write = (arr, v) => {
    if (Array.isArray(v)) { for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j]=v[i][j]; }
    else { for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j]=v; }
    return obj;
  };
  const obj = {
    getRow: () => r, getColumn: () => c, getNumRows: () => nr, getNumColumns: () => nc,
    getA1Notation: () => (nr === 1 && nc === 1 ? 'A' + r : 'A' + r + ':B' + (r + nr - 1)),
    getValues: () => slice(grid),
    getDisplayValues: () => slice(grid).map(row => row.map(String)),
    getFormulas: () => slice(grid).map(row => row.map(() => '')),
    getBackgrounds: () => slice(grid).map(row => row.map(() => '#ffffff')),
    getFontColors: () => slice(fcolors),
    setFontColors: (m) => write(fcolors, m),
    setFontColor: (v) => write(fcolors, v),
  };
  return obj;
}
const mockSh = {
  getSheetId: () => 1, getName: () => '売上', getParent: () => mockSs,
  getDataRange: () => mkRange(1, 1, 4, 2), getLastRow: () => 4, getLastColumn: () => 2,
  getFrozenRows: () => 0, getFrozenColumns: () => 0,
  getActiveRange: () => mkRange(1, 1, 1, 1),
  getRange: (a, b, c, d) => typeof a === 'string' ? mkRange(1, 1, 1, 1) : mkRange(a, b, c || 1, d || 1),
};
const mockSs = {
  getId: () => 'SS_LITE',
  getName: () => '軽量テスト',
  getSheets: () => [mockSh], getActiveSheet: () => mockSh, getActiveRange: () => mkRange(1, 1, 1, 1),
  getSheetByName: (n) => n === '売上' ? mockSh : null,
};
const ctx = vm.createContext({
  SpreadsheetApp: { getActiveSpreadsheet: () => mockSs, openById: () => mockSs, flush: () => {} },
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...propsStore }),
      getProperty: k => (k in propsStore ? propsStore[k] : null),
      setProperty: (k, v) => { propsStore[k] = String(v); },
      deleteProperty: k => { delete propsStore[k]; }
    }),
    getScriptProperties: () => ({
      getProperties: () => ({ ...propsStore }),
      getProperty: k => (k in propsStore ? propsStore[k] : null),
      setProperty: (k, v) => { propsStore[k] = String(v); },
      deleteProperty: k => { delete propsStore[k]; }
    })
  },
  CacheService: { getScriptCache: () => ({
    get: k => (k in cacheStore ? cacheStore[k] : null),
    put: (k, v) => { cacheStore[k] = String(v); },
    remove: k => { delete cacheStore[k]; }
  }) },
  Utilities: { computeDigest: () => [1,2,3], DigestAlgorithm: { MD5: 'MD5' }, newBlob: (s) => ({ getBytes: () => Buffer.from(String(s), 'utf8') }), base64Encode: (b) => Buffer.from(b).toString('base64') }
});
vm.runInContext(payload.engine + '\n' + payload.server, ctx);
const rInit = ctx.comboInit({ assumeActive: true });
const rAsk = ctx.comboRunAsk({
  ask: 'タイトルの文字色を赤に',
  ops: [{ shelf: 'format', title: true, color: '赤' }],
  assumeActive: true,
  targetName: '軽量テスト',
  sheets: ['売上'],
  table: rInit.table,
  sheet: '売上',
  selection: 'A1',
  fastUndo: true
});
const colorAfterRed = fcolors[0][0];
const rUndo = ctx.comboUndo({ assumeActive: true });
const colorAfterUndo = fcolors[0][0];
const rFind = ctx.comboFind({ ask: '書式', kind: 'sheet' });
process.stdout.write(JSON.stringify({ rInit, rAsk, colorAfterRed, rUndo, colorAfterUndo, rFind }));
"""
    res = _run_node_json(node_code, {"engine": eng, "server": by_name["ComboServer"]})
    assert res["rInit"]["ok"] is True
    assert res["rAsk"]["ok"] is True
    assert res["colorAfterRed"].lower() in ("#ff0000", "red")
    assert res["rUndo"]["ok"] is True
    assert res["colorAfterUndo"].lower() == "#0000ff"
    assert res["rFind"]["ok"] is True and "format" in res["rFind"]["text"]

    # コネクタ設定のデフォルトが developmentMode=False / Sheets拡張なし / 30行繋ぎコードであることを確認
    conn_files = combo_mod.build_combo_connector_files(engine_lib_id="LIB_LITE_1", engine_version="3")
    c_map = {f["name"]: f["source"] for f in conn_files}
    c_manifest = json.loads(c_map["appsscript"])
    lib = c_manifest["dependencies"]["libraries"][0]
    assert lib["libraryId"] == "LIB_LITE_1"
    assert lib["version"] == "3"
    assert lib["developmentMode"] is False
    assert lib["userSymbol"] == "shucomboengine"
    assert "enabledAdvancedServices" not in c_manifest["dependencies"]
    assert "shucomboengine.comboRunAsk" in c_map["コード"]
    assert "shucomboengine.comboQuickList" in c_map["コード"]
    assert "shucomboengine.comboQuickAiSave" in c_map["コード"]
    assert "https://www.googleapis.com/auth/drive.scripts" in c_manifest["oauthScopes"]


def test_connect_spreadsheet_from_url_and_cli(tmp_path):
    """スプレッドシート URL / ID を渡すだけで parentId 付き GAS 作成〜30行繋ぎ配置ができることを検証。"""
    clasprc = tmp_path / ".clasprc.json"
    clasprc.write_text(
        json.dumps({"tokens": {"default": {"client_id": "c", "client_secret": "s", "refresh_token": "r"}}}),
        encoding="utf-8",
    )
    with patch.object(GasClient, "get_access_token", return_value="dummy"):
        client = GasClient(clasprc_path=str(clasprc), backup_dir=str(tmp_path / ".bak"))

    client.create_project = MagicMock(return_value={"scriptId": "NEW_BOUND_SID_123"})
    client.resolve_script_id = MagicMock(side_effect=lambda x: x)
    client.list_versions = MagicMock(return_value=[{"versionNumber": 3}])
    client._put_content = MagicMock()

    ss_url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEf/edit#gid=0"
    st_file = tmp_path / ".combo_state.json"
    client.set_alias = MagicMock()
    res = combo_mod.connect_spreadsheet(
        ss_url,
        engine_lib_id="LIB_COMBO_1",
        engine_version="3",
        title="GASコンボ",
        client=client,
        state_path=st_file,
    )
    assert res["ok"] is True
    assert res["createdProject"] is True
    assert res["spreadsheetId"] == "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEf"
    assert res["scriptId"] == "NEW_BOUND_SID_123"
    client.create_project.assert_called_once_with("GASコンボ", parent_id="1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEf")
    assert client.set_alias.call_count == 1
    assert client._put_content.call_count == 1
    pushed = client._put_content.call_args[0][1]
    assert [f["name"] for f in pushed] == ["appsscript", "コード"]

    # 2回目は同じスプレッドシートIDに対して二重作成せず既存 sid を再利用すること
    client.create_project.reset_mock()
    res2 = combo_mod.connect_spreadsheet(
        ss_url,
        engine_lib_id="LIB_COMBO_1",
        engine_version="3",
        client=client,
        state_path=st_file,
    )
    assert res2["createdProject"] is False
    assert res2["scriptId"] == "NEW_BOUND_SID_123"
    client.create_project.assert_not_called()

    # CLI ルーティング: URL 直接渡し＆引数なし（アクティブシート自動取得）で connect_spreadsheet が動くこと
    with patch("gas_client.GasClient", return_value=client), \
         patch.object(combo_mod, "COMBO_ENGINE_STATE_PATH", st_file), \
         patch.object(combo_mod, "_resolve_active_sheet_id", return_value=("AUTO_SS_777", "自動テスト表")):
        client.create_project.reset_mock()
        rc = combo_mod._run_cli(["connect", ss_url, "--lib-id", "LIB_COMBO_1", "--lib-ver", "3"])
        assert rc == 0
        client.create_project.assert_not_called()  # st_file に記録済みのため再利用

        rc_auto = combo_mod._run_cli(["connect", "--lib-id", "LIB_COMBO_1", "--lib-ver", "3"])
        assert rc_auto == 0
        client.create_project.assert_called_once_with("GASコンボ", parent_id="AUTO_SS_777")


@needs_node
def test_sidebar_direct_sheets_api_expanded():
    """拡張した直接 Sheets API ルート（borders/merge/clear/write/filter/sort/banding/sheet.*/api）とガードを検証。"""
    files = combo_mod.build_combo_files()
    sidebar_html = {f["name"]: f["source"] for f in files}["ComboSidebar"]
    scripts = re.findall(r"<script>([\s\S]*?)</script>", sidebar_html)
    assert scripts, "ComboSidebar に <script> が見つかりません"

    node_code = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

function makeEl(id) {
  return {
    id,
    value: '',
    checked: false,
    disabled: false,
    textContent: '',
    innerHTML: '',
    style: {},
    dataset: {},
    children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){},
    appendChild(c){ this.children.push(c); return c; },
    querySelectorAll(){ return []; },
    querySelector(){ return null; },
    focus(){}
  };
}
const elsMap = {};
const sandbox = {
  console, Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp, Error, parseInt, parseFloat, isNaN, isFinite,
  encodeURIComponent, decodeURIComponent,
  setTimeout: () => 0,
  clearTimeout: () => {},
  performance: { now: () => 100 },
  document: {
    getElementById(id) {
      if (!elsMap[id]) elsMap[id] = makeEl(id);
      return elsMap[id];
    },
    createElement(tag) { return makeEl(tag); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {}
  },
  window: { addEventListener() {} },
  localStorage: { getItem(){ return null; }, setItem(){} }
};
sandbox.globalThis = sandbox;
for (const sc of input.scripts) {
  vm.runInNewContext(sc, sandbox);
}

const dt = sandbox.__comboDirectTest;
if (!dt || typeof dt.buildDirectBatchUpdate !== 'function') {
  throw new Error('__comboDirectTest.buildDirectBatchUpdate not exposed');
}

dt.state.oauthToken = 'tok_dummy';
dt.state.target = { id: 'SS_1', kind: 'sheet', name: '売上表', sheet: 'Sheet1' };
dt.state.curSheet = 'Sheet1';
dt.state.sheets = ['Sheet1', '元データ'];
dt.state.sheetIdMap = { Sheet1: 111, '元データ': 222 };
dt.state.table = {
  title_a1: 'A1',
  header_row: 3,
  first_col: 'A',
  last_col: 'D',
  data: '4-8',
  total_row: 9,
  columns: [
    { col: 'A', name: '日付' },
    { col: 'B', name: '部門' },
    { col: 'C', name: '担当者' },
    { col: 'D', name: '売上' }
  ]
};
dt.state.sheetSnapshot = {
  Sheet1: { frozenRows: 0, frozenCols: 0, bandedRangeIds: [901], vals: {}, cells: Array.from({ length: 30 }, () => Array.from({ length: 26 }, () => ({}))) }
};
dt.els.chkBackup.checked = false;
dt.els.chkOk.checked = false;

const build = (ops, sh) => dt.buildDirectBatchUpdate(ops, sh || 'Sheet1');

// 1. format borders & merge（文字書式なしでも repeatCell 空送信せず updateBorders/mergeCells のみ生成）
const pBorders = build([{ shelf: 'format', range: 'A3:D8', borders: true }]);
const pOuter = build([{ shelf: 'format', range: 'A3:D8', borders: 'outer' }]);
const pMerge = build([{ shelf: 'format', range: 'A1:D1', merge: true, bold: true }]);

// 2. clear.format は確認不要、clear.values / clear.all / api は chkOk=false で null（GAS確認へフォールバック）
const pClearFmt = build([{ shelf: 'clear.format', range: 'A4:D8' }]);
const pClearValBlocked = build([{ shelf: 'clear.values', range: 'A4:D8' }]);
const pClearAllBlocked = build([{ shelf: 'clear.all', range: 'A4:D8' }]);
const pApiBlocked = build([{ shelf: 'api', requests: [{ deleteDimension: {} }] }]);

dt.els.chkOk.checked = true;
const pClearValOk = build([{ shelf: 'clear.values', range: 'A4:D8' }]);
const pClearValConst = build([{ shelf: 'clear.values', range: 'A4:D8', only: 'constants' }]);
const pClearAllOk = build([{ shelf: 'clear.all', range: 'A4:D8' }]);
const pApiOk = build([{ shelf: 'api', requests: [{ updateSheetProperties: { properties: { sheetId: 111 } } }] }]);
dt.els.chkOk.checked = false;

// 3. write
const pWrite = build([{ shelf: 'write', cells: { A10: '合計', D10: '=SUM(D4:D8)', B10: 1200, C10: true } }]);

// 4. filter.on / filter.off / sort
const pFilterOn = build([{ shelf: 'filter.on' }]);
const pFilterOff = build([{ shelf: 'filter.off' }]);
const pSortDesc = build([{ shelf: 'sort', col: '売上', desc: true }]);
const pSortAsc = build([{ shelf: 'sort', col: 'A', desc: false }]);

// 5. banding.add / banding.remove
const pBandAdd = build([{ shelf: 'banding.add', theme: 'blue' }]);
pBandAdd.applySnapshot({ replies: [{}, { addBanding: { bandedRange: { bandedRangeId: 902 } } }] });
const bandIdAfterAdd = dt.state.sheetSnapshot.Sheet1.bandedRangeIds.slice();
const pBandRem = build([{ shelf: 'banding.remove' }]);

// 6. sheet.color / sheet.rename / sheet.hide / sheet.show
const pTabColor = build([{ shelf: 'sheet.color', color: '赤' }]);
const pTabClear = build([{ shelf: 'sheet.color', color: 'なし' }]);
const pHide = build([{ shelf: 'sheet.hide', name: '元データ' }]);
const pShow = build([{ shelf: 'sheet.show', name: '元データ' }]);
const pRename = build([{ shelf: 'sheet.rename', name: 'Sheet1', to: '売上集計' }]);
pRename.applySnapshot();
const curAfterRename = dt.state.curSheet;
const sidAfterRename = dt.state.sheetIdMap['売上集計'];

process.stdout.write(JSON.stringify({
  pBorders, pOuter, pMerge,
  pClearFmt, pClearValBlocked, pClearAllBlocked, pApiBlocked,
  pClearValOk, pClearValConst, pClearAllOk, pApiOk,
  pWrite, pFilterOn, pFilterOff, pSortDesc, pSortAsc,
  pBandAddReqs: pBandAdd.requests, bandIdAfterAdd, pBandRemReqs: pBandRem.requests,
  pTabColor, pTabClear, pHide, pShow, pRenameReqs: pRename.requests, curAfterRename, sidAfterRename
}));
"""
    res = _run_node_json(node_code, {"scripts": scripts})

    # borders / merge
    assert len(res["pBorders"]["requests"]) == 1
    assert "updateBorders" in res["pBorders"]["requests"][0]
    assert "innerHorizontal" in res["pBorders"]["requests"][0]["updateBorders"]
    assert "innerHorizontal" not in res["pOuter"]["requests"][0]["updateBorders"]
    assert [list(r.keys())[0] for r in res["pMerge"]["requests"]] == ["repeatCell", "mergeCells"]

    # clear & api ガード
    assert "repeatCell" in res["pClearFmt"]["requests"][0]
    assert res["pClearFmt"]["requests"][0]["repeatCell"]["fields"] == "userEnteredFormat"
    assert res["pClearValBlocked"] is None
    assert res["pClearAllBlocked"] is None
    assert res["pApiBlocked"] is None
    assert res["pClearValOk"]["requests"][0]["updateCells"]["fields"] == "userEnteredValue"
    assert res["pClearValConst"] is None
    assert res["pClearAllOk"]["requests"][0]["updateCells"]["fields"] == "userEnteredValue,userEnteredFormat"
    assert len(res["pApiOk"]["requests"]) == 1

    # write
    w_reqs = res["pWrite"]["requests"]
    assert len(w_reqs) == 4
    assert w_reqs[0]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"] == {"stringValue": "合計"}
    assert w_reqs[1]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"] == {"formulaValue": "=SUM(D4:D8)"}
    assert w_reqs[2]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"] == {"numberValue": 1200}
    assert w_reqs[3]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"] == {"boolValue": True}

    # filter / sort
    assert res["pFilterOn"]["requests"][0]["setBasicFilter"]["filter"]["range"]["startRowIndex"] == 2
    assert res["pFilterOff"]["requests"][0]["clearBasicFilter"]["sheetId"] == 111
    assert res["pSortDesc"]["requests"][0]["sortRange"]["sortSpecs"][0] == {"dimensionIndex": 3, "sortOrder": "DESCENDING"}
    assert res["pSortDesc"]["requests"][0]["sortRange"]["range"]["startRowIndex"] == 3  # ヘッダ行3除外、4行目(idx 3)から
    assert res["pSortAsc"]["requests"][0]["sortRange"]["sortSpecs"][0] == {"dimensionIndex": 0, "sortOrder": "ASCENDING"}

    # banding
    assert list(res["pBandAddReqs"][0].keys()) == ["deleteBanding"]
    assert res["pBandAddReqs"][0]["deleteBanding"]["bandedRangeId"] == 901
    assert list(res["pBandAddReqs"][1].keys()) == ["addBanding"]
    assert res["bandIdAfterAdd"] == [902]
    assert res["pBandRemReqs"][0]["deleteBanding"]["bandedRangeId"] == 902

    # sheet.*
    assert res["pTabColor"]["requests"][0]["updateSheetProperties"]["properties"]["tabColorStyle"]["rgbColor"]["red"] == 1
    assert res["pTabClear"]["requests"][0]["updateSheetProperties"]["properties"]["tabColorStyle"] is None
    assert res["pHide"]["requests"][0]["updateSheetProperties"]["properties"] == {"sheetId": 222, "hidden": True}
    assert res["pShow"]["requests"][0]["updateSheetProperties"]["properties"] == {"sheetId": 222, "hidden": False}
    assert res["pRenameReqs"][0]["updateSheetProperties"]["properties"] == {"sheetId": 111, "title": "売上集計"}
    assert res["curAfterRename"] == "売上集計"
    assert res["sidAfterRename"] == 111


@needs_node
def test_planner_to_direct_api_e2e_59_prompts():
    """補強した先打ち（ComboPlanner）が59パターンの日本語指示で直接APIルートまで貫通することを検証。"""
    files = combo_mod.build_combo_files()
    sidebar_html = {f["name"]: f["source"] for f in files}["ComboSidebar"]
    scripts = re.findall(r"<script>([\s\S]*?)</script>", sidebar_html)
    cases = [
        ("タイトルの文字を赤にして", "format", True),
        ("タイトルの文字色を青にして", "format", True),
        ("タイトルを太字にして", "format", True),
        ("タイトルを斜体にして", "format", True),
        ("タイトルの文字サイズを16ptにして", "format", True),
        ("ヘッダーの背景を薄い青にして", "format", True),
        ("ヘッダーの背景色をグレーにして", "format", True),
        ("見出しの文字を白にして太字にして", "format", True),
        ("見出しを中央揃えにして", "format", True),
        ("金額列を桁区切りにして", "format", True),
        ("金額列を円マーク表示にして", "format", True),
        ("A3:D3を中央揃えにして", "format", True),
        ("A1を左寄せにして", "format", True),
        ("D4:D8を右揃えにして", "format", True),
        ("A4:D8を折り返しにして", "format", True),
        ("A3からD8に罫線を引いて", "format", True),
        ("表に罫線を引いて", "format", True),
        ("A3:D8に罫線を引いて", "format", True),
        ("A3:D8に外枠だけつけて", "format", True),
        ("A3:D8の罫線を消して", "format", True),
        ("A1:D1を結合して", "format", True),
        ("A1:D1の結合を解除して", "format", True),
        ("ヘッダー行を固定して", "freeze", True),
        ("3行目まで固定して", "freeze", True),
        ("固定を解除して", "unfreeze", True),
        ("D列の幅を150にして", "width", True),
        ("A列の横幅を120にして", "width", True),
        ("B列とC列の幅を自動調整して", "width", True),
        ("D列の幅を中身に合わせて", "width", True),
        ("金額列を降順で並べ替えて", "sort", True),
        ("金額が高い順に並べ替えて", "sort", True),
        ("日付列を昇順でソートして", "sort", True),
        ("フィルターをつけて", "filter.on", True),
        ("表にフィルタを設定して", "filter.on", True),
        ("フィルターを解除して", "filter.off", True),
        ("オートフィルターを外して", "filter.off", True),
        ("交互に色をつけて", "banding.add", True),
        ("交互の背景色を青にして", "banding.add", True),
        ("交互の背景色を緑にして", "banding.add", True),
        ("交互の背景色を消して", "banding.remove", True),
        ("しましまを消して", "banding.remove", True),
        ("A4:D8の書式をクリアして", "clear.format", True),
        ("A4からD8の書式をリセットして", "clear.format", True),
        ("A4:D8の値を消して", "clear.values", False),
        ("A4:D8をすべてクリアして", "clear.all", False),
        ("A4:D8を白紙にして", "clear.all", False),
        ("A10に合計と書いて", "write", True),
        ("D10に=SUM(D4:D8)と入力して", "write", True),
        ("B10に500を入れて", "write", True),
        ("B2の値をテストに変えて", "write", True),
        ("シートの色を赤にして", "sheet.color", True),
        ("元データシートのタブの色を青にして", "sheet.color", True),
        ("タブの色をなしにして", "sheet.color", True),
        ("シート名を売上集計に変えて", "sheet.rename", True),
        ("元データシートの名前を「アーカイブ」に変えて", "sheet.rename", True),
        ("元データシートを非表示にして", "sheet.hide", True),
        ("元データシートを隠して", "sheet.hide", True),
        ("元データシートを再表示して", "sheet.show", True),
        ("C列を非表示にして", "cols.hide", True),
        ("A1の背景色を消して", "bg.clear", True),
        ("見出しの背景色を消して", "bg.clear", True),
        ("タイトルの背景色を消して", "bg.clear", True),
        ("A1セルの背景色を無しにして", "bg.clear", True),
        ("B4:D8の塗りつぶしを消して", "bg.clear", True),
    ]
    node_code = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function makeEl(id) {
  return {
    id, value: '', checked: false, disabled: false, textContent: '', innerHTML: '',
    style: {}, dataset: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, appendChild(c){ this.children.push(c); return c; },
    querySelectorAll(){ return []; }, querySelector(){ return null; }, focus(){}
  };
}
const elsMap = {};
const sandbox = {
  console, Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp, Error, parseInt, parseFloat, isNaN, isFinite,
  encodeURIComponent, decodeURIComponent, setTimeout: () => 0, clearTimeout: () => {},
  performance: { now: () => 100 },
  document: {
    getElementById(id){ if (!elsMap[id]) elsMap[id] = makeEl(id); return elsMap[id]; },
    createElement(tag){ return makeEl(tag); },
    querySelectorAll(){ return []; }, querySelector(){ return null; }, addEventListener(){}
  },
  window: { addEventListener() {} }, localStorage: { getItem(){ return null; }, setItem(){} }
};
sandbox.globalThis = sandbox;
for (const sc of input.scripts) vm.runInNewContext(sc, sandbox);
const dt = sandbox.__comboDirectTest;
dt.state.oauthToken = 'tok';
dt.state.target = { id: 'SS1', kind: 'sheet', name: '売上', sheet: '売上表' };
dt.state.curSheet = '売上表';
dt.state.sheets = ['売上表', '元データ'];
dt.state.sheetIdMap = { '売上表': 111, '元データ': 222 };
const tbl = {
  title_a1: 'A1', header_row: 3, first_col: 'A', last_col: 'D', data: '4-8', total_row: 9,
  columns: [{col:'A',name:'日付'},{col:'B',name:'部門'},{col:'C',name:'担当者'},{col:'D',name:'金額',number:true}]
};
dt.state.table = tbl;
dt.state.sheetSnapshot = { '売上表': { frozenRows: 0, frozenCols: 0, hideGridlines: false, bandedRangeIds: [901], vals: {}, cells: Array.from({ length: 30 }, () => Array.from({ length: 26 }, () => ({}))) } };
dt.els.chkBackup.checked = false;
dt.els.chkOk.checked = false;

const failures = [];
for (const [q, expShelf, expDirect] of input.cases) {
  const p = sandbox.ComboPlanner.plan(q, 'sheet', tbl, ['売上表', '元データ'], '売上表');
  const hitOk = !!(p && p.ops && p.ops.length && p.ops[0].shelf === expShelf);
  const direct = hitOk ? dt.buildDirectBatchUpdate(p.ops, '売上表') : null;
  if (!hitOk || (!!direct) !== expDirect) {
    failures.push({ q, expShelf, expDirect, gotOps: p && p.ops, reasons: p && p.reasons, missing: p && p.missing, directOk: !!direct });
  }
}
const bgReq = dt.buildDirectBatchUpdate([{ shelf: 'bg.clear', header: true }], '売上表');
// 取り消しは書く前の色に戻す（A1 は青だった）。写しが無ければ直結の道を使わない
const blue = { red: 0, green: 0, blue: 1 };
dt.state.sheetSnapshot['売上表'].cells[0][0] = { textFormat: { foregroundColorStyle: { rgbColor: blue } } };
const redReq = dt.buildDirectBatchUpdate([{ shelf: 'format', title: true, color: '赤' }], '売上表');
// 書く手：空でないセルには直結で書かない（GAS の道の上書きの止めに任せる）。空のセルなら、取り消しで空に戻す
dt.state.sheetSnapshot['売上表'].vals = { B2: { stringValue: '確定前' } };
const wFull = dt.buildDirectBatchUpdate([{ shelf: 'write', cells: { B2: 'テスト' } }], '売上表');
const wEmpty = dt.buildDirectBatchUpdate([{ shelf: 'write', cells: { A10: '合計' } }], '売上表');
dt.state.sheetSnapshot['売上表'].vals = {};
const saved = dt.state.sheetSnapshot['売上表'];
delete dt.state.sheetSnapshot['売上表'];
const noSnap = dt.buildDirectBatchUpdate([{ shelf: 'format', title: true, color: '赤' }], '売上表');
dt.state.sheetSnapshot['売上表'] = saved;
const extraDirect = {
  gridReq: dt.buildDirectBatchUpdate([{ shelf: 'sheet.gridlines', show: false }], '売上表'),
  rowHideReq: dt.buildDirectBatchUpdate([{ shelf: 'rows.hide', rows: [4, 5, 6] }], '売上表'),
  noteSetReq: dt.buildDirectBatchUpdate([{ shelf: 'note.set', range: 'B5', text: '確認済み' }], '売上表'),
  noteClrReq: dt.buildDirectBatchUpdate([{ shelf: 'note.clear', range: 'B5' }], '売上表'),
  valClrReq: dt.buildDirectBatchUpdate([{ shelf: 'validation.clear', range: 'C4:C8' }], '売上表'),
  widthAllNull: dt.buildDirectBatchUpdate([{ shelf: 'width', all_sheets: true }], '売上表'),
  sortColsNull: dt.buildDirectBatchUpdate([{ shelf: 'sort', cols: ['部門', '-金額'] }], '売上表'),
};
process.stdout.write(JSON.stringify({ total: input.cases.length, failures, bgReq, redUndo: redReq && redReq.undoRequests, noSnap, wFull, wEmptyUndo: wEmpty && wEmpty.undoRequests, extraDirect }));
"""
    res = _run_node_json(node_code, {"scripts": scripts, "cases": cases})
    assert res["total"] == 64
    assert res["failures"] == [], f"Failed cases: {res['failures']}"
    # 背景色を消す棚は、見出しの行に「背景色の欄だけを空で送る」1 本になる（色を塗らない）
    rc = [r["repeatCell"] for r in _find_requests(res["bgReq"]) if "repeatCell" in r]
    assert len(rc) == 1 and rc[0]["fields"] == "userEnteredFormat.backgroundColorStyle"
    assert "backgroundColorStyle" not in rc[0]["cell"]["userEnteredFormat"]
    assert rc[0]["range"] == {"sheetId": 111, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": 4}
    uc = res["redUndo"][0]["updateCells"]
    assert uc["fields"] == "userEnteredFormat.textFormat.foregroundColorStyle"
    assert uc["rows"][0]["values"][0]["userEnteredFormat"]["textFormat"]["foregroundColorStyle"] == {"rgbColor": {"red": 0, "green": 0, "blue": 1}}
    assert res["noSnap"] is None
    assert res["wFull"] is None
    assert res["wEmptyUndo"] == [{"updateCells": {"start": {"sheetId": 111, "rowIndex": 9, "columnIndex": 0}, "rows": [{"values": [{}]}], "fields": "userEnteredValue"}}]
    ed = res["extraDirect"]
    assert ed["gridReq"]["requests"][0]["updateSheetProperties"]["properties"]["gridProperties"]["hideGridlines"] is True
    assert ed["gridReq"]["undoRequests"][0]["updateSheetProperties"]["properties"]["gridProperties"]["hideGridlines"] is False
    assert ed["rowHideReq"]["requests"][0]["updateDimensionProperties"]["range"] == {"sheetId": 111, "dimension": "ROWS", "startIndex": 3, "endIndex": 6}
    assert ed["rowHideReq"]["undoRequests"][0]["updateDimensionProperties"]["properties"]["hiddenByUser"] is False
    assert ed["noteSetReq"]["requests"][0]["repeatCell"]["cell"]["note"] == "確認済み"
    assert ed["noteClrReq"]["requests"][0]["repeatCell"]["cell"] == {}
    assert ed["valClrReq"]["requests"][0]["setDataValidation"]["range"] == {"sheetId": 111, "startRowIndex": 3, "endRowIndex": 8, "startColumnIndex": 2, "endColumnIndex": 3}
    assert ed["widthAllNull"] is None and ed["sortColsNull"] is None


def _find_requests(obj):
    """buildDirectBatchUpdate の返り値から requests の並びを探す（形が入れ子でも拾う）"""
    if isinstance(obj, dict):
        if isinstance(obj.get("requests"), list):
            return obj["requests"]
        for v in obj.values():
            r = _find_requests(v)
            if r:
                return r
    return []





@needs_node
def test_engine_reports_only_new_errors_and_lost_formulas_after_ops():
    """撃った後の点検：撃つ前に無かったエラーだけ・式が減った列だけを返す（もとからあるエラーは数えない）"""
    eng = (HERE / "workspace_engine.gs").read_text(encoding="utf-8")
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const d = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = vm.createContext({ console });
vm.runInContext(d.eng, ctx);
vm.runInContext(`
function mkSheet(id, name, vals, forms) {
  return { getSheetId: () => id, getName: () => name, getLastRow: () => vals.length, getLastColumn: () => vals[0].length,
    getRange: () => ({ getValues: () => vals, getFormulas: () => forms }) };
}
function scan(sheets) { return errScan_({ getSheets: () => sheets }); }
var out = {};
// 1. もとから #N/A があり、撃った後に #REF! が 1 つ増えた
var b1 = scan([mkSheet(1, '集計', [['#N/A', 5]], [['=VLOOKUP(1,A:B,2,0)', '=SUM(B2:B9)']])]);
var a1 = scan([mkSheet(1, '集計', [['#N/A', '#REF!']], [['=VLOOKUP(1,A:B,2,0)', '=SUM(#REF!)']])]);
var c1 = { notes: [] }; errReport_(c1, [{ shelf: 'rows.insert' }], b1, a1); out.newErr = c1;
// 2. 何も増えない
var c2 = { notes: [] }; errReport_(c2, [{ shelf: 'write' }], b1, b1); out.none = c2;
// 3. 式の列が値に化けた（書式の棚以外・式が減ってよい棚でもない）
var b3 = scan([mkSheet(2, '明細', [[1], [2]], [['=1'], ['=2']])]);
var a3 = scan([mkSheet(2, '明細', [[1], [2]], [[''], ['']])]);
var c3 = { notes: [] }; errReport_(c3, [{ shelf: 'text.case' }], b3, a3); out.drop = c3;
var c4 = { notes: [] }; errReport_(c4, [{ shelf: 'formula.tovalue' }], b3, a3); out.dropOk = c4;
out.skipFormat = errScanNeeded_([{ shelf: 'format' }, { shelf: 'width' }]);
out.needWrite = errScanNeeded_([{ shelf: 'format' }, { shelf: 'write' }]);
__out = JSON.stringify(out);
`, ctx);
process.stdout.write(ctx.__out);
"""
    res = _run_node_json(node_code, {"eng": eng})
    assert res["newErr"]["newErrors"] == ["集計!B1 #REF!（=SUM(#REF!)）"]
    assert res["newErr"]["notes"][0].startswith("新しいエラー: 集計!B1 #REF!")
    assert res["none"]["newErrors"] == [] and res["none"]["notes"] == []
    assert res["drop"]["newErrors"] == ["明細 の A 列の式が 2 → 0 個"] and res["drop"]["notes"][0].startswith("式が減った")
    assert res["dropOk"]["newErrors"] == []
    assert res["skipFormat"] is False and res["needWrite"] is True


def test_addon_files_have_workspace_manifest_library_and_planner(tmp_path):
    """アドオン版：Sheets の Workspace アドオンの定義・大元ライブラリ・棚当てが揃い、つなぎコードに頼らない"""
    files = combo_mod.build_combo_addon_files("LIB_X", "7")
    by = {f["name"]: f for f in files}
    assert set(by) == {"appsscript", "コード", "ComboPlanner"}
    man = json.loads(by["appsscript"]["source"])
    assert man["addOns"]["sheets"]["homepageTrigger"]["runFunction"] == "onHome"
    assert man["dependencies"]["libraries"][0] == {"userSymbol": "shucomboengine", "libraryId": "LIB_X", "version": "7", "developmentMode": True}   # 大元を開発モードでつなぐ（combo push がすぐ届く・3ad4842）
    assert man["dependencies"]["enabledAdvancedServices"][0]["serviceId"] == "sheets"   # 操作窓の直結の道（Sheets API）に要る
    assert man["webapp"]["executeAs"] == "USER_ACCESSING"
    code = by["コード"]["source"]
    assert "{lib_symbol}" not in code and "shucomboengine.comboRunAsk" in code and "ComboPlanner.plan" in code
    assert "fastUndo: true" in code            # 取り消しのための記録を取る
    assert "getActiveSpreadsheet" in code      # シートごとの許可なしで今のシートを相手にする
    with pytest.raises(ValueError):
        combo_mod.build_combo_addon_files("", "1")


@needs_node
def test_addon_code_is_valid_javascript(tmp_path):
    files = combo_mod.build_combo_addon_files("LIB_X", "7")
    for f in files:
        if f["type"] != "SERVER_JS":
            continue
        p = tmp_path / (f["name"] + ".js")
        p.write_text(f["source"], encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert proc.returncode == 0, proc.stderr


def test_install_combo_addon_reuses_saved_project_and_records_it(tmp_path, monkeypatch):
    st = tmp_path / "state.json"
    st.write_text(json.dumps({"addon_sid": "ADDON1"}), encoding="utf-8")
    monkeypatch.setattr(combo_mod, "ensure_combo_engine_project", lambda **kw: ("LIB9", "15", []))
    # テスト実行で本番の Windows スタートアップを絶対に書き換えないことを保証
    called_autostart = []
    monkeypatch.setattr(combo_mod, "install_watch_autostart", lambda *a, **kw: called_autostart.append((a, kw)) or {"ok": True, "text": ""})
    class C:
        def __init__(self): self.put = []; self.dep = []
        def _put_content(self, sid, files): self.put.append((sid, [f["name"] for f in files]))
        def create_project(self, title): raise AssertionError("作り直さない")
        def deploy(self, sid, description="", deployment_id=None, fast=False):
            self.dep.append(deployment_id); return {"deploymentId": deployment_id or "DEPEXEC"}
    c = C()
    res = combo_mod.install_combo_addon(client=c, state_path=st, window_json=tmp_path / "w.json")
    assert res["scriptId"] == "ADDON1" and c.put[-1] == ("ADDON1", ["appsscript", "コード", "ComboPlanner"])
    assert called_autostart == []
    assert "入れ直し" in res["next"]
    assert res["window"] == "https://script.google.com/macros/s/DEPEXEC/exec"     # サイドパネルの中に入れられる正式な番地
    assert c.dep == [None, "DEPEXEC"]                                              # 初回はデプロイを作り、番地を書いた版でもう一度上げる


def test_direct_only_watcher_does_not_fail_on_unknown_script_id():
    class C:
        def resolve_script_id(self, target):
            raise ValueError(f"not found: {target}")
    w = combo_mod.ComboPostboxWatcher("UNKNOWN_ID", client=C(), direct_only=True)
    assert w.sid == "UNKNOWN_ID"


def test_repair_local_bindings_if_stale_fixes_moved_vbs_only(tmp_path, monkeypatch):
    if combo_mod.os.name != "nt":
        return
    fake_appdata = tmp_path / "appdata"
    startup = fake_appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    vbs = startup / "GASコンボ受け手.vbs"
    # 古いフォルダを指す壊れた VBS を置く
    vbs.write_text('CreateObject("WScript.Shell").Run """pyw"" ""C:\\OldFolder\\gas.py"" combo watch OLD", 0, False\r\n', encoding="utf-16")
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setattr(combo_mod, "_load_combo_state", lambda *a, **kw: ({"addon_sid": "REAL_SID"}, tmp_path / "s.json"))
    # winreg は未登録扱いにモックして実レジストリを触らない
    import winreg
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    res = combo_mod.repair_local_bindings_if_stale()
    assert res["repaired"] == ["startup_vbs"]
    fixed = vbs.read_text(encoding="utf-16")
    assert str(combo_mod.HERE / "gas.py") in fixed and "REAL_SID" in fixed
    # 2 回目はすでに一致しているため修復されない
    assert combo_mod.repair_local_bindings_if_stale()["repaired"] == []


def test_direct_watch_server_blocks_external_origin_and_allows_fixed_ext(monkeypatch):
    import threading
    import time
    import urllib.error
    import urllib.request
    # 空きポートで直結サーバーを一時起動して CORS / Origin 防御を検証
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(combo_mod, "COMBO_WATCH_PORT", port)
    class C:
        def resolve_script_id(self, target): return target
    w = combo_mod.ComboPostboxWatcher("TEST_DIRECT", client=C(), direct_only=True)
    th = threading.Thread(target=w.watch, kwargs={"direct_only": True}, daemon=True)
    th.start()
    try:
        # 起動待ち
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=0.5).read()
                break
            except Exception:
                time.sleep(0.05)
        # 1. 悪意ある外部サイト Origin は OPTIONS / GET / POST すべて 403 で拒否
        for method, path in (("OPTIONS", "/resolve"), ("GET", "/stop"), ("POST", "/resolve")):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=b"{}" if method == "POST" else None,
                method=method,
                headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=2)
                raise AssertionError(f"{method} {path} should have been rejected with 403")
            except urllib.error.HTTPError as e:
                assert e.code == 403
                assert e.headers.get("Access-Control-Allow-Origin") is None
        # 2. 固定拡張機能 Origin のみ許可
        ext_origin = f"chrome-extension://{combo_mod.EXT_FIXED_ID}"
        req_ok = urllib.request.Request(
            f"http://127.0.0.1:{port}/ping",
            method="GET",
            headers={"Origin": ext_origin},
        )
        with urllib.request.urlopen(req_ok, timeout=2) as r:
            assert r.status == 200
            assert r.headers.get("Access-Control-Allow-Origin") == ext_origin
    finally:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/stop", timeout=2).read()
        except Exception:
            pass
        th.join(timeout=3)


def test_create_combo_template_creates_and_reuses_template(tmp_path, monkeypatch):
    """combo template 初回作成・2回目入れ直し・--new 作り直し・CLI 入口を検証。"""
    st = tmp_path / ".combo_state.json"
    monkeypatch.setattr(combo_mod, "ensure_combo_engine_project", lambda **kw: ("LIB_TMPL_1", "18", []))

    created_sheets = []
    created_projects = []
    puts = []

    class Resp:
        def __init__(self, code, data):
            self.status_code = code
            self._data = data
            self.text = json.dumps(data)
        def json(self):
            return self._data

    class FakeClient:
        def _headers(self):
            return {"Authorization": "Bearer dummy"}
        def resolve_script_id(self, x):
            return x
        def set_alias(self, name, sid):
            pass
        def _request_with_retry(self, method, url, **kw):
            if method == "POST" and url.endswith("/drive/v3/files"):
                idx = len(created_sheets) + 1
                ss_id = f"TMPL_SS_{idx}"
                name = kw["json"]["name"]
                created_sheets.append((ss_id, name))
                return Resp(200, {"id": ss_id, "name": name})
            if method == "GET" and "/drive/v3/files/" in url:
                fid = url.rsplit("/", 1)[-1].split("?")[0]
                return Resp(200, {"id": fid, "name": "GASコンボ テンプレート"})
            return Resp(404, {})
        def create_project(self, title, parent_id=""):
            idx = len(created_projects) + 1
            sid = f"TMPL_SID_{idx}"
            created_projects.append((title, parent_id, sid))
            return {"scriptId": sid}
        def _put_content(self, sid, files):
            puts.append((sid, files))

    client = FakeClient()

    # 1. 初回: 新規シート作成 + つなぎ配置 + 3項目返却
    res1 = combo_mod.create_combo_template(client=client, state_path=st)
    assert res1["created"] is True
    assert res1["url"] == "https://docs.google.com/spreadsheets/d/TMPL_SS_1/edit"
    assert res1["copy_url"] == "https://docs.google.com/spreadsheets/d/TMPL_SS_1/copy"
    assert res1["engineVersion"] == "18"
    assert len(created_sheets) == 1 and created_sheets[0][1] == "GASコンボ テンプレート"
    assert len(created_projects) == 1 and created_projects[0][1] == "TMPL_SS_1"
    pushed_map = {f["name"]: f["source"] for f in puts[-1][1]}
    manifest = json.loads(pushed_map["appsscript"])
    assert manifest["dependencies"]["libraries"][0]["libraryId"] == "LIB_TMPL_1"
    assert manifest["dependencies"]["enabledAdvancedServices"][0]["userSymbol"] == "Sheets"
    assert "shucomboengine.comboRunAsk" in pushed_map["コード"]

    # 2. 2回目: 新規作成せず、覚えたテンプレートに入れ直す
    res2 = combo_mod.create_combo_template(client=client, state_path=st)
    assert res2["created"] is False
    assert res2["url"] == res1["url"]
    assert res2["copy_url"] == res1["copy_url"]
    assert len(created_sheets) == 1
    assert len(created_projects) == 1
    assert len(puts) == 2 and puts[-1][0] == "TMPL_SID_1"

    # 3. --new CLI: 新しいテンプレートを作り直す
    with patch("gas_client.GasClient", return_value=client), \
         patch.object(combo_mod, "COMBO_ENGINE_STATE_PATH", st):
        rc = combo_mod._run_cli(["template", "--new", "--title", "カスタムテンプレート"])
        assert rc == 0
    assert len(created_sheets) == 2 and created_sheets[1] == ("TMPL_SS_2", "カスタムテンプレート")
    assert len(created_projects) == 2 and created_projects[1][1] == "TMPL_SS_2"


def test_reload_tools_rebinds_server_helpers():
    """reload_tools がサーバー本体の下請け（combo の振り分け）も読み直し、再起動なしで combo phrase が効く。"""
    import gas_mcp_server as m
    m._handle_combo_command = lambda args, client: "old"
    m.reload_tools()
    assert "combo phrase" in m._handle_combo_command(["phrase"], None)


def test_addon_files_include_drive_scripts_scope_and_quick_rpcs():
    """Chrome拡張アドオン版に drive.scripts 権限と マイマクロ系 RPC 転送関数が含まれること。"""
    files = combo_mod.build_combo_addon_files("LIB_QUICK", "39")
    by_name = {f["name"]: f["source"] for f in files}
    manifest = json.loads(by_name["appsscript"])
    assert "https://www.googleapis.com/auth/drive.scripts" in manifest["oauthScopes"]
    code = by_name["コード"]
    for fn in (
        "comboQuickList",
        "comboQuickRun",
        "comboQuickMake",
        "comboQuickGetFn",
        "comboQuickSaveFn",
        "comboQuickAddFn",
        "comboQuickDeleteFn",
        "comboQuickSaveOrder",
        "comboQuickSavePins",
        "comboQuickSaveSteps",
        "comboQuickAiSave",
        "comboCall",
    ):
        assert f"function {fn}(" in code
        assert f"shucomboengine.{fn}(" in code


def test_combo_lite_catalog_trims_defaults_and_has_list_tab():
    """combo_lite=True のカタログ args 既定値削減と 6タブ・一覧 UI の組み込みを検証。"""
    files = combo_mod.build_combo_files(combo_lite=True)
    sidebar = next(f["source"] for f in files if f["name"] == "ComboSidebar")
    m = re.search(r"var COMBO_CATALOG_DATA = (\{.*?\});\s*</script>", sidebar, flags=re.DOTALL)
    assert m, "COMBO_CATALOG_DATA が ComboSidebar 内に見つかりません"
    cat = json.loads(m.group(1))
    assert len(cat.get("shelves") or []) >= 149
    for sh in cat["shelves"]:
        for arg in sh.get("args") or []:
            if isinstance(arg, dict):
                assert arg.get("req") is not False, f"{sh['name']} arg has req=False"
                assert "default" not in arg or arg["default"] is not None, f"{sh['name']} arg has default=None"
                assert "choices" not in arg or arg["choices"] is not None, f"{sh['name']} arg has choices=None"
    for marker in (
        'data-tab="list"',
        'id="pane-list"',
        'id="quickFilterBar"',
        'id="quickEditModal"',
        'id="quickModalTabs"',
        'id="tabQuickModalChat"',
        'id="tabQuickModalCode"',
        'id="quickChatLog"',
        '💬 AI会話',
        '📄 コード',
        'id="btnQuickAi"',
        'id="btnSaveSteps"',
        "gascombo_quick_cache_v1",
        "決定して保存",
        "previewOnly: true",
        "gemini_hydrogen",
        "gemini_neon",
        "postboxOnly = true",
        "#pane-list {",
    ):
        assert marker in sidebar, f"ComboSidebar missing marker: {marker}"
    assert "gemini_flash" not in sidebar
    assert "quickCodeDetails" not in sidebar, "quickCodeDetails must be removed so code stays visible"
    assert "18766/kick" not in sidebar and "GAS_COMBO_KICK_WATCH" not in sidebar
    sp_js = (combo_mod.HERE / "ws_browser_ext" / "sidepanel.js").read_text(encoding="utf-8")
    assert "isAllowedSidepanelOrigin" in sp_js and "18766/kick" not in sp_js and "GAS_COMBO_KICK_WATCH" not in sp_js


def test_combo_server_webapp_mymacro_proxy_and_sheetcopy_undo():
    """WebApp環境(getActive()===null)での Proxy 経由マイマクロ実行・全シート退避アンドゥ・CRUD を検証。"""
    files = combo_mod.build_combo_files(combo_lite=True)
    by_name = {f["name"]: f["source"] for f in files}
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const userProps = {}, scriptProps = {}, userCache = {};
const driveFiles = {};
let driveSeq = 0;

function makeSheet(name, initGrid) {
  const rows = initGrid.map(r => r.slice());
  const weights = rows.map(r => r.map(() => 'normal'));
  const bgs = rows.map(r => r.map(() => '#ffffff'));
  let hidden = false, frozenR = 0, frozenC = 0;
  function parseA1(a1) {
    const parts = String(a1).toUpperCase().split(':');
    const c2n = (s) => { let n = 0; for (let i=0;i<s.length;i++) n = n*26 + (s.charCodeAt(i)-64); return n; };
    const p = (s) => { const m = s.match(/^([A-Z]+)(\d+)$/); return [parseInt(m[2],10), c2n(m[1])]; };
    const [r1, c1] = p(parts[0]);
    const [r2, c2] = parts[1] ? p(parts[1]) : [r1, c1];
    return [r1, c1, r2 - r1 + 1, c2 - c1 + 1];
  }
  function mkRg(r, c, nr, nc) {
    const apply = (arr, val) => {
      for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j] = Array.isArray(val) ? val[i][j] : val;
    };
    const rg = {
      getRow: () => r, getColumn: () => c, getNumRows: () => nr, getNumColumns: () => nc,
      getValues: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc)),
      getDisplayValues: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc).map(String)),
      getFormulas: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc).map(() => '')),
      getFontWeight: () => weights[r-1][c-1],
      setFontWeight: (w) => { apply(weights, w); return rg; },
      setBackground: (bg) => { apply(bgs, bg); return rg; },
      clear: () => { apply(rows, ''); apply(weights, 'normal'); apply(bgs, '#ffffff'); return rg; },
      breakApart: () => rg, clearDataValidations: () => rg,
      copyTo: (dst) => {
        const dR = dst.getRow(), dC = dst.getColumn();
        for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) {
          dst._sheet._rows[dR-1+i][dC-1+j] = rows[r-1+i][c-1+j];
          dst._sheet._weights[dR-1+i][dC-1+j] = weights[r-1+i][c-1+j];
          dst._sheet._bgs[dR-1+i][dC-1+j] = bgs[r-1+i][c-1+j];
        }
      },
      _sheet: shObj
    };
    return rg;
  }
  const shObj = {
    _rows: rows, _weights: weights, _bgs: bgs,
    getSheetId: () => name === '売上' ? 10 : 20,
    getName: () => name,
    setName: (n) => { name = n; },
    hideSheet: () => { hidden = true; },
    isSheetHidden: () => hidden,
    getMaxRows: () => rows.length,
    getMaxColumns: () => rows[0].length,
    getLastRow: () => rows.length,
    getLastColumn: () => rows[0].length,
    getFrozenRows: () => frozenR,
    getFrozenColumns: () => frozenC,
    setFrozenRows: (n) => { frozenR = n; },
    setFrozenColumns: (n) => { frozenC = n; },
    getBandings: () => [],
    getFilter: () => null,
    getDataRange: () => mkRg(1, 1, rows.length, rows[0].length),
    getRange: (a, b, c, d) => {
      if (typeof a === 'string') { const [r, co, nr, nc] = parseA1(a); return mkRg(r, co, nr, nc); }
      return mkRg(a, b, c || 1, d || 1);
    },
    getRangeList: (a1s) => {
      const rgs = a1s.map(x => shObj.getRange(x));
      return {
        getRanges: () => rgs,
        setFontWeight: (w) => rgs.forEach(r => r.setFontWeight(w)),
        setBackground: (bg) => rgs.forEach(r => r.setBackground(bg))
      };
    },
    copyTo: (targetSs) => {
      const copy = makeSheet(name + '_copy', rows);
      for (let i=0;i<rows.length;i++) {
        copy._weights[i] = weights[i].slice();
        copy._bgs[i] = bgs[i].slice();
      }
      targetSs._addSheet(copy);
      return copy;
    }
  };
  return shObj;
}

const mainSh = makeSheet('売上', [
  ['部門', '金額'],
  ['', ''],
  ['品名', '金額'],
  ['営業', 100],
  ['開発', 200]
]);
const sheetsMap = { '売上': mainSh };
const mockSs = {
  _addSheet: (s) => { sheetsMap[s.getName()] = s; },
  getId: () => 'MOCK_WEB_SS',
  getName: () => 'WebAppテスト',
  getSheets: () => Object.values(sheetsMap),
  getSheetByName: (n) => Object.values(sheetsMap).find(s => s.getName() === n) || null,
  getActiveSheet: () => mainSh,
  deleteSheet: (s) => { Object.keys(sheetsMap).forEach(k => { if (sheetsMap[k] === s || sheetsMap[k].getName() === s.getName()) delete sheetsMap[k]; }); }
};

const ctx = vm.createContext({
  SpreadsheetApp: {
    getActive: () => null,
    getActiveSpreadsheet: () => null,
    openById: (id) => id === 'MOCK_WEB_SS' ? mockSs : null,
    flush: () => {},
    CopyPasteType: { PASTE_COLUMN_WIDTHS: 'PASTE_COLUMN_WIDTHS' }
  },
  ScriptApp: { getOAuthToken: () => 'TOK_MOCK' },
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...userProps }),
      getProperty: (k) => (k in userProps ? userProps[k] : null),
      setProperty: (k, v) => { userProps[k] = String(v); },
      deleteProperty: (k) => { delete userProps[k]; }
    }),
    getScriptProperties: () => ({
      getProperty: (k) => (k in scriptProps ? scriptProps[k] : null),
      setProperty: (k, v) => { scriptProps[k] = String(v); },
      deleteProperty: (k) => { delete scriptProps[k]; }
    })
  },
  CacheService: {
    getUserCache: () => ({
      get: (k) => (k in userCache ? userCache[k] : null),
      put: (k, v) => { userCache[k] = String(v); },
      remove: (k) => { delete userCache[k]; }
    }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  DriveApp: {
    getFileById: (id) => {
      const f = driveFiles[id];
      if (!f) throw new Error('missing');
      return { getId: () => id, getName: () => f.name, isTrashed: () => false, getLastUpdated: () => ({ getTime: () => f.stamp }) };
    },
    searchFiles: () => {
      const vals = Object.values(driveFiles);
      let idx = 0;
      return { hasNext: () => idx < vals.length, next: () => { const f = vals[idx++]; return { getId: () => f.id, getLastUpdated: () => ({ getTime: () => f.stamp }) }; } };
    }
  },
  UrlFetchApp: {
    fetch: (url, o) => {
      if (o.method === 'post' && url.includes('/upload/drive/v3/files')) {
        const body = String(o.payload || '');
        const idx = body.indexOf('application/vnd.google-apps.script+json');
        const jsonPart = body.slice(body.indexOf('{', idx), body.lastIndexOf('}') + 1);
        const id = 'MY_' + (++driveSeq);
        driveFiles[id] = { id, name: 'GASクイック マイマクロ', content: JSON.parse(jsonPart), stamp: Date.now() };
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id }) };
      }
      if (o.method === 'get' && url.includes('/export?')) {
        const m = url.match(/\/files\/([^/]+)\/export/);
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify(driveFiles[m[1]].content) };
      }
      if (o.method === 'patch' && url.includes('/upload/drive/v3/files/')) {
        const m = url.match(/\/files\/([^?]+)/);
        driveFiles[m[1]].content = JSON.parse(o.payload);
        driveFiles[m[1]].stamp = Date.now() + 10;
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id: m[1] }) };
      }
      return { getResponseCode: () => 404, getContentText: () => 'not found' };
    }
  },
  Date, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Infinity, Proxy, parseInt, parseFloat, encodeURIComponent, decodeURIComponent
});
ctx.globalThis = ctx;
vm.runInContext(payload.engine + '\n' + payload.server, ctx);

const made = ctx.comboQuickMake({});
const initRes = ctx.comboInit({ targetId: 'MOCK_WEB_SS', sheet: '売上', selection: 'A4:B4', includeQuick: true, wantCodes: true });
const run1 = ctx.comboQuickRun({ targetId: 'MOCK_WEB_SS', sheet: '売上', selection: 'A4:B4', name: '選んだ所を太字', backup: true });
const weightAfterRun = mainSh._weights[3][0];
const bkExists = !!mockSs.getSheetByName('_GASクイックの控え');
const undoRes = ctx.comboUndo({ targetId: 'MOCK_WEB_SS' });
const weightAfterUndo = mainSh._weights[3][0];
const bkGone = !mockSs.getSheetByName('_GASクイックの控え');

const added = ctx.comboQuickAddFn({ code: '// テスト\nfunction セル色() {\n  SpreadsheetApp.getActiveRange().setBackground("#fff2cc");\n}' });
const gotFn = ctx.comboQuickGetFn({ name: 'セル色' });
const savedFn = ctx.comboQuickSaveFn({ name: 'セル色', code: '// テスト更新\nfunction セル色() {\n  SpreadsheetApp.getActiveRange().setBackground("#fef08a");\n}' });
const stepsSaved = ctx.comboQuickSaveSteps({ name: '朝一整形', steps: ['見出しを黄色に', '列幅を自動調整'] });
const pinsRes = ctx.comboQuickSavePins({ pins: { 'my:セル色': 1 } });
const ordRes = ctx.comboQuickSaveOrder({ kind: 'my', names: ['セル色'], targetId: 'MOCK_WEB_SS' });
const callRes = ctx.comboCall('comboQuickList', { targetId: 'MOCK_WEB_SS' });
const delRes = ctx.comboQuickDeleteFn({ name: 'セル色' });

console.log(JSON.stringify({
  madeOk: made.ok, initQuickCount: initRes.quick.my.length,
  runOk: run1.ok, snapped: run1.snapped, weightAfterRun, bkExists,
  undoOk: undoRes.ok, weightAfterUndo, bkGone,
  addedOk: added.ok, gotOk: gotFn.ok, savedOk: savedFn.ok, stepsOk: stepsSaved.ok,
  pinsOk: pinsRes.ok, ordOk: ordRes.ok, callOk: callRes.ok, delOk: delRes.ok
}));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps({"engine": by_name["Engine"], "server": by_name["ComboServer"]}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\nstdout: {proc.stdout}"
    res = json.loads(proc.stdout.strip())
    assert res["madeOk"] and res["initQuickCount"] == 3
    assert res["runOk"] and res["snapped"] and res["weightAfterRun"] == "bold" and res["bkExists"]
    assert res["undoOk"] and res["weightAfterUndo"] == "normal" and res["bkGone"]
    assert all(res[k] for k in ("addedOk", "gotOk", "savedOk", "stepsOk", "pinsOk", "ordOk", "callOk", "delOk"))


def test_combo_server_ai_mymacro_save_and_postbox():
    """comboQuickAiSave の API直結(構文リトライ＋自動保存＋prevCode)と郵便受け(Deliverリトライ＋needsClientSave)を検証。"""
    files = combo_mod.build_combo_files(combo_lite=True)
    by_name = {f["name"]: f["source"] for f in files}
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const userProps = {}, scriptProps = {}, userCache = {};
const driveFiles = {};
let driveSeq = 0;
let geminiAttempt = 0;
let claudeAttempt = 0;
let forceDriveForbidden = false;
let openByIdCalls = 0;

const mainSh = {
  getSheetId: () => 1,
  getName: () => '売上',
  getLastRow: () => 4,
  getLastColumn: () => 2,
  getDataRange: () => ({
    getValues: () => [['部門', '金額'], ['営業', 100], ['開発', 200], ['合計', 300]],
    getDisplayValues: () => [['部門', '金額'], ['営業', '100'], ['開発', '200'], ['合計', '300']],
    getFormulas: () => [['', ''], ['', ''], ['', ''], ['', '']],
  }),
  getRange: () => ({ getA1Notation: () => 'A1' }),
};
const mockSs = {
  getId: () => 'SS_AI_1',
  getName: () => 'AI検証表',
  getSheets: () => [mainSh],
  getSheetByName: (n) => n === '売上' ? mainSh : null,
  getActiveSheet: () => mainSh,
};

const ctx = vm.createContext({
  SpreadsheetApp: {
    getActive: () => null,
    getActiveSpreadsheet: () => null,
    openById: () => { openByIdCalls++; return mockSs; },
    flush: () => {},
  },
  ScriptApp: { getOAuthToken: () => 'TOK_AI' },
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...userProps }),
      getProperty: (k) => (k in userProps ? userProps[k] : null),
      setProperty: (k, v) => { userProps[k] = String(v); },
      deleteProperty: (k) => { delete userProps[k]; }
    }),
    getScriptProperties: () => ({
      getProperty: (k) => (k in scriptProps ? scriptProps[k] : null),
      setProperty: (k, v) => { scriptProps[k] = String(v); },
      deleteProperty: (k) => { delete scriptProps[k]; }
    })
  },
  CacheService: {
    getUserCache: () => ({
      get: (k) => (k in userCache ? userCache[k] : null),
      put: (k, v) => { userCache[k] = String(v); },
      remove: (k) => { delete userCache[k]; }
    }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  DriveApp: {
    getFileById: (id) => {
      const f = driveFiles[id];
      if (!f) throw new Error('missing');
      return { getId: () => id, getName: () => f.name, isTrashed: () => false, getLastUpdated: () => ({ getTime: () => f.stamp }) };
    },
    searchFiles: () => {
      const vals = Object.values(driveFiles);
      let idx = 0;
      return { hasNext: () => idx < vals.length, next: () => { const f = vals[idx++]; return { getId: () => f.id, getLastUpdated: () => ({ getTime: () => f.stamp }) }; } };
    }
  },
  UrlFetchApp: {
    fetch: (url, o) => {
      if (url.includes('generativelanguage.googleapis.com')) {
        if (String(o.payload || '').includes('このコード改善点の相談をして')) {
          return {
            getResponseCode: () => 200,
            getContentText: () => JSON.stringify({ candidates: [{ content: { parts: [{ text: JSON.stringify({ action: 'reply', message: '案1: 背景も変える\n案2: 完了メッセージを追加する' }) }] } }] })
          };
        }
        geminiAttempt++;
        const jsonOut = geminiAttempt === 1
          ? { action: 'mymacro', code: 'function brokenSyntax( {' }
          : { action: 'mymacro', code: "// 黄背景\n// 棚: 黄色にする\nfunction セルを黄に() {\n  SpreadsheetApp.getActiveRange().setBackground('#fef08a');\n}", note: '黄色に変更' };
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({ candidates: [{ content: { parts: [{ text: JSON.stringify(jsonOut) }] } }] })
        };
      }
      if (url.includes('api.anthropic.com/v1/models')) {
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({ data: [{ id: 'claude-sonnet-5-5' }, { id: 'claude-haiku-5-5' }] })
        };
      }
      if (url.includes('generativelanguage.googleapis.com/v1beta/models?')) {
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({
            models: [
              { name: 'models/gemini-3.8-flash', supportedGenerationMethods: ['generateContent'] },
              { name: 'models/gemini-4-hydrogen', supportedGenerationMethods: ['generateContent'] }
            ]
          })
        };
      }
      if (url.includes('api.anthropic.com')) {
        claudeAttempt++;
        const jsonOut = { action: 'mymacro', code: "// 黄背景(濃)\n// 棚: 濃い黄色\nfunction セルを黄に() {\n  SpreadsheetApp.getActiveRange().setBackground('#fff2cc');\n}", note: '背景色変更' };
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({ content: [{ text: JSON.stringify(jsonOut) }] })
        };
      }
      if (forceDriveForbidden && (o.method === 'patch' || o.method === 'post')) {
        return { getResponseCode: () => 403, getContentText: () => 'Insufficient Permission: drive.scripts required' };
      }
      if (o.method === 'post' && url.includes('/upload/drive/v3/files')) {
        const body = String(o.payload || '');
        const idx = body.indexOf('application/vnd.google-apps.script+json');
        const jsonPart = body.slice(body.indexOf('{', idx), body.lastIndexOf('}') + 1);
        const id = 'MY_' + (++driveSeq);
        driveFiles[id] = { id, name: 'GASクイック マイマクロ', content: JSON.parse(jsonPart), stamp: Date.now() };
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id }) };
      }
      if (o.method === 'get' && url.includes('/export?')) {
        const m = url.match(/\/files\/([^/]+)\/export/);
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify(driveFiles[m[1]].content) };
      }
      if (o.method === 'patch' && url.includes('/upload/drive/v3/files/')) {
        const m = url.match(/\/files\/([^?]+)/);
        driveFiles[m[1]].content = JSON.parse(o.payload);
        driveFiles[m[1]].stamp = Date.now() + 10;
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id: m[1] }) };
      }
      return { getResponseCode: () => 404, getContentText: () => 'not found' };
    }
  },
  Date, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Infinity, parseInt, parseFloat, encodeURIComponent, decodeURIComponent
});
ctx.globalThis = ctx;
vm.runInContext(payload.engine + '\n' + payload.server, ctx);

// 1. Gemini API モード: 構文エラーで 1 回自動リトライし自動保存
ctx.comboSaveConfig({ aiMode: 'api_gemini', aiModel: 'gemini-2.5-flash', apiKey: 'AIzaTEST_GKEY' });
const gRes = ctx.comboQuickAiSave({ mode: 'add', prompt: '選んだセルを黄色に', targetId: 'SS_AI_1', sheet: '売上', selection: 'B2' });
const gAttemptAfter1 = geminiAttempt;

// 2. Claude API モード (edit): prevCode を返しつつ上書き保存
ctx.comboSaveConfig({ aiMode: 'api_claude', aiModel: 'sonnet', apiKey: 'sk-ant-TEST_CKEY' });
const cRes = ctx.comboQuickAiSave({ mode: 'edit', name: 'セルを黄に', prompt: '少し薄くして', targetId: 'SS_AI_1', sheet: '売上', selection: 'B2' });
const cAttemptAfter2 = claudeAttempt;

// 3. 郵便受けモード: 未稼働時は案内を返して止まり、稼働中は enqueue -> retryable失敗 -> 再送で保存完了 -> needsClientSave フォールバック
ctx.comboSaveConfig({ aiMode: 'postbox', aiModel: 'sonnet' });
const pbNotListening = ctx.comboQuickAiSave({ mode: 'add', prompt: '見出し太字にする', targetId: 'SS_AI_1', sheet: '売上', selection: 'A1:B1' });
ctx.comboPostboxPoll();
const pbReq = ctx.comboQuickAiSave({ mode: 'add', prompt: '見出し太字にする', targetId: 'SS_AI_1', sheet: '売上', selection: 'A1:B1' });
const poll1 = ctx.comboPostboxPoll();
const dBad = ctx.comboPostboxDeliver({ reqId: pbReq.reqId, kind: 'mymacro', action: 'mymacro', code: 'function broken(){' });
const dGood = ctx.comboPostboxDeliver({
  reqId: pbReq.reqId, kind: 'mymacro', mode: 'add', ssId: 'SS_AI_1', ask: '見出し太字にする',
  action: 'mymacro', code: "// 太字\nfunction 見出し太字にする() {\n  SpreadsheetApp.getActiveRange().setFontWeight('bold');\n}", note: '太字化'
});
const sidePoll = ctx.comboPollSelection({ targetId: 'SS_AI_1', sheet: '売上' });

forceDriveForbidden = true;
const pbReq2 = ctx.comboQuickAiSave({ mode: 'add', prompt: '文字赤に', targetId: 'SS_AI_1', sheet: '売上', selection: 'A1' });
ctx.comboPostboxPoll();
const dClientFallback = ctx.comboPostboxDeliver({
  reqId: pbReq2.reqId, kind: 'mymacro', mode: 'add', ssId: 'SS_AI_1', ask: '文字赤に',
  action: 'mymacro', code: "// 赤文字\nfunction 赤文字にする() {\n  SpreadsheetApp.getActiveRange().setFontColor('#ff0000');\n}"
});
const sidePoll2 = ctx.comboPollSelection({ targetId: 'SS_AI_1', sheet: '売上' });

// 4. previewOnly: true (API 直結 & 郵便受け) - 重複名/構文リトライ後に Drive 未保存のまま code を返すこと
forceDriveForbidden = false;
const driveCountBeforePreview = Object.keys(driveFiles).length;
const driveSnapshotBeforePreview = JSON.stringify(driveFiles);
ctx.comboSaveConfig({ aiMode: 'api_claude', aiModel: 'sonnet', apiKey: 'sk-ant-TEST_CKEY' });
// 'セルを黄に' は既に登録済み。add + previewOnly で重複名リトライの挙動を検証するため一旦既存の Gemini 側で試す
const pvApiDup = ctx.comboQuickAiSave({ mode: 'add', previewOnly: true, prompt: 'セルを黄に（別名に）', targetId: 'SS_AI_1', sheet: '売上', selection: 'B2' });
ctx.comboSaveConfig({ aiMode: 'api_gemini', aiModel: 'gemini-2.5-flash', apiKey: 'AIzaTEST_GKEY' });
geminiAttempt = 0; // geminiAttempt===1 は構文エラー -> 2回目は 'セルを黄に' (既存名と重複！) -> リトライ後も同名なのでエラー確認
const pvApiDupErr = ctx.comboQuickAiSave({ mode: 'add', previewOnly: true, prompt: '重複チェック', targetId: 'SS_AI_1', sheet: '売上', selection: 'B2' });
// edit + previewOnly は同名でも OK、Drive へ書き込まないこと
const pvApiEditOk = ctx.comboQuickAiSave({ mode: 'edit', previewOnly: true, name: 'セルを黄に', code: "// prev\nfunction セルを黄に() {}", prompt: '修正案を出して', targetId: 'SS_AI_1', sheet: '売上', selection: 'B2' });

ctx.comboSaveConfig({ aiMode: 'postbox', aiModel: 'sonnet' });
ctx.comboPostboxPoll();
const pbPvReq = ctx.comboQuickAiSave({ mode: 'add', previewOnly: true, prompt: '背景を青に', code: '// draft\nfunction 背景を青に() {}', targetId: 'SS_AI_1', sheet: '売上', selection: 'C2' });
const pollPv = ctx.comboPostboxPoll();
const dPvDup = ctx.comboPostboxDeliver({ reqId: pbPvReq.reqId, kind: 'mymacro', action: 'mymacro', code: "function セルを黄に() {}" });
const dPvOk = ctx.comboPostboxDeliver({
  reqId: pbPvReq.reqId, kind: 'mymacro', mode: 'add', previewOnly: true, existingNames: ['セルを黄に'],
  ssId: 'SS_AI_1', ask: '背景を青に', action: 'mymacro',
  code: "// 青背景\nfunction 背景を青にする() {\n  SpreadsheetApp.getActiveRange().setBackground('#cfe2ff');\n}", note: '青色案'
});
const sidePollPv = ctx.comboPollSelection({ targetId: 'SS_AI_1', sheet: '売上' });

// 5. 会話・相談フロー (action: "reply" 正常返却 + history 伝搬 + 説明内コード例で誤昇格しない)
ctx.comboSaveConfig({ aiMode: 'api_gemini', aiModel: 'gemini-2.5-flash', apiKey: 'AIzaTEST_GKEY' });
const chatApiReply = ctx.comboQuickAiSave({
  mode: 'edit', previewOnly: true, name: 'セルを黄に', code: '// cur\nfunction セルを黄に() {}',
  prompt: 'このコード改善点の相談をして', history: [{ role: 'user', text: '前の確認' }, { role: 'ai', text: '承知しました' }],
  targetId: 'SS_AI_1', sheet: '売上', selection: 'B2'
});
ctx.comboSaveConfig({ aiMode: 'postbox', aiModel: 'sonnet' });
ctx.comboPostboxPoll();
const pbChatReq = ctx.comboQuickAiSave({
  mode: 'edit', previewOnly: true, name: 'セルを黄に', code: '// cur\nfunction セルを黄に() {}',
  prompt: '使い方を教えて', history: [{ role: 'user', text: '最初の質問' }, { role: 'ai', text: '最初の返答' }],
  targetId: 'SS_AI_1', sheet: '売上', selection: 'B2'
});
const pollChat = ctx.comboPostboxPoll();
const dChatOk = ctx.comboPostboxDeliver({
  reqId: pbChatReq.reqId, kind: 'mymacro', mode: 'edit', previewOnly: true,
  action: 'reply', message: '郵便受けからの提案です'
});
const sidePollChat = ctx.comboPollSelection({ targetId: 'SS_AI_1', sheet: '売上', postboxOnly: true });
const dChatOk2 = ctx.comboPostboxDeliver({
  reqId: 'pb_fast_1', kind: 'mymacro', mode: 'edit', previewOnly: true, ssId: 'SS_AI_1',
  action: 'reply', message: '高速回収チェック'
});
const openBeforeFastPoll = openByIdCalls;
const fastPollRes = ctx.comboPollSelection({ targetId: 'SS_AI_1', postboxOnly: true });
const openAfterFastPoll = openByIdCalls;
const shortSysPromptCheck = ctx.comboBuildAiMyMacroPrompts_('edit', '相談', 'AI表', '売上', 'B2', null, ['売上'], 'セルを黄に', '// c', [], [], true);
const extractedReplyWithSnippet = ctx.comboExtractMyMacroCode_(
  JSON.stringify({ action: 'reply', message: "案1: 行全体を塗る\n例:\n```js\nfunction ex() {}\n```\nいかがでしょうか？" })
);

const driveCountAfterPreview = Object.keys(driveFiles).length;
const driveSnapshotAfterPreview = JSON.stringify(driveFiles);

console.log(JSON.stringify({
  geminiAttempt: gAttemptAfter1, geminiAttemptEnd: geminiAttempt, gOk: gRes.ok, gName: gRes.name,
  claudeAttempt: cAttemptAfter2, claudeAttemptEnd: claudeAttempt, cOk: cRes.ok, cPrevHasFef08a: (cRes.prevCode || '').includes('#fef08a'),
  pbNotListeningOk: !pbNotListening.ok && String(pbNotListening.error || '').includes('拡張'),
  pbPending: pbReq.pendingPostbox, pbKind: poll1.queue[0] && poll1.queue[0].kind,
  dBadRetryable: !dBad.ok && !!dBad.retryable,
  dGoodSaved: dGood.ok && dGood.saved,
  sideDone1: sidePoll.postboxDone && sidePoll.postboxDone[0],
  dClientFallbackFlag: dClientFallback.ok && dClientFallback.needsClientSave && !dClientFallback.saved,
  sideDone2: sidePoll2.postboxDone && sidePoll2.postboxDone[0],
  pvApiDupErrRetry: !pvApiDupErr.ok && String(pvApiDupErr.error || '').includes('同じ名前'),
  pvApiDupNotSaved: !pvApiDup.ok && String(pvApiDup.error || '').includes('同じ名前'),
  pvApiEditOk: pvApiEditOk.ok && !!pvApiEditOk.previewOnly && pvApiEditOk.saved === false && (pvApiEditOk.code || '').includes('#fef08a'),
  pbPvEnqueuedFlag: !!(pbPvReq.previewOnly && pollPv.queue[0] && pollPv.queue[0].previewOnly && String(pollPv.queue[0].existingCode || '').includes('draft')),
  dPvDupRetryable: !dPvDup.ok && !!dPvDup.retryable && String(dPvDup.error || '').includes('同じ名前'),
  dPvOkPreview: dPvOk.ok && !!dPvOk.previewOnly && dPvOk.saved === false && dPvOk.name === '背景を青にする',
  sideDonePv: sidePollPv.postboxDone && sidePollPv.postboxDone[0],
  chatApiOk: !!(chatApiReply.ok && chatApiReply.action === 'reply' && chatApiReply.previewOnly && chatApiReply.saved === false && String(chatApiReply.message || '').includes('案1: 背景も変える')),
  pbChatHistoryLen: (pollChat.queue[0] && Array.isArray(pollChat.queue[0].history)) ? pollChat.queue[0].history.length : 0,
  dChatOkReply: !!(dChatOk.ok && dChatOk.action === 'reply' && dChatOk.previewOnly && dChatOk.saved === false),
  sideDoneChat: sidePollChat.postboxDone && sidePollChat.postboxDone[0],
  fastPollOk: !!(dChatOk2.ok && fastPollRes.ok && fastPollRes.postboxDone && fastPollRes.postboxDone[0] && fastPollRes.postboxDone[0].message === '高速回収チェック' && openBeforeFastPoll === openAfterFastPoll),
  hasShortPromptRule: String(shortSysPromptCheck.system || '').includes('200 文字以内'),
  extractedReplyStaysReply: extractedReplyWithSnippet.action === 'reply',
  driveUnchanged: driveCountBeforePreview === driveCountAfterPreview && driveSnapshotBeforePreview === driveSnapshotAfterPreview
}));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps({"engine": by_name["Engine"], "server": by_name["ComboServer"]}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\nstdout: {proc.stdout}"
    res = json.loads(proc.stdout.strip())
    assert res["geminiAttempt"] == 2 and res["geminiAttemptEnd"] == 3 and res["gOk"] and res["gName"] == "セルを黄に"
    assert res["claudeAttempt"] == 1 and res["claudeAttemptEnd"] == 3 and res["cOk"] and res["cPrevHasFef08a"]
    assert res["pbNotListeningOk"]
    assert res["pbPending"] and res["pbKind"] == "mymacro"
    assert res["dBadRetryable"] and res["dGoodSaved"]
    assert res["sideDone1"]["kind"] == "mymacro" and res["sideDone1"]["saved"] is True
    assert res["dClientFallbackFlag"]
    assert res["sideDone2"]["kind"] == "mymacro" and res["sideDone2"]["saved"] is False and "赤文字にする" in res["sideDone2"]["code"]
    assert res["pvApiDupErrRetry"] and res["pvApiDupNotSaved"]
    assert res["pvApiEditOk"]
    assert res["pbPvEnqueuedFlag"] and res["dPvDupRetryable"] and res["dPvOkPreview"]
    assert res["sideDonePv"]["previewOnly"] is True and res["sideDonePv"]["saved"] is False and "背景を青にする" in res["sideDonePv"]["code"]
    assert res["chatApiOk"] and res["pbChatHistoryLen"] == 2 and res["dChatOkReply"]
    assert res["sideDoneChat"]["action"] == "reply" and res["sideDoneChat"]["previewOnly"] is True and res["sideDoneChat"]["saved"] is False
    assert "郵便受けからの提案です" in res["sideDoneChat"]["message"]
    assert res["fastPollOk"] and res["hasShortPromptRule"]
    assert res["extractedReplyStaysReply"]
    assert res["driveUnchanged"]


def test_postbox_watcher_mymacro_resolve_and_retry(monkeypatch):
    """ComboPostboxWatcher が kind=='mymacro' を解釈し、retryable エラー時に previewOnly/existingNames 等を維持して再送すること。"""
    delivered = []
    prompts_seen = []
    poll_kws = []

    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

        def run_function(self, sid, fn_name, args=None, **kw):
            if fn_name == "comboPostboxPoll":
                poll_kws.append(kw)
                return {
                    "ok": True,
                    "result": {
                        "ok": True,
                        "queue": [
                            {
                                "reqId": "pb_m1",
                                "kind": "mymacro",
                                "mode": "edit",
                                "previewOnly": True,
                                "targetName": "テストマクロ",
                                "existingCode": "function テストマクロ() {}",
                                "existingNames": ["既存A"],
                                "ask": "太字にして",
                                "ssId": "SS_W1",
                                "ssName": "売上表",
                                "sheet": "Sheet1",
                                "selection": "A1:B2",
                                "aiModel": "sonnet",
                                "myId": "MY_W1",
                            }
                        ],
                    },
                }
            if fn_name == "comboPostboxDeliver":
                payload = args[0]
                delivered.append(payload)
                if len(delivered) == 1:
                    return {"ok": True, "result": {"ok": False, "retryable": True, "error": "構文エラー"}}
                return {"ok": True, "result": {"ok": True, "saved": False, "previewOnly": True, "reqId": payload["reqId"]}}
            raise AssertionError(f"unexpected fn: {fn_name}")

    w = combo_mod.ComboPostboxWatcher("ADDON_W", client=FakeClient(), backend="claude")

    def fake_ask_mymacro(prompt, model=None):
        prompts_seen.append(prompt)
        if len(prompts_seen) == 1:
            return {"action": "mymacro", "code": "function テストマクロ({", "note": "1回目"}
        return {"action": "mymacro", "code": "function テストマクロ() {\n  SpreadsheetApp.getActiveRange().setFontWeight('bold');\n}", "note": "修正済み"}

    w._ask_mymacro_via_claude = fake_ask_mymacro
    out = w.poll_once()
    assert poll_kws and poll_kws[0].get("timeout") == 7
    assert isinstance(out[0].get("timing"), dict)
    for k in ("poll_wall_ms", "ai_ms", "deliver_wall_ms", "total_ms"):
        assert k in out[0]["timing"]
    assert "200 文字以内" in w._MYMACRO_SYSTEM_PROMPT
    assert len(prompts_seen) == 2
    assert "既存のコード" in prompts_seen[0] or "現在のコード" in prompts_seen[0]
    assert "構文エラー" in prompts_seen[1]
    assert len(delivered) == 2
    assert delivered[1]["kind"] == "mymacro" and delivered[1]["mode"] == "edit"
    assert delivered[1]["previewOnly"] is True and delivered[1]["existingNames"] == ["既存A"]
    assert delivered[1]["targetName"] == "テストマクロ" and delivered[1]["ask"] == "太字にして"
    assert out[0]["deliver"]["previewOnly"] is True and out[0]["deliver"]["saved"] is False

    # add モードで下書きコード (existingCode) と history / previewOnly がある場合のプロンプトと reply 正規化も確認
    draft_prompt = w._build_mymacro_prompt({
        "mode": "add",
        "previewOnly": True,
        "ask": "やっぱり青にして",
        "existingCode": "function 新規下書き() {}",
        "existingNames": ["既存A"],
        "history": [
            {"role": "user", "text": "どんな色がおすすめ？"},
            {"role": "ai", "text": "薄青が読みやすいです"},
        ],
        "ssName": "売上表",
        "sheet": "Sheet1",
    })
    assert "既存A" in draft_prompt and "現在表示中の下書きコード" in draft_prompt and "function 新規下書き()" in draft_prompt
    assert "【これまでの会話】" in draft_prompt and "ユーザー: どんな色がおすすめ？" in draft_prompt and "AI: 薄青が読みやすいです" in draft_prompt
    assert "質問・相談・改修案の提案なら" in draft_prompt
    norm_reply = w._normalize_mymacro_parsed({
        "action": "reply",
        "message": "背景色を揃える案です。例:\n```js\nrange.setBackground('#cfe2ff');\n```\n進めますか？",
    })
    assert norm_reply["action"] == "reply" and "背景色を揃える案" in norm_reply["message"]

    # タイムアウト 1 回で runner_installed を消さない＋アイドル HTTP プールを閉じることを確認
    closed_cnt = [0]

    class _MockAdapter:
        def close(self):
            closed_cnt[0] += 1

    class _TimeoutClient:
        def __init__(self):
            self._cache_data = {"deployments": {"ADDON_WT": {"runner_installed": True}}}
            self.session = type("S", (), {"adapters": {"https://": _MockAdapter()}})()

        def resolve_script_id(self, sid):
            return sid

    wt = combo_mod.ComboPostboxWatcher("ADDON_WT", client=_TimeoutClient(), backend="claude")
    wt.poll_once = lambda: (_ for _ in ()).throw(TimeoutError("Webアプリの呼び出しがタイムアウトしました (7秒)"))
    monkeypatch.setattr(combo_mod, "COMBO_WATCH_PORT", 19877)
    wt.watch(max_loops=1, idle_interval=0.01)
    assert wt.client._cache_data["deployments"]["ADDON_WT"].get("runner_installed") is True
    assert closed_cnt[0] == 1


def test_postbox_watcher_resolve_direct_and_http(monkeypatch):
    """ComboPostboxWatcher.resolve_direct の動作と /ping・/resolve・/stop HTTP サーバー応答を確認する。"""
    import socket
    import threading
    import time
    import urllib.request

    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

    w = combo_mod.ComboPostboxWatcher("ADDON_DIR", client=FakeClient(), backend="claude")

    # 1. kind="mymacro" の reply 返却
    w._ask_mymacro_via_claude = lambda prompt, model=None: {
        "action": "reply",
        "message": "1. 見出しを強調できます\n2. 桁区切りを設定できます",
    }
    res_rep = w.resolve_direct({
        "kind": "mymacro",
        "mode": "add",
        "previewOnly": True,
        "ask": "どんな編集ができますか？",
        "aiModel": "sonnet",
    })
    assert res_rep["ok"] is True
    assert res_rep["direct"] is True
    assert res_rep["action"] == "reply"
    assert res_rep["previewOnly"] is True
    assert res_rep["saved"] is False
    assert isinstance(res_rep["aiMs"], int) and res_rep["aiMs"] >= 0
    assert "見出しを強調" in res_rep["message"]

    # 2. kind="mymacro" 新規作成で既存関数名重複 -> 1回自動リトライして別名で成功
    prompts_dup = []

    def fake_dup_then_ok(prompt, model=None):
        prompts_dup.append(prompt)
        if len(prompts_dup) == 1:
            return {"action": "mymacro", "code": "function 既存名() {\n  return 'ng';\n}", "note": "重複案"}
        return {"action": "mymacro", "code": "function 新規名() {\n  return 'ok';\n}", "note": "別名で作成"}

    w._ask_mymacro_via_claude = fake_dup_then_ok
    res_code = w.resolve_direct({
        "kind": "mymacro",
        "mode": "add",
        "previewOnly": True,
        "existingNames": ["既存名"],
        "ask": "テストマクロを作って",
        "aiModel": "sonnet",
    })
    assert len(prompts_dup) == 2
    assert "既存名" in prompts_dup[1] and "同じ名前" in prompts_dup[1]
    assert res_code["ok"] is True
    assert res_code["direct"] is True
    assert res_code["action"] == "mymacro"
    assert res_code["name"] == "新規名"
    assert "function 新規名()" in res_code["code"]
    assert res_code["previewOnly"] is True
    assert res_code["saved"] is False

    # 3. kind="ops" の ops 返却および reply 返却
    w._ask_via_claude = lambda prompt, model=None: {
        "action": "ops",
        "ops": [{"shelf": "width", "auto": ["A", "B"]}],
        "note": "列幅調整",
    }
    res_ops = w.resolve_direct({"kind": "ops", "ask": "AとBの列幅を自動調整して", "aiModel": "sonnet"})
    assert res_ops["ok"] is True and res_ops["direct"] is True and res_ops["action"] == "ops"
    assert res_ops["ops"] == [{"shelf": "width", "auto": ["A", "B"]}]

    w._ask_via_claude = lambda prompt, model=None: {
        "action": "reply",
        "message": "対象の列を教えてください",
    }
    res_ops_rep = w.resolve_direct({"kind": "ops", "ask": "調整して", "aiModel": "sonnet"})
    assert res_ops_rep["ok"] is True and res_ops_rep["direct"] is True and res_ops_rep["action"] == "reply"
    assert "対象の列" in res_ops_rep["message"]

    # 4. ローカル HTTP サーバー（/ping -> POST /resolve -> /stop）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    monkeypatch.setattr(combo_mod, "COMBO_WATCH_PORT", free_port)
    w._ask_mymacro_via_claude = lambda prompt, model=None: {
        "action": "reply",
        "message": "HTTP直結テスト応答",
    }
    w.poll_once = lambda: []
    srv_thread = threading.Thread(target=lambda: w.watch(idle_interval=0.05), daemon=True)
    srv_thread.start()

    ping_data = None
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/ping", timeout=1.0) as resp:
                ping_data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception:
            time.sleep(0.02)
    assert ping_data and ping_data.get("ok") is True and ping_data.get("direct") is True

    req_body = json.dumps({
        "kind": "mymacro",
        "mode": "add",
        "previewOnly": True,
        "ask": "テスト質問",
        "aiModel": "sonnet",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{free_port}/resolve",
        data=req_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        post_data = json.loads(resp.read().decode("utf-8"))
    assert post_data["ok"] is True and post_data["direct"] is True
    assert post_data["action"] == "reply" and post_data["message"] == "HTTP直結テスト応答"

    with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/stop", timeout=2.0) as resp:
        stop_data = json.loads(resp.read().decode("utf-8"))
    assert stop_data.get("ok") is True
    srv_thread.join(timeout=5.0)
    assert not srv_thread.is_alive()


def test_postbox_watcher_direct_only_skips_gas_poll(monkeypatch):
    """watch(direct_only=True) が GAS ポーリング (poll_once) を一度も呼ばずに /ping・/resolve・/stop に応じること。"""
    import socket
    import threading
    import time
    import urllib.request

    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

    w = combo_mod.ComboPostboxWatcher("ADDON_DO", client=FakeClient(), backend="claude")
    w._ask_mymacro_via_claude = lambda prompt, model=None: {
        "action": "reply",
        "message": "直結専用テスト応答",
    }
    poll_calls = [0]

    def spy_poll():
        poll_calls[0] += 1
        raise AssertionError("direct_only=True で poll_once が呼ばれてはいけません")

    w.poll_once = spy_poll

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    monkeypatch.setattr(combo_mod, "COMBO_WATCH_PORT", free_port)
    srv_thread = threading.Thread(target=lambda: w.watch(idle_interval=0.05, direct_only=True), daemon=True)
    srv_thread.start()

    ping_data = None
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/ping", timeout=1.0) as resp:
                ping_data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception:
            time.sleep(0.02)
    assert ping_data and ping_data.get("ok") is True
    assert ping_data.get("direct") is True and ping_data.get("directOnly") is True

    time.sleep(0.1)
    req_body = json.dumps({
        "kind": "mymacro",
        "mode": "add",
        "previewOnly": True,
        "ask": "直結専用テスト",
        "aiModel": "sonnet",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{free_port}/resolve",
        data=req_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        post_data = json.loads(resp.read().decode("utf-8"))
    assert post_data["ok"] is True and post_data["direct"] is True and post_data["message"] == "直結専用テスト応答"

    with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/stop", timeout=2.0) as resp:
        stop_data = json.loads(resp.read().decode("utf-8"))
    assert stop_data.get("ok") is True
    srv_thread.join(timeout=5.0)
    assert not srv_thread.is_alive()
    assert poll_calls[0] == 0


def test_ai_prompts_include_all_shelves_without_50_cutoff():
    """AI プロンプト（Python / GAS 両方）が 50 件カットされず全検索対象シート棚を含み、まとめ棚ルールを持つこと。"""
    import gas_ws_find

    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

    w = combo_mod.ComboPostboxWatcher("ADDON_DIR", client=FakeClient(), backend="claude")
    py_prompt = w._build_prompt({
        "ask": "見出しを青にして",
        "ssName": "売上表",
        "sheet": "売上",
        "sheets": ["売上"],
    })
    for must in ("format", "width", "cf.add", "rows.delete", "sheet.add", "table.new"):
        assert must in py_prompt

    finder = w._get_finder()
    searchable_sheet = [
        s["name"]
        for s in finder.cat.shelves
        if s.get("searchable", True) and (s.get("kind") == "sheet" or s.get("shared"))
    ]
    missing_py = [nm for nm in searchable_sheet if nm not in py_prompt]
    assert missing_py == [], missing_py

    py_my_prompt = w._build_mymacro_prompt({
        "mode": "add",
        "ask": "月次締めのまとめ棚を作って",
        "ssName": "売上表",
        "sheet": "売上",
    })
    assert "shelf(" in w._MYMACRO_SYSTEM_PROMPT
    assert "format" in py_my_prompt and "sheet.add" in py_my_prompt

    # GAS 側（ComboServer + ComboPlanner）を Node vm で実行して検証
    files_full = combo_mod.build_combo_files(combo_lite=False)
    by_full = {f["name"]: f["source"] for f in files_full}
    files_lite = combo_mod.build_combo_files(combo_lite=True)
    by_lite = {f["name"]: f["source"] for f in files_lite}
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = vm.createContext({
  Date, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Infinity, Proxy, parseInt, parseFloat, encodeURIComponent, decodeURIComponent
});
ctx.globalThis = ctx;
vm.runInContext(payload.planner + '\n' + payload.server, ctx);
const opsP = ctx.comboBuildAiPrompts_('見出しを青にして', '売上表', '売上', 'A1', null, ['売上']);
const myP = ctx.comboBuildAiMyMacroPrompts_('add', 'まとめ棚を作って', '売上表', '売上', 'A1', null, ['売上'], '', '', [], [], true);
console.log(JSON.stringify({ opsUser: opsP.user, mySys: myP.system, myUser: myP.user }));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps({"planner": by_full["ComboPlanner"], "server": by_lite["ComboServer"]}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}"
    res = json.loads(proc.stdout.strip())
    for must in ("format", "width", "cf.add", "rows.delete", "sheet.add", "table.new"):
        assert must in res["opsUser"], must
    missing_gas = [nm for nm in searchable_sheet if nm not in res["opsUser"]]
    assert missing_gas == [], missing_gas
    assert "shelf(" in res["mySys"] and "まとめ棚" in res["mySys"]
    assert "format" in res["myUser"] and "rows.delete" in res["myUser"]


def test_postbox_watcher_resolve_direct_ops_validation_and_retry():
    """resolve_direct(kind='ops') のローカル引数検査と 1 回自動リトライを検証する。"""
    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

    w = combo_mod.ComboPostboxWatcher("ADDON_DIR", client=FakeClient(), backend="claude")
    prompts = []

    def fake_bad_then_ok(prompt, model=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"action": "ops", "ops": [{"shelf": "rows.delete"}], "note": "引数不足"}
        return {"action": "ops", "ops": [{"shelf": "rows.delete", "rows": [3]}], "note": "3行目削除"}

    w._ask_via_claude = fake_bad_then_ok
    res = w.resolve_direct({"kind": "ops", "ask": "3行目を消して", "aiModel": "sonnet"})
    assert len(prompts) == 2
    assert "rows" in prompts[1]
    assert res["ok"] is True and res["action"] == "ops"
    assert res["ops"] == [{"shelf": "rows.delete", "rows": [3]}]

    # 2 回目も未知棚なら action="error" を返す
    w._ask_via_claude = lambda prompt, model=None: {
        "action": "ops",
        "ops": [{"shelf": "no_such_shelf"}],
        "note": "不正棚",
    }
    res_ng = w.resolve_direct({"kind": "ops", "ask": "何かして", "aiModel": "sonnet"})
    assert res_ng["ok"] is False and res_ng["action"] == "error"
    assert "no_such_shelf" in res_ng["error"]


def test_combo_quick_run_shelf_bundle_and_run_ask_mymacro_match():
    """マイマクロ内からの shelf() まとめ棚実行と、comboRunAsk での // 棚: 照合・競合回避を検証する。"""
    files_full = combo_mod.build_combo_files(combo_lite=False)
    by_full = {f["name"]: f["source"] for f in files_full}
    files_lite = combo_mod.build_combo_files(combo_lite=True)
    by_lite = {f["name"]: f["source"] for f in files_lite}
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const userProps = {}, scriptProps = {}, userCache = {};
const driveFiles = {};
let driveSeq = 0;

function makeSheet(name, initGrid) {
  const rows = initGrid.map(r => r.slice());
  const weights = rows.map(r => r.map(() => 'normal'));
  const bgs = rows.map(r => r.map(() => '#ffffff'));
  const fgs = rows.map(r => r.map(() => '#000000'));
  function parseA1(a1) {
    const parts = String(a1).toUpperCase().split(':');
    const c2n = (s) => { let n = 0; for (let i=0;i<s.length;i++) n = n*26 + (s.charCodeAt(i)-64); return n; };
    const p = (s) => { const m = s.match(/^([A-Z]+)(\d+)$/); return [parseInt(m[2],10), c2n(m[1])]; };
    const [r1, c1] = p(parts[0]);
    const [r2, c2] = parts[1] ? p(parts[1]) : [r1, c1];
    return [r1, c1, r2 - r1 + 1, c2 - c1 + 1];
  }
  function mkRg(r, c, nr, nc) {
    const apply = (arr, val) => {
      for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) arr[r-1+i][c-1+j] = Array.isArray(val) ? val[i][j] : val;
    };
    const rg = {
      getRow: () => r, getColumn: () => c, getNumRows: () => nr, getNumColumns: () => nc,
      getA1Notation: () => 'A1',
      getValues: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc)),
      getDisplayValues: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc).map(String)),
      getFormulas: () => rows.slice(r-1, r-1+nr).map(x => x.slice(c-1, c-1+nc).map(() => '')),
      getFontWeight: () => weights[r-1][c-1],
      setFontWeight: (w) => { apply(weights, w); return rg; },
      setBackground: (bg) => { apply(bgs, bg); return rg; },
      setFontColor: (fg) => { apply(fgs, fg); return rg; },
      clear: () => { apply(rows, ''); apply(weights, 'normal'); apply(bgs, '#ffffff'); return rg; },
      breakApart: () => rg, clearDataValidations: () => rg,
      copyTo: (dst) => {
        const dR = dst.getRow(), dC = dst.getColumn();
        for (let i=0;i<nr;i++) for (let j=0;j<nc;j++) {
          dst._sheet._rows[dR-1+i][dC-1+j] = rows[r-1+i][c-1+j];
          dst._sheet._weights[dR-1+i][dC-1+j] = weights[r-1+i][c-1+j];
          dst._sheet._bgs[dR-1+i][dC-1+j] = bgs[r-1+i][c-1+j];
        }
      },
      _sheet: shObj
    };
    return rg;
  }
  const shObj = {
    _rows: rows, _weights: weights, _bgs: bgs, _fgs: fgs,
    getSheetId: () => 10,
    getName: () => name,
    setName: (n) => { name = n; },
    hideSheet: () => {},
    isSheetHidden: () => false,
    getMaxRows: () => rows.length,
    getMaxColumns: () => rows[0].length,
    getLastRow: () => rows.length,
    getLastColumn: () => rows[0].length,
    getFrozenRows: () => 0,
    getFrozenColumns: () => 0,
    getBandings: () => [],
    getFilter: () => null,
    getDataRange: () => mkRg(1, 1, rows.length, rows[0].length),
    getRange: (a, b, c, d) => {
      if (typeof a === 'string') { const [r, co, nr, nc] = parseA1(a); return mkRg(r, co, nr, nc); }
      return mkRg(a, b, c || 1, d || 1);
    },
    getRangeList: (a1s) => ({ getRanges: () => a1s.map(x => shObj.getRange(x)) }),
    copyTo: (targetSs) => {
      const copy = makeSheet(name + '_copy', rows);
      for (let i=0;i<rows.length;i++) {
        copy._weights[i] = weights[i].slice();
        copy._bgs[i] = bgs[i].slice();
      }
      targetSs._addSheet(copy);
      return copy;
    }
  };
  return shObj;
}

const mainSh = makeSheet('売上', [
  ['品名', '金額'],
  ['りんご', 100],
  ['みかん', 200]
]);
const sheetsMap = { '売上': mainSh };
const mockSs = {
  _addSheet: (s) => { sheetsMap[s.getName()] = s; },
  getId: () => 'MOCK_WEB_SS',
  getName: () => 'WebAppテスト',
  getSheets: () => Object.values(sheetsMap),
  getSheetByName: (n) => Object.values(sheetsMap).find(s => s.getName() === n) || null,
  getActiveSheet: () => mainSh,
  deleteSheet: (s) => { Object.keys(sheetsMap).forEach(k => { if (sheetsMap[k] === s) delete sheetsMap[k]; }); }
};

const ctx = vm.createContext({
  SpreadsheetApp: {
    getActive: () => null,
    getActiveSpreadsheet: () => null,
    openById: (id) => id === 'MOCK_WEB_SS' ? mockSs : null,
    flush: () => {},
    CopyPasteType: { PASTE_COLUMN_WIDTHS: 'PASTE_COLUMN_WIDTHS' }
  },
  ScriptApp: { getOAuthToken: () => 'TOK_MOCK' },
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...userProps }),
      getProperty: (k) => (k in userProps ? userProps[k] : null),
      setProperty: (k, v) => { userProps[k] = String(v); },
      deleteProperty: (k) => { delete userProps[k]; }
    }),
    getScriptProperties: () => ({
      getProperty: (k) => (k in scriptProps ? scriptProps[k] : null),
      setProperty: (k, v) => { scriptProps[k] = String(v); },
      deleteProperty: (k) => { delete scriptProps[k]; }
    })
  },
  CacheService: {
    getUserCache: () => ({
      get: (k) => (k in userCache ? userCache[k] : null),
      put: (k, v) => { userCache[k] = String(v); },
      remove: (k) => { delete userCache[k]; }
    }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  DriveApp: {
    getFileById: (id) => {
      const f = driveFiles[id];
      return { getId: () => id, getName: () => f.name, isTrashed: () => false, getLastUpdated: () => ({ getTime: () => f.stamp }) };
    },
    searchFiles: () => {
      const vals = Object.values(driveFiles);
      let idx = 0;
      return { hasNext: () => idx < vals.length, next: () => { const f = vals[idx++]; return { getId: () => f.id, getLastUpdated: () => ({ getTime: () => f.stamp }) }; } };
    }
  },
  UrlFetchApp: {
    fetch: (url, o) => {
      if (o.method === 'post' && url.includes('/upload/drive/v3/files')) {
        const body = String(o.payload || '');
        const idx = body.indexOf('application/vnd.google-apps.script+json');
        const jsonPart = body.slice(body.indexOf('{', idx), body.lastIndexOf('}') + 1);
        const id = 'MY_' + (++driveSeq);
        driveFiles[id] = { id, name: 'GASクイック マイマクロ', content: JSON.parse(jsonPart), stamp: Date.now() };
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id }) };
      }
      if (o.method === 'get' && url.includes('/export?')) {
        const m = url.match(/\/files\/([^/]+)\/export/);
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify(driveFiles[m[1]].content) };
      }
      if (o.method === 'patch' && url.includes('/upload/drive/v3/files/')) {
        const m = url.match(/\/files\/([^?]+)/);
        driveFiles[m[1]].content = JSON.parse(o.payload);
        driveFiles[m[1]].stamp = Date.now() + 10;
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ id: m[1] }) };
      }
      return { getResponseCode: () => 404, getContentText: () => 'not found' };
    }
  },
  Utilities: {
    computeDigest: (algo, s) => [1, 2, 3, 4, 5, 6, 7, 8],
    DigestAlgorithm: { SHA_1: 'SHA_1', MD5: 'MD5' },
    Charset: { UTF_8: 'UTF_8' },
    newBlob: (s) => ({ getBytes: () => Buffer.from(String(s), 'utf8'), getDataAsString: () => String(s) }),
    gzip: (b) => b,
    ungzip: (b) => b,
    base64Encode: (b) => Buffer.from(b).toString('base64'),
    base64Decode: (s) => Buffer.from(String(s), 'base64')
  },
  Date, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Infinity, Proxy, parseInt, parseFloat, encodeURIComponent, decodeURIComponent
});
ctx.globalThis = ctx;
vm.runInContext(payload.engine + '\n' + payload.planner + '\n' + payload.server, ctx);

const shelfCalls = [];
ctx.SHELF['test.bold'] = function (c, op) {
  shelfCalls.push(op);
  c.changed.push('太字:' + (op.range || ''));
  ctx.openTarget_({ id: 'MOCK_WEB_SS', kind: 'sheet' }).file.getSheetByName('売上').getRange(op.range || 'A1').setFontWeight('bold');
};
ctx.SHELF['test.bg'] = function (c, op) {
  shelfCalls.push(op);
  c.changed.push('背景:' + (op.range || ''));
  ctx.openTarget_({ id: 'MOCK_WEB_SS', kind: 'sheet' }).file.getSheetByName('売上').getRange(op.range || 'A1').setBackground(op.bg || '#ddebf7');
};

ctx.comboQuickMake({});
ctx.comboQuickAddFn({
  code: [
    '// 月次締めの定型まとめ棚',
    '// 棚: 月次締め仕上げ, 請求書チェック',
    'function 月次締めまとめ() {',
    '  shelf([{shelf: "test.bold", range: "A1:B1"}]);',
    '  shelf("test.bg", {range: "A2:B2", bg: "#fff2cc"});',
    '  return "まとめ完了";',
    '}'
  ].join('\n')
});
ctx.comboQuickAddFn({
  code: [
    '// 存在しない棚を呼ぶエラー確認用',
    '// 棚: 壊れたまとめ',
    'function 壊れたまとめ() {',
    '  shelf("no_such_shelf");',
    '}'
  ].join('\n')
});

// 1. comboQuickRun によるまとめ棚実行＋控え保持＋Undo
const runMatome = ctx.comboQuickRun({ targetId: 'MOCK_WEB_SS', sheet: '売上', name: '月次締めまとめ', backup: true });
const weightAfter = mainSh._weights[0][0];
const bgAfter = mainSh._bgs[1][0];
const bkExists = !!mockSs.getSheetByName('_GASクイックの控え');
const undoRes = ctx.comboUndo({ targetId: 'MOCK_WEB_SS' });
const weightUndone = mainSh._weights[0][0];

// 2. 存在しない棚のエラー伝播
const runBad = ctx.comboQuickRun({ targetId: 'MOCK_WEB_SS', sheet: '売上', name: '壊れたまとめ', backup: false });

// 3. comboRunAsk から // 棚: 月次締め仕上げ に自動ヒットして実行
const askHit = ctx.comboRunAsk({ targetId: 'MOCK_WEB_SS', sheet: '売上', ask: '月次締め仕上げをして', aiAuto: false });

// 4. 同じ // 棚: を持つ競合マクロを追加すると曖昧回避でヒットしないこと
ctx.comboQuickAddFn({
  code: '// 競合テスト\n// 棚: 月次締め仕上げ\nfunction 別案締め() {\n  return "別案";\n}'
});
const askConflict = ctx.comboRunAsk({ targetId: 'MOCK_WEB_SS', sheet: '売上', ask: '月次締め仕上げをして', aiAuto: false });

console.log(JSON.stringify({
  runOk: runMatome.ok, runErr: runMatome.error || '', snapped: runMatome.snapped, weightAfter, bgAfter, bkExists,
  undoOk: undoRes.ok, weightUndone, callCount: shelfCalls.length,
  badOk: runBad.ok, badErr: runBad.error || '',
  askSource: askHit.source, askMacro: askHit.matchedMacro, askOk: askHit.ok, askErr: askHit.error || '',
  conflictOk: askConflict.ok, conflictSource: askConflict.source || ''
}));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps(
            {"engine": by_lite["Engine"], "planner": by_full["ComboPlanner"], "server": by_lite["ComboServer"]},
            ensure_ascii=False,
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\nstdout: {proc.stdout}"
    res = json.loads(proc.stdout.strip())
    assert res["runOk"] and res["snapped"] and res["bkExists"], res
    assert res["weightAfter"] == "bold" and res["bgAfter"] == "#fff2cc"
    assert res["undoOk"] and res["weightUndone"] == "normal"
    assert res["badOk"] is False and "no_such_shelf" in res["badErr"]
    assert res["askOk"] and res["askSource"] == "mymacro" and res["askMacro"] == "月次締めまとめ"
    assert res["conflictOk"] is False and res["conflictSource"] != "mymacro"


def test_gas_mcp_server_ws_check_ws_misses_and_combo_quick(monkeypatch):
    """gas_mcp_server の ws-check / ws-misses / shelf整合 / combo quick を検証する。"""
    import gas_mcp_server as srv

    chk = srv.gas("ws-check")
    assert "[OK]" in chk and "Workspace 棚カタログ検査" in chk

    misses = srv.gas("ws-misses 5")
    assert "Workspace 棚の外れ・API逃げ集計" in misses

    captured = {}

    def fake_gas_shelf(**kw):
        captured["shelf"] = kw
        return "SHELF_OK"

    monkeypatch.setattr(srv, "gas_shelf", fake_gas_shelf)
    assert srv.gas("shelf MyProj 文言を替え") == "SHELF_OK"
    assert captured["shelf"]["apply"] is None
    assert captured["shelf"]["filename"] == ""

    calls = []

    class FakeCli:
        def resolve_script_id(self, s):
            return s

        def run_function(self, sid, fn, args):
            calls.append((sid, fn, args))
            if fn == "comboQuickList":
                return {"ok": True, "result": {"ok": True, "my": [{"name": "朝一整形", "desc": "表を整える", "words": ["朝一"]}]}}
            return {"ok": True, "result": {"ok": True, "text": "朝一整形 を実行しました", "gasMs": 120}}

    monkeypatch.setattr(srv, "get_client", lambda: FakeCli())
    ql = srv.gas("combo quick SID123 list")
    assert "朝一整形" in ql and "棚: 朝一" in ql
    qr = srv.gas("combo quick SID123 run 朝一整形 --sel A1:B5")
    assert "朝一整形 を実行しました" in qr
    assert calls[1][1] == "comboQuickRun" and calls[1][2][0]["selection"] == "A1:B5"


def test_postbox_watcher_fetch_recorded_macros_and_http(monkeypatch, tmp_path):
    """記録マクロ自動取り込み（macros.gs 優先抽出・scriptId 自動記憶・HTTP /recorded-macros・UI存在）を検証する。"""
    import socket
    import threading
    import time
    import urllib.request

    state_file = tmp_path / ".combo_engine_state.json"

    class FakeClient:
        def resolve_script_id(self, sid):
            return sid

        def _get_bound_spreadsheet_id(self, sid):
            if sid == "BOUND_SCRIPT_123456789012":
                return "SS_REC_1"
            return "OTHER_SS_ID"

        def get_content(self, sid, use_cache=False):
            assert sid == "BOUND_SCRIPT_123456789012"
            return {
                "files": [
                    {
                        "name": "コード",
                        "type": "SERVER_JS",
                        "source": (
                            "function onOpen() {}\n"
                            "function comboInit() {}\n"
                            "function helper_() {}\n"
                            "function 手動集計() {\n  return 1;\n}\n"
                        ),
                    },
                    {
                        "name": "macros",
                        "type": "SERVER_JS",
                        "source": (
                            "// 記録マクロ\n"
                            "function UntitledMacro() {\n"
                            "  var ss = SpreadsheetApp.getActive();\n"
                            "  ss.getRange('A1:C1').activate();\n"
                            "  ss.getActiveRangeList().setBackground('#cfe2f3');\n"
                            "}\n"
                        ),
                    },
                ]
            }

    w = combo_mod.ComboPostboxWatcher("ADDON_REC", client=FakeClient(), backend="claude")
    monkeypatch.setattr(combo_mod, "COMBO_ENGINE_STATE_PATH", state_file)

    # 1. 未紐付け時は needsEditor=True で案内を返す（別シート紐付けの scriptId も拒否）
    r0 = w.fetch_recorded_macros({"ssId": "SS_REC_1"}, state_path=state_file)
    assert r0["ok"] is False and r0.get("needsEditor") is True
    r_foreign = w.fetch_recorded_macros({"ssId": "SS_REC_1", "scriptId": "FOREIGN_SCRIPT_123456"}, state_path=state_file)
    assert r_foreign["ok"] is False and r_foreign.get("needsEditor") is True

    # 2. 初回 scriptId 指定で macros.gs 優先抽出＋補助・繋ぎ関数除外＋自動記憶
    r1 = w.fetch_recorded_macros({"ssId": "SS_REC_1", "scriptId": "BOUND_SCRIPT_123456789012"}, state_path=state_file)
    assert r1["ok"] is True and r1["direct"] is True
    names = [m["name"] for m in r1["macros"]]
    assert names == ["UntitledMacro", "手動集計"]
    assert r1["macros"][0]["file"] == "macros"
    assert "setBackground('#cfe2f3')" in r1["macros"][0]["code"]

    # 3. 2 回目は scriptId 省略でも自動記憶から取得できる
    r2 = w.fetch_recorded_macros({"ssId": "SS_REC_1", "scriptId": ""}, state_path=state_file)
    assert r2["ok"] is True and r2["scriptId"] == "BOUND_SCRIPT_123456789012"

    # 4. HTTP POST /recorded-macros が正常応答すること
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    monkeypatch.setattr(combo_mod, "COMBO_WATCH_PORT", free_port)
    srv_thread = threading.Thread(target=lambda: w.watch(idle_interval=0.05, direct_only=True), daemon=True)
    srv_thread.start()

    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/ping", timeout=1.0):
                break
        except Exception:
            time.sleep(0.02)

    req_body = json.dumps({"ssId": "SS_REC_1"}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{free_port}/recorded-macros",
        data=req_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        post_data = json.loads(resp.read().decode("utf-8"))
    assert post_data["ok"] is True and post_data["macros"][0]["name"] == "UntitledMacro"

    with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/stop", timeout=2.0):
        pass
    srv_thread.join(timeout=5.0)
    assert not srv_thread.is_alive()

    # 5. サイドバーテンプレートに UI とメッセージが含まれること
    sidebar_txt = combo_mod.SIDEBAR_TEMPLATE.read_text(encoding="utf-8")
    assert "btnQuickImportRec" in sidebar_txt and "GAS_COMBO_FETCH_RECORDED_MACROS" in sidebar_txt


def test_quick_parse_fns_extracts_direct_ops_safely():
    """静的な shelf(...) のみのマイマクロから directOps が抽出され、動的コードは除外されること。"""
    server_js = (combo_mod.SERVER_TEMPLATE).read_text(encoding="utf-8")
    src = """
// タイトルの色を変える
// 棚: タイトルの色を変える
function タイトルの色を変える() {
  // 静的まとめ棚
  shelf([
    { shelf: 'format', title: true, bg: '#fce8e6', bold: true },
    { shelf: 'width' }
  ]);
}

// 棚名文字列形式
function 単発棚呼び出し() {
  shelf('format', { header: true, bg: '#fef08a' });
}

// 動的コードを含むため直結対象外
function 動的マクロ() {
  var sh = SpreadsheetApp.getActiveSheet();
  shelf([{ shelf: 'format', title: true, bg: '#fff' }]);
  sh.getRange('A1').setValue('x');
}

// 計算式を含むため直結対象外
function 式ありマクロ() {
  shelf([{ shelf: 'write', cells: { A1: 'a' + 'b' } }]);
}
"""
    node_code = """
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const sandbox = { console };
vm.runInNewContext(input.serverJs, sandbox);
const list = sandbox.quickParseFns_(input.src);
process.stdout.write(JSON.stringify(list));
"""
    parsed = _run_node_json(node_code, {"serverJs": server_js, "src": src})
    by_name = {f["name"]: f for f in parsed}
    assert by_name["タイトルの色を変える"].get("directOps") == [
        {"shelf": "format", "title": True, "bg": "#fce8e6", "bold": True},
        {"shelf": "width"},
    ]
    assert by_name["単発棚呼び出し"].get("directOps") == [
        {"shelf": "format", "header": True, "bg": "#fef08a"},
    ]
    assert not by_name["動的マクロ"].get("directOps")
    assert not by_name["式ありマクロ"].get("directOps")


def test_try_compile_my_macro_direct_toggle_and_fallback():
    """定番 SpreadsheetApp マイマクロが直結 ops に変換され、未対応命令は null でフォールバックすること。"""
    html = combo_mod.SIDEBAR_TEMPLATE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)
    node_code = r"""
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const mkEl = () => ({
  value: '', textContent: '', innerHTML: '', checked: false, disabled: false,
  style: {}, dataset: {},
  classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
  addEventListener(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
  appendChild(){}, focus(){}, select(){}, scrollTop: 0, scrollHeight: 0,
  getAttribute(){ return ''; }, setAttribute(){}
});
const elsMap = {};
const sandbox = {
  console, setTimeout, clearTimeout,
  performance: { now: () => 0 },
  document: {
    getElementById: (id) => (elsMap[id] || (elsMap[id] = mkEl())),
    querySelector: () => mkEl(),
    querySelectorAll: () => [],
    createElement: () => mkEl(),
    createDocumentFragment: () => ({ appendChild(){} }),
    addEventListener(){},
  },
  window: { addEventListener(){} },
  localStorage: { getItem(){ return null; }, setItem(){} }
};
sandbox.globalThis = sandbox;
for (const sc of input.scripts) vm.runInNewContext(sc, sandbox);
const dt = sandbox.__comboDirectTest;
dt.state.oauthToken = 'tok';
dt.state.target = { id: 'SS1', kind: 'sheet', name: '検証', sheet: 'Sheet1' };
dt.state.curSheet = 'Sheet1';
dt.state.sheets = ['Sheet1'];
dt.state.sheetIdMap = { 'Sheet1': 0 };
dt.state.selection = 'A1:B1';
dt.els.chkBackup.checked = false;
dt.els.chkSync.checked = true;
dt.state.sheetSnapshot = {
  'Sheet1': {
    maxRows: 30, maxCols: 26,
    vals: { A1: { stringValue: 'タイトル' }, D1: { stringValue: '金額' } },
    cells: Array.from({ length: 30 }, () => Array.from({ length: 26 }, () => ({})))
  }
};
dt.state.quick.codeCache = {
  stamp: 'S1',
  map: {
    'タイトルの色を変える': `
function タイトルの色を変える() {
  var range = SpreadsheetApp.getActiveRange();
  if (!range) return;
  var now = String(range.getCell(1, 1).getFontColor()).toLowerCase();
  var next;
  if (now === '#000000') { next = '#ff0000'; }
  else if (now === '#ff0000') { next = '#0000ff'; }
  else { next = '#000000'; }
  range.setFontColor(next);
}`,
    '選んだ所を太字': `
function 選んだ所を太字() {
  var list = SpreadsheetApp.getActive().getActiveRangeList();
  var first = list.getRanges()[0];
  var isBold = first && first.getFontWeight() === 'bold';
  list.setFontWeight(isBold ? 'normal' : 'bold');
}`,
    '選んだ所の色を消す': `
function 選んだ所の色を消す() {
  SpreadsheetApp.getActive().getActiveRangeList().setBackground(null);
}`,
    '見出しを黄色に': `
function 見出しを黄色に() {
  var sh = SpreadsheetApp.getActiveSheet();
  var lastCol = Math.max(1, sh.getLastColumn());
  sh.getRange(1, 1, 1, lastCol).setBackground('#fef08a');
}`,
    '未対応コピー': `
function 未対応コピー() {
  SpreadsheetApp.getActiveSheet().copyTo(SpreadsheetApp.getActive());
}`,
    '範囲外アクセス': `
function 範囲外アクセス() {
  SpreadsheetApp.getActiveSheet().getRange('A100').setFontColor('#ff0000');
}`,
    '外部サービス': `
function 外部サービス() {
  DriveApp.getRootFolder();
}`
  }
};

// 1. トグル 3 連打（黒→赤→青→黒）＋ applySnapshot 連動
const colors = [];
for (let step = 0; step < 3; step++) {
  const ops = dt.tryCompileMyMacroDirect({ src: 'my', name: 'タイトルの色を変える' }, 'Sheet1');
  colors.push(ops && ops[0] && ops[0].color);
  const plan = dt.buildDirectBatchUpdate(ops, 'Sheet1');
  plan.applySnapshot({});
}
// 2. 太字トグル・背景クリア・見出し黄色
const bold1 = dt.tryCompileMyMacroDirect({ src: 'my', name: '選んだ所を太字' }, 'Sheet1');
dt.buildDirectBatchUpdate(bold1, 'Sheet1').applySnapshot({});
const bold2 = dt.tryCompileMyMacroDirect({ src: 'my', name: '選んだ所を太字' }, 'Sheet1');
const bgClr = dt.tryCompileMyMacroDirect({ src: 'my', name: '選んだ所の色を消す' }, 'Sheet1');
const hdrY = dt.tryCompileMyMacroDirect({ src: 'my', name: '見出しを黄色に' }, 'Sheet1');
// 3. 未対応命令は必ず null
const fbCopy = dt.tryCompileMyMacroDirect({ src: 'my', name: '未対応コピー' }, 'Sheet1');
const fbOut = dt.tryCompileMyMacroDirect({ src: 'my', name: '範囲外アクセス' }, 'Sheet1');
const fbDrive = dt.tryCompileMyMacroDirect({ src: 'my', name: '外部サービス' }, 'Sheet1');

process.stdout.write(JSON.stringify({ colors, bold1, bold2, bgClr, hdrY, fbCopy, fbOut, fbDrive }));
"""
    res = _run_node_json(node_code, {"scripts": scripts})
    assert res["colors"] == ["#ff0000", "#0000ff", "#000000"]
    assert res["bold1"] == [{"shelf": "format", "range": "A1:B1", "bold": True}]
    assert res["bold2"] == [{"shelf": "format", "range": "A1:B1", "bold": False}]
    assert res["bgClr"] == [{"shelf": "bg.clear", "range": "A1:B1"}]
    assert res["hdrY"] == [{"shelf": "format", "range": "A1:D1", "bg": "#fef08a"}]
    assert res["fbCopy"] is None
    assert res["fbOut"] is None
    assert res["fbDrive"] is None


def test_headless_claude_session_refreshes_at_max_turns(monkeypatch):
    import ws_window_ai
    sess = ws_window_ai._HeadlessClaudeSession(model="sonnet")
    sess.MAX_TURNS = 2
    state = {"alive": False, "closed": 0, "started": 0}
    monkeypatch.setattr(sess, "alive", lambda: state["alive"])
    def fake_start():
        state["alive"] = True
        state["started"] += 1
        sess.turns = 0
    monkeypatch.setattr(sess, "start", fake_start)
    monkeypatch.setattr(sess, "_send_and_wait", lambda p, t: f"ok:{p}")
    orig_close = sess.close
    def fake_close():
        state["alive"] = False
        state["closed"] += 1
        orig_close()
    monkeypatch.setattr(sess, "close", fake_close)
    assert sess.ask("1") == "ok:1" and sess.turns == 1 and state["closed"] == 0 and state["started"] == 1
    assert sess.ask("2") == "ok:2" and sess.turns == 2 and state["closed"] == 0 and state["started"] == 1
    assert sess.ask("3") == "ok:3" and sess.turns == 1 and state["closed"] == 1 and state["started"] == 2


def test_open_watch_log_truncates_oversized_file(tmp_path):
    log_p = tmp_path / ".combo_watch.log"
    log_p.write_text(("LINE\n" * 500), encoding="utf-8")
    assert log_p.stat().st_size > 1000
    f = combo_mod._open_watch_log(log_p, max_bytes=1000, keep_bytes=200)
    f.close()
    assert log_p.stat().st_size <= 200


def test_resolve_latest_api_model_dynamic_cache_and_fallback():
    files = combo_mod.build_combo_files(combo_lite=True)
    by_name = {f["name"]: f["source"] for f in files}
    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const userCache = {};
let fetchCount = 0;
let failModels = false;
const ctx = vm.createContext({
  CacheService: {
    getUserCache: () => ({
      get: (k) => (k in userCache ? userCache[k] : null),
      put: (k, v) => { userCache[k] = String(v); },
      remove: (k) => { delete userCache[k]; }
    }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  UrlFetchApp: {
    fetch: (url) => {
      fetchCount++;
      if (failModels) return { getResponseCode: () => 500, getContentText: () => 'err' };
      if (url.includes('api.anthropic.com/v1/models')) {
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ data: [{ id: 'claude-sonnet-6-0' }, { id: 'claude-haiku-5-5' }] }) };
      }
      if (url.includes('generativelanguage.googleapis.com/v1beta/models')) {
        return {
          getResponseCode: () => 200,
          getContentText: () => JSON.stringify({
            models: [
              { name: 'models/gemini-4-hydrogen', supportedGenerationMethods: ['generateContent'] },
              { name: 'models/gemini-5-hydrogen', supportedGenerationMethods: ['generateContent'] },
              { name: 'models/gemini-4-neon', supportedGenerationMethods: ['generateContent'] }
            ]
          })
        };
      }
      return { getResponseCode: () => 404, getContentText: () => '' };
    }
  },
  encodeURIComponent, parseFloat, JSON, Array, Object, String, RegExp
});
ctx.globalThis = ctx;
vm.runInContext(payload.engine + '\n' + payload.server, ctx);
const c1 = ctx.comboResolveLatestApiModel_('api_claude', 'sonnet', 'K1');
const c2 = ctx.comboResolveLatestApiModel_('api_claude', 'sonnet', 'K1'); // cache hit
const g1 = ctx.comboResolveLatestApiModel_('api_gemini', 'gemini_hydrogen', 'K2');
const g2 = ctx.comboResolveLatestApiModel_('api_gemini', 'gemini_neon', 'K2');
failModels = true;
const fbC = ctx.comboResolveLatestApiModel_('api_claude', 'haiku', 'K1');
const fbG = ctx.comboResolveLatestApiModel_('api_gemini', 'sonnet', 'K2'); // cached hydrogen hit
const fbNeon = ctx.comboResolveLatestApiModel_('api_gemini', 'gemini_neon', 'K2'); // cached neon hit
// 未キャッシュ状態でのフォールバック確認用 (apiKey なし)
const fbDirectN = ctx.comboResolveLatestApiModel_('api_gemini', 'gemini_neon', '');
process.stdout.write(JSON.stringify({ c1, c2, g1, g2, fbC, fbG, fbNeon, fbDirectN, fetchCount }));
"""
    res = _run_node_json(node_code, {"engine": by_name["Engine"], "server": by_name["ComboServer"]})
    assert res["c1"] == "claude-sonnet-6-0" and res["c2"] == "claude-sonnet-6-0"
    assert res["g1"] == "gemini-5-hydrogen" and res["g2"] == "gemini-4-neon"
    assert res["fbC"] == "claude-haiku-5-5" and res["fbG"] == "gemini-5-hydrogen" and res["fbNeon"] == "gemini-4-neon"
    assert res["fbDirectN"] == "gemini-4-neon"
    assert res["fetchCount"] == 4
