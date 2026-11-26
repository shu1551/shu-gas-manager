# -*- coding: utf-8 -*-
"""
gas_ws_browser.py - ブラウザ連動（Chrome拡張の同期受信＋Windowsウィンドウタイトル検知）

1. Chrome 拡張（ws_browser_ext）から 127.0.0.1:18767/sync 等へ送られるアクティブタブ情報を
   .ws_browser_active.json へアトミックに保存し、WorkspaceManager から参照できるようにする。
2. 拡張が未動作・未更新の環境向けの補助として、Windows の可視ウィンドウタイトルから
   開いている Google スプレッドシート / ドキュメント名を検出する。
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time

HERE = Path(__file__).resolve().parent
BROWSER_ACTIVE_PATH = HERE / ".ws_browser_active.json"
MCP_SYNC_PORT = 18767
EXT_FIXED_ID = "mbkcmenmaeaiemdppphmbokhbfckpjhm"
DEFAULT_MAX_AGE_SEC = 600.0
RECONNECT_GAP_SEC = 30.0

_FILE_LOCK = threading.Lock()
_SYNC_SERVERS = {}
_SRV_LOCK = threading.Lock()

_SHEET_TITLE_RE = re.compile(r"^(.+?)\s*-\s*Google\s*(?:スプレッドシート|Sheets)(?:\s*-\s*.*)?$", re.IGNORECASE)
_DOC_TITLE_RE = re.compile(r"^(.+?)\s*-\s*Google\s*(?:ドキュメント|Docs)(?:\s*-\s*.*)?$", re.IGNORECASE)


def _default_url(fid, kind):
    if kind == "doc":
        return f"https://docs.google.com/document/d/{fid}/edit"
    return f"https://docs.google.com/spreadsheets/d/{fid}/edit"


def _read_json_unlocked(p):
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_browser_active(data, path=None, source="ext"):
    """Chrome 拡張などから受け取ったアクティブタブ情報を .ws_browser_active.json に保存する。"""
    if not isinstance(data, dict):
        return None
    fid = str(data.get("id") or "").strip()
    if not fid:
        return None

    kind = str(data.get("kind") or "sheet").strip().lower()
    if kind not in ("sheet", "doc"):
        kind = "sheet"

    p = Path(path) if path else BROWSER_ACTIVE_PATH
    now = float(data.get("ts") or time.time())
    # ミリ秒で渡された場合を秒へ丸める
    if now > 1e12:
        now = now / 1000.0

    partial = bool(data.get("partial"))
    force = bool(data.get("force"))

    with _FILE_LOCK:
        prev = _read_json_unlocked(p)
        same_id = prev.get("id") == fid and prev.get("kind") == kind

        name = str(data.get("name") or "").strip()
        sheet = str(data.get("sheet") or "").strip()
        selection = str(data.get("selection") or "").strip()
        heading = str(data.get("heading") or "").strip()
        gid = str(data.get("gid") or "").strip()
        url = str(data.get("url") or "").strip()

        if partial and same_id:
            if not name:
                name = str(prev.get("name") or "").strip()
            if not sheet:
                sheet = str(prev.get("sheet") or "").strip()
            if not selection:
                selection = str(prev.get("selection") or "").strip()
            if not heading:
                heading = str(prev.get("heading") or "").strip()
            if not gid:
                gid = str(prev.get("gid") or "").strip()

        if not url:
            url = str(prev.get("url") or "").strip() if same_id else ""
        if not url:
            url = _default_url(fid, kind)

        sig = [fid, kind, sheet, selection, heading]
        prev_sig = [
            str(prev.get("id") or ""),
            str(prev.get("kind") or ""),
            str(prev.get("sheet") or ""),
            str(prev.get("selection") or ""),
            str(prev.get("heading") or ""),
        ]
        prev_seen = float(prev.get("seen_at") or 0.0)
        prev_changed = float(prev.get("changed_at") or 0.0)

        if not prev or sig != prev_sig or (now - prev_seen > RECONNECT_GAP_SEC) or force:
            changed_at = now
        else:
            changed_at = prev_changed or now

        entry = {
            "id": fid,
            "kind": kind,
            "url": url,
            "gid": gid,
            "name": name,
            "sheet": sheet,
            "selection": selection,
            "heading": heading,
            "source": str(source or "ext"),
            "seen_at": now,
            "changed_at": changed_at,
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
            for attempt in range(5):
                try:
                    tmp.replace(p)
                    break
                except OSError:
                    if attempt < 4:
                        time.sleep(0.02 * (attempt + 1))
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return dict(entry)


def load_browser_active(path=None, max_age_sec=DEFAULT_MAX_AGE_SEC):
    """保存済みのブラウザアクティブタブ情報を返す。期限切れや未保存時は None。"""
    p = Path(path) if path else BROWSER_ACTIVE_PATH
    with _FILE_LOCK:
        data = _read_json_unlocked(p)
    fid = str(data.get("id") or "").strip()
    if not fid:
        return None
    seen_at = float(data.get("seen_at") or 0.0)
    age_sec = max(0.0, time.time() - seen_at) if seen_at > 0 else 0.0
    if max_age_sec is not None and (seen_at <= 0 or age_sec > float(max_age_sec)):
        return None
    out = dict(data)
    out["age_sec"] = round(age_sec, 1)
    return out


def start_mcp_sync_server(port=MCP_SYNC_PORT, path=None):
    """127.0.0.1:{port} で Chrome 拡張からの /sync 通知を受け取る軽量 HTTP サーバーを起動する。"""
    p_key = int(port)
    active_path = Path(path) if path else BROWSER_ACTIVE_PATH
    with _SRV_LOCK:
        existing = _SYNC_SERVERS.get(p_key)
        if existing is not None:
            return existing

        allowed_ext_origin = f"chrome-extension://{EXT_FIXED_ID}"

        class _McpSyncHandler(BaseHTTPRequestHandler):
            def log_message(self, _fmt, *_args):
                pass

            def _origin_ok(self):
                o = str(self.headers.get("Origin") or "").strip()
                if o:
                    return o == allowed_ext_origin or o == "https://docs.google.com"
                sfs = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                return sfs in ("", "none")

            def _send_cors(self):
                o = str(self.headers.get("Origin") or "").strip()
                if o and (o == allowed_ext_origin or o == "https://docs.google.com"):
                    self.send_header("Access-Control-Allow-Origin", o)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Private-Network", "true")

            def _reply(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self._send_cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                self._reply({"ok": True}, code=200)

            def do_GET(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                if self.path.startswith("/ping"):
                    actual_port = self.server.server_address[1]
                    self._reply({"ok": True, "app": "gas-manager-mcp", "pid": os.getpid(), "port": actual_port})
                elif self.path.startswith("/active"):
                    cur = load_browser_active(active_path, max_age_sec=None)
                    self._reply(cur if cur is not None else {})
                else:
                    self._reply({"ok": True, "app": "gas-manager-mcp"})

            def do_POST(self):
                if not self._origin_ok():
                    self._reply({"ok": False, "error": "origin not allowed"}, code=403)
                    return
                if not self.path.startswith("/sync"):
                    self._reply({"ok": False, "error": "not found"}, code=404)
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except Exception:
                    length = 0
                if length <= 0 or length > 64 * 1024:
                    self._reply({"ok": False, "error": "body empty or too large"}, code=400)
                    return
                try:
                    raw = self.rfile.read(length).decode("utf-8", "replace")
                    data = json.loads(raw)
                except Exception as e:
                    self._reply({"ok": False, "error": f"invalid json: {e}"}, code=400)
                    return
                if not isinstance(data, dict):
                    self._reply({"ok": False, "error": "json object required"}, code=400)
                    return
                save_browser_active(data, path=active_path, source="mcp-sync")
                self._reply({"ok": True})

        class _Srv(ThreadingHTTPServer):
            allow_reuse_address = False
            daemon_threads = True

        try:
            srv = _Srv(("127.0.0.1", p_key), _McpSyncHandler)
        except OSError:
            return None

        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        if p_key != 0:
            _SYNC_SERVERS[p_key] = srv
        return srv


def parse_window_title(title):
    """ブラウザのウィンドウタイトルから Google スプレッドシート / ドキュメントの名前と種別を抽出する。"""
    t = str(title or "").strip()
    if not t:
        return None
    m = _SHEET_TITLE_RE.match(t)
    if m:
        name = m.group(1).strip()
        if name:
            return {"name": name, "kind": "sheet", "window_title": t}
    m = _DOC_TITLE_RE.match(t)
    if m:
        name = m.group(1).strip()
        if name:
            return {"name": name, "kind": "doc", "window_title": t}
    return None


def detect_window_targets():
    """Windows の可視ウィンドウを Z-order（手前順）で走査し、開いている Google スプレッドシート / 文書候補を返す。"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    val = buf.value.strip()
                    if val:
                        titles.append(val)
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        out = []
        seen = set()
        for t in titles:
            parsed = parse_window_title(t)
            if not parsed:
                continue
            key = (parsed["name"], parsed["kind"])
            if key in seen:
                continue
            seen.add(key)
            out.append(parsed)
        return out
    except Exception:
        return []


