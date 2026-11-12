# -*- coding: utf-8 -*-
"""
ws_do の速さ詰め（段 3 のあと）の試験。エンジンの JS を node でそのまま動かし、GAS の部品は偽物（呼び出し回数を数える）にする。
  ・内訳（ms）が返る  ・控えは控えブックのタブ一覧を 1 回だけ読む（列ごとに幅を読まない）
  ・台帳は成功した回に 1 回だけ書く（番号の先書きをしない・変更なしでは書かない）
  ・指紋が日本語を区別する（来期と今期）。昔の控えの指紋（版 1）は昔の数え方のまま比べられる
  ・控え・戻しの守り（ok なしで止まる・失敗で戻す）が今のまま効く
"""

import json
import subprocess

import pytest

import gas_workspace as gw


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _node_ok(), reason="node が無い")

HARNESS = r"""
const vm = require('vm'), fs = require('fs'), crypto = require('crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const counts = { getSheetsBook: 0, colWidth: 0, setLedger: 0, setProps: 0, deleteSheet: 0, copyTo: 0 };
const store = {};
function md5(buf) { return crypto.createHash('md5').update(buf).digest(); }
const Utilities = {
  DigestAlgorithm: { MD5: 'MD5' },
  Charset: { UTF_8: 'UTF_8' },
  // GAS の computeDigest(文字列) は非 ASCII を同じ物に潰す（実機で確かめた。来期＝今期）。偽物でもそれを真似る
  computeDigest: function (alg, v) { if (typeof v === 'string') return Array.from(md5(Buffer.from(v.replace(/[^\x00-\x7f]/g, '?'), 'utf8'))); return Array.from(md5(Buffer.from(v))); },
  base64Encode: function (b) { return Buffer.from(b).toString('base64'); },
  newBlob: function (s) { return { getBytes: function () { return Array.from(Buffer.from(s, 'utf8')); } }; },
  formatDate: function () { return '2026-11-12 00:00:00'; }
};
const PropertiesService = { getScriptProperties: function () { return {
  getProperty: function (k) { return store[k] === undefined ? null : store[k]; },
  setProperty: function (k, v) { counts.setProps++; if (k === 'LEDGER') counts.setLedger++; store[k] = v; } }; } };
let nextId = 1;
class Range {
  constructor(sh, r, c, nr, nc) { this.sh = sh; this.r = r; this.c = c; this.nr = nr; this.nc = nc; }
  _grid(f) { const o = []; for (let i = 0; i < this.nr; i++) { const row = []; for (let j = 0; j < this.nc; j++) row.push(f(this.sh.values[this.r - 1 + i][this.c - 1 + j])); o.push(row); } return o; }
  getFormulas() { return this._grid(() => ''); }
  getDisplayValues() { return this._grid(v => String(v)); }
  getBackgrounds() { return this._grid(() => '#ffffff'); }
  getFontWeights() { return this._grid(() => 'normal'); }
  getFontColors() { return this._grid(() => '#000000'); }
  getNumberFormats() { return this._grid(() => ''); }
  getHorizontalAlignments() { return this._grid(() => 'general'); }
}
class Sheet {
  constructor(book, name, values) { this.book = book; this.name = name; this.id = nextId++; this.values = values || [['a', 'b'], [1, 2]]; }
  getName() { return this.name; } setName(n) { this.name = n; }
  getSheetId() { return this.id; }
  getLastRow() { return this.values.length; } getLastColumn() { return this.values[0].length; }
  getRange(r, c, nr, nc) { return new Range(this, r, c, nr, nc); }
  getFrozenRows() { return 1; } getFrozenColumns() { return 0; }
  getIndex() { return this.book.sheets.indexOf(this) + 1; }
  getColumnWidth() { counts.colWidth++; return 100; }
  copyTo(book) { counts.copyTo++; const s = new Sheet(book, 'Copy of ' + this.name, JSON.parse(JSON.stringify(this.values))); book.sheets.push(s); return s; }
}
class Book {
  constructor(name) { this.name = name; this.sheets = []; this.id = 'B' + nextId++; }
  getId() { return this.id; } getName() { return this.name; } getUrl() { return 'u'; }
  getSheets() { if (this.name === 'keep') counts.getSheetsBook++; return this.sheets.slice(); }
  getSheetByName(n) { return this.sheets.filter(s => s.name === n)[0] || null; }
  deleteSheet(s) { counts.deleteSheet++; this.sheets.splice(this.sheets.indexOf(s), 1); }
  getNumSheets() { return this.sheets.length; }
}
const files = {};
const ss = new Book('target'); ss.sheets.push(new Sheet(ss, '表', [['見出し', 'x'], ['今期', 2]])); files['S'] = ss;
const keep = new Book('keep'); keep.sheets.push(new Sheet(keep, 'シート1', [['']]));   // 控えブックに最初からある白紙シート
const SpreadsheetApp = { openById: function (id) { return files[id]; }, create: function (n) { const b = new Book(n); files[b.id] = b; return b; }, flush: function () {} };
files[keep.id] = keep; store['BK_BOOK'] = keep.id;
const ctxv = vm.createContext({ console, Utilities, PropertiesService, SpreadsheetApp, DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext(`
  CATALOG['t.set'] = { kind: 'sheet', touch: ['値'], backup: ['今'], danger: '' };
  SHELF['t.set'] = function (ctx, op) { var sh = sheetCtx_(ctx, op); var before = sh.values[1][0]; sh.values[1][0] = op.v; if (before !== op.v) chg_(ctx, sh, 'A2', 'x'); else note_(ctx, '変更なし'); };
  CATALOG['t.boom'] = { kind: 'sheet', touch: ['値'], backup: ['今'], danger: '' };
  SHELF['t.boom'] = function (ctx, op) { var sh = sheetCtx_(ctx, op); sh.values[1][0] = 'こわれた'; throw new Error('boom'); };
`, ctxv);
ctxv.__input = input; ctxv.__files = files; ctxv.__counts = counts; ctxv.__store = store;
vm.runInContext(`
  var __out = [];
  __input.steps.forEach(function (s) {
    var c0 = JSON.parse(JSON.stringify(__counts));
    var res = runDo_({ target: { id: 'S', kind: 'sheet' }, ops: [{ shelf: s.shelf, v: s.v }], ok: false }, Date.now());
    var c1 = __counts, led = JSON.parse(__store['LEDGER'] || '{"seq":0,"items":[]}');
    __out.push({ step: s.name, ok: res.ok, changed: res.changed, ms: res.ms, backup: res.backup, notes: res.notes, dGetSheets: c1.getSheetsBook - c0.getSheetsBook, dColW: c1.colWidth - c0.colWidth,
      dLedger: c1.setLedger - c0.setLedger, seq: led.seq, items: led.items.length, cell: __files['S'].sheets[0].values[1][0], tabs: __files[__store['BK_BOOK']].sheets.map(function (x) { return x.name; }) });
  });
  var __fp = { v2: [digest_('来期', 2), digest_('今期', 2)], v1: [digest_('来期', 1), digest_('今期', 1)], def: [digest_('来期'), digest_('今期')] };
  __out.push({ fp: __fp });
  __out = JSON.stringify(__out);
`, ctxv);
console.log(ctxv.__out);
"""


