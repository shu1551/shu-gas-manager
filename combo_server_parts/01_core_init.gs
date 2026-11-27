/**
 * combo_server_template.gs - GASコンボ サーバー側実行・サイドバー基盤
 *
 * コンテナバインドスクリプト（サイドバー）およびヘッドレス API（run_function）の両方から
 * 0.2〜0.5秒台の高速実行・即座の選択範囲取得・高速アンドゥ・AI連携（API直結 / 郵便受け）を提供する。
 * Engine（workspace_engine.gs + Catalog + ApiTypes + ws_shelves/*.gs）および
 * ComboPlanner（combo_planner_template.js）と同居して動作する。
 */

// ビルド時（gas_ws_combo.py）に target_ss_id が指定されると埋め込まれる既定ターゲットID
var DEFAULT_TARGET_SS_ID = '';
// 軽量モード（サーバー側 ComboPlanner 除外時）に注入される最小棚サマリー
var COMBO_MINI_SHELVES = null;

// プロパティ・キャッシュキー定数
var COMBO_PROP_TARGET = 'COMBO_TARGET_SS_ID';
var COMBO_PROP_CONFIG = 'COMBO_CONFIG';
var COMBO_PROP_FAST_UNDO = 'COMBO_FAST_UNDO';
var COMBO_PROP_PB_QUEUE = 'COMBO_POSTBOX_Q';
var COMBO_PROP_PB_DONE = 'COMBO_POSTBOX_DONE';
var COMBO_TBL_CACHE_PREFIX = 'COMBO_TBL_';
var COMBO_TBL_CACHE_TTL = 21600; // 6時間

// ---------------------------------------------------------------- メニュー・サイドバー入口

/**
 * スプレッドシートを開いたときにカスタムメニューを追加する。
 * @param {Object} e イベントオブジェクト
 */
function onOpen(e) {
  try {
    SpreadsheetApp.getUi()
      .createMenu('⚡ GASコンボ')
      .addItem('操作窓（サイドバー）を開く', 'showGasComboSidebar')
      .addItem('直前を取り消す', 'comboMenuUndo')
      .addToUi();
  } catch (err) {
    // トリガー外（APIテスト等）でのエラーは無視する
  }
}

/**
 * サイドバー用の HtmlOutput を生成して返す（ライブラリ呼び出し用）。
 */
function createComboSidebarHtml() {
  return HtmlService.createHtmlOutputFromFile('ComboSidebar')
    .setTitle('GASコンボ')
    .setWidth(300);
}

/**
 * GASコンボのサイドバー（幅300px）を開く。
 */
function showGasComboSidebar() {
  SpreadsheetApp.getUi().showSidebar(createComboSidebarHtml());
}

/**
 * メニューから直前の操作を取り消す。
 */
function comboMenuUndo() {
  var res = comboUndo({ ok: false });
  try {
    var ss = comboOpenSs_({});
    ss.toast(res.ok ? ('取り消しました: ' + (res.what || '')) : (res.error || '取り消せませんでした'), 'GASコンボ', 4);
  } catch (err) {}
  return res;
}

// ---------------------------------------------------------------- 対象スプレッドシート・選択範囲

/**
 * ヘッドレス API テスト用にターゲットスプレッドシート ID を人ごとの置き場（UserProperties）へ保存する（同じ大元を使う別の人に書き換えさせない）。
 * @param {string} ssId スプレッドシート ID
 */
function comboSetTestTarget(ssId) {
  var p = PropertiesService.getUserProperties();
  var val = String(ssId || '').trim();
  if (val) {
    p.setProperty(COMBO_PROP_TARGET, val);
  } else {
    p.deleteProperty(COMBO_PROP_TARGET);
  }
  return { ok: true, targetId: val };
}

/**
 * コンテナバインドでは getActiveSpreadsheet() を 0ms で使い、
 * ヘッドレス実行時は req.targetId / COMBO_TARGET_SS_ID / DEFAULT_TARGET_SS_ID で開く。
 * @param {Object} req リクエスト
 * @return {Spreadsheet}
 */
function comboIsDocReq_(req) {
  if (req && (req.kind === 'doc' || (req.target && req.target.kind === 'doc'))) return true;
  if (req && Array.isArray(req.ops) && req.ops.length && req.ops.every(function (o) { return o && /^doc\./.test(String(o.shelf || '')); })) return true;
  if (req && req.kind === 'sheet') return false;
  try {
    if (typeof SpreadsheetApp !== 'undefined' && typeof SpreadsheetApp.getActiveSpreadsheet === 'function' && SpreadsheetApp.getActiveSpreadsheet()) return false;
  } catch (e1) {}
  try {
    if (typeof DocumentApp !== 'undefined' && typeof DocumentApp.getActiveDocument === 'function' && DocumentApp.getActiveDocument()) return true;
  } catch (e2) {}
  return false;
}

