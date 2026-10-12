# -*- coding: utf-8 -*-
"""托盘图标的取图：自定义图片优先，没有就用角色头像（由调用方提供）。

默认的托盘图标取自角色当前帧，等比缩进托盘的小方格里；角色是横长的时候图标就显得
很小。设置项 ``tray_icon`` 让用户指定一张自己的图片（绝对路径，与对话背景等自定义
图片同一约定）。文件不在、不是图片、或者没填，一律视为「没有自定义图标」，调用方
回到默认——不报错、不弹窗。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QPixmap, QRegion

CONFIG_KEY = "tray_icon"


def fit_icon_pixmap(pm: QPixmap, size: int) -> QPixmap:
    """裁掉透明留白后等比缩放到 ``size`` 以内。

    直接缩放会把主体连同四周的透明边一起缩小（动画帧是整张视频画布，角色只占中间
    一块）；托盘、灵动岛头像、自定义托盘图片共用这一份裁剪语义。
    """
    image = pm.toImage()
    bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
    if bounds.isValid() and not bounds.isEmpty():
        pm = QPixmap.fromImage(image.copy(bounds))
    return pm.scaled(size, size,
                     Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


def load_custom_pixmap(path, size: int = 64) -> QPixmap | None:
    """用户指定的托盘图片 → 可用的图标位图；用不了返回 ``None``（调用方用默认图标）。"""
    text = str(path or "").strip()
    if not text:
        return None
    try:
        if not Path(text).is_file():
            return None
    except OSError:
        return None
    pixmap = QPixmap(text)
    if pixmap.isNull():
        return None
    return fit_icon_pixmap(pixmap, size)
