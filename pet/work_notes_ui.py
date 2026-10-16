# -*- coding: utf-8 -*-
"""工作笔记摆在哪：简报窗口里的「笔记」标签页 + 到点的提醒气泡。

标签页：上面一个输入框（粘贴 Slack / Jira 链接或片段，Ctrl+Enter 记下），中间笔记列表，下面
选中那条的全文（摘要 + 原文）和几个按钮：在 Obsidian 打开、重新总结、稍后、完成。
提醒走宿主的 ``show_alert``（留到用户点为止），和简报 / Slack 关注同一套。笔记内容不送语音合成。
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

from . import work_notes as wn

ALERT_PREFIX = "work-note:"
_HINT_EMPTY = "还没有笔记。粘贴一个 Slack / Jira 链接或一段话，Ctrl+Enter 记下；WSL 里的 Claude Code 会去读、总结、定提醒。"
_PLACEHOLDER = "粘贴 Slack / Jira 链接，或一段要记的话……  Ctrl+Enter 记下"
_QSS = """
QPlainTextEdit#notesInput, QListWidget#notesList, QTextBrowser#notesDetail {{
    background: {card}; color: {text}; border: 1px solid {border}; border-radius: 12px;
    padding: 8px 10px; font-size: 13px;
}}
QListWidget#notesList::item {{ padding: 6px 4px; }}
QListWidget#notesList::item:selected {{ background: {hover}; color: {title}; border-radius: 6px; }}
QLabel#notesHint, QLabel#notesStatus {{ color: {muted}; font-size: 12px; }}
"""


def _when(value: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%m-%d %H:%M}"
    except ValueError:
        return ""


def row_label(note: wn.Note, busy: bool) -> str:
    """列表里一行：状态记号 + 标题 + 提醒时间。"""
    mark = "✓ " if note.status == wn.STATUS_DONE else ("… " if busy else ("● " if note.remind_at else "○ "))
    tail = f" · 提醒 {_when(note.remind_at)}" if note.remind_at and note.status != wn.STATUS_DONE else ""
    return f"{mark}{note.title}{tail}"


def detail_markdown(note: wn.Note, busy: bool) -> str:
    """右下那块的全文（Markdown）：摘要在前，原文在后，原文逐字。"""
    parts = [f"### {note.title}"]
    meta = [f"记于 {_when(note.created) or note.created}", note.kind]
    if note.status == wn.STATUS_DONE:
        meta.append("已完成")
    elif note.remind_at:
        meta.append(f"提醒 {_when(note.remind_at)}" + (f"（{note.reason}）" if note.reason else ""))
    if note.tags:
        meta.append(" ".join(f"`{tag}`" for tag in note.tags))
    parts.append(" · ".join(meta))
    if busy:
        parts.append("*正在让 WSL 里的 Claude Code 读这条，大约一分钟…*")
    elif note.summary:
        parts.append(f"**{note.summary}**")
        if note.details:
            parts.append(note.details)
    else:
        parts.append("*还没有总结。*")
    parts.append("---")
    parts.append("**原文**")
    parts.append(note.original)
    return "\n\n".join(parts)


class _Input(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class WorkNotesPanel(QWidget):
    add_requested = Signal(str)
    resummarize_requested = Signal(str)
    done_requested = Signal(str)
    snooze_requested = Signal(str, int)
    obsidian_requested = Signal(str)
    folder_requested = Signal()

    def __init__(self, colors: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workNotes")
        self._colors = colors
        self.setStyleSheet(_QSS.format(**colors))
        self._notes: dict[str, wn.Note] = {}

        self.input = _Input(self)
        self.input.setObjectName("notesInput")
        self.input.setPlaceholderText(_PLACEHOLDER)
        self.input.setFixedHeight(72)
        self.input.setAccessibleName("新笔记")
        self.input.submitted.connect(self._submit)
        self.add_btn = QPushButton("记下", self)
        self.add_btn.setAccessibleDescription("保存这条笔记，并让 WSL 里的 Claude Code 去读、总结、定提醒")
        self.add_btn.clicked.connect(self._submit)
        QShortcut(QKeySequence("Ctrl+Return"), self.input, activated=self._submit)
        self.hint_label = QLabel(_HINT_EMPTY, self)
        self.hint_label.setObjectName("notesHint")
        self.hint_label.setWordWrap(True)

        self.list = QListWidget(self)
        self.list.setObjectName("notesList")
        self.list.setAccessibleName("笔记列表")
        self.list.currentItemChanged.connect(lambda *_: self._show_current())
        self.detail = QTextBrowser(self)
        self.detail.setObjectName("notesDetail")
        self.detail.setOpenExternalLinks(True)
        palette = self.detail.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))
        self.detail.setPalette(palette)
        self.detail.setAccessibleName("笔记全文")

        self.obsidian_btn = QPushButton("在 Obsidian 打开", self)
        self.obsidian_btn.clicked.connect(lambda: self._emit_current(self.obsidian_requested))
        self.resummarize_btn = QPushButton("重新总结", self)
        self.resummarize_btn.clicked.connect(lambda: self._emit_current(self.resummarize_requested))
        self.snooze_btn = QPushButton("稍后 ▾", self)
        self.snooze_menu = QMenu(self.snooze_btn)
        for label, minutes in wn.SNOOZE_CHOICES:
            self.snooze_menu.addAction(label, lambda minutes=minutes: self._snooze(minutes))
        self.snooze_btn.setMenu(self.snooze_menu)
        self.done_btn = QPushButton("完成", self)
        self.done_btn.clicked.connect(lambda: self._emit_current(self.done_requested))
        self.folder_btn = QPushButton("打开文件夹", self)
        self.folder_btn.clicked.connect(self.folder_requested)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("notesStatus")
        self.status_label.setWordWrap(True)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.input, 1)
        top.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignBottom)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.status_label, 1)
        for button in (self.obsidian_btn, self.resummarize_btn, self.snooze_btn, self.done_btn, self.folder_btn):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.list, 2)
        layout.addWidget(self.detail, 3)
        layout.addLayout(buttons)
        self._show_current()

    # ---------------------------------------------------------- 数据进来
    def show_notes(self, notes: list[wn.Note], busy: frozenset[str] | set[str] = frozenset(),
                   error: str = "", repo_ready: bool = True, repo_dir: str = "") -> None:
        current = self.current_name()
        self._notes = {note.name: note for note in notes}
        self._busy = set(busy)
        self.list.blockSignals(True)
        self.list.clear()
        for note in notes:
            item = QListWidgetItem(row_label(note, note.name in self._busy))
            item.setData(Qt.ItemDataRole.UserRole, note.name)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if notes:
            self.select(current if current in self._notes else notes[0].name)
        else:
            self._show_current()
        self.hint_label.setVisible(not notes)
        status = error
        if not repo_ready:
            status = f"没找到仓库副本 {repo_dir}（在 WSL 里 git clone 到这里，笔记才推得上去）" + (f" · {error}" if error else "")
        self.status_label.setText(status)

    def select(self, name: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self.list.setCurrentItem(item)
                return
        self._show_current()

    def current_name(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    # ---------------------------------------------------------- 内部
    def _submit(self) -> None:
        text = self.input.toPlainText()
        if not text.strip():
            return
        self.input.clear()
        self.add_requested.emit(text)

    def _emit_current(self, signal) -> None:
        name = self.current_name()
        if name:
            signal.emit(name)

    def _snooze(self, minutes: int) -> None:
        name = self.current_name()
        if name:
            self.snooze_requested.emit(name, minutes)

    def _show_current(self) -> None:
        name = self.current_name()
        note = self._notes.get(name)
        busy = name in getattr(self, "_busy", set())
        has = note is not None
        for button in (self.obsidian_btn, self.snooze_btn, self.done_btn):
            button.setEnabled(has and (note.status != wn.STATUS_DONE if button is not self.obsidian_btn else True))
        self.resummarize_btn.setEnabled(has and not busy)
        if note is None:
            self.detail.setPlainText("")
            return
        self.detail.setMarkdown(detail_markdown(note, busy))


class WorkNotesController(QObject):
    """把服务接到标签页和提醒气泡上。``open_window``：怎么把简报窗口开到「笔记」那一页。"""

    def __init__(self, host, service, *, open_window: Callable[[], None] | None = None,
                 colors: dict | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self._open_window = open_window or (lambda: None)
        self._colors = colors
        self._panel: WorkNotesPanel | None = None
        service.changed.connect(self._refresh)
        service.summarized.connect(self._on_summarized)
        service.reminder_due.connect(self._on_reminder)

    def panel(self) -> WorkNotesPanel:
        if self._panel is None:
            if self._colors is None:
                from .settings_widgets import _system_dark
                from .work_briefing_ui import _PALETTES

                self._colors = _PALETTES[bool(_system_dark())]
            panel = WorkNotesPanel(self._colors)
            panel.add_requested.connect(self.add)
            panel.resummarize_requested.connect(self.service.resummarize)
            panel.done_requested.connect(self.service.mark_done)
            panel.snooze_requested.connect(self.service.snooze)
            panel.obsidian_requested.connect(self.open_in_obsidian)
            panel.folder_requested.connect(self.service.open_folder)
            self._panel = panel
            self._refresh()
        return self._panel

    def open_notes(self, name: str = "") -> None:
        self._open_window()
        if name and self._panel is not None:
            self._panel.select(name)

    # ---------------------------------------------------------- 动作
    def add(self, text: str) -> None:
        note = self.service.add(text)
        if note is None:
            self._host.show_bubble("这条没记下来：" + (self.service.last_error() or "内容是空的"), 5000)
            return
        self._host.show_bubble("记下了，这就让 WSL 里的 Claude Code 去读一遍～", 3200)

    def open_in_obsidian(self, name: str) -> None:
        if not self.service.open_in_obsidian(name):
            self._host.show_bubble("Obsidian 还没把这个仓库登记成库：先在 Obsidian 里「Open folder as vault」选它一次，之后就能直接跳过去", 8000)

    # ---------------------------------------------------------- 服务回调
    def _refresh(self) -> None:
        if self._panel is None:
            return
        settings = self.service.settings()
        self._panel.show_notes(self.service.notes(), self.service.busy_names, self.service.last_error(),
                               repo_ready=self.service.repo_ready(), repo_dir=settings["repo_dir"])

    def _on_summarized(self, name: str, ok: bool, error: str) -> None:
        if not ok:
            self._host.show_bubble(f"这条笔记没总结出来：{error}", 7000)

    def _on_reminder(self, note: wn.Note) -> None:
        alert_id = ALERT_PREFIX + note.name
        self._host.show_alert(
            note.summary or note.title, subtitle=f"笔记提醒 · {note.title}", sticky=True,
            buttons=[("查看", lambda: self._view(alert_id, note.name)),
                     ("稍后 1 小时", lambda: self._snooze(alert_id, note.name)),
                     ("完成", lambda: self._done(alert_id, note.name))],
            alert_id=alert_id, priority=1, alert_type="work_note",
        )

    def _view(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        self.open_notes(name)

    def _snooze(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        self.service.snooze(name, 60)

    def _done(self, alert_id: str, name: str) -> None:
        self._host.resolve_alert(alert_id)
        self.service.mark_done(name)
