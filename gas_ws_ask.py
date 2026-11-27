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
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import gas_ws_catalog
import gas_ws_find

ASK_MISSES_FILE = Path(__file__).resolve().parent / ".ws_ask_misses.tsv"

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
        self.read_only = False # シートを変えない「読むだけ」の問いと判定されたか
        self.choices = []      # 曖昧な頼みに対する選択肢 [{label, desc, ops}, ...]
        self.reasons = []      # 撃たない理由（人と AI に見せる）
        self.missing = []      # 決まらなかった引数（"棚: 引数(型)"）
        self.cards = []        # 候補の棚の dict（撃たないときに札を見せる）
        self.guide = []

    def to_dict(self):
        return {"ops": self.ops, "fire": self.fire, "read_only": self.read_only, "choices": self.choices,
                "reasons": self.reasons, "missing": self.missing, "cards": [s["name"] for s in self.cards], "guide": self.guide}


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


def _resolve_col_ref(raw, table):
    """列名の解決を 1 か所に統一する。順: 列記号 → 完全一致 → 含む列が 1 つだけ → 2 つ以上/0 なら None。"""
    s = nfkc(str(raw or "")).strip()
    if not s:
        return None
    if not table or not table.get("columns"):
        return str(raw).strip()
    if re.fullmatch(r"[A-Z]{1,3}", s):
        return s
    m_cl = re.fullmatch(r"([A-Z]{1,3})列", s)
    if m_cl:
        return m_cl.group(1)
    s_clean = re.sub(r"(?:の列|列|の欄|欄)$", "", s).strip()
    cols = [str(c.get("name") or "").strip() for c in table["columns"] if str(c.get("name") or "").strip()]
    # 1. 完全一致
    for cn in cols:
        if nfkc(cn).strip() in (s, s_clean):
            return cn
    # 2. 含む列がちょうど 1 つだけ（2文字以上・ストップワード除外）
    tok = re.sub(r"(?:別表|別|毎)$", "", s_clean).strip()
    if len(tok) >= 2 and tok not in _COL_TOKEN_STOP:
        hits = [cn for cn in cols if tok in nfkc(cn)]
        if len(hits) == 1:
            return hits[0]
    return None


def _col_names(text, table):
    """見出しの名前を 1 本化した順（完全一致 → 含む列が 1 つだけ）で出現順に返す。"""
    if not table or not table.get("columns"):
        return []
    names = [str(c.get("name") or "").strip() for c in table["columns"] if str(c.get("name") or "").strip()]
    hits = []
    taken = [False] * len(text)
    # 1. 完全一致（長い名前優先）
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
    # 2. 残りの語から「含む列がちょうど 1 つだけ」を解決（2つ以上・0は採らない）
    nfkc_text = nfkc(text)
    if len(nfkc_text) == len(taken):
        for m in re.finditer(r"[一-龥ァ-ヶA-Za-z0-9]{2,}", nfkc_text):
            if any(taken[m.start():m.end()]):
                continue
            tok = re.sub(r"(?:別表|別|毎|列|欄)$", "", m.group(0))
            if len(tok) < 2 or tok in _COL_TOKEN_STOP:
                continue
            matched = [nm for nm in names if tok in nfkc(nm)]
            if len(matched) == 1 and not any(nm == matched[0] for _, nm in hits):
                for k in range(m.start(), m.end()):
                    taken[k] = True
                hits.append((m.start(), matched[0]))
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
    res = _resolve_col_ref(name, table)
    if not res:
        return None
    if re.fullmatch(r"[A-Z]{1,3}", res):
        return res
    for c in (table or {}).get("columns") or []:
        if c.get("name") == res:
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
                # 「空白」「余白」「白紙」「面白い」等の熟語中の「白」は色ではない
                if word == "白" and ((i > 0 and text[i - 1] in "空余明面告") or (i + 1 < len(text) and text[i + 1] in "紙")):
                    start = i + 1
                    continue
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


def _extract_calc_expr(text, table):
    """日本語の四則演算表現（語順「AとB」「BにAを」、ひらがな・漢字・記号）から計算式（A*B 等）を抽出する。"""
    src = nfkc(text)
    col_names = sorted(
        {str(c.get("name") or "").strip() for c in (table or {}).get("columns") or [] if str(c.get("name") or "").strip()},
        key=len,
        reverse=True,
    )
    # 出し先の「〜の列に/へ」を先頭・末尾とも取り除いた候補文も用意する
    expr_stripped = src
    for cn in col_names:
        expr_stripped = re.sub(re.escape(nfkc(cn)) + r"の?(?:列|欄)[にへ]", " ", expr_stripped)
    m_pref = re.search(r"^.*?(?:列|欄)[にへ]\s*", src)
    expr_pref = src[m_pref.end():] if m_pref else src

    def _clean_operand(raw):
        s = re.sub(r"^[\s、,。をにで]+|[\s、,。をにで]+$", "", str(raw or "").strip())
        if not s:
            return None
        if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", s):
            return s
        res = _resolve_col_ref(s, table)
        if res:
            return res
        return None if (table and table.get("columns")) else s

    patterns = [
        (r"([^\s、,。をにと×*]{1,20})\s*(?:と|に|×|\*)\s*([^\s、,。をにと×*]{1,20})\s*(?:を)?(?:掛け|かけ|のかけ|乗算|掛け算)", "*"),
        (r"([^\s、,。をにと＋+]{1,20})\s*(?:と|に|＋|\+)\s*([^\s、,。をにと＋+]{1,20})\s*(?:を)?(?:足[しす]|た[しす]|加算)", "+"),
        (r"([^\s、,。をにから−-]{1,20})\s*(?:から|−|-)\s*([^\s、,。をにから−-]{1,20})\s*(?:を)?(?:引[いけく]|ひ[いけく]|差し引|減算)", "-"),
        (r"([^\s、,。をに÷/]{1,20})\s*(?:を|÷|/)\s*([^\s、,。をに÷/]{1,20})\s*(?:で)?(?:割[っりる]|わ[っりる]|除算)", "/"),
    ]
    cands = []
    for cs in (expr_stripped, expr_pref, src):
        if cs and cs not in cands:
            cands.append(cs)
    for cand_src in cands:
        for pat, sym in patterns:
            m = re.search(pat, cand_src)
            if m:
                a = _clean_operand(m.group(1))
                b = _clean_operand(m.group(2))
                if a and b:
                    return f"{a}{sym}{b}"
    return None


def _normalize_filter_number(val):
    """比較フィルタの数値を正規化する（%→小数、万/億→乗算、カンマ除去）。数値化できなければ None。"""
    if val is None:
        return None
    s = nfkc(str(val)).replace(",", "").strip()
    if not s:
        return None
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1].strip()
    mul = 1
    if s.endswith("万"):
        mul = 10000
        s = s[:-1].strip()
    elif s.endswith("億"):
        mul = 100000000
        s = s[:-1].strip()
    try:
        num = float(s) * mul
    except Exception:
        return None
    if is_pct:
        num = num / 100.0
    if num.is_integer():
        return str(int(num))
    return f"{num:.10g}"


_COL_TOKEN_STOP = {
    "集計", "合計", "平均", "件数", "人数", "グラフ", "ピボット", "クロス", "シート", "別シート",
    "データ", "テーブル", "一覧", "全部", "全体", "全て", "行全体", "条件", "書式", "表示", "形式",
    "作成", "追加", "変更", "削除", "抽出", "固定", "並べ", "整理", "自動", "調整", "内容", "中身",
    "範囲", "セル", "タイトル", "見出し", "ヘッダ", "合計行", "標準", "棒グラフ", "折れ線", "円グラフ",
    "新しい", "別表", "結果", "計算", "数式", "文字", "背景", "罫線", "太字", "斜体", "中央", "右揃",
    "左揃", "非表示", "表示形式", "プルダウン", "リスト", "選択肢", "以上", "以下", "未満", "以外",
    "重複", "空行", "空白", "空欄", "昇順", "降順", "上位", "下位", "最大", "最小", "小計", "累計",
    "順位", "構成比", "割合", "消費税", "税込", "税抜", "円マーク", "カンマ", "パーセント", "年月日",
}

_FORMULA_COL_SHELVES = {
    "calc.col", "calc.percent", "calc.diff", "calc.running", "calc.rank",
    "calc.if", "calc.tax", "date.parts", "date.diff", "date.age",
    "text.join", "col.compare", "lookup.add",
}

_SKIP_COL_VALIDATE = {
    ("table.new", "number"), ("table.new", "total"),
    ("lookup.add", "val_col"), ("lookup.add", "key_col"),
}

_CMP_VALUE_SHELVES = {
    "filter.where", "filter.delete", "filter.extract",
    "cf.add", "calc.if", "rows.highlight",
}
_PCT_COL_RE = re.compile(r"(?:率|割合|構成比|達成|進捗|%|％)")
_CALC_VERB_PREFIX_RE = re.compile(
    r"^.*?(?:(?:差し引い|掛け|かけ|足し|たし|引い|ひい|割っ|わっ|乗算し|加算し|減算し|除算し|計算し)(?:た|て)|(?:掛け算|かけ算|足し算|引き算|割り算)(?:の|で))\s*"
)

# 任意（非必須）の列引数へ無関係な列名が流れ込まないようにするキーワード条件（1 か所管理）
_OPT_COL_CUES = {
    "at": re.compile(r"(?:列|欄)[にへ]|の間に"),
    "renumber": re.compile(r"連番|通し番号|番号を?(?:振|付)|振り直|ふり直|付け直|つけ直|ナンバリング"),
    "number": re.compile(r"連番|通し番号"),
    "total": re.compile(r"合計|総計|小計"),
    "url_col": re.compile(r"url|リンク先|アドレス", re.IGNORECASE),
}

# cols.delete の型ガード（列そのものが消す対象のときだけ許可し、「列の〈中身〉を消して」は列削除にしない）
_COL_CONTENT_DEL_RE = re.compile(
    r"中身|値だけ|値を|データだけ|データを|クリア|空白|スペース|改行|重複|ダブ|エラー|記号|ハイフン|"
    r"文字|数字|数値|数式|式だけ|式を|ゼロ|0を|色|背景|書式|罫線|太字|メモ|コメント|リンク|"
    r"プルダウン|入力規則|フィルタ|フィルター|条件付き書式|前後|余分な|ゴミ|不可視|非表示|隠|"
    r"振り直|付け直|連番|行を|の行|行目"
)
_COL_PROP_OBJ_RE = re.compile(
    r"(?:列|カラム)の(?!削除|消去|除去|一番|右|左|先頭|末尾|最後|最初)[^\s、。のをにはが]{1,16}を"
)
_COL_DIRECT_DEL_RE = re.compile(
    r"(?:列|カラム)(?:を|ごと|丸ごと|まるごと|まるっと|の(?:削除|消去|除去)|(?:は|が)?(?:いらない|要らない|不要|削除|消))"
)

# 条件つき書式（行ごと）の対象名詞型（「〈列〉が〈条件〉の〈何か〉を〈書式〉に」、ただし「セル」は列単体のまま維持）
_ROW_CF_THING_RE = re.compile(
    r"行全体|の行(?:に|を|全部|だけ|は)?|行に色|行を目立|行を(?:赤|黄|青|緑|黒|白|薄|濃|橙|灰|紫|水色|紺|茶|桃|太字)|いない行|ない行"
    r"|(?:になって(?:いる|る)|の)(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)"
    r"|(?:以上|以下|未満|より大き(?:い|く)?|より小さ(?:い|く)?|より前|より後|以前|以降|を超え?|上回[るっ]|下回[るっ]|届か(?:ない)?|届いてい?ない|以外|ではない|でない|じゃない|になって(?:いない|ない|いる|る)|マイナス|負の値)(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)"
    r"|(?:書かれ|記載され|入力され|入っ|含まれ|含[むみ]|とある)(?:てい?る|た)?(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)"
)
def _mask_col_names(text, table):
    """表の列名（「メモ」「コメント」等）を伏せる。除外語の判定が列名に引っかからないように"""
    if not table or not table.get("columns"):
        return text
    out = text
    for nm in sorted((str(c.get("name") or "") for c in table["columns"]), key=len, reverse=True):
        if len(nm) >= 2:
            out = out.replace(nm, "□")
    return out


_DATE_SHIFT_RE = re.compile(r"([^\s、。をにがはで]{1,16}?)(?:列)?(?:から|の)([0-9]+)\s*(日|週間|週|か月|ヶ月|カ月|ヵ月|ケ月|月|年)(後|前)")


def _date_shift_of(text, table):
    """「〈日付の列〉から N 日／週間／か月／年 後・前」→ (式, 列名)。日・週は足し引き、月・年は EDATE"""
    m = _DATE_SHIFT_RE.search(nfkc(text))
    if not m:
        return None
    col = _resolve_col_ref(m.group(1).strip(), table) if table and table.get("columns") else m.group(1).strip()
    if not col:
        return None
    n, unit, d = int(m.group(2)), m.group(3), m.group(4)
    sign = "+" if d == "後" else "-"
    if unit == "日":
        expr = f"{col}{sign}{n}"
    elif unit in ("週間", "週"):
        expr = f"{col}{sign}{n * 7}"
    else:
        months = n * 12 if unit == "年" else n
        expr = f"EDATE({col},{'' if sign == '+' else '-'}{months})"
    return expr, f"{n}{unit}{d}"


def _multi_col_agg_of(text, table):
    """「国語と数学と英語の合計の列」「3教科の平均の列」→ (式, 列名)。数値の列だけ。読めなければ None"""
    if not table or not table.get("columns"):
        return None
    t = nfkc(text)
    m_kind = re.search(r"の?(合計|和|平均)(?:点|値)?の?(?:列|欄)", t)
    if not m_kind:
        return None
    kind = "平均" if m_kind.group(1) == "平均" else "合計"
    head = t[: m_kind.start()]
    nums = [str(c.get("name") or "") for c in table["columns"] if c.get("number")]
    cols = []
    m_n = re.search(r"([0-9]+|全|各)(?:教科|科目|項目|つの(?:点数|数値|列))", head)
    if m_n:
        if m_n.group(1) in ("全", "各") or int(m_n.group(1)) == len(nums):
            cols = nums
    else:
        parts = re.split(r"と|・|、|,", head)
        for p in parts:
            r = _resolve_col_ref(p.strip(), table)
            if r and r not in cols:
                cols.append(r)
        if len(cols) != len([p for p in parts if p.strip()]):
            return None
    if len(cols) < 2 or any(c not in nums for c in cols):
        return None
    expr = "+".join(cols) if kind == "合計" else f"AVERAGE({','.join(cols)})"
    return expr, kind


def _cf_blank_today_expr(text, ref_l, r1):
    """行ごとの条件付き書式で「空欄」「今日より前」等を文字のまま式に入れない（空欄は ""・今日は TODAY()）"""
    t = nfkc(text)
    c = f"${ref_l}{r1}"
    if re.search(r"(?:空欄|空白)(?:以外|ではない|でない|じゃない)|入力済", t):
        return f'={c}<>""'
    if re.search(r"空欄|空白|未入力|入力されていない", t):
        return f'={c}=""'
    if re.search(r"今日(?:より前|以前|を過ぎ|が過ぎ)|期限切れ|期限が切れ|期限を過ぎ", t):
        return f"=AND(ISNUMBER({c}),{c}<TODAY())" if "以前" not in t else f"=AND(ISNUMBER({c}),{c}<=TODAY())"
    if re.search(r"今日(?:より後|以降|より先)", t):
        return f"=AND(ISNUMBER({c}),{c}>TODAY())" if "以降" not in t else f"=AND(ISNUMBER({c}),{c}>=TODAY())"
    m_y = re.search(r"((?:19|20)[0-9]{2})年(以前|まで|以降|から|より前|より後|より新しい|より古い)", t)
    if m_y:
        sym = {"以前": "<=", "まで": "<=", "より前": "<", "より古い": "<", "以降": ">=", "から": ">=", "より後": ">", "より新しい": ">"}[m_y.group(2)]
        return f"=AND(ISNUMBER({c}),YEAR({c}){sym}{m_y.group(1)})"
    return ""


