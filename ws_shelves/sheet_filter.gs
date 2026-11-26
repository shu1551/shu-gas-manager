// 絞る・整える棚（整える手伝い tidyRange_ もここ）

// 速い版：書式・幅・固定を Sheets API の batchUpdate 1 回にまとめる（セルごとの呼び出しをやめる）。失敗したら従来の版（tidyRangeLegacy_）でやり直す
function hexColor_(h) { return { red: parseInt(h.substr(1, 2), 16) / 255, green: parseInt(h.substr(3, 2), 16) / 255, blue: parseInt(h.substr(5, 2), 16) / 255 }; }
function tidyNumText_(v, dec) {
  var s = Math.abs(v).toFixed(dec ? 2 : 0), p = s.split('.');
  p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (v < 0 ? '-' : '') + p.join('.');
}
function filterSpanOf_(sh) {
  try {
    var f = (typeof sh.getFilter === 'function') ? sh.getFilter() : null;
    if (!f) return null;
    var rg = f.getRange();
    return { row: rg.getRow(), c1: rg.getColumn(), c2: rg.getLastColumn() };
  } catch (e) { return null; }
}
// 文字列の日付（2026-11-01 / 2026/11/1 / 2026年11月1日 / 2026.11.01）を本物の Date に直す
function parseDateText_(s) {
  var m = /^(\d{4})[\/\-\.年](\d{1,2})[\/\-\.月](\d{1,2})日?$/.exec(s);
  if (!m) return null;
  var y = parseInt(m[1], 10), mo = parseInt(m[2], 10), d = parseInt(m[3], 10);
  if (y < 1900 || y > 2100 || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  var dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return dt;
}
// 列ごとの書式・配置・折り返しを、見出し名・値の型・既存書式から自動判定する
function tidyColSpec_(headName, vals, existingFmts, isNoCol) {
  var h = String(headName || '').trim();
  if (isNoCol) return { fmt: null, fmtType: null, align: 'center', wrap: false, kind: null };
  var nums = vals.filter(function (v) { return typeof v === 'number'; });
  var dates = vals.filter(function (v) { return Object.prototype.toString.call(v) === '[object Date]'; });
  var nonEmptyList = vals.filter(function (v) { return !isBlank_(v); });
  var nonEmpty = nonEmptyList.length;
  var fmtSample = (existingFmts || []).filter(function (f) { return f && f !== 'General' && f !== '@'; });
  var hasPctFmt = fmtSample.length > 0 && fmtSample.filter(function (f) { return f.indexOf('%') >= 0; }).length / fmtSample.length > 0.5;
  var hasCurFmt = fmtSample.length > 0 && fmtSample.filter(function (f) { return /[¥￥]/.test(f); }).length / fmtSample.length > 0.5;

  if (nonEmpty && nums.length / nonEmpty > 0.5) {
    var hasNeg = nums.some(function (v) { return v < 0; });
    var isPctHead = /(?:率|割合|構成比|達成|進捗|％|%)/.test(h) && nums.filter(function (v) { return Math.abs(v) <= 2; }).length / nums.length > 0.5;
    if (hasPctFmt || isPctHead) {
      return { fmt: hasNeg ? '0.0%;[Red]-0.0%' : '0.0%', fmtType: 'PERCENT', align: 'right', wrap: false, kind: 'pct' };
    }
    var dec = nums.some(function (v) { return v % 1 !== 0; });
    if (hasCurFmt) {
      var cBase = dec ? '¥#,##0.00' : '¥#,##0';
      return { fmt: hasNeg ? (cBase + ';[Red]-' + cBase) : cBase, fmtType: 'CURRENCY', align: 'right', wrap: false, kind: dec ? 'cur_dec' : 'cur' };
    }
    var nBase = dec ? STYLE.numFmtDec : STYLE.numFmt;
    return { fmt: hasNeg ? (nBase + ';[Red]-' + nBase) : nBase, fmtType: 'NUMBER', align: 'right', wrap: false, kind: dec ? 'dec' : 'int' };
  }
  if (nonEmpty && dates.length / nonEmpty > 0.5) {
    return { fmt: STYLE.dateFmt, fmtType: 'DATE', align: 'center', wrap: false, kind: 'date' };
  }
  // 文字列列：ID/コード/区分/ステータス系は中央寄せ、備考/長文は左寄せ＋折り返し
  var strList = nonEmptyList.map(function (v) { return String(v).trim(); });
  var isCodeHead = /^(?:No\.?|NO|番号|ID|コード|区分|状態|ステータス|判定|結果|出欠|性別|曜日|ランク|評価|フラグ|承認|有無)$/i.test(h);
  if (isCodeHead || (strList.length >= 2 && strList.every(function (s) { return wlen_(s) <= 4 && s.indexOf('\n') < 0; }))) {
    return { fmt: null, fmtType: null, align: 'center', wrap: false, kind: null };
  }
  var avgLen = strList.length ? strList.reduce(function (a, s) { return a + wlen_(s); }, 0) / strList.length : 0;
  var isNoteHead = /(?:備考|メモ|内容|説明|コメント|詳細|住所|理由)/.test(h);
  if (isNoteHead || avgLen >= 28) {
    return { fmt: null, fmtType: null, align: 'left', wrap: true, kind: null };
  }
  return { fmt: null, fmtType: null, align: 'left', wrap: false, kind: null };
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
    var colFmt = {}, hasWrapCol = false;   // 列ごとの書式（幅の見積もり・行高さ判定に使う）
    if (t.lastData - t.firstData + 1 >= 1) {
      var rows = (t.totalRow ? t.totalRow : t.lastData) - t.firstData + 1;
      var existFmts = sh.getRange(t.firstData, t.firstCol, t.lastData - t.firstData + 1, nc).getNumberFormats();
      for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
        var kCol = ci - t.firstCol, vals = [], fCol = [];
        for (var rr = t.firstData; rr <= t.lastData; rr++) {
          vals.push(t.vals[rr - 1][ci - 1]);
          fCol.push(existFmts[rr - t.firstData] ? existFmts[rr - t.firstData][kCol] : '');
        }
        var headNm = t.vals[t.headerRow - 1] ? t.vals[t.headerRow - 1][ci - 1] : '';
        var spec = tidyColSpec_(headNm, vals, fCol, isNoCol_(t, ci));
        colFmt[ci] = spec.kind;
        if (spec.wrap) hasWrapCol = true;
        var uf = {}, fl = [];
        if (spec.fmt) { uf.numberFormat = { type: spec.fmtType || 'NUMBER', pattern: spec.fmt }; fl.push('numberFormat'); }
        if (spec.align) { uf.horizontalAlignment = spec.align.toUpperCase(); fl.push('horizontalAlignment'); }
        if (spec.wrap) { uf.wrapStrategy = 'WRAP'; fl.push('wrapStrategy'); }
        if (fl.length) reqs.push({ repeatCell: { range: grid(t.firstData, t.firstData + rows - 1, ci, ci), cell: { userEnteredFormat: uf }, fields: 'userEnteredFormat(' + fl.join(',') + ')' } });
      }
    }
    if (t.totalRow) {
      var bdTop = { style: 'DOUBLE', color: hexColor_('#595959') };
      reqs.push({ repeatCell: { range: grid(t.totalRow, t.totalRow, t.firstCol, t.lastCol), cell: { userEnteredFormat: { backgroundColor: hexColor_(STYLE.totalBg), textFormat: { bold: true } } }, fields: 'userEnteredFormat(backgroundColor,textFormat(bold))' } });
      reqs.push({ updateBorders: { range: grid(t.totalRow, t.totalRow, t.firstCol, t.lastCol), top: bdTop } });
    }
    // タイトル行の自動仕上げ（見出しの上に単一タイトルがあり 12pt 以下なら太字 14pt に引き上げる）
    if (t.headerRow > 1) {
      try {
        var tRg = titleRange_(sh);
        if (tRg && tRg.getRow() < t.headerRow) {
          var curSz = tRg.getFontSize();
          if (!curSz || curSz <= 12) {
            reqs.push({ repeatCell: { range: grid(tRg.getRow(), tRg.getLastRow(), tRg.getColumn(), tRg.getLastColumn()), cell: { userEnteredFormat: { textFormat: { bold: true, fontSize: 14 } } }, fields: 'userEnteredFormat.textFormat(bold,fontSize)' } });
          }
        }
      } catch (eTitle) { }
    }
    // 行高さの最適化（見出し 28px・データ行 24px（長文折り返し列が無いとき）・合計行 26px）
    reqs.push({ updateDimensionProperties: { range: { sheetId: sid, dimension: 'ROWS', startIndex: t.headerRow - 1, endIndex: t.headerRow }, properties: { pixelSize: 28 }, fields: 'pixelSize' } });
    if (!hasWrapCol && t.lastData >= t.firstData) {
      reqs.push({ updateDimensionProperties: { range: { sheetId: sid, dimension: 'ROWS', startIndex: t.firstData - 1, endIndex: t.lastData }, properties: { pixelSize: 24 }, fields: 'pixelSize' } });
    }
    if (t.totalRow) {
      reqs.push({ updateDimensionProperties: { range: { sheetId: sid, dimension: 'ROWS', startIndex: t.totalRow - 1, endIndex: t.totalRow }, properties: { pixelSize: 26 }, fields: 'pixelSize' } });
    }
    // 列幅：中身に合わせる。数値・日付は、これから付ける書式で表示される形に見積もる（フィルター付き見出しは▼アイコン分を足す）
    var disp = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc).getDisplayValues();
    var flSpan = filterSpanOf_(sh);
    for (var c = 0; c < nc; c++) {
      var colIdx = t.firstCol + c, k = colFmt[colIdx], mx = 0;
      disp.forEach(function (row, ri) {
        var s = row[c], v = t.vals[t.headerRow - 1 + ri][t.firstCol - 1 + c];
        if (k && ri > 0) {
          if (k === 'date' && Object.prototype.toString.call(v) === '[object Date]') s = '0000/00/00';
          else if (k === 'pct' && typeof v === 'number') s = (v * 100).toFixed(1) + '%';
          else if ((k === 'cur' || k === 'cur_dec') && typeof v === 'number') s = '¥' + tidyNumText_(v, k === 'cur_dec');
          else if ((k === 'int' || k === 'dec') && typeof v === 'number') s = tidyNumText_(v, k === 'dec');
        }
        mx = Math.max(mx, wlen_(s));
      });
      var wantPx = mx * STYLE.px + STYLE.pad;
      if (flSpan && flSpan.row === t.headerRow && colIdx >= flSpan.c1 && colIdx <= flSpan.c2) {
        wantPx = Math.max(wantPx, wlen_(disp[0][c]) * STYLE.px + STYLE.pad + 42);
      }
      reqs.push({ updateDimensionProperties: { range: { sheetId: sid, dimension: 'COLUMNS', startIndex: colIdx - 1, endIndex: colIdx }, properties: { pixelSize: Math.max(STYLE.colMin, Math.min(STYLE.colMax, wantPx)) }, fields: 'pixelSize' } });
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
  var cnt = t.lastData - t.firstData + 1, hasWrapColL = false;
  if (cnt >= 1) {
    // 表の値は findTable_ が 1 回で読んだもの（t.vals）を使う。書式は範囲ごとの配列で一括して書く
    var rows = (t.totalRow ? t.totalRow : t.lastData) - t.firstData + 1;
    var bodyRg = sh.getRange(t.firstData, t.firstCol, rows, nc);
    var nf = bodyRg.getNumberFormats(), al = bodyRg.getHorizontalAlignments(), wr = bodyRg.getWraps();
    for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
      var k = ci - t.firstCol, vals = [], fColL = [];
      for (var r = t.firstData; r <= t.lastData; r++) {
        vals.push(t.vals[r - 1][ci - 1]);
        fColL.push(nf[r - t.firstData] ? nf[r - t.firstData][k] : '');
      }
      var headNmL = t.vals[t.headerRow - 1] ? t.vals[t.headerRow - 1][ci - 1] : '';
      var specL = tidyColSpec_(headNmL, vals, fColL, isNoCol_(t, ci));
      if (specL.wrap) hasWrapColL = true;
      for (var rr = 0; rr < rows; rr++) {
        if (specL.fmt) nf[rr][k] = specL.fmt;
        if (specL.align) al[rr][k] = specL.align;
        if (specL.wrap) wr[rr][k] = true;
      }
    }
    bodyRg.setNumberFormats(nf).setHorizontalAlignments(al);
    if (hasWrapColL && typeof bodyRg.setWraps === 'function') bodyRg.setWraps(wr);
  }
  if (t.totalRow) {
    var totRg = sh.getRange(t.totalRow, t.firstCol, 1, nc);
    totRg.setFontWeight('bold').setBackground(STYLE.totalBg);
    try { totRg.setBorder(true, null, null, null, null, null, '#595959', SpreadsheetApp.BorderStyle.DOUBLE); } catch (eBd) { }
  }
  if (t.headerRow > 1) {
    try {
      var tRgL = titleRange_(sh);
      if (tRgL && tRgL.getRow() < t.headerRow) {
        var curSzL = tRgL.getFontSize();
        if (!curSzL || curSzL <= 12) tRgL.setFontWeight('bold').setFontSize(14);
      }
    } catch (eTL) { }
  }
  if (typeof sh.setRowHeight === 'function') {
    try {
      sh.setRowHeight(t.headerRow, 28);
      if (!hasWrapColL && t.lastData >= t.firstData) sh.setRowHeights(t.firstData, t.lastData - t.firstData + 1, 24);
      if (t.totalRow) sh.setRowHeight(t.totalRow, 26);
    } catch (eRh) { }
  }
  // 列幅：中身に合わせる（上限・下限つき・フィルター付き見出しは▼アイコン分を足す）
  var disp = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc).getDisplayValues();
  var flSpanL = filterSpanOf_(sh);
  for (var c = 0; c < nc; c++) {
    var colIdxL = t.firstCol + c, mx = 0;
    disp.forEach(function (row) { mx = Math.max(mx, wlen_(row[c])); });
    var wantPxL = mx * STYLE.px + STYLE.pad;
    if (flSpanL && flSpanL.row === t.headerRow && colIdxL >= flSpanL.c1 && colIdxL <= flSpanL.c2) {
      wantPxL = Math.max(wantPxL, wlen_(disp[0][c]) * STYLE.px + STYLE.pad + 42);
    }
    sh.setColumnWidth(colIdxL, Math.max(STYLE.colMin, Math.min(STYLE.colMax, wantPxL)));
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
// 引数: trim=真偽, halfwidth=真偽, numbers=真偽, dates=真偽, blank_rows=真偽, dedupe=真偽, renumber=列, tidy=真偽
// 頼み: blank_rows=true<空行|空いている行 ; dedupe=true<重複 ; halfwidth=true<全角
// 例: 「全角の数字を半角に直して」 → {"shelf":"seiri"}
// 例: 「空行を詰めて重複行も消して」 → {"shelf":"seiri","blank_rows":true,"dedupe":true}
// 危ない: 消す
// 触る: 値 書式 幅 固定
SHELF['seiri'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rg = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
  var vals = rg.getValues(), forms = rg.getFormulas(), fixed = [], nTrim = 0, nHalf = 0, nNum = 0, nDate = 0;
  var doTrim = op.trim !== false, doHalf = op.halfwidth !== false, doNum = op.numbers !== false, doDate = op.dates !== false;
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    var v = vals[r][c];
    if (forms[r][c] || typeof v !== 'string') continue;
    var nv = v;
    if (doHalf) { var h = nv.replace(/[！-～]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); }).replace(/　/g, ' '); if (h !== nv) { nv = h; nHalf++; } }
    if (doTrim) { var tr = nv.replace(/^[\s　]+|[\s　]+$/g, ''); if (tr !== nv) { nv = tr; nTrim++; } }
    if (doNum && r > 0 && /^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(nv) && !/^-?0\d/.test(nv)) { nv = Number(nv.replace(/,/g, '')); nNum++; }
    else if (doDate && r > 0 && typeof nv === 'string') { var dt = parseDateText_(nv); if (dt) { nv = dt; nDate++; } }
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
    chg_(ctx, sh, fixed.slice(0, 4).join('・') + (fixed.length > 4 ? ' ほか' + (fixed.length - 4) + ' 件' : ''), '空白' + nTrim + '・全角→半角' + nHalf + '・数値化' + nNum + (nDate ? '・日付化' + nDate : ''));
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
// 語: 並べ替え|並べて|昇順に|降順に|順番に並べ|大きい順|小さい順|高い順|低い順|ソート|あいうえお順|少ない順|多い順|古い順|新しい順|かためて並べ|ごとに並べ|同部署内
// 違い: 文字・漢字の列の並べ替え（あいうえお順等）もこの棚 1 回で済む（行を手動で動かさない）。条件に合う行だけ見せるなら filter.where（古い filter・where の引数も今までどおり撃てる）
// 引数: col=列, cols=配列, desc=真偽, filter=真偽, where=対応
// 頼み: desc=true<大きい順|多い順|高い順|降順|新しい順|逆順|遅い順 ; desc=false<小さい順|少ない順|低い順|昇順|古い順|五十音順|あいうえお順|若い順 ; col~([^\sの]+)の(?:大きい順|小さい順|高い順|低い順|昇順|降順|少ない順|多い順|古い順|新しい順|若い順|順に)
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
      var absCi = colIndexOf_(t, op.where.col);
      var ci = absCi - t.firstCol + 1;
      var fb = SpreadsheetApp.newFilterCriteria();
      var wh = op.where.when ? String(op.where.when).toLowerCase() : '';
      var wv = op.where.value !== undefined ? op.where.value : op.where.equals;
      var wvStr = String(wv !== undefined && wv !== null ? wv : '');
      var wvNumStr = wvStr.replace(/,/g, '').trim();
      var isNumWv = wvNumStr !== '' && isFinite(Number(wvNumStr));
      var crit;
      if (wh === 'blank') crit = fb.whenCellEmpty().build();
      else if (wh === 'notblank') crit = fb.whenCellNotEmpty().build();
      else if (wh === 'contains') crit = fb.whenTextContains(wvStr).build();
      else if (wh === 'ne') {
        if (wvStr === '') crit = fb.whenCellNotEmpty().build();
        else if (isNumWv && typeof fb.whenNumberNotEqualTo === 'function') crit = fb.whenNumberNotEqualTo(Number(wvNumStr)).build();
        else if (isNumWv) crit = fb.whenFormulaSatisfied('=' + colLetter_(absCi) + t.firstData + '<>' + Number(wvNumStr)).build();
        else crit = fb.whenFormulaSatisfied('=' + colLetter_(absCi) + t.firstData + '<>"' + wvStr.replace(/"/g, '""') + '"').build();
      }
      else if (wh === 'gt') crit = fb.whenNumberGreaterThan(Number(wvNumStr)).build();
      else if (wh === 'ge') crit = fb.whenNumberGreaterThanOrEqualTo(Number(wvNumStr)).build();
      else if (wh === 'lt') crit = fb.whenNumberLessThan(Number(wvNumStr)).build();
      else if (wh === 'le') crit = fb.whenNumberLessThanOrEqualTo(Number(wvNumStr)).build();
      else if (wh === 'eq' || op.where.equals !== undefined) {
        if (isNumWv && typeof fb.whenNumberEqualTo === 'function') crit = fb.whenNumberEqualTo(Number(wvNumStr)).build();
        else crit = fb.whenTextEqualTo(wvStr).build();
      }
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
// 語: だけ表示|だけ見せ|だけ出して|ものだけ|だけに絞|行だけ残|絞り込んで|のみ表示|フィルタをかけ|行だけ絞り込|だけ絞り込|以上の行|以下の行|を含む行|空白の行|を超えている|超えてる|絞り込み|フィルタ 表示
// 違い: 並べ替えは sort
// 引数: col*=列, equals=文字, when=選択(eq/ne/contains/gt/ge/lt/le/blank/notblank), value=文字
// 頼み: when=ge<以上 ; when=le<以下 ; when=gt<より大|超える|超え ; when=lt<未満|より小 ; when=contains<を含む|含む ; when=blank<空白|空欄 ; when=notblank<空白以外|空欄以外|入力済み ; value~([0-9][0-9,\.]*%?[万億]?)(?:円|個|件|人|時間|点)?(?:以上|以下|未満|より|を超|超) ; equals~(?:が|は)[『「]?([^』」]+?)[』」]?の(?:行|人|もの|データ)だけ ; equals~([^\s]+)の行だけ ; col~([^\s]+)(?:が|は)[^\s]+の(?:行|人|もの|データ)だけ
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
// 語: 重複を削除|重複を消|重複行|ダブりを消|同じ行を消|重複を取り除|重複行を削除|重複している行|重複してる行|ダブってる行|重複した行|同じ行がダブ|ダブっているのを取り除|重複を取り除いて
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
    if (ci + extraCols > sh.getMaxColumns()) {
      sh.insertColumnsAfter(sh.getMaxColumns(), (ci + extraCols) - sh.getMaxColumns());
    }
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
// 語: 上位を抽出|上位だけ抽出|トップを抽出|下位を抽出|ワーストを抽出|ベストを抽出|上位何件|上位抽出|下位抽出|上位5件|上位10件|トップ5|トップ10|上位を別シート|上位を抽出して
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

// 棚: rows.trim
// 題: 余分な空行・空列を削ってシートを軽くする
// 分類: 整える
// 語: 余分な空行|不要な空行|空行を削っ|末尾の空行|シートを軽く|空列を削|余白の行|下まで続く空行
// 違い: 表の途中の空行を詰めるなら blank.rows.delete。シートの削除なら sheet.delete
// 引数: keep_rows=数=5, keep_cols=数=2
// 例: 「下の余分な空行と空列を削ってシートを軽くして」 → {"shelf":"rows.trim"}
// 触る: シート構成
// 控え: 今
SHELF['rows.trim'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var keepR = op.keep_rows !== undefined ? Math.max(0, parseInt(op.keep_rows, 10) || 0) : 5;
  var keepC = op.keep_cols !== undefined ? Math.max(0, parseInt(op.keep_cols, 10) || 0) : 2;
  var lr = Math.max(1, sh.getLastRow()), lc = Math.max(1, sh.getLastColumn());
  var mr = sh.getMaxRows(), mc = sh.getMaxColumns();
  var wantR = Math.min(mr, lr + keepR);
  var wantC = Math.min(mc, lc + keepC);
  var msgs = [];
  if (mr > wantR) {
    sh.deleteRows(wantR + 1, mr - wantR);
    msgs.push('空行 ' + (mr - wantR) + ' 行削除');
  }
  if (mc > wantC) {
    sh.deleteColumns(wantC + 1, mc - wantC);
    msgs.push('空列 ' + (mc - wantC) + ' 列削除');
  }
  if (!msgs.length) {
    note_(ctx, '削る余分な空行・空列はありませんでした（変更なし）');
    return;
  }
  chg_(ctx, sh, '', msgs.join('・'));
};

// 棚: blank.rows.delete
// 題: 表の途中の空行を一括削除する
// 分類: 整える
// 語: 空行を削除|空行を詰め|空行を消|空白行を消|空白の行を消|途中の空行|空いている行を消|空き行を消
// 違い: 見た目整えまでまとめてやるなら seiri。シート末尾の大量空行を軽くするなら rows.trim
// 引数: なし
// 例: 「表の途中の空行を一括で詰めて」 → {"shelf":"blank.rows.delete"}
// 危ない: 消す
// 触る: 値
// 控え: 今
SHELF['blank.rows.delete'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var blanks = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var row = t.vals[r - 1].slice(t.firstCol - 1, t.lastCol);
    if (row.every(isBlank_)) blanks.push(r);
  }
  if (!blanks.length) {
    note_(ctx, '表の途中に空行はありませんでした（変更なし）');
    return;
  }
  guardDelete_(ctx, '表内の空行 ' + blanks.slice(0, 6).join('・') + (blanks.length > 6 ? ' ほか' : '') + ' 行目を削除します', wideRowCount_(t, blanks.length), blanks.length + ' 行');
  deleteRowRuns_(sh, blanks);
  chg_(ctx, sh, blanks.slice(0, 6).join('・') + (blanks.length > 6 ? ' ほか' : '') + ' 行目', '空行を一括削除（' + blanks.length + ' 行）');
};

// 棚: text.clean
// 題: セル内の改行・連続空白・不可視文字を掃除する
// 分類: 整える
// 語: セル内改行|改行を消|改行をスペース|連続空白|余分なスペース|不可視文字|ゴミ文字を消|テキストを掃除
// 違い: 表全体を整えるなら seiri。特定文字の置き換えは replace
// 引数: col=列, range=範囲, newline=文字
// 例: 「備考列のセル内改行と連続空白を掃除して」 → {"shelf":"text.clean","col":"備考"}
// 触る: 値
// 控え: 今
SHELF['text.clean'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = dataRange_(needTable_(sh));
  }
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  var nlRepl = op.newline !== undefined ? String(op.newline) : ' ';
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) { vals[r][c] = f; continue; }
      if (typeof v !== 'string') continue;
      var cleaned = v
        .replace(/[\u200B-\u200D\uFEFF\u00AD\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
        .replace(/\r?\n/g, nlRepl)
        .replace(/[ \t\u3000]+/g, ' ')
        .trim();
      if (cleaned !== v) {
        vals[r][c] = cleaned;
        changed++;
      }
    }
  }
  if (!changed) {
    note_(ctx, '掃除が必要な文字列はありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '改行・連続空白・不可視文字を掃除（' + changed + ' 件）');
};

// 棚: zero.pad
// 題: コードや番号の先頭を0埋めして桁をそろえる
// 分類: 整える
// 語: ゼロ埋め|ゼロパディング|先頭に0|前ゼロ|先頭0|桁数をそろ|桁をそろ|0を補う
// 違い: 連番を書くなら fill.series、表示形式のみ変えるなら format
// 引数: col=列, range=範囲, digits*=数=5
// 頼み: digits~([0-9]+)\s*桁
// 例: 「社員コード列を5桁で先頭0埋めして」 → {"shelf":"zero.pad","col":"社員コード","digits":5}
// 触る: 値 書式
// 控え: 今
SHELF['zero.pad'] = function (ctx, op) {
  need_(op, ['digits']);
  var digits = Math.max(1, Math.min(20, parseInt(op.digits, 10) || 5));
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = dataRange_(needTable_(sh));
  }
  var vals = rg.getValues(), forms = rg.getFormulas(), fmts = rg.getNumberFormats(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) { vals[r][c] = f; continue; }
      if (isBlank_(v)) continue;
      var s = (typeof v === 'number' && isFinite(v) && v >= 0 && Math.floor(v) === v)
        ? String(v)
        : (typeof v === 'string' ? v.trim() : '');
      if (!s || !/^\d+$/.test(s)) continue;
      var padded = s;
      while (padded.length < digits) padded = '0' + padded;
      if (v !== padded || fmts[r][c] !== '@') {
        vals[r][c] = padded;
        fmts[r][c] = '@';
        changed++;
      }
    }
  }
  if (!changed) {
    note_(ctx, '0埋め対象の数値・数字はありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setNumberFormats(fmts);
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), digits + ' 桁で先頭0埋め（' + changed + ' 件）');
};

