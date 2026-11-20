# -*- coding: utf-8 -*-
"""报告页：在浏览器里读一份「生成出来的内容」：工作简报（``work_briefing``）和个人简报（``personal_briefing``，2026-11-20）。

页面薄、不认功能（ADR 0014）：应用构造 ``PanoramaService`` 时按名字登记 provider（``reports={"work_briefing": …}``）。
provider 在**界面线程**上被调（它读 Qt 对象），返回页面要摆的那份字典：

- ``title`` / ``theme``（``dark`` / ``light``，跟「外观」里的偏好）；
- ``summary``（一句概要）、``generated``（「生成于 …」那一行）、``usage``（模型 / effort / 用时 / tokens / 花费，每项
  ``{key, text, tip}``）、``html``（全文，Markdown 已由 ``markdown.py`` 渲染成只含几个标签的 HTML）；
- ``busy`` / ``busy_text`` / ``empty_text`` / ``error``（上一次失败的原因，已翻成整句）；
- ``action``：底部那个按钮——``{name, report, label, hint}``，页面 ``POST /api/actions/<name>`` 时把 ``report`` 带回来；
  ``actions``：旁边再放几个按钮（同一种字典；个人简报的「记灵感…」在肥鱼里开 Qt 窗口，动作回 ``opened``）；
- ``available``：这台机器上有没有这项功能（工作简报要 WSL；没有就只显示一句说明）；
- ``sections``：全文按 ``<h3>`` 切成的几区 ``{id, source, title, html, count, p3, p2, p1, bugs, updated}``（``split_sections``）：
  页面用它画左栏的分区磁贴和右栏的每区一张卡；``source`` 只是按标题猜的来源（配色、图标用），猜不到是 ``other``。
  没有 ``<h3>`` 的内容是空列表，页面退回整段 ``html``；
- ``details``：「这次是怎么生成的」——几段 ``{title, html}``（服务端渲染、全部转义），页面折叠着摆在全文下面；
  ``settings_focus``：详情里「到设置里改」的链接要翻到配置全景的哪一组（页面自己拼带令牌的地址，替换 ``SETTINGS_URL`` 占位）。

隐私：报告内容只经带令牌的接口给本机浏览器，不落离线快照、不进日志（本机服务只记请求行）。
"""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Callable

from .. import work_briefing as wb
from ..i18n import t
from . import markdown

WORK_BRIEFING = "work_briefing"
PERSONAL_BRIEFING = "personal_briefing"
OPEN_INSPIRATION_ACTION = "open_inspiration"       # 个人简报页「记灵感…」：在肥鱼里开那扇 Qt 窗口的灵感页
GENERATE_ACTION = "generate_report"                 # 页面上「重新生成」走的动作名（actions.generate_report）
USAGE_ORDER = ("model", "effort", "time", "tokens_in", "tokens_out", "cost")
SETTINGS_URL = "__SETTINGS_URL__"                   # 详情 HTML 里的占位：页面换成 /#<令牌>&settings=<组>
#: 分区标题里的关键词 → 来源 id（只用来配色和图标；提示词模板是用户可改的，所以按词猜，猜不到就是 other）
SOURCE_WORDS = (("jira", ("jira", "工单")), ("pr", ("pull request", "pr")), ("slack", ("slack",)),
                ("calendar", ("日程", "日历", "calendar", "schedule", "meeting")), ("email", ("邮件", "email", "mail")),
                ("suggestions", ("建议", "suggest", "first")))
_H3 = re.compile(r"<h3>(.*?)</h3>\n?", re.S)
_TAG = re.compile(r"<[^>]+>")
_STATUSES = ("connected", "needs-auth", "failed")


