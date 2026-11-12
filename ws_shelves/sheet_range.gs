// 範囲の棚

// 棚: write
// 題: セルに値・式を書く
// 分類: 範囲
// 語: 値を書|値を入れ|セルに入れ|式を入れ|貼り付け|を書き込|入力して
// 引数: cells=対応, range=範囲, tsv=文字
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
// 語: 置換|置き換え|書き換え|文字を探して|を直して|一括で変|名前を変えて
// 引数: find*=文字, with=文字, range=範囲, match_case=真偽, whole=真偽
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
