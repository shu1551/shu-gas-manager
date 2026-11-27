# -*- coding: utf-8 -*-
"""ws_look / ws_do 用の軽量「気づき」分析モジュール（型 1・2・4・6・7）。

対象の表（メモリ上の値・数式・見出し・脇情報）だけを見て、
当てずっぽうを排除した確かな気づきだけを最大 3 行返す。
"""

import re
import hashlib as _hashlib
# 健診の結果の版＝このファイルの中身から作る。直したら覚えていた健診を作り直す（古い誤った気づきを出し続けない）
try:
    DIAG_VERSION = _hashlib.sha1(open(__file__, 'rb').read()).hexdigest()[:12]
except Exception:
    DIAG_VERSION = 'unknown'

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

    # --- 関連性フィルタ用タグ ---
    # ws_look (ops 空) なら全型を出す。ws_do ならその手に関わる型だけを残す。
    if op_shelves:
        allowed_tags = set()
        if op_shelves & {"filter", "filter.where", "sort"}:
            allowed_tags.add("type4")
        if op_shelves & {"summary", "top.n", "chart.new", "pivot.new"}:
            allowed_tags.update({"type2", "type6", "type7"})
        if op_shelves & {"calc.col", "total"}:
            allowed_tags.add("type2")
        if op_shelves & {"tidy"}:
            allowed_tags.update({"type6", "type7"})
        if op_shelves & {"phone.fix", "date.fix", "text.case", "seiri", "blank.rows.delete", "dedupe"}:
            allowed_tags.update({"type6", "type7"})
    else:
        allowed_tags = {"type1", "type2", "type4", "type6", "type7"}

    tagged_insights = []

    def add_ins(tag, msg):
        if tag in allowed_tags:
            tagged_insights.append(msg)

    insights = tagged_insights

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
            add_ins(
                "type4",
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
                        match_rows = [r for r in valid_rows if abs(col_nums[tc_key][r] - fn(col_nums[k1][r], col_nums[k2][r])) < 1e-4]
                        mismatch_rows = [r for r in valid_rows if abs(col_nums[tc_key][r] - fn(col_nums[k1][r], col_nums[k2][r])) >= 1e-4]
                        if len(match_rows) == len(valid_rows):
                            add_ins(
                                "type1",
                                f"「{target_c['name']}」列（{tc_key}{first_data}:{tc_key}{last_data}）は"
                                f"「{c1['name']} {op_sym} {c2['name']}」で計算できますが、数式ではなく値で入っています"
                            )
                            found_calc = True
                            break
                        if len(match_rows) >= 2 and len(match_rows) / len(valid_rows) >= 0.65 and mismatch_rows:
                            mr = mismatch_rows[0]
                            exp_v = fn(col_nums[k1][mr], col_nums[k2][mr])
                            exp_s = f"{int(exp_v):,}" if abs(exp_v - round(exp_v)) < 1e-6 else f"{exp_v:,.2f}"
                            act_s = get_val(mr, target_c["ci"])
                            extra_m = f"（ほか {len(mismatch_rows) - 1} 件）" if len(mismatch_rows) > 1 else ""
                            add_ins(
                                "type1",
                                f"{tc_key}{mr}（{target_c['name']}={act_s}）が「{c1['name']} {op_sym} {c2['name']}」（{exp_s}）と食い違っています{extra_m}（数式ではなく値で入力）"
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
        discount_hits = []
        zero_hits = []
        prog_hits = []
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
                        discount_hits.append((r, ac, note_txt, get_val(r, ac["ci"])))
            # パターンB: 無料・キャンセル なのに 金額 > 0
            if _ZERO_NOTE_RE.search(note_txt) and amt_cols:
                av = _to_float(get_val(r, amt_cols[0]["ci"]))
                if av is not None and av > 0:
                    ac = amt_cols[0]
                    zero_hits.append((r, ac, note_txt, get_val(r, ac["ci"])))
            # パターンC: 完了/未着手 と進捗率の矛盾
            if prog_cols:
                pc = prog_cols[0]
                pv = _to_float(get_val(r, pc["ci"]))
                if pv is not None:
                    if _DONE_NOTE_RE.search(note_txt) and pv < 1.0 - 1e-6:
                        prog_hits.append(f"{pc['col']}{r}（{pc['name']}={get_val(r, pc['ci'])}）と{nc['col']}{r}（{nc['name']}「{note_txt}」）に食い違いがあります")
                    elif _NOT_DONE_NOTE_RE.search(note_txt) and pv >= 1.0 - 1e-6:
                        prog_hits.append(f"{pc['col']}{r}（{pc['name']}=100%）と{nc['col']}{r}（{nc['name']}「{note_txt}」）に食い違いがあります")
        if discount_hits:
            r, ac, note_txt, amt_disp = discount_hits[0]
            extra_n = f"（ほか {len(discount_hits) - 1} 件）" if len(discount_hits) > 1 else ""
            add_ins(
                "type2",
                f"{nc['col']}{r}（{nc['name']}）に「{note_txt}」とありますが、{ac['col']}{r}（{ac['name']}={amt_disp}）は値引き前の金額のままです{extra_n}"
            )
        if zero_hits:
            r, ac, note_txt, amt_disp = zero_hits[0]
            extra_n = f"（ほか {len(zero_hits) - 1} 件）" if len(zero_hits) > 1 else ""
            add_ins(
                "type2",
                f"{nc['col']}{r}（{nc['name']}）が「{note_txt}」ですが、{ac['col']}{r}（{ac['name']}={amt_disp}）に金額が残っています{extra_n}"
            )
        if prog_hits:
            add_ins("type2", prog_hits[0])

    # --- 型7: 集計の元の偏りや欠け（月の欠け・空行・重複行） ---
    month_hits = []
    half_labels = set()
    for c in col_infos:
        # 2 段見出しは「上期（4〜6月）・4月」の形＝親の「6月」でなく、最後に出る月（子の見出し）を取る
        ms = list(_MONTH_RE.finditer(c["name"]))
        if ms:
            m = ms[-1]
            half = next((x.group(1) for x in ms if x.group(1)), None) or next((h for h in ("上期", "下期") if h in c["name"]), None)
            if half:
                half_labels.add(half)
            month_hits.append(int(m.group(2)))
    if len(month_hits) >= 2 and len(set(month_hits)) < 12:
        uniq_m = sorted(set(month_hits))
        if half_labels or len(uniq_m) <= 6:
            m_str = "・".join(f"{m}月" for m in uniq_m)
            add_ins(
                "type7",
                f"月別データは {m_str}（計{len(uniq_m)}か月分）のみで、他の月が欠けています"
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
            add_ins("type7", f"表内に空行（{r_str}行目）があります")
        if dup_rows:
            r_str = "・".join(str(r) for r in dup_rows[:3])
            add_ins("type7", f"全列が一致する重複行（{r_str}行目）があります")

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
                add_ins("type6", f"「{cname}」列に形式が不完全なメールアドレスがあります（{bad[0]}）")
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
                add_ins("type6", f"「{cname}」列に書式が不揃いな番号があります（{bad[0]}）")
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
                add_ins("type6", f"「{cname}」列に日付表記の揺れがあります（{ex} 等）")
                continue

    # 前後空白・全角数字（seiri 直後でなく、まだ拾えていない場合のみ。実際にある種類だけ正確に言う）
    if len(insights) < max_items and not skip_clean_check:
        trim_cells = []
        zen_cells = []
        for r in range(first_data, last_data + 1):
            for c in col_infos:
                if c["col"] in op_cols or c["name"] in op_cols:
                    continue
                raw = get_val(r, c["ci"])
                if not isinstance(raw, str) or not raw:
                    continue
                if raw != raw.strip(" \t　") and len(trim_cells) < 2:
                    trim_cells.append(f"{c['col']}{r}")
                if _ZEN_NUM_RE.search(raw) and len(zen_cells) < 2:
                    zen_cells.append(f"{c['col']}{r}")
            if len(trim_cells) >= 2 and len(zen_cells) >= 2:
                break
        if trim_cells:
            add_ins("type6", f"{'・'.join(trim_cells)} 等に前後の空白が含まれています")
        if zen_cells and len(insights) < max_items:
            add_ins("type6", f"{'・'.join(zen_cells)} 等に全角数字が含まれています")

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


# ====================================================================
# 【1】ブック全体健診（全シート総当たり・8つの型）
# ====================================================================
_ERR_TOKENS = ("#REF!", "#NAME?", "#VALUE!", "#N/A", "#DIV/0!", "#NUM!", "#ERROR!")
_CROSS_REF_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9_\u3040-\u30ff\u4e00-\u9faf]+))![$]?[A-Z]{1,3}(?:[$]?\d+|:[A-Z]{1,3})")
_KEY_HEAD_RE = re.compile(r"(?:コード|ID|番号|No|顧客|部門|部署|担当|商品|店舗|地域)", re.I)
_UNIQUE_KEY_HEAD_RE = re.compile(r"(?:コード|ID|社員番号|会員番号|顧客番号|管理番号|注文番号|メール|mail)", re.I)
_PCT_OFF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]\s*(?:引|びき|オフ|OFF)", re.I)


