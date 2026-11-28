// ---------------------------------------------------------------- 自然文実行・AI直接連携

function comboStripJsonFence_(text) {
  var t = String(text || '').trim();
  var m = t.match(/^```[\w-]*[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```\s*$/);
  if (m) t = m[1].trim();
  if ((t.charAt(0) === '{' && t.charAt(t.length - 1) === '}') || (t.charAt(0) === '[' && t.charAt(t.length - 1) === ']')) {
    return t;
  }
  var m2 = t.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  return m2 ? m2[1] : t;
}

function comboBuildCompactShelfSummary_(ask, fullLimit, optPlanCards) {
  var lines = [];
  var askPlan = '';
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.ask === 'function') {
    askPlan = String(ComboPlanner.ask(ask || '', 'sheet') || '').slice(0, 1600);
    if (askPlan) lines.push(askPlan);
  }
  var aiShelves = (typeof COMBO_CATALOG_DATA !== 'undefined' && COMBO_CATALOG_DATA.shelves)
    ? COMBO_CATALOG_DATA.shelves
    : (Array.isArray(COMBO_MINI_SHELVES) ? COMBO_MINI_SHELVES : null);
  if (aiShelves) {
    var sheetShelves = aiShelves.filter(function (s) {
      return s && s.searchable !== false && (s.kind === 'sheet' || s.shared || !s.kind);
    });
    var prioSet = {
      seiri: 1, tidy: 1, format: 1, write: 1, replace: 1, total: 1, 'calc.col': 1, sort: 1,
      'filter.on': 1, 'filter.where': 1, 'filter.delete': 1, 'filter.extract': 1, 'filter.off': 1, 'cf.add': 1,
      width: 1, freeze: 1, unfreeze: 1, dedupe: 1, 'banding.add': 1, 'banding.remove': 1, 'chart.new': 1,
      'rows.delete': 1, 'rows.insert': 1, 'cols.delete': 1, 'sheet.add': 1, 'sheet.rename': 1, 'sheet.copy': 1,
      'table.new': 1, 'validation.list': 1, summary: 1, api: 1
    };
    (optPlanCards || []).forEach(function (cn) { if (cn) prioSet[cn] = 1; });
    var picked = [];
    var pickedMap = {};
    sheetShelves.forEach(function (s) {
      if ((askPlan && askPlan.indexOf(s.name) >= 0) || prioSet[s.name]) {
        if (!pickedMap[s.name] && picked.length < (fullLimit || 30)) {
          pickedMap[s.name] = true;
          picked.push(s);
        }
      }
    });
    if (picked.length) {
      lines.push('\n【利用可能な棚一覧（主要・関連：棚名 | 説明 | 引数）】');
      picked.forEach(function (s) {
        lines.push('- ' + s.name + ': ' + (s.title || s.t || '') + ' | ' + (s.args_raw || s.a || 'なし'));
      });
    }
    var rest = sheetShelves.filter(function (s) { return !pickedMap[s.name]; });
    if (rest.length) {
      lines.push('\n【その他すべての利用可能な棚（カテゴリ別・全件）】');
      var byCat = {};
      var catOrder = [];
      rest.forEach(function (s) {
        var c = s.category || s.c || 'その他';
        if (!byCat[c]) { byCat[c] = []; catOrder.push(c); }
        byCat[c].push(s.name + '(' + (s.title || s.t || '') + ')');
      });
      catOrder.forEach(function (c) {
        lines.push('- ' + c + ': ' + byCat[c].join(' / '));
      });
    }
  } else if (typeof CATALOG !== 'undefined') {
    lines.push('\n【利用可能な棚一覧】');
    Object.keys(CATALOG).filter(function (k) { return CATALOG[k] && CATALOG[k].kind === 'sheet'; }).forEach(function (k) {
      lines.push('- ' + k);
    });
  }
  return lines.join('\n');
}

function comboReadTableSnippet_(ss, curSheet, table) {
  var sh = sheetOf_(ss, curSheet, '');
  var lr = Math.max(0, sh.getLastRow());
  var lc = Math.max(0, sh.getLastColumn());
  if (!lr || !lc) {
    return { text: '(シートは空です)', truncated: false, totalRows: 0, note: '' };
  }
  var maxRows = 100, headRows = 80, tailRows = 20, maxCols = 26;
  var useCols = Math.min(lc, maxCols);
  var truncated = lr > maxRows;
  var fmtRow = function (rNo, dispRow, fmRow) {
    var parts = [];
    for (var j = 0; j < useCols; j++) {
      var vs = dispRow && dispRow[j] !== undefined && dispRow[j] !== null ? String(dispRow[j]) : '';
      var fs = fmRow && fmRow[j] ? String(fmRow[j]) : '';
      if (!vs && !fs) continue;
      parts.push(colLetter_(j + 1) + '=' + vs + (fs ? ' {' + fs + '}' : ''));
    }
    return 'R' + rNo + ': ' + (parts.length ? parts.join(' | ') : '(空行)');
  };
  var lines = [];
  if (!truncated) {
    var rgAll = sh.getRange(1, 1, lr, useCols);
    var dvAll = rgAll.getDisplayValues();
    var fmAll = rgAll.getFormulas();
    for (var i = 0; i < lr; i++) lines.push(fmtRow(i + 1, dvAll[i], fmAll[i]));
  } else {
    var rgH = sh.getRange(1, 1, headRows, useCols);
    var dvH = rgH.getDisplayValues(), fmH = rgH.getFormulas();
    for (var hi = 0; hi < headRows; hi++) lines.push(fmtRow(hi + 1, dvH[hi], fmH[hi]));
    lines.push('...（中略: 全 ' + lr + ' 行のうち先頭 ' + headRows + ' 行＋末尾 ' + tailRows + ' 行を抜粋）...');
    var tailStart = lr - tailRows + 1;
    var rgT = sh.getRange(tailStart, 1, tailRows, useCols);
    var dvT = rgT.getDisplayValues(), fmT = rgT.getFormulas();
    for (var ti = 0; ti < tailRows; ti++) lines.push(fmtRow(tailStart + ti, dvT[ti], fmT[ti]));
  }
  var note = truncated ? ('※全 ' + lr + ' 行のうち抜粋（先頭' + headRows + '行＋末尾' + tailRows + '行）で読みました') : '';
  return { text: lines.join('\n'), truncated: truncated, totalRows: lr, note: note };
}

