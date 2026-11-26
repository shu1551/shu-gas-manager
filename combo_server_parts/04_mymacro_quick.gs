// ---------------------------------------------------------------- マイマクロ・一覧連携（GASクイック互換）

var QUICK_MY_TITLE = 'GASクイック マイマクロ';
var QUICK_SCRIPT_JSON = 'application/vnd.google-apps.script+json';
var QUICK_MY_ID_KEY = 'QUICK_MY_ID';
var QUICK_PINS_KEY = 'QUICK_PINS';
var QUICK_BK_NAME = '_GASクイックの控え';
var QUICK_JS_RESERVED_ = {
  'break': 1, 'case': 1, 'catch': 1, 'class': 1, 'const': 1, 'continue': 1, 'debugger': 1,
  'default': 1, 'delete': 1, 'do': 1, 'else': 1, 'enum': 1, 'export': 1, 'extends': 1,
  'false': 1, 'finally': 1, 'for': 1, 'function': 1, 'if': 1, 'import': 1, 'in': 1,
  'instanceof': 1, 'let': 1, 'new': 1, 'null': 1, 'return': 1, 'static': 1, 'super': 1,
  'switch': 1, 'this': 1, 'throw': 1, 'true': 1, 'try': 1, 'typeof': 1, 'var': 1,
  'void': 1, 'while': 1, 'with': 1, 'yield': 1, 'await': 1, 'eval': 1, 'arguments': 1
};

function quickOrderKey_(kind, optSsId) {
  if (kind === 'sheet') {
    var id = optSsId || '';
    if (!id) { try { id = comboOpenSs_({}).getId(); } catch (e) {} }
    return 'QUICK_ORDER_sheet_' + id;
  }
  return 'QUICK_ORDER_' + (kind === 'my' ? 'my' : 'shelf');
}

function quickGetOrders_(optAllProps, optSsId) {
  var props = optAllProps;
  if (!props) {
    try { props = PropertiesService.getUserProperties().getProperties() || {}; } catch (e) { props = {}; }
  }
  var out = {};
  ['sheet', 'my', 'shelf'].forEach(function (k) {
    try { out[k] = JSON.parse(props[quickOrderKey_(k, optSsId)] || '[]'); } catch (e) { out[k] = []; }
  });
  return out;
}

function quickGetPins_(optAllProps) {
  try {
    var raw = optAllProps ? optAllProps[QUICK_PINS_KEY] : PropertiesService.getUserProperties().getProperty(QUICK_PINS_KEY);
    var parsed = raw ? JSON.parse(raw) : {};
    return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : {};
  } catch (e) {
    return {};
  }
}

/** 一覧のピン留め（★）状態をユーザーごとに保存する。 */
function comboQuickSavePins(req) {
  req = req || {};
  var raw = (req.pins && typeof req.pins === 'object' && !Array.isArray(req.pins)) ? req.pins : {};
  var clean = {}, keys = Object.keys(raw).slice(0, 400);
  for (var i = 0; i < keys.length; i++) {
    if (raw[keys[i]]) clean[String(keys[i])] = 1;
  }
  try {
    PropertiesService.getUserProperties().setProperty(QUICK_PINS_KEY, JSON.stringify(clean));
    return { ok: true, pins: clean };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

/** 区切りの中の並びを覚える（names＝上からの名前の並び）。 */
function comboQuickSaveOrder(req) {
  req = req || {};
  var kind = req.kind === 'sheet' ? 'sheet' : (req.kind === 'my' ? 'my' : 'shelf');
  var names = (req.names || []).map(String).slice(0, 400);
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim();
  try {
    PropertiesService.getUserProperties().setProperty(quickOrderKey_(kind, ssId), JSON.stringify(names));
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

// 手順文字列を安全に分割する（エスケープされた \/・\／ や URL・日付 2026/11/21 を保護）
function quickSplitSteps_(raw) {
  var s = String(raw || '').trim();
  if (!s) return [];
  var tokens = [], idx = 0;
  var protect = function (re) {
    s = s.replace(re, function (m) {
      var key = '\uE002' + (idx++) + '\uE003';
      tokens.push(m);
      return key;
    });
  };
  protect(/\\\//g);
  protect(/\\／/g);
  protect(/https?:\/\/[^\s]+/g);
  protect(/\d+(?:\/\d+)+/g);
  var parts = (/／|\s+\/\s+/.test(s)) ? s.split(/\s*／\s*|\s+\/\s+/) : s.split(/\s*\/\s*/);
  return parts.map(function (st) {
    var restored = st.replace(/\uE002(\d+)\uE003/g, function (_, n) {
      var t = tokens[parseInt(n, 10)] || '';
      if (t === '\\/') return '/';
      if (t === '\\／') return '／';
      return t;
    });
    return restored.trim();
  }).filter(Boolean);
}

function quickMyFind_(wantMeta, optAllProps, optForce) {
  var cache = comboCache_();
  if (!optForce && cache) {
    try {
      var mRaw = cache.get('QUICK_MY_META');
      if (mRaw) {
        var m = JSON.parse(mRaw);
        if (m && m.id && m.checkedAt && (Date.now() - m.checkedAt < 60000)) {
          return wantMeta ? { id: m.id, stamp: m.stamp || '' } : m.id;
        }
      }
    } catch (eC) {}
  }
  var props = null;
  try { props = PropertiesService.getUserProperties(); } catch (ePr) {}
  var known = optAllProps ? (optAllProps[QUICK_MY_ID_KEY] || '') : (props ? props.getProperty(QUICK_MY_ID_KEY) : '');
  if (known && typeof DriveApp !== 'undefined') {
    try {
      var f = DriveApp.getFileById(known);
      if (!f.isTrashed() && f.getName() === QUICK_MY_TITLE) {
        var st = String(f.getLastUpdated().getTime());
        if (cache) { try { cache.put('QUICK_MY_META', JSON.stringify({ id: known, stamp: st, checkedAt: Date.now() }), 300); } catch (ePut1) {} }
        return wantMeta ? { id: known, stamp: st } : known;
      }
    } catch (e) {}
    if (props) { try { props.deleteProperty(QUICK_MY_ID_KEY); } catch (eDel) {} }
  }
  if (typeof DriveApp !== 'undefined') {
    var q = DriveApp.searchFiles("title = '" + QUICK_MY_TITLE + "' and mimeType = 'application/vnd.google-apps.script' and trashed = false");
    if (q.hasNext()) {
      var nf = q.next();
      var id = nf.getId();
      var st2 = String(nf.getLastUpdated().getTime());
      if (props) { try { props.setProperty(QUICK_MY_ID_KEY, id); } catch (eSet) {} }
      if (cache) { try { cache.put('QUICK_MY_META', JSON.stringify({ id: id, stamp: st2, checkedAt: Date.now() }), 300); } catch (ePut2) {} }
      return wantMeta ? { id: id, stamp: st2 } : id;
    }
  }
  if (cache) { try { cache.remove('QUICK_MY_META'); } catch (eRm) {} }
  return wantMeta ? { id: '', stamp: '' } : '';
}

function quickMyStamp_(id) {
  try { return typeof DriveApp !== 'undefined' ? String(DriveApp.getFileById(id).getLastUpdated().getTime()) : ''; } catch (e) { return ''; }
}

function quickMyInvalidate_(id) {
  if (!id) return;
  try {
    var cache = comboCache_();
    if (!cache) return;
    cache.remove('QUICK_MY_LIST_' + id);
    cache.remove('QUICK_MY_SRC_' + id);
    cache.remove('QUICK_MY_META');
  } catch (e) {}
}

function quickMyCachePut_(id, src, optStamp) {
  if (!id) return '';
  var stamp = optStamp || quickMyStamp_(id) || String(Date.now());
  try {
    var cache = comboCache_();
    if (!cache) return stamp;
    var nowTs = Date.now();
    var srcStr = String(src || '');
    var payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, src: srcStr });
    if (payload.length > 50000 && typeof Utilities !== 'undefined') {
      var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(srcStr, 'text/plain')).getBytes());
      payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, __gz: gz });
    }
    if (payload.length < 95000) {
      cache.put('QUICK_MY_SRC_' + id, payload, 21600);
    } else {
      cache.remove('QUICK_MY_SRC_' + id);
    }
    var list = quickParseFns_(srcStr);
    cache.put('QUICK_MY_LIST_' + id, JSON.stringify({ v: 4, stamp: stamp, list: list }), 21600);
    cache.put('QUICK_MY_META', JSON.stringify({ id: id, stamp: stamp, checkedAt: nowTs }), 300);
  } catch (e) {
    quickMyInvalidate_(id);
  }
  return stamp;
}

function quickMySourceCached_(id, optStamp, fastMode) {
  var cache = comboCache_(), key = 'QUICK_MY_SRC_' + id;
  var raw = null;
  if (cache) { try { raw = cache.get(key); } catch (eGet) { raw = null; } }
  var readCached = function (c) {
    if (!c) return null;
    if (c.__gz && typeof Utilities !== 'undefined') {
      return Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(c.__gz), 'application/x-gzip')).getDataAsString('utf-8');
    }
    return typeof c.src === 'string' ? c.src : null;
  };
  if (fastMode && raw) {
    try {
      var cf = JSON.parse(raw);
      if (cf && cf.cachedAt && (Date.now() - cf.cachedAt < 60000) && (!optStamp || cf.stamp === optStamp)) {
        var fastSrc = readCached(cf);
        if (fastSrc !== null) return fastSrc;
      }
    } catch (eF) {}
  }
  var stamp = optStamp !== undefined ? optStamp : quickMyStamp_(id);
  if (raw && stamp) {
    try {
      var c = JSON.parse(raw);
      if (c && c.stamp === stamp) {
        var hitSrc = readCached(c);
        if (hitSrc !== null) return hitSrc;
      }
    } catch (e2) {}
  }
  var src = quickMySource_(quickMyContent_(id));
  if (stamp && cache) {
    try {
      var nowTs = Date.now();
      var payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, src: src });
      if (payload.length > 50000 && typeof Utilities !== 'undefined') {
        var gz = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(src, 'text/plain')).getBytes());
        payload = JSON.stringify({ stamp: stamp, cachedAt: nowTs, __gz: gz });
      }
      if (payload.length < 95000) cache.put(key, payload, 21600);
    } catch (e3) {}
  }
  return src;
}