def work_briefing(service_of: Callable[[], object], config) -> Callable[[], dict]:
    """工作简报的 provider。``service_of()`` 给 ``WorkBriefingService``（这台机器没有 WSL 时是 None）。"""
    def build() -> dict:
        service = service_of()
        data = {
            "id": WORK_BRIEFING, "title": t("briefing.app"), "theme": theme(config), "available": service is not None,
            "summary": "", "generated": "", "usage": [], "html": "",
            "busy": False, "busy_text": t("briefing.busy"), "empty_text": t("briefing.empty"), "error": "",
            "action": {"name": GENERATE_ACTION, "report": WORK_BRIEFING,
                       "label": t("briefing.button.regenerate"), "hint": t("briefing.button.regenerate_hint")},
            "details": [], "settings_focus": WORK_BRIEFING, "sections": [], "actions": [],
        }
        if service is None:
            return data
        data["busy"] = bool(service.busy)
        error = str(service.last_error() or "")
        data["error"] = t("briefing.status.failed", error=error) if error else ""
        briefing = service.latest()
        if briefing is not None:
            rendered = markdown.render(briefing.markdown, bug_mark=wb.BUG_MARK)
            data.update(summary=briefing.summary, generated=generated_line(briefing.generated_at), usage=usage(briefing),
                        html=rendered, sections=split_sections(rendered))
        data["details"] = trace_sections(getattr(service, "last_trace", dict)() or {})
        return data
    return build


def personal_briefing(service_of: Callable[[], object], config) -> Callable[[], dict]:
    """个人简报的 provider。``service_of()`` 给 ``PersonalService``（没装聊天模块时是 None）。
    和工作简报同一张页；没有运行记录那套事件流，「这次是怎么生成的」只有一段：怎么连的、读了哪些文件、pull 成没成。"""
    def build() -> dict:
        service = service_of()
        data = {
            "id": PERSONAL_BRIEFING, "title": t("personal.app"), "theme": theme(config), "available": service is not None,
            "summary": "", "generated": "", "usage": [], "html": "", "sections": [],
            "busy": False, "busy_text": t("personal.busy", model="?", effort="?"), "empty_text": t("personal.empty"), "error": "",
            "action": {"name": GENERATE_ACTION, "report": PERSONAL_BRIEFING,
                       "label": t("personal.button.regenerate"), "hint": t("personal.button.regenerate_hint")},
            "actions": [{"name": OPEN_INSPIRATION_ACTION, "report": PERSONAL_BRIEFING,
                         "label": t("personal.button.inspiration"), "hint": t("personal.button.inspiration_hint")}],
            "details": [], "settings_focus": "personal",
        }
        if service is None:
            return data
        data["busy"] = bool(service.busy)
        if data["busy"]:
            data["busy_text"] = t("personal.busy", model=service.busy_model or "?", effort=service.busy_effort or "?")
        error = str(service.last_error() or "")
        data["error"] = t("personal.status.failed", error=error) if error else ""
        briefing = service.latest()
        if briefing is not None:
            rendered = markdown.render(briefing.markdown, bug_mark=wb.BUG_MARK)
            data.update(summary=briefing.summary, generated=generated_line(briefing.generated_at, "personal.generated"),
                        usage=usage(briefing), html=rendered, sections=split_sections(rendered), details=personal_details(briefing))
        return data
    return build


def personal_details(briefing) -> list[dict]:
    """个人简报的「这次是怎么生成的」：一段——怎么连的（自己的 key、只读本地克隆、没有连接器）、工具几轮、读了哪些文件、
    git pull 没成功的话是什么原因。全部转义。"""
    e = html.escape
    files = [str(name) for name in getattr(briefing, "files_read", None) or []]
    parts = [f"<p>{e(t('personal.meta.how'))}</p>",
             f"<p>{e(t('personal.trace.rounds', rounds=int(briefing.turns or 0), n=len(files)))}</p>"]
    if files:
        parts.append("<ul>" + "".join(f"<li><code>{e(name)}</code></li>" for name in files) + "</ul>")
    note = str(getattr(briefing, "pull_note", "") or "")
    if note:
        parts.append(f"<p class=\"bad\">{e(t('personal.meta.pull_failed', error=' '.join(note.split())[-120:]))}</p>")
    return [{"title": t("briefing.trace.section", when=_when(briefing.generated_at), state=""), "html": "".join(parts)}]


def generate_briefing(service_of: Callable[[], object]) -> Callable[[], str]:
    """页面上点了「重新生成」：``unavailable``（没接简报服务）/ ``busy`` / ``started`` / ``failed``。工作简报、个人简报同用。"""
    def run() -> str:
        service = service_of()
        if service is None:
            return "unavailable"
        if service.busy:
            return "busy"
        return "started" if service.generate_now() else "failed"
    return run


