# -*- coding: utf-8 -*-
"""Slack 关注摆在哪：有新的需要你看的 → 一个带按钮的提醒气泡；全文在一个窗口里（复用简报的窗口）。

自动检查什么新的都没有时一声不吭；用户点「现在检查」时不管有没有都回一句。失败只在手动时说，
自动检查失败记在状态文件里（窗口底部能看到），不每 15 分钟冒一次。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from . import slack_watch as sw
from . import work_briefing as wb
from .work_briefing_ui import WorkBriefingWindow

ALERT_ID = "slack-watch"
WINDOW_TITLE = "Slack 关注"
_EMPTY = "还没有检查过。点「现在检查」让 WSL 里的 Claude Code 看一眼 Slack，大约半分钟。"
_BUSY = "正在看 Slack，大约半分钟…"


def _as_briefing(result: sw.WatchResult) -> wb.Briefing:
    """窗口认 ``Briefing``：把检查结果装进去（概要 + 条目列表）。"""
    headline = result.summary or ("Slack 上有 %d 条需要你看的" % len(result.items) if result.items else "没有需要你看的")
    return wb.Briefing(ok=True, summary=headline, markdown=result.markdown, generated_at=result.checked_at,
                       seconds=result.seconds, turns=result.turns, denied=list(result.denied))


class SlackWatchController(QObject):
    """把服务的结果摆到宿主上；菜单的动作也落在这里。"""

    state_changed = Signal()

    def __init__(self, host, service, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self.window: WorkBriefingWindow | None = None
        service.started.connect(self._on_started)
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def check_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble("还在看 Slack，再等一下～", 3200)
        elif self.service.check_now():
            self._host.show_bubble("这就去看看 Slack，大约半分钟～", 4000)

    def open_window(self) -> None:
        if self.window is None:
            self.window = WorkBriefingWindow(title=WINDOW_TITLE, regenerate_label="现在检查",
                                             empty_text=_EMPTY, busy_text=_BUSY)
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
                self._host.show_bubble(f"Slack 没看成：{result.error}", 8000)
            return
        if not fresh:
            if manual:
                self._host.show_bubble("Slack 上没有新的需要你看的～", 4000)
            return
        urgent = any(item.get("urgency") == "high" for item in fresh)
        text = result.summary or sw.ALERT_FALLBACK.format(n=len(fresh))
        self._host.show_alert(
            text, subtitle=f"Slack · {len(fresh)} 条需要你看" + ("（有急的）" if urgent else ""), sticky=True,
            buttons=[("查看", self._on_view), ("知道了", self._on_dismiss)],
            alert_id=ALERT_ID, priority=1 if urgent else 2, alert_type="slack_watch",
        )

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
