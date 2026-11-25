// 入力の棚

// 棚: validation.list
// 題: プルダウンを付ける
// 分類: 入力
// 語: プルダウン|選択肢から選|リストから選|選べるように|入力規則
// 引数: range*=範囲, items=配列, from=範囲, strict=真偽=true
// 頼み: items~(?:に|へ|は)\s*([^\s、。・:に]+(?:[・、,][^\s、。・:に、,]+)+)(?:の|という|から)?(?:プルダウン|リスト|選択肢) ; items~((?:[^\s、。・:に]+・)+[^\s、。・:]+?)(?:から|の)
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
// 語: 数字だけ入|数値だけ入|数字しか入|数字以外は入|文字を入れられない|数字だけ入れられる
// 引数: range*=範囲, min=数, max=数
// 頼み: min~([0-9]+(?:\.[0-9]+)?)以上の(?:数字|数値) ; max~([0-9]+(?:\.[0-9]+)?)以下の(?:数字|数値)
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
    builder.requireFormulaSatisfied('=ISNUMBER(' + a1_(rg.getRow(), rg.getColumn()) + ')');
  }
  builder.setAllowInvalid(false);
  rg.setDataValidation(builder.build());
  chg_(ctx, sh, rg.getA1Notation(), '数値限定の入力規則を設定');
};

// 棚: validation.date
// 題: 日付だけ入るようにする
// 分類: 入力
// 語: 日付だけ入|日付しか入|日付以外は入|カレンダーで選|カレンダーから日付|カレンダー|日付入力制限|日付だけ入力
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
  guardOverwrite_(ctx, rg, '範囲「' + rg.getA1Notation() + '」');
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
// 語: シートを保護|編集できないように|触れないように|書き換えられないように|いじれない|他の人が書き換えられない|保護したい
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
// 語: 範囲を保護|セルを保護|列を保護|行を保護|ここだけ保護|範囲を書き換えられないように|書き換えられないように保護|編集できないように保護|触れないようにロック|ロックしたい|セルを保護して書き換え
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
// 頼み: name~[『「]([^』」]+)[』」]という名前 ; name~[『「]([^』」]+)[』」]と名付 ; name~[A-Za-z0-9:]+に([^\sにを「『]+)という名前 ; name~[『「]([^』」]+)[』」]
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
// 語: 名前付き範囲を消|名前付き範囲を削除|範囲の名前を消|定義した名前を消|名前定義を消|名前を消して|定義した名前「
// 違い: 作成は name.add、一覧は name.list
// 引数: name*=文字
// 頼み: name~[『「]([^』」]+)[』」]という名前 ; name~([^\sにを「『]+)という名前(?:付き範囲)?
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
// 語: 名前付き範囲を一覧|名前付き範囲を調べ|名前付き範囲を見|定義した名前|名前付き範囲を教え|定義されている名前付き範囲|名前付き範囲がどこ|名前付き範囲を確認
// 違い: 作成は name.add、削除は name.delete
// 引数: なし
// 例: 「定義されている名前付き範囲を教えて」 → {"shelf":"name.list"}
// 触る: なし
// 控え: なし
SHELF['name.list'] = function (ctx, op) {
  var ss = ctx.ss;
  var list = ss.getNamedRanges().map(function (nr) {
    var rg = nr.getRange();
    return { name: nr.getName(), sheet: rg.getSheet().getName(), range: rg.getA1Notation() };
  });
  if (!list.length) { note_(ctx, '名前付き範囲はありません'); return; }
  var lines = list.map(function (x) { return x.name + ': ' + x.sheet + '!' + x.range; });
  note_(ctx, '名前付き範囲（' + list.length + ' 件）:\n' + lines.join('\n'));
};

// 棚: backup
// 題: バックアップのオン・オフを切り替える
// 分類: 守る
// 語: バックアップ|控え|自動バックアップ|ロールバック|元に戻せる
// 引数: on*=真偽
// 頼み: on=false<取らない|取らなくて|取らず|不要|オフ|OFF|やめて|止めて|なし|無し|しない|外して|切る|切って ; on=true<取って|取る|オン|ON|有効|残して|戻せる|入れて
// 例: 「バックアップを取って」 → {"shelf":"backup","on":true}
// 例: 「バックアップ取らなくていい」 → {"shelf":"backup","on":false}
// 触る: なし
// 控え: なし
SHELF['backup'] = function (ctx, op) {
  chg_(ctx, null, '', 'バックアップ設定: ' + (op.on ? 'ON' : 'OFF'));
};

