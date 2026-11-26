  // ---- アクション実行 ----
  function runServerAction(opts) {
    if (state.busy) {
      appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
      return;
    }
    var switchChat = opts.switchToChat !== false;
    setBusy(true, opts.statusText || "実行中…");
    if (switchChat) switchTab("chat");

    var t0 = performance.now();
    callGas(
      opts.fnName,
      opts.payload,
      function(res) {
        var wallMs = performance.now() - t0;
        setBusy(false);

        if (!res || res.ok === false) {
          var errMsg = (res && (res.text || res.error)) || "実行に失敗しました";
          if (res && res.needs_ok && errMsg.indexOf("確認なし") === -1) {
            errMsg += "\n（「確認なし」にチェックを入れて再実行してください）";
          }
          recordExecution(false, opts.label, errMsg, wallMs, res && res.gasMs, opts.onError ? switchChat : true);
          if (opts.onError) opts.onError(errMsg);
          return;
        }

        if (opts.onSuccess) opts.onSuccess(res, wallMs);
        applyServerState(res, true);

        if (res.pendingPostbox) {
          if (res.reqId) state.pendingPostboxIds[res.reqId] = true;
          els.postboxStatusLabel.textContent = "郵便受け: 待機中 (ID: " + (res.reqId || "-") + ")";
          var pText = res.text || "郵便受けに依頼を置きました。PC側の watch が処理するまで待機します。";
          appendLog(els.chatLog, "is-info", "[郵便受け待機] " + opts.label, pText + "\n(" + formatTiming(wallMs, res.gasMs) + ")");
          appendLog(els.traceLog, "is-info", "[… " + opts.label + "] " + formatTiming(wallMs, res.gasMs), "");
          kickWatcher();
          schedulePoll(800);
          return;
        }

        if (!opts.silentSuccess) {
          recordExecution(true, opts.label, res.text || "完了", wallMs, res.gasMs, switchChat);
        }
      },
      function(err) {
        var wallMs = performance.now() - t0;
        setBusy(false);
        recordExecution(false, opts.label, formatError(err), wallMs, undefined, opts.onError ? switchChat : true);
        if (opts.onError) opts.onError(err);
      }
    );
  }

  function quickClientStamp() {
    var cc = state.quick && state.quick.codeCache;
    return (cc && cc.stamp && Object.keys(cc.map || {}).length) ? cc.stamp : "";
  }

  function onInit(silent) {
    runServerAction({
      fnName: "comboInit",
      payload: {
        targetId: state.target.id || "",
        sheet: state.curSheet || "",
        assumeActive: true,
        includeQuick: true,
        forceQuick: !silent,
        wantCodes: true,
        clientStamp: quickClientStamp()
      },
      label: "初期化 / 再読込",
      statusText: "読込中…",
      switchToChat: false,
      silentSuccess: !!silent,
      onSuccess: function(res) {
        if (res.postboxDone) handlePostboxDone(res.postboxDone);
        if (res && res.quick) applyQuickListRes(res.quick);
        else loadQuickList();
        loadLearned();
      }
    });
  }

  function onLook(sheetOverride) {
    var targetSheet = (typeof sheetOverride === "string") ? sheetOverride : (els.sheetSelect.value || state.curSheet || "");
    runServerAction({
      fnName: "comboLook",
      payload: {
        targetId: state.target.id || "",
        sheet: targetSheet,
        assumeActive: true
      },
      label: "読込 (comboLook)",
      statusText: "読込中…",
      switchToChat: false
    });
  }

  function hasSelectionPronoun(txt) {
    return /(ここ|このセル|選択範囲|選択セル|この行|この列|この範囲|今のセル)/.test(txt || "");
  }

  function requestLiveSelection(done) {
    if (typeof window === "undefined" || !window.top || window.top === window) {
      done(null);
      return;
    }
    var settled = false;
    var finish = function(res) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMsg);
      clearTimeout(timer);
      done(res);
    };
    var onMsg = function(ev) {
      var d = ev && ev.data;
      if (!d || d.type !== "GAS_COMBO_GET_SEL_DONE") return;
      finish(d.ok && d.range ? { range: String(d.range).trim(), sheet: String(d.sheet || "").trim() } : null);
    };
    window.addEventListener("message", onMsg);
    var timer = setTimeout(function() { finish(null); }, 250);
    try { window.top.postMessage({ type: "GAS_COMBO_GET_SEL" }, "*"); } catch (e) { finish(null); }
  }

  // 合い言葉つきの頼みは、いちばん外の窓が Google（シート・操作窓）のときだけ、その相手にだけ送る
  function bridgeTopOrigin() {
    try {
      var ao = location.ancestorOrigins;
      var top = ao && ao.length ? String(ao[ao.length - 1]) : "";
      if (top === "https://docs.google.com" || top === "https://script.google.com" ||
          top === "chrome-extension://mbkcmenmaeaiemdppphmbokhbfckpjhm") return top;
    } catch (e) {}
    return "";
  }
  function postToBridge(msg) {
    var to = bridgeTopOrigin();
    if (!to) throw new Error("bridge top is not Google");
    msg.token = (state.config && state.config.bridgeToken) || "";
    window.top.postMessage(msg, to);
  }

  function canUseDirectLocalAi() {
    if (typeof window === "undefined" || !window.top || window.top === window) return false;
    var mode = (els.cfgAiMode && els.cfgAiMode.value) || (state.config && state.config.aiMode) || "postbox";
    return mode === "postbox";
  }

  function getCurrentAiModel() {
    return (els.cfgAiModel && els.cfgAiModel.value) || (state.config && state.config.aiModel) || "";
  }

  function requestDirectAi(payload, done) {
    if (!canUseDirectLocalAi()) {
      done({ reachable: false });
      return;
    }
    var reqId = "dir_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
    var settled = false;
    var ackTimer = null;
    var resTimer = null;
    var finish = function(res) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMsg);
      clearTimeout(ackTimer);
      clearTimeout(resTimer);
      done(res);
    };
    var onMsg = function(ev) {
      var d = ev && ev.data;
      if (!d || d.reqId !== reqId) return;
      if (d.type === "GAS_COMBO_DIRECT_AI_ACK") {
        clearTimeout(ackTimer);
        clearTimeout(resTimer);
        resTimer = setTimeout(function() {
          finish({ reachable: true, ok: false, error: "ローカル AI が時間切れになりました" });
        }, 70000);
        return;
      }
      if (d.type === "GAS_COMBO_DIRECT_AI_DONE") {
        finish(d);
      }
    };
    window.addEventListener("message", onMsg);
    ackTimer = setTimeout(function() { finish({ reachable: false }); }, 350);
    try {
      postToBridge({ type: "GAS_COMBO_DIRECT_AI", reqId: reqId, payload: payload });
    } catch (e) {
      finish({ reachable: false });
    }
  }

  function requestRecordedMacros(payload, done) {
    if (typeof window === "undefined" || !window.top || window.top === window) {
      done({ reachable: false });
      return;
    }
    var reqId = "rec_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
    var settled = false;
    var ackTimer = null;
    var resTimer = null;
    var finish = function(res) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMsg);
      clearTimeout(ackTimer);
      clearTimeout(resTimer);
      done(res);
    };
    var onMsg = function(ev) {
      var d = ev && ev.data;
      if (!d || d.reqId !== reqId) return;
      if (d.type === "GAS_COMBO_FETCH_RECORDED_ACK") {
        clearTimeout(ackTimer);
        clearTimeout(resTimer);
        resTimer = setTimeout(function() {
          finish({ reachable: true, ok: false, error: "記録マクロの取得が時間切れになりました" });
        }, 25000);
        return;
      }
      if (d.type === "GAS_COMBO_FETCH_RECORDED_DONE") {
        finish(d);
      }
    };
    window.addEventListener("message", onMsg);
    ackTimer = setTimeout(function() { finish({ reachable: false }); }, 350);
    try {
      postToBridge({ type: "GAS_COMBO_FETCH_RECORDED_MACROS", reqId: reqId, payload: payload || {} });
    } catch (e) {
      finish({ reachable: false });
    }
  }

  function onRunAsk() {
    var txt = (els.askInput.value || "").trim();
    if (!txt) return;
    if (state.busy) {
      appendLog(els.chatLog, "is-err", "⚠ 別の処理を実行中です", "完了までお待ちください。");
      return;
    }
    pushHistory(txt);

    var liveSelPrompt = !!(els.chkSync.checked && hasSelectionPronoun(txt));
    var planRes = updatePreview();
    var fireOps = (!liveSelPrompt && planRes && planRes.fire && Array.isArray(planRes.ops) && planRes.ops.length) ? planRes.ops : null;
    var aiAuto = !!els.chkAiAuto.checked;

    els.askInput.value = "";
    updatePreview();

    // 近い候補があれば、AI自動でも先に［はい］を出す（郵便受けの受け手がいなくても止まらない。［いいえ］なら AI へ回す）
    var suggestOps = (!fireOps && !liveSelPrompt && planRes && Array.isArray(planRes.suggest) && planRes.suggest.length) ? planRes.suggest : null;

    var statusText = (!fireOps && aiAuto) ? "AI解釈・実行中…" : "実行中…";
    var payload = {
      ask: txt,
      ops: fireOps,
      ok: !!els.chkOk.checked,
      backup: !!els.chkBackup.checked,
      aiAuto: aiAuto,
      assumeActive: true,
      targetId: state.target.id || "",
      targetName: state.target.name || "",
      sheets: state.sheets || [],
      sheet: liveSelPrompt ? "" : (state.curSheet || ""),
      table: state.table
    };
    if (!liveSelPrompt) {
      payload.selection = els.chkSync.checked ? (state.selection || "") : "";
    }
    var runViaGasAsk = function() {
      state.directUndoStack = [];
      runServerAction({
        fnName: "comboRunAsk",
        payload: payload,
        label: txt,
        statusText: statusText,
        switchToChat: true
      });
    };
    var runAiAskDirectOrGas = function() {
      if (fireOps || !aiAuto || !canUseDirectLocalAi()) {
        runViaGasAsk();
        return;
      }
      setBusy(true, "✨ ローカル AI に直接確認中…");
      requestDirectAi({
        kind: "ops",
        ask: txt,
        ssId: state.target.id || "",
        ssName: state.target.name || "",
        sheet: state.curSheet || "",
        selection: els.chkSync.checked ? (state.selection || "") : "",
        table: state.table,
        sheets: state.sheets || [],
        aiModel: getCurrentAiModel()
      }, function(r) {
        setBusy(false);
        if (r && r.inExtension && !r.reachable) {
          switchTab("chat");
          appendLog(els.chatLog, "is-err", "⚠ ローカル直結に接続できません: " + txt, "ローカル AI 受け手（127.0.0.1:18766）に接続できません。PC の受け手が起動しているか確認してください");
          return;
        }
        if (!r || !r.reachable) {
          runViaGasAsk();
          return;
        }
        var d = r.data || {};
        if (d.ok && d.action === "ops" && Array.isArray(d.ops) && d.ops.length) {
          onRunOps(d.ops, txt, { switchToChat: true });
          return;
        }
        if (d.ok && d.action === "reply") {
          switchTab("chat");
          var head = "💬 " + txt + (typeof d.aiMs === "number" ? ("（直結 " + (d.aiMs / 1000).toFixed(1) + "秒）") : "");
          appendLog(els.chatLog, "is-info", head, String(d.message || d.text || ""));
          return;
        }
        switchTab("chat");
        appendLog(els.chatLog, "is-err", "⚠ AI エラー: " + txt, String(d.error || r.error || "AI 処理に失敗しました"));
      });
    };
    if (suggestOps) {
      offerSuggest(txt, suggestOps, aiAuto ? runAiAskDirectOrGas : null);
      return;
    }
    // 「ここ」「この列」など選択範囲の頼みも、Chrome 拡張から最新選択を即取得できれば直結 API（0.3 秒）で撃つ
    if (liveSelPrompt && !els.chkBackup.checked) {
      requestLiveSelection(function(live) {
        if (live && live.range && (!live.sheet || live.sheet === state.curSheet || typeof state.sheetIdMap[live.sheet] === "number")) {
          if (live.sheet && live.sheet !== state.curSheet) {
            state.curSheet = live.sheet;
            syncSheetSelects();
          }
          state.selection = live.range.toUpperCase();
          state.scope = Planner.parseSelectionScope ? Planner.parseSelectionScope(state.selection) : {};
          updateSelectionLabel();
          var livePlan = Planner.plan ? Planner.plan(txt, {
            table: state.table,
            sheets: state.sheets,
            curSheet: state.curSheet,
            scope: getActiveScope(),
            kind: "sheet",
            learned: state.learned
          }) : null;
          var liveOps = (livePlan && livePlan.fire && Array.isArray(livePlan.ops) && livePlan.ops.length) ? livePlan.ops : null;
          if (liveOps && tryDirectSheetsApi(liveOps, txt, true, runViaGasAsk)) {
            return;
          }
        }
        (!fireOps && aiAuto) ? runAiAskDirectOrGas() : runViaGasAsk();
      });
      return;
    }
    if (fireOps && !liveSelPrompt && !els.chkBackup.checked) {
      var handledDirect = tryDirectSheetsApi(fireOps, txt, true, runViaGasAsk);
      if (handledDirect) return;
    }

    (!fireOps && aiAuto) ? runAiAskDirectOrGas() : runViaGasAsk();
  }

  function onRunOps(ops, customLabel, opts) {
    if (Array.isArray(ops) && ops.length === 1 && ops[0] && ops[0].shelf) {
      quickRecordUsage({ src: "shelf", name: ops[0].shelf });
    }
    var label = customLabel || formatOpsShort(ops) || "ops実行";
    var switchChat = !(opts && opts.switchToChat === false);
    var runViaGas = function() {
      state.directUndoStack = [];
      runServerAction({
        fnName: "comboRunOps",
        payload: {
          ops: ops,
          ok: !!els.chkOk.checked,
          backup: !!els.chkBackup.checked,
          assumeActive: true,
          targetId: state.target.id || "",
          targetName: state.target.name || "",
          sheets: state.sheets || [],
          sheet: state.curSheet || "",
          selection: els.chkSync.checked ? (state.selection || "") : "",
          table: state.table
        },
        label: label,
        statusText: "実行中…",
        switchToChat: switchChat
      });
    };
    if (!els.chkBackup.checked && tryDirectSheetsApi(ops, label, false, runViaGas, { switchToChat: switchChat })) {
      return;
    }
    runViaGas();
  }

  function onUndo() {
    var undoViaGas = function() {
      runServerAction({
        fnName: "comboUndo",
        payload: {
          ok: !!els.chkOk.checked,
          targetId: state.target.id || "",
          assumeActive: true
        },
        label: "直前を取り消す",
        statusText: "取り消し中…",
        switchToChat: true
      });
    };
    if (tryDirectUndo(undoViaGas)) {
      return;
    }
    undoViaGas();
  }

  function onAutoWidth() {
    var scope = getActiveScope();
    if (els.chkSync.checked && scope && Array.isArray(scope.cols) && scope.cols.length &&
        (scope.col_select || scope.cols.length > 1)) {
      onRunOps([{ shelf: "width", auto: scope.cols }], "列幅自動");
      return;
    }
    var cols = (state.table && Array.isArray(state.table.columns))
      ? state.table.columns.map(function(c) { return c.col; }).filter(Boolean)
      : [];
    if (cols.length) {
      onRunOps([{ shelf: "width", auto: cols }], "列幅自動");
      return;
    }
    runServerAction({
      fnName: "comboRunAsk",
      payload: {
        ask: "全ての列の幅を中身に合わせて",
        ok: !!els.chkOk.checked,
        backup: !!els.chkBackup.checked,
        aiAuto: !!els.chkAiAuto.checked,
        targetId: state.target.id || "",
        targetName: state.target.name || "",
        sheets: state.sheets || [],
        sheet: state.curSheet || "",
        selection: els.chkSync.checked ? (state.selection || "") : "",
        table: state.table
      },
      label: "列幅自動",
      statusText: "実行中…",
      switchToChat: true
    });
  }

  function onFreezeHeader() {
    var hr = (state.table && state.table.header_row) ? state.table.header_row : 1;
    onRunOps([{ shelf: "freeze", rows: hr }], "見出し固定");
  }

  function onBorders() {
    var runWithSel = function(selA1) {
      var s = String(selA1 || "").trim().toUpperCase();
      var isMulti = /^[A-Z]{1,3}[0-9]{1,7}:[A-Z]{1,3}[0-9]{1,7}$/.test(s);
      if (isMulti) {
        var pts = s.split(":");
        if (pts[0] !== pts[1]) {
          onRunOps([{ shelf: "format", range: s, borders: true }], "罫線 (" + s + ")");
          return;
        }
      }
      var tblRange = resolveTableRangeStr(true);
      if (tblRange) {
        onRunOps([{ shelf: "format", range: tblRange, borders: true }], "罫線 (表全体)");
        return;
      }
      if (s) {
        onRunOps([{ shelf: "format", range: s, borders: true }], "罫線 (" + s + ")");
        return;
      }
      appendLog(els.chatLog, "is-err", "⚠ 罫線を引く範囲が見つかりません", "範囲を選択するか、表を読み込んでから押してください。");
    };
    requestLiveSelection(function(live) {
      if (live && live.range) {
        if (live.sheet && live.sheet !== state.curSheet && typeof state.sheetIdMap[live.sheet] === "number") {
          state.curSheet = live.sheet;
          syncSheetSelects();
        }
        state.selection = live.range.toUpperCase();
        state.scope = Planner.parseSelectionScope ? Planner.parseSelectionScope(state.selection) : {};
        updateSelectionLabel();
        runWithSel(state.selection);
      } else {
        runWithSel(els.chkSync.checked ? state.selection : "");
      }
    });
  }

  function onFindShelf() {
    var txt = (els.askInput.value || "").trim();
    var kind = (state.target && state.target.kind) || "sheet";
    if (typeof Planner.ask === "function") {
      var t0 = performance.now();
      var resText = String(Planner.ask(txt, kind) || "");
      var elapsed = performance.now() - t0;
      recordExecution(true, "棚検索: " + (txt || "一覧") + " (ローカル0ms)", resText, elapsed, 0, true);
      return;
    }
    runServerAction({
      fnName: "comboFind",
      payload: { ask: txt, kind: kind },
      label: "棚検索: " + (txt || "一覧"),
      statusText: "棚検索中…",
      switchToChat: true
    });
  }

  function onSaveConfig() {
    var mode = els.cfgAiMode.value;
    var model = els.cfgAiModel.value;
    var rawKey = (els.cfgApiKey.value || "").trim();
    var cfgPayload = {
      aiMode: mode,
      aiModel: model,
      backupDefault: !!els.chkBackup.checked
    };
    if (rawKey) {
      cfgPayload.apiKey = rawKey;
      if (mode === "api_gemini") cfgPayload.geminiKey = rawKey;
      if (mode === "api_claude") cfgPayload.claudeKey = rawKey;
    }

    runServerAction({
      fnName: "comboSaveConfig",
      payload: cfgPayload,
      label: "設定を保存",
      statusText: "設定保存中…",
      switchToChat: false,
      onSuccess: function(res) {
        els.cfgApiKey.value = "";
        if (rawKey) {
          state.config.hasApiKey = true;
          if (mode === "api_gemini") state.config.hasGeminiKey = true;
          if (mode === "api_claude") state.config.hasClaudeKey = true;
        }
        applyConfig(res.config || res);
        var modeLabel = mode === "postbox" ? "ローカル直結 (Claude Code CLI)" : (mode === "api_gemini" ? "Gemini API" : (mode === "api_claude" ? "Claude API" : mode));
        els.postboxStatusLabel.textContent = "設定を保存しました（方式: " + modeLabel + " / モデル: " + model + "）";
      }
    });
  }

  function requestDirectPing(done) {
    if (typeof window === "undefined" || !window.top || window.top === window) {
      done({ reachable: false, inExtension: false });
      return;
    }
    var reqId = "png_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
    var settled = false;
    var ackTimer = null;
    var resTimer = null;
    var finish = function(res) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMsg);
      clearTimeout(ackTimer);
      clearTimeout(resTimer);
      done(res);
    };
    var onMsg = function(ev) {
      var d = ev && ev.data;
      if (!d || d.reqId !== reqId) return;
      if (d.type === "GAS_COMBO_PING_LOCAL_ACK") {
        clearTimeout(ackTimer);
        clearTimeout(resTimer);
        resTimer = setTimeout(function() {
          finish({ reachable: false, inExtension: true, error: "応答が時間切れになりました" });
        }, 12000);
        return;
      }
      if (d.type === "GAS_COMBO_PING_LOCAL_DONE") {
        finish(d);
      }
    };
    window.addEventListener("message", onMsg);
    ackTimer = setTimeout(function() { finish({ reachable: false, inExtension: false }); }, 400);
    try {
      postToBridge({ type: "GAS_COMBO_PING_LOCAL", reqId: reqId });
    } catch (e) {
      finish({ reachable: false, inExtension: false });
    }
  }

  function onCheckPostbox() {
    if (state.polling) return;
    state.polling = true;
    els.postboxStatusLabel.textContent = "ローカル直結: 接続確認中…";
    var t0 = performance.now();
    requestDirectPing(function(r) {
      state.polling = false;
      var ms = (performance.now() - t0).toFixed(0);
      if (r && r.reachable && r.data && r.data.ok) {
        var pid = r.data.pid ? ("PID: " + r.data.pid + " / ") : "";
        els.postboxStatusLabel.textContent = r.recovered
          ? ("✅ ローカル直結 OK（自動起動で復旧 / " + pid + ms + "ms）")
          : ("✅ ローカル直結 OK（稼働中 / " + pid + ms + "ms）");
      } else if (r && r.inExtension) {
        els.postboxStatusLabel.textContent = "⚠ ローカル受け手（127.0.0.1:18766）に接続できません: " + String(r.error || "受け手未起動");
      } else {
        els.postboxStatusLabel.textContent = "⚠ Chrome 拡張機能（GASコンボ ブラウザ連動）が未読み込みまたは未更新です";
      }
    });
  }

  // 直結専用モードでは不要な旧郵便受け向けキック処理は送らない（Origin 403 ノイズ防止）
  function kickWatcher() {}

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function() {
        return fallbackCopy(text);
      });
    }
    return fallbackCopy(text);
  }

  function fallbackCopy(text) {
    return new Promise(function(resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) resolve();
        else reject(new Error("コピーに失敗しました"));
      } catch (e) {
        reject(e);
      }
    });
  }

  function onCopyForAi() {
    var txt = (els.askInput.value || "").trim();
    var url = (state.target && state.target.url) || "";
    var sh = state.curSheet || "";
    var selPart = state.selection ? ("・選択: " + state.selection) : "";
    var msg = url ? ("対象: " + url + "（シート: " + sh + selPart + "）\n依頼: " + txt) : txt;
    if (!msg) {
      appendLog(els.chatLog, "is-info", "[コピー]", "コピーする対象情報や入力文がありません。");
      return;
    }
    copyToClipboard(msg).then(function() {
      appendLog(els.chatLog, "is-ok", "[AIへコピー完了]", msg);
      if (els.btnCopyAi) {
        els.btnCopyAi.textContent = "済";
        setTimeout(function() { els.btnCopyAi.textContent = "AI"; }, 1200);
      }
    }).catch(function(err) {
      appendLog(els.chatLog, "is-err", "[コピー失敗]", formatError(err));
    });
  }

  // ---- 郵便受け完了待ちポーリング（常時ポーリングは行わない） ----
  function schedulePoll(delayMs) {
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    var hasPending = Object.keys(state.pendingPostboxIds).length > 0;
    if (!hasPending || !hasGasBridge()) return;

    state.pollTimer = setTimeout(runPollTick, delayMs || 1200);
  }

  function runPollTick() {
    state.pollTimer = null;
    var hasPending = Object.keys(state.pendingPostboxIds).length > 0;
    if (!hasPending) return;
    if (document.hidden || state.busy || state.polling) {
      schedulePoll(1500);
      return;
    }
    state.polling = true;
    var pollReq = {
      targetId: state.target.id || "",
      sheet: state.curSheet || ""
    };
    if (pollReq.targetId) pollReq.postboxOnly = true;
    callGas(
      "comboPollSelection",
      pollReq,
      function(res) {
        state.polling = false;
        if (res && res.ok !== false) {
          var prevSheet = state.curSheet;
          var prevSel = state.selection;
          if (typeof res.sheet === "string" && res.sheet && res.sheet !== prevSheet) {
            state.curSheet = res.sheet;
            syncSheetSelects();
          }
          if (typeof res.selection === "string") {
            state.selection = res.selection.toUpperCase();
          }
          if (res.scope && typeof res.scope === "object") {
            state.scope = res.scope;
          } else if (state.selection && Planner.parseSelectionScope) {
            state.scope = Planner.parseSelectionScope(state.selection);
          } else {
            state.scope = {};
          }
          if (typeof res.heading === "string") {
            state.heading = res.heading;
          }
          if (res.postboxDone) {
            handlePostboxDone(res.postboxDone);
          }
          if (state.curSheet !== prevSheet || state.selection !== prevSel) {
            updateSelectionLabel();
            updatePreview();
          }
        }
        if (Object.keys(state.pendingPostboxIds).length > 0) {
          schedulePoll(1800);
        }
      },
      function() {
        state.polling = false;
        if (Object.keys(state.pendingPostboxIds).length > 0) {
          schedulePoll(3000);
        }
      }
    );
  }

  // ---- キーボード操作（Enter実行・Shift+Enter改行・上下履歴） ----
  function getCursorLineInfo(ta) {
    var val = ta.value || "";
    var pos = ta.selectionStart || 0;
    var before = val.slice(0, pos);
    var lineIdx = before.split("\n").length - 1;
    var totalLines = val.split("\n").length;
    return { lineIdx: lineIdx, totalLines: totalLines };
  }

  els.askInput.addEventListener("keydown", function(e) {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (state.activeTab === "list" && quickRunFromInput()) return;
      onRunAsk();
      return;
    }
    if (e.key === "ArrowUp") {
      var infoUp = getCursorLineInfo(els.askInput);
      if (infoUp.lineIdx === 0 && state.history.length > 0) {
        e.preventDefault();
        if (state.histIdx < 0 || state.histIdx > state.history.length) {
          state.histIdx = state.history.length;
        }
        state.histIdx = Math.max(0, state.histIdx - 1);
        els.askInput.value = state.history[state.histIdx] || "";
        updatePreview();
        if (state.activeTab === "list") { state.quick.sel = -1; renderQuickList(); }
      }
      return;
    }
    if (e.key === "ArrowDown") {
      var infoDown = getCursorLineInfo(els.askInput);
      if (infoDown.lineIdx === infoDown.totalLines - 1 && state.history.length > 0) {
        e.preventDefault();
        state.histIdx = Math.min(state.history.length, state.histIdx + 1);
        els.askInput.value = (state.histIdx >= state.history.length) ? "" : (state.history[state.histIdx] || "");
        updatePreview();
        if (state.activeTab === "list") { state.quick.sel = -1; renderQuickList(); }
      }
    }
  });

  function onAskChanged() {
    updatePreview();
    if (state.activeTab === "list") {
      state.quick.sel = -1;
      renderQuickList();
    }
  }
  els.askInput.addEventListener("input", onAskChanged);
  els.askInput.addEventListener("keyup", onAskChanged);

  // ---- ボタン・イベント配線 ----
  els.btnRun.addEventListener("click", onRunAsk);
  els.btnClear.addEventListener("click", function() {
    els.askInput.value = "";
    onAskChanged();
    els.askInput.focus();
  });
  if (els.btnCopyAi) {
    els.btnCopyAi.addEventListener("click", onCopyForAi);
  }

  els.chkAiAuto.addEventListener("change", updatePreview);
  els.chkSync.addEventListener("change", function() {
    updateSelectionLabel();
    updatePreview();
  });
  els.chkBackup.addEventListener("change", function() {
    var on = !!els.chkBackup.checked;
    state.config.backupDefault = on;
    onRunOps([{ shelf: "backup", on: on }], "控え切替(" + (on ? "ON" : "OFF") + ")");
  });

  els.sheetSelect.addEventListener("change", function() {
    onLook(els.sheetSelect.value);
  });
  els.settingsSheetSelect.addEventListener("change", function() {
    onLook(els.settingsSheetSelect.value);
  });
  els.btnLook.addEventListener("click", function() { onLook(); });
  els.btnRefresh.addEventListener("click", function() { onInit(true); });

  var tabBtns = document.querySelectorAll(".tab-btn");
  for (var t = 0; t < tabBtns.length; t++) {
    tabBtns[t].addEventListener("click", function() {
      var tab = this.getAttribute("data-tab");
      state._userSwitchedTab = true;
      switchTab(tab);
      if (tab === "list") {
        state.quick.sel = -1;
        renderQuickCatBar();
        renderQuickList();
        if (hasGasBridge() && !state.quick._fetchedOnce) {
          loadQuickList(false);
        }
      }
    });
  }

  els.btnSeiri.addEventListener("click", function() {
    onRunOps([{ shelf: "seiri" }], "【一発整形】データ整理 ＋ 表を整える");
  });
  els.btnDocStyle.addEventListener("click", function() {
    onRunOps([{ shelf: "doc.style" }], "【一発整形】文書の体裁を整える");
  });

  var quickBtns = document.querySelectorAll("#pane-auto .quick-grid .btn");
  for (var q = 0; q < quickBtns.length; q++) {
    quickBtns[q].addEventListener("click", function() {
      var opRaw = this.getAttribute("data-op");
      var action = this.getAttribute("data-action");
      var btnText = this.textContent.trim();
      if (opRaw) {
        try {
          onRunOps(JSON.parse(opRaw), btnText);
        } catch (e) {
          appendLog(els.chatLog, "is-err", "[✗ 操作解析エラー]", formatError(e));
        }
      } else if (action === "look") {
        onLook();
      } else if (action === "undo") {
        onUndo();
      } else if (action === "autoWidth") {
        onAutoWidth();
      } else if (action === "freezeHeader") {
        onFreezeHeader();
      } else if (action === "borders") {
        onBorders();
      } else if (action === "findShelf") {
        onFindShelf();
      }
    });
  }

  function flashBtn(b, t, label) { b.textContent = t; setTimeout(function() { b.textContent = label; }, 1500); }

  els.btnAgain.addEventListener("click", function() {
    var last = state.history.length ? state.history[state.history.length - 1] : "";
    if (!last) { flashBtn(els.btnAgain, "頼みがありません", "もう一度"); return; }
    els.askInput.value = last;
    onRunAsk();
  });

  // 直した所へ移る: シートの名前ボックスに番地を入れる（Chrome の拡張のサイドパネルで開いているとき）
  els.btnGoChanged.addEventListener("click", function() {
    var a1 = state.lastChanged || "";
    if (!a1) { flashBtn(els.btnGoChanged, "まだありません", "直した所"); return; }
    var bang = a1.lastIndexOf("!");
    if (bang > 0) {
      var sh = a1.slice(0, bang).replace(/^'|'$/g, "");
      a1 = "'" + sh.replace(/'/g, "''") + "'!" + a1.slice(bang + 1);
    }
    state.gotoWait = setTimeout(function() {
      state.gotoWait = null;
      flashBtn(els.btnGoChanged, "移れません", "直した所");
      appendLog(els.traceLog, "is-err", "[直した所] " + a1, "拡張から返事がありません（Chrome 拡張のサイドパネルで開いているときだけ効きます。拡張を chrome://extensions で再読み込み）");
    }, 1500);
    try { window.top.postMessage({ type: "GAS_COMBO_GOTO", range: a1 }, "*"); } catch (e) {}
  });
  window.addEventListener("message", function(ev) {
    var d = ev && ev.data;
    if (!d || d.type !== "GAS_COMBO_GOTO_DONE") return;
    if (state.gotoWait) { clearTimeout(state.gotoWait); state.gotoWait = null; }
    flashBtn(els.btnGoChanged, d.ok ? "移りました" : "移れません", "直した所");
    if (!d.ok) appendLog(els.traceLog, "is-err", "[直した所] 移れません", String(d.why || ""));
  });

  els.btnCopyLog.addEventListener("click", function() {
    var b = els.btnCopyLog, label = "会話をコピー";
    var txt = els.chatLog.querySelector(".log-empty") ? "" : String(els.chatLog.innerText || "").trim();
    function flash(t) { b.textContent = t; setTimeout(function() { b.textContent = label; }, 1500); }
    if (!txt) { flash("会話がありません"); return; }
    copyToClipboard(txt).then(function() { flash("コピーしました"); })
      .catch(function(err) { flash("コピー失敗"); });
  });

  els.btnClearLog.addEventListener("click", function() {
    clearLogBox(els.chatLog, "実行結果がここに表示されます。");
  });

  els.btnUseHist.addEventListener("click", function() {
    if (state.selectedHistIdx >= 0 && state.history[state.selectedHistIdx] !== undefined) {
      els.askInput.value = state.history[state.selectedHistIdx];
      updatePreview();
      els.askInput.focus();
    }
  });
  els.btnRerunHist.addEventListener("click", function() {
    if (state.selectedHistIdx >= 0 && state.history[state.selectedHistIdx] !== undefined) {
      els.askInput.value = state.history[state.selectedHistIdx];
      updatePreview();
      onRunAsk();
    }
  });

  els.cfgAiMode.addEventListener("change", updateApiKeyPlaceholder);
  // 方式・モデルは選んだその場で覚える（保存ボタンを押さなくても次に開いたとき残る）
  function autoSaveAiChoice_() {
    rememberModel_();
    state.config.aiMode = els.cfgAiMode.value;
    state.config.aiModel = els.cfgAiModel.value;
    callGas("comboSaveConfig", { aiMode: els.cfgAiMode.value, aiModel: els.cfgAiModel.value }, function() {}, function() {});
  }
  els.cfgAiMode.addEventListener("change", autoSaveAiChoice_);
  els.cfgAiModel.addEventListener("change", autoSaveAiChoice_);
  els.btnSaveConfig.addEventListener("click", onSaveConfig);
  els.btnCheckPostbox.addEventListener("click", onCheckPostbox);

  els.btnNewTalk.addEventListener("click", function() {
    els.askInput.value = "";
    updatePreview();
    clearLogBox(els.chatLog, "実行結果がここに表示されます。");
    switchTab("auto");
    els.askInput.focus();
  });
  els.btnUndo.addEventListener("click", onUndo);
  els.btnReload.addEventListener("click", function() { onInit(true); });

  document.addEventListener("visibilitychange", function() {
    if (!document.hidden && Object.keys(state.pendingPostboxIds).length > 0) {
      schedulePoll(300);
    }
  });

