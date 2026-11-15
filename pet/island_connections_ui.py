# -*- coding: utf-8 -*-
"""「模型连接」面板的窗口：每个模型服务一张 Metro 实色磁贴（纯界面）。

数据由 ``island_connections`` 给好（``set_rows``），这里只管画，外壳与近 7 天仪表盘同一套
（``usage_dashboard_ui``）：透明底、磁贴浮在桌面上带一圈柔和阴影；页头 / 页脚文字带反色光晕；
白天 / 黑夜跟「外观」里的主题。

磁贴底色就是状态：翡翠绿 = 连得上，红 = 连不上，钢灰 = 还没查 / 正在查。白字三行：名称（在用的
那一项右侧一块「使用中」小标）、模型 · 地址、状态说明。白字在三种底色上对比度都 ≥ 4.5:1。

无边框置顶的工具窗：点别处（窗口失去激活）、按 Esc 或点右上角 × 收起。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QToolTip, QVBoxLayout, QWidget

from .i18n import t
from .island_connections import BAD, CHECKING, OK, ServiceRow
from .settings_theme_qss import METRO_TOKENS
from .settings_widgets import TiltButton
from .usage_dashboard_ui import _TILE_SHADOW_LAYERS, _HaloLabel, _font, resolve_dark

TILE_W, TILE_H = 340, 78
TILE_GAP = 8
_PAD = 14
#: 状态 → 磁贴底色（白字对比度：#008a00 4.5、#c50f1f 6.0、#5d6b7a 5.5）
STATE_COLORS = {OK: "#008a00", BAD: "#c50f1f", CHECKING: "#5d6b7a", "unknown": "#5d6b7a"}


class ServiceTile(QWidget):
    """一张磁贴 = 一个模型服务。"""

    def __init__(self, row: ServiceRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(TILE_W, TILE_H)
        self.row = row
        self.set_row(row)

    def set_row(self, row: ServiceRow) -> None:
        self.row = row
        name = row.name + (t("island.connections.in_use_suffix") if row.in_use else "")
        self.setAccessibleName(f"{name}: {self.state_text()}")
        self.setAccessibleDescription(f"{self.second_line()} · {row.detail}")
        self.setToolTip(row.detail)
        self.update()

    def state_text(self) -> str:
        return t(f"island.connections.state_{self.row.state}")

    def status_line(self) -> str:
        """第三行：有结论时「连得上 / 连不上 · 原因」，还没结论时只写「正在检查… / 还没检查」。"""
        if self.row.state in (OK, BAD):
            return f"{self.state_text()} · {self.row.detail}"
        return self.row.detail

    def second_line(self) -> str:
        return " · ".join(part for part in (self.row.model, self.row.host) if part)

    def color(self) -> QColor:
        return QColor(STATE_COLORS.get(self.row.state, STATE_COLORS["unknown"]))

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        row = self.row
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), self.color())
        white = QColor(255, 255, 255)
        inner = self.width() - 2 * _PAD
        badge_w = 0
        if row.in_use:                          # 「使用中」：右上角一块半透明白底的小标
            badge_font = _font(11, QFont.Weight.DemiBold)
            text = t("island.connections.in_use")
            badge_w = QFontMetrics(badge_font).horizontalAdvance(text) + 12
            badge = QRectF(self.width() - _PAD - badge_w, 11, badge_w, 18)
            painter.fillRect(badge, QColor(255, 255, 255, 56))
            painter.setFont(badge_font)
            painter.setPen(white)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        lines = ((_font(15, QFont.Weight.DemiBold), row.name, 8, 24, inner - (badge_w + 8 if badge_w else 0)),
                 (_font(12), self.second_line(), 32, 18, inner),
                 (_font(12), self.status_line(), 52, 18, inner))
        painter.setPen(white)
        for font, text, top, height, width in lines:
            painter.setFont(font)
            elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width)
            painter.drawText(QRectF(_PAD, top, width, height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)


class ConnectionsWindow(QWidget):
    """面板窗口：页头 + 一列磁贴 + 两行按钮（重新检查 / 去设置修改；配置全景）。"""

    recheck_requested = Signal()
    settings_requested = Signal()
    panorama_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("connectionsPanel")
        self.setWindowTitle(t("island.connections.title"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setProperty("coversIsland", True)      # 开着时岛不重申置顶（见 DynamicIsland.reassert_topmost）
        self.app_label = _HaloLabel(t("island.connections.app"), self, px=12, weight=QFont.Weight.DemiBold,
                                    spacing=1.0)
        self.title_label = _HaloLabel(t("island.connections.title"), self, px=28, weight=QFont.Weight.Light)
        self.close_btn = TiltButton("×", self)
        self.close_btn.setObjectName("connectionsClose")
        self.close_btn.setAccessibleName(t("dashboard.close"))
        self.close_btn.setToolTip(t("dashboard.close"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        self.recheck_btn = TiltButton(t("island.connections.recheck"), self)
        self.recheck_btn.setObjectName("connectionsAction")
        self.recheck_btn.clicked.connect(self.recheck_requested)
        self.settings_btn = TiltButton(t("island.connections.edit_in_settings"), self)
        self.settings_btn.setObjectName("connectionsAction")
        self.settings_btn.clicked.connect(self.settings_requested)
        self.panorama_btn = TiltButton(t("island.connections.panorama"), self)
        self.panorama_btn.setObjectName("connectionsAction")
        self.panorama_btn.setToolTip(t("island.connections.panorama_tip"))
        self.panorama_btn.clicked.connect(self.panorama_requested)
        self.footer_label = _HaloLabel(t("island.connections.footer"), self, px=11)
        self.footer_label.setWordWrap(True)
        self.footer_label.setFixedWidth(TILE_W)
        self.tiles: list[ServiceTile] = []

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.app_label)
        names.addWidget(self.title_label)
        head.addLayout(names)
        head.addStretch(1)
        head.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._tiles_layout = QVBoxLayout()
        self._tiles_layout.setSpacing(TILE_GAP)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.recheck_btn)
        actions.addWidget(self.settings_btn)
        actions.addStretch(1)
        more = QHBoxLayout()                 # 另起一行：英文下前两个按钮已经比磁贴宽，再并排会把面板撑宽
        more.setContentsMargins(0, 0, 0, 0)
        more.addWidget(self.panorama_btn)
        more.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(self._tiles_layout)
        layout.addLayout(actions)
        layout.addLayout(more)
        layout.addWidget(self.footer_label)
        self.colors = METRO_TOKENS["light"]
        self.apply_theme("system")

    def apply_theme(self, theme: str) -> None:
        self.colors = colors = METRO_TOKENS["dark" if resolve_dark(theme) else "light"]
        self.setStyleSheet("")      # 先清空再设：窗口还没显示过时第二次 setStyleSheet 不生效（同仪表盘）
        for label, key in ((self.app_label, "muted"), (self.title_label, "title"), (self.footer_label, "muted")):
            label.set_ink(QColor(colors[key]))
        self.setStyleSheet(f"""
            QWidget#connectionsPanel {{ background: transparent; }}
            QPushButton#connectionsClose {{
                background: transparent; color: {colors['text']}; border: 2px solid transparent; border-radius: 0;
                font-size: 16px; min-width: 28px; min-height: 26px; padding: 0 4px;
            }}
            QPushButton#connectionsClose:hover {{ border-color: {colors['outline']}; }}
            QPushButton#connectionsClose:focus, QPushButton#connectionsAction:focus {{
                border-color: {colors['accent']};
            }}
            QPushButton#connectionsAction {{
                background: {colors['tile']}; color: {colors['text']}; border: 2px solid transparent;
                border-radius: 0; padding: 5px 12px; font-size: 12px; font-weight: 600;
            }}
            QPushButton#connectionsAction:hover {{ background: {colors['tile_hover']}; }}
        """)

    def set_rows(self, rows: list[ServiceRow]) -> None:
        """换内容：行数没变就原地更新磁贴，变了就重建（服务增删）。"""
        if [tile.row.provider_id for tile in self.tiles] == [row.provider_id for row in rows]:
            for tile, row in zip(self.tiles, rows):
                tile.set_row(row)
            return
        for tile in self.tiles:
            self._tiles_layout.removeWidget(tile)
            tile.deleteLater()
        self.tiles = [ServiceTile(row, self) for row in rows]
        for tile in self.tiles:
            self._tiles_layout.addWidget(tile)
        if self.isVisible():
            self.adjustSize()
        self.update()

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

    def hideEvent(self, event) -> None:  # noqa: N802
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
