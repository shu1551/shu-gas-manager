// 作る・集計の棚

// 棚: table.new
// 題: 表を新しく作る
// 分類: 作る
// 語: 表を作|表を新規|一覧表を|テーブルを作|見出しと行|名簿を作|表にして
// 引数: headers*=配列, title=文字, rows=表, number=列, total=列[], label=文字, tidy=真偽
// 例: 「見出しが名前と金額の表を作って」 → {"shelf":"table.new","headers":["名前","金額"],"rows":[["田中",1000]],"total":["金額"]}
// 触る: 値 書式 シート構成 固定
// 控え: 今
SHELF['table.new'] = function (ctx, op) {
  need_(op, ['headers']);
  var ss = ctx.ss, rows = op.rows || [], headers = op.headers;
  var name = op.sheet || op.title || '表';
  var sh = ss.getSheetByName(name);
  var title = op.title || '';
  var off = title ? 2 : 0;
  var hr = 1 + off, nc = headers.length;
  var grid = [headers.map(String)];
  rows.forEach(function (r, i) {
    var row = r.slice(); while (row.length < nc) row.push('');
    grid.push(row.slice(0, nc).map(function (v) { return typeof v === 'string' ? shiftFormula_(v, off) : v; }));
  });
  // 列は見出しの名前でも列記号でも（手順書の約束どおり）
  var colOf = function (ref) { var k = headers.map(String).indexOf(String(ref)); return k >= 0 ? k + 1 : colNum_(ref); };
  var numCol = op.number ? colOf(op.number) : 0;
  if (numCol) for (var i = 1; i < grid.length; i++) grid[i][numCol - 1] = i;
  var totalCols = (op.total || []).map(colOf);
  totalCols.concat(numCol ? [numCol] : []).forEach(function (c) { if (c > nc) throw new ArgError('列「' + colLetter_(c) + '」は表の外です（見出しは ' + nc + ' 列）'); });
  if (sh) {
    // 同じ頼みの撃ち直し：中身が同じなら変更なし。違えば止める
    var same = false;
    if (sh.getLastRow() === hr + rows.length + (totalCols.length ? 1 : 0) && sh.getLastColumn() >= nc) {
      var cur = sh.getRange(hr, 1, grid.length, nc).getFormulas();
      var curV = sh.getRange(hr, 1, grid.length, nc).getValues();
      same = grid.every(function (row, r) { return row.every(function (v, c) { var w = cur[r][c] || curV[r][c]; return String(w) === String(v) || (typeof v === 'string' && v.charAt(0) === '=' && String(cur[r][c]) === v); }); });
    }
    ctx.curSheet = name;
    if (same) { note_(ctx, '同じ表がすでにあります（変更なし）'); return; }
    throw new ArgError('シート「' + name + '」はすでにあります（中身が違います）。別の名前にするか、write・format で直してください');
  }
  if (ctx.isNew) { sh = ss.getSheets()[0]; sh.setName(name); } else { sh = ss.insertSheet(name); ctx.createdSheets.push(name); }
  ctx.curSheet = name;
  if (title) { sh.getRange(1, 1).setValue(title).setFontWeight('bold').setFontSize(14); }
  var rg = sh.getRange(hr, 1, grid.length, nc);
  rg.setValues(grid);
  var last = hr + grid.length - 1;
  if (totalCols.length) {
    var tr = last + 1;
    var labelCol = 1;
    while (labelCol <= nc && (totalCols.indexOf(labelCol) >= 0 || labelCol === numCol)) labelCol++;
    if (labelCol > nc) labelCol = 1;
    sh.getRange(tr, labelCol).setValue(op.label || '合計');
    totalCols.forEach(function (c) { sh.getRange(tr, c).setFormula('=SUM(' + colLetter_(c) + (hr + 1) + ':' + colLetter_(c) + last + ')'); });
    last = tr;
  }
  chg_(ctx, sh, a1_(1, 1, last, nc), '表を作成（' + rows.length + ' 行' + (totalCols.length ? '・合計行' : '') + '）');
  if (op.tidy !== false) tidyRange_(ctx, sh, null);
};

