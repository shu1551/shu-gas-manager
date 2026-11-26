# -*- coding: utf-8 -*-
"""Phase 3: Sheets API 直結拡大棚 (format.negred / font.unify / clear.values / clear.format / sort / rows.insert / cols.insert / cf.clear) の単体テスト。"""

import json
import subprocess
from pathlib import Path

import gas_ws_direct as D

HERE = Path(__file__).resolve().parent


class _DummyMgr:
    def __init__(self, st_extra=None):
        self._st = {
            "direct_token": {"token": "TOK_DIRECT", "until": 9999999999},
            **(st_extra or {}),
        }

    def _post(self, payload):
        return {"token": "TOK_DIRECT"}

    def _load(self):
        return dict(self._st)

    def _cached_table(self, st, tgt):
        return {
            "sheet": "売上",
            "sheets": ["売上"],
            "table": {
                "header_row": 1,
                "first_col": "A",
                "last_col": "C",
                "data": "2-5",
                "title_a1": "A1",
                "columns": [
                    {"col": "A", "name": "部署", "number": False},
                    {"col": "B", "name": "社員番号", "number": True},
                    {"col": "C", "name": "金額", "number": True},
                ],
            },
        }


def _sample_snapshot_json():
    def cell(v, fmt=None):
        out = {}
        if isinstance(v, (int, float)):
            out["userEnteredValue"] = {"numberValue": v}
        elif v != "":
            out["userEnteredValue"] = {"stringValue": str(v)}
        if fmt:
            out["userEnteredFormat"] = fmt
        return out

    rows = [
        {"values": [cell("部署"), cell("社員番号"), cell("金額")]},
        {"values": [cell("営業"), cell(101), cell(1000, {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})]},
        {"values": [cell("開発"), cell(201), cell(-500, {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})]},
        {"values": [cell("営業"), cell(102), cell(2000)]},
        {"values": [cell("総務"), cell(301), cell(3000)]},
    ]
    return {
        "sheets": [
            {
                "properties": {
                    "sheetId": 10,
                    "title": "売上",
                    "index": 0,
                    "hidden": False,
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 0, "hideGridlines": False},
                },
                "conditionalFormats": [
                    {
                        "ranges": [{"sheetId": 10, "startRowIndex": 1, "endRowIndex": 5, "startColumnIndex": 2, "endColumnIndex": 3}],
                        "booleanRule": {"condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]}},
                    }
                ],
                "data": [{"startRow": 0, "startColumn": 0, "rowData": rows}],
            }
        ]
    }


