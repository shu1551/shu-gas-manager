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

// 棚: sheet.delete
// 題: シートを消す
// 分類: シート
// 語: シートを削除|シートを消|シートごと消|いらないシート|シートを捨て|タブを消
// 違い: 名前変更は sheet.rename、シート追加は sheet.add
// 引数: name*=シート
// 例: 「古い集計シートを消して」 → {"shelf":"sheet.delete","name":"古い集計"}
// 危ない: 消す
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.delete'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var s = sheetOf_(ss, op.name, '');
  if (ss.getSheets().length <= 1) throw new ArgError('シートが1枚しかないため削除できません');
  guardDelete_(ctx, 'シート「' + op.name + '」を削除します', true);   // シートごと消す手は広い削除
  ss.deleteSheet(s);
  chg_(ctx, null, '', 'シート「' + op.name + '」を削除');
};

// 棚: sheet.copy
// 題: シートを複製する
// 分類: シート
// 語: シートを複製|シートをコピー|シートの写し|同じシートをもう|来月分を作|シートを複製して
// 違い: シートの追加は sheet.add、名前変更は sheet.rename
// 引数: name*=シート, as=文字, before=シート
// 例: 「売上シートを複製して」 → {"shelf":"sheet.copy","name":"売上"}
// 例: 「売上シートを写して名前を来月売上にして」 → {"shelf":"sheet.copy","name":"売上","as":"来月売上"}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.copy'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var s = sheetOf_(ss, op.name, '');
  var c = s.copyTo(ss);
  var targetName = op.as;
  if (targetName) {
    if (ss.getSheetByName(targetName)) throw new ArgError('シート「' + targetName + '」はすでにあります');
    c.setName(targetName);
  }
  if (op.before) {
    var bs = sheetOf_(ss, op.before, '');
    ss.setActiveSheet(c);
    ss.moveActiveSheet(bs.getIndex());
  }
  ctx.createdSheets.push(c.getName());
  ctx.curSheet = c.getName();
  chg_(ctx, c, '', 'シート「' + op.name + '」を複製' + (targetName ? '（名前: ' + targetName + '）' : ''));
};
