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
var BK_TABS_KEEP = 15;
var LEDGER_MAX = 40;

// 見た目の決まり（どの棚も同じ決まりを使う）
var STYLE = {
  headBg: '#1F4E79', headFg: '#FFFFFF', border: '#9E9E9E', totalBg: '#F2F2F2',
  numFmt: '#,##0', numFmtDec: '#,##0.00', dateFmt: 'yyyy/mm/dd',
  colMin: 50, colMax: 360, px: 7, pad: 18
};

// ---------------------------------------------------------------- 入口

var DYNAMIC = {};   // 棚ごとに、控えるシートと触る物をその呼びの引数から決める口（ふつうは空。棚のファイルが名前で登録する）
var EXTRA_ACTIONS = {};   // 別の入口を足すときの口（ふつうは空。エンジンに別のファイルを足すと、そこが名前で登録する）

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
  var tl0 = Date.now();
  LANE = '';
  var laneOn = !!(req.lane && EXTRA_ACTIONS.trial_config);   // 並べて回す入口（試験用のエンジンだけ）。錠と控えと台帳を lane ごとに分ける
  if (laneOn) {
    LANE = String(req.lane).replace(/[^0-9A-Za-z]/g, '').slice(0, 8);
    if (!lock.tryLock(30000)) return json_({ ok: false, error: '別の処理が走っています。少し待って撃ち直してください。', busy: true });
    try {   // 全体の錠は「lane の錠を取る・返す」一瞬だけ持つ。作業の間は lane の錠（プロパティの印）だけ
      var held = Number(PropertiesService.getScriptProperties().getProperty('LOCK@' + LANE) || 0);
      if (held && Date.now() - held < 330000) return json_({ ok: false, error: 'この lane（' + LANE + '）は別の処理が走っています。', busy: true });
      PropertiesService.getScriptProperties().setProperty('LOCK@' + LANE, String(Date.now()));
    } finally { lock.releaseLock(); }
  } else if (!lock.tryLock(30000)) return json_({ ok: false, error: '別の処理が走っています。少し待って撃ち直してください。', busy: true });
  var lockMs = Date.now() - tl0;
  try {
    var res;
    if (a === 'look') res = actLook_(req);
    else if (a === 'do') res = actDo_(req);
    else if (a === 'undo') res = actUndo_(req);
    else if (a === 'list') res = { ok: true, ledger: ledgerBrief_() };
    else if (EXTRA_ACTIONS[a]) res = EXTRA_ACTIONS[a](req);
    else res = { ok: false, error: '知らない action: ' + a };
    res.version = ENGINE_VERSION;
    res.ms = res.ms || {}; res.ms.lock = lockMs;     // 鍵を待った時間（ほかの処理と重なると伸びる）
    return json_(res);
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message || err), version: ENGINE_VERSION });
  } finally {
    if (laneOn) { try { PropertiesService.getScriptProperties().deleteProperty('LOCK@' + LANE); } catch (e2) { } }
    else lock.releaseLock();
  }
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function ArgError(msg) { this.message = msg; this.isArg = true; }
function Blocked(msg) { this.message = msg; this.isBlocked = true; }

// ---------------------------------------------------------------- 小道具

var LANE = '';   // 並べて回すときの lane（空＝ふつう）。プロパティの名前に @lane を付けて、台帳・控え・印を lane ごとに分ける（TRIAL_CFG だけ共通）
function props_() {
  var p = PropertiesService.getScriptProperties();
  if (!LANE) return p;
  var k2 = function (k) { return k === 'TRIAL_CFG' ? k : k + '@' + LANE; };
  return {
    getProperty: function (k) { return p.getProperty(k2(k)); },
    setProperty: function (k, v) { return p.setProperty(k2(k), v); },
    setProperties: function (obj) {
      var o = {};
      Object.keys(obj).forEach(function (k) { o[k2(k)] = obj[k]; });
      return typeof p.setProperties === 'function' ? p.setProperties(o) : Object.keys(o).forEach(function (k) { p.setProperty(k, o[k]); });
    },
    deleteProperty: function (k) { return p.deleteProperty(k2(k)); }
  };
}
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
var FP_VER = 4;   // 指紋の版。1＝文字を既定、2＝UTF-8、3＝固定の列も入れる、4＝値・式＋構成・固定の軽量版（書式 5 配列を外す）
function digest_(s, v) {
  var bytes = (v === 1) ? s : Utilities.newBlob(s).getBytes();   // 版 1 は昔の控えの指紋を比べるためだけに残す
  return Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, bytes)).slice(0, 12);
}
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

var _TBL_CACHE = null;   // 値を変えない 1 回の runDo_ 中だけ findTable_ の結果を共有する（finally で必ず null に戻す）
function findTable_(sh) {
  var sid = _TBL_CACHE ? sh.getSheetId() : null;
  if (_TBL_CACHE && _TBL_CACHE[sid] !== undefined) {
    var c0 = _TBL_CACHE[sid];
    return c0 ? { sheet: sh, headerRow: c0.headerRow, firstCol: c0.firstCol, lastCol: c0.lastCol, firstData: c0.firstData, lastData: c0.lastData, totalRow: c0.totalRow, vals: c0.vals } : null;
  }
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  if (lr < 1 || lc < 1) { if (_TBL_CACHE) _TBL_CACHE[sid] = null; return null; }
  var vals = sh.getRange(1, 1, lr, lc).getValues();
  var nonEmpty = function (row) { return row.filter(function (v) { return !isBlank_(v); }).length; };
  var h = -1;
  for (var r = 0; r < vals.length; r++) { if (nonEmpty(vals[r]) >= 2) { h = r; break; } }
  if (h < 0) { if (_TBL_CACHE) _TBL_CACHE[sid] = null; return null; }
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
    var first = '';   // 最終行の最初の文字のセル（ラベルは 2 列目より右にあることもある。「合計金額」が D 列、等）
    for (var fcx = fc; fcx <= lcol; fcx++) { var fv = vals[last][fcx]; if (!isBlank_(fv)) { first = String(fv); break; } }
    if (/^(合計|総計|小計|計|total|sum)/i.test(first.trim())) { t.totalRow = last + 1; t.lastData = last; }
  }
  if (_TBL_CACHE) _TBL_CACHE[sid] = { headerRow: t.headerRow, firstCol: t.firstCol, lastCol: t.lastCol, firstData: t.firstData, lastData: t.lastData, totalRow: t.totalRow, vals: t.vals };
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

