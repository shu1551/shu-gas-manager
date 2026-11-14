// 式と計算の棚

// 棚: calc.col
// 題: 計算の列を足す
// 分類: 集計
// 語: 計算の列|計算列|を掛け|を足して|を引いて|で割って|を乗算|計算式を入れ|数式を入れ|の列を足
// 違い: 表の下に合計行を足すなら total・stat.row。構成比なら calc.percent。行なら rows.insert
// 引数: name*=文字, expr*=文字, at=列
// 頼み: at~([A-Z]{1,3})列に ; expr~[（(]([^）)]+[-+*/×÷＋ー−][^）)]+)[）)] ; expr~([^\s]+(?:[×*÷/＋+\-ー−][^\s]+)+)で ; name~[A-Z]{1,3}列に([^\s（(]+)[（(] ; name~([^\s（(]+)[（(] ; name~で([^\sを]+)の列 ; name~([^\sを]+)の列を(?:足|追加|作|入れ)
// 例: 「数量×単価で金額の列を足して」 → {"shelf":"calc.col","name":"金額","expr":"数量*単価"}
// 例: 「D列に利益（売上-費用）の列を足して」 → {"shelf":"calc.col","name":"利益","expr":"売上-費用","at":"D"}
// 触る: 値 書式
SHELF['calc.col'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['name', 'expr']);
  var rawExpr = String(op.expr).trim();
  // 全角記号の正規化
  var expr = rawExpr.replace(/×/g, '*').replace(/÷/g, '/').replace(/＋/g, '+').replace(/[ー−]/g, '-');
  var hdrs = headerNames_(t);
  // 見出し名を長い順にソートして、列記号に置換
  var sortedHdrs = hdrs.slice().sort(function (a, b) { return b.length - a.length; });
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    sh.insertColumnsBefore(atCol, 1);
    t = needTable_(sh); // テーブル再取得
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());

  // 式を行ごとに組み立てる関数
  var makeFormula = function (r) {
    var f = expr;
    sortedHdrs.forEach(function (h) {
      if (!h) return;
      var ci = colIndexOf_(t, h);
      var colL = colLetter_(ci);
      f = f.split(h).join(colL + r);
    });
    // もしすでに列記号（例: BやC）で書かれていれば行番号を付与
    f = f.replace(/(?<![A-Za-z0-9])([A-Z]{1,3})(?![0-9])/g, '$1' + r);
    return f.charAt(0) === '=' ? f : '=' + f;
  };

  // 見出しの設定
  sh.getRange(t.headerRow, atCol).setValue(op.name);
  // 既存見出しの書式をコピー
  var tmplCell = sh.getRange(t.headerRow, t.lastCol > atCol ? atCol + 1 : t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');

  // データ行の数式を設定
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push([makeFormula(r)]);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '計算列「' + op.name + '」を追加');
};

// 棚: calc.percent
// 題: 構成比の列を足す
// 分類: 集計
// 語: 構成比|構成比の列|割合の列|パーセント|シェア|比率の列|割合を出して|構成比を出して|構成比を足
// 違い: 2つの列の差なら calc.diff。計算列なら calc.col。合計行なら total
// 引数: col*=列, name=文字, at=列
// 頼み: at~([A-Z]{1,3})列に ; col~([^\sの]+)の(?:構成比|割合|比率|シェア) ; name~で([^\sを]+)の列
// 例: 「売上の構成比を出して」 → {"shelf":"calc.percent","col":"売上"}
// 触る: 値 書式
SHELF['calc.percent'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    sh.insertColumnsBefore(atCol, 1);
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());

  var name = op.name || '構成比';
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');

  var colL = colLetter_(ci);
  var sumRef = t.totalRow ? (colL + '$' + t.totalRow) : ('SUM(' + colL + '$' + t.firstData + ':' + colL + '$' + t.lastData + ')');
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=' + colL + r + '/' + sumRef]);
    }
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
    rg.setFormulas(formulas);
    rg.setNumberFormat('0.0%');
  }
  if (t.totalRow) {
    sh.getRange(t.totalRow, atCol).setValue(1.0).setNumberFormat('0.0%').setFontWeight('bold');
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '構成比列「' + name + '」を追加');
};

