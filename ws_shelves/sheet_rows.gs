// 行と列の棚

// 棚: rows
// 題: 行・列の挿入・削除・移動
// 分類: 行と列
// 語: 行を削除|行を消|行を挿入|行を追加|列を削除|列を挿入|行を移動|列を入れ替
// 引数: action=選択(insert/delete/move)=delete, rows=行[], cols=列[], at=文字, count=数, from=文字, to=文字
// どれか: rows cols
// 例: 「3行目から5行目を消して」 → {"shelf":"rows","rows":[3,4,5]}
// 例: 「A列とB列を入れ替えて」 → {"shelf":"rows","action":"move","cols":["A"],"from":"A","to":"B"}
// 違い: 移動の to は、動かした後にその列・行が来る位置
// 危ない: 消す
// 触る: 値 書式
// 検索: しない
SHELF['rows'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), act = op.action || (op.cols ? 'delete' : 'delete');
  var isCol = !!op.cols, list = (isCol ? op.cols : op.rows) || [];
  var tw;
  var getTw = function () { if (tw === undefined) tw = findTable_(sh); return tw; };
  var colRef = function (x) {
    if (typeof x === 'number') return x;
    if (/^[A-Za-z]{1,3}$/.test(String(x).trim())) return colNum_(x);
    return getTw() ? colIndexOf_(getTw(), x) : colNum_(x);
  };
  if (act === 'insert') {
    var at = op.at || list[0]; need_({ shelf: 'rows', at: at }, ['at']);
    var cnt = op.count || 1;
    var atNum = isCol ? colRef(at) : parseInt(at);
    if (isCol) sh.insertColumnsBefore(atNum, cnt); else sh.insertRowsBefore(atNum, cnt);
    chg_(ctx, sh, (isCol ? (typeof at === 'number' ? colLetter_(at) : at) + '列の前' : at + '行目の前'), cnt + ' ' + (isCol ? '列' : '行') + '挿入');
  } else if (act === 'delete') {
    if (!list.length) throw new ArgError('棚「rows」に rows（行番号の配列）か cols が要ります');
    var nums = list.map(function (x) { return isCol ? colRef(x) : parseInt(x); }).sort(function (a, b) { return b - a; });
    var max = isCol ? sh.getMaxColumns() : sh.getMaxRows();
    nums.forEach(function (n) { if (n < 1 || n > max) throw new ArgError((isCol ? '列' : '行') + '番号 ' + n + ' は範囲外です（1〜' + max + '）'); });
    var peek = nums.map(function (n) { var v = isCol ? sh.getRange(1, n, Math.min(sh.getLastRow() || 1, 50), 1).getDisplayValues() : sh.getRange(n, 1, 1, Math.max(1, sh.getLastColumn())).getDisplayValues()[0]; return (isCol ? colLetter_(n) + '列' : n + '行目') + '「' + String(isCol ? v.map(function (x) { return x[0]; }).filter(Boolean).slice(0, 2).join('/') : v.filter(Boolean).slice(0, 3).join('/')).slice(0, 24) + '」'; });
    var wide = false;   // 表の外まで／明細の半分より多くを消す削除は、ok=True でも 1 回止める
    if (getTw()) wide = isCol ? nums.some(function (n) { return n < tw.firstCol || n > tw.lastCol; }) : (nums.some(function (n) { return n < tw.headerRow || n > (tw.totalRow || tw.lastData); }) || wideRowCount_(tw, nums.length));
    guardDelete_(ctx, peek.reverse().join('、') + ' を削除します', wide, nums.length + (isCol ? ' 列' : ' 行'));
    nums.forEach(function (n) { if (isCol) sh.deleteColumn(n); else sh.deleteRow(n); });
    chg_(ctx, sh, nums.slice().reverse().join('・') + (isCol ? ' 列' : ' 行目'), '削除');
  } else if (act === 'move') {
    need_(op, ['from', 'to']);
    // to＝動かした後にその列（行）が来る位置。moveColumns/moveRows は「その位置の手前へ」入れるので、右（下）へ動かすときは動かす幅だけ先へ渡す
    try {
      if (isCol) { var f = colRef(op.from), to = colRef(op.to); sh.moveColumns(sh.getRange(1, f, 1, 1), to > f ? to + 1 : to); }
      else { var fr = parseInt(op.from), cn = op.count || 1, tr = parseInt(op.to); sh.moveRows(sh.getRange(fr, 1, cn, 1), tr > fr ? tr + cn : tr); }
      SpreadsheetApp.flush();   // 結合をまたぐ移動の失敗は、書き込みが反映されるここで出る（棚の外で出ると「内部のエラー」になる）
    } catch (e) {
      if (e && e.isArg) throw e;
      if (/結合|merge/i.test(String(e && e.message || e))) throw new ArgError('結合されたセルをまたぐ位置には動かせません。結合を解除してから（または結合のない列・行で）やり直してください');
      throw e;
    }
    chg_(ctx, sh, op.from + ' → ' + op.to, '移動');
  } else throw new ArgError('棚「rows」の action は insert・delete・move です');
};

