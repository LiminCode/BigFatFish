# -*- coding: utf-8 -*-
"""工作简报摆在哪：一个带按钮的气泡（一句话概要）+ 浏览器里的简报页。

``WorkBriefingController`` 的宿主是 overlay 壳（只用它的 ``show_alert`` / ``resolve_alert`` / ``show_bubble``），数据来自
``WorkBriefingService``；「查看」经 ``open_report`` 开配置全景的 ``/report/work_briefing``（ADR 0018），打开即算读过。

概要用提醒气泡而不是普通气泡：普通气泡几秒就消失，早上那一下人不一定在看；提醒气泡留到用户点「查看」或「知道了」为止。
气泡文字不送语音合成，简报内容也不进聊天窗。

Qt 的简报窗口 ``WorkBriefingWindow``（Metro 壳，曾给简报 / 笔记 / Slack 关注 / 个人助理四处复用）2026-11-21 下线：四页都在
浏览器里了，本机服务起不来时只冒一句气泡，没有离线退路（原来的窗口也要肥鱼开着才有）。主题偏好的几个函数搬到了
``window_theme``。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from .i18n import t

ALERT_ID = "work-briefing"


class WorkBriefingController(QObject):
    """把服务的结果摆到宿主上；菜单的几个动作也落在这里。

    ``state_changed(str)``：灵动岛上那个按钮该是什么样——``idle`` 或 ``unread``
    （有一份生成好了、用户还没打开看过）。"""

    state_changed = Signal(str)

    def __init__(self, host, service, parent: QObject | None = None, *, open_report: Callable[[], bool] | None = None,
                 report_watched: Callable[[], bool] | None = None) -> None:
        """``open_report``：在浏览器里打开简报页（配置全景的 ``PanoramaService.open_report``），返回是否打开了；没给
        （测试、旧接线）时「查看」只能冒一句「打不开」。``report_watched``：有没有页面正开着看——有就不再为新一份冒提醒
        （页面已经原地换成新的了）。"""
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._open_report = open_report
        self._report_watched = report_watched
        self._unread = False
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def generate_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble(t("briefing.bubble.busy"), 3200)
        elif self.service.generate_now():
            self._host.show_bubble(t("briefing.bubble.started"), 4000)

    def open_window(self) -> None:
        """「查看」（菜单、岛按钮、提醒）：开浏览器里的简报页，打开即算读过；开不了（本机服务起不来）冒一句气泡。
        名字沿用 Qt 窗口时代的——菜单外观层和岛都这么调。"""
        if self._open_report is not None and self._open_report():
            self._set_unread(False)
        else:
            self._host.show_bubble(t("briefing.bubble.page_failed"), 7000)

    @property
    def island_state(self) -> str:
        """灵动岛上的按钮：没开自动生成、也从没生成过的人看不到它（``hidden``）。"""
        if self._unread:
            return "unread"
        if self.service.settings()["enabled"] or self.service.latest() is not None:
            return "idle"
        return "hidden"

    def refresh_state(self) -> None:
        """设置变了（菜单里开 / 关了自动生成）：让岛重新问一次按钮该不该在。"""
        self.state_changed.emit(self.island_state)

    def _set_unread(self, unread: bool) -> None:
        if unread != self._unread:
            self._unread = unread
            self.state_changed.emit(self.island_state)

    # ---------------------------------------------------------- 服务回调
    def _on_finished(self, briefing, _manual: bool) -> None:
        if not briefing.ok:
            self._host.show_bubble(t("briefing.bubble.failed", error=briefing.error), 8000)
            return
        if self._report_watched is not None and self._report_watched():
            return  # 用户正开着浏览器里的简报页：页面已经原地换成新的了，不用再冒提醒
        self._set_unread(True)   # 点「知道了」只是收起气泡；打开看过才算读了
        self._host.show_alert(
            briefing.summary, subtitle=t("briefing.alert.subtitle"), sticky=True,
            buttons=[(t("briefing.alert.view"), self._on_view), (t("briefing.alert.dismiss"), self._on_dismiss)],
            alert_id=ALERT_ID, priority=1, alert_type="work_briefing",
        )

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
