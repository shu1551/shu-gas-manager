# -*- coding: utf-8 -*-
"""
gas_ws_agent.py - 頼みの文 1 つを道具が回す脳（Excel マネージャーの agent の写し・2026-11-27）

輪: 材料（ws_look・ブック全体の健診）→ 先撃ち（ws_do(ask)＝棚当て・汚れの直し・残り・次の手）
    → AI に聞く（JSON 1 個: やることの一覧・手・done・報告）→ 道具が撃つ（look / trace / find / do / undo）
    → 結果を AI に返す …（max_turns まで）→ 関所 → 報告
関所: (0) 落とし物＝一覧に「未」が残ったままの done は受け付けない
      (1) 仕上げ検査＝撃った手の返事に ⚠（検算の食い違い・新しいエラー）が残ったままの done は受け付けない
      (2) 採点＝別の会話の AI に、頼み・道具が読み直した現物・報告だけを渡し、満たしていない点を挙げさせる（no_grade で止める）
人の値を消す・上書きする手（ok=True）は、頼みに承認の言葉があるときだけ通す。無ければ ok を外して撃ち、止まった物は
【人に判断してほしいこと】に並べる。台帳は .ws_agent_runs.jsonl（1 走行 1 行）。
"""
import json
import os
import re
import shutil
import subprocess
import threading
import queue
import time
from pathlib import Path

import ws_window_ai

HERE = Path(__file__).resolve().parent
RUNS_PATH = HERE / ".ws_agent_runs.jsonl"
LAST_LOG = HERE / ".ws_agent_last.jsonl"     # 直前の走行の往復の全文
DEFAULT_MODEL = "sonnet"
AI_TIMEOUT = 180
OUT_CAP = 3500

APPROVAL_RE = re.compile(r"消してよい|消していい|削除してよい|削除していい|置き換えてよい|置き換えていい|上書きしてよい|上書きしていい|"
                         r"消して|削除して|取り除いて|クリアして")

SYSTEM_PROMPT = (
    "あなたは Google スプレッドシートを直す AI エージェントの頭です。道具（GAS マネージャー）が材料を集め、あなたの手を撃ち、結果を返します。\n"
    "必ず有効な JSON オブジェクト 1 個だけを返してください（説明文や ``` は付けない）。形:\n"
    '{"plan":[{"item":"やること","state":"済|未"}],'
    '"actions":[{"type":"look","sheet":"シート","range":"A1:Z60"}|{"type":"trace","cell":"シート!A1"}|{"type":"find","ask":"語"}|'
    '{"type":"do","sheet":"シート","ops":[{"shelf":"棚",...}],"ok":false}|{"type":"undo"}],'
    '"done":false,"report":"使う人への返事（done のとき）","ask_human":["人に判断してほしいこと"]}\n'
    "決まり:\n"
    "1. 頼みを分けて plan に並べる。手の無い頼みを黙って落とさない。できない物は report に「できなかったこと」と人がやるなら何をするかを書く。\n"
    "2. 先撃ち（道具が棚当てで撃った結果）の「次の手」に従う。「なし」なら手を足さずに done で報告してよい。\n"
    "3. 手を組むときは、列名・値・範囲を材料の実物から取る（頼みの言葉を値にしない）。do には sheet を必ず書く。"
    "棚に無い設定は shelf=api（Sheets API の batchUpdate の requests）、棚にも api にも無い手は shelf=script（Apps Script の本文・ss と sheet が使える）。\n"
    "4. 撃った後の返事の 検算・前→後 を読む。⚠ があれば直すか undo して組み直す。\n"
    "5. 人の値を消す・上書きする手の ok は、道具が承認の有無で決める（あなたが付けても承認が無ければ外れる）。止まったら ask_human に消える物を番地で書く。\n"
    "6. どちらを残す・どれが正しい等、人の判断が要る物は撃たずに ask_human へ。\n"
    "7. 手と done は同じ返事に載せてよい（全部の手が通れば、道具はそのまま関所へ進む）。\n"
    "8. report は要点だけ 3〜5 行: 何をどこに直したか（番地）・検算の数・その手に効く気づき（否認・表記ゆれ・前に見つけたずれ・本当の値）。読むだけの問いは根拠の番地と内訳・割合を添える。"
)

