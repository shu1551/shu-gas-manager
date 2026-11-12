// 絞る・整える棚（整える手伝い tidyRange_ もここ）

function tidyRange_(ctx, sh, rangeA1) {
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
  sh.setFrozenRows(t.headerRow);
}

// 棚: tidy
// 題: 表の見た目を整える
// 分類: 整える
// 語: 表を整|見た目を整|体裁を整|見やすく|罫線を引|列幅を揃|表を綺麗
// 引数: range=範囲
// 例: 「この表を見やすく整えて」 → {"shelf":"tidy"}
// 例: 「B列からD列だけ体裁を整えて」 → {"shelf":"tidy","range":"B:D"}
// 触る: 書式 幅 固定
SHELF['tidy'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  tidyRange_(ctx, sh, op.range || null);
  chg_(ctx, sh, op.range || 'A1', '書式をそろえた');
};

// 棚: seiri
// 題: 表のデータを整理する
// 分類: 整える
// 語: データを整理|空白を除|全角を半角|数字を数値に|空行を詰|重複を消|表を掃除
// 引数: trim=真偽, halfwidth=真偽, numbers=真偽, blank_rows=真偽, dedupe=真偽, renumber=列, tidy=真偽
// 例: 「全角の数字を半角に直して」 → {"shelf":"seiri"}
// 例: 「空行を詰めて重複行も消して」 → {"shelf":"seiri","blank_rows":true,"dedupe":true}
// 危ない: 消す
// 触る: 値 書式 固定
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
  }
  // 空行を詰める＊ / 重複行を消す＊
  var t2 = findTable_(sh);
  if (op.blank_rows && t2) {
    var blanks = [];
    for (var rr = t2.firstData; rr <= t2.lastData; rr++) {
      var row = t2.vals[rr - 1].slice(t2.firstCol - 1, t2.lastCol);
      if (row.every(isBlank_)) blanks.push(rr);
    }
    // 表の途中の空行だけ（findTable_ が最後の非空行までを表とするので、すべて途中）
    if (blanks.length) {
      guardDelete_(ctx, '空行 ' + blanks.join('・') + ' 行目を詰めます');
      for (var k = blanks.length - 1; k >= 0; k--) sh.deleteRow(blanks[k]);
      chg_(ctx, sh, blanks.join('・') + ' 行目', '空行を削除（' + blanks.length + ' 行）');
    }
  }
  t2 = findTable_(sh);
  if (op.dedupe && t2) {
    var seen = {}, dups = [];
    for (var d = t2.firstData; d <= t2.lastData; d++) {
      var key = JSON.stringify(t2.vals[d - 1].slice(t2.firstCol - 1, t2.lastCol));
      if (seen[key]) dups.push(d); else seen[key] = 1;
    }
    if (dups.length) {
      guardDelete_(ctx, '全列が同じ重複行 ' + dups.join('・') + ' 行目を消します');
      for (var k2 = dups.length - 1; k2 >= 0; k2--) sh.deleteRow(dups[k2]);
      chg_(ctx, sh, dups.join('・') + ' 行目', '重複行を削除（' + dups.length + ' 行）');
    }
  }
  if (op.renumber) SHELF['renumber'](ctx, { shelf: 'renumber', col: op.renumber, sheet: op.sheet });
  if (op.tidy !== false) tidyRange_(ctx, sh, null);
  if (!ctx.changed.length) note_(ctx, '直す所はありませんでした');
};

// 棚: renumber
// 題: 番号の列を振り直す
// 分類: 整える
// 語: 番号を振り直|連番に直|番号を振り|通し番号|No を振|番号を付け直
// 引数: col*=列, start=数
// 例: 「No列を1から振り直して」 → {"shelf":"renumber","col":"No"}
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
// 語: 並べ替え|昇順に|降順に|順番に並べ|大きい順|小さい順|ソート
// 違い: 条件に合う行だけ見せるなら filter.where（古い filter・where の引数も今までどおり撃てる）
// 引数: col=列, desc=真偽, filter=真偽, where=対応
// どれか: col filter where
// 例: 「金額の大きい順に並べて」 → {"shelf":"sort","col":"金額","desc":true}
// 触る: 値 フィルタ
SHELF['sort'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rng = dataRange_(t);
  if (op.col) { rng.sort({ column: colIndexOf_(t, op.col), ascending: !op.desc }); chg_(ctx, sh, rng.getA1Notation(), op.col + ' で' + (op.desc ? '降順' : '昇順') + 'に並べ替え'); }
  if (op.filter || op.where) {
    var full = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
    var f = sh.getFilter(); if (f) f.remove();
    f = full.createFilter();
    if (op.where) {
      need_(op.where, ['col']);
      var ci = colIndexOf_(t, op.where.col) - t.firstCol + 1;
      var crit = op.where.equals !== undefined ? SpreadsheetApp.newFilterCriteria().whenTextEqualTo(String(op.where.equals)).build()
        : SpreadsheetApp.newFilterCriteria().whenCellNotEmpty().build();
      f.setColumnFilterCriteria(ci, crit);
    }
    chg_(ctx, sh, full.getA1Notation(), 'フィルタを設定');
  }
  if (!op.col && !op.filter && !op.where) throw new ArgError('棚「sort」に col か filter が要ります');
};

// 棚: filter.where
// 題: 条件に合う行だけ表示
// 分類: 絞る
// 語: だけ表示|だけ見せ|だけに絞|行だけ残|絞り込んで|のみ表示|フィルタをかけ
// 違い: 並べ替えは sort
// 引数: col*=列, equals=文字
// 例: 「部署が営業の行だけ見せて」 → {"shelf":"filter.where","col":"部署","equals":"営業"}
// 触る: 値 フィルタ
SHELF['filter.where'] = function (ctx, op) {
  SHELF['sort'](ctx, { shelf: 'sort', where: { col: op.col, equals: op.equals }, sheet: op.sheet });
};
