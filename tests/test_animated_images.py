# -*- coding: utf-8 -*-
"""配图里的动图要动起来：自言自语气泡与彩蛋弹窗。

配图池里放 GIF 一直是允许的（后缀在清单里），但两处都用 ``QPixmap`` 读，只显示
第一帧。这里钉住：动图会换帧、至少播完一遍、看不见时停止解码；静态图的路径不变。

纪律：offscreen；动图用 Pillow 现场生成；换帧靠真实 Qt 定时器，用带宽预算的事件
循环轮询等到，不固定 sleep。
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication

from pet import animated_image
from pet.speech_bubble import ANIMATED_IMAGE_MAX_MS, PetSpeechBubble

app = QApplication.instance() or QApplication([])

COLORS = [(220, 30, 30), (30, 200, 30), (30, 30, 220), (230, 230, 30)]
ANCHOR = QRect(600, 600, 200, 200)


def _gif(path, colors=COLORS, frame_ms=40, size=(64, 48)):
    frames = [Image.new("RGB", size, color) for color in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=frame_ms, loop=0)
    return path


def _png(path):
    Image.new("RGB", (64, 48), (10, 120, 200)).save(path)
    return path


def _pump(predicate, budget_s: float = 20.0) -> bool:
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
    return False


def _center_color(bubble) -> tuple[int, int, int]:
    image = bubble._source_pixmap.toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return color.red(), color.green(), color.blue()


@pytest.fixture
def bubble():
    widget = PetSpeechBubble()
    yield widget
    widget.close()
    widget.deleteLater()


# ---------------------------------------------------------------- 识别
def test_only_multi_frame_images_are_treated_as_animations(tmp_path):
    movie = animated_image.open_movie(_gif(tmp_path / "moving.gif"))
    assert isinstance(movie, QMovie) and movie.frameCount() == len(COLORS)
    assert animated_image.loop_duration_ms(movie) == len(COLORS) * 40
    movie.deleteLater()

    assert animated_image.open_movie(_gif(tmp_path / "still.gif", colors=COLORS[:1])) is None, \
        "单帧 GIF 就是一张静态图"
    assert animated_image.open_movie(_png(tmp_path / "photo.png")) is None
    assert animated_image.open_movie(tmp_path / "missing.gif") is None
    (tmp_path / "broken.gif").write_bytes(b"GIF89a not really")
    assert animated_image.open_movie(tmp_path / "broken.gif") is None


# ---------------------------------------------------------------- 气泡
def test_bubble_plays_an_animated_gif(bubble, tmp_path):
    assert bubble.show_image(_gif(tmp_path / "moving.gif"), ANCHOR, 3000) is True
    assert bubble._movie is not None and bubble._movie.state() == QMovie.MovieState.Running

    seen = {_center_color(bubble)}
    assert _pump(lambda: seen.add(_center_color(bubble)) or len(seen) >= 3), \
        f"画面一直停在同一帧：{seen}"


def test_frames_are_swapped_without_rebuilding_the_bubble_geometry(bubble, tmp_path):
    bubble.show_image(_gif(tmp_path / "moving.gif"), ANCHOR, 3000)
    key, size, first = bubble._image_paint_key(), bubble.size(), _center_color(bubble)
    assert _pump(lambda: _center_color(bubble) != first)
    assert bubble._image_paint_key() == key and bubble.size() == size, \
        "换帧只重画配图那一块，不重排气泡"


def test_bubble_stays_long_enough_for_one_loop_but_not_forever(bubble, tmp_path):
    bubble.show_image(_gif(tmp_path / "long.gif", colors=COLORS * 10, frame_ms=100), ANCHOR, 800)
    assert bubble._hide_timer.interval() == 4000, "40 帧 × 100ms：播完一遍再收"

    bubble.show_image(_gif(tmp_path / "huge.gif", colors=COLORS * 50, frame_ms=100), ANCHOR, 800)
    assert bubble._hide_timer.interval() == ANIMATED_IMAGE_MAX_MS, "一遍太长的截到上限"

    bubble.show_image(_gif(tmp_path / "short.gif", frame_ms=20), ANCHOR, 3000)
    assert bubble._hide_timer.interval() == 3000, "比原定时长短的动图循环播，时长不变"


def test_playback_stops_when_the_bubble_is_hidden_or_shows_something_else(bubble, tmp_path):
    gif = _gif(tmp_path / "moving.gif")
    bubble.show_image(gif, ANCHOR, 3000)
    bubble.hide()
    assert bubble._movie is None, "看不见了就不再解码"

    bubble.show_image(gif, ANCHOR, 3000)
    bubble.show_text("换成一句话", ANCHOR, 1000)
    assert bubble._movie is None

    bubble.show_image(gif, ANCHOR, 3000)
    first = bubble._movie
    bubble.show_image(gif, ANCHOR, 3000)
    assert bubble._movie is not first and bubble._movie.state() == QMovie.MovieState.Running


def test_static_images_take_the_old_path(bubble, tmp_path):
    assert bubble.show_image(_png(tmp_path / "photo.png"), ANCHOR, 3000) is True
    assert bubble._movie is None and _center_color(bubble) == (10, 120, 200)
    assert bubble._hide_timer.interval() == 3000
    assert bubble.show_image(tmp_path / "missing.png", ANCHOR, 3000) is False


def test_prewarmed_still_frame_does_not_freeze_an_animated_image(bubble, tmp_path):
    """壳会把配图预先解码好直供（那是静态首帧）：动图不能因此被当成静态图。"""
    from PySide6.QtGui import QPixmap

    gif = _gif(tmp_path / "moving.gif")
    assert bubble.show_image(gif, ANCHOR, 3000, pixmap=QPixmap(str(gif))) is True
    assert bubble._movie is not None


def test_breath_bubble_style_also_animates(tmp_path):
    widget = PetSpeechBubble(style_id="breath_bubble")
    try:
        assert widget.show_image(_gif(tmp_path / "moving.gif"), ANCHOR, 3000) is True
        first = _center_color(widget)
        assert _pump(lambda: _center_color(widget) != first)
    finally:
        widget.close()
        widget.deleteLater()


# ---------------------------------------------------------------- 彩蛋弹窗
def test_popup_window_plays_animated_images_and_stops_on_close(tmp_path):
    from PySide6.QtWidgets import QLabel

    from pet.fun_image_popup import OjingjingWindow

    window = OjingjingWindow(_gif(tmp_path / "moving.gif"), lambda: None, lambda _w: None)
    label = window.findChild(QLabel, "ojingjingFullImage")
    movie = label.movie()
    assert movie is not None and movie.state() == QMovie.MovieState.Running
    assert max(movie.scaledSize().width(), movie.scaledSize().height()) == label.width(), \
        "等比放大到弹窗的图片框"
    first = movie.currentFrameNumber()
    assert _pump(lambda: movie.currentFrameNumber() != first)
    window.close()
    assert movie.state() == QMovie.MovieState.NotRunning

    still = OjingjingWindow(_png(tmp_path / "photo.png"), lambda: None, lambda _w: None)
    still_label = still.findChild(QLabel, "ojingjingFullImage")
    assert still_label.movie() is None and not still_label.pixmap().isNull()
    still.close()
