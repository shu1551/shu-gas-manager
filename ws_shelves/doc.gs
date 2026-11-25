// 文書の棚（Markdown の読み取り・書き出しの手伝いも、ここに置く）

function parseMd_(md) {
  var lines = String(md).replace(/\r/g, '').split('\n'), blocks = [], i = 0;
  while (i < lines.length) {
    var ln = lines[i], m;
    if (/^\s*$/.test(ln)) { i++; continue; }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(ln))) { blocks.push({ t: 'h', level: m[1].length, text: m[2] }); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { blocks.push({ t: 'hr' }); i++; continue; }
    if (/^\s*\|/.test(ln)) {
      var rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        var cells = lines[i].trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (s) { return s.trim(); });
        if (!cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) rows.push(cells);
        i++;
      }
      blocks.push({ t: 'table', rows: rows }); continue;
    }
    if ((m = /^(\s*)[-*+]\s+(.*)$/.exec(ln))) { blocks.push({ t: 'li', ordered: false, level: Math.floor(m[1].length / 2), text: m[2] }); i++; continue; }
    if ((m = /^(\s*)\d+[.)]\s+(.*)$/.exec(ln))) { blocks.push({ t: 'li', ordered: true, level: Math.floor(m[1].length / 2), text: m[2] }); i++; continue; }
    blocks.push({ t: 'p', text: ln.trim() }); i++;
  }
  return blocks;
}
function inlineRuns_(text) {
  // **太字** と *斜体* を分ける
  var runs = [], re = /(\*\*[^*]+\*\*|\*[^*]+\*)/g, last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) runs.push({ s: text.slice(last, m.index) });
    if (m[0].indexOf('**') === 0) runs.push({ s: m[0].slice(2, -2), b: true }); else runs.push({ s: m[0].slice(1, -1), i: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) runs.push({ s: text.slice(last) });
  return runs.length ? runs : [{ s: '' }];
}
function applyInline_(el, text) {
  var runs = inlineRuns_(text), plain = runs.map(function (r) { return r.s; }).join('');
  var tx = el.editAsText(); tx.setText(plain); tx.setBold(false); tx.setItalic(false);
  var pos = 0;
  runs.forEach(function (r) { if (r.s.length) { if (r.b) tx.setBold(pos, pos + r.s.length - 1, true); if (r.i) tx.setItalic(pos, pos + r.s.length - 1, true); } pos += r.s.length; });
}
var HEADINGS = [null, DocumentApp.ParagraphHeading.HEADING1, DocumentApp.ParagraphHeading.HEADING2, DocumentApp.ParagraphHeading.HEADING3,
  DocumentApp.ParagraphHeading.HEADING4, DocumentApp.ParagraphHeading.HEADING5, DocumentApp.ParagraphHeading.HEADING6];

// 本文の idx 番目（null なら末尾）から順にブロックを入れる。入れた数を返す
function emitBlocks_(body, blocks, idx, prevList) {
  var n = 0;
  blocks.forEach(function (b) {
    var el;
    var put = function (kind, arg) {
      if (idx === null) return kind === 'p' ? body.appendParagraph(arg) : kind === 'li' ? body.appendListItem(arg) : body.appendTable(arg);
      var r = kind === 'p' ? body.insertParagraph(idx + n, arg) : kind === 'li' ? body.insertListItem(idx + n, arg) : body.insertTable(idx + n, arg);
      return r;
    };
    if (b.t === 'h') { el = put('p', ''); el.setHeading(HEADINGS[Math.min(b.level, 6)]); applyInline_(el, b.text); prevList = null; }
    else if (b.t === 'p') { el = put('p', ''); el.setHeading(DocumentApp.ParagraphHeading.NORMAL); applyInline_(el, b.text); prevList = null; }
    else if (b.t === 'li') {
      el = put('li', ''); applyInline_(el, b.text);
      el.setGlyphType(b.ordered ? DocumentApp.GlyphType.NUMBER : DocumentApp.GlyphType.BULLET);
      if (b.level) el.setNestingLevel(Math.min(b.level, 8));
      if (prevList && prevList.ordered === b.ordered) { try { el.setListId(prevList.el); } catch (e) { } }
      prevList = { el: el, ordered: b.ordered };
    }
    else if (b.t === 'table') {
      var w = Math.max.apply(null, b.rows.map(function (r) { return r.length; }));
      var cells = b.rows.map(function (r) { var x = r.slice(); while (x.length < w) x.push(''); return x; });
      el = put('t', cells);
      styleTable_(el);
      prevList = null;
    }
    else if (b.t === 'hr') { el = idx === null ? body.appendHorizontalRule() : body.insertHorizontalRule(idx + n); prevList = null; }
    n++;
  });
  return n;
}
function styleTable_(tb) {
  for (var c = 0; c < tb.getRow(0).getNumCells(); c++) { var ce = tb.getCell(0, c); ce.setBackgroundColor('#D9E2F3'); ce.editAsText().setBold(true); }
}

