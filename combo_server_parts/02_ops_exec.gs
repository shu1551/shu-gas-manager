// ---------------------------------------------------------------- ops 実行・報告整形

function comboFormatOpsShort_(ops) {
  if (typeof ComboPlanner !== 'undefined' && typeof ComboPlanner.formatOpsShort === 'function') {
    return ComboPlanner.formatOpsShort(ops);
  }
  return (ops || []).map(function (o) {
    var args = Object.keys(o).filter(function (k) { return k !== 'shelf'; }).map(function (k) {
      return k + '=' + JSON.stringify(o[k]);
    }).join(', ');
    return (o.shelf || '?') + '(' + args + ')';
  }).join(', ');
}

function comboFormatDoText_(res, backupOn) {
  var tgt = res.target || {};
  var head = '対象: ' + (tgt.name || '(名前なし)') + (tgt.sheet ? ' › ' + tgt.sheet : '');
  var lines = [head];
  if (res.ok) {
    var ch = res.changed || [];
    if (ch.length) {
      lines.push('直した所: ' + ch.slice(0, 2).join(' ／ ') + (ch.length > 2 ? '（ほか ' + (ch.length - 2) + ' 件）' : ''));
    } else {
      lines.push('直した所: なし');
    }
    var rest = [];
    if (res.notes && res.notes.length) rest.push('メモ: ' + res.notes.slice(0, 3).join(' ／ '));
    if (res.remaining && res.remaining.length) rest.push('残り: ' + res.remaining.slice(0, 3).join(' ／ '));
    if (rest.length) lines.push(rest.join('　'));
    var tail = [];
    if (res.backup) tail.push('控え #' + res.backup + '（戻す で取り消せます）');
    else if (res.fastUndo) tail.push('高速控えあり（戻す で取り消せます）');
    else if (!backupOn) tail.push('控えなし（backup=OFF）');
    if (tail.length) lines.push(tail.join(' ／ '));
    return lines.join('\n');
  }
  if (res.blocked) {
    lines.push('止めました: ' + (res.error || '確認が必要です'));
    lines.push('何も変えていません。「確認なし」にチェックを入れて再実行してください。');
  } else {
    lines.push('失敗: ' + (res.where ? res.where + ' ' : '') + (res.error || '不明なエラー'));
  }
  return lines.join('\n');
}

function comboKeepsShape_(ops) {
  for (var i = 0; i < ops.length; i++) {
    var op = ops[i];
    if (!op || op.shelf === 'api') return false;
    var c = CATALOG[op.shelf];
    if (!c) return false;
    var touch = c.touch || [];
    if (touch.indexOf('値') >= 0 || touch.indexOf('シート構成') >= 0) return false;
  }
  return true;
}

/**
 * ops 配列を直接実行する（backup=false 時はロックや外部控えを省略した 0.5秒以下の高速経路）。
 * @param {Object} req { ops, ok, backup, sheet, selection, table }
 */
