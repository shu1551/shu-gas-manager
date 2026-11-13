"""gas_ws_coverage.py の試験"""
from types import SimpleNamespace
import gas_ws_coverage as CV


def test_analyze_coverage_detects_shortages():
    cases = [
        {
            "id": "c1",
            "kind": "集計",
            "tags": ["K1"],
            "turns": [{"approve": "まだ"}],
            "model": [{"shelf": "sh_a"}],
        },
        {
            "id": "c2",
            "kind": "請求",
            "tags": ["K1", "K1"],
            "turns": [{"approve": "ある"}],
            "model": [{"shelf": "sh_a"}, {"shelf": "doc.x"}],
        },
        {
            "id": "c3",
            "kind": "請求",
            "tags": ["J1"],
            "turns": [{"approve": "まだ"}],
            "model": [{"shelf": "sh_danger"}],
        },
    ]
    cat = SimpleNamespace(
        shelves=[
            {"name": "sh_a", "kind": "シート", "file": "sheet.gs", "danger": False, "touch": "書く"},
            {"name": "doc.x", "kind": "文書", "file": "doc.gs", "danger": False, "touch": "書く"},
            {"name": "sh_danger", "kind": "シート", "file": "sheet.gs", "danger": True, "touch": "消す"},
        ]
    )
    res = CV.analyze_coverage(cases=cases, catalog=cat, templates={"sh_a": {}})
    assert res["total_cases"] == 3
    # K1 は 3 本なので不足に入らない、K2..K19 や J1..J15 は不足に入る
    short_tags = {x["tag"] for x in res["tag_short"]}
    assert "K1" not in short_tags
    assert "J1" in short_tags
    # sh_a は 2 本（3 本未満）なので不足、doc.x は 1 本（2 本未満）なので不足
    short_shelves = {x["shelf"] for x in res["shelf_short"]}
    assert {"sh_a", "doc.x", "sh_danger"} <= short_shelves
    # sh_danger は まだ=1, ある=0 なので不足
    assert [x["shelf"] for x in res["danger_short"]] == ["sh_danger"]
    # format_report が文字列を返す
    txt = CV.format_report(res)
    assert "=== 網羅の検査" in txt
