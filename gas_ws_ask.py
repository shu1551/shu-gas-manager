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

import gas_ws_find

MARGIN = 3              # 1 位と 2 位の点の差がこれ未満なら「割れた」
EVIDENCE_GAP = 8        # 札の正規表現が当たった棚を繰り上げる、1 位との点の差の上限
WHAT_MIN = 3           # 「何をするか」の引数（真偽・色・数・文字・選択の任意の物）がこれ以上ある棚で、1 つも決まらなければ撃たない
# 何を指しているか人にしか分からない言い方（撃たずに聞く）
VAGUE = re.compile(r"いらない|要らない|不要な?|余分なところ|余分な箇所|古い(?!順)|おかしい|この辺|どこか|適当に|いい感じ|ダブってる人|変な")
CUR_SHEET = re.compile(r"今の|この|現在の|シート名")
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

# 色の言い方 → エンジンの色の名前（rgb_ が読む物）。長い順に当てる
_COLORS = [
    ("薄い灰色", "薄灰"), ("薄い灰", "薄灰"), ("薄灰色", "薄灰"), ("薄いグレー", "薄灰"), ("薄グレー", "薄灰"),
    ("薄い青", "薄青"), ("薄青", "薄青"), ("水色", "水色"), ("薄い赤", "薄赤"), ("薄い緑", "薄緑"), ("薄い黄", "薄黄"),
    ("薄いオレンジ", "薄橙"), ("薄い紫", "薄紫"),
    ("灰色", "灰"), ("グレー", "灰"), ("オレンジ", "橙"), ("ピンク", "桃"), ("ネイビー", "紺"), ("紺", "紺"), ("茶色", "茶"),
    ("赤", "赤"), ("青", "青"), ("緑", "緑"), ("黄", "黄"), ("紫", "紫"), ("黒", "黒"), ("白", "白"),
]


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


def clauses(ask):
    parts = [p.strip() for p in SPLIT.split(nfkc(ask))]
    return [p for p in parts if len(p) >= 2]


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


def _colors(text):
    out, taken = [], [False] * len(text)
    for word, val in _COLORS:
        start = 0
        while True:
            i = text.find(word, start)
            if i < 0:
                break
            if not any(taken[i:i + len(word)]):
                for k in range(i, i + len(word)):
                    taken[k] = True
                out.append((i, val))
            start = i + 1
    return [v for _, v in sorted(out)]


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
        if r["arg"] in op:
            continue
        if "re" in r:
            rx = _rx(r["re"])
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
    names = _col_names(scan, table)
    letters = _col_letters(scan)
    explicit_range = _range_of(scan, table)
    rows = _rows_of(scan)
    colors = _colors(scan)
    nums = _numbers(scan)
    sheet_hits = [s for s in (sheets or []) if s and nfkc(s) in scan]
    named = bool(explicit_range or rows or letters or names or sheet_hits or shelf["name"] in ("dedupe", "seiri"))
    need = [a["name"] for a in shelf["args"] if a["req"]] + [k for k in shelf["any"]]
    col_pool = list(names) + [x for x in letters if x not in [_letter_of(table, n) for n in names]]
    range_given = False
    # 色: 引数が 1 つならそれ。2 つ以上なら 背景／文字 の語で振り分け
    color_args = [a["name"] for a in shelf["args"] if a["type"] == "色" and a["name"] not in op]
    if colors and color_args:
        if len(color_args) == 1:
            op[color_args[0]] = colors[0]
        else:
            pick = None
            if "文字" in text and "color" in color_args:
                pick = "color"
            elif "bg" in color_args:
                pick = "bg"
            op[pick or color_args[0]] = colors[0]
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
            if range_given or (not wanted and any(op.get(x) not in (None, "", []) for x in shelf["any"])):
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
            if col_pool:
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