// 棚: stat.row
// 題: 平均・最大・最小の行を表の下に足す
// 分類: 集計
// 語: 平均行|平均の行|最大行|最小行|平均を足|最大値を足|最小値を足|平均も足|最大も足|最小も足
// 違い: 合計行なら total。列の計算なら calc.col。項目ごとの集計表なら summary
// 引数: stat=選択(average/max/min)=average, cols=列[], label=文字
// 頼み: stat=average<平均 ; stat=max<最大 ; stat=min<最小 ; label~[『「]([^』」]+)[』」]
// 例: 「表の下に平均の行も足して」 → {"shelf":"stat.row","stat":"average"}
// 例: 「金額の最大値の行を足して」 → {"shelf":"stat.row","stat":"max","cols":["金額"]}
// 触る: 値 書式
SHELF['stat.row'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var stat = (op.stat || 'average').toLowerCase();
  var fnName = stat === 'average' ? 'AVERAGE' : stat === 'max' ? 'MAX' : 'MIN';
  var label = op.label || (stat === 'average' ? '平均' : stat === 'max' ? '最大' : '最小');

  var cols = op.cols ? op.cols.map(function (c) { return colIndexOf_(t, c); }) : [];
  if (!cols.length) {
    for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
      if (!isNoCol_(t, ci) && isNumberCol_(t, ci)) cols.push(ci);
    }
  }
  if (!cols.length) throw new ArgError('集計する数値列が見つかりません。cols で指定してください');

  var tr = (t.totalRow ? t.totalRow : t.lastData) + 1;
  var nc = t.lastCol - t.firstCol + 1;
  var rowRg = sh.getRange(tr, t.firstCol, 1, nc);

  // ラベル位置（最初の列またはキー列以外）
  sh.getRange(tr, t.firstCol).setValue(label);

  cols.forEach(function (c) {
    var f = '=' + fnName + '(' + colLetter_(c) + t.firstData + ':' + colLetter_(c) + t.lastData + ')';
    sh.getRange(tr, c).setFormula(f).setNumberFormat(STYLE.numFmt).setHorizontalAlignment('right');
  });

  rowRg.setFontWeight('bold').setBackground(STYLE.totalBg).setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  chg_(ctx, sh, a1_(tr, t.firstCol, 1, nc), label + '行を追加');
};

// 棚: lookup.add
// 題: 別の表から列を引いて足す
// 分類: 集計
// 語: 引いてきて|VLOOKUP|XLOOKUP|マスタから|別のシートから|参照して列|対応する値|表から引っ張|から単価を
// 違い: 単純な計算なら calc.col。集計なら count.if または summary
// 引数: from_sheet*=文字, val_col*=列, key_col=列, my_key=列, name=文字, at=列
// 頼み: at~([A-Z]{1,3})列に ; from_sheet~([^\s]+マスタ)から ; val_col~から([^\sを]+)を引いて ; val_col~([^\sを]+)を引いて ; name~で([^\sを]+)の列
// 例: 「商品マスタから単価を引いてきて」 → {"shelf":"lookup.add","from_sheet":"商品マスタ","val_col":"単価"}
// 触る: 値 書式
SHELF['lookup.add'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['from_sheet', 'val_col']);
  var srcSh = sheetOf_(ctx.ss, op.from_sheet, null);
  var srcT = needTable_(srcSh);
  var vci = colIndexOf_(srcT, op.val_col);

  // キー列の特定
  var keyCol = op.key_col ? colIndexOf_(srcT, op.key_col) : null;
  var myKey = op.my_key ? colIndexOf_(t, op.my_key) : null;
  if (!keyCol || !myKey) {
    // 共通の見出しを探す
    var myHdrs = headerNames_(t), srcHdrs = headerNames_(srcT);
    for (var i = 0; i < myHdrs.length; i++) {
      var h = myHdrs[i];
      if (h && srcHdrs.indexOf(h) >= 0) {
        if (!myKey) myKey = t.firstCol + i;
        if (!keyCol) keyCol = srcT.firstCol + srcHdrs.indexOf(h);
        break;
      }
    }
  }
  if (!keyCol) keyCol = srcT.firstCol;
  if (!myKey) myKey = t.firstCol;

  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    sh.insertColumnsBefore(atCol, 1);
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());

  var name = op.name || String(op.val_col);
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');

  var srcName = q_(srcSh.getName());
  var keyRange = srcName + '!$' + colLetter_(keyCol) + '$' + srcT.firstData + ':$' + colLetter_(keyCol) + '$' + srcT.lastData;
  var valRange = srcName + '!$' + colLetter_(vci) + '$' + srcT.firstData + ':$' + colLetter_(vci) + '$' + srcT.lastData;

  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var myKeyCell = colLetter_(myKey) + r;
      formulas.push(['=XLOOKUP(' + myKeyCell + ',' + keyRange + ',' + valRange + ',"")']);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '「' + srcSh.getName() + '」から「' + name + '」を引いて追加');
};

