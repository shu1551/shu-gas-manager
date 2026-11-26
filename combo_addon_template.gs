/**
 * GASコンボ（Google Workspace アドオン）
 * 1 回入れれば、どのスプレッドシートでも右の枠（⚡）から頼みを撃てる。シートごとのつなぎコードは要らない。
 * 本体・棚は大元ライブラリ {lib_symbol}、棚当ては同じプロジェクトの ComboPlanner（サイドバーと同じ物）。
 * 入れ方: py gas.py combo addon → Apps Script の「デプロイ」→「デプロイをテスト」→「インストール」（初回だけ）
 */
function onHome(e) { return comboAddonCard_(e, ''); }

// 今開いているスプレッドシートまたはドキュメント（e.sheets / e.docs に id/title があれば重い呼び出しを省く）
function comboAddonTarget_(e) {
  var s = (e && e.sheets) || {};
  if (s.id && s.title) return { id: s.id, title: s.title, kind: 'sheet' };
  var d = (e && e.docs) || {};
  if (d.id && d.title) return { id: d.id, title: d.title, kind: 'doc' };
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    if (ss) return { id: ss.getId(), title: ss.getName(), kind: 'sheet', _ss: ss };
  } catch (err) {}
  try {
    if (typeof DocumentApp !== 'undefined' && typeof DocumentApp.getActiveDocument === 'function') {
      var doc = DocumentApp.getActiveDocument();
      if (doc) return { id: doc.getId(), title: doc.getName(), kind: 'doc', _doc: doc };
    }
  } catch (errD) {}
  if (s.id) return { id: s.id, title: s.title || '', kind: 'sheet' };
  if (d.id) return { id: d.id, title: d.title || '', kind: 'doc' };
  return {};
}

function onAddonGrant(e) {
  return CardService.newEditorFileScopeActionResponseBuilder().requestFileScopeForActiveDocument().build();
}
function onFileScopeGranted(e) { return comboAddonCard_(e, ''); }

// 表の形（見出し・列・合計行）とシートの一覧を覚えておき、2 回目からは読み直さない（読むと 0.9 秒かかる）。
// 表の形を変えない手（書式・幅・色・縞・条件付き書式・固定・絞り込み・並べ替え）のときだけ覚えを残す
var COMBO_ADDON_KEEPS_SHAPE = /^(format|width|bg\.clear|banding\.|cf\.|freeze|unfreeze|filter\.(?:on|off|where)|sort|tidy|sheet\.(?:gridlines|color|move)|book\.finish|audit\.check|protect\.|name\.|note\.(?:set|clear)|link\.(?:set|clear)|validation\.|print\.setup|chart\.)/;
var COMBO_ADDON_LEARNED_CACHE_KEY = 'addon_learned_v1';
function comboAddonKey_(tg, sheetName) { return 'addon_tbl:' + tg.id + ':' + sheetName; }
function comboAddonInit_(tg, optCache, optHitRaw, optSheetName) {
  if (tg && tg.kind === 'doc') {
    var initDoc = {lib_symbol}.comboInit({ targetId: tg.id, kind: 'doc' });
    return { target: initDoc.target || { id: tg.id, name: tg.title, kind: 'doc' }, table: null, sheets: [], outline: initDoc.outline || [] };
  }
  var sheetName = optSheetName || '';
  if (!sheetName) {
    try { sheetName = (tg._ss || SpreadsheetApp.getActiveSpreadsheet()).getActiveSheet().getName(); } catch (e0) {}
  }
  var cache = optCache || null;
  if (!cache) { try { cache = CacheService.getUserCache(); } catch (e1) {} }
  var hit = optHitRaw !== undefined ? optHitRaw : ((cache && sheetName) ? cache.get(comboAddonKey_(tg, sheetName)) : null);
  if (hit) {
    try { var o = JSON.parse(hit); o._cached = true; return o; } catch (e2) {}
  }
  var init = {lib_symbol}.comboInit({ targetId: tg.id });
  var keep = { target: init.target, table: init.table, sheets: init.sheets };
  try { if (cache) cache.put(comboAddonKey_(tg, (init.target && init.target.sheet) || sheetName), JSON.stringify(keep), 600); } catch (e3) {}
  return keep;
}
function comboAddonForget_(tg, sheetName) {
  try { CacheService.getUserCache().remove(comboAddonKey_(tg, sheetName)); } catch (e) {}
}

