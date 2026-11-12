# -*- coding: utf-8 -*-
"""
gas_ws_judge.py - 試験の判定の部品（純 Python・通信なし）。試験設計書 第 3 章（段 T0 の分）

入るのは、試験用のエンジンの `snap` が返す形の「撮った状態」（Trial.gs の trialSnapSheet_）:
  {"name", "sheets": [{"name","index","rows","cols","frozen":{"rows","cols"},"merges":[…],"hidden_rows":[…],"filtered_rows":[…],
                       "hidden_cols":[…],"cells":{"A1":{"v","t","nf","e":{"bg","fg","b"},"u":{"bg","fg","b"},"bd","f","n"}}}]}
出す物:
  ・promise_fingerprints: 約束の指紋（値・式・素の書式・数の書式・結合・固定・シートの並び。条件付き書式を重ねた後の色は入れない）
  ・compare_golden: 「模範と同じ」（面・比べ方）
  ・check_condition / check_expect: 条件 6 つ（値・式である・並び・見えている書式・見えている行・変わっていない）と どれか
  ・check_rules: いつも掛かる決まり 1・4・5
  ・diff_list: 変わったセルの差分の一覧（模範の検品用）
"""

import hashlib
import json
import re
from collections import Counter

# ------------------------------------------------------------------ 色
_NAMED = {"黄": "黄", "黄色": "黄", "赤": "赤", "赤色": "赤", "青": "青", "青色": "青", "緑": "緑", "緑色": "緑", "橙": "橙", "オレンジ": "橙", "灰": "灰", "灰色": "灰",
          "グレー": "灰", "白": "白", "黒": "黒", "紫": "紫", "桃": "桃", "ピンク": "桃", "茶": "茶"}


def color_family(c):
    """色を名前の仲間に丸める（#RRGGBB でも日本語の名前でもよい）"""
    if c is None:
        return "白"
    if not str(c).startswith("#"):
        return _NAMED.get(str(c), str(c))
    h = str(c).lstrip("#")
    if len(h) != 6:
        return "他"
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 60:
        return "黒"
    if mn > 235:
        return "白"
    if mx - mn < 30:
        return "灰"
    d = mx - mn
    if mx == r:
        hue = (60 * ((g - b) / d)) % 360
    elif mx == g:
        hue = 60 * ((b - r) / d) + 120
    else:
        hue = 60 * ((r - g) / d) + 240
    sat = d / mx
    if hue < 15 or hue >= 345:
        return "桃" if sat < 0.45 and mx > 200 else "赤"
    if hue < 40:
        return "茶" if mx < 170 else "橙"
    if hue < 70:
        return "黄"
    if hue < 165:
        return "緑"
    if hue < 255:
        return "青"
    if hue < 300:
        return "紫"
    return "桃"


# ------------------------------------------------------------------ 状態の読み出し
def sheet_of(snap, name):
    for s in snap["sheets"]:
        if s["name"] == name:
            return s
    return None


def split_a1(a1):
    m = re.fullmatch(r"([A-Z]+)(\d+)", a1)
    return m.group(1), int(m.group(2))


def col_num(s):
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def col_letter(n):
    s = ""
    while n > 0:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


def extent(sheet):
    """値のあるセルの範囲（最後の行・列）"""
    mr = mc = 0
    for a1, c in sheet["cells"].items():
        if c.get("v") not in ("", None):
            col, row = split_a1(a1)
            mr, mc = max(mr, row), max(mc, col_num(col))
    return mr, mc


def rows_of(sheet, visible_only=False):
    """行ごとの表示の文字の並び（1 行目から最後の行まで）"""
    mr, mc = extent(sheet)
    hid = set(sheet.get("hidden_rows", [])) | set(sheet.get("filtered_rows", []))
    out = []
    for r in range(1, mr + 1):
        if visible_only and r in hid:
            continue
        out.append(tuple(sheet["cells"].get(f"{col_letter(c)}{r}", {}).get("v", "") for c in range(1, mc + 1)))
    return out


def cell_v(sheet, a1):
    return sheet["cells"].get(a1, {}).get("v", "")


