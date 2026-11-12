# -*- coding: utf-8 -*-
"""
並べて回す（lane）の試験。通信なし。エンジンの JS を node で動かして、錠・台帳・控えが lane ごとに分かれることを確かめ、
props の並べ回し（キュー・振り分け・書き出し）と「変わった所だけ回す」を偽のエンジンで確かめる。
"""

import json
import subprocess
import threading
import time

import pytest

import gas_workspace as gw
import gas_ws_props as P
import gas_ws_trial as TR


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = {}; const lockLog = [];
const ctxv = vm.createContext({ console, store, lockLog,
  PropertiesService: { getScriptProperties: function () { return { getProperty: function (k) { return store[k] === undefined ? null : store[k]; }, setProperty: function (k, v) { store[k] = String(v); }, deleteProperty: function (k) { delete store[k]; } }; } },
  LockService: { getScriptLock: function () { return { tryLock: function () { lockLog.push('try'); return true; }, releaseLock: function () { lockLog.push('rel'); } }; } },
  ContentService: { MimeType: { JSON: 1 }, createTextOutput: function (s) { return { s: s, setMimeType: function () { return this; } }; } },
  DocumentApp: new Proxy({}, { get: function () { return new Proxy({}, { get: function () { return 1; } }); } }) });
vm.runInContext(input.files.join('\n'), ctxv);
vm.runInContext('var __now = 1000000; Date.now = function () { return __now; }; var __out = null;\n' + input.script, ctxv);
console.log(JSON.stringify(ctxv.__out));
"""


def _run(script):
    files = [t for _, t in gw._engine_texts()]
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps({"files": files, "script": script}).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


SETUP = """
EXTRA_ACTIONS['trial_config'] = function (req) { setJson_('TRIAL_CFG', { ids: req.ids || [] }); if (req.bk_book) props_().setProperty('BK_BOOK', req.bk_book); return { ok: true }; };
EXTRA_ACTIONS['mark'] = function (req) { var l = ledger_(); l.seq++; l.items.push({ n: l.seq, tag: req.tag }); ledgerSave_(l); return { ok: true, seq: l.seq, lane: LANE, held: store['LOCK@' + LANE] || null }; };
EXTRA_ACTIONS['peek'] = function (req) { return { ok: true, seq: ledger_().seq, bk: props_().getProperty('BK_BOOK'), cfg: getJson_('TRIAL_CFG', null) }; };
function post(o) { return JSON.parse(doPost({ postData: { contents: JSON.stringify(o) } }).s); }
"""


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_ledger_and_backup_book_are_separate_per_lane_but_the_sandbox_list_is_shared():
    out = _run(SETUP + """
      post({ action: 'trial_config', ids: ['a', 'b'], bk_book: 'BK1' });
      post({ action: 'trial_config', lane: '2', ids: ['a', 'b'], bk_book: 'BK2' });
      post({ action: 'mark', tag: 'x' }); post({ action: 'mark', tag: 'y' });
      var m2 = post({ action: 'mark', lane: '2', tag: 'z' });
      __out = { l1: post({ action: 'peek' }), l2: post({ action: 'peek', lane: '2' }), l3: post({ action: 'peek', lane: '3' }), m2: m2,
                keys: Object.keys(store).sort() };
    """)
    assert out["l1"]["seq"] == 2 and out["l2"]["seq"] == 1 and out["l3"]["seq"] == 0       # 台帳が lane ごと
    assert out["l1"]["bk"] == "BK1" and out["l2"]["bk"] == "BK2" and out["l3"]["bk"] is None   # 控えのブックが lane ごと
    assert out["l1"]["cfg"] == out["l2"]["cfg"] == out["l3"]["cfg"] == {"ids": ["a", "b"]}     # 試験場の登録は共通
    assert "LEDGER" in out["keys"] and "LEDGER@2" in out["keys"] and "TRIAL_CFG" in out["keys"] and "TRIAL_CFG@2" not in out["keys"]


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_lane_lock_is_per_lane_and_the_script_lock_is_held_only_for_the_instant():
    out = _run(SETUP + """
      var r2 = post({ action: 'mark', lane: '2', tag: 'a' });
      var lockAfter = store['LOCK@2'] === undefined;                 // 終われば印は消える
      store['LOCK@3'] = String(Date.now() - 1000);                   // lane 3 は別の処理が走っている
      var busy3 = post({ action: 'mark', lane: '3', tag: 'b' });
      var ok4 = post({ action: 'mark', lane: '4', tag: 'c' });        // lane 4 は待たされない
      store['LOCK@5'] = String(Date.now() - 400000);                  // 古い印（切れた処理）は無視して取る
      var ok5 = post({ action: 'mark', lane: '5', tag: 'd' });
      __out = { held: r2.held, lockAfter: lockAfter, busy3: busy3, ok4: ok4.ok, ok5: ok5.ok, locks: lockLog.join(',') };
    """)
    assert out["held"] and out["lockAfter"]
    assert out["busy3"]["busy"] is True and "lane" in out["busy3"]["error"]
    assert out["ok4"] is True and out["ok5"] is True
    assert "try,rel,try,rel" in out["locks"]                          # 作業の間は全体の錠を持たない（取って返すを繰り返す）


@pytest.mark.skipif(not _node_ok(), reason="node が無い")
def test_without_a_lane_or_on_an_engine_without_trial_config_the_old_script_lock_is_used():
    out = _run("""
      function post(o) { return JSON.parse(doPost({ postData: { contents: JSON.stringify(o) } }).s); }
      EXTRA_ACTIONS['mark'] = function (req) { return { ok: true, lane: LANE }; };
      var a = post({ action: 'mark' });                                // lane なし（本番と同じ）
      var b = post({ action: 'mark', lane: '2' });                     // trial_config の無いエンジンは lane を読まない
      __out = { a: a, b: b, locks: lockLog.join(','), keys: Object.keys(store) };
    """)
    assert out["a"]["lane"] == "" and out["b"]["lane"] == ""
    assert out["locks"] == "try,rel,try,rel" and out["keys"] == []


def test_manager_adds_the_lane_to_the_request_only_when_set(tmp_path):
    sent = []

    class C:
        def call_webapp(self, url, body=None, **kw):
            sent.append(body)
            return {"data": {"ok": True, "version": m.engine_version()}}

    m = TR.TrialEngine(client=C(), state_path=tmp_path / "s.json")
    m._ensure_engine = lambda: {"engine_url": "https://script.google.com/x"}
    m._post({"action": "ping"})
    m.lane = "3"
    m._post({"action": "ping"})
    assert "lane" not in sent[0] and sent[1]["lane"] == "3"


# ------------------------------------------------------------------ props の並べ回しと「変わった所だけ」
class FakeEng:
    def __init__(self, lane="", delay=0.0, log=None):
        self.lane, self.delay, self.log = lane, delay, log

    def seed(self, fid, table):
        self.log.append(("seed", self.lane, fid))
        return {"ok": True}

    def trial_post(self, action, **kw):
        time.sleep(self.delay)
        self.log.append((action, self.lane, kw.get("id")))
        return {"ok": True, "snaps": {}, "steps": []}


def _patch_evaluate(monkeypatch):
    monkeypatch.setattr(P, "evaluate", lambda resp, shelf, danger, may, tinfo: {"p": {"P1": "pass"}, "p5class": "同じ", "reasons": {}, "p6": [], "wide": False})


def test_parallel_run_spreads_combos_over_workers_and_writes_every_record_once(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    log = []
    workers = [(FakeEng(str(i), 0.05, log), f"file{i}") for i in range(1, 5)]
    shelves = ["tidy", "seiri", "sort", "format", "width", "freeze", "unfreeze", "write"]
    stats, rf = P.run(workers[0][0], "file1", shelves=shelves, tables=["meibo_base", "uriage_base"], workers=workers, out=lambda *_: None, stagger=0)
    rows = [json.loads(x) for x in rf.read_text(encoding="utf-8").splitlines()]
    assert stats["n"] == 16 and len({(r["shelf"], r["table"]) for r in rows}) == 16          # 全部 1 回ずつ
    assert {r["lane"] for r in rows} == {"1", "2", "3", "4"} and all(r["fp"]["shelf"] for r in rows)
    seqs = [e for e in log if e[0] == "seq"]
    assert {e[2] for e in seqs} == {"file1", "file2", "file3", "file4"}                        # lane ごとの試験場に撃つ
    assert stats["workers"] == 4 and stats["post_fail"] == 0


def test_parallel_run_is_faster_than_one_worker_by_about_the_worker_count(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    shelves = ["tidy", "seiri", "sort", "format", "width", "freeze", "unfreeze", "write"]

    def go(n):
        log = []
        ws = [(FakeEng(str(i), 0.1, log), f"f{i}") for i in range(n)]
        t0 = time.time()
        P.run(ws[0][0], "f0", shelves=shelves, tables=["meibo_base"], workers=ws, run_file=tmp_path / f"r{n}.jsonl", out=lambda *_: None, stagger=0)
        return time.time() - t0

    t1, t4 = go(1), go(4)
    assert t4 < t1 * 0.6


def test_a_failed_post_is_recorded_and_the_worker_reseeds(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    log = []

    class Flaky(FakeEng):
        n = 0

        def trial_post(self, action, **kw):
            Flaky.n += 1
            if Flaky.n == 2:
                raise RuntimeError("Service invoked too many times")
            return super().trial_post(action, **kw)

    monkeypatch.setattr(P, "QUOTA_RETRIES", 0)
    e = Flaky("2", 0, log)
    stats, rf = P.run(e, "f", shelves=["tidy", "seiri", "sort"], tables=["meibo_base"], out=lambda *_: None)
    rows = [json.loads(x) for x in rf.read_text(encoding="utf-8").splitlines()]
    assert stats["post_fail"] == 1 and stats["quota"] == 1 and [r.get("post_fail") for r in rows] == [None, True, None]
    assert [x[0] for x in log].count("seed") == 2                                              # 失敗の後は流し込み直す


def test_changed_combos_picks_only_what_the_shelf_table_template_or_a_missing_record_touches():
    fp = P.inputs_fp()
    combos = [("meibo_base", "tidy"), ("meibo_base", "sort"), ("uriage_base", "tidy")]
    combos = [(t, s) for t, s in combos]
    prev = {}
    for t, s in combos:
        prev[(s, t)] = {"shelf": s, "table": t, "p": {"P1": "pass"}, "fp": P.combo_fp(fp, s, t)}
    assert P.changed_combos(combos, fp, prev) == ([], {})                                     # 何も変わっていなければ 0 組
    fp2 = json.loads(json.dumps(fp))
    fp2["shelf"]["sort"] = "changed"                                                          # 棚の中身が変わった
    got, why = P.changed_combos(combos, fp2, prev)
    assert got == [("meibo_base", "sort")] and why == {"棚": 1}
    fp3 = json.loads(json.dumps(fp))
    fp3["table"]["uriage_base"] = "changed"                                                   # 表が変わった
    assert P.changed_combos(combos, fp3, prev)[0] == [("uriage_base", "tidy")]
    fp4 = json.loads(json.dumps(fp))
    fp4["tpl"]["tidy"] = "changed"                                                            # ひな形が変わった（tidy は 2 つの表）
    assert sorted(P.changed_combos(combos, fp4, prev)[0]) == [("meibo_base", "tidy"), ("uriage_base", "tidy")]
    fp5 = json.loads(json.dumps(fp))
    fp5["common"] = "changed"                                                                 # 共通部だけ変わっても、節目（--with-engine）でなければ回さない
    assert P.changed_combos(combos, fp5, prev)[0] == [] and len(P.changed_combos(combos, fp5, prev, with_engine=True)[0]) == 3
    del prev[("sort", "meibo_base")]                                                          # 前回が無い組は回す
    assert P.changed_combos(combos, fp, prev)[0] == [("meibo_base", "sort")]
    prev[("tidy", "meibo_base")]["post_fail"] = True                                          # 前回 POST が失敗した組も回す
    assert ("meibo_base", "tidy") in P.changed_combos(combos, fp, prev)[0]
    prev[("tidy", "uriage_base")].pop("fp")                                                   # 指紋のない昔の記録は回す（stamp で足せる）
    assert ("uriage_base", "tidy") in P.changed_combos(combos, fp, prev)[0]


def test_run_with_changed_runs_nothing_when_nothing_changed_and_stamp_fills_legacy_records(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    log = []
    e = FakeEng("", 0, log)
    stats, rf = P.run(e, "f", shelves=["tidy", "sort"], tables=["meibo_base"], run_file=tmp_path / "props_20260101_000001.jsonl", out=lambda *_: None)
    assert stats["n"] == 2
    msgs = []
    stats2, _ = P.run(e, "f", shelves=["tidy", "sort"], tables=["meibo_base"], changed=True, runs_dir=tmp_path, run_file=tmp_path / "props_20260101_000002.jsonl", out=msgs.append)
    assert stats2["n"] == 0 and "変わった組はありません" in msgs[0]
    legacy = tmp_path / "props_20250101_000000.jsonl"                                       # 指紋のない昔の記録（別の組）
    legacy.write_text(json.dumps({"shelf": "width", "table": "meibo_base", "p": {"P1": "pass"}}) + "\n", encoding="utf-8")
    assert P.stamp(legacy, P.inputs_fp()) == 1 and json.loads(legacy.read_text(encoding="utf-8"))["fp"]["shelf"]
    stats3, _ = P.run(e, "f", shelves=["width"], tables=["meibo_base"], changed=True, runs_dir=tmp_path, run_file=tmp_path / "props_20260101_000003.jsonl", out=lambda *_: None)
    assert stats3["n"] == 0                                                                  # 足した指紋が今と同じなので回さない


def test_lane_workers_use_one_sandbox_per_lane_up_to_the_limit():
    st = {"files": {"WS試験_場": "f1", "WS試験_場2": "f2", "WS試験_控え2": "b2", "WS試験_場3": "f3"}}   # 場 3 は控えが無い＝まだ使えない
    ws = TR.lane_workers(lambda: TR.TrialEngine(client=object(), state_path="x.json"), st, jobs=5)
    assert [(e.lane, f) for e, f in ws] == [("1", "f1"), ("2", "f2")]
    assert len(TR.lane_workers(lambda: TR.TrialEngine(client=object(), state_path="x.json"), st, jobs=1)) == 1


def test_a_429_is_waited_out_and_retried_without_dropping_workers(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    monkeypatch.setattr(P, "QUOTA_WAIT", 0)
    log = []

    class Hot(FakeEng):
        n = 0

        def trial_post(self, action, **kw):
            Hot.n += 1
            if Hot.n in (1, 2):
                raise RuntimeError("Service invoked too many times: 429 rate limit")
            return super().trial_post(action, **kw)

    stats, rf = P.run(Hot("2", 0, log), "f", shelves=["tidy"], tables=["meibo_base"], out=lambda *_: None)
    r = json.loads(rf.read_text(encoding="utf-8").splitlines()[0])
    assert stats["quota_retry"] == 2 and stats["post_fail"] == 0 and r["p"]["P1"] == "pass" and r["retries"] == 2
    Hot.n = -100                                                           # 上限まで撃ち直しても駄目なら、失敗として残す
    monkeypatch.setattr(P, "QUOTA_RETRIES", 1)

    class Dead(FakeEng):
        def trial_post(self, action, **kw):
            raise RuntimeError("429 rate limit")

    stats, rf = P.run(Dead("2", 0, log), "f", shelves=["tidy"], tables=["uriage_base"], out=lambda *_: None)
    assert stats["post_fail"] == 1 and stats["quota"] == 1 and stats["quota_retry"] == 1


def test_default_jobs_is_five_and_lanes_can_go_up_to_ten():
    assert TR.DEFAULT_JOBS == 5 and TR.MAX_JOBS == 10 and len(TR.LANE_NUMS) == 9 and TR.LANE_SHEETS["10"] == "WS試験_場10"


def test_a_busy_lock_is_retried_and_a_429_cools_everyone(tmp_path, monkeypatch):
    _patch_evaluate(monkeypatch)
    monkeypatch.setattr(P, "RUNS", tmp_path)
    monkeypatch.setattr(P, "QUOTA_WAIT", 0)
    log = []

    class Busy(FakeEng):
        n = 0

        def trial_post(self, action, **kw):
            Busy.n += 1
            if Busy.n == 1:
                raise RuntimeError("別の処理が走っています。少し待って撃ち直してください。")
            return super().trial_post(action, **kw)

    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    stats, rf = P.run(Busy("1", 0, log), "f", shelves=["tidy"], tables=["meibo_base"], out=lambda *_: None)
    assert stats["busy_retry"] == 1 and stats["post_fail"] == 0 and stats["quota_retry"] == 0
