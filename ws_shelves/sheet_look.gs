// 見た目の棚

// 棚: format
// 題: 範囲の書式を変える
// 分類: 見た目
// 語: 書式を|太字に|色を付け|背景色|文字色|中央揃え|罫線
// 引数: range=範囲, col=列, header=真偽, bold=真偽, italic=真偽, color=色, bg=色, size=数, font=文字, number_format=文字, align=文字, valign=文字, wrap=真偽, borders=文字, merge=真偽
// どれか: range col header
// 例: 「見出しを太字で青い背景に」 → {"shelf":"format","header":true,"bold":true,"bg":"#1F4E79","color":"#FFFFFF"}
// 例: 「金額の列を桁区切りに」 → {"shelf":"format","col":"金額","number_format":"#,##0"}
// 触る: 書式
SHELF['format'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = null, rg;
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, 1, t.lastCol - t.firstCol + 1); }
  else if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, (t.totalRow || t.lastData) - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「format」に range・col・header のどれかが要ります');
  var did = [];
  var set = function (key, fn) { if (op[key] !== undefined) { fn(op[key]); did.push(key); } };
  set('bold', function (v) { rg.setFontWeight(v ? 'bold' : 'normal'); });
  set('italic', function (v) { rg.setFontStyle(v ? 'italic' : 'normal'); });
  set('color', function (v) { rg.setFontColor(v); });
  set('bg', function (v) { rg.setBackground(v); });
  set('size', function (v) { rg.setFontSize(v); });
  set('font', function (v) { rg.setFontFamily(v); });
  set('number_format', function (v) { rg.setNumberFormat(v); });
  set('align', function (v) { rg.setHorizontalAlignment(v); });
  set('valign', function (v) { rg.setVerticalAlignment(v); });
  set('wrap', function (v) { rg.setWrap(!!v); });
  set('borders', function (v) { if (v) rg.setBorder(true, true, true, true, v === 'outer' ? false : true, v === 'outer' ? false : true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID); else rg.setBorder(false, false, false, false, false, false); });
  set('merge', function (v) { if (v) rg.merge(); else rg.breakApart(); });
  if (!did.length) throw new ArgError('棚「format」に書式の指定（bold・color・bg・number_format・align など）がありません');
  chg_(ctx, sh, rg.getA1Notation(), did.join('・'));
};

// 棚: width
// 題: 列の幅・行の高さを変える
// 分類: 見た目
// 語: 列幅を|列の幅|幅を広げ|幅を狭め|行の高さ|幅を自動|幅を揃
// 引数: cols=対応, col=列, width=数, rows=対応, auto=列[]
// どれか: cols col rows auto
// 例: 「A列を幅200にして」 → {"shelf":"width","col":"A","width":200}
// 例: 「B列とC列の幅を中身に合わせて」 → {"shelf":"width","auto":["B","C"]}
// 触る: 幅
SHELF['width'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = findTable_(sh), did = [];
  var colRef = function (k) { return t ? colIndexOf_(t, k) : colNum_(k); };
  if (op.cols) Object.keys(op.cols).forEach(function (k) { sh.setColumnWidth(colRef(k), op.cols[k]); did.push(k + '列'); });
  if (op.col && op.width) { sh.setColumnWidth(colRef(op.col), op.width); did.push(op.col + '列'); }
  if (op.rows) Object.keys(op.rows).forEach(function (k) { sh.setRowHeight(parseInt(k), op.rows[k]); did.push(k + '行'); });
  (op.auto || []).forEach(function (k) {
    var ci = colRef(k), lr = sh.getLastRow(), mx = 0;
    if (lr > 0) sh.getRange(1, ci, lr, 1).getDisplayValues().forEach(function (x) { mx = Math.max(mx, wlen_(x[0])); });
    sh.setColumnWidth(ci, Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad))); did.push(k + '列(自動)');
  });
  if (!did.length) throw new ArgError('棚「width」に cols・rows・auto のどれかが要ります');
  chg_(ctx, sh, did.join('・'), '幅・高さを変更');
};
