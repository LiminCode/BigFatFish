# -*- coding: utf-8 -*-
"""工作笔记摆在哪：简报窗口里的「笔记」标签页 + 到点的提醒气泡。

标签页：上面一个输入框（粘贴 Slack / Jira 链接或片段，Ctrl+Enter 记下），中间笔记列表，下面
选中那条的全文（摘要 + 原文）和几个按钮：在 Obsidian 打开、重新总结、稍后、完成。
提醒走宿主的 ``show_alert``（留到用户点为止），和简报 / Slack 关注同一套。笔记内容不送语音合成。
界面文字全部走 ``i18n.t``（中 / 英跟随 ``ui_language``；换语言后重开窗口生效）。
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget,
)

from . import work_notes as wn
from .i18n import t
from .settings_widgets import TiltButton

ALERT_PREFIX = "work-note:"
#: 输入框与「记下」按钮一样高
INPUT_HEIGHT = 72
# 样式由简报窗口的 Metro 样式表统一给（按 objectName 选中这里的控件）；面板自己只管颜色相关的调色板。


def _when(value: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%m-%d %H:%M}"
    except ValueError:
        return ""


def row_label(note: wn.Note, busy: bool) -> str:
    """列表里一行：状态记号 + 标题 + 提醒时间。"""
    mark = "✓ " if note.status == wn.STATUS_DONE else ("… " if busy else ("● " if note.remind_at else "○ "))
    tail = ""
    if note.remind_at and note.status != wn.STATUS_DONE:
        tail = " · " + t("notes.row.remind", when=_when(note.remind_at))
    return f"{mark}{note.title}{tail}"


def detail_markdown(note: wn.Note, busy: bool) -> str:
    """右下那块的全文（Markdown）：摘要在前，原文在后，原文逐字。"""
    parts = [f"### {note.title}"]
    meta = [t("notes.detail.created", when=_when(note.created) or note.created), note.kind]
    if note.status == wn.STATUS_DONE:
        meta.append(t("notes.detail.done"))
    elif note.remind_at:
        meta.append(t("notes.detail.remind", when=_when(note.remind_at)) + (f"（{note.reason}）" if note.reason else ""))
    if note.tags:
        meta.append(" ".join(f"`{tag}`" for tag in note.tags))
    parts.append(" · ".join(meta))
    if note.model:
        parts.append(t("notes.detail.usage", model=note.model, tokens_in=f"{note.tokens_in:,}",
                       tokens_out=f"{note.tokens_out:,}", cost=f"{note.cost_usd:.3f}", seconds=f"{note.seconds:.0f}"))
    if busy:
        parts.append(f"*{t('notes.detail.busy')}*")
    elif note.summary:
        parts.append(f"**{note.summary}**")
        if note.details:
            parts.append(note.details)
    else:
        parts.append(f"*{t('notes.detail.no_summary')}*")
    parts.append("---")
    parts.append(f"**{t('notes.detail.original')}**")
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
        self._notes: dict[str, wn.Note] = {}
        self._busy: set[str] = set()

        self.input = _Input(self)
        self.input.setObjectName("notesInput")
        self.input.setPlaceholderText(t("notes.input.placeholder"))
        self.input.setFixedHeight(INPUT_HEIGHT)
        self.input.setAccessibleName(t("notes.tab"))
        self.input.submitted.connect(self._submit)
        self.add_btn = TiltButton(t("notes.button.add"), self)
        self.add_btn.setFixedHeight(INPUT_HEIGHT)   # 和输入框一样高（用户 2026-10-15：之前只有一行高、贴在底边）
        self.add_btn.setAccessibleDescription(t("notes.button.add_hint"))
        self.add_btn.clicked.connect(self._submit)
        QShortcut(QKeySequence("Ctrl+Return"), self.input, activated=self._submit)
        self.hint_label = QLabel(t("notes.hint.empty"), self)
        self.hint_label.setObjectName("notesHint")
        self.hint_label.setWordWrap(True)

        self.list = QListWidget(self)
        self.list.setObjectName("notesList")
        self.list.setAccessibleName(t("notes.tab"))
        self.list.currentItemChanged.connect(lambda *_: self._show_current())
        self.detail = QTextBrowser(self)
        self.detail.setObjectName("notesDetail")
        self.detail.setOpenExternalLinks(True)
        palette = self.detail.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))
        self.detail.setPalette(palette)
        self.detail.setAccessibleName(t("notes.detail.original"))

        self.obsidian_btn = TiltButton(t("notes.button.obsidian"), self)
        self.obsidian_btn.clicked.connect(lambda: self._emit_current(self.obsidian_requested))
        self.resummarize_btn = TiltButton(t("notes.button.resummarize"), self)
        self.resummarize_btn.clicked.connect(lambda: self._emit_current(self.resummarize_requested))
        self.snooze_btn = TiltButton(t("notes.button.snooze"), self)
        self.snooze_menu = QMenu(self.snooze_btn)
        for key, minutes in wn.SNOOZE_CHOICES:
            self.snooze_menu.addAction(t(key), lambda minutes=minutes: self._snooze(minutes))
        self.snooze_btn.setMenu(self.snooze_menu)
        self.done_btn = TiltButton(t("notes.button.done"), self)
        self.done_btn.clicked.connect(lambda: self._emit_current(self.done_requested))
        self.folder_btn = TiltButton(t("notes.button.folder"), self)
        self.folder_btn.clicked.connect(self.folder_requested)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("notesStatus")
        self.status_label.setWordWrap(True)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.input, 1)
        top.addWidget(self.add_btn, 0)
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
            status = t("notes.status.no_repo", path=repo_dir) + (f" · {error}" if error else "")
        self.status_label.setText(status)

    def apply_theme(self, colors: dict) -> None:
        """简报窗口换了白天 / 黑夜：只需换正文里链接的颜色，其余由窗口的样式表接管。"""
        self._colors = colors
        palette = self.detail.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))
        self.detail.setPalette(palette)
        self._show_current()

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
        busy = name in self._busy
        has = note is not None
        open_note = has and note.status != wn.STATUS_DONE
        self.obsidian_btn.setEnabled(has)
        self.snooze_btn.setEnabled(open_note)
        self.done_btn.setEnabled(open_note)
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
                from .work_briefing_ui import briefing_tokens, resolve_dark, theme_preference

                self._colors = briefing_tokens(resolve_dark(theme_preference(self.service._config)))
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
            self._host.show_bubble(t("notes.bubble.not_saved", reason=self.service.last_error() or t("notes.bubble.empty")), 5000)
            return
        self._host.show_bubble(t("notes.bubble.saved"), 3200)

    def open_in_obsidian(self, name: str) -> None:
        if not self.service.open_in_obsidian(name):
            self._host.show_bubble(t("notes.bubble.obsidian_hint"), 8000)

    # ---------------------------------------------------------- 服务回调
    def _refresh(self) -> None:
        if self._panel is None:
            return
        settings = self.service.settings()
        self._panel.show_notes(self.service.notes(), self.service.busy_names, self.service.last_error(),
                               repo_ready=self.service.repo_ready(), repo_dir=settings["repo_dir"])

    def _on_summarized(self, name: str, ok: bool, error: str) -> None:
        if not ok:
            self._host.show_bubble(t("notes.bubble.summary_failed", reason=error), 7000)

    def _on_reminder(self, note: wn.Note) -> None:
        alert_id = ALERT_PREFIX + note.name
        self._host.show_alert(
            note.summary or note.title, subtitle=t("notes.alert.subtitle", title=note.title), sticky=True,
            buttons=[(t("notes.alert.view"), lambda: self._view(alert_id, note.name)),
                     (t("notes.alert.snooze"), lambda: self._snooze(alert_id, note.name)),
                     (t("notes.alert.done"), lambda: self._done(alert_id, note.name))],
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
