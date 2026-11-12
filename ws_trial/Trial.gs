// Trial.gs - 試験用のエンジン（shu-workspace-engine-test）だけに入れる入口。本番のエンジンには入れない・公開しない。
// 共通部・Catalog・棚のファイルのあとに置く（EXTRA_ACTIONS に名前で登録する）。棚の関数は使わない（試される物で試験の土台を作らない）。
// 効くのは「試験場」（設定に登録した ID・名前が WS試験_ で始まる）のファイルだけ。ほかの ID は断る。

var TRIAL_PREFIX = 'WS試験_';
BK_BOOK_NAME = TRIAL_PREFIX + '控え';          // 控えのブックも試験用（本番の控えと別。名前で見分ける）
BK_DOC_PREFIX = TRIAL_PREFIX + '文書控え_';

function trialCfg_() { return getJson_('TRIAL_CFG', { ids: [], docs: [] }); }

// 試験場のスプレッドシートを開く。登録されていない ID・名前が WS試験_ で始まらないファイルは断る
function trialOpen_(id) {
  var cfg = trialCfg_();
  if (!id || cfg.ids.indexOf(id) < 0) throw new ArgError('試験場のファイルではありません（登録されていない ID）: ' + id);
  var ss = SpreadsheetApp.openById(id);
  if (String(ss.getName()).indexOf(TRIAL_PREFIX) !== 0) throw new ArgError('試験場のファイルではありません（名前が ' + TRIAL_PREFIX + ' で始まらない）: ' + ss.getName());
  return ss;
}

// ---------------------------------------------------------------- 純粋な部品（node でも試験する）

function trialHex_(c, dflt) {
  if (!c) return dflt;
  var h = function (v) { var n = Math.round((v || 0) * 255); return ('0' + n.toString(16)).slice(-2); };
  return '#' + h(c.red) + h(c.green) + h(c.blue);
}

// 道具が渡す 1 セル（数・文字・{"f":式}・{"s":文字のまま}・{"d":日付}・null）を、シートに書く値と数の書式に直す
function trialCell_(c) {
  if (c === null || c === undefined) return { v: '', nf: '' };
  if (typeof c === 'number' || typeof c === 'boolean') return { v: c, nf: '' };
  if (typeof c === 'string') return { v: c, nf: '' };
  if (c.f !== undefined) return { v: c.f, nf: '' };
  if (c.s !== undefined) return { v: String(c.s), nf: '@' };
  if (c.d !== undefined) { var p = String(c.d).split('-'); return { v: new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10)), nf: 'yyyy-mm-dd' }; }
  return { v: String(c), nf: '' };
}

// 流し込んだ後の型の確かめ: 期待（道具が渡した 1 セル）と、読み戻した値・式を比べる。違えば理由の文字を返す（同じなら ''）
function trialCheckCell_(exp, got, gotFormula) {
  if (exp === null || exp === undefined) return got === '' ? '' : '空のはずが値がある';
  if (typeof exp === 'number') return typeof got === 'number' && got === exp ? '' : '数のはずが ' + typeof got + '（' + got + '）';
  if (typeof exp === 'boolean') return got === exp ? '' : '真偽のはずが違う';
  if (typeof exp === 'string') return (typeof got === 'string' && got === exp) ? '' : '文字のはずが ' + typeof got + '（' + got + '）に化けた';
  if (exp.f !== undefined) return (gotFormula && gotFormula.charAt(0) === '=') ? '' : '式のはずが式でない';
  if (exp.s !== undefined) return (typeof got === 'string' && got === String(exp.s)) ? '' : '文字のままのはずが ' + typeof got + '（' + got + '）に化けた';
  if (exp.d !== undefined) { var p = String(exp.d).split('-'); var ok = Object.prototype.toString.call(got) === '[object Date]' && got.getFullYear() === parseInt(p[0], 10) && got.getMonth() === parseInt(p[1], 10) - 1 && got.getDate() === parseInt(p[2], 10); return ok ? '' : '日付のはずが ' + typeof got + 'に化けた'; }
  return '';
}

