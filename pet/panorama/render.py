# -*- coding: utf-8 -*-
"""把图变成页面：同一份页面代码（``page/`` 目录），两种交付方式。

- **离线快照** ``render()`` / ``write()``：外壳、样式、脚本、数据全部内联进一个 HTML 文件。不联网、不依赖肥鱼
  开着，``file://`` 直接能看。
- **本机服务** ``shell()`` / ``asset()`` / ``payload()``：外壳和脚本是不含数据的静态内容，数据由页面带着令牌
  向 ``/api/graph`` 要（路由在 ``routes.py``）。

界面文字从字表取好一起交给页面，所以页面跟着肥鱼的界面语言走。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..i18n import current_language
from ..theme_tokens import tokens_css
from .sources import L

PAGE_DIR = Path(__file__).with_name("page")
PAGE_NAME = "panorama.html"
DATA_NAME = "PANORAMA_DATA"                     # 快照里嵌数据的那个变量名（boot.js 认它）
STYLE_LINK = '<link rel="stylesheet" href="/tokens.css">\n<link rel="stylesheet" href="/app.css">'
#: 不是文件、现算出来的静态内容：名字 → 生成函数。``tokens.css`` 是和 Qt 共用的那张颜色令牌表（见 ``theme_tokens``）。
GENERATED = {"tokens.css": tokens_css}
STYLES = ("tokens.css", "app.css")              # 顺序即层叠顺序：令牌在前，页面样式在后
SCRIPT_TAGS = '<script type="module" src="/boot.js"></script>'
#: 报告页（``/report/<名字>``，见 ``reports.py``）：自己的外壳、样式和入口模块；``util.js`` / ``client.js`` 和配置全景共用。
#: 报告页没有离线快照，所以这几个模块不进 ``MODULES``（``report.js`` 是会自己跑起来的入口，不能拼进全景的脚本里）。
REPORT_SHELL = "report.html"
REPORT_STYLES = ("tokens.css", "report.css")
REPORT_MODULES = ("util.js", "client.js", "items.js", "report.js")
REPORT_SCRIPT_TAG = '<script type="module" src="/report.js"></script>'
#: 笔记页（``/report/work_notes`` / ``/report/slack_watch``，见 ``notes.py``）：同一条数据路、另一套外壳和模块。
NOTES_SHELL = "notes.html"
NOTES_STYLES = ("tokens.css", "notes.css")
NOTES_MODULES = ("util.js", "client.js", "notelist.js", "notes.js")
NOTES_SCRIPT_TAG = '<script type="module" src="/notes.js"></script>'
#: 报告类页面的种类 → （外壳文件, 它的 script 标签）。provider 函数的 ``page`` 属性选哪一种（没有就是 report）。
PAGE_SHELLS = {"report": (REPORT_SHELL, REPORT_SCRIPT_TAG), "notes": (NOTES_SHELL, NOTES_SCRIPT_TAG)}
#: 页面脚本的原生模块，**按依赖顺序**：被 import 的排在前面，入口 ``boot.js`` 在最后。
#: 本机服务把它们一个个发出去，浏览器按 import 自己装配；离线快照没法这样（``file://`` 页面加载不了模块），
#: 所以 ``bundle()`` 按这个顺序把它们拼成一段普通脚本。加模块就在这里登记。
MODULES = ("util.js", "layout.js", "roads.js", "draw.js", "viewer.js", "memory.js", "form.js", "settings.js", "repair.js",
           "interact.js", "app.js", "client.js", "boot.js")
#: 本机服务发的静态文件：名字 → 内容类型。**都不含用户数据**，所以不要令牌。
ASSETS = {**{name: "text/css; charset=utf-8" for name in STYLES + REPORT_STYLES + NOTES_STYLES},
          **{name: "text/javascript; charset=utf-8" for name in MODULES + REPORT_MODULES + NOTES_MODULES}}
# 模块里只许这两种写法，bundle() 才拼得起来：整行的具名 import，和顶层声明前的 export。
_IMPORT_LINE = re.compile(r"^import \{\w+(?:, \w+)*\} from '\./[a-z]+\.js';\n", re.M)
_EXPORT_PREFIX = re.compile(r"^export (?=(?:function|const) )", re.M)
_LEFTOVER = re.compile(r"^\s*(?:import|export)\b", re.M)
PAGE_KEYS = ("title", "search_placeholder", "motion_on", "motion_off", "help_title", "help_text", "quests_title", "no_quests",
             "uses", "used_by", "open_vscode", "copy_path", "copied", "settings_at", "settings_hint", "footer", "pending",
             "lost", "view", "view_needs_service", "viewer_close", "viewer_loading", "viewer_failed", "viewer_empty",
             "viewer_truncated", "viewer_managed", "viewer_more", "viewer_binary", "memory_button", "memory_title", "memory_global",
             "memory_project", "memory_own", "memory_none", "memory_only_flagged", "memory_all", "memory_note", "memory_count",
             "memory_truncated", "memory_empty", "settings_open", "settings_needs_service", "settings_failed", "settings_unsaved",
             "repair", "repair_confirm_win", "repair_confirm_wsl", "repair_working", "repair_installed", "repair_pending",
             "repair_failed", "repair_lost", "action_needs_service",
             "check", "check_working", "check_checked", "check_failed", "check_busy", "check_missing",
             "sync", "sync_confirm_win", "sync_working", "sync_synced", "sync_noop", "sync_conflict", "sync_blocked", "sync_failed",
             "sync_busy", "sync_missing",
             "list_count", "list_filter", "expand_all", "collapse_all", "ago_now", "ago_minutes", "ago_hours", "ago_days", "gutter_tip",
             *("form_" + key for key in (
                 "saving", "saved", "stale", "invalid", "busy", "unavailable", "failed", "lost", "save", "revert", "restore_builtin",
                 "using_builtin", "dirty", "custom", "custom_label", "advanced", "err_unknown", "err_type", "err_not_a_choice",
                 "err_rejected", "err_out_of_range", "add_row", "delete_row",
                 "preview", "preview_working", "preview_played", "preview_missing", "preview_failed")))
#: 报告页自己的几句界面文字（随数据一起给：外壳是公开的静态文件，只带标题和「连接断了」）
REPORT_KEYS = ("report_lost", "report_unavailable", "report_action_started", "report_action_busy", "report_action_failed",
               "report_action_lost", "report_sections", "report_filters", "report_filter_all", "report_filter_p3",
               "report_filter_p2", "report_filter_p1", "report_filter_bug", "report_filter_upd", "report_hide_done",
               "report_items", "report_untitled", "report_fold", "report_trace", "report_done", "report_action_opened",
               "report_compose_empty")
#: 笔记页的界面文字（计数片、筛选片、详情里的字、按钮、动作的回答）；副按钮沿用报告页那几句
NOTES_KEYS = ("report_lost", "report_action_started", "report_action_busy", "report_action_failed", "report_action_opened",
              "report_action_lost", "notes_unavailable", "notes_count_open", "notes_count_due", "notes_count_busy", "notes_count_done",
              "notes_filter_all", "notes_filter_open", "notes_filter_due", "notes_filter_busy", "notes_filter_done", "notes_search",
              "notes_select", "notes_original", "notes_busy", "notes_busy_short", "notes_no_summary", "notes_remind", "notes_overdue",
              "notes_done_mark", "notes_kind_slack", "notes_kind_jira", "notes_kind_confluence", "notes_kind_link", "notes_kind_text",
              "notes_btn_link", "notes_btn_obsidian", "notes_btn_resummarize", "notes_btn_done", "notes_btn_delete", "notes_btn_push",
              "notes_btn_folder", "notes_btn_settings", "notes_snooze", "notes_snooze_hour", "notes_snooze_three", "notes_snooze_tomorrow",
              "notes_confirm_delete", "notes_saved", "notes_empty_text", "notes_failed", "notes_started", "notes_opened",
              "notes_folder_opened", "notes_no_link", "notes_missing", "notes_lost",
              "notes_watch_last", "notes_watch_found", "notes_watch_next", "notes_watch_never", "notes_watch_busy")
PAGE_STRING_KEYS = {"report": REPORT_KEYS, "notes": NOTES_KEYS}
NODE_STATE_KEYS = ("live", "ok", "warn", "bad", "unknown", "off", "info")
EDGE_STATE_KEYS = ("live", "ok", "warn", "broken", "unknown", "off")


def page_strings() -> dict:
    strings = {key: L(f"ui.{key}") for key in PAGE_KEYS}
    strings["state"] = {key: L(f"state.{key}") for key in NODE_STATE_KEYS}
    strings["edge_state"] = {key: L(f"edge_state.{key}") for key in EDGE_STATE_KEYS}
    return strings


def summary(graph: dict) -> str:
    meta = graph.get("meta") or {}
    timing = meta.get("timing") or {}
    counts = {"time": meta.get("taken_at", ""), "nodes": len(graph.get("nodes") or []), "edges": len(graph.get("edges") or []),
              "win": timing.get("windows_s", "?")}
    if "wsl_s" in timing:
        return L("ui.summary", wsl=timing["wsl_s"], **counts)
    return L("ui.summary_windows_only", **counts)


def _language() -> str:
    return "zh-CN" if current_language() == "zh" else "en"


def page_data(graph: dict, *, revision: int = 0) -> dict:
    """页面拿到的那一份：图 + 界面文字 + 摘要 + 语言与标题。``revision`` 每发布一次加一，页面靠它知道数据换了。"""
    return {**graph, "strings": page_strings(), "meta": {**(graph.get("meta") or {}), "summary": summary(graph)},
            "page": {"lang": _language(), "title": L("ui.window_title")}, "revision": revision}


def payload(graph: dict, *, revision: int = 0) -> bytes:
    """``/api/graph`` 的响应正文。"""
    return json.dumps(page_data(graph, revision=revision), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def asset(name: str) -> bytes:
    """一份静态内容：``page/`` 下的文件，或 ``GENERATED`` 里现算的；只认 ``ASSETS`` 里登记的名字。"""
    if name not in ASSETS:
        raise KeyError(name)
    if name in GENERATED:
        return GENERATED[name]().encode("utf-8")
    return (PAGE_DIR / name).read_bytes()


def bundle(names: tuple[str, ...] = MODULES) -> str:
    """把模块按顺序拼成一段普通脚本：去掉 import 行和 ``export`` 前缀，所有顶层名字落在同一个作用域里。

    这不是通用的打包器，只认 ``_IMPORT_LINE`` / ``_EXPORT_PREFIX`` 那两种写法；模块里出现别的 import / export
    写法（默认导出、改名、``import *``、跨行）就报错，而不是悄悄拼出一段坏脚本。
    """
    parts = []
    for name in names:
        text = _EXPORT_PREFIX.sub("", _IMPORT_LINE.sub("", _text(name).replace("\r\n", "\n")))
        if _LEFTOVER.search(text):
            raise RuntimeError(f"panorama module {name} uses an import/export form the bundler does not handle")
        parts.append(text)
    return "\n".join(parts)


def report_payload(report: dict, *, revision: int = 0, page: str = "report") -> bytes:
    """报告页 / 笔记页向 ``/api/report/<名字>`` 要到的那份：provider 给的字典 + 编号 + 页面信息 + 那种页面自己的几句界面文字。"""
    data = {"revision": revision,
            "page": {"lang": _language(), "title": L("ui.report_window_title", title=str(report.get("title") or ""))},
            "report": report, "strings": {key: L(f"ui.{key}") for key in PAGE_STRING_KEYS.get(page, REPORT_KEYS)}}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def report_shell(page: str = "report") -> str:
    """报告页 / 笔记页的外壳：公开的静态文件，没有数据，只有结构、语言、临时标题（页面拿到数据后再换）和「连接断了」那句话。
    ``page`` 是 ``PAGE_SHELLS`` 里的一种；不认识的当 report。"""
    shell_name, script_tag = PAGE_SHELLS.get(page, PAGE_SHELLS["report"])
    page = (PAGE_DIR / shell_name).read_text(encoding="utf-8")
    if script_tag not in page:
        raise RuntimeError("report shell lost its script tag")
    return page.replace("__LANG__", _language()).replace("__TITLE__", _html(L("ui.report_shell_title"))).replace(
        "__LOST__", _html(L("ui.report_lost")))


def shell() -> str:
    """本机服务发的页面外壳：没有数据，只有结构、语言、标题和「连接断了」那句话。"""
    page = (PAGE_DIR / "shell.html").read_text(encoding="utf-8")
    if STYLE_LINK not in page or SCRIPT_TAGS not in page:
        raise RuntimeError("panorama shell lost its style or script tags")
    return page.replace("__LANG__", _language()).replace("__TITLE__", _html(L("ui.window_title"))).replace(
        "__LOST__", _html(L("ui.lost")))


def render(graph: dict) -> str:
    """图 → 自带一切的整页 HTML（离线快照）。

    数据里的 ``</`` 转义掉：嵌进 ``<script>`` 的数据里出现 ``</script>`` 会把脚本截断。
    """
    data = json.dumps(page_data(graph), ensure_ascii=False).replace("</", "<\\/")
    script = f"<script>\nconst {DATA_NAME} = {data};\n{bundle()}</script>"
    styles = "".join(_text(name) for name in STYLES)
    return shell().replace(STYLE_LINK, f"<style>\n{styles}</style>").replace(SCRIPT_TAGS, script)


def write(graph: dict, out_dir: str | Path) -> Path:
    """写到 ``<out_dir>/panorama.html``（先写临时文件再替换：浏览器正好在重读时不会读到半个文件）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / PAGE_NAME
    temp = target.with_suffix(".html.tmp")
    temp.write_text(render(graph), encoding="utf-8")
    os.replace(temp, target)
    return target


def _text(name: str) -> str:
    return asset(name).decode("utf-8")


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