_CF_NUM_CMP_RE = re.compile(r"(-?[0-9][0-9,\.]*)\s*(?:円|個|件|人|点|日|%)?\s*(以上|以下|未満|より大きい|より小さい|を超え(?:る|た)?|超え?|を下回る|を上回る)")


def _cf_atom(cond, ref_l, r1):
    """1 つの条件（「今日より前」「空欄」「60点未満」「完了」）→ 式の中身（= なし）。読めなければ ''"""
    e = _cf_blank_today_expr(cond, ref_l, r1)
    if e:
        return e[1:]
    c = f"${ref_l}{r1}"
    m = _CF_NUM_CMP_RE.search(nfkc(cond))
    if m:
        n = m.group(1).replace(",", "")
        w = m.group(2)
        sym = ">=" if w == "以上" else "<=" if w == "以下" else "<" if w in ("未満", "より小さい", "を下回る") else ">"
        return f"{c}{sym}{n}"
    lit = nfkc(cond).strip().strip("「」『』")
    if lit and re.fullmatch(r"[^\s、。をにがはでの]{1,16}", lit) and not re.search(r"以上|以下|未満|より|超|以外|ない|前|後", lit):
        return f'{c}="{lit}"'
    return ""


def _cf_compound_expr(text, table):
    """「〈列A〉が〈条件〉で〈列B〉が〈条件〉の行」→ (式, 読めたか)。2 つの条件がどちらも列に当たるときだけ扱う"""
    if not table or not table.get("columns"):
        return None
    t = nfkc(text)
    m = re.search(r"([^\s、。をに]{1,16}?)(?:列)?(?:が|は)(.+?)(?:で|かつ|且つ|、かつ|、)([^\s、。をに]{1,16}?)(?:列)?(?:が|は)(.+?)(?:の行|行を|行全体|行に)", t)
    if not m:
        return None
    c1, c2 = _resolve_col_ref(m.group(1), table), _resolve_col_ref(m.group(3), table)
    if not c1 or not c2 or c1 == c2:
        return None
    l1, l2 = _letter_of(table, c1), _letter_of(table, c2)
    sp = _data_span(table)
    r1 = sp[0] if sp else ((table.get("header_row") or 1) + 1)
    a1, a2 = _cf_atom(m.group(2), l1, r1), _cf_atom(m.group(4), l2, r1)
    if a1 and a2:
        return f"=AND({a1},{a2})", True
    return "", False


_COND_EQ_THING_RE = re.compile(
    r"([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)[『「]?([^』」\s、。の]+?)[』」]?(?:になって(?:いる|る)|の)(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線)[^\s、。のをにはが]{1,12}"
)
_TWO_COL_CMP_RE = re.compile(
    r"([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)"
    r"([^\s、。をに]{1,16}?)(?:列)?"
    r"(?:を(下回[るっ]|上回[るっ]|超え?る?|超え)|に(届か(?:ない)?|届いてい?ない)|"
    r"(下回[るっ]|上回[るっ]|超え?る?|超え|届か(?:ない)?|届いてい?ない|"
    r"より大き(?:い|く)?|より小さ(?:い|く)?|以上|以下|未満|"
    r"と等しい|と同じ|と一致|と違う|と異なる|以外|ではない|でない|じゃない))"
)
_COL_CONTAINS_RE = re.compile(
    r"([^\s、。をがはで]{1,16}?)(?:列)?(?:に|が|は)"
    r"(?:[『「]([^』」]{1,24}?)[』」]|([^』」\s、。をにがは]{1,20}?))"
    r"(?:(?:と|が)(?:書かれ|記載|入力され|入っ|含まれ)(?!て?い?な|て?な|な|ず)|を含[むみん](?!で?い?な|で?な|な)|とある(?!わけではな))"
)
_CALC_DIFF_RE = re.compile(
    r"([^\s、。をにとがは]{1,16}?)(?:列)?と([^\s、。をにとがは]{1,16}?)(?:列)?の(?:差額?|差分|差と伸び率|伸び率|増減率)"
)


def _two_col_cmp_of(text, table):
    """「〈列A〉が〈列B〉を下回る/上回る/以上…」の 2 列比較を _resolve_col_ref で解決し (col_a, op_sym, col_b) を返す。"""
    if not table or not table.get("columns"):
        return None
    t_n = nfkc(text)
    for m in _TWO_COL_CMP_RE.finditer(t_n):
        r1, r2 = m.group(1).strip(), m.group(2).strip()
        c1 = _resolve_col_ref(r1, table) or (("の" in r1) and _resolve_col_ref(r1.rsplit("の", 1)[-1], table))
        c2 = _resolve_col_ref(r2, table)
        if not c1 or not c2 or c1 == c2:
            continue
        kw = m.group(3) or m.group(4) or m.group(5) or ""
        if re.search(r"下回|未満|より小さ|届か|届いて", kw):
            sym = "<"
        elif re.search(r"上回|超|より大き", kw):
            sym = ">"
        elif "以上" in kw:
            sym = ">="
        elif "以下" in kw:
            sym = "<="
        elif re.search(r"等しい|同じ|一致", kw):
            sym = "="
        else:
            sym = "<>"
        return (c1, sym, c2)
    return None


def _col_contains_of(text, table):
    """「〈列〉に〈語〉と書かれている/入っている/を含む…」を _resolve_col_ref で解決し (col, word) を返す。"""
    t_n = nfkc(text)
    has_cols = bool(table and table.get("columns"))
    for m in _COL_CONTAINS_RE.finditer(t_n):
        r1 = m.group(1).strip()
        word = (m.group(2) or m.group(3) or "").strip()
        if not word:
            continue
        if has_cols:
            c1 = _resolve_col_ref(r1, table) or (("の" in r1) and _resolve_col_ref(r1.rsplit("の", 1)[-1], table))
            if not c1:
                continue
            return (c1, word)
        return (r1, word)
    return None


def _calc_diff_cols_of(text, table):
    """「〈列A〉と〈列B〉の差額/差/差分/伸び率/増減率」を _resolve_col_ref で解決し (col_a, col_b) を返す。"""
    t_n = nfkc(text)
    has_cols = bool(table and table.get("columns"))
    for m in _CALC_DIFF_RE.finditer(t_n):
        r1, r2 = m.group(1).strip(), m.group(2).strip()
        if has_cols:
            c1 = _resolve_col_ref(r1, table) or (("の" in r1) and _resolve_col_ref(r1.rsplit("の", 1)[-1], table))
            c2 = _resolve_col_ref(r2, table)
            if not c1 or not c2 or c1 == c2:
                continue
            return (c1, c2)
        if r1 and r2 and r1 != r2:
            return (r1, r2)
    return None


def _col_let_to_num(s):
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n


def _cond_col_of(text, table):
    """文中の「〈列〉が／は…」から条件対象列を _resolve_col_ref 1 か所で解決して返す。"""
    t_n = nfkc(text)
    for m in re.finditer(r"([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)", t_n):
        res = _resolve_col_ref(m.group(1).strip(), table)
        if res:
            return res
    return None

# 日付比較の 1 か所定義（西暦・和暦・年なし月日）
_DATE_TOK_PAT = (
    r"(?<![0-9A-Za-z/])("
    r"[0-9]{4}\s*[/\-.年]\s*[0-9]{1,2}\s*[/\-.月]\s*[0-9]{1,2}\s*日?"
    r"|(?:令和|平成|昭和|大正|明治|[RrHhSsTtMm])\s*(?:元|[0-9]{1,2})\s*[/\-.年]\s*[0-9]{1,2}\s*[/\-.月]\s*[0-9]{1,2}\s*日?"
    r"|[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日"
    r"|[0-9]{1,2}/[0-9]{1,2}"
    r")(?![0-9/])"
)
_DATE_RANGE_CMP_RE = re.compile(_DATE_TOK_PAT + r"\s*(?:から|〜|~|～)\s*" + _DATE_TOK_PAT + r"\s*(?:まで)?")
_DATE_SINGLE_CMP_RE = re.compile(
    _DATE_TOK_PAT + r"\s*(より以前|より前|以前|より以降|より後|以降|の前|の後|から|まで|以上|以下|未満|より大き(?:い|く)?|を超え?|より小さ(?:い|く)?)"
)
_DATE_CMP_CUE_RE = re.compile(
    r"より以前|より前|より以降|より後|以前|以降|" + _DATE_TOK_PAT + r"\s*(?:の前|の後|から|まで)"
)
_ERA_BASE = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925, "大正": 1911, "T": 1911, "明治": 1867, "M": 1867}


