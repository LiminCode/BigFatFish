# -*- coding: utf-8 -*-
"""报告页：在浏览器里读一份「生成出来的内容」。现在只有工作简报；个人简报以后多登记一项就行。

页面薄、不认功能（ADR 0014）：应用构造 ``PanoramaService`` 时按名字登记 provider（``reports={"work_briefing": …}``）。
provider 在**界面线程**上被调（它读 Qt 对象），返回页面要摆的那份字典：

- ``title`` / ``theme``（``dark`` / ``light``，跟「外观」里的偏好）；
- ``summary``（一句概要）、``generated``（「生成于 …」那一行）、``usage``（模型 / effort / 用时 / tokens / 花费，每项
  ``{key, text, tip}``）、``html``（全文，Markdown 已由 ``markdown.py`` 渲染成只含几个标签的 HTML）；
- ``busy`` / ``busy_text`` / ``empty_text`` / ``error``（上一次失败的原因，已翻成整句）；
- ``action``：底部那个按钮——``{name, report, label, hint}``，页面 ``POST /api/actions/<name>`` 时把 ``report`` 带回来；
- ``available``：这台机器上有没有这项功能（工作简报要 WSL；没有就只显示一句说明）；
- ``details``：「这次是怎么生成的」——几段 ``{title, html}``（服务端渲染、全部转义），页面折叠着摆在全文下面；
  ``settings_focus``：详情里「到设置里改」的链接要翻到配置全景的哪一组（页面自己拼带令牌的地址，替换 ``SETTINGS_URL`` 占位）。

隐私：报告内容只经带令牌的接口给本机浏览器，不落离线快照、不进日志（本机服务只记请求行）。
"""
from __future__ import annotations

import datetime as dt
import html
from typing import Callable

from .. import work_briefing as wb
from ..i18n import t
from . import markdown

WORK_BRIEFING = "work_briefing"
GENERATE_ACTION = "generate_report"                 # 页面上「重新生成」走的动作名（actions.generate_report）
USAGE_ORDER = ("model", "effort", "time", "tokens_in", "tokens_out", "cost")
SETTINGS_URL = "__SETTINGS_URL__"                   # 详情 HTML 里的占位：页面换成 /#<令牌>&settings=<组>
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
            "details": [], "settings_focus": WORK_BRIEFING,
        }
        if service is None:
            return data
        data["busy"] = bool(service.busy)
        error = str(service.last_error() or "")
        data["error"] = t("briefing.status.failed", error=error) if error else ""
        briefing = service.latest()
        if briefing is not None:
            data.update(summary=briefing.summary, generated=generated_line(briefing.generated_at), usage=usage(briefing),
                        html=markdown.render(briefing.markdown, bug_mark=wb.BUG_MARK))
        data["details"] = trace_sections(getattr(service, "last_trace", dict)() or {})
        return data
    return build


def generate_work_briefing(service_of: Callable[[], object]) -> Callable[[], str]:
    """页面上点了「重新生成」：``unavailable``（没接简报服务）/ ``busy`` / ``started`` / ``failed``。"""
    def run() -> str:
        service = service_of()
        if service is None:
            return "unavailable"
        if service.busy:
            return "busy"
        return "started" if service.generate_now() else "failed"
    return run


def generated_line(generated_at: str) -> str:
    try:
        when = f"{dt.datetime.fromisoformat(generated_at):%m-%d %H:%M}"
    except ValueError:
        when = "?"
    return t("briefing.meta", when=when)


def usage(briefing: wb.Briefing) -> list[dict]:
    """和 Qt 窗口底下那条图标栏同一套数字（``note_meta_bar.usage_values``），按固定顺序，空的不给。"""
    from ..note_meta_bar import usage_values

    values = usage_values(briefing.model, briefing.effort, briefing.tokens_in, briefing.tokens_out, briefing.cost_usd,
                          briefing.seconds)
    return [{"key": key, "text": text, "tip": tip} for key in USAGE_ORDER
            for text, tip in [values.get(key, ("", ""))] if text]


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
