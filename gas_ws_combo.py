# -*- coding: utf-8 -*-
"""
gas_ws_combo.py - GASコンボ ビルダー・インストーラー・郵便受けウォッチャー

スプレッドシートのコンテナバインドスクリプトまたはスタンドアロン GAS プロジェクトに
5 ファイル構成の GASコンボ（Engine / ComboPlanner / ComboServer / ComboSidebar / appsscript）を
生成・配置し、CLI 操作および郵便受け AI 連携監視を提供する。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gas_workspace
import gas_ws_api  # LOCAL_HANDLERS / EXTRA_CHECKS の登録を保証
import gas_ws_ask
import gas_ws_catalog
import gas_ws_find

PLANNER_TEMPLATE = HERE / "combo_planner_template.js"
PHRASES_PATH = HERE / "combo_phrases.json"   # 言い方の表（頼み→ops。combo phrase で足す。全員に配る覚え）
SERVER_TEMPLATE = HERE / "combo_server_template.gs"
SIDEBAR_TEMPLATE = HERE / "combo_sidebar_template.html"
ADDON_TEMPLATE = HERE / "combo_addon_template.gs"
DEFAULT_ADDON_TITLE = "GASコンボ（アドオン）"
DEFAULT_COMBO_TEMPLATE_TITLE = "GASコンボ テンプレート"

COMBO_FILE_NAMES = ("appsscript", "Engine", "ComboPlanner", "ComboServer", "ComboSidebar")

_SHELF_DROP_KEYS = {"body", "file"}


def build_combo_catalog_data(shelf_dir=None):
    """棚カタログ・同義語・案内・カテゴリを JSON シリアライズ可能な辞書として抽出する。"""
    sd = Path(shelf_dir) if shelf_dir else gas_ws_catalog.SHELF_DIR
    cat = gas_ws_catalog.load(sd)
    synonyms = gas_ws_find.load_synonyms(sd / "synonyms.txt")
    guide = gas_ws_find.load_guide(sd / "guide.txt")

    shelves = []
    for s in cat.shelves:
        item = {k: v for k, v in s.items() if k not in _SHELF_DROP_KEYS}
        shelves.append(item)

    return {
        "shelves": shelves,
        "synonyms": [[a, b] for a, b in synonyms],
        "guide": [[list(words), text] for words, text in guide],
        "categories": list(gas_ws_catalog.CATEGORIES),
        "localHandlers": sorted(gas_ws_catalog.LOCAL_HANDLERS.keys()),
        "ask_rules": gas_ws_ask.load_ask_rules(),
    }


def _patch_engine_open_target(engine_src):
    """メモリ上で openTarget_ を差し替え、コンテナバインドでは getActiveSpreadsheet() を優先させる。"""
    pattern = re.compile(
        r"function openTarget_\(t\)\s*\{.*?\n\}",
        re.DOTALL,
    )
    replacement = (
        "function openTarget_(t) {\n"
        "  t = t || {};\n"
        "  if (t.kind === 'doc') {\n"
        "    var activeDoc = null;\n"
        "    try { activeDoc = DocumentApp.getActiveDocument(); } catch (eD) {}\n"
        "    if (activeDoc && (!t.id || activeDoc.getId() === t.id)) return { kind: 'doc', file: activeDoc };\n"
        "    if (!t.id) throw new ArgError('対象のファイルが決まっていません');\n"
        "    return { kind: 'doc', file: DocumentApp.openById(t.id) };\n"
        "  }\n"
        "  var activeSs = null;\n"
        "  try { activeSs = SpreadsheetApp.getActiveSpreadsheet(); } catch (eS) {}\n"
        "  if (activeSs && (!t.id || activeSs.getId() === t.id)) return { kind: 'sheet', file: activeSs };\n"
        "  if (t.id) return { kind: 'sheet', file: SpreadsheetApp.openById(t.id) };\n"
        "  if (typeof comboOpenSs_ === 'function') return { kind: 'sheet', file: comboOpenSs_(t) };\n"
        "  throw new ArgError('対象のファイルが決まっていません');\n"
        "}"
    )
    patched, count = pattern.subn(replacement, engine_src, count=1)
    if count != 1:
        raise RuntimeError("workspace_engine.gs 内の openTarget_ が見つからずパッチできませんでした")
    return patched


def _patch_engine_sheets_guards(engine_src):
    """Sheets 高度なサービス無効時も Engine が安全にフォールバックできるようメモリ上でガードを注入する。"""
    guards = [
        ("function backupSheetsLite_(ss, sheets, n, items) {", "if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets) return null;"),
        ("function captureSide_(ss, sheets, bk, items) {", "if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets) return;"),
        ("function restoreSide_(ss, bk, notes) {", "if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets) return;"),
        ("function lookSide_(ss, sh) {", "if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets) return [];"),
    ]
    out = engine_src
    for sig, guard in guards:
        if sig in out and guard not in out:
            out = out.replace(sig, sig + "\n  " + guard, 1)
    return out


def _strip_js_comments_ws(src):
    """文字列・正規表現リテラルを保護しつつ // と /* */ コメントおよび余分な空白行を除去する。"""
    out = []
    i = 0
    n = len(src)
    prev_tok = ""
    regex_prev = set("(=!&|?:;,{}[~+-*%^<>")
    while i < n:
        c = src[i]
        if c in ('"', "'"):
            q = c
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    j += 1
                    break
                j += 1
            out.append(src[i:j])
            prev_tok = "S"
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                break
            i = j + 2
            continue
        if c == "/" and (
            not prev_tok
            or prev_tok in regex_prev
            or prev_tok in ("return", "case", "throw", "typeof", "else")
        ):
            j = i + 1
            in_cls = False
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_cls = True
                elif ch == "]":
                    in_cls = False
                elif ch == "/" and not in_cls:
                    j += 1
                    while j < n and src[j].isalpha():
                        j += 1
                    break
                elif ch == "\n":
                    break
                j += 1
            out.append(src[i:j])
            prev_tok = ")"
            i = j
            continue
        if c.isalnum() or c in ("_", "$"):
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in ("_", "$")):
                j += 1
            word = src[i:j]
            out.append(word)
            prev_tok = word
            i = j
            continue
        if not c.isspace():
            prev_tok = c
        out.append(c)
        i += 1
    lines = [ln.strip() for ln in "".join(out).splitlines() if ln.strip()]
    return "\n".join(lines)


def _inject_combo_sheets_shim(engine_src):
    """Advanced Service (Sheets v4) 無効時も api 棚・lookSide_・tidy が動作する遅延 REST シムを先頭に注入する。"""
    shim = (
        "var Sheets = (typeof Sheets !== 'undefined' && Sheets && Sheets.Spreadsheets) ? Sheets : (function () {\n"
        "  function qs_(params) {\n"
        "    if (!params) return '';\n"
        "    var p = [];\n"
        "    Object.keys(params).forEach(function (k) {\n"
        "      var v = params[k];\n"
        "      if (v === undefined || v === null || v === '') return;\n"
        "      if (Array.isArray(v)) {\n"
        "        v.forEach(function (item) { p.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(item))); });\n"
        "      } else {\n"
        "        p.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(v)));\n"
        "      }\n"
        "    });\n"
        "    return p.length ? ('?' + p.join('&')) : '';\n"
        "  }\n"
        "  function call_(method, url, payload) {\n"
        "    var opt = { method: method, headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true };\n"
        "    if (payload !== undefined) { opt.contentType = 'application/json'; opt.payload = JSON.stringify(payload); }\n"
        "    var res = UrlFetchApp.fetch(url, opt);\n"
        "    var code = res.getResponseCode();\n"
        "    var txt = res.getContentText() || '{}';\n"
        "    var obj = JSON.parse(txt);\n"
        "    if (code >= 400 || obj.error) {\n"
        "      throw new Error((obj.error && obj.error.message) || ('Sheets API error ' + code));\n"
        "    }\n"
        "    return obj;\n"
        "  }\n"
        "  return {\n"
        "    Spreadsheets: {\n"
        "      get: function (ssId, params) {\n"
        "        return call_('get', 'https://sheets.googleapis.com/v4/spreadsheets/' + encodeURIComponent(ssId) + qs_(params));\n"
        "      },\n"
        "      batchUpdate: function (body, ssId) {\n"
        "        return call_('post', 'https://sheets.googleapis.com/v4/spreadsheets/' + encodeURIComponent(ssId) + ':batchUpdate', body);\n"
        "      }\n"
        "    }\n"
        "  };\n"
        "})();\n"
    )
    return shim + engine_src


def _trim_engine_for_combo(engine_src):
    """コンボ大元エンジンで不要な WebApp(doGet/doPost) および MCP 目視(actLook_/actRender_) コードをメモリ上のみ除外する。"""
    out = re.sub(
        r"function doGet\(e\)\s*\{.*?(?=\nfunction json_\()",
        "",
        engine_src,
        count=1,
        flags=re.DOTALL,
    )
    out = re.sub(
        r"function actLook_\(req\)\s*\{.*?(?=\n// -+\s*棚（共通）|\nvar SHELF = \{\};)",
        "",
        out,
        count=1,
        flags=re.DOTALL,
    )
    return out


def build_combo_files(
    target_ss_id="",
    shelf_dir=None,
    include_extra_scopes=True,
    enable_advanced_sheets=False,
    minify_server=True,
    sheet_only=False,
    include_server_planner=True,
    combo_lite=False,
):
    """GASコンボ用ファイル（appsscript / Engine / [ComboPlanner] / ComboServer / ComboSidebar）を組み立てる。"""
    if combo_lite:
        sheet_only = True
        include_server_planner = False
        enable_advanced_sheets = False
        minify_server = True

    sd = Path(shelf_dir) if shelf_dir else gas_ws_catalog.SHELF_DIR
    cat_data = build_combo_catalog_data(sd)
    if combo_lite:
        trimmed_shelves = []
        for s in cat_data["shelves"]:
            if s.get("kind") == "doc" and not s.get("shared"):
                continue
            s_copy = dict(s)
            if isinstance(s.get("args"), list):
                s_copy["args"] = [
                    {
                        k: v
                        for k, v in a.items()
                        if not ((k == "req" and v is False) or (k in ("default", "choices") and v is None))
                    }
                    if isinstance(a, dict)
                    else a
                    for a in s["args"]
                ]
            trimmed_shelves.append(s_copy)
        cat_for_html = dict(cat_data, shelves=trimmed_shelves)
    else:
        cat_for_html = cat_data
    cat_json = json.dumps(cat_for_html, ensure_ascii=False, separators=(",", ":"))

    planner_src = PLANNER_TEMPLATE.read_text(encoding="utf-8")
    phrases_json = json.dumps(load_combo_phrases(), ensure_ascii=False, separators=(",", ":"))
    planner_src = "var COMBO_PHRASES = " + phrases_json + ";\n" + planner_src
    server_src = SERVER_TEMPLATE.read_text(encoding="utf-8")
    sidebar_src = SIDEBAR_TEMPLATE.read_text(encoding="utf-8")

    # 1. appsscript (JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if not combo_lite:
        scopes.insert(1, "https://www.googleapis.com/auth/documents")
    if include_extra_scopes:
        scopes.extend([
            "https://www.googleapis.com/auth/script.container.ui",
            "https://www.googleapis.com/auth/script.external_request",
        ])
    dependencies = (
        {"enabledAdvancedServices": [{"userSymbol": "Sheets", "serviceId": "sheets", "version": "v4"}]}
        if enable_advanced_sheets
        else {}
    )
    manifest = {
        "timeZone": "Asia/Tokyo",
        "exceptionLogging": "STACKDRIVER",
        "runtimeVersion": "V8",
        "dependencies": dependencies,
        "oauthScopes": scopes,
        "webapp": {"executeAs": "USER_DEPLOYING", "access": "MYSELF"},
    }

    # 2. Engine (SERVER_JS) - 元ファイルを変更せずメモリ上のみ ENGINE_VERSION 埋め込みと openTarget_ / Sheets をパッチ
    engine_texts, _, engine_ver = gas_workspace._engine_bundle(shelf_dir=sd)
    engine_texts = list(engine_texts)
    engine_texts[0] = (
        engine_texts[0][0],
        re.sub(r"var ENGINE_VERSION = '[^']*';", f"var ENGINE_VERSION = '{engine_ver}';", engine_texts[0][1], count=1),
    )
    if sheet_only:
        engine_texts = [(nm, src) for nm, src in engine_texts if nm not in ("doc", "doc_more")]
    engine_joined = "\n".join(src for _, src in engine_texts)
    if combo_lite:
        engine_joined = _trim_engine_for_combo(engine_joined)
    engine_patched = _patch_engine_open_target(engine_joined)
    if enable_advanced_sheets:
        engine_patched = _patch_engine_sheets_guards(engine_patched)
    elif combo_lite:
        engine_patched = _inject_combo_sheets_shim(engine_patched)
    else:
        engine_patched = _patch_engine_sheets_guards(engine_patched)
    if minify_server:
        engine_patched = _strip_js_comments_ws(engine_patched)

    # 3. ComboPlanner (SERVER_JS) - 毎回のトップレベル巨大オブジェクト評価を省き、必要時のみ JSON.parse する遅延定義
    if sheet_only:
        srv_cat = dict(
            cat_data,
            shelves=[s for s in cat_data["shelves"] if s.get("kind") != "doc" or s.get("shared")],
        )
        srv_cat_json = json.dumps(srv_cat, ensure_ascii=False, separators=(",", ":"))
    else:
        srv_cat_json = cat_json
    cat_json_literal = json.dumps(srv_cat_json, ensure_ascii=False)
    planner_body = _strip_js_comments_ws(planner_src) if minify_server else planner_src
    combo_planner_src = (
        f"var COMBO_CATALOG_JSON = {cat_json_literal};\n"
        "var _COMBO_CATALOG_PARSED_ = null;\n"
        "Object.defineProperty(typeof globalThis !== 'undefined' ? globalThis : this, 'COMBO_CATALOG_DATA', {\n"
        "  configurable: true,\n"
        "  enumerable: true,\n"
        "  get: function () {\n"
        "    if (!_COMBO_CATALOG_PARSED_) _COMBO_CATALOG_PARSED_ = JSON.parse(COMBO_CATALOG_JSON);\n"
        "    return _COMBO_CATALOG_PARSED_;\n"
        "  }\n"
        "});\n"
        f"{planner_body}"
    )

    # 4. ComboServer (SERVER_JS) - target_ss_id / 軽量棚サマリーを埋め込む
    ss_id_clean = str(target_ss_id or "").strip()
    if ss_id_clean:
        server_src = re.sub(
            r"var DEFAULT_TARGET_SS_ID = '[^']*';",
            f"var DEFAULT_TARGET_SS_ID = {json.dumps(ss_id_clean)};",
            server_src,
            count=1,
        )
    if combo_lite:
        mini_shelves = [
            {"name": s["name"], "c": s.get("category", ""), "t": s.get("title", ""), "a": s.get("args_raw", "")}
            for s in cat_for_html["shelves"]
        ]
        server_src = re.sub(
            r"var COMBO_MINI_SHELVES = null;",
            f"var COMBO_MINI_SHELVES = {json.dumps(mini_shelves, ensure_ascii=False, separators=(',', ':'))};",
            server_src,
            count=1,
        )
    if minify_server:
        server_src = _strip_js_comments_ws(server_src)

    # 5. ComboSidebar (HTML) - <script> 内での </script> 誤閉じを防ぎつつインライン展開
    html_cat = f"var COMBO_CATALOG_DATA = {cat_json.replace('</', '<\\/')};"
    planner_for_html = _strip_js_comments_ws(planner_src) if combo_lite else planner_src
    html_planner = planner_for_html.replace("</", "<\\/")
    if "/*__COMBO_CATALOG_DATA__*/" not in sidebar_src or "/*__COMBO_PLANNER_JS__*/" not in sidebar_src:
        raise RuntimeError("combo_sidebar_template.html に必須の注入プレースホルダーが見つかりません")
    sidebar_out = sidebar_src.replace("/*__COMBO_CATALOG_DATA__*/", html_cat, 1)
    sidebar_out = sidebar_out.replace("/*__COMBO_PLANNER_JS__*/", html_planner, 1)
    shared_defs_p = Path(__file__).resolve().parent / "ws_shared_defs.json"
    if shared_defs_p.exists() and "/*__WS_SHARED_COLOR_MAP_START__*/" in sidebar_out and "/*__WS_SHARED_COLOR_MAP_END__*/" in sidebar_out:
        _sdefs = json.loads(shared_defs_p.read_text(encoding="utf-8"))
        _cmap_json = json.dumps(_sdefs.get("color_map") or {}, ensure_ascii=False, separators=(",", ":"))
        sidebar_out = re.sub(
            r"/\*__WS_SHARED_COLOR_MAP_START__\*/[\s\S]*?/\*__WS_SHARED_COLOR_MAP_END__\*/",
            f"var DIRECT_COLOR_MAP = {_cmap_json};",
            sidebar_out,
            count=1,
        )

    out_files = [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, ensure_ascii=False, indent=2)},
        {"name": "Engine", "type": "SERVER_JS", "source": engine_patched},
    ]
    if include_server_planner:
        out_files.append({"name": "ComboPlanner", "type": "SERVER_JS", "source": combo_planner_src})
    out_files.extend([
        {"name": "ComboServer", "type": "SERVER_JS", "source": server_src},
        {"name": "ComboSidebar", "type": "HTML", "source": sidebar_out},
    ])
    return out_files


