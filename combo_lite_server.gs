/**
 * GASコンボ 超軽量・高速サーバー（スプレッドシート内完結・外部ライブラリ通信ゼロ版）
 */
var COMBO_PROP_CONFIG = 'COMBO_CONFIG';
var COMBO_CACHE_TBL = 'COMBO_LITE_TBL_';
var COMBO_CACHE_UNDO = 'COMBO_LITE_UNDO';

var STYLE = {
  headBg: '#1F4E79', headFg: '#FFFFFF', border: '#9E9E9E', totalBg: '#F2F2F2',
  numFmt: '#,##0', dateFmt: 'yyyy/mm/dd', colMin: 50, colMax: 360, px: 7, pad: 18
};

function onOpen(e) {
  try {
    SpreadsheetApp.getUi()
      .createMenu('⚡ GASコンボ')
      .addItem('操作窓（サイドバー）を開く', 'showGasComboSidebar')
      .addItem('直前を取り消す', 'comboMenuUndo')
      .addToUi();
  } catch (err) {}
}

function showGasComboSidebar() {
  var html = HtmlService.createHtmlOutputFromFile('ComboSidebar')
    .setTitle('GASコンボ')
    .setWidth(300);
  SpreadsheetApp.getUi().showSidebar(html);
}

function comboMenuUndo() {
  var res = comboUndo({});
  try {
    SpreadsheetApp.getActiveSpreadsheet().toast(
      res.ok ? ('取り消しました: ' + (res.what || '')) : (res.error || '取り消せませんでした'),
      'GASコンボ', 4
    );
  } catch (e) {}
  return res;
}

function colLetter_(n) {
  var s = '';
  while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function colNum_(s) {
  s = String(s || '').trim().toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
  return n;
}

function rgb_(s) {
  if (s === undefined || s === null || s === '') return null;
  var str = String(s).trim();
  if (str === 'なし' || /^(none|transparent|clear)$/i.test(str)) return null;
  if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(str)) {
    return str.length === 4 ? ('#' + str[1] + str[1] + str[2] + str[2] + str[3] + str[3]).toUpperCase() : str.toUpperCase();
  }
  var map = {
    '黒': '#000000', 'black': '#000000', '白': '#FFFFFF', 'white': '#FFFFFF',
    '赤': '#FF0000', 'red': '#FF0000', '青': '#0000FF', 'blue': '#0000FF',
    '緑': '#008000', 'green': '#008000', '黄': '#FFFF00', 'yellow': '#FFFF00',
    '橙': '#FFA500', 'オレンジ': '#FFA500', 'orange': '#FFA500',
    '紫': '#800080', 'purple': '#800080', '桃': '#FFC0CB', 'ピンク': '#FFC0CB', 'pink': '#FFC0CB',
    '灰': '#808080', '灰色': '#808080', 'グレー': '#808080', 'gray': '#808080', 'grey': '#808080',
    '水色': '#00FFFF', 'シアン': '#00FFFF', 'cyan': '#00FFFF', 'lightblue': '#ADD8E6',
    '紺': '#000080', 'ネイビー': '#000080', 'navy': '#000080', '茶': '#8B4513', '茶色': '#8B4513', 'brown': '#8B4513',
    '薄赤': '#FCE4D6', '薄青': '#D9E1F2', '薄緑': '#E2EFDA', '薄黄': '#FFF2CC', '薄灰': '#F2F2F2',
    '薄灰色': '#F2F2F2', '薄グレー': '#F2F2F2', '薄橙': '#FCE5CD', '薄紫': '#EAD1DC',
    'lightred': '#FCE4D6', 'lightgreen': '#E2EFDA', 'lightyellow': '#FFF2CC', 'lightgray': '#F2F2F2'
  };
  var k = str.toLowerCase();
  if (map[k]) return map[k];
  if (map[str]) return map[str];
  var norm = str.replace(/^薄い/, '薄').replace(/色$/, '');
  return map[norm] || map[str.replace(/^薄い/, '薄')] || str;
}

function isBlank_(v) { return v === '' || v === null || v === undefined; }