function comboAddonEsc_(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

function comboAddonCard_(e, msg, suggestBtn, optTg) {
  var tg = optTg || comboAddonTarget_(e);
  var sec = CardService.newCardSection();
  if (!tg.id) {
    sec.addWidget(CardService.newTextParagraph().setText('このファイルで使うには、1 回だけ許可が要ります。'));
    sec.addWidget(CardService.newTextButton().setText('このファイルで使う')
      .setOnClickAction(CardService.newAction().setFunctionName('onAddonGrant')));
  } else {
    var ph = tg.kind === 'doc' ? '頼み（例: 見出し一覧を見せて / 目次を入れて）' : '頼み（例: タイトルの文字の色を赤に）';
    // 1 行の入力欄。Enter（音声入力の終わりの Enter も）で確定したら、そのまま実行する
    sec.addWidget(CardService.newTextInput().setFieldName('ask').setTitle(ph).setMultiline(false)
      .setOnChangeAction(CardService.newAction().setFunctionName('onAddonRun')));
    // 実行・戻す・操作窓を横 1 行にまとめる
    var btnRow = CardService.newButtonSet()
      .addButton(CardService.newTextButton().setText('実行').setTextButtonStyle(CardService.TextButtonStyle.FILLED)
        .setOnClickAction(CardService.newAction().setFunctionName('onAddonRun')))
      .addButton(CardService.newTextButton().setText('戻す')
        .setOnClickAction(CardService.newAction().setFunctionName('onAddonUndo')))
      .addButton(CardService.newTextButton().setText('操作窓')
        .setOnClickAction(CardService.newAction().setFunctionName('onAddonOpenWindow')));
    sec.addWidget(btnRow);
    if (msg) sec.addWidget(CardService.newTextParagraph().setText(comboAddonEsc_(msg)));
    if (suggestBtn) {
      sec.addWidget(CardService.newTextButton().setText('はい（撃って覚える）').setTextButtonStyle(CardService.TextButtonStyle.FILLED)
        .setOnClickAction(CardService.newAction().setFunctionName('onAddonAcceptSuggest')));
    }
  }
  var builder = CardService.newCardBuilder().setHeader(CardService.newCardHeader().setTitle(tg.title || 'GASコンボ')).addSection(sec);
  if (tg.id) {
    var qBtn = function (label, act) {
      return CardService.newTextButton().setText(label)
        .setOnClickAction(CardService.newAction().setFunctionName('onAddonQuick').setParameters({ action: act }));
    };
    if (tg.kind === 'doc') {
      var qSecDoc = CardService.newCardSection()
        .addWidget(CardService.newButtonSet()
          .addButton(qBtn('章立て', 'docOutline'))
          .addButton(qBtn('目次挿入', 'docToc'))
          .addButton(qBtn('表装飾', 'docTableStyle'))
          .addButton(qBtn('ページ番号', 'docHeader')));
      builder.addSection(qSecDoc);
    } else {
      var qSec = CardService.newCardSection()
        .addWidget(qBtn('【一発整形】データ整理＋表整形', 'seiri'))
        .addWidget(CardService.newButtonSet()
          .addButton(qBtn('幅自動', 'autoWidth'))
          .addButton(qBtn('重複消', 'dedupe'))
          .addButton(qBtn('罫線', 'borders')));
      builder.addSection(qSec);
    }
  }
  return builder.build();
}

function comboAddonReply_(e, msg, suggestBtn, optTg) {
  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().updateCard(comboAddonCard_(e, msg, suggestBtn, optTg))).build();
}

