# -*- coding: utf-8 -*-
"""Phase 4: 直結ヘルス・ストリーミング応答・PID多重起動防止・ドライラン・共有/CIの単体テスト。"""

import json
import re
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import gas_ws_combo as combo_mod

HERE = Path(__file__).resolve().parent


def _node_ok():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


needs_node = pytest.mark.skipif(not _node_ok(), reason="node が必要です")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_watcher_health_streaming_and_pid_guard(tmp_path):
    """ComboLocalWatcher の /health・/resolve-stream (NDJSON)・PID多重起動ガード・/stop 後片付けを実HTTPで確認。"""
    port = _free_port()
    pid_path = tmp_path / "watch.pid"
    mock_client = MagicMock()
    w = combo_mod.ComboLocalWatcher("DUMMY_SID", client=mock_client, model="sonnet")
    w.resolve_item = lambda item: {
        "action": "reply",
        "message": f"受信: {item.get('ask', '')}",
    }

    th = threading.Thread(
        target=w.watch,
        kwargs={"port": port, "pid_path": pid_path},
        daemon=True,
    )
    th.start()

    # 起動待ち
    health = None
    for _ in range(40):
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5).read().decode("utf-8")
            health = json.loads(raw)
            break
        except Exception:
            time.sleep(0.05)

    assert health is not None, "/health が応答しませんでした"
    assert health["ok"] is True
    assert health["directOnly"] is True
    assert health["version"] == combo_mod.COMBO_WATCH_VERSION
    assert isinstance(health["pid"], int) and health["pid"] > 0
    assert pid_path.is_file()

    # /resolve-stream で NDJSON チャンクを受信
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/resolve-stream",
        data=json.dumps({"kind": "ops", "ask": "テスト質問"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    stream_text = urllib.request.urlopen(req, timeout=3).read().decode("utf-8")
    events = [json.loads(line) for line in stream_text.splitlines() if line.strip()]
    types = [e.get("type") for e in events]
    assert "status" in types
    assert "delta" in types
    assert types[-1] == "done"
    assert events[-1]["result"]["ok"] is True
    assert "テスト質問" in events[-1]["result"]["message"]

    # lastAiMs が /health に記録されていること
    health2 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read().decode("utf-8"))
    assert isinstance(health2["lastAiMs"], int) and health2["lastAiMs"] >= 0
    assert health2["lastError"] == ""

    # 同一ポート＋PID ファイルへの多重起動は即終了すること
    w2 = combo_mod.ComboLocalWatcher("DUMMY_SID", client=mock_client)
    t_dup0 = time.perf_counter()
    w2.watch(direct_only=True, port=port, pid_path=pid_path)
    assert (time.perf_counter() - t_dup0) < 2.0

    # /stop で停止し、PID ファイルが削除されること
    urllib.request.urlopen(f"http://127.0.0.1:{port}/stop", timeout=1).read()
    th.join(timeout=3.0)
    assert not th.is_alive()
    assert not pid_path.is_file()


@needs_node
def test_server_dryrun_and_force_ai_mode():
    """comboQuickRun(dryRunCode) の控え付き試実行と、comboRunAsk / comboQuickAiSave の forceAiMode 切替を検証。"""
    files = combo_mod.build_combo_files(combo_lite=False)
    by_name = {f["name"]: f["source"] for f in files}

    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const userProps = {
  COMBO_CONFIG: JSON.stringify({ aiMode: 'postbox', aiModel: 'gemini_hydrogen', geminiKey: 'AIzaTEST_FALLBACK_KEY' })
};
const scriptProps = {}, userCache = {};
let deletedBackup = 0, copiedToBackup = 0;

function mkSheet(name) {
  let values = [['見出しA', '見出しB'], ['x', 100]];
  let frozenR = 0, frozenC = 0;
  const sh = {
    _name: name,
    getName: () => sh._name,
    setName: (n) => { sh._name = n; },
    hideSheet: () => {},
    getLastRow: () => values.length,
    getLastColumn: () => values[0].length,
    getMaxRows: () => 20,
    getMaxColumns: () => 5,
    getFrozenRows: () => frozenR,
    getFrozenColumns: () => frozenC,
    setFrozenRows: (n) => { frozenR = n; },
    setFrozenColumns: (n) => { frozenC = n; },
    getBandings: () => [],
    getFilter: () => null,
    getDataRange: () => ({ getValues: () => values, getA1Notation: () => 'A1:B2' }),
    getActiveRange: () => sh.getRange('A1:B2'),
    getRange: (a1OrR, c, nr, nc) => ({
      getA1Notation: () => typeof a1OrR === 'string' ? a1OrR : 'A1',
      setFontWeight: () => sh.getRange(a1OrR),
      setBackground: () => sh.getRange(a1OrR),
      copyTo: () => {},
      breakApart: () => {},
      clear: () => {},
      clearDataValidations: () => {},
    }),
    copyTo: (ssObj) => { copiedToBackup++; const b = mkSheet('copy'); ssObj._sheets.push(b); return b; }
  };
  return sh;
}

const mainSh = mkSheet('Sheet1');
const mockSs = {
  _sheets: [mainSh],
  getId: () => 'SS_DRY_1',
  getName: () => 'テストブック',
  getUrl: () => 'https://docs.google.com/spreadsheets/d/SS_DRY_1/edit',
  getSheets: () => mockSs._sheets,
  getSheetByName: (n) => mockSs._sheets.find(s => s.getName() === n) || null,
  getActiveSheet: () => mainSh,
  deleteSheet: (s) => { deletedBackup++; mockSs._sheets = mockSs._sheets.filter(x => x !== s); },
  toast: () => {}
};

const fetchCalls = [];
const ctx = vm.createContext({
  SpreadsheetApp: {
    getActiveSpreadsheet: () => mockSs,
    getActive: () => mockSs,
    openById: () => mockSs,
    flush: () => {},
    BorderStyle: { SOLID: 'SOLID' },
    BandingTheme: { BLUE: 'BLUE' },
    CopyPasteType: { PASTE_COLUMN_WIDTHS: 'PASTE_COLUMN_WIDTHS' }
  },
  DocumentApp: {
    getActiveDocument: () => null,
    openById: () => null,
    ParagraphHeading: { NORMAL: 'NORMAL', HEADING1: 'HEADING1', HEADING2: 'HEADING2', HEADING3: 'HEADING3', HEADING4: 'HEADING4', HEADING5: 'HEADING5', HEADING6: 'HEADING6', TITLE: 'TITLE', SUBTITLE: 'SUBTITLE' },
    ElementType: { PARAGRAPH: 'PARAGRAPH', LIST_ITEM: 'LIST_ITEM', TABLE: 'TABLE' }
  },
  DriveApp: { getFileById: () => ({ getName: () => 'テストブック', isTrashed: () => false, getLastUpdated: () => ({ getTime: () => 1000 }) }), searchFiles: () => ({ hasNext: () => false }), getFilesByName: () => ({ hasNext: () => false }) },
  LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
  Session: { getScriptTimeZone: () => 'Asia/Tokyo' },
  PropertiesService: {
    getUserProperties: () => ({
      getProperties: () => ({ ...userProps }),
      getProperty: k => (k in userProps ? userProps[k] : null),
      setProperty: (k, v) => { userProps[k] = String(v); },
      deleteProperty: k => { delete userProps[k]; }
    }),
    getScriptProperties: () => ({
      getProperty: k => (k in scriptProps ? scriptProps[k] : null),
      setProperty: (k, v) => { scriptProps[k] = String(v); },
      deleteProperty: k => { delete scriptProps[k]; }
    })
  },
  CacheService: {
    getUserCache: () => ({ get: k => (k in userCache ? userCache[k] : null), put: (k, v) => { userCache[k] = String(v); }, remove: k => { delete userCache[k]; }, getAll: () => ({}) }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  UrlFetchApp: {
    fetch: (url, opts) => {
      fetchCalls.push({ url, payload: JSON.parse((opts && opts.payload) || '{}') });
      return {
        getResponseCode: () => 200,
        getContentText: () => JSON.stringify({
          candidates: [{ content: { parts: [{ text: JSON.stringify({ action: 'reply', message: 'API鍵フォールバック応答' }) }] } }]
        })
      };
    }
  },
  ScriptApp: { getOAuthToken: () => 'TOK' },
  Utilities: { formatDate: () => '20261126', computeDigest: () => [1], DigestAlgorithm: { MD5: 'MD5' }, newBlob: (s) => ({ getBytes: () => Buffer.from(String(s)) }), base64Encode: () => 'x' },
  console, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Date, Proxy
});
ctx.globalThis = ctx;
vm.runInContext(payload.engine + '\n' + payload.planner + '\n' + payload.server, ctx);

// 1. 下書きコードのドライラン試実行（Drive保存なし、控え作成あり）
const dryRes = ctx.comboQuickRun({
  dryRunCode: '// テスト用下書き\nfunction 試実行マクロ() {\n  return "完了テスト";\n}',
  backup: false,
  targetId: 'SS_DRY_1'
});

// 2. postbox 設定のまま forceAiMode='api_gemini' で fallback できること
const askFb = ctx.comboRunAsk({
  ask: '棚に絶対に当たらない特別なお願い',
  aiAuto: true,
  forceAiMode: 'api_gemini',
  targetId: 'SS_DRY_1',
  sheet: 'Sheet1'
});
const quickFb = ctx.comboQuickAiSave({
  mode: 'add',
  previewOnly: true,
  forceAiMode: 'api_gemini',
  prompt: 'どんなマクロが作れる？',
  targetId: 'SS_DRY_1',
  sheet: 'Sheet1'
});

process.stdout.write(JSON.stringify({ dryRes, copiedToBackup, askFb, quickFb, fetchCallsCount: fetchCalls.length }));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps(
            {
                "engine": by_name["Engine"],
                "planner": by_name["ComboPlanner"],
                "server": by_name["ComboServer"],
            },
            ensure_ascii=False,
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\nstdout: {proc.stdout}"
    res = json.loads(proc.stdout.strip())
    assert res["dryRes"]["ok"] is True
    assert res["dryRes"]["dryRun"] is True
    assert res["dryRes"]["snapped"] is True
    assert res["dryRes"]["name"] == "試実行マクロ"
    assert res["copiedToBackup"] >= 1
    assert res["askFb"]["ok"] is True
    assert res["askFb"]["source"] == "ai_reply"
    assert res["quickFb"]["ok"] is True
    assert res["quickFb"]["action"] == "reply"
    assert res["fetchCallsCount"] >= 2


@needs_node
def test_sidebar_templates_export_import_js():
    """サイドバーのまとめ棚テンプレート(3件)・JSON/.gsエクスポート・インポート検証が動作すること。"""
    files = combo_mod.build_combo_files()
    html = {f["name"]: f["source"] for f in files}["ComboSidebar"]
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)

    node_code = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const elsMap = {};
function mkEl(id) {
  return {
    id, value: '', checked: false, disabled: false, textContent: '', innerHTML: '', style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, appendChild(c){ this.children.push(c); return c; },
    querySelectorAll(){ return []; }, querySelector(){ return null; }, focus(){}
  };
}
const sandbox = {
  console, Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp, Error, parseInt, parseFloat, isNaN, isFinite,
  encodeURIComponent, decodeURIComponent, setTimeout: () => 0, clearTimeout: () => {}, performance: { now: () => 100 },
  document: { getElementById: (id) => elsMap[id] || (elsMap[id] = mkEl(id)), createElement: mkEl, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {} },
  window: { addEventListener() {} }, localStorage: { getItem(){ return null; }, setItem(){} }
};
sandbox.globalThis = sandbox;
for (const sc of input.scripts) vm.runInNewContext(sc, sandbox);

const dt = sandbox.__comboDirectTest;
dt.state.quick.codeCache = {
  stamp: '1',
  map: {
    既存マクロ: '// 既存\nfunction 既存マクロ() {\n  return 1;\n}'
  }
};
const tpls = dt.QUICK_MY_TEMPLATES;
const expJson = dt.exportMyMacrosData('json');
const expGs = dt.exportMyMacrosData('gs');
const impOk = dt.parseImportMyMacros(expJson.content, ['別マクロ']);
const impDup = dt.parseImportMyMacros(expJson.content, ['既存マクロ']);
const impBadSyn = dt.parseImportMyMacros('function 壊れ( {', []);

process.stdout.write(JSON.stringify({ tpls, expJson, expGs, impOk, impDup, impBadSyn }));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps({"scripts": scripts}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\nstdout: {proc.stdout}"
    res = json.loads(proc.stdout.strip())
    assert [t["name"] for t in res["tpls"]] == [
        "名簿クレンジング",
        "請求書フォーマットチェック",
        "部署別集計と区切り線",
    ]
    assert res["expJson"]["ok"] is True
    assert res["expGs"]["ok"] is True
    assert "function 既存マクロ" in res["expGs"]["content"]
    assert res["impOk"]["ok"] is True
    assert res["impOk"]["names"] == ["既存マクロ"]
    assert res["impDup"]["ok"] is False
    assert "重複" in res["impDup"]["error"]
    assert res["impBadSyn"]["ok"] is False
    assert "構文エラー" in res["impBadSyn"]["error"]


def test_ci_workflow_exists_and_valid():
    """GitHub Actions CI ワークフローが必要な検査ステップを含んで存在すること。"""
    wf = HERE / ".github" / "workflows" / "ci.yml"
    assert wf.is_file()
    txt = wf.read_text(encoding="utf-8")
    assert "publish_check.py" in txt
    assert "build_combo_templates.py --check" in txt
    assert "pytest" in txt
