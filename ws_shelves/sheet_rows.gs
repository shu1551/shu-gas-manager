// 行と列の棚

// 棚: rows
// 題: 行・列の挿入・削除・移動
// 分類: 行と列
// 語: 行を削除|行を消|行を挿入|行を追加|列を削除|列を挿入|行を移動|列を入れ替
// 引数: action=選択(insert/delete/move)=delete, rows=行[], cols=列[], at=文字, count=数, from=文字, to=文字
// どれか: rows cols
// 例: 「3行目から5行目を消して」 → {"shelf":"rows","rows":[3,4,5]}
// 例: 「A列とB列を入れ替えて」 → {"shelf":"rows","action":"move","cols":["A"],"from":"A","to":"B"}
// 危ない: 消す
// 触る: 値 書式
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
    if (isCol) sh.moveColumns(sh.getRange(1, colNum_(op.from), 1, 1), colNum_(op.to)); else sh.moveRows(sh.getRange(parseInt(op.from), 1, op.count || 1, 1), parseInt(op.to));
    chg_(ctx, sh, op.from + ' → ' + op.to, '移動');
  } else throw new ArgError('棚「rows」の action は insert・delete・move です');
};
