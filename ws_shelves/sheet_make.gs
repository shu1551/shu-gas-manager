// 作る・集計の棚

// 棚: table.new
// 題: 表を新しく作る
// 分類: 作る
// 語: 表を作|表を新規|一覧表を|テーブルを作|見出しと行|名簿を作|表にして|見出しが|表を新しく作|新しい表を作
// 引数: headers*=配列, title=文字, rows=表, number=列, total=列[], label=文字, tidy=真偽
// 頼み: headers~見出し[がは]\s*([^\s、。]+?(?:(?:[・、,]|と)[^\s、。]+?)+)の(?:表|テーブル|名簿)
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
  if (ctx.isNew) { sh = ss.getSheets()[0]; sh.setName(name); } else { sh = ss.insertSheet(name, ss.getSheets().length); ctx.createdSheets.push(name); }
  ctx.curSheet = name;
  if (title) { sh.getRange(1, 1).setValue(title).setFontWeight('bold').setFontSize(14); }
  var dataLastRow = hr + grid.length - 1;
  var last = dataLastRow;
  if (totalCols.length) {
    var totRow = [];
    for (var tc = 0; tc < nc; tc++) totRow.push('');
    var labelCol = 1;
    while (labelCol <= nc && (totalCols.indexOf(labelCol) >= 0 || labelCol === numCol)) labelCol++;
    if (labelCol > nc) labelCol = 1;
    totRow[labelCol - 1] = op.label || '合計';
    totalCols.forEach(function (c) {
      totRow[c - 1] = '=SUM(' + colLetter_(c) + (hr + 1) + ':' + colLetter_(c) + dataLastRow + ')';
    });
    grid.push(totRow);
    last = hr + grid.length - 1;
  }
  var rg = sh.getRange(hr, 1, grid.length, nc);
  rg.setValues(grid);
  chg_(ctx, sh, a1_(1, 1, last, nc), '表を作成（' + rows.length + ' 行' + (totalCols.length ? '・合計行' : '') + '）');
  if (op.tidy !== false) tidyRange_(ctx, sh, null);
};

// 棚: total
// 題: 表の下に合計行を足す
// 分類: 集計
// 語: 合計行|合計を足|合計を出|合計を入れ|合計を付け|列の合計|合計欄|合計も入れ|合計入れといて
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
  // すでにある合計行で式が合っているなら、書式も書き直さない（「変更なし」と言いながら書式を変えない）
  if (existed && !fixed.length) { note_(ctx, '合計行 ' + tr + ' はすでにあります（変更なし）'); return; }
  var out = fr[0].map(function (f, k) { return f || vr[0][k]; });
  rowRg.setValues([out]).setNumberFormats(nf).setHorizontalAlignments(al);
  rowRg.setFontWeight('bold').setBackground(STYLE.totalBg).setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  if (existed && !fixed.length) note_(ctx, '合計行 ' + tr + ' はすでにあります（変更なし）');
  else chg_(ctx, sh, a1_(tr, t.firstCol, 1, nc), existed ? '合計行の範囲を直した（' + fixed.join('・') + '列）' : '合計行を追加');
};

