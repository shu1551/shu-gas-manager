// GASコンボ ブラウザ連動 - Background Service Worker
// Content Script から受け取った選択セル・シート・ファイル情報をローカルの GASコンボ (127.0.0.1:18765) へ送信する

const SYNC_URL = "http://127.0.0.1:18765/sync";

// 拡張のファイル（フォルダの今の中身）の指紋。道具が拡張を直したら、サイドパネルを開いたときに自分で入れ直すのに使う
const STAMP_FILES = ["manifest.json", "background.js", "content.js", "sidepanel.js", "sidepanel.html"];
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

// ---------------------------------------------------------------- サイドパネルで GASコンボを開く
// 拡張のアイコン（または Alt+G）で、ブラウザの右のサイドパネルを開く。中身は sidepanel.html（今のタブのシートを相手にする）
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
