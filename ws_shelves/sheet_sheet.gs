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
    var s = ss.insertSheet(op.name, ss.getSheets().length); ctx.createdSheets.push(op.name);
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
// 語: シートを改名|シート名を変|名前を変更|シートの名前|名前を付け替|リネーム|別の名前に|シート名を
// 違い: 追加は sheet.add、並び順は sheet.move
// 引数: name*=シート, to*=文字
// 頼み: to~[『「]([^』」]+)[』」]に ; to~(?:シート名|名前)を[『「]?([^』」\s]+?)[』」]?に(?:変え|変更|直|し)
// 例: 「シート1の名前を売上に変えて」 → {"shelf":"sheet.rename","name":"シート1","to":"売上"}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.rename'] = function (ctx, op) {
  SHELF['sheet.add'](ctx, { shelf: 'sheet.add', rename: { from: op.name, to: op.to } });
};

// 棚: sheet.move
// 題: シートの並び順を変える
// 分類: シート
// 語: シートを移動|シートの順番|シートの並び|順番を入れ替|先頭に動か|左へ動か|タブを先頭|を先頭にして|一番左に|末尾にして
// 違い: 追加は sheet.add、改名は sheet.rename
// 引数: name*=シート, index*=数
// 頼み: index=1<先頭|一番左|最初 ; index=999<末尾|一番右|最後 ; index~([0-9]+)番目
// 例: 「集計を先頭に動かして」 → {"shelf":"sheet.move","name":"集計","index":1}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.move'] = function (ctx, op) {
  SHELF['sheet.add'](ctx, { shelf: 'sheet.add', move: { name: op.name, index: op.index } });
};

// 棚: sheet.delete
// 題: シートを消す
// 分類: シート
// 語: シートを削除|シートを消|シートごと消|いらないシート|シートはいらない|シートを捨て|タブを消|シートごと削除|シート丸ごと削除|シート丸ごと消
// 違い: 改名は sheet.rename、追加は sheet.add
// 引数: name*=シート
// 例: 「集計シートを消して」 → {"shelf":"sheet.delete","name":"集計"}
// 危ない: 消す
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.delete'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var s = sheetOf_(ss, op.name, '');
  if (ss.getSheets().length <= 1) throw new ArgError('シートが1枚しかないため削除できません');
  guardDelete_(ctx, 'シート「' + op.name + '」を削除します', true, '1 枚');   // シートごと消す手は広い削除
  ss.deleteSheet(s);
  chg_(ctx, null, '', 'シート「' + op.name + '」を削除');
};

// 棚: sheet.copy
// 題: シートを複製する
// 分類: シート
// 語: シートを複製|シートをコピー|シートの写し|同じシートをもう|来月分を作|シートを複製して
// 違い: シートの追加は sheet.add、名前変更は sheet.rename
// 引数: name*=シート, as=文字, before=シート
// 頼み: as~[『「]([^』」]+)[』」]という名前
// 例: 「売上シートを複製して」 → {"shelf":"sheet.copy","name":"売上"}
// 例: 「売上シートを写して名前を来月売上にして」 → {"shelf":"sheet.copy","name":"売上","as":"来月売上"}
// 触る: シート構成
// 控え: 名前,全部
SHELF['sheet.copy'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var s = sheetOf_(ss, op.name, '');
  var targetName = op.as;
  if (targetName && ss.getSheetByName(targetName)) throw new ArgError('シート「' + targetName + '」はすでにあります');   // 複製する前に確かめる（複製した後に断ると、複製だけ残る）
  var bs = op.before ? sheetOf_(ss, op.before, '') : null;
  var c = s.copyTo(ss);
  ctx.createdSheets.push(c.getName());
  if (targetName) { c.setName(targetName); ctx.createdSheets[ctx.createdSheets.length - 1] = targetName; }
  if (bs) {
    ss.setActiveSheet(c);
    ss.moveActiveSheet(bs.getIndex());
  }
  ctx.curSheet = c.getName();
  chg_(ctx, c, '', 'シート「' + op.name + '」を複製' + (targetName ? '（名前: ' + targetName + '）' : ''));
};

