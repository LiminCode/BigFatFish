# -*- coding: utf-8 -*-
"""设置页「桌面组件 · 图标」：点图标方块直接选一张图片做灵动岛图标（2026-10-20 用户要求）。

以前这一行是下拉框（鱼本体头像 / 十个 emoji），用户放不了自己的图。现在：

- 点方块 = 直接弹出系统选文件对话框（从「图片」文件夹开始，只列图片）；
- 选中的图读进来、缩到最长边 ``MAX_EDGE``、存成 PNG，复制进肥鱼配置目录下的 ``ICON_DIR``
  （文件名带内容哈希）。原文件以后移走 / 删掉都不影响；岛也不用常驻一张几十 MB 的大图；
- 「用鱼本体头像」回到默认 ``auto``；保存时把不再用的旧副本删掉；
- 旧配置里的 emoji（下拉框时代选的）不动它就原样保存——岛照旧会画；设置页这里不画 emoji
  （首次画 emoji 会加载彩色字体栈，约 +33 MB，见 ``dynamic_island._icon_text``）。

配置值沿用岛早就认的 ``img:<路径>``（``dynamic_island._ICON_IMG_PREFIX``），岛那边不用改。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, QStandardPaths, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .context_menus.icons import vector_widget_icon
from .i18n import t
from .settings_widgets import IMAGE_NAME_FILTER, TiltButton

log = logging.getLogger(__name__)

#: 配置目录下放图标副本的子目录
ICON_DIR = "island-icons"
#: 副本的最长边（像素）。岛里图标画 22 逻辑像素，200% 缩放也只要 44
MAX_EDGE = 128
AUTO = "auto"
IMG_PREFIX = "img:"
_TILE_PX = 40
_PREVIEW_PX = 28


def import_icon(source: str | Path, data_dir: str | Path) -> Path | None:
    """把 ``source`` 这张图缩好存进 ``data_dir/ICON_DIR``，返回副本路径；读不了返回 None。"""
    image = QImage(str(source))
    if image.isNull():
        return None
    if max(image.width(), image.height()) > MAX_EDGE:
        image = image.scaled(MAX_EDGE, MAX_EDGE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    buffer.close()
    payload = bytes(data.data())
    folder = Path(data_dir) / ICON_DIR
    target = folder / f"icon-{hashlib.sha1(payload).hexdigest()[:12]}.png"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(payload)
    except OSError:
        log.warning("灵动岛图标：写入副本失败 %s", target, exc_info=True)
        return None
    return target


def prune_icons(data_dir: str | Path, keep: str = "") -> int:
    """删掉 ``ICON_DIR`` 里除 ``keep``（当前配置值）以外的副本。返回删了几个。"""
    folder = Path(data_dir) / ICON_DIR
    kept = Path(keep[len(IMG_PREFIX):]).name if keep.startswith(IMG_PREFIX) else ""
    removed = 0
    for path in folder.glob("icon-*.png") if folder.is_dir() else ():
        if path.name == kept:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            log.debug("灵动岛图标：删旧副本失败 %s", path, exc_info=True)
    return removed


def _start_dir() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return pictures if pictures and Path(pictures).is_dir() else str(Path.home())


class IslandIconPicker(QWidget):
    """图标方块（点了直接选文件）+ 当前状态 +「用鱼本体头像」。值 = 岛的 ``icon`` 配置值。"""

    def __init__(self, value: str, data_dir: str | Path, parent=None) -> None:
        super().__init__(parent)
        self._value = str(value or AUTO).strip() or AUTO
        self._data_dir = Path(data_dir)
        self.tile = TiltButton(self)
        self.tile.setObjectName("islandIconTile")
        self.tile.setFixedSize(_TILE_PX + 8, _TILE_PX + 8)
        self.tile.setIconSize(QSize(_PREVIEW_PX, _PREVIEW_PX))
        self.tile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tile.setToolTip(t("settings.island_icon.tile_tip"))
        self.tile.setAccessibleName(t("settings.island_icon.tile_tip"))
        self.tile.clicked.connect(self.choose)
        self.state_label = QLabel(self)
        self.reset_button = TiltButton(t("settings.island_icon.reset"), self)
        # 按文字定最小宽度：英文「Use fish avatar」比中文长，样式表左右各 14px 内边距 + 2px 描边
        self.reset_button.setMinimumWidth(self.reset_button.fontMetrics().horizontalAdvance(self.reset_button.text()) + 40)
        self.reset_button.clicked.connect(self.reset)
        self.error_label = QLabel(self)
        self.error_label.setObjectName("settingHint")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self.tile)
        row.addWidget(self.state_label, 1)
        row.addWidget(self.reset_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(self.error_label)
        self._sync()

    def value(self) -> str:
        return self._value

    def choose(self) -> None:
        """点方块：直接打开选文件对话框。取消 = 不改；读不了 = 不改并说一句。"""
        selected, _filter = QFileDialog.getOpenFileName(
            self, t("settings.island_icon.choose_title"), _start_dir(), t(IMAGE_NAME_FILTER))
        if not selected:
            return
        stored = import_icon(selected, self._data_dir)
        if stored is None:
            self.error_label.setText(t("settings.island_icon.unusable"))
            self.error_label.show()
            return
        self._value = IMG_PREFIX + str(stored)
        self._sync()

    def reset(self) -> None:
        self._value = AUTO
        self._sync()

    def _sync(self) -> None:
        self.error_label.hide()
        value = self._value
        if value.startswith(IMG_PREFIX):
            pixmap = QPixmap(value[len(IMG_PREFIX):])
            if pixmap.isNull():
                self.tile.setIcon(vector_widget_icon(self.tile, "character", _PREVIEW_PX))
                self.state_label.setText(t("settings.island_icon.missing"))
            else:
                self.tile.setIcon(QIcon(pixmap))
                self.state_label.setText(t("settings.island_icon.custom"))
        elif value == AUTO:
            self.tile.setIcon(vector_widget_icon(self.tile, "pet", _PREVIEW_PX))
            self.state_label.setText(t("settings.island_icon.fish_avatar"))
        else:
            self.tile.setIcon(vector_widget_icon(self.tile, "character", _PREVIEW_PX))
            self.state_label.setText(t("settings.island_icon.emoji"))
        self.reset_button.setEnabled(value != AUTO)


def island_icon_row(dialog, island_cfg: dict):
    """建出选择器（挂在 ``dialog.island_icon_picker``），返回设置行。"""
    from .settings_widgets import SettingRow

    picker = IslandIconPicker(str(island_cfg.get("icon") or AUTO), dialog.config.dir, parent=dialog)
    dialog.island_icon_picker = picker
    return SettingRow("dynamic_island_icon_value", t("settings.dlg.icon"), t("settings.island_icon.hint"), picker)


def save_island_icon(dialog) -> str:
    """保存时取值，并把不再用的旧副本删掉。返回要写进 ``dynamic_island.icon`` 的值。"""
    picker = getattr(dialog, "island_icon_picker", None)
    if picker is None:
        return AUTO
    value = picker.value()
    prune_icons(dialog.config.dir, value)
    return value
