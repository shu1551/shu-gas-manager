// 見た目の棚

// 棚: format
// 題: 範囲の書式を変える
// 分類: 見た目
// 語: 書式を|太字に|斜体に|太字を|斜体を|太字を外|斜体を外|太字を解除|斜体を解除|折り返しを解除|折り返さ|はみ出|色を付け|色を変え|色に変え|色にして|背景色|背景を|文字の色|文字色|フォントの色|フォント色|フォントを|文字サイズ|フォントサイズ|大きくして|小さくして|表示に|中央揃え|右揃え|左揃え|中央寄せ|右寄せ|左寄せ|桁区切り|桁区切りに|カンマ区切り|罫線|罫線を引|罫線を消|罫線をつけ|罫線を付け|外枠|外枠だけ|外枠を|結合解除|結合を解除|マージ|折り返し|赤く|青く|黄色く|緑に|赤にして|青にして|黄色にして|緑にして|黒にして|白にして|水色にして|紺にして|赤に変え|青に変え|黄色に変え|緑に変え|黒に変え|白に変え|水色に変え|紺に変え|グレーに変え|オレンジに変え|ピンクに変え|紫に変え|見出しの行|見出しを|黄色の背景|青い背景|薄い青色|色も付けて|を結合して|セルを結合|セルの結合|に罫線を引|表に罫線|曜日も出|曜日を出|曜日付き|曜日つき|表示形式|日付の表示|日付の見せ方|年月日の形|年月日形式|年月日に|時刻の表示|時刻を|hh:mm|yyyy/mm/dd|yyyy-mm-dd|桁区切|カンマ|パーセント|円マーク|円表示|通貨形式|数値形式|数値標準|標準形式|標準に戻|白文字|黒文字|赤文字|青文字|緑文字|黄文字|紫文字|灰文字|橙文字
// 違い: 「〜の列」は範囲を切らず col:"列名" で渡す。条件付きは cf.add、1行おきは banding.add
// 引数: range=範囲, col=列, header=真偽, title=真偽, bold=真偽, italic=真偽, color=色, bg=色, size=数, size_delta=数, font=文字, number_format=文字, align=文字, valign=文字, wrap=真偽, borders=文字, merge=真偽
// 頼み: bold=false<太字を解除|太字解除|太字を外|太字をやめ|太字をなく|太字じゃなく|太字でなく|太字を戻 ; bold=true<太字|太く ; italic=false<斜体を解除|斜体解除|斜体を外|斜体をやめ|斜体をなく|イタリックを解除|イタリックを外 ; italic=true<斜体|イタリック ; header=true<見出し|ヘッダ ; title=true<タイトル|表題 ; number_format=yyyy/mm/dd(ddd)<年月日と曜日|年付きの曜日 ; number_format=m"月"d"日"(ddd)<曜日も|曜日を出|曜日付き|曜日つき|曜日入り ; number_format=hh:mm<HH:mm|09:00|2桁の時刻|時刻を2桁|時刻形式|時分 ; number_format=yyyy-mm-dd<yyyy-mm-dd ; number_format=yyyy/mm/dd<yyyy/MM/dd|2026/11/04|スラッシュの日付|年/月/日|年月日の形|年月日形式|年月日の形式|年月日に ; number_format=0.0%<パーセント|%表示 ; number_format=General<数値(標準)|標準形式|表示形式を標準|標準に戻 ; number_format=¥#,##0<円マーク|¥|円表示|通貨形式 ; number_format=#,##0<カンマ|桁区切り|3桁 ; wrap=false<折り返しを解除|折り返し解除|折り返しをやめ|折り返さな|折り返しを外|折り返しなし|折り返しを消|はみ出 ; wrap=true<折り返 ; align=center<中央寄せ|中央揃え|中央に|真ん中に|真ん中寄せ|真ん中揃え ; align=left<左寄せ|左揃え ; align=right<右寄せ|右揃え ; borders=false<罫線なし|罫線を消|罫線を削除|罫線解除|枠線なし|枠線を消|枠線解除 ; borders=outer<外枠|外罫線 ; borders=true<罫線を引|罫線をつけ|罫線を付け|罫線で囲|枠線を引|枠線をつけ|枠線を付け|罫線|格子 ; merge=false<結合解除|結合を解除|結合を外|結合を消|マージ解除 ; merge=true<結合|マージ ; size~([0-9]+)\s*(?:pt|ポイント) ; font~(?:フォント|書体)を[『「]?([^』」、。にへ]+?)[』」]?(?:に|へ)
// どれか: range col header title
// 例: 「見出しを太字で青い背景に」 → {"shelf":"format","header":true,"bold":true,"bg":"#1F4E79","color":"#FFFFFF"}
// 例: 「金額の列を桁区切りに」 → {"shelf":"format","col":"金額","number_format":"#,##0"}
// 触る: 書式
SHELF['format'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = null, rg;
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, t.headerRows || 1, t.lastCol - t.firstCol + 1); }
  else if (op.title) { rg = titleRange_(sh); }
  else if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, (t.totalRow || t.lastData) - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「format」に range・col・header・title のどれかが要ります');
  // タイトルが 1 つのセル（結合なし）なら、表の幅いっぱいの帯に塗る。帯の中で中央・右に寄せると A 列の中で切れて読めない＝寄せは左のまま
  var titleBand = false;
  if (op.title && op.merge === undefined && typeof rg.getNumRows === 'function' && rg.getNumRows() === 1 && !(typeof rg.isPartOfMerge === 'function' && rg.isPartOfMerge())) {
    var tt = findTable_(sh);
    if (tt && tt.lastCol > rg.getColumn()) {
      var c0 = Math.min(rg.getColumn(), tt.firstCol);
      var rowVals = (tt.vals && tt.vals[rg.getRow() - 1])
        ? tt.vals[rg.getRow() - 1].slice(c0 - 1, tt.lastCol)
        : sh.getRange(rg.getRow(), c0, 1, tt.lastCol - c0 + 1).getValues()[0];
      if (rowVals.filter(function (v) { return !isBlank_(v); }).length <= 1) {
        rg = sh.getRange(rg.getRow(), c0, 1, tt.lastCol - c0 + 1);
        titleBand = true;
      }
    }
  }
  var did = [];
  var set = function (key, fn) { if (op[key] !== undefined) { fn(op[key]); did.push(key); } };
  if (titleBand && (op.align === 'center' || op.align === 'right')) op = Object.assign({}, op, { align: 'left' });
  set('bold', function (v) { rg.setFontWeight(v ? 'bold' : 'normal'); });
  set('italic', function (v) { rg.setFontStyle(v ? 'italic' : 'normal'); });
  set('color', function (v) { rg.setFontColor(rgb_(v)); });
  set('bg', function (v) { rg.setBackground(rgb_(v)); });
  set('size', function (v) { rg.setFontSize(v); });
  set('size_delta', function (v) {
    var d = Number(v);
    if (!d) return;
    var cur = rg.getFontSizes();
    var next = cur.map(function (row) {
      return row.map(function (s) { return Math.max(6, Math.min(72, (Number(s) || 10) + d)); });
    });
    rg.setFontSizes(next);
  });
  set('font', function (v) { rg.setFontFamily(v); });
  set('number_format', function (v) { rg.setNumberFormat(v); });
  set('align', function (v) { rg.setHorizontalAlignment(v); });
  set('valign', function (v) { rg.setVerticalAlignment(v); });
  set('wrap', function (v) { rg.setWrap(!!v); });
  set('borders', function (v) { var bOff = (v === false || v === 'none' || v === 'なし'); if (!bOff) rg.setBorder(true, true, true, true, v === 'outer' ? false : true, v === 'outer' ? false : true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID); else rg.setBorder(false, false, false, false, false, false); });
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
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, t.headerRows || 1, t.lastCol - t.firstCol + 1); }
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
// 引数: cols=対応, col=列, width=数, rows=対応, auto=列[], all_sheets=真偽=false, auto_rows=真偽=false
// 頼み: width~(?:幅を?|横幅を?)\s*([0-9]+) ; all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体 ; auto_rows=true<行の高さを自動|行の高さも自動|行高を自動|行の高さ自動|行の高さを中身|行も自動
// どれか: cols col rows auto all_sheets auto_rows
// 例: 「A列を幅200にして」 → {"shelf":"width","col":"A","width":200}
// 例: 「B列とC列の幅を中身に合わせて」 → {"shelf":"width","auto":["B","C"]}
// 触る: 幅
SHELF['width'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = findTable_(sh), did = [];
  var colRef = function (k) { return t ? colIndexOf_(t, k) : colNum_(k); };
  if (op.cols) Object.keys(op.cols).forEach(function (k) { sh.setColumnWidth(colRef(k), op.cols[k]); did.push(k + '列'); });
  if (op.col && op.width) { sh.setColumnWidth(colRef(op.col), op.width); did.push(op.col + '列'); }
  if (op.rows) Object.keys(op.rows).forEach(function (k) { sh.setRowHeight(parseInt(k), op.rows[k]); did.push(k + '行'); });
  var canBatchW = typeof Sheets !== 'undefined' && Sheets.Spreadsheets && typeof Sheets.Spreadsheets.batchUpdate === 'function' && typeof batchRetry_ === 'function';
  var widthReqs = [], widthFallbacks = [];
  var autoList = Array.isArray(op.auto) ? op.auto : (op.auto ? [op.auto] : []);
  if (autoList.length) {
    var flSpanW = (typeof filterSpanOf_ === 'function') ? filterSpanOf_(sh) : null;
    var lrW = sh.getLastRow();
    var shIdW = sh.getSheetId();
    var autoCis = autoList.map(function (k) { return { k: k, ci: colRef(k) }; });
    var minCi = Infinity, maxCi = 0;
    autoCis.forEach(function (a) { if (a.ci < minCi) minCi = a.ci; if (a.ci > maxCi) maxCi = a.ci; });
    var dispW = (lrW > 0 && maxCi >= minCi) ? sh.getRange(1, minCi, lrW, maxCi - minCi + 1).getDisplayValues() : [];
    autoCis.forEach(function (a) {
      var ci = a.ci, off = ci - minCi, mx = 0;
      for (var rw = 0; rw < dispW.length; rw++) mx = Math.max(mx, wlen_(dispW[rw][off]));
      var wantW = mx * STYLE.px + STYLE.pad;
      if (flSpanW && flSpanW.row >= 1 && flSpanW.row <= dispW.length && ci >= flSpanW.c1 && ci <= flSpanW.c2) {
        wantW = Math.max(wantW, wlen_(dispW[flSpanW.row - 1][off]) * STYLE.px + STYLE.pad + 42);
      }
      var pxW = Math.max(STYLE.colMin, Math.min(STYLE.colMax, wantW));
      if (canBatchW) {
        widthReqs.push({ updateDimensionProperties: { range: { sheetId: shIdW, dimension: 'COLUMNS', startIndex: ci - 1, endIndex: ci }, properties: { pixelSize: pxW }, fields: 'pixelSize' } });
        widthFallbacks.push({ s: sh, ci: ci, px: pxW });
      } else {
        sh.setColumnWidth(ci, pxW);
      }
      did.push(a.k + '列(自動)');
    });
  }
  if (widthReqs.length) {
    try { batchRetry_(ctx.ss, widthReqs); }
    catch (eBw) { widthFallbacks.forEach(function (u) { u.s.setColumnWidth(u.ci, u.px); }); }
  }
  if (op.auto_rows && !op.all_sheets) {
    var lr0 = sh.getLastRow();
    if (lr0 > 0 && typeof sh.autoResizeRows === 'function') {
      sh.autoResizeRows(1, lr0);
      did.push('全行の高さ(自動)');
    }
  }
  if (op.all_sheets) {
    var sCnt = 0, allReqs = [], allFb = [];
    ctx.ss.getSheets().forEach(function (s) {
      if (s.getName() === '_GASクイックの控え' || s.isSheetHidden()) return;
      var lrA = s.getLastRow(), lcA = s.getLastColumn();
      if (lrA > 0 && lcA > 0) {
        var dA = s.getRange(1, 1, lrA, lcA).getDisplayValues();
        var flA = (typeof filterSpanOf_ === 'function') ? filterSpanOf_(s) : null;
        var sIdA = s.getSheetId();
        for (var cA = 0; cA < lcA; cA++) {
          var mxA = 0;
          for (var rA = 0; rA < lrA; rA++) mxA = Math.max(mxA, wlen_(dA[rA][cA]));
          var wantA = mxA * STYLE.px + STYLE.pad;
          if (flA && flA.row >= 1 && flA.row <= lrA && (cA + 1) >= flA.c1 && (cA + 1) <= flA.c2) {
            wantA = Math.max(wantA, wlen_(dA[flA.row - 1][cA]) * STYLE.px + STYLE.pad + 42);
          }
          var pxA = Math.max(STYLE.colMin, Math.min(STYLE.colMax, wantA));
          if (canBatchW) {
            allReqs.push({ updateDimensionProperties: { range: { sheetId: sIdA, dimension: 'COLUMNS', startIndex: cA, endIndex: cA + 1 }, properties: { pixelSize: pxA }, fields: 'pixelSize' } });
            allFb.push({ s: s, ci: cA + 1, px: pxA });
          } else {
            s.setColumnWidth(cA + 1, pxA);
          }
        }
        if (op.auto_rows && typeof s.autoResizeRows === 'function') s.autoResizeRows(1, lrA);
      }
      sCnt++;
    });
    if (allReqs.length) {
      try { batchRetry_(ctx.ss, allReqs); }
      catch (eBa) { allFb.forEach(function (u) { u.s.setColumnWidth(u.ci, u.px); }); }
    }
    did.push('全' + sCnt + 'シート列幅' + (op.auto_rows ? '・行高' : '') + '(自動)');
    chg_(ctx, null, did.join('・'), '幅・高さを変更');
    return;
  }
  if (!did.length) throw new ArgError('棚「width」に cols・rows・auto・all_sheets・auto_rows のどれかが要ります');
  chg_(ctx, sh, did.join('・'), '幅・高さを変更');
};
DYNAMIC['width'] = {
  touch: function () { return ['幅']; },
  sheets: function (ctx, op) {
    if (op.all_sheets) {
      return ctx.ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え' && !s.isSheetHidden(); }).map(function (s) { return s.getName(); });
    }
    return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()];
  }
};

