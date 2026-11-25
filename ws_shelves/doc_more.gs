// 文書の追加棚

// 棚: doc.outline
// 題: 文書の見出し一覧を見る
// 分類: 文書
// 語: 章立て|見出し一覧|文書の構成|目次を見せて|目次を確認|アウトライン|文書の構成を見
// 違い: 本文を書くなら doc.new。節の差し替えなら doc.section。文字を探すなら doc.find
// 引数: なし
// 例: 「この文書の章立てを見せて」 → {"shelf":"doc.outline"}
// 触る: なし
SHELF['doc.outline'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), n = body.getNumChildren(), lines = [];
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
      var p = ch.asParagraph(), h = String(p.getHeading());
      if (/^HEADING\d/.test(h)) {
        var lvl = parseInt(h.slice(7), 10);
        var hashes = new Array(lvl + 1).join('#');
        lines.push(hashes + ' ' + p.getText().trim());
      }
    }
  }
  note_(ctx, lines.length ? lines.join('\n') : '見出しはありません');
});

// 棚: doc.insert
// 題: 文書に段落を差し込む
// 分類: 文書
// 語: 節の下に足|見出しの下に|段落を挿入|間に書き足|の後に足|段落を追加|行を差し込|の下に1行足
// 違い: 末尾に追記するなら doc.append。節ごと差し替えるなら doc.section。表に足すなら doc.table.row
// 引数: markdown*=文字, under=文字, after=数
// 頼み: under~[『「]([^』」]+)[』」]の下 ; under~([^\s]+)の下に ; markdown~[『「]([^』」]+)[』」]を?(?:差し込|挿入|足|追加)
// 例: 「決定事項の下に1行足して」 → {"shelf":"doc.insert","under":"決定事項","markdown":"- 次回は 12/2"}
// 触る: 値
SHELF['doc.insert'] = docKind_(function (ctx, op) {
  need_(op, ['markdown']);
  var body = ctx.doc.getBody(), blocks = parseMd_(op.markdown);
  var idx = null;
  if (op.under) {
    var h = headingAt_(body, op.under);
    idx = h.idx + 1;
  } else if (op.after !== undefined) {
    idx = parseInt(op.after, 10);
  } else {
    idx = body.getNumChildren();
  }
  emitBlocks_(body, blocks, idx, null);
  chg_(ctx, null, (op.under ? '「' + op.under + '」の下' : '位置 ' + idx), '段落を差し込み（' + blocks.length + ' ブロック）');
});

// 棚: doc.table.cell
// 題: 文書の表のセルを書き換える
// 分類: 文書
// 語: 表のセル|表の値を|表の欄を書き換|表の中身を直|セルの文字を|表の欄を直|表の担当欄|表のセルを|セルの中身を直|表の金額のセル
// 違い: 表全体を差し替えるなら doc.table。文中の置換なら doc.replace。行を足すなら doc.table.row
// 引数: text*=文字, find=文字, table=数, row=数, col=数
// 頼み: find~([^\sの]+)の(?:欄|セル) ; text~[『「]([^』」]+)[』」]にして ; text~欄を([^\sに]+)にして
// 例: 「担当の欄を佐藤にして」 → {"shelf":"doc.table.cell","find":"担当","text":"佐藤"}
// 触る: 値
SHELF['doc.table.cell'] = docKind_(function (ctx, op) {
  need_(op, ['text']);
  var body = ctx.doc.getBody(), n = body.getNumChildren();
  var tables = [];
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.TABLE) tables.push(ch.asTable());
  }
  if (!tables.length) throw new ArgError('文書内に表がありません');
  var tbl = tables[op.table ? (op.table - 1) : 0];
  var done = false;
  if (op.find) {
    var findStr = String(op.find).trim();
    for (var r = 0; r < tbl.getNumRows(); r++) {
      var row = tbl.getRow(r);
      for (var c = 0; c < row.getNumCells(); c++) {
        var cell = row.getCell(c);
        if (cell.getText().trim() === findStr) {
          var targetCell = (c + 1 < row.getNumCells()) ? row.getCell(c + 1) : cell;
          targetCell.setText(String(op.text));
          done = true; break;
        }
      }
      if (done) break;
    }
    if (!done) throw new ArgError('表内に「' + findStr + '」の項目が見つかりません');
  } else if (op.row !== undefined && op.col !== undefined) {
    var tr = op.row - 1, tc = op.col - 1;
    if (tr < 0 || tr >= tbl.getNumRows() || tc < 0 || tc >= tbl.getRow(tr).getNumCells()) {
      throw new ArgError('指定された行・列（' + op.row + ', ' + op.col + '）は表の範囲外です');
    }
    tbl.getCell(tr, tc).setText(String(op.text));
    done = true;
  } else {
    throw new ArgError('棚「doc.table.cell」には find または (row, col) が必要です');
  }
  chg_(ctx, null, '表', 'セルを「' + op.text + '」に書き換え');
});

