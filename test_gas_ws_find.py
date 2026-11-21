# -*- coding: utf-8 -*-
"""
Workspace マネージャー 2 号機・段 1（棚を引く）の試験。通信なし（本物の Google に出ようとしたら落ちる）。
"""

import io
import json
import socket
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import gas_workspace as gw
import gas_ws_catalog as cat_mod
import gas_ws_check
import gas_ws_find

HERE = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("本物の通信に出ようとしました（試験は通信なし）")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


@pytest.fixture
def mgr(tmp_path):
    m = gw.WorkspaceManager(client=object(), state_path=tmp_path / ".ws_state.json")
    m.misses_path = tmp_path / ".ws_misses.tsv"
    return m


@pytest.fixture(scope="module")
def finder():
    return gas_ws_find.Finder()


# ---------------------------------------------------------------- 引く
def test_normalization_and_synonyms(finder):
    s = finder.syn
    assert gas_ws_find.norm("タブを消して", s) == gas_ws_find.norm("タブ消して", s)       # 助詞の「を」を抜く
    assert gas_ws_find.norm("ヘッダー", s) == gas_ws_find.norm("見出し", s)                # 言い換えの表
    assert gas_ws_find.norm("ＡＢＣ　ｄｅｆ", s) == "abcdef"                               # NFKC・小文字・空白


def test_find_returns_right_shelf_and_card_format(mgr):
    out = mgr.find("3行目から5行目を消して")
    lines = out.splitlines()
    assert lines[0].startswith("棚の候補（") and "ws_do で撃つ" in lines[0]
    assert "rows.delete ＊消す｜行を削除する｜rows*=行[]" in out
    assert "例 「3行目から5行目を消して」→ {\"shelf\":\"rows.delete\"" in out
    assert "違い:" in out
    assert not any(ln.startswith("6. ") for ln in lines) and len([ln for ln in lines if ln[:2] in ("1.", "2.", "3.", "4.", "5.")]) <= 5   # 節が 1 つなら 5 本まで


def test_find_is_pure_python_no_engine_call(mgr):
    class Boom:
        def __getattr__(self, k):
            raise AssertionError("通信（client）は使わない: " + k)
    m = gw.WorkspaceManager(client=Boom(), state_path=mgr.state_path)
    m.misses_path = mgr.misses_path
    assert "棚の候補" in m.find("合計行を足して")
    assert "分類" in m.find("")


def test_find_special_asks(mgr):
    cat = mgr.find("分類:行と列")
    assert "rows.insert" in cat and "cols.move" in cat and "\n1. rows｜" not in cat      # 古い束ねた棚は引いても出ない
    one = mgr.find("棚:sort")
    assert one.startswith("1. sort｜表を並べ替える") and "引数: " in one
    assert "はありません" in mgr.find("棚:nothing")
    assert "作る: 1 本" in mgr.find("") and "文書: 26 本" in mgr.find("")


def test_find_kind_filter(mgr):
    assert "doc." not in mgr.find("表を作って", kind="sheet")
    assert "doc.new" in mgr.find("文書を作って", kind="doc") and "table.new" not in mgr.find("文書を作って", kind="doc")
    mgr._save({"target": {"id": "x" * 30, "kind": "doc", "name": "n"}})
    out = mgr.find("見出しを太字にして背景を青にして")        # 今の相手が文書なら文書の棚だけ
    assert "format" not in out.split("\n", 1)[1].replace("doc.style", "")


def test_two_clause_asks_include_both_sides(finder):
    picks, _, _ = finder.find("プルダウンにして、完了は灰色に")
    assert len(picks) <= gas_ws_find.MAX_N
    picks, _, _ = finder.find("3行目を消して、それから金額の合計行を足して")
    names = [s["name"] for s in picks]
    assert "rows.delete" in names and "total" in names and len(names) == len(set(names)) <= gas_ws_find.MAX_N


