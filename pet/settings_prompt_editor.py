# -*- coding: utf-8 -*-
"""设置页里「可见可改的提示词」：一个预填内置模板的多行框 + 「恢复内置」按钮。

工作简报 / 工作笔记 / Slack 关注三处共用（用户 2026-10-24：发给 AI 的提示词要明文、能改）。
口径和语音报时的内置台词库一样：没改过存空串（= 原样，跟着以后的版本更新），改过才整份存；
「恢复内置」把框里的字换回内置版（没改过时置灰）。模板里的占位符由各功能自己渲染。
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .i18n import t


class PromptEditor(QWidget):
    """``edit``（多行框）+ ``restore``（恢复内置）。``value()`` 是要存进配置的值（和内置一样 → 空串）。"""

    def __init__(self, parent: QWidget | None, *, default: str, stored: str = "", accessible_name: str = "",
                 min_height: int = 160, max_height: int = 320) -> None:
        super().__init__(parent)
        self._default = str(default or "").strip()
        self.edit = QPlainTextEdit(self)
        self.edit.setMinimumSize(320, min_height)
        self.edit.setMaximumHeight(max_height)
        self.edit.setPlainText(str(stored or "").strip() or self._default)
        if accessible_name:
            self.edit.setAccessibleName(accessible_name)
        self.restore = QPushButton(t("settings.prompt.restore_builtin"), self)
        self.restore.setToolTip(t("settings.prompt.restore_builtin_hint"))
        self.restore.setAccessibleDescription(t("settings.prompt.restore_builtin_hint"))
        self.restore.clicked.connect(lambda: self.edit.setPlainText(self._default))
        self.edit.textChanged.connect(self._sync_restore)
        self._sync_restore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.edit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.restore)
        layout.addLayout(buttons)

    def _sync_restore(self) -> None:
        self.restore.setEnabled(self.edit.toPlainText().strip() != self._default)

    def value(self) -> str:
        """保存值：和内置一字不差就存空串，改过才整份存。"""
        text = self.edit.toPlainText().strip()
        return "" if text == self._default else text
