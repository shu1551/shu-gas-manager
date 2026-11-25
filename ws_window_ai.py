# -*- coding: utf-8 -*-
"""GASコンボ用・直結AIプランナー（ヘッドレス Claude Code 常駐セッション）。"""

import atexit
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import queue

import gas_workspace
import gas_ws_find

DEFAULT_MODEL = "haiku"
AI_TIMEOUT = 60
_CC_ARGS = [
    "-p",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--verbose",
    "--tools", "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--setting-sources", "user",
    "--no-session-persistence",
    "--effort", "low",
    "--settings", '{"alwaysThinkingEnabled":false}',
]

SYSTEM_PROMPT = (
    "あなたは Google スプレッドシートおよび Google ドキュメントを操作するアシスタントです。\n"
    "必ず有効な JSON オブジェクト 1 個だけを返してください（説明文や ``` などの装飾は一切付けない）。\n"
    "・操作を実行するとき: "
    '{"action":"ops","ops":[{"shelf":"棚名","引数":値}],"note":"何をするかの短い日本語要約"}\n'
    "・削除範囲が曖昧・情報不足・単なる質問でユーザーへ返事や確認だけを返すとき: "
    '{"action":"reply","message":"日本語の返事"}\n'
    "ルール:\n"
    "1. 棚名・引数名は、必ずユーザーメッセージ内の「利用可能な棚一覧」に載っている正確な名前と型を使うこと。\n"
    "2. 複数の変更（見出し設定＋記号除去＋書式整理など）は 1 つの ops 配列にまとめて返すこと。\n"
    "3. 文書で Markdown の見出し記号(## 等)を本物の見出しにしつつ記号を消すときは、"
    "先に記号付きの文字列で doc.heading を設定してから、後で doc.replace（### を先に、## を後）で記号を消すこと。\n"
)


def _neutral_cwd():
    """CLAUDE.md や記憶を読ませない中立の作業フォルダを返す。"""
    if os.name == "nt" and os.path.isdir(r"C:\tmp"):
        return r"C:\tmp"
    return tempfile.gettempdir()


def _strip_json_fence(text):
    """コードフェンス等を取り除いて JSON 部分を抜き出す。"""
    t = (text or "").strip()
    m = re.match(r"^```[\w-]*[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\s*$", t, re.S)
    if m:
        t = m.group(1).strip()
    if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
        return t
    m2 = re.search(r"(\{.*\}|\[.*\])", t, re.S)
    return m2.group(0) if m2 else t


def _parse_ai_json(text):
    """AI 応答から辞書を復元し、ops/actions/配列ゆれを吸収して正規化する。"""
    raw = _strip_json_fence(text)
    data = json.loads(raw)
    if isinstance(data, list):
        return {"action": "ops", "ops": data, "note": ""}
    if not isinstance(data, dict):
        raise ValueError("AI の返答が JSON オブジェクトではありません")
    if "shelf" in data and "ops" not in data:
        return {"action": "ops", "ops": [data], "note": ""}
    if "ops" not in data:
        for alt in ("actions", "commands", "operations", "steps"):
            if isinstance(data.get(alt), list):
                data["ops"] = data[alt]
                data.setdefault("action", "ops")
                break
    return data


