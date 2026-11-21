# -*- coding: utf-8 -*-
"""个人助理的界面。个人简报在浏览器里读（配置全景的 ``/report/personal_briefing``，ADR 0018）：岛上的人形、提醒的
「查看」都开那张页；记灵感也在那张页上（顶部的输入区，``panorama.reports.add_inspiration``）；「在 Obsidian 打开 AI-Base」
是页上的副按钮，经 ``panorama.reports.open_obsidian`` 落到这里的 ``open_obsidian``。这里只剩：提醒、岛状态、推送失败的气泡。

Qt 窗口（简报 + 灵感两页，复用简报窗口壳）2026-11-21 随简报窗口一起下线。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from .i18n import t

ALERT_ID = "personal-briefing"


class PersonalController(QObject):
    """把服务的结果摆到宿主上；岛上的按钮状态也从这里报（``state_changed(str)``）。"""

    state_changed = Signal(str)

    def __init__(self, host, service, parent: QObject | None = None, *, open_report: Callable[[], bool] | None = None,
                 report_watched: Callable[[], bool] | None = None) -> None:
        """``open_report``：在浏览器里打开个人简报页，返回是否打开了；没给时「查看」只能冒一句「打不开」。
        ``report_watched``：有没有页面正开着看——有就不再为新一份冒提醒，推送失败也不冒气泡（页面自己写着）。"""
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._open_report = open_report
        self._report_watched = report_watched
        self._unread = False
        service.finished.connect(self._on_finished)
        service.synced.connect(self._on_synced)

    # ---------------------------------------------------------- 动作
    def generate_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble(t("personal.bubble.busy"), 3200)
        elif self.service.generate_now():
            self._host.show_bubble(t("personal.bubble.started", model=self.service.busy_model), 4000)

    def open_obsidian(self) -> None:
        how, target = self.service.open_in_obsidian()
        if how == "folder":
            self._host.show_bubble(t("personal.bubble.obsidian_hint", path=target), 9000)
        elif how == "failed":
            self._host.show_bubble(t("personal.bubble.open_failed", path=target), 5000)

    def open_window(self) -> None:
        """「查看」（岛、提醒）：开浏览器里的个人简报页，打开即读过；开不了冒一句气泡。名字沿用 Qt 窗口时代的。"""
        if self._open_report is not None and self._open_report():
            self._set_unread(False)
        else:
            self._host.show_bubble(t("briefing.bubble.page_failed"), 6000)

    # ---------------------------------------------------------- 岛
    @property
    def island_state(self) -> str:
        """灵动岛上的人形图标：关着自动生成、也从没生成过时不显示。"""
        if self._unread:
            return "unread"
        if self.service.settings()["enabled"] or self.service.latest() is not None:
            return "idle"
        return "hidden"

    def refresh_state(self) -> None:
        self.state_changed.emit(self.island_state)

    def _set_unread(self, unread: bool) -> None:
        if unread != self._unread:
            self._unread = unread
            self.state_changed.emit(self.island_state)

    def _watched(self) -> bool:
        return self._report_watched is not None and bool(self._report_watched())

    # ---------------------------------------------------------- 服务回调
    def _on_finished(self, briefing, _manual: bool) -> None:
        if not briefing.ok:
            self._host.show_bubble(t("personal.bubble.failed", error=briefing.error), 8000)
            return
        if self._watched():
            return   # 页面开着：它自己原地换成新的
        self._set_unread(True)
        self._host.show_alert(
            briefing.summary, subtitle=t("personal.alert.subtitle"), sticky=True,
            buttons=[(t("personal.alert.view"), self._on_view), (t("personal.alert.dismiss"), self._on_dismiss)],
            alert_id=ALERT_ID, priority=1, alert_type="personal_briefing",
        )

    def _on_synced(self, ok: bool, error: str) -> None:
        if not ok and not self._watched():
            self._host.show_bubble(t("personal.inspiration.push_failed", error=" ".join(error.split())[-120:]), 8000)

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