GRADE_PROMPT = (
    "あなたはスプレッドシートの仕事の採点係です。頼み・道具が読み直した今の現物・担当者の報告だけを見て、"
    "頼みのうち満たしていない点を挙げてください。必ず JSON 1 個だけ: {\"unmet\":[\"満たしていない点\"]}（全部満たしていれば空の配列）。"
    "人の判断を待つと報告に書いてある物・頼みに無い物は挙げない。"
)


class _Session(ws_window_ai._HeadlessClaudeSession):
    """claude -p の常駐会話（system prompt だけ替える）"""
    MAX_TURNS = 30

    def __init__(self, model, system_prompt):
        super().__init__(model=model)
        self.system_prompt = system_prompt

    def start(self):
        if self.alive():
            return
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("claude コマンドが見つかりません（Claude Code をインストールしてログインしてください）。")
        cmd = [exe] + ws_window_ai._CC_ARGS + ["--model", self.model, "--system-prompt", self.system_prompt]
        kw = {"cwd": ws_window_ai._neutral_cwd(), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self.err = []
        self.lines = queue.Queue()
        self.turns = 0
        self.last_used_at = time.monotonic()
        self.proc = subprocess.Popen(cmd, **kw)
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, None), daemon=True).start()


def _cap(s, n=OUT_CAP):
    s = str(s or "")
    return s if len(s) <= n else s[:n] + f"\n…（{len(s) - n} 字を省略）"


def _parse(raw):
    t = ws_window_ai._strip_json_fence(raw)
    d = json.loads(t)
    if isinstance(d, list):                       # ops の配列だけが来た
        d = {"actions": [{"type": "do", "ops": d}]}
    if not isinstance(d, dict):
        raise ValueError("JSON オブジェクトではありません")
    # 形のゆれを吸う（棚の札の例に引かれて ws_do の形で返すことがある・11/27 実測で 4 往復とも）
    if not d.get("actions"):
        a = None
        if isinstance(d.get("args"), dict) and (d.get("tool") or "").endswith(("do", "look", "undo", "find")):
            a = dict(d["args"], type=str(d["tool"]).replace("ws_", ""))
        elif d.get("ops"):
            a = {"type": "do", "sheet": d.get("sheet", ""), "ops": d["ops"], "ok": d.get("ok", False)}
        elif d.get("shelf"):
            a = {"type": "do", "sheet": d.get("sheet", ""), "ops": [{k: v for k, v in d.items() if k != "sheet"}]}
        if a:
            if a.get("type") == "do" and not isinstance(a.get("ops"), list):
                a["ops"] = [a.get("ops")] if a.get("ops") else []
            d["actions"] = [a]
    d.setdefault("plan", [])
    d.setdefault("actions", [])
    return d


def _open_items(plan):
    return [p.get("item") for p in (plan or []) if isinstance(p, dict) and str(p.get("state") or "") != "済"]


