# -*- coding: utf-8 -*-
"""近 7 天仪表盘的窗口：Windows Phone / Metro 的四张实色磁贴（纯界面）。

数据、文字与摆放都由 ``usage_dashboard`` 给好（``set_content``），这里只管画：

- 页面底色、小字的应用名、大而轻的页头，跟设置页同一套令牌（``METRO_TOKENS``），
  白天 / 黑夜跟「外观」里的主题（``apply_theme``）；
- 每张磁贴一块实色、方角、无描边无阴影：左上小标题，大号细体数字（今天），一行副标题
  （7 天合计 / 平均），底下 7 根柱子（最右是今天，实白；以前的天半透明白）。「上下班」是
  悬浮的区间柱，纵轴从上到下是一天里的钟点，右侧标出上下沿；
- 悬停一根柱子弹出那天的确切数字（``QToolTip``）。

无边框置顶的工具窗：点别处（窗口失去激活）、按 Esc 或点右上角 × 收起。开着时每分钟发一次
``refresh_requested``。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QToolTip, QVBoxLayout, QWidget

from .i18n import t
from .settings_theme_qss import METRO_TOKENS
from .settings_widgets import TiltButton, _system_dark
from .usage_dashboard import Bar, Tile

TILE_W, TILE_H = 236, 200
TILE_GAP = 8
_PAD = 14
_FAMILIES = ["Segoe UI", "SF Pro Text", "PingFang SC", "Microsoft YaHei UI"]
_REFRESH_MS = 60_000


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(_FAMILIES)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def resolve_dark(theme: str) -> bool:
    """``system`` 跟随系统；别的按字面（和简报窗口同一口径）。"""
    return theme == "dark" or (theme != "light" and _system_dark())


class MetricTile(QWidget):
    """一张磁贴。``set_tile`` 换内容；悬停的柱子高亮并弹出那天的数字。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(TILE_W, TILE_H)
        self.setMouseTracking(True)
        self.tile: Tile | None = None
        self.hover: int | None = None

    def set_tile(self, tile: Tile) -> None:
        self.tile = tile
        self.setAccessibleName(f"{tile.title}: {tile.value}")
        self.setAccessibleDescription(tile.sub)
        self.update()

    # 柱子区域：上沿在副标题下面，下沿给星期留一行
    def _chart_rect(self) -> QRectF:
        right = self.width() - _PAD - (34 if self.tile is not None and self.tile.kind == "ranges" else 0)
        return QRectF(_PAD, 104, right - _PAD, self.height() - 104 - 26)

    def bar_rects(self) -> list[QRectF]:
        """每根柱子所在的那一列（悬停判定用整列，比柱子本身大）。"""
        if self.tile is None or not self.tile.bars:
            return []
        chart = self._chart_rect()
        width = chart.width() / len(self.tile.bars)
        return [QRectF(chart.left() + i * width, chart.top(), width, chart.height() + 18)
                for i in range(len(self.tile.bars))]

    def _bar_at(self, pos) -> int | None:
        for index, rect in enumerate(self.bar_rects()):
            if rect.contains(pos):
                return index
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._bar_at(event.position())
        if index != self.hover:
            self.hover = index
            self.update()
            if index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPosition().toPoint(), self.tile.bars[index].tip, self)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        tile = self.tile
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tile.color if tile is not None else "#555555"))
        if tile is None:
            return
        white = QColor(255, 255, 255)
        painter.setPen(white)
        inner = self.width() - 2 * _PAD
        for font, text, top, height in ((_font(15, QFont.Weight.DemiBold), tile.title, 10, 22),
                                         (_font(34, QFont.Weight.Light), tile.value, 30, 46),
                                         (_font(12), tile.sub, 76, 18)):
            painter.setFont(font)
            elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, inner)
            painter.drawText(QRectF(_PAD, top, inner, height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             elided)
        chart = self._chart_rect()
        columns = self.bar_rects()
        if tile.kind == "ranges":
            self._paint_ranges(painter, tile, chart, columns)
        else:
            self._paint_bars(painter, tile, chart, columns)
        painter.setFont(_font(11))
        for index, (bar, column) in enumerate(zip(tile.bars, columns)):
            font = _font(11, QFont.Weight.Bold if bar.today else QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(white)
            painter.drawText(QRectF(column.left(), chart.bottom() + 4, column.width(), 16), Qt.AlignmentFlag.AlignCenter,
                             bar.label)

    def _bar_color(self, bar: Bar, index: int) -> QColor:
        alpha = 255 if bar.today or index == self.hover else 140
        return QColor(255, 255, 255, alpha)

    @staticmethod
    def _bar_x(column: QRectF) -> tuple[float, float]:
        width = max(6.0, column.width() - 10)
        return column.center().x() - width / 2, width

    def _paint_bars(self, painter: QPainter, tile: Tile, chart: QRectF, columns: list[QRectF]) -> None:
        peak = max((bar.value for bar in tile.bars), default=0.0)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (bar, column) in enumerate(zip(tile.bars, columns)):
            x, width = self._bar_x(column)
            if bar.value <= 0 or peak <= 0:
                painter.setBrush(QColor(255, 255, 255, 70))      # 没有：贴底一道细线
                painter.drawRect(QRectF(x, chart.bottom() - 2, width, 2))
                continue
            height = max(3.0, chart.height() * bar.value / peak)
            painter.setBrush(self._bar_color(bar, index))
            painter.drawRect(QRectF(x, chart.bottom() - height, width, height))

    def _paint_ranges(self, painter: QPainter, tile: Tile, chart: QRectF, columns: list[QRectF]) -> None:
        top, bottom = tile.span
        scale = chart.height() / max(1e-6, bottom - top)
        painter.setPen(QColor(255, 255, 255, 60))
        painter.drawLine(chart.topLeft(), chart.topRight())
        painter.drawLine(chart.bottomLeft(), chart.bottomRight())
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(_font(10))
        for text, y in ((tile.axis[0], chart.top()), (tile.axis[1], chart.bottom())):
            painter.drawText(QRectF(chart.right() + 4, y - 8, 34, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (bar, column) in enumerate(zip(tile.bars, columns)):
            if bar.low is None or bar.high is None:
                continue
            x, width = self._bar_x(column)
            y1 = chart.top() + (bar.low - top) * scale
            y2 = chart.top() + (bar.high - top) * scale
            painter.setBrush(self._bar_color(bar, index))
            painter.drawRect(QRectF(x, y1, width, max(3.0, y2 - y1)))


class UsageDashboardWindow(QWidget):
    """仪表盘窗口：页头 + 2×2 磁贴 + 一行口径说明。"""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("usageDashboard")
        self.setWindowTitle(t("dashboard.title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.app_label = QLabel(t("dashboard.app"), self)
        self.app_label.setObjectName("dashboardApp")
        self.title_label = QLabel(t("dashboard.title"), self)
        self.title_label.setObjectName("dashboardTitle")
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("dashboardStatus")
        self.close_btn = TiltButton("×", self)
        self.close_btn.setObjectName("dashboardClose")
        self.close_btn.setAccessibleName(t("dashboard.close"))
        self.close_btn.setToolTip(t("dashboard.close"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        self.tiles = [MetricTile(self) for _ in range(4)]
        self.footer_label = QLabel("", self)
        self.footer_label.setObjectName("dashboardFooter")
        self.footer_label.setWordWrap(True)
        self.footer_label.setFixedWidth(2 * TILE_W + TILE_GAP)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.app_label)
        names.addWidget(self.title_label)
        head.addLayout(names)
        head.addStretch(1)
        head.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        grid = QGridLayout()
        grid.setSpacing(TILE_GAP)
        for index, tile in enumerate(self.tiles):
            grid.addWidget(tile, index // 2, index % 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(grid)
        layout.addWidget(self.footer_label)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh_requested)
        self.colors = METRO_TOKENS["light"]
        self.apply_theme("system")

    def apply_theme(self, theme: str) -> None:
        self.colors = colors = METRO_TOKENS["dark" if resolve_dark(theme) else "light"]
        # 先清空再设：窗口还没显示过时，第二次 setStyleSheet 的底色不生效（Qt 6 实测，
        # 普通 QWidget 也一样），构造时已经按 system 设过一次
        self.setStyleSheet("")
        self.setStyleSheet(f"""
            QWidget#usageDashboard {{ background: {colors['page']}; }}
            QLabel#dashboardApp {{ color: {colors['muted']}; font-size: 12px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#dashboardTitle {{ color: {colors['title']}; font-size: 28px; font-weight: 300; }}
            QLabel#dashboardStatus, QLabel#dashboardFooter {{ color: {colors['muted']}; font-size: 11px; }}
            QPushButton#dashboardClose {{
                background: transparent; color: {colors['text']}; border: 2px solid transparent; border-radius: 0;
                font-size: 16px; min-width: 28px; min-height: 26px; padding: 0 4px;
            }}
            QPushButton#dashboardClose:hover {{ border-color: {colors['outline']}; }}
            QPushButton#dashboardClose:focus {{ border-color: {colors['accent']}; }}
        """)

    def set_content(self, tiles: list[Tile], footer: str, *, loading: bool = False) -> None:
        for widget, tile in zip(self.tiles, tiles):
            widget.set_tile(tile)
        self.footer_label.setText(footer)
        self.status_label.setText(t("dashboard.loading") if loading else "")

    # ------------------------------------------------------------ 收起
    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        QToolTip.hideText()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        # 点了别处（别的应用、桌面）：窗口失去激活就收起。岛本身不抢焦点，点它不会走到这里
        if event.type() == QEvent.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
