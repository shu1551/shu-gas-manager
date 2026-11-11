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
function colNum_(s) { s = String(s).toUpperCase(); var n = 0; for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64); return n; }
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
      if (!fn) throw new ArgError('棚「' + op.shelf + '」はありません。あるのは: ' + Object.keys(SHELF).join('、'));
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

// 指紋に出ない変更（列幅・文書の書式）を含む棚があるときは「変わらない」と断定しない
function isNoop_(ops, entry, ctx) {
  if (ctx.createdSheets.length) return false;
  if (ops.some(function (o) { return o.shelf === 'width' || o.shelf === 'doc.style'; })) return false;
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

// 書き換える恐れのあるシートを控える（棚が触るシート名＋既定のシート）
function touchedSheets_(ctx, ops) {
  var ss = ctx.ss, seen = {}, out = [];
  var add = function (name) {
    var s = name ? ss.getSheetByName(name) : null;
    if (s && !seen[s.getSheetId()]) { seen[s.getSheetId()] = 1; out.push(s); }
  };
  var def = ctx.sheetName || ss.getSheets()[0].getName();
  ops.forEach(function (op) {
    if (op.shelf === 'table.new' || op.shelf === 'summary') { if (op.shelf === 'summary') add(op.sheet || def); add(op.into || (op.shelf === 'table.new' ? op.sheet : null)); return; }
    if (op.shelf === 'sheet.add') { add(op.name); add(op.rename && op.rename.from); add(op.move && op.move.name); if (op.rename || op.move) ss.getSheets().forEach(function (s) { add(s.getName()); }); return; }
    add(op.sheet || def);
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
  else { for (var i = l.items.length - 1; i >= 0; i--) if (!l.items[i].undone && !l.items[i].isUndo) { it = l.items[i]; break; } }
  if (!it) return { ok: false, error: '戻せる記録がありません' };
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
function shiftFormula_(f, off) {
  if (!off || typeof f !== 'string' || f.charAt(0) !== '=') return f;
  return f.replace(/(\$?[A-Z]{1,3}\$?)(\d+)/g, function (m, c, r) { return c.indexOf('$') >= 0 && /\$$/.test(c) ? m : c + (parseInt(r) + off); });
}

// ---------------------------------------------------------------- 棚：作る

SHELF['table.new'] = function (ctx, op) {
  need_(op, ['headers']);
  var ss = ctx.ss, rows = op.rows || [], headers = op.headers;
  var name = op.sheet || op.title || '表';
  var sh = ss.getSheetByName(name);
  var title = op.title || '';
  var off = title ? 2 : 0;
  var hr = 1 + off, nc = headers.length;
  var grid = [headers.map(String)];
  rows.forEach(function (r, i) {
    var row = r.slice(); while (row.length < nc) row.push('');
    grid.push(row.slice(0, nc).map(function (v) { return typeof v === 'string' ? shiftFormula_(v, off) : v; }));
  });
  var numCol = op.number ? colNum_(op.number) : 0;
  if (numCol) for (var i = 1; i < grid.length; i++) grid[i][numCol - 1] = i;
  var totalCols = (op.total || []).map(function (c) { return colNum_(c); });
  if (sh) {
    // 同じ頼みの撃ち直し：中身が同じなら変更なし。違えば止める
    var same = false;
    if (sh.getLastRow() === hr + rows.length + (totalCols.length ? 1 : 0) && sh.getLastColumn() >= nc) {
      var cur = sh.getRange(hr, 1, grid.length, nc).getFormulas();
      var curV = sh.getRange(hr, 1, grid.length, nc).getValues();
      same = grid.every(function (row, r) { return row.every(function (v, c) { var w = cur[r][c] || curV[r][c]; return String(w) === String(v) || (typeof v === 'string' && v.charAt(0) === '=' && String(cur[r][c]) === v); }); });
    }
    ctx.curSheet = name;
    if (same) { note_(ctx, '同じ表がすでにあります（変更なし）'); return; }
    throw new ArgError('シート「' + name + '」はすでにあります（中身が違います）。別の名前にするか、write・format で直してください');
  }
  if (ctx.isNew) { sh = ss.getSheets()[0]; sh.setName(name); } else { sh = ss.insertSheet(name); ctx.createdSheets.push(name); }
  ctx.curSheet = name;
  if (title) { sh.getRange(1, 1).setValue(title).setFontWeight('bold').setFontSize(14); }
  var rg = sh.getRange(hr, 1, grid.length, nc);
  rg.setValues(grid);
  var last = hr + grid.length - 1;
  if (totalCols.length) {
    var tr = last + 1;
    var labelCol = 1;
    while (labelCol <= nc && (totalCols.indexOf(labelCol) >= 0 || labelCol === numCol)) labelCol++;
    if (labelCol > nc) labelCol = 1;
    sh.getRange(tr, labelCol).setValue(op.label || '合計');
    totalCols.forEach(function (c) { sh.getRange(tr, c).setFormula('=SUM(' + colLetter_(c) + (hr + 1) + ':' + colLetter_(c) + last + ')'); });
    last = tr;
  }
  chg_(ctx, sh, a1_(1, 1, last, nc), '表を作成（' + rows.length + ' 行' + (totalCols.length ? '・合計行' : '') + '）');
  if (op.tidy !== false) tidyRange_(ctx, sh, null);
};

SHELF['sheet.add'] = function (ctx, op) {
  var ss = ctx.ss;
  if (op.name && !op.rename && !op.move) {
    if (ss.getSheetByName(op.name)) { note_(ctx, 'シート「' + op.name + '」はすでにあります（変更なし）'); ctx.curSheet = op.name; return; }
    var s = ss.insertSheet(op.name); ctx.createdSheets.push(op.name);
    if (op.before) { var bs = sheetOf_(ss, op.before, ''); ss.setActiveSheet(s); ss.moveActiveSheet(bs.getIndex()); }
    ctx.curSheet = op.name; chg_(ctx, s, '', 'シートを追加');
  }
  if (op.rename) {
    need_(op.rename, ['from', 'to']);
    var f = sheetOf_(ss, op.rename.from, '');
    if (ss.getSheetByName(op.rename.to)) throw new ArgError('シート「' + op.rename.to + '」はすでにあります');
    f.setName(op.rename.to); ctx.curSheet = op.rename.to; chg_(ctx, f, '', '名前を「' + op.rename.from + '」から変更');
  }
  if (op.move) {
    need_(op.move, ['name', 'index']);
    var m = sheetOf_(ss, op.move.name, ''); ss.setActiveSheet(m); ss.moveActiveSheet(parseInt(op.move.index)); chg_(ctx, m, '', '並び順を ' + op.move.index + ' 番目へ');
  }
  if (!op.name && !op.rename && !op.move) throw new ArgError('棚「sheet.add」に name・rename・move のどれかが要ります');
};

// ---------------------------------------------------------------- 棚：整える

function tidyRange_(ctx, sh, rangeA1) {
  var t = findTable_(sh);
  if (!t) { note_(ctx, 'tidy: 表が見つからないので整えていません'); return; }
  if (rangeA1) {
    var r = sh.getRange(rangeA1);
    t.firstCol = r.getColumn(); t.lastCol = r.getLastColumn();
  }
  var nc = t.lastCol - t.firstCol + 1, last = t.totalRow || t.lastData;
  var full = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc);
  full.setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  full.setVerticalAlignment('middle');
  var hd = sh.getRange(t.headerRow, t.firstCol, 1, nc);
  hd.setFontWeight('bold').setBackground(STYLE.headBg).setFontColor(STYLE.headFg).setHorizontalAlignment('center').setWrap(true);
  var cnt = t.lastData - t.firstData + 1;
  if (cnt >= 1) {
    // 表の値は findTable_ が 1 回で読んだもの（t.vals）を使う。書式は範囲ごとの配列で一括して書く
    var rows = (t.totalRow ? t.totalRow : t.lastData) - t.firstData + 1;
    var bodyRg = sh.getRange(t.firstData, t.firstCol, rows, nc);
    var nf = bodyRg.getNumberFormats(), al = bodyRg.getHorizontalAlignments();
    for (var ci = t.firstCol; ci <= t.lastCol; ci++) {
      var k = ci - t.firstCol, vals = [];
      for (var r = t.firstData; r <= t.lastData; r++) vals.push(t.vals[r - 1][ci - 1]);
      var fmt = null, align = null;
      if (isNoCol_(t, ci)) align = 'center';
      else {
        var nums = vals.filter(function (v) { return typeof v === 'number'; });
        var dates = vals.filter(function (v) { return Object.prototype.toString.call(v) === '[object Date]'; });
        var nonEmpty = vals.filter(function (v) { return !isBlank_(v); }).length;
        if (nonEmpty && nums.length / nonEmpty > 0.5) { fmt = nums.some(function (v) { return v % 1 !== 0; }) ? STYLE.numFmtDec : STYLE.numFmt; align = 'right'; }
        else if (nonEmpty && dates.length / nonEmpty > 0.5) { fmt = STYLE.dateFmt; align = 'center'; }
      }
      for (var rr = 0; rr < rows; rr++) { if (fmt) nf[rr][k] = fmt; if (align) al[rr][k] = align; }
    }
    bodyRg.setNumberFormats(nf).setHorizontalAlignments(al);
  }
  if (t.totalRow) sh.getRange(t.totalRow, t.firstCol, 1, nc).setFontWeight('bold').setBackground(STYLE.totalBg);
  // 列幅：中身に合わせる（上限・下限つき）
  var disp = sh.getRange(t.headerRow, t.firstCol, last - t.headerRow + 1, nc).getDisplayValues();
  for (var c = 0; c < nc; c++) {
    var mx = 0; disp.forEach(function (row) { mx = Math.max(mx, wlen_(row[c])); });
    sh.setColumnWidth(t.firstCol + c, Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad)));
  }
  sh.setFrozenRows(t.headerRow);
}

SHELF['tidy'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op);
  tidyRange_(ctx, sh, op.range || null);
  chg_(ctx, sh, op.range || 'A1', '書式をそろえた');
};

