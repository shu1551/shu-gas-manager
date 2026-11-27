# -*- coding: utf-8 -*-
"""ws_look / ws_do 用の軽量「気づき」分析モジュール（型 1・2・4・6・7）。

対象の表（メモリ上の値・数式・見出し・脇情報）だけを見て、
当てずっぽうを排除した確かな気づきだけを最大 3 行返す。
"""

import re

_EMAIL_HEAD_RE = re.compile(r"(?:メール|mail|e-?mail|アドレス)", re.I)
_PHONE_HEAD_RE = re.compile(r"(?:電話|携帯|tel|fax|連絡先)", re.I)
_DATE_HEAD_RE = re.compile(r"(?:日|date|年月|期限|締切)", re.I)
_NOTE_HEAD_RE = re.compile(r"(?:備考|メモ|注記|状態|ステータス|コメント|note|remark)", re.I)
_PROG_HEAD_RE = re.compile(r"(?:進捗|達成|完了率|progress)", re.I)
_AMT_HEAD_RE = re.compile(r"(?:金額|売上|合計|小計|請求|支払|価格|amount|total)", re.I)

_DISCOUNT_NOTE_RE = re.compile(r"(?:値引|割引|ディスカウント|半額|off|OFF)")
_ZERO_NOTE_RE = re.compile(r"(?:無料|無償|0円|キャンセル|取消|中止)")
_DONE_NOTE_RE = re.compile(r"(?:完了|済)")
_NOT_DONE_NOTE_RE = re.compile(r"(?:未着手|中止|保留)")

_EMAIL_VALID_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_WAREKI_RE = re.compile(r"^[MTSHR明治大正昭和平成令和]\s*\d{1,2}[./年]")
_ZEN_NUM_RE = re.compile(r"[０-９]")
_MONTH_RE = re.compile(r"(?:(上期|下期)\s*[・/／]?\s*)?(\d{1,2})月")


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _col_num(col: str) -> int:
    n = 0
    for ch in str(col or "").strip().upper():
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
    return n


