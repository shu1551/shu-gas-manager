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
 * ヘッドレス API テスト用にターゲットスプレッドシート ID を ScriptProperties へ保存する。
 * @param {string} ssId スプレッドシート ID
 */
function comboSetTestTarget(ssId) {
  var p = PropertiesService.getScriptProperties();
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
    propId = PropertiesService.getScriptProperties().getProperty(COMBO_PROP_TARGET) || '';
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

function comboTblCacheKey_(sheetName) {
  return COMBO_TBL_CACHE_PREFIX + String(sheetName || '').slice(0, 200);
}

function comboCacheGet_(ssId, sheetName) {
  try {
    var raw = CacheService.getScriptCache().get(comboTblCacheKey_(sheetName));
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
      CacheService.getScriptCache().put(comboTblCacheKey_(sheetName), s, COMBO_TBL_CACHE_TTL);
    }
  } catch (e) {}
}

function comboCacheInvalidate_(sheetName) {
  try {
    CacheService.getScriptCache().remove(comboTblCacheKey_(sheetName));
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
    var ss = comboOpenSs_(req);
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
    var ssId = ss.getId();
    var ssName = ss.getName();
    var tb = findTable_(sh);
    var table = tb ? tableOut_(tb) : null;
    var titleA1 = comboComputeTitleA1_(sh, tb);
    if (table && titleA1) table.title_a1 = titleA1;
    comboCachePut_(ssId, sh.getName(), table, sheets, tb, ssName, titleA1);
    return {
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
      config: comboGetConfig(),
      postboxPendingCount: comboPostboxPoll().count,
      gasMs: Date.now() - t0
    };
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
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var postboxDone = comboPopPostboxDone_(ss.getId());
    var out = {
      ok: true,
      sheet: selInfo.sheet,
      selection: selInfo.selection,
      scope: comboParseScope_(selInfo.selection),
      postboxDone: postboxDone,
      gasMs: Date.now() - t0
    };
    if (req.checkPostbox) {
      out.postboxPending = comboPostboxPoll().count;
    }
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

var COMBO_STRUCTURAL_SHELVES_ = {
  'sheet.add': 1, 'sheet.delete': 1, 'sheet.rename': 1,
  'sheet.move': 1, 'sheet.copy': 1, 'sheet.hide': 1, 'sheet.show': 1
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
  var cache = CacheService.getScriptCache();
  try {
    var ssId = optSsId || (typeof sh.getParent === 'function' ? sh.getParent().getId() : '');
    // シート構成そのものを変える操作は高速スナップショット対象外
    for (var i = 0; i < ops.length; i++) {
      if (COMBO_STRUCTURAL_SHELVES_[ops[i].shelf]) {
        cache.remove(COMBO_PROP_FAST_UNDO);
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
      if (op.shelf !== 'format' || op.merge !== undefined || op.borders !== undefined) formatOnly = false;
      if (op.shelf !== 'freeze' && op.shelf !== 'unfreeze') freezeOnly = false;
      if (op.shelf !== 'width') widthOnly = false;
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

    var jsonStr = JSON.stringify(snap);
    if (jsonStr.length > 50000) {
      var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(jsonStr, 'application/json')).getBytes());
      jsonStr = JSON.stringify({ __gz: gz, ssId: snap.ssId });
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
  var cache = CacheService.getScriptCache();
  var raw = optRaw || cache.get(COMBO_PROP_FAST_UNDO);
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
  var snap;
  try {
    snap = JSON.parse(raw);
    if (snap && snap.__gz) {
      var unz = Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(snap.__gz), 'application/x-gzip')).getDataAsString('utf-8');
      snap = JSON.parse(unz);
    }
  } catch (e) {
    cache.remove(COMBO_PROP_FAST_UNDO);
    return { ok: false, error: '高速控えのデータが壊れていました' };
  }
  var ssId = ss.getId();
  if (!snap || snap.ssId !== ssId) {
    return { ok: false, error: '現在のスプレッドシートの高速控えがありません' };
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

  cache.remove(COMBO_PROP_FAST_UNDO);
  if (fromProp) {
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eDelP) {}
  }
  // 書式・色・固定・幅のみの部分復元では表構造が変わらないためキャッシュを温存する
  if (!snap.partial) {
    comboCacheInvalidate_(snap.sheetName);
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
    text: text,
    gasMs: Date.now() - t0
  };
}

// ---------------------------------------------------------------- ops 実行・報告整形

function comboFormatOpsShort_(ops) {
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.formatOpsShort === 'function') {
    return ComboPlanner.formatOpsShort(ops);
  }
  return (ops || []).map(function (o) {
    var args = Object.keys(o).filter(function (k) { return k !== 'shelf'; }).map(function (k) {
      return k + '=' + JSON.stringify(o[k]);
    }).join(', ');
    return (o.shelf || '?') + '(' + args + ')';
  }).join(', ');
}

function comboFormatDoText_(res, backupOn) {
  var tgt = res.target || {};
  var head = '対象: ' + (tgt.name || '(名前なし)') + (tgt.sheet ? ' › ' + tgt.sheet : '');
  var lines = [head];
  if (res.ok) {
    var ch = res.changed || [];
    if (ch.length) {
      lines.push('直した所: ' + ch.slice(0, 2).join(' ／ ') + (ch.length > 2 ? '（ほか ' + (ch.length - 2) + ' 件）' : ''));
    } else {
      lines.push('直した所: なし');
    }
    var rest = [];
    if (res.notes && res.notes.length) rest.push('メモ: ' + res.notes.slice(0, 3).join(' ／ '));
    if (res.remaining && res.remaining.length) rest.push('残り: ' + res.remaining.slice(0, 3).join(' ／ '));
    if (rest.length) lines.push(rest.join('　'));
    var tail = [];
    if (res.backup) tail.push('控え #' + res.backup + '（戻す で取り消せます）');
    else if (res.fastUndo) tail.push('高速控えあり（戻す で取り消せます）');
    else if (!backupOn) tail.push('控えなし（backup=OFF）');
    if (tail.length) lines.push(tail.join(' ／ '));
    return lines.join('\n');
  }
  if (res.blocked) {
    lines.push('止めました: ' + (res.error || '確認が必要です'));
    lines.push('何も変えていません。「確認なし」にチェックを入れて再実行してください。');
  } else {
    lines.push('失敗: ' + (res.where ? res.where + ' ' : '') + (res.error || '不明なエラー'));
  }
  return lines.join('\n');
}

function comboKeepsShape_(ops) {
  for (var i = 0; i < ops.length; i++) {
    var op = ops[i];
    if (!op || op.shelf === 'api') return false;
    var c = CATALOG[op.shelf];
    if (!c) return false;
    var touch = c.touch || [];
    if (touch.indexOf('値') >= 0 || touch.indexOf('シート構成') >= 0) return false;
  }
  return true;
}

/**
 * ops 配列を直接実行する（backup=false 時はロックや外部控えを省略した 0.5秒以下の高速経路）。
 * @param {Object} req { ops, ok, backup, sheet, selection, table }
 */
function comboRunOps(req) {
  var t0 = Date.now();
  req = req || {};
  var ops = req.ops;
  if (typeof ops === 'string') {
    try { ops = JSON.parse(ops); } catch (e) {
      return { ok: false, error: 'ops が JSON として読めません', text: 'エラー: ops が JSON として読めません', gasMs: Date.now() - t0 };
    }
  }
  if (ops && !Array.isArray(ops) && ops.shelf) ops = [ops];
  if (!Array.isArray(ops) || !ops.length) {
    return { ok: false, error: 'ops が空です', text: 'エラー: ops が空です', gasMs: Date.now() - t0 };
  }

  var ss;
  try {
    ss = req._ss || comboOpenSs_(req);
  } catch (errOpen) {
    return { ok: false, error: String(errOpen && errOpen.message || errOpen), text: 'エラー: ' + String(errOpen && errOpen.message || errOpen), gasMs: Date.now() - t0 };
  }
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim() || ss.getId();
  var ssUrl = 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit';

  var selInfo;
  try {
    selInfo = comboGetSelectionInfo_(ss, req, true);
  } catch (errSel) {
    return { ok: false, error: String(errSel && errSel.message || errSel), text: 'エラー: ' + String(errSel && errSel.message || errSel), gasMs: Date.now() - t0 };
  }
  var curSheet = selInfo.sheet;
  var backupOn = !!req.backup;

  // フル控えモード（backup=true）：Engine の actDo_ に委譲
  if (backupOn) {
    try { CacheService.getScriptCache().remove(COMBO_PROP_FAST_UNDO); } catch (eDelC) {}
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eDel) {}
    var fullRes = actDo_({
      target: { id: ssId, kind: 'sheet', sheet: curSheet },
      ops: ops,
      ok: !!req.ok,
      backup: true,
      want_table: true
    });
    if (fullRes.ok) {
      comboCacheInvalidate_(curSheet);
      if (fullRes.table !== undefined) {
        comboCachePut_(ssId, (fullRes.target && fullRes.target.sheet) || curSheet, fullRes.table, fullRes.sheets, null, (fullRes.target && fullRes.target.name) || '');
      }
    }
    fullRes.text = comboFormatDoText_(fullRes, true);
    fullRes.gasMs = Date.now() - t0;
    return fullRes;
  }

  // 高速パス（backup=false）：ロック・外部控えブックなしで即時実行
  var sh = sheetOf_(ss, curSheet, '');
  var needTitleA1 = ops.some(function (o) { return o && o.shelf === 'format' && o.title === true; });
  var hasFrontMeta = !!(req.targetName && req.sheets && req.table !== undefined);
  var hasFrontTitle = !needTitleA1 || !!(req.table && req.table.title_a1);
  var cached = (req._cached !== undefined)
    ? req._cached
    : ((hasFrontMeta && hasFrontTitle) ? null : comboCacheGet_(ssId, curSheet));
  var ssName = req.targetName || req._ssName || (cached && cached.ssName) || ss.getName();
  var table = req.table !== undefined ? req.table : (cached && cached.table ? cached.table : null);
  var sheets = req.sheets || (cached && cached.sheets) || null;
  var keepsShape = comboKeepsShape_(ops);

  // format(title/header) の事前解決：table.title_a1 / header_row を使って titleRange_・needTable_ の重い RPC をゼロ化する
  var titleA1 = (table && table.title_a1) || (cached && cached.titleA1) || '';
  var resolvedOps = ops.map(function (op) {
    if (!op || op.shelf !== 'format') return op;
    if (op.title === true && titleA1) {
      // 1 つのセルのタイトルは表の幅いっぱいの帯で（棚が帯に塗る＝控えも帯ごと取る）
      var bandA1 = titleA1;
      if (titleA1.indexOf(':') < 0 && table && table.last_col) {
        var tm = /^([A-Z]+)(\d+)$/.exec(titleA1);
        if (tm && colNum_(table.last_col) > colNum_(tm[1])) bandA1 = (colNum_(table.first_col || tm[1]) < colNum_(tm[1]) ? table.first_col : tm[1]) + tm[2] + ':' + table.last_col + tm[2];
      }
      return Object.assign({}, op, { range: bandA1, title: false, _title: true, _titleA1: titleA1 });
    }
    if (op.header === true && table && table.header_row && table.first_col && table.last_col) {
      var hdrA1 = table.first_col + table.header_row + ':' + table.last_col + table.header_row;
      return Object.assign({}, op, { range: hdrA1, header: false });
    }
    return op;
  });

  _TBL_CACHE = {};
  if (cached && cached.rawTable && (keepsShape || !cached.rawTable.headOnly)) {
    _TBL_CACHE[sh.getSheetId()] = cached.rawTable;
  }

  var fastSaved = false;
  var ctx = {
    wideKey: digest_(ssId + '|' + JSON.stringify(ops), FP_VER),
    kind: 'sheet',
    file: ss,
    ss: ss,
    doc: null,
    sheetName: curSheet,
    curSheet: curSheet,
    ok: !!req.ok,
    changed: [],
    notes: [],
    remaining: [],
    createdSheets: [],
    n: 0,
    isNew: false,
    _file: { id: ssId, name: ssName, url: ssUrl }
  };

  try {
    if (req.fastUndo === true) {
      fastSaved = comboFastUndoSave_(sh, resolvedOps, table, ssId);
    }
    if (!keepsShape && _TBL_CACHE) _TBL_CACHE._once = true;
    for (var i = 0; i < resolvedOps.length; i++) {
      var op = resolvedOps[i];
      var fn = SHELF[op.shelf];
      if (!fn) throw new ArgError('棚「' + op.shelf + '」はありません');
      if (fn.kind && fn.kind !== 'sheet') {
        throw new ArgError('棚「' + op.shelf + '」は文書用です（今の相手はスプレッドシート）');
      }
      ctx.opNo = i + 1;
      ctx.opName = op.shelf;
      fn(ctx, op);
      if (!keepsShape) _TBL_CACHE = null;
    }

    var finalSheet = ctx.curSheet || curSheet;
    if (!keepsShape) {
      SpreadsheetApp.flush();
      comboCacheInvalidate_(curSheet);
      if (finalSheet !== curSheet) comboCacheInvalidate_(finalSheet);
      try {
        var finalSh = ss.getSheetByName(finalSheet);
        if (finalSh) {
          var tbNew = findTable_(finalSh);
          table = tbNew ? tableOut_(tbNew) : null;
          var newTitleA1 = comboComputeTitleA1_(finalSh, tbNew);
          if (table && newTitleA1) table.title_a1 = newTitleA1;
          sheets = ss.getSheets().map(function (s) { return s.getName(); });
          comboCachePut_(ssId, finalSheet, table, sheets, tbNew, ssName, newTitleA1);
        }
      } catch (eTbl) {}
    } else if (!sheets) {
      sheets = ss.getSheets().map(function (s) { return s.getName(); });
    }

    var out = {
      ok: true,
      target: {
        id: ssId,
        name: ssName,
        kind: 'sheet',
        url: ssUrl,
        sheet: finalSheet
      },
      changed: ctx.changed,
      notes: ctx.notes,
      remaining: ctx.remaining,
      backup: 0,
      fastUndo: fastSaved,
      selection: selInfo.selection || req.selection || '',
      table: table,
      sheets: sheets
    };
    out.text = comboFormatDoText_(out, false);
    out.gasMs = Date.now() - t0;
    return out;
  } catch (err) {
    var errOut = {
      ok: false,
      error: String(err && err.message || err),
      where: '棚 #' + (ctx.opNo || 0) + ' ' + (ctx.opName || ''),
      blocked: !!(err && err.isBlocked),
      needs_ok: !!(err && err.isBlocked),
      arg: !!(err && err.isArg),
      target: {
        id: ssId,
        name: ssName,
        kind: 'sheet',
        url: ssUrl,
        sheet: ctx.curSheet || curSheet
      }
    };
    errOut.text = comboFormatDoText_(errOut, false);
    errOut.gasMs = Date.now() - t0;
    return errOut;
  } finally {
    _TBL_CACHE = null;
  }
}

