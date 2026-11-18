// 範囲の棚

// 棚: write
// 題: セルに値・式を書く
// 分類: 範囲
// 語: 値を書|値を入れ|セルに入れ|式を入れ|書いて|を書き込|入力して|打ち直|と入力|と書いて|セットして|の値を|値を変え|値を書き換
// 引数: cells=対応, range=範囲, tsv=文字
// 頼み: cells~([A-Z]{1,3}[0-9]+)の[^\sを]{0,8}を[『「]?([^』」に]+?)[』」]?に(?:書き換|打ち直|直|変え|入れ) ; cells~(?<![A-Za-z0-9:])([A-Za-z]{1,3}[0-9]+)に(?!チェックボックス)[『「]?([^』」]+?)[』」]?(?:と(?:書|入力|記載|記入|入)|を(?:書|入|入力|セット))
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
// 引数: find*=文字, with=文字, range=範囲, match_case=真偽, whole=真偽
// 頼み: find~[『「]([^』」]+)[』」]を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; with~[『「][^』」]+[』」]を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; find~([^0-9A-Za-z\sを]+)を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換) ; with~[^0-9A-Za-z\sを]+を[『「]?([^』」に]+?)[』」]?に(?:置き換|置換)
// 例: 「営業部を営業課に置き換えて」 → {"shelf":"replace","find":"営業部","with":"営業課"}
// 触る: 値
SHELF['replace'] = function (ctx, op) {
  need_(op, ['find']);
  var sh = sheetCtx_(ctx, op), scope = op.range ? sh.getRange(op.range) : sh.getDataRange();
  var tf = scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole);
  var hits = tf.findAll().map(function (r) { return r.getA1Notation(); });
  if (!hits.length) { note_(ctx, '「' + op.find + '」は見つかりませんでした'); return; }
  scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole).replaceAllWith(String(op['with'] === undefined ? '' : op['with']));
  chg_(ctx, sh, hits.slice(0, 4).join('・') + (hits.length > 4 ? ' ほか' + (hits.length - 4) + ' 件' : ''), '「' + op.find + '」→「' + (op['with'] || '') + '」');
};

