# -*- coding: utf-8 -*-
"""气泡配图按原始大小显示，长边超过上限才等比缩小。

此前配图不论多大都被塞进一个固定的框（标准气泡 220×140，吐气水泡再小一些）：
2000 像素的照片和 300 像素的动图显示出来一样大，小图还会被放大。

纪律：offscreen（DPR=1）；显示尺寸从气泡实际画出来的像素量，不读私有几何。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.speech_bubble import PetSpeechBubble
from pet.speech_bubble_text import (
    SELF_TALK_IMAGE_MAX_EDGE_DEFAULT,
    clamp_image_max_edge,
    natural_image_size,
)

app = QApplication.instance() or QApplication([])

MAGENTA = QColor(255, 0, 255)
ANCHOR = QRect(900, 600, 200, 160)


def _image(tmp_path, width, height, name=None):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(MAGENTA)
    path = tmp_path / (name or f"{width}x{height}.png")
    assert image.save(str(path))
    return path


def _drawn_size(bubble) -> tuple[int, int]:
    """气泡里实际画出来的图片有多大：量品红像素的外接框。"""
    image = bubble.grab().toImage()
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.red() > 200 and c.green() < 90 and c.blue() > 200:
                xs.append(x)
                ys.append(y)
    assert xs, "气泡里没有画出图片"
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _show(tmp_path, style, width, height, *, max_edge, scale=1.0):
    bubble = PetSpeechBubble(None, style)
    path = _image(tmp_path, width, height)
    assert bubble.show_image(path, ANCHOR, 5000, pet_scale=0.72, image_scale=scale,
                             image_max_edge=max_edge, pixmap=QPixmap(str(path)))
    return bubble


def _close(*bubbles):
    for bubble in bubbles:
        bubble.close()
        bubble.deleteLater()


# ---------------------------------------------------------------- 尺寸规则

@pytest.mark.parametrize("source, max_edge, expected", [
    ((300, 317), 360, (300, 317)),        # 比上限小：原样
    ((1968, 1088), 360, (360, 199)),      # 横图：长边压到上限
    ((2308, 3929), 360, (211, 360)),      # 竖图
    ((360, 360), 360, (360, 360)),
    ((4000, 10), 360, (360, 1)),          # 极端长宽比也不会得到 0
])
def test_images_keep_their_size_until_the_long_edge_passes_the_limit(source, max_edge, expected):
    assert natural_image_size(QSize(*source), max_edge) == QSize(*expected)


def test_scale_applies_before_the_limit():
    assert natural_image_size(QSize(300, 200), 360, scale=0.5) == QSize(150, 100)
    assert natural_image_size(QSize(300, 200), 360, scale=2.0) == QSize(360, 240), "放大也受上限约束"


def test_the_limit_itself_is_clamped_to_a_sane_range():
    assert clamp_image_max_edge(None) == SELF_TALK_IMAGE_MAX_EDGE_DEFAULT
    assert clamp_image_max_edge("abc") == SELF_TALK_IMAGE_MAX_EDGE_DEFAULT
    assert clamp_image_max_edge(5) == 160 and clamp_image_max_edge(99999) == 800
    assert clamp_image_max_edge(421.6) == 422


# ---------------------------------------------------------------- 标准气泡

def test_a_small_image_is_shown_at_its_own_size_and_a_big_one_at_the_limit(tmp_path):
    small = _show(tmp_path, "paper_left", 300, 180, max_edge=360)
    big = _show(tmp_path, "paper_left", 1968, 1088, max_edge=360)
    try:
        assert _drawn_size(small) == pytest.approx((300, 180), abs=2), "没有被缩进固定的框，也没有被放大"
        assert _drawn_size(big) == pytest.approx((360, 199), abs=2)
        assert big.width() > small.width(), "气泡跟着图片的大小走"
    finally:
        _close(small, big)


def test_raising_the_limit_lets_big_images_grow(tmp_path):
    tight = _show(tmp_path, "paper_left", 1968, 1088, max_edge=240)
    roomy = _show(tmp_path, "paper_left", 1968, 1088, max_edge=600)
    try:
        assert _drawn_size(tight)[0] == pytest.approx(240, abs=2)
        assert _drawn_size(roomy)[0] == pytest.approx(600, abs=2)
    finally:
        _close(tight, roomy)


def test_without_a_limit_the_old_fixed_box_still_applies(tmp_path):
    """旧调用方（不传上限）行为不变：仍是 220×140 的框乘配图大小。"""
    bubble = PetSpeechBubble(None, "paper_left")
    path = _image(tmp_path, 1968, 1088)
    try:
        assert bubble.show_image(path, ANCHOR, 5000, image_scale=1.0)
        assert _drawn_size(bubble)[0] == pytest.approx(220, abs=2)
    finally:
        _close(bubble)


# ---------------------------------------------------------------- 吐气水泡

def test_the_breath_bubble_never_grows_past_the_limit_and_never_enlarges_a_small_image(tmp_path):
    big = _show(tmp_path, "breath_bubble", 1968, 1088, max_edge=420)
    tall = _show(tmp_path, "breath_bubble", 2308, 3929, max_edge=420)
    small = _show(tmp_path, "breath_bubble", 120, 90, max_edge=420)
    try:
        for bubble in (big, tall):
            assert bubble.width() <= 420, "上限约束的是整个气泡"
            drawn = _drawn_size(bubble)
            assert drawn[0] <= bubble.width() and drawn[1] <= bubble.height()
        assert big.width() > small.width(), "大图得到更大的气泡"
        assert _drawn_size(small) == pytest.approx((120, 90), abs=3), "小图不被放大去填满水泡"
    finally:
        _close(big, tall, small)


def test_the_breath_bubble_shows_big_images_larger_than_the_old_fixed_size(tmp_path):
    old = PetSpeechBubble(None, "breath_bubble")
    path = _image(tmp_path, 1968, 1088)
    assert old.show_image(path, ANCHOR, 5000, pet_scale=0.72, image_scale=1.0)
    new = _show(tmp_path, "breath_bubble", 1968, 1088, max_edge=420)
    try:
        assert _drawn_size(new)[0] > _drawn_size(old)[0] * 1.4
    finally:
        _close(old, new)


# ---------------------------------------------------------------- 配置

def test_the_limit_is_a_persisted_setting_with_a_default(tmp_path):
    config = Config(tmp_path)
    assert config.get("self_talk_image_max_edge") == SELF_TALK_IMAGE_MAX_EDGE_DEFAULT
    config.set("self_talk_image_max_edge", 520)
    config.save()
    assert Config(tmp_path).get("self_talk_image_max_edge") == 520
    config.set("self_talk_image_max_edge", 99999)
    config.save()
    assert Config(tmp_path).get("self_talk_image_max_edge") == 800
    config.set("self_talk_image_max_edge", "abc")
    config.save()
    assert Config(tmp_path).get("self_talk_image_max_edge") == SELF_TALK_IMAGE_MAX_EDGE_DEFAULT


def test_settings_offer_the_limit_next_to_the_image_scale(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
    try:
        row = dialog.findChild(settings_mod.SettingRow, "settingRow_self_talk_image_max_edge")
        assert row is not None
        assert dialog.self_talk_image_max_edge_spin.value() == SELF_TALK_IMAGE_MAX_EDGE_DEFAULT
        dialog.self_talk_image_max_edge_spin.setValue(480)
        dialog._save()
    finally:
        dialog.deleteLater()
    assert Config(tmp_path).get("self_talk_image_max_edge") == 480


# ---------------------------------------------------------------- 桌宠（单合成窗壳）

def _talk_shell(tmp_path, **values):
    import tests.test_overlay_self_talk as st

    shell, _config = st._make_shell(tmp_path, st._talk_values(self_talk_image_chance=100, **values))
    return st, shell


def test_the_pet_shows_pictures_with_the_configured_limit(tmp_path):
    import time

    st, shell = _talk_shell(tmp_path, self_talk_image_max_edge=520, self_talk_image_scale=150)
    try:
        path = st._write_png(tmp_path / "imgs")
        shell._self_talk_images = [path]
        shell._self_talk_image_cache = {str(path): QPixmap(str(path)).toImage()}
        shell._self_talk_images_checked_at = time.monotonic()
        seen: dict = {}
        shell._bubble_follower.show_image = lambda _path, _ms, **kw: (seen.update(kw), True)[1]

        assert shell._show_random_self_talk() is True
        assert seen["image_max_edge"] == 520 and seen["image_scale"] == 1.5
    finally:
        st._cleanup(shell)


def test_pictures_added_while_running_join_the_pool_without_a_restart(tmp_path):
    import tests.test_overlay_self_talk_image_cache as cache_tests

    folder = tmp_path / "pool"
    first = _image(folder_ready(folder), 60, 40, "first.png")
    st, shell = _talk_shell(tmp_path, self_talk_image_dir=str(folder))
    try:
        assert shell._self_talk_images == [first]
        second = _image(folder, 60, 40, "second.gif.png")
        (folder / "notes.txt").write_text("不是图片", encoding="utf-8")
        shell._self_talk_images_checked_at = 0.0          # 让下一次自言自语重新看一眼目录
        shell._bubble_follower.show_image = lambda *_a, **_k: True

        shell._show_random_self_talk()

        assert shell._self_talk_images == [first, second], "新图片进来了，非图片文件不算"
        assert cache_tests._wait_for(lambda: str(second) in shell._self_talk_image_cache), "新图片也要预热进缓存"
    finally:
        st._cleanup(shell)


def folder_ready(folder):
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_the_decode_cache_is_sized_by_the_limit_and_the_screen_scale():
    from pet.overlay_shell import self_talk_image_cache_edge_for_limit as edge

    assert edge(420, 1.0) == 462 and edge(420, 1.25) == 578 and edge(420, 2.0) == 924
    assert edge(800, 1.0) > edge(420, 1.0) > edge(160, 1.0)
    assert edge(5, 1.0) == edge(160, 1.0) and edge(99999, 1.0) == edge(800, 1.0), "上限先收进可用区间"
    assert edge(420, 0.5) == edge(420, 1.0), "读不到屏幕缩放时不按更省内存的方向裁"
    assert edge(420, 1.25, "breath_bubble") == 318, "吐气水泡里图片只画到水泡宽的 55%：缓存不必留到上限"
    assert edge(420, 1.25, "paper_left") == edge(420, 1.25, "") == 578


@pytest.mark.parametrize("style", ["breath_bubble", "paper_left", "glass_right"])
def test_the_cache_keeps_enough_pixels_for_what_the_bubble_actually_draws(tmp_path, style):
    """缓存按「实际画到的长边」留像素：不能比气泡真正画出来的尺寸小（否则发糊）。"""
    from pet.speech_bubble import image_display_edge

    bubble = _show(tmp_path, style, 3000, 3000, max_edge=420)
    wide = _show(tmp_path, style, 3000, 600, max_edge=420)
    try:
        for shown in (bubble, wide):
            assert max(_drawn_size(shown)) <= image_display_edge(420, style) + 1
    finally:
        _close(bubble, wide)
