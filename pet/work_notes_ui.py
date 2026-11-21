# -*- coding: utf-8 -*-
"""工作笔记摆在哪：浏览器里的笔记页（``open_report``，配置全景的 ``/report/work_notes``）+ 到点的提醒气泡。

``WorkNotesController`` 只管两件事：提醒（宿主的 ``show_alert``，留到用户点为止，和简报 / Slack 关注同一套；「查看」开到
浏览器里的那一条）和总结失败的气泡。看、记、处理都在页面上（``panorama/notes.py`` 的 provider 与 ``note`` 动作）。
``slack=True`` 是「Slack 关注」存档的控制器：提醒的「查看」直接开那条 Slack 链接，提醒 id 另起前缀。笔记内容不送语音合成；
提醒文字跟随 ``ui_language``。

简报窗口里的 Qt「笔记」/「Slack 关注」页 2026-11-21 随简报窗口一起下线；本机服务起不来时只冒一句气泡。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject

from . import work_notes as wn
from .i18n import t

ALERT_PREFIX = "work-note:"
SLACK_ALERT_PREFIX = "slack-note:"


class WorkNotesController(QObject):
    """把服务接到提醒气泡上；「查看」开浏览器里的笔记页。"""

    def __init__(self, host, service, *, slack: bool = False, open_report: Callable[[str], object] | None = None,
                 parent: QObject | None = None) -> None:
        """``slack=True``：这是「Slack 关注」页的控制器——提醒的「查看」直接开那条 Slack 链接，提醒 id 另起前缀。
        ``open_report(name)``：在浏览器里开笔记页并选中那一条（返回真假）；没给或开不了时只能冒一句「打不开」。"""
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._slack = slack
        self._alert_prefix = SLACK_ALERT_PREFIX if slack else ALERT_PREFIX
        self._open_report = open_report
        service.summarized.connect(self._on_summarized)
        service.reminder_due.connect(self._on_reminder)

    def open_notes(self, name: str = "") -> None:
        """开到笔记：浏览器里的笔记页（选中 ``name``）；没接页面或开不了（本机服务起不来）时冒一句气泡。"""
        if self._open_report is not None and self._open_report(name):
            return
        self._host.show_bubble(t("slack.bubble.page_failed" if self._slack else "notes.bubble.page_failed"), 7000)

    def view(self, name: str) -> None:
        """查看一条 Slack 关注：有链接就开那条消息；没有就开到页面上那条。"""
        if not self.service.open_link(name):
            self.open_notes(name)

    # ---------------------------------------------------------- 服务回调
    def _on_summarized(self, name: str, ok: bool, error: str) -> None:
        if not ok:
            self._host.show_bubble(t("notes.bubble.summary_failed", reason=error), 7000)

    def _on_reminder(self, note: wn.Note) -> None:
        alert_id = self._alert_prefix + note.name
        subtitle = t("slack.notes.alert.subtitle" if self._slack else "notes.alert.subtitle", title=note.title)
        self._host.show_alert(
            note.summary or note.title, subtitle=subtitle, sticky=True,
            buttons=[(t("notes.alert.view"), lambda: self._view(alert_id, note.name)),
                     (t("notes.alert.snooze"), lambda: self._snooze(alert_id, note.name)),
                     (t("notes.alert.done"), lambda: self._done(alert_id, note.name))],
            alert_id=alert_id, priority=1, alert_type="slack_watch" if self._slack else "work_note",
        )

    def _view(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        if self._slack:
            self.view(name)
        else:
            self.open_notes(name)

    def _snooze(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        self.service.snooze(name, 60)

    def _done(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        self.service.mark_done(name)
