# -*- coding: utf-8 -*-
"""Slack 关注摆在哪：有新的需要你看的 → 一个带按钮的提醒气泡；全文在一个窗口里（复用简报的窗口）。

自动检查什么新的都没有时一声不吭；用户点「现在检查」时不管有没有都回一句。失败只在手动时说，
自动检查失败记在状态文件里（窗口底部能看到），不每 15 分钟冒一次。

接了「Slack 关注」页（``notes``，一个 ``WorkNotesController(slack=True)``）之后：每条新的先存成仓库 ``slack/``
里的 Markdown（防止错过），总提醒多一个「稍后 1 小时」把这批都放到一小时后，「查看」开到那一页。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from . import slack_watch as sw
from . import work_briefing as wb
from .i18n import t
from .work_briefing_ui import WorkBriefingWindow, theme_preference, save_theme_preference

ALERT_ID = "slack-watch"


def _as_briefing(result: sw.WatchResult) -> wb.Briefing:
    """窗口认 ``Briefing``：把检查结果装进去（概要 + 条目列表）。"""
    headline = result.summary or (t("slack.ui.d_slack_messages_need_your") % len(result.items) if result.items else t("slack.ui.nothing_needs_your_attention"))
    return wb.Briefing(ok=True, summary=headline, markdown=result.markdown, generated_at=result.checked_at,
                       seconds=result.seconds, turns=result.turns, denied=list(result.denied))


class SlackWatchController(QObject):
    """把服务的结果摆到宿主上；菜单的动作也落在这里。"""

    state_changed = Signal()

    SNOOZE_MINUTES = 60

    def __init__(self, host, service, *, notes=None, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._notes = notes
        self.window: WorkBriefingWindow | None = None
        service.started.connect(self._on_started)
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def check_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble(t("slack.bubble.busy"), 3200)
        elif self.service.check_now():
            self._host.show_bubble(t("slack.bubble.started"), 4000)

    def open_window(self) -> None:
        if self.window is None:
            self.window = WorkBriefingWindow(title=t("slack.app"), regenerate_label=t("slack.button.check"),
                                             empty_text=t("slack.empty"), busy_text=t("slack.busy"),
                                             page_label=t("slack.tab"), theme=theme_preference(self.service._config))
            self.window.theme_changed.connect(lambda theme: save_theme_preference(self.service._config, theme))
            self.window.regenerate_requested.connect(self.service.check_now)
        self._refresh_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def refresh_state(self) -> None:
        self.state_changed.emit()

    # ---------------------------------------------------------- 服务回调
    def _refresh_window(self) -> None:
        if self.window is not None:
            latest = self.service.latest()
            self.window.show_briefing(_as_briefing(latest) if latest is not None else None,
                                      busy=self.service.busy, error=self.service.last_error())

    def _on_started(self, _manual: bool) -> None:
        self._refresh_window()

    def _on_finished(self, result, manual: bool, fresh) -> None:
        self._refresh_window()
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
        """每条新的存进仓库的 slack/（有「Slack 关注」页才存）；返回存下的文件名。"""
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
