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
        "  'タイトルの字の色を#FF0000にして'\n"
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
    expected_colors = ["赤", "青", "緑", "#FF0000"]
    for p, col in zip(out["plans"], expected_colors):
        assert p["fire"] is True, p
        assert p["ops"] == [{"shelf": "format", "title": True, "color": col}], p

    assert "分類:" in out["asks"][0] or "棚" in out["asks"][0]
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

// 郵便受けフロー
const rPb = ctx.comboRunAsk({ ask: 'この表の傾向を日本語で説明して', aiAuto: true });
const rPoll = ctx.comboPostboxPoll();
const reqId = rPoll.queue[0].reqId;
const rDeliv = ctx.comboPostboxDeliver({ reqId, action: 'reply', message: '売上が順調です。' });
const rSidePoll = ctx.comboPollSelection({});

process.stdout.write(JSON.stringify({
  rInit, rLook, rFind, rAskRed, colorAfterRed, rUndo, colorAfterUndo,
  rAskHonest, colorAfterHonest, rUndo2, colorFinal,
  rPb, rPoll, rDeliv, rSidePoll
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
  PropertiesService: { getScriptProperties: () => ({
    getProperty: k => (k in propsStore ? propsStore[k] : null),
    setProperty: (k, v) => { propsStore[k] = String(v); },
    deleteProperty: k => { delete propsStore[k]; }
  }) },
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
  PropertiesService: { getScriptProperties: () => ({
    getProperty: k => (k in propsStore ? propsStore[k] : null),
    setProperty: (k, v) => { propsStore[k] = String(v); },
    deleteProperty: k => { delete propsStore[k]; }
  }) },
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
  window: {},
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
        ("C列を非表示にして", "cols.hide", False),
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
  window: {}, localStorage: { getItem(){ return null; }, setItem(){} }
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
dt.state.sheetSnapshot = { '売上表': { frozenRows: 0, frozenCols: 0, bandedRangeIds: [901], vals: {}, cells: Array.from({ length: 30 }, () => Array.from({ length: 26 }, () => ({}))) } };
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
process.stdout.write(JSON.stringify({ total: input.cases.length, failures, bgReq, redUndo: redReq && redReq.undoRequests, noSnap, wFull, wEmptyUndo: wEmpty && wEmpty.undoRequests }));
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
