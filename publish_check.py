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
    "test_gas_offline.py",
    "test_client.py",
    "verify_gas_manager.py",
    "publish_check.py",
    "queue/README.md",
    "queue/001_sample_テンプレート指示書.md",
]

# 公開ファイル内に1件でも残っていたらNGとする禁止パターン
FORBID_PATTERNS = [
    (r"C:\\Users\\shu|C:/Users/shu|D:\\エクセル|shu1551@", "ローカル個人パス・メールアドレス"),
    (r"AIza[0-9A-Za-z_-]{30,}|GOCSPX-[0-9A-Za-z_-]{20,}|ya29\.[0-9A-Za-z_-]{20,}", "Google APIキー / OAuthシークレット"),
    (r"\?{3,}", "文字化け (クエスチョン3連続)"),
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
            for m in re.finditer(pat, text):
                line_no = text.count("\n", 0, m.start()) + 1
                print(f"  [NG] {fname}:{line_no} に禁止パターン ({reason}): 「{m.group(0)}」")
                bad += 1

    # 3. .gitignore の保護対象確認 ＆ ホワイトリスト外ファイル混入検査
    gitignore_text = (HERE / ".gitignore").read_text(encoding="utf-8", errors="replace") if (HERE / ".gitignore").is_file() else ""
    for must_ignore in (".backups/", ".cache.json", ".content_cache.json", ".gas-sync.json", ".clasprc.json"):
        if must_ignore not in gitignore_text:
            print(f"  [NG] .gitignore に '{must_ignore}' が含まれていません")
            bad += 1

    allowed_local = set(PUBLIC_FILES) | {"queue", ".git", ".backups", ".pytest_cache", "__pycache__", ".cache.json", ".content_cache.json", ".gas-sync.json"}
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