// 棚: total
// 題: 表の下に合計行を足す
// 分類: 集計
// 語: 合計行|合計を足|合計を出|合計を入れ|合計を付け|列の合計|合計欄
// 引数: cols=列[], label=文字
// 例: 「表の下に合計行を足して」 → {"shelf":"total"}
// 例: 「金額の合計を出して」 → {"shelf":"total","cols":["金額"]}
// 触る: 値 書式
SHELF['total'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var cols = op.cols ? op.cols.map(function (c) { return colIndexOf_(t, c); }) : [];
  if (!cols.length) for (var ci = t.firstCol; ci <= t.lastCol; ci++) if (!isNoCol_(t, ci) && isNumberCol_(t, ci)) cols.push(ci);
  if (!cols.length) throw new ArgError('合計する列が見つかりません。cols で指定してください');
  var tr, existed = !!t.totalRow;
  tr = existed ? t.totalRow : t.lastData + 1;
  var label = op.label || '合計';
  if (!existed) {
    var lc = t.firstCol;
    while (lc <= t.lastCol && (cols.indexOf(lc) >= 0 || isNoCol_(t, lc))) lc++;
    if (lc > t.lastCol) lc = t.firstCol;
    sh.getRange(tr, lc).setValue(label);
  }
  var nc = t.lastCol - t.firstCol + 1;
  var rowRg = sh.getRange(tr, t.firstCol, 1, nc);
  // 合計行は 1 回で読み、式と書式を配列にして 1 回ずつ書く（列ごとに API を呼ばない）
  var fr = rowRg.getFormulas(), vr = rowRg.getValues(), nf = rowRg.getNumberFormats(), al = rowRg.getHorizontalAlignments(), fixed = [];
  cols.forEach(function (c) {
    var k = c - t.firstCol, f = '=SUM(' + colLetter_(c) + t.firstData + ':' + colLetter_(c) + t.lastData + ')';
    if (fr[0][k] !== f) { fr[0][k] = f; fixed.push(colLetter_(c)); }
    nf[0][k] = STYLE.numFmt; al[0][k] = 'right';
  });
  var out = fr[0].map(function (f, k) { return f || vr[0][k]; });
  rowRg.setValues([out]).setNumberFormats(nf).setHorizontalAlignments(al);
  rowRg.setFontWeight('bold').setBackground(STYLE.totalBg).setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  if (existed && !fixed.length) note_(ctx, '合計行 ' + tr + ' はすでにあります（変更なし）');
  else chg_(ctx, sh, a1_(tr, t.firstCol, 1, nc), existed ? '合計行の範囲を直した（' + fixed.join('・') + '列）' : '合計行を追加');
};

// 棚: summary
// 題: 項目ごとの集計表を作る
// 分類: 集計
// 語: 項目ごとの集計|まとめて|集計表を|部署ごとに合計|ごとの合計|ごとに集計|ごとの件数
// 違い: ピボットテーブルを作るなら pivot.new。表自体の合計行なら total
// 引数: by*=列, values*=列[], func=選択(sum/count/avg)=sum, into=文字
// 例: 「部署ごとの金額の合計表を作って」 → {"shelf":"summary","by":"部署","values":["金額"]}
// 危ない: 消す
// 触る: 値 書式 シート構成
// 控え: 今,先
SHELF['summary'] = function (ctx, op) {
  need_(op, ['by', 'values']);
  var src = sheetOf_(ctx.ss, op.sheet, ctx.sheetName), t = needTable_(src);
  var by = colIndexOf_(t, op.by), vals = (Array.isArray(op.values) ? op.values : [op.values]).map(function (v) { return colIndexOf_(t, v); });
  var func = (op.func || 'sum').toLowerCase(), into = op.into || '集計';
  var keys = [], seen = {};
  for (var r = t.firstData; r <= t.lastData; r++) { var k = t.vals[r - 1][by - 1]; if (isBlank_(k)) continue; k = String(k); if (!seen[k]) { seen[k] = 1; keys.push(k); } }
  var sq = q_(src.getName()), rng = function (c) { return sq + '!$' + colLetter_(c) + '$' + t.firstData + ':$' + colLetter_(c) + '$' + t.lastData; };
  var hdr = [String(t.vals[t.headerRow - 1][by - 1])].concat(vals.map(function (c) { return String(t.vals[t.headerRow - 1][c - 1]) + (func === 'count' ? '(件数)' : func === 'avg' ? '(平均)' : ''); }));
  var grid = [hdr];
  keys.forEach(function (k, i) {
    var row = [k];
    vals.forEach(function (c) {
      var rr = i + 2;
      row.push(func === 'count' ? '=COUNTIFS(' + rng(by) + ',$A' + rr + ')' : func === 'avg' ? '=IFERROR(AVERAGEIFS(' + rng(c) + ',' + rng(by) + ',$A' + rr + '),0)' : '=SUMIFS(' + rng(c) + ',' + rng(by) + ',$A' + rr + ')');
    });
    grid.push(row);
  });
  if (func !== 'avg') {
    var tot = ['合計']; vals.forEach(function (c, j) { var L = colLetter_(j + 2); tot.push('=SUM(' + L + '2:' + L + (keys.length + 1) + ')'); });
    grid.push(tot);
  }
  var dst = ctx.ss.getSheetByName(into);
  if (dst) {
    var cur = dst.getLastRow() ? dst.getRange(1, 1, grid.length, grid[0].length).getFormulas() : [];
    var curV = dst.getLastRow() ? dst.getRange(1, 1, grid.length, grid[0].length).getValues() : [];
    var same = dst.getLastRow() === grid.length && grid.every(function (row, r2) { return row.every(function (v, c2) { return String(cur[r2][c2] || curV[r2][c2]) === String(v); }); });
    ctx.curSheet = src.getName();  // 集計は元の表から作るおまけ。今のシートは元の表のまま（続く「並べ替えて」等が元の表に効くように）
    if (same) { note_(ctx, '集計シート「' + into + '」は最新です（変更なし）'); return; }
    guardDelete_(ctx, '集計シート「' + into + '」はすでにあり、中身が変わります（作り直します）');
    dst.clear();
  } else { dst = ctx.ss.insertSheet(into); ctx.createdSheets.push(into); }
  dst.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
  ctx.curSheet = src.getName();
  chg_(ctx, dst, a1_(1, 1, grid.length, grid[0].length), '「' + src.getName() + '」の ' + hdr[0] + ' ごとの集計（元の表を直すと追従）');
  tidyRange_(ctx, dst, null);
};