function fingerSheet_(sh, v, meta) {
  v = v || FP_VER;
  var lr = sh.getLastRow(), lc = sh.getLastColumn();
  var d = '';
  if (lr > 0 && lc > 0) {
    var rg = sh.getRange(1, 1, lr, lc);
    if (v >= 4) {
      d = digest_(JSON.stringify(rg.getFormulas()) + JSON.stringify(rg.getDisplayValues()), v);
    } else {
      d = digest_(JSON.stringify(rg.getFormulas()) + JSON.stringify(rg.getDisplayValues()) + JSON.stringify(rg.getBackgrounds()) + JSON.stringify(rg.getFontWeights()) +
        JSON.stringify(rg.getFontColors()) + JSON.stringify(rg.getNumberFormats()) + JSON.stringify(rg.getHorizontalAlignments()), v);
    }
  }
  var nm = (meta && meta.name !== undefined) ? meta.name : sh.getName();
  var fr = (meta && meta.frozenR !== undefined) ? meta.frozenR : sh.getFrozenRows();
  var fc = (meta && meta.frozenC !== undefined) ? meta.frozenC : sh.getFrozenColumns();
  return { rows: lr, cols: lc, d: digest_(d + '|' + nm + '|' + fr + (v >= 3 ? '|' + fc : ''), v) };
}
function fingerDoc_(doc, v) {
  v = v || FP_VER;
  var b = doc.getBody();
  return { n: b.getNumChildren(), d: digest_(b.getText() + '|' + docStructure_(b), v) };
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
function ledgerSave_(l, extraProps) {
  while (l.items.length > LEDGER_MAX) {
    var x = l.items.shift();
    if (x && x.hasSide) { try { props_().deleteProperty('SIDE_' + x.n); } catch (e) { } }
    if (x && x.hasLight) { try { props_().deleteProperty('LIGHT_' + x.n); } catch (e) { } }
  }
  var p = props_();
  if (extraProps && Object.keys(extraProps).length && typeof p.setProperties === 'function') {
    var map = {};
    Object.keys(extraProps).forEach(function (k) { map[k] = JSON.stringify(extraProps[k]); });
    map['LEDGER'] = JSON.stringify(l);
    p.setProperties(map);
  } else {
    if (extraProps) Object.keys(extraProps).forEach(function (k) { setJson_(k, extraProps[k]); });
    setJson_('LEDGER', l);
  }
}
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
var BKT = {};   // 控えの中の内訳（ミリ秒）。返事の ms に bk_ を付けて入れる
function bkLap_(k, t0) { BKT['bk_' + k] = (BKT['bk_' + k] || 0) + (Date.now() - t0); }
function backupSheets_(ss, sheets, n, sideItems) {
  if (!sheets.length) return [];
  var tb = Date.now();
  var book = bkBook_(), out = []; bkLap_('open', tb); tb = Date.now();
  var cur = book.getSheets(); bkLap_('list', tb);   // 控えブックの全タブを 1 回で読み、数で掃除の要否を決める
  var curCount = cur.length, added = [], needRefresh = false;
  sheets.forEach(function (sh) {
    var sid = sh.getSheetId(), shName = sh.getName();
    var nm = bkTabName_(n, sid);
    if (curCount > 1) {
      var dup = book.getSheetByName(nm);
      if (dup) { book.deleteSheet(dup); curCount--; needRefresh = true; }
    }
    var tc = Date.now();
    var c = sh.copyTo(book); bkLap_('copy', tc); tc = Date.now();
    c.setName(nm); curCount++; added.push({ s: c, name: nm }); bkLap_('name', tc);
    // 列幅は控えのタブ（copyTo が写す）にあるので、戻すときにそこから読む（書く前に列ごとに読まない）
    out.push({ id: sid, name: shName, index: sh.getIndex(), tab: nm, frozenR: sh.getFrozenRows(), frozenC: sh.getFrozenColumns() });
  });
  var tp = Date.now();
  // 白紙の初期シート削除は枚数が少ない初期状態のみ確認（通常時は getName() を呼ばない）
  if (cur.length <= 3) {
    for (var j = 0; j < cur.length; j++) {
      var nj = cur[j].getName();
      if ((nj === 'シート1' || nj === 'Sheet1') && curCount > 1) { try { book.deleteSheet(cur[j]); curCount--; needRefresh = true; } catch (e) { } break; }
    }
  }
  // 古い控えのタブを回す（BK_TABS_MAX 枚を超えたときだけ BK_TABS_KEEP 枚までまとめて削り、普段は掃除を走らせない）
  if (curCount > BK_TABS_MAX) {
    var list = needRefresh
      ? book.getSheets().map(function (s) { return { s: s, name: s.getName() }; })
      : cur.map(function (s) { return { s: s, name: s.getName() }; }).concat(added);
    var tabs = list.filter(function (x) { return /^ws\d+_/.test(x.name); });
    tabs.sort(function (x, y) { return parseInt(x.name.slice(2)) - parseInt(y.name.slice(2)); });
    var extra = tabs.length - BK_TABS_KEEP, left = list.length;
    for (var k = 0; k < extra && left > 1; k++) { book.deleteSheet(tabs[k].s); left--; }
  }
  bkLap_('prune', tp);
  var ts = Date.now();
  captureSide_(ss, sheets, out, sideItems || []); bkLap_('side', ts);
  return out;
}
// 列幅は表のある列だけ記録する（1 回の API 呼びが約 0.1 秒なので、全列・全行は読まない。行の高さは戻しの対象外）
// 変更の無い控えを破棄する（ライト控えは控えブックにタブを持たないので何もしない）
function discardBackup_(bk) {
  if (!bk || !bk.length) return;
  if (!bk.some(function (b) { return !b.lite && b.tab; })) return;
  try {
    var book = bkBook_();
    bk.forEach(function (b) { if (!b.lite && b.tab) { var t = book.getSheetByName(b.tab); if (t && book.getSheets().length > 1) book.deleteSheet(t); } });
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
      tmp.setName(b.name); ss.setActiveSheet(tmp); ss.moveActiveSheet(Math.min(b.index, ss.getNumSheets())); tmp = null;   // b.index は 1 始まり（+1 すると末尾のシートで「引数が無効」）
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
    // 控えのタブのフィルタを先に外す: 掛かったままだと、フィルタで隠れた行が写されず、あとの行が上へずれて値が狂う
    try { var tf = tmp.getFilter(); if (tf) tf.remove(); } catch (eF) { }
    tmp.getRange(1, 1, lr, lc).copyTo(orig.getRange(1, 1, lr, lc));
    var widths = b.widths || colWidths_(tab);   // 古い控えは記録を持つ。新しい控えは控えのタブから読む
    for (var c = 0; c < widths.length && c < lc; c++) orig.setColumnWidth(c + 1, widths[c]);
    orig.setFrozenRows(b.frozenR); orig.setFrozenColumns(b.frozenC);
    if (orig.getIndex() !== b.index) { ss.setActiveSheet(orig); ss.moveActiveSheet(b.index); }
  } finally { if (tmp) { try { ss.deleteSheet(tmp); } catch (e) { } } }
}

// 値やシート構成を変えない棚は、控えブックへ copyTo せず Sheets API で必要な項目だけを控える（9KB を超える巨大シートは従来控えへ戻す）
var LITE_EXCLUDE_ = { '値': 1, 'シート構成': 1 };
function liteTouch_(ops) {
  if (!ops || !ops.length) return null;
  var set = {};
  for (var i = 0; i < ops.length; i++) {
    var op = ops[i], c = CATALOG[op.shelf];
    if (!c || DYNAMIC[op.shelf]) return null;
    if (op.to && String(op.to).indexOf('!') >= 0) return null;
    if ('merge' in op && op.merge !== undefined) return null;   // セル結合は右下の値を消すので通常控えへ
    var touch = c.touch || [];
    for (var j = 0; j < touch.length; j++) {
      if (LITE_EXCLUDE_[touch[j]]) return null;
      set[touch[j]] = 1;
    }
  }
  return Object.keys(set);
}
function packRects_(rows, rOff, cOff, pickFn) {
  var pal = [], pMap = {}, truns = [], rects = [], prev = {};
  for (var r = 0; r < rows.length; r++) {
    var vals = (rows[r] && rows[r].values) || [];
    var cur = {}, c = 0;
    while (c < vals.length) {
      var v = vals[c] || {};
      if (v.textFormatRuns) truns.push([rOff + r, cOff + c, v.textFormatRuns]);
      var obj = pickFn(v);
      if (!obj || !Object.keys(obj).length) { c++; continue; }
      var key = JSON.stringify(obj), idx = pMap[key];
      if (!idx) { pal.push(obj); idx = pal.length; pMap[key] = idx; }
      var c0 = c;
      while (c + 1 < vals.length) {
        var nv = vals[c + 1] || {};
        var nobj = pickFn(nv);
        if (!nobj || !Object.keys(nobj).length || JSON.stringify(nobj) !== key) break;
        if (nv.textFormatRuns) truns.push([rOff + r, cOff + c + 1, nv.textFormatRuns]);
        c++;
      }
      var c1 = c + 1, rk = (cOff + c0) + ':' + (cOff + c1) + ':' + idx;
      if (prev[rk] && prev[rk][1] === rOff + r) {
        prev[rk][1] = rOff + r + 1;
        cur[rk] = prev[rk];
      } else {
        var rect = [rOff + r, rOff + r + 1, cOff + c0, cOff + c1, idx];
        rects.push(rect);
        cur[rk] = rect;
      }
      c++;
    }
    prev = cur;
  }
  return { pal: pal, rects: rects, truns: truns };
}
function packDim_(meta, defPx) {
  var out = [];
  (meta || []).forEach(function (m) {
    var px = (m && m.pixelSize !== undefined) ? m.pixelSize : defPx;
    if (out.length && out[out.length - 1][1] === px) out[out.length - 1][0]++;
    else out.push([1, px]);
  });
  return out;
}
function saveSide_(n, rec) {
  var s = JSON.stringify(rec);
  if (s.length <= 6000) { props_().setProperty('SIDE_' + n, s); return; }
  var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(s, 'application/json')).getBytes());
  props_().setProperty('SIDE_' + n, JSON.stringify({ __gz: gz }));
}
function backupSheetsLite_(ss, sheets, n, items) {
  if (!sheets.length) return [];
  var tb = Date.now();
  var want = {}; items.forEach(function (i) { want[i] = 1; });
  var out = sheets.map(function (sh) {
    return { id: sh.getSheetId(), name: sh.getName(), index: sh.getIndex(), frozenR: sh.getFrozenRows(), frozenC: sh.getFrozenColumns(), lite: true };
  });
  var needMeta = !!(want['隠し'] || want['グループ'] || want['保護'] || want['名前'] || want['タブ色'] || want['グラフ'] || want['フィルタ'] || want['条件付き'] || want['交互の色']);
  if (needMeta) {
    var shF = ['properties(sheetId' + (want['隠し'] ? ',hidden' : '') + (want['タブ色'] ? ',tabColorStyle' : '') + ')'];
    if (want['フィルタ']) shF.push('basicFilter');
    if (want['グループ']) shF.push('rowGroups', 'columnGroups');
    if (want['保護']) shF.push('protectedRanges(protectedRangeId,range,description,warningOnly,editors,unprotectedRanges)');
    if (want['グラフ']) shF.push('charts(chartId,spec,position)');
    if (want['条件付き']) shF.push('conditionalFormats');
    if (want['交互の色']) shF.push('bandedRanges');
    var resp = Sheets.Spreadsheets.get(ss.getId(), { fields: 'sheets(' + shF.join(',') + ')' + (want['名前'] ? ',namedRanges' : '') });
    var byId = {}; (resp.sheets || []).forEach(function (x) { byId[x.properties.sheetId] = x; });
    out.forEach(function (b) {
      var x = byId[b.id]; if (!x) return;
      b.side = b.side || {};
      if (want['フィルタ']) b.side.filter = x.basicFilter || null;
      if (want['隠し']) b.side.hidden = !!x.properties.hidden;
      if (want['タブ色']) b.side.tab = x.properties.tabColorStyle || null;
      if (want['グループ']) { b.side.rg = x.rowGroups || []; b.side.cg = x.columnGroups || []; }
      if (want['保護']) b.side.prot = (x.protectedRanges || []).map(stripId_);
      if (want['グラフ']) b.side.charts = (x.charts || []).map(function (c) { return { spec: c.spec, position: c.position }; });
      if (want['条件付き']) b.side.cf = x.conditionalFormats || [];
      if (want['交互の色']) b.side.band = (x.bandedRanges || []).map(function (br) { var c = {}; Object.keys(br).forEach(function (k) { if (k !== 'bandedRangeId') c[k] = br[k]; }); return c; });
    });
    if (want['名前']) out.book = { named: (resp.namedRanges || []).map(function (r) { return { name: r.name, range: r.range }; }) };
  }
  var needGrid = !!(want['書式'] || want['入力規則'] || want['幅'] || want['隠し']);
  if (needGrid) {
    var ranges = [], gFields = ['properties(sheetId)'];
    var needCells = !!(want['書式'] || want['入力規則']);
    if (want['書式']) gFields.push('merges');
    var dataF = [];
    if (want['隠し'] || want['幅']) {
      dataF.push('rowMetadata(' + (want['隠し'] ? 'hiddenByUser' : '') + (want['隠し'] && want['幅'] ? ',' : '') + (want['幅'] ? 'pixelSize' : '') + ')');
      dataF.push('columnMetadata(' + (want['隠し'] ? 'hiddenByUser' : '') + (want['隠し'] && want['幅'] ? ',' : '') + (want['幅'] ? 'pixelSize' : '') + ')');
    }
    if (needCells) {
      var vF = [];
      if (want['書式']) vF.push('userEnteredFormat', 'textFormatRuns');
      if (want['入力規則']) vF.push('dataValidation');
      dataF.push('startRow', 'startColumn', 'rowData(values(' + vF.join(',') + '))');
      sheets.forEach(function (s, si) { ranges.push(q_(out[si].name)); });
    } else {
      sheets.forEach(function (s, si) { var qn = q_(out[si].name); ranges.push(qn + '!A:A'); ranges.push(qn + '!1:1'); });
    }
    gFields.push('data(' + dataF.join(',') + ')');
    var dr = Sheets.Spreadsheets.get(ss.getId(), { includeGridData: true, ranges: ranges, fields: 'sheets(' + gFields.join(',') + ')' });
    var dById = {}; (dr.sheets || []).forEach(function (x) { dById[x.properties.sheetId] = x; });
    out.forEach(function (b) {
      var x = dById[b.id]; if (!x) return;
      b.side = b.side || {};
      var d = x.data || [], g0 = d[0] || {}, g1 = needCells ? g0 : (d[1] || {});
      if (want['隠し']) { b.side.hr = hiddenRuns_(g0.rowMetadata); b.side.hc = hiddenRuns_(g1.columnMetadata); }
      if (want['幅']) { b.side.rh = packDim_(g0.rowMetadata, 21); b.side.cw = packDim_(g1.columnMetadata, 100); }
      if (want['書式']) {
        var pf = packRects_(g0.rowData || [], g0.startRow || 0, g0.startColumn || 0, function (v) { return v.userEnteredFormat || null; });
        var fmt = { merges: x.merges || [], pal: pf.pal, rects: pf.rects };
        if (pf.truns.length) fmt.truns = pf.truns;
        b.side.fmt = fmt;
      }
      if (want['入力規則']) {
        var pd = packRects_(g0.rowData || [], g0.startRow || 0, g0.startColumn || 0, function (v) { return v.dataValidation || null; });
        b.side.dv = { pal: pd.pal, rects: pd.rects };
      }
    });
  }
  if (want['固定']) {
    out.forEach(function (b) { b.side = b.side || {}; b.side.fr = [b.frozenR, b.frozenC]; });
  }
  // 9KB 上限を超える場合は従来控えへ安全にフォールバックする
  var probe = packSide_(out, items);
  if (probe) {
    var ps = JSON.stringify(probe);
    if (ps.length > 6000) {
      var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(ps, 'application/json')).getBytes());
      if (JSON.stringify({ __gz: gz }).length > 7800) return null;
    }
  }
  bkLap_('lite', tb);
  return out;
}

