# -*- coding: utf-8 -*-
"""
gas_ws_ask.py - 頼みの文 1 つから ops を組む（ws_do の ask。純 Python・通信なし）

ws_find の当て（gas_ws_find.Finder）で節ごとに棚を 1 本に決め、引数を
  ・棚の札の「頼み:」の決め（引数=値<語|語 ／ 引数~正規表現）
  ・型ごとの読み取り（範囲・列・列[]・行[]・シート・色・数・「」の文字）
で埋める。表の見出し（覚えている表の形）を使って列の名前を当てる。
当てが割れる・弱い・引数が決まらない・案内（できない頼み 等）が出る ときは撃たない（fire=False）で、
組みかけの ops・足りない物・候補の札を返す。このファイルには棚の名前を書かない（決めは札に置く）。
"""

import json
import re
import unicodedata
from pathlib import Path

import gas_ws_catalog
import gas_ws_find

_RULES_PATH = Path(__file__).resolve().parent / "ws_ask_rules.json"


def load_ask_rules(path=None):
    """Python・JS 共通の棚当て定義（ws_ask_rules.json）を読み込む。"""
    p = Path(path) if path else _RULES_PATH
    return json.loads(p.read_text(encoding="utf-8"))


_ASK_RULES = load_ask_rules()

MARGIN = int(_ASK_RULES["margin"])                  # 1 位と 2 位の点の差がこれ未満なら「割れた」
EVIDENCE_GAP = int(_ASK_RULES["evidence_gap"])      # 札の正規表現が当たった棚を繰り上げる、1 位との点の差の上限
WHAT_MIN = int(_ASK_RULES["what_min"])              # 「何をするか」の引数（真偽・色・数・文字・選択の任意の物）がこれ以上ある棚で、1 つも決まらなければ撃たない
# 何を指しているか人にしか分からない言い方（撃たずに聞く）
VAGUE = re.compile(_ASK_RULES["vague_re"])
CUR_SHEET = re.compile(_ASK_RULES["cur_sheet_re"])
_LOCATOR_TYPES = ("範囲", "列", "列[]", "行[]", "シート")
SPLIT = re.compile(r"[。、，,\n]|(?<=[ぁ-ん]て)から|それから|ついでに|そのあと|その後")

_A1 = r"[A-Z]{1,3}[0-9]{1,6}"
_SEP = r"\s*(?:[:：]|から|〜|~|－|-|ー)\s*"
RANGE_RE = re.compile(r"(?<![A-Za-z])(" + _A1 + r")" + _SEP + r"(" + _A1 + r")(?:まで)?(?![0-9])")
CELL_RE = re.compile(r"(?<![A-Za-z0-9])(" + _A1 + r")(?![0-9])")
COLROWS_RE = re.compile(r"(?<![A-Za-z])([A-Z]{1,3})列の?\s*([0-9]+)行目?" + _SEP + r"([0-9]+)行目?(?:まで)?")
COLSPAN_RE = re.compile(r"(?<![A-Za-z])([A-Z]{1,3})列?" + r"\s*(?:から|〜|~|－|-)\s*" + r"([A-Z]{1,3})列(?:まで)?")
COL_RE = re.compile(r"(?<![A-Za-z])([A-Z]{1,3})列")
ROWSPAN_RE = re.compile(r"([0-9]+)行目?" + _SEP + r"([0-9]+)行目?(?:まで)?")
ROW_RE = re.compile(r"(?<![0-9])([0-9]+)\s*行目")
QUOTE_RE = re.compile(r"[「『\"“]([^」』\"”]+)[」』\"”]")
NUM_RE = re.compile(r"(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+)?)(?![0-9])")

# 色の言い方 → エンジンの色の名前（rgb_ が読む物）。長い順に当てる（ws_ask_rules.json から共通読込）
_COLORS = [tuple(pair) for pair in _ASK_RULES["colors"]]
_FG_COLOR_KEYS = tuple(_ASK_RULES["fg_color_keys"])
_BG_COLOR_KEYS = tuple(_ASK_RULES["bg_color_keys"])
_FG_AFTER_RE = re.compile(_ASK_RULES["fg_after_re"])
_BG_AFTER_RE = re.compile(_ASK_RULES["bg_after_re"])
_CLAUSE_PROTECT_PATTERNS = tuple(_ASK_RULES["clause_protect_patterns"])
_HEX_COLOR_RE = re.compile(r"(?<![0-9A-Za-z])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z])")
_EN_COLOR_RE = re.compile(
    r"(?<![A-Za-z])(lightred|lightgreen|lightyellow|lightgray|lightblue|orange|purple|yellow|green|black|white|brown|navy|pink|gray|grey|cyan|blue|red)(?![A-Za-z])",
    re.IGNORECASE,
)


_RX = {}


def _rx(pat):
    r = _RX.get(pat)
    if r is None:
        r = _RX[pat] = re.compile(pat)
    return r


class Plan:
    def __init__(self):
        self.ops = []          # 組んだ ops（fire=False でも組めた所まで）
        self.fire = False
        self.reasons = []      # 撃たない理由（人と AI に見せる）
        self.missing = []      # 決まらなかった引数（"棚: 引数(型)"）
        self.cards = []        # 候補の棚の dict（撃たないときに札を見せる）
        self.guide = []

    def to_dict(self):
        return {"ops": self.ops, "fire": self.fire, "reasons": self.reasons, "missing": self.missing,
                "cards": [s["name"] for s in self.cards], "guide": self.guide}


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


PLACE_ONLY = re.compile(_ASK_RULES["place_only_re"])   # 「日付のとこ」のような場所だけの節は、次の節につなげる


def clauses(ask):
    src = nfkc(ask)
    saved = []

    def _prot(pat):
        nonlocal src

        def _repl(m):
            k = f"\ue010{len(saved)}\ue011"
            saved.append(m.group(0))
            return k

        src = re.sub(pat, _repl, src)

    # プルダウン候補や複数セルの「、」区切り、複数キー並べ替え、表作成の見出し列挙を節分割から守る
    for _pat in _CLAUSE_PROTECT_PATTERNS:
        _prot(_pat)
    parts = [re.sub(r"\ue010(\d+)\ue011", lambda m: saved[int(m.group(1))], p).strip() for p in SPLIT.split(src)]
    parts = [p for p in parts if len(p) >= 2]
    out = []
    for p in parts:
        if out and PLACE_ONLY.match(out[-1]):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


# ------------------------------------------------------------------ 型ごとの読み取り
def _rows_of(text):
    out = []
    for a, b in ROWSPAN_RE.findall(text):
        a, b = int(a), int(b)
        if a <= b and b - a < 5000:
            out += list(range(a, b + 1))
    rest = ROWSPAN_RE.sub(" ", text)
    for r in ROW_RE.findall(rest):
        out.append(int(r))
    seen, uniq = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def _col_letters(text):
    out = []
    for a, b in COLSPAN_RE.findall(text):
        from_n, to_n = _col_num(a), _col_num(b)
        if from_n <= to_n and to_n - from_n < 60:
            out += [_col_letter(n) for n in range(from_n, to_n + 1)]
    rest = COLSPAN_RE.sub(" ", text)
    out += COL_RE.findall(rest)
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _col_num(s):
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letter(n):
    s = ""
    while n > 0:
        m = (n - 1) % 26
        s = chr(65 + m) + s
        n = (n - 1) // 26
    return s