// ---------------------------------------------------------------- 自然文実行・AI直接連携

function comboStripJsonFence_(text) {
  var t = String(text || '').trim();
  var m = t.match(/^```[\w-]*[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/);
  if (m) t = m[1].trim();
  if ((t.charAt(0) === '{' && t.charAt(t.length - 1) === '}') || (t.charAt(0) === '[' && t.charAt(t.length - 1) === ']')) {
    return t;
  }
  var m2 = t.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  return m2 ? m2[1] : t;
}

function comboBuildAiPrompts_(ask, ssName, sheetName, selection, table, sheets) {
  var sys = [
    'あなたは Google スプレッドシートを操作するアシスタントです。',
    '必ず有効な JSON オブジェクト 1 個だけを返してください（説明文や ``` などの装飾は一切付けない）。',
    '・操作を実行するとき: {"action":"ops","ops":[{"shelf":"棚名","引数":値}],"note":"短い日本語要約"}',
    '・返事や確認だけを返すとき: {"action":"reply","message":"日本語の返事"}',
    'ルール: 棚名・引数名は利用可能な棚一覧に載っている正確な名前と型を使うこと。'
  ].join('\n');

  var lines = ['【現在の対象状態】', 'ブック: ' + ssName + ' / シート: ' + sheetName];
  if (sheets && sheets.length) lines.push('全シート: ' + sheets.join('、'));
  if (selection) lines.push('選択中のセル範囲: ' + selection + '（「ここ」「選択範囲」等の対象）');
  if (table) {
    lines.push('表: 見出し ' + table.header_row + '行目・' + table.first_col + '〜' + table.last_col + '列・明細 ' + table.data + '行目' + (table.total_row ? '・合計行 ' + table.total_row : ''));
    lines.push('列: ' + (table.columns || []).map(function (c) { return c.col + '=' + c.name + (c.number ? '(数値)' : ''); }).join('、'));
  }

  lines.push('\n【関連する棚候補】');
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.ask === 'function') {
    lines.push(String(ComboPlanner.ask(ask, 'sheet') || '').slice(0, 1600));
  }
  lines.push('\n【主要シート棚一覧】');
  var aiShelves = (typeof COMBO_CATALOG_DATA !== 'undefined' && COMBO_CATALOG_DATA.shelves)
    ? COMBO_CATALOG_DATA.shelves
    : (Array.isArray(COMBO_MINI_SHELVES) ? COMBO_MINI_SHELVES : null);
  if (aiShelves) {
    var sheetShelves = aiShelves.filter(function (s) { return s.kind === 'sheet' || s.shared || !s.kind; });
    sheetShelves.slice(0, 50).forEach(function (s) {
      lines.push('- ' + s.name + ': ' + (s.title || s.t || '') + ' | ' + (s.args_raw || s.a || 'なし'));
    });
  } else if (typeof CATALOG !== 'undefined') {
    Object.keys(CATALOG).filter(function (k) { return CATALOG[k] && CATALOG[k].kind === 'sheet'; }).slice(0, 50).forEach(function (k) {
      lines.push('- ' + k);
    });
  }
  lines.push('\n【ユーザーの依頼】\n' + ask);
  lines.push('\nJSON 1個だけを返してください。');
  return { system: sys, user: lines.join('\n') };
}

