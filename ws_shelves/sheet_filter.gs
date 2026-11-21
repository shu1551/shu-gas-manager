// 絞る・整える棚（整える手伝い tidyRange_ もここ）

// 速い版：書式・幅・固定を Sheets API の batchUpdate 1 回にまとめる（セルごとの呼び出しをやめる）。失敗したら従来の版（tidyRangeLegacy_）でやり直す
function hexColor_(h) { return { red: parseInt(h.substr(1, 2), 16) / 255, green: parseInt(h.substr(3, 2), 16) / 255, blue: parseInt(h.substr(5, 2), 16) / 255 }; }
function tidyNumText_(v, dec) {
  var s = Math.abs(v).toFixed(dec ? 2 : 0), p = s.split('.');
  p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (v < 0 ? '-' : '') + p.join('.');
}
function tidyRange_(ctx, sh, rangeA1) {
  if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets || typeof Sheets.Spreadsheets.batchUpdate !== 'function') return tidyRangeLegacy_(ctx, sh, rangeA1);
  var t = findTable_(sh);
  if (!t) { note_(ctx, 'tidy: 表が見つからないので整えていません'); return; }
  try {
    if (rangeA1) {
      var r = sh.getRange(rangeA1);
      t.firstCol = r.getColumn(); t.lastCol = r.getLastColumn();
    }
    var sid = sh.getSheetId(), nc = t.lastCol - t.firstCol + 1, last = t.totalRow || t.lastData;
    var grid = function (r1, r2, c1, c2) { return { sheetId: sid, startRowIndex: r1 - 1, endRowIndex: r2, startColumnIndex: c1 - 1, endColumnIndex: c2 }; };
    var bd = { style: 'SOLID', color: hexColor_(STYLE.border) };
    var reqs = [
      { updateBorders: { range: grid(t.headerRow, last, t.firstCol, t.lastCol), top: bd, bottom: bd, left: bd, right: bd, innerHorizontal: bd, innerVertical: bd } },
      { repeatCell: { range: grid(t.headerRow, last, t.firstCol, t.lastCol), cell: { userEnteredFormat: { verticalAlignment: 'MIDDLE' } }, fields: 'userEnteredFormat.verticalAlignment' } },
      { repeatCell: { range: grid(t.headerRow, t.headerRow, t.firstCol, t.lastCol), cell: { userEnteredFormat: { backgroundColor: hexColor_(STYLE.headBg), textFormat: { bold: true, foregroundColor: hexColor_(STYLE.headFg) }, horizontalAlignment: 'CENTER', wrapStrategy: 'WRAP' } }, fields: 'userEnteredFormat(backgroundColor,textFormat(bold,foregroundColor),horizontalAlignment,wrapStrategy)' } }
    ];
    var colFmt = {};   // 列ごとの書式（幅の見積もりに使う）
    if (t.lastData - t.firstData + 1 >= 1) {
      var rows = (t.totalRow ? t.totalRow : t.lastData) - t.firstData + 1;
      for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
        var vals = [];
        for (var rr = t.firstData; rr <= t.lastData; rr++) vals.push(t.vals[rr - 1][ci - 1]);
        var fmt = null, align = null, kind = null;
        if (isNoCol_(t, ci)) align = 'center';
        else {
          var nums = vals.filter(function (v) { return typeof v === 'number'; });
          var dates = vals.filter(function (v) { return Object.prototype.toString.call(v) === '[object Date]'; });
          var nonEmpty = vals.filter(function (v) { return !isBlank_(v); }).length;
          if (nonEmpty && nums.length / nonEmpty > 0.5) { var dec = nums.some(function (v) { return v % 1 !== 0; }); fmt = dec ? STYLE.numFmtDec : STYLE.numFmt; align = 'right'; kind = dec ? 'dec' : 'int'; }
          else if (nonEmpty && dates.length / nonEmpty > 0.5) { fmt = STYLE.dateFmt; align = 'center'; kind = 'date'; }
        }
        colFmt[ci] = kind;
        var uf = {}, fl = [];
        if (fmt) { uf.numberFormat = { type: kind === 'date' ? 'DATE' : 'NUMBER', pattern: fmt }; fl.push('numberFormat'); }
        if (align) { uf.horizontalAlignment = align.toUpperCase(); fl.push('horizontalAlignment'); }
        if (fl.length) reqs.push({ repeatCell: { range: grid(t.firstData, t.firstData + rows - 1, ci, ci), cell: { userEnteredFormat: uf }, fields: 'userEnteredFormat(' + fl.join(',') + ')' } });
      }
    }
    if (t.totalRow) reqs.push({ repeatCell: { range: grid(t.totalRow, t.totalRow, t.firstCol, t.lastCol), cell: { userEnteredFormat: { backgroundColor: hexColor_(STYLE.totalBg), textFormat: { bold: true } } }, fields: 'userEnteredFormat(backgroundColor,textFormat(bold))' } });
    // 列幅：中身に合わせる。数値・日付は、これから付ける書式で表示される形に見積もる
    var disp = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc).getDisplayValues();
    for (var c = 0; c < nc; c++) {
      var k = colFmt[t.firstCol + c], mx = 0;
      disp.forEach(function (row, ri) {
        var s = row[c], v = t.vals[t.headerRow - 1 + ri][t.firstCol - 1 + c];
        if (k && ri > 0) {
          if (k === 'date' && Object.prototype.toString.call(v) === '[object Date]') s = '0000/00/00';
          else if ((k === 'int' || k === 'dec') && typeof v === 'number') s = tidyNumText_(v, k === 'dec');
        }
        mx = Math.max(mx, wlen_(s));
      });
      reqs.push({ updateDimensionProperties: { range: { sheetId: sid, dimension: 'COLUMNS', startIndex: t.firstCol - 1 + c, endIndex: t.firstCol + c }, properties: { pixelSize: Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad)) }, fields: 'pixelSize' } });
    }
    // 見出しの行までを固定する。結合セルが固定の線をまたぐと Google が断るので、またぐ結合の終わりの行まで広げる
    var fr = t.headerRow;
    try {
      for (var pass = 0; pass < 4; pass++) {
        var fr0 = fr;
        sh.getRange(1, 1, fr, Math.max(1, sh.getLastColumn())).getMergedRanges().forEach(function (m) { fr = Math.max(fr, m.getLastRow()); });
        if (fr === fr0) break;
      }
    } catch (e) { fr = t.headerRow; }
    reqs.push({ updateSheetProperties: { properties: { sheetId: sid, gridProperties: { frozenRowCount: fr } }, fields: 'gridProperties.frozenRowCount' } });
    if (ctx.changed.length) SpreadsheetApp.flush();   // 前の書き込み（値・行の削除）を先に反映してから、行番号で指す
    batchRetry_(sh.getParent(), reqs);
  } catch (e) {
    note_(ctx, '速い整え方が使えなかったので従来の方法で整えました（' + String(e && e.message || e).slice(0, 120) + '）');
    tidyRangeLegacy_(ctx, sh, rangeA1);   // うまくいかなければ従来のやり方で整える
  }
}