// 棚: sheet.hide
// 題: シートを隠す
// 分類: シート
// 語: シートを隠|シートを非表示|シートを見えなく|シートを隠して|シート非表示
// 違い: シートを再表示するなら sheet.show。シートごと消すなら sheet.delete
// 引数: name*=シート
// 例: 「集計シートを隠して」 → {"shelf":"sheet.hide","name":"集計"}
// 触る: 隠し
// 控え: 名前,全部
SHELF['sheet.hide'] = function (ctx, op) {
  need_(op, ['name']);
  var ss = ctx.ss;
  var s = sheetOf_(ss, op.name, '');
  var visible = ss.getSheets().filter(function (sh) { return !sh.isSheetHidden(); });
  if (visible.length <= 1 && visible[0].getName() === s.getName()) {
    throw new ArgError('すべてのシートを非表示にすることはできません');
  }
  s.hideSheet();
  chg_(ctx, s, '', 'シート「' + op.name + '」を非表示に設定');
};

// 棚: sheet.show
// 題: 隠したシートを出す
// 分類: シート
// 語: シートを再表示|隠したシート|非表示のシート|シートを出|シートが見えない|非表示になっているシート|隠れているシート|シートを全部出
// 違い: シートを隠すなら sheet.hide
// 引数: name=シート
// 例: 「隠してある集計シートを再表示して」 → {"shelf":"sheet.show","name":"集計"}
// 例: 「非表示のシートを全部出して」 → {"shelf":"sheet.show"}
// 触る: 隠し
// 控え: 名前,全部
SHELF['sheet.show'] = function (ctx, op) {
  var ss = ctx.ss;
  if (op.name) {
    var s = sheetOf_(ss, op.name, '');
    s.showSheet();
    chg_(ctx, s, '', 'シート「' + op.name + '」を再表示');
  } else {
    var hidden = ss.getSheets().filter(function (sh) { return sh.isSheetHidden(); });
    hidden.forEach(function (sh) { sh.showSheet(); });
    chg_(ctx, null, '', hidden.length ? hidden.length + ' 枚のシートを再表示' : '非表示シートはありません（変更なし）');
  }
};

// 棚: sheet.color
// 題: タブの色を変える
// 分類: シート
// 語: タブの色|シートの色|タブを赤|タブに色|シート見出しの色|色変更|色を変え
// 違い: セルの色を変えるなら format
// 引数: name=シート, color*=色
// 例: 「売上シートのタブを赤にして」 → {"shelf":"sheet.color","name":"売上","color":"red"}
// 例: 「このシートの見出し色を青にして」 → {"shelf":"sheet.color","color":"blue"}
// 触る: タブ色
// 控え: 今
SHELF['sheet.color'] = function (ctx, op) {
  need_(op, ['color']);
  var s = op.name ? sheetOf_(ctx.ss, op.name, '') : sheetCtx_(ctx, op);
  var c = op.color;
  var hex = (c === 'なし' || c === 'none' || c === '') ? null : rgb_(c);
  s.setTabColor(hex);
  chg_(ctx, s, '', 'タブの色を「' + op.color + '」に変更');
};

