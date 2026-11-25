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
  var effOk = !!req.ok || ops.some(function (o) { return !!(o && o.ok === true); });

  // フル控えモード（backup=true）：Engine の actDo_ に委譲
  if (backupOn) {
    try { CacheService.getScriptCache().remove(COMBO_PROP_FAST_UNDO); } catch (eDelC) {}
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eDel) {}
    var fullRes = actDo_({
      target: { id: ssId, kind: 'sheet', sheet: curSheet },
      ops: ops,
      ok: effOk,
      backup: true,
      want_table: true
    });
    if (fullRes.ok) {
      comboCacheInvalidate_(ssId, curSheet);
      if (fullRes.table !== undefined) {
        comboCachePut_(ssId, (fullRes.target && fullRes.target.sheet) || curSheet, fullRes.table, fullRes.sheets, null, (fullRes.target && fullRes.target.name) || '');
      }
    }
    fullRes.oauthToken = comboGetOAuthToken_();
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
      if (op.merge === undefined && titleA1.indexOf(':') < 0 && table && table.last_col) {
        var tm = /^([A-Z]+)(\d+)$/.exec(titleA1);
        if (tm && colNum_(table.last_col) > colNum_(tm[1])) {
          var c0 = Math.min(colNum_(table.first_col || tm[1]), colNum_(tm[1]));
          var c1 = colNum_(table.last_col);
          var rIdx = parseInt(tm[2], 10) - 1;
          var rawRow = (cached && cached.rawTable && cached.rawTable.vals && cached.rawTable.vals[rIdx]) ? cached.rawTable.vals[rIdx].slice(c0 - 1, c1) : null;
          if (!rawRow || rawRow.filter(function (v) { return !isBlank_(v); }).length <= 1) {
            bandA1 = (colNum_(table.first_col || tm[1]) < colNum_(tm[1]) ? table.first_col : tm[1]) + tm[2] + ':' + table.last_col + tm[2];
          }
        }
      }
      var nextOp = Object.assign({}, op, { range: bandA1, title: false });
      if (bandA1 !== titleA1 && (op.align === 'center' || op.align === 'right')) nextOp.align = 'left';
      return nextOp;
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
    ok: effOk,
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
    var sheetInfos = null;
    if (!keepsShape) {
      SpreadsheetApp.flush();
      comboCacheInvalidate_(ssId, curSheet);
      if (finalSheet !== curSheet) comboCacheInvalidate_(ssId, finalSheet);
      try {
        var finalSh = ss.getSheetByName(finalSheet);
        if (finalSh) {
          var tbNew = findTable_(finalSh);
          table = tbNew ? tableOut_(tbNew) : null;
          var newTitleA1 = comboComputeTitleA1_(finalSh, tbNew);
          if (table && newTitleA1) table.title_a1 = newTitleA1;
          var allSh = ss.getSheets();
          sheets = allSh.map(function (s) { return s.getName(); });
          sheetInfos = allSh.map(function (s) {
            return { name: s.getName(), sheetId: s.getSheetId(), rows: s.getLastRow(), cols: s.getLastColumn() };
          });
          comboCachePut_(ssId, finalSheet, table, sheets, tbNew, ssName, newTitleA1);
        }
      } catch (eTbl) {}
    } else if (!sheets) {
      var allShKeep = ss.getSheets();
      sheets = allShKeep.map(function (s) { return s.getName(); });
      sheetInfos = allShKeep.map(function (s) {
        return { name: s.getName(), sheetId: s.getSheetId(), rows: s.getLastRow(), cols: s.getLastColumn() };
      });
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
      sheets: sheets,
      oauthToken: comboGetOAuthToken_()
    };
    if (sheetInfos) out.sheetInfos = sheetInfos;
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

function comboBuildCompactShelfSummary_(ask, fullLimit) {
  var lines = [];
  var askPlan = '';
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.ask === 'function') {
    askPlan = String(ComboPlanner.ask(ask || '', 'sheet') || '').slice(0, 1600);
    if (askPlan) lines.push(askPlan);
  }
  var aiShelves = (typeof COMBO_CATALOG_DATA !== 'undefined' && COMBO_CATALOG_DATA.shelves)
    ? COMBO_CATALOG_DATA.shelves
    : (Array.isArray(COMBO_MINI_SHELVES) ? COMBO_MINI_SHELVES : null);
  if (aiShelves) {
    var sheetShelves = aiShelves.filter(function (s) {
      return s && s.searchable !== false && (s.kind === 'sheet' || s.shared || !s.kind);
    });
    var prioSet = {
      seiri: 1, tidy: 1, format: 1, write: 1, replace: 1, total: 1, 'formula.col': 1, sort: 1,
      'filter.on': 1, 'filter.where': 1, 'filter.off': 1, width: 1, freeze: 1, unfreeze: 1,
      dedupe: 1, 'banding.add': 1, 'banding.remove': 1, 'chart.new': 1, 'rows.delete': 1, 'rows.insert': 1,
      'cols.delete': 1, 'sheet.add': 1, 'sheet.rename': 1, 'sheet.copy': 1, 'table.new': 1, 'validation.list': 1
    };
    var picked = [];
    var pickedMap = {};
    sheetShelves.forEach(function (s) {
      if ((askPlan && askPlan.indexOf(s.name) >= 0) || prioSet[s.name]) {
        if (!pickedMap[s.name] && picked.length < (fullLimit || 30)) {
          pickedMap[s.name] = true;
          picked.push(s);
        }
      }
    });
    if (picked.length) {
      lines.push('\n【利用可能な棚一覧（主要・関連：棚名 | 説明 | 引数）】');
      picked.forEach(function (s) {
        lines.push('- ' + s.name + ': ' + (s.title || s.t || '') + ' | ' + (s.args_raw || s.a || 'なし'));
      });
    }
    var rest = sheetShelves.filter(function (s) { return !pickedMap[s.name]; });
    if (rest.length) {
      lines.push('\n【その他すべての利用可能な棚（カテゴリ別・全件）】');
      var byCat = {};
      var catOrder = [];
      rest.forEach(function (s) {
        var c = s.category || s.c || 'その他';
        if (!byCat[c]) { byCat[c] = []; catOrder.push(c); }
        byCat[c].push(s.name + '(' + (s.title || s.t || '') + ')');
      });
      catOrder.forEach(function (c) {
        lines.push('- ' + c + ': ' + byCat[c].join(' / '));
      });
    }
  } else if (typeof CATALOG !== 'undefined') {
    lines.push('\n【利用可能な棚一覧】');
    Object.keys(CATALOG).filter(function (k) { return CATALOG[k] && CATALOG[k].kind === 'sheet'; }).forEach(function (k) {
      lines.push('- ' + k);
    });
  }
  return lines.join('\n');
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

  lines.push('\n【関連する棚候補と全棚カタログ】');
  lines.push(comboBuildCompactShelfSummary_(ask, 30));
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

function comboResolveLatestApiModel_(provider, aliasOrModel, apiKey) {
  var raw = String(aliasOrModel || '').trim();
  var lower = raw.toLowerCase();
  if (provider === 'api_claude') {
    if (/^claude-(?:sonnet|haiku|opus|fable)-\d/.test(lower)) return raw;
    var cFam = lower.indexOf('haiku') >= 0 ? 'haiku' : (lower.indexOf('opus') >= 0 ? 'opus' : 'sonnet');
    var cFallback = 'claude-' + cFam + '-5-5';
    var cCacheKey = 'combo_latest_model:api_claude:' + cFam;
    try {
      var uc = CacheService.getUserCache();
      var hit = uc ? uc.get(cCacheKey) : null;
      if (hit) return hit;
    } catch (eC0) {}
    if (apiKey) {
      try {
        var r = UrlFetchApp.fetch('https://api.anthropic.com/v1/models?limit=50', {
          method: 'get',
          muteHttpExceptions: true,
          headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' }
        });
        if (r.getResponseCode() >= 200 && r.getResponseCode() < 300) {
          var j = JSON.parse(r.getContentText() || '{}');
          var arr = Array.isArray(j.data) ? j.data : [];
          var picked = '';
          for (var i = 0; i < arr.length; i++) {
            var id = String((arr[i] && arr[i].id) || '').trim();
            if (id.indexOf('claude-' + cFam + '-') === 0) { picked = id; break; }
          }
          if (picked) {
            try { var uc2 = CacheService.getUserCache(); if (uc2) uc2.put(cCacheKey, picked, 21600); } catch (eC1) {}
            return picked;
          }
        }
      } catch (eC2) {}
    }
    return cFallback;
  }
  if (/^gemini-\d/.test(lower) && lower.indexOf('gemini-4-hydrogen-') !== 0) return raw;
  var gFam = lower.indexOf('neon') >= 0 ? 'neon' : 'hydrogen';
  var gFallback = gFam === 'neon' ? 'gemini-4-neon' : 'gemini-4-hydrogen';
  var gCacheKey = 'combo_latest_model:api_gemini:' + gFam;
  try {
    var ug = CacheService.getUserCache();
    var gHit = ug ? ug.get(gCacheKey) : null;
    if (gHit) return gHit;
  } catch (eG0) {}
  if (apiKey) {
    try {
      var gr = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models?key=' + encodeURIComponent(apiKey) + '&pageSize=100', {
        method: 'get',
        muteHttpExceptions: true
      });
      if (gr.getResponseCode() >= 200 && gr.getResponseCode() < 300) {
        var gj = JSON.parse(gr.getContentText() || '{}');
        var models = Array.isArray(gj.models) ? gj.models : [];
        var best = '';
        var bestVer = -1;
        for (var k = 0; k < models.length; k++) {
          var m = models[k] || {};
          var methods = Array.isArray(m.supportedGenerationMethods) ? m.supportedGenerationMethods : [];
          if (methods.length && methods.indexOf('generateContent') < 0) continue;
          var nm = String(m.name || '').replace(/^models\//, '').trim();
          var nl = nm.toLowerCase();
          var vm = (gFam === 'neon')
            ? nl.match(/^gemini-(\d+(?:\.\d+)?)-neon$/)
            : nl.match(/^gemini-(\d+(?:\.\d+)?)-hydrogen$/);
          if (vm) {
            var verNum = parseFloat(vm[1]);
            if (verNum > bestVer) { bestVer = verNum; best = nm; }
          }
        }
        if (best) {
          try { var ug2 = CacheService.getUserCache(); if (ug2) ug2.put(gCacheKey, best, 21600); } catch (eG1) {}
          return best;
        }
      }
    } catch (eG2) {}
  }
  return gFallback;
}