function tidyRangeLegacy_(ctx, sh, rangeA1) {
  var t = findTable_(sh);
  if (!t) { note_(ctx, 'tidy: 表が見つからないので整えていません'); return; }
  if (rangeA1) {
    var r = sh.getRange(rangeA1);
    t.firstCol = r.getColumn(); t.lastCol = r.getLastColumn();
  }
  var nc = t.lastCol - t.firstCol + 1, last = t.totalRow || t.lastData;
  var full = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc);
  full.setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  full.setVerticalAlignment('middle');
  var hd = sh.getRange(t.headerRow, t.firstCol, 1, nc);
  hd.setFontWeight('bold').setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setHorizontalAlignment('center').setWrap(true);
  var cnt = t.lastData - t.firstData + 1;
  if (cnt >= 1) {
    // 表の値は findTable_ が 1 回で読んだもの（t.vals）を使う。書式は範囲ごとの配列で一括して書く
    var rows = (t.totalRow ? t.totalRow : t.lastData) - t.firstData + 1;
    var bodyRg = sh.getRange(t.firstData, t.firstCol, rows, nc);
    var nf = bodyRg.getNumberFormats(), al = bodyRg.getHorizontalAlignments();
    for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
      var k = ci - t.firstCol, vals = [];
      for (var r = t.firstData; r <= t.lastData; r++) vals.push(t.vals[r - 1][ci - 1]);
      var fmt = null, align = null;
      if (isNoCol_(t, ci)) align = 'center';
      else {
        var nums = vals.filter(function (v) { return typeof v === 'number'; });
        var dates = vals.filter(function (v) { return Object.prototype.toString.call(v) === '[object Date]'; });
        var nonEmpty = vals.filter(function (v) { return !isBlank_(v); }).length;
        if (nonEmpty && nums.length / nonEmpty > 0.5) { fmt = nums.some(function (v) { return v % 1 !== 0; }) ? STYLE.numFmtDec : STYLE.numFmt; align = 'right'; }
        else if (nonEmpty && dates.length / nonEmpty > 0.5) { fmt = STYLE.dateFmt; align = 'center'; }
      }
      for (var rr = 0; rr < rows; rr++) { if (fmt) nf[rr][k] = fmt; if (align) al[rr][k] = align; }
    }
    bodyRg.setNumberFormats(nf).setHorizontalAlignments(al);
  }
  if (t.totalRow) sh.getRange(t.totalRow, t.firstCol, 1, nc).setFontWeight('bold').setBackground(STYLE.totalBg);
  // 列幅：中身に合わせる（上限・下限つき）
  var disp = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc).getDisplayValues();
  for (var c = 0; c < nc; c++) {
    var mx = 0; disp.forEach(function (row) { mx = Math.max(mx, wlen_(row[c])); });
    sh.setColumnWidth(t.firstCol + c, Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad)));
  }
  // 見出しの行までを固定する。結合セルが固定の線をまたぐと Google が断るので、またぐ結合の終わりの行まで広げる
  var fr = t.headerRow;
  try {
    for (var pass = 0; pass < 4; pass++) {
      var fr0 = fr;
      sh.getRange(1, 1, fr, Math.max(1, sh.getLastColumn())).getMergedRanges().forEach(function (m) { fr = Math.max(fr, m.getLastRow()); });
      if (fr === fr0) break;
    }
  } catch (e) { fr = t.headerRow; }
  try { sh.setFrozenRows(fr); } catch (e) { note_(ctx, '結合セルをまたぐので、行の固定は変えませんでした'); }
}

// 棚: tidy
// 題: 表の見た目を整える
// 分類: 整える
// 語: 表を整|見た目を整|体裁を整|見やすく|罫線を引|列幅を揃|見た目も整
// 違い: 見た目（罫線・幅・書式）だけ頼まれたとき（「見た目も整えて」「列幅も合わせて」）用。「表をきれいに整えて」等で空白・全角・数字文字などの汚れがあり得るときは seiri を使う（seiri は汚れを直したあと見た目も自動で整える）
// 引数: range=範囲
// 例: 「この表を見やすく整えて」 → {"shelf":"tidy"}
// 例: 「B列からD列だけ体裁を整えて」 → {"shelf":"tidy","range":"B:D"}
// 触る: 書式 幅 固定
SHELF['tidy'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  tidyRange_(ctx, sh, op.range || null);
  chg_(ctx, sh, op.range || 'A1', '書式をそろえた');
};