// ---------------------------------------------------------------- 脇の状態（控えと戻し）
// シートの中身と書式は控えのタブの写しで戻る。それ以外（フィルタ・行と列の隠し・シートの隠し・グループ・保護・名前付き範囲・タブの色・グラフ）は
// 写しに入らないので、控えのとき Sheets API で読んで記録し、戻すとき「今あるのを消してから、記録のとおりに付け直す」。
// 記録するのは、その回の棚の「触る:」に出た項目だけ（フィルタだけは常に。ただしフィルタの無いシートでは何もしない）。
var SIDE_ITEMS = ['隠し', 'グループ', '保護', '名前', 'タブ色', 'グラフ'];
function sideItems_(ops) {
  var set = {};
  ops.forEach(function (o) {
    var c = CATALOG[o.shelf], touch = DYNAMIC[o.shelf] ? DYNAMIC[o.shelf].touch(o) : (c ? c.touch : []);
    touch.forEach(function (x) { if (SIDE_ITEMS.indexOf(x) >= 0) set[x] = 1; });
  });
  return Object.keys(set);
}
function hiddenRuns_(meta) {
  var runs = [], start = -1;
  (meta || []).forEach(function (m, i) {
    if (m && m.hiddenByUser) { if (start < 0) start = i; } else if (start >= 0) { runs.push([start, i]); start = -1; }
  });
  if (start >= 0) runs.push([start, (meta || []).length]);
  return runs;
}
function stripId_(p) { var c = {}; Object.keys(p).forEach(function (k) { if (k !== 'protectedRangeId') c[k] = p[k]; }); return c; }
function sideFields_(want, filter) {
  var sh = ['properties(sheetId' + (want['隠し'] ? ',hidden' : '') + (want['タブ色'] ? ',tabColorStyle' : '') + ')'];
  if (filter) sh.push('basicFilter');
  if (want['グループ']) sh.push('rowGroups', 'columnGroups');
  if (want['保護']) sh.push('protectedRanges(protectedRangeId,range,description,warningOnly,editors,unprotectedRanges)');
  if (want['グラフ']) sh.push('charts(chartId,spec,position)');
  return 'sheets(' + sh.join(',') + ')' + (want['名前'] ? ',namedRanges' : '');
}
// 控えのとき: bk の各項目に side を付ける（bk.book に名前付き範囲）。要る物が無ければ API を呼ばない
function captureSide_(ss, sheets, bk, items) {
  var want = {}; items.forEach(function (i) { want[i] = 1; });
  var hasFilter = sheets.some(function (s) { return !!s.getFilter(); });
  if (!items.length && !hasFilter) return;
  // ranges を付けると、その範囲に重なる保護・グラフ・名前付き範囲しか返らないので、隠しの行と列だけ別の呼びにする
  var resp = Sheets.Spreadsheets.get(ss.getId(), { fields: sideFields_(want, hasFilter) });
  var byId = {}; (resp.sheets || []).forEach(function (x) { byId[x.properties.sheetId] = x; });
  var dataById = {};
  if (want['隠し']) {
    var ranges = [];
    sheets.forEach(function (s, si) { var qn = q_((bk[si] && bk[si].name) || s.getName()); ranges.push(qn + '!A:A'); ranges.push(qn + '!1:1'); });
    var dr = Sheets.Spreadsheets.get(ss.getId(), { includeGridData: true, ranges: ranges, fields: 'sheets(properties(sheetId),data(rowMetadata(hiddenByUser),columnMetadata(hiddenByUser)))' });
    (dr.sheets || []).forEach(function (x) { dataById[x.properties.sheetId] = x.data || []; });
  }
  bk.forEach(function (b) {
    var x = byId[b.id]; if (!x) return;
    var s = {};
    if (x.basicFilter) s.filter = x.basicFilter;
    if (want['隠し']) { var d = dataById[b.id] || []; s.hidden = !!x.properties.hidden; s.hr = hiddenRuns_(d[0] && d[0].rowMetadata); s.hc = hiddenRuns_(d[1] && d[1].columnMetadata); }
    if (want['タブ色']) s.tab = x.properties.tabColorStyle || null;
    if (want['グループ']) { s.rg = x.rowGroups || []; s.cg = x.columnGroups || []; }
    if (want['保護']) s.prot = (x.protectedRanges || []).map(stripId_);
    if (want['グラフ']) s.charts = (x.charts || []).map(function (c) { return { spec: c.spec, position: c.position }; });
    if (Object.keys(s).length) b.side = s;
  });
  if (want['名前']) bk.book = { named: (resp.namedRanges || []).map(function (r) { return { name: r.name, range: r.range }; }) };
}
// 台帳に残す形（脇の状態は別のプロパティ SIDE_n に。台帳の記録は小さいまま）
function packSide_(bk, items) {
  var sheets = {}, any = false;
  (bk || []).forEach(function (b) { if (b.side) { sheets[b.id] = b.side; any = true; } });
  if (bk && bk.book) any = true;
  return any ? { sheets: sheets, book: (bk && bk.book) || null, items: items || [] } : null;
}
function stripSide_(bk) {
  return bk.map(function (b) { var c = {}; Object.keys(b).forEach(function (k) { if (k !== 'side') c[k] = b[k]; }); return c; });
}
function loadSide_(it) {
  var rec = it.hasSide ? getJson_('SIDE_' + it.n, null) : null;
  if (rec && rec.__gz) {
    try { rec = JSON.parse(Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(rec.__gz), 'application/x-gzip')).getDataAsString('utf-8')); }
    catch (e) { rec = null; }
  }
  var bks = (it.sheets || []).map(function (b) { var c = {}; Object.keys(b).forEach(function (k) { c[k] = b[k]; }); if (rec && rec.sheets && rec.sheets[b.id]) c.side = rec.sheets[b.id]; return c; });
  if (rec && rec.book) bks.book = rec.book;
  return bks;
}
// batchUpdate は全部かなにも変えないかなので、Google の一時的な内部エラー（Internal error）だけは 1 回撃ち直す
function batchRetry_(ss, reqs) {
  try { return Sheets.Spreadsheets.batchUpdate({ requests: reqs }, ss.getId()); }
  catch (e) {
    if (String(e && e.message || e).indexOf('Internal error') < 0) throw e;
    Utilities.sleep(1000);
    return Sheets.Spreadsheets.batchUpdate({ requests: reqs }, ss.getId());
  }
}
// 戻すとき: 今ある物を消してから、記録のとおりに付け直す（1 回の batchUpdate）。戻せない物は notes に 1 行出す
function restoreSide_(ss, bk, notes) {
  var recs = (bk || []).filter(function (b) { return b.side; });
  var book = bk && bk.book;
  if (!recs.length && !book) return;
  var needCur = !!book, need = {};
  recs.forEach(function (b) {
    ['rg', 'cg', 'prot', 'charts'].forEach(function (k) { if (b.side[k] !== undefined) { needCur = true; need[k] = 1; } });
    if (b.side.fmt !== undefined) { needCur = true; need.merges = 1; }
    if (b.side.cf !== undefined) { needCur = true; need.cf = 1; }
    if (b.side.band !== undefined) { needCur = true; need.band = 1; }
  });
  var cur = {};
  if (needCur) {
    var f = ['properties(sheetId)'];
    if (need.rg) f.push('rowGroups'); if (need.cg) f.push('columnGroups');
    if (need.prot) f.push('protectedRanges(protectedRangeId)'); if (need.charts) f.push('charts(chartId)');
    if (need.merges) f.push('merges');
    if (need.cf) f.push('conditionalFormats');
    if (need.band) f.push('bandedRanges(bandedRangeId)');
    var r = Sheets.Spreadsheets.get(ss.getId(), { fields: 'sheets(' + f.join(',') + ')' + (book ? ',namedRanges(namedRangeId)' : '') });
    (r.sheets || []).forEach(function (x) { cur[x.properties.sheetId] = x; });
    cur.__named = r.namedRanges || [];
  }
  var repeatReq_ = function (range, cell, fields) { var req = {}; req['repeat' + 'Cell'] = { range: range, cell: cell, fields: fields }; return req; };
  var build = function (withEditors) {
    var dels = [], adds = [], props = [];
    recs.forEach(function (b) {
      var s = b.side, id = b.id, c = cur[id] || {};
      if (s.fmt !== undefined) {
        (c.merges || []).forEach(function (m) { dels.push({ unmergeCells: { range: m } }); });
        dels.push(repeatReq_({ sheetId: id }, {}, 'userEnteredFormat,textFormatRuns'));
        (s.fmt.rects || []).forEach(function (q) {
          adds.push(repeatReq_({ sheetId: id, startRowIndex: q[0], endRowIndex: q[1], startColumnIndex: q[2], endColumnIndex: q[3] },
            { userEnteredFormat: s.fmt.pal[q[4] - 1] }, 'userEnteredFormat'));
        });
        (s.fmt.truns || []).forEach(function (tr) {
          adds.push({ updateCells: { start: { sheetId: id, rowIndex: tr[0], columnIndex: tr[1] }, rows: [{ values: [{ textFormatRuns: tr[2] }] }], fields: 'textFormatRuns' } });
        });
        (s.fmt.merges || []).forEach(function (m) { adds.push({ mergeCells: { range: m, mergeType: 'MERGE_ALL' } }); });
      }
      if (s.dv !== undefined) {
        dels.push(repeatReq_({ sheetId: id }, {}, 'dataValidation'));
        (s.dv.rects || []).forEach(function (q) {
          adds.push(repeatReq_({ sheetId: id, startRowIndex: q[0], endRowIndex: q[1], startColumnIndex: q[2], endColumnIndex: q[3] },
            { dataValidation: s.dv.pal[q[4] - 1] }, 'dataValidation'));
        });
      }
      if (s.cw !== undefined) {
        var ci = 0;
        s.cw.forEach(function (run) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'COLUMNS', startIndex: ci, endIndex: ci + run[0] }, properties: { pixelSize: run[1] }, fields: 'pixelSize' } }); ci += run[0]; });
      }
      if (s.rh !== undefined) {
        var ri = 0;
        s.rh.forEach(function (run) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'ROWS', startIndex: ri, endIndex: ri + run[0] }, properties: { pixelSize: run[1] }, fields: 'pixelSize' } }); ri += run[0]; });
      }
      if (s.cf !== undefined) {
        for (var cfi = 0; cfi < (c.conditionalFormats || []).length; cfi++) dels.push({ deleteConditionalFormatRule: { sheetId: id, index: 0 } });
        s.cf.forEach(function (rule, idx) { adds.push({ addConditionalFormatRule: { rule: rule, index: idx } }); });
      }
      if (s.band !== undefined) {
        (c.bandedRanges || []).forEach(function (br) { dels.push({ deleteBanding: { bandedRangeId: br.bandedRangeId } }); });
        s.band.forEach(function (br) { adds.push({ addBanding: { bandedRange: br } }); });
      }
      if (s.fr !== undefined) {
        props.push({ updateSheetProperties: { properties: { sheetId: id, gridProperties: { frozenRowCount: s.fr[0], frozenColumnCount: s.fr[1] } }, fields: 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount' } });
      }
      if (s.hr !== undefined || s.hc !== undefined) {
        var sh = byId_(ss, id), mr = sh ? sh.getMaxRows() : 0, mc = sh ? sh.getMaxColumns() : 0;
        if (s.hr !== undefined && mr) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'ROWS', startIndex: 0, endIndex: mr }, properties: { hiddenByUser: false }, fields: 'hiddenByUser' } });
          s.hr.forEach(function (e) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'ROWS', startIndex: e[0], endIndex: e[1] }, properties: { hiddenByUser: true }, fields: 'hiddenByUser' } }); }); }
        if (s.hc !== undefined && mc) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'COLUMNS', startIndex: 0, endIndex: mc }, properties: { hiddenByUser: false }, fields: 'hiddenByUser' } });
          s.hc.forEach(function (e) { props.push({ updateDimensionProperties: { range: { sheetId: id, dimension: 'COLUMNS', startIndex: e[0], endIndex: e[1] }, properties: { hiddenByUser: true }, fields: 'hiddenByUser' } }); }); }
      }
      if (s.tab !== undefined) props.push({ updateSheetProperties: { properties: { sheetId: id, tabColorStyle: s.tab || {} }, fields: 'tabColorStyle' } });
      ['rg', 'cg'].forEach(function (k) {
        if (s[k] === undefined) return;
        (c[k === 'rg' ? 'rowGroups' : 'columnGroups'] || []).forEach(function (g) { dels.push({ deleteDimensionGroup: { range: g.range } }); });
        s[k].slice().sort(function (a, b2) { return a.depth - b2.depth; }).forEach(function (g) { adds.push({ addDimensionGroup: { range: g.range } }); });
        s[k].forEach(function (g) { if (g.collapsed) adds.push({ updateDimensionGroup: { dimensionGroup: g, fields: 'collapsed' } }); });
      });
      if (s.prot !== undefined) {
        (c.protectedRanges || []).forEach(function (p) { dels.push({ deleteProtectedRange: { protectedRangeId: p.protectedRangeId } }); });
        s.prot.forEach(function (p) { var q = JSON.parse(JSON.stringify(p)); if (!withEditors) delete q.editors; adds.push({ addProtectedRange: { protectedRange: q } }); });
      }
      if (s.charts !== undefined) {
        (c.charts || []).forEach(function (ch) { dels.push({ deleteEmbeddedObject: { objectId: ch.chartId } }); });
        s.charts.forEach(function (ch) { adds.push({ addChart: { chart: { spec: ch.spec, position: ch.position } } }); });
      }
      if (s.hidden !== undefined) props.push({ updateSheetProperties: { properties: { sheetId: id, hidden: s.hidden }, fields: 'hidden' } });
    });
    if (book) {
      (cur.__named || []).forEach(function (n) { dels.push({ deleteNamedRange: { namedRangeId: n.namedRangeId } }); });
      book.named.forEach(function (n) { adds.push({ addNamedRange: { namedRange: { name: n.name, range: n.range } } }); });
    }
    // 先にシートの隠しを「出す」側へ寄せないと、最後の見えているシートを隠すとき失敗する。付け直しの後に隠しを合わせる
    var showFirst = props.filter(function (q) { return q.updateSheetProperties && q.updateSheetProperties.properties.hidden === false; });
    var hideLast = props.filter(function (q) { return q.updateSheetProperties && q.updateSheetProperties.properties.hidden === true; });
    var rest = props.filter(function (q) { return showFirst.indexOf(q) < 0 && hideLast.indexOf(q) < 0; });
    return dels.concat(showFirst, adds, rest, hideLast);
  };
  var reqs = build(true);
  if (reqs.length) SpreadsheetApp.flush();   // 中身を戻した分を反映してから、脇の状態を付け直す（グラフは中身の範囲を指すため）
  if (reqs.length) try { batchRetry_(ss, reqs); }
  catch (e) {
    var chartReqs = reqs.filter(function (q) { return q.addChart; });
    if (String(e && e.message || e).indexOf('Internal error') >= 0 && chartReqs.length) {
      // グラフの付け直しだけが通らないとき（series の無いグラフなど）: ほかを先に通し、グラフは SpreadsheetApp で作り直す。作り直せなければ知らせる
      batchRetry_(ss, reqs.filter(function (q) { return !q.addChart; }));
      recs.forEach(function (b) {
        (b.side.charts || []).forEach(function (ch) {
          try { restoreChartApp_(byId_(ss, b.id), ch); }
          catch (e2) { if (notes) notes.push('グラフを付け直せませんでした（種類・範囲・位置・題の記録から作れない形でした）。グラフだけ作り直してください'); }
        });
      });
    } else {
    var hasEditors = recs.some(function (b) { return (b.side.prot || []).some(function (p) { return p.editors; }); });
    if (!hasEditors) throw e;
    batchRetry_(ss, build(false));     // 編集できる人の一覧が戻せないときは、一覧なしで付け直して知らせる
    if (notes) notes.push('保護の「編集できる人」の一覧は戻せませんでした（保護そのものは付け直しました）');
    }
  }
  recs.forEach(function (b) {
    if (b.side.filter) restoreFilter_(ss, b.id, b.side.filter, notes);   // フィルタは SpreadsheetApp で付け直す（API の setBasicFilter では隠す行が反映されない）
    else if (b.side.filter === null) { var shf = byId_(ss, b.id); var f0 = shf && shf.getFilter(); if (f0) f0.remove(); }
  });
}