// 棚: doc.find
// 題: 文書の言葉を探す
// 分類: 文書
// 語: 言葉を探して|単語を探して|どこに書いてある|文書内を検索|どの節にある|探して|キーワード検索|文書内で|を検索して
// 違い: 置き換えるなら doc.replace。見出し一覧なら doc.outline
// 引数: text*=文字, match_case=真偽
// 頼み: text~[『「]([^』」]+)[』」]という言葉を探して ; text~[『「]([^』」]+)[』」]を探して
// 例: 「納期と書いてある所はどこ？」 → {"shelf":"doc.find","text":"納期"}
// 触る: なし
SHELF['doc.find'] = docKind_(function (ctx, op) {
  need_(op, ['text']);
  var body = ctx.doc.getBody(), findStr = String(op.text);
  var esc = findStr.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var pat = op.match_case === false ? '(?i)' + esc : esc;
  var r = body.findText(pat), hits = [];
  while (r) {
    var el = r.getElement();
    var top = el;
    while (top && top.getParent() && top.getParent().getType() !== DocumentApp.ElementType.BODY_SECTION) {
      top = top.getParent();
    }
    var pidx = top ? body.getChildIndex(top) : -1;
    var heading = '本文先頭';
    for (var k = pidx; k >= 0; k--) {
      var ch = body.getChild(k);
      if (ch.getType() === DocumentApp.ElementType.PARAGRAPH && /^HEADING\d/.test(String(ch.asParagraph().getHeading()))) {
        heading = ch.asParagraph().getText().trim();
        break;
      }
    }
    hits.push('段落' + (pidx + 1) + '（' + heading + '）');
    r = body.findText(pat, r);
  }
  if (!hits.length) note_(ctx, '「' + findStr + '」は見つかりませんでした');
  else note_(ctx, '「' + findStr + '」の見つかった箇所 (' + hits.length + '件): ' + hits.slice(0, 5).join('、') + (hits.length > 5 ? ' ほか' : ''));
});

// 棚: doc.heading
// 題: 見出しにする・見出しの段を変える
// 分類: 文書
// 語: 見出しにして|見出し2にして|見出し3にして|大見出し|中見出し|小見出し|見出しのレベル|見出しに変更
// 違い: 章立てを見るなら doc.outline。書式（太字等）なら doc.font
// 引数: level*=数, text=文字, heading=文字
// 頼み: level~見出し\s*([1-6]) ; text~[『「]([^』」]+)[』」]を見出し ; text~([^\s]+)を見出し
// 例: 「この行を見出し2にして」 → {"shelf":"doc.heading","text":"決定事項","level":2}
// 触る: 書式
SHELF['doc.heading'] = docKind_(function (ctx, op) {
  need_(op, ['level']);
  var body = ctx.doc.getBody(), lvl = parseInt(op.level, 10);
  var hEnum = lvl === 0 ? DocumentApp.ParagraphHeading.NORMAL : HEADINGS[Math.min(Math.max(lvl, 1), 6)];
  var target = op.heading || op.text;
  if (!target) throw new ArgError('対象の段落（text または heading）が必要です');
  var found = false;
  for (var i = 0; i < body.getNumChildren(); i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
      var p = ch.asParagraph();
      if (p.getText().trim().indexOf(String(target).trim()) >= 0) {
        p.setHeading(hEnum);
        found = true;
        break;
      }
    }
  }
  if (!found) throw new ArgError('「' + target + '」の段落が見つかりません');
  chg_(ctx, null, '「' + target + '」', '見出し' + (lvl || '本文') + 'に設定');
});