// 棚: calc.diff
// 題: 差や増減率の列を足す
// 分類: 集計
// 語: 差の列|前月との差|伸び率の列|増減率|差分を計算|伸び率|差を出して|前年比|前月比
// 違い: 構成比なら calc.percent。汎用計算なら calc.col
// 引数: col_a*=列, col_b*=列, rate=真偽, name=文字, at=列
// 頼み: rate=true<伸び率|増減率 ; col_a~([^\sと]+)と([^\s]+)の差 ; col_b~[^\sと]+と([^\s]+)の差
// 例: 「前月との差と伸び率の列を足して」 → {"shelf":"calc.diff","col_a":"今月","col_b":"前月","rate":true}
// 触る: 値 書式
SHELF['calc.diff'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col_a', 'col_b']);
  var ca = colIndexOf_(t, op.col_a), cb = colIndexOf_(t, op.col_b);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { sh.insertColumnsBefore(atCol, 1); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var isRate = !!op.rate;
  var name = op.name || (isRate ? '増減率' : '差額');
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');
  var la = colLetter_(ca), lb = colLetter_(cb);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var f = isRate ? ('=(' + la + r + '-' + lb + r + ')/' + lb + r) : ('=' + la + r + '-' + lb + r);
      formulas.push([f]);
    }
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
    rg.setFormulas(formulas);
    if (isRate) rg.setNumberFormat('0.0%');
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '差・増減列「' + name + '」を追加');
};

