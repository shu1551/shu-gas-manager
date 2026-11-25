# -*- coding: utf-8 -*-
"""
gas_ws_api.py - 汎用の手 `api`（Sheets API の batchUpdate を ws_do の中で撃つ）の型の表（設計書 第 5 章・段 5）

棚に無い頼みを「棚にありません」で終わらせないための受け皿。使い捨ての GAS コードは流さず、流すのは batchUpdate の requests（宣言の JSON）だけで、
今の ws_do の中を通す（控え・失敗時の戻し・台帳・ws_undo）。ここは **型の表が 1 か所**:
  ・TYPES: requests の型ごとに「触る物」（札の `触る:` と同じ語）と、消す型か、断る欄
  ・表に無い型は断る（許す物だけ通す）。消す型（delete…）は ok が要る（エンジンの守り）
  ・表に載せてよいのは、その型の「触る」物が ws_undo で戻ると実機で確かめられた型だけ（段 4 の調べ: 値・書式・数の書式・結合・固定・シート構成・幅・入力規則・条件付き・
    交互の色・フィルタ・隠し・グループ・保護・名前・タブ色・グラフ。行の高さ・グリッド線・右から左は戻らないので、その欄は断る）
  ・build_types_gs: エンジンに入れる ApiTypes（エンジンの共通部は棚の名前も型も持たず、これだけを見る）
  ・log_uses / used_types: 使った型と頼みの 1 行を .ws_api_uses.tsv に残し、2 回以上使われた型を棚の候補として並べる
"""

import json
from datetime import date
from pathlib import Path

import gas_ws_catalog

HERE = Path(__file__).resolve().parent
USES_FILE = HERE / ".ws_api_uses.tsv"
SHELF = "api"          # 棚の名前（ws_shelves/api.gs の札）

# 型 → 触る物（戻ると確かめられた項目）／ danger＝消す型（ok が要る）／ deny＝この欄を含む指定は断る（戻らない物）
TYPES = {
    # 値・書式
    "repeatCell":                 {"touch": ["値", "書式"]},
    "updateCells":                {"touch": ["値", "書式"]},
    "updateBorders":              {"touch": ["書式"]},
    "mergeCells":                 {"touch": ["書式"]},
    "unmergeCells":               {"touch": ["書式"]},
    "sortRange":                  {"touch": ["値"]},
    "findReplace":                {"touch": ["値"]},
    "copyPaste":                  {"touch": ["値", "書式"]},
    # 消す（ok が要る）
    "deleteRange":                {"touch": ["値", "書式"], "danger": True},
    "deleteDimension":            {"touch": ["値", "書式"], "danger": True},
    # 行・列・シートの形
    "insertDimension":            {"touch": ["値", "書式"]},
    "updateDimensionProperties":  {"touch": ["隠し", "幅"], "deny": [{"when": {"range.dimension": "ROWS"}, "fields": ["pixelSize"]}]},   # 行の高さは戻らない
    "updateSheetProperties":      {"touch": ["シート構成", "固定", "タブ色", "隠し"], "deny": [{"fields": ["hideGridlines", "rightToLeft"]}]},   # グリッド線・右から左は戻らない
    # 脇の状態（段 4 で戻る）
    "addConditionalFormatRule":   {"touch": ["条件付き"]},
    "deleteConditionalFormatRule": {"touch": ["条件付き"], "danger": True},
    "setDataValidation":          {"touch": ["入力規則"]},
    "addBanding":                 {"touch": ["交互の色"]},
    "setBasicFilter":             {"touch": ["フィルタ"]},
    "clearBasicFilter":           {"touch": ["フィルタ"]},
    "addNamedRange":              {"touch": ["名前"]},
    "addDimensionGroup":          {"touch": ["グループ"]},
    "addProtectedRange":          {"touch": ["保護"]},
    "addChart":                   {"touch": ["グラフ"]},
}


def danger_types():
    return sorted(k for k, v in TYPES.items() if v.get("danger"))


def touch_items(types):
    out = []
    for t in types:
        for x in TYPES.get(t, {}).get("touch", []):
            if x not in out:
                out.append(x)
    return out


