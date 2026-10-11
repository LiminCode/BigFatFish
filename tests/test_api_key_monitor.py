# -*- coding: utf-8 -*-
"""ApiKeyMonitor：灵动岛「连接」图标的数据来源（AI 对话 API 体检）。

体检本身是网络请求，这里一律注入替身 probe；线程用同步 spawn 顶替，只有一条用例
走真线程，验证结果确实排队回到 GUI 线程。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.api_key_monitor import ApiKeyMonitor

app = QApplication.instance() or QApplication([])


class _Config:
    def __init__(self, key: str = "sk-1", model: str = "m1") -> None:
        self.key, self.model = key, model

    def chat_settings(self):
        provider = SimpleNamespace(provider_id="p", base_url="http://x", chat_path="/v1/chat/completions",
                                   model=self.model, api_format="auto", api_key="")
        return SimpleNamespace(active_config=provider)

    def resolve_api_key(self, _provider) -> str:
        return self.key


class _Probe:
    def __init__(self, result=(True, "连接成功")) -> None:
        self.result = result
        self.seen: list = []

    def __call__(self, provider):
        self.seen.append(provider)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _monitor(config=None, probe=None, *, spawn=None, **kwargs):
    monitor = ApiKeyMonitor(config or _Config(), probe=probe or _Probe(),
                            spawn=spawn or (lambda fn: fn()), **kwargs)
    monitor.changes = []
    monitor.status_changed.connect(lambda state, detail: monitor.changes.append((state, detail)))
    return monitor


def test_starts_unknown_and_turns_ok_once_the_probe_passes():
    probe = _Probe((True, "连接成功（Claude · m1）"))
    monitor = _monitor(probe=probe)
    monitor.start()
    assert monitor.state == "unknown", "查之前不许先亮绿灯"
    assert probe.seen == [], "启动时不抢着联网：延后到 STARTUP_DELAY_MS"
    assert monitor._timer.isActive() and monitor._timer.interval() == monitor.STARTUP_DELAY_MS

    assert monitor.check() is True

    assert (monitor.state, monitor.detail) == ("ok", "连接成功（Claude · m1）")
    assert monitor.changes[-1] == ("ok", "连接成功（Claude · m1）")
    assert probe.seen[0].api_key == "sk-1", "体检用的是解析后的 Key（钥匙串 / 配置）"
    assert monitor._timer.isActive() and monitor._timer.interval() == monitor.OK_RECHECK_MS


def test_failed_probe_is_bad_and_retried_sooner():
    monitor = _monitor(probe=_Probe((False, "认证失败：API Key 无效或已失效")))
    monitor.start()
    monitor.check()
    assert (monitor.state, monitor.detail) == ("bad", "认证失败：API Key 无效或已失效")
    assert monitor._timer.interval() == monitor.BAD_RECHECK_MS < monitor.OK_RECHECK_MS


def test_a_crashing_probe_is_bad_not_a_dead_worker():
    monitor = _monitor(probe=_Probe(RuntimeError("boom")))
    monitor.start()
    monitor.check()
    assert monitor.state == "bad" and "boom" in monitor.detail


def test_builds_without_chat_never_probe():
    probe = _Probe()
    monitor = _monitor(probe=probe, chat_enabled=False)
    monitor.start()
    assert monitor.check() is False
    monitor.refresh()
    monitor.note_success()
    assert probe.seen == [] and monitor.state == "unknown"
    assert not monitor._timer.isActive()


def test_nothing_happens_before_start():
    probe = _Probe()
    monitor = _monitor(probe=probe)
    assert monitor.check() is False
    assert probe.seen == []


def test_refresh_reprobes_only_when_the_provider_or_key_changed():
    config, probe = _Config(), _Probe()
    monitor = _monitor(config, probe)
    monitor.start()
    monitor.refresh()
    assert probe.seen == [], "还没查过第一次：交给启动延时那一次，不提前"
    monitor.check()

    monitor.refresh()
    assert len(probe.seen) == 1, "配置没变（改了别的设置）：不重查"

    config.key = "sk-2"
    probe.result = (False, "认证失败")
    monitor.refresh()
    assert len(probe.seen) == 2 and probe.seen[-1].api_key == "sk-2"
    assert monitor.state == "bad"

    config.model = "m2"
    probe.result = (True, "连接成功")
    monitor.refresh()
    assert len(probe.seen) == 3 and monitor.state == "ok"


def test_a_changed_key_drops_the_old_verdict_while_the_new_probe_is_in_flight():
    config, pending = _Config(), []
    monitor = _monitor(config, _Probe(), spawn=pending.append)
    monitor.start()
    monitor.check()
    pending.pop()()
    assert monitor.state == "ok"

    config.key = "sk-2"
    monitor.refresh()
    assert monitor.state == "unknown", "旧 Key 的绿灯不能挂在新 Key 上"


def test_stale_results_are_ignored():
    config, pending = _Config(), []
    probe = _Probe()
    monitor = _monitor(config, probe, spawn=pending.append)
    monitor.start()
    monitor.check()                         # 第一次体检在途
    assert monitor.check() is False, "在途时不重复发起"
    first = pending.pop()
    first()
    assert monitor.state == "ok"

    monitor.check()                         # 旧 Key 的体检在途……
    old = pending.pop()
    config.key = "sk-2"
    monitor.refresh()                       # ……用户换了 Key：再发起一次
    new = pending.pop()
    probe.result = (False, "认证失败")
    new()
    probe.result = (True, "连接成功")
    old()                                   # 旧 Key 的结果晚到

    assert monitor.state == "bad", "晚到的旧结果不许盖掉新结论"


def test_stop_cancels_the_schedule_and_drops_in_flight_results():
    pending = []
    monitor = _monitor(spawn=pending.append)
    monitor.start()
    monitor.check()
    monitor.stop()
    pending.pop()()
    assert monitor.state == "unknown" and not monitor._timer.isActive()
    assert monitor.check() is False

    monitor.start()                         # 灵动岛重新打开
    assert monitor._timer.isActive()


def test_a_successful_chat_counts_as_a_passed_check():
    monitor = _monitor(probe=_Probe((False, "网络连接失败")))
    monitor.start()
    monitor.check()
    assert monitor.state == "bad"

    monitor.note_success()

    assert monitor.state == "ok"


def test_unreadable_chat_config_is_unknown_not_a_crash():
    config = _Config()
    config.chat_settings = lambda: (_ for _ in ()).throw(RuntimeError("坏配置"))
    monitor = _monitor(config)
    monitor.start()
    assert monitor.check() is False
    assert monitor.state == "unknown"


def test_real_worker_thread_delivers_on_the_gui_thread():
    """默认 spawn 是真线程：结果必须排队回到 GUI 线程（Qt 对象不跨线程动）。"""
    probe_threads, slot_threads = [], []

    def probe(_provider):
        probe_threads.append(threading.current_thread())
        return True, "连接成功"

    monitor = ApiKeyMonitor(_Config(), probe=probe)
    loop = QEventLoop()

    def on_change(state, _detail):
        slot_threads.append(threading.current_thread())
        if state != "unknown":
            loop.quit()

    monitor.status_changed.connect(on_change)
    monitor.start()
    monitor.check()
    QTimer.singleShot(30_000, loop.quit)    # 宽预算兜底：正常由事件唤醒
    loop.exec()

    assert monitor.state == "ok"
    assert probe_threads and probe_threads[0] is not threading.main_thread()
    assert slot_threads and all(t is threading.main_thread() for t in slot_threads)
