# -*- coding: utf-8 -*-
"""下线的功能（docs/adr/0016-drop-screen-watching-and-file-interpret.md）：代码删干净，旧配置里的键读不进来、写不回去，
界面上找不到入口。

- 拖文件解读（``file_interpret``）：肥鱼吃完文件后问「要不要交给 AI 解读」那一步。吃文件动画和统计（``file_eater`` /
  ``sprite_feeding``）不是它，留着。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pet import i18n
from pet.config import Config

PET_DIR = Path(__file__).resolve().parent.parent / "pet"

#: 已删除的模块：文件不许回来，pet/ 里任何地方都不许再 import
RETIRED_FEATURE_MODULES = ("file_interpret", "settings_file_interpret")
#: 已删除的配置键：读进来就丢，下一次保存从 config.json 里消失
RETIRED_CONFIG_KEYS = ("file_interpret",)
#: 已删除的文案前缀
RETIRED_TEXT_PREFIXES = ("file_interpret.", "settings.file.", "settings.domain.file", "panorama.feature.file")


def test_the_modules_are_gone_and_nothing_imports_them():
    assert [name for name in RETIRED_FEATURE_MODULES if (PET_DIR / f"{name}.py").exists()] == []
    offenders = []
    for path in sorted(PET_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")) and any(re.search(rf"\b{name}\b", stripped) for name in RETIRED_FEATURE_MODULES):
                offenders.append(f"{path.relative_to(PET_DIR)}:{lineno}: {stripped}")
    assert offenders == []


def test_an_old_config_loses_the_retired_keys_on_the_next_save(tmp_path):
    path = Config(tmp_path).path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 4, "file_interpret": {"enabled": False, "progress_interval_seconds": 30}, "playback_speed": 1.5,
    }), encoding="utf-8")
    config = Config(tmp_path)
    assert all(config.get(key) is None for key in RETIRED_CONFIG_KEYS)
    assert config.get("playback_speed") == 1.5, "别的设置照常读进来"
    assert config.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert not set(RETIRED_CONFIG_KEYS) & set(saved)


def test_a_fresh_config_does_not_have_them_either(tmp_path):
    assert all(Config(tmp_path).get(key) is None for key in RETIRED_CONFIG_KEYS)


def test_no_text_is_left_for_them_in_either_language():
    for language in ("zh", "en"):
        left = [key for key in i18n.table(language) if key.startswith(RETIRED_TEXT_PREFIXES)]
        assert left == [], language


def test_the_panorama_has_no_tile_for_them():
    from pet.panorama import features

    assert "file" not in {feature.id for feature in features.FEATURES}
    assert all(feature.config_key not in RETIRED_CONFIG_KEYS for feature in features.FEATURES)


def test_eating_files_no_longer_has_a_seam_for_offering_to_read_them():
    """吃文件本身留着（两种拓扑各一个控制器），只是吃完不再有「交给 AI 解读」的接缝。"""
    for name in ("file_eater.py", "sprite_feeding.py", "overlay_shell.py", "window_optional_services.py", "app.py"):
        source = (PET_DIR / name).read_text(encoding="utf-8")
        assert "interpret_offer" not in source and "install_file_interpreter" not in source, name
