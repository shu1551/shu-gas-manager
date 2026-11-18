/**
 * GASコンボ（Google Workspace アドイン）
 * 1 回入れれば、どのスプレッドシートでも右の枠（⚡）から頼みを撃てる。シートごとのつなぎコードは要らない。
 * 本体・棚は大元ライブラリ {lib_symbol}、棚当ては同じプロジェクトの ComboPlanner（サイドバーと同じ物）。
 * 入れ方: py gas.py combo addon → Apps Script の「デプロイ」→「デプロイをテスト」→「インストール」（初回だけ）
 */
function onHome(e) { return comboAddonCard_(e, ''); }

// 今開いているスプレッドシート（シートごとの許可は要らない。取れないときだけ 1 回の許可を求める）
function comboAddonTarget_(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    if (ss) return { id: ss.getId(), title: ss.getName() };
  } catch (err) {}
  var s = (e && e.sheets) || {};
  if (s.id) return { id: s.id, title: s.title };
  return {};
}

function onAddonGrant(e) {
  return CardService.newEditorFileScopeActionResponseBuilder().requestFileScopeForActiveDocument().build();
}
function onFileScopeGranted(e) { return comboAddonCard_(e, ''); }

function comboAddonEsc_(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

function comboAddonCard_(e, msg) {
  var tg = comboAddonTarget_(e);
  var sec = CardService.newCardSection();
  if (!tg.id) {
    sec.addWidget(CardService.newTextParagraph().setText('このスプレッドシートで使うには、1 回だけ許可が要ります。'));
    sec.addWidget(CardService.newTextButton().setText('このシートで使う')
      .setOnClickAction(CardService.newAction().setFunctionName('onAddonGrant')));
  } else {
    sec.addWidget(CardService.newTextParagraph().setText('<b>' + comboAddonEsc_(tg.title) + '</b>'));
    // 1 行の入力欄。Enter（音声入力の終わりの Enter も）で確定したら、そのまま実行する
    sec.addWidget(CardService.newTextInput().setFieldName('ask').setTitle('頼み（例: タイトルの文字の色を赤に）').setMultiline(false)
      .setOnChangeAction(CardService.newAction().setFunctionName('onAddonRun')));
    sec.addWidget(CardService.newTextButton().setText('実行').setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setOnClickAction(CardService.newAction().setFunctionName('onAddonRun')));
    sec.addWidget(CardService.newTextButton().setText('直前を取り消す')
      .setOnClickAction(CardService.newAction().setFunctionName('onAddonUndo')));
    if (msg) sec.addWidget(CardService.newTextParagraph().setText(comboAddonEsc_(msg)));
  }
  return CardService.newCardBuilder().setHeader(CardService.newCardHeader().setTitle('GASコンボ')).addSection(sec).build();
}

function comboAddonReply_(e, msg) {
  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().updateCard(comboAddonCard_(e, msg))).build();
}

function comboAddonSecs_(t0) { return '（合計 ' + ((Date.now() - t0) / 1000).toFixed(2) + ' 秒）'; }

function onAddonRun(e) {
  var t0 = Date.now(), res;
  var f = (e && e.commonEventObject && e.commonEventObject.formInputs) || {};
  var ask = (f.ask && f.ask.stringInputs && f.ask.stringInputs.value[0]) || '';
  // Enter の確定と「実行」ボタンが続けて来ても 2 回撃たない（同じ頼みが 3 秒以内なら 2 回目は捨てる）
  try {
    var cache = CacheService.getUserCache(), key = 'addon_last_ask';
    var last = cache.get(key);
    if (last && last === ask) return comboAddonReply_(e, '（同じ頼みを続けて受けたので、2 回目は撃っていません）');
    cache.put(key, ask, 3);
  } catch (eC) {}
  if (!String(ask).trim()) return comboAddonReply_(e, '');
  try {
    var tg = comboAddonTarget_(e);
    // 表の形（見出し・列・合計行）とシートの一覧を読み、棚に当てる。当たれば AI を通さずにそのまま撃つ
    var init = {lib_symbol}.comboInit({ targetId: tg.id });
    var curSheet = init.target && init.target.sheet;
    var p = ComboPlanner.plan(ask, 'sheet', init.table, init.sheets, curSheet, null);
    if (p && p.fire && p.ops && p.ops.length) {
      res = {lib_symbol}.comboRunAsk({ ops: p.ops, fastUndo: true, targetId: tg.id, sheet: curSheet, table: init.table, sheets: init.sheets });
    } else {
      res = {lib_symbol}.comboRunAsk({ ask: ask, fastUndo: true, targetId: tg.id, sheet: curSheet });   // 棚に当たらなければいつもの道（AI・郵便受け）
    }
  } catch (err) {
    res = { ok: false, text: String(err && err.message || err) };
  }
  return comboAddonReply_(e, (res.text || res.error || '') + '\n' + comboAddonSecs_(t0));
}

function onAddonUndo(e) {
  var t0 = Date.now(), res;
  try { res = {lib_symbol}.comboUndo({ targetId: comboAddonTarget_(e).id }); }
  catch (err) { res = { ok: false, text: String(err && err.message || err) }; }
  return comboAddonReply_(e, (res.text || res.error || '') + '\n' + comboAddonSecs_(t0));
}