// 昇順または降順の行番号配列を連続ラン単位で後ろから一括削除する
function deleteRowRuns_(sh, rowNums) {
  if (!rowNums || !rowNums.length) return;
  var seen = {}, desc = [];
  for (var i = 0; i < rowNums.length; i++) {
    var n = rowNums[i];
    if (!seen[n]) { seen[n] = 1; desc.push(n); }
  }
  desc.sort(function (a, b) { return b - a; });
  for (var di = 0; di < desc.length; ) {
    var runEnd = desc[di], runStart = runEnd;
    while (di + 1 < desc.length && desc[di + 1] === runStart - 1) { runStart = desc[++di]; }
    sh.deleteRows(runStart, runEnd - runStart + 1);
    di++;
  }
}

// 棚: seiri
// 題: 表のデータを整理する
// 分類: 整える
// 語: データを整理|空白を除|全角を半角|全角の数字|数字を半角|数字を数値に|空行を詰|重複を消|きれいに整|汚れを直|余分な空白|全角数字|空白行|空行を全部|空白や全角|整理して|きれいにして|きれいに整えて
// 違い: 前後の空白・全角半角・数字文字の掃除と見た目整え（tidy）をまとめて行う。見た目だけと限らない「表をきれいに整えて」はこれ。blank_rows/dedupe を付けない限り行削除はしないので ok 不要で即撃てる。見た目だけなら tidy
// 引数: trim=真偽, halfwidth=真偽, numbers=真偽, blank_rows=真偽, dedupe=真偽, renumber=列, tidy=真偽
// 頼み: blank_rows=true<空行|空いている行 ; dedupe=true<重複 ; halfwidth=true<全角
// 例: 「全角の数字を半角に直して」 → {"shelf":"seiri"}
// 例: 「空行を詰めて重複行も消して」 → {"shelf":"seiri","blank_rows":true,"dedupe":true}
// 危ない: 消す
// 触る: 値 書式 幅 固定
SHELF['seiri'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rg = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
  var vals = rg.getValues(), forms = rg.getFormulas(), fixed = [], nTrim = 0, nHalf = 0, nNum = 0;
  var doTrim = op.trim !== false, doHalf = op.halfwidth !== false, doNum = op.numbers !== false;
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    var v = vals[r][c];
    if (forms[r][c] || typeof v !== 'string') continue;
    var nv = v;
    if (doHalf) { var h = nv.replace(/[！-～]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); }).replace(/　/g, ' '); if (h !== nv) { nv = h; nHalf++; } }
    if (doTrim) { var tr = nv.replace(/^[\s　]+|[\s　]+$/g, ''); if (tr !== nv) { nv = tr; nTrim++; } }
    if (doNum && r > 0 && /^-?[\d,]+(\.\d+)?$/.test(nv) && !/^-?0\d/.test(nv)) { nv = Number(nv.replace(/,/g, '')); nNum++; }
    if (nv !== v) { vals[r][c] = nv; fixed.push(a1_(t.headerRow + r, t.firstCol + c)); }
  }
  if (fixed.length) {
    // 式のセルは触らず、値のセルだけ書く
    // 直したセルだけを、列ごとに縦に連続した範囲にまとめて setValues（1 セルずつ書かない）
    var changedSet = {}; fixed.forEach(function (a) { changedSet[a] = 1; });
    for (var c2 = 0; c2 < vals[0].length; c2++) {
      var r2 = 0;
      while (r2 < vals.length) {
        if (!changedSet[a1_(t.headerRow + r2, t.firstCol + c2)]) { r2++; continue; }
        var r3 = r2; while (r3 + 1 < vals.length && changedSet[a1_(t.headerRow + r3 + 1, t.firstCol + c2)]) r3++;
        sh.getRange(t.headerRow + r2, t.firstCol + c2, r3 - r2 + 1, 1).setValues(vals.slice(r2, r3 + 1).map(function (row) { return [row[c2]]; }));
        r2 = r3 + 1;
      }
    }
    chg_(ctx, sh, fixed.slice(0, 4).join('・') + (fixed.length > 4 ? ' ほか' + (fixed.length - 4) + ' 件' : ''), '空白' + nTrim + '・全角→半角' + nHalf + '・数値化' + nNum);
    if (_TBL_CACHE) _TBL_CACHE = { _once: true };   // 値を書いたので表の読み取り結果を捨てる
  }
  // 空行を詰める＊ / 重複行を消す＊
  var t2 = op.blank_rows ? findTable_(sh) : null;   // 空行・重複を扱わないときは読み直さない（速さのため）
  if (op.blank_rows && t2) {
    var blanks = [];
    for (var rr = t2.firstData; rr <= t2.lastData; rr++) {
      var row = t2.vals[rr - 1].slice(t2.firstCol - 1, t2.lastCol);
      if (row.every(isBlank_)) blanks.push(rr);
    }
    // 表の途中の空行だけ（findTable_ が最後の非空行までを表とするので、すべて途中）
    if (blanks.length) {
      guardDelete_(ctx, '空行 ' + blanks.join('・') + ' 行目を詰めます', wideRowCount_(t2, blanks.length), blanks.length + ' 行');
      deleteRowRuns_(sh, blanks);
      chg_(ctx, sh, blanks.join('・') + ' 行目', '空行を削除（' + blanks.length + ' 行）');
      if (_TBL_CACHE) _TBL_CACHE = { _once: true };
    }
  }
  t2 = op.dedupe ? findTable_(sh) : null;
  if (op.dedupe && t2) {
    var seen = {}, dups = [];
    for (var d = t2.firstData; d <= t2.lastData; d++) {
      var key = JSON.stringify(t2.vals[d - 1].slice(t2.firstCol - 1, t2.lastCol));
      if (seen[key]) dups.push(d); else seen[key] = 1;
    }
    if (dups.length) {
      guardDelete_(ctx, '全列が同じ重複行 ' + dups.join('・') + ' 行目を消します', wideRowCount_(t2, dups.length), dups.length + ' 行');
      deleteRowRuns_(sh, dups);
      chg_(ctx, sh, dups.join('・') + ' 行目', '重複行を削除（' + dups.length + ' 行）');
      if (_TBL_CACHE) _TBL_CACHE = { _once: true };
    }
  }
  if (op.renumber) SHELF['renumber'](ctx, { shelf: 'renumber', col: op.renumber, sheet: op.sheet });
  if (op.tidy !== false) { tidyRange_(ctx, sh, null); chg_(ctx, sh, '', '書式をそろえた'); }   // 書式をそろえるので「変更なし」とは言わない（指紋が変わるため）
  if (!ctx.changed.length) note_(ctx, '直す所はありませんでした');
};

