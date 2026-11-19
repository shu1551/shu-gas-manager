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
import gas_ws_catalog
import gas_ws_find

PLANNER_TEMPLATE = HERE / "combo_planner_template.js"
PHRASES_PATH = HERE / "combo_phrases.json"   # 言い方の表（頼み→ops。combo phrase で足す。全員に配る覚え）
SERVER_TEMPLATE = HERE / "combo_server_template.gs"
SIDEBAR_TEMPLATE = HERE / "combo_sidebar_template.html"
ADDON_TEMPLATE = HERE / "combo_addon_template.gs"
DEFAULT_ADDON_TITLE = "GASコンボ（アドイン）"
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
    cat_for_html = (
        dict(cat_data, shelves=[s for s in cat_data["shelves"] if s.get("kind") != "doc" or s.get("shared")])
        if combo_lite
        else cat_data
    )
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
            {"name": s["name"], "t": s.get("title", ""), "a": s.get("args_raw", "")}
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


def _planner_eval_many(asks, table=None):
    """頼みを何本でも node 1 回で棚当てに通し、[{ask, fire, ops, suggest, reasons}] を返す。"""
    import subprocess
    planner = next(f["source"] for f in build_combo_files() if f["name"] == "ComboPlanner")
    tbl = table or {"title_a1": "A1", "header_row": 3, "header": ["日付", "部門", "担当者", "商品名", "数量", "単価", "売上金額"],
                    "first_row": 4, "last_row": 9, "total_row": 9, "range": "A3:G9"}
    js = ("const vm=require('vm'),fs=require('fs');const d=JSON.parse(fs.readFileSync(0,'utf8'));"
          "const ctx=vm.createContext({});vm.runInContext(d.pj,ctx);const P=ctx.ComboPlanner;"
          "process.stdout.write(JSON.stringify(d.asks.map(a=>{const p=P.plan(a,'sheet',d.t,['売上表'],'売上表',null);"
          "return {ask:a,fire:!!p.fire,ops:p.ops,suggest:p.suggest||null,reasons:p.reasons};})));")
    r = subprocess.run(["node", "-e", js], input=json.dumps({"pj": planner, "asks": list(asks), "t": tbl}, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("棚当ての実行に失敗しました: " + r.stderr.decode("utf-8", "replace")[:400])
    return json.loads(r.stdout.decode("utf-8"))


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


def push_combo_dev(client=None, state_path=None, asks=None):
    """元（combo_*_template と言い方の表）を直したら、これ 1 回で届く。
    大元ライブラリとアドインへ同時に送り、操作窓（/exec）の版だけ上げる。大元の版は上げない（アドインは開発モードでつなぐ）。
    テンプレート（人がコピーする物）は版でつなぐので、配る節目に combo template で上げる。"""
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    t0 = _time.time()
    # 1. 確かめ: 渡した頼みが、どの棚にどの引数で当たるか（送る前に並べる）
    checks = []
    if asks:
        for r in _planner_eval_many(asks):
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
    return {"ok": True, "mode": "push", "checks": checks, "leak": leak_line, "engineLibId": lib_id, "addon": addon_sid, "window": webapp_url,
            "seconds": round(_time.time() - t0, 1),
            "next": "アドイン（カード・操作窓）は次に開いたときから新しいコード。テンプレートは配る節目に combo template"}


def add_combo_phrase(ask, ops=None, deploy=True, client=None, path=None):
    """当たらなかった頼みを言い方の表に足し、大元とアドインへ送るまでを 1 回で。
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
            "https://www.googleapis.com/auth/script.container.ui",
            "https://www.googleapis.com/auth/script.external_request",
        ],
        "webapp": {"executeAs": "USER_DEPLOYING", "access": "MYSELF"},
    }
    return [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, ensure_ascii=False, indent=2)},
        {"name": "コード", "type": "SERVER_JS", "source": code_gs},
    ]


def build_combo_addon_files(engine_lib_id, engine_version, lib_symbol="shucomboengine", webapp_url="", development_mode=True):
    """Google Workspace アドイン版 GASコンボのファイル（appsscript・コード・ComboPlanner）を組み立てる。
    1 回インストールすれば全部のスプレッドシートに出る（シートごとのつなぎコードは要らない）。"""
    if not str(engine_lib_id or "").strip():
        raise ValueError("つなぐ大元ライブラリが決まっていません（install_combo_addon が自分の Drive に作ります）")
    sym = str(lib_symbol or "shucomboengine").strip()
    manifest = {
        "timeZone": "Asia/Tokyo",
        "runtimeVersion": "V8",
        "exceptionLogging": "STACKDRIVER",
        # Sheets の高度なサービスを入れると、このプロジェクトで Sheets API が有効になる（操作窓の直結の道＝画面から Sheets API を直接叩く 0.3 秒の道に要る。無いと 403）
        # 大元は「いつも最新」（開発モード）でつなぐ＝元を直して大元へ送れば、版を上げずにアドインに届く（アドインは持ち主が使う物）
        "dependencies": {"libraries": [{"userSymbol": sym, "libraryId": engine_lib_id, "version": str(engine_version or "1"), "developmentMode": bool(development_mode)}],
                         "enabledAdvancedServices": [{"userSymbol": "Sheets", "serviceId": "sheets", "version": "v4"}]},
        "oauthScopes": [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/script.external_request",
            "https://www.googleapis.com/auth/script.locale",
        ],
        "addOns": {
            "common": {"name": "GASコンボ", "logoUrl": "https://www.gstatic.com/images/icons/material/system/1x/bolt_black_48dp.png"},
            "sheets": {"homepageTrigger": {"runFunction": "onHome"}, "onFileScopeGrantedTrigger": {"runFunction": "onFileScopeGranted"}},
        },
        "webapp": {"executeAs": "USER_ACCESSING", "access": "MYSELF"},   # 操作窓（前のサイドバーの HTML）を別の窓で開く
        # Workspace アドインを正式にデプロイするには、外へ通信する先の一覧が要る（AI の API 鍵の道・Sheets API・書き出し）
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
    """アドイン版を作る・入れ直す。大元ライブラリを最新にし、アドインのプロジェクトへ push する。
    テスト デプロイ（Test latest code）は最新のコードで動くので、2 回目からはこれだけで全部のシートに効く。"""
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
    res = {"ok": True, "mode": "addon", "scriptId": sid, "engineLibId": lib_id, "engineVersion": ver, "window": webapp_url,
           "editor": f"https://script.google.com/home/projects/{sid}/edit"}
    if created:
        res["next"] = ("初回だけ: 上の editor を開き「デプロイ」→「デプロイをテスト」→「インストール」。"
                       "あとはどのスプレッドシートでも右の枠の ⚡ から使えます（初回に権限の許可が 1 回出ます）")
    else:
        res["next"] = "入れ直し済み（次に右の枠を開いたときから新しいコードで動きます）"
    ext_dir = str(HERE / "ws_browser_ext")
    res["chrome_extension"] = {
        "folder": ext_dir,
        "how": ("Chrome の右のサイドパネルで開く拡張（任意・おすすめ）: chrome://extensions を開き、右上の「デベロッパー モード」をオン →"
                f"「パッケージ化されていない拡張機能を読み込む」→ {ext_dir} を選ぶ。入れてあるなら「再読み込み」を押す"
                "（操作窓の番地を今書いたため）。あとは拡張のアイコンか Alt+G で、今開いているシートが相手の GASコンボが開きます"),
    }
    return res


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

                def do_OPTIONS(self):
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.end_headers()

                def do_POST(self):
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        data = json.loads(self.rfile.read(n).decode("utf-8"))
                        if isinstance(data, dict) and data.get("id") and data.get("kind", "sheet") == "sheet":
                            got["id"] = str(data["id"]).strip()
                            got["name"] = str(data.get("name") or "").strip()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
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
    """GAS側の郵便受け（COMBO_POSTBOX_Q）を監視し、ローカル AI で ops を組んで返す。"""

    def __init__(self, project_or_sid, client=None, model=None, poll_interval=2.0, backend="auto"):
        if client is None:
            from gas_client import GasClient
            client = GasClient()
        self.client = client
        self.sid = client.resolve_script_id(project_or_sid)
        self.model = model
        self.poll_interval = float(poll_interval)
        self.backend = backend
        self._ai_runner = None
        self._finder = None

    def _get_finder(self):
        if self._finder is None:
            self._finder = gas_ws_find.default()
        return self._finder

    def _build_prompt(self, item):
        ask = item.get("ask") or ""
        ss_name = item.get("ssName") or item.get("ssId") or ""
        sheet = item.get("sheet") or ""
        selection = item.get("selection") or ""
        table = item.get("table")
        sheets = item.get("sheets") or []

        lines = ["【現在の対象状態】", f"ブック: {ss_name} / シート: {sheet}"]
        if sheets:
            lines.append("全シート: " + "、".join(sheets))
        if selection:
            lines.append(f"選択中のセル範囲: {selection}（「ここ」「選択範囲」等の対象）")
        if table:
            lines.append(
                f"表: 見出し {table.get('header_row')}行目・{table.get('first_col')}〜{table.get('last_col')}列"
                f"・明細 {table.get('data')}行目"
                + (f"・合計行 {table['total_row']}行目" if table.get("total_row") else "")
            )
            cols = "、".join(
                f"{c.get('col')}={c.get('name')}{'(数値)' if c.get('number') else ''}"
                for c in (table.get("columns") or [])
            )
            lines.append("列: " + cols)

        finder = self._get_finder()
        lines.append("\n【よく関連する棚の詳細】")
        lines.append((finder.ask(ask, "sheet", log_to=False) or "")[:1600])
        lines.append("\n【利用可能な棚一覧（棚名 | 説明 | 引数）】")
        shelves = [s for s in finder.cat.shelves if s.get("kind") == "sheet" or s.get("shared")]
        for s in shelves[:50]:
            lines.append(f"- {s['name']}: {s.get('title', '')} | {s.get('args_raw', 'なし')}")
        lines.append(
            f"\n【ユーザーの依頼】\n{ask}\n\n"
            '必ず {"action":"ops","ops":[{"shelf":"...",...}],"note":"短い要約"} '
            'または {"action":"reply","message":"..."} の JSON 1個だけを返してください。'
        )
        return "\n".join(lines)

    def _ask_via_claude(self, prompt, model=None):
        import ws_window_ai
        eff_model = model or self.model or "sonnet"
        if self._ai_runner is None:
            self._ai_runner = ws_window_ai.GasAiRunner(model=eff_model)
        elif eff_model and self._ai_runner.model != eff_model:
            self._ai_runner.set_model(eff_model)
        raw = self._ai_runner.session.ask(prompt)
        return ws_window_ai._parse_ai_json(raw)

    def _ask_via_agy(self, prompt, model=None):
        import ws_window_ai
        exe = shutil.which("agy")
        if not exe:
            raise RuntimeError("agy コマンドが見つかりません")
        eff_model = model or self.model or "gemini-4-hydrogen-low"
        full = ws_window_ai.SYSTEM_PROMPT + "\n\n" + prompt
        kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": 60}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        cmd = [exe, "-p", full, "--model", eff_model, "--disable-slash-commands"]
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0:
            raise RuntimeError(f"agy 失敗 ({proc.returncode}): {(proc.stderr or proc.stdout)[:300]}")
        return ws_window_ai._parse_ai_json(proc.stdout)

    def resolve_item(self, item):
        """1 件の郵便受けリクエストを AI で解釈し、comboPostboxDeliver 用ペイロードを返す。"""
        req_id = item.get("reqId")
        req_model = str(item.get("aiModel") or self.model or "").strip()
        prompt = self._build_prompt(item)
        try:
            if self.backend == "claude":
                parsed = self._ask_via_claude(prompt, model=req_model or None)
            elif self.backend == "agy":
                parsed = self._ask_via_agy(prompt, model=req_model or None)
            else:
                # 選択モデルに応じて自動振り分け（gemini-* はハイド君/agy、それ以外は claude 優先）
                if req_model.startswith("gemini-"):
                    parsed = self._ask_via_agy(prompt, model=req_model)
                elif shutil.which("claude"):
                    parsed = self._ask_via_claude(prompt, model=req_model or "sonnet")
                else:
                    parsed = self._ask_via_agy(prompt, model=req_model or "gemini-4-hydrogen-low")
            action = parsed.get("action") or ("ops" if parsed.get("ops") else "reply")
            return {
                "reqId": req_id,
                "action": action,
                "ops": parsed.get("ops") or [],
                "note": parsed.get("note") or "",
                "message": parsed.get("message") or "",
            }
        except Exception as e:
            return {"reqId": req_id, "action": "error", "error": str(e)}

    def poll_once(self):
        """1 回ポーリングして保留中のリクエストをすべて処理する。"""
        poll_resp = self.client.run_function(self.sid, "comboPostboxPoll", [], fast=True, keep_runner=True)
        data = _unwrap_run_result(poll_resp, client=self.client, sid=self.sid) or {}
        queue_items = data.get("queue") or []
        results = []
        for item in queue_items:
            payload = self.resolve_item(item)
            deliv_resp = self.client.run_function(
                self.sid, "comboPostboxDeliver", [payload], fast=True, keep_runner=True
            )
            results.append({
                "reqId": item.get("reqId"),
                "payload": payload,
                "deliver": _unwrap_run_result(deliv_resp, client=self.client, sid=self.sid),
            })
        return results

    def watch(self, max_loops=None):
        """継続監視ループを実行する。"""
        loops = 0
        try:
            while max_loops is None or loops < max_loops:
                loops += 1
                handled = self.poll_once()
                for h in handled:
                    print(f"[postbox] {h['reqId']} -> {json.dumps(h['deliver'], ensure_ascii=False)}")
                if max_loops is not None and loops >= max_loops:
                    break
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            if self._ai_runner is not None:
                self._ai_runner.close()


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

    p_addon = sub.add_parser("addon", help="GASコンボを Google Workspace アドインとして作る・入れ直す（シートごとのつなぎコード不要）")
    p_addon.add_argument("--id", default="", help="アドインのスクリプトID（省略時は前回作った物・無ければ新しく作る）")
    p_addon.add_argument("--force", action="store_true", help="大元ライブラリの版を必ず上げる")

    p_conn = sub.add_parser("connect", help="スプレッドシート側へ大元ライブラリ shu-gas-combo-engine の30行繋ぎコードを配置する")
    p_conn.add_argument("script_id", nargs="?", default="", help="対象のスクリプトID または スプレッドシートの URL/ID")
    p_conn.add_argument("--ss", default="", help="スプレッドシートの URL または ID（新規コンテナバインド作成＋配置）")
    p_conn.add_argument("--title", default="GASコンボ", help="新規作成する GAS プロジェクト名（--ss 用）")
    p_conn.add_argument("--lib-id", default="", help="大元ライブラリのスクリプトID")
    p_conn.add_argument("--lib-ver", default="", help="大元ライブラリのバージョン番号")

    p_push = sub.add_parser("push", help="元を直したら 1 回＝大元とアドインへ同時に送る（版は上げない・テンプレートは配る節目に template）")
    p_push.add_argument("--ask", action="append", default=[], help="送る前に棚当てに通して見る頼み（何本でも）")
    p_phr = sub.add_parser("phrase", help="当たらなかった頼みを言い方の表に足し、大元とアドインへ送るまで 1 回で")
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
    if args.cmd == "watch":
        watcher = ComboPostboxWatcher(args.script_id, client=client, model=args.model or None, poll_interval=args.interval)
        if args.once:
            res = watcher.poll_once()
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            watcher.watch()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
