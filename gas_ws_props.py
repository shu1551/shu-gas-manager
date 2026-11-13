# -*- coding: utf-8 -*-
"""
gas_ws_props.py - L1 性質の総当たり（試験設計書 第 4.1 節・段 T1）。AI なし。棚 × 表の組ごとに、試験用のエンジンの seq を 1 回撃って次を確かめる。
  P1 戻すと元どおり（撃つ → 2 回目も撃つ → 全部戻す。約束の指紋が最初と同じ）  P2 承認なしでは変わらない（危ない棚を ok なしで撃つ → 止まる・指紋が同じ）
  P3 失敗しても元どおり（ひな形の後ろに「無いシートを指す手」を足して撃つ → 失敗が返り指紋が同じ）  P4 壊さない（いつも掛かる決まり 1・4・5）
  P5 二度撃ち（2 回目の結果を 同じ／変更なしと言う／断る／増える に分ける。合否は壊れないだけ）  P6 脇の状態（戻した後に戻らなかった物。表だけ）
  P7 広い削除は 1 回止まる（ok=True でも止まり、同じ ops をもう一度撃つと通る）は seq の retry_wide で通し、止まったかを記録する
ひな形は ws_trial/templates.json（印は表の形の JSON から埋まる）。回した結果は ws_trial/runs/props_*.jsonl（git に入れない）。
"""

import json
import re
import sys
import time
from pathlib import Path

import gas_ws_judge as J
import gas_ws_tables as T

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "ws_trial" / "templates.json"
RUNS = HERE / "ws_trial" / "runs"
SKIP_FILE = HERE / "ws_trial" / "props_skip.tsv"
TABLES = ["meibo_base", "meibo_dirty", "meibo_quirk", "uriage_base", "uriage_dirty", "uriage_quirk"]
BAD_OP = {"shelf": "write", "sheet": "存在しないシート", "cells": {"A1": 1}}
QUOTA_RETRIES = 6     # 回数超え（429）が返ったら、待って撃ち直す回数
QUOTA_WAIT = 10       # 待つ秒（1 回目 10・2 回目 20…）。待つ間は全員が止まる（1 本が 429 を受けたら、みんなで冷ます）。撮影の読みの枠切れは GAS の中で待って読み直すので、ここに来るのはまれ
BUSY_WORDS = ("別の処理が走っています",)
QUOTA_WORDS = ("quota", "rate limit", "429", "too many", "Service invoked too many", "上限", "Exceeded")


def load_templates():
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


def load_skips(path=SKIP_FILE):
    """棚<TAB>表<TAB>理由。表は * で全部。番頭が理由つきで外した組"""
    out = {}
    p = Path(path)
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 3 and not ln.startswith("#"):
                out[(parts[0], parts[1])] = parts[2]
    return out


# ------------------------------------------------------------------ 印の解決（表の形の JSON から）
def table_marks(t):
    sh = t["sheets"][0]
    tb = sh["tables"][0]
    grid = T.expand_sheet(sh)
    a, b = (int(x) for x in tb["data"].split("-"))
    hr = tb["header_rows"][-1]
    fc, lc = T.col_num(tb["first_col"]), T.col_num(tb["last_col"])
    num_col = text_col = None
    for c in range(fc, lc + 1):
        vals = [grid[r - 1][c - 1] for r in range(a, b + 1) if r - 1 < len(grid) and c - 1 < len(grid[r - 1])]
        vals = [v for v in vals if v not in (None, "")]
        if not vals:
            continue
        isnum = all(isinstance(v, (int, float)) and not isinstance(v, bool) or (isinstance(v, str) and v.startswith("=")) for v in vals)
        istext = all((isinstance(v, str) and not v.startswith("=")) or (isinstance(v, dict) and "text" in v) for v in vals)
        if isnum and num_col is None:
            num_col = c
        if istext and text_col is None and c != T.col_num(tb["key"]):
            text_col = c
    num_col = num_col or fc
    text_col = text_col or fc
    letter = T.col_letter
    ec = lc + 1
    first = grid[a - 1][text_col - 1] if a - 1 < len(grid) else ""
    first = first.get("text") if isinstance(first, dict) else first
    last = tb.get("total_row") or b
    m = {
        "S": sh["name"], "表": f"{letter(fc)}{tb['header_rows'][0]}:{letter(lc)}{last}", "明細": f"{letter(fc)}{a}:{letter(lc)}{b}",
        "見出し行": f"{letter(fc)}{hr}:{letter(lc)}{hr}", "FC": letter(fc), "SC": letter(fc + 1), "NC": letter(num_col), "TC": letter(text_col), "KC": tb["key"],
        "EC": letter(ec), "NC明細": f"{letter(num_col)}{a}:{letter(num_col)}{b}", "TC明細": f"{letter(text_col)}{a}:{letter(text_col)}{b}",
        "FC明細": f"{letter(fc)}{a}:{letter(fc)}{b}", "EC明細": f"{letter(ec)}{a}:{letter(ec)}{b}", "R1": a, "R3": a + 2, "TCの値": str(first or ""),
        "EA": f"{letter(ec)}{a}", "先頭行": f"{letter(fc)}{a}:{letter(lc)}{a}", "空き行": f"A{last + 4}",
        "明細の行": list(range(a, b + 1)), "広い範囲": f"{letter(fc)}{hr}:{letter(lc + 1)}{last + 1}", "EC明細の下まで": f"{letter(ec)}{a}:{letter(ec)}{b + 1}",
    }
    return m


