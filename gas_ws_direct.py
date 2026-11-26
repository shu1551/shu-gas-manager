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

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets/"
TOKEN_LIFE = 45 * 60          # GAS の鍵はおよそ 1 時間。余裕を見て 45 分で取り直す
LEDGER_KEEP = 30
DIRECT_SHELVES = {"format", "bg.clear", "freeze", "unfreeze", "width", "write",
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
            norm = re.sub(r"色$", "", re.sub(r"^薄い", "薄", s))
            hx = COLOR_MAP.get(norm) or COLOR_MAP.get(re.sub(r"^薄い", "薄", s))
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
                  "basicFilter,merges,data(startRow,startColumn,rowData(values(userEnteredFormat,userEnteredValue,note,effectiveValue(errorValue))),"
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
            return (tb["header_row"], col_num(tb["first_col"]), tb["header_row"], col_num(tb["last_col"]))
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
        writes = any(o.get("shelf") == "write" for o in ops)
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
                    "fp": fp, "ranges": ranges, "shape": any(o.get("shelf") in ("write", "sheet.rename") for o in ops)})
        del led[:-LEDGER_KEEP]
        if any(o.get("shelf") in ("write", "sheet.rename") for o in ops):
            st.pop("table_cache", None)      # 値やシート名が変わったので、次の頼みで表の形を見直す
        out_t = {k: tgt[k] for k in ("id", "name", "kind", "url") if tgt.get(k)}
        out_t["sheet"] = next((o.get("to") for o in ops if o.get("shelf") == "sheet.rename" and (o.get("name") or sheet) == sheet), None) or sheet
        return {"ok": True, "target": out_t, "changed": changed, "notes": notes, "remaining": [], "backup": f"D{n}", "direct": True}

    # ------------------------------------------------------------ 裏の指紋
    def _fp_later(self, n, token, sid, ranges, touched):
        fields = ("sheets(properties(sheetId,title,index,hidden,tabColorStyle,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),"
                  "basicFilter,merges,data(startRow,startColumn,rowData(values(userEnteredFormat,userEnteredValue,note,effectiveValue(errorValue))),"
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
