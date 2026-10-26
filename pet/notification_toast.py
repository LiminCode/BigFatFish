# -*- coding: utf-8 -*-
"""我们自己弹的通知：Windows Phone / Metro 风格的卡片，一次叠出好几条（macOS 那样）。

为什么：Windows 一次只弹一条 toast，后面的排队；通知中心里的又要点开才看得到。这里把读到的
（``notification_center.read_toasts``）每条弹成一张卡片，几条同时叠在屏幕一角。

- **摆在哪**：四个角（``corner``）× 哪块屏（``screen``：``primary`` 主屏、``cursor`` 光标所在的屏，
  或者 ``QScreen.name()``，拔掉了就退回主屏）。用屏幕的可用区（让开任务栏）。最新的贴着角，
  旧的往远离角的方向排；放不下或超过 ``max_visible`` 的排队，前面有一张走了就补上。
- **长什么样**：和简报窗口 / 设置页同一套 ``METRO_TOKENS``：方角平铺、无阴影；左边一块强调色的
  方磁贴放应用图标（没有图标就写应用名首字），右边小字大写的应用名 + 时间、标题、两行正文。
  进场像 WP 的 toast 一样绕着靠屏幕边的那条边翻下来；悬停朝光标倾斜（``tilt_transform``）、
  停止倒计时；往屏幕边划走就关掉；点一下发 ``activated``（跳回原应用由调用方做）。
- 每张卡片是一个独立的置顶、不抢焦点的无边框窗口，画在一张缓存的位图上再按动画变换贴出来。

纯函数 ``stack_positions`` / ``resolve_screen`` / ``normalize`` 不碰窗口，测试直接用。
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import (
    Property, QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPixmap, QTextLayout, QTransform,
)
from PySide6.QtWidgets import QWidget

from . import notification_center as nc
from .settings_theme_qss import METRO_TOKENS
from .settings_widgets import _system_dark, tilt_transform

CORNERS = nc.TOAST_CORNERS
SCREEN_PRIMARY = nc.TOAST_SCREEN_PRIMARY
SCREEN_CURSOR = nc.TOAST_SCREEN_CURSOR
THEMES = ("system", "light", "dark")
SECONDS_RANGE = nc.TOAST_SECONDS_RANGE
MAX_VISIBLE_RANGE = nc.TOAST_MAX_RANGE
DEFAULTS = {**nc.TOAST_DEFAULTS, "theme": "system"}

CARD_WIDTH = 360
MARGIN = 16              # 离屏幕可用区边缘
GAP = 8                  # 卡片之间
_PAD = 12
_TILE = 44               # 左边的应用磁贴
_LOGO = 28
_CLOSE = 24
_TEXT_LEFT = _PAD + _TILE + _PAD
_TEXT_WIDTH = CARD_WIDTH - _TEXT_LEFT - _PAD - _CLOSE // 2
_BODY_LINES = 2
_ENTER_MS = 280
_LEAVE_MS = 200
_MOVE_MS = 180
_ENTER_DEG = 75.0        # 进场从这个角度翻下来
_SWIPE_FRACTION = 0.35   # 划过卡宽的这么多就算划走
_CLICK_SLOP = 6
_MAX_PENDING = 50       # 排队最多留这么多（更旧的丢掉）
_TILT = (5.0, 8.0)       # 卡片比设置页的磁贴宽，倾斜小一点
_FONTS = ["Segoe UI", "Microsoft YaHei UI", "PingFang SC", "sans-serif"]


# ---------------------------------------------------------------- 配置
def normalize(raw) -> dict:
    """弹窗设置：``notifications.toast`` 的规则（``notification_center.normalize_toast``）+ 明暗主题。"""
    data = dict(raw) if isinstance(raw, dict) else {}
    theme = str(data.get("theme") or "").strip()
    return {**nc.normalize_toast(data), "theme": theme if theme in THEMES else DEFAULTS["theme"]}


# ---------------------------------------------------------------- 摆放（纯函数）
def stack_positions(area: QRect, corner: str, width: int, heights: list[int], *,
                    margin: int = MARGIN, gap: int = GAP) -> list[QPoint]:
    """``heights``（最新的在前）各自的左上角。最新的贴着角，之后的往远离角的方向排。

    放不下的不给位置（返回的比 ``heights`` 短）；第一张无论多高都给。
    """
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")
    x = area.right() - margin - width + 1 if right else area.left() + margin
    limit_top, limit_bottom = area.top() + margin, area.bottom() - margin
    positions: list[QPoint] = []
    cursor = area.bottom() - margin + 1 if bottom else limit_top
    for height in heights:
        y = cursor - height if bottom else cursor
        if positions and (y < limit_top if bottom else y + height - 1 > limit_bottom):
            break
        positions.append(QPoint(x, y))
        cursor = y - gap if bottom else y + height + gap
    return positions


def resolve_screen(choice: str, screens, *, primary, cursor=None):
    """按设置挑屏：屏幕名 → 那块屏；``cursor`` → 光标所在；其余（含拔掉了的）→ 主屏。"""
    if choice == SCREEN_CURSOR and cursor is not None:
        return cursor
    for screen in screens:
        if screen.name() == choice:
            return screen
    return primary


def screen_label(index: int, screen) -> str:
    """设置里列屏幕用：「2 · G3223Q · 2560×1440」。"""
    size = screen.size()
    model = (screen.model() or screen.manufacturer() or screen.name()).strip()
    return f"{index + 1} · {model} · {size.width()}×{size.height()}"


def wrap_lines(text: str, font: QFont, width: int, max_lines: int) -> list[str]:
    """把一段字按 ``width`` 折行，最多 ``max_lines`` 行，超出的在最后一行末尾省略。"""
    text = " ".join(str(text or "").split())
    if not text or max_lines <= 0:
        return []
    layout = QTextLayout(text, font)
    layout.beginLayout()
    starts: list[int] = []
    end = 0
    while len(starts) < max_lines:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        starts.append(line.textStart())
        end = line.textStart() + line.textLength()
    layout.endLayout()
    lines = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [end])]
    if end < len(text):
        lines[-1] = QFontMetrics(font).elidedText(text[starts[-1]:], Qt.TextElideMode.ElideRight, width)
    return lines


def card_height(notice) -> int:
    """一张卡片多高：标题一行，正文最多两行。"""
    body = len(wrap_lines(getattr(notice, "body", ""), _font(13), _TEXT_WIDTH, _BODY_LINES))
    return max(_PAD + _TILE + _PAD, _PAD + 16 + 4 + 22 + body * 19 + _PAD)


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    font = QFont()
    font.setFamilies(_FONTS)
    font.setPixelSize(px)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def _tokens(theme: str) -> dict:
    dark = theme == "dark" or (theme != "light" and _system_dark())
    return METRO_TOKENS["dark" if dark else "light"]


# ---------------------------------------------------------------- 一张卡片
class ToastCard(QWidget):
    """一条通知。``clicked`` 点了正文；``leaving(reason)`` 开始退场（叠放管理器这时就让出位置）；
    ``finished`` 退场动画走完（之后删掉）。"""

    clicked = Signal()
    leaving_started = Signal(str)
    finished = Signal()

    def __init__(self, notice, *, logo: bytes = b"", corner: str = "top_right", theme: str = "system",
                 seconds: int = DEFAULTS["seconds"], animate: bool = True) -> None:
        super().__init__(None)
        self.notice = notice
        self._corner = corner
        self._animate = animate
        self._tokens = _tokens(theme)
        self._logo = QPixmap()
        if logo:
            self._logo.loadFromData(logo)
        self._swing = 0.0 if animate else 1.0
        self._leave = 0.0
        self._leaving = ""
        self._hovered = False
        self._tilt_pos: QPoint | None = None
        self._press: QPoint | None = None
        self._drag_dx = 0
        self._cache: QPixmap | None = None
        self._move_anim: QPropertyAnimation | None = None
        self._duration_ms = int(seconds) * 1000
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.expire_now)
        self._remaining_ms = self._duration_ms

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(CARD_WIDTH, card_height(notice))

    def close_rect(self) -> QRect:
        return QRect(CARD_WIDTH - _PAD // 2 - _CLOSE, _PAD // 2, _CLOSE, _CLOSE)

    # ------------------------------------------------------------ 计时
    def start_timer(self) -> None:
        if not self._hovered and not self._leaving:
            self._timer.start(max(1, self._remaining_ms))

    def timer_active(self) -> bool:
        return self._timer.isActive()

    def set_hovered(self, hovered: bool) -> None:
        """悬停时停下倒计时（剩下的时间留着），离开后接着倒数。"""
        if hovered == self._hovered:
            return
        self._hovered = hovered
        if hovered:
            if self._timer.isActive():
                self._remaining_ms = max(1500, self._timer.remainingTime())
            self._timer.stop()
        else:
            self._tilt_pos = None
            self.start_timer()
        self.update()

    def expire_now(self) -> None:
        self.dismiss("expired")

    # ------------------------------------------------------------ 动画
    def _get_swing(self) -> float:
        return self._swing

    def _set_swing(self, value: float) -> None:
        self._swing = float(value)
        self.update()

    def _get_leave(self) -> float:
        return self._leave

    def _set_leave(self, value: float) -> None:
        self._leave = float(value)
        self.update()

    swing = Property(float, _get_swing, _set_swing)
    leave = Property(float, _get_leave, _set_leave)

    def _run(self, prop: bytes, start: float, end: float, ms: int, curve, on_done=None) -> None:
        anim = QPropertyAnimation(self, prop, self)
        anim.setDuration(ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(curve)
        if on_done is not None:
            anim.finished.connect(on_done)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def appear_at(self, pos: QPoint) -> None:
        self.move(pos)
        self.show()
        if self._animate:
            self._run(b"swing", 0.0, 1.0, _ENTER_MS, QEasingCurve.Type.OutCubic)
        self.start_timer()

    def move_to(self, pos: QPoint) -> None:
        if pos == self.pos() and self._move_anim is None:
            return
        if self._move_anim is not None:
            self._move_anim.stop()
            self._move_anim = None
        if not self._animate or not self.isVisible():
            self.move(pos)
            return
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(_MOVE_MS)
        anim.setEndValue(pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: setattr(self, "_move_anim", None))
        self._move_anim = anim
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def set_corner(self, corner: str) -> None:
        self._corner = corner

    def leaving(self) -> bool:
        return bool(self._leaving)

    def park(self) -> None:
        """让出位置但不算走（更新的来了、放不下）：藏起来，剩下的时间留着，回来接着倒数。"""
        if self._timer.isActive():
            self._remaining_ms = max(1500, self._timer.remainingTime())
        self._timer.stop()
        self._hovered = False
        self._tilt_pos = None
        self.hide()

    def dismiss(self, reason: str) -> None:
        """退场：往靠近的那条屏幕边滑出、淡掉。开始时发 ``leaving_started``，走完发 ``finished``。"""
        if self._leaving:
            return
        self._leaving = reason
        self._timer.stop()
        self.leaving_started.emit(reason)
        if self._animate and self.isVisible():
            self._run(b"leave", 0.0, 1.0, _LEAVE_MS, QEasingCurve.Type.InCubic, self._finish)
        else:
            self._finish()

    def _finish(self) -> None:
        self.hide()
        self.finished.emit()

    # ------------------------------------------------------------ 鼠标
    def enterEvent(self, event) -> None:  # noqa: N802
        self.set_hovered(True)
        self._tilt_pos = self.mapFromGlobal(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.set_hovered(False)
        super().leaveEvent(event)

    def _edge_sign(self) -> int:
        return 1 if self._corner.endswith("right") else -1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._drag_dx = 0
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._press is not None:
            # 只能往屏幕边那一侧拖（反方向拖不动）
            self._drag_dx = max(0, (pos.x() - self._press.x()) * self._edge_sign()) * self._edge_sign()
        if not self._hovered:
            self.set_hovered(True)
        self._tilt_pos = pos
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return super().mouseReleaseEvent(event)
        pos = event.position().toPoint()
        moved = (pos - self._press).manhattanLength()
        self._press = None
        if abs(self._drag_dx) >= CARD_WIDTH * _SWIPE_FRACTION:
            self.dismiss("swiped")
        elif moved <= _CLICK_SLOP:
            self._drag_dx = 0
            if self.close_rect().contains(pos):
                self.dismiss("closed")
            else:
                self.clicked.emit()
        else:
            self._drag_dx = 0          # 没划够：弹回原位
            self.update()
        return None

    # ------------------------------------------------------------ 画
    def _render(self) -> QPixmap:
        """卡片本身（不带动画变换）画进一张位图，内容不变就复用。"""
        dpr = self.devicePixelRatioF()
        if self._cache is not None and self._cache.devicePixelRatioF() == dpr:
            return self._cache
        tok = self._tokens
        pixmap = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self.width(), self.height())
        p.fillRect(rect, QColor(tok["tile"]))
        p.setPen(QPen(QColor(tok["field_border"]), 1))      # 无阴影：浅色桌面上靠一圈细边分开
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        # 应用磁贴
        tile = QRectF(_PAD, _PAD, _TILE, _TILE)
        p.fillRect(tile, QColor(tok["accent"]))
        if not self._logo.isNull():
            logo = self._logo.scaled(int(_LOGO * dpr), int(_LOGO * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            logo.setDevicePixelRatio(dpr)
            size = logo.deviceIndependentSize()
            p.drawPixmap(QRectF(tile.center().x() - size.width() / 2, tile.center().y() - size.height() / 2,
                                size.width(), size.height()), logo, QRectF(logo.rect()))
        else:
            p.setPen(QColor(tok["selected_text"]))
            p.setFont(_font(20, QFont.Weight.Light))
            p.drawText(tile, Qt.AlignmentFlag.AlignCenter, (self.notice.app or "?").strip()[:1].upper())
        # 文字
        left, width = _TEXT_LEFT, _TEXT_WIDTH
        header = _font(11, QFont.Weight.DemiBold, 1.0)
        p.setFont(header)
        p.setPen(QColor(tok["muted"]))
        when = dt.datetime.fromtimestamp(self.notice.created).strftime("%H:%M") if self.notice.created else ""
        when_w = QFontMetrics(header).horizontalAdvance(when) + 8
        app_name = QFontMetrics(header).elidedText((self.notice.app or "").upper(), Qt.TextElideMode.ElideRight,
                                                   width - when_w)
        p.drawText(QRectF(left, _PAD, width, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{app_name}  ·  {when}" if when else app_name)
        title_font = _font(15, QFont.Weight.DemiBold)
        p.setFont(title_font)
        p.setPen(QColor(tok["title"]))
        title = QFontMetrics(title_font).elidedText(" ".join((self.notice.title or "").split()),
                                                    Qt.TextElideMode.ElideRight, width)
        p.drawText(QRectF(left, _PAD + 20, width, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)
        p.setFont(_font(13))
        p.setPen(QColor(tok["text"]))
        for index, line in enumerate(wrap_lines(self.notice.body, _font(13), width, _BODY_LINES)):
            p.drawText(QRectF(left, _PAD + 42 + index * 19, width, 19),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        p.end()
        self._cache = pixmap
        return pixmap

    def _transform(self) -> QTransform:
        w, h = self.width(), self.height()
        transform = QTransform()
        if self._swing < 1.0:
            # 绕靠屏幕边的那条横边翻进来（WP toast 从顶上翻下来）；远端往屏幕里退，不会画出窗口
            hinge_y = h if self._corner.startswith("bottom") else 0
            angle = (1.0 - self._swing) * _ENTER_DEG * (1 if hinge_y == 0 else -1)
            transform.translate(w / 2, hinge_y)
            transform.rotate(angle, Qt.Axis.XAxis, 1024)
            transform.translate(-w / 2, -hinge_y)
        dx = self._drag_dx + self._leave * w * self._edge_sign()
        if dx:
            transform *= QTransform.fromTranslate(dx, 0)
        if self._hovered and self._tilt_pos is not None and not self._leaving and self._swing >= 1.0:
            transform = tilt_transform(self.rect(), self._tilt_pos, pressed=self._press is not None,
                                       degrees=_TILT) * transform
        return transform

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        opacity = min(1.0, 0.2 + self._swing) * (1.0 - self._leave)
        if self._drag_dx:
            opacity *= 1.0 - min(0.6, abs(self._drag_dx) / CARD_WIDTH)
        p.setOpacity(max(0.0, opacity))
        p.setTransform(self._transform())
        p.drawPixmap(0, 0, self._render())
        if self._hovered and not self._leaving:
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(self._tokens["muted"]), 1.4))
            box = QRectF(self.close_rect()).adjusted(7, 7, -7, -7)
            p.drawLine(box.topLeft(), box.bottomRight())
            p.drawLine(box.topRight(), box.bottomLeft())
        p.end()


# ---------------------------------------------------------------- 叠放
class ToastStack(QObject):
    """管一摞卡片：摆位、排队、补位、换角换屏。

    ``activated(notice)`` 用户点了某条（调用方负责跳回原应用）；``dismissed(notice, reason)``
    一条走了：``activated`` / ``closed`` / ``swiped`` / ``expired`` / ``cleared``。
    """

    activated = Signal(object)
    dismissed = Signal(object, str)

    def __init__(self, *, animate: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._animate = animate
        self._settings = normalize(None)
        self._entries: list[_Entry] = []            # 在场的 + 排队的，最新的在前
        self._seen: set = set()
        self._screen = None
        self._clearing = False

    # ------------------------------------------------------------ 设置
    @property
    def settings(self) -> dict:
        return dict(self._settings)

    def apply_settings(self, raw: dict) -> None:
        self._settings = normalize({**self._settings, **(raw or {})})
        self._screen = None
        for entry in self._entries:
            if entry.card is not None:
                entry.card.set_corner(self._settings["corner"])
        self._reflow()

    def target_screen(self):
        if self._screen is None:
            choice = self._settings["screen"]
            cursor = QGuiApplication.screenAt(QCursor.pos()) if choice == SCREEN_CURSOR else None
            self._screen = resolve_screen(choice, QGuiApplication.screens(),
                                          primary=QGuiApplication.primaryScreen(), cursor=cursor)
        return self._screen

    # ------------------------------------------------------------ 数据
    def visible_cards(self) -> list[ToastCard]:
        return [e.card for e in self._entries if e.card is not None and e.card.isVisible()]

    def queued_count(self) -> int:
        return sum(1 for e in self._entries if e.card is None or not e.card.isVisible())

    def push(self, notice, logo: bytes = b"") -> bool:
        """弹一条；同一 ``uid`` 只弹一次。返回是否收下。最新的总是马上弹出来，放不下的是最旧的。"""
        uid = getattr(notice, "uid", id(notice))
        if uid in self._seen:
            return False
        self._seen.add(uid)
        if not self._entries:
            self._screen = None          # 「光标所在的屏」按一摞开始时算
        self._entries.insert(0, _Entry(notice, logo))
        del self._entries[_MAX_PENDING:]
        self._reflow()
        return True

    def clear(self) -> None:
        self._clearing = True
        try:
            for entry in list(self._entries):
                if entry.card is not None:
                    entry.card.dismiss("cleared")
            self._entries.clear()
        finally:
            self._clearing = False

    # ------------------------------------------------------------ 摆
    def _make_card(self, entry: "_Entry") -> ToastCard:
        s = self._settings
        card = ToastCard(entry.notice, logo=entry.logo, corner=s["corner"], theme=s["theme"],
                         seconds=s["seconds"], animate=self._animate)
        card.clicked.connect(lambda c=card: self._on_clicked(c))
        card.leaving_started.connect(lambda reason, c=card: self._on_leaving(c, reason))
        card.finished.connect(card.deleteLater)
        return card

    def _reflow(self) -> None:
        """前面放得下的（且不超过 ``max_visible``）摆到位，后面的藏起来等位置。"""
        screen = self.target_screen()
        if screen is None:
            return
        head = self._entries[:self._settings["max_visible"]]
        positions = stack_positions(screen.availableGeometry(), self._settings["corner"], CARD_WIDTH,
                                    [card_height(e.notice) for e in head])
        for entry, pos in zip(head, positions):
            if entry.card is None:
                entry.card = self._make_card(entry)
            if entry.card.isVisible():
                entry.card.move_to(pos)
            else:
                entry.card.appear_at(pos)
        for entry in self._entries[len(positions):]:
            if entry.card is not None and entry.card.isVisible():
                entry.card.park()

    def _on_clicked(self, card: ToastCard) -> None:
        if card.leaving():
            return
        self.activated.emit(card.notice)
        card.dismiss("activated")

    def _on_leaving(self, card: ToastCard, reason: str) -> None:
        self._entries = [e for e in self._entries if e.card is not card]
        self.dismissed.emit(card.notice, reason)
        if not self._clearing:
            self._reflow()


class _Entry:
    __slots__ = ("notice", "logo", "card")

    def __init__(self, notice, logo: bytes) -> None:
        self.notice = notice
        self.logo = logo
        self.card: ToastCard | None = None
