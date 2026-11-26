# -*- coding: utf-8 -*-
"""
gas_ws_find.py - Workspace の棚を「引く」（純 Python・通信なし）

頼みの文（または AI が言い換えた語）から、棚の札（名前・題・引数・例）を上位数本返す。
当てて撃つのは AI。ここは目録を引くだけで、棚を撃たない。
引き方・点数・しきい値は設計書 第 4 章・第 10 章のとおり。しきい値は下の定数（変えるのは問題集の結果を見て番頭が決める）。
"""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import gas_ws_catalog

HERE = Path(__file__).resolve().parent
SYNONYMS_FILE = gas_ws_catalog.SHELF_DIR / "synonyms.txt"
GUIDE_FILE = gas_ws_catalog.SHELF_DIR / "guide.txt"
MISSES_FILE = HERE / ".ws_misses.tsv"
_ASK_RULES_FILE = HERE / "ws_ask_rules.json"


def _build_color_norm_res():
    try:
        rules = json.loads(_ASK_RULES_FILE.read_text(encoding="utf-8"))
        words = [re.escape(pair[0]) for pair in rules.get("colors") or [] if pair and pair[0]]
    except Exception:
        words = ["薄い灰色", "薄い青", "薄い赤", "薄い緑", "薄い黄", "灰色", "グレー", "オレンジ", "ピンク", "紺", "茶", "赤", "青", "緑", "黄", "紫", "黒", "白"]
    alt = "|".join(words) + r"|#[0-9a-f]{6}|#[0-9a-f]{3}"
    return (
        re.compile(rf"(?<![大小])(文字|フォント)(?:を|は|に)?({alt})"),
        re.compile(rf"(背景|塗り)(?:を|は|に)?({alt})"),
        re.compile(rf"(タイトル|見出し)(?:を|は|に)?({alt})"),
        re.compile(rf"({alt})(?:に|で)塗"),
    )


_FG_NOCOLOR_RE, _BG_NOCOLOR_RE, _TITLE_NOCOLOR_RE, _PAINT_COLOR_RE = _build_color_norm_res()

MIN_SCORE = 2          # これ未満の棚は出さない
WEAK_SCORE = 6         # 1 位がこれ未満なら「近い棚は見つかりません」
TOP_N = 5              # 節が 1 つのときの本数
CLAUSE_TOP = 3         # 節が 2 つ以上のときの、節ごと・全体の本数
MAX_N = 8              # 節が 2 つ以上のときの合計の上限
MISSES_MAX = 500
NAME_BONUS = 20
CLAUSE_SPLIT = re.compile(r"[。、，,\n]|それから|ついでに|あと|でも")

HEAD_OK = "棚の候補（{n} 本）。合う物を選んで ws_do で撃つ。合わなければ語を変えて ws_find、棚に無ければ api（Sheets API の batchUpdate）を使う:"
HEAD_WEAK = "近い棚は見つかりません。語を変えて引くか、棚に無ければ api（Sheets API の batchUpdate。札は ws_find の ask=\"棚:api\"）を使う。いちばん近い候補（{n} 本）:"
HEAD_NONE = "近い棚は見つかりません。語を変えて引くか、棚に無ければ api（Sheets API の batchUpdate。札は ws_find の ask=\"棚:api\"）を使う。"

_HIRA = re.compile(r"^[ぁ-ゟ]+$")


# ------------------------------------------------------------------ 下ごしらえ
def load_synonyms(path=SYNONYMS_FILE):
    pairs = []
    p = Path(path)
    if not p.exists():
        return pairs
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        a, b = ln.split("=", 1)
        a, b = _base(a), _base(b)
        if a:
            pairs.append((a, b))
    return pairs


def _base(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).lower())


def norm(s, synonyms):
    """NFKC・小文字・空白除去 → 言い換えの表 → 色表現の統一 → 助詞の「を」を抜く"""
    s = _base(s)
    for a, b in synonyms:
        s = s.replace(a, b)
    s = re.sub(r"(^|[^文])字の色", r"\1文字色", s)
    s = _FG_NOCOLOR_RE.sub(r"\1色\2", s)
    s = _BG_NOCOLOR_RE.sub(r"背景色\2", s)
    s = _PAINT_COLOR_RE.sub(r"背景色\1", s)
    s = _TITLE_NOCOLOR_RE.sub(r"\1文字色\2", s)
    s = re.sub(r"(タイトル|表題|題名)の色", r"\1の文字色", s)
    return s.replace("を", "")


def load_guide(path=GUIDE_FILE):
    items = []
    p = Path(path)
    if not p.exists():
        return items
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=>" not in ln:
            continue
        left, right = ln.split("=>", 1)
        words = [w.strip() for w in left.split("|") if w.strip()]
        if words:
            items.append((words, right.strip()))
    return items