generate_work_briefing = generate_briefing      # 老名字


def open_inspiration(controller_of: Callable[[], object]) -> Callable[[], str]:
    """个人简报页上点了「记灵感…」：在肥鱼里开个人助理那扇 Qt 窗口的灵感页（动作在界面线程上跑）。
    ``opened`` / ``unavailable``（没接个人助理）。"""
    def run() -> str:
        controller = controller_of()
        if controller is None:
            return "unavailable"
        controller.open_inspiration()
        return "opened"
    return run


def generated_line(generated_at: str, key: str = "briefing.meta") -> str:
    """「生成于 … · 谁做的」那一行；个人简报用自己的句子（``personal.generated``）。"""
    try:
        when = f"{dt.datetime.fromisoformat(generated_at):%m-%d %H:%M}"
    except ValueError:
        when = "?"
    return t(key, when=when)


def usage(briefing: wb.Briefing) -> list[dict]:
    """和 Qt 窗口底下那条图标栏同一套数字（``note_meta_bar.usage_values``），按固定顺序，空的不给。
    个人简报没有花费这一项（自己的 key，Claude Code 才报 cost）：0 就不摆。"""
    from ..note_meta_bar import usage_values

    cost = float(getattr(briefing, "cost_usd", 0.0) or 0.0)
    values = usage_values(briefing.model, briefing.effort, briefing.tokens_in, briefing.tokens_out, cost, briefing.seconds)
    if not cost:
        values.pop("cost", None)
    return [{"key": key, "text": text, "tip": tip} for key in USAGE_ORDER
            for text, tip in [values.get(key, ("", ""))] if text]


def source_of(title: str) -> str:
    """分区标题 → 来源 id（``SOURCE_WORDS`` 的第一个命中；都不中是 ``other``）。"""
    low = title.lower()
    return next((source for source, words in SOURCE_WORDS if any(word in low for word in words)), "other")


def split_sections(rendered: str) -> list[dict]:
    """渲染好的全文按 ``<h3>``（Markdown 的 ``##``）切区，每区数一数顶层的条目：总数、三档优先级、bug、有更新。

    计数只看 ``markdown.render`` 产出的那几种标记：每行一个元素，``<ul>`` / ``<ol>`` 进一层、``</ul>`` / ``</ol>`` 出一层，
    第一层的 ``<li`` 是一条；那一行里的 ``class="star sN"`` 是优先级、``class="bug"`` 是 bug、``<strong>`` 是「有更新」。
    第一个 ``<h3>`` 之前的文字（如果有）算一区，标题空、来源 other。没有 ``<h3>`` 就是空列表。
    """
    if "<h3>" not in rendered:
        return []
    sections: list[dict] = []
    pieces = re.split(r"(?=<h3>)", rendered)
    for piece in pieces:
        if not piece.strip():
            continue
        heading = _H3.match(piece)
        title = _TAG.sub("", heading.group(1)).strip() if heading else ""
        body = piece[heading.end():] if heading else piece
        counts = {"count": 0, "p3": 0, "p2": 0, "p1": 0, "bugs": 0, "updated": 0}
        depth = 0
        for line in body.split("\n"):
            if line.startswith(("<ul>", "<ol>")):
                depth += 1
            elif line.startswith(("</ul>", "</ol>")):
                depth -= 1
            elif line.startswith("<li") and depth == 1:
                counts["count"] += 1
                star = re.search(r'class="star s([123])"', line)
                if star:
                    counts[f"p{star.group(1)}"] += 1
                if line.startswith('<li class="bug"'):
                    counts["bugs"] += 1
                if "<strong>" in line:
                    counts["updated"] += 1
        sections.append({"id": f"s{len(sections) + 1}", "source": source_of(title) if title else "other", "title": title,
                         "html": body.strip("\n"), **counts})
    return sections


def _when(iso: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(iso):%m-%d %H:%M}"
    except (TypeError, ValueError):
        return "?"


