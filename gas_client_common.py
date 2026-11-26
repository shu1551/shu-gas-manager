# -*- coding: utf-8 -*-
"""gas_client 共通デコレータ・レポートヘルパー。"""

import functools
import re

# 直す手（送りを返事の後ろに回し、続けて来たら前の送りを待たずにまとめて送る）
_COALESCE_OPS = {"replace_function", "patch_function", "add_function", "delete_function", "batch_patch",
                 "patch_code", "replace_file", "add_file", "delete_file",
                 "gas_shelf", "gas_recipe", "gas_scaffold", "design_skin", "clean_dead"}


def _dep_report_line(dep):
    """棚の返事（markdown_report）に足すデプロイの 1 行。裏で進めているときは、待たずに見られる最新の番地も出す"""
    if not isinstance(dep, dict):
        return ""
    if dep.get("status") == "queued":
        s = "\n[本番デプロイ] 裏で進めています（7 秒ほどで本番に出ます。失敗したら次の返事で知らせます）"
        if dep.get("devUrl"):
            s += "\n今すぐ見るなら最新の番地（/dev・持ち主だけ）: " + re.sub(r"/exec$", "/dev", str(dep["devUrl"]))
        return s
    if dep.get("versionNumber") is not None:
        return f"\n[本番デプロイ] Version {dep['versionNumber']} 反映済み"
    return ""


def _track_sid_op(fn):
    """script_id への読み書きで裏送り完了待ち・送り中・失敗通知を統一処理するデコレータ"""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        self._ensure_sync_state()
        tl = self._op_state_tl
        prev_depth = getattr(tl, "depth", 0)
        tl.depth = prev_depth + 1
        is_outer = (prev_depth == 0)

        script_arg = kwargs.get("script_id")
        if script_arg is None:
            script_arg = kwargs.get("project")
        if script_arg is None and args:
            script_arg = args[0]

        sid = ""
        prev_err = None
        edit = is_outer and fn.__name__ in _COALESCE_OPS and self._can_async_put()
        if is_outer:
            tl.async_put_sids = set()
            if script_arg:
                try:
                    sid = self.resolve_script_id(script_arg)
                    self._drop_orphan_unsent(sid)
                    if not edit:      # 読む手・実行する手は、送りが届いてから
                        self._wait_pending_put(sid)
                        self._note_stuck_put(sid)
                    else:             # 直す手は待たないが、前の送りが 30 秒以上止まっていたら知らせる
                        self._note_stuck_put(sid, min_age=30.0)
                    prev_err = self._pop_put_error(sid)
                except Exception:
                    sid = ""

        # 直す手は送りもデプロイも返事の後ろで（前の送りの最中なら続けて送る）。それ以外の手の deploy=True は今までどおりその場で
        deploy_sync = bool(kwargs.get("deploy", False)) and not edit
        prev_co, prev_dd = getattr(tl, "coalesce", False), getattr(tl, "defer_deploy", False)
        if is_outer:
            tl.coalesce, tl.defer_deploy = edit, edit
        try:
            with self._sync_put_context(enabled=deploy_sync):
                res = fn(self, *args, **kwargs)
        except Exception as e:
            if is_outer and prev_err:
                warn_msg = f"前の直しが届いていません（{prev_err}）"
                raise type(e)(f"{warn_msg}\n{e}") from e
            raise
        finally:
            tl.depth = prev_depth
            if is_outer:
                tl.coalesce, tl.defer_deploy = prev_co, prev_dd
            async_sids = getattr(tl, "async_put_sids", set()) if is_outer else set()
            if is_outer:
                tl.async_put_sids = set()

        if is_outer:
            if not sid and script_arg:
                try:
                    sid = self.resolve_script_id(script_arg)
                except Exception:
                    sid = ""
            return self._decorate_sid_op_result(res, sid, prev_err, async_sids)
        return res
    return wrapper
