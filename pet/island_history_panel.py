# -*- coding: utf-8 -*-
"""灵动岛卡片里的「最近的对话」折叠框（纯界面）。

给它几行数据（``set_rows``），它报用户点了什么（``activated`` / ``action_requested``）；
数据从哪来、点了之后做什么都不归它管（见 ``session_history_service`` 与 AppShell）。

样子（2026-10-14 起，照 Windows Phone 那种平铺卡片）：表头是一块方角的卡片；每一行也是
一块卡片，卡片之间留 2px 的缝；行的左边一个小图标说明从哪开的（VS Code / 本机终端 /
WSL 终端 / 脚本），进行中的行左缘一道主题色竖条。没有圆角、没有描边、没有阴影，靠
底色深浅和留白分层。卡片底色随岛的配色：浅字（深底）用浅色薄膜，深字用深色薄膜。

一行 = 标题 + 多久以前，下面一行小字「从哪开的 · 路径」。点一行 = 默认动作，右键出
菜单。行数多了在框里滚动，卡片不跟着无限长高。置顶的行（``pinned``，2026-10-20）
标题右边多一枚主题色图钉，右键菜单第一项是「置顶 / 取消置顶」；排序由数据层决定。

文字都按可用宽度省略好再交给 QLabel（标题省略末尾，路径省略中间——盘符和最后一段
目录名两头都要看得见），所以不会像卡片详情行那样从右边溢出。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .i18n import t

ROW_HEIGHT = 40          # 一行占的高度：38 的卡片 + 2 的缝
_ROW_GAP = 2
#: 列表最多露几行（缺省值；超出的在框里滚动）。5 行实机反馈太短
MAX_VISIBLE_ROWS = 10
_HEADER_HEIGHT = 28
_ROW_PAD_X = 8
_ICON_PX = 16
_ICON_SLOT = 22          # 图标占的宽度（没有图标也留着，文字对齐）
_PIN_PX = 12             # 置顶图钉（只有置顶的行才占位）
_LIVE_BAR_PX = 3
_SCROLLBAR_PX = 6
_TITLE_PX, _SMALL_PX = 12, 10
_STATUS_MS = 4000
_ICON_WARM_DELAY_MS = 2500
LIVE_TEXT_KEY = "history.live"
#: 从哪开的 → 图标名（``context_menus.icons``）
HOST_ICONS = {"vscode": "vscode", "desktop": "sparkle", "terminal": "terminal", "wsl": "ubuntu",
              "script": "automation"}
#: 右键菜单：(动作名, 文案)；None = 分隔线。第一项按行的置顶状态在 ``_PIN_ITEMS`` 里二选一
_PIN_ITEMS = {False: ("pin", "history.menu.pin"), True: ("unpin", "history.menu.unpin")}
_MENU = (None, ("terminal", "history.menu.terminal"), ("vscode", "history.menu.vscode"),
         ("folder", "history.menu.folder"),
         None, ("copy_path", "history.menu.copy_path"), ("copy_resume", "history.menu.copy_resume"), None,
         ("remove", "history.menu.remove"), ("clear", "history.menu.clear"))


def _font(base: QFont, pixels: int, *, bold: bool = False) -> QFont:
    font = QFont(base)
    font.setPixelSize(pixels)
    font.setBold(bold)
    return font


_PIN_CACHE: dict[tuple[str, int, float], QPixmap] = {}


def pin_pixmap(widget, color: str, size: int = _PIN_PX) -> QPixmap:
    """图钉记号（与右键菜单里 ``context_menus.icons`` 的 ``pin`` 同一个形状），按给定颜色画。

    不走 ``vector_widget_icon``：那套颜色跟控件调色板走，而岛的文字色是自己定的。
    按（颜色, 尺寸, DPR）缓存：每次刷新列表都要给置顶的行重设图钉。
    """
    dpr = float(widget.devicePixelRatioF() or 1.0)
    cached = _PIN_CACHE.get((color, size, dpr))
    if cached is not None:
        return cached
    pixmap = QPixmap(max(1, round(size * dpr)), max(1, round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 16.0, size / 16.0)
    painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(4.5, 2.0, 7.0, 5.0), 1.0, 1.0)
    painter.drawLine(QPointF(5.5, 7.0), QPointF(3.5, 10.0))
    painter.drawLine(QPointF(10.5, 7.0), QPointF(12.5, 10.0))
    painter.drawLine(QPointF(3.5, 10.0), QPointF(12.5, 10.0))
    painter.drawLine(QPointF(8.0, 10.0), QPointF(8.0, 14.0))
    painter.end()
    _PIN_CACHE[(color, size, dpr)] = pixmap
    return pixmap


def style_island_menu(menu: QMenu, primary: str, appearance: dict | None = None) -> None:
    """岛上弹出的菜单套肥鱼右键菜单那套 modern 样式：不透明底，岛是深底就深色、浅底就浅色。

    不这么做的话菜单会继承卡片 ``background: transparent`` 的样式表——透明底白字浮在岛上
    看不清（2026-10-20 用户截图）。``appearance`` 是右键菜单的外观设置（字号 / 密度 / 圆角），
    明暗与透明度在这里定死。
    """
    from .context_menus.menu_styles.modern import apply_modern_menu_style

    dark = QColor(primary).lightness() >= 128          # 浅字 = 深底的岛
    apply_modern_menu_style(menu, {**(appearance or {}), "theme": "dark" if dark else "light",
                                   "translucent": False})


def tile_colors(primary: str) -> tuple[str, str]:
    """(卡片底色, 悬停底色)：按主文字色的明暗判断岛是深底还是浅底。"""
    if QColor(primary).lightness() >= 128:
        return "rgba(255, 255, 255, 18)", "rgba(255, 255, 255, 34)"
    return "rgba(0, 0, 0, 14)", "rgba(0, 0, 0, 26)"


class _HistoryRow(QFrame):
    """一行会话（一块卡片）。左键点 = ``clicked``，右键 = ``menu_requested``。"""

    clicked = Signal(object)
    menu_requested = Signal(object, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.key = None
        self._press: QPoint | None = None
        self.setObjectName("historyRow")
        self.setFixedHeight(ROW_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, _ROW_GAP)          # 卡片之间的缝
        outer.setSpacing(0)
        self.tile = QFrame(self)
        self.tile.setObjectName("historyTile")
        self.tile.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        outer.addWidget(self.tile)
        grid = QGridLayout(self.tile)
        grid.setContentsMargins(_ROW_PAD_X, 3, _ROW_PAD_X, 3)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(0)
        self.icon = QLabel(self.tile)
        self.icon.setFixedSize(_ICON_SLOT, ROW_HEIGHT - _ROW_GAP - 6)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title, self.ago, self.path = QLabel(self.tile), QLabel(self.tile), QLabel(self.tile)
        self.pin = QLabel(self.tile)                          # 置顶图钉：没置顶就藏起来、不占位
        self.pin.setFixedSize(_PIN_PX, _PIN_PX)
        self.pin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin.hide()
        self.ago.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.icon, self.title, self.pin, self.ago, self.path):
            label.setTextFormat(Qt.TextFormat.PlainText)     # 标题 / 路径是外来内容：不当富文本
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title.setFont(_font(self.font(), _TITLE_PX, bold=True))
        self.ago.setFont(_font(self.font(), _SMALL_PX))
        self.path.setFont(_font(self.font(), _SMALL_PX))
        grid.addWidget(self.icon, 0, 0, 2, 1)
        grid.addWidget(self.title, 0, 1)
        grid.addWidget(self.pin, 0, 2)
        grid.addWidget(self.ago, 0, 3)
        grid.addWidget(self.path, 1, 1, 1, 3)
        grid.setColumnStretch(1, 1)

    def set_data(self, row: dict, width: int, *, accent: str, secondary: str) -> None:
        self.key = row.get("key")
        inner = max(40, width - 2 * _ROW_PAD_X - _ICON_SLOT - 6)
        live = bool(row.get("live"))
        ago = t(LIVE_TEXT_KEY) if live else str(row.get("ago") or "")
        ago_width = QFontMetrics(self.ago.font()).horizontalAdvance(ago) + 2
        self.ago.setText(ago)
        self.ago.setFixedWidth(ago_width)
        self.ago.setStyleSheet(f"color: {accent if live else secondary};")
        pinned = bool(row.get("pinned"))
        if pinned:
            self.pin.setPixmap(pin_pixmap(self, accent))
            self.pin.setToolTip(t("history.menu.unpin"))
        self.pin.setVisible(pinned)
        pin_width = _PIN_PX + 6 if pinned else 0
        self.title.setText(QFontMetrics(self.title.font()).elidedText(
            str(row.get("label") or ""), Qt.TextElideMode.ElideRight, max(20, inner - ago_width - pin_width - 8)))
        where, path = str(row.get("where") or ""), str(row.get("path") or "")
        self.path.setText(QFontMetrics(self.path.font()).elidedText(
            f"{where} · {path}" if where else path, Qt.TextElideMode.ElideMiddle, inner))
        self.setToolTip(path)
        self._set_icon(str(row.get("host") or ""))
        self.tile.setProperty("live", live)
        self.tile.style().unpolish(self.tile)
        self.tile.style().polish(self.tile)

    def _set_icon(self, host: str) -> None:
        if host not in HOST_ICONS:
            self.icon.clear()
            return
        from .host_icons import host_icon

        # 本机装着的那个程序自己的图标（VS Code / PowerShell / wsl.exe）；没有就是手绘记号
        self.icon.setPixmap(host_icon(self, host, _ICON_PX).pixmap(_ICON_PX, _ICON_PX))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press = event.position().toPoint()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        press, self._press = self._press, None
        event.accept()
        if press is None or not self.rect().contains(event.position().toPoint()):
            return                                       # 拖出去了：不算点击
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.key, event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)


class SessionHistoryPanel(QWidget):
    """「最近的对话」折叠框。"""

    toggled = Signal(bool)                  # 用户折叠 / 展开了
    activated = Signal(object)              # 点了一行（key）
    action_requested = Signal(str, object)  # 右键菜单里选了一项（动作名, key）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._row_widgets: list[_HistoryRow] = []
        self._open = False
        self._max_visible = MAX_VISIBLE_ROWS
        self._width = 300
        self._colors = {"primary": "#e5eaf5", "secondary": "#a0aabe", "accent": "#40b8ff"}
        self._menu_appearance: dict = {}
        self._menu: QMenu | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_ROW_GAP)
        self.header = QPushButton(self)
        self.header.setObjectName("historyHeader")
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
        # 来源图标里 VS Code 那个第一次要外壳解包 150 ms：启动稳定后先取好，别卡第一次展开
        QTimer.singleShot(_ICON_WARM_DELAY_MS, self._warm_icons)

    def _warm_icons(self) -> None:
        from .host_icons import warm

        try:
            warm(self, _ICON_PX)
        except Exception:  # noqa: BLE001 - 预热失败没关系，用到时再取
            pass

    # ---------------------------------------------------------------- 外观
    def set_look(self, *, primary: str, secondary: str, accent: str, width: int,
                 menu_appearance: dict | None = None) -> None:
        """跟着岛的配色与卡片宽度走；``menu_appearance`` 是右键菜单的外观设置（给行的菜单用）。"""
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
            # 表头：一块方角卡片，粗体，左对齐；悬停加亮
            f"QPushButton#historyHeader {{ color: {c['primary']}; background: {tile}; border: none;"
            f" border-radius: 0; text-align: left; padding: 0 {_ROW_PAD_X}px; }}"
            f"QPushButton#historyHeader:hover {{ background: {hover}; }}"
            # 行：外框透明（只负责留缝），里面那块是卡片；进行中的行左缘一道主题色竖条
            f"QFrame#historyRow {{ background: transparent; border: none; }}"
            f"QFrame#historyTile {{ background: {tile}; border: none; border-radius: 0;"
            f" border-left: {_LIVE_BAR_PX}px solid transparent; }}"
            f"QFrame#historyTile:hover {{ background: {hover}; }}"
            f"QFrame#historyTile[live=\"true\"] {{ border-left: {_LIVE_BAR_PX}px solid {c['accent']}; }}"
            f"QFrame#historyTile QLabel {{ color: {c['secondary']}; background: transparent; }}"
            f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}"
            # 细滚动条：系统默认那种带箭头的粗条在卡片里太抢眼
            f"QScrollBar:vertical {{ background: transparent; width: {_SCROLLBAR_PX}px; margin: 2px 0; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(128, 128, 128, 120); border-radius: 0;"
            f" min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")
        for row in self._row_widgets:
            row.title.setStyleSheet(f"color: {c['primary']};")

    # ---------------------------------------------------------------- 数据
    def row_widgets(self) -> list[_HistoryRow]:
        return list(self._row_widgets)

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
            widget = _HistoryRow(self._list)
            widget.clicked.connect(self.activated)
            widget.menu_requested.connect(lambda key, pos: self.popup_row_menu(key, pos))
            self._list_layout.insertWidget(len(self._row_widgets), widget)
            self._row_widgets.append(widget)
        self._refill()

    def set_max_visible(self, count) -> None:
        """列表最多露几行（至少 1；给的值不像话就用默认）。"""
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
            widget.set_data(row, width, accent=self._colors["accent"], secondary=self._colors["secondary"])
            widget.title.setStyleSheet(f"color: {self._colors['primary']};")
        self.body.setFixedHeight(min(len(self._rows), self._max_visible) * ROW_HEIGHT)
        self.body.setVisible(self._open and bool(self._rows))
        self._update_header()
        self.updateGeometry()

    def _update_header(self) -> None:
        if self._status:
            text = self._status
        else:
            text = t("history.header.open" if self._open else "history.header.closed", n=len(self._rows))
        self.header_text = text          # 未省略的全文（省略只为显示；测试与悬停提示看这个）
        self.header.setToolTip(text)
        self.header.setText(QFontMetrics(self.header.font()).elidedText(
            text, Qt.TextElideMode.ElideRight, max(40, self._width - 2 * _ROW_PAD_X - 4)))

    def retranslate(self) -> None:
        """界面语言换了：表头、「进行中」这些由面板自己写的字按新语言重写（行数据由 app 重推）。"""
        self._refill()

    # ---------------------------------------------------------------- 折叠
    def is_open(self) -> bool:
        return self._open

    def set_open(self, is_open: bool) -> None:
        """设折叠状态（恢复上次的状态用；不发 ``toggled``）。"""
        self._open = bool(is_open)
        self.body.setVisible(self._open and bool(self._rows))
        self._update_header()
        self.updateGeometry()

    def _on_header_clicked(self) -> None:
        self.set_open(not self._open)
        self.toggled.emit(self._open)

    # ---------------------------------------------------------------- 状态行
    def show_status(self, text: str) -> None:
        """动作的结果（「已在终端里恢复…」）：在标题那一行显示几秒。"""
        self._status = str(text or "")
        self._update_header()
        if self._status:
            self._status_timer.start()

    def _clear_status(self) -> None:
        self._status = ""
        self._update_header()

    # ---------------------------------------------------------------- 右键菜单
    def _is_pinned(self, key) -> bool:
        return any(bool(row.get("pinned")) for row in self._rows if row.get("key") == key)

    def row_menu(self, key) -> QMenu:
        menu = QMenu(self)
        for item in (_PIN_ITEMS[self._is_pinned(key)], *_MENU):
            if item is None:
                menu.addSeparator()
                continue
            name, text_key = item
            menu.addAction(t(text_key)).triggered.connect(
                lambda _checked=False, name=name: self.action_requested.emit(name, key))
        style_island_menu(menu, self._colors["primary"], self._menu_appearance)
        return menu

    def popup_row_menu(self, key, pos: QPoint) -> None:
        self._menu = self.row_menu(key)          # 留着引用：popup 不阻塞
        self._menu.popup(pos)
