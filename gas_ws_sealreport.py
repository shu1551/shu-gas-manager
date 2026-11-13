# -*- coding: utf-8 -*-
"""
gas_ws_sealreport.py - 段 T2 の「封の前」の一覧（番頭が見る）。AI なし。
  ・模範ごとの差分の一覧（1 本 1〜2 行）: golden の記録の最新（`diff`・`n_diff`）から
  ・表ごとの要約: ws_trial/tables/*.json（業務・種類・大きさ・汚れ／癖の説明）と、その表を使う台本の数
  ・癖の表（kind=quirk）の ws_look の画像: 試験場に流し込んで look → gas_workspace_view.render_to_png（Playwright）
使い方: py -X utf8 gas.py ws-trial seal-report [--images] [--out ファイル] [--img-dir フォルダ]
"""

import glob
import json
import re
import shutil
from pathlib import Path

import gas_ws_shot as S
import gas_ws_tables as T

HERE = Path(__file__).resolve().parent
RUNS = HERE / "ws_trial" / "runs"
TABLES_DIR = HERE / "ws_trial" / "tables"


def latest_golden(runs_dir=RUNS):
    """golden の記録を古い順に読み、本ごとの最新"""
    last = {}
    for f in sorted(Path(runs_dir).glob("golden_*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if "id" in r:
                last[r["id"]] = r
    return last


def table_rows():
    out = []
    for f in sorted(TABLES_DIR.glob("*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        sh = (t.get("sheets") or [{}])[0]
        tb = (sh.get("tables") or [{}])[0] if sh else {}
        try:
            n = len(T.expand_sheet(sh)) if sh.get("name") else 0
        except Exception:
            n = 0
        out.append({"name": t["name"], "business": t.get("business", ""), "kind": t.get("kind", ""), "notes": t.get("notes", ""),
                    "doc": bool(t.get("doc")) and not t.get("sheets"), "rows": n, "header": tb.get("header_rows"), "data": tb.get("data"), "total": tb.get("total_row")})
    return out


def capture_images(eng, file_id, names, img_dir, out=print):
    """癖の表を流し込んで ws_look の画像にする。返り値は {表の名前: 画像のファイル名}"""
    import gas_workspace_view as V
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    got = {}
    for tn in names:
        t = T.load_table(tn)
        if not t.get("sheets"):
            continue
        r = eng.seed(file_id, t)
        if not r.get("ok"):
            out(f"[流し込み失敗] {tn}: {str(r.get('error'))[:100]}")
            continue
        res = eng._post({"action": "look", "target": {"id": file_id, "kind": "sheet"}, "sheet": t["sheets"][0]["name"], "range": ""})
        try:
            p = V.render_to_png(res, img_dir)
        except Exception as e:  # noqa: BLE001
            out(f"[画像失敗] {tn}: {str(e)[:100]}")
            continue
        dest = img_dir / f"{tn}.png"
        shutil.move(str(p), str(dest))
        got[tn] = dest.name
        out(f"画像: {tn}")
    return got


def build_md(cases, golden, tables, images=None, img_rel="161_images"):
    images = images or {}
    by_table = {}
    for c in cases:
        by_table.setdefault(c["table"], []).append(c["id"])
    L = ["# 161 封の前の一覧（段 T2・番頭が見る）", "",
         "封（`seal`）は番頭の OK の後。模範は golden の最新の記録の「撃つ前 → 撃った後」の差分、表は表の JSON の要約です。",
         "",
         "- 差分の一覧が見る物: セルの値・式・書式の有無・結合・固定、シートの増減、文書の段落と書式。**見ない物**: グラフ・入力規則・条件付き書式・保護・縞・フィルタ・隠し行（これらを変える本は「差分なし」と出る。期待の条件で確かめている）。",
         "- 大きい表（scale_big）は先頭 60 行と末尾 20 行を細かく、全体は値と式の要約で比べている。",
         "- 対象外「–」は、再生する模範が無い台本（聞き返す・断る 23 本）と、文書を探す棚が無い gij-05。",
         "- OK が出たら: `seal`（sealed.tsv）→ `props --changed --with-engine --refail --jobs 5`（直した共通部の確かめ）→ `props --all --jobs 5` を 1 回。", ""]
    marks = {}
    for r in golden.values():
        marks[r["mark"]] = marks.get(r["mark"], 0) + 1
    L += [f"## 1. 模範の再生（{len(golden)} 本）: " + "・".join(f"{k} {v}" for k, v in sorted(marks.items())), ""]
    L += ["| 本 | 表 | 頼み | 印 | 差分（前 → 後・最初の 2 つ） |", "|---|---|---|---|---|"]
    for c in cases:
        r = golden.get(c["id"], {})
        mk = r.get("mark", "?")
        if mk == "○":
            d = r.get("diff") or []
            tail = f"（全 {r.get('n_diff')} 件）" if r.get("n_diff", 0) > 2 else ""
            txt = "<br>".join(x.replace("|", "｜")[:90] for x in d[:2]) + tail if d else "差分なし（変わらないのが期待）"
        else:
            txt = "；".join(r.get("why", []))[:120].replace("|", "｜")
        L.append(f"| {c['id']} | {c['table']} | {c['turns'][0]['say'][:28]} | {mk} | {txt} |")
    flag = []
    for c in cases:
        r = golden.get(c["id"], {})
        if r.get("mark") == "○" and not r.get("n_diff") and "変わっていない" not in json.dumps(c["turns"][0].get("expect"), ensure_ascii=False):
            flag.append(f"- **{c['id']}**（{c['table']}）「{c['turns'][0]['say'][:30]}」: 模範を撃っても差分が無い。すでにその状態か、差分の一覧が見ない物（グラフ・保護 等）を変えた。期待を満たしているので ○ だが、模範が何も確かめていない可能性")
    if flag:
        L += ["", "### 番頭に見てほしい所（模範を撃っても差分が無いのに、変わっていないことを期待していない本）", ""] + flag
    L += ["", "## 2. 表（" + str(len(tables)) + " 枚）", "",
          "| 表 | 業務 | 種類 | 行 | 台本 | 汚れ・癖の説明 |", "|---|---|---|---|---|---|"]
    for t in tables:
        ids = by_table.get(t["name"], [])
        L.append(f"| {t['name']} | {t['business']} | {t['kind']}{'（文書）' if t['doc'] else ''} | {t['rows'] or ''} | {len(ids)} | {t['notes'][:120].replace('|', '｜')} |")
    if images:
        L += ["", "## 3. 癖の表の ws_look の画像", ""]
        for tn, fn in images.items():
            L += [f"### {tn}", "", f"![{tn}]({img_rel}/{fn})", ""]
    return "\n".join(L) + "\n"


def run(eng=None, file_id=None, out_path=None, img_dir=None, images=False, out=print):
    cases = S.load_cases()
    golden = latest_golden()
    tables = table_rows()
    imgs = {}
    if images and eng is not None:
        imgs = capture_images(eng, file_id, [t["name"] for t in tables if t["kind"] == "quirk" and not t["doc"]], img_dir or HERE / "ws_trial" / "seal_images", out=out)
    if not imgs and img_dir and Path(img_dir).is_dir():
        imgs = {q.stem: q.name for q in sorted(Path(img_dir).glob("*.png"))}      # 撮り済みの画像を使う
    md = build_md(cases, golden, tables, imgs, img_rel=Path(img_dir).name if img_dir else "seal_images")
    if out_path:
        Path(out_path).write_text(md, encoding="utf-8")
    return md


def seal(out_path=None, out=print):
    """封: 全部の台本の最新の golden が ○（または模範なしの –）のときだけ ws_trial/sealed.tsv を書く。
    列: id・表・頼み・印・台本の指紋（台本 JSON の sha1 先頭 12 桁）。後で台本が変わったかを見分ける用"""
    import hashlib
    cases = S.load_cases()
    prev = S.latest_records("golden_")
    rows, bad = [], []
    for c in cases:
        r = prev.get(c["id"], {})
        mark = r.get("mark", "")
        if mark not in ("○", "◎", "–"):
            bad.append(f"{c['id']}（{mark or '記録なし'}）")
            continue
        fp = hashlib.sha1(json.dumps(c, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        rows.append([c["id"], c["table"], c["turns"][0]["say"].replace("\t", " "), mark, fp])
    if bad:
        out("封できません。通っていない本: " + "・".join(bad))
        return 1
    p = Path(out_path) if out_path else HERE / "ws_trial" / "sealed.tsv"
    p.write_text("id\ttable\tsay\tmark\tfp\n" + "\n".join("\t".join(x) for x in rows) + "\n", encoding="utf-8")
    n_ok = sum(1 for x in rows if x[3] != "–")
    out(f"封した: {len(rows)} 本（○ {n_ok}・対象外 {len(rows) - n_ok}）→ {p}")
    return 0