# ------------------------------------------------------------------ 点数
class Finder:
    def __init__(self, catalog=None, synonyms=None, guide=None):
        self.cat = catalog or gas_ws_catalog.load()
        self.syn = load_synonyms() if synonyms is None else synonyms
        self.guide = load_guide() if guide is None else guide
        self._guide_norm = [([nw for nw in (norm(w, self.syn) for w in words) if nw], text) for words, text in self.guide]
        self._index = []
        for order, s in enumerate(self.cat.shelves):
            words = [norm(w, self.syn) for w in s["words"]]
            text = norm(s["title"] + "".join(s["words"]) + "".join(a for a, _ in s["examples"]), self.syn)
            self._index.append((order, s, words, text))

    # ---- 1 つの文を全棚に当てて (点, 目録の順, 棚, 点の内訳) を返す
    def score_all(self, ask, kind=""):
        q = norm(ask, self.syn)
        raw = _base(ask)
        grams = {q[i:i + 2] for i in range(len(q) - 1) if len(q[i:i + 2]) == 2 and not _HIRA.match(q[i:i + 2])}
        out = []
        for order, s, words, text in self._index:
            if not s["searchable"] or (kind and s["kind"] != kind and not s.get("shared") and s["name"] not in gas_ws_catalog.LOCAL_HANDLERS):
                continue
            wp = sum(len(w) for w in words if w and w in q) * 2
            cp = sum(1 for g in grams if g in text)
            bonus = NAME_BONUS if s["name"] in raw else 0
            total = wp + cp + bonus
            if total >= MIN_SCORE:
                out.append((total, order, s, {"語": wp, "字": cp, "名": bonus}))
        out.sort(key=lambda x: (-x[0], x[1]))
        return out

    def clauses(self, ask):
        parts = [p.strip() for p in CLAUSE_SPLIT.split(ask)]
        return [p for p in parts if len(p) >= 2]

    def search(self, ask, kind="", top=25):
        """上位の棚と点数のペア [(棚dict, 点数), ...] を返す"""
        return [(s, t) for t, _, s, _ in self.score_all(ask, kind)[:top]]

    def find(self, ask, kind=""):
        """札を返す。返り値は (棚の dict のリスト, 点の dict, 案内の行のリスト)"""
        ask = (ask or "").strip()
        scores = {}
        picks = []
        overall = self.score_all(ask, kind)
        for t, _, s, _ in overall:
            scores[s["name"]] = t
        cl = self.clauses(ask)
        if len(cl) <= 1:
            chosen = overall[:TOP_N]
            picks = [s for _, _, s, _ in chosen]
        else:
            seen = []
            for _, _, s, _ in overall[:CLAUSE_TOP]:
                if s["name"] not in [x["name"] for x in seen]:
                    seen.append(s)
            for c in cl:
                for t, _, s, _ in self.score_all(c, kind)[:CLAUSE_TOP]:
                    scores.setdefault(s["name"], t)
                    if s["name"] not in [x["name"] for x in seen]:
                        seen.append(s)
            picks = seen[:MAX_N]
        q = norm(ask, self.syn)
        guide = [text for nwords, text in self._guide_norm if any(nw in q for nw in nwords)]
        return picks, scores, guide

    def why(self, ask, kind=""):
        return [(t, s["name"], d) for t, _, s, d in self.score_all(ask, kind)[:MAX_N]]

    # ---- 札の文字
    def card(self, s, with_diff=True):
        mark = " ＊" + s["danger"] if s["danger"] else ""
        lines = [f"{s['name']}{mark}｜{s['title']}｜{s['args_raw']}"]
        if with_diff and s["diff"]:
            lines.append("   違い: " + s["diff"])
        if s["examples"]:
            a, op = s["examples"][0]
            lines.append(f"   例 「{a}」→ " + _json(op))
        return lines

    def render(self, picks, guide, weak=False):
        lines = []
        for g in guide:
            lines.append("案内: " + g)
        if not picks:
            lines.append(HEAD_NONE)
            return "\n".join(lines)
        lines.append((HEAD_WEAK if weak else HEAD_OK).format(n=len(picks)))
        for i, s in enumerate(picks, 1):
            c = self.card(s)
            lines.append(f"{i}. " + c[0])
            lines.extend(c[1:])
        return "\n".join(lines)

    def ask(self, ask, kind="", log_to=None):
        """ws_find の返事（文字）。log_to を渡すと、弱い頼みを .ws_misses.tsv に足す"""
        ask = (ask or "").strip()
        m = re.match(r"^分類\s*[:：]\s*(.+)$", ask)
        if m:
            cat = m.group(1).strip()
            target_kind = "doc" if cat == "文書" else kind
            shelves = [s for s in self.cat.shelves if s["category"] == cat and s["searchable"] and (not target_kind or s["kind"] == target_kind or s.get("shared") or s["name"] in gas_ws_catalog.LOCAL_HANDLERS)]
            if not shelves:
                return f"分類「{cat}」の棚はありません。分類: " + "・".join(gas_ws_catalog.CATEGORIES)
            return self.render(shelves, [])
        m = re.match(r"^棚\s*[:：]\s*(\S+)$", ask)
        if m:
            s = self.cat.by_name.get(m.group(1))
            if not s:
                return f"棚「{m.group(1)}」はありません。" + self.near(m.group(1))
            return "\n".join(["1. " + self.card(s)[0]] + self.card(s)[1:] + ["   引数: " + s["args_raw"]])
        if not ask:
            return self.overview(kind=kind)
        # 文書系の棚・分類を指している場合は kind 未指定でも doc 棚に向ける
        if not kind and (ask.startswith("doc.") or "棚:doc." in ask or "棚：doc." in ask):
            kind = "doc"
        picks, scores, guide = self.find(ask, kind)
        top = max([scores.get(s["name"], 0) for s in picks], default=0)
        weak = top < WEAK_SCORE
        if weak and log_to is not False:
            log_miss(ask, picks[0]["name"] if picks else "", top, log_to)
        return self.render(picks, guide, weak=weak)

    def near(self, name, n=3):
        picks, _, _ = self.find(name)
        picks = picks[:n]
        return ("近い棚:\n" + self.render(picks, [])) if picks else ""

    def overview(self, kind=""):
        counts = {}
        for s in self.cat.shelves:
            if s["searchable"] and (not kind or s["kind"] == kind or s.get("shared") or s["name"] in gas_ws_catalog.LOCAL_HANDLERS):
                counts[s["category"]] = counts.get(s["category"], 0) + 1
        lines = ["棚の分類と本数（ws_find(ask=\"分類:名前\") でその分類の札、ask=\"頼みの文\" で候補）:"]
        lines += [f"  {c}: {counts[c]} 本" for c in gas_ws_catalog.CATEGORIES if c in counts]
        return "\n".join(lines)