def _ping_local_port(port, timeout=0.3):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/ping", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return bool(isinstance(data, dict) and data.get("ok")), data
    except Exception:
        return False, None


def diagnose_browser_sync(port=MCP_SYNC_PORT, watch_port=18766, chrome_user_data=None):
    """受信ポート(18767/18766)の疎通と Chrome 拡張の登録状態（重複ID・無効化理由）を診断する。"""
    mcp_ok, _ = _ping_local_port(port)
    watch_ok, _ = _ping_local_port(watch_port)

    ud = Path(chrome_user_data) if chrome_user_data else None
    if ud is None and os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            ud = Path(local_app) / "Google" / "Chrome" / "User Data"

    ext_registered = None
    ext_path = ""
    ext_disable_reasons = []
    duplicate_ids = []
    hints = []

    if not mcp_ok:
        hints.append(f"MCP 受信ポート {port} が応答していません（MCP サーバーの再読込/再起動を確認してください）")

    if ud is not None:
        sp_path = ud / "Default" / "Secure Preferences"
        if sp_path.is_file():
            try:
                sp = json.loads(sp_path.read_text(encoding="utf-8", errors="replace"))
                settings = ((sp.get("extensions") or {}).get("settings") or {})
                cur = settings.get(EXT_FIXED_ID)
                if isinstance(cur, dict):
                    ext_registered = True
                    ext_path = str(cur.get("path") or "").strip()
                    ext_disable_reasons = list(cur.get("disable_reasons") or [])
                else:
                    ext_registered = False

                norm_ext_path = ext_path.lower().rstrip("\\/")
                for eid, info in settings.items():
                    if eid == EXT_FIXED_ID or not isinstance(info, dict):
                        continue
                    ep = str(info.get("path") or "").strip()
                    norm_ep = ep.lower().rstrip("\\/")
                    if (norm_ext_path and norm_ep == norm_ext_path) or ("ws_browser_ext" in norm_ep):
                        duplicate_ids.append({
                            "id": eid,
                            "path": ep,
                            "disable_reasons": list(info.get("disable_reasons") or []),
                        })
            except Exception:
                pass

    if ext_registered is False:
        hints.append("Chrome に拡張機能（GASコンボ ブラウザ連動）が未登録です。chrome://extensions から読み込んでください")
    elif ext_disable_reasons:
        hints.append(f"Chrome で拡張機能が無効化されています（disable_reasons={ext_disable_reasons}）。chrome://extensions で有効化または再読み込みしてください")

    if duplicate_ids:
        dup_desc = "・".join(f"{d['id']}(disable={d['disable_reasons']})" for d in duplicate_ids[:3])
        hints.append(
            f"同じパス/旧版と競合する拡張登録が残っています（{dup_desc}）。再起動で消える場合は別パスのジャンクション（例: gas_combo_ext）から読み込んでください"
        )

    return {
        "mcp_sync_ok": mcp_ok,
        "mcp_port": int(port),
        "watch_ok": watch_ok,
        "watch_port": int(watch_port),
        "ext_registered": ext_registered,
        "ext_path": ext_path,
        "ext_disable_reasons": ext_disable_reasons,
        "duplicate_ids": duplicate_ids,
        "hints": hints,
    }