function comboResolveApiKey_(cfg) {
  if (!cfg) return '';
  if (cfg.aiMode === 'api_gemini') return String(cfg.geminiKey || cfg.apiKey || '').trim();
  if (cfg.aiMode === 'api_claude') return String(cfg.claudeKey || cfg.apiKey || '').trim();
  return String(cfg.apiKey || '').trim();
}

function comboCallAiApi_(cfg, ask, ss, curSheet, selection, table, sheets) {
  var apiKey = comboResolveApiKey_(cfg);
  if (!apiKey) throw new Error('APIキーが設定されていません');
  var prompts = comboBuildAiPrompts_(ask, ss.getName(), curSheet, selection, table, sheets);
  var rawText = '';

  if (cfg.aiMode === 'api_gemini') {
    var gModel = String(cfg.aiModel || 'gemini-4-hydrogen-low').trim();
    if (!gModel || gModel === 'sonnet' || gModel === 'haiku') gModel = 'gemini-4-hydrogen-low';
    var gUrl = 'https://generativelanguage.googleapis.com/v1beta/models/' + encodeURIComponent(gModel) + ':generateContent?key=' + encodeURIComponent(apiKey);
    var gResp = UrlFetchApp.fetch(gUrl, {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      payload: JSON.stringify({
        systemInstruction: { parts: [{ text: prompts.system }] },
        contents: [{ role: 'user', parts: [{ text: prompts.user }] }],
        generationConfig: { temperature: 0, responseMimeType: 'application/json' }
      })
    });
    var gCode = gResp.getResponseCode();
    var gBody = gResp.getContentText();
    if (gCode < 200 || gCode >= 300) {
      throw new Error('Gemini API エラー (' + gCode + '): ' + gBody.slice(0, 200));
    }
    var gJson = JSON.parse(gBody);
    rawText = (((((gJson.candidates || [])[0] || {}).content || {}).parts || [])[0] || {}).text || '';
  } else if (cfg.aiMode === 'api_claude') {
    var cModel = String(cfg.aiModel || 'claude-3-5-haiku-latest').trim();
    if (cModel === 'haiku') cModel = 'claude-3-5-haiku-latest';
    else if (cModel === 'sonnet') cModel = 'claude-3-5-sonnet-latest';
    var cResp = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      payload: JSON.stringify({
        model: cModel,
        max_tokens: 1024,
        system: prompts.system,
        messages: [{ role: 'user', content: prompts.user }]
      })
    });
    var cCode = cResp.getResponseCode();
    var cBody = cResp.getContentText();
    if (cCode < 200 || cCode >= 300) {
      throw new Error('Claude API エラー (' + cCode + '): ' + cBody.slice(0, 200));
    }
    var cJson = JSON.parse(cBody);
    rawText = (((cJson.content || [])[0] || {}).text) || '';
  } else {
    throw new Error('未対応の AI モード: ' + cfg.aiMode);
  }

  var parsed = JSON.parse(comboStripJsonFence_(rawText));
  if (Array.isArray(parsed)) return { action: 'ops', ops: parsed, note: '' };
  if (parsed && parsed.shelf && !parsed.ops) return { action: 'ops', ops: [parsed], note: '' };
  return parsed;
}

