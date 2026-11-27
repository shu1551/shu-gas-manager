# -*- coding: utf-8 -*-
"""
gas_ws_direct.py - ws_do の直接の道（エンジンの往復を省いて Sheets API を直接叩く）

右の枠（GASコンボ）が 0.3 秒台で直せるのと同じ道を、会話からの直し（ws_do）にも通す。
  ・鍵: エンジンの GAS 側の鍵（ScriptApp.getOAuthToken・action "token"）を 1 回もらって手元に持つ（clasp の鍵では Sheets API が止められている）
  ・撃つ前に、触る範囲を Sheets API で 1 回読む（＝控え）。戻しの命令はこの読みから作る
  ・撃った後に同じ範囲をもう 1 回読み、指紋を取る。ws_undo は戻す前に読み直して指紋を比べ、人が手で直していたら止まる
  ・直接撃つのは、戻しまで確かに作れる棚だけ（DIRECT_SHELVES）。ほかの棚・文書・新しいファイルは今のエンジンの道へ
  ・覚えている表の形が今のシートと違えば（見出しの文字が違う）、直接は撃たずエンジンの道へ（エンジンがその場で形を見直す）
"""

import hashlib
import json
import re
import unicodedata
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

FP_FILE = Path(__file__).resolve().parent / ".ws_direct_fp.json"   # 後ろで取った指紋（git に入れない）
_PENDING = {}            # 控えの番号 → 指紋を取っている裏の糸
_FP_LOCK = threading.Lock()
# 表の末尾の集計の段（合計・小計・消費税 等）の見出し。workspace_engine.gs の findTable_ と同じ
_FOOTER_LABEL_RE = re.compile(r"^(合計|総計|小計|税込合計|税抜合計|消費税|外税|内税|税額|値引き?|割引|計|平均|最大値?|最小値?|件数|total|subtotal|tax|sum)", re.I)

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets/"
TOKEN_LIFE = 45 * 60          # GAS の鍵はおよそ 1 時間。余裕を見て 45 分で取り直す
LEDGER_KEEP = 30
DIRECT_SHELVES = {"format", "format.negred", "font.unify", "bg.clear", "freeze", "unfreeze", "width", "write",
                  "clear.values", "clear.format", "sort", "rows.insert", "cols.insert", "cf.clear",
                  "sheet.rename", "sheet.hide", "sheet.show", "sheet.color", "sheet.gridlines",
                  "filter.on", "filter.off", "rows.hide", "rows.show", "cols.hide", "cols.show",
                  "note.set", "note.clear", "fmt.copy", "cf.add", "sheet.new", "_raw", "filter.where"}
_SHARED_DEFS_FILE = Path(__file__).resolve().parent / "ws_shared_defs.json"


def load_shared_defs(path=None):
    """Python・JS 共通の色・罫線・エラー表記定義（ws_shared_defs.json）を読み込む。"""
    p = Path(path) if path else _SHARED_DEFS_FILE
    return json.loads(p.read_text(encoding="utf-8"))


_SHARED_DEFS = load_shared_defs()
_BC255 = _SHARED_DEFS["border_color"]["rgb255"]
BORDER_COLOR = {"red": _BC255[0] / 255, "green": _BC255[1] / 255, "blue": _BC255[2] / 255}   # エンジンの STYLE.border（#9E9E9E）

# エンジンの rgb_ と同じ色の名前（どちらの道でも同じ色になるように）
COLOR_MAP = dict(_SHARED_DEFS["color_map"])
NONE_WORDS = set(_SHARED_DEFS["none_words"])
ERR_LABEL = dict(_SHARED_DEFS["err_label"])


class Skip(Exception):
    """直接の道に乗せない（エンジンの道へ回す）。人に見せる失敗ではない"""


class DirectError(Exception):
    """直接の道で撃ったが失敗した（エンジンの道へ回す）"""


def rgb(val):
    """色の名前・#RRGGBB → Sheets API の rgbColor。なし → None。知らない色は Skip（エンジンに断らせる）"""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in NONE_WORDS:
        return None
    if re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", s):
        hx = s if len(s) == 7 else "#" + "".join(ch * 2 for ch in s[1:])
    else:
        hx = COLOR_MAP.get(s.lower()) or COLOR_MAP.get(s)
        if not hx:
            s_shade = re.sub(r"^濃い", "濃", re.sub(r"^薄い", "薄", s))
            norm = re.sub(r"色$", "", s_shade)
            hx = COLOR_MAP.get(norm) or COLOR_MAP.get(s_shade)
    if not hx:
        raise Skip("知らない色")
    return {"red": int(hx[1:3], 16) / 255, "green": int(hx[3:5], 16) / 255, "blue": int(hx[5:7], 16) / 255}