def _col_names(text, table):
    """見出しの名前で頼みに出てくる物（出てくる順・長い名前を優先して重なりを除く）"""
    if not table:
        return []
    names = [c["name"] for c in table.get("columns") or [] if str(c.get("name") or "").strip()]
    hits = []
    taken = [False] * len(text)
    for nm in sorted(set(names), key=len, reverse=True):
        key = nfkc(nm).strip()
        start = 0
        while key:
            i = text.find(key, start)
            if i < 0:
                break
            if not any(taken[i:i + len(key)]):
                for k in range(i, i + len(key)):
                    taken[k] = True
                hits.append((i, nm))
                break
            start = i + 1
    return [nm for _, nm in sorted(hits)]


def _range_of(text, table):
    m = COLROWS_RE.search(text)
    if m:
        return f"{m.group(1)}{m.group(2)}:{m.group(1)}{m.group(3)}"
    m = RANGE_RE.search(text)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = CELL_RE.search(text)
    if m:
        return m.group(1)
    return None


def _all_explicit_ranges(text):
    spans = []
    m = COLROWS_RE.search(text)
    if m:
        spans.append((m.start(), m.end(), f"{m.group(1)}{m.group(2)}:{m.group(1)}{m.group(3)}"))
    for m in RANGE_RE.finditer(text):
        spans.append((m.start(), m.end(), f"{m.group(1)}:{m.group(2)}"))
    for m in CELL_RE.finditer(text):
        if not any(st <= m.start() < ed for st, ed, _ in spans):
            spans.append((m.start(), m.end(), m.group(1)))
    spans.sort(key=lambda x: x[0])
    return [v for _, _, v in spans]


def _data_span(table):
    if not table or not table.get("data"):
        return None
    try:
        a, b = [int(x) for x in str(table["data"]).split("-")]
        return a, b
    except Exception:
        return None


def _col_range(table, letters):
    sp = _data_span(table)
    if not sp or not letters:
        return None
    a, b = sp
    if len(letters) == 1:
        return f"{letters[0]}{a}:{letters[0]}{b}"
    return f"{letters[0]}{a}:{letters[-1]}{b}"


def _letter_of(table, name):
    for c in (table or {}).get("columns") or []:
        if c.get("name") == name:
            return c.get("col")
    return None


def _color_hits(text):
    out, taken = [], [False] * len(text)
    for m in _HEX_COLOR_RE.finditer(text):
        for k in range(m.start(), m.end()):
            taken[k] = True
        out.append((m.start(), m.end(), m.group(0).upper()))
    for word, val in _COLORS:
        start = 0
        while True:
            i = text.find(word, start)
            if i < 0:
                break
            if not any(taken[i:i + len(word)]):
                for k in range(i, i + len(word)):
                    taken[k] = True
                out.append((i, i + len(word), val))
            start = i + 1
    for m in _EN_COLOR_RE.finditer(text):
        if not any(taken[m.start():m.end()]):
            for k in range(m.start(), m.end()):
                taken[k] = True
            out.append((m.start(), m.end(), m.group(1).lower()))
    return sorted(out)


def _colors(text):
    return [v for _, _, v in _color_hits(text)]


def _quotes(text):
    return [q.strip() for q in QUOTE_RE.findall(text) if q.strip()]


def _numbers(text):
    t = RANGE_RE.sub(" ", text)
    t = CELL_RE.sub(" ", t)
    t = ROWSPAN_RE.sub(" ", t)
    t = ROW_RE.sub(" ", t)
    t = re.sub(r"[0-9]+列", " ", t)
    out = []
    for n in NUM_RE.findall(t):
        out.append(float(n) if "." in n else int(n))
    return out


def _cast(a, v):
    t = a["type"]
    if t == "配列" and isinstance(v, str):
        return [x.strip() for x in re.split(r"[・、,／/]", v) if x.strip()]
    if t == "数":
        try:
            f = float(str(v).replace(",", ""))
            return int(f) if f.is_integer() else f
        except Exception:
            return None
    if t == "真偽":
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes")
    if t == "範囲" and isinstance(v, str):
        m = RANGE_RE.search(v)
        if m:
            return f"{m.group(1)}:{m.group(2)}"
    if t == "選択":
        s = str(v).lower()
        return s if s in a["choices"] else None
    if t in ("列[]", "行[]", "配列") and not isinstance(v, list):
        if t == "行[]":
            try:
                return [int(v)]
            except Exception:
                return None
        return [v]
    return v