def resolve(node, marks):
    if isinstance(node, str):
        m = re.fullmatch(r"\{([^{}]+)\}", node)
        if m and m.group(1) in marks and not isinstance(marks[m.group(1)], str):
            return marks[m.group(1)]               # 数・行の並びは型のまま入れる（文字の印は下で文字として埋める）
        return re.sub(r"\{([^{}]+)\}", lambda x: str(marks[x.group(1)]) if x.group(1) in marks else x.group(0), node)
    if isinstance(node, list):
        return [resolve(x, marks) for x in node]
    if isinstance(node, dict):
        return {resolve(k, marks): resolve(v, marks) for k, v in node.items()}
    return node


def build_ops(shelf, table, templates=None):
    tpl = (templates or load_templates())[shelf]
    marks = table_marks(table)
    return [resolve(tpl["templates"][0], marks)][0], tpl.get("may_change", [])


def build_ops_wide(shelf, table, templates=None):
    """広い削除のひな形（templates.json の "wide"）。無ければ None"""
    tpl = (templates or load_templates())[shelf]
    if not tpl.get("wide"):
        return None
    return resolve(tpl["wide"][0], table_marks(table))


def build_steps_wide(ops):
    """P7 を確かめる 1 本: いきなり ok=True で撃つ → 止まる（retry_wide が同じ ops をもう一度撃つ）→ 戻す"""
    return [{"snap": "A"}, {"do": ops, "ok": True, "name": "w1", "retry_wide": True}, {"snap": "B"}, {"undo_all": True, "name": "undow"}, {"snap": "C"}]


def evaluate_wide(resp):
    """広いひな形の seq の返事 → (pass/fail/na, 理由)。止まらずに通ったら fail、引数違いで断られた（この表に当てはまらない）なら na"""
    sn, st = resp["snaps"], resp["steps"]
    s = _step(st, "w1")
    k = kind_of(s["res"])
    if not s["wide"]:
        if k in ("arg", "noop"):
            return "na", f"この表では広い削除に当たらなかった（{k}）"
        if k == "ok":
            return "fail", "広い削除のひな形が、止まらずに ok=True で通った"
        return "fail", f"止まらずに {k}: " + str(s["res"].get("error_brief"))[:100]
    v, why = p7_verdict(st, sn, sn["A"])
    undos = [u for x in st if "undo" in x for u in x["undo"]]
    if v == "pass" and (not _same(sn["A"], sn["C"]) or any(not u["ok"] for u in undos)):
        return "fail", "広い削除を通した後、戻しても指紋が最初と違う"
    return v, why


def build_steps(ops, danger):
    s = [{"snap": "A"},
         {"do": ops, "ok": True, "name": "do1", "retry_wide": True}, {"snap": "B1"},
         {"do": ops, "ok": True, "name": "do2", "retry_wide": True}, {"snap": "B2"},
         {"undo_all": True, "name": "undo1"}, {"snap": "C"}]
    if danger:
        s += [{"do": ops, "ok": False, "name": "p2"}, {"snap": "P2"}, {"undo_all": True, "name": "undo2"}, {"snap": "P2C"}]
    s += [{"do": ops + [BAD_OP], "ok": True, "name": "p3", "retry_wide": True}, {"snap": "P3"}, {"undo_all": True, "name": "undo3"}, {"snap": "D"}]
    return s


