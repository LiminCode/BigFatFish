# -*- coding: utf-8 -*-
"""笔记详情底部的「基本信息」栏：记下的时间、模型、tokens、花费、用时（2026-10-20 用户要求）。

工作简报顶部那条「这次用了什么」（模型、effort、用时、tokens、花费，2026-10-24）也是它：
``NoteMetaBar(keys=BRIEFING_KEYS, framed=False)`` + ``show_values``。

以前这些是正文第二行的一串纯文字，和摘要抢地方。现在是详情下面一条不随正文滚动的细栏：
每项一个小图标 + 简短数字（时钟、火花、向下 / 向上箭头、美元硬币、秒表），用次要文字色，
精确值放悬停提示。图标自己画（不用 emoji：首次画 emoji 会加载彩色字体栈，约 +33 MB），
颜色跟简报窗口的白天 / 黑夜色板走（``apply_colors``）。
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from . import work_notes as wn
from .i18n import t

ICON_PX = 14
#: 显示顺序
KEYS = ("saved", "model", "tokens_in", "tokens_out", "cost", "time")
#: 工作简报那条的显示顺序
BRIEFING_KEYS = ("model", "effort", "time", "tokens_in", "tokens_out", "cost")


def short_count(value: int) -> str:
    """34641 → 34.6k；1234567 → 1.2M；不到 1000 原样。"""
    value = int(value)
    if value < 1000:
        return str(value)
    for limit, unit in ((1_000_000, "M"), (1000, "k")):
        if value >= limit:
            number = value / limit
            text = f"{number:.0f}" if number >= 100 else f"{number:.1f}".rstrip("0").rstrip(".")
            return text + unit
    return str(value)


def short_cost(value: float) -> str:
    """美元金额（不带 $，前面是美元图标）：三位小数；太小写「<0.001」；≥1 两位小数。"""
    value = float(value)
    if value <= 0:
        return "0"
    if value < 0.001:
        return "<0.001"
    if value >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _when(value: str) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%m-%d %H:%M}"
    except ValueError:
        return value


def meta_icon(name: str, color: str, size: int = ICON_PX, dpr: float = 1.0) -> QPixmap:
    """在 16 单位的画布上画一个线条小图标。"""
    pixmap = QPixmap(max(1, round(size * dpr)), max(1, round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 16.0, size / 16.0)
    pen = QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    line = painter.drawLine
    if name == "saved":                       # 时钟
        painter.drawEllipse(QPointF(8, 8), 6.2, 6.2)
        line(QPointF(8, 8), QPointF(8, 4.6))
        line(QPointF(8, 8), QPointF(10.6, 9.6))
    elif name == "model":                     # 四角火花
        path = QPainterPath(QPointF(8, 1.8))
        for point in ((9.4, 6.6), (14.2, 8), (9.4, 9.4), (8, 14.2), (6.6, 9.4), (1.8, 8), (6.6, 6.6), (8, 1.8)):
            path.lineTo(QPointF(*point))
        painter.drawPath(path)
    elif name in ("tokens_in", "tokens_out"):  # 托盘 + 进 / 出箭头
        line(QPointF(2.5, 10.5), QPointF(2.5, 13.5))
        line(QPointF(2.5, 13.5), QPointF(13.5, 13.5))
        line(QPointF(13.5, 13.5), QPointF(13.5, 10.5))
        line(QPointF(8, 2), QPointF(8, 10))
        if name == "tokens_in":
            line(QPointF(8, 10), QPointF(5, 7))
            line(QPointF(8, 10), QPointF(11, 7))
        else:
            line(QPointF(8, 2), QPointF(5, 5))
            line(QPointF(8, 2), QPointF(11, 5))
    elif name == "effort":                    # 仪表盘
        painter.drawArc(QRectF(2, 3.5, 12, 12), 0, 180 * 16)
        line(QPointF(2, 9.5), QPointF(14, 9.5))
        line(QPointF(8, 9.5), QPointF(11, 5.6))
    elif name == "cost":                      # 美元硬币
        painter.drawEllipse(QPointF(8, 8), 6.4, 6.4)
        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0.4, 16, 16), Qt.AlignmentFlag.AlignCenter, "$")
    elif name == "time":                      # 秒表
        painter.drawEllipse(QPointF(8, 9), 5.6, 5.6)
        line(QPointF(6.5, 1.8), QPointF(9.5, 1.8))
        line(QPointF(8, 1.8), QPointF(8, 3.4))
        line(QPointF(8, 9), QPointF(10.2, 6.8))
        line(QPointF(12.6, 3.8), QPointF(13.6, 4.8))
    painter.end()
    return pixmap


class _Chip(QWidget):
    """一项：图标 + 文字；悬停看精确值。"""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.icon = QLabel(self)
        self.icon.setFixedSize(ICON_PX, ICON_PX)
        self.text = QLabel(self)
        self.text.setObjectName("notesMetaText")
        self.text.setTextFormat(Qt.TextFormat.PlainText)      # 模型名是外来内容
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.icon)
        layout.addWidget(self.text)


class NoteMetaBar(QFrame):
    """详情底部那一条。``show_note(None)`` = 藏起来。

    ``keys`` 是有哪几项、什么顺序；``framed=False`` 时不画底色和上边线、不留内边距（简报顶部那条
    紧跟在「生成于」那行下面，不是一块单独的面板）。"""

    def __init__(self, colors: dict, parent=None, *, keys: tuple[str, ...] = KEYS, framed: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("notesMeta")
        self._colors = dict(colors)
        self._keys = tuple(keys)
        self._framed = framed
        self._chips = {key: _Chip(key, self) for key in self._keys}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(*((14, 7, 14, 8) if framed else (0, 0, 0, 0)))
        layout.setSpacing(16)
        for key in self._keys:
            layout.addWidget(self._chips[key])
        layout.addStretch(1)
        self._restyle()
        self.hide()

    def chips(self) -> list[_Chip]:
        return [self._chips[key] for key in self._keys]

    def apply_colors(self, colors: dict) -> None:
        self._colors = dict(colors)
        self._restyle()

    def _restyle(self) -> None:
        c = self._colors
        muted = c.get("muted", "#777777")
        frame = (f"background: {c.get('tile', 'transparent')}; border: 0;"
                 f" border-top: 1px solid {c.get('divider', c.get('border', '#dddddd'))};"
                 if self._framed else "background: transparent; border: 0;")
        self.setStyleSheet(
            f"QFrame#notesMeta {{ {frame} }}"
            f"QLabel#notesMetaText {{ color: {muted}; font-size: 12px; background: transparent; }}")
        dpr = float(self.devicePixelRatioF() or 1.0)
        for chip in self._chips.values():
            chip.icon.setPixmap(meta_icon(chip.key, muted, ICON_PX, dpr))

    def show_note(self, note: wn.Note | None) -> None:
        if note is None:
            self.hide()
            return
        when = _when(note.created)
        values = {"saved": (when, t("notes.meta.saved_tip", when=when))}
        if note.model:
            values.update({
                "model": (note.model, t("notes.meta.model_tip", model=note.model)),
                "tokens_in": (short_count(note.tokens_in), t("notes.meta.tokens_in_tip", n=f"{note.tokens_in:,}")),
                "tokens_out": (short_count(note.tokens_out), t("notes.meta.tokens_out_tip", n=f"{note.tokens_out:,}")),
                "cost": (short_cost(note.cost_usd), t("notes.meta.cost_tip", cost=f"{note.cost_usd:.4f}")),
                "time": time_value(note.seconds),
            })
        self.show_values(values)

    def show_values(self, values: dict[str, tuple[str, str]]) -> None:
        """每项（文字, 悬停提示）；没给或文字为空的项藏起来。"""
        for key, chip in self._chips.items():
            text, tip = values.get(key, ("", ""))
            chip.text.setText(text)
            chip.setToolTip(tip)
            chip.setVisible(bool(text))
        self.setAccessibleName(" · ".join(values[key][1] for key in self._keys if values.get(key, ("",))[0]))
        self.show()


def time_value(seconds: float) -> tuple[str, str]:
    return (t("notes.meta.seconds", n=f"{seconds:.0f}"),
            t("notes.meta.time_tip", n=f"{seconds:.1f}".rstrip("0").rstrip(".")))


def usage_values(model: str, effort: str, tokens_in: int, tokens_out: int, cost_usd: float,
                 seconds: float) -> dict[str, tuple[str, str]]:
    """一次 ``claude -p`` 的用量 → ``show_values`` 的参数；没有模型名（旧记录）就只有用时。"""
    values = {"time": time_value(seconds)}
    if model:
        values.update({
            "model": (model, t("notes.meta.model_tip", model=model)),
            "effort": (effort, t("notes.meta.effort_tip", effort=effort)) if effort else ("", ""),
            "tokens_in": (short_count(tokens_in), t("notes.meta.tokens_in_tip", n=f"{tokens_in:,}")),
            "tokens_out": (short_count(tokens_out), t("notes.meta.tokens_out_tip", n=f"{tokens_out:,}")),
            "cost": (short_cost(cost_usd), t("notes.meta.cost_tip", cost=f"{cost_usd:.4f}")),
        })
    return values