def _parse_cmp_date_str(raw):
    """日付トークンを標準比較形式（年あり: YYYY-MM-DD / 年なし: MM/DD）へ正規化。無効なら None。"""
    s = nfkc(str(raw or "")).strip()
    if not s:
        return None
    m = re.fullmatch(r"([0-9]{4})\s*[/\-.年]\s*([0-9]{1,2})\s*[/\-.月]\s*([0-9]{1,2})\s*日?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1868 <= y <= 2100:
            try:
                datetime(y, mo, d)
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                return None
        return None
    mw = re.fullmatch(r"(令和|平成|昭和|大正|明治|[RrHhSsTtMm])\s*(元|[0-9]{1,2})\s*[/\-.年]\s*([0-9]{1,2})\s*[/\-.月]\s*([0-9]{1,2})\s*日?", s)
    if mw:
        base = _ERA_BASE.get(mw.group(1).upper())
        ey = 1 if mw.group(2) == "元" else int(mw.group(2))
        if base and 1 <= ey <= 99:
            y, mo, d = base + ey, int(mw.group(3)), int(mw.group(4))
            try:
                datetime(y, mo, d)
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                return None
        return None
    md = re.fullmatch(r"([0-9]{1,2})\s*(?:月|/)\s*([0-9]{1,2})\s*日?", s)
    if md:
        mo, d = int(md.group(1)), int(md.group(2))
        try:
            datetime(2024, mo, d)
            return f"{mo:02d}/{d:02d}"
        except ValueError:
            return None
    return None


def _date_cmp_to_formula_atom(d_str, table=None):
    """標準日付文字列（YYYY-MM-DD または MM/DD）をスプレッドシート数式 DATE(...) へ変換する。"""
    m_full = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", str(d_str or ""))
    if m_full:
        return f"DATE({int(m_full.group(1))},{int(m_full.group(2))},{int(m_full.group(3))})"
    m_md = re.fullmatch(r"([0-9]{2})/([0-9]{2})", str(d_str or ""))
    if m_md:
        y_hint = None
        for row in (table or {}).get("rows") or []:
            if isinstance(row, (list, tuple)):
                for cell in row:
                    m_y = re.match(r"^\s*([12][0-9]{3})[/\-.年]", nfkc(str(cell or "")))
                    if m_y:
                        y_hint = int(m_y.group(1))
                        break
            if y_hint:
                break
        y_expr = str(y_hint) if y_hint else "YEAR(TODAY())"
        return f"DATE({y_expr},{int(m_md.group(1))},{int(m_md.group(2))})"
    return None


def _resolve_cmp_value(op, text):
    """比べる棚すべてで共通: 文中から日付比較・%・万・億を落とさず比較演算子と値を抽出・正規化する。"""
    t_n = nfkc(text)
    # 0. 日付の比べ（より前・より後・以降・以前・から・まで・範囲）を 1 か所で最優先解決
    m_dr = _DATE_RANGE_CMP_RE.search(t_n)
    if m_dr:
        d1 = _parse_cmp_date_str(m_dr.group(1))
        d2 = _parse_cmp_date_str(m_dr.group(2))
        if d1 and d2:
            op["when"] = "between"
            op["value"] = f"{d1}..{d2}"
            op.pop("equals", None)
            return
    m_ds = _DATE_SINGLE_CMP_RE.search(t_n)
    if m_ds:
        d_norm = _parse_cmp_date_str(m_ds.group(1))
        if d_norm:
            kw = m_ds.group(2)
            if kw in ("より前", "より以前", "の前", "未満") or kw.startswith("より小さ"):
                op["when"] = "lt"
            elif kw in ("以前", "まで", "以下"):
                op["when"] = "le"
            elif kw in ("より後", "より以降", "の後") or kw.startswith("より大き") or kw.startswith("を超"):
                op["when"] = "gt"
            else:
                op["when"] = "ge"
            op["value"] = d_norm
            op.pop("equals", None)
            return

    w = op.get("when")
    if w not in ("gt", "ge", "lt", "le", "eq", "ne"):
        return
    m_num = re.search(
        r"(-?[0-9][0-9,\.]*%?[万億]?)(?:円|個|件|人|時間|点)?\s*(?:以上|以下|未満|より|(?:を)?超|(?:を)?上回|(?:を)?下回|(?:に)?届か|(?:に)?届いてい?ない|になっていない|になってない|ではない|でない|じゃない|以外|の行|のセル|なら|判定)",
        t_n,
    )
    raw = op.get("value")
    if w in ("gt", "ge", "lt", "le"):
        op.pop("equals", None)
        if m_num:
            cand = m_num.group(1).strip()
            # op["value"] が未設定、または %/万/億 が欠落していた場合は文中の完全表記を優先
            if raw in (None, "") or (
                re.search(r"[%万億]", cand) and not re.search(r"[%万億]", nfkc(str(raw)))
            ):
                raw = cand
        norm_v = _normalize_filter_number(raw)
        if norm_v is not None:
            op["value"] = norm_v
        else:
            op.pop("value", None)
    else:
        # eq / ne: 数値(%・万・億含む)なら正規化、文字ならそのまま残す
        if raw in (None, "") and w == "ne":
            m_ne = re.search(
                r"(?:が|は)[『「]?([^』」\s、。]+?)[』」]?(?:になっていない|になってない|ではない|でない|じゃない|以外)",
                t_n,
            )
            if not m_ne:
                m_ne = re.search(
                    r"([^\s、。をにのがは]+?)(?:になっていない|になってない|ではない|でない|じゃない|以外)",
                    t_n,
                )
            if m_ne:
                raw = m_ne.group(1).strip()
        if raw not in (None, "") and m_num:
            cand = m_num.group(1).strip()
            if re.search(r"[%万億]", cand) and not re.search(r"[%万億]", nfkc(str(raw))) and re.sub(r"[%万億,]", "", cand) == re.sub(r"[,]", "", nfkc(str(raw))):
                raw = cand
        if raw not in (None, ""):
            norm_v = _normalize_filter_number(raw)
            if norm_v is not None and (w == "ne" or re.search(r"[%万億,]", nfkc(str(raw)))):
                op["value"] = norm_v
            else:
                op["value"] = str(raw).strip()


def _clean_calc_col_name(raw_name):
    """計算列の新列名から直前の動詞（「引いた」「掛けた」等）や余分な助詞を外す。"""
    if not raw_name:
        return None
    s = nfkc(str(raw_name)).strip()
    s = _CALC_VERB_PREFIX_RE.sub("", s)
    s = re.sub(r"^(?:の|で|を|に|へ)+|(?:の列|列|の欄|欄|の)+$", "", s).strip()
    if not s or re.search(r"(?:差し引い|掛け|かけ|足し|たし|引い|ひい|割っ|わっ)(?:た|て)", s):
        return None
    return s


def _parse_date_ord_py(val, fallback_year=None):
    """行条件判定用の日付 ordinal（YYYY*10000 + MM*100 + DD）を返す。"""
    norm = _parse_cmp_date_str(val)
    if not norm:
        return None
    if "-" in norm:
        y, mo, d = (int(x) for x in norm.split("-"))
        return y * 10000 + mo * 100 + d
    mo, d = (int(x) for x in norm.split("/"))
    y = fallback_year or datetime.now().year
    return y * 10000 + mo * 100 + d


def _match_row_cond_py(cell_val, when, target):
    """手元の表データに対する行条件一致判定（過半数削除ガード用）。"""
    w = str(when or "eq").lower()
    blank = cell_val is None or str(cell_val).strip() == ""
    if w == "blank":
        return blank
    if w == "notblank":
        return not blank
    tgt = "" if target is None else str(target).strip()
    if w == "contains":
        return not blank and tgt in str(cell_val)
    if w == "between" and ".." in tgt:
        p1, p2 = tgt.split("..", 1)
        cd0 = _parse_date_ord_py(cell_val)
        y_fb = (cd0 // 10000) if cd0 else None
        d1, d2 = _parse_date_ord_py(p1, y_fb), _parse_date_ord_py(p2, y_fb)
        if cd0 is None or d1 is None or d2 is None:
            return False
        lo, hi = (d1, d2) if d1 <= d2 else (d2, d1)
        return lo <= cd0 <= hi
    if not re.fullmatch(r"-?[0-9,]+(?:\.[0-9]+)?", tgt):
        cd = _parse_date_ord_py(cell_val)
        y_fb = (cd // 10000) if cd else None
        td = _parse_date_ord_py(tgt, y_fb)
        if td is not None:
            if cd is None:
                return w == "ne"
            if w == "gt":
                return cd > td
            if w == "ge":
                return cd >= td
            if w == "lt":
                return cd < td
            if w == "le":
                return cd <= td
            if w == "ne":
                return cd != td
            return cd == td
    if w in ("gt", "ge", "lt", "le"):
        try:
            cv = float(str(cell_val).replace(",", "").strip())
            tv = float(tgt.replace(",", "").strip())
        except Exception:
            return False
        return (cv > tv) if w == "gt" else ((cv >= tv) if w == "ge" else ((cv < tv) if w == "lt" else cv <= tv))
    if w == "ne":
        try:
            return float(str(cell_val).replace(",", "")) != float(tgt.replace(",", ""))
        except Exception:
            return ("" if blank else str(cell_val).strip()) != tgt
    try:
        return float(str(cell_val).replace(",", "")) == float(tgt.replace(",", ""))
    except Exception:
        return ("" if blank else str(cell_val).strip()) == tgt


_ADD_SHELVES = {
    "banding.add", "filter.on", "cf.add", "cf.dup", "cf.scale", "cf.weekend",
    "validation.list", "validation.number", "validation.date", "freeze",
    "note.set", "link.set", "protect.range", "protect.sheet",
    "group.rows", "group.cols", "chart.new",
}


def _clean_validation_items(text, orig_quotes_list, cur_items):
    """プルダウン候補の並び（「」・、・と区切り）から括弧や助詞を落として綺麗に分割する。"""
    def _strip_item(x):
        s = re.sub(r'^[「『"“\s]+|[」』"”\s]+$', "", str(x or "").strip())
        s = re.sub(r'[「『"“”』」]+', "", s).strip()
        return s

    def _split_chunk(chunk):
        s = re.sub(r'^[「『"“\s]+', "", str(chunk or "").strip())
        s = re.sub(r'(?:[」』"”]|の|から|という|で|を|選べる|\s)+$', "", s).strip()
        if not s:
            return []
        if re.search(r"[・、,／/]", s):
            parts = re.split(r"[・、,／/]", s)
        elif "と" in s:
            parts = s.split("と")
        else:
            parts = [s]
        return [it for it in (_strip_item(p) for p in parts) if it]

    if orig_quotes_list:
        if len(orig_quotes_list) >= 2:
            cleaned = [it for it in (_strip_item(q) for q in orig_quotes_list) if it]
            if cleaned:
                return cleaned
        else:
            cleaned = _split_chunk(orig_quotes_list[0])
            if len(cleaned) >= 2:
                return cleaned
    t_n = nfkc(text)
    m_list = re.search(
        r"(?:に|へ|は)\s*(.+?)\s*(?:の|という|から|で)?(?:選べる)?(?:プルダウン|リスト|選択肢)",
        t_n,
    )
    if m_list:
        cleaned = _split_chunk(m_list.group(1))
        if len(cleaned) >= 2:
            return cleaned
    if isinstance(cur_items, list) and cur_items:
        joined = "・".join(str(x) for x in cur_items)
        cleaned = _split_chunk(joined)
        if cleaned:
            return cleaned
    return cur_items


def _normalize_calc_expr_str(expr, table):
    """計算式の全角記号を半角(* / + -)へ統一し、各辺の省略列名も一意解決する。"""
    if not expr:
        return expr
    s = nfkc(str(expr)).strip()
    s = s.replace("×", "*").replace("＊", "*").replace("÷", "/").replace("／", "/").replace("＋", "+").replace("−", "-").replace("ー", "-")
    parts = re.split(r"([*/+\-()])", s)
    out = []
    for p in parts:
        st = p.strip()
        if not st or st in ("*", "/", "+", "-", "(", ")") or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", st):
            out.append(st)
        else:
            res = _resolve_col_ref(st, table)
            out.append(res if res else st)
    return "".join(out)


def _expr_referenced_cols(expr, table):
    """計算式文字列の中で参照されている列名・列記号を抽出する。"""
    if not expr:
        return set()
    s = nfkc(str(expr))
    refs = set()
    cols = (table or {}).get("columns") or []
    for c in sorted(cols, key=lambda x: len(str(x.get("name") or "")), reverse=True):
        nm = str(c.get("name") or "").strip()
        cl = str(c.get("col") or "").strip()
        if nm and nm in s:
            refs.add(nm)
            if cl:
                refs.add(cl)
            s = s.replace(nm, " ")
    for m in re.finditer(r"(?<![A-Za-z0-9_$!])([A-Z]{1,3})(?![A-Za-z0-9_(])", s):
        cl = m.group(1)
        refs.add(cl)
        for c in cols:
            if c.get("col") == cl and c.get("name"):
                refs.add(str(c["name"]).strip())
    return refs


def _validate_and_resolve_col_args(shelf, op, table, missing):
    """全棚共通の列名解決ゲート。完全一致 → 一意部分一致 → 解けなければ止める（無い列名で撃たない）。"""
    if not table or not table.get("columns"):
        return
    sh_name = shelf["name"]

    def _add_miss(msg):
        if msg not in missing:
            missing.append(msg)

    for a in shelf["args"]:
        k, t = a["name"], a["type"]
        if k not in op or (sh_name, k) in _SKIP_COL_VALIDATE:
            continue
        if t == "列":
            raw = op[k]
            res = _resolve_col_ref(raw, table)
            if res:
                op[k] = res
            else:
                op.pop(k, None)
                _add_miss(f"表に無い列名（{raw}）")
        elif t == "列[]":
            vals = op[k] if isinstance(op[k], list) else [op[k]]
            resolved_list = []
            bad = []
            for v in vals:
                res = _resolve_col_ref(v, table)
                if res:
                    if res not in resolved_list:
                        resolved_list.append(res)
                else:
                    bad.append(str(v))
            if bad:
                op.pop(k, None)
                _add_miss(f"表に無い列名（{'・'.join(bad)}）")
            elif resolved_list:
                op[k] = resolved_list
    if sh_name == "sort" and isinstance(op.get("cols"), list):
        new_scols, bad_s = [], []
        for spec in op["cols"]:
            s = str(spec)
            neg = s.startswith("-")
            body = s[1:] if neg else s
            res = _resolve_col_ref(body, table)
            if res:
                new_scols.append(("-" if neg else "") + res)
            else:
                bad_s.append(body)
        if bad_s:
            op.pop("cols", None)
            _add_miss(f"表に無い列名（{'・'.join(bad_s)}）")
        elif new_scols:
            op["cols"] = new_scols


def _has_number_meta(table):
    cols = (table or {}).get("columns") or []
    return any(bool(c.get("number")) for c in cols)


def _is_number_col(table, col_ref):
    res = _resolve_col_ref(col_ref, table)
    if not res:
        return False
    for c in (table or {}).get("columns") or []:
        if c.get("name") == res or c.get("col") == res:
            return bool(c.get("number"))
    return False


def _resolve_unique_cols(text, table, number_only=False, exclude=()):
    """文中の省略語（例:「売上」→「売上金額」）から一意に定まる列名を解決する。曖昧なら返さない。"""
    if not table or not table.get("columns"):
        return []
    excl = set(exclude or ())
    cands = []
    for c in table["columns"]:
        nm = str(c.get("name") or "").strip()
        if not nm or nm in excl:
            continue
        if number_only and not c.get("number"):
            continue
        cands.append(nm)
    if not cands:
        return []
    work = nfkc(text)
    for ex in sorted({str(c.get("name") or "").strip() for c in table["columns"] if str(c.get("name") or "").strip()}, key=len, reverse=True):
        if ex in excl or ex in work:
            if ex in excl:
                work = work.replace(ex, " ")
    out = []
    for m in re.finditer(r"[一-龥ァ-ヶA-Za-z0-9]{2,}", work):
        raw_tok = m.group(0)
        tok = re.sub(r"(?:別表|別|毎|列|欄)$", "", raw_tok)
        if len(tok) < 2 or tok in _COL_TOKEN_STOP or tok in excl:
            continue
        hits = [nm for nm in cands if tok in nm]
        if len(hits) == 1 and hits[0] not in out:
            out.append(hits[0])
    return out


def _single_numeric_fallback(table, exclude=()):
    """表の数値列（No/番号/ID 除く）がちょうど1本だけのときだけその列名を返す。"""
    if not table or not _has_number_meta(table):
        return None
    excl = set(exclude or ())
    nums = [
        c["name"] for c in table.get("columns") or []
        if c.get("number") and c.get("name") not in excl
        and not re.fullmatch(r"no\.?|番号|id", str(c.get("name") or "").strip(), re.IGNORECASE)
    ]
    return nums[0] if len(nums) == 1 else None


def _header_groups(table):
    """2段見出し（親・子）の親グループごとの子列リスト（2列以上ある親のみ）を返す。"""
    if not table or not table.get("columns"):
        return {}
    has_num = _has_number_meta(table)
    groups = {}
    for c in table["columns"]:
        nm = str(c.get("name") or "").strip()
        if "・" not in nm:
            continue
        if has_num and not c.get("number"):
            continue
        parent = nm.split("・", 1)[0].strip()
        if parent:
            groups.setdefault(parent, []).append(nm)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def _clean_filter_equals(op, text, table, quoted_vals):
    """フィルタの equals に列名や助詞「が」「は」が残っていれば剥がす。外せなければ削除して止める。"""
    eq = op.get("equals")
    if not isinstance(eq, str):
        return
    eq_s = eq.strip()
    is_quoted = eq_s in quoted_vals
    if not is_quoted:
        cols_all = [str(c.get("name") or "").strip() for c in (table or {}).get("columns") or [] if str(c.get("name") or "").strip()]
        m_ga = re.match(r"^([^\s、。]+?)(?:列)?(?:が|は)(.+)$", eq_s)
        if m_ga:
            lhs, rhs = m_ga.group(1).strip(), m_ga.group(2).strip()
            resolved_col = _resolve_col_ref(lhs, table)
            if resolved_col and rhs:
                if "col" not in op:
                    op["col"] = resolved_col
                eq_s = rhs
            else:
                op.pop("equals", None)
                return
        if op.get("col") and isinstance(op["col"], str):
            col_nm = op["col"].strip()
            if col_nm and eq_s.startswith(col_nm) and len(eq_s) > len(col_nm):
                rest = re.sub(r"^(?:列)?(?:が|は)", "", eq_s[len(col_nm):]).strip()
                if rest:
                    eq_s = rest
        eq_s = re.sub(r"(?:さん|様)$", "", eq_s).strip()
        if (
            not eq_s
            or eq_s in cols_all
            or re.search(r"(?:が|は)", eq_s)
            or re.search(r"以上|以下|未満|より大|より小|より前|より後|以前|以降|を超|超え|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄", eq_s)
            or _DATE_CMP_CUE_RE.search(nfkc(eq_s))
        ):
            op.pop("equals", None)
            return
    op["equals"] = eq_s


def _audit_built_op(shelf, op, text, scan, table, color_hits, missing):
    """守りの決まり（1本化）: 頼みの文のうち使わなかった中身の語・意味破綻が残っていれば撃たずに止める。"""
    sh_name = shelf["name"]
    scan_n = nfkc(scan)

    def _add_miss(msg):
        if msg not in missing:
            missing.append(msg)

    # 1. 文字サイズ変更語があるのに size も size_delta も未反映
    has_size_cue = bool(re.search(
        r"(?<!より)(?:大きく|小さく)|文字サイズ|フォントサイズ|(?<![0-9])サイズを(?:変え|上げ|下げ|大きく|小さく|拡大|縮小)|拡大して|縮小して",
        scan_n,
    ))
    is_dim_size = bool(re.search(r"(?:幅|高さ|列幅|行高|行|列)を(?:大きく|小さく)", scan_n))
    if has_size_cue and (not is_dim_size or re.search(r"文字|フォント", scan_n)):
        if not (sh_name == "width" and not re.search(r"文字|フォント", scan_n)) and op.get("size") is None and op.get("size_delta") is None:
            _add_miss("サイズ（具体的な数値 pt）")

    # 1b. 付ける棚に対して逆の動き（外して・消して・解除・やめて）が含まれていれば誤爆防止で止める
    if sh_name in _ADD_SHELVES and re.search(r"外し|外す|解除|やめ|なくし|無くし|消して|消す|削除|クリア", scan_n):
        _add_miss("逆の操作（外す・消す・解除）の語が含まれています")

    # 2. 未対応の書式装飾語が残っている（api 棚で直接 Sheets API を組む場合を除く）
    if sh_name != "api" and re.search(r"下線|アンダーライン|取り消し線|打ち消し線|取消線|縦書き|斜め文字|文字を回転|テキストを回転", scan_n):
        _add_miss("未対応の書式指示（下線・取り消し線・回転等）")

    # 3. format 棚での取りこぼし・誤爆防止
    if sh_name == "format":
        _m_eq_f = _COND_EQ_THING_RE.search(scan_n)
        _has_eq_col_f = bool(_m_eq_f and (not table or not table.get("columns") or _resolve_col_ref(_m_eq_f.group(1), table)))
        has_row_cond = bool(
            re.search(r"[^\s、。]+?(?:が|は)[^\s、。の]+?の行", scan_n)
            or _has_eq_col_f
            or _two_col_cmp_of(scan_n, table)
            or _col_contains_of(text, table)
            or re.search(r"(?:以上|以下|未満|より大き|より小さ|より前|より後|以前|以降|を超|超え|上回|下回|届か|届いてい?ない|マイナス|負の値|空欄|空白|以外|ではない|になってない|になっている|になってる).{0,8}(?:の行|行を|行に|行全体|のセル|セルを|(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線)[^\s、。のをにはが]{1,12}(?:を|に|は))", scan_n)
            or (_DATE_CMP_CUE_RE.search(scan_n) and re.search(r"の行|行を|行に|行全体|のセル|セルを", scan_n))
        )
        if has_row_cond:
            _add_miss("条件付き書式（cf.add）の条件")
        if re.search(r"固定|フリーズ", scan_n):
            _add_miss("固定（freeze）の指定")
        if re.search(r"並べ替|ソート", scan_n):
            _add_miss("並べ替え（sort）の指定")
        if re.search(r"フィルタ|絞り込", scan_n):
            _add_miss("絞り込み（filter）の指定")
        if "太字" in scan_n and "bold" not in op:
            _add_miss("太字（bold）")
        if re.search(r"斜体|イタリック", scan_n) and "italic" not in op:
            _add_miss("斜体（italic）")
        if re.search(r"中央揃え|中央寄せ|中央に|真ん中に|右揃え|右寄せ|左揃え|左寄せ", scan_n) and "align" not in op:
            _add_miss("配置（align）")
        if "折り返" in scan_n and "wrap" not in op:
            _add_miss("折り返し（wrap）")
        if re.search(r"罫線|外枠", scan_n) and "borders" not in op:
            _add_miss("罫線（borders）")
        if re.search(r"結合|マージ", scan_n) and "merge" not in op:
            _add_miss("結合（merge）")
        if re.search(r"二重線|点線|破線", scan_n):
            _add_miss("罫線の種類（formatは実線のみ）")
        if re.search(r"パーセント|%\s*表示|桁区切|カンマ区切|通貨形式|円マーク|年月日の?形|年月日形式|yyyy|hh:mm|曜日", scan_n, re.IGNORECASE) and "number_format" not in op:
            _add_miss("表示形式（number_format）")
        if color_hits and not op.get("bg") and not op.get("color"):
            _add_miss("色（color/bg）")

    # 3b. cf.add は書式（bg・color・bold）と必要な比較値（value）が欠けたまま撃たない
    if sh_name == "cf.add":
        if not op.get("bg") and not op.get("color") and op.get("bold") is None:
            _add_miss("書式（bg・color・bold）")
        if op.get("when") in ("gt", "ge", "lt", "le", "eq", "ne", "between", "contains", "formula") and op.get("value") in (None, ""):
            _add_miss("value")

    # 4. フィルタ系で条件語が落ちている／条件自体が空
    if sh_name in ("filter.where", "filter.delete", "filter.extract"):
        if (re.search(r"以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|を含|含む|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄", scan_n) or _DATE_CMP_CUE_RE.search(scan_n) or _col_contains_of(text, table)) and not op.get("when"):
            _add_miss("条件（when）")
        if not op.get("when") and op.get("equals") in (None, "") and op.get("value") in (None, ""):
            _add_miss("絞り込み条件（equals/when）")
        if op.get("when") in ("gt", "ge", "lt", "le", "ne", "between", "contains") and op.get("value") in (None, ""):
            _add_miss("value")

    # 5. 式を入れる棚で入れ先の列(at)が式・計算の入力列と同じなら撃たない（自己上書き・循環参照防止）
    if sh_name in _FORMULA_COL_SHELVES and op.get("at"):
        dst_col = op["at"]
        dst_l = _letter_of(table, dst_col) or dst_col
        src_refs = set()
        if sh_name == "calc.col" and op.get("expr"):
            src_refs = _expr_referenced_cols(op["expr"], table)
        else:
            for sk in ("col", "col_a", "col_b", "start_col", "end_col"):
                if op.get(sk):
                    src_refs.add(op[sk])
                    sl = _letter_of(table, op[sk])
                    if sl:
                        src_refs.add(sl)
            if isinstance(op.get("cols"), list):
                for sc in op["cols"]:
                    src_refs.add(sc)
                    sl = _letter_of(table, sc)
                    if sl:
                        src_refs.add(sl)
        if dst_col in src_refs or dst_l in src_refs:
            _add_miss(f"入れ先の列「{dst_col}」が式の入力列と同じため上書き不可")

    # 6. 最終防波堤: 組んだ op の列引数（col・at・by・values・cols 等）や式に表に無い列名が残っていれば撃たない
    if table and table.get("columns"):
        valid_names = {str(c.get("name") or "").strip() for c in table["columns"] if str(c.get("name") or "").strip()}
        valid_letters = {str(c.get("col") or "").strip() for c in table["columns"] if str(c.get("col") or "").strip()}

        def _is_valid_col_val(v, allow_any_letter=False):
            sv = nfkc(str(v or "")).strip()
            if not sv:
                return False
            if sv in valid_names or sv in valid_letters:
                return True
            if allow_any_letter and re.fullmatch(r"[A-Z]{1,3}", sv):
                return True
            return False

        for a in shelf["args"]:
            k, t = a["name"], a["type"]
            if k not in op or (sh_name, k) in _SKIP_COL_VALIDATE:
                continue
            allow_let = k in ("at", "from", "to")
            if t == "列":
                if not _is_valid_col_val(op[k], allow_any_letter=allow_let):
                    _add_miss(f"表に無い列名（{op[k]}）")
            elif t == "列[]":
                vals = op[k] if isinstance(op[k], list) else [op[k]]
                for v in vals:
                    if not _is_valid_col_val(v, allow_any_letter=allow_let):
                        _add_miss(f"表に無い列名（{v}）")
        if sh_name == "sort" and isinstance(op.get("cols"), list):
            for spec in op["cols"]:
                body = str(spec)[1:] if str(spec).startswith("-") else str(spec)
                if not _is_valid_col_val(body):
                    _add_miss(f"表に無い列名（{body}）")
        if sh_name == "calc.col" and op.get("expr"):
            for tok in re.split(r"[*/+\-(),]", re.sub(r"[A-Za-z]+(?=\()", " ", nfkc(str(op["expr"])))):
                st = tok.strip()
                if not st or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", st):
                    continue
                if not _is_valid_col_val(st):
                    _add_miss(f"式に表に無い列名（{st}）")

    # 7. % 列（進捗率・達成率等）に対する 1 超え比較の誤爆防止 ＋ 過半数・全行削除の防止
    if sh_name in _CMP_VALUE_SHELVES:
        cmp_col = op.get("col")
        cmp_num_str = None
        if sh_name == "cf.add" and op.get("when") == "formula" and isinstance(op.get("value"), str):
            m_fm = re.search(r"\$([A-Z]{1,3})[0-9]+\s*(?:>=|<=|<>|>|<|=)\s*(-?[0-9]+(?:\.[0-9]+)?)", op["value"])
            if m_fm:
                col_l = m_fm.group(1)
                cmp_num_str = m_fm.group(2)
                for c_inf in (table or {}).get("columns") or []:
                    if c_inf.get("col") == col_l and c_inf.get("name"):
                        cmp_col = c_inf["name"]
                        break
        elif op.get("when") in ("gt", "ge", "lt", "le", "eq", "ne") and op.get("value") not in (None, ""):
            cmp_num_str = str(op["value"]).replace(",", "").strip()
        if not cmp_col and sh_name == "cf.add" and isinstance(op.get("range"), str) and table:
            m_rg_c = re.match(r"^([A-Z]{1,3})[0-9]+:\1[0-9]+$", op["range"])
            if m_rg_c:
                for c_inf in table.get("columns") or []:
                    if c_inf.get("col") == m_rg_c.group(1) and c_inf.get("name"):
                        cmp_col = c_inf["name"]
                        break
        if cmp_col and _PCT_COL_RE.search(str(cmp_col)) and cmp_num_str is not None:
            try:
                cmp_num = float(cmp_num_str)
                if abs(cmp_num) > 1.0:
                    _add_miss(f"%列「{cmp_col}」を1を超える値（{cmp_num_str}）で比較しているため確認が必要")
            except Exception:
                pass
        if sh_name == "filter.delete" and table and isinstance(table.get("rows"), list) and table["rows"] and op.get("col"):
            cols_l = table.get("columns") or []
            col_idx = next((idx for idx, c_inf in enumerate(cols_l) if c_inf.get("name") == op["col"] or c_inf.get("col") == op["col"]), -1)
            if col_idx >= 0:
                total_r = len(table["rows"])
                tgt_v = op.get("value") if op.get("value") is not None else op.get("equals")
                hits_r = sum(
                    1 for row in table["rows"]
                    if isinstance(row, (list, tuple)) and col_idx < len(row) and _match_row_cond_py(row[col_idx], op.get("when") or "eq", tgt_v)
                )
                if hits_r > 0 and (hits_r == total_r or hits_r * 2 > total_r):
                    _add_miss(f"条件に合う行が過半数（{hits_r}/{total_r}行）のため確認が必要")

    # 8. 守りの逆（頼みに無い手を勝手に足さない）＋ find の疑問文誤爆防止
    t_full_n = nfkc(text)
    if sh_name == "find":
        has_q_word = bool(re.search(r"どんな|何が|何を|何の|何か|なにが|なにを|何が入|何があ|どれ|誰|だれ|いくつ|何件|何人|何行|何列|何個|いくら", t_full_n))
        has_polite_q = bool(re.search(r"ですか|でしょうか|ますか", t_full_n)) and not bool(re.search(r"(?:もらえ|くれ|いただけ|でき|られ)ますか", t_full_n))
        find_txt_n = nfkc(str(op.get("text") or ""))
        if has_q_word or has_polite_q or re.search(r"どんな|何|なに|どれ|どこ|誰|だれ|いくつ", find_txt_n):
            _add_miss("疑問の文のため find で検索しません")
    if sh_name == "seiri":
        if op.get("renumber") and not _OPT_COL_CUES["renumber"].search(t_full_n):
            _add_miss("頼みに無い操作（renumber）が混入しています")
        if op.get("blank_rows") is True and not re.search(r"空行|空白行|空白の行|空いてる行|空いている行|空き行", t_full_n):
            _add_miss("頼みに無い操作（blank_rows）が混入しています")
        if op.get("dedupe") is True and not re.search(r"重複|ダブ|同じ行", t_full_n):
            _add_miss("頼みに無い操作（dedupe）が混入しています")
    if sh_name == "table.new":
        if op.get("number") and not _OPT_COL_CUES["number"].search(t_full_n):
            _add_miss("頼みに無い操作（number）が混入しています")
        if op.get("total") and not _OPT_COL_CUES["total"].search(t_full_n):
            _add_miss("頼みに無い操作（total）が混入しています")
    if sh_name == "sort":
        if (op.get("filter") is True or op.get("where")) and not re.search(r"フィルタ|フィルター|絞り|だけ|のみ", t_full_n):
            _add_miss("頼みに無い操作（filter/where）が混入しています")
    if op.get("all_sheets") is True and not re.search(r"全シート|すべてのシート|全てのシート|ブック全体", t_full_n):
        _add_miss("頼みに無い操作（all_sheets）が混入しています")
    if sh_name == "format":
        if op.get("bold") is True and not re.search(r"太字|太く|ボールド", t_full_n, re.IGNORECASE):
            _add_miss("頼みに無い操作（bold）が混入しています")
        if op.get("italic") is True and not re.search(r"斜体|イタリック", t_full_n, re.IGNORECASE):
            _add_miss("頼みに無い操作（italic）が混入しています")
        if op.get("merge") is True and not re.search(r"結合|マージ", t_full_n, re.IGNORECASE):
            _add_miss("頼みに無い操作（merge）が混入しています")
        if op.get("borders") not in (None, False, "none", "なし") and not re.search(r"罫線|枠線|外枠|格子", t_full_n):
            _add_miss("頼みに無い操作（borders）が混入しています")
    if sh_name == "cols.delete":
        if _COL_CONTENT_DEL_RE.search(scan_n) or _COL_PROP_OBJ_RE.search(scan_n):
            _add_miss("列そのものではなく列の中身の語が含まれているため列削除しません")
        elif re.search(r"列|カラム", scan_n) and not _COL_DIRECT_DEL_RE.search(scan_n):
            _add_miss("列そのものが削除対象ではないため列削除しません")
    if sh_name == "rows.delete":
        if re.search(r"(?:行目|行)の(?!削除|消去|除去)[^\s、。のをにはが]{1,12}を|中身|値だけ|値を|空白|スペース|改行|色|背景|書式|罫線|メモ|コメント|リンク", scan_n):
            _add_miss("行そのものではなく中身の語が含まれているため行削除しません")


_AI_DESTRUCTIVE_SHELVES = frozenset({"rows.delete", "cols.delete", "filter.delete", "clear.values", "clear.all", "sheet.delete"})
_AI_DELETE_CUE_RE = re.compile(r"消|削除|取り除|捨て|クリア|空に|抜[いきく]|削[っりる]|除去|除外|詰め|無く|なく[しす]|減ら|落と")
_AI_SPLITTABLE_RANGE_SHELVES = frozenset({
    "clear.values", "clear.format", "clear.all", "bg.clear",
    "format", "cf.add", "cf.clear",
    "formula.guard", "formula.tovalue", "round", "text.case", "text.affix", "text.clean",
    "note.clear", "link.clear", "checkbox", "protect.add",
})
_A1_PART_RE = re.compile(r"^(?:(?:'(?:[^']|'')+'|[^!',\s]+)!)?(?:[A-Za-z]{1,3}\d*(?::[A-Za-z]{1,3}\d*)?|\d+:\d+)$")


def _expand_disjoint_range_op(op, sh_name, issues):
    """range にカンマ区切りの飛び地（例: 'F5,F8'）があれば、安全な棚だけ 1 範囲ずつの ops に分ける。分けられない棚は止める。"""
    raw_r = op.get("range")
    if not isinstance(raw_r, str) or "," not in raw_r:
        return [op]
    parts = [p.strip() for p in raw_r.split(",")]
    if not parts or any(not p or not _A1_PART_RE.fullmatch(p) for p in parts):
        issues.append(f"棚「{sh_name}」の range に不正な複数範囲（{raw_r}）が含まれています")
        return None
    can_split = sh_name in _AI_SPLITTABLE_RANGE_SHELVES
    if sh_name == "format" and op.get("merge") is not None:
        can_split = False
    if not can_split:
        issues.append(f"棚「{sh_name}」の range にカンマ区切りの複数範囲（{raw_r}）は使えません（1 範囲ずつに分けて指定してください）")
        return None
    if len(parts) > 50:
        issues.append(f"棚「{sh_name}」の飛び地範囲が多すぎます（{len(parts)} か所・上限 50）")
        return None
    out = []
    for p in parts:
        cp = dict(op)
        cp["range"] = p
        out.append(cp)
    return out


def audit_ai_ops(ops, ask, finder, table=None):
    """AI が返した ops を棚と同じ守り（ok 剥ぎ取り・飛び地範囲分割・カタログ検査・_audit_built_op）に通す。
    戻り値: {"ok": bool, "ops": sanitized_ops, "issues": list[str]}
    """
    issues = []
    if not isinstance(ops, list) or not ops:
        return {"ok": False, "ops": [], "issues": ["ops が空または配列ではありません"]}
    cat = finder.cat if finder is not None else None
    ask_s = str(ask or "").strip()
    ask_n = nfkc(ask_s)
    if ask_s and _is_read_only_ask(ask_s):
        return {"ok": False, "ops": [], "issues": ["読むだけの質問のためシートを変更する ops は実行しません"]}

    sanitized = []
    for idx, raw_op in enumerate(ops, 1):
        if not isinstance(raw_op, dict) or not isinstance(raw_op.get("shelf"), str) or not raw_op.get("shelf").strip():
            issues.append(f"{idx} 番目の ops に 'shelf'（棚の名前）がありません")
            continue
        # 守り: AI が勝手に ok=True を付けて承認（guardDelete_ / guardOverwrite_）を素通りするのを防ぐ
        op = {k: v for k, v in raw_op.items() if k != "ok"}
        sh_name = op["shelf"].strip()
        op["shelf"] = sh_name
        if cat is not None:
            if not cat.spec(sh_name):
                near = finder.near(sh_name)
                issues.append(f"棚「{sh_name}」はありません（{idx} 番目）" + (f"（{near}）" if near else ""))
                continue
            msg = cat.check_op(idx, op) or (gas_ws_catalog.EXTRA_CHECKS[sh_name](op) if sh_name in gas_ws_catalog.EXTRA_CHECKS else None)
            if msg:
                issues.append(msg)
                continue
        if ask_s and sh_name in _AI_DESTRUCTIVE_SHELVES and not _AI_DELETE_CUE_RE.search(ask_n):
            issues.append(f"頼みに削除・消去の指示が無いため「{sh_name}」は実行しません")
            continue
        expanded = _expand_disjoint_range_op(op, sh_name, issues)
        if expanded is None:
            continue
        sanitized.extend(expanded)

    if issues or not sanitized or not ask_s or cat is None:
        return {"ok": not issues and bool(sanitized), "ops": sanitized, "issues": issues}

    scan = QUOTE_RE.sub(" ", ask_s)
    scan = re.sub(r"[（(][^）)]*[）)]", " ", scan)
    color_hits = _color_hits(scan)
    scan = _HEX_COLOR_RE.sub(" ", scan)

    all_shelves = {o["shelf"] for o in sanitized}
    multi = len(sanitized) > 1
    # 複数 op のときに別 op が分担して満たし得る使い残し項目
    shared_ok = {
        "サイズ（具体的な数値 pt）": any(o.get("size") is not None or o.get("size_delta") is not None for o in sanitized),
        "太字（bold）": any("bold" in o for o in sanitized),
        "斜体（italic）": any("italic" in o for o in sanitized),
        "配置（align）": any("align" in o for o in sanitized),
        "折り返し（wrap）": any("wrap" in o for o in sanitized),
        "罫線（borders）": any("borders" in o for o in sanitized),
        "結合（merge）": any("merge" in o for o in sanitized),
        "表示形式（number_format）": any("number_format" in o or o["shelf"] in ("format.negred", "date.fix") for o in sanitized),
        "色（color/bg）": any(o.get("bg") or o.get("color") or o["shelf"] in ("cf.add", "banding.add", "sheet.color") for o in sanitized),
        "条件付き書式（cf.add）の条件": "cf.add" in all_shelves,
        "固定（freeze）の指定": "freeze" in all_shelves,
        "並べ替え（sort）の指定": "sort" in all_shelves,
        "絞り込み（filter）の指定": bool(all_shelves & {"filter.on", "filter.where", "filter.delete", "filter.extract", "filter.off"}),
        "逆の操作（外す・消す・解除）の語が含まれています": bool(all_shelves & {"banding.remove", "cf.clear", "validation.clear", "filter.off", "unfreeze", "protect.remove", "group.remove", "chart.delete", "bg.clear", "clear.format", "clear.values", "clear.all"}),
    }

    for idx, op in enumerate(sanitized, 1):
        shelf = cat.by_name.get(op["shelf"])
        if not shelf:
            continue
        op_miss = []
        _audit_built_op(shelf, op, ask_s, scan, table, color_hits, op_miss)
        for m in op_miss:
            if multi and shared_ok.get(m):
                continue
            tag = f"{op['shelf']}: {m}" if multi else m
            if tag not in issues:
                issues.append(tag)

    return {"ok": not issues, "ops": sanitized, "issues": issues}


# ------------------------------------------------------------------ 1 節 → 1 op
def build_op(shelf, text, table=None, sheets=None, cur_sheet=""):
    """棚 1 本と節 1 つから op を組む。返り値 (op, 足りない引数の名前のリスト, 頼みに名指しの場所があったか)"""
    args = {a["name"]: a for a in shelf["args"]}
    op = {"shelf": shelf["name"]}
    quotes = _quotes(text)
    orig_quotes_list = list(quotes)
    orig_quotes = set(quotes)
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
    has_sheet_arg = any(a["type"] == "シート" for a in shelf["args"])
    sheet_hits = []
    scan_n_sh = nfkc(scan)
    for sh_nm in sorted((sheets or []), key=lambda x: len(str(x)), reverse=True):
        if not sh_nm:
            continue
        sn_n = nfkc(str(sh_nm))
        esc_sn = re.escape(sn_n)
        explicit_sh_re = re.compile(rf"(?:シート|タブ)\s*の?\s*[「『]?{esc_sn}[」』]?|{esc_sn}\s*の?\s*(?:シート|タブ)")
        if explicit_sh_re.search(scan_n_sh):
            sheet_hits.append(sh_nm)
            scan_n_sh = explicit_sh_re.sub(" ", scan_n_sh)
            scan = explicit_sh_re.sub(" ", nfkc(scan))
        elif has_sheet_arg and sn_n in scan_n_sh:
            sheet_hits.append(sh_nm)
            scan_n_sh = scan_n_sh.replace(sn_n, " ")
            scan = nfkc(scan).replace(sn_n, " ")
    names = _col_names(scan, table)
    letters = _col_letters(scan)
    explicit_ranges = _all_explicit_ranges(scan)
    explicit_range = explicit_ranges[0] if explicit_ranges else None
    rem_ranges = list(explicit_ranges)
    has_from_to_ranges = args.get("from", {}).get("type") == "範囲" and args.get("to", {}).get("type") == "範囲"
    rows = _rows_of(scan)
    nums = _numbers(scan)
    named = bool(explicit_range or rows or letters or names or sheet_hits or shelf["name"] in ("dedupe", "seiri", "blank.rows.delete"))
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
            elif wanted and shelf["name"] in ("clear.all", "cf.dup") and table and not (shelf["name"] == "cf.dup" and col_pool):   # 列の名指しがある重複はその列だけ
                first_r = table["data"].split("-")[0] if table.get("data") else str(table.get("header_row", 1) + 1)
                last_r = table["data"].split("-")[-1] if table.get("data") else str(table.get("header_row", 1) + 1)
                v = f"{table['first_col']}{first_r}:{table['last_col']}{last_r}"
            elif col_pool and (wanted or not has_col_arg):
                ls = [x for x in ((_letter_of(table, c) or (c if re.fullmatch(r"[A-Z]{1,3}", c) else None)) for c in col_pool) if x]
                v = _col_range(table, ls)
            if v:
                range_given = True
        elif t == "列":
            if not a["req"] and k in _OPT_COL_CUES and not _OPT_COL_CUES[k].search(nfkc(text)):
                pass
            elif shelf["name"] == "calc.col" and k == "at":
                pass
            elif col_pool and not (k in shelf["any"] and any(op.get(x) not in (None, "", []) for x in shelf["any"])):
                v = col_pool.pop(0)
        elif t == "列[]":
            if not a["req"] and k in _OPT_COL_CUES and not _OPT_COL_CUES[k].search(nfkc(text)):
                pass
            elif col_pool:
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
        elif re.search(r"(?:yyyy/mm/dd|2026/11/04|スラッシュ.{0,4}日付|年/月/日|年月日の?形|年月日形式|年月日に)", text, re.IGNORECASE):
            op["number_format"] = "yyyy/mm/dd"
        elif op.get("number_format") == 'm"月"d"日"(ddd)' and re.search(r"年|yyyy", text, re.IGNORECASE):
            op["number_format"] = "yyyy/mm/dd(ddd)"
        elif not op.get("number_format") and re.search(r"パーセント|%\s*表示", text):
            op["number_format"] = "0.0%"
        elif not op.get("number_format") and re.search(r"3桁|桁区切|カンマ", text):
            op["number_format"] = "#,##0"
        if "size" not in op and "size_delta" not in op and not re.search(r"(?:幅|高さ|列幅|行高|行|列)を(?:大きく|小さく)", nfkc(scan)):
            step_sz = 4 if re.search(r"もっと|だいぶ|かなり|ぐっと|大幅に", nfkc(scan)) else 2
            if re.search(r"(?<!より)大きく|拡大して", nfkc(scan)):
                op["size_delta"] = step_sz
            elif re.search(r"(?<!より)小さく|縮小して", nfkc(scan)):
                op["size_delta"] = -step_sz
        if "align" not in op:
            t_al = nfkc(text).strip()
            if re.search(r"(?:^|[\s、,])(?:中央|真ん中)(?:に|へ|にして)?$", t_al):
                op["align"] = "center"
            elif re.search(r"(?:^|[\s、,])右(?:に|へ|にして)?$", t_al):
                op["align"] = "right"
            elif re.search(r"(?:^|[\s、,])左(?:に|へ|にして)?$", t_al):
                op["align"] = "left"
    if shelf["name"] == "validation.list":
        cleaned_items = _clean_validation_items(text, orig_quotes_list, op.get("items"))
        if cleaned_items:
            op["items"] = cleaned_items
    if shelf["name"] in _CMP_VALUE_SHELVES and op.get("when") != "formula":
        _resolve_cmp_value(op, text)
    if shelf["name"] == "cf.add" and op.get("when") != "formula" and table and table.get("first_col") and table.get("last_col"):
        sp_cf = _data_span(table)
        cf_r1 = sp_cf[0] if sp_cf else ((table.get("header_row") or 1) + 1)
        cf_r2 = sp_cf[1] if sp_cf else cf_r1
        two_col_cf = _two_col_cmp_of(text, table)
        col_cont_cf = _col_contains_of(text, table)
        if not re.search(r"のセル|セルを|セルに", text) and _ROW_CF_THING_RE.search(nfkc(text)):
            cond_col_cf = _cond_col_of(scan, table)
            ref_l = (_letter_of(table, cond_col_cf) if cond_col_cf else None) or (_letter_of(table, names[0]) if names else None) or (letters[0] if letters else "")
            if not ref_l:
                u_cf = _resolve_unique_cols(scan, table)
                if u_cf:
                    ref_l = _letter_of(table, u_cf[0]) or ""
            expr = ""
            raw_v_cf = op.get("value")
            norm_v_cf = _normalize_filter_number(raw_v_cf) if raw_v_cf not in (None, "") else None
            num_val = norm_v_cf if norm_v_cf is not None else (str(raw_v_cf).replace(",", "") if raw_v_cf is not None else "")
            if two_col_cf:
                la_cf, lb_cf = _letter_of(table, two_col_cf[0]), _letter_of(table, two_col_cf[2])
                if la_cf and lb_cf:
                    expr = f"=${la_cf}{cf_r1}{two_col_cf[1]}${lb_cf}{cf_r1}"
            if not expr and col_cont_cf:
                cl_cc = _letter_of(table, col_cont_cf[0])
                if cl_cc:
                    escaped_cc = col_cont_cf[1].replace('"', '""')
                    expr = f'=ISNUMBER(SEARCH("{escaped_cc}",${cl_cc}{cf_r1}))'
            comp_cf = _cf_compound_expr(text, table)
            if comp_cf is not None:
                expr = comp_cf[0]
                if not comp_cf[1]:
                    ref_l = ""   # 2 つ目の条件が読めない＝1 つだけで撃たない
            if not expr and ref_l:
                expr = _cf_blank_today_expr(text, ref_l, cf_r1)
            if not expr and ref_l:
                w = op.get("when")
                d_cf_atom = _date_cmp_to_formula_atom(raw_v_cf, table) if (raw_v_cf not in (None, "") and norm_v_cf is None) else None
                if w == "between" and isinstance(raw_v_cf, str) and ".." in raw_v_cf:
                    p1_cf, p2_cf = raw_v_cf.split("..", 1)
                    da1, da2 = _date_cmp_to_formula_atom(p1_cf, table), _date_cmp_to_formula_atom(p2_cf, table)
                    if da1 and da2:
                        expr = f"=AND(ISNUMBER(${ref_l}{cf_r1}),${ref_l}{cf_r1}>={da1},${ref_l}{cf_r1}<={da2})"
                elif d_cf_atom and w in ("gt", "ge", "lt", "le", "eq", "ne"):
                    op_sym_cf = {"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": "=", "ne": "<>"}[w]
                    expr = f"=AND(ISNUMBER(${ref_l}{cf_r1}),${ref_l}{cf_r1}{op_sym_cf}{d_cf_atom})"
                elif w == "ge" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}>={num_val}"
                elif w == "le" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}<={num_val}"
                elif w == "gt" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}>{num_val}"
                elif w == "lt" and num_val != "":
                    expr = f"=${ref_l}{cf_r1}<{num_val}"
                elif w == "ne" and raw_v_cf not in (None, ""):
                    if norm_v_cf is not None:
                        expr = f"=${ref_l}{cf_r1}<>{norm_v_cf}"
                    else:
                        escaped_v = str(raw_v_cf).replace('"', '""')
                        expr = f'=${ref_l}{cf_r1}<>"{escaped_v}"'
                elif re.search(r"マイナス|負の値", text):
                    expr = f"=${ref_l}{cf_r1}<0"
                elif re.search(r"([0-9][0-9,\.]*%?[万億]?)(?:になっていない|になってない|ではない|でない|じゃない|以外)", nfkc(text)):
                    m_not = re.search(r"([0-9][0-9,\.]*%?[万億]?)(?:になっていない|になってない|ではない|でない|じゃない|以外)", nfkc(text))
                    nv_not = _normalize_filter_number(m_not.group(1)) or m_not.group(1)
                    expr = f"=${ref_l}{cf_r1}<>{nv_not}"
                elif w == "contains" and raw_v_cf not in (None, ""):
                    escaped_v = str(raw_v_cf).replace('"', '""')
                    expr = f'=ISNUMBER(SEARCH("{escaped_v}",${ref_l}{cf_r1}))'
                elif w == "eq" and raw_v_cf not in (None, ""):
                    if norm_v_cf is not None:
                        expr = f"=${ref_l}{cf_r1}={norm_v_cf}"
                    else:
                        escaped_v = str(raw_v_cf).replace('"', '""')
                        expr = f'=${ref_l}{cf_r1}="{escaped_v}"'
                elif not w:
                    m_eq_row = _COND_EQ_THING_RE.search(nfkc(text))
                    if m_eq_row:
                        rv_eq = m_eq_row.group(2).strip()
                        nv_eq = _normalize_filter_number(rv_eq)
                        if nv_eq is not None:
                            expr = f"=${ref_l}{cf_r1}={nv_eq}"
                        else:
                            escaped_v = rv_eq.replace('"', '""')
                            expr = f'=${ref_l}{cf_r1}="{escaped_v}"'
                    elif raw_v_cf not in (None, ""):
                        escaped_v = str(raw_v_cf).replace('"', '""')
                        expr = f'=ISNUMBER(SEARCH("{escaped_v}",${ref_l}{cf_r1}))'
            elif not expr and re.search(r"欠席|完了|未完了|終了", text):
                kw_cf = "欠席" if "欠席" in text else ("未完了" if "未完了" in text else ("完了" if "完了" in text else "終了"))
                expr = f'=COUNTIF(${table["first_col"]}{cf_r1}:${table["last_col"]}{cf_r1},"*{kw_cf}*")>0'
            if expr:
                op["range"] = f"{table['first_col']}{cf_r1}:{table['last_col']}{cf_r2}"
                op["when"] = "formula"
                op["value"] = expr
                named = True
        elif two_col_cf:
            la_cf, lb_cf = _letter_of(table, two_col_cf[0]), _letter_of(table, two_col_cf[2])
            if la_cf and lb_cf:
                op["range"] = f"{la_cf}{cf_r1}:{la_cf}{cf_r2}"
                op["when"] = "formula"
                op["value"] = f"=${la_cf}{cf_r1}{two_col_cf[1]}${lb_cf}{cf_r1}"
                named = True
        elif col_cont_cf and op.get("when") in (None, "contains") and op.get("value") in (None, ""):
            cl_cc = _letter_of(table, col_cont_cf[0])
            if cl_cc:
                op["range"] = f"{cl_cc}{cf_r1}:{cl_cc}{cf_r2}"
            op["when"] = "contains"
            op["value"] = col_cont_cf[1]
            named = True
        if re.search(r"赤字|赤い文字|文字を赤", text) and op.get("bg") == "赤" and not re.search(r"背景|塗", text):
            op["color"] = op.pop("bg")   # 「〜の行を赤字に」は文字の色
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
    extra_missing = []
    if shelf["name"] == "sort":
        sort_pairs = []
        nfkc_t = nfkc(text)
        _desc_pat = r"(?:大きい|多い|高い|新しい|遅い)(?:順|ものから|方から|ほうから|のから)|降順|逆順"
        _asc_pat = r"(?:小さい|少ない|低い|古い|若い)(?:順|ものから|方から|ほうから|のから)|昇順|五十音順|あいうえお順"
        # 「部署ごと、同部署内は社員番号の昇順」「部署ごとにかためて…社員番号の若い順」の 1 列目（ごと）を拾う
        m_grp = re.search(r"([^\s、,の]{1,16})ごと(?:[、,]|に?(?:かためて)?並べ)", nfkc_t)
        if m_grp:
            raw_g = m_grp.group(1).strip()
            col_g = _resolve_col_ref(raw_g, table)
            if col_g:
                sort_pairs.append(col_g)
            else:
                extra_missing.append(f"表に無い列名（{raw_g}）")
        for sm in re.finditer(
            r"(?:その中で\s*|同じ[^\s、,。]{1,12}の中は\s*|同[^\s、,。]{1,12}内は\s*)?([^\s、,のがは]{1,16})(?:の|が)(?:(" + _desc_pat + r")|(" + _asc_pat + r"))",
            nfkc_t,
        ):
            raw_c = sm.group(1).strip()
            col_c = _resolve_col_ref(raw_c, table)
            if not col_c:
                extra_missing.append(f"表に無い列名（{raw_c}）")
                continue
            is_desc = bool(sm.group(2))
            spec = ("-" if is_desc else "") + col_c
            if spec not in sort_pairs and col_c not in sort_pairs:
                sort_pairs.append(spec)
        if len(sort_pairs) >= 2:
            op["cols"] = sort_pairs
            op.pop("col", None)
            op.pop("desc", None)
            named = True
        elif "desc" not in op:
            if re.search(_desc_pat, nfkc_t):
                op["desc"] = True
            elif re.search(_asc_pat, nfkc_t):
                op["desc"] = False
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
    if shelf["name"] == "freeze":
        if "rows" not in op and table and table.get("header_row") and re.search(r"見出し|ヘッダ", text):
            op["rows"] = int(table["header_row"]) + max(1, int(table.get("header_rows") or 1)) - 1
        t_fz = nfkc(text)
        fz_cols = 0
        max_tbl_cols = max(
            (_col_let_to_num(str(c.get("col") or "")) for c in (table or {}).get("columns") or [] if re.fullmatch(r"[A-Z]{1,3}", str(c.get("col") or ""))),
            default=26,
        )
        for m_fc in re.finditer(r"(?<![A-Za-z0-9])([A-Z]{1,2}(?:\s*列?\s*(?:[・、,〜~～\-]|と|から)\s*[A-Z]{1,2})*)\s*列", t_fz):
            for tok in re.findall(r"[A-Z]{1,2}", m_fc.group(1)):
                if len(tok) == 1:
                    fz_cols = max(fz_cols, _col_let_to_num(tok))
                else:
                    res_fc = _resolve_col_ref(tok, table)
                    if res_fc:
                        res_l = _letter_of(table, res_fc)
                        if res_l:
                            fz_cols = max(fz_cols, _col_let_to_num(res_l))
                    else:
                        n_fc = _col_let_to_num(tok)
                        if n_fc <= max_tbl_cols:
                            fz_cols = max(fz_cols, n_fc)
        for m_fn in re.finditer(r"(?:左(?:から)?|先頭(?:から)?|最初(?:の)?)\s*([0-9]+)\s*列|([0-9]+)\s*列(?:目?(?:まで)?(?:固定|フリーズ|動かない)|を固定)", t_fz):
            nv_f = int(m_fn.group(1) or m_fn.group(2))
            if nv_f > 0:
                fz_cols = max(fz_cols, nv_f)
        # 列名で名指し（「氏名の列まで固定」「商品名列まで」）→ その列の位置まで
        for cn_fz in sorted((str(c.get("name") or "") for c in (table or {}).get("columns") or []), key=len, reverse=True):
            if cn_fz and re.search(re.escape(nfkc(cn_fz)) + r"(?:の)?(?:列|欄)", t_fz):
                l_fz = _letter_of(table, cn_fz)
                if l_fz:
                    fz_cols = max(fz_cols, _col_let_to_num(l_fz))
        if fz_cols > 0:
            op["cols"] = fz_cols
    if shelf["name"] == "calc.diff":
        dc = _calc_diff_cols_of(text, table)
        if dc:
            op["col_a"], op["col_b"] = dc[0], dc[1]
            named = True
        else:
            for dk in ("col_a", "col_b"):
                if isinstance(op.get(dk), str):
                    res_d = _resolve_col_ref(op[dk], table)
                    if res_d:
                        op[dk] = res_d
    if shelf["name"] == "calc.col":
        t_nfkc = nfkc(text)
        tbl_cols_sorted = sorted(
            [str(c.get("name") or "").strip() for c in (table or {}).get("columns") or [] if str(c.get("name") or "").strip()],
            key=len,
            reverse=True,
        )
        has_at_cue = bool(re.search(r"(?:列|欄)[にへ]", t_nfkc))
        if not has_at_cue:
            op.pop("at", None)
        elif "at" not in op or _resolve_col_ref(op.get("at"), table) is None:
            op.pop("at", None)
            for cn in tbl_cols_sorted:
                if re.search(re.escape(nfkc(cn)) + r"の?(?:列|欄)[にへ]", t_nfkc):
                    op["at"] = cn
                    break
            if "at" not in op:
                m_at_col = re.search(r"([^\s、,。をにのがとてで]{1,20}?)の?(?:列|欄)[にへ]", t_nfkc)
                if m_at_col:
                    raw_at = m_at_col.group(1).strip()
                    res_at = _resolve_col_ref(raw_at, table)
                    if res_at:
                        op["at"] = res_at
                    elif not re.search(r"足し|追加|作", t_nfkc):
                        op["at"] = raw_at
        d_shift = _date_shift_of(text, table) or _multi_col_agg_of(text, table)
        if d_shift and "expr" not in op:
            op["expr"], op["name"] = d_shift
        if "expr" not in op:
            ext_expr = _extract_calc_expr(text, table)
            if ext_expr:
                op["expr"] = ext_expr
        if op.get("expr"):
            op["expr"] = _normalize_calc_expr_str(op["expr"], table)
        if "name" not in op and "at" in op:
            op["name"] = op["at"]
        if "name" not in op and op.get("expr"):
            m_after = re.search(r"(?:(?:掛け|かけ|足[しす]|た[しす]|引[いけく]|ひ[いけく]|割[っりる]|わ[っりる]|乗算|加算|減算|除算)(?:て|た|算)?|[×*＊÷/／＋+−\-][^\s、,。をの]{1,20}?で)\s*(.+)$", t_nfkc)
            if m_after:
                after_op = m_after.group(1)
                m_dest = re.search(r"([^\s、,。をの]{1,20}?)(?:の列|列|の欄|欄)?(?:を(?:出し|求め|計算|足し|追加|作|入れ)|に(?:出し|入れ|して))", after_op)
                cand_nm = m_dest.group(1).strip() if m_dest else ""
                if cand_nm in ("数式", "式", "計算式", "計算結果", "結果", "値"):
                    after_cols = _col_names(after_op, table)
                    cand_nm = after_cols[-1] if after_cols else ""
                elif cand_nm:
                    # 既存列に一意解決できるなら（新規追加明示でなければ）既存列名へ正規化
                    res_dest = _resolve_col_ref(cand_nm, table)
                    if res_dest and not re.search(r"足し|追加|作", after_op):
                        cand_nm = res_dest
                if not cand_nm:
                    after_cols = _col_names(after_op, table)
                    if after_cols:
                        cand_nm = after_cols[-1]
                if cand_nm:
                    op["name"] = cand_nm
                    if cand_nm in tbl_cols_sorted and "at" not in op and not re.search(r"足し|追加|作", after_op):
                        op["at"] = cand_nm
        if "name" in op and isinstance(op["name"], str):
            cleaned_cnm = _clean_calc_col_name(op["name"])
            if cleaned_cnm:
                op["name"] = cleaned_cnm
            else:
                op.pop("name", None)
        if op.get("expr") and op.get("name"):
            named = True
    if shelf["name"] in ("summary", "pivot.new"):
        if shelf["name"] == "summary" and isinstance(op.get("by"), str):
            res_by = _resolve_col_ref(op["by"], table)
            if res_by:
                op["by"] = res_by
            else:
                extra_missing.append(f"表に無い列名（{op['by']}）")
                op.pop("by", None)
        if shelf["name"] == "pivot.new" and isinstance(op.get("rows"), list) and isinstance(op.get("cols"), list):
            dedup_cols = [c for c in op["cols"] if c not in op["rows"]]
            if dedup_cols:
                op["cols"] = dedup_cols
            else:
                op.pop("cols", None)
        group_cols = set()
        if shelf["name"] == "summary" and op.get("by"):
            group_cols.add(op["by"])
        if shelf["name"] == "pivot.new":
            for gk in ("rows", "cols"):
                if isinstance(op.get(gk), list):
                    group_cols.update(op[gk])
        if op.get("func") != "count":
            cur_vals = list(op.get("values") or []) if isinstance(op.get("values"), list) else ([op["values"]] if op.get("values") else [])
            filtered_vals = [v for v in cur_vals if v not in group_cols]
            if table and _has_number_meta(table):
                filtered_vals = [v for v in filtered_vals if _is_number_col(table, v)]
            if not filtered_vals and table:
                resolved_nums = _resolve_unique_cols(scan, table, number_only=_has_number_meta(table), exclude=group_cols)
                if resolved_nums:
                    filtered_vals = resolved_nums
                else:
                    fb_num = _single_numeric_fallback(table, exclude=group_cols)
                    if fb_num:
                        filtered_vals = [fb_num]
            if filtered_vals:
                op["values"] = filtered_vals
            else:
                op.pop("values", None)
        elif not op.get("values") and group_cols:
            op["values"] = [next(iter(group_cols))]
    if shelf["name"] == "chart.new" and not op.get("edit") and not explicit_range and table:
        chart_cols = list(names) + [x for x in letters if x not in [_letter_of(table, n) for n in names]]
        for uc in _resolve_unique_cols(scan, table, number_only=False, exclude=chart_cols):
            if uc not in chart_cols:
                chart_cols.append(uc)
        h_groups_ch = _header_groups(table)
        is_two_tier_ch = int(table.get("header_rows") or 1) >= 2 or bool(h_groups_ch)
        if not chart_cols and is_two_tier_ch and re.search(r"推移|月別|期別|折れ線", text):
            first_lbl = next((c["name"] for c in table.get("columns") or [] if c.get("name") and not c.get("number")), None)
            if first_lbl:
                chart_cols.append(first_lbl)
        if chart_cols:
            has_num_meta = _has_number_meta(table)
            label_cols, num_cols = [], []
            for cc in chart_cols:
                if has_num_meta and _is_number_col(table, cc):
                    num_cols.append(cc)
                else:
                    label_cols.append(cc)
            used_group_series = False
            if has_num_meta and not num_cols:
                res_nums = _resolve_unique_cols(scan, table, number_only=True, exclude=chart_cols)
                if res_nums:
                    num_cols.extend(res_nums)
                elif is_two_tier_ch and h_groups_ch:
                    grp_sub_cols = [
                        cn for g_list in h_groups_ch.values() for cn in g_list
                        if cn not in chart_cols and not re.search(r"(?:年計|合計|総計|小計)$", cn)
                    ]
                    if len(grp_sub_cols) >= 2:
                        num_cols.extend(grp_sub_cols)
                        used_group_series = True
                else:
                    fb_c = _single_numeric_fallback(table, exclude=chart_cols)
                    if fb_c:
                        num_cols.append(fb_c)
            if has_num_meta and not num_cols:
                op.pop("range", None)
                extra_missing.append("グラフにする数値の列")
            else:
                ordered_cols = label_cols + num_cols if has_num_meta else chart_cols
                ordered_ls = []
                for oc in ordered_cols:
                    ol = _letter_of(table, oc) or (oc if re.fullmatch(r"[A-Z]{1,3}", str(oc)) else None)
                    if ol and ol not in ordered_ls:
                        ordered_ls.append(ol)
                sp_ch = _data_span(table)
                if ordered_ls and sp_ch:
                    ch_r1 = int(table.get("header_row") or sp_ch[0]) + max(1, int(table.get("header_rows") or 1)) - 1
                    ch_r2 = sp_ch[1]
                    if len(ordered_ls) == 1:
                        op["range"] = f"{ordered_ls[0]}{ch_r1}:{ordered_ls[0]}{ch_r2}"
                    else:
                        col_ns = [_col_num(x) for x in ordered_ls]
                        is_contig_asc = all(col_ns[i] - col_ns[i - 1] == 1 for i in range(1, len(col_ns)))
                        if is_contig_asc:
                            op["range"] = f"{ordered_ls[0]}{ch_r1}:{ordered_ls[-1]}{ch_r2}"
                        else:
                            op["range"] = ",".join(f"{x}{ch_r1}:{x}{ch_r2}" for x in ordered_ls)
                    if used_group_series and len(label_cols) == 1 and len(num_cols) >= 2 and re.search(r"推移|月別|折れ線|ごと|別", text):
                        op["transpose"] = True
    if shelf["name"] == "seiri":
        if not _OPT_COL_CUES["renumber"].search(nfkc(text)):
            op.pop("renumber", None)
        elif op.get("col") and "renumber" not in op and not op.get("trim") and not op.get("halfwidth"):
            op["renumber"] = op.pop("col")
    if shelf["name"] in ("filter.where", "filter.delete", "filter.extract"):
        if shelf["name"] == "filter.extract" and op.get("into") == "別":
            op.pop("into", None)
        col_cont_f = _col_contains_of(text, table)
        if col_cont_f and op.get("when") in (None, "contains"):
            op["col"] = col_cont_f[0]
            op["when"] = "contains"
            op["value"] = col_cont_f[1]
            op.pop("equals", None)
        if op.get("when") == "contains":
            op.pop("equals", None)
        if "when" in op and "equals" in op and isinstance(op["equals"], str):
            if re.search(r"以上|以下|未満|より|超|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄|以前|以降", op["equals"]) or _DATE_CMP_CUE_RE.search(nfkc(op["equals"])):
                op.pop("equals", None)
        if shelf["name"] == "filter.where":
            has_cmp_cue = ("when" in op) or bool(col_cont_f) or bool(re.search(r"以上|以下|未満|より|を超?|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄|以前|以降", text)) or bool(_DATE_CMP_CUE_RE.search(nfkc(text)))
            if not has_cmp_cue and "equals" not in op:
                m_gen = re.search(r"(?:が|は)[『「]?([^』」\sの、。]+?)[』」]?の[^\s、。のをにはが]{1,12}(?:だけ|のみ)", text.strip())
                if m_gen:
                    op["equals"] = m_gen.group(1).strip()
                else:
                    m_name = re.search(r"^(.+?)(?:さん|様)?の行だけ", text.strip())
                    if m_name:
                        op["equals"] = m_name.group(1).strip()
        if "equals" in op:
            _clean_filter_equals(op, text, table, orig_quotes)
        if op.get("when") == "ne":
            op.pop("equals", None)
        _resolve_cmp_value(op, text)
        if "col" not in op and table:
            cols = [c["name"] for c in table.get("columns", [])]
            eq = op.get("equals", "")
            val_s = str(op.get("value") or "")
            is_date_val = bool(val_s and (".." in val_s or _parse_cmp_date_str(val_s)))
            date_cands = [c["name"] for c in table.get("columns", []) if c.get("name") and not c.get("number") and re.search(r"日付|日$|date", str(c["name"]), re.IGNORECASE)]
            if is_date_val and len(date_cands) == 1:
                op["col"] = date_cands[0]
            elif any(k in cols for k in ("勘定科目", "科目")) and (any(x in eq for x in ("費", "料", "税", "手当")) or "旅費" in eq):
                op["col"] = "勘定科目" if "勘定科目" in cols else "科目"
            elif any(k in cols for k in ("氏名", "名前", "社員名", "担当者", "担当")) and (" " in eq or "　" in eq or any(x in text for x in ("さん", "様", "氏"))):
                op["col"] = next(k for k in ("氏名", "名前", "社員名", "担当者", "担当") if k in cols)
            elif cols:
                text_cols = [c["name"] for c in table.get("columns", []) if not c.get("number")]
                if text_cols:
                    op["col"] = text_cols[0]
        if shelf["name"] == "filter.delete" and op.get("col") and (op.get("when") or op.get("equals") is not None or op.get("value") is not None):
            named = True
    if shelf["name"] == "cols.delete" and not op.get("cols") and table:
        u_del = _resolve_unique_cols(scan, table)
        if u_del:
            op["cols"] = u_del
            named = True
    if shelf["name"] == "date.fix":
        if "format" not in op:
            if re.search(r"yyyy-mm-dd", text, re.IGNORECASE):
                op["format"] = "yyyy-mm-dd"
            elif re.search(r"yyyy/mm/dd|年/月/日|年月日の?形|年月日形式", text, re.IGNORECASE):
                op["format"] = "yyyy/mm/dd"
        if "col" not in op and "range" not in op and table:
            d_cands = [c["name"] for c in table.get("columns") or [] if c.get("name") and not c.get("number") and re.search(r"日付|日$|date", str(c["name"]), re.IGNORECASE)]
            if len(d_cands) == 1:
                op["col"] = d_cands[0]
                named = True
    if shelf["name"] == "phone.fix":
        if "col" not in op and "range" not in op and table:
            p_cands = [c["name"] for c in table.get("columns") or [] if c.get("name") and re.search(r"電話|携帯|tel|phone", str(c["name"]), re.IGNORECASE)]
            if len(p_cands) == 1:
                op["col"] = p_cands[0]
                named = True
    if shelf["name"] == "width":
        if "col" in op and "width" not in op and "auto" not in op and re.search(r"(?:自動|中身に合|オートフィット)", text):
            op["auto"] = [op.pop("col")]
        elif not any(k in op for k in ("auto", "cols", "col", "rows")) and not op.get("all_sheets") and re.search(r"(?:自動|中身に合|オートフィット|ちょうどよく|見切れ)", text):
            if table and table.get("columns"):
                cols_auto = [c["col"] for c in table["columns"] if c.get("col")]
                if cols_auto:
                    op["auto"] = cols_auto
                    named = True
    missing = []
    _validate_and_resolve_col_args(shelf, op, table, missing)
    for k in (a["name"] for a in shelf["args"] if a["req"]):
        if op.get(k) in (None, "", []) and k not in missing:
            missing.append(k)
    for em in extra_missing:
        if em not in missing:
            missing.append(em)
    if shelf["any"] and not any(op.get(k) not in (None, "", []) for k in shelf["any"]):
        missing.append("・".join(shelf["any"]) + " のどれか")
    what = [a["name"] for a in shelf["args"] if not a["req"] and a["type"] not in _LOCATOR_TYPES and a["name"] not in shelf["any"]]
    bare_ok = any(not any(k in ex for k in what) for _, ex in shelf["examples"])   # 札の例に「何をするか」なしで撃つ例があれば、なしでも撃てる棚
    if not missing and not bare_ok and len(what) >= WHAT_MIN and not any(k in op for k in what) and not any(a["req"] and a["type"] not in _LOCATOR_TYPES for a in shelf["args"]):
        missing.append("何をするか（" + "・".join(what[:6]) + " …）")
    _audit_built_op(shelf, op, text, scan, table, color_hits, missing)
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
        if re.search(r"(?:が|は|の).{0,16}(?:行|データ|明細|レコード|案件|商品)|以上|以下|未満|超え?|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行", clause):
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


