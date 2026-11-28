// GASコンボ ブラウザ連動 - Background Service Worker
// Content Script から受け取った選択セル・シート・ファイル情報をローカルの GASコンボ (127.0.0.1:18765) へ送信する

const SYNC_URL = "http://127.0.0.1:18765/sync";
const DIRECT_SYNC_URL = "http://127.0.0.1:18766/sync";
const MCP_SYNC_URL = "http://127.0.0.1:18767/sync";
const DIRECT_PING_URL = "http://127.0.0.1:18766/ping";
const DIRECT_HEALTH_URL = "http://127.0.0.1:18766/health";
const DIRECT_RESOLVE_URL = "http://127.0.0.1:18766/resolve";
const DIRECT_RESOLVE_STREAM_URL = "http://127.0.0.1:18766/resolve-stream";
const DIRECT_RECORDED_URL = "http://127.0.0.1:18766/recorded-macros";
const NATIVE_HOST_NAME = "com.shu.gas_combo_host";

let _ensuringWatcherPromise = null;
function ensureLocalWatcherRunning() {
  if (_ensuringWatcherPromise) return _ensuringWatcherPromise;
  _ensuringWatcherPromise = new Promise((resolve) => {
    try {
      if (!chrome.runtime || typeof chrome.runtime.sendNativeMessage !== "function") {
        resolve({ ok: false, error: "nativeMessaging unavailable" });
        return;
      }
      chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, { action: "ensure_watch" }, (resp) => {
        const err = chrome.runtime.lastError;
        if (err) {
          resolve({ ok: false, error: String(err.message || err) });
          return;
        }
        resolve(resp && typeof resp === "object" ? resp : { ok: false, error: "empty_response" });
      });
    } catch (e) {
      resolve({ ok: false, error: String((e && e.message) || e) });
    }
  }).finally(() => {
    _ensuringWatcherPromise = null;
  });
  return _ensuringWatcherPromise;
}

// スプレッドシートID と Apps Script エディタの scriptId の自動紐付け
const SHEET_URL_RE = /docs\.google\.com\/spreadsheets\/d\/([\w-]{20,})/;
const DOC_URL_RE = /docs\.google\.com\/document\/d\/([\w-]{20,})/;
const SCRIPT_URL_RE = /script\.google\.com\/(?:u\/\d+\/)?(?:home\/projects|d)\/([A-Za-z0-9_-]{20,})/;

function _stripDocsTitleSuffix(title) {
  return String(title || "")
    .replace(/\s*-\s*Google\s*(スプレッドシート|ドキュメント|Sheets|Docs)\s*$/i, "")
    .trim();
}