// 棚: renumber
// 題: 表の番号の列を振り直す
// 分類: 整える
// 語: 番号の列|Noの列|番号を振り直|連番に直|番号を振り|通し番号|Noを振|番号を付け直
// 違い: すでに表にある番号の列を、見出しの名前（番号・No）で指して 1,2,3… に直す（空の行は飛ばす）。番地の範囲を指して連番を書くなら fill.series
// 引数: col*=列, start=数
// 頼み: start~(?<![A-Za-z])([0-9]+)から
// 例: 「番号の列を1から振り直して」 → {"shelf":"renumber","col":"番号"}
// 例: 「行を消したのでNoを2から付け直して」 → {"shelf":"renumber","col":"No","start":2}
// 触る: 値
SHELF['renumber'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col), start = op.start === undefined ? 1 : op.start;
  var n = 0, rowsOut = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var row = t.vals[r - 1].slice(t.firstCol - 1, t.lastCol).filter(function (v, i) { return t.firstCol + i !== ci; });
    var empty = row.every(isBlank_);
    if (empty) { rowsOut.push(['']); continue; }
    rowsOut.push([start + n]); n++;
  }
  if (rowsOut.length) sh.getRange(t.firstData, ci, rowsOut.length, 1).setValues(rowsOut);
  chg_(ctx, sh, a1_(t.firstData, ci, rowsOut.length, 1), '番号を ' + start + ' から振り直し（' + n + ' 件）');
};

// 棚: sort
// 題: 表を並べ替える
// 分類: 絞る
// 語: 並べ替え|並べて|昇順に|降順に|順番に並べ|大きい順|小さい順|高い順|低い順|ソート|あいうえお順|少ない順|多い順|古い順|新しい順
// 違い: 文字・漢字の列の並べ替え（あいうえお順等）もこの棚 1 回で済む（行を手動で動かさない）。条件に合う行だけ見せるなら filter.where（古い filter・where の引数も今までどおり撃てる）
// 引数: col=列, cols=配列, desc=真偽, filter=真偽, where=対応
// 頼み: desc=true<大きい順|多い順|高い順|降順|新しい順|逆順|遅い順 ; desc=false<小さい順|少ない順|低い順|昇順|古い順|五十音順|あいうえお順 ; col~([^\sの]+)の(?:大きい順|小さい順|高い順|低い順|昇順|降順|少ない順|多い順|古い順|新しい順|順に)
// どれか: col cols filter where
// 例: 「金額の大きい順に並べて」 → {"shelf":"sort","col":"金額","desc":true}
// 触る: 値 フィルタ
SHELF['sort'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rng = dataRange_(t);
  var multiCols = op.cols ? (Array.isArray(op.cols) ? op.cols : [op.cols]) : [];
  if (multiCols.length) {
    var specs = multiCols.map(function (item) {
      var colName, isDesc = false;
      if (item && typeof item === 'object') {
        colName = item.col;
        isDesc = !!item.desc;
      } else {
        var s = String(item || '').trim();
        if (s.charAt(0) === '-') { isDesc = true; s = s.slice(1).trim(); }
        else if (/:desc$/i.test(s)) { isDesc = true; s = s.replace(/:desc$/i, '').trim(); }
        else if (/:asc$/i.test(s)) { isDesc = false; s = s.replace(/:asc$/i, '').trim(); }
        colName = s;
      }
      return { column: colIndexOf_(t, colName), ascending: !isDesc, label: colName + (isDesc ? '(降順)' : '(昇順)') };
    });
    rng.sort(specs.map(function (sp) { return { column: sp.column, ascending: sp.ascending }; }));
    chg_(ctx, sh, rng.getA1Notation(), specs.map(function (sp) { return sp.label; }).join('→') + ' で並べ替え');
  } else if (op.col) {
    rng.sort({ column: colIndexOf_(t, op.col), ascending: !op.desc });
    chg_(ctx, sh, rng.getA1Notation(), op.col + ' で' + (op.desc ? '降順' : '昇順') + 'に並べ替え');
  }
  if (op.filter || op.where) {
    var full = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
    var f = sh.getFilter(); if (f) f.remove();
    f = full.createFilter();
    if (op.where) {
      need_(op.where, ['col']);
      var ci = colIndexOf_(t, op.where.col) - t.firstCol + 1;
      var fb = SpreadsheetApp.newFilterCriteria();
      var wh = op.where.when ? String(op.where.when).toLowerCase() : '';
      var wv = op.where.value !== undefined ? op.where.value : op.where.equals;
      var crit;
      if (wh === 'blank') crit = fb.whenCellEmpty().build();
      else if (wh === 'notblank') crit = fb.whenCellNotEmpty().build();
      else if (wh === 'contains') crit = fb.whenTextContains(String(wv !== undefined ? wv : '')).build();
      else if (wh === 'ne') crit = fb.whenTextDoesNotContain(String(wv !== undefined ? wv : '')).build();
      else if (wh === 'gt') crit = fb.whenNumberGreaterThan(Number(wv)).build();
      else if (wh === 'ge') crit = fb.whenNumberGreaterThanOrEqualTo(Number(wv)).build();
      else if (wh === 'lt') crit = fb.whenNumberLessThan(Number(wv)).build();
      else if (wh === 'le') crit = fb.whenNumberLessThanOrEqualTo(Number(wv)).build();
      else if (wh === 'eq' || op.where.equals !== undefined) crit = fb.whenTextEqualTo(String(wv)).build();
      else crit = fb.whenCellNotEmpty().build();
      f.setColumnFilterCriteria(ci, crit);
    }
    chg_(ctx, sh, full.getA1Notation(), 'フィルタを設定');
  }
  if (!op.col && !multiCols.length && !op.filter && !op.where) throw new ArgError('棚「sort」に col・cols・filter のどれかが要ります');
};

