# -*- coding: utf-8 -*-
"""动图（GIF / 动态 WebP）的打开与时长估算——配图气泡与彩蛋弹窗共用。

配图池（``assets/big_blue_fat_fish`` 或用户自选目录）里的图此前一律用 ``QPixmap``
读，动图只显示第一帧。要动起来就得用 ``QMovie``；这里只管「这是不是动图、能不能
播、一遍多长」，播放与停表由各自的窗口管（谁显示谁负责在隐藏时停）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QMovie

#: 可能是动图的后缀。先按后缀筛：静态图占绝大多数，不为每一张都建一次 QMovie。
ANIMATED_SUFFIXES = frozenset({".gif", ".webp"})
#: 读不出帧延时的动图按这个间隔估（GIF 约定俗成的缺省值）
_DEFAULT_FRAME_MS = 100


def open_movie(path: str | Path, parent=None) -> QMovie | None:
    """``path`` 是能播的多帧动图 → 停在第一帧的 ``QMovie``；否则 None。

    不缓存解码帧（``CacheNone``）：一张 300×428、122 帧的 GIF 全缓存就是 60MB，
    循环时重新解码的开销远小于这个。
    """
    path = Path(str(path))
    if path.suffix.lower() not in ANIMATED_SUFFIXES:
        return None
    movie = QMovie(str(path))
    if not movie.isValid() or movie.frameCount() <= 1 or not movie.jumpToFrame(0):
        movie.deleteLater()
        return None
    if parent is not None:
        movie.setParent(parent)
    movie.setCacheMode(QMovie.CacheMode.CacheNone)
    return movie


def loop_duration_ms(movie: QMovie) -> int:
    """播一遍大约多久（帧数 × 当前帧的延时；各帧延时不同的动图是近似值）。"""
    delay = movie.nextFrameDelay()
    if delay <= 0:
        delay = _DEFAULT_FRAME_MS
    return max(0, movie.frameCount()) * delay