// 棚: doc.list
// 題: 箇条書き・番号つきリストにする
// 分類: 文書
// 語: 箇条書きにして|番号付きにして|リストにして|番号リスト|箇条書きを外して|箇条書きに|番号付きリスト
// 違い: 追記するなら doc.append。差し込むなら doc.insert
// 引数: type=選択(bullet/number/none)=bullet, under=文字, text=文字
// 頼み: type=number<番号付き|番号リスト ; type=bullet<箇条書き ; type=none<外して|解除 ; under~[『「]([^』」]+)[』」]の下
// 例: 「出席者を箇条書きにして」 → {"shelf":"doc.list","under":"出席者","type":"bullet"}
// 触る: 書式
SHELF['doc.list'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), type = op.type || 'bullet';
  var start = 0, end = body.getNumChildren();
  if (op.under) {
    var h = headingAt_(body, op.under);
    start = h.idx + 1;
    end = sectionEnd_(body, h);
  }
  var count = 0;
  for (var i = start; i < end; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
      var p = ch.asParagraph();
      if (p.getText().trim() === '') continue;
      if (type === 'bullet' || type === 'number') {
        var li = body.insertListItem(i, p.getText());
        li.setGlyphType(type === 'bullet' ? DocumentApp.GlyphType.BULLET : DocumentApp.GlyphType.NUMBER);
        body.removeChild(p);
        count++;
      }
    } else if (ch.getType() === DocumentApp.ElementType.LIST_ITEM && type === 'none') {
      var li2 = ch.asListItem();
      var np = body.insertParagraph(i, li2.getText());
      np.setHeading(DocumentApp.ParagraphHeading.NORMAL);
      body.removeChild(li2);
      count++;
    }
  }
  chg_(ctx, null, (op.under ? '「' + op.under + '」の下' : '全体'), count + ' 段落を' + (type === 'none' ? '本文に戻した' : 'リスト化'));
});

// 棚: doc.delete
// 題: 段落・節を消す
// 分類: 文書
// 語: 節を消して|段落を削除|見出しを消して|節を削除|段落を消して|文書の節を消|不要な節を消|節をまるごと削除|文書 削除 節
// 違い: 節の中身を差し替えるなら doc.section。文字の置換なら doc.replace
// 引数: heading=文字, text=文字
// 頼み: heading~[『「]([^』」]+)[』」]の(?:節|章)を消 ; heading~([^\s]+)の節を消
// 例: 「補足の節を消して」 → {"shelf":"doc.delete","heading":"補足"}
// 危ない: 消す
// 触る: 値
SHELF['doc.delete'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody();
  if (op.heading) {
    var h = headingAt_(body, op.heading);
    var end = sectionEnd_(body, h);
    var cnt = end - h.idx;
    guardDelete_(ctx, '節「' + op.heading + '」（' + cnt + ' ブロック）を削除します', cnt > 5, cnt + ' ブロック');
    for (var i = end - 1; i >= h.idx; i--) {
      body.removeChild(body.getChild(i));
    }
    chg_(ctx, null, '「' + op.heading + '」', '節を削除（' + cnt + ' ブロック）');
  } else if (op.text) {
    var findStr = String(op.text).trim();
    var removed = 0;
    for (var j = body.getNumChildren() - 1; j >= 0; j--) {
      var ch = body.getChild(j);
      if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
        var tx = ch.asParagraph().getText().trim();
        if (tx === findStr || tx.indexOf(findStr) >= 0) {
          body.removeChild(ch);
          removed++;
          break;
        }
      }
    }
    if (!removed) throw new ArgError('「' + findStr + '」の段落が見つかりません');
    chg_(ctx, null, '段落', '「' + findStr + '」を削除');
  } else {
    throw new ArgError('棚「doc.delete」に heading または text が必要です');
  }
});