// 棚: summary
// 題: 項目ごとの集計表を作る
// 分類: 集計
// 語: 項目ごとの集計|まとめて集計|集計表を|部署ごとに合計|ごとの合計|ごとに集計|ごとの件数|集計表を作|集計表を新|ごとの集計表|ごとの金額|ごとの数量|をまとめて|売上をまとめて
// 違い: ピボットテーブルを作るなら pivot.new。表自体の合計行なら total。出力先シートの既定は「集計」（別シート名の指定が無ければ into は省略）
// 引数: by*=列, values*=列[], func=選択(sum/count/avg)=sum, into=文字
// 頼み: into=集計<新しいシートに ; by~([^\s・、をにのはが]+?)ごと(?:に|の) ; by~([^\s・、をにのはが]+?)別(?:に|で|の) ; func=avg<平均 ; func=count<件数|人数
// 例: 「部署ごとの金額の合計表を作って」 → {"shelf":"summary","by":"部署","values":["金額"]}
// 例: 「得意先ごとの金額の合計を出して」 → {"shelf":"summary","by":"得意先","values":["金額"]}
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
    var dstLr = dst.getLastRow(), dstLc = dst.getLastColumn(), same = false;
    if (dstLr === grid.length && dstLc >= grid[0].length) {
      var dstChk = dst.getRange(1, 1, grid.length, grid[0].length);
      var cur = dstChk.getFormulas(), curV = dstChk.getValues();
      same = grid.every(function (row, r2) { return row.every(function (v, c2) { return String(cur[r2][c2] || curV[r2][c2]) === String(v); }); });
    }
    ctx.curSheet = src.getName();  // 集計は元の表から作るおまけ。今のシートは元の表のまま（続く「並べ替えて」等が元の表に効くように）
    if (same) { note_(ctx, '集計シート「' + into + '」は最新です（変更なし）'); return; }
    guardDelete_(ctx, '集計シート「' + into + '」はすでにあり、中身が変わります（作り直します）');
    dst.clear();
  } else { dst = ctx.ss.insertSheet(into, ctx.ss.getSheets().length); ctx.createdSheets.push(into); }
  dst.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
  ctx.curSheet = src.getName();
  chg_(ctx, dst, a1_(1, 1, grid.length, grid[0].length), 'シート「' + into + '」へ「' + src.getName() + '」の ' + hdr[0] + ' ごとの集計（元の表を直すと追従）');
  note_(ctx, '別の棚からこの表を参照するときは range:"' + into + '"（または "' + into + '!' + a1_(1, 1, grid.length, grid[0].length) + '"）');
  tidyRange_(ctx, dst, null);
};

// 棚: pivot.new
// 題: ピボットテーブルを作る
// 分類: 集計
// 語: ピボット|クロス集計|縦と横で集計|ドラッグで集計|ピボットテーブル|クロス集計表を作成|ピボットを作成
// 違い: 式の集計表（元を直すと追従）なら summary。表の下に合計行なら total
// 引数: rows*=列[], values*=列[], cols=列[], func=選択(sum/count/avg)=sum, into=文字
// 頼み: func=avg<平均 ; func=count<件数|人数 ; rows~([^\s・、]+?)別(?:・|に|で) ; cols~別・([^\s別の]+?)別 ; values~(?:別に|別の|・|で)\s*([^\sの、]+?)の?ピボット
// 例: 「部署別に金額のピボットテーブルを作って」 → {"shelf":"pivot.new","rows":["部署"],"values":["金額"]}
// 例: 「部署別・月別の売上ピボットテーブルを作って」 → {"shelf":"pivot.new","rows":["部署"],"cols":["月"],"values":["売上"]}
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
  var dst = ctx.ss.insertSheet(into, ctx.ss.getSheets().length);
  ctx.createdSheets.push(into);

  var anchor = dst.getRange('A1');
  var pivotTable = anchor.createPivotTable(sourceRange);

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

