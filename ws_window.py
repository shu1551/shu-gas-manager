"""GASコンボ（Excelコンボ風レイアウト・AIなし即棚打ちデスクトップ窓）。"""

import argparse
import ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gas_workspace
import gas_ws_ask
import ws_window_ai

FONT_UI = ("BIZ UDPゴシック", 13)
FONT_BOLD = FONT_UI
FONT_MONO = ("BIZ UDゴシック", 12)
CMD_FILE = HERE / ".ws_window_cmd.json"
RECENT_FILE = HERE / ".ws_recent_targets.json"
VER_FILE = HERE / ".ws_window_ver.txt"
BROWSER_SYNC_PORT = 18765
BROWSER_EXT_DIR = HERE / "ws_browser_ext"


def _start_browser_sync_server(ui_queue):
    """ブラウザ拡張からの選択セル範囲・シート・対象ファイル通知を 127.0.0.1:18765 で待ち受ける。"""

    class _SyncHandler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def _origin_ok(self):
            # 拡張機能（chrome-extension://）と Google の画面（docs.google.com）からだけ受ける。
            # ほかのサイトが勝手に「相手のシート」をすり替えられないように
            o = str(self.headers.get("Origin") or "").strip()
            return (not o) or o.startswith("chrome-extension://") or o == "https://docs.google.com"

        def _send_json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            o = str(self.headers.get("Origin") or "").strip()
            if o and self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if not self._origin_ok():
                self._send_json(403, {"ok": False, "error": "origin not allowed"})
                return
            self._send_json(200, {"ok": True})

        def do_GET(self):
            if not self._origin_ok():
                self._send_json(403, {"ok": False, "error": "origin not allowed"})
                return
            self._send_json(200, {"ok": True, "app": "gas-combo"})

        def do_POST(self):
            if not self._origin_ok():
                self._send_json(403, {"ok": False, "error": "origin not allowed"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace") if length > 0 else "{}"
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("id"):
                    ui_queue.put(("browser_sync", data, "", 0.0))
                    try:
                        import gas_ws_browser
                        gas_ws_browser.save_browser_active(data, source="ws-window")
                    except Exception:
                        pass
                self._send_json(200, {"ok": True})
            except Exception as e:
                self._send_json(400, {"ok": False, "error": str(e)})

    def serve():
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", BROWSER_SYNC_PORT), _SyncHandler)
            srv.daemon_threads = True
            srv.serve_forever()
        except Exception:
            pass

    threading.Thread(target=serve, daemon=True).start()


def _code_signature():
    """このスクリプト自体の更新時刻・サイズから版識別子を返す。"""
    st = Path(__file__).resolve().stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _close_mutex(handle):
    if handle:
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def _load_recent_targets():
    """最近使った対象（シート・文書）の一覧を読み込む。"""
    try:
        if RECENT_FILE.exists():
            data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict) and x.get("id")]
    except Exception:
        pass
    return []


def _save_recent_target(tgt):
    """現在の対象を最近使った対象一覧の先頭に記憶する（最大20件）。"""
    fid = (tgt or {}).get("id")
    if not fid:
        return
    entry = {
        "id": fid,
        "name": tgt.get("name") or fid,
        "kind": tgt.get("kind") or "sheet",
        "url": tgt.get("url") or "",
    }
    items = [x for x in _load_recent_targets() if x.get("id") != fid]
    items.insert(0, entry)
    try:
        RECENT_FILE.write_text(json.dumps(items[:20], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def send_window_cmd(action="show", target="", sheet=""):
    """常駐中の GASコンボ 窓へ表示・対象切替の合図ファイルを書く。"""
    payload = {"action": action, "target": target or "", "sheet": sheet or "", "ts": time.time()}
    tmp = CMD_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CMD_FILE)


def _acquire_single_instance_mutex():
    """同一ユーザーセッション内での二重起動を防ぐ Mutex を取得する。"""
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.CreateMutexW(None, False, "Local\\GasComboWindowSingleInstance")
        already = k32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        return handle, already
    except Exception:
        return None, False


def _format_ops_short(ops):
    """ops リストを短い文字列に整形する。"""
    parts = []
    for o in ops:
        args = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False)}"
            for k, v in o.items()
            if k != "shelf"
        )
        parts.append(f"{o.get('shelf', '?')}({args})")
    return ", ".join(parts)


def _format_exec_timing(mgr, wall_sec):
    """WorkspaceManager の計測結果から内訳文字列を作る。"""
    tim = getattr(mgr, "last_timing", None)
    if not tim or not isinstance(getattr(tim, "laps", None), dict):
        return f"合計 {wall_sec:.2f}s"
    total = sum(tim.laps.values()) if tim.laps else wall_sec
    eng_ms = (tim.engine or {}).get("total")
    if isinstance(eng_ms, (int, float)):
        eng_s = eng_ms / 1000.0
        py_s = max(0.0, total - eng_s)
        return f"合計 {total:.2f}s（Python/通信 {py_s:.2f}s / GAS {eng_s:.2f}s）"
    return f"合計 {total:.2f}s"


