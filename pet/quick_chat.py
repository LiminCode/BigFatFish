# -*- coding: utf-8 -*-
"""快速对话气泡（Quick Chat）。

点击桌宠弹出的头顶小气泡输入框；回车发送，AI 回复在气泡内流式显示，
与完整 AI 对话窗口共用同一会话历史（SessionStore / ChatService）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .speech_bubble import BUBBLE_STYLE_PRESETS
from .speech_bubble_text import truncate_bubble_text
from .ui_fonts import apply_family

from .chat.models import ChatMessage
from .chat.prompt import PromptBuilder
from .chat.service import ChatService
from .chat.session_store import SessionStore

_PAGE_SIZE = 500

# 气泡内 AI 回答的展示上限：超长回答不进气泡（头顶气泡只有几百像素），
# 截断到 _REPLY_PREVIEW_LIMIT 字并提示全文在聊天窗（气泡内提供直达按钮）。
# 回复区加高到两倍后上限随之翻倍（原 150）：不然加高的部分只是空白。
_REPLY_PREVIEW_LIMIT = 300
_REPLY_PREVIEW_SUFFIX = "…（全文见聊天窗）"

# 气泡整体放大倍数（宽度、留白、圆角、按钮、字号）。原始尺寸（320~460 宽、系统
# 默认字号）在高分屏上偏小；再乘「气泡文字大小」设置（bubble_text_scale，100 =
# 不额外缩放），所以用户调那一项时聊天气泡跟着变。
QUICK_CHAT_BASE_SCALE = 1.25
# 回复区（文字窗口）的高度单独放大：要的是多看几行字，不是整个气泡变大。
QUICK_CHAT_REPLY_HEIGHT_SCALE = 2.0
_SCALE_MIN, _SCALE_MAX = 1.0, 4.0


def quick_chat_scale(config) -> float:
    """聊天气泡的整体缩放倍数（构造时取一次）。"""
    try:
        percent = float(config.get("bubble_text_scale", 100) or 100)
    except (AttributeError, TypeError, ValueError):
        percent = 100.0
    return max(_SCALE_MIN, min(_SCALE_MAX, QUICK_CHAT_BASE_SCALE * percent / 100.0))


def _surface_radius(preset: dict) -> float:
    """气泡主体圆角。

    breath_bubble 是有机水滴形（speech_bubble 专属几何，preset 里 radius=0）：
    quick_chat 不支持该形状，按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置在桌宠气泡与快速对话两套观感。这里用大圆角
    近似，与 speech_bubble 同设置不破解；普通预设用自己的 radius。
    """
    if preset.get("shape") == "breath_bubble":
        return 22.0
    return float(preset.get("radius", 14))


class QuickChatBubble(QFrame):
    def __init__(self, config, pet_window=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.pet_window = pet_window
        self.setObjectName("quick-chat-bubble")
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._capture_compat = False
        self._capture_host: QWidget | None = None
        self._scale = quick_chat_scale(config)
        apply_family(self)   # 与桌宠气泡同一种字体（等线）
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * self._scale)
            self.setFont(font)  # 子控件在 _build 里创建，继承这份字号
        min_w, max_w = self._px(320), self._px(460)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            # 放大后也不许比屏幕还宽（小屏 / 竖屏）
            limit = max(240, screen.availableGeometry().width() - 16)
            min_w, max_w = min(min_w, limit), min(max_w, limit)
        self.setMinimumWidth(min_w)
        self.setMaximumWidth(max_w)
        # 完整聊天窗的同步入口（宿主注入）：``callback(session_id, focus=False)``。
        # 回复落库后调一次，让开着的聊天窗重读；点「去聊天窗」时带 focus=True，
        # 让聊天窗切到这里正在聊的会话。
        self.chat_sync_callback = None
        self._handoff = False  # 生成途中点了「去聊天窗」：关气泡也不打断这一轮

        style_id = str(config.get("self_talk_bubble_style", "classic_top") or "classic_top")
        self._preset = BUBBLE_STYLE_PRESETS.get(style_id, BUBBLE_STYLE_PRESETS["classic_top"])
        self._tail_up = False

        self.character_id = str(config.get("character", "shenshen"))
        self.settings = config.chat_settings()
        self.prompt_builder = PromptBuilder(Path(__file__).resolve().parent.parent / "assets" / "characters")
        self.store = SessionStore(config.dir, getattr(config, "instance_id", ""))
        self.session = self._get_session()
        self.service = ChatService(parent=self)
        self._active_request_id: str | None = None
        self._reply_full = ""       # AI 回答全文（会话历史/聊天窗用，不截断）
        self._reply_text = ""       # 气泡内展示文本（超上限截断 + 提示看聊天窗）
        self._reply_truncated = False
        self._page = 0
        self._pages: list[str] = []
        self._deactivate_check_pending = False

        self._build()
        self._connect()

    def _px(self, value: float) -> int:
        """按气泡缩放倍数换算一个像素尺寸。"""
        return int(round(value * self._scale))

    def _reply_px(self, value: float) -> int:
        """回复区高度：按它自己的倍数放大（同样跟随「气泡文字大小」设置）。"""
        factor = QUICK_CHAT_REPLY_HEIGHT_SCALE * self._scale / QUICK_CHAT_BASE_SCALE
        return int(round(value * factor))

    def _build(self) -> None:
        px = self._px
        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(14), px(12), px(14), px(12))
        layout.setSpacing(px(8))

        header = QHBoxLayout()
        title = QLabel("快速对话")
        title.setObjectName("quick-chat-title")
        self.title_label = title  # 子类（灵动岛气泡）改标题用
        header.addWidget(title)
        header.addStretch(1)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("quick-chat-hint")
        header.addWidget(self.hint_label)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("quick-chat-close")
        self.close_btn.setFixedSize(px(24), px(24))
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.output = QLabel("")
        self.output.setObjectName("quick-chat-output")
        self.output.setWordWrap(True)
        self.output.setMinimumHeight(self._reply_px(60))
        self.output.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.output_scroll = QScrollArea()
        self.output_scroll.setObjectName("quick-chat-output-scroll")
        self.output_scroll.setWidgetResizable(True)
        self.output_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.output_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output_scroll.setMinimumHeight(self._reply_px(60))
        self.output_scroll.setMaximumHeight(self._reply_px(220))
        self.output_scroll.setWidget(self.output)
        layout.addWidget(self.output_scroll)

        self.page_widget = QWidget()
        self.page_row = QHBoxLayout(self.page_widget)
        self.page_row.setContentsMargins(0, 0, 0, 0)
        self.prev_btn = QPushButton("←")
        self.page_label = QLabel("")
        self.next_btn = QPushButton("→")
        for btn in (self.prev_btn, self.next_btn):
            btn.setObjectName("quick-chat-page")
            btn.setFixedSize(px(28), px(24))
        self.open_chat_btn = QPushButton("去聊天窗")
        self.open_chat_btn.setObjectName("quick-chat-open")
        self.page_row.addWidget(self.prev_btn)
        self.page_row.addWidget(self.page_label)
        self.page_row.addWidget(self.next_btn)
        self.page_row.addStretch(1)
        self.page_row.addWidget(self.open_chat_btn)
        layout.addWidget(self.page_widget)
        self.page_widget.setVisible(False)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入消息，回车发送…")
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("quick-chat-send")
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        bg = self._preset["background"]
        fg = self._preset["foreground"]
        border = self._preset["border"]
        self.setStyleSheet(f"""
            QLabel#quick-chat-title, QLabel#quick-chat-hint, QLabel#quick-chat-output,
            QLabel#quick-chat-page {{ background: transparent; color: {fg}; border: none; }}
            QScrollArea#quick-chat-output-scroll {{ background: transparent; border: none; }}
            QPushButton {{
                background: {border}; color: {fg}; border: none; border-radius: {px(8)}px;
                padding: {px(3)}px {px(8)}px;
            }}
            QPushButton:hover {{ background: {fg}; color: {bg}; }}
            QLineEdit {{
                background: {bg}; color: {fg}; border: 1px solid {border};
                border-radius: {px(8)}px; padding: {px(5)}px {px(8)}px;
            }}
        """)

    def _connect(self) -> None:
        self.close_btn.clicked.connect(self.close)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.prev_btn.clicked.connect(lambda: self._show_page(self._page - 1))
        self.next_btn.clicked.connect(lambda: self._show_page(self._page + 1))
        self.open_chat_btn.clicked.connect(self._open_full_chat)
        self.service.started.connect(self._started)
        self.service.delta.connect(self._delta)
        self.service.finished.connect(self._finished)
        self.service.error.connect(self._error)
        self.service.stopped.connect(self._stopped)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = self._scale
        rect = QRectF(self.rect()).adjusted(6 * s, 8 * s, -6 * s, -8 * s)
        radius = _surface_radius(self._preset) * s
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        tail = QPainterPath()
        tip_x = rect.center().x()
        half, rise, overlap = 8 * s, 6 * s, 2 * s
        if self._tail_up:
            tip = QPointF(tip_x, rect.top() - rise)
            tail.moveTo(QPointF(tip_x - half, rect.top() + overlap))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + half, rect.top() + overlap))
        else:
            tip = QPointF(tip_x, rect.bottom() + rise)
            tail.moveTo(QPointF(tip_x - half, rect.bottom() - overlap))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + half, rect.bottom() - overlap))
        tail.closeSubpath()
        surface = body.united(tail).simplified()

        # 柔和阴影
        shadow = QPainterPath(surface)
        shadow.translate(0, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._preset.get("shadow", "#6b542b")))
        painter.drawPath(shadow)

        # 气泡主体
        painter.setBrush(QColor(self._preset["background"]))
        painter.setPen(QPen(QColor(self._preset["border"]), 1))
        painter.drawPath(surface)
        painter.end()

    # ------------------------------------------------------------ 会话
    def _get_session(self):
        sessions = self.store.list(self.character_id)
        return sessions[0] if sessions else self._new_session()

    def refresh_session(self) -> None:
        """从磁盘重取最近会话（公开 seam；角色切换后外部刷新用，替代私访 _get_session）。"""
        self.session = self._get_session()

    def _new_session(self):
        session = self.store.create(
            self.character_id,
            self.settings.active_provider,
            self.prompt_builder.effective_system_prompt(self.settings, self.character_id),
        )
        self.store.save(session)
        return session

    def position_near_pet(self) -> None:
        pet = self.pet_window
        if pet is None or not hasattr(pet, "visible_content_rect"):
            return
        anchor = pet.visible_content_rect()
        host = self._capture_host if self._capture_compat else None
        if host is not None and not host.geometry().isEmpty():
            available = host.geometry()
        else:
            screen = QGuiApplication.screenAt(anchor.center())
            available = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        w = self.width()
        h = self.height()
        x = anchor.center().x() - w // 2
        y = anchor.top() - h - 8
        self._tail_up = False
        if host is not None and y < available.top():
            # 子模式默认只允许落在主窗内，会把气泡挤到下方/遮挡宠物。
            # 先向主窗申请透明头顶空间，尽量恢复“向上生成”的原生位置。
            screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
            if screen is not None:
                screen_top = screen.availableGeometry().top()
                desired_top = y - 4
                if desired_top >= screen_top:
                    desired_h = available.top() - desired_top
                    setter = getattr(host, "set_capture_headroom", None)
                    if desired_h > 0 and setter is not None and setter(desired_h):
                        return self.position_near_pet()
        if y < available.top():
            y = anchor.bottom() + 8
            self._tail_up = True
        x = max(available.left() + 4, min(x, available.right() - w - 4))
        if host is not None:
            # 直播捕获子模式下只允许落在主窗矩形内；空间不足时夹到窗内，
            # 避免子控件被主窗边界裁掉。
            if h <= available.height():
                y = max(available.top() + 4, min(y, available.bottom() - h - 4))
            else:
                y = available.top() + 4
            self.move(host.mapFromGlobal(QPoint(x, y)))
        else:
            self.move(x, y)
        self.update()

    def set_capture_compat(self, on: bool, host: QWidget | None = None) -> None:
        """直播捕获兼容：把快速对话气泡作为桌宠主窗的子内容渲染（issue #62）。

        开启后快速对话不再是独立 Tool 窗口，而成为主窗子控件，捕获主窗时即可
        看到并操作它；关闭后恢复独立置顶 Tool 窗口形态。
        """
        on = bool(on)
        if on == self._capture_compat:
            return
        if on and host is None:
            return
        was_visible = self.isVisible()
        self._capture_compat = on
        self._capture_host = host if on else None
        if on:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setParent(host)
        else:
            self.setParent(None)
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setWindowFlags(flags)
        if was_visible:
            self.position_near_pet()
            self.show()
            if not on:
                self.raise_()
                self.activateWindow()
                self.input.setFocus()
        else:
            # 子模式重挂主窗后不能随父窗显示而自动弹出空白窗。
            self.hide()

    def show_for_pet(self, pet_window=None) -> None:
        if pet_window is not None:
            self.pet_window = pet_window
        self.position_near_pet()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    # ------------------------------------------------------------ 发送
    def _send(self) -> None:
        if self.service.busy:
            self.service.stop()
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        # 陈旧快照防护（DS-M7 → R3 P1 硬修）：原子「读-追加-提交」
        synced, _absorbed = self.store.append_message(
            self.session, ChatMessage("user", text)
        )
        if synced is None:
            self.session.messages.append(ChatMessage("user", text))
            self.store.save(self.session)
        else:
            self.session = synced
        self._notify_chat_sync()
        self.output.setText("")
        self._set_reply_text("")
        self._page = 0
        self._pages = []
        self.page_widget.setVisible(False)
        self.hint_label.setText("思考中…")
        config = self.settings.active_config
        config.api_key = self.config.resolve_api_key(config)
        messages = self.prompt_builder.build_messages(
            self.settings, self.character_id, self.session.messages[:-1], text
        )
        self._active_request_id = self.service.send(messages, config)

    def _started(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self.hint_label.setText("生成中…")

    def _delta(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id:
            return
        self._set_reply_text(self._reply_full + str(text))
        self._render_reply()

    def _finished(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id:
            return
        # 落库/聊天窗用全文；气泡展示文本另行截断（见 _set_reply_text）。
        self._set_reply_text(text)
        synced, _absorbed = self.store.append_message(self.session, ChatMessage("assistant", self._reply_full))
        if synced is None:
            self.session.messages.append(ChatMessage("assistant", self._reply_full))
            self.store.save(self.session)
        else:
            self.session = synced
        self._active_request_id = None
        self._handoff = False
        self.hint_label.setText("")
        self._render_reply()
        self._notify_chat_sync()

    def _error(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id:
            return
        self._active_request_id = None
        self._handoff = False
        self.hint_label.setText("")
        self._set_reply_text(f"请求失败：{text}")
        self._render_reply()

    def _stopped(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self._active_request_id = None
        self._handoff = False
        self.hint_label.setText("已停止")

    # ------------------------------------------------------------ 显示
    def _set_reply_text(self, full_text: str) -> None:
        """记录 AI 回答全文，并算出气泡内展示文本（超限截断 + 提示全文位置）。

        全文与展示文本分开：会话历史/聊天窗始终拿全文，气泡只展示开头一段，
        免得长回答把头顶气泡撑成一堵墙。
        """
        self._reply_full = str(full_text or "")
        self._reply_text = truncate_bubble_text(
            self._reply_full, _REPLY_PREVIEW_LIMIT, _REPLY_PREVIEW_SUFFIX
        )
        self._reply_truncated = self._reply_text != self._reply_full

    def _set_page_controls_visible(self, on: bool) -> None:
        """显示/隐藏分页箭头与页码（截断预览时只保留「去聊天窗」按钮）。"""
        for widget in (self.prev_btn, self.page_label, self.next_btn):
            widget.setVisible(on)

    def _render_reply(self) -> None:
        text = self._reply_text
        if len(text) > _PAGE_SIZE:
            self._pages = [text[i:i + _PAGE_SIZE] for i in range(0, len(text), _PAGE_SIZE)]
            self._show_page(0)
            self._set_page_controls_visible(True)
            self.page_widget.setVisible(True)
            return
        self._pages = []
        # 截断预览：文案末尾已提示「全文见聊天窗」，这里只露出直达按钮；
        # 分页箭头/页码对一段预览没有意义，隐藏。
        self._set_page_controls_visible(not self._reply_truncated)
        self.page_widget.setVisible(self._reply_truncated)
        self.output.setText(text)

    def _show_page(self, index: int) -> None:
        if not self._pages:
            return
        self._page = max(0, min(index, len(self._pages) - 1))
        self.output.setText(self._pages[self._page])
        self.page_label.setText(f"{self._page + 1}/{len(self._pages)}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < len(self._pages) - 1)

    def _open_full_chat(self) -> None:
        # 聊天窗一激活，本气泡就会因失焦而关闭。回答还在生成时不能跟着被掐掉：
        # 让这一轮在后台跑完、照常落库，落库后再通知聊天窗重读。
        self._handoff = bool(self.service.busy)
        pet = self.pet_window
        if pet is not None and callable(getattr(pet, "on_open_chat", None)):
            pet.on_open_chat()
        elif hasattr(self, "open_chat_callback") and callable(self.open_chat_callback):
            self.open_chat_callback()
        # 聊天窗是隐藏后复用的，手里可能还是旧快照，甚至停在别的会话上
        self._notify_chat_sync(focus=True)

    def _notify_chat_sync(self, *, focus: bool = False) -> None:
        callback = self.chat_sync_callback
        if not callable(callback):
            return
        try:
            callback(self.session.session_id, focus=focus)
        except Exception:
            logging.exception("快速对话：同步聊天窗失败")

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            # Cocoa 在另一个应用内窗口仍活动时首次 show/activate Tool 窗口，
            # 会产生一次过渡性的 WindowDeactivate；此时同步 close 会留下只
            # 有原生灰色底板的空白窗口。下一事件轮的 activeWindow 已稳定，
            # 可以区分这次过渡和用户真正切走焦点。
            if not self._deactivate_check_pending:
                self._deactivate_check_pending = True
                QTimer.singleShot(0, self, self._close_if_still_inactive)
        return super().event(event)

    def _close_if_still_inactive(self) -> None:
        self._deactivate_check_pending = False
        if self.isVisible() and QApplication.activeWindow() is not self:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.service.busy and not self._handoff:
            self.service.stop()
        if self._capture_compat and self._capture_host is not None:
            setter = getattr(self._capture_host, "set_capture_headroom", None)
            if setter is not None:
                try:
                    setter(0)
                except RuntimeError:
                    pass  # 宿主窗口已在销毁中
        super().closeEvent(event)
