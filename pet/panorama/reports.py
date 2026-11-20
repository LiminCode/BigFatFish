# -*- coding: utf-8 -*-
"""报告页：在浏览器里读一份「生成出来的内容」。现在只有工作简报；个人简报以后多登记一项就行。

页面薄、不认功能（ADR 0014）：应用构造 ``PanoramaService`` 时按名字登记 provider（``reports={"work_briefing": …}``）。
provider 在**界面线程**上被调（它读 Qt 对象），返回页面要摆的那份字典：

- ``title`` / ``theme``（``dark`` / ``light``，跟「外观」里的偏好）；
- ``summary``（一句概要）、``generated``（「生成于 …」那一行）、``usage``（模型 / effort / 用时 / tokens / 花费，每项
  ``{key, text, tip}``）、``html``（全文，Markdown 已由 ``markdown.py`` 渲染成只含几个标签的 HTML）；
- ``busy`` / ``busy_text`` / ``empty_text`` / ``error``（上一次失败的原因，已翻成整句）；
- ``action``：底部那个按钮——``{name, report, label, hint}``，页面 ``POST /api/actions/<name>`` 时把 ``report`` 带回来；
- ``available``：这台机器上有没有这项功能（工作简报要 WSL；没有就只显示一句说明）。

隐私：报告内容只经带令牌的接口给本机浏览器，不落离线快照、不进日志（本机服务只记请求行）。
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from .. import work_briefing as wb
from ..i18n import t
from . import markdown

WORK_BRIEFING = "work_briefing"
GENERATE_ACTION = "generate_report"                 # 页面上「重新生成」走的动作名（actions.generate_report）
USAGE_ORDER = ("model", "effort", "time", "tokens_in", "tokens_out", "cost")


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


def theme(config) -> str:
    """页面的明暗：跟「外观」里的主题偏好（``system`` 按系统调色板定）。页面上不放切换按钮——那个偏好只在一处改。"""
    from ..work_briefing_ui import resolve_dark, theme_preference

    return "dark" if resolve_dark(theme_preference(config)) else "light"