// 棚: cf.add
// 題: 条件付き書式を付ける
// 分類: 見た目
// 語: 条件付き書式|以上なら|以下なら|未満は|のとき色|入ってい|を目立たせ|自動で色|未満は黄色|未満なら|以上は|以下は|より大きい|より小さい|より前|より後|以前|以降|行全体|の行を赤|の行を黄|の行を青|の行を緑|の行を薄|の行に色|の行を目立|以上のセル|以下のセル|未満のセル|より大きいセル|より小さいセル
// 違い: いつも同じ色なら format
// 引数: range*=範囲, when*=選択(gt/ge/lt/le/eq/ne/between/contains/blank/notblank/formula), value=文字, bg=色, color=色, bold=真偽
// 頼み: bold=true<太字|太く ; when=ge<以上 ; when=le<以下 ; when=lt<未満|より小さい|より少ない|マイナス|下回る|下回っ|届かない|届いていない|届いてない ; when=gt<より大きい|を超え|超える|より多い|上回る|上回っ ; when=ne<以外|ではない|でない|じゃない|になっていない|になってない ; when=contains<が入っている|を含む|が含まれ|と書かれ|が書かれ|と記載|とある ; when=blank<空欄のセル|空白のセル ; value~([0-9][0-9,\.]*%?[万億]?)(?:円|個|件|人|時間|点)?(?:以上|以下|未満|より|(?:を)?超|(?:を)?上回|(?:を)?下回|(?:に)?届か|(?:に)?届いてい?ない) ; value~[『「]([^』」]+)[』」]
// 例: 「売上が100万以上のセルを赤く」 → {"shelf":"cf.add","range":"F2:F100","when":"ge","value":"1000000","bg":"赤"}
// 例: 「売上が100万以上の行を目立たせて」 → {"shelf":"cf.add","range":"A2:F100","when":"formula","value":"=$F2>=1000000","bg":"薄赤"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.add'] = function (ctx, op) {
  need_(op, ['range', 'when']);
  var sh = sheetCtx_(ctx, op), rg = sh.getRange(op.range);
  var rule = SpreadsheetApp.newConditionalFormatRule().setRanges([rg]);
  var w = String(op.when).toLowerCase(), val = op.value !== undefined ? String(op.value) : '';
  var cfCellA1 = a1_(rg.getRow(), rg.getColumn());
  var cfClean = val.replace(/,/g, '').trim();
  var isNumVal = cfClean !== '' && isFinite(Number(cfClean));
  var cfYear = (typeof inferColDateYear_ === 'function') ? inferColDateYear_(rg.getValues(), 0) : new Date().getFullYear();
  var dRange = (w === 'between' && typeof parseCmpDateRange_ === 'function') ? parseCmpDateRange_(val, cfYear) : null;
  var dSingle = (!isNumVal && (w === 'gt' || w === 'ge' || w === 'lt' || w === 'le' || w === 'eq' || w === 'ne') && typeof parseCmpDate_ === 'function')
    ? parseCmpDate_(val, cfYear) : null;
  var dateExpr = function (d) { return 'DATE(' + d.y + ',' + d.m + ',' + d.d + ')'; };
  if (w === 'between' && dRange) {
    rule.whenFormulaSatisfied('=AND(ISNUMBER(' + cfCellA1 + '),' + cfCellA1 + '>=' + dateExpr(dRange[0]) + ',' + cfCellA1 + '<=' + dateExpr(dRange[1]) + ')');
  } else if (dSingle) {
    var opMapCf = { gt: '>', ge: '>=', lt: '<', le: '<=', eq: '=', ne: '<>' };
    rule.whenFormulaSatisfied('=AND(ISNUMBER(' + cfCellA1 + '),' + cfCellA1 + opMapCf[w] + dateExpr(dSingle) + ')');
  } else if (w === 'gt') rule.whenNumberGreaterThan(Number(val));
  else if (w === 'ge') rule.whenNumberGreaterThanOrEqualTo(Number(val));
  else if (w === 'lt') rule.whenNumberLessThan(Number(val));
  else if (w === 'le') rule.whenNumberLessThanOrEqualTo(Number(val));
  else if (w === 'eq') {
    if (isNumVal) rule.whenNumberEqualTo(Number(cfClean));
    else rule.whenTextEqualTo(val);
  } else if (w === 'ne') {
    if (isNumVal) rule.whenNumberNotEqualTo(Number(cfClean));
    else rule.whenFormulaSatisfied('=' + cfCellA1 + '<>"' + val.replace(/"/g, '""') + '"');
  }
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
// 語: 重複に色|重複を赤|重複を黄色|重複に印|ダブりに色|重複を目立|重複をハイライト|重複してるとこ|ダブっている|ダブっている行に色|ダブってる行をハイライト|重複行をハイライト
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
// 語: 条件付き書式を消|条件付き書式を全部消|条件付き書式を外|条件付き書式を削除|自動の色を消|条件付き書式をクリア|条件付き書式を外して|自動でついた色を消
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
// 語: 条件付き書式を一覧|条件付き書式を調べ|条件付き書式はどこ|条件付き書式を確認|条件付き書式を教え|設定されている条件付き書式
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
// 語: 交互の背景色|交互の背景色を|交互に背景色|交互の色|交互に色|しましま|縞模様|1行おきに色|ストライプ|1行おきに薄い|1行おきの背景色
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
// 語: 交互の背景色を消して|交互の背景色を消|交互の背景色を解除|交互の背景を消|交互の色を外|交互の色を消|しましまを消|しましまを外|縞模様を消|縞模様を外|ストライプを解除|縞模様を解除|ストライプを消|1行おきの色を消|1行おきのしましまを消|1行おきのしましまを外|1行おきについてる色|ついてる色を外|縞模様のストライプを解除|交互の色を解除|ストライプを外|交互の色 解除
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

// 棚: sheet.gridlines
// 題: 枠線（グリッド線）を表示・非表示
// 分類: 見た目
// 語: 枠線を非表示|枠線を表示|グリッド線を消|グリッド線を非表示|グリッド線を表示|グリッド線を出|目盛り線を消|目盛り線を表示|目盛り線を非表示|シートの枠線を消
// 違い: セル範囲の罫線なら format（borders）、印刷時の枠線設定は print.setup
// 引数: show=真偽, all_sheets=真偽=false
// 頼み: show=false<非表示|消して|消す|隠|オフ|OFF|なし|無く ; show=true<表示|出して|出す|オン|ON|戻 ; all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体
// 例: 「グリッド線を非表示にして」 → {"shelf":"sheet.gridlines","show":false}
// 例: 「全シートの枠線を非表示にして」 → {"shelf":"sheet.gridlines","show":false,"all_sheets":true}
// 触る: 書式
// 控え: 今
SHELF['sheet.gridlines'] = function (ctx, op) {
  var ss = ctx.ss;
  var targets = op.all_sheets
    ? ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; })
    : [sheetCtx_(ctx, op)];
  var labels = [];
  targets.forEach(function (s) {
    var nextShow = op.show === undefined ? s.isGridlinesHidden() : !!op.show;
    s.setHiddenGridlines(!nextShow);
    labels.push(s.getName() + ':' + (nextShow ? '表示' : '非表示'));
  });
  chg_(ctx, op.all_sheets ? null : targets[0], '', '枠線（グリッド線）を切り替え（' + labels.slice(0, 4).join('・') + (labels.length > 4 ? ' ほか' : '') + '）');
};
DYNAMIC['sheet.gridlines'] = {
  touch: function () { return ['書式']; },
  sheets: function (ctx, op) {
    if (op.all_sheets) {
      return ctx.ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; }).map(function (s) { return s.getName(); });
    }
    return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()];
  }
};