SHELF['seiri'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rg = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
  var vals = rg.getValues(), forms = rg.getFormulas(), fixed = [], nTrim = 0, nHalf = 0, nNum = 0;
  var doTrim = op.trim !== false, doHalf = op.halfwidth !== false, doNum = op.numbers !== false;
  for (var r = 0; r < vals.length; r++) for (var c = 0; c < vals[r].length; c++) {
    var v = vals[r][c];
    if (forms[r][c] || typeof v !== 'string') continue;
    var nv = v;
    if (doHalf) { var h = nv.replace(/[！-～]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0); }).replace(/　/g, ' '); if (h !== nv) { nv = h; nHalf++; } }
    if (doTrim) { var tr = nv.replace(/^[\s　]+|[\s　]+$/g, ''); if (tr !== nv) { nv = tr; nTrim++; } }
    if (doNum && r > 0 && /^-?[\d,]+(\.\d+)?$/.test(nv) && !/^-?0\d/.test(nv)) { nv = Number(nv.replace(/,/g, '')); nNum++; }
    if (nv !== v) { vals[r][c] = nv; fixed.push(a1_(t.headerRow + r, t.firstCol + c)); }
  }
  if (fixed.length) {
    // 式のセルは触らず、値のセルだけ書く
    // 直したセルだけを、列ごとに縦に連続した範囲にまとめて setValues（1 セルずつ書かない）
    var changedSet = {}; fixed.forEach(function (a) { changedSet[a] = 1; });
    for (var c2 = 0; c2 < vals[0].length; c2++) {
      var r2 = 0;
      while (r2 < vals.length) {
        if (!changedSet[a1_(t.headerRow + r2, t.firstCol + c2)]) { r2++; continue; }
        var r3 = r2; while (r3 + 1 < vals.length && changedSet[a1_(t.headerRow + r3 + 1, t.firstCol + c2)]) r3++;
        sh.getRange(t.headerRow + r2, t.firstCol + c2, r3 - r2 + 1, 1).setValues(vals.slice(r2, r3 + 1).map(function (row) { return [row[c2]]; }));
        r2 = r3 + 1;
      }
    }
    chg_(ctx, sh, fixed.slice(0, 4).join('・') + (fixed.length > 4 ? ' ほか' + (fixed.length - 4) + ' 件' : ''), '空白' + nTrim + '・全角→半角' + nHalf + '・数値化' + nNum);
  }
  // 空行を詰める＊ / 重複行を消す＊
  var t2 = findTable_(sh);
  if (op.blank_rows && t2) {
    var blanks = [];
    for (var rr = t2.firstData; rr <= t2.lastData; rr++) {
      var row = t2.vals[rr - 1].slice(t2.firstCol - 1, t2.lastCol);
      if (row.every(isBlank_)) blanks.push(rr);
    }
    // 表の途中の空行だけ（findTable_ が最後の非空行までを表とするので、すべて途中）
    if (blanks.length) {
      guardDelete_(ctx, '空行 ' + blanks.join('・') + ' 行目を詰めます');
      for (var k = blanks.length - 1; k >= 0; k--) sh.deleteRow(blanks[k]);
      chg_(ctx, sh, blanks.join('・') + ' 行目', '空行を削除（' + blanks.length + ' 行）');
    }
  }
  t2 = findTable_(sh);
  if (op.dedupe && t2) {
    var seen = {}, dups = [];
    for (var d = t2.firstData; d <= t2.lastData; d++) {
      var key = JSON.stringify(t2.vals[d - 1].slice(t2.firstCol - 1, t2.lastCol));
      if (seen[key]) dups.push(d); else seen[key] = 1;
    }
    if (dups.length) {
      guardDelete_(ctx, '全列が同じ重複行 ' + dups.join('・') + ' 行目を消します');
      for (var k2 = dups.length - 1; k2 >= 0; k2--) sh.deleteRow(dups[k2]);
      chg_(ctx, sh, dups.join('・') + ' 行目', '重複行を削除（' + dups.length + ' 行）');
    }
  }
  if (op.renumber) SHELF['renumber'](ctx, { shelf: 'renumber', col: op.renumber, sheet: op.sheet });
  if (op.tidy !== false) tidyRange_(ctx, sh, null);
  if (!ctx.changed.length) note_(ctx, '直す所はありませんでした');
};

