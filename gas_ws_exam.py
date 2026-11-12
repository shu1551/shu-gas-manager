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
# 試験用の表の様子（固定の 1 枚）。実際の使い方では AI は先に ws_look で相手を見るので、試験でも ws_look の返事と同じ形で渡す
SAMPLE_SHEET = {
    "target": {"id": "sample", "name": "試験用の表", "kind": "sheet", "url": ""},
    "sheets": [{"name": "売上", "rows": 21, "cols": 5}],
    "table": {"header_row": 1, "first_col": 1, "last_col": 5, "data": "2-20", "total_row": 21,
              "columns": [{"col": "A", "name": "番号", "number": True}, {"col": "B", "name": "日付", "number": False},
                          {"col": "C", "name": "部署", "number": False}, {"col": "D", "name": "名前", "number": False},
                          {"col": "E", "name": "金額", "number": True}]},
    "range": "A1:E3",
    "values": [["番号", "日付", "部署", "名前", "金額"], [1, "2026/11/02", "営業", "田中", 12000], [2, "2026/11/03", "総務", "鈴木", 8500]],
}
SAMPLE_DOC = {
    "target": {"id": "sample", "name": "試験用の文書", "kind": "doc", "url": ""},
    "paragraphs": 8,
    "headings": [{"no": 1, "level": 1, "text": "会議の記録"}, {"no": 3, "level": 2, "text": "概要"}, {"no": 6, "level": 2, "text": "決定事項"}],
    "outline": ["1: # 会議の記録", "2: 11/12 定例会議", "3: ## 概要", "4: 今期の進め方を確認した。", "5: - 次回は 12/2", "6: ## 決定事項", "7: - 予算を承認", "8: - 担当を分担"],
}


def sample_look(kind="sheet"):
    """ws_look の返事と同じ形の、試験用の表（または文書）の様子"""
    return gas_workspace.WorkspaceManager.format_look(SAMPLE_DOC if kind == "doc" else SAMPLE_SHEET)


ASK_BACK = re.compile(r"^\s*質問\s*[:：]")


def build_prompt(ask, find_reply, look=""):
    return (
        "あなたはスプレッドシート・文書を操作する道具 Workspace の呼び出し役です。\n"
        "次の「棚の候補」だけを使って、頼みを ws_do の ops（棚の JSON 配列）にしてください。\n"
        "棚の名前と引数は札のとおりに。合う棚が無ければ [] とだけ答えてください。\n"
        "頼みで指す物（どの列・どの行・どの範囲か）が表の様子から決まらないときは、ops を作らず「質問: …」の 1 行だけ答えてください。\n"
        "答えは JSON の配列だけ（説明・コードフェンスなし）。\n\n"
        + (f"【今の相手の様子（ws_look の返事）】\n{look}\n\n" if look else "")
        + f"【棚の候補】\n{find_reply}\n\n【頼み】\n{ask}\n"
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
def alt_satisfied(ops, alts):
    """別解: 返答の ops が、別解のどれか 1 つの「棚（と引数）」をすべて満たす"""
    for alt in alts:
        if all(any(isinstance(o, dict) and o.get("shelf") == shelf and all(o.get(k) not in (None, "", []) for k in keys) for o in ops) for shelf, keys in alt):
            return True
    return False


def evaluate(questions, ask_fn, manager=None, finder=None, extras=None, with_look=True):
    """各問を AI に聞いて数える。返り値は (結果の dict のリスト, 集計の dict)。
    extras は問題集の印（? ＝聞き返しも正解・別解）。with_look は試験用の表の様子を渡すか"""
    mgr = manager or gas_workspace.WorkspaceManager(client=object())
    finder = finder or mgr.finder
    extras = gas_ws_check.load_extras() if extras is None else extras
    results = []
    for exp, ask, src in questions:
        reply = finder.ask(ask, log_to=False)
        raw = err = None
        ops = None
        mark = extras.get(ask, {})
        kind = "doc" if any(gas_workspace.CATALOG.by_name[e]["kind"] == "doc" for e in exp if e in gas_workspace.CATALOG.by_name) else "sheet"
        try:
            raw = ask_fn(build_prompt(ask, reply, sample_look(kind) if with_look else ""))
            if ASK_BACK.match(raw or ""):
                if mark.get("ask_ok"):                # 指す物が決まらない頼み: 聞き返しも正解
                    results.append({"ask": ask, "expect": exp, "got": ["（聞き返し）"], "shelf_ok": True, "valid": True, "why": "", "src": src, "asked": True})
                    continue
                err = "聞き返しました（この問では聞き返しを正解に数えない）"
            else:
                ops = parse_ops_from(raw)
        except Exception as e:                       # AI が答えなかった問は、棚も検査も外れとして数える
            err = f"AI の呼び出しに失敗: {e}"
        names = [o.get("shelf") for o in ops if isinstance(o, dict)] if ops else []
        shelf_ok = bool(ops) and (all(e in names for e in exp) or alt_satisfied(ops, mark.get("alts", [])))
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
    stats = {"n": n, "shelf_ok": ok_shelf, "valid": ok_valid, "asked": sum(1 for r in results if r.get("asked")),
             "shelf_pct": 100.0 * ok_shelf / n if n else 0.0, "valid_pct": 100.0 * ok_valid / n if n else 0.0}
    stats["pass"] = n > 0 and stats["shelf_pct"] >= TARGET and stats["valid_pct"] >= TARGET
    return results, stats


def report(results, stats):
    lines = [f"AI を通した試験 {stats['n']} 問: 正しい棚 {stats['shelf_ok']}/{stats['n']}（{stats['shelf_pct']:.0f}%）・"
             f"検査を通る ops {stats['valid']}/{stats['n']}（{stats['valid_pct']:.0f}%）・目安は両方 {TARGET:.0f}% 以上 → "
             + ("目安どおり" if stats["pass"] else "目安を下回りました")]
    if stats.get("asked"):
        lines[0] += f"（うち聞き返し {stats['asked']} 問は正解に数えた）"
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
