# -*- coding: utf-8 -*-
"""日付を書く所の見張り（道具が自分で止まる仕組み）。

エンジン（GAS）の時刻帯で作った Date を、そのままシートに書くと、スプレッドシートの時刻帯との差で 1 日ずれる
（11/27 に date.fix・seiri の和暦・fill.date で 3 回起きた）。シートに書く日付は formatDateCell_（文字の yyyy/mm/dd）を
通してシートの時刻帯で日付にさせる。ここに引っかかったら、書き方を formatDateCell_ に直すこと。
今の瞬間（時刻）を書くなど、Date のままが正しい行だけ、行末に「date-ok:」と理由を書いて通す。
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
BAD = [
    re.compile(r"\.push\(\s*new Date\("),              # 配列に Date を積んで setValues する
    re.compile(r"new Date\(\s*\d{4}\s*,"),             # 年月日の部品から作った固定の日付
    re.compile(r"\.setValues?\(\s*new Date\("),        # Date を直に書く
]


def test_no_component_dates_written_to_cells():
    hits = []
    for f in sorted((HERE / "ws_shelves").glob("*.gs")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "date-ok:" in line:
                continue
            if any(b.search(line) for b in BAD):
                hits.append(f"{f.name}:{i}: {line.strip()[:120]}")
    assert not hits, "シートに Date をそのまま書いている所があります（formatDateCell_ を通す）:\n" + "\n".join(hits)
