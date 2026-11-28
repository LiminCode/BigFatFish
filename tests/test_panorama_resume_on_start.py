# -*- coding: utf-8 -*-
"""启动时恢复配置全景的本机服务：用过（会话文件在）才在几秒后起服务，从没用过什么都不做、连包都不 import。"""
from __future__ import annotations

from types import SimpleNamespace

from pet import app as app_module
from pet.app import AppShell


class _Shell:
    PANORAMA_RESUME_DELAY_MS = AppShell.PANORAMA_RESUME_DELAY_MS

    def __init__(self, tmp_path):
        self.config = SimpleNamespace(dir=tmp_path)
        self.resumed = 0

    def _panorama(self):
        return SimpleNamespace(resume=self._resume)

    def _resume(self):
        self.resumed += 1
        return True


def _timers(monkeypatch):
    scheduled = []
    monkeypatch.setattr(app_module.QTimer, "singleShot", lambda ms, fn: scheduled.append((ms, fn)))
    return scheduled


def test_never_used_means_nothing_is_scheduled(tmp_path, monkeypatch):
    scheduled = _timers(monkeypatch)
    shell = _Shell(tmp_path)
    AppShell._resume_panorama_later(shell)
    assert scheduled == [] and shell.resumed == 0


def test_used_before_resumes_the_service_a_few_seconds_after_start(tmp_path, monkeypatch):
    scheduled = _timers(monkeypatch)
    (tmp_path / "panorama-session.json").write_text('{"port": 50000, "token": "' + "a" * 43 + '"}', "utf-8")
    shell = _Shell(tmp_path)
    AppShell._resume_panorama_later(shell)
    assert [ms for ms, _fn in scheduled] == [AppShell.PANORAMA_RESUME_DELAY_MS] and shell.resumed == 0
    scheduled[0][1]()
    assert shell.resumed == 1


def test_a_resume_that_blows_up_does_not_escape(tmp_path, monkeypatch, caplog):
    scheduled = _timers(monkeypatch)
    (tmp_path / "panorama-session.json").write_text("{}", "utf-8")
    shell = _Shell(tmp_path)
    shell._panorama = lambda: (_ for _ in ()).throw(OSError("no port"))
    AppShell._resume_panorama_later(shell)
    scheduled[0][1]()                                                    # 记日志，不抛
    assert "配置全景" in caplog.text