def cell_num(sheet, a1):
    c = sheet["cells"].get(a1, {})
    if "n" in c:
        return c["n"]
    try:
        return float(str(c.get("v", "")).replace(",", "").replace("¥", ""))
    except ValueError:
        return None


# ------------------------------------------------------------------ 約束の指紋
def _promise_cells(sheet):
    out = {}
    for a1, c in sheet["cells"].items():
        u = c.get("u", {})
        out[a1] = [c.get("v", ""), c.get("f", ""), c.get("nf", ""), u.get("bg"), u.get("fg"), u.get("b"), c.get("bd")]
    return out


def promise_fingerprint(sheet):
    body = {"cells": _promise_cells(sheet), "merges": sorted(sheet.get("merges", [])), "frozen": sheet.get("frozen"), "name": sheet["name"]}
    return hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def promise_fingerprints(snap):
    """{シート名: 指紋} と、シートの並び（名前の順）"""
    order = [s["name"] for s in sorted(snap["sheets"], key=lambda x: x.get("index", 0))]
    return {s["name"]: promise_fingerprint(s) for s in snap["sheets"]}, order


# ------------------------------------------------------------------ 模範と同じ
KIND_FACES = {
    "値を直す・計算": ["値", "式がある所", "行数"],
    "並べる": ["値", "式がある所", "行数"],
    "絞る": ["見えている行", "値", "行数"],
    "見た目": ["見えている書式", "数の書式", "値"],
    "行や列を足す・消す": ["値", "式がある所", "見出し"],
    "構成": ["シートの並び", "固定", "見えている行と列", "値"],
    "仕掛け": ["値"],
}
ROW_SET_FACES = ("値", "見えている行", "見出し")      # 並びを問わない比べ方で、行の集まりとして比べる面


def _norm_rows(rows):
    return Counter(tuple(r) for r in rows)


def _face(sheet, face, tinfo):
    if face == "値":
        return rows_of(sheet)
    if face == "式がある所":
        return sorted(a for a, c in sheet["cells"].items() if c.get("f"))
    if face == "行数":
        return extent(sheet)
    if face == "見えている行":
        return rows_of(sheet, visible_only=True)
    if face == "見えている書式":
        return {a: [color_family(c["e"]["bg"]), color_family(c["e"]["fg"]), bool(c["e"]["b"]), bool(c.get("bd"))]
                for a, c in sheet["cells"].items() if c.get("e") and (color_family(c["e"]["bg"]) != "白" or c["e"]["b"] or c.get("bd") or color_family(c["e"]["fg"]) != "黒")}
    if face == "数の書式":
        return {a: c.get("nf", "") for a, c in sheet["cells"].items() if c.get("nf")}
    if face == "見出し":
        rows = rows_of(sheet)
        hr = ((tinfo or {}).get(sheet["name"]) or [{}])[0].get("header_rows") or [1]
        return [rows[i - 1] for i in hr if i - 1 < len(rows)]
    if face == "固定":
        return sheet.get("frozen")
    if face == "見えている行と列":
        hr = set(sheet.get("hidden_rows", [])) | set(sheet.get("filtered_rows", []))
        return [sorted(hr), sorted(sheet.get("hidden_cols", []))]
    raise ValueError(f"知らない面: {face}")


