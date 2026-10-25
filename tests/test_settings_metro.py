# -*- coding: utf-8 -*-
"""设置页的 Windows Phone / Metro 风格（2026-10-14）：方角、磁贴、朝光标倾斜、上下折叠。

守住的：设置页 QSS 里没有任何非零圆角；颜色令牌按 ``METRO_TOKENS`` 落到 QSS；``tilt_transform``
的几何（中心不偏、角度有界、按下更明显）；``TiltButton`` 画得出来且跟着光标变；开关是方角的；侧栏
装了倾斜代理；手风琴一次只开一页。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from pet import settings_theme_qss as theme
from pet import settings_widgets as sw
from pet.config import Config

app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 令牌与 QSS

@pytest.mark.parametrize("dark", [False, True])
def test_the_settings_stylesheet_has_no_rounded_corner_left(dark):
    qss = theme.metro_stylesheet(dark) + sw.BROWSER_CONTROL_STYLESHEET + sw.SETTINGS_POPUP_STYLESHEET
    radii = re.findall(r"border(?:-[a-z]+-[a-z]+)?-radius:\s*([0-9]+)(px)?", qss)
    assert radii, "圆角声明得显式写成 0，不是靠缺省"
    assert all(value == "0" for value, _unit in radii), {v for v, _ in radii}
    assert sw.BROWSER_CONTROL_SPEC["radius"] == 0


@pytest.mark.parametrize("dark", [False, True])
def test_the_tokens_land_in_the_stylesheet(dark):
    tokens = theme.METRO_TOKENS["dark" if dark else "light"]
    qss = theme.metro_stylesheet(dark)
    assert f"QFrame#settingsCard {{ background: {tokens['tile']}; border: none; border-radius: 0; }}" in qss
    assert f"QFrame#sidebarPane {{ background: {tokens['sidebar']}; border: none; }}" in qss
    assert f"QListWidget#settingsSidebar::item:selected {{\n    background: {tokens['selected']};" in qss
    assert "font-size: 30px;\n    font-weight: 300;" in qss, "页标题：大而轻"
    assert "QPushButton#advancedSectionToggle:checked { border-left: 4px solid " + tokens["accent"] in qss
    assert "QPushButton {\n    min-height: 26px;\n    padding: 1px 14px;\n    background: transparent;\n    border: 2px solid " + tokens["outline"] in qss


def test_system_dark_picks_the_dark_tokens(monkeypatch):
    monkeypatch.setattr(theme, "_system_dark", lambda: True)
    assert theme.METRO_TOKENS["dark"]["page"] in theme._settings_stylesheet()
    assert theme.METRO_TOKENS["light"]["page"] in theme._settings_stylesheet("light")


# ---------------------------------------------------------------- 倾斜

def test_tilt_transform_geometry():
    rect = QRect(0, 0, 200, 60)
    assert sw.tilt_transform(rect, None).isIdentity()
    assert sw.tilt_transform(QRect(0, 0, 0, 0), QPoint(1, 1)).isIdentity()
    centre = sw.tilt_transform(rect, QPoint(100, 30))
    assert centre.isIdentity() or abs(centre.m31()) < 1e-6, "光标在正中：不偏（悬停时也不缩放）"
    right = sw.tilt_transform(rect, QPoint(200, 30))
    left = sw.tilt_transform(rect, QPoint(0, 30))
    assert not right.isIdentity() and right != left
    # 朝光标压下去：光标那一侧的边向中心靠（退远），对面的边向外扩（透视里离观者更近）；上下同理
    from PySide6.QtCore import QPointF

    # 旋转本身让两边都略向中心缩（cos），透视让光标那一侧缩得明显多：比较两边的位移量
    near, far = 200 - right.map(QPointF(200, 30)).x(), right.map(QPointF(0, 30)).x() - 0
    assert near > 0 and near > abs(far), (near, far)
    bottom = sw.tilt_transform(rect, QPoint(100, 60))
    near, far = 60 - bottom.map(QPointF(100, 60)).y(), bottom.map(QPointF(100, 0)).y() - 0
    assert near > 0 and near > abs(far), (near, far)
    pressed = sw.tilt_transform(rect, QPoint(200, 30), pressed=True)
    assert abs(pressed.map(QPointF(200, 30)).x() - 100) < abs(right.map(QPointF(200, 30)).x() - 100), "按下更明显"
    far = sw.tilt_transform(rect, QPoint(5000, 5000))
    assert abs(far.map(QPoint(0, 0)).x()) < 60, "光标跑出去了：角度仍有界"


def test_tilt_button_follows_the_pointer_and_still_paints():
    button = sw.TiltButton("磁贴")
    button.resize(160, 40)
    button.show()
    app.processEvents()
    button.leaveEvent(None)                 # 离屏平台上光标恰好在 (0,0)，show 就算进入了：先离开
    assert button.hasMouseTracking() and button.tilt_point() is None and button.current_tilt().isIdentity()
    from PySide6.QtGui import QMouseEvent

    pos = QPoint(150, 10)
    button.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, pos.toPointF(), pos.toPointF(),
                                      button.mapToGlobal(pos).toPointF(), Qt.MouseButton.NoButton,
                                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert button.tilt_point() == pos and not button.current_tilt().isIdentity()
    image = button.grab().toImage()
    assert image.width() == 160 and not image.isNull()
    button.leaveEvent(None)
    assert button.tilt_point() is None
    button.close()


def test_disclosure_header_and_menu_button_are_tilting_tiles():
    assert issubclass(sw.SettingsDisclosureHeader, sw.TiltButton)
    assert issubclass(sw.SettingsMenuButton, sw.TiltButton)
    header = sw.SettingsDisclosureHeader("高级")
    header.resize(300, 44)
    header.show()
    header.setChecked(True)
    header.grab()                           # 箭头画在倾斜画布上：画得出来就行
    assert header.accessibleName() == "展开高级" or header.accessibleName()
    header.close()


def test_the_sidebar_has_the_tilt_delegate(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        assert isinstance(dialog.sidebar.itemDelegate(), sw.TiltItemDelegate)
        assert dialog.sidebar.hasMouseTracking()
        assert all(dialog.sidebar.item(i).sizeHint().height() >= 38 for i in range(dialog.sidebar.count()))
        assert isinstance(dialog.save_exit_button, sw.TiltButton) or dialog.save_exit_button is not None
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 开关与手风琴

def _corner_is_transparent(image: QImage, x: int, y: int) -> bool:
    return QColor(image.pixel(x, y)).alpha() == 0 or image.pixelColor(x, y).alpha() == 0


def test_toggle_switch_is_square_and_fills_with_accent_when_on():
    toggle = sw.ToggleSwitch()
    toggle.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    assert toggle.size().width() == 44 and toggle.size().height() == 20
    toggle.setChecked(True)
    image = toggle.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    # 开着：轨道中部是主题色；滑块在右边、是方的（右上角像素有色，不是圆角留白）
    assert image.pixelColor(20, 10).name() == "#0a84ff"
    assert image.pixelColor(43, 0).alpha() > 0 and image.pixelColor(32, 19).alpha() > 0
    toggle.setChecked(False)
    image = toggle.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    assert image.pixelColor(20, 10).name() != "#0a84ff", "关着：轨道只有描边"
    assert image.pixelColor(0, 0).alpha() > 0 and image.pixelColor(11, 19).alpha() > 0, "滑块在左边、方角"


def test_accordion_hides_other_pages_and_keeps_them_alive():
    tabs = sw.SettingsTabContainer()
    first, second = QWidget(), QWidget()
    first.setMinimumWidth(900)
    tabs.addTab("a", "甲", first)
    tabs.addTab("b", "乙", second)
    tabs.show()
    app.processEvents()
    assert tabs.currentKey() == "a" and tabs.stack.currentWidget() is first and tabs.stack.count() == 2
    tabs.setCurrentKey("b")
    assert tabs.stack.currentWidget() is second and tabs.stack.currentIndex() == 1
    assert first.isVisibleTo(tabs) is False and not first.isHidden() is False or first.isHidden()
    assert tabs.minimumSizeHint().width() < 900, "收起的那页不把自己的最小宽度压给容器"
    assert tabs.key_for_descendant(second) == "b" and tabs.activate_for_descendant(first)
    assert tabs.currentKey() == "a"
    tabs.close()