// 棚: sheet.merge
// 題: 複数シートの表を1つのシートに縦結合する
// 分類: シート
// 語: シートを結合|シートをまとめ|シートを統合|複数シートを1枚|縦に結合|縦にまとめ|シートを合体|全シートをまとめ
// 違い: 項目ごとに集計するなら summary、シートを分割するなら sheet.split
// 引数: sheets=配列, into=文字=統合, skip_header=真偽=true
// 頼み: into~[『「]([^』」]+)[』」](?:シート)?に(?:まとめ|統合|結合) ; into~(?:表を|を)?\s*([^\sにへを「『]+?)シートに(?:縦に)?(?:まとめ|統合|結合)
// 例: 「全シートの表を統合シートに縦にまとめて」 → {"shelf":"sheet.merge","into":"統合"}
// 例: 「4月と5月のシートを上半期シートに結合して」 → {"shelf":"sheet.merge","sheets":["4月","5月"],"into":"上半期"}
// 触る: シート構成 値
// 控え: 名前,全部
SHELF['sheet.merge'] = function (ctx, op) {
  var ss = ctx.ss;
  var intoName = String(op.into || '統合').trim();
  var skipHeader = op.skip_header !== false;
  var srcSheets = [];
  if (op.sheets && op.sheets.length) {
    op.sheets.forEach(function (nm) {
      var s = sheetOf_(ss, nm, '');
      if (s.getName() !== intoName) srcSheets.push(s);
    });
  } else {
    ss.getSheets().forEach(function (s) {
      var nm = s.getName();
      if (nm !== intoName && nm !== '_GASクイックの控え' && !s.isSheetHidden()) srcSheets.push(s);
    });
  }
  if (!srcSheets.length) throw new ArgError('結合する元シートが見つかりません');

  var merged = [];
  var maxCols = 0;
  var usedCount = 0;
  srcSheets.forEach(function (s) {
    var lr = s.getLastRow(), lc = s.getLastColumn();
    if (lr < 1 || lc < 1) return;
    var vals = s.getRange(1, 1, lr, lc).getValues();
    var startIdx = (usedCount > 0 && skipHeader) ? 1 : 0;
    for (var r = startIdx; r < vals.length; r++) {
      merged.push(vals[r]);
      if (vals[r].length > maxCols) maxCols = vals[r].length;
    }
    usedCount++;
  });
  if (!merged.length || !maxCols) throw new ArgError('結合できるデータがありません');

  var normalized = merged.map(function (row) {
    var out = row.slice();
    while (out.length < maxCols) out.push('');
    return out;
  });
  var dest = ss.getSheetByName(intoName);
  if (!dest) {
    dest = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dest.clearContents();
  }
  dest.getRange(1, 1, normalized.length, maxCols).setValues(normalized);
  ctx.curSheet = intoName;
  chg_(ctx, dest, a1_(1, 1, normalized.length, maxCols), usedCount + ' シートを縦結合（計 ' + normalized.length + ' 行）');
};

// 棚: sheet.split
// 題: 列の値ごとにシートを自動分割する
// 分類: シート
// 語: シートを分割|シートに分け|ごとにシート|別シートに分け|部署ごとにシート|項目ごとにシート|シートを分け
// 違い: 複数シートをまとめるなら sheet.merge、列を分けるなら split.col
// 引数: col*=列, prefix=文字
// 頼み: col~([^\sの]+)ごとに(?:別)?シート
// 例: 「部署ごとにシートを分けて作って」 → {"shelf":"sheet.split","col":"部署"}
// 触る: シート構成 値
// 控え: 名前,全部
SHELF['sheet.split'] = function (ctx, op) {
  need_(op, ['col']);
  var ss = ctx.ss, sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var nc = t.lastCol - t.firstCol + 1;
  var header = headerNames_(t);
  var groups = {}, order = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var row = t.vals[r - 1].slice(t.firstCol - 1, t.lastCol);
    if (row.every(isBlank_)) continue;
    var rawKey = t.vals[r - 1][ci - 1];
    var key = isBlank_(rawKey) ? '未分類' : String(rawKey).trim();
    if (!groups[key]) { groups[key] = []; order.push(key); }
    groups[key].push(row);
  }
  if (!order.length) throw new ArgError('分割できるデータ行がありません');

  var prefix = op.prefix ? String(op.prefix) : '';
  var createdNames = [];
  var usedNames = {};
  order.forEach(function (k) {
    var baseSafe = (prefix + k).replace(/[\\\/\?\*\[\]:]/g, '_').slice(0, 31) || '分割';
    var safeName = baseSafe;
    if (usedNames[safeName]) {
      var dupIdx = 2;
      while (usedNames[safeName]) {
        var suf = '_' + dupIdx;
        safeName = baseSafe.slice(0, 31 - suf.length) + suf;
        dupIdx++;
      }
    }
    usedNames[safeName] = 1;
    var dst = ss.getSheetByName(safeName);
    if (!dst) {
      dst = ss.insertSheet(safeName, ss.getSheets().length);
      ctx.createdSheets.push(safeName);
    } else {
      dst.clearContents();
    }
    var out = [header].concat(groups[k]);
    dst.getRange(1, 1, out.length, nc).setValues(out);
    createdNames.push(safeName + '(' + groups[k].length + '件)');
  });
  chg_(ctx, sh, '', op.col + ' ごとに ' + order.length + ' シートへ分割: ' + createdNames.slice(0, 8).join('・') + (createdNames.length > 8 ? ' ほか' : ''));
};

