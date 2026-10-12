# -*- coding: utf-8 -*-
"""程序改名 dsh-pet-standalone → big-fat-fish：老用户的数据、凭据、开机自启要跟过来。

改名前的名字出现在四处会持久化的地方——数据目录、钥匙串服务名、开机自启项、
同机其它变体的配置发现。每一处都得认旧名字，且只迁移一次、不覆盖新数据。
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from pet import autostart as autostart_mod
from pet import config as config_mod
from pet.config import Config

OLD, NEW = "dsh-pet-standalone", "big-fat-fish"


def _legacy_dir(base, name=OLD, **config):
    root = base / name
    (root / "sessions").mkdir(parents=True)
    (root / "knowledge-base" / "current").mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"version": 4, "character": "claude", **config}), encoding="utf-8")
    (root / "config-slot-1.json").write_text("{}", encoding="utf-8")
    (root / "sessions" / "a.json").write_text("{}", encoding="utf-8")
    (root / "knowledge-base" / "current" / "INDEX.md").write_text("map", encoding="utf-8")
    return root


# ---------------------------------------------------------------- 名字

def test_the_app_directory_is_named_big_fat_fish():
    assert config_mod.APP_DIR_NAME == NEW and config_mod.LEGACY_APP_DIR_NAME == OLD


def test_packaged_variants_keep_their_own_directory_under_the_new_name(monkeypatch):
    monkeypatch.setitem(sys.modules, "build_variant", types.SimpleNamespace(VARIANT="webm-chat"))
    assert config_mod._app_dir_name() == "big-fat-fish-webm-chat"
    assert config_mod._app_dir_name(config_mod.LEGACY_APP_DIR_BASE) == "dsh-pet-standalone-webm-chat"


# ---------------------------------------------------------------- 数据目录

def test_the_old_data_directory_moves_over_whole(tmp_path):
    _legacy_dir(tmp_path)

    assert config_mod.migrate_legacy_app_dir(tmp_path) is True

    new = tmp_path / NEW
    assert sorted(p.relative_to(new).as_posix() for p in new.rglob("*") if p.is_file()) == [
        "agent-hooks-refresh.pending", "config-slot-1.json", "config.json",
        "knowledge-base/current/INDEX.md", "sessions/a.json"], "多出的那个文件是「钩子路径待更新」的待办标记"
    assert not (tmp_path / OLD).exists()
    assert config_mod.migrate_legacy_app_dir(tmp_path) is False, "只迁移一次"


def test_config_opens_on_the_migrated_settings(tmp_path):
    _legacy_dir(tmp_path, scale=1.75)

    config = Config(base=tmp_path)

    assert config.dir == tmp_path / NEW and config.get("scale") == 1.75
    assert (config.dir / "sessions" / "a.json").is_file()


def test_fresh_installs_and_already_migrated_users_are_left_alone(tmp_path):
    assert config_mod.migrate_legacy_app_dir(tmp_path) is False
    assert not (tmp_path / NEW).exists(), "没有旧目录时不凭空建新目录"

    _legacy_dir(tmp_path, scale=1.75)
    (tmp_path / NEW).mkdir()
    (tmp_path / NEW / "config.json").write_text(json.dumps({"scale": 0.5}), encoding="utf-8")

    assert config_mod.migrate_legacy_app_dir(tmp_path) is False
    assert json.loads((tmp_path / NEW / "config.json").read_text(encoding="utf-8")) == {"scale": 0.5}, \
        "新目录已有配置：绝不拿旧的覆盖"
    assert (tmp_path / OLD / "config.json").is_file()


def test_a_half_created_new_directory_still_receives_the_old_data(tmp_path):
    """启动早期可能先在新目录里落了日志或锁文件：这时不能整目录改名，要逐项搬。"""
    _legacy_dir(tmp_path, scale=1.75)
    new = tmp_path / NEW
    (new / "sessions").mkdir(parents=True)
    (new / "pet-123.log").write_text("early log", encoding="utf-8")
    (new / "sessions" / "fresh.json").write_text("fresh", encoding="utf-8")

    assert config_mod.migrate_legacy_app_dir(tmp_path) is True

    assert json.loads((new / "config.json").read_text(encoding="utf-8"))["scale"] == 1.75
    assert (new / "knowledge-base" / "current" / "INDEX.md").read_text(encoding="utf-8") == "map"
    assert (new / "pet-123.log").read_text(encoding="utf-8") == "early log"
    assert (new / "sessions" / "fresh.json").is_file(), "新目录里已有的同名项原样保留"


def test_events_written_to_the_old_path_later_do_not_trigger_another_migration(tmp_path):
    """已打开的 Claude Code 会话还握着旧路径的钩子，会把旧目录重新写出来。"""
    _legacy_dir(tmp_path)
    config_mod.migrate_legacy_app_dir(tmp_path)
    (tmp_path / OLD / "agent-events").mkdir(parents=True)
    (tmp_path / OLD / "agent-events" / "claude.jsonl").write_text("{}", encoding="utf-8")

    assert config_mod.migrate_legacy_app_dir(tmp_path) is False
    assert (tmp_path / OLD / "agent-events" / "claude.jsonl").is_file()


def test_a_packaged_variant_still_inherits_from_the_shared_directory_of_either_name(tmp_path, monkeypatch):
    """更早的版本各变体共用一个目录；变体第一次运行时从共用目录复制配置与会话。"""
    monkeypatch.setattr(config_mod, "APP_DIR_NAME", "big-fat-fish-webm-chat")
    monkeypatch.setattr(config_mod, "LEGACY_APP_DIR_NAME", "dsh-pet-standalone-webm-chat")
    _legacy_dir(tmp_path, scale=1.25)

    config = Config(base=tmp_path)

    assert config.dir == tmp_path / "big-fat-fish-webm-chat" and config.get("scale") == 1.25
    assert (tmp_path / OLD / "config.json").is_file(), "共用目录是复制，不是搬走：别的变体还要用"


# ---------------------------------------------------------------- 钥匙串

class _FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service, ref):
        return self.entries.get((service, ref))

    def set_password(self, service, ref, value):
        self.entries[(service, ref)] = value


@pytest.fixture
def keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


def test_secrets_saved_under_the_old_service_name_are_found_and_carried_over(keyring):
    from pet.chat.models import SecretStore

    keyring.entries[(OLD, "provider/api-2")] = "sk-ant-old"

    assert SecretStore().get("provider/api-2") == "sk-ant-old"
    assert keyring.entries[(NEW, "provider/api-2")] == "sk-ant-old", "顺手抄到新服务名下"
    assert keyring.entries[(OLD, "provider/api-2")] == "sk-ant-old", "旧条目不删：回滚到旧版本还能用"


def test_new_secrets_win_and_are_written_under_the_new_name_only(keyring):
    from pet.chat.models import SecretStore

    keyring.entries[(OLD, "connector/github")] = "ghp_old"
    assert SecretStore().set("connector/github", "ghp_new") is True

    assert SecretStore().get("connector/github") == "ghp_new"
    assert keyring.entries[(OLD, "connector/github")] == "ghp_old"
    assert SecretStore().get("provider/never-saved") == ""


# ---------------------------------------------------------------- 开机自启（Windows）

class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self):
        self.values: dict[str, str] = {}

    def OpenKey(self, root, subkey, reserved=0, access=0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(autostart_mod, "_IS_WIN", True)
    monkeypatch.setattr(autostart_mod, "_IS_MAC", False)
    monkeypatch.setattr(autostart_mod, "_IS_LINUX", False)
    fake = _FakeWinreg()
    monkeypatch.setattr(autostart_mod, "winreg", fake, raising=False)
    return fake


def test_autostart_identity_uses_the_new_name():
    assert autostart_mod.VALUE_NAME == NEW and autostart_mod.LEGACY_VALUE_NAME == OLD
    assert OLD in autostart_mod.KNOWN_VALUE_NAMES and NEW in autostart_mod.KNOWN_VALUE_NAMES
    assert "big-fat-fish" in autostart_mod.PLIST_LABEL and "dsh-pet-standalone" not in autostart_mod.PLIST_LABEL


def test_an_autostart_entry_under_the_old_name_is_renamed_not_duplicated(registry):
    """留着旧名字的自启项会让开机时启动两次（第二个被单实例门拦下，但白起一个进程）。"""
    registry.values[OLD] = autostart_mod._win_command()

    assert autostart_mod.adopt_legacy_entry() is True

    assert registry.values == {NEW: autostart_mod._win_command()}
    assert autostart_mod.is_enabled() is True
    assert autostart_mod.adopt_legacy_entry() is False


def test_is_enabled_adopts_the_old_entry_on_its_own(registry):
    registry.values[OLD] = autostart_mod._win_command()
    assert autostart_mod.is_enabled() is True
    assert list(registry.values) == [NEW]


def test_an_old_entry_that_belongs_to_another_install_is_not_touched(registry):
    foreign = r'cmd /c start "" /D "D:\elsewhere\pet" "D:\elsewhere\pet\.venv\Scripts\pythonw.exe" -m pet --slot 0'
    registry.values[OLD] = foreign

    assert autostart_mod.adopt_legacy_entry() is False
    assert registry.values == {OLD: foreign} and autostart_mod.is_enabled() is False


def test_the_new_entry_is_never_overwritten_by_the_old_one(registry):
    registry.values[NEW] = "new-command"
    registry.values[OLD] = autostart_mod._win_command()

    assert autostart_mod.adopt_legacy_entry() is True, "新的已在：旧的那条只需删掉"
    assert registry.values == {NEW: "new-command"}


# ---------------------------------------------------------------- 其它认旧名字的地方

def test_other_installs_are_discovered_under_both_names(tmp_path):
    from pet.agent_link import other_instances_use_agent

    for name in ("dsh-pet-standalone-webm-chat", "big-fat-fish-gif"):
        (tmp_path / name).mkdir()
    (tmp_path / "dsh-pet-standalone-webm-chat" / "config.json").write_text(
        json.dumps({"agent_link": {"claude": True}}), encoding="utf-8")
    (tmp_path / "big-fat-fish-gif" / "config.json").write_text(
        json.dumps({"agent_link": {"opencode": True}}), encoding="utf-8")
    config = Config(base=tmp_path)

    assert other_instances_use_agent(config, "claude") is True, "还在用旧名字的变体也算"
    assert other_instances_use_agent(config, "opencode") is True
    assert other_instances_use_agent(config, "dsh") is False


def test_characters_dropped_into_the_old_data_directory_are_still_found(monkeypatch, tmp_path):
    from pet import catalog

    monkeypatch.setattr(catalog, "_data_character_dirs", lambda name: [tmp_path / name / "characters"])
    names = [p.parent.name for p in catalog.external_character_dirs()[1:]]
    assert names == [NEW, OLD]


# ---------------------------------------------------------------- Claude Code 钩子里的路径

def _installed_hooks(tmp_path, monkeypatch, events_file):
    """一份装过本桌宠钩子（指向 events_file）、还带着用户自己钩子的 settings.json。"""
    from pet.agent_link import ClaudeCodeMonitor

    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]}}), encoding="utf-8")
    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path", staticmethod(lambda: settings))
    events_file.parent.mkdir(parents=True, exist_ok=True)
    assert ClaudeCodeMonitor.install_hooks(events_file) is True
    return settings


def test_installed_hooks_follow_the_data_directory_to_its_new_path(tmp_path, monkeypatch):
    from pet.agent_link import ClaudeCodeMonitor

    old_events = tmp_path / OLD / "agent-events" / "claude.jsonl"
    new_events = tmp_path / NEW / "agent-events" / "claude.jsonl"
    settings = _installed_hooks(tmp_path, monkeypatch, old_events)
    assert OLD in settings.read_text(encoding="utf-8")
    new_events.parent.mkdir(parents=True)

    assert ClaudeCodeMonitor.refresh_hooks(new_events) is True

    text = settings.read_text(encoding="utf-8")
    assert OLD not in text and f"{NEW}/agent-events/claude.jsonl" in text
    assert "echo mine" in text, "用户自己的钩子不碰"
    assert ClaudeCodeMonitor.refresh_hooks(new_events) is False, "已经是现在的路径：不重写"


def test_hooks_are_never_installed_by_a_refresh(tmp_path, monkeypatch):
    """注入要用户同意；没装过的人不能因为一次改名迁移就被装上。"""
    from pet.agent_link import ClaudeCodeMonitor

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]}}), encoding="utf-8")
    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path", staticmethod(lambda: settings))
    before = settings.read_text(encoding="utf-8")

    assert ClaudeCodeMonitor.refresh_hooks(tmp_path / NEW / "agent-events" / "claude.jsonl") is False
    assert settings.read_text(encoding="utf-8") == before

    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path", staticmethod(lambda: tmp_path / "missing.json"))
    assert ClaudeCodeMonitor.refresh_hooks(tmp_path / NEW / "agent-events" / "claude.jsonl") is False


def _manager(tmp_path, **agent_link):
    from PySide6.QtWidgets import QApplication

    from pet.agent_link import AgentLinkManager

    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    config.set("agent_link", {"claude": False, "claude_wsl": False, **agent_link})
    return AgentLinkManager(None, config)


def test_the_link_manager_refreshes_hooks_once_after_a_migration(tmp_path, monkeypatch):
    from pet.agent_link import ClaudeCodeMonitor

    _legacy_dir(tmp_path)
    settings = _installed_hooks(tmp_path, monkeypatch, tmp_path / OLD / "agent-events" / "claude.jsonl")
    wsl_calls: list = []
    monkeypatch.setattr(ClaudeCodeMonitor, "install_wsl_hooks",
                        classmethod(lambda cls, events_file, **_k: (wsl_calls.append(events_file), (True, ""))[1]))
    marker = tmp_path / NEW / "agent-hooks-refresh.pending"
    Config(base=tmp_path)                               # 目录迁移在这里完成，并留下待办标记
    assert marker.is_file() and OLD in settings.read_text(encoding="utf-8")
    manager = _manager(tmp_path, claude=True)           # 管理器构造时就会应用一次配置
    try:
        assert OLD not in settings.read_text(encoding="utf-8")
        assert not marker.exists() and wsl_calls == [], "没开 WSL 通道：不去动 WSL"
    finally:
        manager.shutdown()


def test_without_a_migration_the_link_manager_never_touches_the_hooks(tmp_path, monkeypatch):
    """平时的每次配置应用都不该读写用户的 ~/.claude/settings.json。"""
    from pet.agent_link import ClaudeCodeMonitor

    settings = _installed_hooks(tmp_path, monkeypatch, tmp_path / "elsewhere" / "agent-events" / "claude.jsonl")
    before = settings.read_text(encoding="utf-8")
    manager = _manager(tmp_path, claude=True)
    try:
        manager.apply_config()
        assert settings.read_text(encoding="utf-8") == before
    finally:
        manager.shutdown()


def test_wsl_hooks_are_refreshed_in_the_background_and_retried_until_they_succeed(tmp_path, monkeypatch):
    import threading

    from pet.agent_link import ClaudeCodeMonitor

    _legacy_dir(tmp_path)
    outcomes = [(False, "WSL 没有响应"), (True, "")]
    done = threading.Event()

    def fake_install(cls, events_file, **_kwargs):
        try:
            return outcomes.pop(0)
        finally:
            done.set()

    monkeypatch.setattr(ClaudeCodeMonitor, "install_wsl_hooks", classmethod(fake_install))
    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path", staticmethod(lambda: tmp_path / "none.json"))
    manager = _manager(tmp_path, claude_wsl=True)       # 构造时应用配置：第一次尝试在后台开始
    marker = tmp_path / NEW / "agent-hooks-refresh.pending"
    try:
        assert done.wait(20) and manager.wait_for_hooks_refresh(20)
        assert marker.is_file(), "WSL 没成功：标记留着，下次再试"

        done.clear()
        manager._refresh_moved_hooks({"claude_wsl": True})
        assert done.wait(20) and manager.wait_for_hooks_refresh(20)
        assert not marker.exists() and outcomes == []
    finally:
        manager.shutdown()