// 棚: filter.where
// 題: 条件に合う行だけ表示
// 分類: 絞る
// 語: だけ表示|だけ見せ|だけに絞|行だけ残|絞り込んで|のみ表示|フィルタをかけ|行だけ絞り込|だけ絞り込|以上の行|以下の行|を含む行|空白の行
// 違い: 並べ替えは sort
// 引数: col*=列, equals=文字, when=選択(eq/ne/contains/gt/ge/lt/le/blank/notblank), value=文字
// 頼み: when=ge<以上 ; when=le<以下 ; when=gt<より大|超える|超え ; when=lt<未満|より小 ; when=contains<を含む|含む ; when=blank<空白|空欄 ; when=notblank<空白以外|空欄以外|入力済み ; equals~(?:が|は)[『「]?([^』」]+?)[』」]?の(?:行|人|もの|データ)だけ ; equals~([^\s]+)の行だけ ; col~([^\s]+)(?:が|は)[^\s]+の(?:行|人|もの|データ)だけ
// 例: 「部署が営業の行だけ見せて」 → {"shelf":"filter.where","col":"部署","equals":"営業"}
// 例: 「金額が10000以上の行だけ絞り込んで」 → {"shelf":"filter.where","col":"金額","when":"ge","value":"10000"}
// 触る: 値 フィルタ
SHELF['filter.where'] = function (ctx, op) {
  SHELF['sort'](ctx, { shelf: 'sort', where: { col: op.col, equals: op.equals, when: op.when, value: op.value }, sheet: op.sheet });
};

// 棚: filter.on
// 題: フィルタを付ける
// 分類: 絞る
// 語: フィルタを付|フィルターを付|フィルタをつ|フィルターをつ|フィルタをかけ|フィルターをかけ|フィルタを設定|フィルターを設定|絞り込めるように|見出しに▼|オートフィルタ|オートフィルター
// 違い: 条件で絞り込むなら filter.where、並べ替えなら sort
// 引数: range=範囲
// 例: 「表にフィルタを付けて」 → {"shelf":"filter.on"}
// 例: 「A1からE50にフィルタを設定して」 → {"shelf":"filter.on","range":"A1:E50"}
// 触る: フィルタ
// 控え: 今
SHELF['filter.on'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var full = op.range ? sh.getRange(op.range) : (function () {
    var t = findTable_(sh);
    return t ? sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1) : sh.getDataRange();
  })();
  var f = sh.getFilter(); if (f) f.remove();
  full.createFilter();
  chg_(ctx, sh, full.getA1Notation(), 'フィルタを設定');
};

// 棚: dedupe
// 題: 重複した行を消す
// 分類: 整える
// 語: 重複を削除|重複を消|重複行|ダブりを消|同じ行を消|重複を取り除|重複行を削除|重複している行|重複してる行|ダブってる行|重複した行
// 違い: 全体の整頓なら tidy、空行や全角半角の整理なら seiri、重複に色を付けるだけなら cf.dup。列名が名指しされた重複行削除（「会員番号がダブってる行」「伝票番号が重複」等）は他列の値が違っても確認せず cols 指定・ok=True で即撃つ（列名無しの「ダブってる人を消して」等は聞き返す）
// 引数: cols=列[]
// 頼み: cols~([^\sの]+)が(?:ダブっ|重複) ; cols~([^\sの]+)列が同じ
// 例: 「重複した行を削除して」 → {"shelf":"dedupe"}
// 例: 「メールアドレス列が同じ重複行を消して」 → {"shelf":"dedupe","cols":["メールアドレス"]}
// 危ない: 消す
// 触る: 値
// 控え: 今
SHELF['dedupe'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var colIndices = [];
  if (op.cols) {
    var cols = Array.isArray(op.cols) ? op.cols : [op.cols];
    colIndices = cols.map(function (c) { return colIndexOf_(t, c) - 1; });
  }
  var seen = {}, dups = [];
  for (var d = t.firstData; d <= t.lastData; d++) {
    var row = t.vals[d - 1];
    var key = colIndices.length
      ? JSON.stringify(colIndices.map(function (ci) { return row[ci]; }))
      : JSON.stringify(row.slice(t.firstCol - 1, t.lastCol));
    if (seen[key]) dups.push(d); else seen[key] = 1;
  }
  if (!dups.length) {
    note_(ctx, '重複行はありませんでした（変更なし）');
    return;
  }
  guardDelete_(ctx, (colIndices.length ? '指定列が同じ' : '全列が同じ') + '重複行 ' + dups.join('・') + ' 行目を消します', wideRowCount_(t, dups.length), dups.length + ' 行');
  deleteRowRuns_(sh, dups);
  chg_(ctx, sh, dups.join('・') + ' 行目', '重複行を削除（' + dups.length + ' 行）');
};