function quickMyListCached_(id, optStamp) {
  var cache = comboCache_(), key = 'QUICK_MY_LIST_' + id;
  var stamp = optStamp !== undefined ? optStamp : quickMyStamp_(id);
  var raw = null;
  if (cache) { try { raw = cache.get(key); } catch (eGet) { raw = null; } }
  if (raw && stamp) {
    try {
      var c = JSON.parse(raw);
      if (c.stamp === stamp && c.v === 4) return c.list;
    } catch (e2) {}
  }
  var list = quickParseFns_(quickMySourceCached_(id, stamp));
  if (stamp && cache) { try { cache.put(key, JSON.stringify({ v: 4, stamp: stamp, list: list }), 21600); } catch (e3) {} }
  return list;
}

function quickMyUrl_(id) {
  return 'https://script.google.com/d/' + id + '/edit';
}

function quickDrive_(method, url, payload, ctype) {
  var o = { method: method, headers: { Authorization: 'Bearer ' + comboGetOAuthToken_() }, muteHttpExceptions: true };
  if (payload !== undefined) { o.payload = payload; o.contentType = ctype; }
  var r = UrlFetchApp.fetch(url, o);
  var code = r.getResponseCode();
  if (code !== 200) {
    var msg = r.getContentText().slice(0, 300);
    if (/drive\.scripts/.test(msg)) msg = 'マイマクロに書き込む許可がありません。サイドパネルを再読み込み（または拡張をもう一度開いて許可）してください';
    throw new Error(msg);
  }
  return r.getContentText();
}

function quickMyContent_(id) {
  return JSON.parse(quickDrive_('get', 'https://www.googleapis.com/drive/v3/files/' + id + '/export?mimeType=' + encodeURIComponent(QUICK_SCRIPT_JSON)));
}

function quickMySource_(content) {
  return (content.files || []).filter(function (f) { return f.type === 'server_js'; }).map(function (f) { return f.source; }).join('\n');
}