// 記録した spec から、種類・範囲・位置・題だけを SpreadsheetApp で作り直す（API の addChart が通らない形のとき）
function restoreChartApp_(sh, ch) {
  var spec = ch.spec || {}, srcs = [], type = null;
  var take = function (x) { if (x && x.sourceRange) (x.sourceRange.sources || []).forEach(function (s) { srcs.push(s); }); };
  if (spec.basicChart) { type = spec.basicChart.chartType || 'COLUMN'; (spec.basicChart.domains || []).forEach(function (d) { take(d.domain); }); (spec.basicChart.series || []).forEach(function (s) { take(s.series); }); }
  else if (spec.pieChart) { type = 'PIE'; take(spec.pieChart.domain); take(spec.pieChart.series); }
  if (!type || !Charts.ChartType[type]) throw new Error('作れない種類: ' + type);
  var b = sh.newChart().setChartType(Charts.ChartType[type]);
  srcs.forEach(function (r) { b.addRange(sh.getRange((r.startRowIndex || 0) + 1, (r.startColumnIndex || 0) + 1, (r.endRowIndex || sh.getMaxRows()) - (r.startRowIndex || 0), (r.endColumnIndex || sh.getMaxColumns()) - (r.startColumnIndex || 0))); });
  var pos = ch.position && ch.position.overlayPosition;
  if (pos && pos.anchorCell) b.setPosition((pos.anchorCell.rowIndex || 0) + 1, (pos.anchorCell.columnIndex || 0) + 1, pos.offsetXPixels || 0, pos.offsetYPixels || 0);
  if (spec.title) b.setOption('title', spec.title);
  sh.insertChart(b.build());
}