// 棚: sheet.diff
// 題: 2つのシートの差分を比較する
// 分類: シート
// 語: シートを比較|シートの差分|2つのシートを比較|差分を比較|違いを比較|シート間の差分|シートの違い|変更点を比較
// 違い: 同じシート内の2列の引き算列を足すなら calc.diff
// 引数: from*=シート, to*=シート, into=文字=差分
// 頼み: from~[「『]?([^「『」』\sと]+?)[」』]?と[「『]?[^「『」』\s]+?[」』]?(?:の)?(?:シート)?(?:の)?(?:差分|違い|比較) ; to~[「『]?[^「『」』\sと]+?[」』]?と[「『]?([^「『」』\s]+?)[」』]?(?:の)?(?:シート)?(?:の)?(?:差分|違い|比較)
// 例: 「4月と5月のシートの差分を比較して」 → {"shelf":"sheet.diff","from":"4月","to":"5月"}
// 触る: シート構成 値
// 控え: 先
SHELF['sheet.diff'] = function (ctx, op) {
  need_(op, ['from', 'to']);
  var ss = ctx.ss;
  var s1 = sheetOf_(ss, op.from, '');
  var s2 = sheetOf_(ss, op.to, '');
  var lr1 = s1.getLastRow(), lc1 = s1.getLastColumn();
  var lr2 = s2.getLastRow(), lc2 = s2.getLastColumn();
  var maxR = Math.max(lr1, lr2), maxC = Math.max(lc1, lc2);
  var v1 = (lr1 > 0 && lc1 > 0) ? s1.getRange(1, 1, lr1, lc1).getDisplayValues() : [];
  var v2 = (lr2 > 0 && lc2 > 0) ? s2.getRange(1, 1, lr2, lc2).getDisplayValues() : [];
  var diffs = [], totalDiffs = 0, CAP = 5000;
  for (var r = 0; r < maxR; r++) {
    for (var c = 0; c < maxC; c++) {
      var a = (v1[r] && v1[r][c] !== undefined) ? String(v1[r][c]) : '';
      var b = (v2[r] && v2[r][c] !== undefined) ? String(v2[r][c]) : '';
      if (a !== b) {
        totalDiffs++;
        if (diffs.length < CAP) diffs.push([a1_(r + 1, c + 1), a, b]);
      }
    }
  }
  if (!totalDiffs) {
    note_(ctx, '「' + op.from + '」と「' + op.to + '」に差分はありませんでした');
    return;
  }
  var intoName = String(op.into || '差分').trim();
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var out = [['セル', op.from + 'の値', op.to + 'の値']].concat(diffs);
  dst.getRange(1, 1, out.length, 3).setValues(out);
  dst.getRange(1, 1, 1, 3).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
  ctx.curSheet = intoName;
  if (totalDiffs > CAP) note_(ctx, '差分が ' + totalDiffs + ' 件あったため先頭 ' + CAP + ' 件のみ出力しました');
  chg_(ctx, dst, a1_(1, 1, out.length, 3), '「' + op.from + '」と「' + op.to + '」の差分 ' + totalDiffs + ' 件を出力');
};

