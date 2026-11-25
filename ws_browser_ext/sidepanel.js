// GASコンボ サイドパネル：今のタブのスプレッドシートを相手に、アドオンの画面（/dev）を中に開く。
// 窓の番地は py gas.py combo addon が combo_window.json に書く（人ごとに違う）。タブを替えたら相手も替える。
const frame = document.getElementById("combo");
const msg = document.getElementById("msg");
let curId = "";

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

// フォルダの中身が入れたときと違っても、自分で入れ直さない（chrome.runtime.reload）。
// パッケージ化していない拡張は、入れ直しにしくじると Chrome の一覧から消えてしまう（2026-11-25 に起きた）。
// 指紋だけ覚え直す。サイドパネル・シートの中継はページを開き直せば新しい中身で動く。
(async () => {
  try {
    const cur = await diskStamp();
    const { stamp } = await chrome.storage.local.get("stamp");
    if (stamp !== cur) chrome.storage.local.set({ stamp: cur });
  } catch (_e) {}
})();

function show(text) {
  msg.textContent = text;
  msg.style.display = "block";
  frame.style.display = "none";
}

async function base() {
  try {
    const res = await fetch(chrome.runtime.getURL("combo_window.json"), { cache: "no-store" });
    if (!res.ok) return "";
    const j = await res.json();
    return String((j && j.base) || "");
  } catch (_e) {
    return "";
  }
}

async function refresh() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const m = String((tab && tab.url) || "").match(/docs\.google\.com\/spreadsheets\/d\/([\w-]+)/);
  if (!m) { if (!curId) show("スプレッドシートのタブで開くと、そのシートを相手に GASコンボが使えます。"); return; }
  if (m[1] === curId) return;
  const b = await base();
  if (!b) { show("GASコンボの画面の番地がまだありません。AI に「GASコンボを入れて」と頼む（py gas.py combo addon）と番地が入るので、その後このサイドパネルを閉じて開き直してください。"); return; }
  curId = m[1];
  frame.src = b + (b.indexOf("?") >= 0 ? "&" : "?") + "id=" + encodeURIComponent(curId) + "&z=1";
  msg.style.display = "none";
  frame.style.display = "block";
}

// GASコンボの画面から「直した所」へ移る頼みや、今の選択範囲の問い合わせが来たら、今のタブのシートへ渡す
const GOOGLE_SANDBOX_RE = /^https:\/\/[a-z0-9-]+\.googleusercontent\.com$/i;
function isAllowedSidepanelOrigin(origin) {
  const o = String(origin || "");
  return o === "https://script.google.com" || GOOGLE_SANDBOX_RE.test(o);
}

// 直結の合い言葉（combo_window.json）。本人の操作窓だけが同じ物を持つ
async function bridgeToken() {
  try {
    const res = await fetch(chrome.runtime.getURL("combo_window.json"), { cache: "no-store" });
    if (!res.ok) return "";
    const j = await res.json();
    return String((j && j.token) || "");
  } catch (_e) {
    return "";
  }
}
const NEEDS_TOKEN = { GAS_COMBO_PING_LOCAL: 1, GAS_COMBO_DIRECT_AI: 1, GAS_COMBO_FETCH_RECORDED_MACROS: 1 };