function findTable_(sh) {
  var vals = sh.getDataRange().getValues();
  var lr = vals.length, lc = vals[0] ? vals[0].length : 0;
  if (lr < 1 || lc < 1) return null;
  var nonEmpty = function (row) { return row.filter(function (v) { return !isBlank_(v); }).length; };
  var h = -1;
  for (var r = 0; r < lr; r++) { if (nonEmpty(vals[r]) >= 2) { h = r; break; } }
  // 見出しの行：2 つ以上埋まった最初の行。ただしすぐ下の行がその倍以上埋まっていれば、その行は表の前の欄（「表示部門 | すべて」等の選ぶ欄）として下へ送る
  for (var hs = 0; h >= 0 && hs < 10; hs++) {
    var nx = h + 1; while (nx < vals.length && nonEmpty(vals[nx]) === 0) nx++;
    if (nx < vals.length && nonEmpty(vals[nx]) >= 2 * nonEmpty(vals[h])) h = nx; else break;
  }
  if (h < 0) return null;
  var hdr = vals[h], fc = -1, lcol = -1;
  for (var c = 0; c < hdr.length; c++) if (!isBlank_(hdr[c])) { if (fc < 0) fc = c; lcol = c; }
  var last = h;
  for (var r2 = h + 1; r2 < lr; r2++) {
    if (nonEmpty(vals[r2].slice(fc, lcol + 1)) > 0) last = r2;
  }
  var t = { sheet: sh, headerRow: h + 1, firstCol: fc + 1, lastCol: lcol + 1, firstData: h + 2, lastData: last + 1, totalRow: 0, vals: vals };
  // 合計行・末尾集計ブロック：最終行から上に向かって連続する 合計/小計/消費税 等を明細から除外する（workspace_engine.gs findTable_ と同じ型）
  var footerRe = /^(合計|総計|小計|税込合計|税抜合計|消費税|外税|内税|税額|値引き?|割引|計|平均|最大値?|最小値?|件数|total|subtotal|tax|sum)/i;
  for (var footerEnd = last; footerEnd >= h + 2; footerEnd--) {
    var first = '';
    for (var fcx = fc; fcx <= lcol; fcx++) { if (!isBlank_(vals[footerEnd][fcx])) { first = String(vals[footerEnd][fcx]); break; } }
    if (!footerRe.test(first.trim())) break;
    if (!t.totalRow) t.totalRow = footerEnd + 1;
    t.lastData = footerEnd;
  }
  var titleA1 = 'A1';
  for (var tr = 0; tr < h; tr++) {
    for (var tc = 0; tc < vals[tr].length; tc++) {
      if (!isBlank_(vals[tr][tc])) { titleA1 = colLetter_(tc + 1) + (tr + 1); tr = h; break; }
    }
  }
  t.titleA1 = titleA1;
  return t;
}

function tableOut_(tb) {
  var cols = [];
  for (var c = tb.firstCol; c <= tb.lastCol; c++) {
    var h = String(tb.vals[tb.headerRow - 1][c - 1] || '');
    var n = 0, tot = 0;
    for (var r = tb.firstData; r <= tb.lastData; r++) {
      var v = tb.vals[r - 1][c - 1];
      if (!isBlank_(v)) { tot++; if (typeof v === 'number') n++; }
    }
    cols.push({ col: colLetter_(c), name: h, number: tot > 0 && n / tot > 0.5 });
  }
  return {
    header_row: tb.headerRow,
    first_col: colLetter_(tb.firstCol),
    last_col: colLetter_(tb.lastCol),
    data: tb.firstData + '-' + tb.lastData,
    total_row: tb.totalRow || null,
    title_a1: tb.titleA1 || 'A1',
    columns: cols
  };
}

function openSs_(req) {
  var active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) return active;
  var id = (req && (req.targetId || (req.target && req.target.id))) || PropertiesService.getScriptProperties().getProperty('COMBO_TARGET_SS_ID');
  return id ? SpreadsheetApp.openById(id) : null;
}

function comboInit(req) {
  var t0 = Date.now();
  try {
    var ss = openSs_(req);
    var sh = (req && req.sheet && ss.getSheetByName(req.sheet)) || ss.getActiveSheet() || ss.getSheets()[0];
    var sel = '';
    try { var rg = sh.getActiveRange(); if (rg) sel = rg.getA1Notation(); } catch (e) {}
    var sheetInfos = ss.getSheets().map(function (s) { return { name: s.getName(), rows: s.getLastRow(), cols: s.getLastColumn() }; });
    var sheets = sheetInfos.map(function (s) { return s.name; });
    var tb = findTable_(sh);
    var table = tb ? tableOut_(tb) : null;
    var ssId = ss.getId(), ssName = ss.getName();
    return {
      ok: true,
      target: { id: ssId, name: ssName, kind: 'sheet', url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit', sheet: sh.getName() },
      sheets: sheets,
      sheetInfos: sheetInfos,
      table: table,
      selection: sel,
      config: comboGetConfig(),
      gasMs: Date.now() - t0
    };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err), gasMs: Date.now() - t0 };
  }
}

