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

function trialRng_(g) {
  if (!g) return '';
  var a = colLetter_((g.startColumnIndex || 0) + 1) + ((g.startRowIndex || 0) + 1);
  if (g.endColumnIndex === undefined && g.endRowIndex === undefined) return a;
  return a + ':' + colLetter_(g.endColumnIndex || ((g.startColumnIndex || 0) + 1)) + (g.endRowIndex || ((g.startRowIndex || 0) + 1));
}

// 脇の状態: 戻しが約束していない物の一覧（約束の指紋には入れず、戻らなかった物として並べる）
function trialSide_(sh) {
  var P = sh.properties || {};
  var bf = sh.basicFilter;
  var side = {
    filter: bf ? { range: trialRng_(bf.range), criteria: bf.criteria ? Object.keys(bf.criteria).sort() : [] } : null,
    cf_rules: (sh.conditionalFormats || []).map(function (r) {
      var b = r.booleanRule;
      return { ranges: (r.ranges || []).map(trialRng_), type: b ? b.condition.type : (r.gradientRule ? 'GRADIENT' : ''), values: b ? (b.condition.values || []).map(function (v) { return v.userEnteredValue; }) : [],
        bg: b && b.format ? trialHex_(b.format.backgroundColor, '') : '' };
    }),
    protected: (sh.protectedRanges || []).map(function (r) { var g = r.range || {}; var whole = g.startRowIndex === undefined && g.endRowIndex === undefined && g.startColumnIndex === undefined && g.endColumnIndex === undefined; return { range: whole ? 'シート全体' : trialRng_(g), warning: !!r.warningOnly }; }),
    charts: (sh.charts || []).map(function (c) { var s = c.spec || {}; return { title: s.title || '', type: s.basicChart ? s.basicChart.chartType : (s.pieChart ? 'PIE' : 'OTHER') }; }),
    banded: (sh.bandedRanges || []).map(function (r) { return trialRng_(r.range); }),
    groups: { rows: (sh.rowGroups || []).map(function (g) { return { range: trialRng_(g.range), depth: g.depth, collapsed: !!g.collapsed }; }),
      cols: (sh.columnGroups || []).map(function (g) { return { range: trialRng_(g.range), depth: g.depth, collapsed: !!g.collapsed }; }) },
    tab_color: P.tabColorStyle && P.tabColorStyle.rgbColor ? trialHex_(P.tabColorStyle.rgbColor, '') : '',
    validations: {}
  };
  return side;
}