def test_guide_items(mgr):
    out = mgr.find("さっきの戻して")
    assert out.startswith("案内: 棚ではありません。ws_undo() を使います")
    assert "Workspace マネージャーの外" in mgr.find("これを PDF にしてメールで送って")


def test_weak_ask_is_logged_once_and_capped(mgr, tmp_path):
    out = mgr.find("宇宙旅行の予約をして")
    assert "近い棚は見つかりません" in out
    rows = mgr.misses_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and rows[0].split("\t")[1] == "宇宙旅行の予約をして"
    mgr.find("宇宙旅行の予約をして")
    assert len(mgr.misses_path.read_text(encoding="utf-8").splitlines()) == 1      # 同じ文は 1 回
    p = tmp_path / "m.tsv"
    for i in range(520):
        gas_ws_find.log_miss(f"文{i}", "x", 1, p)
    assert len(p.read_text(encoding="utf-8").splitlines()) == gas_ws_find.MISSES_MAX   # 500 行で古い物から捨てる
    assert "文519" in p.read_text(encoding="utf-8") and "文0\t" not in p.read_text(encoding="utf-8")


def test_old_bundled_shelves_are_not_searchable_but_still_valid(mgr):
    out = mgr.find("行を削除して")
    assert "\n1. rows｜" not in "\n" + out and "rows.delete" in out
    # 古い名前・古い引数は今までどおり通る
    for op in ({"shelf": "rows", "rows": [3]}, {"shelf": "rows", "action": "move", "cols": ["A"], "from": "A", "to": "B"},
               {"shelf": "sort", "where": {"col": "部署", "equals": "営業"}}, {"shelf": "sort", "col": "A", "filter": True},
               {"shelf": "sheet.add", "rename": {"from": "a", "to": "b"}}, {"shelf": "sheet.add", "move": {"name": "a", "index": 1}}):
        assert mgr.validate_ops([op]) == "sheet"


# ---------------------------------------------------------------- ws_do の返し方（第 4.4 節）
def test_do_unknown_shelf_returns_near_cards_not_all_names(mgr):
    with pytest.raises(gw.WorkspaceError) as ei:
        mgr.validate_ops([{"shelf": "行を削除"}])
    msg = str(ei.value)
    assert msg.startswith("棚「行を削除」はありません") and "rows.delete" in msg
    assert len([ln for ln in msg.splitlines() if ln[:2] in ("1.", "2.", "3.", "4.", "5.")]) <= 3
    assert "、".join(gw.CATALOG.names()[:6]) not in msg
    with pytest.raises(gw.WorkspaceError) as e2:
        gw.WorkspaceManager.parse_ops("[]")
    assert "棚の一覧" not in str(e2.value)


def test_do_bad_args_return_that_shelfs_card(mgr):
    with pytest.raises(gw.WorkspaceError) as ei:
        mgr.validate_ops([{"shelf": "rows.delete", "row": [3]}])
    msg = str(ei.value)
    assert "引数「row」はありません" in msg and "その棚の札" in msg and "rows.delete" in msg and "例 「" in msg
    with pytest.raises(gw.WorkspaceError, match="「rows」が要ります"):
        mgr.validate_ops([{"shelf": "rows.delete"}])


# ---------------------------------------------------------------- ws_look(ask=)
def test_look_ask_appends_cards_and_survives_look_failure(mgr, monkeypatch):
    monkeypatch.setattr(mgr, "_look", lambda **k: "対象: 見積書\nURL: u")
    out = mgr.look(ask="合計行を足して")
    assert out.startswith("対象: 見積書") and "棚の候補" in out and "total" in out
    assert mgr.look() == "対象: 見積書\nURL: u"                    # ask が無ければ今まで通り（札を付けない）

    def _fail(**k):
        raise gw.WorkspaceError("今の相手が決まっていません。")
    monkeypatch.setattr(mgr, "_look", _fail)
    with pytest.raises(gw.WorkspaceError) as ei:
        mgr.look(ask="合計行を足して")
    assert "今の相手が決まっていません" in str(ei.value) and "棚の候補" in str(ei.value)   # 相手が見られなくても札は付く


