# -*- coding: utf-8 -*-
"""Phase 1 开关式加载门控测试。

验证目标：可选功能关闭时不构造/启动对应服务对象；启用时才懒装配。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.window import PetWindow


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _disabled_config(tmp_path):
    cfg = Config(base=tmp_path)
    cfg.set("collision_enabled", False)
    cfg.set("decode_broker_enabled", True)  # 依赖碰撞通道，碰撞关时仍不应创建 broker
    cfg.set("todo_reminder_enabled", False)
    cfg.set("click_sound_enabled", False)
    island = dict(cfg.get("dynamic_island", {}))
    island["enabled"] = False
    cfg.set("dynamic_island", island)
    cfg.set("auto_hide_fullscreen", False)
    # Claude Code 联动默认开（2026-11-14）：「全关」的配置要把它们也关上
    cfg.set("agent_link", {**cfg.get("agent_link"), "claude": False, "claude_wsl": False})
    return cfg


def test_petapp_disabled_optional_services_not_constructed(tmp_path):
    from pet.app import AppShell

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    # 本分支架构差异：碰撞会话为每窗自持（批5.2 P1-1，恒建），broker 已由
    # 进程内 fan-out hub 取代（批5.3）；上游断言的 collision/broker 门控不适用。
    # todo 服务走 Phase 1 懒门控（挂 AppShell 进程级）。
    assert shell.todo_service is None


def test_petapp_enabled_default_services_still_constructed(tmp_path):
    """默认配置（待办开）保持既有构造行为。"""
    from pet.app import AppShell

    app = _qapp()
    shell = AppShell(app, Config(tmp_path), enable_chat=False)
    assert shell.todo_service is not None
    # 4.4a：碰撞 IPC 会话已随多进程多宠退役层停用（多宠碰撞归 sprite 世界）；
    # 共享解码 hub 仍为进程级（默认 enabled 取决于 flag/拓扑）。
    assert not hasattr(shell.instance, "collision_ipc")
    assert shell._decode_hub is not None


def test_petapp_start_disabled_services_stay_stopped(tmp_path, monkeypatch):
    import pet.app as app_mod
    from pet.app import AppShell

    app = _qapp()
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda *a, **k: None)
    cfg = _disabled_config(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    shell.instance._create_ui = lambda cid: None
    shell.instance._apply_spawn_offset = lambda: None
    shell._apply_balance_timer = lambda: None
    shell.start()
    assert shell.todo_service is None


def test_petwindow_disabled_optional_services_not_constructed(tmp_path):
    from tests.pet_window_fakes import FakeLibrary

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    win = PetWindow(FakeLibrary(), cfg)
    try:
        assert win.agent_link_manager is None
    finally:
        win.close()
        app.processEvents()


def test_petwindow_lazy_ensure_creates_optional_services(tmp_path):
    from tests.pet_window_fakes import FakeLibrary

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    win = PetWindow(FakeLibrary(), cfg)
    try:
        assert win.agent_link_manager is None
        assert win._ensure_agent_link_manager() is not None
    finally:
        win.close()
        app.processEvents()


def test_petwindow_startup_applies_configured_optional_services(tmp_path):
    """开机即按配置装配可选服务（不触碰任何菜单/设置对话框）。

    回归：监视器实例由 AgentLinkManager.__init__ 装配，但真正启动靠
    apply_config()；构造末尾若只调 _install_effect_services()，配置里
    已开启的 Agent 联动（含 custom_agents 通道）与主动识屏要等用户展开
    「Agent 联动」菜单或开关一次设置对话框才会启动。
    """
    from tests.pet_window_fakes import FakeLibrary

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    cfg.set("agent_link", {"opencode": True})
    win = PetWindow(FakeLibrary(), cfg)
    try:
        assert win.agent_link_manager is not None
        assert win.agent_link_manager.monitors["opencode"]._running
    finally:
        win.close()
        app.processEvents()


def test_petwindow_agent_link_enabled_at_startup_constructs_manager(tmp_path):
    """回归（#99）：agent_link 已开启时，启动路径必须创建 AgentLinkManager。

    此前 __init__ 收尾只调 _install_effect_services()，没人调
    sync_optional_services()/apply_config()——重启后已开启的 Agent 联动
    必须手工展开一次联动菜单或开关一次设置对话框才生效。
    """
    from tests.pet_window_fakes import FakeLibrary

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    cfg.set("agent_link", {"dsh": True})
    win = PetWindow(FakeLibrary(), cfg)
    try:
        assert win.agent_link_manager is not None
        # DSH 通道同样必须真被 apply_config() 启动，而不只是创建了管理器。
        assert win.agent_link_manager.monitors["dsh"]._running
    finally:
        mgr = win.agent_link_manager
        if mgr is not None:
            mgr.shutdown()
        win.close()
        app.processEvents()