// 棚: cf.weekend
// 題: 日付列の土日行に自動で色を付ける
// 分類: 見た目
// 語: 土日に色|土日の行|週末に色|カレンダーの色|土曜と日曜|土日を色分け|土日行に色|曜日で色分け
// 違い: 数値の大小などの条件付き書式なら cf.add
// 引数: col=列, sat_bg=色=#E8F0FE, sun_bg=色=#FCE8E6
// 例: 「日付列を見て土日の行に自動で色を付けて」 → {"shelf":"cf.weekend"}
// 触る: 条件付き
// 控え: 今
SHELF['cf.weekend'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var ci = 0;
  if (op.col) {
    ci = colIndexOf_(t, op.col);
  } else {
    for (var c = t.firstCol; c <= t.lastCol; c++) {
      for (var r = t.firstData; r <= t.lastData; r++) {
        var v = t.vals[r - 1][c - 1];
        if (v instanceof Date || Object.prototype.toString.call(v) === '[object Date]') { ci = c; break; }
      }
      if (ci) break;
    }
    if (!ci) ci = t.firstCol;
  }
  var nr = Math.max(1, t.lastData - t.firstData + 1);
  var rg = sh.getRange(t.firstData, t.firstCol, nr, t.lastCol - t.firstCol + 1);
  var cellRef = '$' + colLetter_(ci) + t.firstData;
  var satBg = rgb_(op.sat_bg || '#E8F0FE');
  var sunBg = rgb_(op.sun_bg || '#FCE8E6');
  var rSat = SpreadsheetApp.newConditionalFormatRule().setRanges([rg])
    .whenFormulaSatisfied('=AND(' + cellRef + '<>"",WEEKDAY(' + cellRef + ')=7)')
    .setBackground(satBg).build();
  var rSun = SpreadsheetApp.newConditionalFormatRule().setRanges([rg])
    .whenFormulaSatisfied('=AND(' + cellRef + '<>"",WEEKDAY(' + cellRef + ')=1)')
    .setBackground(sunBg).build();
  var rules = sh.getConditionalFormatRules();
  rules.push(rSat, rSun);
  sh.setConditionalFormatRules(rules);
  chg_(ctx, sh, rg.getA1Notation(), colLetter_(ci) + '列の土日行に色分け条件付き書式を設定');
};

