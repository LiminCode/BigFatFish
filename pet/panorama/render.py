# -*- coding: utf-8 -*-
"""把图渲染成一个自带数据的 HTML 文件。

页面不联网、不带外部脚本：图以 JSON 形式嵌在模板里，位置和走线由页面自己的脚本算。界面文字从字表取好
一起嵌进去，所以页面跟着肥鱼的界面语言走。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..i18n import current_language
from .sources import L

TEMPLATE = Path(__file__).with_name("template.html")
PAGE_NAME = "panorama.html"
GRAPH_MARK = "/*GRAPH*/null"
PAGE_KEYS = ("title", "search_placeholder", "motion_on", "motion_off", "help_title", "help_text", "quests_title", "no_quests",
             "uses", "used_by", "open_vscode", "copy_path", "copied", "settings_at", "settings_hint", "footer", "pending")
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


def render(graph: dict) -> str:
    """图 → 整页 HTML。``</`` 转义掉：嵌进 ``<script>`` 的数据里出现 ``</script>`` 会把脚本截断。"""
    data = {**graph, "strings": page_strings(), "meta": {**(graph.get("meta") or {}), "summary": summary(graph)}}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    if GRAPH_MARK not in page:
        raise RuntimeError("panorama template lost its data placeholder")
    lang = "zh-CN" if current_language() == "zh" else "en"
    return page.replace("__LANG__", lang).replace("__TITLE__", L("ui.window_title")).replace(GRAPH_MARK, payload)


def write(graph: dict, out_dir: str | Path) -> Path:
    """写到 ``<out_dir>/panorama.html``（先写临时文件再替换：浏览器正好在重读时不会读到半个文件）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / PAGE_NAME
    temp = target.with_suffix(".html.tmp")
    temp.write_text(render(graph), encoding="utf-8")
    os.replace(temp, target)
    return target