// ---------------------------------------------------------------- 文書：位置

function headingAt_(body, text) {
  var want = String(text).trim(), n = body.getNumChildren(), hit = -1;
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() !== DocumentApp.ElementType.PARAGRAPH) continue;
    var p = ch.asParagraph(), h = String(p.getHeading());
    if (!/^HEADING\d/.test(h)) continue;
    var tx = p.getText().trim();
    if (tx === want) return { idx: i, level: parseInt(h.slice(7)) };
    if (hit < 0 && tx.indexOf(want) >= 0) hit = i;
  }
  if (hit >= 0) return { idx: hit, level: parseInt(String(body.getChild(hit).asParagraph().getHeading()).slice(7)) };
  var names = []; for (var j = 0; j < n; j++) { var c = body.getChild(j); if (c.getType() === DocumentApp.ElementType.PARAGRAPH && /^HEADING\d/.test(String(c.asParagraph().getHeading()))) names.push(c.asParagraph().getText()); }
  throw new ArgError('見出し「' + text + '」がありません。あるのは: ' + names.join('、'));
}
// 見出し idx の節の終わり（次の同じか上の階層の見出しの手前）。末尾の空段落は節に含めない
function sectionEnd_(body, h) {
  var n = body.getNumChildren(), end = n;
  for (var i = h.idx + 1; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
      var hh = String(ch.asParagraph().getHeading());
      if (/^HEADING\d/.test(hh) && parseInt(hh.slice(7)) <= h.level) { end = i; break; }
    }
  }
  while (end - 1 > h.idx) {
    var e = body.getChild(end - 1);
    if (e.getType() === DocumentApp.ElementType.PARAGRAPH && e.asParagraph().getText() === '' ) end--; else break;
  }
  return end;
}

// ---------------------------------------------------------------- 棚：文書

function docKind_(fn) { fn.kind = 'doc'; return fn; }

// 棚: doc.new
// 題: 文書の本文を書く
// 分類: 文書
// 語: 文書を作|文書を書|本文を書|議事録を作|見積書を作|文章を作|ドキュメントを作
// 引数: markdown*=文字
// 例: 「見出しと箇条書きの文書を書いて」 → {"shelf":"doc.new","markdown":"# 題\n- 項目1\n- 項目2"}
// 触る: 値 書式
SHELF['doc.new'] = docKind_(function (ctx, op) {
  need_(op, ['markdown']);
  var body = ctx.doc.getBody();
  if (body.getText() !== '' || body.getNumChildren() > 1) {
    // 撃ち直し：同じ内容なら変更なし
    var probe = body.getText();
    var want = parseMd_(op.markdown).map(function (b) { return b.t === 'table' ? b.rows.map(function (r) { return r.join(''); }).join('') : (b.text || ''); }).join('').replace(/\*/g, '');
    if (probe.replace(/\s/g, '').replace(/\*/g, '').indexOf(want.replace(/\s/g, '')) === 0 && probe.replace(/\s/g, '').length === want.replace(/\s/g, '').length) { note_(ctx, '同じ文書がすでにあります（変更なし）'); return; }
    throw new ArgError('この文書にはすでに内容があります。追記は doc.append、差し替えは doc.section を使ってください');
  }
  var blocks = parseMd_(op.markdown);
  emitBlocks_(body, blocks, null, null);
  if (body.getNumChildren() > 1 && body.getChild(0).getType() === DocumentApp.ElementType.PARAGRAPH && body.getChild(0).asParagraph().getText() === '') body.removeChild(body.getChild(0));
  var tail = body.getChild(body.getNumChildren() - 1);
  if (tail.getType() === DocumentApp.ElementType.TABLE) body.appendParagraph('');
  chg_(ctx, null, '全体', '文書を作成（' + blocks.length + ' ブロック）');
});

