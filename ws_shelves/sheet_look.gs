// 見た目の棚

// 棚: format
// 題: 範囲の書式を変える
// 分類: 見た目
// 語: 書式を|太字に|斜体に|色を付け|色を変え|色に変え|色にして|背景色|背景を|文字の色|文字色|フォントの色|フォント色|フォントを|文字サイズ|フォントサイズ|表示に|中央揃え|右揃え|左揃え|中央寄せ|右寄せ|左寄せ|桁区切り|桁区切りに|カンマ区切り|罫線を引|罫線を消|罫線をつけ|罫線を付け|外枠|外枠だけ|外枠を|結合解除|結合を解除|マージ|折り返し|赤く|青く|黄色く|緑に|赤にして|青にして|黄色にして|緑にして|黒にして|白にして|水色にして|紺にして|見出しの行|見出しを|黄色の背景|青い背景|薄い青色|色も付けて|を結合して|セルを結合|セルの結合|に罫線を引|表に罫線|曜日も出|曜日を出|曜日付き|曜日つき|表示形式|日付の表示|日付の見せ方
// 違い: 「〜の列」は範囲を切らず col:"列名" で渡す。条件付きは cf.add、1行おきは banding.add
// 引数: range=範囲, col=列, header=真偽, title=真偽, bold=真偽, italic=真偽, color=色, bg=色, size=数, font=文字, number_format=文字, align=文字, valign=文字, wrap=真偽, borders=文字, merge=真偽
// 頼み: bold=true<太字|太く ; italic=true<斜体|イタリック ; header=true<見出し|ヘッダ ; title=true<タイトル|表題 ; number_format=¥#,##0<円マーク|¥|円表示 ; number_format=#,##0<カンマ|桁区切り ; wrap=true<折り返 ; align=center<中央寄せ|中央揃え ; align=left<左寄せ|左揃え ; align=right<右寄せ|右揃え ; borders=false<罫線なし|罫線を消|罫線を削除|罫線解除|枠線なし|枠線を消|枠線解除 ; borders=outer<外枠|外罫線 ; borders=true<罫線を引|罫線をつけ|罫線を付け|罫線で囲|枠線を引|枠線をつけ|枠線を付け ; merge=false<結合解除|結合を解除|結合を外|結合を消|マージ解除 ; merge=true<結合|マージ ; number_format=m"月"d"日"(ddd)<曜日も|曜日を出|曜日付き|曜日つき ; size~([0-9]+)\s*(?:pt|ポイント)
// どれか: range col header title
// 例: 「見出しを太字で青い背景に」 → {"shelf":"format","header":true,"bold":true,"bg":"#1F4E79","color":"#FFFFFF"}
// 例: 「金額の列を桁区切りに」 → {"shelf":"format","col":"金額","number_format":"#,##0"}
// 触る: 書式
SHELF['format'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = null, rg;
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, 1, t.lastCol - t.firstCol + 1); }
  else if (op.title) { rg = titleRange_(sh); }
  else if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, (t.totalRow || t.lastData) - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「format」に range・col・header・title のどれかが要ります');
  var did = [];
  var set = function (key, fn) { if (op[key] !== undefined) { fn(op[key]); did.push(key); } };
  set('bold', function (v) { rg.setFontWeight(v ? 'bold' : 'normal'); });
  set('italic', function (v) { rg.setFontStyle(v ? 'italic' : 'normal'); });
  set('color', function (v) { rg.setFontColor(rgb_(v)); });
  set('bg', function (v) { rg.setBackground(rgb_(v)); });
  set('size', function (v) { rg.setFontSize(v); });
  set('font', function (v) { rg.setFontFamily(v); });
  set('number_format', function (v) { rg.setNumberFormat(v); });
  set('align', function (v) { rg.setHorizontalAlignment(v); });
  set('valign', function (v) { rg.setVerticalAlignment(v); });
  set('wrap', function (v) { rg.setWrap(!!v); });
  set('borders', function (v) { if (v) rg.setBorder(true, true, true, true, v === 'outer' ? false : true, v === 'outer' ? false : true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID); else rg.setBorder(false, false, false, false, false, false); });
  set('merge', function (v) { if (v) rg.merge(); else rg.breakApart(); });
  if (!did.length) throw new ArgError('棚「format」に書式の指定（bold・color・bg・number_format・align など）がありません');
  chg_(ctx, sh, rg.getA1Notation(), did.join('・'));
};