// 棚: format.negred
// 題: マイナス数値を赤字表示・単位表示に整える
// 分類: 見た目
// 語: マイナスを赤|赤字表示|負の数を赤|三角表記|千円表示|百万円表示|マイナス赤|数値の表示形式
// 違い: 一般的な文字色や太字変更なら format
// 引数: col=列, range=範囲, unit=選択(none/yen/thousand/million)=none, triangle=真偽=false
// 頼み: unit=thousand<千円|千単位 ; unit=million<百万|百万円 ; unit=yen<円マーク|通貨 ; triangle=true<三角|白三角|黒三角
// 例: 「金額列をマイナス赤字の表示にして」 → {"shelf":"format.negred","col":"金額"}
// 触る: 書式
// 控え: 今
SHELF['format.negred'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  var unit = String(op.unit || 'none').toLowerCase();
  var base = unit === 'yen' ? '¥#,##0' : unit === 'thousand' ? '#,##0,' : unit === 'million' ? '#,##0,,' : '#,##0';
  var neg = (op.triangle ? '"▲"' : '-') + base;
  var fmt = base + ';[Red]' + neg;
  var ranges = [];
  if (op.col) {
    var t = needTable_(sh), ci = colIndexOf_(t, op.col);
    ranges.push(sh.getRange(t.firstData, ci, Math.max(1, (t.totalRow || t.lastData) - t.firstData + 1), 1));
  } else if (op.range) {
    ranges.push(sh.getRange(op.range));
  } else {
    var t2 = needTable_(sh), rows = Math.max(1, (t2.totalRow || t2.lastData) - t2.firstData + 1);
    for (var c = t2.firstCol; c <= t2.lastCol; c++) {
      if (!isNoCol_(t2, c) && isNumberCol_(t2, c)) {
        ranges.push(sh.getRange(t2.firstData, c, rows, 1));
      }
    }
    if (!ranges.length) throw new ArgError('書式を設定する数値列が見つかりません');
  }
  ranges.forEach(function (rg) { rg.setNumberFormat(fmt); });
  chg_(ctx, sh, ranges.map(function (rg) { return rg.getA1Notation(); }).join('・'), '数値表示（' + fmt + '）を適用');
};