_READ_ONLY_MUTATE_RE = re.compile(
    r"並べて|並べ替|ソート|絞り込|フィルタ|抽出|消して|消す|削除|取り除|捨て|外して|外す|解除|塗|"
    r"色[をに]?付|色[をに]?つ|色[をに]?変|色にして|太字|斜体|罫線|固定|フリーズ|非表示|隠して|再表示|"
    r"追加|足して|作って|作成|入れて|入力|書[きくい]|書き換|置換|直して|そろえて|揃えて|整えて|変換|"
    r"グラフ|ピボット|集計表|別シート|コピー|複製|移動|変更|保護|結合|幅を|高さを|広げて|狭めて|"
    r"大きくして|小さくして|プルダウン|リストを作|ハイライト|目立たせ|"
    r"だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|にして(?:くれ|もらえ|くださ|いただ)?[?？]?$|(?<!教え)(?<!見せ)(?:てくれ|てもらえ|ていただ)|てほしい|て欲しい|お願い"
)
_READ_ONLY_QUERY_RE = re.compile(
    r"[?？]|どこ|どれ|だれ|誰|どんな|何が|何を|何が入|いくつ|何件|何人|何行|何列|何個|何社|何名|いくら|何円|何%|"
    r"ありますか|あるか|いるか|ですか|ますか|でしょうか|どうなって|教えて|知りたい|確認したい|"
    r"構成を|概要を|中身を|一覧を|おかしな|おかしい|異常|エラー|不備|ミス|間違|崩れ"
)