// 棚: calc.running
// 題: 累計の列を足す
// 分類: 集計
// 語: 累計の列|金額の累計|累積|累計を出して|累積合計|ランニングトータル
// 違い: 合計行なら total。構成比なら calc.percent
// 引数: col*=列, name=文字, at=列
// 頼み: col~([^\sの]+)の累計
// 例: 「金額の累計を出して」 → {"shelf":"calc.running","col":"金額"}
// 触る: 値 書式
SHELF['calc.running'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { sh.insertColumnsBefore(atCol, 1); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '累計';
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');
  var cl = colLetter_(ci);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=SUM(' + cl + '$' + t.firstData + ':' + cl + r + ')']);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '累計列「' + name + '」を追加');
};

// 棚: calc.rank
// 題: 順位の列を足す
// 分類: 集計
// 語: 順位の列|ランキング|順位を付けて|順位を出して|ランクの列
// 違い: 並べ替えるなら sort。番号を振るなら renumber
// 引数: col*=列, desc=真偽, name=文字, at=列
// 頼み: desc=true<多い順|大きい順|高い順 ; desc=false<少ない順|小さい順|低い順 ; col~([^\sの]+)の(?:多い順|大きい順|順位)
// 例: 「売上の多い順に順位を付けて」 → {"shelf":"calc.rank","col":"売上"}
// 触る: 値 書式
SHELF['calc.rank'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { sh.insertColumnsBefore(atCol, 1); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '順位';
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');
  var cl = colLetter_(ci), order = op.desc === false ? 1 : 0;
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    var ref = cl + '$' + t.firstData + ':' + cl + '$' + t.lastData;
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=RANK(' + cl + r + ', ' + ref + ', ' + order + ')']);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '順位列「' + name + '」を追加');
};

// 棚: count.if
// 題: 条件に合う数を数える・合計する式を入れる
// 分類: 集計
// 語: 条件で数えて|人数を数えて|件数を数えて|COUNTIF|SUMIF|条件付き合計|カウントして|件数をカウント
// 違い: 集計表を作るなら summary。表全体なら total
// 引数: range*=範囲, criteria*=文字, sum_range=範囲, into=範囲
// 頼み: criteria~[『「]([^』」]+)[』」]の人数 ; criteria~[『「]([^』」]+)[』」]の件数
// 例: 「部署ごとの人数を数えて」 → {"shelf":"count.if","range":"C4:C20","criteria":"営業部"}
// 触る: 値
SHELF['count.if'] = function (ctx, op) {
  need_(op, ['range', 'criteria']);
  var sh = sheetCtx_(ctx, op);
  var f = op.sum_range
    ? ('=SUMIF(' + op.range + ', "' + op.criteria + '", ' + op.sum_range + ')')
    : ('=COUNTIF(' + op.range + ', "' + op.criteria + '")');
  var targetA1 = op.into;
  if (!targetA1) {
    var t = findTable_(sh);
    targetA1 = t ? colLetter_(t.lastCol + 2) + t.headerRow : 'J1';
  }
  sh.getRange(targetA1).setFormula(f);
  chg_(ctx, sh, targetA1, '式「' + f + '」を設定');
};

// 棚: subtotal
// 題: 区分ごとに小計の行を入れる
// 分類: 集計
// 語: 小計を入れて|小計行を足して|ごとに小計|区分ごとの小計|SUBTOTAL
// 違い: 表末尾の合計なら total。別シート集計なら summary
// 引数: key_col*=列, sum_cols=列[]
// 頼み: key_col~([^\s]+)ごとに小計
// 例: 「得意先ごとに小計を入れて」 → {"shelf":"subtotal","key_col":"得意先"}
// 触る: 値 書式
SHELF['subtotal'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['key_col']);
  var ki = colIndexOf_(t, op.key_col);
  var sumIndices = op.sum_cols ? op.sum_cols.map(function (c) { return colIndexOf_(t, c); }) : [];
  if (!sumIndices.length) {
    for (var c = t.firstCol; c <= t.lastCol; c++) if (isNumberCol_(t, c)) sumIndices.push(c);
  }
  var vals = sh.getRange(t.firstData, ki, t.lastData - t.firstData + 1, 1).getValues();
  var breaks = [];
  for (var i = 1; i < vals.length; i++) {
    if (vals[i][0] !== vals[i - 1][0] && vals[i][0] !== '' && vals[i - 1][0] !== '') {
      breaks.push(t.firstData + i);
    }
  }
  var inserted = 0, lastR = t.firstData;
  for (var b = breaks.length - 1; b >= 0; b--) {
    var rowIdx = breaks[b];
    sh.insertRowBefore(rowIdx);
    sh.getRange(rowIdx, t.firstCol).setValue('小計').setFontWeight('bold');
    sumIndices.forEach(function (si) {
      var cl = colLetter_(si);
      sh.getRange(rowIdx, si).setFormula('=SUBTOTAL(9, ' + cl + lastR + ':' + cl + (rowIdx - 1) + ')').setFontWeight('bold');
    });
    inserted++;
  }
  chg_(ctx, sh, '表', inserted + ' か所に小計行を挿入');
};

// 棚: formula.guard
// 題: エラー表示を消す（IFERRORで包む）
// 分類: 集計
// 語: エラーが出ないように|エラーを隠して|エラーを空白に|IFERROR|DIV/0
// 違い: 式を計算するなら calc.col。値を消すなら clear.values
// 引数: col=列, range=範囲, fallback=文字
// 例: 「#DIV/0! が出ないようにして」 → {"shelf":"formula.guard","fallback":0}
// 触る: 値
SHELF['formula.guard'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    var t2 = findTable_(sh);
    rg = t2 ? sh.getRange(t2.firstData, t2.firstCol, t2.lastData - t2.firstData + 1, t2.lastCol - t2.firstCol + 1) : sh.getDataRange();
  }
  var forms = rg.getFormulas(), changed = 0;
  var fb = op.fallback !== undefined ? (typeof op.fallback === 'string' ? ('"' + op.fallback + '"') : op.fallback) : '""';
  for (var r = 0; r < forms.length; r++) {
    for (var c = 0; c < forms[r].length; c++) {
      var f = forms[r][c];
      if (f && f.indexOf('=IFERROR(') !== 0) {
        forms[r][c] = '=IFERROR(' + f.replace(/^=/, '') + ', ' + fb + ')';
        changed++;
      }
    }
  }
  if (changed) rg.setFormulas(forms);
  chg_(ctx, sh, rg.getA1Notation(), changed + ' 個の数式を IFERROR で保護');
};

