// 式と計算の棚

function copyHeaderStyle_(sh, headerRow, tmplCol, dstCol, name, optHeaderRows) {
  var hRows = optHeaderRows && optHeaderRows > 1 ? optHeaderRows : 1;
  var dst = sh.getRange(headerRow, dstCol, hRows, 1);
  if (hRows > 1 && typeof dst.breakApart === 'function') {
    try { dst.breakApart(); } catch (eB) {}
  }
  sh.getRange(headerRow, tmplCol, hRows, 1).copyTo(dst, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
  sh.getRange(headerRow, dstCol).setValue(name).setHorizontalAlignment('center');
  if (hRows > 1 && typeof dst.merge === 'function') {
    try { dst.merge(); } catch (eM) {}
  }
}

// フィルタで非表示の行にも確実に数式を書く（Sheets API 経由。使えない環境では setFormulas へフォールバック）
function setFormulasAllRows_(ctx, sh, startRow, col, formulas) {
  if (!formulas || !formulas.length) return;
  var numRows = formulas.length;
  var numCols = formulas[0].length;
  var canApi = typeof Sheets !== 'undefined' && Sheets.Spreadsheets &&
    typeof Sheets.Spreadsheets.batchUpdate === 'function' &&
    typeof batchRetry_ === 'function';
  if (canApi) {
    try {
      SpreadsheetApp.flush();
      var rows = formulas.map(function (row) {
        return {
          values: row.map(function (v) {
            var s = String(v == null ? '' : v);
            if (s.charAt(0) === '=') return { userEnteredValue: { formulaValue: s } };
            return { userEnteredValue: { stringValue: s } };
          })
        };
      });
      batchRetry_(ctx.ss, [{
        updateCells: {
          range: {
            sheetId: sh.getSheetId(),
            startRowIndex: startRow - 1,
            endRowIndex: startRow - 1 + numRows,
            startColumnIndex: col - 1,
            endColumnIndex: col - 1 + numCols
          },
          rows: rows,
          fields: 'userEnteredValue'
        }
      }]);
      return;
    } catch (eApi) {
      note_(ctx, 'Sheets API での数式書き込みに失敗したため通常方式へ切替: ' + String(eApi && eApi.message || eApi).slice(0, 80));
    }
  }
  sh.getRange(startRow, col, numRows, numCols).setFormulas(formulas);
}

// 棚: calc.col
// 題: 計算の列を足す
// 分類: 集計
// 語: 計算の列|計算列|を掛け|をかけ|掛けた|かけた|加算して|足し算|から引いて|差し引いて|で割って|でわって|を乗算|計算式を入れ|数式を入れ|の列を足|計算 式 列 追加|計算列を追加
// 違い: 表の下に合計行を足すなら total・stat.row。構成比なら calc.percent。行なら rows.insert
// 引数: name*=文字, expr*=文字, at=列
// 頼み: at~([A-Z]{1,3})列に ; expr~[（(]([^）)]+[-+*/×÷＋ー−][^）)]+)[）)] ; expr~([^\s]+(?:[×*÷/＋+\-ー−][^\s]+)+)で ; name~[A-Z]{1,3}列に([^\s（(]+)[（(][^）)]+[-+*/×÷＋ー−] ; name~([^\s（(]+)[（(][^）)]+[-+*/×÷＋ー−] ; name~で([^\sを]+)の列 ; name~([^\sをたてで]+)の列を(?:足|追加|作|入れ)
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
  // 2 段見出しの表で親グループ（親・子）の計算列を足すときは、表の右端ではなくその組の中（末尾の右隣）に挿入する
  var insertInGroup = false, groupParent = '', groupFirstCol = 0, groupLastCol = 0;
  if (!op.at && (t.headerRows || 1) >= 2) {
    var refNames = [], scanExpr = expr;
    sortedHdrs.forEach(function (h) {
      if (h && scanExpr.indexOf(h) >= 0) {
        refNames.push(h);
        scanExpr = scanExpr.split(h).join(' ');
      }
    });
    if (refNames.length >= 2) {
      var pMap = {}, allGrouped = true;
      refNames.forEach(function (rn) {
        var dot = rn.indexOf('・');
        if (dot > 0) pMap[rn.slice(0, dot)] = true;
        else allGrouped = false;
      });
      var pKeys = Object.keys(pMap);
      if (allGrouped && pKeys.length === 1) {
        groupParent = pKeys[0];
        for (var gi = 0; gi < hdrs.length; gi++) {
          if (String(hdrs[gi] || '').indexOf(groupParent + '・') === 0) {
            var cPos = t.firstCol + gi;
            if (!groupFirstCol || cPos < groupFirstCol) groupFirstCol = cPos;
            if (cPos > groupLastCol) groupLastCol = cPos;
          }
        }
        if (groupFirstCol && groupLastCol) {
          insertInGroup = true;
          atCol = groupLastCol + 1;
        }
      }
    }
  }
  var needInsertBefore = false;
  if (insertInGroup) {
    if (atCol <= t.lastCol) needInsertBefore = true;
  } else if (op.at && atCol <= t.lastCol) {
    var existingHdr = String(hdrs[atCol - t.firstCol] || '').trim();
    if (existingHdr !== String(op.name || '').trim()) {
      needInsertBefore = true;
    }
  }
  if (needInsertBefore) {
    insertColsSafe_(ctx, sh, atCol, 1, true);
    t = needTable_(sh); // テーブル再取得
    hdrs = headerNames_(t);
    sortedHdrs = hdrs.slice().sort(function (a, b) { return b.length - a.length; });
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
    // 文字列リテラル・関数名・既存セル番地を壊さず、単独の列記号だけに行番号を付与
    f = f.replace(/"(?:""|[^"])*"|(?<![A-Za-z0-9_$!])([A-Z]{1,3})(?![A-Za-z0-9_(])/g, function (m, col) {
      return col ? (col + r) : m;
    });
    return f.charAt(0) === '=' ? f : '=' + f;
  };

  if (insertInGroup) {
    // 親見出しを上段で拡張結合し、下段に子見出し（例: 「小計」）を配置する
    var subName = String(op.name || '').trim();
    if (subName.indexOf(groupParent + '・') === 0) subName = subName.slice(groupParent.length + 1).trim();
    else if (subName.indexOf(groupParent) === 0 && subName.length > groupParent.length) subName = subName.slice(groupParent.length).trim();
    if (!subName) subName = String(op.name || '').trim();
    var topSpan = sh.getRange(t.headerRow, groupFirstCol, 1, atCol - groupFirstCol + 1);
    if (typeof topSpan.breakApart === 'function') { try { topSpan.breakApart(); } catch (eBg) {} }
    try {
      sh.getRange(t.headerRow, groupFirstCol, 1, 1).copyTo(sh.getRange(t.headerRow, atCol, 1, 1), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    } catch (eCp1) {}
    sh.getRange(t.headerRow, groupFirstCol).setValue(groupParent).setHorizontalAlignment('center');
    if (typeof topSpan.merge === 'function') { try { topSpan.merge(); } catch (eMg) {} }
    try {
      sh.getRange(t.headerRow + 1, groupLastCol, 1, 1).copyTo(sh.getRange(t.headerRow + 1, atCol, 1, 1), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    } catch (eCp2) {}
    sh.getRange(t.headerRow + 1, atCol).setValue(subName).setHorizontalAlignment('center');
  } else {
    copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, op.name, t.headerRows || 1);
  }

  // データ行の数式を設定（左隣から書式も引き継ぐ）
  var numRows = t.lastData - t.firstData + 1;
  var tmplDataCol = insertInGroup ? groupLastCol : Math.max(t.firstCol, atCol - 1);
  if (numRows > 0) {
    if (tmplDataCol !== atCol) {
      try {
        sh.getRange(t.firstData, tmplDataCol, numRows, 1).copyTo(sh.getRange(t.firstData, atCol, numRows, 1), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      } catch (eCpD) {}
    }
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push([makeFormula(r)]);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  // 合計行がある表では、追加した計算列の合計行にも式と書式を入れる
  if (t.totalRow) {
    if (tmplDataCol !== atCol) {
      try {
        sh.getRange(t.totalRow, tmplDataCol, 1, 1).copyTo(sh.getRange(t.totalRow, atCol, 1, 1), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      } catch (eCpT) {}
    }
    var totFormula = (expr.indexOf('/') >= 0 || numRows <= 0)
      ? makeFormula(t.totalRow)
      : ('=SUM(' + colLetter_(atCol) + t.firstData + ':' + colLetter_(atCol) + t.lastData + ')');
    setFormulasAllRows_(ctx, sh, t.totalRow, atCol, [[totFormula]]);
  }
  if (_TBL_CACHE) _TBL_CACHE = null;
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
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= ci) ci++;
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());

  var name = op.name || '構成比';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);

  var colL = colLetter_(ci);
  var sumRef = t.totalRow ? (colL + '$' + t.totalRow) : ('SUM(' + colL + '$' + t.firstData + ':' + colL + '$' + t.lastData + ')');
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=' + colL + r + '/' + sumRef]);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
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
  var lc = t.firstCol;
  while (lc <= t.lastCol && (cols.indexOf(lc) >= 0 || isNoCol_(t, lc))) lc++;
  if (lc > t.lastCol) {
    lc = t.firstCol;
    while (lc <= t.lastCol && cols.indexOf(lc) >= 0) lc++;
  }
  var fr = rowRg.getFormulas(), vr = rowRg.getValues(), nf = rowRg.getNumberFormats(), al = rowRg.getHorizontalAlignments();
  if (lc <= t.lastCol) {
    fr[0][lc - t.firstCol] = '';
    vr[0][lc - t.firstCol] = label;
  }
  cols.forEach(function (c) {
    var k = c - t.firstCol;
    fr[0][k] = '=' + fnName + '(' + colLetter_(c) + t.firstData + ':' + colLetter_(c) + t.lastData + ')';
    nf[0][k] = STYLE.numFmt;
    al[0][k] = 'right';
  });
  var out = fr[0].map(function (f, k) { return f || vr[0][k]; });
  rowRg.setValues([out]).setNumberFormats(nf).setHorizontalAlignments(al)
    .setFontWeight('bold').setBackground(STYLE.totalBg)
    .setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  chg_(ctx, sh, a1_(tr, t.firstCol, 1, nc), label + '行を追加');
};