SHELF['renumber'] = function (ctx, op) {
  need_(op, ['col']);
  var sh = sheetCtx_(ctx, op), t = needTable_(sh), ci = colIndexOf_(t, op.col), start = op.start === undefined ? 1 : op.start;
  var n = 0, rowsOut = [];
  for (var r = t.firstData; r <= t.lastData; r++) {
    var row = t.vals[r - 1].slice(t.firstCol - 1, t.lastCol).filter(function (v, i) { return t.firstCol + i !== ci; });
    var empty = row.every(isBlank_);
    if (empty) { rowsOut.push(['']); continue; }
    rowsOut.push([start + n]); n++;
  }
  if (rowsOut.length) sh.getRange(t.firstData, ci, rowsOut.length, 1).setValues(rowsOut);
  chg_(ctx, sh, a1_(t.firstData, ci, rowsOut.length, 1), '番号を ' + start + ' から振り直し（' + n + ' 件）');
};

SHELF['width'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = findTable_(sh), did = [];
  var colRef = function (k) { return t ? colIndexOf_(t, k) : colNum_(k); };
  if (op.cols) Object.keys(op.cols).forEach(function (k) { sh.setColumnWidth(colRef(k), op.cols[k]); did.push(k + '列'); });
  if (op.col && op.width) { sh.setColumnWidth(colRef(op.col), op.width); did.push(op.col + '列'); }
  if (op.rows) Object.keys(op.rows).forEach(function (k) { sh.setRowHeight(parseInt(k), op.rows[k]); did.push(k + '行'); });
  (op.auto || []).forEach(function (k) {
    var ci = colRef(k), lr = sh.getLastRow(), mx = 0;
    if (lr > 0) sh.getRange(1, ci, lr, 1).getDisplayValues().forEach(function (x) { mx = Math.max(mx, wlen_(x[0])); });
    sh.setColumnWidth(ci, Math.max(STYLE.colMin, Math.min(STYLE.colMax, mx * STYLE.px + STYLE.pad))); did.push(k + '列(自動)');
  });
  if (!did.length) throw new ArgError('棚「width」に cols・rows・auto のどれかが要ります');
  chg_(ctx, sh, did.join('・'), '幅・高さを変更');
};

