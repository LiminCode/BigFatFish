# -*- coding: utf-8 -*-
"""会话小鱼的交互面：详情卡、专属右键菜单、跳转（Qt 层）。

会话小鱼是一个 Claude Code 会话的状态指示，不是另一只肥鱼——主肥鱼那棵菜单
（动作点播、AI 对话、角色切换……）对它没有意义。这里给它两样自己的东西：

- **单击 → 详情卡**（Metro 风格）：标题、状态、模型 / 思考强度 / 持续时长三块磁贴、
  上下文用了多少、最近的问题、在哪打开的（VS Code 插件 / 终端 / 桌面版 / WSL；VS Code 的
  还有所在的工作区）、项目路径与分支，外加「跳到对话 / 打开文件夹 / 复制恢复命令」；
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
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import claude_hooks, claude_session_info, claude_session_jump, session_card_themes
from .claude_session_info import SessionDetail
from .i18n import t
from .note_meta_bar import meta_icon, short_count
from .settings_widgets import TiltButton

log = logging.getLogger(__name__)

#: 详情卡相对系统默认字号 / 尺寸的放大倍数（再乘「气泡文字大小」设置）
CARD_BASE_SCALE = 1.25
_WAIT_TEXT = "menu.session.waiting_for_you"   # 文案键，用时 t()


def elapsed_text(seconds: float) -> str:
    """持续时间的口语说法：刚刚 / 3 分钟 / 1 小时 5 分。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return t("menu.session.just_now")
    minutes = seconds // 60
    if minutes < 60:
        return t("menu.session.minutes_min", minutes=minutes)
    hours, minutes = divmod(minutes, 60)
    return t("menu.session.hours_h_minutes_min", hours=hours, minutes=minutes) if minutes else t("menu.session.hours_h", hours=hours)


def status_line(detail: SessionDetail, since: float | None, now: float | None = None) -> str:
    """「工作中 · 已 3 分钟」；等批准时点名在等哪个工具。"""
    text = claude_hooks.PHASE_TEXT.get(detail.phase, "")
    if detail.phase == "waiting" and detail.tool:
        text = t("menu.session.waiting_for_tool", tool=detail.tool)
    # 在用的模型与 effort（会话记录里读到才有）：「Fable 5.1 · high」
    model = claude_session_info.model_label(detail.model)
    for part in (model, detail.effort if model else ""):
        if part:
            text = f"{text} · {part}" if text else part
    if since:
        text = t("menu.session.text_v", text=text, v=elapsed_text((now or time.time()) - since)) if text else ""
    return text


def where_line(detail: SessionDetail) -> str:
    parts = [detail.entry_text] if detail.entry_text else []
    if detail.cwd:
        parts.append(detail.cwd)
    if detail.git_branch and detail.git_branch != "HEAD":
        parts.append(t("menu.session.branch_git_branch", git_branch=detail.git_branch))
    return " · ".join(parts)


def phase_line(detail: SessionDetail) -> str:
    """详情卡状态行：只有阶段（等批准时点名在等哪个工具）；模型、effort、时长各有各的磁贴。"""
    if detail.phase == "waiting" and detail.tool:
        return t("menu.session.waiting_for_tool", tool=detail.tool)
    return claude_hooks.PHASE_TEXT.get(detail.phase, "")


def context_text(detail: SessionDetail) -> tuple[str, float | None, str]:
    """上下文那一行：(文字, 占窗口的比例或 None, 悬停提示)。没读到用量时全是空。

    窗口按模型查（``claude_session_info.context_window``）；认不出的模型只写用了多少、不画比例。"""
    used = int(detail.context_tokens or 0)
    if used <= 0:
        return "", None, ""
    window = claude_session_info.context_window(detail.model)
    if not window:
        return (t("session_card.context_only", used=short_count(used)), None,
                t("session_card.context_tip_unknown", used=f"{used:,}"))
    ratio = min(1.0, used / window)
    return (t("session_card.context_used", used=short_count(used), window=short_count(window),
              percent=max(1, round(ratio * 100))),
            ratio, t("session_card.context_tip", used=f"{used:,}", window=f"{window:,}"))