// 棚: chart.new
// 題: グラフを作る・直す
// 分類: 集計
// 語: グラフを作|グラフにして|グラフを入れ|棒グラフ|折れ線|円グラフ|推移|グラフのタイトル
// 違い: タイトルや種類を変えるときは chart.delete で消して作り直さず、{"shelf":"chart.new","edit":true,"title":"..."} で既存グラフを変更する（target 指定可）。「〇〇ごとの△△をグラフにして」でも集計表作成の頼みが無ければ summary で新シートを足さず元表 2 列（例 "C1:C21,G1:G21"）でそのまま描く。ピボットは pivot.new
// 引数: range=範囲, type=選択(column/bar/line/pie/area/scatter)=column, title=文字, at=範囲, target=文字, edit=真偽
// 頼み: type=bar<横棒 ; type=line<折れ線 ; type=pie<円グラフ ; type=area<面グラフ ; type=scatter<散布図 ; type=column<棒グラフ|縦棒|グラフ ; title~タイトルを[『「]([^』」]+)[』」] ; title~グラフ[^、。]*タイトルを([^』」\s、。]+?)(?:に|へ) ; edit=true<グラフのタイトル|今あるグラフ|既存のグラフ
// 例: 「売上の推移を折れ線グラフにして」 → {"shelf":"chart.new","type":"line","title":"売上推移"}
// 例: 「今あるグラフのタイトルを分類別在庫に変えて」 → {"shelf":"chart.new","edit":true,"title":"分類別在庫"}
// 触る: グラフ
// 控え: 今
SHELF['chart.new'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var charts = sh.getCharts ? sh.getCharts() : [];
  var isEdit = Boolean(op.edit || op.target || (!op.range && !op.at && !op.type && op.title && charts.length === 1));
  var rangeList = op.range ? String(op.range).split(/\s*,\s*/).filter(function (s) { return s; }) : [];
  var resolveRanges_ = function () {
    return rangeList.length ? rangeList.map(function (r) {
      if (r.indexOf('!') >= 0) return ctx.ss.getRange(r);
      var refSh = r.indexOf(':') < 0 ? ctx.ss.getSheetByName(r) : null;
      if (refSh) {
        var rt = findTable_(refSh);
        return rt ? refSh.getRange(rt.headerRow, rt.firstCol, rt.lastData - rt.headerRow + 1, rt.lastCol - rt.firstCol + 1) : refSh.getDataRange();
      }
      return sh.getRange(r);
    }) : [(function () {
      var t = findTable_(sh);
      return t ? sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1) : sh.getDataRange();
    })()];
  };
  var typeMap = {
    column: Charts.ChartType.COLUMN,
    bar: Charts.ChartType.BAR,
    line: Charts.ChartType.LINE,
    pie: Charts.ChartType.PIE,
    area: Charts.ChartType.AREA,
    scatter: Charts.ChartType.SCATTER
  };
  var typeStr = op.type ? String(op.type).toLowerCase() : '';
  if (typeStr && !typeMap[typeStr]) throw new ArgError('種類「' + typeStr + '」は使えません（column/bar/line/pie/area/scatter）');

  if (isEdit) {
    if (!charts.length) throw new ArgError('シート「' + sh.getName() + '」に変更するグラフがありません');
    var targetChart = null;
    if (op.target && op.target !== '*' && op.target !== 'last') {
      for (var i = 0; i < charts.length; i++) {
        var ct = charts[i].getOptions() && charts[i].getOptions().get('title');
        if (ct === op.target) { targetChart = charts[i]; break; }
      }
      if (!targetChart) throw new ArgError('グラフ「' + op.target + '」が見つかりませんでした');
    } else {
      targetChart = charts[charts.length - 1];
    }
    var mb = targetChart.modify();
    if (typeStr) mb.setChartType(typeMap[typeStr]);
    if (op.title !== undefined && op.title !== null) mb.setOption('title', op.title);
    if (op.at) {
      var editAt = sh.getRange(op.at);
      mb.setPosition(editAt.getRow(), editAt.getColumn(), 0, 0);
    }
    if (rangeList.length) {
      var editRanges = resolveRanges_();
      if (mb.clearRanges) mb.clearRanges();
      editRanges.forEach(function (rg) { mb.addRange(rg); });
    }
    sh.updateChart(mb.build());
    ctx.curSheet = sh.getName();
    var parts = [];
    if (op.title !== undefined && op.title !== null) parts.push('タイトル「' + op.title + '」');
    if (typeStr) parts.push('種類 ' + typeStr);
    if (op.at) parts.push('位置 ' + op.at);
    chg_(ctx, sh, op.target || '', 'グラフを変更' + (parts.length ? '（' + parts.join('・') + '）' : ''));
    return;
  }

  var ranges = resolveRanges_();
  var full = ranges[0];
  if (!full || full.getLastRow() === 0 || full.getLastColumn() === 0) {
    throw new ArgError('グラフにするデータがありません');
  }
  typeStr = typeStr || 'column';
  var b = sh.newChart().setChartType(typeMap[typeStr]);
  ranges.forEach(function (rg) { b.addRange(rg); });
  if (op.title) b.setOption('title', op.title);
  if (op.at) {
    var atRg = sh.getRange(op.at);
    b.setPosition(atRg.getRow(), atRg.getColumn(), 0, 0);
  } else {
    var sameSheet = ranges.every(function (rg) { return !rg.getSheet || rg.getSheet().getName() === sh.getName(); });
    var atRow = sameSheet ? full.getRow() : 1;
    var atCol = sameSheet
      ? Math.max.apply(null, ranges.map(function (rg) { return rg.getLastColumn(); })) + 2
      : Math.max(1, sh.getLastColumn()) + 2;
    b.setPosition(atRow, atCol, 0, 0);
  }
  sh.insertChart(b.build());
  ctx.curSheet = sh.getName();
  chg_(ctx, sh, ranges.map(function (rg) {
    var sname = rg.getSheet ? rg.getSheet().getName() : sh.getName();
    return (sname !== sh.getName() ? sname + '!' : '') + rg.getA1Notation();
  }).join(','), 'グラフを作成（' + typeStr + (op.title ? '・' + op.title : '') + '）');
};