// 棚: doc.move
// 題: 節の順番を入れ替える
// 分類: 文書
// 語: 節を移動|節を前に|節を後ろに|節の順番を|順番を入れ替えて|節を移して|先頭に持ってきて|節を前に移|前に移して
// 違い: 差し替えるなら doc.section。削除なら doc.delete
// 引数: heading*=文字, before=文字, after=文字
// 頼み: heading~[『「]([^』」]+)[』」]を[『「]?([^』」\s]+?)[』」]?の(?:前|手前) ; before~の(?:前|手前)に[『「]?([^』」]+)[』」]?を
// 例: 「次回予定を先頭に持ってきて」 → {"shelf":"doc.move","heading":"次回予定","before":"議題"}
// 触る: 値
SHELF['doc.move'] = docKind_(function (ctx, op) {
  need_(op, ['heading']);
  var body = ctx.doc.getBody();
  var h = headingAt_(body, op.heading);
  var send = sectionEnd_(body, h);
  var blocks = [];
  for (var i = h.idx; i < send; i++) {
    var ch = body.getChild(i);
    blocks.push(ch.copy());
  }
  var destIdx = 0;
  if (op.before) {
    var bh = headingAt_(body, op.before);
    destIdx = bh.idx;
  } else if (op.after) {
    var ah = headingAt_(body, op.after);
    destIdx = sectionEnd_(body, ah);
  }
  for (var j = send - 1; j >= h.idx; j--) {
    body.removeChild(body.getChild(j));
  }
  if (destIdx > h.idx) destIdx -= blocks.length;
  destIdx = Math.max(0, Math.min(destIdx, body.getNumChildren()));
  for (var k = 0; k < blocks.length; k++) {
    var b = blocks[k];
    if (b.getType() === DocumentApp.ElementType.PARAGRAPH) body.insertParagraph(destIdx + k, b.asParagraph());
    else if (b.getType() === DocumentApp.ElementType.LIST_ITEM) body.insertListItem(destIdx + k, b.asListItem());
    else if (b.getType() === DocumentApp.ElementType.TABLE) body.insertTable(destIdx + k, b.asTable());
  }
  chg_(ctx, null, '「' + op.heading + '」', '節を移動');
});

// 棚: doc.table.row
// 題: 文書の表に行を追加・削除する
// 分類: 文書
// 語: 表に行を足して|表に行を追加|表の行を消して|表の行を削除|表に1行足して|表の末尾に行|行目を削除|表の行を削除して
// 違い: 表のセルを直すなら doc.table.cell。表全体なら doc.table
// 引数: action=選択(insert/delete)=insert, table=数, at=数, values=配列
// 頼み: action=delete<行を消|行を削除
// 例: 「表に1行足して」 → {"shelf":"doc.table.row","action":"insert","values":["次回","未定"]}
// 触る: 値 書式
SHELF['doc.table.row'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), n = body.getNumChildren(), tables = [];
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.TABLE) tables.push(ch.asTable());
  }
  if (!tables.length) throw new ArgError('文書内に表がありません');
  var tbl = tables[op.table ? (op.table - 1) : 0];
  var act = op.action || 'insert';
  if (act === 'delete') {
    var delIdx = op.at !== undefined ? (op.at - 1) : (tbl.getNumRows() - 1);
    if (delIdx < 0 || delIdx >= tbl.getNumRows()) throw new ArgError('削除する行番号が範囲外です');
    tbl.removeRow(delIdx);
    chg_(ctx, null, '表', (delIdx + 1) + '行目を削除');
  } else {
    var vals = op.values || [];
    var row = tbl.appendTableRow();
    var nc = tbl.getRow(0).getNumCells();
    for (var c = 0; c < nc; c++) {
      var cellText = c < vals.length ? String(vals[c]) : '';
      row.appendTableCell(cellText);
    }
    chg_(ctx, null, '表', '1行追加（' + vals.join('・') + '）');
  }
});

// 棚: doc.font
// 題: 文字の書式を変える
// 分類: 文書
// 語: 文字を太字|文字の色を|下線を引いて|文字を大きく|文字を赤く|太字にして|赤い太字|下線|ポイントにして太字|フォント 文字 色|文字色 大きさ 書式
// 違い: 文書全体なら doc.style。見出しにするなら doc.heading
// 引数: find=文字, under=文字, size=数, color=色, bold=真偽, underline=真偽
// 頼み: bold=true<太字 ; underline=true<下線 ; size~([0-9]+)\s*(?:pt|ポイント) ; find~[『「]([^』」]+)[』」]を
// 例: 「締め切りの日付を赤い太字にして」 → {"shelf":"doc.font","find":"11/20","color":"赤","bold":true}
// 触る: 書式
SHELF['doc.font'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody();
  var start = 0, end = body.getNumChildren();
  if (op.under) {
    var h = headingAt_(body, op.under);
    start = h.idx + 1;
    end = sectionEnd_(body, h);
  }
  var did = 0;
  var applyStyle_ = function (txt, s, e) {
    if (op.bold !== undefined) txt.setBold(s, e, !!op.bold);
    if (op.underline !== undefined) txt.setUnderline(s, e, !!op.underline);
    if (op.size !== undefined) txt.setFontSize(s, e, parseInt(op.size, 10));
    if (op.color) txt.setForegroundColor(s, e, rgb_(op.color));
    did++;
  };
  if (op.find) {
    var esc = String(op.find).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var r = body.findText(esc);
    while (r) {
      applyStyle_(r.getElement().asText(), r.getStartOffset(), r.getEndOffsetInclusive());
      r = body.findText(esc, r);
    }
  } else {
    for (var i = start; i < end; i++) {
      var ch = body.getChild(i);
      if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
        var t = ch.asParagraph().editAsText();
        if (t.getText().length) applyStyle_(t, 0, t.getText().length - 1);
      }
    }
  }
  chg_(ctx, null, (op.find ? '「' + op.find + '」' : '範囲'), '文字書式を変更');
});