class GasComboWindow:
    """Excelコンボと同じ構成・操作感を持つ GASマネージャー操作窓。"""

    def __init__(self, root, initial_target="", initial_sheet="", start_hidden=False):
        self.root = root
        self.root.title("GASコンボ")
        # ×ボタンでは終了せず非表示で常駐待機し、チャットや再起動から即呼び出せるようにする
        self.root.protocol("WM_DELETE_WINDOW", self.on_hide_window)

        self.dpi_scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Excelコンボに近い縦長コンパクトサイズで画面右寄りに配置する
        w = min(int(590 * self.dpi_scale), int(sw * 0.88))
        h = min(int(635 * self.dpi_scale), int(sh * 0.90))
        x = max(20, sw - w - 30)
        self.root.geometry(f"{w}x{h}+{x}+20")
        self.root.minsize(int(480 * self.dpi_scale), int(520 * self.dpi_scale))
        self.wrap_w = max(360, w - int(50 * self.dpi_scale))

        self.mgr = gas_workspace.WorkspaceManager()
        self.mgr.timing = False
        self.ui_queue = queue.Queue()
        self.busy = False
        self.history = []
        self.hist_idx = -1
        self.drive_files = []
        self._choice_map = {}
        self.ai = ws_window_ai.GasAiRunner(model=ws_window_ai.DEFAULT_MODEL)
        self._last_look_text = ""
        self._last_look_id = ""
        self.browser_selection = ""
        self.browser_sheet = ""
        self.browser_heading = ""
        self._last_prefetch_key = ("", "")
        self._prefetching = False

        self._build_vars()
        self._build_ui()
        self._refresh_from_state()
        _start_browser_sync_server(self.ui_queue)
        self.root.after(100, self._poll_queue)
        self.root.after(200, self._poll_cmd)
        self.root.after(250, self._refresh_drive_targets_async)
        self.root.after(450, lambda: threading.Thread(target=self.ai.prewarm, daemon=True).start())
        self.root.after(600, lambda: threading.Thread(target=self._prewarm_engine_conn, daemon=True).start())
        if start_hidden:
            self.root.withdraw()
        else:
            self.root.after(150, self._bring_to_front)

        if initial_target:
            self.target_var.set(initial_target)
            if initial_sheet:
                self.sheet_var.set(initial_sheet)
            self.root.after(150, lambda: self.on_look(sheet=initial_sheet))

    def _prewarm_engine_conn(self):
        """起動直後の初回操作を速くするため、エンジン Web アプリへの接続を事前に温める。"""
        try:
            url = (self.mgr._load() or {}).get("engine_url") or ""
            if url.endswith("/exec"):
                self.mgr.client.call_webapp(url, body={"action": "ping"}, method="POST", use_auth=True, timeout=15)
        except Exception:
            pass

    def _build_vars(self):
        self.target_var = tk.StringVar()
        self.target_choice_var = tk.StringVar()
        self.sheet_var = tk.StringVar()
        self.info_var = tk.StringVar(value="対象: 未選択（上部の一覧／貼付切替、または［設定］で指定）")
        self.sel_var = tk.StringVar(value="ブラウザ連動: 待機中（拡張機能から自動取得）")
        self.preview_var = tk.StringVar(value="自動判定: 待機中")
        self.ok_var = tk.BooleanVar(value=False)
        self.untopmost_var = tk.BooleanVar(value=False)
        self.backup_var = tk.BooleanVar(value=False)
        self.ai_auto_var = tk.BooleanVar(value=True)
        self.browser_sync_var = tk.BooleanVar(value=True)
        self.ai_model_var = tk.StringVar(value=ws_window_ai.DEFAULT_MODEL)
        self.status_var = tk.StringVar(value="表示中: 自動")

    def _build_ui(self):
        self.root.option_add("*TCombobox*Listbox.font", FONT_UI)
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure(".", font=FONT_UI, foreground="#000000")
        style.configure("TLabel", font=FONT_UI, foreground="#000000")
        style.configure("TButton", font=FONT_UI, foreground="#000000", padding=(4, 2))
        style.configure("Run.TButton", font=FONT_BOLD, foreground="#000000", padding=(8, 8))
        style.configure("TEntry", font=FONT_UI, foreground="#000000")
        style.configure("TCombobox", font=FONT_UI, foreground="#000000")
        style.configure("TCheckbutton", font=FONT_UI, foreground="#000000")
        style.configure("TNotebook.Tab", font=FONT_UI, foreground="#000000", padding=(8, 2))

        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_top_input(main)
        self._build_option_row(main)
        self._build_target_bar(main)
        self._build_tabs(main)
        self._build_bottom_bar(main)

    def _build_top_input(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 4))

        self.ask_text = tk.Text(
            top, height=3, width=20, font=FONT_UI, fg="#000000", bg="#FFFFFF",
            wrap=tk.WORD, relief=tk.SOLID, borderwidth=1, spacing2=3
        )
        self.ask_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.ask_text.bind("<Return>", self.on_return_key)
        self.ask_text.bind("<Shift-Return>", lambda _e: None)
        self.ask_text.bind("<Up>", self.on_hist_up)
        self.ask_text.bind("<Down>", self.on_hist_down)
        self.ask_text.bind("<KeyRelease>", lambda _e: self._update_ask_preview())

        btns = ttk.Frame(top)
        btns.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(btns, text="実 行", style="Run.TButton", width=7, command=self.on_run_ask).pack(
            fill=tk.X, expand=True, pady=(0, 4)
        )
        ttk.Button(btns, text="クリア(×)", width=7, command=self.on_clear_input).pack(fill=tk.X)

    def _build_option_row(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 4))

        ttk.Checkbutton(row, text="確認なし", variable=self.ok_var).pack(side=tk.LEFT)
        ttk.Checkbutton(row, text="控え", variable=self.backup_var, command=self.on_toggle_backup).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Checkbutton(row, text="手前解除", variable=self.untopmost_var, command=self.on_toggle_topmost).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Checkbutton(row, text="AI自動", variable=self.ai_auto_var, command=self._update_ask_preview).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Checkbutton(row, text="連動", variable=self.browser_sync_var, command=self.on_toggle_browser_sync).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Label(row, textvariable=self.status_var, foreground="#000000").pack(side=tk.RIGHT)

    def _build_target_bar(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text="対象:").pack(side=tk.LEFT, padx=(0, 4))
        self.target_combo = ttk.Combobox(
            row, textvariable=self.target_choice_var, state="readonly", font=FONT_UI, width=10
        )
        self.target_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.target_combo.bind("<<ComboboxSelected>>", self.on_select_target_choice)
        ttk.Button(row, text="貼付切替", width=0, command=self.on_paste_target).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="一覧更新", width=0, command=lambda: self._refresh_drive_targets_async(notify=True)).pack(side=tk.LEFT)

    def _build_tabs(self, parent):
        self.nb = ttk.Notebook(parent)
        self.nb.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.tab_auto = ttk.Frame(self.nb, padding=8)
        self.tab_chat = ttk.Frame(self.nb, padding=6)
        self.tab_hist = ttk.Frame(self.nb, padding=6)
        self.tab_trace = ttk.Frame(self.nb, padding=6)
        self.tab_conf = ttk.Frame(self.nb, padding=8)

        self.nb.add(self.tab_auto, text="自動")
        self.nb.add(self.tab_chat, text="会話")
        self.nb.add(self.tab_hist, text="履歴")
        self.nb.add(self.tab_trace, text="経過")
        self.nb.add(self.tab_conf, text="設定")

        self._build_tab_auto()
        self._build_tab_chat()
        self._build_tab_hist()
        self._build_tab_trace()
        self._build_tab_conf()

    def _build_quick_panel(self, parent, main_text, main_cmd, quick):
        """自動タブ用の大ボタン＋3列クイックボタン群を作る。"""
        box = ttk.Frame(parent)
        ttk.Button(box, text=main_text, command=main_cmd).pack(fill=tk.X, pady=(0, 8))

        grid = ttk.Frame(box)
        grid.pack(fill=tk.X, pady=(0, 6))
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="qbtn")

        for idx, (label, cmd) in enumerate(quick):
            r, c = divmod(idx, 3)
            ttk.Button(grid, text=label, command=cmd).grid(row=r, column=c, sticky="ew", padx=2, pady=2)
        return box

    def _switch_auto_panel(self, kind):
        """現在の対象種別（sheet / doc）に合わせて自動タブのボタンを切り替える。"""
        k = "doc" if kind == "doc" else "sheet"
        if getattr(self, "_active_auto_kind", None) == k:
            return
        self._active_auto_kind = k
        if k == "doc":
            self.auto_sheet_panel.pack_forget()
            self.auto_doc_panel.pack(fill=tk.X)
        else:
            self.auto_doc_panel.pack_forget()
            self.auto_sheet_panel.pack(fill=tk.X)

    def _build_tab_auto(self):
        self.auto_host = ttk.Frame(self.tab_auto)
        self.auto_host.pack(fill=tk.X)
        self._active_auto_kind = None

        sheet_quick = [
            ("読込", lambda: self.on_look()),
            ("戻す", self.on_undo),
            ("合計行", lambda: self.on_run_ops([{"shelf": "total"}])),
            ("列幅自動", self.on_auto_width),
            ("見出し固定", self.on_freeze_header),
            ("固定解除", lambda: self.on_run_ops([{"shelf": "unfreeze"}])),
            ("フィルタON", lambda: self.on_run_ops([{"shelf": "filter.on"}])),
            ("フィルタOFF", lambda: self.on_run_ops([{"shelf": "filter.off"}])),
            ("重複削除", lambda: self.on_run_ops([{"shelf": "dedupe"}])),
            ("交互の色", lambda: self.on_run_ops([{"shelf": "banding.add", "theme": "blue"}])),
            ("交互解除", lambda: self.on_run_ops([{"shelf": "banding.remove"}])),
            ("棚検索", self.on_find_shelf),
        ]
        doc_quick = [
            ("読込", lambda: self.on_look()),
            ("戻す", self.on_undo),
            ("章立て確認", lambda: self.on_run_ops([{"shelf": "doc.outline"}])),
            ("目次挿入", lambda: self.on_run_ops([{"shelf": "doc.toc"}])),
            ("ページ番号", lambda: self.on_run_ops([{"shelf": "doc.header", "page_number": True}])),
            ("表の装飾", lambda: self.on_run_ops([{"shelf": "doc.table.style"}])),
            ("左揃え", lambda: self.on_run_ops([{"shelf": "doc.align", "align": "left"}])),
            ("中央揃え", lambda: self.on_run_ops([{"shelf": "doc.align", "align": "center"}])),
            ("行間1.5", lambda: self.on_run_ops([{"shelf": "doc.align", "line_spacing": 1.5}])),
            ("箇条書き", lambda: self.on_run_ops([{"shelf": "doc.list", "type": "bullet"}])),
            ("リスト解除", lambda: self.on_run_ops([{"shelf": "doc.list", "type": "none"}])),
            ("棚検索", self.on_find_shelf),
        ]

        self.auto_sheet_panel = self._build_quick_panel(
            self.auto_host,
            "【一発整形】データ整理 ＋ 表を整える",
            lambda: self.on_run_ops([{"shelf": "seiri"}]),  # seiri が内部で tidy を行うため単独で呼ぶ
            sheet_quick,
        )
        self.auto_doc_panel = self._build_quick_panel(
            self.auto_host,
            "【一発整形】文書の体裁を整える",
            lambda: self.on_run_ops([{"shelf": "doc.style"}]),
            doc_quick,
        )
        self._switch_auto_panel("sheet")

        ttk.Label(self.tab_auto, textvariable=self.sel_var, foreground="#000000", wraplength=self.wrap_w).pack(
            fill=tk.X, pady=(6, 2)
        )
        ttk.Label(self.tab_auto, textvariable=self.preview_var, foreground="#000000", wraplength=self.wrap_w).pack(
            fill=tk.X, pady=(2, 2)
        )
        ttk.Label(self.tab_auto, textvariable=self.info_var, foreground="#000000", wraplength=self.wrap_w).pack(
            fill=tk.X, pady=(2, 0)
        )

    def _build_tab_chat(self):
        frame = ttk.Frame(self.tab_chat)
        frame.pack(fill=tk.BOTH, expand=True)

        self.chat_text = tk.Text(
            frame, width=32, height=10, font=FONT_MONO, fg="#000000", bg="#FFFFFF",
            wrap=tk.WORD, state=tk.DISABLED, spacing2=3
        )
        scr = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=scr.set)
        self.chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

        bar = ttk.Frame(self.tab_chat)
        bar.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(bar, text="AIへコピー", command=self.on_copy_for_ai).pack(side=tk.LEFT)
        ttk.Button(bar, text="会話消去", command=self.on_clear_log).pack(side=tk.RIGHT)

    def _build_tab_hist(self):
        frame = ttk.Frame(self.tab_hist)
        frame.pack(fill=tk.BOTH, expand=True)

        self.hist_list = tk.Listbox(frame, font=FONT_UI, fg="#000000", bg="#FFFFFF")
        scr = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.hist_list.yview)
        self.hist_list.configure(yscrollcommand=scr.set)
        self.hist_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)
        self.hist_list.bind("<Double-Button-1>", lambda _e: self.on_rerun_hist())

        bar = ttk.Frame(self.tab_hist)
        bar.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(bar, text="入力欄へ", command=self.on_use_hist).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bar, text="再実行", command=self.on_rerun_hist).pack(side=tk.LEFT)

    def _build_tab_trace(self):
        frame = ttk.Frame(self.tab_trace)
        frame.pack(fill=tk.BOTH, expand=True)

        self.trace_text = tk.Text(
            frame, width=32, height=10, font=FONT_MONO, fg="#000000", bg="#FFFFFF",
            wrap=tk.WORD, state=tk.DISABLED, spacing2=3
        )
        scr = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.trace_text.yview)
        self.trace_text.configure(yscrollcommand=scr.set)
        self.trace_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_tab_conf(self):
        ttk.Label(self.tab_conf, text="URL / ID / ファイル名:").pack(anchor=tk.W)
        row1 = ttk.Frame(self.tab_conf)
        row1.pack(fill=tk.X, pady=(2, 6))
        ttk.Entry(row1, textvariable=self.target_var, width=10, font=FONT_UI).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row1, text="貼付", width=0, command=self.on_paste_target).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="読込", width=0, command=lambda: self.on_look()).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="開く", width=0, command=self.on_open_browser).pack(side=tk.LEFT)

        ttk.Label(self.tab_conf, text="シート切替:").pack(anchor=tk.W)
        self.sheet_combo = ttk.Combobox(self.tab_conf, textvariable=self.sheet_var, state="readonly", font=FONT_UI)
        self.sheet_combo.pack(fill=tk.X, pady=(2, 8))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_look(sheet=self.sheet_var.get()))

        ttk.Label(self.tab_conf, textvariable=self.info_var, foreground="#000000", wraplength=self.wrap_w).pack(
            fill=tk.X, pady=(4, 8)
        )
        ai_row = ttk.Frame(self.tab_conf)
        ai_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(ai_row, text="AIモデル:").pack(side=tk.LEFT, padx=(0, 6))
        model_cb = ttk.Combobox(
            ai_row, textvariable=self.ai_model_var, values=["haiku", "sonnet"], state="readonly", font=FONT_UI, width=10
        )
        model_cb.pack(side=tk.LEFT)
        model_cb.bind("<<ComboboxSelected>>", lambda _e: self.ai.set_model(self.ai_model_var.get()))
        ttk.Button(ai_row, text="ブラウザ拡張フォルダ", command=self.on_open_ext_folder).pack(side=tk.RIGHT)
        ttk.Button(self.tab_conf, text="完全終了（常駐を止める）", command=self.on_quit_app).pack(anchor=tk.E)

    def _build_bottom_bar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X)
        for c in range(3):
            bar.columnconfigure(c, weight=1, uniform="btm")

        ttk.Button(bar, text="新しい話", command=self.on_new_talk).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(bar, text="直前を取り消す", command=self.on_undo).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(bar, text="隠す（待機）", command=self.on_hide_window).grid(row=0, column=2, sticky="ew", padx=(4, 0))

    # ------------------------------------------------------------ 入力・テキスト操作
    def _get_ask(self):
        return self.ask_text.get("1.0", "end-1c").strip()

    def _set_ask(self, text):
        self.ask_text.delete("1.0", tk.END)
        self.ask_text.insert("1.0", text)
        self._update_ask_preview()

    def _append_box(self, widget, msg):
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, msg.rstrip() + "\n" + "-" * 42 + "\n")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _on_tab_changed(self, _e):
        if not self.busy:
            tab_text = self.nb.tab(self.nb.select(), "text")
            self.status_var.set(f"表示中: {tab_text}")

    # ------------------------------------------------------------ 状態反映・プレビュー
    def _refresh_from_state(self):
        st = self.mgr._load()
        tgt = st.get("target") or {}
        kind = tgt.get("kind") or "sheet"
        if tgt.get("id"):
            _save_recent_target(tgt)
        if tgt.get("url"):
            self.target_var.set(tgt["url"])
        elif tgt.get("id"):
            self.target_var.set(tgt["id"])

        self.backup_var.set(bool(st.get("backup", False)))
        self._switch_auto_panel(kind)
        if kind == "doc":
            self.sheet_combo["values"] = []
            self.sheet_var.set("")
            self.sheet_combo.configure(state="disabled")
            if tgt.get("name"):
                self.info_var.set(f"[文書] {tgt.get('name')}\n（Google ドキュメントを選択中）")
        else:
            tc = self.mgr._cached_table(st, tgt) or {}
            sheets = tc.get("sheets") or []
            self.sheet_combo.configure(state="readonly")
            self.sheet_combo["values"] = sheets
            cur_sh = tgt.get("sheet") or (sheets[0] if sheets else "")
            self.sheet_var.set(cur_sh)
            tb = tc.get("table")
            if tgt.get("name"):
                if tb:
                    cols = "・".join(f"{c['col']}:{c['name']}" for c in tb.get("columns") or [])
                    self.info_var.set(
                        f"[表] {tgt.get('name')} › {cur_sh}\n見出し{tb.get('header_row')}行 ({tb.get('first_col')}〜{tb.get('last_col')}・{tb.get('data')}行) / 列: {cols}"
                    )
                else:
                    self.info_var.set(f"[表] {tgt.get('name')} › {cur_sh}（表情報なし）")
        self._rebuild_target_choices(tgt)
        self._update_selection_label(st)
        self._update_ask_preview()

    def _update_selection_label(self, st=None):
        """ブラウザ連動による現在の選択セル範囲・見出し表示を更新する。"""
        if not self.browser_sync_var.get():
            self.sel_var.set("ブラウザ連動: OFF（上部「連動」チェックで有効化）")
            return
        if st is None:
            st = self.mgr._load()
        tgt = st.get("target") or {}
        ls_info = st.get("last_scope") or {}
        if ls_info.get("id") and ls_info.get("id") == tgt.get("id"):
            if (tgt.get("kind") or "sheet") == "doc":
                hd = ls_info.get("heading") or self.browser_heading
                if hd:
                    self.sel_var.set(f"ブラウザ連動中: 見出し「{hd}」")
                elif tgt.get("name"):
                    self.sel_var.set(f"ブラウザ連動中: {tgt.get('name')}")
                else:
                    self.sel_var.set("ブラウザ連動: 待機中（拡張機能から自動取得）")
                return
            sel = ls_info.get("selection") or self.browser_selection
            sh = ls_info.get("sheet") or tgt.get("sheet") or self.browser_sheet
            if sel:
                sh_part = f"{sh} › " if sh else ""
                self.sel_var.set(f"ブラウザ選択中: {sh_part}{sel}（「ここ」「選択範囲」や場所省略で即適用）")
                return
        if self.browser_selection:
            self.sel_var.set(f"ブラウザ選択中: {self.browser_selection}")
        else:
            self.sel_var.set("ブラウザ連動: 待機中（拡張機能から自動取得）")

    def _rebuild_target_choices(self, cur_tgt=None):
        """現在の対象・最近使った履歴・Drive一覧をまとめてドロップダウンへ反映する。"""
        if cur_tgt is None:
            cur_tgt = (self.mgr._load() or {}).get("target") or {}
        merged = []
        seen_ids = set()

        def add_item(item):
            fid = (item or {}).get("id")
            if not fid or fid in seen_ids:
                return
            seen_ids.add(fid)
            kind = item.get("kind") or ("doc" if item.get("mimeType") == gas_workspace.MIME_DOC else "sheet")
            merged.append({"id": fid, "name": item.get("name") or fid, "kind": kind})

        if cur_tgt.get("id"):
            add_item(cur_tgt)
        for it in _load_recent_targets():
            add_item(it)
        for f in self.drive_files:
            add_item(f)

        labels = []
        choice_map = {}
        used_labels = set()
        cur_label = ""
        cur_id = cur_tgt.get("id")
        for it in merged:
            tag = "文書" if it["kind"] == "doc" else "表"
            label = f"[{tag}] {it['name']}"
            if label in used_labels:
                label = f"[{tag}] {it['name']} ({it['id'][:6]})"
            used_labels.add(label)
            labels.append(label)
            choice_map[label] = it["id"]
            if it["id"] == cur_id and not cur_label:
                cur_label = label

        self._choice_map = choice_map
        self.target_combo["values"] = labels
        if cur_label:
            self.target_choice_var.set(cur_label)
        elif labels and not self.target_choice_var.get():
            self.target_choice_var.set("（対象を選択…）")

    def _refresh_drive_targets_async(self, notify=False):
        """Google Drive から最近のスプレッドシート・ドキュメント一覧を非同期で取得する。"""
        if notify:
            self.status_var.set("Drive 一覧取得中…")

        def worker():
            try:
                q = f"(mimeType='{gas_workspace.MIME_SHEET}' or mimeType='{gas_workspace.MIME_DOC}') and trashed=false"
                files = self.mgr._drive_list(q, "files(id,name,mimeType,modifiedTime)")
                self.ui_queue.put(("targets", files, "", notify))
            except BaseException as e:
                self.ui_queue.put(("targets", [], str(e), notify))

        threading.Thread(target=worker, daemon=True).start()

    def _plan_current_ask(self, txt):
        """現在のターゲット情報を使って棚の事前判定を行う。"""
        st = self.mgr._load()
        tgt = st.get("target") or {}
        tc = self.mgr._cached_table(st, tgt) or st.get("table_cache") or {}
        kind = tgt.get("kind") or "sheet"
        cur_sh = tgt.get("sheet") or tc.get("sheet") or ""
        ls_info = st.get("last_scope") or {}
        ls = (
            ls_info.get("scope")
            if ls_info.get("id") == tgt.get("id")
            and (not cur_sh or not ls_info.get("sheet") or ls_info.get("sheet") == cur_sh)
            else None
        )
        return gas_ws_ask.plan(txt, self.mgr.finder, kind, tc.get("table"), tc.get("sheets"), cur_sheet=cur_sh, last_scope=ls)

    def _update_ask_preview(self):
        txt = self._get_ask()
        if not txt:
            self.preview_var.set("自動判定: 待機中")
            return
        p = self._plan_current_ask(txt)
        if p.fire:
            self.preview_var.set(f"棚ヒット: {_format_ops_short(p.ops)}")
        else:
            reason = "／".join(p.reasons) if p.reasons else ("不足: " + "、".join(p.missing) if p.missing else "棚に該当なし")
            suffix = "（実行時はAIが解釈して実行）" if self.ai_auto_var.get() else ""
            self.preview_var.set(f"未確定: {reason}{suffix}")

    # ------------------------------------------------------------ 非同期実行
    def _run_async(self, label, fn, switch_to_chat=True, status_text="実行中…"):
        if self.busy:
            self._append_box(self.chat_text, "⚠ 別の処理を実行中です。完了までお待ちください。")
            return
        self.busy = True
        self.status_var.set(status_text)
        if switch_to_chat:
            self.nb.select(self.tab_chat)

        def worker():
            t0 = time.perf_counter()
            try:
                out = fn()
                dt = time.perf_counter() - t0
                self.ui_queue.put(("ok", label, out, dt))
            except BaseException as e:
                dt = time.perf_counter() - t0
                self.ui_queue.put(("err", label, str(e), dt))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, label, text, dt = self.ui_queue.get_nowait()
                if kind == "browser_sync":
                    self._handle_browser_sync(label)
                    continue
                if kind == "prefetch_done":
                    self._prefetching = False
                    if text:
                        self._last_look_text = text
                        self._last_look_id = label or ""
                    self._refresh_from_state()
                    continue
                if kind == "targets":
                    if text:
                        if dt:
                            self.status_var.set("一覧取得エラー")
                            self._append_box(self.chat_text, f"[✗ Drive一覧取得]\n{text}")
                    else:
                        self.drive_files = label or []
                        self._rebuild_target_choices()
                        if dt and not self.busy:
                            self.status_var.set(f"一覧更新 ({len(self.drive_files)}件)")
                            self.target_combo.focus_set()
                    continue
                self.busy = False
                tab_text = self.nb.tab(self.nb.select(), "text")
                self.status_var.set(f"表示中: {tab_text}")
                timing_str = _format_exec_timing(self.mgr, dt)
                prefix = "✓" if kind == "ok" else "✗"
                self._append_box(self.chat_text, f"[{prefix}] {label}\n{text}\n({timing_str})")
                self._append_box(self.trace_text, f"[{prefix} {label}] {timing_str}")
                if kind == "err":
                    self.nb.select(self.tab_chat)
                self._refresh_from_state()
        except queue.Empty:
            pass
        except Exception as e:
            self.busy = False
            self.status_var.set("待機中")
            self._append_box(self.chat_text, f"[✗ 画面更新エラー]\n{e}")
        finally:
            self.root.after(100, self._poll_queue)

    def _poll_cmd(self):
        """合図ファイル（チャットや再起動からの呼び出し）を監視して表示・対象切替を行う。"""
        try:
            if CMD_FILE.exists():
                raw = CMD_FILE.read_text(encoding="utf-8")
                try:
                    CMD_FILE.unlink()
                except Exception:
                    pass
                cmd = json.loads(raw)
                self._handle_external_cmd(cmd)
        except Exception:
            pass
        finally:
            self.root.after(200, self._poll_cmd)

    def _handle_external_cmd(self, cmd):
        action = (cmd.get("action") or "show").lower()
        if action == "quit":
            self.on_quit_app()
            return
        if action == "hide":
            self.on_hide_window()
            return
        tgt = (cmd.get("target") or "").strip()
        sheet = (cmd.get("sheet") or "").strip()
        self._bring_to_front()
        if tgt and (tgt != self.target_var.get().strip() or sheet):
            self.target_var.set(tgt)
            self.on_look(sheet=sheet)
        elif sheet and sheet != self.sheet_var.get().strip():
            self.on_look(sheet=sheet)
        else:
            self._refresh_from_state()

    def _handle_browser_sync(self, data):
        """ブラウザ拡張から届いたファイル・シート・選択セル範囲をリアルタイム反映する。"""
        if not self.browser_sync_var.get() or not isinstance(data, dict):
            return
        fid = (data.get("id") or "").strip()
        if not fid:
            return
        kind = "doc" if data.get("kind") == "doc" else "sheet"
        name = (data.get("name") or "").strip()
        url = (data.get("url") or "").strip()
        sheet = (data.get("sheet") or "").strip()
        selection = (data.get("selection") or "").strip().upper()
        heading = (data.get("heading") or "").strip()

        self.browser_selection = selection
        self.browser_sheet = sheet
        self.browser_heading = heading

        st = self.mgr._load()
        cur = st.get("target") or {}
        cur_id = cur.get("id") or ""
        cur_sh = cur.get("sheet") or ""
        cur_name = cur.get("name") or ""

        target_changed = (fid != cur_id) or (kind == "sheet" and sheet and sheet != cur_sh)
        name_updated = bool(name and name != cur_name)

        new_tgt = {
            "id": fid,
            "name": name or (cur_name if fid == cur_id else fid),
            "kind": kind,
            "url": url or (cur.get("url") if fid == cur_id else ""),
        }
        if kind == "sheet":
            eff_sheet = sheet or (cur_sh if fid == cur_id else "")
            if eff_sheet:
                new_tgt["sheet"] = eff_sheet

        scope_dict = gas_ws_ask.parse_selection_scope(selection) if (kind == "sheet" and selection) else {}
        ls_prev = st.get("last_scope") or {}
        scope_changed = (
            ls_prev.get("id") != fid
            or ls_prev.get("sheet") != new_tgt.get("sheet", "")
            or ls_prev.get("selection") != selection
            or ls_prev.get("heading") != heading
        )

        if target_changed or name_updated or scope_changed:
            st["target"] = new_tgt
            if kind == "sheet" and selection and scope_dict:
                st["last_scope"] = {
                    "id": fid,
                    "sheet": new_tgt.get("sheet", ""),
                    "scope": scope_dict,
                    "selection": selection,
                }
            elif kind == "doc" and heading:
                st["last_scope"] = {
                    "id": fid,
                    "sheet": "",
                    "scope": {},
                    "heading": heading,
                }
            self.mgr._save(st)

        if target_changed or name_updated:
            self._refresh_from_state()
            # 対象ファイルまたはシートが切り替わり、表構造キャッシュがまだ無い場合は裏で静かに先読みする
            if kind == "sheet" and not self.busy and not self._prefetching:
                tc = self.mgr._cached_table(st, new_tgt)
                pf_key = (fid, new_tgt.get("sheet", ""))
                if tc is None and self._last_prefetch_key != pf_key:
                    self._prefetch_table_async(fid, new_tgt.get("sheet", ""))
        else:
            self._update_selection_label(st)
            self._update_ask_preview()

    def _prefetch_table_async(self, fid, sheet=""):
        """画面操作を止めずに裏で対象シートの表構造（見出し・列）を先読みキャッシュする。"""
        self._prefetching = True
        self._last_prefetch_key = (fid, sheet)

        def worker():
            try:
                out = self.mgr.look(target=fid, sheet=sheet)
                self.ui_queue.put(("prefetch_done", fid, out, 0.0))
            except Exception:
                self.ui_queue.put(("prefetch_done", fid, "", 0.0))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ ハンドラ
    def _push_history(self, txt):
        if not txt:
            return
        if not self.history or self.history[-1] != txt:
            self.history.append(txt)
            self.hist_list.insert(tk.END, txt)
            self.hist_list.see(tk.END)
        self.hist_idx = len(self.history)

    def on_return_key(self, event):
        if event.state & 0x0001:
            return None
        self.on_run_ask()
        return "break"

    def on_run_ask(self):
        txt = self._get_ask()
        if not txt:
            return
        self._push_history(txt)
        ok = bool(self.ok_var.get())
        p = self._plan_current_ask(txt)
        if self.busy:  # 実行中は受け付けないので、入力は消さない
            self._run_async(txt, lambda: None)
            return
        self._set_ask("")  # 実行を受け付けたら入力欄をクリア（履歴には残る）
        if p.fire or not self.ai_auto_var.get():
            self._run_async(txt, lambda: self.mgr.do(ask=txt, ok=ok))
            return

        def run_ai():
            self.mgr.last_timing = None
            out, used_look = self.ai.run_with_ai(
                self.mgr, txt, ok=ok, look_text=self._last_look_text, look_target_id=self._last_look_id
            )
            cur_id = ((self.mgr._load() or {}).get("target") or {}).get("id", "")
            if used_look:
                self._last_look_text = used_look
                self._last_look_id = cur_id
            return out

        self._run_async(txt, run_ai, status_text="AI解釈・実行中…")

    def on_run_ops(self, ops):
        ok = bool(self.ok_var.get())
        payload = json.dumps(ops, ensure_ascii=False)
        label = _format_ops_short(ops)
        self._run_async(label, lambda: self.mgr.do(ops=payload, ok=ok))

    def on_look(self, sheet=""):
        tgt = self.target_var.get().strip()
        self.mgr.last_timing = None

        def run_look():
            out = self.mgr.look(target=tgt, sheet=sheet)
            cur_id = ((self.mgr._load() or {}).get("target") or {}).get("id", "")
            self._last_look_text = out
            self._last_look_id = cur_id
            return out

        self._run_async("読込 (ws_look)", run_look, switch_to_chat=False)

    def on_undo(self):
        ok = bool(self.ok_var.get())
        self.mgr.last_timing = None
        self._run_async("直前を取り消す", lambda: self.mgr.undo(ok=ok))

    def on_auto_width(self):
        st = self.mgr._load()
        tgt = st.get("target") or {}
        ls_info = st.get("last_scope") or {}
        scope = ls_info.get("scope") or {}
        # ブラウザで列選択または複数列範囲を選んでいる場合は、その選択列の幅を自動調整する
        if ls_info.get("id") == tgt.get("id") and scope.get("cols") and (
            scope.get("col_select") or len(scope.get("cols") or []) > 1
        ):
            self.on_run_ops([{"shelf": "width", "auto": scope["cols"]}])
            return
        tb = (st.get("table_cache") or {}).get("table") or {}
        cols = [c["col"] for c in tb.get("columns") or []]
        if cols:
            self.on_run_ops([{"shelf": "width", "auto": cols}])
        else:
            self._run_async("列幅自動", lambda: self.mgr.do(ask="全ての列の幅を中身に合わせて"))

    def on_freeze_header(self):
        st = self.mgr._load()
        tb = (st.get("table_cache") or {}).get("table") or {}
        hr = tb.get("header_row") or 1
        self.on_run_ops([{"shelf": "freeze", "rows": hr}])

    def on_find_shelf(self):
        txt = self._get_ask()
        res = self.mgr.find(ask=txt)
        self.nb.select(self.tab_chat)
        self._append_box(self.chat_text, f"[棚検索: {txt or '一覧'}]\n{res}")

    def on_select_target_choice(self, _e=None):
        disp = self.target_choice_var.get()
        fid = self._choice_map.get(disp)
        cur_id = ((self.mgr._load() or {}).get("target") or {}).get("id")
        if fid and fid != cur_id:
            self.target_var.set(fid)
            self.on_look()

    def on_paste_target(self):
        try:
            clip = self.root.clipboard_get().strip()
        except Exception:
            clip = ""
        if not clip:
            self.status_var.set("クリップボードが空です")
            return
        self.target_var.set(clip)
        self.on_look()

    def on_open_browser(self):
        url = self.target_var.get().strip() or (self.mgr._load().get("target") or {}).get("url", "")
        if url.startswith("http"):
            webbrowser.open(url)

    def on_toggle_topmost(self):
        self.root.attributes("-topmost", not bool(self.untopmost_var.get()))

    def on_toggle_browser_sync(self):
        self._update_selection_label()
        self._update_ask_preview()

    def on_open_ext_folder(self):
        ext_path = str(BROWSER_EXT_DIR)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(ext_path)
        except Exception:
            pass
        if os.name == "nt" and BROWSER_EXT_DIR.exists():
            try:
                subprocess.Popen(["explorer", f"/select,{ext_path}"])
            except Exception:
                pass
        guide = (
            f"[ブラウザ連動拡張の導入手順]\n"
            f"フォルダのパスをコピー済みです:\n{ext_path}\n\n"
            f"1. Chrome のアドレスバーに chrome://extensions と入れて開く\n"
            f"2. 右上の「デベロッパー モード」を ON にする\n"
            f"3. 左上の「パッケージ化されていない拡張機能を読み込む」を押し、\n"
            f"   フォルダ選択欄に Ctrl+V で貼り付けて「フォルダーの選択」を押す\n"
            f"   （または開いたエクスプローラーの ws_browser_ext フォルダを Chrome 画面へドラッグ＆ドロップ）"
        )
        self.nb.select(self.tab_chat)
        self._append_box(self.chat_text, guide)

    def on_toggle_backup(self):
        self.on_run_ops([{"shelf": "backup", "on": bool(self.backup_var.get())}],)

    def on_copy_for_ai(self):
        txt = self._get_ask()
        st = self.mgr._load()
        url = (st.get("target") or {}).get("url") or self.target_var.get().strip()
        sh = self.sheet_var.get().strip()
        sel = ((st.get("last_scope") or {}).get("selection") or self.browser_selection or "").strip()
        sel_part = f"・選択: {sel}" if sel else ""
        msg = f"対象: {url}（シート: {sh}{sel_part}）\n依頼: {txt}" if url else txt
        self.root.clipboard_clear()
        self.root.clipboard_append(msg)
        self._append_box(self.chat_text, f"チャット貼り付け用にコピーしました:\n{msg}")

    def on_clear_input(self):
        self._set_ask("")
        self.ask_text.focus_set()

    def on_clear_log(self):
        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        self.chat_text.configure(state=tk.DISABLED)

    def on_new_talk(self):
        self.on_clear_input()
        self.on_clear_log()
        self.ai.reset()
        self.nb.select(self.tab_auto)

    def on_hide_window(self):
        self.root.withdraw()

    def on_quit_app(self):
        self.ai.close()
        self.root.destroy()

    def on_use_hist(self):
        sel = self.hist_list.curselection()
        if sel:
            self._set_ask(self.hist_list.get(sel[0]))
            self.ask_text.focus_set()

    def on_rerun_hist(self):
        sel = self.hist_list.curselection()
        if sel:
            self._set_ask(self.hist_list.get(sel[0]))
            self.on_run_ask()

    def on_hist_up(self, _e):
        if self.ask_text.index(tk.INSERT).split(".")[0] != "1":
            return None
        if not self.history:
            return "break"
        self.hist_idx = max(0, self.hist_idx - 1)
        self._set_ask(self.history[self.hist_idx])
        return "break"

    def on_hist_down(self, _e):
        last_line = self.ask_text.index("end-1c").split(".")[0]
        if self.ask_text.index(tk.INSERT).split(".")[0] != last_line:
            return None
        if not self.history:
            return "break"
        self.hist_idx = min(len(self.history), self.hist_idx + 1)
        self._set_ask("" if self.hist_idx == len(self.history) else self.history[self.hist_idx])
        return "break"

    def _bring_to_front(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", not bool(self.untopmost_var.get()))
            self.root.focus_force()
            self.ask_text.focus_set()
        except Exception:
            pass


def _enable_dpi_awareness():
    """Windows の高 DPI スケーリングを有効化する。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="GASコンボ 操作窓")
    parser.add_argument("--target", default="", help="初期読み込みするURL・ID・名前")
    parser.add_argument("--sheet", default="", help="初期シート名")
    parser.add_argument("--hidden", action="store_true", help="非表示の常駐待機状態で起動する")
    parser.add_argument("--send", default="", help="常駐中の窓へ合図を送る (show/hide/quit)")
    args = parser.parse_args()

    if args.send:
        send_window_cmd(action=args.send, target=args.target, sheet=args.sheet)
        return

    _mutex, already = _acquire_single_instance_mutex()
    cur_sig = _code_signature()
    if already:
        running_sig = VER_FILE.read_text(encoding="utf-8").strip() if VER_FILE.exists() else ""
        if running_sig != cur_sig:
            _close_mutex(_mutex)
            send_window_cmd(action="quit")
            deadline = time.time() + 2.5
            while time.time() < deadline:
                time.sleep(0.1)
                _mutex, already = _acquire_single_instance_mutex()
                if not already:
                    break
                _close_mutex(_mutex)
        if already:
            send_window_cmd(action="show", target=args.target, sheet=args.sheet)
            return

    try:
        VER_FILE.write_text(cur_sig, encoding="utf-8")
    except Exception:
        pass
    _enable_dpi_awareness()
    root = tk.Tk()
    GasComboWindow(root, initial_target=args.target, initial_sheet=args.sheet, start_hidden=args.hidden)
    root.mainloop()


if __name__ == "__main__":
    main()