# ------------------------------------------------------------------ 頼み → ops
def plan(ask, finder, kind="", table=None, sheets=None, cur_sheet=""):
    cur_sheet = cur_sheet or (sheets[0] if sheets else "")
    p = Plan()
    ask = (ask or "").strip()
    if not ask:
        p.reasons.append("頼みの文が空です")
        return p
    q_all = gas_ws_find.norm(ask, finder.syn)
    p.guide = [text for words, text in finder.guide if any(gas_ws_find.norm(w, finder.syn) and gas_ws_find.norm(w, finder.syn) in q_all for w in words)]
    cl = clauses(ask) or [nfkc(ask)]
    ok_all = True
    if VAGUE.search(nfkc(ask)):
        p.reasons.append("どこを指すかが人にしか分かりません（" + VAGUE.search(nfkc(ask)).group(0) + "）")
        ok_all = False
    for c in cl:
        scored = finder.score_all(c, kind)
        if not scored:
            p.reasons.append(f"「{c}」に当たる棚がありません")
            ok_all = False
            continue
        # 札の「頼み:」の正規表現が当たった棚は、点が近ければ（EVIDENCE_GAP 以内）その棚を 1 位にする（当たった棚が 1 本だけのとき）
        lead = scored[0][0]
        near = [x for x in scored if lead - x[0] <= EVIDENCE_GAP]
        rx_hit = lambda x: any("re" in r and _rx(r["re"]).search(c) for r in x[2].get("ask_rules") or [])
        hit = [x for x in near if rx_hit(x)]
        far = [x for x in scored if x not in near and rx_hit(x)]
        if far and any(x[2]["name"] == "write" for x in far) and scored[0][2]["name"] == "replace" and CELL_RE.search(c):
            w_item = next(x for x in far if x[2]["name"] == "write")
            hit = [w_item]
            far = [x for x in far if x[2]["name"] != "write"]
        if far and not hit:
            p.reasons.append(f"「{c}」の当てが割れた（{scored[0][2]['name']} と {far[0][2]['name']}）")
            p.cards += [scored[0][2], far[0][2]]
            ok_all = False
            continue
        if len(hit) == 1 and hit[0] is not scored[0]:
            scored = [hit[0]] + [x for x in scored if x is not hit[0]]
            scored[0] = (max(lead, hit[0][0], gas_ws_find.WEAK_SCORE) + MARGIN,) + tuple(scored[0][1:])
        elif len(hit) == 1:
            scored[0] = (max(scored[0][0], gas_ws_find.WEAK_SCORE) + MARGIN,) + tuple(scored[0][1:])
        top_t, _, top, _ = scored[0]
        second = scored[1] if len(scored) > 1 else None
        if top_t < gas_ws_find.WEAK_SCORE:
            p.reasons.append(f"「{c}」の当てが弱い（{top['name']}）")
            p.cards += [s for _, _, s, _ in scored[:3]]
            ok_all = False
            continue
        if second and top_t - second[0] < MARGIN:
            p.reasons.append(f"「{c}」の当てが割れた（{top['name']} と {second[2]['name']}）")
            p.cards += [s for _, _, s, _ in scored[:3]]
            ok_all = False
            continue
        if top["name"] == "api" or not top["searchable"]:
            p.reasons.append(f"「{c}」は棚に無い頼みです")
            ok_all = False
            continue
        op, missing, named = build_op(top, c, table, sheets, cur_sheet)
        if p.ops and p.ops[-1].get("shelf") == top["name"]:
            prev = p.ops[-1]
            for scope_k in ("header", "range", "col"):
                if scope_k in prev and scope_k not in op:
                    op[scope_k] = prev[scope_k]
                    named = True
                    missing = [m for m in missing if not any(x in m for x in ("range", "col", "header"))]
            if top["name"] == "format":
                if re.search(r"色[もを]付[け言]|色[もを]つ[け言]|色[もを]塗", c) and not op.get("bg") and not op.get("color"):
                    op["bg"] = "青"
        p.ops.append(op)
        if missing:
            p.missing += [f"{top['name']}: " + m for m in missing]
            p.cards.append(top)
            ok_all = False
        elif top["danger"] and not named and len(op) == 1:
            p.reasons.append(f"「{c}」は{top['danger']}棚で、場所の名指しがありません")
            p.cards.append(top)
            ok_all = False
    if any(("外です" in g or "ws_undo" in g or (("棚はありません" in g or "棚ではありません" in g) and not any(o["shelf"] in ("doc.outline", "filter.where", "filter.on") for o in p.ops))) for g in p.guide) or (p.guide and not p.ops):
        p.reasons.append("案内が出ています（棚でない頼み）")
        ok_all = False
    kinds = {finder.cat.by_name[o["shelf"]]["kind"] for o in p.ops}
    if len(kinds) > 1:
        p.reasons.append("シートの棚と文書の棚が混ざりました")
        ok_all = False
    seen, cards = set(), []
    for s in p.cards:
        if s["name"] not in seen:
            seen.add(s["name"])
            cards.append(s)
    p.cards = cards[:4]
    p.fire = ok_all and bool(p.ops)
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
    lines.append("決まったら ws_do(ops=…) で撃つ（足りない物が人にしか分からないときだけ聞く）。")
    return "\n".join(lines)


def table_line(table):
    if not table or table.get("none"):
        return ""
    s = f"表: {table.get('first_col')}〜{table.get('last_col')} 列・見出し {table.get('header_row')} 行目・明細 {table.get('data')} 行目"
    s += f"・合計行 {table['total_row']} 行目" if table.get("total_row") else "・合計行なし"
    return s
