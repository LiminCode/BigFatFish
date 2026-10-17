# -*- coding: utf-8 -*-
"""个人助理的界面：自己的一扇窗（复用简报窗口的壳）——「简报」页 + 「灵感」页，底部「在 Obsidian 打开 AI-Base」。

窗口顶部那行写明这次是谁在处理、怎么处理（模型、思考强度、token、秒数、工具轮数、读了哪些文件），
忙碌时写明正在让哪个模型读；灵感页的状态行写明写进了哪个文件、推没推上去。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import personal_briefing as pb
from .i18n import t
from .settings_widgets import TiltButton
from .work_briefing_ui import WorkBriefingWindow, save_theme_preference, theme_preference
from .work_notes_ui import INPUT_HEIGHT, _Input

ALERT_ID = "personal-briefing"
MAX_FILES_SHOWN = 8


def _when(value: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%m-%d %H:%M}"
    except ValueError:
        return "?"


def meta_line(briefing: pb.PersonalBriefing) -> str:
    """窗口顶部的「谁在处理、怎么处理」：模型 / 强度 / token / 秒 / 轮数 / 文件数，第二行怎么连的，第三行读过的文件。"""
    lines = [t("personal.meta", when=_when(briefing.generated_at), model=briefing.model or "?",
               effort=briefing.effort or "?", tokens_in=f"{briefing.tokens_in:,}", tokens_out=f"{briefing.tokens_out:,}",
               seconds=f"{briefing.seconds:.0f}", rounds=briefing.turns, n=len(briefing.files_read)),
             t("personal.meta.how")]
    if briefing.files_read:
        shown = briefing.files_read[:MAX_FILES_SHOWN]
        more = f" +{len(briefing.files_read) - len(shown)}" if len(briefing.files_read) > len(shown) else ""
        lines.append(t("personal.meta.files", files=" · ".join(shown) + more))
    if briefing.pull_note:
        lines.append(t("personal.meta.pull_failed", error=" ".join(briefing.pull_note.split())[-120:]))
    return "\n".join(lines)


class InspirationPanel(QWidget):
    """「灵感」页：一个输入框、一个「记下」、一行提示、一行状态。``add_requested(text)``。"""

    add_requested = Signal(str)

    def __init__(self, colors: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personalInspiration")
        self._colors = colors
        self.input = _Input(self)
        self.input.setObjectName("notesInput")      # 复用笔记页的样式表（简报窗口按 objectName 上色）
        self.input.setPlaceholderText(t("personal.inspiration.placeholder"))
        self.input.setFixedHeight(INPUT_HEIGHT)
        self.input.setAccessibleName(t("personal.tab.inspiration"))
        self.input.submitted.connect(self._submit)
        self.save_btn = TiltButton(t("personal.button.save"), self)
        self.save_btn.setFixedHeight(INPUT_HEIGHT)
        self.save_btn.clicked.connect(self._submit)
        QShortcut(QKeySequence("Ctrl+Return"), self.input, activated=self._submit)
        self.hint_label = QLabel(t("personal.inspiration.hint"), self)
        self.hint_label.setObjectName("notesHint")
        self.hint_label.setWordWrap(True)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("notesStatus")
        self.status_label.setWordWrap(True)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.input, 1)
        top.addWidget(self.save_btn, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def show_status(self, text: str) -> None:
        self.status_label.setText(text)

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors

    def _submit(self) -> None:
        text = self.input.toPlainText()
        if not text.strip():
            return
        self.input.clear()
        self.add_requested.emit(text)


def sync_status_text(service) -> str:
    state = service.sync_state
    if state == "pushing":
        return t("personal.inspiration.saved", file=os.path.basename(pb.pv.INSPIRATION_FILE))
    if state == "pushed":
        return t("personal.inspiration.pushed", when=service.pushed_at)
    if state == "failed":
        return t("personal.inspiration.push_failed", error=" ".join(service.sync_error.split())[-160:])
    return ""


class PersonalController(QObject):
    """把服务的结果摆到宿主上；岛上的按钮状态也从这里报（``state_changed(str)``）。"""

    state_changed = Signal(str)

    def __init__(self, host, service, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self.window: WorkBriefingWindow | None = None
        self.panel: InspirationPanel | None = None
        self._unread = False
        service.started.connect(self._on_started)
        service.finished.connect(self._on_finished)
        service.changed.connect(self._refresh_panel)
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

    def open_window(self, tab: str = "") -> None:
        if self.window is None:
            config = self.service._config
            self.window = WorkBriefingWindow(
                title=t("personal.app"), regenerate_label=t("personal.button.regenerate"), empty_text=t("personal.empty"),
                busy_text=t("personal.busy", model="?", effort="?"), page_label=t("personal.tab.briefing"),
                theme=theme_preference(config))
            self.window.regenerate_btn.setAccessibleDescription(t("personal.button.regenerate_hint"))
            self.window.regenerate_requested.connect(self.generate_now)
            self.window.theme_changed.connect(lambda theme: save_theme_preference(config, theme))
            self.obsidian_btn = self.window.add_action_button(t("personal.button.obsidian"))
            self.obsidian_btn.clicked.connect(self.open_obsidian)
            self.panel = InspirationPanel(self.window.colors, self.window)
            self.panel.add_requested.connect(self.service.add_inspiration)
            self.window.add_tab(t("personal.tab.inspiration"), self.panel)
        self._refresh_window()
        self._refresh_panel()
        if tab:
            self.window.select_tab(tab)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._set_unread(False)

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

    # ---------------------------------------------------------- 服务回调
    def _refresh_window(self) -> None:
        if self.window is None:
            return
        latest = self.service.latest()
        self.window.show_briefing(latest, busy=self.service.busy, error=self.service.last_error(),
                                  meta=meta_line(latest) if latest is not None else None,
                                  busy_text=t("personal.busy", model=self.service.busy_model or "?",
                                              effort=self.service.busy_effort or "?"))

    def _refresh_panel(self) -> None:
        if self.panel is not None:
            self.panel.show_status(sync_status_text(self.service))

    def _on_started(self, _manual: bool) -> None:
        self._refresh_window()

    def _on_finished(self, briefing, _manual: bool) -> None:
        self._refresh_window()
        if not briefing.ok:
            self._host.show_bubble(t("personal.bubble.failed", error=briefing.error), 8000)
            return
        if self.window is not None and self.window.isVisible():
            return
        self._set_unread(True)
        self._host.show_alert(
            briefing.summary, subtitle=t("personal.alert.subtitle"), sticky=True,
            buttons=[(t("personal.alert.view"), self._on_view), (t("personal.alert.dismiss"), self._on_dismiss)],
            alert_id=ALERT_ID, priority=1, alert_type="personal_briefing",
        )

    def _on_synced(self, ok: bool, error: str) -> None:
        self._refresh_panel()
        if not ok and (self.window is None or not self.window.isVisible()):
            self._host.show_bubble(t("personal.inspiration.push_failed", error=" ".join(error.split())[-120:]), 8000)

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