// 棚: folder
// 題: フォルダの作成・移動・保存先を設定する
// 対象: 両方
// 分類: 守る
// 語: フォルダに移動|フォルダへ移動|別フォルダ|保存先フォルダ|フォルダに入れる|フォルダに作|フォルダを作|フォルダを作成
// 引数: to*=文字, mode=選択(move/default/create)=move, create=真偽=false
// 頼み: create=true<フォルダを作|フォルダを作成|新設|なければ作 ; mode=move<移動|入れ ; mode=default<これから|今後は|既定|デフォルト|いつも|保存先に ; mode=create<フォルダを作|フォルダを作成|新設 ; to~[「『"“]([^」』"”]+)[」』"”] ; to~([^\s、。・「」]+?)(?:という)?フォルダ
// 例: 「「営業部」フォルダに移動して」 → {"shelf":"folder","to":"営業部"}
// 例: 「これからは「月次報告」フォルダに作って」 → {"shelf":"folder","to":"月次報告","mode":"default"}
// 触る: なし
// 控え: なし
SHELF['folder'] = function (ctx, op) {
  need_(op, ['to']);
  var mode = String(op.mode || 'move').toLowerCase();
  var create = !!op.create;
  if (mode === 'create') {
    try {
      var ex = resolveFolder_(op.to, false);
      chg_(ctx, null, '', 'フォルダ「' + ex.name + '」はすでに存在します（ID: ' + ex.id + '）');
      return;
    } catch (e) {
      if (!e || String(e.message || e).indexOf('見つかりません') < 0) throw e;
      var cr = resolveFolder_(op.to, true);
      chg_(ctx, null, '', 'フォルダ「' + cr.name + '」を作成しました（ID: ' + cr.id + '）');
      return;
    }
  }
  if (mode === 'default') {
    var fDef = resolveFolder_(op.to, create);
    if (fDef.isRoot) {
      ctx.defaultFolder = { id: 'root', name: 'マイドライブ' };
      chg_(ctx, null, '', 'これからの新規作成先を「マイドライブ直下（既定解除）」に設定しました');
    } else {
      ctx.defaultFolder = { id: fDef.id, name: fDef.name };
      chg_(ctx, null, '', 'これからの新規作成先を「' + fDef.name + '」フォルダ（ID: ' + fDef.id + '）に設定しました');
    }
    return;
  }
  if (!ctx.file) throw new ArgError('移動対象のファイルが開かれていません（target を指定してください）');
  var fDest = resolveFolder_(op.to, create);
  DriveApp.getFileById(ctx.file.getId()).moveTo(fDest.folder);
  chg_(ctx, null, '', 'フォルダ「' + fDest.name + '」へ移動しました' + (fDest.created ? '（フォルダ新設）' : ''));
};