# ------------------------------------------------------------------ 判定
def _step(steps, name):
    for s in steps:
        if s.get("name") == name:
            return s
    return None


def _same(x, y):
    return J.promise_fingerprints(x) == J.promise_fingerprints(y)


WIDE_COUNT = re.compile(r"消える数: ?\d+")


def p7_verdict(st, sn, A):
    """(pass/fail/na, 理由)。止まらなかった組（広い削除に当たらない）は na。止まった組は 3 つを確かめる:
    止めの返事に何が何件消えるかがある・止まった後の指紋が最初と同じ・止まった後の同じ ops の撃ち直しが通る（また止まらない）"""
    why = []
    hit = False
    for name in ("do1", "do2", "w1"):
        s = _step(st, name)
        if not s or not s.get("wide"):
            continue
        hit = True
        first = s.get("first") or {}
        msg = first.get("error_brief") or first.get("error") or ""
        if not first.get("blocked"):
            why.append(f"{name}: 最初の撃ちが止まっていない")
        if not WIDE_COUNT.search(msg):
            why.append(f"{name}: 返事に何が何件消えるかが無い（{msg[:60]}）")
        if name != "do2":
            snap = sn.get(name + "_first")
            if snap is None or not _same(A, snap):
                why.append(f"{name}: 止まったのに指紋が変わった")
        if kind_of(s["res"]) == "blocked":
            why.append(f"{name}: 同じ ops をもう一度撃っても通らない")
    if not hit:
        return "na", ""
    return ("fail", "；".join(why)[:300]) if why else ("pass", "")


def kind_of(res):
    if res["ok"]:
        return "ok" if res["changed"] else "noop"
    return "blocked" if res["blocked"] else ("arg" if res["arg"] else "error")




def side_items():
    sys.path.insert(0, str(HERE / "ws_trial"))
    import side_probe
    return [(k, label) for k, label in side_probe.ITEMS if k != "frozen"], side_probe.readout


