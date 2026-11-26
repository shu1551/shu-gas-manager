# -*- coding: utf-8 -*-
"""Phase 3: GASコンボ Google ドキュメント本格対応 (アドオン manifest / onHome / comboInit / comboRunAsk / phrases_文書) の単体テスト。"""

import json
import subprocess
from pathlib import Path

import pytest

import gas_ws_combo as C
import gas_ws_find as F

HERE = Path(__file__).resolve().parent
NODE_AVAILABLE = subprocess.run(["node", "--version"], capture_output=True).returncode == 0
needs_node = pytest.mark.skipif(not NODE_AVAILABLE, reason="Node.js が必要です")


def test_addon_manifest_includes_docs_scope_and_trigger():
    """アドオン版 manifest に documents スコープと docs トリガーが含まれること。"""
    files = C.build_combo_addon_files(
        engine_lib_id="LIB_ENG_DOC",
        engine_version="5",
        webapp_url="https://script.google.com/macros/s/AKfy_DOC/dev",
    )
    by_name = {f["name"]: f["source"] for f in files}
    manifest = json.loads(by_name["appsscript"])
    assert "https://www.googleapis.com/auth/documents" in manifest["oauthScopes"]
    assert "docs" in manifest["addOns"]
    assert manifest["addOns"]["docs"]["homepageTrigger"]["runFunction"] == "onHome"
    assert manifest["addOns"]["docs"]["onFileScopeGrantedTrigger"]["runFunction"] == "onFileScopeGranted"