def trace_sections(trace: dict) -> list[dict]:
    """运行记录（``work_briefing.parse_trace`` + ``generate`` 填的命令 / 提示词 / 名单）→ 页面上折叠的几段。
    全部转义；只产出 p / table / ol / code / pre / a 这几个标签。没有记录就是空列表（老版本生成的简报）。"""
    if not trace:
        return []
    e = html.escape
    state = "" if trace.get("ok", True) else t("briefing.trace.failed_mark")
    parts = [f"<p class=\"chain\">{e(t('briefing.trace.chain', version=trace.get('version') or '?', model=trace.get('model') or '?', mode=trace.get('permission_mode') or '?', turns=int(trace.get('turns') or 0)))}</p>"]
    rows = []
    for item in trace.get("servers") or []:
        status, name = str(item.get("status") or ""), str(item.get("name") or "")
        label = t(f"briefing.trace.status.{status.replace('-', '_')}") if status in _STATUSES else status   # 字表键不能带连字符
        if item.get("calls"):
            note = t("briefing.trace.used", n=int(item["calls"]))
        elif status == "needs-auth":
            note = t("briefing.trace.needs_auth", name=name)
        elif item.get("allowed"):
            note = t("briefing.trace.allowed_unused")
        else:
            note = t("briefing.trace.not_allowed")
        cls = status if status in _STATUSES else "other"
        rows.append(f"<tr><td>{e(name)}</td><td class=\"st {cls}\">{e(label)}</td><td>{e(note)}</td></tr>")
    parts.append(f"<table class=\"servers\">{''.join(rows)}</table>" if rows else f"<p class=\"note\">{e(t('briefing.trace.no_servers'))}</p>")
    if int(trace.get("others") or 0):
        parts.append(f"<p class=\"note\">{e(t('briefing.trace.others', n=int(trace['others'])))}</p>")
    parts.append(f"<p class=\"note\">{e(t('briefing.trace.tools_present', present=len(trace.get('tools') or []), allowed=len(trace.get('allowed') or [])))}</p>")
    sections = [{"title": t("briefing.trace.section", when=_when(str(trace.get("at") or "")), state=state), "html": "".join(parts)}]

    calls = [call for call in trace.get("calls") or [] if isinstance(call, dict)]
    items = []
    for call in calls:
        tool = str(call.get("tool") or "")
        bits = tool.split("__") if tool.startswith("mcp__") else []
        short, server = (bits[-1], bits[1]) if len(bits) >= 3 else (tool, "")
        ok = call.get("ok")
        mark = '<span class="ok">✓</span>' if ok else ('<span class="bad">✗</span>' if ok is False else "")
        items.append(f"<li><code>{e(short)}</code> <span class=\"srv\">{e(server)}</span> {e(str(call.get('args') or ''))} {mark}</li>")
    body = f"<ol class=\"calls\">{''.join(items)}</ol>" if items else f"<p class=\"note\">{e(t('briefing.trace.no_calls'))}</p>"
    denied = [str(name) for name in trace.get("denied") or []]
    if denied:
        body += f"<p class=\"bad\">{e(t('briefing.trace.denied', names=', '.join(denied)))}</p>"
    sections.append({"title": t("briefing.trace.calls", n=len(calls)), "html": body})

    hooks = [str(name) for name in trace.get("hooks") or []]
    sections.append({"title": t("briefing.trace.hooks"),
                     "html": f"<p>{e(', '.join(hooks))}</p>" if hooks else f"<p class=\"note\">{e(t('briefing.trace.no_hooks'))}</p>"})
    command = "\n".join(str(part) for part in (trace.get("gh_command"), trace.get("command")) if part)
    sections.append({"title": t("briefing.trace.command"), "html": f"<pre>{e(command)}</pre>"})
    sections.append({"title": t("briefing.trace.prompt"),
                     "html": f"<p><a class=\"settings\" href=\"{SETTINGS_URL}\">{e(t('briefing.trace.edit_template'))}</a></p>"
                             f"<pre>{e(str(trace.get('prompt') or ''))}</pre>"})
    return sections


def theme(config) -> str:
    """页面的明暗：跟「外观」里的主题偏好（``system`` 按系统调色板定）。页面上不放切换按钮——那个偏好只在一处改。"""
    from ..work_briefing_ui import resolve_dark, theme_preference

    return "dark" if resolve_dark(theme_preference(config)) else "light"