// 棚: rows.insert
// 題: 行を挿入する
// 分類: 行と列
// 語: 行を挿入|行を追加|行を足|行を差し込|空行を入れ|間に行|行を増や
// 違い: 列なら cols.insert。表の下に足すだけなら write
// 引数: at*=文字, count=数
// 頼み: at~([0-9]+)行目の(?:前|上) ; count~([0-9]+)行(?:を|足|追加|挿入)
// 例: 「3行目の前に2行足して」 → {"shelf":"rows.insert","at":3,"count":2}
// 触る: 値 書式
SHELF['rows.insert'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'insert', at: op.at, count: op.count, sheet: op.sheet });
};

// 棚: rows.delete
// 題: 行を削除する
// 分類: 行と列
// 語: 行を削除|行を消|行目を消|行を取り除|行を捨て|いらない|不要な行|まとめて削除|一気に消|まとめて消|一気に削除
// 違い: 列なら cols.delete。重複した行・空行だけなら seiri
// 引数: rows*=行[]
// 例: 「3行目から5行目を消して」 → {"shelf":"rows.delete","rows":[3,4,5]}
// 危ない: 消す
// 触る: 値 書式
SHELF['rows.delete'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'delete', rows: op.rows, sheet: op.sheet });
};

// 棚: rows.move
// 題: 行を移動する
// 分類: 行と列
// 語: 行を移動|行を動か|行を上へ|行を下へ|行の順番|行を入れ替|行を並べ替
// 違い: to＝動かした後にその行が来る位置。列なら cols.move。値で並べ替えるなら sort
// 引数: from*=文字, to*=文字, count=数
// 例: 「5行目を2行目の前に動かして」 → {"shelf":"rows.move","from":5,"to":2}
// 触る: 値 書式
SHELF['rows.move'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'move', from: op.from, to: op.to, count: op.count, sheet: op.sheet });
};

// 棚: cols.insert
// 題: 列を挿入する
// 分類: 行と列
// 語: 列を挿入|列を追加|空の列を足|間に列を足|列を1列足|列を差し込|空の列|間に列|列を増や
// 違い: 行なら rows.insert
// 引数: at*=列, count=数
// 頼み: at~[A-Z]{1,3}列と([A-Z]{1,3})列の間 ; at~([A-Z]{1,3})列の(?:前|左)
// 例: 「C列の前に列を1つ足して」 → {"shelf":"cols.insert","at":"C"}
// 触る: 値 書式
SHELF['cols.insert'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'insert', cols: [op.at], at: op.at, count: op.count, sheet: op.sheet });
};

// 棚: cols.delete
// 題: 列を削除する
// 分類: 行と列
// 語: 列を削除|列を消|列を取り除|列を捨て|不要な列|いらない|列ごと消
// 違い: 行なら rows.delete。中身だけ消すなら write
// 引数: cols*=列[]
// 例: 「B列を消して」 → {"shelf":"cols.delete","cols":["B"]}
// 危ない: 消す
// 触る: 値 書式
SHELF['cols.delete'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'delete', cols: op.cols, sheet: op.sheet });
};

// 棚: cols.move
// 題: 列を移動する
// 分類: 行と列
// 語: 列を移動|列を動か|列を入れ替|列の順番|列を左へ|列を右へ|列を並べ替
// 違い: to＝動かした後にその列が来る位置。行なら rows.move
// 引数: from*=列, to*=列
// 例: 「A列とB列を入れ替えて」 → {"shelf":"cols.move","from":"A","to":"B"}
// 触る: 値 書式
SHELF['cols.move'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'move', cols: [op.from], from: op.from, to: op.to, sheet: op.sheet });
};

// 棚: freeze
// 題: 見出しを固定する
// 分類: 行と列
// 語: 見出しを固定|行を固定|列を固定|枠を固定|動かない|スクロールしても|ウィンドウ枠の固定
// 違い: 固定を外すなら unfreeze
// 引数: rows=数=1, cols=数=0
// 頼み: rows~([0-9]+)行目?(?:まで)?(?:固定|フリーズ|動かない) ; cols=1<A列 ; cols~([0-9]+)列目
// 例: 「1行目の見出しを固定して」 → {"shelf":"freeze","rows":1}
// 例: 「見出し行とA列を固定して」 → {"shelf":"freeze","rows":1,"cols":1}
// 触る: 固定
// 控え: 今
SHELF['freeze'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var r = op.rows !== undefined ? parseInt(op.rows) : 1;
  var c = op.cols !== undefined ? parseInt(op.cols) : 0;
  var sid = sh.getSheetId(), bk = (ctx.bk || []).filter(function (x) { return x.id === sid; })[0];
  var curR = bk ? bk.frozenR : sh.getFrozenRows(), curC = bk ? bk.frozenC : sh.getFrozenColumns();
  try { if (curR !== r) sh.setFrozenRows(r); if (curC !== c) sh.setFrozenColumns(c); }
  catch (e) { throw new ArgError('結合セルの途中では固定できません（行 ' + r + '・列 ' + c + '）。結合を解除するか、結合をすべて含む行・列までを指定してください'); }
  chg_(ctx, sh, '', '行固定: ' + r + '、列固定: ' + c);
};