def _dig(obj, path):
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def check_requests(requests):
    """requests の形の検査。問題の文字列のリスト（空なら通る）。意味（シート名・範囲）はエンジンが見る"""
    p = []
    if not isinstance(requests, list) or not requests:
        return ["requests は batchUpdate の requests の配列です（1 つ以上）"]
    for i, r in enumerate(requests, 1):
        if not isinstance(r, dict) or len(r) != 1:
            p.append(f"{i} 番目の request は {{\"型の名前\": {{…}}}} の形（キーが 1 つ）です")
            continue
        (name, body), = r.items()
        spec = TYPES.get(name)
        if spec is None:
            p.append(f"{i} 番目の request の型「{name}」は api の表にありません（許す型: {'・'.join(sorted(TYPES))}）")
            continue
        if not isinstance(body, dict):
            p.append(f"{i} 番目の「{name}」の中身はオブジェクトです")
            continue
        fields = str(body.get("fields", ""))
        for d in spec.get("deny", []):
            when = d.get("when", {})
            if all(_dig(body, k) == v for k, v in when.items()) and any(tok in fields for tok in d["fields"]):
                p.append(f"{i} 番目の「{name}」の fields「{fields}」は、ws_undo で戻らない物（{'・'.join(d['fields'])}）を含むので断ります")
    return p


def check_op(op):
    """validate_ops から呼ばれる（札の引数の形の検査の後）。問題があれば日本語の 1 文、無ければ None"""
    probs = check_requests(op.get("requests"))
    return ("棚「api」: " + probs[0] + ("（ほか " + str(len(probs) - 1) + " 件）" if len(probs) > 1 else "")) if probs else None


gas_ws_catalog.EXTRA_CHECKS[SHELF] = check_op


def build_types_gs():
    """エンジンに入れる ApiTypes。共通部は api の中身を知らず、棚（ws_shelves/api.gs）がこれを読む"""
    obj = {k: {"touch": v["touch"], "danger": bool(v.get("danger")), "deny": v.get("deny", [])} for k, v in sorted(TYPES.items())}
    return "// ApiTypes.gs - 道具（gas_ws_api.py の型の表）が作る。手で直さない\nvar API_TYPES = " + json.dumps(obj, ensure_ascii=False) + ";\n"


# ------------------------------------------------------------------ 使った型の記録（棚に上げる候補の材料）
def log_uses(ops, path=None, today=None):
    """撃った api の型と頼みの 1 行を 1 行ずつ残す: 日付<TAB>型<TAB>why"""
    p = Path(path) if path else USES_FILE
    rows = []
    for op in ops or []:
        if isinstance(op, dict) and op.get("shelf") == SHELF and isinstance(op.get("requests"), list):
            why = str(op.get("why") or "").replace("\t", " ").replace("\n", " ")
            for r in op["requests"]:
                if isinstance(r, dict) and len(r) == 1:
                    rows.append(f"{today or date.today().isoformat()}\t{next(iter(r))}\t{why}")
    if not rows:
        return 0
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
    except OSError:
        return 0
    return len(rows)


def used_types(path=None, min_count=2):
    """2 回以上使われた型 [(型, 回数, 頼みの例)]（回数の多い順）"""
    p = Path(path) if path else USES_FILE
    if not p.exists():
        return []
    cnt, why = {}, {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2:
            cnt[parts[1]] = cnt.get(parts[1], 0) + 1
            if len(parts) >= 3 and parts[2] and parts[1] not in why:
                why[parts[1]] = parts[2]
    return sorted([(t, n, why.get(t, "")) for t, n in cnt.items() if n >= min_count], key=lambda x: (-x[1], x[0]))


def _handle_backup(st, op, **kw):
    """backup 棚の実行: .ws_state.json の backup フラグを永続切替する"""
    if kw.get("phase") == "post":
        return None
    on = bool(op.get("on"))
    st["backup"] = on
    return (
        "バックアップ設定を ON（毎回控えを取る）に切り替えました"
        if on
        else "バックアップ設定を OFF（控えなし・高速）に切り替えました"
    )


gas_ws_catalog.LOCAL_HANDLERS["backup"] = _handle_backup
gas_ws_catalog.NEEDS_TARGET_FN["folder"] = lambda op: (op.get("mode") or "move").lower() == "move"
gas_ws_catalog.NEEDS_TARGET_FN["drive.list"] = lambda op: False
gas_ws_catalog.NEEDS_TARGET_FN["drive.rename"] = lambda op: not op.get("item")
gas_ws_catalog.NEEDS_TARGET_FN["drive.move"] = lambda op: not op.get("item")
gas_ws_catalog.NEEDS_TARGET_FN["drive.trash"] = lambda op: not op.get("item")