def load_combo_phrases(path=None):
    """言い方の表（鍵＝棚当ての learnKey・値＝ops）を読む。無ければ空。"""
    pth = Path(path) if path else PHRASES_PATH
    if not pth.exists():
        return {}
    try:
        data = json.loads(pth.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


DEFAULT_PUSH_CHECK_ASKS = (
    "単価の列を削除して",
    "日付から経過年数の列を足して",
    "売上金額の大きい順に並べ替えて",
    "売上金額の合計を表の一番下に出して",
)


def _planner_eval_many(asks, table=None):
    """頼みを何本でも node 1 回で棚当てに通し、[{ask, fire, ops, suggest, reasons}] を返す。"""
    import subprocess
    planner = next(f["source"] for f in build_combo_files() if f["name"] == "ComboPlanner")
    tbl = table or {"title_a1": "A1", "header_row": 3, "header": ["日付", "部門", "担当者", "商品名", "数量", "単価", "売上金額"],
                    "first_row": 4, "last_row": 9, "total_row": 9, "range": "A3:G9"}
    js = ("const vm=require('vm'),fs=require('fs');const d=JSON.parse(fs.readFileSync(0,'utf8'));"
          "const ctx=vm.createContext({});vm.runInContext(d.pj,ctx);const P=ctx.ComboPlanner;"
          "process.stdout.write(JSON.stringify(d.asks.map(a=>{try{"
          "const p=P.plan(a,'sheet',d.t,['売上表'],'売上表',null);"
          "return {ask:a,fire:!!p.fire,ops:p.ops,suggest:p.suggest||null,reasons:p.reasons};}"
          "catch(e){return {ask:a,error:(e&&e.message)?String(e.message):String(e)};}})));")
    r = subprocess.run(["node", "-e", js], input=json.dumps({"pj": planner, "asks": list(asks), "t": tbl}, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("棚当ての実行に失敗しました: " + r.stderr.decode("utf-8", "replace")[:400])
    items = json.loads(r.stdout.decode("utf-8"))
    errs = [f"「{x['ask']}」で例外: {x['error']}" for x in items if x.get("error")]
    if errs:
        raise RuntimeError("棚当てで例外が発生したため中止しました: " + " / ".join(errs))
    return items


def _publish_leak_check():
    """公開してはいけない物（手元のパス・鍵・メールアドレス・知らないファイル）が混ざっていないかだけを見る。"""
    import subprocess
    pc = HERE / "publish_check.py"
    if not pc.exists():
        return True, ""
    # MCP の標準入力（会話の管）を子に渡すと待ちで止まるので、入力は空にする
    r = subprocess.run([sys.executable, str(pc)], cwd=str(HERE), capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    text = r.stdout.decode("utf-8", "replace").strip()
    return r.returncode == 0, (text.splitlines()[-1] if text else "")


def _planner_eval(ask, table=None):
    """棚当て（JS）を node で 1 回動かし、learnKey・当たり・候補を返す。"""
    import subprocess
    planner = next(f["source"] for f in build_combo_files() if f["name"] == "ComboPlanner")
    tbl = table or {"title_a1": "A1", "header_row": 3, "header": ["日付", "部門", "担当者", "商品名", "数量", "単価", "売上金額"],
                    "first_row": 4, "last_row": 9, "total_row": 9, "range": "A3:G9"}
    js = ("const vm=require('vm'),fs=require('fs');const d=JSON.parse(fs.readFileSync(0,'utf8'));"
          "const ctx=vm.createContext({});vm.runInContext(d.pj,ctx);const P=ctx.ComboPlanner;"
          "const p=P.plan(d.ask,'sheet',d.t,['表'],'表',null);"
          "process.stdout.write(JSON.stringify({key:P.learnKey(d.ask),fire:!!p.fire,ops:p.ops,suggest:p.suggest||null,reasons:p.reasons}));")
    r = subprocess.run(["node", "-e", js], input=json.dumps({"pj": planner, "ask": ask, "t": tbl}, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("棚当ての実行に失敗しました: " + r.stderr.decode("utf-8", "replace")[:400])
    return json.loads(r.stdout.decode("utf-8"))


def push_combo_dev(client=None, state_path=None, asks=None, dry_run=False):
    """元（combo_*_template と言い方の表）を直したら、これ 1 回で届く。
    大元ライブラリとアドオンへ同時に送り、操作窓（/exec）の版だけ上げる。大元の版は上げない（アドオンは開発モードでつなぐ）。
    テンプレート（人がコピーする物）は版でつなぐので、配る節目に combo template で上げる。"""
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    t0 = _time.time()
    # 1. 確かめ: 渡した頼み＋表ありの代表頼みが、どの棚にどの引数で当たるか（送る前に並べる）
    checks = []
    eval_asks = list(dict.fromkeys([*(asks or []), *DEFAULT_PUSH_CHECK_ASKS]))
    for r in _planner_eval_many(eval_asks):
        if r["fire"]:
            checks.append("当たる: " + r["ask"] + " → " + json.dumps(r["ops"], ensure_ascii=False))
        elif r.get("suggest"):
            checks.append("候補: " + r["ask"] + " → " + json.dumps(r["suggest"], ensure_ascii=False) + "（［はい］で撃つ）")
        else:
            checks.append("当たらない: " + r["ask"] + "（" + "／".join(r.get("reasons") or []) + "）")
    # 2. 公開してはいけない物が混ざっていないか（混ざっていたら送らない）
    ok_leak, leak_line = _publish_leak_check()
    if not ok_leak:
        return {"ok": False, "mode": "push", "checks": checks, "leak": leak_line, "text": "公開前の点検で止めました（送っていません）"}
    if dry_run:
        return {"ok": True, "mode": "dry_run", "checks": checks, "leak": leak_line, "seconds": round(_time.time() - t0, 1)}
    if client is None:
        from gas_client import GasClient
        client = GasClient()
    spath = Path(state_path) if state_path else COMBO_ENGINE_STATE_PATH
    st = json.loads(spath.read_text(encoding="utf-8")) if spath.exists() else {}
    lib_id = str(st.get("combo_engine_sid") or "").strip()
    addon_sid = str(st.get("addon_sid") or "").strip()
    dep_id = str(st.get("addon_webapp_dep") or "").strip()
    if not (lib_id and addon_sid):
        return install_combo_addon(client=client, state_path=state_path)
    ver = str(st.get("combo_engine_ver") or "1")
    webapp_url = f"https://script.google.com/macros/s/{dep_id}/exec" if dep_id else ""
    lib_files = build_combo_files(combo_lite=True)
    addon_files = build_combo_addon_files(lib_id, ver, webapp_url=webapp_url, development_mode=True)

    def _send_lib():
        client._put_content(lib_id, lib_files)
        _clear_runner_cache(client, lib_id)

    def _send_addon():
        client._put_content(addon_sid, addon_files)
        if dep_id:
            client.deploy(addon_sid, description="GASコンボ 操作窓", deployment_id=dep_id, fast=True)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_send_lib), ex.submit(_send_addon)]
        for f in futs:
            f.result()
    if client.__class__.__name__ == "GasClient":
        try:
            deliver_bridge_token(client, addon_sid, st, spath)
        except Exception as e_tok:
            checks = list(checks or []) + [f"直結の合い言葉を操作窓へ渡せませんでした: {e_tok}"]
    return {"ok": True, "mode": "push", "checks": checks, "leak": leak_line, "engineLibId": lib_id, "addon": addon_sid, "window": webapp_url,
            "seconds": round(_time.time() - t0, 1),
            "next": "アドオン（カード・操作窓）は次に開いたときから新しいコード。テンプレートは配る節目に combo template"}


def add_combo_phrase(ask, ops=None, deploy=True, client=None, path=None):
    """当たらなかった頼みを言い方の表に足し、大元とアドオンへ送るまでを 1 回で。
    ops を省くと棚当ての「近い候補」を使う。既に一発で当たる頼みは足さない。"""
    import subprocess
    import time as _time
    t0 = _time.time()
    ask = str(ask or "").strip()
    if not ask:
        raise ValueError("頼みの文がありません")
    before = _planner_eval(ask)
    if before["fire"] and not ops:
        return {"ok": True, "added": False, "text": "もう一発で当たります: " + json.dumps(before["ops"], ensure_ascii=False)}
    if isinstance(ops, str):
        ops = json.loads(ops)
    if isinstance(ops, dict):
        ops = [ops]
    use_ops = ops or before.get("suggest")
    if not use_ops:
        return {"ok": False, "added": False, "text": "近い候補がありません。ops を渡してください（例: '{\"shelf\":\"format\",\"title\":true,\"color\":\"赤\"}'）",
                "reasons": before.get("reasons")}
    pth = Path(path) if path else PHRASES_PATH
    table = load_combo_phrases(pth)
    table[before["key"]] = use_ops
    pth.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = _planner_eval(ask)
    if not after["fire"] or after["ops"] != use_ops:
        raise RuntimeError("足したのに当たりません: " + json.dumps(after, ensure_ascii=False))
    out = {"ok": True, "added": True, "ask": ask, "key": before["key"], "ops": use_ops}
    if deploy:
        r = push_combo_dev(client=client)
        out["pushSeconds"] = r.get("seconds")
    out["seconds"] = round(_time.time() - t0, 1)
    return out


DEFAULT_ENGINE_LIB_ID = ""   # 決め打ちの大元は持たない（使う人ごとに ensure_combo_engine_project が自分の Drive に作る）
DEFAULT_COMBO_ENGINE_TITLE = "shu-gas-combo-engine"
COMBO_ENGINE_STATE_PATH = HERE / ".combo_engine_state.json"

CONNECTOR_CODE_TEMPLATE = """/**
 * GASコンボ（スプレッドシート側 繋ぎコード）
 * 本体・棚・UI はすべて大元ライブラリ {lib_symbol} 側で管理する。
 */
function onOpen(e) {
  SpreadsheetApp.getUi()
    .createMenu('⚡ GASコンボ')
    .addItem('操作窓（サイドバー）を開く', 'showGasComboSidebar')
    .addItem('直前を取り消す', 'comboMenuUndo')
    .addToUi();
}

function showGasComboSidebar() {
  SpreadsheetApp.getUi().showSidebar({lib_symbol}.createComboSidebarHtml());
}

function comboMenuUndo() {
  return {lib_symbol}.comboMenuUndo();
}

function comboInit(req) { return {lib_symbol}.comboInit(req); }
function comboLook(req) { return {lib_symbol}.comboLook(req); }
function comboRunAsk(req) { return {lib_symbol}.comboRunAsk(req); }
function comboRunOps(req) { return {lib_symbol}.comboRunOps(req); }
function comboFind(req) { return {lib_symbol}.comboFind(req); }
function comboUndo(req) { return {lib_symbol}.comboUndo(req); }
function comboGetConfig() { return {lib_symbol}.comboGetConfig(); }
function comboSaveConfig(cfg) { return {lib_symbol}.comboSaveConfig(cfg); }
function comboPollSelection(req) { return {lib_symbol}.comboPollSelection(req); }
function comboSetTestTarget(ssId) { return {lib_symbol}.comboSetTestTarget(ssId); }
function comboPostboxPoll() { return {lib_symbol}.comboPostboxPoll(); }
function comboPostboxDeliver(p) { return {lib_symbol}.comboPostboxDeliver(p); }
function comboGetLearned(req) { return {lib_symbol}.comboGetLearned(req); }
function comboLearn(req) { return {lib_symbol}.comboLearn(req); }
function comboQuickList(req) { return {lib_symbol}.comboQuickList(req); }
function comboQuickRun(req) { return {lib_symbol}.comboQuickRun(req); }
function comboQuickMake(req) { return {lib_symbol}.comboQuickMake(req); }
function comboQuickGetFn(req) { return {lib_symbol}.comboQuickGetFn(req); }
function comboQuickSaveFn(req) { return {lib_symbol}.comboQuickSaveFn(req); }
function comboQuickAddFn(req) { return {lib_symbol}.comboQuickAddFn(req); }
function comboQuickDeleteFn(req) { return {lib_symbol}.comboQuickDeleteFn(req); }
function comboQuickSaveOrder(req) { return {lib_symbol}.comboQuickSaveOrder(req); }
function comboQuickSavePins(req) { return {lib_symbol}.comboQuickSavePins(req); }
function comboQuickSaveSteps(req) { return {lib_symbol}.comboQuickSaveSteps(req); }
function comboQuickAiSave(req) { return {lib_symbol}.comboQuickAiSave(req); }
function comboCall(name, req) { return {lib_symbol}.comboCall(name, req); }
"""
CONNECTOR_CODE_GS = CONNECTOR_CODE_TEMPLATE.replace("{lib_symbol}", "shucomboengine")


def _combo_files_hash(files):
    import hashlib
    h = hashlib.sha1()
    for f in files:
        h.update(f["name"].encode("utf-8"))
        h.update(f["source"].encode("utf-8"))
    return h.hexdigest()[:12]


def ensure_combo_engine_project(client=None, force_update=False, state_path=None):
    """GASコンボ専用の超軽量大元ライブラリプロジェクト（shu-gas-combo-engine）を1本用意し、(scriptId, version) を返す。"""
    if client is None:
        from gas_client import GasClient
        client = GasClient()

    spath = Path(state_path) if state_path else COMBO_ENGINE_STATE_PATH
    st = {}
    if spath.exists():
        try:
            st = json.loads(spath.read_text(encoding="utf-8")) or {}
        except Exception:
            st = {}

    files = build_combo_files(combo_lite=True)
    fhash = _combo_files_hash(files)

    sid = str(st.get("combo_engine_sid") or "").strip()
    if not sid:
        try:
            projs = client.list_projects(limit=100) or []
            for p in projs:
                if p.get("name") == DEFAULT_COMBO_ENGINE_TITLE and p.get("id"):
                    sid = str(p["id"]).strip()
                    break
        except Exception:
            pass
    if not sid:
        created = client.create_project(DEFAULT_COMBO_ENGINE_TITLE)
        sid = str(created["scriptId"]).strip()

    ver = str(st.get("combo_engine_ver") or "").strip()
    if force_update or st.get("combo_engine_hash") != fhash or st.get("combo_engine_sid") != sid or not ver:
        client._put_content(sid, files)
        _clear_runner_cache(client, sid)
        v_num = client.create_version(sid, description=f"GASコンボ超軽量エンジン ({fhash})")
        ver = str(v_num or "1")
        st.update({
            "combo_engine_sid": sid,
            "combo_engine_ver": ver,
            "combo_engine_hash": fhash,
            "combo_engine_symbol": "shucomboengine",
        })
        try:
            spath.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return sid, ver, files


def build_combo_connector_files(
    engine_lib_id="",
    engine_version="1",
    development_mode=False,
    enable_advanced_sheets=False,
    lib_symbol="shucomboengine",
):
    """スプレッドシート側に置く 30 行の繋ぎコード（コード.gs）とライブラリ設定付き appsscript.json を組み立てる。"""
    lib_id = str(engine_lib_id or "").strip()
    if not lib_id:
        try:
            if COMBO_ENGINE_STATE_PATH.exists():
                st = json.loads(COMBO_ENGINE_STATE_PATH.read_text(encoding="utf-8")) or {}
                lib_id = str(st.get("combo_engine_sid") or "").strip()
        except Exception:
            lib_id = ""
    if not lib_id:
        raise ValueError("つなぐ大元ライブラリが決まっていません（gas.py combo connect で自分の Drive に作ってからつなぎます）")

    sym = str(lib_symbol or "shucomboengine").strip()
    code_gs = CONNECTOR_CODE_TEMPLATE.replace("{lib_symbol}", sym).strip() + "\n"

    deps = {
        "libraries": [
            {
                "userSymbol": sym,
                "version": str(engine_version or "1"),
                "libraryId": lib_id,
                "developmentMode": bool(development_mode),
            }
        ]
    }
    if enable_advanced_sheets:
        deps["enabledAdvancedServices"] = [
            {"userSymbol": "Sheets", "serviceId": "sheets", "version": "v4"}
        ]

    manifest = {
        "timeZone": "Asia/Tokyo",
        "exceptionLogging": "STACKDRIVER",
        "runtimeVersion": "V8",
        "dependencies": deps,
        "oauthScopes": [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.scripts",
            "https://www.googleapis.com/auth/script.container.ui",
            "https://www.googleapis.com/auth/script.external_request",
            "https://www.googleapis.com/auth/script.locale",
        ],
        "webapp": {"executeAs": "USER_DEPLOYING", "access": "MYSELF"},
    }
    return [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, ensure_ascii=False, indent=2)},
        {"name": "コード", "type": "SERVER_JS", "source": code_gs},
    ]


def build_combo_addon_files(engine_lib_id, engine_version, lib_symbol="shucomboengine", webapp_url="", development_mode=True):
    """Google Workspace アドオン版 GASコンボのファイル（appsscript・コード・ComboPlanner）を組み立てる。
    1 回インストールすれば全部のスプレッドシートに出る（シートごとのつなぎコードは要らない）。"""
    if not str(engine_lib_id or "").strip():
        raise ValueError("つなぐ大元ライブラリが決まっていません（install_combo_addon が自分の Drive に作ります）")
    sym = str(lib_symbol or "shucomboengine").strip()
    manifest = {
        "timeZone": "Asia/Tokyo",
        "runtimeVersion": "V8",
        "exceptionLogging": "STACKDRIVER",
        # Sheets の高度なサービスを入れると、このプロジェクトで Sheets API が有効になる（操作窓の直結の道＝画面から Sheets API を直接叩く 0.3 秒の道に要る。無いと 403）
        # 大元は「いつも最新」（開発モード）でつなぐ＝元を直して大元へ送れば、版を上げずにアドオンに届く（アドオンは持ち主が使う物）
        "dependencies": {"libraries": [{"userSymbol": sym, "libraryId": engine_lib_id, "version": str(engine_version or "1"), "developmentMode": bool(development_mode)}],
                         "enabledAdvancedServices": [{"userSymbol": "Sheets", "serviceId": "sheets", "version": "v4"}]},
        "oauthScopes": [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.scripts",
            "https://www.googleapis.com/auth/script.external_request",
            "https://www.googleapis.com/auth/script.locale",
        ],
        "addOns": {
            "common": {"name": "GASコンボ", "logoUrl": "https://www.gstatic.com/images/icons/material/system/1x/bolt_black_48dp.png"},
            "sheets": {"homepageTrigger": {"runFunction": "onHome"}, "onFileScopeGrantedTrigger": {"runFunction": "onFileScopeGranted"}},
            "docs": {"homepageTrigger": {"runFunction": "onHome"}, "onFileScopeGrantedTrigger": {"runFunction": "onFileScopeGranted"}},
        },
        "webapp": {"executeAs": "USER_ACCESSING", "access": "MYSELF"},   # 操作窓（前のサイドバーの HTML）を別の窓で開く
        # Workspace アドオンを正式にデプロイするには、外へ通信する先の一覧が要る（AI の API 鍵の道・Sheets API・書き出し）
        "urlFetchWhitelist": ["https://generativelanguage.googleapis.com/", "https://api.anthropic.com/",
                              "https://sheets.googleapis.com/", "https://www.googleapis.com/", "https://docs.google.com/"],
    }
    code = ADDON_TEMPLATE.read_text(encoding="utf-8").replace("{lib_symbol}", sym).replace("{webapp_url}", str(webapp_url or ""))
    planner = next(f for f in build_combo_files() if f["name"] == "ComboPlanner")
    return [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, ensure_ascii=False, indent=2)},
        {"name": "コード", "type": "SERVER_JS", "source": code},
        {"name": "ComboPlanner", "type": "SERVER_JS", "source": planner["source"]},
    ]


