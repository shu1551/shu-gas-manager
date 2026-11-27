// 範囲の棚

// 棚: write
// 題: セルに値・式を書く
// 分類: 範囲
// 語: 値を書|値を入れ|セルに入れ|式を入れ|書いて|を書き込|入力して|打ち直|と入力|と書いて|セットして|の値を|値を変え|値を書き換|を入れて|に入力
// 引数: cells=対応, range=範囲, tsv=文字
// 頼み: cells~([A-Z]{1,3}[0-9]+)の[^\sを]{0,8}を[『「]?([^』」に]+?)[』」]?に(?:書き換|打ち直|直|変え|入れ) ; cells~(?<![A-Za-z0-9:])([A-Za-z]{1,3}[0-9]+)に(?!チェックボックス)[『「]?([^』」]+?)[』」]?(?=[、,]\s*[A-Za-z]{1,3}[0-9]+に|(?:と(?:書|入力|記載|記入|入)|を(?:書|入|入力|セット)))
// どれか: cells tsv
// 例: 「B2に100、B3に200を入れて」 → {"shelf":"write","cells":{"B2":100,"B3":200}}
// 触る: 値
SHELF['write'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), did = [];
  if (op.cells) Object.keys(op.cells).forEach(function (a) { sh.getRange(a).setValue(op.cells[a]); did.push(a); });
  if (op.tsv !== undefined) {
    need_(op, ['range']);
    var start = sh.getRange(op.range.split(':')[0]);
    var rows = String(op.tsv).split(/\r?\n/).map(function (l) { return l.split('\t'); });
    var nc = Math.max.apply(null, rows.map(function (r) { return r.length; }));
    rows = rows.map(function (r) { while (r.length < nc) r.push(''); return r; });
    var rg = sh.getRange(start.getRow(), start.getColumn(), rows.length, nc);
    rg.setValues(rows); did.push(rg.getA1Notation());
  }
  if (!did.length) throw new ArgError('棚「write」に cells か（range と tsv）が要ります');
  chg_(ctx, sh, did.join('・'), '値・式を書いた');
};

// 棚: replace
// 題: 文字を探して置き換える
// 分類: 範囲
// 語: 置換|置き換え|書き換え|文字を探して|を直して|一括で変|名前を変えて|に置き換
// 違い: 重複行を消すなら dedupe。全角半角や空白の整理なら seiri
// 引数: find*=文字, with=文字, range=範囲, match_case=真偽, whole=真偽, all_sheets=真偽=false
// 頼み: find~[『「]([^』」]+)[』」]を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; with~[『「][^』」]+[』」]を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; find~(?:(?:全シート|すべてのシート|全てのシート|ブック全体)で\s*)?([^0-9A-Za-z\sを式]+)を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; with~(?:(?:全シート|すべてのシート|全てのシート|ブック全体)で\s*)?[^0-9A-Za-z\sを式]+を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体
// 例: 「営業部を営業課に置き換えて」 → {"shelf":"replace","find":"営業部","with":"営業課"}
// 触る: 値
SHELF['replace'] = function (ctx, op) {
  need_(op, ['find']);
  var replWith = String(op['with'] === undefined ? '' : op['with']);
  if (op.all_sheets) {
    var totalHits = 0, hitSheets = [];
    ctx.ss.getSheets().forEach(function (s) {
      if (s.getName() === '_GASクイックの控え') return;
      var sc = s.getDataRange();
      var tf = sc.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole);
      var cnt = tf.findAll().length;
      if (cnt > 0) {
        sc.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole).replaceAllWith(replWith);
        totalHits += cnt;
        hitSheets.push(s.getName() + '(' + cnt + '件)');
      }
    });
    if (!totalHits) { note_(ctx, '全シートで「' + op.find + '」は見つかりませんでした'); return; }
    chg_(ctx, null, hitSheets.slice(0, 4).join('・') + (hitSheets.length > 4 ? ' ほか' : ''), '全シート「' + op.find + '」→「' + replWith + '」（計 ' + totalHits + ' 件）');
    return;
  }
  var sh = sheetCtx_(ctx, op), scope = op.range ? sh.getRange(op.range) : sh.getDataRange();
  var tf = scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole);
  var hits = tf.findAll().map(function (r) { return r.getA1Notation(); });
  if (!hits.length) { note_(ctx, '「' + op.find + '」は見つかりませんでした'); return; }
  scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole).replaceAllWith(replWith);
  chg_(ctx, sh, hits.slice(0, 4).join('・') + (hits.length > 4 ? ' ほか' + (hits.length - 4) + ' 件' : ''), '「' + op.find + '」→「' + replWith + '」');
};
DYNAMIC['replace'] = {
  touch: function () { return ['値']; },
  sheets: function (ctx, op) {
    if (op.all_sheets) {
      return ctx.ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; }).map(function (s) { return s.getName(); });
    }
    return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()];
  }
};

// 棚: find
// 題: 値を探して番地を返す
// 分類: 範囲
// 語: を探して|を検索|どこにある|があるセル|入っているセル|どのセル
// 違い: 置き換えるなら replace、値を取り出すなら ws_look
// 引数: text*=文字, range=範囲, whole=真偽, all_sheets=真偽
// 頼み: text~[「『]([^」』]+)[」』] ; text~([^\sがを]+?)が入って ; text~([^\sがを]+?)がある ; text~から([^\sをの]+)のセル
// 例: 「売上合計が入っているセルを探して」 → {"shelf":"find","text":"売上合計"}
// 例: 「A列から完了のセルを検索して」 → {"shelf":"find","text":"完了","range":"A:A","whole":true}
// 触る: なし
// 控え: なし
SHELF['find'] = function (ctx, op) {
  need_(op, ['text']);
  var ss = ctx.ss;
  var hits = [];
  if (op.all_sheets) {
    ss.getSheets().forEach(function (s) {
      var tf = s.getDataRange().createTextFinder(String(op.text)).matchEntireCell(!!op.whole);
      var res = tf.findAll();
      res.forEach(function (r) { hits.push(s.getName() + '!' + r.getA1Notation()); });
    });
  } else {
    var sh = sheetCtx_(ctx, op);
    var scope = op.range ? sh.getRange(op.range) : sh.getDataRange();
    var tf = scope.createTextFinder(String(op.text)).matchEntireCell(!!op.whole);
    var res = tf.findAll();
    res.forEach(function (r) { hits.push(r.getA1Notation()); });
  }
  if (!hits.length) {
    note_(ctx, '「' + op.text + '」は見つかりませんでした');
  } else {
    var first20 = hits.slice(0, 20);
    note_(ctx, '「' + op.text + '」の見つかったセル (' + hits.length + '件): ' + first20.join(', ') + (hits.length > 20 ? ' ほか' + (hits.length - 20) + '件' : ''));
  }
};

