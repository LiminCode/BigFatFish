# -*- coding: utf-8 -*-
"""近 7 天仪表盘的窗口：Windows Phone / Metro 的四张实色磁贴（纯界面）。

数据、文字与摆放都由 ``usage_dashboard`` 给好（``set_content``），这里只管画：

- 页面底色、小字的应用名、大而轻的页头，跟设置页同一套令牌（``METRO_TOKENS``），
  白天 / 黑夜跟「外观」里的主题（``apply_theme``）；
- 窗口底色透明，四张磁贴直接浮在桌面上、每张底下一圈柔和阴影（``_TILE_SHADOW_LAYERS``）；页头 / 页脚的文字
  带一圈反色光晕（``_HaloLabel``），深浅壁纸上都读得出来；
- 每张磁贴一块实色、方角、无描边：左上小标题，大号细体数字（今天），一行副标题
  （7 天合计 / 平均），底下 7 根柱子（最右是今天，实白；以前的天半透明白）。「上下班」是
  悬浮的区间柱，纵轴从上到下是一天里的钟点，右侧标出上下沿；用量 / 消息分账号时每天并排
  两根（Win 实心、WSL 空心，``part_rects``），大数字一行写不下时自动缩小字号；
- 悬停一根柱子弹出那天的确切数字（``QToolTip``）。

无边框置顶的工具窗：点别处（窗口失去激活）、按 Esc 或点右上角 × 收起。开着时每分钟发一次
``refresh_requested``。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QToolTip, QVBoxLayout, QWidget

from .i18n import t
from .settings_theme_qss import METRO_TOKENS
from .settings_widgets import TiltButton, _system_dark
from .usage_dashboard import Bar, Tile

TILE_W, TILE_H = 236, 200
TILE_GAP = 8
#: 磁贴阴影：由内到外几层半透明黑（外扩 px, 下移 px, 不透明度）；最外一层外扩多少就是 TILE_SHADOW_SPREAD
_TILE_SHADOW_LAYERS = ((1, 1, 70), (3, 2, 42), (5, 4, 26), (8, 6, 12))
TILE_SHADOW_SPREAD = max(spread for spread, _dy, _alpha in _TILE_SHADOW_LAYERS)
_PAD = 14
_PART_GAP = 2.0               # 分账号时同一天两根柱子之间的缝
_FAMILIES = ["Segoe UI", "SF Pro Text", "PingFang SC", "Microsoft YaHei UI"]
_REFRESH_MS = 60_000


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(_FAMILIES)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def _value_font(text: str, width: float) -> QFont:
    """大数字的字号：34px 起，一行写不下（分账号的「Win 2.38M · WSL 1.10M」）就逐级缩到 20px。"""
    for px in (34, 28, 24, 20):
        font = _font(px, QFont.Weight.Light)
        if QFontMetrics(font).horizontalAdvance(text) <= width:
            break
    return font


def halo_color(ink: QColor) -> QColor:
    """文字光晕的颜色：深色字配浅光晕、浅色字配深光晕（底色透明，字直接落在壁纸上）。"""
    return QColor(255, 255, 255, 170) if ink.lightness() < 128 else QColor(0, 0, 0, 170)


class _HaloLabel(QLabel):
    """带反色光晕的文字标签：先在四周 1px 与下方 2px 画光晕，再画字。字色与字号由代码给（不走样式表）。"""

    def __init__(self, text: str, parent: QWidget | None = None, *, px: int = 12,
                 weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> None:
        super().__init__(text, parent)
        font = _font(px, weight)
        if spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        self.setFont(font)
        self._ink = QColor("#111111")

    def set_ink(self, color: QColor) -> None:
        self._ink = QColor(color)
        self.update()

    def ink(self) -> QColor:
        return QColor(self._ink)

    def halo(self) -> QColor:
        return halo_color(self._ink)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        rect = self.contentsRect()
        flags = int(self.alignment()) | (int(Qt.TextFlag.TextWordWrap) if self.wordWrap() else 0)
        painter.setPen(self.halo())
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 2)):
            painter.drawText(rect.translated(dx, dy), flags, self.text())
        painter.setPen(self._ink)
        painter.drawText(rect, flags, self.text())


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
                                         (_value_font(tile.value, inner), tile.value, 30, 46),
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

    def part_rects(self) -> list[list[QRectF]]:
        """分账号时每一列里并排的几根柱子（先 Win 后 WSL）；没有分账号 = 空列表。高 0 = 那天那个账号没有用量。"""
        tile = self.tile
        if tile is None or not any(bar.parts for bar in tile.bars):
            return []
        chart = self._chart_rect()
        peak = max((max(bar.parts, default=0.0) for bar in tile.bars), default=0.0)
        groups = []
        for bar, column in zip(tile.bars, self.bar_rects()):
            x, width = self._bar_x(column)
            count = max(1, len(bar.parts))
            each = (width - _PART_GAP * (count - 1)) / count
            rects = []
            for index, part in enumerate(bar.parts):
                height = max(3.0, chart.height() * part / peak) if part > 0 and peak > 0 else 0.0
                rects.append(QRectF(x + index * (each + _PART_GAP), chart.bottom() - height, each, height))
            groups.append(rects)
        return groups

    def _paint_bars(self, painter: QPainter, tile: Tile, chart: QRectF, columns: list[QRectF]) -> None:
        groups = self.part_rects()
        if groups:
            self._paint_grouped(painter, tile, chart, groups)
            return
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

    def _paint_grouped(self, painter: QPainter, tile: Tile, chart: QRectF, groups: list[list[QRectF]]) -> None:
        """同一天并排几根：第一个账号实心，第二个起空心（1.5px 描边）；没有用量的贴底一道细线。"""
        for index, (bar, rects) in enumerate(zip(tile.bars, groups)):
            color = self._bar_color(bar, index)
            for part, rect in enumerate(rects):
                if rect.height() <= 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 70))
                    painter.drawRect(QRectF(rect.left(), chart.bottom() - 2, rect.width(), 2))
                elif part == 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    painter.drawRect(rect)
                else:
                    painter.setPen(QPen(color, 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(rect.adjusted(0.75, 0.75, -0.75, -0.75))
        painter.setPen(Qt.PenStyle.NoPen)

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
        # 底色透明：磁贴直接浮在桌面上，阴影由 paintEvent 画在每张磁贴底下
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setProperty("coversIsland", True)      # 开着时岛不重申置顶（见 DynamicIsland.reassert_topmost）
        self.app_label = _HaloLabel(t("dashboard.app"), self, px=12, weight=QFont.Weight.DemiBold, spacing=1.0)
        self.app_label.setObjectName("dashboardApp")
        self.title_label = _HaloLabel(t("dashboard.title"), self, px=28, weight=QFont.Weight.Light)
        self.title_label.setObjectName("dashboardTitle")
        self.status_label = _HaloLabel("", self, px=11)
        self.status_label.setObjectName("dashboardStatus")
        self.close_btn = TiltButton("×", self)
        self.close_btn.setObjectName("dashboardClose")
        self.close_btn.setAccessibleName(t("dashboard.close"))
        self.close_btn.setToolTip(t("dashboard.close"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        self.tiles = [MetricTile(self) for _ in range(4)]
        self.footer_label = _HaloLabel("", self, px=11)
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
        for label, key in ((self.app_label, "muted"), (self.title_label, "title"),
                           (self.status_label, "muted"), (self.footer_label, "muted")):
            label.set_ink(QColor(colors[key]))
        self.setStyleSheet(f"""
            QWidget#usageDashboard {{ background: transparent; }}
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

    def paintEvent(self, event) -> None:  # noqa: N802
        """透明底上只画每张磁贴底下的阴影（磁贴自己画自己）。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        for tile in self.tiles:
            if not tile.isVisible():
                continue
            geometry = QRectF(tile.geometry())
            for spread, dy, alpha in _TILE_SHADOW_LAYERS:
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRect(geometry.adjusted(-spread, -spread + dy, spread, spread + dy))

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