// 棚: font.unify
// 題: シートや全シートのフォントとサイズを統一する
// 分類: 見た目
// 語: フォントを統一|フォント統一|フォントを揃え|書体を統一|書体を揃え|フォントサイズ統一|文字を統一|書体とサイズ
// 違い: 特定セルだけ色や太字を変えるなら format
// 引数: font=文字=Noto Sans JP, size=数, all_sheets=真偽=false
// 頼み: all_sheets=true<全シート|すべてのシート|全てのシート|ブック全体 ; size~([0-9]+)\s*(?:pt|ポイント) ; font~(?:フォント|書体)を[『「]?([^』」、。にへ]+?)[』」]?(?:に|へ)
// 例: 「シート全体のフォントをNoto Sans JPに統一して」 → {"shelf":"font.unify"}
// 触る: 書式
// 控え: 今
SHELF['font.unify'] = function (ctx, op) {
  var ss = ctx.ss, font = String(op.font || 'Noto Sans JP').trim() || 'Noto Sans JP';
  var sz = op.size !== undefined ? Number(op.size) : 0;
  var targets = op.all_sheets
    ? ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; })
    : [sheetCtx_(ctx, op)];
  var touched = [];
  targets.forEach(function (s) {
    var lr = s.getLastRow(), lc = s.getLastColumn();
    if (lr < 1 || lc < 1) return;
    var rg = s.getRange(1, 1, lr, lc);
    rg.setFontFamily(font);
    if (sz > 0) rg.setFontSize(sz);
    touched.push(s.getName());
  });
  if (!touched.length) {
    note_(ctx, 'フォントを変更するデータがありませんでした（変更なし）');
    return;
  }
  chg_(ctx, op.all_sheets ? null : targets[0], '', 'フォントを「' + font + '」' + (sz > 0 ? ('・' + sz + 'pt ') : '') + 'に統一（' + touched.length + ' シート）');
};
DYNAMIC['font.unify'] = {
  touch: function () { return ['書式']; },
  sheets: function (ctx, op) {
    if (op.all_sheets) {
      return ctx.ss.getSheets().filter(function (s) { return s.getName() !== '_GASクイックの控え'; }).map(function (s) { return s.getName(); });
    }
    return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()];
  }
};