// 棚: clear.values
// 題: 範囲の値を消す（書式は残す）
// 分類: 範囲
// 語: 値を消|値をクリア|中身を消|中身を空|入力を消|数字を消|データを消|範囲の値を消|セルの値を消|セルを消|番地を消|の値を消して|数字だけ消|消しといて
// 違い: 範囲を省略するとシート全体の値を消す。書式ごと消すなら clear.all。書式だけなら clear.format。行ごと消すなら rows.delete
// 引数: range=範囲, only=選択(all/constants)=all
// 頼み: range~([A-Z]{1,3}[0-9]+(?:\s*から\s*|〜|~|－|-)[A-Z]{1,3}[0-9]+)を消
// 例: 「B2からD10の中身を消して」 → {"shelf":"clear.values","range":"B2:D10"}
// 例: 「数字だけ消して式は残して」 → {"shelf":"clear.values","range":"A2:F50","only":"constants"}
// 危ない: 消す
// 触る: 値
// 控え: 今
SHELF['clear.values'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var raw = op.range ? String(op.range).trim() : '';
  var rg, label;
  if (!raw || /^(all|\*|全体|全セル|シート全体|sheet)$/i.test(raw)) {
    rg = sh.getDataRange();
    label = 'シート全体（' + rg.getA1Notation() + '）';
  } else {
    var fixed = raw.replace(/^([A-Za-z]+)1:([A-Za-z]+)$/, '$1:$2');
    try {
      rg = sh.getRange(fixed);
    } catch (e) {
      var m = fixed.match(/^([A-Za-z]+)(\d*):([A-Za-z]+)(\d*)$/);
      if (!m) throw e;
      var colToNum_ = function (col) {
        var n = 0; col = col.toUpperCase();
        for (var i = 0; i < col.length; i++) n = n * 26 + (col.charCodeAt(i) - 64);
        return n;
      };
      var maxR = sh.getMaxRows(), maxC = sh.getMaxColumns();
      var c1 = colToNum_(m[1]), c2 = colToNum_(m[3]);
      var r1 = m[2] ? parseInt(m[2], 10) : 1, r2 = m[4] ? parseInt(m[4], 10) : maxR;
      if (c1 < 1 || c1 > maxC || r1 < 1 || r1 > maxR) throw e;
      c2 = Math.min(c2, maxC); r2 = Math.min(r2, maxR);
      if (c2 < c1 || r2 < r1) throw e;
      rg = sh.getRange(r1, c1, r2 - r1 + 1, c2 - c1 + 1);
    }
    label = '範囲「' + op.range + '」';
  }
  guardDelete_(ctx, label + 'の値を消します', wideRange_(sh, rg), rg.getNumRows() * rg.getNumColumns() + ' セル');
  var only = op.only || 'all';
  if (only === 'constants') {
    var formulas = rg.getFormulas();
    var vals = rg.getValues();
    var changed = false;
    for (var r = 0; r < vals.length; r++) {
      for (var c = 0; c < vals[r].length; c++) {
        if (formulas[r][c]) {
          vals[r][c] = formulas[r][c];
        } else if (vals[r][c] !== '') {
          vals[r][c] = '';
          changed = true;
        }
      }
    }
    if (changed) rg.setValues(vals);
  } else {
    rg.clearContent();
  }
  chg_(ctx, sh, rg.getA1Notation(), '値を消去');
};

// 棚: clear.format
// 題: 範囲の書式を消す（値は残す）
// 分類: 範囲
// 語: 書式を消|書式をクリア|書式をリセット|色を消|色を元に|色や罫線を消|色と罫線を消|書式を元に
// 違い: 値ごと消すなら clear.all。値だけなら clear.values
// 引数: range*=範囲
// 例: 「A1からE20の書式をクリアして」 → {"shelf":"clear.format","range":"A1:E20"}
// 触る: 書式
// 控え: 今
SHELF['clear.format'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  rg.clearFormat();
  chg_(ctx, sh, rg.getA1Notation(), '書式をクリア');
};

// 棚: clear.all
// 題: 範囲の値と書式を消す
// 分類: 範囲
// 語: 全部消|すべて消|まっさら|全部クリア|すべてクリア|全クリア|白紙に|書式ごと消|値も書式も全部|値も書式も|値と書式も|全部消して空に
// 違い: 値だけ消すなら clear.values。書式だけなら clear.format
// 引数: range*=範囲
// 例: 「B2からD10を全部クリアして」 → {"shelf":"clear.all","range":"B2:D10"}
// 危ない: 消す
// 触る: 値 書式
// 控え: 今
SHELF['clear.all'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  guardDelete_(ctx, '範囲「' + op.range + '」の値と書式を消します', wideRange_(sh, rg), rg.getNumRows() * rg.getNumColumns() + ' セル');
  rg.clear();
  chg_(ctx, sh, rg.getA1Notation(), '値と書式をクリア');
};

// 棚: copy
// 題: 範囲を写す
// 分類: 範囲
// 語: をコピーして|を貼り付け|を写して|を複写|同じ物を|範囲をコピー
// 違い: 値だけなら copy.values、書式だけなら copy.format
// 引数: from*=範囲, to*=範囲
// 例: 「A1:B10をD1:E10にコピーして」 → {"shelf":"copy","from":"A1:B10","to":"D1:E10"}
// 例: 「売上表を別の場所に写して」 → {"shelf":"copy","from":"A1:C5","to":"F1"}
// 危ない: 上書き
// 触る: 値 書式
// 控え: 今
SHELF['copy'] = function (ctx, op) {
  need_(op, ['from', 'to']);
  var sh = sheetCtx_(ctx, op);
  var srcRg = op.from.indexOf('!') >= 0 ? ctx.ss.getRange(op.from) : sh.getRange(op.from);
  var destRg = op.to.indexOf('!') >= 0 ? ctx.ss.getRange(op.to) : sh.getRange(op.to);
  var destSh = destRg.getSheet();
  var targetRg = destSh.getRange(destRg.getRow(), destRg.getColumn(), srcRg.getNumRows(), srcRg.getNumColumns());
  guardOverwrite_(ctx, targetRg, '貼り付け先「' + targetRg.getA1Notation() + '」');
  srcRg.copyTo(destRg);
  chg_(ctx, destSh, targetRg.getA1Notation(), '「' + op.from + '」からコピー');
};

// 棚: copy.values
// 題: 値だけ貼り付ける・式を値にする
// 分類: 範囲
// 語: 値だけ貼|値のみ貼|値として貼|式を値に|数式を値に|値に変え|値貼り付け|数式を値にして|値にして固定|数式 値化
// 違い: 全部写すなら copy、書式だけなら copy.format
// 引数: from*=範囲, to=範囲
// 例: 「A1:B10をD1:E10に値だけ貼り付けて」 → {"shelf":"copy.values","from":"A1:B10","to":"D1:E10"}
// 例: 「A1:B10の値をD1へ値貼り付けして」 → {"shelf":"copy.values","from":"A1:B10","to":"D1"}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['copy.values'] = function (ctx, op) {
  need_(op, ['from']);
  var sh = sheetCtx_(ctx, op);
  var srcRg = op.from.indexOf('!') >= 0 ? ctx.ss.getRange(op.from) : sh.getRange(op.from);
  var destRg = op.to ? (op.to.indexOf('!') >= 0 ? ctx.ss.getRange(op.to) : sh.getRange(op.to)) : srcRg;
  var destSh = destRg.getSheet();
  var targetRg = destSh.getRange(destRg.getRow(), destRg.getColumn(), srcRg.getNumRows(), srcRg.getNumColumns());
  guardOverwrite_(ctx, targetRg, '値貼り付け先「' + targetRg.getA1Notation() + '」');
  srcRg.copyTo(targetRg, SpreadsheetApp.CopyPasteType.PASTE_VALUES, false);
  chg_(ctx, destSh, targetRg.getA1Notation(), '値のみ貼り付け');
};

