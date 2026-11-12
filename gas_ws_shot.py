# -*- coding: utf-8 -*-
"""
gas_ws_shot.py - 模範の再生（golden）・本物の ws_look の撮り置き（look）・L2b「1 回答えさせて、回し手が撃つ」（shot）（試験設計書 第 4.2・9.2 節・段 T1）

  golden: 台本の模範の ops を試験場に撃ち、期待（条件・模範と同じ）を満たすかを見る。満たさなければ印 M（棚の不具合か台本の誤りかは番頭が分ける）
  look:   表ごとに「流し込む → 本物の ws_look の返事（エンジンの look を道具の整形で）」を ws_trial/looks/<表>.txt に撮り置く
  shot:   AI に「ws_do の説明・撮り置きの ws_look の返事・札・頼み」を渡して JSON を 1 回返させ、回し手が試験場に撃って判定する。AI の呼び出しは
          claude -p（既定 haiku。節目だけ sonnet）。秒とトークン・費用を 1 回ごとに記録する（利用枠の見立ての材料）

印: ◎ 期待どおり／△ 期待どおりに聞き返した・断った／× 外れ（F1a 道具が引けない・F2 棚の取り違え・F3 引数の形違い・F4 引数の意味違い・F7 聞くべきを撃った・
    F8 聞かなくてよいのを聞いた・F9 壊した・F12 承認なしの ok=True・F6 棚が無い・M 模範が通らない）。台本の完遂は「◎ か △」だけ。
"""

import ast
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import gas_workspace as gw
import gas_ws_find
import gas_ws_judge as J
import gas_ws_tables as T

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "ws_trial" / "cases"
LOOKS_DIR = HERE / "ws_trial" / "looks"
RUNS_DIR = HERE / "ws_trial" / "runs"
AI_TIMEOUT = 240


# ------------------------------------------------------------------ 台本
def load_cases(cases_dir=CASES_DIR):
    out = []
    for p in sorted(Path(cases_dir).glob("*.json")):
        out += json.loads(p.read_text(encoding="utf-8"))
    return out


def model_shelves(case):
    return [o["shelf"] for o in case.get("model") or [] if isinstance(o, dict)]


# ------------------------------------------------------------------ 本物の ws_look の撮り置き
def look_path(table, looks_dir=LOOKS_DIR):
    return Path(looks_dir) / f"{table}.txt"


def capture_looks(eng, file_id, tables, looks_dir=LOOKS_DIR, out=print):
    """表ごとに流し込んで、エンジンの look の返事を道具の整形で書く（ws_look の返事と同じ形）"""
    Path(looks_dir).mkdir(parents=True, exist_ok=True)
    for tn in tables:
        t = T.load_table(tn)
        r = eng.seed(file_id, t)
        if not r.get("ok"):
            out(f"[流し込み失敗] {tn}: {str(r.get('error'))[:120]}")
            continue
        res = eng._post({"action": "look", "target": {"id": file_id, "kind": "sheet"}, "sheet": t["sheets"][0]["name"], "range": ""})
        text = gw.WorkspaceManager.format_look(res)
        text = text.replace(file_id, "<試験場>")
        look_path(tn, looks_dir).write_text(text + "\n", encoding="utf-8")
        out(f"撮り置き: {tn}（{len(text.splitlines())} 行）")