// ---------------------------------------------------------------- 覚えた言い方（［はい］で決めた頼み→ops。使う人ごと）
var COMBO_PROP_LEARNED = 'COMBO_LEARNED';

function comboGetLearned(req) {
  var map = {};
  try { map = JSON.parse(PropertiesService.getUserProperties().getProperty(COMBO_PROP_LEARNED) || '{}') || {}; } catch (e) { map = {}; }
  return { ok: true, learned: map };
}

function comboLearn(req) {
  req = req || {};
  var ask = String(req.ask || '').trim();
  var ops = req.ops;
  if (!ask || !Array.isArray(ops) || !ops.length) return { ok: false, text: '覚える頼みと ops がありません' };
  var map = comboGetLearned().learned;
  if (req.key) {
    // 呼び手（サイドバー・アドオンのカード）の棚当てが作った鍵をそのまま使う（軽量版はここに棚当てが無い）
    delete map[req.key];
    map[String(req.key)] = ops;
    var ks = Object.keys(map);
    while (ks.length > 300) delete map[ks.shift()];
  } else if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.learn === 'function') {
    ComboPlanner.setLearned(map);
    map = ComboPlanner.learn(ask, ops);
  } else {
    var key = ask.normalize('NFKC').toLowerCase().replace(/\s+/g, '').replace(/[。．.!！?？]+$/g, '');
    map[key] = ops;
  }
  try { PropertiesService.getUserProperties().setProperty(COMBO_PROP_LEARNED, JSON.stringify(map)); } catch (e) {
    return { ok: false, text: '覚えを保存できませんでした: ' + String(e && e.message || e) };
  }
  return { ok: true, text: '覚えました: ' + ask };
}