@needs_node
def test_doc_combo_addon_and_server_execution():
    """Node vm 上で Document モックに対して comboInit / comboRunAsk / comboUndo / アドオン onHome & onAddonQuick が動作すること。"""
    files = C.build_combo_files(combo_lite=False)
    by_name = {f["name"]: f["source"] for f in files}
    addon_files = C.build_combo_addon_files(
        engine_lib_id="LIB_ENG_DOC",
        engine_version="5",
        lib_symbol="shucomboengine",
        webapp_url="https://script.google.com/macros/s/AKfy_DOC/dev",
    )
    addon_code = next(f["source"] for f in addon_files if f["name"] == "コード")

    node_code = r"""
const vm = require('vm'), fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

const userProps = {}, scriptProps = {}, userCache = {};
const paras = [
  { type: 'PARAGRAPH', heading: 'HEADING1', text: '1. 概要' },
  { type: 'PARAGRAPH', heading: 'NORMAL', text: '山田さんへの確認事項です。' },
  { type: 'PARAGRAPH', heading: 'HEADING2', text: '2. 今後の予定' },
];
function mkPara(obj) {
  return {
    getType: () => 'PARAGRAPH',
    asParagraph: () => ({
      getHeading: () => obj.heading,
      getText: () => obj.text,
      setText: (t) => { obj.text = t; },
      editAsText: () => ({
        getText: () => obj.text,
        replaceText: (pat, rep) => { obj.text = obj.text.replace(new RegExp(pat, 'g'), rep); }
      })
    }),
    replaceText: (pat, rep) => { obj.text = obj.text.replace(new RegExp(pat, 'g'), rep); }
  };
}
const mockBody = {
  getNumChildren: () => paras.length,
  getChild: (i) => mkPara(paras[i]),
  findText: () => null,
  replaceText: (pat, rep) => { paras.forEach(p => { p.text = p.text.replace(new RegExp(pat, 'g'), rep); }); },
  insertTableOfContents: () => {},
  appendParagraph: (t) => { const o = { type: 'PARAGRAPH', heading: 'NORMAL', text: t }; paras.push(o); return mkPara(o).asParagraph(); },
  insertParagraph: (idx, t) => { const o = { type: 'PARAGRAPH', heading: 'NORMAL', text: t }; paras.splice(idx, 0, o); return mkPara(o).asParagraph(); },
  getParagraphs: () => paras.map(p => mkPara(p).asParagraph()),
  getTables: () => [],
};
const mockDoc = {
  getId: () => 'DOC_TEST_1',
  getName: () => '会議議事録',
  getUrl: () => 'https://docs.google.com/document/d/DOC_TEST_1/edit',
  getBody: () => mockBody,
  saveAndClose: () => {},
};
const cardLog = [];
const mkWidget = (name) => {
  const w = { _name: name, _text: '', _title: '' };
  w.setText = (t) => { w._text = t; return w; };
  w.setTitle = (t) => { w._title = t; return w; };
  w.setFieldName = () => w;
  w.setMultiline = () => w;
  w.setOnChangeAction = () => w;
  w.setOnClickAction = () => w;
  w.setTextButtonStyle = () => w;
  w.setFunctionName = () => w;
  w.setParameters = () => w;
  w.addButton = (b) => { cardLog.push(b._text); return w; };
  return w;
};
const sharedEnv = {
  DocumentApp: {
    getActiveDocument: () => mockDoc,
    openById: (id) => id === 'DOC_TEST_1' ? mockDoc : null,
    ElementType: { PARAGRAPH: 'PARAGRAPH', LIST_ITEM: 'LIST_ITEM', TABLE: 'TABLE' },
    ParagraphHeading: { NORMAL: 'NORMAL', HEADING1: 'HEADING1', HEADING2: 'HEADING2' }
  },
  SpreadsheetApp: { getActiveSpreadsheet: () => null, openById: () => null, flush: () => {} },
  ScriptApp: { getOAuthToken: () => 'TOK_DOC' },
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
    getUserCache: () => ({ get: k => (k in userCache ? userCache[k] : null), put: (k, v) => { userCache[k] = String(v); }, getAll: () => ({}), remove: () => {} }),
    getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} })
  },
  CardService: {
    TextButtonStyle: { FILLED: 'FILLED' },
    OpenAs: { OVERLAY: 'OVERLAY' },
    OnClose: { NOTHING: 'NOTHING' },
    newCardSection: () => ({ addWidget: (w) => { if (w && w._text) cardLog.push(w._text); } }),
    newCardHeader: () => mkWidget('header'),
    newCardBuilder: () => { const b = { addSection: () => b, setHeader: () => b, build: () => ({ built: true }) }; return b; },
    newTextParagraph: () => mkWidget('p'),
    newTextInput: () => mkWidget('input'),
    newTextButton: () => mkWidget('btn'),
    newButtonSet: () => mkWidget('bset'),
    newAction: () => mkWidget('act'),
    newNavigation: () => ({ updateCard: (c) => c }),
    newActionResponseBuilder: () => ({ setNavigation: () => ({ build: () => ({ ok: true }) }), setOpenLink: () => ({ build: () => ({ ok: true }) }) }),
    newOpenLink: () => ({ setUrl: () => ({ setOpenAs: () => ({ setOnClose: () => ({}) }) }) }),
  },
  Utilities: { computeDigest: () => [1,2,3], DigestAlgorithm: { MD5: 'MD5' }, newBlob: (s) => ({ getBytes: () => Buffer.from(String(s), 'utf8') }), base64Encode: (b) => Buffer.from(b).toString('base64'), formatDate: () => '20261126_120000' },
  Session: { getScriptTimeZone: () => 'Asia/Tokyo' },
  LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
  DriveApp: { getFileById: () => ({ getName: () => '会議議事録', makeCopy: () => ({ getId: () => 'BK_DOC_1' }) }), getFilesByName: () => ({ hasNext: () => false }) },
  console, JSON, Math, RegExp, Object, Array, String, Number, Boolean, Error, Date
};

const libCtx = vm.createContext({ ...sharedEnv });
libCtx.globalThis = libCtx;
vm.runInContext(payload.engine + '\n' + payload.planner + '\n' + payload.server, libCtx);

const addonCtx = vm.createContext({ ...sharedEnv, shucomboengine: libCtx });
addonCtx.globalThis = addonCtx;
vm.runInContext(payload.planner + '\n' + payload.addon, addonCtx);

const initRes = libCtx.comboInit({ targetId: 'DOC_TEST_1', kind: 'doc' });
const lookRes = libCtx.comboLook ? libCtx.comboLook({ targetId: 'DOC_TEST_1', kind: 'doc' }) : null;
const askOutline = libCtx.comboRunAsk({ ask: '見出し一覧を見せて', targetId: 'DOC_TEST_1', kind: 'doc' });

cardLog.length = 0;
addonCtx.onHome({ docs: { id: 'DOC_TEST_1', title: '会議議事録' } });
const docButtons = cardLog.slice();
addonCtx.onAddonQuick({ docs: { id: 'DOC_TEST_1', title: '会議議事録' }, commonEventObject: { parameters: { action: 'docOutline' } } });

process.stdout.write(JSON.stringify({ initRes, lookRes, askOutline, docButtons }));
"""
    proc = subprocess.run(
        ["node", "-e", node_code],
        input=json.dumps(
            {
                "engine": by_name["Engine"],
                "planner": by_name["ComboPlanner"],
                "server": by_name["ComboServer"],
                "addon": addon_code,
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
    assert res["initRes"]["ok"] is True, res
    assert res["initRes"]["target"]["kind"] == "doc"
    assert len(res["initRes"]["outline"]) == 2
    assert res["askOutline"]["ok"] is True, res
    assert "1. 概要" in res["askOutline"]["text"]
    assert {"章立て", "目次挿入", "表装飾", "ページ番号"} <= set(res["docButtons"])


def test_doc_exam_phrases_all_route_correctly():
    """ws_exam/phrases_文書.tsv の全問が kind='doc' で期待の棚を引けること。"""
    finder = F.Finder()
    lines = (HERE / "ws_exam" / "phrases_文書.tsv").read_text(encoding="utf-8").splitlines()
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        exp_raw, ask = ln.split("\t")[:2]
        exp_list = [e.strip().lstrip("?") for e in exp_raw.split("+") if e.strip()]
        picks, _, _ = finder.find(ask, kind="doc")
        names = [p["name"] for p in picks]
        for exp in exp_list:
            assert exp in names, f"{ask}: expected {exp} in {names}"
