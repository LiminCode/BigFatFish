# -*- coding: utf-8 -*-
"""设置页「桌面组件 · 图标」：点图标直接弹出选文件，用户换成自己的图片（2026-10-20 用户要求）。

以前是下拉框（鱼本体头像 / 十个 emoji），用户没法放自己的图。现在：

- 点那个图标方块 = 直接打开系统选文件对话框（从「图片」文件夹开始，只列图片）；
- 选中的图片缩到最长边 128 像素、存成 PNG，**复制进肥鱼自己的配置目录**——原文件以后移走 / 删掉都不影响；
- 「用鱼本体头像」回到默认；保存时把不再用的旧副本清掉；
- 选的不是能读的图片：不改，提示一句；取消：不改；
- 旧配置里的 emoji 不动它就原样保存（岛照旧会画）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import settings_island_icon as sii
from pet.config import Config

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, icon: str | None = None, language: str = "zh"):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path / "cfg")
    config.set("ui_language", language)
    if icon is not None:
        config.set("dynamic_island", {**config.get("dynamic_island"), "icon": icon})
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def _image(path: Path, width=1000, height=600, color="#ff3366") -> Path:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))
    return path


def _pick(monkeypatch, result: str):
    """替换系统对话框：记下被怎么调用，返回 ``result``（空串 = 用户取消）。"""
    asked = []

    def fake(parent, title, start, name_filter):
        asked.append({"title": title, "start": start, "filter": name_filter})
        return result, ""

    monkeypatch.setattr(sii.QFileDialog, "getOpenFileName", staticmethod(fake))
    return asked


def _save_island(dialog):
    assert dialog._write_config()


def test_the_icon_row_is_a_clickable_tile_not_a_dropdown(tmp_path, monkeypatch):
    from pet.settings_widgets import ModernSelect, SettingRow

    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        row = dialog.findChild(SettingRow, "settingRow_dynamic_island_icon_value")
        assert row is not None
        picker = dialog.island_icon_picker
        assert isinstance(picker, sii.IslandIconPicker) and row.isAncestorOf(picker)
        assert not row.findChildren(ModernSelect), "不再是下拉框"
        assert picker.value() == "auto"
        assert picker.state_label.text() == "鱼本体头像"
        assert not picker.reset_button.isEnabled(), "已经是默认：「用鱼本体头像」不可点"
        assert picker.tile.toolTip() == "点一下选一张图片"
    finally:
        _close(dialog)


def test_clicking_the_tile_opens_the_file_chooser_and_stores_a_copy(tmp_path, monkeypatch):
    source = _image(tmp_path / "my-photo.jpg")
    asked = _pick(monkeypatch, str(source))
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        picker = dialog.island_icon_picker
        picker.tile.click()

        assert len(asked) == 1, "点一下就直接弹出选文件，不经过菜单"
        assert "*.png" in asked[0]["filter"] and "*.jpg" in asked[0]["filter"]
        assert Path(asked[0]["start"]).is_dir()
        value = picker.value()
        assert value.startswith("img:")
        stored = Path(value[len("img:"):])
        assert stored.parent == Path(config.dir) / sii.ICON_DIR, "复制进肥鱼自己的配置目录"
        assert stored.suffix == ".png" and stored.exists()
        copy = QImage(str(stored))
        assert max(copy.width(), copy.height()) == sii.MAX_EDGE, "缩到最长边 128，岛不用常驻一张大图"
        assert copy.width() > copy.height(), "保持宽高比"
        assert picker.state_label.text() == "我的图片" and picker.reset_button.isEnabled()
        assert not picker.tile.icon().isNull(), "方块里显示选中的图"

        _save_island(dialog)
        assert config.get("dynamic_island")["icon"] == value
    finally:
        _close(dialog)


def test_the_island_still_shows_the_icon_after_the_original_is_deleted(tmp_path, monkeypatch):
    from pet.dynamic_island import DynamicIsland

    source = _image(tmp_path / "gone-later.png", 64, 64)
    _pick(monkeypatch, str(source))
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.island_icon_picker.tile.click()
        _save_island(dialog)
    finally:
        _close(dialog)
    source.unlink()
    island = DynamicIsland(config)
    try:
        pixmap = island._icon_pixmap()
        assert pixmap is not None and not pixmap.isNull()
        assert pixmap.toImage().pixelColor(32, 32).name() == "#ff3366"
    finally:
        island.deleteLater()
        app.processEvents()


def test_cancelling_the_chooser_changes_nothing(tmp_path, monkeypatch):
    asked = _pick(monkeypatch, "")
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.island_icon_picker.tile.click()
        assert len(asked) == 1 and dialog.island_icon_picker.value() == "auto"
        assert not (Path(config.dir) / sii.ICON_DIR).exists()
    finally:
        _close(dialog)


def test_a_file_that_is_not_an_image_is_refused_with_a_reason(tmp_path, monkeypatch):
    bogus = tmp_path / "notes.png"
    bogus.write_text("not really a png", encoding="utf-8")
    _pick(monkeypatch, str(bogus))
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        picker = dialog.island_icon_picker
        picker.tile.click()
        assert picker.value() == "auto"
        assert picker.error_label.text() == "这个文件不是肥鱼读得了的图片，图标没换。"
        assert not picker.error_label.isHidden()
    finally:
        _close(dialog)


def test_reset_goes_back_to_the_fish_avatar_and_saving_cleans_old_copies(tmp_path, monkeypatch):
    first, second = _image(tmp_path / "a.png", 50, 50, "#112233"), _image(tmp_path / "b.png", 50, 50, "#445566")
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        picker = dialog.island_icon_picker
        _pick(monkeypatch, str(first))
        picker.tile.click()
        _pick(monkeypatch, str(second))
        picker.tile.click()
        folder = Path(config.dir) / sii.ICON_DIR
        assert len(list(folder.glob("*.png"))) == 2
        _save_island(dialog)
        assert [p.name for p in folder.glob("*.png")] == [Path(picker.value()[4:]).name], "只留正在用的那张"

        picker.reset_button.click()
        assert picker.value() == "auto" and picker.state_label.text() == "鱼本体头像"
        assert not picker.reset_button.isEnabled()
        _save_island(dialog)
        assert config.get("dynamic_island")["icon"] == "auto"
        assert list(folder.glob("*.png")) == [], "回到默认：副本也清掉"
    finally:
        _close(dialog)


def test_an_emoji_from_an_older_setting_is_kept_until_the_user_changes_it(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, icon="🐳")
    try:
        picker = dialog.island_icon_picker
        assert picker.value() == "🐳"
        assert picker.state_label.text() == "表情图标（旧设置）"
        assert picker.reset_button.isEnabled()
        _save_island(dialog)
        assert config.get("dynamic_island")["icon"] == "🐳"
    finally:
        _close(dialog)


def test_the_row_hides_with_the_show_icon_switch(tmp_path, monkeypatch):
    from pet.settings_widgets import SettingRow

    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        row = dialog.findChild(SettingRow, "settingRow_dynamic_island_icon_value")
        dialog.island_icon_check.setChecked(False)
        assert row.isHidden()
        dialog.island_icon_check.setChecked(True)
        assert not row.isHidden()
    finally:
        _close(dialog)


def test_english(tmp_path, monkeypatch):
    bogus = tmp_path / "x.png"
    bogus.write_text("nope", encoding="utf-8")
    asked = _pick(monkeypatch, str(bogus))
    config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        picker = dialog.island_icon_picker
        assert picker.state_label.text() == "Fish avatar"
        assert picker.reset_button.text() == "Use fish avatar"
        assert picker.tile.toolTip() == "Click to choose an image"
        picker.tile.click()
        assert asked[0]["title"] == "Choose an island icon"
        assert picker.error_label.text() == "That file isn't an image the fish can read, so the icon didn't change."
    finally:
        _close(dialog)