// 棚: drive.list
// 題: ドライブ内のファイル・フォルダ一覧を見る
// 対象: 両方
// 分類: 守る
// 語: ドライブ一覧|ファイル一覧|フォルダの中身|ドライブを検索|フォルダ一覧|ドライブを探す
// 引数: folder=文字=マイドライブ, query=文字, kind=選択(all/folder/file/sheet/doc)=all, limit=数=30
// 頼み: kind=folder<フォルダだけ|フォルダ一覧 ; kind=sheet<スプレッドシート|シートだけ ; kind=doc<文書|ドキュメント ; limit~(\d+)\s*件 ; folder~[「『"“]([^」』"”]+)[」』"”](?:の中身|フォルダ|内|配下|にある)?
// 例: 「「TEST」フォルダの中身を一覧で見せて」 → {"shelf":"drive.list","folder":"TEST"}
// 例: 「「見積」を含むファイルを探して」 → {"shelf":"drive.list","query":"見積"}
// 触る: なし
// 控え: なし
SHELF['drive.list'] = function (ctx, op) {
  var kind = String(op.kind || 'all').toLowerCase();
  var lim = Math.max(1, Math.min(100, Number(op.limit) || 30));
  var q = String(op.query || '').trim();
  var items = [];
  var wantFolder = kind === 'all' || kind === 'folder';
  var wantFile = kind !== 'folder';
  var mimeCond = '';
  if (kind === 'sheet') mimeCond = " and mimeType = 'application/vnd.google-apps.spreadsheet'";
  else if (kind === 'doc') mimeCond = " and mimeType = 'application/vnd.google-apps.document'";
  if (q) {
    var esc = q.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    var fSpec = String(op.folder || '').trim();
    var parentCond = '';
    if (fSpec && fSpec !== 'マイドライブ' && fSpec !== 'root' && fSpec !== 'My Drive') {
      parentCond = " and '" + resolveFolder_(fSpec, false).id + "' in parents";
    }
    if (wantFolder) {
      var df = DriveApp.searchFolders("title contains '" + esc + "' and trashed = false" + parentCond);
      while (df.hasNext() && items.length < lim) {
        var d = df.next();
        items.push('[フォルダ] ' + d.getName() + ' (ID: ' + d.getId() + ')');
      }
    }
    if (wantFile && items.length < lim) {
      var ff = DriveApp.searchFiles("title contains '" + esc + "' and trashed = false" + mimeCond + parentCond);
      while (ff.hasNext() && items.length < lim) {
        var f = ff.next();
        items.push('[' + mimeLabel_(f.getMimeType()) + '] ' + f.getName() + ' (ID: ' + f.getId() + ')');
      }
    }
  } else {
    var base = resolveFolder_(op.folder || 'マイドライブ', false).folder;
    if (wantFolder) {
      var df2 = base.getFolders();
      while (df2.hasNext() && items.length < lim) {
        var d2 = df2.next();
        if (!d2.isTrashed()) items.push('[フォルダ] ' + d2.getName() + ' (ID: ' + d2.getId() + ')');
      }
    }
    if (wantFile && items.length < lim) {
      var ff2 = base.getFiles();
      while (ff2.hasNext() && items.length < lim) {
        var f2 = ff2.next();
        if (f2.isTrashed()) continue;
        var m2 = f2.getMimeType();
        if (kind === 'sheet' && m2 !== 'application/vnd.google-apps.spreadsheet') continue;
        if (kind === 'doc' && m2 !== 'application/vnd.google-apps.document') continue;
        items.push('[' + mimeLabel_(m2) + '] ' + f2.getName() + ' (ID: ' + f2.getId() + ')');
      }
    }
  }
  note_(ctx, items.length ? ('ドライブ一覧（' + items.length + ' 件）:\n' + items.join('\n')) : '該当する項目はありませんでした');
};

// 棚: drive.rename
// 題: ファイルやフォルダの名前を変える
// 対象: 両方
// 分類: 守る
// 語: ファイル名を変更|ファイル名を変える|フォルダ名を変更|フォルダ名を変える|ドライブ上の名前|リネーム|ファイルの名前を変|ファイルの名前を
// 引数: name*=文字, item=文字
// 頼み: item~[「『]([^」』]+)[」』]の名前 ; name~名前を[「『]([^」』]+)[」』]
// 例: 「ファイル「資料_old.pdf」の名前を「資料_2026.pdf」に変えて」 → {"shelf":"drive.rename","item":"資料_old.pdf","name":"資料_2026.pdf"}
// 例: 「今開いているファイルの名前を「売上確定」に変更して」 → {"shelf":"drive.rename","name":"売上確定"}
// 触る: なし
// 控え: なし
SHELF['drive.rename'] = function (ctx, op) {
  need_(op, ['name']);
  var target = op.item
    ? resolveDriveItem_(op.item)
    : (ctx.file ? wrapDriveObj_(DriveApp.getFileById(ctx.file.getId()), false) : null);
  if (!target) throw new ArgError('名前を変える対象（item または target）を指定してください');
  var oldName = target.obj.getName();
  target.obj.setName(String(op.name));
  chg_(ctx, null, '', (target.isFolder ? 'フォルダ' : mimeLabel_(target.mime)) + '名を変更: 「' + oldName + '」→「' + op.name + '」');
};