// 覚えた言い方（UserCache にキャッシュして毎回のライブラリ＋PropertiesService 往復を省く）
function comboAddonLoadLearned_(optCache, optCachedRaw) {
  try {
    if (optCachedRaw !== undefined && optCachedRaw !== null) {
      ComboPlanner.setLearned(JSON.parse(optCachedRaw));
      return;
    }
    var cache = optCache || null;
    if (!cache) { try { cache = CacheService.getUserCache(); } catch (e0) {} }
    var hit = cache ? cache.get(COMBO_ADDON_LEARNED_CACHE_KEY) : null;
    if (hit !== null && hit !== undefined) {
      ComboPlanner.setLearned(JSON.parse(hit));
      return;
    }
    var r = {lib_symbol}.comboGetLearned();
    var learned = (r && r.learned) ? r.learned : {};
    ComboPlanner.setLearned(learned);
    try { if (cache) cache.put(COMBO_ADDON_LEARNED_CACHE_KEY, JSON.stringify(learned), 600); } catch (e1) {}
  } catch (e) {}
}
var COMBO_ADDON_SUGGEST_KEY = 'addon_suggest';

// 候補の［はい］: 出した候補を撃ち、その言い方を覚える
function onAddonAcceptSuggest(e) {
  var t0 = Date.now(), res, sg = null, tg = null;
  var cache = null;
  try { cache = CacheService.getUserCache(); sg = JSON.parse((cache && cache.get(COMBO_ADDON_SUGGEST_KEY)) || 'null'); } catch (eC) {}
  if (!sg || !sg.ops) return comboAddonReply_(e, '候補の期限が切れました。もう一度頼んでください。');
  try {
    tg = comboAddonTarget_(e);
    var init = comboAddonInit_(tg, cache);
    var curSheet = init.target && init.target.sheet;
    res = {lib_symbol}.comboRunAsk({ ops: sg.ops, fastUndo: true, kind: tg.kind || 'sheet', targetId: tg.id, targetName: tg.title, sheet: curSheet, selection: '', table: init.table, sheets: init.sheets });
    if (res && res.ok !== false) {
      {lib_symbol}.comboLearn({ ask: sg.ask, ops: sg.ops, key: ComboPlanner.learnKey(sg.ask) });
      try { if (cache) cache.remove(COMBO_ADDON_LEARNED_CACHE_KEY); } catch (eLC) {}
      res.text = (res.text || '') + '\n覚えました（次から「' + sg.ask + '」は一発で撃ちます）';
    }
    try { if (cache) cache.remove(COMBO_ADDON_SUGGEST_KEY); } catch (eR) {}
    if (!sg.ops.every(function (o) { return COMBO_ADDON_KEEPS_SHAPE.test(String(o.shelf || '')); })) comboAddonForget_(tg, curSheet);
  } catch (err) {
    res = { ok: false, text: String(err && err.message || err) };
  }
  return comboAddonReply_(e, (res.text || res.error || '') + '\n' + comboAddonSecs_(t0), false, tg);
}

function comboAddonSecs_(t0) { return '（' + ((Date.now() - t0) / 1000).toFixed(2) + ' 秒）'; }
function comboAddonShortMsg_(res, t0) {
  if (!res) return 'エラー\n' + comboAddonSecs_(t0);
  if (res.ok === false) return '✗ ' + (res.error || res.text || '失敗しました') + '\n' + comboAddonSecs_(t0);
  var head = '';
  if (res.undone) {
    head = '↶ 戻しました（' + (res.what || '直前') + '）';
  } else if (Array.isArray(res.changed) && res.changed.length) {
    var items = res.changed.slice(0, 2).map(function (c) { return String(c).replace(/^[^!]+!/, ''); });
    head = '✓ ' + items.join(' ／ ');
  } else {
    head = String(res.text || '完了').split('\n')[0];
  }
  var extra = (Array.isArray(res.notes) && res.notes.length) ? ('\n' + res.notes[0]) : '';
  return head + extra + '\n' + comboAddonSecs_(t0);
}

