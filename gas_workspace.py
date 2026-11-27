# -*- coding: utf-8 -*-
"""
gas_workspace.py - Workspace マネージャー（スプレッドシートとドキュメントを会話で作る・直す）

通り道は 1 本：専用の GAS エンジン（shu-workspace-engine, workspace_engine.gs）の /exec に
本人のトークンで POST する。型（棚）はエンジンが持ち、ここは
  ・今の相手（.ws_state.json）を覚える　・ファイルを名前で探す（Drive 一覧）
  ・ops（棚の名前と引数の JSON）を撃つ前に検査する　・呼び直しで二重にならない番号　・報告を 3〜5 行に組む
だけを受け持つ。書く前の控え・失敗時の戻し・undo・指紋はエンジン側。
"""

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import gas_ws_api
import gas_ws_browser
import gas_ws_catalog
import gas_ws_find

HERE = Path(__file__).resolve().parent
ENGINE_COMMON = HERE / "workspace_engine.gs"      # 共通部（入口・控え・戻し・台帳・look・render・手伝い）。棚は置かない
SHELF_DIR = HERE / "ws_shelves"                   # 棚（札つき）。道具が *.gs を全部読む
ENGINE_SOURCE = HERE / ".ws_engine_all.gs"        # 共通部＋Catalog＋棚をつないだ全文（GAS に入れる形・道具が作る・git に入れない）
ENGINE_TITLE = "shu-workspace-engine"
RETRY_MAX = 3

MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_DOC = "application/vnd.google-apps.document"

CATALOG = gas_ws_catalog.load(SHELF_DIR)
# 棚の検査表（kind / req / any / keys）は棚の札から作る。手では書かない
SHELVES = CATALOG.specs()


class WorkspaceError(Exception):
    """利用者（AI）に日本語でそのまま返す種類のエラー"""


class WorkspaceAuthNeeded(WorkspaceError):
    pass


class WorkspaceTimeout(WorkspaceError):
    pass


_ENGINE_CACHE = {}


def _engine_bundle(common_path=ENGINE_COMMON, shelf_dir=SHELF_DIR):
    """共通部・Catalog・棚の (texts, hash, version) をファイルの更新時刻つきでキャッシュして返す"""
    cp, sd = Path(common_path).resolve(), Path(shelf_dir).resolve()
    sfiles = gas_ws_catalog.shelf_files(sd)
    try:
        cst = cp.stat()
        ast_m = Path(gas_ws_api.__file__).stat().st_mtime_ns
        sig = (cst.st_mtime_ns, cst.st_size, ast_m, tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sfiles))
    except OSError:
        sig = None
    cached = _ENGINE_CACHE.get((cp, sd))
    if sig is not None and cached is not None and cached[0] == sig:
        return cached[1], cached[2], cached[3]
    cat = CATALOG if (sd == SHELF_DIR.resolve() and cached is None) else gas_ws_catalog.load(sd)
    common_text = cp.read_text(encoding="utf-8")
    out = [("Engine", common_text), ("Catalog", gas_ws_catalog.build_catalog_gs(cat)), ("ApiTypes", gas_ws_api.build_types_gs())]
    for p in sfiles:
        out.append((p.stem, p.read_text(encoding="utf-8")))
    h = hashlib.sha1()
    for _, text in out:
        h.update(text.encode("utf-8"))
    fhash = h.hexdigest()[:8]
    m = re.search(r"var ENGINE_VERSION = '([^']*)'", common_text)
    ver = f"{m.group(1) if m else 'ws'}+{fhash}"
    if sig is not None:
        _ENGINE_CACHE[(cp, sd)] = (sig, out, fhash, ver)
    return out, fhash, ver


def _engine_texts(common_path=ENGINE_COMMON, shelf_dir=SHELF_DIR):
    """GAS に入れる順の (名前, 本文): 共通部 → Catalog（札から作る）→ 棚のファイル（名前の順）"""
    return list(_engine_bundle(common_path, shelf_dir)[0])


class _Timer:
    """ws_do 1 回の内訳（秒）。WS_TIMING=1 のときだけ返事に出す。普段は計るだけで何も出さない"""

    def __init__(self):
        self.t0 = self.last = time.perf_counter()
        self.laps = {}
        self.engine = {}

    def lap(self, name):
        n = time.perf_counter()
        self.laps[name] = self.laps.get(name, 0.0) + (n - self.last)
        self.last = n

    def total(self):
        return time.perf_counter() - self.t0


ENGINE_LAP_NAMES = [("lock", "鍵待ち"), ("cacheGet", "呼び直し確認"), ("open", "ファイルを開く"), ("seq", "台帳の番号"), ("backup", "控え"), ("finger0", "書く前の指紋"), ("ops", "棚の本体"),
                    ("save", "文書の保存"), ("finger", "書いた後の指紋"), ("noop", "変更なしの判定"), ("discard", "控えの破棄"), ("ledger", "台帳の書き込み"),
                    ("bk_open", "控え:ブックを開く"), ("bk_list", "控え:タブ一覧"), ("bk_copy", "控え:シートの写し"), ("bk_name", "控え:名前付け"), ("bk_prune", "控え:古いタブを消す"), ("bk_side", "控え:脇の状態"), ("bk_lite", "控え:軽量")]


def format_timing(tim):
    """内訳の 2 行（秒）。準備＝Python 側（検査・相手の解決・状態の保存・エンジン版の確認）、往復＝Web アプリの呼び出しの待ち"""
    L = tim.laps
    eng = tim.engine or {}
    roundtrip = L.get("往復", 0.0)
    eng_total = (eng.get("total") or 0) / 1000.0
    prep = sum(L.get(k, 0.0) for k in ("検査", "相手", "状態", "版"))
    line1 = (f"内訳(秒) 合計 {tim.total():.2f}: 準備 {prep:.2f}（検査 {L.get('検査', 0):.2f}・相手 {L.get('相手', 0):.2f}・状態 {L.get('状態', 0):.2f}・版の確認 {L.get('版', 0):.2f}）"
             f" ／ 往復 {roundtrip:.2f}（エンジン内 {eng_total:.2f}・残り＝通信と起動 {max(roundtrip - eng_total, 0):.2f}）"
             f" ／ 返事の組み立て {L.get('返事', 0):.2f}")
    parts = [f"{label} {eng[k] / 1000.0:.2f}" for k, label in ENGINE_LAP_NAMES if k in eng]
    line2 = "エンジン内(秒): " + ("・".join(parts) if parts else "（エンジンが内訳を返していません）")
    return line1 + "\n" + line2


def _file_hash(common_path=ENGINE_COMMON, shelf_dir=SHELF_DIR):
    """版の指紋: 入れる全ファイルの連結から取る"""
    return _engine_bundle(common_path, shelf_dir)[1]


def _range_origin(range_str):
    """"A2:H16"・"経費!C3:D9"・"" の左上の (行, 列)（1 始まり）。読めなければ (1, 1)"""
    s = str(range_str or "").strip()
    if "!" in s:
        s = s.rsplit("!", 1)[1]
    m = re.match(r"\$?([A-Za-z]{1,3})\$?(\d+)", s)
    if not m:
        return 1, 1
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)), col