function comboCallAiApi_(cfg, ask, ss, curSheet, selection, table, sheets) {
  var apiKey = comboResolveApiKey_(cfg);
  if (!apiKey) throw new Error('APIキーが設定されていません');
  var prompts = comboBuildAiPrompts_(ask, ss.getName(), curSheet, selection, table, sheets);
  var rawText = '';

  if (cfg.aiMode === 'api_gemini') {
    var gModel = comboResolveLatestApiModel_('api_gemini', cfg.aiModel, apiKey);
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
    var cModel = comboResolveLatestApiModel_('api_claude', cfg.aiModel, apiKey);
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
  if (req && req.reset) return { ok: true, learned: {} };
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

function comboMatchMyMacro_(askText, myList) {
  if (!askText || !Array.isArray(myList) || !myList.length) return null;
  var norm = function (s) {
    var t = String(s || '');
    try { if (typeof t.normalize === 'function') t = t.normalize('NFKC'); } catch (eN) {}
    return t.toLowerCase().replace(/[\s\u3000、。,.!！?？「」『』()（）]/g, '');
  };
  var stripTail = function (s) {
    return s.replace(/(してください|して下さい|を実行する|を実行|を動かして|を動かして下さい|をお願い|お願いします|をやって|を呼んで|して)$/, '');
  };
  var q = norm(askText);
  var qBase = stripTail(q);
  if (!q) return null;

  var exactHits = [];
  var subBestScore = 0;
  var subHits = [];
  for (var i = 0; i < myList.length; i++) {
    var m = myList[i];
    if (!m || !m.name) continue;
    var cands = [m.name].concat(Array.isArray(m.words) ? m.words : []);
    var isExact = false;
    var bestLen = 0;
    for (var j = 0; j < cands.length; j++) {
      var w = norm(cands[j]);
      var wBase = stripTail(w);
      if (!w) continue;
      if (w === q || (wBase && wBase === qBase)) {
        isExact = true;
        break;
      }
      if (w.length >= 2 && q.indexOf(w) >= 0 && w.length > bestLen) bestLen = w.length;
      if (wBase.length >= 2 && qBase.indexOf(wBase) >= 0 && wBase.length > bestLen) bestLen = wBase.length;
    }
    if (isExact) {
      exactHits.push(m);
    } else if (bestLen > 0) {
      if (bestLen > subBestScore) {
        subBestScore = bestLen;
        subHits = [m];
      } else if (bestLen === subBestScore) {
        subHits.push(m);
      }
    }
  }
  if (exactHits.length === 1) return exactHits[0];
  if (exactHits.length > 1) return null;
  if (subHits.length === 1) return subHits[0];
  return null;
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

    // 既製棚に一発ヒットしなかった場合、マイマクロの // 棚: 言い方 と関数名を照合する
    if (typeof quickMyFind_ === 'function' && typeof quickMyListCached_ === 'function' && typeof comboQuickRun === 'function') {
      try {
        var allPropsMy = null;
        try { allPropsMy = PropertiesService.getUserProperties().getProperties() || {}; } catch (ePM) {}
        var metaMy = quickMyFind_(true, allPropsMy);
        if (metaMy && metaMy.id) {
          var myList = quickMyListCached_(metaMy.id, metaMy.stamp || undefined);
          var myHit = comboMatchMyMacro_(askText, myList);
          if (myHit) {
            var myRes = comboQuickRun({
              name: myHit.name,
              myId: metaMy.id,
              myStamp: metaMy.stamp || '',
              targetId: ssId,
              sheet: curSheet,
              selection: selection,
              backup: !!req.backup
            });
            if (myRes) {
              myRes.source = 'mymacro';
              myRes.matchedMacro = myHit.name;
              if (myRes.ok) myRes.text = '[マイマクロ] ' + myHit.name + '\n' + (myRes.text || '');
              myRes.gasMs = Date.now() - t0;
              return myRes;
            }
          }
        }
      } catch (eMyMatch) {}
    }

    // 棚にもマイマクロにも一発ヒットしなかった場合
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
      var cUndo = comboCache_();
      var fastRaw = cUndo ? cUndo.get(COMBO_PROP_FAST_UNDO) : null;
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
      comboCacheInvalidate_(ss.getId(), t.sheet || '');
      res.text = [
        '対象: ' + (t.name || ss.getName()),
        '戻した: #' + res.undone + '（' + (res.what || '') + '）を取り消しました',
        '控え #' + res.backup + '（もう一度 戻す で元に戻せます）'
      ].join('\n');
    } else {
      res.text = (res.needs_ok ? '止めました: ' : '戻せませんでした: ') + (res.error || '');
    }
    res.oauthToken = comboGetOAuthToken_();
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

function comboGetRawConfig_(optAllProps) {
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
    var raw = optAllProps ? optAllProps[COMBO_PROP_CONFIG] : PropertiesService.getUserProperties().getProperty(COMBO_PROP_CONFIG);
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

  var action = resPayload.action || (Array.isArray(resPayload.ops) ? 'ops' : (resPayload.code ? 'mymacro' : 'reply'));
  var isMyMacro = (orig && orig.kind === 'mymacro') || resPayload.kind === 'mymacro' || action === 'mymacro';
  if (isMyMacro) {
    var mMode = (orig && orig.mode) || resPayload.mode || 'add';
    var mTarget = (orig && orig.targetName) || resPayload.targetName || '';
    var mPrev = (orig && orig.existingCode) || resPayload.existingCode || '';
    var mMyId = (orig && orig.myId) || resPayload.myId || '';
    var mSsId = (orig && orig.ssId) || resPayload.ssId || '';
    var mAsk = (orig && orig.ask) || resPayload.ask || '';
    var mPreview = !!((orig && orig.previewOnly) || resPayload.previewOnly);
    var mExistingNames = (orig && orig.existingNames) || resPayload.existingNames || [];
    if (action === 'error') {
      var errTxt = '[AIエラー(郵便受け)] ' + (resPayload.error || 'マイマクロ生成に失敗しました');
      comboPushPostboxDone_({
        reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
        name: mTarget, ok: false, error: resPayload.error || '失敗', text: errTxt, gasMs: Date.now() - t0
      });
      return { ok: true, delivered: true, reqId: reqId, kind: 'mymacro', text: errTxt, gasMs: Date.now() - t0 };
    }
    var mExtracted = resPayload.code
      ? { action: 'mymacro', code: String(resPayload.code), note: String(resPayload.note || '') }
      : comboExtractMyMacroCode_(resPayload.message || '');
    if (mExtracted.action === 'reply' || !mExtracted.code) {
      if (mPreview && mExtracted.action === 'reply') {
        var rawRep = String(mExtracted.message || resPayload.message || '').trim() || 'ご希望の編集内容を教えてください。';
        comboPushPostboxDone_({
          reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
          action: 'reply', ok: true, saved: false, previewOnly: true,
          name: mTarget, targetName: mTarget, message: rawRep, text: rawRep, gasMs: Date.now() - t0
        });
        return {
          ok: true, delivered: true, action: 'reply', saved: false, previewOnly: true,
          reqId: reqId, kind: 'mymacro', message: rawRep, text: rawRep, gasMs: Date.now() - t0
        };
      }
      var rMsg = '[AI返答(郵便受け)]\n' + (mExtracted.message || resPayload.message || 'コードを生成できませんでした');
      comboPushPostboxDone_({
        reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
        name: mTarget, ok: false, error: rMsg, text: rMsg, gasMs: Date.now() - t0
      });
      return { ok: true, delivered: true, reqId: reqId, kind: 'mymacro', text: rMsg, gasMs: Date.now() - t0 };
    }
    if (mPreview) {
      var valRes = comboValidateAiMyMacroCode_(mMode, mExtracted.code, mExistingNames);
      if (!valRes.ok && valRes.retryable) {
        return { ok: false, retryable: true, error: valRes.error, gasMs: Date.now() - t0 };
      }
      if (!valRes.ok) {
        var failPvTxt = '[AIマイマクロ検証失敗] ' + (valRes.error || 'コードを検証できませんでした');
        comboPushPostboxDone_({
          reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
          name: mTarget, ok: false, error: valRes.error || failPvTxt, text: failPvTxt, gasMs: Date.now() - t0
        });
        return { ok: false, reqId: reqId, kind: 'mymacro', error: valRes.error, text: failPvTxt, gasMs: Date.now() - t0 };
      }
      var pvName = valRes.name || mTarget || 'マイマクロ';
      var pvText = '✨ コード案ができました（' + pvName + '）。「決定して保存」で登録されます' + (mExtracted.note ? '（' + mExtracted.note + '）' : '');
      comboPushPostboxDone_({
        reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
        action: 'mymacro', ok: true, saved: false, previewOnly: true,
        name: pvName, newName: pvName, targetName: mTarget,
        code: valRes.code, prevCode: mPrev, myId: mMyId,
        note: mExtracted.note || '', text: pvText, gasMs: Date.now() - t0
      });
      return {
        ok: true, delivered: true, action: 'mymacro', saved: false, previewOnly: true,
        reqId: reqId, kind: 'mymacro', name: pvName, code: valRes.code, text: pvText, gasMs: Date.now() - t0
      };
    }
    var saveRes = comboSaveAiMyMacroResult_(mMode, mTarget, mExtracted.code, mMyId);
    if (!saveRes.ok && saveRes.retryable) {
      return { ok: false, retryable: true, error: saveRes.error, gasMs: Date.now() - t0 };
    }
    if (!saveRes.ok && saveRes.needsClientSave) {
      var pendTxt = 'AI でコードを作成しました（拡張側で保存を完了します）';
      comboPushPostboxDone_({
        reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
        ok: true, saved: false, code: saveRes.code, targetName: mTarget,
        prevCode: mPrev, myId: mMyId, note: mExtracted.note || '', text: pendTxt, gasMs: Date.now() - t0
      });
      return { ok: true, delivered: true, saved: false, needsClientSave: true, reqId: reqId, kind: 'mymacro', text: pendTxt, gasMs: Date.now() - t0 };
    }
    if (!saveRes.ok) {
      var failTxt = '[AIマイマクロ保存失敗] ' + (saveRes.error || '保存できませんでした');
      comboPushPostboxDone_({
        reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
        name: mTarget, ok: false, error: saveRes.error || failTxt, text: failTxt, gasMs: Date.now() - t0
      });
      return { ok: false, reqId: reqId, kind: 'mymacro', error: saveRes.error, text: failTxt, gasMs: Date.now() - t0 };
    }
    var savedNm = saveRes.newName || saveRes.name || (saveRes.names && saveRes.names[0]) || mTarget || 'マイマクロ';
    var okText = '✨ AI でマイマクロ「' + savedNm + '」を' + (mMode === 'edit' ? '修正' : '作成') + 'して自動保存しました' + (mExtracted.note ? '（' + mExtracted.note + '）' : '');
    comboPushPostboxDone_({
      reqId: reqId, ssId: mSsId, ask: mAsk, kind: 'mymacro', mode: mMode,
      ok: true, saved: true, name: savedNm, newName: savedNm,
      prevCode: mPrev, myId: saveRes.myId || mMyId, myUrl: saveRes.myUrl || '', myStamp: saveRes.myStamp || '',
      note: mExtracted.note || '', text: okText, gasMs: Date.now() - t0
    });
    return {
      ok: true, delivered: true, saved: true, reqId: reqId, kind: 'mymacro',
      name: savedNm, myId: saveRes.myId || mMyId, myStamp: saveRes.myStamp || '', text: okText, gasMs: Date.now() - t0
    };
  }

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

// ---------------------------------------------------------------- マイマクロ・一覧連携（GASクイック互換）

var QUICK_MY_TITLE = 'GASクイック マイマクロ';
var QUICK_SCRIPT_JSON = 'application/vnd.google-apps.script+json';
var QUICK_MY_ID_KEY = 'QUICK_MY_ID';
var QUICK_PINS_KEY = 'QUICK_PINS';
var QUICK_BK_NAME = '_GASクイックの控え';
var QUICK_JS_RESERVED_ = {
  'break': 1, 'case': 1, 'catch': 1, 'class': 1, 'const': 1, 'continue': 1, 'debugger': 1,
  'default': 1, 'delete': 1, 'do': 1, 'else': 1, 'enum': 1, 'export': 1, 'extends': 1,
  'false': 1, 'finally': 1, 'for': 1, 'function': 1, 'if': 1, 'import': 1, 'in': 1,
  'instanceof': 1, 'let': 1, 'new': 1, 'null': 1, 'return': 1, 'static': 1, 'super': 1,
  'switch': 1, 'this': 1, 'throw': 1, 'true': 1, 'try': 1, 'typeof': 1, 'var': 1,
  'void': 1, 'while': 1, 'with': 1, 'yield': 1, 'await': 1, 'eval': 1, 'arguments': 1
};

function quickOrderKey_(kind, optSsId) {
  if (kind === 'sheet') {
    var id = optSsId || '';
    if (!id) { try { id = comboOpenSs_({}).getId(); } catch (e) {} }
    return 'QUICK_ORDER_sheet_' + id;
  }
  return 'QUICK_ORDER_' + (kind === 'my' ? 'my' : 'shelf');
}

function quickGetOrders_(optAllProps, optSsId) {
  var props = optAllProps;
  if (!props) {
    try { props = PropertiesService.getUserProperties().getProperties() || {}; } catch (e) { props = {}; }
  }
  var out = {};
  ['sheet', 'my', 'shelf'].forEach(function (k) {
    try { out[k] = JSON.parse(props[quickOrderKey_(k, optSsId)] || '[]'); } catch (e) { out[k] = []; }
  });
  return out;
}

function quickGetPins_(optAllProps) {
  try {
    var raw = optAllProps ? optAllProps[QUICK_PINS_KEY] : PropertiesService.getUserProperties().getProperty(QUICK_PINS_KEY);
    var parsed = raw ? JSON.parse(raw) : {};
    return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : {};
  } catch (e) {
    return {};
  }
}

/** 一覧のピン留め（★）状態をユーザーごとに保存する。 */
function comboQuickSavePins(req) {
  req = req || {};
  var raw = (req.pins && typeof req.pins === 'object' && !Array.isArray(req.pins)) ? req.pins : {};
  var clean = {}, keys = Object.keys(raw).slice(0, 400);
  for (var i = 0; i < keys.length; i++) {
    if (raw[keys[i]]) clean[String(keys[i])] = 1;
  }
  try {
    PropertiesService.getUserProperties().setProperty(QUICK_PINS_KEY, JSON.stringify(clean));
    return { ok: true, pins: clean };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

/** 区切りの中の並びを覚える（names＝上からの名前の並び）。 */
function comboQuickSaveOrder(req) {
  req = req || {};
  var kind = req.kind === 'sheet' ? 'sheet' : (req.kind === 'my' ? 'my' : 'shelf');
  var names = (req.names || []).map(String).slice(0, 400);
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim();
  try {
    PropertiesService.getUserProperties().setProperty(quickOrderKey_(kind, ssId), JSON.stringify(names));
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

// 手順文字列を安全に分割する（エスケープされた \/・\／ や URL・日付 2026/11/21 を保護）
function quickSplitSteps_(raw) {
  var s = String(raw || '').trim();
  if (!s) return [];
  var tokens = [], idx = 0;
  var protect = function (re) {
    s = s.replace(re, function (m) {
      var key = '\uE002' + (idx++) + '\uE003';
      tokens.push(m);
      return key;
    });
  };
  protect(/\\\//g);
  protect(/\\／/g);
  protect(/https?:\/\/[^\s]+/g);
  protect(/\d+(?:\/\d+)+/g);
  var parts = (/／|\s+\/\s+/.test(s)) ? s.split(/\s*／\s*|\s+\/\s+/) : s.split(/\s*\/\s*/);
  return parts.map(function (st) {
    var restored = st.replace(/\uE002(\d+)\uE003/g, function (_, n) {
      var t = tokens[parseInt(n, 10)] || '';
      if (t === '\\/') return '/';
      if (t === '\\／') return '／';
      return t;
    });
    return restored.trim();
  }).filter(Boolean);
}

function quickMyFind_(wantMeta, optAllProps, optForce) {
  var cache = comboCache_();
  if (!optForce && cache) {
    try {
      var mRaw = cache.get('QUICK_MY_META');
      if (mRaw) {
        var m = JSON.parse(mRaw);
        if (m && m.id && m.checkedAt && (Date.now() - m.checkedAt < 60000)) {
          return wantMeta ? { id: m.id, stamp: m.stamp || '' } : m.id;
        }
      }
    } catch (eC) {}
  }
  var props = null;
  try { props = PropertiesService.getUserProperties(); } catch (ePr) {}
  var known = optAllProps ? (optAllProps[QUICK_MY_ID_KEY] || '') : (props ? props.getProperty(QUICK_MY_ID_KEY) : '');
  if (known && typeof DriveApp !== 'undefined') {
    try {
      var f = DriveApp.getFileById(known);
      if (!f.isTrashed() && f.getName() === QUICK_MY_TITLE) {
        var st = String(f.getLastUpdated().getTime());
        if (cache) { try { cache.put('QUICK_MY_META', JSON.stringify({ id: known, stamp: st, checkedAt: Date.now() }), 300); } catch (ePut1) {} }
        return wantMeta ? { id: known, stamp: st } : known;
      }
    } catch (e) {}
    if (props) { try { props.deleteProperty(QUICK_MY_ID_KEY); } catch (eDel) {} }
  }
  if (typeof DriveApp !== 'undefined') {
    var q = DriveApp.searchFiles("title = '" + QUICK_MY_TITLE + "' and mimeType = 'application/vnd.google-apps.script' and trashed = false");
    if (q.hasNext()) {
      var nf = q.next();
      var id = nf.getId();
      var st2 = String(nf.getLastUpdated().getTime());
      if (props) { try { props.setProperty(QUICK_MY_ID_KEY, id); } catch (eSet) {} }
      if (cache) { try { cache.put('QUICK_MY_META', JSON.stringify({ id: id, stamp: st2, checkedAt: Date.now() }), 300); } catch (ePut2) {} }
      return wantMeta ? { id: id, stamp: st2 } : id;
    }
  }
  if (cache) { try { cache.remove('QUICK_MY_META'); } catch (eRm) {} }
  return wantMeta ? { id: '', stamp: '' } : '';
}

function quickMyStamp_(id) {
  try { return typeof DriveApp !== 'undefined' ? String(DriveApp.getFileById(id).getLastUpdated().getTime()) : ''; } catch (e) { return ''; }
}

function quickMyInvalidate_(id) {
  if (!id) return;
  try {
    var cache = comboCache_();
    if (!cache) return;
    cache.remove('QUICK_MY_LIST_' + id);
    cache.remove('QUICK_MY_SRC_' + id);
    cache.remove('QUICK_MY_META');
  } catch (e) {}
}

function quickMyCachePut_(id, src, optStamp) {
  if (!id) return '';
  var stamp = optStamp || quickMyStamp_(id) || String(Date.now());
  try {
    var cache = comboCache_();
    if (!cache) return stamp;
    var nowTs = Date.now();
    var srcStr = String(src || '');
    var payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, src: srcStr });
    if (payload.length > 50000 && typeof Utilities !== 'undefined') {
      var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(srcStr, 'text/plain')).getBytes());
      payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, __gz: gz });
    }
    if (payload.length < 95000) {
      cache.put('QUICK_MY_SRC_' + id, payload, 21600);
    } else {
      cache.remove('QUICK_MY_SRC_' + id);
    }
    var list = quickParseFns_(srcStr);
    cache.put('QUICK_MY_LIST_' + id, JSON.stringify({ v: 4, stamp: stamp, list: list }), 21600);
    cache.put('QUICK_MY_META', JSON.stringify({ id: id, stamp: stamp, checkedAt: nowTs }), 300);
  } catch (e) {
    quickMyInvalidate_(id);
  }
  return stamp;
}

function quickMySourceCached_(id, optStamp, fastMode) {
  var cache = comboCache_(), key = 'QUICK_MY_SRC_' + id;
  var raw = null;
  if (cache) { try { raw = cache.get(key); } catch (eGet) { raw = null; } }
  var readCached = function (c) {
    if (!c) return null;
    if (c.__gz && typeof Utilities !== 'undefined') {
      return Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(c.__gz), 'application/x-gzip')).getDataAsString('utf-8');
    }
    return typeof c.src === 'string' ? c.src : null;
  };
  if (fastMode && raw) {
    try {
      var cf = JSON.parse(raw);
      if (cf && cf.cachedAt && (Date.now() - cf.cachedAt < 60000) && (!optStamp || cf.stamp === optStamp)) {
        var fastSrc = readCached(cf);
        if (fastSrc !== null) return fastSrc;
      }
    } catch (eF) {}
  }
  var stamp = optStamp !== undefined ? optStamp : quickMyStamp_(id);
  if (raw && stamp) {
    try {
      var c = JSON.parse(raw);
      if (c && c.stamp === stamp) {
        var hitSrc = readCached(c);
        if (hitSrc !== null) return hitSrc;
      }
    } catch (e2) {}
  }
  var src = quickMySource_(quickMyContent_(id));
  if (stamp && cache) {
    try {
      var nowTs = Date.now();
      var payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, src: src });
      if (payload.length > 50000 && typeof Utilities !== 'undefined') {
        var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(src, 'text/plain')).getBytes());
        payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, __gz: gz });
      }
      if (payload.length < 95000) cache.put(key, payload, 21600);
    } catch (e3) {}
  }
  return src;
}