def _chart_summary_ops(op, clause, table):
    """明細表に対する「〜ごとの／〜別の」グラフ依頼を summary → chart.new の 2 手へ変換する。該当しなければ None。"""
    if not table or not table.get("columns") or op.get("edit") or op.get("transpose"):
        return None
    if _all_explicit_ranges(clause):
        return None
    c_n = nfkc(clause)
    if not re.search(r"(?:ごと(?:に|の)|別(?:に|で|の))", c_n):
        return None
    # 軸列（by）を解決
    by_col = None
    m_by = re.search(r"([^\s・、をにのはが]{1,16}?)(?:ごと(?:に|の)|別(?:に|で|の))", c_n)
    if m_by:
        by_col = _resolve_col_ref(m_by.group(1).strip(), table)
    if not by_col:
        return None
    # 値列（values）を解決
    func = "count" if re.search(r"件数|人数", c_n) else ("avg" if "平均" in c_n else None)
    val_cols = []
    if func == "count":
        val_cols = [by_col]
    else:
        for nm in _col_names(clause, table):
            if nm != by_col and (not _has_number_meta(table) or _is_number_col(table, nm)) and nm not in val_cols:
                val_cols.append(nm)
        if not val_cols:
            for uc in _resolve_unique_cols(clause, table, number_only=_has_number_meta(table), exclude=(by_col,)):
                if uc not in val_cols:
                    val_cols.append(uc)
        if not val_cols:
            fb = _single_numeric_fallback(table, exclude=(by_col,))
            if fb:
                val_cols.append(fb)
    if not val_cols:
        return None
    into_name = f"集計_{by_col}別"
    sum_op = {"shelf": "summary", "by": by_col, "values": val_cols, "into": into_name, "ok": True}
    if func:
        sum_op["func"] = func
    if op.get("sheet"):
        sum_op["sheet"] = op["sheet"]
    ch_op = {"shelf": "chart.new", "type": op.get("type") or "column", "range": into_name}
    for k in ("title", "at", "sheet"):
        if op.get(k) is not None:
            ch_op[k] = op[k]
    return [sum_op, ch_op]