// 棚: doc.append
// 題: 文書に追記する
// 分類: 文書
// 語: 追記|末尾に足|文末に足|最後に追加|段落を足|項目を足|節の下に|最後に|末尾に
// 引数: markdown*=文字, under=文字
// 頼み: markdown~[『「]([^』」]+)[』」]を?(?:書き足|足|追記|加え) ; markdown~最後に[『「]([^』」]+)[』」]を?(?:足|追加|追記)
// 例: 「最後に1行足して」 → {"shelf":"doc.append","markdown":"以上です。"}
// 触る: 値 書式
SHELF['doc.append'] = docKind_(function (ctx, op) {
  need_(op, ['markdown']);
  var body = ctx.doc.getBody(), blocks = parseMd_(op.markdown);
  var idx, prevList = null;
  if (op.under) {
    var h = headingAt_(body, op.under), end = sectionEnd_(body, h);
    idx = end;
    var prev = idx - 1 > h.idx ? body.getChild(idx - 1) : null;
    if (prev && prev.getType() === DocumentApp.ElementType.LIST_ITEM) {
      var pl = prev.asListItem();
      prevList = { el: pl, ordered: /NUMBER|LATIN|ROMAN/.test(String(pl.getGlyphType())) };
    }
    // 同じ行がすでにあれば足さない（撃ち直し）
    var firstText = blocks.length && blocks[0].text ? blocks[0].text.replace(/\*/g, '') : null;
    if (firstText) for (var k = h.idx + 1; k < end; k++) { var c = body.getChild(k); var tx = c.getType() === DocumentApp.ElementType.LIST_ITEM ? c.asListItem().getText() : c.getType() === DocumentApp.ElementType.PARAGRAPH ? c.asParagraph().getText() : null; if (tx === firstText && blocks.length === 1) { note_(ctx, '同じ行がすでにあります（変更なし）'); return; } }
  } else {
    var n = body.getNumChildren();
    idx = n;
    while (idx > 0 && body.getChild(idx - 1).getType() === DocumentApp.ElementType.PARAGRAPH && body.getChild(idx - 1).asParagraph().getText() === '' && idx > 1) idx--;
    var lastEl = idx > 0 ? body.getChild(idx - 1) : null;
    if (lastEl && lastEl.getType() === DocumentApp.ElementType.LIST_ITEM) prevList = { el: lastEl.asListItem(), ordered: /NUMBER|LATIN|ROMAN/.test(String(lastEl.asListItem().getGlyphType())) };
    var tailText = lastEl && lastEl.getType() !== DocumentApp.ElementType.TABLE ? (lastEl.getType() === DocumentApp.ElementType.LIST_ITEM ? lastEl.asListItem().getText() : lastEl.asParagraph().getText()) : null;
    if (blocks.length === 1 && blocks[0].text && tailText === blocks[0].text.replace(/\*/g, '')) { note_(ctx, '同じ行がすでにあります（変更なし）'); return; }
  }
  var cnt = emitBlocks_(body, blocks, idx, prevList);
  chg_(ctx, null, (op.under ? '「' + op.under + '」の下 ' : '末尾 ') + (idx + 1) + '〜' + (idx + cnt) + ' 番目', cnt + ' ブロックを追記');
});

