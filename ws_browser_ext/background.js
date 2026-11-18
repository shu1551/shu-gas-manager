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