_AMBIG_TIDY_CUE_RE = re.compile(r"見やすく|きれいに|綺麗に|整えて|整え|体裁|見栄え")
_SPECIFIC_TIDY_RE = re.compile(
    r"見た目だけ|書式だけ|デザインだけ|中身は|値は|掃除なし|罫線|列幅|幅を|色|背景|太字|斜体|フォント|"
    r"空行|空白|スペース|全角|半角|重複|ダブ|和暦|日付|電話|ハイフン|固定|フィルタ|並べ|ソート|グラフ|集計|合計|平均|削除|消して"
)


def _ambiguous_tidy_choices(ask, ops, kind=""):
    """「見やすく整えて」のような曖昧な整え依頼なら 3 択候補を返す。具体的指示や VAGUE 語があれば None。"""
    if kind == "doc":
        return None
    t = nfkc(ask or "").strip()
    if not t or VAGUE.search(t) or _all_explicit_ranges(t):
        return None
    if not _AMBIG_TIDY_CUE_RE.search(t) or _SPECIFIC_TIDY_RE.search(t):
        return None
    is_bare_tidy = (
        len(ops) == 1
        and ops[0].get("shelf") in ("tidy", "seiri")
        and not any(k in ops[0] for k in ("range", "col", "blank_rows", "dedupe", "halfwidth", "trim", "numbers", "dates", "renumber"))
    )
    if not is_bare_tidy and ops:
        return None
    sh = ops[0].get("sheet") if (len(ops) == 1 and ops[0].get("sheet")) else None

    def _with_sh(op_list):
        if not sh:
            return op_list
        return [dict(o, sheet=sh) for o in op_list]

    return [
        {"label": "見た目だけ整える", "desc": "見出し・罫線・桁区切り・列幅だけ（値は触らない）", "ops": _with_sh([{"shelf": "tidy"}])},
        {"label": "見た目＋データの掃除", "desc": "空行削除・前後空白・全角半角の統一＋見た目", "ops": _with_sh([{"shelf": "seiri"}, {"shelf": "tidy"}])},
        {"label": "重複削除＋掃除＋見た目", "desc": "重複行の削除も含めて表を丸ごと整える", "ops": _with_sh([{"shelf": "dedupe", "ok": True}, {"shelf": "seiri"}, {"shelf": "tidy"}])},
    ]