function comboLook(req) {
  var res = comboInit(req);
  if (!res.ok) return res;
  var lines = [
    '対象: ' + res.target.name + ' › ' + res.target.sheet,
    'シート: ' + (res.sheetInfos || []).map(function (s) { return s.name + '（' + s.rows + '行×' + s.cols + '列）'; }).join('、')
  ];
  if (res.table) {
    lines.push('表: 見出し ' + res.table.header_row + ' 行目・' + res.table.first_col + '〜' + res.table.last_col + ' 列・明細 ' + res.table.data + ' 行目');
    lines.push('列: ' + res.table.columns.map(function (c) { return c.col + '=' + c.name; }).join('、'));
  }
  res.text = lines.join('\n');
  return res;
}

function resolveColIndex_(table, colSpec) {
  if (!colSpec) return 1;
  var s = String(colSpec).trim();
  if (table && table.columns) {
    for (var i = 0; i < table.columns.length; i++) {
      if (table.columns[i].name === s || table.columns[i].col === s.toUpperCase()) return colNum_(table.columns[i].col);
    }
  }
  if (/^[A-Za-z]{1,3}$/.test(s)) return colNum_(s);
  return 1;
}

function execSingleOp_(sh, op, table, changed, notes) {
  var name = op.shelf;
  if (name === 'format') {
    var a1 = op.range;
    if (!a1) {
      if (op.title) a1 = (table && table.title_a1) || 'A1';
      else if (op.header && table) a1 = table.first_col + table.header_row + ':' + table.last_col + table.header_row;
      else if (op.col && table) {
        var ci = resolveColIndex_(table, op.col), cl = colLetter_(ci);
        var sp = String(table.data || '2-10').split('-');
        a1 = cl + sp[0] + ':' + cl + (table.total_row || sp[1] || sp[0]);
      } else {
        var act = sh.getActiveRange();
        a1 = act ? act.getA1Notation() : 'A1';
      }
    }
    var rg = sh.getRange(a1), did = [];
    if (op.color !== undefined) { rg.setFontColor(rgb_(op.color)); did.push('color'); }
    if (op.bg !== undefined) { rg.setBackground(rgb_(op.bg)); did.push('bg'); }
    if (op.bold !== undefined) { rg.setFontWeight(op.bold ? 'bold' : 'normal'); did.push('bold'); }
    if (op.italic !== undefined) { rg.setFontStyle(op.italic ? 'italic' : 'normal'); did.push('italic'); }
    if (op.size !== undefined) { rg.setFontSize(Number(op.size)); did.push('size'); }
    if (op.font !== undefined) { rg.setFontFamily(String(op.font)); did.push('font'); }
    if (op.number_format !== undefined) { rg.setNumberFormat(String(op.number_format)); did.push('number_format'); }
    if (op.align !== undefined) { rg.setHorizontalAlignment(String(op.align)); did.push('align'); }
    if (op.valign !== undefined) { rg.setVerticalAlignment(String(op.valign)); did.push('valign'); }
    if (op.wrap !== undefined) { rg.setWrap(!!op.wrap); did.push('wrap'); }
    if (op.borders !== undefined) {
      if (op.borders && op.borders !== 'none') rg.setBorder(true, true, true, true, op.borders !== 'outer', op.borders !== 'outer', STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
      else rg.setBorder(false, false, false, false, false, false);
      did.push('borders');
    }
    if (op.merge !== undefined) { if (op.merge) rg.merge(); else rg.breakApart(); did.push('merge'); }
    changed.push(sh.getName() + '!' + a1 + ' ' + did.join('・'));
    return;
  }
  if (name === 'freeze') {
    var rows = op.rows !== undefined ? Number(op.rows) : ((table && table.header_row) || 1);
    sh.setFrozenRows(rows);
    if (op.cols !== undefined) sh.setFrozenColumns(Number(op.cols));
    changed.push(sh.getName() + '! ' + rows + '行目を固定');
    return;
  }
  if (name === 'unfreeze') {
    sh.setFrozenRows(0); sh.setFrozenColumns(0);
    changed.push(sh.getName() + '! 固定を解除');
    return;
  }
  if (name === 'width') {
    var didW = [];
    if (op.col && op.width) {
      sh.setColumnWidth(resolveColIndex_(table, op.col), Number(op.width));
      didW.push(op.col + '列');
    }
    (op.auto || []).forEach(function (k) {
      var ci2 = resolveColIndex_(table, k);
      sh.autoResizeColumn(ci2);
      didW.push(k + '列(自動)');
    });
    changed.push(sh.getName() + '! ' + didW.join('・') + ' 幅を変更');
    return;
  }
  if (name === 'filter.on') {
    var f0 = sh.getFilter(); if (f0) f0.remove();
    var frg = op.range ? sh.getRange(op.range) : (table ? sh.getRange(table.header_row, colNum_(table.first_col), (Number(String(table.data).split('-')[1]) - table.header_row + 1), colNum_(table.last_col) - colNum_(table.first_col) + 1) : sh.getDataRange());
    frg.createFilter();
    changed.push(sh.getName() + '!' + frg.getA1Notation() + ' フィルタON');
    return;
  }
  if (name === 'filter.off') {
    var f1 = sh.getFilter(); if (f1) f1.remove();
    changed.push(sh.getName() + '! フィルタOFF');
    return;
  }
  if (name === 'write') {
    if (op.cells && typeof op.cells === 'object') {
      var ks = Object.keys(op.cells);
      ks.forEach(function (a1k) { sh.getRange(a1k).setValue(op.cells[a1k]); });
      changed.push(sh.getName() + '!' + ks.join('・') + ' 値を書き込み');
    }
    return;
  }
  if (name === 'banding.add') {
    var brg = op.range ? sh.getRange(op.range) : sh.getDataRange();
    brg.getBandings().forEach(function (b) { b.remove(); });
    brg.applyRowBanding(SpreadsheetApp.BandingTheme.BLUE, true, false);
    changed.push(sh.getName() + '!' + brg.getA1Notation() + ' 交互の色');
    return;
  }
  if (name === 'banding.remove') {
    sh.getDataRange().getBandings().forEach(function (b) { b.remove(); });
    changed.push(sh.getName() + '! 交互の色を解除');
    return;
  }
  if (name === 'seiri' || name === 'tidy') {
    var tb2 = findTable_(sh);
    if (tb2) {
      var hRg = sh.getRange(tb2.headerRow, tb2.firstCol, 1, tb2.lastCol - tb2.firstCol + 1);
      hRg.setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
      var allRg = sh.getRange(tb2.headerRow, tb2.firstCol, (tb2.totalRow || tb2.lastData) - tb2.headerRow + 1, tb2.lastCol - tb2.firstCol + 1);
      allRg.setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
      changed.push(sh.getName() + '!' + allRg.getA1Notation() + ' 表を整形');
    }
    return;
  }
}

function comboRunOps(req) {
  var t0 = Date.now();
  try {
    req = req || {};
    var ops = typeof req.ops === 'string' ? JSON.parse(req.ops) : (req.ops || []);
    if (!Array.isArray(ops)) ops = [ops];
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sh = (req.sheet && ss.getSheetByName(req.sheet)) || ss.getActiveSheet();
    var table = req.table || null;
    var changed = [], notes = [];
    for (var i = 0; i < ops.length; i++) {
      execSingleOp_(sh, ops[i], table, changed, notes);
    }
    var gasMs = Date.now() - t0;
    var shName = sh.getName();
    var ssName = req.targetName || 'スプレッドシート';
    var text = '対象: ' + ssName + ' › ' + shName + '\n直した所: ' + (changed.join(' ／ ') || 'なし');
    return {
      ok: true,
      target: { id: req.targetId || '', name: ssName, kind: 'sheet', sheet: shName },
      changed: changed,
      notes: notes,
      table: table,
      sheets: req.sheets || [shName],
      text: text,
      gasMs: gasMs
    };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err), text: 'エラー: ' + String(err && err.message || err), gasMs: Date.now() - t0 };
  }
}

