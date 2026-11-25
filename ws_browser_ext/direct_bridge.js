// GASコンボ ブラウザ連動 - トップレベル直結ブリッジ
// 操作窓 (script.google.com/macros/s/*) やシート内サイドバー (docs.google.com/*) の iframe からの
// postMessage をトップフレームで受け、Service Worker 経由で 127.0.0.1:18766/resolve へ中継する。
(() => {
  if (window.top !== window) return;

  const GOOGLE_SANDBOX_RE = /^https:\/\/[a-z0-9-]+\.googleusercontent\.com$/i;
  function isAllowedMessageOrigin(origin) {
    const o = String(origin || "");
    return (
      o === "https://docs.google.com" ||
      o === "https://script.google.com" ||
      GOOGLE_SANDBOX_RE.test(o)
    );
  }

  // script.google.com/macros/s/* 上では、自分の combo_window.json に登録された操作窓 URL のみ許可する（第三者の GAS Web アプリを遮断）
  let _trustedWindowPromise = null;
  function isTrustedHostPage() {
    if (location.hostname === "docs.google.com") return Promise.resolve(true);
    if (location.hostname !== "script.google.com") return Promise.resolve(false);
    if (!_trustedWindowPromise) {
      _trustedWindowPromise = fetch(chrome.runtime.getURL("combo_window.json"), { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          const base = String((j && j.base) || "").trim();
          if (!base) return false;
          const u = new URL(base);
          return u.origin === location.origin && location.pathname.startsWith(u.pathname.replace(/\/(exec|dev)$/, "/"));
        })
        .catch(() => false);
    }
    return _trustedWindowPromise;
  }

  // 直結の合い言葉（py gas.py combo addon / combo push が combo_window.json に書く）。
  // 本人の操作窓だけが同じ合い言葉を持つ＝ほかの人のアドオンの窓からは PC の AI・記録取込を呼べない
  let _tokenPromise = null;
  function bridgeToken() {
    if (!_tokenPromise) {
      // 拡張のファイルはバックグラウンドに読んでもらう（ページの側からは読めないことがある）
      _tokenPromise = new Promise((resolve) => {
        try {
          chrome.runtime.sendMessage({ type: "GAS_COMBO_GET_TOKEN_BG" }, (res) => {
            void chrome.runtime.lastError;
            resolve(String((res && res.token) || ""));
          });
        } catch (_e) {
          resolve("");
        }
      }).then((t) => {
        if (!t) _tokenPromise = null;   // まだ無ければ次の頼みで読み直す
        return t;
      });
    }
    return _tokenPromise;
  }
  async function tokenOk(d) {
    const t = await bridgeToken();
    return !!t && typeof d.token === "string" && d.token === t;
  }
  const NEEDS_TOKEN = { GAS_COMBO_PING_LOCAL: 1, GAS_COMBO_DIRECT_AI: 1, GAS_COMBO_FETCH_RECORDED_MACROS: 1 };

  window.addEventListener("message", async (ev) => {
    const d = ev && ev.data;
    if (!d || !isAllowedMessageOrigin(ev.origin)) return;
    if (NEEDS_TOKEN[d.type] && !(await tokenOk(d))) return;
    const targetOrigin = ev.origin && ev.origin !== "null" ? ev.origin : "*";

    if (d.type === "GAS_COMBO_PING_LOCAL") {
      if (!(await isTrustedHostPage())) return;
      const reqId = String(d.reqId || "");
      const replyDone = (obj) => {
        try {
          ev.source.postMessage(
            Object.assign({ type: "GAS_COMBO_PING_LOCAL_DONE", reqId, inExtension: true }, obj),
            targetOrigin
          );
        } catch (_e) {}
      };
      try {
        ev.source.postMessage({ type: "GAS_COMBO_PING_LOCAL_ACK", reqId }, targetOrigin);
      } catch (_e) {}
      try {
        chrome.runtime.sendMessage({ type: "GAS_COMBO_PING_LOCAL_BG" }, (res) => {
          if (chrome.runtime.lastError || !res) {
            replyDone({
              reachable: false,
              error: String(
                (chrome.runtime.lastError && chrome.runtime.lastError.message) ||
                  "拡張バックグラウンド応答なし"
              ),
            });
            return;
          }
          replyDone(res);
        });
      } catch (e) {
        replyDone({ reachable: false, error: String((e && e.message) || e) });
      }
      return;
    }

    if (d.type === "GAS_COMBO_DIRECT_AI") {
      if (!(await isTrustedHostPage())) return;
      const reqId = String(d.reqId || "");
      const replyDone = (obj) => {
        try {
          ev.source.postMessage(
            Object.assign({ type: "GAS_COMBO_DIRECT_AI_DONE", reqId, inExtension: true }, obj),
            targetOrigin
          );
        } catch (_e) {}
      };
      try {
        ev.source.postMessage({ type: "GAS_COMBO_DIRECT_AI_ACK", reqId }, targetOrigin);
      } catch (_e) {}
      try {
        chrome.runtime.sendMessage(
          { type: "GAS_COMBO_DIRECT_AI_BG", payload: d.payload || {} },
          (res) => {
            if (chrome.runtime.lastError || !res) {
              replyDone({
                reachable: false,
                error: String(
                  (chrome.runtime.lastError && chrome.runtime.lastError.message) ||
                    "拡張バックグラウンド応答なし"
                ),
              });
              return;
            }
            replyDone(res);
          }
        );
      } catch (e) {
        replyDone({ reachable: false, error: String((e && e.message) || e) });
      }
      return;
    }

    if (d.type === "GAS_COMBO_FETCH_RECORDED_MACROS") {
      if (!(await isTrustedHostPage())) return;
      const reqId = String(d.reqId || "");
      const replyDone = (obj) => {
        try {
          ev.source.postMessage(
            Object.assign({ type: "GAS_COMBO_FETCH_RECORDED_DONE", reqId, inExtension: true }, obj),
            targetOrigin
          );
        } catch (_e) {}
      };
      try {
        ev.source.postMessage({ type: "GAS_COMBO_FETCH_RECORDED_ACK", reqId }, targetOrigin);
      } catch (_e) {}
      try {
        chrome.runtime.sendMessage(
          { type: "GAS_COMBO_FETCH_RECORDED_BG", payload: d.payload || {} },
          (res) => {
            if (chrome.runtime.lastError || !res) {
              replyDone({
                reachable: false,
                error: String(
                  (chrome.runtime.lastError && chrome.runtime.lastError.message) ||
                    "拡張バックグラウンド応答なし"
                ),
              });
              return;
            }
            replyDone(res);
          }
        );
      } catch (e) {
        replyDone({ reachable: false, error: String((e && e.message) || e) });
      }
      return;
    }

    if (location.hostname === "docs.google.com") {
      if (d.type === "GAS_COMBO_GET_SEL") {
        const box = document.querySelector("#t-name-box") || document.querySelector("input.waffle-name-box");
        const range = box ? String(box.value || "").trim() : "";
        const tabEl = document.querySelector(".docs-sheet-active-tab .docs-sheet-tab-name");
        const sheet = tabEl ? String(tabEl.textContent || "").trim() : "";
        try {
          ev.source.postMessage({ type: "GAS_COMBO_GET_SEL_DONE", ok: !!range, range, sheet }, targetOrigin);
        } catch (_e) {}
        return;
      }
      if (d.type === "GAS_COMBO_GOTO" && d.range) {
        const reply = (ok, why) => {
          try {
            ev.source.postMessage({ type: "GAS_COMBO_GOTO_DONE", ok, why: why || "" }, targetOrigin);
          } catch (_e) {}
        };
        const box = document.querySelector("#t-name-box") || document.querySelector("input.waffle-name-box");
        if (!box) {
          reply(false, "シートの名前ボックスが見つかりません");
          return;
        }
        box.focus();
        box.value = String(d.range);
        box.dispatchEvent(new Event("input", { bubbles: true }));
        for (const type of ["keydown", "keypress", "keyup"]) {
          box.dispatchEvent(
            new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true })
          );
        }
        reply(true, "");
      }
    }
  });
})();