def col_num(s):
    """列記号 → 1 始まり。列記号でなければ 0"""
    s = str(s or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", s):
        return 0
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def col_letter(n):
    s = ""
    while n > 0:
        m = (n - 1) % 26
        s = chr(65 + m) + s
        n = (n - 1) // 26
    return s


def q(name):
    return "'" + str(name).replace("'", "''") + "'"


def parse_a1(a1):
    """'B2' / 'B2:D9' → (r1, c1, r2, c2)（1 始まり）。列だけ・行だけの範囲や複数範囲は Skip"""
    m = re.fullmatch(r"\s*([A-Za-z]{1,3})([0-9]{1,7})(?::([A-Za-z]{1,3})([0-9]{1,7}))?\s*", str(a1 or ""))
    if not m:
        raise Skip("範囲の形")
    c1, r1 = col_num(m.group(1)), int(m.group(2))
    c2 = col_num(m.group(3)) if m.group(3) else c1
    r2 = int(m.group(4)) if m.group(4) else r1
    if r2 < r1 or c2 < c1 or r1 < 1 or c1 < 1:
        raise Skip("範囲の形")
    return r1, c1, r2, c2


def a1(r1, c1, r2, c2):
    s = col_letter(c1) + str(r1)
    return s if (r1, c1) == (r2, c2) else s + ":" + col_letter(c2) + str(r2)


def grid(sid, r1, c1, r2, c2):
    return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def infer_number_format_type(pattern):
    """表示形式の文字列から Sheets API の numberFormat.type を判定する"""
    p = str(pattern or "")
    if "@" in p:
        return "TEXT"
    if "%" in p:
        return "PERCENT"
    if re.search(r"[¥$€£￥]", p):
        return "CURRENCY"
    stripped = re.sub(r'"[^"]*"|\\.', "", p)
    has_date = bool(re.search(r"[ymd]", stripped, re.I))
    has_time = bool(re.search(r"[hs]", stripped, re.I)) or ("AM/PM" in stripped)
    if has_date and has_time:
        return "DATE_TIME"
    if has_date:
        return "DATE"
    if has_time:
        return "TIME"
    return "NUMBER"


def clean_format(f):
    """読んだ書式を書き戻せる形にする（古い色の欄は *Style に寄せて外す）"""
    f = json.loads(json.dumps(f or {}))
    if "backgroundColor" in f:
        f.setdefault("backgroundColorStyle", {"rgbColor": f["backgroundColor"]})
        f.pop("backgroundColor", None)
    tf = f.get("textFormat")
    if isinstance(tf, dict) and "foregroundColor" in tf:
        tf.setdefault("foregroundColorStyle", {"rgbColor": tf["foregroundColor"]})
        tf.pop("foregroundColor", None)
    for side in (f.get("borders") or {}).values():
        if isinstance(side, dict) and "color" in side:
            side.setdefault("colorStyle", {"rgbColor": side["color"]})
            side.pop("color", None)
    return f


def _intersects(m, r1, c1, r2, c2):
    return not (m["endRowIndex"] < r1 or m["startRowIndex"] + 1 > r2 or m["endColumnIndex"] < c1 or m["startColumnIndex"] + 1 > c2)


class Snapshot:
    """1 回の GET の読み（シートごとの性質・フィルタ・結合・読んだ範囲のセル）"""

    def __init__(self, data):
        self.sheets = {}      # 名前 → {"props", "filter", "merges", "cells": {(r,c): cell}, "colpx": {c: px}, "rowpx": {r: px}, "colhid": {c: bool}, "rowhid": {r: bool}}
        for sh in data.get("sheets") or []:
            p = sh.get("properties") or {}
            ent = self.sheets.setdefault(p.get("title"), {"props": p, "filter": sh.get("basicFilter"), "merges": sh.get("merges") or [],
                                                          "cf_rules": sh.get("conditionalFormats") or [],
                                                          "cells": {}, "colpx": {}, "rowpx": {}, "colhid": {}, "rowhid": {}})
            for d in sh.get("data") or []:
                r0, c0 = d.get("startRow", 0), d.get("startColumn", 0)
                for i, row in enumerate(d.get("rowData") or []):
                    for j, cell in enumerate(row.get("values") or []):
                        ent["cells"][(r0 + i + 1, c0 + j + 1)] = cell
                for j, cm in enumerate(d.get("columnMetadata") or []):
                    ent["colpx"][c0 + j + 1] = cm.get("pixelSize")
                    ent["colhid"][c0 + j + 1] = bool(cm.get("hiddenByUser"))
                for i, rm in enumerate(d.get("rowMetadata") or []):
                    ent["rowpx"][r0 + i + 1] = rm.get("pixelSize")
                    ent["rowhid"][r0 + i + 1] = bool(rm.get("hiddenByUser"))

    def sheet(self, name):
        ent = self.sheets.get(name)
        if not ent:
            raise Skip("シートが読めない")
        return ent

    @staticmethod
    def value_text(cell):
        v = (cell or {}).get("userEnteredValue") or {}
        for k in ("stringValue", "numberValue", "boolValue", "formulaValue"):
            if k in v:
                x = v[k]
                if k == "numberValue" and float(x).is_integer():
                    x = int(x)
                return str(x)
        return ""

    @staticmethod
    def display_text(cell):
        """formattedValue があれば表示文字列（日付など）を優先して返す。"""
        if isinstance(cell, dict) and cell.get("formattedValue") is not None:
            return str(cell["formattedValue"])
        return Snapshot.value_text(cell)


class DirectRunner:
    def __init__(self, mgr):
        self.mgr = mgr

    # ------------------------------------------------------------ 鍵・通信
    def _token(self, st, fresh=False):
        tk = st.get("direct_token") or {}
        if not fresh and tk.get("token") and time.time() < tk.get("until", 0):
            return tk["token"]
        res = self.mgr._post({"action": "token"})
        cur = self.mgr._load()     # _post がエンジンを入れ直していたら、その記録を手元の st にも写す（古い st で上書きしない）
        for k in ("engine_sid", "engine_url", "engine_deploy_id", "engine_ver"):
            if k in cur:
                st[k] = cur[k]
        tok = res.get("token") or ""
        if not tok:
            raise Skip("鍵がもらえない")
        st["direct_token"] = {"token": tok, "until": time.time() + TOKEN_LIFE}
        return tok

    def _call(self, st, method, url, **kw):
        sess = self.mgr.client.session
        if method != "GET" and isinstance(getattr(self.mgr, "_look_memo", None), dict):
            self.mgr._look_memo.clear()      # 書いたら、覚えた表の読みは古い
        waited, fresh = 0.0, False
        for attempt in range(8):
            h = {"Authorization": "Bearer " + self._token(st, fresh=fresh)}
            if "json" in kw:
                h["Content-Type"] = "application/json"
            r = sess.request(method, url, headers=h, timeout=30, **kw)
            if r.status_code == 401 and not fresh:
                fresh = True
                continue
            if r.status_code == 429 and waited < 40:
                # 1 分あたりの読み書きの上限（Sheets API は 1 人 60 回/分）。断られた要求は何も書いていないので、待って撃ち直す
                import time as _t
                w = min(2 ** attempt, 10)
                _t.sleep(w)
                waited += w
                continue
            if r.status_code == 403 and "SERVICE_DISABLED" in r.text:
                st["direct_off"] = "Sheets API が止められている"
                raise Skip("Sheets API が止められている")
            if r.status_code != 200:
                raise DirectError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        raise DirectError("鍵が通らない")

    def _get(self, st, sid, ranges, extra_fields=""):
        params = [("ranges", r) for r in ranges] + [("fields", _FULL_FIELDS)]
        return Snapshot(self._call(st, "GET", SHEETS + sid, params=params))

    def _before(self, st, tgt, sheet, ranges):
        """撃つ前の読み。同じ呼び出しで先撃ちが今のシートの A1:Z60 を読んでいて、読む範囲がその中に収まれば使い回す"""
        lf = getattr(self.mgr, "_light_full", None) or getattr(self.mgr, "_light_seen", None)
        if lf and lf[0] == tgt.get("id") and lf[1] == sheet:
            ok_all = True
            for rg in ranges:
                m = re.fullmatch(r"(?:'((?:[^']|'')*)'|([^!]+))!(.+)", rg)
                if not m or (m.group(1) or m.group(2)).replace("''", "'") != sheet:
                    ok_all = False
                    break
                try:
                    r1, c1, r2, c2 = parse_a1(m.group(3))
                except Exception:
                    ok_all = False
                    break
                if r2 > 60 or c2 > 26:
                    ok_all = False
                    break
            if ok_all:
                return lf[2]["snap"]
        return self._get(st, tgt["id"], ranges)

    # ------------------------------------------------------------ 場所を決める
    @staticmethod
    def _table_rows(tb):
        m = re.fullmatch(r"([0-9]+)-([0-9]+)", str(tb.get("data") or ""))
        if not m:
            raise Skip("表の形")
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def _col_of(tb, ref):
        s = str(ref).strip()
        names = [c.get("name") for c in tb.get("columns") or []]
        if s in names:
            return col_num(tb["columns"][names.index(s)]["col"])
        m = re.fullmatch(r"([A-Za-z]{1,3})列?", s)
        if m:
            return col_num(m.group(1))
        raise Skip("列が分からない")

    def _place(self, op, tb):
        """format・bg.clear の場所（title は読みの後で決めるので 'title' を返す）"""
        if op.get("header"):
            if not tb:
                raise Skip("表が無い")
            h_end = tb["header_row"] + max(1, int(tb.get("header_rows") or 1)) - 1
            return (tb["header_row"], col_num(tb["first_col"]), h_end, col_num(tb["last_col"]))
        if op.get("title"):
            return "title"
        if op.get("col"):
            if not tb:
                raise Skip("表が無い")
            c = self._col_of(tb, op["col"])
            f, l = self._table_rows(tb)
            return (f, c, tb.get("total_row") or l, c)
        if op.get("range"):
            return parse_a1(op["range"])
        raise Skip("場所が無い")

    @staticmethod
    def _title_place(ent, tb, op=None):
        """エンジンの titleRange_ と同じ: 見出しの上の行で、最初に中身のあるセル（結合していれば結合の範囲、未結合 1 セルなら表の横幅帯へ拡張）"""
        limit = (tb["header_row"] - 1) if tb else 0
        if limit < 1:
            raise Skip("タイトルの行が無い")
        width = col_num(tb["last_col"])
        first_col = col_num(tb["first_col"])
        for r in range(1, limit + 1):
            for c in range(1, width + 1):
                if Snapshot.value_text(ent["cells"].get((r, c))):
                    for m in ent["merges"]:
                        if m["startRowIndex"] + 1 <= r <= m["endRowIndex"] and m["startColumnIndex"] + 1 <= c <= m["endColumnIndex"]:
                            return (m["startRowIndex"] + 1, m["startColumnIndex"] + 1, m["endRowIndex"], m["endColumnIndex"]), False
                    if op and op.get("shelf") == "format" and op.get("merge") is None:
                        filled = sum(1 for cc in range(min(c, first_col), width + 1) if Snapshot.value_text(ent["cells"].get((r, cc))))
                        if filled <= 1 and width > min(c, first_col):
                            return (r, min(c, first_col), r, width), True
                    return (r, c, r, c), False
        raise Skip("タイトルが見つからない")

    # ------------------------------------------------------------ 命令を組む（撃つ命令と戻す命令）
    def _plan(self, ops, sheet, tb, sheets_known):
        """読む範囲を決める。返すのは (読む範囲のリスト, 組み立ての関数)。組み立ては読みの後に呼ぶ"""
        ranges = set()
        for op in ops:
            if op.get("_new") or op["shelf"] in ("sheet.new", "_raw"):
                continue      # これから作るシートへの手（読む物が無い）
            sh = op.get("sheet") or sheet
            ranges.add(f"{q(sh)}!A1")
            s = op["shelf"]
            if s in ("format", "bg.clear"):
                pl = self._place(op, tb)
                if pl == "title":
                    if not tb or (tb.get("header_row") or 0) <= 1:
                        raise Skip("タイトルの行が無い")
                    ranges.add(f"{q(sh)}!A1:{tb['last_col']}{tb['header_row'] - 1}")
                else:
                    ranges.add(f"{q(sh)}!{a1(*pl)}")
            elif s == "format.negred":
                if op.get("col") or op.get("range"):
                    pl = self._place(op, tb)
                    ranges.add(f"{q(sh)}!{a1(*pl)}")
                elif tb:
                    f, l = self._table_rows(tb)
                    r_end = tb.get("total_row") or l
                    for c_info in tb.get("columns") or []:
                        if c_info.get("number") and not re.fullmatch(r"no\.?|番号|項番|id", str(c_info.get("name") or "").strip(), re.IGNORECASE):
                            ci = col_num(c_info["col"])
                            ranges.add(f"{q(sh)}!{a1(f, ci, r_end, ci)}")
                else:
                    raise Skip("対象範囲が分からない")
            elif s == "font.unify":
                if op.get("all_sheets") or not tb:
                    raise Skip("all_sheets または表無しはエンジンの道へ")
                _, l = self._table_rows(tb)
                r_end = tb.get("total_row") or l
                if r_end * col_num(tb["last_col"]) > 1000:
                    raise Skip("範囲が広いのでエンジンの道へ")
                ranges.add(f"{q(sh)}!A1:{tb['last_col']}{r_end}")
            elif s == "clear.values":
                if not op.get("ok") or op.get("only") == "constants" or not op.get("range"):
                    raise Skip("確認・指定条件のためエンジンの道へ")
                r1, c1, r2, c2 = parse_a1(op["range"])
                if (r2 - r1 + 1) * (c2 - c1 + 1) > 400:
                    raise Skip("範囲が広いのでエンジンの道へ")
                if tb:
                    f, l = self._table_rows(tb)
                    tr_end = tb.get("total_row") or l
                    fc_n, lc_n = col_num(tb["first_col"]), col_num(tb["last_col"])
                    if r1 < tb["header_row"] or r2 > tr_end or c1 < fc_n or c2 > lc_n:
                        raise Skip("表外の広い削除はエンジンの道へ")
                    data_rows = max(1, l - f + 1)
                    if r2 >= f and (min(r2, l) - max(r1, f) + 1) > data_rows / 2:
                        raise Skip("明細の半分超の削除はエンジンの道へ")
                ranges.add(f"{q(sh)}!{a1(r1, c1, r2, c2)}")
            elif s == "clear.format":
                if not op.get("range"):
                    raise Skip("range が要る")
                r1, c1, r2, c2 = parse_a1(op["range"])
                if (r2 - r1 + 1) * (c2 - c1 + 1) > 400:
                    raise Skip("範囲が広いのでエンジンの道へ")
                ranges.add(f"{q(sh)}!{a1(r1, c1, r2, c2)}")
            elif s == "sort":
                if op.get("where") or op.get("filter") or not tb:
                    raise Skip("where/filter/表無しはエンジンの道へ")
                if not (op.get("cols") or op.get("col")):
                    raise Skip("列が要る")
                f, l = self._table_rows(tb)
                if l - f + 1 > 500:
                    raise Skip("行数が多いためエンジンの道へ")
                ranges.add(f"{q(sh)}!{tb['first_col']}{f}:{tb['last_col']}{l}")
            elif s in ("rows.insert", "cols.insert"):
                if op.get("at") in (None, ""):
                    raise Skip("at が要る")
                cnt = int(op.get("count") or 1)
                if cnt < 1 or cnt > 50:
                    raise Skip("count 範囲外")
                if s == "cols.insert" and tb:
                    f_row, l_row = self._table_rows(tb)
                    end_r = max(l_row, int(tb.get("total_row") or 0))
                    if end_r >= f_row and (end_r - f_row + 1) <= 500:
                        ranges.add(f"{q(sh)}!{tb['first_col']}{f_row}:{tb['last_col']}{end_r}")
            elif s == "cf.clear":
                pass
            elif s == "width":
                if op.get("all_sheets") or op.get("auto_rows"):
                    raise Skip("all_sheets / auto_rows はエンジンの道へ")
                for k in list((op.get("cols") or {}).keys()) + ([op["col"]] if op.get("col") and op.get("width") else []) + list(op.get("auto") or []):
                    c = self._col_of(tb, k) if tb else col_num(k)
                    if not c:
                        raise Skip("列が分からない")
                    ranges.add(f"{q(sh)}!{col_letter(c)}1")
                for k in (op.get("rows") or {}):
                    ranges.add(f"{q(sh)}!A{int(k)}")
            elif s in ("rows.hide", "rows.show"):
                r1, r2 = int(op.get("from") or op.get("row") or 0), int(op.get("to") or op.get("from") or op.get("row") or 0)
                if r1 < 1 or r2 < r1:
                    raise Skip("行番号が要る")
                ranges.add(f"{q(sh)}!A{r1}:A{r2}")
            elif s in ("cols.hide", "cols.show"):
                raw = op.get("cols") if isinstance(op.get("cols"), list) else ([op["col"]] if op.get("col") is not None else [])
                if not raw:
                    raise Skip("列が要る")
                for k in raw:
                    c = self._col_of(tb, k) if tb else col_num(k)
                    if not c:
                        raise Skip("列が分からない")
                    ranges.add(f"{q(sh)}!{col_letter(c)}1")
            elif s == "note.set":
                has = False
                if isinstance(op.get("cells"), dict) and op["cells"]:
                    for k in op["cells"]:
                        parse_a1(k)
                        ranges.add(f"{q(sh)}!{k}")
                        has = True
                if op.get("cell") and op.get("text") is not None:
                    parse_a1(op["cell"])
                    ranges.add(f"{q(sh)}!{op['cell']}")
                    has = True
                if not has:
                    raise Skip("note.set の指定が無い")
            elif s == "note.clear":
                if op.get("range"):
                    r1, c1, r2, c2 = parse_a1(op["range"])
                elif tb:
                    _, l = self._table_rows(tb)
                    r1, c1, r2, c2 = 1, 1, max(tb.get("total_row") or l, l), col_num(tb["last_col"])
                else:
                    raise Skip("範囲が無い")
                ranges.add(f"{q(sh)}!{a1(r1, c1, r2, c2)}")
            elif s == "write":
                if op.get("tsv") is not None or not isinstance(op.get("cells"), dict) or not op["cells"]:
                    raise Skip("write は cells だけ")
                for k in op["cells"]:
                    parse_a1(k)
                    ranges.add(f"{q(sh)}!{k}")
            elif s == "cf.add":
                if not op.get("range") or not op.get("when"):
                    raise Skip("range と when が要る")
                parse_a1(op["range"])
            elif s == "fmt.copy":      # 直の道の中だけの手（値を書く棚を組み替えたときの書式の写し）
                fr1, fc1, fr2, fc2 = parse_a1(op["from"])
                tr1, tc1, tr2, tc2 = parse_a1(op["to"])
                if (fr2 - fr1, fc2 - fc1) != (tr2 - tr1, tc2 - tc1):
                    raise Skip("写しの大きさが違う")
                ranges.add(f"{q(sh)}!{op['to']}")
            elif s in ("sheet.rename", "sheet.hide", "sheet.color"):
                if op.get("name"):
                    ranges.add(f"{q(op['name'])}!A1")
            elif s == "sheet.show":
                if op.get("name"):
                    ranges.add(f"{q(op['name'])}!A1")
                else:
                    for n in sheets_known or []:
                        ranges.add(f"{q(n)}!A1")
            elif s == "filter.where":
                if not tb or not op.get("col"):
                    raise Skip("表と列が要る")
                f_r, l_r = self._table_rows(tb)
                if l_r - f_r + 1 > 500:
                    raise Skip("行数が多いためエンジンの道へ")
                ci_w = self._col_of(tb, op["col"])
                if not ci_w:
                    raise Skip("列が分からない")
                ranges.add(f"{q(sh)}!{col_letter(ci_w)}{f_r}:{col_letter(ci_w)}{l_r}")
            elif s == "filter.on":
                if op.get("range"):
                    ranges.add(f"{q(sh)}!{op['range']}")
            elif s in ("freeze", "unfreeze", "filter.off", "sheet.gridlines"):
                if s == "sheet.gridlines" and op.get("all_sheets"):
                    raise Skip("all_sheets はエンジンの道へ")
                pass
            else:
                raise Skip("直接の道に無い棚")
        if tb:   # 覚えている表の形が今と同じかを確かめる見出しの行
            ranges.add(f"{q(sheet)}!{tb['first_col']}{tb['header_row']}:{tb['last_col']}{tb['header_row']}")
        return sorted(ranges)

    @staticmethod
    def _rgb_eq(c1, c2, tol=0.03):
        if not isinstance(c1, dict) or not isinstance(c2, dict):
            return False
        for k in ("red", "green", "blue"):
            if abs(float(c1.get(k, 0.0) or 0.0) - float(c2.get(k, 0.0) or 0.0)) > tol:
                return False
        return True

    @classmethod
    def _format_already_applied(cls, ent, r1, c1, r2, c2, op, title_band):
        """対象範囲の全セルに op で指定された書式がすでに当たっているか判定する。"""
        if op.get("borders") is not None or op.get("merge") is not None or op.get("size_delta") is not None:
            return False
        checked = False
        cells = ent.get("cells") or {}
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = cells.get((r, c)) or {}
                ef = cell.get("effectiveFormat") or {}
                uf = cell.get("userEnteredFormat") or {}
                if not ef and not uf:
                    return False
                if op.get("bg") is not None:
                    checked = True
                    want = rgb(op["bg"])
                    cur_bg = ((ef.get("backgroundColorStyle") or {}).get("rgbColor")) or ef.get("backgroundColor")
                    if want is None:
                        if uf.get("backgroundColorStyle") or uf.get("backgroundColor"):
                            return False
                    elif not cls._rgb_eq(want, cur_bg):
                        return False
                if op.get("bold") is not None:
                    checked = True
                    if bool(op["bold"]) != bool((ef.get("textFormat") or {}).get("bold", False)):
                        return False
                if op.get("italic") is not None:
                    checked = True
                    if bool(op["italic"]) != bool((ef.get("textFormat") or {}).get("italic", False)):
                        return False
                if op.get("color") is not None:
                    checked = True
                    want_c = rgb(op["color"])
                    cur_c = ((ef.get("textFormat") or {}).get("foregroundColorStyle") or {}).get("rgbColor") or (ef.get("textFormat") or {}).get("foregroundColor")
                    if want_c is not None and not cls._rgb_eq(want_c, cur_c):
                        return False
                if op.get("size") is not None:
                    checked = True
                    if int(op["size"]) != int((ef.get("textFormat") or {}).get("fontSize") or 10):
                        return False
                if op.get("font") is not None:
                    checked = True
                    if str(op["font"]).lower() != str((ef.get("textFormat") or {}).get("fontFamily") or "").lower():
                        return False
                if op.get("number_format") is not None:
                    checked = True
                    if str(op["number_format"]) != str((ef.get("numberFormat") or {}).get("pattern") or ""):
                        return False
                if op.get("align") is not None:
                    checked = True
                    al = str(op["align"]).upper()
                    if title_band and al in ("CENTER", "MIDDLE", "RIGHT"):
                        al = "LEFT"
                    want_al = "CENTER" if al == "MIDDLE" else al
                    if want_al != str(ef.get("horizontalAlignment") or "").upper():
                        return False
                if op.get("valign") is not None:
                    checked = True
                    va = str(op["valign"]).upper()
                    want_va = "MIDDLE" if va == "CENTER" else va
                    if want_va != str(ef.get("verticalAlignment") or "").upper():
                        return False
                if op.get("wrap") is not None:
                    checked = True
                    want_w = "WRAP" if op["wrap"] else "OVERFLOW_CELL"
                    if want_w != str(ef.get("wrapStrategy") or "").upper():
                        return False
        return checked

    def _build(self, ops, sheet, tb, snap):
        req, undo, changed, touched, already = [], [], [], [], []
        self._cf_added = {}

        def area(shname, r1, c1, r2, c2):
            touched.append((shname, r1, c1, r2, c2))

        for op in ops:
            s = op["shelf"]
            shn = op.get("sheet") or sheet
            if s == "sheet.new":
                req.append({"addSheet": {"properties": {"sheetId": op["sheet_id"], "title": op["name"], "index": op["index"]}}})
                undo.append({"deleteSheet": {"sheetId": op["sheet_id"]}})     # 戻しは最後にシートごと消す
                continue
            if s == "_raw":
                req.extend(op["requests"])
                undo[0:0] = list(op.get("undo") or [])
                for t_ in op.get("touch") or []:
                    area(*t_)
                if op.get("said"):
                    changed.append(op["said"])
                continue
            if s == "write" and op.get("_new"):
                for k in op["cells"]:
                    r1, c1, _, _ = parse_a1(k)
                    area(shn, r1, c1, r1, c1)
                req.append({"_values": {shn: op["cells"]}})
                continue
            ent = snap.sheet(shn)
            sid = ent["props"]["sheetId"]
            if s in ("format", "bg.clear"):
                pl = self._place(op, tb)
                if pl == "title":
                    (r1, c1, r2, c2), title_band = self._title_place(ent, tb, op)
                else:
                    (r1, c1, r2, c2), title_band = pl, False
                if s == "format" and self._format_already_applied(ent, r1, c1, r2, c2, op, title_band):
                    already.append(f"{shn}!{a1(r1, c1, r2, c2)}")
                    continue
                g = grid(sid, r1, c1, r2, c2)
                cf, tf, fields, did = {}, {}, [], []
                if s == "bg.clear" or (op.get("bg") is not None and rgb(op["bg"]) is None):
                    fields.append("userEnteredFormat.backgroundColorStyle"); did.append("背景色なし" if s == "bg.clear" else "bg")
                elif op.get("bg") is not None:
                    cf["backgroundColorStyle"] = {"rgbColor": rgb(op["bg"])}; fields.append("userEnteredFormat.backgroundColorStyle"); did.append("bg")
                if s == "format":
                    if op.get("bold") is not None:
                        tf["bold"] = bool(op["bold"]); fields.append("userEnteredFormat.textFormat.bold"); did.append("bold")
                    if op.get("italic") is not None:
                        tf["italic"] = bool(op["italic"]); fields.append("userEnteredFormat.textFormat.italic"); did.append("italic")
                    if op.get("color") is not None:
                        c = rgb(op["color"])
                        if c is not None:
                            tf["foregroundColorStyle"] = {"rgbColor": c}
                        fields.append("userEnteredFormat.textFormat.foregroundColorStyle"); did.append("color")
                    if op.get("size_delta") is not None:
                        raise Skip("size_delta")
                    if op.get("size") is not None:
                        tf["fontSize"] = int(op["size"]); fields.append("userEnteredFormat.textFormat.fontSize"); did.append("size")
                    if op.get("font") is not None:
                        tf["fontFamily"] = str(op["font"]); fields.append("userEnteredFormat.textFormat.fontFamily"); did.append("font")
                    if op.get("number_format") is not None:
                        pat = str(op["number_format"])
                        cf["numberFormat"] = {"type": infer_number_format_type(pat), "pattern": pat}; fields.append("userEnteredFormat.numberFormat"); did.append("number_format")
                    if op.get("align") is not None:
                        al = str(op["align"]).upper()
                        if title_band and al in ("CENTER", "MIDDLE", "RIGHT"):
                            al = "LEFT"
                        cf["horizontalAlignment"] = "CENTER" if al == "MIDDLE" else al; fields.append("userEnteredFormat.horizontalAlignment"); did.append("align")
                    if op.get("valign") is not None:
                        va = str(op["valign"]).upper()
                        cf["verticalAlignment"] = "MIDDLE" if va == "CENTER" else va; fields.append("userEnteredFormat.verticalAlignment"); did.append("valign")
                    if op.get("wrap") is not None:
                        cf["wrapStrategy"] = "WRAP" if op["wrap"] else "OVERFLOW_CELL"; fields.append("userEnteredFormat.wrapStrategy"); did.append("wrap")
                if tf:
                    cf["textFormat"] = tf
                if op.get("borders") is not None:
                    fields_b = True
                else:
                    fields_b = False
                if fields:
                    req.append({"repeatCell": {"range": g, "cell": {"userEnteredFormat": cf}, "fields": ",".join(fields)}})
                if fields or fields_b:
                    rows = [{"values": [{"userEnteredFormat": clean_format((ent["cells"].get((r, c)) or {}).get("userEnteredFormat"))}
                                        for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                    mask = list(fields) + (["userEnteredFormat.borders"] if fields_b else [])
                    undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": ",".join(mask)}})
                if fields_b:
                    v = op["borders"]
                    on = {"style": "SOLID", "width": 1, "colorStyle": {"rgbColor": BORDER_COLOR}}
                    off = {"style": "NONE"}
                    if v in (False, "none", "なし", "false"):
                        b = dict(top=off, bottom=off, left=off, right=off, innerHorizontal=off, innerVertical=off)
                    elif v == "outer":
                        b = dict(top=on, bottom=on, left=on, right=on)
                    else:
                        b = dict(top=on, bottom=on, left=on, right=on, innerHorizontal=on, innerVertical=on)
                    req.append({"updateBorders": dict(range=g, **b)}); did.append("borders")
                if op.get("merge") is not None:
                    prior = [m for m in ent["merges"] if _intersects(m, r1, c1, r2, c2)]
                    if op["merge"]:
                        req.append({"mergeCells": {"range": g, "mergeType": "MERGE_ALL"}}); did.append("merge")
                        undo.insert(0, {"unmergeCells": {"range": g}})
                        for m in prior:
                            undo.insert(1, {"mergeCells": {"range": m, "mergeType": "MERGE_ALL"}})
                    else:
                        req.append({"unmergeCells": {"range": g}}); did.append("merge")
                        for m in prior:
                            undo.insert(0, {"mergeCells": {"range": m, "mergeType": "MERGE_ALL"}})
                if not did:
                    raise Skip("書式の指定が無い")
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}!{a1(r1, c1, r2, c2)} {'・'.join(did)}")
            elif s in ("freeze", "unfreeze"):
                gp = ent["props"].get("gridProperties") or {}
                fr = 0 if s == "unfreeze" else int(op.get("rows", 1) if op.get("rows") is not None else 1)
                fc = 0 if s == "unfreeze" else int(op.get("cols", 0) if op.get("cols") is not None else 0)
                f = "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
                req.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": fr, "frozenColumnCount": fc}}, "fields": f}})
                undo.insert(0, {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
                    "frozenRowCount": gp.get("frozenRowCount", 0), "frozenColumnCount": gp.get("frozenColumnCount", 0)}}, "fields": f}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!" + ("固定を解除" if s == "unfreeze" else f"行固定: {fr}、列固定: {fc}"))
            elif s == "width":
                did = []
                pairs = [(k, w) for k, w in (op.get("cols") or {}).items()]
                if op.get("col") and op.get("width"):
                    pairs.append((op["col"], op["width"]))
                for k, w in pairs:
                    c = self._col_of(tb, k) if tb else col_num(k)
                    req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
                                                              "properties": {"pixelSize": int(w)}, "fields": "pixelSize"}})
                    did.append(f"{k}列")
                for k in op.get("auto") or []:
                    c = self._col_of(tb, k) if tb else col_num(k)
                    req.append({"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c}}})
                    did.append(f"{k}列(自動)")
                    pairs.append((k, None))
                for k, _ in pairs:
                    c = self._col_of(tb, k) if tb else col_num(k)
                    px = ent["colpx"].get(c)
                    if not px:
                        raise Skip("前の幅が読めない")
                    undo.insert(0, {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
                                                                  "properties": {"pixelSize": px}, "fields": "pixelSize"}})
                for k, h in (op.get("rows") or {}).items():
                    r = int(k)
                    px = ent["rowpx"].get(r)
                    if not px:
                        raise Skip("前の高さが読めない")
                    req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
                                                              "properties": {"pixelSize": int(h)}, "fields": "pixelSize"}})
                    undo.insert(0, {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
                                                                  "properties": {"pixelSize": px}, "fields": "pixelSize"}})
                    did.append(f"{k}行")
                if not did:
                    raise Skip("幅の指定が無い")
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{'・'.join(did)} 幅・高さを変更")
            elif s == "cf.add":
                if not lower_pin_ok("cf.add"):
                    raise Skip("エンジンの cf.add が書き換わった（直の道の写しが古い）")
                r1, c1, r2, c2 = parse_a1(op["range"])
                w = str(op["when"]).lower()
                val = "" if op.get("value") is None else str(op["value"])
                clean = val.replace(",", "").strip()
                try:
                    is_num = clean != "" and float(clean) == float(clean)
                except ValueError:
                    is_num = False
                if w == "between" or (not is_num and w in ("gt", "ge", "lt", "le", "eq", "ne") and re.search(r"\d+\s*[/年月\-]|今日|昨日|明日", val)):
                    raise Skip("日付の比べはエンジンの道で")
                a1c = f"{col_letter(c1)}{r1}"
                num = {"gt": "NUMBER_GREATER", "ge": "NUMBER_GREATER_THAN_EQ", "lt": "NUMBER_LESS", "le": "NUMBER_LESS_THAN_EQ"}
                if w in num:
                    if not is_num:
                        raise Skip("数でない比べ")
                    cond = {"type": num[w], "values": [{"userEnteredValue": clean}]}
                elif w == "eq":
                    cond = {"type": "NUMBER_EQ", "values": [{"userEnteredValue": clean}]} if is_num else {"type": "TEXT_EQ", "values": [{"userEnteredValue": val}]}
                elif w == "ne":
                    cond = ({"type": "NUMBER_NOT_EQ", "values": [{"userEnteredValue": clean}]} if is_num else
                            {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f'={a1c}<>"' + val.replace('"', '""') + '"'}]})
                elif w == "contains":
                    cond = {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": val}]}
                elif w == "blank":
                    cond = {"type": "BLANK"}
                elif w == "notblank":
                    cond = {"type": "NOT_BLANK"}
                elif w == "formula":
                    cond = {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": val}]}
                else:
                    raise Skip("知らない when")
                fmt = {}
                if op.get("bg"):
                    fmt["backgroundColor"] = rgb(op["bg"])
                if op.get("color"):
                    fmt.setdefault("textFormat", {})["foregroundColor"] = rgb(op["color"])
                if op.get("bold"):
                    fmt.setdefault("textFormat", {})["bold"] = True
                cf_n = getattr(self, "_cf_added", {})
                idx = len(ent.get("cf_rules") or []) + cf_n.get(shn, 0)
                cf_n[shn] = cf_n.get(shn, 0) + 1
                self._cf_added = cf_n
                req.append({"addConditionalFormatRule": {"rule": {"ranges": [grid(sid, r1, c1, r2, c2)],
                                                                  "booleanRule": {"condition": cond, "format": fmt}}, "index": idx}})
                undo.insert(0, {"deleteConditionalFormatRule": {"sheetId": sid, "index": idx}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{op['range']} 条件付き書式を付与（when: {op['when']}）")
            elif s == "fmt.copy":
                fr1, fc1, fr2, fc2 = parse_a1(op["from"])
                tr1, tc1, tr2, tc2 = parse_a1(op["to"])
                rows_u = []
                for r in range(tr1, tr2 + 1):
                    rows_u.append({"values": [{"userEnteredFormat": ((ent["cells"].get((r, c)) or {}).get("userEnteredFormat") or {})}
                                              for c in range(tc1, tc2 + 1)]})
                undo.insert(0, {"updateCells": {"start": {"sheetId": sid, "rowIndex": tr1 - 1, "columnIndex": tc1 - 1},
                                                "rows": rows_u, "fields": "userEnteredFormat"}})
                req.append({"copyPaste": {"source": grid(sid, fr1, fc1, fr2, fc2), "destination": grid(sid, tr1, tc1, tr2, tc2),
                                          "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
                area(shn, tr1, tc1, tr2, tc2)
            elif s == "write":
                for k, v in op["cells"].items():
                    r1, c1, r2, c2 = parse_a1(k)
                    if (r1, c1) != (r2, c2):
                        raise Skip("write は 1 セルずつ")
                    old = (ent["cells"].get((r1, c1)) or {}).get("userEnteredValue")
                    undo.insert(0, {"updateCells": {"start": {"sheetId": sid, "rowIndex": r1 - 1, "columnIndex": c1 - 1},
                                                    "rows": [{"values": [{"userEnteredValue": old} if old else {}]}], "fields": "userEnteredValue"}})
                    area(shn, r1, c1, r1, c1)
                changed.append(f"{shn}!{'・'.join(op['cells'].keys())} 値・式を書いた")
                req.append({"_values": {shn: op["cells"]}})
            elif s in ("sheet.rename", "sheet.hide", "sheet.color", "sheet.show"):
                names = [op.get("name") or shn] if s != "sheet.show" or op.get("name") else \
                    [n for n, e in snap.sheets.items() if e["props"].get("hidden")]
                if s in ("sheet.rename", "sheet.hide") and not op.get("name"):
                    raise Skip("name が要る")
                for nm in names:
                    e2 = snap.sheet(nm)
                    sid2 = e2["props"]["sheetId"]
                    if s == "sheet.rename":
                        to = str(op.get("to") or "").strip()
                        if not to or to in snap.sheets:
                            raise Skip("名前が空か、もうある")
                        req.append({"updateSheetProperties": {"properties": {"sheetId": sid2, "title": to}, "fields": "title"}})
                        undo.insert(0, {"updateSheetProperties": {"properties": {"sheetId": sid2, "title": nm}, "fields": "title"}})
                        changed.append(f"{nm}!シート名を「{to}」に変更")
                    elif s == "sheet.hide":
                        visible = [n for n, e in snap.sheets.items() if not e["props"].get("hidden")]
                        if visible == [nm]:
                            raise Skip("最後のシート")
                        req.append({"updateSheetProperties": {"properties": {"sheetId": sid2, "hidden": True}, "fields": "hidden"}})
                        undo.insert(0, {"updateSheetProperties": {"properties": {"sheetId": sid2, "hidden": bool(e2['props'].get('hidden'))}, "fields": "hidden"}})
                        changed.append(f"{nm}!シート「{nm}」を非表示に設定")
                    elif s == "sheet.show":
                        req.append({"updateSheetProperties": {"properties": {"sheetId": sid2, "hidden": False}, "fields": "hidden"}})
                        undo.insert(0, {"updateSheetProperties": {"properties": {"sheetId": sid2, "hidden": bool(e2['props'].get('hidden'))}, "fields": "hidden"}})
                        changed.append(f"{nm}!シート「{nm}」を再表示")
                    else:
                        c = rgb(op.get("color"))
                        p = {"sheetId": sid2}
                        if c is not None:
                            p["tabColorStyle"] = {"rgbColor": c}
                        req.append({"updateSheetProperties": {"properties": p, "fields": "tabColorStyle"}})
                        p0 = {"sheetId": sid2}
                        if e2["props"].get("tabColorStyle"):
                            p0["tabColorStyle"] = e2["props"]["tabColorStyle"]
                        undo.insert(0, {"updateSheetProperties": {"properties": p0, "fields": "tabColorStyle"}})
                        changed.append(f"{nm}!タブの色を「{op.get('color')}」に変更")
                    area(nm, 0, 0, 0, 0)
                if s == "sheet.show" and not names:
                    raise Skip("隠したシートが無い")
            elif s == "filter.where":
                if not lower_pin_ok("sort"):
                    raise Skip("エンジンの sort（絞り込みの本体）が書き換わった")
                if int(tb.get("header_rows") or 1) > 1:
                    raise Skip("2 段見出しはエンジンの道で")
                f_r, l_r = self._table_rows(tb)
                c_first, c_last = col_num(tb["first_col"]), col_num(tb["last_col"])
                ci_w = self._col_of(tb, op["col"])
                wh = str(op.get("when") or "").lower()
                wv = op.get("value") if op.get("value") is not None else op.get("equals")
                wvs = "" if wv is None else str(wv)
                wvn = wvs.replace(",", "").strip()
                try:
                    is_n = wvn != "" and float(wvn) == float(wvn)
                except ValueError:
                    is_n = False
                fy = None
                for r in range(f_r, l_r + 1):
                    c0 = ent["cells"].get((r, ci_w)) or {}
                    e0 = c0.get("effectiveValue") or {}
                    if "numberValue" in e0 and (((c0.get("effectiveFormat") or {}).get("numberFormat")) or {}).get("type") in ("DATE", "DATE_TIME"):
                        fy = _low_serial_date(e0["numberValue"]).year
                        break
                    if "stringValue" in e0 and re.match(r"^\s*\d{4}", e0["stringValue"]):
                        d0 = _low_cmp_date(e0["stringValue"], False, 2000)
                        if d0:
                            fy = d0.year
                            break
                if fy is None:
                    from datetime import date as _d
                    fy = _d.today().year
                ref = f"{col_letter(ci_w)}{f_r}"
                de = lambda d: f"DATE({d.year},{d.month},{d.day})"
                d_rng = None
                if wh == "between" and ".." in wvs:
                    d1, d2 = _low_cmp_date(wvs.split("..")[0], False, fy), _low_cmp_date(wvs.split("..")[1], False, fy)
                    d_rng = (min(d1, d2), max(d1, d2)) if d1 and d2 else None
                d_one = _low_cmp_date(wvs, False, fy) if (not is_n and (wh in ("gt", "ge", "lt", "le", "eq", "ne") or (wh == "" and op.get("equals") is not None))) else None
                cf_ = lambda t, v=None: {"type": t, **({"values": [{"userEnteredValue": v}]} if v is not None else {})}
                if wh == "blank":
                    cond = cf_("BLANK")
                elif wh in ("notblank", "not_blank"):
                    cond = cf_("NOT_BLANK")
                elif wh == "contains":
                    cond = cf_("TEXT_CONTAINS", wvs)
                elif wh == "between" and d_rng:
                    cond = cf_("CUSTOM_FORMULA", f"=AND(ISNUMBER({ref}),{ref}>={de(d_rng[0])},{ref}<={de(d_rng[1])})")
                elif d_one:
                    opm = {"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": "=", "ne": "<>"}.get(wh or "eq", "=")
                    cond = cf_("CUSTOM_FORMULA", f"=AND(ISNUMBER({ref}),{ref}{opm}{de(d_one)})")
                elif wh == "ne":
                    if wvs == "":
                        cond = cf_("NOT_BLANK")
                    elif is_n:
                        cond = cf_("NUMBER_NOT_EQ", wvn)
                    else:
                        cond = cf_("CUSTOM_FORMULA", f'={ref}<>"' + wvs.replace('"', '""') + '"')
                elif wh in ("gt", "ge", "lt", "le"):
                    cond = cf_({"gt": "NUMBER_GREATER", "ge": "NUMBER_GREATER_THAN_EQ", "lt": "NUMBER_LESS", "le": "NUMBER_LESS_THAN_EQ"}[wh], wvn)
                elif wh == "eq" or op.get("equals") is not None:
                    cond = cf_("NUMBER_EQ", wvn) if is_n else cf_("TEXT_EQ", wvs)
                else:
                    cond = cf_("NOT_BLANK")
                prev = ent.get("filter")
                g_f = grid(sid, int(tb["header_row"]), c_first, l_r, c_last)
                req.append({"setBasicFilter": {"filter": {"range": g_f, "filterSpecs": [{"columnIndex": ci_w - 1, "filterCriteria": {"condition": cond}}]}}})
                undo.insert(0, {"setBasicFilter": {"filter": prev}} if prev else {"clearBasicFilter": {"sheetId": sid}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{a1(int(tb['header_row']), c_first, l_r, c_last)} フィルタを設定")
            elif s in ("filter.on", "filter.off"):
                prev = ent.get("filter")
                if s == "filter.off" and not prev:
                    raise Skip("フィルタが無い")
                if s == "filter.on":
                    if op.get("range"):
                        r1, c1, r2, c2 = parse_a1(op["range"])
                    elif tb:
                        f, l = self._table_rows(tb)
                        r1, c1, r2, c2 = tb["header_row"], col_num(tb["first_col"]), l, col_num(tb["last_col"])
                    else:
                        raise Skip("表が無い")
                    req.append({"setBasicFilter": {"filter": {"range": grid(sid, r1, c1, r2, c2)}}})
                    changed.append(f"{shn}!{a1(r1, c1, r2, c2)} フィルタを設定")
                else:
                    req.append({"clearBasicFilter": {"sheetId": sid}})
                    changed.append(f"{shn}!フィルタを解除")
                undo.insert(0, {"setBasicFilter": {"filter": prev}} if prev else {"clearBasicFilter": {"sheetId": sid}})
                area(shn, 0, 0, 0, 0)
            elif s == "sheet.gridlines":
                gp = ent["props"].get("gridProperties") or {}
                show = op.get("show") is not False
                f = "gridProperties.hideGridlines"
                req.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"hideGridlines": not show}}, "fields": f}})
                undo.insert(0, {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"hideGridlines": bool(gp.get("hideGridlines", False))}}, "fields": f}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!枠線を{'表示' if show else '非表示'}")
            elif s in ("rows.hide", "rows.show"):
                r1, r2 = int(op.get("from") or op.get("row") or 0), int(op.get("to") or op.get("from") or op.get("row") or 0)
                hide = (s == "rows.hide")
                req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r1 - 1, "endIndex": r2},
                                                          "properties": {"hiddenByUser": hide}, "fields": "hiddenByUser"}})
                for r in range(r1, r2 + 1):
                    undo.insert(0, {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
                                                                  "properties": {"hiddenByUser": bool(ent["rowhid"].get(r, False))}, "fields": "hiddenByUser"}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{r1}〜{r2}行を{'非表示' if hide else '再表示'}")
            elif s in ("cols.hide", "cols.show"):
                raw = op.get("cols") if isinstance(op.get("cols"), list) else ([op["col"]] if op.get("col") is not None else [])
                hide = (s == "cols.hide")
                done = []
                for k in raw:
                    c = self._col_of(tb, k) if tb else col_num(k)
                    req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
                                                              "properties": {"hiddenByUser": hide}, "fields": "hiddenByUser"}})
                    undo.insert(0, {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
                                                                  "properties": {"hiddenByUser": bool(ent["colhid"].get(c, False))}, "fields": "hiddenByUser"}})
                    done.append(f"{col_letter(c)}列")
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{'・'.join(done)}を{'非表示' if hide else '再表示'}")
            elif s == "note.set":
                pairs = []
                if isinstance(op.get("cells"), dict):
                    pairs.extend(op["cells"].items())
                if op.get("cell") and op.get("text") is not None:
                    pairs.append((op["cell"], op["text"]))
                done = []
                for k, txt in pairs:
                    r1, c1, r2, c2 = parse_a1(k)
                    g = grid(sid, r1, c1, r2, c2)
                    req.append({"repeatCell": {"range": g, "cell": {"note": "" if txt is None else str(txt)}, "fields": "note"}})
                    rows = [{"values": [{"note": (ent["cells"].get((r, c)) or {}).get("note") or ""} for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                    undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "note"}})
                    area(shn, r1, c1, r2, c2)
                    done.append(k)
                changed.append(f"{shn}!{'・'.join(done)} メモを設定")
            elif s == "note.clear":
                if op.get("range"):
                    r1, c1, r2, c2 = parse_a1(op["range"])
                    label = op["range"]
                else:
                    _, l = self._table_rows(tb)
                    r1, c1, r2, c2 = 1, 1, max(tb.get("total_row") or l, l), col_num(tb["last_col"])
                    label = "シート全体"
                g = grid(sid, r1, c1, r2, c2)
                req.append({"repeatCell": {"range": g, "cell": {"note": ""}, "fields": "note"}})
                rows = [{"values": [{"note": (ent["cells"].get((r, c)) or {}).get("note") or ""} for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "note"}})
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}!{label} メモを消去")
            elif s == "format.negred":
                unit = str(op.get("unit") or "none").lower()
                base = "¥#,##0" if unit == "yen" else ("#,##0," if unit == "thousand" else ("#,##0,," if unit == "million" else "#,##0"))
                neg = ('"▲"' if op.get("triangle") else "-") + base
                fmt = f"{base};[Red]{neg}"
                pls = []
                if op.get("col") or op.get("range"):
                    pls.append(self._place(op, tb))
                else:
                    f_r, l_r = self._table_rows(tb)
                    r_end = tb.get("total_row") or l_r
                    for c_info in tb.get("columns") or []:
                        if c_info.get("number") and not re.fullmatch(r"no\.?|番号|項番|id", str(c_info.get("name") or "").strip(), re.IGNORECASE):
                            ci = col_num(c_info["col"])
                            pls.append((f_r, ci, r_end, ci))
                if not pls:
                    raise Skip("数値列が見つからない")
                nf_obj = {"type": "NUMBER", "pattern": fmt}
                done_lbls = []
                for r1, c1, r2, c2 in pls:
                    g = grid(sid, r1, c1, r2, c2)
                    req.append({"repeatCell": {"range": g, "cell": {"userEnteredFormat": {"numberFormat": nf_obj}}, "fields": "userEnteredFormat.numberFormat"}})
                    rows = [{"values": [{"userEnteredFormat": clean_format((ent["cells"].get((r, c)) or {}).get("userEnteredFormat"))}
                                        for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                    undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "userEnteredFormat.numberFormat"}})
                    area(shn, r1, c1, r2, c2)
                    done_lbls.append(a1(r1, c1, r2, c2))
                changed.append(f"{shn}!{'・'.join(done_lbls)} 数値表示（{fmt}）を適用")
            elif s == "font.unify":
                font_nm = str(op.get("font") or "Noto Sans JP").strip() or "Noto Sans JP"
                sz = int(op["size"]) if op.get("size") is not None else 0
                _, l_r = self._table_rows(tb)
                r1, c1, r2, c2 = 1, 1, tb.get("total_row") or l_r, col_num(tb["last_col"])
                g = grid(sid, r1, c1, r2, c2)
                tf_u = {"fontFamily": font_nm}
                flds = ["userEnteredFormat.textFormat.fontFamily"]
                if sz > 0:
                    tf_u["fontSize"] = sz
                    flds.append("userEnteredFormat.textFormat.fontSize")
                req.append({"repeatCell": {"range": g, "cell": {"userEnteredFormat": {"textFormat": tf_u}}, "fields": ",".join(flds)}})
                rows = [{"values": [{"userEnteredFormat": clean_format((ent["cells"].get((r, c)) or {}).get("userEnteredFormat"))}
                                    for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": ",".join(flds)}})
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}! フォントを「{font_nm}」" + (f"・{sz}pt " if sz > 0 else "") + "に統一")
            elif s == "clear.values":
                r1, c1, r2, c2 = parse_a1(op["range"])
                g = grid(sid, r1, c1, r2, c2)
                req.append({"updateCells": {"range": g, "fields": "userEnteredValue"}})
                rows = [{"values": [{"userEnteredValue": (ent["cells"].get((r, c)) or {}).get("userEnteredValue")}
                                    if (ent["cells"].get((r, c)) or {}).get("userEnteredValue") else {}
                                    for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "userEnteredValue"}})
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}!{a1(r1, c1, r2, c2)} 値を消去")
            elif s == "clear.format":
                r1, c1, r2, c2 = parse_a1(op["range"])
                g = grid(sid, r1, c1, r2, c2)
                req.append({"repeatCell": {"range": g, "cell": {}, "fields": "userEnteredFormat"}})
                rows = [{"values": [{"userEnteredFormat": clean_format((ent["cells"].get((r, c)) or {}).get("userEnteredFormat"))}
                                    for c in range(c1, c2 + 1)]} for r in range(r1, r2 + 1)]
                undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "userEnteredFormat"}})
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}!{a1(r1, c1, r2, c2)} 書式をクリア")
            elif s == "sort":
                f_r, l_r = self._table_rows(tb)
                r1, c1, r2, c2 = f_r, col_num(tb["first_col"]), l_r, col_num(tb["last_col"])
                raw_specs = op.get("cols") if isinstance(op.get("cols"), list) else ([op["cols"]] if op.get("cols") else [])
                sort_specs, lbl_specs = [], []
                if raw_specs:
                    for item in raw_specs:
                        if isinstance(item, dict):
                            cn, is_desc = item.get("col"), bool(item.get("desc"))
                        else:
                            st_s = str(item or "").strip()
                            is_desc = st_s.startswith("-") or st_s.lower().endswith(":desc")
                            cn = re.sub(r":(?:asc|desc)$", "", st_s.lstrip("-"), flags=re.IGNORECASE).strip()
                        ci = self._col_of(tb, cn)
                        sort_specs.append({"dimensionIndex": ci - 1, "sortOrder": "DESCENDING" if is_desc else "ASCENDING"})
                        lbl_specs.append(f"{cn}({'降順' if is_desc else '昇順'})")
                else:
                    ci = self._col_of(tb, op["col"])
                    is_desc = bool(op.get("desc"))
                    sort_specs.append({"dimensionIndex": ci - 1, "sortOrder": "DESCENDING" if is_desc else "ASCENDING"})
                    lbl_specs.append(f"{op['col']} で{'降順' if is_desc else '昇順'}")
                g = grid(sid, r1, c1, r2, c2)
                req.append({"sortRange": {"range": g, "sortSpecs": sort_specs}})
                rows = [{"values": [
                    {k: v for k, v in (
                        ("userEnteredValue", (ent["cells"].get((r, c)) or {}).get("userEnteredValue")),
                        ("userEnteredFormat", clean_format((ent["cells"].get((r, c)) or {}).get("userEnteredFormat"))),
                    ) if v is not None}
                    for c in range(c1, c2 + 1)
                ]} for r in range(r1, r2 + 1)]
                undo.insert(0, {"updateCells": {"range": g, "rows": rows, "fields": "userEnteredValue,userEnteredFormat"}})
                area(shn, r1, c1, r2, c2)
                changed.append(f"{shn}!{a1(r1, c1, r2, c2)} {'→'.join(lbl_specs)} に並べ替え")
            elif s in ("rows.insert", "cols.insert"):
                is_col_ins = (s == "cols.insert")
                cnt = int(op.get("count") or 1)
                at_num = (self._col_of(tb, op["at"]) if tb else col_num(op["at"])) if is_col_ins else int(op["at"])
                if at_num < 1:
                    raise Skip("挿入位置が不正")
                if is_col_ins and any(
                    isinstance((cv.get("userEnteredValue") or {}).get("formulaValue"), str)
                    and (cv.get("userEnteredValue") or {}).get("formulaValue", "").startswith("=")
                    for cv in (ent.get("cells") or {}).values()
                ):
                    raise Skip("既存の数式を保護するためエンジンの道へ")
                dim = "COLUMNS" if is_col_ins else "ROWS"
                req.append({"insertDimension": {
                    "range": {"sheetId": sid, "dimension": dim, "startIndex": at_num - 1, "endIndex": at_num - 1 + cnt},
                    "inheritFromBefore": at_num > 1
                }})
                undo.insert(0, {"deleteDimension": {"range": {"sheetId": sid, "dimension": dim, "startIndex": at_num - 1, "endIndex": at_num - 1 + cnt}}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{op['at']}{'列' if is_col_ins else '行目'}の前に {cnt} {'列' if is_col_ins else '行'}挿入")
            elif s == "cf.clear":
                rules = ent.get("cf_rules") or []
                targets_cf = []
                if not op.get("range"):
                    targets_cf = list(enumerate(rules))
                else:
                    tr1, tc1, tr2, tc2 = parse_a1(op["range"])
                    for idx_cf, rule in enumerate(rules):
                        if any(
                            r_g.get("sheetId", sid) == sid and _intersects(r_g, tr1, tc1, tr2, tc2)
                            for r_g in (rule.get("ranges") or [])
                        ):
                            targets_cf.append((idx_cf, rule))
                if not targets_cf:
                    raise Skip("消す条件付き書式が無い")
                for idx_cf, _ in reversed(targets_cf):
                    req.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": idx_cf}})
                for idx_cf, rule in targets_cf:
                    undo.append({"addConditionalFormatRule": {"rule": rule, "index": idx_cf}})
                area(shn, 0, 0, 0, 0)
                changed.append(f"{shn}!{op.get('range') or 'シート全体'} 条件付き書式を解除（{len(targets_cf)} 件）")
        self._last_already = already
        return req, undo, changed, touched

    # ------------------------------------------------------------ 指紋（撃った後の姿。戻す前に人の手直しを見つける）
    @staticmethod
    def _fp(snap, touched):
        parts = []
        for shn, r1, c1, r2, c2 in touched:
            ent = snap.sheets.get(shn) or {}
            p = ent.get("props") or {}
            if r1 == 0:
                parts.append([shn, p.get("title"), p.get("hidden"), p.get("tabColorStyle"), p.get("gridProperties"), ent.get("filter"),
                              ent.get("cf_rules"),
                              sorted(ent.get("colpx", {}).items()), sorted(ent.get("rowpx", {}).items()),
                              sorted(ent.get("colhid", {}).items()), sorted(ent.get("rowhid", {}).items())])
            else:
                parts.append([shn, [[(ent.get("cells") or {}).get((r, c), {}).get("userEnteredValue"),
                                     clean_format((ent.get("cells") or {}).get((r, c), {}).get("userEnteredFormat")),
                                     (ent.get("cells") or {}).get((r, c), {}).get("note") or ""]
                                    for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]])
        return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _errors(snap, touched):
        out = {}
        for shn, r1, c1, r2, c2 in touched:
            if r1 == 0:
                continue
            cells = (snap.sheets.get(shn) or {}).get("cells") or {}
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    ev = ((cells.get((r, c)) or {}).get("effectiveValue") or {}).get("errorValue")
                    if ev and ERR_LABEL.get(ev.get("type"), "x") != "":
                        out[f"{shn}!{col_letter(c)}{r}"] = ERR_LABEL.get(ev.get("type")) or "#" + str(ev.get("type"))
        return out

    # ------------------------------------------------------------ 撃つ
    def try_do(self, st, tgt, ops, tim=None):
        """直接撃てたら res（エンジンの返事と同じ形）を返す。乗らなければ None（エンジンの道へ）"""
        if st.get("direct_off") or tgt.get("kind") != "sheet" or not tgt.get("id") or tgt.get("new"):
            return None
        if not ops or any(o.get("shelf") not in DIRECT_SHELVES for o in ops):
            return None
        if any(o.get("shelf") == "write" for o in ops) and len(ops) > 1:
            # 値を書く棚を組み替えた手（write 1 本＋書式・書式の写し）だけは一緒に撃つ（書式が先・値が後）
            if not all(o.get("shelf") in ("write", "format", "fmt.copy", "cf.add", "sort", "sheet.new", "_raw", "filter.where") for o in ops):
                return None
            if sum(1 for o in ops if o.get("shelf") == "write" and not o.get("_new")) > 1:
                return None
        if any(o.get("shelf") == "fmt.copy" for o in ops) and not any(o.get("shelf") == "write" for o in ops):
            return None
        tc = self.mgr._cached_table(st, tgt) or {}
        sheet = tgt.get("sheet") or tc.get("sheet") or ""
        if not sheet:
            return None
        tb = tc.get("table")
        try:
            ranges = self._plan(ops, sheet, tb, tc.get("sheets"))
            before = self._before(st, tgt, sheet, ranges)
            if tim:
                tim.lap("直接:読む")
            if tb:      # 覚えている見出しが今の見出しと同じか（違えばエンジンの道でその場の形を見る）
                ent = before.sheet(sheet)
                now = [Snapshot.value_text(ent["cells"].get((tb["header_row"], col_num(c["col"])))) for c in tb.get("columns") or []]
                if now != [str(c.get("name")) for c in tb.get("columns") or []]:
                    return None
            req, undo, changed, touched = self._build(ops, sheet, tb, before)
            already = getattr(self, "_last_already", []) or []
            vals = [r["_values"] for r in req if "_values" in r]
            req = [r for r in req if "_values" not in r]
            if not req and not vals and already:
                out_t = {k: tgt[k] for k in ("id", "name", "kind", "url") if tgt.get(k)}
                out_t["sheet"] = sheet
                return {
                    "ok": True,
                    "target": out_t,
                    "changed": [],
                    "notes": [f"すでにその書式が当たっています（変更なし）: {'・'.join(already)}"],
                    "remaining": [],
                    "backup": 0,
                    "direct": True,
                    "already": True,
                }
            # 撃つ順: 書式など → 値 → 並べ替え（汚れを直した値で並べる）
            post = [r for r in req if "sortRange" in r or ("setBasicFilter" in r and r["setBasicFilter"]["filter"].get("filterSpecs"))] if vals else []
            req = [r for r in req if not (vals and r in post)]
            if req:
                self._call(st, "POST", SHEETS + tgt["id"] + ":batchUpdate", json={"requests": req})
            for v in vals:
                for shn, cells in v.items():
                    data = [{"range": f"{q(shn)}!{k}", "values": [[x]]} for k, x in cells.items()]
                    self._call(st, "POST", SHEETS + tgt["id"] + "/values:batchUpdate", json={"valueInputOption": "USER_ENTERED", "data": data})
            if post:
                self._call(st, "POST", SHEETS + tgt["id"] + ":batchUpdate", json={"requests": post})
            if tim:
                tim.lap("直接:撃つ")
        except (Skip, DirectError) as e:
            st["direct_last_skip"] = str(e)[:200]
            return None
        except Exception as e:     # 思わぬ形でも、直接の道では止めずにエンジンの道へ回す（まだ何も書いていない）
            st["direct_last_skip"] = f"{type(e).__name__}: {e}"[:200]
            return None
        # ここから先は書いた後。失敗してもエンジンの道へは回さない（二重に書かない）
        renamed = {o.get("name") or sheet: str(o.get("to") or "").strip() for o in ops if o.get("shelf") == "sheet.rename" and o.get("to")}
        if renamed:
            def _map_range(rng):
                for o_nm, n_nm in renamed.items():
                    pref = f"{q(o_nm)}!"
                    if rng.startswith(pref):
                        return f"{q(n_nm)}!" + rng[len(pref):]
                return rng
            ranges = sorted({_map_range(r) for r in ranges})
            touched = [(renamed.get(s, s), r1, c1, r2, c2) for s, r1, c1, r2, c2 in touched]
        notes = []
        led = st.setdefault("direct_ledger", [])
        n = (max([x["n"] for x in led], default=0) + 1)
        after_ranges = sorted(set(ranges) | {f"{q(s)}!{a1(r1, c1, r2, c2)}" for s, r1, c1, r2, c2 in touched if r1})
        if tb and any(o.get("shelf") == "write" for o in ops):
            # 検算（合計＝明細の和）・前→後は表全体で見る（書いたセルだけ読むと、明細の一部しか足せず食い違いに見える）
            _f, _l = self._table_rows(tb)
            _end = max(_l, int(tb.get("total_row") or 0))
            _lc = max([col_num(tb["last_col"])] + [c2 for s, r1, c1, r2, c2 in touched if r1 and s == sheet])
            after_ranges = sorted(set(after_ranges) | {f"{q(sheet)}!A1:{col_letter(_lc)}{_end}"})
        writes = any(o.get("shelf") in ("write", "clear.values", "sort", "rows.insert", "cols.insert") for o in ops)
        after, fp = None, None
        if writes:     # 値を書いたときは、新しいエラーを返事に入れるので、ここで読み直す
            try:
                after = self._get(st, tgt["id"], after_ranges)
                fp = self._fp(after, touched)
                if tim:
                    tim.lap("直接:読み直す")
            except Exception as e:
                notes.append(f"書いた後の読み直しに失敗しました（{type(e).__name__}）。戻すときは人の手直しを確かめられないので ok=True が要ります")
        else:          # 書式などは返事を先に返し、指紋は裏で取る（ws_undo は指紋が取れるのを待ってから比べる）
            fp = "pending"
            self._fp_later(n, st["direct_token"]["token"], tgt["id"], after_ranges, touched)
        if after is not None and tb:
            self.mgr._after_light = (tgt["id"], sheet, {"snap": after, "table": tb, "sheet": sheet})
        e0, e1 = self._errors(before, touched), (self._errors(after, touched) if after else {})
        news = [f"{k} {v}" for k, v in e1.items() if k not in e0]
        if news:
            notes.append("新しいエラー: " + "・".join(news[:5]) + (f" ほか {len(news) - 5} 件" if len(news) > 5 else ""))
        led.append({"n": n, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "id": tgt["id"], "name": tgt.get("name", ""),
                    "sheet": sheet, "what": " ／ ".join(changed)[:120], "undo": undo, "touched": touched,
                    "fp": fp, "ranges": after_ranges, "shape": any(o.get("shelf") in ("write", "clear.values", "sort", "rows.insert", "cols.insert", "sheet.rename") for o in ops)})
        del led[:-LEDGER_KEEP]
        if any(o.get("shelf") in ("write", "clear.values", "sort", "rows.insert", "cols.insert", "sheet.rename") for o in ops):
            st.pop("table_cache", None)      # 値やシート名が変わったので、次の頼みで表の形を見直す
        out_t = {k: tgt[k] for k in ("id", "name", "kind", "url") if tgt.get(k)}
        out_t["sheet"] = next((o.get("to") for o in ops if o.get("shelf") == "sheet.rename" and (o.get("name") or sheet) == sheet), None) or sheet
        already = getattr(self, "_last_already", []) or []
        if already:
            notes.append(f"すでに書式が当たっている範囲はスキップしました: {'・'.join(already)}")
        insights = []
        diff_cells = []
        verify = {"ok": True, "checks": [], "mismatch": []}
        if tb and not any(o.get("shelf") in ("sheet.rename", "sheet.delete") for o in ops):
            try:
                import gas_ws_insights
                snap_ins = after or before
                insights = gas_ws_insights.analyze_from_snapshot(snap_ins, out_t["sheet"], tb, ops=ops)
                if after:
                    b_map = snapshot_cell_map(before, sheet)
                    a_map = snapshot_cell_map(after, out_t["sheet"])
                    # 前→後は触ったセルだけで比べる（読み直しは表全体、撃つ前の読みは触るセルだけなので）
                    _rects = [(r1, c1, r2, c2) for s_, r1, c1, r2, c2 in touched if r1 and s_ in (sheet, out_t["sheet"])]
                    _in = lambda k: any(r1 <= k[0] <= r2 and c1 <= k[1] <= c2 for r1, c1, r2, c2 in _rects)
                    a_map = {k: v for k, v in a_map.items() if _in(k)}
                    b_map = {k: v for k, v in b_map.items() if _in(k)}
                    diff_cells = gas_ws_insights.diff_cell_values(b_map, a_map)
                    v_grid, f_grid, _ = snapshot_to_grids(after, out_t["sheet"], tb)
                    verify = gas_ws_insights.verify_after_do(tb, v_grid, f_grid, ops=ops)
            except Exception:
                insights = []
        return {
            "ok": True,
            "target": out_t,
            "changed": changed,
            "notes": notes,
            "remaining": [],
            "backup": f"D{n}",
            "direct": True,
            "insights": insights,
            "diff_cells": diff_cells,
            "verify": verify,
        }

    # ------------------------------------------------------------ 裏の指紋
    def _fp_later(self, n, token, sid, ranges, touched):
        fields = ("sheets(properties(sheetId,title,index,hidden,tabColorStyle,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),"
                  "basicFilter,merges,conditionalFormats,data(startRow,startColumn,rowData(values(userEnteredFormat,userEnteredValue,note,effectiveValue(errorValue))),"
                  "columnMetadata(pixelSize,hiddenByUser),rowMetadata(pixelSize,hiddenByUser)))")

        def run():
            try:
                r = requests.get(SHEETS + sid, headers={"Authorization": "Bearer " + token},
                                 params=[("ranges", x) for x in ranges] + [("fields", fields)], timeout=30)
                fp = self._fp(Snapshot(r.json()), touched) if r.status_code == 200 else None
            except Exception:
                fp = None
            with _FP_LOCK:
                try:
                    d = json.loads(FP_FILE.read_text(encoding="utf-8"))
                except Exception:
                    d = {}
                d[str(n)] = fp
                keys = sorted(d, key=lambda k: int(k))[-LEDGER_KEEP:]
                FP_FILE.write_text(json.dumps({k: d[k] for k in keys}), encoding="utf-8")

        th = threading.Thread(target=run, daemon=False)     # 道具が終わる前に指紋を書き切る（daemon にしない）
        _PENDING[n] = th
        th.start()

    @staticmethod
    def _fp_of(item):
        if item.get("fp") != "pending":
            return item.get("fp")
        th = _PENDING.get(item["n"])
        if th:
            th.join(10)
        try:
            return json.loads(FP_FILE.read_text(encoding="utf-8")).get(str(item["n"]))
        except Exception:
            return None

    # ------------------------------------------------------------ 戻す
    def latest(self, st, target_id):
        for it in reversed(st.get("direct_ledger") or []):
            if it["id"] == target_id and not it.get("undone"):
                return it
        return None

    def undo(self, st, item, ok=False):
        snap = self._get(st, item["id"], sorted(set(item["ranges"]) | {f"{q(s)}!{a1(r1, c1, r2, c2)}" for s, r1, c1, r2, c2 in item["touched"] if r1}))
        want = self._fp_of(item)
        if (want is None or self._fp(snap, item["touched"]) != want) and not ok:
            return {"ok": False, "needs_ok": True,
                    "error": f"道具が書いた後に手で直した所があります（戻すと消えます）: {item['what']}。それでも戻すなら ok=True"}
        self._call(st, "POST", SHEETS + item["id"] + ":batchUpdate", json={"requests": item["undo"]})
        item["undone"] = True
        if item.get("shape", True):      # 値やシート名を戻したときだけ、表の形を見直す（書式だけなら形は変わらない）
            st.pop("table_cache", None)
        return {"ok": True}

    # ------------------------------------------------------------ ws_look 直接の道
    def look(self, st, tgt, sheet="", range_str=""):
        """同じ呼び出しの中で同じ表をもう一度読まない（書き込みがあれば覚えを捨てる＝_call）。Sheets API の 1 分 60 回の上限のため"""
        memo = getattr(self.mgr, "_look_memo", None)
        key = (tgt.get("id"), tgt.get("kind"), sheet or "", str(range_str or ""))
        if isinstance(memo, dict) and key in memo:
            return memo[key]
        out = self._look_raw(st, tgt, sheet, range_str)
        if isinstance(memo, dict) and out is not None:
            memo[key] = out
        return out

    def _look_raw(self, st, tgt, sheet="", range_str=""):
        """Sheets API を直接叩いて actLook_ 互換の結果を返す。非対応時は None を返しエンジンへフォールバック。"""
        if tgt.get("kind") != "sheet" or not tgt.get("id") or st.get("direct_off"):
            return None
        sid = tgt["id"]
        range_str = str(range_str or "").strip()
        try:
            parsed_range = parse_a1(range_str) if range_str else None
            # トークンを先に確定させて後続の並列呼び出しでの二重取得を防ぐ
            self._token(st)
            meta_fields = (
                "spreadsheetId,properties(title),spreadsheetUrl,namedRanges,"
                "sheets(properties(sheetId,title,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)),"
                "basicFilter,bandedRanges(range),protectedRanges(range,warningOnly),"
                "rowGroups,columnGroups,"
                # 目（11/27・Excel の materials の写し）: グラフは種類と題だけでなく、横軸・系列の元の範囲と置き場所まで読む。
                # 条件付き書式も読む（撃った後に、何がどこに付いているかを値で確かめられるように）
                "conditionalFormats(ranges,booleanRule(condition(type,values(userEnteredValue)),"
                "format(textFormat(foregroundColor,bold),backgroundColor)),gradientRule(minpoint(color),maxpoint(color))),"
                "charts(chartId,position(overlayPosition(anchorCell)),"
                "spec(title,basicChart(chartType,domains(domain(sourceRange(sources))),series(series(sourceRange(sources)))),"
                "pieChart(legendPosition,domain(sourceRange(sources)),series(sourceRange(sources))))))"
            )
            meta_resp = self._call(st, "GET", SHEETS + sid, params={"fields": meta_fields})
            sheets_meta = meta_resp.get("sheets") or []
            if not sheets_meta or len(sheets_meta) >= 16:
                raise Skip("シート数制限")

            req_sheet = str(sheet or "").strip()
            if req_sheet:
                sh_meta = next((s for s in sheets_meta if (s.get("properties") or {}).get("title") == req_sheet), None)
                if not sh_meta:
                    raise Skip("シートが見つからない")
            else:
                sh_meta = sheets_meta[0]

            sh_props = sh_meta.get("properties") or {}
            sh_name = sh_props.get("title") or ""
            gp = sh_props.get("gridProperties") or {}
            grid_r = int(gp.get("rowCount") or 1000)
            grid_c = int(gp.get("columnCount") or 26)
            max_r = min(max(grid_r, 1), 2000)
            max_c = min(max(grid_c, 1), 60)
            if parsed_range and (parsed_range[2] > max_r or parsed_range[3] > max_c):
                raise Skip("範囲が上限超え")

            detail_fields = (
                "sheets(properties(sheetId,title),merges,"
                "data(startRow,startColumn,rowMetadata(hiddenByUser,hiddenByFilter),columnMetadata(hiddenByUser),"
                "rowData(values(formattedValue,effectiveValue,userEnteredValue,"
                "effectiveFormat(numberFormat(type)),dataValidation))))"
            )
            target_range = f"{q(sh_name)}!A1:{col_letter(max_c)}{max_r}"
            other_names = [
                (s.get("properties") or {}).get("title") or ""
                for s in sheets_meta
                if (s.get("properties") or {}).get("title") != sh_name
            ]

            def _fetch_detail():
                return self._call(st, "GET", SHEETS + sid, params=[("ranges", target_range), ("fields", detail_fields)])

            def _fetch_others():
                return self._call(
                    st,
                    "GET",
                    SHEETS + sid + "/values:batchGet",
                    params=[("ranges", q(n)) for n in other_names] + [("valueRenderOption", "UNFORMATTED_VALUE")],
                )

            if other_names:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as ex:
                    f1 = ex.submit(_fetch_detail)
                    f2 = ex.submit(_fetch_others)
                    detail_resp = f1.result()
                    others_resp = f2.result()
            else:
                detail_resp = _fetch_detail()
                others_resp = None

            d_sh = (detail_resp.get("sheets") or [{}])[0]
            grid_data = (d_sh.get("data") or [{}])[0]
            row_data = grid_data.get("rowData") or []
            last_r, last_c = _measure_row_data(row_data)
            if (last_r >= 2000 and grid_r > 2000) or (last_c >= 60 and grid_c > 60):
                raise Skip("データが大きすぎる")

            other_dims = {}
            if others_resp:
                vrs = others_resp.get("valueRanges") or []
                for idx, o_name in enumerate(other_names):
                    vals = vrs[idx].get("values") or [] if idx < len(vrs) else []
                    o_r = len(vals)
                    o_c = max((len(r) for r in vals), default=0)
                    other_dims[o_name] = (o_r, o_c)

            sheets_out = []
            for s in sheets_meta:
                nm = (s.get("properties") or {}).get("title") or ""
                if nm == sh_name:
                    sheets_out.append({"name": nm, "rows": last_r, "cols": last_c})
                else:
                    o_r, o_c = other_dims.get(nm, (0, 0))
                    sheets_out.append({"name": nm, "rows": o_r, "cols": o_c})

            title = (meta_resp.get("properties") or {}).get("title") or tgt.get("name") or ""
            url = meta_resp.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{sid}/edit"
            out = {
                "ok": True,
                "target": {"id": sid, "name": title, "kind": "sheet", "url": url, "sheet": sh_name},
                "sheets": sheets_out,
                "direct": True,
            }
            tb = _find_table_direct(row_data, merges=d_sh.get("merges") or [])
            if tb:
                out["table"] = tb
            side = _build_side_direct(meta_resp, sh_meta, grid_data)
            if side:
                out["side"] = side
            if parsed_range:
                rr1, cc1, rr2, cc2 = parsed_range
                out_vals, out_forms = _extract_range_direct(row_data, rr1, cc1, rr2, cc2)
                out["range"] = range_str
                out["values"] = out_vals
                out["formulas"] = out_forms
            return out
        except (Skip, DirectError) as e:
            st["direct_last_look_skip"] = str(e)[:200]
            return None
        except Exception as e:
            st["direct_last_look_skip"] = f"{type(e).__name__}: {e}"[:200]
            return None


_CHART_NAMES = {
    "COLUMN": "縦棒",
    "BAR": "横棒",
    "LINE": "折れ線",
    "PIE": "円",
    "AREA": "面",
    "SCATTER": "散布図",
    "COMBO": "複合",
    "STEPPED_AREA": "階段面",
}


def _grid_a1(g):
    if not g:
        return ""
    r0 = g.get("startRowIndex") or 0
    c0 = g.get("startColumnIndex") or 0
    if all(g.get(k) is None for k in ("startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex")):
        return "シート全体"
    a = col_letter(c0 + 1) + str(r0 + 1)
    r1 = g.get("endRowIndex")
    c1 = g.get("endColumnIndex")
    if r1 is None and c1 is None:
        return a
    if (r1 is None or r1 == r0 + 1) and (c1 is None or c1 == c0 + 1):
        return a
    return a + ":" + (col_letter(c1) if c1 is not None else "") + (str(r1) if r1 is not None else "")


def _num_runs(idx0):
    out, s, prev = [], -1, -2
    for i in idx0:
        if i == prev + 1:
            prev = i
            continue
        if s >= 0:
            out.append(str(s + 1) if s == prev else f"{s + 1}-{prev + 1}")
        s = prev = i
    if s >= 0:
        out.append(str(s + 1) if s == prev else f"{s + 1}-{prev + 1}")
    return out


def _col_runs(idx0):
    return [re.sub(r"\d+", lambda m: col_letter(int(m.group(0))), x) for x in _num_runs(idx0)]


def _cap_list(arr, n):
    return arr[:n] + [f"ほか {len(arr) - n}"] if len(arr) > n else list(arr)


def _validation_label(v):
    c = (v or {}).get("condition") or {}
    vals = [x.get("userEnteredValue") or "" for x in (c.get("values") or [])]
    ctype = str(c.get("type") or "")
    if ctype == "ONE_OF_LIST":
        return "プルダウン（" + "/".join(vals[:4]) + ("…" if len(vals) > 4 else "") + "）"
    if ctype == "ONE_OF_RANGE":
        return "プルダウン（範囲 " + re.sub(r"^=", "", str(vals[0] if vals else "")) + "）"
    if ctype == "BOOLEAN":
        return "チェックボックス"
    if ctype.startswith("NUMBER_"):
        return "数値の入力規則"
    if ctype.startswith("DATE_"):
        return "日付の入力規則"
    return ctype or "入力規則"


def _cell_is_blank(cell):
    if not isinstance(cell, dict) or not cell:
        return True
    fv = cell.get("formattedValue")
    if fv is not None and str(fv).strip() != "":
        return False
    ev = cell.get("effectiveValue") or {}
    if not ev:
        return True
    for k in ("stringValue", "numberValue", "boolValue", "errorValue"):
        if k in ev:
            if k == "stringValue" and str(ev[k]).strip() == "":
                return True
            return False
    return True


def _cell_text(cell):
    if not isinstance(cell, dict):
        return ""
    if cell.get("formattedValue") is not None:
        return str(cell["formattedValue"])
    ev = cell.get("effectiveValue") or {}
    for k in ("stringValue", "numberValue", "boolValue"):
        if k in ev:
            x = ev[k]
            if k == "numberValue" and isinstance(x, float) and x.is_integer():
                x = int(x)
            return str(x)
    return ""


def _cell_is_number(cell):
    if not isinstance(cell, dict):
        return False
    ev = cell.get("effectiveValue") or {}
    if ev.get("numberValue") is None:
        return False
    nf_type = (((cell.get("effectiveFormat") or {}).get("numberFormat") or {}).get("type") or "").upper()
    return nf_type not in ("DATE", "DATE_TIME", "TIME")


def _measure_row_data(row_data):
    last_r, last_c = 0, 0
    for r_idx, row in enumerate(row_data, 1):
        vals = (row or {}).get("values") or []
        row_last_c = 0
        for c_idx, cell in enumerate(vals, 1):
            if not _cell_is_blank(cell):
                row_last_c = c_idx
        if row_last_c > 0:
            last_r = r_idx
            if row_last_c > last_c:
                last_c = row_last_c
    return last_r, last_c


def _find_table_direct(row_data, merges=None):
    if not row_data:
        return None
    grid_rows = [(r or {}).get("values") or [] for r in row_data]
    lr, lc = _measure_row_data(row_data)
    if lr < 1 or lc < 1:
        return None

    def _non_empty_count(row_cells):
        return sum(1 for cell in row_cells if not _cell_is_blank(cell))

    def _cell_at(r0, c0):
        row = grid_rows[r0] if r0 < len(grid_rows) else []
        return row[c0] if c0 < len(row) else {}

    norm_merges = []
    for m in (merges or []):
        r1 = m.get("startRowIndex", 0)
        c1 = m.get("startColumnIndex", 0)
        r2 = m.get("endRowIndex", r1 + 1) - 1
        c2 = m.get("endColumnIndex", c1 + 1) - 1
        if r2 >= r1 and c2 >= c1:
            norm_merges.append((r1, c1, r2, c2))

    def _has_row_merge(r0):
        for r1, c1, r2, c2 in norm_merges:
            if (r1 == r0 and r2 == r0 and c2 > c1) or (r1 == r0 and r2 == r0 + 1):
                return True
        return False

    def _find_merge_at(r0, c0):
        for m in norm_merges:
            if m[0] <= r0 <= m[2] and m[1] <= c0 <= m[3]:
                return m
        return None

    h = -1
    for r in range(lr):
        if _non_empty_count(grid_rows[r]) >= 2:
            h = r
            break
    for _ in range(10):
        if h < 0 or _has_row_merge(h):
            break
        nx = h + 1
        while nx < lr and _non_empty_count(grid_rows[nx]) == 0:
            nx += 1
        if nx < lr and _non_empty_count(grid_rows[nx]) >= 2 * _non_empty_count(grid_rows[h]):
            h = nx
        else:
            break
    if h < 0:
        return None

    hdr = grid_rows[h]
    fc, lcol = -1, -1
    for c in range(len(hdr)):
        if not _cell_is_blank(hdr[c]):
            if fc < 0:
                fc = c
            lcol = c
    for r1, c1, r2, c2 in norm_merges:
        if r1 == h and r2 == h and c2 > c1 and not _cell_is_blank(_cell_at(h, c1)):
            if fc < 0 or c1 < fc:
                fc = c1
            if c2 > lcol:
                lcol = c2
    if fc < 0:
        return None

    # 2 段見出しの検出（結合された上段＋下段、または相補的な 2 行見出し）
    header_rows = 1
    if h + 2 < lr:
        sub_non_empty, sub_num_cnt, sub_first = 0, 0, ""
        for sc in range(lc):
            c_obj = _cell_at(h + 1, sc)
            if not _cell_is_blank(c_obj):
                sub_non_empty += 1
                if not sub_first:
                    sub_first = _cell_text(c_obj).strip()
                ev = (c_obj or {}).get("effectiveValue") or {}
                if ev.get("numberValue") is not None:
                    sub_num_cnt += 1
        sub_is_total = bool(re.match(r"^(合計|総計|小計|計|total|sum)", sub_first, re.I))
        if sub_non_empty > 0 and not sub_is_total:
            horiz_match, vert_match = False, False
            for r1, c1, r2, c2 in norm_merges:
                if r1 == h and r2 == h and c2 > c1 and not _cell_is_blank(_cell_at(h, c1)):
                    sub_under = sum(1 for cc3 in range(c1, c2 + 1) if not _cell_is_blank(_cell_at(h + 1, cc3)))
                    if sub_under >= 2:
                        horiz_match = True
                        break
                if r1 == h and r2 == h + 1 and not _cell_is_blank(_cell_at(h, c1)):
                    vert_match = True
            unmerged_two_tier = False
            if not horiz_match and not vert_match and sub_num_cnt == 0:
                top_gap_filled = sum(
                    1 for cc4 in range(fc, lcol + 1)
                    if _cell_is_blank(_cell_at(h, cc4)) and not _cell_is_blank(_cell_at(h + 1, cc4))
                )
                if top_gap_filled >= 1:
                    unmerged_two_tier = True
            if horiz_match or (vert_match and sub_num_cnt == 0) or unmerged_two_tier:
                header_rows = 2
                for cc5 in range(lc):
                    if not _cell_is_blank(_cell_at(h + 1, cc5)):
                        if fc < 0 or cc5 < fc:
                            fc = cc5
                        if cc5 > lcol:
                            lcol = cc5

    header_names = []
    if header_rows == 2:
        last_top = ""
        for hc in range(fc, lcol + 1):
            m_top = _find_merge_at(h, hc)
            m_sub = _find_merge_at(h + 1, hc)
            top_cell = _cell_at(m_top[0], m_top[1]) if m_top else _cell_at(h, hc)
            top_str = "" if _cell_is_blank(top_cell) else _cell_text(top_cell).strip()
            same_vert = bool(m_top and m_sub and m_top == m_sub)
            sub_cell = {} if same_vert else _cell_at(h + 1, hc)
            sub_str = "" if _cell_is_blank(sub_cell) else _cell_text(sub_cell).strip()
            if top_str:
                last_top = top_str
            elif not m_top and sub_str and last_top:
                top_str = last_top
            if top_str and sub_str and top_str != sub_str:
                header_names.append(f"{top_str}・{sub_str}")
            else:
                header_names.append(top_str or sub_str or "")
    else:
        for hc in range(fc, lcol + 1):
            c_obj = _cell_at(h, hc)
            header_names.append("" if _cell_is_blank(c_obj) else _cell_text(c_obj))

    data_start0 = h + header_rows
    last = data_start0 - 1
    for r2 in range(data_start0, lr):
        if any(not _cell_is_blank(_cell_at(r2, cc)) for cc in range(fc, lcol + 1)):
            last = r2

    header_row = h + 1
    first_col = fc + 1
    last_col = lcol + 1
    first_data = data_start0 + 1
    last_data = last + 1
    total_row = None

    # 合計行・末尾集計ブロック：最終行から上に向かって連続する 合計/小計/消費税 等を明細から除外する（workspace_engine.gs findTable_ と同じ型）
    footer_end = last
    while footer_end >= data_start0 + 1:
        first_txt = ""
        for fcx in range(fc, lcol + 1):
            c_obj = _cell_at(footer_end, fcx)
            if not _cell_is_blank(c_obj):
                first_txt = _cell_text(c_obj)
                break
        if not _FOOTER_LABEL_RE.match(first_txt.strip()):
            break
        if total_row is None:
            total_row = footer_end + 1
        last_data = footer_end
        footer_end -= 1

    columns = []
    for idx, ci in enumerate(range(first_col, last_col + 1)):
        name = header_names[idx]
        n_num, tot = 0, 0
        for rr in range(first_data, last_data + 1):
            c_obj = _cell_at(rr - 1, ci - 1)
            if _cell_is_blank(c_obj):
                continue
            tot += 1
            if _cell_is_number(c_obj):
                n_num += 1
        columns.append({
            "col": col_letter(ci),
            "name": name,
            "number": (tot > 0 and n_num / tot > 0.5),
        })

    out = {
        "header_row": header_row,
        "first_col": col_letter(first_col),
        "last_col": col_letter(last_col),
        "data": f"{first_data}-{last_data}",
        "total_row": total_row,
        "columns": columns,
    }
    if header_rows > 1:
        out["header_rows"] = header_rows
    return out


def _build_side_direct(meta_resp, sh_meta, grid_data):
    lines = []
    row_data = (grid_data or {}).get("rowData") or []
    if row_data:
        by_sig = {}
        for r_idx, row in enumerate(row_data):
            for c_idx, cell in enumerate((row or {}).get("values") or []):
                dv = (cell or {}).get("dataValidation")
                if dv:
                    k = _validation_label(dv)
                    by_sig.setdefault(k, []).append((r_idx, c_idx))
        vparts = []
        for k, coords in by_sig.items():
            cols = {}
            for rc in coords:
                cols.setdefault(rc[1], []).append(rc[0])
            runs_by_key = {}
            for c in sorted(cols.keys()):
                for rr in _num_runs(cols[c]):
                    m = rr.split("-")
                    runs_by_key.setdefault(rr, {"r": m, "cols": []})["cols"].append(c)
            for o in runs_by_key.values():
                cs = o["cols"]
                st_c = pv_c = cs[0]
                for i in range(1, len(cs) + 1):
                    if i < len(cs) and cs[i] == pv_c + 1:
                        pv_c = cs[i]
                        continue
                    a_cell = col_letter(st_c + 1) + o["r"][0]
                    b_cell = col_letter(pv_c + 1) + (o["r"][1] if len(o["r"]) > 1 else o["r"][0])
                    vparts.append((a_cell if a_cell == b_cell else f"{a_cell}:{b_cell}") + f" {k}")
                    if i < len(cs):
                        st_c = pv_c = cs[i]
        if vparts:
            lines.append("入力規則: " + "、".join(_cap_list(vparts, 4)))

    banded = (sh_meta or {}).get("bandedRanges") or []
    if banded:
        lines.append("交互の色: " + "、".join(_cap_list([_grid_a1(b.get("range")) for b in banded], 3)))

    prot = [
        _grid_a1(p.get("range")) + ("（警告のみ）" if p.get("warningOnly") else "")
        for p in ((sh_meta or {}).get("protectedRanges") or [])
    ]
    if prot:
        lines.append("保護: " + "、".join(_cap_list(prot, 3)))

    bf = (sh_meta or {}).get("basicFilter")
    if bf:
        cr = [col_letter(int(k) + 1) for k in (bf.get("criteria") or {}).keys()]
        lines.append("フィルタ: " + _grid_a1(bf.get("range")) + (f"（{'・'.join(cr)} 列で絞り込み中）" if cr else ""))

    if grid_data:
        row_meta = grid_data.get("rowMetadata") or []
        hr = [i for i, m in enumerate(row_meta) if m and m.get("hiddenByUser")]
        hc = [i for i, m in enumerate(grid_data.get("columnMetadata") or []) if m and m.get("hiddenByUser")]
        hp = []
        if hr:
            hp.append("隠した行: " + "、".join(_cap_list(_num_runs(hr), 4)))
        if hc:
            hp.append("隠した列: " + "、".join(_cap_list(_col_runs(hc), 4)))
        if hp:
            lines.append(" ／ ".join(hp))
        filt_hidden = [i + 1 for i, m in enumerate(row_meta) if (m or {}).get("hiddenByFilter")]
        if filt_hidden:
            # 表のデータ行範囲が分かれば表示中の行番号を出す
            tb_f = None
            try:
                tb_f = _find_table_direct((grid_data or {}).get("rowData") or [])
            except Exception:
                tb_f = None
            if tb_f and tb_f.get("data"):
                d_parts = str(tb_f["data"]).split("-")
                if len(d_parts) == 2:
                    r_d1, r_d2 = int(d_parts[0]), int(d_parts[1])
                    shown_data = [r for r in range(r_d1, r_d2 + 1) if r not in filt_hidden]
                    lines.append(
                        f"絞り込み表示中: {'・'.join(str(r) for r in shown_data[:10])}行目"
                        + (f" ほか{len(shown_data) - 10}件" if len(shown_data) > 10 else "")
                        + f"（全{r_d2 - r_d1 + 1}件中 {len(shown_data)}件）"
                    )

    gp = []
    for g in (sh_meta or {}).get("rowGroups") or []:
        rng = g.get("range") or {}
        gp.append(
            f"行 {(rng.get('startIndex') or 0) + 1}-{rng.get('endIndex')}（深さ{g.get('depth')}"
            + ("・畳んである" if g.get("collapsed") else "")
            + "）"
        )
    for g in (sh_meta or {}).get("columnGroups") or []:
        rng = g.get("range") or {}
        gp.append(
            f"列 {col_letter((rng.get('startIndex') or 0) + 1)}-{col_letter(rng.get('endIndex'))}（深さ{g.get('depth')}"
            + ("・畳んである" if g.get("collapsed") else "")
            + "）"
        )
    if gp:
        lines.append("グループ: " + "、".join(_cap_list(gp, 3)))

    nm = [f"{n.get('name')}={_grid_a1(n.get('range'))}" for n in ((meta_resp or {}).get("namedRanges") or [])]
    if nm:
        lines.append("名前付き範囲: " + "、".join(_cap_list(nm, 4)))

    id2name = {(s.get("properties") or {}).get("sheetId"): (s.get("properties") or {}).get("title") or ""
               for s in ((meta_resp or {}).get("sheets") or [])}
    my_name = ((sh_meta or {}).get("properties") or {}).get("title") or ""

    gprops = ((sh_meta or {}).get("properties") or {}).get("gridProperties") or {}
    fr, fc = int(gprops.get("frozenRowCount") or 0), int(gprops.get("frozenColumnCount") or 0)
    if fr or fc:
        lines.append("固定: " + "・".join(([f"上 {fr} 行"] if fr else []) + ([f"左 {fc} 列"] if fc else [])))

    cfs = []
    for cf in (sh_meta or {}).get("conditionalFormats") or []:
        rngs = "・".join(_grid_a1(r) for r in (cf.get("ranges") or [])[:2])
        br = cf.get("booleanRule")
        if br:
            cond = br.get("condition") or {}
            vals = [str(v.get("userEnteredValue") or "") for v in (cond.get("values") or [])]
            ctype = str(cond.get("type") or "")
            what = ("式 " + vals[0]) if ctype == "CUSTOM_FORMULA" and vals else (ctype + (" " + "・".join(vals) if vals else ""))
            fmt = br.get("format") or {}
            look = []
            tf = fmt.get("textFormat") or {}
            if tf.get("foregroundColor"):
                look.append("文字色 " + _color_hex(tf["foregroundColor"]))
            if tf.get("bold"):
                look.append("太字")
            if fmt.get("backgroundColor"):
                look.append("塗り " + _color_hex(fmt["backgroundColor"]))
            cfs.append(f"{rngs} {what} → {'・'.join(look) or '書式'}")
        elif cf.get("gradientRule"):
            cfs.append(f"{rngs} 色の段階（カラースケール）")
    if cfs:
        lines.append("条件付き書式: " + "、".join(_cap_list(cfs, 4)))

    ch = []
    for c in (sh_meta or {}).get("charts") or []:
        s = c.get("spec") or {}
        bc = s.get("basicChart") or {}
        pc = s.get("pieChart") or {}
        ty = bc.get("chartType") or ("PIE" if pc else "")
        if bc:
            dom = [_src_a1(d.get("domain"), id2name, my_name) for d in (bc.get("domains") or [])]
            ser = [_src_a1(x.get("series"), id2name, my_name) for x in (bc.get("series") or [])]
        else:
            dom = [_src_a1(pc.get("domain"), id2name, my_name)] if pc.get("domain") else []
            ser = [_src_a1(pc.get("series"), id2name, my_name)] if pc.get("series") else []
        parts = []
        if dom:
            parts.append("横軸 " + "・".join(x for x in dom if x))
        if ser:
            parts.append(f"系列 {len(ser)} 本 " + "・".join(x for x in ser if x))
        anc = ((c.get("position") or {}).get("overlayPosition") or {}).get("anchorCell") or {}
        if anc:
            parts.append("置き場所 " + col_letter(int(anc.get("columnIndex") or 0) + 1) + str(int(anc.get("rowIndex") or 0) + 1))
        ch.append((_CHART_NAMES.get(ty) or ty or "グラフ") + (f"「{s.get('title')}」" if s.get("title") else "")
                  + (f"（{'／'.join(parts)}）" if parts else ""))
    if ch:
        lines.append("グラフ: " + "、".join(_cap_list(ch, 4)))
    return lines


def _src_a1(chart_data, id2name, my_name):
    """グラフの横軸・系列の元（ChartData.sourceRange.sources）を「シート!A1:A6」に。今のシートなら名前を省く"""
    out = []
    for g in (((chart_data or {}).get("sourceRange") or {}).get("sources") or []):
        nm = id2name.get(g.get("sheetId"), "")
        a1 = _grid_a1(g)
        out.append(a1 if (not nm or nm == my_name) else f"{nm}!{a1}")
    return ",".join(out)


def _color_hex(c):
    try:
        return "#" + "".join(f"{int(round(float(c.get(k) or 0) * 255)):02X}" for k in ("red", "green", "blue"))
    except Exception:
        return "色"


def _extract_range_direct(row_data, rr1, cc1, rr2, cc2):
    out_vals, out_forms = [], []
    for r in range(rr1 - 1, rr2):
        row_cells = (row_data[r].get("values") or []) if r < len(row_data) else []
        v_row, f_row = [], []
        for c in range(cc1 - 1, cc2):
            cell = row_cells[c] if c < len(row_cells) else {}
            v_row.append(str(cell.get("formattedValue") or "") if isinstance(cell, dict) else "")
            uev = (cell.get("userEnteredValue") or {}) if isinstance(cell, dict) else {}
            f_row.append(str(uev.get("formulaValue") or ""))
        out_vals.append(v_row)
        out_forms.append(f_row)
    return out_vals, out_forms


def fetch_sheet_snapshot_light(mgr, st, sid, sheet_name, range_str="A1:Z60"):
    """気づき分析・確認用に 1 シートの値・数式・表構造を軽量（1 リクエスト）で取得する。"""
    if not sid or not sheet_name or st.get("direct_off"):
        return None
    try:
        runner = DirectRunner(mgr)
        fields = _FULL_FIELDS     # 直の道の撃つ前の読みと同じ欄（撃つ前にもう一度読まずに使い回す）
        rng = f"{q(sheet_name)}!{range_str}"
        resp = runner._call(st, "GET", SHEETS + sid, params=[("ranges", rng), ("fields", fields)])
        d_sh = (resp.get("sheets") or [{}])[0]
        grid_data = (d_sh.get("data") or [{}])[0]
        row_data = grid_data.get("rowData") or []
        tb = _find_table_direct(row_data, merges=d_sh.get("merges") or [])
        if not tb:
            return None
        snap = Snapshot(resp)
        return {"snap": snap, "table": tb, "sheet": sheet_name}
    except Exception:
        return None


def snapshot_cell_map(snap, sheet_name):
    """Snapshot の指定シートから {(r, c): formatted_text} 辞書を取り出す。"""
    if not snap or not sheet_name:
        return {}
    try:
        ent = snap.sheet(sheet_name)
    except Exception:
        return {}
    out = {}
    for (r, c), cell in (ent.get("cells") or {}).items():
        txt = Snapshot.display_text(cell)
        if txt != "":
            out[(r, c)] = txt
    return out


def snapshot_to_grids(snap, sheet_name, tb=None):
    """Snapshot の指定シートから (values_grid, formulas_grid, cell_map) を生成する。"""
    if not snap or not sheet_name:
        return [], [], {}
    try:
        ent = snap.sheet(sheet_name)
    except Exception:
        return [], [], {}
    cells = ent.get("cells") or {}
    if not cells:
        return [], [], {}
    max_r = max((r for r, _ in cells.keys()), default=0)
    max_c = max((c for _, c in cells.keys()), default=0)
    if tb and tb.get("total_row"):
        max_r = max(max_r, int(tb["total_row"]))
    v_grid, f_grid, cmap = [], [], {}
    for r in range(1, max_r + 1):
        v_row, f_row = [], []
        for c in range(1, max_c + 1):
            cell = cells.get((r, c)) or {}
            ev = cell.get("effectiveValue") or {}
            if "numberValue" in ev and not (
                (((cell.get("effectiveFormat") or {}).get("numberFormat") or {}).get("type") or "").upper()
                in ("DATE", "DATE_TIME", "TIME")
            ):
                v_row.append(ev["numberValue"])
            else:
                fv = cell.get("formattedValue")
                if fv is not None:
                    v_row.append(str(fv))
                elif "stringValue" in ev:
                    v_row.append(str(ev["stringValue"]))
                elif "numberValue" in ev:
                    v_row.append(ev["numberValue"])
                else:
                    v_row.append("")
            uv = (cell.get("userEnteredValue") or {}).get("formulaValue") or ""
            f_row.append(str(uv))
            txt = Snapshot.display_text(cell)
            if txt != "":
                cmap[(r, c)] = txt
        v_grid.append(v_row)
        f_grid.append(f_row)
    return v_grid, f_grid, cmap


def fetch_workbook_payload_for_diagnosis(mgr, st, sid, sheet_names=None, range_str="A1:Z60"):
    """全シートの表・値・数式を 1 リクエストで軽量取得し、ブック健診用のペイロードを返す。"""
    if not sid or st.get("direct_off"):
        return []
    try:
        runner = DirectRunner(mgr)
        fields = (
            "sheets(properties(sheetId,title),basicFilter,merges,"
            "data(startRow,startColumn,rowData(values(formattedValue,effectiveValue,userEnteredValue,"
            "effectiveFormat(numberFormat(type))))))"
        )
        params = [("fields", fields)]
        if sheet_names:
            for nm in sheet_names[:15]:
                params.append(("ranges", f"{q(nm)}!{range_str}"))
        else:
            params.append(("includeGridData", "true"))
        resp = runner._call(st, "GET", SHEETS + sid, params=params)
        snap = Snapshot(resp)
        out = []
        for d_sh in resp.get("sheets") or []:
            nm = (d_sh.get("properties") or {}).get("title") or ""
            grid_data = (d_sh.get("data") or [{}])[0]
            row_data = grid_data.get("rowData") or []
            tb = _find_table_direct(row_data, merges=d_sh.get("merges") or [])
            v_grid, f_grid, _ = snapshot_to_grids(snap, nm, tb)
            side = ["フィルタ"] if d_sh.get("basicFilter") else []
            out.append({"sheet": nm, "table": tb, "values": v_grid, "formulas": f_grid, "side": side})
        return out
    except Exception:
        return []


# ------------------------------------------------------------ 式の木（Excel マネージャーの trace の写し・11/27）
_TRACE_STR_RE = re.compile(r'"(?:[^"]|"")*"')
_TRACE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:(?:'((?:[^']|'')+)'|([^\s'!(),=+\-*/&^<>:;{}\"]+))!)?"
    r"(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)(?![\w(])")


