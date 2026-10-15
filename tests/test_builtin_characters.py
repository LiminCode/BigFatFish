# -*- coding: utf-8 -*-
"""内置角色包的底线：登记在 ``catalog.CHARACTERS`` 里的角色，包必须真的在、真的能用。

内置角色列表是一个写死的元组（不扫描 ``assets/characters``），所以「把角色包放进
目录」和「在列表里登记」是两件事——漏了后一步，角色包装好了也不会出现在右键的
角色列表里（2026-10-11 新增 claude 角色时遇到）。
"""
from __future__ import annotations

import pytest

from pet import catalog


def test_claude_character_is_listed():
    assert "claude" in catalog.list_available_characters()
    assert catalog.character_display_name("claude") == "Claude"


@pytest.mark.parametrize("character_id", catalog.CHARACTERS)
def test_builtin_character_package_is_usable(character_id):
    video_dir = catalog.character_video_dir(character_id)
    idle = video_dir / catalog.DIR_IDLE / catalog.ANIM_FILES[catalog.IDLE]
    assert idle.is_file(), f"{character_id} 缺少待机动画：没有它肥鱼连站都站不住"

    box = catalog.character_body_box(character_id)
    assert box is not None, f"{character_id} 的 manifest 没有声明 body_box"
    x1, y1, x2, y2 = box
    assert 0 <= x1 < x2 <= catalog.CANVAS_W and 0 <= y1 < y2 <= catalog.CANVAS_H
    assert y2 == int(catalog.FEET_Y), "脚底必须落在统一的地面线上，否则换动画 / 换角色会跳"
    # 身体框左右对称：贴边与碰撞都按它算
    assert abs((x1 + x2) / 2 - catalog.CANVAS_W / 2) <= 1


# ---------------------------------------------------------------- 换角色 / 缺动画
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_missing_animation_falls_back_to_idle(qapp):
    """保底：角色包里没有的动画，一律用待机那一段顶上（不报错、不卡住）。"""
    from pet.library import MovieLibrary

    lib = MovieLibrary(character_id="claude")
    try:
        idle = lib.movie(catalog.IDLE)
        assert "写代码" not in lib.names()

        assert lib.movie("写代码") is idle
        assert lib.duration("写代码") == lib.duration(catalog.IDLE)
        # 顶替的不登记成那个名字：素材清单与已建 clip 表里都不该凭空多出一段
        assert "写代码" not in lib.names()
        assert "写代码" not in lib.movies()
    finally:
        lib.shutdown()
