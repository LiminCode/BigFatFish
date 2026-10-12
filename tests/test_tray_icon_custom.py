# -*- coding: utf-8 -*-
"""自定义托盘图标：设置里指定一张图片就用它；没指定或图片用不了就回到默认（角色头像）。

默认图标取自角色当前帧，等比缩进托盘的小方格——角色是横长的，图标就显得很小。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

import tests.test_overlay_tray_icon as tray_tests
from pet import tray_icon

app = QApplication.instance() or QApplication([])

BLUE = QColor(20, 60, 220)
RED = QColor(200, 80, 80)


def _image_file(tmp_path, name="icon.png", *, size=200, margin=70, color=BLUE):
    """一张四周透明、中间一块实色的图片。"""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    for y in range(margin, size - margin):
        for x in range(margin, size - margin):
            image.setPixelColor(x, y, color)
    path = tmp_path / name
    assert image.save(str(path))
    return path


def _center(icon) -> QColor:
    return icon.pixmap(32).toImage().pixelColor(16, 16)


def _corner(icon) -> QColor:
    return icon.pixmap(32).toImage().pixelColor(1, 1)


# ---------------------------------------------------------------- 读图

def test_custom_image_fills_the_icon_after_trimming_its_transparent_margin(tmp_path):
    pixmap = tray_icon.load_custom_pixmap(str(_image_file(tmp_path)), 64)

    assert (pixmap.width(), pixmap.height()) == (64, 64)
    image = pixmap.toImage()
    assert image.pixelColor(1, 1) == BLUE and image.pixelColor(62, 62) == BLUE, \
        "透明留白要裁掉：否则图片主体在托盘里只占中间一小块"


def test_wide_images_keep_their_shape(tmp_path):
    image = QImage(300, 100, QImage.Format.Format_ARGB32)
    image.fill(BLUE)
    path = tmp_path / "wide.png"
    image.save(str(path))

    pixmap = tray_icon.load_custom_pixmap(str(path), 64)

    assert (pixmap.width(), pixmap.height()) == (64, 21), "不拉伸、不裁内容"


def test_unusable_choices_mean_no_custom_icon(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not an image")
    folder = tmp_path / "folder.png"
    folder.mkdir()

    for value in ("", "   ", None, str(tmp_path / "missing.png"), str(broken), str(folder)):
        assert tray_icon.load_custom_pixmap(value, 64) is None, value


# ---------------------------------------------------------------- 托盘

def _shell(tmp_path, **config):
    shell = tray_tests._make_shell(tmp_path)
    for key, value in config.items():
        shell._config.set(key, value)
    shell.icon_pixmap = lambda size=64: tray_tests._pixmap()      # 角色帧已就绪（红色）
    return shell


def test_tray_uses_the_custom_image_when_one_is_set(tmp_path):
    shell = _shell(tmp_path, tray_icon=str(_image_file(tmp_path)))
    try:
        assert _center(shell._tray_icon()) == BLUE

        shell._arm_tray_icon_refresh()
        assert _center(shell.tray.icon()) == BLUE, "首帧就绪后的刷新不能把自定义图标换回角色头像"
        assert getattr(shell, "_tray_icon_timer", None) is None, "自定义图标不依赖角色帧：不用起轮询"
    finally:
        shell._delete_runtime_marker()


def test_tray_falls_back_to_the_character_when_nothing_usable_is_set(tmp_path):
    for value in ("", str(tmp_path / "deleted-later.png")):
        shell = _shell(tmp_path, tray_icon=value)
        try:
            shell._arm_tray_icon_refresh()
            assert _center(shell.tray.icon()) == RED
        finally:
            shell._delete_runtime_marker()


def test_changing_the_setting_takes_effect_without_a_restart(tmp_path):
    shell = _shell(tmp_path)
    try:
        shell._arm_tray_icon_refresh()
        assert _center(shell.tray.icon()) == RED

        shell._config.set("tray_icon", str(_image_file(tmp_path)))
        shell.refresh_settings()
        assert _center(shell.tray.icon()) == BLUE

        shell._config.set("tray_icon", "")
        shell.refresh_settings()
        assert _center(shell.tray.icon()) == RED, "清空设置：回到默认的角色头像"
    finally:
        timer = getattr(shell, "_tray_icon_timer", None)
        if timer is not None:
            timer.stop()
        shell._delete_runtime_marker()


def test_the_custom_image_waits_for_nothing(tmp_path):
    """角色首帧还没解码时默认图标只能先用爪印占位；自定义图标不用等。"""
    shell = _shell(tmp_path, tray_icon=str(_image_file(tmp_path)))
    try:
        shell.icon_pixmap = lambda size=64: None
        assert _center(shell._tray_icon()) == BLUE
        assert shell._refresh_tray_icon_once() is True
    finally:
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- 设置页

def _dialog(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    return config, settings_mod, settings_mod.ModernSettingsDialog(config, include_ai=False)


def test_settings_offer_a_tray_icon_picker_that_persists(tmp_path, monkeypatch):
    from pet.config import Config

    config, settings_mod, dialog = _dialog(tmp_path, monkeypatch)
    image = _image_file(tmp_path)
    try:
        assert config.get("tray_icon") == "", "默认不指定：用角色头像"
        row = dialog.findChild(settings_mod.SettingRow, "settingRow_tray_icon")
        assert row is not None and dialog.tray_icon_picker.text() == ""
        dialog.tray_icon_picker.setText(f"  {image}  ")
        dialog._save()
    finally:
        dialog.deleteLater()

    assert Config(tmp_path).get("tray_icon") == str(image)
    _config, settings_mod, reopened = _dialog(tmp_path, monkeypatch)
    try:
        assert reopened.tray_icon_picker.text() == str(image)
        reopened.tray_icon_picker.setText("")
        reopened._save()
    finally:
        reopened.deleteLater()
    assert Config(tmp_path).get("tray_icon") == ""


def test_the_picker_says_so_when_the_chosen_file_is_not_a_usable_image(tmp_path, monkeypatch):
    _config, settings_mod, dialog = _dialog(tmp_path, monkeypatch)
    try:
        row = dialog.findChild(settings_mod.SettingRow, "settingRow_tray_icon")
        default_hint = row.hint_label.text()
        dialog.tray_icon_picker.setText(str(tmp_path / "missing.png"))
        assert "用不了" in row.hint_label.text() and "默认" in row.hint_label.text()
        dialog.tray_icon_picker.setText(str(_image_file(tmp_path)))
        assert row.hint_label.text() == default_hint
        dialog.tray_icon_picker.setText("")
        assert row.hint_label.text() == default_hint
    finally:
        dialog.deleteLater()