function comboRunOps(req) {
  var t0 = Date.now();
  req = req || {};
  var ops = req.ops;
  if (typeof ops === 'string') {
    try { ops = JSON.parse(ops); } catch (e) {
      return { ok: false, error: 'ops が JSON として読めません', text: 'エラー: ops が JSON として読めません', gasMs: Date.now() - t0 };
    }
  }
  if (ops && !Array.isArray(ops) && ops.shelf) ops = [ops];
  if (!Array.isArray(ops) || !ops.length) {
    return { ok: false, error: 'ops が空です', text: 'エラー: ops が空です', gasMs: Date.now() - t0 };
  }

  if (comboIsDocReq_(req)) {
    try {
      var doc = req._doc || comboOpenDoc_(req);
      var docId = String(req.targetId || (req.target && req.target.id) || '').trim() || doc.getId();
      var docName = req.targetName || doc.getName();
      var docUrl = 'https://docs.google.com/document/d/' + docId + '/edit';
      var effOkDoc = !!req.ok || ops.some(function (o) { return !!(o && o.ok === true); });
      if (typeof actDo_ === 'function') {
        var docRes = actDo_({
          target: { id: docId, kind: 'doc' },
          ops: ops,
          ok: effOkDoc,
          backup: !!req.backup
        });
        docRes.oauthToken = comboGetOAuthToken_();
        docRes.text = comboFormatDoText_(docRes, !!req.backup);
        docRes.gasMs = Date.now() - t0;
        return docRes;
      }
      var docCtx = {
        wideKey: '',
        kind: 'doc',
        file: doc,
        ss: null,
        doc: doc,
        ok: effOkDoc,
        changed: [],
        notes: [],
        remaining: [],
        n: 0,
        isNew: false,
        _file: { id: docId, name: docName, url: docUrl }
      };
      for (var di = 0; di < ops.length; di++) {
        var dop = ops[di];
        var dfn = SHELF[dop.shelf];
        if (!dfn) throw new ArgError('棚「' + dop.shelf + '」はありません');
        docCtx.opNo = di + 1;
        docCtx.opName = dop.shelf;
        dfn(docCtx, dop);
      }
      var docOut = {
        ok: true,
        target: { id: docId, name: docName, kind: 'doc', url: docUrl, sheet: '' },
        changed: docCtx.changed,
        notes: docCtx.notes,
        remaining: docCtx.remaining,
        backup: 0,
        oauthToken: comboGetOAuthToken_()
      };
      docOut.text = comboFormatDoText_(docOut, false);
      docOut.gasMs = Date.now() - t0;
      return docOut;
    } catch (errDoc) {
      var docErr = {
        ok: false,
        error: String(errDoc && errDoc.message || errDoc),
        blocked: !!(errDoc && errDoc.isBlocked),
        needs_ok: !!(errDoc && errDoc.isBlocked),
        arg: !!(errDoc && errDoc.isArg),
        target: { id: String(req.targetId || ''), name: req.targetName || '', kind: 'doc', sheet: '' }
      };
      docErr.text = comboFormatDoText_(docErr, false);
      docErr.gasMs = Date.now() - t0;
      return docErr;
    }
  }

  var ss;
  try {
    ss = req._ss || comboOpenSs_(req);
  } catch (errOpen) {
    return { ok: false, error: String(errOpen && errOpen.message || errOpen), text: 'エラー: ' + String(errOpen && errOpen.message || errOpen), gasMs: Date.now() - t0 };
  }
  var ssId = String(req.targetId || (req.target && req.target.id) || '').trim() || ss.getId();
  var ssUrl = 'https://docs.google.com/spreadsheets/d/' + ssId + '/edit';

  var selInfo;
  try {
    selInfo = comboGetSelectionInfo_(ss, req, true);
  } catch (errSel) {
    return { ok: false, error: String(errSel && errSel.message || errSel), text: 'エラー: ' + String(errSel && errSel.message || errSel), gasMs: Date.now() - t0 };
  }
  var curSheet = selInfo.sheet;
  var backupOn = !!req.backup;
  var effOk = !!req.ok || ops.some(function (o) { return !!(o && o.ok === true); });

  // フル控えモード（backup=true）：Engine の actDo_ に委譲
  if (backupOn) {
    try { CacheService.getScriptCache().remove(COMBO_PROP_FAST_UNDO); } catch (eDelC) {}
    try { PropertiesService.getScriptProperties().deleteProperty(COMBO_PROP_FAST_UNDO); } catch (eDel) {}
    var fullRes = actDo_({
      target: { id: ssId, kind: 'sheet', sheet: curSheet },
      ops: ops,
      ok: effOk,
      backup: true,
      want_table: true
    });
    if (fullRes.ok) {
      comboCacheInvalidate_(ssId, curSheet);
      if (fullRes.table !== undefined) {
        comboCachePut_(ssId, (fullRes.target && fullRes.target.sheet) || curSheet, fullRes.table, fullRes.sheets, null, (fullRes.target && fullRes.target.name) || '');
      }
    }
    fullRes.oauthToken = comboGetOAuthToken_();
    fullRes.text = comboFormatDoText_(fullRes, true);
    fullRes.gasMs = Date.now() - t0;
    return fullRes;
  }

  // 高速パス（backup=false）：ロック・外部控えブックなしで即時実行
  var sh = sheetOf_(ss, curSheet, '');
  var needTitleA1 = ops.some(function (o) { return o && o.shelf === 'format' && o.title === true; });
  var hasFrontMeta = !!(req.targetName && req.sheets && req.table !== undefined);
  var hasFrontTitle = !needTitleA1 || !!(req.table && req.table.title_a1);
  var cached = (req._cached !== undefined)
    ? req._cached
    : ((hasFrontMeta && hasFrontTitle) ? null : comboCacheGet_(ssId, curSheet));
  var ssName = req.targetName || req._ssName || (cached && cached.ssName) || ss.getName();
  var table = req.table !== undefined ? req.table : (cached && cached.table ? cached.table : null);
  var sheets = req.sheets || (cached && cached.sheets) || null;
  var keepsShape = comboKeepsShape_(ops);

  // format(title/header) の事前解決：table.title_a1 / header_row を使って titleRange_・needTable_ の重い RPC をゼロ化する
  var titleA1 = (table && table.title_a1) || (cached && cached.titleA1) || '';
  var resolvedOps = ops.map(function (op) {
    if (!op || op.shelf !== 'format') return op;
    if (op.title === true && titleA1) {
      // 1 つのセルのタイトルは表の幅いっぱいの帯で（棚が帯に塗る＝控えも帯ごと取る）
      var bandA1 = titleA1;
      if (op.merge === undefined && titleA1.indexOf(':') < 0 && table && table.last_col) {
        var tm = /^([A-Z]+)(\d+)$/.exec(titleA1);
        if (tm && colNum_(table.last_col) > colNum_(tm[1])) {
          var c0 = Math.min(colNum_(table.first_col || tm[1]), colNum_(tm[1]));
          var c1 = colNum_(table.last_col);
          var rIdx = parseInt(tm[2], 10) - 1;
          var rawRow = (cached && cached.rawTable && cached.rawTable.vals && cached.rawTable.vals[rIdx]) ? cached.rawTable.vals[rIdx].slice(c0 - 1, c1) : null;
          if (!rawRow || rawRow.filter(function (v) { return !isBlank_(v); }).length <= 1) {
            bandA1 = (colNum_(table.first_col || tm[1]) < colNum_(tm[1]) ? table.first_col : tm[1]) + tm[2] + ':' + table.last_col + tm[2];
          }
        }
      }
      var nextOp = Object.assign({}, op, { range: bandA1, title: false });
      if (bandA1 !== titleA1 && (op.align === 'center' || op.align === 'right')) nextOp.align = 'left';
      return nextOp;
    }
    if (op.header === true && table && table.header_row && table.first_col && table.last_col) {
      var hdrA1 = table.first_col + table.header_row + ':' + table.last_col + table.header_row;
      return Object.assign({}, op, { range: hdrA1, header: false });
    }
    return op;
  });

  _TBL_CACHE = {};
  if (cached && cached.rawTable && (keepsShape || !cached.rawTable.headOnly)) {
    _TBL_CACHE[sh.getSheetId()] = cached.rawTable;
  }

  var fastSaved = false;
  var ctx = {
    wideKey: digest_(ssId + '|' + JSON.stringify(ops), FP_VER),
    kind: 'sheet',
    file: ss,
    ss: ss,
    doc: null,
    sheetName: curSheet,
    curSheet: curSheet,
    ok: effOk,
    changed: [],
    notes: [],
    remaining: [],
    createdSheets: [],
    n: 0,
    isNew: false,
    _file: { id: ssId, name: ssName, url: ssUrl }
  };

  try {
    if (req.fastUndo === true) {
      fastSaved = comboFastUndoSave_(sh, resolvedOps, table, ssId);
    }
    if (!keepsShape && _TBL_CACHE) _TBL_CACHE._once = true;
    for (var i = 0; i < resolvedOps.length; i++) {
      var op = resolvedOps[i];
      var fn = SHELF[op.shelf];
      if (!fn) throw new ArgError('棚「' + op.shelf + '」はありません');
      if (fn.kind && fn.kind !== 'sheet') {
        throw new ArgError('棚「' + op.shelf + '」は文書用です（今の相手はスプレッドシート）');
      }
      ctx.opNo = i + 1;
      ctx.opName = op.shelf;
      fn(ctx, op);
      if (!keepsShape) _TBL_CACHE = null;
    }

    var finalSheet = ctx.curSheet || curSheet;
    var sheetInfos = null;
    if (ctx._colInsertGuard && ctx._colInsertBefore && typeof errReport_ === 'function' && typeof errScan_ === 'function') {
      SpreadsheetApp.flush();
      errReport_(ctx, resolvedOps, ctx._colInsertBefore, errScan_(ss));
    }
    if (!keepsShape) {
      SpreadsheetApp.flush();
      comboCacheInvalidate_(ssId, curSheet);
      if (finalSheet !== curSheet) comboCacheInvalidate_(ssId, finalSheet);
      try {
        var finalSh = ss.getSheetByName(finalSheet);
        if (finalSh) {
          var tbNew = findTable_(finalSh);
          table = tbNew ? tableOut_(tbNew) : null;
          var newTitleA1 = comboComputeTitleA1_(finalSh, tbNew);
          if (table && newTitleA1) table.title_a1 = newTitleA1;
          var allSh = ss.getSheets();
          sheets = allSh.map(function (s) { return s.getName(); });
          sheetInfos = allSh.map(function (s) {
            return { name: s.getName(), sheetId: s.getSheetId(), rows: s.getLastRow(), cols: s.getLastColumn() };
          });
          comboCachePut_(ssId, finalSheet, table, sheets, tbNew, ssName, newTitleA1);
        }
      } catch (eTbl) {}
    } else if (!sheets) {
      var allShKeep = ss.getSheets();
      sheets = allShKeep.map(function (s) { return s.getName(); });
      sheetInfos = allShKeep.map(function (s) {
        return { name: s.getName(), sheetId: s.getSheetId(), rows: s.getLastRow(), cols: s.getLastColumn() };
      });
    }

    var out = {
      ok: true,
      target: {
        id: ssId,
        name: ssName,
        kind: 'sheet',
        url: ssUrl,
        sheet: finalSheet
      },
      changed: ctx.changed,
      notes: ctx.notes,
      remaining: ctx.remaining,
      backup: 0,
      fastUndo: fastSaved,
      selection: selInfo.selection || req.selection || '',
      table: table,
      sheets: sheets,
      oauthToken: comboGetOAuthToken_()
    };
    if (sheetInfos) out.sheetInfos = sheetInfos;
    out.text = comboFormatDoText_(out, false);
    out.gasMs = Date.now() - t0;
    return out;
  } catch (err) {
    var colRestored = false;
    if (ctx._colInsertGuard && typeof rollbackColInserts_ === 'function') {
      try { colRestored = rollbackColInserts_(ctx); } catch (eRb) {}
    }
    var errOut = {
      ok: false,
      error: String(err && err.message || err),
      where: '棚 #' + (ctx.opNo || 0) + ' ' + (ctx.opName || ''),
      restored: colRestored,
      blocked: !!(err && err.isBlocked),
      needs_ok: !!(err && err.isBlocked),
      arg: !!(err && err.isArg),
      target: {
        id: ssId,
        name: ssName,
        kind: 'sheet',
        url: ssUrl,
        sheet: ctx.curSheet || curSheet
      }
    };
    errOut.text = comboFormatDoText_(errOut, false);
    errOut.gasMs = Date.now() - t0;
    return errOut;
  } finally {
    _TBL_CACHE = null;
  }
}