// Sheets API の 1 シート（spreadsheets.get の sheets[i]）を、道具が比べやすい形にする（疎: 値か書式のあるセルだけ）
function trialSnapSheet_(sh) {
  var P = sh.properties || {}, G = P.gridProperties || {};
  var out = { name: P.title, id: P.sheetId, index: P.index, hidden: !!P.hidden, rows: G.rowCount || 0, cols: G.columnCount || 0,
    frozen: { rows: G.frozenRowCount || 0, cols: G.frozenColumnCount || 0 }, merges: [], hidden_rows: [], filtered_rows: [], hidden_cols: [], widths: [], cells: {}, cf: (sh.conditionalFormats || []).length };
  (sh.merges || []).forEach(function (m) { out.merges.push(colLetter_((m.startColumnIndex || 0) + 1) + ((m.startRowIndex || 0) + 1) + ':' + colLetter_(m.endColumnIndex) + m.endRowIndex); });
  var d = (sh.data || [])[0] || {};
  (d.rowMetadata || []).forEach(function (r, i) { if (r.hiddenByUser) out.hidden_rows.push(i + 1); if (r.hiddenByFilter) out.filtered_rows.push(i + 1); });
  (d.columnMetadata || []).forEach(function (c, i) { if (c.hiddenByUser) out.hidden_cols.push(i + 1); out.widths.push(c.pixelSize || 0); });
  (d.rowData || []).forEach(function (row, r) {
    (row.values || []).forEach(function (cell, c) {
      var uv = cell.userEnteredValue || {}, ev = cell.effectiveValue || {}, uf = cell.userEnteredFormat || {}, ef = cell.effectiveFormat || {};
      var fv = cell.formattedValue === undefined ? '' : cell.formattedValue;
      var bd = false, b = ef.borders || {};
      ['top', 'bottom', 'left', 'right'].forEach(function (k) { if (b[k] && b[k].style && b[k].style !== 'NONE') bd = true; });
      var ubg = trialHex_((uf.backgroundColor), '#ffffff'), ebg = trialHex_(ef.backgroundColor, '#ffffff');
      var efg = trialHex_(ef.textFormat && ef.textFormat.foregroundColor, '#000000'), ufg = trialHex_(uf.textFormat && uf.textFormat.foregroundColor, '#000000');
      var ebold = !!(ef.textFormat && ef.textFormat.bold), ubold = !!(uf.textFormat && uf.textFormat.bold);
      var plain = fv === '' && ebg === '#ffffff' && !ebold && !bd && efg === '#000000';
      if (plain) return;
      var t = ev.numberValue !== undefined ? 'n' : ev.boolValue !== undefined ? 'b' : ev.errorValue ? 'e' : ev.stringValue !== undefined ? 's' : '';
      var cellOut = { v: fv, t: t, nf: (ef.numberFormat && ef.numberFormat.pattern) || '', e: { bg: ebg, fg: efg, b: ebold }, u: { bg: ubg, fg: ufg, b: ubold }, bd: bd };
      if (uv.formulaValue !== undefined) cellOut.f = uv.formulaValue;
      if (ev.numberValue !== undefined) cellOut.n = ev.numberValue;
      out.cells[colLetter_(c + 1) + (r + 1)] = cellOut;
    });
  });
  return out;
}

var TRIAL_SNAP_FIELDS = 'sheets(properties(sheetId,title,index,hidden,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)),merges,conditionalFormats(ranges),' +
  'data(rowMetadata(hiddenByUser,hiddenByFilter),columnMetadata(hiddenByUser,pixelSize),rowData(values(formattedValue,userEnteredValue,effectiveValue,' +
  'userEnteredFormat(backgroundColor,textFormat(bold,foregroundColor)),effectiveFormat(backgroundColor,textFormat(bold,foregroundColor),numberFormat,borders)))))';

// 今の状態を撮る（Sheets API の spreadsheets.get を 1 回）
function trialSnap_(ss) {
  var resp = Sheets.Spreadsheets.get(ss.getId(), { includeGridData: true, fields: TRIAL_SNAP_FIELDS });
  return { name: ss.getName(), sheets: (resp.sheets || []).map(trialSnapSheet_) };
}

// ---------------------------------------------------------------- 入口

EXTRA_ACTIONS['trial_config'] = function (req) {
  var ids = req.ids || [], docs = req.docs || [];
  var bad = [];
  ids.forEach(function (id) { try { var n = SpreadsheetApp.openById(id).getName(); if (String(n).indexOf(TRIAL_PREFIX) !== 0) bad.push(n); } catch (e) { bad.push(id); } });
  docs.forEach(function (id) { try { var n = DocumentApp.openById(id).getName(); if (String(n).indexOf(TRIAL_PREFIX) !== 0) bad.push(n); } catch (e) { bad.push(id); } });
  if (bad.length) return { ok: false, error: '試験場に登録できないファイルがあります（開けない・名前が ' + TRIAL_PREFIX + ' で始まらない）: ' + bad.join('、') };
  setJson_('TRIAL_CFG', { ids: ids, docs: docs });
  ids.forEach(function (id) { var s = SpreadsheetApp.openById(id); s.setSpreadsheetLocale('ja_JP'); s.setSpreadsheetTimeZone('Asia/Tokyo'); });   // 日本・東京で固定
  if (req.bk_book) props_().setProperty('BK_BOOK', req.bk_book);   // 控えのブック（フォルダに入れた物）を使う
  return { ok: true, ids: ids.length, docs: docs.length };
};