// 棚: copy.format
// 題: 書式だけ貼り付ける
// 分類: 範囲
// 語: 書式だけ貼|書式のみ貼|書式をコピー|の書式をコピー|書式を写|同じ書式に|同じ見た目に|書式貼り付け|書式をコピーして貼|書式だけ写|書式を写しといて
// 違い: 全部写すなら copy、値だけなら copy.values
// 引数: from*=範囲, to*=範囲
// 例: 「A1の書式をB1:E1にコピーして」 → {"shelf":"copy.format","from":"A1","to":"B1:E1"}
// 触る: 書式
// 控え: 今
SHELF['copy.format'] = function (ctx, op) {
  need_(op, ['from', 'to']);
  var sh = sheetCtx_(ctx, op);
  var srcRg = op.from.indexOf('!') >= 0 ? ctx.ss.getRange(op.from) : sh.getRange(op.from);
  var destRg = op.to.indexOf('!') >= 0 ? ctx.ss.getRange(op.to) : sh.getRange(op.to);
  srcRg.copyTo(destRg, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
  chg_(ctx, destRg.getSheet(), destRg.getA1Notation(), '書式のみ貼り付け');
};

// 棚: fill.series
// 題: 範囲に連番を埋める
// 分類: 範囲
// 語: 連番を入|連番を埋|1から順|通し番号を入|番号を下まで|通し番号を振
// 違い: 番地の範囲（A2:A20 や A列）を指して、その範囲に連番を書き込む（空の列にも書ける。値があれば上書きなので ok が要る）。表にある番号の列を見出しの名前で直すだけなら renumber、日付なら fill.date
// 引数: range*=範囲, start=数=1, step=数=1
// 頼み: start~([0-9]+)から(?:連番|番号)
// 例: 「A列に1から連番を入れて」 → {"shelf":"fill.series","range":"A2:A20"}
// 例: 「10から5刻みで番号を埋めて」 → {"shelf":"fill.series","range":"B2:B10","start":10,"step":5}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['fill.series'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  guardOverwrite_(ctx, rg, '範囲「' + op.range + '」に連番を記入');
  var start = op.start !== undefined ? Number(op.start) : 1;
  var step = op.step !== undefined ? Number(op.step) : 1;
  var nr = rg.getNumRows(), nc = rg.getNumColumns();
  var vals = [];
  var cur = start;
  for (var r = 0; r < nr; r++) {
    var row = [];
    for (var c = 0; c < nc; c++) {
      row.push(cur);
      cur += step;
    }
    vals.push(row);
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '連番を記入（' + start + 'から step ' + step + '）');
};

// 棚: date.fix
// 題: 文字・和暦の日付を本物の日付に直してそろえる
// 分類: 範囲
// 語: ちゃんとした日付|本物の日付|日付に直|日付にして|日付にしておいて|文字の日付|文字で入って|日付じゃなく|日付として扱|日付型|日付と認識|日付の文字列|文字列を日付|日付に変換|和暦|西暦の日付|日付をそろ|日付を揃
// 違い: 日付の見せ方（「11月4日(水)」など）を変えるだけなら format の number_format。和暦（R5.4.1・令和5年4月1日）や文字日付を本物の日付へ変換して揃えるならこの棚。日付を下へ連続で入れるなら fill.date
// 引数: col=列, range=範囲, format=文字
// どれか: col range
// 例: 「日付の列に文字で入っている日付を、ちゃんとした日付にして」 → {"shelf":"date.fix","col":"日付"}
// 例: 「入社日をすべて yyyy/mm/dd の形にそろえて」 → {"shelf":"date.fix","col":"入社日","format":"yyyy/mm/dd"}
// 触る: 値 書式
// 控え: 今
SHELF['date.fix'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg, t = null;
  if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「date.fix」に col か range が要ります');
  var vals = rg.getValues(), forms = rg.getFormulas(), fmts = rg.getNumberFormats();
  var startR = rg.getRow(), startC = rg.getColumn();
  // 年を書いていない日付（「11月4日」）は、同じ列の本物の日付の年に合わせる（無ければ今年）
  var year = new Date().getFullYear(), dateFmt = op.format ? String(op.format) : '';
  for (var r0 = 0; r0 < vals.length; r0++) for (var c0 = 0; c0 < vals[r0].length; c0++) {
    var v0 = vals[r0][c0];
    if (v0 instanceof Date && !isNaN(v0.getTime())) { year = v0.getFullYear(); if (!dateFmt && fmts[r0][c0] && fmts[r0][c0] !== '@') dateFmt = fmts[r0][c0]; }
  }
  var targetFmt = dateFmt || 'yyyy/mm/dd';
  var z2h = function (x) {
    return x
      .replace(/[０-９Ａ-Ｚａ-ｚ]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); })
      .replace(/[／－―ー‐．]/g, function (ch) { return ch === '／' ? '/' : (ch === '．' ? '.' : '-'); });
  };
  var mk = function (y, m, d) { var dt = new Date(y, m - 1, d); return (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d) ? dt : null; };
  var eraBase = { '令和': 2018, 'R': 2018, '平成': 1988, 'H': 1988, '昭和': 1925, 'S': 1925, '大正': 1911, 'T': 1911, '明治': 1867, 'M': 1867 };
  var fixed = [], fmtOnly = 0;
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    var v = vals[r][c];
    if (forms[r][c]) continue;
    if (v instanceof Date && !isNaN(v.getTime())) {
      if (op.format && fmts[r][c] !== targetFmt) { fmts[r][c] = targetFmt; fmtOnly++; }
      continue;
    }
    if (typeof v !== 'string' || !v.trim()) continue;
    var s = z2h(v.trim()).replace(/\s*[(（][^)）]*[)）]\s*$/, '');      // 後ろの（水）は外して読む
    var dt = null, m;
    if ((m = s.match(/^(\d{4})\s*[\/\-.年]\s*(\d{1,2})\s*[\/\-.月]\s*(\d{1,2})\s*日?$/))) {
      dt = mk(+m[1], +m[2], +m[3]);
    } else if ((m = s.match(/^(令和|平成|昭和|大正|明治|[RrHhSsTtMm])\s*(元|\d{1,2})\s*[\/\-.年]\s*(\d{1,2})\s*[\/\-.月]\s*(\d{1,2})\s*日?$/))) {
      var b = eraBase[m[1].toUpperCase()];
      var ey = m[2] === '元' ? 1 : +m[2];
      if (b && ey >= 1 && ey <= 99) dt = mk(b + ey, +m[3], +m[4]);
    } else if ((m = s.match(/^(\d{1,2})\s*[\/月]\s*(\d{1,2})\s*日?$/))) {
      dt = mk(year, +m[1], +m[2]);
    }
    if (!dt) continue;
    vals[r][c] = dt;
    if (op.format || !fmts[r][c] || fmts[r][c] === '@' || fmts[r][c] === 'General') fmts[r][c] = targetFmt;
    fixed.push(a1_(startR + r, startC + c));
  }
  if (!fixed.length && !fmtOnly) { note_(ctx, '変換対象の日付は見つかりませんでした（' + rg.getA1Notation() + '）'); return; }
  rg.setNumberFormats(fmts);
  if (fixed.length) rg.setValues(vals);
  chg_(ctx, sh, fixed.length ? (fixed.slice(0, 5).join('・') + (fixed.length > 5 ? ' ほか ' + (fixed.length - 5) + ' 件' : '')) : rg.getA1Notation(),
    '日付を変換・統一（変換 ' + fixed.length + ' 件' + (fmtOnly ? '・書式統一 ' + fmtOnly + ' 件' : '') + '）');
};