// 棚: lookup.add
// 題: 別の表から列を引いて足す
// 分類: 集計
// 語: 引いてきて|VLOOKUP|XLOOKUP|マスタから|別のシートから|参照して列|対応する値|表から引っ張|から単価を|マスタ 参照 列|別シートから参照|マスタから引
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
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= myKey) myKey++;
    if (srcSh.getSheetId() === sh.getSheetId()) {
      if (atCol <= keyCol) keyCol++;
      if (atCol <= vci) vci++;
    }
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());

  var name = op.name || String(op.val_col);
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);

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
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '「' + srcSh.getName() + '」から「' + name + '」を引いて追加');
};

// 棚: calc.diff
// 題: 差や増減率の列を足す
// 分類: 集計
// 語: 差の列|の差の列|差の列を足|前月との差|差と伸び率|伸び率の列|増減率|差分を計算|伸び率|差を出して|前年比|前月比|前月との差額|差額の列を足|差額の列
// 違い: 構成比なら calc.percent。汎用計算なら calc.col
// 引数: col_a*=列, col_b*=列, rate=真偽, name=文字, at=列
// 頼み: rate=true<伸び率|増減率 ; col_a~([^\sと、。]+)と([^\sのにの、。]+)の(?:差額?|差分|伸び率|増減率) ; col_b~[^\sと、。]+と([^\sのにの、。]+)の(?:差額?|差分|伸び率|増減率)
// 例: 「売上と原価の差の列を足して」 → {"shelf":"calc.diff","col_a":"売上","col_b":"原価"}
// 例: 「今月と前月の差と伸び率の列を足して」 → {"shelf":"calc.diff","col_a":"今月","col_b":"前月","rate":true}
// 触る: 値 書式
SHELF['calc.diff'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col_a', 'col_b']);
  var ca = colIndexOf_(t, op.col_a), cb = colIndexOf_(t, op.col_b);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); if (atCol <= ca) ca++; if (atCol <= cb) cb++; t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var isRate = !!op.rate;
  var name = op.name || (isRate ? '増減率' : '差額');
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var la = colLetter_(ca), lb = colLetter_(cb);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var f = isRate ? ('=(' + la + r + '-' + lb + r + ')/' + lb + r) : ('=' + la + r + '-' + lb + r);
      formulas.push([f]);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
    if (isRate) rg.setNumberFormat('0.0%');
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '差・増減列「' + name + '」を追加');
};