def install_combo_addon(addon_id="", force_engine_update=False, client=None, state_path=None, window_json=None):
    """アドオン版を作る・入れ直す。大元ライブラリを最新にし、アドオンのプロジェクトへ push する。
    テスト デプロイ（Test latest code）は最新のコードで動くので、2 回目からはこれだけで全部のシートに効く。"""
    is_real_client = client is None
    if client is None:
        from gas_client import GasClient
        client = GasClient()
    lib_id, ver, _ = ensure_combo_engine_project(client=client, force_update=force_engine_update, state_path=state_path)
    spath = Path(state_path) if state_path else COMBO_ENGINE_STATE_PATH
    st = {}
    try:
        st = json.loads(spath.read_text(encoding="utf-8")) or {} if spath.exists() else {}
    except Exception:
        st = {}
    sid = str(addon_id or st.get("addon_sid") or "").strip()
    created = False
    if not sid:
        sid = str(client.create_project(DEFAULT_ADDON_TITLE)["scriptId"]).strip()
        created = True
    # 操作窓の番地＝正式なウェブアプリのデプロイ（/exec）。/dev は Chrome 拡張のサイドパネルの中に入れると Google が通さない
    # （持ち主でも「アクセス権が必要です」）。デプロイの ID は変わらないので、初回だけ作って、あとは版を上げる
    dep_id = str(st.get("addon_webapp_dep") or "").strip() if not created else ""
    if not dep_id:
        client._put_content(sid, build_combo_addon_files(lib_id, ver, webapp_url=""))
        d = client.deploy(sid, description="GASコンボ 操作窓", fast=True)
        dep_id = str(d.get("deploymentId") or "").strip()
    webapp_url = f"https://script.google.com/macros/s/{dep_id}/exec" if dep_id else ""
    client._put_content(sid, build_combo_addon_files(lib_id, ver, webapp_url=webapp_url))
    if dep_id:
        client.deploy(sid, description="GASコンボ 操作窓", deployment_id=dep_id, fast=True)
    st["addon_webapp_dep"] = dep_id
    st["addon_sid"] = sid
    # Chrome 拡張（ws_browser_ext）のアイコンで操作窓を直接開けるよう、窓の番地を拡張のフォルダに書く（人ごとに違うので公開しない）
    if webapp_url:
        try:
            (Path(window_json) if window_json else HERE / "ws_browser_ext" / "combo_window.json").write_text(json.dumps({"base": webapp_url}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    try:
        spath.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    if client.__class__.__name__ == "GasClient":
        try:
            ensure_bridge_token(window_json)
            st.pop("bridge_token_sent", None)   # 操作窓を作り直したときは渡し直す
            deliver_bridge_token(client, sid, st, spath)
        except Exception:
            pass
    res = {"ok": True, "mode": "addon", "scriptId": sid, "engineLibId": lib_id, "engineVersion": ver, "window": webapp_url,
           "editor": f"https://script.google.com/home/projects/{sid}/edit"}
    # 郵便受け（AI 連携の PC の受け手）を、ログオンのたびに自分で起きるようにして今も起こす（テスト用の偽クライアント時は本番スタートアップを触らない）
    if is_real_client:
        try:
            res["postbox_watcher"] = install_watch_autostart(sid, restart=True).get("text", "")
        except Exception as e:
            res["postbox_watcher"] = f"受け手を起こせませんでした: {e}"
    else:
        res["postbox_watcher"] = "テスト実行のためスキップ"
    if created:
        res["next"] = ("初回だけ、人がアドオンを入れる（AI は install_guide を上から 1 段ずつ読み上げ、"
                       "押せたかを聞いてから次の段へ進む。全部を一度に並べない）")
    else:
        res["next"] = ("入れ直し済み（次に右の枠を開いたときから新しいコードで動きます）。"
                       "シートの右端に ⚡ GASコンボが無い人＝まだ入れていない人には install_guide で案内する")
    res["install_guide"] = _addon_install_guide(res["editor"])
    ext_dir = str(HERE / "ws_browser_ext")
    res["chrome_extension"] = {
        "folder": ext_dir,
        "how": ("Chrome の右のサイドパネルで開く拡張（任意・おすすめ）: chrome://extensions を開き、右上の「デベロッパー モード」をオン →"
                f"「パッケージ化されていない拡張機能を読み込む」→ {ext_dir} を選ぶ。入れてあるなら何もしなくてよい"
                "（拡張のファイルが変わったら、シートのタブを読み込み直す。裏方の background.js が変わったときだけ chrome://extensions で再読み込みを押す）。あとは拡張のアイコンか Alt+G で、今開いているシートが相手の GASコンボが開きます"),
        # 人が入れるときの手ほどき（AI が 1 段ずつ読み上げ、押せたかを聞いてから次へ）。入れ済みの人には要らない
        "install_guide": [
            {"step": 1, "say": "Chrome のアドレス欄に chrome://extensions と入れて開いてください（AI がブラウザを開けるなら AI が開く）"},
            {"step": 2, "say": "右上の「デベロッパー モード」のスイッチをオンにしてください"},
            {"step": 3, "say": f"左上に出た「パッケージ化されていない拡張機能を読み込む」を押し、このフォルダを選んで「フォルダーの選択」を押してください: {ext_dir}",
             "if_stuck": "一覧に「GASコンボ ブラウザ連動」がもうあるなら入れ済みです。次へ"},
            {"step": 4, "say": "右上のパズルの形のアイコン（拡張機能）を押し、「GASコンボ ブラウザ連動」の横のピンを押して、ツールバーに留めてください"},
            {"step": 5, "say": "スプレッドシートを開いて、留めた拡張のアイコン（または Alt+G）を押すと、右のサイドパネルに GASコンボが開きます。タブを替えると相手のシートも替わります",
             "if_stuck": "Alt+G が効かないときは chrome://extensions/shortcuts で「GASコンボをサイドパネルに開く」のキーを確かめる。パネルに「番地がまだありません」と出たら combo addon を撃ってからパネルを開き直す"},
        ],
    }
    return res


def _addon_install_guide(editor_url):
    """アドオンを人が入れるときの手ほどき（画面の名前は 2026-11 の Apps Script・スプレッドシートの表示のまま）。
    AI が 1 段ずつ読み上げ、押せたかを聞いてから次へ進むための台本。"""
    return [
        {"step": 1, "say": f"この番地を開いてください: {editor_url}（Apps Script の編集画面が開きます。AI がブラウザを開けるなら AI が開く）"},
        {"step": 2, "say": "右上の青い「デプロイ」ボタンを押し、出てきた一覧の「デプロイをテスト」を押してください"},
        {"step": 3, "say": "「デプロイをテスト」の窓が開きます。窓の右側を下へ送ると「Google Workspace アドオン」の段があります"
                           "（デプロイ: Test latest code、Application(s): Sheets）。その段の「インストール」を押し、最後に右下の「完了」を押してください",
         "if_stuck": "「インストール」ではなく「アンインストール」と出ているなら、もう入っています。「完了」を押して次へ"},
        {"step": 4, "say": "使いたいスプレッドシートを開いてください（開いていたら再読み込み F5）。画面の右端の縦に並んだアイコンに ⚡（GASコンボ）があるので押してください",
         "if_stuck": "見えないときは右端のアイコン列の下の「…」（その他のアドオン）の中にあります。それでも無ければシートを再読み込み"},
        {"step": 5, "say": "初回だけ権限の画面が出ます。「アクセスを承認」→ ご自分のアカウントを選ぶ →「このアプリは Google で確認されていません」と出たら、"
                           "ご自分の Drive に作ったアドオンなので「詳細」→「GASコンボ（アドオン）（安全ではないページ）に移動」→ 許可の一覧で「すべて選択」に印を付けて「続行」",
         "if_stuck": "「続行」を押した後に右の枠が白いままなら、枠を閉じてもう一度 ⚡ を押す"},
        {"step": 6, "say": "右の枠に GASコンボが出たら入れ終わりです。頼みを書いて「実行」で使えます（入れるのはこの 1 回だけで、ほかのスプレッドシートでも右端の ⚡ から使えます）"},
    ]


def install_combo_connector(
    project_or_sid,
    engine_lib_id="",
    engine_version="",
    development_mode=False,
    enable_advanced_sheets=False,
    lib_symbol="",
    force_engine_update=False,
    client=None,
    state_path=None,
):
    """スプレッドシート付属 GAS へ 30 行の繋ぎコード（コード.gs）とライブラリ設定を配置する。"""
    if client is None:
        from gas_client import GasClient
        client = GasClient()

    sid = client.resolve_script_id(project_or_sid)
    lib_id = str(engine_lib_id or "").strip()
    ver = str(engine_version or "").strip()

    if not lib_id:
        lib_id, ver_auto, _ = ensure_combo_engine_project(client=client, force_update=force_engine_update, state_path=state_path)
        if not ver:
            ver = ver_auto
        sym = str(lib_symbol or "shucomboengine").strip()
    else:
        sym = str(lib_symbol or "shucomboengine").strip()
        if not ver:
            try:
                versions = client.list_versions(lib_id, limit=5) or []
                if versions:
                    ver = str(max(int(v.get("versionNumber", 1)) for v in versions))
            except Exception:
                ver = "1"
        if not ver:
            ver = "1"

    files = build_combo_connector_files(
        engine_lib_id=lib_id,
        engine_version=ver,
        development_mode=development_mode,
        enable_advanced_sheets=enable_advanced_sheets,
        lib_symbol=sym,
    )
    client._put_content(sid, files)
    _clear_runner_cache(client, sid)
    return {
        "ok": True,
        "mode": "connector",
        "scriptId": sid,
        "engineLibId": lib_id,
        "engineVersion": ver,
        "libSymbol": sym,
        "developmentMode": bool(development_mode),
        "advancedSheets": bool(enable_advanced_sheets),
        "files": [f["name"] for f in files],
    }


def _extract_ss_id(val):
    """スプレッドシートの URL または ID からスプレッドシート ID を取り出す。"""
    s = str(val or "").strip()
    if not s:
        return ""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", s)
    if m:
        return m.group(1)
    m2 = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", s)
    if m2:
        return m2.group(1)
    return s


def _extract_script_id_from_url(val):
    s = str(val or "").strip()
    m = re.search(r"/projects/([A-Za-z0-9_-]{20,})", s)
    if m:
        return m.group(1)
    m2 = re.search(r"/d/([A-Za-z0-9_-]{20,})", s)
    if m2 and "script.google.com" in s:
        return m2.group(1)
    return s


def _detect_connect_target(val, client):
    """渡された URL/ID がスプレッドシートか GAS スクリプトかを判定し (kind, id) を返す。"""
    raw = str(val or "").strip()
    if "/spreadsheets/d/" in raw:
        return "sheet", _extract_ss_id(raw)
    if "script.google.com" in raw:
        return "script", _extract_script_id_from_url(raw)
    if hasattr(client, "_request_with_retry") and hasattr(client, "_headers"):
        try:
            url = f"https://www.googleapis.com/drive/v3/files/{raw}?fields=id,name,mimeType&supportsAllDrives=true"
            res = client._request_with_retry("GET", url, headers=client._headers(), timeout=10)
            if getattr(res, "status_code", 0) == 200:
                mt = (res.json() or {}).get("mimeType", "")
                if mt == "application/vnd.google-apps.spreadsheet":
                    return "sheet", raw
                if mt == "application/vnd.google-apps.script":
                    return "script", raw
        except Exception:
            pass
    return "script", raw


def _load_combo_state(state_path=None):
    spath = Path(state_path) if state_path else COMBO_ENGINE_STATE_PATH
    if spath.exists():
        try:
            return json.loads(spath.read_text(encoding="utf-8")) or {}, spath
        except Exception:
            pass
    return {}, spath


def _save_combo_state(st, spath):
    try:
        spath.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _resolve_drive_file_name(file_id, client):
    if hasattr(client, "_request_with_retry") and hasattr(client, "_headers"):
        try:
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name&supportsAllDrives=true"
            res = client._request_with_retry("GET", url, headers=client._headers(), timeout=10)
            if getattr(res, "status_code", 0) == 200:
                return str((res.json() or {}).get("name") or "").strip()
        except Exception:
            pass
    return ""


def _resolve_active_sheet_id(wait_ext_sec=2.0):
    """Chrome 拡張機能（127.0.0.1:18765）または WorkspaceManager の状態から、今開いているスプレッドシート ID を取得する。"""
    # 1. まずローカル状態（拡張機能が ws_window 経由で記録した last_scope / target）を確認
    st_id = ""
    st_name = ""
    try:
        st = gas_workspace.WorkspaceManager()._load() or {}
        ls = st.get("last_scope") or {}
        tgt = st.get("target") or {}
        if ls.get("id") and (ls.get("kind") in (None, "", "sheet")):
            st_id = str(ls["id"]).strip()
        elif tgt.get("id") and (tgt.get("kind") in (None, "", "sheet")):
            st_id = str(tgt["id"]).strip()
            st_name = str(tgt.get("name") or "").strip()
    except Exception:
        pass

    # 2. ws_window が立ち上がっていない場合のみ、127.0.0.1:18765 を短時間待ち受けて拡張機能の最新通知を拾う
    if wait_ext_sec > 0:
        try:
            from http.server import BaseHTTPRequestHandler, HTTPServer
            import threading

            got = {}

            class _OnceHandler(BaseHTTPRequestHandler):
                def log_message(self, _fmt, *_args):
                    pass

                def _origin_ok(self):
                    o = str(self.headers.get("Origin") or "").strip()
                    return (not o) or o == f"chrome-extension://{EXT_FIXED_ID}" or o == "https://docs.google.com"

                def do_OPTIONS(self):
                    if not self._origin_ok():
                        self.send_response(403)
                        self.end_headers()
                        return
                    o = str(self.headers.get("Origin") or "").strip()
                    self.send_response(204)
                    if o:
                        self.send_header("Access-Control-Allow-Origin", o)
                        self.send_header("Vary", "Origin")
                        self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.end_headers()

                def do_POST(self):
                    if not self._origin_ok():
                        self.send_response(403)
                        self.end_headers()
                        return
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        data = json.loads(self.rfile.read(n).decode("utf-8"))
                        if isinstance(data, dict) and data.get("id") and data.get("kind", "sheet") == "sheet":
                            got["id"] = str(data["id"]).strip()
                            got["name"] = str(data.get("name") or "").strip()
                        o = str(self.headers.get("Origin") or "").strip()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        if o:
                            self.send_header("Access-Control-Allow-Origin", o)
                            self.send_header("Vary", "Origin")
                        self.end_headers()
                        self.wfile.write(b'{"ok":true}')
                    except Exception:
                        self.send_response(400)
                        self.end_headers()

            srv = HTTPServer(("127.0.0.1", 18765), _OnceHandler)
            srv.timeout = 0.25
            deadline = time.time() + float(wait_ext_sec)
            while time.time() < deadline and not got.get("id"):
                srv.handle_request()
            srv.server_close()
            if got.get("id"):
                return got["id"], got.get("name", "")
        except Exception:
            pass

    if st_id:
        return st_id, st_name
    raise ValueError("今開いているスプレッドシートを取得できませんでした。URL または ID を指定してください。")


def connect_spreadsheet(
    ss_url_or_id,
    engine_lib_id="",
    engine_version="",
    lib_symbol="",
    title="GASコンボ",
    client=None,
    state_path=None,
    enable_advanced_sheets=False,
    force_engine_update=False,
):
    """スプレッドシートの URL または ID からコンテナバインド GAS を自動作成（既存記録があれば再利用）し、30行繋ぎコードを配置＆別名登録する。"""
    if client is None:
        from gas_client import GasClient
        client = GasClient()

    ss_id = _extract_ss_id(ss_url_or_id)
    if not ss_id:
        raise ValueError("スプレッドシートの URL または ID を指定してください。")

    st, spath = _load_combo_state(state_path)
    sheets_map = st.get("sheets") if isinstance(st.get("sheets"), dict) else {}
    existing_sid = str(sheets_map.get(ss_id) or "").strip()

    created_proj = False
    if existing_sid:
        sid = existing_sid
    else:
        created = client.create_project(title or "GASコンボ", parent_id=ss_id)
        sid = str((created or {}).get("scriptId") or "").strip()
        if not sid:
            raise RuntimeError(f"コンテナバインド GAS の作成に失敗しました: {created!r}")
        created_proj = True

    res = install_combo_connector(
        sid,
        engine_lib_id=engine_lib_id,
        engine_version=engine_version,
        enable_advanced_sheets=enable_advanced_sheets,
        lib_symbol=lib_symbol,
        force_engine_update=force_engine_update,
        client=client,
        state_path=state_path,
    )

    ss_name = _resolve_drive_file_name(ss_id, client)
    alias_name = ss_name or f"GASコンボ_{ss_id[:8]}"
    if hasattr(client, "set_alias"):
        try:
            client.set_alias(alias_name, sid)
        except Exception:
            pass

    sheets_map[ss_id] = sid
    st["sheets"] = sheets_map
    _save_combo_state(st, spath)

    res["spreadsheetId"] = ss_id
    res["spreadsheetName"] = ss_name
    res["aliasName"] = alias_name
    res["createdProject"] = created_proj
    return res


def _create_spreadsheet(title, client):
    """Drive API で新しいスプレッドシートを作成する。"""
    name = str(title or "").strip() or DEFAULT_COMBO_TEMPLATE_TITLE
    url = "https://www.googleapis.com/drive/v3/files"
    params = {"fields": "id,name", "supportsAllDrives": "true"}
    payload = {"name": name, "mimeType": "application/vnd.google-apps.spreadsheet"}
    res = client._request_with_retry("POST", url, headers=client._headers(), params=params, json=payload, timeout=15)
    if getattr(res, "status_code", 0) not in (200, 201):
        raise RuntimeError(f"テンプレート用スプレッドシートの作成に失敗しました ({getattr(res, 'status_code', '?')}): {getattr(res, 'text', '')}")
    data = res.json() if hasattr(res, "json") else {}
    ss_id = str((data or {}).get("id") or "").strip()
    if not ss_id:
        raise RuntimeError(f"作成したスプレッドシートの ID が取得できませんでした: {data!r}")
    return ss_id, str((data or {}).get("name") or name).strip()


def create_combo_template(
    title="",
    new=False,
    force_engine_update=False,
    client=None,
    state_path=None,
):
    """「コピーを作成」だけで使える GASコンボ テンプレートスプレッドシートを作り・入れ直す。"""
    if client is None:
        from gas_client import GasClient
        client = GasClient()

    lib_id, ver, _ = ensure_combo_engine_project(
        client=client,
        force_update=force_engine_update,
        state_path=state_path,
    )
    st, _ = _load_combo_state(state_path)
    tmpl_ss_id = str(st.get("template_ss_id") or "").strip()
    tmpl_title = str(title or "").strip() or DEFAULT_COMBO_TEMPLATE_TITLE

    created_ss = False
    resolved_name = ""
    if new or not tmpl_ss_id:
        tmpl_ss_id, resolved_name = _create_spreadsheet(tmpl_title, client)
        created_ss = True

    res = connect_spreadsheet(
        tmpl_ss_id,
        engine_lib_id=lib_id,
        engine_version=ver,
        title=tmpl_title,
        client=client,
        state_path=state_path,
        enable_advanced_sheets=True,
    )

    st2, spath2 = _load_combo_state(state_path)
    st2["template_ss_id"] = tmpl_ss_id
    st2["template_sid"] = str(res.get("scriptId") or "").strip()
    if resolved_name or res.get("spreadsheetName"):
        st2["template_title"] = str(res.get("spreadsheetName") or resolved_name)
    _save_combo_state(st2, spath2)

    return {
        "ok": True,
        "mode": "template",
        "spreadsheetId": tmpl_ss_id,
        "spreadsheetName": res.get("spreadsheetName") or resolved_name or tmpl_title,
        "scriptId": str(res.get("scriptId") or ""),
        "engineLibId": lib_id,
        "engineVersion": str(res.get("engineVersion") or ver),
        "created": created_ss,
        "url": f"https://docs.google.com/spreadsheets/d/{tmpl_ss_id}/edit",
        "copy_url": f"https://docs.google.com/spreadsheets/d/{tmpl_ss_id}/copy",
        # コピーして使う人への手ほどき（AI が 1 段ずつ読み上げ、押せたかを聞いてから次へ）
        "install_guide": [
            {"step": 1, "say": f"この番地を開いてください: https://docs.google.com/spreadsheets/d/{tmpl_ss_id}/copy"},
            {"step": 2, "say": "「ドキュメントのコピーを作成」の画面が出るので、名前をお好みで変えて「コピーを作成」を押してください（コピーはご自分の Drive に入ります）"},
            {"step": 3, "say": "開いたコピーのメニューの右端に「⚡ GASコンボ」が出ます。それを押して「操作窓（サイドバー）を開く」を押してください",
             "if_stuck": "メニューに「⚡ GASコンボ」が無いときは、数秒待つか、シートを再読み込み（F5）"},
            {"step": 4, "say": "初回だけ「承認が必要です」と出ます。「続行」→ ご自分のアカウントを選ぶ →「このアプリは Google で確認されていません」と出たら、"
                               "ご自分のコピーに付いたスクリプトなので「詳細」→「〜（安全ではないページ）に移動」→「すべて選択」に印を付けて「続行」",
             "if_stuck": "許可の後に何も開かなければ、もう一度「⚡ GASコンボ」→「操作窓（サイドバー）を開く」"},
            {"step": 5, "say": "右にサイドバーが出たら使えます。頼みを書いて「実行」。このコピーの中だけで使えます（ほかのシートでも使いたいときはアドオン版）"},
        ],
    }


def _clear_runner_cache(client, sid):
    """ファイル上書き後に古いランナー導入済みキャッシュが残らないよう掃除する。"""
    try:
        deps = getattr(client, "_cache_data", {}).get("deployments", {})
        if sid in deps and "runner_installed" in deps[sid]:
            deps[sid].pop("runner_installed", None)
            if hasattr(client, "_save_cache"):
                client._save_cache()
    except Exception:
        pass


def install_combo(
    project_or_sid,
    target_ss_id="",
    client=None,
    preserve_existing=False,
    include_extra_scopes=True,
    enable_advanced_sheets=False,
    minify_server=True,
    sheet_only=False,
    include_server_planner=True,
):
    """対象 GAS プロジェクトへ GASコンボ ファイルを配置する。"""
    if client is None:
        from gas_client import GasClient
        client = GasClient()

    sid = client.resolve_script_id(project_or_sid)
    files = build_combo_files(
        target_ss_id=target_ss_id,
        include_extra_scopes=include_extra_scopes,
        enable_advanced_sheets=enable_advanced_sheets,
        minify_server=minify_server,
        sheet_only=sheet_only,
        include_server_planner=include_server_planner,
    )

    if preserve_existing:
        existing = client.get_content(sid, use_cache=False) or {}
        existing_files = existing.get("files") or []
        combo_names = set(COMBO_FILE_NAMES)
        kept = [f for f in existing_files if f.get("name") not in combo_names]
        files = files + kept

    client._put_content(sid, files)
    _clear_runner_cache(client, sid)

    ss_id_clean = str(target_ss_id or "").strip()
    test_target_saved = False
    test_target_error = ""
    auth_needed = False
    if ss_id_clean and hasattr(client, "run_function"):
        if hasattr(client, "resolve_webapp_url") and hasattr(client, "deploy"):
            try:
                client.resolve_webapp_url(sid, refresh=True, dev=True)
            except Exception:
                try:
                    client.deploy(sid, description="GASコンボ WebApp ランナー初期化", fast=True)
                except Exception:
                    pass
        try:
            r = client.run_function(sid, "comboSetTestTarget", [ss_id_clean])
            test_target_saved = bool(isinstance(r, dict) and r.get("ok"))
            if not test_target_saved and isinstance(r, dict):
                if _is_auth_needed(r):
                    auth_needed = True
                    test_target_error = _auth_needed_message(client, sid)
                else:
                    test_target_error = str(r.get("error") or str(r.get("raw") or "")[:200] or "comboSetTestTarget に失敗しました")
        except Exception as e:
            test_target_error = str(e)

    return {
        "ok": True,
        "scriptId": sid,
        "targetSsId": ss_id_clean,
        "files": [f["name"] for f in files],
        "testTargetSaved": test_target_saved,
        "testTargetError": test_target_error,
        "authNeeded": auth_needed,
    }


def _is_auth_needed(resp):
    """GasClient.run_function の応答が初回 OAuth 承認要求かどうかを判定する。"""
    if not isinstance(resp, dict):
        return False
    raw = str(resp.get("raw") or "")
    err = str(resp.get("error") or "")
    return (
        "Authorization needed" in raw
        or "承認が必要" in raw
        or "authorization" in raw.lower()[:600]
        or "呼び出す権限がありません" in err
        or "You do not have permission to call" in err
        or "Required permissions:" in err
    )


def _auth_needed_message(client=None, sid=""):
    """初回承認が必要な場合に表示する WebApp URL と承認手順メッセージを返す。"""
    url = ""
    if client is not None and sid and hasattr(client, "resolve_webapp_url"):
        try:
            url = client.resolve_webapp_url(sid, dev=True)
        except Exception:
            url = f"https://script.google.com/d/{sid}/edit"
    elif sid:
        url = f"https://script.google.com/d/{sid}/edit"
    return (
        "GASコンボの初回承認がまだです（最初の 1 回だけ、ブラウザで承認ボタンを押す必要があります）。\n"
        + (f"1. このURLを開く: {url}\n" if url else "1. スクリプトの WebApp URL またはエディタを開く\n")
        + "2. 「権限を確認」→ アカウントを選び、「詳細」→「（安全ではないページ）に移動」→「許可」を押してください。\n"
        + "3. 許可後、もう一度実行してください。"
    )


def _unwrap_run_result(resp, client=None, sid=""):
    """GasClient.run_function の返却辞書を検査し、GAS 関数の戻り値を取り出す。"""
    if not isinstance(resp, dict):
        raise RuntimeError(f"予期しない run_function 応答: {resp!r}")
    if not resp.get("ok"):
        if _is_auth_needed(resp):
            raise RuntimeError(_auth_needed_message(client, sid))
        err = resp.get("error")
        if not err and resp.get("raw"):
            err = f"GAS 実行に失敗しました: {str(resp['raw'])[:200]}"
        raise RuntimeError(err or "GAS 実行に失敗しました")
    return resp.get("result")



class ComboPostboxWatcher:
    """GAS側の郵便受け（COMBO_POSTBOX_Q）を監視し、ローカル AI で ops / マイマクロを組んで返す。"""

    _MYMACRO_SYSTEM_PROMPT = (
        "あなたは Google スプレッドシート用の Google Apps Script（GAS）マイマクロ作成・修正・相談アシスタントです。\n"
        "必ず有効な JSON オブジェクト 1 個だけを返してください（JSON 以外の説明文や ``` などの装飾をテキスト直書きしないこと）。\n"
        '・相談・質問・改修案の提案（まだコード書き換えの確定指示ではない場合）: {"action":"reply","message":"箇条書き 3〜5 個・合計 200 文字以内を目安に簡潔・番号付きで返すこと（長文一覧は避ける）"}\n'
        '・コードの作成・修正の指示または合意（「それでお願い」「1番で」「作って」「〜に直して」等）: {"action":"mymacro","code":"// 説明\\n// 棚: 呼び方1, 呼び方2\\nfunction 分かりやすい日本語名() {\\n  ...\\n}","note":"何をしたかの1行要約"}\n'
        "ルール（mymacro 出力時）:\n"
        "1. インデントなしのトップレベル function 名前() { ... } を 1 つ定義し、引数は取らないこと（補助関数のみ末尾に _ 可）。メイン関数名の末尾に _ は付けないこと。\n"
        "2. 関数の直上の行に「// 説明」と「// 棚: 言い方1, 言い方2」のコメントを書くこと。\n"
        "3. openById() 等で固定IDを書かず、必ず SpreadsheetApp.getActive() / getActiveSheet() / getActiveRange() / getActiveRangeList() を使うこと。\n"
        "4. 1セルずつの getValue/setValue ループは避け、getValues()/setValues() や getBackgrounds()/setBackgrounds() で2次元配列一括処理すること。\n"
        '5. 結果通知には Browser.msgBox や ui.prompt を使わず、return "完了メッセージ"; を使うこと。\n'
        '6. 既存の棚（ws_shelves）でできる処理（表整理・書式・列幅・集計・フィルタ・罫線・並べ替え等）は自前で長く実装せず、shelf([{shelf:"棚名", ...}, ...]) または shelf("棚名", {...}) を呼んで複数の棚を束ねる「まとめ棚」として組み、棚に無い固有処理だけ SpreadsheetApp で補うこと。'
    )

    def __init__(self, project_or_sid, client=None, model=None, poll_interval=2.0, backend="auto", direct_only=False):
        if client is None:
            from gas_client import GasClient
            client = GasClient()
        self.client = client
        if direct_only:
            # 直結専用モードは GAS 郵便受けポーリングを行わないため、ID 未登録でもサーバー起動を止めない
            try:
                self.sid = client.resolve_script_id(project_or_sid) if project_or_sid else ""
            except Exception:
                self.sid = str(project_or_sid or "")
        else:
            self.sid = client.resolve_script_id(project_or_sid)
        self.model = model
        self.poll_interval = float(poll_interval)
        self.backend = backend
        self._ai_runner = None
        self._mymacro_session = None
        self._finder = None
        self._last_http_at = 0.0
        self._started_at = time.time()
        self._last_ai_ms = None
        self._last_error = ""
        self._direct_only = bool(direct_only)
        import threading as _th
        self._ai_lock = _th.Lock()

    def get_health(self):
        """直結受け手のヘルス情報（稼働時間・直近AI所要時間・バージョン等）を返す。"""
        return {
            "ok": True,
            "pid": os.getpid(),
            "startedAt": int(self._started_at),
            "uptimeSec": round(max(0.0, time.time() - self._started_at), 1),
            "directOnly": bool(self._direct_only),
            "backend": str(self.backend or "auto"),
            "model": str(self.model or "auto"),
            "lastAiMs": self._last_ai_ms,
            "lastError": self._last_error,
            "version": COMBO_WATCH_VERSION,
        }

    @staticmethod
    def _ts_now():
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _close_idle_http_pool(self):
        """長時間アイドルで切れた keep-alive ソケットを閉じて次の HTTP 呼び出しでの 30 秒ハングを防ぐ。"""
        adapters = getattr(getattr(self.client, "session", None), "adapters", None)
        if isinstance(adapters, dict):
            for ad in list(adapters.values()):
                try:
                    ad.close()
                except Exception:
                    pass

    def _get_finder(self):
        if self._finder is None:
            self._finder = gas_ws_find.default()
        return self._finder

    @staticmethod
    def _strip_code_fence(text):
        t = str(text or "").strip()
        m = re.match(r"^```(?:javascript|js|gs)?[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\s*$", t, re.S | re.I)
        if m:
            return m.group(1).strip()
        m2 = re.search(r"```(?:javascript|js|gs)?[ \t]*\r?\n(.*?)\r?\n?[ \t]*```", t, re.S | re.I)
        if m2:
            return m2.group(1).strip()
        return t

    @classmethod
    def _normalize_mymacro_parsed(cls, parsed, raw_text=""):
        if isinstance(parsed, dict) and parsed.get("code"):
            return {
                "action": "mymacro",
                "code": cls._strip_code_fence(parsed.get("code")),
                "note": str(parsed.get("note") or "").strip(),
            }
        if isinstance(parsed, dict) and parsed.get("action") == "reply" and parsed.get("message"):
            msg = str(parsed.get("message") or "").strip()
            m_full = re.match(r"^```(?:javascript|js|gs)?[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\s*$", msg, re.S | re.I)
            if m_full and re.search(r"(?:^|\n)\s*(?:async\s+)?function\s+[^\s(]+\s*\(", m_full.group(1)):
                return {"action": "mymacro", "code": m_full.group(1).strip(), "note": ""}
            return {"action": "reply", "message": msg}
        raw_s = cls._strip_code_fence(raw_text)
        if raw_s and re.search(r"(?:^|\n)\s*(?:async\s+)?function\s+[^\s(]+\s*\(", raw_s):
            return {"action": "mymacro", "code": raw_s, "note": ""}
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("AI の返答からマイマクロコードを取得できませんでした")

    def _build_mymacro_prompt(self, item):
        mode = item.get("mode") or "add"
        is_edit = mode == "edit"
        ask = item.get("ask") or ""
        ss_name = item.get("ssName") or item.get("ssId") or ""
        sheet = item.get("sheet") or ""
        selection = item.get("selection") or ""
        table = item.get("table")
        sheets = item.get("sheets") or []
        target_name = item.get("targetName") or ""
        existing_code = item.get("existingCode") or ""
        existing_names = item.get("existingNames") or []
        history = item.get("history") or []
        allow_chat = bool(item.get("previewOnly"))

        lines = [
            "※以下が今回の最新状態と会話履歴です。過去の別マクロの会話は無視してください。",
            "【依頼種別】既存マイマクロの相談・修正" if is_edit else "【依頼種別】新規マイマクロの相談・作成",
            "【現在の対象状態】",
            f"ブック: {ss_name or '(不明)'} / シート: {sheet or '(先頭シート)'}",
        ]
        if sheets:
            lines.append("全シート: " + "、".join(sheets))
        if selection:
            lines.append(f"選択範囲: {selection}")
        if table:
            lines.append(
                f"表構造: 見出し {table.get('header_row', 1)}行目・{table.get('first_col', 'A')}〜{table.get('last_col', '?')}列"
                f"・明細 {table.get('data', '')}行"
                + (f"・合計行 {table['total_row']}行目" if table.get("total_row") else "")
            )
            cols = "、".join(
                f"{c.get('col')}={c.get('name')}{'(数値)' if c.get('number') else ''}"
                for c in (table.get("columns") or [])
            )
            if cols:
                lines.append("列: " + cols)
        if is_edit and target_name:
            lines.append(f"\n【修正対象の既存関数名】\n{target_name}")
            if existing_code:
                lines.append(f"【現在のコード（これを要望どおりに書き換えること）】\n{existing_code}")
        else:
            if existing_names:
                lines.append("【既存のマイマクロ名（重複禁止）】\n" + "、".join(str(x) for x in existing_names[:60]))
            if existing_code:
                lines.append(f"\n【現在表示中の下書きコード（これを要望どおりに修正すること）】\n{existing_code}")
        if isinstance(history, list) and history:
            lines.append("\n【これまでの会話】")
            for h in history[-10:]:
                if isinstance(h, dict) and h.get("text"):
                    who = "AI: " if h.get("role") == "ai" else "ユーザー: "
                    lines.append(who + str(h.get("text")))
        finder = self._get_finder()
        lines.append("\n" + gas_ws_find.build_ai_shelf_prompt(finder, ask, kind="sheet", detail_limit=900, top_args=15))
        tail = (
            '質問・相談・改修案の提案なら {"action":"reply","message":"箇条書き3〜5個・200文字以内で簡潔に"}、'
            'コード作成・修正の依頼や合意なら {"action":"mymacro","code":"// 説明\\n// 棚: ...\\nfunction 名前() {\\n  ...\\n}","note":"短い要約"} '
            "の JSON 1個だけを返してください。"
            if allow_chat
            else '必ず {"action":"mymacro","code":"// 説明\\n// 棚: ...\\nfunction 名前() {\\n  ...\\n}","note":"短い要約"} の JSON 1個だけを返してください。'
        )
        lines.append(f"\n【ユーザーの指示】\n{ask}\n\n{tail}")
        return "\n".join(lines)

    def _build_prompt(self, item):
        ask = item.get("ask") or ""
        ss_name = item.get("ssName") or item.get("ssId") or ""
        sheet = item.get("sheet") or ""
        selection = item.get("selection") or ""
        table = item.get("table")
        sheets = item.get("sheets") or []
        is_read_only = (item.get("kind") == "read") or bool(item.get("readOnly"))

        lines = ["【現在の対象状態】", f"ブック: {ss_name} / シート: {sheet}"]
        if sheets:
            lines.append("全シート: " + "、".join(sheets))
        if selection:
            lines.append(f"選択中のセル範囲: {selection}（「ここ」「選択範囲」等の対象）")
        if table:
            hr1 = table.get("header_row")
            hrs = int(table.get("header_rows") or 1)
            hr_s = f"{hr1}-{hr1 + hrs - 1}" if (hr1 and hrs > 1) else f"{hr1}"
            lines.append(
                f"表: 見出し {hr_s}行目・{table.get('first_col')}〜{table.get('last_col')}列"
                f"・明細 {table.get('data')}行目"
                + (f"・合計行 {table['total_row']}行目" if table.get("total_row") else "")
            )
            cols = "、".join(
                f"{c.get('col')}={c.get('name')}{'(数値)' if c.get('number') else ''}"
                for c in (table.get("columns") or [])
            )
            lines.append("列: " + cols)

        if is_read_only:
            snip_txt = str(item.get("tableSnippet") or "").strip()
            if item.get("truncated") and item.get("totalRows"):
                lines.append(f"※全 {item['totalRows']} 行のうち抜粋（先頭80行＋末尾20行）です。")
            if snip_txt:
                lines.append("\n【表の中身（行番号・列記号・値・数式）】\n" + snip_txt)
            lines.append(
                f"\n【ユーザーの質問（読むだけ・シート変更禁止）】\n{ask}\n\n"
                "シートは変更せず、上の表の中身から根拠のセル番地・数値を添えて簡潔に答えてください。"
                '必ず {"action":"reply","message":"..."} の JSON 1個だけを返してください（ops は返さないこと）。'
            )
            return "\n".join(lines)

        snip_txt = str(item.get("tableSnippet") or "").strip()
        if snip_txt:
            if len(snip_txt) > 12000:
                snip_txt = snip_txt[:12000] + "\n...（文字数上限のため一部省略）..."
            if item.get("truncated") and item.get("totalRows"):
                lines.append(f"※全 {item['totalRows']} 行のうち抜粋（先頭80行＋末尾20行）です。")
            lines.append("\n【表の中身（行番号・列記号・値・数式）】\n" + snip_txt)

        finder = self._get_finder()
        partial_ops = item.get("partialOps") if isinstance(item.get("partialOps"), list) else None
        plan_reasons = item.get("planReasons") if isinstance(item.get("planReasons"), list) else None
        plan_missing = item.get("planMissing") if isinstance(item.get("planMissing"), list) else None
        plan_cards = item.get("planCards") if isinstance(item.get("planCards"), list) else None
        if partial_ops is None and plan_reasons is None and plan_missing is None and plan_cards is None and ask:
            try:
                import gas_ws_ask
                p_hint = gas_ws_ask.plan(ask, finder, "sheet", table, sheets, cur_sheet=sheet)
                partial_ops = p_hint.ops or []
                plan_reasons = p_hint.reasons or []
                plan_missing = p_hint.missing or []
                plan_cards = [s.get("name") for s in (p_hint.cards or []) if isinstance(s, dict) and s.get("name")]
            except Exception:
                partial_ops, plan_reasons, plan_missing, plan_cards = [], [], [], []
        hint_lines = []
        if plan_reasons:
            hint_lines.append("止まった理由: " + "／".join(str(x) for x in plan_reasons[:3]))
        if plan_missing:
            hint_lines.append("足りない引数: " + "、".join(str(x) for x in plan_missing[:5]))
        if partial_ops:
            hint_lines.append("組みかけの ops: " + json.dumps(partial_ops, ensure_ascii=False, separators=(",", ":")))
        if plan_cards:
            hint_lines.append("候補の棚: " + "、".join(str(x) for x in plan_cards[:6]))
        if hint_lines:
            lines.append("\n【棚当ての途中結果】\n" + "\n".join(hint_lines))

        base_priority = (
            "seiri", "tidy", "format", "write", "replace", "total", "calc.col", "sort",
            "filter.on", "filter.where", "filter.delete", "filter.extract", "filter.off", "cf.add",
            "width", "freeze", "unfreeze", "dedupe", "banding.add", "banding.remove", "chart.new",
            "rows.delete", "rows.insert", "cols.delete", "sheet.add", "sheet.rename", "sheet.copy",
            "table.new", "validation.list", "summary", "api",
        )
        priority = tuple(dict.fromkeys([str(x) for x in (plan_cards or []) if x] + list(base_priority)))
        lines.append("\n" + gas_ws_find.build_ai_shelf_prompt(finder, ask, kind="sheet", detail_limit=1600, top_args=25, priority_names=priority))
        lines.append(
            f"\n【ユーザーの依頼】\n{ask}\n\n"
            "厳守ルール:\n"
            "・表の見出しに存在しない列名を作らないこと。表の中身を見て正しい列・セル・値を選ぶこと。\n"
            "・頼みに書かれていない余計な操作（勝手な太字・連番・全シート等）を足さないこと。\n"
            "・削除や上書きの棚に ok:true を勝手に付けないこと（承認はユーザー側で行う）。\n"
            "・曖昧・情報不足・対象が特定できない・棚と api でも安全にできないときは、無理に ops を作らず reply で聞き返すこと。\n"
            '必ず {"action":"ops","ops":[{"shelf":"...",...}],"note":"短い要約"} '
            'または {"action":"reply","message":"..."} の JSON 1個だけを返してください。'
        )
        return "\n".join(lines)

    def _ask_via_claude(self, prompt, model=None):
        import ws_window_ai
        eff_model = model or self.model or "sonnet"
        if str(eff_model).startswith("gemini-"):
            eff_model = "sonnet"
        if self._ai_runner is None:
            self._ai_runner = ws_window_ai.GasAiRunner(model=eff_model)
        elif eff_model and self._ai_runner.model != eff_model:
            self._ai_runner.set_model(eff_model)
        raw = self._ai_runner.session.ask(prompt)
        return ws_window_ai._parse_ai_json(raw)

    def _ask_mymacro_via_claude(self, prompt, model=None):
        import queue
        import threading
        import ws_window_ai
        eff_model = model or self.model or "sonnet"
        if str(eff_model).startswith("gemini-"):
            eff_model = "sonnet"
        sys_prompt = self._MYMACRO_SYSTEM_PROMPT

        class _MyMacroSession(ws_window_ai._HeadlessClaudeSession):
            def start(self_s):
                if self_s.alive():
                    return
                exe = shutil.which("claude")
                if not exe:
                    raise RuntimeError("claude コマンドが見つかりません（Claude Code をインストールしてログインしてください）。")
                cmd = [exe] + ws_window_ai._CC_ARGS + ["--model", self_s.model, "--system-prompt", sys_prompt]
                kwargs = {
                    "cwd": ws_window_ai._neutral_cwd(),
                    "stdin": subprocess.PIPE,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                self_s.err = []
                self_s.lines = queue.Queue()
                self_s.proc = subprocess.Popen(cmd, **kwargs)
                threading.Thread(target=self_s._pump, args=(self_s.proc.stdout, self_s.lines), daemon=True).start()
                threading.Thread(target=self_s._pump, args=(self_s.proc.stderr, None), daemon=True).start()

        if self._mymacro_session is None or self._mymacro_session.model != eff_model:
            if self._mymacro_session is not None:
                self._mymacro_session.close()
            self._mymacro_session = _MyMacroSession(model=eff_model)
        raw = self._mymacro_session.ask(prompt)
        try:
            parsed = ws_window_ai._parse_ai_json(raw)
        except Exception:
            parsed = None
        return self._normalize_mymacro_parsed(parsed, raw_text=raw)

    def resolve_item(self, item):
        """1 件のローカル直結 / 郵便受けリクエストを公式 Claude Code CLI で解釈し、結果を返す。"""
        req_id = item.get("reqId")
        req_model = str(item.get("aiModel") or self.model or "").strip()
        # ローカル直結は Claude Code だけ＝Claude の名前以外（gemini_hydrogen 等の古い設定）は Sonnet で答える
        if not re.match(r"^(sonnet|opus|haiku|claude-[\w.-]+)$", req_model):
            req_model = "sonnet"
        if item.get("kind") == "mymacro":
            prompt = self._build_mymacro_prompt(item)
            meta = {
                "reqId": req_id,
                "kind": "mymacro",
                "mode": item.get("mode") or "add",
                "previewOnly": bool(item.get("previewOnly")),
                "targetName": item.get("targetName") or "",
                "existingCode": item.get("existingCode") or "",
                "existingNames": item.get("existingNames") or [],
                "myId": item.get("myId") or "",
                "ssId": item.get("ssId") or "",
                "ask": item.get("ask") or "",
            }
            try:
                parsed = self._ask_mymacro_via_claude(prompt, model=req_model or "sonnet")
                parsed = self._normalize_mymacro_parsed(parsed)
                action = parsed.get("action") or ("mymacro" if parsed.get("code") else "reply")
                return dict(
                    meta,
                    action=action,
                    code=parsed.get("code") or "",
                    note=parsed.get("note") or "",
                    message=parsed.get("message") or "",
                )
            except Exception as e:
                return dict(meta, action="error", error=str(e))

        is_read_only = (item.get("kind") == "read") or bool(item.get("readOnly"))
        # 直す・作る頼みで棚当てが撃てなかった物は、GAS マネージャーの脳（ws_agent＝Excel マネージャーの agent の写し）に回す。
        # 脳が材料を読み、先撃ち・AI・撃つ・関所まで回して、シートはその場で直る。サイドバーには報告の文を返す（11/27 シュウさん「つないで」）。
        # 拡張が 65 秒で待ちを切るので、待てる秒は 55 秒・採点は時間が余るときだけ。aiMode="quick" なら前の 1 回聞きの道。
        if (not is_read_only and item.get("ssId") and str(item.get("kind") or "sheet") in ("", "sheet", "ops")
                and str(item.get("aiMode") or "").lower() != "quick" and os.environ.get("GAS_COMBO_AGENT", "1") != "0"):
            try:
                import gas_workspace
                import gas_ws_agent
                mgr = gas_workspace.WorkspaceManager(client=self.client) if getattr(self, "client", None) else gas_workspace.WorkspaceManager()
                mgr.timing = False
                ag = gas_ws_agent.Agent(mgr, model=req_model or "sonnet", max_turns=3, grade=True, budget_sec=55)
                report = ag.run(item.get("ask") or "", target=item.get("ssId"), sheet=item.get("sheet") or "")
                return {"reqId": req_id, "action": "reply", "ops": [], "note": "", "message": report, "agent": True}
            except Exception as e:
                print(f"[{self._ts_now()}][agent] 脳で回せませんでした（前の 1 回聞きの道に戻します）: {e}")
        prompt = self._build_prompt(item)
        try:
            parsed = self._ask_via_claude(prompt, model=req_model or "sonnet")
            if is_read_only:
                # 守り: 読むだけの道で AI が ops を返してもコード側で必ず捨てて撃たない
                msg = str(parsed.get("message") or parsed.get("note") or "").strip()
                if not msg:
                    msg = "読むだけの質問のためシートは変更しませんでした。"
                if item.get("truncated") and item.get("totalRows"):
                    trunc_note = f"※全 {item['totalRows']} 行のうち抜粋（先頭80行＋末尾20行）で読みました"
                    if "抜粋" not in msg:
                        msg = msg + "\n" + trunc_note
                return {
                    "reqId": req_id,
                    "action": "reply",
                    "ops": [],
                    "note": "",
                    "message": msg,
                }
            action = parsed.get("action") or ("ops" if parsed.get("ops") else "reply")
            raw_ops = parsed.get("ops") or []
            # 守り: AI が勝手に ok:true を付けても必ず剥ぎ取る（承認スキップ防止）
            clean_ops = [{k: v for k, v in o.items() if k != "ok"} if isinstance(o, dict) else o for o in raw_ops] if isinstance(raw_ops, list) else []
            return {
                "reqId": req_id,
                "action": action,
                "ops": clean_ops,
                "note": parsed.get("note") or "",
                "message": parsed.get("message") or "",
            }
        except Exception as e:
            return {"reqId": req_id, "action": "error", "error": str(e)}

    @staticmethod
    def _validate_mymacro_code_local(mode, code, existing_names=None):
        """直結ルート用: マイマクロコードの関数定義・重複をローカルで検証する。"""
        clean = ComboPostboxWatcher._strip_code_fence(code).replace("\r\n", "\n").rstrip()
        if not clean:
            return {"ok": False, "retryable": True, "error": "AI が空のコードを返しました"}
        fns = [
            m.group(1)
            for m in re.finditer(r"(?:^|\n)function\s+([^\s(]+)\s*\(", clean)
            if not m.group(1).endswith("_")
        ]
        if not fns:
            return {
                "ok": False,
                "retryable": True,
                "code": clean,
                "error": "インデントなしの関数定義（function 名前() { ... }、末尾 _ なし）が見つかりません",
            }
        if mode != "edit" and existing_names:
            name_set = {str(x or "") for x in existing_names}
            for fn in fns:
                if fn in name_set:
                    return {
                        "ok": False,
                        "retryable": True,
                        "code": clean,
                        "error": f"同じ名前のマイマクロ「{fn}」が既にあります。別の関数名にしてください",
                    }
        return {"ok": True, "code": clean, "name": fns[0], "names": fns}

    def _validate_ops_local(self, ops, ask=None, table=None):
        """直結・郵便受け共通: AI が返した ops をカタログ検査＋棚と同じ守り(_audit_built_op)に通す。"""
        if not isinstance(ops, list) or not ops:
            return {"ok": False, "ops": [], "error": "ops が空または配列ではありません"}
        finder = self._get_finder()
        cat = finder.cat
        sanitized = []
        for i, raw_op in enumerate(ops, 1):
            if not isinstance(raw_op, dict) or not isinstance(raw_op.get("shelf"), str) or not raw_op.get("shelf").strip():
                return {"ok": False, "ops": [], "error": f"{i} 番目の ops に 'shelf'（棚の名前）がありません"}
            op = {k: v for k, v in raw_op.items() if k != "ok"}
            name = op["shelf"]
            if not cat.spec(name):
                near = finder.near(name)
                return {"ok": False, "ops": [], "error": f"棚「{name}」はありません（{i} 番目）。" + ("\n" + near if near else "")}
            msg = cat.check_op(i, op) or (gas_ws_catalog.EXTRA_CHECKS[name](op) if name in gas_ws_catalog.EXTRA_CHECKS else None)
            if msg:
                s = cat.by_name[name]
                card = "\n".join(finder.card(s))
                return {"ok": False, "ops": [], "error": f"{msg}\nその棚の札:\n{card}\n   引数: {s['args_raw']}"}
            sanitized.append(op)
        import gas_ws_ask
        aud = gas_ws_ask.audit_ai_ops(sanitized, ask or "", finder, table=table)
        if not aud.get("ok"):
            return {
                "ok": False,
                "ops": [],
                "error": "守りの監査で止まりました: " + " ／ ".join(aud.get("issues") or ["不明な不備"]),
            }
        sanitized = aud.get("ops") or sanitized
        return {"ok": True, "ops": sanitized}

    @staticmethod
    def _extract_recorded_macros_from_files(files):
        """GAS プロジェクトのファイル一覧から、記録マクロ候補（トップレベル関数）を抽出する。"""
        if not isinstance(files, list):
            return []
        skip_names = {"onOpen", "onEdit", "onInstall", "doGet", "doPost", "showGasComboSidebar"}

        def _file_priority(f):
            nm = str((f or {}).get("name") or "").lower()
            if nm in ("macros", "macro", "マクロ"):
                return 0
            if "macro" in nm or "マクロ" in nm:
                return 1
            return 2

        js_files = [f for f in files if isinstance(f, dict) and f.get("type") == "SERVER_JS" and f.get("source")]
        js_files.sort(key=_file_priority)

        out = []
        seen_names = set()
        fn_re = re.compile(r"(?:^|\n)(?:async\s+)?function\s+([^\s(]+)\s*\([^)]*\)\s*\{")
        for f in js_files:
            fname = str(f.get("name") or "")
            src = str(f.get("source") or "").replace("\r\n", "\n")
            for m in fn_re.finditer(src):
                fn_name = m.group(1).strip()
                if not fn_name or fn_name.endswith("_") or fn_name in skip_names or fn_name.startswith("combo"):
                    continue
                if fn_name in seen_names:
                    continue
                # 直上の連続コメントも含めて開始位置を決める
                def_start = m.start() + (1 if src[m.start()] == "\n" else 0)
                start = def_start
                while start > 0:
                    prev_nl = src.rfind("\n", 0, start - 1)
                    line_start = 0 if prev_nl < 0 else prev_nl + 1
                    prev_line = src[line_start:start - 1]
                    if re.match(r"^\s*//", prev_line):
                        start = line_start
                    else:
                        break
                # ブレースの対応で関数末尾を特定
                i = m.end() - 1
                n = len(src)
                depth = 0
                in_str = ""
                in_line_com = False
                in_blk_com = False
                end = n
                while i < n:
                    ch = src[i]
                    nx = src[i + 1] if i + 1 < n else ""
                    if in_line_com:
                        if ch == "\n":
                            in_line_com = False
                        i += 1
                        continue
                    if in_blk_com:
                        if ch == "*" and nx == "/":
                            in_blk_com = False
                            i += 2
                            continue
                        i += 1
                        continue
                    if in_str:
                        if ch == "\\":
                            i += 2
                            continue
                        if ch == in_str:
                            in_str = ""
                        i += 1
                        continue
                    if ch == "/" and nx == "/":
                        in_line_com = True
                        i += 2
                        continue
                    if ch == "/" and nx == "*":
                        in_blk_com = True
                        i += 2
                        continue
                    if ch in ("'", '"', "`"):
                        in_str = ch
                        i += 1
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                    i += 1
                code_block = src[start:end].strip()
                if code_block:
                    seen_names.add(fn_name)
                    out.append({"name": fn_name, "file": fname, "code": code_block})
        return out

    def fetch_recorded_macros(self, item, state_path=None):
        """スプレッドシート付属の記録マクロ（macros.gs 等）を Apps Script API から取得して返す。"""
        ss_id = str((item or {}).get("ssId") or "").strip()
        script_id = str((item or {}).get("scriptId") or "").strip()
        st, spath = _load_combo_state(state_path)
        rec_map = st.get("recorded_scripts") if isinstance(st.get("recorded_scripts"), dict) else {}
        sheets_map = st.get("sheets") if isinstance(st.get("sheets"), dict) else {}

        known_id = str(rec_map.get(ss_id) or sheets_map.get(ss_id) or "").strip() if ss_id else ""
        if script_id and script_id != known_id:
            # 頼みに付いてきた scriptId は、そのシートに紐づく Apps Script のときだけ使う（別のプロジェクトのコードを読ませない）
            if not ss_id:
                script_id = ""
            else:
                try:
                    bound = self.client._get_bound_spreadsheet_id(script_id)
                except Exception:
                    bound = None
                if bound != ss_id:
                    script_id = ""
        if not script_id:
            script_id = known_id

        if not script_id:
            return {
                "ok": False,
                "direct": True,
                "needsEditor": True,
                "error": (
                    "このシートの Apps Script がまだ紐付いていません。"
                    "シートのメニュー「拡張機能 → Apps Script」を 1 回開いてから、"
                    "もう一度「🎬記録取込」を押してください（コピペ不要です）。"
                ),
            }

        if ss_id and rec_map.get(ss_id) != script_id:
            rec_map[ss_id] = script_id
            st["recorded_scripts"] = rec_map
            _save_combo_state(st, spath)

        try:
            content = self.client.get_content(script_id, use_cache=False) or {}
        except Exception as e:
            return {
                "ok": False,
                "direct": True,
                "scriptId": script_id,
                "error": f"Apps Script（{script_id}）の取得に失敗しました: {e}",
            }

        macros = self._extract_recorded_macros_from_files(content.get("files") or [])
        if not macros:
            return {
                "ok": False,
                "direct": True,
                "scriptId": script_id,
                "error": "記録されたマクロ関数が見つかりません。先にスプレッドシートで「拡張機能 → マクロ → マクロを記録」を行って保存してください。",
            }
        return {"ok": True, "direct": True, "scriptId": script_id, "macros": macros}

    def resolve_direct(self, item, on_event=None):
        """Chrome 拡張からの直結リクエスト（127.0.0.1 /resolve）を処理して返す。"""
        if isinstance(item, dict) and item.get("kind") == "ai_solved":
            try:
                import gas_ws_ask
                gas_ws_ask.log_ask_ai_solved(
                    item.get("ask") or "",
                    item.get("ops") or [],
                    source=str(item.get("source") or "combo_direct"),
                    note=str(item.get("note") or ""),
                )
            except Exception:
                pass
            return {"ok": True, "direct": True, "logged": True}

        def _emit(ev):
            if callable(on_event):
                try:
                    on_event(ev)
                except Exception:
                    pass

        t0 = time.perf_counter()
        _emit({"type": "status", "message": "AI に問い合わせ中…"})
        with self._ai_lock:
            payload = self.resolve_item(item)
        if item.get("kind") != "mymacro" and payload.get("action") == "ops":
            val_ops = self._validate_ops_local(payload.get("ops"), ask=item.get("ask"), table=item.get("table"))
            if val_ops.get("ok"):
                payload["ops"] = val_ops.get("ops") or payload.get("ops")
            else:
                _emit({"type": "status", "message": "検証・監査エラーを検出・AI に修正依頼中…"})
                retry_item = dict(
                    item,
                    ask=str(item.get("ask") or "")
                    + "\n（前の答えの ops は守りの検査で止まりました: "
                    + str(val_ops.get("error") or "")
                    + "。表にある列名と頼みに合う棚・引数だけで直し、安全にできない・曖昧なら reply で聞き返してください）",
                )
                with self._ai_lock:
                    payload = self.resolve_item(retry_item)
                if payload.get("action") == "ops":
                    val_ops2 = self._validate_ops_local(payload.get("ops"), ask=item.get("ask"), table=item.get("table"))
                    if val_ops2.get("ok"):
                        payload["ops"] = val_ops2.get("ops") or payload.get("ops")
                    else:
                        payload = {"action": "error", "error": val_ops2.get("error") or "ops の検証・監査に失敗しました"}
        if item.get("kind") == "mymacro" and payload.get("action") == "mymacro":
            mode = item.get("mode") or "add"
            existing_names = item.get("existingNames") or []
            val = self._validate_mymacro_code_local(mode, payload.get("code") or "", existing_names)
            if not val.get("ok") and val.get("retryable"):
                _emit({"type": "status", "message": "検証エラーを検出・AI に修正依頼中…"})
                retry_item = dict(
                    item,
                    ask=str(item.get("ask") or "")
                    + "\n（前の答えは失敗しました: "
                    + str(val.get("error") or "")
                    + "。問題点を直して答え直してください）",
                )
                with self._ai_lock:
                    payload = self.resolve_item(retry_item)
                if payload.get("action") == "mymacro":
                    val = self._validate_mymacro_code_local(mode, payload.get("code") or "", existing_names)
            if payload.get("action") == "mymacro":
                if val.get("ok"):
                    payload["code"] = val["code"]
                    payload["name"] = val["name"]
                else:
                    payload["action"] = "error"
                    payload["error"] = val.get("error") or "マイマクロの検証に失敗しました"
        ai_ms = int((time.perf_counter() - t0) * 1000)
        act = payload.get("action") or ""
        if act == "error":
            res = {
                "ok": False,
                "direct": True,
                "action": "error",
                "error": str(payload.get("error") or "AI 処理に失敗しました"),
                "aiMs": ai_ms,
            }
        else:
            res = dict(payload, ok=True, direct=True, aiMs=ai_ms)
            if item.get("kind") == "mymacro":
                res["previewOnly"] = bool(item.get("previewOnly", True))
                res["saved"] = False
                if act == "reply":
                    res["text"] = res.get("message") or ""
                elif act == "mymacro":
                    note_s = f"（{res.get('note')}）" if res.get("note") else ""
                    res["text"] = f"✨ コード案ができました（{res.get('name') or ''}）。「決定して保存」で登録されます{note_s}"
        self._last_ai_ms = ai_ms
        self._last_error = "" if res.get("ok") else str(res.get("error") or "")
        print(
            f"[{self._ts_now()}][direct] kind={item.get('kind') or 'ops'} "
            f"model={item.get('aiModel') or self.model or 'auto'} action={act} ai={ai_ms}ms ok={res.get('ok')}"
        )
        return res

    def poll_once(self):
        """1 回ポーリングして保留中のリクエストをすべて処理する。"""
        if self._last_http_at and (time.monotonic() - self._last_http_at) >= 20.0:
            self._close_idle_http_pool()
        t_poll = time.perf_counter()
        poll_resp = self.client.run_function(self.sid, "comboPostboxPoll", [], fast=True, keep_runner=True, force=True, timeout=7)
        self._last_http_at = time.monotonic()
        poll_wall_ms = int((time.perf_counter() - t_poll) * 1000)
        poll_gas_ms = int((poll_resp.get("elapsed_ms") or poll_resp.get("duration_ms") or 0) if isinstance(poll_resp, dict) else 0)
        data = _unwrap_run_result(poll_resp, client=self.client, sid=self.sid) or {}
        queue_items = data.get("queue") or []
        results = []
        for item in queue_items:
            t_ai = time.perf_counter()
            with self._ai_lock:
                payload = self.resolve_item(item)
            if item.get("kind") != "mymacro" and payload.get("action") == "ops":
                val_pb = self._validate_ops_local(payload.get("ops"), ask=item.get("ask"), table=item.get("table"))
                if val_pb.get("ok"):
                    payload["ops"] = val_pb.get("ops") or payload.get("ops")
                else:
                    retry_pb = dict(
                        item,
                        ask=str(item.get("ask") or "")
                        + "\n（前の答えの ops は守りの検査で止まりました: "
                        + str(val_pb.get("error") or "")
                        + "。表にある列名と頼みに合う棚・引数だけで直し、安全にできない・曖昧なら reply で聞き返してください）",
                    )
                    with self._ai_lock:
                        payload = self.resolve_item(retry_pb)
                    if payload.get("action") == "ops":
                        val_pb2 = self._validate_ops_local(payload.get("ops"), ask=item.get("ask"), table=item.get("table"))
                        if val_pb2.get("ok"):
                            payload["ops"] = val_pb2.get("ops") or payload.get("ops")
                        else:
                            payload = {"reqId": item.get("reqId"), "action": "error", "error": val_pb2.get("error") or "ops の検証・監査に失敗しました"}
            ai_ms = int((time.perf_counter() - t_ai) * 1000)
            t_deliv = time.perf_counter()
            deliv_resp = self.client.run_function(
                self.sid, "comboPostboxDeliver", [payload], fast=True, keep_runner=True, force=True, timeout=15
            )
            self._last_http_at = time.monotonic()
            deliv_wall_ms = int((time.perf_counter() - t_deliv) * 1000)
            deliv = _unwrap_run_result(deliv_resp, client=self.client, sid=self.sid)
            deliv_gas_ms = int(
                ((deliv.get("gasMs") if isinstance(deliv, dict) and deliv.get("gasMs") is not None else None)
                 or (deliv_resp.get("elapsed_ms") or deliv_resp.get("duration_ms") if isinstance(deliv_resp, dict) else 0)
                 or 0)
            )
            # 棚の引数不足、またはマイマクロ構文/重複エラーなら、その理由を添えて AI に 1 回だけ作り直させる
            if isinstance(deliv, dict) and deliv.get("ok") is False and (deliv.get("arg") or deliv.get("retryable")):
                retry_item = dict(
                    item,
                    ask=str(item.get("ask") or "")
                    + "\n（前の答えは失敗しました: "
                    + str(deliv.get("error") or "")
                    + "。問題点を直して答え直してください）",
                )
                t_ai2 = time.perf_counter()
                with self._ai_lock:
                    payload = self.resolve_item(retry_item)
                ai_ms += int((time.perf_counter() - t_ai2) * 1000)
                for k in ("ssId", "sheet", "selection", "ok", "backup", "kind", "mode", "previewOnly", "targetName", "existingCode", "existingNames", "myId", "ask"):
                    if item.get(k) is not None and (k == "ask" or k not in payload):
                        payload[k] = item.get(k)
                t_deliv2 = time.perf_counter()
                deliv_resp2 = self.client.run_function(
                    self.sid, "comboPostboxDeliver", [payload], fast=True, keep_runner=True, force=True, timeout=15
                )
                self._last_http_at = time.monotonic()
                deliv_wall_ms += int((time.perf_counter() - t_deliv2) * 1000)
                deliv = _unwrap_run_result(deliv_resp2, client=self.client, sid=self.sid)
                deliv_gas_ms += int(
                    ((deliv.get("gasMs") if isinstance(deliv, dict) and deliv.get("gasMs") is not None else None)
                     or (deliv_resp2.get("elapsed_ms") or deliv_resp2.get("duration_ms") if isinstance(deliv_resp2, dict) else 0)
                     or 0)
                )
            if isinstance(deliv, dict) and deliv.get("ok") is True and payload.get("action") == "ops" and payload.get("ops"):
                try:
                    import gas_ws_ask
                    gas_ws_ask.log_ask_ai_solved(
                        item.get("ask") or "",
                        payload.get("ops"),
                        source="combo_postbox",
                        note=payload.get("note") or "",
                    )
                except Exception:
                    pass
            timing = {
                "poll_wall_ms": poll_wall_ms,
                "poll_gas_ms": poll_gas_ms,
                "ai_ms": ai_ms,
                "deliver_wall_ms": deliv_wall_ms,
                "deliver_gas_ms": deliv_gas_ms,
                "total_ms": poll_wall_ms + ai_ms + deliv_wall_ms,
            }
            results.append({"reqId": item.get("reqId"), "payload": payload, "deliver": deliv, "timing": timing})
        return results

    def watch(self, max_loops=None, idle_interval=15.0, direct_only=False, port=None, pid_path=None):
        """継続監視・直結サーバー。direct_only=True のときは GAS 郵便受けポーリングを行わず /resolve のみ待つ。
        /stop を受けると安全に終了し、新コードへの再起動に備える。"""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        listen_port = COMBO_WATCH_PORT if port is None else int(port)
        pid_file = Path(pid_path) if pid_path else WATCH_PID_PATH
        self._direct_only = bool(direct_only)
        self._started_at = time.time()
        # 窓なし（pythonw）で起きたときは標準出力が無い＝書き先を手元のログにする（無いと途中で黙って止まる）
        if sys.stdout is None or sys.stderr is None or Path(sys.executable).name.lower() == "pythonw.exe":
            _log = _open_watch_log()
            sys.stdout = sys.stderr = _log

        already, active_pid = _is_watch_running(pid_file, listen_port)
        if already:
            print(f"[{self._ts_now()}][postbox] 受け手は既に稼働中です pid={active_pid} (127.0.0.1:{listen_port})")
            return

        kick = threading.Event()
        stop_ev = threading.Event()
        watcher = self

        allowed_ext_origin = f"chrome-extension://{EXT_FIXED_ID}"

        class _H(BaseHTTPRequestHandler):
            def _origin_ok(self):
                # ブラウザからは固定の GASコンボ拡張機能のみ許可し、一般の外部 Web サイトからの無断アクセスを拒否する
                o = str(self.headers.get("Origin") or "").strip()
                if o:
                    return o == allowed_ext_origin
                # Origin なしでもブラウザ発（<img src=…/stop> 等）は Sec-Fetch-Site で見分けて断る。手元の CLI・Python は送らない
                sfs = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                return sfs in ("", "none")

            def _send_cors(self):
                o = str(self.headers.get("Origin") or "").strip()
                if o and o == allowed_ext_origin:
                    self.send_header("Access-Control-Allow-Origin", o)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Private-Network", "true")

            def _reply(self, data=None, code=200):
                self.send_response(code)
                self._send_cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                body = data if data is not None else {"ok": True, "pid": os.getpid()}
                self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

            def do_OPTIONS(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                self._reply()

            def do_GET(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                if self.path.startswith("/stop"):
                    stop_ev.set()
                    kick.set()
                    self._reply()
                elif self.path.startswith("/kick"):
                    kick.set()
                    self._reply()
                elif self.path.startswith("/health"):
                    self._reply(watcher.get_health())
                elif self.path.startswith("/ping"):
                    self._reply({"ok": True, "pid": os.getpid(), "direct": True, "directOnly": bool(direct_only)})
                else:
                    self._reply()

            def do_POST(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                if self.path.startswith("/sync") or self.path.startswith("/resolve-stream") or self.path.startswith("/resolve") or self.path.startswith("/recorded-macros"):
                    try:
                        raw_len = self.headers.get("Content-Length") or "0"
                        length = int(raw_len)
                    except Exception:
                        length = 0
                    if length <= 0 or length > 512 * 1024:
                        self._reply({"ok": False, "direct": True, "error": "リクエスト本文が空または大きすぎます"}, code=400)
                        return
                    try:
                        raw_body = self.rfile.read(length).decode("utf-8")
                        item = json.loads(raw_body)
                    except Exception as e:
                        self._reply({"ok": False, "direct": True, "error": f"JSON 解析エラー: {e}"}, code=400)
                        return
                    if not isinstance(item, dict):
                        self._reply({"ok": False, "direct": True, "error": "リクエストは JSON オブジェクトである必要があります"}, code=400)
                        return
                    if self.path.startswith("/sync"):
                        try:
                            import gas_ws_browser
                            gas_ws_browser.save_browser_active(item, source="combo-watch")
                        except Exception:
                            pass
                        self._reply({"ok": True}, code=200)
                        return
                    if self.path.startswith("/resolve-stream"):
                        self.send_response(200)
                        self._send_cors()
                        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()

                        _wlock = threading.Lock()

                        def _emit_ndjson(ev_obj):
                            try:
                                line = (json.dumps(ev_obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")
                                with _wlock:
                                    self.wfile.write(line)
                                    self.wfile.flush()
                            except Exception:
                                pass

                        _emit_ndjson({"type": "status", "message": "AI が考えています…"})
                        # 考えている間も 5 秒ごとに知らせる（画面に経過が出る・画面側の待ち時計が巻き直る）
                        _beat_stop = threading.Event()
                        _t_beat = time.perf_counter()

                        def _beat():
                            while not _beat_stop.wait(5.0):
                                _emit_ndjson({"type": "status", "message": f"AI が考えています…（{int(time.perf_counter() - _t_beat)} 秒）"})

                        threading.Thread(target=_beat, daemon=True).start()
                        try:
                            res = watcher.resolve_direct(item, on_event=_emit_ndjson)
                            _beat_stop.set()
                            preview = str(res.get("message") or res.get("text") or res.get("note") or "").strip()
                            if preview:
                                _emit_ndjson({"type": "delta", "text": preview})
                            _emit_ndjson({"type": "done", "result": res})
                        except Exception as e:
                            _beat_stop.set()
                            _emit_ndjson({"type": "done", "result": {"ok": False, "direct": True, "action": "error", "error": str(e)}})
                        return
                    try:
                        if self.path.startswith("/recorded-macros"):
                            res = watcher.fetch_recorded_macros(item)
                        else:
                            res = watcher.resolve_direct(item)
                        self._reply(res, code=200)
                    except Exception as e:
                        self._reply({"ok": False, "direct": True, "action": "error", "error": str(e)}, code=500)
                    return
                self.do_GET()

            def log_message(self, *a):
                pass

        try:
            class _Srv(ThreadingHTTPServer):
                allow_reuse_address = False   # Windows では True だと同じ口に 2 つ目も入れてしまう＝受け手が 2 つ動く
            srv = _Srv(("127.0.0.1", listen_port), _H)
        except OSError:
            print(f"[{self._ts_now()}][postbox] 受け手はもう動いています（127.0.0.1:{listen_port}）")
            return
        try:
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        if direct_only:
            print(f"[{self._ts_now()}][direct] 直結専用サーバー起動 pid={os.getpid()} port={listen_port} (郵便受けポーリング停止)")
        else:
            print(f"[{self._ts_now()}][postbox] 監視開始 pid={os.getpid()} port={listen_port} idle={idle_interval}s")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        loops = 0
        consec_err = 0
        try:
            if direct_only:
                while not stop_ev.is_set():
                    if kick.wait(0.5):
                        kick.clear()
                        try:
                            self.poll_once()
                        except Exception:
                            pass
            else:
                while (max_loops is None or loops < max_loops) and not stop_ev.is_set():
                    loops += 1
                    last_err = False
                    t_loop = time.perf_counter()
                    try:
                        handled = self.poll_once()
                        consec_err = 0
                    except Exception as e:
                        handled = []
                        last_err = True
                        consec_err += 1
                        err_ms = int((time.perf_counter() - t_loop) * 1000)
                        err_s = str(e)
                        is_timeout = isinstance(e, TimeoutError) or ("timed out" in err_s.lower()) or ("タイムアウト" in err_s)
                        print(f"[{self._ts_now()}][postbox] poll失敗 wall={err_ms}ms 連続{consec_err}回 timeout={is_timeout}: {err_s[:200]}")
                        self._close_idle_http_pool()
                        if not (is_timeout and consec_err < 3):
                            try:
                                from gas_client import GasClient
                                self.client = GasClient()
                                self.client._cache_data.get("deployments", {}).get(self.sid, {}).pop("runner_installed", None)
                            except Exception as e2:
                                print(f"[{self._ts_now()}][postbox] 作り直しに失敗: {e2}")
                    for h in handled:
                        tm = h.get("timing") or {}
                        print(
                            f"[{self._ts_now()}][postbox] {h['reqId']} "
                            f"poll={tm.get('poll_wall_ms', 0)}ms(gas={tm.get('poll_gas_ms', 0)}ms) "
                            f"ai={tm.get('ai_ms', 0)}ms "
                            f"deliver={tm.get('deliver_wall_ms', 0)}ms(gas={tm.get('deliver_gas_ms', 0)}ms) "
                            f"total={tm.get('total_ms', 0)}ms -> {json.dumps(h['deliver'], ensure_ascii=False)}"
                        )
                    if (max_loops is not None and loops >= max_loops) or stop_ev.is_set():
                        break
                    wait_sec = 0.5 if (last_err and consec_err <= 2) else (2.0 if last_err else idle_interval)
                    kick.wait(wait_sec)
                    if stop_ev.is_set():
                        break
                    if kick.is_set():
                        kick.clear()
                        time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            srv.shutdown()
            try:
                srv.server_close()
            except Exception:
                pass
            try:
                if pid_file.is_file() and pid_file.read_text(encoding="utf-8", errors="ignore").strip() == str(os.getpid()):
                    pid_file.unlink()
            except Exception:
                pass
            if self._ai_runner is not None:
                self._ai_runner.close()
            if self._mymacro_session is not None:
                self._mymacro_session.close()


def _open_watch_log(log_path=None, max_bytes=512 * 1024, keep_bytes=128 * 1024):
    """受け手ログ (.combo_watch.log) をサイズ上限付きで開く（肥大化防止のため超過時は末尾のみ残す）。"""
    p = Path(log_path) if log_path else (HERE / ".combo_watch.log")
    try:
        if p.exists() and p.stat().st_size > max_bytes:
            raw = p.read_bytes()
            tail = raw[-keep_bytes:]
            nl = tail.find(b"\n")
            if nl >= 0 and nl + 1 < len(tail):
                tail = tail[nl + 1:]
            p.write_bytes(tail)
    except Exception:
        pass
    return open(p, "a", encoding="utf-8", buffering=1)


COMBO_WATCH_PORT = 18766
COMBO_WATCH_VERSION = "4.0"
WATCH_PID_PATH = HERE / ".combo_watch.pid"
NATIVE_HOST_NAME = "com.shu.gas_combo_host"
EXT_FIXED_ID = "mbkcmenmaeaiemdppphmbokhbfckpjhm"


def _is_watch_running(pid_path=None, port=None):
    """PID ファイルと /ping でローカル受け手の実生存を確認する。古い PID ファイルは掃除する。"""
    import urllib.request
    p = Path(pid_path) if pid_path else WATCH_PID_PATH
    listen_port = COMBO_WATCH_PORT if port is None else int(port)
    pid_val = None
    if p.is_file():
        try:
            pid_val = int(p.read_text(encoding="utf-8", errors="ignore").strip())
        except Exception:
            pid_val = None
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{listen_port}/ping", timeout=0.35).read().decode("utf-8", "ignore")
        info = json.loads(raw or "{}")
        if isinstance(info, dict) and info.get("ok"):
            return True, info.get("pid") or pid_val
    except Exception:
        pass
    if p.is_file():
        try:
            p.unlink()
        except Exception:
            pass
    return False, None


BRIDGE_TOKEN_PATH = HERE / ".combo_bridge_token"


def ensure_bridge_token(window_json=None):
    """拡張の直結の合い言葉を用意し、拡張のフォルダ（combo_window.json）にも書く。
    操作窓は同じ合い言葉を人ごとの設定（UserProperties）から受け取り、拡張は合わない頼みを中継しない
    ＝ほかの人のアドオンの窓から直結 AI を呼ばせない。合い言葉は手元にだけ置く（.gitignore 済み・公開しない）。"""
    import secrets
    tok = ""
    try:
        tok = BRIDGE_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        tok = ""
    if not re.match(r"^[A-Za-z0-9_-]{32,}$", tok):
        tok = secrets.token_urlsafe(32)
        BRIDGE_TOKEN_PATH.write_text(tok, encoding="utf-8")
    wpath = Path(window_json) if window_json else HERE / "ws_browser_ext" / "combo_window.json"
    try:
        cur = json.loads(wpath.read_text(encoding="utf-8")) if wpath.exists() else {}
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    if cur.get("token") != tok:
        cur["token"] = tok
        try:
            wpath.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return tok


def deliver_bridge_token(client, addon_sid, st, spath):
    """合い言葉を操作窓（アドオン経由で人ごとの設定）へ渡す。渡し済みなら何もしない。"""
    tok = ensure_bridge_token()
    import hashlib
    h = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16]
    if not addon_sid or st.get("bridge_token_sent") == h:
        return False
    client.run_function(addon_sid, "comboSaveConfig", [{"bridgeToken": tok}], fast=True, force=True, timeout=30)
    st["bridge_token_sent"] = h
    try:
        Path(spath).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return True


def install_native_host(extra_ext_ids=None):
    """Chrome / Edge 等の拡張機能からローカル受け手を自動起動できるよう、Native Messaging Host を登録する（HKCU・管理者権限不要）。"""
    if os.name != "nt":
        return {"ok": False, "text": "Native Messaging の自動登録は Windows のみ対応です"}
    import winreg
    py_exe = str(Path(sys.executable).with_name("python.exe"))
    if not Path(py_exe).exists():
        py_exe = sys.executable
    host_py = str(HERE / "native_host.py")
    bat_path = HERE / ".native_host.bat"
    manifest_path = HERE / ".native_host_manifest.json"
    origins = [f"chrome-extension://{EXT_FIXED_ID}/"]
    for eid in (extra_ext_ids or []):
        eid_s = str(eid or "").strip()
        if eid_s:
            orig = f"chrome-extension://{eid_s}/"
            if orig not in origins:
                origins.append(orig)
    try:
        bat_path.write_text(f'@echo off\r\nchcp 65001 >nul\r\n"{py_exe}" "{host_py}" %*\r\n', encoding="utf-8")
        manifest = {
            "name": NATIVE_HOST_NAME,
            "description": "GASコンボ ローカル AI 受け手 自動起動ホスト",
            "path": str(bat_path),
            "type": "stdio",
            "allowed_origins": origins,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        reg_paths = [
            rf"Software\Google\Chrome\NativeMessagingHosts\{NATIVE_HOST_NAME}",
            rf"Software\Microsoft\Edge\NativeMessagingHosts\{NATIVE_HOST_NAME}",
            rf"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{NATIVE_HOST_NAME}",
        ]
        for rp in reg_paths:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rp) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest_path))
    except Exception as e:
        return {"ok": False, "text": f"Native Messaging ホストの登録に失敗しました: {e}"}
    return {"ok": True, "manifest": str(manifest_path), "text": "拡張からの自動復旧ホスト（Native Messaging）を登録しました"}


def repair_local_bindings_if_stale():
    """フォルダ移動等で既存のスタートアップ / Native Messaging 登録のパスが現在位置とズレた場合のみ自動で修復する。
    未導入環境（既存登録が無い環境）には一切書き込まない。"""
    if os.name != "nt":
        return {"repaired": []}
    repaired = []
    gas_py = str(HERE / "gas.py")
    # 1. 既存スタートアップ .vbs のパスズレ修復
    try:
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs = startup / "GASコンボ受け手.vbs"
        if vbs.is_file():
            txt = vbs.read_text(encoding="utf-16", errors="ignore")
            if gas_py.lower() not in txt.lower():
                st, _ = _load_combo_state()
                sid = str((st or {}).get("addon_sid") or "").strip() or "DIRECT"
                pyw = Path(sys.executable).with_name("pythonw.exe")
                exe = str(pyw if pyw.exists() else sys.executable)
                cmd = f'"{exe}" "{gas_py}" combo watch {sid}'
                vbs.write_text('CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\r\n', encoding="utf-16")
                repaired.append("startup_vbs")
    except Exception:
        pass
    # 2. 既存 Native Messaging ホスト登録のパスズレ・欠損修復
    try:
        import winreg
        reg_path = rf"Software\Google\Chrome\NativeMessagingHosts\{NATIVE_HOST_NAME}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as k:
            cur_manifest, _ = winreg.QueryValueEx(k, "")
        expected_manifest = str(HERE / ".native_host_manifest.json")
        bat_ok = (HERE / ".native_host.bat").is_file()
        man_ok = (HERE / ".native_host_manifest.json").is_file()
        if str(cur_manifest or "").lower() != expected_manifest.lower() or not (bat_ok and man_ok):
            if install_native_host().get("ok"):
                repaired.append("native_host")
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {"repaired": repaired}


def install_watch_autostart(script_id, start_now=True, restart=False):
    """郵便受けの受け手を、Windows にログオンしたら窓を出さずに自分で起きるようにする（スタートアップに 1 本置く）。
    start_now なら今も起こす。restart=True のときは動作中の旧プロセスへ /stop を送って入れ替える。"""
    if os.name != "nt":
        return {"ok": False, "text": "自動で起こすのは Windows だけです。端末で py gas.py combo watch <id> を撃ってください"}
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else sys.executable)
    gas_py = str(HERE / "gas.py")
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    vbs = startup / "GASコンボ受け手.vbs"
    cmd = f'"{exe}" "{gas_py}" combo watch {script_id}'
    try:
        startup.mkdir(parents=True, exist_ok=True)
        vbs.write_text('CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\r\n', encoding="utf-16")
    except Exception as e:
        return {"ok": False, "text": f"スタートアップに置けませんでした: {e}"}
    if start_now:
        if restart:
            import socket
            import urllib.request
            old_pid = None
            try:
                raw_stop = urllib.request.urlopen(f"http://127.0.0.1:{COMBO_WATCH_PORT}/stop", timeout=1.5).read().decode("utf-8", "ignore")
                try:
                    info = json.loads(raw_stop or "{}")
                    if isinstance(info, dict) and isinstance(info.get("pid"), int):
                        old_pid = info["pid"]
                except Exception:
                    pass
                for _ in range(25):
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        if s.connect_ex(("127.0.0.1", COMBO_WATCH_PORT)) != 0:
                            break
                    time.sleep(0.1)
            except Exception:
                pass
            if isinstance(old_pid, int) and old_pid > 0 and old_pid != os.getpid():
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    still_open = (s.connect_ex(("127.0.0.1", COMBO_WATCH_PORT)) == 0)
                if still_open:
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(old_pid)],
                            capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                        )
                        for _ in range(10):
                            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                                if s.connect_ex(("127.0.0.1", COMBO_WATCH_PORT)) != 0:
                                    break
                            time.sleep(0.1)
                    except Exception:
                        pass
        subprocess.Popen([exe, gas_py, "combo", "watch", script_id], cwd=str(HERE),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x8),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    nh = install_native_host()
    return {
        "ok": True,
        "startup": str(vbs),
        "native_host": nh,
        "text": "郵便受けの受け手を動かしました（ログオン自動起動＋Chrome拡張からの自動復旧を登録済み）",
    }


# ---------------------------------------------------------------- CLI 入口

def _run_cli(argv=None):
    parser = argparse.ArgumentParser(description="GASコンボ CLI (install / ask / ops / undo / look / watch)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inst = sub.add_parser("install", help="GASプロジェクトへ GASコンボ 5 ファイルを配置する")
    p_inst.add_argument("script_id", help="対象 GAS スクリプトID")
    p_inst.add_argument("--ss", default="", help="既定のスプレッドシートID")
    p_inst.add_argument("--preserve", action="store_true", help="既存の別ファイルを残す")
    p_inst.add_argument("--no-extra-scopes", action="store_true", help="基本3スコープのみにする（既存エンジン互換用）")
    p_inst.add_argument("--no-minify", action="store_true", help="サーバーJSのコメント/空白除去を行わない")
    p_inst.add_argument("--sheet-only", action="store_true", help="シート専用に軽量化する（文書用棚を除外）")
    p_inst.add_argument("--no-server-planner", action="store_true", help="サーバー側から ComboPlanner を省く（サイドバー専用最軽量）")
    p_inst.add_argument("--connector", action="store_true", help="大元ライブラリ shuworkspaceengine へ繋ぐ30行の繋ぎコード（コード.gs）のみを配置する")
    p_inst.add_argument("--lib-id", default="", help="大元ライブラリのスクリプトID（--connector 用）")
    p_inst.add_argument("--lib-ver", default="", help="大元ライブラリのバージョン番号（--connector 用）")

    p_tmpl = sub.add_parser("template", help="GASコンボのテンプレートシートを作る・入れ直す（コピーするだけで使える版）")
    p_tmpl.add_argument("--title", default="", help=f"テンプレートのスプレッドシート名（既定: {DEFAULT_COMBO_TEMPLATE_TITLE}）")
    p_tmpl.add_argument("--new", action="store_true", help="記録を無視してテンプレートを新しく作り直す")
    p_tmpl.add_argument("--force", action="store_true", help="大元ライブラリの版を必ず上げる")

    p_addon = sub.add_parser("addon", help="GASコンボを Google Workspace アドオンとして作る・入れ直す（シートごとのつなぎコード不要）")
    p_addon.add_argument("--id", default="", help="アドオンのスクリプトID（省略時は前回作った物・無ければ新しく作る）")
    p_addon.add_argument("--force", action="store_true", help="大元ライブラリの版を必ず上げる")

    p_conn = sub.add_parser("connect", help="スプレッドシート側へ大元ライブラリ shu-gas-combo-engine の30行繋ぎコードを配置する")
    p_conn.add_argument("script_id", nargs="?", default="", help="対象のスクリプトID または スプレッドシートの URL/ID")
    p_conn.add_argument("--ss", default="", help="スプレッドシートの URL または ID（新規コンテナバインド作成＋配置）")
    p_conn.add_argument("--title", default="GASコンボ", help="新規作成する GAS プロジェクト名（--ss 用）")
    p_conn.add_argument("--lib-id", default="", help="大元ライブラリのスクリプトID")
    p_conn.add_argument("--lib-ver", default="", help="大元ライブラリのバージョン番号")

    p_push = sub.add_parser("push", help="元を直したら 1 回＝大元とアドオンへ同時に送る（版は上げない・テンプレートは配る節目に template）")
    p_push.add_argument("--ask", action="append", default=[], help="送る前に棚当てに通して見る頼み（何本でも）")
    p_phr = sub.add_parser("phrase", help="当たらなかった頼みを言い方の表に足し、大元とアドオンへ送るまで 1 回で")
    p_phr.add_argument("ask", help="頼みの文（例: タイトルの文字を赤）")
    p_phr.add_argument("ops", nargs="?", default="", help="撃つ ops の JSON（省くと棚当ての近い候補）")
    p_phr.add_argument("--no-deploy", action="store_true", help="入れ直さない（表に足して試験だけ）")
    p_look = sub.add_parser("look", help="対象スプレッドシートの状態を見る")
    p_look.add_argument("script_id", help="対象 GAS スクリプトID")
    p_look.add_argument("--ss", default="", help="スプレッドシートID")
    p_look.add_argument("--sheet", default="", help="シート名")
    p_look.add_argument("--range", default="", help="A1範囲")

    p_ask = sub.add_parser("ask", help="自然文で実行する (comboRunAsk)")
    p_ask.add_argument("script_id", help="対象 GAS スクリプトID")
    p_ask.add_argument("text", help="依頼文")
    p_ask.add_argument("--ss", default="", help="スプレッドシートID")
    p_ask.add_argument("--sheet", default="", help="シート名")
    p_ask.add_argument("--ok", action="store_true", help="確認なしで実行する")
    p_ask.add_argument("--backup", action="store_true", help="フル控えを取る")
    p_ask.add_argument("--no-ai", action="store_true", help="AIフォールバック無効")

    p_ops = sub.add_parser("ops", help="ops JSON を直接実行する (comboRunOps)")
    p_ops.add_argument("script_id", help="対象 GAS スクリプトID")
    p_ops.add_argument("ops_json", help="ops JSON 文字列")
    p_ops.add_argument("--ss", default="", help="スプレッドシートID")
    p_ops.add_argument("--sheet", default="", help="シート名")
    p_ops.add_argument("--ok", action="store_true", help="確認なしで実行する")
    p_ops.add_argument("--backup", action="store_true", help="フル控えを取る")

    p_undo = sub.add_parser("undo", help="直前の変更を取り消す (comboUndo)")
    p_undo.add_argument("script_id", help="対象 GAS スクリプトID")
    p_undo.add_argument("--ss", default="", help="スプレッドシートID")
    p_undo.add_argument("--ok", action="store_true", help="確認なしで戻す")
    p_undo.add_argument("--to", default="", help="戻す台帳番号")

    p_watch = sub.add_parser("watch", help="郵便受けキューを監視して AI 実行する")
    p_watch.add_argument("script_id", help="対象 GAS スクリプトID")
    p_watch.add_argument("--interval", type=float, default=2.0, help="ポーリング間隔（秒）")
    p_watch.add_argument("--model", default="", help="AI モデル名")
    p_watch.add_argument("--once", action="store_true", help="1回だけポーリングして終了")
    p_watch.add_argument("--autostart", action="store_true", help="ログオンのたびに窓を出さずに自分で起きるようにして、今も起こす（Windows）")
    p_watch.add_argument("--postbox", action="store_true", help="従来の GAS 郵便受けポーリングも併用する（既定は直結専用）")

    p_quick = sub.add_parser("quick", help="マイマクロ一覧・実行 (comboQuickList / comboQuickRun)")
    p_quick.add_argument("script_id", help="対象 GAS スクリプトID")
    p_quick.add_argument("quick_action", choices=("list", "run"), help="list または run")
    p_quick.add_argument("macro_name", nargs="?", default="", help="実行するマイマクロ名（run 時）")
    p_quick.add_argument("--ss", default="", help="スプレッドシートID")
    p_quick.add_argument("--sheet", default="", help="シート名")
    p_quick.add_argument("--sel", default="", help="選択範囲（例: A1:C10）")
    p_quick.add_argument("--force", action="store_true", help="一覧キャッシュを無視して再取得")
    p_quick.add_argument("--no-backup", action="store_true", help="実行前の控えを省略する")

    args = parser.parse_args(argv)
    from gas_client import GasClient
    client = GasClient()

    if args.cmd == "push":
        print(json.dumps(push_combo_dev(client=client, asks=args.ask), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "phrase":
        print(json.dumps(add_combo_phrase(args.ask, ops=args.ops or None, deploy=not args.no_deploy), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "template":
        print(json.dumps(create_combo_template(title=args.title, new=args.new, force_engine_update=args.force, client=client), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "addon":
        print(json.dumps(install_combo_addon(addon_id=args.id, force_engine_update=args.force, client=client), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "connect" or (args.cmd == "install" and getattr(args, "connector", False)):
        ss_arg = str(getattr(args, "ss", "") or "").strip()
        tgt_arg = str(getattr(args, "script_id", "") or "").strip()
        if ss_arg:
            res = connect_spreadsheet(
                ss_arg,
                engine_lib_id=getattr(args, "lib_id", ""),
                engine_version=getattr(args, "lib_ver", ""),
                title=getattr(args, "title", "GASコンボ"),
                client=client,
            )
        elif tgt_arg:
            kind, resolved = _detect_connect_target(tgt_arg, client)
            if kind == "sheet":
                res = connect_spreadsheet(
                    resolved,
                    engine_lib_id=getattr(args, "lib_id", ""),
                    engine_version=getattr(args, "lib_ver", ""),
                    title=getattr(args, "title", "GASコンボ"),
                    client=client,
                )
            else:
                res = install_combo_connector(
                    resolved,
                    engine_lib_id=getattr(args, "lib_id", ""),
                    engine_version=getattr(args, "lib_ver", ""),
                    client=client,
                )
        else:
            auto_ss_id, _ = _resolve_active_sheet_id()
            res = connect_spreadsheet(
                auto_ss_id,
                engine_lib_id=getattr(args, "lib_id", ""),
                engine_version=getattr(args, "lib_ver", ""),
                title=getattr(args, "title", "GASコンボ"),
                client=client,
            )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "install":
        res = install_combo(
            args.script_id,
            target_ss_id=args.ss,
            client=client,
            preserve_existing=args.preserve,
            include_extra_scopes=not args.no_extra_scopes,
            minify_server=not args.no_minify,
            sheet_only=args.sheet_only,
            include_server_planner=not args.no_server_planner,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "look":
        req = {"targetId": args.ss, "sheet": args.sheet, "range": args.range}
        res = _unwrap_run_result(client.run_function(args.script_id, "comboLook", [req]), client=client, sid=args.script_id)
        print(res.get("text") or json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "ask":
        req = {
            "ask": args.text,
            "targetId": args.ss,
            "sheet": args.sheet,
            "ok": args.ok,
            "backup": args.backup,
            "aiAuto": not args.no_ai,
        }
        res = _unwrap_run_result(client.run_function(args.script_id, "comboRunAsk", [req]), client=client, sid=args.script_id)
        print(res.get("text") or json.dumps(res, ensure_ascii=False, indent=2))
        if isinstance(res, dict) and res.get("gasMs") is not None:
            print(f"(gasMs: {res['gasMs']}ms)")
        return 0 if (res or {}).get("ok") else 1
    if args.cmd == "ops":
        ops = json.loads(args.ops_json)
        req = {
            "ops": ops,
            "targetId": args.ss,
            "sheet": args.sheet,
            "ok": args.ok,
            "backup": args.backup,
        }
        res = _unwrap_run_result(client.run_function(args.script_id, "comboRunOps", [req]), client=client, sid=args.script_id)
        print(res.get("text") or json.dumps(res, ensure_ascii=False, indent=2))
        if isinstance(res, dict) and res.get("gasMs") is not None:
            print(f"(gasMs: {res['gasMs']}ms)")
        return 0 if (res or {}).get("ok") else 1
    if args.cmd == "undo":
        req = {"targetId": args.ss, "ok": args.ok, "to": args.to}
        res = _unwrap_run_result(client.run_function(args.script_id, "comboUndo", [req]), client=client, sid=args.script_id)
        print(res.get("text") or json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res or {}).get("ok") else 1
    if args.cmd == "watch" and args.autostart:
        print(json.dumps(install_watch_autostart(args.script_id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "watch":
        # 窓なし（pythonw）起動時は初期化エラーも必ずログに残す
        if sys.stdout is None or sys.stderr is None or Path(sys.executable).name.lower() == "pythonw.exe":
            _log = _open_watch_log()
            sys.stdout = sys.stderr = _log
        is_direct_only = (not args.once) and (not args.postbox)
        watcher = ComboPostboxWatcher(args.script_id, client=client, model=args.model or None, poll_interval=args.interval, direct_only=is_direct_only)
        if args.once:
            res = watcher.poll_once()
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            watcher.watch(idle_interval=3.0, direct_only=not args.postbox)
        return 0
    if args.cmd == "quick":
        if args.quick_action == "list":
            req = {"targetId": args.ss, "force": args.force}
            res = _unwrap_run_result(client.run_function(args.script_id, "comboQuickList", [req]), client=client, sid=args.script_id)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if (res or {}).get("ok") else 1
        if not args.macro_name:
            print("実行するマイマクロ名を指定してください: quick <script_id> run <macro_name>")
            return 1
        req = {
            "name": args.macro_name,
            "targetId": args.ss,
            "sheet": args.sheet,
            "selection": args.sel,
            "backup": not args.no_backup,
        }
        res = _unwrap_run_result(client.run_function(args.script_id, "comboQuickRun", [req]), client=client, sid=args.script_id)
        print((res or {}).get("text") or json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if (res or {}).get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