// 棚: phone.fix
// 題: 電話番号をハイフン区切りにそろえる
// 分類: 整える
// 語: 電話番号|携帯番号|ハイフン区切り|ハイフン付き|ハイフンで区切|ハイフンを入れ|電話の形式|番号をハイフン
// 違い: 0埋めなら zero.pad、日付の統一なら date.fix、一般的な文字掃除なら seiri
// 引数: col=列, range=範囲
// どれか: col range
// 例: 「電話番号をハイフン区切りにそろえて」 → {"shelf":"phone.fix","col":"電話番号"}
// 例: 「携帯番号をハイフン付きの書式に揃えて」 → {"shelf":"phone.fix","col":"携帯番号"}
// 触る: 値 書式
// 控え: 今
SHELF['phone.fix'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg, t = null;
  if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「phone.fix」に col か range が要ります');
  var vals = rg.getValues(), forms = rg.getFormulas(), fmts = rg.getNumberFormats();
  var startR = rg.getRow(), startC = rg.getColumn();
  var fmtPhone = function (raw) {
    var s;
    if (typeof raw === 'number' && isFinite(raw) && Math.floor(raw) === raw && raw > 0) {
      s = String(raw);
      if (s.length === 9 || s.length === 10) s = '0' + s;
    } else if (typeof raw === 'string') {
      s = raw.trim();
    } else {
      return null;
    }
    if (!s) return null;
    var h = s
      .replace(/[０-９]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); })
      .replace(/[－ー―‐−]/g, '-')
      .replace(/[（]/g, '(').replace(/[）]/g, ')')
      .replace(/　/g, ' ');
    var digits = h.replace(/[^\d]/g, '');
    if (digits.length < 10 || digits.length > 11 || digits.charAt(0) !== '0') return null;
    if (digits.length === 11) {
      if (/^0800/.test(digits)) return digits.slice(0, 4) + '-' + digits.slice(4, 7) + '-' + digits.slice(7);
      return digits.slice(0, 3) + '-' + digits.slice(3, 7) + '-' + digits.slice(7);
    }
    if (/^0120/.test(digits)) return digits.slice(0, 4) + '-' + digits.slice(4, 7) + '-' + digits.slice(7);
    if (/^0[36]/.test(digits)) return digits.slice(0, 2) + '-' + digits.slice(2, 6) + '-' + digits.slice(6);
    var grp = h.replace(/[()]/g, ' ').trim().split(/[\s\-]+/).filter(function (x) { return /^\d+$/.test(x); });
    if (grp.length === 3 && grp.join('') === digits && grp[0].length >= 2 && grp[0].length <= 5 && grp[2].length === 4) {
      return grp.join('-');
    }
    return digits.slice(0, 3) + '-' + digits.slice(3, 6) + '-' + digits.slice(6);
  };
  var fixed = [];
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    if (forms[r][c]) continue;
    var formatted = fmtPhone(vals[r][c]);
    if (!formatted) continue;
    if (String(vals[r][c]) !== formatted || fmts[r][c] !== '@') {
      vals[r][c] = formatted;
      fmts[r][c] = '@';
      fixed.push(a1_(startR + r, startC + c));
    }
  }
  if (!fixed.length) { note_(ctx, '整形対象の電話番号は見つかりませんでした（' + rg.getA1Notation() + '）'); return; }
  rg.setNumberFormats(fmts);
  rg.setValues(vals);
  chg_(ctx, sh, fixed.slice(0, 5).join('・') + (fixed.length > 5 ? ' ほか ' + (fixed.length - 5) + ' 件' : ''), '電話番号をハイフン区切りに統一（' + fixed.length + ' 件）');
};

// 棚: fill.date
// 題: 日付を下へ埋める
// 分類: 範囲
// 語: 日付を埋|日付を連続|日付を下まで|毎日の日付|1日ずつ|平日だけ|カレンダー
// 違い: 数字の連番なら fill.series、上のセルをそのまま写すなら fill.down
// 引数: range*=範囲, start=文字, unit=選択(day/week/month/weekday)=day
// 例: 「A2からA31まで5月の日付を埋めて」 → {"shelf":"fill.date","range":"A2:A31","start":"2026-05-01"}
// 例: 「毎週月曜の日付を下に連続で入れて」 → {"shelf":"fill.date","range":"B2:B10","start":"2026-05-04","unit":"week"}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['fill.date'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  guardOverwrite_(ctx, rg, '範囲「' + op.range + '」に日付を記入');
  var unit = op.unit || 'day';
  var dt;
  if (op.start) {
    var sDt = String(op.start).trim();
    var zDt = sDt.replace(/[０-９]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); });
    var md = /^(\d{4})[\/\-\.年](\d{1,2})[\/\-\.月](\d{1,2})日?$/.exec(zDt);
    if (md) {
      var yy = parseInt(md[1], 10), mm = parseInt(md[2], 10), dd = parseInt(md[3], 10);
      var tmpDt = new Date(yy, mm - 1, dd);
      dt = (tmpDt.getFullYear() === yy && tmpDt.getMonth() === mm - 1 && tmpDt.getDate() === dd) ? tmpDt : new Date(NaN);
    } else {
      dt = (typeof parseDateText_ === 'function' ? parseDateText_(zDt) : null) || new Date(op.start);
    }
    if (!dt || isNaN(dt.getTime())) throw new ArgError('開始日付が読めません: ' + op.start);
  } else {
    var v = rg.getCell(1, 1).getValue();
    dt = (v instanceof Date && !isNaN(v.getTime())) ? new Date(v.getTime()) : new Date();
  }
  var nr = rg.getNumRows(), nc = rg.getNumColumns();
  var vals = [];
  var baseY = dt.getFullYear(), baseM = dt.getMonth(), baseDay = dt.getDate();
  var cur = new Date(dt.getTime());
  var stepIdx = 0;
  var stepFn = function (d, u, idx) {
    if (u === 'month') {
      var tgtFirst = new Date(baseY, baseM + idx + 1, 1);
      var lastDay = new Date(tgtFirst.getFullYear(), tgtFirst.getMonth() + 1, 0).getDate();
      return new Date(tgtFirst.getFullYear(), tgtFirst.getMonth(), Math.min(baseDay, lastDay));
    }
    var next = new Date(d.getTime());
    if (u === 'day') next.setDate(next.getDate() + 1);
    else if (u === 'week') next.setDate(next.getDate() + 7);
    else if (u === 'weekday') {
      do { next.setDate(next.getDate() + 1); } while (next.getDay() === 0 || next.getDay() === 6);
    }
    return next;
  };
  for (var r = 0; r < nr; r++) {
    var row = [];
    for (var c = 0; c < nc; c++) {
      row.push(new Date(cur.getTime()));
      cur = stepFn(cur, unit, stepIdx++);
    }
    vals.push(row);
  }
  rg.setValues(vals);
  rg.setNumberFormat(STYLE.dateFmt);
  chg_(ctx, sh, rg.getA1Notation(), '日付を記入（unit: ' + unit + '）');
};

// 棚: fill.down
// 題: 上のセルを下へ写す
// 分類: 範囲
// 語: 下まで写|下までコピー|式を下まで|下にコピー|オートフィル|下へ伸ば|下方向にコピー|下に写して|下まで写して
// 違い: 連番にするなら fill.series、日付なら fill.date
// 引数: range*=範囲
// 例: 「C2の計算式をC2:C50まで下へコピーして」 → {"shelf":"fill.down","range":"C2:C50"}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['fill.down'] = function (ctx, op) {
  need_(op, ['range']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  if (rg.getNumRows() <= 1) throw new ArgError('棚「fill.down」の範囲は2行以上要ります');
  var firstRow = rg.offset(0, 0, 1, rg.getNumColumns());
  var dest = rg.offset(1, 0, rg.getNumRows() - 1, rg.getNumColumns());
  guardOverwrite_(ctx, dest, 'コピー先「' + dest.getA1Notation() + '」');
  firstRow.copyTo(dest);
  chg_(ctx, sh, dest.getA1Notation(), '上のセルを下へ複写');
};

// 棚: note.set
// 題: セルにメモを付ける
// 分類: 範囲
// 語: メモを付|メモをつ|メモを入|メモを書|メモを追加|コメントを付|注釈を付|セルにメモ
// 違い: メモを消すなら note.clear
// 引数: range*=範囲, text*=文字
// 頼み: text~[『「]([^』」]+)[』」](?:と|って)?メモ ; text~メモ[をに][『「]([^』」]+)[』」]
// 例: 「B5に「確認済み」とメモを付けて」 → {"shelf":"note.set","range":"B5","text":"確認済み"}
// 触る: 書式
// 控え: 今
SHELF['note.set'] = function (ctx, op) {
  need_(op, ['range', 'text']);
  var sh = sheetCtx_(ctx, op);
  var rg = sh.getRange(op.range);
  rg.setNote(String(op.text));
  chg_(ctx, sh, rg.getA1Notation(), 'メモを設定: 「' + String(op.text).slice(0, 40) + '」');
};