function comboOpenDoc_(req) {
  req = req || {};
  var reqId = String(req.targetId || (req.target && req.target.id) || '').trim();
  var active = null;
  try {
    if (typeof DocumentApp !== 'undefined' && typeof DocumentApp.getActiveDocument === 'function') {
      active = DocumentApp.getActiveDocument();
    }
  } catch (e) {}
  if (active && (!reqId || req.assumeActive === true || active.getId() === reqId)) {
    return active;
  }
  var propId = '';
  try {
    propId = PropertiesService.getUserProperties().getProperty(COMBO_PROP_TARGET) || '';
  } catch (e2) {}
  var id = reqId || propId || '';
  if (id && typeof DocumentApp !== 'undefined' && typeof DocumentApp.openById === 'function') {
    return DocumentApp.openById(id);
  }
  if (active) return active;
  throw new ArgError('対象のドキュメントを開けません（targetId を指定してください）');
}

function comboDocOutline_(doc) {
  var out = [];
  try {
    var body = doc && typeof doc.getBody === 'function' ? doc.getBody() : null;
    if (!body || typeof body.getNumChildren !== 'function') return out;
    var n = body.getNumChildren();
    for (var i = 0; i < n; i++) {
      var ch = body.getChild(i);
      if (typeof DocumentApp !== 'undefined' && DocumentApp.ElementType && ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
        var p = ch.asParagraph();
        var h = p.getHeading();
        if (h && DocumentApp.ParagraphHeading && h !== DocumentApp.ParagraphHeading.NORMAL) {
          var txt = String(p.getText() || '').trim();
          if (txt) out.push({ level: String(h), text: txt });
        }
      }
    }
  } catch (e) {}
  return out;
}

function comboOpenSs_(req) {
  req = req || {};
  var reqId = String(req.targetId || (req.target && req.target.id) || '').trim();
  var active = null;
  try {
    active = SpreadsheetApp.getActiveSpreadsheet();
  } catch (e) {}
  if (active && (!reqId || req.assumeActive === true || active.getId() === reqId)) {
    return active;
  }
  var propId = '';
  try {
    propId = PropertiesService.getUserProperties().getProperty(COMBO_PROP_TARGET) || '';
  } catch (e2) {}
  var id = reqId || propId || DEFAULT_TARGET_SS_ID || '';
  if (id) {
    return SpreadsheetApp.openById(id);
  }
  if (active) {
    return active;
  }
  throw new ArgError('対象のスプレッドシートを開けません（COMBO_TARGET_SS_ID を設定してください）');
}

/**
 * 現在のシート名と選択セル範囲（A1表記）を取得する。
 * @param {Spreadsheet} ss
 * @param {Object} req
 * @return {{sheet: string, selection: string}}
 */
function comboGetSelectionInfo_(ss, req, skipLookup) {
  req = req || {};
  var reqSheet = String(req.sheet || (req.target && req.target.sheet) || '').trim();
  // sheet が指定済みで selection 指定済み、または選択範囲不要な ops 実行時は API 呼び出しを省略する
  if (reqSheet && (req.selection !== undefined || skipLookup)) {
    return { sheet: reqSheet, selection: String(req.selection || '').trim().toUpperCase() };
  }
  var activeSh = null;
  try {
    activeSh = ss.getActiveSheet();
  } catch (e) {}
  var sh = null;
  if (reqSheet) {
    sh = ss.getSheetByName(reqSheet);
    if (!sh) {
      throw new ArgError('シート「' + reqSheet + '」がありません。あるのは: ' + ss.getSheets().map(function (s) { return s.getName(); }).join('、'));
    }
  } else {
    sh = activeSh || ss.getSheets()[0];
  }
  var sheetName = sh.getName();
  var sel = String(req.selection || '').trim().toUpperCase();
  if (!sel && activeSh && activeSh.getName() === sheetName) {
    try {
      var rg = activeSh.getActiveRange();
      if (rg) sel = rg.getA1Notation();
    } catch (e2) {}
  }
  if (!sel && !reqSheet) {
    try {
      var rg2 = ss.getActiveRange();
      if (rg2) sel = rg2.getA1Notation();
    } catch (e3) {}
  }
  return { sheet: sheetName, selection: sel };
}

// ---------------------------------------------------------------- 表メタデータキャッシュ

function comboCache_() {
  try {
    if (typeof CacheService !== 'undefined' && typeof CacheService.getUserCache === 'function') {
      var uc = CacheService.getUserCache();
      if (uc) return uc;
    }
  } catch (eU) {}
  try {
    if (typeof CacheService !== 'undefined' && typeof CacheService.getScriptCache === 'function') {
      return CacheService.getScriptCache();
    }
  } catch (eS) {}
  return null;
}

function comboTblCacheKey_(ssId, sheetName) {
  if (sheetName === undefined) {
    sheetName = ssId;
    ssId = '';
  }
  return COMBO_TBL_CACHE_PREFIX + (ssId ? String(ssId).slice(0, 44) + '_' : '') + String(sheetName || '').slice(0, 150);
}

function comboCacheGet_(ssId, sheetName) {
  try {
    var c = comboCache_();
    if (!c) return null;
    var raw = c.get(comboTblCacheKey_(ssId, sheetName)) || c.get(comboTblCacheKey_(sheetName));
    if (!raw) return null;
    var obj = JSON.parse(raw);
    if (obj && obj.ssId === ssId) return obj;
  } catch (e) {}
  return null;
}