function comboRenderUnfired_(plan) {
  var lines = ['撃っていません: ' + ((plan.reasons && plan.reasons.length) ? plan.reasons.join('／') : '引数が決まりません')];
  if (plan.suggest && plan.suggest.length) {
    lines.push('近い候補: ' + comboFormatOpsShort_(plan.suggest));
  }
  if (plan.missing && plan.missing.length) {
    lines.push('足りない引数: ' + plan.missing.join('、'));
  }
  if (plan.ops && plan.ops.length) {
    lines.push('組みかけ: ' + comboFormatOpsShort_(plan.ops));
  }
  if (plan.guide && plan.guide.length) {
    plan.guide.slice(0, 2).forEach(function (g) { lines.push('案内: ' + g); });
  }
  return lines.join('\n');
}

/**
 * 自然文または事前解決済み ops を受け取り、棚ヒット即実行または AI 解釈・郵便受け投入を行う。
 * @param {Object} req { ask, ops, ok, backup, aiAuto, sheet, selection, table }
 */
function comboRunAsk(req) {
  var t0 = Date.now();
  req = req || {};
  var askText = String(req.ask || '').trim();

  // フロント側ですでに棚ヒット済み ops が渡された場合は最速で実行する
  if (Array.isArray(req.ops) && req.ops.length) {
    var preRes = comboRunOps({
      ops: req.ops,
      ok: !!req.ok,
      backup: !!req.backup,
      fastUndo: req.fastUndo,
      sheet: req.sheet,
      selection: req.selection,
      table: req.table,
      sheets: req.sheets,
      targetName: req.targetName || req._ssName,
      targetId: req.targetId
    });
    if (preRes.ok) {
      preRes.source = 'shelf';
      preRes.text = '[棚ヒット] ' + comboFormatOpsShort_(req.ops) + '\n' + preRes.text;
    }
    preRes.gasMs = Date.now() - t0;
    return preRes;
  }

  if (!askText) {
    return { ok: false, error: '依頼文が空です', text: '依頼文が空です', gasMs: Date.now() - t0 };
  }

  var ss;
  try {
    ss = comboOpenSs_(req);
  } catch (errOpen) {
    return { ok: false, error: String(errOpen && errOpen.message || errOpen), text: 'エラー: ' + String(errOpen && errOpen.message || errOpen), gasMs: Date.now() - t0 };
  }
  var ssId = ss.getId();

  var selInfo;
  try {
    selInfo = comboGetSelectionInfo_(ss, req);
  } catch (errSel) {
    return { ok: false, error: String(errSel && errSel.message || errSel), text: 'エラー: ' + String(errSel && errSel.message || errSel), gasMs: Date.now() - t0 };
  }
  var curSheet = selInfo.sheet;
  var selection = selInfo.selection;
  var scope = comboParseScope_(selection);

  var cached = (req.targetName && req.sheets && req.table !== undefined && req.table && req.table.title_a1)
    ? null
    : comboCacheGet_(ssId, curSheet);
  var ssName = req.targetName || (cached && cached.ssName) || '';
  var table = req.table !== undefined ? req.table : (cached ? cached.table : undefined);
  var sheets = req.sheets || (cached ? cached.sheets : null);
  if (table === undefined || !sheets) {
    var sh = sheetOf_(ss, curSheet, '');
    var tb = findTable_(sh);
    table = tb ? tableOut_(tb) : null;
    var titleA1 = comboComputeTitleA1_(sh, tb);
    if (table && titleA1) table.title_a1 = titleA1;
    sheets = ss.getSheets().map(function (s) { return s.getName(); });
    ssName = ssName || ss.getName();
    comboCachePut_(ssId, curSheet, table, sheets, tb, ssName, titleA1);
    cached = comboCacheGet_(ssId, curSheet);
  }

  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.plan === 'function') {
    if (typeof ComboPlanner.setLearned === 'function') ComboPlanner.setLearned(comboGetLearned().learned);
    var plan = ComboPlanner.plan(askText, 'sheet', table, sheets, curSheet, scope);
    if (plan && plan.fire && plan.ops && plan.ops.length) {
      var hitRes = comboRunOps({
        ops: plan.ops,
        ok: !!req.ok,
        backup: !!req.backup,
        fastUndo: req.fastUndo,
        sheet: curSheet,
        selection: selection,
        table: table,
        sheets: sheets,
        targetId: ssId,
        assumeActive: !!req.assumeActive,
        _ss: ss,
        _ssName: ssName,
        _cached: cached
      });
      if (hitRes.ok) {
        hitRes.source = 'shelf';
        hitRes.text = '[棚ヒット] ' + comboFormatOpsShort_(plan.ops) + '\n' + hitRes.text;
      }
      hitRes.gasMs = Date.now() - t0;
      return hitRes;
    }

    // 棚に一発ヒットしなかった場合
    if (!req.aiAuto) {
      return {
        ok: false,
        unfired: true,
        plan: plan,
        text: comboRenderUnfired_(plan),
        gasMs: Date.now() - t0
      };
    }
  } else if (!req.aiAuto) {
    return {
      ok: false,
      unfired: true,
      text: '撃っていません: 棚に一発で当てはまらない指示です（「AI自動」をONにするか言い方を具体化してください）',
      gasMs: Date.now() - t0
    };
  }

  var cfg = comboGetRawConfig_();
  var hasApiKey = (cfg.aiMode === 'api_gemini' || cfg.aiMode === 'api_claude') && !!comboResolveApiKey_(cfg);
  if (hasApiKey) {
    try {
      var aiRes = comboCallAiApi_(cfg, askText, ss, curSheet, selection, table, sheets);
      if (aiRes && aiRes.action === 'reply') {
        return {
          ok: true,
          source: 'ai_reply',
          text: '[AI返答]\n' + (aiRes.message || '(返答なし)'),
          gasMs: Date.now() - t0
        };
      }
      if (aiRes && Array.isArray(aiRes.ops) && aiRes.ops.length) {
        var execRes = comboRunOps({
          ops: aiRes.ops,
          ok: !!req.ok,
          backup: !!req.backup,
          fastUndo: req.fastUndo,
          sheet: curSheet,
          selection: selection,
          table: table,
          sheets: sheets,
          targetId: ssId,
          _ss: ss,
          _ssName: ssName,
          _cached: cached
        });
        var noteHead = '[AI解釈]' + (aiRes.note ? ' ' + aiRes.note : '');
        execRes.source = 'ai_api';
        execRes.text = noteHead + '\n' + execRes.text;
        execRes.gasMs = Date.now() - t0;
        return execRes;
      }
      return { ok: false, error: 'AI が実行可能な ops を返しませんでした', text: 'エラー: AI が実行可能な ops を返しませんでした', gasMs: Date.now() - t0 };
    } catch (errAi) {
      return {
        ok: false,
        error: String(errAi && errAi.message || errAi),
        text: 'AI解釈エラー: ' + String(errAi && errAi.message || errAi),
        gasMs: Date.now() - t0
      };
    }
  }

  // 郵便受けモード（PC常駐ウォッチャー連携）
  var reqId = comboPostboxEnqueue_({
    ssId: ss.getId(),
    ssName: ss.getName(),
    sheet: curSheet,
    selection: selection,
    ask: askText,
    ok: !!req.ok,
    backup: !!req.backup,
    aiModel: cfg.aiModel || 'sonnet',
    table: table,
    sheets: sheets
  });
  return {
    ok: true,
    pendingPostbox: true,
    reqId: reqId,
    text: '[郵便受け] 依頼を送信しました（ID: ' + reqId + '）。\nPC側の待機プロセス (gas_ws_combo.py watch) が自動実行します。',
    gasMs: Date.now() - t0
  };
}