// 棚: split.col
// 題: 文字を列に分ける
// 分類: 整える
// 語: 列に分け|列を分割|区切って分|カンマで分|スペースで分|姓と名に分|文字を分割
// 違い: 隣の列を消さず左に空列を入れて分けるなら insert:true。列を挿入するだけなら cols.insert
// 引数: col*=列, by=選択(comma/space/tab/slash/hyphen/custom)=comma, sep=文字, insert=真偽
// 頼み: by=space<スペース|空白 ; by=comma<カンマ|コンマ ; by=slash<スラッシュ ; by=hyphen<ハイフン
// 例: 「氏名列を姓と名にスペースで分けて」 → {"shelf":"split.col","col":"氏名","by":"space"}
// 例: 「住所列をカンマで列に分割して」 → {"shelf":"split.col","col":"住所","by":"comma"}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['split.col'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var by = op.by || 'comma';
  var re;
  if (by === 'comma') re = ',';
  else if (by === 'space') re = /\s+/;
  else if (by === 'tab') re = '\t';
  else if (by === 'slash') re = '/';
  else if (by === 'hyphen') re = '-';
  else if (by === 'custom') re = op.sep !== undefined ? op.sep : ',';
  else throw new ArgError('棚「split.col」の by の値が不正です: ' + by);

  var numRows = t.lastData - t.firstData + 1;
  var colVals = sh.getRange(t.firstData, ci, numRows, 1).getValues();
  var splitRows = [];
  var maxParts = 1;
  for (var r = 0; r < numRows; r++) {
    var str = String(colVals[r][0] !== null && colVals[r][0] !== undefined ? colVals[r][0] : '');
    var parts = (str === '') ? [''] : str.split(re);
    if (parts.length > maxParts) maxParts = parts.length;
    splitRows.push(parts);
  }
  if (maxParts <= 1) {
    note_(ctx, '区切り文字が見つからず、分割されませんでした（変更なし）');
    return;
  }
  var extraCols = maxParts - 1;
  // insert=true のときは右に空列を挿入して上書きを避ける
  if (op.insert) {
    sh.insertColumnsAfter(ci, extraCols);
  } else {
    var checkRg = sh.getRange(t.firstData, ci + 1, numRows, extraCols);
    guardOverwrite_(ctx, checkRg, '分割先「' + checkRg.getA1Notation() + '」');
  }

  var outVals = [];
  for (var i = 0; i < numRows; i++) {
    var p = splitRows[i];
    var row = [];
    for (var j = 0; j < maxParts; j++) {
      row.push(j < p.length ? p[j] : '');
    }
    outVals.push(row);
  }
  sh.getRange(t.firstData, ci, numRows, maxParts).setValues(outVals);
  chg_(ctx, sh, a1_(t.firstData, ci, numRows, maxParts), op.col + '列を ' + maxParts + ' 列に分割');
};

// 棚: filter.off
// 題: フィルタを外す
// 分類: 絞る
// 語: フィルタを外|フィルターを外|オートフィルタを外|オートフィルターを外|フィルタを解除|フィルターを解除|オートフィルタを解除|オートフィルターを解除|絞り込みを解除|フィルタを消|フィルターを消|全部表示に戻|▼を外
// 違い: フィルタを付けるなら filter.on、条件付き書式を外すなら cf.clear
// 引数: なし
// 例: 「フィルタを解除して全部表示に戻して」 → {"shelf":"filter.off"}
// 触る: フィルタ
// 控え: 今
SHELF['filter.off'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var f = sh.getFilter();
  if (f) {
    f.remove();
    chg_(ctx, sh, '', 'フィルタを解除');
  } else {
    note_(ctx, 'フィルタは設定されていません（変更なし）');
  }
};

// 行条件判定の共通ヘルパー（filter.delete / filter.extract で共有）
function matchRowCond_(cellVal, when, target) {
  var w = String(when || '').toLowerCase();
  if (w === 'not_blank') w = 'notblank';
  var blank = isBlank_(cellVal);
  if (w === 'blank') return blank;
  if (w === 'notblank') return !blank;
  var tgtStr = (target !== undefined && target !== null) ? String(target) : '';
  var cellStr = blank ? '' : String(cellVal);
  if (w === 'contains') return cellStr.indexOf(tgtStr) >= 0;
  if (w === 'ne') {
    if (/^-?[\d,]+(\.\d+)?$/.test(tgtStr.trim()) && typeof cellVal === 'number') {
      return cellVal !== Number(tgtStr.replace(/,/g, ''));
    }
    return cellStr !== tgtStr;
  }
  if (w === 'gt' || w === 'ge' || w === 'lt' || w === 'le') {
    var cv = (typeof cellVal === 'number') ? cellVal :
      (typeof cellVal === 'string' && cellVal.trim() !== '' && isFinite(Number(cellVal.replace(/,/g, ''))) ? Number(cellVal.replace(/,/g, '')) : NaN);
    var tv = tgtStr.trim() !== '' && isFinite(Number(tgtStr.replace(/,/g, ''))) ? Number(tgtStr.replace(/,/g, '')) : NaN;
    if (isNaN(cv) || isNaN(tv)) return false;
    if (w === 'gt') return cv > tv;
    if (w === 'ge') return cv >= tv;
    if (w === 'lt') return cv < tv;
    return cv <= tv;
  }
  if (/^-?[\d,]+(\.\d+)?$/.test(tgtStr.trim()) && typeof cellVal === 'number') {
    return cellVal === Number(tgtStr.replace(/,/g, ''));
  }
  return cellStr === tgtStr;
}

