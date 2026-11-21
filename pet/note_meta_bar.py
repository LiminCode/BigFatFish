# -*- coding: utf-8 -*-
"""一次 ``claude -p`` 用量的「基本信息」：记下的时间、模型、effort、tokens、花费、用时——数字怎么缩写、悬停提示怎么写，
以及会话卡片上那几个自己画的线条小图标。

浏览器里的报告页 / 笔记页（``panorama.reports.usage`` / ``panorama.notes.note_dict``）用 ``usage_values`` 给每项
``(简短文字, 精确值的提示)``：34641 → 34.6k，花费三位小数，秒数取整；精确值放提示里。图标自己画线条（不用 emoji：首次画
emoji 会加载彩色字体栈，约 +33 MB），颜色由调用方给。

Qt 的那条信息栏 ``NoteMetaBar``（笔记详情底部、简报顶部）2026-11-21 随简报窗口一起下线；模块名没改，免得会话卡片和页面的
导入跟着动。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap

from .i18n import t

ICON_PX = 14


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


def time_value(seconds: float) -> tuple[str, str]:
    return (t("notes.meta.seconds", n=f"{seconds:.0f}"),
            t("notes.meta.time_tip", n=f"{seconds:.1f}".rstrip("0").rstrip(".")))


def usage_values(model: str, effort: str, tokens_in: int, tokens_out: int, cost_usd: float,
                 seconds: float) -> dict[str, tuple[str, str]]:
    """一次 ``claude -p`` 的用量 → 每项 ``(简短文字, 悬停提示)``；没有模型名（旧记录）就只有用时。"""
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
