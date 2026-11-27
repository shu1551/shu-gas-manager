// 足の手 script（11/27・Excel マネージャーの「VBA を書いて run-macro で動かす」の写し）:
// 棚にも api にも無い手（込み入った並べ替え・まとめて作る・行ごとの計算 等）を、AI が書いた Apps Script の本文で撃つ。
// ws_do の中を通す＝撃つ前に触るシートを丸ごと控え、失敗したらその場で戻し、台帳に載り、ws_undo で戻せる。
// 渡すのは ss（このスプレッドシート）と sheet（sheet 引数のシート）だけ。ほかのファイル・メール・外への通信に届く語は断る（戻せないため）。
var SCRIPT_DENY_ = /\b(DriveApp|DocumentApp|GmailApp|MailApp|UrlFetchApp|PropertiesService|CacheService|ScriptApp|CalendarApp|FormApp|SlidesApp|LockService|ContentService|HtmlService|Session|Sheets|eval|Function|setTimeout)\b|SpreadsheetApp\s*\.\s*(open|create)\w*|\.\s*(addEditor|addViewer|removeEditor|removeViewer|setSharing|makeCopy)\s*\(/;
var SCRIPT_DELETE_ = /\.\s*(delete\w*|clear\w*|remove\w*)\s*\(/;

// 棚: script
// 題: Apps Script の本文を控えつきで撃つ
// 分類: 範囲
// 語: スクリプトで|Apps Scriptで|GASで書いて|コードで直して
// 違い: 棚・api で足りる手は棚を使う。script は棚にも api にも無い手だけ。本文は function の中身（ss と sheet が使える・return した値は返事に出る）。消す・クリアする手を含むなら ok が要る
// 引数: code*=文字, sheets=配列, why=文字
// 例: 「B 列の名前の前後の空白を全部取って（棚に無い書き方で）」 → {"shelf":"script","code":"var r=sheet.getRange('B3:B15');r.setValues(r.getValues().map(function(x){return [String(x[0]).trim()];}));return r.getA1Notation();","why":"B 列の前後の空白を取る"}
// 危ない: 消す
// 触る: 値 書式 幅 シート構成 固定 隠し グループ 保護 名前 タブ色 グラフ フィルタ
// 控え: 今
SHELF['script'] = function (ctx, op) {
  need_(op, ['code']);
  var code = String(op.code), ss = ctx.ss;
  var deny = SCRIPT_DENY_.exec(code);
  if (deny) throw new ArgError('棚「script」: 「' + deny[0] + '」は使えません（このスプレッドシートの外に届く手は ws_undo で戻せないため）。ss と sheet だけで書いてください');
  var del = SCRIPT_DELETE_.exec(code);
  if (del) guardDelete_(ctx, 'script の本文に消す手「' + del[1] + '」があります', false);
  var fn;
  try { fn = new Function('ss', 'sheet', '"use strict";\n' + code); }
  catch (eSyn) { throw new ArgError('棚「script」: 本文が JavaScript として読めません（何も変わっていません）: ' + String(eSyn.message || eSyn).slice(0, 200)); }
  var sh = sheetOf_(ss, op.sheet || ((op.sheets || [])[0]) || '', ctx.sheetName);
  var before = ss.getSheets().map(function (s) { return s.getName(); });
  ctx.curSheet = sh.getName();
  var ret = fn(ss, sh);   // 実行時の失敗は、そのまま runDo_ の catch に落ちて控えから戻る
  SpreadsheetApp.flush();
  ss.getSheets().forEach(function (s) { if (before.indexOf(s.getName()) < 0) ctx.createdSheets.push(s.getName()); });   // 増えたシートは、失敗・undo で消す
  var retStr = '';
  if (ret !== undefined && ret !== null) { try { retStr = JSON.stringify(ret); } catch (eJ) { retStr = String(ret); } }
  chg_(ctx, sh, '', 'script を撃った' + (op.why ? '：' + op.why : ''));
  if (retStr) ctx.notes.push('script の返り値: ' + retStr.slice(0, 300));
};

DYNAMIC['script'] = {
  // 控えるシート: sheets に書いた物と sheet。書いていなければ今のシート（ほかのシートを触る本文なら sheets に並べる）
  sheets: function (ctx, op) {
    var names = [];
    var add = function (n) { if (n && names.indexOf(n) < 0) names.push(n); };
    (Array.isArray(op.sheets) ? op.sheets : (op.sheets ? [op.sheets] : [])).forEach(add);
    add(op.sheet || (names.length ? '' : (ctx.sheetName || ctx.ss.getSheets()[0].getName())));
    return names;
  },
  touch: function () { return ['値', '書式', '幅', 'シート構成', '固定', '隠し', 'グループ', '保護', '名前', 'タブ色', 'グラフ', 'フィルタ']; }
};
