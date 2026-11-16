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
from pathlib import Path

from ..i18n import current_language
from .sources import L

PAGE_DIR = Path(__file__).with_name("page")
PAGE_NAME = "panorama.html"
DATA_NAME = "PANORAMA_DATA"                     # 快照里嵌数据的那个变量名（boot.js 认它）
STYLE_LINK = '<link rel="stylesheet" href="/app.css">'
SCRIPT_TAGS = '<script src="/app.js"></script>\n<script src="/boot.js"></script>'
#: 本机服务发的静态文件：名字 → 内容类型。**都不含用户数据**，所以不要令牌。
ASSETS = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "boot.js": "text/javascript; charset=utf-8",
}
PAGE_KEYS = ("title", "search_placeholder", "motion_on", "motion_off", "help_title", "help_text", "quests_title", "no_quests",
             "uses", "used_by", "open_vscode", "copy_path", "copied", "settings_at", "settings_hint", "footer", "pending",
             "lost")
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
    """``page/`` 下的一个静态文件；只认 ``ASSETS`` 里登记的名字。"""
    if name not in ASSETS:
        raise KeyError(name)
    return (PAGE_DIR / name).read_bytes()


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
    script = f"<script>\nconst {DATA_NAME} = {data};\n{_text('app.js')}\n{_text('boot.js')}</script>"
    return shell().replace(STYLE_LINK, f"<style>\n{_text('app.css')}</style>").replace(SCRIPT_TAGS, script)


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