# ------------------------------------------------------------------ 1 節 → 1 op
def build_op(shelf, text, table=None, sheets=None, cur_sheet=""):
    """棚 1 本と節 1 つから op を組む。返り値 (op, 足りない引数の名前のリスト, 頼みに名指しの場所があったか)"""
    args = {a["name"]: a for a in shelf["args"]}
    op = {"shelf": shelf["name"]}
    quotes = _quotes(text)
    for r in shelf.get("ask_rules") or []:
        a = args[r["arg"]]
        if r["arg"] in op and r["arg"] != "cells":
            continue
        if "re" in r:
            rx = _rx(r["re"])
            if r["arg"] == "cells" and a["type"] == "対応" and rx.groups >= 2:
                for gm in rx.finditer(text):
                    val = gm.group(2).strip()
                    op.setdefault("cells", {})[gm.group(1).strip()] = int(val) if re.fullmatch(r"-?[0-9]+", val) else val
                    for g in gm.groups():
                        if g and g.strip() in quotes:
                            quotes.remove(g.strip())
                continue
            m = rx.search(text)
            if m:
                if a["type"] == "対応" and rx.groups >= 2:
                    val = m.group(2).strip()
                    v = {m.group(1).strip(): (int(val) if re.fullmatch(r"-?[0-9]+", val) else val)}
                else:
                    v = _cast(a, m.group(1).strip())
                if v not in (None, "", []):
                    op[r["arg"]] = v
                    for g in m.groups():
                        if g and g.strip() in quotes:
                            quotes.remove(g.strip())
        elif any(w in text for w in r["words"]):
            v = r["value"]
            op[r["arg"]] = v if a["type"] in ("対応", "配列", "表") else _cast(a, v)
    scan = QUOTE_RE.sub(" ", text)          # 「」の中（タイトル・入れる文字など）は、列・範囲・行・色として読まない
    scan = re.sub(r"[（(][^）)]*[）)]", " ", scan)  # （）の中（計算式や補足説明など）も列・範囲として読まない
    color_hits = _color_hits(scan)
    scan = _HEX_COLOR_RE.sub(" ", scan)     # #FF6600 等をセル番地や数値として誤読しない
    sheet_hits = [s for s in sorted((sheets or []), key=lambda x: len(str(x)), reverse=True) if s and nfkc(s) in nfkc(scan)]
    for sh_nm in sheet_hits:
        scan = scan.replace(sh_nm, " ")
        scan = nfkc(scan).replace(nfkc(sh_nm), " ")
    names = _col_names(scan, table)
    letters = _col_letters(scan)
    explicit_ranges = _all_explicit_ranges(scan)
    explicit_range = explicit_ranges[0] if explicit_ranges else None
    rem_ranges = list(explicit_ranges)
    has_from_to_ranges = args.get("from", {}).get("type") == "範囲" and args.get("to", {}).get("type") == "範囲"
    rows = _rows_of(scan)
    nums = _numbers(scan)
    named = bool(explicit_range or rows or letters or names or sheet_hits or shelf["name"] in ("dedupe", "seiri"))
    need = [a["name"] for a in shelf["args"] if a["req"]] + [k for k in shelf["any"]]
    col_pool = list(names) + [x for x in letters if x not in [_letter_of(table, n) for n in names]]
    range_given = False
    # 色: 引数が 1 つならそれ。2 つ以上なら 背景／文字 の文脈で振り分け（複数色対応）
    all_color_args = [a["name"] for a in shelf["args"] if a["type"] == "色"]
    color_args = [k for k in all_color_args if k not in op]
    if color_hits and color_args:
        if len(all_color_args) == 1:
            op[color_args[0]] = color_hits[0][2]
        else:
            prev_end = 0
            for pos, end, val in color_hits:
                ctx = scan[prev_end:pos]
                after = scan[end:end + 4]
                prev_end = end
                fg_i = max((ctx.rfind(k) for k in _FG_COLOR_KEYS), default=-1)
                bg_i = max((ctx.rfind(k) for k in _BG_COLOR_KEYS), default=-1)
                if _FG_AFTER_RE.match(after):
                    target_k = "color"
                elif _BG_AFTER_RE.match(after):
                    target_k = "bg"
                elif fg_i > bg_i:
                    target_k = "color"
                elif bg_i > fg_i:
                    target_k = "bg"
                elif len(color_hits) == 1:
                    if any(k in text for k in _FG_COLOR_KEYS) and "背景" not in text:
                        target_k = "color"
                    else:
                        target_k = "bg"
                else:
                    target_k = "bg" if "bg" in color_args and "bg" not in op else "color"
                if target_k in color_args and target_k not in op:
                    op[target_k] = val
                elif len(color_hits) == 1 and color_args and color_args[0] not in op and len(all_color_args) == len(color_args):
                    op[color_args[0]] = val
    has_col_arg = any(a["type"] == "列" for a in shelf["args"])
    req_text_filled = False
    for a in shelf["args"]:
        k, t = a["name"], a["type"]
        if k in op:
            if t == "範囲":
                range_given = True
            continue
        wanted = k in need
        v = None
        if t == "範囲":
            if has_from_to_ranges and k in ("from", "to") and rem_ranges:
                v = rem_ranges.pop(0)
            elif range_given or (not wanted and any(op.get(x) not in (None, "", []) for x in shelf["any"])):
                pass
            elif explicit_range:
                v = explicit_range
            elif wanted and shelf["name"] in ("clear.all", "cf.dup") and table:
                first_r = table["data"].split("-")[0] if table.get("data") else str(table.get("header_row", 1) + 1)
                last_r = table["data"].split("-")[-1] if table.get("data") else str(table.get("header_row", 1) + 1)
                v = f"{table['first_col']}{first_r}:{table['last_col']}{last_r}"
            elif col_pool and (wanted or not has_col_arg):
                ls = [x for x in ((_letter_of(table, c) or (c if re.fullmatch(r"[A-Z]{1,3}", c) else None)) for c in col_pool) if x]
                v = _col_range(table, ls)
            if v:
                range_given = True
        elif t == "列":
            if col_pool and not (k in shelf["any"] and any(op.get(x) not in (None, "", []) for x in shelf["any"])):
                v = col_pool.pop(0)
        elif t == "列[]":
            if col_pool:
                v, col_pool = list(col_pool), []
        elif t == "行[]":
            if rows:
                v = rows
        elif t == "配列":
            if quotes and (wanted or not op.get(k)):
                v = list(quotes)
                quotes.clear()
        elif t == "シート":
            if sheet_hits:
                v = sheet_hits.pop(0)
            elif wanted and cur_sheet and CUR_SHEET.search(text):
                v = cur_sheet
            elif wanted and quotes:
                v = quotes.pop(0)
        elif t == "文字":
            if quotes and (wanted or req_text_filled):
                v = quotes.pop(0)
                req_text_filled = req_text_filled or wanted
        elif t == "数":
            if wanted and len(nums) == 1:
                v = nums[0]
        if v not in (None, "", []):
            op[k] = v
    if sheet_hits and shelf.get("kind") == "sheet" and not shelf.get("shared") and "sheet" not in op:
        op["sheet"] = sheet_hits[0]
    if shelf["name"] == "format" and "borders" in op and not any(k in op for k in ("range", "col", "header", "title")) and table and table.get("first_col") and table.get("last_col"):
        fmt_first_r = table.get("header_row") or 1
        fmt_last_r = table.get("total_row") or (str(table["data"]).split("-")[-1] if table.get("data") else fmt_first_r)
        op["range"] = f"{table['first_col']}{fmt_first_r}:{table['last_col']}{fmt_last_r}"
    if shelf["name"] == "format":
        if "col" in op and col_pool and "range" not in op and table:
            first_l = _letter_of(table, op["col"]) or (op["col"] if re.fullmatch(r"[A-Z]{1,3}", str(op["col"])) else "")
            seq_ls = [first_l] if first_l else []
            for cp in col_pool:
                fl = _letter_of(table, cp) or (cp if re.fullmatch(r"[A-Z]{1,3}", str(cp)) else "")
                if fl:
                    seq_ls.append(fl)
            if len(seq_ls) >= 2:
                nums_ls = sorted(_col_num(x) for x in seq_ls)
                if all(nums_ls[i] - nums_ls[i - 1] <= 1 for i in range(1, len(nums_ls))):
                    span_rg = _col_range(table, [_col_letter(nums_ls[0]), _col_letter(nums_ls[-1])])
                    if span_rg:
                        op["range"] = span_rg
                        op.pop("col", None)
        if re.search(r"数値\s*[（(]?標準[）)]?|表示形式を標準|標準形式|標準に戻", text):
            op["number_format"] = "General"
        elif re.search(r"(?:hh:mm|09:00|時刻.{0,4}2桁|2桁.{0,4}時刻|時分形式)", text, re.IGNORECASE):
            op["number_format"] = "hh:mm"
        elif re.search(r"(?:yyyy/mm/dd|2026/11/04|スラッシュ.{0,4}日付|年/月/日)", text, re.IGNORECASE):
            op["number_format"] = "yyyy/mm/dd"
        elif op.get("number_format") == 'm"月"d"日"(ddd)' and re.search(r"年|yyyy", text, re.IGNORECASE):
            op["number_format"] = "yyyy/mm/dd(ddd)"
        elif not op.get("number_format") and re.search(r"パーセント|%\s*表示", text):
            op["number_format"] = "0.0%"
        elif not op.get("number_format") and re.search(r"3桁|桁区切|カンマ", text):
            op["number_format"] = "#,##0"
    if shelf["name"] == "cf.add" and op.get("when") != "formula":
        m_jpnum = re.fullmatch(r"([0-9][0-9,\.]*)(万|億)", str(op.get("value") or "").strip())
        if m_jpnum:
            mul = 10000 if m_jpnum.group(2) == "万" else 100000000
            v_f = float(m_jpnum.group(1).replace(",", "")) * mul
            op["value"] = str(int(v_f)) if v_f.is_integer() else str(v_f)
    if shelf["name"] == "cf.add" and op.get("when") != "formula" and table and table.get("first_col") and table.get("last_col"):
        if re.search(r"行全体|の行(?:に|を|全部|だけ)|行に色|行を目立|行を(?:赤|黄|青|緑|黒|白)", text):
            sp_cf = _data_span(table)
            cf_r1 = sp_cf[0] if sp_cf else ((table.get("header_row") or 1) + 1)
            cf_r2 = sp_cf[1] if sp_cf else cf_r1
            ref_l = (_letter_of(table, names[0]) if names else None) or (letters[0] if letters else "")
            expr = ""
            num_val = str(op["value"]).replace(",", "") if op.get("value") is not None else ""
            if ref_l:
                w = op.get("when")
                if w == "ge" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}>={num_val}"
                elif w == "le" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}<={num_val}"
                elif w == "gt" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}>{num_val}"
                elif w == "lt" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}<{num_val}"
                elif re.search(r"マイナス|負の値", text):
                    expr = f"=${ref_l}{cf_r1}<0"
                elif re.search(r"([0-9]+)\s*%?(?:になってない|ではない)", text):
                    m_not = re.search(r"([0-9]+)\s*%?(?:になってない|ではない)", text)
                    expr = f"=${ref_l}{cf_r1}<>{m_not.group(1)}"
                elif op.get("value") not in (None, ""):
                    escaped_v = str(op["value"]).replace('"', '""')
                    expr = f'=ISNUMBER(SEARCH("{escaped_v}",${ref_l}{cf_r1}))'
            elif re.search(r"欠席|完了|未完了|終了", text):
                kw_cf = "欠席" if "欠席" in text else ("未完了" if "未完了" in text else ("完了" if "完了" in text else "終了"))
                expr = f'=COUNTIF(${table["first_col"]}{cf_r1}:${table["last_col"]}{cf_r1},"*{kw_cf}*")>0'
            if expr:
                op["range"] = f"{table['first_col']}{cf_r1}:{table['last_col']}{cf_r2}"
                op["when"] = "formula"
                op["value"] = expr
                named = True
        if not op.get("bg") and not op.get("color") and re.search(r"色[を]?付|色[を]?つ|目立", text):
            op["bg"] = "薄黄"
    if shelf["name"] == "renumber" and "col" not in op and table:
        for col_info in table.get("columns") or []:
            c_nm = str((col_info or {}).get("name") or "")
            if re.fullmatch(r"no|番号|連番|項番|id", c_nm.strip(), re.IGNORECASE):
                op["col"] = c_nm
                named = True
                break
    if shelf["name"] == "sheet.rename" and "name" not in op and "to" in op and cur_sheet:
        op["name"] = cur_sheet
    if shelf["name"] == "table.new":
        if not re.search(r"合計|総計|小計", text):
            op.pop("total", None)
        if not re.search(r"連番|通し番号", text):
            op.pop("number", None)
        if not op.get("headers"):
            hdr_src = re.sub(r"^.*?(?:シート|タブ)[にへで]\s*", "", text.strip())
            hdr_src = re.sub(r"^.*?(?:見出し|項目|列)[がはを]\s*", "", hdr_src)
            m_hdr = re.search(
                r"([^\s、,。・をに]{1,16}(?:\s*(?:[・、,]|と)\s*[^\s、,。・をに]{1,16})+)の(?:表|テーブル|名簿|一覧表)",
                hdr_src,
            )
            if m_hdr:
                op["headers"] = [h.strip() for h in re.split(r"[・、,／/]|と", m_hdr.group(1)) if h.strip()]
        if isinstance(op.get("headers"), list) and any("と" in str(x) for x in op["headers"]):
            op["headers"] = [h.strip() for x in op["headers"] for h in str(x).split("と") if h.strip()]
    if shelf["name"] == "replace":
        if "find" in op and isinstance(op["find"], str):
            clean_find = re.sub(r"^(?:全シート|すべてのシート|全てのシート|ブック全体)で\s*", "", op["find"]).strip()
            if clean_find != op["find"]:
                op["all_sheets"] = True
                op["find"] = clean_find
        if re.search(r"全シート|すべてのシート|全てのシート|ブック全体", text):
            op["all_sheets"] = True
    if shelf["name"] == "sort":
        sort_pairs = []
        nfkc_t = nfkc(text)
        cols_meta = (table or {}).get("columns", [])
        # 「部署ごと、同部署内は社員番号の昇順」「部署ごとにかためて…社員番号の若い順」の 1 列目（ごと）を拾う
        m_grp = re.search(r"([^\s、,の]{1,16})ごと(?:[、,]|に?かためて並べ)", nfkc_t)
        if m_grp:
            raw_g = m_grp.group(1).strip()
            col_g = next((c["name"] for c in cols_meta if c["name"] == raw_g), raw_g)
            sort_pairs.append(col_g)
        for sm in re.finditer(
            r"(?:その中で\s*|同じ[^\s、,。]{1,12}の中は\s*|同[^\s、,。]{1,12}内は\s*)?([^\s、,のは]{1,16})の(?:(大きい順|多い順|高い順|降順|新しい順|逆順|遅い順)|(小さい順|少ない順|低い順|昇順|古い順|五十音順|あいうえお順|若い順))",
            nfkc_t,
        ):
            raw_c = sm.group(1).strip()
            col_c = next((c["name"] for c in cols_meta if c["name"] == raw_c), raw_c)
            is_desc = bool(sm.group(2))
            spec = ("-" if is_desc else "") + col_c
            if spec not in sort_pairs and col_c not in sort_pairs:
                sort_pairs.append(spec)
        if len(sort_pairs) >= 2:
            op["cols"] = sort_pairs
            op.pop("col", None)
            op.pop("desc", None)
            named = True
    if shelf["name"] == "sheet.diff":
        op.pop("sheet", None)
        if sheet_hits and (op.get("from") == op.get("to") or "from" not in op or "to" not in op):
            ordered_sh = sorted(set(sheet_hits), key=lambda x: nfkc(text).find(nfkc(x)))
            if len(ordered_sh) >= 2:
                op["from"] = ordered_sh[0]
                op["to"] = ordered_sh[1]
    if shelf["name"] == "top.n":
        if op.get("into") == "別":
            op.pop("into", None)
        if "col" not in op and table and table.get("columns"):
            num_cols = [c["name"] for c in table["columns"] if c.get("number") and not re.fullmatch(r"no\.?|番号|id", c["name"].strip(), re.IGNORECASE)]
            if num_cols:
                op["col"] = num_cols[0]
                named = True
    if shelf["name"] in ("filter.where", "filter.delete", "filter.extract"):
        if shelf["name"] == "filter.extract" and op.get("into") == "別":
            op.pop("into", None)
        if "when" in op and "equals" in op and isinstance(op["equals"], str):
            if re.search(r"以上|以下|未満|より|超|を含|含む|以外|ではな|でない|空白|空欄", op["equals"]):
                op.pop("equals", None)
        if shelf["name"] == "filter.where":
            m_name = re.search(r"^(.+?)(?:さん|様)?の行だけ", text.strip())
            if m_name:
                op["equals"] = m_name.group(1).strip()
            elif "equals" in op and isinstance(op["equals"], str):
                op["equals"] = re.sub(r"(?:さん|様)$", "", op["equals"]).strip()
        if "col" not in op and table:
            cols = [c["name"] for c in table.get("columns", [])]
            eq = op.get("equals", "")
            if any(k in cols for k in ("勘定科目", "科目")) and (any(x in eq for x in ("費", "料", "税", "手当")) or "旅費" in eq):
                op["col"] = "勘定科目" if "勘定科目" in cols else "科目"
            elif any(k in cols for k in ("氏名", "名前", "社員名", "担当")) and (" " in eq or "　" in eq or any(x in text for x in ("さん", "様", "氏"))):
                op["col"] = next(k for k in ("氏名", "名前", "社員名", "担当") if k in cols)
            elif cols:
                text_cols = [c["name"] for c in table.get("columns", []) if not c.get("number")]
                if text_cols:
                    op["col"] = text_cols[0]
        if shelf["name"] == "filter.delete" and op.get("col") and (op.get("when") or op.get("equals") is not None or op.get("value") is not None):
            named = True
    if shelf["name"] == "width" and "col" in op and "width" not in op and "auto" not in op and re.search(r"(?:自動|中身に合|オートフィット)", text):
        op["auto"] = [op.pop("col")]
    missing = [k for k in (a["name"] for a in shelf["args"] if a["req"]) if op.get(k) in (None, "", [])]
    if shelf["any"] and not any(op.get(k) not in (None, "", []) for k in shelf["any"]):
        missing.append("・".join(shelf["any"]) + " のどれか")
    what = [a["name"] for a in shelf["args"] if not a["req"] and a["type"] not in _LOCATOR_TYPES and a["name"] not in shelf["any"]]
    bare_ok = any(not any(k in ex for k in what) for _, ex in shelf["examples"])   # 札の例に「何をするか」なしで撃つ例があれば、なしでも撃てる棚
    if not missing and not bare_ok and len(what) >= WHAT_MIN and not any(k in op for k in what) and not any(a["req"] and a["type"] not in _LOCATOR_TYPES for a in shelf["args"]):
        missing.append("何をするか（" + "・".join(what[:6]) + " …）")
    if shelf["danger"] and named and not VAGUE.search(nfkc(text)) and not missing:
        op["ok"] = True
    return op, missing, named


