# -*- coding: utf-8 -*-
"""GasClient 高速化レシピ・骨格・33棚・デザイン Mixin。"""

import collections
import copy
import difflib
import json
import re
from gas_client_common import _dep_report_line, _track_sid_op


def _gc():
    import gas_client
    return gas_client


class GasClientRecipesMixin:
    @_track_sid_op
    def design_skin(self, project: str, filename: str = "Index", preset: str = "linear", deploy: bool = False) -> dict:
        """
        HTMLファイルにプロ仕様の視覚レイヤー（CSS変数・タイポグラフィ・8pxグリッド・多層シャドウ・半透明サーフェス）を安全に注入・着せ替えします。
        """
        sid = self.resolve_script_id(project)
        content = self.get_content(sid)
        files = content.get('files', []) if isinstance(content, dict) else []
        
        target_file = None
        clean_name = (filename or "Index").replace(".html", "").replace(".HTML", "")
        for f in files:
            fname = f.get("name", "")
            ftype = f.get("type", "")
            if ftype == "HTML" and (fname.lower() == clean_name.lower() or fname.lower() == (filename or "Index").lower()):
                target_file = f
                break
        if not target_file:
            for f in files:
                if f.get("type") == "HTML":
                    target_file = f
                    break
        if not target_file:
            return {"success": False, "error": f"プロジェクト内に HTML ファイルが見つかりません: {filename}"}
        
        target_fname = target_file.get("name", "")
        html_src = target_file.get("source", "")
        preset_key = (preset or "linear").lower().strip()
        if preset_key in ("saas", "modern"): preset_key = "linear"
        if preset_key in ("apple", "acrylic"): preset_key = "glass"
        if preset_key in ("minimal", "clean"): preset_key = "notion"
        if preset_key in ("fintech", "stripe", "supabase"): preset_key = "emerald"

        PRESETS = {
            "linear": {
                "name": "Linear / Modern SaaS",
                "desc": "スレート系ダーク＆ライト・洗練タイポグラフィ・多層ソフトシャドウ・半透明ボーダー",
                "dark_body": """
            /* --- 1. タイポグラフィ階層 (Typography Hierarchy) --- */
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-sub: #64748b;

            /* --- 2. 背景・半透明サーフェス (Subtle Surface & Elevation) --- */
            --bg-body: #0b0f19;
            --surface: rgba(30, 41, 59, 0.7);
            --surface-hover: rgba(51, 65, 85, 0.8);
            --card-bg: rgba(15, 23, 42, 0.65);
            --card-border: rgba(255, 255, 255, 0.08);
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.16);
            --border-focus: #38bdf8;

            /* --- 3. プライマリ＆アクセント (Color & Identity) --- */
            --primary: #3b82f6;
            --primary-glow: rgba(59, 130, 246, 0.35);
            --accent: #38bdf8;

            /* --- 4. 空気感のある多層ソフトシャドウ (Soft Layered Shadows) --- */
            --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.15);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.25), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
            --shadow-float: 0 12px 24px -4px rgba(0, 0, 0, 0.4), 0 4px 8px -2px rgba(0, 0, 0, 0.25);
            --shadow: rgba(0, 0, 0, 0.4);

            /* --- 5. 8pxグリッド余白＆角丸秩序 (Spacing & Border Radius) --- */
            --space-unit: 8px;
            --card-padding: 14px 18px;
            --card-gap: 8px;
            --radius-container: 12px;
            --radius-card: 8px;
            --radius-btn: 6px;
            --radius-badge: 9999px;

            /* --- 6. マイクロインタラクション (Micro-interactions) --- */
            --transition-fast: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
            --hover-lift: translateY(-1px);

            /* --- 既存互換エイリアス --- */
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
""",
                "light_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #0f172a;
            --text-muted: #475569;
            --text-sub: #94a3b8;
            --bg-body: #f8fafc;
            --surface: rgba(255, 255, 255, 0.8);
            --surface-hover: rgba(255, 255, 255, 0.95);
            --card-bg: rgba(255, 255, 255, 0.7);
            --card-border: rgba(0, 0, 0, 0.08);
            --border: rgba(0, 0, 0, 0.08);
            --border-hover: rgba(0, 0, 0, 0.16);
            --border-focus: #0284c7;
            --primary: #2563eb;
            --primary-glow: rgba(37, 99, 235, 0.2);
            --accent: #0284c7;
            --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -1px rgba(0, 0, 0, 0.04);
            --shadow-float: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -2px rgba(0, 0, 0, 0.04);
            --shadow: rgba(0, 0, 0, 0.08);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
"""
            },
            "glass": {
                "name": "Apple / Acrylic Glass",
                "desc": "上質なフロストガラス・ブラー表現・エレガントな半透明パレット",
                "dark_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            --text-main: #ffffff;
            --text-muted: rgba(235, 235, 245, 0.6);
            --text-sub: rgba(235, 235, 245, 0.38);
            --bg-body: #000000;
            --surface: rgba(30, 30, 32, 0.65);
            --surface-hover: rgba(45, 45, 50, 0.75);
            --card-bg: rgba(24, 24, 26, 0.55);
            --card-border: rgba(255, 255, 255, 0.12);
            --border: rgba(255, 255, 255, 0.12);
            --border-hover: rgba(255, 255, 255, 0.24);
            --border-focus: #2997ff;
            --primary: #2997ff;
            --primary-glow: rgba(41, 151, 255, 0.3);
            --accent: #5e5ce6;
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.25);
            --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.35);
            --shadow-float: 0 16px 36px rgba(0, 0, 0, 0.5);
            --shadow: rgba(0, 0, 0, 0.4);
            --glass-blur: 20px;
            --space-unit: 8px;
            --card-padding: 16px 20px;
            --card-gap: 10px;
            --radius-container: 16px;
            --radius-card: 12px;
            --radius-btn: 8px;
            --radius-badge: 9999px;
            --transition-fast: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1);
            --hover-lift: translateY(-2px);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: rgba(0, 0, 0, 0.8);
""",
                "light_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            --text-main: #1d1d1f;
            --text-muted: #86868b;
            --text-sub: #a1a1a6;
            --bg-body: #f5f5f7;
            --surface: rgba(255, 255, 255, 0.7);
            --surface-hover: rgba(255, 255, 255, 0.85);
            --card-bg: rgba(255, 255, 255, 0.6);
            --card-border: rgba(0, 0, 0, 0.08);
            --border: rgba(0, 0, 0, 0.08);
            --border-hover: rgba(0, 0, 0, 0.18);
            --border-focus: #0071e3;
            --primary: #0071e3;
            --primary-glow: rgba(0, 113, 227, 0.2);
            --accent: #5856d6;
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.04);
            --shadow-md: 0 8px 20px rgba(0, 0, 0, 0.06);
            --shadow-float: 0 16px 32px rgba(0, 0, 0, 0.08);
            --shadow: rgba(0, 0, 0, 0.06);
            --glass-blur: 20px;
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: rgba(245, 245, 247, 0.8);
"""
            },
            "notion": {
                "name": "Notion / Minimal Clean",
                "desc": "知的なモノトーン・削ぎ落とされた端正なレイアウト・紙のような質感",
                "dark_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #e6e6e6;
            --text-muted: #9b9b9b;
            --text-sub: #6f6f6f;
            --bg-body: #191919;
            --surface: #202020;
            --surface-hover: #2a2a2a;
            --card-bg: #202020;
            --card-border: rgba(255, 255, 255, 0.09);
            --border: rgba(255, 255, 255, 0.09);
            --border-hover: rgba(255, 255, 255, 0.2);
            --border-focus: #ffffff;
            --primary: #ffffff;
            --primary-glow: rgba(255, 255, 255, 0.2);
            --accent: #e16259;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
            --shadow-md: 0 3px 6px rgba(0, 0, 0, 0.3);
            --shadow-float: 0 8px 16px rgba(0, 0, 0, 0.4);
            --shadow: rgba(0, 0, 0, 0.3);
            --space-unit: 8px;
            --card-padding: 12px 16px;
            --card-gap: 6px;
            --radius-container: 8px;
            --radius-card: 6px;
            --radius-btn: 4px;
            --radius-badge: 4px;
            --transition-fast: all 0.12s ease-in-out;
            --hover-lift: translateY(-1px);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
""",
                "light_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #37352f;
            --text-muted: #787774;
            --text-sub: #9b9a97;
            --bg-body: #ffffff;
            --surface: #f7f6f3;
            --surface-hover: #efeee9;
            --card-bg: #ffffff;
            --card-border: rgba(55, 53, 47, 0.09);
            --border: rgba(55, 53, 47, 0.09);
            --border-hover: rgba(55, 53, 47, 0.2);
            --border-focus: #37352f;
            --primary: #37352f;
            --primary-glow: rgba(55, 53, 47, 0.15);
            --accent: #eb5757;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
            --shadow-md: 0 2px 4px rgba(0, 0, 0, 0.06);
            --shadow-float: 0 6px 12px rgba(0, 0, 0, 0.08);
            --shadow: rgba(0, 0, 0, 0.04);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
"""
            },
            "emerald": {
                "name": "Supabase / Emerald Fintech",
                "desc": "知的なディープダーク・洗練されたエメラルドグリーンアクセント",
                "dark_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #ededed;
            --text-muted: #8c8c8c;
            --text-sub: #595959;
            --bg-body: #121212;
            --surface: #1a1a1a;
            --surface-hover: #242424;
            --card-bg: #171717;
            --card-border: #262626;
            --border: #262626;
            --border-hover: #404040;
            --border-focus: #10b981;
            --primary: #10b981;
            --primary-glow: rgba(16, 185, 129, 0.3);
            --accent: #34d399;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.4);
            --shadow-float: 0 12px 20px rgba(0, 0, 0, 0.5);
            --shadow: rgba(0, 0, 0, 0.4);
            --space-unit: 8px;
            --card-padding: 14px 18px;
            --card-gap: 8px;
            --radius-container: 10px;
            --radius-card: 8px;
            --radius-btn: 6px;
            --radius-badge: 9999px;
            --transition-fast: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
            --hover-lift: translateY(-1px);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
""",
                "light_body": """
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --text-main: #171717;
            --text-muted: #737373;
            --text-sub: #a3a3a3;
            --bg-body: #fafafa;
            --surface: #ffffff;
            --surface-hover: #f5f5f5;
            --card-bg: #ffffff;
            --card-border: #e5e5e5;
            --border: #e5e5e5;
            --border-hover: #d4d4d4;
            --border-focus: #059669;
            --primary: #059669;
            --primary-glow: rgba(5, 150, 105, 0.2);
            --accent: #10b981;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.08);
            --shadow-float: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            --shadow: rgba(0, 0, 0, 0.05);
            --bg: var(--bg-body);
            --text: var(--text-main);
            --header-bg: var(--bg-body);
"""
            }
        }

        selected = PRESETS.get(preset_key, PRESETS["linear"])
        patches = []

        # 1. :root ブロックの置換
        match_root = re.search(r':root\s*\{([^}]+)\}', html_src)
        if match_root:
            old_root = match_root.group(0)
            new_root = f":root {{{selected['dark_body']}\n        }}"
            patches.append({"target": old_root, "replacement": new_root})
        else:
            match_style = re.search(r'<style[^>]*>', html_src, re.IGNORECASE)
            if match_style:
                old_style = match_style.group(0)
                new_style = f"{old_style}\n        :root {{{selected['dark_body']}\n        }}\n"
                patches.append({"target": old_style, "replacement": new_style})

        # 2. ライトテーマブロック ([data-theme="light"] または body.light-mode) の置換
        match_light = re.search(r'(\[data-theme=["\']light["\']\]|body\.light-mode)\s*\{([^}]+)\}', html_src)
        if match_light:
            old_light = match_light.group(0)
            selector = match_light.group(1)
            new_light = f"{selector} {{{selected['light_body']}\n        }}"
            patches.append({"target": old_light, "replacement": new_light})
        elif match_root and selected.get("light_body"):
            new_light_block = f'\n\n        [data-theme="light"] {{{selected["light_body"]}\n        }}'
            if patches:
                patches[0]["replacement"] = patches[0]["replacement"] + new_light_block

        if not patches:
            match_head_close = re.search(r'</head>', html_src, re.IGNORECASE)
            if match_head_close:
                head_tag = match_head_close.group(0)
                new_block = f"  <style>\n    :root {{{selected['dark_body']}\n    }}\n  </style>\n{head_tag}"
                patches.append({"target": head_tag, "replacement": new_block})
            else:
                return {"success": False, "error": "HTML内に <style>, :root または </head> タグが見つかりませんでした"}

        res = self.patch_code(script_id=sid, filename=target_fname, patches=json.dumps(patches), deploy=deploy)
        if res.get("status") != "success" and not res.get("success"):
            return res

        return {
            "success": True,
            "project": project,
            "filename": target_fname,
            "preset": preset_key,
            "preset_name": selected["name"],
            "desc": selected["desc"],
            "deployed": deploy,
            "patches_applied": len(patches)
        }


    def list_recipes(self) -> dict:
        """GAS 高速化レシピ棚 全12種の一覧とレポートを取得"""
        lines = [
            "=== ⚡ GAS 高速化レシピ棚カタログ (全12種) ===",
            "| レシピID | レシピ名 | 自動適用 | 概要 | キーワード |",
            "| --- | --- | --- | --- | --- |"
        ]
        for r in _gc().GAS_SPEEDUP_RECIPES:
            apply_str = "✅ 対応" if r.get("auto_apply") else "手動（処方コード提示）"
            kw_str = ", ".join(r.get("keywords", []))
            lines.append(f"| {r['id']} | {r['name']} | {apply_str} | {r['desc']} | {kw_str} |")
        return {
            "recipes": _gc().GAS_SPEEDUP_RECIPES,
            "count": len(_gc().GAS_SPEEDUP_RECIPES),
            "markdown_report": "\n".join(lines)
        }


    def match_recipe_by_text(self, query: str) -> list:
        """頼み文（日本語・英語）から最適な高速化レシピ棚をマッチングしてスコア順に返す"""
        if not query:
            return []
        q_lower = query.lower()
        scored = []
        for r in _gc().GAS_SPEEDUP_RECIPES:
            score = 0
            if r["id"].lower() in q_lower:
                score += 10
            if r["name"].lower() in q_lower:
                score += 8
            for kw in r.get("keywords", []):
                kw_low = kw.lower()
                if kw_low in q_lower:
                    score += 5
                elif any(tok in kw_low for tok in q_lower.split() if len(tok) >= 2):
                    score += 2
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored]


    @_track_sid_op
    def gas_recipe(self, script_id="", filename="", func_name="", recipe_id="", apply=False, ttl=300, deploy=False, ask="", list_only=False):
        """GAS 高速化レシピ棚（頻出パターンの検出・処方コード生成・自動変換・自然言語直撃）"""
        if list_only:
            return self.list_recipes()

        matched_info_str = ""
        matched_recipes = []
        if ask:
            matched_recipes = self.match_recipe_by_text(ask)
            if not recipe_id and matched_recipes:
                recipe_id = matched_recipes[0]["id"]
            matched_ids_str = ", ".join(f"{m['id']}({m['name']})" for m in matched_recipes) if matched_recipes else "該当なし"
            matched_info_str = f"💡 頼み文「{ask}」からの判定: {matched_ids_str}"

        if not script_id:
            # プロジェクト未指定かつ ask のみの場合、判定結果をレポートとして即答
            lines = [
                "=== ⚡ GAS 高速化レシピ棚 (GAS RECIPE) ===",
                matched_info_str if matched_info_str else "プロジェクト名またはスクリプトIDを指定してください。"
            ]
            return {
                "script_id": "",
                "detections": [],
                "applied_results": [],
                "matched_recipes": matched_recipes,
                "markdown_report": "\n".join(lines)
            }

        sid = self.resolve_script_id(script_id)
        content = self.get_content(sid, use_cache=not apply)
        files = content.get("files", [])

        target_files = [f for f in files if f.get("type") == "SERVER_JS"]
        if filename:
            target_files = [f for f in target_files if f.get("name") == filename]

        detections = []
        applied_results = []

        for f in target_files:
            fname = f.get("name", "")
            source = f.get("source", "")
            raw_funcs = self._extract_functions_from_js(source, 0)

            for fn_info in raw_funcs:
                curr_fn_name = fn_info["name"]
                if func_name and curr_fn_name != func_name:
                    continue

                if "start_pos" in fn_info and "end_pos" in fn_info:
                    abs_start, abs_end = fn_info["start_pos"], fn_info["end_pos"]
                else:
                    abs_start, abs_end = self._get_function_absolute_span(f, curr_fn_name)
                fn_source = source[abs_start:abs_end]

                # R01: ループ内 appendRow
                if not recipe_id or recipe_id == "R01":
                    r01_pat = re.compile(r"([A-Za-z0-9_$]+)\s*\.\s*appendRow\s*\(([^;\n]+?)\)\s*;?")
                    loop_m = re.search(r"\b(for|while)\s*\([^{]+\)\s*\{([\s\S]+?)\}", fn_source)
                    if loop_m and r01_pat.search(loop_m.group(2)):
                        ap_m = r01_pat.search(loop_m.group(2))
                        sheet_var = ap_m.group(1)
                        arg_expr = ap_m.group(2).strip()

                        old_loop = loop_m.group(0)
                        body_replaced = r01_pat.sub(f"__batchRows.push({arg_expr});", loop_m.group(2))
                        new_loop = (
                            f"const __batchRows = [];\n  "
                            f"{loop_m.group(1)} {old_loop[len(loop_m.group(1)):old_loop.find('{') + 1]}"
                            f"{body_replaced}"
                            f"}}\n  "
                            f"if (__batchRows.length > 0) {{\n    "
                            f"{sheet_var}.getRange({sheet_var}.getLastRow() + 1, 1, __batchRows.length, __batchRows[0].length).setValues(__batchRows);\n  }}"
                        )
                        transformed_code = fn_source.replace(old_loop, new_loop, 1)
                        line_no = source.count('\n', 0, abs_start) + 1
                        det = {
                            "recipe_id": "R01",
                            "recipe_name": "append_row_batch",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で {sheet_var}.appendRow が呼ばれています。setValues で配列一括追記化できます。",
                            "transformed_code": transformed_code
                        }
                        detections.append(det)

                        if apply:
                            res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                            applied_results.append({
                                "recipe_id": "R01",
                                "file": fname,
                                "function": curr_fn_name,
                                "status": res.get("status"),
                                "diff": res.get("diff")
                            })

                # R02: ループ内 getValue / setValue
                if not recipe_id or recipe_id == "R02":
                    if re.search(r"\b(for|while)\s*\([^{]+\)\s*\{[\s\S]*?\.(?:getValue|setValue)\s*\([\s\S]*?\}", fn_source):
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: getValues / setValues 一括化】\n"
                            "const data = sheet.getDataRange().getValues();\n"
                            "for (let i = 0; i < data.length; i++) {\n"
                            "  // data[i][col] を読み書き\n"
                            "}\n"
                            "sheet.getDataRange().setValues(data);"
                        )
                        detections.append({
                            "recipe_id": "R02",
                            "recipe_name": "sheet_values_batch",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で getValue/setValue が呼ばれています。2次元配列で一括処理してください。",
                            "snippet": snippet
                        })

                # R03: ループ内 UrlFetchApp.fetch
                if not recipe_id or recipe_id == "R03":
                    if re.search(r"\b(for|while)\s*\([^{]+\)\s*\{[\s\S]*?UrlFetchApp\.fetch\s*\((?!All)[\s\S]*?\}", fn_source):
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: UrlFetchApp.fetchAll 並列化】\n"
                            "const requests = urls.map(u => ({ url: u, muteHttpExceptions: true }));\n"
                            "const responses = UrlFetchApp.fetchAll(requests);\n"
                            "const results = responses.map(r => r.getContentText());"
                        )
                        detections.append({
                            "recipe_id": "R03",
                            "recipe_name": "urlfetch_parallel",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で UrlFetchApp.fetch が直列呼出されています。fetchAll で並列一括送信できます。",
                            "snippet": snippet
                        })

                # R04: CacheService キャッシュ包装
                if not recipe_id or recipe_id == "R04":
                    has_read = bool(re.search(r"\b(?:getValues|UrlFetchApp\.fetch)\b", fn_source))
                    has_write = bool(re.search(r"\b(?:setValue|setValues|appendRow|deleteRow|clear|sendEmail|moveToTrash)\b", fn_source))
                    has_cache = "CacheService" in fn_source
                    if has_read and not has_write and not has_cache:
                        body_start = fn_source.find('{')
                        if body_start != -1:
                            cache_header = (
                                f"\n  const __cache = CacheService.getScriptCache();\n"
                                f"  const __ckey = \"{curr_fn_name}_\" + JSON.stringify(Array.from(arguments));\n"
                                f"  const __cached = __cache.get(__ckey);\n"
                                f"  if (__cached !== null) {{\n"
                                f"    try {{ return JSON.parse(__cached); }} catch (_) {{}}\n"
                                f"  }}\n"
                            )
                            fn_body = fn_source[body_start + 1:]
                            ret_m = re.search(r"return\s+([^;]+?);", fn_body)
                            if ret_m:
                                ret_expr = ret_m.group(1).strip()
                                new_ret = (
                                    f"const __ret = {ret_expr};\n"
                                    f"  __cache.put(__ckey, JSON.stringify(__ret), {ttl});\n"
                                    f"  return __ret;"
                                )
                                new_body = fn_body[:ret_m.start()] + new_ret + fn_body[ret_m.end():]
                                transformed_code = fn_source[:body_start + 1] + cache_header + new_body
                                line_no = source.count('\n', 0, abs_start) + 1
                                det = {
                                    "recipe_id": "R04",
                                    "recipe_name": "cache_service_wrap",
                                    "file": fname,
                                    "function": curr_fn_name,
                                    "line": line_no,
                                    "reason": f"読み取り関数 '{curr_fn_name}' に CacheService キャッシュを導入することで2回目以降の呼び出しを瞬時に完了できます。",
                                    "transformed_code": transformed_code
                                }
                                detections.append(det)

                                if apply:
                                    res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                                    applied_results.append({
                                        "recipe_id": "R04",
                                        "file": fname,
                                        "function": curr_fn_name,
                                        "status": res.get("status"),
                                        "diff": res.get("diff")
                                    })

                # R05: ループ内 PropertiesService.getProperty
                if not recipe_id or recipe_id == "R05":
                    prop_pat = re.compile(r"([A-Za-z0-9_$.()]+)\.getProperty\s*\(([^)]+)\)")
                    loop_m = re.search(r"\b(for|while)\s*\([^{]+\)\s*\{([\s\S]+?)\}", fn_source)
                    if loop_m and prop_pat.search(loop_m.group(2)):
                        old_loop = loop_m.group(0)
                        body_replaced = prop_pat.sub(r"__props[\2]", loop_m.group(2))
                        hoist_header = "const __props = PropertiesService.getScriptProperties().getProperties();\n  "
                        new_loop = hoist_header + loop_m.group(1) + old_loop[len(loop_m.group(1)):old_loop.find('{') + 1] + body_replaced + "}"
                        transformed_code = fn_source.replace(old_loop, new_loop, 1)
                        line_no = source.count('\n', 0, abs_start) + 1
                        det = {
                            "recipe_id": "R05",
                            "recipe_name": "props_cache_hoist",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で getProperty が呼ばれています。PropertiesService.getProperties() で一括巻き上げできます。",
                            "transformed_code": transformed_code
                        }
                        detections.append(det)

                        if apply:
                            res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                            applied_results.append({
                                "recipe_id": "R05",
                                "file": fname,
                                "function": curr_fn_name,
                                "status": res.get("status"),
                                "diff": res.get("diff")
                            })

                # R06: ループ内 thread.getMessages()
                if not recipe_id or recipe_id == "R06":
                    msg_pat = re.compile(r"([A-Za-z0-9_$]+)(?:\[([A-Za-z0-9_$]+)\])?\s*\.\s*getMessages\s*\(\)")
                    loop_m = re.search(r"\b(for|while)\s*\([^{]+\)\s*\{([\s\S]+?)\}", fn_source)
                    if loop_m and msg_pat.search(loop_m.group(2)):
                        old_loop = loop_m.group(0)
                        threads_var = "threads"
                        idx_var = "i"
                        th_m = re.search(r"\bfor\s*\(\s*(?:var|let|const)?\s*(\w+)\s*=\s*0;\s*\1\s*<\s*(\w+)\.length", old_loop)
                        if th_m:
                            idx_var = th_m.group(1)
                            threads_var = th_m.group(2)
                        else:
                            mp = msg_pat.search(loop_m.group(2))
                            if mp and mp.group(2):
                                threads_var = mp.group(1)
                                idx_var = mp.group(2)
                            elif mp and mp.group(1):
                                threads_var = mp.group(1)
                        body_replaced = re.sub(rf"{re.escape(threads_var)}\s*\[\s*{re.escape(idx_var)}\s*\]\s*\.\s*getMessages\s*\(\)", f"__threadMsgs[{idx_var}]", loop_m.group(2))
                        if body_replaced == loop_m.group(2):
                            body_replaced = msg_pat.sub(f"__threadMsgs[{idx_var}]", loop_m.group(2))
                        hoist_header = f"const __threadMsgs = GmailApp.getMessagesForThreads({threads_var});\n  "
                        new_loop = hoist_header + loop_m.group(1) + old_loop[len(loop_m.group(1)):old_loop.find('{') + 1] + body_replaced + "}"
                        transformed_code = fn_source.replace(old_loop, new_loop, 1)
                        line_no = source.count('\n', 0, abs_start) + 1
                        det = {
                            "recipe_id": "R06",
                            "recipe_name": "gmail_threads_batch",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で getMessages が呼ばれています。GmailApp.getMessagesForThreads で一括取得化できます。",
                            "transformed_code": transformed_code
                        }
                        detections.append(det)

                        if apply:
                            res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                            applied_results.append({
                                "recipe_id": "R06",
                                "file": fname,
                                "function": curr_fn_name,
                                "status": res.get("status"),
                                "diff": res.get("diff")
                            })

                # R07: ループ内 setBackground / setFontColor / setNumberFormat
                if not recipe_id or recipe_id == "R07":
                    if re.search(r"\b(for|while)\s*\([^{]+\)\s*\{[\s\S]*?\.(?:setBackground|setFontColor|setFontWeight|setNumberFormat)\s*\([\s\S]*?\}", fn_source):
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: 2次元配列による書式一括設定】\n"
                            "// sheet.getRange(startRow, startCol, numRows, numCols).setBackgrounds(colors2D);\n"
                            "// sheet.getRange(startRow, startCol, numRows, numCols).setFontColors(colors2D);\n"
                            "// sheet.getRange(startRow, startCol, numRows, numCols).setNumberFormats(formats2D);"
                        )
                        detections.append({
                            "recipe_id": "R07",
                            "recipe_name": "sheet_style_batch",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で セル装飾/書式設定 が呼ばれています。setBackgrounds 等の2次元配列で一括装飾してください。",
                            "snippet": snippet
                        })

                # R08: ループ内 deleteRow
                if not recipe_id or recipe_id == "R08":
                    if re.search(r"\b(for|while)\s*\([^{]+\)\s*\{[\s\S]*?\.deleteRow\s*\([\s\S]*?\}", fn_source):
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: deleteRow ループを filter + setValues 一括書き戻しに変換】\n"
                            "const rows = sheet.getDataRange().getValues();\n"
                            "const kept = rows.filter((r, idx) => idx === 0 || !shouldDelete(r));\n"
                            "sheet.clearContents();\n"
                            "if (kept.length > 0) sheet.getRange(1, 1, kept.length, kept[0].length).setValues(kept);"
                        )
                        detections.append({
                            "recipe_id": "R08",
                            "recipe_name": "sheet_delete_row_filter",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で deleteRow が呼ばれています。配列 filter による一括書き戻し化で高速化できます。",
                            "snippet": snippet
                        })

                # R09: ループ内 openById / getSheetByName
                if not recipe_id or recipe_id == "R09":
                    if re.search(r"\b(for|while)\s*\([^{]+\)\s*\{[\s\S]*?(?:SpreadsheetApp\.openBy|\.getSheetByName)\s*\([\s\S]*?\}", fn_source):
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: openById / getSheetByName のループ外巻き上げ】\n"
                            "const ss = SpreadsheetApp.openById(targetId);\n"
                            "const targetSheet = ss.getSheetByName(sheetName);\n"
                            "for (let i = 0; i < items.length; i++) {\n"
                            "  // targetSheet を再利用して処理\n"
                            "}"
                        )
                        detections.append({
                            "recipe_id": "R09",
                            "recipe_name": "spreadsheet_open_hoist",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' のループ内で スプレッドシート/シートの再取得 が呼ばれています。ループ外へ巻き上げてください。",
                            "snippet": snippet
                        })

                # R10: DriveApp.getFiles() 全件走査ループ
                if not recipe_id or recipe_id == "R10":
                    has_iter = bool(re.search(r"\bwhile\s*\([^)]*\.hasNext\s*\(\)[^)]*\)\s*\{[\s\S]*?\.next\s*\(\)", fn_source)) or bool(re.search(r"\.hasNext\s*\(\)[\s\S]*?\.next\s*\(\)", fn_source))
                    has_drive_scan = bool(re.search(r"DriveApp|\.getName\s*\(|\.getMimeType\s*\(", fn_source))
                    if has_iter and has_drive_scan:
                        line_no = source.count('\n', 0, abs_start) + 1
                        snippet = (
                            "// 【処方コード案: searchFiles(query) によるインデックス検索化】\n"
                            "const files = DriveApp.searchFiles(\"title contains 'report' and trashed = false\");\n"
                            "while (files.hasNext()) {\n"
                            "  const f = files.next();\n"
                            "  // 処理\n"
                            "}"
                        )
                        detections.append({
                            "recipe_id": "R10",
                            "recipe_name": "drive_search_query",
                            "file": fname,
                            "function": curr_fn_name,
                            "line": line_no,
                            "reason": f"関数 '{curr_fn_name}' で DriveApp ファイルの全件走査ループが検出されました。searchFiles(query) によるインデックス検索化で高速化できます。",
                            "snippet": snippet
                        })

                # R12: LockService 排他制御
                if not recipe_id or recipe_id == "R12":
                    has_write_ops = bool(re.search(r"\b(?:setValue|setValues|appendRow|deleteRow|clear|sendEmail)\b", fn_source))
                    has_lock = "LockService" in fn_source
                    if (recipe_id == "R12" or has_write_ops) and not has_lock:
                        body_start = fn_source.find('{')
                        body_end = fn_source.rfind('}')
                        if body_start != -1 and body_end != -1 and body_end > body_start:
                            inner_body = fn_source[body_start + 1:body_end]
                            lock_header = (
                                "\n  const __lock = LockService.getScriptLock();\n"
                                "  if (!__lock.tryLock(10000)) return;\n"
                                "  try {"
                            )
                            lock_footer = "\n  } finally {\n    __lock.releaseLock();\n  }\n"
                            transformed_code = fn_source[:body_start + 1] + lock_header + inner_body + lock_footer + fn_source[body_end:]
                            line_no = source.count('\n', 0, abs_start) + 1
                            det = {
                                "recipe_id": "R12",
                                "recipe_name": "lock_and_chunk",
                                "file": fname,
                                "function": curr_fn_name,
                                "line": line_no,
                                "reason": f"関数 '{curr_fn_name}' は LockService による排他ロックが未導入です。多重実行の防止とタイムアウト対策が有効です。",
                                "transformed_code": transformed_code
                            }
                            detections.append(det)

                            if apply and (recipe_id == "R12" or func_name):
                                res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                                applied_results.append({
                                    "recipe_id": "R12",
                                    "file": fname,
                                    "function": curr_fn_name,
                                    "status": res.get("status"),
                                    "diff": res.get("diff")
                                })

                # R13: 指数バックオフ付き自動リトライ包装
                if not recipe_id or recipe_id == "R13":
                    has_external = bool(re.search(r"\b(?:UrlFetchApp\.(?:fetch|fetchAll)|GmailApp\.|MailApp\.|DriveApp\.)\b", fn_source))
                    has_retry = bool(re.search(r"Utilities\.sleep|retry|backoff", fn_source, re.IGNORECASE))
                    if (recipe_id == "R13" or has_external) and not has_retry:
                        body_start = fn_source.find('{')
                        body_end = fn_source.rfind('}')
                        if body_start != -1 and body_end != -1 and body_end > body_start:
                            inner_body = fn_source[body_start + 1:body_end]
                            retry_header = (
                                "\n  const __maxAttempts = 3;\n"
                                "  for (let __attempt = 1; __attempt <= __maxAttempts; __attempt++) {\n"
                                "    try {"
                            )
                            retry_footer = (
                                "\n    } catch (__err) {\n"
                                "      if (__attempt >= __maxAttempts) throw __err;\n"
                                "      Utilities.sleep(Math.pow(2, __attempt) * 500 + Math.floor(Math.random() * 250));\n"
                                "    }\n"
                                "  }\n"
                            )
                            transformed_code = fn_source[:body_start + 1] + retry_header + inner_body + retry_footer + fn_source[body_end:]
                            line_no = source.count('\n', 0, abs_start) + 1
                            detections.append({
                                "recipe_id": "R13",
                                "recipe_name": "retry_backoff",
                                "file": fname,
                                "function": curr_fn_name,
                                "line": line_no,
                                "reason": f"関数 '{curr_fn_name}' で外部通信・サービス呼出にリトライ機構がありません。指数バックオフ再試行で 429/503 や一時エラーへの耐性を高められます。",
                                "transformed_code": transformed_code
                            })
                            if apply and (recipe_id == "R13" or func_name):
                                res = self.replace_function(sid, fname, curr_fn_name, transformed_code, deploy=deploy)
                                applied_results.append({
                                    "recipe_id": "R13",
                                    "file": fname,
                                    "function": curr_fn_name,
                                    "status": res.get("status"),
                                    "diff": res.get("diff")
                                })

        # HTML ファイルの走査 (R11)
        if not recipe_id or recipe_id == "R11":
            html_files = [f for f in files if f.get("type") == "HTML"]
            if filename:
                html_files = [f for f in html_files if f.get("name") == filename]
            for hf in html_files:
                hname = hf.get("name", "")
                hsource = hf.get("source", "")
                rpc_matches = list(re.finditer(r"google\.script\.run", hsource))
                chain_match = re.search(r"withSuccessHandler\s*\([^)]*\)\s*\{[\s\S]*?google\.script\.run", hsource)
                if len(rpc_matches) >= 2 or chain_match:
                    line_no = hsource.count('\n', 0, rpc_matches[0].start()) + 1 if rpc_matches else 1
                    snippet = (
                        "// 【処方コード案: getInitialBundle() によるRPC一括通信 + キャッシュ先行描画】\n"
                        "google.script.run.withSuccessHandler(bundle => {\n"
                        "  renderInitialView(bundle.user, bundle.data, bundle.config);\n"
                        "}).getInitialBundle();"
                    )
                    detections.append({
                        "recipe_id": "R11",
                        "recipe_name": "html_rpc_bundle",
                        "file": hname,
                        "function": "(HTML Script)",
                        "line": line_no,
                        "reason": f"HTMLファイル '{hname}' 内で複数の google.script.run 通信または連鎖呼出が検出されました。1回のRPCバンドル関数化で初期描画を高速化できます。",
                        "snippet": snippet
                    })

        lines = [
            f"=== ⚡ GAS 高速化レシピ棚 (GAS RECIPE): [{script_id}] ==="
        ]
        if matched_info_str:
            lines.append(matched_info_str)
        lines.append(f"検出レシピ数: {len(detections)}件" + (f" | 適用結果: {len(applied_results)}件反映" if apply else ""))
        lines.append("")

        if not detections:
            lines.append("検出された高速化対象パターンはありません（良好な状態です）。")
        else:
            for idx, d in enumerate(detections, 1):
                lines.append(f"### {idx}. [{d['recipe_id']} {d['recipe_name']}] {d['file']}:{d['function']} (L{d['line']})")
                lines.append(f"  - 理由: {d['reason']}")
                if d.get("snippet"):
                    lines.append(f"  - 処方コード案:\n```javascript\n{d['snippet']}\n```")
                elif d.get("transformed_code") and not apply:
                    lines.append(f"  - 変換後コード案:\n```javascript\n{d['transformed_code']}\n```")

        if apply and applied_results:
            lines.append("")
            lines.append("### 🛠️ 自動適用結果 (Applied Diff)")
            for ar in applied_results:
                lines.append(f"  - [{ar['recipe_id']}] {ar['file']}:{ar['function']} -> {ar.get('status', 'success')}")
                if ar.get("diff"):
                    lines.append(f"```diff\n{ar['diff']}\n```")

        md_report = "\n".join(lines)
        return {
            "script_id": sid,
            "detections": detections,
            "applied_results": applied_results,
            "matched_recipes": matched_recipes,
            "markdown_report": md_report
        }


    @_track_sid_op
    def gas_scaffold(self, script_id="", scaffold_id="", filename="Index", server_file="Code", apply=False, deploy=False, list_only=False) -> dict:
        """上級GASアーキテクチャ骨格・部品棚（プレビュー・安全注入・二重防止）"""
        if list_only or not scaffold_id:
            lines = [
                f"=== 🏗️ 上級GASアーキテクチャ骨格棚カタログ (全{len(_gc().GAS_SCAFFOLD_CATALOG)}種) ===",
                "| ID | 部品名 | 対象 | 概要 | キーワード |",
                "| --- | --- | --- | --- | --- |"
            ]
            for s in _gc().GAS_SCAFFOLD_CATALOG:
                kw_str = ", ".join(s.get("keywords", []))
                lines.append(f"| {s['id']} | {s['name']} | {s['target_type']} | {s['desc']} | {kw_str} |")
            return {
                "scaffolds": _gc().GAS_SCAFFOLD_CATALOG,
                "count": len(_gc().GAS_SCAFFOLD_CATALOG),
                "markdown_report": "\n".join(lines)
            }

        target_id = scaffold_id.upper().strip()
        matched = None
        for s in _gc().GAS_SCAFFOLD_CATALOG:
            if s["id"] == target_id or s["name"].lower() == scaffold_id.lower().strip():
                matched = s
                break
        if not matched:
            raise ValueError(f"指定された骨格棚ID '{scaffold_id}' が見つかりません。S01〜S{len(_gc().GAS_SCAFFOLD_CATALOG):02d} または部品名を指定してください。")

        if matched["id"] == "S06":
            return self._gas_scaffold_s06(script_id, apply=apply, deploy=deploy)

        # プレビュー時 (apply=False)
        if not apply:
            if matched["id"] == "S05":
                codes = []
                for s in _gc().GAS_SCAFFOLD_CATALOG[:4]:
                    codes.append(f"// --- [{s['id']}] {s['title']} ({s['target_type']}) ---\n{s['code']}")
                preview_code = "\n\n".join(codes)
            else:
                preview_code = matched["code"]

            lines = [
                f"=== 🏗️ 上級GAS骨格プレビュー: [{matched['id']}] {matched['title']} ===",
                f"対象: {matched['target_type']}",
                f"概要: {matched['desc']}",
                "",
                "### 📝 注入コード案内",
                "```javascript",
                preview_code,
                "```",
                "",
                "💡 実際にプロジェクトへ注入するには apply=True (CLIでは --apply) を指定してください。"
            ]
            return {
                "scaffold": matched,
                "code": preview_code,
                "applied": False,
                "markdown_report": "\n".join(lines)
            }

        # apply=True
        if not script_id:
            raise ValueError("骨格を注入するプロジェクト名またはスクリプトIDを指定してください。")

        sid = self.resolve_script_id(script_id)
        content = self.get_content(sid, use_cache=False)
        files = content.get("files", [])

        to_inject_html = []
        to_inject_server = []

        if matched["id"] == "S01":
            to_inject_html.append(_gc().GAS_SCAFFOLD_CATALOG[0])
        elif matched["id"] == "S02":
            to_inject_html.append(_gc().GAS_SCAFFOLD_CATALOG[1])
        elif matched["id"] == "S03":
            to_inject_html.append(_gc().GAS_SCAFFOLD_CATALOG[2])
        elif matched["id"] == "S04":
            to_inject_server.append(_gc().GAS_SCAFFOLD_CATALOG[3])
        elif matched["id"] == "S05":
            to_inject_html.extend(_gc().GAS_SCAFFOLD_CATALOG[:3])
            to_inject_server.append(_gc().GAS_SCAFFOLD_CATALOG[3])
        elif matched.get("target_type") == "SERVER_JS":
            to_inject_server.append(matched)
        elif matched.get("target_type") == "HTML":
            to_inject_html.append(matched)

        ops = []
        applied_parts = []
        skipped_parts = []

        # HTMLファイルへの注入処理
        if to_inject_html:
            html_file = self._match_file(files, filename)
            html_src = html_file.get("source", "")
            pieces = []
            for item in to_inject_html:
                if item["marker"] in html_src:
                    skipped_parts.append(f"{item['id']} ({item['name']}) [既に注入済み]")
                else:
                    pieces.append(item["code"])
                    applied_parts.append(f"{item['id']} ({item['name']}) -> {html_file['name']}")

            if pieces:
                combined_code = "\n\n".join(pieces)
                last_script_close = [m for m in re.finditer(r"</script>", html_src, re.IGNORECASE)]
                if last_script_close:
                    idx = last_script_close[-1].start()
                    new_html_src = html_src[:idx] + "\n" + combined_code + "\n" + html_src[idx:]
                else:
                    new_html_src = html_src + "\n<script>\n" + combined_code + "\n</script>\n"
                ops.append({
                    "file": html_file["name"],
                    "action": "replace_file",
                    "new_source": new_html_src
                })

        # SERVER_JSファイルへの注入処理
        if to_inject_server:
            js_file = self._match_file(files, server_file)
            js_src = js_file.get("source", "")
            pieces = []
            for item in to_inject_server:
                if item["marker"] in js_src:
                    skipped_parts.append(f"{item['id']} ({item['name']}) [既に注入済み]")
                else:
                    pieces.append(item["code"])
                    applied_parts.append(f"{item['id']} ({item['name']}) -> {js_file['name']}")

            if pieces:
                combined_code = "\n\n".join(pieces)
                new_js_src = js_src.rstrip() + "\n\n" + combined_code + "\n"
                ops.append({
                    "file": js_file["name"],
                    "action": "replace_file",
                    "new_source": new_js_src
                })

        if not ops:
            lines = [
                f"=== 🏗️ 上級GAS骨格注入: [{matched['id']}] {matched['title']} ===",
                "状態: スキップ（注入対象のすべての部品が既に存在しています）",
                "二重注入防止が作動しました。"
            ]
            if skipped_parts:
                lines.append("\n【検出された既存部品】:")
                for sp in skipped_parts:
                    lines.append(f"  - {sp}")
            return {
                "status": "already_applied",
                "script_id": sid,
                "scaffold": matched,
                "applied": False,
                "applied_parts": applied_parts,
                "skipped_parts": skipped_parts,
                "markdown_report": "\n".join(lines)
            }

        res = self.batch_patch(sid, ops, deploy=deploy)
        lines = [
            f"=== 🏗️ 上級GAS骨格注入: [{matched['id']}] {matched['title']} ===",
            f"状態: 正常反映 (注入部品: {len(applied_parts)}件, スキップ: {len(skipped_parts)}件)"
        ]
        if applied_parts:
            lines.append("\n【注入完了部品】:")
            for ap in applied_parts:
                lines.append(f"  - ✅ {ap}")
        if skipped_parts:
            lines.append("\n【二重注入防止スキップ】:")
            for sp in skipped_parts:
                lines.append(f"  - ⏩ {sp}")

        return {
            "status": "success",
            "script_id": sid,
            "scaffold": matched,
            "applied": True,
            "applied_parts": applied_parts,
            "skipped_parts": skipped_parts,
            "batch_result": res,
            "markdown_report": "\n".join(lines)
        }


    @staticmethod
    def _parse_js_literal_value(raw_val: str):
        """単純な JS リテラル（文字列・数値・真偽値）を Python 値に変換する。対象外なら (False, None)"""
        s = raw_val.strip()
        if not s:
            return False, None
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            inner = s[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
            return True, inner
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            return True, float(s) if "." in s else int(s)
        if s == "true":
            return True, True
        if s == "false":
            return True, False
        return False, None


    @staticmethod
    def _split_js_decl_rhs(rhs: str):
        """宣言行の右辺からクォート外の末尾セミコロンと // コメントを切り離す -> (value_raw, suffix)"""
        in_quote = None
        escaped = False
        comment_idx = -1
        for i, ch in enumerate(rhs):
            if escaped:
                escaped = False
                continue
            if in_quote is not None:
                if ch == "\\":
                    escaped = True
                elif ch == in_quote:
                    in_quote = None
                continue
            if ch in ("'", '"', "`"):
                in_quote = ch
                continue
            if ch == "/" and i + 1 < len(rhs) and rhs[i + 1] == "/":
                comment_idx = i
                break
        if comment_idx >= 0:
            code_part = rhs[:comment_idx]
            comment_part = rhs[comment_idx:]
        else:
            code_part = rhs
            comment_part = ""
        trimmed_code = code_part.rstrip()
        ws_after_code = code_part[len(trimmed_code):]
        semi = ""
        if trimmed_code.endswith(";"):
            semi = ";"
            trimmed_code = trimmed_code[:-1].rstrip()
        return trimmed_code.strip(), f"{semi}{ws_after_code}{comment_part}"


    def _collect_top_level_constants(self, files: list) -> list:
        """SERVER_JS ファイルからトップレベルの表示文字・上限・シート名等の定数宣言を抽出する"""
        const_pat = re.compile(
            r"^(const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(.+)$"
        )
        items = []
        for f in files:
            if f.get("type") != "SERVER_JS":
                continue
            fname = f.get("name", "")
            src = f.get("source", "")
            lines = src.splitlines()
            # 関数範囲内はトップレベル対象外とする
            fn_ranges = [
                (fn["start_line"], fn["end_line"])
                for fn in self._extract_functions_from_js(src, 0)
            ]
            for idx, line in enumerate(lines, 1):
                if any(s <= idx <= e for s, e in fn_ranges):
                    continue
                if line[:1].isspace():
                    continue
                m = const_pat.match(line)
                if not m:
                    continue
                kw, name = m.group(1), m.group(2)
                raw_val, _ = self._split_js_decl_rhs(m.group(3))
                if "getSetting_(" in raw_val:
                    continue
                ok, parsed = self._parse_js_literal_value(raw_val)
                if not ok:
                    continue
                items.append({
                    "file": fname,
                    "line": idx,
                    "kw": kw,
                    "name": name,
                    "raw_value": raw_val,
                    "value": parsed,
                    "orig_line": line,
                })
        return items


    def _gas_scaffold_s06(self, script_id: str, apply: bool = False, deploy: bool = False) -> dict:
        """S06: コード内の定数を紐づいたスプレッドシートの「設定」シートへ外出しする下見・反映"""
        if not script_id:
            raise ValueError("S06 を実行するプロジェクト名またはスクリプトIDを指定してください。")
        sid = self.resolve_script_id(script_id)
        parent_ss_id = self._get_bound_spreadsheet_id(sid)
        if not parent_ss_id:
            msg = (
                "=== 🏗️ 上級GAS骨格 [S06] 設定を外に出す ===\n"
                "判定: 対象外（このプロジェクトに紐づいたスプレッドシートがありません）"
            )
            return {
                "status": "not_applicable",
                "script_id": sid,
                "reason": "紐づいたスプレッドシートがありません",
                "applied": False,
                "markdown_report": msg,
            }

        content, _, _ = self._get_content_for_write_with_status(sid)
        files = content.get("files", [])
        orig_files = copy.deepcopy(files)
        constants = self._collect_top_level_constants(files)
        if not constants:
            msg = (
                "=== 🏗️ 上級GAS骨格 [S06] 設定を外に出す ===\n"
                f"紐づきシートID: {parent_ss_id}\n"
                "状態: 外出し対象のトップレベル定数が見つかりませんでした。"
            )
            return {
                "status": "no_constants",
                "script_id": sid,
                "spreadsheet_id": parent_ss_id,
                "applied": False,
                "settings": [],
                "markdown_report": msg,
            }

        # 「設定」シート（項目・値の 2 列）のデータと 2 号機向け操作を組み立てる
        sheet_rows = [["項目", "値"]] + [[c["name"], c["value"]] for c in constants]
        tsv_text = "\n".join(
            f"{row[0]}\t" + str(row[1]).replace("\t", " ").replace("\r", " ").replace("\n", " ")
            for row in sheet_rows
        )
        ws_ops = [
            {"shelf": "sheet.add", "name": "設定"},
            {"shelf": "write", "sheet": "設定", "range": "A1", "tsv": tsv_text},
        ]

        # コード側の差し替え下見を作成
        s06_item = next(s for s in _gc().GAS_SCAFFOLD_CATALOG if s["id"] == "S06")
        by_file = collections.defaultdict(list)
        for c in constants:
            by_file[c["file"]].append(c)

        new_files = copy.deepcopy(files)
        diff_chunks = []
        changed_file_names = []
        helper_added_file = None

        for f in new_files:
            fname = f.get("name", "")
            if f.get("type") != "SERVER_JS" or fname not in by_file:
                continue
            orig_src = f.get("source", "")
            lines = orig_src.splitlines(keepends=True)
            for c in by_file[fname]:
                l_idx = c["line"] - 1
                eol = "\r\n" if lines[l_idx].endswith("\r\n") else ("\n" if lines[l_idx].endswith("\n") else "")
                lines[l_idx] = f"{c['kw']} {c['name']} = getSetting_({json.dumps(c['name'], ensure_ascii=False)}, {c['raw_value']});{eol}"
            new_src = "".join(lines)
            if helper_added_file is None and s06_item["marker"] not in new_src and "function getSetting_(" not in new_src:
                new_src = new_src.rstrip() + "\n\n" + s06_item["code"] + "\n"
                helper_added_file = fname
            f["source"] = new_src
            changed_file_names.append(fname)
            d_iter = list(difflib.unified_diff(
                orig_src.splitlines(keepends=True),
                new_src.splitlines(keepends=True),
                fromfile=f"a/{fname}",
                tofile=f"b/{fname}",
                n=2,
            ))
            diff_chunks.append("".join(d_iter))

        combined_diff = "\n".join(diff_chunks)
        table_lines = ["| 項目 | 値 | 元ファイル |", "| --- | --- | --- |"]
        for c in constants:
            table_lines.append(f"| {c['name']} | {c['value']} | {c['file']}:L{c['line']} |")

        if not apply:
            report_lines = [
                f"=== 🏗️ 上級GAS骨格下見 [S06] {s06_item['title']} ===",
                f"紐づきスプレッドシート: {parent_ss_id}",
                f"検出定数: {len(constants)}件",
                "",
                "### 📋 「設定」シート出力内容（項目・値）",
                *table_lines,
                "",
                "### 📝 コード変更下見 (Diff)",
                "```diff",
                combined_diff.rstrip(),
                "```",
                "",
                "※ 読み込み方式（毎回／キャッシュ）は確認事項のため暫定の単純読み込み関数を提示しています。",
                "💡 反映するには apply=True を指定してください。",
            ]
            return {
                "status": "preview",
                "script_id": sid,
                "spreadsheet_id": parent_ss_id,
                "applied": False,
                "settings": [{"name": c["name"], "value": c["value"], "file": c["file"], "line": c["line"]} for c in constants],
                "sheet_rows": sheet_rows,
                "ws_ops": ws_ops,
                "diff": combined_diff,
                "markdown_report": "\n".join(report_lines),
            }

        # apply=True のときのみコードを書き換える
        for f in new_files:
            if f.get("name") in changed_file_names:
                self._validate_syntax(f["name"], f["source"], file_type="SERVER_JS")
        backup_path = self._save_backup(sid, content)
        put_res = self._put_content(sid, new_files)
        self._verify_and_rollback_if_broken(sid, orig_files, new_files, fast=False)

        ret = {
            "status": "success",
            "script_id": sid,
            "spreadsheet_id": parent_ss_id,
            "applied": True,
            "delivery": put_res.get("delivery", "") if isinstance(put_res, dict) else "",
            "settings": [{"name": c["name"], "value": c["value"], "file": c["file"], "line": c["line"]} for c in constants],
            "sheet_rows": sheet_rows,
            "ws_ops": ws_ops,
            "backup_file": str(backup_path),
            "diff": combined_diff,
            "markdown_report": "\n".join([
                f"=== 🏗️ 上級GAS骨格反映 [S06] {s06_item['title']} ===",
                f"紐づきスプレッドシート: {parent_ss_id}",
                f"対象定数: {len(constants)}件 | 設定シート用データ準備済み（2列: 項目・値）",
                *table_lines,
                "```diff",
                combined_diff.rstrip(),
                "```",
            ]),
        }
        if deploy:
            ret["deployment"] = self.deploy(sid, description="S06 settings externalized", fast=True)
        return ret


    @staticmethod
    def _parse_e01_query(query: str):
        """E01 頼み文からかぎかっこ内の (変更前, 変更後) の 2 語（または 1 語＋削除指示）を取り出す"""
        if not query:
            return None, None
        tokens = []
        for m in re.finditer(r"「([^」]*)」|『([^』]*)』|'([^']*)'|\"([^\"]*)\"", query):
            val = next((g for g in m.groups() if g is not None), None)
            if val is not None:
                tokens.append(val)
        if len(tokens) >= 2 and tokens[0]:
            return tokens[0], tokens[1]
        if len(tokens) == 1 and tokens[0] and re.search(r"(?:削除|消して|消去|取り除|なくして|外して)", query):
            return tokens[0], ""
        return None, None


    @staticmethod
    def _parse_e02_query(query: str):
        """E02 頼み文から (対象名, 新しい値) を取り出す"""
        if not query:
            return None, None
        q = query.strip()
        q = re.sub(r"^(?:定数|変数|設定値|設定)\s+", "", q)
        m = re.match(
            r"^[「『'\"]?([A-Za-z0-9_\u3040-\u30ff\u4e00-\u9fffー$]+)[」』'\"]?\s*(?:の値)?\s*(?:を|は)\s*(.+?)\s*(に(?:替え|変え|変更|し|直し|セット|設定)?(?:て|る|ます)?|へ(?:替え|変え|変更)?(?:て|る)?)$",
            q,
        )
        if not m:
            return None, None
        name = m.group(1).strip()
        val_raw = (m.group(2) or "").strip()
        # 末尾の助詞「に」が残った場合を剥がす
        val_raw = re.sub(r"\s*に$", "", val_raw).strip()
        if not name or not val_raw:
            return None, None
        # 値として妥当（数値・真偽・引用文字・短いトークン）でない長文動詞句は誤爆防止で除外
        is_quoted = len(val_raw) >= 2 and (
            (val_raw[0] == "「" and val_raw[-1] == "」")
            or (val_raw[0] == "『" and val_raw[-1] == "』")
            or (val_raw[0] in ("'", '"') and val_raw[-1] == val_raw[0])
        )
        is_scalar = bool(re.match(r"^(?:-?\d+(?:\.\d+)?|true|false|null)$", val_raw, re.IGNORECASE))
        if not (is_quoted or is_scalar):
            if re.search(r"(?:して|作って|追加|削除|設計|修正|調べ|教え)", val_raw) or len(val_raw) > 40:
                return None, None
        return name, val_raw


    def _find_line_func_name(self, ftype: str, source: str, line_no: int) -> str:
        """指定行が属する関数名（見つからなければトップレベル／HTML）を返す"""
        if ftype == "SERVER_JS":
            for fn in self._extract_functions_from_js(source, 0):
                if fn["start_line"] <= line_no <= fn["end_line"]:
                    return fn["name"]
            return "(トップレベル)"
        if ftype == "HTML":
            for sm in re.finditer(r"(<script[^>]*>)([\s\S]*?)(</script>)", source, re.IGNORECASE):
                if not self._is_js_script_tag(sm.group(1)):
                    continue
                offset = source.count("\n", 0, sm.start(2))
                for fn in self._extract_functions_from_js(sm.group(2), offset):
                    if fn["start_line"] <= line_no <= fn["end_line"]:
                        return fn["name"]
            return "(HTML)"
        return f"({ftype})"


    def _gas_edit_text(self, sid: str, query: str, apply: bool = False, deploy: bool = False, target_func: str = "", target_file: str = "") -> dict:
        """E01: 全ファイル（SERVER_JS・HTML）から文字を探して 1 か所なら替える"""
        old_text, new_text = self._parse_e01_query(query)
        if old_text is None or new_text is None:
            return {
                "status": "need_args",
                "shelf_id": "E01",
                "applied": False,
                "markdown_report": "=== ✏️ [E01] 文字を替える ===\n変更前と変更後の文字を「」や『』で 2 つ指定してください（例: 『送信』を『保存』に替えて）。",
            }

        content, _, _ = self._get_content_for_write_with_status(sid)
        files = content.get("files", [])
        orig_files = copy.deepcopy(files)

        hits = []
        for f in files:
            ftype = f.get("type", "")
            if ftype not in ("SERVER_JS", "HTML"):
                continue
            fname = f.get("name", "")
            src = f.get("source", "")
            lines = src.splitlines()
            pos = 0
            while True:
                idx = src.find(old_text, pos)
                if idx < 0:
                    break
                line_no = src.count("\n", 0, idx) + 1
                func_name = self._find_line_func_name(ftype, src, line_no)
                line_preview = lines[line_no - 1].strip() if 0 <= line_no - 1 < len(lines) else ""
                hits.append({
                    "file": fname,
                    "type": ftype,
                    "function": func_name,
                    "line": line_no,
                    "start": idx,
                    "end": idx + len(old_text),
                    "line_text": line_preview,
                    "file_obj": f,
                })
                pos = idx + max(1, len(old_text))

        if not hits:
            return {
                "status": "not_found",
                "shelf_id": "E01",
                "old_text": old_text,
                "new_text": new_text,
                "hits": 0,
                "applied": False,
                "markdown_report": f"=== ✏️ [E01] 文字を替える ===\n『{old_text}』は全ファイル（SERVER_JS・HTML）で 0 か所（見つかりませんでした）。",
            }

        if len(hits) >= 2 and target_file:
            tf_low = target_file.strip().lower()
            file_filtered = [h for h in hits if h["file"].lower() == tf_low]
            if file_filtered:
                hits = file_filtered

        if len(hits) >= 2 and target_func:
            fn_filtered = [h for h in hits if h["function"] == target_func]
            if fn_filtered:
                hits = fn_filtered

        if len(hits) >= 2:
            loc_lines = []
            for h in hits:
                hints = [f"filename='{h['file']}'"]
                if h["function"] not in ("(HTML)", "(トップレベル)"):
                    hints.append(f"func_name='{h['function']}'")
                loc_lines.append(f"  - {h['file']} | 関数: {h['function']} | L{h['line']}: `{h['line_text']}` （絞込: {', '.join(hints)}）")
            return {
                "status": "ambiguous",
                "shelf_id": "E01",
                "old_text": old_text,
                "new_text": new_text,
                "hits": len(hits),
                "matches": [{k: v for k, v in h.items() if k != "file_obj"} for h in hits],
                "applied": False,
                "markdown_report": "\n".join([
                    f"=== ✏️ [E01] 文字を替える（{len(hits)} か所ヒットのため変更せず） ===",
                    f"対象: 『{old_text}』 -> 『{new_text}』",
                    *loc_lines,
                ]),
            }

        hit = hits[0]
        target_file = hit["file_obj"]
        old_src = target_file.get("source", "")
        end_pos = hit["end"]
        # 空文字への削除で行全体が消える場合、直後の改行も除去して空行を残さない
        if new_text == "" and (hit["start"] == 0 or old_src[hit["start"] - 1] == "\n"):
            if old_src[end_pos:end_pos + 2] == "\r\n":
                end_pos += 2
            elif old_src[end_pos:end_pos + 1] == "\n":
                end_pos += 1
        new_src = old_src[:hit["start"]] + new_text + old_src[end_pos:]
        diff_text = "".join(difflib.unified_diff(
            old_src.splitlines(keepends=True),
            new_src.splitlines(keepends=True),
            fromfile=f"a/{target_file['name']}",
            tofile=f"b/{target_file['name']}",
            n=2,
        ))
        syntax_status = self._validate_syntax(target_file["name"], new_src, file_type=target_file.get("type", "SERVER_JS"))

        if not apply:
            return {
                "status": "preview",
                "shelf_id": "E01",
                "file": target_file["name"],
                "function": hit["function"],
                "line": hit["line"],
                "hits": 1,
                "applied": False,
                "syntax_check": syntax_status,
                "diff": diff_text,
                "markdown_report": "\n".join([
                    f"=== ✏️ [E01] 文字を替える（下見） ===",
                    f"箇所: {target_file['name']} ({hit['function']} L{hit['line']})",
                    f"構文検査: {syntax_status}",
                    "```diff",
                    diff_text.rstrip(),
                    "```",
                ]),
            }

        backup_path = self._save_backup(sid, content)
        target_file["source"] = new_src
        put_res = self._put_content(sid, files)
        self._verify_and_rollback_if_broken(sid, orig_files, files, fast=False)
        ret = {
            "status": "success",
            "shelf_id": "E01",
            "file": target_file["name"],
            "function": hit["function"],
            "line": hit["line"],
            "hits": 1,
            "applied": True,
            "delivery": put_res.get("delivery", "") if isinstance(put_res, dict) else "",
            "backup_file": str(backup_path),
            "syntax_check": syntax_status,
            "diff": diff_text,
            "markdown_report": f"[完了] {target_file['name']}({hit['function']} L{hit['line']}) 『{old_text}』→『{new_text}』",
        }
        if deploy:
            dep_res = self.deploy(sid, description="E01 replace_text", fast=True)
            ret["deployment"] = dep_res
            ret["markdown_report"] += _dep_report_line(dep_res)
        return ret


    def _gas_edit_const(self, sid: str, query: str, apply: bool = False, deploy: bool = False, target_func: str = "", target_file: str = "") -> dict:
        """E02: const/var/let 名前 = 値 の 1 行を探して値だけ替える（日本語名は候補一覧のみ）"""
        name, val_raw = self._parse_e02_query(query)
        if not name or not val_raw:
            return {
                "status": "need_args",
                "shelf_id": "E02",
                "applied": False,
                "markdown_report": "=== 🔢 [E02] 値を替える ===\n定数名と新しい値を指定してください（例: 上限を 100 に、SHEET_NAME を『名簿』に）。",
            }

        content, _, _ = self._get_content_for_write_with_status(sid)
        files = content.get("files", [])
        orig_files = copy.deepcopy(files)

        decl_pat = re.compile(
            r"^([ \t]*(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*)(.+)$"
        )
        all_consts = []
        for f in files:
            ftype = f.get("type", "")
            if ftype not in ("SERVER_JS", "HTML"):
                continue
            fname = f.get("name", "")
            src = f.get("source", "")
            for line_no, line in enumerate(src.splitlines(), 1):
                m = decl_pat.match(line)
                if not m:
                    continue
                val_raw_part, suffix_part = self._split_js_decl_rhs(m.group(3))
                all_consts.append({
                    "file": fname,
                    "type": ftype,
                    "line": line_no,
                    "name": m.group(2),
                    "prefix": m.group(1),
                    "value_raw": val_raw_part,
                    "suffix": suffix_part,
                    "orig_line": line,
                    "function": self._find_line_func_name(ftype, src, line_no),
                    "file_obj": f,
                })

        is_ident = bool(re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name))
        if not is_ident:
            # 名前が日本語の言い方のときは、当たりそうな定数を並べて返すだけ（直さない）
            hint_map = {
                "上限": ("max", "limit", "cap", "upper"),
                "最大": ("max", "limit"),
                "最小": ("min",),
                "シート": ("sheet",),
                "件数": ("count", "limit", "max", "rows", "num"),
                "行数": ("row", "rows", "max"),
                "タイムアウト": ("timeout", "wait", "ms", "sec"),
                "待ち": ("wait", "delay", "sleep", "timeout"),
                "名前": ("name", "title"),
                "名称": ("name", "title", "label"),
                "リトライ": ("retry", "retries"),
            }
            hints = []
            for k, words in hint_map.items():
                if k in name:
                    hints.extend(words)
            scored = []
            for c in all_consts:
                low = (c["name"] + " " + c["orig_line"]).lower()
                sc = sum(2 for w in hints if w in low) + (3 if name in c["orig_line"] else 0)
                if c["name"].isupper():
                    sc += 1
                scored.append((sc, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            cand_list = [x[1] for x in scored[:15]]
            cand_lines = [
                f"  - {c['name']} = {c['value_raw']}  ({c['file']} {c['function']} L{c['line']})"
                for c in cand_list
            ]
            return {
                "status": "candidates",
                "shelf_id": "E02",
                "query_name": name,
                "requested_value": val_raw,
                "applied": False,
                "candidates": [{k: v for k, v in c.items() if k != "file_obj"} for c in cand_list],
                "markdown_report": "\n".join([
                    f"=== 🔢 [E02] 値を替える（日本語指定「{name}」のため候補一覧のみ） ===",
                    "対象の英数字定数名を指定して実行してください（例: MAX_ROWS を 100 に）:",
                    *(cand_lines if cand_lines else ["  (const/var/let の定数宣言が見つかりませんでした)"]),
                ]),
            }

        hits = [c for c in all_consts if c["name"] == name]
        if not hits:
            return {
                "status": "not_found",
                "shelf_id": "E02",
                "const_name": name,
                "applied": False,
                "markdown_report": f"=== 🔢 [E02] 値を替える ===\n定数/変数 `{name}` の宣言行が見つかりませんでした。",
            }

        if len(hits) >= 2 and target_file:
            tf_low = target_file.strip().lower()
            ff = [c for c in hits if c["file"].lower() == tf_low]
            if ff:
                hits = ff

        if len(hits) >= 2 and target_func:
            fnf = [c for c in hits if c["function"] == target_func]
            if fnf:
                hits = fnf

        if len(hits) >= 2:
            loc_lines = [f"  - {c['file']} ({c['function']} L{c['line']}): `{c['orig_line'].strip()}`" for c in hits]
            return {
                "status": "ambiguous",
                "shelf_id": "E02",
                "const_name": name,
                "hits": len(hits),
                "applied": False,
                "markdown_report": "\n".join([
                    f"=== 🔢 [E02] 値を替える（{len(hits)} か所ヒットのため変更せず） ===",
                    *loc_lines,
                ]),
            }

        hit = hits[0]
        # 新しい値をリテラル整形（『』や「」は元のクォート種別に合わせて文字列化）
        q_m = re.fullmatch(r"[「『](.*)[」』]", val_raw)
        orig_val = hit["value_raw"]
        orig_quote = orig_val[0] if len(orig_val) >= 2 and orig_val[0] in ("'", '"') and orig_val[-1] == orig_val[0] else "'"
        if q_m:
            new_lit = json.dumps(q_m.group(1), ensure_ascii=False)
            if orig_quote == "'":
                new_lit = "'" + q_m.group(1).replace("\\", "\\\\").replace("'", "\\'") + "'"
        elif re.fullmatch(r"(?:-?\d+(?:\.\d+)?|true|false|null|['\"].*['\"])", val_raw):
            new_lit = val_raw
        elif orig_val and orig_val[0] in ("'", '"'):
            new_lit = f"{orig_quote}{val_raw}{orig_quote}"
        else:
            new_lit = val_raw

        # 値末尾のセミコロンが value_raw 側に入っていた場合の保護
        val_core = orig_val.rstrip()
        semi = ""
        if val_core.endswith(";"):
            semi = ";"
        new_line = f"{hit['prefix']}{new_lit}{semi}{hit['suffix']}"

        target_file = hit["file_obj"]
        old_src = target_file.get("source", "")
        src_lines = old_src.splitlines(keepends=True)
        l_idx = hit["line"] - 1
        eol = "\r\n" if src_lines[l_idx].endswith("\r\n") else ("\n" if src_lines[l_idx].endswith("\n") else "")
        src_lines[l_idx] = new_line + eol
        new_src = "".join(src_lines)

        diff_text = "".join(difflib.unified_diff(
            old_src.splitlines(keepends=True),
            new_src.splitlines(keepends=True),
            fromfile=f"a/{target_file['name']}",
            tofile=f"b/{target_file['name']}",
            n=2,
        ))
        syntax_status = self._validate_syntax(target_file["name"], new_src, file_type=target_file.get("type", "SERVER_JS"))

        if not apply:
            return {
                "status": "preview",
                "shelf_id": "E02",
                "file": target_file["name"],
                "function": hit["function"],
                "line": hit["line"],
                "const_name": name,
                "old_value": orig_val,
                "new_value": new_lit,
                "applied": False,
                "syntax_check": syntax_status,
                "diff": diff_text,
                "markdown_report": "\n".join([
                    f"=== 🔢 [E02] 値を替える（下見） ===",
                    f"箇所: {target_file['name']} ({hit['function']} L{hit['line']})",
                    f"構文検査: {syntax_status}",
                    "```diff",
                    diff_text.rstrip(),
                    "```",
                ]),
            }

        backup_path = self._save_backup(sid, content)
        target_file["source"] = new_src
        put_res = self._put_content(sid, files)
        self._verify_and_rollback_if_broken(sid, orig_files, files, fast=False)
        ret = {
            "status": "success",
            "shelf_id": "E02",
            "file": target_file["name"],
            "function": hit["function"],
            "line": hit["line"],
            "const_name": name,
            "old_value": orig_val,
            "new_value": new_lit,
            "applied": True,
            "delivery": put_res.get("delivery", "") if isinstance(put_res, dict) else "",
            "backup_file": str(backup_path),
            "syntax_check": syntax_status,
            "diff": diff_text,
            "markdown_report": f"[完了] {target_file['name']}({hit['function']} L{hit['line']}) {name}: {orig_val}→{new_lit}",
        }
        if deploy:
            dep_res = self.deploy(sid, description="E02 replace_const", fast=True)
            ret["deployment"] = dep_res
            ret["markdown_report"] += _dep_report_line(dep_res)
        return ret


    def _gas_edit_shelf(self, sid: str, shelf_id: str, query: str = "", apply: bool = False, deploy: bool = False, func_name: str = "", filename: str = "") -> dict:
        """EDIT 棚（E01/E02）のディスパッチ"""
        if shelf_id.upper() == "E01":
            return self._gas_edit_text(sid, query=query, apply=apply, deploy=deploy, target_func=func_name, target_file=filename)
        if shelf_id.upper() == "E02":
            return self._gas_edit_const(sid, query=query, apply=apply, deploy=deploy, target_func=func_name, target_file=filename)
        raise ValueError(f"未対応の編集棚ID: {shelf_id}")


    def match_shelf(self, query: str) -> dict:
        """頼み文（日本語・英語）から最適な棚（全28棚）を特定して返す"""
        if not query or not query.strip():
            return {"shelf_id": "", "category": "", "name": "", "score": 0, "candidates": []}

        q = query.strip().lower()
        e01_pair = self._parse_e01_query(query)
        e02_pair = self._parse_e02_query(query)
        has_other_kw = any(
            kw.lower() in q
            for s in _gc().GAS_UNIFIED_SHELVES
            if s["category"] not in ("EDIT",)
            for kw in s.get("keywords", [])
            if kw not in ("書き換え",)
        )
        scored = []

        for s in _gc().GAS_UNIFIED_SHELVES:
            score = 0
            s_id = s["id"].lower()
            s_name = s["name"].lower()
            if s_id == q or f" {s_id} " in f" {q} " or s_id in q:
                score += 30
            if s_name in q:
                score += 20
            for kw in s.get("keywords", []):
                kw_low = kw.lower()
                if kw_low in q:
                    score += 15 + len(kw_low) * 2
                elif any(tok in kw_low for tok in q.split() if len(tok) >= 2):
                    score += 5

            # E01/E02 の構文パターン加点（他棚の固有キーワードと衝突しない場合）
            if s["id"] == "E01" and e01_pair[0] is not None and not has_other_kw:
                score += 45
            elif s["id"] == "E02" and e02_pair[0] is not None and e01_pair[0] is None and not has_other_kw:
                score += 40

            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored or scored[0][0] < 10:
            return {"shelf_id": "", "category": "", "name": "", "score": 0, "candidates": []}

        best = scored[0][1]
        best_score = scored[0][0]
        return {
            "shelf_id": best["id"],
            "category": best["category"],
            "name": best["name"],
            "score": best_score,
            "handler_type": best["handler_type"],
            "shelf": best,
            "candidates": [{"id": it[1]["id"], "name": it[1]["name"], "score": it[0]} for it in scored[:5]]
        }


    def check_shelves(self) -> dict:
        """全28棚のゴールデン頼み文テスト（42問）を機械検証"""
        golden_cases = [
            ("シートに1行ずつ追記するのを速くして", "R01"),
            ("appendRow を配列一括にしたい", "R01"),
            ("getValue をループで呼んでいるのを一括化して", "R02"),
            ("UrlFetchApp を fetchAll で並列化して", "R03"),
            ("読み取り処理を CacheService でキャッシュ化して", "R04"),
            ("PropertiesService.getProperty をループ外に巻き上げて", "R05"),
            ("メールのスレッド取得が遅いので一括取得にしたい", "R06"),
            ("セルの背景色を setBackgrounds で一括装飾して", "R07"),
            ("deleteRow のループを行削除 filter に変えて", "R08"),
            ("ループ内で openById しているので巻き上げて", "R09"),
            ("DriveApp の全件走査ループを searchFiles に直して", "R10"),
            ("HTMLからの初期描画通信をRPCバンドルで束ねて", "R11"),
            ("排他ロックと6分制限対策を入れて", "R12"),
            ("LockService による多重起動防止", "R12"),
            ("通信エラーで固まらないようにPromise化してエラートーストを出したい", "S01"),
            ("callServer を使って自動リトライしたい", "S01"),
            ("0.05秒で表示できるように IndexedDB 裏同期 SWR を導入して", "S02"),
            ("ボタン押下即時反映の楽観的UIと自動ロールバックを入れて", "S03"),
            ("サーバー例外保護と try/catch 防御の runSafeRpc を導入して", "S04"),
            ("上級骨格フルセットを一括注入して", "S05"),
            ("モダン骨格一括でアプリの土台を作って", "S05"),
            ("見た目を Linear風のモダンダークデザインに着せ替えたい", "K01"),
            ("画面をすりガラス風グラスモーフィズムにして", "K02"),
            ("Notion風のクリーンミニマルなデザインにして", "K03"),
            ("エメラルドグリーンのフィンテック風テーマにして", "K04"),
            ("GASドックで健康診断して", "D01"),
            ("ガスドックで総合診断をお願い", "D01"),
            ("レントゲンでコールパスと幽霊RPCを調べて", "D02"),
            ("xray 解析して", "D02"),
            ("使っていない関数を削除して掃除して", "D03"),
            ("死にコードを削除して", "D03"),
            ("戻り値のズレやプロパティ不一致を検査して", "D04"),
            ("withFailureHandler漏れとデータ契約を点検して", "D04"),
            ("RPC戻り値プロパティ契約の検査をして", "D04"),
            ("『送信』を『保存』に替えて", "E01"),
            ("ボタンの文字を「決定」から「登録」に変えて", "E01"),
            ("「エラーが発生しました」を「入力を確認してください」に書き換えて", "E01"),
            ("上限を 100 に", "E02"),
            ("SHEET_NAME を『名簿』に", "E02"),
            ("MAX_RETRY を 5 に変えて", "E02"),
            ("設定を外に出して", "S06"),
            ("コードの定数を設定シートに出して", "S06")
        ]

        total = len(golden_cases)
        matched = 0
        mismatches = []

        for q, expected_id in golden_cases:
            res = self.match_shelf(q)
            actual_id = res.get("shelf_id", "")
            if actual_id == expected_id:
                matched += 1
            else:
                mismatches.append({
                    "query": q,
                    "expected": expected_id,
                    "actual": actual_id,
                    "score": res.get("score", 0)
                })

        passed = (matched == total)
        lines = [
            "=== 🎯 GAS 全28棚・ゴールデン棚当て検査 (shelf --check) ===",
            f"判定: {'🟢 [PASS] 合格 (誤爆 0件)' if passed else '🔴 [FAIL] 不一致あり'}",
            f"検証件数: {total}問 | 正解: {matched}問 | 不一致: {len(mismatches)}件",
            ""
        ]
        if mismatches:
            lines.append("【不一致詳細】:")
            for m in mismatches:
                lines.append(f"  - 頼み文: 「{m['query']}」 -> 期待: {m['expected']}, 実際: {m['actual']} (スコア: {m['score']})")
        else:
            lines.append("✨ 全問が期待された棚IDへ正確に直結しています。")

        return {
            "passed": passed,
            "total": total,
            "matched": matched,
            "mismatches": mismatches,
            "markdown_report": "\n".join(lines)
        }


    @_track_sid_op
    def gas_shelf(self, script_id="", query="", shelf_id="", filename="", func_name="", apply=None, deploy=False, list_only=False, check_only=False) -> dict:
        """GAS 先撃ち総合棚ルーター（全28棚直結・棚当て検査・自動ディスパッチ）"""
        if check_only:
            return self.check_shelves()

        if list_only:
            lines = [
                f"=== 🧭 GAS 先撃ち総合棚カタログ (全{len(_gc().GAS_UNIFIED_SHELVES)}棚) ===",
                "| 棚ID | 分類 | 棚名 | 概要 | キーワード |",
                "| --- | --- | --- | --- | --- |"
            ]
            for s in _gc().GAS_UNIFIED_SHELVES:
                kw_str = ", ".join(s.get("keywords", []))
                lines.append(f"| {s['id']} | {s['category']} | {s['name']} | {s['desc']} | {kw_str} |")
            return {
                "shelves": _gc().GAS_UNIFIED_SHELVES,
                "count": len(_gc().GAS_UNIFIED_SHELVES),
                "markdown_report": "\n".join(lines)
            }

        matched_shelf = None
        if query:
            match_res = self.match_shelf(query)
            if match_res.get("shelf_id"):
                shelf_id = match_res["shelf_id"]
                matched_shelf = match_res

        if not shelf_id:
            lines = [
                "=== 🧭 GAS 先撃ち総合棚ルーター ===",
                f"頼み文: 「{query}」",
                f"該当する棚が見つかりませんでした。shelf --list で全{len(_gc().GAS_UNIFIED_SHELVES)}棚を確認してください。"
            ]
            return {
                "status": "not_found",
                "query": query,
                "shelf_id": "",
                "markdown_report": "\n".join(lines)
            }

        target_shelf = next((s for s in _gc().GAS_UNIFIED_SHELVES if s["id"].upper() == shelf_id.upper()), None)
        if not target_shelf:
            raise ValueError(f"棚ID '{shelf_id}' が見つかりません。")

        if not script_id:
            lines = [
                f"=== 🧭 GAS 先撃ち総合棚: [{target_shelf['id']}] {target_shelf['name']} ===",
                f"分類: {target_shelf['category']} | 概要: {target_shelf['desc']}",
                f"実行コマンド案: py gas.py shelf <project> --id {target_shelf['id']}" + (" --apply" if apply else "")
            ]
            return {
                "status": "preview",
                "matched_shelf": target_shelf,
                "markdown_report": "\n".join(lines)
            }

        sid = self.resolve_script_id(script_id)
        h_type = target_shelf["handler_type"]
        # 省略時（None）は小さな直し棚（E01/E02）のみ 1 発で反映し、大規模変更棚は安全側（下見）にする
        effective_apply = (h_type == "edit") if apply is None else bool(apply)

        target_fname = filename or "Index"
        if h_type == "recipe":
            dispatch_res = self.gas_recipe(sid, filename=target_fname, func_name=func_name, recipe_id=target_shelf["id"], apply=effective_apply, deploy=deploy)
        elif h_type == "scaffold":
            dispatch_res = self.gas_scaffold(sid, scaffold_id=target_shelf["id"], filename=target_fname, apply=effective_apply, deploy=deploy)
        elif h_type == "skin":
            if effective_apply:
                dispatch_res = self.design_skin(sid, filename=target_fname, preset=target_shelf.get("preset", "linear"), deploy=deploy)
            else:
                dispatch_res = {
                    "success": True,
                    "preview": True,
                    "preset": target_shelf.get("preset", "linear"),
                    "markdown_report": f"=== 🎨 GAS デザイン着せ替えプレビュー: [{target_shelf.get('preset', 'linear')}] ===\n概要: {target_shelf['desc']}\n反映するには apply=True を指定してください。"
                }
        elif h_type == "dock":
            dispatch_res = self.gas_dock(sid, filename=target_fname)
        elif h_type == "xray":
            dispatch_res = self.xray(sid, filename=target_fname)
        elif h_type == "clean_dead":
            dispatch_res = self.clean_dead(sid, dry_run=not effective_apply, deploy=deploy)
        elif h_type == "rpc_contracts":
            dispatch_res = self.check_rpc_contracts(sid, filename=target_fname)
        elif h_type == "security_audit":
            dispatch_res = self.security_audit(sid)
        elif h_type == "schema_check":
            dispatch_res = self.schema_check(sid)
        elif h_type == "edit":
            dispatch_res = self._gas_edit_shelf(sid, target_shelf["id"], query=query, apply=effective_apply, deploy=deploy, func_name=func_name, filename=filename)
        else:
            raise ValueError(f"未対応のハンドラ種別: {h_type}")

        md_report = dispatch_res.get("markdown_report", "") if isinstance(dispatch_res, dict) else str(dispatch_res)
        dep_info = dispatch_res.get("deployment") if isinstance(dispatch_res, dict) else None
        if "[本番デプロイ]" not in md_report:
            md_report += _dep_report_line(dep_info)

        return {
            "status": "success",
            "matched_shelf": target_shelf,
            "result": dispatch_res,
            "markdown_report": md_report
        }

