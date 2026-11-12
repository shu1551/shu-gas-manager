# -*- coding: utf-8 -*-
"""
Workspace マネージャー 2 号機・段 0（目録の土台）の試験。通信なし。
- 札の読み方・形の検査・Catalog.gs
- 共通部に棚の名前の決め打ちが無いこと
- 19 本の「控えるシート」「変更なしの判定」が段 0 の前（旧エンジンの決め打ち）と同じこと
  （エンジンの JS を node でそのまま動かして比べる。node が無ければ飛ばす）
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import gas_workspace as gw
import gas_ws_catalog as cat_mod

HERE = Path(__file__).resolve().parent

LEGACY_NAMES = [
    "table.new", "sheet.add", "tidy", "seiri", "renumber", "width", "total", "summary", "sort", "write", "format", "rows", "replace",
    "doc.new", "doc.append", "doc.replace", "doc.section", "doc.table", "doc.style",
]

# 段 1 で足した束ねた棚の別名 9 本
ALIAS_NAMES = ["rows.insert", "rows.delete", "rows.move", "cols.insert", "cols.delete", "cols.move", "sheet.rename", "sheet.move", "filter.where"]
ALL_NAMES = LEGACY_NAMES + ALIAS_NAMES

# 段 0 の前のエンジン（workspace_engine.gs 1297 行版）の、控えるシートと変更なしの判定。棚名の決め打ちのまま写してある
LEGACY_JS = r"""
function legacyTouched_(ctx, ops) {
  var ss = ctx.ss, seen = {}, out = [];
  var add = function (name) {
    var s = name ? ss.getSheetByName(name) : null;
    if (s && !seen[s.getSheetId()]) { seen[s.getSheetId()] = 1; out.push(s); }
  };
  var def = ctx.sheetName || ss.getSheets()[0].getName();
  ops.forEach(function (op) {
    if (op.shelf === 'table.new' || op.shelf === 'summary') { if (op.shelf === 'summary') add(op.sheet || def); add(op.into || (op.shelf === 'table.new' ? op.sheet : null)); return; }
    if (op.shelf === 'sheet.add') { add(op.name); add(op.rename && op.rename.from); add(op.move && op.move.name); if (op.rename || op.move) ss.getSheets().forEach(function (s) { add(s.getName()); }); return; }
    add(op.sheet || def);
  });
  return out;
}
function legacyNoop_(ops, entry, ctx) {
  if (ctx.createdSheets.length) return false;
  if (ops.some(function (o) { return o.shelf === 'width' || o.shelf === 'doc.style'; })) return false;
  if (ctx.kind === 'sheet') {
    if (!entry.sheets || !entry.sheets.length) return false;
    return entry.sheets.every(function (b) { return sameFinger_(entry.before[b.id], entry.after[b.id]); });
  }
  return sameFinger_(entry.beforeDoc, entry.afterDoc);
}
"""

HARNESS_JS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctxv = vm.createContext({ console: console, __input: input, DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
const driver = `
function fakeSs_(names) {
  var sheets = names.map(function (n, i) { return { getName: function () { return n; }, getSheetId: function () { return i + 1; } }; });
  return { getSheetByName: function (n) { return sheets.filter(function (s) { return s.getName() === n; })[0] || null; }, getSheets: function () { return sheets; } };
}
var __out = null;
(function () {
  var res = [], ss = fakeSs_(__input.sheets);
  var fin = function (a) { return { rows: 1, cols: 1, d: a, n: 1 }; };
  var mk = function (names, c) {
    var e = { sheets: names.map(function (n) { return { id: ss.getSheetByName(n).getSheetId() }; }), before: {}, after: {}, beforeDoc: fin('a'), afterDoc: fin(c.same ? 'a' : 'b') };
    e.sheets.forEach(function (b) { e.before[b.id] = fin('a'); e.after[b.id] = fin(c.same ? 'a' : 'b'); });
    return e;
  };
  __input.cases.forEach(function (c) {
    var ctx = { ss: ss, sheetName: c.cur || '', kind: c.kind, createdSheets: c.created ? ['x'] : [], changed: c.changed };
    var nu = touchedSheets_(ctx, c.ops).map(function (s) { return s.getName(); });
    var old = legacyTouched_(ctx, c.ops).map(function (s) { return s.getName(); });
    res.push({ id: c.id, nu: nu, old: old, nuNoop: isNoop_(c.ops, mk(nu, c), ctx), oldNoop: legacyNoop_(c.ops, mk(old, c), ctx) });
  });
  __out = JSON.stringify(res);
})();
`;
vm.runInContext(input.engine + '\n' + input.catalog + '\n' + input.legacy + '\n' + driver, ctxv);
console.log(ctxv.__out);
"""


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