function comboReadSnippet(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var ss = comboOpenSs_(req);
    var selInfo = comboGetSelectionInfo_(ss, req);
    var sn = comboReadTableSnippet_(ss, selInfo.sheet, req.table);
    return Object.assign({ ok: true, sheet: selInfo.sheet, gasMs: Date.now() - t0 }, sn);
  } catch (err) {
    return { ok: false, error: String(err && err.message || err), gasMs: Date.now() - t0 };
  }
}

function comboBuildAiPrompts_(ask, ssName, sheetName, selection, table, sheets, optOpts) {
  var isReadOnly = !!(optOpts && optOpts.readOnly);
  var sys = isReadOnly
    ? [
        'あなたは Google スプレッドシートの内容を読んで質問に答えるアシスタントです。',
        '必ず有効な JSON オブジェクト 1 個だけを返してください（説明文や ``` などの装飾は一切付けない）。',
        '形式: {"action":"reply","message":"日本語の返事（根拠セル番地・数値を添えて簡潔に）"}',
        '重要: シートは一切変更しないでください（ops は絶対に返さないこと）。'
      ].join('\n')
    : [
        'あなたは Google スプレッドシートを操作するアシスタントです。',
        '必ず有効な JSON オブジェクト 1 個だけを返してください（説明文や ``` などの装飾は一切付けない）。',
        '・操作を実行するとき: {"action":"ops","ops":[{"shelf":"棚名","引数":値}],"note":"短い日本語要約"}',
        '・返事や確認だけを返すとき: {"action":"reply","message":"日本語の返事"}',
        'ルール: 棚名・引数名は利用可能な棚一覧に載っている正確な名前と型を使うこと。表に無い列名や頼みに無い操作を足さないこと。削除や上書きの棚に ok:true を勝手に付けないこと（承認はユーザー側で行う）。曖昧・情報不足なら reply で聞き返すこと。'
      ].join('\n');

  var lines = ['【現在の対象状態】', 'ブック: ' + ssName + ' / シート: ' + sheetName];
  if (sheets && sheets.length) lines.push('全シート: ' + sheets.join('、'));
  if (selection) lines.push('選択中のセル範囲: ' + selection + '（「ここ」「選択範囲」等の対象）');
  if (table) {
    var hr1 = table.header_row;
    var hrs = parseInt(table.header_rows || 1, 10);
    var hrLabel = hrs > 1 ? (hr1 + '-' + (hr1 + hrs - 1)) : String(hr1);
    lines.push('表: 見出し ' + hrLabel + '行目・' + table.first_col + '〜' + table.last_col + '列・明細 ' + table.data + '行目' + (table.total_row ? '・合計行 ' + table.total_row : ''));
    lines.push('列: ' + (table.columns || []).map(function (c) { return c.col + '=' + c.name + (c.number ? '(数値)' : ''); }).join('、'));
  }

  var sn = (optOpts && optOpts.snippet) || {};
  if (isReadOnly) {
    if (sn.note) lines.push(sn.note);
    if (sn.text) lines.push('\n【表の中身（行番号・列記号・値・数式）】\n' + sn.text);
    lines.push('\n【ユーザーの質問（読むだけ・シート変更禁止）】\n' + ask);
    lines.push('\n必ず {"action":"reply","message":"..."} の JSON 1個だけを返してください。');
    return { system: sys, user: lines.join('\n') };
  }

  if (sn.text) {
    var snTxt = String(sn.text);
    if (snTxt.length > 12000) snTxt = snTxt.slice(0, 12000) + '\n...（文字数上限のため一部省略）...';
    if (sn.note) lines.push(sn.note);
    lines.push('\n【表の中身（行番号・列記号・値・数式）】\n' + snTxt);
  }
  var planHint = (optOpts && optOpts.plan) || null;
  var planCardNames = [];
  if (planHint) {
    var pHints = [];
    if (Array.isArray(planHint.reasons) && planHint.reasons.length) pHints.push('止まった理由: ' + planHint.reasons.slice(0, 3).join('／'));
    if (Array.isArray(planHint.missing) && planHint.missing.length) pHints.push('足りない引数: ' + planHint.missing.slice(0, 5).join('、'));
    if (Array.isArray(planHint.ops) && planHint.ops.length) pHints.push('組みかけの ops: ' + JSON.stringify(planHint.ops));
    if (Array.isArray(planHint.cards) && planHint.cards.length) {
      planCardNames = planHint.cards.map(function (c) { return typeof c === 'string' ? c : (c && c.name); }).filter(Boolean);
      if (planCardNames.length) pHints.push('候補の棚: ' + planCardNames.slice(0, 6).join('、'));
    }
    if (pHints.length) lines.push('\n【棚当ての途中結果】\n' + pHints.join('\n'));
  }

  lines.push('\n【関連する棚候補と全棚カタログ】');
  lines.push(comboBuildCompactShelfSummary_(ask, 30, planCardNames));
  lines.push('\n【ユーザーの依頼】\n' + ask);
  lines.push('\nJSON 1個だけを返してください。');
  return { system: sys, user: lines.join('\n') };
}

