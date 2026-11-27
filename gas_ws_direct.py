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
                  "note.set", "note.clear"}
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
        for attempt in range(2):
            h = {"Authorization": "Bearer " + self._token(st, fresh=attempt > 0)}
            if "json" in kw:
                h["Content-Type"] = "application/json"
            r = sess.request(method, url, headers=h, timeout=30, **kw)
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code == 403 and "SERVICE_DISABLED" in r.text:
                st["direct_off"] = "Sheets API が止められている"
                raise Skip("Sheets API が止められている")
            if r.status_code != 200:
                raise DirectError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        raise DirectError("鍵が通らない")

    def _get(self, st, sid, ranges, extra_fields=""):
        fields = ("sheets(properties(sheetId,title,index,hidden,tabColorStyle,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),"
                  "basicFilter,merges,conditionalFormats,data(startRow,startColumn,rowData(values(userEnteredFormat,userEnteredValue,note,effectiveValue(errorValue))),"
                  "columnMetadata(pixelSize,hiddenByUser),rowMetadata(pixelSize,hiddenByUser)))")
        params = [("ranges", r) for r in ranges] + [("fields", fields)]
        return Snapshot(self._call(st, "GET", SHEETS + sid, params=params))

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
            elif s in ("sheet.rename", "sheet.hide", "sheet.color"):
                if op.get("name"):
                    ranges.add(f"{q(op['name'])}!A1")
            elif s == "sheet.show":
                if op.get("name"):
                    ranges.add(f"{q(op['name'])}!A1")
                else:
                    for n in sheets_known or []:
                        ranges.add(f"{q(n)}!A1")
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

    def _build(self, ops, sheet, tb, snap):
        req, undo, changed, touched = [], [], [], []

        def area(shname, r1, c1, r2, c2):
            touched.append((shname, r1, c1, r2, c2))

        for op in ops:
            s = op["shelf"]
            shn = op.get("sheet") or sheet
            ent = snap.sheet(shn)
            sid = ent["props"]["sheetId"]
            if s in ("format", "bg.clear"):
                pl = self._place(op, tb)
                if pl == "title":
                    (r1, c1, r2, c2), title_band = self._title_place(ent, tb, op)
                else:
                    (r1, c1, r2, c2), title_band = pl, False
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
            return None
        tc = self.mgr._cached_table(st, tgt) or {}
        sheet = tgt.get("sheet") or tc.get("sheet") or ""
        if not sheet:
            return None
        tb = tc.get("table")
        try:
            ranges = self._plan(ops, sheet, tb, tc.get("sheets"))
            before = self._get(st, tgt["id"], ranges)
            if tim:
                tim.lap("直接:読む")
            if tb:      # 覚えている見出しが今の見出しと同じか（違えばエンジンの道でその場の形を見る）
                ent = before.sheet(sheet)
                now = [Snapshot.value_text(ent["cells"].get((tb["header_row"], col_num(c["col"])))) for c in tb.get("columns") or []]
                if now != [str(c.get("name")) for c in tb.get("columns") or []]:
                    return None
            req, undo, changed, touched = self._build(ops, sheet, tb, before)
            vals = [r["_values"] for r in req if "_values" in r]
            req = [r for r in req if "_values" not in r]
            if req:
                self._call(st, "POST", SHEETS + tgt["id"] + ":batchUpdate", json={"requests": req})
            for v in vals:
                for shn, cells in v.items():
                    data = [{"range": f"{q(shn)}!{k}", "values": [[x]]} for k, x in cells.items()]
                    self._call(st, "POST", SHEETS + tgt["id"] + "/values:batchUpdate", json={"valueInputOption": "USER_ENTERED", "data": data})
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
        e0, e1 = self._errors(before, touched), (self._errors(after, touched) if after else {})
        news = [f"{k} {v}" for k, v in e1.items() if k not in e0]
        if news:
            notes.append("新しいエラー: " + "・".join(news[:5]) + (f" ほか {len(news) - 5} 件" if len(news) > 5 else ""))
        led.append({"n": n, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "id": tgt["id"], "name": tgt.get("name", ""),
                    "sheet": sheet, "what": " ／ ".join(changed)[:120], "undo": undo, "touched": touched,
                    "fp": fp, "ranges": ranges, "shape": any(o.get("shelf") in ("write", "clear.values", "sort", "rows.insert", "cols.insert", "sheet.rename") for o in ops)})
        del led[:-LEDGER_KEEP]
        if any(o.get("shelf") in ("write", "clear.values", "sort", "rows.insert", "cols.insert", "sheet.rename") for o in ops):
            st.pop("table_cache", None)      # 値やシート名が変わったので、次の頼みで表の形を見直す
        out_t = {k: tgt[k] for k in ("id", "name", "kind", "url") if tgt.get(k)}
        out_t["sheet"] = next((o.get("to") for o in ops if o.get("shelf") == "sheet.rename" and (o.get("name") or sheet) == sheet), None) or sheet
        return {"ok": True, "target": out_t, "changed": changed, "notes": notes, "remaining": [], "backup": f"D{n}", "direct": True}

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
                "sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)),"
                "basicFilter,bandedRanges(range),protectedRanges(range,warningOnly),"
                "rowGroups,columnGroups,charts(spec(title,basicChart(chartType),pieChart(legendPosition))))"
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
                "data(startRow,startColumn,rowMetadata(hiddenByUser),columnMetadata(hiddenByUser),"
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
        hr = [i for i, m in enumerate(grid_data.get("rowMetadata") or []) if m and m.get("hiddenByUser")]
        hc = [i for i, m in enumerate(grid_data.get("columnMetadata") or []) if m and m.get("hiddenByUser")]
        hp = []
        if hr:
            hp.append("隠した行: " + "、".join(_cap_list(_num_runs(hr), 4)))
        if hc:
            hp.append("隠した列: " + "、".join(_cap_list(_col_runs(hc), 4)))
        if hp:
            lines.append(" ／ ".join(hp))

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

    ch = []
    for c in (sh_meta or {}).get("charts") or []:
        s = c.get("spec") or {}
        ty = (s.get("basicChart") or {}).get("chartType") or ("PIE" if s.get("pieChart") else "")
        ch.append((_CHART_NAMES.get(ty) or ty or "グラフ") + (f"（{s.get('title')}）" if s.get("title") else ""))
    if ch:
        lines.append("グラフ: " + "、".join(_cap_list(ch, 3)))
    return lines


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