function comboRunAsk(req) {
  var t0 = Date.now();
  req = req || {};
  if (Array.isArray(req.ops) && req.ops.length) {
    var res = comboRunOps(req);
    if (res.ok) {
      var shortStr = req.ops.map(function (o) {
        var a = Object.keys(o).filter(function (k) { return k !== 'shelf'; }).map(function (k) { return k + '=' + JSON.stringify(o[k]); }).join(', ');
        return o.shelf + '(' + a + ')';
      }).join(', ');
      res.text = '[棚ヒット] ' + shortStr + '\n' + res.text;
    }
    res.gasMs = Date.now() - t0;
    return res;
  }
  return { ok: false, error: 'サイドバー側で棚が確定しませんでした', text: '棚に該当しませんでした', gasMs: Date.now() - t0 };
}

function comboFind(req) { return { ok: true, text: 'サイドバー内で検索できます', gasMs: 1 }; }
function comboUndo(req) { return { ok: false, error: 'Ctrl+Z で戻せます', text: 'シート上で Ctrl+Z を押すと直前の変更を戻せます', gasMs: 1 }; }
function comboGetConfig() { return { aiMode: 'postbox', aiModel: 'haiku', backupDefault: false, hasApiKey: false }; }
function comboSaveConfig(cfg) { return { ok: true, config: cfg }; }
function comboPollSelection(req) {
  var sh = SpreadsheetApp.getActiveSheet();
  var rg = sh ? sh.getActiveRange() : null;
  return { ok: true, sheet: sh ? sh.getName() : '', selection: rg ? rg.getA1Notation() : '', gasMs: 1 };
}