def compare_golden(before, actual, model, kind, face="既定", mode="そのまま", tinfo=None):
    """模範の ops を撃った後の状態（model）と、答えの ops を撃った後の状態（actual）を比べる。返り値は (合っているか, 違いの文字のリスト)"""
    faces = KIND_FACES.get(kind, ["値", "式がある所", "行数"]) if face == "既定" else (face if isinstance(face, list) else [face])
    diffs = []
    before_names = {s["name"] for s in before["sheets"]}
    if mode == "新しいシートに含む":
        new_model = [s for s in model["sheets"] if s["name"] not in before_names]
        new_actual = [s for s in actual["sheets"] if s["name"] not in before_names]
        have = Counter()
        for s in new_actual:
            have.update(tuple(sorted(str(x) for x in r if x != "")) for r in rows_of(s))
        for s in new_model:
            need = Counter(tuple(sorted(str(x) for x in r if x != "")) for r in rows_of(s))
            lack = need - have
            if lack:
                diffs.append(f"新しいシートに、模範の行 {sum(lack.values())} 件が見つかりません（例: {list(lack)[0]}）")
        if not new_model:
            diffs.append("模範に新しいシートがありません")
        return (not diffs), diffs
    if "シートの並び" in faces:
        oa = [s["name"] for s in sorted(actual["sheets"], key=lambda x: x.get("index", 0))]
        om = [s["name"] for s in sorted(model["sheets"], key=lambda x: x.get("index", 0))]
        if oa != om:
            diffs.append(f"シートの並びが違います（{oa} と {om}）")
        faces = [f for f in faces if f != "シートの並び"]
    for ms in model["sheets"]:
        a = sheet_of(actual, ms["name"])
        if a is None:
            diffs.append(f"シート「{ms['name']}」がありません")
            continue
        for f in faces:
            fa, fm = _face(a, f, tinfo), _face(ms, f, tinfo)
            if mode == "並びを問わない" and f in ROW_SET_FACES:
                if _norm_rows(fa) != _norm_rows(fm):
                    diffs.append(f"{ms['name']}: {f} が違います（行の集まりとして）")
            elif fa != fm:
                diffs.append(f"{ms['name']}: {f} が違います" + _short(fa, fm))
    if kind != "行や列を足す・消す":
        for ms in model["sheets"]:
            a = sheet_of(actual, ms["name"])
            if a is not None and extent(a) != extent(ms):
                diffs.append(f"{ms['name']}: 行・列の数が違います（{extent(a)} と {extent(ms)}）")
    return (not diffs), diffs


def _short(a, b):
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return f"（{i + 1} 番目: {x} と {y}）"
        return f"（長さ {len(a)} と {len(b)}）"
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return f"（{k}: {a.get(k)} と {b.get(k)}）"
    return ""


# ------------------------------------------------------------------ 条件
def _main_table(sheet, tinfo):
    return ((tinfo or {}).get(sheet["name"]) or [{}])[0]


def _columns(sheet, tinfo):
    """見出しの名前 → 列番号（最後の見出しの行）"""
    tb = _main_table(sheet, tinfo)
    hr = (tb.get("header_rows") or [1])[-1]
    mr, mc = extent(sheet)
    return {sheet["cells"].get(f"{col_letter(c)}{hr}", {}).get("v", ""): c for c in range(1, mc + 1)}


def _data_rows(sheet, tinfo, total_label=None):
    tb = _main_table(sheet, tinfo)
    hr = (tb.get("header_rows") or [1])[-1]
    mr, mc = extent(sheet)
    rows = list(range(hr + 1, mr + 1))
    if tb.get("total_row"):
        rows = [r for r in rows if sheet["cells"].get(f"A{r}", {}).get("v") != "合計"]
    return rows


def _first_sheet(snap, cond):
    name = cond.get("シート") if isinstance(cond, dict) else None
    return sheet_of(snap, name) if name else snap["sheets"][0]