function quickMyListCached_(id, optStamp) {
  var cache = comboCache_(), key = 'QUICK_MY_LIST_' + id;
  var stamp = optStamp !== undefined ? optStamp : quickMyStamp_(id);
  var raw = null;
  if (cache) { try { raw = cache.get(key); } catch (eGet) { raw = null; } }
  if (raw && stamp) {
    try {
      var c = JSON.parse(raw);
      if (c.stamp === stamp && c.v === 4) return c.list;
    } catch (e2) {}
  }
  var list = quickParseFns_(quickMySourceCached_(id, stamp));
  if (stamp && cache) { try { cache.put(key, JSON.stringify({ v: 4, stamp: stamp, list: list }), 21600); } catch (e3) {} }
  return list;
}

function quickMyUrl_(id) {
  return 'https://script.google.com/d/' + id + '/edit';
}

function quickDrive_(method, url, payload, ctype) {
  var o = { method: method, headers: { Authorization: 'Bearer ' + comboGetOAuthToken_() }, muteHttpExceptions: true };
  if (payload !== undefined) { o.payload = payload; o.contentType = ctype; }
  var r = UrlFetchApp.fetch(url, o);
  var code = r.getResponseCode();
  if (code !== 200) {
    var msg = r.getContentText().slice(0, 300);
    if (/drive\.scripts/.test(msg)) msg = 'マイマクロに書き込む許可がありません。サイドパネルを再読み込み（または拡張をもう一度開いて許可）してください';
    throw new Error(msg);
  }
  return r.getContentText();
}

function quickMyContent_(id) {
  return JSON.parse(quickDrive_('get', 'https://www.googleapis.com/drive/v3/files/' + id + '/export?mimeType=' + encodeURIComponent(QUICK_SCRIPT_JSON)));
}

function quickMySource_(content) {
  return (content.files || []).filter(function (f) { return f.type === 'server_js'; }).map(function (f) { return f.source; }).join('\n');
}

