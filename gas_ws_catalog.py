# -*- coding: utf-8 -*-
"""
gas_ws_catalog.py - Workspace の棚の目録（札）を読む・形を検査する・Catalog.gs を作る（純 Python・通信なし）

棚の札は、棚の関数（SHELF の添字に名前を書いて代入している所）のすぐ上に続く `//` コメントの塊（`// 棚:` の行から下）。
別の台帳は持たない。棚の名前・引数・控えるシート・触る物は、ここが札から作る。
このファイルには棚の名前を書かない（試験で縛る）。

札の形・検査の決めは Workspace マネージャー 2 号機の設計書（第 3 章・第 10 章）のとおり。
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELF_DIR = HERE / "ws_shelves"

CATEGORIES = ["作る", "シート", "範囲", "行と列", "見た目", "絞る", "整える", "入力", "集計", "守る", "文書"]
TOUCH_ITEMS = ["値", "書式", "シート構成", "幅", "固定", "フィルタ", "入力規則", "条件付き", "交互の色", "隠し", "グループ", "保護", "名前", "グラフ", "タブ色"]
BACKUP_ITEMS = ["今", "名前", "先", "全部", "なし"]
DANGERS = ["消す", "上書き"]
HEADINGS = ["棚", "題", "分類", "対象", "語", "違い", "引数", "どれか", "例", "危ない", "触る", "控え", "検索", "頼み"]
REQUIRED = ["棚", "題", "分類", "語", "引数", "例", "触る"]
TYPES = ["シート", "範囲", "列", "列[]", "行[]", "色", "文字", "数", "真偽", "配列", "表", "対応"]
GUARD = {"消す": "guardDelete_(", "上書き": "guardOverwrite_("}

_SHELF_LINE = re.compile(r"^\s*SHELF\[\s*'([^']*)'\s*\]\s*=")
_HEAD_LINE = re.compile(r"^//\s*([^\s:：]+)\s*[:：]\s?(.*)$")


# 棚ごとの追加の形の検査（引数の形の後に呼ぶ）。{棚の名前: 関数(op) → 問題の文 or None}。棚の側のモジュールが自分で登録する
EXTRA_CHECKS = {}
# ローカル状態（.ws_state.json）のみを扱う棚の実行関数。{棚の名前: 関数(st, op) → メッセージ}
LOCAL_HANDLERS = {}
# 既定でターゲット（ファイル）を必要としない／引数によって決まる棚の判定関数。{棚の名前: 関数(op) → bool}
NEEDS_TARGET_FN = {}


class CatalogError(Exception):
    pass


# ------------------------------------------------------------------ 札を読む
def _parse_arg(text):
    """`名前[*]=型[=既定]`。型は `選択(a/b/c)` も"""
    parts = text.strip().split("=", 2)
    if len(parts) < 2 or not parts[0].strip():
        raise CatalogError(f"引数の書き方が違います: 「{text.strip()}」（名前[*]=型[=既定]）")
    name, typ = parts[0].strip(), parts[1].strip()
    req = name.endswith("*")
    name = name.rstrip("*").strip()
    default = parts[2].strip() if len(parts) == 3 else None
    choices = None
    m = re.fullmatch(r"選択\(([^()]*)\)", typ)
    if m:
        choices = [c.strip() for c in m.group(1).split("/") if c.strip()]
        if not choices:
            raise CatalogError(f"引数「{name}」の選択肢が空です")
        typ = "選択"
    elif typ not in TYPES:
        raise CatalogError(f"引数「{name}」の型「{typ}」を知りません（{'・'.join(TYPES)}・選択(a/b/c)）")
    return {"name": name, "req": req, "type": typ, "default": default, "choices": choices}


def _split_args(text):
    text = text.strip()
    if text == "なし":
        return []
    # 選択(a/b/c) の中にカンマは来ない決め。カンマ区切りで割る
    return [_parse_arg(p) for p in text.split(",") if p.strip()]


def parse_text(text, fname="?"):
    """1 ファイルから札を全部読む。返すのは棚の dict のリスト（ファイルの中の順）"""
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if _SHELF_LINE.match(ln)]
    shelves = []
    for k, i in enumerate(marks):
        name_in_code = _SHELF_LINE.match(lines[i]).group(1)
        j = i
        while j - 1 >= 0 and lines[j - 1].startswith("//"):
            j -= 1
        block = lines[j:i]
        start = next((x for x, ln in enumerate(block) if re.match(r"^//\s*棚\s*[:：]", ln)), None)
        if start is None:
            raise CatalogError(f"{fname}: 棚「{name_in_code}」に札（// 棚: …）がありません")
        fields = {}
        for ln in block[start:]:
            m = _HEAD_LINE.match(ln)
            if not m:
                raise CatalogError(f"{fname}: 棚「{name_in_code}」の札に見出しのない行があります: {ln}")
            head, val = m.group(1), m.group(2).strip()
            if head not in HEADINGS:
                raise CatalogError(f"{fname}: 棚「{name_in_code}」の札に知らない見出し「{head}」があります（綴り違い？）")
            if head == "例":
                fields.setdefault("例", []).append(val)
            elif head in fields:
                raise CatalogError(f"{fname}: 棚「{name_in_code}」の札に「{head}:」が 2 回あります")
            else:
                fields[head] = val
        end = marks[k + 1] if k + 1 < len(marks) else len(lines)
        # 次の棚の札の分（塊の先頭まで）を除いた、この棚の本文
        nxt = end
        if k + 1 < len(marks):
            while nxt - 1 > i and lines[nxt - 1].startswith("//"):
                nxt -= 1
        body = "\n".join(lines[i:nxt])
        shelves.append(_build(fields, name_in_code, fname, body))
    return shelves


def _build(f, name_in_code, fname, body):
    tag = f"{fname}: 棚「{name_in_code}」"
    for h in REQUIRED:
        if h not in f or (f[h] in ("", []) and h != "例"):
            raise CatalogError(f"{tag}の札に必須の「{h}:」がありません")
    name = f["棚"]
    if name != name_in_code:
        raise CatalogError(f"{tag}の札の「棚: {name}」と SHELF の添字が違います")
    if not re.fullmatch(r"[a-z0-9]+(\.[a-z0-9]+)*", name):
        raise CatalogError(f"{tag}の名前は英小文字・数字・ドットだけです")
    if len(f["題"]) > 25:
        raise CatalogError(f"{tag}の題は 25 字以内です（{len(f['題'])} 字）")
    if f["分類"] not in CATEGORIES:
        raise CatalogError(f"{tag}の分類「{f['分類']}」は決まりの 11 個にありません")
    words = [w.strip() for w in f["語"].split("|") if w.strip()]
    if len(words) < 4:
        raise CatalogError(f"{tag}の語が {len(words)} 個です（4 個以上・5〜8 個が目安）")
    for w in words:
        if len(w) < 2:
            raise CatalogError(f"{tag}の語「{w}」が 1 字です（2 字以上）")
        if re.search(r"[\\^$.*+?()\[\]{}]", w):
            raise CatalogError(f"{tag}の語「{w}」に正規表現の記号があります（字面で探す）")
    try:
        args = _split_args(f["引数"])
    except CatalogError as e:
        raise CatalogError(f"{tag}: {e}")
    names = [a["name"] for a in args]
    if len(set(names)) != len(names):
        raise CatalogError(f"{tag}の引数の名前が重なっています")
    if "sheet" in names:
        raise CatalogError(f"{tag}の引数に sheet は書きません（共通の引数です）")
    anyof = f.get("どれか", "").split()
    for k in anyof:
        if k not in names:
            raise CatalogError(f"{tag}の「どれか:」に引数にない名前「{k}」があります")
    touch = f["触る"].split()
    if touch == ["なし"]:
        touch = []
    for t in touch:
        if t not in TOUCH_ITEMS:
            raise CatalogError(f"{tag}の「触る:」の「{t}」は決まりの項目にありません")
    backup = [b.strip() for b in f.get("控え", "今").split(",") if b.strip()]
    for b in backup:
        if b not in BACKUP_ITEMS:
            raise CatalogError(f"{tag}の「控え:」の「{b}」は決まりの項目にありません（{'・'.join(BACKUP_ITEMS)}）")
    danger = f.get("危ない", "")
    if danger and danger not in DANGERS:
        raise CatalogError(f"{tag}の「危ない:」は 消す か 上書き です")
    cat = f["分類"]
    sh = {
        "name": name, "title": f["題"], "category": cat, "kind": "doc" if cat == "文書" else "sheet",
        "shared": f.get("対象", "") == "両方",
        "words": words, "args_raw": f["引数"], "diff": f.get("違い", ""), "args": args, "any": anyof, "danger": danger,
        "touch": touch, "backup": backup, "searchable": f.get("検索", "") != "しない",
        "examples": [], "file": fname, "body": body,
    }
    if cat == "文書" and f.get("控え"):
        raise CatalogError(f"{tag}は文書の棚なので「控え:」は書きません")
    for raw in f.get("例", []):
        m = re.match(r"^「(.*)」\s*(?:→|->)\s*(\{.*\})\s*$", raw)
        if not m:
            raise CatalogError(f"{tag}の例の形が違います（「頼みの文」 → ops の JSON 1 個）: {raw}")
        try:
            op = json.loads(m.group(2))
        except Exception as e:
            raise CatalogError(f"{tag}の例の JSON が読めません: {e}")
        sh["examples"].append((m.group(1), op))
    if not 1 <= len(sh["examples"]) <= 2:
        raise CatalogError(f"{tag}の例は 1〜2 個です")
    try:
        sh["ask_rules"] = parse_ask_rules(f.get("頼み", ""), {a["name"]: a for a in args})
    except CatalogError as e:
        raise CatalogError(f"{tag}: {e}")
    return sh


def parse_ask_rules(text, args):
    """札の「頼み:」＝頼みの文から引数を組む決め（ws_do の ask が読む）。「 ; 」区切りで 2 つの形:
      引数=値<語|語   … 語のどれかが頼みにあれば、その値（JSON として読めれば JSON、読めなければ文字）
      引数~正規表現   … 頼みに当たれば、1 つ目の括弧の中身（型が 数 なら数に）
    """
    rules = []
    for part in [p.strip() for p in (text or "").split(" ; ") if p.strip()]:
        m = re.match(r"^([a-z_]+)~(.+)$", part)
        if m:
            name, pat = m.group(1), m.group(2)
            if name not in args:
                raise CatalogError(f"「頼み:」に引数にない名前「{name}」があります")
            try:
                rx = re.compile(pat)
            except re.error as e:
                raise CatalogError(f"「頼み:」の正規表現が読めません（{name}）: {e}")
            if rx.groups < 1:
                raise CatalogError(f"「頼み:」の正規表現に括弧がありません（{name}）")
            rules.append({"arg": name, "re": pat})       # 文字のまま持つ（札は JSON にされることがある）。当てる側で compile
            continue
        m = re.match(r"^([a-z_]+)=(.+?)<(.+)$", part)
        if not m:
            raise CatalogError(f"「頼み:」の形が違います（引数=値<語|語 か 引数~正規表現）: {part}")
        name, raw, words = m.group(1), m.group(2).strip(), [w.strip() for w in m.group(3).split("|") if w.strip()]
        if name not in args:
            raise CatalogError(f"「頼み:」に引数にない名前「{name}」があります")
        try:
            val = json.loads(raw)
        except Exception:
            val = raw
        rules.append({"arg": name, "value": val, "words": words})
    return rules


class Catalog:
    def __init__(self, shelves):
        self.shelves = list(shelves)
        self.by_name = {}
        for s in self.shelves:
            if s["name"] in self.by_name:
                raise CatalogError(f"棚「{s['name']}」が重なっています（{self.by_name[s['name']]['file']} と {s['file']}）")
            self.by_name[s["name"]] = s

    def names(self):
        return [s["name"] for s in self.shelves]

    def spec(self, name):
        """検査に使う形: kind / req / any / keys"""
        s = self.by_name.get(name)
        if not s:
            return None
        keys = [a["name"] for a in s["args"]]
        if s["kind"] == "sheet":
            keys = ["sheet"] + keys
        return {"kind": s["kind"], "req": [a["name"] for a in s["args"] if a["req"]], "any": list(s["any"]), "keys": keys}

    def specs(self):
        return {n: self.spec(n) for n in self.names()}

    # ------------------------------------------------------------ ops の形の検査
    def check_op(self, i, op):
        """1 つの op の形を見る。問題があれば日本語の 1 文を返す（無ければ None）。意味はエンジンが見る"""
        name = op["shelf"]
        s = self.by_name.get(name)
        args = {a["name"]: a for a in s["args"]}
        spec = self.spec(name)
        for k in op:
            if k != "shelf" and k not in spec["keys"]:
                return f"棚「{name}」（{i} 番目）に引数「{k}」はありません。使えるのは: " + "、".join(spec["keys"])
        for k in spec["req"]:
            if op.get(k) in (None, "", []):
                return f"棚「{name}」（{i} 番目）に「{k}」が要ります。"
        if spec["any"] and not any(op.get(k) not in (None, "", []) for k in spec["any"]):
            return f"棚「{name}」（{i} 番目）に " + "・".join(spec["any"]) + " のどれかが要ります。"
        for k, v in op.items():
            a = args.get(k)
            if a is None or v is None:
                continue
            msg = _check_type(name, i, a, v)
            if msg:
                return msg
        return None

    # ------------------------------------------------------------ 撃つ前にそろえる
    def normalize_op(self, op):
        """`列[]`・`行[]` に 1 つだけ渡された値を配列にそろえる（エンジンは配列を前提にする）。範囲の 'シート名'!A1 も分離する"""
        s = self.by_name[op["shelf"]]
        out = dict(op)
        for a in s["args"]:
            if a["type"] in ("列[]", "行[]") and a["name"] in out and out[a["name"]] is not None and not isinstance(out[a["name"]], list):
                out[a["name"]] = [out[a["name"]]]
            elif a["type"] == "範囲" and s["kind"] == "sheet" and isinstance(out.get(a["name"]), str):
                raw_r = out[a["name"]].strip()
                if "!" in raw_r and "," not in raw_r:
                    m = re.match(r"^(?:'((?:[^']|'')+)'|([^!']+))!(.+)$", raw_r)
                    if m and m.group(3).strip():
                        sh_nm = (m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)).strip()
                        if sh_nm and not out.get("sheet"):
                            out["sheet"] = sh_nm
                        out[a["name"]] = m.group(3).strip()
        return out


def _scalar(v):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _check_type(name, i, a, v):
    k, t = a["name"], a["type"]
    where = f"棚「{name}」の {k} は"
    if t in ("シート", "範囲", "列", "色"):
        if not _scalar(v):
            return f"{where}文字です（{i} 番目）。"
    elif t == "文字":
        if not (_scalar(v) or isinstance(v, bool)):
            return f"{where}文字です（{i} 番目）。"
    elif t == "数":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"{where}数です（{i} 番目）。"
    elif t == "真偽":
        if not isinstance(v, bool):
            return f"{where}true か false です（{i} 番目）。"
    elif t == "列[]":
        items = v if isinstance(v, list) else [v]
        if any(not _scalar(x) for x in items):
            return f"{where}列の名前（文字）の配列です（{i} 番目）。"
    elif t == "行[]":
        items = v if isinstance(v, list) else [v]
        for r in items:
            ok = (isinstance(r, int) and not isinstance(r, bool)) or (isinstance(r, str) and r.strip().isdigit())
            if not ok:
                return f"棚「{name}」の行番号は 1 以上の整数の配列です（{i} 番目）。"
            if int(r) < 1:
                return f"棚「{name}」の行番号は 1 以上です（{r} は指定できません）。"
    elif t == "配列":
        if not isinstance(v, list):
            return f"{where}配列です（{i} 番目）。"
    elif t == "表":
        if not isinstance(v, list) or any(not isinstance(r, list) for r in v):
            return f"{where}行の配列の配列です（{i} 番目）。"
    elif t == "対応":
        if not isinstance(v, dict):
            return f"{where}オブジェクトです（{i} 番目）。"
    elif t == "選択":
        key = v.lower() if isinstance(v, str) else v
        if key not in a["choices"]:
            return f"棚「{name}」の {k} は " + "・".join(a["choices"]) + " です。"
    return None


# ------------------------------------------------------------------ 読み込み
def shelf_files(shelf_dir=None):
    d = Path(shelf_dir) if shelf_dir else SHELF_DIR
    return sorted(d.glob("*.gs"), key=lambda p: p.name)


def load(shelf_dir=None):
    shelves = []
    for p in shelf_files(shelf_dir):
        shelves += parse_text(p.read_text(encoding="utf-8"), p.name)
    return Catalog(shelves)


# ------------------------------------------------------------------ Catalog.gs
def build_catalog_gs(cat):
    """エンジンの共通部が見る CATALOG。棚ごとに kind・触る物・控えるシート・危ない"""
    obj = {s["name"]: {"kind": s["kind"], "touch": s["touch"], "backup": s["backup"], "danger": s["danger"]} for s in cat.shelves}
    body = ",\n".join("  " + json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False) for k, v in obj.items())
    return "// Catalog.gs - 道具（gas_ws_catalog.py）が棚の札から作る。手で直さない\nvar CATALOG = {\n" + body + "\n};\n"


# ------------------------------------------------------------------ 検査（札の形・守り・決め打ち）
HARDCODE_FILES = ["workspace_engine.gs", "gas_workspace.py", "gas_ws_catalog.py", "gas_ws_find.py"]


def find_hardcoded_names(cat, root=None):
    """共通部に棚の名前の決め打ちが残っていないか。見つけた所を文字列のリストで返す"""
    root = Path(root) if root else HERE
    hits = []
    for fn in HARDCODE_FILES:
        p = root / fn
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for ln_no, ln in enumerate(text.split("\n"), 1):
            if re.search(r"SHELF\[\s*['\"]", ln):
                hits.append(f"{fn}:{ln_no}: SHELF の添字に名前を書いている")
            for n in cat.names():
                q = re.escape(n)
                if re.search(r"shelf\s*[:=]+\s*['\"]" + q + r"['\"]", ln) or re.search(r"\.shelf\s*[!=]==?\s*['\"]" + q + r"['\"]", ln):
                    hits.append(f"{fn}:{ln_no}: 棚「{n}」の決め打ち")
                elif "." in n and re.search(r"(?<![\w.])['\"]" + q + r"['\"]", ln):
                    hits.append(f"{fn}:{ln_no}: 棚「{n}」の名前")
    return hits


def check(cat=None):
    """札の検査。止める問題の文字列リストを返す（空なら通った）"""
    problems = []
    try:
        cat = cat or load()
    except CatalogError as e:
        return [str(e)]
    for s in cat.shelves:
        has_delete = GUARD["消す"] in s["body"]
        has_over = GUARD["上書き"] in s["body"]
        # 別の棚を呼ぶだけの棚（別名）は、呼び先の守りを引き継ぐ
        called = [n for n in re.findall(r"SHELF\[\s*'([^']+)'\s*\]\s*\(", s["body"]) if n in cat.by_name and n != s["name"]]
        inherits_delete = any(GUARD["消す"] in cat.by_name[n]["body"] for n in called)
        inherits_over = any(GUARD["上書き"] in cat.by_name[n]["body"] for n in called)
        if s["danger"] == "消す" and not (has_delete or inherits_delete):
            problems.append(f"棚「{s['name']}」は「危ない: 消す」ですが、本文に guardDelete_ がありません")
        if s["danger"] == "上書き" and not (has_over or inherits_over):
            problems.append(f"棚「{s['name']}」は「危ない: 上書き」ですが、本文に guardOverwrite_ がありません")
        if has_delete and s["danger"] != "消す":
            problems.append(f"棚「{s['name']}」の本文に guardDelete_ がありますが、札に「危ない: 消す」がありません")
        if has_over and s["danger"] != "上書き":
            problems.append(f"棚「{s['name']}」の本文に guardOverwrite_ がありますが、札に「危ない: 上書き」がありません")
        for ask, op in s["examples"]:
            if op.get("shelf") != s["name"]:
                problems.append(f"棚「{s['name']}」の例「{ask}」の shelf が違います")
                continue
            msg = cat.check_op(1, op)
            if msg:
                problems.append(f"棚「{s['name']}」の例「{ask}」が引数に合いません: {msg}")
    problems += find_hardcoded_names(cat)
    return problems