async function recordTabContextUrl(url, title) {
  const u = String(url || "");
  if (!u) return;
  const sm = u.match(SHEET_URL_RE);
  if (sm) {
    try {
      await chrome.storage.local.set({ lastSheetId: sm[1] });
    } catch (_e) {}
    const mg = u.match(/[#?&]gid=([0-9]+)/);
    postToGasCombo({
      id: sm[1],
      kind: "sheet",
      url: u,
      gid: mg ? mg[1] : "",
      name: _stripDocsTitleSuffix(title),
      partial: true,
      force: true,
      ts: Date.now() / 1000,
    });
    return;
  }
  const dm = u.match(DOC_URL_RE);
  if (dm) {
    postToGasCombo({
      id: dm[1],
      kind: "doc",
      url: u,
      gid: "",
      name: _stripDocsTitleSuffix(title),
      partial: true,
      force: true,
      ts: Date.now() / 1000,
    });
    return;
  }
  const gm = u.match(SCRIPT_URL_RE);
  if (gm) {
    const scriptId = gm[1];
    try {
      const st = await chrome.storage.local.get(["lastSheetId", "sheetScriptMap"]);
      const map = (st && st.sheetScriptMap && typeof st.sheetScriptMap === "object") ? st.sheetScriptMap : {};
      if (st && st.lastSheetId) {
        map[st.lastSheetId] = scriptId;
      }
      await chrome.storage.local.set({ lastScriptId: scriptId, sheetScriptMap: map });
    } catch (_e) {}
  }
}

async function detectScriptIdForSheet(ssId, explicitScriptId) {
  if (explicitScriptId) return String(explicitScriptId).trim();
  // 1. 現在開いているタブの中から Apps Script エディタのタブを探す
  try {
    const tabs = await chrome.tabs.query({});
    const scriptTabs = [];
    for (const t of tabs || []) {
      const m = String((t && t.url) || "").match(SCRIPT_URL_RE);
      if (m) scriptTabs.push({ id: m[1], lastAccessed: t.lastAccessed || 0 });
    }
    if (scriptTabs.length) {
      scriptTabs.sort((a, b) => b.lastAccessed - a.lastAccessed);
      const picked = scriptTabs[0].id;
      if (ssId) {
        const st = await chrome.storage.local.get(["sheetScriptMap"]);
        const map = (st && st.sheetScriptMap && typeof st.sheetScriptMap === "object") ? st.sheetScriptMap : {};
        map[ssId] = picked;
        await chrome.storage.local.set({ sheetScriptMap: map, lastScriptId: picked });
      }
      return picked;
    }
  } catch (_e) {}
  // 2. 過去にこのシートで開いた Apps Script の記憶を見る
  if (ssId) {
    try {
      const st = await chrome.storage.local.get(["sheetScriptMap"]);
      const map = (st && st.sheetScriptMap && typeof st.sheetScriptMap === "object") ? st.sheetScriptMap : {};
      if (map[ssId]) return String(map[ssId]);
    } catch (_e) {}
  }
  return "";
}

async function fetchRecordedMacrosViaDirect(payload, _retried) {
  const ssId = String((payload && payload.ssId) || "").trim();
  const scriptId = await detectScriptIdForSheet(ssId, payload && payload.scriptId);
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 20000);
  try {
    const res = await fetch(DIRECT_RECORDED_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssId, scriptId }),
      cache: "no-store",
      signal: ac.signal,
    });
    const data = await res.json().catch(() => null);
    if (!data || data.direct !== true) {
      return { reachable: false };
    }
    return { reachable: true, data };
  } catch (e) {
    if (e && e.name === "AbortError") {
      return { reachable: true, ok: false, error: "記録マクロの取得が時間切れになりました (20秒)" };
    }
    if (!_retried) {
      const woken = await ensureLocalWatcherRunning();
      if (woken && woken.ok) {
        return await fetchRecordedMacrosViaDirect(payload, true);
      }
    }
    return { reachable: false, error: String((e && e.message) || e) };
  } finally {
    clearTimeout(timer);
  }
}

// 拡張のファイル（フォルダの今の中身）の指紋。道具が拡張を直したかを見分ける（自分で入れ直しはしない）
const STAMP_FILES = ["manifest.json", "background.js", "content.js", "direct_bridge.js", "sidepanel.js", "sidepanel.html"];
async function diskStamp() {
  let h = 0;
  for (const f of STAMP_FILES) {
    try {
      const t = await (await fetch(chrome.runtime.getURL(f), { cache: "no-store" })).text();
      for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0;
    } catch (_e) {}
  }
  return String(h);
}

// 入れたとき・入れ直したときの指紋を覚える（サイドパネルはこれとフォルダの今の中身を比べる）
chrome.runtime.onInstalled.addListener(async () => {
  chrome.storage.local.set({ stamp: await diskStamp() });
});

async function postToGasCombo(payload) {
  const body = JSON.stringify(payload);
  const targets = [SYNC_URL, MCP_SYNC_URL, DIRECT_SYNC_URL];
  const results = await Promise.allSettled(
    targets.map((url) =>
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      })
    )
  );
  return results.some((r) => r.status === "fulfilled" && r.value && r.value.ok);
}