// 棚: drive.move
// 題: ファイルやフォルダを別のフォルダへ移動する
// 対象: 両方
// 分類: 守る
// 語: ドライブ移動|フォルダごと移動|PDFを移動|画像を移動|項目を移動|ファイルを整理|フォルダに移動|フォルダへ移動|ファイル移動
// 引数: to*=文字, item=文字, create=真偽=false
// 頼み: item~[「『]([^」』]+)[」』]を ; to~を[「『]([^」』]+)[」』]フォルダ
// 例: 「ファイル「請求書.pdf」を「経理/2026」フォルダに移動して」 → {"shelf":"drive.move","item":"請求書.pdf","to":"経理/2026"}
// 例: 「「作業用」フォルダを「アーカイブ」フォルダに入れて」 → {"shelf":"drive.move","item":"作業用","to":"アーカイブ"}
// 触る: なし
// 控え: なし
SHELF['drive.move'] = function (ctx, op) {
  need_(op, ['to']);
  var target = op.item
    ? resolveDriveItem_(op.item)
    : (ctx.file ? wrapDriveObj_(DriveApp.getFileById(ctx.file.getId()), false) : null);
  if (!target) throw new ArgError('移動する対象（item または target）を指定してください');
  var dest = resolveFolder_(op.to, !!op.create);
  if (target.isFolder && isAncestorFolder_(target.id, dest.folder)) {
    throw new ArgError('フォルダ「' + target.name + '」を自分自身または配下のフォルダへは移動できません');
  }
  target.obj.moveTo(dest.folder);
  chg_(ctx, null, '', (target.isFolder ? 'フォルダ' : mimeLabel_(target.mime)) + '「' + target.name + '」を「' + dest.name + '」へ移動しました' + (dest.created ? '（フォルダ新設）' : ''));
};

// 棚: drive.trash
// 題: 不要なファイルやフォルダをゴミ箱に入れる
// 対象: 両方
// 分類: 守る
// 語: ゴミ箱|ごみ箱|ゴミ箱に入れ|ごみ箱に入れ|ファイルを削除|フォルダを削除|不要ファイル削除|ファイルを消して|フォルダを消して
// 引数: item=文字
// 頼み: item~[「『"“]([^」』"”]+)[」』"”]
// 例: 「「下書き.pdf」をゴミ箱に入れて」 → {"shelf":"drive.trash","item":"下書き.pdf"}
// 例: 「「一時作業」フォルダを削除して」 → {"shelf":"drive.trash","item":"一時作業"}
// 危ない: 消す
// 触る: なし
// 控え: なし
SHELF['drive.trash'] = function (ctx, op) {
  var target = op.item
    ? resolveDriveItem_(op.item)
    : (ctx.file ? wrapDriveObj_(DriveApp.getFileById(ctx.file.getId()), false) : null);
  if (!target) throw new ArgError('ゴミ箱に入れる対象（item または target）を指定してください');
  var subN = target.isFolder ? countFolderChildren_(target.obj) : undefined;
  var desc = (target.isFolder ? 'フォルダ' : mimeLabel_(target.mime)) + '「' + target.name + '」をゴミ箱に入れます'
    + (target.isFolder ? '（中の項目数: ' + subN + '）' : '');
  guardDelete_(ctx, desc, target.isFolder, subN);
  target.obj.setTrashed(true);
  chg_(ctx, null, '', (target.isFolder ? 'フォルダ' : mimeLabel_(target.mime)) + '「' + target.name + '」をゴミ箱に入れました');
};

// 棚: print.setup
// 題: シートの印刷設定を保存する
// 分類: 守る
// 語: 印刷設定|A4横|A4縦|1ページに収め|余白を狭く|グリッド線|印刷の向き|用紙サイズ|ページ設定
// 違い: 実際にPDFファイルを作るなら export.pdf
// 引数: paper=選択(a4/a3/b4/b5/letter)=a4, landscape=真偽=true, fit_width=真偽=true, gridlines=真偽=false, margins=選択(narrow/normal/wide)=narrow
// 頼み: paper=a3<A3 ; paper=b4<B4 ; paper=b5<B5 ; paper=a4<A4 ; landscape=false<縦向き|A4縦|縦に印刷 ; landscape=true<横向き|A4横|横に印刷 ; fit_width=true<1ページに収|幅を1ページ|横1ページ ; gridlines=true<枠線あり|グリッド線あり ; gridlines=false<枠線なし|グリッド線なし
// 例: 「A4横・幅1ページに収める印刷設定にして」 → {"shelf":"print.setup","paper":"a4","landscape":true,"fit_width":true}
// 触る: 書式
// 控え: 今
SHELF['print.setup'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var cfg = {
    paper: String(op.paper || 'A4').toUpperCase(),
    landscape: op.landscape !== false,
    fit_width: op.fit_width !== false,
    gridlines: op.gridlines === true,
    margins: String(op.margins || 'narrow').toLowerCase()
  };
  var key = 'ws_print_cfg_' + sh.getSheetId();
  PropertiesService.getDocumentProperties().setProperty(key, JSON.stringify(cfg));
  chg_(ctx, sh, '', '印刷設定を保存（' + cfg.paper + '・' + (cfg.landscape ? '横' : '縦') + '・幅1ページ:' + (cfg.fit_width ? 'ON' : 'OFF') + '・枠線:' + (cfg.gridlines ? 'ON' : 'OFF') + '・余白:' + cfg.margins + '）');
};

