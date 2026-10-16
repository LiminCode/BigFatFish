# -*- coding: utf-8 -*-
"""设置页的「保存」：写入配置但不关窗口。

原来只有「保存并退出」（关窗口也会保存），想让改动立刻生效只能关掉设置再重开。
这里加一个不关窗的保存：侧栏按钮 + Ctrl+S。写盘走对话框既有的 ``_write_config``
（保存前先重读磁盘，吸收别处的改动）与 ``_apply_autostart``。

改动怎么到达运行中的肥鱼：

- 独立设置进程（默认）：主进程盯着 config.json，约 0.3 秒内自己应用；
- 进程内对话框（关掉进程隔离时）：对话框发 ``saved`` 信号，宿主接它走与关窗相同的
  应用链（``PetInstance._modern_settings_saved``）。

从 ``modern_settings_dialog`` 拆出来放这里，是因为那个文件有行数预算。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton

from .context_menus.icons import vector_widget_icon
from .i18n import t

#: 按钮文字的文案键（用时 t()）
SAVE_TEXT = "settings.save.save"
SAVED_TEXT = "settings.save.saved"
_FEEDBACK_MS = 1500


def install_save_button(dialog, sidebar_pane, sidebar_layout) -> None:
    """在侧栏放「保存」按钮并绑 Ctrl+S；对话框上挂 ``save_button`` / ``_save_feedback_timer``。"""
    button = QPushButton(t(SAVE_TEXT), sidebar_pane)
    button.setObjectName("saveOnly")
    button.setIcon(vector_widget_icon(button, "check", 16))
    button.setToolTip(t("settings.save.save_apply_now_without_closing"))
    button.setAutoDefault(False)         # 在输入框里按回车不该触发保存
    button.setDefault(False)
    button.clicked.connect(dialog._save_only)
    sidebar_layout.addWidget(button)
    dialog.save_button = button

    timer = QTimer(dialog)
    timer.setSingleShot(True)
    timer.setInterval(_FEEDBACK_MS)
    timer.timeout.connect(lambda: button.setText(t(SAVE_TEXT)))
    dialog._save_feedback_timer = timer

    shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), dialog)
    shortcut.activated.connect(dialog._save_only)
    dialog._save_shortcut = shortcut


def save_without_exit(dialog) -> bool:
    """写入配置、应用开机自启，发 ``saved``；按钮短暂显示「已保存」。返回是否存上了。"""
    if not dialog._write_config():
        return False                     # 失败原因由 _write_config 自己提示
    dialog._apply_autostart()
    dialog.saved.emit()
    dialog.save_button.setText(t(SAVED_TEXT))
    dialog._save_feedback_timer.start()
    return True
