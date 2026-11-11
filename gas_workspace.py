# -*- coding: utf-8 -*-
"""
gas_workspace.py - Workspace マネージャー（スプレッドシートとドキュメントを会話で作る・直す）

通り道は 1 本：専用の GAS エンジン（shu-workspace-engine, workspace_engine.gs）の /dev に
本人のトークンで POST する。型（棚）はエンジンが持ち、ここは
  ・今の相手（.ws_state.json）を覚える　・ファイルを名前で探す（Drive 一覧）
  ・ops（棚の名前と引数の JSON）を撃つ前に検査する　・呼び直しで二重にならない番号　・報告を 3〜5 行に組む
だけを受け持つ。書く前の控え・失敗時の戻し・undo・指紋はエンジン側。
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_SOURCE = HERE / "workspace_engine.gs"
ENGINE_TITLE = "shu-workspace-engine"
RETRY_MAX = 3

MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_DOC = "application/vnd.google-apps.document"

# 棚: kind = sheet|doc / req = 必須 / any = どれか 1 つ必須 / keys = 使える引数
SHELVES = {
    "table.new":   dict(kind="sheet", req=["headers"], keys=["title", "headers", "rows", "sheet", "number", "total", "label", "tidy"]),
    "sheet.add":   dict(kind="sheet", any=["name", "rename", "move"], keys=["name", "before", "rename", "move"]),
    "tidy":        dict(kind="sheet", keys=["sheet", "range"]),
    "seiri":       dict(kind="sheet", keys=["sheet", "trim", "halfwidth", "numbers", "blank_rows", "dedupe", "renumber", "tidy"]),
    "renumber":    dict(kind="sheet", req=["col"], keys=["sheet", "col", "start"]),
    "width":       dict(kind="sheet", any=["cols", "col", "rows", "auto"], keys=["sheet", "cols", "col", "width", "rows", "auto"]),
    "total":       dict(kind="sheet", keys=["sheet", "cols", "label"]),
    "summary":     dict(kind="sheet", req=["by", "values"], keys=["sheet", "by", "values", "func", "into"]),
    "sort":        dict(kind="sheet", any=["col", "filter", "where"], keys=["sheet", "col", "desc", "filter", "where"]),
    "write":       dict(kind="sheet", any=["cells", "tsv"], keys=["sheet", "cells", "range", "tsv"]),
    "format":      dict(kind="sheet", any=["range", "col", "header"], keys=["sheet", "range", "col", "header", "bold", "italic", "color", "bg", "size", "font", "number_format", "align", "valign", "wrap", "borders", "merge"]),
    "rows":        dict(kind="sheet", any=["rows", "cols"], keys=["sheet", "action", "rows", "cols", "at", "count", "from", "to"]),
    "replace":     dict(kind="sheet", req=["find"], keys=["sheet", "find", "with", "range", "match_case", "whole"]),
    "doc.new":     dict(kind="doc", req=["markdown"], keys=["markdown"]),
    "doc.append":  dict(kind="doc", req=["markdown"], keys=["markdown", "under"]),
    "doc.replace": dict(kind="doc", req=["find"], keys=["find", "with", "match_case"]),
    "doc.section": dict(kind="doc", req=["heading"], keys=["heading", "action", "markdown"]),
    "doc.table":   dict(kind="doc", any=["rows", "text"], keys=["action", "rows", "under", "table", "row", "col", "text"]),
    "doc.style":   dict(kind="doc", keys=["font", "size", "line_spacing"]),
}


class WorkspaceError(Exception):
    """利用者（AI）に日本語でそのまま返す種類のエラー"""


class WorkspaceAuthNeeded(WorkspaceError):
    pass


class WorkspaceTimeout(WorkspaceError):
    pass


def _file_hash(path=ENGINE_SOURCE):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:8]


def _digest(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


class WorkspaceManager:
    def __init__(self, client=None, state_path=None, engine_path=None):
        self._client = client
        self.state_path = Path(state_path) if state_path else HERE / ".ws_state.json"
        self.engine_path = Path(engine_path) if engine_path else ENGINE_SOURCE

    # ------------------------------------------------------------ 状態
    @property
    def client(self):
        if self._client is None:
            from gas_client import GasClient
            self._client = GasClient()
        return self._client

    def _load(self):
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def _save(self, st):
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    # ------------------------------------------------------------ エンジン
    def engine_version(self):
        text = self.engine_path.read_text(encoding="utf-8")
        m = re.search(r"var ENGINE_VERSION = '([^']*)'", text)
        return f"{m.group(1) if m else 'ws'}+{_file_hash(self.engine_path)}"

    def _engine_files(self):
        text = self.engine_path.read_text(encoding="utf-8")
        text = re.sub(r"var ENGINE_VERSION = '[^']*';", f"var ENGINE_VERSION = '{self.engine_version()}';", text, count=1)
        manifest = {
            "timeZone": "Asia/Tokyo", "dependencies": {}, "exceptionLogging": "STACKDRIVER", "runtimeVersion": "V8",
            "oauthScopes": ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/documents"],
            "webapp": {"executeAs": "USER_DEPLOYING", "access": "MYSELF"},
        }
        return [{"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, indent=2)},
                {"name": "Engine", "type": "SERVER_JS", "source": text}]

    def _find_engine_sid(self):
        q = f"mimeType='application/vnd.google-apps.script' and name='{ENGINE_TITLE}' and trashed=false"
        files = self._drive_list(q, "files(id,name)")
        return files[0]["id"] if files else None

    def install_engine(self, st=None):
        """エンジンの置き場所を決め、リポジトリの版を差し替える（無ければ作る）"""
        st = st if st is not None else self._load()
        sid = st.get("engine_sid") or self._find_engine_sid()
        created = False
        if not sid:
            sid = self.client.create_project(ENGINE_TITLE)["scriptId"]
            created = True
        self.client._put_content(sid, self._engine_files())
        if created or not st.get("engine_url"):
            if created:
                self.client.deploy(sid, description="shu-workspace-engine setup")
            url = self.client.resolve_webapp_url(sid, refresh=True, dev=True)
            st["engine_url"] = re.sub(r"/(exec|dev)$", "/dev", url)
        st["engine_sid"] = sid
        st["engine_ver"] = self.engine_version()
        self._save(st)
        return st

    def _ensure_engine(self):
        st = self._load()
        if not st.get("engine_sid") or not st.get("engine_url") or st.get("engine_ver") != self.engine_version():
            st = self.install_engine(st)
        return st

    def _post(self, body, timeout=90):
        st = self._ensure_engine()
        url = st["engine_url"]
        try:
            r = self.client.call_webapp(url, body=body, method="POST", use_auth=True, timeout=timeout)
        except TimeoutError as e:
            raise WorkspaceTimeout(str(e))
        data = r.get("data")
        if isinstance(data, dict):
            ver = data.get("version")
            if ver and ver != self.engine_version() and not body.get("_retried"):
                # 版が違う（誰かがエンジンを書き換えた）→ 差し替えて 1 回だけ撃ち直す
                self.install_engine(self._load())
                return self._post(dict(body, _retried=True), timeout)
            return data
        text = (r.get("text") or "")
        if "Authorization needed" in text or "承認が必要" in text or "authorization" in text.lower()[:600]:
            raise WorkspaceAuthNeeded(self._auth_message(url))
        if r.get("status_code") in (500, 502, 503, 504) or "Exceeded maximum execution time" in text or "最大実行時間" in text:
            raise WorkspaceTimeout(f"エンジンが応答しませんでした（HTTP {r.get('status_code')}）")
        raise WorkspaceError("エンジンの返事が読めません: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:200])

    @staticmethod
    def _auth_message(url):
        return ("エンジンの許可がまだです（最初の 1 回だけ、ブラウザで押す必要があります）。\n"
                f"1. このURLを開く: {url}\n"
                "2. 「権限を確認」→ アカウントを選び、「詳細」→「（安全ではないページ）に移動」→「許可」を押す\n"
                "3. 押したら、もう一度頼んでください。")

    # ------------------------------------------------------------ Drive（名前で探す）
    def _drive_list(self, q, fields):
        r = self.client._request_with_retry(
            "GET", "https://www.googleapis.com/drive/v3/files", headers=self.client._headers(),
            params={"q": q, "fields": fields, "pageSize": 20, "orderBy": "modifiedTime desc"}, timeout=15)
        if r.status_code != 200:
            raise WorkspaceError(f"Drive の一覧に失敗しました（{r.status_code}）")
        return r.json().get("files", [])

    def _drive_meta(self, fid):
        r = self.client._request_with_retry(
            "GET", f"https://www.googleapis.com/drive/v3/files/{fid}", headers=self.client._headers(),
            params={"fields": "id,name,mimeType,trashed"}, timeout=15)
        if r.status_code == 404:
            raise WorkspaceError(f"ファイル {fid} が見つかりません（または、このアカウントでは開けません）")
        if r.status_code != 200:
            raise WorkspaceError(f"ファイル情報の取得に失敗しました（{r.status_code}）")
        return r.json()

    @staticmethod
    def _kind_of_mime(m):
        return "sheet" if m == MIME_SHEET else "doc" if m == MIME_DOC else None

    def _search_name(self, name, want_kind=None):
        esc = name.replace("\\", "\\\\").replace("'", "\\'")
        mimes = [MIME_SHEET, MIME_DOC] if not want_kind else [MIME_SHEET if want_kind == "sheet" else MIME_DOC]
        mq = " or ".join(f"mimeType='{m}'" for m in mimes)
        exact = self._drive_list(f"name='{esc}' and ({mq}) and trashed=false", "files(id,name,mimeType,modifiedTime,webViewLink)")
        found = exact or self._drive_list(f"name contains '{esc}' and ({mq}) and trashed=false", "files(id,name,mimeType,modifiedTime,webViewLink)")
        if not found:
            raise WorkspaceError(f"「{name}」という名前のスプレッドシート・文書が見つかりません。")
        if len(found) > 1:
            lines = [f"「{name}」に当たるファイルが {len(found)} 件あります。どれか決めてください（URL か ID を target に）："]
            for f in found[:6]:
                lines.append(f"  - {f['name']}（{self._kind_label(f['mimeType'])}・最終更新 {f.get('modifiedTime', '')[:16].replace('T', ' ')}）{f.get('webViewLink', '')}")
            raise WorkspaceError("\n".join(lines))
        f = found[0]
        return {"id": f["id"], "name": f["name"], "kind": self._kind_of_mime(f["mimeType"])}

    @staticmethod
    def _kind_label(m):
        return "スプレッドシート" if m == MIME_SHEET else "文書" if m == MIME_DOC else "その他"

    # ------------------------------------------------------------ ops の検査
    @staticmethod
    def parse_ops(ops):
        if isinstance(ops, str):
            try:
                ops = json.loads(ops)
            except Exception as e:
                raise WorkspaceError(f"ops が JSON として読めません: {e}")
        if isinstance(ops, dict):
            ops = [ops]
        if not isinstance(ops, list) or not ops:
            raise WorkspaceError("ops は棚の JSON 配列です。例: [{\"shelf\":\"tidy\"}]。棚の一覧: " + "、".join(SHELVES))
        return ops

    def validate_ops(self, ops):
        kinds = set()
        for i, op in enumerate(ops, 1):
            if not isinstance(op, dict) or not isinstance(op.get("shelf"), str):
                raise WorkspaceError(f"{i} 番目の ops に \"shelf\"（棚の名前）がありません。棚の一覧: " + "、".join(SHELVES))
            name = op["shelf"]
            spec = SHELVES.get(name)
            if not spec:
                raise WorkspaceError(f"棚「{name}」はありません（{i} 番目）。あるのは: " + "、".join(SHELVES))
            for k in op:
                if k != "shelf" and k not in spec["keys"]:
                    raise WorkspaceError(f"棚「{name}」（{i} 番目）に引数「{k}」はありません。使えるのは: " + "、".join(spec["keys"]))
            for k in spec.get("req", []):
                if op.get(k) in (None, "", []):
                    raise WorkspaceError(f"棚「{name}」（{i} 番目）に「{k}」が要ります。")
            if spec.get("any") and not any(op.get(k) not in (None, "", []) for k in spec["any"]):
                raise WorkspaceError(f"棚「{name}」（{i} 番目）に " + "・".join(spec["any"]) + " のどれかが要ります。")
            if name == "table.new":
                if not isinstance(op["headers"], list):
                    raise WorkspaceError(f"棚「table.new」の headers は配列です（{i} 番目）。")
                rows = op.get("rows", [])
                if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
                    raise WorkspaceError(f"棚「table.new」の rows は行の配列の配列です（{i} 番目）。")
            if name == "rows" and op.get("action", "delete") not in ("insert", "delete", "move"):
                raise WorkspaceError("棚「rows」の action は insert・delete・move です。")
            if name == "rows" and not op.get("rows") and not op.get("cols") and op.get("action") != "insert":
                raise WorkspaceError("棚「rows」に rows（行番号の配列）か cols が要ります。")
            if name == "rows":
                for r in (op.get("rows") or []):
                    if isinstance(r, int) and r < 1:
                        raise WorkspaceError(f"棚「rows」の行番号は 1 以上です（{r} は指定できません）。")
            if name == "doc.section" and op.get("action", "replace") not in ("replace", "delete"):
                raise WorkspaceError("棚「doc.section」の action は replace・delete です。")
            if name == "doc.section" and op.get("action", "replace") == "replace" and not op.get("markdown"):
                raise WorkspaceError("棚「doc.section」の replace には markdown が要ります。")
            kinds.add(spec["kind"])
        if len(kinds) > 1:
            raise WorkspaceError("スプレッドシートの棚と文書の棚は、同じ ws_do にまとめられません。")
        return kinds.pop()

    # ------------------------------------------------------------ 相手を決める
    def resolve_target(self, target, kind, st):
        target = (target or "").strip()
        cur = st.get("target") or {}
        if not target:
            if not cur.get("id"):
                raise WorkspaceError("今の相手が決まっていません。target に URL・ID・名前、または \"new:名前\"（新規）を渡してください。")
            return dict(cur), False
        if target.lower().startswith("new:"):
            name = target[4:].strip()
            if not name:
                raise WorkspaceError("new: のあとに新しいファイルの名前が要ります（例: new:見積書）。")
            return {"new": name, "kind": kind}, True
        m = re.search(r"/(spreadsheets|document)/d/([\w-]+)", target)
        if m:
            return {"id": m.group(2), "kind": "sheet" if m.group(1) == "spreadsheets" else "doc"}, False
        if re.fullmatch(r"[\w-]{25,}", target):
            if cur.get("id") == target:
                return dict(cur), False
            meta = self._drive_meta(target)
            k = self._kind_of_mime(meta["mimeType"])
            if not k:
                raise WorkspaceError(f"「{meta['name']}」はスプレッドシートでも文書でもありません。")
            return {"id": meta["id"], "kind": k, "name": meta["name"]}, False
        if cur.get("name") == target and cur.get("id"):
            return dict(cur), False
        return self._search_name(target, kind), False

    # ------------------------------------------------------------ ws_do
    def do(self, ops, target="", ok=False):
        ops = self.parse_ops(ops)
        kind = self.validate_ops(ops)
        st = self._load()
        tgt, is_new = self.resolve_target(target, kind, st)
        if tgt.get("kind") and tgt["kind"] != kind:
            raise WorkspaceError("今の相手は" + ("文書" if tgt["kind"] == "doc" else "スプレッドシート")
                                 + "ですが、頼みの棚は" + ("文書" if kind == "doc" else "シート") + "用です。target を替えてください。")
        # やり直しは 3 回まで（同じ相手での失敗が続いたとき）
        key = tgt.get("id") or tgt.get("new")
        fails = st.get("fails") or {}
        if not is_new and fails.get(key, 0) >= RETRY_MAX:
            raise WorkspaceError(f"同じ相手（{tgt.get('name') or key}）で {RETRY_MAX} 回続けて通りませんでした。ここで止めます。"
                                 "頼み方を変えるか、人の判断が要ります（ws_look で今の様子を見る・ws_undo list で控えを見る）。")
        sheet = (st.get("target") or {}).get("sheet") if (st.get("target") or {}).get("id") == tgt.get("id") else ""
        body_target = {k: v for k, v in tgt.items() if k in ("id", "kind", "new")}
        if sheet:
            body_target["sheet"] = sheet
        # 呼び直しで二重にならない番号：時間切れで終わった同じ頼みは同じ番号で撃つ
        h = _digest(body_target, ops, bool(ok))
        pend = st.get("pending") or {}
        call_id = pend["call_id"] if pend.get("hash") == h else uuid.uuid4().hex
        st["pending"] = {"hash": h, "call_id": call_id}
        self._save(st)
        res = self._post({"action": "do", "call_id": call_id, "target": body_target, "ops": ops, "ok": bool(ok)})
        st = self._load()
        st.pop("pending", None)
        return self._finish_do(st, res, key)

    def _finish_do(self, st, res, key):
        tgt = res.get("target") or {}
        created = res.get("created")
        if created and not tgt.get("id"):
            tgt = created
        if tgt.get("id"):
            st["target"] = {k: tgt[k] for k in ("id", "name", "kind", "url", "sheet") if tgt.get(k)}
        fails = st.setdefault("fails", {})
        if res.get("ok"):
            for k in (key, tgt.get("id")):
                fails.pop(k, None)
        elif not res.get("blocked") and not res.get("arg"):
            nk = tgt.get("id") or key
            fails[nk] = fails.get(nk, 0) + 1
            res["_fail_count"] = fails[nk]
        self._save(st)
        return self.format_do(res)

    @staticmethod
    def _title(tgt):
        s = tgt.get("name") or "(名前なし)"
        if tgt.get("sheet"):
            s += " › " + tgt["sheet"]
        return "対象: " + s

    def format_do(self, res):
        tgt = res.get("target") or res.get("created") or {}
        lines = [self._title(tgt)]
        if res.get("ok"):
            ch = res.get("changed") or []
            for c in ch[:2]:
                lines.append("直した所: " + c)
            if len(ch) > 2:
                lines[-1] += f"（ほか {len(ch) - 2} 件）"
            if not ch:
                lines.append("直した所: なし")
            rest = (res.get("notes") or []) + (res.get("remaining") or [])
            if rest:
                lines.append("残り: " + " ／ ".join(rest[:3]))
            tail = []
            if tgt.get("url"):
                tail.append(tgt["url"])
            if res.get("created"):
                tail.insert(0, "新しく作りました")
            if res.get("backup"):
                tail.append(f"控え #{res['backup']}（ws_undo で戻せます）")
            if res.get("replayed"):
                tail.append("同じ番号の呼び直し：撃ち直さず前の結果を返しました")
            if tail:
                lines.append(" ／ ".join(tail))
            return "\n".join(lines[:5])
        err = res.get("error") or "不明なエラー"
        if res.get("blocked"):
            lines.append("止めました: " + err)
            lines.append("何も変えていません。承認の言葉があるときだけ ok=True で撃ち直してください。")
        elif res.get("busy"):
            lines.append("失敗: " + err)
        else:
            lines.append(f"失敗: {res.get('where', '')} {err}".strip())
            if res.get("restored"):
                lines.append("戻した: 書く前の控えから元に戻しました（途中の状態は残していません）")
            elif res.get("restore_error"):
                lines.append("戻せませんでした: " + res["restore_error"] + "（ws_undo list で控えを確認）")
            if res.get("_fail_count"):
                lines.append(f"やり直し: {res['_fail_count']}/{RETRY_MAX} 回目" + ("（次は止めます）" if res["_fail_count"] >= RETRY_MAX else ""))
        if res.get("created") and not res.get("ok"):
            lines.append("作ったファイルは今の相手として覚えました。やり直しは同じファイルに書きます: " + (res["created"].get("url") or ""))
        return "\n".join(lines[:5])

    # ------------------------------------------------------------ ws_look
    def look(self, target="", sheet="", range=""):
        st = self._load()
        tgt, is_new = self.resolve_target(target, None, st)
        if is_new:
            raise WorkspaceError("ws_look には new: は使えません（まだ無いファイルは見られません）。")
        cur = st.get("target") or {}
        body_target = {k: v for k, v in tgt.items() if k in ("id", "kind")}
        if not body_target.get("kind"):
            meta = self._drive_meta(tgt["id"])
            body_target["kind"] = self._kind_of_mime(meta["mimeType"])
        res = self._post({"action": "look", "target": body_target, "sheet": sheet or (cur.get("sheet") if cur.get("id") == tgt.get("id") else ""), "range": range})
        if not res.get("ok"):
            raise WorkspaceError(res.get("error") or "見られませんでした")
        t = res["target"]
        st = self._load()
        st["target"] = {k: t[k] for k in ("id", "name", "kind", "url", "sheet") if t.get(k)}
        self._save(st)
        return self.format_look(res)

    @staticmethod
    def format_look(res):
        t = res["target"]
        lines = [WorkspaceManager._title(t), "URL: " + t.get("url", "")]
        if t["kind"] == "sheet":
            lines.append("シート: " + "、".join(f"{s['name']}（{s['rows']}行×{s['cols']}列）" for s in res.get("sheets", [])))
            tb = res.get("table")
            if tb:
                d = tb["data"].split("-")
                lines.append(f"表: 見出し {tb['header_row']} 行目・{tb['first_col']}〜{tb['last_col']} 列・明細 {tb['data']} 行目" + (f"・合計行 {tb['total_row']} 行目" if tb.get("total_row") else "・合計行なし"))
                lines.append("列: " + "、".join(f"{c['col']}={c['name']}{'(数値)' if c['number'] else ''}" for c in tb["columns"]))
            else:
                lines.append("表: 見つかりません（空のシート、または見出しの行がありません）")
            if res.get("values"):
                lines.append(f"中身 {res['range']}:")
                fm = res.get("formulas") or []
                for i, row in enumerate(res["values"][:60]):
                    cells = []
                    for j, v in enumerate(row):
                        f = fm[i][j] if i < len(fm) and j < len(fm[i]) else ""
                        cells.append(f"{v}{'  {' + f + '}' if f else ''}")
                    lines.append("\t".join(cells))
        else:
            lines.append(f"段落数 {res.get('paragraphs')}・見出し: " + (" / ".join(f"{h['no']}:{'#' * h['level']}{h['text']}" for h in res.get("headings", [])) or "なし"))
            lines.extend(res.get("outline", []))
        return "\n".join(lines)

    # ------------------------------------------------------------ ws_undo
    def undo(self, to="", list=False, ok=False):
        if list:
            res = self._post({"action": "list"})
            items = res.get("ledger") or []
            if not items:
                return "控えの記録はまだありません。"
            out = ["番号 / 時刻 / 相手 / した事"]
            for it in items[:15]:
                out.append(f"#{it['n']} {it['time'][5:16]} {it['target']} {it['what']}" + ("（戻し済み）" if it.get("undone") else ""))
            return "\n".join(out)
        st = self._load()
        res = self._post({"action": "undo", "to": str(to or ""), "ok": bool(ok)})
        t = res.get("target") or {}
        if res.get("ok"):
            if t.get("id"):
                st["target"] = {k: t[k] for k in ("id", "name", "kind", "url") if t.get(k)}
                st.get("fails", {}).pop(t["id"], None)
                self._save(st)
            return "\n".join([self._title(t), f"戻した: #{res['undone']}（{res.get('what', '')}）を取り消しました",
                              f"控え #{res['backup']}（戻す前の状態。もう一度 ws_undo で元に戻せます）", t.get("url", "")])
        msg = res.get("error") or "戻せませんでした"
        if res.get("needs_ok"):
            return "\n".join([self._title(t), "止めました: " + msg])
        return "戻せませんでした: " + msg