// ---------------------------------------------------------------- 棚：集計

SHELF['total'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var cols = op.cols ? op.cols.map(function (c) { return colIndexOf_(t, c); }) : [];
  if (!cols.length) for (var ci = t.firstCol; ci <= t.lastCol; ci++) if (!isNoCol_(t, ci) && isNumberCol_(t, ci)) cols.push(ci);
  if (!cols.length) throw new ArgError('合計する列が見つかりません。cols で指定してください');
  var tr, existed = !!t.totalRow;
  tr = existed ? t.totalRow : t.lastData + 1;
  var label = op.label || '合計';
  if (!existed) {
    var lc = t.firstCol;
    while (lc <= t.lastCol && (cols.indexOf(lc) >= 0 || isNoCol_(t, lc))) lc++;
    if (lc > t.lastCol) lc = t.firstCol;
    sh.getRange(tr, lc).setValue(label);
  }
  var nc = t.lastCol - t.firstCol + 1;
  var rowRg = sh.getRange(tr, t.firstCol, 1, nc);
  // 合計行は 1 回で読み、式と書式を配列にして 1 回ずつ書く（列ごとに API を呼ばない）
  var fr = rowRg.getFormulas(), vr = rowRg.getValues(), nf = rowRg.getNumberFormats(), al = rowRg.getHorizontalAlignments(), fixed = [];
  cols.forEach(function (c) {
    var k = c - t.firstCol, f = '=SUM(' + colLetter_(c) + t.firstData + ':' + colLetter_(c) + t.lastData + ')';
    if (fr[0][k] !== f) { fr[0][k] = f; fixed.push(colLetter_(c)); }
    nf[0][k] = STYLE.numFmt; al[0][k] = 'right';
  });
  var out = fr[0].map(function (f, k) { return f || vr[0][k]; });
  rowRg.setValues([out]).setNumberFormats(nf).setHorizontalAlignments(al);
  rowRg.setFontWeight('bold').setBackground(STYLE.totalBg).setBorder(true, true, true, true, true, true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID);
  if (existed && !fixed.length) note_(ctx, '合計行 ' + tr + ' はすでにあります（変更なし）');
  else chg_(ctx, sh, a1_(tr, t.firstCol, 1, nc), existed ? '合計行の範囲を直した（' + fixed.join('・') + '列）' : '合計行を追加');
};