function comboComputeTitleA1_(sh, tb) {
  if (!sh || !tb || !tb.headerRow || tb.headerRow <= 1) return '';
  var prevCache = _TBL_CACHE;
  try {
    if (!_TBL_CACHE) _TBL_CACHE = {};
    if (typeof sh.getSheetId === 'function') _TBL_CACHE[sh.getSheetId()] = tb;
    return titleRange_(sh).getA1Notation();
  } catch (e) {
    return '';
  } finally {
    _TBL_CACHE = prevCache || null;
  }
}

function comboCachePut_(ssId, sheetName, table, sheets, tb, ssName, titleA1) {
  try {
    var effTitleA1 = titleA1 || (table && table.title_a1) || '';
    if (table && effTitleA1 && !table.title_a1) table.title_a1 = effTitleA1;
    var payload = {
      ssId: ssId,
      ssName: ssName || '',
      titleA1: effTitleA1,
      table: table || null,
      sheets: sheets || null,
      ts: Date.now()
    };
    if (tb && tb.vals) {
      payload.rawTable = {
        headerRow: tb.headerRow,
        firstCol: tb.firstCol,
        lastCol: tb.lastCol,
        firstData: tb.firstData,
        lastData: tb.lastData,
        totalRow: tb.totalRow,
        vals: tb.vals
      };
    }
    var s = JSON.stringify(payload);
    if (s.length >= 95000 && payload.rawTable) {
      // 巨大シートでも先頭行を残して titleRange_ が 0ms でタイトルを特定できるようにする
      var headKeep = Math.max(10, (tb.headerRow || 1) + 2);
      payload.rawTable.vals = tb.vals.slice(0, headKeep);
      payload.rawTable.headOnly = true;
      s = JSON.stringify(payload);
      if (s.length >= 95000) {
        delete payload.rawTable;
        s = JSON.stringify(payload);
      }
    }
    if (s.length < 95000) {
      var c = comboCache_();
      if (c) c.put(comboTblCacheKey_(ssId, sheetName), s, COMBO_TBL_CACHE_TTL);
    }
  } catch (e) {}
}

function comboCacheInvalidate_(ssId, sheetName) {
  try {
    var c = comboCache_();
    if (!c) return;
    if (sheetName === undefined) {
      c.remove(comboTblCacheKey_(ssId));
    } else {
      c.remove(comboTblCacheKey_(ssId, sheetName));
      c.remove(comboTblCacheKey_(sheetName));
    }
  } catch (e) {}
}

function comboParseScope_(selection) {
  if (!selection || typeof ComboPlanner === 'undefined' || typeof ComboPlanner.parseSelectionScope !== 'function') {
    return null;
  }
  try {
    return ComboPlanner.parseSelectionScope(selection);
  } catch (e) {
    return null;
  }
}

// ---------------------------------------------------------------- 初期化・選択監視・Look

function comboGetOAuthToken_() {
  try {
    if (typeof ScriptApp !== 'undefined' && typeof ScriptApp.getOAuthToken === 'function') {
      return ScriptApp.getOAuthToken() || '';
    }
  } catch (e) {}
  return '';
}

/**
 * サイドバー起動時・リロード時の初期情報を一括取得する。
 * @param {Object} req
 */