_HERE_ROW_RE = re.compile(r"(?:この|選択(?:中の?)?|今の)行")
_HERE_COL_RE = re.compile(r"(?:この|選択(?:中の?)?|今の)列")
_HERE_RANGE_RE = re.compile(
    r"(?:ここ|このセル|この範囲|選択範囲|選択セル|選択中(?:のセル|の範囲|の場所|の箇所)?|今選んで(?:いる|る)(?:セル|範囲|ところ|箇所)?)"
)


def parse_selection_scope(selection):
    """ブラウザの名前ボックスの値（例: B3, B3:D10, C:C, 3:5）から last_scope 辞書を組み立てる。"""
    sel = nfkc(selection or "").strip().upper()
    if not sel:
        return {}
    if "!" in sel:
        sel = sel.rsplit("!", 1)[-1].strip()
    m_cell = re.fullmatch(r"([A-Z]{1,3})([0-9]{1,7})", sel)
    if m_cell:
        col_s, row_n = m_cell.group(1), int(m_cell.group(2))
        return {
            "selection": sel,
            "cell": sel,
            "range": sel,
            "col": col_s,
            "cols": [col_s],
            "rows": [row_n],
            "from_browser": True,
        }
    m_rng = re.fullmatch(r"([A-Z]{1,3})([0-9]{1,7}):([A-Z]{1,3})([0-9]{1,7})", sel)
    if m_rng:
        c1, r1, c2, r2 = m_rng.group(1), int(m_rng.group(2)), m_rng.group(3), int(m_rng.group(4))
        n1, n2 = sorted((_col_num(c1), _col_num(c2)))
        r_lo, r_hi = sorted((r1, r2))
        cols = [_col_letter(n) for n in range(n1, n2 + 1)] if n2 - n1 < 60 else [c1]
        out = {"selection": sel, "range": f"{_col_letter(n1)}{r_lo}:{_col_letter(n2)}{r_hi}", "cols": cols, "from_browser": True}
        if len(cols) == 1:
            out["col"] = cols[0]
            if r_lo == r_hi:
                out["cell"] = f"{cols[0]}{r_lo}"
        if r_hi - r_lo < 500:
            out["rows"] = list(range(r_lo, r_hi + 1))
        return out
    m_col = re.fullmatch(r"([A-Z]{1,3}):([A-Z]{1,3})", sel)
    if m_col:
        n1, n2 = sorted((_col_num(m_col.group(1)), _col_num(m_col.group(2))))
        cols = [_col_letter(n) for n in range(n1, n2 + 1)] if n2 - n1 < 60 else [m_col.group(1)]
        out = {"selection": sel, "range": f"{_col_letter(n1)}:{_col_letter(n2)}", "cols": cols, "col_select": True, "from_browser": True}
        if len(cols) == 1:
            out["col"] = cols[0]
        return out
    m_row = re.fullmatch(r"([0-9]{1,7}):([0-9]{1,7})", sel)
    if m_row:
        r1, r2 = sorted((int(m_row.group(1)), int(m_row.group(2))))
        rows = list(range(r1, r2 + 1)) if r2 - r1 < 5000 else [r1]
        return {"selection": sel, "range": f"{r1}:{r2}", "rows": rows, "row_select": True, "from_browser": True}
    return {}