class Agent:
    def __init__(self, mgr, model=DEFAULT_MODEL, max_turns=4, grade=True, budget_sec=None):
        self.mgr = mgr
        self.model = model or DEFAULT_MODEL
        self.max_turns = max(1, int(max_turns or 4))
        self.grade = grade
        self.budget_sec = budget_sec       # 待てる秒（サイドバーは拡張が 65 秒で切るので 55 秒）。None は上限なし

    # ------------------------------------------------------------ 手を撃つ
    def _act(self, a, target, approved, log):
        typ = str(a.get("type") or "")
        if typ == "look":
            return self.mgr.look(target=target, sheet=a.get("sheet") or "", range=a.get("range") or "A1:Z60")
        if typ == "trace":
            return self.mgr.look(target=target, trace=a.get("cell") or "")
        if typ == "find":
            return self.mgr.find(ask=a.get("ask") or "")
        if typ == "undo":
            out = self.mgr.undo()
            log["undo"] += 1
            return out
        if typ == "do":
            ops = a.get("ops") or []
            ops = ops if isinstance(ops, list) else [ops]
            want_ok = bool(a.get("ok")) or any(isinstance(o, dict) and o.get("ok") for o in ops)
            ok = want_ok and approved
            if want_ok and not approved:
                ops = [{k: v for k, v in o.items() if k != "ok"} if isinstance(o, dict) else o for o in ops]
                log["ok_stripped"] += 1
            out = self.mgr.do(ops=json.dumps(ops, ensure_ascii=False), target=target, sheet=a.get("sheet") or "", ok=ok)
            log["do"] += 1
            m = re.search(r"控え #(\w+)", out)
            if m:
                log["backups"].append(m.group(1))
            for ln in out.splitlines():
                if ln.startswith("直した所"):
                    log["changed"].append(ln[len("直した所: "):] if ln.startswith("直した所: ") else ln)
            return out
        return f"（知らない手「{typ}」は撃っていません。type は look / trace / find / do / undo）"

    # ------------------------------------------------------------ 輪
    def run(self, request, target="", sheet=""):
        t0 = time.time()
        ai_sec = tool_sec = 0.0
        approved = bool(APPROVAL_RE.search(request or ""))
        log = {"do": 0, "undo": 0, "ok_stripped": 0, "backups": [], "changed": []}
        gates = {"落とし物": 0, "仕上げ検査": 0, "採点": 0}

        tt = time.time()
        # 1手目は先撃ち（ws_do(ask)）から入る。読むだけ・撃っていませんのときは prefire 内に表の中身と健診が入るため、
        # 最初の重複 look は省き、先撃ちがシートを書き換えた（控えができた）あとだけ最新のシートを look して材料にする。
        if sheet and target:
            st0 = self.mgr._load()
            t0_cur = st0.get("target") or {}
            if t0_cur.get("id") == target and t0_cur.get("sheet") != sheet:
                t0_cur["sheet"] = sheet
                self.mgr._save(st0)
        try:
            prefire = self.mgr.do(ask=request, target=target, ok=approved)
        except Exception as e:
            prefire = f"（先撃ちは撃てませんでした: {e}）"
        st = self.mgr._load()
        tgt = st.get("target") or {}
        sheet = sheet or tgt.get("sheet") or ""
        target = tgt.get("id") or target
        m = re.search(r"控え #(\w+)", prefire)
        if m:
            log["backups"].append(m.group(1))
        for ln in prefire.splitlines():
            if ln.startswith("直した所: "):
                log["changed"].append(ln[len("直した所: "):])
        if ("中身（行番号・列記号・数式つき）:" in prefire or "表の中身（行番号・列記号・数式つき）:" in prefire) and not m:
            material = "（先撃ちの返事に表の中身と健診が含まれています）"
        else:
            material = self.mgr.look(target=target, sheet=sheet, range="A1:Z60")
        try:
            import gas_ws_find
            cards = "" if "次の手: なし＝これで仕上がり" in prefire else gas_ws_find.build_ai_shelf_prompt(
                self.mgr.finder, request, kind="sheet", detail_limit=1600, top_args=25)
        except Exception:
            cards = ""
        tool_sec += time.time() - tt

        sess = _Session(self.model, SYSTEM_PROMPT)
        prompt = (f"【頼み】\n{request}\n\n【承認の言葉】{'あり（消す・上書きの ok を通す）' if approved else 'なし（消す・上書きは止まる）'}\n\n"
                  f"【材料（ws_look・シート「{sheet}」）】\n{_cap(material, 6000)}\n\n"
                  f"【先撃ち（道具が棚当てで撃った結果）】\n{_cap(prefire)}\n\n{_cap(cards, 4000)}\n\n"
                  "上の札の例は ws_do の形で書いてあるが、あなたの返事は必ず決まりの形（plan・actions・done・report を持つ JSON 1 個）にする。"
                  "棚の手は actions の中の {\"type\":\"do\",\"sheet\":…,\"ops\":[…]} に入れる。")
        turns, parsed, last_outs, report, ask_human = 0, None, [], "", []
        trail = []                                   # 往復の全文（検分の材料・Excel の _last_agent_log.jsonl と同じ）
        try:
            while turns < self.max_turns + 2:          # 関所の差し戻しは別枠（2 回まで）
                left = None if self.budget_sec is None else self.budget_sec - (time.time() - t0)
                if left is not None and left < 12:
                    report = (parsed or {}).get("report") or "（待てる時間の中で終わりませんでした。ここまでにやったことは下の「変わった所」。続きは同じ頼みをもう一度）"
                    break
                turns += 1
                ta = time.time()
                try:
                    raw = sess.ask(prompt, timeout=AI_TIMEOUT if left is None else max(10, int(left - 2)))
                except TimeoutError:
                    ai_sec += time.time() - ta
                    report = (parsed or {}).get("report") or "（AI の返事が待てる時間の中に来ませんでした。ここまでにやったことは下の「変わった所」）"
                    break
                ai_sec += time.time() - ta
                trail.append({"turn": turns, "prompt": prompt, "raw": raw})
                try:
                    parsed = _parse(raw)
                except Exception as e:
                    prompt = f"返事が JSON として読めませんでした（{e}）。決まりの形の JSON 1 個だけで返してください。"
                    continue
                ask_human = [x for x in (parsed.get("ask_human") or []) if x]
                outs, all_ok = [], True
                tt = time.time()
                for a in (parsed.get("actions") or [])[:8]:
                    if not isinstance(a, dict):
                        continue
                    try:
                        o = self._act(a, target, approved, log)
                    except Exception as e:
                        o = f"失敗: {e}"
                    if o.startswith(("失敗", "止めました")) or "\n失敗" in o or "⚠" in o:
                        all_ok = False
                    outs.append(f"▼ {a.get('type')} {json.dumps({k: v for k, v in a.items() if k != 'type'}, ensure_ascii=False)[:300]}\n{_cap(o)}")
                tool_sec += time.time() - tt
                if outs:
                    last_outs = outs
                if parsed.get("done"):
                    open_items = _open_items(parsed.get("plan"))
                    if open_items and not (outs and all_ok):
                        if gates["落とし物"] < 1:
                            gates["落とし物"] += 1
                            prompt = ("\n\n".join(outs) + "\n\n" if outs else "") + \
                                "関所(0) 落とし物: 一覧に「未」が残ったまま done です: " + "・".join(map(str, open_items)) + \
                                "。済ませるか、できない理由を report の「できなかったこと」に書いてから done にしてください。"
                            continue
                    if any("⚠" in o for o in last_outs) and gates["仕上げ検査"] < 1:
                        gates["仕上げ検査"] += 1
                        prompt = "\n\n".join(last_outs) + "\n\n関所(1) 仕上げ検査: 撃った手の返事に ⚠（検算の食い違い・新しいエラー）が残っています。直すか undo して組み直してから done にしてください。"
                        continue
                    # 先撃ち（prefire）1発で「次の手: なし＝これで仕上がり」となり、AIが追加の do を撃たず ⚠ も無いときは
                    # 道具側の検算をすでに通過しているため、別会話AIによる二重採点（_grade）を省く。
                    prefire_finished = ("次の手: なし＝これで仕上がり" in prefire and log["do"] == 0 and "⚠" not in prefire)
                    if (self.grade and not prefire_finished
                            and (self.budget_sec is None or self.budget_sec - (time.time() - t0) > 25)
                            and log["do"] + (1 if log["backups"] else 0) > 0 and gates["採点"] < 1):
                        tg = time.time()
                        unmet = self._grade(request, target, sheet, parsed.get("report") or "")
                        ai_sec += time.time() - tg
                        if unmet:
                            gates["採点"] += 1
                            prompt = "関所(2) 採点（別の会話の AI が現物を見た結果）: 頼みのうち満たしていない点: " + " ／ ".join(unmet) + \
                                "。一覧に「未」で足して済ませるか、人の判断が要る物は ask_human に回してから done にしてください。"
                            continue
                    report = parsed.get("report") or ""
                    break
                if turns >= self.max_turns + sum(gates.values()):
                    report = parsed.get("report") or "（往復の上限に達しました。ここまでにやったことは下の「変わった所」）"
                    break
                prompt = ("\n\n".join(outs) + "\n\n結果を読んで、次の JSON を返してください。") if outs else (
                    "返事に actions も done もありませんでした。決まりの形 "
                    '{"plan":[…],"actions":[{"type":"do","sheet":"…","ops":[…]}],"done":false,"report":""} の JSON 1 個で返してください。')
        finally:
            sess.close()
            try:
                LAST_LOG.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in trail), encoding="utf-8")
            except Exception:
                pass

        secs = time.time() - t0
        passed = sum(gates.values())
        verdict = "一発合格" if passed == 0 else "関所で直して合格"
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "target": target, "sheet": sheet, "request": request,
               "turns": turns, "secs": round(secs, 1), "ai_secs": round(ai_sec, 1), "tool_secs": round(tool_sec, 1),
               "done": bool(parsed and parsed.get("done")), "gates": gates, "backups": log["backups"], "do": log["do"],
               "undo": log["undo"], "model": self.model}
        try:
            with RUNS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
        lines = [f"入口: agent（{self.model}・往復 {turns}・{secs:.1f} 秒＝AI {ai_sec:.1f}・道具 {tool_sec:.1f}）",
                 report.strip() or "（報告なし）"]
        if ask_human or log["ok_stripped"]:
            lines.append("【人に判断してほしいこと】")
            lines += [f"- {x}" for x in ask_human]
            if log["ok_stripped"]:
                lines.append("- 消す・上書きの手は、頼みに承認の言葉が無いので止めました（「消してよい」と言っていただければ撃ちます）")
        if log["changed"]:
            lines.append("変わった所: " + " ／ ".join(log["changed"][:6]) + (f"（ほか {len(log['changed']) - 6} 件）" if len(log["changed"]) > 6 else ""))
        if log["backups"]:
            lines.append(f"控え: #{'・#'.join(log['backups'])}（新しい順に ws_undo で戻せます）")
        lines.append(f"関所の差し戻し: 落とし物 {gates['落とし物']}・仕上げ検査 {gates['仕上げ検査']}・採点 {gates['採点']} ＝ {verdict}")
        return "\n".join(lines)

    def _grade(self, request, target, sheet, report):
        try:
            now = self.mgr.look(target=target, sheet=sheet, range="A1:Z60")
            g = _Session(self.model, GRADE_PROMPT)
            try:
                raw = g.ask(f"【頼み】\n{request}\n\n【今の現物】\n{_cap(now, 6000)}\n\n【担当者の報告】\n{report}\n\nJSON 1 個で。", timeout=AI_TIMEOUT)
            finally:
                g.close()
            d = json.loads(ws_window_ai._strip_json_fence(raw))
            return [str(x) for x in (d.get("unmet") or []) if str(x).strip()][:5]
        except Exception:
            return []


def runs(n=20):
    """本番の走行台帳（新しい順）"""
    if not RUNS_PATH.exists():
        return "走行の記録はまだありません。"
    rows = [json.loads(x) for x in RUNS_PATH.read_text(encoding="utf-8").splitlines() if x.strip()][-n:]
    out = []
    for r in reversed(rows):
        g = r.get("gates") or {}
        out.append(f"{r['time']}  {r.get('sheet', '')}  「{r['request'][:30]}」  往復 {r['turns']}・{r['secs']} 秒・"
                   f"{'done' if r.get('done') else '未完'}・関所 {sum(g.values())}・控え {'・'.join(r.get('backups') or []) or 'なし'}")
    return "\n".join(out)
