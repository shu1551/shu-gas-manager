// combo_planner_template.js - GASコンボ用 自然言語→棚判定＆ops組立エンジン（純JS）
// gas_ws_find.py / gas_ws_ask.py / ws_window.py のロジックをブラウザ・GAS V8 両対応で移植。
// 先頭で var COMBO_CATALOG_DATA = {...}; が定義されるか、ComboPlanner.init(data) で初期化する。

var ComboPlanner = (function () {
  "use strict";

  // ------------------------------------------------------------------ 定数
  var MIN_SCORE = 2;
  var WEAK_SCORE = 6;
  var TOP_N = 5;
  var CLAUSE_TOP = 3;
  var MAX_N = 8;
  var NAME_BONUS = 20;

  var MARGIN = 3;
  var EVIDENCE_GAP = 8;
  var WHAT_MIN = 3;

  var DEFAULT_CATEGORIES = [
    "作る", "シート", "範囲", "行と列", "見た目", "絞る", "整える", "入力", "集計", "守る", "文書"
  ];
  var DEFAULT_LOCAL_HANDLERS = { backup: true };

  var HEAD_OK = "棚の候補（{n} 本）。合う物を選んで ws_do で撃つ。合わなければ語を変えて ws_find、棚に無ければ api（Sheets API の batchUpdate）を使う:";
  var HEAD_WEAK = "近い棚は見つかりません。語を変えて引くか、棚に無ければ api（Sheets API の batchUpdate。札は ws_find の ask=\"棚:api\"）を使う。いちばん近い候補（{n} 本）:";
  var HEAD_NONE = "近い棚は見つかりません。語を変えて引くか、棚に無ければ api（Sheets API の batchUpdate。札は ws_find の ask=\"棚:api\"）を使う。";

  var _HIRA = /^[\u3041-\u309f]+$/;
  var FIND_CLAUSE_SPLIT = /[。、，,\n]|それから|ついでに|あと|でも/;
  var ASK_SPLIT = /[。、，,\n]|(?<=[\u3041-\u3093]て)から|それから|ついでに|そのあと|その後/;

  var VAGUE_RE = /いらない|要らない|不要な?|余分なところ|余分な箇所|古い(?!順)|おかしい|この辺|どこか|適当に|いい感じ|ダブってる人|変な/;
  var CUR_SHEET_RE = /今の|この|現在の|シート名/;
  var LOCATOR_TYPES = { "範囲": true, "列": true, "列[]": true, "行[]": true, "シート": true };

  var _A1 = "[A-Z]{1,3}[0-9]{1,6}";
  var _SEP = "\\s*(?:[:：]|から|〜|~|－|-|ー)\\s*";
  var RANGE_RE = new RegExp("(?<![A-Za-z])(" + _A1 + ")" + _SEP + "(" + _A1 + ")(?:まで)?(?![0-9])");
  var RANGE_RE_G = new RegExp(RANGE_RE.source, "g");
  var CELL_RE = new RegExp("(?<![A-Za-z0-9])(" + _A1 + ")(?![0-9])");
  var CELL_RE_G = new RegExp(CELL_RE.source, "g");
  var COLROWS_RE = new RegExp("(?<![A-Za-z])([A-Z]{1,3})列の?\\s*([0-9]+)行目?" + _SEP + "([0-9]+)行目?(?:まで)?");
  var COLSPAN_RE = /(?<![A-Za-z])([A-Z]{1,3})列?\s*(?:から|〜|~|－|-)\s*([A-Z]{1,3})列(?:まで)?/;
  var COLSPAN_RE_G = new RegExp(COLSPAN_RE.source, "g");
  var COL_RE_G = /(?<![A-Za-z])([A-Z]{1,3})列/g;
  var ROWSPAN_RE = new RegExp("([0-9]+)行目?" + _SEP + "([0-9]+)行目?(?:まで)?");
  var ROWSPAN_RE_G = new RegExp(ROWSPAN_RE.source, "g");
  var ROW_RE_G = /(?<![0-9])([0-9]+)\s*行目/g;
  var QUOTE_RE_G = /[「『"“]([^」』"”]+)[」』"”]/g;
  var PAREN_RE_G = /[（(][^）)]*[）)]/g;
  var NUM_RE_G = /(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+)?)(?![0-9])/g;

  // 色の言い方 → エンジンの色の名前（長い順に当てる）
  var _COLORS = [
    ["薄い灰色", "薄灰"], ["薄い灰", "薄灰"], ["薄灰色", "薄灰"], ["薄いグレー", "薄灰"], ["薄グレー", "薄灰"],
    ["薄い青色", "薄青"], ["薄い青", "薄青"], ["薄青色", "薄青"], ["薄青", "薄青"], ["水色", "水色"], ["シアン", "水色"],
    ["薄い赤色", "薄赤"], ["薄い赤", "薄赤"], ["薄い緑色", "薄緑"], ["薄い緑", "薄緑"],
    ["薄い黄色", "薄黄"], ["薄い黄", "薄黄"], ["薄いオレンジ色", "薄橙"], ["薄いオレンジ", "薄橙"],
    ["薄い紫色", "薄紫"], ["薄い紫", "薄紫"],
    ["灰色", "灰"], ["グレー", "灰"], ["オレンジ色", "橙"], ["オレンジ", "橙"], ["ピンク色", "桃"], ["ピンク", "桃"],
    ["ネイビー", "紺"], ["紺色", "紺"], ["紺", "紺"], ["茶色", "茶"],
    ["赤色", "赤"], ["青色", "青"], ["緑色", "緑"], ["黄色", "黄"], ["紫色", "紫"], ["黒色", "黒"], ["白色", "白"],
    ["赤", "赤"], ["青", "青"], ["緑", "緑"], ["黄", "黄"], ["紫", "紫"], ["黒", "黒"], ["白", "白"]
  ];
  var _COLOR_ALT = _COLORS.map(function (c) { return c[0]; }).join("|") + "|#[0-9a-f]{6}|#[0-9a-f]{3}";
  var _FG_NOCOLOR_RE_G = new RegExp("(?<![大小])(文字|フォント)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
  var _BG_NOCOLOR_RE_G = new RegExp("(背景|塗り)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
  var _PAINT_COLOR_RE_G = new RegExp("(" + _COLOR_ALT + ")(?:に|で)塗", "g");
  var _TITLE_NOCOLOR_RE_G = new RegExp("(タイトル|見出し)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
  var _HEX_COLOR_RE_G =/(?<![0-9A-Za-z])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z])/g;
  var _EN_COLOR_RE_G = /(?<![A-Za-z])(lightred|lightgreen|lightyellow|lightgray|lightblue|orange|purple|yellow|green|black|white|brown|navy|pink|gray|grey|cyan|blue|red)(?![A-Za-z])/gi;

  // 文字色（前景）を表すキーワード群（ws_ask_rules.json が渡されたら init 時に共通定義で上書き）
  var FG_COLOR_KEYS = ["文字", "フォント", "持ち色", "持ちの色", "本当の色", "ほんとの色", "字の色", "字を", "字は", "字が"];
  var BG_COLOR_KEYS = ["背景", "塗り", "セル"];
  var FG_AFTER_RE = /^(?:文字|フォント|持ち色|持ちの色|本当の色|ほんとの色|字の色)/;
  var BG_AFTER_RE = /^(?:い|の)?(?:背景|塗り)/;
  var PLACE_ONLY_RE = /^.{1,12}(?:のとこ|のところ|の所|の列に|の列は|の列で|の欄に|の欄は)(?:は|も)?$/;
  var _CLAUSE_PROTECT_RES = [
    /(?:に|へ|は)\s*[^\s、,。]{1,16}(?:[、,][^\s、,。]{1,16})+(?=(?:の|という|から)?(?:プルダウン|リスト|選択肢))/g,
    /[A-Z]{1,3}[0-9]{1,6}に[^\s、,。]+(?:[、,]\s*[A-Z]{1,3}[0-9]{1,6}に[^\s、,。]+)+/g,
    /[^\s、,。]{1,16}の(?:昇順|降順|大きい順|小さい順|高い順|低い順|多い順|少ない順|古い順|新しい順)(?:[、,]\s*(?:その中で\s*)?[^\s、,。]{1,16}の(?:昇順|降順|大きい順|小さい順|高い順|低い順|多い順|少ない順|古い順|新しい順))+/g,
    /(?:(?:見出し|項目|列)[がは]\s*)?[^\s、,。をに]{0,11}[^\s、,。をにてで](?:[、,]\s*(?:と\s*)?[^\s、,。をに]{0,11}[^\s、,。をにてで])+(?=(?:の|で|という)(?:表|テーブル|名簿|一覧表))/g
  ];

  function _applyAskRules(rules) {
    if (!rules || typeof rules !== "object") return;
    if (typeof rules.margin === "number") MARGIN = rules.margin;
    if (typeof rules.evidence_gap === "number") EVIDENCE_GAP = rules.evidence_gap;
    if (typeof rules.what_min === "number") WHAT_MIN = rules.what_min;
    if (typeof rules.vague_re === "string" && rules.vague_re) VAGUE_RE = new RegExp(rules.vague_re);
    if (typeof rules.cur_sheet_re === "string" && rules.cur_sheet_re) CUR_SHEET_RE = new RegExp(rules.cur_sheet_re);
    if (typeof rules.place_only_re === "string" && rules.place_only_re) PLACE_ONLY_RE = new RegExp(rules.place_only_re);
    if (Array.isArray(rules.clause_protect_patterns) && rules.clause_protect_patterns.length) {
      _CLAUSE_PROTECT_RES = rules.clause_protect_patterns.map(function (p) { return new RegExp(p, "g"); });
    }
    if (Array.isArray(rules.colors) && rules.colors.length) {
      _COLORS = rules.colors.map(function (c) { return [String(c[0]), String(c[1])]; });
      _COLOR_ALT = _COLORS.map(function (c) { return c[0]; }).join("|") + "|#[0-9a-f]{6}|#[0-9a-f]{3}";
      _FG_NOCOLOR_RE_G = new RegExp("(?<![大小])(文字|フォント)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
      _BG_NOCOLOR_RE_G = new RegExp("(背景|塗り)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
      _PAINT_COLOR_RE_G = new RegExp("(" + _COLOR_ALT + ")(?:に|で)塗", "g");
      _TITLE_NOCOLOR_RE_G = new RegExp("(タイトル|見出し)(?:を|は|に)?(" + _COLOR_ALT + ")", "g");
    }
    if (Array.isArray(rules.fg_color_keys) && rules.fg_color_keys.length) FG_COLOR_KEYS = rules.fg_color_keys.slice();
    if (Array.isArray(rules.bg_color_keys) && rules.bg_color_keys.length) BG_COLOR_KEYS = rules.bg_color_keys.slice();
    if (typeof rules.fg_after_re === "string" && rules.fg_after_re) FG_AFTER_RE = new RegExp(rules.fg_after_re);
    if (typeof rules.bg_after_re === "string" && rules.bg_after_re) BG_AFTER_RE = new RegExp(rules.bg_after_re);
  }

  var _HERE_ROW_RE = /(?:この|選択(?:中の?)?|今の)行/;
  var _HERE_ROW_RE_G = /(?:この|選択(?:中の?)?|今の)行/g;
  var _HERE_COL_RE = /(?:この|選択(?:中の?)?|今の)列/;
  var _HERE_COL_RE_G = /(?:この|選択(?:中の?)?|今の)列/g;
  var _HERE_RANGE_RE = /(?:ここ|このセル|この範囲|選択範囲|選択セル|選択中(?:のセル|の範囲|の場所|の箇所)?|今選んで(?:いる|る)(?:セル|範囲|ところ|箇所)?)/;
  var _HERE_RANGE_RE_G = /(?:ここ|このセル|この範囲|選択範囲|選択セル|選択中(?:のセル|の範囲|の場所|の箇所)?|今選んで(?:いる|る)(?:セル|範囲|ところ|箇所)?)/g;

  // ------------------------------------------------------------------ 状態・キャッシュ
  var _initialized = false;
  var _shelves = [];
  var _byName = {};
  var _synonyms = [];
  var _guide = [];
  var _guideNorm = [];
  var _categories = DEFAULT_CATEGORIES.slice();
  var _localHandlers = DEFAULT_LOCAL_HANDLERS;
  var _index = [];
  var _rxCache = {};

  function _rx(pat) {
    if (!_rxCache[pat]) {
      _rxCache[pat] = new RegExp(pat);
    }
    return _rxCache[pat];
  }

  function nfkc(s) {
    return String(s === null || s === undefined ? "" : s).normalize("NFKC");
  }

  function _base(s) {
    return nfkc(s).toLowerCase().replace(/\s+/g, "");
  }

  function norm(s, synonyms) {
    var out = _base(s);
    var syns = synonyms !== undefined ? synonyms : _synonyms;
    if (syns && syns.length) {
      for (var i = 0; i < syns.length; i++) {
        var pair = syns[i];
        if (!pair || !pair[0]) continue;
        out = out.split(pair[0]).join(pair[1] || "");
      }
    }
    // 「本当の色」「ほんとの色」「字の色」も文字色として統一（「文字の色」を壊さないため直前が「文」のときは除外）
    out = out.split("本当の色").join("文字色");
    out = out.split("ほんとの色").join("文字色");
    out = out.replace(/(^|[^文])字の色/g, "$1文字色");
    // 「色」を言わない言い方（「文字を赤」「背景を緑」「タイトルを赤に」）も統一
    out = out.replace(_FG_NOCOLOR_RE_G, "$1色$2");
    out = out.replace(_BG_NOCOLOR_RE_G, "背景色$2");
    out = out.replace(_PAINT_COLOR_RE_G, "背景色$1");
    out = out.replace(_TITLE_NOCOLOR_RE_G, "$1文字色$2");
    // 「タイトルの色は青」「表題の色を赤に」＝タイトルの文字色
    out = out.replace(/(タイトル|表題|題名)の色/g, "$1の文字色");
    return out.split("を").join("");
  }

  function _isEmptyVal(v) {
    return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
  }

  function _hasOwn(obj, k) {
    return Object.prototype.hasOwnProperty.call(obj, k);
  }

  function _isLocalHandler(name) {
    return !!(_localHandlers && _localHandlers[name]);
  }

  // ------------------------------------------------------------------ 初期化
  function init(data) {
    data = data || {};
    _shelves = Array.isArray(data.shelves) ? data.shelves : [];
    _byName = {};
    for (var i = 0; i < _shelves.length; i++) {
      var sh = _shelves[i];
      if (sh && sh.name) {
        _byName[sh.name] = sh;
      }
    }

    // synonyms 正規化（[a, b] 配列）
    _synonyms = [];
    var rawSyn = Array.isArray(data.synonyms) ? data.synonyms : [];
    for (var j = 0; j < rawSyn.length; j++) {
      var item = rawSyn[j];
      var a = "", b = "";
      if (Array.isArray(item)) {
        a = _base(item[0]);
        b = _base(item[1] || "");
      } else if (item && typeof item === "object") {
        a = _base(item.from || item.a || "");
        b = _base(item.to || item.b || "");
      }
      if (a) _synonyms.push([a, b]);
    }

    // guide 正規化（[words, text] または {words, text}）
    _guide = [];
    var rawGuide = Array.isArray(data.guide) ? data.guide : [];
    for (var g = 0; g < rawGuide.length; g++) {
      var gi = rawGuide[g];
      if (Array.isArray(gi) && gi.length >= 2) {
        _guide.push([gi[0] || [], String(gi[1] || "")]);
      } else if (gi && typeof gi === "object") {
        _guide.push([gi.words || [], String(gi.text || "")]);
      }
    }

    _categories = Array.isArray(data.categories) && data.categories.length
      ? data.categories.slice()
      : DEFAULT_CATEGORIES.slice();

    if (Array.isArray(data.localHandlers)) {
      _localHandlers = {};
      for (var lh = 0; lh < data.localHandlers.length; lh++) {
        _localHandlers[data.localHandlers[lh]] = true;
      }
    } else if (data.localHandlers && typeof data.localHandlers === "object") {
      _localHandlers = data.localHandlers;
    } else {
      _localHandlers = DEFAULT_LOCAL_HANDLERS;
    }

    if (data.ask_rules && typeof data.ask_rules === "object") {
      _applyAskRules(data.ask_rules);
    }

    // 検索用インデックス構築
    _guideNorm = [];
    for (var gn = 0; gn < _guide.length; gn++) {
      var gWords = _guide[gn][0];
      var gText = _guide[gn][1];
      var nwords = [];
      for (var gw = 0; gw < gWords.length; gw++) {
        var nw = norm(gWords[gw], _synonyms);
        if (nw) nwords.push(nw);
      }
      _guideNorm.push([nwords, gText]);
    }

    _index = [];
    for (var order = 0; order < _shelves.length; order++) {
      var s = _shelves[order];
      var sWords = [];
      var rawWords = s.words || [];
      for (var wi = 0; wi < rawWords.length; wi++) {
        sWords.push(norm(rawWords[wi], _synonyms));
      }
      var exStr = "";
      var exs = s.examples || [];
      for (var ei = 0; ei < exs.length; ei++) {
        exStr += String(exs[ei][0] || "");
      }
      var sText = norm(String(s.title || "") + rawWords.join("") + exStr, _synonyms);
      _index.push({
        order: order,
        shelf: s,
        words: sWords,
        text: sText
      });
    }

    _initialized = true;
    return ComboPlanner;
  }

  function _ensureInit() {
    if (_initialized) return;
    if (typeof COMBO_CATALOG_DATA !== "undefined" && COMBO_CATALOG_DATA) {
      init(COMBO_CATALOG_DATA);
    } else if (typeof globalThis !== "undefined" && globalThis.COMBO_CATALOG_DATA) {
      init(globalThis.COMBO_CATALOG_DATA);
    }
  }

  // ------------------------------------------------------------------ Finder（点数・検索・札）
  function scoreAll(askText, kind) {
    _ensureInit();
    kind = kind || "";
    var q = norm(askText, _synonyms);
    var raw = _base(askText);

    var gramsObj = {};
    var grams = [];
    for (var i = 0; i < q.length - 1; i++) {
      var g = q.slice(i, i + 2);
      if (g.length === 2 && !_HIRA.test(g) && !gramsObj[g]) {
        gramsObj[g] = true;
        grams.push(g);
      }
    }

    var out = [];
    for (var idx = 0; idx < _index.length; idx++) {
      var item = _index[idx];
      var s = item.shelf;
      if (!s.searchable || (kind && s.kind !== kind && !s.shared && !_isLocalHandler(s.name))) {
        continue;
      }
      var wp = 0;
      for (var wi = 0; wi < item.words.length; wi++) {
        var w = item.words[wi];
        if (w && q.indexOf(w) >= 0) {
          wp += w.length;
        }
      }
      wp *= 2;

      var cp = 0;
      for (var gi = 0; gi < grams.length; gi++) {
        if (item.text.indexOf(grams[gi]) >= 0) {
          cp += 1;
        }
      }

      var bonus = raw.indexOf(s.name) >= 0 ? NAME_BONUS : 0;
      var total = wp + cp + bonus;
      if (total >= MIN_SCORE) {
        out.push({
          total: total,
          order: item.order,
          shelf: s,
          detail: { "語": wp, "字": cp, "名": bonus }
        });
      }
    }
    out.sort(function (a, b) {
      if (b.total !== a.total) return b.total - a.total;
      return a.order - b.order;
    });
    return out;
  }

  function _findClauses(askText) {
    var parts = String(askText || "").split(FIND_CLAUSE_SPLIT);
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i].trim();
      if (p.length >= 2) out.push(p);
    }
    return out;
  }

  function _matchGuide(qNorm) {
    var out = [];
    for (var i = 0; i < _guideNorm.length; i++) {
      var nwords = _guideNorm[i][0];
      var text = _guideNorm[i][1];
      for (var j = 0; j < nwords.length; j++) {
        if (qNorm.indexOf(nwords[j]) >= 0) {
          out.push(text);
          break;
        }
      }
    }
    return out;
  }

  function card(s, withDiff) {
    if (withDiff === undefined) withDiff = true;
    var mark = s.danger ? " ＊" + s.danger : "";
    var lines = [s.name + mark + "｜" + s.title + "｜" + s.args_raw];
    if (withDiff && s.diff) {
      lines.push("   違い: " + s.diff);
    }
    if (s.examples && s.examples.length) {
      var ex = s.examples[0];
      lines.push("   例 「" + ex[0] + "」→ " + JSON.stringify(ex[1]));
    }
    return lines;
  }

  function _renderFind(picks, guide, weak) {
    var lines = [];
    for (var g = 0; g < guide.length; g++) {
      lines.push("案内: " + guide[g]);
    }
    if (!picks || !picks.length) {
      lines.push(HEAD_NONE);
      return lines.join("\n");
    }
    var head = (weak ? HEAD_WEAK : HEAD_OK).replace("{n}", String(picks.length));
    lines.push(head);
    for (var i = 0; i < picks.length; i++) {
      var c = card(picks[i], true);
      lines.push((i + 1) + ". " + c[0]);
      for (var k = 1; k < c.length; k++) lines.push(c[k]);
    }
    return lines.join("\n");
  }

  function find(askText, kind) {
    _ensureInit();
    askText = String(askText || "").trim();
    kind = kind || "";
    var scores = {};
    var picks = [];
    var overall = scoreAll(askText, kind);
    for (var i = 0; i < overall.length; i++) {
      scores[overall[i].shelf.name] = overall[i].total;
    }
    var cl = _findClauses(askText);
    if (cl.length <= 1) {
      var chosen = overall.slice(0, TOP_N);
      for (var ci = 0; ci < chosen.length; ci++) picks.push(chosen[ci].shelf);
    } else {
      var seenNames = {};
      var seen = [];
      var topOverall = overall.slice(0, CLAUSE_TOP);
      for (var oi = 0; oi < topOverall.length; oi++) {
        var os = topOverall[oi].shelf;
        if (!seenNames[os.name]) {
          seenNames[os.name] = true;
          seen.push(os);
        }
      }
      for (var cj = 0; cj < cl.length; cj++) {
        var sub = scoreAll(cl[cj], kind).slice(0, CLAUSE_TOP);
        for (var sj = 0; sj < sub.length; sj++) {
          var subItem = sub[sj];
          if (!_hasOwn(scores, subItem.shelf.name)) {
            scores[subItem.shelf.name] = subItem.total;
          }
          if (!seenNames[subItem.shelf.name]) {
            seenNames[subItem.shelf.name] = true;
            seen.push(subItem.shelf);
          }
        }
      }
      picks = seen.slice(0, MAX_N);
    }
    var q = norm(askText, _synonyms);
    var guide = _matchGuide(q);
    var topScore = 0;
    for (var pi = 0; pi < picks.length; pi++) {
      var sc = scores[picks[pi].name] || 0;
      if (sc > topScore) topScore = sc;
    }
    var text = _renderFind(picks, guide, topScore < WEAK_SCORE);
    return { picks: picks, scores: scores, guide: guide, text: text };
  }

  function _near(name, n) {
    if (n === undefined) n = 3;
    var res = find(name, "");
    var picks = res.picks.slice(0, n);
    return picks.length ? ("近い棚:\n" + _renderFind(picks, [], false)) : "";
  }

  function _overview(kind) {
    _ensureInit();
    kind = kind || "";
    var counts = {};
    for (var i = 0; i < _shelves.length; i++) {
      var s = _shelves[i];
      if (s.searchable && (!kind || s.kind === kind || s.shared || _isLocalHandler(s.name))) {
        counts[s.category] = (counts[s.category] || 0) + 1;
      }
    }
    var lines = ['棚の分類と本数（ws_find(ask="分類:名前") でその分類の札、ask="頼みの文" で候補）:'];
    for (var ci = 0; ci < _categories.length; ci++) {
      var cat = _categories[ci];
      if (_hasOwn(counts, cat)) {
        lines.push("  " + cat + ": " + counts[cat] + " 本");
      }
    }
    return lines.join("\n");
  }

  function ask(askText, kind) {
    _ensureInit();
    askText = String(askText || "").trim();
    kind = kind || "";
    var mCat = /^分類\s*[:：]\s*(.+)$/.exec(askText);
    if (mCat) {
      var cat = mCat[1].trim();
      var targetKind = cat === "文書" ? "doc" : kind;
      var matched = [];
      for (var i = 0; i < _shelves.length; i++) {
        var s = _shelves[i];
        if (s.category === cat && s.searchable && (!targetKind || s.kind === targetKind || s.shared || _isLocalHandler(s.name))) {
          matched.push(s);
        }
      }
      if (!matched.length) {
        return "分類「" + cat + "」の棚はありません。分類: " + _categories.join("・");
      }
      return _renderFind(matched, [], false);
    }
    var mShelf = /^棚\s*[:：]\s*(\S+)$/.exec(askText);
    if (mShelf) {
      var sName = mShelf[1];
      var sh = _byName[sName];
      if (!sh) {
        return "棚「" + sName + "」はありません。" + _near(sName, 3);
      }
      var c = card(sh, true);
      return ["1. " + c[0]].concat(c.slice(1), ["   引数: " + sh.args_raw]).join("\n");
    }
    if (!askText) {
      return _overview(kind);
    }
    if (!kind && (askText.indexOf("doc.") === 0 || askText.indexOf("棚:doc.") >= 0 || askText.indexOf("棚：doc.") >= 0)) {
      kind = "doc";
    }
    return find(askText, kind).text;
  }

  // ------------------------------------------------------------------ 読み取りヘルパー
  function _clauses(askText) {
    var src = nfkc(askText);
    var saved = [];
    var protect = function (re) {
      src = src.replace(re, function (m) {
        var k = "\uE010" + saved.length + "\uE011";
        saved.push(m);
        return k;
      });
    };
    // プルダウン候補や複数セルの「、」区切り、複数キー並べ替え、表作成の見出し列挙を節分割から守る
    for (var pi = 0; pi < _CLAUSE_PROTECT_RES.length; pi++) {
      protect(_CLAUSE_PROTECT_RES[pi]);
    }
    var parts = src.split(ASK_SPLIT);
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var restored = parts[i].replace(/\uE010(\d+)\uE011/g, function (_, idx) {
        return saved[parseInt(idx, 10)] || "";
      });
      var p = restored.trim();
      if (p.length < 2) continue;
      if (out.length && PLACE_ONLY_RE.test(out[out.length - 1])) out[out.length - 1] = out[out.length - 1] + " " + p;
      else out.push(p);
    }
    return out;
  }

  function _colNum(s) {
    var n = 0;
    for (var i = 0; i < s.length; i++) {
      n = n * 26 + (s.charCodeAt(i) - 64);
    }
    return n;
  }

  function _colLetter(n) {
    var s = "";
    while (n > 0) {
      var m = (n - 1) % 26;
      s = String.fromCharCode(65 + m) + s;
      n = Math.floor((n - 1) / 26);
    }
    return s;
  }

  function _rowsOf(text) {
    var out = [];
    var m;
    ROWSPAN_RE_G.lastIndex = 0;
    while ((m = ROWSPAN_RE_G.exec(text)) !== null) {
      var a = parseInt(m[1], 10);
      var b = parseInt(m[2], 10);
      if (a <= b && b - a < 5000) {
        for (var r = a; r <= b; r++) out.push(r);
      }
    }
    var rest = text.replace(ROWSPAN_RE_G, " ");
    ROW_RE_G.lastIndex = 0;
    while ((m = ROW_RE_G.exec(rest)) !== null) {
      out.push(parseInt(m[1], 10));
    }
    var seen = {};
    var uniq = [];
    for (var i = 0; i < out.length; i++) {
      if (!seen[out[i]]) {
        seen[out[i]] = true;
        uniq.push(out[i]);
      }
    }
    return uniq;
  }

  function _colLetters(text) {
    var out = [];
    var m;
    COLSPAN_RE_G.lastIndex = 0;
    while ((m = COLSPAN_RE_G.exec(text)) !== null) {
      var fromN = _colNum(m[1]);
      var toN = _colNum(m[2]);
      if (fromN <= toN && toN - fromN < 60) {
        for (var n = fromN; n <= toN; n++) out.push(_colLetter(n));
      }
    }
    var rest = text.replace(COLSPAN_RE_G, " ");
    COL_RE_G.lastIndex = 0;
    while ((m = COL_RE_G.exec(rest)) !== null) {
      out.push(m[1]);
    }
    var seen = {};
    var uniq = [];
    for (var i = 0; i < out.length; i++) {
      if (!seen[out[i]]) {
        seen[out[i]] = true;
        uniq.push(out[i]);
      }
    }
    return uniq;
  }

  var _COL_TOKEN_STOP_TOP = {
    "集計": 1, "合計": 1, "平均": 1, "件数": 1, "人数": 1, "グラフ": 1, "ピボット": 1, "クロス": 1, "シート": 1, "別シート": 1,
    "データ": 1, "テーブル": 1, "一覧": 1, "全部": 1, "全体": 1, "全て": 1, "行全体": 1, "条件": 1, "書式": 1, "表示": 1, "形式": 1,
    "作成": 1, "追加": 1, "変更": 1, "削除": 1, "抽出": 1, "固定": 1, "並べ": 1, "整理": 1, "自動": 1, "調整": 1, "内容": 1, "中身": 1,
    "範囲": 1, "セル": 1, "タイトル": 1, "見出し": 1, "ヘッダ": 1, "合計行": 1, "標準": 1, "棒グラフ": 1, "折れ線": 1, "円グラフ": 1,
    "新しい": 1, "別表": 1, "結果": 1, "計算": 1, "数式": 1, "文字": 1, "背景": 1, "罫線": 1, "太字": 1, "斜体": 1, "中央": 1, "右揃": 1,
    "左揃": 1, "非表示": 1, "表示形式": 1, "プルダウン": 1, "リスト": 1, "選択肢": 1, "以上": 1, "以下": 1, "未満": 1, "以外": 1,
    "重複": 1, "空行": 1, "空白": 1, "空欄": 1, "昇順": 1, "降順": 1, "上位": 1, "下位": 1, "最大": 1, "最小": 1, "小計": 1, "累計": 1,
    "順位": 1, "構成比": 1, "割合": 1, "消費税": 1, "税込": 1, "税抜": 1, "円マーク": 1, "カンマ": 1, "パーセント": 1, "年月日": 1
  };
  var _FORMULA_COL_SHELVES_JS = {
    "calc.col": 1, "calc.percent": 1, "calc.diff": 1, "calc.running": 1, "calc.rank": 1,
    "calc.if": 1, "calc.tax": 1, "date.parts": 1, "date.diff": 1, "date.age": 1,
    "text.join": 1, "col.compare": 1, "lookup.add": 1
  };
  var _SKIP_COL_VALIDATE_JS = {
    "table.new:number": 1, "table.new:total": 1,
    "lookup.add:val_col": 1, "lookup.add:key_col": 1
  };

  var _CMP_VALUE_SHELVES_JS = {
    "filter.where": 1, "filter.delete": 1, "filter.extract": 1,
    "cf.add": 1, "calc.if": 1, "rows.highlight": 1
  };
  var _PCT_COL_RE_JS = /(?:率|割合|構成比|達成|進捗|%|％)/;
  var _CALC_VERB_PREFIX_RE_JS = /^.*?(?:(?:差し引い|掛け|かけ|足し|たし|引い|ひい|割っ|わっ|乗算し|加算し|減算し|除算し|計算し)(?:た|て)|(?:掛け算|かけ算|足し算|引き算|割り算)(?:の|で))\s*/;

  function _normFilterNumTopJs(val) {
    if (val === undefined || val === null) return null;
    var s = nfkc(String(val)).replace(/,/g, "").trim();
    if (!s) return null;
    var isPct = s.slice(-1) === "%";
    if (isPct) s = s.slice(0, -1).trim();
    var mul = 1;
    if (s.slice(-1) === "万") { mul = 10000; s = s.slice(0, -1).trim(); }
    else if (s.slice(-1) === "億") { mul = 100000000; s = s.slice(0, -1).trim(); }
    if (!s || isNaN(Number(s))) return null;
    var num = Number(s) * mul;
    if (isPct) num = num / 100.0;
    return String(num);
  }

  function _resolveCmpValueJs(opObj, text) {
    var w = opObj.when;
    if (w !== "gt" && w !== "ge" && w !== "lt" && w !== "le" && w !== "eq" && w !== "ne") return;
    var tN = nfkc(text);
    var mNum = /(-?[0-9][0-9,\.]*%?[万億]?)(?:円|個|件|人|時間|点)?\s*(?:以上|以下|未満|より|を超|超|になっていない|になってない|ではない|でない|じゃない|以外|の行|のセル|なら|判定)/.exec(tN);
    var raw = opObj.value;
    if (w === "gt" || w === "ge" || w === "lt" || w === "le") {
      delete opObj.equals;
      if (mNum) {
        var cand = mNum[1].trim();
        if (_isEmptyVal(raw) || (/[%万億]/.test(cand) && !/[%万億]/.test(nfkc(String(raw))))) {
          raw = cand;
        }
      }
      var normV = _normFilterNumTopJs(raw);
      if (normV !== null) opObj.value = normV;
      else delete opObj.value;
    } else {
      if (_isEmptyVal(raw) && w === "ne") {
        var mNe = /(?:が|は)[『「]?([^』」\s、。]+?)[』」]?(?:になっていない|になってない|ではない|でない|じゃない|以外)/.exec(tN) ||
          /([^\s、。をにのがは]+?)(?:になっていない|になってない|ではない|でない|じゃない|以外)/.exec(tN);
        if (mNe) raw = mNe[1].trim();
      }
      if (!_isEmptyVal(raw) && mNum) {
        var cand2 = mNum[1].trim();
        if (/[%万億]/.test(cand2) && !/[%万億]/.test(nfkc(String(raw))) && cand2.replace(/[%万億,]/g, "") === nfkc(String(raw)).replace(/,/g, "")) {
          raw = cand2;
        }
      }
      if (!_isEmptyVal(raw)) {
        var normV2 = _normFilterNumTopJs(raw);
        if (normV2 !== null && (w === "ne" || /[%万億,]/.test(nfkc(String(raw))))) opObj.value = normV2;
        else opObj.value = String(raw).trim();
      }
    }
  }

  function _cleanCalcColNameJs(rawName) {
    if (!rawName) return null;
    var s = nfkc(String(rawName)).trim().replace(_CALC_VERB_PREFIX_RE_JS, "");
    s = s.replace(/^(?:の|で|を|に|へ)+|(?:の列|列|の欄|欄|の)+$/g, "").trim();
    if (!s || /(?:差し引い|掛け|かけ|足し|たし|引い|ひい|割っ|わっ)(?:た|て)/.test(s)) return null;
    return s;
  }

  function _matchRowCondJs(cellVal, when, target) {
    var w = String(when || "eq").toLowerCase();
    var blank = cellVal === null || cellVal === undefined || String(cellVal).trim() === "";
    if (w === "blank") return blank;
    if (w === "notblank") return !blank;
    var tgt = (target === null || target === undefined) ? "" : String(target).trim();
    if (w === "contains") return !blank && String(cellVal).indexOf(tgt) >= 0;
    var cv = Number(String(cellVal).replace(/,/g, "").trim());
    var tv = Number(tgt.replace(/,/g, "").trim());
    if (w === "gt" || w === "ge" || w === "lt" || w === "le") {
      if (blank || tgt === "" || isNaN(cv) || isNaN(tv)) return false;
      return w === "gt" ? cv > tv : (w === "ge" ? cv >= tv : (w === "lt" ? cv < tv : cv <= tv));
    }
    if (w === "ne") {
      if (!blank && tgt !== "" && !isNaN(cv) && !isNaN(tv)) return cv !== tv;
      return (blank ? "" : String(cellVal).trim()) !== tgt;
    }
    if (!blank && tgt !== "" && !isNaN(cv) && !isNaN(tv)) return cv === tv;
    return (blank ? "" : String(cellVal).trim()) === tgt;
  }

  var _ADD_SHELVES_JS = {
    "banding.add": 1, "filter.on": 1, "cf.add": 1, "cf.dup": 1, "cf.scale": 1, "cf.weekend": 1,
    "validation.list": 1, "validation.number": 1, "validation.date": 1, "freeze": 1,
    "note.set": 1, "link.set": 1, "protect.range": 1, "protect.sheet": 1,
    "group.rows": 1, "group.cols": 1, "chart.new": 1
  };

  function _cleanValidationItemsJs(text, origQuotesList, curItems) {
    var stripItem = function (x) {
      return String(x === null || x === undefined ? "" : x).trim()
        .replace(/^[「『"“\s]+|[」』"”\s]+$/g, "")
        .replace(/[「『"“”』」]+/g, "").trim();
    };
    var splitChunk = function (chunk) {
      var s = String(chunk === null || chunk === undefined ? "" : chunk).trim()
        .replace(/^[「『"“\s]+/, "")
        .replace(/(?:[」』"”]|の|から|という|で|を|選べる|\s)+$/, "").trim();
      if (!s) return [];
      var parts = /[・、,／/]/.test(s) ? s.split(/[・、,／/]/) : (s.indexOf("と") >= 0 ? s.split("と") : [s]);
      var out = [];
      for (var i = 0; i < parts.length; i++) {
        var it = stripItem(parts[i]);
        if (it) out.push(it);
      }
      return out;
    };
    if (origQuotesList && origQuotesList.length) {
      if (origQuotesList.length >= 2) {
        var c0 = [];
        for (var qi = 0; qi < origQuotesList.length; qi++) {
          var qit = stripItem(origQuotesList[qi]);
          if (qit) c0.push(qit);
        }
        if (c0.length) return c0;
      } else {
        var c1 = splitChunk(origQuotesList[0]);
        if (c1.length >= 2) return c1;
      }
    }
    var mList = /(?:に|へ|は)\s*(.+?)\s*(?:の|という|から|で)?(?:選べる)?(?:プルダウン|リスト|選択肢)/.exec(nfkc(text));
    if (mList) {
      var c2 = splitChunk(mList[1]);
      if (c2.length >= 2) return c2;
    }
    if (Array.isArray(curItems) && curItems.length) {
      var c3 = splitChunk(curItems.join("・"));
      if (c3.length) return c3;
    }
    return curItems;
  }

  function _normalizeCalcExprStrJs(expr, table) {
    if (!expr) return expr;
    var s = nfkc(String(expr)).trim()
      .replace(/×/g, "*").replace(/＊/g, "*")
      .replace(/÷/g, "/").replace(/／/g, "/")
      .replace(/＋/g, "+").replace(/[−ー]/g, "-");
    var parts = s.split(/([*/+\-()])/);
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var st = parts[i].trim();
      if (!st || st === "*" || st === "/" || st === "+" || st === "-" || st === "(" || st === ")" || /^-?[0-9]+(?:\.[0-9]+)?$/.test(st)) {
        out.push(st);
      } else {
        var res = _resolveColRefJs(st, table);
        out.push(res || st);
      }
    }
    return out.join("");
  }

  function _resolveColRefJs(raw, table) {
    var s = nfkc(String(raw === null || raw === undefined ? "" : raw)).trim();
    if (!s) return null;
    if (!table || !Array.isArray(table.columns) || !table.columns.length) return String(raw).trim();
    if (/^[A-Z]{1,3}$/.test(s)) return s;
    var mCl = /^([A-Z]{1,3})列$/.exec(s);
    if (mCl) return mCl[1];
    var sClean = s.replace(/(?:の列|列|の欄|欄)$/, "").trim();
    var cols = [];
    for (var i = 0; i < table.columns.length; i++) {
      var nm = String((table.columns[i] && table.columns[i].name) || "").trim();
      if (nm) cols.push(nm);
    }
    for (var j = 0; j < cols.length; j++) {
      var ncn = nfkc(cols[j]).trim();
      if (ncn === s || ncn === sClean) return cols[j];
    }
    var tok = sClean.replace(/(?:別表|別|毎)$/, "").trim();
    if (tok.length >= 2 && !_COL_TOKEN_STOP_TOP[tok]) {
      var hits = [];
      for (var k = 0; k < cols.length; k++) {
        if (nfkc(cols[k]).indexOf(tok) >= 0) hits.push(cols[k]);
      }
      if (hits.length === 1) return hits[0];
    }
    return null;
  }

  function _exprReferencedColsJs(expr, table) {
    var refs = {};
    if (!expr) return refs;
    var s = nfkc(String(expr));
    var cols = (table && Array.isArray(table.columns)) ? table.columns.slice() : [];
    cols.sort(function (a, b) { return String((b && b.name) || "").length - String((a && a.name) || "").length; });
    for (var i = 0; i < cols.length; i++) {
      var nm = String((cols[i] && cols[i].name) || "").trim();
      var cl = String((cols[i] && cols[i].col) || "").trim();
      if (nm && s.indexOf(nm) >= 0) {
        refs[nm] = true;
        if (cl) refs[cl] = true;
        s = s.split(nm).join(" ");
      }
    }
    var reL = /(?<![A-Za-z0-9_$!])([A-Z]{1,3})(?![A-Za-z0-9_(])/g;
    var m;
    while ((m = reL.exec(s)) !== null) {
      var cl2 = m[1];
      refs[cl2] = true;
      for (var j = 0; j < cols.length; j++) {
        if (cols[j] && cols[j].col === cl2 && cols[j].name) refs[String(cols[j].name).trim()] = true;
      }
    }
    return refs;
  }

  function _validateAndResolveColArgsJs(shelf, op, table, missing) {
    if (!table || !Array.isArray(table.columns) || !table.columns.length) return;
    var shName = shelf.name;
    var addMiss = function (msg) { if (missing.indexOf(msg) < 0) missing.push(msg); };
    var argsList = shelf.args || [];
    for (var i = 0; i < argsList.length; i++) {
      var a = argsList[i], k = a.name, t = a.type;
      if (!_hasOwn(op, k) || _SKIP_COL_VALIDATE_JS[shName + ":" + k]) continue;
      if (t === "列") {
        var raw = op[k];
        var res = _resolveColRefJs(raw, table);
        if (res) op[k] = res;
        else { delete op[k]; addMiss("表に無い列名（" + raw + "）"); }
      } else if (t === "列[]") {
        var vals = Array.isArray(op[k]) ? op[k] : [op[k]];
        var resList = [], bad = [];
        for (var vi = 0; vi < vals.length; vi++) {
          var rv = _resolveColRefJs(vals[vi], table);
          if (rv) { if (resList.indexOf(rv) < 0) resList.push(rv); }
          else bad.push(String(vals[vi]));
        }
        if (bad.length) { delete op[k]; addMiss("表に無い列名（" + bad.join("・") + "）"); }
        else if (resList.length) op[k] = resList;
      }
    }
    if (shName === "sort" && Array.isArray(op.cols)) {
      var newScols = [], badS = [];
      for (var si = 0; si < op.cols.length; si++) {
        var sp = String(op.cols[si]);
        var neg = sp.charAt(0) === "-";
        var body = neg ? sp.slice(1) : sp;
        var rs = _resolveColRefJs(body, table);
        if (rs) newScols.push((neg ? "-" : "") + rs);
        else badS.push(body);
      }
      if (badS.length) { delete op.cols; addMiss("表に無い列名（" + badS.join("・") + "）"); }
      else if (newScols.length) op.cols = newScols;
    }
  }

  function _colNames(text, table) {
    if (!table || !table.columns) return [];
    var seenSet = {};
    var names = [];
    for (var i = 0; i < table.columns.length; i++) {
      var rawNm = table.columns[i] && table.columns[i].name;
      if (rawNm !== null && rawNm !== undefined && String(rawNm).trim()) {
        var sNm = String(rawNm).trim();
        if (!seenSet[sNm]) {
          seenSet[sNm] = true;
          names.push(sNm);
        }
      }
    }
    names.sort(function (a, b) {
      return b.length - a.length;
    });

    var hits = [];
    var taken = new Array(text.length);
    for (var ni = 0; ni < names.length; ni++) {
      var nm = names[ni];
      var key = nfkc(nm).trim();
      var start = 0;
      while (key) {
        var pos = text.indexOf(key, start);
        if (pos < 0) break;
        var overlap = false;
        for (var k = pos; k < pos + key.length; k++) {
          if (taken[k]) {
            overlap = true;
            break;
          }
        }
        if (!overlap) {
          for (var k2 = pos; k2 < pos + key.length; k2++) taken[k2] = true;
          hits.push([pos, nm]);
          break;
        }
        start = pos + 1;
      }
    }
    var nfkcText = nfkc(text);
    if (nfkcText.length === taken.length) {
      var tokRe = /[\u4e00-\u9fff\u30a1-\u30f6A-Za-z0-9]{2,}/g;
      var tm;
      while ((tm = tokRe.exec(nfkcText)) !== null) {
        var ovT = false;
        for (var tk = tm.index; tk < tm.index + tm[0].length; tk++) {
          if (taken[tk]) { ovT = true; break; }
        }
        if (ovT) continue;
        var tok = tm[0].replace(/(?:別表|別|毎|列|欄)$/, "");
        if (tok.length < 2 || _COL_TOKEN_STOP_TOP[tok]) continue;
        var matched = [];
        for (var mi = 0; mi < names.length; mi++) {
          if (nfkc(names[mi]).indexOf(tok) >= 0) matched.push(names[mi]);
        }
        if (matched.length === 1) {
          var already = false;
          for (var hi0 = 0; hi0 < hits.length; hi0++) {
            if (hits[hi0][1] === matched[0]) { already = true; break; }
          }
          if (!already) {
            for (var tk2 = tm.index; tk2 < tm.index + tm[0].length; tk2++) taken[tk2] = true;
            hits.push([tm.index, matched[0]]);
          }
        }
      }
    }
    hits.sort(function (a, b) { return a[0] - b[0]; });
    var res = [];
    for (var hi = 0; hi < hits.length; hi++) res.push(hits[hi][1]);
    return res;
  }

  function _rangeOf(text) {
    var m = COLROWS_RE.exec(text);
    if (m) return m[1] + m[2] + ":" + m[1] + m[3];
    m = RANGE_RE.exec(text);
    if (m) return m[1] + ":" + m[2];
    m = CELL_RE.exec(text);
    if (m) return m[1];
    return null;
  }

  function _allExplicitRanges(text) {
    var spans = [];
    var m;
    COLROWS_RE.lastIndex = 0;
    if ((m = COLROWS_RE.exec(text)) !== null) {
      spans.push({ start: m.index, end: m.index + m[0].length, val: m[1] + m[2] + ":" + m[1] + m[3] });
    }
    RANGE_RE_G.lastIndex = 0;
    while ((m = RANGE_RE_G.exec(text)) !== null) {
      spans.push({ start: m.index, end: m.index + m[0].length, val: m[1] + ":" + m[2] });
    }
    CELL_RE_G.lastIndex = 0;
    while ((m = CELL_RE_G.exec(text)) !== null) {
      var overlap = false;
      for (var si = 0; si < spans.length; si++) {
        if (m.index >= spans[si].start && m.index < spans[si].end) {
          overlap = true;
          break;
        }
      }
      if (!overlap) spans.push({ start: m.index, end: m.index + m[0].length, val: m[1] });
    }
    spans.sort(function (a, b) { return a.start - b.start; });
    var out = [];
    for (var i = 0; i < spans.length; i++) out.push(spans[i].val);
    return out;
  }

  function _dataSpan(table) {
    if (!table || !table.data) return null;
    var parts = String(table.data).split("-");
    if (parts.length !== 2) return null;
    var a = parseInt(parts[0], 10);
    var b = parseInt(parts[1], 10);
    if (isNaN(a) || isNaN(b)) return null;
    return [a, b];
  }

  function _colRange(table, letters) {
    var sp = _dataSpan(table);
    if (!sp || !letters || !letters.length) return null;
    var a = sp[0], b = sp[1];
    if (letters.length === 1) return letters[0] + a + ":" + letters[0] + b;
    return letters[0] + a + ":" + letters[letters.length - 1] + b;
  }

  function _letterOf(table, name) {
    var res = _resolveColRefJs(name, table);
    if (!res) return null;
    if (/^[A-Z]{1,3}$/.test(res)) return res;
    if (!table || !table.columns) return null;
    for (var i = 0; i < table.columns.length; i++) {
      if (table.columns[i] && table.columns[i].name === res) {
        return table.columns[i].col || null;
      }
    }
    return null;
  }

  function _colorHits(text) {
    var out = [];
    var taken = new Array(text.length);
    var m;

    _HEX_COLOR_RE_G.lastIndex = 0;
    while ((m = _HEX_COLOR_RE_G.exec(text)) !== null) {
      for (var k = m.index; k < m.index + m[0].length; k++) taken[k] = true;
      out.push([m.index, m.index + m[0].length, m[0].toUpperCase()]);
    }

    for (var ci = 0; ci < _COLORS.length; ci++) {
      var word = _COLORS[ci][0];
      var val = _COLORS[ci][1];
      var start = 0;
      while (true) {
        var pos = text.indexOf(word, start);
        if (pos < 0) break;
        var overlap = false;
        for (var k2 = pos; k2 < pos + word.length; k2++) {
          if (taken[k2]) {
            overlap = true;
            break;
          }
        }
        if (!overlap) {
          for (var k3 = pos; k3 < pos + word.length; k3++) taken[k3] = true;
          out.push([pos, pos + word.length, val]);
        }
        start = pos + 1;
      }
    }

    _EN_COLOR_RE_G.lastIndex = 0;
    while ((m = _EN_COLOR_RE_G.exec(text)) !== null) {
      var ov = false;
      for (var k4 = m.index; k4 < m.index + m[0].length; k4++) {
        if (taken[k4]) {
          ov = true;
          break;
        }
      }
      if (!ov) {
        for (var k5 = m.index; k5 < m.index + m[0].length; k5++) taken[k5] = true;
        out.push([m.index, m.index + m[0].length, m[1].toLowerCase()]);
      }
    }

    out.sort(function (a, b) {
      if (a[0] !== b[0]) return a[0] - b[0];
      return a[1] - b[1];
    });
    return out;
  }

  function _quotes(text) {
    var out = [];
    var m;
    QUOTE_RE_G.lastIndex = 0;
    while ((m = QUOTE_RE_G.exec(text)) !== null) {
      var q = m[1].trim();
      if (q) out.push(q);
    }
    return out;
  }

  function _numbers(text) {
    var t = text.replace(RANGE_RE_G, " ");
    t = t.replace(CELL_RE_G, " ");
    t = t.replace(ROWSPAN_RE_G, " ");
    t = t.replace(ROW_RE_G, " ");
    t = t.replace(/[0-9]+列/g, " ");
    var out = [];
    var m;
    NUM_RE_G.lastIndex = 0;
    while ((m = NUM_RE_G.exec(t)) !== null) {
      var s = m[1];
      out.push(s.indexOf(".") >= 0 ? parseFloat(s) : parseInt(s, 10));
    }
    return out;
  }

  function _cast(a, v) {
    var t = a.type;
    if (t === "配列" && typeof v === "string") {
      var parts = v.split(/[・、,／/]/);
      var arr = [];
      for (var i = 0; i < parts.length; i++) {
        var x = parts[i].trim();
        if (x) arr.push(x);
      }
      return arr;
    }
    if (t === "数") {
      var raw = String(v).replace(/,/g, "").trim();
      if (!raw) return null;
      var f = Number(raw);
      return isFinite(f) ? f : null;
    }
    if (t === "真偽") {
      if (typeof v === "boolean") return v;
      var low = String(v).toLowerCase();
      return low === "true" || low === "1" || low === "yes";
    }
    if (t === "範囲" && typeof v === "string") {
      var m = RANGE_RE.exec(v);
      if (m) return m[1] + ":" + m[2];
    }
    if (t === "選択") {
      var s = String(v).toLowerCase();
      return (a.choices && a.choices.indexOf(s) >= 0) ? s : null;
    }
    if ((t === "列[]" || t === "行[]" || t === "配列") && !Array.isArray(v)) {
      if (t === "行[]") {
        var sv = String(v).trim();
        if (!/^-?[0-9]+$/.test(sv)) return null;
        return [parseInt(sv, 10)];
      }
      return [v];
    }
    return v;
  }

  // ------------------------------------------------------------------ 1節 → 1 op
  function buildOp(shelf, text, table, sheets, curSheet) {
    _ensureInit();
    if (typeof shelf === "string") {
      shelf = _byName[shelf];
    }
    var argsList = shelf.args || [];
    var argsMap = {};
    for (var ai = 0; ai < argsList.length; ai++) {
      argsMap[argsList[ai].name] = argsList[ai];
    }

    var op = { shelf: shelf.name };
    var quotes = _quotes(text);
    var origQuotesList = quotes.slice();
    var origQuotesMap = {};
    for (var oqi = 0; oqi < quotes.length; oqi++) origQuotesMap[quotes[oqi]] = true;
    var rules = shelf.ask_rules || [];

    for (var ri = 0; ri < rules.length; ri++) {
      var r = rules[ri];
      var a = argsMap[r.arg];
      if (!a || (_hasOwn(op, r.arg) && r.arg !== "cells")) continue;
      if (_hasOwn(r, "re")) {
        if (r.arg === "cells" && a.type === "対応") {
          var rgCells = new RegExp(r.re, "g");
          var gm;
          while ((gm = rgCells.exec(text)) !== null) {
            if (gm.length >= 3) {
              var objC = op.cells || {};
              var valStrC = gm[2].trim();
              objC[gm[1].trim()] = /^-?[0-9]+$/.test(valStrC) ? parseInt(valStrC, 10) : valStrC;
              op.cells = objC;
              for (var giC = 1; giC < gm.length; giC++) {
                if (gm[giC]) {
                  var gsC = gm[giC].trim();
                  var qIdxC = quotes.indexOf(gsC);
                  if (qIdxC >= 0) quotes.splice(qIdxC, 1);
                }
              }
            }
          }
          continue;
        }
        var rx = _rx(r.re);
        var m = rx.exec(text);
        if (m) {
          var v;
          if (a.type === "対応" && m.length >= 3) {
            var valStr = m[2].trim();
            var obj = {};
            obj[m[1].trim()] = /^-?[0-9]+$/.test(valStr) ? parseInt(valStr, 10) : valStr;
            v = obj;
          } else {
            v = _cast(a, m[1].trim());
          }
          if (!_isEmptyVal(v)) {
            op[r.arg] = v;
            for (var gi = 1; gi < m.length; gi++) {
              if (m[gi]) {
                var gs = m[gi].trim();
                var qIdx = quotes.indexOf(gs);
                if (qIdx >= 0) quotes.splice(qIdx, 1);
              }
            }
          }
        }
      } else if (r.words) {
        var matchedWord = false;
        for (var wi = 0; wi < r.words.length; wi++) {
          if (text.indexOf(r.words[wi]) >= 0) {
            matchedWord = true;
            break;
          }
        }
        if (matchedWord) {
          var wv = r.value;
          op[r.arg] = (a.type === "対応" || a.type === "配列" || a.type === "表") ? wv : _cast(a, wv);
        }
      }
    }

    var scan = text.replace(QUOTE_RE_G, " ");
    scan = scan.replace(PAREN_RE_G, " ");
    var colorHits = _colorHits(scan);
    scan = scan.replace(_HEX_COLOR_RE_G, " ");

    var hasSheetArg = false;
    for (var hsa = 0; hsa < argsList.length; hsa++) {
      if (argsList[hsa].type === "シート") { hasSheetArg = true; break; }
    }
    var rawSheets = Array.isArray(sheets) ? sheets.slice() : [];
    rawSheets.sort(function (a, b) {
      return String(b).length - String(a).length;
    });
    var sheetHits = [];
    var nfkcScan = nfkc(scan);
    for (var si = 0; si < rawSheets.length; si++) {
      var sn = rawSheets[si];
      if (!sn) continue;
      var snN = nfkc(String(sn));
      var escSn = snN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      var explicitShRe = new RegExp("(?:シート|タブ)\\s*の?\\s*[「『]?" + escSn + "[」』]?|" + escSn + "\\s*の?\\s*(?:シート|タブ)", "g");
      if (explicitShRe.test(nfkcScan)) {
        sheetHits.push(sn);
        explicitShRe.lastIndex = 0;
        nfkcScan = nfkcScan.replace(explicitShRe, " ");
        scan = nfkc(scan).replace(explicitShRe, " ");
      } else if (hasSheetArg && nfkcScan.indexOf(snN) >= 0) {
        sheetHits.push(sn);
        nfkcScan = nfkcScan.split(snN).join(" ");
        scan = nfkc(scan).split(snN).join(" ");
      }
    }

    var names = _colNames(scan, table);
    var letters = _colLetters(scan);
    var explicitRanges = _allExplicitRanges(scan);
    var explicitRange = explicitRanges.length ? explicitRanges[0] : null;
    var remRanges = explicitRanges.slice();
    var hasFromToRanges = !!(argsMap.from && argsMap.from.type === "範囲" && argsMap.to && argsMap.to.type === "範囲");
    var rows = _rowsOf(scan);
    var nums = _numbers(scan);
    var named = !!(
      explicitRange ||
      rows.length ||
      letters.length ||
      names.length ||
      sheetHits.length ||
      shelf.name === "dedupe" ||
      shelf.name === "seiri" ||
      shelf.name === "blank.rows.delete"
    );

    var anyList = shelf.any || [];
    var needMap = {};
    for (var ni = 0; ni < argsList.length; ni++) {
      if (argsList[ni].req) needMap[argsList[ni].name] = true;
    }
    for (var anyI = 0; anyI < anyList.length; anyI++) {
      needMap[anyList[anyI]] = true;
    }

    var nameLetters = {};
    for (var nli = 0; nli < names.length; nli++) {
      var nl = _letterOf(table, names[nli]);
      if (nl) nameLetters[nl] = true;
    }
    var colPool = names.slice();
    for (var li = 0; li < letters.length; li++) {
      if (!nameLetters[letters[li]]) colPool.push(letters[li]);
    }

    var rangeGiven = false;

    // 色: 引数が 1 つならそれ。2 つ以上なら 背景／文字 の文脈で振り分け
    var allColorArgs = [];
    var colorArgs = [];
    for (var cai = 0; cai < argsList.length; cai++) {
      if (argsList[cai].type === "色") {
        allColorArgs.push(argsList[cai].name);
        if (!_hasOwn(op, argsList[cai].name)) {
          colorArgs.push(argsList[cai].name);
        }
      }
    }
    if (colorHits.length && colorArgs.length) {
      if (allColorArgs.length === 1) {
        op[colorArgs[0]] = colorHits[0][2];
      } else {
        var prevEnd = 0;
        for (var chi = 0; chi < colorHits.length; chi++) {
          var pos = colorHits[chi][0];
          var end = colorHits[chi][1];
          var cval = colorHits[chi][2];
          var ctx = scan.slice(prevEnd, pos);
          var after = scan.slice(end, end + 6);
          prevEnd = end;

          var fgI = -1;
          for (var fki = 0; fki < FG_COLOR_KEYS.length; fki++) {
            var idxF = ctx.lastIndexOf(FG_COLOR_KEYS[fki]);
            if (idxF > fgI) fgI = idxF;
          }
          var bgI = -1;
          for (var bki = 0; bki < BG_COLOR_KEYS.length; bki++) {
            var idxB = ctx.lastIndexOf(BG_COLOR_KEYS[bki]);
            if (idxB > bgI) bgI = idxB;
          }

          var targetK;
          if (FG_AFTER_RE.test(after)) {
            targetK = "color";
          } else if (BG_AFTER_RE.test(after)) {
            targetK = "bg";
          } else if (fgI > bgI) {
            targetK = "color";
          } else if (bgI > fgI) {
            targetK = "bg";
          } else if (colorHits.length === 1) {
            var hasFgWord = false;
            for (var fwi = 0; fwi < FG_COLOR_KEYS.length; fwi++) {
              if (text.indexOf(FG_COLOR_KEYS[fwi]) >= 0) {
                hasFgWord = true;
                break;
              }
            }
            // タイトルの色はたいてい文字の色（「背景」「塗り」と言ったときだけ背景）。見出しの行・範囲は今までどおり背景
            var saysBg = /背景|塗/.test(text);
            var isTitleAsk = /タイトル|表題|題名/.test(text) && !/見出し|ヘッダ/.test(text);
            targetK = ((hasFgWord || isTitleAsk) && !saysBg) ? "color" : "bg";
          } else {
            targetK = (colorArgs.indexOf("bg") >= 0 && !_hasOwn(op, "bg")) ? "bg" : "color";
          }

          if (colorArgs.indexOf(targetK) >= 0 && !_hasOwn(op, targetK)) {
            op[targetK] = cval;
          } else if (
            colorHits.length === 1 &&
            colorArgs.length &&
            !_hasOwn(op, colorArgs[0]) &&
            allColorArgs.length === colorArgs.length
          ) {
            op[colorArgs[0]] = cval;
          }
        }
      }
    }

    var hasColArg = false;
    for (var hci = 0; hci < argsList.length; hci++) {
      if (argsList[hci].type === "列") {
        hasColArg = true;
        break;
      }
    }

    var reqTextFilled = false;
    var hasAnyFilled = function () {
      for (var i = 0; i < anyList.length; i++) {
        if (!_isEmptyVal(op[anyList[i]])) return true;
      }
      return false;
    };

    for (var xi = 0; xi < argsList.length; xi++) {
      var arg = argsList[xi];
      var k = arg.name;
      var t = arg.type;
      if (_hasOwn(op, k)) {
        if (t === "範囲") rangeGiven = true;
        continue;
      }
      var wanted = !!needMap[k];
      var av = null;
      if (t === "範囲") {
        if (hasFromToRanges && (k === "from" || k === "to") && remRanges.length) {
          av = remRanges.shift();
        } else if (rangeGiven || (!wanted && hasAnyFilled())) {
          // 既に範囲または「どれか」が埋まっている場合はスキップ
        } else if (explicitRange) {
          av = explicitRange;
        } else if (wanted && (shelf.name === "clear.all" || shelf.name === "cf.dup") && table) {
          var firstR = table.data ? String(table.data).split("-")[0] : String((table.header_row || 1) + 1);
          var lastR = table.data ? String(table.data).split("-").slice(-1)[0] : String((table.header_row || 1) + 1);
          av = table.first_col + firstR + ":" + table.last_col + lastR;
        } else if (colPool.length && (wanted || !hasColArg)) {
          var ls = [];
          for (var cpi = 0; cpi < colPool.length; cpi++) {
            var cp = colPool[cpi];
            var clt = _letterOf(table, cp) || (/^[A-Z]{1,3}$/.test(cp) ? cp : null);
            if (clt) ls.push(clt);
          }
          av = _colRange(table, ls);
        }
        if (av) rangeGiven = true;
      } else if (t === "列") {
        if (k === "at" && !arg.req && !/(?:列|欄)[にへ]|の間に/.test(text)) {
          // 任意 at に計算入力列等を勝手に入れない
        } else if (shelf.name === "calc.col" && k === "at") {
          // calc.col の at は専用解析で決める
        } else if (colPool.length && !(anyList.indexOf(k) >= 0 && hasAnyFilled())) {
          av = colPool.shift();
        }
      } else if (t === "列[]") {
        if (colPool.length) {
          av = colPool.slice();
          colPool = [];
        }
      } else if (t === "行[]") {
        if (rows.length) av = rows;
      } else if (t === "配列") {
        if (quotes.length && (wanted || _isEmptyVal(op[k]))) {
          av = quotes.slice();
          quotes = [];
        }
      } else if (t === "シート") {
        if (sheetHits.length) {
          av = sheetHits.shift();
        } else if (wanted && curSheet && CUR_SHEET_RE.test(text)) {
          av = curSheet;
        } else if (wanted && quotes.length) {
          av = quotes.shift();
        }
      } else if (t === "文字") {
        if (quotes.length && (wanted || reqTextFilled)) {
          av = quotes.shift();
          reqTextFilled = reqTextFilled || wanted;
        }
      } else if (t === "数") {
        if (wanted && nums.length === 1) {
          av = nums[0];
        }
      }
      if (!_isEmptyVal(av)) {
        op[k] = av;
      }
    }

    if (sheetHits.length && shelf.kind === "sheet" && !shelf.shared && !_hasOwn(op, "sheet")) {
      op.sheet = sheetHits[0];
    }

    if (shelf.name === "format" && _hasOwn(op, "borders") && !_hasOwn(op, "range") && !_hasOwn(op, "col") && !op.header && !op.title && table && table.first_col && table.last_col) {
      var fmtFirstR = table.header_row || 1;
      var fmtLastR = table.total_row || (table.data ? String(table.data).split("-").slice(-1)[0] : fmtFirstR);
      op.range = table.first_col + fmtFirstR + ":" + table.last_col + fmtLastR;
    }
    if (shelf.name === "format") {
      // 連続する複数列が列挙された書式設定（例: 予算額・実績額・差異に3桁カンマ）を範囲へ統合
      if (_hasOwn(op, "col") && colPool.length && !_hasOwn(op, "range") && table) {
        var firstL = _letterOf(table, op.col) || (/^[A-Z]{1,3}$/.test(op.col) ? op.col : "");
        var seqLs = firstL ? [firstL] : [];
        for (var fci = 0; fci < colPool.length; fci++) {
          var fl = _letterOf(table, colPool[fci]) || (/^[A-Z]{1,3}$/.test(colPool[fci]) ? colPool[fci] : "");
          if (fl) seqLs.push(fl);
        }
        if (seqLs.length >= 2) {
          var numsLs = seqLs.map(_colNum).sort(function (a, b) { return a - b; });
          var contig = true;
          for (var cki2 = 1; cki2 < numsLs.length; cki2++) {
            if (numsLs[cki2] - numsLs[cki2 - 1] > 1) { contig = false; break; }
          }
          if (contig) {
            var spanRg = _colRange(table, [_colLetter(numsLs[0]), _colLetter(numsLs[numsLs.length - 1])]);
            if (spanRg) {
              op.range = spanRg;
              delete op.col;
            }
          }
        }
      }
      // 表示形式の自然文詳細補正
      if (/(?:数値\s*[（(]?標準[）)]?|表示形式を標準|標準形式|標準に戻)/.test(text)) {
        op.number_format = "General";
      } else if (/(?:hh:mm|09:00|時刻.{0,4}2桁|2桁.{0,4}時刻|時分形式)/i.test(text)) {
        op.number_format = "hh:mm";
      } else if (/(?:yyyy\/mm\/dd|2026\/11\/04|スラッシュ.{0,4}日付|年\/月\/日|年月日の?形|年月日形式|年月日に)/i.test(text)) {
        op.number_format = "yyyy/mm/dd";
      } else if (op.number_format === 'm"月"d"日"(ddd)' && /(?:年|yyyy)/i.test(text)) {
        op.number_format = "yyyy/mm/dd(ddd)";
      } else if (!op.number_format && /(?:パーセント|%\s*表示)/.test(text)) {
        op.number_format = "0.0%";
      } else if (!op.number_format && /(?:3桁|桁区切|カンマ)/.test(text)) {
        op.number_format = "#,##0";
      }
      if (!_hasOwn(op, "size") && !_hasOwn(op, "size_delta") && !/(?:幅|高さ|列幅|行高|行|列)を(?:大きく|小さく)/.test(nfkc(scan))) {
        var stepSz = /もっと|だいぶ|かなり|ぐっと|大幅に/.test(nfkc(scan)) ? 4 : 2;
        if (/(?<!より)大きく|拡大して/.test(nfkc(scan))) op.size_delta = stepSz;
        else if (/(?<!より)小さく|縮小して/.test(nfkc(scan))) op.size_delta = -stepSz;
      }
    }
    if (shelf.name === "validation.list") {
      var cleanedValItems = _cleanValidationItemsJs(text, origQuotesList, op.items);
      if (cleanedValItems && cleanedValItems.length) op.items = cleanedValItems;
    }
    var _COL_TOKEN_STOP_JS = {
      "集計": 1, "合計": 1, "平均": 1, "件数": 1, "人数": 1, "グラフ": 1, "ピボット": 1, "クロス": 1, "シート": 1, "別シート": 1,
      "データ": 1, "テーブル": 1, "一覧": 1, "全部": 1, "全体": 1, "全て": 1, "行全体": 1, "条件": 1, "書式": 1, "表示": 1, "形式": 1,
      "作成": 1, "追加": 1, "変更": 1, "削除": 1, "抽出": 1, "固定": 1, "並べ": 1, "整理": 1, "自動": 1, "調整": 1, "内容": 1, "中身": 1,
      "範囲": 1, "セル": 1, "タイトル": 1, "見出し": 1, "ヘッダ": 1, "合計行": 1, "標準": 1, "棒グラフ": 1, "折れ線": 1, "円グラフ": 1,
      "新しい": 1, "別表": 1, "結果": 1, "計算": 1, "数式": 1
    };

    function _hasNumberMetaJs(tbl) {
      var cols = (tbl && tbl.columns) || [];
      for (var i = 0; i < cols.length; i++) {
        if (cols[i] && cols[i].number) return true;
      }
      return false;
    }

    function _isNumberColJs(tbl, colRef) {
      var res = _resolveColRefJs(colRef, tbl);
      if (!res) return false;
      var cols = (tbl && tbl.columns) || [];
      for (var i = 0; i < cols.length; i++) {
        if (cols[i] && (cols[i].name === res || cols[i].col === res)) return !!cols[i].number;
      }
      return false;
    }

    function _resolveUniqueColsJs(txt, tbl, numberOnly, excludeArr) {
      if (!tbl || !Array.isArray(tbl.columns)) return [];
      var excl = {};
      var exList = excludeArr || [];
      for (var ei = 0; ei < exList.length; ei++) excl[exList[ei]] = true;
      var cands = [];
      var allNames = [];
      for (var i = 0; i < tbl.columns.length; i++) {
        var nm = String((tbl.columns[i] && tbl.columns[i].name) || "").trim();
        if (!nm) continue;
        if (allNames.indexOf(nm) < 0) allNames.push(nm);
        if (excl[nm]) continue;
        if (numberOnly && !tbl.columns[i].number) continue;
        cands.push(nm);
      }
      if (!cands.length) return [];
      var work = nfkc(txt);
      allNames.sort(function (a, b) { return b.length - a.length; });
      for (var ai2 = 0; ai2 < allNames.length; ai2++) {
        if (excl[allNames[ai2]]) work = work.split(allNames[ai2]).join(" ");
      }
      var out = [];
      var tokRe = /[\u4e00-\u9fff\u30a1-\u30f6A-Za-z0-9]{2,}/g;
      var tm;
      while ((tm = tokRe.exec(work)) !== null) {
        var tok = tm[0].replace(/(?:別表|別|毎|列|欄)$/, "");
        if (tok.length < 2 || _COL_TOKEN_STOP_JS[tok] || excl[tok]) continue;
        var hits = [];
        for (var ci2 = 0; ci2 < cands.length; ci2++) {
          if (cands[ci2].indexOf(tok) >= 0) hits.push(cands[ci2]);
        }
        if (hits.length === 1 && out.indexOf(hits[0]) < 0) out.push(hits[0]);
      }
      return out;
    }

    function _singleNumericFallbackJs(tbl, excludeArr) {
      if (!tbl || !_hasNumberMetaJs(tbl)) return null;
      var excl = {};
      var exList = excludeArr || [];
      for (var ei = 0; ei < exList.length; ei++) excl[exList[ei]] = true;
      var numsList = [];
      for (var i = 0; i < tbl.columns.length; i++) {
        var c0 = tbl.columns[i];
        var nm = String((c0 && c0.name) || "").trim();
        if (c0 && c0.number && nm && !excl[nm] && !/^(?:no\.?|番号|id)$/i.test(nm)) {
          numsList.push(nm);
        }
      }
      return numsList.length === 1 ? numsList[0] : null;
    }

    function _normFilterNumJs(val) {
      if (val === undefined || val === null) return null;
      var s = nfkc(String(val)).replace(/,/g, "").trim();
      if (!s) return null;
      var isPct = s.slice(-1) === "%";
      if (isPct) s = s.slice(0, -1).trim();
      var mul = 1;
      if (s.slice(-1) === "万") { mul = 10000; s = s.slice(0, -1).trim(); }
      else if (s.slice(-1) === "億") { mul = 100000000; s = s.slice(0, -1).trim(); }
      if (!s || isNaN(Number(s))) return null;
      var num = Number(s) * mul;
      if (isPct) num = num / 100.0;
      return String(num);
    }

    function _cleanFilterEqualsJs(opObj, txt, tbl, qMap) {
      if (typeof opObj.equals !== "string") return;
      var eqS = opObj.equals.trim();
      var isQuoted = !!qMap[eqS];
      if (!isQuoted) {
        var colsAll = [];
        var tCols = (tbl && tbl.columns) || [];
        for (var i = 0; i < tCols.length; i++) {
          var cn = String((tCols[i] && tCols[i].name) || "").trim();
          if (cn) colsAll.push(cn);
        }
        var mGa = /^([^\s、。]+?)(?:列)?(?:が|は)(.+)$/.exec(eqS);
        if (mGa) {
          var lhs = mGa[1].trim(), rhs = mGa[2].trim();
          var resCol = _resolveColRefJs(lhs, tbl);
          if (resCol && rhs) {
            if (!_hasOwn(opObj, "col")) opObj.col = resCol;
            eqS = rhs;
          } else {
            delete opObj.equals;
            return;
          }
        }
        if (opObj.col && typeof opObj.col === "string") {
          var colNm = opObj.col.trim();
          if (colNm && eqS.indexOf(colNm) === 0 && eqS.length > colNm.length) {
            var rest = eqS.slice(colNm.length).replace(/^(?:列)?(?:が|は)/, "").trim();
            if (rest) eqS = rest;
          }
        }
        eqS = eqS.replace(/(?:さん|様)$/, "").trim();
        if (!eqS || colsAll.indexOf(eqS) >= 0 || /(?:が|は)/.test(eqS) || /以上|以下|未満|より大|より小|を超|超え|を含|含む|以外|ではな|でない|空白|空欄/.test(eqS)) {
          delete opObj.equals;
          return;
        }
      }
      opObj.equals = eqS;
    }

    function _auditBuiltOpJs(shObj, opObj, txt, scanTxt, tbl, cHits, missArr) {
      var shN = shObj.name;
      var scanN = nfkc(scanTxt);
      var addMiss = function (msg) {
        if (missArr.indexOf(msg) < 0) missArr.push(msg);
      };
      var hasSizeCue = /(?<!より)(?:大きく|小さく)|文字サイズ|フォントサイズ|(?<![0-9])サイズを(?:変え|上げ|下げ|大きく|小さく|拡大|縮小)|拡大して|縮小して/.test(scanN);
      var isDimSize = /(?:幅|高さ|列幅|行高|行|列)を(?:大きく|小さく)/.test(scanN);
      if (hasSizeCue && (!isDimSize || /文字|フォント/.test(scanN))) {
        if (!(shN === "width" && !/文字|フォント/.test(scanN)) && (opObj.size === undefined || opObj.size === null) && (opObj.size_delta === undefined || opObj.size_delta === null)) {
          addMiss("サイズ（具体的な数値 pt）");
        }
      }
      if (_ADD_SHELVES_JS[shN] && /外し|外す|解除|やめ|なくし|無くし|消して|消す|削除|クリア/.test(scanN)) {
        addMiss("逆の操作（外す・消す・解除）の語が含まれています");
      }
      if (/下線|アンダーライン|取り消し線|打ち消し線|取消線|縦書き|斜め文字|文字を回転|テキストを回転/.test(scanN)) {
        addMiss("未対応の書式指示（下線・取り消し線・回転等）");
      }
      if (shN === "format") {
        var hasRowCond = /[^\s、。]+?(?:が|は)[^\s、。の]+?の行/.test(scanN) ||
          /(?:以上|以下|未満|より大き|より小さ|を超|超え|マイナス|負の値|空欄|空白|以外|ではない|になってない).{0,8}(?:の行|行を|行に|行全体|のセル|セルを)/.test(scanN);
        if (hasRowCond) addMiss("条件付き書式（cf.add）の条件");
        if (/固定|フリーズ/.test(scanN)) addMiss("固定（freeze）の指定");
        if (/並べ替|ソート/.test(scanN)) addMiss("並べ替え（sort）の指定");
        if (/フィルタ|絞り込/.test(scanN)) addMiss("絞り込み（filter）の指定");
        if (scanN.indexOf("太字") >= 0 && !_hasOwn(opObj, "bold")) addMiss("太字（bold）");
        if (/斜体|イタリック/.test(scanN) && !_hasOwn(opObj, "italic")) addMiss("斜体（italic）");
        if (/中央揃え|中央寄せ|右揃え|右寄せ|左揃え|左寄せ/.test(scanN) && !_hasOwn(opObj, "align")) addMiss("配置（align）");
        if (scanN.indexOf("折り返") >= 0 && !_hasOwn(opObj, "wrap")) addMiss("折り返し（wrap）");
        if (/罫線|外枠/.test(scanN) && !_hasOwn(opObj, "borders")) addMiss("罫線（borders）");
        if (/結合|マージ/.test(scanN) && !_hasOwn(opObj, "merge")) addMiss("結合（merge）");
        if (/二重線|点線|破線/.test(scanN)) addMiss("罫線の種類（formatは実線のみ）");
        if (/(?:パーセント|%\s*表示|桁区切|カンマ区切|通貨形式|円マーク|年月日の?形|年月日形式|yyyy|hh:mm|曜日)/i.test(scanN) && !_hasOwn(opObj, "number_format")) {
          addMiss("表示形式（number_format）");
        }
        if (cHits.length && !opObj.bg && !opObj.color) addMiss("色（color/bg）");
      }
      if (shN === "filter.where" || shN === "filter.delete" || shN === "filter.extract") {
        if (/以上|以下|未満|より大|より小|を超|超え|を含|含む|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄/.test(scanN) && !opObj.when) {
          addMiss("条件（when）");
        }
        if (!opObj.when && _isEmptyVal(opObj.equals) && _isEmptyVal(opObj.value)) {
          addMiss("絞り込み条件（equals/when）");
        }
        if ((opObj.when === "gt" || opObj.when === "ge" || opObj.when === "lt" || opObj.when === "le" || opObj.when === "ne") && _isEmptyVal(opObj.value)) {
          addMiss("value");
        }
      }
      if (_FORMULA_COL_SHELVES_JS[shN] && opObj.at) {
        var dstCol = opObj.at;
        var dstL = _letterOf(tbl, dstCol) || dstCol;
        var srcRefs = {};
        if (shN === "calc.col" && opObj.expr) {
          srcRefs = _exprReferencedColsJs(opObj.expr, tbl);
        } else {
          var sKeys = ["col", "col_a", "col_b", "start_col", "end_col"];
          for (var ski = 0; ski < sKeys.length; ski++) {
            var sv = opObj[sKeys[ski]];
            if (sv) {
              srcRefs[sv] = true;
              var sl0 = _letterOf(tbl, sv);
              if (sl0) srcRefs[sl0] = true;
            }
          }
          if (Array.isArray(opObj.cols)) {
            for (var sci0 = 0; sci0 < opObj.cols.length; sci0++) {
              var scv = opObj.cols[sci0];
              srcRefs[scv] = true;
              var sl1 = _letterOf(tbl, scv);
              if (sl1) srcRefs[sl1] = true;
            }
          }
        }
        if (srcRefs[dstCol] || srcRefs[dstL]) {
          addMiss("入れ先の列「" + dstCol + "」が式の入力列と同じため上書き不可");
        }
      }
      // 6. 最終防波堤: 組んだ op の列引数・式に表に無い列名が残っていれば撃たない
      if (tbl && Array.isArray(tbl.columns) && tbl.columns.length) {
        var validNames = {}, validLetters = {};
        for (var vi0 = 0; vi0 < tbl.columns.length; vi0++) {
          var vnm = String((tbl.columns[vi0] && tbl.columns[vi0].name) || "").trim();
          var vcl = String((tbl.columns[vi0] && tbl.columns[vi0].col) || "").trim();
          if (vnm) validNames[vnm] = true;
          if (vcl) validLetters[vcl] = true;
        }
        var isValidColVal = function (v, allowAnyLetter) {
          var sv = nfkc(String(v === null || v === undefined ? "" : v)).trim();
          if (!sv) return false;
          if (validNames[sv] || validLetters[sv]) return true;
          if (allowAnyLetter && /^[A-Z]{1,3}$/.test(sv)) return true;
          return false;
        };
        var shArgs = shObj.args || [];
        for (var ai3 = 0; ai3 < shArgs.length; ai3++) {
          var ak = shArgs[ai3].name, at = shArgs[ai3].type;
          if (!_hasOwn(opObj, ak) || _SKIP_COL_VALIDATE_JS[shN + ":" + ak]) continue;
          var allowLet = (ak === "at" || ak === "from" || ak === "to");
          if (at === "列") {
            if (!isValidColVal(opObj[ak], allowLet)) addMiss("表に無い列名（" + opObj[ak] + "）");
          } else if (at === "列[]") {
            var arrV = Array.isArray(opObj[ak]) ? opObj[ak] : [opObj[ak]];
            for (var avi = 0; avi < arrV.length; avi++) {
              if (!isValidColVal(arrV[avi], allowLet)) addMiss("表に無い列名（" + arrV[avi] + "）");
            }
          }
        }
        if (shN === "sort" && Array.isArray(opObj.cols)) {
          for (var si3 = 0; si3 < opObj.cols.length; si3++) {
            var sSpec = String(opObj.cols[si3]);
            var sBody = sSpec.charAt(0) === "-" ? sSpec.slice(1) : sSpec;
            if (!isValidColVal(sBody, false)) addMiss("表に無い列名（" + sBody + "）");
          }
        }
        if (shN === "calc.col" && opObj.expr) {
          var eToks = nfkc(String(opObj.expr)).split(/[*/+\-()]/);
          for (var eti = 0; eti < eToks.length; eti++) {
            var stE = eToks[eti].trim();
            if (!stE || /^-?[0-9]+(?:\.[0-9]+)?$/.test(stE)) continue;
            if (!isValidColVal(stE, false)) addMiss("式に表に無い列名（" + stE + "）");
          }
        }
      }
      // 7. % 列の 1 超え比較防止 ＋ 過半数・全行削除防止
      if (_CMP_VALUE_SHELVES_JS[shN]) {
        var cmpCol = opObj.col;
        var cmpNumStr = null;
        if (shN === "cf.add" && opObj.when === "formula" && typeof opObj.value === "string") {
          var mFm = /\$([A-Z]{1,3})[0-9]+\s*(?:>=|<=|<>|>|<|=)\s*(-?[0-9]+(?:\.[0-9]+)?)/.exec(opObj.value);
          if (mFm) {
            var fmColL = mFm[1];
            cmpNumStr = mFm[2];
            var fmCols = (tbl && tbl.columns) || [];
            for (var fmi = 0; fmi < fmCols.length; fmi++) {
              if (fmCols[fmi] && fmCols[fmi].col === fmColL && fmCols[fmi].name) { cmpCol = fmCols[fmi].name; break; }
            }
          }
        } else if ((opObj.when === "gt" || opObj.when === "ge" || opObj.when === "lt" || opObj.when === "le" || opObj.when === "eq" || opObj.when === "ne") && !_isEmptyVal(opObj.value)) {
          cmpNumStr = String(opObj.value).replace(/,/g, "").trim();
        }
        if (!cmpCol && shN === "cf.add" && typeof opObj.range === "string" && tbl && tbl.columns) {
          var mRgC = /^([A-Z]{1,3})[0-9]+:\1[0-9]+$/.exec(opObj.range);
          if (mRgC) {
            for (var rgi = 0; rgi < tbl.columns.length; rgi++) {
              if (tbl.columns[rgi] && tbl.columns[rgi].col === mRgC[1] && tbl.columns[rgi].name) { cmpCol = tbl.columns[rgi].name; break; }
            }
          }
        }
        if (cmpCol && _PCT_COL_RE_JS.test(String(cmpCol)) && cmpNumStr !== null && cmpNumStr !== "" && !isNaN(Number(cmpNumStr))) {
          if (Math.abs(Number(cmpNumStr)) > 1.0) {
            addMiss("%列「" + cmpCol + "」を1を超える値（" + cmpNumStr + "）で比較しているため確認が必要");
          }
        }
        if (shN === "filter.delete" && tbl && Array.isArray(tbl.rows) && tbl.rows.length && opObj.col) {
          var delCols = tbl.columns || [];
          var delIdx = -1;
          for (var dci0 = 0; dci0 < delCols.length; dci0++) {
            if (delCols[dci0] && (delCols[dci0].name === opObj.col || delCols[dci0].col === opObj.col)) { delIdx = dci0; break; }
          }
          if (delIdx >= 0) {
            var totalR = tbl.rows.length, hitsR = 0;
            var tgtV = opObj.value !== undefined ? opObj.value : opObj.equals;
            for (var dri = 0; dri < totalR; dri++) {
              var rowD = tbl.rows[dri];
              if (Array.isArray(rowD) && delIdx < rowD.length && _matchRowCondJs(rowD[delIdx], opObj.when || "eq", tgtV)) hitsR++;
            }
            if (hitsR > 0 && (hitsR === totalR || hitsR * 2 > totalR)) {
              addMiss("条件に合う行が過半数（" + hitsR + "/" + totalR + "行）のため確認が必要");
            }
          }
        }
      }
    }

    if (_CMP_VALUE_SHELVES_JS[shelf.name] && op.when !== "formula") {
      _resolveCmpValueJs(op, text);
    }
    if (shelf.name === "cf.add" && op.when !== "formula" && table && table.first_col && table.last_col) {
      if (/(?:行全体|の行(?:に|を|全部|だけ)|行に色|行を目立|行を(?:赤|黄|青|緑|黒|白|薄|濃|橙|灰|紫|水色|紺|茶|桃)|いない行|ない行)/.test(text)) {
        var spCf = _dataSpan(table);
        var cfR1 = spCf ? spCf[0] : ((table.header_row || 1) + 1);
        var cfR2 = spCf ? spCf[1] : cfR1;
        var refL = (names.length && _letterOf(table, names[0])) || (letters.length ? letters[0] : "");
        if (!refL) {
          var uCf = _resolveUniqueColsJs(scan, table, false, []);
          if (uCf.length) refL = _letterOf(table, uCf[0]) || "";
        }
        var expr = "";
        var rawVCf = op.value;
        var normVCf = !_isEmptyVal(rawVCf) ? _normFilterNumJs(rawVCf) : null;
        var numVal = normVCf !== null ? normVCf : ((rawVCf !== undefined && rawVCf !== null) ? String(rawVCf).replace(/,/g, "") : "");
        if (refL) {
          if (op.when === "ge" && numVal !== "") expr = "=$" + refL + cfR1 + ">=" + numVal;
          else if (op.when === "le" && numVal !== "") expr = "=$" + refL + cfR1 + "<=" + numVal;
          else if (op.when === "gt" && numVal !== "") expr = "=$" + refL + cfR1 + ">" + numVal;
          else if (op.when === "lt" && numVal !== "") expr = "=$" + refL + cfR1 + "<" + numVal;
          else if (op.when === "ne" && !_isEmptyVal(rawVCf)) {
            if (normVCf !== null) expr = "=$" + refL + cfR1 + "<>" + normVCf;
            else expr = "=$" + refL + cfR1 + "<>\"" + String(rawVCf).replace(/"/g, "\"\"") + "\"";
          } else if (/マイナス|負の値/.test(text)) expr = "=$" + refL + cfR1 + "<0";
          else if (/([0-9][0-9,\.]*%?[万億]?)(?:になっていない|になってない|ではない|でない|じゃない|以外)/.test(nfkc(text))) {
            var mNot = /([0-9][0-9,\.]*%?[万億]?)(?:になっていない|になってない|ではない|でない|じゃない|以外)/.exec(nfkc(text));
            var nvNot = _normFilterNumJs(mNot[1]) || mNot[1];
            expr = "=$" + refL + cfR1 + "<>" + nvNot;
          } else if (op.when === "contains" && !_isEmptyVal(rawVCf)) {
            expr = "=ISNUMBER(SEARCH(\"" + String(rawVCf).replace(/"/g, "\"\"") + "\",$" + refL + cfR1 + "))";
          } else if (op.when === "eq" && !_isEmptyVal(rawVCf)) {
            if (normVCf !== null) expr = "=$" + refL + cfR1 + "=" + normVCf;
            else expr = "=$" + refL + cfR1 + "=\"" + String(rawVCf).replace(/"/g, "\"\"") + "\"";
          } else if (!op.when) {
            var mEqRow = /([^\s、。]+?)(?:が|は)[『「]?([^』」\s、。の]+?)[』」]?の行/.exec(nfkc(text));
            if (mEqRow) {
              var rvEq = mEqRow[2].trim();
              var nvEq = _normFilterNumJs(rvEq);
              if (nvEq !== null) expr = "=$" + refL + cfR1 + "=" + nvEq;
              else expr = "=$" + refL + cfR1 + "=\"" + rvEq.replace(/"/g, "\"\"") + "\"";
            } else if (!_isEmptyVal(rawVCf)) {
              expr = "=ISNUMBER(SEARCH(\"" + String(rawVCf).replace(/"/g, "\"\"") + "\",$" + refL + cfR1 + "))";
            }
          }
        } else if (/欠席|完了|未完了|終了/.test(text)) {
          var kwCf = /欠席/.test(text) ? "欠席" : (/未完了/.test(text) ? "未完了" : (/完了/.test(text) ? "完了" : "終了"));
          expr = "=COUNTIF($" + table.first_col + cfR1 + ":$" + table.last_col + cfR1 + ",\"*" + kwCf + "*\")>0";
        }
        if (expr) {
          op.range = table.first_col + cfR1 + ":" + table.last_col + cfR2;
          op.when = "formula";
          op.value = expr;
          named = true;
        }
      }
      if (!op.bg && !op.color && /(?:色[を]?付|色[を]?つ|目立)/.test(text)) {
        op.bg = "薄黄";
      }
    }
    if (shelf.name === "renumber" && !_hasOwn(op, "col") && table && Array.isArray(table.columns)) {
      for (var rci = 0; rci < table.columns.length; rci++) {
        var rColNm = String((table.columns[rci] && table.columns[rci].name) || "");
        if (/^(?:no|番号|連番|項番|id)$/i.test(rColNm.trim())) {
          op.col = rColNm;
          named = true;
          break;
        }
      }
    }
    if (shelf.name === "sheet.rename" && !_hasOwn(op, "name") && _hasOwn(op, "to") && curSheet) {
      op.name = curSheet;
    }
    if (shelf.name === "table.new") {
      if (!/合計|総計|小計/.test(text)) delete op.total;
      if (!/連番|通し番号/.test(text)) delete op.number;
      if (!op.headers || !op.headers.length) {
        var hdrSrc = text.trim().replace(/^.*?(?:シート|タブ)[にへで]\s*/, "").replace(/^.*?(?:見出し|項目|列)[がはを]\s*/, "");
        var mHdr = /([^\s、,。・をに]{1,16}(?:\s*(?:[・、,]|と)\s*[^\s、,。・をに]{1,16})+)の(?:表|テーブル|名簿|一覧表)/.exec(hdrSrc);
        if (mHdr) {
          op.headers = mHdr[1].split(/[・、,／/]|と/).map(function (h) { return h.trim(); }).filter(function (h) { return h; });
        }
      }
      if (Array.isArray(op.headers) && op.headers.some(function (x) { return String(x).indexOf("と") >= 0; })) {
        var flatHdr = [];
        for (var hri = 0; hri < op.headers.length; hri++) {
          var subH = String(op.headers[hri]).split("と");
          for (var shri = 0; shri < subH.length; shri++) {
            var th = subH[shri].trim();
            if (th) flatHdr.push(th);
          }
        }
        op.headers = flatHdr;
      }
    }
    if (shelf.name === "replace") {
      if (_hasOwn(op, "find") && typeof op.find === "string") {
        var cleanFind = op.find.replace(/^(?:全シート|すべてのシート|全てのシート|ブック全体)で\s*/, "").trim();
        if (cleanFind !== op.find) {
          op.all_sheets = true;
          op.find = cleanFind;
        }
      }
      if (/全シート|すべてのシート|全てのシート|ブック全体/.test(text)) {
        op.all_sheets = true;
      }
    }
    var extraMissing = [];
    if (shelf.name === "sort") {
      var sortPairs = [];
      var nfkcTxt = nfkc(text);
      var mGrp = nfkcTxt.match(/([^\s、,の]{1,16})ごと(?:[、,]|に?かためて並べ)/);
      if (mGrp) {
        var rawGrp = mGrp[1].trim();
        var mappedGrp = _resolveColRefJs(rawGrp, table);
        if (mappedGrp) sortPairs.push(mappedGrp);
        else extraMissing.push("表に無い列名（" + rawGrp + "）");
      }
      var sortReG = /(?:その中で\s*|同じ[^\s、,。]{1,12}の中は\s*|同[^\s、,。]{1,12}内は\s*)?([^\s、,のは]{1,16})の(?:(大きい順|多い順|高い順|降順|新しい順|逆順|遅い順)|(小さい順|少ない順|低い順|昇順|古い順|五十音順|あいうえお順|若い順))/g;
      var sm;
      while ((sm = sortReG.exec(nfkcTxt)) !== null) {
        var rawColS = sm[1].trim();
        var mappedColS = _resolveColRefJs(rawColS, table);
        if (!mappedColS) {
          extraMissing.push("表に無い列名（" + rawColS + "）");
          continue;
        }
        var specS = (sm[2] ? "-" : "") + mappedColS;
        if (sortPairs.indexOf(specS) < 0 && sortPairs.indexOf(mappedColS) < 0) {
          sortPairs.push(specS);
        }
      }
      if (sortPairs.length >= 2) {
        op.cols = sortPairs;
        delete op.col;
        delete op.desc;
        named = true;
      }
    }
    if (shelf.name === "sheet.diff") {
      delete op.sheet;
      if (sheetHits.length && (op.from === op.to || !_hasOwn(op, "from") || !_hasOwn(op, "to"))) {
        var nfkcDiff = nfkc(text);
        var uniqSh = [];
        var seenShD = {};
        for (var sdi = 0; sdi < sheetHits.length; sdi++) {
          if (!seenShD[sheetHits[sdi]]) {
            seenShD[sheetHits[sdi]] = true;
            uniqSh.push(sheetHits[sdi]);
          }
        }
        uniqSh.sort(function (a, b) {
          return nfkcDiff.indexOf(nfkc(a)) - nfkcDiff.indexOf(nfkc(b));
        });
        if (uniqSh.length >= 2) {
          op.from = uniqSh[0];
          op.to = uniqSh[1];
        }
      }
    }
    if (shelf.name === "top.n") {
      if (op.into === "別") delete op.into;
      if (!_hasOwn(op, "col") && table && Array.isArray(table.columns)) {
        for (var tni = 0; tni < table.columns.length; tni++) {
          var tc = table.columns[tni];
          if (tc && tc.number && !/^(?:no\.?|番号|id)$/i.test(String(tc.name || "").trim())) {
            op.col = tc.name;
            named = true;
            break;
          }
        }
      }
    }
    function _extractCalcExprJs(txt, tbl) {
      var src = nfkc(txt);
      var colNames = [];
      var colsList = (tbl && tbl.columns) || [];
      for (var ci0 = 0; ci0 < colsList.length; ci0++) {
        var nm0 = String((colsList[ci0] && colsList[ci0].name) || "").trim();
        if (nm0 && colNames.indexOf(nm0) < 0) colNames.push(nm0);
      }
      colNames.sort(function (a, b) { return b.length - a.length; });
      var exprStripped = src;
      for (var es0 = 0; es0 < colNames.length; es0++) {
        var escEs = nfkc(colNames[es0]).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        exprStripped = exprStripped.replace(new RegExp(escEs + "の?(?:列|欄)[にへ]", "g"), " ");
      }
      var mPref = /^.*?(?:列|欄)[にへ]\s*/.exec(src);
      var exprPref = mPref ? src.slice(mPref[0].length) : src;
      function _cleanOp(raw) {
        var s = String(raw || "").trim().replace(/^[\s、,。をにで]+|[\s、,。をにで]+$/g, "");
        if (!s) return null;
        if (/^-?[0-9]+(?:\.[0-9]+)?$/.test(s)) return s;
        var res = _resolveColRefJs(s, tbl);
        if (res) return res;
        return (tbl && Array.isArray(tbl.columns) && tbl.columns.length) ? null : s;
      }
      var pats = [
        [/([^\s、,。をにと×*]{1,20})\s*(?:と|に|×|\*)\s*([^\s、,。をにと×*]{1,20})\s*(?:を)?(?:掛け|かけ|のかけ|乗算|掛け算)/, "*"],
        [/([^\s、,。をにと＋+]{1,20})\s*(?:と|に|＋|\+)\s*([^\s、,。をにと＋+]{1,20})\s*(?:を)?(?:足[しす]|た[しす]|加算)/, "+"],
        [/([^\s、,。をにから−-]{1,20})\s*(?:から|−|-)\s*([^\s、,。をにから−-]{1,20})\s*(?:を)?(?:引[いけく]|ひ[いけく]|差し引|減算)/, "-"],
        [/([^\s、,。をに÷/]{1,20})\s*(?:を|÷|\/)\s*([^\s、,。をに÷/]{1,20})\s*(?:で)?(?:割[っりる]|わ[っりる]|除算)/, "/"]
      ];
      var cands = [];
      var rawCands = [exprStripped, exprPref, src];
      for (var rc = 0; rc < rawCands.length; rc++) {
        if (rawCands[rc] && cands.indexOf(rawCands[rc]) < 0) cands.push(rawCands[rc]);
      }
      for (var ci1 = 0; ci1 < cands.length; ci1++) {
        for (var pi1 = 0; pi1 < pats.length; pi1++) {
          var mm = pats[pi1][0].exec(cands[ci1]);
          if (mm) {
            var a = _cleanOp(mm[1]), b = _cleanOp(mm[2]);
            if (a && b) return a + pats[pi1][1] + b;
          }
        }
      }
      return null;
    }

    if (shelf.name === "freeze" && !_hasOwn(op, "rows") && table && table.header_row && /見出し|ヘッダ/.test(text)) {
      op.rows = parseInt(table.header_row, 10);
    }
    if (shelf.name === "calc.col") {
      var tNfkcAt = nfkc(text);
      var tblColsSorted = [];
      if (table && Array.isArray(table.columns)) {
        for (var tc0 = 0; tc0 < table.columns.length; tc0++) {
          var tcNm = String((table.columns[tc0] && table.columns[tc0].name) || "").trim();
          if (tcNm && tblColsSorted.indexOf(tcNm) < 0) tblColsSorted.push(tcNm);
        }
        tblColsSorted.sort(function (a, b) { return b.length - a.length; });
      }
      if (!/(?:列|欄)[にへ]/.test(tNfkcAt)) {
        delete op.at;
      } else if (!_hasOwn(op, "at") || !_resolveColRefJs(op.at, table)) {
        delete op.at;
        for (var ati = 0; ati < tblColsSorted.length; ati++) {
          var cnAt = tblColsSorted[ati];
          var escAt = nfkc(cnAt).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          if (new RegExp(escAt + "の?(?:列|欄)[にへ]").test(tNfkcAt)) {
            op.at = cnAt;
            break;
          }
        }
        if (!_hasOwn(op, "at")) {
          var mAtCol = /([^\s、,。をにのがとてで]{1,20}?)の?(?:列|欄)[にへ]/.exec(tNfkcAt);
          if (mAtCol) {
            var rawAt = mAtCol[1].trim();
            var resAt = _resolveColRefJs(rawAt, table);
            if (resAt) op.at = resAt;
            else if (!/足し|追加|作/.test(tNfkcAt)) op.at = rawAt;
          }
        }
      }
      if (!_hasOwn(op, "expr")) {
        var extExpr = _extractCalcExprJs(text, table);
        if (extExpr) op.expr = extExpr;
      }
      if (op.expr) op.expr = _normalizeCalcExprStrJs(op.expr, table);
      if (!_hasOwn(op, "name") && _hasOwn(op, "at")) op.name = op.at;
      if (!_hasOwn(op, "name") && op.expr) {
        var mAfter = /(?:(?:掛け|かけ|足[しす]|た[しす]|引[いけく]|ひ[いけく]|割[っりる]|わ[っりる]|乗算|加算|減算|除算)(?:て|た|算)?|[×*＊÷\/／＋+−\-][^\s、,。をの]{1,20}?で)\s*(.+)$/.exec(tNfkcAt);
        if (mAfter) {
          var afterOp = mAfter[1];
          var mDest = /([^\s、,。をの]{1,20}?)(?:の列|列|の欄|欄)?(?:を(?:出し|求め|計算|足し|追加|作|入れ)|に(?:出し|入れ|して))/.exec(afterOp);
          var candNm = mDest ? mDest[1].trim() : "";
          if (candNm === "数式" || candNm === "式" || candNm === "計算式" || candNm === "計算結果" || candNm === "結果" || candNm === "値") {
            var afterCols = _colNames(afterOp, table);
            candNm = afterCols.length ? afterCols[afterCols.length - 1] : "";
          } else if (candNm) {
            var resDest = _resolveColRefJs(candNm, table);
            if (resDest && !/足し|追加|作/.test(afterOp)) candNm = resDest;
          }
          if (!candNm) {
            var afterCols2 = _colNames(afterOp, table);
            if (afterCols2.length) candNm = afterCols2[afterCols2.length - 1];
          }
          if (candNm) {
            op.name = candNm;
            if (tblColsSorted.indexOf(candNm) >= 0 && !_hasOwn(op, "at") && !/足し|追加|作/.test(afterOp)) {
              op.at = candNm;
            }
          }
        }
      }
      if (typeof op.name === "string") {
        var cleanedCnm = _cleanCalcColNameJs(op.name);
        if (cleanedCnm) op.name = cleanedCnm;
        else delete op.name;
      }
      if (op.expr && op.name) named = true;
    }

    if (shelf.name === "summary" || shelf.name === "pivot.new") {
      if (shelf.name === "summary" && typeof op.by === "string") {
        var resBy = _resolveColRefJs(op.by, table);
        if (resBy) op.by = resBy;
        else {
          extraMissing.push("表に無い列名（" + op.by + "）");
          delete op.by;
        }
      }
      if (shelf.name === "pivot.new" && Array.isArray(op.rows) && Array.isArray(op.cols)) {
        var dedupCols = [];
        for (var dci = 0; dci < op.cols.length; dci++) {
          if (op.rows.indexOf(op.cols[dci]) < 0) dedupCols.push(op.cols[dci]);
        }
        if (dedupCols.length) op.cols = dedupCols;
        else delete op.cols;
      }
      var groupCols = [];
      if (shelf.name === "summary" && op.by) groupCols.push(op.by);
      if (shelf.name === "pivot.new") {
        if (Array.isArray(op.rows)) groupCols = groupCols.concat(op.rows);
        if (Array.isArray(op.cols)) groupCols = groupCols.concat(op.cols);
      }
      if (op.func !== "count") {
        var curVals = Array.isArray(op.values) ? op.values.slice() : (op.values ? [op.values] : []);
        var fvList = [];
        for (var svi = 0; svi < curVals.length; svi++) {
          if (groupCols.indexOf(curVals[svi]) < 0) fvList.push(curVals[svi]);
        }
        if (table && _hasNumberMetaJs(table)) {
          var numFv = [];
          for (var nvi = 0; nvi < fvList.length; nvi++) {
            if (_isNumberColJs(table, fvList[nvi])) numFv.push(fvList[nvi]);
          }
          fvList = numFv;
        }
        if (!fvList.length && table) {
          var resNums = _resolveUniqueColsJs(scan, table, _hasNumberMetaJs(table), groupCols);
          if (resNums.length) fvList = resNums;
          else {
            var fbNum = _singleNumericFallbackJs(table, groupCols);
            if (fbNum) fvList = [fbNum];
          }
        }
        if (fvList.length) op.values = fvList;
        else delete op.values;
      } else if ((!op.values || !op.values.length) && groupCols.length) {
        op.values = [groupCols[0]];
      }
    }
    if (shelf.name === "chart.new" && !op.edit && !explicitRange && table) {
      var chartCols = names.slice();
      for (var cli2 = 0; cli2 < letters.length; cli2++) {
        if (!nameLetters[letters[cli2]] && chartCols.indexOf(letters[cli2]) < 0) chartCols.push(letters[cli2]);
      }
      var uChart = _resolveUniqueColsJs(scan, table, false, chartCols);
      for (var uci = 0; uci < uChart.length; uci++) {
        if (chartCols.indexOf(uChart[uci]) < 0) chartCols.push(uChart[uci]);
      }
      if (chartCols.length) {
        var hasNumMetaCh = _hasNumberMetaJs(table);
        var labelCols = [], numColsCh = [];
        for (var cci = 0; cci < chartCols.length; cci++) {
          if (hasNumMetaCh && _isNumberColJs(table, chartCols[cci])) numColsCh.push(chartCols[cci]);
          else labelCols.push(chartCols[cci]);
        }
        if (hasNumMetaCh && !numColsCh.length) {
          var resChNums = _resolveUniqueColsJs(scan, table, true, chartCols);
          if (resChNums.length) numColsCh = numColsCh.concat(resChNums);
          else {
            var fbCh = _singleNumericFallbackJs(table, chartCols);
            if (fbCh) numColsCh.push(fbCh);
          }
        }
        if (hasNumMetaCh && !numColsCh.length) {
          delete op.range;
          extraMissing.push("グラフにする数値の列");
        } else {
          var orderedCols = hasNumMetaCh ? labelCols.concat(numColsCh) : chartCols;
          var orderedLs = [];
          for (var oci = 0; oci < orderedCols.length; oci++) {
            var ol = _letterOf(table, orderedCols[oci]) || (/^[A-Z]{1,3}$/.test(String(orderedCols[oci])) ? String(orderedCols[oci]) : null);
            if (ol && orderedLs.indexOf(ol) < 0) orderedLs.push(ol);
          }
          var spCh = _dataSpan(table);
          if (orderedLs.length && spCh) {
            var chR1 = parseInt(table.header_row || spCh[0], 10);
            var chR2 = spCh[1];
            if (orderedLs.length === 1) {
              op.range = orderedLs[0] + chR1 + ":" + orderedLs[0] + chR2;
            } else {
              var contigAsc = true;
              for (var cai2 = 1; cai2 < orderedLs.length; cai2++) {
                if (_colNum(orderedLs[cai2]) - _colNum(orderedLs[cai2 - 1]) !== 1) { contigAsc = false; break; }
              }
              if (contigAsc) {
                op.range = orderedLs[0] + chR1 + ":" + orderedLs[orderedLs.length - 1] + chR2;
              } else {
                var rParts = [];
                for (var rpi = 0; rpi < orderedLs.length; rpi++) rParts.push(orderedLs[rpi] + chR1 + ":" + orderedLs[rpi] + chR2);
                op.range = rParts.join(",");
              }
            }
          }
        }
      }
    }
    if (shelf.name === "width") {
      if (_hasOwn(op, "col") && !_hasOwn(op, "width") && !_hasOwn(op, "auto") && /(?:自動|中身に合|オートフィット)/.test(text)) {
        op.auto = [op.col];
        delete op.col;
      } else if (!_hasOwn(op, "auto") && !_hasOwn(op, "cols") && !_hasOwn(op, "col") && !_hasOwn(op, "rows") && !op.all_sheets && /(?:自動|中身に合|オートフィット|ちょうどよく|見切れ)/.test(text)) {
        if (table && Array.isArray(table.columns)) {
          var colsAuto = [];
          for (var wci = 0; wci < table.columns.length; wci++) {
            if (table.columns[wci].col) colsAuto.push(table.columns[wci].col);
          }
          if (colsAuto.length) { op.auto = colsAuto; named = true; }
        }
      }
    }

    if (shelf.name === "filter.where" || shelf.name === "filter.delete" || shelf.name === "filter.extract") {
      if (shelf.name === "filter.extract" && op.into === "別") delete op.into;
      if (_hasOwn(op, "when") && _hasOwn(op, "equals") && typeof op.equals === "string") {
        if (/以上|以下|未満|より|超|を含|含む|以外|ではな|でない|空白|空欄/.test(op.equals)) {
          delete op.equals;
        }
      }
      if (shelf.name === "filter.where") {
        var hasCmpCue = _hasOwn(op, "when") || /以上|以下|未満|より|を超?|を含|含む|以外|ではな|でない|空白|空欄/.test(text);
        if (!hasCmpCue && !_hasOwn(op, "equals")) {
          var mName = /^(.+?)(?:さん|様)?の行だけ/.exec(text.trim());
          if (mName) op.equals = mName[1].trim();
        }
      }
      if (_hasOwn(op, "equals")) {
        _cleanFilterEqualsJs(op, text, table, origQuotesMap);
      }
      if (op.when === "ne") delete op.equals;
      _resolveCmpValueJs(op, text);
      if (!_hasOwn(op, "col") && table && table.columns) {
        var cols = [];
        for (var tci = 0; tci < table.columns.length; tci++) {
          cols.push(table.columns[tci].name);
        }
        var eq = String(op.equals || "");
        var hasKamoku = cols.indexOf("勘定科目") >= 0 || cols.indexOf("科目") >= 0;
        var isExpense = eq.indexOf("旅費") >= 0 || ["費", "料", "税", "手当"].some(function (x) { return eq.indexOf(x) >= 0; });
        var personCols = ["氏名", "名前", "社員名", "担当者", "担当"];
        var foundPersonCol = null;
        for (var pci = 0; pci < personCols.length; pci++) {
          if (cols.indexOf(personCols[pci]) >= 0) {
            foundPersonCol = personCols[pci];
            break;
          }
        }
        var isPerson = eq.indexOf(" ") >= 0 || eq.indexOf("　") >= 0 || ["さん", "様", "氏"].some(function (x) { return text.indexOf(x) >= 0; });
        if (hasKamoku && isExpense) {
          op.col = cols.indexOf("勘定科目") >= 0 ? "勘定科目" : "科目";
        } else if (foundPersonCol && isPerson) {
          op.col = foundPersonCol;
        } else if (cols.length) {
          var textCols = [];
          for (var tci2 = 0; tci2 < table.columns.length; tci2++) {
            if (!table.columns[tci2].number) textCols.push(table.columns[tci2].name);
          }
          if (textCols.length) op.col = textCols[0];
        }
      }
      if (shelf.name === "filter.delete" && op.col && (op.when || _hasOwn(op, "equals") || _hasOwn(op, "value"))) {
        named = true;
      }
    }

    var missing = [];
    _validateAndResolveColArgsJs(shelf, op, table, missing);
    for (var mi = 0; mi < argsList.length; mi++) {
      if (argsList[mi].req && _isEmptyVal(op[argsList[mi].name]) && missing.indexOf(argsList[mi].name) < 0) {
        missing.push(argsList[mi].name);
      }
    }
    for (var emi = 0; emi < extraMissing.length; emi++) {
      if (missing.indexOf(extraMissing[emi]) < 0) missing.push(extraMissing[emi]);
    }
    if (anyList.length && !hasAnyFilled()) {
      missing.push(anyList.join("・") + " のどれか");
    }

    var what = [];
    var hasNonLocReq = false;
    for (var wi2 = 0; wi2 < argsList.length; wi2++) {
      var wa = argsList[wi2];
      if (wa.req && !LOCATOR_TYPES[wa.type]) hasNonLocReq = true;
      if (!wa.req && !LOCATOR_TYPES[wa.type] && anyList.indexOf(wa.name) < 0) {
        what.push(wa.name);
      }
    }
    var bareOk = false;
    var exList = shelf.examples || [];
    for (var exi = 0; exi < exList.length; exi++) {
      var exOp = exList[exi][1] || {};
      var hasWhatInEx = false;
      for (var wki = 0; wki < what.length; wki++) {
        if (_hasOwn(exOp, what[wki])) {
          hasWhatInEx = true;
          break;
        }
      }
      if (!hasWhatInEx) {
        bareOk = true;
        break;
      }
    }
    var hasWhatInOp = false;
    for (var woi = 0; woi < what.length; woi++) {
      if (_hasOwn(op, what[woi])) {
        hasWhatInOp = true;
        break;
      }
    }
    if (!missing.length && !bareOk && what.length >= WHAT_MIN && !hasWhatInOp && !hasNonLocReq) {
      missing.push("何をするか（" + what.slice(0, 6).join("・") + " …）");
    }
    _auditBuiltOpJs(shelf, op, text, scan, table, colorHits, missing);
    if (shelf.danger && named && !VAGUE_RE.test(nfkc(text)) && !missing.length) {
      op.ok = true;
    }
    return { op: op, missing: missing, named: named };
  }

  // ------------------------------------------------------------------ 選択範囲・代名詞
  function parseSelectionScope(selection) {
    var sel = nfkc(selection || "").trim().toUpperCase();
    if (!sel) return {};
    var bang = sel.lastIndexOf("!");
    if (bang >= 0) sel = sel.slice(bang + 1).trim();

    var mCell = /^([A-Z]{1,3})([0-9]{1,7})$/.exec(sel);
    if (mCell) {
      var colS = mCell[1];
      var rowN = parseInt(mCell[2], 10);
      return {
        selection: sel,
        cell: sel,
        range: sel,
        col: colS,
        cols: [colS],
        rows: [rowN],
        from_browser: true
      };
    }

    var mRng = /^([A-Z]{1,3})([0-9]{1,7}):([A-Z]{1,3})([0-9]{1,7})$/.exec(sel);
    if (mRng) {
      var c1 = mRng[1], r1 = parseInt(mRng[2], 10);
      var c2 = mRng[3], r2 = parseInt(mRng[4], 10);
      var nc1 = _colNum(c1), nc2 = _colNum(c2);
      var n1 = Math.min(nc1, nc2), n2 = Math.max(nc1, nc2);
      var rLo = Math.min(r1, r2), rHi = Math.max(r1, r2);
      var cols = [];
      if (n2 - n1 < 60) {
        for (var n = n1; n <= n2; n++) cols.push(_colLetter(n));
      } else {
        cols = [c1];
      }
      var outRng = {
        selection: sel,
        range: _colLetter(n1) + rLo + ":" + _colLetter(n2) + rHi,
        cols: cols,
        from_browser: true
      };
      if (cols.length === 1) {
        outRng.col = cols[0];
        if (rLo === rHi) outRng.cell = cols[0] + rLo;
      }
      if (rHi - rLo < 500) {
        var rowsArr = [];
        for (var r = rLo; r <= rHi; r++) rowsArr.push(r);
        outRng.rows = rowsArr;
      }
      return outRng;
    }

    var mCol = /^([A-Z]{1,3}):([A-Z]{1,3})$/.exec(sel);
    if (mCol) {
      var mc1 = _colNum(mCol[1]), mc2 = _colNum(mCol[2]);
      var mn1 = Math.min(mc1, mc2), mn2 = Math.max(mc1, mc2);
      var cCols = [];
      if (mn2 - mn1 < 60) {
        for (var cn = mn1; cn <= mn2; cn++) cCols.push(_colLetter(cn));
      } else {
        cCols = [mCol[1]];
      }
      var outCol = {
        selection: sel,
        range: _colLetter(mn1) + ":" + _colLetter(mn2),
        cols: cCols,
        col_select: true,
        from_browser: true
      };
      if (cCols.length === 1) outCol.col = cCols[0];
      return outCol;
    }

    var mRow = /^([0-9]{1,7}):([0-9]{1,7})$/.exec(sel);
    if (mRow) {
      var rr1 = parseInt(mRow[1], 10), rr2 = parseInt(mRow[2], 10);
      var rl1 = Math.min(rr1, rr2), rl2 = Math.max(rr1, rr2);
      var rRows = [];
      if (rl2 - rl1 < 5000) {
        for (var rr = rl1; rr <= rl2; rr++) rRows.push(rr);
      } else {
        rRows = [rr1];
      }
      return {
        selection: sel,
        range: rl1 + ":" + rl2,
        rows: rRows,
        row_select: true,
        from_browser: true
      };
    }

    return {};
  }

  function _expandSelectionPronouns(text, sourceScope) {
    if (!sourceScope || typeof sourceScope !== "object" || !Object.keys(sourceScope).length) {
      return text;
    }
    var out = text;
    var rows = sourceScope.rows;
    if (rows && rows.length && _HERE_ROW_RE.test(out)) {
      var rowExpr = rows.length === 1 ? (rows[0] + "行目") : (rows[0] + "行目から" + rows[rows.length - 1] + "行目");
      out = out.replace(_HERE_ROW_RE_G, rowExpr);
    }
    var cols = (sourceScope.cols && sourceScope.cols.length) ? sourceScope.cols : (sourceScope.col ? [sourceScope.col] : []);
    if (cols.length && _HERE_COL_RE.test(out)) {
      var colExpr = cols.length === 1 ? (cols[0] + "列") : (cols[0] + "列から" + cols[cols.length - 1] + "列");
      out = out.replace(_HERE_COL_RE_G, colExpr);
    }
    var rng = sourceScope.cell || sourceScope.range;
    if (rng && _HERE_RANGE_RE.test(out)) {
      var putCellRe = /(?:ここ|このセル|選択セル|選択中のセル)に\s*([『「"“]?[^』」"”\s]+[』」"”]?)\s*を(?:入れ|書|入力)(?:き込|て|して)?/;
      var chgCellRe = /(?:ここ|このセル|選択セル|選択中のセル)(?:の[^\sを]{0,8})?を\s*([『「"“]?[^』」"”\s]+[』」"”]?)\s*に(?:書き換|打ち直|変え|直)/;
      if (sourceScope.cell && putCellRe.test(out)) {
        out = out.replace(putCellRe, sourceScope.cell + "の値を$1に打ち直して");
      } else if (sourceScope.cell && chgCellRe.test(out)) {
        out = out.replace(chgCellRe, sourceScope.cell + "の値を$1に打ち直");
      } else {
        out = out.replace(_HERE_RANGE_RE_G, rng);
      }
    }
    return out;
  }

  function _filterMissing(missing, keywords) {
    var out = [];
    for (var i = 0; i < missing.length; i++) {
      var m = missing[i];
      var hit = false;
      for (var j = 0; j < keywords.length; j++) {
        if (m.indexOf(keywords[j]) >= 0) {
          hit = true;
          break;
        }
      }
      if (!hit) out.push(m);
    }
    return out;
  }

  function _applyScopeFallback(op, missing, sourceScope, shelf, clause) {
    if (!sourceScope || typeof sourceScope !== "object" || !Object.keys(sourceScope).length) {
      return { missing: missing, added: false };
    }
    var locKeys = ["header", "title", "range", "col", "cols", "rows", "cells", "at", "from"];
    for (var li = 0; li < locKeys.length; li++) {
      var lk = locKeys[li];
      if (_hasOwn(op, lk) && !_isEmptyVal(op[lk])) {
        return { missing: missing, added: false };
      }
    }

    if (!shelf || !sourceScope.from_browser) {
      var legacyKeys = ["header", "title", "range", "col"];
      for (var lki = 0; lki < legacyKeys.length; lki++) {
        var sk = legacyKeys[lki];
        if (_hasOwn(sourceScope, sk) && !_isEmptyVal(sourceScope[sk])) {
          op[sk] = sourceScope[sk];
          return { missing: _filterMissing(missing, ["range", "col", "header", "title"]), added: true };
        }
      }
      return { missing: missing, added: false };
    }

    var argNames = {};
    var sArgs = shelf.args || [];
    for (var ai = 0; ai < sArgs.length; ai++) argNames[sArgs[ai].name] = true;
    var shName = shelf.name || "";

    // 危険な行/列削除へのブラウザ選択自動補完は厳格化（行選択・列選択または指示代名詞のみ許可、条件文脈なら絶対補完しない）
    if (shName === "rows.delete" || shName === "cols.delete" || shName === "filter.delete") {
      if (shName === "filter.delete") {
        return { missing: missing, added: false };
      }
      if (/(?:が|は|の).{0,16}(?:行|データ)|以上|以下|未満|超え?|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行/.test(clause)) {
        return { missing: missing, added: false };
      }
      if (shName === "rows.delete" && !sourceScope.row_select && !_HERE_ROW_RE.test(clause)) {
        return { missing: missing, added: false };
      }
      if (shName === "cols.delete" && !sourceScope.col_select && !_HERE_COL_RE.test(clause)) {
        return { missing: missing, added: false };
      }
    }

    if (shName === "write" && sourceScope.cell && !op.cells && !op.tsv) {
      var qs = _quotes(clause);
      var ns = _numbers(clause);
      var val = qs.length ? qs[0] : (ns.length === 1 ? ns[0] : null);
      if (val !== null && val !== undefined) {
        var cellsObj = {};
        cellsObj[sourceScope.cell] = val;
        op.cells = cellsObj;
        return { missing: _filterMissing(missing, ["cells", "tsv"]), added: true };
      }
    }

    var isMultiRange = String(sourceScope.range || "").indexOf(":") >= 0;
    var hasPronoun = _HERE_RANGE_RE.test(clause) || _HERE_COL_RE.test(clause) || _HERE_ROW_RE.test(clause);
    if (!missing.length && !hasPronoun && shName !== "format" && shName !== "clear.values") {
      if (!isMultiRange) {
        return { missing: missing, added: false };
      }
    }

    var candidates;
    if (sourceScope.row_select) {
      candidates = [["rows", "rows"], ["range", "range"]];
    } else if (sourceScope.col_select) {
      candidates = [["cols", "cols"], ["auto", "cols"], ["col", "col"], ["range", "range"]];
    } else {
      candidates = [
        ["header", "header"],
        ["title", "title"],
        ["range", "range"],
        ["col", "col"],
        ["cols", "cols"],
        ["auto", "cols"],
        ["rows", "rows"]
      ];
    }

    for (var ci = 0; ci < candidates.length; ci++) {
      var argK = candidates[ci][0];
      var srcK = candidates[ci][1];
      if (argNames[argK] && !_isEmptyVal(sourceScope[srcK])) {
        op[argK] = sourceScope[srcK];
        return {
          missing: _filterMissing(missing, ["range", "col", "cols", "rows", "header", "title", "auto"]),
          added: true
        };
      }
    }
    return { missing: missing, added: false };
  }

  // ------------------------------------------------------------------ 短い表示形式・全体 plan
  function _pyJsonDumps(v) {
    if (v === null || typeof v !== "object") {
      return JSON.stringify(v);
    }
    if (Array.isArray(v)) {
      var items = [];
      for (var i = 0; i < v.length; i++) {
        items.push(v[i] === undefined ? "null" : _pyJsonDumps(v[i]));
      }
      return "[" + items.join(", ") + "]";
    }
    var keys = Object.keys(v);
    var pairs = [];
    for (var j = 0; j < keys.length; j++) {
      var k = keys[j];
      if (v[k] === undefined) continue;
      pairs.push(JSON.stringify(k) + ": " + _pyJsonDumps(v[k]));
    }
    return "{" + pairs.join(", ") + "}";
  }

  function formatOpsShort(ops) {
    if (!ops || !ops.length) return "";
    var parts = [];
    for (var i = 0; i < ops.length; i++) {
      var o = ops[i] || {};
      var keys = Object.keys(o);
      var args = [];
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j];
        if (k === "shelf") continue;
        args.push(k + "=" + _pyJsonDumps(o[k]));
      }
      parts.push((o.shelf || "?") + "(" + args.join(", ") + ")");
    }
    return parts.join(", ");
  }

  function _hasNonMetaKeys(op) {
    var keys = Object.keys(op);
    for (var i = 0; i < keys.length; i++) {
      if (keys[i] !== "shelf" && keys[i] !== "sheet") return true;
    }
    return false;
  }

  function _rxHitShelf(shelf, text) {
    var rules = shelf.ask_rules || [];
    for (var i = 0; i < rules.length; i++) {
      if (_hasOwn(rules[i], "re") && _rx(rules[i].re).test(text)) return true;
    }
    return false;
  }

  function _buildPreviewText(res) {
    if (res.fire) {
      return "棚ヒット: " + formatOpsShort(res.ops);
    }
    var reason = res.reasons.length
      ? res.reasons.join("／")
      : (res.missing.length ? "不足: " + res.missing.join("、") : "棚に該当なし");
    return "未確定: " + reason;
  }

  function plan(askText, kind, table, sheets, curSheet, lastScope) {
    _ensureInit();
    kind = kind || "";
    sheets = sheets || [];
    curSheet = curSheet || (sheets.length ? sheets[0] : "");

    var p = {
      ops: [],
      fire: false,
      reasons: [],
      missing: [],
      cards: [],
      guide: [],
      previewText: ""
    };

    askText = String(askText || "").trim();
    if (!askText) {
      p.reasons.push("頼みの文が空です");
      p.previewText = _buildPreviewText(p);
      return p;
    }

    var qAll = norm(askText, _synonyms);
    p.guide = _matchGuide(qAll);

    var rawCl = _clauses(askText);
    if (!rawCl.length) rawCl = [nfkc(askText)];
    var cl = [];
    for (var rci0 = 0; rci0 < rawCl.length; rci0++) {
      var rc0 = rawCl[rci0];
      var mTs = /合計(?:行)?と(平均|最大値?|最小値?)(?:の?行)?/.exec(rc0);
      if (mTs && /一番下|表の下|下に|行を?(?:足|追加|入れ)|足して|追加して|入れて/.test(rc0) && !/ごと|別に|別シート|小計/.test(rc0)) {
        cl.push(rc0.replace(mTs[0], "合計行"));
        cl.push(rc0.replace(mTs[0], mTs[1] + "の行"));
      } else {
        cl.push(rc0);
      }
    }

    var fatalErr = false;
    var vagueM = VAGUE_RE.exec(nfkc(askText));
    if (vagueM) {
      p.reasons.push("どこを指すかが人にしか分かりません（" + vagueM[0] + "）");
      fatalErr = true;
    }

    var lastIncomplete = null;
    for (var ci = 0; ci < cl.length; ci++) {
      var cRaw = cl[ci];
      var c = _expandSelectionPronouns(cRaw, lastScope);
      var scored = scoreAll(c, kind);

      if (lastIncomplete !== null && (
        !scored.length ||
        scored[0].total < WEAK_SCORE ||
        scored[0].shelf.name === lastIncomplete.top.name
      )) {
        var prevC = lastIncomplete.clause;
        var prevTop = lastIncomplete.top;
        var merged = prevC + " " + c;
        var mRes = buildOp(prevTop, merged, table, sheets, curSheet);
        var mOp = mRes.op;
        var mMissing = mRes.missing;
        var mNamed = mRes.named;

        if (lastScope && typeof lastScope === "object" && (prevTop.name === "format" || lastScope.from_browser) && (_hasNonMetaKeys(mOp) || mMissing.length)) {
          var fbM = _applyScopeFallback(mOp, mMissing, lastScope, prevTop, merged);
          mMissing = fbM.missing;
          mNamed = mNamed || fbM.added;
          if (prevTop.danger && mNamed && !VAGUE_RE.test(nfkc(merged)) && !mMissing.length) {
            mOp.ok = true;
          }
        }
        var lastOpKeysLen = Object.keys(p.ops[p.ops.length - 1]).length;
        var mOpKeysLen = Object.keys(mOp).length;
        if (mMissing.length < lastIncomplete.missingN || (mOpKeysLen > lastOpKeysLen && mMissing.length <= lastIncomplete.missingN)) {
          p.ops[p.ops.length - 1] = mOp;
          p.missing.splice(lastIncomplete.missStart);
          if (mMissing.length) {
            for (var mmi = 0; mmi < mMissing.length; mmi++) {
              p.missing.push(prevTop.name + ": " + mMissing[mmi]);
            }
            lastIncomplete.clause = merged;
            lastIncomplete.missingN = mMissing.length;
          } else {
            if (lastIncomplete.cardAdded && p.cards.length) p.cards.pop();
            lastIncomplete = null;
          }
          continue;
        }
      }

      // 型ベースの優先調停（スコア0でも明確な型の依頼を救済する）
      var boostName = "";
      var topBase = scored.length ? scored[0].total : WEAK_SCORE;
      var candMap = {};
      for (var cmi = 0; cmi < scored.length; cmi++) candMap[scored[cmi].shelf.name] = true;
      if (kind !== "doc") {
        var hasFmtCue = /(?:表示形式|曜日|hh:mm|yyyy|mm\/dd|時刻.{0,4}2桁|09:00|カンマ|桁区切|パーセント|円マーク|円表示|¥|通貨形式|数値\s*[（(]?標準|標準形式|標準に戻|年月日の?形|年月日形式|年月日に|日付の?形)/i.test(c);
        var hasColsHideCue = /(?:列|カラム).*(?:非表示|隠|見えなく)/.test(c) &&
          !/グリッド線|枠線|目盛り線|シート|タブ|再表示/.test(c);
        var hasRowsHideCue = /行.*(?:非表示|隠|見えなく)/.test(c) &&
          !/グリッド線|枠線|目盛り線|シート|タブ|再表示|消|削除/.test(c);
        var hasFontUnifyCue = /(?:フォント|書体).*(?:統一|揃え|そろえ)/.test(c) ||
          /(?:全シート|すべてのシート|全てのシート|シート全体|ブック全体).*(?:フォント|書体)/.test(c);
        var hasTotalRowCue = ((c.indexOf("合計") >= 0 && /一番下|最後の行|末尾の行|表の下|下に|合計行|合計欄/.test(c)) || /合計を.{0,12}(?:足|追加|入れ|付け)/.test(c)) &&
          !/ごと|別に|別シート|小計|平均|最大|最小|ピボット|クロス/.test(c);
        var hasStatRowCue = /平均|最大|最小/.test(c) &&
          /一番下|最後の行|末尾の行|表の下|下に|(?:平均|最大|最小)(?:値)?(?:の?行|を.{0,12}(?:足|追加|入れ|付け))/.test(c) &&
          !/ごと|別に|別シート|合計|ピボット|クロス/.test(c);
        var hasPaintFmtCue = _colorHits(c).length > 0 && c.indexOf("塗") >= 0 &&
          !/条件|以上|以下|未満|以外|じゃない|になって|消|削除|クリア|なし|無し|1行おき|交互|しましま|縞模様|重複|ダブ|固定色|該当行|行全体|の行/.test(c);
        var hasRowCfCond = /(?:以上|以下|未満|より大き|より小さ|を超|超え|マイナス|負の値|になっていない|になってない|ではない|でない|じゃない|以外|空欄|空白|欠席|完了)/.test(c) ||
          /[^\s、。]+?(?:が|は)[^\s、。の]+?の行/.test(c);
        var hasRowCfCue = /(?:行全体|の行|行を|行に|いない行|ない行)/.test(c) &&
          hasRowCfCond &&
          !/消|削除|重複|ダブ|固定色/.test(c) &&
          (_colorHits(c).length > 0 || /色[を]?付|色[を]?つ|目立|ハイライト/.test(c));
        var hasRowDelCond = /(?:の行|行を|行に|行は|データ)/.test(c) &&
          /(?:以上|以下|未満|より大きい|より小さい|を超え|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行)/.test(c) &&
          /消|削除/.test(c);
        var hasSummaryCue = /(?:別(?:に|で|の)|ごと(?:に|の))/.test(c) &&
          /集計|合計|平均|件数/.test(c) &&
          !/ピボット|クロス|縦と横|小計|グラフ|並|ソート|抽出/.test(c);
        var hasCalcCue = /(?:と|に|×|\*)[^\s、。をにが]{1,16}?(?:を)?(?:掛け|かけ|乗算)|(?:と|に|＋|\+)[^\s、。をにが]{1,16}?(?:を)?(?:足[しす]|た[しす]|加算)|(?:から|−|-)[^\s、。をにが]{1,16}?(?:を)?(?:引[いけく]|ひ[いけく]|差し引|減算)|(?:を|÷|\/)[^\s、。をにが]{1,16}?(?:で)?(?:割[っりる]|わ[っりる]|除算)|[^\s、。0-9:\/\-][^\s、。]{0,14}[×*＊÷＋][^\s、。]{1,14}(?:で|を|の)/.test(nfkc(c)) &&
          !/構成比|割合|消費税|税込|税抜|累計|順位|平均|合計行|別シート|ごと|別に|小計|前月比|前年比|経過|罫線|空の?(?:列|行)|の間に|の下に|の上に/.test(c);
        var hasChartCue = /(?:グラフ|棒グラフ|折れ線|円グラフ|散布図|面グラフ)/.test(c) &&
          !/消|削除|なく|いらない/.test(c);
        var hasFilterWhereCue = (/(?:以上|以下|未満|より大|より小|を超|超え|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄)/.test(c) ||
          /[^\s、。]+?(?:が|は)[^\s、。の]+?の(?:行|もの|データ|人)/.test(c)) &&
          /(?:だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|絞り込|フィルタ)/.test(c) &&
          !/(?:消|削除|別シート|抽出|色|ハイライト|目立|IF|判定|解除|外し|外す)/i.test(c);
        var hasFreezeCue = /固定|フリーズ/.test(c) &&
          !/解除|外|やめ|なく|値|式|数式|絶対参照|固定色|書式|太字|色|背景|罫線|揃え|寄せ/.test(c);
        var hasBlankDelCue = /空行|空いてる行|空いている行|空白行|空白の行|空き行/.test(c) &&
          !/重複|ダブ|全角|半角|整え|きれい|掃除|トリム|余分な空白|末尾|軽く|下まで|余白/.test(c);
        var hasBorderFmtCue = /罫線|外枠|格子/.test(c) &&
          !/整え|見やすく|体裁|きれい|区切り線|変わる行|切り替わる行|グリッド線|目盛り線|シート.*枠線/.test(c);
        var hasRemoveAct = /外し|外す|解除|やめ|なくし|無くし|消して|消す|削除|クリア|オフ|OFF/.test(c);

        var ensureBoost = function (nm) {
          boostName = nm;
          if (!candMap[nm] && _byName[nm]) {
            scored.push({ total: topBase, order: 999, shelf: _byName[nm], detail: {} });
            candMap[nm] = true;
          }
        };

        if (hasRemoveAct && /1行おき|交互|しましま|縞模様|ストライプ/.test(c)) {
          ensureBoost("banding.remove");
        } else if (hasRemoveAct && /条件付き書式|自動でついた色|自動の色/.test(c)) {
          ensureBoost("cf.clear");
        } else if (hasRemoveAct && /プルダウン|入力規則/.test(c)) {
          ensureBoost("validation.clear");
        } else if (hasRemoveAct && /フィルタ|フィルター|絞り込み|▼/.test(c)) {
          ensureBoost("filter.off");
        } else if (hasRemoveAct && /固定|フリーズ|ウィンドウ枠/.test(c)) {
          ensureBoost("unfreeze");
        } else if (hasRemoveAct && /保護|ロック/.test(c)) {
          ensureBoost("protect.remove");
        } else if (hasRemoveAct && /グループ|折りたた/.test(c)) {
          ensureBoost("group.remove");
        } else if (hasRemoveAct && /グラフ|棒グラフ|折れ線|円グラフ/.test(c)) {
          ensureBoost("chart.delete");
        } else if (hasRowCfCue) {
          ensureBoost("cf.add");
        } else if (hasChartCue) {
          ensureBoost("chart.new");
        } else if (hasFilterWhereCue) {
          ensureBoost("filter.where");
        } else if (hasCalcCue) {
          ensureBoost("calc.col");
        } else if (hasSummaryCue) {
          ensureBoost("summary");
        } else if (hasFreezeCue) {
          ensureBoost("freeze");
        } else if (hasBlankDelCue && (candMap["blank.rows.delete"] || candMap["seiri"])) {
          ensureBoost("blank.rows.delete");
        } else if (hasBorderFmtCue) {
          ensureBoost("format");
        } else if (hasColsHideCue) {
          ensureBoost("cols.hide");
        } else if (hasRowsHideCue) {
          ensureBoost("rows.hide");
        } else if (hasFontUnifyCue) {
          ensureBoost("font.unify");
        } else if (hasTotalRowCue) {
          ensureBoost("total");
        } else if (hasStatRowCue) {
          ensureBoost("stat.row");
        } else if (hasPaintFmtCue) {
          ensureBoost("format");
        } else if (hasFmtCue && !/分け|取り出|抽出|列を足|列を作|経過|日数|年齢|勤続|本物の日付|ちゃんとした日付|文字列を日付|日付に変換|マイナス|赤字|三角|千円|百万/.test(c)) {
          ensureBoost("format");
        } else if (scored.length >= 2) {
          if (_colorHits(c).length > 0 && c.indexOf("文字") >= 0 && !/(?:大文字|小文字|全角|半角|UPPER|LOWER|PROPER)/i.test(c) && candMap["format"]) {
            boostName = "format";
          } else if (hasRowDelCond && candMap["filter.delete"]) {
            boostName = "filter.delete";
          } else if (candMap["link.clear"] && /(?:リンク|ハイパーリンク).*(?:外|解除|消|削除|クリア)/.test(c)) {
            boostName = "link.clear";
          } else if (candMap["link.extract"] && /(?:URL|リンク先).*(?:抽出|取り出)|埋め込みリンク/i.test(c)) {
            boostName = "link.extract";
          } else if (candMap["top.n"] && /(?:上位|下位|トップ|ワースト|ベスト)\s*[0-9]*/.test(c)) {
            boostName = "top.n";
          } else if (candMap["filter.extract"] && c.indexOf("抽出") >= 0 && !/(?:上位|下位|トップ|ワースト|ベスト|URL|リンク)/i.test(c)) {
            boostName = "filter.extract";
          } else if (candMap["merge.unmerge"] && /結合.*(?:埋め|バラ|ばら|分解|ほど|穴埋)|(?:埋め|穴埋).*結合/.test(c)) {
            boostName = "merge.unmerge";
          } else if (candMap["fill.blank"] && /穴埋め|(?:空白|空欄|ブランク).*上の値/.test(c)) {
            boostName = "fill.blank";
          } else if (candMap["transpose"] && /転置|縦横を入れ替|行列を入れ替|行と列を入れ替|縦と横を逆|横向きを縦向き|縦向きを横向き/.test(c)) {
            boostName = "transpose";
          } else if (candMap["number.fix"] && /(?:文字|テキスト).{0,6}数字|数値に変換|本物の数値|文字.{0,4}数値に直/.test(c)) {
            boostName = "number.fix";
          } else if (candMap["sheet.diff"] && /シート.*(?:比較|差分|違い)|(?:比較|差分|違い).*シート|2つのシート/.test(c)) {
            boostName = "sheet.diff";
          } else if (candMap["sheet.list"] && /教え|確認|見せて|あるか|どんなシート|何枚/.test(c) && !/目次|インデックス|作/.test(c)) {
            boostName = "sheet.list";
          } else if (candMap["sheet.toc"] && /目次|インデックスシート|シート一覧/.test(c) && !/教え|確認|見せて|あるか|どんな/.test(c)) {
            boostName = "sheet.toc";
          } else if (candMap["sheet.sort"] && /(?:シート|タブ).*(?:名前順|昇順|降順|並べ替)/.test(c)) {
            boostName = "sheet.sort";
          } else if (candMap["sheet.gridlines"] && /(?:グリッド線|目盛り線|シート.*枠線|全シート.*枠線|枠線を非表示|枠線を表示)/.test(c) && !/(?:印刷|PDF|A4|A3|余白|ページ)/i.test(c) && !CELL_RE.test(c)) {
            boostName = "sheet.gridlines";
          } else if (candMap["sheet.snapshot"] && /スナップショット|日付[つ付入].*(?:複製|控え|コピー|保存)|控えを複製|今日の控え/.test(c)) {
            boostName = "sheet.snapshot";
          } else if (/書式|見た目/.test(c) && !/消|クリア|削除|外|解除/.test(c) && (scored[0].shelf.name === "copy" || scored[0].shelf.name === "copy.format")) {
            if (candMap["copy.format"] && candMap["copy"]) boostName = "copy.format";
          }
        }
        if (boostName) {
          for (var bsi = 0; bsi < scored.length; bsi++) {
            if (scored[bsi].shelf.name === boostName) {
              scored[bsi] = {
                total: Math.max(topBase, scored[bsi].total, WEAK_SCORE) + MARGIN,
                order: scored[bsi].order,
                shelf: scored[bsi].shelf,
                detail: scored[bsi].detail
              };
              break;
            }
          }
          scored.sort(function (a, b) {
            if (b.total !== a.total) return b.total - a.total;
            return a.order - b.order;
          });
        }
      }
      if (!scored.length) {
        p.reasons.push("「" + c + "」に当たる棚がありません");
        fatalErr = true;
        lastIncomplete = null;
        continue;
      }

      var lead = scored[0].total;
      var near = [];
      var hit = [];
      var far = [];
      for (var si = 0; si < scored.length; si++) {
        var x = scored[si];
        var isNear = (lead - x.total) <= EVIDENCE_GAP;
        if (isNear) near.push(x);
        if (_rxHitShelf(x.shelf, c)) {
          if (isNear) hit.push(x);
          else far.push(x);
        }
      }

      if (!boostName) {
        if (far.length && scored[0].shelf.name === "replace" && CELL_RE.test(c)) {
          var wItem = null;
          for (var fi = 0; fi < far.length; fi++) {
            if (far[fi].shelf.name === "write") {
              wItem = far[fi];
              break;
            }
          }
          if (wItem) {
            hit = [wItem];
            var newFar = [];
            for (var fi2 = 0; fi2 < far.length; fi2++) {
              if (far[fi2].shelf.name !== "write") newFar.push(far[fi2]);
            }
            far = newFar;
          }
        }

        if (far.length && !hit.length) {
          var topNmFar = scored[0].shelf.name || "";
          var intentActionFar = /解除|外し|外す|やめ|消|削除|クリア|一覧|教え|見|確認|動か|移動|入れ替/.test(c);
          var topIsActionFar = /(?:^|\.)(?:clear|remove|off|list|move|delete|diff|audit|check|extract)|^unfreeze$/.test(topNmFar);
          if (!(scored[0].total >= WEAK_SCORE && intentActionFar && topIsActionFar)) {
            p.reasons.push("「" + c + "」の当てが割れた（" + scored[0].shelf.name + " と " + far[0].shelf.name + "）");
            p.cards.push(scored[0].shelf, far[0].shelf);
            fatalErr = true;
            lastIncomplete = null;
            continue;
          }
        }

        if (hit.length === 1 && hit[0] !== scored[0]) {
          var h0 = hit[0];
          var s0Nm = scored[0].shelf.name || "";
          var intentAct = /解除|外し|外す|やめ|消|削除|クリア|一覧|教え|見|確認|動か|移動|入れ替/.test(c);
          var s0IsAct = /(?:^|\.)(?:clear|remove|off|list|move|delete|diff|audit|check|extract)|^unfreeze$/.test(s0Nm);
          if (!(scored[0].total >= WEAK_SCORE && intentAct && s0IsAct && h0.total < scored[0].total)) {
            var reordered = [{
              total: Math.max(lead, h0.total, WEAK_SCORE) + MARGIN,
              order: h0.order,
              shelf: h0.shelf,
              detail: h0.detail
            }];
            for (var ri2 = 0; ri2 < scored.length; ri2++) {
              if (scored[ri2] !== h0) reordered.push(scored[ri2]);
            }
            scored = reordered;
          }
        } else if (hit.length === 1) {
          scored[0] = {
            total: Math.max(scored[0].total, WEAK_SCORE) + MARGIN,
            order: scored[0].order,
            shelf: scored[0].shelf,
            detail: scored[0].detail
          };
        }
      }

      var topT = scored[0].total;
      var top = scored[0].shelf;
      var second = scored.length > 1 ? scored[1] : null;

      if (topT < WEAK_SCORE) {
        p.reasons.push("「" + c + "」の当てが弱い（" + top.name + "）");
        for (var k3 = 0; k3 < Math.min(3, scored.length); k3++) p.cards.push(scored[k3].shelf);
        fatalErr = true;
        lastIncomplete = null;
        continue;
      }
      if (second && (topT - second.total) < MARGIN) {
        p.reasons.push("「" + c + "」の当てが割れた（" + top.name + " と " + second.shelf.name + "）");
        for (var k4 = 0; k4 < Math.min(3, scored.length); k4++) p.cards.push(scored[k4].shelf);
        fatalErr = true;
        lastIncomplete = null;
        continue;
      }
      if (top.name === "api" || !top.searchable) {
        p.reasons.push("「" + c + "」は棚に無い頼みです");
        fatalErr = true;
        lastIncomplete = null;
        continue;
      }

      var bRes = buildOp(top, c, table, sheets, curSheet);
      var op = bRes.op;
      var missing = bRes.missing;
      var named = bRes.named;

      if (p.ops.length && p.ops[p.ops.length - 1].shelf === top.name) {
        var prev = p.ops[p.ops.length - 1];
        var carryKeys = ["header", "title", "range", "col"];
        for (var cki = 0; cki < carryKeys.length; cki++) {
          var sk = carryKeys[cki];
          if (_hasOwn(prev, sk) && !_hasOwn(op, sk)) {
            op[sk] = prev[sk];
            named = true;
            missing = _filterMissing(missing, ["range", "col", "header", "title"]);
          }
        }
        if (top.name === "format") {
          if (/色[もを]付[け言]|色[もを]つ[け言]|色[もを]塗/.test(c) && !op.bg && !op.color) {
            op.bg = "青";
          }
        }
      } else if (lastScope && typeof lastScope === "object" && (top.name === "format" || lastScope.from_browser) && (_hasNonMetaKeys(op) || missing.length)) {
        var fbRes = _applyScopeFallback(op, missing, lastScope, top, cRaw);
        missing = fbRes.missing;
        named = named || fbRes.added;
        if (top.danger && named && !VAGUE_RE.test(nfkc(cRaw)) && !missing.length) {
          op.ok = true;
        }
      }

      p.ops.push(op);
      if (missing.length) {
        var missStart = p.missing.length;
        for (var mi2 = 0; mi2 < missing.length; mi2++) {
          p.missing.push(top.name + ": " + missing[mi2]);
        }
        p.cards.push(top);
        lastIncomplete = {
          clause: c,
          top: top,
          missingN: missing.length,
          missStart: missStart,
          cardAdded: true
        };
      } else if (top.danger && !named && Object.keys(op).length === 1) {
        p.reasons.push("「" + c + "」は" + top.danger + "棚で、場所の名指しがありません");
        p.cards.push(top);
        fatalErr = true;
        lastIncomplete = null;
      } else {
        lastIncomplete = null;
      }
    }

    var hasGuideBlock = false;
    var isPureUndoAsk = /^(?:さっきの?|直前の?|1つ前の?|ひとつ前の?)?(?:元に戻|戻して|取り消|やり直)/.test(nfkc(askText).trim());
    for (var gi = 0; gi < p.guide.length; gi++) {
      var g = p.guide[gi];
      var isSoftGuide = (g.indexOf("棚はありません") >= 0 || g.indexOf("棚ではありません") >= 0) &&
        p.ops.some(function (o) {
          return /^(?:doc\.outline|filter\.where|filter\.on|filter\.off|filter\.extract|drive\.list|cf\.list|name\.list|protect\.list|note\.list|audit\.check|find|rows\.show|cols\.show|sheet\.show|top\.n)$/.test(o.shelf || "");
        });
      if (g.indexOf("外です") >= 0 || (g.indexOf("ws_undo") >= 0 && (!p.ops.length || isPureUndoAsk)) || (g.indexOf("ws_undo") < 0 && (g.indexOf("棚はありません") >= 0 || g.indexOf("棚ではありません") >= 0) && !isSoftGuide)) {
        hasGuideBlock = true;
        break;
      }
    }
    if (hasGuideBlock || (p.guide.length && !p.ops.length)) {
      p.reasons.push("案内が出ています（棚でない頼み）");
      fatalErr = true;
    }

    var kindsSeen = {};
    var kindsCount = 0;
    for (var oi = 0; oi < p.ops.length; oi++) {
      var shName = p.ops[oi].shelf;
      var shObj = _byName[shName];
      if (shObj && !shObj.shared && !_isLocalHandler(shName)) {
        if (!kindsSeen[shObj.kind]) {
          kindsSeen[shObj.kind] = true;
          kindsCount++;
        }
      }
    }
    if (kindsCount > 1) {
      p.reasons.push("シートの棚と文書の棚が混ざりました");
      fatalErr = true;
    }

    var seenCards = {};
    var uniqCards = [];
    for (var k5 = 0; k5 < p.cards.length; k5++) {
      var cs = p.cards[k5];
      if (!seenCards[cs.name]) {
        seenCards[cs.name] = true;
        uniqCards.push(cs);
        if (uniqCards.length >= 4) break;
      }
    }
    p.cards = uniqCards;
    // 同じ手が続いたら 1 つに（節が 2 つとも同じ棚に当たったとき）。足す・書く・埋める手は 2 回で意味が変わるのでまとめない
    var dd = [];
    for (var di = 0; di < p.ops.length; di++) {
      var o = p.ops[di];
      if (dd.length && JSON.stringify(o) === JSON.stringify(dd[dd.length - 1]) && !/insert|add|write|fill|copy|new/.test(String(o.shelf || ""))) continue;
      dd.push(o);
    }
    p.ops = dd;
    p.fire = (!fatalErr) && (!p.missing.length) && (p.ops.length > 0);
    if (!p.fire && !hasGuideBlock && !vagueM) {
      p.suggest = _suggestOps(askText, kind, table, sheets, curSheet, p.cards);
    }
    p.previewText = _buildPreviewText(p);
    return p;
  }

  // ------------------------------------------------------------------ 覚えた言い方（使う人が［はい］で決めた頼み→ops）
  var _learned = {};
  var LEARN_MAX = 300;

  function learnKey(askText) {
    return norm(String(askText || "").trim(), _synonyms).replace(/[。．.!！?？]+$/g, "");
  }

  function setLearned(map) {
    _learned = (map && typeof map === "object") ? map : {};
  }

  function getLearned() {
    return _learned;
  }

  // 頼みと ops を覚えて、覚えの全体（保存用）を返す
  function learn(askText, ops) {
    _ensureInit();
    var key = learnKey(askText);
    if (!key || !Array.isArray(ops) || !ops.length) return _learned;
    delete _learned[key];
    _learned[key] = JSON.parse(JSON.stringify(ops));
    var keys = Object.keys(_learned);
    while (keys.length > LEARN_MAX) {
      delete _learned[keys.shift()];
    }
    return _learned;
  }

  // 当たらなかった頼みに、引数まで決まる近い棚を 1 つ出す（消す・上書きの棚は出さない）
  function _suggestOps(askText, kind, table, sheets, curSheet, cards) {
    var cands = [];
    var seen = {};
    var add = function (sh) {
      // 外す・消す手（〜.clear・〜.remove・〜.off・un〜）と条件付き書式（条件を当て推量で決めてしまう）は候補にしない＝頼みと逆の手や見当違いの手を［はい］で撃たせない
      if (sh && /(^un|\.(clear|remove|off|delete)$|^cf\.)/.test(String(sh.name))) return;
      if (sh && !seen[sh.name] && sh.searchable !== false && sh.name !== "api" && !sh.danger) {
        seen[sh.name] = true;
        cands.push(sh);
      }
    };
    (cards || []).forEach(add);
    scoreAll(nfkc(askText), kind).slice(0, TOP_N).forEach(function (x) { add(x.shelf); });
    // 点が足りなくても、色・太字などの書式は引数が決まれば候補にする（値を消さない棚）
    if (kind !== "doc") add(_byName["format"]);
    for (var i = 0; i < cands.length; i++) {
      var b;
      try {
        b = buildOp(cands[i], nfkc(askText), table, sheets, curSheet);
      } catch (e) {
        continue;
      }
      if (b && b.op && !b.missing.length && _hasNonMetaKeys(b.op)) {
        return [b.op];
      }
    }
    return null;
  }

  var _planCore = plan;
  plan = function (askText, kind, table, sheets, curSheet, lastScope) {
    _ensureInit();
    var key = learnKey(askText);
    // 使う人が［はい］で覚えた言い方 → 配る言い方の表（combo_phrases.json・py gas.py combo phrase で足す）の順に見る
    var phrases = (typeof COMBO_PHRASES !== "undefined" && COMBO_PHRASES) || {};
    var hitOps = (key && _hasOwn(_learned, key)) ? _learned[key] : ((key && _hasOwn(phrases, key)) ? phrases[key] : null);
    if (hitOps) {
      var lp = { ops: JSON.parse(JSON.stringify(hitOps)), fire: true, learned: true, reasons: [], missing: [], cards: [], guide: [], previewText: "" };
      // 覚えた手・表の手に場所（範囲・列・見出し等）が無ければ、ふつうの棚当てと同じく選んでいる所で埋める
      // （埋めないと「range・col・header・title のどれかが要ります」で止まる）
      for (var li2 = 0; li2 < lp.ops.length; li2++) {
        var lsh = _byName[lp.ops[li2].shelf];
        if (lsh) _applyScopeFallback(lp.ops[li2], [], lastScope, lsh, askText);
      }
      lp.previewText = _buildPreviewText(lp);
      return lp;
    }
    return _planCore(askText, kind, table, sheets, curSheet, lastScope);
  };

  function renderUnfired(p) {
    _ensureInit();
    var lines = ["撃っていません: " + (p.reasons && p.reasons.length ? p.reasons.join("／") : "引数が決まりません")];
    if (p.missing && p.missing.length === 1 && p.ops && p.ops.length) {
      var m0 = p.missing[0];
      var idx = m0.indexOf(": ");
      var missName = idx >= 0 ? m0.slice(idx + 2) : m0;
      lines.push("この ops に " + missName + " を入れて ws_do(ops=…) で撃つ");
    } else if (p.missing && p.missing.length) {
      lines.push("足りない引数: " + p.missing.join("、"));
    }
    if (p.ops && p.ops.length) {
      lines.push("組みかけ: ops=" + JSON.stringify(p.ops));
    }
    if (p.guide && p.guide.length) {
      for (var gi = 0; gi < Math.min(2, p.guide.length); gi++) {
        lines.push("案内: " + p.guide[gi]);
      }
    }
    if (p.cards && p.cards.length) {
      lines.push("候補の札:");
      for (var ci = 0; ci < p.cards.length; ci++) {
        var c = card(p.cards[ci], false);
        lines.push((ci + 1) + ". " + c[0]);
        for (var k = 1; k < c.length; k++) lines.push(c[k]);
      }
    }
    lines.push("決まったら ws_do(ops=…) で撃つ（足りない物が人にしか分からないときだけ聞く）。");
    return lines.join("\n");
  }

  function getCatalog() {
    _ensureInit();
    return {
      shelves: _shelves,
      byName: _byName,
      synonyms: _synonyms,
      guide: _guide,
      categories: _categories
    };
  }

  return {
    init: init,
    nfkc: nfkc,
    norm: norm,
    scoreAll: scoreAll,
    find: find,
    ask: ask,
    parseSelectionScope: parseSelectionScope,
    _expandSelectionPronouns: _expandSelectionPronouns,
    expandSelectionPronouns: _expandSelectionPronouns,
    buildOp: buildOp,
    _applyScopeFallback: _applyScopeFallback,
    applyScopeFallback: _applyScopeFallback,
    plan: plan,
    learn: learn,
    learnKey: learnKey,
    setLearned: setLearned,
    getLearned: getLearned,
    formatOpsShort: formatOpsShort,
    renderUnfired: renderUnfired,
    card: card,
    getCatalog: getCatalog,
    MIN_SCORE: MIN_SCORE,
    WEAK_SCORE: WEAK_SCORE,
    NAME_BONUS: NAME_BONUS
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ComboPlanner;
}