function comboResolveApiKey_(cfg) {
  if (!cfg) return '';
  // 鍵は方式ごと。共用の apiKey は形で見分けたときだけ使う（Gemini の鍵を Anthropic へ送る等、別の会社へ鍵を渡さない）
  var legacy = String(cfg.apiKey || '').trim();
  if (cfg.aiMode === 'api_gemini') return String(cfg.geminiKey || (/^AIza/.test(legacy) ? legacy : '') || '').trim();
  if (cfg.aiMode === 'api_claude') return String(cfg.claudeKey || (/^sk-ant-/.test(legacy) ? legacy : '') || '').trim();
  return '';
}

function comboResolveLatestApiModel_(provider, aliasOrModel, apiKey) {
  var raw = String(aliasOrModel || '').trim();
  var lower = raw.toLowerCase();
  if (provider === 'api_claude') {
    if (/^claude-(?:sonnet|haiku|opus|fable)-\d/.test(lower)) return raw;
    var cFam = lower.indexOf('haiku') >= 0 ? 'haiku' : (lower.indexOf('opus') >= 0 ? 'opus' : 'sonnet');
    var cFallback = 'claude-' + cFam + '-5-5';
    var cCacheKey = 'combo_latest_model:api_claude:' + cFam;
    try {
      var uc = CacheService.getUserCache();
      var hit = uc ? uc.get(cCacheKey) : null;
      if (hit) return hit;
    } catch (eC0) {}
    if (apiKey) {
      try {
        var r = UrlFetchApp.fetch('https://api.anthropic.com/v1/models?limit=50', {
          method: 'get',
          muteHttpExceptions: true,
          headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' }
        });
        if (r.getResponseCode() >= 200 && r.getResponseCode() < 300) {
          var j = JSON.parse(r.getContentText() || '{}');
          var arr = Array.isArray(j.data) ? j.data : [];
          var picked = '';
          for (var i = 0; i < arr.length; i++) {
            var id = String((arr[i] && arr[i].id) || '').trim();
            if (id.indexOf('claude-' + cFam + '-') === 0) { picked = id; break; }
          }
          if (picked) {
            try { var uc2 = CacheService.getUserCache(); if (uc2) uc2.put(cCacheKey, picked, 21600); } catch (eC1) {}
            return picked;
          }
        }
      } catch (eC2) {}
    }
    return cFallback;
  }
  if (/^gemini-\d/.test(lower) && lower.indexOf('gemini-4-hydrogen-') !== 0) return raw;
  var gFam = lower.indexOf('neon') >= 0 ? 'neon' : 'hydrogen';
  var gFallback = gFam === 'neon' ? 'gemini-4-neon' : 'gemini-4-hydrogen';
  var gCacheKey = 'combo_latest_model:api_gemini:' + gFam;
  try {
    var ug = CacheService.getUserCache();
    var gHit = ug ? ug.get(gCacheKey) : null;
    if (gHit) return gHit;
  } catch (eG0) {}
  if (apiKey) {
    try {
      var gr = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models?key=' + encodeURIComponent(apiKey) + '&pageSize=100', {
        method: 'get',
        muteHttpExceptions: true
      });
      if (gr.getResponseCode() >= 200 && gr.getResponseCode() < 300) {
        var gj = JSON.parse(gr.getContentText() || '{}');
        var models = Array.isArray(gj.models) ? gj.models : [];
        var best = '';
        var bestVer = -1;
        for (var k = 0; k < models.length; k++) {
          var m = models[k] || {};
          var methods = Array.isArray(m.supportedGenerationMethods) ? m.supportedGenerationMethods : [];
          if (methods.length && methods.indexOf('generateContent') < 0) continue;
          var nm = String(m.name || '').replace(/^models\//, '').trim();
          var nl = nm.toLowerCase();
          var vm = (gFam === 'neon')
            ? nl.match(/^gemini-(\d+(?:\.\d+)?)-neon$/)
            : nl.match(/^gemini-(\d+(?:\.\d+)?)-hydrogen$/);
          if (vm) {
            var verNum = parseFloat(vm[1]);
            if (verNum > bestVer) { bestVer = verNum; best = nm; }
          }
        }
        if (best) {
          try { var ug2 = CacheService.getUserCache(); if (ug2) ug2.put(gCacheKey, best, 21600); } catch (eG1) {}
          return best;
        }
      }
    } catch (eG2) {}
  }
  return gFallback;
}

function comboSanitizeAndAuditAiOps_(ops, askText, table) {
  if (!Array.isArray(ops) || !ops.length) {
    return { ok: false, ops: [], issues: ['ops が空または配列ではありません'] };
  }
  // 守り: AI が勝手に ok:true を付けても必ず剥ぎ取る（guardDelete_ / guardOverwrite_ を緩めない）
  var cleaned = ops.map(function (o) {
    if (!o || typeof o !== 'object') return o;
    var cp = {};
    Object.keys(o).forEach(function (k) { if (k !== 'ok') cp[k] = o[k]; });
    return cp;
  });
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.auditAiOps === 'function') {
    return ComboPlanner.auditAiOps(cleaned, askText || '', table || null);
  }
  var issues = [];
  for (var i = 0; i < cleaned.length; i++) {
    var op = cleaned[i];
    if (!op || typeof op !== 'object' || !op.shelf) {
      issues.push((i + 1) + ' 番目の ops に shelf がありません');
    } else if (typeof CATALOG !== 'undefined' && CATALOG && !CATALOG[op.shelf]) {
      issues.push('棚「' + op.shelf + '」はありません');
    }
  }
  return { ok: !issues.length, ops: cleaned, issues: issues };
}