def test_cli_ws_find(monkeypatch):
    import gas
    monkeypatch.setattr(sys, "argv", ["gas.py", "ws-find", "3行目から5行目を消して", "--why"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        gas.main()
    out = buf.getvalue()
    assert "rows.delete" in out and "点の内訳" in out


# ---------------------------------------------------------------- 別名 9 本（エンジンの JS をそのまま動かす）
def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


ALIAS_JS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctxv = vm.createContext({ console: console, DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext(`
  var __calls = [];
  ['rows', 'sheet.add', 'sort'].forEach(function (n) { SHELF[n] = function (ctx, op) { __calls.push({ to: n, op: op }); }; });
  var __res = [];
  __input.cases.forEach(function (c) { __calls = []; SHELF[c.shelf]({}, c.op); __res.push({ shelf: c.shelf, calls: __calls }); });
  var __out = JSON.stringify(__res);
`, Object.assign(ctxv, { __input: input }));
console.log(ctxv.__out);
"""


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_aliases_forward_to_the_old_shelves_with_the_old_arguments():
    cases = [
        {"shelf": "rows.insert", "op": {"shelf": "rows.insert", "at": 3, "count": 2}},
        {"shelf": "rows.delete", "op": {"shelf": "rows.delete", "rows": [3, 4]}},
        {"shelf": "rows.move", "op": {"shelf": "rows.move", "from": 5, "to": 2}},
        {"shelf": "cols.insert", "op": {"shelf": "cols.insert", "at": "C"}},
        {"shelf": "cols.delete", "op": {"shelf": "cols.delete", "cols": ["B"]}},
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "A", "to": "B"}},
        {"shelf": "sheet.rename", "op": {"shelf": "sheet.rename", "name": "a", "to": "b"}},
        {"shelf": "sheet.move", "op": {"shelf": "sheet.move", "name": "a", "index": 1}},
        {"shelf": "filter.where", "op": {"shelf": "filter.where", "col": "部署", "equals": "営業"}},
    ]
    texts = dict(gw._engine_texts())
    files = [texts["Engine"], texts["Catalog"]] + [t for n, t in gw._engine_texts() if n not in ("Engine", "Catalog")]
    r = subprocess.run(["node", "-e", ALIAS_JS], input=json.dumps({"files": files, "cases": cases}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    res = {x["shelf"]: x["calls"] for x in json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])}
    def one(name):
        assert len(res[name]) == 1, name
        return res[name][0]
    assert one("rows.insert") == {"to": "rows", "op": {"shelf": "rows", "action": "insert", "at": 3, "count": 2}}
    assert one("rows.delete")["op"] == {"shelf": "rows", "action": "delete", "rows": [3, 4]}
    assert one("rows.move")["op"] == {"shelf": "rows", "action": "move", "from": 5, "to": 2}
    assert one("cols.insert")["op"] == {"shelf": "rows", "action": "insert", "cols": ["C"], "at": "C"}
    assert one("cols.delete")["op"] == {"shelf": "rows", "action": "delete", "cols": ["B"]}
    assert one("cols.move")["op"] == {"shelf": "rows", "action": "move", "cols": ["A"], "from": "A", "to": "B"}
    assert one("sheet.rename") == {"to": "sheet.add", "op": {"shelf": "sheet.add", "rename": {"from": "a", "to": "b"}}}
    assert one("sheet.move")["op"] == {"shelf": "sheet.add", "move": {"name": "a", "index": 1}}
    assert one("filter.where") == {"to": "sort", "op": {"shelf": "sort", "where": {"col": "部署", "equals": "営業"}}}


# ---------------------------------------------------------------- 問題集と ws-check
def test_ws_check_passes_and_every_shelf_has_four_questions():
    problems, notes, summary, results = gas_ws_check.run(write=False)
    assert problems == [], problems[:5]
    assert summary.startswith(f"棚 {len(gw.CATALOG.names())} 本・問題 ")
    qs = gas_ws_check.load_questions()
    count = {}
    for exp, _, src in qs:
        if "ijiwaru" not in src:
            for e in exp:
                count[e] = count.get(e, 0) + 1
    for s in gw.CATALOG.shelves:
        if s["searchable"]:
            assert count.get(s["name"], 0) >= 4, s["name"]
        else:
            assert count.get(s["name"], 0) == 0                # 古い名前の棚は問題を足さない（第 10 章）


def test_ws_check_reports_a_planted_miss_and_a_dropped_shelf(tmp_path, monkeypatch):
    exam = tmp_path / "exam"
    exam.mkdir()
    for p in (HERE / "ws_exam").glob("phrases_*.tsv"):
        (exam / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (exam / "phrases_x.tsv").write_text("total\tまったく関係のない宇宙旅行の話\n", encoding="utf-8")
    problems, _, _, _ = gas_ws_check.run(write=False, exam_dir=exam, answers_path=tmp_path / "none.tsv")
    assert any("宇宙旅行" in p and "札の中にありません" in p for p in problems)
    # 前回は入っていた期待の棚が今回は入っていない → 別に並べて止める
    ans = tmp_path / "answers.tsv"
    ans.write_text("合計行を足して\ttotal,seiri\n宇宙旅行の予約をして\ttotal\n", encoding="utf-8")
    (exam / "phrases_x.tsv").write_text("total\t宇宙旅行の予約をして\n", encoding="utf-8")
    problems, _, _, _ = gas_ws_check.run(write=False, exam_dir=exam, answers_path=ans)
    assert any(p.startswith("前回は札の中にあった total") for p in problems)


def test_ws_check_writes_answers_only_when_clean(tmp_path):
    ans = tmp_path / "answers.tsv"
    problems, _, _, _ = gas_ws_check.run(write=True, answers_path=ans)
    assert problems == [] and ans.exists()
    lines = [ln for ln in ans.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    assert len(lines) > 100 and all("\t" in ln for ln in lines)


def test_description_volume_is_pinned():
    lines = gas_ws_check.mcp_doc_lines()
    assert set(lines) == {"ws_look", "ws_find", "ws_do", "ws_undo"}
    assert all(n <= 4 for n in lines.values()) and sum(lines.values()) <= 16
    assert len(gas_ws_check.doc_shelf_names(gw.CATALOG)) <= 5      # 手順書に棚の名前の表は無い（棚を足しても 1 字も変わらない）


def test_misses_file_and_engine_all_file_are_ignored_by_git():
    ignore = (HERE / ".gitignore").read_text(encoding="utf-8")
    assert ".ws_misses.tsv" in ignore and ".ws_engine_all.gs" in ignore


def test_common_files_still_free_of_shelf_names_after_stage1():
    assert cat_mod.find_hardcoded_names(gw.CATALOG) == []
    assert "gas_ws_find.py" in cat_mod.HARDCODE_FILES


# ---------------------------------------------------------------- 移動の to は「動かした後の位置」
MOVE_JS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctxv = vm.createContext({ console: console, SpreadsheetApp: { flush: function () { } }, DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext(`
  var __log = [];
  var fakeSh = {
    getName: function () { return 'S'; },
    getRange: function (r, c, nr, nc) { return { r: r, c: c, nr: nr, nc: nc }; },
    moveColumns: function (rg, dest) { __log.push(['col', rg.c, dest]); },
    moveRows: function (rg, dest) { __log.push(['row', rg.r, rg.nr, dest]); }
  };
  sheetCtx_ = function () { return fakeSh; };
  var __res = [];
  __input.cases.forEach(function (c) {
    __log = [];
    SHELF[c.shelf]({ changed: [], notes: [] }, c.op);
    __res.push(__log);
  });
  var __out = JSON.stringify(__res);
`, Object.assign(ctxv, { __input: input }));
console.log(ctxv.__out);
"""


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_move_to_means_position_after_the_move():
    cases = [
        # 右へ 1 つ（C を D の位置へ）／左へ 1 つ／同じ位置／離れた右・左
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "C", "to": "D"}},
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "D", "to": "C"}},
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "C", "to": "C"}},
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "A", "to": "E"}},
        {"shelf": "cols.move", "op": {"shelf": "cols.move", "from": "E", "to": "A"}},
        {"shelf": "rows.move", "op": {"shelf": "rows.move", "from": 3, "to": 4}},
        {"shelf": "rows.move", "op": {"shelf": "rows.move", "from": 4, "to": 3}},
        {"shelf": "rows.move", "op": {"shelf": "rows.move", "from": 3, "to": 3}},
        {"shelf": "rows.move", "op": {"shelf": "rows.move", "from": 2, "to": 6, "count": 2}},   # 2 行ぶんを動かすと、先頭が 6 行目に来る
        {"shelf": "rows", "op": {"shelf": "rows", "action": "move", "from": 3, "to": 4}},         # 旧名もそろえる
        {"shelf": "rows", "op": {"shelf": "rows", "action": "move", "cols": ["C"], "from": "C", "to": "D"}},
    ]
    files = [t for _, t in gw._engine_texts()]
    r = subprocess.run(["node", "-e", MOVE_JS], input=json.dumps({"files": files, "cases": cases}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    res = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    assert res == [
        [["col", 3, 5]],          # C→D（右へ 1）: D の「手前」ではなく E の手前へ
        [["col", 4, 3]],          # D→C（左へ 1）
        [["col", 3, 3]],          # 同じ位置（何も起きない）
        [["col", 1, 6]],
        [["col", 5, 1]],
        [["row", 3, 1, 5]],
        [["row", 4, 1, 3]],
        [["row", 3, 1, 3]],
        [["row", 2, 2, 8]],
        [["row", 3, 1, 5]],
        [["col", 3, 5]],
    ]


def test_move_cards_say_to_is_the_position_after_the_move():
    for n in ("rows.move", "cols.move", "rows"):
        assert "動かした後" in gw.CATALOG.by_name[n]["diff"], n


# ---------------------------------------------------------------- 問題集の点検・札の区別（renumber と fill.series）
def test_every_shelf_keeps_two_fireable_questions():
    extras = gas_ws_check.load_extras()
    fire = {}
    for exp, ask, src in gas_ws_check.load_questions():
        if "ijiwaru" in src or extras.get(ask, {}).get("ask_ok"):
            continue
        for e in exp:
            fire[e] = fire.get(e, 0) + 1
    for s in gw.CATALOG.shelves:
        if s["searchable"]:
            assert fire.get(s["name"], 0) >= gas_ws_check.MIN_FIREABLE, s["name"]


def test_keyword_list_questions_are_marked_as_ask_back_ok():
    extras = gas_ws_check.load_extras()
    for exp, ask, src in gas_ws_check.load_questions():
        if " " in ask and "ijiwaru" not in src:        # 語の並びは頼みの文ではない（指す物が無い）
            assert extras[ask]["ask_ok"] is True, ask


def test_renumber_and_fill_series_cards_tell_each_other_apart():
    r, f = gw.CATALOG.by_name["renumber"], gw.CATALOG.by_name["fill.series"]
    assert "表の番号の列" in r["title"] and "fill.series" in r["diff"] and "見出しの名前" in r["diff"]
    assert "番地の範囲" in f["diff"] and "renumber" in f["diff"]
    assert f["examples"][0][0] == "A列に1から連番を入れて" and f["examples"][0][1]["range"] == "A2:A20"
    fd = gas_ws_find.Finder()
    picks, scores, _ = fd.find("A列に1から連番を入れて")
    assert picks[0]["name"] == "fill.series"