// 棚: filter.delete
// 題: 条件に合う行を一括削除する
// 分類: 絞る
// 語: 条件に合う行を消|条件に合う行を削除|条件で削除|の行を消|の行を削除|の行を一括削除|条件削除|一致する行を消|一致する行を削除
// 違い: 消さずに絞り込むだけなら filter.where、行番号指定の削除は rows.delete、重複行削除は dedupe
// 引数: col*=列, equals=文字, when=選択(eq/ne/gt/ge/lt/le/contains/blank/notblank), value=文字
// 頼み: when=ge<以上 ; when=le<以下 ; when=gt<より大|超える|超え ; when=lt<未満|より小 ; when=contains<を含む|含む ; when=blank<空白|空欄 ; when=notblank<空白以外|空欄以外|入力済み ; when=ne<以外|ではない|でない ; value~([0-9][0-9,\.]*)(?:円|個|件|人|点|%)?(?:以上|以下|未満|より|を超|超).*?(?:消|削除) ; value~(?:が|は)[『「]?([^』」\s]+?)[』」]?(?:を含む|含む|以外|ではない|でない).*?(?:消|削除) ; equals~(?:が|は)[『「]?((?:(?!以上|以下|未満|より大|より小|を超|超|を含|含む|以外|ではな|でない|空白|空欄)[^』」\s])+?)[』」]?の(?:行|データ|人)を(?:一括|まとめて)?(?:消|削除) ; col~([^\s、。]+?)(?:が|は)[^\s]+の(?:行|データ|人)を(?:一括|まとめて)?(?:消|削除)
// 例: 「ステータスが完了の行を一括削除して」 → {"shelf":"filter.delete","col":"ステータス","equals":"完了"}
// 例: 「金額が0以下の行を削除して」 → {"shelf":"filter.delete","col":"金額","when":"le","value":"0"}
// 危ない: 消す
// 触る: 値
// 控え: 今
SHELF['filter.delete'] = function (ctx, op) {
  need_(op, ['col']);
  if (!op.when && op.equals === undefined && op.value === undefined) {
    throw new ArgError('棚「filter.delete」に条件（when・equals・value）が要ります');
  }
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var when = op.when ? String(op.when).toLowerCase() : 'eq';
  var target = op.value !== undefined ? op.value : op.equals;
  var hits = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    if (matchRowCond_(t.vals[r - 1][ci - 1], when, target)) hits.push(r);
  }
  if (!hits.length) {
    note_(ctx, '条件に合う行はありませんでした（変更なし）');
    return;
  }
  guardDelete_(ctx, op.col + ' の条件に合う ' + hits.length + ' 行を削除します', wideRowCount_(t, hits.length), hits.length + ' 行');
  deleteRowRuns_(sh, hits);
  chg_(ctx, sh, hits.slice(0, 6).join('・') + (hits.length > 6 ? ' ほか' : '') + ' 行目', '条件一致行を削除（' + hits.length + ' 行）');
};

// 棚: filter.extract
// 題: 条件に合う行を別シートへ抽出する
// 分類: 絞る
// 語: 別シートに抽出|別シートへ抽出|シートに抽出|シートへ抽出|条件で抽出|行を抽出|行だけ抽出|条件に合う行を抽出
// 違い: 元のシートで絞り込むだけなら filter.where、列の値ごとに全分割なら sheet.split、上位N件なら top.n
// 引数: col*=列, equals=文字, when=選択(eq/ne/gt/ge/lt/le/contains/blank/notblank), value=文字, into=文字=抽出
// 頼み: when=ge<以上 ; when=le<以下 ; when=gt<より大|超える|超え ; when=lt<未満|より小 ; when=contains<を含む|含む ; when=blank<空白|空欄 ; when=notblank<空白以外|空欄以外|入力済み ; when=ne<以外|ではない|でない ; value~([0-9][0-9,\.]*)(?:円|個|件|人|点|%)?(?:以上|以下|未満|より|を超|超).*?抽出 ; value~(?:が|は)[『「]?([^』」\s]+?)[』」]?(?:を含む|含む|以外|ではない|でない).*?抽出 ; into~[『「]([^』」]+)[』」](?:シート)?(?:に|へ)抽出 ; into~(?!別)([^\sにへを「『]+?)シート(?:に|へ)抽出 ; equals~(?:が|は)[『「]?((?:(?!以上|以下|未満|より大|より小|を超|超|を含|含む|以外|ではな|でない|空白|空欄)[^』」\s])+?)[』」]?の(?:行|データ|人)を(?:別シート|[^\s]+シート)?(?:に|へ)?抽出 ; col~([^\s、。]+?)(?:が|は)[^\s]+の(?:行|データ|人)を.*抽出
// 例: 「部署が営業の行を別シートに抽出して」 → {"shelf":"filter.extract","col":"部署","equals":"営業","into":"抽出"}
// 触る: シート構成 値
// 控え: 先
SHELF['filter.extract'] = function (ctx, op) {
  need_(op, ['col']);
  if (!op.when && op.equals === undefined && op.value === undefined) {
    throw new ArgError('棚「filter.extract」に条件（when・equals・value）が要ります');
  }
  var ss = ctx.ss, sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var when = op.when ? String(op.when).toLowerCase() : 'eq';
  var target = op.value !== undefined ? op.value : op.equals;
  var nc = t.lastCol - t.firstCol + 1;
  var header = t.vals[t.headerRow - 1].slice(t.firstCol - 1, t.lastCol);
  var rowsOut = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    if (matchRowCond_(t.vals[r - 1][ci - 1], when, target)) {
      rowsOut.push(t.vals[r - 1].slice(t.firstCol - 1, t.lastCol));
    }
  }
  if (!rowsOut.length) {
    note_(ctx, '条件に合う行はありませんでした（抽出していません）');
    return;
  }
  var intoName = String(op.into || '抽出').trim();
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var out = [header].concat(rowsOut);
  dst.getRange(1, 1, out.length, nc).setValues(out);
  dst.getRange(1, 1, 1, nc).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, out.length, nc), rowsOut.length + ' 行を抽出');
};

