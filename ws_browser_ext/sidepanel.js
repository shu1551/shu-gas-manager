// GASコンボ サイドパネル：今のタブのスプレッドシートを相手に、アドインの画面（/dev）を中に開く。
// 窓の番地は py gas.py combo addon が combo_window.json に書く（人ごとに違う）。タブを替えたら相手も替える。
const frame = document.getElementById("combo");
const msg = document.getElementById("msg");
let curId = "";

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
  if (!b) { show("GASコンボの画面の番地がまだありません。py gas.py combo addon を撃ってから、chrome://extensions でこの拡張を「再読み込み」してください。"); return; }
  curId = m[1];
  frame.src = b + (b.indexOf("?") >= 0 ? "&" : "?") + "id=" + encodeURIComponent(curId) + "&z=1";
  msg.style.display = "none";
  frame.style.display = "block";
}

// GASコンボの画面から「直した所」へ移る頼みが来たら、今のタブのシートへ渡す（名前ボックスに番地を入れる）
window.addEventListener("message", async (ev) => {
  const d = ev && ev.data;
  if (!d || d.type !== "GAS_COMBO_GOTO" || !d.range) return;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (tab && tab.id) chrome.tabs.sendMessage(tab.id, { type: "GAS_COMBO_GOTO", range: String(d.range) }, () => void chrome.runtime.lastError);
});

chrome.tabs.onActivated.addListener(refresh);
chrome.tabs.onUpdated.addListener((_id, info) => { if (info.url || info.status === "complete") refresh(); });
refresh();
