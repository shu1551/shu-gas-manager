/**
 * workspace_engine.gs - shu-workspace-engine（GAS マネージャーの Workspace エンジン）
 * 道具（gas_workspace.py）が POST で呼ぶ。型（棚）はここが持ち、AI は棚の名前と引数の JSON だけ渡す。
 * 書く前に必ず控えを取り、失敗したら同じ実行の中で戻す。undo は指紋で人の手直しを守る。
 * 版は ENGINE_VERSION（道具が自動で差し替える）。
 */
var ENGINE_VERSION = 'ws-1';
var BK_BOOK_NAME = 'GASマネージャー_控え';
var BK_DOC_PREFIX = 'GASマネージャー_文書控え_';
var BK_DOC_SLOTS = 5;
var BK_TABS_MAX = 20;
var LEDGER_MAX = 40;

// 見た目の決まり（どの棚も同じ決まりを使う）
var STYLE = {
  headBg: '#1F4E79', headFg: '#FFFFFF', border: '#9E9E9E', totalBg: '#F2F2F2',
  numFmt: '#,##0', numFmtDec: '#,##0.00', dateFmt: 'yyyy/mm/dd',
  colMin: 50, colMax: 360, px: 7, pad: 18
};

// ---------------------------------------------------------------- 入口

function doGet(e) { return json_({ ok: true, engine: 'shu-workspace-engine', version: ENGINE_VERSION }); }

function doPost(e) {
  var req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return json_({ ok: false, error: '荷物が JSON ではありません' }); }
  var a = req.action;
  if (a === 'ping') return json_({ ok: true, version: ENGINE_VERSION });
  if (a === 'render') {  // 見るだけ（書かない）ので鍵は掛けない
    try { var rr = actRender_(req); rr.version = ENGINE_VERSION; return json_(rr); }
    catch (err) { return json_({ ok: false, error: String(err && err.message || err), version: ENGINE_VERSION }); }
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return json_({ ok: false, error: '別の処理が走っています。少し待って撃ち直してください。', busy: true });
  try {
    var res;
    if (a === 'look') res = actLook_(req);
    else if (a === 'do') res = actDo_(req);
    else if (a === 'undo') res = actUndo_(req);
    else if (a === 'list') res = { ok: true, ledger: ledgerBrief_() };
    else res = { ok: false, error: '知らない action: ' + a };
    res.version = ENGINE_VERSION;
    return json_(res);
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message || err), version: ENGINE_VERSION });
  } finally { lock.releaseLock(); }
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function ArgError(msg) { this.message = msg; this.isArg = true; }
function Blocked(msg) { this.message = msg; this.isBlocked = true; }

// ---------------------------------------------------------------- 小道具

function props_() { return PropertiesService.getScriptProperties(); }
function getJson_(k, d) { var v = props_().getProperty(k); if (!v) return d; try { return JSON.parse(v); } catch (e) { return d; } }
function setJson_(k, v) { props_().setProperty(k, JSON.stringify(v)); }