def _trace_refs(formula, cur_sheet):
    """式の中の参照を [(シート, 'A1' か 'A1:B9')] に（文字列の中は見ない・同じ物は 1 回）"""
    body = _TRACE_STR_RE.sub('""', str(formula or ""))
    out = []
    for m in _TRACE_REF_RE.finditer(body):
        sh = (m.group(1) or "").replace("''", "'") or m.group(2) or cur_sheet
        a1 = m.group(3).replace("$", "").upper()
        if (sh, a1) not in out:
            out.append((sh, a1))
    return out


def trace(mgr, st, sid, sheet, cell, depth=3, max_nodes=40):
    """セルの式がどこから来ているかを、シートをまたいで木で返す（行のリスト）。
    1 セルは値と式、範囲は大きさ・式の数・数の和を出し、範囲の中の式は 3 つまで辿る。"""
    runner = DirectRunner(mgr)
    runner._token(st)
    cache = {}

    def grab(sh, a1):
        key = (sh, a1)
        if key not in cache:
            rng = f"{q(sh)}!{a1}"
            res = {}
            for opt in ("FORMULA", "FORMATTED_VALUE", "UNFORMATTED_VALUE"):
                r = runner._call(st, "GET", SHEETS + sid + "/values:batchGet",
                                 params=[("ranges", rng), ("valueRenderOption", opt)])
                res[opt] = ((r.get("valueRanges") or [{}])[0].get("values")) or []
            cache[key] = res
        return cache[key]

    lines, seen, count = [], set(), [0]

    def cell_line(sh, a1, level):
        if count[0] >= max_nodes:
            return
        count[0] += 1
        ind = "  " * level
        if (sh, a1) in seen:
            lines.append(f"{ind}{sh}!{a1}（上に出た）")
            return
        seen.add((sh, a1))
        g = grab(sh, a1)
        f = str((g["FORMULA"][0][0] if g["FORMULA"] and g["FORMULA"][0] else "") or "")
        v = str((g["FORMATTED_VALUE"][0][0] if g["FORMATTED_VALUE"] and g["FORMATTED_VALUE"][0] else "") or "")
        lines.append(f"{ind}{sh}!{a1} = {v or '(空)'}" + (f"   式 {f}" if f.startswith("=") else ""))
        if not f.startswith("=") or level >= depth:
            return
        for rsh, ra1 in _trace_refs(f, sh):
            if ":" not in ra1:
                cell_line(rsh, ra1, level + 1)
                continue
            if count[0] >= max_nodes:
                return
            count[0] += 1
            g2 = grab(rsh, ra1)
            r1, c1, _r2, _c2 = parse_a1(ra1)
            n = sum(len(r) for r in g2["UNFORMATTED_VALUE"])
            fcells = []
            for i, row in enumerate(g2["FORMULA"]):
                for j, x in enumerate(row):
                    if str(x).startswith("="):
                        fcells.append(f"{col_letter(c1 + j)}{r1 + i}")
            nums = [x for row in g2["UNFORMATTED_VALUE"] for x in row if isinstance(x, (int, float)) and not isinstance(x, bool)]
            texts = [x for row in g2["UNFORMATTED_VALUE"] for x in row if isinstance(x, str) and x.strip()]
            lines.append(f"{'  ' * (level + 1)}{rsh}!{ra1}（値 {n} 個・数 {len(nums)} 個の和 {sum(nums):,.0f}"
                         + (f"・文字 {len(texts)} 個（例 {texts[0]}）" if texts else "")
                         + (f"・式 {len(fcells)} 個" if fcells else "") + "）")
            for fa in fcells[:3]:
                cell_line(rsh, fa, level + 2)
    cell_line(sheet, cell, 0)
    if count[0] >= max_nodes:
        lines.append(f"（{max_nodes} か所で打ち切り）")
    return lines