// 棚: chart.delete
// 題: グラフを消す
// 分類: 集計
// 語: グラフを消|グラフを削除|グラフをなく|グラフはいらない|グラフ削除
// 違い: タイトルや種類を変えるときは消さずに chart.new（edit:true）を使う。ピボットテーブルを消すなら sheet.delete。表の消去なら range.clear
// 引数: title=文字
// 頼み: title~([^\s、。を]+?)グラフを(?:消|削除)
// 例: 「売上推移グラフを削除して」 → {"shelf":"chart.delete","title":"売上推移"}
// 例: 「このシートのグラフを消して」 → {"shelf":"chart.delete"}
// 危ない: 消す
// 触る: グラフ
// 控え: 今
SHELF['chart.delete'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var charts = sh.getCharts();
  if (!charts.length) {
    note_(ctx, 'シート「' + sh.getName() + '」にグラフはありません（変更なし）');
    return;
  }
  var targets = [];
  if (op.title) {
    charts.forEach(function (c) {
      var t = c.getOptions() && c.getOptions().get('title');
      if (t === op.title) targets.push(c);
    });
    if (!targets.length) {
      note_(ctx, 'グラフ「' + op.title + '」は見つかりませんでした（変更なし）');
      return;
    }
  } else {
    targets = charts;
  }
  guardDelete_(ctx, 'シート「' + sh.getName() + '」のグラフ' + (op.title ? '「' + op.title + '」' : '（' + targets.length + ' 個）') + 'を削除します');
  targets.forEach(function (c) {
    sh.removeChart(c);
  });
  ctx.curSheet = sh.getName();
  chg_(ctx, sh, '', 'グラフを削除' + (op.title ? '（' + op.title + '）' : '（' + targets.length + ' 個）'));
};