def evaluate(resp, shelf, danger, may_change, tinfo):
    """seq の返事 → 判定の dict（p1〜p5 は pass/fail/na と理由、p5class、p6 は戻らなかった脇の項目）"""
    sn, st = resp["snaps"], resp["steps"]
    A = sn["A"]
    out = {"shelf": shelf, "p": {}, "reasons": {}}
    d1, d2 = _step(st, "do1"), _step(st, "do2")
    k1, k2 = kind_of(d1["res"]), kind_of(d2["res"])
    out.update(kind1=k1, kind2=k2, wide=bool(d1["wide"] or d2["wide"]))
    # P7 広い削除は 1 回止まる: 最初に止まった撃ち（do1・do2 の first）が「止め・指紋が同じ・何が何件か」で、止まった後の撃ち直しが通る
    out["p"]["P7"], r7 = p7_verdict(st, sn, A)
    if r7:
        out["reasons"]["P7"] = r7
    undos = [u for s in st if "undo" in s for u in s["undo"]]
    bad = [u for u in undos if not u["ok"]]
    # P1
    c_same = _same(A, sn["C"]) and _same(A, sn["D"])
    out["p"]["P1"] = "pass" if (c_same and not bad) else "fail"
    if not c_same:
        out["reasons"]["P1"] = "undo の後の約束の指紋が最初と違う（C: " + ("同じ" if _same(A, sn["C"]) else "違う") + "）"
    if bad:
        out["reasons"]["P1"] = "undo の失敗: " + str(bad[0]["error"])[:100]
    # P2
    if danger:
        p2 = _step(st, "p2")["res"]
        k = kind_of(p2)
        if k == "blocked":
            ok = _same(A, sn["P2"]) and re.search(r"消|上書き|承認|ok=True", p2["error_brief"] or "")
            out["p"]["P2"] = "pass" if ok else "fail"
            if not ok:
                out["reasons"]["P2"] = "止まったが指紋が変わった・何が消えるかが返事に無い"
        else:
            out["p"]["P2"] = "na"
            out["reasons"]["P2"] = f"この表では止める物が無かった（{k}）"
    else:
        out["p"]["P2"] = "na"
    # P3
    p3 = _step(st, "p3")["res"]
    k = kind_of(p3)
    p3ok = k != "ok" and k != "noop" and _same(A, sn["P3"])
    out["p"]["P3"] = "pass" if p3ok else "fail"
    if not p3ok:
        out["reasons"]["P3"] = f"失敗するはずの ops が {k}／指紋 " + ("同じ" if _same(A, sn["P3"]) else "違う")
    # P4（do1 の後に壊していないか）
    touched = [A["sheets"][0]["name"]] + [s["name"] for s in sn["B1"]["sheets"] if J.sheet_of(A, s["name"]) is None]
    if k1 == "ok":
        v = J.check_rules(A, sn["B1"], touched=touched, may_change=tuple(may_change), tinfo=tinfo)
        out["p"]["P4"] = "pass" if not v else "fail"
        if v:
            out["reasons"]["P4"] = "；".join(v)[:200]
    else:
        out["p"]["P4"] = "pass" if _same(A, sn["B1"]) else "fail"
        if k1 in ("blocked", "arg", "noop", "error") and not _same(A, sn["B1"]):
            out["reasons"]["P4"] = f"{k1} なのに指紋が変わった"
        if k1 == "error":
            out["p"]["P4"] = "fail"
            out["reasons"]["P4"] = "内部のエラー: " + str(d1["res"]["error_brief"])[:120]
    # P5
    if k2 == "ok" or k2 == "noop":
        cls = "変更なしと言う" if k2 == "noop" else ("同じ" if _same(sn["B1"], sn["B2"]) else "増える")
    else:
        cls = "断る" if k2 in ("blocked", "arg") else "内部エラー"
    out["p5class"] = cls
    v5 = J.check_rules(A, sn["B2"], touched=touched, may_change=tuple(may_change), tinfo=tinfo) if k2 == "ok" else []
    out["p"]["P5"] = "pass" if (cls != "内部エラー" and not v5) else "fail"
    if out["p"]["P5"] == "fail":
        out["reasons"]["P5"] = ("内部のエラー: " + str(d2["res"]["error_brief"])[:120]) if cls == "内部エラー" else "；".join(v5)[:200]
    # P6（脇の状態が戻らなかった物。表だけ）
    items, readout = side_items()
    miss = []
    if k1 == "ok":
        for key, label in items:
            try:
                if readout(A, key) != readout(sn["C"], key):
                    miss.append(label)
            except Exception:
                pass
    out["p6"] = miss
    return out


# ------------------------------------------------------------------ 入力の指紋（変わった所だけ回すため）
def _h(*parts):
    import hashlib
    h = hashlib.sha1()
    for x in parts:
        h.update((x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, sort_keys=True, default=list)).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:10]


def inputs_fp(root=None, tables=None):
    """組ごとの入力の指紋。棚（札と関数の中身）・表（JSON）・ひな形（と may_change）・共通部（参考）。root はリポジトリの場所（昔の版の木でも出せる）"""
    import gas_ws_catalog as C
    root = Path(root) if root else HERE
    cat = C.load(root / "ws_shelves")
    tpl = json.loads((root / "ws_trial" / "templates.json").read_text(encoding="utf-8"))
    tdir = root / "ws_trial" / "tables"
    names = tables or sorted(p.stem for p in tdir.glob("*.json"))
    tfp = {n: _h((tdir / f"{n}.json").read_text(encoding="utf-8")) for n in names}
    common = _h((root / "workspace_engine.gs").read_text(encoding="utf-8"), (root / "ws_trial" / "Trial.gs").read_text(encoding="utf-8"))
    shelf = {s["name"]: _h(s) for s in cat.shelves}
    return {"shelf": shelf, "tpl": {k: _h(v) for k, v in tpl.items()}, "table": tfp, "common": common}


def combo_fp(fp, shelf, tname):
    return {"shelf": fp["shelf"].get(shelf, ""), "tpl": fp["tpl"].get(shelf, ""), "table": fp["table"].get(tname, ""), "common": fp["common"]}