// 棚: doc.align
// 題: 段落の配置や行間を変える
// 分類: 文書
// 語: 中央寄せ|右寄せ|左寄せ|行間を広げて|行間を狭めて|字下げ|インデント|題を中央に|タイトルを中央
// 違い: 文字フォントなら doc.font。文書全体なら doc.style
// 引数: heading=文字, under=文字, align=選択(left/center/right/justify), line_spacing=数, indent=数
// 頼み: align=center<中央寄せ|中央に|センター ; align=right<右寄せ|右揃え ; align=left<左寄せ ; line_spacing~行間\s*([0-9.]+)
// 例: 「題を中央にして」 → {"shelf":"doc.align","heading":"議事録","align":"center"}
// 触る: 書式
SHELF['doc.align'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody();
  var start = 0, end = body.getNumChildren();
  if (op.heading) {
    var h = headingAt_(body, op.heading);
    start = h.idx;
    end = h.idx + 1;
  } else if (op.under) {
    var uh = headingAt_(body, op.under);
    start = uh.idx + 1;
    end = sectionEnd_(body, uh);
  }
  var alignMap = {
    left: DocumentApp.HorizontalAlignment.LEFT,
    center: DocumentApp.HorizontalAlignment.CENTER,
    right: DocumentApp.HorizontalAlignment.RIGHT,
    justify: DocumentApp.HorizontalAlignment.JUSTIFY
  };
  for (var i = start; i < end; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.PARAGRAPH) {
      var p = ch.asParagraph();
      if (op.align && alignMap[op.align]) p.setAlignment(alignMap[op.align]);
      if (op.line_spacing !== undefined) p.setLineSpacing(Number(op.line_spacing));
      if (op.indent !== undefined) p.setIndentFirstLine(Number(op.indent));
    }
  }
  chg_(ctx, null, (op.heading ? '「' + op.heading + '」' : '段落'), '配置・行間を変更');
});

// 棚: doc.table.style
// 題: 文書の表の見た目を整える
// 分類: 文書
// 語: 表の見た目|表のヘッダーに色|表の見出しに色|表の背景色|表の枠線|表の罫線|表をきれいに
// 違い: 表の内容なら doc.table。行追加なら doc.table.row
// 引数: table=数, header_bg=色, header_color=色, borders=真偽
// 頼み: header_bg~見出しに([^\s]+)の背景 ; header_bg~見出しに([^\s]+)色
// 例: 「表の見出しに色を付けて」 → {"shelf":"doc.table.style","header_bg":"薄青"}
// 触る: 書式
SHELF['doc.table.style'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody(), n = body.getNumChildren(), tables = [];
  for (var i = 0; i < n; i++) {
    var ch = body.getChild(i);
    if (ch.getType() === DocumentApp.ElementType.TABLE) tables.push(ch.asTable());
  }
  if (!tables.length) throw new ArgError('文書内に表がありません');
  var tbl = tables[op.table ? (op.table - 1) : 0];
  var bg = op.header_bg || '#D9E2F3';
  var fg = op.header_color || '#000000';
  var hrow = tbl.getRow(0);
  for (var c = 0; c < hrow.getNumCells(); c++) {
    var cell = hrow.getCell(c);
    cell.setBackgroundColor(rgb_(bg));
    cell.editAsText().setForegroundColor(rgb_(fg)).setBold(true);
  }
  if (op.borders !== undefined) {
    tbl.setBorderWidth(op.borders ? 1 : 0);
  }
  chg_(ctx, null, '表', 'スタイル（見出し色・枠線）を適用');
});