function comboCallAiApi_(cfg, ask, ss, curSheet, selection, table, sheets, optOpts) {
  var apiKey = comboResolveApiKey_(cfg);
  if (!apiKey) throw new Error('APIキーが設定されていません');
  var isReadOnly = !!(optOpts && optOpts.readOnly);
  var prompts = comboBuildAiPrompts_(ask, ss.getName(), curSheet, selection, table, sheets, optOpts);
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
        generationConfig: { temperature: 0, responseMimeType: 'application/json' }
      })
    });
    var gCode = gResp.getResponseCode();
    var gBody = gResp.getContentText();
    if (gCode < 200 || gCode >= 300) {
      throw new Error('Gemini API エラー (' + gCode + '): ' + gBody.slice(0, 200));
    }
    var gJson = JSON.parse(gBody);
    var gCand = (gJson.candidates || [])[0] || {};
    // 考えの塊（thought）は外し、答えの塊をつなぐ
    rawText = ((gCand.content || {}).parts || []).filter(function (pt) { return pt && !pt.thought && typeof pt.text === 'string'; })
      .map(function (pt) { return pt.text; }).join('');
    if (gCand.finishReason === 'MAX_TOKENS') {
      throw new Error('Gemini API の返事が長すぎて途中で切れました（頼みを小さく分けてください）');
    }
    if (!rawText) {
      throw new Error('Gemini API の返事が空でした（' + (gCand.finishReason || (gJson.promptFeedback && gJson.promptFeedback.blockReason) || '理由不明') + '）');
    }
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
        max_tokens: 4096,
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
    // 返事の塊は text 以外が先に来ることがある＝text の塊をつなぐ
    rawText = (cJson.content || []).filter(function (b) { return b && b.type === 'text'; })
      .map(function (b) { return b.text || ''; }).join('');
    if (cJson.stop_reason === 'max_tokens') {
      throw new Error('Claude API の返事が長すぎて途中で切れました（頼みを小さく分けてください）');
    }
  } else {
    throw new Error('未対応の AI モード: ' + cfg.aiMode);
  }

  var parsed = JSON.parse(comboStripJsonFence_(rawText));
  if (isReadOnly) {
    // 守り: 読むだけの道で AI が ops を返してもコード側で必ず捨てて撃たない
    var roMsg = (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
      ? String(parsed.message || parsed.note || '').trim()
      : '';
    if (!roMsg) roMsg = '読むだけの質問のためシートは変更しませんでした。';
    var snRo = optOpts && optOpts.snippet;
    if (snRo && snRo.truncated && snRo.note && roMsg.indexOf('抜粋') < 0) {
      roMsg += '\n' + snRo.note;
    }
    return { action: 'reply', message: roMsg };
  }
  if (Array.isArray(parsed)) return { action: 'ops', ops: parsed, note: '' };
  if (parsed && parsed.shelf && !parsed.ops) return { action: 'ops', ops: [parsed], note: '' };
  return parsed;
}

// ---------------------------------------------------------------- 覚えた言い方（［はい］で決めた頼み→ops。使う人ごと）
var COMBO_PROP_LEARNED = 'COMBO_LEARNED';

function comboGetLearned(req) {
  if (req && req.reset) return { ok: true, learned: {} };
  var map = {};
  try { map = JSON.parse(PropertiesService.getUserProperties().getProperty(COMBO_PROP_LEARNED) || '{}') || {}; } catch (e) { map = {}; }
  return { ok: true, learned: map };
}

function comboLearn(req) {
  req = req || {};
  var ask = String(req.ask || '').trim();
  var ops = req.ops;
  if (!ask || !Array.isArray(ops) || !ops.length) return { ok: false, text: '覚える頼みと ops がありません' };
  var map = comboGetLearned().learned;
  if (req.key) {
    // 呼び手（サイドバー・アドオンのカード）の棚当てが作った鍵をそのまま使う（軽量版はここに棚当てが無い）
    delete map[req.key];
    map[String(req.key)] = ops;
    var ks = Object.keys(map);
    while (ks.length > 300) delete map[ks.shift()];
  } else if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.learn === 'function') {
    ComboPlanner.setLearned(map);
    map = ComboPlanner.learn(ask, ops);
  } else {
    var key = ask.normalize('NFKC').toLowerCase().replace(/\s+/g, '').replace(/[。．.!！?？]+$/g, '');
    map[key] = ops;
  }
  try { PropertiesService.getUserProperties().setProperty(COMBO_PROP_LEARNED, JSON.stringify(map)); } catch (e) {
    return { ok: false, text: '覚えを保存できませんでした: ' + String(e && e.message || e) };
  }
  return { ok: true, text: '覚えました: ' + ask };
}

function comboRenderUnfired_(plan) {
  var lines = ['撃っていません: ' + ((plan.reasons && plan.reasons.length) ? plan.reasons.join('／') : '引数が決まりません')];
  if (plan.suggest && plan.suggest.length) {
    lines.push('近い候補: ' + comboFormatOpsShort_(plan.suggest));
  }
  if (plan.missing && plan.missing.length) {
    lines.push('足りない引数: ' + plan.missing.join('、'));
  }
  if (plan.ops && plan.ops.length) {
    lines.push('組みかけ: ' + comboFormatOpsShort_(plan.ops));
  }
  if (plan.guide && plan.guide.length) {
    plan.guide.slice(0, 2).forEach(function (g) { lines.push('案内: ' + g); });
  }
  return lines.join('\n');
}

