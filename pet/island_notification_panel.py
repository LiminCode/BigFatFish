# -*- coding: utf-8 -*-
"""灵动岛卡片里的「通知」折叠框（纯界面；数据与跳转见 ``notification_service``）。

样子和「最近的对话」同一套（Windows Phone 式平铺卡片）：表头一块方角卡片，每条通知一块卡片，
卡片之间 2px 的缝。一行三层：左边是发通知的应用自己的图标（Slack 的 logo，由服务读出来的 PNG
字节），右边第一行是频道 / 对方的名字 + 多久以前，下面两行是「发送人: 消息」按宽度折好、折到
第二行末尾还放不下就省略，全文在悬停提示里。没看过的卡片左缘一道主题色竖条；已经不在 Windows
通知中心里的（用户在那边划掉了、或者跳过一次了）名字用次要色，提示它只能打开应用、跳不回原消息。

点一行 = 跳到那条消息；右键 = 跳 / 移除 / 清空。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .i18n import t
from .island_history_panel import _font, style_island_menu, tile_colors

ROW_HEIGHT = 58          # 56 的卡片 + 2 的缝
_ROW_GAP = 2
MAX_VISIBLE_ROWS = 6
_HEADER_HEIGHT = 28
_ROW_PAD_X = 8
_ICON_PX = 20
_ICON_SLOT = 26
_UNREAD_BAR_PX = 3
_SCROLLBAR_PX = 6
_TITLE_PX, _SMALL_PX = 12, 10
_BODY_LINES = 2
_STATUS_MS = 4000
_MENU = (("open", "notices.menu.open"), None, ("dismiss", "notices.menu.dismiss"), ("clear", "notices.menu.clear"))


def body_lines(text: str, font, width: int, max_lines: int = _BODY_LINES) -> list[str]:
    """正文按宽度折成最多 ``max_lines`` 行（按字折，CJK 没空格也行）；放不下的末尾省略。"""
    metrics = QFontMetrics(font)
    text = " ".join(str(text or "").split())
    lines: list[str] = []
    while text and len(lines) < max_lines:
        if len(lines) == max_lines - 1 or metrics.horizontalAdvance(text) <= width:
            lines.append(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))
            break
        cut = len(text)
        while cut > 1 and metrics.horizontalAdvance(text[:cut]) > width:
            cut -= max(1, cut // 8)
        while cut < len(text) and metrics.horizontalAdvance(text[:cut + 1]) <= width:
            cut += 1
        space = text.rfind(" ", max(1, cut - 16), cut)
        if space > 0:
            cut = space
        lines.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return lines


class _NoticeRow(QFrame):
    """一条通知（一块卡片）。左键 = ``clicked``，右键 = ``menu_requested``。"""

    clicked = Signal(object)
    menu_requested = Signal(object, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.key = None
        self._press: QPoint | None = None
        self.setObjectName("noticeRow")
        self.setFixedHeight(ROW_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, _ROW_GAP)
        outer.setSpacing(0)
        self.tile = QFrame(self)
        self.tile.setObjectName("noticeTile")
        self.tile.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        outer.addWidget(self.tile)
        grid = QGridLayout(self.tile)
        grid.setContentsMargins(_ROW_PAD_X, 4, _ROW_PAD_X, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        self.icon = QLabel(self.tile)
        self.icon.setFixedSize(_ICON_SLOT, ROW_HEIGHT - _ROW_GAP - 8)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title, self.ago, self.body = QLabel(self.tile), QLabel(self.tile), QLabel(self.tile)
        self.ago.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for label in (self.icon, self.title, self.ago, self.body):
            label.setTextFormat(Qt.TextFormat.PlainText)      # 全是外来内容：不当富文本
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title.setFont(_font(self.font(), _TITLE_PX, bold=True))
        self.ago.setFont(_font(self.font(), _SMALL_PX))
        self.body.setFont(_font(self.font(), _SMALL_PX))
        grid.addWidget(self.icon, 0, 0, 2, 1)
        grid.addWidget(self.title, 0, 1)
        grid.addWidget(self.ago, 0, 2)
        grid.addWidget(self.body, 1, 1, 1, 2)
        grid.setColumnStretch(1, 1)

    def set_data(self, row: dict, width: int, *, primary: str, secondary: str, logo: QPixmap | None) -> None:
        self.key = row.get("key")
        inner = max(40, width - 2 * _ROW_PAD_X - _ICON_SLOT - 6)
        ago = str(row.get("ago") or "")
        ago_width = QFontMetrics(self.ago.font()).horizontalAdvance(ago) + 2
        self.ago.setText(ago)
        self.ago.setFixedWidth(ago_width)
        title = str(row.get("title") or row.get("app") or "")
        self.title.setText(QFontMetrics(self.title.font()).elidedText(
            title, Qt.TextElideMode.ElideRight, max(20, inner - ago_width - 8)))
        self.title.setStyleSheet(f"color: {primary if row.get('in_center', True) else secondary};")
        sender, message = str(row.get("sender") or ""), str(row.get("message") or "")
        text = f"{sender}: {message}" if sender else message
        self.body.setText("\n".join(body_lines(text, self.body.font(), inner)))
        self.setToolTip(f"{title}\n{text}" if title else text)
        if logo is not None and not logo.isNull():
            self.icon.setPixmap(logo)
        else:
            self.icon.setText("●")
        self.tile.setProperty("unread", bool(row.get("unread")))
        self.tile.style().unpolish(self.tile)
        self.tile.style().polish(self.tile)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press = event.position().toPoint()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        press, self._press = self._press, None
        event.accept()
        if press is None or not self.rect().contains(event.position().toPoint()):
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.key, event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)


class NotificationPanel(QWidget):
    """「通知」折叠框。"""

    toggled = Signal(bool)
    activated = Signal(object)
    action_requested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._row_widgets: list[_NoticeRow] = []
        self._open = True
        self._max_visible = MAX_VISIBLE_ROWS
        self._width = 300
        self._colors = {"primary": "#e5eaf5", "secondary": "#a0aabe", "accent": "#40b8ff"}
        self._menu_appearance: dict = {}
        self._logo_bytes: dict[str, bytes] = {}
        self._logo_pixmaps: dict[tuple[str, float], QPixmap] = {}
        self._menu: QMenu | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_ROW_GAP)
        self.header = QPushButton(self)
        self.header.setObjectName("noticeHeader")
        self.header.setFixedHeight(_HEADER_HEIGHT)
        self.header.setFont(_font(self.font(), 11, bold=True))
        self.header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header.setAutoDefault(False)
        self.header.clicked.connect(self._on_header_clicked)
        layout.addWidget(self.header)
        self.body = QScrollArea(self)
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setWidgetResizable(True)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.viewport().setAutoFillBackground(False)
        self._list = QWidget(self.body)
        self._list.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)
        self.body.setWidget(self._list)
        self.body.hide()
        layout.addWidget(self.body)
        self._status = ""
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(_STATUS_MS)
        self._status_timer.timeout.connect(self._clear_status)
        self._restyle()

    # ---------------------------------------------------------------- 外观
    def set_look(self, *, primary: str, secondary: str, accent: str, width: int,
                 menu_appearance: dict | None = None) -> None:
        if menu_appearance is not None:
            self._menu_appearance = dict(menu_appearance)
        colors = {"primary": primary, "secondary": secondary, "accent": accent}
        if colors == self._colors and int(width) == self._width:
            return
        self._colors, self._width = colors, int(width)
        self._restyle()
        self._refill()

    def _restyle(self) -> None:
        c = self._colors
        tile, hover = tile_colors(c["primary"])
        self.setStyleSheet(
            f"QPushButton#noticeHeader {{ color: {c['primary']}; background: {tile}; border: none;"
            f" border-radius: 0; text-align: left; padding: 0 {_ROW_PAD_X}px; }}"
            f"QPushButton#noticeHeader:hover {{ background: {hover}; }}"
            f"QFrame#noticeRow {{ background: transparent; border: none; }}"
            f"QFrame#noticeTile {{ background: {tile}; border: none; border-radius: 0;"
            f" border-left: {_UNREAD_BAR_PX}px solid transparent; }}"
            f"QFrame#noticeTile:hover {{ background: {hover}; }}"
            f"QFrame#noticeTile[unread=\"true\"] {{ border-left: {_UNREAD_BAR_PX}px solid {c['accent']}; }}"
            f"QFrame#noticeTile QLabel {{ color: {c['secondary']}; background: transparent; }}"
            f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}"
            f"QScrollBar:vertical {{ background: transparent; width: {_SCROLLBAR_PX}px; margin: 2px 0; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(128, 128, 128, 120); border-radius: 0;"
            f" min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")

    # ---------------------------------------------------------------- 数据
    def row_widgets(self) -> list[_NoticeRow]:
        return list(self._row_widgets)

    def set_logos(self, logos: dict[str, bytes]) -> None:
        """应用 id → 图标 PNG 字节（服务读出来的）。"""
        logos = {k: v for k, v in dict(logos or {}).items() if v}
        if logos == self._logo_bytes:
            return
        self._logo_bytes = logos
        self._logo_pixmaps.clear()
        self._refill()

    def _logo(self, app_id: str) -> QPixmap | None:
        data = self._logo_bytes.get(app_id)
        if not data:
            return None
        dpr = float(self.devicePixelRatioF() or 1.0)
        key = (app_id, dpr)
        pixmap = self._logo_pixmaps.get(key)
        if pixmap is None:
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(round(_ICON_PX * dpr), round(_ICON_PX * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                pixmap.setDevicePixelRatio(dpr)
            self._logo_pixmaps[key] = pixmap
        return pixmap if not pixmap.isNull() else None

    def set_rows(self, rows) -> None:
        rows = [dict(row) for row in rows or []]
        if rows == self._rows:
            return
        self._rows = rows
        while len(self._row_widgets) > len(rows):
            widget = self._row_widgets.pop()
            self._list_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        while len(self._row_widgets) < len(rows):
            widget = _NoticeRow(self._list)
            widget.clicked.connect(self.activated)
            widget.menu_requested.connect(lambda key, pos: self.popup_row_menu(key, pos))
            self._list_layout.insertWidget(len(self._row_widgets), widget)
            self._row_widgets.append(widget)
        self._refill()

    def set_max_visible(self, count) -> None:
        try:
            count = max(1, int(count))
        except (TypeError, ValueError):
            count = MAX_VISIBLE_ROWS
        if count != self._max_visible:
            self._max_visible = count
            self._refill()

    def _refill(self) -> None:
        scroll = len(self._rows) > self._max_visible
        width = self._width - (_SCROLLBAR_PX + 2 if scroll else 0)
        for widget, row in zip(self._row_widgets, self._rows):
            widget.set_data(row, width, primary=self._colors["primary"], secondary=self._colors["secondary"],
                            logo=self._logo(str(row.get("app_id") or "")))
        self.body.setFixedHeight(min(len(self._rows), self._max_visible) * ROW_HEIGHT)
        self.body.setVisible(self._open and bool(self._rows))
        self._update_header()
        self.updateGeometry()

    def _update_header(self) -> None:
        if self._status:
            text = self._status
        else:
            text = t("notices.header.open" if self._open else "notices.header.closed", n=len(self._rows))
        self.header_text = text
        self.header.setToolTip(text)
        self.header.setText(QFontMetrics(self.header.font()).elidedText(
            text, Qt.TextElideMode.ElideRight, max(40, self._width - 2 * _ROW_PAD_X - 4)))

    def retranslate(self) -> None:
        self._refill()

    # ---------------------------------------------------------------- 折叠
    def is_open(self) -> bool:
        return self._open

    def set_open(self, is_open: bool) -> None:
        self._open = bool(is_open)
        self.body.setVisible(self._open and bool(self._rows))
        self._update_header()
        self.updateGeometry()

    def _on_header_clicked(self) -> None:
        self.set_open(not self._open)
        self.toggled.emit(self._open)

    # ---------------------------------------------------------------- 状态行
    def show_status(self, text: str) -> None:
        self._status = str(text or "")
        self._update_header()
        if self._status:
            self._status_timer.start()

    def _clear_status(self) -> None:
        self._status = ""
        self._update_header()

    # ---------------------------------------------------------------- 右键菜单
    def row_menu(self, key) -> QMenu:
        menu = QMenu(self)
        for item in _MENU:
            if item is None:
                menu.addSeparator()
                continue
            name, text_key = item
            menu.addAction(t(text_key)).triggered.connect(
                lambda _checked=False, name=name: self.action_requested.emit(name, key))
        style_island_menu(menu, self._colors["primary"], self._menu_appearance)
        return menu

    def popup_row_menu(self, key, pos: QPoint) -> None:
        self._menu = self.row_menu(key)
        self._menu.popup(pos)