# ---------------------------------------------------------------- 値を書く棚の組み替え（直の道に乗せる）
# エンジン（workspace_engine.gs ＋ ws_shelves）の棚と同じ結果になる「普通の場合」だけを write（値と式）＋ format ＋ fmt.copy に組み替える。
# 日付・2 段見出し・列の差し込み・人の判断が要る物は組み替えず None を返す（エンジンの道へ）。
# 棚の振る舞いを変えたら、ここも同じに直す（sheet_filter.gs の seiri・sheet_range.gs の phone.fix・sheet_formula.gs の calc.tax/calc.col・sheet_make.gs の total）
# 写した時の、エンジンの棚の本体の指紋（sha1 の頭 12 字）。エンジンの棚を書き換えると指紋が変わり、
# その棚は組み替えず（直の道に乗せず）エンジンの道で撃つ＝2 か所の食い違いで結果が変わることはない。
# ws-check がずれを知らせる。ここの写しを同じに直したら、gas('ws-check') が出す新しい指紋に書き換える
LOWER_PINS = {"seiri": "ae95f8b5af9a", "phone.fix": "3c0eeebff844", "calc.tax": "47d88fc63fa5",
              "calc.col": "2a5fb1eec63c", "total": "8f6db18212fd", "cf.add": "18a2eabb5f69",
              "sort": "741d5c81681c", "filter.extract": "1ffd5f88061c", "summary": "422d47d5ed6a", "chart.new": "b2a2fd2707d1"}