// 棚: calc.running
// 題: 累計の列を足す
// 分類: 集計
// 語: 累計の列|金額の累計|累積|累計を出して|累積合計|ランニングトータル|累計列を足|累計の列を足|累計 累積
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
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); if (atCol <= ci) ci++; t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '累計';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var cl = colLetter_(ci);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=SUM(' + cl + '$' + t.firstData + ':' + cl + r + ')']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '累計列「' + name + '」を追加');
};

// 棚: calc.rank
// 題: 順位の列を足す
// 分類: 集計
// 語: 順位の列|ランキング|順位を付けて|順位を出して|ランクの列|順位の列を足|売上順位の列|順位 ランク
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
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); if (atCol <= ci) ci++; t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '順位';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var cl = colLetter_(ci), order = op.desc === false ? 1 : 0;
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    var ref = cl + '$' + t.firstData + ':' + cl + '$' + t.lastData;
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=RANK(' + cl + r + ', ' + ref + ', ' + order + ')']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '順位列「' + name + '」を追加');
};

// 棚: count.if
// 題: 条件に合う数を数える・合計する式を入れる
// 分類: 集計
// 語: 条件で数えて|条件付き件数|COUNTIF|SUMIF|条件付き合計|カウントして|件数をカウント|件数を数えて
// 違い: 集計表を作るなら summary。表全体なら total
// 引数: range*=範囲, criteria*=文字, sum_range=範囲, into=範囲
// 頼み: criteria~[『「]([^』」]+)[』」]の?(?:人数|件数) ; criteria~[『「]([^』」]+)[』」]
// 例: 「B2:B10で「営業」の件数を数えて」 → {"shelf":"count.if","range":"B2:B10","criteria":"営業"}
// 例: 「部署ごとの人数を数えて」 → {"shelf":"count.if","range":"C4:C20","criteria":"営業部"}
// 触る: 値
SHELF['count.if'] = function (ctx, op) {
  need_(op, ['range', 'criteria']);
  var sh = sheetCtx_(ctx, op);
  var critEsc = String(op.criteria).replace(/"/g, '""');
  var f = op.sum_range
    ? ('=SUMIF(' + op.range + ', "' + critEsc + '", ' + op.sum_range + ')')
    : ('=COUNTIF(' + op.range + ', "' + critEsc + '")');
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
// 語: 小計を入れて|小計行を足して|ごとに小計|区分ごとの小計|SUBTOTAL|小計 行 挿入|小計行を挿入|小計 集計 行
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
    for (var c = t.firstCol; c <= t.lastCol; c++) if (!isNoCol_(t, c) && isNumberCol_(t, c)) sumIndices.push(c);
  }
  var vals = sh.getRange(t.firstData, ki, t.lastData - t.firstData + 1, 1).getValues();
  // 連続する非空キーの区間をすべて抽出（最終区分にも小計行を入れる）
  var groups = [], cur = null;
  for (var i = 0; i < vals.length; i++) {
    var kv = vals[i][0], rowNo = t.firstData + i;
    if (kv === '' || kv === null || kv === undefined) {
      if (cur) { groups.push(cur); cur = null; }
      continue;
    }
    var keyStr = String(kv);
    if (!cur) cur = { sR: rowNo, eR: rowNo, key: keyStr };
    else if (cur.key === keyStr) cur.eR = rowNo;
    else { groups.push(cur); cur = { sR: rowNo, eR: rowNo, key: keyStr }; }
  }
  if (cur) groups.push(cur);
  if (!groups.length) {
    note_(ctx, '小計を入れるデータがありません');
    return;
  }
  var nc = t.lastCol - t.firstCol + 1;
  var labelCol = t.firstCol;
  if (sumIndices.indexOf(labelCol) >= 0) {
    for (var lc = t.firstCol; lc <= t.lastCol; lc++) {
      if (sumIndices.indexOf(lc) < 0) { labelCol = lc; break; }
    }
  }
  // 行挿入と値・書式を 2 次元配列で一括反映（ループ内 API 呼び出しを回避）
  var nrOrig = t.lastData - t.firstData + 1;
  var srcRg = sh.getRange(t.firstData, t.firstCol, nrOrig, nc);
  var srcVals = srcRg.getValues();
  var srcForms = srcRg.getFormulas();
  var srcWeights = srcRg.getFontWeights();
  var srcBgs = srcRg.getBackgrounds();
  var srcColors = srcRg.getFontColors();
  var srcNumFmts = srcRg.getNumberFormats();
  var outVals = [], outWeights = [], outBgs = [], outColors = [], outNumFmts = [];
  var insertedSoFar = 0, gIdx = 0;
  for (var rOff = 0; rOff < nrOrig; rOff++) {
    var origRowNo = t.firstData + rOff;
    var rowVals = [];
    for (var ci = 0; ci < nc; ci++) {
      var f = srcForms[rOff][ci];
      rowVals.push(f ? shiftFormula_(f, insertedSoFar) : srcVals[rOff][ci]);
    }
    outVals.push(rowVals);
    outWeights.push(srcWeights[rOff].slice());
    outBgs.push(srcBgs[rOff].slice());
    outColors.push(srcColors[rOff].slice());
    outNumFmts.push(srcNumFmts[rOff].slice());
    if (gIdx < groups.length && origRowNo === groups[gIdx].eR) {
      var g = groups[gIdx];
      var sNew = g.sR + insertedSoFar;
      var eNew = g.eR + insertedSoFar;
      var subRow = [], subW = [];
      for (var sci = 0; sci < nc; sci++) {
        subRow.push('');
        subW.push('bold');
      }
      subRow[labelCol - t.firstCol] = '小計';
      sumIndices.forEach(function (si) {
        var cl = colLetter_(si);
        subRow[si - t.firstCol] = '=SUBTOTAL(9, ' + cl + sNew + ':' + cl + eNew + ')';
      });
      outVals.push(subRow);
      outWeights.push(subW);
      outBgs.push(srcBgs[rOff].slice());
      outColors.push(srcColors[rOff].slice());
      outNumFmts.push(srcNumFmts[rOff].slice());
      insertedSoFar++;
      gIdx++;
    }
  }
  sh.insertRowsAfter(t.lastData, groups.length);
  var dstRg = sh.getRange(t.firstData, t.firstCol, outVals.length, nc);
  dstRg.setValues(outVals);
  dstRg.setFontWeights(outWeights);
  dstRg.setBackgrounds(outBgs);
  dstRg.setFontColors(outColors);
  dstRg.setNumberFormats(outNumFmts);
  chg_(ctx, sh, '表', groups.length + ' か所に小計行を挿入');
};