function comboInit(req) {
  var t0 = Date.now();
  try {
    req = req || {};
    var allProps = null;
    try { allProps = PropertiesService.getUserProperties().getProperties() || null; } catch (eP) {}
    if (comboIsDocReq_(req)) {
      var doc = comboOpenDoc_(req);
      var docId = doc.getId();
      var docName = doc.getName();
      var docOutline = comboDocOutline_(doc);
      var docOut = {
        ok: true,
        target: {
          id: docId,
          name: docName,
          kind: 'doc',
          url: 'https://docs.google.com/document/d/' + docId + '/edit',
          sheet: ''
        },
        oauthToken: comboGetOAuthToken_(),
        sheets: [],
        sheetInfos: [],
        table: null,
        outline: docOutline,
        selection: '',
        scope: null,
        config: comboSanitizeConfig_(comboGetRawConfig_(allProps)),
        postboxPendingCount: comboPostboxPoll().count
      };
      if (req.includeQuick) {
        docOut.quick = comboQuickList({
          force: !!req.forceQuick,
          targetId: docId,
          _skipToken: true,
          _allProps: allProps,
          wantCodes: !!req.wantCodes,
          clientStamp: req.clientStamp || ''
        });
      }
      docOut.gasMs = Date.now() - t0;
      return docOut;
    }
    var ss = comboOpenSs_(req);
    var tOpen = Date.now();
    var selInfo = comboGetSelectionInfo_(ss, req);
    var sh = sheetOf_(ss, selInfo.sheet, '');
    var sheetInfos = ss.getSheets().map(function (s) {
      return {
        name: s.getName(),
        sheetId: typeof s.getSheetId === 'function' ? s.getSheetId() : 0,
        rows: s.getLastRow(),
        cols: s.getLastColumn()
      };
    });
    var sheets = sheetInfos.map(function (s) { return s.name; });
    var tSheets = Date.now();
    var ssId = ss.getId();
    var ssName = ss.getName();
    var tb = findTable_(sh);
    var table = tb ? tableOut_(tb) : null;
    var titleA1 = comboComputeTitleA1_(sh, tb);
    if (table && titleA1) table.title_a1 = titleA1;
    comboCachePut_(ssId, sh.getName(), table, sheets, tb, ssName, titleA1);
    var tTable = Date.now();
    var out = {
      ok: true,
      target: {
        id: ssId,
        name: ssName,
        kind: 'sheet',
        url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit',
        sheet: sh.getName()
      },
      sheetId: typeof sh.getSheetId === 'function' ? sh.getSheetId() : 0,
      oauthToken: comboGetOAuthToken_(),
      sheets: sheets,
      sheetInfos: sheetInfos,
      table: table,
      selection: selInfo.selection,
      scope: comboParseScope_(selInfo.selection),
      config: comboSanitizeConfig_(comboGetRawConfig_(allProps)),
      postboxPendingCount: comboPostboxPoll().count
    };
    var tPost = Date.now();
    if (req.includeQuick) {
      out.quick = comboQuickList({
        force: !!req.forceQuick,
        targetId: ssId,
        _skipToken: true,
        _allProps: allProps,
        wantCodes: !!req.wantCodes,
        clientStamp: req.clientStamp || ''
      });
    }
    var tQuick = Date.now();
    if (req.includeLearned) {
      out.learned = comboGetLearned().learned;
    }
    var tEnd = Date.now();
    out.gasMs = tEnd - t0;
    out.timings = {
      openMs: tOpen - t0,
      sheetsMs: tSheets - tOpen,
      tableMs: tTable - tSheets,
      metaPostboxMs: tPost - tTable,
      quickMs: tQuick - tPost,
      learnedMs: tEnd - tQuick
    };
    return out;
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

/**
 * サイドバーからの軽量ポーリング：現在のシート・選択範囲・郵便受け完了結果を返す。
 * @param {Object} req
 */
function comboPollSelection(req) {
  var t0 = Date.now();
  try {
    req = req || {};
    if (req.postboxOnly && req.targetId) {
      return {
        ok: true,
        postboxDone: comboPopPostboxDone_(String(req.targetId).trim()),
        gasMs: Date.now() - t0
      };
    }
    if (comboIsDocReq_(req)) {
      var docP = comboOpenDoc_(req);
      return {
        ok: true,
        kind: 'doc',
        sheet: '',
        selection: '',
        scope: null,
        oauthToken: comboGetOAuthToken_(),
        postboxDone: comboPopPostboxDone_(docP.getId()),
        gasMs: Date.now() - t0
      };
    }
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var postboxDone = comboPopPostboxDone_(ss.getId());
    var out = {
      ok: true,
      sheet: selInfo.sheet,
      selection: selInfo.selection,
      scope: comboParseScope_(selInfo.selection),
      oauthToken: comboGetOAuthToken_(),
      postboxDone: postboxDone
    };
    var prevSheet = String(req.prevSheet || '').trim();
    if (prevSheet && selInfo.sheet && selInfo.sheet !== prevSheet) {
      var sh = sheetOf_(ss, selInfo.sheet, '');
      var sheetInfos = ss.getSheets().map(function (s) {
        return {
          name: s.getName(),
          sheetId: typeof s.getSheetId === 'function' ? s.getSheetId() : 0,
          rows: s.getLastRow(),
          cols: s.getLastColumn()
        };
      });
      var sheets = sheetInfos.map(function (s) { return s.name; });
      var ssId = ss.getId();
      var ssName = ss.getName();
      var tb = findTable_(sh);
      var table = tb ? tableOut_(tb) : null;
      var titleA1 = comboComputeTitleA1_(sh, tb);
      if (table && titleA1) table.title_a1 = titleA1;
      comboCachePut_(ssId, sh.getName(), table, sheets, tb, ssName, titleA1);
      out.sheetChanged = true;
      out.sheetId = typeof sh.getSheetId === 'function' ? sh.getSheetId() : 0;
      out.sheets = sheets;
      out.sheetInfos = sheetInfos;
      out.table = table;
    }
    if (req.checkPostbox) {
      out.postboxPending = comboPostboxPoll().count;
    }
    out.gasMs = Date.now() - t0;
    return out;
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

/**
 * look 結果を見やすいテキスト（ws_look 互換）に整形する。
 */
function comboFormatLookText_(target, sheetInfos, table, side, rangeInfo) {
  var lines = [
    '対象: ' + target.name + ' › ' + target.sheet,
    'URL: ' + target.url,
    'シート: ' + sheetInfos.map(function (s) { return s.name + '（' + s.rows + '行×' + s.cols + '列）'; }).join('、')
  ];
  if (table) {
    lines.push(
      '表: 見出し ' + table.header_row + ' 行目・' + table.first_col + '〜' + table.last_col +
      ' 列・明細 ' + table.data + ' 行目' + (table.total_row ? '・合計行 ' + table.total_row + ' 行目' : '・合計行なし')
    );
    lines.push('列: ' + table.columns.map(function (c) { return c.col + '=' + c.name + (c.number ? '(数値)' : ''); }).join('、'));
  } else {
    lines.push('表: 見つかりません（空のシート、または見出しの行がありません）');
  }
  (side || []).forEach(function (ln) { lines.push(ln); });
  if (rangeInfo && rangeInfo.values) {
    lines.push('中身 ' + rangeInfo.range + ':');
    var fm = rangeInfo.formulas || [];
    var lim = Math.min(rangeInfo.values.length, 60);
    for (var i = 0; i < lim; i++) {
      var row = rangeInfo.values[i];
      var cells = [];
      for (var j = 0; j < row.length; j++) {
        var f = (fm[i] && fm[i][j]) ? fm[i][j] : '';
        cells.push(row[j] + (f ? '  {' + f + '}' : ''));
      }
      lines.push(cells.join('\t'));
    }
  }
  return lines.join('\n');
}

/**
 * 指定シート・アクティブシートの表構造を検査し、CacheService にキャッシュする。
 * @param {Object} req
 */
function comboLook(req) {
  var t0 = Date.now();
  try {
    req = req || {};
    if (comboIsDocReq_(req)) {
      var doc = comboOpenDoc_(req);
      var docId = doc.getId();
      var docName = doc.getName();
      var outline = comboDocOutline_(doc);
      var docUrl = 'https://docs.google.com/document/d/' + docId + '/edit';
      var docTarget = { id: docId, name: docName, kind: 'doc', url: docUrl, sheet: '' };
      var linesD = [
        '対象: [文書] ' + docName,
        'URL: ' + docUrl,
        outline.length ? ('見出し（' + outline.length + ' 件）: ' + outline.slice(0, 8).map(function (x) { return x.text; }).join(' ／ ')) : '見出し: なし'
      ];
      return {
        ok: true,
        target: docTarget,
        oauthToken: comboGetOAuthToken_(),
        sheets: [],
        sheetInfos: [],
        table: null,
        outline: outline,
        text: linesD.join('\n'),
        gasMs: Date.now() - t0
      };
    }
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var sh = sheetOf_(ss, req.sheet || selInfo.sheet, '');
    var sheetInfos = ss.getSheets().map(function (s) {
      return {
        name: s.getName(),
        sheetId: typeof s.getSheetId === 'function' ? s.getSheetId() : 0,
        rows: s.getLastRow(),
        cols: s.getLastColumn()
      };
    });
    var sheets = sheetInfos.map(function (s) { return s.name; });
    var ssId = ss.getId();
    var ssName = ss.getName();
    var tb = findTable_(sh);
    var table = tb ? tableOut_(tb) : null;
    var titleA1 = comboComputeTitleA1_(sh, tb);
    if (table && titleA1) table.title_a1 = titleA1;
    comboCachePut_(ssId, sh.getName(), table, sheets, tb, ssName, titleA1);

    var side = [];
    if (!req.fast) {
      try { side = lookSide_(ss, sh); } catch (eS) {}
    }

    var rangeInfo = null;
    if (req.range) {
      var rg = sh.getRange(req.range);
      rangeInfo = {
        range: req.range,
        values: rg.getDisplayValues(),
        formulas: rg.getFormulas()
      };
    }

    var target = {
      id: ssId,
      name: ssName,
      kind: 'sheet',
      url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit',
      sheet: sh.getName()
    };
    var text = comboFormatLookText_(target, sheetInfos, table, side, rangeInfo);
    return {
      ok: true,
      target: target,
      sheetId: typeof sh.getSheetId === 'function' ? sh.getSheetId() : 0,
      oauthToken: comboGetOAuthToken_(),
      sheets: sheets,
      sheetInfos: sheetInfos,
      table: table,
      selection: selInfo.selection,
      scope: comboParseScope_(selInfo.selection),
      side: side,
      values: rangeInfo ? rangeInfo.values : undefined,
      formulas: rangeInfo ? rangeInfo.formulas : undefined,
      text: text,
      gasMs: Date.now() - t0
    };
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      text: 'エラー: ' + String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

// ---------------------------------------------------------------- 高速アンドゥ（backup=false 用）

  var COMBO_FAST_UNDO_SAFE_SHELVES_ = {
    'format': 1, 'bg.clear': 1, 'freeze': 1, 'unfreeze': 1, 'width': 1,
    'write': 1, 'clear.values': 1, 'clear.format': 1, 'clear.all': 1,
    'renumber': 1, 'formula.guard': 1, 'formula.tovalue': 1, 'round': 1,
    'text.case': 1, 'text.affix': 1, 'date.fix': 1, 'number.fix': 1, 'fill.series': 1, 'fill.date': 1,
    'fill.down': 1, 'fill.blank': 1, 'replace': 1, 'copy': 1, 'copy.values': 1, 'copy.format': 1
  };

function comboEncodeCellVal_(v, formula) {
  if (formula && String(formula).charAt(0) === '=') return formula;
  if (v instanceof Date) return { __dt: v.getTime() };
  return v;
}

function comboDecodeCellVal_(v) {
  if (v && typeof v === 'object' && v.__dt !== undefined) return new Date(v.__dt);
  return v;
}

/**
 * backup=false の高速実行時、変更対象範囲の状態を CacheService へ軽量スナップショットする。
 * format のみの場合は実際に変更する属性（color / bg / bold 等）だけを取得し、API 往復を最小化する。
 */
function comboFastUndoSave_(sh, ops, table, optSsId) {
  var cache = comboCache_();
  try {
    var ssId = optSsId || (typeof sh.getParent === 'function' ? sh.getParent().getId() : '');
    // 安全に戻せる棚のホワイトリスト外が含まれる場合は控えを作らず、既存控えも消す
    for (var i = 0; i < ops.length; i++) {
      var op0 = ops[i];
      if (!op0 || !COMBO_FAST_UNDO_SAFE_SHELVES_[op0.shelf] ||
          (op0.shelf === 'format' && (op0.borders !== undefined || op0.merge !== undefined)) ||
          (op0.shelf === 'write' && op0.tsv !== undefined) || op0.all_sheets) {
        if (cache) cache.remove(COMBO_PROP_FAST_UNDO);
        return false;
      }
    }

    var minR = Infinity, minC = Infinity, maxR = 0, maxC = 0;
    var addRange = function (rg) {
      if (!rg) return;
      var r0 = rg.getRow(), c0 = rg.getColumn();
      var r1 = r0 + rg.getNumRows() - 1, c1 = c0 + rg.getNumColumns() - 1;
      if (r0 < minR) minR = r0;
      if (c0 < minC) minC = c0;
      if (r1 > maxR) maxR = r1;
      if (c1 > maxC) maxC = c1;
    };

    var hasWidth = false;
    var needFullSheet = false;
    var formatOnly = true;
    var freezeOnly = true;
    var widthOnly = true;
    var fmtFlags = {};
    for (var j = 0; j < ops.length; j++) {
      var op = ops[j];
      if ((op.shelf !== 'format' && op.shelf !== 'bg.clear') || op.merge !== undefined || op.borders !== undefined) formatOnly = false;
      if (op.shelf !== 'freeze' && op.shelf !== 'unfreeze') freezeOnly = false;
      if (op.shelf !== 'width') widthOnly = false;
      if (op.shelf === 'bg.clear') fmtFlags.bgs = true;
      if (op.shelf === 'format') {
        if (op.color !== undefined) fmtFlags.colors = true;
        if (op.bg !== undefined) fmtFlags.bgs = true;
        if (op.bold !== undefined) fmtFlags.weights = true;
        if (op.italic !== undefined) fmtFlags.styles = true;
        if (op.size !== undefined) fmtFlags.sizes = true;
        if (op.font !== undefined) fmtFlags.fonts = true;
        if (op.align !== undefined) fmtFlags.aligns = true;
        if (op.valign !== undefined) fmtFlags.valigns = true;
        if (op.number_format !== undefined) fmtFlags.numFmts = true;
        if (op.wrap !== undefined) fmtFlags.wraps = true;
      }
      if (op.shelf === 'width') hasWidth = true;
      if (op.range && !/^(all|\*|全体|全セル|シート全体|sheet)$/i.test(String(op.range).trim())) {
        try { addRange(sh.getRange(op.range)); continue; } catch (eR) {}
      }
      if (op.title) {
        try { addRange(titleRange_(sh)); continue; } catch (eT) {}
      }
      if (op.header && table && table.header_row && table.first_col && table.last_col) {
        try {
          var fc = colNum_(table.first_col), lc = colNum_(table.last_col);
          addRange(sh.getRange(table.header_row, fc, 1, lc - fc + 1));
          continue;
        } catch (eH) {}
      }
      if (op.col && table) {
        try {
          var tObj = findTable_(sh);
          if (tObj) {
            var ci = colIndexOf_(tObj, op.col);
            var endR = tObj.totalRow || tObj.lastData;
            addRange(sh.getRange(tObj.firstData, ci, Math.max(1, endR - tObj.firstData + 1), 1));
            continue;
          }
        } catch (eC) {}
      }
      if (op.cells && typeof op.cells === 'object') {
        var keys = Object.keys(op.cells);
        if (keys.length) {
          keys.forEach(function (k) { try { addRange(sh.getRange(k)); } catch (eK) {} });
          continue;
        }
      }
      if (op.shelf === 'freeze' || op.shelf === 'unfreeze') {
        addRange(sh.getRange(1, 1));
        continue;
      }
      needFullSheet = true;
    }

    if (needFullSheet || minR === Infinity) {
      var lr = sh.getLastRow(), lc2 = sh.getLastColumn();
      if (lr < 1 || lc2 < 1) {
        minR = 1; minC = 1; maxR = 1; maxC = 1;
      } else if (lr * lc2 <= 800) {
        minR = 1; minC = 1; maxR = lr; maxC = lc2;
      } else {
        cache.remove(COMBO_PROP_FAST_UNDO);
        return false;
      }
    }

    var nr = maxR - minR + 1, nc = maxC - minC + 1;
    if (nr * nc > 800) {
      cache.remove(COMBO_PROP_FAST_UNDO);
      return false;
    }

    var targetRg = sh.getRange(minR, minC, nr, nc);
    var snap = {
      ssId: ssId,
      sheetName: sh.getName(),
      r: minR,
      c: minC,
      nr: nr,
      nc: nc,
      a1: targetRg.getA1Notation(),
      what: ops.map(function (o) { return o.shelf; }).join('・'),
      ts: Date.now()
    };

    if (formatOnly && Object.keys(fmtFlags).length) {
      snap.partial = true;
      if (fmtFlags.colors) snap.colors = targetRg.getFontColors();
      if (fmtFlags.bgs) snap.bgs = targetRg.getBackgrounds();
      if (fmtFlags.weights) snap.weights = targetRg.getFontWeights();
      if (fmtFlags.styles) snap.styles = targetRg.getFontStyles();
      if (fmtFlags.sizes) snap.sizes = targetRg.getFontSizes();
      if (fmtFlags.fonts) snap.fonts = targetRg.getFontFamilies();
      if (fmtFlags.aligns) snap.aligns = targetRg.getHorizontalAlignments();
      if (fmtFlags.valigns) snap.valigns = targetRg.getVerticalAlignments();
      if (fmtFlags.numFmts) snap.numFmts = targetRg.getNumberFormats();
      if (fmtFlags.wraps) snap.wraps = targetRg.getWraps();
    } else if (freezeOnly) {
      snap.partial = true;
      snap.frozenR = sh.getFrozenRows();
      snap.frozenC = sh.getFrozenColumns();
    } else if (widthOnly) {
      snap.partial = true;
    } else {
      var rawVals = targetRg.getValues();
      var rawFormulas = targetRg.getFormulas();
      var vals = [];
      for (var r = 0; r < nr; r++) {
        var rowOut = [];
        for (var c = 0; c < nc; c++) {
          rowOut.push(comboEncodeCellVal_(rawVals[r][c], rawFormulas[r][c]));
        }
        vals.push(rowOut);
      }
      snap.vals = vals;
      snap.bgs = targetRg.getBackgrounds();
      snap.colors = targetRg.getFontColors();
      snap.weights = targetRg.getFontWeights();
      snap.styles = targetRg.getFontStyles();
      snap.sizes = targetRg.getFontSizes();
      snap.aligns = targetRg.getHorizontalAlignments();
      snap.numFmts = targetRg.getNumberFormats();
      snap.frozenR = sh.getFrozenRows();
      snap.frozenC = sh.getFrozenColumns();
    }

    if (hasWidth) {
      var cw = {};
      var wEnd = Math.min(maxC, Math.max(sh.getLastColumn(), maxC));
      for (var wc = minC; wc <= wEnd; wc++) {
        cw[wc] = sh.getColumnWidth(wc);
      }
      snap.colWidths = cw;
    }

    var stack = [];
    try {
      var prevRaw = cache ? cache.get(COMBO_PROP_FAST_UNDO) : null;
      if (prevRaw) {
        var prevParsed = JSON.parse(prevRaw);
        if (prevParsed && prevParsed.__gz) {
          var prevUnz = Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(prevParsed.__gz), 'application/x-gzip')).getDataAsString('utf-8');
          prevParsed = JSON.parse(prevUnz);
        }
        if (prevParsed && Array.isArray(prevParsed.__stack)) {
          stack = prevParsed.__stack.filter(function (x) { return x && x.ssId === snap.ssId && x.kind !== 'sheetcopy'; });
        } else if (prevParsed && prevParsed.ssId === snap.ssId && prevParsed.kind !== 'sheetcopy') {
          stack = [prevParsed];
        }
      }
    } catch (ePrev) { stack = []; }
    stack.push(snap);
    if (stack.length > 5) stack = stack.slice(stack.length - 5);

    var encodeStack = function (arr) {
      var s = JSON.stringify({ __stack: arr, ssId: snap.ssId });
      if (s.length > 50000) {
        var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(s, 'application/json')).getBytes());
        s = JSON.stringify({ __gz: gz, ssId: snap.ssId });
      }
      return s;
    };
    var jsonStr = encodeStack(stack);
    while (jsonStr.length > 95000 && stack.length > 1) {
      stack.shift();
      jsonStr = encodeStack(stack);
    }
    if (jsonStr.length > 95000) {
      cache.remove(COMBO_PROP_FAST_UNDO);
      return false;
    }
    cache.put(COMBO_PROP_FAST_UNDO, jsonStr, COMBO_TBL_CACHE_TTL);
    return true;
  } catch (err) {
    try { cache.remove(COMBO_PROP_FAST_UNDO); } catch (eDel) {}
    return false;
  }
}

/**
 * CacheService（または互換 ScriptProperties）の高速アンドゥスナップショットからシート状態を即時復元する。
 */
function comboFastUndoRestore_(ss, optRaw) {
  var t0 = Date.now();
  var cache = comboCache_();
  var raw = optRaw || (cache ? cache.get(COMBO_PROP_FAST_UNDO) : null);
  var fromProp = false;
  if (!raw) {
    try {
      raw = PropertiesService.getScriptProperties().getProperty(COMBO_PROP_FAST_UNDO);
      if (raw) fromProp = true;
    } catch (eP) {}
  }
  if (!raw) {
    return { ok: false, error: '戻せる高速控えがありません' };
  }
  var parsed, stack = null, snap;
  try {
    parsed = JSON.parse(raw);
    if (parsed && parsed.__gz) {
      var unz = Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(parsed.__gz), 'application/x-gzip')).getDataAsString('utf-8');
      parsed = JSON.parse(unz);
    }
    if (parsed && Array.isArray(parsed.__stack)) {
      stack = parsed.__stack.slice();
      snap = stack.pop();
    } else {
      snap = parsed;
    }
  } catch (e) {
    if (cache) cache.remove(COMBO_PROP_FAST_UNDO);
    return { ok: false, error: '高速控えのデータが壊れていました' };
  }
  var ssId = ss.getId();
  if (!snap || snap.ssId !== ssId) {
    return { ok: false, error: '現在のスプレッドシートの高速控えがありません' };
  }
  if (snap.kind === 'sheetcopy') {
    return quickRestoreSheetCopy_(ss, snap, stack, fromProp);
  }
  var sh = ss.getSheetByName(snap.sheetName);
  if (!sh) {
    return { ok: false, error: 'シート「' + snap.sheetName + '」が見つかりません' };
  }

  var rg = sh.getRange(snap.r, snap.c, snap.nr, snap.nc);
  if (snap.vals !== undefined) {
    var restoredVals = snap.vals.map(function (row) {
      return row.map(comboDecodeCellVal_);
    });
    rg.setValues(restoredVals);
  }
  if (snap.bgs !== undefined) rg.setBackgrounds(snap.bgs);
  if (snap.colors !== undefined) rg.setFontColors(snap.colors);
  if (snap.weights !== undefined) rg.setFontWeights(snap.weights);
  if (snap.styles !== undefined) rg.setFontStyles(snap.styles);
  if (snap.sizes !== undefined) rg.setFontSizes(snap.sizes);
  if (snap.fonts !== undefined) rg.setFontFamilies(snap.fonts);
  if (snap.aligns !== undefined) rg.setHorizontalAlignments(snap.aligns);
  if (snap.valigns !== undefined) rg.setVerticalAlignments(snap.valigns);
  if (snap.numFmts !== undefined) rg.setNumberFormats(snap.numFmts);
  if (snap.wraps !== undefined) rg.setWraps(snap.wraps);

  if (snap.frozenR !== undefined && sh.getFrozenRows() !== snap.frozenR) sh.setFrozenRows(snap.frozenR);
  if (snap.frozenC !== undefined && sh.getFrozenColumns() !== snap.frozenC) sh.setFrozenColumns(snap.frozenC);
  if (snap.colWidths) {
    Object.keys(snap.colWidths).forEach(function (k) {
      sh.setColumnWidth(parseInt(k, 10), snap.colWidths[k]);
    });
  }
  try { SpreadsheetApp.flush(); } catch (eFl) {}

  if (cache) {
    if (stack && stack.length > 0) {
      var restStr = JSON.stringify({ __stack: stack, ssId: ssId });
      if (restStr.length > 50000) {
        var gzRest = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(restStr, 'application/json')).getBytes());
        restStr = JSON.stringify({ __gz: gzRest, ssId: ssId });
      }
      if (restStr.length <= 95000) cache.put(COMBO_PROP_FAST_UNDO, restStr, COMBO_TBL_CACHE_TTL);
      else cache.remove(COMBO_PROP_FAST_UNDO);
    } else {
      cache.remove(COMBO_PROP_FAST_UNDO);
    }
  }
  if (fromProp) {
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eDelP) {}
  }
  // 書式・色・固定・幅のみの部分復元では表構造が変わらないためキャッシュを温存する
  if (!snap.partial) {
    comboCacheInvalidate_(ssId, snap.sheetName);
  }

  var cachedUndo = comboCacheGet_(ssId, sh.getName());
  var target = {
    id: ssId,
    name: (cachedUndo && cachedUndo.ssName) || ss.getName(),
    kind: 'sheet',
    url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit',
    sheet: sh.getName()
  };
  var text = [
    '対象: ' + target.name + ' › ' + target.sheet,
    '戻した: ' + snap.a1 + '（' + (snap.what || '直前の変更') + '）を取り消しました（高速戻し）'
  ].join('\n');
  return {
    ok: true,
    fast: true,
    undone: 'fast',
    what: snap.what,
    target: target,
    oauthToken: comboGetOAuthToken_(),
    text: text,
    gasMs: Date.now() - t0
  };
}