function restoreFilter_(ss, id, f, notes) {
  var sh = byId_(ss, id);
  if (!sh || !f || !f.range) return;
  var g = f.range, r0 = g.startRowIndex || 0, c0 = g.startColumnIndex || 0;
  var nr = (g.endRowIndex || sh.getMaxRows()) - r0, nc = (g.endColumnIndex || sh.getMaxColumns()) - c0;
  var old = sh.getFilter(); if (old) old.remove();
  var filter = sh.getRange(r0 + 1, c0 + 1, nr, nc).createFilter(), hard = false;
  Object.keys(f.criteria || {}).forEach(function (k) {
    var c = f.criteria[k];
    if (c.hiddenValues && c.hiddenValues.length && !c.condition) filter.setColumnFilterCriteria(parseInt(k, 10) + 1, SpreadsheetApp.newFilterCriteria().setHiddenValues(c.hiddenValues).build());
    else hard = true;
  });
  SpreadsheetApp.flush();   // 隠す行を反映してから返す（このあと API で読む人が古い状態を見ない）
  if (hard && notes) notes.push('フィルタの条件のうち、隠す値の指定以外（条件式・色）は付け直せませんでした（フィルタの範囲と隠す値は戻しました）');
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

function msOut_(tm) { var o = {}; Object.keys(BKT).forEach(function (k) { o[k] = BKT[k]; }); Object.keys(tm).forEach(function (k) { if (k !== 't0' && k !== 'last') o[k] = tm[k]; }); o.total = Date.now() - tm.t0; return o; }
function lap_(tm, k) { var n = Date.now(); tm[k] = (tm[k] || 0) + (n - tm.last); tm.last = n; }   // 区切りごとのミリ秒（返事の ms。道具が WS_TIMING のときだけ見せる）

function actDo_(req) {
  var tc = Date.now();
  var cache = CacheService.getScriptCache();
  if (req.call_id) {
    var hit = cache.get('call_' + req.call_id);
    if (hit) { var r0 = JSON.parse(hit); r0.replayed = true; return r0; }
  }
  var cacheGetMs = Date.now() - tc;
  var res = runDo_(req, Date.now());
  if (res && res.ms) res.ms.cacheGet = cacheGetMs;
  if (req.call_id && !(res && res.stale)) { try { var s = JSON.stringify(res); if (s.length < 90000) cache.put('call_' + req.call_id, s, 21600); } catch (e) { } }
  return res;
}

function runDo_(req, T0) {
  BKT = {};
  var tm = { t0: T0 || Date.now() }; tm.last = tm.t0;
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
  lap_(tm, 'open');
  if (req.expect && kind === 'sheet' && !created) {
    var shE = (t.sheet && file.getSheetByName(t.sheet)) ? t.sheet : file.getSheets()[0].getName(), nowT = tableOfSheet_(file, shE);
    if (!sameTable_(nowT, req.expect)) {
      return { ok: false, stale: true, error: '表の形が変わっていました（書いていません）', target: { id: file.getId(), name: file.getName(), kind: 'sheet', url: file.getUrl(), sheet: shE },
        table: nowT && !nowT.none ? nowT : null, sheets: file.getSheets().map(function (s) { return s.getName(); }), ms: msOut_(tm) };
    }
    lap_(tm, 'expect');
  }
  var l = ledger_(); l.seq++; var n = l.seq;   // 番号は最後の書き込みでまとめて残す（鍵の中なので重ならない。失敗・変更なしでは番号を使い回す）
  lap_(tm, 'seq');
  var fid = created ? created.id : (t.id || file.getId()), fname = created ? created.name : file.getName();
  var ctx = { wideKey: digest_(fid + '|' + JSON.stringify(ops), FP_VER), kind: kind, file: file, ss: kind === 'sheet' ? file : null, doc: kind === 'doc' ? file : null,
    sheetName: t.sheet || '', ok: !!req.ok, changed: [], notes: [], remaining: [], createdSheets: [], n: n, isNew: !!created,
    _file: { id: fid, name: fname, url: created ? created.url : null } };
  var entry = { n: n, time: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'), id: fid,
    name: fname, kind: kind, what: summarizeOps_(ops), isNew: !!created, fp: FP_VER };
  var bk = null, sideItems = [], liteItems = null, isLite = false;
  try {
    if (!created) {
      if (kind === 'sheet') {
        var names = touchedSheets_(ctx, ops);
        liteItems = liteTouch_(ops);
        if (liteItems !== null) {
          bk = backupSheetsLite_(ctx.ss, names, n, liteItems);
          if (bk !== null) isLite = true;
        }
        if (!isLite) {
          sideItems = sideItems_(ops);
          bk = backupSheets_(ctx.ss, names, n, sideItems);
        }
        lap_(tm, 'backup');
        entry.sheets = bk;
        if (isLite) {
          entry.lite = true;
          entry.liteItems = liteItems;
          tm.finger0 = 0;
        } else {
          entry.before = {}; names.forEach(function (sh0, idx) { var b0 = bk[idx]; entry.before[b0.id] = fingerSheet_(sh0, FP_VER, b0); });
        }
      } else { entry.doc = backupDoc_(ctx.doc, n); lap_(tm, 'backup'); entry.beforeDoc = fingerDoc_(ctx.doc); }
    }
    ctx.bk = bk; lap_(tm, 'finger0');
    for (var i = 0; i < ops.length; i++) {
      var op = ops[i], fn = SHELF[op.shelf];
      if (!fn) throw new ArgError('棚「' + op.shelf + '」はありません');
      if (fn.kind && fn.kind !== kind) throw new ArgError('棚「' + op.shelf + '」は' + (fn.kind === 'doc' ? '文書' : 'シート') + '用です（今の相手は' + (kind === 'doc' ? '文書' : 'スプレッドシート') + '）');
      ctx.opNo = i + 1; ctx.opName = op.shelf;
      fn(ctx, op);
    }
    if (kind === 'sheet' && (created || !(entry.sheets && entry.sheets.length))) SpreadsheetApp.flush();
    lap_(tm, 'ops');
    if (kind === 'doc') { ctx.doc.saveAndClose(); ctx.doc = DocumentApp.openById(entry.id); file = ctx.doc; lap_(tm, 'save'); }
    // 書き終わりの指紋
    if (kind === 'sheet') {
      entry.after = {};
      var hasFix = isLite && liteItems.indexOf('固定') >= 0;
      (entry.sheets || []).forEach(function (b) {
        var s = byId_(ctx.ss, b.id);
        if (s) entry.after[b.id] = fingerSheet_(s, FP_VER, isLite ? (hasFix ? { name: b.name } : b) : null);
      });
      entry.created = {};
      ctx.createdSheets.forEach(function (nm) { var s = ctx.ss.getSheetByName(nm); if (s) entry.created[nm] = fingerSheet_(s); });
    } else entry.afterDoc = fingerDoc_(ctx.doc);
    // 何も変わらなかった（すでにその状態）なら、記録も控えも残さない（undo が空振りしないように）
    lap_(tm, 'finger');
    var noop = !created && isNoop_(ops, entry, ctx);
    lap_(tm, 'noop');
    if (noop) {
      discardBackup_(bk); lap_(tm, 'discard');
      return { ok: true, target: tgt_(ctx, file), changed: [], notes: ['変更はありませんでした（すでにその状態です）'].concat(ctx.notes.filter(function (x) { return x.indexOf('変更なし') < 0; })), remaining: ctx.remaining, backup: 0, ms: msOut_(tm) };
    }
    var sideRec = (bk && bk.length) ? packSide_(bk, isLite ? liteItems : sideItems) : null;
    if (sideRec) { saveSide_(n, sideRec); entry.hasSide = true; entry.sideItems = sideRec.items; entry.sheets = stripSide_(bk); }
    l.items.push(entry); ledgerSave_(l);
    lap_(tm, 'ledger');
    var out = { ok: true, target: tgt_(ctx, file), changed: ctx.changed, notes: ctx.notes, remaining: ctx.remaining, backup: created ? 0 : n, ms: msOut_(tm) };
    if (created) { out.created = created; }
    if (req.want_table && kind === 'sheet') {   // 撃った後の表の形（道具が覚えて、次の頼みの引数に使う・AI が確かめの look を撃たなくて済む）
      try { out.table = tableOfSheet_(ctx.ss, out.target.sheet); out.sheets = ctx.ss.getSheets().map(function (s) { return s.getName(); }); lap_(tm, 'table'); out.ms = msOut_(tm); } catch (eT) { }
    }
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
      restored: restored, restore_error: why, blocked: !!err.isBlocked, needs_ok: !!err.isBlocked, arg: !!err.isArg, target: tgt_(ctx, file), stack: String(err.stack || '').slice(0, 400) };
    if (created) out2.created = created;
    return out2;
  }
}