// 棚: note.clear
// 題: セルのメモを消す
// 分類: 範囲
// 語: メモを消|メモを削除|メモをクリア|メモを外|メモを取|全メモを消
// 違い: メモを付けるなら note.set
// 引数: range=範囲
// 例: 「B5のメモを消して」 → {"shelf":"note.clear","range":"B5"}
// 例: 「このシートのメモを全部消して」 → {"shelf":"note.clear"}
// 触る: 書式
// 控え: 今
SHELF['note.clear'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var rg = op.range ? sh.getRange(op.range) : sh.getDataRange();
  rg.clearNote();
  chg_(ctx, sh, rg.getA1Notation(), 'メモを消去');
};

// 棚: link.set
// 題: セルや列にリンクを付ける
// 分類: 範囲
// 語: リンクを貼|リンクを付|リンクを設定|ハイパーリンク|URLをリンク|クリックで飛べる|リンクにして
// 違い: 文書中の言葉にリンクを付けるなら doc.link
// 引数: range=範囲, url=文字, text=文字, col=列, url_col=列
// どれか: range col
// 例: 「A2に公式サイトへのリンクを貼って」 → {"shelf":"link.set","range":"A2","url":"https://example.com","text":"公式サイト"}
// 例: 「会社名列にURL列のリンクを一括で貼って」 → {"shelf":"link.set","col":"会社名","url_col":"URL"}
// 触る: 値 書式
// 控え: 今
SHELF['link.set'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  if (op.col) {
    need_(op, ['url_col']);
    var t = needTable_(sh);
    var ci = colIndexOf_(t, op.col);
    var uci = colIndexOf_(t, op.url_col);
    var nr = t.lastData - t.firstData + 1;
    if (nr < 1) throw new ArgError('リンクを設定するデータ行がありません');
    var labelVals = sh.getRange(t.firstData, ci, nr, 1).getDisplayValues();
    var urlVals = sh.getRange(t.firstData, uci, nr, 1).getDisplayValues();
    var linkUpdates = [];
    for (var i = 0; i < nr; i++) {
      var lbl = String(labelVals[i][0] || '');
      var u = String(urlVals[i][0] || '').trim();
      if (u && /^https?:\/\//i.test(u)) {
        linkUpdates.push({ r: i, rtv: SpreadsheetApp.newRichTextValue().setText(lbl || u).setLinkUrl(u).build() });
      }
    }
    for (var ui = 0; ui < linkUpdates.length; ) {
      var rs = linkUpdates[ui].r, re = rs, block = [[linkUpdates[ui].rtv]];
      while (ui + 1 < linkUpdates.length && linkUpdates[ui + 1].r === re + 1) {
        ui++;
        re = linkUpdates[ui].r;
        block.push([linkUpdates[ui].rtv]);
      }
      sh.getRange(t.firstData + rs, ci, re - rs + 1, 1).setRichTextValues(block);
      ui++;
    }
    chg_(ctx, sh, a1_(t.firstData, ci, nr, 1), op.col + '列にハイパーリンクを設定（' + linkUpdates.length + ' 件）');
    return;
  }
  need_(op, ['range', 'url']);
  var rg = sh.getRange(op.range);
  var url = String(op.url).trim();
  var label = op.text !== undefined && op.text !== '' ? String(op.text) : (rg.getDisplayValue() || url);
  var rtv = SpreadsheetApp.newRichTextValue().setText(label).setLinkUrl(url).build();
  rg.setRichTextValue(rtv);
  chg_(ctx, sh, rg.getA1Notation(), 'ハイパーリンクを設定（' + url + '）');
};

// 棚: merge.unmerge
// 題: 結合セルを解除して値を埋める
// 分類: 整える
// 語: 結合を解除して埋め|結合解除して埋め|結合セルを解除して埋め|結合セルをほどいて|結合をばらし|結合を分解|結合解除して値を埋め|結合を解除して値を埋め|結合セルを解除して値を|セル結合をほどく|結合解除 値埋め|値埋め
// 違い: 値を埋めずに結合を解除するだけなら format（merge=false）
// 引数: range=範囲
// 例: 「結合セルを解除して値を埋めて」 → {"shelf":"merge.unmerge"}
// 触る: 値 書式
// 控え: 今
SHELF['merge.unmerge'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var rg = op.range ? sh.getRange(op.range) : sh.getDataRange();
  var merged = rg.getMergedRanges();
  if (!merged || !merged.length) {
    note_(ctx, '結合セルはありませんでした（変更なし）');
    return;
  }
  var minR = rg.getRow(), minC = rg.getColumn();
  var maxR = minR + rg.getNumRows() - 1, maxC = minC + rg.getNumColumns() - 1;
  var spans = [];
  merged.forEach(function (mr) {
    var mrR = mr.getRow(), mrC = mr.getColumn(), mrNr = mr.getNumRows(), mrNc = mr.getNumColumns();
    if (mrR < minR) minR = mrR;
    if (mrC < minC) minC = mrC;
    if (mrR + mrNr - 1 > maxR) maxR = mrR + mrNr - 1;
    if (mrC + mrNc - 1 > maxC) maxC = mrC + mrNc - 1;
    spans.push({ r: mrR, c: mrC, nr: mrNr, nc: mrNc });
  });
  var workRg = (minR === rg.getRow() && minC === rg.getColumn() && maxR === rg.getRow() + rg.getNumRows() - 1 && maxC === rg.getColumn() + rg.getNumColumns() - 1)
    ? rg : sh.getRange(minR, minC, maxR - minR + 1, maxC - minC + 1);
  var vals = workRg.getValues(), forms = workRg.getFormulas();
  for (var ri = 0; ri < vals.length; ri++) {
    for (var ci = 0; ci < vals[ri].length; ci++) {
      if (forms[ri][ci]) vals[ri][ci] = forms[ri][ci];
    }
  }
  spans.forEach(function (sp) {
    var relR = sp.r - minR, relC = sp.c - minC;
    var topVal = vals[relR][relC];
    if (!isBlank_(topVal)) {
      for (var rr = relR; rr < relR + sp.nr; rr++) {
        for (var cc = relC; cc < relC + sp.nc; cc++) {
          vals[rr][cc] = topVal;
        }
      }
    }
  });
  workRg.breakApart();
  workRg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '結合セル ' + spans.length + ' か所を解除して値を充填');
};