def _expand_selection_pronouns(text, source_scope):
    """文中の「ここ」「選択範囲」「この行」「この列」等をブラウザ選択中の番地表現に置き換える。"""
    if not isinstance(source_scope, dict) or not source_scope:
        return text
    out = text
    rows = source_scope.get("rows")
    if rows and _HERE_ROW_RE.search(out):
        row_expr = f"{rows[0]}行目" if len(rows) == 1 else f"{rows[0]}行目から{rows[-1]}行目"
        out = _HERE_ROW_RE.sub(row_expr, out)
    cols = source_scope.get("cols") or ([source_scope["col"]] if source_scope.get("col") else [])
    if cols and _HERE_COL_RE.search(out):
        col_expr = f"{cols[0]}列" if len(cols) == 1 else f"{cols[0]}列から{cols[-1]}列"
        out = _HERE_COL_RE.sub(col_expr, out)
    rng = source_scope.get("cell") or source_scope.get("range")
    if rng and _HERE_RANGE_RE.search(out):
        if source_scope.get("cell") and re.search(
            r"(?:ここ|このセル|選択セル|選択中のセル)に\s*([『「\"“]?[^』」\"”\s]+[』」\"”]?)\s*を(?:入れ|書|入力)(?:き込|て|して)?",
            out,
        ):
            out = re.sub(
                r"(?:ここ|このセル|選択セル|選択中のセル)に\s*([『「\"“]?[^』」\"”\s]+[』」\"”]?)\s*を(?:入れ|書|入力)(?:き込|て|して)?",
                rf"{source_scope['cell']}の値を\1に打ち直して",
                out,
                count=1,
            )
        elif source_scope.get("cell") and re.search(
            r"(?:ここ|このセル|選択セル|選択中のセル)(?:の[^\sを]{0,8})?を\s*([『「\"“]?[^』」\"”\s]+[』」\"”]?)\s*に(?:書き換|打ち直|変え|直)",
            out,
        ):
            out = re.sub(
                r"(?:ここ|このセル|選択セル|選択中のセル)(?:の[^\sを]{0,8})?を\s*([『「\"“]?[^』」\"”\s]+[』」\"”]?)\s*に(?:書き換|打ち直|変え|直)",
                rf"{source_scope['cell']}の値を\1に打ち直",
                out,
                count=1,
            )
        else:
            out = _HERE_RANGE_RE.sub(rng, out)
    return out