// 棚: rows.sample
// 題: ランダムにN件を別シートへ抽出する
// 分類: 絞る
// 語: ランダム抽出|無作為抽出|サンプル抽出|ランダムに選|ランダムに行|ランダムに何件|ランダム抜き出
// 違い: 上位・下位N件なら top.n。条件指定の抽出なら filter.extract
// 引数: count*=数=10, into=文字=抽出サンプル
// 頼み: count~(?:ランダム|無作為|サンプル).*?([0-9]+)\s*(?:件|行|名|社)
// 例: 「データからランダムに10件を抽出して」 → {"shelf":"rows.sample","count":10}
// 触る: シート構成 値 書式
// 控え: 先
SHELF['rows.sample'] = function (ctx, op) {
  need_(op, ['count']);
  var ss = ctx.ss, sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  if (nr < 1) { note_(ctx, '抽出元のデータ行がありません'); return; }
  var cnt = Math.max(1, parseInt(op.count, 10) || 10);
  var take = Math.min(cnt, nr);
  var idxs = [];
  for (var i = 0; i < nr; i++) idxs.push(i);
  for (var j = nr - 1; j > 0; j--) {
    var k = Math.floor(Math.random() * (j + 1));
    var tmp = idxs[j]; idxs[j] = idxs[k]; idxs[k] = tmp;
  }
  var nc = t.lastCol - t.firstCol + 1;
  var head = sh.getRange(t.headerRow, t.firstCol, 1, nc).getValues()[0];
  var body = sh.getRange(t.firstData, t.firstCol, nr, nc).getValues();
  var out = [head];
  for (var p = 0; p < take; p++) out.push(body[idxs[p]]);
  var intoName = String(op.into || '抽出サンプル').trim() || '抽出サンプル';
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  dst.getRange(1, 1, out.length, nc).setValues(out);
  tidyRange_(ctx, dst, a1_(1, 1, out.length, nc));
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, out.length, nc), 'ランダム抽出 ' + take + ' 件（元 ' + nr + ' 行）');
};