// 棚: fill.blank
// 題: 空白セルを上の値で穴埋めする
// 分類: 整える
// 語: 空白セルを上の値|空欄を上の値|空白を上の値|上の値で穴埋|上の値で埋|穴埋め|空欄を埋|空白を埋|ブランクを埋
// 違い: 計算式を下までコピーするなら fill.down、結合解除して埋めるなら merge.unmerge
// 引数: range=範囲, col=列
// 例: 「空白セルを上の値で穴埋めして」 → {"shelf":"fill.blank"}
// 例: 「A列の空欄を上の値で埋めて」 → {"shelf":"fill.blank","col":"A"}
// 触る: 値
// 控え: 今
SHELF['fill.blank'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    var t2 = needTable_(sh);
    rg = dataRange_(t2);
  }
  var vals = rg.getValues(), forms = rg.getFormulas();
  var nr = vals.length, nc = nr ? vals[0].length : 0, filled = 0;
  for (var c = 0; c < nc; c++) {
    var hasLast = false, lastVal = '';
    for (var r = 0; r < nr; r++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) {
        vals[r][c] = f;
        hasLast = true;
        lastVal = v;
      } else if (!isBlank_(v)) {
        hasLast = true;
        lastVal = v;
      } else if (hasLast) {
        vals[r][c] = lastVal;
        filled++;
      }
    }
  }
  if (!filled) {
    note_(ctx, '埋める空白セルはありませんでした（変更なし）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '空白 ' + filled + ' セルを上の値で穴埋め');
};

// 棚: transpose
// 題: 行と列を入れ替える（転置）
// 分類: 範囲
// 語: 行と列を入れ替|縦横を入れ替|転置|縦と横を逆|行列を入れ替|横向きを縦向き|縦向きを横向き
// 違い: 行や列の順序移動なら rows.move / cols.move
// 引数: range=範囲, to=範囲, into=文字
// 例: 「A1:D5の行と列を入れ替えてF1に貼って」 → {"shelf":"transpose","range":"A1:D5","to":"F1"}
// 例: 「この表を転置して別シートに出して」 → {"shelf":"transpose","into":"転置"}
// 危ない: 上書き
// 触る: 値 シート構成
// 控え: 今,先
SHELF['transpose'] = function (ctx, op) {
  var ss = ctx.ss, sh = sheetCtx_(ctx, op), srcRg;
  if (op.range) {
    srcRg = op.range.indexOf('!') >= 0 ? ss.getRange(op.range) : sh.getRange(op.range);
  } else {
    var t = findTable_(sh);
    srcRg = t
      ? sh.getRange(t.headerRow, t.firstCol, (t.totalRow || t.lastData) - t.headerRow + 1, t.lastCol - t.firstCol + 1)
      : sh.getDataRange();
  }
  var vals = srcRg.getValues();
  var nr = vals.length, nc = nr ? vals[0].length : 0;
  if (!nr || !nc) throw new ArgError('転置する元データがありません');
  var out = [];
  for (var c = 0; c < nc; c++) {
    var row = [];
    for (var r = 0; r < nr; r++) row.push(vals[r][c]);
    out.push(row);
  }
  if (op.to) {
    var dBase = op.to.indexOf('!') >= 0 ? ss.getRange(op.to) : sh.getRange(op.to);
    var destSh = dBase.getSheet();
    var destRg = destSh.getRange(dBase.getRow(), dBase.getColumn(), out.length, out[0].length);
    guardOverwrite_(ctx, destRg, '転置先「' + destRg.getA1Notation() + '」');
    destRg.setValues(out);
    chg_(ctx, destSh, destRg.getA1Notation(), srcRg.getA1Notation() + ' を転置（' + out.length + '行×' + out[0].length + '列）');
    return;
  }
  var intoName = String(op.into || '転置').trim();
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    var chkRg = dst.getRange(1, 1, out.length, out[0].length);
    guardOverwrite_(ctx, chkRg, '転置先シート「' + intoName + '」');
    dst.clearContents();
  }
  var outRg = dst.getRange(1, 1, out.length, out[0].length);
  outRg.setValues(out);
  ctx.curSheet = intoName;
  chg_(ctx, dst, outRg.getA1Notation(), srcRg.getA1Notation() + ' を転置（' + out.length + '行×' + out[0].length + '列）');
};