// 棚: unfreeze
// 題: 固定を外す
// 分類: 行と列
// 語: 固定を解除|固定を外|固定をやめ|固定をなく|枠固定を解除|固定しない
// 違い: 固定するなら freeze
// 引数: なし
// 例: 「ウィンドウ枠の固定を解除して」 → {"shelf":"unfreeze"}
// 触る: 固定
// 控え: 今
SHELF['unfreeze'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var sid = sh.getSheetId(), bk = (ctx.bk || []).filter(function (x) { return x.id === sid; })[0];
  var curR = bk ? bk.frozenR : sh.getFrozenRows(), curC = bk ? bk.frozenC : sh.getFrozenColumns();
  if (curR !== 0) sh.setFrozenRows(0);
  if (curC !== 0) sh.setFrozenColumns(0);
  chg_(ctx, sh, '', '固定を解除');
};

// 棚: rows.hide
// 題: 行を隠す
// 分類: 行と列
// 語: 行を隠|行を非表示|行目を隠|行を見えなく|行を隠して
// 違い: 行を再表示するなら rows.show。行を消すなら rows.delete
// 引数: rows*=行[]
// 例: 「5行目から10行目を隠して」 → {"shelf":"rows.hide","rows":[5,6,7,8,9,10]}
// 触る: 隠し
// 控え: 今
SHELF['rows.hide'] = function (ctx, op) {
  need_(op, ['rows']);
  var sh = sheetCtx_(ctx, op);
  var list = (Array.isArray(op.rows) ? op.rows : [op.rows]).map(function (x) { return parseInt(x, 10); });
  list.forEach(function (r) { sh.hideRows(r); });
  chg_(ctx, sh, list.join('・') + ' 行目', '行を非表示');
};

// 棚: rows.show
// 題: 隠した行を出す
// 分類: 行と列
// 語: 行を再表示|隠した行|非表示の行|行を出|行が見えない
// 違い: 行を隠すなら rows.hide
// 引数: rows=行[]
// 例: 「隠れている5行目を出して」 → {"shelf":"rows.show","rows":[5]}
// 例: 「非表示の行を全部出して」 → {"shelf":"rows.show"}
// 触る: 隠し
// 控え: 今
SHELF['rows.show'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  if (op.rows) {
    var list = (Array.isArray(op.rows) ? op.rows : [op.rows]).map(function (x) { return parseInt(x, 10); });
    list.forEach(function (r) { sh.unhideRow(sh.getRange(r, 1)); });
    chg_(ctx, sh, list.join('・') + ' 行目', '行を再表示');
  } else {
    sh.unhideRow(sh.getRange(1, 1, sh.getMaxRows(), 1));
    chg_(ctx, sh, '', '全行を再表示');
  }
};

// 棚: cols.hide
// 題: 列を隠す
// 分類: 行と列
// 語: 列を隠|列を非表示|非表示にして|非表示に|列を見えなく|列を隠して
// 違い: 列を再表示するなら cols.show。列を消すなら cols.delete
// 引数: cols*=列[]
// 例: 「C列とD列を隠して」 → {"shelf":"cols.hide","cols":["C","D"]}
// 触る: 隠し
// 控え: 今
SHELF['cols.hide'] = function (ctx, op) {
  need_(op, ['cols']);
  var sh = sheetCtx_(ctx, op);
  var list = Array.isArray(op.cols) ? op.cols : [op.cols];
  list.forEach(function (c) {
    var n = typeof c === 'number' ? c : colNum_(c);
    sh.hideColumns(n);
  });
  chg_(ctx, sh, list.join('・') + ' 列', '列を非表示');
};