// 棚: pivot.new
// 題: ピボットテーブルを作る
// 分類: 集計
// 語: ピボット|クロス集計|縦と横で集計|ドラッグで集計|ピボットテーブル
// 違い: 式の集計表（元を直すと追従）なら summary。表の下に合計行なら total
// 引数: rows*=列[], values*=列[], cols=列[], func=選択(sum/count/avg)=sum, into=文字
// 例: 「部署別・月別の売上ピボットテーブルを作って」 → {"shelf":"pivot.new","rows":["部署"],"cols":["月"],"values":["売上"]}
// 例: 「商品ごとの数量ピボットを作って」 → {"shelf":"pivot.new","rows":["商品"],"values":["数量"]}
// 触る: シート構成 値
// 控え: 先
SHELF['pivot.new'] = function (ctx, op) {
  need_(op, ['rows', 'values']);
  var src = sheetOf_(ctx.ss, op.sheet, ctx.sheetName), t = needTable_(src);
  var into = op.into || ('ピボット_' + src.getName());
  if (ctx.ss.getSheetByName(into)) {
    throw new ArgError('シート「' + into + '」はすでにあります（上書きしません）');
  }
  var rows = (Array.isArray(op.rows) ? op.rows : [op.rows]).map(function (c) { return colIndexOf_(t, c); });
  var vals = (Array.isArray(op.values) ? op.values : [op.values]).map(function (c) { return colIndexOf_(t, c); });
  var cols = op.cols ? (Array.isArray(op.cols) ? op.cols : [op.cols]).map(function (c) { return colIndexOf_(t, c); }) : [];
  var funcStr = (op.func || 'sum').toLowerCase();
  var sumFn = SpreadsheetApp.PivotTableSummarizeFunction.SUM;
  if (funcStr === 'count') sumFn = SpreadsheetApp.PivotTableSummarizeFunction.COUNTA || SpreadsheetApp.PivotTableSummarizeFunction.COUNT;
  else if (funcStr === 'avg') sumFn = SpreadsheetApp.PivotTableSummarizeFunction.AVERAGE;

  var sourceRange = src.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
  var dst = ctx.ss.insertSheet(into);
  ctx.createdSheets.push(into);

  var anchor = dst.getRange('A1');
  var pivotTable = sourceRange.createPivotTable(anchor);

  rows.forEach(function (ci) {
    pivotTable.addRowGroup(ci - t.firstCol + 1);
  });
  cols.forEach(function (ci) {
    pivotTable.addColumnGroup(ci - t.firstCol + 1);
  });
  vals.forEach(function (ci) {
    pivotTable.addPivotValue(ci - t.firstCol + 1, sumFn);
  });

  ctx.curSheet = src.getName();
  chg_(ctx, dst, 'A1', '「' + src.getName() + '」からピボットテーブルを作成');
};