// Sheets API の 1 シート（spreadsheets.get の sheets[i]）を、道具が比べやすい形にする（疎: 値か書式のあるセルだけ）
function trialSnapSheet_(sh) {
  var P = sh.properties || {}, G = P.gridProperties || {};
  var out = { name: P.title, id: P.sheetId, index: P.index, hidden: !!P.hidden, rows: G.rowCount || 0, cols: G.columnCount || 0,
    frozen: { rows: G.frozenRowCount || 0, cols: G.frozenColumnCount || 0 }, merges: [], hidden_rows: [], filtered_rows: [], hidden_cols: [], widths: [], cells: {}, cf: (sh.conditionalFormats || []).length, side: trialSide_(sh) };
  (sh.merges || []).forEach(function (m) { out.merges.push(colLetter_((m.startColumnIndex || 0) + 1) + ((m.startRowIndex || 0) + 1) + ':' + colLetter_(m.endColumnIndex) + m.endRowIndex); });
  var d = (sh.data || [])[0] || {};
  (d.rowMetadata || []).forEach(function (r, i) { if (r.hiddenByUser) out.hidden_rows.push(i + 1); if (r.hiddenByFilter) out.filtered_rows.push(i + 1); });
  (d.columnMetadata || []).forEach(function (c, i) { if (c.hiddenByUser) out.hidden_cols.push(i + 1); out.widths.push(c.pixelSize || 0); });
  (d.rowData || []).forEach(function (row, r) {
    (row.values || []).forEach(function (cell, c) {
      if (cell.dataValidation) { var dv = cell.dataValidation, a1v = colLetter_(c + 1) + (r + 1); out.side.validations[a1v] = { type: dv.condition ? dv.condition.type : '', values: dv.condition ? (dv.condition.values || []).map(function (x) { return x.userEnteredValue || x.relativeDate || ''; }) : [], strict: !!dv.strict }; }
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

var TRIAL_SNAP_FIELDS = 'namedRanges,sheets(properties(sheetId,title,index,hidden,tabColorStyle,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)),merges,' +
  'basicFilter,conditionalFormats,protectedRanges(range,warningOnly),charts(chartId,spec(title,basicChart(chartType),pieChart(legendPosition))),bandedRanges(range),rowGroups,columnGroups,' +
  'data(rowMetadata(hiddenByUser,hiddenByFilter),columnMetadata(hiddenByUser,pixelSize),rowData(values(formattedValue,userEnteredValue,effectiveValue,' +
  'dataValidation,userEnteredFormat(backgroundColor,textFormat(bold,foregroundColor)),effectiveFormat(backgroundColor,textFormat(bold,foregroundColor),numberFormat,borders)))))';

// 今の状態を撮る（Sheets API の spreadsheets.get を 1 回）
function trialSnap_(ss) {
  var resp = Sheets.Spreadsheets.get(ss.getId(), { includeGridData: true, fields: TRIAL_SNAP_FIELDS });
  return { name: ss.getName(), sheets: (resp.sheets || []).map(trialSnapSheet_), named: (resp.namedRanges || []).map(function (n) { return { name: n.name, range: trialRng_(n.range) }; }) };
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
  // 名前付き範囲は API で全部消す（シートを消すと SpreadsheetApp からは見えなくなるが、API には残り、同じ名前を足せなくなる）
  var oldNames = (Sheets.Spreadsheets.get(ss.getId(), { fields: 'namedRanges(namedRangeId)' }).namedRanges || []);
  if (oldNames.length) Sheets.Spreadsheets.batchUpdate({ requests: oldNames.map(function (n) { return { deleteNamedRange: { namedRangeId: n.namedRangeId } }; }) }, ss.getId());
  var tmp = ss.insertSheet('__seed_tmp__' + Date.now());
  ss.getSheets().forEach(function (s) { if (s.getSheetId() !== tmp.getSheetId()) ss.deleteSheet(s); });
  ss.getNamedRanges().forEach(function (n) { n.remove(); });
  var problems = [];
  sheets.forEach(function (sd) {
    var sh = ss.insertSheet(sd.name);
    var grid = sd.grid || [], nr = grid.length, nc = 0, cells = [];
    grid.forEach(function (r) { if (r.length > nc) nc = r.length; });
    if (nr > 0 && nc > 0) {
      if (sh.getMaxRows() < nr) sh.insertRowsAfter(sh.getMaxRows(), nr - sh.getMaxRows());
      if (sh.getMaxColumns() < nc) sh.insertColumnsAfter(sh.getMaxColumns(), nc - sh.getMaxColumns());
      cells = grid.map(function (r) { var o = []; for (var c = 0; c < nc; c++) o.push(trialCell_(r[c])); return o; });
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
      if (f.number_format) {
        // {"text":…}（文字のまま）のセルには数の書式を掛けない。掛けると Sheets が文字を数に読み直して化ける
        var nfr = r.getNumberFormats(), r0 = r.getRow(), c0 = r.getColumn();
        r.setNumberFormats(nfr.map(function (row, i) { return row.map(function (x, j) { var cc = cells[r0 - 1 + i] && cells[r0 - 1 + i][c0 - 1 + j]; return (cc && cc.nf === '@') ? x : f.number_format; }); }));
      }
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
    // ふつうの文字（{"text"} でない）が日付や数に読まれたセルは、そのセルだけ文字のままに直す（"2026年11月" が日付になる等。ほかのセルの書式は動かさない）
    if (nr > 0 && nc > 0) {
      var rgH = sh.getRange(1, 1, nr, nc), valsH = rgH.getValues();
      for (var rh = 0; rh < nr; rh++) for (var ch = 0; ch < nc; ch++) {
        var eh = grid[rh][ch];
        if (typeof eh === 'string' && eh.charAt(0) !== '=' && valsH[rh][ch] !== eh) { var cellH = sh.getRange(rh + 1, ch + 1); cellH.setNumberFormat('@'); cellH.setValue(eh); }
      }
    }
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


// ---------------------------------------------------------------- 脇の状態の調べ（試験用のエンジンの中だけ。棚には足さない）
// 「触る:」に脇の状態の全項目を出している試験用の棚（値を 1 つ書くだけ）。これを撃つと、控えが全項目を記録する
CATALOG['trial.touch_all'] = { kind: 'sheet', touch: ['値', '隠し', 'グループ', '保護', '名前', 'タブ色', 'グラフ', 'フィルタ'], backup: ['今'], danger: '' };
SHELF['trial.touch_all'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  sh.getRange('B3').setValue('書換');
  chg_(ctx, sh, 'B3', '値を書いた（試験用）');
};

// 項目を付ける・外す手。戻しが約束していない「脇の状態」が ws_undo で戻るかを調べる材料
function trialSideApply_(ss, sh, item) {
  var B = SpreadsheetApp.BandingTheme;
  if (item === 'frozen') sh.setFrozenRows(2);
  else if (item === 'validation_list') sh.getRange('C2:C5').setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(['未着手', '完了'], true).build());
  else if (item === 'validation_checkbox') sh.getRange('G2:G5').insertCheckboxes();
  else if (item === 'cf') sh.setConditionalFormatRules([SpreadsheetApp.newConditionalFormatRule().setRanges([sh.getRange('F2:F20')]).whenNumberGreaterThan(11999).setBackground('#ffff00').build()]);
  else if (item === 'banding') sh.getRange('A1:F20').applyRowBanding(B.LIGHT_GREY);
  else if (item === 'filter') { var f = sh.getRange('A1:F20').createFilter(); f.setColumnFilterCriteria(2, SpreadsheetApp.newFilterCriteria().setHiddenValues(['会員14']).build()); }
  else if (item === 'hide_rows') sh.hideRows(9);
  else if (item === 'hide_cols') sh.hideColumns(3);
  else if (item === 'hide_sheet') { ss.insertSheet('メモ'); sh.hideSheet(); }
  else if (item === 'group_rows') sh.getRange('10:12').shiftRowGroupDepth(1);
  else if (item === 'group_cols') sh.getRange('D:E').shiftColumnGroupDepth(1);
  else if (item === 'protect_sheet') sh.protect().setDescription('試験').setWarningOnly(true);
  else if (item === 'protect_range') sh.getRange('F2:F20').protect().setDescription('試験').setWarningOnly(true);
  else if (item === 'named') ss.setNamedRange('金額列', sh.getRange('F2:F20'));
  else if (item === 'tab_color') sh.setTabColor('#ff0000');
  else if (item === 'chart') sh.insertChart(sh.newChart().setChartType(Charts.ChartType.COLUMN).addRange(sh.getRange('F1:F20')).setPosition(2, 8, 0, 0).setOption('title', '試験').build());
  else throw new ArgError('知らない項目: ' + item);
}

function trialSideChange_(ss, sh, item) {
  if (item === 'frozen') sh.setFrozenRows(0);
  else if (item === 'validation_list') sh.getRange('C2:C5').clearDataValidations();
  else if (item === 'validation_checkbox') sh.getRange('G2:G5').removeCheckboxes();
  else if (item === 'cf') sh.setConditionalFormatRules([]);
  else if (item === 'banding') sh.getBandings().forEach(function (b) { b.remove(); });
  else if (item === 'filter') { var f = sh.getFilter(); if (f) f.remove(); }
  else if (item === 'hide_rows') sh.showRows(9);
  else if (item === 'hide_cols') sh.showColumns(3);
  else if (item === 'hide_sheet') sh.showSheet();
  else if (item === 'group_rows') sh.getRange('10:12').shiftRowGroupDepth(-1);
  else if (item === 'group_cols') sh.getRange('D:E').shiftColumnGroupDepth(-1);
  else if (item === 'protect_sheet') sh.getProtections(SpreadsheetApp.ProtectionType.SHEET).forEach(function (q) { q.remove(); });
  else if (item === 'protect_range') sh.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (q) { q.remove(); });
  else if (item === 'named') ss.removeNamedRange('金額列');
  else if (item === 'tab_color') sh.setTabColor(null);
  else if (item === 'chart') sh.getCharts().forEach(function (c) { sh.removeChart(c); });
  else throw new ArgError('知らない項目: ' + item);
}

// 1 回の POST で「流し込む → 項目を付ける → 撮る(x) → 値だけ変える棚を撃つ → [場合 A: 項目を外す・変える] → 撮る(z) → ws_undo → 撮る(y)」
EXTRA_ACTIONS['side_case'] = function (req) {
  var step = 'open', out = { ok: true, item: req.item, case: req.case };
  try {
    var ss = trialOpen_(req.id);
    step = 'seed';
    var sd = trialSeed_(Object.assign({ id: req.id }, req.seed));
    if (!sd.ok) return { ok: false, error: sd.error, step: step };
    step = 'apply';
    ss = trialOpen_(req.id);   // seed が別のハンドルでシートを作り直したので、開き直す
    trialSideApply_(ss, ss.getSheetByName('名簿'), req.item);
    SpreadsheetApp.flush();
    step = 'snap_x';
    out.x = trialSnap_(ss);
    step = 'do';
    out.do = actDo_({ target: { id: req.id, kind: 'sheet' }, ops: [req.case === 'A' ? { shelf: 'trial.touch_all', sheet: '名簿' } : { shelf: 'write', sheet: '名簿', cells: { B3: '書換' } }], ok: true });
    if (req.case === 'A') { step = 'change'; ss = trialOpen_(req.id); trialSideChange_(ss, ss.getSheetByName('名簿'), req.item); SpreadsheetApp.flush(); }
    step = 'snap_z';
    out.z = trialSnap_(ss);
    step = 'undo';
    var origBU = Sheets.Spreadsheets.batchUpdate, logBU = [];
    if (req.debug) { out.sideRec = getJson_('SIDE_' + (out.do && out.do.backup), null); Sheets.Spreadsheets.batchUpdate = function (b, id) { logBU.push({ req: b.requests }); out.batchLog = logBU; var r = origBU.call(Sheets.Spreadsheets, b, id); logBU[logBU.length - 1].res = r; return r; }; }
    out.undo = actUndo_({ target_id: req.id, ok: true });
    if (req.debug) { Sheets.Spreadsheets.batchUpdate = origBU; out.batchLog = logBU; }
    if (req.debug) { var shd = trialOpen_(req.id).getSheetByName('名簿'), fd = shd.getFilter(); out.dbgFilter = { has: !!fd, hidden2: fd && fd.getColumnFilterCriteria(2) ? fd.getColumnFilterCriteria(2).getHiddenValues() : null, rowHidden4: shd.isRowHiddenByFilter(4), b4: shd.getRange('B4').getValue(), rng: fd ? fd.getRange().getA1Notation() : null }; }
    step = 'snap_y';
    out.y = trialSnap_(ss);
    return out;
  } catch (e) {
    return { ok: false, error: String(e && e.message || e), step: step, stack: String(e && e.stack || '').slice(0, 300), batchLog: out.batchLog };
  }
};

// グラフの付け直しが Internal error になる原因の調べ（試験用）。記録した spec をいくつかの形で addChart してみる
EXTRA_ACTIONS['chart_try'] = function (req) {
  var ss = trialOpen_(req.id);
  var sd = trialSeed_(Object.assign({ id: req.id }, req.seed));
  if (!sd.ok) return { ok: false, error: sd.error };
  ss = trialOpen_(req.id);
  var sh = ss.getSheetByName('名簿');
  trialSideApply_(ss, sh, 'chart');
  SpreadsheetApp.flush();
  var r = Sheets.Spreadsheets.get(ss.getId(), { fields: 'sheets(properties(sheetId),charts(chartId,spec,position))' });
  var x = r.sheets.filter(function (s) { return s.properties.sheetId === sh.getSheetId(); })[0];
  var rec = x.charts[0];
  var out = { ok: true, spec: rec.spec, position: rec.position, tries: {} };
  var attempt = function (name, chart, delFirst) {
    try {
      var reqs = [];
      if (delFirst) reqs.push({ deleteEmbeddedObject: { objectId: rec.chartId } });
      reqs.push({ addChart: { chart: chart } });
      Sheets.Spreadsheets.batchUpdate({ requests: reqs }, ss.getId());
      out.tries[name] = 'ok';
      var cur = Sheets.Spreadsheets.get(ss.getId(), { fields: 'sheets(properties(sheetId),charts(chartId))' }).sheets.filter(function (s) { return s.properties.sheetId === sh.getSheetId(); })[0].charts || [];
      cur.forEach(function (c) { if (c.chartId !== rec.chartId) { try { Sheets.Spreadsheets.batchUpdate({ requests: [{ deleteEmbeddedObject: { objectId: c.chartId } }] }, ss.getId()); } catch (e) { } } });
    } catch (e) { out.tries[name] = String(e.message || e).slice(0, 160); }
  };
  // 1: 記録のまま（消してから）
  attempt('そのまま・消さずに足す', { spec: rec.spec, position: rec.position }, false);
  var s2 = JSON.parse(JSON.stringify(rec.spec)); delete s2.titleTextFormat; delete s2.fontName; delete s2.hiddenDimensionStrategy;
  attempt('書式の欄を除く', { spec: s2, position: rec.position }, false);
  var s3 = JSON.parse(JSON.stringify(s2)); (s3.basicChart.axis || []).forEach(function (a) { delete a.viewWindowOptions; });
  attempt('書式と軸の窓を除く', { spec: s3, position: rec.position }, false);
  var p2 = JSON.parse(JSON.stringify(rec.position)); var op = p2.overlayPosition || {}; delete op.widthPixels; delete op.heightPixels;
  attempt('大きさを除く', { spec: s3, position: { overlayPosition: op } }, false);
  return out;
};

// ws_look の脇の状態の出方を見る（試験用）: 流し込む → 項目を全部付ける → look の返事を返す
EXTRA_ACTIONS['side_look'] = function (req) {
  var ss = trialOpen_(req.id);
  var sd = trialSeed_(Object.assign({ id: req.id }, req.seed));
  if (!sd.ok) return { ok: false, error: sd.error };
  ss = trialOpen_(req.id);
  (req.items || []).forEach(function (it) { trialSideApply_(ss, ss.getSheetByName('名簿'), it); });
  SpreadsheetApp.flush();
  return actLook_({ target: { id: req.id, kind: 'sheet' }, sheet: '名簿' });
};

// ---------------------------------------------------------------- 性質の総当たり・模範の再生の下回し（棚を 1 組ずつ撃つ）
// steps: {snap:名前} 撮る／{do:ops, ok, name, retry_wide} 撃つ（retry_wide: 広い削除で止まったら、同じ ops をもう一度撃つ＝P7 の通し方）／{undo_all:true, name} この呼びで取った控えを全部戻す
function trialSlim_(r) {
  return { ok: !!r.ok, error: r.error || null, blocked: !!r.blocked, arg: !!r.arg, restored: r.restored, changed: r.changed || [], notes: r.notes || [], backup: r.backup || 0 };
}
EXTRA_ACTIONS['seq'] = function (req) {
  var ss = trialOpen_(req.id);
  if (req.seed) {
    var sd = trialSeed_(Object.assign({ id: req.id }, req.seed));
    if (!sd.ok) return { ok: false, error: sd.error, step: 'seed' };
    ss = trialOpen_(req.id);
  }
  var out = { ok: true, snaps: {}, steps: [] }, made = 0, ledger0 = ledger_().items.length;
  (req.steps || []).forEach(function (st) {
    if (st.snap) { out.snaps[st.snap] = trialSnap_(ss); return; }
    if (st.do) {
      var go = function () { return actDo_({ target: { id: req.id, kind: 'sheet' }, ops: st.do, ok: !!st.ok }); };
      var r = go(), wide = false;
      if (st.retry_wide && !r.ok && r.blocked && String(r.error || '').indexOf('広い削除') >= 0) { wide = true; r = go(); }
      if (r.ok && r.backup) made++;
      var o = { name: st.name, res: trialSlim_(r), wide: wide };
      o.res.error_brief = String(r.error || '').slice(0, 200);
      out.steps.push(o);
      return;
    }
    if (st.undo_all) {
      var us = [];
      for (var i = 0; i < made; i++) { var u = actUndo_({ target_id: req.id, ok: true }); us.push({ ok: !!u.ok, error: u.error || null, notes: u.notes || [] }); }
      made = 0;
      out.steps.push({ name: st.name, undo: us });
    }
  });
  out.ledger_added = ledger_().items.length - ledger0;
  return out;
};
