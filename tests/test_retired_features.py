# -*- coding: utf-8 -*-
"""下线的功能（docs/adr/0016-drop-screen-watching-and-file-interpret.md）：代码删干净，旧配置里的键读不进来、写不回去，
界面上找不到入口。

- 拖文件解读（``file_interpret``）：肥鱼吃完文件后问「要不要交给 AI 解读」那一步。吃文件动画和统计（``file_eater`` /
  ``sprite_feeding``）不是它，留着。
- 看屏幕（``proactive_screen`` 主动识屏 + 右键「看看屏幕」）：截屏交给视觉模型、冒一句话。``vision.py`` 里别处还在用的
  桌面探测函数（光标可见性、前台窗口信息、系统空闲秒数）留着。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pet import i18n
from pet.config import Config

PET_DIR = Path(__file__).resolve().parent.parent / "pet"

#: 已删除的模块：文件不许回来，pet/ 里任何地方都不许再 import
RETIRED_FEATURE_MODULES = ("file_interpret", "settings_file_interpret", "proactive", "proactive_limiter", "proactive_memory")
#: 已删除的配置键：读进来就丢，下一次保存从 config.json 里消失
RETIRED_CONFIG_KEYS = ("file_interpret", "proactive_screen")
#: 已删除的文案前缀
RETIRED_TEXT_PREFIXES = ("file_interpret.", "settings.file.", "settings.domain.file", "panorama.feature.file",
                         "proactive.", "vision.", "panorama.feature.screen", "panorama.note.screen", "panorama.page.automation_screen",
                         "menu.action.look_screen", "menu.action.proactive_screen", "menu.shared.look_at_screen",
                         "menu.shared.screen_awareness", "menu.facade.screen_awareness", "overlay.ui.look_at_screen",
                         "settings.dlg.screen_awareness", "settings.dlg.proactive_awareness")
#: 已删除的右键菜单动作：旧的菜单编排里有它们，加载时清掉
RETIRED_MENU_ACTIONS = ("look_screen", "proactive_screen")


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
        "proactive_screen": {"enabled": True, "whitelist": ["code.exe"]},
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

    assert not {"file", "screen"} & {feature.id for feature in features.FEATURES}
    assert all(feature.config_key not in RETIRED_CONFIG_KEYS for feature in features.FEATURES)


def test_eating_files_no_longer_has_a_seam_for_offering_to_read_them():
    """吃文件本身留着（两种拓扑各一个控制器），只是吃完不再有「交给 AI 解读」的接缝。"""
    for name in ("file_eater.py", "sprite_feeding.py", "overlay_shell.py", "window_optional_services.py", "app.py"):
        source = (PET_DIR / name).read_text(encoding="utf-8")
        assert "interpret_offer" not in source and "install_file_interpreter" not in source, name


def test_the_menu_has_no_entry_for_them_and_old_layouts_lose_them(tmp_path):
    from pet.context_menus.registry import MENU_ACTIONS

    assert not set(RETIRED_MENU_ACTIONS) & set(MENU_ACTIONS.ids)
    template = (PET_DIR / "menu_templates" / "modern-default-v1.json").read_text(encoding="utf-8")
    assert all(f'"{action}"' not in template for action in RETIRED_MENU_ACTIONS)
    config = Config(tmp_path)
    config.set("context_menu_layout", {"version": 1, "nodes": [
        {"type": "action", "id": "look_screen", "visible": True},
        {"type": "action", "id": "proactive_screen", "visible": True},
        {"type": "action", "id": "chat", "visible": True},
    ]})
    kept = [node.get("id") for node in (config.get("context_menu_layout") or {}).get("nodes", [])]
    assert "chat" in kept and not set(RETIRED_MENU_ACTIONS) & set(kept)


def test_nothing_looks_at_the_screen_any_more():
    """截屏、问视觉模型、把识屏答复同步进聊天的代码都不在了（两种拓扑、聊天窗、共享子系统）。"""
    gone = ("look_at_screen", "on_look_screen", "on_look_synced", "sync_look_to_chat", "append_look_sync",
            "capture_screen_bytes", "ask_about_screen", "ProactiveScreenWatcher", "proactive_watcher")
    offenders = [f"{path.relative_to(PET_DIR)}: {name}" for path in sorted(PET_DIR.rglob("*.py"))
                 for name in gone if name in path.read_text(encoding="utf-8")]
    assert offenders == []
    from pet import vision

    assert callable(vision.get_cursor_visibility) and callable(vision.foreground_window_info)
    assert callable(vision.get_system_idle_seconds), "Slack 关注还在用"


def test_providers_no_longer_carry_a_separate_vision_model_or_key(tmp_path):
    """看屏幕删掉后，服务商里那组「视觉模型 / 视觉地址 / 视觉 Key」也没人用了：数据结构里没有，旧配置读进来就丢，
    下一次保存从文件里消失。明文 Key 照样不落盘。"""
    import dataclasses

    from pet.chat import anthropic_provider
    from pet.chat.models import ProviderConfig

    assert not [f.name for f in dataclasses.fields(ProviderConfig) if f.name.startswith("vision")]
    assert not hasattr(anthropic_provider, "describe_image")
    path = Config(tmp_path).path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 4, "chat": {"active_provider": "p1", "providers": {"p1": {
        "name": "P", "base_url": "https://example.invalid", "model": "m", "vision_model": "glm-4v", "vision_same_as_chat": False,
        "vision_base_url": "https://vision.invalid", "vision_api_key_ref": "provider/p1/vision", "vision_api_key": "sk-plain"}}}}),
        encoding="utf-8")
    config = Config(tmp_path)
    provider = config.get("chat")["providers"]["p1"]
    assert provider["model"] == "m" and not [key for key in provider if key.startswith("vision")]
    assert config.save()
    saved = path.read_text(encoding="utf-8")
    assert "vision" not in saved and "sk-plain" not in saved