// 棚: formula.tovalue
// 題: 計算式を確定した値に変える
// 分類: 集計
// 語: 式を値にして|数式を値に|計算結果を値に|値貼り付け|式を値に置き換え|値に変換
// 違い: 文字を探して置換なら replace。書式だけなら clear.format
// 引数: col=列, range=範囲
// 例: 「この列の式を値にして」 → {"shelf":"formula.tovalue","col":"計算"}
// 危ない: 上書き
// 触る: 値
SHELF['formula.tovalue'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    var t2 = findTable_(sh);
    rg = t2 ? sh.getRange(t2.firstData, t2.firstCol, t2.lastData - t2.firstData + 1, t2.lastCol - t2.firstCol + 1) : sh.getDataRange();
  }
  guardOverwrite_(ctx, rg, '数式を値に確定「' + rg.getA1Notation() + '」');
  var vals = rg.getValues();
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '数式を値に固定化');
};

// 棚: round
// 題: 数値を四捨五入・切り捨て・切り上げする
// 分類: 集計
// 語: 四捨五入して|切り捨てて|切り上げて|千円単位に丸めて|端数処理|ROUND|ラウンド
// 違い: 表示桁数の見た目だけなら format（number_format）。式として計算するならこれ
// 引数: col=列, range=範囲, mode=選択(round/floor/ceil)=round, digits=数=0
// 頼み: mode=floor<切り捨て ; mode=ceil<切り上げ ; digits~([0-9-]+)桁に丸め ; digits=-3<千円単位 ; digits=-4<万円単位
// 例: 「金額を千円単位に丸めて」 → {"shelf":"round","col":"金額","digits":-3}
// 触る: 値
SHELF['round'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else throw new ArgError('棚「round」に col または range が要ります');
  var fnName = op.mode === 'floor' ? 'ROUNDDOWN' : op.mode === 'ceil' ? 'ROUNDUP' : 'ROUND';
  var dig = op.digits !== undefined ? parseInt(op.digits, 10) : 0;
  var forms = rg.getFormulas(), vals = rg.getValues();
  for (var r = 0; r < forms.length; r++) {
    for (var c = 0; c < forms[r].length; c++) {
      var src = forms[r][c] ? forms[r][c].replace(/^=/, '') : vals[r][c];
      if (src !== '') forms[r][c] = '=' + fnName + '(' + src + ', ' + dig + ')';
    }
  }
  rg.setFormulas(forms);
  chg_(ctx, sh, rg.getA1Notation(), fnName + '（桁: ' + dig + '）を適用');
};

// 棚: date.parts
// 題: 日付から年・月・曜日・年度の列を足す
// 分類: 集計
// 語: 年の列|月の列|曜日の列|年度の列|日付から年|日付から月|日付から曜日|曜日を足して
// 違い: 日付の入力なら fill.date。書式変更なら format
// 引数: col*=列, part*=選択(year/month/day/weekday/quarter), name=文字, at=列
// 頼み: part=weekday<曜日 ; part=year<年 ; part=month<月 ; col~([^\sの]+)から(?:年|月|曜日)
// 例: 「日付から曜日の列を作って」 → {"shelf":"date.parts","col":"日付","part":"weekday"}
// 触る: 値 書式
SHELF['date.parts'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col', 'part']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { sh.insertColumnsBefore(atCol, 1); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var part = String(op.part).toLowerCase();
  var nameMap = { year: '年', month: '月', day: '日', weekday: '曜日', quarter: '四半期' };
  var name = op.name || nameMap[part] || '日付要素';
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');
  var cl = colLetter_(ci);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var cellRef = cl + r;
      var f = part === 'year' ? ('=YEAR(' + cellRef + ')')
        : part === 'month' ? ('=MONTH(' + cellRef + ')')
        : part === 'day' ? ('=DAY(' + cellRef + ')')
        : part === 'weekday' ? ('=TEXT(' + cellRef + ', "aaa")')
        : ('=ROUNDUP(MONTH(' + cellRef + ')/3)');
      formulas.push([f]);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '日付抽出列「' + name + '」を追加');
};

