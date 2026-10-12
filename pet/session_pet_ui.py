# -*- coding: utf-8 -*-
"""会话小鱼的交互面：详情卡、专属右键菜单、跳转（Qt 层）。

会话小鱼是一个 Claude Code 会话的状态指示，不是另一只桌宠——主肥鱼那棵菜单
（动作点播、AI 对话、角色切换……）对它没有意义。这里给它两样自己的东西：

- **单击 → 详情卡**：标题、状态与持续时间、最近的问题、在哪打开的（VS Code 插件 /
  终端 / WSL）、项目路径与分支，外加「跳到对话 / 打开文件夹 / 复制恢复命令」；
- **右键 → 精简菜单**：同样的动作，加上「让这只离场」和会话小鱼的开关 / 上限。

详情要读 Claude Code 的会话记录与运行清单（见 ``claude_session_info``），WSL 通道
还要起一次 ``wsl.exe``，跳转要等窗口切换——都放后台线程，结果经信号回 GUI 线程。
最近的问题只在内存里过一下，不落盘。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from . import claude_hooks, claude_session_info, claude_session_jump, session_card_themes
from .claude_session_info import SessionDetail
from .ui_fonts import apply_family

log = logging.getLogger(__name__)

#: 详情卡相对系统默认字号 / 尺寸的放大倍数（再乘「气泡文字大小」设置）
CARD_BASE_SCALE = 1.25
_WAIT_TEXT = "在等你批准"


def elapsed_text(seconds: float) -> str:
    """持续时间的口语说法：刚刚 / 3 分钟 / 1 小时 5 分。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"


def status_line(detail: SessionDetail, since: float | None, now: float | None = None) -> str:
    """「工作中 · 已 3 分钟」；等批准时点名在等哪个工具。"""
    text = claude_hooks.PHASE_TEXT.get(detail.phase, "")
    if detail.phase == "waiting" and detail.tool:
        text = f"{_WAIT_TEXT}：{detail.tool}"
    if since:
        text = f"{text} · 已 {elapsed_text((now or time.time()) - since)}" if text else ""
    return text


def where_line(detail: SessionDetail) -> str:
    parts = [detail.entry_text] if detail.entry_text else []
    if detail.cwd:
        parts.append(detail.cwd)
    if detail.git_branch and detail.git_branch != "HEAD":
        parts.append(f"分支 {detail.git_branch}")
    return " · ".join(parts)


def _configured_theme_id(config) -> str:
    """配置里选的详情卡配色方案（``agent_link.session_card_theme``）。"""
    try:
        agent_cfg = config.get("agent_link", {}) or {}
    except (AttributeError, TypeError):
        agent_cfg = {}
    value = agent_cfg.get(session_card_themes.CONFIG_KEY) if isinstance(agent_cfg, dict) else None
    return session_card_themes.normalize_theme_id(value)


def _card_scale(config) -> float:
    try:
        percent = float(config.get("bubble_text_scale", 100) or 100)
    except (AttributeError, TypeError, ValueError):
        percent = 100.0
    return max(1.0, min(4.0, CARD_BASE_SCALE * percent / 100.0))