// 棚: doc.replace
// 題: 文書の文字を置き換える
// 分類: 文書
// 語: 文書を置換|文書の置き換え|文中の語を|表記を統一|言葉を直し|文字を直し|語を変えて|置き換えて|置換して
// 引数: find*=文字, with=文字, match_case=真偽
// 頼み: find~[『「]([^』」]+)[』」]を[『「](?:[^』」]+)[』」]に ; with~[『「](?:[^』」]+)[』」]を[『「]([^』」]+)[』」]に
// 例: 「山田を山田（総務）に直して」 → {"shelf":"doc.replace","find":"山田","with":"山田（総務）"}
// 触る: 値 書式
SHELF['doc.replace'] = docKind_(function (ctx, op) {
  need_(op, ['find']);
  var body = ctx.doc.getBody(), find = String(op.find), rep = op['with'] === undefined ? '' : String(op['with']);
  var esc = find.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var pat = op.match_case === false ? '(?i)' + esc : esc;
  var hits = [], r = body.findText(pat);
  while (r) {
    var el = r.getElement().asText(), s = r.getStartOffset(), e = r.getEndOffsetInclusive();
    var par = el.getParent(), pidx = -1;
    var top = par; while (top && top.getParent() && top.getParent().getType() !== DocumentApp.ElementType.BODY_SECTION) top = top.getParent();
    if (top) pidx = body.getChildIndex(top);
    var skip = false;
    if (rep && rep.indexOf(find) >= 0) {   // 置換後の文字に探す文字が含まれる（山田→山田（総務））：すでに置換済みの所は飛ばす
      var k = rep.indexOf(find), full = el.getText();
      skip = full.substr(s - k, rep.length) === rep;
    }
    if (!skip) hits.push({ el: el, s: s, e: e, p: pidx });
    r = body.findText(pat, r);
  }
  if (!hits.length) { note_(ctx, '「' + find + '」は見つかりませんでした'); return; }
  // 後ろから置換（位置がずれない）
  for (var i = hits.length - 1; i >= 0; i--) {
    var h = hits[i];
    h.el.deleteText(h.s, h.e);
    if (rep) h.el.insertText(h.s, rep);
  }
  var ps = hits.map(function (h) { return h.p + 1; }).filter(function (v, i, a) { return a.indexOf(v) === i; }).sort(function (a, b) { return a - b; });
  chg_(ctx, null, '段落 ' + ps.slice(0, 6).join('・') + (ps.length > 6 ? ' ほか' : '') + ' 番目', '「' + find + '」→「' + rep + '」' + hits.length + ' か所');
});

// 棚: doc.section
// 題: 文書の節を差し替え・削除
// 分類: 文書
// 語: 節を差し替|節を削除|見出しの下を|章を書き直|節を書き直|節ごと消|見出しごと
// 引数: heading*=文字, action=選択(replace/delete)=replace, markdown=文字
// 頼み: heading~[『「]([^』」]+)[』」]の節 ; action=delete<節を消|節を削除 ; markdown~の節を[『「]([^』」]+)[』」]に
// 例: 「「概要」の節を書き直して」 → {"shelf":"doc.section","heading":"概要","markdown":"新しい概要です。"}
// 危ない: 消す
// 触る: 値 書式
SHELF['doc.section'] = docKind_(function (ctx, op) {
  need_(op, ['heading']);
  if ((op.action || 'replace') === 'replace') need_(op, ['markdown']);   // 差し替えの中身が無いまま節を消さない（道具の事前検査の代わり）
  var body = ctx.doc.getBody(), act = op.action || 'replace', h = headingAt_(body, op.heading), end = sectionEnd_(body, h);
  var count = end - h.idx - 1;
  if (act === 'delete' || act === 'replace') {
    guardDelete_(ctx, '見出し「' + op.heading + '」の節（' + (h.idx + 2) + '〜' + end + ' 番目の ' + count + ' ブロック）を' + (act === 'delete' ? '削除' : '差し替え') + 'ます');
    for (var i = end - 1; i > h.idx; i--) { var ch = body.getChild(i); if (body.getNumChildren() > 1) { try { body.removeChild(ch); } catch (e) { ch.asParagraph && ch.asParagraph().clear(); } } }
    if (act === 'delete') { var hd = body.getChild(h.idx); try { body.removeChild(hd); } catch (e2) { } chg_(ctx, null, '見出し「' + op.heading + '」の節', '削除（' + (count + 1) + ' ブロック）'); return; }
    need_(op, ['markdown']);
    var blocks = parseMd_(op.markdown);
    var cnt = emitBlocks_(body, blocks, h.idx + 1, null);
    chg_(ctx, null, '見出し「' + op.heading + '」の節 ' + (h.idx + 2) + '〜' + (h.idx + 1 + cnt) + ' 番目', '差し替え（' + count + ' → ' + cnt + ' ブロック）');
  } else throw new ArgError('棚「doc.section」の action は replace・delete です');
});

