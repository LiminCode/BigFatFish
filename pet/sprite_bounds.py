# -*- coding: utf-8 -*-
"""逐 sprite 活动边界：被拖到别的屏幕上的 sprite 用它自己那块屏的可用区。

四个 sprite 世界控制器（行为 / 抛掷物理 / 边缘探头 / 抛掷彩蛋）各自只持有**一个**
边界矩形——overlay 所在屏（主屏）的可用区。跨屏之后一只 sprite 可能住在别的屏上
（``PetSprite.home_bounds``，同一坐标系里的另一块矩形，见 ``overlay_screens``），
这时控制器必须按它自己的边界游走 / 反弹 / 判贴边，否则它会被主屏的边界拉回去。

``home_bounds`` 为 ``None``（缺省，也是没有这个属性的测试假对象的读数）= 住在主屏，
沿用控制器自己的边界——单屏下逐位等价于改造前。
"""
from __future__ import annotations


def bounds_for(sprite, default):
    """``sprite`` 的活动边界；类型与 ``default`` 一致（``QRect`` / ``QRectF``）。"""
    own = getattr(sprite, "home_bounds", None)
    if own is None:
        return default
    return type(default)(own)