SHELF['summary'] = function (ctx, op) {
  need_(op, ['by', 'values']);
  var src = sheetOf_(ctx.ss, op.sheet, ctx.sheetName), t = needTable_(src);
  var by = colIndexOf_(t, op.by), vals = (Array.isArray(op.values) ? op.values : [op.values]).map(function (v) { return colIndexOf_(t, v); });
  var func = (op.func || 'sum').toLowerCase(), into = op.into || '集計';
  var keys = [], seen = {};
  for (var r = t.firstData; r <= t.lastData; r++) { var k = t.vals[r - 1][by - 1]; if (isBlank_(k)) continue; k = String(k); if (!seen[k]) { seen[k] = 1; keys.push(k); } }
  var sq = q_(src.getName()), rng = function (c) { return sq + '!$' + colLetter_(c) + '$' + t.firstData + ':$' + colLetter_(c) + '$' + t.lastData; };
  var hdr = [String(t.vals[t.headerRow - 1][by - 1])].concat(vals.map(function (c) { return String(t.vals[t.headerRow - 1][c - 1]) + (func === 'count' ? '(件数)' : func === 'avg' ? '(平均)' : ''); }));
  var grid = [hdr];
  keys.forEach(function (k, i) {
    var row = [k];
    vals.forEach(function (c) {
      var rr = i + 2;
      row.push(func === 'count' ? '=COUNTIFS(' + rng(by) + ',$A' + rr + ')' : func === 'avg' ? '=IFERROR(AVERAGEIFS(' + rng(c) + ',' + rng(by) + ',$A' + rr + '),0)' : '=SUMIFS(' + rng(c) + ',' + rng(by) + ',$A' + rr + ')');
    });
    grid.push(row);
  });
  if (func !== 'avg') {
    var tot = ['合計']; vals.forEach(function (c, j) { var L = colLetter_(j + 2); tot.push('=SUM(' + L + '2:' + L + (keys.length + 1) + ')'); });
    grid.push(tot);
  }
  var dst = ctx.ss.getSheetByName(into);
  if (dst) {
    var cur = dst.getLastRow() ? dst.getRange(1, 1, grid.length, grid[0].length).getFormulas() : [];
    var curV = dst.getLastRow() ? dst.getRange(1, 1, grid.length, grid[0].length).getValues() : [];
    var same = dst.getLastRow() === grid.length && grid.every(function (row, r2) { return row.every(function (v, c2) { return String(cur[r2][c2] || curV[r2][c2]) === String(v); }); });
    ctx.curSheet = into;
    if (same) { note_(ctx, '集計シート「' + into + '」は最新です（変更なし）'); return; }
    guardDelete_(ctx, '集計シート「' + into + '」はすでにあり、中身が変わります（作り直します）');
    dst.clear();
  } else { dst = ctx.ss.insertSheet(into); ctx.createdSheets.push(into); }
  dst.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
  ctx.curSheet = into;
  chg_(ctx, dst, a1_(1, 1, grid.length, grid[0].length), '「' + src.getName() + '」の ' + hdr[0] + ' ごとの集計（元の表を直すと追従）');
  tidyRange_(ctx, dst, null);
};

