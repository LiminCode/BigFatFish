# -*- coding: utf-8 -*-
"""PetSprite.caption：sprite 自带的一行常驻标签（会话小鱼的「标题 · 状态」）。

标签画在 sprite 自己的画布矩形之内（身体框上方 / 下方的透明留白），所以不需要
额外的脏区上报：sprite 移动、重绘时它跟着一起走。现有的气泡是自言自语 / 点击
台词共用的，会被顶掉，不能当名牌。
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from pet import catalog
from tests.test_pet_sprite import FakeClip, _make_sprite

app = QApplication.instance() or QApplication([])


def _sprite(caption: str = "", *, below: bool = False):
    clip = FakeClip()
    clip.image = QImage(catalog.CANVAS_W, catalog.CANVAS_H, QImage.Format.Format_ARGB32)
    clip.image.fill(0)                     # 全透明帧：画面里出现的任何像素都来自标签
    sprite = _make_sprite(clip)
    # 真角色才有身体框（manifest 的 body_box）：标签要贴着它摆，替身库得报上角色名
    sprite.library.character_id = catalog.DEFAULT_CHARACTER
    assert catalog.character_body_box(catalog.DEFAULT_CHARACTER) is not None
    assert sprite.bind_clip("idle") is True
    sprite.caption_below = below
    sprite.caption = caption
    return sprite


def _painted(sprite) -> QImage:
    rect = sprite.rect()
    image = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.translate(-rect.x(), -rect.y())
    sprite.paint(painter)
    painter.end()
    return image


def _inked_rows(image: QImage) -> list[int]:
    return [y for y in range(image.height())
            if any(image.pixelColor(x, y).alpha() > 0 for x in range(0, image.width(), 2))]


def test_no_caption_paints_nothing_extra():
    assert _inked_rows(_painted(_sprite(""))) == []


def test_caption_is_painted_above_the_body_inside_the_canvas():
    sprite = _sprite("dsh-pet · 写代码中")
    rows = _inked_rows(_painted(sprite))
    body_top = sprite.body_rect().top() - sprite.rect().top()

    assert rows, "有标签就得画出来"
    assert rows[0] >= 0 and rows[-1] < body_top, "默认贴在身体框上方，不盖住身体"


def test_caption_can_sit_below_the_body():
    sprite = _sprite("dsh-pet · 休息中", below=True)
    rows = _inked_rows(_painted(sprite))
    body_bottom = sprite.body_rect().bottom() - sprite.rect().top()

    # 身体框下方的留白比标签矮（shenshen 在 0.5 倍时只有 15px）：宁可压住身体底边
    # 几个像素，也不画出画布矩形——画出去的部分移动时会留残影。
    assert rows and rows[0] > body_bottom - sprite.caption_rect().height() // 2
    assert rows[-1] < sprite.rect().height()


def test_long_caption_is_elided_to_the_canvas_width():
    sprite = _sprite("一个特别特别特别特别特别特别特别特别特别特别特别特别长的会话标题 · 写代码中")
    image = _painted(sprite)
    row = _inked_rows(image)[len(_inked_rows(image)) // 2]
    inked = [x for x in range(image.width()) if image.pixelColor(x, row).alpha() > 0]
    assert inked[0] >= 0 and inked[-1] < image.width()
    assert sprite.caption_rect().width() <= sprite.rect().width()


def test_caption_text_layout_is_measured_once_per_text(monkeypatch):
    """标签每帧都画（144Hz）：字体度量只在文本或画布宽度变化时重算。

    实机 py-spy（5 只会话小鱼）：每帧新建 QFont + QFontMetrics 占了 GUI 线程约 9%。
    """
    from pet import pet_sprite as pet_sprite_mod

    calls = []
    real = pet_sprite_mod.QFontMetrics

    def _counting(font):
        calls.append(1)
        return real(font)

    monkeypatch.setattr(pet_sprite_mod, "QFontMetrics", _counting)
    sprite = _sprite("dsh-pet · 写代码中")
    for _ in range(5):
        _painted(sprite)
    sprite.set_pos(sprite.pos + type(sprite.pos)(40, 0))      # 移动不改变文本排版
    _painted(sprite)
    assert len(calls) == 1

    sprite.caption = "dsh-pet · 休息中"
    _painted(sprite)
    assert len(calls) == 2


def test_caption_is_rendered_once_and_blitted_afterwards():
    """胶囊 + 文字只渲染一次，之后每帧贴图。

    实机 py-spy（6 只会话小鱼，144Hz）：每帧 drawRoundedRect + drawText 约占 GUI
    线程 11%，即每只约 1.8% 的单核。
    """
    sprite = _sprite("dsh-pet · 写代码中")
    _painted(sprite)
    first = sprite.caption_pixmap()
    assert first is not None and not first.isNull()
    for _ in range(3):
        _painted(sprite)
    sprite.set_pos(sprite.pos + type(sprite.pos)(40, 0))
    _painted(sprite)
    assert sprite.caption_pixmap().cacheKey() == first.cacheKey(), "文本没变就不重画"

    sprite.caption = "dsh-pet · 休息中"
    _painted(sprite)
    assert sprite.caption_pixmap().cacheKey() != first.cacheKey()
    sprite.caption = ""
    assert sprite.caption_pixmap() is None


def test_caption_rect_is_empty_without_text_and_inside_rect_with_it():
    assert _sprite("").caption_rect() == QRect()
    sprite = _sprite("x")
    assert sprite.rect().contains(sprite.caption_rect())