window.addEventListener("message", async (ev) => {
  const d = ev && ev.data;
  if (!d || !isAllowedSidepanelOrigin(ev.origin)) return;
  if (NEEDS_TOKEN[d.type]) {
    const t = await bridgeToken();
    if (!t || d.token !== t) return;
  }
  const targetOrigin = ev.origin && ev.origin !== "null" ? ev.origin : "*";
  if (d.type === "GAS_COMBO_PING_LOCAL") {
    const reqId = String(d.reqId || "");
    const replyDone = (obj) => {
      try { ev.source.postMessage(Object.assign({ type: "GAS_COMBO_PING_LOCAL_DONE", reqId, inExtension: true }, obj), targetOrigin); } catch (_e) {}
    };
    try { ev.source.postMessage({ type: "GAS_COMBO_PING_LOCAL_ACK", reqId }, targetOrigin); } catch (_e) {}
    chrome.runtime.sendMessage({ type: "GAS_COMBO_PING_LOCAL_BG" }, (resp) => {
      if (chrome.runtime.lastError) {
        replyDone({ reachable: false, error: String(chrome.runtime.lastError.message || "extension_error") });
        return;
      }
      replyDone(resp || { reachable: false });
    });
    return;
  }
  if (d.type === "GAS_COMBO_DIRECT_AI") {
    const reqId = String(d.reqId || "");
    const replyDone = (obj) => {
      try { ev.source.postMessage(Object.assign({ type: "GAS_COMBO_DIRECT_AI_DONE", reqId, inExtension: true }, obj), targetOrigin); } catch (_e) {}
    };
    try { ev.source.postMessage({ type: "GAS_COMBO_DIRECT_AI_ACK", reqId }, targetOrigin); } catch (_e) {}
    chrome.runtime.sendMessage({ type: "GAS_COMBO_DIRECT_AI_BG", payload: d.payload || {} }, (resp) => {
      if (chrome.runtime.lastError) {
        replyDone({ reachable: false, error: String(chrome.runtime.lastError.message || "extension_error") });
        return;
      }
      replyDone(resp || { reachable: false });
    });
    return;
  }
  if (d.type === "GAS_COMBO_FETCH_RECORDED_MACROS") {
    const reqId = String(d.reqId || "");
    const replyDone = (obj) => {
      try { ev.source.postMessage(Object.assign({ type: "GAS_COMBO_FETCH_RECORDED_DONE", reqId, inExtension: true }, obj), targetOrigin); } catch (_e) {}
    };
    try { ev.source.postMessage({ type: "GAS_COMBO_FETCH_RECORDED_ACK", reqId }, targetOrigin); } catch (_e) {}
    chrome.runtime.sendMessage({ type: "GAS_COMBO_FETCH_RECORDED_BG", payload: d.payload || {} }, (resp) => {
      if (chrome.runtime.lastError) {
        replyDone({ reachable: false, error: String(chrome.runtime.lastError.message || "extension_error") });
        return;
      }
      replyDone(resp || { reachable: false });
    });
    return;
  }
  if (d.type === "GAS_COMBO_GET_SEL") {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const replySel = (ok, range, sheet) => {
      try { ev.source.postMessage({ type: "GAS_COMBO_GET_SEL_DONE", ok: !!ok, range: range || "", sheet: sheet || "" }, targetOrigin); } catch (_e) {}
    };
    if (!tab || !tab.id) { replySel(false, "", ""); return; }
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const box = document.querySelector("#t-name-box") || document.querySelector("input.waffle-name-box");
        const range = box ? String(box.value || "").trim() : "";
        const tabEl = document.querySelector(".docs-sheet-active-tab .docs-sheet-tab-name");
        const sheet = tabEl ? String(tabEl.textContent || "").trim() : "";
        return { range, sheet };
      },
    }).then((r) => {
      const res = (r && r[0] && r[0].result) || {};
      replySel(!!res.range, res.range || "", res.sheet || "");
    }).catch(() => replySel(false, "", ""));
    return;
  }
  if (d.type !== "GAS_COMBO_GOTO" || !d.range) return;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const reply = (ok, why) => { try { ev.source.postMessage({ type: "GAS_COMBO_GOTO_DONE", ok, why: why || "" }, targetOrigin); } catch (_e) {} };
  if (!tab || !tab.id) { reply(false, "シートのタブが見つかりません"); return; }
  // 拡張を再読み込みした後もシートのタブを開き直さずに効くよう、頼みのたびに差し込んで撃つ
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [String(d.range)],
    func: (range) => {
      const box = document.querySelector("#t-name-box") || document.querySelector("input.waffle-name-box");
      if (!box) return false;
      box.focus();
      box.value = range;
      box.dispatchEvent(new Event("input", { bubbles: true }));
      for (const type of ["keydown", "keypress", "keyup"]) {
        box.dispatchEvent(new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
      }
      return true;
    },
  }).then((r) => {
    const ok = !!(r && r[0] && r[0].result);
    reply(ok, ok ? "" : "シートの名前ボックスが見つかりません");
  }).catch((e) => reply(false, String((e && e.message) || e)));
});

chrome.tabs.onActivated.addListener(refresh);
chrome.tabs.onUpdated.addListener((_id, info) => { if (info.url || info.status === "complete") refresh(); });
refresh();