class SessionDetailCard(QFrame):
    """锚在会话小鱼头顶的详情卡；失去焦点即收起。"""

    jump_requested = Signal()
    folder_requested = Signal()
    copy_requested = Signal()

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("session-detail-card")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._scale = _card_scale(config)
        self._theme_id = ""
        self._theme = session_card_themes.card_theme(None)
        apply_family(self)   # 与桌宠气泡同一种字体（等线）
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * self._scale)
            self.setFont(font)
        self._anchor = None
        self._deactivate_check_pending = False
        self.key: tuple[str, str] | None = None
        self._build()
        self.apply_theme(_configured_theme_id(config))

    def apply_theme(self, theme_id) -> None:
        """换配色方案（``session_card_themes`` 里的 id）；与当前相同则什么都不做。

        颜色全部取自方案本身，不再从气泡样式推导——按钮底、按钮字、悬停态各有各的
        颜色，每个方案的对比度由测试逐项把关。"""
        theme_id = session_card_themes.normalize_theme_id(theme_id)
        if theme_id == self._theme_id:
            return
        self._theme_id, self._theme = theme_id, session_card_themes.CARD_THEMES[theme_id]
        t, px = self._theme, self._px
        self.setStyleSheet(f"""
            QLabel {{ background: transparent; color: {t["text"]}; border: none; }}
            QLabel#session-card-caption, QLabel#session-card-where,
            QLabel#session-card-result {{ color: {t["muted"]}; }}
            QPushButton {{
                background: {t["button"]}; color: {t["button_text"]};
                border: 1px solid {t["button_border"]}; border-radius: {px(8)}px;
                padding: {px(3)}px {px(8)}px;
            }}
            QPushButton:hover {{
                background: {t["hover"]}; color: {t["hover_text"]}; border-color: {t["hover"]};
            }}
            QPushButton:disabled {{ color: {t["disabled_text"]}; }}
        """)
        self.update()

    def _px(self, value: float) -> int:
        return int(round(value * self._scale))

    def _build(self) -> None:
        px = self._px
        width = px(360)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            width = min(width, max(240, screen.availableGeometry().width() - 16))
        self.setFixedWidth(width)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(16), px(14), px(16), px(14))
        layout.setSpacing(px(6))

        header = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("session-card-title")
        self.title_label.setWordWrap(True)
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        header.addWidget(self.title_label, 1)
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(px(24), px(24))
        self.close_btn.clicked.connect(self.close)
        header.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.status_label = QLabel("")
        self.status_label.setObjectName("session-card-status")
        layout.addWidget(self.status_label)

        self.prompt_caption = QLabel("最近的问题")
        self.prompt_caption.setObjectName("session-card-caption")
        layout.addWidget(self.prompt_caption)
        self.prompt_label = QLabel("")
        self.prompt_label.setObjectName("session-card-prompt")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.prompt_label)

        self.where_label = QLabel("")
        self.where_label.setObjectName("session-card-where")
        self.where_label.setWordWrap(True)
        layout.addWidget(self.where_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(px(6))
        self.jump_btn = QPushButton("跳到对话")
        self.folder_btn = QPushButton("打开文件夹")
        self.copy_btn = QPushButton("复制恢复命令")
        self.jump_btn.clicked.connect(self.jump_requested.emit)
        self.folder_btn.clicked.connect(self.folder_requested.emit)
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        for button in (self.jump_btn, self.folder_btn, self.copy_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.result_label = QLabel("")
        self.result_label.setObjectName("session-card-result")
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        layout.addWidget(self.result_label)


    # ------------------------------------------------------------ 内容
    def show_detail(self, detail: SessionDetail, since: float | None, *,
                    loading: bool = False) -> None:
        self.title_label.setText(claude_hooks.session_label(detail.agent, {
            "title": detail.title, "project": detail.project, "sessionId": detail.session_id}))
        self.status_label.setText(status_line(detail, since))
        if detail.last_prompt:
            prompt = detail.last_prompt
        elif loading:
            prompt = "读取中…"
        else:
            prompt = "（没读到）"
        self.prompt_label.setText(prompt)
        self.where_label.setText(where_line(detail))
        self.where_label.setVisible(bool(self.where_label.text()))
        self.folder_btn.setEnabled(bool(detail.cwd))
        self.adjustSize()
        self._reposition()

    def show_result(self, message: str) -> None:
        self.result_label.setText(message)
        self.result_label.setVisible(bool(message))
        self.adjustSize()
        self._reposition()

    # ------------------------------------------------------------ 定位 / 显示
    def popup(self, anchor) -> None:
        """在 ``anchor``（提供 ``visible_content_rect()`` 的锚点）旁弹出并取得焦点。"""
        self._anchor = anchor
        self.result_label.setVisible(False)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self.activateWindow()

    def _reposition(self) -> None:
        anchor = self._anchor
        if anchor is None:
            return
        rect = anchor.visible_content_rect()
        if rect.isEmpty():
            return
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width, height = self.width(), self.height()
        x = rect.center().x() - width // 2
        y = rect.top() - height - 8
        if y < available.top():
            y = rect.bottom() + 8                 # 头顶放不下：放到脚下
        x = max(available.left() + 4, min(x, available.right() - width - 4))
        y = max(available.top() + 4, min(y, available.bottom() - height - 4))
        self.move(x, y)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        inset = 3 * self._scale
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        radius = 14 * self._scale
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        shadow = QPainterPath(body)
        shadow.translate(0, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme["shadow"]))
        painter.drawPath(shadow)
        painter.setBrush(QColor(self._theme["background"]))
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.drawPath(body)
        painter.end()

    def event(self, event) -> bool:
        # 与快速对话气泡同款：首次激活时 Cocoa 会先发一次过渡性的失焦，下一轮再判
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            if not self._deactivate_check_pending:
                self._deactivate_check_pending = True
                QTimer.singleShot(0, self, self._close_if_still_inactive)
        return super().event(event)

    def _close_if_still_inactive(self) -> None:
        self._deactivate_check_pending = False
        if self.isVisible() and QApplication.activeWindow() is not self:
            self.close()


class SessionPetActions(QObject):
    """会话小鱼的动作集：详情卡、跳转、打开文件夹、复制、离场。

    ``shell`` 提供锚点与气泡，``controller``（``SessionPetController``）提供
    sprite ↔ 会话的对应关系。
    """

    _detail_ready = Signal(object, object)   # (key, SessionDetail)
    _jump_done = Signal(object, object)      # (key, JumpResult)
    _folder_ready = Signal(object, object)   # (key, SessionDetail)

    def __init__(self, shell, controller, *, anchor_factory, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._controller = controller
        self._anchor_factory = anchor_factory
        self._card: SessionDetailCard | None = None
        self._cache: dict[tuple[str, str], SessionDetail] = {}
        self._detail_ready.connect(self._on_detail_ready)
        self._jump_done.connect(self._on_jump_done)
        self._folder_ready.connect(self._on_folder_ready)
        #: 可替换的后端（测试注入；生产 = 真读文件 / 真切窗口）
        self.loader = claude_session_info.load
        self.jumper = claude_session_jump.jump
        self.opener = _open_path

    # ------------------------------------------------------------ 取数
    def detail_of(self, sprite) -> SessionDetail | None:
        """这只小鱼代表的会话（hook 送来的那部分 + 上次读到的详情）；不是会话小鱼 → None。"""
        key = self._controller.key_of(sprite)
        if key is None:
            return None
        return self._detail_for_key(key)

    def _detail_for_key(self, key: tuple[str, str]) -> SessionDetail | None:
        info = self._controller.describe(key)
        if info is None:
            return None
        detail = claude_session_info.from_session(key[0], info)
        cached = self._cache.get(key)
        if cached is not None:
            for name in ("last_prompt", "git_branch", "entrypoint", "version", "name", "pid",
                         "started_at", "alive", "distro", "extra"):
                setattr(detail, name, getattr(cached, name))
            detail.cwd = detail.cwd or cached.cwd
        return detail

    def _load_async(self, key: tuple[str, str], signal) -> bool:
        detail = self._detail_for_key(key)
        if detail is None:
            return False

        def work() -> None:
            try:
                loaded = self.loader(detail)
            except Exception:
                log.debug("读取会话详情失败", exc_info=True)
                loaded = detail
            if shiboken6.isValid(self):
                signal.emit(key, loaded)

        threading.Thread(target=work, name="session-detail", daemon=True).start()
        return True

    # ------------------------------------------------------------ 详情卡
    def show_card(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        detail = self._detail_for_key(key) if key else None
        if detail is None:
            return False
        card = self._ensure_card()
        card.key = key
        card.show_detail(detail, self._controller.since(key), loading=True)
        card.popup(self._anchor_factory(sprite))
        self._load_async(key, self._detail_ready)
        return True

    def _ensure_card(self) -> SessionDetailCard:
        if self._card is None or not shiboken6.isValid(self._card):
            card = SessionDetailCard(self._shell._config)
            card.jump_requested.connect(lambda: self._card_action(self.jump_key))
            card.folder_requested.connect(lambda: self._card_action(self.open_folder_key))
            card.copy_requested.connect(lambda: self._card_action(self.copy_resume_key))
            self._card = card
        # 卡片是复用的：每次要用之前对一下配置里选的方案，菜单里改了下次打开就是新的
        self._card.apply_theme(_configured_theme_id(self._shell._config))
        return self._card

    def _card_action(self, action) -> None:
        card = self._card
        if card is not None and card.key is not None:
            action(card.key)

    def _on_detail_ready(self, key, detail) -> None:
        self._cache[key] = detail
        card = self._card
        if (card is not None and shiboken6.isValid(card) and card.isVisible()
                and card.key == key):
            merged = self._detail_for_key(key) or detail
            card.show_detail(merged, self._controller.since(key))

    def close(self) -> None:
        card, self._card = self._card, None
        if card is not None and shiboken6.isValid(card):
            card.close()
            card.deleteLater()

    def forget(self, key: tuple[str, str]) -> None:
        """会话离场：丢掉它的详情缓存，卡片正开着它就收起。"""
        self._cache.pop(key, None)
        card = self._card
        if card is not None and shiboken6.isValid(card) and card.key == key:
            card.close()

    # ------------------------------------------------------------ 动作
    def jump(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return self.jump_key(key) if key else False

    def jump_key(self, key: tuple[str, str]) -> bool:
        detail = self._detail_for_key(key)
        if detail is None:
            return False
        self._say(key, "正在切过去…")

        def work() -> None:
            try:
                loaded = self.loader(detail)      # 要进程号 / 入口 / 是否还活着
                result = self.jumper(loaded, wsl_env=loaded.extra.get("env"))
            except Exception:
                log.exception("跳到会话失败")
                loaded, result = detail, claude_session_jump.JumpResult(False, "跳转出错了")
            if shiboken6.isValid(self):
                self._detail_ready.emit(key, loaded)
                self._jump_done.emit(key, result)

        threading.Thread(target=work, name="session-jump", daemon=True).start()
        return True

    def _on_jump_done(self, key, result) -> None:
        log.info("会话跳转 agent=%s session=%s ok=%s：%s", key[0], key[1][:8],
                 result.ok, result.message)
        self._say(key, result.message)

    def open_folder(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return self.open_folder_key(key) if key else False

    def open_folder_key(self, key: tuple[str, str]) -> bool:
        detail = self._detail_for_key(key)
        if detail is None or not detail.cwd:
            return False
        if detail.is_wsl and not detail.distro:
            return self._load_async(key, self._folder_ready)   # 要先知道发行版名
        return self._open_folder(key, detail)

    def _on_folder_ready(self, key, detail) -> None:
        self._cache[key] = detail
        self._open_folder(key, detail)

    def _open_folder(self, key, detail: SessionDetail) -> bool:
        path = claude_session_jump.explorer_path(detail)
        if not path or not self.opener(path):
            self._say(key, "打不开这个项目文件夹")
            return False
        return True

    def copy_resume(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return self.copy_resume_key(key) if key else False

    def copy_resume_key(self, key: tuple[str, str]) -> bool:
        detail = self._detail_for_key(key)
        if detail is None or not detail.resume_command:
            return False
        return self._copy(key, detail.resume_command, "恢复命令已复制，到终端里粘贴即可")

    def copy_session_id(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return bool(key) and self._copy(key, key[1], "会话 ID 已复制")

    def _copy(self, key, text: str, said: str) -> bool:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        self._say(key, said)
        return True

    def dismiss(self, sprite) -> bool:
        return self._controller.dismiss(sprite)

    def _say(self, key, message: str) -> None:
        """结果给用户看：卡片开着就写在卡片上，否则用这只小鱼的气泡。"""
        card = self._card
        if (card is not None and shiboken6.isValid(card) and card.isVisible()
                and card.key == key):
            card.show_result(message)
            return
        sprite = self._controller.sprite_of(key)
        if sprite is None:
            return
        try:
            self._shell._show_bubble_text_for(sprite, message, 3200)
        except Exception:
            log.debug("会话小鱼气泡失败", exc_info=True)


def _open_path(path: str) -> bool:
    try:
        os.startfile(path)  # noqa: S606  （资源管理器打开文件夹）
        return True
    except (AttributeError, OSError):
        return False


def build_session_pet_menu(shell, sprite, actions: SessionPetActions) -> QMenu:
    """会话小鱼的右键菜单：只有和这个会话有关的动作。"""
    from .context_menus.menu_styles import apply_modern_menu_style, install_modern_check_indicators
    from .context_menus.menu_styles.common import install_responsive_menu_style
    from .context_menus.shared import add_action, add_submenu
    from .sprite_menu_facade import SpriteMenuFacade

    facade = SpriteMenuFacade(shell, sprite)
    menu = QMenu()
    apply_modern_menu_style(menu, facade.cfg.get("context_menu_appearance", {}) or {})
    detail: Any = actions.detail_of(sprite)
    if detail is not None:
        header = menu.addAction(claude_hooks.session_label(detail.agent, {
            "title": detail.title, "project": detail.project, "sessionId": detail.session_id}))
        header.setEnabled(False)
        menu.addSeparator()
    add_action(menu, "跳到这个对话", None, lambda: actions.jump(sprite), close_on_trigger=True)
    add_action(menu, "查看详情", None, lambda: actions.show_card(sprite), close_on_trigger=True)
    add_action(menu, "打开项目文件夹", None, lambda: actions.open_folder(sprite),
               close_on_trigger=True)
    menu.addSeparator()
    add_action(menu, "复制恢复命令", None, lambda: actions.copy_resume(sprite),
               close_on_trigger=True)
    add_action(menu, "复制会话 ID", None, lambda: actions.copy_session_id(sprite),
               close_on_trigger=True)
    menu.addSeparator()
    add_action(menu, "让这只离场", None, lambda: actions.dismiss(sprite), close_on_trigger=True)

    settings = add_submenu(menu, "会话小鱼设置")
    enabled = settings.addAction("每个会话一只小鱼")
    enabled.setCheckable(True)
    enabled.setChecked(bool((facade.cfg.get("agent_link") or {}).get("session_pets", True)))
    enabled.toggled.connect(lambda on: facade.toggle_session_pets(on))
    limit_menu = add_submenu(settings, "会话小鱼上限")
    current = shell._session_pet_limit()
    for limit in (3, 6, 9, 12, 16, 24):
        item = limit_menu.addAction(f"{limit} 只")
        item.setCheckable(True)
        item.setChecked(limit == current)
        item.triggered.connect(lambda _checked=False, n=limit: facade.set_session_pets_max(n))
    theme_menu = add_submenu(settings, "详情卡配色")
    current_theme = _configured_theme_id(facade.cfg)
    for theme_id, label in session_card_themes.theme_choices():
        item = theme_menu.addAction(label)
        item.setCheckable(True)
        item.setChecked(theme_id == current_theme)
        item.triggered.connect(lambda _checked=False, t=theme_id: facade.set_session_card_theme(t))
    install_modern_check_indicators(menu)
    install_responsive_menu_style(menu)
    return menu