// 棚: audit.check
// 題: 表のエラー・重複・空欄を診断する
// 分類: 整える
// 語: 表を診断|データを診断|エラーを診断|エラーチェック|品質チェック|表を点検|データを点検|異常をチェック|問題点を診断
// 違い: 実際に修正するなら seiri、重複行を消すなら dedupe、式エラー対策なら formula.guard
// 引数: key_col=列
// 例: 「この表のエラーや重複や空欄を診断して」 → {"shelf":"audit.check"}
// 触る: なし
// 控え: なし
SHELF['audit.check'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  var nc = t.lastCol - t.firstCol + 1;
  if (nr < 1) {
    note_(ctx, '診断対象のデータ行がありません（0 行）');
    return;
  }
  var dr = sh.getRange(t.firstData, t.firstCol, nr, nc);
  var vals = dr.getValues(), forms = dr.getFormulas();
  var headers = headerNames_(t);
  var keyIdx = op.key_col ? (colIndexOf_(t, op.key_col) - t.firstCol) : -1;
  var errs = [], blanksByCol = {}, dupCount = 0, seenKeys = {}, mixedText = [];
  var errPat = /^#(REF!|VALUE!|DIV\/0!|N\/A|NAME\?|NUM!|NULL!|ERROR!)/;

  // 列ごとの数値主体判定を先に集計する
  var numCounts = [], nonEmptyCounts = [];
  for (var c0 = 0; c0 < nc; c0++) { numCounts.push(0); nonEmptyCounts.push(0); }
  for (var r = 0; r < nr; r++) {
    var rowKeyVals = [];
    for (var c = 0; c < nc; c++) {
      var v = vals[r][c];
      if (!isBlank_(v)) {
        nonEmptyCounts[c]++;
        if (typeof v === 'number') numCounts[c]++;
      } else {
        blanksByCol[headers[c] || colLetter_(t.firstCol + c)] = (blanksByCol[headers[c] || colLetter_(t.firstCol + c)] || 0) + 1;
      }
      if (typeof v === 'string' && errPat.test(v)) {
        errs.push(a1_(t.firstData + r, t.firstCol + c) + ':' + v);
      }
      rowKeyVals.push(v);
    }
    var kStr = keyIdx >= 0 ? String(vals[r][keyIdx]) : JSON.stringify(rowKeyVals);
    if (keyIdx < 0 || !isBlank_(vals[r][keyIdx])) {
      if (seenKeys[kStr]) dupCount++; else seenKeys[kStr] = 1;
    }
  }
  for (var c2 = 0; c2 < nc; c2++) {
    if (nonEmptyCounts[c2] >= 2 && numCounts[c2] / nonEmptyCounts[c2] > 0.5) {
      for (var r2 = 0; r2 < nr; r2++) {
        var v2 = vals[r2][c2];
        if (!forms[r2][c2] && typeof v2 === 'string' && v2.trim() !== '' && !errPat.test(v2)) {
          mixedText.push(a1_(t.firstData + r2, t.firstCol + c2) + '「' + v2 + '」');
        }
      }
    }
  }

  var lines = ['診断結果（' + sh.getName() + ' / データ ' + nr + ' 行 × ' + nc + ' 列）:'];
  lines.push('・エラー値: ' + (errs.length ? (errs.length + ' 件（' + errs.slice(0, 8).join(', ') + (errs.length > 8 ? ' ほか' : '') + '）') : '0 件'));
  lines.push('・重複行' + (keyIdx >= 0 ? '（' + op.key_col + '基準）' : '') + ': ' + dupCount + ' 件');
  var blankParts = Object.keys(blanksByCol).map(function (k) { return k + '=' + blanksByCol[k]; });
  lines.push('・空欄セル: ' + (blankParts.length ? blankParts.join('、') : 'なし'));
  lines.push('・数値列内の文字混入: ' + (mixedText.length ? (mixedText.length + ' 件（' + mixedText.slice(0, 8).join(', ') + (mixedText.length > 8 ? ' ほか' : '') + '）') : '0 件'));
  note_(ctx, lines.join('\n'));
};

// 棚: top.n
// 題: 上位N件・下位N件を抽出する
// 分類: 集計
// 語: 上位を抽出|上位だけ抽出|トップを抽出|下位を抽出|ワーストを抽出|ベストを抽出|上位何件|上位抽出|下位抽出|上位5件|上位10件|トップ5|トップ10
// 違い: 元の表を並べ替えるだけなら sort、条件一致抽出なら filter.extract
// 引数: col*=列, count=数=5, bottom=真偽=false, into=文字=上位抽出
// 頼み: bottom=true<下位|ワースト|少ない方|小さい方|低い方 ; count~(?:上位|下位|トップ|ワースト|ベスト)\s*([0-9]+)\s*(?:件|名|社|人|位|個|行)? ; into~[『「]([^』」]+)[』」](?:シート)?(?:に|へ)抽出 ; into~(?!別)([^\sにへを「『]+?)シート(?:に|へ)抽出 ; col~([^\sの、。]+?)(?:列)?の(?:上位|下位|トップ|ワースト|ベスト)
// 例: 「金額の上位5件を別シートに抽出して」 → {"shelf":"top.n","col":"金額","count":5}
// 触る: シート構成 値
// 控え: 先
SHELF['top.n'] = function (ctx, op) {
  need_(op, ['col']);
  var ss = ctx.ss, sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var cnt = Math.max(1, parseInt(op.count, 10) || 5);
  var nc = t.lastCol - t.firstCol + 1;
  var header = t.vals[t.headerRow - 1].slice(t.firstCol - 1, t.lastCol);
  var items = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var raw = t.vals[r - 1][ci - 1];
    var num = NaN;
    if (typeof raw === 'number') num = raw;
    else if (typeof raw === 'string' && raw.trim() !== '') {
      var cleaned = raw.replace(/[¥￥$,\s]/g, '');
      if (/^-?\d+(\.\d+)?$/.test(cleaned)) num = Number(cleaned);
    }
    if (!isNaN(num)) {
      items.push({ idx: r, val: num, row: t.vals[r - 1].slice(t.firstCol - 1, t.lastCol) });
    }
  }
  if (!items.length) {
    note_(ctx, op.col + '列に数値データがありません（抽出していません）');
    return;
  }
  items.sort(function (a, b) {
    if (op.bottom) return a.val !== b.val ? (a.val - b.val) : (a.idx - b.idx);
    return a.val !== b.val ? (b.val - a.val) : (a.idx - b.idx);
  });
  var picked = items.slice(0, cnt).map(function (x) { return x.row; });
  var intoName = String(op.into || (op.bottom ? '下位抽出' : '上位抽出')).trim();
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var out = [header].concat(picked);
  dst.getRange(1, 1, out.length, nc).setValues(out);
  dst.getRange(1, 1, 1, nc).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, out.length, nc), op.col + ' の' + (op.bottom ? '下位' : '上位') + picked.length + '件を抽出');
};