// 棚: split.rows
// 題: セル内の複数値を縦の行へ展開する
// 分類: 整える
// 語: 行に分割|縦に展開|改行で行を分け|カンマで行を分け|複数値を縦に分け|1行1件に展開|行へ展開
// 違い: 横の列に分割するなら split.col。結合解除なら merge.unmerge
// 引数: col*=列, sep=文字
// 頼み: sep~[「『"“]([^」』"”]+)[」』"”]で(?:行に分割|縦に展開|展開)
// 例: 「担当列のカンマ区切りを縦の行へ展開して」 → {"shelf":"split.rows","col":"担当"}
// 危ない: 上書き
// 触る: 値 書式
// 控え: 今
SHELF['split.rows'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  if (nr < 1) { note_(ctx, '対象のデータ行がありません'); return; }
  var nc = t.lastCol - t.firstCol + 1, relC = ci - t.firstCol;
  var dr = sh.getRange(t.firstData, t.firstCol, nr, nc);
  var vals = dr.getValues(), forms = dr.getFormulas();
  var sepRx = op.sep
    ? new RegExp(String(op.sep).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    : /[\r\n,、/／]+/;
  var expanded = [], splitCnt = 0;
  for (var r = 0; r < nr; r++) {
    var baseRow = [];
    for (var c = 0; c < nc; c++) baseRow.push(forms[r][c] ? forms[r][c] : vals[r][c]);
    var rawCell = vals[r][relC];
    if (forms[r][relC] || typeof rawCell !== 'string' || !rawCell.trim()) {
      expanded.push(baseRow);
      continue;
    }
    var parts = rawCell.split(sepRx).map(function (x) { return x.trim(); }).filter(function (x) { return x !== ''; });
    if (parts.length <= 1) {
      expanded.push(baseRow);
      continue;
    }
    splitCnt++;
    for (var k = 0; k < parts.length; k++) {
      var copyRow = baseRow.slice();
      copyRow[relC] = parts[k];
      expanded.push(copyRow);
    }
  }
  if (!splitCnt) {
    note_(ctx, '行へ展開する複数値は見つかりませんでした（変更なし）');
    return;
  }
  var extra = expanded.length - nr;
  guardOverwrite_(ctx, dr, op.col + '列の複数値を縦に展開（' + nr + ' → ' + expanded.length + ' 行）');
  if (extra > 0) sh.insertRowsAfter(t.lastData, extra);
  sh.getRange(t.firstData, t.firstCol, expanded.length, nc).setValues(expanded);
  chg_(ctx, sh, a1_(t.firstData, t.firstCol, expanded.length, nc), op.col + '列の ' + splitCnt + ' 行を ' + expanded.length + ' 行へ展開');
};
