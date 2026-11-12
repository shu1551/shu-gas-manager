# -*- coding: utf-8 -*-
"""
汎用の手 api の実機の確かめ（試験用のエンジンと試験場だけ）。型を撃って ws_undo で元の形に戻ることを見る。
  py ws_trial/api_probe.py
  1. 値・書式（repeatCell）  2. 行の隠し（updateDimensionProperties）  3. 名前付き範囲（addNamedRange・ブック単位）  4. 条件付き書式の規則（addConditionalFormatRule）
  5. 消す型（deleteDimension）: ok なしで止まり何も変わらない → ok つきで撃つ → ws_undo で戻る
  6. 表に無い型・戻らない欄は撃つ前に断られる
戻ったかは、約束の指紋（値・式・素の書式・数の書式・結合・固定・シートの並び）と、脇の状態の読み出し（side_probe と同じ）で見る。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gas_workspace as gw   # noqa: E402
import gas_ws_judge as J     # noqa: E402
import gas_ws_tables as T    # noqa: E402
import gas_ws_trial as TR    # noqa: E402
import side_probe as S       # noqa: E402

CASES = [
    ("値・書式（repeatCell）", {"shelf": "api", "why": "見出しを青く", "requests": [{"repeatCell": {"range": "A1:F1", "cell": {"userEnteredFormat": {"backgroundColor": "#4285F4"}}, "fields": "userEnteredFormat.backgroundColor"}}]}, None),
    ("行の隠し（updateDimensionProperties）", {"shelf": "api", "why": "9 行目を隠す", "requests": [{"updateDimensionProperties": {"range": {"sheetId": "名簿", "dimension": "ROWS", "startIndex": 8, "endIndex": 9}, "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}}]}, "hide_rows"),
    ("名前付き範囲（addNamedRange）", {"shelf": "api", "why": "金額列に名前を付ける", "requests": [{"addNamedRange": {"namedRange": {"name": "試験範囲", "range": "F2:F20"}}}]}, "named"),
    ("条件付き書式（addConditionalFormatRule）", {"shelf": "api", "why": "12000 超を黄色に", "requests": [{"addConditionalFormatRule": {"rule": {"ranges": ["F2:F20"], "booleanRule": {"condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "11999"}]}, "format": {"backgroundColor": "yellow"}}}, "index": 0}}]}, "cf"),
]


def state(snap, item):
    fp, order = J.promise_fingerprints(snap)
    return {"fp": fp, "order": order, "side": S.readout(snap, item) if item else None}


def main():
    from gas_client import GasClient
    st = TR.load_state()
    eng = TR.TrialEngine(client=GasClient())
    eng.assert_not_prod()
    fid = st["files"]["WS試験_場"]
    table = T.load_table("meibo_base")
    out, ok_all = [], True

    def line(s):
        out.append(s)
        print(s, flush=True)

    for label, op, item in CASES:
        eng.seed(fid, table)
        s0 = eng.snap(fid)
        text = eng.do([op], target=fid)
        s1 = eng.snap(fid)
        changed = state(s0, item) != state(s1, item)
        undo = eng.undo()
        s2 = eng.snap(fid)
        back = state(s0, item) == state(s2, item)
        ok_all &= changed and back
        line(f"{'○' if changed and back else '×'} {label}: 撃つと変わった={changed}・ws_undo で元どおり={back}（{text.splitlines()[1] if len(text.splitlines()) > 1 else text}）")
    # 消す型は ok なしで止まり、ok つきで撃て、ws_undo で戻る
    op = {"shelf": "api", "why": "3 行目を消す", "requests": [{"deleteDimension": {"range": {"sheetId": "名簿", "dimension": "ROWS", "startIndex": 2, "endIndex": 3}}}]}
    eng.seed(fid, table)
    s0 = eng.snap(fid)
    t1 = eng.do([op], target=fid)
    s1 = eng.snap(fid)
    stopped = "止めました" in t1 and state(s0, None) == state(s1, None)
    t2 = eng.do([op], target=fid, ok=True)
    s2 = eng.snap(fid)
    deleted = state(s0, None) != state(s2, None)
    eng.undo()
    s3 = eng.snap(fid)
    back = state(s0, None) == state(s3, None) and S.values_of(s0) == S.values_of(s3)
    ok_all &= stopped and deleted and back
    line(f"{'○' if stopped and deleted and back else '×'} 消す型（deleteDimension）: ok なしで止まり何も変えない={stopped}・ok つきで消えた={deleted}・ws_undo で戻る={back}")
    # 表に無い型・戻らない欄は撃つ前に断られる（Python の検査）
    refused = []
    for bad in ({"shelf": "api", "requests": [{"deleteSheet": {"sheetId": 1}}]},
                {"shelf": "api", "requests": [{"updateSheetProperties": {"properties": {}, "fields": "gridProperties.hideGridlines"}}]}):
        try:
            eng.do([bad], target=fid)
            refused.append(False)
        except gw.WorkspaceError:
            refused.append(True)
    ok_all &= all(refused)
    line(f"{'○' if all(refused) else '×'} 表に無い型・戻らない欄は撃つ前に断られる: {refused}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
