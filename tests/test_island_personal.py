# -*- coding: utf-8 -*-
"""灵动岛上的「个人助理」小人形：排在简报图标右边、铃铛左边；三种状态；点一下发信号；app 把控制器的状态推给它。"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import i18n
from tests.test_island_notifications import _island

app = QApplication.instance() or QApplication([])


def _release(island, pos: QPointF):
    event = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, island.mapToGlobal(pos.toPoint()).toPointF(),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    island.mouseReleaseEvent(event)


def test_the_person_icon_sits_between_briefing_and_bell_and_takes_its_own_slot(tmp_path):
    island = _island(tmp_path)
    try:
        base = island._capsule_width()
        assert island.personal_button_rect() is None and island.personal_tooltip() == ""
        island.set_personal_state("idle")
        assert island._capsule_width() > base and island.personal_tooltip() == "个人助理"
        alone = island.personal_button_rect()
        island.set_briefing_state("idle")
        island.set_notification_count(0)
        brief, person, bell = island.briefing_button_rect(), island.personal_button_rect(), island.notification_button_rect()
        assert brief.right() <= person.left() < person.right() <= bell.left(), "简报 · 个人 · 铃铛，从左到右，可点区不重叠"
        assert person.left() > alone.left(), "简报出现后往右挪"
        island.set_personal_state("hidden")
        island.set_briefing_state("hidden")
        island.set_notification_count(None)
        assert island.personal_button_rect() is None and island._capsule_width() == base
    finally:
        island.deleteLater()
        app.processEvents()


def test_unread_changes_the_tooltip_and_the_cache_key_and_a_click_asks_for_the_window(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_personal_state("unread")
        assert island.personal_tooltip() == "个人助理 · 有一份新的简报"
        island.set_personal_state("bogus")
        assert island.personal_tooltip() == "" and island._personal_state == "hidden"
        island.set_personal_state("idle")
        app.processEvents()
        key_idle = island._content_cache_key
        island.set_personal_state("unread")
        island._content_cache()
        assert island._content_cache_key != key_idle, "状态进缓存键，否则图标不重画"
        asked = []
        island.personal_requested.connect(lambda: asked.append(1))
        island._dragging = False
        _release(island, island.personal_button_rect().center())
        assert asked == [1]
        i18n.set_language("en")
        assert island.personal_tooltip() == "Personal assistant · a fresh briefing is in"
    finally:
        i18n.set_language("zh")
        island.deleteLater()
        app.processEvents()


def test_the_app_pushes_the_controller_state_to_the_island(tmp_path):
    from pet.app import AppShell

    island = _island(tmp_path)
    try:
        fake = SimpleNamespace(island=island, _personal=None)
        AppShell._push_island_personal_state(fake)
        assert island._personal_state == "hidden"
        fake._personal = SimpleNamespace(island_state="unread", open_window=lambda: None)
        AppShell._push_island_personal_state(fake)
        assert island._personal_state == "unread"
        opened = []
        fake._personal = SimpleNamespace(island_state="idle", open_window=lambda: opened.append(1))
        AppShell._open_personal_from_island(fake)
        assert opened == [1]
    finally:
        island.deleteLater()
        app.processEvents()
    assert QPoint(0, 0) is not None