function comboMatchMyMacro_(askText, myList) {
  if (!askText || !Array.isArray(myList) || !myList.length) return null;
  var norm = function (s) {
    var t = String(s || '');
    try { if (typeof t.normalize === 'function') t = t.normalize('NFKC'); } catch (eN) {}
    return t.toLowerCase().replace(/[\s\u3000、。,.!！?？「」『』()（）]/g, '');
  };
  var stripTail = function (s) {
    return s.replace(/(してください|して下さい|を実行する|を実行|を動かして|を動かして下さい|をお願い|お願いします|をやって|を呼んで|して)$/, '');
  };
  var q = norm(askText);
  var qBase = stripTail(q);
  if (!q) return null;

  var exactHits = [];
  var subBestScore = 0;
  var subHits = [];
  for (var i = 0; i < myList.length; i++) {
    var m = myList[i];
    if (!m || !m.name) continue;
    var cands = [m.name].concat(Array.isArray(m.words) ? m.words : []);
    var isExact = false;
    var bestLen = 0;
    for (var j = 0; j < cands.length; j++) {
      var w = norm(cands[j]);
      var wBase = stripTail(w);
      if (!w) continue;
      if (w === q || (wBase && wBase === qBase)) {
        isExact = true;
        break;
      }
      if (w.length >= 2 && q.indexOf(w) >= 0 && w.length > bestLen) bestLen = w.length;
      if (wBase.length >= 2 && qBase.indexOf(wBase) >= 0 && wBase.length > bestLen) bestLen = wBase.length;
    }
    if (isExact) {
      exactHits.push(m);
    } else if (bestLen > 0) {
      if (bestLen > subBestScore) {
        subBestScore = bestLen;
        subHits = [m];
      } else if (bestLen === subBestScore) {
        subHits.push(m);
      }
    }
  }
  if (exactHits.length === 1) return exactHits[0];
  if (exactHits.length > 1) return null;
  if (subHits.length === 1) return subHits[0];
  return null;
}

/**
 * 自然文または事前解決済み ops を受け取り、棚ヒット即実行または AI（API 鍵）で解釈して実行する。
 * @param {Object} req { ask, ops, ok, backup, aiAuto, sheet, selection, table }
 */
