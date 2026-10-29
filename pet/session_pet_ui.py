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
from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import claude_hooks, claude_session_info, claude_session_jump, session_card_themes
from .claude_session_info import SessionDetail
from . import ui_fonts
from .i18n import t
from .note_meta_bar import meta_icon, short_count
from .notification_toast import wrap_lines
from .settings_widgets import TiltButton
from .context_menus.icons import vector_widget_icon

log = logging.getLogger(__name__)

_WAIT_TEXT = "menu.session.waiting_for_you"   # 文案键，用时 t()
#: 启动后多久预热详情卡的来源图标（比岛上那次晚一点，岛取过的同尺寸图标就直接命中缓存）
_ICON_WARM_DELAY_MS = 4000


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


def _configured_theme_id(config) -> str:
    """配置里选的详情卡配色方案（``agent_link.session_card_theme``）。"""
    try:
        agent_cfg = config.get("agent_link", {}) or {}
    except (AttributeError, TypeError):
        agent_cfg = {}
    value = agent_cfg.get(session_card_themes.CONFIG_KEY) if isinstance(agent_cfg, dict) else None
    return session_card_themes.normalize_theme_id(value)


def _configured_text_size(config) -> int:
    """配置里选的详情卡文字大小（``agent_link.session_card_text_size``，百分比）。"""
    try:
        agent_cfg = config.get("agent_link", {}) or {}
    except (AttributeError, TypeError):
        agent_cfg = {}
    value = agent_cfg.get(session_card_themes.TEXT_SIZE_KEY) if isinstance(agent_cfg, dict) else None
    return session_card_themes.normalize_text_size(value)


def _card_scale(config) -> float:
    return _configured_text_size(config) / 100.0


# ---------------------------------------------------------------- 图标（矢量线条，不用 emoji 字体）
#: 卡片上的东西 → 共用矢量图标库（``context_menus/icons.py``）里的语义名字
_SHARED_ICONS = {"workspace": "vscode", "folder": "folder", "branch": "branch", "jump": "jump",
                 "copy": "copy", "resume": "terminal", "close": "remove"}


def card_icon(widget, name: str, color: str, size: int) -> QPixmap:
    """详情卡用的单色线条小图标。模型 / effort / 时长沿用笔记信息栏那一套（``meta_icon``），
    其余取共用图标库，颜色用配色方案里的。"""
    dpr = float(widget.devicePixelRatioF() or 1.0)
    if name in ("model", "effort", "time"):
        return meta_icon(name, color, size, dpr)
    return vector_widget_icon(widget, _SHARED_ICONS[name], size, color).pixmap(QSize(size, size))


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


def _family_css(family: str) -> str:
    return f'font-family: "{family}"; ' if family else ""


#: 次要信息那一行的顺序（模型 / 思考强度 / 持续）
META_KEYS = ("model", "effort", "time")
#: 标题、最近的问题、跳转结果最多显示几行（超出的在末尾省略，悬停看全文）
TITLE_LINES, PROMPT_LINES, RESULT_LINES = 2, 4, 2


class _Lines(QLabel):
    """按宽度折成最多 ``max_lines`` 行、末尾省略的文字；全文放悬停提示。

    不用 QLabel 自己的 wordWrap：顶层窗口 ``adjustSize`` 时它报的高度不跟宽度走，长文字会被
    截掉一半（2026-10-28 实机截图：英文的最近一问只露出两行半）。这里折好行再按行数定高。"""

    def __init__(self, max_lines: int, parent=None) -> None:
        super().__init__(parent)
        self.max_lines = max_lines
        self.full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_full_text(self, text: str, width: int) -> None:
        self.full_text = str(text or "")
        width = max(20, width)
        lines = wrap_lines(self.full_text, self.font(), width, self.max_lines)
        self.setText("\n".join(lines))
        cut = len(wrap_lines(self.full_text, self.font(), width, self.max_lines + 1)) > self.max_lines
        self.setToolTip(self.full_text if cut else "")