// ---------------------------------------------------------------- 棚検索・アンドゥ・設定

/**
 * 棚の札を検索する。
 * @param {Object} req { ask, kind }
 */
function comboFind(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var ask = String(req.ask || '').trim();
    var kind = String(req.kind || 'sheet').trim();
    if (typeof ComboPlanner !== 'undefined') {
      var text = (typeof ComboPlanner.ask === 'function')
        ? ComboPlanner.ask(ask, kind)
        : String(ComboPlanner.find(ask, kind) || '');
      return { ok: true, text: text, gasMs: Date.now() - t0 };
    }
    var list = Array.isArray(COMBO_MINI_SHELVES) ? COMBO_MINI_SHELVES : [];
    var hits = list.filter(function (s) {
      if (!ask) return true;
      var hay = (s.name || '') + ' ' + (s.t || s.title || '') + ' ' + (s.a || s.args_raw || '');
      return hay.indexOf(ask) >= 0;
    }).slice(0, 15).map(function (s) {
      return '- ' + s.name + ': ' + (s.t || s.title || '') + ' (' + (s.a || s.args_raw || 'なし') + ')';
    });
    var fbText = hits.length ? ('棚一覧（軽量検索）:\n' + hits.join('\n')) : ('該当する棚が見つかりませんでした: ' + ask);
    return { ok: true, text: fbText, gasMs: Date.now() - t0 };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err), text: 'エラー: ' + String(err && err.message || err), gasMs: Date.now() - t0 };
  }
}