function comboRunAsk(req) {
  var t0 = Date.now();
  req = req || {};
  var askText = String(req.ask || '').trim();

  // フロント側ですでに棚ヒット済み ops が渡された場合は最速で実行する
  if (Array.isArray(req.ops) && req.ops.length) {
    var preRes = comboRunOps({
      ops: req.ops,
      ok: !!req.ok,
      backup: !!req.backup,
      fastUndo: req.fastUndo,
      kind: req.kind,
      sheet: req.sheet,
      selection: req.selection,
      table: req.table,
      sheets: req.sheets,
      targetName: req.targetName || req._ssName,
      targetId: req.targetId
    });
    if (preRes.ok) {
      preRes.source = 'shelf';
      preRes.text = '[棚ヒット] ' + comboFormatOpsShort_(req.ops) + '\n' + preRes.text;
    }
    preRes.gasMs = Date.now() - t0;
    return preRes;
  }

  if (!askText) {
    return { ok: false, error: '依頼文が空です', text: '依頼文が空です', gasMs: Date.now() - t0 };
  }

  if (comboIsDocReq_(req)) {
    var doc;
    try {
      doc = comboOpenDoc_(req);
    } catch (errOpenDoc) {
      return { ok: false, error: String(errOpenDoc && errOpenDoc.message || errOpenDoc), text: 'エラー: ' + String(errOpenDoc && errOpenDoc.message || errOpenDoc), gasMs: Date.now() - t0 };
    }
    var docId = doc.getId();
    var docName = req.targetName || doc.getName();
    if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.plan === 'function') {
      if (typeof ComboPlanner.setLearned === 'function') ComboPlanner.setLearned(comboGetLearned().learned);
      var docPlan = ComboPlanner.plan(askText, 'doc', null, [], '', null);
      if (docPlan && docPlan.fire && docPlan.ops && docPlan.ops.length) {
        var docHit = comboRunOps({
          kind: 'doc',
          ops: docPlan.ops,
          ok: !!req.ok,
          backup: !!req.backup,
          targetId: docId,
          targetName: docName,
          _doc: doc
        });
        if (docHit.ok) {
          docHit.source = 'shelf';
          docHit.text = '[棚ヒット] ' + comboFormatOpsShort_(docPlan.ops) + '\n' + docHit.text;
        }
        docHit.gasMs = Date.now() - t0;
        return docHit;
      }
      return {
        ok: false,
        unfired: true,
        plan: docPlan,
        text: comboRenderUnfired_(docPlan),
        gasMs: Date.now() - t0
      };
    }
    return {
      ok: false,
      unfired: true,
      text: '撃っていません: 棚に一発で当てはまらない文書指示です',
      gasMs: Date.now() - t0
    };
  }

  var ss;
  try {
    ss = comboOpenSs_(req);
  } catch (errOpen) {
    return { ok: false, error: String(errOpen && errOpen.message || errOpen), text: 'エラー: ' + String(errOpen && errOpen.message || errOpen), gasMs: Date.now() - t0 };
  }
  var ssId = ss.getId();

  var selInfo;
  try {
    selInfo = comboGetSelectionInfo_(ss, req);
  } catch (errSel) {
    return { ok: false, error: String(errSel && errSel.message || errSel), text: 'エラー: ' + String(errSel && errSel.message || errSel), gasMs: Date.now() - t0 };
  }
  var curSheet = selInfo.sheet;
  var selection = selInfo.selection;
  var scope = comboParseScope_(selection);

  var cached = (req.targetName && req.sheets && req.table !== undefined && req.table && req.table.title_a1)
    ? null
    : comboCacheGet_(ssId, curSheet);
  var ssName = req.targetName || (cached && cached.ssName) || '';
  var table = req.table !== undefined ? req.table : (cached ? cached.table : undefined);
  var sheets = req.sheets || (cached ? cached.sheets : null);
  if (table === undefined || !sheets) {
    var sh = sheetOf_(ss, curSheet, '');
    var tb = findTable_(sh);
    table = tb ? tableOut_(tb) : null;
    var titleA1 = comboComputeTitleA1_(sh, tb);
    if (table && titleA1) table.title_a1 = titleA1;
    sheets = ss.getSheets().map(function (s) { return s.getName(); });
    ssName = ssName || ss.getName();
    comboCachePut_(ssId, curSheet, table, sheets, tb, ssName, titleA1);
    cached = comboCacheGet_(ssId, curSheet);
  }

  var isReadOnlyAsk = false;
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.plan === 'function') {
    if (typeof ComboPlanner.setLearned === 'function') ComboPlanner.setLearned(comboGetLearned().learned);
    var plan = ComboPlanner.plan(askText, 'sheet', table, sheets, curSheet, scope);
    if (plan && plan.fire && plan.ops && plan.ops.length) {
      var hitRes = comboRunOps({
        ops: plan.ops,
        ok: !!req.ok,
        backup: !!req.backup,
        fastUndo: req.fastUndo,
        sheet: curSheet,
        selection: selection,
        table: table,
        sheets: sheets,
        targetId: ssId,
        assumeActive: !!req.assumeActive,
        _ss: ss,
        _ssName: ssName,
        _cached: cached
      });
      if (hitRes.ok) {
        hitRes.source = 'shelf';
        hitRes.text = '[棚ヒット] ' + comboFormatOpsShort_(plan.ops) + '\n' + hitRes.text;
      }
      hitRes.gasMs = Date.now() - t0;
      return hitRes;
    }

    if (plan && Array.isArray(plan.choices) && plan.choices.length) {
      var chLines = ['どこまで整えますか？（まだシートは変更していません）'];
      plan.choices.forEach(function (ch, idx) {
        chLines.push((idx + 1) + '. ' + ch.label + ' — ' + (ch.desc || comboFormatOpsShort_(ch.ops)));
      });
      return {
        ok: true,
        source: 'choices',
        choices: plan.choices,
        text: chLines.join('\n'),
        gasMs: Date.now() - t0
      };
    }

    isReadOnlyAsk = !!(plan && plan.readOnly);

    // 読むだけの質問はマイマクロ照合を行わない。aiAuto=false なら表の中身は AI へ送らず要約のみ返す
    if (isReadOnlyAsk) {
      if (!req.aiAuto) {
        var roSummary = table
          ? ('シート「' + curSheet + '」: 見出し ' + table.header_row + (table.header_rows > 1 ? '-' + (table.header_row + table.header_rows - 1) : '') + '行目・明細 ' + table.data + '行目\n列: ' + (table.columns || []).map(function (c) { return c.col + '=' + c.name; }).join('、'))
          : ('シート「' + curSheet + '」');
        return {
          ok: true,
          source: 'read_only_summary',
          readOnly: true,
          text: '[読むだけ] シートは変更していません。\n' + roSummary + '\n（※「AI自動」をONにするとシートの中身を読んで質問に答えます）',
          gasMs: Date.now() - t0
        };
      }
    } else {
      // 既製棚に一発ヒットしなかった場合、マイマクロの // 棚: 言い方 と関数名を照合する
      if (typeof quickMyFind_ === 'function' && typeof quickMyListCached_ === 'function' && typeof comboQuickRun === 'function') {
        try {
          var allPropsMy = null;
          try { allPropsMy = PropertiesService.getUserProperties().getProperties() || {}; } catch (ePM) {}
          var metaMy = quickMyFind_(true, allPropsMy);
          if (metaMy && metaMy.id) {
            var myList = quickMyListCached_(metaMy.id, metaMy.stamp || undefined);
            var myHit = comboMatchMyMacro_(askText, myList);
            if (myHit) {
              var myRes = comboQuickRun({
                name: myHit.name,
                myId: metaMy.id,
                myStamp: metaMy.stamp || '',
                targetId: ssId,
                sheet: curSheet,
                selection: selection,
                backup: !!req.backup
              });
              if (myRes) {
                myRes.source = 'mymacro';
                myRes.matchedMacro = myHit.name;
                if (myRes.ok) myRes.text = '[マイマクロ] ' + myHit.name + '\n' + (myRes.text || '');
                myRes.gasMs = Date.now() - t0;
                return myRes;
              }
            }
          }
        } catch (eMyMatch) {}
      }

      // 棚にもマイマクロにも一発ヒットしなかった場合
      if (!req.aiAuto) {
        return {
          ok: false,
          unfired: true,
          plan: plan,
          text: comboRenderUnfired_(plan),
          gasMs: Date.now() - t0
        };
      }
    }
  } else if (!req.aiAuto) {
    return {
      ok: false,
      unfired: true,
      text: '撃っていません: 棚に一発で当てはまらない指示です（「AI自動」をONにするか言い方を具体化してください）',
      gasMs: Date.now() - t0
    };
  }

  var cfg = comboGetRawConfig_();
  if (req.forceAiMode === 'api_gemini' || req.forceAiMode === 'api_claude') {
    cfg = Object.assign({}, cfg, { aiMode: req.forceAiMode });
  }
  // aiAuto=true でここまで来たときだけ表の中身（最大100行×26列・値と式）を読む
  var tblSnippet = comboReadTableSnippet_(ss, curSheet, table);
  var planHintObj = (typeof plan !== 'undefined' && plan) ? {
    ops: Array.isArray(plan.ops) ? plan.ops : [],
    reasons: Array.isArray(plan.reasons) ? plan.reasons : [],
    missing: Array.isArray(plan.missing) ? plan.missing : [],
    cards: Array.isArray(plan.cards) ? plan.cards.map(function (c) { return typeof c === 'string' ? c : (c && c.name); }).filter(Boolean) : []
  } : null;
  var hasApiKey = (cfg.aiMode === 'api_gemini' || cfg.aiMode === 'api_claude') && !!comboResolveApiKey_(cfg);
  if (hasApiKey) {
    try {
      var aiRes = comboCallAiApi_(cfg, askText, ss, curSheet, selection, table, sheets, {
        readOnly: isReadOnlyAsk,
        snippet: tblSnippet,
        plan: planHintObj
      });
      if (isReadOnlyAsk || (aiRes && aiRes.action === 'reply')) {
        // 守り: 読むだけモードでは ops が混入していても絶対に実行せず reply のみ返す
        var repMsg = (aiRes && aiRes.message) ? String(aiRes.message) : '読むだけの質問のためシートは変更しませんでした。';
        if (tblSnippet && tblSnippet.truncated && tblSnippet.note && repMsg.indexOf('抜粋') < 0) {
          repMsg += '\n' + tblSnippet.note;
        }
        return {
          ok: true,
          source: 'ai_reply',
          readOnly: isReadOnlyAsk,
          text: (isReadOnlyAsk ? '[読むだけ]\n' : '[AI返答]\n') + repMsg,
          gasMs: Date.now() - t0
        };
      }
      if (aiRes && Array.isArray(aiRes.ops) && aiRes.ops.length) {
        var aud1 = comboSanitizeAndAuditAiOps_(aiRes.ops, askText, table);
        if (!aud1.ok) {
          var retryAsk = askText + '\n（前の答えの ops は守りの監査で止まりました: ' + aud1.issues.join(' ／ ') + '。表にある列名と頼みに合う棚・引数だけで直し、安全にできない・曖昧なら reply で聞き返してください）';
          aiRes = comboCallAiApi_(cfg, retryAsk, ss, curSheet, selection, table, sheets, {
            readOnly: isReadOnlyAsk,
            snippet: tblSnippet,
            plan: planHintObj
          });
          if (aiRes && aiRes.action === 'reply') {
            return {
              ok: true,
              source: 'ai_reply',
              readOnly: false,
              text: '[AI返答]\n' + String(aiRes.message || ''),
              gasMs: Date.now() - t0
            };
          }
          aud1 = comboSanitizeAndAuditAiOps_(aiRes && aiRes.ops, askText, table);
          if (!aud1.ok) {
            var audMsg = 'AI の手順が守りの監査で止まりました: ' + aud1.issues.join(' ／ ');
            return { ok: false, error: audMsg, text: audMsg, gasMs: Date.now() - t0 };
          }
        }
        var safeOps = aud1.ops;
        var execRes = comboRunOps({
          ops: safeOps,
          ok: !!req.ok,
          backup: !!req.backup,
          fastUndo: req.fastUndo,
          sheet: curSheet,
          selection: selection,
          table: table,
          sheets: sheets,
          targetId: ssId,
          _ss: ss,
          _ssName: ssName,
          _cached: cached
        });
        var noteHead = '[AI解釈]' + (aiRes.note ? ' ' + aiRes.note : '');
        execRes.source = 'ai_api';
        execRes.aiOps = safeOps;
        execRes.aiNote = aiRes.note || '';
        execRes.text = noteHead + '\n' + execRes.text;
        execRes.gasMs = Date.now() - t0;
        return execRes;
      }
      return { ok: false, error: 'AI が実行可能な ops を返しませんでした', text: 'エラー: AI が実行可能な ops を返しませんでした', gasMs: Date.now() - t0 };
    } catch (errAi) {
      return {
        ok: false,
        error: String(errAi && errAi.message || errAi),
        text: 'AI解釈エラー: ' + String(errAi && errAi.message || errAi),
        gasMs: Date.now() - t0
      };
    }
  }

  // 鍵が無いとき：この窓からは AI を呼べない（PC の Claude Code は Chrome 拡張のサイドパネルから直結で使う）
  return { ok: false, error: COMBO_NO_AI_MSG, text: COMBO_NO_AI_MSG, gasMs: Date.now() - t0 };
}

