# -*- coding: utf-8 -*-
"""
gas_ws_tables.py - 試験の「表の形」の JSON（ws_trial/tables/*.json）の検査・展開・流し込みの荷物づくり（純 Python・通信なし）

書式は試験設計書 第 5.2 節。ここが受け持つのは
  ・validate_table: 書式の検査（必須の欄・文字に見えて数や日付に化ける値が {"text"} でない・今日で変わる式・表の欄の整合）
  ・expand_sheet: values + repeat + total を、全部の行を並べた表（セルは JSON のまま）にする
  ・seed_payload: 試験用のエンジンの seed に渡す荷物（セルは エンジンの形: 数・文字・{"f"}・{"s"}・{"d"}・null）
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_DIR = HERE / "ws_trial" / "tables"

KINDS = ("base", "dirty", "quirk", "scale")
VOLATILE = re.compile(r"\b(TODAY|NOW|RAND|RANDBETWEEN)\s*\(", re.I)
# 文字に見えて、Sheets に数・日付・時刻として読まれるおそれのある文字（数字・記号だけ）
LOOKS_NUMERIC = re.compile(r"^[\s\d,.\-+/:%¥$０-９－／：，．]+$")
NAME_RE = re.compile(r"^[a-z0-9_]+$")
FORMAT_KEYS = {"range", "bold", "italic", "bg", "color", "size", "number_format", "align", "wrap"}
SHEET_KEYS = {"name", "values", "repeat", "total", "formats", "borders", "merges", "frozen", "hidden", "widths", "validations", "cf", "filter",
              "protect", "tab_color", "hide_sheet", "tables"}


def load_table(name, table_dir=TABLE_DIR):
    return json.loads((Path(table_dir) / f"{name}.json").read_text(encoding="utf-8"))


def table_names(table_dir=TABLE_DIR):
    return sorted(p.stem for p in Path(table_dir).glob("*.json"))


def col_letter(n):
    s = ""
    while n > 0:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


def col_num(s):
    n = 0
    for ch in s.upper():
        n = n * 26 + ord(ch) - 64
    return n


# ------------------------------------------------------------------ 検査
def _cells_of(sheet):
    for r in sheet.get("values", []):
        for c in r:
            yield c
    rep = sheet.get("repeat")
    if rep:
        for c in rep.get("row", []):
            yield c


def validate_table(t):
    """問題の文字列のリスト（空なら通った）"""
    p = []
    name = t.get("name", "?")
    for k in ("name", "business", "kind", "notes", "sheets"):
        if k not in t:
            p.append(f"{name}: 必須の欄「{k}」がありません")
    if p:
        return p
    if not NAME_RE.match(t["name"]):
        p.append(f"{name}: name は ASCII の小文字・数字・_ だけです")
    if t["kind"] not in KINDS:
        p.append(f"{name}: kind は {'・'.join(KINDS)} のどれかです")
    if not str(t["notes"]).strip():
        p.append(f"{name}: notes（汚れ・癖の番地の説明）が空です")
    if t.get("doc") is None and not t["sheets"]:
        p.append(f"{name}: sheets が空です（文書なら doc）")
    if t.get("doc") is not None and t["sheets"]:
        p.append(f"{name}: 文書の表は sheets を空の配列にします")
    for sh in t["sheets"]:
        sn = f"{name}/{sh.get('name', '?')}"
        for k in sh:
            if k not in SHEET_KEYS:
                p.append(f"{sn}: 知らない欄「{k}」")
        if not sh.get("values"):
            p.append(f"{sn}: values が空です")
        if not sh.get("tables"):
            p.append(f"{sn}: tables（見出しの行・列の端・明細・合計行・キー）が必須です。判定はここを正とします")
        for c in _cells_of(sh):
            if isinstance(c, str):
                if c.startswith("="):
                    if VOLATILE.search(c):
                        p.append(f"{sn}: 今日で変わる式は使えません: {c}")
                elif LOOKS_NUMERIC.match(c):
                    p.append(f"{sn}: 数や日付に化けるおそれのある文字は {{\"text\":…}} で書きます: {c!r}")
            elif isinstance(c, dict):
                if set(c) not in ({"text"}, {"date"}):
                    p.append(f"{sn}: セルの書き方が違います: {c}")
                elif "date" in c and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c["date"])):
                    p.append(f"{sn}: 日付は YYYY-MM-DD です: {c}")
            elif c is not None and not isinstance(c, (int, float, bool)):
                p.append(f"{sn}: セルの型が違います: {c!r}")
        for f in sh.get("formats", []):
            bad = set(f) - FORMAT_KEYS
            if bad:
                p.append(f"{sn}: formats の知らない欄 {sorted(bad)}")
        grid = expand_sheet(sh)
        nrows = len(grid)
        for tb in sh.get("tables", []):
            for k in ("header_rows", "first_col", "last_col", "data", "total_row", "key"):
                if k not in tb:
                    p.append(f"{sn}: tables に「{k}」がありません")
            m = re.fullmatch(r"(\d+)-(\d+)", str(tb.get("data", "")))
            if not m:
                p.append(f"{sn}: tables.data は「2-20」の形です")
                continue
            a, b = int(m.group(1)), int(m.group(2))
            hr = tb.get("header_rows") or [0]
            if a != hr[-1] + 1:
                p.append(f"{sn}: 明細の始まり {a} が見出しの最後の行 {hr[-1]} の次ではありません")
            tr = tb.get("total_row")
            if tr is not None and tr != b + 1:
                p.append(f"{sn}: 合計行 {tr} が明細の終わり {b} の次ではありません")
            last = tr if tr is not None else b
            if last != nrows:
                p.append(f"{sn}: 表の最後の行 {last} と、展開した行数 {nrows} が違います")
            if sh.get("total") and tr is None:
                p.append(f"{sn}: total があるのに tables.total_row が null です")
    return p


# ------------------------------------------------------------------ 展開
def _fill(cell, n, r):
    """くり返しの行の 1 セル: {n}・{n:0000}・{r} を置き換える"""
    def sub(s):
        s = re.sub(r"\{n:(0+)\}", lambda m: str(n).zfill(len(m.group(1))), s)
        return s.replace("{n}", str(n)).replace("{r}", str(r))
    if isinstance(cell, str):
        return sub(cell)
    if isinstance(cell, dict):
        return {k: sub(v) if isinstance(v, str) else v for k, v in cell.items()}
    return cell


def expand_sheet(sheet):
    """values + repeat + total を、全部の行を並べた表にする（セルは JSON のまま）"""
    grid = [list(r) for r in sheet["values"]]
    rep = sheet.get("repeat")
    if rep:
        at = rep["at_row"]
        new = []
        for i in range(rep["count"]):
            n = rep.get("start", 1) + i
            r = at + i
            new.append([_fill(c, n, r) for c in rep["row"]])
        grid = grid[:at - 1] + new + grid[at - 1:]
    tot = sheet.get("total")
    if tot:
        tb = (sheet.get("tables") or [{}])[0]
        hr = (tb.get("header_rows") or [1])[-1]
        first = hr + 1
        row_no = len(grid) + 1 if tot["row"] == "last+1" else int(tot["row"])
        width = max(len(r) for r in grid)
        row = [None] * width
        row[col_num(tot["label_col"]) - 1] = tot["label"]
        for c in tot.get("sum_cols", []):
            row[col_num(c) - 1] = f"=SUM({c}{first}:{c}{row_no - 1})"
        if row_no <= len(grid):
            grid[row_no - 1] = row
        else:
            grid.append(row)
    return grid


def encode_cell(c):
    """JSON のセルを、試験用のエンジンの seed の形にする"""
    if isinstance(c, dict):
        if "text" in c:
            return {"s": c["text"]}
        if "date" in c:
            return {"d": c["date"]}
    if isinstance(c, str) and c.startswith("="):
        return {"f": c}
    return c


def seed_payload(t):
    """試験用のエンジンの seed に渡す荷物（id は呼び出し側で足す）"""
    sheets = []
    for sh in t["sheets"]:
        grid = [[encode_cell(c) for c in row] for row in expand_sheet(sh)]
        hid = sh.get("hidden") or {"rows": [], "cols": []}
        sheets.append({"name": sh["name"], "grid": grid, "formats": sh.get("formats", []), "borders": sh.get("borders", []),
                       "merges": sh.get("merges", []), "frozen": sh.get("frozen") or {}, "hidden": hid, "widths": sh.get("widths", {}),
                       "cf": sh.get("cf", []), "validations": sh.get("validations", []), "filter": sh.get("filter"),
                       "tab_color": sh.get("tab_color"), "hide_sheet": bool(sh.get("hide_sheet"))})
    return {"sheets": sheets, "named": t.get("named", [])}


def table_info(t):
    """判定が使う表の範囲: {シート名: [tables…]}"""
    return {sh["name"]: sh.get("tables", []) for sh in t["sheets"]}