function onAddonRun(e) {
  var t0 = Date.now(), res, tg = null;
  var f = (e && e.commonEventObject && e.commonEventObject.formInputs) || {};
  var ask = (f.ask && f.ask.stringInputs && f.ask.stringInputs.value[0]) || '';
  if (!String(ask).trim()) return comboAddonReply_(e, '');
  try {
    tg = comboAddonTarget_(e);
    var tgKind = tg.kind || 'sheet';
    var tA = Date.now();
    var sheetName = '';
    if (tgKind !== 'doc') {
      try { sheetName = (tg._ss || SpreadsheetApp.getActiveSpreadsheet()).getActiveSheet().getName(); } catch (eS) {}
    }
    // UserCache を getAll 1 往復でまとめて引く（二重送信チェック・表キャッシュ・学習済み言い方）
    var cache = null, bag = {};
    var dedupKey = 'addon_last_ask';
    var tblKey = (tgKind !== 'doc' && sheetName) ? comboAddonKey_(tg, sheetName) : '';
    try {
      cache = CacheService.getUserCache();
      var keys = [dedupKey, COMBO_ADDON_LEARNED_CACHE_KEY];
      if (tblKey) keys.push(tblKey);
      bag = cache.getAll(keys) || {};
      if (bag[dedupKey] && bag[dedupKey] === ask) {
        return comboAddonReply_(e, '（同じ頼みを続けて受けたので、2 回目は撃っていません）', false, tg);
      }
      cache.put(dedupKey, ask, 3);
    } catch (eC) {}

    // 表の形（見出し・列・合計行）とシートの一覧を読み、棚に当てる。当たれば AI を通さずにそのまま撃つ
    var init = comboAddonInit_(tg, cache, tblKey ? (bag[tblKey] || null) : null, sheetName);
    var tB = Date.now();
    var curSheet = (init.target && init.target.sheet) || sheetName;
    comboAddonLoadLearned_(cache, bag[COMBO_ADDON_LEARNED_CACHE_KEY]);
    var p = ComboPlanner.plan(ask, tgKind, init.table, init.sheets, curSheet, null);
    var tC = Date.now();
    if (!(p && p.fire) && p && p.suggest && p.suggest.length) {
      try { if (cache) cache.put(COMBO_ADDON_SUGGEST_KEY, JSON.stringify({ ask: ask, ops: p.suggest }), 600); } catch (eS2) {}
      return comboAddonReply_(e, '棚に当たりませんでした。近い候補: ' + ComboPlanner.formatOpsShort(p.suggest) +
        '\nこれを撃ちますか？（［はい］で撃って、この言い方を覚えます）\n' + comboAddonSecs_(t0), true, tg);
    }
    if (p && p.fire && p.ops && p.ops.length) {
      res = {lib_symbol}.comboRunAsk({ ops: p.ops, fastUndo: true, kind: tgKind, targetId: tg.id, targetName: tg.title, sheet: curSheet, selection: '', table: init.table, sheets: init.sheets });
    } else {
      res = {lib_symbol}.comboRunAsk({ ask: ask, fastUndo: true, kind: tgKind, targetId: tg.id, targetName: tg.title, sheet: curSheet });   // 棚に当たらなければいつもの道（AI・郵便受け）
    }
    var keepsShape = tgKind !== 'doc' && !!(p && p.fire && p.ops && p.ops.every(function (o) { return COMBO_ADDON_KEEPS_SHAPE.test(String(o.shelf || '')); }));
    if (!keepsShape && tgKind !== 'doc') comboAddonForget_(tg, curSheet);
  } catch (err) {
    res = { ok: false, error: String(err && err.message || err) };
  }
  return comboAddonReply_(e, comboAddonShortMsg_(res, t0), false, tg);
}

function onAddonUndo(e) {
  var t0 = Date.now(), res, tgU = null;
  try {
    tgU = comboAddonTarget_(e);
    res = {lib_symbol}.comboUndo({ targetId: tgU.id, kind: tgU.kind || 'sheet' });
    if (res && res.ok && !res.fast && tgU.kind !== 'doc') {
      try { comboAddonForget_(tgU, (tgU._ss || SpreadsheetApp.getActiveSpreadsheet()).getActiveSheet().getName()); } catch (eF) {}
    }
  }
  catch (err) { res = { ok: false, error: String(err && err.message || err) }; }
  return comboAddonReply_(e, comboAddonShortMsg_(res, t0), false, tgU);
}