// ---------------------------------------------------------------- 棚検索・アンドゥ・設定

/**
 * 棚の札を検索する。
 * @param {Object} req { ask, kind }
 */
function comboFind(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    var ask = String(req.ask || '').trim();
    var kind = String(req.kind || 'sheet').trim();
    if (typeof ComboPlanner !== 'undefined') {
      var text = (typeof ComboPlanner.ask === 'function')
        ? ComboPlanner.ask(ask, kind)
        : String(ComboPlanner.find(ask, kind) || '');
      return { ok: true, text: text, gasMs: Date.now() - t0 };
    }
    var list = Array.isArray(COMBO_MINI_SHELVES) ? COMBO_MINI_SHELVES : [];
    var hits = list.filter(function (s) {
      if (!ask) return true;
      var hay = (s.name || '') + ' ' + (s.t || s.title || '') + ' ' + (s.a || s.args_raw || '');
      return hay.indexOf(ask) >= 0;
    }).slice(0, 15).map(function (s) {
      return '- ' + s.name + ': ' + (s.t || s.title || '') + ' (' + (s.a || s.args_raw || 'なし') + ')';
    });
    var fbText = hits.length ? ('棚一覧（軽量検索）:\n' + hits.join('\n')) : ('該当する棚が見つかりませんでした: ' + ask);
    return { ok: true, text: fbText, gasMs: Date.now() - t0 };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err), text: 'エラー: ' + String(err && err.message || err), gasMs: Date.now() - t0 };
  }
}

/**
 * 直前の操作を取り消す（高速スナップショットがあれば即時復元、無ければ Engine の actUndo_ を呼ぶ）。
 * @param {Object} req { ok, to, targetId }
 */
