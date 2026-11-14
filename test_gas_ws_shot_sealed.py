"""--set（見せない組）の shot の試験"""
import json
from pathlib import Path
from unittest.mock import patch
import gas_ws_shot as S
import gas_ws_trial as T


def test_run_shot_sealed_hides_text_and_writes_runs_dir(tmp_path):
    """sealed=True のとき、画面出力に台詞・表名・理由を出さず、runs_dir に記録を書く"""
    runs_dir = tmp_path / "runs"
    cases = [
        {
            "id": "S_L2B_01",
            "layer": "L2b",
            "table": "WS試験_売上",
            "turns": [{"say": "秘密の台詞テスト", "expect": {"ok": True}}],
            "model": [],
        }
    ]
    logs = []
    fake_res = {"mark": "◎", "F": "", "why": "秘密の理由テキスト", "got": ["売上を見る"]}
    with patch.object(S, "split_by_lint", return_value=(cases, [])), \
         patch.object(S.T, "load_table", return_value={}), \
         patch.object(S, "is_doc_table", return_value=False), \
         patch.object(S, "run_ai_turn", return_value=fake_res), \
         patch.object(S, "candidates_have_model", return_value=(True, [])):
        results, rf = S.run_shot(
            eng=object(),
            file_id="fid",
            cases=cases,
            model="sonnet",
            ask_fn=lambda p: ('{"ops":[]}', {"sec": 1.2}),
            out=logs.append,
            runs_dir=runs_dir,
            sealed=True,
        )

    assert len(results) == 1
    assert rf.parent == runs_dir
    assert rf.exists()
    joined = "\n".join(logs)
    assert "S_L2B_01" in joined
    assert "◎" in joined
    assert "秘密の台詞テスト" not in joined
    assert "秘密の理由テキスト" not in joined
    assert "WS試験_売上" not in joined


def test_shot_cmd_set_filters_l2b_only(tmp_path):
    """--set 指定時は sealed_dir/<組> から読み、L2b だけ回す"""
    sealed_dir = tmp_path / "WS試験_封"
    set_dir = sealed_dir / "境目"
    set_dir.mkdir(parents=True)
    fake_cases = [
        {"id": "C_L2B", "layer": "L2b", "table": "WS試験_売上", "turns": [{"say": "a"}]},
        {"id": "C_L1", "layer": "L1", "table": "WS試験_売上", "turns": [{"say": "b"}]},
    ]
    (set_dir / "cases.json").write_text(json.dumps(fake_cases, ensure_ascii=False), encoding="utf-8")

    st = {"sealed_dir": str(sealed_dir), "files": {"WS試験_場": "fid1"}}
    logs = []
    captured = {}

    def fake_run_shot(eng, fid, cases, **kw):
        captured["cases"] = cases
        captured["runs_dir"] = kw.get("runs_dir")
        captured["sealed"] = kw.get("sealed")
        return [{"mark": "◎", "F": "", "ai": {"sec": 1.0, "in_tokens": 10, "out_tokens": 5, "cost_usd": 0.0}}], sealed_dir / "runs" / "out.jsonl"

    class FakeEng:
        def __init__(self, client=None): pass
        def assert_not_prod(self): pass

    with patch.object(T, "load_state", return_value=st), \
         patch.object(T, "TrialEngine", FakeEng), \
         patch("gas_client.GasClient", return_value=object()), \
         patch.object(S, "run_shot", side_effect=fake_run_shot):
        rc = T.shot_cmd("shot", ["--set", "境目", "--model", "sonnet", "--jobs", "1"], out=logs.append)

    assert rc == 0
    assert [c["id"] for c in captured["cases"]] == ["C_L2B"]
    assert captured["runs_dir"] == sealed_dir / "runs"
    assert captured["sealed"] is True
    assert any("L2b 以外を 1 本飛ばして 1 本" in ln for ln in logs)
