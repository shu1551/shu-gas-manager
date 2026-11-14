// 入力の棚

// 棚: validation.list
// 題: プルダウンを付ける
// 分類: 入力
// 語: プルダウン|選択肢から選|リストから選|選べるように|入力規則
// 引数: range*=範囲, items=配列, from=範囲, strict=真偽=true
// 頼み: items~((?:[^\s、。・:に]+・)+[^\s、。・:]+?)(?:から|の)
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

// 棚: protect.sheet
// 題: シートを保護する
// 分類: 守る
// 語: シートを保護|編集できないように|触れないように|書き換えられないように|いじれない
// 違い: 特定の範囲だけ保護するなら protect.range。保護を外すなら protect.remove
// 引数: name=シート, except=範囲, warn=真偽
// 例: 「このシートを保護して編集できないようにして」 → {"shelf":"protect.sheet"}
// 例: 「シートを保護して、でもB2:B20だけは入力できるようにして」 → {"shelf":"protect.sheet","except":"B2:B20"}
// 触る: 保護
// 控え: 今
SHELF['protect.sheet'] = function (ctx, op) {
  var s = op.name ? sheetOf_(ctx.ss, op.name, '') : sheetCtx_(ctx, op);
  var p = s.protect();
  if (op.warn) p.setWarningOnly(true);
  if (op.except) {
    var expRg = s.getRange(op.except);
    p.setUnprotectedRanges([expRg]);
  }
  note_(ctx, '持ち主（実行するアカウント）には保護が効かない所があります');
  chg_(ctx, s, '', 'シート「' + s.getName() + '」を保護' + (op.warn ? '（警告のみ）' : ''));
};

// 棚: protect.range
// 題: 範囲を保護する
// 分類: 守る
// 語: 範囲を保護|セルを保護|列を保護|行を保護|ここだけ保護|範囲を書き換えられないように|書き換えられないように保護|編集できないように保護
// 違い: シート全体なら protect.sheet。保護を外すなら protect.remove
// 引数: range*=範囲, warn=真偽
// 頼み: range~([A-Z]{1,3}[0-9]+:[A-Z]{1,3}[0-9]+)の範囲
// 例: 「A1からC10の範囲を保護して」 → {"shelf":"protect.range","range":"A1:C10"}
// 触る: 保護
// 控え: 今
SHELF['protect.range'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  var p = rg.protect();
  if (op.warn) p.setWarningOnly(true);
  note_(ctx, '持ち主（実行するアカウント）には保護が効かない所があります');
  chg_(ctx, sh, rg.getA1Notation(), '範囲を保護' + (op.warn ? '（警告のみ）' : ''));
};

// 棚: protect.remove
// 題: 保護を外す
// 分類: 守る
// 語: 保護を解除|保護を外|編集できるように|保護をやめ
// 違い: 保護をかけるなら protect.sheet または protect.range
// 引数: range=範囲
// 例: 「シートの保護を解除して」 → {"shelf":"protect.remove"}
// 例: 「A1:C10の保護を外して」 → {"shelf":"protect.remove","range":"A1:C10"}
// 触る: 保護
// 控え: 今
SHELF['protect.remove'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var protections = sh.getProtections(SpreadsheetApp.ProtectionType.SHEET).concat(sh.getProtections(SpreadsheetApp.ProtectionType.RANGE));
  if (op.range) {
    var targetRg = sh.getRange(op.range);
    var targetA1 = targetRg.getA1Notation();
    var removed = 0;
    protections.forEach(function (p) {
      if (p.getProtectionType() === SpreadsheetApp.ProtectionType.RANGE) {
        if (p.getRange().getA1Notation() === targetA1) { p.remove(); removed++; }
      }
    });
    if (removed) {
      note_(ctx, '持ち主（実行するアカウント）には保護が効かない所があります');
      chg_(ctx, sh, targetA1, '範囲の保護を解除（' + removed + ' 件）');
    } else {
      note_(ctx, '指定範囲「' + targetA1 + '」の保護は見つかりませんでした（変更なし）');
    }
  } else {
    if (!protections.length) { note_(ctx, 'このシートに保護はありません（変更なし）'); return; }
    protections.forEach(function (p) { p.remove(); });
    note_(ctx, '持ち主（実行するアカウント）には保護が効かない所があります');
    chg_(ctx, sh, '', 'シート内の全保護を解除（' + protections.length + ' 件）');
  }
};

// 棚: name.add
// 題: 名前付き範囲を作る
// 分類: 守る
// 語: 名前付き範囲|範囲に名前|名前を付けて|名前を定義|名前で呼べる
// 違い: 名前を消すなら name.delete、一覧は name.list
// 引数: name*=文字, range*=範囲
// 頼み: name~[『「]([^』」]+)[』」]という名前 ; name~[『「]([^』」]+)[』」]と名付 ; name~[『「]([^』」]+)[』」]
// 例: 「A1:F20に売上データという名前を付けて」 → {"shelf":"name.add","name":"売上データ","range":"A1:F20"}
// 触る: 名前
// 控え: 今
SHELF['name.add'] = function (ctx, op) {
  need_(op, ['name', 'range']);
  var ss = ctx.ss, sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  ss.getNamedRanges().forEach(function (nr) { if (nr.getName() === op.name) nr.remove(); });
  ss.setNamedRange(op.name, rg);
  chg_(ctx, sh, rg.getA1Notation(), '名前付き範囲「' + op.name + '」を定義');
};

// 棚: name.delete
// 題: 名前付き範囲を消す
// 分類: 守る
// 語: 名前付き範囲を消|名前付き範囲を削除|範囲の名前を消|定義した名前を消
// 違い: 作成は name.add、一覧は name.list
// 引数: name*=文字
// 例: 「売上データという名前付き範囲を削除して」 → {"shelf":"name.delete","name":"売上データ"}
// 触る: 名前
// 控え: 今
SHELF['name.delete'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var found = null;
  ss.getNamedRanges().forEach(function (nr) { if (nr.getName() === op.name) found = nr; });
  if (!found) { note_(ctx, '名前付き範囲「' + op.name + '」は見つかりませんでした（変更なし）'); return; }
  found.remove();
  chg_(ctx, null, '', '名前付き範囲「' + op.name + '」を削除');
};

// 棚: name.list
// 題: 名前付き範囲を一覧にする
// 分類: 守る
// 語: 名前付き範囲を一覧|名前付き範囲を調べ|名前付き範囲を見|定義した名前
// 違い: 作成は name.add、削除は name.delete
// 引数: なし
// 例: 「定義されている名前付き範囲を教えて」 → {"shelf":"name.list"}
// 触る: なし
// 控え: なし
SHELF['name.list'] = function (ctx, op) {
  var ss = ctx.ss;
  var list = ss.getNamedRanges().map(function (nr) {
    return { name: nr.getName(), sheet: nr.getRange().getSheet().getName(), range: nr.getRange().getA1Notation() };
  });
  if (!list.length) { note_(ctx, '名前付き範囲はありません'); return; }
  var lines = list.map(function (x) { return x.name + ': ' + x.sheet + '!' + x.range; });
  note_(ctx, '名前付き範囲（' + list.length + ' 件）:\n' + lines.join('\n'));
};
