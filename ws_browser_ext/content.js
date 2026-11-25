// GASコンボ ブラウザ連動 - Content Script
// 開いている Google スプレッドシート／ドキュメントのファイルID・タイトル・シート名・選択セル範囲を検知して GASコンボ へ送る

(() => {
  const DIRECT_SYNC_URL = "http://127.0.0.1:18765/sync";
  const VALID_SELECTION_RE = /^(?:[A-Z]{1,3}[0-9]{1,7}(?::[A-Z]{1,3}[0-9]{1,7})?|[A-Z]{1,3}:[A-Z]{1,3}|[0-9]{1,7}:[0-9]{1,7})$/i;

  let lastSig = "";
  let lastSentAt = 0;
  let debounceTimer = null;

  function parseDocMeta() {
    const url = location.href;
    const m = url.match(/\/(spreadsheets|document)\/d\/([a-zA-Z0-9_-]+)/);
    if (!m) return null;
    const kind = m[1] === "spreadsheets" ? "sheet" : "doc";
    const id = m[2];
    const mg = url.match(/[#?&]gid=([0-9]+)/);
    const gid = mg ? mg[1] : "";
    return { id, kind, url, gid };
  }

  function getDocTitle() {
    // 左上のタイトル入力ボックスがあれば最優先で取得する
    const titleInput = document.querySelector("input.docs-title-input");
    if (titleInput && titleInput.value && titleInput.value.trim()) {
      return titleInput.value.trim();
    }
    return (document.title || "")
      .replace(/\s*-\s*Google\s*(スプレッドシート|ドキュメント|Sheets|Docs)\s*$/i, "")
      .trim();
  }

  function getActiveSheetName() {
    const selectors = [
      ".docs-sheet-active-tab .docs-sheet-tab-name",
      ".docs-sheet-tab[aria-selected='true'] .docs-sheet-tab-name",
      ".docs-sheet-active-tab",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent) {
        const txt = el.textContent.trim();
        if (txt) return txt;
      }
    }
    return "";
  }

  function getSelectedRange() {
    const selectors = [
      "#t-name-box",
      "input.waffle-name-box",
      "#t-name-box-input",
      "input[aria-label*='名前ボックス']",
      "input[aria-label*='Name box']",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && typeof el.value === "string") {
        // ユーザーが名前ボックスに直接手入力している最中は確定前のためスキップ
        if (document.activeElement === el) return "";
        const raw = el.value.trim();
        if (!raw) return "";
        // シート名付きの 'Sheet1'!A1:B2 などの場合はセル範囲部分を取り出す
        const bangIdx = raw.lastIndexOf("!");
        const part = bangIdx >= 0 ? raw.slice(bangIdx + 1).trim() : raw;
        if (VALID_SELECTION_RE.test(part)) {
          return part.toUpperCase();
        }
      }
    }
    return "";
  }

  function getActiveDocHeading() {
    // Google ドキュメントの左アウトラインで現在位置としてハイライトされている見出しを取得する
    const selectors = [
      ".navigation-item.location-indicator-highlight .navigation-item-content",
      ".outline-refresh .location-indicator-highlight .navigation-item-content",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent) {
        const txt = el.textContent.trim();
        if (txt) return txt;
      }
    }
    return "";
  }

  // 名前ボックスに番地を入れて Enter（シートの名前つきなら、そのシートへ移って選ぶ）
  function gotoRange(range) {
    const box = document.querySelector("#t-name-box") || document.querySelector("input.waffle-name-box");
    if (!box) return;
    box.focus();
    box.value = range;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    for (const type of ["keydown", "keypress", "keyup"]) {
      box.dispatchEvent(new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
    }
  }

  function collectState() {
    const meta = parseDocMeta();
    if (!meta) return null;
    const name = getDocTitle();
    let sheet = "";
    let selection = "";
    let heading = "";
    if (meta.kind === "sheet") {
      sheet = getActiveSheetName();
      selection = getSelectedRange();
    } else {
      heading = getActiveDocHeading();
    }
    return {
      id: meta.id,
      kind: meta.kind,
      url: meta.url,
      gid: meta.gid,
      name,
      sheet,
      selection,
      heading,
      ts: Date.now() / 1000,
    };
  }

  function sendPayload(payload) {
    // Python 操作窓 (18765) が未起動のときにページコンソールへ赤い ERR_CONNECTION_REFUSED を
    // 連発しないよう、Service Worker 経由のみで静かに送信する
    try {
      chrome.runtime.sendMessage({ type: "GAS_COMBO_SYNC", payload }, () => {
        void chrome.runtime.lastError;
      });
    } catch (_e) {
      // ignore
    }
  }

  function checkAndSync(force = false) {
    if (document.visibilityState === "hidden" && !force) return;
    const st = collectState();
    if (!st || !st.id) return;
    // シート読み込み直後で名前ボックスがまだ空のときは、少し待ってから再取得する
    const sig = [st.id, st.kind, st.name, st.sheet, st.selection, st.heading].join("|");
    const now = Date.now();
    if (!force && sig === lastSig && now - lastSentAt < 4000) {
      return;
    }
    lastSig = sig;
    lastSentAt = now;
    sendPayload(st);
  }

  function scheduleSync(delayMs = 60, force = false) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => checkAndSync(force), delayMs);
  }

  // マウス選択・キー移動・フォーカス復帰・URLハッシュ変化を即時検知する
  document.addEventListener("mouseup", () => scheduleSync(50), true);
  document.addEventListener("keyup", () => scheduleSync(50), true);
  window.addEventListener("focus", () => scheduleSync(40, true));
  window.addEventListener("hashchange", () => scheduleSync(80, true));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") scheduleSync(40, true);
  });

  // バックグラウンドからのタブ切替PINGに応答する
  try {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg && msg.type === "GAS_COMBO_PING") {
        scheduleSync(10, true);
      }
      if (msg && msg.type === "GAS_COMBO_GOTO" && msg.range) {
        gotoRange(String(msg.range));
      }
    });
  } catch (_e) {
    // ignore
  }

  // 初回同期＋定期軽量チェック（350ms間隔）
  scheduleSync(150, true);
  setInterval(() => checkAndSync(false), 350);
})();