// 棚: sheet.toc
// 題: 全シートの目次シートを作る
// 分類: シート
// 語: 目次シート|目次を作|シート一覧を作|シートの目次|インデックスシート|リンク付き目次|全シートの目次
// 違い: 文書の目次なら doc.toc、シートの追加だけなら sheet.add
// 引数: into=文字=目次
// 頼み: into~[『「]([^』」]+)[』」](?:シート)?(?:に|として)?(?:目次|一覧)
// 例: 「全シートの目次シートを作って」 → {"shelf":"sheet.toc"}
// 触る: シート構成 値 書式
// 控え: 先
SHELF['sheet.toc'] = function (ctx, op) {
  var ss = ctx.ss;
  var intoName = String(op.into || '目次').trim();
  var targets = ss.getSheets().filter(function (s) {
    var nm = s.getName();
    return nm !== intoName && nm !== '_GASクイックの控え';
  });
  if (!targets.length) throw new ArgError('目次に載せるシートがありません');
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, 0);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var rows = [['No', 'シート名', '行数', '列数', '状態']];
  var linkRich = [];
  targets.forEach(function (s, idx) {
    var nm = s.getName();
    rows.push([idx + 1, nm, s.getLastRow(), s.getLastColumn(), s.isSheetHidden() ? '非表示' : '表示']);
    var rtv = SpreadsheetApp.newRichTextValue().setText(nm).setLinkUrl('#gid=' + s.getSheetId()).build();
    linkRich.push([rtv]);
  });
  dst.getRange(1, 1, rows.length, 5).setValues(rows);
  dst.getRange(2, 2, linkRich.length, 1).setRichTextValues(linkRich);
  dst.getRange(1, 1, 1, 5).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold').setHorizontalAlignment('center');
  dst.setColumnWidth(1, 50);
  dst.setColumnWidth(2, 220);
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, rows.length, 5), targets.length + ' シートのリンク付き目次を作成');
};

// 棚: book.finish
// 題: 全シートをA1に揃え提出前仕上げ
// 分類: シート
// 語: 提出前仕上げ|提出前の仕上げ|全シートをA1|全シートA1|カーソルをA1|A1に揃え|納品前仕上げ|提出用に整え
// 違い: 表の書式や列幅を整えるなら tidy、枠線の表示切替だけなら sheet.gridlines
// 引数: gridlines=真偽
// 頼み: gridlines=false<枠線を消|枠線なし|枠線を非表示|グリッド線を消|グリッド線なし|グリッド線を非表示 ; gridlines=true<枠線を表示|枠線あり|グリッド線を表示|グリッド線あり
// 例: 「全シートをA1に揃えて提出前仕上げをして」 → {"shelf":"book.finish"}
// 触る: 書式
// 控え: なし
SHELF['book.finish'] = function (ctx, op) {
  var ss = ctx.ss;
  var targets = ss.getSheets().filter(function (s) {
    return s.getName() !== '_GASクイックの控え' && !s.isSheetHidden();
  });
  if (!targets.length) throw new ArgError('仕上げ対象の可視シートがありません');
  targets.forEach(function (s) {
    s.activate();
    s.getRange('A1').activate();
    if (op.gridlines !== undefined && typeof s.setHiddenGridlines === 'function' && typeof s.isGridlinesHidden === 'function') {
      if (s.isGridlinesHidden() !== !op.gridlines) s.setHiddenGridlines(!op.gridlines);
    }
  });
  targets[0].activate();
  targets[0].getRange('A1').activate();
  ctx.curSheet = targets[0].getName();
  chg_(ctx, null, 'A1', '可視 ' + targets.length + ' シートを A1 選択に統一' + (op.gridlines !== undefined ? ('（枠線:' + (op.gridlines ? '表示' : '非表示') + '）') : ''));
};

// 棚: sheet.sort
// 題: シートを名前順に並べ替える
// 分類: シート
// 語: シートを名前順|シートを昇順|シートを降順|シートを並べ替|タブを名前順|タブを並べ替|シート名で並べ替|全シートを並べ替|シート名で降順|シート名で昇順
// 違い: 特定の1シートを動かすなら sheet.move、表の行を並べ替えるなら sort
// 引数: desc=真偽=false
// 頼み: desc=true<降順|逆順|Zから|大きい順 ; desc=false<昇順|名前順|あいうえお順|五十音順|Aから
// 例: 「シートを名前順に並べ替えて」 → {"shelf":"sheet.sort"}
// 触る: シート構成
// 控え: 全部
SHELF['sheet.sort'] = function (ctx, op) {
  var ss = ctx.ss;
  var list = ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; });
  if (list.length <= 1) {
    note_(ctx, '並べ替えるシートが 1 枚以下です（変更なし）');
    return;
  }
  var sorted = list.slice().sort(function (a, b) {
    var cmp = a.getName().localeCompare(b.getName(), 'ja');
    return op.desc ? -cmp : cmp;
  });
  var doneBatch = false;
  if (typeof Sheets !== 'undefined' && Sheets.Spreadsheets && typeof Sheets.Spreadsheets.batchUpdate === 'function' && typeof batchRetry_ === 'function') {
    try {
      var reqs = sorted.map(function (s, idx) {
        return { updateSheetProperties: { properties: { sheetId: s.getSheetId(), index: idx }, fields: 'index' } };
      });
      batchRetry_(ss, reqs);
      doneBatch = true;
    } catch (eBs) { doneBatch = false; }
  }
  if (!doneBatch) {
    var prevActive = null;
    try { prevActive = ss.getActiveSheet(); } catch (eAct) {}
    sorted.forEach(function (s, idx) {
      if (s.getIndex() !== idx + 1) {
        ss.setActiveSheet(s);
        ss.moveActiveSheet(idx + 1);
      }
    });
    if (prevActive) { try { ss.setActiveSheet(prevActive); } catch (eRest) {} }
  }
  chg_(ctx, null, '', 'シート ' + sorted.length + ' 枚を名前' + (op.desc ? '降順' : '昇順') + 'に並べ替え');
};

