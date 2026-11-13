# -*- coding: utf-8 -*-
"""
gas_ws_trial.py - Workspace の磨き上げの試験の道具（試験設計書 段 T0）。試験用のエンジンと試験場を扱う。

  ・TrialEngine: 試験用のエンジン（GAS プロジェクト shu-workspace-engine-test）。本番のエンジンとは別（控え・台帳・錠・設定が別）。
      共通部・Catalog・棚のあとに ws_trial/Trial.gs を足して入れる。入れるのは試験の命令（ws-trial …）からだけ。
  ・Drive: フォルダ WS試験 と試験場のファイルを作る・移す・ゴミ箱へ送る（手元の道具の Drive の権限）。
      ゴミ箱へ送ってよいのは「回し手が記録した ID」かつ「名前が WS試験_ で始まる」かつ「フォルダ WS試験 の中にある」ファイルだけ。
  ・init: フォルダ・試験場のファイル・試験用のエンジンを作り、初回の許可が要る所で止まる（許可は人が押す）。
  ・check: 段 T0 の完了の条件を実機で確かめる（許可の後）。
手元の記録は .ws_trial.json（git に入れない）。本番の .ws_state.json には触らない。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import gas_workspace
import gas_ws_catalog
import gas_ws_tables

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / ".ws_trial.json"
PROD_STATE_FILE = HERE / ".ws_state.json"
TRIAL_GS = HERE / "ws_trial" / "Trial.gs"
TRIAL_ENGINE_TITLE = "shu-workspace-engine-test"
PREFIX = "WS試験_"
FOLDER_NAME = "WS試験"
MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_SHEET = gas_workspace.MIME_SHEET
MIME_DOC = gas_workspace.MIME_DOC

# 試験場の 5 つ（スプレッドシート 4・文書 1）と、試験用のエンジンの控えのブック
SANDBOX_SHEETS = ["WS試験_場", "WS試験_請求書_10月", "WS試験_請求書_11月", "WS試験_売上"]
SANDBOX_DOCS = ["WS試験_文書"]
BACKUP_BOOK = "WS試験_控え"
# 並べて回すための試験場（lane 2〜5）。場ごとに控えのブックを持ち、エンジンの錠・台帳も lane ごとに分かれる（lane 1＝WS試験_場・WS試験_控え）
LANE_NUMS = [str(i) for i in range(2, 11)]      # 最大 10 枚（既定の並べる数は 5＝場〜場5）
DEFAULT_JOBS = 5
LANE_SHEETS = {n: f"WS試験_場{n}" for n in LANE_NUMS}
LANE_BACKUPS = {n: f"WS試験_控え{n}" for n in LANE_NUMS}
LANE_BACKUPS["1"] = "WS試験_控え1"          # lane 1（WS試験_場）の控えは、ふつうの控え（WS試験_控え）と別のブックにする（古いタブの片付けが他の撃ち手のタブを消すため）
MAX_JOBS = 10         # GAS の同時実行の上限（ユーザーあたり 30 前後）に十分余裕を残す。Sheets API の読み取りは 1 分 60 回前後（超えたら待って撃ち直す）
WORD_LIMIT = 8        # 札 1 本の語の数の上限（第 8.4 節）


class TrialError(Exception):
    """利用者（番頭・回し手）に日本語でそのまま返す種類のエラー"""


# ------------------------------------------------------------------ 手元の記録
def load_state(path=STATE_FILE):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(st, path=STATE_FILE):
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ------------------------------------------------------------------ Drive（手元の道具の権限）
class Drive:
    API = "https://www.googleapis.com/drive/v3/files"

    def __init__(self, client):
        self.c = client

    def _req(self, method, url, **kw):
        return self.c._request_with_retry(method, url, headers=self.c._headers(), timeout=30, **kw)

    def get(self, fid, fields="id,name,mimeType,parents,trashed"):
        r = self._req("GET", f"{self.API}/{fid}", params={"fields": fields})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise TrialError(f"Drive: ファイル情報を取れません（{r.status_code}）: {r.text[:200]}")
        return r.json()

    def find(self, name, mime=None, parent=None):
        q = [f"name='{name}'", "trashed=false"]
        if mime:
            q.append(f"mimeType='{mime}'")
        if parent:
            q.append(f"'{parent}' in parents")
        r = self._req("GET", self.API, params={"q": " and ".join(q), "fields": "files(id,name,mimeType,parents)", "pageSize": 20})
        if r.status_code != 200:
            raise TrialError(f"Drive: 探せません（{r.status_code}）: {r.text[:200]}")
        return r.json().get("files", [])

    def create(self, name, mime, parent=None):
        body = {"name": name, "mimeType": mime}
        if parent:
            body["parents"] = [parent]
        r = self._req("POST", self.API, params={"fields": "id,name,mimeType,parents"}, json=body)
        if r.status_code not in (200, 201):
            raise TrialError(f"Drive: 作れません（{r.status_code}）: {r.text[:300]}")
        return r.json()

    def move(self, fid, new_parent):
        meta = self.get(fid, "id,parents")
        if meta is None:
            raise TrialError(f"Drive: {fid} が見つかりません")
        remove = ",".join(p for p in meta.get("parents", []) if p != new_parent)
        params = {"addParents": new_parent, "fields": "id,parents"}
        if remove:
            params["removeParents"] = remove
        r = self._req("PATCH", f"{self.API}/{fid}", params=params, json={})
        if r.status_code != 200:
            raise TrialError(f"Drive: 移せません（{r.status_code}）: {r.text[:300]}")
        return r.json()

    def trash(self, fid):
        r = self._req("PATCH", f"{self.API}/{fid}", params={"fields": "id,trashed"}, json={"trashed": True})
        if r.status_code != 200:
            raise TrialError(f"Drive: ゴミ箱へ送れません（{r.status_code}）: {r.text[:300]}")
        return r.json()


def trash_guard(meta, recorded_ids, folder_id, protected_ids=()):
    """ゴミ箱へ送ってよいか。(送ってよい, 欠けている条件のリスト)。3 つ全部が要る: 記録した ID・名前が WS試験_・フォルダの中"""
    why = []
    if meta is None:
        return False, ["ファイルが見つからない"]
    if meta["id"] in protected_ids:
        why.append("試験場の 5 つ・控えのブックは送らない")
    if meta["id"] not in recorded_ids:
        why.append("回し手が記録した ID ではない")
    if not str(meta.get("name", "")).startswith(PREFIX):
        why.append(f"名前が {PREFIX} で始まらない")
    if folder_id not in (meta.get("parents") or []):
        why.append(f"フォルダ {FOLDER_NAME} の中にない")
    return (not why), why


def trash_recorded(drive, recorded_ids, folder_id, protected_ids=()):
    """記録した ID のうち、守り 3 つを満たす物だけゴミ箱へ送る。返り値は (送った名前, 送らずに一覧に出す(名前・理由))"""
    sent, kept = [], []
    for fid in list(recorded_ids):
        meta = drive.get(fid)
        ok, why = trash_guard(meta, recorded_ids, folder_id, protected_ids)
        if ok:
            drive.trash(fid)
            sent.append(meta["name"])
        else:
            kept.append((meta["name"] if meta else fid, "・".join(why), fid))
    return sent, kept


# ------------------------------------------------------------------ 試験用のエンジン
class TrialEngine(gas_workspace.WorkspaceManager):
    """試験用のエンジン（本番とは別の GAS プロジェクト）につなぐ。共通部・Catalog・棚のあとに Trial.gs を足して入れる"""

    def __init__(self, client=None, state_path=None, trial_gs=TRIAL_GS, prod_state_path=PROD_STATE_FILE):
        super().__init__(client=client, state_path=state_path or STATE_FILE)
        self.engine_title = TRIAL_ENGINE_TITLE
        self.trial_gs = Path(trial_gs)
        self.prod_state_path = Path(prod_state_path)
        self.lane = ""      # 並べて回すときの lane（"2"〜"5"。空はふつう）。錠・控え・台帳が lane ごとに分かれる

    def _trial_text(self):
        return self.trial_gs.read_text(encoding="utf-8")

    def engine_version(self):
        h = hashlib.sha1(self._trial_text().encode("utf-8")).hexdigest()[:6]
        return super().engine_version() + "+t" + h

    def shelf_version(self):
        """共通部と棚の指紋（本番の engine_version と同じ作り）。手元のファイルとこれが同じなら、棚は本番の形と同じ"""
        return gas_workspace.WorkspaceManager.engine_version(self)

    def _engine_files(self, split=False):
        self.extra_texts = [("Trial", self._trial_text())]
        return super()._engine_files(split=split)

    def assert_not_prod(self):
        """試験の命令は本番のエンジンに入らない。同じプロジェクトを指していたら止める"""
        st = self._load()
        try:
            prod = json.loads(self.prod_state_path.read_text(encoding="utf-8")).get("engine_sid")
        except Exception:
            prod = None
        if prod and st.get("engine_sid") == prod:
            raise TrialError("試験用のエンジンが本番のエンジンと同じプロジェクトを指しています。止めました（.ws_trial.json の engine_sid を確かめてください）")
        if self.engine_title == gas_workspace.ENGINE_TITLE:
            raise TrialError("試験用のエンジンの名前が本番と同じです")

    def trial_post(self, action, **kw):
        """試験の命令を試験用のエンジンにだけ撃つ"""
        self.assert_not_prod()
        res = self._post(dict(kw, action=action))
        return res

    def seed(self, file_id, table):
        payload = gas_ws_tables.seed_payload(table)
        return self.trial_post("seed", id=file_id, **payload)

    def snap(self, file_id):
        r = self.trial_post("snap", id=file_id)
        if not r.get("ok"):
            raise TrialError(r.get("error") or "撮れませんでした")
        return r["snap"]


# ------------------------------------------------------------------ init
AUTH_LINES = ("試験用のエンジンの許可がまだです（最初の 1 回だけ、ブラウザで押す必要があります）。\n"
              "1. このURLを開く: {url}\n"
              "2. 「権限を確認」→ アカウントを選び、「詳細」→「（安全ではないページ）に移動」→「許可」を押す（許可するのはスプレッドシートと文書だけ）\n"
              "3. 押したら、もう一度 `py gas.py ws-trial init` を撃つ。")


def init(client=None, out=print, state_path=STATE_FILE):
    """フォルダ・試験場・試験用のエンジンを作る（あるものは作り直さない）。許可が要る所で止まって 2 を返す。通れば 0"""
    from gas_client import GasClient
    client = client or GasClient()
    drive = Drive(client)
    st = load_state(state_path)
    eng = TrialEngine(client=client, state_path=state_path)

    # 1. フォルダ
    folder = st.get("folder_id")
    if not (folder and drive.get(folder) and not drive.get(folder).get("trashed")):
        found = drive.find(FOLDER_NAME, MIME_FOLDER)
        folder = found[0]["id"] if found else drive.create(FOLDER_NAME, MIME_FOLDER)["id"]
        out(f"フォルダ {FOLDER_NAME}: " + ("見つけた" if found else "作った"))
    st["folder_id"] = folder
    # 2. 試験場のファイルと控えのブック（手元の道具が作るので、手元の道具でフォルダへの出し入れができる）
    files = st.setdefault("files", {})
    for name, mime in [(n, MIME_SHEET) for n in SANDBOX_SHEETS] + [(n, MIME_DOC) for n in SANDBOX_DOCS] + [(BACKUP_BOOK, MIME_SHEET)]:
        fid = files.get(name)
        if fid and drive.get(fid) and not drive.get(fid).get("trashed"):
            continue
        found = drive.find(name, mime, folder)
        if found:
            files[name] = found[0]["id"]
        else:
            files[name] = drive.create(name, mime, folder)["id"]
            out(f"作った: {name}")
    st.setdefault("recorded", [])      # 回し手が作ったファイルの ID（ゴミ箱へ送ってよい物の記録）
    save_state(st, state_path)
    # 3. 試験用のエンジン（別の GAS プロジェクト）
    try:
        eng.assert_not_prod()
        res = eng.trial_post("ping")
    except gas_workspace.WorkspaceAuthNeeded as e:
        url = (eng._load().get("engine_url") or "")
        out(AUTH_LINES.format(url=url))
        return 2
    except gas_workspace.WorkspaceError as e:
        out("試験用のエンジンが答えません: " + str(e))
        return 1
    # 4. 試験場の登録（登録した ID のファイルにだけ試験の入口が効く）・ロケールと時刻
    ids = [files[n] for n in SANDBOX_SHEETS] + [files[n] for n in LANE_SHEETS.values() if n in files]      # lanes で足した試験場も外さない
    docs = [files[n] for n in SANDBOX_DOCS]
    r = eng.trial_post("trial_config", ids=ids, docs=docs, bk_book=files[BACKUP_BOOK])
    if not r.get("ok"):
        out("試験場を登録できません: " + str(r.get("error")))
        return 1
    for ln in ["1"] + LANE_NUMS:              # lane ごとの控えのブック（lanes で作った分だけ。lane 1 は WS試験_控え）
        if LANE_BACKUPS[ln] in files:
            eng.lane = ln
            try:
                rl = eng.trial_post("trial_config", ids=ids, docs=docs, bk_book=files[LANE_BACKUPS[ln]])
            finally:
                eng.lane = ""
            if not rl.get("ok"):
                out(f"lane {ln} の控えを登録できません: " + str(rl.get("error")))
                return 1
    info = eng.trial_post("trial_info")
    st = load_state(state_path)
    st["engine_checked"] = {"version": res.get("version"), "ledger_items": info.get("ledger_items"), "ids": len(ids), "docs": len(docs)}
    save_state(st, state_path)
    out(f"試験用のエンジン: {res.get('version')} ／ 試験場 {len(ids)} 枚＋文書 {len(docs)} 個を登録 ／ 本番のエンジンとは別のプロジェクト")
    return 0



def lanes(client=None, out=print, state_path=STATE_FILE, count=DEFAULT_JOBS):
    """並べて回すための試験場（WS試験_場2〜5）と lane ごとの控えのブックを作り、登録する（あるものは作り直さない）。init の後に撃つ"""
    from gas_client import GasClient
    client = client or GasClient()
    drive = Drive(client)
    st = load_state(state_path)
    folder = st.get("folder_id")
    if not folder:
        out("先に `py gas.py ws-trial init` を撃ってください（フォルダがありません）")
        return 1
    files = st.setdefault("files", {})
    use = LANE_NUMS[:max(0, min(count, MAX_JOBS) - 1)]
    use = ["1"] + use if count >= 1 else use
    use = [n for n in use if n in LANE_BACKUPS]
    for name in [LANE_SHEETS[n] for n in use if n in LANE_SHEETS] + [LANE_BACKUPS[n] for n in use]:
        fid = files.get(name)
        if fid and drive.get(fid) and not drive.get(fid).get("trashed"):
            continue
        found = drive.find(name, MIME_SHEET, folder)
        files[name] = found[0]["id"] if found else drive.create(name, MIME_SHEET, folder)["id"]
        if not found:
            out(f"作った: {name}")
    save_state(st, state_path)
    rc = init(client=client, out=out, state_path=state_path)       # 登録（ids と lane ごとの控え）を init の中で撃つ
    return rc


def lane_workers(eng_factory, st=None, jobs=5):
    """(エンジン, 試験場の ID) の並び。lane 1＝WS試験_場、2〜5＝WS試験_場2〜5（lanes で作った分だけ）。jobs 個まで"""
    st = st if st is not None else load_state()
    files = st.get("files", {})
    ws = [("1", files["WS試験_場"])] if LANE_BACKUPS["1"] in files else [("", files["WS試験_場"])]
    for n in LANE_NUMS:
        if LANE_SHEETS[n] in files and LANE_BACKUPS[n] in files:
            ws.append((n, files[LANE_SHEETS[n]]))
    out = []
    for lane, fid in ws[:max(1, min(jobs, MAX_JOBS))]:
        e = eng_factory()
        e.lane = lane
        out.append((e, fid))
    return out


# ------------------------------------------------------------------ check（段 T0 の完了の条件を実機で確かめる。許可の後）
PROD_BACKUP_BOOK = "GASマネージャー_控え"


def _prod_snapshot(client, drive, prod_state_path=PROD_STATE_FILE):
    """本番のエンジンの台帳（番号と件数）と、本番の控えのブックの更新時刻。読むだけ（本番のエンジンを入れ直さない・書かない）"""
    snap = {"ledger": None, "backup_modified": None}
    try:
        url = json.loads(Path(prod_state_path).read_text(encoding="utf-8")).get("engine_url")
    except Exception:
        url = None
    if url:
        r = client.call_webapp(url, body={"action": "list"}, method="POST", use_auth=True, timeout=90)
        data = r.get("data") or {}
        led = data.get("ledger") or []
        snap["ledger"] = {"count": len(led), "last": (led[-1].get("n") if led and isinstance(led[-1], dict) else None), "raw": json.dumps(led, ensure_ascii=False, sort_keys=True)}
    found = drive.find(PROD_BACKUP_BOOK, MIME_SHEET)
    if found:
        meta = drive.get(found[0]["id"], "id,modifiedTime")
        snap["backup_modified"] = meta.get("modifiedTime") if meta else None
        snap["backup_id"] = found[0]["id"]
    return snap


def check(client=None, out=print, state_path=STATE_FILE, prod_state_path=PROD_STATE_FILE, memo_path=None):
    """試験用のエンジンが許可済みのとき、段 T0 の実機の確かめを回す。0＝全部通った。結果を memo_path（共有メモ）にも書く"""
    from gas_client import GasClient
    client = client or GasClient()
    drive = Drive(client)
    st = load_state(state_path)
    files = st.get("files") or {}
    if not files.get("WS試験_場") or not st.get("engine_checked"):
        out("先に py gas.py ws-trial init を通してください（試験場と許可が要ります）")
        return 1
    eng = TrialEngine(client=client, state_path=state_path, prod_state_path=prod_state_path)
    eng.assert_not_prod()
    folder = st["folder_id"]
    protected = set(files.values())
    results = []

    def rec(name, ok, detail):
        results.append((name, ok, detail))
        out(("[OK] " if ok else "[NG] ") + name + " ／ " + detail)

    before = _prod_snapshot(client, drive, prod_state_path)
    recorded = st.setdefault("recorded", [])

    # 1. 試験場でないファイルへの seed が断られる（登録されていない ID）
    tmp = drive.create(PREFIX + "対象外_確認", MIME_SHEET, folder)
    recorded.append(tmp["id"])
    save_state(st, state_path)
    r = eng.seed(tmp["id"], gas_ws_tables.load_table("meibo_base"))
    rec("試験場でないファイルへの seed が断られる", (not r.get("ok")) and "試験場のファイルではありません" in str(r.get("error", "")), str(r.get("error", ""))[:90])

    # 2. 試験場に流し込める・型が化けない・条件付き書式で付けた色が撮れる
    table = gas_ws_tables.load_table("meibo_base")
    table["sheets"][0]["cf"] = [{"range": "F2:F20", "when": "gt", "value": "11999", "bg": "#ffff00"}]
    sandbox = files["WS試験_場"]
    r = eng.seed(sandbox, table)
    rec("試験場への seed（型の確かめつき）", bool(r.get("ok")), str(r.get("error", "ok"))[:120])
    if r.get("ok"):
        import gas_ws_judge as J
        s = eng.snap(sandbox)["sheets"][0]
        c = s["cells"].get("F2", {})
        got_e, got_u = (c.get("e") or {}).get("bg"), (c.get("u") or {}).get("bg")
        ok = J.color_family(got_e) == "黄" and J.color_family(got_u) == "白"
        rec("条件付き書式で付けた色が effectiveFormat で撮れる", ok, f"F2 の見えている背景 {got_e}（黄の仲間のはず）・素の背景 {got_u}（白のはず）。"
            + ("撮れる" if ok else "撮れない → 条件は「素の書式がその色、または覆う条件付きの規則がその色」の どれか に切り替える"))

    # 3. Drive の権限: 手元の道具が作ったファイルの移す・ゴミ箱、エンジンが作ったファイルの移す・ゴミ箱
    root_file = drive.create(PREFIX + "権限確認_手元", MIME_SHEET)          # マイドライブの直下に作る
    recorded.append(root_file["id"])
    save_state(st, state_path)
    try:
        drive.move(root_file["id"], folder)
        moved = drive.get(root_file["id"], "id,parents")
        rec("手元の道具が作ったファイルをフォルダへ移せる", folder in (moved.get("parents") or []), "移した")
    except TrialError as e:
        rec("手元の道具が作ったファイルをフォルダへ移せる", False, str(e)[:120])
    res = eng.trial_post("do", target={"new": PREFIX + "権限確認_エンジン", "kind": "sheet"}, ops=[{"shelf": "table.new", "headers": ["a"]}], ok=False)
    new = (res.get("created") or {}).get("id") or (res.get("target") or {}).get("id")
    if new:
        recorded.append(new)
        save_state(st, state_path)
        meta = drive.get(new)
        if meta is None:
            rec("エンジンが作ったファイルを手元の道具が見られる", False, "手元の Drive の権限（drive.file）では見えない → 移す・ゴミ箱へ送るはできない。権限を広げずに番頭に戻す")
        else:
            try:
                drive.move(new, folder)
                rec("エンジンが作ったファイルをフォルダへ移せる", True, "移した")
            except TrialError as e:
                rec("エンジンが作ったファイルをフォルダへ移せる", False, str(e)[:120] + " → 権限を広げずに番頭に戻す")
    else:
        rec("エンジンが作ったファイルの確かめ", False, "作れなかった: " + str(res.get("error"))[:100])
    # 4. ゴミ箱へ送る（守り 3 つ）。今回作った確認用のファイルだけ。試験場の 5 つ・控えのブックは送らない
    sent, kept = trash_recorded(drive, recorded, folder, protected)
    rec("ゴミ箱へ送る（守り 3 つを満たす物だけ）", bool(sent), f"送った {len(sent)} 件: {'、'.join(sent)} ／ 送らなかった {len(kept)} 件: " + "；".join(f"{n}（{w}）" for n, w, _ in kept))
    st = load_state(state_path)
    st["recorded"] = [k[2] for k in kept]          # 送らなかった物だけ記録に残す
    save_state(st, state_path)

    # 5. 本番のエンジンの台帳と控えのブックが、試験の前後で 1 件も変わらない。
    #    試験用のエンジンの trial（流し込む→撮る→撃つ→撮る→戻す→撮る）だけを挟んだ短い窓で見る
    #    （ほかの人が本番を使っている時間に当たると、長い窓では本番の台帳が動くので、長い窓は参考にとどめる）
    wide = before
    pre = _prod_snapshot(client, drive, prod_state_path)
    payload = gas_ws_tables.seed_payload(gas_ws_tables.load_table("meibo_base"))
    tr = eng.trial_post("trial", id=sandbox, seed=payload, ops=[{"shelf": "total", "label": "合計"}, {"shelf": "format", "range": "A1:F1", "bold": True}])
    rec("trial（流し込む→撮る→撃つ→撮る→戻す→撮る）が 1 回の POST で通る", bool(tr.get("ok") and tr.get("a") and tr.get("b")) and "do" in tr,
        f"控えが {tr.get('backups_added')} 回増えた（試験用の台帳）・戻した: {'ok' if (tr.get('undo') or {}).get('ok') else (tr.get('undo') or {}).get('error', '戻していない')}")
    post = _prod_snapshot(client, drive, prod_state_path)
    same_ledger = (pre["ledger"] or {}).get("raw") == (post["ledger"] or {}).get("raw")
    same_backup = pre.get("backup_modified") == post.get("backup_modified")
    rec("本番のエンジンの台帳が試験の前後で同じ", same_ledger, f"件数 {(pre['ledger'] or {}).get('count')} → {(post['ledger'] or {}).get('count')}（試験の命令を撃った短い窓）")
    rec("本番の控えのブックが試験の前後で同じ（更新時刻）", same_backup, f"{pre.get('backup_modified')} → {post.get('backup_modified')}")
    if (wide["ledger"] or {}).get("raw") != (post["ledger"] or {}).get("raw"):
        out("[参考] この確かめ全体の間に、本番の台帳が動いています（別の人が本番を使った時間。試験の命令は本番へ撃っていません）")
    if memo_path:
        lines = ["# 段 T0 実機の確かめ", ""] + [("- [OK] " if ok else "- [NG] ") + f"{n} ／ {d}" for n, ok, d in results]
        Path(memo_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if all(ok for _, ok, _ in results) else 1


# ------------------------------------------------------------------ 語の数（第 8.4 節・段 T0 で数える）
def words_over_limit(catalog=None, limit=WORD_LIMIT):
    cat = catalog or gas_workspace.CATALOG
    return [(s["name"], len(s["words"])) for s in cat.shelves if len(s["words"]) > limit]


def props_cmd(args, out=print):
    """py gas.py ws-trial props [--shelf 棚]… [--table 表]… [--all | --changed [--with-engine]] [--jobs N] [--resume ファイル] [--limit-sec 秒] [--stamp ファイル [--root 木]]
    試験用のエンジンの試験場だけに撃つ。--jobs N は試験場を N 枚（lane）並べて同時に撃つ（既定 5。最大 10＝WS試験_場〜場10。足りなければ先に `ws-trial lanes --count N`。元の説明: 先に `ws-trial lanes`）"""
    import argparse
    import gas_ws_props
    ap = argparse.ArgumentParser(prog="ws-trial props")
    ap.add_argument("--shelf", action="append", default=[])
    ap.add_argument("--table", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--changed", action="store_true")          # 前回の記録と比べて、変わった棚・表・ひな形にかかる組だけ回す
    ap.add_argument("--refail", action="store_true")           # 前回通らなかった組も撃ち直す（直した後の確かめ）
    ap.add_argument("--with-engine", action="store_true")      # 共通部（workspace_engine.gs・Trial.gs）が変わった組も回す（節目）
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--resume", default="")
    ap.add_argument("--limit-sec", type=int, default=6 * 3600)        # 全体の時間の上限（既定 6 時間で自分で止まる）
    ap.add_argument("--stamp", default="")                     # 指紋のない昔の記録に指紋を書き足す（--root の木で回した記録に）
    ap.add_argument("--root", default="")
    a = ap.parse_args(args)
    if a.stamp:
        n = gas_ws_props.stamp(a.stamp, gas_ws_props.inputs_fp(root=a.root or None))
        out(f"指紋を足した記録: {n} 件（{a.stamp}）")
        return 0
    if not (a.all or a.changed or a.shelf or a.table):
        out("棚か表を指定してください（--shelf 棚 / --table 表 / --all / --changed）")
        return 1
    from gas_client import GasClient
    st = load_state()
    client = GasClient()
    eng = TrialEngine(client=client)
    eng.assert_not_prod()
    workers = None
    if a.jobs > 1:
        eng._ensure_engine()                 # 版の差し替えは先に 1 回だけ（並べて撃つ前に済ませる）
        client.get_access_token()
        workers = lane_workers(lambda: TrialEngine(client=client), st, a.jobs)
        if len(workers) < a.jobs:
            out(f"[注意] 試験場が {len(workers)} 枚しか無いので {len(workers)} 本で回します（先に `py gas.py ws-trial lanes`）")
    stats, rf = gas_ws_props.run(eng, st["files"]["WS試験_場"], shelves=a.shelf or None, tables=a.table or None, run_file=a.resume or None,
                                 resume=bool(a.resume), out=out, limit_seconds=a.limit_sec, workers=workers, changed=a.changed, with_engine=a.with_engine, refail=a.refail)
    rows, fails, p6 = gas_ws_props.summarize(rf) if Path(rf).exists() else ([], [], {})
    out(f"組 {len(rows)} ・通らない {len(fails)} ・POST 失敗 {stats['post_fail']}（Google の上限らしい物 {stats['quota']}・429 を待って撃ち直した回数 {stats['quota_retry']}・錠の待ち直し {stats['busy_retry']}）・{stats['workers']} 本で {stats.get('sec', 0):.0f} 秒・記録 {rf}")
    return 1 if fails else 0


def shot_cmd(cmd, args, out=print):
    """golden（模範の再生）・look（ws_look の撮り置き）・shot（L2b: AI に 1 回答えさせて撃つ）。試験用のエンジンの試験場だけに撃つ"""
    import argparse
    import gas_ws_shot as S
    ap = argparse.ArgumentParser(prog="ws-trial " + cmd)
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--resume", default="")
    ap.add_argument("--limit-sec", type=int, default=6 * 3600)
    a = ap.parse_args(args)
    from gas_client import GasClient
    st = load_state()
    eng = TrialEngine(client=GasClient())
    eng.assert_not_prod()
    fid = st["files"]["WS試験_場"]
    cases = [c for c in S.load_cases() if not a.case or c["id"] in a.case]
    if cmd == "look":
        import gas_ws_props
        S.capture_looks(eng, fid, sorted({c["table"] for c in cases} | set(gas_ws_props.TABLES)), out=out)
        return 0
    if cmd == "golden":
        bad = 0
        for c in cases:
            resp, _ = S.run_model(eng, fid, c)
            ok, why = S.judge_model(c, resp)
            bad += not ok
            out(("○ " if ok else "M ") + f"{c['id']} {c['table']}「{c['turns'][0]['say'][:24]}」" + ("" if ok else " " + "；".join(why)[:160]))
        out(f"模範の再生 {len(cases)} 本・通らない {bad} 本")
        return 1 if bad else 0
    results, rf = S.run_shot(eng, fid, cases, model=a.model, out=out, run_file=a.resume or None, resume=bool(a.resume), times=a.times, limit_seconds=a.limit_sec)
    sm = S.summarize(results)
    out(f"L2b {a.model}: {sm['ok']}/{sm['n']}（{sm['rate']:.0f}%）・外れの内訳 {sm['F']}・AI {sm['ai_calls']} 回 {sm['ai_sec']:.0f} 秒（1 回 {sm['sec_each']:.1f} 秒）・入力 {sm['in_tokens']} 出力 {sm['out_tokens']} トークン・API 換算 ${sm['cost_usd']:.3f}・記録 {rf}")
    return 0


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "init":
        return init()
    if cmd == "props":
        return props_cmd(argv[1:])
    if cmd == "lanes":
        return lanes(count=int(argv[argv.index("--count") + 1]) if "--count" in argv else DEFAULT_JOBS)
    if cmd in ("golden", "look", "shot"):
        return shot_cmd(cmd, argv[1:])
    if cmd == "check":
        memo = Path(r"C:\Users\shu\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\side-session-notes\local_17e23481-3a47-4d0f-ab8c-f1d69e214e19") / "段T0_実機の確かめ.md"
        return check(memo_path=memo if memo.parent.exists() else None)
    if cmd == "tables":
        bad = 0
        for n in gas_ws_tables.table_names():
            p = gas_ws_tables.validate_table(gas_ws_tables.load_table(n))
            print(("[NG] " if p else "[OK] ") + n + ("" if not p else " " + " / ".join(p)))
            bad += bool(p)
        return 1 if bad else 0
    if cmd == "words":
        over = words_over_limit()
        print(f"語が {WORD_LIMIT} 個を超えている札: {len(over)} 本" + ("（" + "、".join(f"{n}={c}" for n, c in over) + "）" if over else ""))
        return 0
    print("使い方: py gas.py ws-trial init | check | tables | words")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