/**
 * 直前の操作を取り消す（高速スナップショットがあれば即時復元、無ければ Engine の actUndo_ を呼ぶ）。
 * @param {Object} req { ok, to, targetId }
 */
function comboUndo(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var ss = comboOpenSs_(req);
    if (!req.to) {
      var fastRaw = CacheService.getScriptCache().get(COMBO_PROP_FAST_UNDO);
      if (!fastRaw) {
        try { fastRaw = PropertiesService.getScriptProperties().getProperty(COMBO_PROP_FAST_UNDO); } catch (eP) {}
      }
      if (fastRaw) {
        var fastRes = comboFastUndoRestore_(ss, fastRaw);
        if (fastRes.ok || String(fastRes.error || '').indexOf('現在のスプレッドシート') < 0) {
          fastRes.gasMs = Date.now() - t0;
          return fastRes;
        }
      }
    }
    var res = actUndo_({
      target_id: ss.getId(),
      ok: !!req.ok,
      to: req.to ? String(req.to) : ''
    });
    var t = res.target || {};
    if (res.ok) {
      comboCacheInvalidate_(t.sheet || '');
      res.text = [
        '対象: ' + (t.name || ss.getName()),
        '戻した: #' + res.undone + '（' + (res.what || '') + '）を取り消しました',
        '控え #' + res.backup + '（もう一度 戻す で元に戻せます）'
      ].join('\n');
    } else {
      res.text = (res.needs_ok ? '止めました: ' : '戻せませんでした: ') + (res.error || '');
    }
    res.gasMs = Date.now() - t0;
    return res;
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      text: '戻せませんでした: ' + String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

function comboGetRawConfig_() {
  var def = {
    aiMode: 'postbox',
    aiModel: 'sonnet',
    apiKey: '',
    geminiKey: '',
    claudeKey: '',
    backupDefault: false
  };
  try {
    // 設定（API 鍵を含む）は人ごとの置き場に置く。ライブラリ全体の置き場だと、同じライブラリを使う別の人がその鍵で AI を呼べてしまう
    var raw = PropertiesService.getUserProperties().getProperty(COMBO_PROP_CONFIG);
    if (!raw) return def;
    var parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      Object.keys(def).forEach(function (k) {
        if (parsed[k] !== undefined) def[k] = parsed[k];
      });
    }
  } catch (e) {}
  return def;
}

function comboSanitizeConfig_(raw) {
  return {
    aiMode: raw.aiMode || 'postbox',
    aiModel: raw.aiModel || 'sonnet',
    backupDefault: !!raw.backupDefault,
    hasApiKey: !!comboResolveApiKey_(raw),
    hasGeminiKey: !!(raw.geminiKey || (raw.aiMode === 'api_gemini' && raw.apiKey)),
    hasClaudeKey: !!(raw.claudeKey || (raw.aiMode === 'api_claude' && raw.apiKey))
  };
}

/**
 * 設定を UserProperties（人ごと）から読み込む（APIキー自体はクライアントへ露出せず有無フラグを返す）。
 */
function comboGetConfig() {
  return comboSanitizeConfig_(comboGetRawConfig_());
}

/**
 * 設定を UserProperties（人ごと）へ保存する。
 * @param {Object} cfg
 */
function comboSaveConfig(cfg) {
  cfg = cfg || {};
  var cur = comboGetRawConfig_();
  ['aiMode', 'aiModel', 'apiKey', 'geminiKey', 'claudeKey', 'backupDefault'].forEach(function (k) {
    if (cfg[k] !== undefined) cur[k] = cfg[k];
  });
  cur.backupDefault = !!cur.backupDefault;
  PropertiesService.getUserProperties().setProperty(COMBO_PROP_CONFIG, JSON.stringify(cur));
  return { ok: true, config: comboSanitizeConfig_(cur) };
}

// ---------------------------------------------------------------- 郵便受け（PC側 watcher 連携）

function comboPostboxEnqueue_(item) {
  var p = PropertiesService.getScriptProperties();
  var q = [];
  try {
    var raw = p.getProperty(COMBO_PROP_PB_QUEUE);
    if (raw) q = JSON.parse(raw) || [];
  } catch (e) { q = []; }
  var reqId = 'pb_' + Date.now() + '_' + Math.floor(Math.random() * 10000);
  item.reqId = reqId;
  item.ts = Date.now();
  q.push(item);
  if (q.length > 20) q = q.slice(q.length - 20);
  p.setProperty(COMBO_PROP_PB_QUEUE, JSON.stringify(q));
  return reqId;
}

function comboPushPostboxDone_(doneItem) {
  var p = PropertiesService.getScriptProperties();
  var list = [];
  try {
    var raw = p.getProperty(COMBO_PROP_PB_DONE);
    if (raw) list = JSON.parse(raw) || [];
  } catch (e) { list = []; }
  list.push(doneItem);
  if (list.length > 20) list = list.slice(list.length - 20);
  p.setProperty(COMBO_PROP_PB_DONE, JSON.stringify(list));
}