// 棚: text.join
// 題: 複数の列をつないで新しい列を作る
// 分類: 集計
// 語: 列をつないで|結合して1列に|文字列をつなげて|氏名の列を作って|列を連結|列を結合|つなげて
// 違い: 列を分けるなら split.col。セルを結合するなら format（merge）
// 引数: cols*=列[], sep=文字, name=文字, at=列
// 頼み: cols~([^\sと]+)と([^\s]+)をつないで ; sep~[『「]([^』」]+)[』」]でつな
// 例: 「姓と名をつないで氏名の列に」 → {"shelf":"text.join","cols":["姓","名"],"sep":" "}
// 触る: 値 書式
SHELF['text.join'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['cols']);
  var colList = (Array.isArray(op.cols) ? op.cols : [op.cols]).map(function (c) { return colIndexOf_(t, c); });
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { sh.insertColumnsBefore(atCol, 1); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '結合';
  sh.getRange(t.headerRow, atCol).setValue(name);
  var tmplCell = sh.getRange(t.headerRow, t.firstCol);
  sh.getRange(t.headerRow, atCol).setBackground(tmplCell.getBackground()).setFontColor(tmplCell.getFontColor()).setFontWeight(tmplCell.getFontWeight()).setHorizontalAlignment('center');
  var sep = op.sep !== undefined ? String(op.sep) : ' ';
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var parts = colList.map(function (ci) { return colLetter_(ci) + r; });
      var f = sep ? ('=JOIN("' + sep + '", ' + parts.join(', ') + ')') : ('=CONCATENATE(' + parts.join(', ') + ')');
      formulas.push([f]);
    }
    sh.getRange(t.firstData, atCol, numRows, 1).setFormulas(formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '連結列「' + name + '」を追加');
};

// 棚: text.case
// 題: 文字列の大文字・小文字・全角・半角をそろえる
// 分類: 集計
// 語: 大文字にそろえて|小文字にして|半角にそろえて|全角にして|PROPER|UPPER|LOWER
// 違い: 表全体をきれいにするなら seiri。文字置換なら replace
// 引数: col=列, range=範囲, mode*=選択(upper/lower/proper/asc/jis)=upper
// 頼み: mode=upper<大文字 ; mode=lower<小文字 ; mode=proper<先頭だけ大文字 ; mode=asc<半角
// 例: 「品番を大文字にそろえて」 → {"shelf":"text.case","col":"品番","mode":"upper"}
// 危ない: 上書き
// 触る: 値
SHELF['text.case'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else throw new ArgError('棚「text.case」に col または range が要ります');
  guardOverwrite_(ctx, rg, '文字列ケース変換「' + rg.getA1Notation() + '」');
  var mode = (op.mode || 'upper').toLowerCase();
  var fnName = mode === 'lower' ? 'LOWER' : mode === 'proper' ? 'PROPER' : mode === 'asc' ? 'ASC' : mode === 'jis' ? 'JIS' : 'UPPER';
  var forms = rg.getFormulas(), vals = rg.getValues();
  for (var r = 0; r < forms.length; r++) {
    for (var c = 0; c < forms[r].length; c++) {
      var src = forms[r][c] ? forms[r][c].replace(/^=/, '') : ('"' + vals[r][c] + '"');
      forms[r][c] = '=' + fnName + '(' + src + ')';
    }
  }
  rg.setFormulas(forms);
  chg_(ctx, sh, rg.getA1Notation(), fnName + ' 関数を適用');
};
