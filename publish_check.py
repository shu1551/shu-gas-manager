#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_check.py - ガスマネージャー (gas-manager) GitHub公開前機械検査スクリプト
公開対象ファイルにローカル固有パス・認証トークン・不要な一時ファイルが混入していないか検査し、
オフライン単体テスト (pytest) を全件実行して公開可否を判定します。
"""

import os
import re
import sys
import time
import subprocess
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent

# GitHub に公開する正本ファイル一覧（ホワイトリスト）
PUBLIC_FILES = [
    ".gitignore",
    "LICENSE",
    "README.md",
    "SKILL.md",
    "requirements.txt",
    "gas.py",
    "gas_client.py",
    "gas_mcp_server.py",
    "gas_workspace.py",
    "gas_workspace_view.py",
    "workspace_engine.gs",
    "gas_ws_catalog.py",
    "ws_shelves/doc.gs",
    "ws_shelves/sheet_filter.gs",
    "ws_shelves/sheet_look.gs",
    "ws_shelves/sheet_make.gs",
    "ws_shelves/sheet_range.gs",
    "ws_shelves/sheet_rows.gs",
    "ws_shelves/sheet_sheet.gs",
    "test_gas_ws_catalog.py",
    "gas_ws_find.py",
    "gas_ws_check.py",
    "gas_ws_api.py",
    "ws_shelves/api.gs",
    "ws_exam/phrases_api.tsv",
    "test_gas_ws_api.py",
    "test_gas_ws_wide.py",
    "gas_ws_exam.py",
    "test_gas_ws_exam.py",
    "ws_shelves/guide.txt",
    "ws_shelves/synonyms.txt",
    "ws_exam/answers.tsv",
    "test_gas_ws_find.py",
    "ws_exam/phrases_ijiwaru.tsv",
    "ws_exam/phrases_シート.tsv",
    "ws_exam/phrases_作る.tsv",
    "ws_exam/phrases_整える.tsv",
    "ws_exam/phrases_文書.tsv",
    "ws_exam/phrases_範囲.tsv",
    "ws_exam/phrases_絞る.tsv",
    "ws_exam/phrases_行と列.tsv",
    "ws_exam/phrases_見た目.tsv",
    "ws_exam/phrases_集計.tsv",
    "WORKSPACE.md",
    "test_gas_offline.py",
    "test_client.py",
    "verify_gas_manager.py",
    "publish_check.py",
    "axe.min.js",
    "queue/README.md",
    "queue/001_sample_テンプレート指示書.md",
]

# 公開ファイル内に1件でも残っていたらNGとする禁止パターン
FORBID_PATTERNS = [
    (r"C:\\Users\\shu|C:/Users/shu|D:\\エクセル|shu1551@", "ローカル個人パス・メールアドレス"),
    (r"AIza[0-9A-Za-z_-]{30,}|GOCSPX-[0-9A-Za-z_-]{20,}|ya29\.[0-9A-Za-z_-]{20,}", "Google APIキー / OAuthシークレット"),
    (r"\?{3,}", "文字化け (クエスチョン3連続)"),
    (r"ws_tria[l]/|Tria[l]\.gs|\.ws_tria[l]\.json|WS試験_", "試験用の物（試験の入口・試験場・ws_trial）"),
]


def main():
    t0 = time.perf_counter()
    bad = 0

    # 1. 必須公開ファイルの存在確認
    missing = [f for f in PUBLIC_FILES if not (HERE / f).is_file()]
    if missing:
        for m in missing:
            print(f"  [NG] 公開必須ファイルが見つかりません: {m}")
        bad += len(missing)

    # 2. 禁止文字列（個人パス・トークン・文字化け）スキャン
    checked_count = 0
    for fname in PUBLIC_FILES:
        fpath = HERE / fname
        if not fpath.is_file() or fname == "publish_check.py":
            continue
        checked_count += 1
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for pat, reason in FORBID_PATTERNS:
            if fname == ".gitignore" and reason.startswith("試験用の物"):
                continue          # .gitignore は試験用の物を git に入れないために名前を書く
            for m in re.finditer(pat, text):
                line_no = text.count("\n", 0, m.start()) + 1
                print(f"  [NG] {fname}:{line_no} に禁止パターン ({reason}): 「{m.group(0)}」")
                bad += 1


    # 2b. 誇張の語・強すぎる言葉の禁止検査 (指示書109)
    STRONG_WORDS = ["怪物", "爆速", "極限", "100%", "完全", "絶対", "根絶", "撲滅", "SaaS級", "最高峰", "一撃"]
    STRONG_TARGET_FILES = ["SKILL.md", "README.md", "gas_mcp_server.py", "gas.py"]
    for fname in STRONG_TARGET_FILES:
        fpath = HERE / fname
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for word in STRONG_WORDS:
            for m in re.finditer(re.escape(word), text):
                line_no = text.count("\n", 0, m.start()) + 1
                print(f"  [NG] {fname}:{line_no} に誇張の禁止語: 「{m.group(0)}」")
                bad += 1

    # 3. .gitignore の保護対象確認 ＆ ホワイトリスト外ファイル混入検査
    gitignore_text = (HERE / ".gitignore").read_text(encoding="utf-8", errors="replace") if (HERE / ".gitignore").is_file() else ""
    for must_ignore in ("aliases.json", ".backups/", ".cache.json", ".content_cache.json", ".last_run.json", ".gas-sync.json", ".clasprc.json"):
        if must_ignore not in gitignore_text:
            print(f"  [NG] .gitignore に '{must_ignore}' が含まれていません")
            bad += 1

    allowed_local = set(PUBLIC_FILES) | {"queue", ".git", ".backups", ".pytest_cache", "__pycache__", ".cache.json", ".content_cache.json", ".last_run.json", ".gas-sync.json", ".ws_state.json", ".mocks", "screenshots", "gas_local_extras.py", "aliases.json", "index_restored.html",
                                                  # 公開しない物（試験の道具・試験場の記録・手元の記録）。公開物に入らないことは、ホワイトリストと上の禁止パターンで見る
                                                  "ws_exam", "ws_shelves", "ws_trial", "gas_ws_judge.py", "gas_ws_tables.py", "gas_ws_trial.py", "test_gas_ws_trial.py", "gas_ws_props.py", "gas_ws_shot.py", "test_gas_ws_props.py", "test_gas_ws_shot.py", "test_gas_ws_undo_side.py", "test_gas_ws_speed.py", "test_gas_ws_lane.py",
                                                  ".ws_engine_all.gs", ".ws_trial.json", ".ws_api_uses.tsv", ".ws_misses.tsv", ".ws_ledger.json"}
    for item in HERE.iterdir():
        if item.name not in allowed_local:
            print(f"  [NG] 公開ホワイトリスト外の未知のファイル/フォルダが存在します: {item.name}")
            bad += 1

    # 4. pytest 単体テスト実行
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test_gas_offline.py", "-q", "-p", "no:cacheprovider"],
        cwd=str(HERE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **( {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else {} )
    )
    out_lines = (r.stdout or "").strip().splitlines()
    summary = out_lines[-1] if out_lines else "no output"
    if r.returncode != 0:
        print(f"  [NG] pytest 失敗:\n{r.stdout}\n{r.stderr}")
        bad += 1

    elapsed = time.perf_counter() - t0
    status = "合格 (READY FOR GITHUB)" if bad == 0 else f"要修正 ({bad} 件の問題)"
    print(f"公開前検査: {status} （検査 {checked_count} ファイル・残り {bad} 件・pytest: {summary}・所要 {elapsed:.2f}秒）")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
