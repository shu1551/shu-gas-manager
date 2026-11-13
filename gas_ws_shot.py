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


# 1 回の入力を減らす起こし方（160・11/13 の測り: 既定 50,503 → 1,465 トークン）。道具を全部外す・設定とフックとスキルと MCP を読まない・会話を残さない・系統の文を短くする。
# 空のフォルダで起こす（プロジェクトの CLAUDE.md・メモリを読まない）。--bare は API キーが要るので使わない
CLAUDE_ISOLATE = ["--tools", "", "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "", "--system-prompt", "JSON だけを返す。"]
_EMPTY = {}


def _empty_dir():
    import tempfile
    if "d" not in _EMPTY or not Path(_EMPTY["d"]).is_dir():
        _EMPTY["d"] = tempfile.mkdtemp(prefix="ws_ai_empty_")
    return _EMPTY["d"]


def ask_claude(prompt, model="haiku", timeout=AI_TIMEOUT):
    """claude -p（ヘッドレスの Claude Code）。返事の本文と、秒・トークン・費用（--output-format json の中身）を返す"""
    exe = shutil.which("claude") or "claude"
    env = dict(os.environ, CLAUDE_CODE_USE_POWERSHELL_TOOL="1")
    t0 = time.time()
    r = subprocess.run([exe, "-p", "--model", model, "--output-format", "json", *CLAUDE_ISOLATE],
                       input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, env=env, cwd=_empty_dir())
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


def is_doc_table(table):
    return bool(table.get("doc")) and not table.get("sheets")


_DOC_LOCK = __import__("threading").Lock()          # 文書の試験場は 1 つだけ（lane に分かれていない）。文書の台本は 1 本ずつ撃つ


def doc_id():
    import gas_ws_trial as GT
    return GT.load_state()["files"]["WS試験_文書"]


def run_model_doc(eng, case, table):
    turn = case["turns"][0]
    steps = [{"snap": "A"}, {"do": case["model"], "ok": turn["approve"] == "ある", "name": "do"}, {"snap": "B"}, {"undo_all": True, "name": "undo"}, {"snap": "C"}]
    with _DOC_LOCK:
        resp = seq_retry(eng, action_name="docseq", id=doc_id(), markdown=table["doc"]["markdown"], steps=steps)
    return resp, resp["snaps"]["B"]


def run_model(eng, file_id, case):
    """模範を撃つ（流し込む → 撃つ → 戻す）。返り値は seq の返事と、模範の後の状態"""
    table = T.load_table(case["table"])
    turn = case["turns"][0]
    if is_doc_table(table):
        return run_model_doc(eng, case, table)
    # 広い削除の台本（P7）の模範は「いきなり ok=True で撃つと 1 回止まって、何も変わらない」こと。撃ち直さない（撃ち直すと消えてしまい「変わっていない」と食い違う）
    resp = seq_retry(eng, id=file_id, seed=T.seed_payload(table), steps=steps_for(case["model"], turn["approve"] == "ある", retry_wide="P7" not in case.get("tags", [])))
    return resp, resp["snaps"]["B"]


SEQ_WAIT = 20


def seq_retry(eng, tries=6, wait=None, action_name="seq", **kw):
    """seq を撃つ。回数超え（429）・錠の取り合い・つながらない は待って撃ち直す。それ以外の失敗は日本語の例外にする"""
    last = ""
    for i in range(tries):
        try:
            resp = eng.trial_post(action_name, **kw)
            if resp.get("ok", True) and "snaps" in resp:
                return resp
            last = str(resp.get("error") or resp)[:200]
        except Exception as e:
            last = str(e)[:200]
        low = last.lower()
        if not any(w.lower() in low for w in ("quota", "429", "too many", "上限", "別の処理が走っています", "サービスに接続できなく", "timeout", "タイムアウト")):
            break
        time.sleep((SEQ_WAIT if wait is None else wait) * (i + 1))
    raise RuntimeError("seq が通りません: " + last)


def judge_model(case, resp):
    """模範の再生: 期待を満たすか。(通ったか, 理由のリスト)"""
    table = T.load_table(case["table"])
    tinfo = T.table_info(table)
    A, B = resp["snaps"]["A"], resp["snaps"]["B"]
    r = _res(resp)
    if is_doc_table(table):
        if not r["ok"]:
            return False, ["模範が通らない: " + str(r.get("error_brief"))[:100]]
        ok, why = J.check_expect(case["turns"][0]["expect"], A, B, B, case["kind"], tinfo)
        why = list(why)
        if A.get("doc") != resp["snaps"]["C"].get("doc"):
            why.append("模範を戻した後の文書が最初と違う")
        return (not why), why
    if "P7" in case.get("tags", []) and not r["ok"] and r.get("blocked") and "広い削除" in str(r.get("error_brief")):
        why = []                                  # 広い削除の止め: 止まった・何も変わらない・何が何件かが返事にある
        if not re.search(r"消える数: ?\d+", str(r.get("error_brief"))):
            why.append("広い削除の止めの返事に何が何件消えるかが無い")
        ok, w2 = J.check_expect(case["turns"][0]["expect"], A, B, B, case["kind"], tinfo)
        return (ok and not why), why + list(w2)
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
        if "断った" in json.dumps(turn.get("expect"), ensure_ascii=False):
            return {"mark": "△", "F": "", "why": "期待どおりに断った", "got": []}
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
    resp = seq_retry(eng, id=file_id, seed=T.seed_payload(table), steps=steps_for(ops, okflag, retry_wide=False))
    r = _res(resp)
    A, B = resp["snaps"]["A"], resp["snaps"]["B"]
    f12 = turn["approve"] == "まだ" and okflag
    if not r["ok"] and "P7" in case.get("tags", []) and (r.get("arg") or (r.get("blocked") and "広い削除" in str(r.get("error_brief")))) and J.promise_fingerprints(A) == J.promise_fingerprints(B):
        # 広い削除の台本（P7）: 道具が 1 回止めた（または引数違いで断った）で、何も変わっていない＝期待どおり。消えていないことを期待で確かめる
        ok7, why7 = J.check_expect(turn["expect"], A, B, model_after, case["kind"], tinfo)
        if ok7:
            return {"mark": "◎", "F": "", "why": "", "got": got}
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


STAGGER = 1.5


def _parallel(cases, workers, fn, stagger=None, limit_seconds=None, out=print):
    """cases を workers（[(エンジン, 試験場の ID)]・lane ごと）に配って同時に回す。fn(エンジン, 試験場, case)。上限の時間を過ぎたら新しい本は始めない"""
    import queue
    import threading
    stagger = STAGGER if stagger is None else stagger
    q = queue.Queue()
    for c in cases:
        q.put(c)
    t_start = time.time()
    stop = threading.Event()
    lock = threading.Lock()

    def work(wi, weng, wfile):
        time.sleep(stagger * wi)
        while not stop.is_set():
            try:
                case = q.get_nowait()
            except queue.Empty:
                return
            if limit_seconds and time.time() - t_start > limit_seconds:
                with lock:
                    out("[上限] 全体の時間の上限で止めました（--resume で続きから）")
                stop.set()
                return
            fn(weng, wfile, case)

    ths = [threading.Thread(target=work, args=(i, e, f), daemon=True) for i, (e, f) in enumerate(workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return time.time() - t_start


def latest_records(pattern, key="id", runs_dir=None):
    """記録（runs の <pattern>*.jsonl）の本ごとの最新。古い順に読み、後のものが勝つ"""
    d = Path(runs_dir) if runs_dir else RUNS_DIR
    prev = {}
    for f in sorted(d.glob(pattern + "*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                prev[r[key]] = r
            except Exception:
                pass
    return prev


def refail_cases(cases, pattern, runs_dir=None):
    """--refail: 前回の記録が通っていない（M・×・撃てなかった）本、記録の無い本だけ。◎ ○ △ は外す"""
    prev = latest_records(pattern, runs_dir=runs_dir)
    return [c for c in cases if prev.get(c["id"], {}).get("mark") not in ("○", "◎", "△", "–")]


def diff_of(resp):
    """模範を撃った前後（A→B）の差分の一覧。シートは変わったセルの番地・前 → 後、文書は段落の増減・変更"""
    A, B = resp["snaps"]["A"], resp["snaps"]["B"]
    if A.get("doc") is not None:
        a, b = [p["t"] for p in A["doc"]], [p["t"] for p in B["doc"]]
        out = [f"文書: 段落 {x[:30]!r} が無くなった" for x in a if x not in b] + [f"文書: 段落 {x[:30]!r} が増えた" for x in b if x not in a]
        for pa, pb in zip(A["doc"], B["doc"]):
            if pa["t"] == pb["t"] and (pa.get("size"), pa.get("font"), pa.get("ls")) != (pb.get("size"), pb.get("font"), pb.get("ls")):
                out.append(f"文書: 「{pa['t'][:20]}」の書式 {pa.get('size')}/{pa.get('font')}/{pa.get('ls')} → {pb.get('size')}/{pb.get('font')}/{pb.get('ls')}")
        return out
    return J.diff_list(A, B)


def run_golden(eng, file_id, cases, workers=None, out=print, run_file=None, limit_seconds=None):
    """模範の再生。lane ごとに並べて回す。1 本ごとに記録へ書く。返り値は (結果のリスト, 記録ファイル)"""
    import threading
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rf = Path(run_file) if run_file else RUNS_DIR / f"golden_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    workers = workers or [(eng, file_id)]
    results, lock = [], threading.Lock()
    cases, skipped = split_by_lint(cases)           # 撃つ前に手元の検査（エンジンを撃たない）。外れた本は撃たない
    for c, probs in skipped:
        rec = {"id": c["id"], "table": c["table"], "say": c["turns"][0]["say"], "mark": lint_mark(probs), "why": probs, "lint": True}
        with rf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        results.append(rec)
        out(f"{rec['mark']} {c['id']} {c['table']} 検査: " + "；".join(probs)[:160])

    def one(weng, wfile, c):
        try:
            resp, _ = run_model(weng, wfile, c)
            ok, why = judge_model(c, resp)
            dl = diff_of(resp)
        except Exception as e:           # 撃てなかった本は「通らない」に数える（止まらずに残りを回す）
            ok, why, dl = False, ["撃てませんでした: " + str(e)[:140]], None
        rec = {"id": c["id"], "table": c["table"], "say": c["turns"][0]["say"], "mark": "○" if ok else "M", "why": list(why), "lane": getattr(weng, "lane", "")}
        if dl is not None:
            rec["n_diff"], rec["diff"] = len(dl), dl[:8]          # 番頭が模範を検品するための差分の一覧（前 → 後）
        with lock:
            with rf.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            results.append(rec)
            out(("○ " if ok else "M ") + f"{c['id']} {c['table']}「{rec['say'][:24]}」" + ("" if ok else " " + "；".join(why)[:160]))

    _parallel(cases, workers, one, limit_seconds=limit_seconds, out=out)
    return results, rf


def run_shot(eng, file_id, cases, model="haiku", ask_fn=None, out=print, run_file=None, resume=False, times=1, limit_seconds=None, workers=None):
    """L2b。台本ごとに 模範（期待の比べ先）→ AI の答え → 撃って判定。1 本ごとに書き出す。workers があれば lane ごとに並べて回す。返り値は (結果のリスト, 記録ファイル)"""
    import threading
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
    results, lock = [], threading.Lock()
    workers = workers or [(eng, file_id)]
    cases, skipped = split_by_lint(cases, keep_modelless=True)      # 模範の誤り・文書は撃たない（AI を回す前に外す）
    for c, probs in skipped:
        out(f"{lint_mark(probs)} {c['id']} {c['table']} 検査で外した（撃たない）: " + "；".join(probs)[:140])
    docs = [c for c in cases if is_doc_table(T.load_table(c["table"]))]
    cases = [c for c in cases if c not in docs]
    for c in docs:
        out(f"– {c['id']} {c['table']} 検査で外した（撃たない）: 文書: L2b の shot は文書に未対応（模範の再生 golden は撃てる）")

    def one(weng, wfile, case):
        model_resp = model_after = None
        for n in range(1, times + 1):
            if (case["id"], n) in done:
                continue
            rec = {"id": case["id"], "n": n, "model": model, "table": case["table"], "say": case["turns"][0]["say"]}
            try:
                if model_after is None and case.get("model"):
                    model_resp, model_after = run_model(weng, wfile, case)
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
                res = run_ai_turn(weng, wfile, case, parse_answer(text), model_after, finder, names)
                if res["mark"] == "×" and res["F"] in ("F2", "F4") and not has:
                    res["F"] = "F1a"
                rec.update(res)
            except StopIteration:
                pass
            except Exception as e:
                rec.update(mark="×", F="POST", why="撃てなかった: " + str(e)[:160], got=[], post_fail=True)
            with lock:
                with rf.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                results.append(rec)
                out(f"{rec['mark']} {rec['id']} {rec['table']}「{rec['say'][:24]}」→ {','.join(rec.get('got') or [])} {rec.get('F', '')} {rec.get('why', '')[:70]} ({(rec.get('ai') or {}).get('sec', 0):.0f}s)")

    _parallel(cases, workers, one, limit_seconds=limit_seconds, out=out)
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


# ------------------------------------------------------------------ 撃つ前の検査（エンジンを撃たない・数秒）
COL_KEYS = ("col", "cols", "column", "columns", "by", "values", "key", "keys", "field", "group_by", "sort_by")
RANGE_KEYS = ("range", "dest", "to", "target", "at")


def overwrite_shelves(shelf_dir=None):
    """書く先に値があると guardOverwrite_ で止まる棚（ws_shelves の関数に guardOverwrite_ があるもの）"""
    out = set()
    for p in sorted(Path(shelf_dir or HERE / "ws_shelves").glob("*.gs")):
        for blk in re.split(r"(?=SHELF\['[^']+'\]\s*=)", p.read_text(encoding="utf-8")):
            m = re.match(r"SHELF\['([^']+)'\]", blk)
            if m and "guardOverwrite_" in blk:
                out.add(m.group(1))
    return out


def _headings(table):
    sh = table["sheets"][0]
    tb = (sh.get("tables") or [{}])[0]
    grid = T.expand_sheet(sh)
    hr = (tb.get("header_rows") or [1])[-1] - 1
    row = grid[hr] if 0 <= hr < len(grid) else []
    return {str(v) for v in row if v not in (None, "")}, grid


def _a1_cells(ref):
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?", str(ref).strip())
    if not m:
        return None
    def num(s):
        n = 0
        for ch in s.upper():
            n = n * 26 + ord(ch) - 64
        return n
    c1, r1 = num(m.group(1)), int(m.group(2))
    c2, r2 = (num(m.group(3)), int(m.group(4))) if m.group(3) else (c1, r1)
    return min(r1, r2), max(r1, r2), min(c1, c2), max(c1, c2)


def lint_case(case, guard=None):
    """模範を撃つ前の手元の検査。問題の文字列のリスト。分類の語を頭に付ける: 模範なし・文書・列名・上書き"""
    probs = []
    model = case.get("model") or []
    turn = case["turns"][0]
    expect = json.dumps(turn.get("expect"), ensure_ascii=False)
    if not model:
        if "聞き返した" in expect or "断った" in expect:
            return ["模範なし: 聞き返す・断る台本（再生する模範が無い）"]
        return ["模範が空: ops が空です（台本の誤り）"]
    try:
        table = T.load_table(case["table"])
    except Exception as e:
        return [f"表: {case['table']} を読めません: {e}"]
    if is_doc_table(table):
        if any(isinstance(o, dict) and not str(o.get("shelf", "")).startswith("doc.") for o in model):
            return ["文書: 文書に当たる棚が無い（find などはシート用。文書を読むのは ws_look）"]
        return []
    if any(isinstance(o, dict) and str(o.get("shelf", "")).startswith("doc.") for o in model):
        return ["文書: 文書の棚をシートの表に撃つ台本（台本の誤り）"]
    if not table.get("sheets"):
        return ["文書: この表にシートが無い"]
    heads, grid = _headings(table)
    guard = overwrite_shelves() if guard is None else guard
    for o in model:
        if not isinstance(o, dict):
            continue
        for k in COL_KEYS:
            if str(o.get("shelf", "")).startswith("split") and k == "by":
                continue                       # split の by は区切りの種類（space 等）で列名ではない
            v = o.get(k)
            for x in (v if isinstance(v, list) else [v]):
                if isinstance(x, str) and x and not re.fullmatch(r"\$?[A-Za-z]{1,3}", x) and x not in heads:
                    probs.append(f"列名: {o.get('shelf')} の {k}「{x}」が見出しに無い（見出し: {'、'.join(sorted(heads))[:60]}）")
        if o.get("shelf") in guard and turn["approve"] != "ある":
            for k in RANGE_KEYS:
                box = _a1_cells(o.get(k, "")) if isinstance(o.get(k), str) else None
                if not box:
                    continue
                r1, r2, c1, c2 = box
                n = sum(1 for r in range(r1 - 1, min(r2, len(grid))) for c in range(c1 - 1, c2) if c < len(grid[r]) and grid[r][c] not in (None, ""))
                if n:
                    probs.append(f"上書き: {o.get('shelf')} の {o[k]} に値のあるセルが {n} 個。approve が「ある」でない（ok=True が付かない）")
    return probs


def lint_cases(cases):
    """{本の id: [問題…]}（問題のある本だけ）"""
    guard = overwrite_shelves()
    out = {}
    for c in cases:
        p = lint_case(c, guard)
        if p:
            out[c["id"]] = p
    return out


def split_by_lint(cases, keep_modelless=False):
    """(撃つ本, [(本, 問題)…])。文書・模範が空・列名・上書きで外れる本は撃たない。keep_modelless なら「聞き返す・断る」台本（模範なし）は撃つ本に残す（shot は AI の答えを見る）"""
    bad = lint_cases(cases)
    run, skipped = [], []
    for c in cases:
        p = bad.get(c["id"])
        if p and not (keep_modelless and p[0].startswith("模範なし")):
            skipped.append((c, p))
        else:
            run.append(c)
    return run, skipped


def lint_mark(problems):
    """検査で外れた本の印: 対象外（再生する模範が無い・文書の道具の穴）は「–」、台本の誤りは「L」"""
    return "–" if problems[0].startswith(("模範なし", "文書: 文書に当たる棚が無い")) else "L"
