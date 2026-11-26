# -*- coding: utf-8 -*-
"""随手记复习的提醒（界面）：把 ``ReviewService.remind`` 摆到宿主上。复习本身在浏览器里（``/report/review``）。

- **每天定点**（``daily``）：「今天有 N 条笔记该复习了」，按钮「开始复习」（开复习页）/「稍后」；
- **白天随机**（``random``）：「还记得「标题」讲了什么吗？」，按钮「看看」（把这条排到复习页第一张再打开）/「跳过」。

复习页正开着时不弹（页面自己会刷新）。两种提醒共用一个提醒 id：新的替掉旧的，不叠两条。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject

from .i18n import t

ALERT_ID = "capture-review"


class ReviewController(QObject):
    def __init__(self, host, service, parent: QObject | None = None, *, open_report: Callable[[], bool] | None = None,
                 report_watched: Callable[[], bool] | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._open_report = open_report
        self._report_watched = report_watched
        service.remind.connect(self._on_remind)

    def _watched(self) -> bool:
        return self._report_watched is not None and bool(self._report_watched())

    def open_page(self) -> None:
        if self._open_report is None or not self._open_report():
            self._host.show_bubble(t("review.bubble.page_failed"), 6000)

    def _on_remind(self, kind: str, payload) -> None:
        if self._watched():
            return
        payload = payload if isinstance(payload, dict) else {}
        if kind == "daily":
            text = t("review.alert.daily", n=int(payload.get("count") or 0))
            buttons = [(t("review.alert.start"), self._on_start), (t("review.alert.later"), self._on_dismiss)]
        elif kind == "random":
            path = str(payload.get("path") or "")
            text = t("review.alert.random", title=str(payload.get("title") or ""))
            buttons = [(t("review.alert.look"), lambda: self._on_look(path)), (t("review.alert.skip"), self._on_dismiss)]
        else:
            return
        self._host.show_alert(text, subtitle=t("review.alert.subtitle"), sticky=True, buttons=buttons, alert_id=ALERT_ID,
                              priority=2, alert_type="capture_review")

    def _on_start(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_page()

    def _on_look(self, path: str) -> None:
        self._host.resolve_alert(ALERT_ID)
        if path:
            self.service.spotlight(path)
        self.open_page()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
