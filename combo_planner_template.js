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

  var VAGUE_RE = /いらない|要らない|不要な?|余分なところ|余分な箇所|古い(?!順|ものから|方から|ほうから|のから)|おかしい|この辺|どこか|適当に|いい感じ|ダブってる人|変な/;
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
    /[^\s、,。]{1,16}(?:(?:の|が)(?:昇順|降順|(?:大きい|小さい|高い|低い|多い|少ない|古い|新しい|若い|遅い)(?:順|ものから|方から|ほうから|のから))|ごと(?:に?かためて並べ(?:てもらっ)?て?)?)(?:[、,]\s*(?:その中で\s*|同じ[^\s、,。]{1,12}の中は\s*|同[^\s、,。]{1,12}内は\s*)?[^\s、,。]{1,16}(?:の|が)(?:昇順|降順|(?:大きい|小さい|高い|低い|多い|少ない|古い|新しい|若い|遅い)(?:順|ものから|方から|ほうから|のから)))+/g,
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
  var _CALC_VERB_PREFIX_RE_JS = /^.*?(?:(?:差し引い|掛け|かけ|足し|たし|引い|ひい|割っ|わっ|乗算し|加算し|減算し|除算し|計算し)(?:た|て)|(?:掛け算|かけ算|足し算|引き算|割り算|[0-9]+(?:\.[0-9]+)?\s*倍|[0-9]+(?:\.[0-9]+)?\s*割(?:増し?|引き?)|半分)(?:の|で|した))\s*/;

  // 任意（非必須）の列引数へ無関係な列名が流れ込まないようにするキーワード条件（1 か所管理）
  var _OPT_COL_CUES_JS = {
    at: /(?:列|欄)[にへ]|の間に/,
    renumber: /連番|通し番号|番号を?(?:振|付)|振り直|ふり直|付け直|つけ直|ナンバリング/,
    number: /連番|通し番号/,
    total: /合計|総計|小計/,
    url_col: /url|リンク先|アドレス/i
  };

  // cols.delete の型ガード（列そのものが消す対象のときだけ許可し、「列の〈中身〉を消して」は列削除にしない）
  var _COL_CONTENT_DEL_RE_JS = /中身|値だけ|値を|データだけ|データを|クリア|空白|スペース|改行|重複|ダブ|エラー|記号|ハイフン|文字|数字|数値|数式|式だけ|式を|ゼロ|0を|色|背景|書式|罫線|太字|メモ|コメント|リンク|プルダウン|入力規則|フィルタ|フィルター|条件付き書式|前後|余分な|ゴミ|不可視|非表示|隠|振り直|付け直|連番|行を|の行|行目/;
  var _COL_PROP_OBJ_RE_JS = /(?:列|カラム)の(?!削除|消去|除去|一番|右|左|先頭|末尾|最後|最初)[^\s、。のをにはが]{1,16}を/;
  var _COL_DIRECT_DEL_RE_JS = /(?:列|カラム)(?:を|ごと|丸ごと|まるごと|まるっと|の(?:削除|消去|除去)|(?:は|が)?(?:いらない|要らない|不要|削除|消))/;

  // 条件つき書式（行ごと）の対象名詞型（「〈列〉が〈条件〉の〈何か〉を〈書式〉に」、ただし「セル」は列単体のまま維持）
  var _ROW_CF_THING_RE_JS = /行全体|の行(?:に|を|全部|だけ|は)?|行に色|行を目立|行を(?:赤|黄|青|緑|黒|白|薄|濃|橙|灰|紫|水色|紺|茶|桃|太字)|いない行|ない行|(?:になって(?:いる|る)|の)(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)|(?:以上|以下|未満|より大き(?:い|く)?|より小さ(?:い|く)?|より前|より後|以前|以降|を超え?|上回[るっ]|下回[るっ]|届か(?:ない)?|届いてい?ない|以外|ではない|でない|じゃない|になって(?:いない|ない|いる|る)|マイナス|負の値)(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)|(?:書かれ|記載され|入力され|入っ|含まれ|含[むみ]|とある)(?:てい?る|た)?(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線|空白|スペース|表記|表示|形式)[^\s、。のをにはが]{1,12}(?:を|に|は)/;
  var _COND_EQ_THING_RE_JS = /([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)[『「]?([^』」\s、。の]+?)[』」]?(?:になって(?:いる|る)|の)(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線)[^\s、。のをにはが]{1,12}/;

  function _twoColCmpOfJs(text, table) {
    if (!table || !Array.isArray(table.columns) || !table.columns.length) return null;
    var tN = nfkc(text);
    var re = /([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)([^\s、。をに]{1,16}?)(?:列)?(?:を(下回[るっ]|上回[るっ]|超え?る?|超え)|に(届か(?:ない)?|届いてい?ない)|(下回[るっ]|上回[るっ]|超え?る?|超え|届か(?:ない)?|届いてい?ない|より大き(?:い|く)?|より小さ(?:い|く)?|以上|以下|未満|と等しい|と同じ|と一致|と違う|と異なる|以外|ではない|でない|じゃない))/g;
    var m;
    while ((m = re.exec(tN)) !== null) {
      var r1 = m[1].trim(), r2 = m[2].trim();
      var c1 = _resolveColRefJs(r1, table) || (r1.indexOf("の") >= 0 ? _resolveColRefJs(r1.slice(r1.lastIndexOf("の") + 1), table) : null);
      var c2 = _resolveColRefJs(r2, table);
      if (!c1 || !c2 || c1 === c2) continue;
      var kw = m[3] || m[4] || m[5] || "";
      var sym;
      if (/下回|未満|より小さ|届か|届いて/.test(kw)) sym = "<";
      else if (/上回|超|より大き/.test(kw)) sym = ">";
      else if (kw.indexOf("以上") >= 0) sym = ">=";
      else if (kw.indexOf("以下") >= 0) sym = "<=";
      else if (/等しい|同じ|一致/.test(kw)) sym = "=";
      else sym = "<>";
      return [c1, sym, c2];
    }
    return null;
  }

  // 「〈日付の列〉から N 日／週間／か月／年 後・前」→ [式, 列名]（Python _date_shift_of と同じ）
  function _dateShiftOfJs(text, table) {
    var m = /([^\s、。をにがはで]{1,16}?)(?:列)?(?:から|の)([0-9]+)\s*(日|週間|週|か月|ヶ月|カ月|ヵ月|ケ月|月|年)(後|前)/.exec(nfkc(text));
    if (!m) return null;
    var hasCols = !!(table && Array.isArray(table.columns) && table.columns.length);
    var col = hasCols ? _resolveColRefJs(m[1].trim(), table) : m[1].trim();
    if (!col) return null;
    var n = parseInt(m[2], 10), unit = m[3], d = m[4], sign = d === "後" ? "+" : "-", expr;
    if (unit === "日") expr = col + sign + n;
    else if (unit === "週間" || unit === "週") expr = col + sign + (n * 7);
    else expr = "EDATE(" + col + "," + (sign === "+" ? "" : "-") + (unit === "年" ? n * 12 : n) + ")";
    return [expr, n + unit + d];
  }

  // 表の列名（「メモ」「コメント」等）を伏せる。除外語の判定が列名に引っかからないように（Python _mask_col_names と同じ）
  function _maskColNamesJs(text, table) {
    if (!table || !Array.isArray(table.columns)) return text;
    var names = table.columns.map(function (c) { return String((c && c.name) || ""); }).filter(function (n) { return n.length >= 2; });
    names.sort(function (a, b) { return b.length - a.length; });
    var out = text;
    names.forEach(function (n) { out = out.split(n).join("□"); });
    return out;
  }

  // 行ごとの条件付き書式で「空欄」「今日より前」等を文字のまま式に入れない（Python _cf_blank_today_expr と同じ）
  function _cfBlankTodayExprJs(text, refL, r1) {
    var t = nfkc(text), c = "$" + refL + r1;
    if (/(?:空欄|空白)(?:以外|ではない|でない|じゃない)|入力済/.test(t)) return "=" + c + "<>\"\"";
    if (/空欄|空白|未入力|入力されていない/.test(t)) return "=" + c + "=\"\"";
    if (/今日(?:より前|以前|を過ぎ|が過ぎ)|期限切れ|期限が切れ|期限を過ぎ/.test(t)) return "=AND(ISNUMBER(" + c + ")," + c + (t.indexOf("以前") >= 0 ? "<=" : "<") + "TODAY())";
    if (/今日(?:より後|以降|より先)/.test(t)) return "=AND(ISNUMBER(" + c + ")," + c + (t.indexOf("以降") >= 0 ? ">=" : ">") + "TODAY())";
    var mY = /((?:19|20)[0-9]{2})年(以前|まで|以降|から|より前|より後|より新しい|より古い)/.exec(t);
    if (mY) {
      var symY = { "以前": "<=", "まで": "<=", "より前": "<", "より古い": "<", "以降": ">=", "から": ">=", "より後": ">", "より新しい": ">" }[mY[2]];
      return "=AND(ISNUMBER(" + c + "),YEAR(" + c + ")" + symY + mY[1] + ")";
    }
    return "";
  }

  // 「2020年以降」→ ["ge", "2020/01/01"] 等（Python _year_cmp_of と同じ）
  function _yearCmpOfJs(text) {
    var m = /((?:19|20)[0-9]{2})年(以前|まで|以降|から|より前|より後|より新しい|より古い)/.exec(nfkc(text));
    if (!m) return null;
    var y = m[1];
    return ({"以降": ["ge", y + "/01/01"], "から": ["ge", y + "/01/01"], "より後": ["gt", y + "/12/31"], "より新しい": ["gt", y + "/12/31"],
             "以前": ["le", y + "/12/31"], "まで": ["le", y + "/12/31"], "より前": ["lt", y + "/01/01"], "より古い": ["lt", y + "/01/01"]})[m[2]];
  }

  // 1 つの条件 → 式の中身（= なし）。読めなければ ""（Python _cf_atom と同じ）
  function _cfAtomJs(cond, refL, r1) {
    var e = _cfBlankTodayExprJs(cond, refL, r1);
    if (e) return e.slice(1);
    var c = "$" + refL + r1;
    var m = /(-?[0-9][0-9,\.]*)\s*([万億千]?)\s*(?:(?!(?:以上|以下|未満|より|超|上回|下回))[^\s、。0-9]{0,6})?\s*(以上|以下|未満|より大きい|より小さい|を超え(?:る|た)?|超え?|を下回る|を上回る)/.exec(nfkc(cond));
    if (m) {
      var n = m[1].replace(/,/g, ""), w = m[3];
      var mul = ({"万": 10000, "億": 100000000, "千": 1000})[m[2] || ""] || 1;
      if (mul !== 1) n = String(parseFloat(n) * mul);
      var sym = w === "以上" ? ">=" : w === "以下" ? "<=" : (w === "未満" || w === "より小さい" || w === "を下回る") ? "<" : ">";
      return c + sym + n;
    }
    var lit = nfkc(cond).trim().replace(/^[「『]+|[」』]+$/g, "");
    if (lit && /^[^\s、。をにがはでの]{1,16}$/.test(lit) && !/以上|以下|未満|より|超|以外|ない|前|後/.test(lit)) return c + "=\"" + lit + "\"";
    return "";
  }

  // 「〈列A〉が〈条件〉で〈列B〉が〈条件〉の行」→ [式, 読めたか]（Python _cf_compound_expr と同じ）
  function _cfCompoundExprJs(text, table) {
    if (!table || !Array.isArray(table.columns) || !table.columns.length) return null;
    var t = nfkc(text);
    var m = /([^\s、。をに]{1,16}?)(?:列)?(?:が|は)(.+?)(?:で|かつ|且つ|、かつ|、)([^\s、。をに]{1,16}?)(?:列)?(?:が|は)(.+?)(?:の行|行を|行全体|行に)/.exec(t);
    if (!m) return null;
    var c1 = _resolveColRefJs(m[1], table), c2 = _resolveColRefJs(m[3], table);
    if (!c1 || !c2 || c1 === c2) return null;
    var l1 = _letterOf(table, c1), l2 = _letterOf(table, c2);
    var sp = _dataSpan(table);
    var r1 = sp ? sp[0] : ((table.header_row || 1) + 1);
    var a1 = _cfAtomJs(m[2], l1, r1), a2 = _cfAtomJs(m[4], l2, r1);
    if (a1 && a2) return ["=AND(" + a1 + "," + a2 + ")", true];
    return ["", false];
  }

  // 「国語と数学と英語の合計の列」「3教科の平均の列」→ [式, 列名]（Python _multi_col_agg_of と同じ）
  function _multiColAggOfJs(text, table) {
    if (!table || !Array.isArray(table.columns) || !table.columns.length) return null;
    var t = nfkc(text);
    var mK = /の?(合計|和|平均)(?:点|値)?の?(?:列|欄)/.exec(t);
    if (!mK) return null;
    var kind = mK[1] === "平均" ? "平均" : "合計";
    var head = t.slice(0, mK.index);
    var nums = table.columns.filter(function (c) { return c && c.number; }).map(function (c) { return String(c.name || ""); });
    var cols = [];
    var mN = /([0-9]+|全|各)(?:教科|科目|項目|つの(?:点数|数値|列))/.exec(head);
    if (mN) {
      if (mN[1] === "全" || mN[1] === "各" || parseInt(mN[1], 10) === nums.length) cols = nums.slice();
    } else {
      var parts = head.split(/と|・|、|,/);
      var nonEmpty = 0;
      for (var i = 0; i < parts.length; i++) {
        if (!parts[i].trim()) continue;
        nonEmpty++;
        var r = _resolveColRefJs(parts[i].trim(), table);
        if (r && cols.indexOf(r) < 0) cols.push(r);
      }
      if (cols.length !== nonEmpty) return null;
    }
    if (cols.length < 2 || cols.some(function (c) { return nums.indexOf(c) < 0; })) return null;
    return [kind === "合計" ? cols.join("+") : "AVERAGE(" + cols.join(",") + ")", kind];
  }

  function _colContainsOfJs(text, table) {
    var tN = nfkc(text);
    var hasCols = !!(table && Array.isArray(table.columns) && table.columns.length);
    var re = /([^\s、。をがはで]{1,16}?)(?:列)?(?:に|が|は)(?:[『「]([^』」]{1,24}?)[』」]|([^』」\s、。をにがは]{1,20}?))(?:(?:と|が)(?:書かれ|記載|入力され|入っ|含まれ)(?!て?い?な|て?な|な|ず)|を含[むみん](?!で?い?な|で?な|な)|とある(?!わけではな))/g;
    var m;
    while ((m = re.exec(tN)) !== null) {
      var r1 = m[1].trim(), word = (m[2] || m[3] || "").trim();
      if (!word) continue;
      if (hasCols) {
        var c1 = _resolveColRefJs(r1, table) || (r1.indexOf("の") >= 0 ? _resolveColRefJs(r1.slice(r1.lastIndexOf("の") + 1), table) : null);
        if (!c1) continue;
        return [c1, word];
      }
      return [r1, word];
    }
    return null;
  }

  function _calcDiffColsOfJs(text, table) {
    var tN = nfkc(text);
    var hasCols = !!(table && Array.isArray(table.columns) && table.columns.length);
    var re = /([^\s、。をにとがは]{1,16}?)(?:列)?と([^\s、。をにとがは]{1,16}?)(?:列)?の(?:差額?|差分|差と伸び率|伸び率|増減率)/g;
    var m;
    while ((m = re.exec(tN)) !== null) {
      var r1 = m[1].trim(), r2 = m[2].trim();
      if (hasCols) {
        var c1 = _resolveColRefJs(r1, table) || (r1.indexOf("の") >= 0 ? _resolveColRefJs(r1.slice(r1.lastIndexOf("の") + 1), table) : null);
        var c2 = _resolveColRefJs(r2, table);
        if (!c1 || !c2 || c1 === c2) continue;
        return [c1, c2];
      }
      if (r1 && r2 && r1 !== r2) return [r1, r2];
    }
    return null;
  }

  function _colLetToNumJs(s) {
    var n = 0;
    for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
    return n;
  }

  function _condColOfJs(text, table) {
    var tN = nfkc(text);
    var re = /([^\s、。をにで]{1,16}?)(?:列)?(?:が|は)/g;
    var m;
    while ((m = re.exec(tN)) !== null) {
      var res = _resolveColRefJs(m[1].trim(), table);
      if (res) return res;
    }
    return null;
  }

  // 日付比較の 1 か所定義（西暦・和暦・年なし月日）
  var _DATE_TOK_PAT_JS =
    "(?<![0-9A-Za-z/])(" +
    "[0-9]{4}\\s*[/\\-.年]\\s*[0-9]{1,2}\\s*[/\\-.月]\\s*[0-9]{1,2}\\s*日?" +
    "|(?:令和|平成|昭和|大正|明治|[RrHhSsTtMm])\\s*(?:元|[0-9]{1,2})\\s*[/\\-.年]\\s*[0-9]{1,2}\\s*[/\\-.月]\\s*[0-9]{1,2}\\s*日?" +
    "|[0-9]{1,2}\\s*月\\s*[0-9]{1,2}\\s*日" +
    "|[0-9]{1,2}/[0-9]{1,2}" +
    ")(?![0-9/])";
  var _DATE_RANGE_CMP_RE_JS = new RegExp(_DATE_TOK_PAT_JS + "\\s*(?:から|〜|~|～)\\s*" + _DATE_TOK_PAT_JS + "\\s*(?:まで)?");
  var _DATE_SINGLE_CMP_RE_JS = new RegExp(
    _DATE_TOK_PAT_JS + "\\s*(より以前|より前|以前|より以降|より後|以降|の前|の後|から|まで|以上|以下|未満|より大き(?:い|く)?|を超え?|より小さ(?:い|く)?)"
  );
  var _DATE_CMP_CUE_RE_JS = new RegExp(
    "より以前|より前|より以降|より後|以前|以降|" + _DATE_TOK_PAT_JS + "\\s*(?:の前|の後|から|まで)"
  );
  var _ERA_BASE_JS = { "令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925, "大正": 1911, "T": 1911, "明治": 1867, "M": 1867 };

  function _pad2Js(n) { return n < 10 ? ("0" + n) : String(n); }
  function _pad4Js(n) { var s = String(n); while (s.length < 4) s = "0" + s; return s; }

  function _parseCmpDateStrJs(raw) {
    var s = nfkc(String(raw === null || raw === undefined ? "" : raw)).trim();
    if (!s) return null;
    var m = /^([0-9]{4})\s*[/\-.年]\s*([0-9]{1,2})\s*[/\-.月]\s*([0-9]{1,2})\s*日?$/.exec(s);
    if (m) {
      var y = parseInt(m[1], 10), mo = parseInt(m[2], 10), d = parseInt(m[3], 10);
      if (y < 1868 || y > 2100 || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
      var dt = new Date(y, mo - 1, d);
      if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
      return _pad4Js(y) + "-" + _pad2Js(mo) + "-" + _pad2Js(d);
    }
    var mw = /^(令和|平成|昭和|大正|明治|[RrHhSsTtMm])\s*(元|[0-9]{1,2})\s*[/\-.年]\s*([0-9]{1,2})\s*[/\-.月]\s*([0-9]{1,2})\s*日?$/.exec(s);
    if (mw) {
      var base = _ERA_BASE_JS[mw[1].toUpperCase()];
      var ey = mw[2] === "元" ? 1 : parseInt(mw[2], 10);
      if (!base || ey < 1 || ey > 99) return null;
      var yw = base + ey, mow = parseInt(mw[3], 10), dw = parseInt(mw[4], 10);
      if (mow < 1 || mow > 12 || dw < 1 || dw > 31) return null;
      var dtw = new Date(yw, mow - 1, dw);
      if (dtw.getFullYear() !== yw || dtw.getMonth() !== mow - 1 || dtw.getDate() !== dw) return null;
      return _pad4Js(yw) + "-" + _pad2Js(mow) + "-" + _pad2Js(dw);
    }
    var md = /^([0-9]{1,2})\s*(?:月|\/)\s*([0-9]{1,2})\s*日?$/.exec(s);
    if (md) {
      var mom = parseInt(md[1], 10), dm = parseInt(md[2], 10);
      if (mom < 1 || mom > 12 || dm < 1 || dm > 31) return null;
      var dtm = new Date(2024, mom - 1, dm);
      if (dtm.getMonth() !== mom - 1 || dtm.getDate() !== dm) return null;
      return _pad2Js(mom) + "/" + _pad2Js(dm);
    }
    return null;
  }

  function _dateCmpToFormulaAtomJs(dStr, table) {
    var s = String(dStr || "");
    var mFull = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(s);
    if (mFull) {
      return "DATE(" + parseInt(mFull[1], 10) + "," + parseInt(mFull[2], 10) + "," + parseInt(mFull[3], 10) + ")";
    }
    var mMd = /^([0-9]{2})\/([0-9]{2})$/.exec(s);
    if (mMd) {
      var yHint = null;
      var rows = (table && Array.isArray(table.rows)) ? table.rows : [];
      for (var ri = 0; ri < rows.length && !yHint; ri++) {
        if (!Array.isArray(rows[ri])) continue;
        for (var ci = 0; ci < rows[ri].length; ci++) {
          var my = /^\s*([12][0-9]{3})[/\-.年]/.exec(nfkc(String(rows[ri][ci] === null || rows[ri][ci] === undefined ? "" : rows[ri][ci])));
          if (my) { yHint = parseInt(my[1], 10); break; }
        }
      }
      var yExpr = yHint ? String(yHint) : "YEAR(TODAY())";
      return "DATE(" + yExpr + "," + parseInt(mMd[1], 10) + "," + parseInt(mMd[2], 10) + ")";
    }
    return null;
  }

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
    var tN = nfkc(text);
    // 0. 日付の比べ（より前・より後・以降・以前・から・まで・範囲）を 1 か所で最優先解決
    var mDr = _DATE_RANGE_CMP_RE_JS.exec(tN);
    if (mDr) {
      var d1 = _parseCmpDateStrJs(mDr[1]);
      var d2 = _parseCmpDateStrJs(mDr[2]);
      if (d1 && d2) {
        opObj.when = "between";
        opObj.value = d1 + ".." + d2;
        delete opObj.equals;
        return;
      }
    }
    var mDs = _DATE_SINGLE_CMP_RE_JS.exec(tN);
    if (mDs) {
      var dNorm = _parseCmpDateStrJs(mDs[1]);
      if (dNorm) {
        var kw = mDs[2];
        if (kw === "より前" || kw === "より以前" || kw === "の前" || kw === "未満" || kw.indexOf("より小さ") === 0) {
          opObj.when = "lt";
        } else if (kw === "以前" || kw === "まで" || kw === "以下") {
          opObj.when = "le";
        } else if (kw === "より後" || kw === "より以降" || kw === "の後" || kw.indexOf("より大き") === 0 || kw.indexOf("を超") === 0) {
          opObj.when = "gt";
        } else {
          opObj.when = "ge";
        }
        opObj.value = dNorm;
        delete opObj.equals;
        return;
      }
    }

    var w = opObj.when;
    if (w !== "gt" && w !== "ge" && w !== "lt" && w !== "le" && w !== "eq" && w !== "ne") return;
    var mNum = /(-?[0-9][0-9,\.]*%?[万億]?)(?:(?!(?:以上|以下|未満|より|超|上回|下回|届|以外|では|でな|じゃな|にな|の行|のセ|なら|判定))[^\s、。0-9]{0,6})?\s*(?:以上|以下|未満|より|(?:を)?超|(?:を)?上回|(?:を)?下回|(?:に)?届か|(?:に)?届いてい?ない|になっていない|になってない|ではない|でない|じゃない|以外|の行|のセル|なら|判定)/.exec(tN);
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

  function _parseDateOrdJs(val, fallbackYear) {
    var norm = _parseCmpDateStrJs(val);
    if (!norm) return null;
    if (norm.indexOf("-") >= 0) {
      var ps = norm.split("-");
      return parseInt(ps[0], 10) * 10000 + parseInt(ps[1], 10) * 100 + parseInt(ps[2], 10);
    }
    var pm = norm.split("/");
    var y = fallbackYear || (new Date()).getFullYear();
    return y * 10000 + parseInt(pm[0], 10) * 100 + parseInt(pm[1], 10);
  }

  function _matchRowCondJs(cellVal, when, target) {
    var w = String(when || "eq").toLowerCase();
    var blank = cellVal === null || cellVal === undefined || String(cellVal).trim() === "";
    if (w === "blank") return blank;
    if (w === "notblank") return !blank;
    var tgt = (target === null || target === undefined) ? "" : String(target).trim();
    if (w === "contains") return !blank && String(cellVal).indexOf(tgt) >= 0;
    if (w === "between" && tgt.indexOf("..") >= 0) {
      var bps = tgt.split("..");
      var cd0 = _parseDateOrdJs(cellVal);
      var yFb0 = cd0 ? Math.floor(cd0 / 10000) : null;
      var d1 = _parseDateOrdJs(bps[0], yFb0), d2 = _parseDateOrdJs(bps[1], yFb0);
      if (cd0 === null || d1 === null || d2 === null) return false;
      var lo = d1 <= d2 ? d1 : d2, hi = d1 <= d2 ? d2 : d1;
      return cd0 >= lo && cd0 <= hi;
    }
    if (!/^-?[0-9,]+(?:\.[0-9]+)?$/.test(tgt)) {
      var cd = _parseDateOrdJs(cellVal);
      var yFb = cd ? Math.floor(cd / 10000) : null;
      var td = _parseDateOrdJs(tgt, yFb);
      if (td !== null) {
        if (cd === null) return w === "ne";
        if (w === "gt") return cd > td;
        if (w === "ge") return cd >= td;
        if (w === "lt") return cd < td;
        if (w === "le") return cd <= td;
        if (w === "ne") return cd !== td;
        return cd === td;
      }
    }
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
      .replace(/＋/g, "+").replace(/−/g, "-");
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

  function _headerGroupsJs(tbl) {
    if (!tbl || !Array.isArray(tbl.columns) || !tbl.columns.length) return {};
    var hasNum = false;
    for (var i = 0; i < tbl.columns.length; i++) {
      if (tbl.columns[i] && tbl.columns[i].number) { hasNum = true; break; }
    }
    var groups = {};
    for (var j = 0; j < tbl.columns.length; j++) {
      var c = tbl.columns[j];
      if (!c) continue;
      var nm = String(c.name || "").trim();
      var dot = nm.indexOf("・");
      if (dot <= 0) continue;
      if (hasNum && !c.number) continue;
      var parent = nm.slice(0, dot).trim();
      if (parent) {
        if (!groups[parent]) groups[parent] = [];
        groups[parent].push(nm);
      }
    }
    var out = {};
    var keys = Object.keys(groups);
    for (var k = 0; k < keys.length; k++) {
      if (groups[keys[k]].length >= 2) out[keys[k]] = groups[keys[k]];
    }
    return out;
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
          if (word === "白" && ((pos > 0 && "空余明面告".indexOf(text.charAt(pos - 1)) >= 0) || (pos + 1 < text.length && text.charAt(pos + 1) === "紙"))) {
            start = pos + 1;
            continue;
          }
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
    if (shN !== "api" && /下線|アンダーライン|取り消し線|打ち消し線|取消線|縦書き|斜め文字|文字を回転|テキストを回転/.test(scanN)) {
      addMiss("未対応の書式指示（下線・取り消し線・回転等）");
    }
    if (shN === "format") {
      var mEqF = _COND_EQ_THING_RE_JS.exec(scanN);
      var hasEqColF = !!(mEqF && (!tbl || !Array.isArray(tbl.columns) || !tbl.columns.length || _resolveColRefJs(mEqF[1], tbl)));
      var hasRowCond = /[^\s、。]+?(?:が|は)[^\s、。の]+?の行/.test(scanN) ||
        hasEqColF ||
        !!_twoColCmpOfJs(scanN, tbl) ||
        !!_colContainsOfJs(txt, tbl) ||
        /(?:以上|以下|未満|より大き|より小さ|より前|より後|以前|以降|を超|超え|上回|下回|届か|届いてい?ない|マイナス|負の値|空欄|空白|以外|ではない|になってない|になっている|になってる).{0,8}(?:の行|行を|行に|行全体|のセル|セルを|(?:の)?(?!セル|列|値|背景|文字|色|書式|フォント|サイズ|幅|高さ|罫線|枠線)[^\s、。のをにはが]{1,12}(?:を|に|は))/.test(scanN) ||
        (_DATE_CMP_CUE_RE_JS.test(scanN) && /(?:の行|行を|行に|行全体|のセル|セルを)/.test(scanN));
      if (hasRowCond) addMiss("条件付き書式（cf.add）の条件");
      if (/固定|フリーズ/.test(scanN)) addMiss("固定（freeze）の指定");
      if (/並べ替|ソート/.test(scanN)) addMiss("並べ替え（sort）の指定");
      if (/フィルタ|絞り込/.test(scanN)) addMiss("絞り込み（filter）の指定");
      if (scanN.indexOf("太字") >= 0 && !_hasOwn(opObj, "bold")) addMiss("太字（bold）");
      if (/斜体|イタリック/.test(scanN) && !_hasOwn(opObj, "italic")) addMiss("斜体（italic）");
      if (/中央揃え|中央寄せ|中央に|真ん中に|右揃え|右寄せ|左揃え|左寄せ/.test(scanN) && !_hasOwn(opObj, "align")) addMiss("配置（align）");
      if (scanN.indexOf("折り返") >= 0 && !_hasOwn(opObj, "wrap")) addMiss("折り返し（wrap）");
      if (/罫線|外枠/.test(scanN) && !_hasOwn(opObj, "borders")) addMiss("罫線（borders）");
      if (/結合|マージ/.test(scanN) && !_hasOwn(opObj, "merge")) addMiss("結合（merge）");
      if (/二重線|点線|破線/.test(scanN)) addMiss("罫線の種類（formatは実線のみ）");
      if (/(?:パーセント|%\s*表示|桁区切|カンマ区切|通貨形式|円マーク|年月日の?形|年月日形式|yyyy|hh:mm|曜日)/i.test(scanN) && !_hasOwn(opObj, "number_format")) {
        addMiss("表示形式（number_format）");
      }
      if (cHits.length && !opObj.bg && !opObj.color) addMiss("色（color/bg）");
    }
    if (shN === "cf.add") {
      if (!opObj.bg && !opObj.color && (opObj.bold === undefined || opObj.bold === null)) {
        addMiss("書式（bg・color・bold）");
      }
      if ((opObj.when === "gt" || opObj.when === "ge" || opObj.when === "lt" || opObj.when === "le" || opObj.when === "eq" || opObj.when === "ne" || opObj.when === "between" || opObj.when === "contains" || opObj.when === "formula") && _isEmptyVal(opObj.value)) {
        addMiss("value");
      }
    }
    if (shN === "filter.where" || shN === "filter.delete" || shN === "filter.extract") {
      if ((/以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|を含|含む|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄/.test(scanN) || _DATE_CMP_CUE_RE_JS.test(scanN) || !!_colContainsOfJs(txt, tbl)) && !opObj.when) {
        addMiss("条件（when）");
      }
      if (!opObj.when && _isEmptyVal(opObj.equals) && _isEmptyVal(opObj.value)) {
        addMiss("絞り込み条件（equals/when）");
      }
      if ((opObj.when === "gt" || opObj.when === "ge" || opObj.when === "lt" || opObj.when === "le" || opObj.when === "ne" || opObj.when === "between" || opObj.when === "contains") && _isEmptyVal(opObj.value)) {
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
        var eToks = nfkc(String(opObj.expr)).replace(/[A-Za-z]+(?=\()/g, " ").split(/[*/+\-(),]/);
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
        var mFm = /\$([A-Z]{1,3})[0-9]+\)?\s*(?:>=|<=|<>|>|<|=)\s*(-?[0-9]+(?:\.[0-9]+)?)/.exec(opObj.value);
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
        var pctGrounded = null;
        var colsMetaP = (tbl && tbl.columns) || [];
        var colIdxP = -1;
        for (var cpi = 0; cpi < colsMetaP.length; cpi++) {
          if (colsMetaP[cpi] && (colsMetaP[cpi].name === cmpCol || colsMetaP[cpi].col === cmpCol)) { colIdxP = cpi; break; }
        }
        if (colIdxP >= 0) {
          var cMetaP = colsMetaP[colIdxP];
          var fmtP = String(cMetaP.number_format || cMetaP.numberFormat || cMetaP.format || "");
          if (cMetaP.percent === true || fmtP.indexOf("%") >= 0 || fmtP.indexOf("％") >= 0) {
            pctGrounded = true;
          } else if (fmtP) {
            pctGrounded = false;
          } else if (tbl && Array.isArray(tbl.rows) && tbl.rows.length) {
            var hasGt1 = false, hasPctVal = false;
            for (var rpi = 0; rpi < tbl.rows.length; rpi++) {
              var rRow = tbl.rows[rpi];
              if (Array.isArray(rRow) && colIdxP < rRow.length) {
                var rvP = rRow[colIdxP];
                if (typeof rvP === "string" && (rvP.indexOf("%") >= 0 || rvP.indexOf("％") >= 0)) hasPctVal = true;
                else if (typeof rvP === "number") {
                  if (Math.abs(rvP) > 1.0) hasGt1 = true;
                  else if (Math.abs(rvP) > 0 && Math.abs(rvP) <= 1.0) hasPctVal = true;
                }
              }
            }
            if (hasGt1) pctGrounded = false;
            else if (hasPctVal) pctGrounded = true;
          }
        }
        var pctGroundedName = (pctGrounded === null) ? /(?:率|割合|構成比|%|％)/.test(String(cmpCol)) : pctGrounded;
        var cmpNumVal = Number(cmpNumStr);
        if (Math.abs(cmpNumVal) > 1.0) {
          if (shN === "cf.add" && (pctGrounded === true || pctGroundedName)) {
            var spP = _dataSpan(tbl);
            var r1P = spP ? spP[0] : ((tbl && tbl.header_row ? tbl.header_row : 1) + 1);
            var r2P = spP ? spP[1] : r1P;
            var pctColL = tbl ? _letterOf(tbl, cmpCol) : null;
            if (pctColL) {
              var decVal = String(Number((cmpNumVal / 100.0).toPrecision(10)));
              var rawValS = String(Number(cmpNumVal.toPrecision(10)));
              if (opObj.when === "formula" && typeof opObj.value === "string") {
                var mFm2 = /^(.*?)(>=|<=|<>|>|<|=)\s*-?[0-9]+(?:\.[0-9]+)?(.*)$/.exec(opObj.value);
                if (mFm2) {
                  var lhsF = mFm2[1], opF = mFm2[2], rhsF = mFm2[3];
                  if (pctGrounded === true) {
                    opObj.value = lhsF + opF + decVal + rhsF;
                  } else {
                    var bodyDec = lhsF.replace(/^=/, "") + opF + decVal + rhsF;
                    var bodyRaw = lhsF.replace(/^=/, "") + opF + rawValS + rhsF;
                    opObj.value = "=IF(MAX($" + pctColL + "$" + r1P + ":$" + pctColL + "$" + r2P + ")<=1," + bodyDec + "," + bodyRaw + ")";
                  }
                }
              } else if (opObj.when === "gt" || opObj.when === "ge" || opObj.when === "lt" || opObj.when === "le" || opObj.when === "eq" || opObj.when === "ne") {
                var opSymP = { gt: ">", ge: ">=", lt: "<", le: "<=", eq: "=", ne: "<>" }[opObj.when];
                var cellP = pctColL + r1P;
                opObj.when = "formula";
                if (pctGrounded === true) {
                  opObj.value = "=" + cellP + opSymP + decVal;
                } else {
                  opObj.value = "=IF(MAX($" + pctColL + "$" + r1P + ":$" + pctColL + "$" + r2P + ")<=1," + cellP + opSymP + decVal + "," + cellP + opSymP + rawValS + ")";
                }
              }
            }
          } else if (pctGroundedName) {
            addMiss("%列「" + cmpCol + "」を1を超える値（" + cmpNumStr + "）で比較しているため確認が必要");
          }
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
    // 8. 守りの逆（頼みに無い手を勝手に足さない）＋ find の疑問文誤爆防止
    var tFullN = nfkc(txt);
    if (shN === "find") {
      var hasQWord = /どんな|何が|何を|何の|何か|なにが|なにを|何が入|何があ|どれ|誰|だれ|いくつ|何件|何人|何行|何列|何個|いくら/.test(tFullN);
      var hasPoliteQ = /ですか|でしょうか|ますか/.test(tFullN) && !/(?:もらえ|くれ|いただけ|でき|られ)ますか/.test(tFullN);
      var findTxtN = nfkc(String(opObj.text || ""));
      if (hasQWord || hasPoliteQ || /どんな|何|なに|どれ|どこ|誰|だれ|いくつ/.test(findTxtN)) {
        addMiss("疑問の文のため find で検索しません");
      }
    }
    if (shN === "seiri") {
      if (opObj.renumber && !_OPT_COL_CUES_JS.renumber.test(tFullN)) {
        addMiss("頼みに無い操作（renumber）が混入しています");
      }
      if (opObj.blank_rows === true && !/空行|空白行|空白の行|空いてる行|空いている行|空き行/.test(tFullN)) {
        addMiss("頼みに無い操作（blank_rows）が混入しています");
      }
      if (opObj.dedupe === true && !/重複|ダブ|同じ行/.test(tFullN)) {
        addMiss("頼みに無い操作（dedupe）が混入しています");
      }
    }
    if (shN === "table.new") {
      if (opObj.number && !_OPT_COL_CUES_JS.number.test(tFullN)) {
        addMiss("頼みに無い操作（number）が混入しています");
      }
      if (opObj.total && !_OPT_COL_CUES_JS.total.test(tFullN)) {
        addMiss("頼みに無い操作（total）が混入しています");
      }
    }
    if (shN === "sort") {
      if ((opObj.filter === true || opObj.where) && !/フィルタ|フィルター|絞り|だけ|のみ/.test(tFullN)) {
        addMiss("頼みに無い操作（filter/where）が混入しています");
      }
    }
    if (opObj.all_sheets === true && !/全シート|すべてのシート|全てのシート|ブック全体/.test(tFullN)) {
      addMiss("頼みに無い操作（all_sheets）が混入しています");
    }
    if (shN === "format") {
      if (opObj.bold === true && !/太字|太く|ボールド/i.test(tFullN)) {
        addMiss("頼みに無い操作（bold）が混入しています");
      }
      if (opObj.italic === true && !/斜体|イタリック/i.test(tFullN)) {
        addMiss("頼みに無い操作（italic）が混入しています");
      }
      if (opObj.merge === true && !/結合|マージ/i.test(tFullN)) {
        addMiss("頼みに無い操作（merge）が混入しています");
      }
      if (_hasOwn(opObj, "borders") && opObj.borders !== null && opObj.borders !== false && opObj.borders !== "none" && opObj.borders !== "なし" && !/罫線|枠線|外枠|格子/.test(tFullN)) {
        addMiss("頼みに無い操作（borders）が混入しています");
      }
    }
    if (shN === "cols.delete") {
      var maskedDelN = nfkc(_maskColNamesJs(scanTxt, tbl));
      if (_COL_CONTENT_DEL_RE_JS.test(maskedDelN) || _COL_PROP_OBJ_RE_JS.test(maskedDelN)) {
        addMiss("列そのものではなく列の中身の語が含まれているため列削除しません");
      } else if (/(?:列|カラム)/.test(maskedDelN) && !_COL_DIRECT_DEL_RE_JS.test(maskedDelN)) {
        addMiss("列そのものが削除対象ではないため列削除しません");
      }
    }
    if (shN === "rows.delete") {
      if (/(?:行目|行)の(?!削除|消去|除去)[^\s、。のをにはが]{1,12}を|中身|値だけ|値を|空白|スペース|改行|色|背景|書式|罫線|メモ|コメント|リンク/.test(scanN)) {
        addMiss("行そのものではなく中身の語が含まれているため行削除しません");
      }
    }
  }

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
        } else if (wanted && (shelf.name === "clear.all" || shelf.name === "cf.dup") && table && table.first_col && table.last_col && !(shelf.name === "cf.dup" && colPool.length)) {   // 列の名指しがある重複はその列だけ
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
        if (!arg.req && _OPT_COL_CUES_JS[k] && !_OPT_COL_CUES_JS[k].test(nfkc(text))) {
          // 頼みに該当動作の語が無い任意列引数（at / renumber / number 等）には流さない
        } else if (shelf.name === "calc.col" && k === "at") {
          // calc.col の at は専用解析で決める
        } else if (colPool.length && !(anyList.indexOf(k) >= 0 && hasAnyFilled())) {
          av = colPool.shift();
        }
      } else if (t === "列[]") {
        if (!arg.req && _OPT_COL_CUES_JS[k] && !_OPT_COL_CUES_JS[k].test(nfkc(text))) {
          // 頼みに該当動作の語が無い任意列[]引数（total 等）には流さない
        } else if (colPool.length) {
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
      if (!_hasOwn(op, "range") && !_hasOwn(op, "col") && !_hasOwn(op, "header") && !_hasOwn(op, "title")) {
        var mTopR = /(?:上から|先頭|最初(?:の)?)\s*([0-9]+)\s*行/.exec(nfkc(text));
        if (mTopR) {
          var nTopR = Math.max(1, parseInt(mTopR[1], 10));
          if (table && table.first_col && table.last_col) {
            var spTopR = _dataSpan(table);
            var tr1 = spTopR ? spTopR[0] : ((table.header_row || 1) + 1);
            var tr2 = spTopR ? Math.min(spTopR[1], tr1 + nTopR - 1) : (tr1 + nTopR - 1);
            op.range = table.first_col + tr1 + ":" + table.last_col + tr2;
          } else {
            op.range = "1:" + nTopR;
          }
          named = true;
        }
      }
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
      if (!_hasOwn(op, "align")) {
        var tAl = nfkc(text).trim();
        if (/(?:^|[\s、,])(?:中央|真ん中)(?:に|へ|にして)?$/.test(tAl)) op.align = "center";
        else if (/(?:^|[\s、,])右(?:に|へ|にして)?$/.test(tAl)) op.align = "right";
        else if (/(?:^|[\s、,])左(?:に|へ|にして)?$/.test(tAl)) op.align = "left";
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
        if (!eqS || colsAll.indexOf(eqS) >= 0 || /(?:が|は)/.test(eqS) || /以上|以下|未満|より大|より小|より前|より後|以前|以降|を超|超え|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄/.test(eqS) || _DATE_CMP_CUE_RE_JS.test(nfkc(eqS))) {
          delete opObj.equals;
          return;
        }
      }
      opObj.equals = eqS;
    }

    if (_CMP_VALUE_SHELVES_JS[shelf.name] && op.when !== "formula") {
      _resolveCmpValueJs(op, text);
    }
    if (shelf.name === "cf.add" && op.when !== "formula" && table && table.first_col && table.last_col) {
      var spCf = _dataSpan(table);
      var cfR1 = spCf ? spCf[0] : ((table.header_row || 1) + 1);
      var cfR2 = spCf ? spCf[1] : cfR1;
      var twoColCf = _twoColCmpOfJs(text, table);
      var colContCf = _colContainsOfJs(text, table);
      if (!/のセル|セルを|セルに/.test(text) && _ROW_CF_THING_RE_JS.test(nfkc(text))) {
        var condColCf = _condColOfJs(scan, table);
        var refL = (condColCf && _letterOf(table, condColCf)) || (names.length && _letterOf(table, names[0])) || (letters.length ? letters[0] : "");
        if (!refL) {
          var uCf = _resolveUniqueColsJs(scan, table, false, []);
          if (uCf.length) refL = _letterOf(table, uCf[0]) || "";
        }
        var expr = "";
        var rawVCf = op.value;
        var normVCf = !_isEmptyVal(rawVCf) ? _normFilterNumJs(rawVCf) : null;
        var numVal = normVCf !== null ? normVCf : ((rawVCf !== undefined && rawVCf !== null) ? String(rawVCf).replace(/,/g, "") : "");
        if (twoColCf) {
          var laCf = _letterOf(table, twoColCf[0]), lbCf = _letterOf(table, twoColCf[2]);
          if (laCf && lbCf) expr = "=$" + laCf + cfR1 + twoColCf[1] + "$" + lbCf + cfR1;
        }
        if (!expr && colContCf) {
          var clCc = _letterOf(table, colContCf[0]);
          if (clCc) expr = "=ISNUMBER(SEARCH(\"" + String(colContCf[1]).replace(/"/g, "\"\"") + "\",$" + clCc + cfR1 + "))";
        }
        var compCf = _cfCompoundExprJs(text, table);
        if (compCf) {
          expr = compCf[0];
          if (!compCf[1]) refL = "";   // 2 つ目の条件が読めない＝1 つだけで撃たない
        }
        if (!expr && refL) expr = _cfBlankTodayExprJs(text, refL, cfR1);
        if (!expr && refL) {
          var cfValRef = /絶対値/.test(nfkc(text)) ? ("ABS($" + refL + cfR1 + ")") : ("$" + refL + cfR1);
          var dCfAtom =(!_isEmptyVal(rawVCf) && normVCf === null) ? _dateCmpToFormulaAtomJs(rawVCf, table) : null;
          if (op.when === "between" && typeof rawVCf === "string" && rawVCf.indexOf("..") >= 0) {
            var pCf = rawVCf.split("..");
            var da1 = _dateCmpToFormulaAtomJs(pCf[0], table), da2 = _dateCmpToFormulaAtomJs(pCf[1], table);
            if (da1 && da2) expr = "=AND(ISNUMBER($" + refL + cfR1 + "),$" + refL + cfR1 + ">=" + da1 + ",$" + refL + cfR1 + "<=" + da2 + ")";
          } else if (dCfAtom && (op.when === "gt" || op.when === "ge" || op.when === "lt" || op.when === "le" || op.when === "eq" || op.when === "ne")) {
            var opSymCf = { gt: ">", ge: ">=", lt: "<", le: "<=", eq: "=", ne: "<>" }[op.when];
            expr = "=AND(ISNUMBER($" + refL + cfR1 + "),$" + refL + cfR1 + opSymCf + dCfAtom + ")";
          } else if (op.when === "ge" && numVal !== "") expr = "=" + cfValRef + ">=" + numVal;
          else if (op.when === "le" && numVal !== "") expr = "=" + cfValRef + "<=" + numVal;
          else if (op.when === "gt" && numVal !== "") expr = "=" + cfValRef + ">" + numVal;
          else if (op.when === "lt" && numVal !== "") expr = "=" + cfValRef + "<" + numVal;
          else if (op.when === "ne" && !_isEmptyVal(rawVCf)) {
            if (normVCf !== null) expr = "=" + cfValRef + "<>" + normVCf;
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
            var mEqRow = _COND_EQ_THING_RE_JS.exec(nfkc(text));
            if (mEqRow) {
              var rvEq = mEqRow[2].trim();
              var nvEq = _normFilterNumJs(rvEq);
              if (nvEq !== null) expr = "=$" + refL + cfR1 + "=" + nvEq;
              else expr = "=$" + refL + cfR1 + "=\"" + rvEq.replace(/"/g, "\"\"") + "\"";
            } else if (!_isEmptyVal(rawVCf)) {
              expr = "=ISNUMBER(SEARCH(\"" + String(rawVCf).replace(/"/g, "\"\"") + "\",$" + refL + cfR1 + "))";
            }
          }
        } else if (!expr && /欠席|完了|未完了|終了/.test(text)) {
          var kwCf = /欠席/.test(text) ? "欠席" : (/未完了/.test(text) ? "未完了" : (/完了/.test(text) ? "完了" : "終了"));
          expr = "=COUNTIF($" + table.first_col + cfR1 + ":$" + table.last_col + cfR1 + ",\"*" + kwCf + "*\")>0";
        }
        if (expr) {
          op.range = table.first_col + cfR1 + ":" + table.last_col + cfR2;
          op.when = "formula";
          op.value = expr;
          named = true;
        }
      } else if (twoColCf) {
        var laCf2 = _letterOf(table, twoColCf[0]), lbCf2 = _letterOf(table, twoColCf[2]);
        if (laCf2 && lbCf2) {
          op.range = laCf2 + cfR1 + ":" + laCf2 + cfR2;
          op.when = "formula";
          op.value = "=$" + laCf2 + cfR1 + twoColCf[1] + "$" + lbCf2 + cfR1;
          named = true;
        }
      } else if (colContCf && (!op.when || op.when === "contains") && _isEmptyVal(op.value)) {
        var clCc2 = _letterOf(table, colContCf[0]);
        if (clCc2) op.range = clCc2 + cfR1 + ":" + clCc2 + cfR2;
        op.when = "contains";
        op.value = colContCf[1];
        named = true;
      }
      if (/赤字|赤い文字|文字を赤/.test(text) && op.bg === "赤" && !/背景|塗/.test(text)) {
        op.color = op.bg;   // 「〜の行を赤字に」は文字の色
        delete op.bg;
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
      var descPatJs = "(?:大きい|多い|高い|新しい|遅い)(?:順|ものから|方から|ほうから|のから)|降順|逆順";
      var ascPatJs = "(?:小さい|少ない|低い|安い|古い|若い|早い)(?:順|ものから|方から|ほうから|のから)|昇順|五十音順|あいうえお順";
      var mGrp = nfkcTxt.match(/([^\s、,の]{1,16})ごと(?:[、,]|に?(?:かためて)?並べ|に(?=\s*[^\s、,の]{1,16}(?:の|が)))/);
      if (mGrp) {
        var rawGrp = mGrp[1].trim();
        var mappedGrp = _resolveColRefJs(rawGrp, table);
        if (mappedGrp) sortPairs.push(mappedGrp);
        else extraMissing.push("表に無い列名（" + rawGrp + "）");
      }
      var sortReG = new RegExp("(?:[^\\s、,の]{1,16}ごとに\\s*|その中で\\s*|同じ[^\\s、,。]{1,12}の中は\\s*|同[^\\s、,。]{1,12}内は\\s*)?([^\\s、,のがは]{1,16})(?:の|が)(?:(" + descPatJs + ")|(" + ascPatJs + "))", "g");
      var sm;
      while ((sm = sortReG.exec(nfkcTxt)) !== null) {
        var rawColS = sm[1].trim();
        var mappedColS = _resolveColRefJs(rawColS, table);
        if (!mappedColS && rawColS.indexOf("の") >= 0) {
          mappedColS = _resolveColRefJs(rawColS.split("の")[0].trim(), table);
        }
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
      } else {
        if (typeof op.col === "string" && !_resolveColRefJs(op.col, table) && table) {
          var escOpCol = nfkc(op.col).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          var mAlS = new RegExp("([^\\s、,のがは]{1,16})の" + escOpCol).exec(nfkcTxt);
          if (mAlS) {
            var resAl = _resolveColRefJs(mAlS[1].trim(), table);
            if (resAl) { op.col = resAl; extraMissing = []; }
          } else if (names.length === 1) {
            op.col = names[0];
            extraMissing = [];
          }
        }
        if (!_hasOwn(op, "desc")) {
          if (new RegExp(descPatJs).test(nfkcTxt)) op.desc = true;
          else if (new RegExp(ascPatJs).test(nfkcTxt)) op.desc = false;
        }
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
        var s = String(raw || "").trim().replace(/^[\s、,。をにで]+|[\s、,。をにでの]+$/g, "");
        if (!s) return null;
        var mPow = /^(.+?)の([0-9]+(?:\.[0-9]+)?)乗$/.exec(s);
        if (mPow) {
          var baseP = _cleanOp(mPow[1]);
          return baseP ? ("POWER(" + baseP + "," + mPow[2] + ")") : null;
        }
        var mSqrt = /^(.+?)の平方根$|^(?:平方根|ルート)\s*(.+)$/.exec(s);
        if (mSqrt) {
          var baseS = _cleanOp(mSqrt[1] || mSqrt[2]);
          return baseS ? ("SQRT(" + baseS + ")") : null;
        }
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
        var mSpan = /([^\s、,。をにから−-]{1,20})から([^\s、,。をにまで]{1,20})まで/.exec(cands[ci1]);
        if (mSpan) {
          var aSp = _cleanOp(mSpan[1]), bSp = _cleanOp(mSpan[2]);
          if (aSp && bSp) return bSp + "-" + aSp;
        }
        var mPctAdd = /([^\s、,。をにが]{1,20}?)\s*(?:に|へ)\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:を)?(?:足[しす]|た[しす]|加算|上乗せ|増し)/.exec(cands[ci1]);
        if (mPctAdd) {
          var aPa = _cleanOp(mPctAdd[1]);
          if (aPa) return aPa + "*" + Number((1.0 + parseFloat(mPctAdd[2]) / 100.0).toPrecision(10));
        }
        var mPctSub = /([^\s、,。をにが]{1,20}?)\s*(?:から)\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:を)?(?:引[いけく]|ひ[いけく]|減算|割引)/.exec(cands[ci1]);
        if (mPctSub) {
          var aPs = _cleanOp(mPctSub[1]);
          if (aPs) return aPs + "*" + Number((1.0 - parseFloat(mPctSub[2]) / 100.0).toPrecision(10));
        }
        var mMulN = /([^\s、,。をにが]{1,20}?)(?:を|の)\s*([0-9]+(?:\.[0-9]+)?)\s*倍/.exec(cands[ci1]);
        if (mMulN) {
          var aMn = _cleanOp(mMulN[1]);
          if (aMn) return aMn + "*" + mMulN[2];
        }
        var mWari = /([^\s、,。をにが]{1,20}?)(?:を|の)\s*([0-9]+(?:\.[0-9]+)?)\s*割(増し?|引き?)/.exec(cands[ci1]);
        if (mWari) {
          var aWr = _cleanOp(mWari[1]);
          if (aWr) {
            var dWr = parseFloat(mWari[2]) / 10.0;
            var facWr = mWari[3].charAt(0) === "増" ? (1.0 + dWr) : (1.0 - dWr);
            return aWr + "*" + Number(facWr.toPrecision(10));
          }
        }
        var mHalf = /([^\s、,。をにが]{1,20}?)(?:を|の)\s*半分/.exec(cands[ci1]);
        if (mHalf) {
          var aHf = _cleanOp(mHalf[1]);
          if (aHf) return aHf + "/2";
        }
      }
      for (var ci2 = 0; ci2 < cands.length; ci2++) {
        var mSolo = /([^\s、,。をにで]{1,20}の(?:[0-9]+(?:\.[0-9]+)?乗|平方根))/.exec(cands[ci2]);
        if (mSolo) {
          var resS = _cleanOp(mSolo[1]);
          if (resS) return resS;
        }
      }
      return null;
    }

    if (shelf.name === "freeze") {
      if (!_hasOwn(op, "rows") && table && table.header_row && /見出し|ヘッダ/.test(text)) {
        op.rows = parseInt(table.header_row, 10) + Math.max(1, parseInt(table.header_rows || 1, 10)) - 1;
      }
      var tFz = nfkc(text);
      var fzCols = 0;
      var maxTblCols = 26;
      if (table && Array.isArray(table.columns)) {
        var foundMaxC = 0;
        for (var fci = 0; fci < table.columns.length; fci++) {
          var clStr = String((table.columns[fci] && table.columns[fci].col) || "");
          if (/^[A-Z]{1,3}$/.test(clStr)) foundMaxC = Math.max(foundMaxC, _colLetToNumJs(clStr));
        }
        if (foundMaxC > 0) maxTblCols = foundMaxC;
      }
      var reFc = /(?<![A-Za-z0-9])([A-Z]{1,2}(?:\s*列?\s*(?:[・、,〜~～\-]|と|から)\s*[A-Z]{1,2})*)\s*列/g;
      var mFc;
      while ((mFc = reFc.exec(tFz)) !== null) {
        var toks = mFc[1].match(/[A-Z]{1,2}/g) || [];
        for (var ti = 0; ti < toks.length; ti++) {
          var tok = toks[ti];
          if (tok.length === 1) {
            fzCols = Math.max(fzCols, _colLetToNumJs(tok));
          } else {
            var resFc = _resolveColRefJs(tok, table);
            if (resFc) {
              var resL = _letterOf(table, resFc);
              if (resL) fzCols = Math.max(fzCols, _colLetToNumJs(resL));
            } else {
              var nFc = _colLetToNumJs(tok);
              if (nFc <= maxTblCols) fzCols = Math.max(fzCols, nFc);
            }
          }
        }
      }
      var reFn = /(?:左(?:から)?|先頭(?:から)?|最初(?:の)?)\s*([0-9]+)\s*列|([0-9]+)\s*列(?:目?(?:まで)?(?:固定|フリーズ|動かない)|を固定)/g;
      var mFn;
      while ((mFn = reFn.exec(tFz)) !== null) {
        var nvF = parseInt(mFn[1] || mFn[2], 10);
        if (nvF > 0) fzCols = Math.max(fzCols, nvF);
      }
      // 列名で名指し（「氏名の列まで固定」）→ その列の位置まで（Python と同じ）
      var fzNames = ((table && Array.isArray(table.columns)) ? table.columns : []).map(function (c) { return String((c && c.name) || ""); });
      fzNames.sort(function (a, b) { return b.length - a.length; });
      fzNames.forEach(function (cn) {
        if (!cn) return;
        var esc = nfkc(cn).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        if (new RegExp(esc + "(?:の)?(?:列|欄)").test(tFz)) {
          var lFz = _letterOf(table, cn);
          if (lFz) fzCols = Math.max(fzCols, _colLetToNumJs(lFz));
        }
      });
      if (fzCols > 0) op.cols = fzCols;
    }
    if (shelf.name === "calc.diff") {
      var dcJs = _calcDiffColsOfJs(text, table);
      if (dcJs) {
        op.col_a = dcJs[0];
        op.col_b = dcJs[1];
        named = true;
      } else {
        var dKeys = ["col_a", "col_b"];
        for (var dki = 0; dki < dKeys.length; dki++) {
          var dk = dKeys[dki];
          if (typeof op[dk] === "string") {
            var resD = _resolveColRefJs(op[dk], table);
            if (resD) op[dk] = resD;
          }
        }
      }
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
      var dShift = _dateShiftOfJs(text, table) || _multiColAggOfJs(text, table);
      if (dShift && !_hasOwn(op, "expr")) {
        op.expr = dShift[0];
        op.name = dShift[1];
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
      if (shelf.name === "summary" && !_hasOwn(op, "func") && /の(?:数|件数|回数|人数)|数え|カウント/.test(nfkc(text))) {
        op.func = "count";
      }
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
      var cSpanRe = /([^\s、,。をにからの]{1,16})から([^\s、,。をにまでの]{1,16})(?:まで|の)/g;
      var mCspan;
      while ((mCspan = cSpanRe.exec(nfkc(text))) !== null) {
        var caCh = _resolveColRefJs(mCspan[1].trim(), table);
        var cbCh = _resolveColRefJs(mCspan[2].trim(), table);
        if (caCh && cbCh && Array.isArray(table.columns)) {
          var tblCnames = [];
          for (var tci3 = 0; tci3 < table.columns.length; tci3++) {
            if (table.columns[tci3] && table.columns[tci3].name) tblCnames.push(String(table.columns[tci3].name));
          }
          var iaCh = tblCnames.indexOf(caCh), ibCh = tblCnames.indexOf(cbCh);
          if (iaCh >= 0 && ibCh > iaCh) {
            for (var miCh = iaCh; miCh <= ibCh; miCh++) {
              if (chartCols.indexOf(tblCnames[miCh]) < 0) chartCols.push(tblCnames[miCh]);
            }
          }
        }
      }
      var uChart = _resolveUniqueColsJs(scan, table, false, chartCols);
      for (var uci = 0; uci < uChart.length; uci++) {
        if (chartCols.indexOf(uChart[uci]) < 0) chartCols.push(uChart[uci]);
      }
      var hGroupsCh = _headerGroupsJs(table);
      var hGroupKeysCh = Object.keys(hGroupsCh);
      var isTwoTierCh = parseInt(table.header_rows || 1, 10) >= 2 || hGroupKeysCh.length > 0;
      if (!chartCols.length && isTwoTierCh && /推移|月別|期別|折れ線/.test(text) && Array.isArray(table.columns)) {
        for (var fli = 0; fli < table.columns.length; fli++) {
          var flc = table.columns[fli];
          if (flc && flc.name && !flc.number) { chartCols.push(flc.name); break; }
        }
      }
      if (chartCols.length) {
        var hasNumMetaCh = _hasNumberMetaJs(table);
        var labelCols = [], numColsCh = [];
        for (var cci = 0; cci < chartCols.length; cci++) {
          if (hasNumMetaCh && _isNumberColJs(table, chartCols[cci])) numColsCh.push(chartCols[cci]);
          else labelCols.push(chartCols[cci]);
        }
        var usedGroupSeries = false;
        if (hasNumMetaCh && !numColsCh.length) {
          var resChNums = _resolveUniqueColsJs(scan, table, true, chartCols);
          if (resChNums.length) numColsCh = numColsCh.concat(resChNums);
          else if (isTwoTierCh && hGroupKeysCh.length) {
            var grpSubCols = [];
            for (var gki = 0; gki < hGroupKeysCh.length; gki++) {
              var gList = hGroupsCh[hGroupKeysCh[gki]];
              for (var gli = 0; gli < gList.length; gli++) {
                var gcn = gList[gli];
                if (chartCols.indexOf(gcn) < 0 && !/(?:年計|合計|総計|小計)$/.test(gcn)) grpSubCols.push(gcn);
              }
            }
            if (grpSubCols.length >= 2) {
              numColsCh = numColsCh.concat(grpSubCols);
              usedGroupSeries = true;
            }
          } else {
            var fbCh = _singleNumericFallbackJs(table, chartCols);
            if (fbCh) numColsCh.push(fbCh);
          }
        }
        if (hasNumMetaCh && !numColsCh.length) {
          delete op.range;
          if (!(/(?:ごと(?:に|の)|別(?:に|で|の))/.test(nfkc(text)) && /件数|人数|回数|の数|回答数|カウント/.test(nfkc(text)))) {
            extraMissing.push("グラフにする数値の列");
          }
        } else {
          if (numColsCh.length >= 2) {
            numColsCh.sort(function (a, b) {
              var la = _letterOf(table, a) || (/^[A-Z]{1,3}$/.test(String(a)) ? String(a) : "ZZZ");
              var lb = _letterOf(table, b) || (/^[A-Z]{1,3}$/.test(String(b)) ? String(b) : "ZZZ");
              return _colNum(la) - _colNum(lb);
            });
          }
          var orderedCols = hasNumMetaCh ? labelCols.concat(numColsCh) : chartCols;
          var orderedLs = [];
          for (var oci = 0; oci < orderedCols.length; oci++) {
            var ol = _letterOf(table, orderedCols[oci]) || (/^[A-Z]{1,3}$/.test(String(orderedCols[oci])) ? String(orderedCols[oci]) : null);
            if (ol && orderedLs.indexOf(ol) < 0) orderedLs.push(ol);
          }
          var spCh = _dataSpan(table);
          if (orderedLs.length && spCh) {
            var chR1 = parseInt(table.header_row || spCh[0], 10) + Math.max(1, parseInt(table.header_rows || 1, 10)) - 1;
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
                var runsCh = [];
                var stL = orderedLs[0], prevL = orderedLs[0];
                for (var riCh = 1; riCh < orderedLs.length; riCh++) {
                  if (_colNum(orderedLs[riCh]) === _colNum(prevL) + 1) {
                    prevL = orderedLs[riCh];
                  } else {
                    runsCh.push(stL + chR1 + ":" + prevL + chR2);
                    stL = prevL = orderedLs[riCh];
                  }
                }
                runsCh.push(stL + chR1 + ":" + prevL + chR2);
                op.range = runsCh.join(",");
              }
            }
            if (usedGroupSeries && labelCols.length === 1 && numColsCh.length >= 2 && /推移|月別|折れ線|ごと|別/.test(text)) {
              op.transpose = true;
            }
          }
        }
      }
    }
    if (shelf.name === "width") {
      if (rows.length && !_hasOwn(op, "rows") && !_hasOwn(op, "width")) {
        var mRh = /(?:行の高さを?|行高を?)\s*([0-9]+)/.exec(nfkc(text));
        if (mRh) {
          var isContigR = rows.length >= 2;
          for (var rki = 1; rki < rows.length; rki++) {
            if (rows[rki] !== rows[rki - 1] + 1) { isContigR = false; break; }
          }
          var rKey = isContigR ? (rows[0] + ":" + rows[rows.length - 1]) : rows.join(",");
          op.rows = {};
          op.rows[rKey] = parseInt(mRh[1], 10);
          named = true;
        }
      }
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

    if (shelf.name === "date.parts" && !_hasOwn(op, "part")) {
      var tDp = nfkc(text);
      if (tDp.indexOf("四半期") >= 0) op.part = "quarter";
      else if (/(?:から日の?(?:列|欄)|日の?列)/.test(tDp)) op.part = "day";
    }
    if (shelf.name === "calc.if") {
      var vkList = ["then_val", "else_val"];
      for (var vki = 0; vki < vkList.length; vki++) {
        var vk = vkList[vki];
        if (typeof op[vk] === "string") {
          op[vk] = op[vk].replace(/(?:と入る|と表示(?:する|させる)?|にする|を入れる|の?列|の?欄).*$/, "").trim();
        }
      }
    }
    if (shelf.name === "date.age" && !_hasOwn(op, "name")) {
      var mAge = /(勤続年数|勤続月数|在籍年数|経過年数|経過月数|経過日数|築年数|年齢)/.exec(text);
      if (mAge && mAge[1] !== "年齢") {
        op.name = mAge[1];
        if (/月数$/.test(mAge[1]) && !_hasOwn(op, "unit")) op.unit = "months";
        else if (/日数$/.test(mAge[1]) && !_hasOwn(op, "unit")) op.unit = "days";
      }
    }

    if (shelf.name === "seiri") {
      if (!_OPT_COL_CUES_JS.renumber.test(nfkc(text))) delete op.renumber;
      else if (op.col && !_hasOwn(op, "renumber") && !op.trim && !op.halfwidth) {
        op.renumber = op.col;
        delete op.col;
      }
    }

    if (shelf.name === "filter.where" || shelf.name === "filter.delete" || shelf.name === "filter.extract") {
      if (shelf.name === "filter.extract" && op.into === "別") delete op.into;
      var colContF = _colContainsOfJs(text, table);
      if (colContF && (!op.when || op.when === "contains")) {
        op.col = colContF[0];
        op.when = "contains";
        op.value = colContF[1];
        delete op.equals;
      }
      if (op.when === "contains") delete op.equals;
      if (_hasOwn(op, "when") && _hasOwn(op, "equals") && typeof op.equals === "string") {
        if (/以上|以下|未満|より|超|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄|以前|以降/.test(op.equals) || _DATE_CMP_CUE_RE_JS.test(nfkc(op.equals))) {
          delete op.equals;
        }
      }
      if (shelf.name === "filter.where") {
        var hasCmpCue = _hasOwn(op, "when") || !!colContF || /以上|以下|未満|より|を超?|上回|下回|届か|届いてい?ない|を含|含む|以外|ではな|でない|空白|空欄|以前|以降/.test(text) || _DATE_CMP_CUE_RE_JS.test(nfkc(text));
        if (!hasCmpCue && !_hasOwn(op, "equals")) {
          var mGen = /(?:が|は)\s*[『「]?([^』」\sの、。]+?)[』」]?の(?:もの|やつ|行|分|件|データ|項目|[^\s、。のをにはが]{1,12})(?:だけ|のみ)/.exec(text.trim());
          if (mGen) {
            op.equals = mGen[1].trim();
          } else {
            var mName = /^(.+?)(?:さん|様)?の行だけ/.exec(text.trim());
            if (mName) op.equals = mName[1].trim();
          }
        }
      }
      if (_hasOwn(op, "equals")) {
        _cleanFilterEqualsJs(op, text, table, origQuotesMap);
      }
      if (op.when === "ne") delete op.equals;
      _resolveCmpValueJs(op, text);
      if (!_hasOwn(op, "when")) {
        var yc = _yearCmpOfJs(text);
        if (yc) {
          op.when = yc[0];
          op.value = yc[1];
          delete op.equals;
        }
      }
      if (!_hasOwn(op, "col") && table && table.columns) {
        var cols = [];
        var dateCandsF = [];
        for (var tci = 0; tci < table.columns.length; tci++) {
          cols.push(table.columns[tci].name);
          if (table.columns[tci].name && !table.columns[tci].number && /(?:日付|日$|date)/i.test(String(table.columns[tci].name))) {
            dateCandsF.push(table.columns[tci].name);
          }
        }
        var valSF = String(op.value || "");
        var isDateValF = !!(valSF && (valSF.indexOf("..") >= 0 || _parseCmpDateStrJs(valSF)));
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
        if (isDateValF && dateCandsF.length === 1) {
          op.col = dateCandsF[0];
        } else if (hasKamoku && isExpense) {
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
    if (shelf.name === "cols.delete" && (!op.cols || !op.cols.length) && table) {
      var uDel = _resolveUniqueColsJs(scan, table);
      if (uDel.length) {
        op.cols = uDel;
        named = true;
      }
    }
    if (shelf.name === "date.fix") {
      if (!_hasOwn(op, "format")) {
        if (/yyyy-mm-dd/i.test(text)) op.format = "yyyy-mm-dd";
        else if (/yyyy\/mm\/dd|年\/月\/日|年月日の?形|年月日形式/i.test(text)) op.format = "yyyy/mm/dd";
      }
      if (!_hasOwn(op, "col") && !_hasOwn(op, "range") && table && Array.isArray(table.columns)) {
        var dCands = [];
        for (var dci2 = 0; dci2 < table.columns.length; dci2++) {
          var dc2 = table.columns[dci2];
          if (dc2 && dc2.name && !dc2.number && /(?:日付|日$|date)/i.test(String(dc2.name))) dCands.push(dc2.name);
        }
        if (dCands.length === 1) { op.col = dCands[0]; named = true; }
      }
    }
    if (shelf.name === "phone.fix") {
      if (!_hasOwn(op, "col") && !_hasOwn(op, "range") && table && Array.isArray(table.columns)) {
        var pCands = [];
        for (var pci2 = 0; pci2 < table.columns.length; pci2++) {
          var pc2 = table.columns[pci2];
          if (pc2 && pc2.name && /(?:電話|携帯|tel|phone)/i.test(String(pc2.name))) pCands.push(pc2.name);
        }
        if (pCands.length === 1) { op.col = pCands[0]; named = true; }
      }
    }

    if (shelf.name === "cols.insert" && !_hasOwn(op, "at") && table) {
      var tInsN = nfkc(text);
      if (/右端|最後|末尾|一番右/.test(tInsN) && table.last_col) {
        op.at = _colLetter(_colNum(table.last_col) + 1);
        named = true;
      } else if (/左端|先頭|一番左/.test(tInsN) && table.first_col) {
        op.at = table.first_col;
        named = true;
      } else if (names.length) {
        var refLIns = _letterOf(table, names[0]);
        if (refLIns) {
          op.at = /の?(?:右|後ろ|次|あと)/.test(tInsN) ? _colLetter(_colNum(refLIns) + 1) : refLIns;
          named = true;
        }
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
      if (/(?:が|は|の).{0,16}(?:行|データ|明細|レコード|案件|商品)|以上|以下|未満|超え?|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行/.test(clause)) {
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

  var _READ_ONLY_MUTATE_RE_JS = /並べて|並べ替|ソート|絞り込|フィルタ|抽出|消して|消す|削除|取り除|捨て|外して|外す|解除|塗|色[をに]?付|色[をに]?つ|色[をに]?変|色にして|太字|斜体|罫線|固定|フリーズ|非表示|隠して|再表示|追加|足して|作って|作成|入れて|入力|書[きくい]|書き換|置換|直して|そろえて|揃えて|整えて|変換|グラフ|ピボット|集計表|別シート|コピー|複製|移動|変更|保護|結合|幅を|高さを|広げて|狭めて|大きくして|小さくして|プルダウン|リストを作|ハイライト|目立たせ|だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|にして(?:くれ|もらえ|くださ|いただ)?[?？]?$|(?<!教え)(?<!見せ)(?:てくれ|てもらえ|ていただ)|てほしい|て欲しい|お願い/;
  var _READ_ONLY_QUERY_RE_JS = /[?？]|どこ|どれ|だれ|誰|どんな|何が|何を|何が入|いくつ|何件|何人|何行|何列|何個|何社|何名|いくら|何円|何%|ありますか|あるか|いるか|ですか|ますか|でしょうか|どうなって|教えて|知りたい|確認したい|構成を|概要を|中身を|一覧を|おかしな|おかしい|異常|エラー|不備|ミス|間違|崩れ/;

  function _chartSummaryOpsJs(op, clause, table) {
    if (!table || !Array.isArray(table.columns) || !table.columns.length || op.edit || op.transpose) return null;
    if (_allExplicitRanges(clause).length) return null;
    var cN = nfkc(clause);
    if (!/(?:ごと(?:に|の)|別(?:に|で|の))/.test(cN)) return null;
    if (!/集計|合計|平均|件数|人数|回数|の数(?![量値字列])|回答数|カウント/.test(cN)) {
      var wsRe = /([^\s、,。をにからの]{1,16})から([^\s、,。をにまでの]{1,16})(?:まで|の)/g;
      var mWs;
      while ((mWs = wsRe.exec(cN)) !== null) {
        if (_resolveColRefJs(mWs[1].trim(), table) && _resolveColRefJs(mWs[2].trim(), table)) return null;
      }
    }
    var byCol = null;
    var mBy = /([^\s・、をにのはが]{1,16}?)(?:ごと(?:に|の)|別(?:に|で|の))/.exec(cN);
    if (mBy) byCol = _resolveColRefJs(mBy[1].trim(), table);
    if (!byCol) return null;
    var hasNum = false;
    for (var i = 0; i < table.columns.length; i++) {
      if (table.columns[i] && table.columns[i].number) { hasNum = true; break; }
    }
    var isNum = function (colRef) {
      var r = _resolveColRefJs(colRef, table);
      if (!r) return false;
      for (var k = 0; k < table.columns.length; k++) {
        if (table.columns[k] && (table.columns[k].name === r || table.columns[k].col === r)) return !!table.columns[k].number;
      }
      return false;
    };
    var func = /件数|人数|回数|の数(?![量値字列])|回答数|カウント/.test(cN) ? "count" : (cN.indexOf("平均") >= 0 ? "avg" : null);
    var valCols = [];
    if (func === "count") {
      valCols = [byCol];
    } else {
      var cNames = _colNames(clause, table);
      for (var ni = 0; ni < cNames.length; ni++) {
        if (cNames[ni] !== byCol && (!hasNum || isNum(cNames[ni])) && valCols.indexOf(cNames[ni]) < 0) valCols.push(cNames[ni]);
      }
      if (!valCols.length) {
        // 省略列名の一意解決
        var cands = [];
        for (var ci = 0; ci < table.columns.length; ci++) {
          var cn = String((table.columns[ci] && table.columns[ci].name) || "").trim();
          if (!cn || cn === byCol) continue;
          if (hasNum && !table.columns[ci].number) continue;
          cands.push(cn);
        }
        var work = cN.split(nfkc(byCol)).join(" ");
        var tokRe = /[一-龥ァ-ヶA-Za-z0-9]{2,}/g;
        var tm;
        while ((tm = tokRe.exec(work)) !== null) {
          var tok = tm[0].replace(/(?:別表|別|毎|列|欄)$/, "");
          if (tok.length < 2 || _COL_TOKEN_STOP_TOP[tok] || tok === byCol) continue;
          var hits = cands.filter(function (nm) { return nm.indexOf(tok) >= 0; });
          if (hits.length === 1 && valCols.indexOf(hits[0]) < 0) valCols.push(hits[0]);
        }
      }
      if (!valCols.length && hasNum) {
        var nums = [];
        for (var fi = 0; fi < table.columns.length; fi++) {
          var fc = table.columns[fi];
          if (fc && fc.number && fc.name !== byCol && !/^(?:no\.?|番号|id)$/i.test(String(fc.name || "").trim())) nums.push(fc.name);
        }
        if (nums.length === 1) valCols.push(nums[0]);
      }
    }
    if (!valCols.length) return null;
    var intoName = "集計_" + byCol + "別";
    var sumOp = { shelf: "summary", by: byCol, values: valCols, into: intoName, ok: true };
    if (func) sumOp.func = func;
    if (op.sheet) sumOp.sheet = op.sheet;
    var chOp = { shelf: "chart.new", type: op.type || "column", range: intoName };
    if (op.title !== undefined) chOp.title = op.title;
    if (op.at !== undefined) chOp.at = op.at;
    if (op.sheet !== undefined) chOp.sheet = op.sheet;
    return [sumOp, chOp];
  }

  var _AMBIG_TIDY_CUE_RE_JS = /見やすく|きれいに|綺麗に|整えて|整え|体裁|見栄え/;
  var _SPECIFIC_TIDY_RE_JS = /見た目だけ|書式だけ|デザインだけ|中身は|値は|掃除なし|罫線|列幅|幅を|色|背景|太字|斜体|フォント|空行|空白|スペース|全角|半角|重複|ダブ|和暦|日付|電話|ハイフン|固定|フィルタ|並べ|ソート|グラフ|集計|合計|平均|削除|消して/;

  function _ambiguousTidyChoicesJs(askText, ops, kind) {
    if (kind === "doc") return null;
    var t = nfkc(askText || "").trim();
    if (!t || VAGUE_RE.test(t) || _allExplicitRanges(t).length) return null;
    if (!_AMBIG_TIDY_CUE_RE_JS.test(t) || _SPECIFIC_TIDY_RE_JS.test(t)) return null;
    var isBareTidy = (
      ops.length === 1 && ops[0] &&
      (ops[0].shelf === "tidy" || ops[0].shelf === "seiri") &&
      !ops[0].range && !ops[0].col && !ops[0].blank_rows && !ops[0].dedupe && !ops[0].halfwidth &&
      !ops[0].trim && !ops[0].numbers && !ops[0].dates && !ops[0].renumber
    );
    if (!isBareTidy && ops.length) return null;
    var sh = (ops.length === 1 && ops[0] && ops[0].sheet) ? ops[0].sheet : null;
    var withSh = function (arr) {
      if (!sh) return arr;
      return arr.map(function (o) { return Object.assign({}, o, { sheet: sh }); });
    };
    return [
      { label: "見た目だけ整える", desc: "見出し・罫線・桁区切り・列幅だけ（値は触らない）", ops: withSh([{ shelf: "tidy" }]) },
      { label: "見た目＋データの掃除", desc: "空行削除・前後空白・全角半角の統一＋見た目", ops: withSh([{ shelf: "seiri" }, { shelf: "tidy" }]) },
      { label: "重複削除＋掃除＋見た目", desc: "重複行の削除も含めて表を丸ごと整える", ops: withSh([{ shelf: "dedupe", ok: true }, { shelf: "seiri" }, { shelf: "tidy" }]) }
    ];
  }

  function _isReadOnlyAskJs(askText) {
    var t = nfkc(askText || "").trim();
    if (!t) return false;
    if (_READ_ONLY_MUTATE_RE_JS.test(t)) return false;
    return _READ_ONLY_QUERY_RE_JS.test(t);
  }

  function _buildPreviewText(res) {
    if (res.fire) {
      return "棚ヒット: " + formatOpsShort(res.ops);
    }
    if (res.choices && res.choices.length) {
      return "選択待ち: どこまで整えるか候補から選びます（" + res.choices.length + "件）";
    }
    if (res.readOnly) {
      return "読むだけ: シートの中身を読んで答えます（変更なし）";
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
      readOnly: false,
      choices: [],
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
    p.guide = _matchGuide(norm(_maskColNamesJs(askText, table), _synonyms));   // 列名（「メール」「画像」等）で案内を出さない

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
      if (kind !== "doc" && table && /(?:小計|合計)(?:の?列|列)?(?:を(?:列として)?)?(?:足|追加|作|入れ)/.test(c) && !/一番下|最後の行|末尾の行|表の下|合計行|別シート/.test(c)) {
        var hgMapJs = _headerGroupsJs(table);
        var hgKeys = Object.keys(hgMapJs);
        if (hgKeys.length) {
          var cNfkcG = nfkc(c);
          var hitGrpsJs = hgKeys.filter(function (g) { return cNfkcG.indexOf(nfkc(g)) >= 0; });
          hitGrpsJs.sort(function (a, b) { return cNfkcG.indexOf(nfkc(a)) - cNfkcG.indexOf(nfkc(b)); });
          if (hitGrpsJs.length) {
            var sufG = c.indexOf("小計") >= 0 ? "小計" : "合計";
            for (var hgi = 0; hgi < hitGrpsJs.length; hgi++) {
              p.ops.push({ shelf: "calc.col", name: hitGrpsJs[hgi] + sufG, expr: hgMapJs[hitGrpsJs[hgi]].join("+") });
            }
            lastIncomplete = null;
            continue;
          }
        }
      }
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
          !/条件|以上|以下|未満|上回|下回|届か|届いてい?ない|以外|じゃない|になって|消|削除|クリア|なし|無し|1行おき|交互|しましま|縞模様|重複|ダブ|固定色|該当行|行全体|の行/.test(c);
        var cNfkcCf = nfkc(c);
        var mEqCf = _COND_EQ_THING_RE_JS.exec(cNfkcCf);
        var hasEqColCf = !!(mEqCf && (!table || !Array.isArray(table.columns) || !table.columns.length || _resolveColRefJs(mEqCf[1], table)));
        var hasRowCfCond = /(?:以上|以下|未満|より大き|より小さ|を超|超え|上回|下回|届か|届いてい?ない|マイナス|負の値|になっていない|になってない|になっている|になってる|ではない|でない|じゃない|以外|空欄|空白|欠席|完了)/.test(c) ||
          _DATE_CMP_CUE_RE_JS.test(cNfkcCf) ||
          hasEqColCf ||
          !!_twoColCmpOfJs(cNfkcCf, table) ||
          !!_colContainsOfJs(cNfkcCf, table) ||
          /[^\s、。]+?(?:が|は)[^\s、。の]+?の行/.test(c);
        var hasRowCfCue = (_ROW_CF_THING_RE_JS.test(cNfkcCf) || (_DATE_CMP_CUE_RE_JS.test(cNfkcCf) && /(?:のセル|セルを|セルに)/.test(c))) &&
          hasRowCfCond &&
          !/消|削除|取り除|取っ|取る|除去|トリム|詰め|重複|ダブ|固定色|三角|千円|百万|だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|絞り込|フィルタ/.test(c) &&
          !(c.indexOf("赤字") >= 0 && !/の行|行を|行全体/.test(c)) &&
          (_colorHits(c).length > 0 || /太字|太く|色[を]?付|色[を]?つ|目立|ハイライト|赤字/.test(c));
        var hasRowDelCond = /(?:の行|行を|行に|行は|行だけ|た行|る行|いない行|ない行|データ|明細|レコード|案件|商品)/.test(c) &&
          (/(?:以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|を含|含む|欠席|出席|完了|未完了|済み|空欄|空白|ゼロ|0の行)/.test(c) ||
            _DATE_CMP_CUE_RE_JS.test(nfkc(c)) ||
            !!_colContainsOfJs(nfkc(c), table) ||
            /[^\s、。]+?(?:が|は)[^\s、。の]+?の(?:行|データ|明細|レコード|案件|商品)/.test(c)) &&
          /消|削除/.test(c) &&
          !/重複|ダブ|空行|空いてる行|空いている行|空白行|空白の行|空き行|色|書式|罫線|フィルタ|フィルター|メモ|コメント|リンク|プルダウン|入力規則/.test(_maskColNamesJs(c, table)) &&
          _rowsOf(c).length === 0;
        var mColDel = /([^\s、。のをにはが]{2,16}?)の?(?:列|カラム)/.exec(c);
        var cNfkcCd = nfkc(c);
        var hasColsDelCue = _COL_DIRECT_DEL_RE_JS.test(cNfkcCd) &&
          /消(?!費)|削除|取り除|捨て/.test(cNfkcCd) &&
          !_COL_CONTENT_DEL_RE_JS.test(cNfkcCd) &&
          !_COL_PROP_OBJ_RE_JS.test(cNfkcCd) &&
          (_colNames(c, table).length > 0 || _colLetters(c).length > 0 || !!(mColDel && _resolveColRefJs(mColDel[1], table)));
        var hasSummaryCue = /(?:別(?:に|で|の)|ごと(?:に|の))/.test(c) &&
          /集計|合計|平均|件数/.test(c) &&
          !/ピボット|クロス|縦と横|小計|グラフ|並|ソート|抽出/.test(c);
        var hasCalcDiffCue = !!_calcDiffColsOfJs(nfkc(c), table) && !/シート|タブ|比較/.test(c);
        var hasCalcCue = /(?:と|に|×|\*)[^\s、。をにが]{1,16}?(?:を)?(?:掛け|かけ|乗算)|(?:と|に|＋|\+)[^\s、。をにが]{1,16}?(?:を)?(?:足[しす]|た[しす]|加算)|(?:から|−|-)[^\s、。をにが]{1,16}?(?:を)?(?:引[いけく]|ひ[いけく]|差し引|減算)|(?:を|÷|\/)[^\s、。をにが]{1,16}?(?:で)?(?:割[っりる]|わ[っりる]|除算)|[^\s、。0-9:\/\-][^\s、。]{0,14}[×*＊÷＋][^\s、。]{1,14}(?:で|を|の)|[0-9]+(?:\.[0-9]+)?\s*倍|[0-9]+(?:\.[0-9]+)?\s*割(?:増|引)|(?:を|の)\s*半分/.test(nfkc(c)) &&
          !/構成比|割合|消費税|累計|順位|平均|合計行|別シート|ごと|別に|小計|前月比|前年比|経過|罫線|空の?(?:列|行)|の間に|の下に|の上に/.test(c);
        var hasChartCue = /(?:グラフ|棒グラフ|折れ線|円グラフ|散布図|面グラフ)/.test(c) &&
          !/消|削除|なく|いらない/.test(c);
        var hasFilterWhereCue = (/(?:以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄)/.test(c) ||
          _DATE_CMP_CUE_RE_JS.test(nfkc(c)) ||
          !!_colContainsOfJs(nfkc(c), table) ||
          /[^\s、。]+?(?:が|は)[^\s、。の]+?の[^\s、。のをにはが]{1,12}/.test(c)) &&
          /(?:だけ(?:出し|見せ|表示|残し|絞)|のみ(?:出し|見せ|表示)|絞り込|フィルタ)/.test(c) &&
          !/(?:消|削除|別シート|抽出|色|ハイライト|目立|IF|判定|解除|外し|外す)/i.test(c);
        var hasFilterExtractCue = (/(?:以上|以下|未満|より大|より小|を超|超え|上回|下回|届か|届いてい?ない|以外|ではない|でない|じゃない|になっていない|になってない|空白|空欄)/.test(c) ||
          _DATE_CMP_CUE_RE_JS.test(nfkc(c)) ||
          !!_colContainsOfJs(nfkc(c), table) ||
          /[^\s、。]+?(?:が|は)[^\s、。の]+?の(?:行|データ|明細|レコード|案件|商品)/.test(c)) &&
          /抽出/.test(c) &&
          !/(?:上位|下位|トップ|ワースト|ベスト|URL|リンク|消|削除)/i.test(c);
        var hasFreezeCue = /固定|フリーズ/.test(c) &&
          !/解除|外|やめ|なく|値|式|数式|絶対参照|固定色|書式|太字|色|背景|罫線|揃え|寄せ/.test(c);
        var hasBlankDelCue = /空行|空いてる行|空いている行|空白行|空白の行|空き行/.test(c) &&
          !/重複|ダブ|全角|半角|整え|きれい|掃除|トリム|余分な空白|末尾|軽く|下まで|余白/.test(c);
        var hasBorderFmtCue = /罫線|外枠|格子/.test(c) &&
          !/整え|見やすく|体裁|きれい|区切り線|変わる行|切り替わる行|グリッド線|目盛り線|シート.*枠線/.test(c);
        var hasSeiriCleanCue = /(?:前後|余分な?|両端|先頭|末尾)の?(?:空白|スペース).*(?:消|削除|取り除|取っ|取る|除去|詰め|トリム)|(?:空白|スペース)を(?:消|削除|取り除|取っ|取る|除去|詰め|トリム)|全角(?:の?(?:英?数字|文字))?を半角/.test(c) &&
          !/空行|空白行|空白の行|空いてる行|空いている行|空き行|改行|不可視文字|ゴミ文字|セル内改行|穴埋め|上の値|以外の|じゃない|の行を消|の行を削除/.test(c);
        var hasDateFixCue = (c.indexOf("和暦") >= 0 ||
          (/(?:日付|入社日|生年月日|登録日|更新日|期限|yyyy\/mm\/dd|yyyy-mm-dd|年月日の?形)/i.test(c) &&
            /そろえ|揃え|統一|変換|本物の日付|ちゃんとした日付|西暦/.test(c))) &&
          !/並べ|ソート|絞り込|フィルタ|消|削除|連続|下まで|埋め|経過|年齢|曜日/.test(c);
        var hasPhoneFixCue = /(?:電話|携帯|TEL|tel)/.test(c) &&
          /ハイフン|区切り|そろえ|揃え|統一|整形|形式|直し/.test(c) &&
          !/全角|半角|空白|スペース|消|削除|非表示|隠|並|ソート|フィルタ|絞り込|マスク|伏せ字|桁区切|カンマ区切|3桁|三桁|円マーク|円表示|パーセント|%|％|書式|表示形式|太字|斜体|色|背景|中央|右揃|左揃|罫線/.test(c);
        var shortFmtOnlyReJs = /^(?:(?:タイトル|表題|見出し|ヘッダ|表全体|表|[^\s、。]{1,16}(?:の?列|の?欄)|[A-Z]{1,3}[0-9]*(?::[A-Z]{1,3}[0-9]*)?)(?:を|は|に)\s*)?(?:太字|斜体|イタリック|中央揃え|中央寄せ|真ん中揃え|真ん中寄せ|右揃え|右寄せ|左揃え|左寄せ|中央|真ん中|右|左|折り返し?|太字解除|斜体解除|折り返し解除|折り返しなし|罫線(?:なし|外枠)?|外枠|結合(?:解除)?|(?:白|黒|赤|青|緑|黄|紫|灰|橙|紺|茶|桃|水色|濃い?[^\s、。]{1,3}|薄い?[^\s、。]{1,3})(?:い|の)?(?:文字|背景|塗り)|(?:文字|フォント|背景|塗り)(?:は|を|に)?(?:白|黒|赤|青|緑|黄|紫|灰|橙|紺|茶|桃|水色|濃い?[^\s、。]{1,3}|薄い?[^\s、。]{1,3})|[0-9]+\s*(?:pt|ポイント)|(?:少し|もっと|だいぶ|かなり|ぐっと)?(?:大きく|小さく))(?:で|に|へ|も|は|を|にして|して)?$/;
        var cTrimFmt = nfkc(c).trim();
        var hasShortFmtCue = (shortFmtOnlyReJs.test(cTrimFmt) ||
          /(?:太字|斜体|イタリック|中央揃え|中央寄せ|右揃え|右寄せ|左揃え|左寄せ|折り返し)(?:で|に|も|は|を)?$/.test(cTrimFmt)) &&
          !/消|削除|解除|外|追加|挿入|移動|コピー|条件|以上|以下|未満|より|を超|上回|下回|届か|以外|じゃない|になって|固定|並|ソート|フィルタ|絞り|グラフ|集計|合計|平均|行を|の行/.test(c);
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
        } else if (/1行おき|交互|しましま|縞模様|ストライプ/.test(c) && !/条件|以上|以下|未満/.test(c)) {
          ensureBoost("banding.add");
        } else if (hasRemoveAct && /条件付き書式|自動でついた色|自動の色/.test(c)) {
          ensureBoost("cf.clear");
        } else if (hasRemoveAct && /プルダウン|入力規則/.test(c)) {
          ensureBoost("validation.clear");
        } else if (!hasRemoveAct && /プルダウン|選択肢から選|リストから選/.test(c)) {
          ensureBoost("validation.list");
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
        } else if (hasRemoveAct && /重複|ダブ/.test(c) && !/色|目立|ハイライト|印|数え|何件/.test(c) && _byName["dedupe"]) {
          ensureBoost("dedupe");
        } else if (hasRowDelCond) {
          ensureBoost("filter.delete");
        } else if (hasColsDelCue) {
          ensureBoost("cols.delete");
        } else if ((/(?:なら|であれば).*(?:そうでなければ|そうでなく|それ以外|さもなくば|そうでない場合|でなければ).*(?:列|欄)/.test(c) || /IF文|条件分岐|判定列/i.test(c)) && _byName["calc.if"]) {
          ensureBoost("calc.if");
        } else if (/経過年数|経過月数|経過日数|勤続年数|勤続月数|在籍年数|満?年齢|築年数/.test(c) && !/順|並べ|ソート/.test(c) && !hasRowCfCue && !hasRowDelCond && !hasFilterWhereCue && _colNames(c, table).length <= 1 && _byName["date.age"]) {
          ensureBoost("date.age");
        } else if ((/から\s*(?:年|月|日|曜日|年度|四半期)の?(?:列|欄)/.test(c) || (/(?:^|[\s、。])(?:年|月|日|曜日|年度|四半期)の?(?:列|欄)/.test(c) && /足[しす]|作っ|作る|追加|取り出|抜き出|抽出/.test(c))) && !/経過|年齢|勤続|在籍|築年数|年数|月数|日数|年度別|揃え|寄せ|太字|斜体|色|背景|罫線|表示形式|桁区切|パーセント|%|％/.test(c) && _byName["date.parts"]) {
          ensureBoost("date.parts");
        } else if (hasRowCfCue) {
          ensureBoost("cf.add");
        } else if (hasChartCue) {
          ensureBoost("chart.new");
        } else if (hasFilterWhereCue) {
          ensureBoost("filter.where");
        } else if (hasFilterExtractCue) {
          ensureBoost("filter.extract");
        } else if ((_dateShiftOfJs(c, table) && /列|欄/.test(c)) || _multiColAggOfJs(c, table)) {
          ensureBoost("calc.col");
        } else if (/([^\s、,。をにから]{1,16})から([^\s、,。をにまで]{1,16})までの?(?:日数|期間)/.test(c) && !/月数|年数|営業日/.test(c)) {
          ensureBoost("calc.col");
        } else if (/重複|ダブ/.test(c) && /調べ|確認|チェック|ないか|探し|見つけ|色|目立|ハイライト/.test(c) && !hasRemoveAct && _byName["cf.dup"]) {
          ensureBoost("cf.dup");
        } else if (hasCalcDiffCue) {
          ensureBoost("calc.diff");
        } else if (hasCalcCue) {
          ensureBoost("calc.col");
        } else if (hasSummaryCue) {
          ensureBoost("summary");
        } else if (hasFreezeCue) {
          ensureBoost("freeze");
        } else if (hasBlankDelCue && (candMap["blank.rows.delete"] || candMap["seiri"])) {
          ensureBoost("blank.rows.delete");
        } else if (hasPhoneFixCue) {
          ensureBoost("phone.fix");
        } else if (hasDateFixCue) {
          ensureBoost("date.fix");
        } else if (hasSeiriCleanCue) {
          ensureBoost("seiri");
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
        } else if (/(?:列|カラム).{0,10}(?:追加|挿入|増や|足[しす])/.test(c) && !/合計|平均|件数|個数|計算|式|から|より|差|差分|年齢|勤続|経過|グラフ|削除|消|倍|半分|割増|割引|掛[けか]|足し|引き|割り|[%％]|平方根|乗/.test(nfkc(c))) {
          ensureBoost("cols.insert");
        } else if (hasStatRowCue) {
          ensureBoost("stat.row");
        } else if (hasPaintFmtCue || hasShortFmtCue) {
          ensureBoost("format");
        } else if (hasFmtCue && !/分け|取り出|抽出|列を足|列を作|経過|日数|年齢|勤続|本物の日付|ちゃんとした日付|文字列を日付|日付に変換|マイナス|赤字|三角|千円|百万/.test(c)) {
          ensureBoost("format");
        } else if (scored.length >= 2) {
          if (_colorHits(c).length > 0 && c.indexOf("文字") >= 0 && !/(?:大文字|小文字|全角|半角|UPPER|LOWER|PROPER)/i.test(c) && candMap["format"]) {
            boostName = "format";
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
          } else if (candMap["sheet.list"] && /教え|確認|見せて|あるか|どんなシート|何枚/.test(c) && /シート|タブ|何枚/.test(c) && !/目次|インデックス|作/.test(c)) {
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
        var hasOwnScope = carryKeys.some(function (k) { return _hasOwn(op, k); });
        if (!hasOwnScope) {
          for (var cki = 0; cki < carryKeys.length; cki++) {
            var sk = carryKeys[cki];
            if (_hasOwn(prev, sk)) {
              op[sk] = prev[sk];
              named = true;
              missing = _filterMissing(missing, ["range", "col", "header", "title"]);
            }
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

      if (top.name === "chart.new" && !missing.length) {
        var aggOpsJs = _chartSummaryOpsJs(op, c, table);
        if (aggOpsJs) {
          for (var aoi = 0; aoi < aggOpsJs.length; aoi++) p.ops.push(aggOpsJs[aoi]);
          lastIncomplete = null;
          continue;
        }
      }
      p.ops.push(op);
      if (top.name === "cols.insert" && !missing.length && op.at && table && table.header_row) {
        var mNewCol = /(?:^|[\s、。])(?:[『「]([^』」\n]{1,20})[』」]|([^\s、。の]{1,20})という)(?:の?列|カラム)/.exec(nfkc(c));
        if (mNewCol) {
          var newColNm = (mNewCol[1] || mNewCol[2] || "").trim();
          var atL = _letterOf(table, op.at) || (/^[A-Z]{1,3}$/.test(String(op.at)) ? String(op.at) : "");
          if (newColNm && newColNm !== "新しい" && newColNm !== "空" && newColNm !== "空の" && atL) {
            var wCells = {};
            wCells[atL + table.header_row] = newColNm;
            p.ops.push({ shelf: "write", cells: wCells });
          }
        }
      }
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
    // 守り: 読むだけの問い（変更動詞なし・問いの形）で、シートを触る棚が当たったら撃たない（読む棚だけは撃てる）
    if (p.fire && _isReadOnlyAskJs(askText) && p.ops.some(function (o) { var sh0 = _byName[o.shelf]; return sh0 && sh0.touch && sh0.touch.length; })) {
      p.fire = false;
    }
    var ambChoicesJs = _ambiguousTidyChoicesJs(askText, p.fire ? p.ops : [], kind);
    if (ambChoicesJs) {
      p.fire = false;
      p.choices = ambChoicesJs;
      p.ops = [];
      p.reasons = ["どこまで整えるか選んでください"];
      p.missing = [];
      p.cards = [];
      p.suggest = null;
    } else if (!p.fire && _isReadOnlyAskJs(askText)) {
      p.readOnly = true;
      p.ops = [];
      p.reasons = [];
      p.missing = [];
      p.cards = [];
      p.suggest = null;
    } else if (!p.fire && !hasGuideBlock && !vagueM) {
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
      var b = buildOp(cands[i], nfkc(askText), table, sheets, curSheet);
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

  var _AI_DESTRUCTIVE_SHELVES_JS = {
    "rows.delete": 1, "cols.delete": 1, "filter.delete": 1,
    "clear.values": 1, "clear.all": 1, "sheet.delete": 1
  };
  var _AI_DELETE_CUE_RE_JS = /消|削除|取り除|捨て|クリア|空に|抜[いきく]|削[っりる]|除去|除外|詰め|無く|なく[しす]|減ら|落と/;
  var _AI_SPLITTABLE_RANGE_SHELVES_JS = {
    "clear.values": 1, "clear.format": 1, "clear.all": 1, "bg.clear": 1,
    "format": 1, "cf.add": 1, "cf.clear": 1,
    "formula.guard": 1, "formula.tovalue": 1, "round": 1, "text.case": 1, "text.affix": 1, "text.clean": 1,
    "note.clear": 1, "link.clear": 1, "checkbox": 1, "protect.add": 1
  };
  var _A1_PART_RE_JS = /^(?:(?:'(?:[^']|'')+'|[^!',\s]+)!)?(?:[A-Za-z]{1,3}\d*(?::[A-Za-z]{1,3}\d*)?|\d+:\d+)$/;

  function _expandDisjointRangeOpJs(op, shName, issues) {
    var rawR = op.range;
    if (typeof rawR !== "string" || rawR.indexOf(",") < 0) return [op];
    var parts = rawR.split(",").map(function (p) { return p.trim(); });
    for (var pi = 0; pi < parts.length; pi++) {
      if (!parts[pi] || !_A1_PART_RE_JS.test(parts[pi])) {
        issues.push("棚「" + shName + "」の range に不正な複数範囲（" + rawR + "）が含まれています");
        return null;
      }
    }
    var canSplit = !!_AI_SPLITTABLE_RANGE_SHELVES_JS[shName];
    if (shName === "format" && op.merge !== undefined && op.merge !== null) canSplit = false;
    if (!canSplit) {
      issues.push("棚「" + shName + "」の range にカンマ区切りの複数範囲（" + rawR + "）は使えません（1 範囲ずつに分けて指定してください）");
      return null;
    }
    if (parts.length > 50) {
      issues.push("棚「" + shName + "」の飛び地範囲が多すぎます（" + parts.length + " か所・上限 50）");
      return null;
    }
    var out = [];
    for (var pj = 0; pj < parts.length; pj++) {
      var cp = {};
      var ks = Object.keys(op);
      for (var k2 = 0; k2 < ks.length; k2++) cp[ks[k2]] = op[ks[k2]];
      cp.range = parts[pj];
      out.push(cp);
    }
    return out;
  }

  function auditAiOps(ops, askText, table) {
    _ensureInit();
    var issues = [];
    if (!Array.isArray(ops) || !ops.length) {
      return { ok: false, ops: [], issues: ["ops が空または配列ではありません"] };
    }
    var askS = String(askText || "").trim();
    var askN = nfkc(askS);
    if (askS && _isReadOnlyAskJs(askS)) {
      return { ok: false, ops: [], issues: ["読むだけの質問のためシートを変更する ops は実行しません"] };
    }
    var sanitized = [];
    for (var i = 0; i < ops.length; i++) {
      var raw = ops[i];
      if (!raw || typeof raw !== "object" || typeof raw.shelf !== "string" || !raw.shelf.trim()) {
        issues.push((i + 1) + " 番目の ops に 'shelf'（棚の名前）がありません");
        continue;
      }
      var op = {};
      var ks = Object.keys(raw);
      for (var ki = 0; ki < ks.length; ki++) {
        if (ks[ki] !== "ok") op[ks[ki]] = raw[ks[ki]];
      }
      var shName = op.shelf.trim();
      op.shelf = shName;
      var shObj = _byName[shName];
      if (!shObj) {
        issues.push("棚「" + shName + "」はありません（" + (i + 1) + " 番目）");
        continue;
      }
      var reqArgs = shObj.args || [];
      for (var ri = 0; ri < reqArgs.length; ri++) {
        var ra = reqArgs[ri];
        if (ra.req && (!_hasOwn(op, ra.name) || _isEmptyVal(op[ra.name]))) {
          issues.push("棚「" + shName + "」に必須引数「" + ra.name + "」がありません");
        }
      }
      if (Array.isArray(shObj.any) && shObj.any.length) {
        var anyHit = false;
        for (var ai0 = 0; ai0 < shObj.any.length; ai0++) {
          var ak0 = shObj.any[ai0];
          if (_hasOwn(op, ak0) && !_isEmptyVal(op[ak0])) { anyHit = true; break; }
        }
        if (!anyHit) {
          issues.push("棚「" + shName + "」に " + shObj.any.join("・") + " のどれかが要ります");
        }
      }
      if (askS && _AI_DESTRUCTIVE_SHELVES_JS[shName] && !_AI_DELETE_CUE_RE_JS.test(askN)) {
        issues.push("頼みに削除・消去の指示が無いため「" + shName + "」は実行しません");
        continue;
      }
      var expanded = _expandDisjointRangeOpJs(op, shName, issues);
      if (!expanded) continue;
      for (var ei = 0; ei < expanded.length; ei++) sanitized.push(expanded[ei]);
    }
    if (issues.length || !sanitized.length || !askS) {
      return { ok: !issues.length && sanitized.length > 0, ops: sanitized, issues: issues };
    }
    var scan = askS.replace(QUOTE_RE_G, " ").replace(PAREN_RE_G, " ");
    var colorHits = _colorHits(scan);
    scan = scan.replace(_HEX_COLOR_RE_G, " ");

    var allShelves = {};
    for (var si = 0; si < sanitized.length; si++) allShelves[sanitized[si].shelf] = 1;
    var multi = sanitized.length > 1;
    var hasAny = function (fn) {
      for (var xi = 0; xi < sanitized.length; xi++) if (fn(sanitized[xi])) return true;
      return false;
    };
    var sharedOk = {
      "サイズ（具体的な数値 pt）": hasAny(function (o) { return (o.size !== undefined && o.size !== null) || (o.size_delta !== undefined && o.size_delta !== null); }),
      "太字（bold）": hasAny(function (o) { return _hasOwn(o, "bold"); }),
      "斜体（italic）": hasAny(function (o) { return _hasOwn(o, "italic"); }),
      "配置（align）": hasAny(function (o) { return _hasOwn(o, "align"); }),
      "折り返し（wrap）": hasAny(function (o) { return _hasOwn(o, "wrap"); }),
      "罫線（borders）": hasAny(function (o) { return _hasOwn(o, "borders"); }),
      "結合（merge）": hasAny(function (o) { return _hasOwn(o, "merge"); }),
      "表示形式（number_format）": hasAny(function (o) { return _hasOwn(o, "number_format") || o.shelf === "format.negred" || o.shelf === "date.fix"; }),
      "色（color/bg）": hasAny(function (o) { return !!(o.bg || o.color || o.shelf === "cf.add" || o.shelf === "banding.add" || o.shelf === "sheet.color"); }),
      "条件付き書式（cf.add）の条件": !!allShelves["cf.add"],
      "固定（freeze）の指定": !!allShelves["freeze"],
      "並べ替え（sort）の指定": !!allShelves["sort"],
      "絞り込み（filter）の指定": !!(allShelves["filter.on"] || allShelves["filter.where"] || allShelves["filter.delete"] || allShelves["filter.extract"] || allShelves["filter.off"]),
      "逆の操作（外す・消す・解除）の語が含まれています": !!(allShelves["banding.remove"] || allShelves["cf.clear"] || allShelves["validation.clear"] || allShelves["filter.off"] || allShelves["unfreeze"] || allShelves["protect.remove"] || allShelves["group.remove"] || allShelves["chart.delete"] || allShelves["bg.clear"] || allShelves["clear.format"] || allShelves["clear.values"] || allShelves["clear.all"])
    };
    for (var oi = 0; oi < sanitized.length; oi++) {
      var opCur = sanitized[oi];
      var shCur = _byName[opCur.shelf];
      if (!shCur) continue;
      var opMiss = [];
      _auditBuiltOpJs(shCur, opCur, askS, scan, table, colorHits, opMiss);
      for (var mi = 0; mi < opMiss.length; mi++) {
        var mTxt = opMiss[mi];
        if (multi && sharedOk[mTxt]) continue;
        var tag = multi ? (opCur.shelf + ": " + mTxt) : mTxt;
        if (issues.indexOf(tag) < 0) issues.push(tag);
      }
    }
    return { ok: !issues.length, ops: sanitized, issues: issues };
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
    auditAiOps: auditAiOps,
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
