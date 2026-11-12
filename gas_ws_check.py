# -*- coding: utf-8 -*-
"""
gas_ws_check.py - Workspace の棚の検査 `py gas.py ws-check`（純 Python・通信なし・数秒）

止める問題が 1 つでもあれば終了コード 1。検査の中身は設計書 第 6.2 節:
  1. 札の検査（形・守り・棚名の決め打ち）と、棚ごとの問題数（4 問以上）
  2. 引く試験: 全問で、期待の棚が全部、返る札の中に入っていること
  3. 数字で出す（止めない）: 1 位率・(なし) の問で 1 位が 6 点以上の数
  4. 前回から落ちた: 前回は札の中にあった期待の棚が今回は入っていない
  5. 手元の記録（止めない）: .ws_misses.tsv のうち今は 6 点以上で引ける物
  6. 説明の量: MCP の ws_* の説明が各 4 行以内・合わせて 16 行以内。手順書に棚の名前の表が無い
通ったら ws_exam/answers.tsv を書く（前回の控え。近道で通す手は作らない）。
"""

import ast
import re
from pathlib import Path

import gas_ws_catalog
import gas_ws_find

HERE = Path(__file__).resolve().parent
EXAM_DIR = HERE / "ws_exam"
ANSWERS = EXAM_DIR / "answers.tsv"
MCP_FILE = HERE / "gas_mcp_server.py"
DOC_FILES = ["WORKSPACE.md", "SKILL.md"]
MIN_QUESTIONS = 4
DOC_LINES_EACH = 4
DOC_LINES_TOTAL = 16
DOC_NAMES_MAX = 5
RATE_DROP = 5.0


def load_questions(exam_dir=EXAM_DIR):
    """[(期待のリスト or 特別, 頼みの文, 出どころ)]。特別は '(なし)'・'(案内)'"""
    qs = []
    for p in sorted(Path(exam_dir).glob("phrases_*.tsv"), key=lambda x: x.name):
        for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) < 2 or not parts[1].strip():
                continue
            exp = parts[0].strip()
            qs.append(([exp] if exp in ("(なし)", "(案内)") else [e.strip().lstrip("?") for e in exp.split("+") if e.strip()], parts[1].strip(), f"{p.name}:{n}"))
    return qs


def parse_alternatives(text):
    """別解の書き方: `棚{引数,引数}+棚` を `|` で並べる。返り値は [[(棚, [引数…]), …], …]"""
    alts = []
    for alt in (text or "").split("|"):
        items = []
        for part in alt.split("+"):
            m = re.match(r"^\s*([a-z0-9.]+)\s*(?:\{([^}]*)\})?\s*$", part)
            if m:
                items.append((m.group(1), [k.strip() for k in (m.group(2) or "").split(",") if k.strip()]))
        if items:
            alts.append(items)
    return alts


def load_extras(exam_dir=EXAM_DIR):
    """問題集の印。{頼みの文: {"ask_ok": 聞き返しも正解, "alts": 別解}}。
    期待の欄で棚の名前に `?` を付けると、AI が聞き返す（質問: …）のも正解に数える。
    3 列目に別解を書ける（例 `seiri{renumber,dedupe}`＝seiri に renumber と dedupe の引数が付いていれば、別の棚と組みでなくても正解）"""
    out = {}
    for p in sorted(Path(exam_dir).glob("phrases_*.tsv"), key=lambda x: x.name):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) < 2:
                continue
            ask_ok = "?" in parts[0]
            alts = parse_alternatives(parts[2]) if len(parts) >= 3 else []
            if ask_ok or alts:
                out[parts[1].strip()] = {"ask_ok": ask_ok, "alts": alts}
    return out


def card_questions(cat):
    """札の `例:` も問題として読む"""
    return [([s["name"]], ask, f"{s['file']}:{s['name']}の例") for s in cat.shelves if s["searchable"] for ask, _ in s["examples"]]


def load_answers(path=ANSWERS):
    out = {}
    p = Path(path)
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2 and not ln.startswith("#"):
                out[parts[0]] = [x for x in parts[1].split(",") if x]
    return out