function onAddonQuick(e) {
  var t0 = Date.now(), res, tg = null;
  var act = (e && e.commonEventObject && e.commonEventObject.parameters && e.commonEventObject.parameters.action) || '';
  if (!act) return comboAddonReply_(e, '');
  try {
    tg = comboAddonTarget_(e);
    if (tg.kind === 'doc') {
      var docOps = null;
      if (act === 'docOutline') docOps = [{ shelf: 'doc.outline' }];
      else if (act === 'docToc') docOps = [{ shelf: 'doc.toc' }];
      else if (act === 'docTableStyle') docOps = [{ shelf: 'doc.table.style' }];
      else if (act === 'docHeader') docOps = [{ shelf: 'doc.header', page_number: true }];
      if (!docOps) return comboAddonReply_(e, '✗ 未対応のボタンです\n' + comboAddonSecs_(t0), false, tg);
      res = {lib_symbol}.comboRunAsk({ ops: docOps, kind: 'doc', targetId: tg.id, targetName: tg.title });
      return comboAddonReply_(e, comboAddonShortMsg_(res, t0), false, tg);
    }
    var ss = tg._ss || SpreadsheetApp.getActiveSpreadsheet();
    var sh = ss.getActiveSheet();
    var curSheet = sh.getName();
    var cache = null;
    try { cache = CacheService.getUserCache(); } catch (eC) {}
    var init = comboAddonInit_(tg, cache, undefined, curSheet);
    var tb = init.table || null;
    var ops = null;
    if (act === 'seiri') {
      ops = [{ shelf: 'seiri' }];
    } else if (act === 'total') {
      ops = [{ shelf: 'total' }];
    } else if (act === 'dedupe') {
      ops = [{ shelf: 'dedupe' }];
    } else if (act === 'freezeToggle') {
      var curFrozen = 0;
      try { curFrozen = sh.getFrozenRows(); } catch (eFr) {}
      ops = curFrozen > 0
        ? [{ shelf: 'unfreeze' }]
        : [{ shelf: 'freeze', rows: (tb && tb.header_row) ? tb.header_row : 1 }];
    } else if (act === 'bandingToggle') {
      var hasBand = false;
      try { hasBand = (sh.getBandings() || []).length > 0; } catch (eBd) {}
      ops = hasBand
        ? [{ shelf: 'banding.remove' }]
        : [{ shelf: 'banding.add', theme: 'blue' }];
    } else if (act === 'freezeHeader') {
      ops = [{ shelf: 'freeze', rows: (tb && tb.header_row) ? tb.header_row : 1 }];
    } else if (act === 'unfreeze') {
      ops = [{ shelf: 'unfreeze' }];
    } else if (act === 'bandingAdd') {
      ops = [{ shelf: 'banding.add', theme: 'blue' }];
    } else if (act === 'bandingRemove') {
      ops = [{ shelf: 'banding.remove' }];
    } else if (act === 'autoWidth') {
      var cols = (tb && Array.isArray(tb.columns) && tb.columns.length)
        ? tb.columns.map(function (c) { return c.col; })
        : null;
      if (!cols) {
        var lc = Math.max(1, sh.getLastColumn());
        cols = [];
        for (var ci = 1; ci <= lc; ci++) {
          var n = ci, s = '';
          while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
          cols.push(s);
        }
      }
      ops = [{ shelf: 'width', auto: cols }];
    } else if (act === 'borders') {
      var selRg = null, bRange = '';
      try { selRg = sh.getActiveRange(); } catch (eSel) {}
      if (selRg && (selRg.getNumRows() > 1 || selRg.getNumColumns() > 1)) {
        bRange = selRg.getA1Notation();
      } else if (tb && tb.first_col && tb.last_col && tb.header_row) {
        var dm = String(tb.data || '').match(/^(\d+)-(\d+)$/);
        var endR = tb.total_row ? Number(tb.total_row) : (dm ? Number(dm[2]) : Number(tb.last_row || tb.header_row));
        bRange = tb.first_col + tb.header_row + ':' + tb.last_col + endR;
      } else if (selRg) {
        bRange = selRg.getA1Notation();
      }
      if (!bRange) return comboAddonReply_(e, '✗ 罫線を引く範囲が見つかりません\n' + comboAddonSecs_(t0), false, tg);
      ops = [{ shelf: 'format', range: bRange, borders: true }];
    }
    if (!ops) return comboAddonReply_(e, '✗ 未対応のボタンです\n' + comboAddonSecs_(t0), false, tg);
    res = {lib_symbol}.comboRunAsk({ ops: ops, fastUndo: true, targetId: tg.id, targetName: tg.title, sheet: curSheet, selection: '', table: tb, sheets: init.sheets });
    var keepsShape = ops.every(function (o) { return COMBO_ADDON_KEEPS_SHAPE.test(String(o.shelf || '')); });
    if (!keepsShape) comboAddonForget_(tg, curSheet);
  } catch (err) {
    res = { ok: false, error: String(err && err.message || err) };
  }
  return comboAddonReply_(e, comboAddonShortMsg_(res, t0), false, tg);
}