def check_condition(cond, before, after, tinfo=None):
    """条件 1 つ。返り値は (通った, 理由)"""
    if "どれか" in cond:
        reasons = []
        for c in cond["どれか"]:
            ok, why = check_condition(c, before, after, tinfo)
            if ok:
                return True, ""
            reasons.append(why)
        return False, "どれも通りません: " + " ／ ".join(reasons)
    sh = _first_sheet(after, cond)
    if "値" in cond:
        for a1, want in cond["値"].items():
            got = cell_v(sh, a1)
            if isinstance(want, (int, float)):
                n = cell_num(sh, a1)
                if n is None or abs(n - want) > 1e-9:
                    return False, f"{a1} が {want} のはずが {got!r}"
            elif str(got) != str(want):
                return False, f"{a1} が {want!r} のはずが {got!r}"
        return True, ""
    if "式である" in cond:
        for a1 in cond["式である"]:
            if not sh["cells"].get(a1, {}).get("f"):
                return False, f"{a1} が式になっていません"
        return True, ""
    if "並び" in cond:
        spec = cond["並び"]
        col = _columns(sh, tinfo).get(spec["列"])
        if not col:
            return False, f"列「{spec['列']}」がありません"
        vals = [cell_num(sh, f"{col_letter(col)}{r}") for r in _data_rows(sh, tinfo)]
        vals = [v for v in vals if v is not None]
        ok = vals == sorted(vals, reverse=(spec.get("向き") == "降順"))
        return ok, "" if ok else f"列「{spec['列']}」が{spec.get('向き', '昇順')}に並んでいません"
    if "見えている書式" in cond:
        spec = cond["見えている書式"]
        m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", spec["範囲"])
        c1, r1, c2, r2 = col_num(m.group(1)), int(m.group(2)), col_num(m.group(3)), int(m.group(4))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = sh["cells"].get(f"{col_letter(c)}{r}", {})
                e = cell.get("e") or {"bg": "#ffffff", "fg": "#000000", "b": False}
                if "背景" in spec and color_family(e["bg"]) != color_family(spec["背景"]):
                    return False, f"{col_letter(c)}{r} の背景が {color_family(e['bg'])}（{spec['背景']} のはず）"
                if "文字色" in spec and color_family(e["fg"]) != color_family(spec["文字色"]):
                    return False, f"{col_letter(c)}{r} の文字色が {color_family(e['fg'])}（{spec['文字色']} のはず）"
                if "太字" in spec and bool(e["b"]) != bool(spec["太字"]):
                    return False, f"{col_letter(c)}{r} の太字が違います"
        return True, ""
    if "見えている行" in cond:
        spec = cond["見えている行"]
        col = _columns(sh, tinfo).get(spec["列"])
        if not col:
            return False, f"列「{spec['列']}」がありません"
        hid = set(sh.get("hidden_rows", [])) | set(sh.get("filtered_rows", []))
        rows = _data_rows(sh, tinfo)
        vis = [r for r in rows if r not in hid]
        want = [r for r in rows if cell_v(sh, f"{col_letter(col)}{r}") == str(spec["だけ"])]
        if not vis:
            return False, "見えている行がありません"
        if vis != want:
            return False, f"見えている行 {vis} が、「{spec['だけ']}」の行 {want} と違います"
        return True, ""
    if "変わっていない" in cond:
        fb, ob = promise_fingerprints(before)
        fa, oa = promise_fingerprints(after)
        if fb != fa or ob != oa:
            return False, "約束の指紋が変わっています: " + "、".join(sorted(k for k in set(fb) | set(fa) if fb.get(k) != fa.get(k)))
        return True, ""
    if "末尾が式" in cond:
        spec = cond["末尾が式"]
        cols_spec = spec["列"] if isinstance(spec, dict) else spec
        if isinstance(cols_spec, str):
            cols_spec = [cols_spec]
        col_map = _columns(sh, tinfo)
        mr, _ = extent(sh)
        if mr == 0:
            return False, "表にデータがありません"
        for cname in cols_spec:
            c = col_map.get(cname)
            if not c:
                return False, f"列「{cname}」がありません"
            a1 = f"{col_letter(c)}{mr}"
            if not sh["cells"].get(a1, {}).get("f"):
                return False, f"最終行 {a1} に式がありません"
        return True, ""
    if "空白行なし" in cond:
        mr, mc = extent(sh)
        if mr == 0:
            return True, ""
        drows = _data_rows(sh, tinfo)
        start_r = min(drows) if drows else 1
        for r in range(start_r, mr + 1):
            if all(cell_v(sh, f"{col_letter(c)}{r}") == "" for c in range(1, mc + 1)):
                return False, f"{r} 行目が空白行です"
        return True, ""
    if "重複なし" in cond:
        spec = cond["重複なし"]
        col_map = _columns(sh, tinfo)
        _, mc = extent(sh)
        if isinstance(spec, dict) and "列" in spec:
            cnames = [spec["列"]] if isinstance(spec["列"], str) else spec["列"]
            cols = [col_map[n] for n in cnames if n in col_map]
        else:
            cols = list(range(1, mc + 1))
        seen = set()
        for r in _data_rows(sh, tinfo):
            row_vals = tuple(cell_v(sh, f"{col_letter(c)}{r}") for c in cols)
            if all(v == "" for v in row_vals):
                continue
            if row_vals in seen:
                return False, f"{r} 行目が重複しています: {row_vals}"
            seen.add(row_vals)
        return True, ""
    if "連番" in cond:
        spec = cond["連番"]
        cname = spec["列"] if isinstance(spec, dict) else spec
        start = spec.get("開始", 1) if isinstance(spec, dict) else 1
        c = _columns(sh, tinfo).get(cname)
        if not c:
            return False, f"列「{cname}」がありません"
        for idx, r in enumerate(_data_rows(sh, tinfo)):
            n = cell_num(sh, f"{col_letter(c)}{r}")
            want = start + idx
            if n is None or abs(n - want) > 1e-9:
                return False, f"{col_letter(c)}{r} が {want} のはずが {cell_v(sh, f'{col_letter(c)}{r}')!r}"
        return True, ""
    if "行数" in cond:
        spec = cond["行数"]
        sh_b = _first_sheet(before, cond) if before else None
        mr_b = extent(sh_b)[0] if sh_b else 0
        mr_a = extent(sh)[0]
        if isinstance(spec, int):
            return (mr_a == spec), "" if mr_a == spec else f"行数が {spec} のはずが {mr_a}"
        if "減った" in spec:
            diff = mr_b - mr_a
            want = spec["減った"]
            ok = (diff == want) if isinstance(want, int) else (diff > 0)
            return ok, "" if ok else f"行数が {want} 減るはずが {mr_b} -> {mr_a}"
        if "増えた" in spec:
            diff = mr_a - mr_b
            want = spec["増えた"]
            ok = (diff == want) if isinstance(want, int) else (diff > 0)
            return ok, "" if ok else f"行数が {want} 増えるはずが {mr_b} -> {mr_a}"
        return False, "行数の条件が不正です"
    if "列数" in cond:
        spec = cond["列数"]
        sh_b = _first_sheet(before, cond) if before else None
        mc_b = extent(sh_b)[1] if sh_b else 0
        mc_a = extent(sh)[1]
        if isinstance(spec, int):
            return (mc_a == spec), "" if mc_a == spec else f"列数が {spec} のはずが {mc_a}"
        if "増えた" in spec:
            diff = mc_a - mc_b
            want = spec["増えた"]
            ok = (diff == want) if isinstance(want, int) else (diff > 0)
            return ok, "" if ok else f"列数が {want} 増えるはずが {mc_b} -> {mc_a}"
        if "減った" in spec:
            diff = mc_b - mc_a
            want = spec["減った"]
            ok = (diff == want) if isinstance(want, int) else (diff > 0)
            return ok, "" if ok else f"列数が {want} 減るはずが {mc_b} -> {mc_a}"
        return False, "列数の条件が不正です"
    if "空範囲" in cond:
        m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", cond["空範囲"])
        if not m:
            return False, f"範囲指定が不正です: {cond['空範囲']}"
        c1, r1, c2, r2 = col_num(m.group(1)), int(m.group(2)), col_num(m.group(3)), int(m.group(4))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if cell_v(sh, f"{col_letter(c)}{r}") != "":
                    return False, f"{col_letter(c)}{r} が空ではありません"
        return True, ""
    if "整え済み" in cond:
        mr, mc = extent(sh)
        if mr == 0:
            return True, ""
        drows = _data_rows(sh, tinfo)
        start_r = min(drows) if drows else 1
        for r in range(start_r, mr + 1):
            if all(cell_v(sh, f"{col_letter(c)}{r}") == "" for c in range(1, mc + 1)):
                return False, f"{r} 行目が空白行です"
        for a1, cell in sh["cells"].items():
            v = str(cell.get("v", ""))
            if v != v.strip(" \t\u3000"):
                return False, f"{a1} に前後の空白があります"
            if re.search(r"[０-９]", v):
                return False, f"{a1} に全角数字があります"
        return True, ""
    if "シートあり" in cond:
        name = cond["シートあり"]
        return (sheet_of(after, name) is not None), "" if sheet_of(after, name) is not None else f"シート「{name}」がありません"
    if "シートの並び" in cond:
        want = cond["シートの並び"]
        got = [s["name"] for s in after["sheets"]]
        return (got == want), "" if got == want else f"シートの並びが {want} のはずが {got}"
    if "固定" in cond:
        spec = cond["固定"]
        fr = sh.get("frozen", {})
        if "行" in spec and fr.get("rows", 0) != spec["行"]:
            return False, f"固定行が {spec['行']} のはずが {fr.get('rows', 0)}"
        if "列" in spec and fr.get("cols", 0) != spec["列"]:
            return False, f"固定列が {spec['列']} のはずが {fr.get('cols', 0)}"
        return True, ""
    if "入力規則あり" in cond:
        vals = sh.get("side", {}).get("validations", {})
        spec = cond["入力規則あり"]
        if spec is True:
            return (len(vals) > 0), "" if vals else "入力規則がありません"
        return (str(spec) in vals), "" if str(spec) in vals else f"{spec} に入力規則がありません"
    if "条件付き書式あり" in cond:
        n = sh.get("cf", 0) or len(sh.get("side", {}).get("cf_rules", []))
        return (n > 0), "" if n > 0 else "条件付き書式がありません"
    if "交互の色あり" in cond:
        b = sh.get("side", {}).get("banded", [])
        return (len(b) > 0), "" if b else "交互の色がありません"
    if "フィルタあり" in cond:
        f = sh.get("side", {}).get("filter")
        return (f is not None), "" if f is not None else "フィルタがありません"
    if "保護あり" in cond:
        p = sh.get("side", {}).get("protected", [])
        return (len(p) > 0), "" if p else "保護がありません"
    if "名前付き範囲あり" in cond:
        spec = cond["名前付き範囲あり"]
        named = after.get("named", [])
        if spec is True:
            return (len(named) > 0), "" if named else "名前付き範囲がありません"
        ok = any(n.get("name") == spec for n in named)
        return ok, "" if ok else f"名前付き範囲「{spec}」がありません"
    if "隠し行" in cond:
        spec = cond["隠し行"]
        hr = sh.get("hidden_rows", [])
        if spec is True:
            return (len(hr) > 0), "" if hr else "隠し行がありません"
        ok = all(r in hr for r in spec)
        return ok, "" if ok else f"隠し行 {spec} が設定されていません（実際: {hr}）"
    if "隠し列" in cond:
        spec = cond["隠し列"]
        hc = [col_letter(c) for c in sh.get("hidden_cols", [])]
        if spec is True:
            return (len(hc) > 0), "" if hc else "隠し列がありません"
        ok = all(c in hc for c in spec)
        return ok, "" if ok else f"隠し列 {spec} が設定されていません（実際: {hc}）"
    if "グラフあり" in cond:
        spec = cond["グラフあり"]
        charts = sh.get("side", {}).get("charts", [])
        if not charts:
            return False, "グラフがありません"
        if spec is True:
            return True, ""
        cmap = {"縦棒": "COLUMN", "横棒": "BAR", "折れ線": "LINE", "円": "PIE", "面": "AREA", "散布図": "SCATTER"}
        want_type = cmap.get(spec, spec) if isinstance(spec, str) else cmap.get(spec.get("種類", ""), spec.get("種類", ""))
        want_title = spec.get("題", "") if isinstance(spec, dict) else ""
        for ch in charts:
            if want_type and ch.get("type") != want_type:
                continue
            if want_title and ch.get("title") != want_title:
                continue
            return True, ""
        return False, f"条件に合うグラフがありません（実際: {charts}）"
    if "聞き返した" in cond or "断った" in cond:
        if tinfo and isinstance(tinfo, dict):
            if tinfo.get("ops"):
                return False, "ops が空であるべきですが実行されました"
        fb, ob = promise_fingerprints(before)
        fa, oa = promise_fingerprints(after)
        if fb != fa or ob != oa:
            return False, "状態が変わってしまっています"
        return True, ""
    raise ValueError(f"知らない条件: {list(cond)}")