// 棚: number.fix
// 題: 文字の数字を本物の数値に直す
// 分類: 整える
// 語: 文字の数字を数値|文字列の数字を数値|文字列を数値に直|数値に変換|本物の数値|数字の文字列を数値|文字になってる数字|テキストの数字を数値
// 違い: 空白・全角・体裁まで全部整えるなら seiri、日付文字列を直すなら date.fix
// 引数: col=列, range=範囲
// 例: 「金額列の文字の数字を本物の数値に直して」 → {"shelf":"number.fix","col":"金額"}
// 触る: 値
// 控え: 今
SHELF['number.fix'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    var t2 = needTable_(sh);
    rg = dataRange_(t2);
  }
  var vals = rg.getValues(), forms = rg.getFormulas(), count = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) { vals[r][c] = f; continue; }
      if (typeof v !== 'string') continue;
      var hw = v.replace(/[０-９＋－．，]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); })
        .replace(/　/g, ' ').trim();
      var cleaned = hw.replace(/^[¥￥$]+\s*/, '').replace(/\s*円$/, '').replace(/,/g, '');
      if (!cleaned) continue;
      if (/^-?\d+(\.\d+)?$/.test(cleaned) && !/^-?0\d/.test(cleaned)) {
        vals[r][c] = Number(cleaned);
        count++;
      }
    }
  }
  if (!count) {
    note_(ctx, '変換対象の文字列数字は見つかりませんでした（変更なし）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '文字の数字を数値に変換（' + count + ' 件）');
};

// 棚: link.clear
// 題: セルのハイパーリンクを外す
// 分類: 範囲
// 語: リンクを外|リンクを解除|リンクを消|リンクを削除|ハイパーリンクを外|ハイパーリンクを解除|ハイパーリンクを消|リンクだけ外
// 違い: リンクを付けるなら link.set、URLを取り出すなら link.extract
// 引数: range=範囲, col=列
// 例: 「A列のハイパーリンクを外して」 → {"shelf":"link.clear","col":"A"}
// 触る: 値 書式
// 控え: 今
SHELF['link.clear'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = sh.getDataRange();
  }
  var rich = rg.getRichTextValues(), forms = rg.getFormulas(), vals = rg.getValues();
  var disp = null, r0 = rg.getRow(), c0 = rg.getColumn(), cleared = 0;
  var hasFormulaLink = false, hasRichLink = false, hasOtherFormulaOrNonString = false;
  var richUpdates = [];
  for (var r = 0; r < rich.length; r++) {
    for (var c = 0; c < rich[r].length; c++) {
      var f = forms[r][c];
      if (f) {
        if (/^=HYPERLINK\(/i.test(f)) {
          if (!disp) disp = rg.getDisplayValues();
          vals[r][c] = disp[r][c];
          hasFormulaLink = true;
          cleared++;
        } else {
          vals[r][c] = f;
          hasOtherFormulaOrNonString = true;
        }
        continue;
      }
      var v = vals[r][c];
      if (v !== '' && v !== null && v !== undefined && typeof v !== 'string') {
        hasOtherFormulaOrNonString = true;
      }
      var rtv = rich[r][c];
      if (!rtv) continue;
      var hasLink = !!rtv.getLinkUrl();
      if (!hasLink && typeof rtv.getRuns === 'function') {
        hasLink = rtv.getRuns().some(function (run) { return !!run.getLinkUrl(); });
      }
      if (hasLink) {
        var cleanRtv = SpreadsheetApp.newRichTextValue().setText(rtv.getText()).build();
        rich[r][c] = cleanRtv;
        richUpdates.push({ r: r, c: c, rtv: cleanRtv });
        hasRichLink = true;
        cleared++;
      }
    }
  }
  if (!cleared) {
    note_(ctx, 'ハイパーリンクは見つかりませんでした（変更なし）');
    return;
  }
  if (hasFormulaLink) rg.setValues(vals);
  if (hasRichLink) {
    if (!hasOtherFormulaOrNonString && !hasFormulaLink && typeof rg.setRichTextValues === 'function') {
      rg.setRichTextValues(rich);
    } else {
      richUpdates.sort(function (a, b) { return (a.c - b.c) || (a.r - b.r); });
      for (var ui = 0; ui < richUpdates.length; ) {
        var col = richUpdates[ui].c, rs = richUpdates[ui].r, re = rs;
        var block = [[richUpdates[ui].rtv]];
        while (ui + 1 < richUpdates.length && richUpdates[ui + 1].c === col && richUpdates[ui + 1].r === re + 1) {
          ui++;
          re = richUpdates[ui].r;
          block.push([richUpdates[ui].rtv]);
        }
        sh.getRange(r0 + rs, c0 + col, re - rs + 1, 1).setRichTextValues(block);
        ui++;
      }
    }
  }
  chg_(ctx, sh, rg.getA1Notation(), 'ハイパーリンクを解除（' + cleared + ' 件）');
};

// 棚: link.extract
// 題: 埋め込みリンクのURLを隣列へ抽出
// 分類: 範囲
// 語: リンクのURLを抽出|URLを抽出|リンク先を抽出|URLを取り出|リンクのURLを取り出|埋め込みリンクを抽出|URL列を作|URLを隣列
// 違い: リンクを貼るなら link.set、リンクを消すなら link.clear
// 引数: col*=列, name=文字=URL
// 頼み: col~([^\sの、。]+?)(?:列)?の(?:埋め込みリンク|リンク|URL).*(?:抽出|取り出|URL)
// 例: 「会社名列の埋め込みリンクのURLを隣列へ抽出して」 → {"shelf":"link.extract","col":"会社名"}
// 触る: 値
// 控え: 今
SHELF['link.extract'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = colIndexOf_(t, op.col);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  sh.insertColumnAfter(ci);
  var headName = op.name || 'URL';
  var dstHead = sh.getRange(t.headerRow, ci + 1);
  sh.getRange(t.headerRow, ci).copyTo(dstHead, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
  dstHead.setValue(headName).setHorizontalAlignment('center');
  var extracted = 0;
  if (nr > 0) {
    var srcRg = sh.getRange(t.firstData, ci, nr, 1);
    var rich = srcRg.getRichTextValues(), forms = srcRg.getFormulas(), out = [];
    for (var i = 0; i < nr; i++) {
      var u = '';
      var rtv = rich[i][0];
      if (rtv) {
        u = rtv.getLinkUrl() || '';
        if (!u && typeof rtv.getRuns === 'function') {
          var runs = rtv.getRuns();
          for (var ri = 0; ri < runs.length; ri++) {
            var ru = runs[ri].getLinkUrl();
            if (ru) { u = ru; break; }
          }
        }
      }
      if (!u && forms[i][0]) {
        var hm = String(forms[i][0]).match(/^=HYPERLINK\(\s*"([^"]+)"/i);
        if (hm) u = hm[1];
      }
      if (u) extracted++;
      out.push([u]);
    }
    sh.getRange(t.firstData, ci + 1, nr, 1).setValues(out);
  }
  chg_(ctx, sh, colLetter_(ci + 1) + '列', 'リンクURL「' + headName + '」を隣列へ抽出（' + extracted + ' 件）');
};

// 棚: note.list
// 題: セルのメモ一覧を別シートに出す
// 分類: 範囲
// 語: メモ一覧|メモを一覧|メモをまとめ|コメント一覧|注釈一覧|全メモを一覧|メモを一覧シート|メモを書き出
// 違い: メモを付けるなら note.set、消すなら note.clear
// 引数: all_sheets=真偽=false, into=文字=メモ一覧
// 頼み: all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体
// 例: 「シート内のメモ一覧を別シートに出して」 → {"shelf":"note.list"}
// 触る: シート構成 値
// 控え: 先
SHELF['note.list'] = function (ctx, op) {
  var ss = ctx.ss, intoName = String(op.into || 'メモ一覧').trim();
  var targets = op.all_sheets
    ? ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え' && s.getName() !== intoName; })
    : [sheetCtx_(ctx, op)];
  var rowsOut = [];
  targets.forEach(function (s) {
    var lr = s.getLastRow(), lc = s.getLastColumn();
    if (lr < 1 || lc < 1) return;
    var rg = s.getRange(1, 1, lr, lc);
    var notes = rg.getNotes(), disp = rg.getDisplayValues();
    for (var r = 0; r < notes.length; r++) {
      for (var c = 0; c < notes[r].length; c++) {
        var nt = String(notes[r][c] || '').trim();
        if (nt) rowsOut.push([s.getName(), a1_(r + 1, c + 1), disp[r][c], nt]);
      }
    }
  });
  if (!rowsOut.length) {
    note_(ctx, 'メモは見つかりませんでした（作成していません）');
    return;
  }
  var dst = ss.getSheetByName(intoName);
  if (!dst) {
    dst = ss.insertSheet(intoName, ss.getSheets().length);
    ctx.createdSheets.push(intoName);
  } else {
    dst.clearContents();
  }
  var out = [['シート', 'セル', 'セルの値', 'メモ']].concat(rowsOut);
  dst.getRange(1, 1, out.length, 4).setValues(out);
  dst.getRange(1, 1, 1, 4).setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setFontWeight('bold');
  ctx.curSheet = intoName;
  chg_(ctx, dst, a1_(1, 1, out.length, 4), 'メモ一覧を作成（' + rowsOut.length + ' 件）');
};

// 棚: blank.fill.zero
// 題: 空欄セルを0や指定文字で一括埋めする
// 分類: 整える
// 語: 空欄を0|空白を0|空欄に0|空白セルを0|未入力を埋め|空欄を埋め|ブランクに0|空欄へ0
// 違い: 上のセルの値で埋めるなら fill.blank、桁ぞろえ0埋めなら zero.pad
// 引数: col=列, range=範囲, value=文字=0
// 例: 「数量列の空欄を0で埋めて」 → {"shelf":"blank.fill.zero","col":"数量","value":"0"}
// 触る: 値
// 控え: 今
SHELF['blank.fill.zero'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = dataRange_(needTable_(sh));
  }
  var fillVal = op.value !== undefined ? op.value : 0;
  if (typeof fillVal === 'string') {
    var trimmed = fillVal.trim();
    if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(trimmed)) fillVal = Number(trimmed);
  }
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      if (forms[r][c]) { vals[r][c] = forms[r][c]; continue; }
      if (isBlank_(vals[r][c])) {
        vals[r][c] = fillVal;
        changed++;
      }
    }
  }
  if (!changed) {
    note_(ctx, '埋める空欄セルはありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '空欄 ' + changed + ' セルを「' + fillVal + '」で補充');
};

// 棚: text.mask
// 題: 個人情報や文字を伏せ字にマスキングする
// 分類: 整える
// 語: 伏せ字|伏字|マスキング|マスク処理|個人情報を隠|文字の一部を隠|アスタリスクで隠|文字を隠して
// 違い: 行ごと隠すなら rows.hide、置換するなら replace
// 引数: col=列, range=範囲, keep_head=数=1, keep_tail=数=0, mask=文字=*
// 例: 「氏名列を先頭1文字だけ残して伏せ字にして」 → {"shelf":"text.mask","col":"氏名","keep_head":1}
// 危ない: 上書き
// 触る: 値
// 控え: 今
SHELF['text.mask'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = dataRange_(needTable_(sh));
  }
  guardOverwrite_(ctx, rg, '範囲「' + rg.getA1Notation() + '」を伏せ字にマスキング');
  var kh = op.keep_head !== undefined ? Math.max(0, parseInt(op.keep_head, 10) || 0) : 1;
  var kt = op.keep_tail !== undefined ? Math.max(0, parseInt(op.keep_tail, 10) || 0) : 0;
  var mkChar = String(op.mask !== undefined ? op.mask : '*').charAt(0) || '*';
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      if (forms[r][c]) { vals[r][c] = forms[r][c]; continue; }
      if (isBlank_(vals[r][c])) continue;
      var s = String(vals[r][c]);
      var masked = '';
      if (s.indexOf('@') > 0 && kt === 0) {
        var atIdx = s.indexOf('@');
        var local = s.slice(0, atIdx), dom = s.slice(atIdx);
        var lh = Math.min(kh, Math.max(0, local.length - 1));
        masked = local.slice(0, lh) + Array(Math.max(3, local.length - lh) + 1).join(mkChar) + dom;
      } else {
        var hUse = Math.min(kh, Math.max(0, s.length - 1));
        var tUse = Math.min(kt, Math.max(0, s.length - hUse - 1));
        var midLen = Math.max(2, s.length - hUse - tUse);
        masked = s.slice(0, hUse) + Array(midLen + 1).join(mkChar) + (tUse > 0 ? s.slice(s.length - tUse) : '');
      }
      if (masked !== s) {
        vals[r][c] = masked;
        changed++;
      }
    }
  }
  if (!changed) {
    note_(ctx, '伏せ字にするセルはありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), '伏せ字マスキング（' + changed + ' 件）');
};

// 棚: text.extract
// 題: 文字からメール・URL・数字・括弧内を抽出する
// 分類: 整える
// 語: 文字から抽出|メールを抽出|数字だけ抽出|括弧内を抽出|正規表現で抽出|テキスト抽出|文字を抜き出|括弧の中身を抜き|を隣の列へ抽出|メールアドレスを抽出
// 違い: 埋め込みハイパーリンクのURLなら link.extract。区切り文字で分けるなら split.col
// 引数: col*=列, kind*=選択(email/url/number/parens/regex)=number, pattern=文字, name=文字
// 頼み: kind=email<メール ; kind=url<URL|リンク ; kind=parens<括弧|カッコ ; kind=number<数字|数値
// 例: 「備考列からメールアドレスを隣の列へ抽出して」 → {"shelf":"text.extract","col":"備考","kind":"email"}
// 触る: 値 書式
// 控え: 今
SHELF['text.extract'] = function (ctx, op) {
  need_(op, ['col', 'kind']);
  var kind = String(op.kind || 'number').toLowerCase();
  var rx;
  if (kind === 'email') rx = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/;
  else if (kind === 'url') rx = /https?:\/\/[^\s　「」『』()（）]+/;
  else if (kind === 'number') rx = /-?\d+(?:,\d{3})*(?:\.\d+)?/;
  else if (kind === 'parens') rx = /[（(「【『]([^）)」】』]+)[）)」】』]/;
  else if (kind === 'regex') {
    if (!op.pattern) throw new ArgError('kind="regex" のときは pattern が要ります');
    try { rx = new RegExp(String(op.pattern)); }
    catch (eRx) { throw new ArgError('正規表現 pattern が不正です: ' + String(eRx && eRx.message || eRx)); }
  } else {
    throw new ArgError('棚「text.extract」の kind が不正です: ' + kind);
  }
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  sh.insertColumnAfter(ci);
  var defNames = { email: 'メール', url: 'URL', number: '数値', parens: '括弧内', regex: '抽出' };
  var headName = op.name || defNames[kind] || '抽出';
  var dstHead = sh.getRange(t.headerRow, ci + 1);
  sh.getRange(t.headerRow, ci).copyTo(dstHead, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
  dstHead.setValue(headName).setHorizontalAlignment('center');
  var hits = 0;
  if (nr > 0) {
    var srcVals = sh.getRange(t.firstData, ci, nr, 1).getDisplayValues();
    var out = [];
    for (var i = 0; i < nr; i++) {
      var m = rx.exec(String(srcVals[i][0] || ''));
      var picked = m ? (m[1] !== undefined ? m[1] : m[0]) : '';
      if (picked !== '') hits++;
      out.push([picked]);
    }
    sh.getRange(t.firstData, ci + 1, nr, 1).setValues(out);
  }
  chg_(ctx, sh, colLetter_(ci + 1) + '列', '「' + headName + '」を隣列へ抽出（' + hits + ' 件）');
};

// 棚: rows.reverse
// 題: 表のデータ行を上下反転する（逆順にする）
// 分類: 範囲
// 語: 上下反転|逆順に並べ|行を逆順|順番を反転|行を反転|下から上|逆さにする|最新を上に
// 違い: 特定の列の昇順・降順ソートは sort。縦横入れ替えは transpose
// 引数: なし
// 例: 「表のデータ行を上下逆順にして」 → {"shelf":"rows.reverse"}
// 触る: 値
// 控え: 今
SHELF['rows.reverse'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var nr = t.lastData - t.firstData + 1;
  if (nr <= 1) {
    note_(ctx, '反転するデータ行が 2 行未満です（変更なし）');
    return;
  }
  var nc = t.lastCol - t.firstCol + 1;
  var dr = sh.getRange(t.firstData, t.firstCol, nr, nc);
  var vals = dr.getValues(), forms = dr.getFormulas(), rev = [];
  for (var i = 0; i < nr; i++) {
    var srcIdx = nr - 1 - i;
    var delta = i - srcIdx;
    var rowOut = [];
    for (var c = 0; c < nc; c++) {
      var f = forms[srcIdx][c];
      rowOut.push(f ? shiftFormula_(f, delta) : vals[srcIdx][c]);
    }
    rev.push(rowOut);
  }
  dr.setValues(rev);
  chg_(ctx, sh, dr.getA1Notation(), 'データ ' + nr + ' 行を上下反転');
};

// 棚: date.today
// 題: セルに今日の日付や現在時刻を入れる
// 分類: 範囲
// 語: 今日の日付|現在時刻|本日の日付|タイムスタンプ|今日を入れ|今の日時|日付を打つ|日時を入力
// 違い: 連続した日付を埋めるなら fill.date。文字の日付を直すなら date.fix
// 引数: range=範囲, with_time=真偽=false
// 頼み: with_time=true<時刻|日時|タイムスタンプ|今の日時|現在時刻 ; range~([A-Z]{1,3}[0-9]+(?::[A-Z]{1,3}[0-9]+)?)に.*?(?:今日|本日|現在|日付|時刻)
// 例: 「A1に今日の日付を入れて」 → {"shelf":"date.today","range":"A1"}
// 触る: 値 書式
// 控え: 今
SHELF['date.today'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var rg = op.range ? sh.getRange(op.range) : ((typeof sh.getActiveRange === 'function' && sh.getActiveRange()) || sh.getRange('A1'));
  var nr = rg.getNumRows(), nc = rg.getNumColumns();
  var now = new Date(), vals = [];
  for (var r = 0; r < nr; r++) {
    var row = [];
    for (var c = 0; c < nc; c++) row.push(new Date(now.getTime()));
    vals.push(row);
  }
  rg.setValues(vals);
  rg.setNumberFormat(op.with_time ? 'yyyy/mm/dd hh:mm' : STYLE.dateFmt);
  chg_(ctx, sh, rg.getA1Notation(), (op.with_time ? '現在日時' : '今日の日付') + 'を入力');
};

// 棚: text.kana
// 題: ひらがなとカタカナを一括変換する
// 分類: 整える
// 語: カタカナに変換|ひらがなに変換|カタカナに統一|ひらがなに統一|フリガナを統一|かな変換|カナ変換|ひらカナ変換
// 違い: 大文字・小文字や全角・半角の変換は text.case
// 引数: col=列, range=範囲, to=選択(kata/hira)=kata
// 頼み: to=hira<ひらがな|平仮名 ; to=kata<カタカナ|片仮名
// 例: 「フリガナ列をカタカナに統一して」 → {"shelf":"text.kana","col":"フリガナ","to":"kata"}
// 触る: 値
// 控え: 今
SHELF['text.kana'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg;
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    rg = sh.getRange(t.firstData, ci, Math.max(1, t.lastData - t.firstData + 1), 1);
  } else if (op.range) {
    rg = sh.getRange(op.range);
  } else {
    rg = dataRange_(needTable_(sh));
  }
  var toHira = String(op.to || 'kata').toLowerCase() === 'hira';
  var vals = rg.getValues(), forms = rg.getFormulas(), changed = 0;
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var f = forms[r][c], v = vals[r][c];
      if (f) { vals[r][c] = f; continue; }
      if (typeof v !== 'string' || !v) continue;
      var conv = toHira
        ? v.replace(/[\u30a1-\u30f6]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0x60); })
        : v.replace(/[\u3041-\u3096]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) + 0x60); });
      if (conv !== v) {
        vals[r][c] = conv;
        changed++;
      }
    }
  }
  if (!changed) {
    note_(ctx, '変換対象の文字はありませんでした（' + rg.getA1Notation() + '）');
    return;
  }
  rg.setValues(vals);
  chg_(ctx, sh, rg.getA1Notation(), (toHira ? 'ひらがな' : 'カタカナ') + 'へ変換（' + changed + ' 件）');
};
