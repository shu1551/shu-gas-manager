"""段 T4 の網羅（coverage）を数えて表と足りない物を出す（設計書 第 7 章 網羅の決まり 1・2・4）"""
import json
from collections import defaultdict
from pathlib import Path

import gas_ws_catalog as C
import gas_ws_shot as S

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "ws_trial" / "cases"
TEMPLATES_PATH = HERE / "ws_trial" / "templates.json"

K_TAGS = [f"K{i}" for i in range(1, 20)]
J_TAGS = [f"J{i}" for i in range(1, 16)]


def _is_doc_shelf(shelf):
    return shelf.get("kind") == "文書" or "doc" in (shelf.get("file") or "")


def _is_dangerous_shelf(shelf):
    return bool(shelf.get("danger")) or shelf.get("touch") in ("消す", "削除")


def analyze_coverage(cases=None, catalog=None, templates=None):
    cases = cases if cases is not None else S.load_cases(CASES_DIR)
    catalog = catalog if catalog is not None else C.load()
    if templates is None and TEMPLATES_PATH.exists():
        templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    templates = templates or {}

    # 決まり 1: K1..K19, J1..J15 の本数
    tag_counts = defaultdict(int)
    for c in cases:
        for t in c.get("tags") or []:
            tag_counts[t] += 1
    tag_short = [
        {"tag": t, "count": tag_counts[t]}
        for t in (K_TAGS + J_TAGS)
        if tag_counts[t] < 3
    ]

    # 決まり 2・4: 棚ごとの模範本数・業務数・approve の有無
    shelf_cases = defaultdict(list)
    for c in cases:
        for sh in set(S.model_shelves(c)):
            shelf_cases[sh].append(c)

    shelf_rows = []
    shelf_short = []
    danger_short = []

    for sh in catalog.shelves:
        name = sh["name"]
        cs = shelf_cases[name]
        n = len(cs)
        kinds = sorted({c.get("kind") or "" for c in cs if c.get("kind")})
        is_doc = _is_doc_shelf(sh)
        is_danger = _is_dangerous_shelf(sh)
        has_tpl = name in templates

        row = {
            "shelf": name,
            "doc": is_doc,
            "danger": is_danger,
            "has_template": has_tpl,
            "count": n,
            "kinds": kinds,
        }
        shelf_rows.append(row)

        if is_doc:
            if n < 2:
                shelf_short.append({"shelf": name, "doc": True, "count": n, "kinds": len(kinds), "need": "2本以上"})
        else:
            if n < 3 or len(kinds) < 2:
                shelf_short.append({"shelf": name, "doc": False, "count": n, "kinds": len(kinds), "need": "3本以上・2業務以上"})

        if is_danger:
            mada = sum(1 for c in cs if (c.get("turns") or [{}])[0].get("approve") == "まだ")
            aru = sum(1 for c in cs if (c.get("turns") or [{}])[0].get("approve") == "ある")
            if mada == 0 or aru == 0:
                danger_short.append({"shelf": name, "まだ": mada, "ある": aru})

    return {
        "total_cases": len(cases),
        "tag_counts": dict(tag_counts),
        "tag_short": tag_short,
        "shelf_rows": shelf_rows,
        "shelf_short": shelf_short,
        "danger_short": danger_short,
    }


def format_report(res):
    lines = [f"=== 網羅の検査（学ぶ組 {res['total_cases']} 本） ==="]
    lines.append(f"\n[決まり 1] K・J の印で 3 本未満 ({len(res['tag_short'])} 件):")
    for x in res["tag_short"]:
        lines.append(f"  - {x['tag']}: {x['count']} 本")

    lines.append(f"\n[決まり 2] 模範が足りない棚 ({len(res['shelf_short'])} 件):")
    for x in res["shelf_short"]:
        lines.append(f"  - {x['shelf']}: {x['count']} 本 / {x['kinds']} 業務 (目当て: {x['need']})")

    lines.append(f"\n[決まり 4] 危ない棚で approve: まだ / ある の片方が無い ({len(res['danger_short'])} 件):")
    for x in res["danger_short"]:
        lines.append(f"  - {x['shelf']}: まだ={x['まだ']} 本, ある={x['ある']} 本")

    return "\n".join(lines)


def main():
    res = analyze_coverage()
    print(format_report(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