// 棚: table.template
// 題: 定番の業務表テンプレートを一発で作る
// 分類: 作る
// 語: 業務テンプレート|タスク管理表|収支表|顧客リスト|工程表|議事録表|ひな形を作って|定番の表
// 違い: 好きな列を指定してゼロから表を作るなら table.new
// 引数: kind*=選択(task/budget/customer/schedule/minutes)=task, title=文字
// 頼み: kind=budget<収支|予算|家計|売上管理 ; kind=customer<顧客|取引先|クライアント|名簿 ; kind=schedule<工程|スケジュール|予定表|ガント ; kind=minutes<議事録|会議|ミーティング ; kind=task<タスク|作業管理|進捗
// 例: 「タスク管理表のテンプレートを作って」 → {"shelf":"table.template","kind":"task"}
// 触る: 値 書式 シート構成 固定 入力規則
// 控え: 今
SHELF['table.template'] = function (ctx, op) {
  need_(op, ['kind']);
  var kind = String(op.kind || 'task').toLowerCase();
  var specs = {
    task: {
      defName: 'タスク管理',
      title: 'タスク管理表',
      headers: ['No', 'タスク名', '担当者', '期限', '優先度', 'ステータス', '完了'],
      rows: [
        [1, '要件の整理', '田中', new Date(2026, 11, 1), '高', '進行中', false],
        [2, '資料の作成', '佐藤', new Date(2026, 11, 5), '中', '未着手', false],
        [3, 'レビュー依頼', '鈴木', new Date(2026, 11, 10), '低', '未着手', false]
      ],
      listRules: [
        { col: 5, items: ['高', '中', '低'] },
        { col: 6, items: ['未着手', '進行中', '確認待ち', '完了'] }
      ],
      checkboxCol: 7
    },
    budget: {
      defName: '月次収支表',
      title: '月次収支表',
      headers: ['月', '区分', '項目', '予算', '実績', '差額'],
      rows: [
        ['11月', '売上', '商品売上', 500000, 540000, '=E4-D4'],
        ['11月', '経費', '仕入原価', 200000, 195000, '=E5-D5'],
        ['11月', '経費', '広告宣伝費', 80000, 85000, '=E6-D6']
      ],
      total: ['合計', '', '', '=SUM(D4:D6)', '=SUM(E4:E6)', '=SUM(F4:F6)']
    },
    customer: {
      defName: '顧客リスト',
      title: '顧客管理リスト',
      headers: ['No', '会社名', '担当者', '電話番号', 'メール', 'ランク', '備考'],
      rows: [
        [1, '株式会社サンプル', '山田太郎', '03-1234-5678', 'yamada@example.com', 'A', '主要取引先'],
        [2, 'テスト商事', '高橋花子', '06-9876-5432', 'takahashi@example.com', 'B', '月次フォロー']
      ],
      listRules: [{ col: 6, items: ['S', 'A', 'B', 'C'] }]
    },
    schedule: {
      defName: '工程表',
      title: 'スケジュール・工程表',
      headers: ['日付', '工程名', '担当', '開始予定', '完了予定', '進捗'],
      rows: [
        [new Date(2026, 11, 1), '企画立案', '田中', new Date(2026, 11, 1), new Date(2026, 11, 4), '進行中'],
        [new Date(2026, 11, 5), '設計・作成', '佐藤', new Date(2026, 11, 5), new Date(2026, 11, 12), '未着手'],
        [new Date(2026, 11, 14), '検証・公開', '鈴木', new Date(2026, 11, 14), new Date(2026, 11, 18), '未着手']
      ],
      listRules: [{ col: 6, items: ['未着手', '進行中', '完了'] }],
      weekendCol: 1
    },
    minutes: {
      defName: '議事録',
      title: '会議アジェンダ・アクション管理',
      headers: ['No', '議題', '決定事項', '担当者', '期限', '状態'],
      rows: [
        [1, '今月の進捗確認', '次回までに見積確定', '田中', new Date(2026, 11, 8), '対応中'],
        [2, '課題の整理', '関係部署へ確認送付', '佐藤', new Date(2026, 11, 10), '未着手']
      ],
      listRules: [{ col: 6, items: ['未着手', '対応中', '完了'] }]
    }
  };
  var sp = specs[kind];
  if (!sp) throw new ArgError('棚「table.template」の kind が不正です: ' + kind);
  var ss = ctx.ss, name = op.sheet || op.title || sp.defName;
  if (ss.getSheetByName(name)) {
    throw new ArgError('シート「' + name + '」はすでにあります（上書きしません。別の sheet 名を指定してください）');
  }
  var sh;
  if (ctx.isNew) { sh = ss.getSheets()[0]; sh.setName(name); }
  else { sh = ss.insertSheet(name, ss.getSheets().length); ctx.createdSheets.push(name); }
  ctx.curSheet = name;
  var titleTxt = op.title || sp.title;
  sh.getRange(1, 1).setValue(titleTxt).setFontWeight('bold').setFontSize(14);
  var grid = [sp.headers].concat(sp.rows);
  if (sp.total) grid.push(sp.total);
  var nc = sp.headers.length;
  sh.getRange(3, 1, grid.length, nc).setValues(grid);
  var endData = 3 + sp.rows.length;
  if (sp.listRules) {
    sp.listRules.forEach(function (lr) {
      sh.getRange(4, lr.col, sp.rows.length, 1).setDataValidation(
        SpreadsheetApp.newDataValidation().requireValueInList(lr.items, true).setAllowInvalid(false).build()
      );
    });
  }
  if (sp.checkboxCol) {
    sh.getRange(4, sp.checkboxCol, sp.rows.length, 1).setDataValidation(
      SpreadsheetApp.newDataValidation().requireCheckbox().build()
    );
  }
  var wkShelf = 'cf.weekend';
  if (sp.weekendCol && typeof SHELF[wkShelf] === 'function') {
    if (_TBL_CACHE) _TBL_CACHE = null;
    SHELF[wkShelf](ctx, { shelf: wkShelf, sheet: name, col: colLetter_(sp.weekendCol) });
  }
  if (_TBL_CACHE) _TBL_CACHE = null;
  tidyRange_(ctx, sh, null);
  chg_(ctx, sh, a1_(1, 1, 2 + grid.length, nc), '業務テンプレート「' + titleTxt + '」を作成');
};