def _json(op):
    import json
    return json.dumps(op, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ 弱かった頼みの記録
def log_miss(ask, top_name, top_score, path=None):
    """`日付<TAB>頼みの文<TAB>1 位の棚と点`。同じ文は 1 回。500 行で古い物から捨てる"""
    p = Path(path) if path else MISSES_FILE
    ask1 = re.sub(r"[\t\r\n]+", " ", ask)
    try:
        lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        if any(len(x.split("\t")) >= 2 and x.split("\t")[1] == ask1 for x in lines):
            return False
        lines.append(f"{date.today().isoformat()}\t{ask1}\t{top_name} {top_score}")
        p.write_text("\n".join(lines[-MISSES_MAX:]) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def build_ai_shelf_prompt(finder, ask, kind="sheet", detail_limit=1600, top_args=25, priority_names=None):
    """AI プロンプト向けに、関連棚の詳細＋主要引数一覧＋全棚のカテゴリ別圧縮インデックスを組み立てる。"""
    cat = finder.cat
    lines = ["【よく関連する棚の詳細】"]
    detail = finder.ask(ask, kind, log_to=False)
    if detail:
        lines.append(detail[:detail_limit])

    shelves = [
        s for s in cat.shelves
        if s.get("searchable", True)
        and (not kind or s.get("kind") == kind or s.get("shared") or s["name"] in gas_ws_catalog.LOCAL_HANDLERS)
    ]
    hits = [s["name"] for _sc, _ord, s, _d in finder.score_all(ask, kind)[:top_args]]
    prio = set(priority_names or ())
    full_names = []
    seen = set()
    for nm in hits:
        if nm not in seen:
            seen.add(nm)
            full_names.append(nm)
    for s in shelves:
        if s["name"] in prio and s["name"] not in seen:
            seen.add(s["name"])
            full_names.append(s["name"])

    lines.append("\n【利用可能な棚一覧（主要・関連：棚名 | 説明 | 引数）】")
    by_name = cat.by_name
    for nm in full_names:
        s = by_name.get(nm)
        if s and s in shelves:
            lines.append(f"- {s['name']}: {s.get('title', '')} | {s.get('args_raw', 'なし')}")

    rest = [s for s in shelves if s["name"] not in seen]
    if rest:
        lines.append("\n【その他すべての利用可能な棚（カテゴリ別・全件。使いたい棚があればそのまま名前を指定）】")
        by_cat = {}
        for s in rest:
            by_cat.setdefault(s.get("category") or "その他", []).append(f"{s['name']}({s.get('title', '')})")
        for cat_name, items in by_cat.items():
            lines.append(f"- {cat_name}: " + " / ".join(items))
    return "\n".join(lines)


_default = None


def default():
    global _default
    if _default is None:
        _default = Finder()
    return _default