// 棚: cols.show
// 題: 隠した列を出す
// 分類: 行と列
// 語: 列を再表示|隠した列|非表示の列|非表示になってる列|列を出
// 違い: 列を隠すなら cols.hide
// 引数: cols=列[]
// 例: 「非表示になっているC列を出して」 → {"shelf":"cols.show","cols":["C"]}
// 例: 「隠れている列を全部再表示して」 → {"shelf":"cols.show"}
// 触る: 隠し
// 控え: 今
SHELF['cols.show'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  if (op.cols) {
    var list = Array.isArray(op.cols) ? op.cols : [op.cols];
    list.forEach(function (c) {
      var n = typeof c === 'number' ? c : colNum_(c);
      sh.unhideColumn(sh.getRange(1, n));
    });
    chg_(ctx, sh, list.join('・') + ' 列', '列を再表示');
  } else {
    sh.unhideColumn(sh.getRange(1, 1, 1, sh.getMaxColumns()));
    chg_(ctx, sh, '', '全列を再表示');
  }
};

// 棚: group.rows
// 題: 行をグループ化する
// 分類: 行と列
// 語: 行をグループ|行をまとめて折|行を折りたた|行を畳|行をグループ化
// 違い: 列のグループ化は group.cols。グループ解除は group.remove
// 引数: rows*=行[], collapse=真偽
// 例: 「5行目から10行目をグループ化して折りたたんで」 → {"shelf":"group.rows","rows":[5,6,7,8,9,10],"collapse":true}
// 触る: グループ 隠し
// 控え: 今
SHELF['group.rows'] = function (ctx, op) {
  need_(op, ['rows']);
  var sh = sheetCtx_(ctx, op);
  var list = (Array.isArray(op.rows) ? op.rows : [op.rows]).map(function (x) { return parseInt(x, 10); }).sort(function (a, b) { return a - b; });
  var start = list[0], count = list[list.length - 1] - start + 1;
  var rg = sh.getRange(start, 1, count, 1);
  rg.shiftRowGroupDepth(1);
  if (op.collapse) rg.collapseGroups();
  chg_(ctx, sh, start + '〜' + (start + count - 1) + ' 行目', '行をグループ化');
};

// 棚: group.cols
// 題: 列をグループ化する
// 分類: 行と列
// 語: 列をグループ|列をまとめて折|列を折りたた|列を畳|列をグループ化
// 違い: 行のグループ化は group.rows。グループ解除は group.remove
// 引数: cols*=列[], collapse=真偽
// 例: 「D列からF列をグループ化して」 → {"shelf":"group.cols","cols":["D","E","F"]}
// 触る: グループ 隠し
// 控え: 今
SHELF['group.cols'] = function (ctx, op) {
  need_(op, ['cols']);
  var sh = sheetCtx_(ctx, op);
  var list = (Array.isArray(op.cols) ? op.cols : [op.cols]).map(function (x) { return typeof x === 'number' ? x : colNum_(x); }).sort(function (a, b) { return a - b; });
  var start = list[0], count = list[list.length - 1] - start + 1;
  var rg = sh.getRange(1, start, 1, count);
  rg.shiftColumnGroupDepth(1);
  if (op.collapse) rg.collapseGroups();
  chg_(ctx, sh, colLetter_(start) + '〜' + colLetter_(start + count - 1) + ' 列', '列をグループ化');
};

// 棚: group.remove
// 題: グループ化を外す
// 分類: 行と列
// 語: グループを解除|グループ化を解除|グループを外|折りたたみを解除
// 違い: グループを作るなら group.rows または group.cols
// 引数: rows=行[], cols=列[]
// 例: 「5行目から10行目のグループ化を解除して」 → {"shelf":"group.remove","rows":[5,6,7,8,9,10]}
// 例: 「シート全体のグループを全部外して」 → {"shelf":"group.remove"}
// 触る: グループ
// 控え: 今
SHELF['group.remove'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  if (op.rows) {
    var list = (Array.isArray(op.rows) ? op.rows : [op.rows]).map(function (x) { return parseInt(x, 10); }).sort(function (a, b) { return a - b; });
    var start = list[0], count = list[list.length - 1] - start + 1;
    sh.getRange(start, 1, count, 1).shiftRowGroupDepth(-1);
    chg_(ctx, sh, start + '〜' + (start + count - 1) + ' 行目', '行グループを解除');
  } else if (op.cols) {
    var list2 = (Array.isArray(op.cols) ? op.cols : [op.cols]).map(function (x) { return typeof x === 'number' ? x : colNum_(x); }).sort(function (a, b) { return a - b; });
    var start2 = list2[0], count2 = list2[list2.length - 1] - start2 + 1;
    sh.getRange(1, start2, 1, count2).shiftColumnGroupDepth(-1);
    chg_(ctx, sh, colLetter_(start2) + '〜' + colLetter_(start2 + count2 - 1) + ' 列', '列グループを解除');
  } else {
    var all = sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns());
    for (var d = 0; d < 8; d++) {
      try { all.shiftRowGroupDepth(-1); } catch (eR) { }
      try { all.shiftColumnGroupDepth(-1); } catch (eC) { }
    }
    chg_(ctx, sh, '', '全グループを解除');
  }
};
