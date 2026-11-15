# -*- coding: utf-8 -*-
"""设置页「常规 · 配置备份」：把整份设置备份到自己的私有 GitHub 仓库，坏了一键拉回（2026-11-14）。

备份 / 恢复的逻辑在 ``config_backup.py``（不依赖 Qt），这里只是表单和两个按钮：

- **每天自动备份**（``config_backup.auto``，默认关）：主进程里的定时器做，见
  ``config_backup_sync.py``；
- **备份仓库**（``config_backup.repo``）：留空 = 用知识库那个仓库（占位提示里写着）；
- **仓库里的位置**（``config_backup.path``）：默认 ``.big-fat-fish/config.json``；
- **立即备份**：先按「保存」把表单写盘，再上传盘上那份——传上去的就是你眼前这些设置；
- **从 GitHub 恢复…**：确认后拉回备份写盘。写完设置窗口**不保存直接关掉**：表单里还是
  恢复前的值，照常保存会把刚恢复的配置冲回去。肥鱼主进程盯着 config.json，自己会应用。

网络在 daemon 线程里做，结果经 ``_Bridge`` 的信号排队回 GUI 线程。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QWidget

from . import config_backup as cb
from .i18n import t
from .settings_widgets import SettingRow, SettingsSection, ToggleSwitch, _line_edit

log = logging.getLogger(__name__)


def _spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-settings-config-backup").start()


class _Bridge(QObject):
    """worker 线程 → GUI 线程：``done(操作, 成功?, 说明)``。"""

    done = Signal(str, bool, str)


def _kb_repo(config) -> str:
    try:
        return str(config.chat_settings().knowledge_base_repo or "")
    except Exception:  # noqa: BLE001 - 不带聊天的变体 / 聊天配置读坏了
        return ""


def _form_settings(dialog) -> dict:
    return cb.normalize({
        "auto": dialog.config_backup_auto.isChecked(),
        "repo": dialog.config_backup_repo.text(),
        "path": dialog.config_backup_path.text(),
    })


def _token(dialog) -> str:
    """钥匙串里的 Token；AI 页上刚填、还没保存的也算（与知识库「立即同步」同口径）。"""
    page = getattr(dialog, "ai_page", None)
    typed = getattr(page, "github_token", None)
    text = typed.text().strip() if typed is not None else ""
    return text or cb.stored_token()


def config_backup_section(dialog, parent=None) -> SettingsSection:
    """建出这一节（控件挂在 ``dialog.config_backup_*`` 上）。"""
    settings = cb.normalize(dialog.config.get("config_backup"))
    dialog.config_backup_auto = ToggleSwitch(parent)
    dialog.config_backup_auto.setChecked(settings["auto"])
    dialog.config_backup_repo = _line_edit(settings["repo"], width=220)
    dialog.config_backup_repo.setPlaceholderText(cb._parse_repo(_kb_repo(dialog.config)) or "owner/repo")
    dialog.config_backup_path = _line_edit("" if settings["path"] == cb.DEFAULT_PATH else settings["path"], width=220)
    dialog.config_backup_path.setPlaceholderText(cb.DEFAULT_PATH)

    buttons = QWidget(parent)
    layout = QHBoxLayout(buttons)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    dialog.config_backup_now = QPushButton(t("settings.config_backup.backup_now"), buttons)
    dialog.config_backup_restore = QPushButton(t("settings.config_backup.restore"), buttons)
    for button in (dialog.config_backup_now, dialog.config_backup_restore):
        button.setAutoDefault(False)
        layout.addWidget(button)
    dialog.config_backup_now.clicked.connect(lambda: run_backup(dialog))
    dialog.config_backup_restore.clicked.connect(lambda: run_restore(dialog))

    actions = SettingRow("config_backup_actions", t("settings.config_backup.actions_title"),
                         cb.describe(dialog.config.dir), buttons)
    dialog.config_backup_status = actions.hint_label
    bridge = _Bridge(dialog)
    bridge.done.connect(lambda kind, ok, message: _on_done(dialog, kind, ok, message))
    dialog._config_backup_bridge = bridge
    return SettingsSection(t("settings.config_backup.section"), [
        SettingRow("config_backup_auto", t("settings.config_backup.auto_title"),
                   t("settings.config_backup.auto_hint"), dialog.config_backup_auto),
        SettingRow("config_backup_repo", t("settings.config_backup.repo_title"),
                   t("settings.config_backup.repo_hint"), dialog.config_backup_repo),
        SettingRow("config_backup_path", t("settings.config_backup.path_title"),
                   t("settings.config_backup.path_hint"), dialog.config_backup_path),
        actions,
    ], parent)


def save_config_backup(dialog) -> None:
    """保存时写回 ``config_backup``（随对话框统一落盘）。"""
    if getattr(dialog, "config_backup_auto", None) is None:
        return
    dialog.config.set("config_backup", _form_settings(dialog))


def _target(dialog) -> tuple[str, str]:
    settings = _form_settings(dialog)
    return cb.target_repo(settings, _kb_repo(dialog.config)), settings["path"]


def _busy(dialog, text: str) -> None:
    dialog.config_backup_now.setEnabled(False)
    dialog.config_backup_restore.setEnabled(False)
    dialog.config_backup_status.setText(text)


def _start(dialog, kind: str, work: Callable[[], str]) -> None:
    bridge = dialog._config_backup_bridge

    def run() -> None:
        try:
            result = (True, work())
        except Exception as exc:  # noqa: BLE001 - 无论抛什么都要把按钮恢复回来
            result = (False, t("settings.config_backup.failed", error=exc))
        try:
            bridge.done.emit(kind, *result)
        except RuntimeError:
            pass   # 窗口已在途中关闭销毁

    _spawn(run)


def run_backup(dialog) -> bool:
    """「立即备份」：先保存表单，再在后台上传。返回是否发起了。"""
    repo, path = _target(dialog)
    if not repo:
        dialog.config_backup_status.setText(t("config_backup.no_repo"))
        return False
    if not dialog._write_config():
        return False
    token, config = _token(dialog), dialog.config
    _busy(dialog, t("settings.config_backup.backing_up", repo=repo))

    def work() -> str:
        cb.backup(config.path, repo, path, token)
        return cb.describe(config.dir)

    _start(dialog, "backup", work)
    return True


def run_restore(dialog) -> bool:
    """「从 GitHub 恢复…」：确认后在后台拉回写盘。返回是否发起了。"""
    repo, path = _target(dialog)
    if not repo:
        dialog.config_backup_status.setText(t("config_backup.no_repo"))
        return False
    answer = QMessageBox.question(
        dialog, t("settings.config_backup.confirm_title"),
        t("settings.config_backup.confirm_text", repo=repo, path=path),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    token, config_path = _token(dialog), dialog.config.path
    _busy(dialog, t("settings.config_backup.restoring", repo=repo))

    def work() -> str:
        cb.restore(config_path, repo, path, token)
        return t("settings.config_backup.restored")

    _start(dialog, "restore", work)
    return True


def _on_done(dialog, kind: str, ok: bool, message: str) -> None:
    dialog.config_backup_now.setEnabled(True)
    dialog.config_backup_restore.setEnabled(True)
    dialog.config_backup_status.setText(message)
    if kind != "restore" or not ok:
        return
    log.info("设置页：已从 GitHub 恢复配置")
    # 表单里还是恢复前的值：关窗时不许再保存，否则刚恢复的配置被冲回去
    dialog._saved_via_button = True
    try:
        dialog.config.reload()
        dialog.saved.emit()          # 进程内对话框：宿主走应用链；独立进程由主进程的 watcher 接
    except Exception:  # noqa: BLE001
        log.exception("恢复配置后重载失败")
    QMessageBox.information(dialog, t("settings.config_backup.confirm_title"), message)
    dialog.close()