// 棚: find
// 題: 値を探して番地を返す
// 分類: 範囲
// 語: を探して|を検索|どこにある|があるセル|入っているセル|どのセル
// 違い: 置き換えるなら replace、値を取り出すなら ws_look
// 引数: text*=文字, range=範囲, whole=真偽, all_sheets=真偽
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
// 語: 値を消|値をクリア|中身を消|中身を空|入力を消|数字を消|データを消|範囲の値を消|セルの値を消|セルを消|番地を消|の値を消して
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
        if (!formulas[r][c] && vals[r][c] !== '') {
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
// 語: 値だけ貼|値のみ貼|値として貼|式を値に|数式を値に|値に変え|値貼り付け
// 違い: 全部写すなら copy、書式だけなら copy.format
// 引数: from*=範囲, to=範囲
// 例: 「C列の計算式を値に変えて」 → {"shelf":"copy.values","from":"C2:C50"}
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
// 語: 書式だけ貼|書式のみ貼|書式をコピー|書式を写|同じ書式に|同じ見た目に|書式貼り付け
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
// 題: 文字で入った日付を本物の日付に直す
// 分類: 範囲
// 語: ちゃんとした日付|本物の日付|日付に直|日付にして|日付にしておいて|文字の日付|文字で入って|日付じゃなく|日付として扱|日付型|日付と認識
// 違い: 日付の見せ方（「11月4日(水)」など）を変えるだけなら format の number_format。日付を下へ連続で入れるなら fill.date
// 引数: col=列, range=範囲
// どれか: col range
// 例: 「日付の列に文字で入っている日付を、ちゃんとした日付にして」 → {"shelf":"date.fix","col":"日付"}
// 例: 「B2:B30の日付が文字になっているので日付にして」 → {"shelf":"date.fix","range":"B2:B30"}
// 触る: 値
// 控え: 今
SHELF['date.fix'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), rg, t = null;
  if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, t.lastData - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「date.fix」に col か range が要ります');
  var vals = rg.getValues(), forms = rg.getFormulas(), fmts = rg.getNumberFormats();
  // 年を書いていない日付（「11月4日」）は、同じ列の本物の日付の年に合わせる（無ければ今年）
  var year = new Date().getFullYear(), dateFmt = '';
  for (var r0 = 0; r0 < vals.length; r0++) for (var c0 = 0; c0 < vals[r0].length; c0++) {
    var v0 = vals[r0][c0];
    if (v0 instanceof Date && !isNaN(v0.getTime())) { year = v0.getFullYear(); if (!dateFmt && fmts[r0][c0] && fmts[r0][c0] !== '@') dateFmt = fmts[r0][c0]; }
  }
  var z2h = function (x) { return x.replace(/[０-９]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); }).replace(/[／－．]/g, function (ch) { return { '／': '/', '－': '-', '．': '.' }[ch]; }); };
  var mk = function (y, m, d) { var dt = new Date(y, m - 1, d); return (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d) ? dt : null; };
  var fixed = [];
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    var v = vals[r][c];
    if (forms[r][c] || typeof v !== 'string' || !v.trim()) continue;
    var s = z2h(v.trim()).replace(/\s*[(（][^)）]*[)）]\s*$/, '');      // 後ろの（水）は外して読む
    var m = s.match(/^(\d{4})\s*[\/\-.年]\s*(\d{1,2})\s*[\/\-.月]\s*(\d{1,2})\s*日?$/), dt = null;
    if (m) dt = mk(+m[1], +m[2], +m[3]);
    else if ((m = s.match(/^(\d{1,2})\s*[\/月]\s*(\d{1,2})\s*日?$/))) dt = mk(year, +m[1], +m[2]);
    if (!dt) continue;
    vals[r][c] = dt;
    if (!fmts[r][c] || fmts[r][c] === '@' || fmts[r][c] === 'General') fmts[r][c] = dateFmt || 'yyyy/mm/dd';
    fixed.push(rg.getCell(r + 1, c + 1).getA1Notation());
  }
  if (!fixed.length) { note_(ctx, '文字で入った日付は見つかりませんでした（' + rg.getA1Notation() + '）'); return; }
  rg.setNumberFormats(fmts);
  rg.setValues(vals);
  chg_(ctx, sh, fixed.slice(0, 5).join('・') + (fixed.length > 5 ? ' ほか ' + (fixed.length - 5) + ' 件' : ''), '文字の日付を日付に（' + fixed.length + ' 件）');
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
    dt = new Date(op.start);
  } else {
    var v = rg.getCell(1, 1).getValue();
    dt = (v instanceof Date && !isNaN(v.getTime())) ? new Date(v.getTime()) : new Date();
  }
  var nr = rg.getNumRows(), nc = rg.getNumColumns();
  var vals = [];
  var cur = new Date(dt.getTime());
  var stepFn = function (d, u) {
    var next = new Date(d.getTime());
    if (u === 'day') next.setDate(next.getDate() + 1);
    else if (u === 'week') next.setDate(next.getDate() + 7);
    else if (u === 'month') next.setMonth(next.getMonth() + 1);
    else if (u === 'weekday') {
      do { next.setDate(next.getDate() + 1); } while (next.getDay() === 0 || next.getDay() === 6);
    }
    return next;
  };
  for (var r = 0; r < nr; r++) {
    var row = [];
    for (var c = 0; c < nc; c++) {
      row.push(new Date(cur.getTime()));
      cur = stepFn(cur, unit);
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
// 語: 下まで写|下までコピー|式を下まで|下にコピー|オートフィル|下へ伸ば|下方向にコピー
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
  for (var r = 1; r < rg.getNumRows(); r++) {
    firstRow.copyTo(rg.offset(r, 0, 1, rg.getNumColumns()));
  }
  chg_(ctx, sh, dest.getA1Notation(), '上のセルを下へ複写');
};
