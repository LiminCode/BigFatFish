# -*- coding: utf-8 -*-
"""Slack 关注摆在哪：有新的需要你看的 → 一个带按钮的提醒气泡；最近一次结果和存档在浏览器里的 Slack 关注页
（``open_report``，配置全景的 ``/report/slack_watch``）。

自动检查什么新的都没有时一声不吭；用户点「现在检查」时不管有没有都回一句。失败只在手动时说，
自动检查失败记在状态文件里（页面的检查状态条能看到），不每 15 分钟冒一次。

接了「Slack 关注」存档（``notes``，一个 ``WorkNotesController(slack=True)``）之后：每条新的先存成仓库 ``slack/``
里的 Markdown（防止错过），总提醒多一个「稍后 1 小时」把这批都放到一小时后，「查看」开到页面上那一条。

Qt 的独立结果窗口 2026-11-21 随简报窗口一起下线；本机服务起不来时只冒一句气泡。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from . import slack_watch as sw
from .i18n import t

ALERT_ID = "slack-watch"


class SlackWatchController(QObject):
    """把服务的结果摆到宿主上；菜单的动作也落在这里。"""

    state_changed = Signal()

    SNOOZE_MINUTES = 60

    def __init__(self, host, service, *, notes=None, open_report: Callable[[], object] | None = None,
                 parent: QObject | None = None) -> None:
        """``open_report()``：在浏览器里开 Slack 关注页（返回真假）；没给或开不了时「查看最近一次检查」只能冒一句「打不开」。"""
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._notes = notes
        self._open_report = open_report
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def check_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble(t("slack.bubble.busy"), 3200)
        elif self.service.check_now():
            self._host.show_bubble(t("slack.bubble.started"), 4000)

    def open_window(self) -> None:
        """「查看最近一次检查」：浏览器里的 Slack 关注页；开不了（本机服务起不来）冒一句气泡。名字沿用 Qt 窗口时代的。"""
        if self._open_report is not None and self._open_report():
            return
        self._host.show_bubble(t("slack.bubble.page_failed"), 7000)

    def refresh_state(self) -> None:
        self.state_changed.emit()

    # ---------------------------------------------------------- 服务回调
    def _on_finished(self, result, manual: bool, fresh) -> None:
        fresh = list(fresh or [])
        if not result.ok:
            if manual:
                self._host.show_bubble(t("slack.bubble.failed", error=result.error), 8000)
            return
        if not fresh:
            if manual:
                self._host.show_bubble(t("slack.bubble.nothing"), 4000)
            return
        urgent = any(item.get("urgency") == "high" for item in fresh)
        text = result.summary or sw.ALERT_FALLBACK.format(n=len(fresh))
        names = self._archive(fresh)
        buttons = [(t("briefing.alert.view"), lambda: self._on_view(names))]
        if self._notes is not None:
            buttons.append((t("notes.alert.snooze"), lambda: self._on_snooze(names)))
        buttons.append((t("briefing.alert.dismiss"), self._on_dismiss))
        self._host.show_alert(
            text, subtitle=t("slack.alert.subtitle", n=len(fresh)) + (t("slack.alert.urgent") if urgent else ""), sticky=True,
            buttons=buttons, alert_id=ALERT_ID, priority=1 if urgent else 2, alert_type="slack_watch",
        )

    def _archive(self, fresh: list[dict]) -> list[str]:
        """每条新的存进仓库的 slack/（有「Slack 关注」存档才存）；返回存下的文件名。"""
        if self._notes is None:
            return []
        try:
            return [note.name for note in self._notes.service.add_slack_items(fresh)]
        except Exception:  # noqa: BLE001 - 存档失败不影响提醒本身
            import logging

            logging.getLogger(__name__).exception("Slack 关注：存档失败")
            return []

    def _on_view(self, names: list[str] | None = None) -> None:
        self._host.resolve_alert(ALERT_ID)
        if self._notes is not None:
            self._notes.open_notes(names[0] if names else "")
        else:
            self.open_window()

    def _on_snooze(self, names: list[str]) -> None:
        """「稍后 1 小时」：这批都放到一小时后，到点肥鱼逐条再提醒。"""
        self._host.resolve_alert(ALERT_ID)
        for name in names:
            self._notes.service.snooze(name, self.SNOOZE_MINUTES)

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