class _Elided(QLabel):
    """单行文字，放不下就省略（路径省中间——两头的盘符和最后一层目录最有用）；全文在悬停提示里。"""

    def __init__(self, mode: Qt.TextElideMode, parent=None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(1)

    def set_full_text(self, text: str) -> None:
        self.full_text = str(text or "")
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = QFontMetrics(self.font()).elidedText(self.full_text, self.mode, max(1, self.width()))
        if shown != self.text():
            self.setText(shown)
        self.setToolTip(self.full_text if shown != self.full_text else "")

    def is_elided(self) -> bool:
        return bool(self.full_text) and self.text() != self.full_text

    def enterEvent(self, event) -> None:  # noqa: N802
        # 省略了就一移上来立刻贴着这一行显示全文（Qt 自己的悬停提示要停 0.7 秒，用户以为没有）
        super().enterEvent(event)
        if self.is_elided():
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.full_text, self)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        if self.is_elided():
            QToolTip.hideText()

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(min(hint.width(), QFontMetrics(self.font()).horizontalAdvance(self.full_text) + 2),
                     hint.height())


class _MetaChip(QWidget):
    """次要信息里的一项：小图标 + 值（模型 / 思考强度 / 持续）。标题只在悬停提示和无障碍名字里。"""

    def __init__(self, key: str, px, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.caption = t(f"session_card.caption.{key}")
        self.icon = QLabel(self)
        self.icon.setFixedSize(px(11), px(11))
        self.value = QLabel("", self)
        self.value.setObjectName("session-card-meta")
        self.value.setTextFormat(Qt.TextFormat.PlainText)        # 模型名是外来内容
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(4))
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.value, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_value(self, text: str) -> None:
        self.value.setText(text)
        self.setToolTip(f"{self.caption}: {text}")
        self.setAccessibleName(f"{self.caption}: {text}")
        self.setVisible(bool(text))


class _InfoRow(QWidget):
    """一行「图标 + 文字 + 灰色补充」：工作区、文件夹、分支。文字单行，放不下就省略。"""

    def __init__(self, key: str, px, *, mono: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.icon = QLabel(self)
        self.icon.setFixedSize(px(14), px(14))
        self.text = _Elided(Qt.TextElideMode.ElideMiddle, self)
        self.text.setObjectName("session-card-mono" if mono else "session-card-info")
        self.sub = QLabel("", self)
        self.sub.setObjectName("session-card-info-sub")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(8))
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.text, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.sub, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_text(self, text: str, sub: str = "", tip: str = "") -> None:
        self.text.set_full_text(text)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.setToolTip(tip)
        self.setAccessibleName(f"{tip}: {text}" if tip else text)
        self.setVisible(bool(text))


class _ValueLabel(QLabel):
    """路径 / 分支的全文（等宽、可拖选）。``full_text`` 与省略的那几行同名，调用方不用分。"""

    @property
    def full_text(self) -> str:
        return self.text()