// ---------------------------------------------------------------- 操作窓（前のサイドバーと同じ HTML の画面を別の窓で開く）
// カードはボタンのたびに描き直されて入力欄のカーソルが消える。操作窓はカーソルが残るので、音声入力→Enter を続けられる。
// 直結の道（Sheets API を画面から直接叩く 0.3〜0.6 秒）もそのまま使える。シートにコードは入れない。
var COMBO_ADDON_TARGET_PROP = 'ADDON_TARGET';
var COMBO_ADDON_KIND_PROP = 'ADDON_TARGET_KIND';

// 窓の番地は、最新のコードで動くテスト用の番地（HEAD の /dev）。py gas.py combo addon が書き込む
var COMBO_ADDON_WINDOW_BASE = '{webapp_url}';
function comboAddonWindowUrl_(id, kind) {
  var base = COMBO_ADDON_WINDOW_BASE;
  if (!base || base.indexOf('{') === 0) { try { base = ScriptApp.getService().getUrl() || ''; } catch (e) {} }
  var q = 'id=' + encodeURIComponent(id || '');
  if (kind) q += '&kind=' + encodeURIComponent(kind);
  return base + (base.indexOf('?') >= 0 ? '&' : '?') + q;
}

function onAddonOpenWindow(e) {
  var tg = comboAddonTarget_(e);
  try {
    var up = PropertiesService.getUserProperties();
    up.setProperty(COMBO_ADDON_TARGET_PROP, tg.id || '');
    up.setProperty(COMBO_ADDON_KIND_PROP, tg.kind || 'sheet');
  } catch (err) {}
  return CardService.newActionResponseBuilder()
    .setOpenLink(CardService.newOpenLink().setUrl(comboAddonWindowUrl_(tg.id, tg.kind || 'sheet'))
      .setOpenAs(CardService.OpenAs.OVERLAY).setOnClose(CardService.OnClose.NOTHING))
    .build();
}

