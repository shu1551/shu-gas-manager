// 汎用の手 api: 棚に無い頼みの受け皿。Sheets API の batchUpdate の requests を、ws_do の中（控え・失敗時の戻し・台帳・ws_undo）で撃つ。
// 使い捨ての GAS コードは流さない。型の表は道具（gas_ws_api.py）が作る ApiTypes（API_TYPES）に 1 か所だけ。表に無い型は断る・消す型は ok が要る。
// 書きやすくする変換（撃つ前）: sheetId がシート名ならシート ID に／range・source・destination・ranges[]・anchorCell が A1 表記なら GridRange に／色が #RRGGBB・色の名前なら Color に。

// 棚: api
// 題: 棚に無い設定を API で撃つ
// 分類: 範囲
// 語: batchUpdate|棚に無い|棚にない|APIで|Sheets API|APIを直接|API を直接
// 違い: 棚で足りる頼みは棚を使う。棚に無い設定だけ api。requests は Sheets API の batchUpdate の形（表にある型だけ。消す型は ok が要る）
// 引数: requests*=配列, why=文字
// 例: 「棚に無いけど、1 行目のセルを青い背景にして」 → {"shelf":"api","requests":[{"repeatCell":{"range":"A1:C1","cell":{"userEnteredFormat":{"backgroundColor":"#4285F4"}},"fields":"userEnteredFormat.backgroundColor"}}],"why":"1 行目を青く"}
// 危ない: 消す
// 触る: 隠し グループ 保護 名前 タブ色 グラフ フィルタ
// 控え: 今
SHELF['api'] = function (ctx, op) {
  need_(op, ['requests']);
  var reqs = op.requests, ss = ctx.ss;
  if (!Array.isArray(reqs) || !reqs.length) throw new ArgError('棚「api」の requests は batchUpdate の requests の配列です');
  var info = apiScan_(reqs);
  if (info.bad.length) throw new ArgError('棚「api」: ' + info.bad.slice(0, 3).join(' ／ '));
  if (info.danger.length) guardDelete_(ctx, 'api の消す型 ' + info.danger.join('・') + ' を撃ちます（' + info.danger.length + ' 件）', true, info.danger.length + ' 件');   // api の消す型は広い削除
  var def = apiDefaultSheet_(ctx, op);
  var conv = reqs.map(function (r) { return apiWalk_(ss, r, def.getSheetId(), ''); });
  var before = ss.getSheets().map(function (s) { return s.getName(); });
  ctx.curSheet = def.getName();
  Sheets.Spreadsheets.batchUpdate({ requests: conv }, ss.getId());
  ss.getSheets().forEach(function (s) { if (before.indexOf(s.getName()) < 0) ctx.createdSheets.push(s.getName()); });   // 増えたシートは、失敗・undo で消す
  chg_(ctx, null, 'api', info.types.join('・') + ' を撃った（' + reqs.length + ' 件）' + (op.why ? '：' + op.why : ''));
};

// ---- 型の表（API_TYPES）に照らす
function apiDig_(obj, path) {
  var cur = obj, ks = path.split('.');
  for (var i = 0; i < ks.length; i++) { if (!cur || typeof cur !== 'object' || !(ks[i] in cur)) return undefined; cur = cur[ks[i]]; }
  return cur;
}
function apiScan_(reqs) {
  var bad = [], danger = [], types = [];
  reqs.forEach(function (r, i) {
    var ks = r && typeof r === 'object' ? Object.keys(r) : [];
    if (ks.length !== 1) { bad.push((i + 1) + ' 番目の request は {"型の名前": {…}} の形です'); return; }
    var t = ks[0], spec = API_TYPES[t];
    if (!spec) { bad.push((i + 1) + ' 番目の型「' + t + '」は表にありません（許す型: ' + Object.keys(API_TYPES).sort().join('・') + '）'); return; }
    if (types.indexOf(t) < 0) types.push(t);
    if (spec.danger) danger.push(t);
    var fields = String((r[t] || {}).fields || '');
    (spec.deny || []).forEach(function (d) {
      var ok = true; Object.keys(d.when || {}).forEach(function (k) { if (apiDig_(r[t], k) !== d.when[k]) ok = false; });
      if (ok && d.fields.some(function (f) { return fields.indexOf(f) >= 0; })) bad.push((i + 1) + ' 番目の「' + t + '」の fields「' + fields + '」は ws_undo で戻らない物を含むので断ります');
    });
  });
  return { bad: bad, danger: danger, types: types };
}