async function resolveViaDirectLocal(payload, _retried) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 65000);
  try {
    const res = await fetch(DIRECT_RESOLVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
      cache: "no-store",
      signal: ac.signal,
    });
    const data = await res.json().catch(() => null);
    if (!data || data.direct !== true) {
      return { reachable: false };
    }
    return { reachable: true, data };
  } catch (e) {
    if (e && e.name === "AbortError") {
      return { reachable: true, ok: false, error: "AI の返事が 65 秒たっても届きませんでした。もう一度実行してください" };
    }
    if (!_retried) {
      const woken = await ensureLocalWatcherRunning();
      if (woken && woken.ok) {
        return await resolveViaDirectLocal(payload, true);
      }
    }
    return { reachable: false, error: String((e && e.message) || e) };
  } finally {
    clearTimeout(timer);
  }
}

async function pingDirectLocal(_retried) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 3000);
  try {
    let res = await fetch(DIRECT_HEALTH_URL, { cache: "no-store", signal: ac.signal });
    let data = await res.json().catch(() => null);
    if (!data || !data.ok) {
      res = await fetch(DIRECT_PING_URL, { cache: "no-store", signal: ac.signal });
      data = await res.json().catch(() => null);
    }
    if (!data || !data.ok) {
      return { reachable: false, error: "ローカル受け手から正常な応答がありません" };
    }
    return { reachable: true, data, recovered: !!_retried };
  } catch (e) {
    if (!_retried) {
      const woken = await ensureLocalWatcherRunning();
      if (woken && woken.ok) {
        return await pingDirectLocal(true);
      }
      return { reachable: false, error: String((woken && woken.error) || (e && e.message) || e) };
    }
    return { reachable: false, error: String((e && e.message) || e) };
  } finally {
    clearTimeout(timer);
  }
}

const STREAM_CUT_MSG = "AI の返事を待つ途中で切れました。PC 側ではまだ続いているか、もう撃ち終わっているかもしれません。同じ頼みを撃ち直す前に、シートを見て確かめてください";

async function streamResolveViaDirectLocal(port, payload) {
  const ac = new AbortController();
  // 待ちは「知らせが 30 秒途切れたら」切る（受け手は 5 秒ごとに経過を送る）。全体の上限は 150 秒
  const IDLE_MS = 30000, HARD_MS = 150000;
  const tStart = Date.now();
  let timer = setTimeout(() => ac.abort(), IDLE_MS);
  const rearm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => ac.abort(), Math.max(1000, Math.min(IDLE_MS, HARD_MS - (Date.now() - tStart))));
  };
  // 受け手に頼みが届いた（流れが始まった）後は、途中で切れても同じ頼みを送り直さない＝シートに 2 回撃たない
  let streamStarted = false;
  let disconnected = false;
  try {
    port.onDisconnect.addListener(() => {
      disconnected = true;
      try { ac.abort(); } catch (_e) {}
    });
  } catch (_e) {}

  const post = (m) => {
    if (disconnected) return;
    try { port.postMessage(m); } catch (_e) { disconnected = true; }
  };
  // AI を待つ間に裏方（service worker）が 30 秒の居眠りで畳まれないよう、拡張の API を定期的に叩いて起こしておく
  const keepAlive = setInterval(() => {
    try { chrome.runtime.getPlatformInfo(() => { void chrome.runtime.lastError; }); } catch (_e) {}
  }, 10000);

  try {
    const res = await fetch(DIRECT_RESOLVE_STREAM_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
      cache: "no-store",
      signal: ac.signal,
    });
    const ct = String((res.headers && res.headers.get("content-type")) || "").toLowerCase();
    if (res.ok && res.body && typeof res.body.getReader === "function" && ct.indexOf("ndjson") >= 0) {
      streamStarted = true;
      rearm();
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let doneResult = null;
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        rearm();
        buf += decoder.decode(chunk.value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let ev = null;
          try { ev = JSON.parse(line); } catch (_e) {}
          if (!ev) continue;
          if (ev.type === "done" && ev.result) {
            // 答えが来たらその場で渡す（受け手が接続を閉じるのを待たない）
            post({ type: "done", reachable: true, data: ev.result });
            try { reader.cancel(); } catch (_e) {}
            return;
          } else {
            post({ type: "progress", event: ev });
          }
        }
      }
      if (buf.trim()) {
        try {
          const lastEv = JSON.parse(buf.trim());
          if (lastEv && lastEv.type === "done" && lastEv.result) doneResult = lastEv.result;
          else if (lastEv) post({ type: "progress", event: lastEv });
        } catch (_e) {}
      }
      if (doneResult) {
        post({ type: "done", reachable: true, data: doneResult });
        return;
      }
      post({ type: "done", reachable: true, ok: false, error: STREAM_CUT_MSG });
      return;
    }
    // 非対応または旧受け手の場合は通常の /resolve へ自動フォールバック
    const fb = await resolveViaDirectLocal(payload || {});
    post(Object.assign({ type: "done" }, fb));
  } catch (e) {
    if (disconnected) return;
    if (e && e.name === "AbortError") {
      post({ type: "done", reachable: true, ok: false, error: streamStarted ? STREAM_CUT_MSG : "PC 側の AI 窓口から返事がありません。もう一度実行してください" });
      return;
    }
    if (streamStarted) {
      post({ type: "done", reachable: true, ok: false, error: STREAM_CUT_MSG });
      return;
    }
    const fb = await resolveViaDirectLocal(payload || {});
    post(Object.assign({ type: "done" }, fb));
  } finally {
    clearTimeout(timer);
    clearInterval(keepAlive);
  }
}

