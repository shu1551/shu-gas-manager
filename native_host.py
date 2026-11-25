# -*- coding: utf-8 -*-
"""Chrome 拡張 (GASコンボ ブラウザ連動) 用 Native Messaging Host。

ローカル AI 受け手 (127.0.0.1:18766) が止まっていたときに、Chrome 拡張からの
呼び出しを受けて裏で自動起動し、起動完了を確認してから応答を返す。
"""
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMBO_WATCH_PORT = 18766
PING_URL = f"http://127.0.0.1:{COMBO_WATCH_PORT}/ping"


def _read_message():
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len <= 0 or msg_len > 1024 * 1024:
        return None
    raw = sys.stdin.buffer.read(msg_len)
    return json.loads(raw.decode("utf-8"))


def _send_message(obj):
    encoded = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _ping_watcher(timeout=0.5):
    try:
        with urllib.request.urlopen(PING_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore") or "{}")
            if isinstance(data, dict) and data.get("ok"):
                return data
    except Exception:
        pass
    return None


def _resolve_default_sid():
    state_file = HERE / ".combo_engine_state.json"
    try:
        if state_file.exists():
            st = json.loads(state_file.read_text(encoding="utf-8"))
            sid = str(st.get("addon_sid") or "").strip()
            if sid:
                return sid
    except Exception:
        pass
    return "DIRECT"


def _launch_detached_windows(exe, gas_py, sid):
    """Windows で親の Job Object (Chrome Native Messaging 等) 終了に道連れにされないよう独立起動する。"""
    # 1. WMI Win32_Process.Create 経由: WmiPrvSE.exe を親にして起動するため Job Object から完全に独立する
    try:
        cmd_str = f'"{exe}" "{gas_py}" combo watch {sid}'
        ps_cmd = (
            "Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{CommandLine='{cmd_str.replace(chr(39), chr(39)*2)}'; "
            f"CurrentDirectory='{str(HERE).replace(chr(39), chr(39)*2)}'}} | Out-Null"
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            cwd=str(HERE),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if r.returncode == 0:
            return True, None
    except Exception:
        pass
    # 2. フォールバック: CREATE_BREAKAWAY_FROM_JOB → 通常の DETACHED_PROCESS
    base_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x8)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    last_err = None
    for flags in (base_flags | breakaway, base_flags):
        try:
            subprocess.Popen(
                [exe, gas_py, "combo", "watch", sid],
                cwd=str(HERE),
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return True, None
        except Exception as e:
            last_err = e
    return False, last_err


def _ensure_watch(wait_sec=6.0):
    alive = _ping_watcher(timeout=0.5)
    if alive:
        return {"ok": True, "started": False, "pid": alive.get("pid")}

    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else sys.executable)
    gas_py = str(HERE / "gas.py")
    sid = _resolve_default_sid()
    if os.name == "nt":
        launched, last_err = _launch_detached_windows(exe, gas_py, sid)
    else:
        try:
            subprocess.Popen(
                [exe, gas_py, "combo", "watch", sid],
                cwd=str(HERE),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            launched, last_err = True, None
        except Exception as e:
            launched, last_err = False, e
    if not launched:
        return {"ok": False, "started": False, "error": f"受け手の起動に失敗しました: {last_err}"}

    deadline = time.monotonic() + float(wait_sec)
    while time.monotonic() < deadline:
        time.sleep(0.15)
        alive = _ping_watcher(timeout=0.5)
        if alive:
            return {"ok": True, "started": True, "pid": alive.get("pid")}
    return {"ok": False, "started": False, "error": "受け手を起動しましたが 127.0.0.1:18766 が応答しませんでした（.combo_watch.log を確認してください）"}


def main():
    try:
        msg = _read_message()
        if not isinstance(msg, dict):
            _send_message({"ok": False, "error": "invalid_message"})
            return 0
        action = str(msg.get("action") or "ensure_watch")
        if action == "ping":
            alive = _ping_watcher(timeout=0.5)
            _send_message({"ok": bool(alive), "pid": alive.get("pid") if alive else None})
            return 0
        if action == "ensure_watch":
            _send_message(_ensure_watch())
            return 0
        _send_message({"ok": False, "error": f"unknown_action: {action}"})
        return 0
    except Exception as e:
        try:
            _send_message({"ok": False, "error": str(e)})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