def _apply_scope_fallback(op, missing, source_scope, shelf=None, clause=""):
    """未指定のスコープ（header/title/range/col/cols/rows/cells）を前の節または選択スコープから補う。"""
    if not isinstance(source_scope, dict) or not source_scope:
        return missing, False
    loc_keys = ("header", "title", "range", "col", "cols", "rows", "cells", "at", "from")
    if any(k in op and op[k] not in (None, "", []) for k in loc_keys):
        return missing, False

    # 従来の format 棚向けスコープ引き継ぎ
    if shelf is None or not source_scope.get("from_browser"):
        for scope_k in ("header", "title", "range", "col"):
            if scope_k in source_scope and source_scope[scope_k] not in (None, "", []):
                op[scope_k] = source_scope[scope_k]
                missing = [m for m in missing if not any(x in m for x in ("range", "col", "header", "title"))]
                return missing, True
        return missing, False

    # ブラウザ選択連動時の棚別スコープ補完
    arg_names = {a["name"] for a in shelf.get("args") or []}
    sh_name = shelf.get("name", "")
    # 危険な行/列削除へのブラウザ選択自動補完は厳格化（行選択・列選択または指示代名詞のみ許可、条件文脈なら絶対補完しない）
    if sh_name in ("rows.delete", "cols.delete", "filter.delete"):
        if sh_name == "filter.delete":
            return missing, False
        if re.search(r"(?:が|は|の).{0,16}(?:行|データ)|以上|以下|未満|超え?|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行", clause):
            return missing, False
        if sh_name == "rows.delete" and not source_scope.get("row_select") and not _HERE_ROW_RE.search(clause):
            return missing, False
        if sh_name == "cols.delete" and not source_scope.get("col_select") and not _HERE_COL_RE.search(clause):
            return missing, False
    # write 棚で単一セル選択中に値だけが指定された場合
    if sh_name == "write" and source_scope.get("cell") and not op.get("cells") and not op.get("tsv"):
        qs = _quotes(clause)
        ns = _numbers(clause)
        val = qs[0] if qs else (ns[0] if len(ns) == 1 else None)
        if val is not None:
            op["cells"] = {source_scope["cell"]: val}
            missing = [m for m in missing if "cells" not in m and "tsv" not in m]
            return missing, True

    # 場所引数が必須でない全体系棚（tidy / filter.on / banding.* 等）は、単一セル選択時は全体動作を優先する
    is_multi_range = ":" in str(source_scope.get("range") or "")
    has_pronoun = bool(_HERE_RANGE_RE.search(clause) or _HERE_COL_RE.search(clause) or _HERE_ROW_RE.search(clause))
    if not missing and not has_pronoun and sh_name not in ("format", "clear.values"):
        if not is_multi_range:
            return missing, False

    # 行選択優先、列選択優先、一般範囲の順で棚の受け取れる引数に当てはめる
    candidates = []
    if source_scope.get("row_select"):
        candidates = [("rows", "rows"), ("range", "range")]
    elif source_scope.get("col_select"):
        candidates = [("cols", "cols"), ("auto", "cols"), ("col", "col"), ("range", "range")]
    else:
        candidates = [
            ("header", "header"),
            ("title", "title"),
            ("range", "range"),
            ("col", "col"),
            ("cols", "cols"),
            ("auto", "cols"),
            ("rows", "rows"),
        ]

    for arg_k, src_k in candidates:
        if arg_k in arg_names and source_scope.get(src_k) not in (None, "", []):
            op[arg_k] = source_scope[src_k]
            missing = [
                m for m in missing
                if not any(x in m for x in ("range", "col", "cols", "rows", "header", "title", "auto"))
            ]
            return missing, True
    return missing, False