function quickInsertTop_(source, block) {
  var lines = String(source || '').split('\n'), i = 0;
  while (i < lines.length && /^\s*\/\//.test(lines[i])) i++;
  while (i < lines.length && lines[i].trim() === '') i++;
  var head = lines.slice(0, i).join('\n').replace(/\s*$/, '');
  var rest = lines.slice(i).join('\n').replace(/^\s*/, '');
  return (head ? head + '\n\n' : '') + String(block).replace(/\s*$/, '') + '\n' + (rest ? '\n' + rest : '');
}

function quickParseFns_(src) {
  var lines = String(src || '').split('\n'), out = [], words = [], desc = '', steps = [], noBackup = false;
  var inBlock = false;
  for (var i = 0; i < lines.length; i++) {
    var rawLine = lines[i];
    var ln = rawLine.trim();
    if (inBlock) {
      var endIdx = ln.indexOf('*/');
      if (endIdx < 0) continue;
      ln = ln.slice(endIdx + 2).trim();
      inBlock = false;
      if (!ln) continue;
    }
    while (/^\/\*/.test(ln)) {
      var closeIdx = ln.indexOf('*/', 2);
      if (closeIdx < 0) { inBlock = true; ln = ''; break; }
      ln = ln.slice(closeIdx + 2).trim();
    }
    if (inBlock) continue;
    if (!ln) { words = []; desc = ''; steps = []; noBackup = false; continue; }
    if (/^\/\/\s*控えなし(?:\s|$)/.test(ln)) { noBackup = true; continue; }
    var mw = ln.match(/^\/\/\s*棚\s*[:：]\s*(.+)$/);
    if (mw) { words = words.concat(mw[1].split(/[,、，]/).map(function (s) { return s.trim(); }).filter(String)); continue; }
    var ms = ln.match(/^\/\/\s*手順\s*[:：]\s*(.+)$/);
    if (ms) { steps = steps.concat(quickSplitSteps_(ms[1])); continue; }
    var top = !/^\s/.test(rawLine);
    var mf = top && (ln.match(/^(?:async\s+)?function\s+([^\s(]+)\s*\(/) ||
    ln.match(/^(?:const|let|var)\s+([^\s=]+)\s*=\s*(?:async\s+)?(?:function\s*\(|\([^)]*\)\s*=>|[\w$]+\s*=>)/));
    if (mf) {
      if (!/_$/.test(mf[1])) out.push({ name: mf[1], words: words, desc: desc, steps: steps, noBackup: noBackup });
      words = []; desc = ''; steps = []; noBackup = false;
      continue;
    }
    var mc = ln.match(/^\/\/\s*(.+)$/);
    if (mc) { if (!desc) desc = mc[1].trim(); continue; }
    words = []; desc = ''; steps = []; noBackup = false;
  }
  for (var j = 0; j < out.length; j++) {
    if (!out[j].steps || !out[j].steps.length) {
      var dops = quickExtractDirectOps_(src, out[j].name);
      if (dops && dops.length) out[j].directOps = dops;
    }
  }
  return out;
}

/**
 * マイマクロ関数本体が「静的な shelf(...) 呼び出しのみ」で構成されている場合だけ
 * 直結API用の ops 配列を抽出して返す。変数・制御文・SpreadsheetApp 等が 1 つでもあれば null。
 */
function quickExtractDirectOps_(src, name) {
  try {
    var span = quickFindFnSpan_(src, name);
    if (!span) return null;
    var fnText = String(src || '').slice(span.start, span.end);
    var openBrace = fnText.indexOf('{');
    var closeBrace = fnText.lastIndexOf('}');
    if (openBrace < 0 || closeBrace <= openBrace) return null;
    var body = fnText.slice(openBrace + 1, closeBrace);
    // 文字列リテラルを壊さずにコメントを除去し、文字列外に動的要素がないか厳格検証する
    var stripped = '';
    var nonStr = '';
    var inStr = '', inLine = false, inBlk = false;
    for (var i = 0; i < body.length; i++) {
      var c = body[i], nx = i + 1 < body.length ? body[i + 1] : '';
      if (inLine) { if (c === '\n') { inLine = false; stripped += '\n'; nonStr += '\n'; } continue; }
      if (inBlk) { if (c === '*' && nx === '/') { inBlk = false; i++; } continue; }
      if (inStr) {
        stripped += c;
        if (c === '\\' && i + 1 < body.length) { stripped += body[++i]; continue; }
        if (c === inStr) { inStr = ''; nonStr += '""'; }
        continue;
      }
      if (c === '/' && nx === '/') { inLine = true; i++; continue; }
      if (c === '/' && nx === '*') { inBlk = true; i++; continue; }
      if (c === "'" || c === '"') { inStr = c; stripped += c; continue; }
      if (c === '`') return null; // テンプレートリテラルは式展開を含み得るため対象外
      stripped += c;
      nonStr += c;
    }
    stripped = stripped.trim();
    if (!stripped || stripped.indexOf('shelf') < 0) return null;
    // 文字列外の構文チェック：オブジェクトキー（識別子:）・shelf(・true/false/null・数値・区切り記号のみ許可
    var check = nonStr
      .replace(/""/g, ' ')
      .replace(/\bshelf\s*\(/g, '(')
      .replace(/[A-Za-z_$][\w$]*\s*:/g, ':')
      .replace(/\b(?:true|false|null)\b/g, ' ')
      .replace(/-?\d+(?:\.\d+)?/g, ' ');
    if (/[^\[\]{}(),;:\s]/.test(check)) return null;
    // トップレベル文がすべて shelf(...) 呼び出しのみであることを確認
    if (!/^(?:shelf\s*\([\s\S]*\)\s*;?\s*)+$/.test(stripped)) return null;
    var ops = [];
    var collect = function (opsOrName, optArgs) {
      if (Array.isArray(opsOrName)) {
        for (var k = 0; k < opsOrName.length; k++) ops.push(opsOrName[k]);
      } else if (typeof opsOrName === 'string') {
        ops.push(Object.assign({ shelf: opsOrName }, optArgs || {}));
      } else if (opsOrName && typeof opsOrName === 'object') {
        ops.push(opsOrName);
      } else {
        throw new Error('invalid');
      }
    };
    new Function('shelf', '"use strict";\n' + stripped)(collect);
    if (!ops.length) return null;
    for (var m = 0; m < ops.length; m++) {
      if (!ops[m] || typeof ops[m] !== 'object' || Array.isArray(ops[m]) || typeof ops[m].shelf !== 'string' || !ops[m].shelf.trim()) {
        return null;
      }
    }
    return JSON.parse(JSON.stringify(ops));
  } catch (e) {
    return null;
  }
}

/** ソースコードから指定関数（直上の連続コメント含む）の [start, end] 文字位置を返す。見つからなければ null。 */
function quickFindFnSpan_(src, name) {
  src = String(src || '');
  var esc = String(name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (!esc) return null;
  var re = new RegExp('^(?:async\\s+)?function\\s+' + esc + '\\s*\\(|^(?:const|let|var)\\s+' + esc + '\\s*=\\s*(?:async\\s+)?(?:function\\s*\\(|\\([^)]*\\)\\s*=>|[\\w$]+\\s*=>)', 'm');
  var m = re.exec(src);
  if (!m) return null;
  var defStart = m.index;
  var start = defStart;
  while (start > 0) {
    var prevNl = src.lastIndexOf('\n', start - 2);
    var lineStart = prevNl < 0 ? 0 : prevNl + 1;
    var prevLine = src.slice(lineStart, start - 1).replace(/\r$/, '');
    if (/^\s*\/\//.test(prevLine)) {
      start = lineStart;
    } else {
      break;
    }
  }
  var isArrow = /=>\s*$/.test(m[0]);
  var i = defStart, n = src.length, depth = 0, opened = false;
  var inStr = '', inLineCom = false, inBlkCom = false, inRegex = false, inRegexClass = false;
  var lastSig = '';
  var lastWord = '';
  var canStartRegex = function () {
    if (!lastSig) return true;
    if ('=(,[!&|?:;{}~+-*%^<>'.indexOf(lastSig) >= 0) return true;
    return /^(?:return|throw|case|in|of|typeof|void|delete|new|else|do|yield|await)$/.test(lastWord);
  };
  if (isArrow) {
    var arrowBody = defStart + m[0].length;
    while (arrowBody < n && /\s/.test(src[arrowBody])) arrowBody++;
    if (arrowBody < n && src[arrowBody] !== '{') {
      var pDepth = 0, bDepth = 0;
      for (var k = arrowBody; k < n; k++) {
        var c2 = src[k], nx2 = k + 1 < n ? src[k + 1] : '';
        if (inLineCom) { if (c2 === '\n') { inLineCom = false; if (pDepth === 0 && bDepth === 0) return { start: start, end: k }; } continue; }
        if (inBlkCom) { if (c2 === '*' && nx2 === '/') { inBlkCom = false; k++; } continue; }
        if (inStr) { if (c2 === '\\') { k++; continue; } if (c2 === inStr) inStr = ''; continue; }
        if (c2 === '/' && nx2 === '/') { inLineCom = true; k++; continue; }
        if (c2 === '/' && nx2 === '*') { inBlkCom = true; k++; continue; }
        if (c2 === "'" || c2 === '"' || c2 === '`') { inStr = c2; continue; }
        if (c2 === '(') pDepth++;
        else if (c2 === ')') pDepth = Math.max(0, pDepth - 1);
        else if (c2 === '[') bDepth++;
        else if (c2 === ']') bDepth = Math.max(0, bDepth - 1);
        else if (pDepth === 0 && bDepth === 0 && (c2 === ';' || c2 === '\n')) {
          return { start: start, end: c2 === ';' ? k + 1 : k };
        }
      }
      return { start: start, end: n };
    }
  }
  for (; i < n; i++) {
    var ch = src[i], nx = i + 1 < n ? src[i + 1] : '';
    if (inLineCom) { if (ch === '\n') inLineCom = false; continue; }
    if (inBlkCom) { if (ch === '*' && nx === '/') { inBlkCom = false; i++; } continue; }
    if (inRegex) {
      if (ch === '\\') { i++; continue; }
      if (ch === '[') { inRegexClass = true; continue; }
      if (ch === ']') { inRegexClass = false; continue; }
      if (ch === '/' && !inRegexClass) { inRegex = false; lastSig = ')'; lastWord = ''; continue; }
      if (ch === '\n') { inRegex = false; inRegexClass = false; }
      continue;
    }
    if (inStr) {
      if (ch === '\\') { i++; continue; }
      if (ch === inStr) { inStr = ''; lastSig = ')'; lastWord = ''; }
      continue;
    }
    if (ch === '/' && nx === '/') { inLineCom = true; i++; continue; }
    if (ch === '/' && nx === '*') { inBlkCom = true; i++; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { inStr = ch; continue; }
    if (ch === '/' && canStartRegex()) { inRegex = true; inRegexClass = false; continue; }
    if (ch === '{') { depth++; opened = true; lastSig = '{'; lastWord = ''; continue; }
    if (ch === '}') {
      depth--;
      lastSig = '}'; lastWord = '';
      if (opened && depth === 0) {
        var end = i + 1;
        if (src[end] === ';') end++;
        return { start: start, end: end };
      }
      continue;
    }
    if (!/\s/.test(ch)) {
      if (/[\w$]/.test(ch)) {
        lastWord = /[\w$]/.test(lastSig) ? (lastWord + ch) : ch;
      } else {
        lastWord = '';
      }
      lastSig = ch;
    }
  }
  return null;
}

/** マイマクロ・並び順・ピン留め一覧を返す（ブラウザ連動アドオン用）。 */
function comboQuickList(req) {
  var t0 = Date.now();
  req = req || {};
  var allProps = req._allProps;
  if (!allProps) {
    try { allProps = PropertiesService.getUserProperties().getProperties() || {}; } catch (eP) { allProps = {}; }
  }
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim();
  var res = {
    ok: true,
    sheet: [],
    my: [],
    myId: '',
    myUrl: '',
    myStamp: '',
    oauthToken: req._skipToken ? '' : comboGetOAuthToken_(),
    order: quickGetOrders_(allProps, ssId),
    pins: quickGetPins_(allProps)
  };
  try {
    var meta = quickMyFind_(true, allProps, !!req.force);
    if (meta && meta.id) {
      if (req.force) {
        var cF = comboCache_();
        if (cF) {
          try {
            cF.remove('QUICK_MY_LIST_' + meta.id);
            cF.remove('QUICK_MY_SRC_' + meta.id);
          } catch (eInv) {}
        }
      }
      res.myId = meta.id;
      res.myUrl = quickMyUrl_(meta.id);
      res.myStamp = meta.stamp || '';
      res.my = quickMyListCached_(meta.id, meta.stamp || undefined);
      if (req.wantCodes && meta.stamp && meta.stamp !== String(req.clientStamp || '')) {
        try {
          var srcAll = quickMySourceCached_(meta.id, meta.stamp || undefined, true);
          if (srcAll && srcAll.length < 60000) {
            var codes = {};
            for (var j = 0; j < res.my.length; j++) {
              var fnSp = quickFindFnSpan_(srcAll, res.my[j].name);
              if (fnSp) codes[res.my[j].name] = srcAll.slice(fnSp.start, fnSp.end);
            }
            res.myCodes = codes;
          }
        } catch (eCode) {}
      }
    }
  } catch (e) {
    res.myError = String(e && e.message || e);
  }
  res.gasMs = Date.now() - t0;
  return res;
}

function quickDropBackup_(ss) {
  try {
    var old = ss.getSheetByName(QUICK_BK_NAME);
    if (old) ss.deleteSheet(old);
  } catch (e) {}
}

function comboFastUndoClearLocal_(ss, optStack, optFromProp) {
  var cache = comboCache_();
  var ssId = ss ? ss.getId() : '';
  if (cache) {
    try {
      if (optStack && optStack.length > 0 && ssId) {
        var restStr = JSON.stringify({ __stack: optStack, ssId: ssId });
        if (restStr.length > 50000 && typeof Utilities !== 'undefined') {
          var gzRest = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(restStr, 'application/json')).getBytes());
          restStr = JSON.stringify({ __gz: gzRest, ssId: ssId });
        }
        if (restStr.length <= 95000) cache.put(COMBO_PROP_FAST_UNDO, restStr, COMBO_TBL_CACHE_TTL);
        else cache.remove(COMBO_PROP_FAST_UNDO);
      } else {
        var prev = cache.get(COMBO_PROP_FAST_UNDO);
        if (prev && prev.indexOf('"sheetcopy"') >= 0 && ss) quickDropBackup_(ss);
        cache.remove(COMBO_PROP_FAST_UNDO);
      }
    } catch (eU) {}
  }
  if (optFromProp) {
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eP) {}
  }
}

function comboQuickSnapForSs_(ss, sh, what) {
  try {
    if (!ss || !sh || sh.getName() === QUICK_BK_NAME) return false;
    var ssId = ss.getId();
    quickDropBackup_(ss);
    var bk = sh.copyTo(ss);
    bk.setName(QUICK_BK_NAME);
    if (typeof bk.hideSheet === 'function') bk.hideSheet();
    var snap = {
      kind: 'sheetcopy',
      ssId: ssId,
      sheetName: sh.getName(),
      bk: QUICK_BK_NAME,
      a1: 'シート全体',
      what: String(what || 'マクロ'),
      ts: Date.now(),
      frozenR: typeof sh.getFrozenRows === 'function' ? sh.getFrozenRows() : 0,
      frozenC: typeof sh.getFrozenColumns === 'function' ? sh.getFrozenColumns() : 0
    };
    var cache = comboCache_();
    if (cache) cache.put(COMBO_PROP_FAST_UNDO, JSON.stringify(snap), COMBO_TBL_CACHE_TTL);
    return true;
  } catch (e) {
    comboFastUndoClearLocal_(ss, null, true);
    return false;
  }
}

function quickRestoreSheetCopy_(ss, snap, optStack, optFromProp) {
  var t0 = Date.now();
  var ssId = ss.getId();
  var sh = ss.getSheetByName(snap.sheetName);
  var bk = ss.getSheetByName(snap.bk || QUICK_BK_NAME);
  if (!sh) return { ok: false, error: 'シート「' + snap.sheetName + '」が見つかりません' };
  if (!bk) {
    comboFastUndoClearLocal_(ss, optStack, optFromProp);
    return { ok: false, error: '控えのシートが見つかりません（消されたか、次のマクロで入れ替わりました）' };
  }
  var maxR = typeof bk.getMaxRows === 'function' ? bk.getMaxRows() : bk.getLastRow();
  var maxC = typeof bk.getMaxColumns === 'function' ? bk.getMaxColumns() : bk.getLastColumn();
  var isHuge = (maxR * maxC > 50000);
  var nr = isHuge ? Math.min(maxR, Math.max(bk.getLastRow() + 20, sh.getLastRow() + 20, 50)) : maxR;
  var nc = isHuge ? Math.min(maxC, Math.max(bk.getLastColumn() + 5, sh.getLastColumn() + 5, 26)) : maxC;
  if (typeof sh.getMaxRows === 'function' && sh.getMaxRows() < nr && typeof sh.insertRowsAfter === 'function') sh.insertRowsAfter(sh.getMaxRows(), nr - sh.getMaxRows());
  if (typeof sh.getMaxColumns === 'function' && sh.getMaxColumns() < nc && typeof sh.insertColumnsAfter === 'function') sh.insertColumnsAfter(sh.getMaxColumns(), nc - sh.getMaxColumns());
  var clrR = isHuge && typeof sh.getMaxRows === 'function' ? Math.min(sh.getMaxRows(), Math.max(sh.getLastRow() + 20, nr)) : (typeof sh.getMaxRows === 'function' ? sh.getMaxRows() : nr);
  var clrC = isHuge && typeof sh.getMaxColumns === 'function' ? Math.min(sh.getMaxColumns(), Math.max(sh.getLastColumn() + 5, nc)) : (typeof sh.getMaxColumns === 'function' ? sh.getMaxColumns() : nc);
  var all = sh.getRange(1, 1, clrR, clrC);
  if (typeof all.breakApart === 'function') all.breakApart();
  if (typeof all.clear === 'function') all.clear();
  if (typeof all.clearDataValidations === 'function') all.clearDataValidations();
  try { sh.getBandings().forEach(function (b) { b.remove(); }); } catch (eB) {}
  try { var flt = sh.getFilter(); if (flt) flt.remove(); } catch (eF) {}
  var src = bk.getRange(1, 1, nr, nc);
  src.copyTo(sh.getRange(1, 1, nr, nc));
  if (typeof SpreadsheetApp !== 'undefined' && SpreadsheetApp.CopyPasteType && SpreadsheetApp.CopyPasteType.PASTE_COLUMN_WIDTHS) {
    src.copyTo(sh.getRange(1, 1, nr, nc), SpreadsheetApp.CopyPasteType.PASTE_COLUMN_WIDTHS, false);
  }
  if (!isHuge && typeof sh.getMaxRows === 'function' && typeof sh.deleteRows === 'function' && sh.getMaxRows() > nr) sh.deleteRows(nr + 1, sh.getMaxRows() - nr);
  if (!isHuge && typeof sh.getMaxColumns === 'function' && typeof sh.deleteColumns === 'function' && sh.getMaxColumns() > nc) sh.deleteColumns(nc + 1, sh.getMaxColumns() - nc);
  if (snap.frozenR !== undefined && typeof sh.getFrozenRows === 'function' && sh.getFrozenRows() !== snap.frozenR) sh.setFrozenRows(snap.frozenR);
  if (snap.frozenC !== undefined && typeof sh.getFrozenColumns === 'function' && sh.getFrozenColumns() !== snap.frozenC) sh.setFrozenColumns(snap.frozenC);
  ss.deleteSheet(bk);
  comboFastUndoClearLocal_(ss, optStack, optFromProp);
  comboCacheInvalidate_(ssId, sh.getName());
  var cachedUndo = comboCacheGet_(ssId, sh.getName());
  var target = {
    id: ssId,
    name: (cachedUndo && cachedUndo.ssName) || ss.getName(),
    kind: 'sheet',
    url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit',
    sheet: sh.getName()
  };
  return {
    ok: true,
    fast: true,
    undone: 'fast',
    what: snap.what,
    target: target,
    oauthToken: comboGetOAuthToken_(),
    text: '対象: ' + target.name + ' › ' + target.sheet + '\n戻した: シート全体（' + snap.what + ' の前）に戻しました',
    gasMs: Date.now() - t0
  };
}

function quickUndoNote_(snapped, backupOn, noBackup) {
  if (noBackup) return '（控えなし指定）';
  if (backupOn === false) return '（控えなし・取り消し不可・Ctrl+Z 推奨）';
  return snapped ? '' : '（控えを取れませんでした。取り消しは Ctrl+Z で）';
}

function quickFormatMyErr_(name, err, isCompile) {
  var msg = String(err && err.message || err);
  if (isCompile) {
    return 'マイマクロの構文エラーで実行できません: ' + msg + '（「編集」で赤い波線の箇所を確認してください）';
  }
  var lineHint = '';
  try {
    var st = String(err && err.stack || '');
    var m = st.match(/<anonymous>:(\d+)(?::\d+)?/);
    if (m) {
      var ln = parseInt(m[1], 10);
      if (ln > 2) lineHint = '（マイマクロ ' + (ln - 2) + ' 行目付近）';
    }
  } catch (e) {}
  return name + ' でエラー' + lineHint + ': ' + msg;
}

function comboQuickAfter_(ss, sh) {
  try {
    if (ss && sh) comboCacheInvalidate_(ss.getId(), sh.getName());
  } catch (e) {}
}

/** WebApp（getActive() が null の環境）向け SpreadsheetApp/Spreadsheet/Sheet Proxy を生成する。 */
function quickMakeSsProxy_(ss, sheetName, selA1) {
  var targetSh = sheetOf_(ss, sheetName, '');
  var rawSel = String(selA1 || '').trim();
  var bangIdx = rawSel.indexOf('!');
  if (bangIdx >= 0) rawSel = rawSel.slice(bangIdx + 1).trim();
  var selParts = (rawSel || 'A1').split(/\s*,\s*/).map(function (s) { return s.trim(); }).filter(Boolean);
  if (!selParts.length) selParts = ['A1'];
  var toasts = [];
  var unwrap = function (x) { return (x && x.__raw) ? x.__raw : x; };
  var resolveRange = function (shObj, a1) {
    var target = unwrap(shObj) || targetSh;
    var q = String(a1 || selParts[0] || 'A1').trim();
    try { return target.getRange(q); } catch (e) { return target.getRange(1, 1); }
  };
  var resolveRangeList = function (shObj) {
    var target = unwrap(shObj) || targetSh;
    if (typeof target.getRangeList === 'function') {
      try { return target.getRangeList(selParts); } catch (e1) {}
    }
    var ranges = selParts.map(function (p) { return resolveRange(target, p); });
    return { getRanges: function () { return ranges; } };
  };
  var wrapSheet = function (shObj) {
    if (typeof Proxy === 'undefined') return shObj;
    return new Proxy(shObj, {
      get: function (target, prop) {
        if (prop === '__raw') return target;
        if (prop === 'getActiveRange') return function () { return resolveRange(target, selParts[0]); };
        if (prop === 'getActiveCell') return function () { return resolveRange(target, selParts[0].split(':')[0] || 'A1'); };
        if (prop === 'getActiveRangeList') return function () { return resolveRangeList(target); };
        var v = target[prop];
        if (typeof v === 'function') {
          return function () {
            var args = Array.prototype.slice.call(arguments).map(unwrap);
            return v.apply(target, args);
          };
        }
        return v;
      }
    });
  };
  var shProxy = wrapSheet(targetSh);
  var makeSelObj = function () {
    return {
      getActiveRange: function () { return resolveRange(targetSh, selParts[0]); },
      getActiveRangeList: function () { return resolveRangeList(targetSh); },
      getCurrentCell: function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); },
      getActiveSheet: function () { return shProxy; }
    };
  };
  var ssProxy = typeof Proxy === 'undefined' ? ss : new Proxy(ss, {
    get: function (target, prop) {
      if (prop === '__raw') return target;
      if (prop === 'getActiveSheet') return function () { return shProxy; };
      if (prop === 'getActiveRange') return function () { return resolveRange(targetSh, selParts[0]); };
      if (prop === 'getActiveCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'getActiveRangeList') return function () { return resolveRangeList(targetSh); };
      if (prop === 'getCurrentCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'getSelection') return makeSelObj;
      if (prop === 'getDataRange') return function () { return targetSh.getDataRange(); };
      if (prop === 'getLastRow') return function () { return targetSh.getLastRow(); };
      if (prop === 'getLastColumn') return function () { return targetSh.getLastColumn(); };
      if (prop === 'getRange') {
        return function (a1OrRow) {
          if (typeof a1OrRow === 'string' && a1OrRow.indexOf('!') < 0) return targetSh.getRange(a1OrRow);
          return target.getRange.apply(target, Array.prototype.slice.call(arguments).map(unwrap));
        };
      }
      if (prop === 'getRangeList') {
        return function (a1s) {
          var arr = Array.isArray(a1s) ? a1s : [a1s];
          if (arr.every(function (s) { return String(s).indexOf('!') < 0; }) && typeof targetSh.getRangeList === 'function') {
            return targetSh.getRangeList(arr);
          }
          return target.getRangeList.apply(target, Array.prototype.slice.call(arguments).map(unwrap));
        };
      }
      if (prop === 'setActiveSheet') {
        return function (s) {
          var raw = unwrap(s);
          if (raw && typeof raw.getName === 'function') { targetSh = raw; shProxy = wrapSheet(raw); }
          try { return target.setActiveSheet(raw); } catch (e) { return raw; }
        };
      }
      if (prop === 'setActiveRange') {
        return function (rg) {
          var rawR = unwrap(rg);
          if (rawR && typeof rawR.getA1Notation === 'function') selParts = [rawR.getA1Notation()];
          try { return target.setActiveRange(rawR); } catch (e) { return rawR; }
        };
      }
      if (prop === 'setActiveRangeList') {
        return function (rgl) {
          var rawL = unwrap(rgl);
          if (rawL && typeof rawL.getRanges === 'function') {
            try {
              var a1s = rawL.getRanges().map(function (x) { return x.getA1Notation(); }).filter(Boolean);
              if (a1s.length) selParts = a1s;
            } catch (eR) {}
          }
          try { return target.setActiveRangeList(rawL); } catch (e) { return rawL; }
        };
      }
      if (prop === 'getSheetByName') {
        return function (n) {
          var s = target.getSheetByName(n);
          if (!s) return null;
          return s.getName() === targetSh.getName() ? shProxy : wrapSheet(s);
        };
      }
      if (prop === 'toast') {
        return function (msg) {
          toasts.push(String(msg || ''));
          try { return target.toast.apply(target, arguments); } catch (e) {}
        };
      }
      var v = target[prop];
      if (typeof v === 'function') {
        return function () {
          var args = Array.prototype.slice.call(arguments).map(unwrap);
          return v.apply(target, args);
        };
      }
      return v;
    }
  });
  var ssApp = (typeof SpreadsheetApp !== 'undefined') ? SpreadsheetApp : {};
  var ssAppProxy = typeof Proxy === 'undefined' ? ssApp : new Proxy(ssApp, {
    get: function (target, prop) {
      if (prop === 'getActive' || prop === 'getActiveSpreadsheet') return function () { return ssProxy; };
      if (prop === 'getActiveSheet') return function () { return shProxy; };
      if (prop === 'getActiveRange') return function () { return resolveRange(targetSh, selParts[0]); };
      if (prop === 'getActiveRangeList') return function () { return resolveRangeList(targetSh); };
      if (prop === 'getCurrentCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'flush') return function () { try { if (target && target.flush) target.flush(); } catch (e) {} };
      if (prop === 'getUi') {
        return function () {
          return {
            alert: function (m1, m2) { toasts.push(String(m2 || m1 || '')); },
            toast: function (m) { toasts.push(String(m || '')); },
            prompt: function () { throw new Error('ブラウザ連動のサイドパネル側では prompt ダイアログは使えません'); }
          };
        };
      }
      var v = target[prop];
      if (typeof v === 'function') {
        return function () {
          var args = Array.prototype.slice.call(arguments).map(unwrap);
          return v.apply(target, args);
        };
      }
      return v;
    }
  });
  return { spreadsheetApp: ssAppProxy, ss: ssProxy, sheet: shProxy, toasts: toasts };
}

/** マイマクロの 1 本を実行する（WebApp 環境でも対象シート＋選択セル Proxy で動作）。 */
function comboQuickRun(req) {
  var t0 = Date.now();
  req = req || {};
  var name = String(req.name || '');
  var backupOn = req.backup === undefined ? true : !!req.backup;
  if (req.src === 'sheet') {
    return { ok: false, error: 'GASコンボ（ブラウザ連動）ではシート組込マクロは対象外です' };
  }
  try {
    var reqId = String(req.myId || '').trim();
    var reqStamp = String(req.myStamp || '').trim();
    var meta = reqId ? { id: reqId, stamp: reqStamp || quickMyStamp_(reqId) } : quickMyFind_(true);
    if (!meta || !meta.id) meta = quickMyFind_(true);
    if (!meta || !meta.id) return { ok: false, error: 'マイマクロがまだありません。一覧の「＋追加」や「マイマクロを作る」を押してください' };
    var id = meta.id;
    var src = quickMySourceCached_(id, meta.stamp || undefined, true);
    var listM = quickMyListCached_(id, meta.stamp || undefined);
    var hit = listM.filter(function (f) { return f.name === name; })[0];
    if (!hit) hit = quickParseFns_(src).filter(function (f) { return f.name === name; })[0];
    if (!hit) return { ok: false, error: 'マイマクロに「' + name + '」が見つかりません（一覧を更新してください）' };
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var sh = sheetOf_(ss, selInfo.sheet, '');
    var px = quickMakeSsProxy_(ss, sh.getName(), selInfo.selection || req.selection || '');
    var shelfFn = function (opsOrName, optArgs) {
      var normOps;
      if (Array.isArray(opsOrName)) {
        normOps = opsOrName;
      } else if (typeof opsOrName === 'string') {
        normOps = [Object.assign({ shelf: opsOrName }, optArgs || {})];
      } else if (opsOrName && typeof opsOrName === 'object') {
        normOps = [opsOrName];
      } else {
        throw new Error('shelf() の引数は棚配列・棚オブジェクト・棚名文字列のいずれかにしてください');
      }
      var curShName = (px.ss && px.ss.getActiveSheet) ? px.ss.getActiveSheet().getName() : sh.getName();
      var sRes = comboRunOps({
        ops: normOps,
        ok: true,
        backup: false,
        fastUndo: false,
        sheet: curShName,
        selection: selInfo.selection || req.selection || '',
        targetId: ss.getId(),
        _ss: ss,
        _ssName: ss.getName()
      });
      if (!sRes || !sRes.ok) {
        throw new Error((sRes && (sRes.error || sRes.text)) || '棚の実行に失敗しました');
      }
      return sRes;
    };
    var mod;
    try {
      mod = new Function('SpreadsheetApp', 'shelf', src + '\nreturn {' + JSON.stringify(name) + ': ' + name + '};')(px.spreadsheetApp, shelfFn);
    } catch (eComp) {
      return { ok: false, error: quickFormatMyErr_(name, eComp, true), gasMs: Date.now() - t0 };
    }
    var noBkM = !!hit.noBackup;
    var snapped = false;
    if (backupOn && !noBkM) {
      snapped = comboQuickSnapForSs_(ss, sh, name);
    } else {
      comboFastUndoClearLocal_(ss, null, true);
    }
    var r = mod[name]();
    comboQuickAfter_(ss, sh);
    var msgParts = [];
    if (r !== undefined && r !== null && r !== '' && typeof r.then !== 'function') {
      msgParts.push(String(r).slice(0, 200));
    }
    if (px.toasts.length) {
      msgParts.push(px.toasts.join(' / ').slice(0, 200));
    }
    return {
      ok: true,
      snapped: snapped,
      myStamp: meta.stamp,
      text: name + ' を実行しました' + (msgParts.length ? '（' + msgParts.join(' / ') + '）' : '') + quickUndoNote_(snapped, backupOn, noBkM),
      gasMs: Date.now() - t0
    };
  } catch (e) {
    return { ok: false, error: quickFormatMyErr_(name, e, false), gasMs: Date.now() - t0 };
  }
}

/** マイマクロを作る（あれば番地を返すだけ）。 */
function comboQuickMake(req) {
  try {
    req = req || {};
    var id = quickMyFind_(false, null, !!req.force);
    if (id) return { ok: true, myId: id, myUrl: quickMyUrl_(id), created: false, text: 'マイマクロはもうあります' };
    var guide = [
      '// GASクイック マイマクロ',
      '// ここに置いた関数は、どのシートでも GASクイック／GASコンボの一覧に並び、選んで実行できます。',
      '// 作り方: function 名前() { ... } を書く。すぐ上に「// 棚: 言い方, 言い方」と書くと、頼みの欄の言葉でも当たります。',
      '// 棚の言葉を「// 手順: 見出しを黄色に / 太字にして」と書くと、直結APIで高速にまとめて撃てます。',
      '// 今のシートは SpreadsheetApp.getActive() で取れます。名前の末尾が _ の関数は部品として一覧に出しません。',
      '// 新しいマクロは、この手引きのすぐ下（先頭）に足します。一覧でも、新しい物は一番上に出ます。',
      '',
      '// 選んでいる範囲を太字にする（もう一度押すと太字を外す）',
      '// 棚: 太字にする, 選んだ所を太字, 太字を外す',
      'function 選んだ所を太字() {',
      '  var list = SpreadsheetApp.getActive().getActiveRangeList();',
      '  var first = list.getRanges()[0];',
      "  var isBold = first && first.getFontWeight() === 'bold';",
      "  list.setFontWeight(isBold ? 'normal' : 'bold');",
      '}',
      '',
      '// 選んでいる範囲の背景色を消す',
      '// 棚: 色を消す, 選んだ所の色を消す, 背景色を消す',
      'function 選んだ所の色を消す() {',
      '  SpreadsheetApp.getActive().getActiveRangeList().setBackground(null);',
      '}',
      '',
      '// 1 行目（見出し）の背景を薄い黄色にする',
      '// 棚: 見出しを黄色に, 見出しに色を付ける',
      'function 見出しを黄色に() {',
      '  var sh = SpreadsheetApp.getActiveSheet();',
      '  var lastCol = Math.max(1, sh.getLastColumn());',
      "  sh.getRange(1, 1, 1, lastCol).setBackground('#fef08a');",
      '}',
      ''
    ].join('\n');
    var content = { files: [
      { name: 'appsscript', type: 'json', source: JSON.stringify({ timeZone: 'Asia/Tokyo', runtimeVersion: 'V8', exceptionLogging: 'STACKDRIVER' }) },
      { name: 'マイマクロ', type: 'server_js', source: guide }
    ] };
    var b = 'gasquick' + Date.now();
    var body = '--' + b + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' +
      JSON.stringify({ name: QUICK_MY_TITLE, mimeType: 'application/vnd.google-apps.script' }) +
      '\r\n--' + b + '\r\nContent-Type: ' + QUICK_SCRIPT_JSON + '\r\n\r\n' + JSON.stringify(content) + '\r\n--' + b + '--';
    var made = JSON.parse(quickDrive_('post', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart', body, 'multipart/related; boundary=' + b));
    try { PropertiesService.getUserProperties().setProperty(QUICK_MY_ID_KEY, made.id); } catch (eP) {}
    var newStamp = quickMyCachePut_(made.id, guide);
    return { ok: true, myId: made.id, myUrl: quickMyUrl_(made.id), myStamp: newStamp, created: true, text: 'マイマクロを作りました' };
  } catch (e) {
    return { ok: false, error: 'マイマクロを作れませんでした: ' + String(e && e.message || e) };
  }
}

/** 履歴や入力から「⚡ 手順つきマクロ」をマイマクロの先頭へ直接保存する。 */
function comboQuickSaveSteps(req) {
  req = req || {};
  try {
    var rawName = String(req.name || '').trim();
    var safeName = rawName.replace(/[\s　.,:;!?()\[\]{}'"`/\\+\-*=<>|&^%$#@~]+/g, '_').replace(/^_+|_+$/g, '');
    if (!safeName) return { ok: false, error: 'マクロ名を入力してください' };
    if (/^\d/.test(safeName) || QUICK_JS_RESERVED_[safeName]) safeName = '手順_' + safeName;
    if (/_$/.test(safeName)) safeName = safeName.replace(/_+$/, '') + '実行';
    var steps = Array.isArray(req.steps)
      ? req.steps.map(function (s) { return String(s || '').trim().replace(/\r?\n/g, ' '); }).filter(String)
      : quickSplitSteps_(String(req.steps || '').replace(/\r?\n/g, ' ／ '));
    if (!steps.length) return { ok: false, error: '手順が空です' };
    var dateStr = typeof Utilities !== 'undefined' ? Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd') : '登録';
    var desc = (String(req.desc || '').trim() || ('手順マクロ（' + dateStr + ' 登録）')).replace(/\r?\n/g, ' ');
    var stepLines = steps.map(function (st) {
      return '// 手順: ' + String(st).replace(/\//g, '\\/').replace(/／/g, '\\／');
    });
    var block = ['// ' + desc].concat(stepLines, [
      'function ' + safeName + '() {',
      '  // 一覧から実行すると、上の手順を高速APIでまとめて実行します',
      '}'
    ]).join('\n');
    try {
      new Function(block);
    } catch (eSyn) {
      return { ok: false, error: 'マクロ名または構文が不正です: ' + String(eSyn && eSyn.message || eSyn) };
    }
    var made = comboQuickMake({});
    if (!made.ok) return made;
    var content = quickMyContent_(made.myId);
    var all = quickMySource_(content);
    if (quickParseFns_(all).some(function (f) { return f.name === safeName; })) {
      return { ok: false, error: 'マイマクロに同じ名前「' + safeName + '」があります（別の名前にしてください）' };
    }
    var file = (content.files || []).filter(function (f) { return f.type === 'server_js'; })[0];
    if (!file) return { ok: false, error: 'マイマクロのコードファイルが見つかりません' };
    file.source = quickInsertTop_(file.source, block);
    quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + made.myId + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
    var newStamp = quickMyCachePut_(made.myId, quickMySource_(content));
    return { ok: true, name: safeName, myId: made.myId, myUrl: made.myUrl, myStamp: newStamp, text: '⚡ 手順マクロ「' + safeName + '」をマイマクロに保存しました' };
  } catch (e) {
    return { ok: false, error: '手順マクロを保存できませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロから指定関数のコードだけを抜き出して返す。 */
function comboQuickGetFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  try {
    var reqId = String(req.myId || '').trim();
    var reqStamp = String(req.myStamp || '').trim();
    var id = reqId || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var src = '';
    var stamp = reqStamp;
    try {
      src = quickMySourceCached_(id, stamp || undefined, true);
    } catch (eCache) {
      src = '';
    }
    var sp = src ? quickFindFnSpan_(src, name) : null;
    if (!sp) {
      var meta = quickMyFind_(true);
      if (meta && meta.id) {
        id = meta.id;
        stamp = meta.stamp || '';
      }
      var content = quickMyContent_(id);
      src = quickMySource_(content);
      stamp = quickMyCachePut_(id, src, stamp || undefined);
      sp = quickFindFnSpan_(src, name);
    }
    if (!sp) {
      return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
    }
    var res = {
      ok: true,
      name: name,
      code: src.slice(sp.start, sp.end),
      myId: id,
      myStamp: stamp || '',
      myUrl: quickMyUrl_(id)
    };
    if (req.includeAll && src.length < 90000) {
      var codes = {};
      var fns = quickParseFns_(src);
      for (var j = 0; j < fns.length; j++) {
        var fnSp = quickFindFnSpan_(src, fns[j].name);
        if (fnSp) codes[fns[j].name] = src.slice(fnSp.start, fnSp.end);
      }
      res.codes = codes;
    }
    return res;
  } catch (e) {
    return { ok: false, error: 'コードを読めませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロの指定関数だけを編集後のコードでピンポイント上書き保存する。 */
function comboQuickSaveFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  var code = String(req.code || '').replace(/\r\n/g, '\n').replace(/\s*$/, '');
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  if (!code) return { ok: false, error: 'コードが空です' };
  try {
    new Function(code);
  } catch (eSyn) {
    return { ok: false, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsedNew = quickParseFns_(code);
  if (!parsedNew.length) {
    return { ok: false, error: '関数定義（function 名前() { ... }）が見つかりません' };
  }
  try {
    var id = String(req.myId || '').trim() || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var content = quickMyContent_(id);
    var files = (content.files || []).filter(function (f) { return f.type === 'server_js'; });
    for (var i = 0; i < files.length; i++) {
      var sp = quickFindFnSpan_(files[i].source, name);
      if (sp) {
        var allOther = quickMySource_(content);
        var existing = {};
        quickParseFns_(allOther).forEach(function (f) { if (f.name !== name) existing[f.name] = true; });
        var dup = parsedNew.filter(function (f) { return existing[f.name]; }).map(function (f) { return f.name; });
        if (dup.length) {
          return { ok: false, error: '同じ名前「' + dup.join('・') + '」がすでにあります（別の名前にしてください）' };
        }
        files[i].source = files[i].source.slice(0, sp.start) + code + files[i].source.slice(sp.end);
        quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + id + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
        var newStamp = quickMyCachePut_(id, quickMySource_(content));
        var newName = parsedNew[0].name || name;
        return { ok: true, name: name, newName: newName, myStamp: newStamp, text: '「' + newName + '」を保存しました' };
      }
    }
    return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
  } catch (e) {
    return { ok: false, error: '保存できませんでした: ' + String(e && e.message || e) };
  }
}

/** 新しい関数をマイマクロの先頭へ追加する（未作成なら自動作成）。 */
function comboQuickAddFn(req) {
  req = req || {};
  var code = String(req.code || '').replace(/\r\n/g, '\n').replace(/^\s*\n+/, '').replace(/\s*$/, '');
  if (!code) return { ok: false, error: 'コードが空です' };
  try {
    new Function(code);
  } catch (eSyn) {
    return { ok: false, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsed = quickParseFns_(code);
  if (!parsed.length) {
    return { ok: false, error: '関数定義（function 名前() { ... }）が見つかりません' };
  }
  try {
    var made = comboQuickMake({});
    if (!made.ok) return made;
    var content = quickMyContent_(made.myId);
    var all = quickMySource_(content);
    var existing = {};
    quickParseFns_(all).forEach(function (f) { existing[f.name] = true; });
    var dup = parsed.filter(function (f) { return existing[f.name]; }).map(function (f) { return f.name; });
    if (dup.length) {
      return { ok: false, error: '同じ名前「' + dup.join('・') + '」がすでにあります（編集から直すか別の名前にしてください）' };
    }
    var file = (content.files || []).filter(function (f) { return f.type === 'server_js'; })[0];
    if (!file) return { ok: false, error: 'マイマクロのコードファイルが見つかりません' };
    file.source = quickInsertTop_(file.source, code);
    quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + made.myId + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
    var newStamp = quickMyCachePut_(made.myId, quickMySource_(content));
    var names = parsed.map(function (f) { return f.name; });
    return { ok: true, names: names, myId: made.myId, myUrl: made.myUrl, myStamp: newStamp, text: '「' + names.join('・') + '」をマイマクロに追加しました' };
  } catch (e) {
    return { ok: false, error: '追加できませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロから指定関数を削除する。 */
function comboQuickDeleteFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  try {
    var id = String(req.myId || '').trim() || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var content = quickMyContent_(id);
    var files = (content.files || []).filter(function (f) { return f.type === 'server_js'; });
    for (var i = 0; i < files.length; i++) {
      var sp = quickFindFnSpan_(files[i].source, name);
      if (sp) {
        var before = files[i].source.slice(0, sp.start).replace(/\n+$/, '');
        var after = files[i].source.slice(sp.end).replace(/^\n+/, '');
        files[i].source = (before && after) ? (before + '\n\n' + after) : (before || after) + '\n';
        quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + id + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
        var newStamp = quickMyCachePut_(id, quickMySource_(content));
        return { ok: true, name: name, myStamp: newStamp, text: '「' + name + '」をマイマクロから削除しました' };
      }
    }
    return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
  } catch (e) {
    return { ok: false, error: '削除できませんでした: ' + String(e && e.message || e) };
  }
}

/** コードフェンス（```js / ```gs 等）を外して生コードを返す。 */
function quickStripCodeFence_(txt) {
  var s = String(txt || '').trim();
  var m = s.match(/^```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/i);
  if (m) return m[1].trim();
  var mInline = s.match(/```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```/i);
  if (mInline) return mInline[1].trim();
  return s;
}

/** マイマクロ生成・修正用のシステム／ユーザープロンプトを組み立てる。 */
function comboBuildAiMyMacroPrompts_(mode, prompt, ssName, sheetName, selection, table, sheets, targetName, existingCode, existingNames, history, allowChat) {
  var isEdit = mode === 'edit';
  var canChat = !!allowChat;
  var sys = [
    'あなたは Google スプレッドシート用の Google Apps Script（GAS）マイマクロ作成・修正アシスタントです。',
    'ユーザーが自然言語で伝えた要望を、GASコンボ（WebApp 経由でも動作する Proxy 環境）でそのまま実行できる関数 1 個として出力・提案してください。',
    '必ず有効な JSON オブジェクト 1 個だけを返してください（JSON 以外の説明文や挨拶は書かないこと）。',
    canChat
      ? '・相談・質問・改修案の提案（「どんな編集ができますか？」「このコードの意味は？」「案を出して」等、まだコード書き換えの確定指示ではない場合）: {"action":"reply","message":"簡潔に（箇条書き 3〜5 個・合計 200 文字以内を目安、番号付きで選びやすく）"}'
      : '・要望が極めて曖昧で作成不能な場合のみ: {"action":"reply","message":"確認したい点"}',
    '・コードの作成・修正の指示または合意（「作って」「〜に直して」「じゃあ1番でお願い」「それでお願い」等）: {"action":"mymacro","code":"// 説明\\n// 棚: 呼び方1, 呼び方2\\nfunction 分かりやすい日本語名() {\\n  ...\\n}","note":"何を作った・どう直したかの1行要約"}',
    '必須ルール:',
    '1. インデントなしのトップレベル function 名前() { ... } を 1 つ定義し、引数は取らないこと（補助関数は末尾に _ を付け可）。メイン関数名の末尾に _ は付けないこと。',
    '2. 関数の直上の行に「// 説明」と「// 棚: 言い方1, 言い方2」のコメントを書くこと。',
    '3. SpreadsheetApp.openById() 等で固定IDを書かず、必ず SpreadsheetApp.getActive() / SpreadsheetApp.getActiveSheet() / SpreadsheetApp.getActiveRange() / SpreadsheetApp.getActiveRangeList() を使うこと。',
    '4. 1セルずつの getValue/setValue ループは避け、getValues()/setValues() や getBackgrounds()/setBackgrounds() で2次元配列一括処理すること。',
    '5. ユーザーへの結果通知には Browser.msgBox や ui.prompt は使わず、return "完了メッセージ"; を使うこと。',
    '6. 既存の棚（ws_shelves）でできる処理（表整理・書式・列幅・集計・フィルタ・罫線・並べ替え等）は自前で長く実装せず、shelf([{shelf:"棚名", ...}, ...]) または shelf("棚名", {...}) を呼んで複数の棚を束ねる「まとめ棚」として組み、棚に無い固有処理だけ SpreadsheetApp で補うこと。'
  ].join('\n');

  var lines = [
    isEdit ? '【依頼種別】既存マイマクロの相談・修正' : '【依頼種別】新規マイマクロの相談・作成',
    '【現在の対象状態】',
    'ブック: ' + (ssName || '(不明)') + ' / シート: ' + (sheetName || '(先頭シート)')
  ];
  if (Array.isArray(sheets) && sheets.length) lines.push('全シート: ' + sheets.join('、'));
  if (selection) lines.push('選択範囲: ' + selection);
  if (table) {
    lines.push('表構造: 見出し ' + (table.header_row || 1) + '行目・' + (table.first_col || 'A') + '〜' + (table.last_col || '?') + '列・明細 ' + (table.data || '') + '行' + (table.total_row ? '・合計行 ' + table.total_row : ''));
    if (Array.isArray(table.columns) && table.columns.length) {
      lines.push('列: ' + table.columns.map(function (c) { return (c.col || '') + '=' + (c.name || '') + (c.number ? '(数値)' : ''); }).join('、'));
    }
  }
  if (isEdit && targetName) {
    lines.push('\n【修正対象の既存関数名】\n' + targetName);
    if (existingCode) lines.push('【現在のコード（これを要望どおりに書き換えること）】\n' + existingCode);
  } else {
    if (Array.isArray(existingNames) && existingNames.length) {
      lines.push('【既存のマイマクロ名（重複禁止）】\n' + existingNames.slice(0, 60).join('、'));
    }
    if (existingCode) {
      lines.push('\n【現在表示中の下書きコード（これを要望どおりに修正すること）】\n' + existingCode);
    }
  }
  if (Array.isArray(history) && history.length) {
    lines.push('\n【これまでの会話】');
    history.slice(-10).forEach(function (h) {
      if (!h || !h.text) return;
      lines.push((h.role === 'ai' ? 'AI: ' : 'ユーザー: ') + String(h.text));
    });
  }
  var shelfSummary = comboBuildCompactShelfSummary_(String(prompt || ''), 12);
  if (shelfSummary) {
    lines.push('\n【shelf() から呼び出せる既存の棚カタログ（まとめ棚用）】\n' + shelfSummary);
  }
  lines.push('\n【ユーザーの指示】\n' + String(prompt || ''));
  lines.push(
    canChat
      ? '\n質問・相談・改修案の提案なら {"action":"reply","message":"..."}、コード作成・修正の依頼や合意なら {"action":"mymacro","code":"...","note":"変更内容の1行説明"} の JSON 1個だけを返してください。'
      : '\n必ず {"action":"mymacro","code":"...","note":"..."} の JSON 1個だけを返してください。'
  );
  return { system: sys, user: lines.join('\n') };
}

/** AI 応答テキストからマイマクロのコードとメモ（または reply）を取り出す。 */
function comboExtractMyMacroCode_(rawText) {
  var raw = String(rawText || '').trim();
  try {
    var parsed = JSON.parse(comboStripJsonFence_(raw));
    if (parsed && typeof parsed === 'object') {
      if (parsed.code) {
        return { action: 'mymacro', code: quickStripCodeFence_(parsed.code), note: String(parsed.note || '').trim() };
      }
      if (parsed.action === 'reply' && parsed.message) {
        var msgStr = String(parsed.message).trim();
        var fullFenceMatch = msgStr.match(/^```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/i);
        if (fullFenceMatch && /(?:async\s+)?function\s+/.test(fullFenceMatch[1])) {
          return { action: 'mymacro', code: fullFenceMatch[1].trim(), note: '' };
        }
        return { action: 'reply', message: msgStr };
      }
    }
  } catch (eJson) {}
  var stripped = quickStripCodeFence_(raw);
  if (/(?:^|\n)\s*(?:async\s+)?function\s+[^\s(]+\s*\(/.test(stripped) ||
      /(?:^|\n)\s*(?:const|let|var)\s+[^\s=]+\s*=\s*(?:async\s+)?(?:function\s*\(|\([^)]*\)\s*=>)/.test(stripped)) {
    return { action: 'mymacro', code: stripped, note: '' };
  }
  return { action: 'reply', message: raw || 'AI の返答が空でした' };
}

/** Gemini API / Claude API を直接呼んでマイマクロコードを生成・修正する。 */
function comboCallAiMyMacro_(cfg, prompts) {
  var apiKey = comboResolveApiKey_(cfg);
  if (!apiKey) throw new Error('APIキーが設定されていません（「設定」タブでキーを登録してください）');
  var rawText = '';

  if (cfg.aiMode === 'api_gemini') {
    var gModel = comboResolveLatestApiModel_('api_gemini', cfg.aiModel, apiKey);
    var gUrl = 'https://generativelanguage.googleapis.com/v1beta/models/' + encodeURIComponent(gModel) + ':generateContent?key=' + encodeURIComponent(apiKey);
    var gResp = UrlFetchApp.fetch(gUrl, {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      payload: JSON.stringify({
        systemInstruction: { parts: [{ text: prompts.system }] },
        contents: [{ role: 'user', parts: [{ text: prompts.user }] }],
        generationConfig: { temperature: 0.2, responseMimeType: 'application/json' }
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
    var cModel = comboResolveLatestApiModel_('api_claude', cfg.aiModel, apiKey);
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
        max_tokens: 2048,
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
  return comboExtractMyMacroCode_(rawText);
}

/** AI が返したマイマクロコードの構文・関数定義・重複を検証する。 */
function comboValidateAiMyMacroCode_(mode, code, existingNames) {
  var cleanCode = quickStripCodeFence_(code).replace(/\r\n/g, '\n').replace(/\s*$/, '');
  if (!cleanCode) {
    return { ok: false, retryable: true, error: 'AI が空のコードを返しました' };
  }
  try {
    new Function(cleanCode);
  } catch (eSyn) {
    return { ok: false, retryable: true, code: cleanCode, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsedFns = quickParseFns_(cleanCode);
  if (!parsedFns.length) {
    return { ok: false, retryable: true, code: cleanCode, error: 'インデントなしの関数定義（function 名前() { ... }、末尾 _ なし）が見つかりません' };
  }
  if (mode !== 'edit' && Array.isArray(existingNames) && existingNames.length) {
    var nameSet = {};
    existingNames.forEach(function (n) { nameSet[String(n || '')] = true; });
    for (var i = 0; i < parsedFns.length; i++) {
      if (nameSet[parsedFns[i].name]) {
        return {
          ok: false,
          retryable: true,
          code: cleanCode,
          error: '同じ名前のマイマクロ「' + parsedFns[i].name + '」が既にあります。別の関数名にしてください'
        };
      }
    }
  }
  return {
    ok: true,
    code: cleanCode,
    name: parsedFns[0].name,
    names: parsedFns.map(function (f) { return f.name; })
  };
}

/** AI が返したマイマクロコードを検証し、マイマクロへ自動保存する。 */
function comboSaveAiMyMacroResult_(mode, targetName, code, myId) {
  var valRes = comboValidateAiMyMacroCode_(mode, code, []);
  if (!valRes.ok) {
    return valRes;
  }
  var cleanCode = valRes.code;
  var saveRes = (mode === 'edit' && targetName)
    ? comboQuickSaveFn({ name: targetName, code: cleanCode, myId: myId || '' })
    : comboQuickAddFn({ code: cleanCode });
  if (saveRes && saveRes.ok) {
    saveRes.code = cleanCode;
    return saveRes;
  }
  var errMsg = String((saveRes && saveRes.error) || 'マイマクロを保存できませんでした');
  if (/(?:drive\.scripts|insufficient|permission|(?:許可|権限)がありません|403)/i.test(errMsg)) {
    return { ok: false, needsClientSave: true, code: cleanCode, error: errMsg };
  }
  var out = { ok: false, code: cleanCode, error: errMsg };
  if (/同じ名前|構文エラー|関数定義/.test(errMsg)) out.retryable = true;
  return out;
}

/** AI へ自然文を投げてマイマクロを作成・修正し、確認なしで自動保存する（postbox / Gemini / Claude 全対応）。 */
function comboQuickAiSave(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var mode = req.mode === 'edit' ? 'edit' : 'add';
    var prompt = String(req.prompt || '').trim();
    if (!prompt) {
      return { ok: false, error: 'AI に作ってほしい作業・直したい内容を入力してください', gasMs: Date.now() - t0 };
    }
    var targetName = String(req.name || '').trim();
    if (mode === 'edit' && !targetName) {
      return { ok: false, error: '修正対象のマイマクロ名が指定されていません', gasMs: Date.now() - t0 };
    }

    var ss = comboOpenSs_(req);
    var ssId = ss.getId();
    var ssName = ss.getName();
    var selInfo = comboGetSelectionInfo_(ss, req, true);
    var curSheet = selInfo.sheet || '';
    var sheets = (Array.isArray(req.sheets) && req.sheets.length)
      ? req.sheets
      : ss.getSheets().map(function (s) { return s.getName(); });
    var table = req.table || null;
    if (!table && curSheet) {
      try {
        var cachedTbl = comboCacheGet_(ssId, curSheet);
        if (cachedTbl && cachedTbl.table) table = cachedTbl.table;
        else {
          var tbObj = findTable_(sheetOf_(ss, curSheet, ''));
          if (tbObj) table = tableOut_(tbObj);
        }
      } catch (eTbl) {}
    }

    var effMyId = String(req.myId || '').trim();
    var existingNames = [];
    try {
      if (!effMyId) effMyId = quickMyFind_(false) || '';
      if (effMyId) {
        existingNames = quickMyListCached_(effMyId, req.myStamp ? String(req.myStamp) : undefined).map(function (f) { return f.name; });
      }
    } catch (eList) {}

    var existingCode = String(req.code || '').trim();
    if (mode === 'edit' && !existingCode && effMyId) {
      var got = comboQuickGetFn({ name: targetName, myId: effMyId, myStamp: req.myStamp || '' });
      if (got && got.ok && got.code) existingCode = String(got.code);
    }

    var cfg = comboGetRawConfig_();
    var effMode = cfg.aiMode || 'postbox';
    var previewOnly = !!req.previewOnly;
    var history = Array.isArray(req.history)
      ? req.history.slice(-10).map(function (h) {
          return {
            role: (h && h.role === 'ai') ? 'ai' : 'user',
            text: String((h && h.text) || '').trim().slice(0, 600)
          };
        }).filter(function (h) { return !!h.text; })
      : [];

    if (effMode === 'postbox') {
      var reqId = comboPostboxEnqueue_({
        kind: 'mymacro',
        mode: mode,
        previewOnly: previewOnly,
        targetName: targetName,
        existingCode: existingCode,
        existingNames: existingNames,
        history: history,
        ask: prompt,
        ssId: ssId,
        ssName: ssName,
        sheet: curSheet,
        selection: selInfo.selection || req.selection || '',
        table: table,
        sheets: sheets,
        aiModel: cfg.aiModel || 'sonnet',
        myId: effMyId
      });
      return {
        ok: true,
        pendingPostbox: true,
        previewOnly: previewOnly,
        reqId: reqId,
        kind: 'mymacro',
        mode: mode,
        name: targetName,
        text: previewOnly
          ? ('✨ AI（郵便受け）にマイマクロの' + (mode === 'edit' ? '修正案・相談' : 'コード作成') + 'を依頼しました…')
          : ('✨ AI（郵便受け）にマイマクロの' + (mode === 'edit' ? '修正' : '作成') + 'を依頼しました…'),
        gasMs: Date.now() - t0
      };
    }

    var prompts = comboBuildAiMyMacroPrompts_(mode, prompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, previewOnly);
    var aiRes = comboCallAiMyMacro_(cfg, prompts);
    if (aiRes.action === 'reply') {
      if (previewOnly) {
        var repMsg = String(aiRes.message || '').trim() || 'ご希望の編集内容を教えてください。';
        return {
          ok: true,
          action: 'reply',
          previewOnly: true,
          saved: false,
          mode: mode,
          name: targetName,
          message: repMsg,
          text: repMsg,
          gasMs: Date.now() - t0
        };
      }
      return { ok: false, error: aiRes.message || 'コードを生成できませんでした', gasMs: Date.now() - t0 };
    }
    if (previewOnly) {
      var valRes = comboValidateAiMyMacroCode_(mode, aiRes.code, existingNames);
      if (!valRes.ok && valRes.retryable) {
        var pvRetryPrompt = prompt + '\n\n【前回の出力は次のエラーで検証できませんでした。必ず修正して出し直してください】\n' +
          valRes.error + '\n前回の生成コード:\n' + String(aiRes.code || '').slice(0, 1200);
        var pvRetryPrompts = comboBuildAiMyMacroPrompts_(mode, pvRetryPrompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, false);
        aiRes = comboCallAiMyMacro_(cfg, pvRetryPrompts);
        if (aiRes.action === 'reply') {
          return { ok: false, error: aiRes.message || '再試行でもコードを生成できませんでした', gasMs: Date.now() - t0 };
        }
        valRes = comboValidateAiMyMacroCode_(mode, aiRes.code, existingNames);
      }
      if (!valRes.ok) {
        return { ok: false, code: valRes.code || aiRes.code || '', error: valRes.error || 'コードを検証できませんでした', gasMs: Date.now() - t0 };
      }
      var pvName = valRes.name || targetName || 'マイマクロ';
      var pvNote = String(aiRes.note || '').trim();
      return {
        ok: true,
        action: 'mymacro',
        previewOnly: true,
        saved: false,
        mode: mode,
        name: pvName,
        newName: pvName,
        code: valRes.code,
        prevCode: existingCode,
        note: pvNote,
        text: '✨ コード案を作成しました（' + pvName + '）。内容を確認して「決定して保存」を押してください' + (pvNote ? '（' + pvNote + '）' : ''),
        gasMs: Date.now() - t0
      };
    }
    var saveRes = comboSaveAiMyMacroResult_(mode, targetName, aiRes.code, effMyId);
    if (!saveRes.ok && saveRes.retryable) {
      var retryPrompt = prompt + '\n\n【前回の出力は次のエラーで保存できませんでした。必ず修正して出し直してください】\n' +
        saveRes.error + '\n前回の生成コード:\n' + String(aiRes.code || '').slice(0, 1200);
      var retryPrompts = comboBuildAiMyMacroPrompts_(mode, retryPrompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, false);
      aiRes = comboCallAiMyMacro_(cfg, retryPrompts);
      if (aiRes.action === 'reply') {
        return { ok: false, error: aiRes.message || '再試行でもコードを生成できませんでした', gasMs: Date.now() - t0 };
      }
      saveRes = comboSaveAiMyMacroResult_(mode, targetName, aiRes.code, effMyId);
    }
    if (!saveRes.ok) {
      return { ok: false, code: saveRes.code || aiRes.code || '', error: saveRes.error || '保存できませんでした', gasMs: Date.now() - t0 };
    }
    var savedName = saveRes.newName || saveRes.name || (saveRes.names && saveRes.names[0]) || targetName || 'マイマクロ';
    var note = String(aiRes.note || '').trim();
    return {
      ok: true,
      mode: mode,
      name: savedName,
      newName: savedName,
      myId: saveRes.myId || effMyId,
      myUrl: saveRes.myUrl || '',
      myStamp: saveRes.myStamp || '',
      prevCode: existingCode,
      note: note,
      text: '✨ AI でマイマクロ「' + savedName + '」を' + (mode === 'edit' ? '修正' : '作成') + 'して自動保存しました' + (note ? '（' + note + '）' : ''),
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

/** 万能の窓口：許可された combo* 関数だけを安全に呼び出す。 */
function comboCall(name, req) {
  var fnName = String(name || '').trim();
  if (!/^combo[A-Z]\w*$/.test(fnName) || fnName === 'comboCall') {
    return { ok: false, error: '呼び出せない関数です: ' + fnName };
  }
  var f = globalThis[fnName];
  if (typeof f !== 'function') {
    return { ok: false, error: '大元に関数が見つかりません: ' + fnName };
  }
  return f(req);
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
  EXTRA_ACTIONS.combo_call = comboCall;
  EXTRA_ACTIONS.combo_quick_list = comboQuickList;
  EXTRA_ACTIONS.combo_quick_run = comboQuickRun;
  EXTRA_ACTIONS.combo_quick_make = comboQuickMake;
  EXTRA_ACTIONS.combo_quick_get_fn = comboQuickGetFn;
  EXTRA_ACTIONS.combo_quick_save_fn = comboQuickSaveFn;
  EXTRA_ACTIONS.combo_quick_add_fn = comboQuickAddFn;
  EXTRA_ACTIONS.combo_quick_delete_fn = comboQuickDeleteFn;
  EXTRA_ACTIONS.combo_quick_save_order = comboQuickSaveOrder;
  EXTRA_ACTIONS.combo_quick_save_pins = comboQuickSavePins;
  EXTRA_ACTIONS.combo_quick_save_steps = comboQuickSaveSteps;
  EXTRA_ACTIONS.combo_quick_ai_save = comboQuickAiSave;
  EXTRA_ACTIONS.combo_set_target = function (req) {
    return comboSetTestTarget((req && (req.targetId || req.ssId)) || '');
  };
}