// 棚: doc.pagebreak
// 題: 改ページを入れる・外す
// 分類: 文書
// 語: 改ページを入れて|ページを分けて|改ページを挿入|改ページを消して|ページ区切り
// 違い: ヘッダーやフッターなら doc.header
// 引数: heading=文字, under=文字, action=選択(insert/remove)=insert
// 頼み: action=remove<改ページを消 ; heading~([^\s]+)の前で改ページ
// 例: 「議事の前で改ページして」 → {"shelf":"doc.pagebreak","heading":"議事"}
// 触る: 書式
SHELF['doc.pagebreak'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody();
  var act = op.action || 'insert';
  if (act === 'remove') {
    var removed = 0;
    for (var i = body.getNumChildren() - 1; i >= 0; i--) {
      var ch = body.getChild(i);
      if (ch.getType() === DocumentApp.ElementType.PAGE_BREAK) {
        body.removeChild(ch);
        removed++;
      }
    }
    chg_(ctx, null, '文書', '改ページを解除（' + removed + ' か所）');
  } else {
    var idx = body.getNumChildren();
    if (op.heading) {
      var h = headingAt_(body, op.heading);
      idx = h.idx;
    } else if (op.under) {
      var uh = headingAt_(body, op.under);
      idx = sectionEnd_(body, uh);
    }
    body.insertPageBreak(idx);
    chg_(ctx, null, (op.heading ? '「' + op.heading + '」の手前' : '位置 ' + idx), '改ページを挿入');
  }
});

// 棚: doc.header
// 題: ヘッダーやフッターを設定する
// 分類: 文書
// 語: ヘッダーを入れて|フッターに|ページ番号を入れて|ヘッダーを設定|フッターを設定|ページ番号|ヘッダーに
// 違い: 文書本文なら doc.new / doc.append
// 引数: header=文字, footer=文字, page_number=真偽
// 頼み: page_number=true<ページ番号 ; header~ヘッダーに[『「]([^』」]+)[』」] ; footer~フッターに[『「]([^』」]+)[』」]
// 例: 「フッターにページ番号を入れて」 → {"shelf":"doc.header","page_number":true}
// 触る: 書式
SHELF['doc.header'] = docKind_(function (ctx, op) {
  var doc = ctx.doc;
  if (op.header) {
    var hdr = doc.getHeader() || doc.addHeader();
    hdr.clear();
    hdr.appendParagraph(String(op.header));
  }
  if (op.footer || op.page_number) {
    var ftr = doc.getFooter() || doc.addFooter();
    ftr.clear();
    var p = ftr.appendParagraph(op.footer ? String(op.footer) + ' ' : '');
    if (op.page_number) {
      p.appendPageNumber();
    }
    p.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
  }
  chg_(ctx, null, 'ヘッダー・フッター', '設定を更新');
});

// 棚: doc.toc
// 題: 目次（TOC）を入れる
// 分類: 文書
// 語: 目次を入れて|目次を作成|目次を付けて|目次を挿入|TOCを入れて|目次を追加|目次を更新|目次を最新|アウトライン 目次
// 違い: 章立てを見るだけなら doc.outline
// 引数: at=選択(top/under)=top, under=文字
// 例: 「目次を付けて」 → {"shelf":"doc.toc"}
// 触る: 値 書式
SHELF['doc.toc'] = docKind_(function (ctx, op) {
  var body = ctx.doc.getBody();
  var idx = 0;
  if (op.under) {
    var h = headingAt_(body, op.under);
    idx = h.idx + 1;
  }
  var pars = body.getParagraphs(), headings = [];
  for (var i = 0; i < pars.length; i++) {
    var hd = pars[i].getHeading();
    if (hd !== DocumentApp.ParagraphHeading.NORMAL) {
      headings.push({ text: pars[i].getText(), level: hd });
    }
  }
  var pTitle = body.insertParagraph(idx, '【目次】');
  pTitle.setHeading(DocumentApp.ParagraphHeading.HEADING2);
  var inserted = 1;
  for (var j = 0; j < headings.length; j++) {
    var indent = headings[j].level === DocumentApp.ParagraphHeading.HEADING3 ? '    - ' : '・ ';
    body.insertParagraph(idx + inserted, indent + headings[j].text);
    inserted++;
  }
  chg_(ctx, null, '位置 ' + idx, '目次（見出し ' + headings.length + ' 件）を挿入');
});