# ------------------------------------------------------------------ 頼み → ops
def plan(ask, finder, kind="", table=None, sheets=None, cur_sheet="", last_scope=None):
    cur_sheet = cur_sheet or (sheets[0] if sheets else "")
    p = Plan()
    ask = (ask or "").strip()
    if not ask:
        p.reasons.append("頼みの文が空です")
        return p
    q_all = gas_ws_find.norm(ask, finder.syn)
    p.guide = [text for nwords, text in finder._guide_norm if any(nw in q_all for nw in nwords)]
    cl = clauses(ask) or [nfkc(ask)]
    fatal_err = False
    if VAGUE.search(nfkc(ask)):
        p.reasons.append("どこを指すかが人にしか分かりません（" + VAGUE.search(nfkc(ask)).group(0) + "）")
        fatal_err = True
    # 直前の節が棚に当たったが引数不足（missing）のとき、続く補足文（「赤にしてください」等）を合流させるための状態
    last_incomplete = None
    for c_raw in cl:
        c = _expand_selection_pronouns(c_raw, last_scope)
        scored = finder.score_all(c, kind)
        # 前の節が不足ありで、この節単体では別の棚に強く当たらない場合は前の文と合流して補完を試みる
        if last_incomplete is not None and (
            not scored
            or scored[0][0] < gas_ws_find.WEAK_SCORE
            or scored[0][2]["name"] == last_incomplete["top"]["name"]
        ):
            prev_c = last_incomplete["clause"]
            prev_top = last_incomplete["top"]
            merged = prev_c + " " + c
            m_op, m_missing, m_named = build_op(prev_top, merged, table, sheets, cur_sheet)
            if isinstance(last_scope, dict) and (prev_top["name"] == "format" or last_scope.get("from_browser")) and (
                any(k not in ("shelf", "sheet") for k in m_op) or m_missing
            ):
                m_missing, added = _apply_scope_fallback(m_op, m_missing, last_scope, shelf=prev_top, clause=merged)
                m_named = m_named or added
                if prev_top["danger"] and m_named and not VAGUE.search(nfkc(merged)) and not m_missing:
                    m_op["ok"] = True
            if len(m_missing) < last_incomplete["missing_n"] or (len(m_op) > len(p.ops[-1]) and len(m_missing) <= last_incomplete["missing_n"]):
                p.ops[-1] = m_op
                # 直前節が積んだ missing を取り除き、残った不足分だけ置き換える
                del p.missing[last_incomplete["miss_start"]:]
                if m_missing:
                    p.missing += [f"{prev_top['name']}: " + m for m in m_missing]
                    last_incomplete["clause"] = merged
                    last_incomplete["missing_n"] = len(m_missing)
                else:
                    if last_incomplete["card_added"] and p.cards:
                        p.cards.pop()
                    last_incomplete = None
                continue
        if not scored:
            p.reasons.append(f"「{c}」に当たる棚がありません")
            fatal_err = True
            last_incomplete = None
            continue
        # 競合する新・既存棚の文脈調停
        boost_name = ""
        if len(scored) >= 2:
            top_base = scored[0][0]
            cand_names = {x[2]["name"] for x in scored}
            has_fmt_cue = bool(re.search(r"表示形式|曜日|hh:mm|yyyy|mm/dd|時刻.{0,4}2桁|09:00|カンマ|桁区切|パーセント|通貨形式|数値\s*[（(]?標準|標準形式|標準に戻", c, re.IGNORECASE))
            has_row_cf_cue = bool(
                re.search(r"行全体|の行|行を|行に", c)
                and re.search(r"以上|以下|未満|より大きい|より小さい|を超え|マイナス|負の値|になってない|ではない|以外|空欄|空白|欠席|完了", c)
                and _color_hits(c)
            )
            has_row_del_cond = bool(
                re.search(r"の行|行を|行に|行は|データ", c)
                and re.search(r"以上|以下|未満|より大きい|より小さい|を超え|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行", c)
                and re.search(r"消|削除", c)
            )
            if has_fmt_cue and "format" in cand_names and "date.fix" in cand_names and scored[0][2]["name"] in ("format", "date.fix"):
                boost_name = "format"
            elif has_row_cf_cue and "cf.add" in cand_names:
                boost_name = "cf.add"
            elif has_row_del_cond and "filter.delete" in cand_names:
                boost_name = "filter.delete"
            elif "link.clear" in cand_names and re.search(r"(?:リンク|ハイパーリンク).*(?:外|解除|消|削除|クリア)", c):
                boost_name = "link.clear"
            elif "link.extract" in cand_names and re.search(r"(?:URL|リンク先).*(?:抽出|取り出)|埋め込みリンク", c, re.IGNORECASE):
                boost_name = "link.extract"
            elif "top.n" in cand_names and re.search(r"(?:上位|下位|トップ|ワースト|ベスト)\s*[0-9]*", c):
                boost_name = "top.n"
            elif "filter.extract" in cand_names and "抽出" in c and not re.search(r"上位|下位|トップ|ワースト|ベスト|URL|リンク", c, re.IGNORECASE):
                boost_name = "filter.extract"
            elif "merge.unmerge" in cand_names and re.search(r"結合.*(?:埋め|バラ|ばら|分解|ほど|穴埋)|(?:埋め|穴埋).*結合", c):
                boost_name = "merge.unmerge"
            elif "fill.blank" in cand_names and re.search(r"穴埋め|(?:空白|空欄|ブランク).*上の値", c):
                boost_name = "fill.blank"
            elif "transpose" in cand_names and re.search(r"転置|縦横を入れ替|行列を入れ替|行と列を入れ替|縦と横を逆|横向きを縦向き|縦向きを横向き", c):
                boost_name = "transpose"
            elif "number.fix" in cand_names and re.search(r"(?:文字|テキスト).{0,6}数字|数値に変換|本物の数値|文字.{0,4}数値に直", c):
                boost_name = "number.fix"
            elif "sheet.diff" in cand_names and re.search(r"シート.*(?:比較|差分|違い)|(?:比較|差分|違い).*シート|2つのシート", c):
                boost_name = "sheet.diff"
            elif "sheet.list" in cand_names and re.search(r"教え|確認|見せて|あるか|どんなシート|何枚", c) and not re.search(r"目次|インデックス|作", c):
                boost_name = "sheet.list"
            elif "sheet.toc" in cand_names and re.search(r"目次|インデックスシート|シート一覧", c) and not re.search(r"教え|確認|見せて|あるか|どんな", c):
                boost_name = "sheet.toc"
            elif "sheet.sort" in cand_names and re.search(r"(?:シート|タブ).*(?:名前順|昇順|降順|並べ替)", c):
                boost_name = "sheet.sort"
            elif "sheet.gridlines" in cand_names and re.search(r"グリッド線|目盛り線|シート.*枠線|全シート.*枠線|枠線を非表示|枠線を表示", c) and not re.search(r"印刷|PDF|A4|A3|余白|ページ", c, re.IGNORECASE) and not CELL_RE.search(c):
                boost_name = "sheet.gridlines"
            elif "sheet.snapshot" in cand_names and re.search(r"スナップショット|日付[つ付入].*(?:複製|控え|コピー|保存)|控えを複製|今日の控え", c):
                boost_name = "sheet.snapshot"
            elif re.search(r"書式|見た目", c) and not re.search(r"消|クリア|削除|外|解除", c) and scored[0][2]["name"] in ("copy", "copy.format"):
                if "copy.format" in cand_names and "copy" in cand_names:
                    boost_name = "copy.format"
            if boost_name:
                new_sc = []
                for x in scored:
                    if x[2]["name"] == boost_name:
                        new_sc.append((max(top_base, x[0], gas_ws_find.WEAK_SCORE) + MARGIN,) + tuple(x[1:]))
                    else:
                        new_sc.append(x)
                scored = sorted(new_sc, key=lambda x: (-x[0], x[1]))

        # 札の「頼み:」の正規表現が当たった棚は、点が近ければ（EVIDENCE_GAP 以内）その棚を 1 位にする（調停済みならスキップ）
        lead = scored[0][0]
        near = [x for x in scored if lead - x[0] <= EVIDENCE_GAP]
        rx_hit = lambda x: any("re" in r and _rx(r["re"]).search(c) for r in x[2].get("ask_rules") or [])
        hit = [x for x in near if rx_hit(x)]
        far = [x for x in scored if x not in near and rx_hit(x)]
        if not boost_name:
            if far and any(x[2]["name"] == "write" for x in far) and scored[0][2]["name"] == "replace" and CELL_RE.search(c):
                w_item = next(x for x in far if x[2]["name"] == "write")
                hit = [w_item]
                far = [x for x in far if x[2]["name"] != "write"]
            if far and not hit:
                top_nm_far = scored[0][2]["name"]
                intent_act_far = bool(re.search(r"解除|外し|外す|やめ|消|削除|クリア|一覧|教え|見|確認|動か|移動|入れ替", c))
                top_is_act_far = bool(re.search(r"(?:^|\.)(?:clear|remove|off|list|move|delete|diff|audit|check|extract)|^unfreeze$", top_nm_far))
                if not (scored[0][0] >= gas_ws_find.WEAK_SCORE and intent_act_far and top_is_act_far):
                    p.reasons.append(f"「{c}」の当てが割れた（{scored[0][2]['name']} と {far[0][2]['name']}）")
                    p.cards += [scored[0][2], far[0][2]]
                    fatal_err = True
                    last_incomplete = None
                    continue
            if len(hit) == 1 and hit[0] is not scored[0]:
                s0_nm = scored[0][2]["name"]
                intent_act = bool(re.search(r"解除|外し|外す|やめ|消|削除|クリア|一覧|教え|見|確認|動か|移動|入れ替", c))
                s0_is_act = bool(re.search(r"(?:^|\.)(?:clear|remove|off|list|move|delete|diff|audit|check|extract)|^unfreeze$", s0_nm))
                if not (scored[0][0] >= gas_ws_find.WEAK_SCORE and intent_act and s0_is_act and hit[0][0] < scored[0][0]):
                    scored = [hit[0]] + [x for x in scored if x is not hit[0]]
                    scored[0] = (max(lead, hit[0][0], gas_ws_find.WEAK_SCORE) + MARGIN,) + tuple(scored[0][1:])
            elif len(hit) == 1:
                scored[0] = (max(scored[0][0], gas_ws_find.WEAK_SCORE) + MARGIN,) + tuple(scored[0][1:])
        top_t, _, top, _ = scored[0]
        second = scored[1] if len(scored) > 1 else None
        if top_t < gas_ws_find.WEAK_SCORE:
            p.reasons.append(f"「{c}」の当てが弱い（{top['name']}）")
            p.cards += [s for _, _, s, _ in scored[:3]]
            fatal_err = True
            last_incomplete = None
            continue
        if second and top_t - second[0] < MARGIN:
            p.reasons.append(f"「{c}」の当てが割れた（{top['name']} と {second[2]['name']}）")
            p.cards += [s for _, _, s, _ in scored[:3]]
            fatal_err = True
            last_incomplete = None
            continue
        if top["name"] == "api" or not top["searchable"]:
            p.reasons.append(f"「{c}」は棚に無い頼みです")
            fatal_err = True
            last_incomplete = None
            continue
        op, missing, named = build_op(top, c, table, sheets, cur_sheet)
        if p.ops and p.ops[-1].get("shelf") == top["name"]:
            prev = p.ops[-1]
            for scope_k in ("header", "title", "range", "col"):
                if scope_k in prev and scope_k not in op:
                    op[scope_k] = prev[scope_k]
                    named = True
                    missing = [m for m in missing if not any(x in m for x in ("range", "col", "header", "title"))]
            if top["name"] == "format":
                if re.search(r"色[もを]付[け言]|色[もを]つ[け言]|色[もを]塗", c) and not op.get("bg") and not op.get("color"):
                    op["bg"] = "青"
        elif isinstance(last_scope, dict) and (top["name"] == "format" or last_scope.get("from_browser")) and (
            any(k not in ("shelf", "sheet") for k in op) or missing
        ):
            missing, added = _apply_scope_fallback(op, missing, last_scope, shelf=top, clause=c_raw)
            named = named or added
            if top["danger"] and named and not VAGUE.search(nfkc(c_raw)) and not missing:
                op["ok"] = True
        p.ops.append(op)
        if missing:
            miss_start = len(p.missing)
            p.missing += [f"{top['name']}: " + m for m in missing]
            p.cards.append(top)
            last_incomplete = {"clause": c, "top": top, "missing_n": len(missing), "miss_start": miss_start, "card_added": True}
        elif top["danger"] and not named and len(op) == 1:
            p.reasons.append(f"「{c}」は{top['danger']}棚で、場所の名指しがありません")
            p.cards.append(top)
            fatal_err = True
            last_incomplete = None
        else:
            last_incomplete = None
    is_pure_undo = bool(re.match(r"^(?:さっきの?|直前の?|1つ前の?|ひとつ前の?)?(?:元に戻|戻して|取り消|やり直)", nfkc(ask).strip()))
    soft_pat = r"^(?:doc\.outline|filter\.where|filter\.on|filter\.off|filter\.extract|drive\.list|cf\.list|name\.list|protect\.list|note\.list|audit\.check|find|rows\.show|cols\.show|sheet\.show|top\.n)$"
    if any(("外です" in g or ("ws_undo" in g and (not p.ops or is_pure_undo)) or ("ws_undo" not in g and ("棚はありません" in g or "棚ではありません" in g) and not any(re.match(soft_pat, o["shelf"]) for o in p.ops))) for g in p.guide) or (p.guide and not p.ops):
        p.reasons.append("案内が出ています（棚でない頼み）")
        fatal_err = True
    kinds = {finder.cat.by_name[o["shelf"]]["kind"] for o in p.ops if not finder.cat.by_name[o["shelf"]].get("shared") and o["shelf"] not in gas_ws_catalog.LOCAL_HANDLERS}
    if len(kinds) > 1:
        p.reasons.append("シートの棚と文書の棚が混ざりました")
        fatal_err = True
    seen, cards = set(), []
    for s in p.cards:
        if s["name"] not in seen:
            seen.add(s["name"])
            cards.append(s)
    p.cards = cards[:4]
    # 同じ手が続いたら 1 つに（節が 2 つとも同じ棚に当たったとき）。足す・書く・埋める手は 2 回で意味が変わるのでまとめない
    dd = []
    for o in p.ops:
        if dd and o == dd[-1] and not re.search(r"insert|add|write|fill|copy|new", o.get("shelf", "")):
            continue
        dd.append(o)
    p.ops = dd
    p.fire = (not fatal_err) and (not p.missing) and bool(p.ops)
    return p