// 棚: formula.guard
// 題: エラー表示を消す（IFERRORで包む）
// 分類: 集計
// 語: エラーが出ないように|エラーを隠して|エラーを空白に|IFERROR|DIV/0|エラー表示を空白|エラー表示を消|エラーを表示しない|計算式 エラー 回避|エラー 回避 囲む
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
  var forms = rg.getFormulas(), vals = rg.getValues(), out = [], changed = 0;
  var fb = op.fallback !== undefined
    ? (typeof op.fallback === 'string' ? ('"' + op.fallback.replace(/"/g, '""') + '"') : op.fallback)
    : '""';
  for (var r = 0; r < forms.length; r++) {
    var rowOut = [];
    for (var c = 0; c < forms[r].length; c++) {
      var f = forms[r][c];
      if (f && f.indexOf('=IFERROR(') !== 0) {
        rowOut.push('=IFERROR(' + f.replace(/^=/, '') + ', ' + fb + ')');
        changed++;
      } else {
        rowOut.push(f || vals[r][c]);
      }
    }
    out.push(rowOut);
  }
  if (changed) rg.setValues(out);
  chg_(ctx, sh, rg.getA1Notation(), changed + ' 個の数式を IFERROR で保護');
};

// 棚: formula.tovalue
// 題: 計算式を確定した値に変える
// 分類: 集計
// 語: 式を値にして|数式を値に|計算結果を値に|値貼り付け|式を値に置き換え|値に変換|計算式を値に|の計算式を値|式を値に置き換|式を値に変え
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
  var forms = rg.getFormulas(), vals = rg.getValues(), out = [], changed = 0;
  for (var r = 0; r < forms.length; r++) {
    var rowOut = [];
    for (var c = 0; c < forms[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) {
        rowOut.push('=' + fnName + '(' + f.replace(/^=/, '') + ', ' + dig + ')');
        changed++;
      } else if (typeof v === 'number' && !isNaN(v)) {
        rowOut.push('=' + fnName + '(' + v + ', ' + dig + ')');
        changed++;
      } else {
        rowOut.push(v);
      }
    }
    out.push(rowOut);
  }
  if (!changed) { note_(ctx, '丸める数値・式が見つかりませんでした（' + rg.getA1Notation() + '）'); return; }
  rg.setValues(out);
  chg_(ctx, sh, rg.getA1Notation(), fnName + '（桁: ' + dig + '）を適用（' + changed + ' 件）');
};

// 棚: date.parts
// 題: 日付から年・月・曜日・年度の列を足す
// 分類: 集計
// 語: 年の列|月の列|曜日の列|年度の列|日付から年|日付から月|日付から曜日|曜日を足して|曜日を取り出して|日付の列から曜日|日付の列から年|日付の列から月
// 違い: 日付の入力なら fill.date。書式変更なら format
// 引数: col*=列, part*=選択(year/month/day/weekday/quarter/fiscal), name=文字, at=列
// 頼み: part=weekday<曜日 ; part=fiscal<年度 ; part=year<年 ; part=month<月 ; col~([^\sの]+)から(?:年|月|日|曜日|年度|四半期)
// 例: 「日付から曜日の列を作って」 → {"shelf":"date.parts","col":"日付","part":"weekday"}
// 触る: 値 書式
SHELF['date.parts'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col', 'part']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); if (atCol <= ci) ci++; t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var part = String(op.part).toLowerCase();
  var nameMap = { year: '年', month: '月', day: '日', weekday: '曜日', quarter: '四半期', fiscal: '年度' };
  var name = op.name || nameMap[part] || '日付要素';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
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
        : part === 'fiscal' ? ('=IF(MONTH(' + cellRef + ')>=4,YEAR(' + cellRef + '),YEAR(' + cellRef + ')-1)')
        : ('=ROUNDUP(MONTH(' + cellRef + ')/3, 0)');
      formulas.push([f]);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '日付抽出列「' + name + '」を追加');
};

// 棚: text.join
// 題: 複数の列をつないで新しい列を作る
// 分類: 集計
// 語: 列をつないで|結合して1列に|文字列をつなげて|氏名の列を作って|列を連結|列を結合|つなげて|の列を結合|と名を結合
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
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); colList = colList.map(function (c) { return atCol <= c ? c + 1 : c; }); t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '結合';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var sep = op.sep !== undefined ? String(op.sep) : ' ';
  var sepEsc = sep.replace(/"/g, '""');
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var parts = colList.map(function (ci) { return colLetter_(ci) + r; });
      var f = sep ? ('=JOIN("' + sepEsc + '", ' + parts.join(', ') + ')') : ('=CONCATENATE(' + parts.join(', ') + ')');
      formulas.push([f]);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '連結列「' + name + '」を追加');
};