function doGet(e) {
  var id = e && e.parameter && e.parameter.id;
  var kind = e && e.parameter && e.parameter.kind;
  try {
    var up = PropertiesService.getUserProperties();
    if (id) up.setProperty(COMBO_ADDON_TARGET_PROP, id);
    else id = up.getProperty(COMBO_ADDON_TARGET_PROP) || '';
    if (kind) up.setProperty(COMBO_ADDON_KIND_PROP, kind);
    else kind = up.getProperty(COMBO_ADDON_KIND_PROP) || 'sheet';
  } catch (err) {}
  // アドオンの操作窓も Chrome のサイドパネルも等倍（z=1）で同じ見た目にする
  var z = Number((e && e.parameter && e.parameter.z) || 1) || 1;
  var out = {lib_symbol}.createComboSidebarHtml();
  if (z !== 1) out.append('<style>html{zoom:' + z + '}</style>');
  // 拡張機能を使えない環境向け：アドオン操作窓に「右寄せ・縦長」で開き直すボタンを追加する
  if (!(e && e.parameter && String(e.parameter.z || '') === '1')) {
    var popUrl = comboAddonWindowUrl_(id || '');
    out.append(
      '<script>(function(){' +
      'var url=' + JSON.stringify(popUrl) + ';' +
      'function openRight(){' +
      'var sw=(screen&&screen.availWidth)||1280,sh=(screen&&screen.availHeight)||800;' +
      'var sl=(screen&&screen.availLeft)||0,st=(screen&&screen.availTop)||0;' +
      'var w=Math.min(540,Math.max(460,Math.round(sw*0.42)));' +
      'var h=Math.max(600,sh);' +
      'var l=sl+Math.max(0,sw-w),t=st;' +
      'window.open(url,"gas_combo_right_"+Date.now(),"popup=yes,width="+w+",height="+h+",left="+l+",top="+t+",resizable=yes,scrollbars=yes");' +
      'try{window.top.close();}catch(e1){}try{window.close();}catch(e2){}' +
      '}' +
      'function mount(){' +
      'var bar=document.querySelector(".target-bar");if(!bar||document.getElementById("btnDockRight"))return;' +
      'var b=document.createElement("button");b.id="btnDockRight";b.type="button";b.className="btn";' +
      'b.textContent="右縦長";b.title="右寄せ・縦長の別窓で開き直す";b.onclick=openRight;' +
      'bar.appendChild(b);' +
      '}' +
      'if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);else mount();' +
      '})();<' + '/script>'
    );
  }
  // Chrome 拡張のサイドパネルの中に入れられるようにする
  return out.setTitle('GASコンボ').setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// 操作窓から呼ばれる入口。相手のシートは、窓を開いたときに覚えた物
function comboAddonReq_(req) {
  req = req || {};
  try {
    var up = PropertiesService.getUserProperties();
    if (!req.targetId) {
      var id = up.getProperty(COMBO_ADDON_TARGET_PROP);
      if (id) req.targetId = id;
    }
    if (!req.kind) {
      var k = up.getProperty(COMBO_ADDON_KIND_PROP);
      if (k) req.kind = k;
    }
  } catch (e) {}
  return req;
}
function comboInit(req) { return {lib_symbol}.comboInit(comboAddonReq_(req)); }
function comboLook(req) { return {lib_symbol}.comboLook(comboAddonReq_(req)); }
function comboRunAsk(req) { return {lib_symbol}.comboRunAsk(comboAddonReq_(req)); }
function comboRunOps(req) { return {lib_symbol}.comboRunOps(comboAddonReq_(req)); }
function comboFind(req) { return {lib_symbol}.comboFind(comboAddonReq_(req)); }
function comboUndo(req) { return {lib_symbol}.comboUndo(comboAddonReq_(req)); }
function comboPollSelection(req) { return {lib_symbol}.comboPollSelection(comboAddonReq_(req)); }
function comboGetConfig() { return {lib_symbol}.comboGetConfig(); }
function comboGetLearned(req) { return {lib_symbol}.comboGetLearned(req); }
function comboLearn(req) { return {lib_symbol}.comboLearn(req); }
function comboSaveConfig(cfg) { return {lib_symbol}.comboSaveConfig(cfg); }
function comboQuickList(req) { return {lib_symbol}.comboQuickList(comboAddonReq_(req)); }
function comboQuickRun(req) { return {lib_symbol}.comboQuickRun(comboAddonReq_(req)); }
function comboQuickMake(req) { return {lib_symbol}.comboQuickMake(comboAddonReq_(req)); }
function comboQuickGetFn(req) { return {lib_symbol}.comboQuickGetFn(req); }
function comboQuickSaveFn(req) { return {lib_symbol}.comboQuickSaveFn(req); }
function comboQuickAddFn(req) { return {lib_symbol}.comboQuickAddFn(req); }
function comboQuickDeleteFn(req) { return {lib_symbol}.comboQuickDeleteFn(req); }
function comboQuickSaveOrder(req) { return {lib_symbol}.comboQuickSaveOrder(comboAddonReq_(req)); }
function comboQuickSavePins(req) { return {lib_symbol}.comboQuickSavePins(req); }
function comboQuickSaveSteps(req) { return {lib_symbol}.comboQuickSaveSteps(comboAddonReq_(req)); }
function comboQuickAiSave(req) { return {lib_symbol}.comboQuickAiSave(comboAddonReq_(req)); }
function comboCall(name, req) { return {lib_symbol}.comboCall(name, comboAddonReq_(req)); }
// PC の郵便受けの受け手（py gas.py combo watch）が呼ぶ口
function comboPostboxPoll() { return {lib_symbol}.comboPostboxPoll(); }
function comboPostboxDeliver(res) { return {lib_symbol}.comboPostboxDeliver(res); }
