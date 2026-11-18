// GASコンボ ブラウザ連動 - Background Service Worker
// Content Script から受け取った選択セル・シート・ファイル情報をローカルの GASコンボ (127.0.0.1:18765) へ送信する

const SYNC_URL = "http://127.0.0.1:18765/sync";

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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "GAS_COMBO_SYNC" && msg.payload) {
    postToGasCombo(msg.payload).then((ok) => {
      sendResponse({ ok });
    });
    return true;
  }
  return false;
});

// ブラウザのタブを切り替えた瞬間に、そのタブのスプレッドシート／文書の状態を即座に同期させる
chrome.tabs.onActivated.addListener((activeInfo) => {
  try {
    chrome.tabs.sendMessage(activeInfo.tabId, { type: "GAS_COMBO_PING" }, () => {
      // 対象外のタブ（Google以外のページ等）で発生する lastError を握りつぶす
      void chrome.runtime.lastError;
    });
  } catch (_e) {
    // ignore
  }
});

// ---------------------------------------------------------------- 操作窓を 1 回で開く
// 拡張のアイコン（または Alt+G）で、今のタブのスプレッドシートの操作窓（アドインの /dev）を小さな窓で開く。
// 窓の番地は py gas.py combo addon が combo_window.json に書く（人ごとに違う）。
async function comboWindowBase() {
  try {
    const res = await fetch(chrome.runtime.getURL("combo_window.json"), { cache: "no-store" });
    if (!res.ok) return "";
    const j = await res.json();
    return String((j && j.base) || "");
  } catch (_e) {
    return "";
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  const m = String((tab && tab.url) || "").match(/docs\.google\.com\/spreadsheets\/d\/([\w-]+)/);
  const base = await comboWindowBase();
  if (!base) {
    chrome.tabs.create({ url: "data:text/plain;charset=utf-8," + encodeURIComponent("GASコンボの操作窓の番地がまだありません。py gas.py combo addon を撃ってから、chrome://extensions でこの拡張を「再読み込み」してください。") });
    return;
  }
  const url = base + (base.indexOf("?") >= 0 ? "&" : "?") + (m ? "id=" + encodeURIComponent(m[1]) : "");
  chrome.windows.create({ url, type: "popup", width: 560, height: 820 });
});