// 棚: text.case
// 題: 文字列の大文字・小文字・全角・半角をそろえる
// 分類: 集計
// 語: 大文字にそろえて|小文字にして|半角にそろえて|全角にして|PROPER|UPPER|LOWER|小文字に変換|大文字に変換|半角 全角 統一|全角 半角 統一
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
  // 値の列を式の列に変えない：文字の値は Google の関数で変換した「値」を書き戻す。もとが式のセルだけ式で包む。数・日付・空は触らない
  var forms = rg.getFormulas(), vals = rg.getValues(), tmp = [], isText = [], n = 0;
  for (var r = 0; r < forms.length; r++) {
    tmp.push([]); isText.push([]);
    for (var c = 0; c < forms[r].length; c++) {
      var f0 = forms[r][c], v0 = vals[r][c], txt = !f0 && typeof v0 === 'string' && v0 !== '';
      isText[r].push(txt);
      if (f0) { tmp[r].push('=' + fnName + '(' + f0.replace(/^=/, '') + ')'); n++; }
      else if (txt) { tmp[r].push('=' + fnName + '("' + v0.replace(/"/g, '""') + '")'); n++; }
      else tmp[r].push(v0 === '' ? '' : v0);
    }
  }
  if (!n) { note_(ctx, '文字のセルがないので変えていません（' + rg.getA1Notation() + '）'); return; }
  rg.setValues(tmp);
  SpreadsheetApp.flush();
  var got = rg.getValues();
  var textKeepMap = [], hasKeepFmt = false;
  for (var r2 = 0; r2 < tmp.length; r2++) {
    textKeepMap.push([]);
    for (var c2 = 0; c2 < tmp[r2].length; c2++) {
      var keepCell = false;
      if (isText[r2][c2]) {
        var sVal = String(got[r2][c2]);
        tmp[r2][c2] = sVal;
        if (/^[+-]?0\d/.test(sVal) || /^\d{1,4}[-\/]\d{1,4}(?:[-\/]\d{1,4})?$/.test(sVal) || /^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(sVal)) {
          keepCell = true;
          hasKeepFmt = true;
        }
      }
      textKeepMap[r2].push(keepCell);
    }
  }
  if (hasKeepFmt && typeof rg.getNumberFormats === 'function' && typeof rg.setNumberFormats === 'function') {
    var fmtsTc = rg.getNumberFormats();
    for (var r3 = 0; r3 < textKeepMap.length; r3++) for (var c3 = 0; c3 < textKeepMap[r3].length; c3++) {
      if (textKeepMap[r3][c3]) fmtsTc[r3][c3] = '@';
    }
    rg.setNumberFormats(fmtsTc);
  }
  rg.setValues(tmp);
  chg_(ctx, sh, rg.getA1Notation(), fnName + ' でそろえた');
};

// 棚: text.affix
// 題: 文字の先頭・末尾に文字を付ける
// 分類: 整える
// 語: 先頭に文字|末尾に文字|先頭に付け|末尾に付け|後ろに付け|前に付け|接頭辞|接尾辞|末尾に様|先頭にID
// 違い: 複数列をつなぐなら text.join、文字の置換は replace
// 引数: col=列, range=範囲, prefix=文字, suffix=文字, remove=真偽=false
// 頼み: remove=true<外し|削|取り除|消 ; prefix~(?:先頭|頭|前)に[『「]([^』」]+)[』」] ; suffix~(?:末尾|後ろ|最後)に[『「]([^』」]+)[』」] ; prefix~先頭の[『「]([^』」]+)[』」] ; suffix~末尾の[『「]([^』」]+)[』」]
// どれか: prefix suffix
// 例: 「顧客名列の末尾に「様」を付けて」 → {"shelf":"text.affix","col":"顧客名","suffix":"様"}
// 例: 「品番列の先頭に「ID-」を付けて」 → {"shelf":"text.affix","col":"品番","prefix":"ID-"}
// 触る: 値
// 控え: 今
SHELF['text.affix'] = function (ctx, op) {
  var pref = op.prefix !== undefined ? String(op.prefix) : '';
  var suff = op.suffix !== undefined ? String(op.suffix) : '';
  if (!pref && !suff) throw new ArgError('棚「text.affix」に prefix か suffix のどちらかが要ります');
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    var t2 = needTable_(sh);
    rg = dataRange_(t2);
  }
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) { vals[r][c] = f; continue; }
      if (isBlank_(v)) continue;
      var s = String(v), ns = s;
      if (op.remove) {
        if (pref && ns.indexOf(pref) === 0) ns = ns.slice(pref.length);
        if (suff && ns.length >= suff.length && ns.slice(-suff.length) === suff) ns = ns.slice(0, ns.length - suff.length);
      } else {
        if (pref && ns.indexOf(pref) !== 0) ns = pref + ns;
        if (suff && !(ns.length >= suff.length && ns.slice(-suff.length) === suff)) ns = ns + suff;
      }
      if (ns !== s) { vals[r][c] = ns; changed++; }
    }
  }
  if (!changed) {
    note_(ctx, '変更対象のセルはありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '先頭/末尾の文字を' + (op.remove ? '削除' : '付与') + '（' + changed + ' 件）');
};

// 棚: calc.if
// 題: 条件分岐（IF式）の判定列を足す
// 分類: 集計
// 語: 条件分岐|IF文の列|IF式|判定列を足|合格判定|達成判定|ならマル|条件で判定
// 違い: 汎用数式なら calc.col、条件に合う件数なら count.if
// 引数: col*=列, when*=選択(ge/gt/le/lt/eq/ne/contains/blank/notblank)=ge, value=文字, then_val=文字=○, else_val=文字=×, name=文字=判定, at=列
// 頼み: when=ge<以上 ; when=le<以下 ; when=gt<より大|超える|超え|上回る|上回っ ; when=lt<未満|より小|下回る|下回っ|届かない|届いていない|届いてない ; when=contains<を含む|含む ; when=blank<空白|空欄 ; when=notblank<空白以外|空欄以外 ; col~([^\sがは、。]+?)(?:列)?(?:が|は)[^がは、。]*?(?:なら|判定) ; value~(?:が|は)([0-9]+(?:\.[0-9]+)?)[^、。]*?(?:なら|判定) ; then_val~なら([^\sそう、。]+) ; else_val~(?!そう)なければ([^\sの、。]+)
// 例: 「金額が10000以上なら○そうでなければ×の判定列を足して」 → {"shelf":"calc.if","col":"金額","when":"ge","value":"10000"}
// 触る: 値 書式
// 控え: 今
SHELF['calc.if'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['col', 'when']);
  var ci = colIndexOf_(t, op.col);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) { insertColsSafe_(ctx, sh, atCol, 1, true); if (atCol <= ci) ci++; t = needTable_(sh); }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '判定';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var when = String(op.when || 'ge').toLowerCase();
  var valRaw = op.value !== undefined ? String(op.value) : '';
  var valNumStr = valRaw.replace(/,/g, '').trim();
  var isNumVal = valNumStr !== '' && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(valNumStr);
  var valExpr = isNumVal ? valNumStr : ('"' + valRaw.replace(/"/g, '""') + '"');
  var lit = function (x) {
    var s = String(x);
    return /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(s.trim()) ? s.trim() : ('"' + s.replace(/"/g, '""') + '"');
  };
  var thenExpr = lit(op.then_val !== undefined ? op.then_val : '○');
  var elseExpr = lit(op.else_val !== undefined ? op.else_val : '×');
  var cl = colLetter_(ci), numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var ref = cl + r, cond;
      if (when === 'blank') cond = ref + '=""';
      else if (when === 'notblank') cond = ref + '<>""';
      else if (when === 'contains') cond = 'ISNUMBER(FIND("' + valRaw.replace(/"/g, '""') + '",' + ref + '))';
      else if (when === 'ge') cond = ref + '>=' + valExpr;
      else if (when === 'gt') cond = ref + '>' + valExpr;
      else if (when === 'le') cond = ref + '<=' + valExpr;
      else if (when === 'lt') cond = ref + '<' + valExpr;
      else if (when === 'ne') cond = ref + '<>' + valExpr;
      else cond = ref + '=' + valExpr;
      formulas.push(['=IF(' + cond + ',' + thenExpr + ',' + elseExpr + ')']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '判定列「' + name + '」を追加');
};

// 棚: date.diff
// 題: 2つの日付の差（日数・月数・年数）の列を足す
// 分類: 集計
// 語: 日数の差|経過日数|日付の差|営業日数|経過月数|経過年数|何日経過|期間の日数
// 違い: 数値の差や伸び率なら calc.diff、年月の抜き出しなら date.parts
// 引数: start_col*=列, end_col=列, unit=選択(days/months/years/workdays)=days, name=文字, at=列
// 頼み: unit=workdays<営業日 ; unit=months<月数|か月|ヶ月 ; unit=years<年数|勤続年数|年齢
// 例: 「開始日と終了日の経過日数の列を足して」 → {"shelf":"date.diff","start_col":"開始日","end_col":"終了日","unit":"days"}
// 触る: 値 書式
// 控え: 今
SHELF['date.diff'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  need_(op, ['start_col']);
  var sCi = colIndexOf_(t, op.start_col);
  var eCi = op.end_col ? colIndexOf_(t, op.end_col) : 0;
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= sCi) sCi++;
    if (eCi && atCol <= eCi) eCi++;
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var unit = String(op.unit || 'days').toLowerCase();
  var defNames = { days: '日数', months: '月数', years: '年数', workdays: '営業日数' };
  var name = op.name || defNames[unit] || '日数';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var sl = colLetter_(sCi), el = eCi ? colLetter_(eCi) : '';
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var sRef = sl + r, eRef = el ? (el + r) : 'TODAY()';
      var diffExpr = unit === 'months' ? ('DATEDIF(' + sRef + ',' + eRef + ',"M")')
        : unit === 'years' ? ('DATEDIF(' + sRef + ',' + eRef + ',"Y")')
        : unit === 'workdays' ? ('NETWORKDAYS(' + sRef + ',' + eRef + ')')
        : (eRef + '-' + sRef);
      var blankCheck = el ? ('OR(' + sRef + '="",' + eRef + '="")') : (sRef + '=""');
      formulas.push(['=IF(' + blankCheck + ',"",' + diffExpr + ')']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '日付差列「' + name + '」を追加');
};

// 棚: unique.list
// 題: 重複を除いたユニーク一覧を別シートへ出す
// 分類: 集計
// 語: ユニーク一覧|重複なしの一覧|ユニーク抽出|重複を省いた一覧|一覧表を抽出|別シートにユニーク|種類ごとの件数|ユニークリスト
// 違い: 元の表から重複行を消すなら dedupe。金額も集計するなら summary
// 引数: col*=列, with_count=真偽=true, into=文字=一覧
// 例: 「得意先列の重複を除いた一覧を件数付きで作って」 → {"shelf":"unique.list","col":"得意先"}
// 触る: シート構成 値 書式
// 控え: 先
SHELF['unique.list'] = function (ctx, op) {
  need_(op, ['col']);
  var ss = ctx.ss, src = sheetOf_(ss, op.sheet, ctx.sheetName), t = needTable_(src);
  var ci = colIndexOf_(t, op.col);
  var intoName = String(op.into || '一覧').trim();
  var withCount = op.with_count !== false;
  var seen = {}, keys = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var v = t.vals[r - 1][ci - 1];
    if (isBlank_(v)) continue;
    var k = String(v);
    if (!seen[k]) { seen[k] = 1; keys.push(v); }
  }
  if (!keys.length) {
    note_(ctx, op.col + '列にデータがありません（一覧を作成していません）');
    return;
  }
  var colHead = String(t.vals[t.headerRow - 1][ci - 1] || op.col);
  var sq = q_(src.getName()), rangeRef = sq + '!$' + colLetter_(ci) + '$' + t.firstData + ':$' + colLetter_(ci) + '$' + t.lastData;
  var grid = [withCount ? [colHead, '件数'] : [colHead]];
  keys.forEach(function (k, idx) {
    grid.push(withCount ? [k, '=COUNTIF(' + rangeRef + ',A' + (idx + 2) + ')'] : [k]);
  });
  if (withCount) grid.push(['合計', '=SUM(B2:B' + (keys.length + 1) + ')']);
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var nc = grid[0].length;
  dst.getRange(1, 1, grid.length, nc).setValues(grid);
  dst.getRange(1, 1, 1, nc).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold').setHorizontalAlignment('center');
  ctx.curSheet = src.getName();
  chg_(ctx, dst, a1_(1, 1, grid.length, nc), op.col + 'のユニーク一覧（' + keys.length + ' 件）');
};

