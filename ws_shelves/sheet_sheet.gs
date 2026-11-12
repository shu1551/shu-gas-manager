// シートの棚

// 棚: sheet.add
// 題: シートを追加する
// 分類: シート
// 語: シートを追加|シートを作|新しいシート|シートを足|空のシート|シートが欲しい|別のシート
// 違い: 改名は sheet.rename、並び順は sheet.move（古い rename・move の引数も今までどおり撃てる）
// 引数: name=シート, before=シート, rename=対応, move=対応
// どれか: name rename move
// 例: 「集計というシートを足して」 → {"shelf":"sheet.add","name":"集計"}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.add'] = function (ctx, op) {
  var ss = ctx.ss;
  if (op.name && !op.rename && !op.move) {
    if (ss.getSheetByName(op.name)) { note_(ctx, 'シート「' + op.name + '」はすでにあります（変更なし）'); ctx.curSheet = op.name; return; }
    var s = ss.insertSheet(op.name); ctx.createdSheets.push(op.name);
    if (op.before) { var bs = sheetOf_(ss, op.before, ''); ss.setActiveSheet(s); ss.moveActiveSheet(bs.getIndex()); }
    ctx.curSheet = op.name; chg_(ctx, s, '', 'シートを追加');
  }
  if (op.rename) {
    need_(op.rename, ['from', 'to']);
    var f = sheetOf_(ss, op.rename.from, '');
    if (ss.getSheetByName(op.rename.to)) throw new ArgError('シート「' + op.rename.to + '」はすでにあります');
    f.setName(op.rename.to); ctx.curSheet = op.rename.to; chg_(ctx, f, '', '名前を「' + op.rename.from + '」から変更');
  }
  if (op.move) {
    need_(op.move, ['name', 'index']);
    var m = sheetOf_(ss, op.move.name, ''); ss.setActiveSheet(m); ss.moveActiveSheet(parseInt(op.move.index)); chg_(ctx, m, '', '並び順を ' + op.move.index + ' 番目へ');
  }
  if (!op.name && !op.rename && !op.move) throw new ArgError('棚「sheet.add」に name・rename・move のどれかが要ります');
};

// 棚: sheet.rename
// 題: シートの名前を変える
// 分類: シート
// 語: シートを改名|シート名を変|名前を変更|シートの名前|名前を付け替|リネーム|別の名前に
// 違い: 追加は sheet.add、並び順は sheet.move
// 引数: name*=シート, to*=文字
// 例: 「シート1の名前を売上に変えて」 → {"shelf":"sheet.rename","name":"シート1","to":"売上"}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.rename'] = function (ctx, op) {
  SHELF['sheet.add'](ctx, { shelf: 'sheet.add', rename: { from: op.name, to: op.to } });
};

// 棚: sheet.move
// 題: シートの並び順を変える
// 分類: シート
// 語: シートを移動|シートの順番|シートの並び|シートを並べ替|順番を入れ替|先頭に動か|左へ動か
// 違い: 追加は sheet.add、改名は sheet.rename
// 引数: name*=シート, index*=数
// 例: 「集計を先頭に動かして」 → {"shelf":"sheet.move","name":"集計","index":1}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.move'] = function (ctx, op) {
  SHELF['sheet.add'](ctx, { shelf: 'sheet.add', move: { name: op.name, index: op.index } });
};
