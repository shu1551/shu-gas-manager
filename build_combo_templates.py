#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_combo_templates.py - combo_ui_parts/ と combo_server_parts/ から
combo_sidebar_template.html / combo_server_template.gs を決定論的に生成・同期検証するスクリプト。
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

UI_PARTS_DIR = HERE / "combo_ui_parts"
UI_TARGET = HERE / "combo_sidebar_template.html"
UI_PARTS = [
    "01_head_styles.html",
    "02_body.html",
    "03_state_direct.js",
    "04_actions_events.js",
    "05_mymacro_init.js",
]

SERVER_PARTS_DIR = HERE / "combo_server_parts"
SERVER_TARGET = HERE / "combo_server_template.gs"
SERVER_PARTS = [
    "01_core_init.gs",
    "02_ops_exec.gs",
    "03_ai_postbox.gs",
    "04_mymacro_quick.gs",
]


def render_from_parts(parts_dir: Path, part_names: list[str]) -> str:
    chunks = []
    for name in part_names:
        p = parts_dir / name
        if not p.is_file():
            raise FileNotFoundError(f"部品ファイルが見つかりません: {p}")
        chunks.append(p.read_text(encoding="utf-8"))
    return "".join(chunks)


def check_sync() -> list[str]:
    problems = []
    for label, parts_dir, part_names, target in (
        ("ComboSidebar", UI_PARTS_DIR, UI_PARTS, UI_TARGET),
        ("ComboServer", SERVER_PARTS_DIR, SERVER_PARTS, SERVER_TARGET),
    ):
        if not target.is_file():
            problems.append(f"{label}: 生成先ファイルが見つかりません ({target.name})")
            continue
        try:
            rendered = render_from_parts(parts_dir, part_names)
        except FileNotFoundError as e:
            problems.append(f"{label}: {e}")
            continue
        actual = target.read_text(encoding="utf-8")
        if rendered != actual:
            problems.append(
                f"{label}: 部品と {target.name} の内容が一致しません（py build_combo_templates.py --build を実行してください）"
            )
    return problems


def build_all() -> None:
    for parts_dir, part_names, target in (
        (UI_PARTS_DIR, UI_PARTS, UI_TARGET),
        (SERVER_PARTS_DIR, SERVER_PARTS, SERVER_TARGET),
    ):
        rendered = render_from_parts(parts_dir, part_names)
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"[BUILT] {target.name} ({len(rendered)} chars)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GASコンボ テンプレート部品の結合・同期検証")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--build", action="store_true", help="部品からテンプレートファイルを再生成する")
    group.add_argument("--check", action="store_true", help="部品とテンプレートファイルの一致を検査する")
    args = parser.parse_args(argv)

    if args.build:
        build_all()
        return 0
    problems = check_sync()
    if problems:
        for p in problems:
            print(f"[NG] {p}")
        return 1
    print("[OK] combo_ui_parts / combo_server_parts とテンプレートファイルは完全一致しています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
