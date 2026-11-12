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
    }
    return m


def resolve(node, marks):
    if isinstance(node, str):
        m = re.fullmatch(r"\{(R1|R3)\}", node)
        if m:
            return marks[m.group(1)]
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


# ------------------------------------------------------------------ 回す
def run(eng, file_id, shelves=None, tables=None, run_file=None, resume=False, out=print, limit_seconds=None):
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
    t_start = time.time()
    stats = {"n": 0, "quota": 0, "post_fail": 0}
    for tname in tables:
        table = T.load_table(tname)
        tinfo = T.table_info(table)
        seeded = False
        for shelf in shelves:
            if (shelf, tname) in done:
                continue
            if (shelf, tname) in skips or (shelf, "*") in skips:
                continue
            if limit_seconds and time.time() - t_start > limit_seconds:
                out("[上限] 全体の時間の上限で止めました（--resume で続きから）")
                return stats, rf
            if not seeded:
                r = eng.seed(file_id, table)
                if not r.get("ok"):
                    out(f"[流し込み失敗] {tname}: {str(r.get('error'))[:120]}")
                    break
                seeded = True
            ops, may = build_ops(shelf, table, templates)
            danger = bool(cat.by_name[shelf]["danger"])
            t0 = time.time()
            rec = {"shelf": shelf, "table": tname, "ops": ops}
            try:
                resp = eng.trial_post("seq", id=file_id, steps=build_steps(ops, danger))
                if not resp.get("ok", True) or "snaps" not in resp:
                    raise RuntimeError(str(resp.get("error") or resp)[:200])
                ev = evaluate(resp, shelf, danger, may, tinfo)
                rec.update(ev)
                if ev["p"]["P1"] == "fail":
                    seeded = False           # 戻らなかったら、次の組の前に流し込み直す
            except Exception as e:           # POST の失敗（時間切れ・Google の上限 等）
                msg = str(e)
                rec.update(p={"P1": "error"}, reasons={"POST": msg[:200]}, post_fail=True, quota=any(w.lower() in msg.lower() for w in QUOTA_WORDS))
                stats["post_fail"] += 1
                stats["quota"] += 1 if rec["quota"] else 0
                seeded = False
            rec["sec"] = round(time.time() - t0, 1)
            with rf.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats["n"] += 1
            bad = [k for k, v in rec["p"].items() if v in ("fail", "error")]
            out(f"{'×' if bad else '○'} {shelf} × {tname} ({rec['sec']}s) " + (" ".join(bad) + " " + "；".join(f"{k}:{v}" for k, v in list(rec.get("reasons", {}).items())[:2])[:160] if bad else rec.get("p5class", "")))
    return stats, rf


def summarize(rf):
    rows = [json.loads(x) for x in Path(rf).read_text(encoding="utf-8").splitlines() if x.strip()]
    fails = [r for r in rows if any(v in ("fail", "error") for v in r["p"].values())]
    p6 = {}
    for r in rows:
        for it in r.get("p6", []):
            p6.setdefault((r["shelf"], it), []).append(r["table"])
    return rows, fails, p6
