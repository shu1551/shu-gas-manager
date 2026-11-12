# -*- coding: utf-8 -*-
"""
脇の状態（戻しが約束していない物）が ws_undo で戻るかの調べ（指示書 143）。試験用のエンジンと試験場だけに撃つ。直さない・調べるだけ。
  py ws_trial/side_probe.py [報告の書き出し先.md]
場合 A: 項目を付ける → 控えを作る棚（write）→ 項目を外す・変える → ws_undo → 元の形に戻るか
場合 B: 項目が付いた状態で値だけ変える棚を撃つ → ws_undo → 項目の形が変わっていないか
先に「固定」（戻ると分かっている）で測り方が正しいかを確かめる。読めない項目は判定せずに「読めず」と書く。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gas_ws_tables as T   # noqa: E402
import gas_ws_trial as TR   # noqa: E402

ITEMS = [  # (キー, 表の名前, 読む物の説明)
    ("frozen", "固定"),
    ("validation_list", "入力規則（プルダウン）"), ("validation_checkbox", "入力規則（チェックボックス）"), ("cf", "条件付き書式"), ("banding", "交互の色"),
    ("filter", "フィルタ"), ("hide_rows", "行の隠し"), ("hide_cols", "列の隠し"), ("hide_sheet", "シートの隠し"),
    ("group_rows", "行のグループ"), ("group_cols", "列のグループ"), ("protect_sheet", "シートの保護"), ("protect_range", "範囲の保護"),
    ("named", "名前付き範囲"), ("tab_color", "タブの色"), ("chart", "グラフ"),
]

# ×のとき、控えのときに何を記録すれば戻せそうか（調べた結果を読んだ上での見立て。×の項目だけ報告に出る）
HOW = {
    "frozen": "今のまま（frozenR・frozenC を記録して戻す）",
    "validation_list": "範囲ごとの条件（種類・選択肢・厳密か）を記録し、戻すとき付け直す",
    "validation_checkbox": "チェックボックスの範囲を記録し、戻すとき insertCheckboxes で付け直す",
    "cf": "規則の一覧（範囲・条件・値・背景・文字色）を記録し、戻すとき消してから付け直す",
    "banding": "交互の色の範囲・テーマ（ヘッダー・フッターの有無）を記録し、戻すとき消してから付け直す",
    "filter": "フィルタの範囲と、列ごとの条件（隠す値・条件の種類）を記録し、戻すとき消してから付け直す",
    "hide_rows": "隠した行の番号の一覧を記録し、戻すとき全部出してから隠し直す",
    "hide_cols": "隠した列の番号の一覧を記録し、戻すとき全部出してから隠し直す",
    "hide_sheet": "シートの隠しの有無（ブック単位の台帳の項目）を記録し、戻すとき showSheet・hideSheet で合わせる",
    "group_rows": "グループの範囲・深さ・折りたたみを記録し、戻すとき全部外してから作り直す",
    "group_cols": "グループの範囲・深さ・折りたたみを記録し、戻すとき全部外してから作り直す",
    "protect_sheet": "保護の種類・説明・警告だけか・編集できる人を記録し、戻すとき消してから付け直す",
    "protect_range": "範囲・説明・警告だけか・編集できる人を記録し、戻すとき消してから付け直す",
    "named": "名前→範囲の一覧（ブック単位の台帳の項目）を記録し、戻すとき合わせる",
    "tab_color": "タブの色（ブック単位の台帳の項目）を記録し、戻すとき setTabColor で合わせる",
    "chart": "グラフの種類・範囲・位置・題・軸の設定（spec）を記録し、戻すとき消してから insertChart で作り直す",
}


def sheet_named(snap, name="名簿"):
    for s in snap["sheets"]:
        if s["name"] == name:
            return s
    return None


def readout(snap, item):
    s = sheet_named(snap)
    side = s.get("side", {}) if s else {}
    if item == "frozen":
        return s["frozen"]
    if item == "validation_list":
        return {k: v for k, v in side.get("validations", {}).items() if v["type"] == "ONE_OF_LIST"}
    if item == "validation_checkbox":
        return {k: v for k, v in side.get("validations", {}).items() if v["type"] == "BOOLEAN"}
    if item == "cf":
        return side.get("cf_rules")
    if item == "banding":
        return side.get("banded")
    if item == "filter":
        return {"filter": side.get("filter"), "filtered_rows": s["filtered_rows"]} if side.get("filter") or s["filtered_rows"] else None
    if item == "hide_rows":
        return s["hidden_rows"]
    if item == "hide_cols":
        return s["hidden_cols"]
    if item == "hide_sheet":
        return {"名簿が隠れている": bool(s["hidden"]), "シート": [x["name"] for x in snap["sheets"]]} if s["hidden"] else None
    if item == "group_rows":
        return side.get("groups", {}).get("rows")
    if item == "group_cols":
        return side.get("groups", {}).get("cols")
    if item == "protect_sheet":
        return [p for p in side.get("protected", []) if p["range"] == "シート全体"]
    if item == "protect_range":
        return [p for p in side.get("protected", []) if p["range"] != "シート全体"]
    if item == "named":
        return snap.get("named")
    if item == "tab_color":
        return side.get("tab_color")
    if item == "chart":
        return side.get("charts")
    raise ValueError(item)


def values_of(snap):
    sh = sheet_named(snap)
    return {a: c.get("v") for a, c in sh["cells"].items() if c.get("v") not in ("", None)} if sh else {}


def empty(v):
    return v in (None, [], {}, "", False)


def judge(r, item):
    """1 回の結果を判定する。返り値は (判定, 何が違ったか)。判定: 戻る/戻らない/変わらない/変わった/読めず/undo失敗"""
    if not r.get("ok"):
        return "読めず", f"調べの POST が失敗（{r.get('step')}）: " + str(r.get("error"))[:100]
    x, z, y = (readout(r[k], item) for k in ("x", "z", "y"))
    if empty(x):
        return "読めず", "項目を付けた後の撮影に項目が出てこない（付け方か読み方の問題）"
    undo = r.get("undo") or {}
    if not undo.get("ok"):
        return "undo失敗", "ws_undo が失敗: " + str(undo.get("error"))[:120]
    vx, vy = values_of(r["x"]), values_of(r["y"])      # 値も付けた直後に戻っているか（フィルタで隠れた行が落ちて値がずれる不具合を見張る）
    if vx != vy:
        diff = [k for k in sorted(set(vx) | set(vy)) if vx.get(k) != vy.get(k)]
        return "戻らない", f"値が違う（{len(diff)} セル。例 {diff[0]}: {vx.get(diff[0])!r} → {vy.get(diff[0])!r}）"
    if r["case"] == "A":
        if z == x:
            return "読めず", "外す・変える手を撃っても撮影が変わらない（変えた効果が読めない）"
        return ("戻る", "") if y == x else ("戻らない", f"付けた直後 {_s(x)} → 外した後 {_s(z)} → ws_undo の後 {_s(y)}")
    return ("変わらない", "") if y == x else ("変わった", f"付けた直後 {_s(x)} → 値を変えた棚の後 {_s(z)} → ws_undo の後 {_s(y)}")


def _s(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 90 else s[:87] + "…"


def run(eng, file_id, out=print):
    table = T.load_table("meibo_base")
    payload = T.seed_payload(table)
    rows = []
    for item, label in ITEMS:
        res = {}
        for case in ("A", "B"):
            r = eng.trial_post("side_case", id=file_id, seed=payload, item=item, case=case)
            res[case] = judge(r, item)
            out(f"{label} 場合 {case}: {res[case][0]} {res[case][1]}")
        rows.append((item, label, res))
        if item == "frozen":
            ok = res["A"][0] == "戻る" and res["B"][0] == "変わらない"
            out("測り方の確かめ（固定）: " + ("正しい（戻ると分かっている固定が、戻る・変わらないと測れた）" if ok else "NG 固定が想定どおりに測れない。以降は信用しない"))
            if not ok:
                return rows, False
    return rows, True


def report(rows, calibrated):
    L = ["# 143 脇の状態が ws_undo で戻るかの調べ（試験用のエンジン・試験場）", "",
         f"- 測り方の確かめ（固定）: {'○ 戻る・変わらない と測れた' if calibrated else '× 想定どおりに測れなかった'}",
         "- 場合 A: 項目を付ける → write（控えができる）→ 項目を外す・変える → ws_undo → 付けた直後の形に戻るか",
         "- 場合 B: 項目が付いた状態で write（値だけ変える）→ ws_undo → 項目の形が付けた直後と同じか",
         "- 読み方: 試験用のエンジンの snap（Sheets API の spreadsheets.get）。読めない項目は判定せず「読めず」", "",
         "| 項目 | A（外す・変える→undo） | B（値だけ変える→undo） | 何が違ったか | ×なら控えのとき何を記録すれば戻せそうか |", "|---|---|---|---|---|"]
    for item, label, res in rows:
        a, b = res["A"], res["B"]
        bad = a[0] not in ("戻る",) or b[0] not in ("変わらない",)
        diff = "；".join(x for x in (f"A: {a[1]}" if a[1] else "", f"B: {b[1]}" if b[1] else "") if x) or "—"
        how = HOW[item] if (a[0] == "戻らない" or b[0] == "変わった") else ("（読めず・undo 失敗を先に直す）" if bad else "—")
        L.append(f"| {label} | {a[0]} | {b[0]} | {diff} | {how} |")
    return "\n".join(L) + "\n"


def main(argv):
    from gas_client import GasClient
    st = TR.load_state()
    eng = TR.TrialEngine(client=GasClient())
    eng.assert_not_prod()
    fid = st["files"]["WS試験_場"]
    rows, ok = run(eng, fid)
    text = report(rows, ok)
    print(text)
    if argv:
        Path(argv[0]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