// 棚: bg.clear
// 題: 背景色を消す（塗りつぶしなしに戻す）
// 分類: 見た目
// 語: 背景色を消|背景色をなし|背景色を無し|背景色をなく|背景色を無く|背景色を取|背景色を外|背景色を解除|背景を消|背景をなし|背景を無し|塗りつぶしを消|塗りつぶしなし|塗りつぶしを解除|塗りなし|の色を消|背景色を消して|の背景色を消|背景色をなしに|背景色を無しに|の背景色をなし|の背景色を無し|背景色を白に戻
// 違い: 1行おきの縞を消すなら banding.remove。文字色や罫線も含めて書式ごと消すなら clear.format。別の色に塗るなら format（bg）
// 引数: range=範囲, col=列, header=真偽, title=真偽
// 頼み: header=true<見出し|ヘッダ ; title=true<タイトル|表題
// どれか: range col header title
// 例: 「A1の背景色を消して」 → {"shelf":"bg.clear","range":"A1"}
// 例: 「見出しの背景色をなしにして」 → {"shelf":"bg.clear","header":true}
// 触る: 書式
SHELF['bg.clear'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = null, rg;
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, 1, t.lastCol - t.firstCol + 1); }
  else if (op.title) { rg = titleRange_(sh); }
  else if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, (t.totalRow || t.lastData) - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「bg.clear」に range・col・header・title のどれかが要ります');
  rg.setBackground(null);
  chg_(ctx, sh, rg.getA1Notation(), '背景色なし');
};

// 棚: width
// 題: 列の幅・行の高さを変える
// 分類: 見た目
// 語: 列幅を|列の幅|幅を広げ|幅を狭め|行の高さ|幅を自動|自動調整|中身に合わせ|広げて
// 引数: cols=対応, col=列, width=数, rows=対応, auto=列[]
// 頼み: width~(?:幅を?|横幅を?)\s*([0-9]+)
// どれか: cols col rows auto
// 例: 「A列を幅200にして」 → {"shelf":"width","col":"A","width":200}
// 例: 「B列とC列の幅を中身に合わせて」 → {"shelf":"width","auto":["B","C"]}
// 触る: 幅
SHELF['width'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = findTable_(sh), did = [];
  var colRef = function (k) { return t ? colIndexOf_(t, k) : colNum_(k); };
  if (op.cols) Object.keys(op.cols).forEach(function (k) { sh.setColumnWidth(colRef(k), op.cols[k]); did.push(k + '列'); });
  if (op.col && op.width) { sh.setColumnWidth(colRef(op.col), op.width); did.push(op.col + '列'); }
  if (op.rows) Object.keys(op.rows).forEach(function (k) { sh.setRowHeight(parseInt(k), op.rows[k]); did.push(k + '行'); });
  (op.auto || []).forEach(function (k) {
    var ci = colRef(k), lr = sh.getLastRow(), mx = 0;
    if (lr > 0) sh.getRange(1, ci, lr, 1).getDisplayValues().forEach(function (x) { mx = Math.max(mx, wlen_(x[0])); });
    sh.setColumnWidth(ci, Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad))); did.push(k + '列(自動)');
  });
  if (!did.length) throw new ArgError('棚「width」に cols・rows・auto のどれかが要ります');
  chg_(ctx, sh, did.join('・'), '幅・高さを変更');
};

// 棚: cf.add
// 題: 条件付き書式を付ける
// 分類: 見た目
// 語: 条件付き書式|以上なら|以下なら|未満は|のとき色|入ってい|を目立たせ|自動で色|未満は黄色|未満なら|以上は|以下は|より大きい|より小さい
// 違い: いつも同じ色なら format
// 引数: range*=範囲, when*=選択(gt/ge/lt/le/eq/ne/contains/blank/notblank/formula), value=文字, bg=色, color=色, bold=真偽
// 頼み: when=ge<以上 ; when=le<以下 ; when=lt<未満|より小さい|より少ない ; when=gt<より大きい|を超え|超える|より多い ; when=contains<が入っている|を含む|が含まれ ; when=blank<空欄のセル|空白のセル ; value~([0-9][0-9,]*)(?:円|個|件|人)?(?:以上|以下|未満|より|を超|超) ; value~[『「]([^』」]+)[』」]
// 例: 「売上が100万以上のセルを赤く」 → {"shelf":"cf.add","range":"F2:F100","when":"ge","value":"1000000","bg":"赤"}
// 例: 「売上が100万以上の行を目立たせて」 → {"shelf":"cf.add","range":"A2:F100","when":"formula","value":"=$F2>=1000000","bg":"薄赤"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.add'] = function (ctx, op) {
  need_(op, ['range', 'when']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var rule = SpreadsheetApp.newConditionalFormatRule().setRanges([rg]);
  var w = String(op.when).toLowerCase(), val = op.value !== undefined ? String(op.value) : '';
  if (w === 'gt') rule.whenNumberGreaterThan(Number(val));
  else if (w === 'ge') rule.whenNumberGreaterThanOrEqualTo(Number(val));
  else if (w === 'lt') rule.whenNumberLessThan(Number(val));
  else if (w === 'le') rule.whenNumberLessThanOrEqualTo(Number(val));
  else if (w === 'eq') rule.whenNumberEqualTo(Number(val));
  else if (w === 'ne') rule.whenNumberNotEqualTo(Number(val));
  else if (w === 'contains') rule.whenTextContains(val);
  else if (w === 'blank') rule.whenCellEmpty();
  else if (w === 'notblank') rule.whenCellNotEmpty();
  else if (w === 'formula') rule.whenFormulaSatisfied(val);
  else throw new ArgError('知らない when: ' + op.when);

  if (op.bg) rule.setBackground(rgb_(op.bg));
  if (op.color) rule.setFontColor(rgb_(op.color));
  if (op.bold) rule.setBold(true);

  var rules = sh.getConditionalFormatRules();
  rules.push(rule.build());
  sh.setConditionalFormatRules(rules);
  chg_(ctx, sh, rg.getA1Notation(), '条件付き書式を付与（when: ' + op.when + '）');
};