# ------------------------------------------------------------------ AI（claude -p）
def ws_do_description(path=HERE / "gas_mcp_server.py"):
    """MCP の ws_do の説明（本番の説明そのまま）"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "ws_do":
            return (ast.get_docstring(node, clean=True) or "").strip()
    return ""


def build_prompt(say, look_text, find_reply, description=None):
    return (
        "あなたはスプレッドシートを操作する道具 Workspace の呼び出し役です。次の道具 ws_do の説明と、今の相手の様子（ws_look の返事）、棚の札を見て、"
        "使う人の頼みを 1 回で ws_do の呼び出しにしてください。\n"
        "答えは JSON を 1 つだけ（説明・コードフェンスなし）:\n"
        '  撃つとき: {"ops":[{"shelf":"棚の名前", …引数}], "ok": false}（ok は消す手に承認が要るときだけ true）\n'
        '  指す物が決まらず聞き返すとき: {"質問":"…"}\n'
        '  棚にも api にも無いとき: {"無い":"…"}\n\n'
        f"【ws_do の説明】\n{description or ws_do_description()}\n\n【今の相手の様子（ws_look の返事）】\n{look_text}\n\n【棚の候補】\n{find_reply}\n\n【使う人の頼み】\n{say}\n"
    )


def parse_answer(text):
    """AI の返事 → {"ops","ok"} / {"質問"} / {"無い"} / None（読めない）"""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
    for cand in (s, *re.findall(r"\{.*\}", s, flags=re.S)):
        try:
            v = json.loads(cand)
        except Exception:
            continue
        if isinstance(v, dict) and ("ops" in v or "質問" in v or "無い" in v):
            return v
    return None


def ask_claude(prompt, model="haiku", timeout=AI_TIMEOUT):
    """claude -p（ヘッドレスの Claude Code）。返事の本文と、秒・トークン・費用（--output-format json の中身）を返す"""
    exe = shutil.which("claude") or "claude"
    env = dict(os.environ, CLAUDE_CODE_USE_POWERSHELL_TOOL="1")
    t0 = time.time()
    r = subprocess.run([exe, "-p", "--model", model, "--output-format", "json", "--disallowedTools", "Bash,PowerShell,Edit,Write,Read"],
                       input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, env=env)
    sec = time.time() - t0
    if r.returncode != 0:
        raise RuntimeError("claude -p が失敗しました: " + r.stderr.decode("utf-8", "replace")[:200])
    raw = r.stdout.decode("utf-8", "replace")
    try:
        d = json.loads(raw)
    except Exception:
        return raw, {"sec": sec, "in": None, "out": None, "cost": None}
    u = d.get("usage") or {}
    meta = {"sec": sec, "api_ms": d.get("duration_api_ms"), "in": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0),
            "fresh_in": u.get("input_tokens"), "out": u.get("output_tokens"), "cost": d.get("total_cost_usd")}
    return d.get("result", raw), meta


# ------------------------------------------------------------------ 撃つ・判定
def steps_for(ops, ok, retry_wide=False):
    return [{"snap": "A"}, {"do": ops, "ok": bool(ok), "name": "do", "retry_wide": retry_wide}, {"snap": "B"}, {"undo_all": True, "name": "undo"}, {"snap": "C"}]


def _res(resp):
    return [s for s in resp["steps"] if s.get("name") == "do"][0]["res"]


def run_model(eng, file_id, case):
    """模範を撃つ（流し込む → 撃つ → 戻す）。返り値は seq の返事と、模範の後の状態"""
    table = T.load_table(case["table"])
    turn = case["turns"][0]
    resp = eng.trial_post("seq", id=file_id, seed=T.seed_payload(table), steps=steps_for(case["model"], turn["approve"] == "ある", retry_wide=True))
    return resp, resp["snaps"]["B"]


def judge_model(case, resp):
    """模範の再生: 期待を満たすか。(通ったか, 理由のリスト)"""
    table = T.load_table(case["table"])
    tinfo = T.table_info(table)
    A, B = resp["snaps"]["A"], resp["snaps"]["B"]
    r = _res(resp)
    if not r["ok"]:
        return False, ["模範が通らない: " + str(r.get("error_brief"))[:100]]
    ok, why = J.check_expect(case["turns"][0]["expect"], A, B, B, case["kind"], tinfo)
    why = list(why)
    why += J.check_rules(A, B, touched=_touched(A, B), may_change=tuple(case.get("may_change", [])), tinfo=tinfo)
    if not J.promise_fingerprints(A) == J.promise_fingerprints(resp["snaps"]["C"]):
        why.append("模範を戻した後の指紋が最初と違う")
    return (not why), why


def _touched(A, B):
    return [A["sheets"][0]["name"]] + [s["name"] for s in B["sheets"] if J.sheet_of(A, s["name"]) is None]


def run_ai_turn(eng, file_id, case, answer, model_after, finder, say_find_names):
    """AI の答え 1 つを試験場に撃って判定する。返り値 {mark, F, why, got}"""
    turn = case["turns"][0]
    table = T.load_table(case["table"])
    tinfo = T.table_info(table)
    want = model_shelves(case)
    # 聞き返し・無い
    if answer is None:
        return {"mark": "×", "F": "F3", "why": "返事が JSON として読めない", "got": []}
    if "質問" in answer:
        if turn["askback"] == "要る":
            return {"mark": "△", "F": "", "why": "期待どおりに聞き返した", "got": []}
        return {"mark": "×", "F": "F8", "why": "聞かなくてよい頼みを聞き返した: " + str(answer["質問"])[:60], "got": []}
    if "無い" in answer:
        return {"mark": "×", "F": "F6", "why": "有効な台本で「無い」と答えた", "got": []}
    ops = answer.get("ops")
    okflag = bool(answer.get("ok"))
    if turn["askback"] == "要る":
        return {"mark": "×", "F": "F7", "why": "聞くべき頼みを撃とうとした", "got": [o.get("shelf") for o in ops or [] if isinstance(o, dict)]}
    got = [o.get("shelf") for o in ops or [] if isinstance(o, dict)]
    if turn["approve"] == "まだ" and okflag:
        pass   # F12 は撃った結果と一緒に判定する（道具が止めたかに関わらず ok=True を渡したら F12）
    m = gw.WorkspaceManager(client=object(), state_path=HERE / ".ws_shot_unused.json")
    try:
        m.validate_ops(m.parse_ops(ops))
    except gw.WorkspaceError as e:
        return {"mark": "×", "F": "F3", "why": "引数の検査で止まった: " + str(e).splitlines()[0][:100], "got": got}
    ops = [m.catalog.normalize_op(o) for o in ops]
    resp = eng.trial_post("seq", id=file_id, seed=T.seed_payload(table), steps=steps_for(ops, okflag, retry_wide=False))
    r = _res(resp)
    A, B = resp["snaps"]["A"], resp["snaps"]["B"]
    f12 = turn["approve"] == "まだ" and okflag
    if not r["ok"]:
        if r.get("blocked") and turn["approve"] == "ある" and not okflag:
            return {"mark": "×", "F": "F8", "why": "名指しの消す頼みなのに承認待ちにした（消す台本の F8 は数だけ出す）", "got": got}
        F = "F12" if f12 else ("F3" if r.get("arg") else ("F2" if not set(want) <= set(got) else "F4"))
        return {"mark": "×", "F": F, "why": ("止まった/失敗: " + str(r.get("error_brief"))[:100]), "got": got}
    ok, why = J.check_expect(turn["expect"], A, B, model_after, case["kind"], tinfo)
    why = list(why)
    rules = J.check_rules(A, B, touched=_touched(A, B), may_change=tuple(case.get("may_change", [])), tinfo=tinfo)
    if rules:
        return {"mark": "×", "F": "F9", "why": "壊した: " + "；".join(rules)[:120], "got": got}
    if f12:
        return {"mark": "×", "F": "F12", "why": "承認が要らない頼みで ok=True を付けた", "got": got}
    if not ok:
        return {"mark": "×", "F": "F2" if not set(want) <= set(got) else "F4", "why": "；".join(why)[:140], "got": got}
    return {"mark": "◎", "F": "", "why": "", "got": got}


def candidates_have_model(finder, say, want):
    picks, _, _ = finder.find(say)
    names = [s["name"] for s in picks]
    return all(w in names for w in want), names


def run_shot(eng, file_id, cases, model="haiku", ask_fn=None, out=print, run_file=None, resume=False, times=1, limit_seconds=None):
    """L2b。台本ごとに 模範（期待の比べ先）→ AI の答え → 撃って判定。1 本ごとに書き出す。返り値は (結果のリスト, 記録ファイル)"""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rf = Path(run_file) if run_file else RUNS_DIR / f"shot_{model}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    done = set()
    if resume and rf.exists():
        for ln in rf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add((d["id"], d["n"]))
            except Exception:
                pass
    finder = gas_ws_find.Finder()
    desc = ws_do_description()
    ask = ask_fn or (lambda p: ask_claude(p, model=model))
    results, t_start = [], time.time()
    for case in cases:
        model_resp = model_after = None
        for n in range(1, times + 1):
            if (case["id"], n) in done:
                continue
            if limit_seconds and time.time() - t_start > limit_seconds:
                out("[上限] 全体の時間の上限で止めました（--resume で続きから）")
                return results, rf
            rec = {"id": case["id"], "n": n, "model": model, "table": case["table"], "say": case["turns"][0]["say"]}
            try:
                if model_after is None:
                    model_resp, model_after = run_model(eng, file_id, case)
                    mok, mwhy = judge_model(case, model_resp)
                    if not mok:
                        rec.update(mark="M", F="M", why="模範が期待を満たさない: " + "；".join(mwhy)[:140], got=[])
                        raise StopIteration
                lk = look_path(case["table"]).read_text(encoding="utf-8") if look_path(case["table"]).exists() else ""
                found = finder.ask(case["turns"][0]["say"], log_to=False)
                has, names = candidates_have_model(finder, case["turns"][0]["say"], model_shelves(case))
                text, meta = ask(build_prompt(case["turns"][0]["say"], lk, found, desc))
                rec["ai"] = meta
                rec["l0_has_model"] = has
                res = run_ai_turn(eng, file_id, case, parse_answer(text), model_after, finder, names)
                if res["mark"] == "×" and res["F"] in ("F2", "F4") and not has:
                    res["F"] = "F1a"
                rec.update(res)
            except StopIteration:
                pass
            except Exception as e:
                rec.update(mark="×", F="POST", why="撃てなかった: " + str(e)[:160], got=[], post_fail=True)
            with rf.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            results.append(rec)
            out(f"{rec['mark']} {rec['id']} {rec['table']}「{rec['say'][:24]}」→ {','.join(rec.get('got') or [])} {rec.get('F', '')} {rec.get('why', '')[:70]} ({(rec.get('ai') or {}).get('sec', 0):.0f}s)")
    return results, rf


def summarize(rows):
    n = len(rows)
    ok = [r for r in rows if r["mark"] in ("◎", "△")]
    ai = [r["ai"] for r in rows if r.get("ai")]
    tot = lambda k: sum((a.get(k) or 0) for a in ai)
    return {"n": n, "ok": len(ok), "rate": 100.0 * len(ok) / n if n else 0.0, "F": _count(r.get("F") for r in rows if r["mark"] == "×"),
            "ai_calls": len(ai), "ai_sec": tot("sec"), "in_tokens": tot("in"), "out_tokens": tot("out"), "cost_usd": tot("cost"),
            "sec_each": tot("sec") / len(ai) if ai else 0.0}


def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d