// 変更なしの判定。棚の「触る:」（CATALOG）に、指紋に出る物が 1 つでもある棚は指紋で比べる。
// 指紋に出る物＝値・シート構成・固定、シートでは書式も（文書の指紋は文字と見出し構造だけなので、文書の書式は出ない）。
// 幅 は指紋に出ない（棚が「付随して触る」だけなら、判定は前のまま指紋）。フィルタを触る棚は、実際にフィルタが変わったかも比べる。
// 指紋に出る物が 1 つも無い棚（幅だけ・文書の書式だけ 等）を含むときは、棚が報告した変更（ctx.changed）が空のときだけ「変更なし」
var FINGER_ITEMS_ = ['値', 'シート構成', '固定'];
function fingerOnly_(ops, kind) {
  return ops.every(function (o) {
    var c = CATALOG[o.shelf];
    return !!c && c.touch.some(function (t) { return FINGER_ITEMS_.indexOf(t) >= 0; });
  });
}
function touchesItem_(ops, item) {
  return ops.some(function (o) {
    var c = CATALOG[o.shelf];
    if (c && c.touch && c.touch.indexOf(item) >= 0) return true;
    return !!(DYNAMIC[o.shelf] && DYNAMIC[o.shelf].touch && DYNAMIC[o.shelf].touch(o).indexOf(item) >= 0);
  });
}
function normJson_(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(function (x) { return x === undefined ? 'null' : normJson_(x); }).join(',') + ']';
  return '{' + Object.keys(v).sort().filter(function (k) { return v[k] !== undefined; }).map(function (k) { return JSON.stringify(k) + ':' + normJson_(v[k]); }).join(',') + '}';
}
// フィルタの有無や設定内容が実行前後で実際に変わったか調べる
function filterChanged_(ctx, entry) {
  var both = [];
  for (var i = 0; i < (entry.sheets || []).length; i++) {
    var b = entry.sheets[i], s = ctx.ss && byId_(ctx.ss, b.id);
    if (!s || typeof s.getFilter !== 'function') continue;
    var had = !!(b.side && b.side.filter), has = !!s.getFilter();
    if (had !== has) return true;
    if (had && has) both.push(b);
  }
  if (!both.length) return false;
  if (typeof SpreadsheetApp !== 'undefined' && typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
  if (typeof Sheets === 'undefined' || !Sheets.Spreadsheets || typeof Sheets.Spreadsheets.get !== 'function') return ctx.changed.length > 0;
  try {
    var resp = Sheets.Spreadsheets.get(ctx.ss.getId(), { fields: 'sheets(properties(sheetId),basicFilter)' });
    var byId = {};
    (resp.sheets || []).forEach(function (x) { byId[x.properties.sheetId] = x.basicFilter || null; });
    return both.some(function (b) { return normJson_(b.side.filter) !== normJson_(byId[b.id] || null); });
  } catch (e) {
    return ctx.changed.length > 0;
  }
}
function isNoop_(ops, entry, ctx) {
  if (ctx.createdSheets.length) return false;
  if (entry.lite) {
    if (entry.liteItems && entry.liteItems.length === 1 && entry.liteItems[0] === '固定') {
      return (entry.sheets || []).every(function (b) { var s = byId_(ctx.ss, b.id); return s && s.getFrozenRows() === b.frozenR && s.getFrozenColumns() === b.frozenC; });
    }
    return ctx.changed.length === 0;
  }
  if (!fingerOnly_(ops, ctx.kind)) return ctx.changed.length === 0;
  if (ctx.kind === 'sheet') {
    if (!entry.sheets || !entry.sheets.length) return false;
    if (!entry.sheets.every(function (b) { return sameFinger_(entry.before[b.id], entry.after[b.id]); })) return false;
    if (touchesItem_(ops, 'フィルタ') && filterChanged_(ctx, entry)) return false;
    return true;
  }
  return sameFinger_(entry.beforeDoc, entry.afterDoc);
}

function tgt_(ctx, file) {
  var f = ctx._file || {};
  var o = { id: f.id || file.getId(), name: f.name || file.getName(), kind: ctx.kind, url: f.url || file.getUrl() };
  if (ctx.kind === 'sheet') o.sheet = ctx.curSheet || ctx.sheetName || ctx._sheet0 || ctx.ss.getSheets()[0].getName();
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
  var def = ctx.sheetName || (ctx._sheet0 = ss.getSheets()[0].getName());
  ops.forEach(function (op) {
    if (DYNAMIC[op.shelf]) { DYNAMIC[op.shelf].sheets(ctx, op).forEach(add); return; }   // 控えるシートを引数から決める棚
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
  (bk || []).forEach(function (b) { if (!b.lite) restoreSheet_(ss, b); });
  restoreSide_(ss, bk, null);
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
      if (s && it.after && it.after[b.id] && !sameFinger_(it.after[b.id], fingerSheet_(s, it.fp || 1))) hand.push(b.name);
    });
    Object.keys(it.created || {}).forEach(function (nm) {
      var s = ss.getSheetByName(nm);
      if (s && !sameFinger_(it.created[nm], fingerSheet_(s, it.fp || 1))) hand.push(nm);
    });
  } else if (it.afterDoc && !sameFinger_(it.afterDoc, fingerDoc_(file, it.fp || 1))) hand.push(file.getName());
  if (hand.length && !req.ok)
    return { ok: false, needs_ok: true, error: '道具が書いた後に手で直した所があります（戻すと消えます）: ' + hand.join('、') + '。それでも戻すなら ok=True', target: { id: it.id, name: it.name, kind: it.kind, url: file.getUrl() } };
  // 戻す前の状態も控えに取る（undo の undo）
  l.seq++; var n = l.seq; setJson_('LEDGER', l);
  var undoNotes = [];
  var entry = { n: n, time: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'), id: it.id, name: it.name, kind: it.kind, what: 'undo #' + it.n, isUndo: true, fp: FP_VER };
  try {
    if (it.kind === 'sheet') {
      var ss2 = file, names = [];
      (it.sheets || []).forEach(function (b) { var s = byId_(ss2, b.id); if (s) names.push(s); });
      var undoLite = false;
      if (it.lite && it.liteItems) {
        entry.sheets = backupSheetsLite_(ss2, names, n, it.liteItems);
        if (entry.sheets !== null) { undoLite = true; entry.lite = true; entry.liteItems = it.liteItems; }
      }
      if (!undoLite) entry.sheets = backupSheets_(ss2, names, n, it.sideItems || []);
      var made = Object.keys(it.created || {});
      made.forEach(function (nm) { var s = ss2.getSheetByName(nm); if (s && ss2.getSheets().length > 1) ss2.deleteSheet(s); });
      var bks = loadSide_(it);
      bks.forEach(function (b) { if (!b.lite) restoreSheet_(ss2, b); });
      restoreSide_(ss2, bks, undoNotes);
      SpreadsheetApp.flush();
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
  var sideRec2 = (entry.sheets && entry.sheets.length) ? packSide_(entry.sheets, entry.lite ? entry.liteItems : (it.sideItems || [])) : null;
  if (sideRec2) { saveSide_(n, sideRec2); entry.hasSide = true; entry.sideItems = sideRec2.items; entry.sheets = stripSide_(entry.sheets); }
  it.undone = true; l.items.push(entry); ledgerSave_(l);
  return { ok: true, undone: it.n, backup: n, what: it.what, notes: undoNotes, target: { id: it.id, name: it.name, kind: it.kind, url: file.getUrl() } };
}

// ---------------------------------------------------------------- look


// ---------------------------------------------------------------- ws_look: 脇の状態（あるときだけ短く 1 行ずつ）
// AI が「このセルにはもうプルダウンがある」「ここは保護されている」を知らずに撃たないための知らせ。無ければ何も出さない
function gridA1_(g) {
  if (!g) return '';
  var r0 = g.startRowIndex || 0, c0 = g.startColumnIndex || 0;
  if (g.startRowIndex === undefined && g.endRowIndex === undefined && g.startColumnIndex === undefined && g.endColumnIndex === undefined) return 'シート全体';
  var a = colLetter_(c0 + 1) + (r0 + 1);
  var r1 = g.endRowIndex, c1 = g.endColumnIndex;
  if (r1 === undefined && c1 === undefined) return a;
  if ((r1 === undefined || r1 === r0 + 1) && (c1 === undefined || c1 === c0 + 1)) return a;
  return a + ':' + (c1 !== undefined ? colLetter_(c1) : '') + (r1 !== undefined ? r1 : '');
}
function numRuns_(idx0) {   // 0 始まりの添字の並び → 「9、20-22」（1 始まり）
  var out = [], s = -1, prev = -2;
  idx0.forEach(function (i) { if (i === prev + 1) { prev = i; return; } if (s >= 0) out.push(s === prev ? '' + (s + 1) : (s + 1) + '-' + (prev + 1)); s = i; prev = i; });
  if (s >= 0) out.push(s === prev ? '' + (s + 1) : (s + 1) + '-' + (prev + 1));
  return out;
}
function colRuns_(idx0) { return numRuns_(idx0).map(function (x) { return x.replace(/\d+/g, function (n) { return colLetter_(parseInt(n, 10)); }); }); }
function capList_(arr, n) { return arr.length > n ? arr.slice(0, n).concat(['ほか ' + (arr.length - n)]) : arr; }
var CHART_NAMES = { COLUMN: '縦棒', BAR: '横棒', LINE: '折れ線', PIE: '円', AREA: '面', SCATTER: '散布図', COMBO: '複合', STEPPED_AREA: '階段面' };
function validationLabel_(v) {
  var c = v.condition || {}, vals = (c.values || []).map(function (x) { return x.userEnteredValue || ''; });
  if (c.type === 'ONE_OF_LIST') return 'プルダウン（' + vals.slice(0, 4).join('/') + (vals.length > 4 ? '…' : '') + '）';
  if (c.type === 'ONE_OF_RANGE') return 'プルダウン（範囲 ' + String(vals[0] || '').replace(/^=/, '') + '）';
  if (c.type === 'BOOLEAN') return 'チェックボックス';
  if (/^NUMBER_/.test(c.type)) return '数値の入力規則';
  if (/^DATE_/.test(c.type)) return '日付の入力規則';
  return String(c.type || '入力規則');
}
function lookSide_(ss, sh) {
  var lines = [], id = sh.getSheetId();
  var r1 = Sheets.Spreadsheets.get(ss.getId(), { fields: 'namedRanges,sheets(properties(sheetId),basicFilter,rowGroups,columnGroups,protectedRanges(range,warningOnly),charts(spec(title,basicChart(chartType),pieChart(legendPosition))),bandedRanges(range))' });
  var x = (r1.sheets || []).filter(function (s) { return s.properties.sheetId === id; })[0] || {};
  var maxR = Math.min(sh.getLastRow(), 2000), maxC = Math.min(sh.getLastColumn(), 60), d = null;
  if (maxR > 0 && maxC > 0) {
    var r2 = Sheets.Spreadsheets.get(ss.getId(), { includeGridData: true, ranges: [q_(sh.getName()) + '!A1:' + colLetter_(maxC) + maxR],
      fields: 'sheets(properties(sheetId),data(rowMetadata(hiddenByUser),columnMetadata(hiddenByUser),rowData(values(dataValidation))))' });
    d = (((r2.sheets || [])[0] || {}).data || [])[0] || null;
  }
  // 入力規則: 同じ規則のセルを、列ごとの行の連なりにして範囲で書く
  if (d && d.rowData) {
    var bySig = {};
    d.rowData.forEach(function (row, r) { (row.values || []).forEach(function (cell, c) { if (cell.dataValidation) { var k = validationLabel_(cell.dataValidation); (bySig[k] = bySig[k] || []).push([r, c]); } }); });
    var vparts = [];
    Object.keys(bySig).forEach(function (k) {
      var cols = {}; bySig[k].forEach(function (rc) { (cols[rc[1]] = cols[rc[1]] || []).push(rc[0]); });
      var runsByKey = {};
      Object.keys(cols).map(Number).sort(function (a, b) { return a - b; }).forEach(function (c) {
        numRuns_(cols[c]).forEach(function (rr) { var m = rr.split('-'); var key = rr; (runsByKey[key] = runsByKey[key] || { r: m, cols: [] }).cols.push(c); });
      });
      Object.keys(runsByKey).forEach(function (key) {
        var o = runsByKey[key], cs = o.cols, st = cs[0], pv = cs[0];
        for (var i = 1; i <= cs.length; i++) {
          if (i < cs.length && cs[i] === pv + 1) { pv = cs[i]; continue; }
          var a = colLetter_(st + 1) + o.r[0], b = colLetter_(pv + 1) + (o.r[1] || o.r[0]);
          vparts.push((a === b ? a : a + ':' + b) + ' ' + k); if (i < cs.length) { st = cs[i]; pv = cs[i]; }
        }
      });
    });
    if (vparts.length) lines.push('入力規則: ' + capList_(vparts, 4).join('、'));
  }
  (x.bandedRanges || []).length && lines.push('交互の色: ' + capList_((x.bandedRanges || []).map(function (b) { return gridA1_(b.range); }), 3).join('、'));
  var prot = (x.protectedRanges || []).map(function (q) { return gridA1_(q.range) + (q.warningOnly ? '（警告のみ）' : ''); });
  if (prot.length) lines.push('保護: ' + capList_(prot, 3).join('、'));
  if (x.basicFilter) {
    var f = x.basicFilter, cr = Object.keys(f.criteria || {}).map(function (k) { return colLetter_(parseInt(k, 10) + 1); });
    lines.push('フィルタ: ' + gridA1_(f.range) + (cr.length ? '（' + cr.join('・') + ' 列で絞り込み中）' : ''));
  }
  if (d) {
    var hr = [], hc = [];
    (d.rowMetadata || []).forEach(function (m, i) { if (m && m.hiddenByUser) hr.push(i); });
    (d.columnMetadata || []).forEach(function (m, i) { if (m && m.hiddenByUser) hc.push(i); });
    var hp = [];
    if (hr.length) hp.push('隠した行: ' + capList_(numRuns_(hr), 4).join('、'));
    if (hc.length) hp.push('隠した列: ' + capList_(colRuns_(hc), 4).join('、'));
    if (hp.length) lines.push(hp.join(' ／ '));
  }
  var gp = [];
  (x.rowGroups || []).forEach(function (g) { gp.push('行 ' + ((g.range.startIndex || 0) + 1) + '-' + g.range.endIndex + '（深さ' + g.depth + (g.collapsed ? '・畳んである' : '') + '）'); });
  (x.columnGroups || []).forEach(function (g) { gp.push('列 ' + colLetter_((g.range.startIndex || 0) + 1) + '-' + colLetter_(g.range.endIndex) + '（深さ' + g.depth + (g.collapsed ? '・畳んである' : '') + '）'); });
  if (gp.length) lines.push('グループ: ' + capList_(gp, 3).join('、'));
  var nm = (r1.namedRanges || []).map(function (n) { return n.name + '=' + gridA1_(n.range); });
  if (nm.length) lines.push('名前付き範囲: ' + capList_(nm, 4).join('、'));
  var ch = (x.charts || []).map(function (c) { var s = c.spec || {}, ty = s.basicChart ? s.basicChart.chartType : (s.pieChart ? 'PIE' : ''); return (CHART_NAMES[ty] || ty || 'グラフ') + (s.title ? '（' + s.title + '）' : ''); });
  if (ch.length) lines.push('グラフ: ' + capList_(ch, 3).join('、'));
  return lines;
}

function tableOut_(tb) {
  return { header_row: tb.headerRow, first_col: colLetter_(tb.firstCol), last_col: colLetter_(tb.lastCol), data: tb.firstData + '-' + tb.lastData,
    total_row: tb.totalRow || null, columns: headerNames_(tb).map(function (h, i) { var ci = tb.firstCol + i; return { col: colLetter_(ci), name: h, number: isNumberCol_(tb, ci) }; }) };
}
// 頼みの文から引数を組んだ ws_do（ask）用：道具が覚えている表の形と、今の表の形が同じか。違えば書く前に止めて今の形を返す
function tableOfSheet_(ss, name) {
  var sh = name ? ss.getSheetByName(name) : null;
  if (!sh) return null;
  var tb = findTable_(sh);
  return tb ? tableOut_(tb) : { none: true };
}
function sameTable_(a, e) {
  if (!a || a.none || !e) return false;
  if (a.header_row !== e.header_row || a.data !== e.data || (a.total_row || null) !== (e.total_row || null)) return false;
  var an = a.columns.map(function (c) { return c.col + '=' + c.name; }).join('|');
  var en = (e.columns || []).map(function (c) { return c.col + '=' + c.name; }).join('|');
  return an === en;
}

function actLook_(req) {
  var t = req.target || {}, o = openTarget_(t), out = { ok: true };
  if (o.kind === 'sheet') {
    var ss = o.file;
    out.target = { id: ss.getId(), name: ss.getName(), kind: 'sheet', url: ss.getUrl() };
    out.sheets = ss.getSheets().map(function (s) { return { name: s.getName(), rows: s.getLastRow(), cols: s.getLastColumn() }; });
    var sh = sheetOf_(ss, req.sheet || t.sheet, '');
    out.target.sheet = sh.getName();
    try { var side = lookSide_(ss, sh); if (side.length) out.side = side; } catch (eS) { }   // 脇の状態は添え物。読めなくても look は返す
    var tb = findTable_(sh);
    if (tb) out.table = tableOut_(tb);
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
// 消す手の守り。wide（広い削除）のときは、ok=True でも道具の側で 1 回止める（試験設計書 第 3.5 節 (1)・第 13 章）
function guardDelete_(ctx, msg, wide, count) {
  if (wide) return guardWide_(ctx, msg, count);
  if (!ctx.ok) throw new Blocked(msg + '（人の値を消すので、「消してよい」の承認＝ok=True が要ります）');
}
// 広い削除（シートごと・シート全体・表の外まで・明細の半分より多く）: 同じ相手・同じ ops が直前（10 分以内）に 1 回止まっていなければ、ok=True でも止める。
// ok なしの下見も 1 回目に数える（ふつうの「下見 → 承認 → ok=True」は今までと同じ 2 往復）。止めた ops の指紋だけを覚え、同じ ops が ok=True で来たら通す
var WIDE_MS = 10 * 60 * 1000;
function guardWide_(ctx, msg, count) {
  var now = Date.now(), map = getJson_('WIDE', {}), key = ctx.wideKey || 'x', live = {};
  Object.keys(map).forEach(function (k) { if (now - map[k] < WIDE_MS) live[k] = map[k]; });
  if (ctx.ok && live[key]) { delete live[key]; setJson_('WIDE', live); return; }
  live[key] = now; setJson_('WIDE', live);
  throw new Blocked('広い削除です。' + (count ? '消える数: ' + count + '。' : '') + (msg.length > 150 ? msg.slice(0, 150) + '…' : msg) + '（何が消えるかを使う人に見せて、「消してよい」の承認を得てから、同じ ops をもう一度 ok=True で撃つと通ります）');
}
// 広さの目安: 範囲がシートの値のある範囲を全部覆う／表の外まで及ぶ
function wideRange_(sh, rg) {
  var dr = sh.getDataRange();
  if (rg.getRow() <= dr.getRow() && rg.getColumn() <= dr.getColumn() && rg.getLastRow() >= dr.getLastRow() && rg.getLastColumn() >= dr.getLastColumn()) return true;
  var t = findTable_(sh);
  if (t) {
    var last = t.totalRow || t.lastData;
    if (rg.getRow() < t.headerRow || rg.getLastRow() > last || rg.getColumn() < t.firstCol || rg.getLastColumn() > t.lastCol) return true;
  }
  return false;
}
function wideRowCount_(t, n) { return !!t && n > (t.lastData - t.firstData + 1) / 2; }
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
    '薄赤': '#FCE4D6', '薄青': '#D9E1F2', '薄緑': '#E2EFDA', '薄黄': '#FFF2CC', '薄灰': '#F2F2F2', '薄灰色': '#F2F2F2', '薄グレー': '#F2F2F2', '薄橙': '#FCE5CD', '薄紫': '#EAD1DC',
    'lightred': '#FCE4D6', 'lightgreen': '#E2EFDA', 'lightyellow': '#FFF2CC', 'lightgray': '#F2F2F2'
  };
  var k = str.toLowerCase();
  if (map[k] !== undefined) return map[k];
  if (map[str] !== undefined) return map[str];
  // 「黄色」「薄い灰色」などの表記ゆれを吸収する
  var norm = str.replace(/^薄い/, '薄').replace(/色$/, '');
  if (map[norm] !== undefined) return map[norm];
  var norm2 = str.replace(/^薄い/, '薄');
  if (map[norm2] !== undefined) return map[norm2];
  throw new ArgError('知らない色の名前です: 「' + str + '」');
}
function shiftFormula_(f, off) {
  if (!off || typeof f !== 'string' || f.charAt(0) !== '=') return f;
  return f.replace(/(\$?[A-Z]{1,3}\$?)(\d+)/g, function (m, c, r) { return c.indexOf('$') >= 0 && /\$$/.test(c) ? m : c + (parseInt(r) + off); });
}