// 棚: rows.highlight
// 題: 条件に合う行の背景色を固定色でハイライトする
// 分類: 見た目
// 語: 条件に合う行に色|条件の行をハイライト|行に色を付け|該当行に色|特定の行に色|行を固定色で塗|行を目立たせ
// 違い: 値の変化に自動追従させるなら cf.add。交互色なら banding.add
// 引数: col*=列, when=選択(contains/eq/ne/gt/lt/blank/notblank)=contains, value=文字, bg=色=薄黄
// 頼み: when=blank<空欄|空白 ; when=notblank<空白以外|空欄以外|入力済み ; when=gt<より大きい|超える|上回る|上回っ ; when=lt<未満|より小さい|下回る|下回っ|届かない|届いていない|届いてない ; when=eq<と一致|と等しい ; when=ne<以外|ではない ; value~が([^\sの、。]+?)の行.*?(?:色|塗|ハイライト|目立)
// 例: 「ステータス列が未完了の行を薄い赤で塗って」 → {"shelf":"rows.highlight","col":"ステータス","when":"eq","value":"未完了","bg":"薄赤"}
// 触る: 書式
// 控え: 今
SHELF['rows.highlight'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  if (nr < 1) { note_(ctx, '対象データ行がありません'); return; }
  var when = String(op.when || 'contains').toLowerCase();
  var val = op.value !== undefined ? op.value : (op.text !== undefined ? op.text : '');
  var numVal = Number(String(val).replace(/,/g, ''));
  var hex = rgb_(op.bg || '薄黄') || '#fef08a';
  var colVals = sh.getRange(t.firstData, ci, nr, 1).getValues();
  var nc = t.lastCol - t.firstCol + 1;
  var dr = sh.getRange(t.firstData, t.firstCol, nr, nc);
  var bgs = dr.getBackgrounds();
  var hits = 0;
  for (var r = 0; r < nr; r++) {
    var v = colVals[r][0], sv = String(v == null ? '' : v).trim(), tv = String(val == null ? '' : val).trim();
    var ok = false;
    if (when === 'blank') ok = isBlank_(v);
    else if (when === 'notblank') ok = !isBlank_(v);
    else if (when === 'eq') ok = sv === tv;
    else if (when === 'ne') ok = sv !== tv;
    else if (when === 'gt') ok = !isBlank_(v) && isFinite(Number(v)) && isFinite(numVal) && Number(v) > numVal;
    else if (when === 'lt') ok = !isBlank_(v) && isFinite(Number(v)) && isFinite(numVal) && Number(v) < numVal;
    else ok = tv !== '' && sv.indexOf(tv) >= 0;
    if (ok) {
      for (var c = 0; c < nc; c++) bgs[r][c] = hex;
      hits++;
    }
  }
  if (!hits) {
    note_(ctx, '条件に合う行はありませんでした（変更なし）');
    return;
  }
  dr.setBackgrounds(bgs);
  chg_(ctx, sh, dr.getA1Notation(), '条件に合う ' + hits + ' 行をハイライト（' + hex + '）');
};
DYNAMIC['rows.highlight'] = {
  touch: function () { return ['書式']; },
  sheets: function (ctx, op) { return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()]; }
};