needs_node = pytest.mark.skipif(not _node_ok(), reason="node が無い")


# ---------------------------------------------------------------- 札・目録
def test_catalog_loads_all_shelves_and_check_passes():
    c = gw.CATALOG
    assert set(ALL_NAMES) <= set(c.names())          # 段 0・1 の棚は残っている（段 3 以降で増える）
    assert cat_mod.check(c) == []
    # 文書の棚は doc、ほかは sheet（分類: 文書 から決まる）
    assert {n for n in c.names() if c.by_name[n]["kind"] == "doc"} == {n for n in ALL_NAMES if n.startswith("doc.")}


def test_shelves_table_is_built_from_cards_not_handwritten():
    spec = gw.SHELVES["table.new"]
    assert spec["kind"] == "sheet" and spec["req"] == ["headers"] and "sheet" in spec["keys"] and "rows" in spec["keys"]
    assert gw.SHELVES["sheet.add"]["any"] == ["name", "rename", "move"]
    assert "sheet" not in gw.SHELVES["doc.style"]["keys"]            # 文書の棚に sheet は無い
    src = Path(gw.__file__).read_text(encoding="utf-8")
    assert not re.search(r"SHELVES\s*=\s*\{\s*\n\s*\"", src)         # 手書きの表は無い


def test_common_files_have_no_hardcoded_shelf_names():
    assert cat_mod.find_hardcoded_names(gw.CATALOG) == []
    # 共通部の 3 ファイルに、19 本の名前が「棚の名前として」出てこないことを、別の書き方でも確かめる
    for fn in cat_mod.HARDCODE_FILES:
        text = (HERE / fn).read_text(encoding="utf-8")
        for n in ALL_NAMES:
            if "." in n:
                assert f"'{n}'" not in text and f'"{n}"' not in text, (fn, n)
        assert not re.search(r"SHELF\[\s*['\"]", text), fn


def test_hardcode_detector_catches_a_planted_name(tmp_path):
    (tmp_path / "workspace_engine.gs").write_text("if (op.shelf === 'sheet.add') {}\nvar x = SHELF['table.new'];\n", encoding="utf-8")
    hits = cat_mod.find_hardcoded_names(gw.CATALOG, root=tmp_path)
    assert len(hits) >= 2


def test_card_parser_rules():
    good = "// 棚: a.b\n// 題: テスト\n// 分類: 範囲\n// 語: ああああ|いいいい|うううう|ええええ\n// 引数: x*=文字, y=数\n// 例: 「やって」 → {\"shelf\":\"a.b\",\"x\":\"1\"}\n// 触る: 値\nSHELF['a.b'] = function (ctx, op) {};\n"
    s = cat_mod.parse_text(good, "t.gs")[0]
    assert s["name"] == "a.b" and s["kind"] == "sheet" and s["backup"] == ["今"] and [a["name"] for a in s["args"]] == ["x", "y"]
    bad = {
        "知らない見出し": good.replace("// 触る: 値", "// 触る: 値\n// 違う: 何か"),
        "名前が違う": good.replace("SHELF['a.b']", "SHELF['a.c']"),
        "分類が無い": good.replace("// 分類: 範囲", "// 分類: ほか"),
        "語が少ない": good.replace("|うううう|ええええ", ""),
        "語が 1 字": good.replace("ああああ", "あ"),
        "sheet を書いた": good.replace("x*=文字, y=数", "x*=文字, sheet=シート"),
        "触る項目が違う": good.replace("// 触る: 値", "// 触る: ぬ"),
        "例が引数に合わない（検査）": None,
        "札が無い": "SHELF['a.b'] = function () {};\n",
    }
    for why, text in bad.items():
        if text is None:
            continue
        with pytest.raises(cat_mod.CatalogError):
            cat_mod.parse_text(text, "t.gs")
    # 例が引数に合わない・守りが札と食い違うのは check が止める
    wrong_ex = cat_mod.Catalog(cat_mod.parse_text(good.replace('"x":"1"', '"zzz":"1"'), "t.gs"))
    assert any("引数に合いません" in p for p in cat_mod.check(wrong_ex))
    unguarded = cat_mod.Catalog(cat_mod.parse_text(good.replace("// 触る: 値", "// 危ない: 消す\n// 触る: 値"), "t.gs"))
    assert any("guardDelete_" in p for p in cat_mod.check(unguarded))
    guarded_no_card = cat_mod.Catalog(cat_mod.parse_text(good.replace("{};", "{ guardDelete_(ctx, 'x'); };"), "t.gs"))
    assert any("危ない: 消す" in p for p in cat_mod.check(guarded_no_card))


