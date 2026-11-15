# -*- coding: utf-8 -*-
"""灵动岛「模型连接」面板：点岛上的连接图标，列出配置过的全部模型服务和各自的连接状态。

2026-11-14 用户：「悬浮岛上的连接状态需要更新，点击那个连接状态，要显示配置的所有连接。」
以前连接图标只表达聊天在用的那一项，点它和点胶囊别处一样是展开卡片。
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from pet.chat.models import ChatSettings
from pet.island_connections import ConnectionsPanel, build_rows
from tests.test_island_info_slot import _island
from tests.test_island_personal import _release

app = QApplication.instance() or QApplication([])


def _settings() -> ChatSettings:
    return ChatSettings.from_dict({"active_provider": "claude", "providers": {
        "openai-main": {"name": "DeepSeek", "model": "deepseek-v4-flash", "api_key_ref": "provider/openai-main"},
        "claude": {"name": "Claude Opus", "base_url": "https://api.anthropic.com", "model": "claude-opus-5-5",
                   "api_key_ref": "provider/claude"},
        "local": {"name": "本机网关", "base_url": "http://127.0.0.1:8080", "model": "qwen-local",
                  "api_key_ref": "provider/local"},
    }})


# ---------------------------------------------------------------- 岛上的入口

def _link_center(island) -> QPointF:
    rect = island.link_rect()
    assert rect is not None, "显示状态时连接图标可点"
    return QPointF(rect.center().x(), rect.center().y())


def test_clicking_the_link_icon_requests_the_connections_panel(tmp_path):
    island = _island(tmp_path)
    try:
        requested = []
        island.connections_requested.connect(lambda: requested.append(True))
        _release(island, _link_center(island))
        assert requested == [True]
        assert island._mode != "expanded", "点连接图标不展开卡片"
        _release(island, QPointF(30, 20))              # 头像那里：照旧展开卡片
        assert requested == [True] and island._mode == "expanded"
    finally:
        island.deleteLater()


def test_the_metro_link_tile_is_clickable_too(tmp_path):
    island = _island(tmp_path, style="metro")
    try:
        requested = []
        island.connections_requested.connect(lambda: requested.append(True))
        assert island.link_rect().contains(island.metro_blocks()["link"].center())
        _release(island, _link_center(island))
        assert requested == [True]
    finally:
        island.deleteLater()


def test_no_link_icon_no_link_button(tmp_path):
    island = _island(tmp_path, show_status=False)
    try:
        assert island.link_rect() is None
    finally:
        island.deleteLater()


# ---------------------------------------------------------------- 每一行写什么

def test_rows_list_every_service_with_its_model_host_and_status():
    rows = build_rows(_settings(), {"openai-main": ("bad", "认证失败（HTTP 401）")},
                      in_use=("ok", "Claude Opus · 连接成功（Claude · claude-opus-5-5）"))
    assert [row.name for row in rows] == ["DeepSeek", "Claude Opus", "本机网关"], "配置里的顺序，全部列出"
    deepseek, claude, local = rows
    assert (deepseek.model, deepseek.host, deepseek.state, deepseek.in_use) == (
        "deepseek-v4-flash", "api.deepseek.com", "bad", False)
    assert deepseek.detail == "认证失败（HTTP 401）"
    assert (claude.state, claude.in_use) == ("ok", True), "在用的那一项用岛上体检的结论"
    assert claude.detail == "连接成功（Claude · claude-opus-5-5）", "名字已经在行上，不重复"
    assert (local.state, local.host) == ("unknown", "127.0.0.1:8080")
    assert local.detail, "没查过也要说一声"


# ---------------------------------------------------------------- 控制器

class Spawn:
    def __init__(self) -> None:
        self.jobs = []

    def __call__(self, job) -> None:
        self.jobs.append(job)

    def run(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()
        app.processEvents()


class _Config:
    def __init__(self) -> None:
        self.settings = _settings()
        self.keys = {"provider/openai-main": "sk-ds", "provider/claude": "sk-ant", "provider/local": ""}

    def chat_settings(self):
        return self.settings

    def resolve_api_key(self, provider):
        return self.keys.get(provider.api_key_ref, "")

    def get(self, key, default=None):
        return default


class _Monitor:
    def __init__(self) -> None:
        self.state, self.detail = "ok", "Claude Opus · 连接成功"
        self.checks = 0

    def check(self) -> bool:
        self.checks += 1
        return True


def _panel(clock=None):
    probed = []

    def probe(provider):
        probed.append((provider.provider_id, provider.api_key))
        return provider.provider_id != "openai-main", f"结论 {provider.provider_id}"

    spawn, monitor = Spawn(), _Monitor()
    now = [1000.0]
    panel = ConnectionsPanel(_Config(), monitor=monitor, probe=probe, spawn=spawn,
                             clock=clock or (lambda: now[0]))
    return panel, probed, spawn, monitor, now


def _states(panel) -> dict:
    return {row.provider_id: row.state for row in panel.rows()}


def test_opening_lists_all_services_and_checks_the_others_in_the_background():
    panel, probed, spawn, monitor, _now = _panel()
    try:
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        window = panel.window
        assert window.isVisible() and window.geometry().bottom() < 900, "在岛的上方"
        assert [tile.row.name for tile in window.tiles] == ["DeepSeek", "Claude Opus", "本机网关"]
        assert probed == [], "请求在后台线程里跑"
        assert _states(panel) == {"openai-main": "checking", "claude": "ok", "local": "checking"}

        spawn.run()
        assert sorted(probed) == [("local", ""), ("openai-main", "sk-ds")], "在用的那一项岛上已经在查，不重复发"
        assert _states(panel) == {"openai-main": "bad", "claude": "ok", "local": "ok"}
        assert [tile.row.state for tile in window.tiles] == ["bad", "ok", "ok"], "结果回来就重画"
    finally:
        panel.close()


def test_reopening_soon_does_not_probe_again_but_recheck_does():
    panel, probed, spawn, monitor, now = _panel()
    try:
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        spawn.run()
        panel.toggle(QRect(), QRect())                  # 关
        now[0] += 60
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        assert spawn.jobs == [], "一分钟前刚查过：不再发请求"

        panel.window.recheck_btn.click()
        assert monitor.checks == 1, "重新检查也让岛重查在用的那一项"
        spawn.run()
        assert len(probed) == 4

        now[0] += ConnectionsPanel.RECHECK_AFTER_S + 1
        panel.toggle(QRect(), QRect())
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        assert len(spawn.jobs) == 2, "过了半小时再打开就重查"
    finally:
        panel.close()


def test_a_changed_key_or_address_is_checked_again_and_stale_results_are_dropped():
    panel, probed, spawn, monitor, _now = _panel()
    try:
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        stale = spawn.jobs
        spawn.jobs = []
        panel.config.keys["provider/openai-main"] = "sk-ds-new"
        panel.refresh()
        assert len(spawn.jobs) == 1, "Key 变了：这一项重查"
        for job in stale:                                # 旧请求晚到
            job()
        app.processEvents()
        assert _states(panel)["openai-main"] == "checking", "旧 Key 的结论不能挂在新 Key 上"
        spawn.run()
        assert _states(panel)["openai-main"] == "bad"
    finally:
        panel.close()


def test_the_in_use_row_follows_the_island_monitor_while_open():
    panel, _probed, spawn, monitor, _now = _panel()
    try:
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        monitor.state, monitor.detail = "bad", "Claude Opus · 认证失败"
        panel.on_monitor_changed()
        claude = next(tile.row for tile in panel.window.tiles if tile.row.in_use)
        assert (claude.state, claude.detail) == ("bad", "认证失败")
    finally:
        panel.close()


def test_settings_button_and_escape():
    panel, _probed, _spawn, _monitor, _now = _panel()
    try:
        asked = []
        panel.settings_requested.connect(lambda: asked.append(True))
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        panel.window.settings_btn.click()
        assert asked == [True] and not panel.is_open(), "去设置：面板收起"
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        panel.window.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert not panel.is_open()
    finally:
        panel.close()


# ---------------------------------------------------------------- AppShell 接线

def test_shell_opens_the_panel_from_the_island(tmp_path, monkeypatch):
    from tests.test_island_shell_wiring import _make_shell, _teardown_shell

    shell = _make_shell(tmp_path)
    shell.app = app
    try:
        shell._sync_dynamic_island()
        shell.island.connections_requested.emit()
        panel = shell._connections_panel
        assert panel.is_open()
        assert {row.name for row in panel.rows()} == {"DeepSeek"}, "默认配置只有一项"
        shell._api_key_monitor.status_changed.emit("bad", "DeepSeek · 认证失败")
        assert panel.rows()[0].state == "bad", "岛的体检结论同步到面板"
        shell.island.connections_requested.emit()
        assert not panel.is_open(), "再点一下收起"
    finally:
        panel = getattr(shell, "_connections_panel", None)
        if panel is not None:
            panel.close()
        _teardown_shell(shell)


def test_build_rows_tolerates_a_provider_without_a_base_url():
    settings = SimpleNamespace(active_provider="x", providers={"x": SimpleNamespace(
        provider_id="x", name="", model="", base_url="")})
    (row,) = build_rows(settings, {}, in_use=("unknown", ""))
    assert row.name == "x" and row.host == ""