// ---- 変換（シート名→ID・A1→GridRange・色→Color）
function apiDefaultSheet_(ctx, op) {
  var nm = op.sheet || ctx.sheetName;
  return nm ? sheetOf_(ctx.ss, nm, '') : ctx.ss.getSheets()[0];
}
function apiSheetId_(ss, v) {
  if (typeof v === 'number') return v;
  var s = ss.getSheetByName(String(v));
  if (!s) throw new ArgError('シート「' + v + '」がありません');
  return s.getSheetId();
}
function apiGrid_(ss, str, defId) {
  var m = /^(?:'((?:[^']|'')+)'|([^!']+))!(.+)$/.exec(str), sid = defId, a1 = str;
  if (m) { sid = apiSheetId_(ss, m[1] ? m[1].replace(/''/g, "'") : m[2]); a1 = m[3]; }
  var p = /^\$?([A-Za-z]*)\$?(\d*)(?::\$?([A-Za-z]*)\$?(\d*))?$/.exec(a1);
  if (!p || (!p[1] && !p[2])) throw new ArgError('範囲「' + str + '」が読めません');
  var g = { sheetId: sid }, c1 = p[1], r1 = p[2], c2 = p[3], r2 = p[4], single = c2 === undefined && r2 === undefined;
  if (c1) g.startColumnIndex = colNum_(c1.toUpperCase()) - 1;
  if (r1) g.startRowIndex = parseInt(r1, 10) - 1;
  if (single) {
    if (c1) g.endColumnIndex = g.startColumnIndex + 1;
    if (r1) g.endRowIndex = g.startRowIndex + 1;
  } else {
    var ec = c2 || c1, er = r2 || r1;
    if (ec) g.endColumnIndex = colNum_(ec.toUpperCase());
    if (er) g.endRowIndex = parseInt(er, 10);
  }
  return g;
}
function apiColor_(s) {
  var hex = rgb_(s);
  if (!hex) return {};
  var n = parseInt(String(hex).replace('#', ''), 16);
  return { red: ((n >> 16) & 255) / 255, green: ((n >> 8) & 255) / 255, blue: (n & 255) / 255 };
}
var API_GRID_KEYS = { range: 1, source: 1, destination: 1 };
function apiWalk_(ss, node, defId, key) {
  if (Array.isArray(node)) {
    if (key === 'ranges' && node.length && typeof node[0] === 'string') return node.map(function (x) { return apiGrid_(ss, x, defId); });
    return node.map(function (x) { return apiWalk_(ss, x, defId, key); });
  }
  if (node && typeof node === 'object') {
    var o = {};
    Object.keys(node).forEach(function (k) {
      var v = node[k];
      if (k === 'sheetId' && typeof v === 'string') o[k] = apiSheetId_(ss, v);
      else if (API_GRID_KEYS[k] && typeof v === 'string') o[k] = apiGrid_(ss, v, defId);
      else if (k === 'anchorCell' && typeof v === 'string') { var g = apiGrid_(ss, v, defId); o[k] = { sheetId: g.sheetId, rowIndex: g.startRowIndex || 0, columnIndex: g.startColumnIndex || 0 }; }
      else if ((k === 'color' || /Color$/.test(k)) && typeof v === 'string') o[k] = apiColor_(v);
      else o[k] = apiWalk_(ss, v, defId, k);
    });
    return o;
  }
  return node;
}

// ---- 控えるシート・触る物（この呼びの requests から決める。決められなければ全部を控える）
function apiSheetNames_(ctx, op) {
  var ss = ctx.ss, names = [], all = false, found = false;
  var add = function (n) { if (names.indexOf(n) < 0) names.push(n); };
  var scan = function (node, key) {
    if (Array.isArray(node)) { node.forEach(function (x) { scan(x, key); }); return; }
    if (node && typeof node === 'object') {
      if (node.allSheets === true) all = true;
      Object.keys(node).forEach(function (k) {
        var v = node[k];
        if (k === 'sheetId') {
          found = true;
          if (typeof v === 'string') add(v);
          else if (typeof v === 'number') { var s = byId_(ss, v); if (s) add(s.getName()); else all = true; }
        } else if ((API_GRID_KEYS[k] || k === 'anchorCell') && typeof v === 'string') {
          var m = /^(?:'((?:[^']|'')+)'|([^!']+))!/.exec(v);
          if (m) { found = true; add(m[1] ? m[1].replace(/''/g, "'") : m[2]); }
        } else if (key === 'ranges' || k === 'ranges') {
          (Array.isArray(v) ? v : []).forEach(function (x) { if (typeof x === 'string') { var m2 = /^(?:'((?:[^']|'')+)'|([^!']+))!/.exec(x); if (m2) { found = true; add(m2[1] ? m2[1].replace(/''/g, "'") : m2[2]); } } });
          scan(v, k);
        } else scan(v, k);
      });
    }
  };
  scan(op.requests || [], '');
  if (all) return ss.getSheets().map(function (s) { return s.getName(); });
  if (!found) add(apiDefaultSheet_(ctx, op).getName());
  return names;
}
DYNAMIC['api'] = {
  sheets: function (ctx, op) { return apiSheetNames_(ctx, op); },
  touch: function (op) {
    var set = {};
    (Array.isArray(op.requests) ? op.requests : []).forEach(function (r) {
      var t = r && typeof r === 'object' ? Object.keys(r)[0] : null;
      if (t && API_TYPES[t]) API_TYPES[t].touch.forEach(function (x) { set[x] = 1; });
    });
    return Object.keys(set);
  }
};