// 棚: doc.table
// 題: 文書に表を入れる・直す
// 分類: 文書
// 語: 文書に表|表を挿入|表を入れ|表のセル|表の中を|表を足|表を直し
// 引数: action=選択(insert/cell), rows=表, under=文字, table=数, row=数, col=数, text=文字
// どれか: rows text
// 例: 「文末に2列の表を入れて」 → {"shelf":"doc.table","rows":[["項目","内容"],["a","b"]]}
// 例: 「1つ目の表の2行1列を直して」 → {"shelf":"doc.table","table":1,"row":2,"col":1,"text":"新"}
// 触る: 値 書式
SHELF['doc.table'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), act = op.action || (op.rows ? 'insert' : 'cell');
  if (act === 'insert') {
    need_(op, ['rows']);
    var idx;
    if (op.under) { var h = headingAt_(body, op.under); idx = sectionEnd_(body, h); } else { idx = body.getNumChildren(); while (idx > 1 && body.getChild(idx - 1).getType() === DocumentApp.ElementType.PARAGRAPH && body.getChild(idx - 1).asParagraph().getText() === '') idx--; }
    var w = Math.max.apply(null, op.rows.map(function (r) { return r.length; }));
    var cells = op.rows.map(function (r) { var x = r.map(String); while (x.length < w) x.push(''); return x; });
    var tb = body.insertTable(idx, cells); styleTable_(tb);
    chg_(ctx, null, (idx + 1) + ' 番目', '表を挿入（' + cells.length + '行×' + w + '列）');
  } else if (act === 'cell') {
    need_(op, ['row', 'col', 'text']);
    var tables = body.getTables(), ti = (op.table || 1) - 1;
    if (!tables.length) throw new ArgError('文書に表がありません');
    if (ti < 0 || ti >= tables.length) throw new ArgError('表 ' + (ti + 1) + ' がありません（表は ' + tables.length + ' 個）');
    var t = tables[ti];
    if (op.row < 1 || op.row > t.getNumRows() || op.col < 1 || op.col > t.getRow(0).getNumCells()) throw new ArgError('セルが範囲外です（表は ' + t.getNumRows() + '行×' + t.getRow(0).getNumCells() + '列）');
    t.getCell(op.row - 1, op.col - 1).setText(String(op.text));
    chg_(ctx, null, '表' + (ti + 1) + ' の ' + op.row + '行' + op.col + '列', '「' + op.text + '」に変更');
  } else throw new ArgError('棚「doc.table」の action は insert・cell です');
});

// 棚: doc.style
// 題: 文書の書式をそろえる
// 分類: 文書
// 語: 書式をそろえ|フォントを|行間を|文字サイズ|見出しをそろえ|体裁を整え|文書を整|文字の大きさ|文書の見た目
// 引数: font=文字, size=数, line_spacing=数
// 頼み: font~フォントを(.+?)に ; size~([0-9.]+)\s*pt ; size~文字の大きさを([0-9.]+) ; line_spacing~行間を([0-9.]+)
// 例: 「文書のフォントをMeiryoに」 → {"shelf":"doc.style","font":"Meiryo"}
// 触る: 書式
SHELF['doc.style'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), n = body.getNumChildren(), count = 0;
  var hs = { 1: { size: 20, color: '#1F4E79' }, 2: { size: 16, color: '#1F4E79' }, 3: { size: 13, color: '#2F5597' } };
  var font = op.font || 'Arial', bsize = op.size || 11, ls = op.line_spacing || 1.15;
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i), t = ch.getType();
    if (t === DocumentApp.ElementType.PARAGRAPH || t === DocumentApp.ElementType.LIST_ITEM) {
      var p = t === DocumentApp.ElementType.PARAGRAPH ? ch.asParagraph() : ch.asListItem();
      var hh = String(p.getHeading()), m = /^HEADING(\d)/.exec(hh), tx = p.editAsText();
      if (!p.getText()) continue;
      tx.setFontFamily(font);
      if (m && hs[m[1]]) { tx.setFontSize(hs[m[1]].size).setBold(true).setForegroundColor(hs[m[1]].color); }
      else if (!m) tx.setFontSize(bsize);
      p.setLineSpacing(ls); count++;
    } else if (t === DocumentApp.ElementType.TABLE) { styleTable_(ch.asTable()); count++; }
  }
  chg_(ctx, null, '全体', '見出し・本文・表の見出し行をそろえた（' + count + ' ブロック）');
});