class _HeadlessClaudeSession:
    """claude -p (stream-json) を 1 会話 1 プロセスで温めて使うセッション。
    コンテキスト肥大と 5 時間枠の浪費を防ぐため、一定ターン数または長時間アイドルで自動リフレッシュする。"""

    MAX_TURNS = 10
    IDLE_TTL_SEC = 1800

    def __init__(self, model=DEFAULT_MODEL):
        self.model = model
        self.proc = None
        self.lines = None
        self.err = []
        self.target_id = None
        self.turns = 0
        self.last_used_at = 0.0
        self.lock = threading.Lock()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _needs_refresh(self):
        if not self.alive():
            return False
        if self.turns >= self.MAX_TURNS:
            return True
        if self.last_used_at > 0 and (time.monotonic() - self.last_used_at) >= self.IDLE_TTL_SEC:
            return True
        return False

    def start(self):
        if self.alive():
            return
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("claude コマンドが見つかりません（Claude Code をインストールしてログインしてください）。")
        cmd = [exe] + _CC_ARGS + ["--model", self.model, "--system-prompt", SYSTEM_PROMPT]
        kwargs = {
            "cwd": _neutral_cwd(),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self.err = []
        self.lines = queue.Queue()
        self.turns = 0
        self.last_used_at = time.monotonic()
        self.proc = subprocess.Popen(cmd, **kwargs)
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, None), daemon=True).start()

    def _pump(self, stream, q):
        try:
            for raw in iter(stream.readline, b""):
                if q is None:
                    self.err.append(raw.decode("utf-8", "replace"))
                else:
                    q.put(raw)
        finally:
            if q is not None:
                q.put(None)

    def ask(self, prompt, timeout=AI_TIMEOUT):
        with self.lock:
            if self._needs_refresh():
                self.close()
            if not self.alive():
                self.start()
            try:
                res = self._send_and_wait(prompt, timeout)
                self.turns += 1
                self.last_used_at = time.monotonic()
                return res
            except Exception:
                # 常駐プロセスが途中で切れていた場合のみ 1 回やり直す
                if not self.alive():
                    self.close()
                    self.start()
                    res = self._send_and_wait(prompt, timeout)
                    self.turns += 1
                    self.last_used_at = time.monotonic()
                    return res
                raise

    def _send_and_wait(self, prompt, timeout):
        line = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}, ensure_ascii=True)
        self.proc.stdin.write((line + "\n").encode("ascii"))
        self.proc.stdin.flush()

        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                self.close()
                raise TimeoutError(f"AI が {timeout} 秒以内に応答しませんでした。")
            try:
                raw = self.lines.get(timeout=left)
            except queue.Empty:
                self.close()
                raise TimeoutError(f"AI が {timeout} 秒以内に応答しませんでした。")
            if raw is None:
                tail = "".join(self.err)[-400:].strip()
                self.close()
                raise RuntimeError("AI プロセスが終了しました" + (f": {tail}" if tail else ""))
            try:
                d = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if d.get("type") == "result":
                if d.get("is_error"):
                    raise RuntimeError("AI エラー: " + str(d.get("result") or d.get("subtype") or "")[:300])
                return str(d.get("result") or "")

    def close(self):
        p, self.proc = self.proc, None
        self.target_id = None
        self.turns = 0
        self.last_used_at = 0.0
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                )
            else:
                try:
                    p.kill()
                except Exception:
                    pass


def _build_catalog_context(mgr, ask, kind):
    """現在の対象種別（doc / sheet）で使える全棚を、関連詳細＋主要引数＋全件圧縮インデックスで組む。"""
    priority = (
        "seiri", "tidy", "format", "write", "replace", "total", "formula.col", "sort",
        "filter.on", "filter.where", "filter.off", "width", "freeze", "unfreeze",
        "dedupe", "banding.add", "banding.remove", "chart.new", "rows.delete", "rows.insert",
        "cols.delete", "sheet.add", "sheet.rename", "sheet.copy", "table.new", "validation.list",
    )
    return gas_ws_find.build_ai_shelf_prompt(
        mgr.finder,
        ask,
        kind=kind,
        detail_limit=1600,
        top_args=25,
        priority_names=priority if kind != "doc" else None,
    )