def workspace_text(detail: SessionDetail) -> tuple[str, str, str]:
    """VS Code 工作区那一行：(名字, 补充说明, 悬停提示)；不是 VS Code 会话或认不出窗口时全是空。"""
    workspace = detail.extra.get("workspace") if isinstance(detail.extra, dict) else None
    if not isinstance(workspace, dict) or not workspace.get("label"):
        return "", "", ""
    folders = int(workspace.get("folders") or 0)
    sub = (t("session_card.workspace_multi", n=folders) if workspace.get("multi_root")
           else t("session_card.workspace_single"))
    return (str(workspace["label"]), sub,
            t("session_card.workspace_tip", target=str(workspace.get("target") or workspace["label"])))


def app_caption(detail: SessionDetail) -> str:
    """卡片页头的小字：「CLAUDE CODE · VS CODE 插件」（Metro 的应用名那一行，全大写）。"""
    entry = detail.entry_text
    return ("Claude Code · " + entry if entry else "Claude Code").upper()


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


# ---------------------------------------------------------------- 图标（自己画，不用 emoji 字体）
def card_icon(name: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    """详情卡用的线条小图标（16 单位的画布）。模型 / effort / 时长沿用笔记信息栏那一套。"""
    if name in ("model", "effort", "time"):
        return meta_icon(name, color, size, dpr)
    pixmap = QPixmap(max(1, round(size * dpr)), max(1, round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 16.0, size / 16.0)
    painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    line = painter.drawLine
    if name == "folder":
        path = QPainterPath(QPointF(1.8, 4.0))
        for x, y in ((6.0, 4.0), (7.6, 5.8), (14.2, 5.8), (14.2, 12.8), (1.8, 12.8)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "branch":                    # 主干 + 一条分出去的枝
        painter.drawEllipse(QPointF(5, 3.4), 1.6, 1.6)
        painter.drawEllipse(QPointF(5, 12.6), 1.6, 1.6)
        painter.drawEllipse(QPointF(11, 5.4), 1.6, 1.6)
        line(QPointF(5, 5.0), QPointF(5, 11.0))
        path = QPainterPath(QPointF(11, 7.0))
        path.cubicTo(QPointF(11, 9.6), QPointF(5, 8.6), QPointF(5, 11.0))
        painter.drawPath(path)
    elif name == "workspace":                 # 编辑器窗口：标题栏 + 侧栏
        painter.drawRect(QRectF(1.8, 2.6, 12.4, 10.8))
        line(QPointF(1.8, 5.4), QPointF(14.2, 5.4))
        line(QPointF(6.0, 5.4), QPointF(6.0, 13.4))
    elif name == "jump":                      # 向右的箭头
        line(QPointF(2.4, 8), QPointF(13.2, 8))
        line(QPointF(9.0, 3.8), QPointF(13.2, 8))
        line(QPointF(9.0, 12.2), QPointF(13.2, 8))
    elif name == "copy":                      # 两张叠着的纸
        painter.drawRect(QRectF(5.4, 5.4, 8.4, 8.4))
        path = QPainterPath(QPointF(2.4, 10.4))
        path.lineTo(2.4, 2.4)
        path.lineTo(10.4, 2.4)
        painter.drawPath(path)
    elif name == "close":
        line(QPointF(3.6, 3.6), QPointF(12.4, 12.4))
        line(QPointF(12.4, 3.6), QPointF(3.6, 12.4))
    painter.end()
    return pixmap


def phase_badge(phase: str, background: str, foreground: str, size: int, dpr: float = 1.0) -> QPixmap:
    """状态行前面那块方磁贴：强调色底 + 阶段的小记号（工作中三个点、等批准一个感叹号、
    等你回复一个对勾、休息中一弯月亮）。"""
    pixmap = QPixmap(max(1, round(size * dpr)), max(1, round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(QColor(background))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 16.0, size / 16.0)
    ink = QColor(foreground)
    painter.setPen(QPen(ink, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if phase == "working":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        for x in (4.4, 8.0, 11.6):
            painter.drawEllipse(QPointF(x, 8), 1.3, 1.3)
    elif phase == "waiting":
        painter.drawLine(QPointF(8, 3.6), QPointF(8, 9.4))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawEllipse(QPointF(8, 12.2), 1.1, 1.1)
    elif phase == "review":
        path = QPainterPath(QPointF(3.8, 8.4))
        path.lineTo(6.8, 11.4)
        path.lineTo(12.4, 4.8)
        painter.drawPath(path)
    else:                                       # 休息中 / 不知道
        moon = QPainterPath()
        moon.addEllipse(QPointF(8, 8), 4.6, 4.6)
        bite = QPainterPath()
        bite.addEllipse(QPointF(10.4, 6.2), 4.0, 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawPath(moon.subtracted(bite))
    painter.end()
    return pixmap


#: 和简报窗口 / 设置页一样的 Metro 字体：西文 Segoe UI，中文雅黑；标题用它们的细体
_FONTS = ["Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "PingFang SC", "Microsoft YaHei UI", "sans-serif"]
_LIGHT_STACK = ('"Segoe UI Light", "Microsoft YaHei UI Light", "Segoe UI", "SF Pro Display", '
                '"PingFang SC", "Microsoft YaHei UI", sans-serif')
#: 磁贴的顺序与图标
TILE_KEYS = ("model", "effort", "time")


class _MetricTile(QFrame):
    """一块数字磁贴：图标 + 小字标题，下面一行值（模型 / 思考强度 / 持续时长）。"""

    def __init__(self, key: str, px, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("session-card-tile")
        self.icon = QLabel(self)
        self.icon.setFixedSize(px(13), px(13))
        self.caption = QLabel(t(f"session_card.caption.{key}").upper(), self)
        self.caption.setObjectName("session-card-tile-caption")
        self.value = QLabel("", self)
        self.value.setObjectName("session-card-tile-value")
        self.value.setTextFormat(Qt.TextFormat.PlainText)        # 模型名是外来内容
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(px(5))
        top.addWidget(self.icon)
        top.addWidget(self.caption)
        top.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(10), px(8), px(10), px(9))
        layout.setSpacing(px(3))
        layout.addLayout(top)
        layout.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text)
        self.setAccessibleName(f"{self.caption.text()}: {text}")
        self.setVisible(bool(text))


class _InfoRow(QWidget):
    """一行「图标 + 文字 + 灰色补充」：工作区、文件夹、分支。"""

    def __init__(self, key: str, px, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.icon = QLabel(self)
        self.icon.setFixedSize(px(14), px(14))
        self.text = QLabel("", self)
        self.text.setObjectName("session-card-info")
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sub = QLabel("", self)
        self.sub.setObjectName("session-card-info-sub")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(8))
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.sub, 0, Qt.AlignmentFlag.AlignTop)

    def set_text(self, text: str, sub: str = "", tip: str = "") -> None:
        self.text.setText(text)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.setToolTip(tip)
        self.setVisible(bool(text))


class _ContextBar(QWidget):
    """上下文占窗口多少：一根方头的平条（底色 + 强调色的已用部分）。"""

    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self.ratio = 0.0
        self._track = QColor("#dddddd")
        self._fill = QColor("#0a84ff")
        self.setFixedHeight(height)

    def set_colors(self, track: str, fill: str) -> None:
        self._track, self._fill = QColor(track), QColor(fill)
        self.update()

    def set_ratio(self, ratio: float) -> None:
        self.ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._track)
        width = round(self.width() * self.ratio)
        if width > 0:
            painter.fillRect(0, 0, max(2, width), self.height(), self._fill)
        painter.end()


class SessionDetailCard(QFrame):
    """锚在会话小鱼头顶的详情卡（Windows Phone / Metro 风格）；失去焦点即收起。

    方角、平铺、无阴影：页头一条强调色的带子，小字大写的「CLAUDE CODE · 从哪打开的」+ 大而轻的
    标题；下面是状态磁贴、三块数字磁贴（模型 / 思考强度 / 持续）、上下文平条、最近的问题、
    带图标的工作区 / 文件夹 / 分支几行，最后一排会朝光标倾斜的方按钮。颜色全部取自
    ``session_card_themes`` 里选的方案：页头和主按钮用方案的强调色（``accent``），磁贴用按钮底色。
    """

    jump_requested = Signal()
    folder_requested = Signal()
    copy_requested = Signal()

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("session-detail-card")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._scale = _card_scale(config)
        self._theme_id = ""
        self._theme = session_card_themes.card_theme(None)
        self._phase = ""
        self._anchor = None
        self._deactivate_check_pending = False
        self.key: tuple[str, str] | None = None
        font = QFont()
        font.setFamilies(_FONTS)
        font.setPixelSize(self._px(13))
        self.setFont(font)                 # 子控件都继承它；样式表只改个别几处的字号和粗细
        self._build()
        self.apply_theme(_configured_theme_id(config))

    def _px(self, value: float) -> int:
        return int(round(value * self._scale))

    def _dpr(self) -> float:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return max(float(self.devicePixelRatioF() or 1.0), float(screen.devicePixelRatio()) if screen else 1.0)

    # ------------------------------------------------------------ 搭界面
    def _build(self) -> None:
        px = self._px
        width = px(360)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            width = min(width, max(240, screen.availableGeometry().width() - 16))
        self.setFixedWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)          # 留出 1px 的边
        outer.setSpacing(0)

        # 页头：强调色的带子
        self.header = QFrame(self)
        self.header.setObjectName("session-card-header")
        head = QVBoxLayout(self.header)
        head.setContentsMargins(px(16), px(8), px(6), px(14))
        head.setSpacing(px(2))
        top = QHBoxLayout()
        top.setSpacing(px(6))
        self.app_label = QLabel("CLAUDE CODE", self.header)
        self.app_label.setObjectName("session-card-app")
        top.addWidget(self.app_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = QPushButton("", self.header)
        self.close_btn.setObjectName("session-card-close")
        self.close_btn.setFixedSize(px(28), px(28))
        self.close_btn.setToolTip(t("session_card.close"))
        self.close_btn.setAccessibleName(t("session_card.close"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        top.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(top)
        self.title_label = QLabel("", self.header)
        self.title_label.setObjectName("session-card-title")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setContentsMargins(0, 0, px(10), 0)
        head.addWidget(self.title_label)
        outer.addWidget(self.header)

        body = QWidget(self)
        body.setObjectName("session-card-body")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(px(16), px(12), px(16), px(14))
        layout.setSpacing(px(10))
        outer.addWidget(body)

        status = QHBoxLayout()
        status.setSpacing(px(8))
        self.status_icon = QLabel(body)
        self.status_icon.setFixedSize(px(18), px(18))
        status.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_label = QLabel("", body)
        self.status_label.setObjectName("session-card-status")
        self.status_label.setWordWrap(True)
        status.addWidget(self.status_label, 1)
        layout.addLayout(status)

        tiles = QHBoxLayout()
        tiles.setSpacing(px(4))
        self.tiles = {key: _MetricTile(key, px, body) for key in TILE_KEYS}
        for key in TILE_KEYS:
            tiles.addWidget(self.tiles[key], 1)
        layout.addLayout(tiles)

        self.context_box = QWidget(body)
        context = QVBoxLayout(self.context_box)
        context.setContentsMargins(0, 0, 0, 0)
        context.setSpacing(px(5))
        row = QHBoxLayout()
        self.context_caption = QLabel(t("session_card.caption.context").upper(), self.context_box)
        self.context_caption.setObjectName("session-card-caption")
        self.context_value = QLabel("", self.context_box)
        self.context_value.setObjectName("session-card-context")
        row.addWidget(self.context_caption)
        row.addStretch(1)
        row.addWidget(self.context_value)
        context.addLayout(row)
        self.context_bar = _ContextBar(max(4, px(5)), self.context_box)
        context.addWidget(self.context_bar)
        layout.addWidget(self.context_box)

        prompt = QVBoxLayout()
        prompt.setSpacing(px(3))
        self.prompt_caption = QLabel(t("menu.session.latest_question").upper(), body)
        self.prompt_caption.setObjectName("session-card-caption")
        prompt.addWidget(self.prompt_caption)
        self.prompt_label = QLabel("", body)
        self.prompt_label.setObjectName("session-card-prompt")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setTextFormat(Qt.TextFormat.PlainText)
        self.prompt_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prompt.addWidget(self.prompt_label)
        layout.addLayout(prompt)

        places = QVBoxLayout()
        places.setSpacing(px(5))
        self.workspace_row = _InfoRow("workspace", px, body)
        self.folder_row = _InfoRow("folder", px, body)
        self.branch_row = _InfoRow("branch", px, body)
        for info in (self.workspace_row, self.folder_row, self.branch_row):
            places.addWidget(info)
        layout.addLayout(places)

        buttons = QHBoxLayout()
        buttons.setSpacing(px(4))
        self.jump_btn = TiltButton(t("menu.session.jump_chat"), body)
        self.jump_btn.setObjectName("session-card-primary")
        self.folder_btn = TiltButton(t("menu.session.open_folder"), body)
        self.copy_btn = TiltButton(t("menu.session.copy_resume_command"), body)
        self.jump_btn.clicked.connect(self.jump_requested.emit)
        self.folder_btn.clicked.connect(self.folder_requested.emit)
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        for button in (self.jump_btn, self.folder_btn, self.copy_btn):
            button.setAccessibleName(button.text())
            button.setText(" " + button.text())          # 图标和字之间留一点缝（样式表调不了这个间距）
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(px(14), px(14)))
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.result_label = QLabel("", body)
        self.result_label.setObjectName("session-card-result")
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        layout.addWidget(self.result_label)

    # ------------------------------------------------------------ 配色
    def apply_theme(self, theme_id) -> None:
        """换配色方案（``session_card_themes`` 里的 id）；与当前相同则什么都不做。

        颜色全部取自方案本身：页头、主按钮、状态磁贴、上下文平条用强调色（``accent`` /
        ``accent_text``），数字磁贴与普通按钮用按钮底（``button`` / ``button_text``）——这几对的
        对比度由测试逐项把关。"""
        theme_id = session_card_themes.normalize_theme_id(theme_id)
        if theme_id == self._theme_id:
            return
        self._theme_id, self._theme = theme_id, session_card_themes.CARD_THEMES[theme_id]
        c, px = self._theme, self._px
        self.setStyleSheet(f"""
            QLabel {{ background: transparent; color: {c["text"]}; border: none; }}
            QFrame#session-card-header {{ background: {c["accent"]}; border: none; }}
            QFrame#session-card-header QLabel {{ color: {c["accent_text"]}; }}
            QLabel#session-card-app {{ font-size: {px(10.5)}px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#session-card-title {{ font-family: {_LIGHT_STACK}; font-size: {px(21)}px; font-weight: 300; }}
            QLabel#session-card-status {{ font-size: {px(14)}px; font-weight: 600; }}
            QLabel#session-card-caption {{
                color: {c["muted"]}; font-size: {px(10.5)}px; font-weight: 600; letter-spacing: 1px;
            }}
            QLabel#session-card-context, QLabel#session-card-info-sub, QLabel#session-card-result {{
                color: {c["muted"]}; font-size: {px(12)}px;
            }}
            QLabel#session-card-info {{ font-size: {px(12.5)}px; }}
            QFrame#session-card-tile {{ background: {c["button"]}; border: none; }}
            QFrame#session-card-tile QLabel {{ color: {c["button_text"]}; }}
            QLabel#session-card-tile-caption {{ font-size: {px(10)}px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#session-card-tile-value {{ font-size: {px(16)}px; }}
            QPushButton {{
                background: {c["button"]}; color: {c["button_text"]};
                border: 2px solid transparent; border-radius: 0;
                padding: {px(4)}px {px(10)}px; min-height: {px(22)}px;
            }}
            QPushButton:hover {{ border-color: {c["hover"]}; }}
            QPushButton:disabled {{ color: {c["disabled_text"]}; }}
            QPushButton#session-card-primary {{ background: {c["accent"]}; color: {c["accent_text"]}; }}
            QPushButton#session-card-primary:hover {{ border-color: {c["text"]}; }}
            QPushButton#session-card-close {{ background: transparent; padding: 0; min-height: 0; }}
            QPushButton#session-card-close:hover {{ border-color: {c["accent_text"]}; }}
        """)
        self.context_bar.set_colors(c["button"], c["accent"])
        self._paint_icons()
        self.update()

    def _paint_icons(self) -> None:
        c, dpr = self._theme, self._dpr()
        small = self._px(13)
        for tile in self.tiles.values():
            tile.icon.setPixmap(card_icon(tile.key, c["button_text"], small, dpr))
        for info in (self.workspace_row, self.folder_row, self.branch_row):
            info.icon.setPixmap(card_icon(info.key, c["muted"], self._px(14), dpr))
        icon_px = self._px(14)
        for button, name, color in ((self.jump_btn, "jump", c["accent_text"]),
                                    (self.folder_btn, "folder", c["button_text"]),
                                    (self.copy_btn, "copy", c["button_text"])):
            icon = QIcon(card_icon(name, color, icon_px, dpr))
            icon.addPixmap(card_icon(name, c["disabled_text"], icon_px, dpr), QIcon.Mode.Disabled)
            button.setIcon(icon)
        self.close_btn.setIcon(QIcon(card_icon("close", c["accent_text"], icon_px, dpr)))
        self.close_btn.setIconSize(QSize(icon_px, icon_px))
        self.status_icon.setPixmap(phase_badge(self._phase, c["accent"], c["accent_text"], self._px(18), dpr))

    # ------------------------------------------------------------ 内容
    def show_detail(self, detail: SessionDetail, since: float | None, *,
                    loading: bool = False, now: float | None = None) -> None:
        self.app_label.setText(app_caption(detail))
        self.title_label.setText(claude_hooks.session_label(detail.agent, {
            "title": detail.title, "project": detail.project, "sessionId": detail.session_id}))
        self._phase = detail.phase
        self.status_label.setText(phase_line(detail))
        c = self._theme
        self.status_icon.setPixmap(phase_badge(self._phase, c["accent"], c["accent_text"], self._px(18), self._dpr()))
        self.status_icon.setVisible(bool(self.status_label.text()))

        model = claude_session_info.model_label(detail.model)
        self.tiles["model"].set_value(model)
        self.tiles["effort"].set_value(detail.effort if model else "")
        self.tiles["time"].set_value(elapsed_text((now or time.time()) - since) if since else "")

        text, ratio, tip = context_text(detail)
        self.context_value.setText(text)
        self.context_bar.setVisible(ratio is not None)
        self.context_bar.set_ratio(ratio or 0.0)
        self.context_box.setToolTip(tip)
        self.context_box.setAccessibleName(f"{self.context_caption.text()}: {text}" if text else "")
        self.context_box.setVisible(bool(text))

        if detail.last_prompt:
            prompt = detail.last_prompt
        elif loading:
            prompt = t("menu.session.loading")
        else:
            prompt = t("menu.session.couldn_t_read")
        self.prompt_label.setText(prompt)

        self.workspace_row.set_text(*workspace_text(detail))
        self.folder_row.set_text(detail.cwd, "", t("session_card.folder_tip"))
        branch = detail.git_branch if detail.git_branch != "HEAD" else ""
        self.branch_row.set_text(branch, "", t("session_card.branch_tip"))
        self.setAccessibleDescription(where_line(detail))
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
        """方角平铺：卡片底色 + 1px 的边，不画阴影（Metro）。页头的强调色由样式表画。"""
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._theme["background"]))
        painter.setPen(QPen(QColor(self._theme["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
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
        self.loader = load_detail
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
                         "started_at", "alive", "distro", "model", "effort", "context_tokens", "extra"):
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
        # 读回来的标题以会话记录 / 运行清单为准（含用户改的名字）：同步给小鱼头顶；
        # 在用的模型同理（hook 只在回合边界报，中途换模型那一轮它报的还是旧的）→ 桂冠
        self._controller.retitle(tuple(key), getattr(detail, "title", ""))
        self._controller.remodel(tuple(key), getattr(detail, "model", ""))
        self._cache[key] = detail
        card = self._card
        if (card is not None and shiboken6.isValid(card) and card.isVisible()
                and card.key == key):
            merged = self._detail_for_key(key) or detail
            card.show_detail(merged, self._controller.since(key))

    def _refresh_card(self, key) -> None:
        card = self._card
        detail = self._detail_for_key(key)
        if (detail is not None and card is not None and shiboken6.isValid(card)
                and card.isVisible() and card.key == key):
            card.show_detail(detail, self._controller.since(key))

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
        if self._controller.acknowledge(key):
            # 去看了：「等你回复」落回「休息中」，开着的卡片跟着换（下面的线程用的
            # 还是上面那份 detail——跳转只要会话 ID / 路径，与阶段无关）
            self._refresh_card(key)
        self._say(key, t("menu.session.switching_over"))

        def work() -> None:
            try:
                loaded = self.loader(detail)      # 要进程号 / 入口 / 是否还活着
                result = self.jumper(loaded, wsl_env=loaded.extra.get("env"))
            except Exception:
                log.exception("跳到会话失败")
                loaded, result = detail, claude_session_jump.JumpResult(False, t("menu.session.couldn_t_jump_there"))
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
            self._say(key, t("menu.session.couldn_t_open_project_folder"))
            return False
        return True

    def copy_resume(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return self.copy_resume_key(key) if key else False

    def copy_resume_key(self, key: tuple[str, str]) -> bool:
        detail = self._detail_for_key(key)
        if detail is None or not detail.resume_command:
            return False
        return self._copy(key, detail.resume_command, t("menu.session.resume_command_copied_paste_terminal"))

    def copy_session_id(self, sprite) -> bool:
        key = self._controller.key_of(sprite)
        return bool(key) and self._copy(key, key[1], t("menu.session.session_id_copied"))

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


def load_detail(detail: SessionDetail) -> SessionDetail:
    """读详情（会话记录 + 运行清单），VS Code 插件里的会话再认一下它开在哪个工作区。阻塞，后台线程里调。"""
    return claude_session_jump.attach_workspace(claude_session_info.load(detail))


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
    add_action(menu, t("menu.session.jump_chat_2"), None, lambda: actions.jump(sprite), close_on_trigger=True)
    add_action(menu, t("menu.session.show_details"), None, lambda: actions.show_card(sprite), close_on_trigger=True)
    add_action(menu, t("menu.session.open_project_folder"), None, lambda: actions.open_folder(sprite),
               close_on_trigger=True)
    menu.addSeparator()
    add_action(menu, t("menu.session.copy_resume_command"), None, lambda: actions.copy_resume(sprite),
               close_on_trigger=True)
    add_action(menu, t("menu.session.copy_session_id"), None, lambda: actions.copy_session_id(sprite),
               close_on_trigger=True)
    menu.addSeparator()
    add_action(menu, t("menu.session.send_one_off"), None, lambda: actions.dismiss(sprite), close_on_trigger=True)

    settings = add_submenu(menu, t("menu.session.session_fish_settings"))
    enabled = settings.addAction(t("menu.session.one_fish_per_session"))
    enabled.setCheckable(True)
    enabled.setChecked(bool((facade.cfg.get("agent_link") or {}).get("session_pets", True)))
    enabled.toggled.connect(lambda on: facade.toggle_session_pets(on))
    limit_menu = add_submenu(settings, t("menu.session.session_fish_limit"))
    current = shell._session_pet_limit()
    for limit in (3, 6, 9, 12, 16, 24):
        item = limit_menu.addAction(t("menu.session.limit_fish", limit=limit))
        item.setCheckable(True)
        item.setChecked(limit == current)
        item.triggered.connect(lambda _checked=False, n=limit: facade.set_session_pets_max(n))
    theme_menu = add_submenu(settings, t("menu.session.detail_card_colors"))
    current_theme = _configured_theme_id(facade.cfg)
    for theme_id, label in session_card_themes.theme_choices():
        item = theme_menu.addAction(label)
        item.setCheckable(True)
        item.setChecked(theme_id == current_theme)
        item.triggered.connect(lambda _checked=False, t=theme_id: facade.set_session_card_theme(t))
    install_modern_check_indicators(menu)
    install_responsive_menu_style(menu)
    return menu