// 棚: export.pdf
// 題: シートをPDFにして保存する
// 分類: 守る
// 語: PDF出力|PDFに書き出|PDFにして|PDF保存|PDFを作成|PDF化|印刷用PDF|シートをPDF
// 違い: 印刷設定だけ保存するなら print.setup。GoogleドキュメントのPDF化は doc.export.pdf
// 引数: name=文字, folder=文字, paper=選択(a4/a3/b4/b5/letter), landscape=真偽, fit_width=真偽, gridlines=真偽, all_sheets=真偽=false
// 頼み: landscape=false<縦向き|A4縦 ; landscape=true<横向き|A4横 ; paper=a3<A3 ; paper=a4<A4 ; folder~[「『"“]([^」』"”]+)[」』"”]フォルダ ; all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体|全ページ
// 例: 「このシートをA4横のPDFにして保存して」 → {"shelf":"export.pdf","paper":"a4","landscape":true}
// 例: 「売上シートを「請求書_5月.pdf」としてPDF出力して」 → {"shelf":"export.pdf","sheet":"売上","name":"請求書_5月.pdf"}
// 触る: なし
// 控え: なし
SHELF['export.pdf'] = function (ctx, op) {
  var ss = ctx.ss;
  var allSheets = !!op.all_sheets;
  var sh = op.sheet ? sheetOf_(ss, op.sheet, '') : sheetCtx_(ctx, op);
  var saved = {};
  try {
    var raw = PropertiesService.getDocumentProperties().getProperty('ws_print_cfg_' + sh.getSheetId());
    if (raw) saved = JSON.parse(raw);
  } catch (e) {}
  var paper = String(op.paper || saved.paper || 'A4').toUpperCase();
  var landscape = op.landscape !== undefined ? !!op.landscape : (saved.landscape !== undefined ? !!saved.landscape : true);
  var fitWidth = op.fit_width !== undefined ? !!op.fit_width : (saved.fit_width !== undefined ? !!saved.fit_width : true);
  var gridlines = op.gridlines !== undefined ? !!op.gridlines : (saved.gridlines === true);
  var margins = String(saved.margins || 'narrow').toLowerCase();
  var mg = margins === 'wide' ? '0.75' : (margins === 'normal' ? '0.5' : '0.25');

  SpreadsheetApp.flush();
  var url = 'https://docs.google.com/spreadsheets/d/' + ss.getId() + '/export?format=pdf'
    + (allSheets ? '' : ('&gid=' + sh.getSheetId()))
    + '&size=' + encodeURIComponent(paper)
    + '&portrait=' + (landscape ? 'false' : 'true')
    + '&fitw=' + (fitWidth ? 'true' : 'false')
    + '&gridlines=' + (gridlines ? 'true' : 'false')
    + '&sheetnames=false&printtitle=false&pagenumbers=false&fzr=true'
    + '&top_margin=' + mg + '&bottom_margin=' + mg + '&left_margin=' + mg + '&right_margin=' + mg;

  var resp = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) {
    throw new ArgError('PDF出力に失敗しました（HTTP ' + resp.getResponseCode() + '）');
  }
  var defPdfName = allSheets ? (ss.getName() + '.pdf') : (ss.getName() + '_' + sh.getName() + '.pdf');
  var fileName = String(op.name || defPdfName).trim();
  if (!/\.pdf$/i.test(fileName)) fileName += '.pdf';
  var blob = resp.getBlob().setName(fileName);
  var destFolder = op.folder ? resolveFolder_(op.folder, true).folder : null;
  var pdfFile = destFolder ? destFolder.createFile(blob) : DriveApp.createFile(blob);
  note_(ctx, 'PDF保存完了: ' + pdfFile.getName() + '\nID: ' + pdfFile.getId() + '\nURL: ' + pdfFile.getUrl());
  chg_(ctx, allSheets ? null : sh, '', (allSheets ? '全シート ' : '') + 'PDFを作成: 「' + pdfFile.getName() + '」（' + paper + '・' + (landscape ? '横' : '縦') + '）');
};