def mcp_doc_lines(path=MCP_FILE):
    """MCP の ws_* 道具の説明（docstring）の行数"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("ws_"):
            d = ast.get_docstring(node, clean=True) or ""
            out[node.name] = len([x for x in d.splitlines() if x.strip()])
    return out


def doc_shelf_names(cat, files=DOC_FILES, root=HERE):
    """手順書の中でバッククォートに入った棚の名前（種類）"""
    found = set()
    for fn in files:
        p = Path(root) / fn
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"`([^`\n]+)`", text):
            if m.group(1) in cat.by_name:
                found.add(m.group(1))
    return found


def run(write=True, exam_dir=EXAM_DIR, answers_path=ANSWERS):
    """検査して (止める問題, 注意, 要約の 1 行, 机上の結果の行) を返す"""
    problems, notes = [], []
    cat = gas_ws_catalog.load()
    problems += gas_ws_catalog.check(cat)
    finder = gas_ws_find.Finder(cat)
    prev = load_answers(answers_path)

    qs = load_questions(exam_dir)
    searchable = [s["name"] for s in cat.shelves if s["searchable"]]
    # 棚ごとの問題数（札の例は数えない）
    count = {n: 0 for n in searchable}
    for exp, _, src in qs:
        if "ijiwaru" in src:
            continue
        for e in exp:
            if e in count:
                count[e] += 1
    for n, c in count.items():
        if c < MIN_QUESTIONS:
            problems.append(f"棚「{n}」の問題が {c} 問です（{MIN_QUESTIONS} 問以上）")
    for exp, ask, src in qs:
        for e in exp:
            if e not in ("(なし)", "(案内)") and e not in cat.by_name:
                problems.append(f"{src}: 期待の棚「{e}」が目録にありません（{ask}）")

    allq = qs + card_questions(cat)
    top1_ok = top1_n = 0
    none_strong = 0
    answers = {}
    dropped = []
    results = []
    for exp, ask, src in allq:
        picks, scores, guide = finder.find(ask)
        names = [s["name"] for s in picks]
        answers[ask] = names
        top = scores.get(names[0], 0) if names else 0
        real = [e for e in exp if e in cat.by_name]
        if exp == ["(案内)"]:
            ok = bool(guide)
            if not ok:
                problems.append(f"{src}: 案内の項目が出ません（{ask}）")
        elif exp == ["(なし)"]:
            ok = True
            if top >= gas_ws_find.WEAK_SCORE:
                none_strong += 1
        else:
            missing = [e for e in real if e not in names]
            ok = not missing
            if missing:
                msg = f"{src}: 期待の棚 {'・'.join(missing)} が札の中にありません（{ask}） 返った札: {'、'.join(names) or 'なし'}"
                if "ijiwaru" in src:
                    notes.append("机上の問が入りませんでした（語は水増ししない・報告に載せる）: " + msg)   # 机上の意地悪な問は止めず、一覧にして出す
                else:
                    problems.append(msg)
            top1_n += 1
            if names and names[0] in real:
                top1_ok += 1
            was = prev.get(ask)
            if was is not None:
                lost = [e for e in real if e in was and e not in names]
                if lost:
                    dropped.append(f"前回は札の中にあった {'・'.join(lost)} が今回は入っていません（{ask}）")
        results.append((exp, ask, names, ok, top, src))
    problems += dropped
    rate = 100.0 * top1_ok / top1_n if top1_n else 100.0

    # 前回の 1 位率（今の問題で、前回の控えを採点し直す）
    if prev:
        p_ok = p_n = 0
        for exp, ask, _ in allq:
            real = [e for e in exp if e in cat.by_name]
            if real and ask in prev:
                p_n += 1
                if prev[ask] and prev[ask][0] in real:
                    p_ok += 1
        if p_n:
            prate = 100.0 * p_ok / p_n
            if rate < prate - RATE_DROP:
                notes.append(f"注意: 1 位率が前回 {prate:.0f}% から {rate:.0f}% に下がりました")
    if none_strong:
        notes.append(f"(なし) の問で 1 位が {gas_ws_find.WEAK_SCORE} 点以上の物が {none_strong} 問あります")

    # 手元の記録
    mp = gas_ws_find.MISSES_FILE
    if mp.exists():
        strong = []
        for ln in mp.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2:
                picks, scores, _ = finder.find(parts[1])
                if picks and scores.get(picks[0]["name"], 0) >= gas_ws_find.WEAK_SCORE:
                    strong.append(parts[1])
        if strong:
            notes.append(f".ws_misses.tsv のうち、今は引ける物が {len(strong)} 件あります: " + " / ".join(strong[:3]))

    # 説明の量
    lines = mcp_doc_lines()
    for name, n in lines.items():
        if n > DOC_LINES_EACH:
            problems.append(f"MCP の {name} の説明が {n} 行です（{DOC_LINES_EACH} 行以内）")
    total = sum(lines.values())
    if total > DOC_LINES_TOTAL:
        problems.append(f"MCP の ws_* の説明が合わせて {total} 行です（{DOC_LINES_TOTAL} 行以内）")
    names_in_docs = doc_shelf_names(cat)
    if len(names_in_docs) > DOC_NAMES_MAX:
        problems.append(f"手順書（{'・'.join(DOC_FILES)}）に棚の名前が {len(names_in_docs)} 種あります（例として出てよいのは {DOC_NAMES_MAX} 個まで）: " + "、".join(sorted(names_in_docs)))

    summary = f"棚 {len(cat.shelves)} 本・問題 {len(allq)} 問・" + ("全部が札の中" if not [p for p in problems if "札の中にありません" in p] else "札の外に出た問題あり") + (f"（机上の入らなかった問 {len([n for n in notes if n.startswith(chr(26426))])} 問を除く）" if [n for n in notes if n.startswith(chr(26426))] else "") + f"・1 位率 {rate:.0f}%"
    if write and not problems:
        Path(answers_path).write_text("# 前回の検査の控え（頼みの文 → 上位の札）。道具が書く。手で直さない\n" + "".join(f"{a}\t{','.join(n)}\n" for a, n in answers.items()), encoding="utf-8")
    return problems, notes, summary, results


def main(write=True):
    problems, notes, summary, _ = run(write=write)
    for p in problems:
        print("[止める] " + p)
    for n in notes:
        print("[注意] " + n)
    print(("[NG] " if problems else "[OK] ") + summary)
    return 1 if problems else 0
