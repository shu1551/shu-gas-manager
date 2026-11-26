<script>
(function() {
  "use strict";

  // ComboPlanner が未注入の環境向け安全フォールバック
  var Planner = (typeof ComboPlanner !== "undefined" && ComboPlanner) ? ComboPlanner : {
    init: function() {},
    plan: function() {
      return { ops: [], fire: false, reasons: [], missing: [], previewText: "" };
    },
    parseSelectionScope: function() {
      return {};
    },
    formatOpsShort: function(ops) {
      if (!ops || !ops.length) return "";
      return ops.map(function(o) {
        var args = Object.keys(o || {}).filter(function(k) { return k !== "shelf"; }).map(function(k) {
          return k + "=" + JSON.stringify(o[k]);
        }).join(", ");
        return (o.shelf || "?") + "(" + args + ")";
      }).join(", ");
    }
  };

  if (typeof COMBO_CATALOG_DATA !== "undefined" && Planner.init) {
    try { Planner.init(COMBO_CATALOG_DATA); } catch (_e) {}
  }

  var TAB_NAMES = {
    auto: "自動",
    list: "一覧",
    chat: "会話",
    hist: "履歴",
    trace: "経過",
    conf: "設定"
  };

  var state = {
    activeTab: "auto",
    busy: false,
    _userSwitchedTab: false,
    target: { id: "", name: "", kind: "sheet", url: "", sheet: "" },
    sheets: [],
    curSheet: "",
    table: null,
    selection: "",
    heading: "",
    scope: {},
    config: {
      aiMode: "postbox",
      aiModel: "sonnet",
      hasApiKey: false,
      hasGeminiKey: false,
      hasClaudeKey: false,
      backupDefault: false
    },
    history: [],
    histIdx: -1,
    selectedHistIdx: -1,
    checkedHist: {},
    pendingSteps: [],
    pollTimer: null,
    polling: false,
    pendingPostboxIds: {},
    oauthToken: "",
    sheetIdMap: {},
    sheetDimsMap: {},
    sheetSnapshot: {},
    directUndoStack: [],
    quick: {
      loaded: false,
      my: [],
      myId: "",
      myUrl: "",
      myStamp: "",
      order: { my: [], shelf: [] },
      pins: {},
      usage: {},
      filter: "all",
      cat: "all",
      recentSort: "time",
      collapsedCats: {},
      items: [],
      sel: -1,
      codeCache: { stamp: "", map: {} },
      defaultTab: "auto"
    }
  };

  var els = {
    askInput: document.getElementById("askInput"),
    btnRun: document.getElementById("btnRun"),
    btnClear: document.getElementById("btnClear"),
    btnCopyAi: document.getElementById("btnCopyAi"),
    chkOk: document.getElementById("chkOk"),
    chkBackup: document.getElementById("chkBackup"),
    chkAiAuto: document.getElementById("chkAiAuto"),
    chkSync: document.getElementById("chkSync"),
    healthBadge: document.getElementById("healthBadge"),
    statusLabel: document.getElementById("statusLabel"),
    targetNameLabel: document.getElementById("targetNameLabel"),
    sheetSelect: document.getElementById("sheetSelect"),
    btnLook: document.getElementById("btnLook"),
    btnRefresh: document.getElementById("btnRefresh"),
    quickFilterBar: document.getElementById("quickFilterBar"),
    quickCatBar: document.getElementById("quickCatBar"),
    quickTplBar: document.getElementById("quickTplBar"),
    quickList: document.getElementById("quickList"),
    btnQuickTpl: document.getElementById("btnQuickTpl"),
    btnQuickExport: document.getElementById("btnQuickExport"),
    btnQuickExportGs: document.getElementById("btnQuickExportGs"),
    btnQuickImport: document.getElementById("btnQuickImport"),
    quickImportFile: document.getElementById("quickImportFile"),
    btnQuickRun: document.getElementById("btnQuickRun"),
    btnQuickAdd: document.getElementById("btnQuickAdd"),
    btnQuickEdit: document.getElementById("btnQuickEdit"),
    btnQuickAi: document.getElementById("btnQuickAi"),
    btnQuickReload: document.getElementById("btnQuickReload"),
    quickNote: document.getElementById("quickNote"),
    autoSheetPanel: document.getElementById("autoSheetPanel"),
    autoDocPanel: document.getElementById("autoDocPanel"),
    btnSeiri: document.getElementById("btnSeiri"),
    btnDocStyle: document.getElementById("btnDocStyle"),
    selLabel: document.getElementById("selLabel"),
    previewLabel: document.getElementById("previewLabel"),
    infoLabel: document.getElementById("infoLabel"),
    chatLog: document.getElementById("chatLog"),
    btnClearLog: document.getElementById("btnClearLog"),
    btnCopyLog: document.getElementById("btnCopyLog"),
    btnAgain: document.getElementById("btnAgain"),
    btnGoChanged: document.getElementById("btnGoChanged"),
    histList: document.getElementById("histList"),
    saveStepsBar: document.getElementById("saveStepsBar"),
    saveStepsInfo: document.getElementById("saveStepsInfo"),
    saveStepsName: document.getElementById("saveStepsName"),
    btnSaveStepsOk: document.getElementById("btnSaveStepsOk"),
    btnSaveStepsCancel: document.getElementById("btnSaveStepsCancel"),
    btnSaveSteps: document.getElementById("btnSaveSteps"),
    btnUseHist: document.getElementById("btnUseHist"),
    btnRerunHist: document.getElementById("btnRerunHist"),
    traceLog: document.getElementById("traceLog"),
    settingsSheetSelect: document.getElementById("settingsSheetSelect"),
    settingsInfoLabel: document.getElementById("settingsInfoLabel"),
    settingsMyStatus: document.getElementById("settingsMyStatus"),
    btnSettingsMyMacro: document.getElementById("btnSettingsMyMacro"),
    settingsDefaultTab: document.getElementById("settingsDefaultTab"),
    cfgAiMode: document.getElementById("cfgAiMode"),
    cfgAiModel: document.getElementById("cfgAiModel"),
    cfgApiKey: document.getElementById("cfgApiKey"),
    btnSaveConfig: document.getElementById("btnSaveConfig"),
    btnCheckPostbox: document.getElementById("btnCheckPostbox"),
    postboxStatusLabel: document.getElementById("postboxStatusLabel"),
    btnNewTalk: document.getElementById("btnNewTalk"),
    btnUndo: document.getElementById("btnUndo"),
    btnReload: document.getElementById("btnReload"),
    quickEditModal: document.getElementById("quickEditModal"),
    quickEditTitle: document.getElementById("quickEditTitle"),
    btnQuickEditClose: document.getElementById("btnQuickEditClose"),
    quickModalTabs: document.getElementById("quickModalTabs"),
    tabQuickModalChat: document.getElementById("tabQuickModalChat"),
    tabQuickModalCode: document.getElementById("tabQuickModalCode"),
    quickCodeBadge: document.getElementById("quickCodeBadge"),
    quickChatPane: document.getElementById("quickChatPane"),
    quickChatLog: document.getElementById("quickChatLog"),
    quickChatChips: document.getElementById("quickChatChips"),
    quickAiBox: document.getElementById("quickAiBox"),
    quickAiInput: document.getElementById("quickAiInput"),
    btnQuickAiSubmit: document.getElementById("btnQuickAiSubmit"),
    btnQuickRevert: document.getElementById("btnQuickRevert"),
    quickEditCode: document.getElementById("quickEditCode"),
    quickEditStatus: document.getElementById("quickEditStatus"),
    quickDryRunBar: document.getElementById("quickDryRunBar"),
    quickEditPromptRow: document.getElementById("quickEditPromptRow"),
    btnQuickEditPrompt: document.getElementById("btnQuickEditPrompt"),
    btnQuickImportRec: document.getElementById("btnQuickImportRec"),
    btnQuickEditCopy: document.getElementById("btnQuickEditCopy"),
    btnQuickEditPaste: document.getElementById("btnQuickEditPaste"),
    btnQuickDryRun: document.getElementById("btnQuickDryRun"),
    btnQuickEditSave: document.getElementById("btnQuickEditSave"),
    btnQuickEditDelete: document.getElementById("btnQuickEditDelete")
  };

  function hasGasBridge() {
    return typeof google !== "undefined" && google.script && google.script.run;
  }

  function callGas(fnName, arg, onOk, onErr) {
    if (!hasGasBridge()) {
      if (onErr) onErr(new Error("google.script.run が利用できません（GAS サイドバー外でのプレビュー表示中）"));
      return;
    }
    var runner = google.script.run
      .withSuccessHandler(function(res) { if (onOk) onOk(res); })
      .withFailureHandler(function(err) { if (onErr) onErr(err); });
    if (typeof runner[fnName] !== "function") {
      if (onErr) onErr(new Error("サーバー関数が見つかりません: " + fnName));
      return;
    }
    if (arg === undefined) {
      runner[fnName]();
    } else {
      runner[fnName](arg);
    }
  }

  function formatOpsShort(ops) {
    if (Planner.formatOpsShort) {
      return Planner.formatOpsShort(ops || []);
    }
    return (ops || []).map(function(o) {
      var args = Object.keys(o || {}).filter(function(k) { return k !== "shelf"; }).map(function(k) {
        return k + "=" + JSON.stringify(o[k]);
      }).join(", ");
      return (o.shelf || "?") + "(" + args + ")";
    }).join(", ");
  }

  function formatTiming(wallMs, gasMs, isDirectApi) {
    var wallSec = Math.max(0, wallMs / 1000);
    if (isDirectApi) {
      return "合計 " + wallSec.toFixed(2) + "s（直接API " + wallSec.toFixed(2) + "s / GAS 0.00s）";
    }
    if (typeof gasMs === "number" && isFinite(gasMs) && gasMs >= 0) {
      var gasSec = Math.max(0, gasMs / 1000);
      var commSec = Math.max(0, wallSec - gasSec);
      return "合計 " + wallSec.toFixed(2) + "s（通信 " + commSec.toFixed(2) + "s / GAS " + gasSec.toFixed(2) + "s）";
    }
    return "合計 " + wallSec.toFixed(2) + "s";
  }

  function setStatus(text, isBusy) {
    els.statusLabel.textContent = text;
    if (isBusy) {
      els.statusLabel.classList.add("busy");
    } else {
      els.statusLabel.classList.remove("busy");
    }
  }

  function setBusy(busy, statusText) {
    state.busy = !!busy;
    els.btnRun.disabled = state.busy;
    if (state.busy) {
      setStatus(statusText || "実行中…", true);
    } else {
      setStatus("表示中: " + (TAB_NAMES[state.activeTab] || "自動"), false);
    }
  }

  function switchTab(tabKey) {
    if (!TAB_NAMES[tabKey]) tabKey = "auto";
    state.activeTab = tabKey;
    var btns = document.querySelectorAll(".tab-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle("active", btns[i].getAttribute("data-tab") === tabKey);
    }
    var panes = document.querySelectorAll(".tab-pane");
    for (var j = 0; j < panes.length; j++) {
      panes[j].classList.toggle("active", panes[j].id === "pane-" + tabKey);
    }
    if (!state.busy) {
      setStatus("表示中: " + TAB_NAMES[tabKey], false);
    }
  }

  function appendLog(container, kindClass, headText, bodyText) {
    var empty = container.querySelector(".log-empty");
    if (empty) empty.remove();

    var entry = document.createElement("div");
    entry.className = "log-entry " + (kindClass || "is-info");

    var head = document.createElement("div");
    head.className = "log-head";
    head.textContent = headText;
    entry.appendChild(head);

    if (bodyText) {
      var body = document.createElement("div");
      body.textContent = bodyText;
      entry.appendChild(body);
    }

    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
    return entry;
  }

  // 棚に当たらなかった頼みに近い候補を出し、［はい］で撃って言い方を覚える（次から同じ頼みは一発で当たる）
  function loadLearned() {
    if (!Planner.setLearned) return;
    callGas("comboGetLearned", undefined, function(res) {
      if (res && res.learned && typeof res.learned === "object") {
        Planner.setLearned(res.learned);
        updatePreview();
      }
    }, function() {});
  }

  function offerSuggest(txt, ops, onNo) {
    var entry = appendLog(els.chatLog, "is-info", "棚に当たりませんでした: " + txt,
      "近い候補: " + formatOpsShort(ops) + "\nこれを撃ちますか？（［はい］で撃って、この言い方を覚えます）");
    var bar = document.createElement("div");
    var yes = document.createElement("button");
    yes.type = "button";
    yes.className = "btn";
    yes.textContent = "はい（撃って覚える）";
    var no = document.createElement("button");
    no.type = "button";
    no.className = "btn";
    no.textContent = onNo ? "いいえ（AI に頼む）" : "いいえ";
    yes.onclick = function() {
      bar.remove();
      if (Planner.learn) Planner.learn(txt, ops);
      callGas("comboLearn", { ask: txt, ops: ops, key: Planner.learnKey ? Planner.learnKey(txt) : "" }, function() {}, function() {});
      onRunOps(ops, txt);
    };
    no.onclick = function() { bar.remove(); if (onNo) onNo(); };
    bar.appendChild(yes);
    bar.appendChild(no);
    entry.appendChild(bar);
    switchTab("chat");
  }

  function clearLogBox(container, placeholder) {
    container.innerHTML = "";
    var empty = document.createElement("div");
    empty.className = "log-empty";
    empty.textContent = placeholder || "";
    container.appendChild(empty);
  }

  function formatError(err) {
    if (!err) return "不明なエラー";
    if (typeof err === "string") return err;
    if (err.message) return err.message;
    try { return JSON.stringify(err); } catch (_e) { return String(err); }
  }

  function updateAutoPanelMode() {
    var isDoc = state.target && state.target.kind === "doc";
    els.autoSheetPanel.style.display = isDoc ? "none" : "block";
    els.autoDocPanel.style.display = isDoc ? "block" : "none";
  }

  function syncSheetSelects() {
    var isDoc = state.target && state.target.kind === "doc";
    var selects = [els.sheetSelect, els.settingsSheetSelect];
    for (var s = 0; s < selects.length; s++) {
      var sel = selects[s];
      sel.innerHTML = "";
      if (isDoc) {
        var optDoc = document.createElement("option");
        optDoc.value = "";
        optDoc.textContent = "（文書）";
        sel.appendChild(optDoc);
        sel.disabled = true;
      } else {
        sel.disabled = false;
        var list = state.sheets && state.sheets.length ? state.sheets : (state.curSheet ? [state.curSheet] : []);
        for (var i = 0; i < list.length; i++) {
          var opt = document.createElement("option");
          opt.value = list[i];
          opt.textContent = list[i];
          if (list[i] === state.curSheet) opt.selected = true;
          sel.appendChild(opt);
        }
      }
    }
  }

  function updateSelectionLabel() {
    if (!els.chkSync.checked) {
      els.selLabel.textContent = "選択中: OFF（上部「連動」チェックで有効化）";
      return;
    }
    var isDoc = state.target && state.target.kind === "doc";
    if (isDoc) {
      if (state.heading) {
        els.selLabel.textContent = "選択中: 見出し「" + state.heading + "」";
      } else if (state.target.name) {
        els.selLabel.textContent = "選択中: " + state.target.name;
      } else {
        els.selLabel.textContent = "選択中: 待機中…";
      }
      return;
    }
    if (state.selection) {
      var shPart = state.curSheet ? (state.curSheet + " › ") : "";
      els.selLabel.textContent = "選択中: " + shPart + state.selection + "（「ここ」「選択範囲」や場所省略で即適用）";
    } else {
      els.selLabel.textContent = "選択中: 待機中（シート上のセルを選択してください）";
    }
  }

  function updateInfoLabel() {
    var tgt = state.target || {};
    var name = tgt.name || tgt.id || "対象未設定";
    els.targetNameLabel.textContent = name;
    els.targetNameLabel.title = name + (tgt.url ? "\n" + tgt.url : "");

    var msg = "";
    if (tgt.kind === "doc") {
      msg = "[文書] " + name + "\n（Google ドキュメントを選択中）";
    } else {
      var sh = state.curSheet || tgt.sheet || "";
      var tb = state.table;
      if (tb) {
        var cols = (tb.columns || []).map(function(c) {
          return (c.col || "") + ":" + (c.name || "");
        }).join("・");
        msg = "[表] " + name + (sh ? " › " + sh : "") +
          "\n見出し" + (tb.header_row || 1) + "行 (" + (tb.first_col || "?") + "〜" + (tb.last_col || "?") +
          "・" + (tb.data != null ? tb.data : "?") + "行)" +
          (cols ? " / 列: " + cols : "");
      } else {
        msg = "[表] " + name + (sh ? " › " + sh : "") + "（表情報なし）";
      }
    }
    els.infoLabel.textContent = msg;
    els.settingsInfoLabel.textContent = msg;
  }

  function getActiveScope() {
    if (!els.chkSync.checked) return null;
    if (state.scope && Object.keys(state.scope).length > 0) return state.scope;
    if (state.selection && Planner.parseSelectionScope) {
      return Planner.parseSelectionScope(state.selection);
    }
    return null;
  }

  function updatePreview() {
    var txt = (els.askInput.value || "").trim();
    els.previewLabel.classList.remove("preview-hit", "preview-miss");
    if (!txt) {
      els.previewLabel.textContent = "自動判定: 待機中";
      return null;
    }
    var kind = (state.target && state.target.kind) || "sheet";
    var ls = getActiveScope();
    var p = Planner.plan(txt, kind, state.table, state.sheets, state.curSheet, ls);
    if (p && p.fire) {
      var shortOps = formatOpsShort(p.ops);
      els.previewLabel.textContent = "棚ヒット: " + shortOps;
      els.previewLabel.classList.add("preview-hit");
    } else {
      var reason = "";
      if (p && p.reasons && p.reasons.length) {
        reason = p.reasons.join("／");
      } else if (p && p.missing && p.missing.length) {
        reason = "不足: " + p.missing.join("、");
      } else {
        reason = "棚に該当なし";
      }
      var suffix = els.chkAiAuto.checked ? "（実行時はAIが解釈して実行）" : "";
      els.previewLabel.textContent = "未確定: " + reason + suffix;
      els.previewLabel.classList.add("preview-miss");
    }
    return p;
  }

  function applyServerState(res, forceRefreshSnap) {
    if (!res || typeof res !== "object") return;
    if (res.target && typeof res.target === "object") {
      state.target = {
        id: res.target.id || state.target.id || "",
        name: res.target.name || state.target.name || "",
        kind: res.target.kind || state.target.kind || "sheet",
        url: res.target.url || state.target.url || "",
        sheet: res.target.sheet || ""
      };
      if (res.target.sheet) state.curSheet = res.target.sheet;
    }
    if (Array.isArray(res.sheets)) {
      state.sheets = res.sheets;
    }
    if (typeof res.sheet === "string" && res.sheet) {
      state.curSheet = res.sheet;
    }
    if (!state.curSheet && state.sheets.length) {
      state.curSheet = state.sheets[0];
    }
    if ("table" in res && res.table !== undefined) {
      state.table = res.table;
    }
    if (typeof res.selection === "string") {
      state.selection = res.selection.toUpperCase();
      if (res.scope && typeof res.scope === "object") {
        state.scope = res.scope;
      } else if (state.selection && Planner.parseSelectionScope) {
        state.scope = Planner.parseSelectionScope(state.selection);
      } else {
        state.scope = {};
      }
    } else if (res.scope && typeof res.scope === "object") {
      state.scope = res.scope;
    }
    if (typeof res.heading === "string") {
      state.heading = res.heading;
    }
    if (res.config) {
      applyConfig(res.config);
    }
    if (typeof res.oauthToken === "string" && res.oauthToken) {
      state.oauthToken = res.oauthToken;
    }
    if (Array.isArray(res.sheetInfos)) {
      for (var si = 0; si < res.sheetInfos.length; si++) {
        var sInfo = res.sheetInfos[si];
        if (sInfo && sInfo.name) {
          if (typeof sInfo.sheetId === "number") state.sheetIdMap[sInfo.name] = sInfo.sheetId;
          state.sheetDimsMap[sInfo.name] = { rows: Number(sInfo.rows || 0), cols: Number(sInfo.cols || 0) };
        }
      }
    }
    if (state.curSheet && typeof res.sheetId === "number") {
      state.sheetIdMap[state.curSheet] = res.sheetId;
    }

    updateAutoPanelMode();
    syncSheetSelects();
    updateSelectionLabel();
    updateInfoLabel();
    updatePreview();
    if (state.curSheet && state.oauthToken && state.target.id) {
      var curSnap = state.sheetSnapshot[state.curSheet];
      var needDim = getSnapshotDims(state.curSheet);
      if (forceRefreshSnap || !curSnap || (curSnap.maxRows && curSnap.maxRows < needDim.maxRows) || (curSnap.maxCols && curSnap.maxCols < needDim.maxCols)) {
        prefetchSheetSnapshot(state.curSheet);
      }
    }
  }

  function applyConfig(raw) {
    var cfg = (raw && raw.config) ? raw.config : raw;
    if (!cfg || typeof cfg !== "object") return;
    if (cfg.aiMode) state.config.aiMode = cfg.aiMode;
    if (cfg.aiModel) state.config.aiModel = cfg.aiModel;
    if ("bridgeToken" in cfg) state.config.bridgeToken = String(cfg.bridgeToken || "");
    var bkp = ("backupDefault" in cfg) ? cfg.backupDefault : cfg.backup;
    if (typeof bkp === "boolean") {
      state.config.backupDefault = bkp;
      els.chkBackup.checked = bkp;
    }
    if ("hasApiKey" in cfg) state.config.hasApiKey = !!cfg.hasApiKey;
    if ("apiKey" in cfg && cfg.apiKey) state.config.hasApiKey = true;
    if ("hasGeminiKey" in cfg) state.config.hasGeminiKey = !!cfg.hasGeminiKey;
    if ("hasClaudeKey" in cfg) state.config.hasClaudeKey = !!cfg.hasClaudeKey;

    if (els.cfgAiMode.querySelector('option[value="' + state.config.aiMode + '"]')) {
      els.cfgAiMode.value = state.config.aiMode;
    }
    if (els.cfgAiModel.querySelector('option[value="' + state.config.aiModel + '"]')) {
      els.cfgAiModel.value = state.config.aiModel;
    }
    updateApiKeyPlaceholder();
    if (typeof refreshHealthBadge === "function") refreshHealthBadge();
  }

  // 連携方式に合うモデルだけを出す（Gemini の鍵 → Gemini のモデル・それ以外 → Claude のモデル）
  // 方式を替えても、その系統で前に選んだモデルに戻す（無ければ Claude は Sonnet・Gemini は Hydrogen）
  function modelFamilyKey_(isGemini) { return "gasCombo.lastModel." + (isGemini ? "gemini" : "claude"); }
  function rememberModel_() {
    var v = els.cfgAiModel.value;
    try { localStorage.setItem(modelFamilyKey_(v.indexOf("gemini_") === 0), v); } catch (e) {}
  }
  function syncModelOptions() {
    var isGemini = els.cfgAiMode.value === "api_gemini";
    var opts = els.cfgAiModel.options, okVals = {}, curOk = false;
    for (var i = 0; i < opts.length; i++) {
      var ok = (opts[i].value.indexOf("gemini_") === 0) === isGemini;
      opts[i].hidden = !ok;
      opts[i].disabled = !ok;
      if (ok) okVals[opts[i].value] = true;
      if (ok && opts[i].value === els.cfgAiModel.value) curOk = true;
    }
    if (curOk) return;
    var last = "";
    try { last = localStorage.getItem(modelFamilyKey_(isGemini)) || ""; } catch (e) {}
    els.cfgAiModel.value = okVals[last] ? last : (isGemini ? "gemini_hydrogen" : "sonnet");
  }

  function updateApiKeyPlaceholder() {
    syncModelOptions();
    var mode = els.cfgAiMode.value;
    if (mode === "api_gemini" && (state.config.hasGeminiKey || state.config.hasApiKey)) {
      els.cfgApiKey.placeholder = "Geminiキー設定済み（変更時のみ入力）";
    } else if (mode === "api_claude" && (state.config.hasClaudeKey || state.config.hasApiKey)) {
      els.cfgApiKey.placeholder = "Claudeキー設定済み（変更時のみ入力）";
    } else if (mode === "postbox") {
      els.cfgApiKey.placeholder = "ローカル直結ではAPIキー不要";
    } else {
      els.cfgApiKey.placeholder = "APIキーを入力";
    }
  }

  function renderHistory() {
    els.histList.innerHTML = "";
    if (!state.history.length) {
      var empty = document.createElement("div");
      empty.className = "log-empty";
      empty.textContent = "実行した指示の履歴はまだありません。";
      els.histList.appendChild(empty);
      return;
    }
    for (var i = 0; i < state.history.length; i++) {
      (function(idx) {
        var item = document.createElement("div");
        item.className = "hist-item hist-row" + (state.selectedHistIdx === idx ? " selected" : "");
        var chk = document.createElement("input");
        chk.type = "checkbox";
        chk.checked = !!(state.checkedHist && state.checkedHist[idx]);
        chk.title = "チェックして「⚡手順化」でまとめて手順マクロにできます";
        chk.addEventListener("click", function(e) { e.stopPropagation(); });
        chk.addEventListener("change", function() {
          if (!state.checkedHist) state.checkedHist = {};
          if (chk.checked) state.checkedHist[idx] = true;
          else delete state.checkedHist[idx];
        });
        var span = document.createElement("span");
        span.className = "hist-row-txt";
        span.textContent = state.history[idx];
        item.appendChild(chk);
        item.appendChild(span);
        item.addEventListener("click", function() {
          state.selectedHistIdx = idx;
          renderHistory();
        });
        item.addEventListener("dblclick", function() {
          state.selectedHistIdx = idx;
          els.askInput.value = state.history[idx];
          updatePreview();
          onRunAsk();
        });
        els.histList.appendChild(item);
      })(i);
    }
    els.histList.scrollTop = els.histList.scrollHeight;
  }

  function pushHistory(txt) {
    if (!txt) return;
    if (!state.history.length || state.history[state.history.length - 1] !== txt) {
      state.history.push(txt);
      state.selectedHistIdx = state.history.length - 1;
      renderHistory();
    }
    state.histIdx = state.history.length;
  }

  function recordExecution(ok, label, bodyText, wallMs, gasMs, switchToChat, isDirectApi) {
    var timing = formatTiming(wallMs, gasMs, isDirectApi);
    var prefix = ok ? "✓" : "✗";
    var cls = ok ? "is-ok" : "is-err";
    var body = (bodyText ? bodyText.replace(/\s+$/, "") + "\n" : "") + "(" + timing + ")";
    appendLog(els.chatLog, cls, "[" + prefix + "] " + label, body);
    var mChg = ok && bodyText ? String(bodyText).match(/直した所:\s*(\S+)/) : null;
    if (mChg) state.lastChanged = mChg[1].replace(/[／,、]+$/, "");
    appendLog(els.traceLog, cls, "[" + prefix + " " + label + "] " + timing, "");
    if (!ok || switchToChat) {
      switchTab("chat");
    }
  }

  // ---- 直接 Sheets API 高速実行エンジン（GAS起動ゼロ・0.4秒級） ----
  /*__WS_SHARED_COLOR_MAP_START__*/
  var DIRECT_COLOR_MAP = {
    "黒": "#000000", "black": "#000000", "白": "#FFFFFF", "white": "#FFFFFF",
    "赤": "#FF0000", "red": "#FF0000", "青": "#0000FF", "blue": "#0000FF",
    "緑": "#008000", "green": "#008000", "黄": "#FFFF00", "yellow": "#FFFF00",
    "橙": "#FFA500", "オレンジ": "#FFA500", "orange": "#FFA500",
    "紫": "#800080", "purple": "#800080", "桃": "#FFC0CB", "ピンク": "#FFC0CB", "pink": "#FFC0CB",
    "灰": "#808080", "灰色": "#808080", "グレー": "#808080", "gray": "#808080", "grey": "#808080",
    "水色": "#00FFFF", "シアン": "#00FFFF", "cyan": "#00FFFF", "lightblue": "#ADD8E6",
    "紺": "#000080", "ネイビー": "#000080", "navy": "#000080",
    "茶": "#8B4513", "茶色": "#8B4513", "brown": "#8B4513",
    "薄赤": "#FCE4D6", "薄青": "#D9E1F2", "薄緑": "#E2EFDA", "薄黄": "#FFF2CC",
    "薄灰": "#F2F2F2", "薄灰色": "#F2F2F2", "薄グレー": "#F2F2F2",
    "薄橙": "#FCE5CD", "薄紫": "#EAD1DC",
    "lightred": "#FCE4D6", "lightgreen": "#E2EFDA", "lightyellow": "#FFF2CC", "lightgray": "#F2F2F2"
  };
  /*__WS_SHARED_COLOR_MAP_END__*/

  function isClearColor(val) {
    var s = String(val === undefined || val === null ? "" : val).trim();
    return s === "なし" || /^(none|transparent|clear)$/i.test(s);
  }

  function parseColorToRgbObj(val) {
    if (val === undefined || val === null || val === "") return null;
    var s = String(val).trim();
    if (isClearColor(s)) {
      return { red: 1, green: 1, blue: 1 };
    }
    var hex = DIRECT_COLOR_MAP[s] || DIRECT_COLOR_MAP[s.toLowerCase()];
    if (!hex) {
      var norm = s.replace(/^薄い/, "薄").replace(/色$/, "");
      hex = DIRECT_COLOR_MAP[norm] || DIRECT_COLOR_MAP[s.replace(/^薄い/, "薄")];
    }
    if (!hex && /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(s)) {
      hex = s.length === 4 ? ("#" + s[1] + s[1] + s[2] + s[2] + s[3] + s[3]) : s;
    }
    if (!hex) return null;
    var r = parseInt(hex.slice(1, 3), 16) / 255;
    var g = parseInt(hex.slice(3, 5), 16) / 255;
    var b = parseInt(hex.slice(5, 7), 16) / 255;
    return { red: r, green: g, blue: b };
  }

  function colToNum0(colStr) {
    var s = String(colStr || "").trim().toUpperCase();
    var n = 0;
    for (var i = 0; i < s.length; i++) {
      var code = s.charCodeAt(i);
      if (code < 65 || code > 90) return -1;
      n = n * 26 + (code - 64);
    }
    return n - 1;
  }

  function num0ToCol(n0) {
    var n = n0 + 1;
    var s = "";
    while (n > 0) {
      var m = (n - 1) % 26;
      s = String.fromCharCode(65 + m) + s;
      n = Math.floor((n - 1) / 26);
    }
    return s;
  }

  function parseSimpleA1Range(a1Str, sheetId) {
    var s = String(a1Str || "").trim().toUpperCase();
    if (!s || s.indexOf("!") >= 0) return null;
    var m = s.match(/^([A-Z]{1,3})([0-9]{1,6})(?::([A-Z]{1,3})([0-9]{1,6}))?$/);
    if (!m) return null;
    var c1 = colToNum0(m[1]);
    var r1 = parseInt(m[2], 10) - 1;
    var c2 = m[3] ? colToNum0(m[3]) : c1;
    var r2 = m[4] ? (parseInt(m[4], 10) - 1) : r1;
    if (c1 < 0 || c2 < c1 || r1 < 0 || r2 < r1) return null;
    var canon = (r1 === r2 && c1 === c2) ? (m[1] + (r1 + 1)) : (m[1] + (r1 + 1) + ":" + (m[3] || m[1]) + (r2 + 1));
    return {
      gridRange: {
        sheetId: sheetId,
        startRowIndex: r1,
        endRowIndex: r2 + 1,
        startColumnIndex: c1,
        endColumnIndex: c2 + 1
      },
      a1: canon,
      r1: r1, r2: r2, c1: c1, c2: c2
    };
  }

  function resolveColLetterFromTable(colRef) {
    var ref = String(colRef || "").trim();
    if (!ref) return "";
    if (/^[A-Za-z]{1,3}$/.test(ref)) return ref.toUpperCase();
    var mCol = ref.match(/^([A-Za-z]{1,3})列$/);
    if (mCol) return mCol[1].toUpperCase();
    var cols = (state.table && Array.isArray(state.table.columns)) ? state.table.columns : [];
    for (var i = 0; i < cols.length; i++) {
      if (cols[i] && (cols[i].name === ref || cols[i].col === ref.toUpperCase())) {
        return cols[i].col;
      }
    }
    return "";
  }

  function getSnapshotDims(sheetName) {
    var maxR = 30, maxC = 26;
    var dims = state.sheetDimsMap && state.sheetDimsMap[sheetName];
    if (dims) {
      if (dims.rows > maxR) maxR = dims.rows;
      if (dims.cols > maxC) maxC = dims.cols;
    }
    var tb = state.table;
    if (tb && (!state.curSheet || state.curSheet === sheetName)) {
      if (tb.total_row && Number(tb.total_row) > maxR) maxR = Number(tb.total_row);
      if (tb.data) {
        var dm = String(tb.data).match(/-([0-9]+)$/);
        if (dm && parseInt(dm[1], 10) > maxR) maxR = parseInt(dm[1], 10);
      }
      if (tb.last_col) {
        var lcN = colToNum0(tb.last_col) + 1;
        if (lcN > maxC) maxC = lcN;
      }
    }
    maxR = Math.min(200, Math.max(30, maxR));
    maxC = Math.min(40, Math.max(26, maxC));
    return { maxRows: maxR, maxCols: maxC, rangeA1: "A1:" + num0ToCol(maxC - 1) + maxR };
  }

  function prefetchSheetSnapshot(sheetName) {
    if (!state.oauthToken || !state.target.id || !sheetName || typeof fetch !== "function") return;
    var dim = getSnapshotDims(sheetName);
    var qName = "'" + String(sheetName).replace(/'/g, "''") + "'!" + dim.rangeA1;
    var url = "https://sheets.googleapis.com/v4/spreadsheets/" + encodeURIComponent(state.target.id) +
      "?ranges=" + encodeURIComponent(qName) +
      "&fields=sheets(properties(sheetId,title,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),bandedRanges(bandedRangeId),data(rowData(values(userEnteredFormat,userEnteredValue,effectiveValue(errorValue)))))";
    fetch(url, {
      method: "GET",
      headers: { "Authorization": "Bearer " + state.oauthToken }
    })
      .then(function(r) { if (!r.ok) throw new Error("Sheets API HTTP " + r.status); return r.json(); })
      .then(function(data) {
        if (!data || !Array.isArray(data.sheets) || !data.sheets[0]) return;
        var shObj = data.sheets[0];
        var props = shObj.properties || {};
        if (props.title && typeof props.sheetId === "number") {
          state.sheetIdMap[props.title] = props.sheetId;
        }
        var gp = props.gridProperties || {};
        var rowData = (shObj.data && shObj.data[0] && shObj.data[0].rowData) || [];
        var cells = [];
        for (var r = 0; r < dim.maxRows; r++) {
          var rowVals = (rowData[r] && rowData[r].values) || [];
          var rowArr = [];
          for (var c = 0; c < dim.maxCols; c++) {
            rowArr.push((rowVals[c] && rowVals[c].userEnteredFormat) ? JSON.parse(JSON.stringify(rowVals[c].userEnteredFormat)) : {});
          }
          cells.push(rowArr);
        }
        var bIds = [];
        if (Array.isArray(shObj.bandedRanges)) {
          for (var bi = 0; bi < shObj.bandedRanges.length; bi++) {
            if (shObj.bandedRanges[bi] && typeof shObj.bandedRanges[bi].bandedRangeId === "number") {
              bIds.push(shObj.bandedRanges[bi].bandedRangeId);
            }
          }
        }
        state.sheetSnapshot[sheetName] = {
          maxRows: dim.maxRows,
          maxCols: dim.maxCols,
          rangeA1: dim.rangeA1,
          errs: errsOfRowData(rowData, dim.maxRows, dim.maxCols),
          vals: valsOfRowData(rowData, dim.maxRows, dim.maxCols),
          frozenRows: gp.frozenRowCount || 0,
          frozenCols: gp.frozenColumnCount || 0,
          hideGridlines: !!gp.hideGridlines,
          bandedRangeIds: bIds,
          cells: cells
        };
        state.prefetchError = "";
      })
      .catch(function(err) { state.prefetchError = String((err && err.message) || err || "写しを取れません"); });
  }

  // 写しの範囲の中のエラーのセル { "A1": "#REF!" }
  var ERR_LABEL = { ERROR: "#ERROR!", NULL_VALUE: "#NULL!", DIVIDE_BY_ZERO: "#DIV/0!", VALUE: "#VALUE!", REF: "#REF!", NAME: "#NAME?", NUM: "#NUM!", N_A: "#N/A", LOADING: "" };
  // 写しの範囲の「書く前の値」 { "A1": userEnteredValue }（空のセルは入れない）
  function valsOfRowData(rowData, maxRows, maxCols) {
    var out = {};
    var limR = Math.min(rowData.length, maxRows || 30);
    var limC = maxCols || 26;
    for (var r = 0; r < limR; r++) {
      var vs = (rowData[r] && rowData[r].values) || [];
      for (var c = 0; c < Math.min(vs.length, limC); c++) {
        if (vs[c] && vs[c].userEnteredValue) out[num0ToCol(c) + (r + 1)] = vs[c].userEnteredValue;
      }
    }
    return out;
  }

  function errsOfRowData(rowData, maxRows, maxCols) {
    var out = {};
    var limR = Math.min(rowData.length, maxRows || 30);
    var limC = maxCols || 26;
    for (var r = 0; r < limR; r++) {
      var vs = (rowData[r] && rowData[r].values) || [];
      for (var c = 0; c < Math.min(vs.length, limC); c++) {
        var ev = vs[c] && vs[c].effectiveValue && vs[c].effectiveValue.errorValue;
        if (ev && ERR_LABEL[ev.type] !== "") out[num0ToCol(c) + (r + 1)] = ERR_LABEL[ev.type] || ("#" + ev.type);
      }
    }
    return out;
  }

  // 値を書く手を直結で撃った後、写しの範囲を読み直して、撃つ前に無かったエラーだけを返す（書式だけの手では読まない）
  function checkNewErrorsAfterDirect(sheetName, ops, done) {
    var writes = ops.some(function(o) { return /^(write|clear\.)/.test(String(o.shelf || "")); });
    var snap = state.sheetSnapshot[sheetName];
    if (!writes || !snap || !snap.errs || typeof fetch !== "function") { done([]); return; }
    var rngA1 = snap.rangeA1 || "A1:Z30";
    var qName = "'" + String(sheetName).replace(/'/g, "''") + "'!" + rngA1;
    var url = "https://sheets.googleapis.com/v4/spreadsheets/" + encodeURIComponent(state.target.id) +
      "?ranges=" + encodeURIComponent(qName) + "&fields=sheets(data(rowData(values(effectiveValue(errorValue)))))";
    fetch(url, { method: "GET", headers: { "Authorization": "Bearer " + state.oauthToken } })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        var rowData = (data && data.sheets && data.sheets[0] && data.sheets[0].data && data.sheets[0].data[0] && data.sheets[0].data[0].rowData) || [];
        var now = errsOfRowData(rowData, snap.maxRows, snap.maxCols), news = [];
        Object.keys(now).forEach(function(k) { if (!(k in snap.errs)) news.push(k + " " + now[k]); });
        snap.errs = now;
        done(news);
      })
      .catch(function() { done([]); });
  }

  function getSnapCellFmt(sheetName, r0, c0) {
    var snap = state.sheetSnapshot[sheetName];
    if (!snap || !snap.cells || !snap.cells[r0] || !snap.cells[r0][c0]) return {};
    return snap.cells[r0][c0];
  }

  function resolveTableRangeStr(includeHeader) {
    if (!state.table || !state.table.first_col || !state.table.last_col) return "";
    var dm = String(state.table.data || "").match(/^([0-9]+)-([0-9]+)$/);
    var startRow = includeHeader ? Number(state.table.header_row || (dm ? dm[1] : 0)) : (dm ? parseInt(dm[1], 10) : 0);
    var endRow = state.table.total_row ? Number(state.table.total_row) : (dm ? parseInt(dm[2], 10) : Number(state.table.last_row || startRow));
    if (!startRow || !endRow || endRow < startRow) return "";
    return state.table.first_col + startRow + ":" + state.table.last_col + endRow;
  }

  function toUserEnteredValue(val) {
    if (val === null || val === undefined || val === "") return {};
    if (typeof val === "number" && isFinite(val)) return { numberValue: val };
    if (typeof val === "boolean") return { boolValue: val };
    var s = String(val);
    if (s.charAt(0) === "=") return { formulaValue: s };
    return { stringValue: s };
  }

  var BANDING_THEMES = {
    gray: { header: "#616161", first: "#FFFFFF", second: "#F5F5F5" },
    blue: { header: "#1565C0", first: "#FFFFFF", second: "#E3F2FD" },
    green: { header: "#2E7D32", first: "#FFFFFF", second: "#E8F5E9" },
    orange: { header: "#EF6C00", first: "#FFFFFF", second: "#FFF3E0" }
  };

  function inferNumberFormatType(pattern) {
    var p = String(pattern || "");
    if (p === "@" || p.indexOf("@") >= 0) return "TEXT";
    if (p.indexOf("%") >= 0) return "PERCENT";
    if (/[¥$€£￥]/.test(p)) return "CURRENCY";
    var stripped = p.replace(/"[^"]*"/g, "").replace(/\\./g, "");
    var hasDate = /[ymd]/i.test(stripped);
    var hasTime = /[hs]/i.test(stripped) || stripped.indexOf("AM/PM") >= 0;
    if (hasDate && hasTime) return "DATE_TIME";
    if (hasDate) return "DATE";
    if (hasTime) return "TIME";
    return "NUMBER";
  }

  function buildDirectBatchUpdate(ops, sheetName) {
    if (!Array.isArray(ops) || !ops.length) return null;
    if (!state.oauthToken || !state.target.id || state.target.kind !== "sheet" || !sheetName) return null;
    if (els.chkBackup.checked) return null;
    if (typeof state.sheetIdMap[sheetName] !== "number") return null;

    var sheetId = state.sheetIdMap[sheetName];
    var snapCur = state.sheetSnapshot[sheetName] || null;
    var maxRow0 = (snapCur && snapCur.maxRows) ? (snapCur.maxRows - 1) : 29;
    var maxCol0 = (snapCur && snapCur.maxCols) ? (snapCur.maxCols - 1) : 25;
    var requests = [];
    var undoRequests = [];
    var snapshotMutators = [];
    var undoSnapshotMutators = [];
    var changed = [];
    var whatList = [];

    for (var i = 0; i < ops.length; i++) {
      var op = ops[i];
      if (!op || !op.shelf) return null;
      if (op.sheet && op.sheet !== sheetName) return null;
      // 背景色を消す棚／bg="なし" は書式の道で「背景色の欄を空で送る」＝塗りつぶしなしに戻す
      var bgClear = op.shelf === "bg.clear" || (op.shelf === "format" && op.bg !== undefined && isClearColor(op.bg));
      if (op.shelf === "bg.clear") op = Object.assign({}, op, { shelf: "format" });

      if (op.shelf === "format") {
        var targetA1 = "";
        if (op.title) {
          targetA1 = (state.table && state.table.title_a1) || "A1";
          if (op.merge === undefined && targetA1.indexOf(":") < 0 && state.table && state.table.last_col) {
            var tmT = /^([A-Z]+)(\d+)$/.exec(targetA1);
            var fcT = state.table.first_col || (tmT && tmT[1]);
            var lcT = state.table.last_col;
            if (tmT && colToNum0(lcT) > colToNum0(tmT[1])) {
              var startColL = colToNum0(fcT) < colToNum0(tmT[1]) ? fcT : tmT[1];
              var bandClear = !!(snapCur && snapCur.vals);
              if (bandClear) {
                var rKey = tmT[2];
                var cLo = colToNum0(startColL), cHi = colToNum0(lcT), cOrig = colToNum0(tmT[1]);
                for (var bc = cLo; bc <= cHi; bc++) {
                  if (bc !== cOrig && snapCur.vals[num0ToCol(bc) + rKey]) {
                    bandClear = false;
                    break;
                  }
                }
              }
              if (bandClear) {
                targetA1 = startColL + tmT[2] + ":" + lcT + tmT[2];
                if (op.align === "center" || op.align === "right") {
                  op = Object.assign({}, op, { align: "left" });
                }
              }
            }
          }
        } else if (op.header) {
          if (!state.table || !state.table.header_row || !state.table.first_col || !state.table.last_col) return null;
          targetA1 = state.table.first_col + state.table.header_row + ":" + state.table.last_col + state.table.header_row;
        } else if (op.col) {
          var colL = resolveColLetterFromTable(op.col);
          if (!colL || !state.table || !state.table.data) return null;
          var dm = String(state.table.data).match(/^([0-9]+)-([0-9]+)$/);
          if (!dm) return null;
          var rStart = parseInt(dm[1], 10);
          var rEnd = state.table.total_row ? Number(state.table.total_row) : parseInt(dm[2], 10);
          targetA1 = colL + rStart + ":" + colL + rEnd;
        } else if (op.range) {
          targetA1 = String(op.range).trim();
        } else {
          return null;
        }

        var parsedRg = parseSimpleA1Range(targetA1, sheetId);
        if (!parsedRg) return null;

        var cellFmt = {};
        var textFmt = {};
        var hasTextFmt = false;
        var fields = [];
        var did = [];

        if (op.bold !== undefined) {
          textFmt.bold = !!op.bold;
          hasTextFmt = true;
          fields.push("userEnteredFormat.textFormat.bold");
          did.push("bold");
        }
        if (op.italic !== undefined) {
          textFmt.italic = !!op.italic;
          hasTextFmt = true;
          fields.push("userEnteredFormat.textFormat.italic");
          did.push("italic");
        }
        if (op.color !== undefined) {
          var rgbFg = parseColorToRgbObj(op.color);
          if (!rgbFg) return null;
          textFmt.foregroundColorStyle = { rgbColor: rgbFg };
          hasTextFmt = true;
          fields.push("userEnteredFormat.textFormat.foregroundColorStyle");
          did.push("color");
        }
        if (bgClear) {
          fields.push("userEnteredFormat.backgroundColorStyle");
          did.push("bg");
        } else if (op.bg !== undefined) {
          var rgbBg = parseColorToRgbObj(op.bg);
          if (!rgbBg) return null;
          cellFmt.backgroundColorStyle = { rgbColor: rgbBg };
          fields.push("userEnteredFormat.backgroundColorStyle");
          did.push("bg");
        }
        if (op.size !== undefined) {
          textFmt.fontSize = Number(op.size);
          hasTextFmt = true;
          fields.push("userEnteredFormat.textFormat.fontSize");
          did.push("size");
        }
        if (op.font !== undefined) {
          textFmt.fontFamily = String(op.font);
          hasTextFmt = true;
          fields.push("userEnteredFormat.textFormat.fontFamily");
          did.push("font");
        }
        if (op.number_format !== undefined) {
          var nfPat = String(op.number_format);
          cellFmt.numberFormat = { type: inferNumberFormatType(nfPat), pattern: nfPat };
          fields.push("userEnteredFormat.numberFormat");
          did.push("number_format");
        }
        if (op.align !== undefined) {
          var al = String(op.align).toUpperCase();
          if (al === "MIDDLE") al = "CENTER";
          cellFmt.horizontalAlignment = al;
          fields.push("userEnteredFormat.horizontalAlignment");
          did.push("align");
        }
        if (op.valign !== undefined) {
          var val = String(op.valign).toUpperCase();
          if (val === "CENTER") val = "MIDDLE";
          cellFmt.verticalAlignment = val;
          fields.push("userEnteredFormat.verticalAlignment");
          did.push("valign");
        }
        if (op.wrap !== undefined) {
          cellFmt.wrapStrategy = op.wrap ? "WRAP" : "OVERFLOW_CELL";
          fields.push("userEnteredFormat.wrapStrategy");
          did.push("wrap");
        }

        if (fields.length) {
          if (hasTextFmt) cellFmt.textFormat = textFmt;

          requests.push({
            repeatCell: {
              range: parsedRg.gridRange,
              cell: { userEnteredFormat: cellFmt },
              fields: fields.join(",")
            }
          });

          // 取り消し：書く前のセルの書式を、セルごとにそのまま書き戻す（範囲の左上 1 セルで全体を塗り戻さない）。
          // 書く前の写し（A1:Z30）が無い・範囲がその外なら、直結の道は使わず GAS の道に任せる（黒・白で戻してしまうため）
          var snapU = state.sheetSnapshot[sheetName];
          if (!snapU || !snapU.cells || !snapU.cells.length || parsedRg.r2 > maxRow0 || parsedRg.c2 > maxCol0) return null;
          var prevCells = [], undoRows = [];
          for (var ur = parsedRg.r1; ur <= parsedRg.r2; ur++) {
            var pRow = [], uVals = [];
            for (var uc = parsedRg.c1; uc <= parsedRg.c2; uc++) {
              var pf = JSON.parse(JSON.stringify((snapU.cells[ur] && snapU.cells[ur][uc]) || {}));
              pRow.push(pf);
              var uf = JSON.parse(JSON.stringify(pf));
              if (uf.backgroundColor && !uf.backgroundColorStyle) uf.backgroundColorStyle = { rgbColor: uf.backgroundColor };
              if (uf.textFormat && uf.textFormat.foregroundColor && !uf.textFormat.foregroundColorStyle) uf.textFormat.foregroundColorStyle = { rgbColor: uf.textFormat.foregroundColor };
              uVals.push({ userEnteredFormat: uf });
            }
            prevCells.push(pRow);
            undoRows.push({ values: uVals });
          }
          undoRequests.unshift({
            updateCells: {
              range: parsedRg.gridRange,
              rows: undoRows,
              fields: fields.join(",")
            }
          });

          (function(rgInfo, cFmt, prev, clearBg) {
            snapshotMutators.push(function() {
              var snap = state.sheetSnapshot[sheetName];
              if (!snap || !snap.cells) return;
              for (var r = rgInfo.r1; r <= Math.min(rgInfo.r2, maxRow0); r++) {
                for (var c = rgInfo.c1; c <= Math.min(rgInfo.c2, maxCol0); c++) {
                  var cur = snap.cells[r][c] || {};
                  if (cFmt.backgroundColorStyle) cur.backgroundColorStyle = cFmt.backgroundColorStyle;
                  else if (clearBg) { delete cur.backgroundColorStyle; delete cur.backgroundColor; }
                  if (cFmt.horizontalAlignment) cur.horizontalAlignment = cFmt.horizontalAlignment;
                  if (cFmt.verticalAlignment) cur.verticalAlignment = cFmt.verticalAlignment;
                  if (cFmt.wrapStrategy) cur.wrapStrategy = cFmt.wrapStrategy;
                  if (cFmt.numberFormat) cur.numberFormat = cFmt.numberFormat;
                  if (cFmt.textFormat) {
                    cur.textFormat = Object.assign({}, cur.textFormat || {}, cFmt.textFormat);
                  }
                  snap.cells[r][c] = cur;
                }
              }
            });
            undoSnapshotMutators.push(function() {
              var snap = state.sheetSnapshot[sheetName];
              if (!snap || !snap.cells) return;
              for (var r = rgInfo.r1; r <= Math.min(rgInfo.r2, maxRow0); r++) {
                for (var c = rgInfo.c1; c <= Math.min(rgInfo.c2, maxCol0); c++) {
                  snap.cells[r][c] = JSON.parse(JSON.stringify(prev[r - rgInfo.r1][c - rgInfo.c1]));
                }
              }
            });
          })(parsedRg, cellFmt, prevCells, bgClear);
        }

        if (op.borders !== undefined) {
          var bOff = (op.borders === false || op.borders === "none" || op.borders === "なし");
          var bSolid = { style: "SOLID", width: 1, colorStyle: { rgbColor: { red: 0.6196, green: 0.6196, blue: 0.6196 } } };
          var bNone = { style: "NONE" };
          var bReq = { range: parsedRg.gridRange };
          if (bOff) {
            bReq.top = bNone; bReq.bottom = bNone; bReq.left = bNone; bReq.right = bNone;
            bReq.innerHorizontal = bNone; bReq.innerVertical = bNone;
          } else if (op.borders === "outer") {
            bReq.top = bSolid; bReq.bottom = bSolid; bReq.left = bSolid; bReq.right = bSolid;
          } else {
            bReq.top = bSolid; bReq.bottom = bSolid; bReq.left = bSolid; bReq.right = bSolid;
            bReq.innerHorizontal = bSolid; bReq.innerVertical = bSolid;
          }
          // 取り消しは、書く前のセルの罫線をセルごとに書き戻す（写しが無い・範囲の外なら GAS の道に任せる）
          var snapB = state.sheetSnapshot[sheetName];
          if (!snapB || !snapB.cells || !snapB.cells.length || parsedRg.r2 > maxRow0 || parsedRg.c2 > maxCol0) return null;
          var bRows = [];
          for (var brr = parsedRg.r1; brr <= parsedRg.r2; brr++) {
            var bVals = [];
            for (var bcc = parsedRg.c1; bcc <= parsedRg.c2; bcc++) {
              var bPrev = (snapB.cells[brr] && snapB.cells[brr][bcc] && snapB.cells[brr][bcc].borders) || null;
              bVals.push({ userEnteredFormat: bPrev ? { borders: JSON.parse(JSON.stringify(bPrev)) } : {} });
            }
            bRows.push({ values: bVals });
          }
          requests.push({ updateBorders: bReq });
          undoRequests.unshift({
            updateCells: {
              range: parsedRg.gridRange,
              rows: bRows,
              fields: "userEnteredFormat.borders"
            }
          });
          // 罫線は写しに書き足せないので、書いた後・戻した後に写しを取り直す（次の取り消しが古い罫線で戻さないように）
          snapshotMutators.push(function() { prefetchSheetSnapshot(sheetName); });
          undoSnapshotMutators.push(function() { prefetchSheetSnapshot(sheetName); });
          did.push("borders");
        }

        if (op.merge !== undefined) {
          if (op.merge) {
            requests.push({ mergeCells: { range: parsedRg.gridRange, mergeType: "MERGE_ALL" } });
            undoRequests.unshift({ unmergeCells: { range: parsedRg.gridRange } });
            did.push("merge");
          } else {
            requests.push({ unmergeCells: { range: parsedRg.gridRange } });
            undoRequests.unshift({ mergeCells: { range: parsedRg.gridRange, mergeType: "MERGE_ALL" } });
            did.push("unmerge");
          }
        }

        if (!did.length) return null;

        changed.push(sheetName + "!" + parsedRg.a1 + " " + did.join("・"));
        whatList.push(parsedRg.a1 + (bgClear ? "（bg.clear）" : "（format）"));
      } else if (op.shelf === "freeze" || op.shelf === "unfreeze") {
        var fRows = op.shelf === "unfreeze" ? 0 : (op.rows !== undefined ? Number(op.rows) : ((state.table && state.table.header_row) || 1));
        var fCols = op.shelf === "unfreeze" ? 0 : (op.cols !== undefined ? Number(op.cols) : 0);
        requests.push({
          updateSheetProperties: {
            properties: {
              sheetId: sheetId,
              gridProperties: { frozenRowCount: fRows, frozenColumnCount: fCols }
            },
            fields: "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
          }
        });
        var snapF = state.sheetSnapshot[sheetName] || { frozenRows: 0, frozenCols: 0 };
        undoRequests.unshift({
          updateSheetProperties: {
            properties: {
              sheetId: sheetId,
              gridProperties: { frozenRowCount: snapF.frozenRows || 0, frozenColumnCount: snapF.frozenCols || 0 }
            },
            fields: "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
          }
        });
        changed.push(sheetName + "!" + (op.shelf === "unfreeze" ? "固定解除" : ("固定 " + fRows + "行")));
        whatList.push(op.shelf);
      } else if (op.shelf === "width") {
        if (op.all_sheets || op.auto_rows) return null;
        var wDid = [];
        if (op.cols && typeof op.cols === "object") {
          var ckList = Object.keys(op.cols);
          for (var cki = 0; cki < ckList.length; cki++) {
            var cLetter = resolveColLetterFromTable(ckList[cki]);
            var cIdx = colToNum0(cLetter);
            if (cIdx < 0) return null;
            requests.push({
              updateDimensionProperties: {
                range: { sheetId: sheetId, dimension: "COLUMNS", startIndex: cIdx, endIndex: cIdx + 1 },
                properties: { pixelSize: Number(op.cols[ckList[cki]]) },
                fields: "pixelSize"
              }
            });
            wDid.push(ckList[cki] + "列");
          }
        }
        if (op.col && op.width) {
          var singleCol = resolveColLetterFromTable(op.col);
          var singleIdx = colToNum0(singleCol);
          if (singleIdx < 0) return null;
          requests.push({
            updateDimensionProperties: {
              range: { sheetId: sheetId, dimension: "COLUMNS", startIndex: singleIdx, endIndex: singleIdx + 1 },
              properties: { pixelSize: Number(op.width) },
              fields: "pixelSize"
            }
          });
          wDid.push(op.col + "列");
        }
        if (op.rows && typeof op.rows === "object") {
          var rkList = Object.keys(op.rows);
          for (var rki = 0; rki < rkList.length; rki++) {
            var rIdx = parseInt(rkList[rki], 10) - 1;
            if (isNaN(rIdx) || rIdx < 0) return null;
            requests.push({
              updateDimensionProperties: {
                range: { sheetId: sheetId, dimension: "ROWS", startIndex: rIdx, endIndex: rIdx + 1 },
                properties: { pixelSize: Number(op.rows[rkList[rki]]) },
                fields: "pixelSize"
              }
            });
            wDid.push(rkList[rki] + "行");
          }
        }
        if (Array.isArray(op.auto) && op.auto.length) {
          for (var ai = 0; ai < op.auto.length; ai++) {
            var autoCol = resolveColLetterFromTable(op.auto[ai]);
            var autoIdx = colToNum0(autoCol);
            if (autoIdx < 0) return null;
            requests.push({
              autoResizeDimensions: {
                dimensions: { sheetId: sheetId, dimension: "COLUMNS", startIndex: autoIdx, endIndex: autoIdx + 1 }
              }
            });
            wDid.push(op.auto[ai] + "列(自動)");
          }
        }
        if (!wDid.length) return null;
        changed.push(sheetName + "!" + wDid.join("・") + " 幅・高さを変更");
        whatList.push("width");
      } else if (op.shelf === "format.negred") {
        var nrUnit = String(op.unit || "none").toLowerCase();
        var nrBase = nrUnit === "yen" ? "¥#,##0" : nrUnit === "thousand" ? "#,##0," : nrUnit === "million" ? "#,##0,," : "#,##0";
        var nrNeg = (op.triangle ? '"▲"' : "-") + nrBase;
        var nrFmt = nrBase + ";[Red]" + nrNeg;
        var nrRanges = [];
        if (op.col) {
          var nrColL = resolveColLetterFromTable(op.col);
          if (!nrColL || !state.table || !state.table.data) return null;
          var nrDm = String(state.table.data).match(/^([0-9]+)-([0-9]+)$/);
          if (!nrDm) return null;
          nrRanges.push(nrColL + nrDm[1] + ":" + nrColL + (state.table.total_row || nrDm[2]));
        } else if (op.range) {
          nrRanges.push(String(op.range).trim());
        } else if (state.table && Array.isArray(state.table.columns) && state.table.data) {
          var nrDm2 = String(state.table.data).match(/^([0-9]+)-([0-9]+)$/);
          if (!nrDm2) return null;
          var nrEnd = state.table.total_row || nrDm2[2];
          for (var nci = 0; nci < state.table.columns.length; nci++) {
            var nCol = state.table.columns[nci];
            if (nCol && nCol.number && !/^(?:no\.?|番号|項番|id)$/i.test(String(nCol.name || "").trim())) {
              nrRanges.push(nCol.col + nrDm2[1] + ":" + nCol.col + nrEnd);
            }
          }
        }
        if (!nrRanges.length) return null;
        var snapNr = state.sheetSnapshot[sheetName];
        for (var nri = 0; nri < nrRanges.length; nri++) {
          var nrRg = parseSimpleA1Range(nrRanges[nri], sheetId);
          if (!nrRg || !snapNr || !snapNr.cells || nrRg.r2 > maxRow0 || nrRg.c2 > maxCol0) return null;
          requests.push({
            repeatCell: {
              range: nrRg.gridRange,
              cell: { userEnteredFormat: { numberFormat: { type: "NUMBER", pattern: nrFmt } } },
              fields: "userEnteredFormat.numberFormat"
            }
          });
          var nrUndoRows = [];
          for (var nur = nrRg.r1; nur <= nrRg.r2; nur++) {
            var nrUV = [];
            for (var nuc = nrRg.c1; nuc <= nrRg.c2; nuc++) {
              var npf = (snapNr.cells[nur] && snapNr.cells[nur][nuc]) || {};
              nrUV.push({ userEnteredFormat: npf.numberFormat ? { numberFormat: JSON.parse(JSON.stringify(npf.numberFormat)) } : {} });
            }
            nrUndoRows.push({ values: nrUV });
          }
          undoRequests.unshift({ updateCells: { range: nrRg.gridRange, rows: nrUndoRows, fields: "userEnteredFormat.numberFormat" } });
        }
        changed.push(sheetName + "!" + nrRanges.join("・") + " 数値表示(" + nrFmt + ")");
        whatList.push("format.negred");
      } else if (op.shelf === "font.unify") {
        if (op.all_sheets || !state.table || !state.table.last_col || !state.table.data) return null;
        var fuDm = String(state.table.data).match(/^([0-9]+)-([0-9]+)$/);
        if (!fuDm) return null;
        var fuEndR = Number(state.table.total_row || fuDm[2]);
        var fuA1 = "A1:" + state.table.last_col + fuEndR;
        var fuRg = parseSimpleA1Range(fuA1, sheetId);
        var snapFu = state.sheetSnapshot[sheetName];
        if (!fuRg || !snapFu || !snapFu.cells || fuRg.r2 > maxRow0 || fuRg.c2 > maxCol0) return null;
        var fuFont = String(op.font || "Noto Sans JP").trim() || "Noto Sans JP";
        var fuSz = op.size !== undefined ? Number(op.size) : 0;
        var fuTf = { fontFamily: fuFont };
        var fuFields = ["userEnteredFormat.textFormat.fontFamily"];
        if (fuSz > 0) {
          fuTf.fontSize = fuSz;
          fuFields.push("userEnteredFormat.textFormat.fontSize");
        }
        requests.push({ repeatCell: { range: fuRg.gridRange, cell: { userEnteredFormat: { textFormat: fuTf } }, fields: fuFields.join(",") } });
        var fuUndoRows = [];
        for (var fur = fuRg.r1; fur <= fuRg.r2; fur++) {
          var fuUV = [];
          for (var fuc = fuRg.c1; fuc <= fuRg.c2; fuc++) {
            var fpf = (snapFu.cells[fur] && snapFu.cells[fur][fuc]) || {};
            fuUV.push({ userEnteredFormat: fpf.textFormat ? { textFormat: JSON.parse(JSON.stringify(fpf.textFormat)) } : {} });
          }
          fuUndoRows.push({ values: fuUV });
        }
        undoRequests.unshift({ updateCells: { range: fuRg.gridRange, rows: fuUndoRows, fields: fuFields.join(",") } });
        changed.push(sheetName + "! フォント「" + fuFont + "」に統一");
        whatList.push("font.unify");
      } else if (op.shelf === "clear.format" || op.shelf === "clear.values" || op.shelf === "clear.all") {
        if (op.shelf !== "clear.format" && (!els.chkOk || !els.chkOk.checked)) return null;
        if (op.shelf === "clear.values" && op.only === "constants") return null;
        var clRg = parseSimpleA1Range(String(op.range || ""), sheetId);
        if (!clRg) return null;
        var snapCl = state.sheetSnapshot[sheetName];
        var canSnapCl = !!(snapCl && snapCl.cells && clRg.r2 <= maxRow0 && clRg.c2 <= maxCol0);
        if (op.shelf === "clear.format") {
          requests.push({ repeatCell: { range: clRg.gridRange, cell: {}, fields: "userEnteredFormat" } });
          if (canSnapCl) {
            var cfUndoRows = [];
            for (var cfr = clRg.r1; cfr <= clRg.r2; cfr++) {
              var cfUV = [];
              for (var cfc = clRg.c1; cfc <= clRg.c2; cfc++) {
                cfUV.push({ userEnteredFormat: JSON.parse(JSON.stringify((snapCl.cells[cfr] && snapCl.cells[cfr][cfc]) || {})) });
              }
              cfUndoRows.push({ values: cfUV });
            }
            undoRequests.unshift({ updateCells: { range: clRg.gridRange, rows: cfUndoRows, fields: "userEnteredFormat" } });
          }
          changed.push(sheetName + "!" + clRg.a1 + " 書式クリア");
        } else if (op.shelf === "clear.values") {
          requests.push({ updateCells: { range: clRg.gridRange, fields: "userEnteredValue" } });
          if (canSnapCl && snapCl.vals) {
            var cvUndoRows = [];
            for (var cvr = clRg.r1; cvr <= clRg.r2; cvr++) {
              var cvUV = [];
              for (var cvc = clRg.c1; cvc <= clRg.c2; cvc++) {
                var oldVal = snapCl.vals[num0ToCol(cvc) + (cvr + 1)];
                cvUV.push(oldVal ? { userEnteredValue: oldVal } : {});
              }
              cvUndoRows.push({ values: cvUV });
            }
            undoRequests.unshift({ updateCells: { range: clRg.gridRange, rows: cvUndoRows, fields: "userEnteredValue" } });
          }
          changed.push(sheetName + "!" + clRg.a1 + " 値クリア");
        } else {
          requests.push({ updateCells: { range: clRg.gridRange, fields: "userEnteredValue,userEnteredFormat" } });
          if (canSnapCl && snapCl.vals) {
            var caUndoRows = [];
            for (var car = clRg.r1; car <= clRg.r2; car++) {
              var caUV = [];
              for (var cac = clRg.c1; cac <= clRg.c2; cac++) {
                var oldAv = snapCl.vals[num0ToCol(cac) + (car + 1)];
                var oldAf = JSON.parse(JSON.stringify((snapCl.cells[car] && snapCl.cells[car][cac]) || {}));
                var caObj = { userEnteredFormat: oldAf };
                if (oldAv) caObj.userEnteredValue = oldAv;
                caUV.push(caObj);
              }
              caUndoRows.push({ values: caUV });
            }
            undoRequests.unshift({ updateCells: { range: clRg.gridRange, rows: caUndoRows, fields: "userEnteredValue,userEnteredFormat" } });
          }
          changed.push(sheetName + "!" + clRg.a1 + " すべてクリア");
        }
        whatList.push(op.shelf);
      } else if (op.shelf === "write") {
        if (op.tsv !== undefined || !op.cells || typeof op.cells !== "object" || Array.isArray(op.cells)) return null;
        var wKeys = Object.keys(op.cells);
        if (!wKeys.length) return null;
        // 書く前の値が写しで分かるセルだけ直結で書く。空でないセルの上書きは GAS の道（上書きの止め・控えあり）に任せる
        var wSnap = state.sheetSnapshot[sheetName];
        if (!wSnap || !wSnap.vals) return null;
        for (var wi = 0; wi < wKeys.length; wi++) {
          var cellRg = parseSimpleA1Range(wKeys[wi], sheetId);
          if (!cellRg || cellRg.r1 !== cellRg.r2 || cellRg.c1 !== cellRg.c2) return null;
          if (cellRg.r1 > maxRow0 || cellRg.c1 > maxCol0) return null;
          var wPrev = wSnap.vals[cellRg.a1];
          if (wPrev && !(els.chkOk && els.chkOk.checked)) return null;
          undoRequests.unshift({
            updateCells: {
              start: { sheetId: sheetId, rowIndex: cellRg.r1, columnIndex: cellRg.c1 },
              rows: [{ values: [wPrev ? { userEnteredValue: wPrev } : {}] }],
              fields: "userEnteredValue"
            }
          });
          (function(key, newV, oldV) {
            snapshotMutators.push(function() { var sn = state.sheetSnapshot[sheetName]; if (sn && sn.vals) sn.vals[key] = newV; });
            undoSnapshotMutators.push(function() { var sn = state.sheetSnapshot[sheetName]; if (sn && sn.vals) { if (oldV) sn.vals[key] = oldV; else delete sn.vals[key]; } });
          })(cellRg.a1, toUserEnteredValue(op.cells[wKeys[wi]]), wPrev);
          requests.push({
            updateCells: {
              start: { sheetId: sheetId, rowIndex: cellRg.r1, columnIndex: cellRg.c1 },
              rows: [{ values: [{ userEnteredValue: toUserEnteredValue(op.cells[wKeys[wi]]) }] }],
              fields: "userEnteredValue"
            }
          });
        }
        changed.push(sheetName + "!" + wKeys.slice(0, 3).join(",") + (wKeys.length > 3 ? "…" : "") + " 書き込み");
        whatList.push("write");
      } else if (op.shelf === "filter.off") {
        requests.push({ clearBasicFilter: { sheetId: sheetId } });
        changed.push(sheetName + " フィルター解除");
        whatList.push("filter.off");
      } else if (op.shelf === "filter.on") {
        var fA1 = op.range ? String(op.range) : resolveTableRangeStr(true);
        var fRg = parseSimpleA1Range(fA1, sheetId);
        if (!fRg) return null;
        requests.push({ setBasicFilter: { filter: { range: fRg.gridRange } } });
        undoRequests.unshift({ clearBasicFilter: { sheetId: sheetId } });
        changed.push(sheetName + "!" + fRg.a1 + " フィルター設定");
        whatList.push("filter.on");
      } else if (op.shelf === "sort") {
        if (op.where || op.filter || (op.cols && op.cols.length) || !op.col) return null;
        var sortColLetter = resolveColLetterFromTable(op.col);
        var sortColIdx = colToNum0(sortColLetter);
        if (sortColIdx < 0) return null;
        var sA1 = op.range ? String(op.range) : resolveTableRangeStr(false);
        var sRg = parseSimpleA1Range(sA1, sheetId);
        if (!sRg) return null;
        requests.push({
          sortRange: {
            range: sRg.gridRange,
            sortSpecs: [{ dimensionIndex: sortColIdx, sortOrder: op.desc ? "DESCENDING" : "ASCENDING" }]
          }
        });
        var snapS = state.sheetSnapshot[sheetName];
        if (snapS && snapS.vals && snapS.cells && sRg.r2 <= maxRow0 && sRg.c2 <= maxCol0) {
          var sUndoRows = [];
          for (var sr = sRg.r1; sr <= sRg.r2; sr++) {
            var sUV = [];
            for (var sc = sRg.c1; sc <= sRg.c2; sc++) {
              var oldSv = snapS.vals[num0ToCol(sc) + (sr + 1)];
              var oldSf = JSON.parse(JSON.stringify((snapS.cells[sr] && snapS.cells[sr][sc]) || {}));
              var cellObj = { userEnteredFormat: oldSf };
              if (oldSv) cellObj.userEnteredValue = oldSv;
              sUV.push(cellObj);
            }
            sUndoRows.push({ values: sUV });
          }
          undoRequests.unshift({ updateCells: { range: sRg.gridRange, rows: sUndoRows, fields: "userEnteredValue,userEnteredFormat" } });
        }
        changed.push(sheetName + "!" + sRg.a1 + " " + op.col + "列で" + (op.desc ? "降順" : "昇順") + "並べ替え");
        whatList.push("sort");
      } else if (op.shelf === "rows.insert" || op.shelf === "cols.insert") {
        var isColIns = op.shelf === "cols.insert";
        if (op.at === undefined || op.at === null || op.at === "") return null;
        var insCnt = parseInt(op.count || 1, 10);
        if (!insCnt || insCnt < 1 || insCnt > 50) return null;
        var insIdx0 = isColIns ? colToNum0(resolveColLetterFromTable(op.at)) : (parseInt(op.at, 10) - 1);
        if (isNaN(insIdx0) || insIdx0 < 0) return null;
        var insDim = isColIns ? "COLUMNS" : "ROWS";
        requests.push({
          insertDimension: {
            range: { sheetId: sheetId, dimension: insDim, startIndex: insIdx0, endIndex: insIdx0 + insCnt },
            inheritFromBefore: insIdx0 > 0
          }
        });
        undoRequests.unshift({
          deleteDimension: {
            range: { sheetId: sheetId, dimension: insDim, startIndex: insIdx0, endIndex: insIdx0 + insCnt }
          }
        });
        snapshotMutators.push(function() { prefetchSheetSnapshot(sheetName); });
        undoSnapshotMutators.push(function() { prefetchSheetSnapshot(sheetName); });
        changed.push(sheetName + "!" + op.at + (isColIns ? "列" : "行目") + "の前に " + insCnt + (isColIns ? " 列" : " 行") + "挿入");
        whatList.push(op.shelf);
      } else if (op.shelf === "banding.add" || op.shelf === "banding.remove") {
        var bSnap = state.sheetSnapshot[sheetName];
        if (!bSnap || !Array.isArray(bSnap.bandedRangeIds)) return null;
        var oldBandIds = bSnap.bandedRangeIds.slice();
        if (op.shelf === "banding.remove" && !oldBandIds.length) return null;
        for (var bdi = 0; bdi < oldBandIds.length; bdi++) {
          requests.push({ deleteBanding: { bandedRangeId: oldBandIds[bdi] } });
        }
        if (op.shelf === "banding.add") {
          var bA1 = op.range ? String(op.range) : resolveTableRangeStr(true);
          var bRg = parseSimpleA1Range(bA1, sheetId);
          if (!bRg) return null;
          var themeKey = String(op.theme || "gray").toLowerCase();
          var pal = BANDING_THEMES[themeKey] || BANDING_THEMES.gray;
          var addReqIdx = requests.length;
          requests.push({
            addBanding: {
              bandedRange: {
                range: bRg.gridRange,
                rowProperties: {
                  headerColorStyle: { rgbColor: parseColorToRgbObj(pal.header) },
                  firstBandColorStyle: { rgbColor: parseColorToRgbObj(pal.first) },
                  secondBandColorStyle: { rgbColor: parseColorToRgbObj(pal.second) }
                }
              }
            }
          });
          (function(rIdx, sName) {
            snapshotMutators.push(function(resJson) {
              var sp = state.sheetSnapshot[sName];
              if (!sp) return;
              var newIds = [];
              if (resJson && Array.isArray(resJson.replies) && resJson.replies[rIdx] &&
                  resJson.replies[rIdx].addBanding && resJson.replies[rIdx].addBanding.bandedRange) {
                newIds.push(resJson.replies[rIdx].addBanding.bandedRange.bandedRangeId);
              }
              sp.bandedRangeIds = newIds;
            });
          })(addReqIdx, sheetName);
          changed.push(sheetName + "!" + bRg.a1 + " 交互背景色(" + themeKey + ")");
        } else {
          (function(sName) {
            snapshotMutators.push(function() {
              if (state.sheetSnapshot[sName]) state.sheetSnapshot[sName].bandedRangeIds = [];
            });
          })(sheetName);
          changed.push(sheetName + " 交互背景色解除");
        }
        whatList.push(op.shelf);
      } else if (op.shelf === "sheet.color") {
        var tcName = op.name || sheetName;
        var tcSid = state.sheetIdMap[tcName];
        if (typeof tcSid !== "number") return null;
        var isClearTab = (op.color === undefined || op.color === null || op.color === "" ||
          op.color === "なし" || /^(none|clear)$/i.test(String(op.color).trim()));
        var tabStyle = null;
        if (!isClearTab) {
          var tcRgb = parseColorToRgbObj(op.color);
          if (!tcRgb) return null;
          tabStyle = { rgbColor: tcRgb };
        }
        requests.push({
          updateSheetProperties: {
            properties: { sheetId: tcSid, tabColorStyle: tabStyle },
            fields: "tabColorStyle"
          }
        });
        changed.push(tcName + " タブ色" + (isClearTab ? "解除" : "変更"));
        whatList.push("sheet.color");
      } else if (op.shelf === "sheet.rename") {
        if (!op.to) return null;
        var rnOld = op.name || sheetName;
        var rnNew = String(op.to).trim();
        var rnSid = state.sheetIdMap[rnOld];
        if (!rnNew || typeof rnSid !== "number") return null;
        requests.push({
          updateSheetProperties: {
            properties: { sheetId: rnSid, title: rnNew },
            fields: "title"
          }
        });
        undoRequests.unshift({
          updateSheetProperties: {
            properties: { sheetId: rnSid, title: rnOld },
            fields: "title"
          }
        });
        (function(oName, nName, sid) {
          snapshotMutators.push(function() {
            delete state.sheetIdMap[oName];
            state.sheetIdMap[nName] = sid;
            if (state.sheetDimsMap[oName]) {
              state.sheetDimsMap[nName] = state.sheetDimsMap[oName];
              delete state.sheetDimsMap[oName];
            }
            if (Array.isArray(state.sheets)) {
              for (var si = 0; si < state.sheets.length; si++) {
                if (state.sheets[si] === oName) state.sheets[si] = nName;
              }
            }
            if (state.curSheet === oName) state.curSheet = nName;
            if (state.target && state.target.sheet === oName) state.target.sheet = nName;
            if (state.sheetSnapshot[oName]) {
              state.sheetSnapshot[nName] = state.sheetSnapshot[oName];
              delete state.sheetSnapshot[oName];
            }
            syncSheetSelects();
            updateInfoLabel();
          });
          undoSnapshotMutators.push(function() {
            delete state.sheetIdMap[nName];
            state.sheetIdMap[oName] = sid;
            if (state.sheetDimsMap[nName]) {
              state.sheetDimsMap[oName] = state.sheetDimsMap[nName];
              delete state.sheetDimsMap[nName];
            }
            if (Array.isArray(state.sheets)) {
              for (var si = 0; si < state.sheets.length; si++) {
                if (state.sheets[si] === nName) state.sheets[si] = oName;
              }
            }
            if (state.curSheet === nName) state.curSheet = oName;
            if (state.target && state.target.sheet === nName) state.target.sheet = oName;
            if (state.sheetSnapshot[nName]) {
              state.sheetSnapshot[oName] = state.sheetSnapshot[nName];
              delete state.sheetSnapshot[nName];
            }
            syncSheetSelects();
            updateInfoLabel();
          });
        })(rnOld, rnNew, rnSid);
        changed.push(rnOld + " → " + rnNew + " シート名変更");
        whatList.push("sheet.rename");
      } else if (op.shelf === "sheet.hide") {
        var hName = op.name || sheetName;
        var hSid = state.sheetIdMap[hName];
        if (typeof hSid !== "number" || !Array.isArray(state.sheets) || state.sheets.length <= 1) return null;
        requests.push({
          updateSheetProperties: {
            properties: { sheetId: hSid, hidden: true },
            fields: "hidden"
          }
        });
        undoRequests.unshift({
          updateSheetProperties: {
            properties: { sheetId: hSid, hidden: false },
            fields: "hidden"
          }
        });
        changed.push(hName + " 非表示");
        whatList.push("sheet.hide");
      } else if (op.shelf === "sheet.show") {
        if (!op.name) return null;
        var shSid = state.sheetIdMap[op.name];
        if (typeof shSid !== "number") return null;
        requests.push({
          updateSheetProperties: {
            properties: { sheetId: shSid, hidden: false },
            fields: "hidden"
          }
        });
        undoRequests.unshift({
          updateSheetProperties: {
            properties: { sheetId: shSid, hidden: true },
            fields: "hidden"
          }
        });
        changed.push(op.name + " 再表示");
        whatList.push("sheet.show");
      } else if (op.shelf === "sheet.gridlines") {
        if (op.all_sheets) return null;
        var snapG = state.sheetSnapshot[sheetName];
        if (op.show === undefined && !snapG) return null;
        var prevHideG = snapG ? !!snapG.hideGridlines : false;
        var nextHideG = (op.show === undefined) ? !prevHideG : !op.show;
        requests.push({
          updateSheetProperties: {
            properties: { sheetId: sheetId, gridProperties: { hideGridlines: nextHideG } },
            fields: "gridProperties.hideGridlines"
          }
        });
        if (snapG) {
          undoRequests.unshift({
            updateSheetProperties: {
              properties: { sheetId: sheetId, gridProperties: { hideGridlines: prevHideG } },
              fields: "gridProperties.hideGridlines"
            }
          });
          (function(sName, nHide, oHide) {
            snapshotMutators.push(function() {
              var sp = state.sheetSnapshot[sName];
              if (sp) sp.hideGridlines = nHide;
            });
            undoSnapshotMutators.push(function() {
              var sp = state.sheetSnapshot[sName];
              if (sp) sp.hideGridlines = oHide;
            });
          })(sheetName, nextHideG, prevHideG);
        }
        changed.push(sheetName + " 枠線" + (nextHideG ? "非表示" : "表示"));
        whatList.push("sheet.gridlines");
      } else if (op.shelf === "rows.hide" || op.shelf === "rows.show") {
        var rRaw = Array.isArray(op.rows) ? op.rows : (op.rows !== undefined ? [op.rows] : []);
        if (!rRaw.length) return null;
        var rSeen = {}, rNums = [];
        for (var rhi = 0; rhi < rRaw.length; rhi++) {
          var rn = parseInt(rRaw[rhi], 10);
          if (!rn || rn < 1) return null;
          if (!rSeen[rn]) { rSeen[rn] = 1; rNums.push(rn); }
        }
        if (!rNums.length) return null;
        rNums.sort(function(a, b) { return a - b; });
        var isHideR = op.shelf === "rows.hide";
        for (var rIdx0 = 0; rIdx0 < rNums.length; ) {
          var rStart = rNums[rIdx0], rEnd = rStart;
          while (rIdx0 + 1 < rNums.length && rNums[rIdx0 + 1] === rEnd + 1) rEnd = rNums[++rIdx0];
          requests.push({
            updateDimensionProperties: {
              range: { sheetId: sheetId, dimension: "ROWS", startIndex: rStart - 1, endIndex: rEnd },
              properties: { hiddenByUser: isHideR },
              fields: "hiddenByUser"
            }
          });
          undoRequests.unshift({
            updateDimensionProperties: {
              range: { sheetId: sheetId, dimension: "ROWS", startIndex: rStart - 1, endIndex: rEnd },
              properties: { hiddenByUser: !isHideR },
              fields: "hiddenByUser"
            }
          });
          rIdx0++;
        }
        changed.push(sheetName + "!" + rNums.join("・") + "行目 " + (isHideR ? "非表示" : "再表示"));
        whatList.push(op.shelf);
      } else if (op.shelf === "cols.hide" || op.shelf === "cols.show") {
        var cRaw = Array.isArray(op.cols) ? op.cols : (op.cols !== undefined ? [op.cols] : []);
        if (!cRaw.length) return null;
        var cSeen = {}, cNums = [];
        for (var chi2 = 0; chi2 < cRaw.length; chi2++) {
          var cLet = typeof cRaw[chi2] === "number" ? num0ToCol(cRaw[chi2] - 1) : resolveColLetterFromTable(cRaw[chi2]);
          var c0Idx = colToNum0(cLet);
          if (c0Idx < 0) return null;
          if (!cSeen[c0Idx]) { cSeen[c0Idx] = 1; cNums.push(c0Idx); }
        }
        if (!cNums.length) return null;
        cNums.sort(function(a, b) { return a - b; });
        var isHideC = op.shelf === "cols.hide";
        for (var cIdx0 = 0; cIdx0 < cNums.length; ) {
          var cStart = cNums[cIdx0], cEnd = cStart;
          while (cIdx0 + 1 < cNums.length && cNums[cIdx0 + 1] === cEnd + 1) cEnd = cNums[++cIdx0];
          requests.push({
            updateDimensionProperties: {
              range: { sheetId: sheetId, dimension: "COLUMNS", startIndex: cStart, endIndex: cEnd + 1 },
              properties: { hiddenByUser: isHideC },
              fields: "hiddenByUser"
            }
          });
          undoRequests.unshift({
            updateDimensionProperties: {
              range: { sheetId: sheetId, dimension: "COLUMNS", startIndex: cStart, endIndex: cEnd + 1 },
              properties: { hiddenByUser: !isHideC },
              fields: "hiddenByUser"
            }
          });
          cIdx0++;
        }
        changed.push(sheetName + "!" + cRaw.join("・") + "列 " + (isHideC ? "非表示" : "再表示"));
        whatList.push(op.shelf);
      } else if (op.shelf === "note.set" || op.shelf === "note.clear") {
        if (!op.range) return null;
        if (op.shelf === "note.set" && (op.text === undefined || op.text === null || op.text === "")) return null;
        var noteRg = parseSimpleA1Range(String(op.range), sheetId);
        if (!noteRg) return null;
        requests.push({
          repeatCell: {
            range: noteRg.gridRange,
            cell: op.shelf === "note.set" ? { note: String(op.text) } : {},
            fields: "note"
          }
        });
        changed.push(sheetName + "!" + noteRg.a1 + (op.shelf === "note.set" ? " メモ設定" : " メモ消去"));
        whatList.push(op.shelf);
      } else if (op.shelf === "validation.clear") {
        if (!op.range) return null;
        var vcRg = parseSimpleA1Range(String(op.range), sheetId);
        if (!vcRg) return null;
        requests.push({ setDataValidation: { range: vcRg.gridRange } });
        changed.push(sheetName + "!" + vcRg.a1 + " 入力規則解除");
        whatList.push("validation.clear");
      } else if (op.shelf === "api") {
        if (!els.chkOk || !els.chkOk.checked) return null;
        if (!Array.isArray(op.requests) || !op.requests.length) return null;
        for (var apiIdx = 0; apiIdx < op.requests.length; apiIdx++) {
          requests.push(op.requests[apiIdx]);
        }
        changed.push(sheetName + " API直接操作(" + op.requests.length + "件)");
        whatList.push("api");
      } else {
        return null;
      }
    }

    if (!requests.length) return null;
    return {
      requests: requests,
      undoRequests: undoRequests,
      changed: changed,
      what: whatList.join("・"),
      applySnapshot: function(resJson) {
        for (var m = 0; m < snapshotMutators.length; m++) snapshotMutators[m](resJson);
      },
      restoreSnapshot: function() {
        for (var u = 0; u < undoSnapshotMutators.length; u++) undoSnapshotMutators[u]();
      }
    };
  }

  function tryDirectSheetsApi(ops, label, isFromAsk, fallbackFn, extraOpts) {
    if (typeof fetch !== "function") return false;
    var sheetName = state.curSheet || (state.target && state.target.sheet) || "";
    var plan = buildDirectBatchUpdate(ops, sheetName);
    if (!plan) {
      // 直結の道に乗れなかった理由が写しの失敗なら、会話の欄に 1 回だけ出す（黙って遅い道に回らない）
      if (state.prefetchError && !state.prefetchErrorShown) {
        state.prefetchErrorShown = true;
        appendLog(els.chatLog, "is-err", "⚠ 直結の道（0.3 秒）が使えません", state.prefetchError + "（GAS の道で撃ちます）");
      }
      return false;
    }

    if (state.busy) {
      appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
      return true;
    }
    var switchChat = !(extraOpts && extraOpts.switchToChat === false);
    setBusy(true, "実行中…");
    if (switchChat) switchTab("chat");

    var t0 = performance.now();
    var url = "https://sheets.googleapis.com/v4/spreadsheets/" + encodeURIComponent(state.target.id) + ":batchUpdate";
    fetch(url, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + state.oauthToken,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ requests: plan.requests })
    })
      .then(function(res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function(resJson) {
        var wallMs = performance.now() - t0;
        setBusy(false);
        plan.applySnapshot(resJson);
        if (plan.undoRequests && plan.undoRequests.length) {
          state.directUndoStack.push({
            sheet: sheetName,
            what: plan.what || "format",
            requests: plan.undoRequests,
            restoreSnapshot: plan.restoreSnapshot
          });
        } else {
          // 戻しを持たない直結操作を挟んだら、過去の戻し履歴が誤爆しないよう空にする
          state.directUndoStack = [];
        }
        var needSnapReload = ops.some(function(o) {
          return /^(clear\.|sort$)/.test(String((o && o.shelf) || ""));
        });
        var lines = [];
        if (isFromAsk) {
          lines.push("[棚ヒット] " + formatOpsShort(ops));
        }
        lines.push("対象: " + (state.target.name || "(名前なし)") + " › " + sheetName);
        lines.push("直した所: " + plan.changed.slice(0, 2).join(" ／ "));
        lines.push("控えなし（backup=OFF）");
        checkNewErrorsAfterDirect(sheetName, ops, function(news) {
          if (news.length) lines.push("⚠ 新しいエラー: " + news.slice(0, 5).join("・") + (news.length > 5 ? " ほか " + (news.length - 5) + " 件" : "") + "（直前を取り消すで戻せます）");
          recordExecution(true, label, lines.join("\n"), wallMs, 0, switchChat, true);
          if (extraOpts && typeof extraOpts.onDirectDone === "function") {
            extraOpts.onDirectDone(wallMs);
          }
          if (needSnapReload) prefetchSheetSnapshot(state.curSheet || sheetName);
        });
      })
      .catch(function() {
        setBusy(false);
        if (fallbackFn) fallbackFn();
      });
    return true;
  }

  function tryDirectUndo(fallbackFn) {
    if (typeof fetch !== "function" || !state.oauthToken || !state.target.id || !state.directUndoStack.length) {
      return false;
    }
    if (state.busy) {
      appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
      return true;
    }
    var item = state.directUndoStack.pop();
    setBusy(true, "取り消し中…");
    switchTab("chat");

    var t0 = performance.now();
    var url = "https://sheets.googleapis.com/v4/spreadsheets/" + encodeURIComponent(state.target.id) + ":batchUpdate";
    fetch(url, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + state.oauthToken,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ requests: item.requests })
    })
      .then(function(res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function() {
        var wallMs = performance.now() - t0;
        setBusy(false);
        if (item.restoreSnapshot) item.restoreSnapshot();
        var body = [
          "対象: " + (state.target.name || "(名前なし)") + " › " + item.sheet,
          "戻した: " + item.what + " を取り消しました（直接API戻し）"
        ].join("\n");
        recordExecution(true, "直前を取り消す", body, wallMs, 0, true, true);
      })
      .catch(function() {
        setBusy(false);
        if (fallbackFn) fallbackFn();
      });
    return true;
  }

  function handlePostboxDone(doneItems) {
    if (!doneItems) return;
    var items = Array.isArray(doneItems) ? doneItems : [doneItems];
    var handled = 0;
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it || typeof it !== "object") continue;
      handled++;
      if (it.reqId) delete state.pendingPostboxIds[it.reqId];
      var ok = it.ok !== false;
      var label = it.ask || it.label || "郵便受けAI実行";
      var body = it.text || it.error || "";
      var gasMs = (typeof it.gasMs === "number") ? it.gasMs : undefined;
      if (it.kind === "mymacro") {
        appendLog(
          els.chatLog,
          ok ? "is-ok" : "is-err",
          "[" + (ok ? "✓" : "✗") + " 郵便受け AIマイマクロ] " + label,
          body + (gasMs !== undefined ? "\n(GAS " + (gasMs / 1000).toFixed(2) + "s)" : "")
        );
        if (ok && it.previewOnly && it.action === "reply") {
          applyQuickAiReplyResult(it);
          if (els.quickNote) els.quickNote.textContent = "💬 AI からマイマクロの返答が届きました";
        } else if (ok && it.previewOnly && it.code) {
          applyQuickAiPreviewResult(it);
          if (els.quickNote) els.quickNote.textContent = body || "✨ コード案ができました。内容を確認して「決定して保存」を押してください";
        } else if (ok && it.saved) {
          var sNm = it.newName || it.name || "";
          if (it.mode === "edit" && it.prevCode && sNm) quickSavePrevCode(sNm, it.prevCode);
          if (it.myId) state.quick.myId = it.myId;
          if (it.myUrl) state.quick.myUrl = it.myUrl;
          if (it.myStamp) state.quick.myStamp = it.myStamp;
          quickClearCodeCache();
          quickRememberLocal();
          updateSettingsMyMacroUI();
          if (els.quickNote) els.quickNote.textContent = body || "✨ AI マイマクロを保存しました";
          loadQuickList(false);
        } else if (ok && !it.saved && it.code) {
          (function(item) {
            var fnNm = (item.mode === "edit" && item.targetName) ? "comboQuickSaveFn" : "comboQuickAddFn";
            var argObj = (fnNm === "comboQuickSaveFn")
              ? { name: item.targetName, code: item.code, myId: item.myId || state.quick.myId || "" }
              : { code: item.code };
            callGas(fnNm, argObj, function(sRes) {
              if (!sRes || sRes.ok === false) {
                if (els.quickNote) els.quickNote.textContent = "⚠ " + ((sRes && sRes.error) || "マイマクロの保存に失敗しました");
                return;
              }
              var savedN = (sRes && (sRes.newName || sRes.name || (sRes.names && sRes.names[0]))) || item.targetName || "";
              if (item.mode === "edit" && item.prevCode && savedN) quickSavePrevCode(savedN, item.prevCode);
              if (sRes.myId) state.quick.myId = sRes.myId;
              if (sRes.myUrl) state.quick.myUrl = sRes.myUrl;
              if (sRes.myStamp) state.quick.myStamp = sRes.myStamp;
              quickClearCodeCache();
              quickRememberLocal();
              updateSettingsMyMacroUI();
              if (els.quickNote) els.quickNote.textContent = "✨ " + ((sRes && sRes.text) || "AI マイマクロを自動保存しました");
              loadQuickList(false);
            }, function(sErr) {
              if (els.quickNote) els.quickNote.textContent = "⚠ 自動保存に失敗: " + formatError(sErr);
            });
          })(it);
        } else {
          var samePending = !!(it.reqId && quickEditState.pendingReqId && quickEditState.pendingReqId === it.reqId);
          var modalOpen = !!(els.quickEditModal && els.quickEditModal.style.display !== "none");
          if (samePending || modalOpen) {
            if (samePending) quickEditState.pendingReqId = "";
            dropPendingQuickChat();
            quickEditState.chatHistory.push({ role: "err", text: "⚠ " + (it.error || body || "マイマクロ作成に失敗しました") });
            renderQuickChat();
            if (els.btnQuickAiSubmit) els.btnQuickAiSubmit.disabled = false;
            if (els.quickEditCode) els.quickEditCode.disabled = false;
            syncQuickSaveBtnState();
            if (els.quickEditStatus) els.quickEditStatus.textContent = "⚠ " + (it.error || body || "マイマクロ作成に失敗しました");
          }
          if (els.quickNote) els.quickNote.textContent = "⚠ " + (it.error || body || "マイマクロ作成に失敗しました");
        }
        continue;
      }
      appendLog(
        els.chatLog,
        ok ? "is-ok" : "is-err",
        "[" + (ok ? "✓" : "✗") + " 郵便受け] " + label,
        body + (gasMs !== undefined ? "\n(GAS " + (gasMs / 1000).toFixed(2) + "s)" : "")
      );
      if (it.table !== undefined) state.table = it.table;
    }
    if (handled > 0) {
      updateInfoLabel();
      updatePreview();
      els.postboxStatusLabel.textContent = "郵便受け: 完了結果 " + handled + "件を受信しました";
    }
  }

