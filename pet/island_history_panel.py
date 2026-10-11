# -*- coding: utf-8 -*-
"""灵动岛卡片里的「最近的对话」折叠框（纯界面）。

给它几行数据（``set_rows``），它报用户点了什么（``activated`` / ``action_requested``）；
数据从哪来、点了之后做什么都不归它管（见 ``session_history_service`` 与 AppShell）。

一行 = 标题 + 多久以前，下面一行小字「从哪开的 · 路径」。点一行 = 默认动作，右键出
菜单。行数多了在框里滚动，卡片不跟着无限长高。

文字都按可用宽度省略好再交给 QLabel（标题省略末尾，路径省略中间——盘符和最后一段
目录名两头都要看得见），所以不会像卡片详情行那样从右边溢出。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

ROW_HEIGHT = 36
MAX_VISIBLE_ROWS = 5
_HEADER_HEIGHT = 24
_ROW_PAD_X = 6
_SCROLLBAR_PX = 6
_TITLE_PX, _SMALL_PX = 12, 10
_STATUS_MS = 4000
LIVE_TEXT = "进行中"
#: 右键菜单：(动作名, 文案)；None = 分隔线
_MENU = (("terminal", "在终端里恢复"), ("vscode", "在 VS Code 里打开"), ("folder", "打开文件夹"), None,
         ("copy_path", "复制路径"), ("copy_resume", "复制恢复命令"), None,
         ("remove", "从列表移除"), ("clear", "清空列表"))


def _font(base: QFont, pixels: int, *, bold: bool = False) -> QFont:
    font = QFont(base)
    font.setPixelSize(pixels)
    font.setBold(bold)
    return font


class _HistoryRow(QFrame):
    """一行会话。左键点 = ``clicked``，右键 = ``menu_requested``。"""

    clicked = Signal(object)
    menu_requested = Signal(object, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.key = None
        self._press: QPoint | None = None
        self.setObjectName("historyRow")
        self.setFixedHeight(ROW_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        grid = QGridLayout(self)
        grid.setContentsMargins(_ROW_PAD_X, 3, _ROW_PAD_X, 3)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        self.title, self.ago, self.path = QLabel(self), QLabel(self), QLabel(self)
        self.ago.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.title, self.ago, self.path):
            label.setTextFormat(Qt.TextFormat.PlainText)     # 标题 / 路径是外来内容：不当富文本
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title.setFont(_font(self.font(), _TITLE_PX))
        self.ago.setFont(_font(self.font(), _SMALL_PX))
        self.path.setFont(_font(self.font(), _SMALL_PX))
        grid.addWidget(self.title, 0, 0)
        grid.addWidget(self.ago, 0, 1)
        grid.addWidget(self.path, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)

    def set_data(self, row: dict, width: int, *, accent: str, secondary: str) -> None:
        self.key = row.get("key")
        inner = max(40, width - 2 * _ROW_PAD_X)
        live = bool(row.get("live"))
        ago = LIVE_TEXT if live else str(row.get("ago") or "")
        ago_width = QFontMetrics(self.ago.font()).horizontalAdvance(ago) + 2
        self.ago.setText(ago)
        self.ago.setFixedWidth(ago_width)
        self.ago.setStyleSheet(f"color: {accent if live else secondary};")
        self.title.setText(QFontMetrics(self.title.font()).elidedText(
            str(row.get("label") or ""), Qt.TextElideMode.ElideRight, max(20, inner - ago_width - 8)))
        where, path = str(row.get("where") or ""), str(row.get("path") or "")
        self.path.setText(QFontMetrics(self.path.font()).elidedText(
            f"{where} · {path}" if where else path, Qt.TextElideMode.ElideMiddle, inner))
        self.setToolTip(path)

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
        self._width = 300
        self._colors = {"primary": "#e5eaf5", "secondary": "#a0aabe", "accent": "#40b8ff"}
        self._menu: QMenu | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.header = QPushButton(self)
        self.header.setObjectName("historyHeader")
        self.header.setFixedHeight(_HEADER_HEIGHT)
        self.header.setFont(_font(self.font(), 11))
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
    def set_look(self, *, primary: str, secondary: str, accent: str, width: int) -> None:
        """跟着岛的配色与卡片宽度走。"""
        colors = {"primary": primary, "secondary": secondary, "accent": accent}
        if colors == self._colors and int(width) == self._width:
            return
        self._colors, self._width = colors, int(width)
        self._restyle()
        self._refill()

    def _restyle(self) -> None:
        c = self._colors
        self.setStyleSheet(
            f"QPushButton#historyHeader {{ color: {c['secondary']}; background: transparent; border: none;"
            f" text-align: left; padding: 0 2px; }}"
            f"QPushButton#historyHeader:hover {{ color: {c['primary']}; }}"
            f"QFrame#historyRow {{ background: transparent; border-radius: 6px; }}"
            f"QFrame#historyRow:hover {{ background: rgba(128, 128, 128, 46); }}"
            f"QFrame#historyRow QLabel {{ color: {c['secondary']}; background: transparent; }}"
            f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}"
            # 细滚动条：系统默认那种带箭头的粗条在卡片里太抢眼
            f"QScrollBar:vertical {{ background: transparent; width: {_SCROLLBAR_PX}px; margin: 2px 0; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(128, 128, 128, 120); border-radius: 3px;"
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

    def _refill(self) -> None:
        scroll = len(self._rows) > MAX_VISIBLE_ROWS
        width = self._width - (_SCROLLBAR_PX + 2 if scroll else 0)
        for widget, row in zip(self._row_widgets, self._rows):
            widget.set_data(row, width, accent=self._colors["accent"], secondary=self._colors["secondary"])
            widget.title.setStyleSheet(f"color: {self._colors['primary']};")
        self.body.setFixedHeight(min(len(self._rows), MAX_VISIBLE_ROWS) * ROW_HEIGHT)
        self.body.setVisible(self._open and bool(self._rows))
        self._update_header()
        self.updateGeometry()

    def _update_header(self) -> None:
        if self._status:
            text = self._status
        else:
            text = f"最近的对话 ({len(self._rows)}) · {'收起' if self._open else '展开'}"
        self.header.setText(QFontMetrics(self.header.font()).elidedText(
            text, Qt.TextElideMode.ElideRight, max(40, self._width - 6)))

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
    def row_menu(self, key) -> QMenu:
        menu = QMenu(self)
        for item in _MENU:
            if item is None:
                menu.addSeparator()
                continue
            name, text = item
            menu.addAction(text).triggered.connect(
                lambda _checked=False, name=name: self.action_requested.emit(name, key))
        return menu

    def popup_row_menu(self, key, pos: QPoint) -> None:
        self._menu = self.row_menu(key)          # 留着引用：popup 不阻塞
        self._menu.popup(pos)