EXTRA_ACTIONS['trial_info'] = function (req) {
  var cfg = trialCfg_(), l = ledger_();
  return { ok: true, trial: true, ids: cfg.ids, docs: cfg.docs, bk_book: props_().getProperty('BK_BOOK') || '', ledger_items: l.items.length, ledger_seq: l.seq };
};

// 表の形を流し込む。今あるシートを全部捨てて作り直す。流し込んだ後に型を確かめ、化けたセルがあれば止まる
function trialSeed_(req) {
  var ss = trialOpen_(req.id);
  var sheets = req.sheets || [];
  if (!sheets.length) throw new ArgError('sheets が空です');
  var tmp = ss.insertSheet('__seed_tmp__' + Date.now());
  ss.getSheets().forEach(function (s) { if (s.getSheetId() !== tmp.getSheetId()) ss.deleteSheet(s); });
  ss.getNamedRanges().forEach(function (n) { n.remove(); });
  var problems = [];
  sheets.forEach(function (sd) {
    var sh = ss.insertSheet(sd.name);
    var grid = sd.grid || [], nr = grid.length, nc = 0;
    grid.forEach(function (r) { if (r.length > nc) nc = r.length; });
    if (nr > 0 && nc > 0) {
      if (sh.getMaxRows() < nr) sh.insertRowsAfter(sh.getMaxRows(), nr - sh.getMaxRows());
      if (sh.getMaxColumns() < nc) sh.insertColumnsAfter(sh.getMaxColumns(), nc - sh.getMaxColumns());
      var cells = grid.map(function (r) { var o = []; for (var c = 0; c < nc; c++) o.push(trialCell_(r[c])); return o; });
      var rg = sh.getRange(1, 1, nr, nc);
      var curNf = rg.getNumberFormats();   // 文字のまま・日付の所だけ書式を替える（そのほかは今の書式のまま）
      rg.setNumberFormats(cells.map(function (r, i) { return r.map(function (x, j) { return x.nf || curNf[i][j]; }); }));
      rg.setValues(cells.map(function (r) { return r.map(function (x) { return x.v; }); }));
    }
    (sd.formats || []).forEach(function (f) {
      var r = sh.getRange(f.range);
      if (f.bold !== undefined) r.setFontWeight(f.bold ? 'bold' : 'normal');
      if (f.italic !== undefined) r.setFontStyle(f.italic ? 'italic' : 'normal');
      if (f.bg) r.setBackground(f.bg);
      if (f.color) r.setFontColor(f.color);
      if (f.size) r.setFontSize(f.size);
      if (f.number_format) r.setNumberFormat(f.number_format);
      if (f.align) r.setHorizontalAlignment(f.align);
      if (f.wrap !== undefined) r.setWrap(!!f.wrap);
    });
    (sd.borders || []).forEach(function (a1) { sh.getRange(a1).setBorder(true, true, true, true, true, true); });
    (sd.merges || []).forEach(function (a1) { sh.getRange(a1).merge(); });
    var fz = sd.frozen || {};
    if (fz.rows) sh.setFrozenRows(fz.rows);
    if (fz.cols) sh.setFrozenColumns(fz.cols);
    Object.keys(sd.widths || {}).forEach(function (k) { sh.setColumnWidth(colNum_(k), sd.widths[k]); });
    (sd.cf || []).forEach(function (c) {
      var b = SpreadsheetApp.newConditionalFormatRule().setRanges([sh.getRange(c.range)]);
      var v = c.value;
      if (c.when === 'gt') b = b.whenNumberGreaterThan(Number(v)); else if (c.when === 'ge') b = b.whenNumberGreaterThanOrEqualTo(Number(v));
      else if (c.when === 'lt') b = b.whenNumberLessThan(Number(v)); else if (c.when === 'le') b = b.whenNumberLessThanOrEqualTo(Number(v));
      else if (c.when === 'eq') b = b.whenNumberEqualTo(Number(v)); else if (c.when === 'ne') b = b.whenNumberNotEqualTo(Number(v));
      else if (c.when === 'contains') b = b.whenTextContains(String(v)); else if (c.when === 'blank') b = b.whenCellEmpty();
      else if (c.when === 'notblank') b = b.whenCellNotEmpty(); else if (c.when === 'formula') b = b.whenFormulaSatisfied(String(v));
      if (c.bg) b = b.setBackground(c.bg);
      if (c.color) b = b.setFontColor(c.color);
      sh.setConditionalFormatRules(sh.getConditionalFormatRules().concat([b.build()]));
    });
    (sd.validations || []).forEach(function (v) {
      var r = sh.getRange(v.range), b = SpreadsheetApp.newDataValidation();
      if (v.list) b = b.requireValueInList(v.list, true); else if (v.from) b = b.requireValueInRange(ss.getRange(v.from), true);
      else if (v.type === 'number') b = b.requireNumberGreaterThanOrEqualTo(-1e15); else if (v.type === 'date') b = b.requireDate(); else if (v.type === 'checkbox') b = b.requireCheckbox();
      r.setDataValidation(b.build());
    });
    if (sd.filter && sd.filter.range) {
      var f = sh.getRange(sd.filter.range).createFilter();
      var rg2 = sh.getRange(sd.filter.range), headerRow = rg2.getRow(), firstCol = rg2.getColumn();
      Object.keys(sd.filter.hide || {}).forEach(function (name) {
        var col = -1, hdr = sh.getRange(headerRow, firstCol, 1, rg2.getNumColumns()).getValues()[0];
        for (var i = 0; i < hdr.length; i++) if (String(hdr[i]) === name) col = firstCol + i;
        if (col > 0) f.setColumnFilterCriteria(col, SpreadsheetApp.newFilterCriteria().setHiddenValues(sd.filter.hide[name]).build());
      });
    }
    (sd.hidden && sd.hidden.rows || []).forEach(function (r) { sh.hideRows(r); });
    (sd.hidden && sd.hidden.cols || []).forEach(function (c) { sh.hideColumns(colNum_(c)); });
    if (sd.tab_color) sh.setTabColor(sd.tab_color);
    // 型の確かめ: 読み戻して、化けたセルを番地で返す
    if (nr > 0 && nc > 0) {
      var rg3 = sh.getRange(1, 1, nr, nc), vals = rg3.getValues(), fs = rg3.getFormulas();
      for (var r = 0; r < nr && problems.length < 20; r++) for (var c = 0; c < nc; c++) {
        var why = trialCheckCell_(grid[r][c], vals[r][c], fs[r][c]);
        if (why) { problems.push(sd.name + '!' + a1_(r + 1, c + 1) + ' ' + why); if (problems.length >= 20) break; }
      }
    }
  });
  (req.named || []).forEach(function (n) { ss.setNamedRange(n.name, ss.getRange(n.range)); });
  ss.deleteSheet(tmp);
  sheets.forEach(function (sd) { if (sd.hide_sheet) ss.getSheetByName(sd.name).hideSheet(); });
  SpreadsheetApp.flush();
  if (problems.length) return { ok: false, error: '流し込んだ後に型が化けたセルがあります（' + problems.length + ' 件まで表示）: ' + problems.join(' ／ '), problems: problems };
  return { ok: true, sheets: sheets.length };
}
EXTRA_ACTIONS['seed'] = trialSeed_;

EXTRA_ACTIONS['snap'] = function (req) {
  var ss = trialOpen_(req.id);
  var s = trialSnap_(ss);
  return { ok: true, snap: s };
};

// 1 回の POST で「流し込む → 撮る → ops を撃つ → 撮る → 戻す → 撮る」。試験場にだけ効く
EXTRA_ACTIONS['trial'] = function (req) {
  var out = { ok: true };
  var ss = trialOpen_(req.id);
  if (req.seed) {
    var sd = trialSeed_(Object.assign({ id: req.id }, req.seed));
    out.seed = sd;
    if (!sd.ok) return { ok: false, error: sd.error, seed: sd };
  }
  var items0 = ledger_().items.length;
  out.a = trialSnap_(ss);
  var res = actDo_({ target: { id: req.id, kind: 'sheet' }, ops: req.ops || [], ok: !!req.ok });
  out.do = res;
  out.b = trialSnap_(ss);
  var items1 = ledger_().items.length;
  out.backups_added = items1 - items0;
  if (req.restore !== false && res && res.ok && res.backup) {
    out.undo = actUndo_({ target_id: req.id, ok: false });
    out.c = trialSnap_(ss);
  }
  return out;
};