def _run(steps):
    texts = [t for _, t in gw._engine_texts()]
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps({"files": texts, "steps": steps}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


def test_fingerprint_tells_japanese_text_apart_and_old_fingerprints_stay_comparable():
    out = _run([])
    fp = out[-1]["fp"]
    assert fp["v2"][0] != fp["v2"][1]            # UTF-8 で数える（来期≠今期）
    assert fp["def"][0] != fp["def"][1]          # 既定（版 2）
    assert fp["v1"][0] == fp["v1"][1]            # 版 1 ＝昔の数え方（日本語を区別できない）。昔の控えを比べるためだけに残す


def test_japanese_only_change_is_not_a_noop_and_keeps_its_backup_and_ledger():
    out = _run([{"name": "今期→来期", "shelf": "t.set", "v": "来期"}, {"name": "来期→今期", "shelf": "t.set", "v": "今期"}])
    a, b = out[0], out[1]
    assert a["ok"] and a["changed"] and a["backup"] and a["items"] == 1       # 変更あり: 台帳に残る・控えが残る
    assert b["ok"] and b["changed"] and b["backup"] and b["items"] == 2       # 日本語だけの変更も「変更なし」にしない
    assert any(t.startswith("ws") for t in b["tabs"])                           # 控えのタブが残っている（undo できる）


def test_noop_discards_backup_and_writes_no_ledger_and_does_not_burn_a_number():
    out = _run([{"name": "a", "shelf": "t.set", "v": "X"}, {"name": "same", "shelf": "t.set", "v": "X"}, {"name": "b", "shelf": "t.set", "v": "Y"}])
    a, same, b = out[0], out[1], out[2]
    assert a["dLedger"] == 1 and a["seq"] == 1
    assert same["changed"] == [] and same["backup"] == 0 and same["dLedger"] == 0 and same["items"] == 1     # 変更なし: 台帳に書かない
    assert not any(t.startswith("ws2_") for t in same["tabs"])                                                 # 控えは捨てた
    assert b["dLedger"] == 1 and b["seq"] == 2 and b["items"] == 2                                             # 番号は使い回され、飛ばない


def test_ledger_is_written_once_per_changing_call_and_ms_breakdown_comes_back():
    out = _run([{"name": "a", "shelf": "t.set", "v": "X"}])
    a = out[0]
    assert a["dLedger"] == 1                      # 番号の先書きと最後の書き込みの 2 回だったのを 1 回に
    for k in ("open", "seq", "backup", "finger0", "ops", "finger", "noop", "ledger", "total"):
        assert k in a["ms"], k
    assert a["ms"]["total"] >= 0


def test_backup_reads_backup_book_once_and_never_reads_column_widths():
    out = _run([{"name": "a", "shelf": "t.set", "v": "X"}])
    a = out[0]
    assert a["dGetSheets"] == 1                    # 控えブックのタブ一覧は 1 回だけ読む
    assert a["dColW"] == 0                         # 書く前に列ごとの幅を読まない（戻すときに控えのタブから読む）
    assert "シート1" not in a["tabs"]              # 最初からある白紙シートは外す


def test_failure_restores_and_does_not_persist_a_number_or_ledger_entry():
    out = _run([{"name": "ok", "shelf": "t.set", "v": "X"}, {"name": "boom", "shelf": "t.boom", "v": "Z"}])
    ok, boom = out[0], out[1]
    assert boom["ok"] is False                              # 失敗は失敗として返る（控えから戻す所は偽物では動かない。実機で確かめる）
    assert boom["dLedger"] == 0 and boom["items"] == 1


def test_old_backup_tabs_are_rotated_to_the_limit():
    steps = [{"name": f"s{i}", "shelf": "t.set", "v": f"v{i}"} for i in range(24)]
    out = _run(steps)
    last = out[len(steps) - 1]
    assert len([t for t in last["tabs"]]) <= 20          # BK_TABS_MAX 枚まで


# ---------------------------------------------------------------- Python 側の内訳（WS_TIMING）
class _Client:
    def __init__(self, ms):
        self.ms = ms
        self.posts = []

    def call_webapp(self, url, params=None, body=None, method="GET", key=None, timeout=15, use_auth=False, dev=False, no_rerun=False):
        self.posts.append(body)
        return {"status_code": 200, "data": {"ok": True, "target": {"id": "A" * 44, "name": "n", "kind": "sheet", "url": "u", "sheet": "s"},
                                              "changed": ["s!A1 x"], "notes": [], "remaining": [], "backup": 3, "ms": self.ms, "version": self.ver}}


def _mgr(tmp_path, ms, timing):
    c = _Client(ms)
    m = gw.WorkspaceManager(client=c, state_path=tmp_path / "s.json")
    c.ver = m.engine_version()
    m._save({"engine_sid": "E" * 40, "engine_url": "https://script.google.com/macros/s/x/dev", "engine_ver": m.engine_version(), "target": {"id": "A" * 44, "kind": "sheet", "name": "n"}})
    m.timing = timing
    return m, c


def test_timing_is_off_by_default_and_on_with_the_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("WS_TIMING", raising=False)
    ms = {"lock": 80, "open": 150, "seq": 70, "backup": 900, "finger0": 200, "ops": 300, "finger": 250, "noop": 0, "ledger": 90, "total": 2000}
    m, c = _mgr(tmp_path, ms, timing=False)
    out = m.do([{"shelf": "tidy"}])
    assert "内訳" not in out and 3 <= len(out.splitlines()) <= 5          # 普段の返事には出さない
    assert m.last_timing is not None and m.last_timing.engine["total"] == 2000
    m2, _ = _mgr(tmp_path, ms, timing=True)
    out2 = m2.do([{"shelf": "tidy"}])
    assert "内訳(秒)" in out2 and "準備" in out2 and "往復" in out2 and "返事の組み立て" in out2
    assert "エンジン内(秒): 鍵待ち 0.08" in out2 and "控え 0.90" in out2 and "台帳の書き込み 0.09" in out2


def test_timing_env_var_switches_it_on(tmp_path, monkeypatch):
    monkeypatch.setenv("WS_TIMING", "1")
    m = gw.WorkspaceManager(client=object(), state_path=tmp_path / "s.json")
    assert m.timing is True
    monkeypatch.setenv("WS_TIMING", "")
    assert gw.WorkspaceManager(client=object(), state_path=tmp_path / "s.json").timing is False


def test_format_timing_splits_roundtrip_into_engine_and_the_rest():
    t = gw._Timer()
    t.laps = {"検査": 0.01, "相手": 0.02, "状態": 0.03, "版": 0.04, "往復": 5.0, "返事": 0.01}
    t.engine = {"total": 3000, "backup": 1200}
    s = gw.format_timing(t)
    assert "準備 0.10" in s and "往復 5.00（エンジン内 3.00・残り＝通信と起動 2.00）" in s
