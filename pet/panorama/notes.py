# -*- coding: utf-8 -*-
"""笔记页：在浏览器里看、记、处理工作笔记（``work_notes``）和 Slack 关注的存档（``slack_watch``，2026-11-20）。

和报告页同一条路（ADR 0018）：应用把 provider 登记进 ``PanoramaService(reports=…)``，页面向 ``/api/report/<名字>`` 要数据、
带编号等更新；不同的是外壳——provider 函数带属性 ``page = "notes"``，路由据此发 ``notes.html``。页面不认功能（ADR 0014），
只认这份字典：

- ``title`` / ``theme`` / ``available``（没接服务 = 这台机器没有 WSL 或功能关着）/ ``settings_focus``；
- ``composer``（页面顶上有没有输入框：笔记有、Slack 存档没有）、``placeholder`` / ``add_label`` / ``add_hint`` / ``empty_text``；
- ``notes[]``：每条 ``{name, title, kind, status, open, busy, created, created_text, remind_at, remind_text, overdue, reason, tags,
  summary, details_html, original_html, links, usage[]}``——要点是 Markdown 渲染出的 HTML（``markdown.render``），原文**逐字**：
  只转义、裸链接变链接；顺序已经排好：未完成的在前（有提醒的按提醒时间，没提醒的按记下时间倒序），已完成的在后；
- ``counts``：``{open, due, busy, done}``；``repo``：``{ready, dir, status}``（``status`` 是翻好的那一句：仓库没找到 / git 失败原因，空 = 正常）；
- ``watch``：只有 Slack 页有（见 ``slack_watch``）：``{checked_at, checked_text, ago_text, found, next_text, summary, error, busy}``；
  ``action`` / ``actions``：和报告页同一种按钮字典（Slack 页的「现在检查」走报告页的 ``generate_report`` 动作，见 ``check_slack``）；
  ``unavailable_text``：没接服务时页面说的那一句（每页自己的理由）。

动作走 ``POST /api/actions/note {report, op, name, text?, minutes?}``（``note_action``），在界面线程上调 ``WorkNotesService``。
隐私：笔记内容只经带令牌的接口给本机浏览器，不落快照、不进日志。
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from .. import slack_watch as sw
from .. import work_notes as wn
from ..i18n import t
from . import markdown
from .actions import ActionError
from .reports import GENERATE_ACTION, theme
from .sources import L

WORK_NOTES = "work_notes"
SLACK_WATCH = "slack_watch"
NOTE_ACTION = "note"
PAGE = "notes"
#: ``op`` → 回答里的 ``state``，见 ``note_action``
OPS = ("add", "resummarize", "done", "snooze", "delete", "open_link", "obsidian", "folder", "push")
USAGE_ORDER = ("model", "tokens_in", "tokens_out", "cost", "time")
_SNOOZE_MINUTES = {minutes for _key, minutes in wn.SNOOZE_CHOICES}


def _when(value: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%m-%d %H:%M}"
    except (TypeError, ValueError):
        return ""


def note_dict(note: wn.Note, *, busy: bool, now: dt.datetime) -> dict:
    """一条笔记 → 页面要摆的字典。要点渲染成 HTML，原文只转义 + 链接化。"""
    from ..note_meta_bar import usage_values

    is_open = note.status != wn.STATUS_DONE
    remind = note.remind_dt
    values = usage_values(note.model, "", note.tokens_in, note.tokens_out, note.cost_usd, note.seconds) if note.model else {}
    return {
        "name": note.name, "title": note.title, "kind": note.kind or "text", "status": note.status, "open": is_open, "busy": busy,
        "created": note.created, "created_text": _when(note.created),
        "remind_at": note.remind_at if is_open else "", "remind_text": _when(note.remind_at) if is_open else "",
        "overdue": bool(is_open and remind is not None and remind <= now), "reason": note.reason if is_open else "",
        "tags": list(note.tags), "summary": note.summary, "details_html": markdown.render(note.details) if note.details else "",
        "original_html": markdown.linkify(note.original), "links": list(note.links),
        "usage": [{"key": key, "text": text, "tip": tip} for key in USAGE_ORDER for text, tip in [values.get(key, ("", ""))] if text],
    }


def order(notes: list[wn.Note]) -> list[wn.Note]:
    """未完成的在前：有提醒的按提醒时间（早的在前），没提醒的按记下时间倒序；已完成的在后，按记下时间倒序。"""
    open_notes = [note for note in notes if note.status != wn.STATUS_DONE]
    due = sorted((note for note in open_notes if note.remind_at), key=lambda note: note.remind_at)
    rest = sorted((note for note in open_notes if not note.remind_at), key=lambda note: note.created, reverse=True)
    done = sorted((note for note in notes if note.status == wn.STATUS_DONE), key=lambda note: note.created, reverse=True)
    return due + rest + done


def _base(name: str, title: str, config, *, composer: bool, empty_key: str, settings_focus: str, unavailable_key: str) -> dict:
    return {
        "id": name, "page": PAGE, "title": title, "theme": theme(config), "available": False, "settings_focus": settings_focus,
        "unavailable_text": t(unavailable_key),
        "composer": composer, "placeholder": t("notes.input.placeholder") if composer else "",
        "add_label": t("notes.button.add") if composer else "", "add_hint": t("notes.button.add_hint") if composer else "",
        "empty_text": t(empty_key), "notes": [], "counts": {"open": 0, "due": 0, "busy": 0, "done": 0},
        "repo": {"ready": True, "dir": "", "status": ""}, "watch": None, "action": None, "actions": [],
    }


def fill_notes(data: dict, service, now: dt.datetime | None = None) -> dict:
    """把一个 ``WorkNotesService`` 的现状写进 ``data``（笔记页、Slack 页共用）。"""
    now = now or dt.datetime.now()
    busy = set(service.busy_names)
    notes = order(service.notes())
    data["available"] = True
    data["notes"] = [note_dict(note, busy=note.name in busy, now=now) for note in notes]
    data["counts"] = {"open": sum(1 for item in data["notes"] if item["open"]),
                      "due": sum(1 for item in data["notes"] if item["remind_at"]),
                      "busy": sum(1 for item in data["notes"] if item["busy"]),
                      "done": sum(1 for item in data["notes"] if not item["open"])}
    settings = service.settings()
    ready, error = bool(service.repo_ready()), str(service.last_error() or "")
    status = error
    if not ready:
        status = t("notes.status.no_repo", path=settings["repo_dir"]) + (f" · {error}" if error else "")
    data["repo"] = {"ready": ready, "dir": settings["repo_dir"], "status": status}
    return data


def work_notes(service_of: Callable[[], object], config, *, now: Callable[[], dt.datetime] | None = None) -> Callable[[], dict]:
    """工作笔记页的 provider。``service_of()`` 给笔记的 ``WorkNotesService``（功能关着 / 没有 WSL 时是 None）。"""
    def build() -> dict:
        data = _base(WORK_NOTES, t("notes.menu.open"), config, composer=True, empty_key="notes.hint.empty", settings_focus=WORK_NOTES,
                     unavailable_key="panorama.ui.notes_unavailable")
        service = service_of()
        if service is None:
            return data
        return fill_notes(data, service, now() if now else None)
    build.page = PAGE  # type: ignore[attr-defined]
    return build


def _ago(then: dt.datetime, now: dt.datetime) -> str:
    """「N 分钟前」那一句（和页面 ``util.ago`` 同一组字）。"""
    seconds = max(0.0, (now - then).total_seconds())
    if seconds < 60:
        return L("ui.ago_now")
    if seconds < 3600:
        return L("ui.ago_minutes", n=int(seconds // 60))
    if seconds < 86400:
        return L("ui.ago_hours", n=int(seconds // 3600))
    return L("ui.ago_days", n=int(seconds // 86400))


def watch_block(service, now: dt.datetime) -> dict:
    """Slack 关注的检查状态条：上次检查（几点、多久前、发现几条、概要）、下一次大约几点（上次 + 间隔）、失败原因、忙不忙。
    上次的结果来自 ``service.latest()``（状态文件里的最近一次成功）；失败原因是 ``last_error()``（自动检查失败不冒气泡，只在这里看得到）。"""
    latest = service.latest()
    block = {"checked_at": "", "checked_text": "", "ago_text": "", "found": None, "next_text": "", "summary": "",
             "error": str(service.last_error() or ""), "busy": bool(service.busy)}
    if latest is None or not latest.checked_at:
        return block
    try:
        checked = dt.datetime.fromisoformat(latest.checked_at)
    except ValueError:
        return block
    interval = int(service.settings().get("interval_minutes") or sw.DEFAULT_INTERVAL_MIN)
    block.update(checked_at=latest.checked_at, checked_text=f"{checked:%m-%d %H:%M}", ago_text=_ago(checked, now), found=len(latest.items),
                 next_text=f"{checked + dt.timedelta(minutes=interval):%H:%M}", summary=latest.summary)
    return block


def slack_watch(notes_of: Callable[[], object], watch_of: Callable[[], object], config, *,
                now: Callable[[], dt.datetime] | None = None) -> Callable[[], dict]:
    """Slack 关注页的 provider：上面是检查状态条 + 「现在检查」，下面是存档（仓库 ``slack/`` 里的那些笔记，没有输入框）。
    ``watch_of()`` 给 ``SlackWatchService``（没有 WSL 时 None → 页面只说一句不可用）；``notes_of()`` 给存档的 ``WorkNotesService``
    （工作笔记关着时 None → 只有状态条，列表是空的、说明写着要开工作笔记）。"""
    def build() -> dict:
        data = _base(SLACK_WATCH, t("slack.app"), config, composer=False, empty_key="slack.notes.hint.empty", settings_focus=SLACK_WATCH,
                     unavailable_key="panorama.ui.notes_slack_unavailable")
        watch = watch_of()
        if watch is None:
            return data
        at = now() if now else dt.datetime.now()
        data["available"] = True
        data["watch"] = watch_block(watch, at)
        data["action"] = {"name": GENERATE_ACTION, "report": SLACK_WATCH, "label": t("slack.button.check"), "hint": ""}
        notes_service = notes_of()
        if notes_service is None:
            data["empty_text"] = t("panorama.ui.notes_slack_no_archive")
            return data
        return fill_notes(data, notes_service, at)
    build.page = PAGE  # type: ignore[attr-defined]
    return build


def check_slack(service_of: Callable[[], object]) -> Callable[[], str]:
    """Slack 页的「现在检查」（走报告页的 ``generate_report`` 动作）：``unavailable`` / ``busy`` / ``started`` / ``failed``。"""
    def run() -> str:
        service = service_of()
        if service is None:
            return "unavailable"
        if service.busy:
            return "busy"
        return "started" if service.check_now() else "failed"
    return run


def note_action(services: dict[str, Callable[[], object]]) -> Callable[[object], dict]:
    """``POST /api/actions/note``。``services``：报告名 → 给那一页的 ``WorkNotesService`` 的函数。

    回答 ``{report, op, state}``：``add`` → ``saved``（带 ``name``）/ ``empty`` / ``failed``；``resummarize`` → ``started`` / ``busy``；
    ``done`` / ``snooze`` / ``delete`` → ``done`` / ``missing`` / ``failed``；``open_link`` → ``opened`` / ``no_link``；
    ``obsidian`` → ``opened`` / ``folder``（库没登记，开的是文件夹）；``folder`` / ``push`` → ``opened`` / ``started``。
    删除前的确认在页面上（``confirm()``），这里拿到的请求就是「用户点了是」。
    不认识的报告名 / 动作 400，没接服务 503，``snooze`` 的分钟数只认 ``work_notes.SNOOZE_CHOICES`` 里的。
    """
    def run(body) -> dict:
        body = body if isinstance(body, dict) else {}
        report, op = body.get("report"), body.get("op")
        if not isinstance(report, str) or report not in services:
            raise ActionError(400, "bad_report")
        if not isinstance(op, str) or op not in OPS:
            raise ActionError(400, "bad_op")
        service = services[report]()
        if service is None:
            raise ActionError(503, "unavailable")
        name = body.get("name") if isinstance(body.get("name"), str) else ""
        out = {"report": report, "op": op}
        if op == "add":
            text = body.get("text") if isinstance(body.get("text"), str) else ""
            if not text.strip():
                return {**out, "state": "empty"}
            note = service.add(text)
            return {**out, "state": "saved", "name": note.name} if note is not None else {**out, "state": "failed", "error": service.last_error()}
        if op == "push":
            service.push_now()
            return {**out, "state": "started"}
        if op == "folder":
            service.open_folder()
            return {**out, "state": "opened"}
        if not name:
            raise ActionError(400, "bad_name")
        if op == "resummarize":
            return {**out, "state": "started" if service.resummarize(name) else "busy"}
        if op == "open_link":
            return {**out, "state": "opened" if service.open_link(name) else "no_link"}
        if op == "obsidian":
            return {**out, "state": "opened" if service.open_in_obsidian(name) else "folder"}
        if service.note(name) is None:
            return {**out, "state": "missing"}
        if op == "done":
            changed = service.mark_done(name)
        elif op == "snooze":
            minutes = body.get("minutes")
            if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes not in _SNOOZE_MINUTES:
                raise ActionError(400, "bad_minutes")
            changed = service.snooze(name, minutes)
        else:
            changed = service.delete(name)
        return {**out, "state": "done" if changed is not None else "failed", "error": "" if changed is not None else service.last_error()}

    return run
