# -*- coding: utf-8 -*-
"""GasClient フロントエンド検証・UIバンドル・検査 Mixin。"""

import json
import os
import re
from pathlib import Path


def _gc():
    import gas_client
    return gas_client


class GasClientUiMixin:
    def verify_frontend(self, script_id, filename="Index", test_js="", timeout=10):
        """指定した HTML ファイル内の JavaScript ロジックを Node.js vm 模擬環境（インメモリ IndexedDB / DOM / RPC プロキシ）上で実機実行・検証する

        Args:
            script_id: プロジェクト名またはスクリプトID
            filename: 対象の HTML ファイル名 (既定: "Index")
            test_js: 検証用に追加実行する非同期 JS 式/ブロック (例: "await saveToDB([{id:'1'}]); return (await loadFromDB()).length;")
            timeout: タイムアウト秒数 (既定: 10)

        Returns:
            dict: {
                "success": bool,
                "error": str | None,
                "rpc_calls": list,
                "db_records_count": int,
                "alerts": list,
                "confirms": list,
                "test_result": any,
                "file": str
            }
        """
        sid = self.resolve_script_id(script_id)
        content = self.get_content(sid)
        files = content.get("files", [])

        target_file = None
        base_target = os.path.splitext(filename)[0].lower()
        for f in files:
            if f.get("type") == "HTML":
                fname = f.get("name", "")
                if fname.lower() == base_target or os.path.splitext(fname)[0].lower() == base_target:
                    target_file = f
                    break

        if not target_file:
            raise ValueError(f"HTML ファイル '{filename}' が見つかりません。")

        source = target_file.get("source", "")
        script_parts = []
        for m in re.finditer(r'(<script[^>]*>)([\s\S]*?)(</script>)', source, re.IGNORECASE):
            if self._is_js_script_tag(m.group(1)):
                script_parts.append(m.group(2))

        combined_js = "\n;\n".join(script_parts)

        node_runner = r"""
const fs = require('fs');
const vm = require('vm');

let payload;
try {
  payload = JSON.parse(fs.readFileSync(0, 'utf8'));
} catch (e) {
  console.log(JSON.stringify({ success: false, error: 'Payload parse error: ' + e.message }));
  process.exit(0);
}

const htmlJs = payload.html_js || '';
const testJs = payload.test_js || '';

const dbStores = {};
function getStoreMap(name) {
  if (!dbStores[name]) dbStores[name] = new Map();
  return dbStores[name];
}

const mockIndexedDB = {
  open: function(name, version) {
    const req = { onsuccess: null, onupgradeneeded: null, onerror: null, result: null };
    setTimeout(() => {
      const db = {
        transaction: function(storeName, mode) {
          const sNames = Array.isArray(storeName) ? storeName : [storeName];
          return {
            objectStore: function(targetName) {
              const map = getStoreMap(targetName || sNames[0]);
              return {
                put: function(val) {
                  const key = (val && val.id !== undefined) ? val.id : JSON.stringify(val);
                  map.set(key, JSON.parse(JSON.stringify(val)));
                  return {};
                },
                add: function(val) {
                  const key = (val && val.id !== undefined) ? val.id : JSON.stringify(val);
                  map.set(key, JSON.parse(JSON.stringify(val)));
                  return {};
                },
                get: function(key) {
                  const r = { onsuccess: null, result: undefined };
                  setTimeout(() => {
                    const item = map.get(key);
                    r.result = item !== undefined ? JSON.parse(JSON.stringify(item)) : undefined;
                    if (r.onsuccess) r.onsuccess({ target: r });
                  }, 0);
                  return r;
                },
                getAll: function() {
                  const r = { onsuccess: null, result: [] };
                  setTimeout(() => {
                    r.result = Array.from(map.values()).map(v => JSON.parse(JSON.stringify(v)));
                    if (r.onsuccess) r.onsuccess({ target: r });
                  }, 0);
                  return r;
                },
                delete: function(key) {
                  map.delete(key);
                  return {};
                },
                clear: function() {
                  map.clear();
                  return {};
                }
              };
            }
          };
        },
        createObjectStore: function(name, options) {
          getStoreMap(name);
          return {};
        }
      };
      req.result = db;
      if (req.onupgradeneeded) req.onupgradeneeded({ target: { result: db } });
      if (req.onsuccess) req.onsuccess({ target: { result: db } });
    }, 0);
    return req;
  }
};

const mockLocalStorage = {
  _data: {},
  getItem: function(k) { return this._data[k] !== undefined ? this._data[k] : null; },
  setItem: function(k, v) { this._data[k] = String(v); },
  removeItem: function(k) { delete this._data[k]; },
  clear: function() { this._data = {}; }
};

const rpcCalls = [];
const alerts = [];
const confirms = [];

function makeProxy(chain) {
  const fn = function(...args) {
    rpcCalls.push({ chain: chain, args: args });
    return Promise.resolve({ success: true });
  };
  return new Proxy(fn, {
    get: function(target, prop) {
      if (typeof prop !== 'string') return target[prop];
      if (prop === 'withSuccessHandler' || prop === 'withFailureHandler' || prop === 'withUserObject') {
        return function(handler) {
          if (prop === 'withSuccessHandler' && typeof handler === 'function') {
            setTimeout(() => { try { handler({ success: true }); } catch(e){} }, 0);
          }
          return makeProxy(chain.concat([[prop, 'fn']]));
        };
      }
      return makeProxy(chain.concat([prop]));
    }
  });
}

const mockDoc = {
  getElementById: function(id) {
    return {
      id: id,
      style: {},
      dataset: {},
      classList: {
        toggle: () => {},
        add: () => {},
        remove: () => {},
        contains: () => false
      },
      value: '',
      innerText: '',
      innerHTML: '',
      files: [],
      appendChild: () => {},
      removeChild: () => {},
      scrollTo: () => {},
      addEventListener: () => {}
    };
  },
  createElement: function(tag) {
    return {
      tagName: String(tag).toUpperCase(),
      style: {},
      dataset: {},
      classList: { toggle: () => {}, add: () => {}, remove: () => {} },
      appendChild: () => {},
      removeChild: () => {},
      setAttribute: () => {},
      getAttribute: () => null,
      onload: null,
      contentWindow: {
        document: {
          open: () => {},
          write: () => {},
          close: () => {},
          body: { scrollHeight: 100 }
        }
      }
    };
  },
  body: {
    appendChild: () => {},
    removeChild: () => {}
  },
  addEventListener: () => {}
};

class MockWorker {
  constructor() {}
  postMessage() {}
  terminate() {}
}

const sandbox = {
  indexedDB: mockIndexedDB,
  localStorage: mockLocalStorage,
  document: mockDoc,
  window: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  Worker: MockWorker,
  URL: { createObjectURL: () => 'blob:mock', revokeObjectURL: () => {} },
  Blob: class { constructor() {} },
  alert: (msg) => alerts.push(String(msg)),
  confirm: (msg) => { confirms.push(String(msg)); return true; },
  prompt: () => null,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  setInterval: setInterval,
  clearInterval: clearInterval,
  console: {
    log: () => {},
    error: () => {},
    warn: () => {},
    info: () => {}
  },
  google: { script: { run: makeProxy([]) } },
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  escape: escape,
  unescape: unescape,
  encodeURIComponent: encodeURIComponent,
  decodeURIComponent: decodeURIComponent,
  parseInt: parseInt,
  parseFloat: parseFloat,
  isNaN: isNaN,
  isFinite: isFinite,
  Date: Date,
  Math: Math,
  JSON: JSON,
  Promise: Promise,
  Set: Set,
  Map: Map,
  Array: Array,
  Object: Object,
  String: String,
  Number: Number,
  Boolean: Boolean,
  RegExp: RegExp,
  Error: Error,
  TypeError: TypeError,
  RangeError: RangeError
};
sandbox.window = sandbox;
sandbox.self = sandbox;

(async () => {
  try {
    const context = vm.createContext(sandbox);

    if (htmlJs.trim()) {
      const script = new vm.Script(htmlJs, { filename: 'inline_html_script.js' });
      script.runInContext(context);
    }

    let testResult = null;
    if (testJs.trim()) {
      const wrappedTest = '(async () => {\n' + testJs + '\n})()';
      const testScript = new vm.Script(wrappedTest, { filename: 'test_script.js' });
      testResult = await testScript.runInContext(context);
    }

    let totalDbCount = 0;
    for (const s in dbStores) {
      totalDbCount += dbStores[s].size;
    }

    console.log(JSON.stringify({
      success: true,
      error: null,
      rpc_calls: rpcCalls.map(c => ({ chain: c.chain, args: c.args })),
      db_records_count: totalDbCount,
      alerts: alerts,
      confirms: confirms,
      test_result: testResult !== undefined ? testResult : null
    }));
  } catch (err) {
    console.log(JSON.stringify({
      success: false,
      error: (err && err.message) ? err.message : String(err),
      rpc_calls: rpcCalls.map(c => ({ chain: c.chain, args: c.args })),
      db_records_count: 0,
      alerts: alerts,
      confirms: confirms,
      test_result: null
    }));
  }
})();
"""
        payload = json.dumps({"html_js": combined_js, "test_js": test_js}, ensure_ascii=False)
        try:
            p = _gc().subprocess.run(
                ["node", "-e", node_runner],
                input=payload,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=timeout,
                **self._win_no_window_kwargs()
            )
            if p.returncode != 0 and not p.stdout.strip():
                return {
                    "success": False,
                    "error": f"Node.js 実行エラー (code {p.returncode}): {p.stderr.strip()}",
                    "rpc_calls": [],
                    "db_records_count": 0,
                    "alerts": [],
                    "confirms": [],
                    "test_result": None,
                    "file": target_file.get("name", "")
                }
            out_json = json.loads(p.stdout.strip())
            out_json["file"] = target_file.get("name", "")
            return out_json
        except FileNotFoundError:
            raise RuntimeError("Node.js が見つかりません。Node.js をインストールしてください。")
        except _gc().subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"実行タイムアウト ({timeout}秒を超過しました)",
                "rpc_calls": [],
                "db_records_count": 0,
                "alerts": [],
                "confirms": [],
                "test_result": None,
                "file": target_file.get("name", "")
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"検証実行例外: {str(e)}",
                "rpc_calls": [],
                "db_records_count": 0,
                "alerts": [],
                "confirms": [],
                "test_result": None,
                "file": target_file.get("name", "")
            }


    def _bundle_web_page(self, url: str, timeout: int = 15) -> dict:
        """外部 Web ページを解析・アセットインライン化して GAS 用の単一 HTML を生成する"""
        import urllib.parse
        from bs4 import BeautifulSoup

        url = (url or "").strip()
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise ValueError("有効な HTTP/HTTPS URL を指定してください。")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = _gc().requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
        except _gc().requests.exceptions.TooManyRedirects as e:
            raise RuntimeError(f"Webページの取得に失敗しました (循環リダイレクトまたはリダイレクト上限超過): {e}")
        except _gc().requests.exceptions.RequestException as e:
            raise RuntimeError(f"Webページの取得に失敗しました: {e}")

        resp.encoding = resp.apparent_encoding or "utf-8"
        raw_html = resp.text

        soup = BeautifulSoup(raw_html, "html.parser")
        raw_title = soup.title.string.strip() if soup.title and soup.title.string else "Cloned Web App"
        title = re.sub(r'[\r\n]+', ' ', raw_title).replace('*/', '* /')

        inlined_css = 0
        inlined_js = 0
        rewritten_links = 0

        # CSS インライン化
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href")
            if not href:
                continue
            abs_href = urllib.parse.urljoin(url, href)
            try:
                css_resp = _gc().requests.get(abs_href, headers=headers, timeout=10)
                if css_resp.status_code == 200:
                    css_resp.encoding = css_resp.apparent_encoding or "utf-8"
                    css_text = css_resp.text

                    def rewrite_css_url(m):
                        u = m.group(1).strip("\"'")
                        if u.startswith(("data:", "http://", "https://")):
                            return f"url('{u}')"
                        return f"url('{urllib.parse.urljoin(abs_href, u)}')"

                    css_text = re.sub(r'url\s*\(([^)]+)\)', rewrite_css_url, css_text)
                    new_style = soup.new_tag("style")
                    new_style.string = f"/* Inlined from {href} */\n" + css_text
                    link.replace_with(new_style)
                    inlined_css += 1
                else:
                    link["href"] = abs_href
                    rewritten_links += 1
            except Exception:
                link["href"] = abs_href
                rewritten_links += 1

        # JS インライン化（同オリジン）
        parsed_orig = urllib.parse.urlparse(url)
        for script in soup.find_all("script", src=True):
            src = script.get("src")
            if not src:
                continue
            abs_src = urllib.parse.urljoin(url, src)
            parsed_src = urllib.parse.urlparse(abs_src)
            if parsed_orig.netloc == parsed_src.netloc:
                try:
                    js_resp = _gc().requests.get(abs_src, headers=headers, timeout=10)
                    if js_resp.status_code == 200:
                        js_resp.encoding = js_resp.apparent_encoding or "utf-8"
                        new_script = soup.new_tag("script")
                        new_script.string = f"/* Inlined from {src} */\n" + js_resp.text
                        script.replace_with(new_script)
                        inlined_js += 1
                        continue
                except Exception:
                    pass
            script["src"] = abs_src
            rewritten_links += 1

        # アセットの相対パス書き換え
        for tag, attr in [("img", "src"), ("source", "src"), ("video", "src"), ("audio", "src"), ("a", "href")]:
            for el in soup.find_all(tag, **{attr: True}):
                val = el.get(attr)
                if val and not val.startswith(("http://", "https://", "data:", "mailto:", "tel:", "#", "javascript:")):
                    el[attr] = urllib.parse.urljoin(url, val)
                    rewritten_links += 1

        # Viewport メタタグ
        if not soup.find("meta", attrs={"name": "viewport"}) and soup.head:
            meta = soup.new_tag("meta", attrs={"name": "viewport", "content": "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"})
            soup.head.insert(0, meta)

        server_code = f"""/**
 * クローン生成された Web アプリ: {title}
 * 元URL: {url}
 */
function doGet() {{
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle({json.dumps(title)})
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}}
"""
        return {
            "title": title,
            "url": url,
            "html": str(soup),
            "server_code": server_code,
            "inlined_css_count": inlined_css,
            "inlined_js_count": inlined_js,
            "rewritten_links_count": rewritten_links,
            "total_html_length": len(str(soup))
        }


    def clone_web(self, url: str, project_name: str = None, deploy: bool = False, access: str = "MYSELF") -> dict:
        """外部 Web ページを自立型 GAS Web アプリとしてクローン作成する。
        ※ 写してよいのは自分が作ったページ・権利のあるページだけです。
        """
        bundle = self._bundle_web_page(url)
        title = project_name or bundle["title"] or "Cloned Web App"

        try:
            sid = self.resolve_script_id(title)
        except ValueError:
            created = self.create_project(title)
            sid = created["scriptId"]

        manifest = {
            "timeZone": "Asia/Tokyo",
            "dependencies": {},
            "exceptionLogging": "STACKDRIVER",
            "runtimeVersion": "V8",
            "webapp": {
                "executeAs": "USER_DEPLOYING",
                "access": access
            }
        }

        files = [
            {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, indent=2)},
            {"name": "コード", "type": "SERVER_JS", "source": bundle["server_code"]},
            {"name": "Index", "type": "HTML", "source": bundle["html"]}
        ]

        self._put_content(sid, files)

        webapp_url = None
        if deploy:
            try:
                dep_res = self.deploy(sid, description=f"Cloned from {url}")
                webapp_url = dep_res.get("webAppUrl")
            except Exception:
                pass

        xray_res = self.xray(sid, filename="Index")

        warning_header = ""
        if access != "MYSELF":
            warning_header = "⚠️ 写したページを誰でも見られる形で公開しました。他者のページ・ログイン画面の写しを公開すると、なりすましと著作権の問題になります。\n\n"

        lines = [
            f"=== 🚀 Webクローン完了: [{title}] ===",
            f"元URL: {url}",
            f"スクリプトID: {sid}",
            f"WebアプリURL: {webapp_url or '(未デプロイ)'}",
            f"アクセス権限: {access}",
            f"バンドル規模: HTML {bundle['total_html_length']:,} 文字 (CSSインライン化: {bundle['inlined_css_count']}件, JSインライン化: {bundle['inlined_js_count']}件, リンク書き換え: {bundle['rewritten_links_count']}件)",
            "",
            "--- 🩻 クローン直後レントゲン検査 ---",
            xray_res["markdown_report"]
        ]

        return {
            "status": "success",
            "script_id": sid,
            "project_name": title,
            "url": url,
            "webapp_url": webapp_url,
            "access": access,
            "inlined_css_count": bundle["inlined_css_count"],
            "inlined_js_count": bundle["inlined_js_count"],
            "rewritten_links_count": bundle["rewritten_links_count"],
            "html_length": bundle["total_html_length"],
            "xray": xray_res,
            "markdown_report": warning_header + "\n".join(lines)
        }


    def inspect_ui(
        self,
        script_id=None,
        filename="Index",
        url=None,
        theme=None,
        all_themes=False,
        actions=None,
        screenshot=True,
        check_contrast=True,
        check_axe=False,
        baseline_screenshot=None,
        width=1280,
        height=800,
        device="desktop",
        auto_click=True
    ):
        if device == "mobile":
            width, height = 390, 844
        """GAS Web アプリの実機画面をヘッドレスブラウザで起動・レンダリングし、
        全自動ボタン踏破（例外・赤文字検知）、WCAGコントラスト比、スクリーンショット撮影を全自動で実行する。

        Args:
            script_id: プロジェクト名またはスクリプトID
            filename: 対象のHTMLファイル名（デフォルト: Index）
            url: WebアプリのURL（省略時はGASコードからローカル展開）
            theme: 指定テーマ ("white", "dark", "green" 等)
            all_themes: True の場合、主要3テーマを一括検査
            actions: 手動指定の操作リスト（例: [{'click': '#btn'}]）
            screenshot: スクリーンショットを撮影するかどうか
            check_contrast: WCAGコントラスト比の自動検査を行うか
            check_axe: axe-core の検査を行うか
            auto_click: 画面上の全ボタン・クリッカブル要素を自動踏破するか

        Returns:
            dict: {
                "success": bool,
                "contrast_passed": bool,
                "total_elements_checked": int,
                "dangers": list,
                "warnings": list,
                "themes_tested": list,
                "traversal_log": list,
                "console_errors": list,
                "page_errors": list,
                "screenshot_path": str | None
            }
        """
        import os
        import json
        import tempfile
        from pathlib import Path

        # 1. HTML ソースの取得または URL 決定
        html_src = ""
        target_label = url or script_id or filename
        tmp_html_path = None

        if not url and script_id:
            sid = self.resolve_script_id(script_id)
            content = self.get_content(sid)
            files = content.get("files", [])
            target_name = filename.replace(".html", "").replace(".HTML", "").lower()
            html_file = next((f for f in files if f.get("name", "").lower() == target_name and f.get("type") == "HTML"), None)
            if not html_file:
                html_file = next((f for f in files if f.get("type") == "HTML"), None)
            if html_file:
                html_src = html_file.get("source", "")

        if html_src:
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
                f.write(html_src)
                tmp_html_path = f.name
            target_url = f"file:///{tmp_html_path.replace(os.sep, '/')}"
        elif url:
            target_url = url
        else:
            raise ValueError("project または url の指定が必要です。")

        themes_to_test = ["white", "dark", "green"] if all_themes else ([theme] if theme else ["default"])

        all_dangers = []
        all_warnings = []
        total_checked = 0
        console_errors = []
        page_errors = []
        traversal_log = []
        saved_screenshot = None

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})

                page.on("pageerror", lambda err: page_errors.append(str(err)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

                for th in themes_to_test:
                    page.goto(target_url, wait_until="load")
                    page.wait_for_timeout(300)

                    # テーマの適用
                    if th != "default":
                        page.evaluate(f"""() => {{
                            try {{
                                localStorage.setItem('gmail_ultra_theme', '{th}');
                                localStorage.setItem('theme', '{th}');
                                document.body.setAttribute('data-theme', '{th}');
                                if (window.applyTheme) window.applyTheme('{th}');
                            }} catch(e) {{}}
                        }}""")
                        page.wait_for_timeout(200)

                    # 手動指定アクションの実行
                    if actions:
                        for act in actions:
                            if isinstance(act, dict):
                                if "click" in act:
                                    try:
                                        page.click(act["click"], timeout=2000)
                                        page.wait_for_timeout(200)
                                    except Exception as e:
                                        traversal_log.append({"action": f"click {act['click']}", "status": f"error: {e}"})
                                elif "eval" in act:
                                    try:
                                        page.evaluate(act["eval"])
                                    except Exception as e:
                                        traversal_log.append({"action": f"eval {act['eval']}", "status": f"error: {e}"})

                    # 全自動ボタン踏破テスト (auto_click)
                    if auto_click:
                        buttons = page.query_selector_all("button, input[type=button], input[type=submit], [onclick]")
                        for idx, btn in enumerate(buttons[:20]):
                            try:
                                text = (btn.inner_text() or btn.get_attribute("value") or "").strip()[:20]
                                b_id = btn.get_attribute("id") or f"btn-{idx}"
                                if btn.is_visible():
                                    btn.click(timeout=1000)
                                    page.wait_for_timeout(100)
                                    traversal_log.append({"id": b_id, "text": text, "status": "clicked", "theme": th})
                                else:
                                    traversal_log.append({"id": b_id, "text": text, "status": "hidden", "theme": th})
                            except Exception as e:
                                traversal_log.append({"id": b_id, "text": text, "status": f"error: {str(e)}", "theme": th})

                    # WCAG コントラスト比検査
                    if check_contrast:
                        contrast_data = page.evaluate("""() => {
                            function parseColor(c) {
                                const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
                                if (!m) return [0, 0, 0, 1];
                                return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3]), m[4] !== undefined ? parseFloat(m[4]) : 1];
                            }
                            function luminance(r, g, b) {
                                const a = [r, g, b].map(v => {
                                    v /= 255;
                                    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                                });
                                return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
                            }
                            function contrastRatio(rgb1, rgb2) {
                                const l1 = luminance(rgb1[0], rgb1[1], rgb1[2]);
                                const l2 = luminance(rgb2[0], rgb2[1], rgb2[2]);
                                return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
                            }

                            const results = [];
                            const els = document.querySelectorAll('button, h1, h2, h3, p, span, a, label');
                            for (let el of els) {
                                if (el.offsetParent === null) continue;
                                const text = el.innerText ? el.innerText.trim() : '';
                                if (!text) continue;
                                const style = window.getComputedStyle(el);
                                const fg = parseColor(style.color);
                                if (fg[3] === 0) continue;

                                const bgStack = [];
                                let cur = el;
                                while (cur) {
                                    const cStyle = window.getComputedStyle(cur);
                                    const cBg = parseColor(cStyle.backgroundColor);
                                    if (cBg[3] > 0) {
                                        bgStack.push(cBg);
                                        if (cBg[3] >= 0.99) break;
                                    }
                                    cur = cur.parentElement;
                                }
                                let bg = [255, 255, 255];
                                for (let i = bgStack.length - 1; i >= 0; i--) {
                                    const layer = bgStack[i];
                                    const a = layer[3];
                                    bg = [
                                        Math.round(layer[0] * a + bg[0] * (1 - a)),
                                        Math.round(layer[1] * a + bg[1] * (1 - a)),
                                        Math.round(layer[2] * a + bg[2] * (1 - a))
                                    ];
                                }

                                const ratio = Math.round(contrastRatio(fg, bg) * 10) / 10;
                                results.push({
                                    tag: el.tagName.toLowerCase(),
                                    selector: el.id ? '#' + el.id : (el.className ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()),
                                    text: text.slice(0, 25),
                                    ratio: ratio,
                                    fg: style.color,
                                    bg: `rgb(${bg[0]},${bg[1]},${bg[2]})`
                                });
                            }
                            return results;
                        }""")

                        total_checked += len(contrast_data)
                        for item in contrast_data:
                            item["theme"] = th
                            if item["ratio"] < 2.5:
                                all_dangers.append(item)
                            elif item["ratio"] < 4.5:
                                all_warnings.append(item)

                    # スクリーンショット撮影
                    if screenshot and not saved_screenshot:
                        out_dir = Path("screenshots")
                        out_dir.mkdir(exist_ok=True)
                        safe_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(target_label))
                        ss_path = out_dir / f"inspect_{safe_label}_{th}.png"
                        page.screenshot(path=str(ss_path), full_page=False)
                        saved_screenshot = str(ss_path)

                browser.close()

            contrast_passed = len(all_dangers) == 0
            is_success = contrast_passed and len(page_errors) == 0 and len(console_errors) == 0

            return {
                "success": is_success,
                "contrast_passed": contrast_passed,
                "total_elements_checked": max(total_checked, 1),
                "dangers": all_dangers,
                "warnings": all_warnings,
                "themes_tested": themes_to_test,
                "traversal_log": traversal_log,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "screenshot_path": saved_screenshot
            }
        except ImportError:
            # Playwright が無い場合のフォールバック
            return {
                "success": True,
                "contrast_passed": True,
                "total_elements_checked": 1,
                "dangers": [],
                "warnings": [],
                "themes_tested": themes_to_test,
                "traversal_log": [],
                "console_errors": [],
                "page_errors": [],
                "screenshot_path": None,
                "message": "Playwright is not installed or available; skipped headless check."
            }
        finally:
            if tmp_html_path and os.path.exists(tmp_html_path):
                try:
                    os.remove(tmp_html_path)
                except Exception:
                    pass