def _shelf_pin(name):
    import hashlib
    import gas_workspace
    body = (gas_workspace.CATALOG.by_name.get(name) or {}).get("body") or ""
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def lower_pin_ok(name):
    try:
        return LOWER_PINS.get(name) == _shelf_pin(name)
    except Exception:
        return False


def lower_pin_problems():
    """ws-check 用: 直の道の写しが、今のエンジンの棚と違う物"""
    out = []
    for n, pin in LOWER_PINS.items():
        now = _shelf_pin(n)
        if now != pin:
            out.append(f"直の道の写し（gas_ws_direct.lower_ops / cf.add）の対の棚「{n}」が書き換わっています（指紋 {pin} → {now}）。"
                       f"今は {n} をエンジンの道で撃っています。写しを同じに直してから LOWER_PINS を {now} に")
    return out


_FULL_FIELDS = ("sheets(properties(sheetId,title,index,hidden,tabColorStyle,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),"
                "basicFilter,merges,conditionalFormats,data(startRow,startColumn,rowData(values(userEnteredFormat,"
                "effectiveFormat(backgroundColorStyle,backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy,numberFormat),"
                "userEnteredValue,note,effectiveValue(errorValue,numberValue,stringValue,boolValue),formattedValue)),"
                "columnMetadata(pixelSize,hiddenByUser),rowMetadata(pixelSize,hiddenByUser)))")