SHELF['sort'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = needTable_(sh);
  var rng = dataRange_(t);
  if (op.col) { rng.sort({ column: colIndexOf_(t, op.col), ascending: !op.desc }); chg_(ctx, sh, rng.getA1Notation(), op.col + ' で' + (op.desc ? '降順' : '昇順') + 'に並べ替え'); }
  if (op.filter || op.where) {
    var full = sh.getRange(t.headerRow, t.firstCol, t.lastData - t.headerRow + 1, t.lastCol - t.firstCol + 1);
    var f = sh.getFilter(); if (f) f.remove();
    f = full.createFilter();
    if (op.where) {
      need_(op.where, ['col']);
      var ci = colIndexOf_(t, op.where.col) - t.firstCol + 1;
      var crit = op.where.equals !== undefined ? SpreadsheetApp.newFilterCriteria().whenTextEqualTo(String(op.where.equals)).build()
        : SpreadsheetApp.newFilterCriteria().whenCellNotEmpty().build();
      f.setColumnFilterCriteria(ci, crit);
    }
    chg_(ctx, sh, full.getA1Notation(), 'フィルタを設定');
  }
  if (!op.col && !op.filter && !op.where) throw new ArgError('棚「sort」に col か filter が要ります');
};

// ---------------------------------------------------------------- 棚：直す

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

SHELF['format'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), t = null, rg;
  if (op.header) { t = needTable_(sh); rg = sh.getRange(t.headerRow, t.firstCol, 1, t.lastCol - t.firstCol + 1); }
  else if (op.col) { t = needTable_(sh); var ci = colIndexOf_(t, op.col); rg = sh.getRange(t.firstData, ci, (t.totalRow || t.lastData) - t.firstData + 1, 1); }
  else if (op.range) rg = sh.getRange(op.range);
  else throw new ArgError('棚「format」に range・col・header のどれかが要ります');
  var did = [];
  var set = function (key, fn) { if (op[key] !== undefined) { fn(op[key]); did.push(key); } };
  set('bold', function (v) { rg.setFontWeight(v ? 'bold' : 'normal'); });
  set('italic', function (v) { rg.setFontStyle(v ? 'italic' : 'normal'); });
  set('color', function (v) { rg.setFontColor(v); });
  set('bg', function (v) { rg.setBackground(v); });
  set('size', function (v) { rg.setFontSize(v); });
  set('font', function (v) { rg.setFontFamily(v); });
  set('number_format', function (v) { rg.setNumberFormat(v); });
  set('align', function (v) { rg.setHorizontalAlignment(v); });
  set('valign', function (v) { rg.setVerticalAlignment(v); });
  set('wrap', function (v) { rg.setWrap(!!v); });
  set('borders', function (v) { if (v) rg.setBorder(true, true, true, true, v === 'outer' ? false : true, v === 'outer' ? false : true, STYLE.border, SpreadsheetApp.BorderStyle.SOLID); else rg.setBorder(false, false, false, false, false, false); });
  set('merge', function (v) { if (v) rg.merge(); else rg.breakApart(); });
  if (!did.length) throw new ArgError('棚「format」に書式の指定（bold・color・bg・number_format・align など）がありません');
  chg_(ctx, sh, rg.getA1Notation(), did.join('・'));
};