def check_expect(expect, before, actual, model=None, kind="値を直す・計算", tinfo=None):
    """台詞の期待（{"模範と同じ": {…}} か {"条件": [条件, …]}）を見る。返り値は (通った, 理由のリスト)"""
    if "模範と同じ" in expect:
        spec = expect["模範と同じ"]
        ok, diffs = compare_golden(before, actual, model, kind, spec.get("面", "既定"), spec.get("比べ方", "そのまま"), tinfo)
        return ok, diffs
    reasons = []
    for c in expect.get("条件", []):
        ok, why = check_condition(c, before, actual, tinfo)
        if not ok:
            reasons.append(why)
    return (not reasons), reasons


# ------------------------------------------------------------------ いつも掛かる決まり 1・4・5
def _errors(sheet):
    return sum(1 for c in sheet["cells"].values() if c.get("t") == "e" or str(c.get("v", "")).startswith("#"))


def check_rules(before, after, touched=None, may_change=(), tinfo=None):
    """壊していないか。違反の文字のリストを返す（空なら大丈夫）。touched＝頼みが触ってよいシート名（既定: 先頭のシートだけ）"""
    v = []
    touched = set(touched) if touched is not None else {before["sheets"][0]["name"]}
    fb, ob = promise_fingerprints(before)
    fa, oa = promise_fingerprints(after)
    if "シート構成" not in may_change:
        for name in fb:
            if name not in touched and fb[name] != fa.get(name):
                v.append(f"1: 頼みと関係ないシート「{name}」の約束の指紋が変わりました")
        if ob != oa and "シートの並び" not in may_change:
            v.append("1: シートの並びが変わりました")
    for sb in before["sheets"]:
        sa = sheet_of(after, sb["name"])
        if sa is None:
            continue
        if "式" not in may_change:
            # 式だった列の式の数が減っていないか（行が消えた分は許す）。式だったセルが値に化けると減る
            lost = max(0, extent(sb)[0] - extent(sa)[0])
            fb_by_col, fa_by_col = Counter(), Counter()
            for a1, c in sb["cells"].items():
                if c.get("f"):
                    fb_by_col[split_a1(a1)[0]] += 1
            for a1, c in sa["cells"].items():
                if c.get("f"):
                    fa_by_col[split_a1(a1)[0]] += 1
            for col, n in fb_by_col.items():
                if fa_by_col[col] < n - lost:
                    v.append(f"4: 式だった列 {col} の式が {n} 個から {fa_by_col[col]} 個に減りました（値に化けた）")
                    break
        if "エラー" not in may_change and _errors(sa) > _errors(sb):
            v.append(f"5: シート「{sb['name']}」のエラーの値が増えました（{_errors(sb)} → {_errors(sa)}）")
    return v


