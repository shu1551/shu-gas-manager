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
  if (act === 'insert') {
    var at = op.at || list[0]; need_({ shelf: 'rows', at: at }, ['at']);
    var cnt = op.count || 1;
    if (isCol) sh.insertColumnsBefore(typeof at === 'number' ? at : colNum_(at), cnt); else sh.insertRowsBefore(parseInt(at), cnt);
    chg_(ctx, sh, (isCol ? at + '列の前' : at + '行目の前'), cnt + ' ' + (isCol ? '列' : '行') + '挿入');
  } else if (act === 'delete') {
    if (!list.length) throw new ArgError('棚「rows」に rows（行番号の配列）か cols が要ります');
    var nums = list.map(function (x) { return isCol ? (typeof x === 'number' ? x : colNum_(x)) : parseInt(x); }).sort(function (a, b) { return b - a; });
    var max = isCol ? sh.getMaxColumns() : sh.getMaxRows();
    nums.forEach(function (n) { if (n < 1 || n > max) throw new ArgError((isCol ? '列' : '行') + '番号 ' + n + ' は範囲外です（1〜' + max + '）'); });
    var peek = nums.map(function (n) { var v = isCol ? sh.getRange(1, n, Math.min(sh.getLastRow() || 1, 50), 1).getDisplayValues() : sh.getRange(n, 1, 1, Math.max(1, sh.getLastColumn())).getDisplayValues()[0]; return (isCol ? colLetter_(n) + '列' : n + '行目') + '「' + String(isCol ? v.map(function (x) { return x[0]; }).filter(Boolean).slice(0, 2).join('/') : v.filter(Boolean).slice(0, 3).join('/')).slice(0, 24) + '」'; });
    guardDelete_(ctx, peek.reverse().join('、') + ' を削除します');
    nums.forEach(function (n) { if (isCol) sh.deleteColumn(n); else sh.deleteRow(n); });
    chg_(ctx, sh, nums.slice().reverse().join('・') + (isCol ? ' 列' : ' 行目'), '削除');
  } else if (act === 'move') {
    need_(op, ['from', 'to']);
    // to＝動かした後にその列（行）が来る位置。moveColumns/moveRows は「その位置の手前へ」入れるので、右（下）へ動かすときは動かす幅だけ先へ渡す
    if (isCol) { var f = colNum_(op.from), to = colNum_(op.to); sh.moveColumns(sh.getRange(1, f, 1, 1), to > f ? to + 1 : to); }
    else { var fr = parseInt(op.from), cn = op.count || 1, tr = parseInt(op.to); sh.moveRows(sh.getRange(fr, 1, cn, 1), tr > fr ? tr + cn : tr); }
    chg_(ctx, sh, op.from + ' → ' + op.to, '移動');
  } else throw new ArgError('棚「rows」の action は insert・delete・move です');
};

// 棚: rows.insert
// 題: 行を挿入する
// 分類: 行と列
// 語: 行を挿入|行を追加|行を足|行を差し込|空行を入れ|間に行|行を増や
// 違い: 列なら cols.insert。表の下に足すだけなら write
// 引数: at*=文字, count=数
// 例: 「3行目の前に2行足して」 → {"shelf":"rows.insert","at":3,"count":2}
// 触る: 値 書式
SHELF['rows.insert'] = function (ctx, op) {
  SHELF['rows'](ctx, { shelf: 'rows', action: 'insert', at: op.at, count: op.count, sheet: op.sheet });
};

// 棚: rows.delete
// 題: 行を削除する
// 分類: 行と列
// 語: 行を削除|行を消|行目を消|行を取り除|行を捨て|いらない|不要な行
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
// 語: 列を挿入|列を追加|列を足|列を差し込|空の列|間に列|列を増や
// 違い: 行なら rows.insert
// 引数: at*=列, count=数
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
// 例: 「1行目の見出しを固定して」 → {"shelf":"freeze","rows":1}
// 例: 「見出し行とA列を固定して」 → {"shelf":"freeze","rows":1,"cols":1}
// 触る: 固定
// 控え: 今
SHELF['freeze'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var r = op.rows !== undefined ? parseInt(op.rows) : 1;
  var c = op.cols !== undefined ? parseInt(op.cols) : 0;
  sh.setFrozenRows(r);
  sh.setFrozenColumns(c);
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
  sh.setFrozenRows(0);
  sh.setFrozenColumns(0);
  chg_(ctx, sh, '', '固定を解除');
};