def test_dangerous_cards_match_engine_guards():
    danger = {n for n in gw.CATALOG.names() if gw.CATALOG.by_name[n]["danger"] == "消す"}
    assert {"seiri", "summary", "rows", "doc.section", "rows.delete", "cols.delete"} <= danger   # 別名は呼び先の守りを引き継ぐ


def test_catalog_gs_content_and_order():
    gs = cat_mod.build_catalog_gs(gw.CATALOG)
    assert gs.startswith("// Catalog.gs") and "var CATALOG = {" in gs
    obj = json.loads(gs[gs.index("{", gs.index("var CATALOG")):gs.rindex("}") + 1])
    assert sorted(obj) == sorted(gw.CATALOG.names()) and set(ALL_NAMES) <= set(obj)
    assert obj["rows"]["danger"] == "消す" and obj["width"]["touch"] == ["幅"] and obj["sheet.add"]["backup"] == ["名前", "全部"]
    assert obj["doc.new"]["kind"] == "doc" and obj["tidy"]["kind"] == "sheet"


def test_engine_files_order_and_fingerprint(tmp_path):
    mgr = gw.WorkspaceManager(state_path=tmp_path / "s.json")
    files = mgr._engine_files(split=True)
    names = [f["name"] for f in files]
    assert names[:3] == ["appsscript", "Engine", "Catalog"] and names[3:] == sorted(names[3:])
    assert "doc" in names and "sheet_make" in names
    one = mgr._engine_files()
    assert [f["name"] for f in one] == ["appsscript", "Engine"]
    body = one[1]["source"]
    assert body.index("var SHELF = {}") < body.index("var CATALOG") < body.index("SHELF['table.new']")
    assert mgr.engine_version() in body
    # 棚のファイルを 1 字変えると版が変わる（指紋は全ファイルの連結から）
    eng = tmp_path / "workspace_engine.gs"
    shutil.copy(HERE / "workspace_engine.gs", eng)
    shutil.copytree(HERE / "ws_shelves", tmp_path / "ws_shelves")
    m2 = gw.WorkspaceManager(state_path=tmp_path / "s2.json", engine_path=eng)
    v1 = m2.engine_version()
    assert v1 == mgr.engine_version()
    p = tmp_path / "ws_shelves" / "sheet_range.gs"
    p.write_text(p.read_text(encoding="utf-8") + "\n// 手入れ\n", encoding="utf-8")
    assert m2.engine_version() != v1


def test_engine_all_file_has_every_shelf():
    text = Path(gw.ENGINE_SOURCE).read_text(encoding="utf-8")
    assert sorted(re.findall(r"SHELF\['([\w.]+)'\]\s*=", text)) == sorted(gw.CATALOG.names())


def test_validate_ops_from_cards_keeps_old_behaviour(tmp_path):
    mgr = gw.WorkspaceManager(state_path=tmp_path / "s.json")
    bad = [
        ([{"shelf": "table.new", "headers": "x"}], "headers は配列です"),
        ([{"shelf": "table.new", "headers": ["a"], "rows": [1]}], "rows は行の配列の配列です"),
        ([{"shelf": "rows", "rows": [3], "action": "bogus"}], "action は insert・delete・move です"),
        ([{"shelf": "doc.section", "heading": "a", "action": "x"}], "action は replace・delete です"),
        ([{"shelf": "rows", "rows": [0]}], "行番号は 1 以上"),
        ([{"shelf": "doc.style", "sheet": "s"}], "引数「sheet」はありません"),
    ]
    for ops, pat in bad:
        with pytest.raises(gw.WorkspaceError, match=pat):
            mgr.validate_ops(ops)
    # 列[] に文字 1 つ・行[] に整数 1 つは通り、撃つ前に配列にそろう
    assert mgr.validate_ops([{"shelf": "total", "cols": "金額"}, {"shelf": "rows", "rows": 3}]) == "sheet"
    assert mgr.catalog.normalize_op({"shelf": "total", "cols": "金額"})["cols"] == ["金額"]
    assert mgr.catalog.normalize_op({"shelf": "rows", "rows": 3})["rows"] == [3]