// 棚: crosstab
// 題: 2項目の縦横クロス集計表を式つきで作る
// 分類: 集計
// 語: クロス集計|縦横集計|マトリクス集計|マトリックス|2軸集計|二次元集計|クロス表|行と列で集計
// 違い: 1項目の集計表なら summary、ピボット機能そのものを作るなら pivot.new
// 引数: row_col*=列, col_col*=列, val_col=列, func=選択(sum/count/avg)=count, into=文字=クロス集計
// 頼み: func=sum<合計 ; func=avg<平均 ; func=count<件数|回数|人数
// 例: 「部門を行、ステータスを列にしたクロス集計表を作って」 → {"shelf":"crosstab","row_col":"部門","col_col":"ステータス"}
// 触る: シート構成 値 書式
// 控え: 先
SHELF['crosstab'] = function (ctx, op) {
  need_(op, ['row_col', 'col_col']);
  var ss = ctx.ss, src = sheetOf_(ss, op.sheet, ctx.sheetName), t = needTable_(src);
  var rCi = colIndexOf_(t, op.row_col), cCi = colIndexOf_(t, op.col_col);
  var func = String(op.func || (op.val_col ? 'sum' : 'count')).toLowerCase();
  var vCi = 0;
  if (op.val_col) {
    vCi = colIndexOf_(t, op.val_col);
  } else if (func !== 'count') {
    for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
      if (ci !== rCi && ci !== cCi && !isNoCol_(t, ci) && isNumberCol_(t, ci)) { vCi = ci; break; }
    }
    if (!vCi) throw new ArgError('集計する数値列が見つかりません。val_col で指定してください');
  }
  var rKeys = [], cKeys = [], rSeen = {}, cSeen = {};
  for (var r = t.firstData; r <= t.lastData; r++) {
    var rk = t.vals[r - 1][rCi - 1], ck = t.vals[r - 1][cCi - 1];
    if (!isBlank_(rk)) { var rks = String(rk); if (!rSeen[rks]) { rSeen[rks] = 1; rKeys.push(rk); } }
    if (!isBlank_(ck)) { var cks = String(ck); if (!cSeen[cks]) { cSeen[cks] = 1; cKeys.push(ck); } }
  }
  if (!rKeys.length || !cKeys.length) throw new ArgError('クロス集計する見出し値が見つかりません');
  var sq = q_(src.getName()), rng = function (c) { return sq + '!$' + colLetter_(c) + '$' + t.firstData + ':$' + colLetter_(c) + '$' + t.lastData; };
  var rowHead = String(t.vals[t.headerRow - 1][rCi - 1] || op.row_col);
  var hdr = [rowHead].concat(cKeys.map(String));
  if (func !== 'avg') hdr.push('合計');
  var grid = [hdr];
  rKeys.forEach(function (rk, ri) {
    var rr = ri + 2, row = [rk];
    cKeys.forEach(function (ck, cj) {
      var cl = colLetter_(cj + 2);
      if (func === 'sum') row.push('=SUMIFS(' + rng(vCi) + ',' + rng(rCi) + ',$A' + rr + ',' + rng(cCi) + ',' + cl + '$1)');
      else if (func === 'avg') row.push('=IFERROR(AVERAGEIFS(' + rng(vCi) + ',' + rng(rCi) + ',$A' + rr + ',' + rng(cCi) + ',' + cl + '$1),0)');
      else row.push('=COUNTIFS(' + rng(rCi) + ',$A' + rr + ',' + rng(cCi) + ',' + cl + '$1)');
    });
    if (func !== 'avg') row.push('=SUM(B' + rr + ':' + colLetter_(cKeys.length + 1) + rr + ')');
    grid.push(row);
  });
  if (func !== 'avg') {
    var tot = ['合計'];
    for (var tj = 0; tj < cKeys.length + 1; tj++) {
      var tl = colLetter_(tj + 2);
      tot.push('=SUM(' + tl + '2:' + tl + (rKeys.length + 1) + ')');
    }
    grid.push(tot);
  }
  var intoName = String(op.into || 'クロス集計').trim();
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  dst.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
  ctx.curSheet = src.getName();
  chg_(ctx, dst, a1_(1, 1, grid.length, grid[0].length), 'クロス集計表（' + rKeys.length + '×' + cKeys.length + '）を作成');
  tidyRange_(ctx, dst, null);
};

