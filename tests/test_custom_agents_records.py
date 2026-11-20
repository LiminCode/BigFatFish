# -*- coding: utf-8 -*-
"""PR-C（2026-11-20）：自定义联动 Agent 在配置全景上改——``records`` 控件（表 / 描述 / 写入校验 / 页面表格）与
``AgentLinkManager.apply_config`` 的热生效（新增的建、删掉的停并移除、改了路径的重建、只改名的换名）。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import settings_table as st
from pet.agent_link import AgentLinkManager, CustomAgentMonitor
from pet.config import Config
from pet.panorama import render, settings_api
from tests.test_panorama_page import FAKE_DOM, _evaluate
from tests.test_panorama_settings_panel import API, REPORT, _desc

app = QApplication.instance() or QApplication([])
GROUP = st.group("link_win")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 描述与写入

def test_the_description_names_the_columns_and_the_write_path_keeps_or_rejects_rows():
    desc = settings_api.describe(GROUP, {"custom_agents": [{"key": "gemini", "name": "Gemini CLI", "path": "~/g.jsonl"}]})
    row = next(r for r in desc["settings"] if r["id"] == "custom_agents")
    assert row["control"] == "records" and row["commit"] == "on_finish" and row["disclosure"] == "advanced"
    assert row["fields"] == [{"id": "key", "title": "标识"}, {"id": "name", "title": "显示名"}, {"id": "path", "title": "事件文件"}]
    assert row["value"] == [{"key": "gemini", "name": "Gemini CLI", "path": "~/g.jsonl"}] and row["default"] == []

    new, errors = st.check_changes(GROUP, {}, {"custom_agents": [
        {"key": " gemini ", "name": " Gemini CLI ", "path": " ~/g.jsonl "}, {"key": "", "name": "", "path": ""},
        {"key": "codex", "name": "Codex", "path": "C:/ev/codex.jsonl"}]})
    assert errors == [] and new["custom_agents"] == [{"key": "gemini", "name": "Gemini CLI", "path": "~/g.jsonl"},
                                                      {"key": "codex", "name": "Codex", "path": "C:/ev/codex.jsonl"}], "去空白、全空的行不要"
    for bad in ([{"key": "Gemini", "name": "x", "path": "~/g.jsonl"}],        # 大写：功能会改成小写 → 和提交的不一样
                [{"key": "claude", "name": "x", "path": "~/g.jsonl"}],        # 和内置键重名：功能会丢掉这一行
                [{"key": "gemini", "name": "", "path": "~/g.jsonl"}],         # 名字空：功能会补成 key
                [{"key": "gemini", "name": "x", "path": ""}]):                # path 空：功能会丢掉
        assert st.check_changes(GROUP, {}, {"custom_agents": bad})[1] == [{"id": "custom_agents", "code": "rejected"}], bad
    assert st.check_changes(GROUP, {}, {"custom_agents": "gemini"})[1] == [{"id": "custom_agents", "code": "type"}]
    assert st.check_changes(GROUP, {}, {"custom_agents": [{"key": 1}]})[1] == [{"id": "custom_agents", "code": "type"}]


# ---------------------------------------------------------------- 页面表格

@pytest.fixture(scope="module")
def engine():
    from PySide6.QtQml import QJSEngine

    js = QJSEngine()
    yield js
    del js


RECORDS = {"id": "custom_agents", "control": "records", "title": "自定义联动 Agent", "hint": "", "default": [],
           "value": [{"key": "gemini", "name": "Gemini", "path": "~/g.jsonl"}], "choices": [], "commit": "on_finish",
           "disclosure": "primary", "depends_on": "", "builtin": None, "min": None, "max": None, "unit": "", "labels": [],
           "fields": [{"id": "key", "title": "标识"}, {"id": "name", "title": "显示名"}, {"id": "path", "title": "事件文件"}]}


def _page(engine, steps: str) -> dict:
    from pet.panorama import sources
    from tests import panorama_samples as samples

    desc = _desc(group="link_win", settings=[RECORDS])
    data = json.dumps(render.page_data(sources.build(samples.facts())), ensure_ascii=False)
    script = (FAKE_DOM + API % json.dumps(desc, ensure_ascii=False) + render.bundle(render.MODULES[:-1])
              + f"\nvar DATA = {data}; var view = start(DATA, undefined, API);\n" + steps + REPORT)
    return _evaluate(engine, script)


def test_the_form_draws_a_table_with_add_and_delete_and_saves_the_rows_as_dicts(engine):
    out = _page(engine, "view.openSettings('link_win');")
    form = out["form"]
    assert '<table class="frecords"' in form and "<th>标识</th><th>显示名</th><th>事件文件</th>" in form
    assert 'data-rec="custom_agents" data-i="0" data-f="key" value="gemini"' in form and 'data-del="custom_agents" data-i="0"' in form
    assert 'data-add="custom_agents"' in form and ">加一行<" in form and 'data-save="custom_agents" disabled' in form

    out = _page(engine, "view.openSettings('link_win');"
                        "fire('click', {add: 'custom_agents'});"
                        "fire('input', {rec: 'custom_agents', i: '1', f: 'key'}, ' codex ');"
                        "fire('input', {rec: 'custom_agents', i: '1', f: 'path'}, 'C:/ev/codex.jsonl');"
                        "fire('click', {save: 'custom_agents'});")
    assert out["patches"][0]["body"]["changes"] == {"custom_agents": [
        {"key": "gemini", "name": "Gemini", "path": "~/g.jsonl"}, {"key": "codex", "name": "", "path": "C:/ev/codex.jsonl"}]}, "字段去空白，整张表一次交"

    out = _page(engine, "view.openSettings('link_win');"
                        "fire('click', {del: 'custom_agents', i: '0'});"
                        "fire('click', {save: 'custom_agents'});")
    assert out["patches"][0]["body"]["changes"] == {"custom_agents": []}, "删掉唯一一行 = 存空列表"

    out = _page(engine, "view.openSettings('link_win');"
                        "fire('click', {add: 'custom_agents'});"
                        "fire('click', {save: 'custom_agents'});")
    assert out["patches"] == [], "加了一行什么都没填：和原来一样，不算改过"


# ---------------------------------------------------------------- 热生效

class _Win:
    def isVisible(self):
        return True

    def mark_activity(self):
        pass

    def show_bubble(self, *_a, **_k):
        pass


def _manager(tmp_path, agents, **flags):
    config = Config(base=tmp_path)
    config.set("agent_link", {**config.get("agent_link"), "custom_agents": agents, **flags})
    return AgentLinkManager(_Win(), config, min_interval=0.0), config


def _set(config, agents, **flags):
    config.set("agent_link", {**config.get("agent_link"), "custom_agents": agents, **flags})


def test_custom_agents_are_added_removed_and_rebuilt_without_a_restart(tmp_path):
    mgr, config = _manager(tmp_path, [{"key": "gemini", "name": "Gemini", "path": str(tmp_path / "g.jsonl")}], gemini=True)
    mgr.apply_config()
    first = mgr.monitors["gemini"]
    assert isinstance(first, CustomAgentMonitor) and first._running and mgr.agent_names["gemini"] == "Gemini"

    # 只改显示名：同一个监视器，换名
    _set(config, [{"key": "gemini", "name": "Gemini CLI", "path": str(tmp_path / "g.jsonl")}], gemini=True)
    mgr.apply_config()
    assert mgr.monitors["gemini"] is first and first._running and mgr.agent_names["gemini"] == "Gemini CLI"

    # 改路径：停掉重建，并按开关重新起来
    _set(config, [{"key": "gemini", "name": "Gemini CLI", "path": str(tmp_path / "g2.jsonl")}], gemini=True)
    mgr.apply_config()
    second = mgr.monitors["gemini"]
    assert second is not first and not first._running and second._running and second.events_file.name == "g2.jsonl"

    # 新增一个（开关没开：登记但不起）
    _set(config, [{"key": "gemini", "name": "Gemini CLI", "path": str(tmp_path / "g2.jsonl")},
                  {"key": "codex", "name": "Codex", "path": str(tmp_path / "c.jsonl")}], gemini=True)
    mgr.apply_config()
    assert "codex" in mgr.monitors and not mgr.monitors["codex"]._running and mgr.agent_names["codex"] == "Codex"

    # 删掉：停并移除；内置的不受影响
    _set(config, [], gemini=True)
    mgr.apply_config()
    assert "gemini" not in mgr.monitors and "codex" not in mgr.monitors and not second._running
    assert "gemini" not in mgr.agent_names and set(mgr.AGENT_NAMES) <= set(mgr.monitors)
    mgr.stop_all() if hasattr(mgr, "stop_all") else None


# ---------------------------------------------------------------- 页面改了联动设置 → 共享的联动管理器

def test_an_external_config_change_applies_the_shared_agent_link_manager_even_without_a_pet_window():
    """overlay 拓扑没有 PetWindow（instance.win 是 None），「各窗 refresh_pet_settings → apply_config」那条链走不到：
    _apply_external_config_change 要自己应用共享的联动管理器，否则页面上改的联动开关 / 自定义 Agent 都要等重启。"""
    from types import SimpleNamespace

    from pet.app import AppShell

    applied = []
    shell = AppShell.__new__(AppShell)
    shell.config = Config.__new__(Config)
    shell.config.data = {}
    shell._instances = [SimpleNamespace(win=None)]
    shell._overlay_shell = None
    shell._shared = SimpleNamespace(agent_link=SimpleNamespace(apply_config=lambda: applied.append(1)))
    for name in ("_sync_dynamic_island", "_repush_island_texts", "_apply_balance_timer", "_sync_todo_service",
                 "_sync_chime_service", "_sync_festival_service"):
        setattr(shell, name, lambda: None)
    shell._dsh_tracker_wanted = lambda: True
    shell._apply_external_config_change()
    assert applied == [1]
