  // ---- 一覧タブ・マイマクロ・手順マクロ ----
  var QUICK_LS_KEY = "gascombo_quick_cache_v1";
  var QUICK_CODE_LS_KEY = "gascombo_quick_codes_v1";
  var QUICK_USAGE_LS_KEY = "gascombo_quick_usage_v1";
  var QUICK_UI_LS_KEY = "gascombo_quick_ui_v1";
  var QUICK_TAG = { my: "マイ", shelf: "棚" };
  var _quickShelfCacheSheet = null;
  var _quickShelfCacheDoc = null;
  var _quickSynRules = null;
  var quickPinSaveTimer = null;
  var quickSaveTimer = {};
  var quickEditState = { mode: "edit", name: "", myUrl: "", delArmed: false, origCode: "", pendingReqId: "", activeTab: "code", chatHistory: [], codeUpdated: false };
  var quickEditReqSeq = 0;

  function quickNorm(t) {
    var s = String(t || "");
    if (typeof s.normalize === "function") s = s.normalize("NFKC");
    s = s.replace(/[\u30a1-\u30f6]/g, function(ch) { return String.fromCharCode(ch.charCodeAt(0) - 0x60); });
    return s.toLowerCase().replace(/[\s　]+/g, "");
  }

  function quickGetSynRules() {
    if (_quickSynRules) return _quickSynRules;
    var raw = (typeof COMBO_CATALOG_DATA !== "undefined" && COMBO_CATALOG_DATA.synonyms) || [];
    var rules = [];
    for (var i = 0; i < raw.length; i++) {
      var pair = raw[i];
      if (!Array.isArray(pair) || pair.length < 2) continue;
      var a = quickNorm(pair[0]), b = quickNorm(pair[1]);
      if (a && b && a !== b) rules.push([a, b]);
    }
    rules.sort(function(x, y) { return y[0].length - x[0].length; });
    _quickSynRules = rules;
    return _quickSynRules;
  }

  function quickNormSyn(t) {
    var s = quickNorm(t);
    if (!s) return "";
    var rules = quickGetSynRules();
    for (var i = 0; i < rules.length; i++) {
      var a = rules[i][0];
      if (s.indexOf(a) >= 0) s = s.split(a).join(rules[i][1]);
    }
    return s;
  }

  function quickAttachNorm(it) {
    if (!it || it._nw) return it;
    var seen = {}, list = [];
    var rawList = [it.label, it.name].concat(it.words || [], it.cat ? [it.cat] : []);
    for (var i = 0; i < rawList.length; i++) {
      var r = rawList[i];
      if (!r) continue;
      var n = quickNorm(r);
      if (n && !seen[n]) { seen[n] = 1; list.push(n); }
      var ns = quickNormSyn(r);
      if (ns && !seen[ns]) { seen[ns] = 1; list.push(ns); }
    }
    it._nw = list;
    it._nd = it.desc ? quickNormSyn(it.desc) : "";
    it._nst = (it.steps && it.steps.length) ? quickNormSyn(it.steps.join(" ")) : "";
    return it;
  }

  function quickShelfItems() {
    var isDoc = !!(state.target && state.target.kind === "doc");
    if (isDoc && _quickShelfCacheDoc) return _quickShelfCacheDoc;
    if (!isDoc && _quickShelfCacheSheet) return _quickShelfCacheSheet;
    var shelves = (typeof COMBO_CATALOG_DATA !== "undefined" && COMBO_CATALOG_DATA.shelves) || [];
    var items = shelves.filter(function(sh) {
      if (sh.searchable === false || sh.name === "api") return false;
      return isDoc ? (sh.kind === "doc" || sh.shared) : (sh.kind !== "doc");
    }).map(function(sh) {
      var needArgs = (sh.args || []).some(function(a) { return a.req; });
      var ex = (Array.isArray(sh.examples) && sh.examples.length && Array.isArray(sh.examples[0]) && sh.examples[0][0])
        ? String(sh.examples[0][0]) : "";
      return quickAttachNorm({ src: "shelf", name: sh.name, label: sh.title || sh.name, cat: sh.category || "", words: sh.words || [], desc: "", example: ex, needArgs: needArgs });
    });
    if (isDoc) _quickShelfCacheDoc = items;
    else _quickShelfCacheSheet = items;
    return items;
  }

  function quickCatList() {
    var counts = {}, list = quickShelfItems();
    for (var i = 0; i < list.length; i++) {
      var c = list[i].cat || "その他";
      counts[c] = (counts[c] || 0) + 1;
    }
    var order = (typeof COMBO_CATALOG_DATA !== "undefined" && COMBO_CATALOG_DATA.categories) || [];
    var out = [], seen = {};
    for (var j = 0; j < order.length; j++) {
      var oc = order[j];
      if (counts[oc]) { out.push({ name: oc, count: counts[oc] }); seen[oc] = 1; }
    }
    Object.keys(counts).forEach(function(k) { if (!seen[k]) out.push({ name: k, count: counts[k] }); });
    return out;
  }

  function quickOrdered(list, order) {
    var pos = {};
    (order || []).forEach(function(n, i) { pos[n] = i; });
    return list.map(function(it, i) { return { it: it, i: i }; }).sort(function(a, b) {
      var pa = pos.hasOwnProperty(a.it.name) ? pos[a.it.name] : -100000 + a.i;
      var pb = pos.hasOwnProperty(b.it.name) ? pos[b.it.name] : -100000 + b.i;
      return pa - pb;
    }).map(function(x) { return x.it; });
  }

  function quickAllItems() {
    var q = state.quick, my = [];
    (q.my || []).forEach(function(f) {
      my.push(quickAttachNorm({ src: "my", name: f.name, label: f.name, words: f.words || [], desc: f.desc || "", steps: Array.isArray(f.steps) ? f.steps : [], directOps: Array.isArray(f.directOps) ? f.directOps : [] }));
    });
    return quickOrdered(my, q.order.my).concat(quickOrdered(quickShelfItems(), q.order.shelf));
  }

  function quickPinKey(it) { return it ? (it.src + ":" + it.name) : ""; }
  function quickIsPinned(it) { return !!(it && state.quick.pins && state.quick.pins[quickPinKey(it)]); }
  function quickUsageKey(it) { return it ? ((it.src || "") + ":" + (it.name || "")) : ""; }

  function quickSaveUsage() {
    try { window.localStorage.setItem(QUICK_USAGE_LS_KEY, JSON.stringify(state.quick.usage || {})); } catch (e) {}
  }

  function quickSaveUiState() {
    try {
      window.localStorage.setItem(QUICK_UI_LS_KEY, JSON.stringify({
        cat: state.quick.cat || "all",
        recentSort: state.quick.recentSort === "count" ? "count" : "time",
        collapsedCats: state.quick.collapsedCats || {},
        defaultTab: state.quick.defaultTab === "list" ? "list" : "auto"
      }));
    } catch (e) {}
  }

  function quickRecordUsage(it) {
    if (!it || !it.src || !it.name) return;
    var u = state.quick.usage || (state.quick.usage = {});
    var k = quickUsageKey(it), prev = u[k] || {};
    u[k] = { c: (prev.c || 0) + 1, t: Date.now() };
    var keys = Object.keys(u);
    if (keys.length > 150) {
      keys.sort(function(a, b) { return ((u[b] && u[b].t) || 0) - ((u[a] && u[a].t) || 0); });
      for (var i = 150; i < keys.length; i++) delete u[keys[i]];
    }
    quickSaveUsage();
  }

  function quickRestoreCodeCache() {
    try {
      var raw = window.localStorage.getItem(QUICK_CODE_LS_KEY);
      if (raw) {
        var c = JSON.parse(raw);
        if (c && typeof c === "object" && c.map && typeof c.map === "object") {
          state.quick.codeCache = { stamp: String(c.stamp || ""), map: c.map };
        }
      }
    } catch (e) {}
  }

  function quickSaveCodeCache() {
    try {
      var cc = state.quick.codeCache || { stamp: "", map: {} };
      window.localStorage.setItem(QUICK_CODE_LS_KEY, JSON.stringify({ stamp: cc.stamp || "", map: cc.map || {} }));
    } catch (e) {}
  }

  function quickClearCodeCache() {
    state.quick.codeCache = { stamp: "", map: {} };
    try { window.localStorage.removeItem(QUICK_CODE_LS_KEY); } catch (e) {}
  }

  function quickRememberLocal() {
    var q = state.quick;
    try {
      window.localStorage.setItem(QUICK_LS_KEY, JSON.stringify({
        my: q.my || [],
        myId: q.myId || "",
        myUrl: q.myUrl || "",
        myStamp: q.myStamp || "",
        order: { my: q.order.my || [], shelf: q.order.shelf || [] },
        pins: q.pins || {}
      }));
    } catch (e) {}
  }

  function quickItemTip(it) {
    if (!it) return "";
    if (it.steps && it.steps.length) {
      var st = "⚡ 手順: " + it.steps.join(" / ");
      return it.desc ? (it.desc + " — " + st) : st;
    }
    if (it.desc) return it.desc;
    if (it.src === "shelf") {
      var head = (it.cat ? "[" + it.cat + "] " : "") + "棚: " + it.name;
      var body = it.example ? (head + " — 例: " + it.example) : head;
      return it.needArgs ? (body + "（Enter／ダブルクリックで入力欄へ例をセット）") : body;
    }
    return it.label;
  }

  function quickTogglePin(it) {
    if (!it) return;
    var k = quickPinKey(it);
    if (!state.quick.pins) state.quick.pins = {};
    if (state.quick.pins[k]) delete state.quick.pins[k];
    else state.quick.pins[k] = 1;
    state.quick._pinsSynced = true;
    quickRememberLocal();
    renderQuickList();
    if (hasGasBridge()) {
      clearTimeout(quickPinSaveTimer);
      quickPinSaveTimer = setTimeout(function() {
        callGas("comboQuickSavePins", { pins: state.quick.pins }, function() {}, function() {});
      }, 400);
    }
  }

  function quickMove(dir) {
    var q = state.quick, items = q.items || [], it = items[q.sel];
    if (!it || (els.askInput.value || "").trim() || q.filter !== "all") return;
    var j = q.sel + dir, other = items[j];
    if (!other || other.src !== it.src || quickIsPinned(it) !== quickIsPinned(other)) return;
    var group = quickAllItems().filter(function(x) { return x.src === it.src; }).map(function(x) { return x.name; });
    var a = group.indexOf(it.name), b = group.indexOf(other.name);
    if (a < 0 || b < 0) return;
    group[a] = other.name; group[b] = it.name;
    q.order[it.src] = group;
    q.sel = j;
    renderQuickList();
    var row = els.quickList.querySelectorAll(".quick-item")[j];
    if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
    quickRememberLocal();
    clearTimeout(quickSaveTimer[it.src]);
    quickSaveTimer[it.src] = setTimeout(function() {
      callGas("comboQuickSaveOrder", { kind: it.src, names: group, targetId: state.target.id || "" }, function() {}, function() {});
    }, 700);
  }

  function quickMoveButtons(idx) {
    var items = state.quick.items || [], it = items[idx];
    var box = document.createElement("span");
    box.className = "quick-move";
    var pinBtn = document.createElement("button");
    pinBtn.type = "button";
    var pinned = quickIsPinned(it);
    pinBtn.textContent = pinned ? "★" : "☆";
    pinBtn.title = pinned ? "ピン留めを外す" : "ピン留め（★）";
    if (pinned) pinBtn.className = "is-pinned";
    pinBtn.addEventListener("click", function(e) { e.stopPropagation(); quickTogglePin(it); });
    pinBtn.addEventListener("dblclick", function(e) { e.stopPropagation(); });
    box.appendChild(pinBtn);
    var filtering = !!(els.askInput.value || "").trim() || state.quick.filter !== "all";
    [["▲", -1], ["▼", 1]].forEach(function(d) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = d[0];
      b.title = d[1] < 0 ? "上へ（Alt+↑）" : "下へ（Alt+↓）";
      var nb = items[idx + d[1]];
      b.disabled = filtering || !nb || nb.src !== it.src || (quickIsPinned(nb) !== quickIsPinned(it));
      b.addEventListener("click", function(e) { e.stopPropagation(); quickMove(d[1]); });
      b.addEventListener("dblclick", function(e) { e.stopPropagation(); });
      box.appendChild(b);
    });
    return box;
  }

  function quickScoreToken(item, t, ts) {
    if (!t) return 1;
    quickAttachNorm(item);
    var best = 0, nw = item._nw || [];
    for (var i = 0; i < nw.length; i++) {
      var n = nw[i];
      if (n === t || (ts && n === ts)) best = Math.max(best, 100);
      else if (n.indexOf(t) >= 0 || (ts && n.indexOf(ts) >= 0)) best = Math.max(best, 60);
      else if (n.length >= 2 && (t.indexOf(n) >= 0 || (ts && ts.indexOf(n) >= 0))) best = Math.max(best, 40 + Math.min(n.length, 20));
    }
    if (!best && item._nd && (item._nd.indexOf(t) >= 0 || (ts && item._nd.indexOf(ts) >= 0))) best = 30;
    if (!best && item._nst && (item._nst.indexOf(t) >= 0 || (ts && item._nst.indexOf(ts) >= 0))) best = 25;
    return best;
  }

  function quickScore(item, txt) {
    if (!txt) return 1;
    var raw = String(txt || "").trim();
    var parts = raw.split(/[\s　]+/).filter(Boolean);
    if (!parts.length) return 1;
    if (parts.length === 1) {
      var t0 = quickNorm(parts[0]);
      return t0 ? quickScoreToken(item, t0, quickNormSyn(parts[0])) : 1;
    }
    var total = 0, cnt = 0;
    for (var i = 0; i < parts.length; i++) {
      var t = quickNorm(parts[i]);
      if (!t) continue;
      var sc = quickScoreToken(item, t, quickNormSyn(parts[i]));
      if (!sc) return 0;
      total += sc;
      cnt++;
    }
    return cnt ? (Math.round(total / cnt) + 10) : 1;
  }

  function quickFiltered() {
    var txt = (els.askInput.value || "").trim();
    var q = state.quick;
    var f = q.filter || "all";
    var usage = q.usage || {};
    var all = quickAllItems().filter(function(it) {
      if (f === "all") return true;
      if (f === "pin") return quickIsPinned(it);
      if (f === "recent") return !!(usage[quickUsageKey(it)] && usage[quickUsageKey(it)].t);
      if (f === "shelf") {
        if (it.src !== "shelf") return false;
        if (q.cat && q.cat !== "all" && (it.cat || "その他") !== q.cat) return false;
        return true;
      }
      return it.src === f;
    });
    if (!txt) {
      if (f === "recent") {
        var byCount = q.recentSort === "count";
        return all.slice().sort(function(a, b) {
          var ua = usage[quickUsageKey(a)] || {}, ub = usage[quickUsageKey(b)] || {};
          return byCount
            ? (((ub.c || 0) - (ua.c || 0)) || ((ub.t || 0) - (ua.t || 0)))
            : (((ub.t || 0) - (ua.t || 0)) || ((ub.c || 0) - (ua.c || 0)));
        });
      }
      if (f === "all" && q.pins && Object.keys(q.pins).length) {
        var pinned = all.filter(quickIsPinned);
        var rest = all.filter(function(it) { return !quickIsPinned(it); });
        return pinned.concat(rest);
      }
      return all;
    }
    var srcRank = { my: 2, shelf: 1 };
    var byCnt = q.recentSort === "count";
    return all.map(function(it, i) {
      var ua = usage[quickUsageKey(it)];
      return { it: it, s: quickScore(it, txt), p: quickIsPinned(it) ? 1 : 0, t: (ua && ua.t) || 0, c: (ua && ua.c) || 0, i: i };
    }).filter(function(x) { return x.s > 0; })
      .sort(function(a, b) {
        var recCmp = f === "recent" ? (byCnt ? ((b.c - a.c) || (b.t - a.t)) : ((b.t - a.t) || (b.c - a.c))) : 0;
        return (b.s - a.s) || recCmp || (b.p - a.p) || (srcRank[b.it.src] - srcRank[a.it.src]) || (a.i - b.i);
      })
      .map(function(x) { return x.it; });
  }

  function renderQuickCatBar() {
    if (!els.quickCatBar) return;
    var hasFrag = typeof document.createDocumentFragment === "function";
    if (state.quick.filter === "recent") {
      els.quickCatBar.style.display = "";
      var mode = state.quick.recentSort === "count" ? "count" : "time";
      var rFrag = hasFrag ? document.createDocumentFragment() : (els.quickCatBar.innerHTML = "", els.quickCatBar);
      [["time", "最近順"], ["count", "よく使う順"]].forEach(function(pair) {
        var rb = document.createElement("button");
        rb.type = "button";
        rb.className = "quick-cat-btn" + (mode === pair[0] ? " active" : "");
        rb.textContent = pair[1];
        rb.addEventListener("click", function() {
          state.quick.recentSort = pair[0];
          state.quick.sel = -1;
          quickSaveUiState();
          renderQuickCatBar();
          renderQuickList();
        });
        rFrag.appendChild(rb);
      });
      if (hasFrag) {
        els.quickCatBar.innerHTML = "";
        els.quickCatBar.appendChild(rFrag);
      }
      return;
    }
    if (state.quick.filter !== "shelf") {
      els.quickCatBar.style.display = "none";
      return;
    }
    var cats = quickCatList();
    if (!cats.length) { els.quickCatBar.style.display = "none"; return; }
    els.quickCatBar.style.display = "";
    var cur = state.quick.cat || "all";
    if (cur !== "all" && !cats.some(function(c) { return c.name === cur; })) cur = state.quick.cat = "all";
    var frag = hasFrag ? document.createDocumentFragment() : (els.quickCatBar.innerHTML = "", els.quickCatBar);
    var total = quickShelfItems().length;
    var mkBtn = function(catKey, labelText) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "quick-cat-btn" + (cur === catKey ? " active" : "");
      b.textContent = labelText;
      b.addEventListener("click", function() {
        state.quick.cat = catKey;
        state.quick.sel = -1;
        quickSaveUiState();
        renderQuickCatBar();
        renderQuickList();
      });
      return b;
    };
    frag.appendChild(mkBtn("all", "すべて " + total));
    cats.forEach(function(c) { frag.appendChild(mkBtn(c.name, c.name + " " + c.count)); });
    if (hasFrag) {
      els.quickCatBar.innerHTML = "";
      els.quickCatBar.appendChild(frag);
    }
  }

  function updateQuickEditBtnState() {
    if (!els.btnQuickEdit) return;
    var q = state.quick, it = (q.items || [])[q.sel];
    if (!q.myId) {
      els.btnQuickEdit.disabled = false;
      els.btnQuickEdit.textContent = "マイマクロを作る";
      return;
    }
    els.btnQuickEdit.textContent = "編集";
    els.btnQuickEdit.disabled = !(it && it.src === "my");
  }

  function updateSettingsMyMacroUI() {
    var q = state.quick;
    if (els.settingsMyStatus) {
      els.settingsMyStatus.textContent = q.myId
        ? "作成済み（GASクイックと共通のマイマクロを使えます）"
        : "未作成です。下のボタンから作成できます";
    }
    if (els.btnSettingsMyMacro) {
      els.btnSettingsMyMacro.textContent = q.myId ? "マイマクロをエディタで開く" : "マイマクロを作る";
    }
  }

  function quickMarkSel(idx) {
    if (!els.quickList) return;
    var rows = els.quickList.querySelectorAll(".quick-item");
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.toggle("selected", i === idx);
      var mv = rows[i].querySelector(".quick-move");
      if (mv && i !== idx) mv.parentNode.removeChild(mv);
      if (i === idx && !mv) rows[i].appendChild(quickMoveButtons(idx));
    }
    updateQuickEditBtnState();
  }

  function quickSelectIdx(idx) {
    var items = state.quick.items || [];
    if (idx < 0 || idx >= items.length) {
      state.quick.sel = -1;
      quickMarkSel(-1);
      return;
    }
    state.quick.sel = idx;
    quickMarkSel(idx);
    var rows = els.quickList ? els.quickList.querySelectorAll(".quick-item") : [];
    var row = rows[idx];
    if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
    if (els.quickNote) els.quickNote.textContent = quickItemTip(items[idx]);
  }

  function quickMakeRow(it, idx, showCatPill) {
    var row = document.createElement("div");
    row.className = "hist-item quick-item" + (state.quick.sel === idx ? " selected" : "");
    var tag = document.createElement("span");
    tag.className = "quick-tag t-" + it.src;
    tag.textContent = QUICK_TAG[it.src] || it.src;
    row.appendChild(tag);
    if (showCatPill && it.src === "shelf" && it.cat) {
      var pill = document.createElement("span");
      pill.className = "quick-cat-pill";
      pill.textContent = it.cat;
      row.appendChild(pill);
    }
    if (quickIsPinned(it)) {
      var pinMk = document.createElement("span");
      pinMk.className = "quick-pin-mark";
      pinMk.textContent = "★";
      pinMk.title = "ピン留め済み";
      row.appendChild(pinMk);
    }
    if (it.steps && it.steps.length) {
      var bolt = document.createElement("span");
      bolt.className = "quick-bolt";
      bolt.textContent = "⚡";
      bolt.title = "手順つき（直結対応）";
      row.appendChild(bolt);
    }
    var lab = document.createElement("span");
    lab.className = "quick-label";
    lab.textContent = it.label;
    row.appendChild(lab);
    if (state.quick.filter === "recent") {
      var uInfo = (state.quick.usage || {})[quickUsageKey(it)];
      if (uInfo && uInfo.c) {
        var cntPill = document.createElement("span");
        cntPill.className = "quick-cnt-pill";
        cntPill.textContent = uInfo.c + "回";
        row.appendChild(cntPill);
      }
    }
    if (it.src === "shelf" && it.needArgs) {
      var amk = document.createElement("span");
      amk.className = "quick-arg-mark";
      amk.textContent = "✎";
      amk.title = "列や言葉などの指定が必要（Enter／ダブルクリックで入力例をセット）";
      row.appendChild(amk);
    }
    var tip = quickItemTip(it);
    row.addEventListener("mouseenter", function() { if (els.quickNote) els.quickNote.textContent = tip; });
    row.addEventListener("click", function() {
      if (state.busy) return;
      state.quick.sel = idx;
      quickMarkSel(idx);
      if (els.quickNote) els.quickNote.textContent = tip;
    });
    row.addEventListener("dblclick", function() {
      if (state.busy) return;
      state.quick.sel = idx;
      quickMarkSel(idx);
      quickRunItem(it);
    });
    if (state.quick.sel === idx) row.appendChild(quickMoveButtons(idx));
    return row;
  }

  function renderQuickList() {
    if (!els.quickList) return;
    var q = state.quick;
    var txt = (els.askInput.value || "").trim();
    var f = q.filter || "all";
    var items = quickFiltered();
    var grouped = (f === "shelf" && !txt && (!q.cat || q.cat === "all"));
    var visibleItems = [];
    var hasFrag = typeof document.createDocumentFragment === "function";
    var frag = hasFrag ? document.createDocumentFragment() : (els.quickList.innerHTML = "", els.quickList);
    if (!items.length) {
      var empty = document.createElement("div");
      empty.className = "log-empty";
      if (!q.loaded) empty.textContent = "読込中…";
      else if (f === "recent") empty.textContent = txt ? "該当する最近の実行がありません" : "まだ実行履歴がありません（マイや棚を実行するとここに並びます）";
      else empty.textContent = "当たるマクロがありません（実行で頼みとして撃ちます）";
      frag.appendChild(empty);
      q.sel = -1;
      q.items = [];
    } else if (grouped) {
      var buckets = {}, catOrder = [];
      var knownOrder = (typeof COMBO_CATALOG_DATA !== "undefined" && COMBO_CATALOG_DATA.categories) || [];
      items.forEach(function(it) {
        var c = it.cat || "その他";
        if (!buckets[c]) { buckets[c] = []; catOrder.push(c); }
        buckets[c].push(it);
      });
      catOrder.sort(function(a, b) {
        var ia = knownOrder.indexOf(a), ib = knownOrder.indexOf(b);
        if (ia < 0) ia = 999;
        if (ib < 0) ib = 999;
        return ia - ib;
      });
      var collapsedMap = q.collapsedCats || (q.collapsedCats = {});
      catOrder.forEach(function(catName) {
        if (!collapsedMap[catName]) {
          buckets[catName].forEach(function(it) { visibleItems.push(it); });
        }
      });
      if (q.sel >= visibleItems.length) q.sel = -1;
      q.items = visibleItems;
      var vIdx = 0;
      catOrder.forEach(function(catName) {
        var list = buckets[catName];
        var isCol = !!collapsedMap[catName];
        var hdr = document.createElement("div");
        hdr.className = "quick-group-hdr";
        var left = document.createElement("span");
        left.textContent = (isCol ? "▶ " : "▼ ") + catName;
        var right = document.createElement("span");
        right.textContent = list.length + " 本";
        hdr.appendChild(left);
        hdr.appendChild(right);
        hdr.addEventListener("click", function() {
          q.collapsedCats[catName] = !isCol;
          q.sel = -1;
          quickSaveUiState();
          renderQuickList();
        });
        frag.appendChild(hdr);
        if (!isCol) {
          list.forEach(function(it) {
            frag.appendChild(quickMakeRow(it, vIdx++, false));
          });
        }
      });
    } else {
      visibleItems = items;
      if (q.sel >= visibleItems.length) q.sel = -1;
      q.items = visibleItems;
      var showPill = f !== "shelf";
      visibleItems.forEach(function(it, idx) {
        frag.appendChild(quickMakeRow(it, idx, showPill));
      });
    }
    if (hasFrag) {
      els.quickList.innerHTML = "";
      els.quickList.appendChild(frag);
    }
    updateQuickEditBtnState();
    updateSettingsMyMacroUI();
  }

  function quickRestoreList() {
    try {
      var raw = window.localStorage.getItem(QUICK_LS_KEY);
      if (raw) {
        var c = JSON.parse(raw), q = state.quick;
        q.my = c.my || []; q.myId = c.myId || ""; q.myUrl = c.myUrl || ""; q.myStamp = c.myStamp || "";
        if (c.order) { q.order.my = c.order.my || []; q.order.shelf = c.order.shelf || []; }
        if (c.pins && typeof c.pins === "object") q.pins = c.pins;
      }
    } catch (e) {}
    try {
      var uRaw = window.localStorage.getItem(QUICK_USAGE_LS_KEY);
      if (uRaw) {
        var uObj = JSON.parse(uRaw);
        if (uObj && typeof uObj === "object" && !Array.isArray(uObj)) state.quick.usage = uObj;
      }
    } catch (e) {}
    try {
      var uiRaw = window.localStorage.getItem(QUICK_UI_LS_KEY);
      if (uiRaw) {
        var uiObj = JSON.parse(uiRaw);
        if (uiObj && typeof uiObj === "object") {
          if (typeof uiObj.cat === "string" && uiObj.cat) state.quick.cat = uiObj.cat;
          if (uiObj.recentSort === "count" || uiObj.recentSort === "time") state.quick.recentSort = uiObj.recentSort;
          if (uiObj.collapsedCats && typeof uiObj.collapsedCats === "object" && !Array.isArray(uiObj.collapsedCats)) {
            state.quick.collapsedCats = uiObj.collapsedCats;
          }
          if (uiObj.defaultTab === "list" || uiObj.defaultTab === "auto") {
            state.quick.defaultTab = uiObj.defaultTab;
          }
        }
      }
    } catch (e) {}
    if (els.settingsDefaultTab) els.settingsDefaultTab.value = state.quick.defaultTab || "auto";
    quickRestoreCodeCache();
    state.quick.loaded = true;
    renderQuickCatBar();
    renderQuickList();
  }

  function applyQuickListRes(res) {
    if (!res || typeof res !== "object" || res.ok === false) return;
    var q = state.quick;
    q.loaded = true;
    q._fetchedOnce = true;
    if (res.order) {
      q.order = { my: res.order.my || [], shelf: res.order.shelf || [] };
    }
    var prevStamp = q.myStamp || "";
    q.my = res.my || [];
    q.myId = res.myId || "";
    q.myUrl = res.myUrl || "";
    q.myStamp = res.myStamp || "";
    if (q.codeCache && q.codeCache.stamp && q.myStamp && q.codeCache.stamp !== q.myStamp) {
      quickClearCodeCache();
    } else if (!q.myId && prevStamp) {
      quickClearCodeCache();
    }
    if (res.myCodes && typeof res.myCodes === "object") {
      q.codeCache = { stamp: q.myStamp || "", map: res.myCodes };
      quickSaveCodeCache();
    }
    if (res.pins && typeof res.pins === "object" && !Array.isArray(res.pins)) {
      var srvPinKeys = Object.keys(res.pins);
      var locPinKeys = Object.keys(q.pins || {});
      if (srvPinKeys.length === 0 && !q._pinsSynced && locPinKeys.length > 0) {
        q._pinsSynced = true;
        if (hasGasBridge()) {
          callGas("comboQuickSavePins", { pins: q.pins }, function() {}, function() {});
        }
      } else {
        q.pins = res.pins;
        q._pinsSynced = true;
      }
    }
    quickRememberLocal();
    if (els.quickNote) {
      if (res.myError) els.quickNote.textContent = "マイマクロを読めませんでした: " + res.myError;
      else if (!q.myId && !els.quickNote.textContent) els.quickNote.textContent = "「＋追加」または設定の「マイマクロを作る」で全シート共通マクロを作れます";
    }
    renderQuickCatBar();
    renderQuickList();
  }

  function loadQuickList(force) {
    var payload = {
      targetId: state.target.id || "",
      force: force === true,
      wantCodes: true,
      clientStamp: force === true ? "" : quickClientStamp()
    };
    callGas("comboQuickList", payload, function(res) {
      state.quick.loaded = true;
      if (res && res.ok) applyQuickListRes(res);
      else renderQuickList();
    }, function(err) {
      state.quick.loaded = true;
      if (els.quickNote) els.quickNote.textContent = "一覧を読めませんでした: " + formatError(err);
      renderQuickList();
    });
  }

  function quickCompileSteps(steps) {
    var kind = (state.target && state.target.kind) || "sheet";
    var baseScope = getActiveScope();
    var ops = [], carry = null;
    for (var i = 0; i < steps.length; i++) {
      var stepTxt = String(steps[i] || "").trim();
      if (!stepTxt) continue;
      var p = null;
      if (carry && !hasSelectionPronoun(stepTxt)) {
        var pCarry = Planner.plan(stepTxt, kind, state.table, state.sheets, state.curSheet, carry);
        if (pCarry && pCarry.fire && Array.isArray(pCarry.ops) && pCarry.ops.length && pCarry.ops[0].shelf === "format") {
          p = pCarry;
        }
      }
      if (!p) {
        p = Planner.plan(stepTxt, kind, state.table, state.sheets, state.curSheet, baseScope);
      }
      if (p && Array.isArray(p.ops) && p.ops.length === 1 && p.ops[0] && p.ops[0].shelf === "width" &&
          !p.ops[0].width && !p.ops[0].cols && !p.ops[0].rows && !p.ops[0].auto &&
          /(?:自動|中身に合|オートフィット)/.test(stepTxt)) {
        var wOp = p.ops[0];
        if (wOp.col) {
          wOp.auto = [wOp.col];
          delete wOp.col;
        } else if (state.table && Array.isArray(state.table.columns)) {
          var allCols = state.table.columns.map(function(c) { return c.col; }).filter(Boolean);
          if (allCols.length) wOp.auto = allCols;
        }
        if (Array.isArray(wOp.auto) && wOp.auto.length && !(p.reasons && p.reasons.length)) {
          p.fire = true;
        }
      }
      if (!p || !p.fire || !Array.isArray(p.ops) || !p.ops.length) {
        var reason = "";
        if (p && p.reasons && p.reasons.length) reason = p.reasons.join("／");
        else if (p && p.missing && p.missing.length) reason = "不足: " + p.missing.join("、");
        return { ok: false, index: i + 1, step: stepTxt, reason: reason };
      }
      for (var j = 0; j < p.ops.length; j++) ops.push(p.ops[j]);
      var lastOp = p.ops[p.ops.length - 1];
      if (lastOp && lastOp.shelf === "format") {
        var nextCarry = {};
        ["header", "title", "range", "col"].forEach(function(k) {
          if (lastOp[k] !== undefined && lastOp[k] !== null && lastOp[k] !== "" && lastOp[k] !== false) nextCarry[k] = lastOp[k];
        });
        carry = Object.keys(nextCarry).length ? nextCarry : null;
      } else {
        carry = null;
      }
    }
    return { ok: true, ops: ops };
  }

  function applyLiveSelectionResult(live) {
    if (!live || !live.range) return;
    if (live.sheet && live.sheet !== state.curSheet && (!state.sheets.length || state.sheets.indexOf(live.sheet) >= 0 || typeof state.sheetIdMap[live.sheet] === "number")) {
      state.curSheet = live.sheet;
      syncSheetSelects();
    }
    state.selection = String(live.range).trim().toUpperCase();
    state.scope = Planner.parseSelectionScope ? Planner.parseSelectionScope(state.selection) : {};
    updateSelectionLabel();
  }

  function quickRunSteps(it) {
    var steps = (it && Array.isArray(it.steps)) ? it.steps : [];
    if (!steps.length) return;
    if (state.busy) {
      appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
      return;
    }
    var runCompiled = function() {
      var label = "マイマクロ " + it.name;
      var compiled = quickCompileSteps(steps);
      if (!compiled.ok) {
        var msg = "手順 " + compiled.index + "「" + compiled.step + "」が棚に当たりません" + (compiled.reason ? "（" + compiled.reason + "）" : "");
        if (els.quickNote) els.quickNote.textContent = "⚠ " + msg;
        appendLog(els.chatLog, "is-err", "[✗ " + label + "]", msg);
        return;
      }
      if (els.quickNote) els.quickNote.textContent = "⚡ 手順マクロ「" + it.name + "」を実行しました";
      onRunOps(compiled.ops, label, { switchToChat: false });
    };
    var needLiveSel = steps.some(function(s) { return hasSelectionPronoun(s); });
    if (els.chkSync && els.chkSync.checked && needLiveSel) {
      requestLiveSelection(function(live) {
        applyLiveSelectionResult(live);
        runCompiled();
      });
      return;
    }
    runCompiled();
  }

  /**
   * 定番の SpreadsheetApp 命令（色・太字・斜体・サイズ・背景・配置・値など）だけで書かれたマイマクロを
   * ブラウザ側でドライランし、Sheets API 直結用の ops 配列に変換する。
   * 未対応命令・範囲外アクセス・例外が 1 つでもあれば null を返し、従来の GAS 経由へ安全にフォールバックする。
   */
  function tryCompileMyMacroDirect(item, sheetName) {
    try {
      if (!item || item.src !== "my" || !item.name) return null;
      if (!state.oauthToken || !state.target.id || state.target.kind !== "sheet" || !sheetName) return null;
      if (els.chkBackup && els.chkBackup.checked) return null;
      if (typeof state.sheetIdMap[sheetName] !== "number") return null;
      var snap = state.sheetSnapshot && state.sheetSnapshot[sheetName];
      if (!snap || !Array.isArray(snap.cells) || !snap.cells.length) return null;
      var cc = state.quick && state.quick.codeCache && state.quick.codeCache.map;
      var code = cc && cc[item.name];
      if (!code || typeof code !== "string") return null;
      // 外部サービス・シート構成変更など直結対象外の識別子が含まれていれば即フォールバック
      if (/\b(?:DriveApp|UrlFetchApp|MailApp|GmailApp|DocumentApp|SlidesApp|CalendarApp|PropertiesService|CacheService|LockService|ScriptApp|Session|Utilities|Browser|HtmlService|Sheets|fetch|XMLHttpRequest|window|document|localStorage)\b/.test(code)) {
        return null;
      }
      var sheetId = state.sheetIdMap[sheetName];
      var maxRows = snap.maxRows || snap.cells.length;
      var maxCols = snap.maxCols || (snap.cells[0] ? snap.cells[0].length : 26);
      var UNSUPPORTED = new Error("DIRECT_UNSUPPORTED");
      var ops = [];
      // 同一マクロ内での書き込み→読み取りを整合させる仮想キャッシュ
      var vCells = {};
      var vVals = {};

      var rgbObjToHex = function(rgb) {
        if (!rgb || typeof rgb !== "object") return "";
        var ch = function(v) {
          var n = Math.max(0, Math.min(255, Math.round((Number(v) || 0) * 255)));
          return (n < 16 ? "0" : "") + n.toString(16);
        };
        return "#" + ch(rgb.red) + ch(rgb.green) + ch(rgb.blue);
      };
      var cellFormatAt = function(r0, c0) {
        if (r0 < 0 || c0 < 0 || r0 >= maxRows || c0 >= maxCols) throw UNSUPPORTED;
        var key = r0 + "," + c0;
        if (vCells[key]) return vCells[key];
        var base = (snap.cells[r0] && snap.cells[r0][c0]) ? JSON.parse(JSON.stringify(snap.cells[r0][c0])) : {};
        vCells[key] = base;
        return base;
      };
      var toA1 = function(r1, c1, r2, c2) {
        var s = num0ToCol(c1) + (r1 + 1);
        return (r1 === r2 && c1 === c2) ? s : (s + ":" + num0ToCol(c2) + (r2 + 1));
      };
      var parseRangeSpec = function(a1OrRow, col, numRows, numCols) {
        if (typeof a1OrRow === "string") {
          var clean = a1OrRow.trim();
          var bang = clean.indexOf("!");
          if (bang >= 0) {
            var shPart = clean.slice(0, bang).replace(/^'|'$/g, "").replace(/''/g, "'");
            if (shPart !== sheetName) throw UNSUPPORTED;
            clean = clean.slice(bang + 1);
          }
          var p = parseSimpleA1Range(clean, sheetId);
          if (!p) throw UNSUPPORTED;
          return { r1: p.r1, c1: p.c1, r2: p.r2, c2: p.c2 };
        }
        if (typeof a1OrRow === "number" && typeof col === "number") {
          var r1 = Math.floor(a1OrRow) - 1;
          var c1 = Math.floor(col) - 1;
          var nr = numRows === undefined ? 1 : Math.floor(Number(numRows));
          var nc = numCols === undefined ? 1 : Math.floor(Number(numCols));
          if (r1 < 0 || c1 < 0 || nr < 1 || nc < 1) throw UNSUPPORTED;
          return { r1: r1, c1: c1, r2: r1 + nr - 1, c2: c1 + nc - 1 };
        }
        throw UNSUPPORTED;
      };
      var makeRange = function(rg) {
        if (rg.r1 < 0 || rg.c1 < 0 || rg.r2 >= maxRows || rg.c2 >= maxCols) throw UNSUPPORTED;
        var a1 = toA1(rg.r1, rg.c1, rg.r2, rg.c2);
        var mutateRangeFmt = function(fn) {
          for (var r = rg.r1; r <= rg.r2; r++) {
            for (var c = rg.c1; c <= rg.c2; c++) {
              fn(cellFormatAt(r, c));
            }
          }
        };
        var rawObj = {
          getA1Notation: function() { return a1; },
          getRow: function() { return rg.r1 + 1; },
          getColumn: function() { return rg.c1 + 1; },
          getLastRow: function() { return rg.r2 + 1; },
          getLastColumn: function() { return rg.c2 + 1; },
          getNumRows: function() { return rg.r2 - rg.r1 + 1; },
          getNumColumns: function() { return rg.c2 - rg.c1 + 1; },
          getCell: function(row, col) {
            var rr = rg.r1 + Math.floor(Number(row)) - 1;
            var cc2 = rg.c1 + Math.floor(Number(col)) - 1;
            if (rr < rg.r1 || rr > rg.r2 || cc2 < rg.c1 || cc2 > rg.c2) throw UNSUPPORTED;
            return makeRange({ r1: rr, c1: cc2, r2: rr, c2: cc2 });
          },
          getFontColor: function() {
            var fmt = cellFormatAt(rg.r1, rg.c1);
            var tf = fmt.textFormat || {};
            if (tf.foregroundColorStyle) {
              if (tf.foregroundColorStyle.rgbColor) return rgbObjToHex(tf.foregroundColorStyle.rgbColor);
              if (tf.foregroundColorStyle.themeColor) throw UNSUPPORTED;
            }
            if (tf.foregroundColor) return rgbObjToHex(tf.foregroundColor);
            return "#000000";
          },
          getBackground: function() {
            var fmt = cellFormatAt(rg.r1, rg.c1);
            if (fmt.backgroundColorStyle) {
              if (fmt.backgroundColorStyle.rgbColor) return rgbObjToHex(fmt.backgroundColorStyle.rgbColor);
              if (fmt.backgroundColorStyle.themeColor) throw UNSUPPORTED;
            }
            if (fmt.backgroundColor) return rgbObjToHex(fmt.backgroundColor);
            return "#ffffff";
          },
          getFontWeight: function() {
            var fmt = cellFormatAt(rg.r1, rg.c1);
            return (fmt.textFormat && fmt.textFormat.bold) ? "bold" : "normal";
          },
          getFontStyle: function() {
            var fmt = cellFormatAt(rg.r1, rg.c1);
            return (fmt.textFormat && fmt.textFormat.italic) ? "italic" : "normal";
          },
          getFontSize: function() {
            var fmt = cellFormatAt(rg.r1, rg.c1);
            return (fmt.textFormat && fmt.textFormat.fontSize) || 10;
          },
          getValue: function() {
            if (!snap.vals) throw UNSUPPORTED;
            var k = num0ToCol(rg.c1) + (rg.r1 + 1);
            if (Object.prototype.hasOwnProperty.call(vVals, k)) return vVals[k];
            var ev = snap.vals[k];
            if (!ev) return "";
            if (ev.stringValue !== undefined) return ev.stringValue;
            if (ev.numberValue !== undefined) return ev.numberValue;
            if (ev.boolValue !== undefined) return ev.boolValue;
            throw UNSUPPORTED;
          },
          setFontColor: function(c) {
            var colVal = (c === null || c === undefined || c === "") ? "#000000" : String(c);
            var rgb = parseColorToRgbObj(colVal);
            if (!rgb) throw UNSUPPORTED;
            ops.push({ shelf: "format", range: a1, color: colVal });
            mutateRangeFmt(function(f) {
              f.textFormat = f.textFormat || {};
              f.textFormat.foregroundColorStyle = { rgbColor: rgb };
            });
            return proxy;
          },
          setBackground: function(c) {
            if (c === null || c === undefined || c === "" || isClearColor(c)) {
              ops.push({ shelf: "bg.clear", range: a1 });
              mutateRangeFmt(function(f) { delete f.backgroundColorStyle; delete f.backgroundColor; });
            } else {
              var rgb = parseColorToRgbObj(c);
              if (!rgb) throw UNSUPPORTED;
              ops.push({ shelf: "format", range: a1, bg: String(c) });
              mutateRangeFmt(function(f) { f.backgroundColorStyle = { rgbColor: rgb }; });
            }
            return proxy;
          },
          setFontWeight: function(w) {
            var isBold = String(w || "").toLowerCase() === "bold";
            ops.push({ shelf: "format", range: a1, bold: isBold });
            mutateRangeFmt(function(f) { f.textFormat = f.textFormat || {}; f.textFormat.bold = isBold; });
            return proxy;
          },
          setFontStyle: function(s) {
            var isItalic = String(s || "").toLowerCase() === "italic";
            ops.push({ shelf: "format", range: a1, italic: isItalic });
            mutateRangeFmt(function(f) { f.textFormat = f.textFormat || {}; f.textFormat.italic = isItalic; });
            return proxy;
          },
          setFontSize: function(n) {
            var sz = Number(n);
            if (!isFinite(sz) || sz <= 0) throw UNSUPPORTED;
            ops.push({ shelf: "format", range: a1, size: sz });
            mutateRangeFmt(function(f) { f.textFormat = f.textFormat || {}; f.textFormat.fontSize = sz; });
            return proxy;
          },
          setFontFamily: function(ff) {
            ops.push({ shelf: "format", range: a1, font: String(ff || "") });
            return proxy;
          },
          setHorizontalAlignment: function(al) {
            ops.push({ shelf: "format", range: a1, align: String(al || "") });
            return proxy;
          },
          setVerticalAlignment: function(val) {
            ops.push({ shelf: "format", range: a1, valign: String(val || "") });
            return proxy;
          },
          setWrap: function(w) {
            ops.push({ shelf: "format", range: a1, wrap: !!w });
            return proxy;
          },
          setNumberFormat: function(nf) {
            ops.push({ shelf: "format", range: a1, number_format: String(nf || "") });
            return proxy;
          }
        };
        var proxy = typeof Proxy === "function" ? new Proxy(rawObj, {
          get: function(target, prop) {
            if (prop in target) return target[prop];
            if (typeof prop === "symbol" || prop === "then") return undefined;
            throw UNSUPPORTED;
          }
        }) : rawObj;
        return proxy;
      };
      var selParts = String((els.chkSync && els.chkSync.checked && state.selection) ? state.selection : "A1")
        .split(/[,、]/).map(function(s) { return s.trim(); }).filter(Boolean);
      if (!selParts.length) selParts = ["A1"];
      var activeRanges = selParts.map(function(part) { return makeRange(parseRangeSpec(part)); });
      var makeRangeList = function(ranges) {
        var rlRaw = {
          getRanges: function() { return ranges.slice(); },
          setFontColor: function(c) { ranges.forEach(function(r) { r.setFontColor(c); }); return rlProxy; },
          setBackground: function(c) { ranges.forEach(function(r) { r.setBackground(c); }); return rlProxy; },
          setFontWeight: function(w) { ranges.forEach(function(r) { r.setFontWeight(w); }); return rlProxy; },
          setFontStyle: function(s) { ranges.forEach(function(r) { r.setFontStyle(s); }); return rlProxy; },
          setFontSize: function(n) { ranges.forEach(function(r) { r.setFontSize(n); }); return rlProxy; },
          setHorizontalAlignment: function(a) { ranges.forEach(function(r) { r.setHorizontalAlignment(a); }); return rlProxy; },
          setNumberFormat: function(f) { ranges.forEach(function(r) { r.setNumberFormat(f); }); return rlProxy; }
        };
        var rlProxy = typeof Proxy === "function" ? new Proxy(rlRaw, {
          get: function(target, prop) {
            if (prop in target) return target[prop];
            if (typeof prop === "symbol" || prop === "then") return undefined;
            throw UNSUPPORTED;
          }
        }) : rlRaw;
        return rlProxy;
      };
      var computeLastPos = function() {
        var lr = 0, lc = 0;
        if (snap.vals) {
          Object.keys(snap.vals).forEach(function(a1k) {
            var m = /^([A-Z]+)(\d+)$/.exec(a1k);
            if (!m) return;
            var rN = parseInt(m[2], 10);
            var cN = colToNum0(m[1]) + 1;
            if (rN > lr) lr = rN;
            if (cN > lc) lc = cN;
          });
        }
        if (state.table && state.table.last_col) {
          var tc = colToNum0(state.table.last_col) + 1;
          if (tc > lc) lc = tc;
        }
        if (lr >= maxRows || lc >= maxCols) throw UNSUPPORTED;
        return { lastRow: lr, lastCol: lc };
      };
      var sheetRaw = {
        getName: function() { return sheetName; },
        getActiveRange: function() { return activeRanges[0]; },
        getActiveRangeList: function() { return makeRangeList(activeRanges); },
        getRange: function(a, b, c, d) { return makeRange(parseRangeSpec(a, b, c, d)); },
        getLastRow: function() { return computeLastPos().lastRow; },
        getLastColumn: function() { return computeLastPos().lastCol; }
      };
      var sheetProxy = typeof Proxy === "function" ? new Proxy(sheetRaw, {
        get: function(target, prop) {
          if (prop in target) return target[prop];
          if (typeof prop === "symbol" || prop === "then") return undefined;
          throw UNSUPPORTED;
        }
      }) : sheetRaw;
      var ssRaw = {
        getName: function() { return (state.target && state.target.name) || ""; },
        getId: function() { return (state.target && state.target.id) || ""; },
        getActiveSheet: function() { return sheetProxy; },
        getActiveRange: function() { return activeRanges[0]; },
        getActiveRangeList: function() { return makeRangeList(activeRanges); },
        getRange: function(a1) { return makeRange(parseRangeSpec(a1)); },
        getSheetByName: function(n) { if (n === sheetName) return sheetProxy; throw UNSUPPORTED; },
        toast: function() {}
      };
      var ssProxy = typeof Proxy === "function" ? new Proxy(ssRaw, {
        get: function(target, prop) {
          if (prop in target) return target[prop];
          if (typeof prop === "symbol" || prop === "then") return undefined;
          throw UNSUPPORTED;
        }
      }) : ssRaw;
      var ssAppRaw = {
        getActive: function() { return ssProxy; },
        getActiveSpreadsheet: function() { return ssProxy; },
        getActiveSheet: function() { return sheetProxy; },
        getActiveRange: function() { return activeRanges[0]; },
        getActiveRangeList: function() { return makeRangeList(activeRanges); },
        flush: function() {}
      };
      var ssAppProxy = typeof Proxy === "function" ? new Proxy(ssAppRaw, {
        get: function(target, prop) {
          if (prop in target) return target[prop];
          if (typeof prop === "symbol" || prop === "then") return undefined;
          throw UNSUPPORTED;
        }
      }) : ssAppRaw;
      var shelfFn = function(opsOrName, optArgs) {
        if (Array.isArray(opsOrName)) {
          opsOrName.forEach(function(o) { ops.push(o); });
        } else if (typeof opsOrName === "string") {
          ops.push(Object.assign({ shelf: opsOrName }, optArgs || {}));
        } else if (opsOrName && typeof opsOrName === "object") {
          ops.push(opsOrName);
        } else {
          throw UNSUPPORTED;
        }
      };
      var mod = new Function("SpreadsheetApp", "shelf", code + "\nreturn {" + JSON.stringify(item.name) + ": " + item.name + "};")(ssAppProxy, shelfFn);
      if (!mod || typeof mod[item.name] !== "function") return null;
      mod[item.name]();
      if (!ops.length) return null;
      // 実際に Sheets API batchUpdate を組めるか事前検証（組めなければ GAS へフォールバック）
      if (!buildDirectBatchUpdate(ops, sheetName)) return null;
      return ops;
    } catch (e) {
      return null;
    }
  }

  function quickRunItem(it) {
    if (!it) return;
    if (it.src === "shelf") {
      if (it.needArgs) {
        els.askInput.value = it.example || it.label;
        els.askInput.focus();
        if (els.askInput.select) els.askInput.select();
        updatePreview();
        if (els.quickNote) {
          els.quickNote.textContent = it.example
            ? ("例「" + it.example + "」を入力しました。書き換えて Enter で実行できます")
            : ("棚「" + it.label + "」は言葉を足してから実行してください（例: どの列・何色）");
        }
        return;
      }
      if (els.quickNote) els.quickNote.textContent = "棚「" + it.label + "」を実行します…";
      onRunOps([{ shelf: it.name }], it.label, { switchToChat: false });
      return;
    }
    if (Array.isArray(it.steps) && it.steps.length) {
      quickRecordUsage(it);
      quickRunSteps(it);
      return;
    }
    if (Array.isArray(it.directOps) && it.directOps.length) {
      quickRecordUsage(it);
      if (state.busy) {
        appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
        return;
      }
      var runDirectMy = function() {
        if (els.quickNote) els.quickNote.textContent = "⚡ まとめ棚「" + it.name + "」を実行します…";
        onRunOps(it.directOps, "マイマクロ " + it.name, { switchToChat: false });
      };
      if (els.chkSync && els.chkSync.checked) {
        requestLiveSelection(function(live) {
          applyLiveSelectionResult(live);
          runDirectMy();
        });
      } else {
        runDirectMy();
      }
      return;
    }
    var invokeQuickRun = function(item) {
      quickRecordUsage(item);
      var sheetNameNow = state.curSheet || (state.target && state.target.sheet) || "";
      var runViaGasQuick = function() {
        state.directUndoStack = [];
        runServerAction({
          fnName: "comboQuickRun",
          payload: {
            src: item.src,
            name: item.name,
            myId: state.quick.myId,
            myStamp: state.quick.myStamp || "",
            backup: !!els.chkBackup.checked,
            targetId: state.target.id || "",
            sheet: state.curSheet || "",
            selection: els.chkSync.checked ? (state.selection || "") : ""
          },
          label: "マイマクロ " + item.name,
          statusText: item.name + " を実行中…",
          switchToChat: false,
          onSuccess: function(res, wallMs) {
            if (res && res.myStamp) {
              state.quick.myStamp = res.myStamp;
              quickRememberLocal();
            }
            var sec = typeof wallMs === "number" ? ("（" + (Math.max(0, wallMs / 1000)).toFixed(2) + "s）") : "";
            if (els.quickNote) els.quickNote.textContent = (res.text || "完了") + sec;
          },
          onError: function(err) {
            if (els.quickNote) els.quickNote.textContent = "⚠ " + formatError(err);
          }
        });
      };
      var compiledOps = tryCompileMyMacroDirect(item, sheetNameNow);
      if (compiledOps && compiledOps.length) {
        if (tryDirectSheetsApi(compiledOps, "マイマクロ " + item.name, false, runViaGasQuick, {
          switchToChat: false,
          onDirectDone: function(wallMs) {
            var sec = typeof wallMs === "number" ? ("（" + (Math.max(0, wallMs / 1000)).toFixed(2) + "s・直結）") : "";
            if (els.quickNote) els.quickNote.textContent = "⚡ " + item.name + " を実行しました" + sec;
          }
        })) {
          return;
        }
      }
      runViaGasQuick();
    };
    if (els.chkSync && els.chkSync.checked) {
      requestLiveSelection(function(live) {
        applyLiveSelectionResult(live);
        invokeQuickRun(it);
      });
    } else {
      invokeQuickRun(it);
    }
  }

  function quickRunFromInput() {
    var items = state.quick.items || [];
    var picked = state.quick.sel >= 0 && !!items[state.quick.sel];
    var it = picked ? items[state.quick.sel] : null;
    var txt = (els.askInput.value || "").trim();
    if (!picked && txt && items.length && items[0].src !== "shelf" && quickScore(items[0], txt) >= 60) it = items[0];
    if (!it) return false;
    if (!picked && it.src === "shelf" && txt) return false;
    if (it.src === "shelf" && it.needArgs) {
      quickRunItem(it);
      return true;
    }
    pushHistory(txt || it.label);
    els.askInput.value = "";
    updatePreview();
    state.quick.sel = -1;
    renderQuickList();
    quickRunItem(it);
    return true;
  }

  function resetQuickDeleteBtn() {
    quickEditState.delArmed = false;
    if (els.btnQuickEditDelete) {
      els.btnQuickEditDelete.textContent = "削除";
      els.btnQuickEditDelete.style.background = "";
      els.btnQuickEditDelete.style.color = "#dc2626";
    }
  }

  function syncQuickSaveBtnState() {
    if (!els.btnQuickEditSave) return;
    var hasCode = !!(els.quickEditCode && String(els.quickEditCode.value || "").trim());
    els.btnQuickEditSave.disabled = !hasCode;
  }

  function setQuickModalTab(tab) {
    var t = (tab === "chat") ? "chat" : "code";
    quickEditState.activeTab = t;
    if (els.tabQuickModalChat && els.tabQuickModalChat.classList) {
      els.tabQuickModalChat.classList.toggle("active", t === "chat");
    }
    if (els.tabQuickModalCode && els.tabQuickModalCode.classList) {
      els.tabQuickModalCode.classList.toggle("active", t === "code");
    }
    if (els.quickChatPane && els.quickChatPane.style) {
      els.quickChatPane.style.display = (t === "chat") ? "flex" : "none";
    }
    if (els.quickEditCode && els.quickEditCode.style) {
      els.quickEditCode.style.display = (t === "code") ? "block" : "none";
    }
    if (els.quickCodeBadge && els.quickCodeBadge.style) {
      els.quickCodeBadge.style.display = quickEditState.codeUpdated ? "inline-block" : "none";
    }
    if (t === "chat" && els.quickChatLog) {
      els.quickChatLog.scrollTop = 999999;
    }
  }

  function dropPendingQuickChat() {
    if (!Array.isArray(quickEditState.chatHistory)) {
      quickEditState.chatHistory = [];
      return;
    }
    quickEditState.chatHistory = quickEditState.chatHistory.filter(function(h) {
      return h && h.role !== "pending";
    });
  }

  function renderQuickChat() {
    var logEl = els.quickChatLog;
    var chipsEl = els.quickChatChips;
    var hist = Array.isArray(quickEditState.chatHistory) ? quickEditState.chatHistory : [];
    if (logEl) {
      logEl.innerHTML = "";
      if (!hist.length) {
        var emptyDiv = document.createElement("div");
        emptyDiv.className = "quick-chat-empty";
        emptyDiv.textContent = (quickEditState.mode === "edit")
          ? "このコードについて AI に質問・相談できます。\n下の欄に「どんな改善ができる？」「ここを変えて」などと入力するか、下の候補を押してみてください。"
          : "作りたいマクロを AI と相談しながら決められます。\n下の欄にやりたいことを入力するか、下の候補を押してみてください。";
        logEl.appendChild(emptyDiv);
      } else {
        for (var i = 0; i < hist.length; i++) {
          var m = hist[i];
          if (!m || !m.text) continue;
          var card = document.createElement("div");
          card.className = "quick-chat-msg is-" + (m.role || "ai");
          var bodySpan = document.createElement("div");
          bodySpan.textContent = m.text;
          card.appendChild(bodySpan);
          if (m.role === "code") {
            var goBtn = document.createElement("button");
            goBtn.type = "button";
            goBtn.className = "btn";
            goBtn.style.marginTop = "4px";
            goBtn.style.padding = "2px 8px";
            goBtn.textContent = "📄 コードを見る";
            goBtn.addEventListener("click", function() { setQuickModalTab("code"); });
            card.appendChild(goBtn);
          }
          if (m.retryApi) {
            (function(retryInfo) {
              var rBtn = document.createElement("button");
              rBtn.type = "button";
              rBtn.className = "retry-api-btn";
              rBtn.textContent = "🔑 API 鍵で再試行";
              rBtn.addEventListener("click", function() {
                rBtn.disabled = true;
                retryWithApiKeyInQuickModal(retryInfo);
              });
              card.appendChild(rBtn);
            })(m.retryApi);
          }
          logEl.appendChild(card);
        }
      }
      logEl.scrollTop = 999999;
    }
    if (chipsEl) {
      chipsEl.innerHTML = "";
      var recCands = Array.isArray(quickEditState.recordedCandidates) ? quickEditState.recordedCandidates : [];
      var showChips = recCands.length > 0 || !hist.length;
      if (chipsEl.style) chipsEl.style.display = showChips ? "flex" : "none";
      if (recCands.length > 0) {
        for (var ri = 0; ri < recCands.length; ri++) {
          (function(recItem) {
            var rb = document.createElement("button");
            rb.type = "button";
            rb.className = "quick-chat-chip";
            rb.textContent = "🎬 " + (recItem.name || "無名") + (recItem.file ? (" (" + recItem.file + ")") : "");
            rb.addEventListener("click", function() {
              quickEditState.recordedCandidates = [];
              startPolishRecordedMacro(recItem);
            });
            chipsEl.appendChild(rb);
          })(recCands[ri]);
        }
      } else if (showChips) {
        var presets = (quickEditState.mode === "edit")
          ? ["どんな改善ができる？", "このコードの説明をして", "完了メッセージを追加して"]
          : ["どんなマクロが作れる？", "選択範囲の色を変える", "見出し行を整える"];
        for (var ci = 0; ci < presets.length; ci++) {
          (function(chipTxt) {
            var cb = document.createElement("button");
            cb.type = "button";
            cb.className = "quick-chat-chip";
            cb.textContent = chipTxt;
            cb.addEventListener("click", function() {
              if (els.quickAiInput) els.quickAiInput.value = chipTxt;
              submitQuickAi();
            });
            chipsEl.appendChild(cb);
          })(presets[ci]);
        }
      }
    }
  }

  function closeQuickEditModal() {
    quickEditReqSeq++;
    if (els.quickEditModal) els.quickEditModal.style.display = "none";
    if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
    if (els.quickEditCode && els.quickEditCode.style) els.quickEditCode.style.borderColor = "#94a3b8";
    if (els.quickCodeBadge && els.quickCodeBadge.style) els.quickCodeBadge.style.display = "none";
    if (els.quickDryRunBar) { els.quickDryRunBar.style.display = "none"; els.quickDryRunBar.innerHTML = ""; }
    if (els.btnQuickDryRun) els.btnQuickDryRun.disabled = false;
    quickEditState = { mode: "edit", name: "", myUrl: "", delArmed: false, origCode: "", pendingReqId: "", activeTab: "code", chatHistory: [], codeUpdated: false };
    resetQuickDeleteBtn();
  }

  function buildMyMacroAiPrompt() {
    var shName = state.curSheet || (state.target && state.target.sheet) || "";
    var selStr = els.chkSync && els.chkSync.checked ? (state.selection || "") : "";
    var cols = (state.table && Array.isArray(state.table.columns))
      ? state.table.columns.map(function(c) { return (c.col || "") + ":" + (c.name || ""); }).filter(Boolean).join(" / ")
      : "";
    var ctx = [];
    if (state.target && state.target.name) ctx.push("ブック: " + state.target.name);
    if (shName) ctx.push("現在のシート: " + shName);
    if (selStr) ctx.push("選択範囲: " + selStr);
    if (cols) ctx.push("列見出し: " + cols);
    return [
      "Google スプレッドシート（GASコンボ／GASクイック共通 マイマクロ）用の Google Apps Script の関数を 1 つ作ってください。",
      "",
      "【ルール】",
      "・関数名は分かりやすい日本語（引数なし）にする（例: function 選んだ所を黄色に() { ... }）",
      "・関数のすぐ上の行に「// 説明」を 1 行書く（必要なら「// 棚: 言い方1, 言い方2」も追加）",
      "・GASコンボのブラウザ連動側でも SpreadsheetApp.getActive() / getActiveSheet() / getActiveRange() / getActiveRangeList() がそのまま動きます",
      "・コードのみ出力する",
      ctx.length ? ("\n【今のシート情報】\n・" + ctx.join("\n・")) : "",
      "",
      "【やりたいこと】",
      "（ここにやりたい作業を書いてください）"
    ].filter(function(s) { return s !== ""; }).join("\n");
  }

  var QUICK_PREV_LS_KEY = "gascombo_quick_prev_v1";

  function quickLoadPrevMap() {
    try {
      var raw = window.localStorage.getItem(QUICK_PREV_LS_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return (parsed && typeof parsed === "object" && !Array.isArray(parsed)) ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function quickSavePrevCode(name, code) {
    if (!name || !code) return;
    try {
      var m = quickLoadPrevMap();
      m[name] = { code: String(code), at: Date.now() };
      var ks = Object.keys(m);
      if (ks.length > 30) {
        ks.sort(function(a, b) { return ((m[b] && m[b].at) || 0) - ((m[a] && m[a].at) || 0); });
        for (var i = 30; i < ks.length; i++) delete m[ks[i]];
      }
      window.localStorage.setItem(QUICK_PREV_LS_KEY, JSON.stringify(m));
    } catch (e) {}
  }

  function quickGetPrevCode(name) {
    if (!name) return "";
    var m = quickLoadPrevMap();
    return (m[name] && typeof m[name].code === "string") ? m[name].code : "";
  }

  function openQuickAddModal(aiFirst) {
    quickEditReqSeq++;
    quickEditState = {
      mode: "add", name: "", myUrl: state.quick.myUrl || "", delArmed: false,
      origCode: "", pendingReqId: "", activeTab: aiFirst ? "chat" : "code",
      chatHistory: [], codeUpdated: false
    };
    resetQuickDeleteBtn();
    if (els.quickEditTitle) els.quickEditTitle.textContent = aiFirst ? "✨ 新規マイマクロ作成（AI）" : "手動でマイマクロを追加";
    if (els.quickModalTabs && els.quickModalTabs.style) els.quickModalTabs.style.display = aiFirst ? "grid" : "none";
    if (els.quickAiBox) els.quickAiBox.style.display = aiFirst ? "flex" : "none";
    if (els.quickAiInput) {
      els.quickAiInput.value = "";
      els.quickAiInput.placeholder = "例: 選択中の行を薄緑色にして金額列を太字にする / どんなマクロが作れる？";
    }
    if (els.btnQuickAiSubmit) {
      els.btnQuickAiSubmit.disabled = false;
      els.btnQuickAiSubmit.textContent = "✨ 送信";
    }
    if (els.btnQuickRevert) els.btnQuickRevert.style.display = "none";
    if (els.btnQuickImportRec) els.btnQuickImportRec.style.display = aiFirst ? "" : "none";
    if (els.quickEditPromptRow) els.quickEditPromptRow.style.display = aiFirst ? "none" : "";
    if (els.btnQuickEditDelete) els.btnQuickEditDelete.style.display = "none";
    if (els.quickEditCode) {
      els.quickEditCode.disabled = false;
      els.quickEditCode.value = "";
      if (els.quickEditCode.style) els.quickEditCode.style.borderColor = "#94a3b8";
      els.quickEditCode.placeholder = aiFirst
        ? "「💬 AI会話」で要望を伝えると、ここに生成されたコードが表示されます。\n確認したら下の「決定して保存」を押してください。"
        : "// 説明\nfunction 自分のマクロ名() {\n  // ここに処理を書く\n}";
    }
    if (els.btnQuickEditSave) els.btnQuickEditSave.textContent = "決定して保存";
    renderQuickChat();
    setQuickModalTab(aiFirst ? "chat" : "code");
    syncQuickSaveBtnState();
    if (els.quickEditStatus) {
      els.quickEditStatus.textContent = aiFirst
        ? "AI に相談・依頼してコードを作れます（完成後に「決定して保存」）"
        : "コードを貼り付けて「決定して保存」を押してください";
    }
    if (els.quickEditModal) els.quickEditModal.style.display = "flex";
    if (aiFirst && els.quickAiInput) els.quickAiInput.focus();
    else if (els.quickEditCode) els.quickEditCode.focus();
  }

  function ensureQuickEditModalOpenFromAsync(res) {
    var modalClosed = !els.quickEditModal || els.quickEditModal.style.display === "none";
    if (!modalClosed) return;
    var isEditMode = res.mode === "edit" && !!(res.targetName || res.name);
    var restoreName = isEditMode ? (res.targetName || res.name || "") : "";
    var prevChat = Array.isArray(quickEditState.chatHistory) ? quickEditState.chatHistory : [];
    quickEditState = {
      mode: isEditMode ? "edit" : "add",
      name: restoreName,
      myUrl: state.quick.myUrl || "",
      delArmed: false,
      origCode: isEditMode ? String(res.prevCode || "") : "",
      pendingReqId: "",
      activeTab: "chat",
      chatHistory: prevChat,
      codeUpdated: false
    };
    resetQuickDeleteBtn();
    if (els.quickEditTitle) {
      els.quickEditTitle.textContent = isEditMode ? ("編集: " + restoreName) : "✨ 新規マイマクロ作成（AI）";
    }
    if (els.quickModalTabs && els.quickModalTabs.style) els.quickModalTabs.style.display = "grid";
    if (els.quickAiBox) els.quickAiBox.style.display = "flex";
    if (els.quickAiInput) {
      els.quickAiInput.placeholder = isEditMode
        ? "例: どんな編集ができる？ / 背景色も変えて"
        : "例: 選択中の行を薄緑色にして金額列を太字にする / どんなマクロが作れる？";
    }
    if (els.btnQuickRevert) {
      els.btnQuickRevert.style.display = (isEditMode && quickGetPrevCode(restoreName)) ? "" : "none";
    }
    if (els.btnQuickImportRec) els.btnQuickImportRec.style.display = isEditMode ? "none" : "";
    if (els.quickEditPromptRow) els.quickEditPromptRow.style.display = "none";
    if (els.btnQuickEditDelete) els.btnQuickEditDelete.style.display = isEditMode ? "" : "none";
    if (els.btnQuickEditSave) els.btnQuickEditSave.textContent = "決定して保存";
    if (els.quickEditModal) els.quickEditModal.style.display = "flex";
  }

  function applyQuickAiReplyResult(res) {
    if (!res) return;
    ensureQuickEditModalOpenFromAsync(res);
    quickEditState.pendingReqId = "";
    dropPendingQuickChat();
    var msgTxt = String(res.message || res.text || "").trim();
    if (msgTxt) quickEditState.chatHistory.push({ role: "ai", text: msgTxt });
    if (els.btnQuickAiSubmit) {
      els.btnQuickAiSubmit.disabled = false;
      els.btnQuickAiSubmit.textContent = "✨ 送信";
    }
    if (els.quickEditCode) els.quickEditCode.disabled = false;
    syncQuickSaveBtnState();
    renderQuickChat();
    setQuickModalTab("chat");
    if (els.quickEditStatus) {
      var directNote = (res && res.direct && typeof res.aiMs === "number")
        ? ("（直結 " + (res.aiMs / 1000).toFixed(1) + "秒）")
        : "";
      els.quickEditStatus.textContent = "💬 AI から返答が届きました" + directNote + "。続けて要望や「それでお願い」と入力できます";
    }
    if (els.quickAiInput) els.quickAiInput.focus();
  }

  function applyQuickAiPreviewResult(res) {
    if (!res) return;
    ensureQuickEditModalOpenFromAsync(res);
    quickEditState.pendingReqId = "";
    dropPendingQuickChat();
    var notePart = res.note ? ("（" + res.note + "）") : "";
    quickEditState.chatHistory.push({
      role: "code",
      text: "✨ コードを作成・更新しました" + notePart + "\n内容を確認して、よければ下の「決定して保存」を押してください。"
    });
    quickEditState.codeUpdated = true;
    if (els.quickEditCode) {
      els.quickEditCode.disabled = false;
      els.quickEditCode.value = String(res.code || "");
      els.quickEditCode.scrollTop = 0;
      if (els.quickEditCode.style) els.quickEditCode.style.borderColor = "#2563eb";
    }
    if (els.quickAiInput) els.quickAiInput.value = "";
    if (els.btnQuickAiSubmit) {
      els.btnQuickAiSubmit.disabled = false;
      els.btnQuickAiSubmit.textContent = "✨ 送信";
    }
    syncQuickSaveBtnState();
    renderQuickChat();
    setQuickModalTab("code");
    if (els.quickEditStatus) {
      var directNote = (res && res.direct && typeof res.aiMs === "number")
        ? ("（直結 " + (res.aiMs / 1000).toFixed(1) + "秒）")
        : "";
      els.quickEditStatus.textContent = "✨ コードができました！" + directNote + notePart + "確認して「決定して保存」（さらに会話で修正も可）";
    }
  }

  function submitQuickAi() {
    var prompt = els.quickAiInput ? String(els.quickAiInput.value || "").trim() : "";
    if (!prompt) {
      if (els.quickEditStatus) els.quickEditStatus.textContent = "AI に頼む内容や質問を日本語で入力してください";
      if (els.quickAiInput) els.quickAiInput.focus();
      return;
    }
    if (state.busy) return;
    var aiMode = (quickEditState.mode === "edit" && quickEditState.name) ? "edit" : "add";
    var targetNm = aiMode === "edit" ? quickEditState.name : "";
    var currentCode = els.quickEditCode ? String(els.quickEditCode.value || "").trim() : "";
    var origCodeSnapshot = quickEditState.origCode || currentCode;
    var codeToSend = currentCode || (aiMode === "edit" ? (quickEditState.origCode || "") : "");
    var historyPayload = (Array.isArray(quickEditState.chatHistory) ? quickEditState.chatHistory : [])
      .filter(function(h) { return h && (h.role === "user" || h.role === "ai" || h.role === "code") && h.text; })
      .slice(-10)
      .map(function(h) { return { role: h.role === "user" ? "user" : "ai", text: String(h.text) }; });
    if (!Array.isArray(quickEditState.chatHistory)) quickEditState.chatHistory = [];
    quickEditState.chatHistory.push({ role: "user", text: prompt });
    quickEditState.chatHistory.push({ role: "pending", text: "✨ AI が考えています…" });
    if (els.quickAiInput) els.quickAiInput.value = "";
    renderQuickChat();
    setQuickModalTab("chat");
    if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = true;
    if (els.btnQuickEditSave) els.btnQuickEditSave.disabled = true;
    if (els.quickEditStatus) {
      els.quickEditStatus.textContent = "✨ AI に送信しています…";
    }

    var runGasQuickAiSave = function(forceAiModeOpt) {
      var reqPayload = {
        mode: aiMode,
        previewOnly: true,
        name: targetNm,
        code: codeToSend,
        prompt: prompt,
        history: historyPayload,
        targetId: state.target.id || "",
        sheet: state.curSheet || "",
        selection: (els.chkSync && els.chkSync.checked) ? (state.selection || "") : "",
        table: state.table,
        sheets: state.sheets || [],
        myId: state.quick.myId || "",
        myStamp: state.quick.myStamp || ""
      };
      if (forceAiModeOpt) reqPayload.forceAiMode = forceAiModeOpt;
      runServerAction({
        fnName: "comboQuickAiSave",
        payload: reqPayload,
        label: aiMode === "edit" ? ("✨ AI相談/修正: " + targetNm) : "✨ AI作成/相談",
        statusText: aiMode === "edit" ? ("AI が「" + targetNm + "」を検討中…") : "AI が考えています…",
        switchToChat: false,
        onSuccess: function(res) {
          if (res && res.action === "reply") {
            applyQuickAiReplyResult(res);
            return;
          }
          if (res && res.previewOnly && res.code) {
            applyQuickAiPreviewResult(res);
            return;
          }
          dropPendingQuickChat();
          renderQuickChat();
          if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
          syncQuickSaveBtnState();
          var savedName = (res && (res.newName || res.name)) || targetNm;
          var prev = (res && res.prevCode) || origCodeSnapshot;
          if (aiMode === "edit" && prev && savedName) quickSavePrevCode(savedName, prev);
          if (res && res.myId) state.quick.myId = res.myId;
          if (res && res.myUrl) state.quick.myUrl = res.myUrl;
          if (res && res.myStamp) state.quick.myStamp = res.myStamp;
          closeQuickEditModal();
          quickClearCodeCache();
          quickRememberLocal();
          updateSettingsMyMacroUI();
          if (els.quickNote) els.quickNote.textContent = (res && res.text) || ("✨ マイマクロ「" + savedName + "」を保存しました");
          loadQuickList(false);
        },
        onError: function(err) {
          dropPendingQuickChat();
          quickEditState.chatHistory.push({ role: "err", text: "AI エラー: " + formatError(err) });
          renderQuickChat();
          if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
          syncQuickSaveBtnState();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "AI エラー: " + formatError(err);
        }
      });
    };

    var makeRetryApiInfo = function() {
      if (!(state.config && (state.config.hasGeminiKey || state.config.hasClaudeKey || state.config.hasApiKey))) return null;
      var fm = state.config.hasGeminiKey ? "api_gemini" : (state.config.hasClaudeKey ? "api_claude" : "");
      if (!fm) return null;
      return { forceAiMode: fm, prompt: prompt, aiMode: aiMode, targetNm: targetNm, codeToSend: codeToSend, historyPayload: historyPayload, origCodeSnapshot: origCodeSnapshot };
    };

    var dispatchAiSave = function() {
      if (canUseDirectLocalAi()) {
        var existingNames = (state.quick && Array.isArray(state.quick.my))
          ? state.quick.my.map(function(f) { return f && f.name; }).filter(Boolean)
          : [];
        setBusy(true, aiMode === "edit" ? ("✨ AI が「" + targetNm + "」を検討中…") : "✨ AI に問い合わせ中…");
        if (els.quickEditStatus) els.quickEditStatus.textContent = "✨ AI に問い合わせています…";
        requestDirectAi({
          kind: "mymacro",
          stream: true,
          mode: aiMode,
          previewOnly: true,
          targetName: targetNm,
          existingCode: codeToSend,
          existingNames: existingNames,
          ask: prompt,
          history: historyPayload,
          ssId: state.target.id || "",
          ssName: state.target.name || "",
          sheet: state.curSheet || "",
          selection: (els.chkSync && els.chkSync.checked) ? (state.selection || "") : "",
          table: state.table,
          sheets: state.sheets || [],
          myId: state.quick.myId || "",
          aiModel: getCurrentAiModel()
        }, function(r) {
          setBusy(false);
          if (r && r.inExtension && !r.reachable) {
            var connErr = "PC 側の AI 窓口（127.0.0.1:18766）につながりません。PC で受け手が動いているか確かめてください";
            dropPendingQuickChat();
            quickEditState.chatHistory.push({ role: "err", text: "AI エラー: " + connErr, retryApi: makeRetryApiInfo() });
            renderQuickChat();
            if (els.btnQuickAiSubmit) {
              els.btnQuickAiSubmit.disabled = false;
              els.btnQuickAiSubmit.textContent = "✨ 送信";
            }
            syncQuickSaveBtnState();
            if (els.quickEditStatus) els.quickEditStatus.textContent = "AI エラー: " + connErr;
            return;
          }
          if (!r || !r.reachable) {
            runGasQuickAiSave();
            return;
          }
          var d = r.data || {};
          if (d.ok && d.action === "reply") {
            applyQuickAiReplyResult(d);
            return;
          }
          if (d.ok && d.code) {
            applyQuickAiPreviewResult(d);
            return;
          }
          var errTxt = String(d.error || r.error || "AI 処理に失敗しました");
          dropPendingQuickChat();
          quickEditState.chatHistory.push({ role: "err", text: "AI エラー: " + errTxt, retryApi: makeRetryApiInfo() });
          renderQuickChat();
          if (els.btnQuickAiSubmit) {
            els.btnQuickAiSubmit.disabled = false;
            els.btnQuickAiSubmit.textContent = "✨ 送信";
          }
          syncQuickSaveBtnState();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "AI エラー: " + errTxt;
        }, function(ev) {
          if (!ev) return;
          var txtProg = ev.message || (ev.text ? String(ev.text).slice(0, 140) : "");
          if (!txtProg) return;
          for (var pi = quickEditState.chatHistory.length - 1; pi >= 0; pi--) {
            if (quickEditState.chatHistory[pi] && quickEditState.chatHistory[pi].role === "pending") {
              quickEditState.chatHistory[pi].text = "✨ " + txtProg;
              break;
            }
          }
          renderQuickChat();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "✨ " + txtProg;
        });
        return;
      }
      runGasQuickAiSave();
    };

    if (els.chkSync && els.chkSync.checked) {
      requestLiveSelection(function(live) {
        applyLiveSelectionResult(live);
        dispatchAiSave();
      });
    } else {
      dispatchAiSave();
    }
  }

  function retryWithApiKeyInQuickModal(retryInfo) {
    if (!retryInfo || !retryInfo.forceAiMode || state.busy) return;
    quickEditState.chatHistory.push({ role: "pending", text: "🔑 API 鍵で再試行しています…" });
    renderQuickChat();
    if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = true;
    runServerAction({
      fnName: "comboQuickAiSave",
      payload: {
        mode: retryInfo.aiMode || "add",
        previewOnly: true,
        forceAiMode: retryInfo.forceAiMode,
        name: retryInfo.targetNm || "",
        code: retryInfo.codeToSend || "",
        prompt: retryInfo.prompt || "",
        history: retryInfo.historyPayload || [],
        targetId: state.target.id || "",
        sheet: state.curSheet || "",
        selection: (els.chkSync && els.chkSync.checked) ? (state.selection || "") : "",
        table: state.table,
        sheets: state.sheets || [],
        myId: state.quick.myId || "",
        myStamp: state.quick.myStamp || ""
      },
      label: "🔑 API鍵フォールバック",
      statusText: "API 鍵で再実行中…",
      switchToChat: false,
      onSuccess: function(res) {
        if (res && res.action === "reply") { applyQuickAiReplyResult(res); return; }
        if (res && res.previewOnly && res.code) { applyQuickAiPreviewResult(res); return; }
        dropPendingQuickChat();
        renderQuickChat();
        if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
        syncQuickSaveBtnState();
      },
      onError: function(err) {
        dropPendingQuickChat();
        quickEditState.chatHistory.push({ role: "err", text: "API 鍵フォールバック失敗: " + formatError(err) });
        renderQuickChat();
        if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
        syncQuickSaveBtnState();
      }
    });
  }

  var QUICK_MY_TEMPLATES = [
    {
      name: "名簿クレンジング",
      desc: "余分な空白・重複を除き、表全体を整えます",
      code: "// 余分な空白・重複を除き、表全体を整えます\n// 棚: 名簿クレンジング, 名簿整理\nfunction 名簿クレンジング() {\n  return shelf([\n    { shelf: \"clean\" },\n    { shelf: \"dedupe\" },\n    { shelf: \"seiri\" }\n  ]);\n}"
    },
    {
      name: "請求書フォーマットチェック",
      desc: "請求書の整形・マイナス赤字・合計行・見出し固定をまとめて適用します",
      code: "// 請求書の整形・マイナス赤字・合計行・見出し固定をまとめて適用します\n// 棚: 請求書チェック, 請求書整形\nfunction 請求書フォーマットチェック() {\n  return shelf([\n    { shelf: \"seiri\" },\n    { shelf: \"format.negred\" },\n    { shelf: \"total\" },\n    { shelf: \"freeze\", rows: 1 }\n  ]);\n}"
    },
    {
      name: "部署別集計と区切り線",
      desc: "部署で並べ替え、部署が変わる行に区切り線を引き、合計行を出します",
      code: "// 部署で並べ替え、部署が変わる行に区切り線を引き、合計行を出します\n// 棚: 部署別集計, 部署区切り線\nfunction 部署別集計と区切り線() {\n  return shelf([\n    { shelf: \"sort\", by: \"部署\", order: \"asc\" },\n    { shelf: \"borders.group\", col: \"部署\" },\n    { shelf: \"total\" }\n  ]);\n}"
    }
  ];

  function exportMyMacrosData(fmt) {
    var map = (state.quick && state.quick.codeCache && state.quick.codeCache.map) || {};
    var names = Object.keys(map).filter(function(k) { return typeof map[k] === "string" && map[k].trim(); });
    if (!names.length) return { ok: false, error: "書き出せるマイマクロのコードがまだ読み込まれていません" };
    if (fmt === "gs") {
      var gs = names.map(function(n) { return String(map[n]).trim(); }).join("\n\n");
      return { ok: true, count: names.length, filename: "gascombo_mymacros.gs", mime: "text/plain;charset=utf-8", content: gs };
    }
    var payload = {
      version: 1,
      exportedAt: new Date().toISOString(),
      macros: names.map(function(n) { return { name: n, code: String(map[n]).trim() }; })
    };
    return {
      ok: true,
      count: names.length,
      filename: "gascombo_mymacros.json",
      mime: "application/json;charset=utf-8",
      content: JSON.stringify(payload, null, 2)
    };
  }

  function downloadOrCopyText(filename, mime, content) {
    try {
      if (typeof Blob !== "undefined" && typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
        var blob = new Blob([content], { type: mime || "text/plain;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function() { try { URL.revokeObjectURL(url); } catch (_e) {} }, 1000);
        return Promise.resolve("download");
      }
    } catch (_eDl) {}
    return copyToClipboard(content).then(function() { return "copy"; });
  }

  function setQuickExportImportNote(msg) {
    if (els.quickNote) els.quickNote.textContent = msg;
    if (els.settingsMyStatus) els.settingsMyStatus.textContent = msg;
  }

  function exportMyMacros(fmt) {
    var runExport = function() {
      var out = exportMyMacrosData(fmt);
      if (!out.ok) {
        setQuickExportImportNote("⚠ " + out.error);
        return;
      }
      downloadOrCopyText(out.filename, out.mime, out.content).then(function(how) {
        setQuickExportImportNote((how === "download" ? "⬇ 書き出しました: " : "📋 コピーしました: ") + out.filename + "（" + out.count + " 件）");
      }).catch(function(err) {
        setQuickExportImportNote("⚠ 書き出し失敗: " + formatError(err));
      });
    };
    var map = (state.quick && state.quick.codeCache && state.quick.codeCache.map) || {};
    if (!Object.keys(map).length && hasGasBridge()) {
      callGas("comboQuickList", { targetId: state.target.id || "", force: true, wantCodes: true, clientStamp: "" }, function(res) {
        if (res && res.ok) applyQuickListRes(res);
        runExport();
      }, function() { runExport(); });
      return;
    }
    runExport();
  }

  function parseImportMyMacros(rawText, existingNamesList) {
    var txt = String(rawText || "").trim();
    if (!txt) return { ok: false, error: "取込データが空です" };
    var blocks = [];
    if (txt.charAt(0) === "{" || txt.charAt(0) === "[") {
      try {
        var parsed = JSON.parse(txt);
        var arr = Array.isArray(parsed) ? parsed : (parsed && Array.isArray(parsed.macros) ? parsed.macros : null);
        if (!arr) return { ok: false, error: "JSON は配列または { macros: [...] } 形式にしてください" };
        for (var i = 0; i < arr.length; i++) {
          var item = arr[i];
          if (typeof item === "string" && item.trim()) blocks.push(stripCodeFence(item));
          else if (item && typeof item.code === "string" && item.code.trim()) blocks.push(stripCodeFence(item.code));
        }
      } catch (eJ) {
        return { ok: false, error: "JSON 解析エラー: " + String((eJ && eJ.message) || eJ) };
      }
    } else {
      blocks = [stripCodeFence(txt)];
    }
    if (!blocks.length) return { ok: false, error: "取り込めるコードが見つかりません" };

    var existingSet = {};
    var curList = Array.isArray(existingNamesList) ? existingNamesList : ((state.quick && state.quick.my) || []).map(function(x) { return x && x.name; });
    for (var ei = 0; ei < curList.length; ei++) {
      if (curList[ei]) existingSet[String(curList[ei])] = true;
    }

    var seenInImport = {};
    var validBlocks = [];
    var allNames = [];
    for (var bi = 0; bi < blocks.length; bi++) {
      var code = String(blocks[bi] || "").replace(/\r\n/g, "\n").trim();
      if (!code) continue;
      try {
        new Function(code);
      } catch (eSyn) {
        return { ok: false, error: "構文エラー: " + String((eSyn && eSyn.message) || eSyn) };
      }
      var fnMatches = [];
      var reFn = /(?:^|\n)function\s+([^\s(]+)\s*\(/g;
      var mFn;
      while ((mFn = reFn.exec(code)) !== null) {
        if (!/_$/.test(mFn[1])) fnMatches.push(mFn[1]);
      }
      if (!fnMatches.length) {
        return { ok: false, error: "トップレベル関数（function 名前() { ... }、末尾 _ なし）が見つかりません" };
      }
      for (var fi = 0; fi < fnMatches.length; fi++) {
        var fnNm = fnMatches[fi];
        if (existingSet[fnNm] || seenInImport[fnNm]) {
          return { ok: false, error: "名前が重複しています: 「" + fnNm + "」" };
        }
        seenInImport[fnNm] = true;
        allNames.push(fnNm);
      }
      validBlocks.push(code);
    }
    if (!validBlocks.length) return { ok: false, error: "有効な関数がありません" };
    return { ok: true, blocks: validBlocks, names: allNames };
  }

  function importMyMacrosText(rawText) {
    var check = parseImportMyMacros(rawText);
    if (!check.ok) {
      setQuickExportImportNote("⚠ 取込中止: " + check.error);
      return;
    }
    var idx = 0;
    var added = [];
    var stepNext = function() {
      if (idx >= check.blocks.length) {
        setQuickExportImportNote("⬆ " + added.length + " 件を取り込みました: " + added.join("・"));
        quickClearCodeCache();
        loadQuickList(false);
        return;
      }
      var blockCode = check.blocks[idx++];
      runServerAction({
        fnName: "comboQuickAddFn",
        payload: { code: blockCode },
        label: "⬆ 取込 (" + idx + "/" + check.blocks.length + ")",
        statusText: "マイマクロを取り込み中…",
        switchToChat: false,
        onSuccess: function(res) {
          if (res && res.myId) state.quick.myId = res.myId;
          if (res && res.myUrl) state.quick.myUrl = res.myUrl;
          if (res && res.myStamp) state.quick.myStamp = res.myStamp;
          if (res && Array.isArray(res.names)) added = added.concat(res.names);
          quickRememberLocal();
          stepNext();
        },
        onError: function(err) {
          setQuickExportImportNote("⚠ 取込エラー: " + formatError(err));
        }
      });
    };
    stepNext();
  }

  function toggleQuickTplBar() {
    if (!els.quickTplBar) return;
    var showing = els.quickTplBar.style.display !== "none";
    if (showing) {
      els.quickTplBar.style.display = "none";
      return;
    }
    els.quickTplBar.innerHTML = "";
    QUICK_MY_TEMPLATES.forEach(function(tpl) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "quick-chat-chip";
      b.textContent = "📦 " + tpl.name;
      b.title = tpl.desc;
      b.addEventListener("click", function() {
        els.quickTplBar.style.display = "none";
        openQuickAddModal(false);
        if (els.quickEditTitle) els.quickEditTitle.textContent = "📦 テンプレート: " + tpl.name;
        if (els.quickEditCode) els.quickEditCode.value = tpl.code;
        syncQuickSaveBtnState();
        if (els.quickEditStatus) els.quickEditStatus.textContent = "テンプレートを展開しました。「▶試実行」または「決定して保存」を押してください";
      });
      els.quickTplBar.appendChild(b);
    });
    els.quickTplBar.style.display = "flex";
  }

  function dryRunQuickEditCode() {
    if (state.busy) return;
    var code = els.quickEditCode ? String(els.quickEditCode.value || "").trim() : "";
    if (!code) {
      if (els.quickEditStatus) els.quickEditStatus.textContent = "試実行するコードがありません";
      return;
    }
    try {
      new Function(code);
    } catch (eSyn) {
      if (els.quickEditStatus) els.quickEditStatus.textContent = "⚠ 構文エラー: " + String((eSyn && eSyn.message) || eSyn);
      return;
    }
    if (els.quickDryRunBar) { els.quickDryRunBar.style.display = "none"; els.quickDryRunBar.innerHTML = ""; }
    if (els.btnQuickDryRun) els.btnQuickDryRun.disabled = true;
    if (els.quickEditStatus) els.quickEditStatus.textContent = "▶ 控えを取って試実行しています…";
    runServerAction({
      fnName: "comboQuickRun",
      payload: {
        dryRunCode: code,
        backup: true,
        targetId: state.target.id || "",
        sheet: state.curSheet || "",
        selection: (els.chkSync && els.chkSync.checked) ? (state.selection || "") : ""
      },
      label: "▶ 試実行 (ドライラン)",
      statusText: "試実行中…",
      switchToChat: false,
      onSuccess: function(res) {
        if (els.btnQuickDryRun) els.btnQuickDryRun.disabled = false;
        if (els.quickEditStatus) els.quickEditStatus.textContent = (res && res.text) || "▶ 試実行が完了しました";
        if (els.quickDryRunBar) {
          els.quickDryRunBar.innerHTML = "";
          var span = document.createElement("span");
          span.textContent = (res && res.snapped) ? "✓ 控え付きで試実行しました（元に戻せます）" : "✓ 試実行が完了しました";
          var uBtn = document.createElement("button");
          uBtn.type = "button";
          uBtn.className = "btn";
          uBtn.style.padding = "2px 8px";
          uBtn.textContent = "↶ 試実行を取り消す";
          uBtn.addEventListener("click", function() {
            uBtn.disabled = true;
            onUndo();
            els.quickDryRunBar.style.display = "none";
          });
          els.quickDryRunBar.appendChild(span);
          els.quickDryRunBar.appendChild(uBtn);
          els.quickDryRunBar.style.display = "flex";
        }
      },
      onError: function(err) {
        if (els.btnQuickDryRun) els.btnQuickDryRun.disabled = false;
        if (els.quickEditStatus) els.quickEditStatus.textContent = "⚠ 試実行エラー: " + formatError(err);
      }
    });
  }

  function startPolishRecordedMacro(macroItem) {
    if (!macroItem || !macroItem.code) return;
    if (els.quickEditCode) {
      els.quickEditCode.disabled = false;
      els.quickEditCode.value = String(macroItem.code);
    }
    var fnLabel = String(macroItem.name || "記録マクロ");
    var polishPrompt =
      "以下はスプレッドシート標準の「マクロを記録」で記録されたコード（関数名: " + fnLabel + "）です。" +
      "無駄な activate() や固定番地を取り除き、どのシートでも安全・高速に動く汎用マイマクロへ磨き上げてください。" +
      "既存の棚で置き換えられる処理は積極的に shelf([...]) のまとめ棚に変換し、分かりやすい関数名と // 説明・// 棚: 言い方 も付けてください。";
    if (els.quickAiInput) els.quickAiInput.value = polishPrompt;
    syncQuickSaveBtnState();
    submitQuickAi();
  }

  function importRecordedMacros() {
    if (state.busy) return;
    if (els.btnQuickImportRec) els.btnQuickImportRec.disabled = true;
    if (els.quickEditStatus) els.quickEditStatus.textContent = "🎬 記録マクロを読み込んでいます…";
    requestRecordedMacros({ ssId: (state.target && state.target.id) || "" }, function(r) {
      if (els.btnQuickImportRec) els.btnQuickImportRec.disabled = false;
      if (!r || !r.reachable) {
        var msgUnreach = "ローカル直結（Chrome拡張＋受け手 127.0.0.1:18766）に接続できません。拡張がない環境では macros.gs を「貼付」して送信してください。";
        if (els.quickEditStatus) els.quickEditStatus.textContent = "⚠ " + msgUnreach;
        if (!Array.isArray(quickEditState.chatHistory)) quickEditState.chatHistory = [];
        quickEditState.chatHistory.push({ role: "err", text: "⚠ " + msgUnreach });
        renderQuickChat();
        setQuickModalTab("chat");
        return;
      }
      var d = r.data || {};
      if (!d.ok || !Array.isArray(d.macros) || !d.macros.length) {
        var errMsg = String(d.error || r.error || "記録マクロを取得できませんでした");
        if (els.quickEditStatus) els.quickEditStatus.textContent = "⚠ " + errMsg;
        if (!Array.isArray(quickEditState.chatHistory)) quickEditState.chatHistory = [];
        quickEditState.chatHistory.push({ role: "ai", text: errMsg });
        renderQuickChat();
        setQuickModalTab("chat");
        return;
      }
      if (d.macros.length === 1) {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "🎬 「" + d.macros[0].name + "」を取り込みました。AI でまとめ棚へ磨き上げます…";
        startPolishRecordedMacro(d.macros[0]);
        return;
      }
      quickEditState.recordedCandidates = d.macros;
      if (!Array.isArray(quickEditState.chatHistory)) quickEditState.chatHistory = [];
      quickEditState.chatHistory.push({
        role: "ai",
        text: "🎬 記録マクロが " + d.macros.length + " 件見つかりました。下の候補から取り込むマクロを選んでください（クリックすると AI がまとめ棚マイマクロに磨き上げます）。"
      });
      renderQuickChat();
      setQuickModalTab("chat");
      if (els.quickEditStatus) els.quickEditStatus.textContent = "🎬 取り込む記録マクロを下の候補から選んでください";
    });
  }

  function stripCodeFence(txt) {
    var s = String(txt || "").trim();
    var m = s.match(/^```(?:javascript|js|gs)?\r?\n([\s\S]*?)\r?\n?```$/i);
    return m ? m[1].trim() : s;
  }

  function openSaveStepsBar(picked) {
    state.pendingSteps = picked.slice();
    if (!els.saveStepsBar) return;
    if (els.saveStepsInfo) els.saveStepsInfo.textContent = "手順(" + picked.length + "件): " + picked.join(" / ");
    if (els.saveStepsName) els.saveStepsName.value = "手順_" + String(picked[0] || "").slice(0, 12);
    els.saveStepsBar.style.display = "flex";
    if (els.saveStepsName) {
      els.saveStepsName.focus();
      if (els.saveStepsName.select) els.saveStepsName.select();
    }
  }

  function closeSaveStepsBar() {
    state.pendingSteps = [];
    if (els.saveStepsBar) els.saveStepsBar.style.display = "none";
    if (els.saveStepsName) els.saveStepsName.value = "";
  }

  function submitSaveSteps() {
    var steps = (state.pendingSteps || []).slice();
    var name = els.saveStepsName ? (els.saveStepsName.value || "").trim() : "";
    if (!steps.length || !name) {
      if (els.saveStepsName) els.saveStepsName.focus();
      return;
    }
    runServerAction({
      fnName: "comboQuickSaveSteps",
      payload: { name: name, steps: steps },
      label: "⚡手順マクロ保存: " + name,
      statusText: "手順マクロを保存中…",
      switchToChat: false,
      onSuccess: function(res) {
        closeSaveStepsBar();
        state.checkedHist = {};
        renderHistory();
        if (els.quickNote) els.quickNote.textContent = (res && res.text) || "手順マクロを保存しました";
        if (res && res.myStamp) {
          state.quick.myStamp = res.myStamp;
          quickRememberLocal();
        }
        quickClearCodeCache();
        loadQuickList(false);
        switchTab("list");
      }
    });
  }

  if (els.quickFilterBar) {
    var qBtns = els.quickFilterBar.querySelectorAll(".quick-filter-btn");
    for (var qi = 0; qi < qBtns.length; qi++) {
      qBtns[qi].addEventListener("click", function() {
        var f = this.getAttribute("data-qfilter") || "all";
        state.quick.filter = f;
        state.quick.sel = -1;
        for (var k = 0; k < qBtns.length; k++) qBtns[k].classList.toggle("active", qBtns[k] === this);
        renderQuickCatBar();
        renderQuickList();
      });
    }
  }
  if (els.btnQuickRun) {
    els.btnQuickRun.addEventListener("click", function() {
      var it = state.quick.items[state.quick.sel];
      if (it) { quickRunItem(it); return; }
      if (!quickRunFromInput() && (els.askInput.value || "").trim()) onRunAsk();
    });
  }
  if (els.btnQuickReload) {
    els.btnQuickReload.addEventListener("click", function() { quickClearCodeCache(); loadQuickList(true); });
  }
  if (els.btnQuickAdd) {
    els.btnQuickAdd.addEventListener("click", function() { openQuickAddModal(false); });
  }
  if (els.btnQuickAi) {
    els.btnQuickAi.addEventListener("click", function() { openQuickAddModal(true); });
  }
  if (els.btnQuickTpl) els.btnQuickTpl.addEventListener("click", toggleQuickTplBar);
  if (els.btnQuickExport) els.btnQuickExport.addEventListener("click", function() { exportMyMacros("json"); });
  if (els.btnQuickExportGs) els.btnQuickExportGs.addEventListener("click", function() { exportMyMacros("gs"); });
  if (els.btnQuickImport && els.quickImportFile) {
    els.btnQuickImport.addEventListener("click", function() {
      els.quickImportFile.value = "";
      els.quickImportFile.click();
    });
    els.quickImportFile.addEventListener("change", function() {
      var f = els.quickImportFile.files && els.quickImportFile.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function() { importMyMacrosText(String(reader.result || "")); };
      reader.onerror = function() { setQuickExportImportNote("⚠ ファイルを読み込めませんでした"); };
      reader.readAsText(f, "utf-8");
    });
  }
  if (els.btnQuickDryRun) els.btnQuickDryRun.addEventListener("click", dryRunQuickEditCode);
  if (els.btnQuickAiSubmit) {
    els.btnQuickAiSubmit.addEventListener("click", submitQuickAi);
  }
  if (els.quickAiInput) {
    els.quickAiInput.addEventListener("keydown", function(e) {
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitQuickAi();
      }
    });
  }
  if (els.btnQuickRevert) {
    els.btnQuickRevert.addEventListener("click", function() {
      var nm = quickEditState.name || "";
      var prevCode = quickGetPrevCode(nm);
      if (!nm || quickEditState.mode !== "edit" || !prevCode) return;
      var curBefore = quickEditState.origCode || (els.quickEditCode ? els.quickEditCode.value : "");
      if (els.quickEditStatus) els.quickEditStatus.textContent = "修正前のコードに戻しています…";
      runServerAction({
        fnName: "comboQuickSaveFn",
        payload: { name: nm, code: prevCode, myId: state.quick.myId || "" },
        label: "修正前に戻す: " + nm,
        statusText: "修正前に戻しています…",
        switchToChat: false,
        onSuccess: function(res) {
          var revertedName = (res && res.newName) || nm;
          if (curBefore && curBefore !== prevCode) quickSavePrevCode(revertedName, curBefore);
          if (res && res.myStamp) state.quick.myStamp = res.myStamp;
          quickClearCodeCache();
          quickRememberLocal();
          closeQuickEditModal();
          if (els.quickNote) els.quickNote.textContent = "「" + revertedName + "」を修正前のコードに戻しました";
          loadQuickList(false);
        },
        onError: function(err) {
          if (els.quickEditStatus) els.quickEditStatus.textContent = "戻せませんでした: " + formatError(err);
        }
      });
    });
  }
  if (els.btnQuickEdit) {
    els.btnQuickEdit.addEventListener("click", function() {
      var q = state.quick, it = q.items[q.sel];
      if (!q.myId) {
        openQuickAddModal(true);
        return;
      }
      if (!it || it.src === "shelf") {
        if (els.quickNote) els.quickNote.textContent = "「棚」は大元本体の機能のため編集できません";
        return;
      }
      var cc = q.codeCache || { stamp: "", map: {} };
      var cacheOk = !!(cc.map && typeof cc.map[it.name] === "string" && (!q.myStamp || !cc.stamp || cc.stamp === q.myStamp));
      quickEditReqSeq++;
      quickEditState = { mode: "edit", name: it.name, myUrl: q.myUrl || "", delArmed: false, origCode: cacheOk ? cc.map[it.name] : "", pendingReqId: "", activeTab: "code", chatHistory: [], codeUpdated: false };
      resetQuickDeleteBtn();
      if (els.quickModalTabs && els.quickModalTabs.style) els.quickModalTabs.style.display = "grid";
      if (els.quickAiBox) els.quickAiBox.style.display = "flex";
      if (els.quickAiInput) {
        els.quickAiInput.value = "";
        els.quickAiInput.placeholder = "例: どんな編集ができる？ / 背景色も変えて";
      }
      if (els.btnQuickAiSubmit) {
        els.btnQuickAiSubmit.disabled = false;
        els.btnQuickAiSubmit.textContent = "✨ 送信";
      }
      if (els.btnQuickRevert) els.btnQuickRevert.style.display = quickGetPrevCode(it.name) ? "" : "none";
      if (els.quickEditPromptRow) els.quickEditPromptRow.style.display = "none";
      if (els.btnQuickEditDelete) els.btnQuickEditDelete.style.display = "";
      if (els.btnQuickEditSave) els.btnQuickEditSave.textContent = "決定して保存";
      if (els.quickEditTitle) els.quickEditTitle.textContent = "編集: " + it.name;
      if (els.quickEditCode && els.quickEditCode.style) els.quickEditCode.style.borderColor = "#94a3b8";
      renderQuickChat();
      setQuickModalTab("code");
      if (cacheOk) {
        if (els.quickEditCode) { els.quickEditCode.disabled = false; els.quickEditCode.value = cc.map[it.name]; }
        syncQuickSaveBtnState();
        if (els.quickEditStatus) els.quickEditStatus.textContent = "コードを修正または「💬 AI会話」で相談し、「決定して保存」で反映";
        if (els.quickEditModal) els.quickEditModal.style.display = "flex";
        if (els.quickAiInput) els.quickAiInput.focus();
        return;
      }
      if (els.quickEditCode) { els.quickEditCode.value = ""; els.quickEditCode.placeholder = "コードを読込中…"; els.quickEditCode.disabled = true; }
      if (els.btnQuickEditSave) els.btnQuickEditSave.disabled = true;
      if (els.quickEditStatus) els.quickEditStatus.textContent = "既存コードを読み込んでいます…";
      if (els.quickEditModal) els.quickEditModal.style.display = "flex";
      if (els.quickAiInput) els.quickAiInput.focus();
      var reqSeq = quickEditReqSeq;
      callGas("comboQuickGetFn", { name: it.name, myId: q.myId || "", myStamp: q.myStamp || "", includeAll: true }, function(res) {
        if (reqSeq !== quickEditReqSeq) return;
        if (!res || res.ok === false) {
          if (els.quickEditCode) els.quickEditCode.disabled = false;
          syncQuickSaveBtnState();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "読込エラー: " + String((res && (res.error || res.text)) || "読み込めませんでした");
          return;
        }
        var st = (res && res.myStamp) || q.myStamp || "";
        if (res && res.myStamp) { q.myStamp = res.myStamp; quickRememberLocal(); }
        if (res && res.codes && typeof res.codes === "object") {
          q.codeCache = { stamp: st, map: res.codes };
          quickSaveCodeCache();
        } else if (res && typeof res.code === "string") {
          if (!q.codeCache || (st && q.codeCache.stamp !== st)) q.codeCache = { stamp: st, map: {} };
          q.codeCache.map[it.name] = res.code;
          quickSaveCodeCache();
        }
        if (quickEditState.mode !== "edit" || quickEditState.name !== it.name) return;
        quickEditState.myUrl = (res && res.myUrl) || q.myUrl || "";
        quickEditState.origCode = (res && res.code) || "";
        if (els.quickEditCode) { els.quickEditCode.disabled = false; els.quickEditCode.value = quickEditState.origCode; }
        syncQuickSaveBtnState();
        if (els.quickEditStatus) els.quickEditStatus.textContent = "コードを修正または「💬 AI会話」で相談し、「決定して保存」で反映";
      }, function(err) {
        if (reqSeq !== quickEditReqSeq) return;
        if (els.quickEditCode) els.quickEditCode.disabled = false;
        syncQuickSaveBtnState();
        if (els.quickEditStatus) els.quickEditStatus.textContent = "読込エラー: " + formatError(err);
      });
    });
  }
  if (els.tabQuickModalChat) els.tabQuickModalChat.addEventListener("click", function() { setQuickModalTab("chat"); });
  if (els.tabQuickModalCode) els.tabQuickModalCode.addEventListener("click", function() { setQuickModalTab("code"); });
  if (els.btnQuickEditClose) els.btnQuickEditClose.addEventListener("click", closeQuickEditModal);
  if (els.btnQuickImportRec) els.btnQuickImportRec.addEventListener("click", importRecordedMacros);
  if (els.btnQuickEditPrompt) {
    els.btnQuickEditPrompt.addEventListener("click", function() {
      copyToClipboard(buildMyMacroAiPrompt()).then(function() {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "AI へ頼む型をコピーしました";
      }).catch(function() {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "コピーに失敗しました";
      });
    });
  }
  if (els.btnQuickEditCopy) {
    els.btnQuickEditCopy.addEventListener("click", function() {
      var code = els.quickEditCode ? els.quickEditCode.value : "";
      copyToClipboard(code).then(function() {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "コードをコピーしました";
      }).catch(function() {
        if (els.quickEditCode) { els.quickEditCode.focus(); els.quickEditCode.select(); }
        if (els.quickEditStatus) els.quickEditStatus.textContent = "全選択しました。Ctrl+C でコピーしてください";
      });
    });
  }
  if (els.btnQuickEditPaste) {
    els.btnQuickEditPaste.addEventListener("click", function() {
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function(txt) {
          if (!txt || !String(txt).trim()) {
            if (els.quickEditStatus) els.quickEditStatus.textContent = "クリップボードが空です";
            return;
          }
          if (els.quickEditCode) els.quickEditCode.value = stripCodeFence(txt);
          resetQuickDeleteBtn();
          syncQuickSaveBtnState();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "貼り付けました。「決定して保存」を押してください";
        }).catch(function() {
          if (els.quickEditCode) { els.quickEditCode.focus(); els.quickEditCode.select(); }
          if (els.quickEditStatus) els.quickEditStatus.textContent = "全選択しました。Ctrl+V で貼り付けてください";
        });
      } else {
        if (els.quickEditCode) { els.quickEditCode.focus(); els.quickEditCode.select(); }
        if (els.quickEditStatus) els.quickEditStatus.textContent = "全選択しました。Ctrl+V で貼り付けてください";
      }
    });
  }
  if (els.quickEditCode) {
    els.quickEditCode.addEventListener("input", function() {
      if (quickEditState.delArmed) resetQuickDeleteBtn();
      syncQuickSaveBtnState();
    });
  }
  if (els.btnQuickEditSave) {
    els.btnQuickEditSave.addEventListener("click", function() {
      var mode = quickEditState.mode || "edit";
      var nm = quickEditState.name || "";
      var origSnap = quickEditState.origCode || "";
      var code = els.quickEditCode ? els.quickEditCode.value : "";
      if (!String(code || "").trim()) {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "保存するコードがありません";
        return;
      }
      if (mode === "add") {
        if (els.quickEditStatus) els.quickEditStatus.textContent = "マイマクロへ追加しています…";
        runServerAction({
          fnName: "comboQuickAddFn", payload: { code: code },
          label: "新規マイマクロを追加", statusText: "マイマクロへ追加しています…", switchToChat: false,
          onSuccess: function(res) {
            if (res && res.myId) { state.quick.myId = res.myId; state.quick.myUrl = res.myUrl || ""; }
            closeQuickEditModal();
            if (els.quickNote) els.quickNote.textContent = (res && res.text) || "マイマクロに追加しました";
            var newStamp = (res && res.myStamp) || "";
            state.quick.myStamp = newStamp;
            if (res && Array.isArray(res.names) && res.names.length === 1 && state.quick.codeCache) {
              state.quick.codeCache.map[res.names[0]] = String(code || "").replace(/\r\n/g, "\n").replace(/\s*$/, "");
              state.quick.codeCache.stamp = newStamp;
              quickSaveCodeCache();
            } else {
              quickClearCodeCache();
            }
            quickRememberLocal();
            updateSettingsMyMacroUI();
            loadQuickList(false);
          },
          onError: function(err) {
            if (els.quickEditStatus) els.quickEditStatus.textContent = "エラー: " + formatError(err);
          }
        });
        return;
      }
      if (!nm) return;
      if (els.quickEditStatus) els.quickEditStatus.textContent = "保存しています…";
      runServerAction({
        fnName: "comboQuickSaveFn", payload: { name: nm, code: code, myId: state.quick.myId || "" },
        label: "マイマクロを保存", statusText: "保存しています…", switchToChat: false,
        onSuccess: function(res) {
          var savedName = (res && res.newName) || nm;
          if (origSnap && origSnap !== code) quickSavePrevCode(savedName, origSnap);
          closeQuickEditModal();
          if (els.quickNote) els.quickNote.textContent = (res && res.text) || ("「" + savedName + "」を保存しました");
          var newStamp = (res && res.myStamp) || "";
          state.quick.myStamp = newStamp;
          if (state.quick.codeCache && state.quick.codeCache.map) {
            if (savedName !== nm) delete state.quick.codeCache.map[nm];
            state.quick.codeCache.map[savedName] = String(code || "").replace(/\r\n/g, "\n").replace(/\s*$/, "");
            state.quick.codeCache.stamp = newStamp;
            quickSaveCodeCache();
          }
          quickRememberLocal();
          loadQuickList(false);
        },
        onError: function(err) {
          if (els.quickEditStatus) els.quickEditStatus.textContent = "エラー: " + formatError(err);
        }
      });
    });
  }
  if (els.btnQuickEditDelete) {
    els.btnQuickEditDelete.addEventListener("click", function() {
      var nm = quickEditState.name || "";
      if (!nm || quickEditState.mode !== "edit") return;
      if (!quickEditState.delArmed) {
        quickEditState.delArmed = true;
        els.btnQuickEditDelete.textContent = "本当に削除";
        els.btnQuickEditDelete.style.background = "#dc2626";
        els.btnQuickEditDelete.style.color = "#ffffff";
        if (els.quickEditStatus) els.quickEditStatus.textContent = "「" + nm + "」を削除します。よろしければもう一度「本当に削除」を押してください";
        return;
      }
      if (els.quickEditStatus) els.quickEditStatus.textContent = "削除しています…";
      runServerAction({
        fnName: "comboQuickDeleteFn", payload: { name: nm, myId: state.quick.myId || "" },
        label: "マイマクロを削除", statusText: "削除しています…", switchToChat: false,
        onSuccess: function(res) {
          closeQuickEditModal();
          if (els.quickNote) els.quickNote.textContent = (res && res.text) || ("「" + nm + "」を削除しました");
          var newStamp = (res && res.myStamp) || "";
          state.quick.myStamp = newStamp;
          if (state.quick.codeCache && state.quick.codeCache.map) {
            delete state.quick.codeCache.map[nm];
            state.quick.codeCache.stamp = newStamp;
            quickSaveCodeCache();
          }
          quickRememberLocal();
          loadQuickList(false);
        },
        onError: function(err) {
          resetQuickDeleteBtn();
          if (els.quickEditStatus) els.quickEditStatus.textContent = "削除エラー: " + formatError(err);
        }
      });
    });
  }
  if (els.btnSaveSteps) {
    els.btnSaveSteps.addEventListener("click", function() {
      var picked = [];
      for (var hi = 0; hi < state.history.length; hi++) {
        if (state.checkedHist[hi]) picked.push(state.history[hi]);
      }
      if (!picked.length && state.selectedHistIdx >= 0 && state.history[state.selectedHistIdx]) {
        picked.push(state.history[state.selectedHistIdx]);
      }
      if (!picked.length && (els.askInput.value || "").trim()) {
        picked.push((els.askInput.value || "").trim());
      }
      if (!picked.length) {
        flashBtn(els.btnSaveSteps, "履歴を選択", "⚡手順化");
        return;
      }
      openSaveStepsBar(picked);
    });
  }
  if (els.btnSaveStepsOk) els.btnSaveStepsOk.addEventListener("click", submitSaveSteps);
  if (els.btnSaveStepsCancel) els.btnSaveStepsCancel.addEventListener("click", closeSaveStepsBar);
  if (els.saveStepsName) {
    els.saveStepsName.addEventListener("keydown", function(e) {
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Enter") { e.preventDefault(); submitSaveSteps(); }
      else if (e.key === "Escape") { e.preventDefault(); closeSaveStepsBar(); }
    });
  }
  if (els.btnSettingsMyMacro) {
    els.btnSettingsMyMacro.addEventListener("click", function() {
      var q = state.quick;
      if (q.myUrl) {
        q.myStamp = "";
        quickRememberLocal();
        quickClearCodeCache();
        window.open(q.myUrl, "_blank");
        return;
      }
      runServerAction({
        fnName: "comboQuickMake", payload: {}, label: "マイマクロを作る", statusText: "マイマクロを作っています…", switchToChat: false,
        onSuccess: function(res) {
          q.myId = res.myId || ""; q.myUrl = res.myUrl || "";
          if (res.myStamp) { q.myStamp = res.myStamp; quickRememberLocal(); }
          if (els.settingsMyStatus) els.settingsMyStatus.textContent = (res.text || "作成しました") + "。もう一度押すとエディタで開けます";
          updateSettingsMyMacroUI();
          loadQuickList(false);
        }
      });
    });
  }
  if (els.settingsDefaultTab) {
    els.settingsDefaultTab.addEventListener("change", function() {
      state.quick.defaultTab = els.settingsDefaultTab.value === "list" ? "list" : "auto";
      state._userSwitchedTab = true;
      quickSaveUiState();
    });
  }

  document.addEventListener("keydown", function(e) {
    if (e.isComposing || e.keyCode === 229) return;
    if (els.quickEditModal && els.quickEditModal.style.display !== "none") {
      if (e.key === "Escape") { e.preventDefault(); closeQuickEditModal(); }
      return;
    }
    if (state.activeTab !== "list") return;
    if (e.altKey && state.quick.sel >= 0) {
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        quickMove(e.key === "ArrowUp" ? -1 : 1);
      }
      return;
    }
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(e.target.tagName)) return;
    var items = state.quick.items || [];
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      quickSelectIdx(state.quick.sel < 0 ? 0 : Math.min(items.length - 1, state.quick.sel + 1));
    } else if (e.key === "ArrowUp" && state.quick.sel >= 0 && items.length) {
      e.preventDefault();
      quickSelectIdx(state.quick.sel - 1);
    } else if (e.key === "Escape" && state.quick.sel >= 0) {
      e.preventDefault();
      quickSelectIdx(-1);
    } else if (e.key === "Enter" && state.quick.sel >= 0 && items[state.quick.sel] && !state.busy) {
      e.preventDefault();
      quickRunItem(items[state.quick.sel]);
    }
  });

  // ---- 初期起動 ----
  renderHistory();
  quickRestoreList();
  if (state.quick.defaultTab === "list") {
    switchTab("list");
  }
  if (hasGasBridge()) {
    var initKind = "";
    try {
      var usp = new URLSearchParams(window.location.search || "");
      initKind = usp.get("kind") || "";
    } catch (_eUsp) {}
    var startInit = function(extSheet) {
      if (extSheet) applyExtSheet(extSheet);
      runServerAction({
        fnName: "comboInit",
        payload: {
          targetId: "",
          kind: initKind,
          sheet: getSelectedSheet() || extSheet || "",
          assumeActive: true,
          includeQuick: true,
          wantCodes: true,
          includeLearned: true,
          clientStamp: quickClientStamp()
        },
        label: "初期化 / 再読込",
        statusText: "読込中…",
        switchToChat: false,
        silentSuccess: true,
        onSuccess: function(res) {
          if (res && res.quick) applyQuickListRes(res.quick);
          else loadQuickList();
          if (!res || !res.learned) loadLearned();
          if (!res.config) {
            callGas("comboGetConfig", undefined, function(cfg) { applyConfig(cfg); });
          }
        }
      });
    };
    if (initKind !== "doc" && typeof requestLiveSelection === "function") {
      requestLiveSelection(function(live) {
        startInit(live && live.sheet ? live.sheet : "");
      });
    } else {
      startInit("");
    }
  } else {
    els.targetNameLabel.textContent = "プレビュー";
    els.infoLabel.textContent = "対象: GAS サイドバー環境で自動接続されます";
    updateSelectionLabel();
    updatePreview();
  }
  if (typeof globalThis !== "undefined") {
    globalThis.__comboDirectTest = {
      state: state,
      els: els,
      buildDirectBatchUpdate: buildDirectBatchUpdate,
      tryCompileMyMacroDirect: tryCompileMyMacroDirect,
      switchTab: switchTab,
      renderQuickList: renderQuickList,
      quickFiltered: quickFiltered,
      quickRunItem: quickRunItem,
      applyQuickListRes: applyQuickListRes,
      submitQuickAi: submitQuickAi,
      QUICK_MY_TEMPLATES: QUICK_MY_TEMPLATES,
      exportMyMacrosData: exportMyMacrosData,
      parseImportMyMacros: parseImportMyMacros,
      applyServerState: applyServerState,
      applyExtSheet: applyExtSheet,
      onRunAsk: onRunAsk,
      onLook: onLook,
      getSelectedSheet: getSelectedSheet,
      syncSheetSelects: syncSheetSelects
    };
  }
})();
</script>
</body>
</html>