// 棚: cf.dup
// 題: 重複に色を付ける
// 分類: 見た目
// 語: 重複に色|重複を赤|ダブりに色|重複を目立|重複をハイライト|重複してるとこ|ダブっている|ダブっている行に色
// 違い: 重複した行を消すなら dedupe
// 引数: range*=範囲, bg=色
// 例: 「C列の重複を赤く」 → {"shelf":"cf.dup","range":"C2:C100","bg":"赤"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.dup'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var bg = op.bg ? rgb_(op.bg) : '#FCE4D6';
  var firstCellA1 = rg.getCell(1, 1).getA1Notation();
  var startCol = colLetter_(rg.getColumn()), endCol = colLetter_(rg.getLastColumn());
  var startRow = rg.getRow(), endRow = rg.getLastRow();
  var absRange = '$' + startCol + '$' + startRow + ':$' + endCol + '$' + endRow;
  var formula = '=COUNTIF(' + absRange + ', ' + firstCellA1 + ')>1';

  var rule = SpreadsheetApp.newConditionalFormatRule()
    .setRanges([rg])
    .whenFormulaSatisfied(formula)
    .setBackground(bg)
    .build();

  var rules = sh.getConditionalFormatRules();
  rules.push(rule);
  sh.setConditionalFormatRules(rules);
  chg_(ctx, sh, rg.getA1Notation(), '重複セルの条件付き書式を付与（' + formula + '）');
};

// 棚: cf.scale
// 題: カラースケールを付ける
// 分類: 見た目
// 語: カラースケール|色の濃淡|グラデーション|ヒートマップ|大きいほど濃
// 引数: range*=範囲, low=色, high=色
// 例: 「売上列を青のグラデーションにして」 → {"shelf":"cf.scale","range":"F2:F100","low":"白","high":"青"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.scale'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var low = rgb_(op.low || '白');
  var high = rgb_(op.high || '#2E75B6');

  var rule = SpreadsheetApp.newConditionalFormatRule()
    .setRanges([rg])
    .setGradientMinpoint(low)
    .setGradientMaxpoint(high)
    .build();

  var rules = sh.getConditionalFormatRules();
  rules.push(rule);
  sh.setConditionalFormatRules(rules);
  chg_(ctx, sh, rg.getA1Notation(), 'カラースケール条件付き書式を付与');
};

// 棚: cf.clear
// 題: 条件付き書式を外す
// 分類: 見た目
// 語: 条件付き書式を消|条件付き書式を外|条件付き書式を削除|自動の色を消
// 引数: range=範囲
// 例: 「条件付き書式を全部消して」 → {"shelf":"cf.clear"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.clear'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  if (!op.range) {
    sh.clearConditionalFormatRules();
    chg_(ctx, sh, 'シート全体', '条件付き書式をすべて解除');
    return;
  }
  var targetRg = sh.getRange(op.range);
  var tRow = targetRg.getRow(), tLastRow = targetRg.getLastRow();
  var tCol = targetRg.getColumn(), tLastCol = targetRg.getLastColumn();

  var rules = sh.getConditionalFormatRules();
  var kept = [];
  rules.forEach(function (r) {
    var rRanges = r.getRanges();
    var hit = rRanges.some(function (rg) {
      return !(rg.getLastRow() < tRow || rg.getRow() > tLastRow || rg.getLastColumn() < tCol || rg.getColumn() > tLastCol);
    });
    if (!hit) kept.push(r);
  });
  sh.setConditionalFormatRules(kept);
  chg_(ctx, sh, targetRg.getA1Notation(), '条件付き書式を解除');
};

