// GASコンボ ブラウザ連動 - Background Service Worker
// Content Script から受け取った選択セル・シート・ファイル情報をローカルの GASコンボ (127.0.0.1:18765) へ送信する

const SYNC_URL = "http://127.0.0.1:18765/sync";
const DIRECT_PING_URL = "http://127.0.0.1:18766/ping";
const DIRECT_RESOLVE_URL = "http://127.0.0.1:18766/resolve";
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
const SCRIPT_URL_RE = /script\.google\.com\/(?:u\/\d+\/)?(?:home\/projects|d)\/([A-Za-z0-9_-]{20,})/;

async function recordTabContextUrl(url) {
  const u = String(url || "");
  if (!u) return;
  const sm = u.match(SHEET_URL_RE);
  if (sm) {
    try {
      await chrome.storage.local.set({ lastSheetId: sm[1] });
    } catch (_e) {}
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

// 拡張のファイル（フォルダの今の中身）の指紋。道具が拡張を直したら、サイドパネルを開いたときに自分で入れ直すのに使う
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
  try {
    const res = await fetch(SYNC_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (_err) {
    // GASコンボ窓が起動していない場合は静かに無視する
    return false;
  }
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
      return { reachable: true, ok: false, error: "ローカル AI が時間切れになりました (65秒)" };
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
    const res = await fetch(DIRECT_PING_URL, { cache: "no-store", signal: ac.signal });
    const data = await res.json().catch(() => null);
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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "GAS_COMBO_SYNC" && msg.payload) {
    postToGasCombo(msg.payload).then((ok) => {
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
      if (tab && tab.url) recordTabContextUrl(tab.url);
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
  if (url) recordTabContextUrl(url);
});

// ---------------------------------------------------------------- サイドパネルで GASコンボを開く
// 拡張のアイコン（または Alt+G）で、ブラウザの右のサイドパネルを開く。中身は sidepanel.html（今のタブのシートを相手にする）
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