SHELF['rows'] = function (ctx, op) {
  var sh = sheetCtx_(ctx, op), act = op.action || (op.cols ? 'delete' : 'delete');
  var isCol = !!op.cols, list = (isCol ? op.cols : op.rows) || [];
  if (act === 'insert') {
    var at = op.at || list[0]; need_({ shelf: 'rows', at: at }, ['at']);
    var cnt = op.count || 1;
    if (isCol) sh.insertColumnsBefore(typeof at === 'number' ? at : colNum_(at), cnt); else sh.insertRowsBefore(parseInt(at), cnt);
    chg_(ctx, sh, (isCol ? at + '列の前' : at + '行目の前'), cnt + ' ' + (isCol ? '列' : '行') + '挿入');
  } else if (act === 'delete') {
    if (!list.length) throw new ArgError('棚「rows」に rows（行番号の配列）か cols が要ります');
    var nums = list.map(function (x) { return isCol ? (typeof x === 'number' ? x : colNum_(x)) : parseInt(x); }).sort(function (a, b) { return b - a; });
    var max = isCol ? sh.getMaxColumns() : sh.getMaxRows();
    nums.forEach(function (n) { if (n < 1 || n > max) throw new ArgError((isCol ? '列' : '行') + '番号 ' + n + ' は範囲外です（1〜' + max + '）'); });
    var peek = nums.map(function (n) { var v = isCol ? sh.getRange(1, n, Math.min(sh.getLastRow() || 1, 50), 1).getDisplayValues() : sh.getRange(n, 1, 1, Math.max(1, sh.getLastColumn())).getDisplayValues()[0]; return (isCol ? colLetter_(n) + '列' : n + '行目') + '「' + String(isCol ? v.map(function (x) { return x[0]; }).filter(Boolean).slice(0, 2).join('/') : v.filter(Boolean).slice(0, 3).join('/')).slice(0, 24) + '」'; });
    guardDelete_(ctx, peek.reverse().join('、') + ' を削除します');
    nums.forEach(function (n) { if (isCol) sh.deleteColumn(n); else sh.deleteRow(n); });
    chg_(ctx, sh, nums.slice().reverse().join('・') + (isCol ? ' 列' : ' 行目'), '削除');
  } else if (act === 'move') {
    need_(op, ['from', 'to']);
    if (isCol) sh.moveColumns(sh.getRange(1, colNum_(op.from), 1, 1), colNum_(op.to)); else sh.moveRows(sh.getRange(parseInt(op.from), 1, op.count || 1, 1), parseInt(op.to));
    chg_(ctx, sh, op.from + ' → ' + op.to, '移動');
  } else throw new ArgError('棚「rows」の action は insert・delete・move です');
};

SHELF['replace'] = function (ctx, op) {
  need_(op, ['find']);
  var sh = sheetCtx_(ctx, op), scope = op.range ? sh.getRange(op.range) : sh.getDataRange();
  var tf = scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole);
  var hits = tf.findAll().map(function (r) { return r.getA1Notation(); });
  if (!hits.length) { note_(ctx, '「' + op.find + '」は見つかりませんでした'); return; }
  scope.createTextFinder(String(op.find)).matchCase(!!op.match_case).matchEntireCell(!!op.whole).replaceAllWith(String(op['with'] === undefined ? '' : op['with']));
  chg_(ctx, sh, hits.slice(0, 4).join('・') + (hits.length > 4 ? ' ほか' + (hits.length - 4) + ' 件' : ''), '「' + op.find + '」→「' + (op['with'] || '') + '」');
};

// ---------------------------------------------------------------- 文書：Markdown

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

SHELF['doc.section'] = docKind_(function (ctx, op) {
  need_(op, ['heading']);
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