def _is_read_only_ask(ask):
    """棚が撃てなかった依頼のうち、変更動詞が無く問いの形になっている「読むだけ」かを判定する。"""
    t = nfkc(ask or "").strip()
    if not t:
        return False
    if _READ_ONLY_MUTATE_RE.search(t):
        return False
    return bool(_READ_ONLY_QUERY_RE.search(t))


# ------------------------------------------------------------------ 頼み → ops
def plan(ask, finder, kind="", table=None, sheets=None, cur_sheet="", last_scope=None):
    cur_sheet = cur_sheet or (sheets[0] if sheets else "")
    p = Plan()
    ask = (ask or "").strip()
    if not ask:
        p.reasons.append("頼みの文が空です")
        return p
    q_all = gas_ws_find.norm(ask, finder.syn)
    q_guide = gas_ws_find.norm(_mask_col_names(ask, table), finder.syn)   # 列名（「メール」「画像」等）で案内を出さない
    p.guide = [text for nwords, text in finder._guide_norm if any(nw in q_guide for nw in nwords)]
    raw_cl = clauses(ask) or [nfkc(ask)]
    cl = []
    for _c in raw_cl:
        # 1節に「合計と平均（／最大／最小）」の両方を表の下へ足す頼みがあるときは total + stat.row へ展開
        _m_ts = re.search(r"合計(?:行)?と(平均|最大値?|最小値?)(?:の?行)?", _c)
        if _m_ts and re.search(r"一番下|表の下|下に|行を?(?:足|追加|入れ)|足して|追加して|入れて", _c) and not re.search(r"ごと|別に|別シート|小計", _c):
            _stat_w = _m_ts.group(1)
            cl.append(_c.replace(_m_ts.group(0), "合計行"))
            cl.append(_c.replace(_m_ts.group(0), _stat_w + "の行"))
        else:
            cl.append(_c)
    fatal_err = False
    if VAGUE.search(nfkc(ask)):
        p.reasons.append("どこを指すかが人にしか分かりません（" + VAGUE.search(nfkc(ask)).group(0) + "）")
        fatal_err = True
    # 直前の節が棚に当たったが引数不足（missing）のとき、続く補足文（「赤にしてください」等）を合流させるための状態
    last_incomplete = None
    for c_raw in cl:
        c = _expand_selection_pronouns(c_raw, last_scope)
        # 2 段見出しの親グループ小計・合計列（「上期と下期の小計の列を足して」「下期の小計を列として追加して」等）
        if kind != "doc" and table and re.search(r"(?:小計|合計)(?:の?列|列)?(?:を(?:列として)?)?(?:足|追加|作|入れ)", c) and not re.search(r"一番下|最後の行|末尾の行|表の下|合計行|別シート", c):
            hg_map = _header_groups(table)
            if hg_map:
                c_nfkc_g = nfkc(c)
                hit_grps = sorted([g for g in hg_map if nfkc(g) in c_nfkc_g], key=lambda g: c_nfkc_g.find(nfkc(g)))
                if hit_grps:
                    suf_g = "小計" if "小計" in c else "合計"
                    for g_nm in hit_grps:
                        p.ops.append({"shelf": "calc.col", "name": g_nm + suf_g, "expr": "+".join(hg_map[g_nm])})
                    last_incomplete = None
                    continue
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
        # 型ベースの優先調停（スコア0でも明確な型の依頼を救済する）
        boost_name = ""
        top_base = scored[0][0] if scored else gas_ws_find.WEAK_SCORE
        cand_names = {x[2]["name"] for x in scored}
        if kind != "doc":
            has_fmt_cue = bool(re.search(r"表示形式|曜日|hh:mm|yyyy|mm/dd|時刻.{0,4}2桁|09:00|カンマ|桁区切|パーセント|円マーク|円表示|¥|通貨形式|数値\s*[（(]?標準|標準形式|標準に戻|年月日の?形|年月日形式|年月日に|日付の?形", c, re.IGNORECASE))
            has_cols_hide_cue = bool(
                re.search(r"(?:列|カラム).*(?:非表示|隠|見えなく)", c)
                and not re.search(r"グリッド線|枠線|目盛り線|シート|タブ|再表示", c)
            )
            has_rows_hide_cue = bool(
                re.search(r"行.*(?:非表示|隠|見えなく)", c)
                and not re.search(r"グリッド線|枠線|目盛り線|シート|タブ|再表示|消|削除", c)
            )
            has_font_unify_cue = bool(
                re.search(r"(?:フォント|書体).*(?:統一|揃え|そろえ)", c)
                or re.search(r"(?:全シート|すべてのシート|全てのシート|シート全体|ブック全体).*(?:フォント|書体)", c)
            )
            has_total_row_cue = bool(
                (
                    ("合計" in c and re.search(r"一番下|最後の行|末尾の行|表の下|下に|合計行|合計欄", c))
                    or re.search(r"合計を.{0,12}(?:足|追加|入れ|付け)", c)
                )
                and not re.search(r"ごと|別に|別シート|小計|平均|最大|最小|ピボット|クロス", c)
            )
            has_stat_row_cue = bool(
                re.search(r"平均|最大|最小", c)
                and re.search(r"一番下|最後の行|末尾の行|表の下|下に|(?:平均|最大|最小)(?:値)?(?:の?行|を.{0,12}(?:足|追加|入れ|付け))", c)
                and not re.search(r"ごと|別に|別シート|合計|ピボット|クロス", c)
            )
            has_paint_fmt_cue = bool(
                _color_hits(c)
                and "塗" in c
                and not re.search(r"条件|以上|以下|未満|上回|下回|届か|届いてい?ない|以外|じゃない|になって|消|削除|クリア|なし|無し|1行おき|交互|しましま|縞模様|重複|ダブ|固定色|該当行|行全体|の行", c)
            )
            _c_nfkc_cf = nfkc(c)
            _m_eq_cf = _COND_EQ_THING_RE.search(_c_nfkc_cf)
            _has_eq_col_cf = bool(_m_eq_cf and (not table or not table.get("columns") or _resolve_col_ref(_m_eq_cf.group(1), table)))
            has_row_cf_cond = bool(
                re.search(r"以上|以下|未満|より大き|より小さ|を超|超え|上回|下回|届か|届いてい?ない|マイナス|負の値|になっていない|になってない|になっている|になってる|ではない|でない|じゃない|以外|空欄|空白|欠席|完了", c)
                or _DATE_CMP_CUE_RE.search(_c_nfkc_cf)
                or _has_eq_col_cf
                or _two_col_cmp_of(_c_nfkc_cf, table)
                or _col_contains_of(_c_nfkc_cf, table)
                or re.search(r"[^\s、。]+?(?:が|は)[^\s、。の]+?の行", c)
            )
            has_row_cf_cue = bool(
                (_ROW_CF_THING_RE.search(_c_nfkc_cf) or (_DATE_CMP_CUE_RE.search(_c_nfkc_cf) and re.search(r"のセル|セルを|セルに", c)))
                and has_row_cf_cond
                and not re.search(r"消|削除|取り除|取っ|取る|除去|トリム|詰め|重複|ダブ|固定色|三角|千円|百万|だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|絞り込|フィルタ", c)
                and not ("赤字" in c and not re.search(r"の行|行を|行全体", c))
                and (_color_hits(c) or re.search(r"太字|太く|色[を]?付|色[を]?つ|目立|ハイライト|赤字", c))
            )
            has_row_del_cond = bool(
                re.search(r"の行|行を|行に|行は|行だけ|た行|る行|いない行|ない行|データ|明細|レコード|案件|商品", c)
                and (
                    re.search(r"以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|を含|含む|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行", c)
                    or _DATE_CMP_CUE_RE.search(nfkc(c))
                    or _col_contains_of(nfkc(c), table)
                    or re.search(r"[^\s、。]+?(?:が|は)[^\s、。の]+?の(?:行|データ|明細|レコード|案件|商品)", c)
                )
                and re.search(r"消|削除", c)
                and not re.search(r"重複|ダブ|空行|空いてる行|空いている行|空白行|空白の行|空き行|色|書式|罫線|フィルタ|フィルター|メモ|コメント|リンク|プルダウン|入力規則", _mask_col_names(c, table))
                and not _rows_of(c)
            )
            _m_col_del = re.search(r"([^\s、。のをにはが]{2,16}?)の?(?:列|カラム)", c)
            _c_nfkc_cd = nfkc(c)
            has_cols_del_cue = bool(
                _COL_DIRECT_DEL_RE.search(_c_nfkc_cd)
                and re.search(r"消(?!費)|削除|取り除|捨て", _c_nfkc_cd)
                and not _COL_CONTENT_DEL_RE.search(_c_nfkc_cd)
                and not _COL_PROP_OBJ_RE.search(_c_nfkc_cd)
                and bool(_col_names(c, table) or _col_letters(c) or (_m_col_del and _resolve_col_ref(_m_col_del.group(1), table)))
            )
            has_summary_cue = bool(
                re.search(r"(?:別(?:に|で|の)|ごと(?:に|の))", c)
                and re.search(r"集計|合計|平均|件数", c)
                and not re.search(r"ピボット|クロス|縦と横|小計|グラフ|並|ソート|抽出", c)
            )
            has_calc_diff_cue = bool(
                _calc_diff_cols_of(nfkc(c), table)
                and not re.search(r"シート|タブ|比較", c)
            )
            has_calc_cue = bool(
                re.search(
                    r"(?:と|に|×|\*)[^\s、。をにが]{1,16}?(?:を)?(?:掛け|かけ|乗算)|(?:と|に|＋|\+)[^\s、。をにが]{1,16}?(?:を)?(?:足[しす]|た[しす]|加算)|(?:から|−|-)[^\s、。をにが]{1,16}?(?:を)?(?:引[いけく]|ひ[いけく]|差し引|減算)|(?:を|÷|/)[^\s、。をにが]{1,16}?(?:で)?(?:割[っりる]|わ[っりる]|除算)|[^\s、。0-9:/\-][^\s、。]{0,14}[×*＊÷＋][^\s、。]{1,14}(?:で|を|の)",
                    nfkc(c),
                )
                and not re.search(r"構成比|割合|消費税|税込|税抜|累計|順位|平均|合計行|別シート|ごと|別に|小計|前月比|前年比|経過|罫線|空の?(?:列|行)|の間に|の下に|の上に", c)
            )
            has_chart_cue = bool(
                re.search(r"グラフ|棒グラフ|折れ線|円グラフ|散布図|面グラフ", c)
                and not re.search(r"消|削除|なく|いらない", c)
            )
            has_filter_where_cue = bool(
                (
                    re.search(r"以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄", c)
                    or _DATE_CMP_CUE_RE.search(nfkc(c))
                    or _col_contains_of(nfkc(c), table)
                    or re.search(r"[^\s、。]+?(?:が|は)[^\s、。の]+?の[^\s、。のをにはが]{1,12}", c)
                )
                and re.search(r"だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|絞り込|フィルタ", c)
                and not re.search(r"消|削除|別シート|抽出|色|ハイライト|目立|IF|判定|解除|外し|外す", c, re.IGNORECASE)
            )
            has_filter_extract_cue = bool(
                (
                    re.search(r"以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄", c)
                    or _DATE_CMP_CUE_RE.search(nfkc(c))
                    or _col_contains_of(nfkc(c), table)
                    or re.search(r"[^\s、。]+?(?:が|は)[^\s、。の]+?の(?:行|データ|明細|レコード|案件|商品)", c)
                )
                and re.search(r"抽出", c)
                and not re.search(r"上位|下位|トップ|ワースト|ベスト|URL|リンク|消|削除", c, re.IGNORECASE)
            )
            has_freeze_cue = bool(
                re.search(r"固定|フリーズ", c)
                and not re.search(r"解除|外|やめ|なく|値|式|数式|絶対参照|固定色|書式|太字|色|背景|罫線|揃え|寄せ", c)
            )
            has_blank_del_cue = bool(
                re.search(r"空行|空いてる行|空いている行|空白行|空白の行|空き行", c)
                and not re.search(r"重複|ダブ|全角|半角|整え|きれい|掃除|トリム|余分な空白|末尾|軽く|下まで|余白", c)
            )
            has_border_fmt_cue = bool(
                re.search(r"罫線|外枠|格子", c)
                and not re.search(r"整え|見やすく|体裁|きれい|区切り線|変わる行|切り替わる行|グリッド線|目盛り線|シート.*枠線", c)
            )
            has_seiri_clean_cue = bool(
                re.search(r"(?:前後|余分な?|両端|先頭|末尾)の?(?:空白|スペース).*(?:消|削除|取り除|取っ|取る|除去|詰め|トリム)|(?:空白|スペース)を(?:消|削除|取り除|取っ|取る|除去|詰め|トリム)|全角(?:の?(?:英?数字|文字))?を半角", c)
                and not re.search(r"空行|空白行|空白の行|空いてる行|空いている行|空き行|改行|不可視文字|ゴミ文字|セル内改行|穴埋め|上の値|以外の|じゃない|の行を消|の行を削除", c)
            )
            has_date_fix_cue = bool(
                (
                    "和暦" in c
                    or (
                        re.search(r"日付|入社日|生年月日|登録日|更新日|期限|yyyy/mm/dd|yyyy-mm-dd|年月日の?形", c, re.IGNORECASE)
                        and re.search(r"そろえ|揃え|統一|変換|本物の日付|ちゃんとした日付|西暦", c)
                    )
                )
                and not re.search(r"並べ|ソート|絞り込|フィルタ|消|削除|連続|下まで|埋め|経過|年齢|曜日", c)
            )
            has_phone_fix_cue = bool(
                (
                    re.search(r"電話|携帯|TEL|tel", c)
                    and re.search(r"ハイフン|区切り|そろえ|揃え|統一|整形|形式|直し", c)
                )
                and not re.search(r"全角|半角|空白|スペース|消|削除|非表示|隠|並|ソート|フィルタ|絞り込|マスク|伏せ字", c)
            )
            _short_fmt_only_re = re.compile(
                r"^(?:(?:タイトル|表題|見出し|ヘッダ|表全体|表|[^\s、。]{1,16}(?:の?列|の?欄)|[A-Z]{1,3}[0-9]*(?::[A-Z]{1,3}[0-9]*)?)(?:を|は|に)\s*)?"
                r"(?:太字|斜体|イタリック|中央揃え|中央寄せ|真ん中揃え|真ん中寄せ|右揃え|右寄せ|左揃え|左寄せ|中央|真ん中|右|左|折り返し?|"
                r"太字解除|斜体解除|折り返し解除|折り返しなし|罫線(?:なし|外枠)?|外枠|結合(?:解除)?|"
                r"(?:白|黒|赤|青|緑|黄|紫|灰|橙|紺|茶|桃|水色|濃い?[^\s、。]{1,3}|薄い?[^\s、。]{1,3})(?:い|の)?(?:文字|背景|塗り)|"
                r"(?:文字|フォント|背景|塗り)(?:は|を|に)?(?:白|黒|赤|青|緑|黄|紫|灰|橙|紺|茶|桃|水色|濃い?[^\s、。]{1,3}|薄い?[^\s、。]{1,3})|"
                r"[0-9]+\s*(?:pt|ポイント)|(?:少し|もっと|だいぶ|かなり|ぐっと)?(?:大きく|小さく))(?:で|に|へ|も|は|を|にして|して)?$"
            )
            has_short_fmt_cue = bool(
                (
                    _short_fmt_only_re.match(nfkc(c).strip())
                    or re.search(r"(?:太字|斜体|イタリック|中央揃え|中央寄せ|右揃え|右寄せ|左揃え|左寄せ|折り返し)(?:で|に|も|は|を)?$", nfkc(c).strip())
                )
                and not re.search(r"消|削除|解除|外|追加|挿入|移動|コピー|条件|以上|以下|未満|より|を超|上回|下回|届か|以外|じゃない|になって|固定|並|ソート|フィルタ|絞り|グラフ|集計|合計|平均|行を|の行", c)
            )
            has_remove_act = bool(re.search(r"外し|外す|解除|やめ|なくし|無くし|消して|消す|削除|クリア|オフ|OFF", c))

            def _ensure_boost(name):
                nonlocal boost_name
                boost_name = name
                if name not in cand_names and name in finder.cat.by_name:
                    scored.append((top_base, 999, finder.cat.by_name[name], {}))
                    cand_names.add(name)

            if has_remove_act and re.search(r"1行おき|交互|しましま|縞模様|ストライプ", c):
                _ensure_boost("banding.remove")
            elif re.search(r"1行おき|交互|しましま|縞模様|ストライプ", c) and not re.search(r"条件|以上|以下|未満", c):
                _ensure_boost("banding.add")
            elif has_remove_act and re.search(r"条件付き書式|自動でついた色|自動の色", c):
                _ensure_boost("cf.clear")
            elif has_remove_act and re.search(r"プルダウン|入力規則", c):
                _ensure_boost("validation.clear")
            elif has_remove_act and re.search(r"フィルタ|フィルター|絞り込み|▼", c):
                _ensure_boost("filter.off")
            elif has_remove_act and re.search(r"固定|フリーズ|ウィンドウ枠", c):
                _ensure_boost("unfreeze")
            elif has_remove_act and re.search(r"保護|ロック", c):
                _ensure_boost("protect.remove")
            elif has_remove_act and re.search(r"グループ|折りたた", c):
                _ensure_boost("group.remove")
            elif has_remove_act and re.search(r"グラフ|棒グラフ|折れ線|円グラフ", c):
                _ensure_boost("chart.delete")
            elif has_remove_act and re.search(r"重複|ダブ", c) and not re.search(r"色|目立|ハイライト|印|数え|何件", c) and "dedupe" in finder.cat.by_name:
                _ensure_boost("dedupe")
            elif has_row_del_cond:
                _ensure_boost("filter.delete")
            elif has_cols_del_cue:
                _ensure_boost("cols.delete")
            elif has_row_cf_cue:
                _ensure_boost("cf.add")
            elif has_chart_cue:
                _ensure_boost("chart.new")
            elif has_filter_where_cue:
                _ensure_boost("filter.where")
            elif has_filter_extract_cue:
                _ensure_boost("filter.extract")
            elif (_date_shift_of(c, table) and re.search(r"列|欄", c)) or _multi_col_agg_of(c, table):
                _ensure_boost("calc.col")
            elif re.search(r"重複|ダブ", c) and re.search(r"調べ|確認|チェック|ないか|探し|見つけ|色|目立|ハイライト", c) and not has_remove_act and "cf.dup" in finder.cat.by_name:
                _ensure_boost("cf.dup")
            elif has_calc_diff_cue:
                _ensure_boost("calc.diff")
            elif has_calc_cue:
                _ensure_boost("calc.col")
            elif has_summary_cue:
                _ensure_boost("summary")
            elif has_freeze_cue:
                _ensure_boost("freeze")
            elif has_blank_del_cue and ("blank.rows.delete" in cand_names or "seiri" in cand_names):
                _ensure_boost("blank.rows.delete")
            elif has_phone_fix_cue:
                _ensure_boost("phone.fix")
            elif has_date_fix_cue:
                _ensure_boost("date.fix")
            elif has_seiri_clean_cue:
                _ensure_boost("seiri")
            elif has_border_fmt_cue:
                _ensure_boost("format")
            elif has_cols_hide_cue:
                _ensure_boost("cols.hide")
            elif has_rows_hide_cue:
                _ensure_boost("rows.hide")
            elif has_font_unify_cue:
                _ensure_boost("font.unify")
            elif has_total_row_cue:
                _ensure_boost("total")
            elif has_stat_row_cue:
                _ensure_boost("stat.row")
            elif has_paint_fmt_cue or has_short_fmt_cue:
                _ensure_boost("format")
            elif has_fmt_cue and not re.search(r"分け|取り出|抽出|列を足|列を作|経過|日数|年齢|勤続|本物の日付|ちゃんとした日付|文字列を日付|日付に変換|マイナス|赤字|三角|千円|百万", c):
                _ensure_boost("format")
            elif len(scored) >= 2:
                if _color_hits(c) and "文字" in c and not re.search(r"大文字|小文字|全角|半角|UPPER|LOWER|PROPER", c, re.IGNORECASE) and "format" in cand_names:
                    boost_name = "format"
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
                elif "sheet.list" in cand_names and re.search(r"教え|確認|見せて|あるか|どんなシート|何枚", c) and re.search(r"シート|タブ|何枚", c) and not re.search(r"目次|インデックス|作", c):
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
        if not scored:
            p.reasons.append(f"「{c}」に当たる棚がありません")
            fatal_err = True
            last_incomplete = None
            continue

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
            if not any(k in op for k in ("header", "title", "range", "col")):
                for scope_k in ("header", "title", "range", "col"):
                    if scope_k in prev:
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
        if top["name"] == "chart.new" and not missing:
            agg_ops = _chart_summary_ops(op, c, table)
            if agg_ops:
                p.ops.extend(agg_ops)
                last_incomplete = None
                continue
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
    # 守り: 読むだけの問い（変更動詞なし・問いの形）で、シートを触る棚が当たったら撃たない（読む棚だけは撃てる）
    if p.fire and _is_read_only_ask(ask) and any(finder.cat.by_name[o["shelf"]].get("touch") for o in p.ops):
        p.fire = False
    amb_choices = _ambiguous_tidy_choices(ask, p.ops if p.fire else [], kind=kind)
    if amb_choices:
        p.fire = False
        p.choices = amb_choices
        p.ops = []
        p.reasons = ["どこまで整えるか選んでください"]
        p.missing = []
        p.cards = []
    elif not p.fire and _is_read_only_ask(ask):
        p.read_only = True
        p.ops = []
        p.reasons = []
        p.missing = []
        p.cards = []
    return p