// 棚: borders.group
// 題: 値が変わる行の下に区切り線を引く
// 分類: 見た目
// 語: 区切り線|境目に線|境界線|値が変わる行|部署が変わる行|グループ境界|変わる行の下|切り替わる行
// 違い: 表全体に格子を引くなら format の borders。行に色を付けるなら rows.highlight
// 引数: col*=列, style=選択(solid/dashed/double/thick)=solid, color=色, clear_inner=真偽=false
// 頼み: style=dashed<破線|点線 ; style=double<二重線 ; style=thick<太線 ; clear_inner=true<中の線を消|内側を消 ; col~([^\sのが]+)(?:ごと|が変わる|の切り替わり)
// 例: 「部署が変わる行の下に区切り線を引いて」 → {"shelf":"borders.group","col":"部署"}
// 例: 「日付が変わる行の下に二重線の区切り線を引いて」 → {"shelf":"borders.group","col":"日付","style":"double"}
// 触る: 書式
// 控え: 今
SHELF['borders.group'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col);
  var nr = Math.max(0, t.lastData - t.firstData + 1);
  if (nr < 2) { note_(ctx, '比較できるデータ行が 2 行未満です'); return; }
  var nc = t.lastCol - t.firstCol + 1;
  var styleMap = {
    solid: SpreadsheetApp.BorderStyle.SOLID,
    dashed: SpreadsheetApp.BorderStyle.DASHED,
    double: SpreadsheetApp.BorderStyle.DOUBLE,
    thick: SpreadsheetApp.BorderStyle.SOLID_THICK
  };
  var stKey = String(op.style || 'solid').toLowerCase();
  var bs = styleMap[stKey] || SpreadsheetApp.BorderStyle.SOLID;
  var colHex = rgb_(op.color || STYLE.border) || STYLE.border;
  if (op.clear_inner) {
    sh.getRange(t.firstData, t.firstCol, nr, nc).setBorder(null, null, null, null, null, false);
  }
  var disp = sh.getRange(t.firstData, ci, nr, 1).getDisplayValues();
  var boundaryRows = [];
  for (var r = 0; r < nr - 1; r++) {
    var cur = String(disp[r][0] == null ? '' : disp[r][0]).trim();
    var nxt = String(disp[r + 1][0] == null ? '' : disp[r + 1][0]).trim();
    if (cur !== nxt) boundaryRows.push(t.firstData + r);
  }
  if (!boundaryRows.length) {
    note_(ctx, op.col + ' 列の値が切り替わる行はありませんでした（変更なし）');
    return;
  }
  boundaryRows.forEach(function (rowNum) {
    sh.getRange(rowNum, t.firstCol, 1, nc).setBorder(null, null, true, null, null, null, colHex, bs);
  });
  chg_(ctx, sh, colLetter_(t.firstCol) + t.firstData + ':' + colLetter_(t.lastCol) + t.lastData, op.col + ' が変わる ' + boundaryRows.length + ' 箇所の下に区切り線');
};
DYNAMIC['borders.group'] = {
  touch: function () { return ['書式']; },
  sheets: function (ctx, op) { return [op.sheet || ctx.sheetName || ctx.ss.getSheets()[0].getName()]; }
};
