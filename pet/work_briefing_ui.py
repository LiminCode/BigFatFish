# -*- coding: utf-8 -*-
"""工作简报摆在哪：一个带按钮的气泡（一句话概要）+ 一个看全文的窗口。

``WorkBriefingController`` 的宿主是 overlay 壳（只用它的 ``show_alert`` /
``resolve_alert`` / ``show_bubble``），数据来自 ``WorkBriefingService``。

概要用提醒气泡而不是普通气泡：普通气泡几秒就消失，早上那一下人不一定在看；提醒气泡
留到用户点「查看」或「知道了」为止。气泡文字不送语音合成，简报内容也不进聊天窗。
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import work_briefing as wb
from .settings_widgets import _system_dark

ALERT_ID = "work-briefing"
_EMPTY = "还没有简报。点「重新生成」现在做一份，大约一分钟。"
_BUSY = "正在生成，大约一分钟…"

# 颜色、圆角、字号取自设置页那一套（.agents/skills/desktop-pet-ui-style 的 visual-system）。
_PALETTES = {
    False: {"window": "#fcfcfd", "card": "#ffffff", "border": "#e2e4e8", "title": "#171717",
            "text": "#252525", "muted": "#777777", "hover": "#f4f5f6"},
    True: {"window": "#202024", "card": "#2a2a30", "border": "#3a3a42", "title": "#f0f0f5",
           "text": "#e0e0e6", "muted": "#9a9aa3", "hover": "#303036"},
}
_QSS = """
QWidget#workBriefing {{ background: {window}; }}
QLabel#briefingTitle {{ color: {title}; font-size: 22px; font-weight: 600; }}
QLabel#briefingMeta, QLabel#briefingStatus {{ color: {muted}; font-size: 12px; }}
QTextBrowser#briefingBody {{
    background: {card}; color: {text}; border: 1px solid {border}; border-radius: 12px;
    padding: 12px 14px; font-size: 13px;
}}
QPushButton {{
    background: {card}; color: {text}; border: 1px solid {border}; border-radius: 7px;
    min-height: 26px; padding: 2px 14px; font-size: 13px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:focus {{ border-color: #0a84ff; }}
QPushButton:disabled {{ color: {muted}; }}
"""


def _meta_line(briefing: wb.Briefing) -> str:
    try:
        when = f"{dt.datetime.fromisoformat(briefing.generated_at):%m-%d %H:%M}"
    except ValueError:
        when = "?"
    return f"生成于 {when} · 用时 {briefing.seconds:.0f} 秒 · 由 WSL 里的 Claude Code 读取并总结"


class WorkBriefingWindow(QWidget):
    """看全文的窗口。``regenerate_requested``：用户点了「重新生成」。"""

    regenerate_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Window)
        self.setObjectName("workBriefing")
        self.setWindowTitle("工作简报")
        self.setStyleSheet(_QSS.format(**_PALETTES[bool(_system_dark())]))
        self.resize(580, 660)
        self.setMinimumSize(380, 320)

        self.title_label = QLabel("工作简报", self)
        self.title_label.setObjectName("briefingTitle")
        self.meta_label = QLabel("", self)
        self.meta_label.setObjectName("briefingMeta")
        self.meta_label.setWordWrap(True)
        self.body = QTextBrowser(self)
        self.body.setObjectName("briefingBody")
        self.body.setOpenExternalLinks(True)
        self.body.setAccessibleName("简报全文")
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("briefingStatus")
        self.status_label.setWordWrap(True)
        self.regenerate_btn = QPushButton("重新生成", self)
        self.regenerate_btn.setAccessibleDescription("让 WSL 里的 Claude Code 重新读一遍并总结，大约一分钟")
        self.regenerate_btn.clicked.connect(self.regenerate_requested)
        self.close_btn = QPushButton("关闭", self)
        self.close_btn.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.regenerate_btn)
        buttons.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.body, 1)
        layout.addLayout(buttons)

    def show_briefing(self, briefing: wb.Briefing | None, *, busy: bool = False, error: str = "") -> None:
        """摆上最近一份；``busy`` 时按钮变灰，``error`` 是最近一次失败的原因。"""
        if briefing is None:
            self.meta_label.setText("")
            self.body.setPlainText(_BUSY if busy else _EMPTY)
        else:
            self.meta_label.setText(_meta_line(briefing))
            self.body.setMarkdown(f"**{briefing.summary}**\n\n{briefing.markdown}")
        self.regenerate_btn.setEnabled(not busy)
        if busy:
            self.status_label.setText(_BUSY)
        else:
            self.status_label.setText(f"上一次没生成出来：{error}" if error else "")


class WorkBriefingController(QObject):
    """把服务的结果摆到宿主上；菜单的几个动作也落在这里。"""

    def __init__(self, host, service, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self.window: WorkBriefingWindow | None = None
        service.started.connect(self._on_started)
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def generate_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble("工作简报还在生成，再等一下～", 3200)
        elif self.service.generate_now():
            self._host.show_bubble("这就去看看今天有什么，大约一分钟～", 4000)

    def open_window(self) -> None:
        if self.window is None:
            self.window = WorkBriefingWindow()
            self.window.regenerate_requested.connect(self.service.generate_now)
        self._refresh_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    # ---------------------------------------------------------- 服务回调
    def _refresh_window(self) -> None:
        if self.window is not None:
            self.window.show_briefing(self.service.latest(), busy=self.service.busy,
                                      error=self.service.last_error())

    def _on_started(self, _manual: bool) -> None:
        self._refresh_window()

    def _on_finished(self, briefing, _manual: bool) -> None:
        self._refresh_window()
        if not briefing.ok:
            self._host.show_bubble(f"工作简报没生成出来：{briefing.error}", 8000)
            return
        if self.window is not None and self.window.isVisible():
            return  # 用户正开着窗口看：内容已经换成新的了，不用再冒气泡
        self._host.show_alert(
            briefing.summary, subtitle="今天的工作简报", sticky=True,
            buttons=[("查看", self._on_view), ("知道了", self._on_dismiss)],
            alert_id=ALERT_ID, priority=1, alert_type="work_briefing",
        )

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