# ------------------------------------------------------------------ 差分の一覧（模範の検品用）
def diff_list(before, after):
    """変わったセルの番地・前 → 後（値・式・書式）と、変わった面。画像でなく文字で読む"""
    out = []
    for sa in after["sheets"]:
        sb = sheet_of(before, sa["name"])
        if sb is None:
            out.append(f"{sa['name']}: 新しいシート")
            continue
        for a1 in sorted(set(sa["cells"]) | set(sb["cells"]), key=lambda x: (split_a1(x)[1], col_num(split_a1(x)[0]))):
            x, y = sb["cells"].get(a1, {}), sa["cells"].get(a1, {})
            if x.get("v", "") != y.get("v", ""):
                out.append(f"{sa['name']}!{a1} {x.get('v', '')!r} → {y.get('v', '')!r}")
            elif x.get("f", "") != y.get("f", ""):
                out.append(f"{sa['name']}!{a1} 式 {x.get('f', '')!r} → {y.get('f', '')!r}")
            elif (x.get("u"), x.get("nf"), x.get("bd")) != (y.get("u"), y.get("nf"), y.get("bd")):
                out.append(f"{sa['name']}!{a1} 書式が変わった")
        for k in ("frozen", "merges"):
            if sb.get(k) != sa.get(k):
                out.append(f"{sa['name']}: {k} {sb.get(k)} → {sa.get(k)}")
    for sb in before["sheets"]:
        if sheet_of(after, sb["name"]) is None:
            out.append(f"{sb['name']}: シートが消えた")
    return out