def _nfkc_trim(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def diagnose_workbook(sheets_payload):
    """ブック全体の全シートデータから8つの型で確かな健診項目を重要度順に返す。

    戻り値: [{"sheet": str, "tag": str, "priority": int, "text": str}, ...]
    """
    if not sheets_payload:
        return []
    sheet_names = {str(s.get("sheet") or "") for s in sheets_payload}
    findings = []

    def add_f(sheet, tag, priority, text):
        findings.append({"sheet": sheet, "tag": tag, "priority": priority, "text": text})

    for sp in sheets_payload:
        sh = str(sp.get("sheet") or "")
        tb = sp.get("table")
        vals = sp.get("values") or []
        forms = sp.get("formulas") or []
        side = sp.get("side") or []

        # --- 型8: シートをまたぐ参照と、壊れた参照・セルエラー ---
        cross_refs = set()
        broken_refs = []
        cell_errs = []
        for r_idx, row in enumerate(vals, 1):
            f_row = forms[r_idx - 1] if r_idx - 1 < len(forms) else []
            for c_idx, v in enumerate(row, 1):
                sv = str(v or "")
                sf = str(f_row[c_idx - 1] if c_idx - 1 < len(f_row) else "")
                a1 = f"{_col_letter(c_idx)}{r_idx}"
                if any(et in sv for et in _ERR_TOKENS):
                    cell_errs.append(f"{sh}!{a1}({sv})")
                if sf.startswith("="):
                    for m in _CROSS_REF_RE.finditer(sf):
                        ref_sh = m.group(1) or m.group(2)
                        if ref_sh and ref_sh != sh:
                            cross_refs.add(ref_sh)
                            if ref_sh not in sheet_names:
                                broken_refs.append(f"{sh}!{a1}→存在しないシート「{ref_sh}」")
        if cell_errs:
            add_f(sh, "cross_sheet_ref", 1, f"[{sh}] 数式エラーがあります: {'・'.join(cell_errs[:3])}")
        if broken_refs:
            add_f(sh, "cross_sheet_ref", 1, f"[{sh}] シート参照が壊れています: {broken_refs[0]}")
        elif cross_refs:
            add_f(sh, "cross_sheet_ref", 4, f"[{sh}] 他シート（{'・'.join(sorted(cross_refs)[:3])}）への参照があります（元シート削除・改名時は注意）")

        if not tb or not vals:
            continue
        dr = _parse_data_range(tb)
        if not dr:
            continue
        first_data, last_data = dr
        if last_data < first_data:
            continue

        cols = tb.get("columns") or []
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
            continue

        def gval(r1, c1):
            if 1 <= r1 <= len(vals) and 1 <= c1 <= len(vals[r1 - 1]):
                return vals[r1 - 1][c1 - 1]
            return ""

        def gform(r1, c1):
            if 1 <= r1 <= len(forms) and 1 <= c1 <= len(forms[r1 - 1]):
                return str(forms[r1 - 1][c1 - 1] or "")
            return ""

        # --- 型1〜4, 6, 7 の既存分析（最大10件で全取得） ---
        base_ins = analyze_table_insights(tb, vals, forms, side=side, ops=None, max_items=10)
        for txt in base_ins:
            pri = 2
            tag = "general"
            if "食い違っています" in txt:
                pri, tag = 1, "calc_mismatch"
            elif "数式ではなく値" in txt:
                pri, tag = 2, "calc_value"
            elif "キャンセル" in txt or "値引き前の金額" in txt or "食い違いがあります" in txt:
                pri, tag = 1, "note_contradiction"
            elif "SUBTOTAL" in txt:
                pri, tag = 2, "sum_subtotal"
            elif "前後の空白" in txt or "全角数字" in txt:
                pri, tag = 2, "key_whitespace_split"
            elif "メールアドレス" in txt or "番号" in txt or "日付表記" in txt:
                pri, tag = 3, "format_broken"
            elif "欠けています" in txt or "空行" in txt or "重複行" in txt:
                pri, tag = 3, "period_structure"
            # 値引き率（例: 10%引き）があれば試算額を追記
            if "値引き前の金額のまま" in txt:
                m_pct = _PCT_OFF_RE.search(txt)
                if m_pct:
                    pct = float(m_pct.group(1))
                    m_amt = re.search(r"=([0-9,]+(?:\.\d+)?)", txt)
                    if m_amt:
                        raw_a = float(m_amt.group(1).replace(",", ""))
                        disc_a = raw_a * (1.0 - pct / 100.0)
                        txt += f"（{m_pct.group(1)}%引き適用時は {_fmt_num(disc_a)}）"
            add_f(sh, tag, pri, f"[{sh}] {txt}")

        # --- 型2補足: 状態列の行が合計に入っている場合の除外時金額 ---
        total_row = tb.get("total_row")
        amt_cols = [c for c in col_infos if c["number"] and _AMT_HEAD_RE.search(c["name"])]
        note_cols = [c for c in col_infos if _NOTE_HEAD_RE.search(c["name"])]
        if total_row and amt_cols and note_cols:
            ac = amt_cols[0]
            tot_v = _to_float(gval(int(total_row), ac["ci"]))
            if tot_v is not None:
                cancel_sum = 0.0
                cancel_rows = []
                for nc in note_cols:
                    for r in range(first_data, last_data + 1):
                        nt = str(gval(r, nc["ci"]) or "").strip()
                        if _ZERO_NOTE_RE.search(nt) or "保留" in nt:
                            av = _to_float(gval(r, ac["ci"]))
                            if av is not None and av > 0:
                                cancel_sum += av
                                cancel_rows.append(r)
                if cancel_rows and cancel_sum > 0:
                    add_f(
                        sh,
                        "status_in_total",
                        1,
                        f"[{sh}] {ac['col']}{total_row}（{ac['name']}合計 {_fmt_num(tot_v)}）にキャンセル等の行（{','.join(str(x) for x in cancel_rows)}行目: 計{_fmt_num(cancel_sum)}）が含まれています（除外時 {_fmt_num(tot_v - cancel_sum)}）",
                    )

        # --- 型4補足: 集計キーになりそうな列の表記ゆれ・割れ ---
        for c in col_infos:
            if c["number"] or not _KEY_HEAD_RE.search(c["name"]):
                continue
            raw_set = set()
            norm_map = {}
            for r in range(first_data, last_data + 1):
                sv = str(gval(r, c["ci"]) or "")
                if not sv.strip():
                    continue
                raw_set.add(sv)
                nk = _nfkc_trim(sv)
                norm_map.setdefault(nk, set()).add(sv)
            if len(raw_set) > len(norm_map):
                ex = next((vs for vs in norm_map.values() if len(vs) > 1), set())
                ex_s = " / ".join(f"「{x}」" for x in sorted(ex)[:2])
                add_f(sh, "key_whitespace_split", 2, f"[{sh}] 「{c['name']}」列（{c['col']}列）に表記ゆれ・空白違いがあり、集計時に別グループに割れます（{ex_s}）")

        # --- 型5: ユニークキー重複で他列が違う行 ---
        for c in col_infos:
            if not _UNIQUE_KEY_HEAD_RE.search(c["name"]):
                continue
            seen_u = {}
            for r in range(first_data, last_data + 1):
                kv = _nfkc_trim(str(gval(r, c["ci"]) or ""))
                if not kv:
                    continue
                others = tuple(_nfkc_trim(str(gval(r, oc["ci"]) or "")) for oc in col_infos if oc["ci"] != c["ci"])
                if kv in seen_u:
                    fr, f_others = seen_u[kv]
                    if others != f_others:
                        add_f(sh, "key_dup_diff", 2, f"[{sh}] {c['col']}{fr} と {c['col']}{r} で「{c['name']}」（{kv}）が重複していますが、他の列の値が異なります（削除時は確認が必要）")
                        break
                else:
                    seen_u[kv] = (r, others)

        # --- 型7補足: 2段見出し ---
        if int(tb.get("header_rows") or 1) > 1:
            hr = int(tb.get("header_row") or 1)
            add_f(sh, "period_structure", 4, f"[{sh}] 2段見出し（{hr}-{hr + int(tb['header_rows']) - 1}行目）の表です")

        # --- 型7補足: 月の列・データ列が丸ごと空欄 ---
        if last_data - first_data >= 1:
            for c in col_infos:
                if _MONTH_RE.search(c["name"]) or c["number"]:
                    all_empty = all(str(gval(r, c["ci"]) or "").strip() == "" for r in range(first_data, last_data + 1))
                    if all_empty:
                        add_f(sh, "blank_col", 2, f"[{sh}] 「{c['name']}」列（{c['col']}列）がすべて空欄です")

        # --- 型8補足: SUMIF/COUNTIF 等の他シート照合キーずれで 0 になっている ---
        for r in range(first_data, last_data + 1):
            for c in col_infos:
                sf = gform(r, c["ci"])
                if not sf.startswith("=") or not re.search(r"(?:SUM|COUNT|AVERAGE)IFS?\(", sf, re.I):
                    continue
                m_ref = _CROSS_REF_RE.search(sf)
                if not m_ref:
                    continue
                ref_sh = m_ref.group(1) or m_ref.group(2)
                val_num = _to_float(gval(r, c["ci"]))
                if val_num is None or abs(val_num) > 1e-6:
                    continue
                # 同じ行の先頭文字列（キー候補）が参照先シートの文字列に完全一致しないが部分一致するか
                ref_sp = next((x for x in sheets_payload if str(x.get("sheet") or "") == ref_sh), None)
                if not ref_sp or not ref_sp.get("values"):
                    continue
                ref_strings = {
                    str(rv).strip()
                    for rrow in ref_sp["values"]
                    for rv in rrow
                    if isinstance(rv, str) and rv.strip()
                }
                for kc in col_infos:
                    if kc["number"]:
                        continue
                    k_val = str(gval(r, kc["ci"]) or "").strip()
                    if not k_val or k_val in ref_strings:
                        continue
                    partial = [rs for rs in ref_strings if k_val in rs or rs in k_val]
                    if partial:
                        # 参照先シートから部分一致名（例: 開発部）の合計額を試算して添える
                        est_hint = ""
                        try:
                            ref_tb = ref_sp.get("table")
                            ref_dr = _parse_data_range(ref_tb) if ref_tb else None
                            if ref_dr:
                                r_k_cols = [
                                    _col_num(rc.get("col")) for rc in (ref_tb.get("columns") or [])
                                    if not rc.get("number")
                                ]
                                r_v_cols = [
                                    _col_num(rc.get("col")) for rc in (ref_tb.get("columns") or [])
                                    if rc.get("number") and _AMT_HEAD_RE.search(str(rc.get("name") or ""))
                                ]
                                if r_v_cols:
                                    vc = r_v_cols[0]
                                    p_sum = 0.0
                                    p_cnt = 0
                                    for rr in range(ref_dr[0], ref_dr[1] + 1):
                                        rrow = ref_sp["values"][rr - 1] if rr - 1 < len(ref_sp["values"]) else []
                                        if any(str(rrow[kc_i - 1] if kc_i - 1 < len(rrow) else "").strip() == partial[0] for kc_i in r_k_cols):
                                            av = _to_float(rrow[vc - 1] if vc - 1 < len(rrow) else "")
                                            if av is not None:
                                                p_sum += av
                                                p_cnt += 1
                                    if p_cnt > 0:
                                        est_hint = f"（一致させると {_fmt_num(p_sum)}）"
                        except Exception:
                            est_hint = ""
                        add_f(
                            sh,
                            "cross_sheet_mismatch",
                            1,
                            f"[{sh}] {c['col']}{r}（{c['name']}）が 0 になっています: 「{k_val}」（{kc['col']}{r}）が「{ref_sh}」側の「{partial[0]}」等と表記がずれています{est_hint}",
                        )
                        break

    # --- ブック横断チェック: 申請者/担当者等がマスタシートにいない・期間ずれ ---
    master_sets = {}
    sheet_months_info = {}
    for sp in sheets_payload:
        sh = str(sp.get("sheet") or "")
        tb = sp.get("table")
        vals = sp.get("values") or []
        if not tb or not vals:
            continue
        dr = _parse_data_range(tb)
        if not dr:
            continue
        r1, r2 = dr
        cols = tb.get("columns") or []
        if re.search(r"社員|名簿|マスタ|顧客|メンバー", sh):
            for c in cols:
                cn = str(c.get("name") or "")
                if not re.search(r"番号|ID|コード", cn, re.I) and re.search(r"氏名|名前|社員名|顧客名|名$", cn):
                    ci = _col_num(c.get("col"))
                    master_sets[sh] = {
                        _nfkc_trim(str(vals[r - 1][ci - 1]))
                        for r in range(r1, r2 + 1)
                        if r - 1 < len(vals) and ci - 1 < len(vals[r - 1]) and str(vals[r - 1][ci - 1] or "").strip()
                    }
                    break
        # 期間抽出（月見出し、またはマスタ以外の明細シートの日付列の年月）
        # 2 段見出し「上期（4〜6月）・4月」は最後に出る月（子の見出し）を取る
        m_cols = [int(list(_MONTH_RE.finditer(str(c.get("name") or "")))[-1].group(2)) for c in cols if _MONTH_RE.search(str(c.get("name") or ""))]
        if m_cols:
            sheet_months_info[sh] = ("header", sorted(set(m_cols)))
        elif not re.search(r"社員|名簿|マスタ|顧客|メンバー", sh):
            d_months = set()
            for c in cols:
                if _DATE_HEAD_RE.search(str(c.get("name") or "")):
                    ci = _col_num(c.get("col"))
                    for r in range(r1, r2 + 1):
                        if r - 1 < len(vals) and ci - 1 < len(vals[r - 1]):
                            sv = str(vals[r - 1][ci - 1] or "")
                            mm = re.match(r"^\d{4}[/-](\d{1,2})[/-]\d{1,2}", sv)
                            if mm:
                                d_months.add(int(mm.group(1)))
            if d_months:
                sheet_months_info[sh] = ("date", sorted(d_months))

    if master_sets:
        m_sh, m_names = next(iter(master_sets.items()))
        for sp in sheets_payload:
            sh = str(sp.get("sheet") or "")
            if sh == m_sh:
                continue
            tb = sp.get("table")
            vals = sp.get("values") or []
            if not tb or not vals:
                continue
            dr = _parse_data_range(tb)
            if not dr:
                continue
            r1, r2 = dr
            for c in (tb.get("columns") or []):
                cn = str(c.get("name") or "")
                if re.search(r"申請者|担当者|社員|氏名|名前", cn):
                    ci = _col_num(c.get("col"))
                    missing_names = []
                    for r in range(r1, r2 + 1):
                        if r - 1 < len(vals) and ci - 1 < len(vals[r - 1]):
                            raw_n = str(vals[r - 1][ci - 1] or "").strip()
                            if raw_n and _nfkc_trim(raw_n) not in m_names:
                                missing_names.append(f"{c.get('col')}{r}「{raw_n}」")
                    if missing_names:
                        add_f(sh, "cross_sheet_mismatch", 1, f"[{sh}] 「{cn}」に「{m_sh}」シートへ登録のない人がいます（{missing_names[0]}）")

    if len(sheet_months_info) >= 2:
        items_m = list(sheet_months_info.items())
        for i in range(len(items_m)):
            for j in range(i + 1, len(items_m)):
                s1, (k1, m1) = items_m[i]
                s2, (k2, m2) = items_m[j]
                if set(m1) != set(m2) and (set(m1) - set(m2) or set(m2) - set(m1)):
                    add_f(
                        s1,
                        "period_structure",
                        2,
                        f"[{s1}/{s2}] シート間で対象月の範囲がずれています（{s1}: {','.join(str(x)+'月' for x in m1)} ／ {s2}: {','.join(str(x)+'月' for x in m2)}）",
                    )
                    break

    findings.sort(key=lambda x: x["priority"])
    return findings


# ====================================================================
# 【2】撃った後の検算（合計・行数・集計表の和）
# ====================================================================
def verify_after_do(table, values_grid, formulas_grid=None, ops=None, source_info=None, before_map=None, after_map=None):
    """ws_do 後に合計行と明細和、集計表と元表の和、日付ずれを Python で検算する。

    戻り値: {"ok": bool, "checks": [str, ...], "mismatch": [str, ...]}
    """
    checks = []
    mismatch = []
    if not table or not values_grid:
        return {"ok": True, "checks": checks, "mismatch": mismatch}

    # date.fix / seiri 後に既存の日付が 1 日ずれていないか検算
    op_shelves = {str(o.get("shelf") or "") for o in (ops or []) if isinstance(o, dict)}
    if before_map and after_map and (op_shelves & {"date.fix", "seiri"}):
        import datetime as _dt
        for (r, c), bv in before_map.items():
            av = after_map.get((r, c), "")
            mb = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", str(bv or "").strip())
            ma = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", str(av or "").strip())
            if mb and ma:
                try:
                    db = _dt.date(int(mb.group(1)), int(mb.group(2)), int(mb.group(3)))
                    da = _dt.date(int(ma.group(1)), int(ma.group(2)), int(ma.group(3)))
                    if db != da:
                        mismatch.append(f"{_col_letter(c)}{r} の日付が {bv} → {av} にずれています")
                        break
                except ValueError:
                    pass

    dr = _parse_data_range(table)
    if not dr:
        return {"ok": True, "checks": checks, "mismatch": mismatch}
    first_data, last_data = dr
    cols = table.get("columns") or []
    total_row = table.get("total_row")

    def gval(r1, c1):
        if 1 <= r1 <= len(values_grid) and 1 <= c1 <= len(values_grid[r1 - 1]):
            return values_grid[r1 - 1][c1 - 1]
        return ""

    def gform(r1, c1):
        if formulas_grid and 1 <= r1 <= len(formulas_grid) and 1 <= c1 <= len(formulas_grid[r1 - 1]):
            return str(formulas_grid[r1 - 1][c1 - 1] or "")
        return ""

    if total_row and last_data >= first_data:
        for c in cols:
            if not c.get("number"):
                continue
            ci = _col_num(c.get("col"))
            tot_v = _to_float(gval(int(total_row), ci))
            tot_f = gform(int(total_row), ci)
            if tot_v is None or not tot_f.upper().startswith("=SUM("):
                continue
            # 明細和を Python で計算
            row_sum = 0.0
            has_any = False
            for r in range(first_data, last_data + 1):
                rv = _to_float(gval(r, ci))
                if rv is not None:
                    row_sum += rv
                    has_any = True
            if has_any:
                col_l = c.get("col")
                if abs(tot_v - row_sum) < 1e-4:
                    checks.append(f"{col_l}{total_row} = {_fmt_num(tot_v)}（明細 {col_l}{first_data}:{col_l}{last_data} の和と一致）")
                else:
                    mismatch.append(
                        f"{col_l}{total_row}（表示 {_fmt_num(tot_v)}）と明細 {col_l}{first_data}:{col_l}{last_data} の和（{_fmt_num(row_sum)}）が一致しません"
                    )

    return {"ok": not mismatch, "checks": checks[:3], "mismatch": mismatch[:3]}


# ====================================================================
# 【3】変わったセルの前→後差分
# ====================================================================
def diff_cell_values(before_map, after_map, max_items=4):
    """{(r, c): val} 同士を比較し、変化したセルを 'F8: 100,000 → 120,000' 形式で返す。"""
    if not before_map or not after_map:
        return []
    diffs = []
    all_keys = sorted(set(before_map.keys()) | set(after_map.keys()))
    for r, c in all_keys:
        b = str(before_map.get((r, c), "") or "")
        a = str(after_map.get((r, c), "") or "")
        if b != a:
            diffs.append(f"{_col_letter(c)}{r}: {b or '(空)'} → {a or '(空)'}")
    if len(diffs) > max_items:
        rest = len(diffs) - max_items
        return diffs[:max_items] + [f"ほか {rest} セル変更"]
    return diffs