function quickInsertTop_(source, block) {
  var lines = String(source || '').split('\n'), i = 0;
  while (i < lines.length && /^\s*\/\//.test(lines[i])) i++;
  while (i < lines.length && lines[i].trim() === '') i++;
  var head = lines.slice(0, i).join('\n').replace(/\s*$/, '');
  var rest = lines.slice(i).join('\n').replace(/^\s*/, '');
  return (head ? head + '\n\n' : '') + String(block).replace(/\s*$/, '') + '\n' + (rest ? '\n' + rest : '');
}

function quickParseFns_(src) {
  var lines = String(src || '').split('\n'), out = [], words = [], desc = '', steps = [], noBackup = false;
  var inBlock = false;
  for (var i = 0; i < lines.length; i++) {
    var rawLine = lines[i];
    var ln = rawLine.trim();
    if (inBlock) {
      var endIdx = ln.indexOf('*/');
      if (endIdx < 0) continue;
      ln = ln.slice(endIdx + 2).trim();
      inBlock = false;
      if (!ln) continue;
    }
    while (/^\/\*/.test(ln)) {
      var closeIdx = ln.indexOf('*/', 2);
      if (closeIdx < 0) { inBlock = true; ln = ''; break; }
      ln = ln.slice(closeIdx + 2).trim();
    }
    if (inBlock) continue;
    if (!ln) { words = []; desc = ''; steps = []; noBackup = false; continue; }
    if (/^\/\/\s*控えなし(?:\s|$)/.test(ln)) { noBackup = true; continue; }
    var mw = ln.match(/^\/\/\s*棚\s*[:：]\s*(.+)$/);
    if (mw) { words = words.concat(mw[1].split(/[,、，]/).map(function (s) { return s.trim(); }).filter(String)); continue; }
    var ms = ln.match(/^\/\/\s*手順\s*[:：]\s*(.+)$/);
    if (ms) { steps = steps.concat(quickSplitSteps_(ms[1])); continue; }
    var top = !/^\s/.test(rawLine);
    var mf = top && (ln.match(/^(?:async\s+)?function\s+([^\s(]+)\s*\(/) ||
    ln.match(/^(?:const|let|var)\s+([^\s=]+)\s*=\s*(?:async\s+)?(?:function\s*\(|\([^)]*\)\s*=>|[\w$]+\s*=>)/));
    if (mf) {
      if (!/_$/.test(mf[1])) out.push({ name: mf[1], words: words, desc: desc, steps: steps, noBackup: noBackup });
      words = []; desc = ''; steps = []; noBackup = false;
      continue;
    }
    var mc = ln.match(/^\/\/\s*(.+)$/);
    if (mc) { if (!desc) desc = mc[1].trim(); continue; }
    words = []; desc = ''; steps = []; noBackup = false;
  }
  for (var j = 0; j < out.length; j++) {
    if (!out[j].steps || !out[j].steps.length) {
      var dops = quickExtractDirectOps_(src, out[j].name);
      if (dops && dops.length) out[j].directOps = dops;
    }
  }
  return out;
}

/**
 * マイマクロ関数本体が「静的な shelf(...) 呼び出しのみ」で構成されている場合だけ
 * 直結API用の ops 配列を抽出して返す。変数・制御文・SpreadsheetApp 等が 1 つでもあれば null。
 */
function quickExtractDirectOps_(src, name) {
  try {
    var span = quickFindFnSpan_(src, name);
    if (!span) return null;
    var fnText = String(src || '').slice(span.start, span.end);
    var openBrace = fnText.indexOf('{');
    var closeBrace = fnText.lastIndexOf('}');
    if (openBrace < 0 || closeBrace <= openBrace) return null;
    var body = fnText.slice(openBrace + 1, closeBrace);
    // 文字列リテラルを壊さずにコメントを除去し、文字列外に動的要素がないか厳格検証する
    var stripped = '';
    var nonStr = '';
    var inStr = '', inLine = false, inBlk = false;
    for (var i = 0; i < body.length; i++) {
      var c = body[i], nx = i + 1 < body.length ? body[i + 1] : '';
      if (inLine) { if (c === '\n') { inLine = false; stripped += '\n'; nonStr += '\n'; } continue; }
      if (inBlk) { if (c === '*' && nx === '/') { inBlk = false; i++; } continue; }
      if (inStr) {
        stripped += c;
        if (c === '\\' && i + 1 < body.length) { stripped += body[++i]; continue; }
        if (c === inStr) { inStr = ''; nonStr += '""'; }
        continue;
      }
      if (c === '/' && nx === '/') { inLine = true; i++; continue; }
      if (c === '/' && nx === '*') { inBlk = true; i++; continue; }
      if (c === "'" || c === '"') { inStr = c; stripped += c; continue; }
      if (c === '`') return null; // テンプレートリテラルは式展開を含み得るため対象外
      stripped += c;
      nonStr += c;
    }
    stripped = stripped.trim();
    if (!stripped || stripped.indexOf('shelf') < 0) return null;
    // 文字列外の構文チェック：オブジェクトキー（識別子:）・shelf(・true/false/null・数値・区切り記号のみ許可
    var check = nonStr
      .replace(/""/g, ' ')
      .replace(/\bshelf\s*\(/g, '(')
      .replace(/[A-Za-z_$][\w$]*\s*:/g, ':')
      .replace(/\b(?:true|false|null)\b/g, ' ')
      .replace(/-?\d+(?:\.\d+)?/g, ' ');
    if (/[^\[\]{}(),;:\s]/.test(check)) return null;
    // トップレベル文がすべて shelf(...) 呼び出しのみであることを確認
    if (!/^(?:shelf\s*\([\s\S]*\)\s*;?\s*)+$/.test(stripped)) return null;
    var ops = [];
    var collect = function (opsOrName, optArgs) {
      if (Array.isArray(opsOrName)) {
        for (var k = 0; k < opsOrName.length; k++) ops.push(opsOrName[k]);
      } else if (typeof opsOrName === 'string') {
        ops.push(Object.assign({ shelf: opsOrName }, optArgs || {}));
      } else if (opsOrName && typeof opsOrName === 'object') {
        ops.push(opsOrName);
      } else {
        throw new Error('invalid');
      }
    };
    new Function('shelf', '"use strict";\n' + stripped)(collect);
    if (!ops.length) return null;
    for (var m = 0; m < ops.length; m++) {
      if (!ops[m] || typeof ops[m] !== 'object' || Array.isArray(ops[m]) || typeof ops[m].shelf !== 'string' || !ops[m].shelf.trim()) {
        return null;
      }
    }
    return JSON.parse(JSON.stringify(ops));
  } catch (e) {
    return null;
  }
}

/** ソースコードから指定関数（直上の連続コメント含む）の [start, end] 文字位置を返す。見つからなければ null。 */
function quickFindFnSpan_(src, name) {
  src = String(src || '');
  var esc = String(name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (!esc) return null;
  var re = new RegExp('^(?:async\\s+)?function\\s+' + esc + '\\s*\\(|^(?:const|let|var)\\s+' + esc + '\\s*=\\s*(?:async\\s+)?(?:function\\s*\\(|\\([^)]*\\)\\s*=>|[\\w$]+\\s*=>)', 'm');
  var m = re.exec(src);
  if (!m) return null;
  var defStart = m.index;
  var start = defStart;
  while (start > 0) {
    var prevNl = src.lastIndexOf('\n', start - 2);
    var lineStart = prevNl < 0 ? 0 : prevNl + 1;
    var prevLine = src.slice(lineStart, start - 1).replace(/\r$/, '');
    if (/^\s*\/\//.test(prevLine)) {
      start = lineStart;
    } else {
      break;
    }
  }
  var isArrow = /=>\s*$/.test(m[0]);
  var i = defStart, n = src.length, depth = 0, opened = false;
  var inStr = '', inLineCom = false, inBlkCom = false, inRegex = false, inRegexClass = false;
  var lastSig = '';
  var lastWord = '';
  var canStartRegex = function () {
    if (!lastSig) return true;
    if ('=(,[!&|?:;{}~+-*%^<>'.indexOf(lastSig) >= 0) return true;
    return /^(?:return|throw|case|in|of|typeof|void|delete|new|else|do|yield|await)$/.test(lastWord);
  };
  if (isArrow) {
    var arrowBody = defStart + m[0].length;
    while (arrowBody < n && /\s/.test(src[arrowBody])) arrowBody++;
    if (arrowBody < n && src[arrowBody] !== '{') {
      var pDepth = 0, bDepth = 0;
      for (var k = arrowBody; k < n; k++) {
        var c2 = src[k], nx2 = k + 1 < n ? src[k + 1] : '';
        if (inLineCom) { if (c2 === '\n') { inLineCom = false; if (pDepth === 0 && bDepth === 0) return { start: start, end: k }; } continue; }
        if (inBlkCom) { if (c2 === '*' && nx2 === '/') { inBlkCom = false; k++; } continue; }
        if (inStr) { if (c2 === '\\') { k++; continue; } if (c2 === inStr) inStr = ''; continue; }
        if (c2 === '/' && nx2 === '/') { inLineCom = true; k++; continue; }
        if (c2 === '/' && nx2 === '*') { inBlkCom = true; k++; continue; }
        if (c2 === "'" || c2 === '"' || c2 === '`') { inStr = c2; continue; }
        if (c2 === '(') pDepth++;
        else if (c2 === ')') pDepth = Math.max(0, pDepth - 1);
        else if (c2 === '[') bDepth++;
        else if (c2 === ']') bDepth = Math.max(0, bDepth - 1);
        else if (pDepth === 0 && bDepth === 0 && (c2 === ';' || c2 === '\n')) {
          return { start: start, end: c2 === ';' ? k + 1 : k };
        }
      }
      return { start: start, end: n };
    }
  }
  for (; i < n; i++) {
    var ch = src[i], nx = i + 1 < n ? src[i + 1] : '';
    if (inLineCom) { if (ch === '\n') inLineCom = false; continue; }
    if (inBlkCom) { if (ch === '*' && nx === '/') { inBlkCom = false; i++; } continue; }
    if (inRegex) {
      if (ch === '\\') { i++; continue; }
      if (ch === '[') { inRegexClass = true; continue; }
      if (ch === ']') { inRegexClass = false; continue; }
      if (ch === '/' && !inRegexClass) { inRegex = false; lastSig = ')'; lastWord = ''; continue; }
      if (ch === '\n') { inRegex = false; inRegexClass = false; }
      continue;
    }
    if (inStr) {
      if (ch === '\\') { i++; continue; }
      if (ch === inStr) { inStr = ''; lastSig = ')'; lastWord = ''; }
      continue;
    }
    if (ch === '/' && nx === '/') { inLineCom = true; i++; continue; }
    if (ch === '/' && nx === '*') { inBlkCom = true; i++; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { inStr = ch; continue; }
    if (ch === '/' && canStartRegex()) { inRegex = true; inRegexClass = false; continue; }
    if (ch === '{') { depth++; opened = true; lastSig = '{'; lastWord = ''; continue; }
    if (ch === '}') {
      depth--;
      lastSig = '}'; lastWord = '';
      if (opened && depth === 0) {
        var end = i + 1;
        if (src[end] === ';') end++;
        return { start: start, end: end };
      }
      continue;
    }
    if (!/\s/.test(ch)) {
      if (/[\w$]/.test(ch)) {
        lastWord = /[\w$]/.test(lastSig) ? (lastWord + ch) : ch;
      } else {
        lastWord = '';
      }
      lastSig = ch;
    }
  }
  return null;
}

/** マイマクロ・並び順・ピン留め一覧を返す（ブラウザ連動アドオン用）。 */
function comboQuickList(req) {
  var t0 = Date.now();
  req = req || {};
  var allProps = req._allProps;
  if (!allProps) {
    try { allProps = PropertiesService.getUserProperties().getProperties() || {}; } catch (eP) { allProps = {}; }
  }
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim();
  var res = {
    ok: true,
    sheet: [],
    my: [],
    myId: '',
    myUrl: '',
    myStamp: '',
    oauthToken: req._skipToken ? '' : comboGetOAuthToken_(),
    order: quickGetOrders_(allProps, ssId),
    pins: quickGetPins_(allProps)
  };
  try {
    var meta = quickMyFind_(true, allProps, !!req.force);
    if (meta && meta.id) {
      if (req.force) {
        var cF = comboCache_();
        if (cF) {
          try {
            cF.remove('QUICK_MY_LIST_' + meta.id);
            cF.remove('QUICK_MY_SRC_' + meta.id);
          } catch (eInv) {}
        }
      }
      res.myId = meta.id;
      res.myUrl = quickMyUrl_(meta.id);
      res.myStamp = meta.stamp || '';
      res.my = quickMyListCached_(meta.id, meta.stamp || undefined);
      if (req.wantCodes && meta.stamp && meta.stamp !== String(req.clientStamp || '')) {
        try {
          var srcAll = quickMySourceCached_(meta.id, meta.stamp || undefined, true);
          if (srcAll && srcAll.length < 60000) {
            var codes = {};
            for (var j = 0; j < res.my.length; j++) {
              var fnSp = quickFindFnSpan_(srcAll, res.my[j].name);
              if (fnSp) codes[res.my[j].name] = srcAll.slice(fnSp.start, fnSp.end);
            }
            res.myCodes = codes;
          }
        } catch (eCode) {}
      }
    }
  } catch (e) {
    res.myError = String(e && e.message || e);
  }
  res.gasMs = Date.now() - t0;
  return res;
}

function quickDropBackup_(ss) {
  try {
    var old = ss.getSheetByName(QUICK_BK_NAME);
    if (old) ss.deleteSheet(old);
  } catch (e) {}
}

function comboFastUndoClearLocal_(ss, optStack, optFromProp) {
  var cache = comboCache_();
  var ssId = ss ? ss.getId() : '';
  if (cache) {
    try {
      if (optStack && optStack.length > 0 && ssId) {
        var restStr = JSON.stringify({ __stack: optStack, ssId: ssId });
        if (restStr.length > 50000 && typeof Utilities !== 'undefined') {
          var gzRest = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(restStr, 'application/json')).getBytes());
          restStr = JSON.stringify({ __gz: gzRest, ssId: ssId });
        }
        if (restStr.length <= 95000) cache.put(COMBO_PROP_FAST_UNDO, restStr, COMBO_TBL_CACHE_TTL);
        else cache.remove(COMBO_PROP_FAST_UNDO);
      } else {
        var prev = cache.get(COMBO_PROP_FAST_UNDO);
        if (prev && prev.indexOf('"sheetcopy"') >= 0 && ss) quickDropBackup_(ss);
        cache.remove(COMBO_PROP_FAST_UNDO);
      }
    } catch (eU) {}
  }
  if (optFromProp) {
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eP) {}
  }
}

function comboQuickSnapForSs_(ss, sh, what) {
  try {
    if (!ss || !sh || sh.getName() === QUICK_BK_NAME) return false;
    var ssId = ss.getId();
    quickDropBackup_(ss);
    var bk = sh.copyTo(ss);
    bk.setName(QUICK_BK_NAME);
    if (typeof bk.hideSheet === 'function') bk.hideSheet();
    var snap = {
      kind: 'sheetcopy',
      ssId: ssId,
      sheetName: sh.getName(),
      bk: QUICK_BK_NAME,
      a1: 'シート全体',
      what: String(what || 'マクロ'),
      ts: Date.now(),
      frozenR: typeof sh.getFrozenRows === 'function' ? sh.getFrozenRows() : 0,
      frozenC: typeof sh.getFrozenColumns === 'function' ? sh.getFrozenColumns() : 0
    };
    var cache = comboCache_();
    if (cache) cache.put(COMBO_PROP_FAST_UNDO, JSON.stringify(snap), COMBO_TBL_CACHE_TTL);
    return true;
  } catch (e) {
    comboFastUndoClearLocal_(ss, null, true);
    return false;
  }
}

function quickRestoreSheetCopy_(ss, snap, optStack, optFromProp) {
  var t0 = Date.now();
  var ssId = ss.getId();
  var sh = ss.getSheetByName(snap.sheetName);
  var bk = ss.getSheetByName(snap.bk || QUICK_BK_NAME);
  if (!sh) return { ok: false, error: 'シート「' + snap.sheetName + '」が見つかりません' };
  if (!bk) {
    comboFastUndoClearLocal_(ss, optStack, optFromProp);
    return { ok: false, error: '控えのシートが見つかりません（消されたか、次のマクロで入れ替わりました）' };
  }
  var maxR = typeof bk.getMaxRows === 'function' ? bk.getMaxRows() : bk.getLastRow();
  var maxC = typeof bk.getMaxColumns === 'function' ? bk.getMaxColumns() : bk.getLastColumn();
  var isHuge = (maxR * maxC > 50000);
  var nr = isHuge ? Math.min(maxR, Math.max(bk.getLastRow() + 20, sh.getLastRow() + 20, 50)) : maxR;
  var nc = isHuge ? Math.min(maxC, Math.max(bk.getLastColumn() + 5, sh.getLastColumn() + 5, 26)) : maxC;
  if (typeof sh.getMaxRows === 'function' && sh.getMaxRows() < nr && typeof sh.insertRowsAfter === 'function') sh.insertRowsAfter(sh.getMaxRows(), nr - sh.getMaxRows());
  if (typeof sh.getMaxColumns === 'function' && sh.getMaxColumns() < nc && typeof sh.insertColumnsAfter === 'function') sh.insertColumnsAfter(sh.getMaxColumns(), nc - sh.getMaxColumns());
  var clrR = isHuge && typeof sh.getMaxRows === 'function' ? Math.min(sh.getMaxRows(), Math.max(sh.getLastRow() + 20, nr)) : (typeof sh.getMaxRows === 'function' ? sh.getMaxRows() : nr);
  var clrC = isHuge && typeof sh.getMaxColumns === 'function' ? Math.min(sh.getMaxColumns(), Math.max(sh.getLastColumn() + 5, nc)) : (typeof sh.getMaxColumns === 'function' ? sh.getMaxColumns() : nc);
  var all = sh.getRange(1, 1, clrR, clrC);
  if (typeof all.breakApart === 'function') all.breakApart();
  if (typeof all.clear === 'function') all.clear();
  if (typeof all.clearDataValidations === 'function') all.clearDataValidations();
  try { sh.getBandings().forEach(function (b) { b.remove(); }); } catch (eB) {}
  try { var flt = sh.getFilter(); if (flt) flt.remove(); } catch (eF) {}
  var src = bk.getRange(1, 1, nr, nc);
  src.copyTo(sh.getRange(1, 1, nr, nc));
  if (typeof SpreadsheetApp !== 'undefined' && SpreadsheetApp.CopyPasteType && SpreadsheetApp.CopyPasteType.PASTE_COLUMN_WIDTHS) {
    src.copyTo(sh.getRange(1, 1, nr, nc), SpreadsheetApp.CopyPasteType.PASTE_COLUMN_WIDTHS, false);
  }
  if (!isHuge && typeof sh.getMaxRows === 'function' && typeof sh.deleteRows === 'function' && sh.getMaxRows() > nr) sh.deleteRows(nr + 1, sh.getMaxRows() - nr);
  if (!isHuge && typeof sh.getMaxColumns === 'function' && typeof sh.deleteColumns === 'function' && sh.getMaxColumns() > nc) sh.deleteColumns(nc + 1, sh.getMaxColumns() - nc);
  if (snap.frozenR !== undefined && typeof sh.getFrozenRows === 'function' && sh.getFrozenRows() !== snap.frozenR) sh.setFrozenRows(snap.frozenR);
  if (snap.frozenC !== undefined && typeof sh.getFrozenColumns === 'function' && sh.getFrozenColumns() !== snap.frozenC) sh.setFrozenColumns(snap.frozenC);
  ss.deleteSheet(bk);
  comboFastUndoClearLocal_(ss, optStack, optFromProp);
  comboCacheInvalidate_(ssId, sh.getName());
  var cachedUndo = comboCacheGet_(ssId, sh.getName());
  var target = {
    id: ssId,
    name: (cachedUndo && cachedUndo.ssName) || ss.getName(),
    kind: 'sheet',
    url: 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit',
    sheet: sh.getName()
  };
  return {
    ok: true,
    fast: true,
    undone: 'fast',
    what: snap.what,
    target: target,
    oauthToken: comboGetOAuthToken_(),
    text: '対象: ' + target.name + ' › ' + target.sheet + '\n戻した: シート全体（' + snap.what + ' の前）に戻しました',
    gasMs: Date.now() - t0
  };
}

function quickUndoNote_(snapped, backupOn, noBackup) {
  if (noBackup) return '（控えなし指定）';
  if (backupOn === false) return '（控えなし・取り消し不可・Ctrl+Z 推奨）';
  return snapped ? '' : '（控えを取れませんでした。取り消しは Ctrl+Z で）';
}

function quickFormatMyErr_(name, err, isCompile) {
  var msg = String(err && err.message || err);
  if (isCompile) {
    return 'マイマクロの構文エラーで実行できません: ' + msg + '（「編集」で赤い波線の箇所を確認してください）';
  }
  var lineHint = '';
  try {
    var st = String(err && err.stack || '');
    var m = st.match(/<anonymous>:(\d+)(?::\d+)?/);
    if (m) {
      var ln = parseInt(m[1], 10);
      if (ln > 2) lineHint = '（マイマクロ ' + (ln - 2) + ' 行目付近）';
    }
  } catch (e) {}
  return name + ' でエラー' + lineHint + ': ' + msg;
}

function comboQuickAfter_(ss, sh) {
  try {
    if (ss && sh) comboCacheInvalidate_(ss.getId(), sh.getName());
  } catch (e) {}
}

/** WebApp（getActive() が null の環境）向け SpreadsheetApp/Spreadsheet/Sheet Proxy を生成する。 */
function quickMakeSsProxy_(ss, sheetName, selA1) {
  var targetSh = sheetOf_(ss, sheetName, '');
  var rawSel = String(selA1 || '').trim();
  var bangIdx = rawSel.indexOf('!');
  if (bangIdx >= 0) rawSel = rawSel.slice(bangIdx + 1).trim();
  var selParts = (rawSel || 'A1').split(/\s*,\s*/).map(function (s) { return s.trim(); }).filter(Boolean);
  if (!selParts.length) selParts = ['A1'];
  var toasts = [];
  var unwrap = function (x) { return (x && x.__raw) ? x.__raw : x; };
  var resolveRange = function (shObj, a1) {
    var target = unwrap(shObj) || targetSh;
    var q = String(a1 || selParts[0] || 'A1').trim();
    try { return target.getRange(q); } catch (e) { return target.getRange(1, 1); }
  };
  var resolveRangeList = function (shObj) {
    var target = unwrap(shObj) || targetSh;
    if (typeof target.getRangeList === 'function') {
      try { return target.getRangeList(selParts); } catch (e1) {}
    }
    var ranges = selParts.map(function (p) { return resolveRange(target, p); });
    return { getRanges: function () { return ranges; } };
  };
  var wrapSheet = function (shObj) {
    if (typeof Proxy === 'undefined') return shObj;
    return new Proxy(shObj, {
      get: function (target, prop) {
        if (prop === '__raw') return target;
        if (prop === 'getActiveRange') return function () { return resolveRange(target, selParts[0]); };
        if (prop === 'getActiveCell') return function () { return resolveRange(target, selParts[0].split(':')[0] || 'A1'); };
        if (prop === 'getActiveRangeList') return function () { return resolveRangeList(target); };
        var v = target[prop];
        if (typeof v === 'function') {
          return function () {
            var args = Array.prototype.slice.call(arguments).map(unwrap);
            return v.apply(target, args);
          };
        }
        return v;
      }
    });
  };
  var shProxy = wrapSheet(targetSh);
  var makeSelObj = function () {
    return {
      getActiveRange: function () { return resolveRange(targetSh, selParts[0]); },
      getActiveRangeList: function () { return resolveRangeList(targetSh); },
      getCurrentCell: function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); },
      getActiveSheet: function () { return shProxy; }
    };
  };
  var ssProxy = typeof Proxy === 'undefined' ? ss : new Proxy(ss, {
    get: function (target, prop) {
      if (prop === '__raw') return target;
      if (prop === 'getActiveSheet') return function () { return shProxy; };
      if (prop === 'getActiveRange') return function () { return resolveRange(targetSh, selParts[0]); };
      if (prop === 'getActiveCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'getActiveRangeList') return function () { return resolveRangeList(targetSh); };
      if (prop === 'getCurrentCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'getSelection') return makeSelObj;
      if (prop === 'getDataRange') return function () { return targetSh.getDataRange(); };
      if (prop === 'getLastRow') return function () { return targetSh.getLastRow(); };
      if (prop === 'getLastColumn') return function () { return targetSh.getLastColumn(); };
      if (prop === 'getRange') {
        return function (a1OrRow) {
          if (typeof a1OrRow === 'string' && a1OrRow.indexOf('!') < 0) return targetSh.getRange(a1OrRow);
          return target.getRange.apply(target, Array.prototype.slice.call(arguments).map(unwrap));
        };
      }
      if (prop === 'getRangeList') {
        return function (a1s) {
          var arr = Array.isArray(a1s) ? a1s : [a1s];
          if (arr.every(function (s) { return String(s).indexOf('!') < 0; }) && typeof targetSh.getRangeList === 'function') {
            return targetSh.getRangeList(arr);
          }
          return target.getRangeList.apply(target, Array.prototype.slice.call(arguments).map(unwrap));
        };
      }
      if (prop === 'setActiveSheet') {
        return function (s) {
          var raw = unwrap(s);
          if (raw && typeof raw.getName === 'function') { targetSh = raw; shProxy = wrapSheet(raw); }
          try { return target.setActiveSheet(raw); } catch (e) { return raw; }
        };
      }
      if (prop === 'setActiveRange') {
        return function (rg) {
          var rawR = unwrap(rg);
          if (rawR && typeof rawR.getA1Notation === 'function') selParts = [rawR.getA1Notation()];
          try { return target.setActiveRange(rawR); } catch (e) { return rawR; }
        };
      }
      if (prop === 'setActiveRangeList') {
        return function (rgl) {
          var rawL = unwrap(rgl);
          if (rawL && typeof rawL.getRanges === 'function') {
            try {
              var a1s = rawL.getRanges().map(function (x) { return x.getA1Notation(); }).filter(Boolean);
              if (a1s.length) selParts = a1s;
            } catch (eR) {}
          }
          try { return target.setActiveRangeList(rawL); } catch (e) { return rawL; }
        };
      }
      if (prop === 'getSheetByName') {
        return function (n) {
          var s = target.getSheetByName(n);
          if (!s) return null;
          return s.getName() === targetSh.getName() ? shProxy : wrapSheet(s);
        };
      }
      if (prop === 'toast') {
        return function (msg) {
          toasts.push(String(msg || ''));
          try { return target.toast.apply(target, arguments); } catch (e) {}
        };
      }
      var v = target[prop];
      if (typeof v === 'function') {
        return function () {
          var args = Array.prototype.slice.call(arguments).map(unwrap);
          return v.apply(target, args);
        };
      }
      return v;
    }
  });
  var ssApp = (typeof SpreadsheetApp !== 'undefined') ? SpreadsheetApp : {};
  var ssAppProxy = typeof Proxy === 'undefined' ? ssApp : new Proxy(ssApp, {
    get: function (target, prop) {
      if (prop === 'getActive' || prop === 'getActiveSpreadsheet') return function () { return ssProxy; };
      if (prop === 'getActiveSheet') return function () { return shProxy; };
      if (prop === 'getActiveRange') return function () { return resolveRange(targetSh, selParts[0]); };
      if (prop === 'getActiveRangeList') return function () { return resolveRangeList(targetSh); };
      if (prop === 'getCurrentCell') return function () { return resolveRange(targetSh, selParts[0].split(':')[0] || 'A1'); };
      if (prop === 'flush') return function () { try { if (target && target.flush) target.flush(); } catch (e) {} };
      if (prop === 'getUi') {
        return function () {
          return {
            alert: function (m1, m2) { toasts.push(String(m2 || m1 || '')); },
            toast: function (m) { toasts.push(String(m || '')); },
            prompt: function () { throw new Error('ブラウザ連動のサイドパネル側では prompt ダイアログは使えません'); }
          };
        };
      }
      var v = target[prop];
      if (typeof v === 'function') {
        return function () {
          var args = Array.prototype.slice.call(arguments).map(unwrap);
          return v.apply(target, args);
        };
      }
      return v;
    }
  });
  return { spreadsheetApp: ssAppProxy, ss: ssProxy, sheet: shProxy, toasts: toasts };
}

/** マイマクロの 1 本または下書きコードを実行する（WebApp 環境でも対象シート＋選択セル Proxy で動作）。 */
function comboQuickRun(req) {
  var t0 = Date.now();
  req = req || {};
  var dryCode = typeof req.dryRunCode === 'string' ? req.dryRunCode.replace(/\r\n/g, '\n').trim() : '';
  var isDryRun = !!dryCode;
  var name = String(req.name || '');
  var backupOn = isDryRun ? true : (req.backup === undefined ? true : !!req.backup);
  if (req.src === 'sheet') {
    return { ok: false, error: 'GASコンボ（ブラウザ連動）ではシート組込マクロは対象外です' };
  }
  try {
    var src = '';
    var meta = { id: '', stamp: '' };
    var hit = null;
    if (isDryRun) {
      src = dryCode;
      var parsedDry = quickParseFns_(src);
      if (!parsedDry.length) {
        return { ok: false, dryRun: true, error: '試実行する関数定義（function 名前() { ... }、末尾 _ なし）が見つかりません', gasMs: Date.now() - t0 };
      }
      hit = parsedDry[0];
      name = hit.name;
    } else {
      var reqId = String(req.myId || '').trim();
      var reqStamp = String(req.myStamp || '').trim();
      meta = reqId ? { id: reqId, stamp: reqStamp || quickMyStamp_(reqId) } : quickMyFind_(true);
      if (!meta || !meta.id) meta = quickMyFind_(true);
      if (!meta || !meta.id) return { ok: false, error: 'マイマクロがまだありません。一覧の「＋追加」や「マイマクロを作る」を押してください' };
      var id = meta.id;
      src = quickMySourceCached_(id, meta.stamp || undefined, true);
      var listM = quickMyListCached_(id, meta.stamp || undefined);
      hit = listM.filter(function (f) { return f.name === name; })[0];
      if (!hit) hit = quickParseFns_(src).filter(function (f) { return f.name === name; })[0];
      if (!hit) return { ok: false, error: 'マイマクロに「' + name + '」が見つかりません（一覧を更新してください）' };
    }
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var sh = sheetOf_(ss, selInfo.sheet, '');
    var px = quickMakeSsProxy_(ss, sh.getName(), selInfo.selection || req.selection || '');
    var shelfFn = function (opsOrName, optArgs) {
      var normOps;
      if (Array.isArray(opsOrName)) {
        normOps = opsOrName;
      } else if (typeof opsOrName === 'string') {
        normOps = [Object.assign({ shelf: opsOrName }, optArgs || {})];
      } else if (opsOrName && typeof opsOrName === 'object') {
        normOps = [opsOrName];
      } else {
        throw new Error('shelf() の引数は棚配列・棚オブジェクト・棚名文字列のいずれかにしてください');
      }
      var curShName = (px.ss && px.ss.getActiveSheet) ? px.ss.getActiveSheet().getName() : sh.getName();
      var sRes = comboRunOps({
        ops: normOps,
        ok: true,
        backup: false,
        fastUndo: false,
        sheet: curShName,
        selection: selInfo.selection || req.selection || '',
        targetId: ss.getId(),
        _ss: ss,
        _ssName: ss.getName()
      });
      if (!sRes || !sRes.ok) {
        throw new Error((sRes && (sRes.error || sRes.text)) || '棚の実行に失敗しました');
      }
      return sRes;
    };
    var mod;
    try {
      mod = new Function('SpreadsheetApp', 'shelf', src + '\nreturn {' + JSON.stringify(name) + ': ' + name + '};')(px.spreadsheetApp, shelfFn);
    } catch (eComp) {
      return { ok: false, dryRun: isDryRun, error: quickFormatMyErr_(name, eComp, true), gasMs: Date.now() - t0 };
    }
    var noBkM = isDryRun ? false : !!hit.noBackup;
    var snapped = false;
    if (backupOn && !noBkM) {
      snapped = comboQuickSnapForSs_(ss, sh, isDryRun ? ('試実行:' + name) : name);
    } else {
      comboFastUndoClearLocal_(ss, null, true);
    }
    var r = mod[name]();
    comboQuickAfter_(ss, sh);
    var msgParts = [];
    if (r !== undefined && r !== null && r !== '' && typeof r.then !== 'function') {
      msgParts.push(String(r).slice(0, 200));
    }
    if (px.toasts.length) {
      msgParts.push(px.toasts.join(' / ').slice(0, 200));
    }
    return {
      ok: true,
      dryRun: isDryRun,
      name: name,
      snapped: snapped,
      myStamp: meta.stamp || '',
      text: (isDryRun ? ('▶ 試実行完了: ' + name) : (name + ' を実行しました')) + (msgParts.length ? '（' + msgParts.join(' / ') + '）' : '') + quickUndoNote_(snapped, backupOn, noBkM),
      gasMs: Date.now() - t0
    };
  } catch (e) {
    return { ok: false, dryRun: isDryRun, error: quickFormatMyErr_(name, e, false), gasMs: Date.now() - t0 };
  }
}

/** マイマクロを作る（あれば番地を返すだけ）。 */
function comboQuickMake(req) {
  try {
    req = req || {};
    var id = quickMyFind_(false, null, !!req.force);
    if (id) return { ok: true, myId: id, myUrl: quickMyUrl_(id), created: false, text: 'マイマクロはもうあります' };
    var guide = [
      '// GASクイック マイマクロ',
      '// ここに置いた関数は、どのシートでも GASクイック／GASコンボの一覧に並び、選んで実行できます。',
      '// 作り方: function 名前() { ... } を書く。すぐ上に「// 棚: 言い方, 言い方」と書くと、頼みの欄の言葉でも当たります。',
      '// 棚の言葉を「// 手順: 見出しを黄色に / 太字にして」と書くと、直結APIで高速にまとめて撃てます。',
      '// 今のシートは SpreadsheetApp.getActive() で取れます。名前の末尾が _ の関数は部品として一覧に出しません。',
      '// 新しいマクロは、この手引きのすぐ下（先頭）に足します。一覧でも、新しい物は一番上に出ます。',
      '',
      '// 選んでいる範囲を太字にする（もう一度押すと太字を外す）',
      '// 棚: 太字にする, 選んだ所を太字, 太字を外す',
      'function 選んだ所を太字() {',
      '  var list = SpreadsheetApp.getActive().getActiveRangeList();',
      '  var first = list.getRanges()[0];',
      "  var isBold = first && first.getFontWeight() === 'bold';",
      "  list.setFontWeight(isBold ? 'normal' : 'bold');",
      '}',
      '',
      '// 選んでいる範囲の背景色を消す',
      '// 棚: 色を消す, 選んだ所の色を消す, 背景色を消す',
      'function 選んだ所の色を消す() {',
      '  SpreadsheetApp.getActive().getActiveRangeList().setBackground(null);',
      '}',
      '',
      '// 1 行目（見出し）の背景を薄い黄色にする',
      '// 棚: 見出しを黄色に, 見出しに色を付ける',
      'function 見出しを黄色に() {',
      '  var sh = SpreadsheetApp.getActiveSheet();',
      '  var lastCol = Math.max(1, sh.getLastColumn());',
      "  sh.getRange(1, 1, 1, lastCol).setBackground('#fef08a');",
      '}',
      ''
    ].join('\n');
    var content = { files: [
      { name: 'appsscript', type: 'json', source: JSON.stringify({ timeZone: 'Asia/Tokyo', runtimeVersion: 'V8', exceptionLogging: 'STACKDRIVER' }) },
      { name: 'マイマクロ', type: 'server_js', source: guide }
    ] };
    var b = 'gasquick' + Date.now();
    var body = '--' + b + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' +
      JSON.stringify({ name: QUICK_MY_TITLE, mimeType: 'application/vnd.google-apps.script' }) +
      '\r\n--' + b + '\r\nContent-Type: ' + QUICK_SCRIPT_JSON + '\r\n\r\n' + JSON.stringify(content) + '\r\n--' + b + '--';
    var made = JSON.parse(quickDrive_('post', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart', body, 'multipart/related; boundary=' + b));
    try { PropertiesService.getUserProperties().setProperty(QUICK_MY_ID_KEY, made.id); } catch (eP) {}
    var newStamp = quickMyCachePut_(made.id, guide);
    return { ok: true, myId: made.id, myUrl: quickMyUrl_(made.id), myStamp: newStamp, created: true, text: 'マイマクロを作りました' };
  } catch (e) {
    return { ok: false, error: 'マイマクロを作れませんでした: ' + String(e && e.message || e) };
  }
}

/** 履歴や入力から「⚡ 手順つきマクロ」をマイマクロの先頭へ直接保存する。 */
function comboQuickSaveSteps(req) {
  req = req || {};
  try {
    var rawName = String(req.name || '').trim();
    var safeName = rawName.replace(/[\s　.,:;!?()\[\]{}'"`/\\+\-*=<>|&^%$#@~]+/g, '_').replace(/^_+|_+$/g, '');
    if (!safeName) return { ok: false, error: 'マクロ名を入力してください' };
    if (/^\d/.test(safeName) || QUICK_JS_RESERVED_[safeName]) safeName = '手順_' + safeName;
    if (/_$/.test(safeName)) safeName = safeName.replace(/_+$/, '') + '実行';
    var steps = Array.isArray(req.steps)
      ? req.steps.map(function (s) { return String(s || '').trim().replace(/\r?\n/g, ' '); }).filter(String)
      : quickSplitSteps_(String(req.steps || '').replace(/\r?\n/g, ' ／ '));
    if (!steps.length) return { ok: false, error: '手順が空です' };
    var dateStr = typeof Utilities !== 'undefined' ? Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd') : '登録';
    var desc = (String(req.desc || '').trim() || ('手順マクロ（' + dateStr + ' 登録）')).replace(/\r?\n/g, ' ');
    var stepLines = steps.map(function (st) {
      return '// 手順: ' + String(st).replace(/\//g, '\\/').replace(/／/g, '\\／');
    });
    var block = ['// ' + desc].concat(stepLines, [
      'function ' + safeName + '() {',
      '  // 一覧から実行すると、上の手順を高速APIでまとめて実行します',
      '}'
    ]).join('\n');
    try {
      new Function(block);
    } catch (eSyn) {
      return { ok: false, error: 'マクロ名または構文が不正です: ' + String(eSyn && eSyn.message || eSyn) };
    }
    var made = comboQuickMake({});
    if (!made.ok) return made;
    var content = quickMyContent_(made.myId);
    var all = quickMySource_(content);
    if (quickParseFns_(all).some(function (f) { return f.name === safeName; })) {
      return { ok: false, error: 'マイマクロに同じ名前「' + safeName + '」があります（別の名前にしてください）' };
    }
    var file = (content.files || []).filter(function (f) { return f.type === 'server_js'; })[0];
    if (!file) return { ok: false, error: 'マイマクロのコードファイルが見つかりません' };
    file.source = quickInsertTop_(file.source, block);
    quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + made.myId + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
    var newStamp = quickMyCachePut_(made.myId, quickMySource_(content));
    return { ok: true, name: safeName, myId: made.myId, myUrl: made.myUrl, myStamp: newStamp, text: '⚡ 手順マクロ「' + safeName + '」をマイマクロに保存しました' };
  } catch (e) {
    return { ok: false, error: '手順マクロを保存できませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロから指定関数のコードだけを抜き出して返す。 */
function comboQuickGetFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  try {
    var reqId = String(req.myId || '').trim();
    var reqStamp = String(req.myStamp || '').trim();
    var id = reqId || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var src = '';
    var stamp = reqStamp;
    try {
      src = quickMySourceCached_(id, stamp || undefined, true);
    } catch (eCache) {
      src = '';
    }
    var sp = src ? quickFindFnSpan_(src, name) : null;
    if (!sp) {
      var meta = quickMyFind_(true);
      if (meta && meta.id) {
        id = meta.id;
        stamp = meta.stamp || '';
      }
      var content = quickMyContent_(id);
      src = quickMySource_(content);
      stamp = quickMyCachePut_(id, src, stamp || undefined);
      sp = quickFindFnSpan_(src, name);
    }
    if (!sp) {
      return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
    }
    var res = {
      ok: true,
      name: name,
      code: src.slice(sp.start, sp.end),
      myId: id,
      myStamp: stamp || '',
      myUrl: quickMyUrl_(id)
    };
    if (req.includeAll && src.length < 90000) {
      var codes = {};
      var fns = quickParseFns_(src);
      for (var j = 0; j < fns.length; j++) {
        var fnSp = quickFindFnSpan_(src, fns[j].name);
        if (fnSp) codes[fns[j].name] = src.slice(fnSp.start, fnSp.end);
      }
      res.codes = codes;
    }
    return res;
  } catch (e) {
    return { ok: false, error: 'コードを読めませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロの指定関数だけを編集後のコードでピンポイント上書き保存する。 */
function comboQuickSaveFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  var code = String(req.code || '').replace(/\r\n/g, '\n').replace(/\s*$/, '');
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  if (!code) return { ok: false, error: 'コードが空です' };
  try {
    new Function(code);
  } catch (eSyn) {
    return { ok: false, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsedNew = quickParseFns_(code);
  if (!parsedNew.length) {
    return { ok: false, error: '関数定義（function 名前() { ... }）が見つかりません' };
  }
  try {
    var id = String(req.myId || '').trim() || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var content = quickMyContent_(id);
    var files = (content.files || []).filter(function (f) { return f.type === 'server_js'; });
    for (var i = 0; i < files.length; i++) {
      var sp = quickFindFnSpan_(files[i].source, name);
      if (sp) {
        var allOther = quickMySource_(content);
        var existing = {};
        quickParseFns_(allOther).forEach(function (f) { if (f.name !== name) existing[f.name] = true; });
        var dup = parsedNew.filter(function (f) { return existing[f.name]; }).map(function (f) { return f.name; });
        if (dup.length) {
          return { ok: false, error: '同じ名前「' + dup.join('・') + '」がすでにあります（別の名前にしてください）' };
        }
        files[i].source = files[i].source.slice(0, sp.start) + code + files[i].source.slice(sp.end);
        quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + id + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
        var newStamp = quickMyCachePut_(id, quickMySource_(content));
        var newName = parsedNew[0].name || name;
        return { ok: true, name: name, newName: newName, myStamp: newStamp, text: '「' + newName + '」を保存しました' };
      }
    }
    return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
  } catch (e) {
    return { ok: false, error: '保存できませんでした: ' + String(e && e.message || e) };
  }
}

/** 新しい関数をマイマクロの先頭へ追加する（未作成なら自動作成）。 */
function comboQuickAddFn(req) {
  req = req || {};
  var code = String(req.code || '').replace(/\r\n/g, '\n').replace(/^\s*\n+/, '').replace(/\s*$/, '');
  if (!code) return { ok: false, error: 'コードが空です' };
  try {
    new Function(code);
  } catch (eSyn) {
    return { ok: false, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsed = quickParseFns_(code);
  if (!parsed.length) {
    return { ok: false, error: '関数定義（function 名前() { ... }）が見つかりません' };
  }
  try {
    var made = comboQuickMake({});
    if (!made.ok) return made;
    var content = quickMyContent_(made.myId);
    var all = quickMySource_(content);
    var existing = {};
    quickParseFns_(all).forEach(function (f) { existing[f.name] = true; });
    var dup = parsed.filter(function (f) { return existing[f.name]; }).map(function (f) { return f.name; });
    if (dup.length) {
      return { ok: false, error: '同じ名前「' + dup.join('・') + '」がすでにあります（編集から直すか別の名前にしてください）' };
    }
    var file = (content.files || []).filter(function (f) { return f.type === 'server_js'; })[0];
    if (!file) return { ok: false, error: 'マイマクロのコードファイルが見つかりません' };
    file.source = quickInsertTop_(file.source, code);
    quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + made.myId + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
    var newStamp = quickMyCachePut_(made.myId, quickMySource_(content));
    var names = parsed.map(function (f) { return f.name; });
    return { ok: true, names: names, myId: made.myId, myUrl: made.myUrl, myStamp: newStamp, text: '「' + names.join('・') + '」をマイマクロに追加しました' };
  } catch (e) {
    return { ok: false, error: '追加できませんでした: ' + String(e && e.message || e) };
  }
}

/** マイマクロから指定関数を削除する。 */
function comboQuickDeleteFn(req) {
  req = req || {};
  var name = String(req.name || '').trim();
  if (!name) return { ok: false, error: '関数名が指定されていません' };
  try {
    var id = String(req.myId || '').trim() || quickMyFind_();
    if (!id) return { ok: false, error: 'マイマクロが見つかりません' };
    var content = quickMyContent_(id);
    var files = (content.files || []).filter(function (f) { return f.type === 'server_js'; });
    for (var i = 0; i < files.length; i++) {
      var sp = quickFindFnSpan_(files[i].source, name);
      if (sp) {
        var before = files[i].source.slice(0, sp.start).replace(/\n+$/, '');
        var after = files[i].source.slice(sp.end).replace(/^\n+/, '');
        files[i].source = (before && after) ? (before + '\n\n' + after) : (before || after) + '\n';
        quickDrive_('patch', 'https://www.googleapis.com/upload/drive/v3/files/' + id + '?uploadType=media', JSON.stringify(content), QUICK_SCRIPT_JSON);
        var newStamp = quickMyCachePut_(id, quickMySource_(content));
        return { ok: true, name: name, myStamp: newStamp, text: '「' + name + '」をマイマクロから削除しました' };
      }
    }
    return { ok: false, error: 'マイマクロ内に「' + name + '」が見つかりませんでした' };
  } catch (e) {
    return { ok: false, error: '削除できませんでした: ' + String(e && e.message || e) };
  }
}

/** コードフェンス（```js / ```gs 等）を外して生コードを返す。 */
function quickStripCodeFence_(txt) {
  var s = String(txt || '').trim();
  var m = s.match(/^```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/i);
  if (m) return m[1].trim();
  var mInline = s.match(/```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```/i);
  if (mInline) return mInline[1].trim();
  return s;
}

/** マイマクロ生成・修正用のシステム／ユーザープロンプトを組み立てる。 */
function comboBuildAiMyMacroPrompts_(mode, prompt, ssName, sheetName, selection, table, sheets, targetName, existingCode, existingNames, history, allowChat) {
  var isEdit = mode === 'edit';
  var canChat = !!allowChat;
  var sys = [
    'あなたは Google スプレッドシート用の Google Apps Script（GAS）マイマクロ作成・修正アシスタントです。',
    'ユーザーが自然言語で伝えた要望を、GASコンボ（WebApp 経由でも動作する Proxy 環境）でそのまま実行できる関数 1 個として出力・提案してください。',
    '必ず有効な JSON オブジェクト 1 個だけを返してください（JSON 以外の説明文や挨拶は書かないこと）。',
    canChat
      ? '・相談・質問・改修案の提案（「どんな編集ができますか？」「このコードの意味は？」「案を出して」等、まだコード書き換えの確定指示ではない場合）: {"action":"reply","message":"簡潔に（箇条書き 3〜5 個・合計 200 文字以内を目安、番号付きで選びやすく）"}'
      : '・要望が極めて曖昧で作成不能な場合のみ: {"action":"reply","message":"確認したい点"}',
    '・コードの作成・修正の指示または合意（「作って」「〜に直して」「じゃあ1番でお願い」「それでお願い」等）: {"action":"mymacro","code":"// 説明\\n// 棚: 呼び方1, 呼び方2\\nfunction 分かりやすい日本語名() {\\n  ...\\n}","note":"何を作った・どう直したかの1行要約"}',
    '必須ルール:',
    '1. インデントなしのトップレベル function 名前() { ... } を 1 つ定義し、引数は取らないこと（補助関数は末尾に _ を付け可）。メイン関数名の末尾に _ は付けないこと。',
    '2. 関数の直上の行に「// 説明」と「// 棚: 言い方1, 言い方2」のコメントを書くこと。',
    '3. SpreadsheetApp.openById() 等で固定IDを書かず、必ず SpreadsheetApp.getActive() / SpreadsheetApp.getActiveSheet() / SpreadsheetApp.getActiveRange() / SpreadsheetApp.getActiveRangeList() を使うこと。',
    '4. 1セルずつの getValue/setValue ループは避け、getValues()/setValues() や getBackgrounds()/setBackgrounds() で2次元配列一括処理すること。',
    '5. ユーザーへの結果通知には Browser.msgBox や ui.prompt は使わず、return "完了メッセージ"; を使うこと。',
    '6. 既存の棚（ws_shelves）でできる処理（表整理・書式・列幅・集計・フィルタ・罫線・並べ替え等）は自前で長く実装せず、shelf([{shelf:"棚名", ...}, ...]) または shelf("棚名", {...}) を呼んで複数の棚を束ねる「まとめ棚」として組み、棚に無い固有処理だけ SpreadsheetApp で補うこと。'
  ].join('\n');

  var lines = [
    isEdit ? '【依頼種別】既存マイマクロの相談・修正' : '【依頼種別】新規マイマクロの相談・作成',
    '【現在の対象状態】',
    'ブック: ' + (ssName || '(不明)') + ' / シート: ' + (sheetName || '(先頭シート)')
  ];
  if (Array.isArray(sheets) && sheets.length) lines.push('全シート: ' + sheets.join('、'));
  if (selection) lines.push('選択範囲: ' + selection);
  if (table) {
    lines.push('表構造: 見出し ' + (table.header_row || 1) + '行目・' + (table.first_col || 'A') + '〜' + (table.last_col || '?') + '列・明細 ' + (table.data || '') + '行' + (table.total_row ? '・合計行 ' + table.total_row : ''));
    if (Array.isArray(table.columns) && table.columns.length) {
      lines.push('列: ' + table.columns.map(function (c) { return (c.col || '') + '=' + (c.name || '') + (c.number ? '(数値)' : ''); }).join('、'));
    }
  }
  if (isEdit && targetName) {
    lines.push('\n【修正対象の既存関数名】\n' + targetName);
    if (existingCode) lines.push('【現在のコード（これを要望どおりに書き換えること）】\n' + existingCode);
  } else {
    if (Array.isArray(existingNames) && existingNames.length) {
      lines.push('【既存のマイマクロ名（重複禁止）】\n' + existingNames.slice(0, 60).join('、'));
    }
    if (existingCode) {
      lines.push('\n【現在表示中の下書きコード（これを要望どおりに修正すること）】\n' + existingCode);
    }
  }
  if (Array.isArray(history) && history.length) {
    lines.push('\n【これまでの会話】');
    history.slice(-10).forEach(function (h) {
      if (!h || !h.text) return;
      lines.push((h.role === 'ai' ? 'AI: ' : 'ユーザー: ') + String(h.text));
    });
  }
  var shelfSummary = comboBuildCompactShelfSummary_(String(prompt || ''), 12);
  if (shelfSummary) {
    lines.push('\n【shelf() から呼び出せる既存の棚カタログ（まとめ棚用）】\n' + shelfSummary);
  }
  lines.push('\n【ユーザーの指示】\n' + String(prompt || ''));
  lines.push(
    canChat
      ? '\n質問・相談・改修案の提案なら {"action":"reply","message":"..."}、コード作成・修正の依頼や合意なら {"action":"mymacro","code":"...","note":"変更内容の1行説明"} の JSON 1個だけを返してください。'
      : '\n必ず {"action":"mymacro","code":"...","note":"..."} の JSON 1個だけを返してください。'
  );
  return { system: sys, user: lines.join('\n') };
}

/** AI 応答テキストからマイマクロのコードとメモ（または reply）を取り出す。 */
function comboExtractMyMacroCode_(rawText) {
  var raw = String(rawText || '').trim();
  try {
    var parsed = JSON.parse(comboStripJsonFence_(raw));
    if (parsed && typeof parsed === 'object') {
      if (parsed.code) {
        return { action: 'mymacro', code: quickStripCodeFence_(parsed.code), note: String(parsed.note || '').trim() };
      }
      if (parsed.action === 'reply' && parsed.message) {
        var msgStr = String(parsed.message).trim();
        var fullFenceMatch = msgStr.match(/^```(?:javascript|js|gs)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/i);
        if (fullFenceMatch && /(?:async\s+)?function\s+/.test(fullFenceMatch[1])) {
          return { action: 'mymacro', code: fullFenceMatch[1].trim(), note: '' };
        }
        return { action: 'reply', message: msgStr };
      }
    }
  } catch (eJson) {}
  var stripped = quickStripCodeFence_(raw);
  if (/(?:^|\n)\s*(?:async\s+)?function\s+[^\s(]+\s*\(/.test(stripped) ||
      /(?:^|\n)\s*(?:const|let|var)\s+[^\s=]+\s*=\s*(?:async\s+)?(?:function\s*\(|\([^)]*\)\s*=>)/.test(stripped)) {
    return { action: 'mymacro', code: stripped, note: '' };
  }
  return { action: 'reply', message: raw || 'AI の返答が空でした' };
}

/** Gemini API / Claude API を直接呼んでマイマクロコードを生成・修正する。 */
function comboCallAiMyMacro_(cfg, prompts) {
  var apiKey = comboResolveApiKey_(cfg);
  if (!apiKey) throw new Error('APIキーが設定されていません（「設定」タブでキーを登録してください）');
  var rawText = '';

  if (cfg.aiMode === 'api_gemini') {
    var gModel = comboResolveLatestApiModel_('api_gemini', cfg.aiModel, apiKey);
    var gUrl = 'https://generativelanguage.googleapis.com/v1beta/models/' + encodeURIComponent(gModel) + ':generateContent?key=' + encodeURIComponent(apiKey);
    var gResp = UrlFetchApp.fetch(gUrl, {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      payload: JSON.stringify({
        systemInstruction: { parts: [{ text: prompts.system }] },
        contents: [{ role: 'user', parts: [{ text: prompts.user }] }],
        generationConfig: { temperature: 0.2, responseMimeType: 'application/json' }
      })
    });
    var gCode = gResp.getResponseCode();
    var gBody = gResp.getContentText();
    if (gCode < 200 || gCode >= 300) {
      throw new Error('Gemini API エラー (' + gCode + '): ' + gBody.slice(0, 200));
    }
    var gJson = JSON.parse(gBody);
    rawText = (((((gJson.candidates || [])[0] || {}).content || {}).parts || [])[0] || {}).text || '';
  } else if (cfg.aiMode === 'api_claude') {
    var cModel = comboResolveLatestApiModel_('api_claude', cfg.aiModel, apiKey);
    var cResp = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      payload: JSON.stringify({
        model: cModel,
        max_tokens: 2048,
        system: prompts.system,
        messages: [{ role: 'user', content: prompts.user }]
      })
    });
    var cCode = cResp.getResponseCode();
    var cBody = cResp.getContentText();
    if (cCode < 200 || cCode >= 300) {
      throw new Error('Claude API エラー (' + cCode + '): ' + cBody.slice(0, 200));
    }
    var cJson = JSON.parse(cBody);
    rawText = (((cJson.content || [])[0] || {}).text) || '';
  } else {
    throw new Error('未対応の AI モード: ' + cfg.aiMode);
  }
  return comboExtractMyMacroCode_(rawText);
}

/** AI が返したマイマクロコードの構文・関数定義・重複を検証する。 */
function comboValidateAiMyMacroCode_(mode, code, existingNames) {
  var cleanCode = quickStripCodeFence_(code).replace(/\r\n/g, '\n').replace(/\s*$/, '');
  if (!cleanCode) {
    return { ok: false, retryable: true, error: 'AI が空のコードを返しました' };
  }
  try {
    new Function(cleanCode);
  } catch (eSyn) {
    return { ok: false, retryable: true, code: cleanCode, error: '構文エラーがあります: ' + String(eSyn && eSyn.message || eSyn) };
  }
  var parsedFns = quickParseFns_(cleanCode);
  if (!parsedFns.length) {
    return { ok: false, retryable: true, code: cleanCode, error: 'インデントなしの関数定義（function 名前() { ... }、末尾 _ なし）が見つかりません' };
  }
  if (mode !== 'edit' && Array.isArray(existingNames) && existingNames.length) {
    var nameSet = {};
    existingNames.forEach(function (n) { nameSet[String(n || '')] = true; });
    for (var i = 0; i < parsedFns.length; i++) {
      if (nameSet[parsedFns[i].name]) {
        return {
          ok: false,
          retryable: true,
          code: cleanCode,
          error: '同じ名前のマイマクロ「' + parsedFns[i].name + '」が既にあります。別の関数名にしてください'
        };
      }
    }
  }
  return {
    ok: true,
    code: cleanCode,
    name: parsedFns[0].name,
    names: parsedFns.map(function (f) { return f.name; })
  };
}

/** AI が返したマイマクロコードを検証し、マイマクロへ自動保存する。 */
function comboSaveAiMyMacroResult_(mode, targetName, code, myId) {
  var valRes = comboValidateAiMyMacroCode_(mode, code, []);
  if (!valRes.ok) {
    return valRes;
  }
  var cleanCode = valRes.code;
  var saveRes = (mode === 'edit' && targetName)
    ? comboQuickSaveFn({ name: targetName, code: cleanCode, myId: myId || '' })
    : comboQuickAddFn({ code: cleanCode });
  if (saveRes && saveRes.ok) {
    saveRes.code = cleanCode;
    return saveRes;
  }
  var errMsg = String((saveRes && saveRes.error) || 'マイマクロを保存できませんでした');
  if (/(?:drive\.scripts|insufficient|permission|(?:許可|権限)がありません|403)/i.test(errMsg)) {
    return { ok: false, needsClientSave: true, code: cleanCode, error: errMsg };
  }
  var out = { ok: false, code: cleanCode, error: errMsg };
  if (/同じ名前|構文エラー|関数定義/.test(errMsg)) out.retryable = true;
  return out;
}

/** AI へ自然文を投げてマイマクロを作成・修正し、確認なしで自動保存する（postbox / Gemini / Claude 全対応）。 */
function comboQuickAiSave(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var mode = req.mode === 'edit' ? 'edit' : 'add';
    var prompt = String(req.prompt || '').trim();
    if (!prompt) {
      return { ok: false, error: 'AI に作ってほしい作業・直したい内容を入力してください', gasMs: Date.now() - t0 };
    }
    var targetName = String(req.name || '').trim();
    if (mode === 'edit' && !targetName) {
      return { ok: false, error: '修正対象のマイマクロ名が指定されていません', gasMs: Date.now() - t0 };
    }

    var ss = comboOpenSs_(req);
    var ssId = ss.getId();
    var ssName = ss.getName();
    var selInfo = comboGetSelectionInfo_(ss, req, true);
    var curSheet = selInfo.sheet || '';
    var sheets = (Array.isArray(req.sheets) && req.sheets.length)
      ? req.sheets
      : ss.getSheets().map(function (s) { return s.getName(); });
    var table = req.table || null;
    if (!table && curSheet) {
      try {
        var cachedTbl = comboCacheGet_(ssId, curSheet);
        if (cachedTbl && cachedTbl.table) table = cachedTbl.table;
        else {
          var tbObj = findTable_(sheetOf_(ss, curSheet, ''));
          if (tbObj) table = tableOut_(tbObj);
        }
      } catch (eTbl) {}
    }

    var effMyId = String(req.myId || '').trim();
    var existingNames = [];
    try {
      if (!effMyId) effMyId = quickMyFind_(false) || '';
      if (effMyId) {
        existingNames = quickMyListCached_(effMyId, req.myStamp ? String(req.myStamp) : undefined).map(function (f) { return f.name; });
      }
    } catch (eList) {}

    var existingCode = String(req.code || '').trim();
    if (mode === 'edit' && !existingCode && effMyId) {
      var got = comboQuickGetFn({ name: targetName, myId: effMyId, myStamp: req.myStamp || '' });
      if (got && got.ok && got.code) existingCode = String(got.code);
    }

    var cfg = comboGetRawConfig_();
    if (req.forceAiMode === 'api_gemini' || req.forceAiMode === 'api_claude') {
      cfg = Object.assign({}, cfg, { aiMode: req.forceAiMode });
    }
    var effMode = cfg.aiMode || 'postbox';
    var previewOnly = !!req.previewOnly;
    var history = Array.isArray(req.history)
      ? req.history.slice(-10).map(function (h) {
          return {
            role: (h && h.role === 'ai') ? 'ai' : 'user',
            text: String((h && h.text) || '').trim().slice(0, 600)
          };
        }).filter(function (h) { return !!h.text; })
      : [];

    if (effMode === 'postbox') {
      if (!comboPostboxListening_()) {
        return { ok: false, error: COMBO_PB_NOT_LISTENING_MSG, text: COMBO_PB_NOT_LISTENING_MSG, gasMs: Date.now() - t0 };
      }
      var reqId = comboPostboxEnqueue_({
        kind: 'mymacro',
        mode: mode,
        previewOnly: previewOnly,
        targetName: targetName,
        existingCode: existingCode,
        existingNames: existingNames,
        history: history,
        ask: prompt,
        ssId: ssId,
        ssName: ssName,
        sheet: curSheet,
        selection: selInfo.selection || req.selection || '',
        table: table,
        sheets: sheets,
        aiModel: cfg.aiModel || 'sonnet',
        myId: effMyId
      });
      return {
        ok: true,
        pendingPostbox: true,
        previewOnly: previewOnly,
        reqId: reqId,
        kind: 'mymacro',
        mode: mode,
        name: targetName,
        text: previewOnly
          ? ('✨ AI（郵便受け）にマイマクロの' + (mode === 'edit' ? '修正案・相談' : 'コード作成') + 'を依頼しました…')
          : ('✨ AI（郵便受け）にマイマクロの' + (mode === 'edit' ? '修正' : '作成') + 'を依頼しました…'),
        gasMs: Date.now() - t0
      };
    }

    var prompts = comboBuildAiMyMacroPrompts_(mode, prompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, previewOnly);
    var aiRes = comboCallAiMyMacro_(cfg, prompts);
    if (aiRes.action === 'reply') {
      if (previewOnly) {
        var repMsg = String(aiRes.message || '').trim() || 'ご希望の編集内容を教えてください。';
        return {
          ok: true,
          action: 'reply',
          previewOnly: true,
          saved: false,
          mode: mode,
          name: targetName,
          message: repMsg,
          text: repMsg,
          gasMs: Date.now() - t0
        };
      }
      return { ok: false, error: aiRes.message || 'コードを生成できませんでした', gasMs: Date.now() - t0 };
    }
    if (previewOnly) {
      var valRes = comboValidateAiMyMacroCode_(mode, aiRes.code, existingNames);
      if (!valRes.ok && valRes.retryable) {
        var pvRetryPrompt = prompt + '\n\n【前回の出力は次のエラーで検証できませんでした。必ず修正して出し直してください】\n' +
          valRes.error + '\n前回の生成コード:\n' + String(aiRes.code || '').slice(0, 1200);
        var pvRetryPrompts = comboBuildAiMyMacroPrompts_(mode, pvRetryPrompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, false);
        aiRes = comboCallAiMyMacro_(cfg, pvRetryPrompts);
        if (aiRes.action === 'reply') {
          return { ok: false, error: aiRes.message || '再試行でもコードを生成できませんでした', gasMs: Date.now() - t0 };
        }
        valRes = comboValidateAiMyMacroCode_(mode, aiRes.code, existingNames);
      }
      if (!valRes.ok) {
        return { ok: false, code: valRes.code || aiRes.code || '', error: valRes.error || 'コードを検証できませんでした', gasMs: Date.now() - t0 };
      }
      var pvName = valRes.name || targetName || 'マイマクロ';
      var pvNote = String(aiRes.note || '').trim();
      return {
        ok: true,
        action: 'mymacro',
        previewOnly: true,
        saved: false,
        mode: mode,
        name: pvName,
        newName: pvName,
        code: valRes.code,
        prevCode: existingCode,
        note: pvNote,
        text: '✨ コード案を作成しました（' + pvName + '）。内容を確認して「決定して保存」を押してください' + (pvNote ? '（' + pvNote + '）' : ''),
        gasMs: Date.now() - t0
      };
    }
    var saveRes = comboSaveAiMyMacroResult_(mode, targetName, aiRes.code, effMyId);
    if (!saveRes.ok && saveRes.retryable) {
      var retryPrompt = prompt + '\n\n【前回の出力は次のエラーで保存できませんでした。必ず修正して出し直してください】\n' +
        saveRes.error + '\n前回の生成コード:\n' + String(aiRes.code || '').slice(0, 1200);
      var retryPrompts = comboBuildAiMyMacroPrompts_(mode, retryPrompt, ssName, curSheet, selInfo.selection || req.selection || '', table, sheets, targetName, existingCode, existingNames, history, false);
      aiRes = comboCallAiMyMacro_(cfg, retryPrompts);
      if (aiRes.action === 'reply') {
        return { ok: false, error: aiRes.message || '再試行でもコードを生成できませんでした', gasMs: Date.now() - t0 };
      }
      saveRes = comboSaveAiMyMacroResult_(mode, targetName, aiRes.code, effMyId);
    }
    if (!saveRes.ok) {
      return { ok: false, code: saveRes.code || aiRes.code || '', error: saveRes.error || '保存できませんでした', gasMs: Date.now() - t0 };
    }
    var savedName = saveRes.newName || saveRes.name || (saveRes.names && saveRes.names[0]) || targetName || 'マイマクロ';
    var note = String(aiRes.note || '').trim();
    return {
      ok: true,
      mode: mode,
      name: savedName,
      newName: savedName,
      myId: saveRes.myId || effMyId,
      myUrl: saveRes.myUrl || '',
      myStamp: saveRes.myStamp || '',
      prevCode: existingCode,
      note: note,
      text: '✨ AI でマイマクロ「' + savedName + '」を' + (mode === 'edit' ? '修正' : '作成') + 'して自動保存しました' + (note ? '（' + note + '）' : ''),
      gasMs: Date.now() - t0
    };
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

/** 万能の窓口：許可された combo* 関数だけを安全に呼び出す。 */
function comboCall(name, req) {
  var fnName = String(name || '').trim();
  if (!/^combo[A-Z]\w*$/.test(fnName) || fnName === 'comboCall') {
    return { ok: false, error: '呼び出せない関数です: ' + fnName };
  }
  var f = globalThis[fnName];
  if (typeof f !== 'function') {
    return { ok: false, error: '大元に関数が見つかりません: ' + fnName };
  }
  return f(req);
}

// ---------------------------------------------------------------- Engine WebApp (doPost) 用 EXTRA_ACTIONS 登録

if (typeof EXTRA_ACTIONS !== 'undefined') {
  EXTRA_ACTIONS.combo_ping = comboPing;
  EXTRA_ACTIONS.combo_init = comboInit;
  EXTRA_ACTIONS.combo_look = comboLook;
  EXTRA_ACTIONS.combo_find = comboFind;
  EXTRA_ACTIONS.combo_ask = comboRunAsk;
  EXTRA_ACTIONS.combo_ops = comboRunOps;
  EXTRA_ACTIONS.combo_undo = comboUndo;
  EXTRA_ACTIONS.combo_poll = comboPollSelection;
  EXTRA_ACTIONS.combo_call = comboCall;
  EXTRA_ACTIONS.combo_quick_list = comboQuickList;
  EXTRA_ACTIONS.combo_quick_run = comboQuickRun;
  EXTRA_ACTIONS.combo_quick_make = comboQuickMake;
  EXTRA_ACTIONS.combo_quick_get_fn = comboQuickGetFn;
  EXTRA_ACTIONS.combo_quick_save_fn = comboQuickSaveFn;
  EXTRA_ACTIONS.combo_quick_add_fn = comboQuickAddFn;
  EXTRA_ACTIONS.combo_quick_delete_fn = comboQuickDeleteFn;
  EXTRA_ACTIONS.combo_quick_save_order = comboQuickSaveOrder;
  EXTRA_ACTIONS.combo_quick_save_pins = comboQuickSavePins;
  EXTRA_ACTIONS.combo_quick_save_steps = comboQuickSaveSteps;
  EXTRA_ACTIONS.combo_quick_ai_save = comboQuickAiSave;
  EXTRA_ACTIONS.combo_set_target = function (req) {
    return comboSetTestTarget((req && (req.targetId || req.ssId)) || '');
  };
}