// 棚: export.csv
// 題: シートをCSVでDriveに保存する
// 分類: 守る
// 語: CSV出力|CSVに書き出|CSVにして|CSV保存|CSVを作成|CSV化|CSVファイル|シートをCSV
// 違い: PDF保存は export.pdf
// 引数: name=文字, folder=文字, bom=真偽=true
// 頼み: bom=false<BOMなし|BOM無し ; folder~[「『"“]([^」』"”]+)[」』"”]フォルダ
// 例: 「このシートをCSVにしてDriveに保存して」 → {"shelf":"export.csv"}
// 触る: なし
// 控え: なし
SHELF['export.csv'] = function (ctx, op) {
  var ss = ctx.ss, sh = sheetCtx_(ctx, op);
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  var csvLines = [];
  if (lr > 0 && lc > 0) {
    var disp = sh.getRange(1, 1, lr, lc).getDisplayValues();
    for (var r = 0; r < disp.length; r++) {
      var cells = [];
      for (var c = 0; c < disp[r].length; c++) {
        var s = String(disp[r][c] === undefined || disp[r][c] === null ? '' : disp[r][c]);
        if (/[",\r\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
        cells.push(s);
      }
      csvLines.push(cells.join(','));
    }
  }
  var body = csvLines.join('\r\n');
  var withBom = op.bom !== false;
  var csvContent = (withBom ? '\uFEFF' : '') + body;
  var fileName = String(op.name || (ss.getName() + '_' + sh.getName() + '.csv')).trim();
  if (!/\.csv$/i.test(fileName)) fileName += '.csv';
  var blob = Utilities.newBlob(csvContent, 'text/csv; charset=utf-8', fileName);
  var destFolder = op.folder ? resolveFolder_(op.folder, true).folder : null;
  var csvFile = destFolder ? destFolder.createFile(blob) : DriveApp.createFile(blob);
  note_(ctx, 'CSV保存完了: ' + csvFile.getName() + '\nID: ' + csvFile.getId() + '\nURL: ' + csvFile.getUrl());
  chg_(ctx, sh, '', 'CSVを作成: 「' + csvFile.getName() + '」（' + lr + '行・' + (withBom ? 'BOM付きUTF-8' : 'UTF-8') + '）');
};

// 棚: drive.share
// 題: ファイルやフォルダを共有・リンク取得する
// 対象: 両方
// 分類: 守る
// 語: 共有リンク|閲覧リンク|共有設定|リンクを知っている全員|権限を付与|編集権限を|閲覧権限を|共有して
// 引数: item=文字, email=文字, role=選択(viewer/editor/commenter)=viewer, anyone=真偽=false
// 頼み: anyone=true<全員|リンクを知っている|閲覧リンク|共有リンク ; role=editor<編集権限|編集できる ; role=commenter<コメント権限|コメントできる ; role=viewer<閲覧権限|閲覧専用|見るだけ ; email~([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})
// 例: 「閲覧専用の共有リンクを作って」 → {"shelf":"drive.share","anyone":true,"role":"viewer"}
// 例: 「yamada@example.com に編集権限を付けて共有して」 → {"shelf":"drive.share","email":"yamada@example.com","role":"editor"}
// 触る: なし
// 控え: なし
SHELF['drive.share'] = function (ctx, op) {
  var target = op.item
    ? resolveDriveItem_(op.item)
    : (ctx.file ? wrapDriveObj_(DriveApp.getFileById(ctx.file.getId()), false) : null);
  if (!target) throw new ArgError('共有する対象（item または target）を指定してください');
  var role = String(op.role || 'viewer').toLowerCase();
  var actions = [];
  if (op.anyone) {
    var perm = role === 'editor' ? DriveApp.Permission.EDIT : (role === 'commenter' ? DriveApp.Permission.COMMENT : DriveApp.Permission.VIEW);
    target.obj.setSharing(DriveApp.Access.ANYONE_WITH_LINK, perm);
    actions.push('リンクを知っている全員に ' + role + ' 権限を付与');
  }
  if (op.email) {
    var em = String(op.email).trim();
    if (role === 'editor') target.obj.addEditor(em);
    else if (role === 'commenter' && typeof target.obj.addCommenter === 'function') target.obj.addCommenter(em);
    else target.obj.addViewer(em);
    actions.push(em + ' に ' + role + ' 権限を付与');
  }
  if (!actions.length) {
    note_(ctx, '共有URL: ' + target.obj.getUrl());
    return;
  }
  note_(ctx, '共有URL: ' + target.obj.getUrl());
  chg_(ctx, null, '', '「' + target.name + '」を共有（' + actions.join(' / ') + '）');
};

// 棚: protect.list
// 題: 保護中のシートと範囲を一覧にする
// 分類: 守る
// 語: 保護を一覧|保護一覧|保護されている|保護中の|保護を確認|保護を調べ|保護を教え|どこが保護
// 違い: 保護をかけるなら protect.sheet / protect.range、外すなら protect.remove
// 引数: なし
// 例: 「保護中のシートと範囲を一覧にして教えて」 → {"shelf":"protect.list"}
// 触る: なし
// 控え: なし
SHELF['protect.list'] = function (ctx, op) {
  var ss = ctx.ss;
  var sp = ss.getProtections(SpreadsheetApp.ProtectionType.SHEET) || [];
  var rp = ss.getProtections(SpreadsheetApp.ProtectionType.RANGE) || [];
  var lines = [];
  sp.forEach(function (p) {
    var rg = p.getRange();
    var shNm = rg ? rg.getSheet().getName() : '?';
    var warn = p.isWarningOnly() ? '（警告のみ）' : '';
    var desc = p.getDescription() ? (' [' + p.getDescription() + ']') : '';
    lines.push('[シート] ' + shNm + warn + desc);
  });
  rp.forEach(function (p) {
    var rg = p.getRange();
    var loc = rg ? (rg.getSheet().getName() + '!' + rg.getA1Notation()) : '?';
    var warn = p.isWarningOnly() ? '（警告のみ）' : '';
    var desc = p.getDescription() ? (' [' + p.getDescription() + ']') : '';
    lines.push('[範囲] ' + loc + warn + desc);
  });
  if (!lines.length) {
    note_(ctx, 'このブックに保護は設定されていません');
    return;
  }
  note_(ctx, '保護設定の一覧（' + lines.length + ' 件）:\n' + lines.join('\n'));
};

// 棚: checkbox.toggle
// 題: 範囲のチェックボックスを全ON・全OFF・反転する
// 分類: 入力
// 語: チェックを全|全部オン|全部オフ|全チェック|チェックを反転|チェックを外|チェックを一括|チェック全解除|一括オン|一括オフ|一括反転
// 違い: チェックボックス自体を新しく作るなら checkbox
// 引数: range*=範囲, mode=選択(on/off/invert)=off
// 頼み: mode=on<全ON|全部ON|すべてON|全てON|全部チェック|オンに ; mode=invert<反転 ; mode=off<全OFF|全部OFF|すべてOFF|全てOFF|全部外|全解除|オフに
// 例: 「E2:E20のチェックボックスを全部OFFにして」 → {"shelf":"checkbox.toggle","range":"E2:E20","mode":"off"}
// 触る: 値
// 控え: 今
SHELF['checkbox.toggle'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var mode = String(op.mode || 'off').toLowerCase();
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      if (forms[r][c]) { vals[r][c] = forms[r][c]; continue; }
      var v = vals[r][c];
      if (typeof v !== 'boolean') continue;
      var nv = mode === 'on' ? true : (mode === 'invert' ? !v : false);
      if (nv !== v) { vals[r][c] = nv; changed++; }
    }
  }
  if (!changed) {
    note_(ctx, '切り替え対象のチェックボックスは変わっていません（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), 'チェックボックスを ' + mode.toUpperCase() + '（' + changed + ' 件）');
};

// 棚: export.xlsx
// 題: ブックをExcel形式でDriveに保存
// 分類: 守る
// 語: Excel出力|エクセル出力|xlsx出力|Excelに書き出|エクセルに書き出|Excel保存|エクセル形式|xlsx保存
// 違い: PDF保存は export.pdf、CSV保存は export.csv
// 引数: name=文字, folder=文字
// 頼み: folder~[「『"“]([^」』"”]+)[」』"”]フォルダ
// 例: 「このブックをExcel形式でDriveに保存して」 → {"shelf":"export.xlsx"}
// 触る: なし
// 控え: なし
SHELF['export.xlsx'] = function (ctx, op) {
  var ss = ctx.ss;
  SpreadsheetApp.flush();
  var url = 'https://docs.google.com/spreadsheets/d/' + ss.getId() + '/export?format=xlsx';
  var resp = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) {
    throw new ArgError('Excel出力に失敗しました（HTTP ' + resp.getResponseCode() + '）');
  }
  var fileName = String(op.name || (ss.getName() + '.xlsx')).trim();
  if (!/\.xlsx$/i.test(fileName)) fileName += '.xlsx';
  var blob = resp.getBlob().setName(fileName);
  var destFolder = op.folder ? resolveFolder_(op.folder, true).folder : null;
  var xlsxFile = destFolder ? destFolder.createFile(blob) : DriveApp.createFile(blob);
  note_(ctx, 'Excel保存完了: ' + xlsxFile.getName() + '\nID: ' + xlsxFile.getId() + '\nURL: ' + xlsxFile.getUrl());
  chg_(ctx, null, '', 'Excelを作成: 「' + xlsxFile.getName() + '」');
};

// 棚: protect.formulas
// 題: シート内の数式セルを自動検出して保護する
// 分類: 守る
// 語: 数式を保護|数式だけロック|数式セルを保護|計算式を保護|計算式をロック|入力セル以外を保護|数式が消えないように
// 違い: シート全体や固定範囲を保護するなら protect.sheet / protect.range
// 引数: warning_only=真偽=true
// 頼み: warning_only=false<完全ロック|編集不可|変更禁止
// 例: 「シート内の数式セルを全部保護して」 → {"shelf":"protect.formulas"}
// 触る: 保護
// 控え: 今
SHELF['protect.formulas'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  if (lr < 1 || lc < 1) { note_(ctx, '数式セルはありません'); return; }
  var forms = sh.getRange(1, 1, lr, lc).getFormulas();
  var blocks = [], cells = 0;
  for (var c = 0; c < lc; c++) {
    var r = 0;
    while (r < lr) {
      if (!forms[r][c]) { r++; continue; }
      var rStart = r;
      while (r + 1 < lr && forms[r + 1][c]) r++;
      var nr = r - rStart + 1;
      blocks.push({ r1: rStart + 1, c1: c + 1, nr: nr });
      cells += nr;
      r++;
    }
  }
  if (!blocks.length) {
    note_(ctx, '保護対象の数式セルは見つかりませんでした');
    return;
  }
  var warnOnly = op.warning_only !== false;
  var existing = {};
  try {
    sh.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (pr) {
      var r0 = pr.getRange();
      if (r0) existing[r0.getA1Notation()] = 1;
    });
  } catch (eEx) {}
  var MAX_BLOCKS = 40;
  var targets = blocks.slice(0, MAX_BLOCKS);
  var applied = 0;
  for (var i = 0; i < targets.length; i++) {
    var b = targets[i];
    var rg = sh.getRange(b.r1, b.c1, b.nr, 1);
    if (existing[rg.getA1Notation()]) continue;
    var p = rg.protect();
    if (typeof p.setDescription === 'function') p.setDescription('数式保護');
    if (typeof p.setWarningOnly === 'function') p.setWarningOnly(warnOnly);
    applied++;
  }
  if (blocks.length > MAX_BLOCKS) {
    note_(ctx, '数式ブロックが多いため先頭 ' + MAX_BLOCKS + ' ブロック（全 ' + blocks.length + ' 中）まで保護しました');
  }
  chg_(ctx, sh, '', '数式セル ' + cells + ' 個（' + applied + ' 範囲）を' + (warnOnly ? '警告付き保護' : '完全保護'));
};