# ---------------------------------------------------------------- 19 本の控え・変更なしの判定（前と同じ）
def _cases():
    sample = {
        "table.new": {"headers": ["a"], "sheet": "S2"},
        "sheet.add": {"name": "S3"},
        "tidy": {}, "seiri": {}, "renumber": {"col": "A"}, "width": {"col": "A", "width": 90}, "total": {},
        "summary": {"by": "a", "values": ["b"], "into": "S3"}, "sort": {"col": "A"}, "write": {"cells": {"A1": 1}},
        "format": {"range": "A1", "bold": True}, "rows": {"rows": [3]}, "replace": {"find": "a"},
        "doc.new": {"markdown": "x"}, "doc.append": {"markdown": "x"}, "doc.replace": {"find": "a"},
        "doc.section": {"heading": "h", "markdown": "x"}, "doc.table": {"rows": [["a"]]}, "doc.style": {},
    }
    cases = []
    for n in LEGACY_NAMES:
        kind = "doc" if n.startswith("doc.") else "sheet"
        for variant, extra in (("既定", {}), ("sheet 指定", {"sheet": "S2"} if kind == "sheet" else {})):
            for same in (True, False):
                for changed in ([], ["x"]):
                    op = {"shelf": n, **sample[n], **extra}
                    cases.append({"id": f"{n}|{variant}|same={same}|changed={bool(changed)}", "ops": [op], "kind": kind, "same": same,
                                  "changed": changed, "cur": "S1", "created": False})
    # 束ねた棚の別の形（改名・移動）、2 本の組み合わせ
    for same in (True, False):
        for changed in ([], ["x"]):
            for ops in ([{"shelf": "sheet.add", "rename": {"from": "S2", "to": "S9"}}],
                        [{"shelf": "sheet.add", "move": {"name": "S2", "index": 1}}],
                        [{"shelf": "width", "col": "A", "width": 9}, {"shelf": "tidy"}],
                        [{"shelf": "summary", "by": "a", "values": ["b"]}, {"shelf": "sort", "col": "A"}],
                        [{"shelf": "tidy"}, {"shelf": "format", "range": "A1", "bold": True}]):
                cases.append({"id": f"組み合わせ {json.dumps(ops, ensure_ascii=False)}|{same}|{bool(changed)}", "ops": ops, "kind": "sheet", "same": same,
                              "changed": changed, "cur": "S1", "created": False})
    # 新しいシートを作った回は変更なしにしない
    cases.append({"id": "作成あり", "ops": [{"shelf": "tidy"}], "kind": "sheet", "same": True, "changed": [], "cur": "S1", "created": True})
    return cases


def _run_node():
    texts = dict(gw._engine_texts())
    payload = {"engine": texts["Engine"], "catalog": texts["Catalog"], "legacy": LEGACY_JS, "sheets": ["S1", "S2", "S3"], "cases": _cases()}
    r = subprocess.run(["node", "-e", HARNESS_JS], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


@needs_node
def test_noop_decision_and_backup_sheets_same_as_before_for_all_19():
    res = _run_node()
    assert res
    # 変更なしの判定は全部同じ。ただし width／doc.style を含む組が「changed 空」で来る場合は除く
    # （この 2 本は必ず変更を報告する。旧は常に false・新は changed で決める＝現実には同じ答えになる）
    unreal = {c["id"] for c in _cases() if not c["changed"] and any(o["shelf"] in ("width", "doc.style") for o in c["ops"])}
    diff_noop = [r["id"] for r in res if r["nuNoop"] != r["oldNoop"] and r["id"] not in unreal]
    assert diff_noop == [], diff_noop[:5]
    # 控えるシートは、束ねた棚の sheet.add（全部を控える）と table.new（sheet 指定なしでも今のシートを控える）を除いて同じ
    allowed = ("sheet.add", "table.new")
    diff_bk = [r for r in res if r["nu"] != r["old"] and not any(a in r["id"] for a in allowed)]
    assert diff_bk == [], [(r["id"], r["old"], r["nu"]) for r in diff_bk[:5]]
    # 例外 2 本は「前の控えを必ず含む」（控えが減ることは無い）
    for r in res:
        if r["nu"] != r["old"]:
            assert set(r["old"]) <= set(r["nu"]), r["id"]


@needs_node
def test_noop_for_width_and_doc_style_is_never_true_when_changed():
    res = _run_node()
    for r in res:
        if ("width|" in r["id"] or "doc.style|" in r["id"]) and "changed=True" in r["id"]:
            assert r["nuNoop"] is False and r["oldNoop"] is False, r["id"]
    created = [r for r in res if r["id"] == "作成あり"][0]
    assert created["nuNoop"] is False and created["oldNoop"] is False