def render_unfired(p, finder):
    if getattr(p, "choices", None):
        lines = ["どこまで行うか選んでください（まだシートは変更していません）:"]
        for i, ch in enumerate(p.choices, 1):
            ops_s = json.dumps(ch["ops"], ensure_ascii=False, separators=(",", ":"))
            lines.append(f"{i}. {ch['label']} — {ch['desc']}  ops={ops_s}")
        lines.append("使う人に番号を選んでもらい、選ばれた ops を ws_do(ops=…) で撃つ。")
        return "\n".join(lines)
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
    hr1 = table.get("header_row")
    hrs = int(table.get("header_rows") or 1)
    hr_s = f"{hr1}-{hr1 + hrs - 1}" if (hr1 and hrs > 1) else f"{hr1}"
    s = f"表: {table.get('first_col')}〜{table.get('last_col')} 列・見出し {hr_s} 行目・明細 {table.get('data')} 行目"
    s += f"・合計行 {table['total_row']} 行目" if table.get("total_row") else "・合計行なし"
    return s


def log_ask_miss(ask, plan, source="mcp", path=None):
    """ws_do(ask=...) が fire=False になった頼みを .ws_ask_misses.tsv へ自動記録する。"""
    if os.environ.get("WS_NO_MISS_LOG") == "1":
        return
    clean_ask = " ".join(str(ask or "").split())
    if len(clean_ask) < 2:
        return
    p = Path(path) if path else ASK_MISSES_FILE
    reason = " / ".join(plan.reasons) if getattr(plan, "reasons", None) else ("不足: " + ", ".join(getattr(plan, "missing", []) or []))
    reason = " ".join(reason.split()) or "不明"
    missing_s = " ".join(", ".join(getattr(plan, "missing", []) or []).split())
    ops_list = getattr(plan, "ops", None) or []
    ops_s = json.dumps(ops_list, ensure_ascii=False, separators=(",", ":")) if ops_list else ""
    try:
        if p.exists():
            lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                last_parts = lines[-1].split("\t")
                if len(last_parts) >= 4 and last_parts[1] == source and last_parts[2] == clean_ask and last_parts[3] == reason:
                    return
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = f"{ts}\t{source}\t{clean_ask}\t{reason}\t{missing_s}\t{ops_s}\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(row)
    except OSError:
        pass


def log_ask_ai_solved(ask, ops, source="ai", note="", path=None):
    """棚で止まった頼みが AI の ops で通ったとき、後で棚の型にするため .ws_ask_misses.tsv に印と ops を残す。"""
    if os.environ.get("WS_NO_MISS_LOG") == "1":
        return
    clean_ask = " ".join(str(ask or "").split())
    if len(clean_ask) < 2 or not isinstance(ops, list) or not ops:
        return
    p = Path(path) if path else ASK_MISSES_FILE
    mark = "AIで通った"
    note_s = " ".join(str(note or "").split())
    clean_ops = [{k: v for k, v in o.items() if k != "ok"} if isinstance(o, dict) else o for o in ops]
    ops_s = json.dumps(clean_ops, ensure_ascii=False, separators=(",", ":"))
    try:
        if p.exists():
            lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                last_parts = lines[-1].split("\t")
                if len(last_parts) >= 6 and last_parts[1] == source and last_parts[2] == clean_ask and last_parts[3] == mark and last_parts[5] == ops_s:
                    return
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = f"{ts}\t{source}\t{clean_ask}\t{mark}\t{note_s}\t{ops_s}\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(row)
    except OSError:
        pass