// 棚: formula.list
// 題: シートやブックの数式一覧を別シートに出す
// 分類: 集計
// 語: 数式一覧|数式の一覧|式を一覧|どこに式|数式をチェック|関数一覧|関数を調べ|数式リスト
// 違い: 式を値に変えるなら formula.tovalue、エラー診断は audit.check
// 引数: all_sheets=真偽=false, into=文字=数式一覧
// 頼み: all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体
// 例: 「このシートの数式一覧を別シートに出して」 → {"shelf":"formula.list"}
// 触る: シート構成 値 書式
// 控え: 先
SHELF['formula.list'] = function (ctx, op) {
  var ss = ctx.ss, intoName = String(op.into || '数式一覧').trim();
  var targets = op.all_sheets
    ? ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え' && s.getName() !== intoName; })
    : [sheetCtx_(ctx, op)];
  var rowsOut = [], errPat = /^#(REF!|VALUE!|DIV\/0!|N\/A|NAME\?|NUM!|NULL!|ERROR!)/, CAP = 5000;
  targets.forEach(function (s) {
    if (rowsOut.length >= CAP) return;
    var lr = s.getLastRow(), lc = s.getLastColumn();
    if (lr < 1 || lc < 1) return;
    var rg = s.getRange(1, 1, lr, lc);
    var forms = rg.getFormulas(), disp = rg.getDisplayValues();
    for (var r = 0; r < forms.length && rowsOut.length < CAP; r++) {
      for (var c = 0; c < forms[r].length && rowsOut.length < CAP; c++) {
        var f = forms[r][c];
        if (f) {
          var dv = String(disp[r][c] || '');
          rowsOut.push([s.getName(), a1_(r + 1, c + 1), dv, "'" + f, errPat.test(dv) ? 'エラー' : '正常']);
        }
      }
    }
  });
  if (!rowsOut.length) {
    note_(ctx, '数式セルは見つかりませんでした（作成していません）');
    return;
  }
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var out = [['シート', 'セル', '表示値', '数式', '状態']].concat(rowsOut);
  dst.getRange(1, 1, out.length, 5).setValues(out);
  dst.getRange(1, 1, 1, 5).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, out.length, 5), '数式一覧を作成（' + rowsOut.length + ' 件）');
};