def previous_records(runs_dir=None):
    """これまでの総当たりの記録のうち、組ごとの最新（ファイル名の古い順に読み、後のものが勝つ）"""
    d = Path(runs_dir) if runs_dir else RUNS
    prev = {}
    for f in sorted(d.glob("props_*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                prev[(r["shelf"], r["table"])] = r
            except Exception:
                pass
    return prev


def changed_combos(combos, fp, prev, with_engine=False, refail=False):
    """前回の記録と比べて回す組。前回が無い・POST 失敗・指紋が無い・棚/表/ひな形が変わった組（with_engine なら共通部が変わった組も）。返り値は (回す組のリスト, 理由の件数)"""
    out, why = [], {"新規": 0, "前回失敗": 0, "指紋なし": 0, "棚": 0, "表": 0, "ひな形": 0, "共通部": 0}
    for t, s in combos:
        r = prev.get((s, t))
        cur = combo_fp(fp, s, t)
        if r is None:
            why["新規"] += 1
        elif r.get("post_fail") or r.get("p", {}).get("P1") == "error":
            why["前回失敗"] += 1
        elif refail and any(v in ("fail", "error") for v in r.get("p", {}).values()):
            why["前回通らず"] = why.get("前回通らず", 0) + 1
        elif not r.get("fp"):
            why["指紋なし"] += 1
        else:
            o = r["fp"]
            bad = [k for k, lab in (("shelf", "棚"), ("table", "表"), ("tpl", "ひな形")) if o.get(k) != cur[k]]
            if with_engine and o.get("common") != cur["common"]:
                bad.append("common")
            if not bad:
                continue
            for k in bad:
                why[{"shelf": "棚", "table": "表", "tpl": "ひな形", "common": "共通部"}[k]] += 1
        out.append((t, s))
    return out, {k: v for k, v in why.items() if v}


def stamp(rf, fp):
    """指紋のない昔の記録に、与えた木の指紋を書き足す（その木で回した記録に使う）。書いた件数を返す"""
    rows, n = [], 0
    for ln in Path(rf).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if not r.get("fp"):
            r["fp"] = combo_fp(fp, r["shelf"], r["table"])
            n += 1
        rows.append(json.dumps(r, ensure_ascii=False))
    Path(rf).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return n


# ------------------------------------------------------------------ 回す
def run(eng, file_id, shelves=None, tables=None, run_file=None, resume=False, out=print, limit_seconds=None, workers=None, changed=False, with_engine=False, runs_dir=None, fp=None, stagger=1.5, refail=False):
    """workers は [(エンジン, 試験場の ID)] の並び（並べて回す。lane ごとに錠・控え・台帳が分かれる）。無ければ eng・file_id の 1 本。
    changed なら、前回の記録と比べて変わった組だけ回す"""
    import queue
    import threading
    import gas_workspace as gw
    templates = load_templates()
    skips = load_skips()
    cat = gw.CATALOG
    all_shelves = [s["name"] for s in cat.shelves if s["kind"] == "sheet" and s["name"] in templates]
    shelves = shelves or all_shelves
    tables = tables or TABLES
    RUNS.mkdir(parents=True, exist_ok=True)
    rf = Path(run_file) if run_file else RUNS / f"props_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    done = set()
    if rf.exists() and resume:
        for ln in rf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add((d["shelf"], d["table"]))
            except Exception:
                pass
    combos = [(t, s) for t in tables for s in shelves if (s, t) not in done and (s, t) not in skips and (s, "*") not in skips]
    fp = fp or inputs_fp(tables=sorted(set(tables) | set(TABLES)))
    if changed:
        prev = previous_records(runs_dir)
        n0 = len(combos)
        combos, why = changed_combos(combos, fp, prev, with_engine=with_engine, refail=refail)
        out(f"[変わった所だけ] {n0} 組のうち {len(combos)} 組を回す（理由: " + "・".join(f"{k} {v}" for k, v in why.items()) + "）" if combos else f"[変わった所だけ] 変わった組はありません（{n0} 組を確かめた）")
        if not with_engine and prev and any(r.get("fp") and r["fp"].get("common") != fp["common"] for r in prev.values()):
            out("[注意] 共通部（workspace_engine.gs・Trial.gs）が前回から変わっています。全部回すなら --with-engine（節目）")
    workers = workers or [(eng, file_id)]
    q = queue.Queue()
    for c in combos:
        q.put(c)
    lock = threading.Lock()
    t_start = time.time()
    stats = {"n": 0, "quota": 0, "post_fail": 0, "quota_retry": 0, "busy_retry": 0, "workers": len(workers)}
    stop = threading.Event()
    cool = {"until": 0.0}        # 429 を受けたら全員がここまで待つ

    def work(wi, weng, wfile):
        time.sleep(stagger * wi)                       # 同時に撃ち始めない
        seeded = None
        while not stop.is_set():
            try:
                tname, shelf = q.get_nowait()
            except queue.Empty:
                return
            if limit_seconds and time.time() - t_start > limit_seconds:
                with lock:
                    out("[上限] 全体の時間の上限で止めました（--resume で続きから）")
                stop.set()
                return
            table = T.load_table(tname)
            tinfo = T.table_info(table)
            ops, may = build_ops(shelf, table, templates)
            danger = bool(cat.by_name[shelf]["danger"])
            t0 = time.time()
            rec = {"shelf": shelf, "table": tname, "ops": ops, "fp": combo_fp(fp, shelf, tname), "lane": getattr(weng, "lane", "")}
            for attempt in range(QUOTA_RETRIES + 1):
                try:
                    wait = cool["until"] - time.time()
                    if wait > 0:
                        time.sleep(wait)
                    if seeded != tname:
                        ts = time.time()
                        r = weng.seed(wfile, table)
                        if not r.get("ok"):
                            raise RuntimeError("流し込み失敗: " + str(r.get("error"))[:150])
                        seeded = tname
                        rec["seed_sec"] = round(time.time() - ts, 1)
                    ts = time.time()
                    resp = weng.trial_post("seq", id=wfile, steps=build_steps(ops, danger))
                    if not resp.get("ok", True) or "snaps" not in resp:
                        raise RuntimeError(str(resp.get("error") or resp)[:200])
                    rec["seq_sec"] = round(time.time() - ts, 1)
                    if resp.get("io"):
                        rec["io"] = resp["io"]          # GAS の中の段ごとの ms・Sheets API の読みの回数・枠切れで待った ms
                    ev = evaluate(resp, shelf, danger, may, tinfo)
                    wops = build_ops_wide(shelf, table, templates)
                    if wops:
                        rec["wide_ops"] = wops
                        ts = time.time()
                        w = weng.trial_post("seq", id=wfile, steps=build_steps_wide(wops))
                        if not w.get("ok", True) or "snaps" not in w:
                            raise RuntimeError(str(w.get("error") or w)[:200])
                        rec["wide_sec"] = round(time.time() - ts, 1)
                        if w.get("io"):
                            rec["wide_io"] = w["io"]
                        wv, wwhy = evaluate_wide(w)
                        rec["wide_msg"] = ((_step(w["steps"], "w1") or {}).get("first") or {}).get("error_brief", "")
                        ev["p"]["P7"] = "fail" if "fail" in (wv, ev["p"]["P7"]) else ("pass" if "pass" in (wv, ev["p"]["P7"]) else "na")
                        if wwhy:
                            ev["reasons"]["P7"] = (ev["reasons"].get("P7", "") + "；" if ev["reasons"].get("P7") else "") + "広い範囲: " + wwhy
                        seeded = None if wv == "fail" else seeded
                    rec.update(ev)
                    rec.pop("post_fail", None)
                    if ev["p"]["P1"] == "fail":
                        seeded = None            # 戻らなかったら、次の組の前に流し込み直す
                    break
                except Exception as e:           # POST の失敗（時間切れ・Google の上限 等）
                    msg = str(e)
                    isq = any(w.lower() in msg.lower() for w in QUOTA_WORDS)
                    seeded = None
                    isb = any(w in msg for w in BUSY_WORDS)
                    if (isq or isb) and attempt < QUOTA_RETRIES:   # 回数超え（429）・錠の取り合いは待って撃ち直す（並べる数は減らさない）
                        with lock:
                            stats["quota_retry" if isq else "busy_retry"] += 1
                            if isq:
                                cool["until"] = max(cool["until"], time.time() + QUOTA_WAIT * (attempt + 1))
                        rec["retries"] = attempt + 1
                        if isb:
                            time.sleep(3)
                        continue
                    rec.update(p={"P1": "error"}, reasons={"POST": msg[:200]}, post_fail=True, quota=isq)
                    break
            rec["sec"] = round(time.time() - t0, 1)
            bad = [k for k, v in rec["p"].items() if v in ("fail", "error")]
            line = f"{'×' if bad else '○'} {shelf} × {tname} ({rec['sec']}s{'・場' + rec['lane'] if rec['lane'] else ''}) " + (" ".join(bad) + " " + "；".join(f"{k}:{v}" for k, v in list(rec.get("reasons", {}).items())[:2])[:160] if bad else rec.get("p5class", ""))
            with lock:
                with rf.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["n"] += 1
                if rec.get("post_fail"):
                    stats["post_fail"] += 1
                    stats["quota"] += 1 if rec.get("quota") else 0
                out(line)

    threads = [threading.Thread(target=work, args=(i, e, f), daemon=True) for i, (e, f) in enumerate(workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    stats["sec"] = round(time.time() - t_start, 1)
    return stats, rf


def summarize(rf):
    rows = [json.loads(x) for x in Path(rf).read_text(encoding="utf-8").splitlines() if x.strip()]
    fails = [r for r in rows if any(v in ("fail", "error") for v in r["p"].values())]
    p6 = {}
    for r in rows:
        for it in r.get("p6", []):
            p6.setdefault((r["shelf"], it), []).append(r["table"])
    return rows, fails, p6


def report_md(rows, title="性質の総当たり（P1〜P7）"):
    """共有メモ用の Markdown: 通らない物・二度撃ちの分け方・P6（脇の状態が戻らなかった物）・広い削除が 1 回止まった棚・秒"""
    L = [f"# {title}", ""]
    n = len(rows)
    fails = [r for r in rows if any(v in ("fail", "error") for v in r["p"].values())]
    quota = sum(1 for r in rows if r.get("quota"))
    posts = sum(1 for r in rows if r.get("post_fail"))
    secs = [r.get("sec", 0) for r in rows]
    L += [f"- 組 {n}（棚 × 表）・通らない {len(fails)}・POST の失敗 {posts}（うち Google の上限らしい物 {quota}）・1 組の秒 平均 {sum(secs) / n if n else 0:.0f}・合計 {sum(secs) / 3600:.1f} 時間", ""]
    counts = {}
    for r in rows:
        for k, v in r["p"].items():
            counts.setdefault(k, {}).setdefault(v, 0)
            counts[k][v] += 1
    L += ["| 性質 | pass | fail | error | na |", "|---|---|---|---|---|"]
    for k in ("P1", "P2", "P3", "P4", "P5"):
        c = counts.get(k, {})
        L.append(f"| {k} | {c.get('pass', 0)} | {c.get('fail', 0)} | {c.get('error', 0)} | {c.get('na', 0)} |")
    L += ["", "## 通らない組", ""]
    if fails:
        L += ["| 棚 | 表 | 通らない性質 | 理由 |", "|---|---|---|---|"]
        for r in fails:
            bad = [k for k, v in r["p"].items() if v in ("fail", "error")]
            L.append(f"| {r['shelf']} | {r['table']} | {'・'.join(bad)} | " + "；".join(f"{k}: {r.get('reasons', {}).get(k, '')}" for k in bad).replace("|", "/")[:200] + " |")
    else:
        L.append("なし")
    cls = {}
    for r in rows:
        if r.get("p5class"):
            cls.setdefault(r["shelf"], {}).setdefault(r["p5class"], 0)
            cls[r["shelf"]][r["p5class"]] += 1
    L += ["", "## P5 二度撃ちの分け方（棚ごと・表の数）", "", "| 棚 | 同じ | 変更なしと言う | 断る | 増える | 内部エラー |", "|---|---|---|---|---|---|"]
    for shelf in sorted(cls):
        c = cls[shelf]
        L.append(f"| {shelf} | " + " | ".join(str(c.get(x, 0)) for x in ("同じ", "変更なしと言う", "断る", "増える", "内部エラー")) + " |")
    p6 = {}
    for r in rows:
        for it in r.get("p6", []):
            p6.setdefault((r["shelf"], it), []).append(r["table"])
    L += ["", "## P6 戻した後に戻らなかった脇の状態（表だけ・合否には使わない）", ""]
    if p6:
        L += ["| 棚 | 戻らなかった物 | 表 |", "|---|---|---|"]
        for (shelf, it), tabs in sorted(p6.items()):
            L.append(f"| {shelf} | {it} | {'・'.join(tabs)} |")
    else:
        L.append("なし（今の棚は、触る物がすべて戻る）")
    wide = sorted({r["shelf"] for r in rows if r.get("wide")})
    L += ["", "## P7 広い削除が ok=True でも 1 回止まった棚（同じ ops をもう一度撃つと通った）", "", "、".join(wide) if wide else "なし"]
    return "\n".join(L) + "\n"