function comboUndo(req) {
  var t0 = Date.now();
  req = req || {};
  try {
    if (comboIsDocReq_(req)) {
      var docU = comboOpenDoc_(req);
      var resDoc = actUndo_({
        target_id: docU.getId(),
        ok: !!req.ok,
        to: req.to ? String(req.to) : ''
      });
      var td = resDoc.target || {};
      if (resDoc.ok) {
        resDoc.text = [
          '対象: [文書] ' + (td.name || docU.getName()),
          '戻した: #' + resDoc.undone + '（' + (resDoc.what || '') + '）を取り消しました',
          '控え #' + resDoc.backup + '（もう一度 戻す で元に戻せます）'
        ].join('\n');
      } else {
        resDoc.text = (resDoc.needs_ok ? '止めました: ' : '戻せませんでした: ') + (resDoc.error || '');
      }
      resDoc.oauthToken = comboGetOAuthToken_();
      resDoc.gasMs = Date.now() - t0;
      return resDoc;
    }
    var ss = comboOpenSs_(req);
    if (!req.to) {
      var cUndo = comboCache_();
      var fastRaw = cUndo ? cUndo.get(COMBO_PROP_FAST_UNDO) : null;
      if (!fastRaw) {
        try { fastRaw = PropertiesService.getScriptProperties().getProperty(COMBO_PROP_FAST_UNDO); } catch (eP) {}
      }
      if (fastRaw) {
        var fastRes = comboFastUndoRestore_(ss, fastRaw);
        if (fastRes.ok || String(fastRes.error || '').indexOf('現在のスプレッドシート') < 0) {
          fastRes.gasMs = Date.now() - t0;
          return fastRes;
        }
      }
    }
    var res = actUndo_({
      target_id: ss.getId(),
      ok: !!req.ok,
      to: req.to ? String(req.to) : ''
    });
    var t = res.target || {};
    if (res.ok) {
      comboCacheInvalidate_(ss.getId(), t.sheet || '');
      res.text = [
        '対象: ' + (t.name || ss.getName()),
        '戻した: #' + res.undone + '（' + (res.what || '') + '）を取り消しました',
        '控え #' + res.backup + '（もう一度 戻す で元に戻せます）'
      ].join('\n');
    } else {
      res.text = (res.needs_ok ? '止めました: ' : '戻せませんでした: ') + (res.error || '');
    }
    res.oauthToken = comboGetOAuthToken_();
    res.gasMs = Date.now() - t0;
    return res;
  } catch (err) {
    return {
      ok: false,
      error: String(err && err.message || err),
      text: '戻せませんでした: ' + String(err && err.message || err),
      gasMs: Date.now() - t0
    };
  }
}

function comboGetRawConfig_(optAllProps) {
  var def = {
    aiMode: 'local',
    aiModel: 'sonnet',
    apiKey: '',
    geminiKey: '',
    claudeKey: '',
    bridgeToken: '',
    backupDefault: false
  };
  try {
    // 設定（API 鍵を含む）は人ごとの置き場に置く。ライブラリ全体の置き場だと、同じライブラリを使う別の人がその鍵で AI を呼べてしまう
    var raw = optAllProps ? optAllProps[COMBO_PROP_CONFIG] : PropertiesService.getUserProperties().getProperty(COMBO_PROP_CONFIG);
    if (!raw) return def;
    var parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      Object.keys(def).forEach(function (k) {
        if (parsed[k] !== undefined) def[k] = parsed[k];
      });
    }
  } catch (e) {}
  return def;
}

function comboSanitizeConfig_(raw) {
  return {
    aiMode: (!raw.aiMode || raw.aiMode === 'postbox') ? 'local' : raw.aiMode,
    aiModel: raw.aiModel || 'sonnet',
    backupDefault: !!raw.backupDefault,
    // 拡張の直結の合い言葉（人ごとの設定にだけ置く。本人の操作窓だけが受け取り、拡張へ頼みと一緒に渡す）
    bridgeToken: String(raw.bridgeToken || ''),
    hasApiKey: !!comboResolveApiKey_(raw),
    hasGeminiKey: !!comboResolveApiKey_({ aiMode: 'api_gemini', geminiKey: raw.geminiKey, apiKey: raw.apiKey }),
    hasClaudeKey: !!comboResolveApiKey_({ aiMode: 'api_claude', claudeKey: raw.claudeKey, apiKey: raw.apiKey })
  };
}

/**
 * 設定を UserProperties（人ごと）から読み込む（APIキー自体はクライアントへ露出せず有無フラグを返す）。
 */
function comboGetConfig() {
  return comboSanitizeConfig_(comboGetRawConfig_());
}

/**
 * 設定を UserProperties（人ごと）へ保存する。
 * @param {Object} cfg
 */
function comboSaveConfig(cfg) {
  cfg = cfg || {};
  var cur = comboGetRawConfig_();
  ['aiMode', 'aiModel', 'apiKey', 'geminiKey', 'claudeKey', 'bridgeToken', 'backupDefault'].forEach(function (k) {
    if (cfg[k] !== undefined) cur[k] = cfg[k];
  });
  cur.backupDefault = !!cur.backupDefault;
  PropertiesService.getUserProperties().setProperty(COMBO_PROP_CONFIG, JSON.stringify(cur));
  return { ok: true, config: comboSanitizeConfig_(cur) };
}

var COMBO_NO_AI_MSG = 'ローカル直結（Claude Code）は、Chrome 拡張「GASコンボ ブラウザ連動」のサイドパネルから使えます。この窓から AI を使うときは、設定タブで Gemini API か Claude API の鍵を入れてください（棚で済む頼みは今のまま動きます）。';

/**
 * 軽量ピン（V8 Isolate 起動時間＋通信往復時間の計測用）。
 */
function comboPing() {
  return { ok: true, ts: Date.now() };
}