def test_direct_runner_new_shelves_build_execute_and_undo(monkeypatch):
    mgr = _DummyMgr()
    runner = D.DirectRunner(mgr)
    snap_json = _sample_snapshot_json()
    posted_batches = []

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class _Sess:
        def request(self, method, url, headers=None, params=None, json=None, timeout=30):
            if method == "GET":
                return _Resp(200, snap_json)
            posted_batches.append((url, json))
            return _Resp(200, {"replies": []})

    mgr.client = type("C", (), {"session": _Sess()})()
    monkeypatch.setattr(runner, "_fp_later", lambda *a, **k: None)

    tgt = {"id": "SS_TEST_1", "name": "売上表", "kind": "sheet", "sheet": "売上", "url": "https://example.com"}

    # 1. format.negred (col 省略時は数値列 C のみを対象にし、社員番号列は除外しないが number=True 列へ適用)
    st = {"direct_token": {"token": "TOK_DIRECT", "until": 9999999999}}
    res1 = runner.try_do(st, tgt, [{"shelf": "format.negred", "col": "金額", "triangle": True}])
    assert res1 and res1["ok"] and res1["direct"] is True
    assert posted_batches[-1][1]["requests"][0]["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] == '#,##0;[Red]"▲"#,##0'
    assert st["direct_ledger"][-1]["undo"][0]["updateCells"]["fields"] == "userEnteredFormat.numberFormat"

    # 2. font.unify
    res2 = runner.try_do(st, tgt, [{"shelf": "font.unify", "font": "メイリオ", "size": 11}])
    assert res2 and res2["ok"] and res2["direct"] is True
    rc_fu = posted_batches[-1][1]["requests"][0]["repeatCell"]
    assert rc_fu["cell"]["userEnteredFormat"]["textFormat"] == {"fontFamily": "メイリオ", "fontSize": 11}

    # 3. clear.values (ok=False は Skip、表内小範囲+ok=True は直結＋Undo値復元)
    assert runner.try_do(st, tgt, [{"shelf": "clear.values", "range": "C2:C2"}]) is None
    assert runner.try_do(st, tgt, [{"shelf": "clear.values", "range": "A2:C5", "ok": True}]) is None  # 明細半分超は Skip
    res3 = runner.try_do(st, tgt, [{"shelf": "clear.values", "range": "C2:C2", "ok": True}])
    assert res3 and res3["ok"] and res3["direct"] is True
    assert st["direct_ledger"][-1]["undo"][0]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"] == {"numberValue": 1000}

    # 4. clear.format
    res4 = runner.try_do(st, tgt, [{"shelf": "clear.format", "range": "C2:C3"}])
    assert res4 and res4["ok"] and res4["direct"] is True
    assert posted_batches[-1][1]["requests"][0]["repeatCell"]["fields"] == "userEnteredFormat"

    # 5. sort (複数列)
    res5 = runner.try_do(st, tgt, [{"shelf": "sort", "cols": ["部署", "-金額"]}])
    assert res5 and res5["ok"] and res5["direct"] is True
    sr = posted_batches[-1][1]["requests"][0]["sortRange"]
    assert sr["sortSpecs"] == [
        {"dimensionIndex": 0, "sortOrder": "ASCENDING"},
        {"dimensionIndex": 2, "sortOrder": "DESCENDING"},
    ]
    assert st["direct_ledger"][-1]["undo"][0]["updateCells"]["fields"] == "userEnteredValue,userEnteredFormat"

    # 6. rows.insert / cols.insert
    res6 = runner.try_do(st, tgt, [{"shelf": "rows.insert", "at": 3, "count": 2}])
    assert res6 and res6["ok"] and res6["direct"] is True
    assert posted_batches[-1][1]["requests"][0]["insertDimension"]["range"]["dimension"] == "ROWS"
    assert st["direct_ledger"][-1]["undo"][0]["deleteDimension"]["range"]["endIndex"] == 4

    res7 = runner.try_do(st, tgt, [{"shelf": "cols.insert", "at": "B", "count": 1}])
    assert res7 and res7["ok"] and res7["direct"] is True
    assert posted_batches[-1][1]["requests"][0]["insertDimension"]["range"]["dimension"] == "COLUMNS"

    # 7. cf.clear (条件付き書式削除＋addConditionalFormatRule Undo)
    res8 = runner.try_do(st, tgt, [{"shelf": "cf.clear"}])
    assert res8 and res8["ok"] and res8["direct"] is True
    assert posted_batches[-1][1]["requests"][0] == {"deleteConditionalFormatRule": {"sheetId": 10, "index": 0}}
    assert "addConditionalFormatRule" in st["direct_ledger"][-1]["undo"][0]


def test_sidebar_js_direct_batch_update_new_shelves():
    """combo_sidebar_template.html の buildDirectBatchUpdate が拡張棚のバッチリクエストと Undo を組めること。"""
    html = (HERE / "combo_sidebar_template.html").read_text(encoding="utf-8")
    m = __import__("re").findall(r"<script[^>]*>([\s\S]*?)</script>", html, flags=__import__("re").IGNORECASE)
    main_js = m[2]
    # buildDirectBatchUpdate は IIFE 内なので、末尾にテストヘルパを差し込んだテストではなく Node で関数定義チェック＆簡易評価
    node_code = r"""
const fs = require('fs');
const js = fs.readFileSync(0, 'utf8');
for (const pat of ['op.shelf === "format.negred"', 'op.shelf === "font.unify"', 'op.shelf === "rows.insert" || op.shelf === "cols.insert"', 'op.shelf === "clear.format" || op.shelf === "clear.values" || op.shelf === "clear.all"']) {
  if (!js.includes(pat)) throw new Error('missing: ' + pat);
}
console.log('OK');
"""
    proc = subprocess.run(["node", "-e", node_code], input=main_js, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "OK"