// 棚: doc.link
// 題: 文書中の言葉にリンクを付ける
// 分類: 文書
// 語: リンクを付けて|URLを貼って|リンクを設定|リンクを外して|ハイパーリンク
// 違い: 文字置換なら doc.replace
// 引数: text*=文字, url=文字
// 頼み: text~[『「]([^』」]+)[』」]という言葉にリンク ; url~[『「](https?://[^』」]+)[』」] ; url~(https?://[^\s]+)
// 例: 「資料という言葉にリンクを付けて」 → {"shelf":"doc.link","text":"資料","url":"https://example.com"}
// 触る: 書式
SHELF['doc.link'] = docKind_(function (ctx, op) {
  need_(op, ['text']);
  var body = ctx.doc.getBody(), findStr = String(op.text);
  var esc = findStr.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var r = body.findText(esc), count = 0;
  var url = op.url ? String(op.url) : null;
  while (r) {
    var txt = r.getElement().asText();
    txt.setLinkUrl(r.getStartOffset(), r.getEndOffsetInclusive(), url);
    count++;
    r = body.findText(esc, r);
  }
  if (!count) throw new ArgError('「' + findStr + '」は見つかりませんでした');
  chg_(ctx, null, '「' + findStr + '」', count + ' か所にリンクを' + (url ? '設定' : '解除'));
});

// 棚: doc.from.sheet
// 題: スプレッドシートの表を文書に入れる
// 分類: 文書
// 語: スプレッドシートの表を入れて|シートの表を文書に|売上の表を報告書に入れて|表を差し込んで|シートから表を|スプレッドシート 表 差し込み|シート 表 挿入 ドキュメント
// 違い: 手動で表を作るなら doc.table
// 引数: sheet_name=文字, sheet_id=文字, range=範囲, under=文字
// 頼み: sheet_name~([^\s]+)の表を ; under~[『「]([^』」]+)[』」]の下
// 例: 「売上の表を報告書に入れて」 → {"shelf":"doc.from.sheet","sheet_name":"売上"}
// 触る: 値 書式
SHELF['doc.from.sheet'] = docKind_(function (ctx, op) {
  var ss = op.sheet_id ? SpreadsheetApp.openById(op.sheet_id) : (ctx.ss || null);
  if (!ss) {
    var files = DriveApp.getFilesByName(op.sheet_name ? ('WS試験_' + op.sheet_name) : 'WS試験_150_グラフ2本');
    if (files.hasNext()) ss = SpreadsheetApp.open(files.next());
  }
  if (!ss) throw new ArgError('参照元のスプレッドシートが見つかりません');
  var sh = op.sheet_name ? ss.getSheetByName(op.sheet_name) : ss.getSheets()[0];
  if (!sh) throw new ArgError('シート「' + op.sheet_name + '」が見つかりません');
  var rg = op.range ? sh.getRange(op.range) : sh.getDataRange();
  var vals = rg.getDisplayValues();
  if (!vals.length) throw new ArgError('シートの表にデータがありません');
  var body = ctx.doc.getBody();
  var idx = body.getNumChildren();
  if (op.under) {
    var h = headingAt_(body, op.under);
    idx = h.idx + 1;
  }
  var tbl = body.insertTable(idx, vals);
  styleTable_(tbl);
  chg_(ctx, null, (op.under ? '「' + op.under + '」の下' : '末尾'), 'シート「' + sh.getName() + '」の表（' + vals.length + '行×' + vals[0].length + '列）を挿入');
});

// 棚: doc.template
// 題: ひな形から新しい文書を作成する
// 分類: 文書
// 語: ひな形から作|テンプレートから作成|差し込み文書|ひな形を埋めて|テンプレートを埋めて|ひな形文書の|テンプレートの変数を差し替え
// 違い: 元の文書を置換するなら doc.replace。複製だけなら doc.copy
// 引数: vars*=対応, title=文字
// 例: 「この見積のひな形に宛名を入れて作って」 → {"shelf":"doc.template","vars":{"宛名":"山田様"}}
// 触る: シート構成
SHELF['doc.template'] = docKind_(function (ctx, op) {
  need_(op, ['vars']);
  var doc = ctx.doc;
  var title = op.title || ('WS試験_' + doc.getName().replace(/^WS試験_/, '') + '_作成');
  if (title.indexOf('WS試験_') !== 0) title = 'WS試験_' + title;
  var newDoc = DocumentApp.create(title);
  var srcBody = doc.getBody(), dstBody = newDoc.getBody();
  for (var i = 0; i < srcBody.getNumChildren(); i++) {
    var elem = srcBody.getChild(i).copy();
    var type = elem.getType();
    if (type === DocumentApp.ElementType.PARAGRAPH) dstBody.appendParagraph(elem);
    else if (type === DocumentApp.ElementType.TABLE) dstBody.appendTable(elem);
    else if (type === DocumentApp.ElementType.LIST_ITEM) dstBody.appendListItem(elem);
  }
  if (dstBody.getNumChildren() > 1 && dstBody.getChild(0).getText() === '') {
    dstBody.removeChild(dstBody.getChild(0));
  }
  var vars = op.vars || {};
  Object.keys(vars).forEach(function (k) {
    dstBody.replaceText('\\{\\{' + k + '\\}\\}', String(vars[k]));
  });
  newDoc.saveAndClose();
  note_(ctx, '作成した文書: ' + title + ' (ID: ' + newDoc.getId() + ')');
  chg_(ctx, null, title, 'ひな形から新規文書を作成（ID: ' + newDoc.getId() + '）');
});

