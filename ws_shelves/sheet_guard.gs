// 入力の棚

// 棚: validation.list
// 題: プルダウンを付ける
// 分類: 入力
// 語: プルダウン|選択肢から選|リストから選|選べるように|入力規則
// 引数: range*=範囲, items=配列, from=範囲, strict=真偽=true
// どれか: items from
// 例: 「C列に未着手、進行中、完了のプルダウンを付けて」 → {"shelf":"validation.list","range":"C2:C100","items":["未着手","進行中","完了"]}
// 触る: 入力規則
// 控え: 今
SHELF['validation.list'] = function (ctx, op) {
  need_(op, ['range']);
  if (!op.items && !op.from) throw new ArgError('棚「validation.list」に items か from のどちらかが要ります');
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var builder = SpreadsheetApp.newDataValidation();
  if (op.items) {
    var items = Array.isArray(op.items) ? op.items : [op.items];
    builder.requireValueInList(items, true);
  } else if (op.from) {
    var fromRg = rangeOf_(ctx.ss, op.from, sh);
    builder.requireValueInRange(fromRg, true);
  }
  var strict = op.strict === undefined ? true : !!op.strict;
  builder.setAllowInvalid(!strict);

  rg.setDataValidation(builder.build());
  chg_(ctx, sh, rg.getA1Notation(), 'プルダウン入力規則を設定');
};

// 棚: validation.number
// 題: 数だけ入るようにする
// 分類: 入力
// 語: 数字だけ入|数値だけ入|数字しか入|数字以外は入|文字を入れられない
// 引数: range*=範囲, min=数, max=数
// 例: 「D列には0以上の数字だけ入れられるようにして」 → {"shelf":"validation.number","range":"D2:D100","min":0}
// 触る: 入力規則
// 控え: 今
SHELF['validation.number'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var builder = SpreadsheetApp.newDataValidation();
  if (op.min !== undefined && op.max !== undefined) {
    builder.requireNumberBetween(Number(op.min), Number(op.max));
  } else if (op.min !== undefined) {
    builder.requireNumberGreaterThanOrEqualTo(Number(op.min));
  } else if (op.max !== undefined) {
    builder.requireNumberLessThanOrEqualTo(Number(op.max));
  } else {
    builder.requireNumberGreaterThanOrEqualTo(-Infinity);
  }
  builder.setAllowInvalid(false);
  rg.setDataValidation(builder.build());
  chg_(ctx, sh, rg.getA1Notation(), '数値限定の入力規則を設定');
};

// 棚: validation.date
// 題: 日付だけ入るようにする
// 分類: 入力
// 語: 日付だけ入|日付しか入|日付以外は入|カレンダーで選
// 引数: range*=範囲
// 例: 「A列は日付だけ入るようにして」 → {"shelf":"validation.date","range":"A2:A100"}
// 触る: 入力規則
// 控え: 今
SHELF['validation.date'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var builder = SpreadsheetApp.newDataValidation()
    .requireDate()
    .setAllowInvalid(false)
    .build();
  rg.setDataValidation(builder);
  chg_(ctx, sh, rg.getA1Notation(), '日付限定の入力規則を設定');
};

// 棚: checkbox
// 題: チェックボックスを付ける
// 分類: 入力
// 語: チェックボックス|チェック欄|チェックを付けられる|済みの印
// 危ない: 上書き
// 引数: range*=範囲
// 例: 「E列にチェックボックスを付けて」 → {"shelf":"checkbox","range":"E2:E100"}
// 触る: 入力規則 値
// 控え: 今
SHELF['checkbox'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  guardOverwrite_(ctx, rg, op);
  var builder = SpreadsheetApp.newDataValidation()
    .requireCheckbox()
    .build();
  rg.setDataValidation(builder);
  chg_(ctx, sh, rg.getA1Notation(), 'チェックボックスを設定');
};

// 棚: validation.clear
// 題: 入力規則を外す
// 分類: 入力
// 語: 入力規則を外|入力規則を消|入力規則を解除|プルダウンを外|プルダウンを消
// 引数: range*=範囲
// 例: 「C列のプルダウンを外して」 → {"shelf":"validation.clear","range":"C2:C100"}
// 触る: 入力規則
// 控え: 今
SHELF['validation.clear'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  rg.clearDataValidations();
  chg_(ctx, sh, rg.getA1Notation(), '入力規則を解除');
};