class GasAiRunner:
    """GASコンボ窓から直接 AI で ops を組み立てて WorkspaceManager.do を実行する。"""

    def __init__(self, model=DEFAULT_MODEL):
        self.model = model
        self.session = _HeadlessClaudeSession(model=model)
        atexit.register(self.close)

    def set_model(self, model):
        if model and model != self.model:
            self.model = model
            self.session.close()
            self.session = _HeadlessClaudeSession(model=model)

    def prewarm(self):
        """入力中に裏で claude プロセスを立ち上げて待機時間を削る。"""
        try:
            if shutil.which("claude"):
                self.session.start()
        except Exception:
            pass

    def reset(self):
        self.session.close()

    def close(self):
        self.session.close()

    def run_with_ai(self, mgr, ask, ok=False, look_text="", look_target_id=""):
        """棚に一発で当たらない依頼を AI に解釈させ、検証後に mgr.do で実行する。"""
        st = mgr._load()
        tgt = st.get("target") or {}
        if not tgt.get("id"):
            raise gas_workspace.WorkspaceError("操作対象が選ばれていません。上部の一覧や「貼付切替」でファイルを選択してください。")
        kind = tgt.get("kind") or "sheet"
        cur_id = tgt.get("id")

        if self.session.target_id and self.session.target_id != cur_id:
            self.session.close()
        self.session.target_id = cur_id

        # 対象の中身情報が手元に無ければ 1 回だけ look で取得する
        if not look_text or look_target_id != cur_id:
            look_text = mgr.look()

        ls_info = st.get("last_scope") or {}
        sel_ctx = ""
        if ls_info.get("id") == cur_id:
            sel_str = ls_info.get("selection") or ""
            hd_str = ls_info.get("heading") or ""
            sh_str = ls_info.get("sheet") or tgt.get("sheet") or ""
            if sel_str and kind == "sheet":
                sel_ctx = (
                    f"【ブラウザで現在選択中のセル範囲】\n"
                    f"シート「{sh_str or '先頭シート'}」の {sel_str} を選択中です。"
                    f"依頼文で場所が省略されている場合や「ここ」「選択範囲」「この行」「この列」と言われた場合は {sel_str} を対象にしてください。\n\n"
                )
            elif hd_str and kind == "doc":
                sel_ctx = (
                    f"【ブラウザで現在表示中の見出し】\n"
                    f"見出し「{hd_str}」付近を表示中です。「ここ」「この章」と言われた場合は under=\"{hd_str}\" または heading=\"{hd_str}\" を優先してください。\n\n"
                )

        cat_ctx = _build_catalog_context(mgr, ask, kind)
        prompt = (
            f"【現在の対象状態】\n{look_text[:3500]}\n\n"
            f"{sel_ctx}"
            f"{cat_ctx}\n\n"
            f"【ユーザーの依頼】\n{ask}\n\n"
            '必ず {"action":"ops","ops":[{"shelf":"...",...}],"note":"短い要約"} '
            'または {"action":"reply","message":"..."} の JSON 1個だけを返してください。'
        )

        raw = self.session.ask(prompt)
        parsed = _parse_ai_json(raw)

        # 返答のみ（確認や質問）の場合
        if parsed.get("action") == "reply":
            return f"[AI返答]\n{parsed.get('message') or '(返答なし)'}", look_text

        ops = parsed.get("ops")
        note = (parsed.get("note") or "").strip()
        if not isinstance(ops, list) or not ops:
            raise ValueError("AI が実行可能な ops を返しませんでした。")

        # 引数・棚名エラーが出た場合は同じウォームセッションで 1 回だけ自動修復を試みる
        try:
            mgr.validate_ops(ops)
        except Exception as e:
            fix_prompt = (
                f"次のエラーが発生しました:\n{e}\n\n"
                "正しい棚名・引数名に直した JSON（action='ops' または 'reply'）だけをもう一度返してください。"
            )
            raw2 = self.session.ask(fix_prompt)
            parsed2 = _parse_ai_json(raw2)
            if parsed2.get("action") == "reply":
                return f"[AI返答]\n{parsed2.get('message') or ''}", look_text
            ops = parsed2.get("ops")
            note = (parsed2.get("note") or note).strip()
            mgr.validate_ops(ops)

        payload = json.dumps(ops, ensure_ascii=False)
        out = mgr.do(ops=payload, ok=ok)
        head = f"[AI解釈] {note}\n" if note else "[AI解釈]\n"
        return head + out, look_text