def render_unfired(p, finder):
    lines = ["撃っていません: " + ("／".join(p.reasons) or "引数が決まりません")]
    if len(p.missing) == 1 and p.ops:
        miss_name = p.missing[0].split(": ", 1)[-1] if ": " in p.missing[0] else p.missing[0]
        lines.append(f"この ops に {miss_name} を入れて ws_do(ops=…) で撃つ")
    elif p.missing:
        lines.append("足りない引数: " + "、".join(p.missing))
    if p.ops:
        lines.append("組みかけ: ops=" + json.dumps(p.ops, ensure_ascii=False, separators=(",", ":")))
    for g in p.guide[:2]:
        lines.append("案内: " + g)
    if p.cards:
        lines.append("候補の札:")
        for i, s in enumerate(p.cards, 1):
            c = finder.card(s, with_diff=False)
            lines.append(f"{i}. " + c[0])
            lines.extend(c[1:])
    if any("人にしか分かりません" in r for r in p.reasons):
        lines.append("表を調べに行かず、どこ（どれ）を指すかを使う人に聞いて終える。")
    else:
        lines.append("決まったら ws_do(ops=…) で撃つ（足りない物が人にしか分からないときだけ聞く）。")
    return "\n".join(lines)


def table_line(table):
    if not table or table.get("none"):
        return ""
    s = f"表: {table.get('first_col')}〜{table.get('last_col')} 列・見出し {table.get('header_row')} 行目・明細 {table.get('data')} 行目"
    s += f"・合計行 {table['total_row']} 行目" if table.get("total_row") else "・合計行なし"
    return s