chrome.runtime.onConnect.addListener((port) => {
  if (!port || port.name !== "GAS_COMBO_DIRECT_STREAM") return;
  port.onMessage.addListener((msg) => {
    if (msg && msg.type === "START") {
      streamResolveViaDirectLocal(port, msg.payload || {});
    }
  });
});

const _lastSheetById = {};
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "GAS_COMBO_SYNC" && msg.payload) {
    const p = msg.payload;
    if (p.kind === "sheet" && p.id && p.sheet && _lastSheetById[p.id] !== p.sheet) {
      _lastSheetById[p.id] = p.sheet;
      try {
        chrome.runtime.sendMessage({ type: "GAS_COMBO_SHEET_CHANGED", id: p.id, sheet: p.sheet }, () => {
          void chrome.runtime.lastError;
        });
      } catch (_e) {}
    }
    postToGasCombo(p).then((ok) => {
      sendResponse({ ok });
    });
    return true;
  }
  if (msg && msg.type === "GAS_COMBO_GET_TOKEN_BG") {
    fetch(chrome.runtime.getURL("combo_window.json"), { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => sendResponse({ token: String((j && j.token) || "") }))
      .catch(() => sendResponse({ token: "" }));
    return true;
  }
  if (msg && msg.type === "GAS_COMBO_PING_LOCAL_BG") {
    pingDirectLocal(false).then((res) => {
      sendResponse(res);
    });
    return true;
  }
  if (msg && msg.type === "GAS_COMBO_DIRECT_AI_BG") {
    resolveViaDirectLocal(msg.payload || {}).then((res) => {
      sendResponse(res);
    });
    return true;
  }
  if (msg && msg.type === "GAS_COMBO_FETCH_RECORDED_BG") {
    fetchRecordedMacrosViaDirect(msg.payload || {}).then((res) => {
      sendResponse(res);
    });
    return true;
  }
  return false;
});

// ブラウザのタブを切り替えた瞬間に、そのタブのスプレッドシート／文書の状態を即座に同期させる
chrome.tabs.onActivated.addListener((activeInfo) => {
  try {
    chrome.tabs.get(activeInfo.tabId, (tab) => {
      void chrome.runtime.lastError;
      if (tab && tab.url) recordTabContextUrl(tab.url, tab.title);
    });
    chrome.tabs.sendMessage(activeInfo.tabId, { type: "GAS_COMBO_PING" }, () => {
      // 対象外のタブ（Google以外のページ等）で発生する lastError を握りつぶす
      void chrome.runtime.lastError;
    });
  } catch (_e) {
    // ignore
  }
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  const url = (changeInfo && changeInfo.url) || (tab && tab.url);
  if (url && (!tab || tab.active)) recordTabContextUrl(url, (tab && tab.title) || "");
});

// ---------------------------------------------------------------- サイドパネルで GASコンボを開く
// 拡張のアイコン（または Alt+G）で、ブラウザの右のサイドパネルを開く。中身は sidepanel.html（今のタブのシートを相手にする）
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