class _SideScroll(QScrollArea):
    """只能左右滑的一行：滚轮上下滚也当左右滑；一换内容先停在最右端（最后一层目录 / 分支名最能
    认出是哪个），用户自己滑过之后就不再拽回去。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.stick_to_end = True
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(False)
        self.viewport().setAutoFillBackground(False)
        bar = self.horizontalScrollBar()
        bar.actionTriggered.connect(self._released)          # 拖滚动条 / 点滚动条
        bar.rangeChanged.connect(self._follow_end)

    def _released(self, _action=None) -> None:
        self.stick_to_end = False

    def _follow_end(self, _low=0, high=0) -> None:
        if self.stick_to_end:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().maximum())

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta()
        step = delta.x() or delta.y()
        bar = self.horizontalScrollBar()
        if bar.maximum() <= 0 or not step:
            event.ignore()
            return
        self.stick_to_end = False
        bar.setValue(bar.value() - step // 2)                # 一格 120 → 滑 60 px
        event.accept()


class _ValueRow(QWidget):
    """路径 / 分支那一行：图标 + 可左右滑动的全文 + 复制按钮。

    2026-10-28 用户看实机后要的：省略了看不全、也没法复制。现在放不下不省略，用滚轮或底下那根细
    滚动条左右滑；字可以拖选；右边的按钮直接复制整个值（``copied`` 发出行的种类，卡片说一句）。"""

    copied = Signal(str)

    def __init__(self, key: str, px, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self._bar = max(3, px(4))
        self.icon = QLabel(self)
        self.icon.setFixedSize(px(14), px(14))
        self.scroll = _SideScroll(self)
        self.scroll.setObjectName("session-card-scroll")
        self.text = _ValueLabel(self.scroll)
        self.text.setObjectName("session-card-mono")
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.scroll.setWidget(self.text)
        self.copy_btn = QPushButton("", self)
        self.copy_btn.setObjectName("session-card-copy")
        self.copy_btn.setFixedSize(px(26), px(26))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip(t(f"session_card.copy_{key}"))
        self.copy_btn.setAccessibleName(t(f"session_card.copy_{key}"))
        self.copy_btn.clicked.connect(self._copy)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(8))
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.scroll, 1, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignTop)

    def set_text(self, text: str, sub: str = "", tip: str = "") -> None:
        del sub
        self.text.setText(text)
        self.text.ensurePolished()
        self.text.adjustSize()
        # 留出滚动条的高度：滚动条出不出现，这一行都不跳
        self.scroll.setFixedHeight(self.text.height() + self._bar + 1)
        self.scroll.stick_to_end = True
        self.scroll._follow_end()
        self.icon.setToolTip(tip)
        self.setAccessibleName(f"{tip}: {text}" if tip else text)
        self.setVisible(bool(text))

    def overflows(self) -> bool:
        return self.scroll.horizontalScrollBar().maximum() > 0

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.text())
        self.copied.emit(self.key)


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

    方角、平铺、无阴影。从上到下按重要程度排：

    - 页头一条强调色的带子：**在哪打开的**（那个程序自己的图标，放在一块白色小方磁贴上，
      旁边写「Claude 桌面版」「VS Code 插件」「终端 · WSL」）+ 大而轻的**标题**；
    - 状态（阶段小磁贴 + 阶段名），下面一行灰色小字的次要信息：模型、思考强度、持续多久；
    - 上下文用量（数字 + 平条）；**最近的问题**；
    - **工作区 / 目录 / 分支**几行，目录和分支用等宽字、放不下省中间；
    - 一个强调色的「跳到对话」主按钮，旁边两个方形图标按钮（打开文件夹、复制恢复命令）。

    颜色全部取自 ``session_card_themes`` 里选的方案；字号由「详情卡文字大小」那一项决定。
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
        # 卡片不在前台时（刚弹出、焦点还在别的程序上）Qt 默认不弹悬停提示：路径 / 分支的全文靠它
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._scale = _card_scale(config)
        self._theme_id = ""
        self._theme = session_card_themes.card_theme(None)
        self._phase = ""
        self._host = ""
        self._anchor = None
        self._deactivate_check_pending = False
        self.key: tuple[str, str] | None = None
        # 字体都只点一个族（ui_fonts 的约束：给 Qt 一串族名，它会把整个字体库映射进进程）：
        # 正文微软雅黑 UI（Metro 那一代的中文界面字），标题它的细体，路径 / 分支等宽字
        font = QFont()
        if ui_fonts.metro_font_family():
            font.setFamily(ui_fonts.metro_font_family())
        font.setPixelSize(self._px(13))
        self.setFont(font)                 # 子控件都继承它；样式表只改个别几处的字号和粗细
        self._build()
        self.apply_theme(_configured_theme_id(config))

    @property
    def scale(self) -> float:
        return self._scale

    def _px(self, value: float) -> int:
        return int(round(value * self._scale))

    def _dpr(self) -> float:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return max(float(self.devicePixelRatioF() or 1.0), float(screen.devicePixelRatio()) if screen else 1.0)

    def _text_width(self) -> int:
        """正文区的宽度（卡片宽 − 1px 边 × 2 − 左右内边距）。"""
        return self.width() - 2 - 2 * self._px(16)

    # ------------------------------------------------------------ 搭界面
    def _build(self) -> None:
        px = self._px
        width = px(340)
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
        head.setContentsMargins(px(16), px(10), px(6), px(12))
        head.setSpacing(px(6))
        top = QHBoxLayout()
        top.setSpacing(px(8))
        self.host_tile = QLabel(self.header)
        self.host_tile.setObjectName("session-card-host")
        self.host_tile.setFixedSize(px(22), px(22))
        self.host_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.host_tile, 0, Qt.AlignmentFlag.AlignVCenter)
        self.app_label = QLabel("", self.header)
        self.app_label.setObjectName("session-card-app")
        self.app_label.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(self.app_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = QPushButton("", self.header)
        self.close_btn.setObjectName("session-card-close")
        self.close_btn.setFixedSize(px(26), px(26))
        self.close_btn.setToolTip(t("session_card.close"))
        self.close_btn.setAccessibleName(t("session_card.close"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        top.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(top)
        self.title_label = _Lines(TITLE_LINES, self.header)
        self.title_label.setObjectName("session-card-title")
        head.addWidget(self.title_label)
        outer.addWidget(self.header)

        body = QWidget(self)
        body.setObjectName("session-card-body")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(px(16), px(12), px(16), px(14))
        layout.setSpacing(px(10))
        outer.addWidget(body)

        status = QVBoxLayout()
        status.setSpacing(px(4))
        phase = QHBoxLayout()
        phase.setSpacing(px(8))
        self.status_icon = QLabel(body)
        self.status_icon.setFixedSize(px(16), px(16))
        phase.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_label = _Elided(Qt.TextElideMode.ElideRight, body)
        self.status_label.setObjectName("session-card-status")
        phase.addWidget(self.status_label, 1, Qt.AlignmentFlag.AlignVCenter)
        status.addLayout(phase)
        meta = QHBoxLayout()
        meta.setSpacing(px(12))
        self.meta = {key: _MetaChip(key, px, body) for key in META_KEYS}
        for key in META_KEYS:
            meta.addWidget(self.meta[key])
        meta.addStretch(1)
        status.addLayout(meta)
        layout.addLayout(status)

        self.context_box = QWidget(body)
        context = QVBoxLayout(self.context_box)
        context.setContentsMargins(0, 0, 0, 0)
        context.setSpacing(px(4))
        row = QHBoxLayout()
        self.context_caption = QLabel(t("session_card.caption.context").upper(), self.context_box)
        self.context_caption.setObjectName("session-card-caption")
        self.context_value = QLabel("", self.context_box)
        self.context_value.setObjectName("session-card-context")
        row.addWidget(self.context_caption)
        row.addStretch(1)
        row.addWidget(self.context_value)
        context.addLayout(row)
        self.context_bar = _ContextBar(max(3, px(4)), self.context_box)
        context.addWidget(self.context_bar)
        layout.addWidget(self.context_box)

        prompt = QVBoxLayout()
        prompt.setSpacing(px(3))
        self.prompt_caption = QLabel(t("menu.session.latest_question").upper(), body)
        self.prompt_caption.setObjectName("session-card-caption")
        prompt.addWidget(self.prompt_caption)
        self.prompt_label = _Lines(PROMPT_LINES, body)
        self.prompt_label.setObjectName("session-card-prompt")
        self.prompt_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prompt.addWidget(self.prompt_label)
        layout.addLayout(prompt)

        self.workspace_row = _InfoRow("workspace", px, parent=body)
        layout.addWidget(self.workspace_row)
        # 目录和分支放在同一块磁贴里：每行可左右滑、可拖选、右边一个复制按钮
        self.places = QFrame(body)
        self.places.setObjectName("session-card-places")
        places = QVBoxLayout(self.places)
        places.setContentsMargins(px(10), px(7), px(4), px(5))
        places.setSpacing(px(2))
        self.folder_row = _ValueRow("folder", px, self.places)
        self.branch_row = _ValueRow("branch", px, self.places)
        for row in (self.folder_row, self.branch_row):
            row.copied.connect(self._said_copied)
            places.addWidget(row)
        layout.addWidget(self.places)

        buttons = QHBoxLayout()
        buttons.setSpacing(px(4))
        self.jump_btn = TiltButton(t("menu.session.jump_chat"), body)
        self.jump_btn.setObjectName("session-card-primary")
        self.folder_btn = TiltButton("", body)
        self.copy_btn = TiltButton("", body)
        for button, tip in ((self.folder_btn, t("menu.session.open_folder")),
                            (self.copy_btn, t("menu.session.copy_resume_command"))):
            # 次要动作：方形图标按钮（Metro 应用栏那样），文字在悬停提示和无障碍名字里
            button.setObjectName("session-card-icon-button")
            button.setToolTip(tip)
            button.setFixedSize(px(32), px(32))
        self.jump_btn.clicked.connect(self.jump_requested.emit)
        self.folder_btn.clicked.connect(self.folder_requested.emit)
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        self.jump_btn.setAccessibleName(self.jump_btn.text())
        self.jump_btn.setText(" " + self.jump_btn.text())   # 图标和字之间留一点缝（样式表调不了这个间距）
        self.jump_btn.setMinimumHeight(px(32))
        self.folder_btn.setAccessibleName(t("menu.session.open_folder"))
        self.copy_btn.setAccessibleName(t("menu.session.copy_resume_command"))
        for button in (self.jump_btn, self.folder_btn, self.copy_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(px(14), px(14)))
        buttons.addWidget(self.jump_btn, 1)
        buttons.addWidget(self.folder_btn)
        buttons.addWidget(self.copy_btn)
        layout.addLayout(buttons)

        self.result_label = _Lines(RESULT_LINES, body)
        self.result_label.setObjectName("session-card-result")
        self.result_label.setVisible(False)
        layout.addWidget(self.result_label)

    # ------------------------------------------------------------ 配色
    def apply_theme(self, theme_id) -> None:
        """换配色方案（``session_card_themes`` 里的 id）；与当前相同则什么都不做。

        颜色全部取自方案本身：页头、主按钮、状态磁贴、上下文平条用强调色（``accent`` /
        ``accent_text``），图标按钮用按钮底（``button`` / ``button_text``）——这几对的
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
            QLabel#session-card-host {{ background: #ffffff; }}
            QLabel#session-card-app {{ font-size: {px(12.5)}px; font-weight: 600; }}
            QLabel#session-card-title {{ {_family_css(ui_fonts.metro_font_family(light=True))}font-size: {px(19)}px; }}
            QLabel#session-card-status {{ font-size: {px(13.5)}px; font-weight: 600; }}
            QLabel#session-card-meta {{ color: {c["muted"]}; font-size: {px(11.5)}px; }}
            QLabel#session-card-caption {{
                color: {c["muted"]}; font-size: {px(10)}px; font-weight: 600; letter-spacing: 1px;
            }}
            QLabel#session-card-context, QLabel#session-card-info-sub, QLabel#session-card-result {{
                color: {c["muted"]}; font-size: {px(11.5)}px;
            }}
            QLabel#session-card-info {{ font-size: {px(12.5)}px; }}
            QLabel#session-card-mono {{ {_family_css(ui_fonts.mono_font_family())}font-size: {px(13.5)}px; }}
            QFrame#session-card-places {{ background: {c["button"]}; border: none; }}
            QFrame#session-card-places QLabel {{ color: {c["button_text"]}; }}
            QScrollArea#session-card-scroll {{ background: transparent; border: none; }}
            QScrollArea#session-card-scroll QScrollBar:horizontal {{
                height: {max(3, px(4))}px; background: transparent; border: none; margin: 0;
            }}
            QScrollArea#session-card-scroll QScrollBar::handle:horizontal {{
                background: {c["muted"]}; min-width: {px(24)}px; border: none;
            }}
            QScrollArea#session-card-scroll QScrollBar::handle:horizontal:hover {{ background: {c["accent"]}; }}
            QScrollArea#session-card-scroll QScrollBar::add-line:horizontal,
            QScrollArea#session-card-scroll QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}
            QScrollArea#session-card-scroll QScrollBar::add-page:horizontal,
            QScrollArea#session-card-scroll QScrollBar::sub-page:horizontal {{ background: none; }}
            QToolTip {{
                font-size: {px(13)}px; color: {c["text"]}; background: {c["background"]};
                border: 1px solid {c["border"]}; padding: {px(4)}px {px(6)}px;
            }}
            QPushButton {{
                background: {c["button"]}; color: {c["button_text"]};
                border: 2px solid transparent; border-radius: 0;
                padding: {px(3)}px {px(10)}px;
            }}
            QPushButton:hover {{ border-color: {c["hover"]}; }}
            QPushButton:focus {{ border-color: {c["accent"]}; }}
            QPushButton:disabled {{ color: {c["disabled_text"]}; }}
            QPushButton#session-card-primary {{ background: {c["accent"]}; color: {c["accent_text"]}; }}
            QPushButton#session-card-primary:hover, QPushButton#session-card-primary:focus {{
                border-color: {c["text"]};
            }}
            QPushButton#session-card-icon-button {{ padding: 0; }}
            QPushButton#session-card-close {{ background: transparent; padding: 0; }}
            QPushButton#session-card-close:hover {{ border-color: {c["accent_text"]}; }}
            QPushButton#session-card-copy {{ background: transparent; padding: 0; }}
        """)
        self.context_bar.set_colors(c["button"], c["accent"])
        self._paint_icons()
        self.update()

    def _paint_icons(self) -> None:
        c = self._theme
        for chip in self.meta.values():
            chip.icon.setPixmap(card_icon(chip.icon, chip.key, c["muted"], self._px(11)))
        self.workspace_row.icon.setPixmap(card_icon(self.workspace_row.icon, "workspace", c["muted"], self._px(14)))
        for row in (self.folder_row, self.branch_row):
            row.icon.setPixmap(card_icon(row.icon, row.key, c["button_text"], self._px(14)))
            row.copy_btn.setIcon(QIcon(card_icon(row.copy_btn, "copy", c["button_text"], self._px(13))))
            row.copy_btn.setIconSize(QSize(self._px(13), self._px(13)))
        icon_px = self._px(14)
        for button, name, color in ((self.jump_btn, "jump", c["accent_text"]),
                                    (self.folder_btn, "folder", c["button_text"]),
                                    (self.copy_btn, "resume", c["button_text"])):
            icon = QIcon(card_icon(button, name, color, icon_px))
            icon.addPixmap(card_icon(button, name, c["disabled_text"], icon_px), QIcon.Mode.Disabled)
            button.setIcon(icon)
        self.close_btn.setIcon(QIcon(card_icon(self.close_btn, "close", c["accent_text"], icon_px)))
        self.close_btn.setIconSize(QSize(icon_px, icon_px))
        self.status_icon.setPixmap(phase_badge(self._phase, c["accent"], c["accent_text"], self._px(16), self._dpr()))

    def _paint_host(self) -> None:
        """页头左边那块白色小磁贴：这个会话所在程序自己的图标（取不到就是单色记号）。"""
        from .host_icons import host_icon

        size = self._px(16)
        icon = host_icon(self.host_tile, self._host, size) if self._host else QIcon()
        self.host_tile.setPixmap(icon.pixmap(QSize(size, size)) if not icon.isNull() else QPixmap())
        self.host_tile.setVisible(not icon.isNull())

    # ------------------------------------------------------------ 内容
    def show_detail(self, detail: SessionDetail, since: float | None, *,
                    loading: bool = False, now: float | None = None) -> None:
        width = self._text_width()
        where = detail.entry_text
        self.app_label.setText(where or "Claude Code")
        self.app_label.setToolTip(t("session_card.caption.where") + ": " + (where or "Claude Code"))
        if detail.host != self._host or self.host_tile.pixmap().isNull():
            self._host = detail.host
            self._paint_host()
        self.title_label.set_full_text(claude_hooks.session_label(detail.agent, {
            "title": detail.title, "project": detail.project, "sessionId": detail.session_id}),
            width + self._px(10))
        self._phase = detail.phase
        self.status_label.set_full_text(phase_line(detail))
        c = self._theme
        self.status_icon.setPixmap(phase_badge(self._phase, c["accent"], c["accent_text"], self._px(16), self._dpr()))
        self.status_icon.setVisible(bool(self.status_label.full_text))

        model = claude_session_info.model_label(detail.model)
        self.meta["model"].set_value(model)
        self.meta["effort"].set_value(detail.effort if model else "")
        self.meta["time"].set_value(elapsed_text((now or time.time()) - since) if since else "")

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
        self.prompt_label.set_full_text(prompt, width)

        self.workspace_row.set_text(*workspace_text(detail))
        self.folder_row.set_text(detail.cwd, "", t("session_card.folder_tip"))
        branch = detail.git_branch if detail.git_branch != "HEAD" else ""
        self.branch_row.set_text(branch, "", t("session_card.branch_tip"))
        self.places.setVisible(bool(detail.cwd or branch))
        self.setAccessibleDescription(where_line(detail))
        self.folder_btn.setEnabled(bool(detail.cwd))
        self.adjustSize()
        self._reposition()

    def _said_copied(self, key: str) -> None:
        self.show_result(t(f"session_card.copied_{key}"))

    def show_result(self, message: str) -> None:
        self.result_label.set_full_text(message, self._text_width())
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
        QTimer.singleShot(_ICON_WARM_DELAY_MS, self, self._warm_host_icons)

    def _warm_host_icons(self) -> None:
        """详情卡页头那块程序图标第一次要外壳解包（Claude 桌面版的实测 360 ms）：启动稳定后按
        详情卡的尺寸先取好，别卡第一次点小鱼。岛上已经按同样尺寸取过的不再取。"""
        from .host_icons import warm

        probe = QWidget()
        try:
            warm(probe, int(round(16 * _card_scale(self._shell._config))))
        except Exception:  # noqa: BLE001 - 预热失败没关系，用到时再取
            log.debug("预热来源图标失败", exc_info=True)
        finally:
            probe.deleteLater()

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
        if (self._card is not None and shiboken6.isValid(self._card)
                and self._card.scale != _card_scale(self._shell._config)):
            self.close()                # 菜单里改了文字大小：卡片按新字号重搭
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
    size_menu = add_submenu(settings, t("menu.session.detail_card_text_size"))
    current_size = _configured_text_size(facade.cfg)
    for size, label in session_card_themes.text_size_choices():
        item = size_menu.addAction(label)
        item.setCheckable(True)
        item.setChecked(size == current_size)
        item.triggered.connect(lambda _checked=False, n=size: facade.set_session_card_text_size(n))
    install_modern_check_indicators(menu)
    install_responsive_menu_style(menu)
    return menu