def _to_float(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    # パーセントや通貨・カンマを除去（ただし日付やハイフン区切りは除外）
    if re.search(r"[/@]", s):
        return None
    is_pct = s.endswith("%") or s.endswith("％")
    s_clean = s.rstrip("%％").replace(",", "").replace("¥", "").replace("￥", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s_clean):
        return None
    num = float(s_clean)
    return num / 100.0 if is_pct else num


def _parse_data_range(tb):
    if not tb or not tb.get("data"):
        return None
    parts = str(tb["data"]).split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def analyze_table_insights(
    table,
    values_grid,
    formulas_grid=None,
    side=None,
    ops=None,
    max_items=3,
):
    """表の値・数式・見出し・脇情報から確かな気づきを最大 max_items 件返す。"""
    if not table or not values_grid:
        return []
    dr = _parse_data_range(table)
    if not dr:
        return []
    first_data, last_data = dr
    if last_data < first_data:
        return []

    cols = table.get("columns") or []
    if not cols:
        return []
    col_infos = []
    for c in cols:
        ci = _col_num(c.get("col"))
        if ci > 0:
            col_infos.append({
                "ci": ci,
                "col": str(c.get("col")),
                "name": str(c.get("name") or c.get("col")),
                "number": bool(c.get("number")),
            })
    if not col_infos:
        return []

    formulas_grid = formulas_grid or []
    side = side or []
    ops = ops or []
    op_shelves = {str(o.get("shelf") or "") for o in ops if isinstance(o, dict)}
    op_cols = {str(o.get("col") or "").strip() for o in ops if isinstance(o, dict) and o.get("col")}

    def get_val(r1: int, c1: int):
        if 1 <= r1 <= len(values_grid):
            row = values_grid[r1 - 1]
            if 1 <= c1 <= len(row):
                return row[c1 - 1]
        return ""

    def get_form(r1: int, c1: int) -> str:
        if 1 <= r1 <= len(formulas_grid):
            row = formulas_grid[r1 - 1]
            if 1 <= c1 <= len(row):
                return str(row[c1 - 1] or "")
        return ""

    insights = []

    # --- 型4: 絞り込み・並べ替えと合計行 =SUM(...) の相性 ---
    total_row = table.get("total_row")
    has_filter = any("フィルタ" in str(ln) for ln in side) or bool(
        op_shelves & {"filter", "filter.where", "sort"}
    )
    if total_row and has_filter:
        sum_cols = []
        for ci_info in col_infos:
            f = get_form(int(total_row), ci_info["ci"])
            if f.upper().startswith("=SUM("):
                sum_cols.append(ci_info["col"])
        if sum_cols:
            insights.append(
                f"合計行（{total_row}行目）が =SUM(...) のため、絞り込み中も非表示行を含めて合計されます。"
                "表示行だけ合計するには =SUBTOTAL(9, ...) が適しています"
            )

    # --- 型1: 計算で出せる列が、式でなく値で入っている ---
    # 2行以上の数値データがあり、数式がないセルが2つ以上ある数値列を対象に検査
    num_cols = [c for c in col_infos if c["number"]]
    if len(num_cols) >= 3 and (last_data - first_data + 1) >= 2:
        col_nums = {}
        col_forms = {}
        for c in num_cols:
            vals_map = {}
            forms_map = {}
            for r in range(first_data, last_data + 1):
                vals_map[r] = _to_float(get_val(r, c["ci"]))
                forms_map[r] = get_form(r, c["ci"])
            col_nums[c["col"]] = vals_map
            col_forms[c["col"]] = forms_map

        found_calc = False
        for target_c in num_cols:
            if found_calc:
                break
            tc_key = target_c["col"]
            if tc_key in op_cols or target_c["name"] in op_cols:
                continue
            # 値（非数式）の行を集める
            val_rows = [
                r for r in range(first_data, last_data + 1)
                if col_nums[tc_key][r] is not None and not col_forms[tc_key][r].startswith("=")
            ]
            if len(val_rows) < 2:
                continue
            # 他の2列の積・和・差を検証
            others = [c for c in num_cols if c["col"] != tc_key]
            for i in range(len(others)):
                if found_calc:
                    break
                for j in range(i + 1, len(others)):
                    c1, c2 = others[i], others[j]
                    k1, k2 = c1["col"], c2["col"]
                    valid_rows = [
                        r for r in val_rows
                        if col_nums[k1][r] is not None and col_nums[k2][r] is not None
                    ]
                    if len(valid_rows) < 2 or len(valid_rows) != len(val_rows):
                        continue
                    # 非自明チェック（定数0・1ばかりでないこと）
                    distinct_pairs = {(col_nums[k1][r], col_nums[k2][r]) for r in valid_rows}
                    if len(distinct_pairs) < 2:
                        continue
                    if all(col_nums[k1][r] in (0.0, 1.0) or col_nums[k2][r] in (0.0, 1.0) for r in valid_rows):
                        continue
                    for op_sym, fn in (
                        ("×", lambda a, b: a * b),
                        ("+", lambda a, b: a + b),
                    ):
                        if all(abs(col_nums[tc_key][r] - fn(col_nums[k1][r], col_nums[k2][r])) < 1e-4 for r in valid_rows):
                            insights.append(
                                f"「{target_c['name']}」列（{tc_key}{first_data}:{tc_key}{last_data}）は"
                                f"「{c1['name']} {op_sym} {c2['name']}」で計算できますが、数式ではなく値で入っています"
                            )
                            found_calc = True
                            break
                    if found_calc:
                        break

    # --- 型2: 備考と数の食い違い ---
    note_cols = [c for c in col_infos if _NOTE_HEAD_RE.search(c["name"])]
    amt_cols = [c for c in col_infos if c["number"] and _AMT_HEAD_RE.search(c["name"])]
    prog_cols = [c for c in col_infos if c["number"] and _PROG_HEAD_RE.search(c["name"])]
    qty_col = next((c for c in num_cols if re.search(r"数量|個数|件数|qty", c["name"], re.I)), None)
    price_col = next((c for c in num_cols if re.search(r"単価|price", c["name"], re.I)), None)

    for nc in note_cols:
        for r in range(first_data, last_data + 1):
            note_txt = str(get_val(r, nc["ci"]) or "").strip()
            if not note_txt:
                continue
            # パターンA: 値引・割引あり なのに 数量×単価 と金額が完全一致
            if _DISCOUNT_NOTE_RE.search(note_txt) and qty_col and price_col and amt_cols:
                qv = _to_float(get_val(r, qty_col["ci"]))
                pv = _to_float(get_val(r, price_col["ci"]))
                av = _to_float(get_val(r, amt_cols[0]["ci"]))
                if qv is not None and pv is not None and av is not None and qv > 0 and pv > 0:
                    if abs(av - qv * pv) < 1e-4:
                        ac = amt_cols[0]
                        insights.append(
                            f"{ac['col']}{r}（{ac['name']}）は備考（{nc['col']}{r}「{note_txt}」）に反して、"
                            f"{qty_col['name']}×{price_col['name']}そのままの金額になっています"
                        )
                        break
            # パターンB: 無料・キャンセル なのに 金額 > 0
            if _ZERO_NOTE_RE.search(note_txt) and amt_cols:
                av = _to_float(get_val(r, amt_cols[0]["ci"]))
                if av is not None and av > 0:
                    ac = amt_cols[0]
                    insights.append(
                        f"{ac['col']}{r}（{ac['name']}）は備考（{nc['col']}{r}「{note_txt}」）と異なり、金額（{get_val(r, ac['ci'])}）が入っています"
                    )
                    break
            # パターンC: 完了/未着手 と進捗率の矛盾
            if prog_cols:
                pc = prog_cols[0]
                pv = _to_float(get_val(r, pc["ci"]))
                if pv is not None:
                    if _DONE_NOTE_RE.search(note_txt) and pv < 1.0 - 1e-6:
                        insights.append(
                            f"{pc['col']}{r}（{pc['name']}）は {get_val(r, pc['ci'])} ですが、備考（{nc['col']}{r}「{note_txt}」）は「{note_txt}」になっています"
                        )
                        break
                    if _NOT_DONE_NOTE_RE.search(note_txt) and pv >= 1.0 - 1e-6:
                        insights.append(
                            f"{pc['col']}{r}（{pc['name']}）は 100% ですが、備考（{nc['col']}{r}「{note_txt}」）は「{note_txt}」になっています"
                        )
                        break

    # --- 型7: 集計の元の偏りや欠け（月の欠け・空行・重複行） ---
    month_hits = []
    half_labels = set()
    for c in col_infos:
        m = _MONTH_RE.search(c["name"])
        if m:
            if m.group(1):
                half_labels.add(m.group(1))
            month_hits.append(int(m.group(2)))
    if len(month_hits) >= 2 and len(month_hits) < 12:
        if half_labels or len(month_hits) <= 6:
            m_str = "・".join(f"{m}月" for m in month_hits)
            insights.append(
                f"月別データは {m_str}（計{len(month_hits)}か月分）のみで、他の月が欠けています"
            )

    if not (op_shelves & {"blank.rows.delete", "dedupe", "seiri"}):
        blank_rows = []
        dup_rows = []
        seen_rows = set()
        for r in range(first_data, last_data + 1):
            row_vals = [str(get_val(r, c["ci"]) or "").strip() for c in col_infos]
            if all(v == "" for v in row_vals):
                blank_rows.append(r)
            else:
                key = tuple(row_vals)
                if key in seen_rows:
                    dup_rows.append(r)
                else:
                    seen_rows.add(key)
        if blank_rows:
            r_str = "・".join(str(r) for r in blank_rows[:3])
            insights.append(f"表内に空行（{r_str}行目）があります")
        if dup_rows:
            r_str = "・".join(str(r) for r in dup_rows[:3])
            insights.append(f"全列が一致する重複行（{r_str}行目）があります")

    # --- 型6: 頼まれていない列の崩れ（メール・電話・日付・空白/全角） ---
    skip_clean_check = "seiri" in op_shelves
    for c in col_infos:
        if len(insights) >= max_items:
            break
        if c["col"] in op_cols or c["name"] in op_cols:
            continue
        cname = c["name"]
        # メールアドレス
        if _EMAIL_HEAD_RE.search(cname) and "phone.fix" not in op_shelves:
            bad = []
            for r in range(first_data, last_data + 1):
                s = str(get_val(r, c["ci"]) or "").strip()
                if s and not _EMAIL_VALID_RE.match(s):
                    bad.append(f"{c['col']}{r}「{s}」")
            if bad:
                insights.append(f"「{cname}」列に形式が不完全なメールアドレスがあります（{bad[0]}）")
                continue
        # 電話番号
        if _PHONE_HEAD_RE.search(cname) and "phone.fix" not in op_shelves:
            bad = []
            for r in range(first_data, last_data + 1):
                s = str(get_val(r, c["ci"]) or "").strip()
                if not s:
                    continue
                digits = re.sub(r"\D", "", s.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
                if " " in s or "　" in s or _ZEN_NUM_RE.search(s) or len(digits) not in (10, 11) or "-" not in s:
                    bad.append(f"{c['col']}{r}「{s}」")
            if bad:
                insights.append(f"「{cname}」列に書式が不揃いな番号があります（{bad[0]}）")
                continue
        # 日付の和暦・形式揺れ
        if _DATE_HEAD_RE.search(cname) and "date.fix" not in op_shelves and not skip_clean_check:
            styles = set()
            wareki_ex = None
            for r in range(first_data, last_data + 1):
                s = str(get_val(r, c["ci"]) or "").strip()
                if not s:
                    continue
                if _WAREKI_RE.match(s):
                    styles.add("wareki")
                    wareki_ex = wareki_ex or f"{c['col']}{r}「{s}」"
                elif "年" in s and "月" in s:
                    styles.add("kanji")
                elif "/" in s:
                    styles.add("slash")
                elif "-" in s:
                    styles.add("hyphen")
            if wareki_ex or len(styles) >= 2:
                ex = wareki_ex or f"{c['col']}{first_data}"
                insights.append(f"「{cname}」列に日付表記の揺れがあります（{ex} 等）")
                continue

    # 前後空白・全角数字（seiri 直後でなく、まだ拾えていない場合のみ）
    if len(insights) < max_items and not skip_clean_check:
        dirty_cells = []
        for r in range(first_data, last_data + 1):
            for c in col_infos:
                if c["col"] in op_cols or c["name"] in op_cols:
                    continue
                raw = get_val(r, c["ci"])
                if not isinstance(raw, str) or not raw:
                    continue
                if raw != raw.strip(" \t　") or _ZEN_NUM_RE.search(raw):
                    dirty_cells.append(f"{c['col']}{r}")
                    if len(dirty_cells) >= 2:
                        break
            if len(dirty_cells) >= 2:
                break
        if dirty_cells:
            insights.append(f"{'・'.join(dirty_cells)} 等に前後の空白や全角数字が含まれています")

    # 重複除去して max_items まで返す
    uniq = []
    for item in insights:
        if item not in uniq:
            uniq.append(item)
        if len(uniq) >= max_items:
            break
    return uniq


def analyze_from_look_res(res, max_items=3):
    """ws_look の戻り値 dict（Direct / Engine 共通）から気づきを生成する。"""
    if not isinstance(res, dict) or not res.get("ok"):
        return []
    t = res.get("target") or {}
    if t.get("kind") != "sheet":
        return []
    tb = res.get("table")
    vals = res.get("values")
    if not tb or not vals:
        return []
    # range が A1 始まりでない場合は行・列オフセットを考慮する
    rng = str(res.get("range") or "").strip()
    start_r, start_c = 1, 1
    m = re.match(r"^(?:[^!]+!)?([A-Za-z]+)(\d+):", rng)
    if m:
        start_c = _col_num(m.group(1))
        start_r = int(m.group(2))
    if start_r == 1 and start_c == 1:
        v_grid = vals
        f_grid = res.get("formulas") or []
    else:
        # オフセット付きグリッドを 1-based にパディング
        v_grid = [[] for _ in range(start_r - 1)]
        for row in vals:
            v_grid.append([""] * (start_c - 1) + list(row))
        f_grid = [[] for _ in range(start_r - 1)]
        for row in (res.get("formulas") or []):
            f_grid.append([""] * (start_c - 1) + list(row))
    return analyze_table_insights(tb, v_grid, f_grid, side=res.get("side") or [], max_items=max_items)


def analyze_from_snapshot(snap, sheet_name, tb, ops=None, max_items=3):
    """DirectRunner の Snapshot から気づきを生成する。"""
    if not snap or not tb:
        return []
    try:
        ent = snap.sheet(sheet_name)
    except Exception:
        return []
    cells = ent.get("cells") or {}
    if not cells:
        return []
    dr = _parse_data_range(tb)
    max_r = max([r for r, _ in cells.keys()] + [tb.get("total_row") or 0, (dr[1] if dr else 0)], default=0)
    max_c = max([c for _, c in cells.keys()], default=0)
    if max_r <= 0 or max_c <= 0:
        return []
    v_grid = []
    f_grid = []
    for r in range(1, max_r + 1):
        v_row = []
        f_row = []
        for c in range(1, max_c + 1):
            cell = cells.get((r, c)) or {}
            # テキスト/数値の取得
            ev = cell.get("effectiveValue") or {}
            if "numberValue" in ev and not (
                (((cell.get("effectiveFormat") or {}).get("numberFormat") or {}).get("type") or "").upper()
                in ("DATE", "DATE_TIME", "TIME")
            ):
                v_row.append(ev["numberValue"])
            else:
                fv = cell.get("formattedValue")
                if fv is not None:
                    v_row.append(str(fv))
                elif "stringValue" in ev:
                    v_row.append(str(ev["stringValue"]))
                elif "numberValue" in ev:
                    v_row.append(ev["numberValue"])
                else:
                    v_row.append("")
            uv = (cell.get("userEnteredValue") or {}).get("formulaValue") or ""
            f_row.append(str(uv))
        v_grid.append(v_row)
        f_grid.append(f_row)
    side = []
    if ent.get("basicFilter"):
        side.append("フィルタ")
    return analyze_table_insights(tb, v_grid, f_grid, side=side, ops=ops, max_items=max_items)