function comboPopPostboxDone_(ssId) {
  var p = PropertiesService.getScriptProperties();
  var raw = p.getProperty(COMBO_PROP_PB_DONE);
  if (!raw) return [];
  var list = [];
  try { list = JSON.parse(raw) || []; } catch (e) { return []; }
  if (!list.length) return [];
  var hit = [], keep = [];
  list.forEach(function (it) {
    if (!ssId || !it.ssId || it.ssId === ssId) hit.push(it);
    else keep.push(it);
  });
  if (hit.length) {
    if (keep.length) p.setProperty(COMBO_PROP_PB_DONE, JSON.stringify(keep));
    else p.deleteProperty(COMBO_PROP_PB_DONE);
  }
  return hit;
}

/**
 * PC側ウォッチャー用：未処理の郵便受けキューを取得する。
 */
function comboPostboxPoll() {
  var p = PropertiesService.getScriptProperties();
  var q = [];
  try {
    var raw = p.getProperty(COMBO_PROP_PB_QUEUE);
    if (raw) q = JSON.parse(raw) || [];
  } catch (e) { q = []; }
  // 古い頼み（5 分より前）は撃たずに捨てる＝受け手が止まっていた間に溜まった頼みを、あとでまとめてシートに撃たない
  var now = Date.now(), fresh = q.filter(function (it) { return it && it.ts && now - it.ts < 5 * 60 * 1000; });
  if (fresh.length !== q.length) {
    if (fresh.length) p.setProperty(COMBO_PROP_PB_QUEUE, JSON.stringify(fresh));
    else p.deleteProperty(COMBO_PROP_PB_QUEUE);
  }
  return { ok: true, queue: fresh, count: fresh.length, dropped: q.length - fresh.length };
}

/**
 * PC側ウォッチャー用：AI が解決した ops / 返答を受け取り、スプレッドシート上で実行して結果を保存する。
 * @param {Object} resPayload { reqId, action, ops, note, message, error }
 */
function comboPostboxDeliver(resPayload) {
  var t0 = Date.now();
  resPayload = resPayload || {};
  var reqId = String(resPayload.reqId || '').trim();
  if (!reqId) return { ok: false, error: 'reqId がありません' };

  var p = PropertiesService.getScriptProperties();
  var q = [];
  try {
    var raw = p.getProperty(COMBO_PROP_PB_QUEUE);
    if (raw) q = JSON.parse(raw) || [];
  } catch (e) { q = []; }

  var orig = null;
  var rest = [];
  q.forEach(function (it) {
    if (it && it.reqId === reqId && !orig) orig = it;
    else rest.push(it);
  });
  p.setProperty(COMBO_PROP_PB_QUEUE, JSON.stringify(rest));

  var action = resPayload.action || (Array.isArray(resPayload.ops) ? 'ops' : 'reply');
  if (action === 'ops' && Array.isArray(resPayload.ops) && resPayload.ops.length) {
    var execRes = comboRunOps({
      ops: resPayload.ops,
      ok: orig ? !!orig.ok : !!resPayload.ok,
      backup: orig ? !!orig.backup : !!resPayload.backup,
      sheet: orig ? orig.sheet : (resPayload.sheet || ''),
      selection: orig ? orig.selection : (resPayload.selection || ''),
      table: orig ? orig.table : undefined,
      targetId: orig ? orig.ssId : (resPayload.ssId || '')
    });
    var noteHead = '[AI解釈(郵便受け)]' + (resPayload.note ? ' ' + resPayload.note : '');
    execRes.text = noteHead + '\n' + execRes.text;
    execRes.reqId = reqId;
    comboPushPostboxDone_({
      reqId: reqId,
      ssId: orig ? orig.ssId : '',
      ask: orig ? orig.ask : '',
      ok: execRes.ok,
      ops: resPayload.ops,
      note: resPayload.note || '',
      text: execRes.text,
      target: execRes.target,
      table: execRes.table,
      sheets: execRes.sheets,
      gasMs: execRes.gasMs || (Date.now() - t0)
    });
    return execRes;
  }

  var msgText = action === 'error'
    ? ('[AIエラー(郵便受け)] ' + (resPayload.error || '失敗'))
    : ('[AI返答(郵便受け)]\n' + (resPayload.message || '(返答なし)'));
  comboPushPostboxDone_({
    reqId: reqId,
    ssId: orig ? orig.ssId : '',
    ask: orig ? orig.ask : '',
    ok: action !== 'error',
    text: msgText,
    gasMs: Date.now() - t0
  });
  return { ok: true, delivered: true, reqId: reqId, text: msgText, gasMs: Date.now() - t0 };
}

/**
 * 軽量ピン（V8 Isolate 起動時間＋通信往復時間の計測用）。
 */
function comboPing() {
  return { ok: true, ts: Date.now() };
}

// ---------------------------------------------------------------- Engine WebApp (doPost) 用 EXTRA_ACTIONS 登録

if (typeof EXTRA_ACTIONS !== 'undefined') {
  EXTRA_ACTIONS.combo_ping = comboPing;
  EXTRA_ACTIONS.combo_init = comboInit;
  EXTRA_ACTIONS.combo_look = comboLook;
  EXTRA_ACTIONS.combo_find = comboFind;
  EXTRA_ACTIONS.combo_ask = comboRunAsk;
  EXTRA_ACTIONS.combo_ops = comboRunOps;
  EXTRA_ACTIONS.combo_undo = comboUndo;
  EXTRA_ACTIONS.combo_poll = comboPollSelection;
  EXTRA_ACTIONS.combo_set_target = function (req) {
    return comboSetTestTarget((req && (req.targetId || req.ssId)) || '');
  };
}