_LOW_NUM_FMT = "#,##0"
_LOW_CODE_HEAD = re.compile(r"(?:郵便|〒|電話|携帯|TEL|FAX|社員番号|社員ID|会員番号|会員ID|顧客番号|顧客ID|管理番号|注文番号|伝票番号|口座番号|商品コード|コード|品番|型番)", re.I)
_LOW_NUM_RE = re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$")
_LOW_AUTO_PARSE = re.compile(r"^[=+\-@]|^\s*[-+]?[\d０-９][\d０-９,，.．/／:：\-－年月日%％\s]*$|^(true|false)$", re.I)
_LOW_NO_SUM_HEAD = re.compile(r"(?:単価|価格|率|％|%|平均|割合|年齢|日付|年月)")


def _zen2han(s):
    return re.sub(r"[！-～]", lambda m: chr(ord(m.group(0)) - 0xFEE0), s).replace("　", " ")


def _low_phone(raw):
    """phone.fix の fmtPhone と同じ"""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw).is_integer() and raw > 0:
        s = str(int(raw))
        if len(s) in (9, 10):
            s = "0" + s
    elif isinstance(raw, str):
        s = raw.strip()
    else:
        return None
    if not s:
        return None
    h = re.sub(r"[０-９]", lambda m: chr(ord(m.group(0)) - 0xFEE0), s)
    h = re.sub(r"[－ー―‐−]", "-", h).replace("（", "(").replace("）", ")").replace("　", " ")
    d = re.sub(r"[^\d]", "", h)
    if len(d) < 10 or len(d) > 11 or d[0] != "0":
        return None
    if len(d) == 11:
        if d.startswith("0800"):
            return f"{d[:4]}-{d[4:7]}-{d[7:]}"
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if d.startswith("0120"):
        return f"{d[:4]}-{d[4:7]}-{d[7:]}"
    if re.match(r"^0[36]", d):
        return f"{d[:2]}-{d[2:6]}-{d[6:]}"
    grp = [x for x in re.split(r"[\s\-]+", re.sub(r"[()]", " ", h).strip()) if re.fullmatch(r"\d+", x)]
    if len(grp) == 3 and "".join(grp) == d and 2 <= len(grp[0]) <= 5 and len(grp[2]) == 4:
        return "-".join(grp)
    return f"{d[:3]}-{d[3:6]}-{d[6:]}"


def _low_serial_date(n):
    from datetime import date, timedelta
    try:
        return date(1899, 12, 30) + timedelta(days=int(float(n)))
    except Exception:
        return None


