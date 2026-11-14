"""167: 穴修正・色名・split.col insert・chart.new 複数範囲の回帰試験。"""
import json
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import gas_workspace  # noqa: E402


def _run_node(js_body: str):
    """workspace_engine.gs と棚コードを読み込んで Node 上で関数を実行する。"""
    src = (
        (ROOT / "workspace_engine.gs").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "ws_shelves" / "sheet_make.gs").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "ws_shelves" / "sheet_filter.gs").read_text(encoding="utf-8")
    )
    script = (
        "var PropertiesService={getScriptProperties:function(){return {getProperty:function(){return null;},setProperty:function(){}};}};\n"
        "var Charts={ChartType:{COLUMN:'COLUMN',BAR:'BAR',LINE:'LINE',PIE:'PIE',AREA:'AREA',SCATTER:'SCATTER'}};\n"
        "var SHELF={};\n"
        + src
        + "\n"
        + js_body
        + "\nconsole.log(JSON.stringify(__out));\n"
    )
    res = subprocess.run(
        ["node", "-"],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_rgb_supports_variants():
    out = _run_node("""
      __out = {
        kiiro: rgb_('黄色'),
        usu_hai: rgb_('薄い灰色'),
        usu_gray: rgb_('薄いグレー'),
        mizuiro: rgb_('水色'),
        chairo: rgb_('茶色'),
        usu_aka: rgb_('薄い赤')
      };
    """)
    assert out["kiiro"] == "#FFFF00"
    assert out["usu_hai"] == "#F2F2F2"
    assert out["usu_gray"] == "#F2F2F2"
    assert out["mizuiro"] == "#00FFFF"
    assert out["chairo"] == "#8B4513"
    assert out["usu_aka"] == "#FCE4D6"


def test_format_do_blocked_asks_user_approval():
    wm = gas_workspace.WorkspaceManager.__new__(gas_workspace.WorkspaceManager)
    txt = wm.format_do(
        {"ok": False, "blocked": True, "needs_ok": True, "error": "広い削除です。消える数: 10。"}
    )
    assert "止めました:" in txt
    assert "ユーザーに見せて確認" in txt
    assert "ok=True" in txt


def test_chart_new_supports_comma_separated_ranges():
    out = _run_node("""
      var added = [], pos = null, inserted = 0;
      var mkRg = function(a1, r, lc) {
        return {
          getA1Notation: function(){ return a1; },
          getRow: function(){ return r; },
          getLastRow: function(){ return 22; },
          getLastColumn: function(){ return lc; }
        };
      };
      var sh = {
        getName: function(){ return '経費'; },
        getRange: function(s){
          if (s === 'B1:B22') return mkRg('B1:B22', 1, 2);
          if (s === 'G1:G22') return mkRg('G1:G22', 1, 7);
          return mkRg(s, 1, 1);
        },
        newChart: function(){
          return {
            setChartType: function(){ return this; },
            addRange: function(rg){ added.push(rg.getA1Notation()); return this; },
            setOption: function(){ return this; },
            setPosition: function(r, c){ pos = [r, c]; return this; },
            build: function(){ return {}; }
          };
        },
        insertChart: function(){ inserted++; }
      };
      var ctx = { curSheet: '経費', logs: [], ss: { getSheetByName: function(){ return sh; }, getSheets: function(){ return [sh]; } } };
      function sheetCtx_(c){ return sh; }
      function chg_(c, s, a1, msg){ c.logs.push({a1: a1, msg: msg}); }
      SHELF['chart.new'](ctx, { type: 'line', range: 'B1:B22, G1:G22', title: '経費推移' });
      __out = { added: added, pos: pos, inserted: inserted, log: ctx.logs[0] };
    """)
    assert out["added"] == ["B1:B22", "G1:G22"]
    assert out["pos"] == [1, 9]
    assert out["inserted"] == 1
    assert out["log"]["a1"] == "B1:B22,G1:G22"


def test_split_col_insert_avoids_guard_overwrite():
    out = _run_node("""
      var insertedAfter = null, writtenA1 = null, writtenVals = null;
      var sh = {
        getName: function(){ return '名簿'; },
        insertColumnsAfter: function(col, n){ insertedAfter = [col, n]; },
        getRange: function(r, c, nr, nc){
          return {
            getA1Notation: function(){ return 'B2:C3'; },
            getValues: function(){ return [['山田 太郎'], ['佐藤 花子']]; },
            setValues: function(v){ writtenA1 = [r, c, nr, nc]; writtenVals = v; }
          };
        }
      };
      function sheetCtx_(){ return sh; }
      function findTable_(){ return { headerRow: 1, firstCol: 1, lastCol: 4, firstData: 2, lastData: 3, vals: [['番号', '氏名', '電話', '住所']] }; }
      function colIndexOf_(t, c){ return 2; }
      function a1_(r, c, nr, nc){ return 'B2:C3'; }
      function chg_(){}
      function guardOverwrite_(){ throw new Error('should not call guardOverwrite_'); }
      var ctx = { ok: false, logs: [] };
      SHELF['split.col'](ctx, { col: '氏名', by: 'space', insert: true });
      __out = { insertedAfter: insertedAfter, writtenA1: writtenA1, writtenVals: writtenVals };
    """)
    assert out["insertedAfter"] == [2, 1]
    assert out["writtenA1"] == [2, 2, 2, 2]
    assert out["writtenVals"] == [["山田", "太郎"], ["佐藤", "花子"]]


def test_ws_do_docstring_and_sheet_delete_avoid_excess_askback():
    import gas_ws_shot as shot
    desc = shot.ws_do_description()
    assert "聞き返さず ok なしで即撃つ" in desc
    assert "消す・上書きの ok=True は" in desc
    assert "名指しで 1 つに決まるか" in desc
    assert len([ln for ln in desc.splitlines() if ln.strip()]) <= 4
    delete_card = next(
        s for s in gas_workspace.CATALOG.shelves if s.get("name") == "sheet.delete"
    )
    assert "質問する" not in str(delete_card.get("diff", ""))
    ws_md = (ROOT / "WORKSPACE.md").read_text(encoding="utf-8")
    assert "聞き返さず `ok` なしで即実行" in ws_md


def test_chart_new_accepts_summary_sheet_name():
    out = _run_node("""
      var added = [], pos = null, inserted = 0;
      var mkRg = function(sname, a1, lc) {
        return {
          getSheet: function(){ return { getName: function(){ return sname; } }; },
          getA1Notation: function(){ return a1; },
          getRow: function(){ return 1; },
          getLastRow: function(){ return 3; },
          getLastColumn: function(){ return lc; }
        };
      };
      var sumRg = mkRg('集計', 'A1:B3', 2);
      var sumSh = {
        getName: function(){ return '集計'; },
        getLastRow: function(){ return 4; },
        getLastColumn: function(){ return 2; },
        getRange: function(r, c, nr, nc){
          if (nr === 3) return mkRg('集計', 'A1:B3', 2);
          return { getValues: function(){ return [['分類', '現在庫'], ['A', 10], ['B', 20], ['合計', 30]]; } };
        }
      };
      var mainSh = {
        getName: function(){ return '在庫一覧'; },
        getLastColumn: function(){ return 9; },
        newChart: function(){
          return {
            setChartType: function(){ return this; },
            addRange: function(rg){ added.push(rg.getSheet().getName() + '!' + rg.getA1Notation()); return this; },
            setOption: function(){ return this; },
            setPosition: function(r, c){ pos = [r, c]; return this; },
            build: function(){ return {}; }
          };
        },
        insertChart: function(){ inserted++; }
      };
      var ctx = {
        curSheet: '在庫一覧',
        logs: [],
        ss: {
          getSheetByName: function(n){ return n === '集計' ? sumSh : (n === '在庫一覧' ? mainSh : null); },
          getSheets: function(){ return [mainSh, sumSh]; }
        }
      };
      function sheetCtx_(c){ return mainSh; }
      function chg_(c, s, a1, msg){ c.logs.push({sh: s.getName(), a1: a1, msg: msg}); }
      SHELF['chart.new'](ctx, { type: 'column', range: '集計' });
      __out = { added: added, pos: pos, inserted: inserted, log: ctx.logs[0] };
    """)
    assert out["added"] == ["集計!A1:B3"]
    assert out["pos"] == [1, 11]
    assert out["inserted"] == 1
    assert out["log"]["sh"] == "在庫一覧"
    assert out["log"]["a1"] == "集計!A1:B3"


def test_ws_look_and_shelves_prevent_f10_and_f4():
    import ast
    src = (ROOT / "gas_mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    look_doc = next(
        ast.get_docstring(n) for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "ws_look"
    )
    assert "1 回で済む" in look_doc
    assert "確認の ws_look は撃たない" in look_doc
    cards = {s["name"]: s for s in gas_workspace.CATALOG.shelves}
    assert "seiri" in cards["tidy"]["diff"]
    assert "ok 不要" in cards["seiri"]["diff"]
    assert "あいうえお順" in cards["sort"]["diff"]
    assert "既定は「集計」" in cards["summary"]["diff"]
    assert "元表の 2 列" in cards["chart.new"]["diff"]
    assert "range に" in cards["chart.new"]["diff"]
    assert "他列の値が違っても" in cards["dedupe"]["diff"]


