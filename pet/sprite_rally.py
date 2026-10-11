# -*- coding: utf-8 -*-
"""护驾：让所有小肥鱼围到主肥鱼身边。

两块，都不依赖 overlay 壳：

- ``escort_spots``（纯函数）：给每只小肥鱼在主肥鱼周围挑一个落点。全部按**身体框**
  算——碰撞体就是身体框，落点之间、落点与主肥鱼 / 障碍之间至少留 ``gap``，落地后
  才不会被碰撞世界当成重叠推开。
- ``SpriteRallyWorld``（tick 尾段的 extras 控制器）：把鱼从当前位置平滑送到落点。
  飞行途中这只鱼处于拖拽态（``INTERACTION_DRAG``——行为控制器据此播拖拽悬空动画，
  位置不归它管），并整只退出碰撞世界（``collision_suspended``——否则拖拽态是无限
  质量，一路把别的鱼和主肥鱼撞开）；到位后两样都还回去。

落点记成「相对主肥鱼的偏移」：飞行途中主肥鱼自己走开了，落点跟着它走。
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QPointF

from . import overlay_spawn_state
from .pet_sprite import INTERACTION_DRAG, INTERACTION_NORMAL

Rect = tuple[int, int, int, int]        # (x, y, w, h)，overlay 局部坐标


def _too_close(x: int, y: int, w: int, h: int, other: Sequence, gap: int) -> bool:
    ox, oy, ow, oh = other
    return x < ox + ow + gap and ox < x + w + gap and y < oy + oh + gap and oy < y + h + gap


def escort_spots(sizes: Sequence[Sequence[int]], anchor: Sequence[int], bounds: Sequence[int],
                 *, obstacles: Iterable[Sequence[int]] = (), gap: int = 12,
                 max_rows: int = 6, max_cols: int = 10) -> list[tuple[int, int] | None]:
    """给每只小肥鱼挑一个主肥鱼身边的落点，返回各自身体框的左上角（放不下为 None）。

    ``sizes`` 是各只的身体框 ``(w, h)``，``anchor`` 是主肥鱼身体框 ``(x, y, w, h)``，
    ``bounds`` 是可用区 ``(左, 上, 右, 下)``（右 / 下不含），``obstacles`` 是不许压上去
    的矩形（灵动岛）。

    候选点是一张贴着主肥鱼的格子：脚底对齐的那一行紧挨它左右两侧，其余各行再加上
    以它为中心向两边铺开的一列；按「离主肥鱼中心多近」排序逐个试，所以头两只一左
    一右站在它两侧，后面的往外、往上一圈圈补。格子只铺 ``max_rows`` × ``max_cols``
    这么大（够站几十只）；真铺满了再退回全屏找空位。
    """
    left, top, right, bottom = (int(v) for v in bounds)
    ax, ay, aw, ah = (int(v) for v in anchor)
    centre_x, centre_y = ax + aw / 2.0, ay + ah / 2.0
    taken: list[tuple] = [(ax, ay, aw, ah), *(tuple(int(v) for v in o) for o in obstacles)]
    spots: list[tuple[int, int] | None] = []
    for size in sizes:
        w, h = int(size[0]), int(size[1])
        spot = None
        if 0 < w <= right - left and 0 < h <= bottom - top:
            step_x, step_y = w + gap, h + gap
            base_y = ay + ah - h                     # 脚底与主肥鱼对齐
            centred_x = ax + (aw - w) // 2
            candidates = []
            for row in range(-max_rows, max_rows + 1):
                y = base_y + row * step_y
                if y < top or y + h > bottom:
                    continue
                xs = {ax + aw + gap + col * step_x for col in range(max_cols)}
                xs.update(ax - gap - w - col * step_x for col in range(max_cols))
                xs.update(centred_x + col * step_x for col in range(-max_cols, max_cols + 1))
                for x in xs:
                    if x < left or x + w > right:
                        continue
                    dx, dy = x + w / 2.0 - centre_x, y + h / 2.0 - centre_y
                    # 一样近时：先脚底对齐的那一行，再右侧
                    candidates.append((dx * dx + dy * dy, row != 0, dx < 0, x, y))
            for _dist, _off_row, _left_side, x, y in sorted(candidates):
                if not any(_too_close(x, y, w, h, other, gap) for other in taken):
                    spot = (x, y)
                    break
            if spot is None:
                # 格子铺满了：全屏找空位（现有鱼各自外扩一圈，保住间隙）
                spot = overlay_spawn_state.free_spawn_spot(
                    (w, h), (ax, ay, aw, ah),
                    [(o[0] - gap, o[1] - gap, o[2] + 2 * gap, o[3] + 2 * gap) for o in taken],
                    (left, top, right, bottom), gap)
        spots.append(spot)
        if spot is not None:
            taken.append((spot[0], spot[1], w, h))
    return spots


class _Flight:
    __slots__ = ("anchor", "offset", "start", "elapsed", "duration")

    def __init__(self, anchor, offset: QPointF, start: QPointF, duration: float) -> None:
        self.anchor, self.offset, self.start = anchor, QPointF(offset), QPointF(start)
        self.elapsed, self.duration = 0.0, duration


class SpriteRallyWorld:
    """把小肥鱼送到主肥鱼身边的飞行段（见模块说明）。"""

    MIN_DURATION_S = 0.45
    MAX_DURATION_S = 1.1
    SPEED_PX_S = 1800.0          # 远的飞久一点，但整体不超过 MAX_DURATION_S

    def __init__(self, on_arrived: Callable | None = None) -> None:
        self._on_arrived = on_arrived
        self._flights: dict = {}                 # sprite → _Flight

    def active(self, sprite=None) -> bool:
        """有没有鱼在飞（给 ``sprite`` 则只问这一只）。"""
        return bool(self._flights) if sprite is None else sprite in self._flights

    def start(self, anchor, moves) -> None:
        """出发。``moves`` 是 ``[(sprite, 落点相对 anchor.pos 的偏移), ...]``。

        正在飞的重新出发 = 从它现在的位置改飞新落点。被用户拖着的那只不抢。
        """
        for sprite, offset in moves:
            if getattr(sprite, "dragging", False):
                continue
            start = QPointF(sprite.pos)
            target = QPointF(anchor.pos) + QPointF(offset)
            distance = math.hypot(target.x() - start.x(), target.y() - start.y())
            duration = min(self.MAX_DURATION_S, max(self.MIN_DURATION_S, distance / self.SPEED_PX_S))
            sprite.set_velocity(QPointF(0, 0))
            sprite.interaction_state = INTERACTION_DRAG
            sprite.collision_suspended = True
            self._flights[sprite] = _Flight(anchor, offset, start, duration)

    def forget(self, sprite) -> None:
        """这只鱼离场了（sprite-removed 监听）。"""
        self._flights.pop(sprite, None)

    def tick(self, sprites, dt: float) -> None:
        if not self._flights:
            return
        present = {id(sprite) for sprite in sprites}
        for sprite, flight in list(self._flights.items()):
            if id(sprite) not in present:
                del self._flights[sprite]        # 飞到一半离场了
                continue
            if getattr(sprite, "dragging", False) or sprite.interaction_state != INTERACTION_DRAG:
                # 用户拖住了它（或别的控制器接管了）：位置归人家，只把碰撞资格还回去
                del self._flights[sprite]
                sprite.collision_suspended = False
                continue
            flight.elapsed += max(0.0, float(dt))
            t = min(1.0, flight.elapsed / flight.duration)
            eased = 1.0 - (1.0 - t) ** 3          # 先快后慢：落位时是轻轻停下
            target = QPointF(flight.anchor.pos) + flight.offset
            sprite.set_pos(flight.start + (target - flight.start) * eased)
            if t >= 1.0:
                del self._flights[sprite]
                sprite.interaction_state = INTERACTION_NORMAL
                sprite.collision_suspended = False
                if self._on_arrived is not None:
                    self._on_arrived(sprite)