// 棚: doc.copy
// 題: 文書を複製する
// 分類: 文書
// 語: 文書を複製|文書をコピー|議事録を写して|ドキュメントを複製|文書の写し
// 違い: ひな形を埋めるなら doc.template。シートの複製なら sheet.copy
// 引数: title=文字
// 頼み: title~[『「]([^』」]+)[』」]という名前で複製 ; title~写して[『「]?([^』」\s]+?)[』」]?を作
// 例: 「この議事録を写して来月分を作って」 → {"shelf":"doc.copy","title":"来月分議事録"}
// 触る: シート構成
SHELF['doc.copy'] = docKind_(function (ctx, op) {
  var doc = ctx.doc;
  var title = op.title || ('WS試験_' + doc.getName().replace(/^WS試験_/, '') + '_コピー');
  if (title.indexOf('WS試験_') !== 0) title = 'WS試験_' + title;
  var newDoc = DocumentApp.create(title);
  var srcBody = doc.getBody(), dstBody = newDoc.getBody();
  for (var i = 0; i < srcBody.getNumChildren(); i++) {
    var elem = srcBody.getChild(i).copy();
    var type = elem.getType();
    if (type === DocumentApp.ElementType.PARAGRAPH) dstBody.appendParagraph(elem);
    else if (type === DocumentApp.ElementType.TABLE) dstBody.appendTable(elem);
    else if (type === DocumentApp.ElementType.LIST_ITEM) dstBody.appendListItem(elem);
  }
  if (dstBody.getNumChildren() > 1 && dstBody.getChild(0).getText() === '') {
    dstBody.removeChild(dstBody.getChild(0));
  }
  newDoc.saveAndClose();
  note_(ctx, '複製した文書: ' + title + ' (ID: ' + newDoc.getId() + ')');
  chg_(ctx, null, title, '文書を複製（ID: ' + newDoc.getId() + '）');
});

// 棚: doc.export.pdf
// 題: 文書をPDFにして保存する
// 分類: 文書
// 語: 文書をPDF|ドキュメントをPDF|PDFに書き出|PDF化して|PDF保存|PDFを作成
// 違い: スプレッドシートのPDF化は export.pdf。文書の複製は doc.copy
// 引数: name=文字, folder=文字
// 頼み: folder~[「『"“]([^」』"”]+)[」』"”]フォルダ
// 例: 「この文書をPDFにして保存して」 → {"shelf":"doc.export.pdf"}
// 例: 「この見積書を「見積書_山田様.pdf」としてPDF書き出しして」 → {"shelf":"doc.export.pdf","name":"見積書_山田様.pdf"}
// 触る: なし
SHELF['doc.export.pdf'] = docKind_(function (ctx, op) {
  var doc = ctx.doc;
  var docId = doc.getId();
  var docName = doc.getName();
  doc.saveAndClose();
  var fileName = String(op.name || (docName + '.pdf')).trim();
  if (!/\.pdf$/i.test(fileName)) fileName += '.pdf';
  var blob = DriveApp.getFileById(docId).getAs('application/pdf').setName(fileName);
  var destFolder = op.folder ? resolveFolder_(op.folder, true).folder : null;
  var pdfFile = destFolder ? destFolder.createFile(blob) : DriveApp.createFile(blob);
  note_(ctx, 'PDF保存完了: ' + pdfFile.getName() + '\nID: ' + pdfFile.getId() + '\nURL: ' + pdfFile.getUrl());
  chg_(ctx, null, fileName, '文書をPDF保存（ID: ' + pdfFile.getId() + '）');
});
