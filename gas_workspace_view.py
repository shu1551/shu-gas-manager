# -*- coding: utf-8 -*-
"""
gas_workspace_view.py - Workspace マネージャーの「目」

エンジンの render（見た目を一括で読むだけ・書かない）が返した材料を、手元で HTML に描き直し、
Playwright（headless Chromium）で PNG に撮る。ブラウザのログインも Drive の許可も要らない。
写らないもの：グラフ・画像・図形・入力規則のプルダウン（材料に無い）。
"""

import html
import re
import threading
from datetime import datetime
from pathlib import Path

FONT = "Arial, 'Noto Sans JP', 'Yu Gothic UI', 'Meiryo', sans-serif"
GRID = "#e2e3e3"
_NUM = re.compile(r"^[\s¥$€£-]*[-+(]?[\d,]+(\.\d+)?\)?\s*(%|円)?$")


def _col_letter(n):
    s = ""
    while n > 0:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def _css_color(c):
    """GAS の asHexString は '#AARRGGBB'（例 '#ff000000'＝不透明の黒）で返すことがある。CSS の 8 桁は RRGGBBAA なので直す。"""
    c = str(c or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{8}", c):
        return "#" + c[3:]
    return c


def _border_css(code):
    return {"S": "1px solid #000", "T": "2px solid #000", "D": "3px double #000"}.get(code, "")


def html_sheet(res):
    vals = res.get("values") or [[]]
    nr, nc = len(vals), max((len(r) for r in vals), default=0)
    r0, c0 = res.get("row0", 1), res.get("col0", 1)
    widths = res.get("widths") or [100] * nc
    heights = res.get("heights") or [21] * nr
    g = lambda key, i, j, d="": ((res.get(key) or [])[i][j] if i < len(res.get(key) or []) and j < len((res.get(key) or [])[i]) else d)

    covered, span = set(), {}
    for m in res.get("merges") or []:
        span[(m["r"], m["c"])] = (m["nr"], m["nc"])
        for i in range(m["r"], m["r"] + m["nr"]):
            for j in range(m["c"], m["c"] + m["nc"]):
                if (i, j) != (m["r"], m["c"]):
                    covered.add((i, j))

    frozen = res.get("frozen") or 0
    out = [f"<table style='border-collapse:collapse;table-layout:fixed;font-family:{FONT};font-size:10pt'>",
           "<colgroup><col style='width:46px'>" + "".join(f"<col style='width:{w}px'>" for w in widths[:nc]) + "</colgroup>",
           "<tr style='height:22px'><th style='background:#f8f9fa;border:1px solid #c0c0c0'></th>" +
           "".join(f"<th style='background:#f8f9fa;border:1px solid #c0c0c0;color:#555;font-weight:normal'>{_col_letter(c0 + j)}</th>" for j in range(nc)) + "</tr>"]
    for i in range(nr):
        rn = r0 + i
        line = f"border-bottom:2px solid #9aa0a6;" if frozen and rn == frozen else ""
        out.append(f"<tr style='height:{heights[i] if i < len(heights) else 21}px'>"
                   f"<th style='background:#f8f9fa;border:1px solid #c0c0c0;color:#555;font-weight:normal;{line}'>{rn}</th>")
        for j in range(nc):
            if (i, j) in covered:
                continue
            v = g("values", i, j)
            bg = _css_color(g("ebg", i, j) or g("bg", i, j)) or "#ffffff"
            st = [f"background:{bg}", "padding:2px 3px", "overflow:hidden", "white-space:nowrap", "vertical-align:bottom"]
            col = _css_color(g("color", i, j))
            if col and col.lower() != "#000000":
                st.append(f"color:{col}")
            if g("bold", i, j) == "bold":
                st.append("font-weight:bold")
            if g("italic", i, j) == "italic":
                st.append("font-style:italic")
            sz = g("size", i, j)
            if sz and sz != 10:
                st.append(f"font-size:{sz}pt")
            al = str(g("align", i, j) or "general").lower()
            if al.startswith("general"):
                al = "right" if (v and _NUM.match(str(v))) else "left"
            st.append("text-align:" + ("center" if "center" in al else "right" if "right" in al else "left"))
            bd = g("borders", i, j)
            if bd:
                t, r, b, l = (bd.split("|") + ["", "", "", ""])[:4]
                for side, code in (("top", t), ("right", r), ("bottom", b), ("left", l)):
                    st.append(f"border-{side}:{_border_css(code) or '1px solid ' + GRID}")
            else:
                st.append(f"border:1px solid {GRID}")
            if frozen and rn == frozen:
                st.append("border-bottom:2px solid #9aa0a6")
            attrs = ""
            if (i, j) in span:
                rs, cs = span[(i, j)]
                attrs = (f" rowspan='{rs}'" if rs > 1 else "") + (f" colspan='{cs}'" if cs > 1 else "")
            out.append(f"<td{attrs} style='{';'.join(st)}'>{_esc(v)}</td>")
        out.append("</tr>")
    out.append("</table>")
    t = res.get("target") or {}
    cap = f"{t.get('name', '')} › {t.get('sheet', '')} › {res.get('range', '')}" + ("（大きいので途中まで）" if res.get("cut") else "")
    note = res.get("borders_note")
    width = 46 + sum(widths[:nc]) + 40
    return _page(cap, "".join(out), note), width


def _runs(runs):
    out = []
    for r in runs or []:
        s = _esc(r.get("t", "")).replace("\n", "<br>")
        if r.get("b"):
            s = f"<b>{s}</b>"
        if r.get("i"):
            s = f"<i>{s}</i>"
        c = _css_color(r.get("c"))
        if c and c.lower() not in ("#000000", ""):
            s = f"<span style='color:{c}'>{s}</span>"
        out.append(s)
    return "".join(out) or "&nbsp;"


DOC_SIZE = {"title": 26, "subtitle": 15, "h1": 20, "h2": 16, "h3": 14, "h4": 12, "h5": 11, "h6": 11, "p": 11}


def html_doc(res):
    out, counters = [], {}
    for blk in res.get("blocks") or []:
        k = blk.get("k")
        if k != "li":
            counters = {}
        al = blk.get("align") or ""
        ta = "center" if "center" in al else "right" if "right" in al else "justify" if "justify" in al else "left"
        if k in DOC_SIZE:
            tag = k if k.startswith("h") else "div"
            weight = "normal" if k in ("p", "subtitle") else "bold" if k != "title" else "normal"
            color = "#666" if k == "subtitle" else "#000"
            mt = 0 if k == "p" else 14
            out.append(f"<{tag} style='font-size:{DOC_SIZE[k]}pt;font-weight:{weight};color:{color};margin:{mt}px 0 6px;text-align:{ta}'>{_runs(blk.get('runs'))}</{tag}>")
        elif k == "li":
            lv = blk.get("level", 0)
            for deeper in [x for x in counters if x > lv]:
                counters.pop(deeper)
            counters[lv] = counters.get(lv, 0) + 1
            mark = f"{counters[lv]}." if blk.get("ordered") else ("•" if lv % 2 == 0 else "◦")
            out.append(f"<div style='font-size:11pt;margin:2px 0 2px {36 + lv * 36}px;text-indent:-22px'>"
                       f"<span style='display:inline-block;width:22px;text-indent:0'>{mark}</span>{_runs(blk.get('runs'))}</div>")
        elif k == "table":
            rows = blk.get("rows") or []
            t = ["<table style='border-collapse:collapse;margin:8px 0;font-size:11pt'>"]
            for row in rows:
                t.append("<tr>" + "".join(
                    f"<td style='border:1px solid #000;padding:4px 8px;background:{_css_color(c.get('bg')) or '#fff'};{'font-weight:bold' if c.get('b') else ''}'>{_esc(c.get('t', ''))}</td>"
                    for c in row) + "</tr>")
            t.append("</table>")
            out.append("".join(t))
        elif k == "hr":
            out.append("<hr>")
    t = res.get("target") or {}
    cap = f"{t.get('name', '')}（文書）" + (f"（{res.get('total')} 段落のうち先頭だけ）" if res.get("cut") else "")
    body = f"<div style='width:624px;padding:48px 72px;background:#fff;box-shadow:0 1px 3px #999;font-family:{FONT};line-height:1.45'>{''.join(out)}</div>"
    return _page(cap, body, None, bg="#f1f3f4"), 816 + 60


def _page(caption, inner, note, bg="#ffffff"):
    n = f"<div style='color:#a50e0e;font-size:9pt;margin-top:6px'>{_esc(note)}</div>" if note else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'></head>"
            f"<body style='margin:0;padding:16px;background:{bg};font-family:{FONT}'>"
            f"<div style='font-size:9pt;color:#5f6368;margin-bottom:8px'>{_esc(caption)}</div>{inner}{n}</body></html>")


def shoot(page_html, out_path, width):
    """HTML を PNG に撮る。MCP の非同期ループの中でも動くよう、別スレッドで Playwright を回す。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    box = {}

    def work():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                br = p.chromium.launch(headless=True)
                try:
                    pg = br.new_page(viewport={"width": int(min(max(width, 480), 2000)), "height": 400})
                    pg.set_content(page_html, wait_until="load")
                    pg.screenshot(path=str(out_path), full_page=True)
                finally:
                    br.close()
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(60)
    if th.is_alive():
        raise RuntimeError("画像を撮るのが 60 秒で終わりませんでした")
    if "err" in box:
        msg = str(box["err"])
        if "No module named 'playwright'" in msg or "Executable doesn't exist" in msg:
            raise RuntimeError("画像を撮るには Playwright が要ります（py -m pip install playwright → py -m playwright install chromium）")
        raise RuntimeError(f"画像を撮れませんでした: {msg[:200]}")
    return out_path


def render_to_png(res, out_dir):
    page_html, width = html_doc(res) if res.get("kind") == "doc" else html_sheet(res)
    name = "ws_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png"
    return shoot(page_html, Path(out_dir) / name, width)