// 棚: date.age
// 題: 日付から年齢・勤続年数などの列を足す
// 分類: 集計
// 語: 年齢を計算|満年齢|年齢を出|勤続年数|経過年数|経過月数|生年月日から年齢|入社日から勤続
// 違い: 2つの日付列の差は date.diff。年や月の取り出しは date.parts
// 引数: col*=列, unit=選択(years/months/days)=years, name=文字, at=列
// 頼み: unit=months<月数|経過月数|ヶ月 ; unit=days<日数|経過日数 ; col~([^\sの]+?)(?:列)?から(?:満?年齢|勤続|経過)
// 例: 「生年月日から年齢の列を足して」 → {"shelf":"date.age","col":"生年月日"}
// 触る: 値 書式
// 控え: 今
SHELF['date.age'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var unit = String(op.unit || 'years').toLowerCase();
  var uMap = { years: 'Y', months: 'M', days: 'D' };
  var code = uMap[unit] || 'Y';
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= ci) ci++;
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var defName = code === 'M' ? '経過月数' : (code === 'D' ? '経過日数' : '年齢');
  var name = op.name || defName;
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var cl = colLetter_(ci);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var ref = cl + r;
      formulas.push(['=IF(OR(' + ref + '="",' + ref + '>TODAY()),"",DATEDIF(' + ref + ',TODAY(),"' + code + '"))']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
    rg.setNumberFormat(STYLE.numFmt);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', name + 'の列を追加');
};

// 棚: calc.tax
// 題: 金額列から税込・税抜・消費税額の計算列を足す
// 分類: 集計
// 語: 消費税を計算|税込価格|税抜価格|税額を計算|消費税の列|税込金額|税抜金額|消費税10|税率8
// 違い: 汎用計算式は calc.col。丸めだけ行うなら round
// 引数: col*=列, mode=選択(in/out/tax)=in, rate=数=10, round=選択(floor/round/ceil)=floor, name=文字, at=列
// 頼み: mode=out<税抜|本体価格 ; mode=tax<税額|消費税額|消費税だけ ; mode=in<税込 ; rate~(?:消費税|税率)\s*([0-9]+(?:\.[0-9]+)?)\s*% ; round=round<四捨五入 ; round=ceil<切り上げ|切上げ ; col~([^\sの]+?)(?:列)?から(?:税込|税抜|消費税|税額)
// 例: 「金額列から税込金額の列を足して」 → {"shelf":"calc.tax","col":"金額"}
// 触る: 値 書式
// 控え: 今
SHELF['calc.tax'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var mode = String(op.mode || 'in').toLowerCase();
  var rateNum = op.rate !== undefined && op.rate !== '' ? Number(op.rate) : 10;
  if (!isFinite(rateNum) || rateNum < 0) rateNum = 10;
  var ratioStr = String(rateNum / 100);
  var roundMode = String(op.round || 'floor').toLowerCase();
  var roundFn = roundMode === 'round' ? 'ROUND' : (roundMode === 'ceil' ? 'ROUNDUP' : 'ROUNDDOWN');
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= ci) ci++;
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var defName = mode === 'out' ? '税抜' : (mode === 'tax' ? '消費税' : '税込');
  var name = op.name || defName;
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var cl = colLetter_(ci);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      var ref = cl + r;
      var expr = mode === 'out'
        ? (ref + '/(1+' + ratioStr + ')')
        : (mode === 'tax' ? (ref + '*' + ratioStr) : (ref + '*(1+' + ratioStr + ')'));
      formulas.push(['=IF(' + ref + '="","",' + roundFn + '(' + expr + ',0))']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
    var rg = sh.getRange(t.firstData, atCol, numRows, 1);
    rg.setNumberFormat(STYLE.numFmt);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', name + '（税率 ' + rateNum + '%）の列を追加');
};

// 棚: col.compare
// 題: 表内の2つの列を比較して一致・不一致列を足す
// 分類: 集計
// 語: 2列を比較|列を比較|値が一致|差分を判定|2つの列を比べ|同じ値か確認|比較結果の列|突合して
// 違い: 2つのシートを比べるなら sheet.diff。数値の引き算なら calc.diff
// 引数: col_a*=列, col_b*=列, match_val=文字=一致, diff_val=文字=不一致, name=文字=比較結果, at=列
// 頼み: col_a~([^\sと、。]+?)と([^\sを、。]+?)を比較 ; col_b~[^\sと、。]+?と([^\sを、。]+?)を比較
// 例: 「予算と実績を比較して一致判定の列を足して」 → {"shelf":"col.compare","col_a":"予算","col_b":"実績"}
// 触る: 値 書式
// 控え: 今
SHELF['col.compare'] = function (ctx, op) {
  need_(op, ['col_a', 'col_b']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ca = colIndexOf_(t, op.col_a), cb = colIndexOf_(t, op.col_b);
  var atCol = op.at ? colIndexOf_(t, op.at) : (t.lastCol + 1);
  if (op.at && atCol <= t.lastCol) {
    insertColsSafe_(ctx, sh, atCol, 1, true);
    if (atCol <= ca) ca++;
    if (atCol <= cb) cb++;
    t = needTable_(sh);
  }
  if (atCol > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), atCol - sh.getMaxColumns());
  var name = op.name || '比較結果';
  copyHeaderStyle_(sh, t.headerRow, t.firstCol, atCol, name, t.headerRows || 1);
  var escQ = function (s) { return '"' + String(s).replace(/"/g, '""') + '"'; };
  var mTxt = escQ(op.match_val !== undefined ? op.match_val : '一致');
  var dTxt = escQ(op.diff_val !== undefined ? op.diff_val : '不一致');
  var la = colLetter_(ca), lb = colLetter_(cb);
  var numRows = t.lastData - t.firstData + 1;
  if (numRows > 0) {
    var formulas = [];
    for (var r = t.firstData; r <= t.lastData; r++) {
      formulas.push(['=IF(AND(' + la + r + '="",' + lb + r + '=""),"",IF(' + la + r + '=' + lb + r + ',' + mTxt + ',' + dTxt + '))']);
    }
    setFormulasAllRows_(ctx, sh, t.firstData, atCol, formulas);
  }
  chg_(ctx, sh, colLetter_(atCol) + '列', '2列比較結果「' + name + '」を追加');
};