// 棚: sheet.snapshot
// 題: 日付つきでシートの控えを複製保存
// 分類: シート
// 語: スナップショット|日付つきで複製|日付付きで複製|日付入りで複製|控えを複製|バックアップシートを作|今日の控えを作|日付付き控え
// 違い: 任意の名前で複製するなら sheet.copy
// 引数: name=シート, suffix=文字
// 頼み: suffix~[『「]([^』」]+)[』」]を付け
// 例: 「売上シートを日付つきで複製保存して」 → {"shelf":"sheet.snapshot","name":"売上"}
// 触る: シート構成
// 控え: なし
SHELF['sheet.snapshot'] = function (ctx, op) {
  var ss = ctx.ss;
  var s = op.name ? sheetOf_(ss, op.name, '') : sheetCtx_(ctx, op);
  var suf = op.suffix ? String(op.suffix).trim() : '';
  if (!suf) {
    if (typeof Utilities !== 'undefined' && typeof Utilities.formatDate === 'function') {
      var tz = (typeof Session !== 'undefined' && Session.getScriptTimeZone) ? (Session.getScriptTimeZone() || 'Asia/Tokyo') : 'Asia/Tokyo';
      suf = Utilities.formatDate(new Date(), tz, 'yyyyMMdd');
    } else {
      var d = new Date();
      var pad = function (n) { return n < 10 ? '0' + n : String(n); };
      suf = d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate());
    }
  }
  var base = s.getName() + '_' + suf;
  var targetName = base;
  var seq = 2;
  while (ss.getSheetByName(targetName)) {
    targetName = base + '_' + seq;
    seq++;
  }
  var c = s.copyTo(ss);
  c.setName(targetName);
  ctx.createdSheets.push(targetName);
  ctx.curSheet = targetName;
  chg_(ctx, c, '', 'シート「' + s.getName() + '」の控え「' + targetName + '」を保存');
};

// 棚: sheet.list
// 題: シート一覧と大きさを見る
// 分類: シート
// 語: シート一覧|他のシート|別のシートがあ|シートがあるか|シートの一覧|どんなシート|全シート名|何枚シート
// 違い: 目次シートを作るなら sheet.toc。隠れたシートを出すなら sheet.show
// 引数: なし
// 例: 「シート一覧を教えて」 → {"shelf":"sheet.list"}
// 例: 「他のシートがあるか確認したい」 → {"shelf":"sheet.list"}
// 触る: なし
// 控え: なし
SHELF['sheet.list'] = function (ctx, op) {
  var sheets = ctx.ss.getSheets();
  var lines = sheets.map(function (s, idx) {
    var hidden = (typeof s.isSheetHidden === 'function' && s.isSheetHidden()) ? '（非表示）' : '';
    var lr = typeof s.getLastRow === 'function' ? s.getLastRow() : 0;
    var lc = typeof s.getLastColumn === 'function' ? s.getLastColumn() : 0;
    return (idx + 1) + '. ' + s.getName() + hidden + '（' + lr + '行×' + lc + '列）';
  });
  note_(ctx, 'シート一覧（' + sheets.length + ' 枚）:\n' + lines.join('\n'));
};