// 棚: cf.list
// 題: 条件付き書式を一覧にする
// 分類: 見た目
// 語: 条件付き書式を一覧|条件付き書式を調べ|条件付き書式はどこ|条件付き書式を確認
// 引数: なし
// 例: 「設定されている条件付き書式を教えて」 → {"shelf":"cf.list"}
// 触る: なし
// 控え: なし
SHELF['cf.list'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var rules = sh.getConditionalFormatRules();
  if (!rules.length) {
    ctx.notes.push('シート「' + sh.getName() + '」に条件付き書式はありません');
    return;
  }
  var list = rules.map(function (r, i) {
    var ranges = r.getRanges().map(function (rg) { return rg.getA1Notation(); }).join(', ');
    var crit = r.getBooleanCondition();
    var grad = r.getGradientCondition();
    var desc = crit ? ('条件: ' + crit.getCriteriaType()) : (grad ? 'カラースケール' : '書式ルール');
    return '#' + (i + 1) + ' ' + ranges + ' (' + desc + ')';
  });
  ctx.notes.push('シート「' + sh.getName() + '」の条件付き書式（' + rules.length + ' 件）: ' + list.join('； '));
};

// 棚: banding.add
// 題: 交互の色を付ける
// 分類: 見た目
// 語: 交互の背景色|交互の背景色を|交互に背景色|交互の色|交互に色|しましま|縞模様|1行おきに色|ストライプ
// 違い: 自分で色を選ぶなら format
// 引数: range=範囲, theme=選択(gray/blue/green/orange)=gray
// 頼み: theme=blue<青|ブルー ; theme=green<緑|グリーン ; theme=orange<橙|オレンジ ; theme=gray<灰|グレー
// 例: 「表を1行おきに薄いグレーにして」 → {"shelf":"banding.add","theme":"gray"}
// 触る: 交互の色
// 控え: 今
SHELF['banding.add'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.range) rg = sh.getRange(op.range);
  else {
    var t = needTable_(sh);
    rg = sh.getRange(t.headerRow, t.firstCol, (t.totalRow || t.lastData) - t.headerRow + 1, t.lastCol - t.firstCol + 1);
  }
  rg.getBandings().forEach(function (b) { b.remove(); });

  var themeStr = (op.theme || 'gray').toLowerCase();
  var theme = SpreadsheetApp.BandingTheme.LIGHT_GREY;
  if (themeStr === 'blue') theme = SpreadsheetApp.BandingTheme.BLUE;
  else if (themeStr === 'green') theme = SpreadsheetApp.BandingTheme.GREEN;
  else if (themeStr === 'orange') theme = SpreadsheetApp.BandingTheme.ORANGE;
  else if (themeStr === 'gray' || themeStr === 'grey') theme = SpreadsheetApp.BandingTheme.LIGHT_GREY;

  var t2 = findTable_(sh);
  var hasHeader = t2 ? (rg.getRow() === t2.headerRow) : true;
  var hasFooter = t2 && t2.totalRow ? (rg.getLastRow() === t2.totalRow) : false;

  rg.applyRowBanding(theme, hasHeader, hasFooter);
  chg_(ctx, sh, rg.getA1Notation(), '交互の背景色を付与（テーマ: ' + (op.theme || 'gray') + '）');
};

// 棚: banding.remove
// 題: 交互の色を外す
// 分類: 見た目
// 語: 交互の背景色を消して|交互の背景色を消|交互の背景色を解除|交互の背景を消|交互の色を外|交互の色を消|しましまを消|縞模様を消|ストライプを解除|縞模様を解除|ストライプを消|1行おきの色を消|1行おきのしましまを消
// 引数: range=範囲
// 例: 「1行おきについてる色を外して」 → {"shelf":"banding.remove"}
// 触る: 交互の色
// 控え: 今
SHELF['banding.remove'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.range) rg = sh.getRange(op.range);
  else {
    var t = findTable_(sh);
    rg = t ? sh.getRange(t.headerRow, t.firstCol, (t.totalRow || t.lastData) - t.headerRow + 1, t.lastCol - t.firstCol + 1) : sh.getDataRange();
  }
  var bandings = rg.getBandings();
  if (!bandings.length) {
    bandings = sh.getBandings();
  }
  bandings.forEach(function (b) { b.remove(); });
  chg_(ctx, sh, rg.getA1Notation(), '交互の背景色を解除');
};