function colLetter_(n) { var s = ''; while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }
function colNum_(s) {
  s = String(s).trim().toUpperCase();
  // 列記号（A〜ZZZ）以外を数に直すと桁外れの列番号になり「セル数の上限」で落ちる（11/12 実機で「金額」を渡して踏んだ）
  if (!/^[A-Z]{1,3}$/.test(s)) throw new ArgError('列「' + s + '」は列記号（A・B…）ではありません。見出しの名前で指すときは表の見出しと同じ文字で');
  var n = 0; for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64); return n;
}
function a1_(r, c, nr, nc) {
  var s = colLetter_(c) + r;
  if ((nr || 1) > 1 || (nc || 1) > 1) s += ':' + colLetter_(c + (nc || 1) - 1) + (r + (nr || 1) - 1);
  return s;
}
function wlen_(s) { s = String(s); var n = 0; for (var i = 0; i < s.length; i++) n += s.charCodeAt(i) > 255 ? 2 : 1; return n; }
function isBlank_(v) { return v === '' || v === null || v === undefined; }
function digest_(s) { return Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, s)).slice(0, 12); }
function q_(name) { return "'" + String(name).replace(/'/g, "''") + "'"; }

// ---------------------------------------------------------------- 対象を開く

function openTarget_(t) {
  if (!t || !t.id) throw new ArgError('対象のファイルが決まっていません');
  if (t.kind === 'doc') return { kind: 'doc', file: DocumentApp.openById(t.id) };
  return { kind: 'sheet', file: SpreadsheetApp.openById(t.id) };
}

function sheetOf_(ss, name, ctxDefault) {
  var nm = name || ctxDefault;
  if (!nm) return ss.getSheets()[0];
  var sh = ss.getSheetByName(nm);
  if (!sh) throw new ArgError('シート「' + nm + '」がありません。あるのは: ' + ss.getSheets().map(function (s) { return s.getName(); }).join('、'));
  return sh;
}

// ---------------------------------------------------------------- 表の形

function findTable_(sh) {
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  if (lr < 1 || lc < 1) return null;
  var vals = sh.getRange(1, 1, lr, lc).getValues();
  var nonEmpty = function (row) { return row.filter(function (v) { return !isBlank_(v); }).length; };
  var h = -1;
  for (var r = 0; r < vals.length; r++) { if (nonEmpty(vals[r]) >= 2) { h = r; break; } }
  if (h < 0) return null;
  var hdr = vals[h], fc = -1, lcol = -1;
  for (var c = 0; c < hdr.length; c++) if (!isBlank_(hdr[c])) { if (fc < 0) fc = c; lcol = c; }
  var last = h;
  for (var r2 = h + 1; r2 < vals.length; r2++) {
    var seg = vals[r2].slice(fc, lcol + 1);
    if (nonEmpty(seg) > 0) last = r2;
  }
  var t = { sheet: sh, headerRow: h + 1, firstCol: fc + 1, lastCol: lcol + 1, firstData: h + 2, lastData: last + 1, totalRow: 0, vals: vals };
  // 合計行：最終行の最初の文字セルが 合計/計 など
  if (last > h) {
    var first = String(vals[last][fc] === '' ? (vals[last][fc + 1] || '') : vals[last][fc]);
    if (/^(合計|総計|小計|計|total|sum)/i.test(first.trim())) { t.totalRow = last + 1; t.lastData = last; }
  }
  return t;
}
function needTable_(sh) {
  var t = findTable_(sh);
  if (!t) throw new ArgError('シート「' + sh.getName() + '」に表が見つかりません（見出しの行がありません）');
  return t;
}
function dataRange_(t) { return t.sheet.getRange(t.firstData, t.firstCol, Math.max(1, t.lastData - t.firstData + 1), t.lastCol - t.firstCol + 1); }
function headerNames_(t) { return t.vals[t.headerRow - 1].slice(t.firstCol - 1, t.lastCol).map(String); }
function colIndexOf_(t, ref) {
  if (typeof ref === 'number') return ref;
  var s = String(ref).trim();
  var names = headerNames_(t);
  var i = names.indexOf(s);
  if (i >= 0) return t.firstCol + i;
  if (/^[A-Za-z]{1,3}$/.test(s)) return colNum_(s);
  throw new ArgError('列「' + s + '」がありません。見出しは: ' + names.join('、'));
}
function isNumberCol_(t, ci) {
  var n = 0, tot = 0;
  for (var r = t.firstData; r <= t.lastData; r++) { var v = t.vals[r - 1][ci - 1]; if (isBlank_(v)) continue; tot++; if (typeof v === 'number') n++; }
  return tot > 0 && n / tot > 0.5;
}
function isNoCol_(t, ci) {
  var h = String(t.vals[t.headerRow - 1][ci - 1]).trim();
  return /^(no\.?|番号|#|№|id)$/i.test(h);
}

// ---------------------------------------------------------------- 指紋

function fingerSheet_(sh) {
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  var d = '';
  if (lr > 0 && lc > 0) {
    var rg = sh.getRange(1, 1, lr, lc);
    d = digest_(JSON.stringify(rg.getFormulas()) + JSON.stringify(rg.getDisplayValues()) + JSON.stringify(rg.getBackgrounds()) + JSON.stringify(rg.getFontWeights()) +
      JSON.stringify(rg.getFontColors()) + JSON.stringify(rg.getNumberFormats()) + JSON.stringify(rg.getHorizontalAlignments()));
  }
  return { rows: lr, cols: lc, d: digest_(d + '|' + sh.getName() + '|' + sh.getFrozenRows()) };
}
function fingerDoc_(doc) {
  var b = doc.getBody();
  return { n: b.getNumChildren(), d: digest_(b.getText() + '|' + docStructure_(b)) };
}
function docStructure_(b) {
  var o = [];
  for (var i = 0; i < b.getNumChildren(); i++) {
    var ch = b.getChild(i), t = String(ch.getType());
    if (t === 'PARAGRAPH') o.push('P' + ch.asParagraph().getHeading());
    else if (t === 'LIST_ITEM') o.push('L' + ch.asListItem().getNestingLevel());
    else o.push(t);
  }
  return o.join(',');
}
function sameFinger_(a, b) { return a && b && a.rows === b.rows && a.cols === b.cols && a.d === b.d && a.n === b.n; }

// ---------------------------------------------------------------- 台帳

function ledger_() { return getJson_('LEDGER', { seq: 0, items: [] }); }
function ledgerSave_(l) { while (l.items.length > LEDGER_MAX) l.items.shift(); setJson_('LEDGER', l); }
function ledgerBrief_() {
  return ledger_().items.slice().reverse().map(function (it) {
    return { n: it.n, time: it.time, target: it.name, kind: it.kind, what: it.what, undone: !!it.undone };
  });
}

// ---------------------------------------------------------------- 控え（シート）

function bkBook_() {
  var id = props_().getProperty('BK_BOOK');
  if (id) { try { return SpreadsheetApp.openById(id); } catch (e) { } }
  var b = SpreadsheetApp.create(BK_BOOK_NAME);
  props_().setProperty('BK_BOOK', b.getId());
  return b;
}
function bkTabName_(n, sheetId) { return 'ws' + n + '_' + sheetId; }
function pruneTabs_(book) {
  var tabs = book.getSheets().filter(function (s) { return /^ws\d+_/.test(s.getName()); });
  tabs.sort(function (a, b) { return parseInt(a.getName().slice(2)) - parseInt(b.getName().slice(2)); });
  var extra = tabs.length - BK_TABS_MAX;
  var left = book.getSheets().length;
  for (var i = 0; i < extra && left > 1; i++) { book.deleteSheet(tabs[i]); left--; }
}
function backupSheets_(ss, sheets, n) {
  if (!sheets.length) return [];
  var book = bkBook_(), out = [];
  sheets.forEach(function (sh) {
    var old = book.getSheetByName(bkTabName_(n, sh.getSheetId()));
    if (old && book.getSheets().length > 1) book.deleteSheet(old);
    var c = sh.copyTo(book);
    c.setName(bkTabName_(n, sh.getSheetId()));
    out.push({ id: sh.getSheetId(), name: sh.getName(), index: sh.getIndex(), tab: c.getName(),
      widths: colWidths_(sh), frozenR: sh.getFrozenRows(), frozenC: sh.getFrozenColumns() });
  });
  // 控えブックに最初からある白紙シートを外す
  var first = book.getSheetByName('シート1') || book.getSheetByName('Sheet1');
  if (first && book.getSheets().length > 1) { try { book.deleteSheet(first); } catch (e) { } }
  pruneTabs_(book);
  return out;
}
// 列幅は表のある列だけ記録する（1 回の API 呼びが約 0.1 秒なので、全列・全行は読まない。行の高さは戻しの対象外）
function discardBackup_(bk) {
  if (!bk || !bk.length) return;
  try {
    var book = bkBook_();
    bk.forEach(function (b) { var t = book.getSheetByName(b.tab); if (t && book.getSheets().length > 1) book.deleteSheet(t); });
  } catch (e) { }
}
function colWidths_(sh) { var o = [], lc = Math.min(Math.max(sh.getLastColumn(), 1), 30); for (var c = 1; c <= lc; c++) o.push(sh.getColumnWidth(c)); return o; }

// 控えのタブから、元のシートの中へ戻す（シートは作り直さないので他シートからの参照が切れない）
function restoreSheet_(ss, b) {
  var book = bkBook_();
  var tab = book.getSheetByName(b.tab);
  if (!tab) throw new Error('控えのタブ「' + b.tab + '」が見つかりません（古くて消えた可能性があります）');
  var orig = ss.getSheets().filter(function (s) { return s.getSheetId() === b.id; })[0];
  var tmp = tab.copyTo(ss);
  try {
    if (!orig) {
      // 元のシートが消えていた：控えを新しいシートとして戻す
      tmp.setName(b.name); ss.setActiveSheet(tmp); ss.moveActiveSheet(b.index + 1); tmp = null;
      return;
    }
    if (orig.getName() !== b.name) orig.setName(b.name);
    var lr = tmp.getMaxRows(), lc = tmp.getMaxColumns();
    var f = orig.getFilter(); if (f) f.remove();
    orig.getRange(1, 1, orig.getMaxRows(), orig.getMaxColumns()).breakApart();
    orig.clear();
    if (orig.getMaxRows() < lr) orig.insertRowsAfter(orig.getMaxRows(), lr - orig.getMaxRows());
    else if (orig.getMaxRows() > lr) orig.deleteRows(lr + 1, orig.getMaxRows() - lr);
    if (orig.getMaxColumns() < lc) orig.insertColumnsAfter(orig.getMaxColumns(), lc - orig.getMaxColumns());
    else if (orig.getMaxColumns() > lc) orig.deleteColumns(lc + 1, orig.getMaxColumns() - lc);
    tmp.getRange(1, 1, lr, lc).copyTo(orig.getRange(1, 1, lr, lc));
    for (var c = 0; c < b.widths.length && c < lc; c++) orig.setColumnWidth(c + 1, b.widths[c]);
    orig.setFrozenRows(b.frozenR); orig.setFrozenColumns(b.frozenC);
    if (orig.getIndex() !== b.index) { ss.setActiveSheet(orig); ss.moveActiveSheet(b.index); }
  } finally { if (tmp) { try { ss.deleteSheet(tmp); } catch (e) { } } }
}

// ---------------------------------------------------------------- 控え（文書）

function docBkIds_() { return getJson_('BK_DOCS', []); }
function docBkSlotDoc_(slot) {
  var ids = docBkIds_(), id = ids[slot];
  if (id) { try { return DocumentApp.openById(id); } catch (e) { } }
  var d = DocumentApp.create(BK_DOC_PREFIX + (slot + 1));
  ids[slot] = d.getId(); setJson_('BK_DOCS', ids);
  return d;
}
// body.clear() が「最終段落は削除できません」で落ちる文書がある（末尾が表・箇条書きのとき）ので、手で外す道を持つ
function clearBody_(b) {
  try { b.clear(); return; } catch (e) { }
  b.appendParagraph('');
  for (var i = b.getNumChildren() - 2; i >= 0; i--) { try { b.removeChild(b.getChild(i)); } catch (e2) { } }
}
function copyBody_(src, dst) {
  clearBody_(dst);
  var afterTable = false;
  for (var i = 0; i < src.getNumChildren(); i++) {
    var el = src.getChild(i).copy(), t = String(el.getType());
    if (afterTable && t === 'PARAGRAPH' && el.asParagraph().getText() === '') { afterTable = false; continue; }
    afterTable = false;
    if (t === 'PARAGRAPH') dst.appendParagraph(el);
    else if (t === 'LIST_ITEM') dst.appendListItem(el);
    else if (t === 'TABLE') { dst.appendTable(el); afterTable = true; }
    else if (t === 'HORIZONTAL_RULE') dst.appendHorizontalRule();
    else if (t === 'PAGE_BREAK') dst.appendPageBreak();
  }
  if (dst.getNumChildren() > 1 && dst.getChild(0).getType() == DocumentApp.ElementType.PARAGRAPH && dst.getChild(0).asParagraph().getText() === '') {
    try { dst.removeChild(dst.getChild(0)); }
    catch (e) { try { dst.removeChild(dst.getChild(dst.getNumChildren() - 1)); } catch (e2) { } }   // 空の文書：最終段落は消せないので、もう一方を外す
  }
}
// 控え文書の枠：今の台帳で使われていない枠を先に使い、全部使われていれば一番古い枠を上書きする
function pickSlot_() {
  var seqs = getJson_('BK_DOC_SEQ', {}), live = {};
  ledger_().items.forEach(function (it) { if (it.doc) live[it.n] = 1; });
  var best = -1, bestSeq = Infinity;
  for (var i = 0; i < BK_DOC_SLOTS; i++) {
    if (seqs[i] === undefined || !live[seqs[i]]) return i;
    if (seqs[i] < bestSeq) { bestSeq = seqs[i]; best = i; }
  }
  return best;
}
function backupDoc_(doc, n) {
  var slot = pickSlot_();
  var bk = docBkSlotDoc_(slot);
  copyBody_(doc.getBody(), bk.getBody());
  bk.saveAndClose();
  var slots = getJson_('BK_DOC_SEQ', {}); slots[slot] = n; setJson_('BK_DOC_SEQ', slots);
  return { slot: slot };
}
function restoreDoc_(doc, b, n) {
  var slots = getJson_('BK_DOC_SEQ', {});
  if (slots[b.slot] !== n) throw new Error('文書の控え（枠' + (b.slot + 1) + '）はその後の控えで上書きされました');
  var bk = docBkSlotDoc_(b.slot);
  copyBody_(bk.getBody(), doc.getBody());
}

// ---------------------------------------------------------------- do

function summarizeOps_(ops) { return ops.map(function (o) { return o.shelf; }).join('・'); }

function actDo_(req) {
  var cache = CacheService.getScriptCache();
  if (req.call_id) {
    var hit = cache.get('call_' + req.call_id);
    if (hit) { var r0 = JSON.parse(hit); r0.replayed = true; return r0; }
  }
  var res = runDo_(req);
  if (req.call_id) { try { var s = JSON.stringify(res); if (s.length < 90000) cache.put('call_' + req.call_id, s, 21600); } catch (e) { } }
  return res;
}

function runDo_(req) {
  var ops = req.ops || [];
  if (!ops.length) return { ok: false, error: 'ops が空です' };
  var t = req.target || {}, created = null, file, kind;
  if (t.new) {
    kind = t.kind === 'doc' ? 'doc' : 'sheet';
    file = kind === 'doc' ? DocumentApp.create(t.new) : SpreadsheetApp.create(t.new);
    created = { id: file.getId(), name: t.new, kind: kind, url: file.getUrl() };
  } else {
    var o = openTarget_(t); file = o.file; kind = o.kind;
  }
  var l = ledger_(); l.seq++; var n = l.seq; setJson_('LEDGER', l);
  var ctx = { kind: kind, file: file, ss: kind === 'sheet' ? file : null, doc: kind === 'doc' ? file : null,
    sheetName: t.sheet || '', ok: !!req.ok, changed: [], notes: [], remaining: [], createdSheets: [], n: n, isNew: !!created };
  var entry = { n: n, time: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'), id: file.getId(),
    name: file.getName(), kind: kind, what: summarizeOps_(ops), isNew: !!created };
  var bk = null, tm = { t0: Date.now() };
  try {
    if (!created) {
      if (kind === 'sheet') {
        var names = touchedSheets_(ctx, ops);
        bk = backupSheets_(ctx.ss, names, n);
        entry.sheets = bk;
        entry.before = {}; names.forEach(function (sh0) { entry.before[sh0.getSheetId()] = fingerSheet_(sh0); });
      } else { entry.doc = backupDoc_(ctx.doc, n); entry.beforeDoc = fingerDoc_(ctx.doc); }
    }
    ctx.bk = bk; tm.backup = Date.now() - tm.t0;
    for (var i = 0; i < ops.length; i++) {
      var op = ops[i], fn = SHELF[op.shelf];
      if (!fn) throw new ArgError('棚「' + op.shelf + '」はありません');
      if (fn.kind && fn.kind !== kind) throw new ArgError('棚「' + op.shelf + '」は' + (fn.kind === 'doc' ? '文書' : 'シート') + '用です（今の相手は' + (kind === 'doc' ? '文書' : 'スプレッドシート') + '）');
      ctx.opNo = i + 1; ctx.opName = op.shelf;
      fn(ctx, op);
    }
    SpreadsheetApp.flush();
    if (kind === 'doc') { ctx.doc.saveAndClose(); ctx.doc = DocumentApp.openById(entry.id); file = ctx.doc; }
    // 書き終わりの指紋
    if (kind === 'sheet') {
      entry.after = {};
      (entry.sheets || []).forEach(function (b) { var s = byId_(ctx.ss, b.id); if (s) entry.after[b.id] = fingerSheet_(s); });
      entry.created = {};
      ctx.createdSheets.forEach(function (nm) { var s = ctx.ss.getSheetByName(nm); if (s) entry.created[nm] = fingerSheet_(s); });
    } else entry.afterDoc = fingerDoc_(ctx.doc);
    // 何も変わらなかった（すでにその状態）なら、記録も控えも残さない（undo が空振りしないように）
    if (!created && isNoop_(ops, entry, ctx)) {
      discardBackup_(bk);
      return { ok: true, target: tgt_(ctx, file), changed: [], notes: ['変更はありませんでした（すでにその状態です）'].concat(ctx.notes.filter(function (x) { return x.indexOf('変更なし') < 0; })), remaining: ctx.remaining, backup: 0, ms: { total: Date.now() - tm.t0 } };
    }
    l = ledger_(); l.items.push(entry); ledgerSave_(l);
    tm.total = Date.now() - tm.t0;
    var out = { ok: true, target: tgt_(ctx, file), changed: ctx.changed, notes: ctx.notes, remaining: ctx.remaining, backup: created ? 0 : n, ms: tm };
    if (created) { out.created = created; }
    return out;
  } catch (err) {
    var restored = false, why = '';
    try {
      if (created) resetNew_(ctx, kind);
      else if (kind === 'sheet') { restoreAll_(ctx.ss, bk || [], ctx.createdSheets); }
      else if (entry.doc) { restoreDoc_(DocumentApp.openById(entry.id), entry.doc, n); }
      restored = true;
      discardBackup_(bk);
    } catch (e2) { why = String(e2.message || e2); }
    var out2 = { ok: false, error: String(err.message || err), where: '棚 #' + (ctx.opNo || 0) + ' ' + (ctx.opName || ''),
      restored: restored, restore_error: why, blocked: !!err.isBlocked, arg: !!err.isArg, target: tgt_(ctx, file), stack: String(err.stack || '').slice(0, 400) };
    if (created) out2.created = created;
    return out2;
  }
}

// 変更なしの判定。棚の「触る:」（CATALOG）に、指紋に出る物が 1 つでもある棚は指紋で比べる。
// 指紋に出る物＝値・シート構成・固定、シートでは書式も（文書の指紋は文字と見出し構造だけなので、文書の書式は出ない）。
// フィルタ・幅 は指紋に出ない（棚が「付随して触る」だけなら、判定は前のまま指紋）。
// 指紋に出る物が 1 つも無い棚（幅だけ・文書の書式だけ 等）を含むときは、棚が報告した変更（ctx.changed）が空のときだけ「変更なし」
var FINGER_ITEMS_ = ['値', 'シート構成', '固定'];
function fingerOnly_(ops, kind) {
  var vis = kind === 'sheet' ? FINGER_ITEMS_.concat(['書式']) : FINGER_ITEMS_;
  return ops.every(function (o) {
    var c = CATALOG[o.shelf];
    return !!c && c.touch.some(function (t) { return vis.indexOf(t) >= 0; });
  });
}
function isNoop_(ops, entry, ctx) {
  if (ctx.createdSheets.length) return false;
  if (!fingerOnly_(ops, ctx.kind)) return ctx.changed.length === 0;
  if (ctx.kind === 'sheet') {
    if (!entry.sheets || !entry.sheets.length) return false;
    return entry.sheets.every(function (b) { return sameFinger_(entry.before[b.id], entry.after[b.id]); });
  }
  return sameFinger_(entry.beforeDoc, entry.afterDoc);
}

function tgt_(ctx, file) {
  var o = { id: file.getId(), name: file.getName(), kind: ctx.kind, url: file.getUrl() };
  if (ctx.kind === 'sheet') o.sheet = ctx.curSheet || ctx.sheetName || ctx.ss.getSheets()[0].getName();
  return o;
}
function byId_(ss, id) { return ss.getSheets().filter(function (s) { return s.getSheetId() === id; })[0]; }

// 書き換える恐れのあるシートを控える。控えるシートは棚の札の「控え:」（CATALOG の backup）で決まる
//   今＝sheet 引数（無ければ今のシート）／名前＝name 引数／先＝into 引数／全部＝全シート／なし
function touchedSheets_(ctx, ops) {
  var ss = ctx.ss, seen = {}, out = [];
  var add = function (name) {
    var s = name ? ss.getSheetByName(name) : null;
    if (s && !seen[s.getSheetId()]) { seen[s.getSheetId()] = 1; out.push(s); }
  };
  var def = ctx.sheetName || ss.getSheets()[0].getName();
  ops.forEach(function (op) {
    var c = CATALOG[op.shelf], bk = c && c.backup ? c.backup : ['今'];
    bk.forEach(function (b) {
      if (b === '今') add(op.sheet || def);
      else if (b === '名前') add(op.name);
      else if (b === '先') add(op.into);
      else if (b === '全部') ss.getSheets().forEach(function (s) { add(s.getName()); });
    });
  });
  return out;
}

function restoreAll_(ss, bk, createdNames) {
  (createdNames || []).forEach(function (nm) { var s = ss.getSheetByName(nm); if (s && ss.getSheets().length > 1) ss.deleteSheet(s); });
  (bk || []).forEach(function (b) { restoreSheet_(ss, b); });
}
function resetNew_(ctx, kind) {
  if (kind === 'sheet') {
    var shs = ctx.ss.getSheets();
    for (var i = shs.length - 1; i >= 1; i--) ctx.ss.deleteSheet(shs[i]);
    shs[0].clear(); shs[0].setName('シート1');
  } else { clearBody_(ctx.doc.getBody()); }
}

// ---------------------------------------------------------------- undo

function actUndo_(req) {
  var l = ledger_(), it;
  if (req.to) it = l.items.filter(function (x) { return x.n === parseInt(req.to); })[0];
  else {
    // 「直前を戻す」は今の相手のファイルの直前だけ（台帳は全ファイル共通なので、別のファイルを戻さない。11/12 実機で踏んだ）
    for (var i = l.items.length - 1; i >= 0; i--) {
      var x = l.items[i];
      if (!x.undone && !x.isUndo && (!req.target_id || x.id === req.target_id)) { it = x; break; }
    }
  }
  if (!it) return { ok: false, error: req.target_id && !req.to ? '今の相手のファイルには、戻せる記録がありません（ws_undo(list=True) で全体の台帳）' : '戻せる記録がありません' };
  if (it.isNew && !it.sheets && !it.doc) return { ok: false, error: '新しく作ったファイルは undo では消しません（消すのは人です）: ' + it.name };
  var file = it.kind === 'doc' ? DocumentApp.openById(it.id) : SpreadsheetApp.openById(it.id);
  // 指紋：道具が書いた後に人が手で直していないか
  var hand = [];
  if (it.kind === 'sheet') {
    var ss = file;
    (it.sheets || []).forEach(function (b) {
      var s = byId_(ss, b.id);
      if (s && it.after && it.after[b.id] && !sameFinger_(it.after[b.id], fingerSheet_(s))) hand.push(b.name);
    });
    Object.keys(it.created || {}).forEach(function (nm) {
      var s = ss.getSheetByName(nm);
      if (s && !sameFinger_(it.created[nm], fingerSheet_(s))) hand.push(nm);
    });
  } else if (it.afterDoc && !sameFinger_(it.afterDoc, fingerDoc_(file))) hand.push(file.getName());
  if (hand.length && !req.ok)
    return { ok: false, needs_ok: true, error: '道具が書いた後に手で直した所があります（戻すと消えます）: ' + hand.join('、') + '。それでも戻すなら ok=True', target: { id: it.id, name: it.name, kind: it.kind, url: file.getUrl() } };
  // 戻す前の状態も控えに取る（undo の undo）
  l.seq++; var n = l.seq; setJson_('LEDGER', l);
  var entry = { n: n, time: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'), id: it.id, name: it.name, kind: it.kind, what: 'undo #' + it.n, isUndo: true };
  try {
    if (it.kind === 'sheet') {
      var ss2 = file, names = [];
      (it.sheets || []).forEach(function (b) { var s = byId_(ss2, b.id); if (s) names.push(s); });
      entry.sheets = backupSheets_(ss2, names, n);
      var made = Object.keys(it.created || {});
      made.forEach(function (nm) { var s = ss2.getSheetByName(nm); if (s && ss2.getSheets().length > 1) ss2.deleteSheet(s); });
      (it.sheets || []).forEach(function (b) { restoreSheet_(ss2, b); });
      entry.after = {}; (entry.sheets || []).forEach(function (b) { var s = byId_(ss2, b.id); if (s) entry.after[b.id] = fingerSheet_(s); });
    } else {
      entry.doc = backupDoc_(file, n);
      restoreDoc_(file, it.doc, it.n);
      file.saveAndClose(); file = DocumentApp.openById(it.id);
      entry.afterDoc = fingerDoc_(file);
    }
  } catch (err) {
    return { ok: false, error: '戻せませんでした: ' + String(err.message || err), target: { id: it.id, name: it.name, kind: it.kind, url: file.getUrl() } };
  }
  it.undone = true; l.items.push(entry); ledgerSave_(l);
  return { ok: true, undone: it.n, backup: n, what: it.what, target: { id: it.id, name: it.name, kind: it.kind, url: file.getUrl() } };
}

// ---------------------------------------------------------------- look

function actLook_(req) {
  var t = req.target || {}, o = openTarget_(t), out = { ok: true };
  if (o.kind === 'sheet') {
    var ss = o.file;
    out.target = { id: ss.getId(), name: ss.getName(), kind: 'sheet', url: ss.getUrl() };
    out.sheets = ss.getSheets().map(function (s) { return { name: s.getName(), rows: s.getLastRow(), cols: s.getLastColumn() }; });
    var sh = sheetOf_(ss, req.sheet || t.sheet, '');
    out.target.sheet = sh.getName();
    var tb = findTable_(sh);
    if (tb) {
      out.table = { header_row: tb.headerRow, first_col: colLetter_(tb.firstCol), last_col: colLetter_(tb.lastCol), data: tb.firstData + '-' + tb.lastData,
        total_row: tb.totalRow || null, columns: headerNames_(tb).map(function (h, i) { var ci = tb.firstCol + i; return { col: colLetter_(ci), name: h, number: isNumberCol_(tb, ci) }; }) };
    }
    if (req.range) {
      var rg = sh.getRange(req.range);
      out.range = req.range; out.values = rg.getDisplayValues(); out.formulas = rg.getFormulas();
      if (req.formats) out.formats = { bold: rg.getFontWeights(), color: rg.getFontColorObjects().map(function (r) { return r.map(function (c) { return c ? (c.getColorType() == SpreadsheetApp.ColorType.RGB ? c.asRgbColor().asHexString() : 'theme') : ''; }); }), bg: rg.getBackgrounds(), numfmt: rg.getNumberFormats(), widths: (function () { var o = []; for (var c = 0; c < rg.getNumColumns(); c++) o.push(sh.getColumnWidth(rg.getColumn() + c)); return o; })() };
    }
  } else {
    var d = o.file, b = d.getBody();
    out.target = { id: d.getId(), name: d.getName(), kind: 'doc', url: d.getUrl() };
    var heads = [], n = b.getNumChildren();
    for (var i = 0; i < n; i++) {
      var ch = b.getChild(i), ty = String(ch.getType());
      if (ty === 'PARAGRAPH') {
        var p = ch.asParagraph(), h = String(p.getHeading());
        if (/^HEADING(\d)/.test(h)) heads.push({ no: i, level: parseInt(h.slice(7)), text: p.getText() });
      }
    }
    out.paragraphs = n; out.headings = heads;
    out.outline = [];
    for (var j = 0; j < Math.min(n, req.limit || 80); j++) {
      var c2 = b.getChild(j), t2 = String(c2.getType());
      var txt = t2 === 'PARAGRAPH' ? c2.asParagraph().getText() : t2 === 'LIST_ITEM' ? c2.asListItem().getText() : t2 === 'TABLE' ? '〔表 ' + c2.asTable().getNumRows() + '行〕' : '';
      out.outline.push(j + ': ' + t2.charAt(0) + ' ' + String(txt).slice(0, 40));
    }
  }
  return out;
}

// ---------------------------------------------------------------- 目（見た目を読む・書かない）
// 手元で描き直して画像にするための材料を、範囲ごとの一括読みで返す。
var RENDER_MAX_ROWS = 100, RENDER_MAX_COLS = 26, RENDER_MAX_BLOCKS = 200;

function hexOf_(c) {
  try { return c && c.getColorType() == SpreadsheetApp.ColorType.RGB ? c.asRgbColor().asHexString() : ''; } catch (e) { return ''; }
}

function actRender_(req) {
  var t = req.target || {}, o = openTarget_(t);
  return o.kind === 'sheet' ? renderSheet_(o.file, req) : renderDoc_(o.file, req);
}

function renderSheet_(ss, req) {
  var sh = sheetOf_(ss, req.sheet || (req.target || {}).sheet, '');
  var rg;
  if (req.range) rg = sh.getRange(req.range);
  else {
    var lr = Math.max(sh.getLastRow(), 1), lc = Math.max(sh.getLastColumn(), 1);
    rg = sh.getRange(1, 1, Math.min(lr + 1, RENDER_MAX_ROWS), Math.min(lc, RENDER_MAX_COLS));
  }
  var r0 = rg.getRow(), c0 = rg.getColumn();
  var nr = Math.min(rg.getNumRows(), RENDER_MAX_ROWS), nc = Math.min(rg.getNumColumns(), RENDER_MAX_COLS);
  var cut = nr < rg.getNumRows() || nc < rg.getNumColumns();
  rg = sh.getRange(r0, c0, nr, nc);
  var widths = [], heights = [];
  for (var c = 0; c < nc; c++) widths.push(sh.getColumnWidth(c0 + c));
  for (var r = 0; r < nr; r++) heights.push(sh.getRowHeight(r0 + r));
  var out = {
    ok: true, kind: 'sheet',
    target: { id: ss.getId(), name: ss.getName(), kind: 'sheet', url: ss.getUrl(), sheet: sh.getName() },
    range: rg.getA1Notation(), row0: r0, col0: c0, cut: cut, frozen: sh.getFrozenRows(),
    values: rg.getDisplayValues(),
    bg: rg.getBackgrounds(),
    color: rg.getFontColorObjects().map(function (row) { return row.map(hexOf_); }),
    bold: rg.getFontWeights(), italic: rg.getFontStyles(), size: rg.getFontSizes(),
    align: rg.getHorizontalAlignments(), widths: widths, heights: heights,
    merges: rg.getMergedRanges().map(function (m) { return { r: m.getRow() - r0, c: m.getColumn() - c0, nr: m.getNumRows(), nc: m.getNumColumns() }; }),
    borders: null
  };
  // 罫線と、条件付き書式を含む実際の背景色は SpreadsheetApp では読めないので、Sheets の高度なサービスで（無ければ省く）
  try {
    var g = Sheets.Spreadsheets.get(ss.getId(), {
      ranges: [q_(sh.getName()) + '!' + out.range],
      fields: 'sheets(data(rowData(values(effectiveFormat(borders,backgroundColor)))))'
    });
    var rows = (((g.sheets || [])[0] || {}).data || [])[0];
    rows = rows && rows.rowData || [];
    var side = function (b) { return b && b.style && b.style !== 'NONE' ? (b.style.indexOf('DOUBLE') >= 0 ? 'D' : b.style.indexOf('THICK') >= 0 || b.style.indexOf('MEDIUM') >= 0 ? 'T' : 'S') : ''; };
    var hex = function (col) {
      if (!col) return '';
      var f = function (v) { var s = Math.round((v || 0) * 255).toString(16); return s.length < 2 ? '0' + s : s; };
      return '#' + f(col.red) + f(col.green) + f(col.blue);
    };
    out.borders = []; out.ebg = [];
    for (var i = 0; i < nr; i++) {
      var vs = (rows[i] && rows[i].values) || [], br = [], eb = [];
      for (var j = 0; j < nc; j++) {
        var ef = (vs[j] && vs[j].effectiveFormat) || {}, b = ef.borders || {};
        br.push(side(b.top) + '|' + side(b.right) + '|' + side(b.bottom) + '|' + side(b.left));
        eb.push(ef.backgroundColor ? hex(ef.backgroundColor) : '');
      }
      out.borders.push(br); out.ebg.push(eb);
    }
  } catch (e) { out.borders_note = '罫線は読めませんでした（' + String(e.message || e).slice(0, 80) + '）'; }
  return out;
}

function renderDoc_(d, req) {
  var b = d.getBody(), n = b.getNumChildren(), blocks = [];
  var lim = Math.min(n, req.limit || RENDER_MAX_BLOCKS);
  var alignOf = function (p) { var a = p.getAlignment(); return a ? String(a).toLowerCase() : ''; };
  var runsOf = function (el) {  // 太字・斜体・色の区切りごとに文字を分ける
    var tx = el.editAsText(), s = tx.getText(), idx = tx.getTextAttributeIndices(), runs = [];
    for (var k = 0; k < idx.length; k++) {
      var a = idx[k], z = k + 1 < idx.length ? idx[k + 1] : s.length;
      if (z <= a) continue;
      runs.push({ t: s.slice(a, z), b: !!tx.isBold(a), i: !!tx.isItalic(a), c: tx.getForegroundColor(a) || '' });
    }
    return runs.length ? runs : [{ t: s, b: false, i: false, c: '' }];
  };
  for (var i = 0; i < lim; i++) {
    var ch = b.getChild(i), ty = String(ch.getType());
    if (ty === 'PARAGRAPH') {
      var p = ch.asParagraph(), h = String(p.getHeading()), m = /^HEADING(\d)/.exec(h);
      blocks.push({ k: m ? 'h' + m[1] : (h === 'TITLE' ? 'title' : h === 'SUBTITLE' ? 'subtitle' : 'p'), runs: runsOf(p), align: alignOf(p) });
    } else if (ty === 'LIST_ITEM') {
      var li = ch.asListItem(), g = String(li.getGlyphType());
      blocks.push({ k: 'li', runs: runsOf(li), level: li.getNestingLevel(), ordered: /NUMBER|LATIN|ROMAN/.test(g) });
    } else if (ty === 'TABLE') {
      var tb = ch.asTable(), rows = [];
      for (var r = 0; r < tb.getNumRows(); r++) {
        var row = tb.getRow(r), cells = [];
        for (var c = 0; c < row.getNumCells(); c++) {
          var cell = row.getCell(c);
          var ct = cell.getText();
          cells.push({ t: ct, bg: cell.getBackgroundColor() || '', b: ct.length > 0 ? !!cell.editAsText().isBold(0) : false });
        }
        rows.push(cells);
      }
      blocks.push({ k: 'table', rows: rows });
    } else if (ty === 'HORIZONTAL_RULE') blocks.push({ k: 'hr' });
    else if (ty === 'PAGE_BREAK') blocks.push({ k: 'hr' });
  }
  return { ok: true, kind: 'doc', target: { id: d.getId(), name: d.getName(), kind: 'doc', url: d.getUrl() }, blocks: blocks, cut: n > lim, total: n };
}

// ---------------------------------------------------------------- 棚（共通）
// 棚の本体は ws_shelves/*.gs。名前・題・引数・控え・触る物は棚の札（頭のコメント）が正で、道具が Catalog に写す。

var SHELF = {};
function sheetCtx_(ctx, op) {
  var sh = sheetOf_(ctx.ss, op.sheet, ctx.sheetName);
  ctx.curSheet = sh.getName();
  return sh;
}
function note_(ctx, s) { ctx.notes.push(s); }
function chg_(ctx, sh, a1, what) { ctx.changed.push((sh ? sh.getName() + '!' : '') + a1 + (what ? ' ' + what : '')); }
function need_(op, keys) { keys.forEach(function (k) { if (op[k] === undefined || op[k] === null || op[k] === '') throw new ArgError('棚「' + op.shelf + '」に「' + k + '」が要ります'); }); }
function guardDelete_(ctx, msg) { if (!ctx.ok) throw new Blocked(msg + '（人の値を消すので、「消してよい」の承認＝ok=True が要ります）'); }
function guardOverwrite_(ctx, rg, msg) {
  if (ctx.ok) return;
  var vals = rg.getValues();
  var r0 = rg.getRow(), c0 = rg.getColumn();
  var hit = 0, first3 = [];
  for (var r = 0; r < vals.length; r++) {
    for (var c = 0; c < vals[r].length; c++) {
      var v = vals[r][c];
      if (v !== '' && v !== null && v !== undefined) {
        hit++;
        if (first3.length < 3) first3.push(a1_(r0 + r, c0 + c));
      }
    }
  }
  if (hit > 0) {
    var desc = (msg ? msg + '（' : '（') + '書く先に空でないセルが ' + hit + ' 個あります: ' + first3.join('・') + (hit > 3 ? ' など' : '') + '。「上書きしてよい」の承認＝ok=True が要ります）';
    throw new Blocked(desc);
  }
}
function rgb_(s) {
  if (s === undefined || s === null || s === '') return null;
  if (typeof s !== 'string') return s;
  var str = s.trim();
  if (str === 'なし' || str.toLowerCase() === 'none' || str.toLowerCase() === 'transparent' || str.toLowerCase() === 'clear') return null;
  if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(str)) {
    if (str.length === 4) {
      return ('#' + str[1] + str[1] + str[2] + str[2] + str[3] + str[3]).toUpperCase();
    }
    return str.toUpperCase();
  }
  var map = {
    '黒': '#000000', 'black': '#000000',
    '白': '#FFFFFF', 'white': '#FFFFFF',
    '赤': '#FF0000', 'red': '#FF0000',
    '青': '#0000FF', 'blue': '#0000FF',
    '緑': '#008000', 'green': '#008000',
    '黄': '#FFFF00', 'yellow': '#FFFF00',
    '橙': '#FFA500', 'オレンジ': '#FFA500', 'orange': '#FFA500',
    '紫': '#800080', 'purple': '#800080',
    '桃': '#FFC0CB', 'ピンク': '#FFC0CB', 'pink': '#FFC0CB',
    '灰': '#808080', '灰色': '#808080', 'グレー': '#808080', 'gray': '#808080', 'grey': '#808080',
    '水色': '#00FFFF', 'シアン': '#00FFFF', 'cyan': '#00FFFF', 'lightblue': '#ADD8E6',
    '紺': '#000080', 'ネイビー': '#000080', 'navy': '#000080',
    '茶': '#8B4513', '茶色': '#8B4513', 'brown': '#8B4513',
    '薄赤': '#FCE4D6', '薄青': '#D9E1F2', '薄緑': '#E2EFDA', '薄黄': '#FFF2CC', '薄灰': '#F2F2F2', '薄灰色': '#F2F2F2',
    'lightred': '#FCE4D6', 'lightgreen': '#E2EFDA', 'lightyellow': '#FFF2CC', 'lightgray': '#F2F2F2'
  };
  var k = str.toLowerCase();
  if (map[k] !== undefined) return map[k];
  if (map[str] !== undefined) return map[str];
  throw new ArgError('知らない色の名前です: 「' + str + '」');
}
function shiftFormula_(f, off) {
  if (!off || typeof f !== 'string' || f.charAt(0) !== '=') return f;
  return f.replace(/(\$?[A-Z]{1,3}\$?)(\d+)/g, function (m, c, r) { return c.indexOf('$') >= 0 && /\$$/.test(c) ? m : c + (parseInt(r) + off); });
}
