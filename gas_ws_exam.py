# -*- coding: utf-8 -*-
"""
gas_ws_exam.py - AI を通した試験 `py gas.py ws-exam --ai [--n 30]`（設計書 第 6.3 節）

問題集（ws_exam/phrases_*.tsv）から選んだ頼みについて、`ws_find` の返事と頼みの文を AI に渡し、
返ってきた ops を `validate_ops` にかけて、
  ・棚の名前が期待どおりか（期待の棚が全部 ops に入っているか）
  ・引数の検査を通るか
を数える。実在のファイルには触らない（ws_do は撃たない。validate_ops は形を見るだけで通信しない）。
目安は「正しい棚 9 割以上・検査を通る ops 9 割以上」。下回った問は、札の `違い:`・`例:` を直す材料にする。

既定の AI は、ヘッドレスの Claude Code（`claude -p`・sonnet・API 鍵なし）。`ask_fn` を差し替えれば偽の AI で数え方を試験できる。
"""

import json
import os
import re
import shutil
import subprocess

import gas_workspace
import gas_ws_check
import gas_ws_find

DEFAULT_MODEL = "sonnet"
DEFAULT_N = 30
TARGET = 90.0
AI_TIMEOUT = 180


# ------------------------------------------------------------------ 問題を選ぶ
def select_questions(n=DEFAULT_N, exam_dir=gas_ws_check.EXAM_DIR):
    """棚が期待の問から、棚ごとにまんべんなく n 問。順番は決まっている（同じ n なら同じ問）"""
    cat = gas_workspace.CATALOG
    qs = [(exp, ask, src) for exp, ask, src in gas_ws_check.load_questions(exam_dir) if exp and exp[0] not in ("(なし)", "(案内)")
          and len({cat.by_name[e]["kind"] for e in exp if e in cat.by_name}) <= 1]       # シートと文書の両方が期待の問（どちらかが正解）は、1 回の ops にならないので除く
    by_shelf = {}
    for q in qs:
        by_shelf.setdefault(q[0][0], []).append(q)
    pools = [by_shelf[k] for k in sorted(by_shelf)]
    out, i = [], 0
    while len(out) < n and any(i < len(p) for p in pools):
        for p in pools:
            if i < len(p) and len(out) < n:
                out.append(p[i])
        i += 1
    return out


# ------------------------------------------------------------------ AI に渡す物・返事を読む
def build_prompt(ask, find_reply):
    return (
        "あなたはスプレッドシート・文書を操作する道具 Workspace の呼び出し役です。\n"
        "次の「棚の候補」だけを使って、頼みを ws_do の ops（棚の JSON 配列）にしてください。\n"
        "棚の名前と引数は札のとおりに。合う棚が無ければ [] とだけ答えてください。\n"
        "答えは JSON の配列だけ（説明・コードフェンスなし）。\n\n"
        f"【棚の候補】\n{find_reply}\n\n【頼み】\n{ask}\n"
    )


def parse_ops_from(text):
    """AI の返事から ops（dict のリスト）を取り出す。読めなければ None"""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
    for cand in (s, *re.findall(r"\[.*\]", s, flags=re.S)):
        try:
            v = json.loads(cand)
        except Exception:
            continue
        if isinstance(v, dict):
            v = [v]
        if isinstance(v, list):
            return v
    return None


def claude_code_ask(prompt, model=DEFAULT_MODEL, timeout=AI_TIMEOUT):
    """既定の AI: ヘッドレスの Claude Code（`claude -p`）。鍵は要らない。実在のファイルには触らせない（道具を許さない）"""
    exe = shutil.which("claude") or "claude"   # Windows は claude.cmd（npm）なので名前だけでは見つからない
    # Windows で Bash だけ禁じると「PowerShell も無くなる」で止まるので、PowerShell の道具を有効にしてから両方禁じる
    env = dict(os.environ, CLAUDE_CODE_USE_POWERSHELL_TOOL="1")
    r = subprocess.run([exe, "-p", "--model", model, "--disallowedTools", "Bash,PowerShell,Edit,Write,Read"],
                       input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError("claude -p が失敗しました: " + r.stderr.decode("utf-8", "replace")[:200])
    return r.stdout.decode("utf-8", "replace")


# ------------------------------------------------------------------ 数える
def evaluate(questions, ask_fn, manager=None, finder=None):
    """各問を AI に聞いて数える。返り値は (結果の dict のリスト, 集計の dict)"""
    mgr = manager or gas_workspace.WorkspaceManager(client=object())
    finder = finder or mgr.finder
    results = []
    for exp, ask, src in questions:
        reply = finder.ask(ask, log_to=False)
        raw = err = None
        ops = None
        try:
            raw = ask_fn(build_prompt(ask, reply))
            ops = parse_ops_from(raw)
        except Exception as e:                       # AI が答えなかった問は、棚も検査も外れとして数える
            err = f"AI の呼び出しに失敗: {e}"
        names = [o.get("shelf") for o in ops if isinstance(o, dict)] if ops else []
        shelf_ok = bool(ops) and all(e in names for e in exp)
        valid, why = False, ""
        if ops is None:
            why = err or "返事が JSON の配列として読めません"
        elif not ops:
            why = "ops が空（棚にありません、と答えた）"
        else:
            try:
                mgr.validate_ops(ops)
                valid = True
            except gas_workspace.WorkspaceError as e:
                why = str(e).splitlines()[0]
            except Exception as e:
                why = f"検査で想定外: {e}"
        results.append({"ask": ask, "expect": exp, "got": names, "shelf_ok": shelf_ok, "valid": valid, "why": why, "src": src})
    n = len(results)
    ok_shelf = sum(r["shelf_ok"] for r in results)
    ok_valid = sum(r["valid"] for r in results)
    stats = {"n": n, "shelf_ok": ok_shelf, "valid": ok_valid,
             "shelf_pct": 100.0 * ok_shelf / n if n else 0.0, "valid_pct": 100.0 * ok_valid / n if n else 0.0}
    stats["pass"] = n > 0 and stats["shelf_pct"] >= TARGET and stats["valid_pct"] >= TARGET
    return results, stats


def report(results, stats):
    lines = [f"AI を通した試験 {stats['n']} 問: 正しい棚 {stats['shelf_ok']}/{stats['n']}（{stats['shelf_pct']:.0f}%）・"
             f"検査を通る ops {stats['valid']}/{stats['n']}（{stats['valid_pct']:.0f}%）・目安は両方 {TARGET:.0f}% 以上 → "
             + ("目安どおり" if stats["pass"] else "目安を下回りました")]
    bad = [r for r in results if not (r["shelf_ok"] and r["valid"])]
    if bad:
        lines.append("下回った問（札の「違い:」「例:」を直す材料）:")
        for r in bad:
            what = []
            if not r["shelf_ok"]:
                what.append("棚が違う（期待 " + "+".join(r["expect"]) + " / 返答 " + ("・".join(map(str, r["got"])) or "なし") + "）")
            if not r["valid"]:
                what.append("検査を通らない: " + r["why"])
            lines.append(f"  - {r['ask']} … " + "。".join(what) + f"  [{r['src']}]")
    return lines


def main(n=DEFAULT_N, model=DEFAULT_MODEL, ask_fn=None):
    """終了コードは常に 0（数字を出す試験。目安を下回っても止めない）。実在のファイルには触らない"""
    qs = select_questions(n)
    fn = ask_fn or (lambda p: claude_code_ask(p, model=model))
    results, stats = evaluate(qs, fn)
    print("\n".join(report(results, stats)))
    return 0