def _digest(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


BROWSER_TARGET_ALIASES = ("browser", "now", "active", "今", "ブラウザ")
RECENT_TARGET_ALIASES = ("recent", "最近")


class WorkspaceManager:
    def __init__(self, client=None, state_path=None, engine_path=None, shelf_dir=None, browser_detect=None):
        self._client = client
        self.state_path = Path(state_path) if state_path else HERE / ".ws_state.json"
        self.browser_active_path = self.state_path.parent / ".ws_browser_active.json"
        self.browser_detect = (
            (state_path is None and os.environ.get("WS_NO_BROWSER_DETECT", "").strip().lower() not in ("1", "true", "yes"))
            if browser_detect is None
            else bool(browser_detect)
        )
        self.engine_path = Path(engine_path) if engine_path else ENGINE_COMMON
        self.shelf_dir = Path(shelf_dir) if shelf_dir else (self.engine_path.parent / "ws_shelves")
        self.catalog = CATALOG if self.shelf_dir.resolve() == SHELF_DIR.resolve() else gas_ws_catalog.load(self.shelf_dir)
        self.finder = gas_ws_find.Finder(self.catalog, synonyms=gas_ws_find.load_synonyms(self.shelf_dir / "synonyms.txt"),
                                         guide=gas_ws_find.load_guide(self.shelf_dir / "guide.txt"))
        self.misses_path = HERE / ".ws_misses.tsv"      # 弱かった頼み（git に入れない）
        self.ask_misses_path = self.state_path.parent / ".ws_ask_misses.tsv"   # ws_do(ask) の外れ記録（git に入れない）
        self.api_uses_path = gas_ws_api.USES_FILE        # 撃った api の型の記録（git に入れない）
        self.engine_title = ENGINE_TITLE      # エンジンの GAS プロジェクトの名前（別のエンジンを使う道具が差し替える）
        self.extra_texts = []                 # 共通部・棚のあとに足すファイル [(名前, 本文)]（別のエンジンの入口など）
        self.timing = os.environ.get("WS_TIMING", "").lower() in ("1", "true", "yes", "on")   # ws_do の内訳を返事に足す
        self.last_timing = None
        self._tim = None

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
        return _engine_bundle(self.engine_path, self.shelf_dir)[2]

    def _engine_files(self, split=False):
        """GAS に入れるファイル。既定は appsscript と、全部をつないだ 1 本の Engine（順番は共通部 → Catalog → 棚）。
        split=True は共通部・Catalog・棚のファイルごとに分ける（設計書の形）"""
        texts = _engine_texts(self.engine_path, self.shelf_dir)
        texts[0] = (texts[0][0], re.sub(r"var ENGINE_VERSION = '[^']*';", f"var ENGINE_VERSION = '{self.engine_version()}';", texts[0][1], count=1))
        manifest = {
            "timeZone": "Asia/Tokyo", "exceptionLogging": "STACKDRIVER", "runtimeVersion": "V8",
            # 目（render）が罫線を読むのに Sheets の高度なサービスを使う（許可は spreadsheets のまま増えない）
            "dependencies": {"enabledAdvancedServices": [{"userSymbol": "Sheets", "serviceId": "sheets", "version": "v4"}]},
            "oauthScopes": [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive",
            ],
            "webapp": {"executeAs": "USER_DEPLOYING", "access": "MYSELF"},
        }
        head = {"name": "appsscript", "type": "JSON", "source": json.dumps(manifest, indent=2)}
        texts = texts + list(self.extra_texts)
        if split:
            return [head] + [{"name": n, "type": "SERVER_JS", "source": s} for n, s in texts]
        return [head, {"name": "Engine", "type": "SERVER_JS", "source": "\n".join(s for _, s in texts)}]

    def _find_engine_sid(self):
        q = f"mimeType='application/vnd.google-apps.script' and name='{self.engine_title}' and trashed=false"
        files = self._drive_list(q, "files(id,name)")
        return files[0]["id"] if files else None

    def install_engine(self, st=None):
        """エンジンの置き場所を決め、リポジトリの版を差し替える（無ければ作る）"""
        st = st if st is not None else self._load()
        sid = st.get("engine_sid") or self._find_engine_sid()
        if not sid:
            sid = self.client.create_project(self.engine_title)["scriptId"]
        self.client._put_content(sid, self._engine_files())
        dep_id = st.get("engine_deploy_id") or None
        dep = self.client.deploy(
            sid,
            description=f"{self.engine_title} {self.engine_version()}",
            deployment_id=dep_id,
            refresh=not dep_id,
            fast=True,
        )
        dep_id = (dep or {}).get("deploymentId") or dep_id or ""
        url = (dep or {}).get("webAppUrl") or ""
        if not url.startswith("http"):
            prev_url = st.get("engine_url") or ""
            url = prev_url if (dep_id and prev_url.startswith("http") and prev_url.endswith("/exec")) else self.client.resolve_webapp_url(sid, refresh=True, dev=False)
        st["engine_url"] = re.sub(r"/(exec|dev)$", "/exec", url)
        if dep_id:
            st["engine_deploy_id"] = dep_id
        st["engine_sid"] = sid
        st["engine_ver"] = self.engine_version()
        self._save(st)
        return st

    def _ensure_engine(self):
        st = self._load()
        url = st.get("engine_url") or ""
        if (
            not st.get("engine_sid")
            or not url.endswith("/exec")
            or not st.get("engine_deploy_id")
            or st.get("engine_ver") != self.engine_version()
        ):
            st = self.install_engine(st)
        return st

    def _post(self, body, timeout=90):
        tim = self._tim
        if getattr(self, "lane", "") and "lane" not in body:
            body = dict(body, lane=self.lane)       # 並べて回すとき（試験用のエンジンだけが読む）
        st = self._ensure_engine()
        if tim:
            tim.lap("版")
        url = st["engine_url"]
        try:
            r = self.client.call_webapp(url, body=body, method="POST", use_auth=True, timeout=timeout)
        except TimeoutError as e:
            raise WorkspaceTimeout(str(e))
        finally:
            if tim:
                tim.lap("往復")
        data = r.get("data")
        if isinstance(data, dict):
            ver = data.get("version")
            if ver and ver != self.engine_version() and not body.get("_retried"):
                # 版が違う（誰かがエンジンを書き換えた）→ 差し替えて 1 回だけ撃ち直す
                self.install_engine(self._load())
                return self._post(dict(body, _retried=True), timeout)
            err_msg = str(data.get("error") or "")
            if data.get("ok") is False and ("呼び出す権限がありません" in err_msg or "You do not have permission to call" in err_msg or "Required permissions:" in err_msg):
                raise WorkspaceAuthNeeded(self._auth_message(data.get("auth_url") or url))
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
            raise WorkspaceError("ops は棚の JSON 配列です。例: [{\"shelf\":\"棚の名前\", …引数}]。棚の名前と引数は ws_find（または ws_look の ask）で引けます。")
        return ops

    def validate_ops(self, ops):
        """棚の札（引数: どれか:）から形を検査する。意味（列があるか・範囲が表の中か）はエンジンが見る"""
        kinds, first_kind = set(), None
        for i, op in enumerate(ops, 1):
            if not isinstance(op, dict) or not isinstance(op.get("shelf"), str):
                raise WorkspaceError(f"{i} 番目の ops に \"shelf\"（棚の名前）がありません。棚の名前と引数は ws_find（または ws_look の ask）で引けます。")
            name = op["shelf"]
            spec = self.catalog.spec(name)
            if not spec:
                near = self.finder.near(name)
                raise WorkspaceError(f"棚「{name}」はありません（{i} 番目）。" + ("\n" + near if near else ""))
            msg = self.catalog.check_op(i, op) or (gas_ws_catalog.EXTRA_CHECKS[name](op) if name in gas_ws_catalog.EXTRA_CHECKS else None)
            if msg:
                s = self.catalog.by_name[name]
                raise WorkspaceError(msg + "\nその棚の札:\n" + "\n".join(self.finder.card(s)) + "\n   引数: " + s["args_raw"])
            if first_kind is None:
                first_kind = spec["kind"]
            if not self.catalog.by_name[name].get("shared") and name not in gas_ws_catalog.LOCAL_HANDLERS:
                kinds.add(spec["kind"])
        if len(kinds) > 1:
            raise WorkspaceError("スプレッドシートの棚と文書の棚は、同じ ws_do にまとめられません。")
        return kinds.pop() if kinds else first_kind

    @staticmethod
    def _op_needs_target(op):
        sh = op.get("shelf")
        if sh in gas_ws_catalog.LOCAL_HANDLERS:
            return False
        fn = gas_ws_catalog.NEEDS_TARGET_FN.get(sh)
        return bool(fn(op)) if fn else True

    @classmethod
    def _ops_need_target(cls, ops):
        return any(cls._op_needs_target(o) for o in ops)

    # ------------------------------------------------------------ ブラウザ連動・最近開いたファイル
    def recent_files(self, limit=10, kind=None):
        """Drive API から最近開いた（または更新された）スプレッドシート・文書を取得する。"""
        mimes = [MIME_SHEET, MIME_DOC] if not kind else [MIME_SHEET if kind == "sheet" else MIME_DOC]
        mq = " or ".join(f"mimeType='{m}'" for m in mimes)
        q = f"({mq}) and trashed=false"
        fields = "files(id,name,mimeType,modifiedTime,viewedByMeTime,webViewLink)"
        for order_by in ("viewedByMeTime desc, modifiedTime desc", "modifiedTime desc"):
            r = self.client._request_with_retry(
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                headers=self.client._headers(),
                params={"q": q, "fields": fields, "pageSize": max(1, min(int(limit or 10), 30)), "orderBy": order_by},
                timeout=15,
            )
            if r.status_code == 200:
                files = r.json().get("files", [])
                out = []
                for f in files:
                    out.append({
                        "id": f.get("id", ""),
                        "name": f.get("name", ""),
                        "kind": self._kind_of_mime(f.get("mimeType")),
                        "viewedByMeTime": f.get("viewedByMeTime", ""),
                        "modifiedTime": f.get("modifiedTime", ""),
                        "url": f.get("webViewLink", ""),
                    })
                return out
        raise WorkspaceError("Drive の最近開いたファイル一覧の取得に失敗しました。")

    def format_recent_files(self, limit=10, kind=None):
        """最近開いたスプレッドシート・文書の一覧を整形して返す。"""
        items = self.recent_files(limit=limit, kind=kind)
        if not items:
            return "最近開いたスプレッドシート・文書が見つかりませんでした。"
        lines = [f"=== 最近開いたスプレッドシート・文書 ({len(items)}件) ==="]
        for i, it in enumerate(items, 1):
            k_lbl = "スプレッドシート" if it["kind"] == "sheet" else "文書"
            ts = (it.get("viewedByMeTime") or it.get("modifiedTime") or "")[:16].replace("T", " ")
            lines.append(f"{i}. {it['name']}（{k_lbl}・{ts or '日時不明'}）")
            lines.append(f"   {it['url'] or ('https://docs.google.com/spreadsheets/d/' + it['id'] + '/edit')}")
        return "\n".join(lines)

    def _detect_from_extension(self, max_age_sec=None):
        import gas_ws_browser
        kwargs = {"path": self.browser_active_path}
        if max_age_sec is not None:
            kwargs["max_age_sec"] = max_age_sec
        return gas_ws_browser.load_browser_active(**kwargs)

    def _detect_from_windows(self):
        import gas_ws_browser
        return gas_ws_browser.detect_window_targets()

    def _resolve_browser_target(self, st, kind=None, force=False):
        """1. Chrome 拡張同期 → 2. Windows ウィンドウタイトル の順で現在開いている相手を解決する。"""
        cur = st.get("target") or {}
        ext = self._detect_from_extension()
        if ext and (not kind or ext.get("kind") == kind):
            ext_changed = float(ext.get("changed_at") or 0.0)
            set_at = float(st.get("target_set_at") or 0.0)
            if force or not cur.get("id") or ext_changed > set_at:
                out = {
                    "id": ext["id"],
                    "kind": ext.get("kind") or "sheet",
                    "name": ext.get("name") or "",
                    "url": ext.get("url") or "",
                    "_source": "browser_ext",
                }
                if ext.get("sheet"):
                    out["sheet"] = ext["sheet"]
                if ext.get("selection"):
                    out["_selection"] = ext["selection"]
                return out
            # 拡張が新鮮な状態かつ target_set_at の方が新しい＝人が明示指定した別ファイル作業中
            return None

        if not (self.browser_detect or force):
            return None

        win_list = self._detect_from_windows()
        picked = None
        for w in win_list:
            if not kind or w.get("kind") == kind:
                picked = w
                break
        if not picked:
            return None
        if not force and cur.get("id") and picked["window_title"] == st.get("last_window_title"):
            return None
        try:
            found = self._search_name(picked["name"], picked["kind"])
        except WorkspaceError:
            if force or not cur.get("id"):
                raise
            return None
        found["_source"] = "window_title"
        found["_window_title"] = picked["window_title"]
        return found

    def inspect_active_target(self, include_recent=False):
        """ブラウザ連動の現在状態（拡張機能・ウィンドウ検知・記憶中の相手・Drive最近）を診断レポートで返す。"""
        st = self._load()
        cur = st.get("target") or {}
        ext = self._detect_from_extension()
        wins = self._detect_from_windows()

        lines = ["=== gas-manager ブラウザ連動・相手検知状態 ==="]
        if ext:
            k_lbl = "スプレッドシート" if ext.get("kind") == "sheet" else "文書"
            sel_s = f"・選択 {ext['selection']}" if ext.get("selection") else ""
            sh_s = f" › {ext['sheet']}" if ext.get("sheet") else ""
            lines.append(f"1. Chrome拡張（即時同期・{ext.get('source', 'ext')} / {ext.get('age_sec', 0)}秒前）:")
            lines.append(f"   {ext.get('name') or '(名前未取得)'}{sh_s}（{k_lbl}{sel_s}）")
            lines.append(f"   ID: {ext['id']}  URL: {ext.get('url', '')}")
        else:
            lines.append("1. Chrome拡張（即時同期）: 未受信（または期限切れ）")

        if wins:
            lines.append(f"2. Windowsウィンドウ検知 ({len(wins)}件・手前順):")
            for w in wins[:5]:
                k_lbl = "シート" if w["kind"] == "sheet" else "文書"
                lines.append(f"   - [{k_lbl}] {w['name']}  ({w['window_title']})")
        else:
            lines.append("2. Windowsウィンドウ検知: 開いている Google シート/文書は見つかりません")

        if cur.get("id"):
            sh_s = f" › {cur['sheet']}" if cur.get("sheet") else ""
            lines.append(f"3. 記憶中の相手 (.ws_state.json): {cur.get('name') or cur['id']}{sh_s}")
            if cur.get("url"):
                lines.append(f"   {cur['url']}")
        else:
            lines.append("3. 記憶中の相手 (.ws_state.json): なし")

        if include_recent or (not ext and not wins):
            try:
                rec = self.recent_files(limit=5)
                if rec:
                    lines.append("4. Drive 最近開いたファイル (上位5件):")
                    for r in rec:
                        k_lbl = "シート" if r["kind"] == "sheet" else "文書"
                        ts = (r.get("viewedByMeTime") or r.get("modifiedTime") or "")[:16].replace("T", " ")
                        lines.append(f"   - [{k_lbl}] {r['name']} ({ts})  ID: {r['id']}")
            except Exception as e:
                lines.append(f"4. Drive 最近開いたファイル: 取得失敗 ({e})")

        diag = gas_ws_browser.diagnose_browser_sync()
        mcp_lbl = "稼働" if diag["mcp_sync_ok"] else "停止"
        watch_lbl = "稼働" if diag["watch_ok"] else "停止"
        lines.append(f"5. 受信口: MCP({diag['mcp_port']})={mcp_lbl} / 直結watch({diag['watch_port']})={watch_lbl}")
        if (not ext) or diag["hints"]:
            for h in diag["hints"]:
                lines.append(f"   診断ヒント: {h}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 相手を決める
    def resolve_target(self, target, kind, st):
        target = (target or "").strip()
        cur = st.get("target") or {}
        if target.lower() in BROWSER_TARGET_ALIASES:
            bt = self._resolve_browser_target(st, kind=kind, force=True)
            if bt:
                return bt, False
            hint = ""
            try:
                rec = self.recent_files(limit=5, kind=kind)
                if rec:
                    hint = "\n最近開いたファイル:\n" + "\n".join(
                        f"  - {r['name']} ({r['id']})" for r in rec
                    )
            except Exception:
                pass
            raise WorkspaceError(
                "ブラウザで開いているスプレッドシート・文書を検知できませんでした。"
                "Chrome で対象タブを開くか、URL・ID・名前を target に指定してください。" + hint
            )
        if not target:
            if cur.get("id"):
                return dict(cur), False
            if self.browser_active_path.exists() or self.browser_detect:
                bt = self._resolve_browser_target(st, kind=kind, force=False)
                if bt:
                    return bt, False
            raise WorkspaceError("今の相手が決まっていません。target に URL・ID・名前、または \"new:名前\"（新規）を渡してください。")
        if target.lower().startswith("new:"):
            raw = target[4:].strip()
            if not raw:
                raise WorkspaceError("new: のあとに新しいファイルの名前が要ります（例: new:見積書）。")
            if "/" in raw:
                folder_spec, name = raw.rsplit("/", 1)
                folder_spec, name = folder_spec.strip(), name.strip()
                if not name:
                    raise WorkspaceError("new:フォルダ名/ のあとに新しいファイルの名前が要ります（例: new:営業部/見積書）。")
                out = {"new": name, "kind": kind}
                if folder_spec:
                    out["folder"] = folder_spec
                return out, True
            return {"new": raw, "kind": kind}, True
        m = re.search(r"/(spreadsheets|document)/d/([\w-]+)", target)
        if m:
            fid = m.group(2)
            out = {"id": fid, "kind": "sheet" if m.group(1) == "spreadsheets" else "doc"}
            if out["kind"] == "sheet":
                mg = re.search(r"[?#&]gid=([0-9]+)", target)
                tc = st.get("table_cache") or {}
                if mg and int(mg.group(1)) == 0 and tc.get("id") == fid and tc.get("sheets"):
                    out["sheet"] = tc["sheets"][0]
                elif cur.get("id") == fid and cur.get("sheet"):
                    out["sheet"] = cur["sheet"]
            return out, False
        m_open = re.search(r"(?:^|[?&])id=([\w-]{20,})", target)
        if m_open and target.startswith("http"):
            fid = m_open.group(1)
            if cur.get("id") == fid:
                return dict(cur), False
            meta = self._drive_meta(fid)
            k = self._kind_of_mime(meta["mimeType"])
            if not k:
                raise WorkspaceError(f"「{meta['name']}」はスプレッドシートでも文書でもありません。")
            return {"id": meta["id"], "kind": k, "name": meta["name"]}, False
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
    def _switch_sheet(self, target, sheet):
        """ws_do(sheet=…): 撃つシートを名指しする。今の相手と違うときだけ、そのシートを読んで相手にする
        （確かめに読んだ別のシートへ次の手が流れないように・11/27 撃ち直し 3 の #5）"""
        sheet = str(sheet or "").strip()
        if not sheet or str(target or "").startswith("new:"):
            return
        cur = self._load().get("target") or {}
        t = str(target or "").strip()
        same_file = (not t) or t == cur.get("id") or t == cur.get("name") or (cur.get("id") and cur["id"] in t)
        if same_file and cur.get("sheet") == sheet:
            return
        self._look(target=target, sheet=sheet)

    def do(self, ops="", target="", ok=False, ask="", sheet=""):
        tim = _Timer()
        self._tim = tim
        try:
            self._switch_sheet(target, sheet)
            tim.lap("シート")
            if not str(target or "").startswith("new:"):
                self._prime_before()                 # 前→後の「前」を撃つ直前に取る
                tim.lap("前の写し")
            if ask and not (ops if isinstance(ops, (list, dict)) else str(ops or "").strip()):
                out = self._do_ask(ask, target, ok, tim)
            else:
                out = self._do(ops, target, ok, tim)
        finally:
            self._tim = None
        tim.lap("返事")
        self.last_timing = tim
        return out + ("\n" + format_timing(tim) if self.timing else "")

    # ------------------------------------------------------------ ws_do(ask=…)：当てて・組んで・撃つを 1 回で
    @staticmethod
    def _save_sheet_vals(st, sid, sheet, cell_map, bounds=None):
        """前→後の「前」を覚える。bounds=(r1, c1, r2, c2) は読んだ範囲（後と比べるのはこの中だけ）。
        読んだ範囲の外を「(空) → 値」と出さないように、範囲も一緒に覚える（11/27・A1:B2 だけ読んだ後に 113 セルの誤報）"""
        if not sid or not sheet or not isinstance(cell_map, dict):
            return
        m = st.setdefault("last_sheet_values", {})
        key = f"{sid}:{sheet}"
        # A1:Z60（1,560 セル）まで覚える（200 で切ると、大きい表で切った先が「(空) → 値」に見えた）
        ser = {f"{r},{c}": str(v) for (r, c), v in list(cell_map.items())[:1600]}
        if bounds:
            ser["_bounds"] = ",".join(str(int(x)) for x in bounds)
        m[key] = ser
        if len(m) > 8:
            for old_k in list(m.keys())[:-8]:
                m.pop(old_k, None)

    @staticmethod
    def _load_sheet_vals(st, sid, sheet):
        if not sid or not sheet:
            return {}
        raw = (st.get("last_sheet_values") or {}).get(f"{sid}:{sheet}") or {}
        out = {}
        for k, v in raw.items():
            if k == "_bounds":
                continue
            try:
                r_s, c_s = k.split(",", 1)
                out[(int(r_s), int(c_s))] = v
            except Exception:
                pass
        return out

    @staticmethod
    def _sheet_vals_bounds(st, sid, sheet):
        raw = (st.get("last_sheet_values") or {}).get(f"{sid}:{sheet}") or {}
        try:
            r1, c1, r2, c2 = (int(x) for x in str(raw.get("_bounds") or "").split(","))
            return r1, c1, r2, c2
        except Exception:
            return None

    def _prime_before(self):
        """撃つ直前に、今の相手のシートの A1:Z60 を読んで前→後の「前」にする（Excel マネージャーの seiri が
        撃つ前に写しを取るのと同じ）。前に読んだ物と比べると、読んだ範囲・時が違って偽の「変更」が出た（11/27）"""
        st = self._load()
        tgt = st.get("target") or {}
        if st.get("direct_off") or tgt.get("kind") != "sheet" or not tgt.get("id") or not tgt.get("sheet"):
            return
        try:
            import gas_ws_direct
            light = gas_ws_direct.fetch_sheet_snapshot_light(self, st, tgt["id"], tgt["sheet"], "A1:Z60")
            if not light:
                return
            _, _, a_map = gas_ws_direct.snapshot_to_grids(light["snap"], tgt["sheet"], light["table"])
            st_now = self._load()
            if st.get("direct_token"):
                st_now["direct_token"] = st["direct_token"]
            self._save_sheet_vals(st_now, tgt["id"], tgt["sheet"], a_map, bounds=(1, 1, 60, 26))
            self._save(st_now)
        except Exception:
            pass

    @staticmethod
    def _filter_new_insights(st, tgt_id, sheet_name, insights):
        """同じシートで一度伝えた気づき文言を繰り返さないよう絞り込む。"""
        if not insights or not tgt_id:
            return list(insights or [])
        key = f"{tgt_id}:{sheet_name or ''}"
        seen_map = st.setdefault("seen_insights", {})
        seen_list = seen_map.get(key) or []
        fresh = [x for x in insights if x not in seen_list]
        if fresh:
            seen_map[key] = (seen_list + fresh)[-20:]
        return fresh

    def _remember_table(self, st, tgt, table, sheets):
        """表の形を覚える（次の頼みの引数を組むのに使う）。sheets は名前のリスト"""
        if not tgt.get("id"):
            return
        st["table_cache"] = {"id": tgt["id"], "sheet": tgt.get("sheet", ""), "table": table or None,
                             "sheets": [s["name"] if isinstance(s, dict) else s for s in (sheets or [])]}

    def _cached_table(self, st, tgt):
        tc = st.get("table_cache") or {}
        if tgt.get("id") and tc.get("id") == tgt["id"] and (not tgt.get("sheet") or tc.get("sheet") == tgt.get("sheet")):
            return tc
        return None

    def _do_ask(self, ask, target, ok, tim):
        import gas_ws_ask
        st = self._load()
        # 相手が決まる前やターゲット不要の棚だけのときは、ファイルを開かずにそのまま実行する
        p0 = gas_ws_ask.plan(ask, self.finder, "")
        if p0.fire and p0.ops and not self._ops_need_target(p0.ops):
            tim.lap("当て")
            st2, res, key = self._do_res(p0.ops, target, ok, tim)
            text = self._finish_do(st2, res, key)
            if res.get("ok") and st2.pop("last_unfired_ask", None) is not None:
                self._save(st2)
            if not res.get("ok"):
                return text
            shown = ", ".join(o["shelf"] + "(" + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in o.items() if k != "shelf") + ")" for o in p0.ops)
            ch_text = " ／ ".join(res.get("changed") or []) or "なし"
            out_lines = [self._title(res.get("target") or {}), f"直した所: {ch_text}（撃った棚: {shown}）"]
            errs = [x for x in (res.get("notes") or []) if x.startswith(("新しいエラー", "式が減った", "式の値が変わった"))]
            rest = [x for x in (res.get("notes") or []) if x not in errs]
            out_lines += errs
            if rest:
                out_lines.append("メモ: " + " ／ ".join(rest[:3]))
            out_lines.append("次の手: 上のエラーを見て、直すか ws_undo で戻すかを決めてから使う人に報告する" if errs
                             else "次の手: なし＝これで仕上がり。道具をこれ以上撃たず、何をどこに作った・直したかを 3〜5 行で報告する")
            return "\n".join(out_lines)
        tgt, is_new = self.resolve_target(target, None, st)
        if tgt.get("_window_title"):
            st["last_window_title"] = tgt["_window_title"]
            self._save(st)
        elif (target or "").strip() and (target or "").strip().lower() not in BROWSER_TARGET_ALIASES:
            st["target_set_at"] = time.time()
            self._save(st)
        kind = tgt.get("kind") or ""
        if not kind and tgt.get("id"):
            kind = self._kind_of_mime(self._drive_meta(tgt["id"])["mimeType"]) or ""
        tim.lap("相手")
        tc, fresh = None, False

        def look_fresh():
            try:
                self._look(target=target)           # 表の形を見て覚える（1 往復）
            except WorkspaceError as e:
                if "がありません。あるのは" not in str(e):
                    raise
                s0 = self._load()                    # 覚えていたシートが消えた → 先頭のシートで見直す
                (s0.get("target") or {}).pop("sheet", None)
                self._save(s0)
                self._look(target=target)
            s = self._load()
            t = dict(s.get("target") or tgt)
            return t, self._cached_table(s, t)
        if kind == "sheet" and not is_new:
            tc = self._cached_table(st, tgt)
            if tc is None:                          # 表の形を覚えていない相手は、先に 1 回だけ見る
                tgt, tc = look_fresh()
                fresh = True
            # 頼みの中に別シート名（例:「社員の表」「社員：」）が含まれていれば、相手のシートを切り替える
            sheets_known = [s for s in ((tc or {}).get("sheets") or []) if s]
            cur_sh0 = tgt.get("sheet") or (tc or {}).get("sheet") or ""
            ask_n = ask.strip()
            mentioned_sh = None
            for sn in sorted(sheets_known, key=len, reverse=True):
                if sn == cur_sh0:
                    continue
                if re.match(rf"^{re.escape(sn)}\s*[:：]|{re.escape(sn)}(?:シート|の表|のシート|を|の)", ask_n):
                    mentioned_sh = sn
                    break
            if mentioned_sh:
                tgt["sheet"] = mentioned_sh
                s_sw = self._load()
                if (s_sw.get("target") or {}).get("id") == tgt.get("id"):
                    s_sw["target"]["sheet"] = mentioned_sh
                    self._save(s_sw)
                self._look(target=tgt.get("id") or target, sheet=mentioned_sh)
                s_sw2 = self._load()
                tgt = dict(s_sw2.get("target") or tgt)
                tc = self._cached_table(s_sw2, tgt)
                fresh = True
        tim.lap("表の形")
        for attempt in range(2):
            table = (tc or {}).get("table")
            cur_sh = tgt.get("sheet") or (tc or {}).get("sheet") or ""
            ls_info = st.get("last_scope") or {}
            ls = ls_info.get("scope") if ls_info.get("id") == tgt.get("id") and (not cur_sh or not ls_info.get("sheet") or ls_info.get("sheet") == cur_sh) else None
            p = gas_ws_ask.plan(ask, self.finder, kind, table, (tc or {}).get("sheets"), cur_sheet=cur_sh, last_scope=ls)
            tim.lap("当て")
            if not p.fire and p.missing and not p.reasons and not fresh and kind == "sheet" and not is_new:
                # 覚えていた形で引数が決まらなかった → 形が変わったのかもしれない。1 回だけ見直して組み直す
                tgt, tc = look_fresh()
                fresh = True
                table = (tc or {}).get("table")
                cur_sh = tgt.get("sheet") or (tc or {}).get("sheet") or ""
                p = gas_ws_ask.plan(ask, self.finder, kind, table, (tc or {}).get("sheets"), cur_sheet=cur_sh, last_scope=ls)
                tim.lap("当て")
            if not p.fire:
                if p.read_only:
                    return self._answer_read_only(ask, target, tgt, kind, tc, tim)
                if getattr(p, "choices", None):
                    return self._title(tgt) + "\n" + gas_ws_ask.render_unfired(p, self.finder)
                gas_ws_ask.log_ask_miss(ask, p, source="mcp", path=self.ask_misses_path)
                try:
                    st_u = self._load()
                    st_u["last_unfired_ask"] = {"ask": ask, "id": tgt.get("id") or "", "ts": time.time()}
                    self._save(st_u)
                except Exception:
                    pass
                unfired_txt = self._title(tgt) + "\n" + gas_ws_ask.render_unfired(p, self.finder)
                # 止まった頼みを呼び出し元 AI へ切れ目なく渡す: 表の中身（最大100行×26列・値と式）を添える
                if (
                    kind == "sheet"
                    and tgt.get("id")
                    and not is_new
                    and not any("人にしか分かりません" in r for r in (p.reasons or []))
                ):
                    sn_info = self._fetch_sheet_snippet(tgt, tc, tim)
                    if sn_info and sn_info.get("text"):
                        sn_lines = []
                        if sn_info.get("note"):
                            sn_lines.append(sn_info["note"])
                        sn_lines.append("表の中身（行番号・列記号・数式つき）:\n" + sn_info["text"])
                        sn_lines.append("※消す・上書きの棚には ok=True を勝手に付けず、ユーザー確認を取ってください。")
                        unfired_txt += "\n" + "\n".join(sn_lines)
                if not any("人にしか分かりません" in r for r in (p.reasons or [])):
                    unfired_txt += ("\n次の手: 棚当てでは撃てなかった＝ここからは AI の番。頼みを、棚が確かに撃てる単純な手に割って"
                                    " ops を組む（列名・値・範囲は表の実物から・札は ws_find・棚に無ければ api）。"
                                    "sheet を名指しして ws_do(ops=…) で撃ち、返事の検算・前→後を読んでから報告する")
                return unfired_txt
            # 消す・値を変える棚で、人の判断が要る空白（姓と名の間などセル内の空白）がある場合の確かめ
            if (
                not ok
                and kind == "sheet"
                and not is_new
                and any(isinstance(o, dict) and o.get("shelf") == "seiri" and o.get("trim") is not False and not o.get("trim_inner") for o in p.ops)
                and re.search(r"空白|スペース", ask)
                and not re.search(r"前後|先頭|末尾|両端|トリム", ask)
            ):
                try:
                    import gas_ws_direct
                    light = gas_ws_direct.fetch_sheet_snapshot_light(self, st, tgt.get("id"), cur_sh, "A1:Z40")
                    if light and light.get("table"):
                        ltb = light["table"]
                        dr_m = re.fullmatch(r"(\d+)-(\d+)", str(ltb.get("data") or ""))
                        if dr_m:
                            r_a, r_b = int(dr_m.group(1)), int(dr_m.group(2))
                            ent_l = light["snap"].sheet(cur_sh)
                            inner_hits = []
                            for rr in range(r_a, r_b + 1):
                                for col_i in (ltb.get("columns") or []):
                                    c_num = gas_ws_direct.col_num(col_i["col"])
                                    txt = gas_ws_direct.Snapshot.value_text((ent_l.get("cells") or {}).get((rr, c_num)))
                                    if txt and not re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}", txt):
                                        trimmed = txt.strip(" \t　")
                                        if re.search(r"[ \t　]", trimmed):
                                            inner_hits.append(f"{col_i['col']}{rr}「{trimmed}」")
                                            break
                                if inner_hits:
                                    break
                            if inner_hits:
                                return (
                                    f"{self._title(tgt)}\n"
                                    f"確認: セル内の空白（例: {inner_hits[0]} の途中の空白）も消しますか？それとも前後の空白だけ消しますか？\n"
                                    "何も変えていません。\n"
                                    '1. 前後の空白だけ消す → ws_do(ops=\'[{"shelf":"seiri","trim":true}]\', ok=True)\n'
                                    '2. 中の空白もすべて消す → ws_do(ops=\'[{"shelf":"seiri","trim_inner":true}]\', ok=True)'
                                )
                except Exception:
                    pass
            # dedupe(cols=...) でキー列は同じだが他列が異なる行がある場合の確かめ
            if (
                not ok
                and kind == "sheet"
                and not is_new
                and any(isinstance(o, dict) and o.get("shelf") == "dedupe" and o.get("cols") for o in p.ops)
            ):
                try:
                    import gas_ws_direct
                    d_op = next(o for o in p.ops if isinstance(o, dict) and o.get("shelf") == "dedupe" and o.get("cols"))
                    d_cols = d_op["cols"] if isinstance(d_op["cols"], list) else [d_op["cols"]]
                    light = gas_ws_direct.fetch_sheet_snapshot_light(self, st, tgt.get("id"), cur_sh, "A1:Z60")
                    if light and light.get("table"):
                        ltb = light["table"]
                        dr_m = re.fullmatch(r"(\d+)-(\d+)", str(ltb.get("data") or ""))
                        if dr_m:
                            r_a, r_b = int(dr_m.group(1)), int(dr_m.group(2))
                            ent_l = light["snap"].sheet(cur_sh)
                            cells_l = ent_l.get("cells") or {}
                            key_cis = [gas_ws_direct.DirectRunner._col_of(ltb, c) for c in d_cols]
                            all_cis = [gas_ws_direct.col_num(c["col"]) for c in (ltb.get("columns") or [])]
                            other_cis = [c for c in all_cis if c not in key_cis]
                            seen_k = {}
                            diff_hits = []
                            for rr in range(r_a, r_b + 1):
                                kv = tuple(gas_ws_direct.Snapshot.value_text(cells_l.get((rr, ci))) for ci in key_cis)
                                if not any(kv):
                                    continue
                                ov = tuple(gas_ws_direct.Snapshot.value_text(cells_l.get((rr, ci))) for ci in other_cis)
                                if kv in seen_k:
                                    first_r, first_ov = seen_k[kv]
                                    if ov != first_ov:
                                        diff_hits.append((rr, first_r, "/".join(kv)))
                                else:
                                    seen_k[kv] = (rr, ov)
                            if diff_hits:
                                rr_d, fr_d, k_disp = diff_hits[0]
                                ops_s = json.dumps([dict(d_op, ok=True)], ensure_ascii=False, separators=(",", ":"))
                                return (
                                    f"{self._title(tgt)}\n"
                                    f"確認: キー列（{'・'.join(str(x) for x in d_cols)}＝「{k_disp}」）が同じでも、"
                                    f"他の列の値が異なる行があります（{fr_d}行目 と {rr_d}行目"
                                    + (f" ほか{len(diff_hits) - 1}件" if len(diff_hits) > 1 else "")
                                    + "）。削除してよろしいですか？\n"
                                    "何も変えていません。\n"
                                    f"削除する場合 → ws_do(ops='{ops_s}', ok=True)"
                                )
                except Exception:
                    pass
            # 絞り込み（絞る分類で equals/value を持つ棚）で完全一致 0 件になる場合は、実際の列値と突き合わせて補正または候補を返す
            if kind == "sheet" and not is_new and any(
                isinstance(o, dict) and (self.catalog.by_name.get(o.get("shelf")) or {}).get("cat") == "絞る"
                and (o.get("equals") is not None or o.get("value") is not None)
                for o in p.ops
            ):
                try:
                    import gas_ws_direct
                    light = gas_ws_direct.fetch_sheet_snapshot_light(self, st, tgt.get("id"), cur_sh, "A1:Z60")
                    if light and light.get("table"):
                        ltb = light["table"]
                        dr_m = re.fullmatch(r"(\d+)-(\d+)", str(ltb.get("data") or ""))
                        if dr_m:
                            r_a, r_b = int(dr_m.group(1)), int(dr_m.group(2))
                            ent_l = light["snap"].sheet(cur_sh)
                            cells_l = ent_l.get("cells") or {}
                            for f_op in p.ops:
                                if not isinstance(f_op, dict) or (self.catalog.by_name.get(f_op.get("shelf")) or {}).get("cat") != "絞る":
                                    continue
                                f_when = str(f_op.get("when") or "eq").lower()
                                f_val = f_op.get("equals") if f_op.get("equals") is not None else f_op.get("value")
                                if f_when not in ("eq", "ne") or f_val is None or not f_op.get("col"):
                                    continue
                                f_val_s = str(f_val).strip()
                                f_ci = None
                                for c_inf in (ltb.get("columns") or []):
                                    if str(c_inf.get("name") or "").strip() == str(f_op["col"]).strip() or str(c_inf.get("col") or "").strip().upper() == str(f_op["col"]).strip().upper():
                                        f_ci = gas_ws_direct.col_num(c_inf["col"])
                                        break
                                if not f_ci:
                                    continue
                                col_vals = []
                                for rr in range(r_a, r_b + 1):
                                    tv = gas_ws_direct.Snapshot.display_text(cells_l.get((rr, f_ci))).strip()
                                    if tv and tv not in col_vals:
                                        col_vals.append(tv)
                                if col_vals and f_val_s not in col_vals:
                                    cands = [cv for cv in col_vals if f_val_s in cv or cv in f_val_s]
                                    if len(cands) == 1:
                                        if f_op.get("equals") is not None:
                                            f_op["equals"] = cands[0]
                                        else:
                                            f_op["value"] = cands[0]
                                    else:
                                        show_cands = "・".join((cands or col_vals)[:8])
                                        return (
                                            f"{self._title(tgt)}\n"
                                            f"確認: 「{f_op['col']}」列に「{f_val_s}」と完全一致する行がありません（0件になります）。\n"
                                            f"この列にある値: {show_cands}\n"
                                            "どの値で絞り込むか指定してください（まだシートは変更していません）。"
                                        )
                except Exception:
                    pass
            # 先撃ちの中で、棚で直せる汚れも同じ呼び出しで直す（Excel マネージャーの seiri の autofix の写し・11/27）。
            # 汚れを AI の宿題として返さず、道具がその場で直して前→後に出す。直すのは値の意味を変えない 2 つだけ:
            #   数の列の「12,000円」のような文字の数 → 数値 ／ 文字の前後の空白（「佐藤 」）→ 取る
            # 人の判断が要る物（重複・どちらが正しいか）は直さず「残り」に出る。控えは頼みの手と 1 つ（ws_undo 1 回で両方戻る）
            autofix_notes = []
            if kind == "sheet" and not is_new and not any(isinstance(o, dict) and o.get("shelf") == "seiri" and not o.get("col") for o in p.ops):
                try:
                    p.ops, autofix_notes = self._autofix_ops(st, tgt, cur_sh, p.ops)
                except Exception:
                    autofix_notes = []
            # 表の形（値・シート構成）を変えない棚だけのときは、撃つ前の形の確かめ（expect）と撃った後の読み直し（want_table）を省く。
            # 形は変わらないので覚えた形をそのまま使える。場所（見出し・列・タイトル）はエンジンがその場で解決する（約 1 秒の短縮）
            keeps_shape = kind == "sheet" and not is_new and all(self._keeps_shape(o) for o in p.ops)
            extra = {} if keeps_shape else {"want_table": True}
            if table and kind == "sheet" and not is_new and not keeps_shape:
                extra["expect"] = table
            st2, res, key = self._do_res(p.ops, target, ok, tim, extra)
            if res.get("stale") and attempt == 0:
                t = res.get("target") or tgt
                if t.get("sheet") and (st2.get("target") or {}).get("id") == t.get("id"):
                    st2["target"]["sheet"] = t["sheet"]     # 覚えていたシートが消えていたら、エンジンが見た先頭のシートに替える
                self._remember_table(st2, t, res.get("table"), res.get("sheets"))
                self._save(st2)
                tc = self._cached_table(st2, t)
                tgt, fresh = dict(t), True
                continue
            break
        text = self._finish_do(st2, res, key)
        if res.get("ok") and st2.pop("last_unfired_ask", None) is not None:
            self._save(st2)
        shown = ", ".join(o["shelf"] + "(" + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in o.items() if k != "shelf") + ")" for o in p.ops)
        if not res.get("ok"):
            return text + "\n撃った棚: " + shown
        tgt_out = res.get("target") or res.get("created") or {}
        ch = res.get("changed") or []
        ch_text = (" ／ ".join(ch[:2]) + (f"（ほか {len(ch) - 2} 件）" if len(ch) > 2 else "")) if ch else "なし"
        tail = []
        if res.get("created"):
            tail.append("新しく作りました")
        if res.get("backup"):
            tail.append(f"控え #{res['backup']}（ws_undo で戻せます）")
        elif not st2.get("backup", True) and not res.get("created") and not res.get("local_only"):
            tail.append("控えなし（backup=OFF）")
        if res.get("replayed"):
            tail.append("同じ番号の呼び直し：撃ち直さず前の結果を返しました")
        errs = [x for x in (res.get("notes") or []) if x.startswith(("新しいエラー", "式が減った", "式の値が変わった"))]
        rest = [x for x in (res.get("notes") or []) if x not in errs]
        out_lines = [
            self._title(tgt_out),
            f"直した所: {ch_text}（撃った棚: {shown}）",
        ]
        if autofix_notes:
            out_lines.append("汚れの直し（道具がその場で・頼みの手と同じ控え）: " + " ／ ".join(autofix_notes[:4])
                             + (f"（ほか {len(autofix_notes) - 4} 件）" if len(autofix_notes) > 4 else ""))
        if rest:
            out_lines.append("メモ: " + " ／ ".join(rest[:3]))
        self._enrich_do_res(st2, res, p.ops, cur_sh, keeps_shape=keeps_shape)
        diff_cells = res.get("diff_cells") or []
        verify = res.get("verify") or {"ok": True, "checks": [], "mismatch": []}
        merged_ins = res.get("insights") or []
        if diff_cells:
            out_lines.append("変更前→後: " + " ／ ".join(diff_cells))
        if verify.get("checks") and not verify.get("mismatch"):
            out_lines.append("検算: " + " ／ ".join(verify["checks"]))
        if merged_ins:
            out_lines.append("気づき: " + " ／ ".join(merged_ins[:2]))
        if tail:
            out_lines.append(" ／ ".join(tail))
        out_lines += self._rest_lines(st2, res, tgt_out.get("sheet") or cur_sh, errs, verify.get("mismatch") or [], merged_ins)
        return "\n".join(out_lines)

    _AUTOFIX_NUM_RE = re.compile(r"[¥￥$]?\s*-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\s*(?:円|個|件|本|枚|台)?")

    def _autofix_ops(self, st, tgt, sheet, ops):
        """先撃ちの頼みの手の前に、汚れを直す seiri の手（列ごと）を足す。戻り値 (ops, 番地つきの一言[])"""
        import gas_ws_direct
        light = gas_ws_direct.fetch_sheet_snapshot_light(self, st, tgt.get("id"), sheet, "A1:Z60")
        if not light or not light.get("table"):
            return ops, []
        ltb = light["table"]
        dr_m = re.fullmatch(r"(\d+)-(\d+)", str(ltb.get("data") or ""))
        if not dr_m:
            return ops, []
        r_a, r_b = int(dr_m.group(1)), int(dr_m.group(2))
        cells = (light["snap"].sheet(sheet).get("cells")) or {}
        done_cols = {str(o.get("col")) for o in ops if isinstance(o, dict) and o.get("shelf") in ("seiri", "number.fix") and o.get("col")}
        add, notes = [], []
        for c in ltb.get("columns") or []:
            col = c.get("col")
            if not col or col in done_cols or str(c.get("name") or "") in done_cols:
                continue
            ci = gas_ws_direct.col_num(col)
            trim_hit = num_hit = None
            for rr in range(r_a, r_b + 1):
                ev = ((cells.get((rr, ci)) or {}).get("effectiveValue")) or {}
                if "stringValue" not in ev:
                    continue
                sv = str(ev["stringValue"])
                core = sv.strip(" \t　")
                if not core:
                    continue
                if trim_hit is None and core != sv:
                    trim_hit = f"{col}{rr}「{sv}」の前後の空白"
                if (num_hit is None and c.get("number") and not re.match(r"0\d", core)
                        and self._AUTOFIX_NUM_RE.fullmatch(core)):
                    num_hit = f"{col}{rr}「{core}」（文字の数）→ 数値"
            if trim_hit or num_hit:
                add.append({"shelf": "seiri", "col": col, "trim": bool(trim_hit), "numbers": bool(num_hit),
                            "halfwidth": False, "dates": False, "tidy": False})
                # ok は付けない（1 本でも ok があると、頼みの消す手まで確かめなしで撃たれる＝_do_res の決まり）
                notes += [x for x in (num_hit, trim_hit) if x]
        return add + list(ops), notes

    def _rest_lines(self, st2, res, sheet, errs, mismatch, shown_ins=()):
        """先撃ち（ws_do の ask）の返事の締め＝Excel の seiri と同じ「残り」と「次の手」。
        道具が撃てた所は上に出した。ここには AI が見て決める物だけを並べ、次に何をするかを言い切る。"""
        sid = (res.get("target") or res.get("created") or {}).get("id")
        diag = (((st2.get("book_diagnosis") or {}).get(sid) or {}).get("findings")) or []
        shown = set(shown_ins or ())
        here = [d["text"] for d in diag if d.get("sheet") == sheet and d.get("text") not in shown]
        other = [d["text"] for d in diag if d.get("sheet") != sheet and d.get("text") not in shown]
        lines = ["--- 残り（ここだけ AI が見て決める） ---"]
        bad = list(errs) + [f"検算不一致: {m}" for m in mismatch]
        lines.append(("⚠ " + " ／ ".join(bad)) if bad else "エラー・検算の食い違い: なし")
        if here:
            lines.append("この表の気づき: " + " ／ ".join(here[:6]))
        if other:
            lines.append("ほかのシートの気づき: " + " ／ ".join(other[:4]))
        if bad:
            lines.append("次の手: 上の ⚠ を見て、直すか ws_undo で戻すかを決める。直すなら ws_look で見た実物から ops を組み、"
                         "sheet を名指しして撃つ。直した後に使う人へ報告する")
        elif here:
            lines.append("次の手: 頼みが「直して・整えて・きれいに・出し直して」で、この表の気づきがその頼みの中なら、"
                         "ws_look で見た実物（列の値・範囲）から ops を組み、sheet を名指しして同じシートに撃つ。"
                         "人の判断が要る物（どちらを残す・消す・どれが正しい）は撃たずに番地で聞く。"
                         "頼みの外の気づきは直さず、返事に効く物だけ番地つきで添える。"
                         "報告は何をどこに直したかを番地で 3〜5 行（検算の数を添える）")
        else:
            lines.append("次の手: なし＝これで仕上がり（先撃ちは 1 回で終える）。道具をこれ以上撃たない。"
                         "報告は何をどこに直したかを番地で 3〜5 行（検算の数を添える）")
        return lines

    def _keeps_shape(self, op):
        """表の形を変えない棚か（触る に 値・シート構成 が無い。触る が引数で変わる api は変えるものとして扱う）"""
        s = self.catalog.by_name.get(op.get("shelf"))
        if not s or op.get("shelf") == "api":
            return False
        return not ({"値", "シート構成"} & set(s.get("touch") or []))

    @staticmethod
    def format_read_only_snippet(values, formulas=None, total_rows=None, start_row=1, start_col=1, max_rows=100, head_rows=80, tail_rows=20, max_cols=26):
        """読むだけモード用: 表の中身を行番号・列記号・数式つきテキストへ整形（上限 100 行×26 列・超過時は先頭80＋末尾20抜粋）。"""
        import gas_ws_direct
        rows = values or []
        fms = formulas or []
        n_rows = len(rows)
        actual_total = max(n_rows, int(total_rows or 0))
        truncated = actual_total > max_rows
        if n_rows > max_rows:
            picked_idx = list(range(head_rows)) + [-1] + list(range(n_rows - tail_rows, n_rows))
        else:
            picked_idx = list(range(n_rows))
        lines = []
        for idx in picked_idx:
            if idx < 0:
                lines.append(f"...（中略: 全 {actual_total} 行のうち先頭 {head_rows} 行＋末尾 {tail_rows} 行を抜粋）...")
                continue
            r_no = start_row + idx
            row = rows[idx] or []
            fm_row = fms[idx] if idx < len(fms) and isinstance(fms[idx], list) else []
            parts = []
            for j in range(min(len(row), max_cols)):
                v = row[j]
                f = fm_row[j] if j < len(fm_row) else ""
                vs = "" if v is None else str(v)
                fs = "" if f is None else str(f)
                if vs == "" and fs == "":
                    continue
                col_l = gas_ws_direct.col_letter(start_col + j)
                parts.append(f"{col_l}={vs}{' {' + fs + '}' if fs else ''}")
            lines.append(f"R{r_no}: " + (" | ".join(parts) if parts else "(空行)"))
        note = f"※全 {actual_total} 行のうち抜粋（先頭{head_rows}行＋末尾{tail_rows}行）で読みました" if truncated else ""
        return {"text": "\n".join(lines), "truncated": truncated, "total_rows": actual_total, "note": note}

    def _fetch_sheet_snippet(self, tgt, tc, tim):
        """表の中身（最大100行×26列・値と式・超えたら先頭80＋末尾20抜粋）を1往復で取得する。失敗時は None。"""
        if not tgt or not tgt.get("id"):
            return None
        try:
            import gas_ws_direct
            st = self._load()
            cur = st.get("target") or {}
            body_target = {k: v for k, v in tgt.items() if k in ("id", "kind")}
            want_sheet = tgt.get("sheet") or (tc or {}).get("sheet") or (cur.get("sheet") if cur.get("id") == tgt.get("id") else "")
            tb = (tc or {}).get("table")
            r_end, c_end = 100, 26
            if tb and not tb.get("none"):
                try:
                    c_end = min(26, max(1, gas_ws_direct.col_num(tb.get("last_col") or "Z")))
                except Exception:
                    c_end = 26
                data_last = 0
                m_d = re.fullmatch(r"([0-9]+)-([0-9]+)", str(tb.get("data") or ""))
                if m_d:
                    data_last = int(m_d.group(2))
                r_end = max(int(tb.get("total_row") or 0), data_last, int(tb.get("header_row") or 1))
            fetch_rows = min(max(r_end, 1), 2000)
            rng_str = f"A1:{gas_ws_direct.col_letter(c_end)}{fetch_rows}"
            res = None
            if not st.get("direct_off") and (st.get("direct_token") or {}).get("token"):
                res = gas_ws_direct.DirectRunner(self).look(st, body_target, sheet=want_sheet, range_str=rng_str)
            if res is None and st.get("engine_url"):
                res = self._post({"action": "look", "target": body_target, "sheet": want_sheet, "range": rng_str})
            if not res or not res.get("ok"):
                return None
            tim.lap("表の中身")
            t_out = res.get("target") or tgt
            sh_rows = 0
            for s_info in res.get("sheets") or []:
                if s_info.get("name") == t_out.get("sheet"):
                    sh_rows = int(s_info.get("rows") or 0)
                    break
            snip = self.format_read_only_snippet(
                res.get("values") or [],
                formulas=res.get("formulas") or [],
                total_rows=max(sh_rows, len(res.get("values") or [])),
            )
            snip["target"] = t_out
            snip["table"] = res.get("table")
            return snip
        except Exception:
            return None

    def _answer_read_only(self, ask, target, tgt, kind, tc, tim):
        """シートを変えない「読むだけ」の問いに対し、棚を撃たず表の中身（上限100行×26列）を1往復で返す。"""
        if kind != "sheet" or not tgt.get("id"):
            look_txt = self._look(target=target)
            return "[読むだけ] シート・文書は変更していません。以下の内容から質問に答えてください。\n" + look_txt
        snip = self._fetch_sheet_snippet(tgt, tc, tim)
        if not snip:
            # 直接トークンもエンジンURLも無い場合は従来の _post でエラーを出す
            import gas_ws_direct
            st = self._load()
            cur = st.get("target") or {}
            body_target = {k: v for k, v in tgt.items() if k in ("id", "kind")}
            want_sheet = tgt.get("sheet") or (tc or {}).get("sheet") or (cur.get("sheet") if cur.get("id") == tgt.get("id") else "")
            res = self._post({"action": "look", "target": body_target, "sheet": want_sheet, "range": "A1:Z100"})
            if not res or not res.get("ok"):
                raise WorkspaceError((res or {}).get("error") or "シートの中身を読めませんでした")
            t_out = res.get("target") or tgt
            tb_now = res.get("table")
            snip = self.format_read_only_snippet(res.get("values") or [], formulas=res.get("formulas") or [])
            snip["target"] = t_out
            snip["table"] = tb_now
        t_out = snip.get("target") or tgt
        tb_now = snip.get("table")
        # 読むだけ・チェック依頼でも初回ブック健診（または変更後の再健診）を実行・記憶し、他シートを含む要点を添える
        diag_findings = []
        try:
            st_ro = self._load()
            sid_ro = t_out.get("id") or tgt.get("id")
            if sid_ro and not st_ro.get("direct_off"):
                diag_map = st_ro.setdefault("book_diagnosis", {})
                import gas_ws_insights
                if sid_ro not in diag_map or (diag_map.get(sid_ro) or {}).get("stale") or (diag_map.get(sid_ro) or {}).get("ver") != gas_ws_insights.DIAG_VERSION:
                    import gas_ws_direct
                    sh_names = (tc or {}).get("sheets") or []
                    payload = gas_ws_direct.fetch_workbook_payload_for_diagnosis(self, st_ro, sid_ro, sheet_names=sh_names or None)
                    if payload:
                        findings = gas_ws_insights.diagnose_workbook(payload)
                        diag_map[sid_ro] = {"findings": findings, "ts": time.time(), "stale": False, "ver": gas_ws_insights.DIAG_VERSION}
                        self._save(st_ro)
                diag_findings = ((diag_map.get(sid_ro) or {}).get("findings") or [])[:8]
        except Exception:
            diag_findings = []
        lines = [
            f"[読むだけ] {self._title(t_out)}（シートは変更していません）",
            f"質問: {ask}",
        ]
        if tb_now:
            hr1 = tb_now["header_row"]
            hrs = int(tb_now.get("header_rows") or 1)
            hr_label = f"{hr1}-{hr1 + hrs - 1}" if hrs > 1 else f"{hr1}"
            lines.append(
                f"表: 見出し {hr1 if hrs == 1 else hr_label} 行目・{tb_now['first_col']}〜{tb_now['last_col']} 列・明細 {tb_now['data']} 行目"
                + (f"・合計行 {tb_now['total_row']} 行目" if tb_now.get("total_row") else "・合計行なし")
            )
            lines.append("列: " + "、".join(f"{c['col']}={c['name']}{'(数値)' if c['number'] else ''}" for c in tb_now["columns"]))
        if snip["note"]:
            lines.append(snip["note"])
        if snip["text"]:
            lines.append("中身（行番号・列記号・数式つき）:\n" + snip["text"])
        if diag_findings:
            lines.append("ブック全体の健診結果（重要度順）:")
            for df in diag_findings:
                lines.append("- " + df["text"])
        lines.append("上の表の中身と根拠セル・健診結果をもとに、シートを変更せずそのまま答えてください。")
        return "\n".join(lines)

    def _enrich_do_res(self, st2, res, ops, cur_sh, keeps_shape=False):
        """ws_do(ask/ops) 共通で検算・変更前→後差分・健診のずれ持ち越しを res に付与する。"""
        if not res.get("ok") or res.get("local_only"):
            return
        tgt_out = res.get("target") or res.get("created") or {}
        sid_out = tgt_out.get("id")
        sh_for_ins = tgt_out.get("sheet") or cur_sh
        kind_out = tgt_out.get("kind") or "sheet"
        if kind_out != "sheet" or not sid_out:
            return
        insights = res.get("insights")
        diff_cells = [] if keeps_shape else list(res.get("diff_cells") or [])
        verify = res.get("verify") or {"ok": True, "checks": [], "mismatch": []}
        if not st2.get("direct_off"):
            need_light = (insights is None) or (not keeps_shape and not res.get("direct"))
            if need_light:
                try:
                    import gas_ws_direct, gas_ws_insights
                    light = gas_ws_direct.fetch_sheet_snapshot_light(self, st2, sid_out, sh_for_ins, "A1:Z60")
                    if light:
                        if insights is None:
                            insights = gas_ws_insights.analyze_from_snapshot(light["snap"], sh_for_ins, light["table"], ops=ops)
                        v_grid, f_grid, a_map = gas_ws_direct.snapshot_to_grids(light["snap"], sh_for_ins, light["table"])
                        if not keeps_shape:
                            b_map = self._load_sheet_vals(st2, sid_out, sh_for_ins)
                            bnd = self._sheet_vals_bounds(st2, sid_out, sh_for_ins)
                            if b_map and not diff_cells and res.get("changed"):
                                a_cmp = a_map if not bnd else {k: v for k, v in a_map.items()
                                                               if bnd[0] <= k[0] <= bnd[2] and bnd[1] <= k[1] <= bnd[3]}
                                diff_cells = gas_ws_insights.diff_cell_values(b_map, a_cmp)
                            self._save_sheet_vals(st2, sid_out, sh_for_ins, a_map, bounds=(1, 1, 60, 26))
                            if not verify.get("checks") and not verify.get("mismatch"):
                                verify = gas_ws_insights.verify_after_do(
                                    light["table"],
                                    v_grid,
                                    f_grid,
                                    ops=ops,
                                    before_map=(b_map if res.get("changed") else None),
                                    after_map=(a_map if res.get("changed") else None),
                                )
                except Exception:
                    insights = insights or []
            # Direct/Engine 問わず、値・行が変わる手を撃った後はブック健診を最新化対象にする
            if not keeps_shape and res.get("changed"):
                if (st2.get("book_diagnosis") or {}).get(sid_out):
                    st2["book_diagnosis"][sid_out]["stale"] = True
                if res.get("direct"):
                    try:
                        import gas_ws_direct
                        light_d = gas_ws_direct.fetch_sheet_snapshot_light(self, st2, sid_out, sh_for_ins, "A1:Z60")
                        if light_d:
                            _, _, a_map_d = gas_ws_direct.snapshot_to_grids(light_d["snap"], sh_for_ins, light_d["table"])
                            self._save_sheet_vals(st2, sid_out, sh_for_ins, a_map_d, bounds=(1, 1, 60, 26))
                    except Exception:
                        pass
        diag_entry = (st2.get("book_diagnosis") or {}).get(sid_out) or {}
        import gas_ws_insights as _gwi
        if (diag_entry.get("stale") or (diag_entry and diag_entry.get("ver") != _gwi.DIAG_VERSION)) and not st2.get("direct_off") and sid_out:
            try:
                import gas_ws_direct, gas_ws_insights
                tc_now = self._cached_table(st2, tgt_out) or {}
                sh_names_d = tc_now.get("sheets") or []
                payload_d = gas_ws_direct.fetch_workbook_payload_for_diagnosis(self, st2, sid_out, sheet_names=sh_names_d or None)
                if payload_d:
                    diag_entry["findings"] = gas_ws_insights.diagnose_workbook(payload_d)
                    diag_entry["stale"] = False
                    diag_entry["ver"] = gas_ws_insights.DIAG_VERSION
                    diag_entry["ts"] = time.time()
            except Exception:
                pass
        diag_all = diag_entry.get("findings") or []
        sticky_insights = []
        if diag_all:
            op_cats = {(self.catalog.by_name.get(o.get("shelf")) or {}).get("cat") for o in (ops or []) if isinstance(o, dict)}
            want_tags = set()
            if op_cats & {"集計", "計算"}:
                want_tags.update({"cross_sheet_mismatch", "key_whitespace_split", "status_in_total", "note_contradiction", "calc_mismatch", "period_structure", "blank_col"})
            elif "絞る" in op_cats:
                want_tags.add("sum_subtotal")
            elif any(isinstance(o, dict) and o.get("shelf") == "dedupe" for o in (ops or [])):
                want_tags.add("key_dup_diff")
            if want_tags:
                sticky_insights = [
                    d["text"] for d in diag_all
                    if d.get("tag") in want_tags and (d.get("sheet") == sh_for_ins or d.get("tag") == "cross_sheet_mismatch")
                ][:2]
        filtered_ins = self._filter_new_insights(st2, sid_out, sh_for_ins, insights) if insights else []
        merged_ins = list(dict.fromkeys(sticky_insights + filtered_ins))
        res["diff_cells"] = diff_cells
        res["verify"] = verify
        res["insights"] = merged_ins[:2]
        self._save(st2)

    def _do(self, ops, target, ok, tim):
        st, res, key = self._do_res(ops, target, ok, tim)
        if res.get("ok") and not res.get("local_only"):
            parsed_ops = self.parse_ops(ops)
            keeps_shape = all(self._keeps_shape(o) for o in parsed_ops if isinstance(o, dict))
            cur_sh = ((res.get("target") or {}).get("sheet")) or ((st.get("target") or {}).get("sheet")) or ""
            self._enrich_do_res(st, res, parsed_ops, cur_sh, keeps_shape=keeps_shape)
            lu = st.get("last_unfired_ask")
            if isinstance(lu, dict) and lu.get("ask") and (time.time() - float(lu.get("ts") or 0)) <= 300:
                tid = (res.get("target") or res.get("created") or {}).get("id") or ""
                if not lu.get("id") or not tid or lu.get("id") == tid:
                    try:
                        import gas_ws_ask
                        gas_ws_ask.log_ask_ai_solved(lu["ask"], parsed_ops, source="mcp_ai", path=self.ask_misses_path)
                    except Exception:
                        pass
                    st.pop("last_unfired_ask", None)
        return self._finish_do(st, res, key)

    def _do_res(self, ops, target, ok, tim, extra=None):
        ops = self.parse_ops(ops)
        if any(isinstance(o, dict) and o.get("ok") is True for o in ops):
            ok = True
        ops = [{k: v for k, v in o.items() if k != "ok"} if isinstance(o, dict) and "ok" in o else o for o in ops]
        kind = self.validate_ops(ops)
        ops = [self.catalog.normalize_op(o) for o in ops]   # 列[]・行[] に 1 つだけ渡された値を配列にそろえる
        tim.lap("検査")
        st = self._load()
        local_ops = [o for o in ops if o["shelf"] in gas_ws_catalog.LOCAL_HANDLERS]
        remote_ops = [o for o in ops if o["shelf"] not in gas_ws_catalog.LOCAL_HANDLERS]
        pre_msgs, pending_local = [], []
        for o in local_ops:
            msg = gas_ws_catalog.LOCAL_HANDLERS[o["shelf"]](st, o, mgr=self, target=target, phase="pre")
            if msg is None:
                pending_local.append(o)
            else:
                pre_msgs.append(msg)
        if pre_msgs:
            self._save(st)
        if not remote_ops:
            tgt_out = dict(st.get("target") or {})
            if pending_local:
                tgt_out, _ = self.resolve_target(target, None, st)
                for o in pending_local:
                    msg = gas_ws_catalog.LOCAL_HANDLERS[o["shelf"]](
                        st, o, mgr=self, target=target, target_id=tgt_out.get("id"), phase="post"
                    )
                    if msg:
                        pre_msgs.append(msg)
            return st, {"ok": True, "target": tgt_out, "changed": pre_msgs, "notes": [], "remaining": [], "backup": 0, "local_only": True}, None
        backup = bool(st.get("backup", True))   # 既定は控えを取る（README・WORKSPACE.md の約束）。「バックアップ取らなくていい」で以後ずっと切れる
        need_tgt = bool((target or "").strip()) or self._ops_need_target(remote_ops)
        if need_tgt:
            tgt, is_new = self.resolve_target(target, kind, st)
            if tgt.get("_window_title"):
                st["last_window_title"] = tgt["_window_title"]
            elif (target or "").strip() and (target or "").strip().lower() not in BROWSER_TARGET_ALIASES:
                st["target_set_at"] = time.time()
            tim.lap("相手")
            if tgt.get("kind") and tgt["kind"] != kind:
                raise WorkspaceError("今の相手は" + ("文書" if tgt["kind"] == "doc" else "スプレッドシート")
                                     + "ですが、頼みの棚は" + ("文書" if kind == "doc" else "シート") + "用です。target を替えてください。")
            # やり直しは 3 回まで（同じ相手での失敗が続いたとき）
            key = tgt.get("id") or tgt.get("new")
            fails = st.get("fails") or {}
            if not is_new and fails.get(key, 0) >= RETRY_MAX:
                raise WorkspaceError(f"同じ相手（{tgt.get('name') or key}）で {RETRY_MAX} 回続けて通りませんでした。ここで止めます。"
                                     "頼み方を変えるか、人の判断が要ります（ws_look で今の様子を見る・ws_undo list で控えを見る）。")
            sheet = tgt.get("sheet") or ((st.get("target") or {}).get("sheet") if (st.get("target") or {}).get("id") == tgt.get("id") else "")
            body_target = {k: v for k, v in tgt.items() if k in ("id", "kind", "new", "folder", "name")}
            if is_new and not body_target.get("folder") and st.get("default_folder", {}).get("id"):
                body_target["folder_id"] = st["default_folder"]["id"]
            if sheet:
                body_target["sheet"] = sheet
        else:
            tgt, is_new, key = {}, False, ""
            tim.lap("相手")
            body_target = {"no_file": True}
        # 直接の道（Sheets API をエンジンの鍵で直接叩く。右の枠と同じ道）。戻しまで作れる棚だけ。乗らなければ下のエンジンの道
        if need_tgt and not is_new and not pending_local and not os.environ.get("WS_NO_DIRECT"):
            import gas_ws_direct
            cur = st.get("target") or {}
            dt = dict(tgt, kind=tgt.get("kind") or kind, sheet=sheet)
            if cur.get("id") == dt.get("id"):
                for k in ("name", "url"):
                    dt.setdefault(k, cur.get(k))
            dres = gas_ws_direct.DirectRunner(self).try_do(st, dt, remote_ops, tim)
            if dres is not None:
                for o in reversed(remote_ops):
                    sc = next(({k: o[k]} for k in ("header", "title", "col", "range") if o.get(k) not in (None, "", [])), None)
                    if sc:
                        dres["_last_scope"] = sc
                        break
                tim.last = time.perf_counter()
                return st, dres, key
            self._save(st)          # 鍵・乗らなかった理由を残す
        # 呼び直しで二重にならない番号：時間切れで終わった同じ頼みは同じ番号で撃つ
        if extra or not backup:
            h = _digest(body_target, remote_ops, bool(ok), extra, bool(backup))
        else:
            h = _digest(body_target, remote_ops, bool(ok))
        pend = st.get("pending") or {}
        call_id = pend["call_id"] if pend.get("hash") == h else uuid.uuid4().hex
        st["pending"] = {"hash": h, "call_id": call_id}
        self._save(st)
        tim.lap("状態")
        body = {"action": "do", "call_id": call_id, "target": body_target, "ops": remote_ops, "ok": bool(ok), "backup": bool(backup)}
        body.update(extra or {})
        try:
            res = self._post(body)
        except WorkspaceAuthNeeded:
            st0 = self._load()
            if st0.pop("pending", None) is not None:
                self._save(st0)
            raise
        post_msgs = []
        if res.get("ok"):
            gas_ws_api.log_uses(remote_ops, self.api_uses_path)       # 撃った api の型と頼みの 1 行（棚に上げる候補の材料）
            for o in reversed(remote_ops):
                sc = next(({k: o[k]} for k in ("header", "title", "col", "range") if o.get(k) not in (None, "", [])), None)
                if sc:
                    res["_last_scope"] = sc
                    break
            tid = (res.get("created") or res.get("target") or {}).get("id") or tgt.get("id")
            for o in pending_local:
                msg = gas_ws_catalog.LOCAL_HANDLERS[o["shelf"]](
                    st, o, mgr=self, target=target, target_id=tid, phase="post"
                )
                if msg:
                    post_msgs.append(msg)
            if pre_msgs or post_msgs:
                res["changed"] = pre_msgs + (res.get("changed") or []) + post_msgs
        tim.engine = res.get("ms") or {}
        tim.last = time.perf_counter()
        st = self._load()
        st.pop("pending", None)
        if res.get("ok") and not res.get("local_only"):     # エンジンの道で書いた時刻（ws_undo がどちらの道の直しを先に戻すか決める）
            tid = (res.get("created") or res.get("target") or {}).get("id")
            if tid:
                st.setdefault("engine_last", {})[tid] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return st, res, key

    def _finish_do(self, st, res, key):
        tgt = res.get("target") or {}
        created = res.get("created")
        if created and not tgt.get("id"):
            tgt = created
        if tgt.get("id"):
            # 失敗して戻したときのシート名は、作りかけて消えたシートかもしれないので覚えない（11/12 実機で踏んだ）
            keys = ("id", "name", "kind", "url", "sheet") if res.get("ok") else ("id", "name", "kind", "url")
            st["target"] = {k: tgt[k] for k in keys if tgt.get(k)}
        df = res.get("default_folder")
        if isinstance(df, dict):
            if df.get("id") == "root" or not df.get("id"):
                st.pop("default_folder", None)
            else:
                st["default_folder"] = {"id": df["id"], "name": df.get("name", "")}
        fails = st.setdefault("fails", {})
        if res.get("ok"):
            for k in (key, tgt.get("id")):
                if k:
                    fails.pop(k, None)
        elif not res.get("blocked") and not res.get("arg"):
            nk = tgt.get("id") or key
            if nk:
                fails[nk] = fails.get(nk, 0) + 1
                res["_fail_count"] = fails[nk]
        if res.get("ok") and res.get("table") is not None:
            self._remember_table(st, res.get("target") or {}, res.get("table"), res.get("sheets"))
        if res.get("ok") and res.get("_last_scope") and tgt.get("id"):
            prev_ls = st.get("last_scope") or {}
            new_sc = dict(res["_last_scope"])
            sel_keep = ""
            if (
                prev_ls.get("id") == tgt["id"]
                and prev_ls.get("sheet", "") == tgt.get("sheet", "")
                and prev_ls.get("selection")
                and new_sc.get("range") == prev_ls.get("selection")
            ):
                new_sc = dict(prev_ls.get("scope") or new_sc)
                sel_keep = prev_ls["selection"]
            ls_entry = {"id": tgt["id"], "sheet": tgt.get("sheet", ""), "scope": new_sc}
            if sel_keep:
                ls_entry["selection"] = sel_keep
            st["last_scope"] = ls_entry
        self._save(st)
        return self.format_do(res, backup=True) if st.get("backup", True) else self.format_do(res)

    @staticmethod
    def _title(tgt):
        s = tgt.get("name") or "(名前なし)"
        if tgt.get("sheet"):
            s += " › " + tgt["sheet"]
        return "対象: " + s

    def format_do(self, res, backup=False):
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
            rest = []
            if res.get("notes"):
                rest.append("メモ: " + " ／ ".join(res["notes"][:3]))
            if res.get("remaining"):
                rest.append("残り: " + " ／ ".join(res["remaining"][:3]))
            if rest:
                lines.append("　".join(rest))
            if res.get("diff_cells"):
                lines.append("変更前→後: " + " ／ ".join(res["diff_cells"]))
            ver = res.get("verify") or {}
            if ver.get("mismatch"):
                lines.append("⚠ 検算不一致: " + " ／ ".join(ver["mismatch"]))
            elif ver.get("checks"):
                lines.append("検算: " + " ／ ".join(ver["checks"]))
            if res.get("insights"):
                lines.append("気づき: " + " ／ ".join(res["insights"][:2]))
            tail = []
            if tgt.get("url"):
                tail.append(tgt["url"])
            if res.get("created"):
                tail.insert(0, "新しく作りました")
            if res.get("backup"):
                tail.append(f"控え #{res['backup']}（ws_undo で戻せます）")
            elif not backup and not res.get("created") and not res.get("local_only"):
                tail.append("控えなし（backup=OFF）")
            if res.get("replayed"):
                tail.append("同じ番号の呼び直し：撃ち直さず前の結果を返しました")
            if tail:
                lines.append(" ／ ".join(tail))
            return "\n".join(lines[:8])
        err = res.get("error") or "不明なエラー"
        if res.get("blocked"):
            lines.append("止めました: " + err)
            lines.append("何も変えていません。消える物をユーザーに見せて確認し、ユーザーの承認の言葉があるときだけ ok=True で撃ち直してください。")
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
    def _cur_kind(self):
        return (self._load().get("target") or {}).get("kind") or ""

    def find(self, ask="", kind=""):
        """棚の札を引く（通信なし）。kind 省略時は今の相手の種類で絞る"""
        k = kind
        if not k:
            ask_s = (ask or "").strip()
            # ask が文書系を指している場合は doc、そうでなければ今の相手の種類
            if re.match(r"^分類\s*[:：]\s*文書$", ask_s) or re.match(r"^(?:棚\s*[:：]\s*)?doc\.", ask_s):
                k = "doc"
            else:
                k = self._cur_kind()
        return self.finder.ask(ask, k, log_to=self.misses_path)

    def look(self, target="", sheet="", range="", image=False, ask="", trace=""):
        if (target or "").strip().lower() in RECENT_TARGET_ALIASES:
            return self.format_recent_files()
        if str(trace or "").strip():
            return self._trace(target, sheet, trace)
        if not ask:
            return self._look_image(target, sheet, range, image)
        try:
            text = self._look_image(target, sheet, range, image)
        except WorkspaceError as e:
            # 相手が見られなくても、札は引ける（通信なし）
            raise WorkspaceError(str(e) + "\n\n" + self.find(ask))
        return text + "\n\n" + self.find(ask)

    def _trace(self, target, sheet, cell, depth=3):
        """ws_look(trace="予算!I5")＝式の木（Excel マネージャーの trace の写し）。読むだけ・今の相手は替えない"""
        import gas_ws_direct
        st = self._load()
        tgt, is_new = self.resolve_target(target, None, st)
        if is_new or not tgt.get("id"):
            raise WorkspaceError("式の木は、今あるスプレッドシートにだけ使えます。")
        c = str(cell).strip()
        if "!" in c:
            sh, a1 = c.rsplit("!", 1)
            sh = sh.strip().strip("'")
        else:
            sh, a1 = (sheet or tgt.get("sheet") or ((st.get("target") or {}).get("sheet")) or ""), c
        if not sh:
            raise WorkspaceError("どのシートのセルかを trace=\"シート名!A1\" の形で渡してください。")
        a1 = a1.replace("$", "").upper()
        if not re.fullmatch(r"[A-Z]{1,3}\d+", a1):
            raise WorkspaceError(f"trace は 1 つのセルの番地で渡してください（受け取った物: {cell}）。")
        lines = gas_ws_direct.trace(self, st, tgt["id"], sh, a1, depth=depth)
        st_now = self._load()                       # 鍵だけ持ち帰る（今の相手・覚えた表は替えない）
        if st.get("direct_token"):
            st_now["direct_token"] = st["direct_token"]
            self._save(st_now)
        return "\n".join([f"対象: {tgt.get('name') or tgt['id']}（式の木・深さ {depth}）"] + lines)

    def _look_image(self, target="", sheet="", range="", image=False):
        text = self._look(target=target, sheet=sheet, range=range)
        if not image:
            return text
        st = self._load()
        cur = st.get("target") or {}
        body = {"action": "render", "target": {"id": cur.get("id"), "kind": cur.get("kind")},
                "sheet": sheet or cur.get("sheet", ""), "range": range}
        res = self._post(body)
        if not res.get("ok"):
            return text + "\n画像: 撮れませんでした（" + str(res.get("error") or "") + "）"
        import gas_workspace_view
        png = gas_workspace_view.render_to_png(res, HERE / "screenshots")
        return text + f"\n画像: {png}（描き直した姿。グラフ・画像・プルダウンは写りません。この画像を開いて見た目を確かめる）"

    def _look(self, target="", sheet="", range=""):
        st = self._load()
        tgt, is_new = self.resolve_target(target, None, st)
        if tgt.get("_window_title"):
            st["last_window_title"] = tgt["_window_title"]
            self._save(st)
        elif (target or "").strip() and (target or "").strip().lower() not in BROWSER_TARGET_ALIASES:
            st["target_set_at"] = time.time()
            self._save(st)
        if is_new:
            raise WorkspaceError("ws_look には new: は使えません（まだ無いファイルは見られません）。")
        cur = st.get("target") or {}
        body_target = {k: v for k, v in tgt.items() if k in ("id", "kind")}
        if not body_target.get("kind"):
            meta = self._drive_meta(tgt["id"])
            body_target["kind"] = self._kind_of_mime(meta["mimeType"])
        want_sheet = sheet or tgt.get("sheet") or (cur.get("sheet") if cur.get("id") == tgt.get("id") else "")
        res = None
        if body_target.get("kind") == "sheet" and not st.get("direct_off"):
            import gas_ws_direct
            res = gas_ws_direct.DirectRunner(self).look(st, body_target, sheet=want_sheet, range_str=range)
        if res is None:
            res = self._post({"action": "look", "target": body_target, "sheet": want_sheet, "range": range})
        if not res.get("ok"):
            raise WorkspaceError(res.get("error") or "見られませんでした")
        t = res["target"]
        st_mem = st
        st = self._load()
        for k in ("direct_token", "direct_off", "direct_last_look_skip", "engine_sid", "engine_url", "engine_deploy_id", "engine_ver"):
            if k in st_mem:
                st[k] = st_mem[k]
        st["target"] = {k: t[k] for k in ("id", "name", "kind", "url", "sheet") if t.get(k)}
        if tgt.get("_window_title"):
            st["last_window_title"] = tgt["_window_title"]
        elif (target or "").strip() and (target or "").strip().lower() not in BROWSER_TARGET_ALIASES:
            st["target_set_at"] = time.time()
        if t.get("kind") == "sheet":
            self._remember_table(st, st["target"], res.get("table"), res.get("sheets"))
            sid_lk = t.get("id")
            sh_lk = t.get("sheet")
            # 現在のシートのセル値を記憶（次の ws_do での変更前→後比較用）
            if res.get("values") and sid_lk and sh_lk:
                cmap = {}
                # 読んだ範囲の左上から数える（A2:H16 を読んだのに A1 から数えると、次の ws_do の前→後が 1 行ずれて
                # 変わっていないセルまで「変更」と出た・11/27 撃ち直し 3 の #9）
                r0, c0 = _range_origin(range)
                for r_i, row in enumerate(res["values"], r0):
                    for c_i, val in enumerate(row, c0):
                        if str(val or "") != "":
                            cmap[(r_i, c_i)] = str(val)
                n_c = max((len(r) for r in res["values"]), default=1)
                self._save_sheet_vals(st, sid_lk, sh_lk, cmap,
                                      bounds=(r0, c0, r0 + len(res["values"]) - 1, c0 + n_c - 1))
            try:
                import gas_ws_insights
                ins = []
                # 初回ブック健診（全シート総当たり・1回だけ実行して記憶。stale なら再実行）
                diag_map = st.setdefault("book_diagnosis", {})
                if sid_lk and (sid_lk not in diag_map or (diag_map.get(sid_lk) or {}).get("stale") or (diag_map.get(sid_lk) or {}).get("ver") != gas_ws_insights.DIAG_VERSION) and not st.get("direct_off"):
                    import gas_ws_direct
                    t0 = time.perf_counter()
                    sh_names = [s.get("name") for s in (res.get("sheets") or []) if s.get("name")]
                    payload = gas_ws_direct.fetch_workbook_payload_for_diagnosis(self, st, sid_lk, sheet_names=sh_names)
                    if payload:
                        findings = gas_ws_insights.diagnose_workbook(payload)
                        diag_map[sid_lk] = {
                            "findings": findings,
                            "ts": time.time(),
                            "elapsed": round(time.perf_counter() - t0, 2),
                            "stale": False,
                            "ver": gas_ws_insights.DIAG_VERSION,
                        }
                        if len(diag_map) > 5:
                            for old_sid in list(diag_map.keys())[:-5]:
                                diag_map.pop(old_sid, None)
                        ins.extend(f["text"] for f in findings[:8])
                elif sid_lk and sid_lk in diag_map:
                    # ws_look は AI の材料＝毎回ブック全体の健診を重要度の順に渡す（一度伝えた物も省かない。省くのは ws_do の返事だけ）
                    ins.extend(d["text"] for d in (diag_map[sid_lk].get("findings") or [])[:8])
                if not ins:
                    ins = gas_ws_insights.analyze_from_look_res(res)
                if ins:
                    res["insights"] = ins
            except Exception:
                pass
        self._save(st)
        out = self.format_look(res)
        if t.get("kind") == "sheet" and self.browser_active_path.exists():
            ext = self._detect_from_extension()
            if ext and ext.get("id") == t.get("id") and ext.get("selection"):
                if not ext.get("sheet") or ext.get("sheet") == t.get("sheet"):
                    out += f"\n選択セル: {ext['selection']}"
        return out

    @staticmethod
    def format_look(res):
        t = res["target"]
        lines = [WorkspaceManager._title(t), "URL: " + t.get("url", "")]
        if t["kind"] == "sheet":
            lines.append("シート: " + "、".join(f"{s['name']}（{s['rows']}行×{s['cols']}列）" for s in res.get("sheets", [])))
            tb = res.get("table")
            if tb:
                d = tb["data"].split("-")
                hr1 = tb["header_row"]
                hrs = int(tb.get("header_rows") or 1)
                hr_label = f"{hr1}-{hr1 + hrs - 1}" if hrs > 1 else f"{hr1}"
                lines.append(f"表: 見出し {hr_label} 行目・{tb['first_col']}〜{tb['last_col']} 列・明細 {tb['data']} 行目" + (f"・合計行 {tb['total_row']} 行目" if tb.get("total_row") else "・合計行なし"))
                lines.append("列: " + "、".join(f"{c['col']}={c['name']}{'(数値)' if c['number'] else ''}" for c in tb["columns"]))
            else:
                lines.append("表: 見つかりません（空のシート、または見出しの行がありません）")
            for ln in res.get("side") or []:      # 脇の状態（入力規則・交互の色・保護・フィルタ・隠し・グループ・名前付き範囲・グラフ）。あるときだけ 1 行ずつ
                lines.append(ln)
            if res.get("values"):
                lines.append(f"中身 {res['range']}:")
                fm = res.get("formulas") or []
                for i, row in enumerate(res["values"][:60]):
                    cells = []
                    for j, v in enumerate(row):
                        f = fm[i][j] if i < len(fm) and j < len(fm[i]) else ""
                        cells.append(f"{v}{'  {' + f + '}' if f else ''}")
                    lines.append("\t".join(cells))
            if res.get("insights"):
                lines.append("気づき:")
                for ins in res["insights"][:8]:
                    lines.append("- " + ins)
        else:
            lines.append(f"段落数 {res.get('paragraphs')}・見出し: " + (" / ".join(f"{h['no']}:{'#' * h['level']}{h['text']}" for h in res.get("headings", [])) or "なし"))
            lines.extend(res.get("outline", []))
        return "\n".join(lines)

    # ------------------------------------------------------------ ws_undo
    def undo(self, to="", list=False, ok=False):
        import gas_ws_direct
        if list:
            res = self._post({"action": "list"})
            items = res.get("ledger") or []
            st0 = self._load()
            rows = [(it["time"][:16], f"#{it['n']} {it['time'][5:16]} {it['target']} {it['what']}" + ("（戻し済み）" if it.get("undone") else "")) for it in items[:15]]
            rows += [(it["time"][:16], f"#D{it['n']} {it['time'][5:16]} {it.get('name') or it['id']} {it['what']}" + ("（戻し済み）" if it.get("undone") else ""))
                     for it in (st0.get("direct_ledger") or [])[-15:]]
            if not rows:
                return "控えの記録はまだありません。"
            rows.sort(key=lambda x: x[0], reverse=True)
            return "\n".join(["番号 / 時刻 / 相手 / した事"] + [r for _, r in rows[:20]])
        st = self._load()
        dr = gas_ws_direct.DirectRunner(self)
        tid = (st.get("target") or {}).get("id", "")
        item = None
        to_s = str(to or "").strip().lstrip("#")
        if to_s.upper().startswith("D"):
            item = next((x for x in (st.get("direct_ledger") or []) if str(x["n"]) == to_s[1:]), None)
            if not item:
                return f"戻せませんでした: 直接の道の控え #{to_s} がありません"
            if item.get("undone"):
                return f"戻せませんでした: #{to_s} はもう戻してあります"
        elif not to_s and tid:
            item = dr.latest(st, tid)
            if item and (st.get("engine_last") or {}).get(tid, "") > item["time"]:
                item = None          # エンジンの道の直しの方が新しい → そちらを戻す
        if item:
            res = dr.undo(st, item, ok=bool(ok))
            self._save(st)
            t = {"name": item.get("name") or "", "sheet": item.get("sheet", "")}
            if res.get("ok"):
                return "\n".join([self._title(t), f"戻した: #D{item['n']}（{item['what']}）を取り消しました"])
            if res.get("needs_ok"):
                return "\n".join([self._title(t), "止めました: " + res["error"]])
            return "戻せませんでした: " + str(res.get("error") or "")
        res = self._post({"action": "undo", "to": str(to or ""), "ok": bool(ok),
                          "target_id": (st.get("target") or {}).get("id", "")})
        t = res.get("target") or {}
        if res.get("ok"):
            if t.get("id"):
                prev_cur = st.get("target") or {}
                kept_sheet = t.get("sheet") or (prev_cur.get("sheet") if prev_cur.get("id") == t.get("id") else "")
                st["target"] = {k: t[k] for k in ("id", "name", "kind", "url") if t.get(k)}
                if kept_sheet:
                    st["target"]["sheet"] = kept_sheet
                st.get("fails", {}).pop(t["id"], None)
                self._save(st)
            return "\n".join([self._title(t), f"戻した: #{res['undone']}（{res.get('what', '')}）を取り消しました",
                              f"控え #{res['backup']}（戻す前の状態。もう一度 ws_undo で元に戻せます）", t.get("url", "")])
        msg = res.get("error") or "戻せませんでした"
        if res.get("needs_ok"):
            return "\n".join([self._title(t), "止めました: " + msg])
        return "戻せませんでした: " + msg


def write_engine_all(path=ENGINE_SOURCE):
    """共通部＋Catalog＋棚をつないだ全文を書く（中身が同じなら触らない）。GAS に入れる Engine と同じ並び"""
    text = "\n".join(s for _, s in _engine_texts())
    path = Path(path)
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return path


write_engine_all()