def _low_cmp_date(val, is_date_num, fy):
    """セルの値・比べる値を日付に（エンジンの parseCmpDate_）。日付でなければ None"""
    from datetime import date
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return _low_serial_date(val) if is_date_num else None
    if not isinstance(val, str) or not val.strip():
        return None
    import gas_ws_ask
    d = gas_ws_ask._parse_cmp_date_str(val)
    if not d:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", d)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{2})/(\d{2})", d)
    try:
        return date(int(fy), int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def _low_match(cv, is_date_num, when, target, fy):
    """エンジンの matchRowCond_ と同じ"""
    w = str(when or "").lower()
    if w == "not_blank":
        w = "notblank"
    blank = cv in (None, "")
    if w == "blank":
        return blank
    if w == "notblank":
        return not blank
    ts = "" if target is None else str(target)
    cs = "" if blank else (str(int(cv)) if isinstance(cv, float) and cv.is_integer() else str(cv))
    if w == "contains":
        return ts in cs
    if w == "between":
        if ".." not in ts or blank:
            return False
        a0, b0 = ts.split("..", 1)
        d1, d2 = _low_cmp_date(a0, False, fy), _low_cmp_date(b0, False, fy)
        if not d1 or not d2:
            return False
        lo, hi = min(d1, d2), max(d1, d2)
        c = _low_cmp_date(cv, is_date_num, fy)
        return bool(c and lo <= c <= hi)
    tn = ts.replace(",", "").strip()
    is_tn = bool(re.fullmatch(r"-?\d+(?:\.\d+)?", tn))
    td = _low_cmp_date(ts, False, fy) if not is_tn else None
    if td:
        if blank:
            return False
        c = _low_cmp_date(cv, is_date_num, fy)
        if not c:
            return w == "ne"
        return {"gt": c > td, "ge": c >= td, "lt": c < td, "le": c <= td, "ne": c != td}.get(w, c == td)
    if w == "ne":
        if re.fullmatch(r"-?[\d,]+(\.\d+)?", ts.strip()) and isinstance(cv, (int, float)) and not isinstance(cv, bool):
            return cv != float(ts.replace(",", ""))
        return cs != ts
    if w in ("gt", "ge", "lt", "le"):
        try:
            c = float(cv) if isinstance(cv, (int, float)) and not isinstance(cv, bool) else float(str(cv).replace(",", ""))
            t = float(ts.replace(",", ""))
        except (TypeError, ValueError):
            return False
        return {"gt": c > t, "ge": c >= t, "lt": c < t, "le": c <= t}[w]
    return None      # eq などのほかの型はこの写しでは決めない（呼んだ側がエンジンの道へ）


def lower_ops(ops, light, sheet, sheet_names=None, light_of=None, ok=False):
    """ops を直の道で撃てる形に組み替える。戻り値 (新しい ops, 直した所の文[]) か None（組み替えない）"""
    if not light or not light.get("table") or not ops:
        return None
    tb = light["table"]
    if int(tb.get("header_rows") or 1) > 1:
        return None
    m = re.fullmatch(r"(\d+)-(\d+)", str(tb.get("data") or ""))
    if not m:
        return None
    r_a, r_b = int(m.group(1)), int(m.group(2))
    hr = int(tb["header_row"])
    tot = int(tb.get("total_row") or 0)
    cells = (light["snap"].sheet(sheet).get("cells")) or {}
    cols = tb.get("columns") or []
    name2c = {str(c.get("name") or "").strip(): col_num(c["col"]) for c in cols if c.get("col")}
    first_c, last_c = col_num(tb["first_col"]), col_num(tb["last_col"])
    writes, fmts, copies, said, sorts = {}, [], [], [], []
    news, new_writes, notes = [], [], []          # 新しいシート（抽出・集計）とグラフ
    names_now = list(sheet_names or [])
    mem = {}                                       # 作ったシートの中身（続く手の元になる）
    conv = []                                      # 日付の比べを式に組み替えた印（書く物が無くても直の道へ）

    def cell(r, c):
        return cells.get((r, c)) or {}

    def formula(r, c):
        return str(((cell(r, c).get("userEnteredValue")) or {}).get("formulaValue") or "")

    def raw(r, c):
        uv = cell(r, c).get("userEnteredValue") or {}
        if "stringValue" in uv:
            return uv["stringValue"]
        if "numberValue" in uv:
            return uv["numberValue"]
        return None

    def col_of(name):
        k = str(name or "").strip()
        if k in name2c:
            return name2c[k]
        if re.fullmatch(r"[A-Z]{1,3}", k):
            return col_num(k)
        return None

    def put(r, c, v):
        k = f"{col_letter(c)}{r}"
        if k in writes:
            raise Skip("同じセルを 2 回書く")
        writes[k] = v

    def ev(r, c, depth=0):
        """今の値（この呼び出しで直した値・式を先に）。式は、直した値で計算し直せる形（同じ行の四則）だけ自分で計算する"""
        k = f"{col_letter(c)}{r}"
        f = writes[k] if k in writes and isinstance(writes[k], str) and writes[k].startswith("=") else None
        if k in writes and f is None:
            return writes[k]
        if f is None:
            f = formula(r, c) or None
            if f and writes and depth == 0 or (f and depth > 0):
                pass
            elif not f:
                e = cell(r, c).get("effectiveValue") or {}
                for kk in ("stringValue", "numberValue", "boolValue"):
                    if kk in e:
                        return e[kk]
                return None
            else:
                e = cell(r, c).get("effectiveValue") or {}
                if "errorValue" in e:
                    return cell(r, c).get("formattedValue")
                for kk in ("stringValue", "numberValue", "boolValue"):
                    if kk in e:
                        return e[kk]
                return None
        # 式を計算し直す（=E10*F10 のような同じシートの四則だけ。ほかの式で直した値に関わる物はエンジンの道へ）
        body = f[1:]
        if not re.fullmatch(r"[A-Z]{1,3}\d+(?:\s*[-+*/]\s*(?:[A-Z]{1,3}\d+|\d+(?:\.\d+)?))*", body.strip()) or depth > 3:
            if not writes:
                e = cell(r, c).get("effectiveValue") or {}
                for kk in ("stringValue", "numberValue", "boolValue"):
                    if kk in e:
                        return e[kk]
                return cell(r, c).get("formattedValue")
            raise Skip("直した値に関わる式を計算し直せない")
        def ref(m):
            rr, cc = int(m.group(2)), col_num(m.group(1))
            v = ev(rr, cc, depth + 1)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise Skip("数でない値の計算")
            return repr(float(v))
        expr = re.sub(r"([A-Z]{1,3})(\d+)", ref, body)
        try:
            val = eval(expr, {"__builtins__": {}}, {})
        except ZeroDivisionError:
            return "#DIV/0!"
        return int(val) if float(val).is_integer() else val

    def src_table(name):
        """元の表: 今のシートか、この呼び出しで作ったシート"""
        if name in (None, "", sheet):
            return {"name": sheet, "hr": hr, "ra": r_a, "rb": r_b, "fc": first_c, "lc": last_c,
                    "names": {c: h for h, c in name2c.items()}, "get": ev,
                    "isdate": lambda r, c: (((cell(r, c).get("effectiveFormat") or {}).get("numberFormat")) or {}).get("type") in ("DATE", "DATE_TIME"),
                    "fmt": lambda c: (((cell(r_a, c).get("userEnteredFormat") or {}).get("numberFormat")) or {})}
        if name in mem:
            return mem[name]
        raise Skip("ほかのシートの表")

    def uniq_id():
        import random
        return random.randint(10 ** 8, 2 ** 31 - 1)

    def tidy_reqs(sid, nrow, ncol, total, num_cols, rows_text):
        bd = {"style": "SOLID", "color": rgb("#9E9E9E")}
        last = nrow
        out = [
            {"updateBorders": {"range": grid(sid, 1, 1, last, ncol), "top": bd, "bottom": bd, "left": bd, "right": bd, "innerHorizontal": bd, "innerVertical": bd}},
            {"repeatCell": {"range": grid(sid, 1, 1, last, ncol), "cell": {"userEnteredFormat": {"verticalAlignment": "MIDDLE"}}, "fields": "userEnteredFormat.verticalAlignment"}},
            {"repeatCell": {"range": grid(sid, 1, 1, 1, ncol), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#1F4E79"), "textFormat": {"bold": True, "foregroundColor": rgb("#FFFFFF")},
                                                                                     "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"}},
                            "fields": "userEnteredFormat(backgroundColor,textFormat(bold,foregroundColor),horizontalAlignment,wrapStrategy)"}},
        ]
        for c in num_cols:
            out.append({"repeatCell": {"range": grid(sid, 2, c, last, c), "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}, "horizontalAlignment": "RIGHT"}},
                                       "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
        if total:
            out.append({"repeatCell": {"range": grid(sid, last, 1, last, ncol), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#F2F2F2"), "textFormat": {"bold": True}}},
                                       "fields": "userEnteredFormat(backgroundColor,textFormat(bold))"}})
            out.append({"updateBorders": {"range": grid(sid, last, 1, last, ncol), "top": {"style": "DOUBLE", "color": rgb("#595959")}}})
        dims = [(0, 1, 28)] + ([(1, last - 1 if total else last, 24)] if last > 1 else []) + ([(last - 1, last, 26)] if total else [])
        for a0, b0, px in dims:
            if b0 > a0:
                out.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": a0, "endIndex": b0}, "properties": {"pixelSize": px}, "fields": "pixelSize"}})
        for c in range(1, ncol + 1):
            mx = max((sum(2 if ord(ch) > 255 else 1 for ch in str(row[c - 1])) for row in rows_text if c - 1 < len(row)), default=0)
            out.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c - 1, "endIndex": c},
                                                      "properties": {"pixelSize": max(50, min(360, mx * 7 + 18))}, "fields": "pixelSize"}})
        out.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}})
        return out

    def numtxt(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"
        return str(v if v is not None else "")

    next_col = last_c + 1
    for op in ops:
        if not isinstance(op, dict) or (op.get("sheet") and op.get("sheet") != sheet and op.get("sheet") not in mem):
            return None
        s = op.get("shelf")
        if s in LOWER_PINS and not lower_pin_ok(s):
            return None      # エンジンの棚が書き換わった＝この写しは古い。エンジンの道で撃つ（ws-check が知らせる）
        try:
            if s == "filter.extract":
                if not lower_pin_ok(s) or not op.get("col"):
                    return None
                tgt_v = op["value"] if op.get("value") is not None else op.get("equals")
                if tgt_v is None and str(op.get("when") or "").lower() not in ("blank", "notblank", "not_blank"):
                    return None
                into = str(op.get("into") or "抽出").strip()
                if not sheet_names:
                    return None
                T = src_table(op.get("sheet"))
                ci = next((c for c, h in T["names"].items() if h == str(op["col"]).strip()), None) or col_of(op["col"])
                if not ci:
                    return None
                when = str(op.get("when") or "eq").lower()
                isd = T.get("isdate") or (lambda r, c: False)
                fy = next((_low_serial_date(T["get"](r, ci)).year for r in range(T["ra"], T["rb"] + 1)
                           if isd(r, ci) and isinstance(T["get"](r, ci), (int, float))), None)
                if fy is None:
                    fy = next((_low_cmp_date(T["get"](r, ci), False, 2000).year for r in range(T["ra"], T["rb"] + 1)
                               if isinstance(T["get"](r, ci), str) and re.match(r"^\s*\d{4}", T["get"](r, ci)) and _low_cmp_date(T["get"](r, ci), False, 2000)), None)
                if fy is None:
                    from datetime import date as _d
                    fy = _d.today().year
                hdr = [T["names"].get(c, "") for c in range(T["fc"], T["lc"] + 1)]
                rows = []
                for r in range(T["ra"], T["rb"] + 1):
                    v = T["get"](r, ci)
                    if when == "eq" and not _low_cmp_date(str(tgt_v), False, fy):
                        cs = "" if v in (None, "") else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                        hit = cs == str(tgt_v)
                    else:
                        hit = _low_match(v, isd(r, ci), when, tgt_v, fy)
                        if hit is None:
                            return None
                    if hit:
                        rows.append([T["get"](r, c) for c in range(T["fc"], T["lc"] + 1)])
                if not rows:
                    return None
                ncol = len(hdr)
                if into in names_now:
                    # 既にあるシート: 値だけ消して書く（書式は残す＝エンジンの clearContents と同じ）。戻しは書く前の値
                    if not light_of:
                        return None
                    L2 = light_of(into)
                    if not L2:
                        return None
                    ent2 = L2["snap"].sheet(into)
                    sid_n = ent2["props"]["sheetId"]
                    used = [k for k, c0 in (ent2.get("cells") or {}).items() if (c0.get("userEnteredValue") or {})]
                    mr = max([k[0] for k in used] + [len(rows) + 1])
                    mc = max([k[1] for k in used] + [ncol])
                    if mr >= 60 or mc >= 26:
                        return None      # 読んだ範囲（A1:Z60）を越えるシートはエンジンの道で
                    old_rows = [{"values": [{"userEnteredValue": ((ent2["cells"].get((r, c)) or {}).get("userEnteredValue"))} if ((ent2["cells"].get((r, c)) or {}).get("userEnteredValue")) else {}
                                            for c in range(1, mc + 1)]} for r in range(1, mr + 1)]
                    news.append({"shelf": "_raw", "requests": [{"updateCells": {"range": grid(sid_n, 1, 1, mr, mc), "fields": "userEnteredValue"}}],
                                 "undo": [{"updateCells": {"start": {"sheetId": sid_n, "rowIndex": 0, "columnIndex": 0}, "rows": old_rows, "fields": "userEnteredValue"}}],
                                 "touch": [(into, 1, 1, mr, mc)]})
                else:
                    sid_n = uniq_id()
                    news.append({"shelf": "sheet.new", "name": into, "sheet_id": sid_n, "index": len(names_now)})
                    names_now.append(into)
                reqs = [{"repeatCell": {"range": grid(sid_n, 1, 1, 1, ncol), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#1F4E79"), "textFormat": {"bold": True, "foregroundColor": rgb("#FFFFFF")}}},
                                        "fields": "userEnteredFormat(backgroundColor,textFormat(bold,foregroundColor))"}}]
                for j, c in enumerate(range(T["fc"], T["lc"] + 1), start=1):   # 日付などの数の形を元の列から
                    nf = T["fmt"](c)
                    if nf.get("pattern"):
                        reqs.append({"repeatCell": {"range": grid(sid_n, 2, j, len(rows) + 1, j), "cell": {"userEnteredFormat": {"numberFormat": nf}}, "fields": "userEnteredFormat.numberFormat"}})
                news.append({"shelf": "_raw", "requests": reqs, "said": f"{into}!A1:{col_letter(ncol)}{len(rows) + 1} {len(rows)} 行を抽出"})
                cells_n = {}
                for j, h in enumerate(hdr, start=1):
                    cells_n[f"{col_letter(j)}1"] = h
                for i, row in enumerate(rows, start=2):
                    for j, v in enumerate(row, start=1):
                        if v not in (None, ""):
                            cells_n[f"{col_letter(j)}{i}"] = v
                new_writes.append({"shelf": "write", "sheet": into, "cells": cells_n, "_new": True})
                mrows = {(i, j): v for i, row in enumerate(rows, start=2) for j, v in enumerate(row, start=1)}
                mem[into] = {"name": into, "hr": 1, "ra": 2, "rb": len(rows) + 1, "fc": 1, "lc": ncol,
                             "names": {j: h for j, h in enumerate(hdr, start=1)}, "get": (lambda mr: (lambda r, c: mr.get((r, c))))(mrows),
                             "fmt": (lambda T0, fc0: (lambda c: T0["fmt"](c + fc0 - 1)))(T, T["fc"])}
                continue
            if s == "summary":
                if not lower_pin_ok(s) or not op.get("by") or not op.get("values"):
                    return None
                func = str(op.get("func") or "sum").lower()
                if func not in ("sum", "count"):
                    return None
                T = src_table(op.get("sheet"))
                nm2 = {h: c for c, h in T["names"].items()}
                by = nm2.get(str(op["by"]).strip()) or col_of(op["by"])
                vals_c = [nm2.get(str(v).strip()) or col_of(v) for v in (op["values"] if isinstance(op["values"], list) else [op["values"]])]
                if not by or not all(vals_c):
                    return None
                by_name = T["names"].get(by, str(op["by"]))
                into = op.get("into")
                if not sheet_names:
                    return None
                if not into:
                    into = "集計"
                    if into in names_now:
                        base = f"集計_{by_name}別"
                        into, k2 = base, 2
                        while into in names_now:
                            into, k2 = f"{base}_{k2}", k2 + 1
                exist = into in names_now
                if exist and not ok:
                    return None      # 作り直しは消す手＝確かめが要る（エンジンの道が聞き返す）
                keys, trim_hit = [], False
                for r in range(T["ra"], T["rb"] + 1):
                    k = T["get"](r, by)
                    if k in (None, ""):
                        continue
                    ks = str(k)
                    if ks != ks.strip():
                        trim_hit = True
                    if ks.strip() not in keys:
                        keys.append(ks.strip())
                def normk(v):
                    return re.sub(r"[\s()（）［］\[\]・,，.、。]", "", re.sub(r"株式会社|有限会社|合同会社|\(株\)|\(有\)|\(同\)|㈱|㈲", "", unicodedata.normalize("NFKC", str(v)))).lower()
                groups, order = {}, []
                for k in keys:
                    n0 = normk(k)
                    if n0 not in groups:
                        groups[n0] = []
                        order.append(n0)
                    groups[n0].append(k)
                merged = []
                if any(len(v) > 1 for v in groups.values()):
                    # 書き方の違いで割れる物は 1 行に。名前はマスタ（同じ見出しの列を持ち、値が重ならないほかのシート）の書き方（エンジンの summary と同じ）
                    master = {}
                    for nm in names_now:
                        if nm in (T["name"], into, "_GASクイックの控え") or nm in mem or not light_of:
                            continue
                        L3 = light_of(nm)
                        if not L3 or not L3.get("table"):
                            continue
                        t3 = L3["table"]
                        c3 = next((col_num(c["col"]) for c in t3.get("columns") or [] if str(c.get("name") or "").strip() == by_name), None)
                        if not c3:
                            continue
                        m3 = re.fullmatch(r"(\d+)-(\d+)", str(t3.get("data") or ""))
                        if not m3:
                            continue
                        cand, dup = {}, False
                        for r in range(int(m3.group(1)), int(m3.group(2)) + 1):
                            v3 = Snapshot.value_text(L3["snap"].sheet(nm)["cells"].get((r, c3))).strip()
                            if not v3:
                                continue
                            if normk(v3) in cand:
                                dup = True
                                break
                            cand[normk(v3)] = v3
                        if dup:
                            continue
                        master = cand
                        break
                    if not light_of:
                        return None
                    names_k = []
                    for n0 in order:
                        vs = groups[n0]
                        nm0 = master.get(n0) or vs[0]
                        if len(vs) > 1:
                            merged.append("・".join(f"「{v}」" for v in vs if v != nm0) + f"を「{nm0}」")
                        names_k.append(nm0)
                else:
                    names_k = list(keys)
                variants = [groups[n0] for n0 in order]
                keys = names_k
                sq = "'" + T["name"].replace("'", "''") + "'"
                rng = lambda c: f"{sq}!${col_letter(c)}${T['ra']}:${col_letter(c)}${T['rb']}"
                hdr_row = [by_name] + [T["names"].get(c, "") + ("(件数)" if func == "count" else "") for c in vals_c]
                grid_rows, preview = [hdr_row], []
                qv = lambda v: '"' + str(v).replace('"', '""') + '"'
                for i, k in enumerate(keys):
                    rr = i + 2
                    row = [k]
                    vs = variants[i]
                    for c in vals_c:
                        if len(vs) > 1:
                            hit = "(" + "+".join(f"(TRIM({rng(by)})={qv(v)})" for v in vs) + ")"
                            row.append(f"=SUMPRODUCT({hit}*1)" if func == "count" else f"=SUMPRODUCT({hit}*({rng(c)}))")
                        elif trim_hit:
                            row.append(f"=SUMPRODUCT((TRIM({rng(by)})=$A{rr})*1)" if func == "count" else f"=SUMPRODUCT((TRIM({rng(by)})=$A{rr})*({rng(c)}))")
                        else:
                            row.append(f"=COUNTIFS({rng(by)},$A{rr})" if func == "count" else f"=SUMIFS({rng(c)},{rng(by)},$A{rr})")
                    grid_rows.append(row)
                    if i < 4:
                        tot_v = 0
                        for r in range(T["ra"], T["rb"] + 1):
                            if str(T["get"](r, by) or "").strip() in variants[i]:
                                v = T["get"](r, vals_c[0])
                                tot_v += 1 if func == "count" else (v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0)
                        preview.append(f"{k}: {int(tot_v) if float(tot_v).is_integer() else tot_v}")
                tot_row = ["合計"] + [f"=SUM({col_letter(j + 2)}2:{col_letter(j + 2)}{len(keys) + 1})" for j in range(len(vals_c))]
                grid_rows.append(tot_row)
                ncol = len(hdr_row)
                nrow = len(grid_rows)
                if exist:
                    # 作り直し（ok あり）: 値と書式を消して書き直す。戻しは書く前の値と書式
                    L2 = light_of(into) if light_of else None
                    if not L2:
                        return None
                    ent2 = L2["snap"].sheet(into)
                    sid_n = ent2["props"]["sheetId"]
                    used = list((ent2.get("cells") or {}).keys())
                    mr, mc = max([k[0] for k in used] + [nrow]), max([k[1] for k in used] + [ncol])
                    if mr >= 60 or mc >= 26:
                        return None
                    cur_g = [[Snapshot.value_text(ent2["cells"].get((r, c))) for c in range(1, ncol + 1)] for r in range(1, nrow + 1)]
                    new_g = [[(str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)) for v in row] for row in grid_rows]
                    if cur_g == new_g and not any((ent2["cells"].get((r, c)) or {}).get("userEnteredValue") for r in range(nrow + 1, mr + 1) for c in range(1, mc + 1)):
                        notes.append(f"集計シート「{into}」は最新です（変更なし）")
                        continue
                    old_rows = [{"values": [{k2: v2 for k2, v2 in (("userEnteredValue", (ent2["cells"].get((r, c)) or {}).get("userEnteredValue")),
                                                                    ("userEnteredFormat", clean_format((ent2["cells"].get((r, c)) or {}).get("userEnteredFormat")))) if v2}
                                            for c in range(1, mc + 1)]} for r in range(1, mr + 1)]
                    news.append({"shelf": "_raw", "requests": [{"updateCells": {"range": grid(sid_n, 1, 1, mr, mc), "fields": "userEnteredValue,userEnteredFormat"}}],
                                 "undo": [{"updateCells": {"start": {"sheetId": sid_n, "rowIndex": 0, "columnIndex": 0}, "rows": old_rows, "fields": "userEnteredValue,userEnteredFormat"}}],
                                 "touch": [(into, 1, 1, mr, mc)]})
                else:
                    sid_n = uniq_id()
                    news.append({"shelf": "sheet.new", "name": into, "sheet_id": sid_n, "index": len(names_now)})
                    names_now.append(into)
                txt = [[str(x) for x in grid_rows[0]]] + [[k] + ["0" * 7] * len(vals_c) for k in keys] + [["合計"] + ["0" * 9] * len(vals_c)]
                news.append({"shelf": "_raw", "requests": tidy_reqs(sid_n, nrow, ncol, True, list(range(2, ncol + 1)), txt),
                             "said": f"{into}!A1:{col_letter(ncol)}{nrow} シート「{into}」へ「{T['name']}」の {by_name} ごとの集計（元の表を直すと追従）"})
                new_writes.append({"shelf": "write", "sheet": into, "_new": True,
                                   "cells": {f"{col_letter(j)}{i}": v for i, row in enumerate(grid_rows, start=1) for j, v in enumerate(row, start=1)}})
                notes.append("集計結果: " + " ／ ".join(preview[:4]) + (f" ほか{len(keys) - 3}件" if len(keys) > 3 else ""))
                if trim_hit:
                    notes.append(f"「{by_name}」列の前後の空白を無視してまとめました")
                for c, h in T["names"].items():
                    if re.search(r"状態|ステータス|状況|備考|メモ", h) and any(re.search(r"キャンセル|取消|無効", str(T["get"](r, c) or "")) for r in range(T["ra"], T["rb"] + 1)):
                        notes.append(f"※「{h}」列にキャンセル等の行を含んでいます")
                        break
                if merged:
                    notes.append("書き方の違いをまとめて数えました: " + "、".join(merged[:3]) + "（元の表は直していません。そろえるなら match.master）")
                notes.append(f'別の棚からこの表を参照するときは range:"{into}"（または "{into}!A1:{col_letter(ncol)}{nrow}"）')
                mem[into] = {"name": into, "hr": 1, "ra": 2, "rb": len(keys) + 1, "fc": 1, "lc": ncol, "names": {j: h for j, h in enumerate(hdr_row, start=1)},
                             "get": (lambda g: (lambda r, c: g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else None))(grid_rows),
                             "fmt": lambda c: {}, "sid": sid_n}
                continue
            if s == "chart.new":
                if not lower_pin_ok(s) or op.get("edit") or op.get("target") or op.get("at") or op.get("transpose"):
                    return None
                typ = str(op.get("type") or "column").lower()
                if typ not in ("column", "bar", "line", "pie", "area"):
                    return None
                host = op.get("sheet") or sheet
                if host != sheet:
                    return None
                rname = str(op.get("range") or "")
                if rname not in mem:
                    return None      # 作ったシートの表をグラフにする形だけ（ほかはエンジンの道）
                M = mem[rname]
                g_sid = M.get("sid")
                if not g_sid:
                    return None
                r1, r2, c1, c2 = M["hr"], M["rb"], M["fc"], M["lc"]
                src = lambda c: {"sourceRange": {"sources": [grid(g_sid, r1, c, r2, c)]}}
                cid = uniq_id()
                right = max([last_c] + [c for (_r, c) in cells.keys()]) if cells else last_c
                anchor = {"anchorCell": {"sheetId": light["snap"].sheet(sheet)["props"]["sheetId"], "rowIndex": hr - 1, "columnIndex": right + 1}, "offsetXPixels": 0, "offsetYPixels": 0}
                if typ == "pie":
                    spec = {"pieChart": {"legendPosition": "RIGHT_LEGEND", "domain": src(c1), "series": src(c1 + 1)}}
                else:
                    spec = {"basicChart": {"chartType": typ.upper(), "legendPosition": "RIGHT_LEGEND", "headerCount": 1,
                                           "domains": [{"domain": src(c1)}], "series": [{"series": src(c), "targetAxis": "LEFT_AXIS"} for c in range(c1 + 1, c2 + 1)]}}
                if op.get("title"):
                    spec["title"] = op["title"]
                news.append({"shelf": "_raw", "requests": [{"addChart": {"chart": {"chartId": cid, "spec": spec, "position": {"overlayPosition": anchor}}}}],
                             "undo": [{"deleteEmbeddedObject": {"objectId": cid}}], "touch": [(sheet, 0, 0, 0, 0)],
                             "said": f"{sheet}!{rname}!A{r1}:{col_letter(c2)}{r2} グラフを作成（{typ}{'・' + op['title'] if op.get('title') else ''}）"})
                continue
            if s == "filter.where":
                sorts.append(dict(op))
                said.append(f"{sheet}!{tb['first_col']}{hr}:{tb['last_col']}{r_b} フィルタを設定")
                continue
            if s == "sort":
                if op.get("where") or op.get("filter"):
                    return None
                sorts.append(dict(op))
                said.append(f"{sheet}!{tb['first_col']}{r_a}:{tb['last_col']}{r_b} {op.get('col') or op.get('cols')} で{'降順' if op.get('desc') else '昇順'}に並べ替え")
                continue
            if s == "cf.add":
                w0 = str(op.get("when") or "").lower()
                v0 = "" if op.get("value") is None else str(op["value"])
                is_n = bool(re.fullmatch(r"-?\d+(?:\.\d+)?", v0.replace(",", "").strip()))
                if w0 == "between" or (not is_n and w0 in ("gt", "ge", "lt", "le", "eq", "ne") and _low_cmp_date(v0.split("..")[0], False, 2000)):
                    # 日付の比べ: エンジンと同じ式（=AND(ISNUMBER(先頭),先頭 比べ DATE(年,月,日))）。年の無い日付は範囲の先頭の列の年
                    r1, c1, r2, c2 = parse_a1(op["range"])
                    fy = next((_low_serial_date(ev(r, c1)).year for r in range(r1, r2 + 1)
                               if isinstance(ev(r, c1), (int, float)) and (((cell(r, c1).get("effectiveFormat") or {}).get("numberFormat")) or {}).get("type") in ("DATE", "DATE_TIME")), None)
                    if fy is None:
                        from datetime import date as _d
                        fy = _d.today().year
                    a1c = f"{col_letter(c1)}{r1}"
                    de = lambda d: f"DATE({d.year},{d.month},{d.day})"
                    if w0 == "between":
                        if ".." not in v0:
                            return None
                        d1, d2 = _low_cmp_date(v0.split("..")[0], False, fy), _low_cmp_date(v0.split("..")[1], False, fy)
                        if not d1 or not d2:
                            return None
                        lo, hi = min(d1, d2), max(d1, d2)
                        fml = f"=AND(ISNUMBER({a1c}),{a1c}>={de(lo)},{a1c}<={de(hi)})"
                    else:
                        d1 = _low_cmp_date(v0, False, fy)
                        fml = f"=AND(ISNUMBER({a1c}),{a1c}{ {'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<=', 'eq': '=', 'ne': '<>'}[w0] }{de(d1)})"
                    op = dict(op, when="formula", value=fml)
                    conv.append(1)
                fmts.append(dict(op))
                said.append(f"{sheet}!{op.get('range')} 条件付き書式を付与（when: {op.get('when')}）")
            elif s == "seiri":
                if not op.get("col") or any(op.get(k) for k in ("blank_rows", "dedupe", "dates", "tidy", "renumber", "trim_inner")):
                    return None
                ci = col_of(op["col"])
                if not ci:
                    return None
                hname = next((h for h, cc in name2c.items() if cc == ci), str(op["col"]))
                keep = bool(_LOW_CODE_HEAD.search(hname)) or any(
                    isinstance(raw(r, ci), str) and re.match(r"^\s*[+-]?[0０][0-9０-９]", raw(r, ci))
                    for r in range(r_a, r_b + 1) if not formula(r, ci))
                got = []
                for r in range(r_a, r_b + 1):
                    v = raw(r, ci)
                    if formula(r, ci) or not isinstance(v, str):
                        continue
                    nv = v
                    if op.get("halfwidth"):
                        nv = _zen2han(nv)
                    if op.get("trim"):
                        nv = re.sub(r"^[\s　]+|[\s　]+$", "", nv)
                    out = nv
                    cpat = (((cell(r, ci).get("userEnteredFormat") or {}).get("numberFormat")) or {}).get("pattern")
                    if op.get("numbers") and not keep and not re.match(r"^[+-]?0\d", nv) and cpat != "@":
                        nc = re.sub(r"[０-９，．－＋]", lambda mm: chr(ord(mm.group(0)) - 0xFEE0), nv)
                        nc = re.sub(r"\s*(?:円|個|件|本|枚|台)$", "", re.sub(r"^[¥￥$]\s*", "", nc)).strip()
                        if _LOW_NUM_RE.fullmatch(nc):
                            num = float(nc.replace(",", ""))
                            out = int(num) if num.is_integer() else num
                    if out == v:
                        continue
                    if isinstance(out, str) and _LOW_AUTO_PARSE.search(out):
                        return None        # 書くと数や日付に化ける文字はエンジンの道で（@ の扱い）
                    put(r, ci, out)
                    got.append(f"{col_letter(ci)}{r}")
                if got:
                    said.append(f"{sheet}!{'・'.join(got[:4])}{(' ほか' + str(len(got) - 4) + ' 件') if len(got) > 4 else ''} {hname}列の汚れを直した")
            elif s == "phone.fix":
                ci = col_of(op.get("col"))
                if not ci or op.get("range"):
                    return None
                got = []
                for r in range(r_a, r_b + 1):
                    if formula(r, ci):
                        continue
                    v = raw(r, ci)
                    f = _low_phone(v)
                    if not f:
                        continue
                    pat = (((cell(r, ci).get("userEnteredFormat") or {}).get("numberFormat")) or {}).get("pattern")
                    if str(v) != f or pat != "@":
                        fmts.append({"shelf": "format", "range": f"{col_letter(ci)}{r}", "number_format": "@"})
                        put(r, ci, f)
                        got.append(f"{col_letter(ci)}{r}")
                if not got:
                    return None    # 変更なしの返事はエンジンの言い方に合わせる
                said.append(f"{sheet}!{'・'.join(got[:4])} 電話番号をハイフン区切りに統一（{len(got)} 件）")
            elif s == "calc.tax":
                if op.get("at"):
                    return None
                ci = col_of(op.get("col"))
                if not ci:
                    return None
                mode = str(op.get("mode") or "in").lower()
                rate = float(op["rate"]) if op.get("rate") not in (None, "") else 10.0
                ratio = rate / 100
                ratio_s = str(int(ratio)) if float(ratio).is_integer() else repr(ratio)
                fn = {"round": "ROUND", "ceil": "ROUNDUP"}.get(str(op.get("round") or "floor").lower(), "ROUNDDOWN")
                at = next_col
                next_col += 1
                name = op.get("name") or {"out": "税抜", "tax": "消費税"}.get(mode, "税込")
                copies.append({"shelf": "fmt.copy", "from": f"{col_letter(first_c)}{hr}", "to": f"{col_letter(at)}{hr}"})
                put(hr, at, name)
                L = col_letter(ci)
                for r in range(r_a, r_b + 1):
                    ref = f"{L}{r}"
                    ex = f"{ref}/(1+{ratio_s})" if mode == "out" else (f"{ref}*{ratio_s}" if mode == "tax" else f"{ref}*(1+{ratio_s})")
                    put(r, at, f'=IF({ref}="","",{fn}({ex},0))')
                fmts.append({"shelf": "format", "range": f"{col_letter(at)}{r_a}:{col_letter(at)}{r_b}", "number_format": _LOW_NUM_FMT})
                said.append(f"{sheet}!{col_letter(at)}列 {name}（税率 {rate:g}%）の列を追加")
            elif s == "calc.col":
                name, expr = str(op.get("name") or "").strip(), str(op.get("expr") or "").strip()
                if not name or not expr:
                    return None
                expr = expr.replace("×", "*").replace("÷", "/").replace("＋", "+")
                expr = re.sub(r"[ー−]", "-", expr)
                hs = sorted([h for h in name2c if h], key=len, reverse=True)
                rest, refs = expr, []
                for h in hs:
                    if h in rest:
                        refs.append(name2c[h])
                        rest = rest.replace(h, " ")
                if not refs or not re.fullmatch(r"[\s\d.+\-*/()]*", rest):
                    return None     # 関数・列記号・文字のある式はエンジンの道で
                for rc in refs:     # 日付・時刻の列を使う式はエンジンの道で
                    hn = next((h for h, c in name2c.items() if c == rc), "")
                    nf = (((cell(r_a, rc).get("effectiveFormat") or {}).get("numberFormat")) or {}).get("type")
                    if nf in ("DATE", "TIME", "DATE_TIME") or re.search(r"日付|日$|時刻|時間|開始|終了|出勤|退勤|納期|期限", hn):
                        return None
                if op.get("at"):
                    if str(op["at"]).strip() != name or name not in name2c:
                        return None   # 差し込みはエンジンの道で
                    at = name2c[name]
                else:
                    at = next_col
                    next_col += 1
                    copies.append({"shelf": "fmt.copy", "from": f"{col_letter(first_c)}{hr}", "to": f"{col_letter(at)}{hr}"})
                    put(hr, at, name)

                def mk(r, expr=expr, hs=hs):
                    f = expr
                    for h in hs:
                        f = f.replace(h, f"{col_letter(name2c[h])}{r}")
                    return "=" + f
                tmpl = max(first_c, at - 1)
                if tmpl != at:
                    copies.append({"shelf": "fmt.copy", "from": f"{col_letter(tmpl)}{r_a}:{col_letter(tmpl)}{r_b}",
                                   "to": f"{col_letter(at)}{r_a}:{col_letter(at)}{r_b}"})
                for r in range(r_a, r_b + 1):
                    put(r, at, mk(r))
                pct = bool(re.search(r"率|割合|％|%", name))
                if pct:
                    fmts.append({"shelf": "format", "range": f"{col_letter(at)}{r_a}:{col_letter(at)}{r_b}", "number_format": "0.0%"})
                if tot:
                    if tmpl != at:
                        copies.append({"shelf": "fmt.copy", "from": f"{col_letter(tmpl)}{tot}", "to": f"{col_letter(at)}{tot}"})
                    rate_e = pct or re.search(r"比|単価|平均", name) or re.search(r"/\s*[A-Z]{1,3}(?![0-9.])", mk(r_a))
                    put(tot, at, mk(tot) if rate_e else f"=SUM({col_letter(at)}{r_a}:{col_letter(at)}{r_b})")
                    if pct:
                        fmts.append({"shelf": "format", "range": f"{col_letter(at)}{tot}", "number_format": "0.0%"})
                said.append(f"{sheet}!{col_letter(at)}列 計算列「{name}」を{'式にそろえた' if op.get('at') else '追加'}")
            elif s == "total":
                if not tot or op.get("label"):
                    return None    # 合計行を新しく作るのはエンジンの道で（書式ごと作る）
                fixed = []
                want = [col_of(c) for c in op["cols"]] if op.get("cols") else None
                for c in range(first_c, last_c + 1):
                    if want is not None and c not in want:
                        continue
                    hn = next((h for h, cc in name2c.items() if cc == c), "")
                    cur = formula(tot, c).strip()
                    f = f"=SUM({col_letter(c)}{r_a}:{col_letter(c)}{r_b})"
                    if want is None:
                        if not cur or not re.fullmatch(r"=SUM\(\s*\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+\s*\)", cur, re.I):
                            continue
                        if _LOW_NO_SUM_HEAD.search(hn):
                            continue
                    if cur != f:
                        put(tot, c, f)
                        fixed.append(col_letter(c))
                if fixed:
                    said.append(f"{sheet}!{col_letter(first_c)}{tot}:{col_letter(last_c)}{tot} 合計行の範囲を直した（{'・'.join(fixed)}列）")
            elif s == "write" and isinstance(op.get("cells"), dict) and op.get("tsv") is None:
                for k, v in op["cells"].items():
                    r1, c1, r2, c2 = parse_a1(k)
                    if (r1, c1) != (r2, c2):
                        return None
                    put(r1, c1, v)
                said.append(f"{sheet}!{'・'.join(list(op['cells'])[:4])} 値・式を書いた")
            else:
                return None
        except Skip:
            return None
    if not writes and not news and not conv:
        return None
    if mem and any(o.get("shelf") == "sort" for o in ops):
        return None
    out_ops = news + copies + fmts + ([{"shelf": "write", "cells": writes}] if writes else []) + new_writes + sorts
    lower_ops.last_notes = notes
    return out_ops, said + [o["said"] for o in news if o.get("said")]
