# -*- coding: utf-8 -*-
"""设置的写入链路，整条路：真实的本机服务 → 请求线程 → 转到界面线程 → 真的 ``Config`` 落盘。

请求在工作线程里发（``http.client``），主线程转着 Qt 的事件循环——和肥鱼里一样。等的是线程结束这个事件，
不是睡一个猜出来的时间。
"""
from __future__ import annotations

import http.client
import json
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import settings_table as st
from pet import work_briefing as wb
from pet.config import Config
from pet.panorama import routes
from pet.panorama import server as srv
from pet.panorama import settings_api as api
from pet.panorama.feed import Feed
from pet.panorama.service import PanoramaService
from tests import panorama_samples as samples

WAIT = 30.0
SECRET_PROMPT = "PROMPT-TEXT-THAT-MUST-NOT-LEAK-INTO-LOGS"


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """一个真的 Config、一个真的服务对象（在主线程）、一个真的本机服务。"""
    app = QApplication.instance() or QApplication([])
    i18n.set_language("zh")
    monkeypatch.setattr(st.claude_hooks, "wsl_exe", lambda: "wsl.exe")
    config = Config(base=tmp_path)
    config.set("work_briefing", wb.normalize({"enabled": False, "time": "09:00"}))
    assert config.save()
    applied = []
    service = PanoramaService(config, windows=lambda *a, **k: {}, wsl=dict, write=lambda facts, out_dir: out_dir / "p.html",
                              open_page=lambda target: None, spawn=lambda run: None,
                              apply=lambda: applied.append(threading.current_thread() is threading.main_thread()))
    server = srv.PanoramaServer(routes.build_router(service._feed, settings=service), poll_seconds=0.02)
    server.start()
    yield type("Stack", (), {"app": app, "config": config, "service": service, "server": server, "applied": applied})
    service.stop()
    server.stop()
    i18n.set_language("zh")


def _send(server, method, path, body=None, *, token=True, origin=True, content_type="application/json", raw=None):
    headers = {"Host": f"127.0.0.1:{server.port}"}
    if token:
        headers[srv.TOKEN_HEADER] = server.token
    if origin:
        headers["Origin"] = origin if isinstance(origin, str) else f"http://127.0.0.1:{server.port}"
    payload = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    if payload is not None and content_type:
        headers["Content-Type"] = content_type
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=WAIT)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, (json.loads(data) if data else None)
    finally:
        connection.close()


def _pump(app, call, *, events=True):
    """在工作线程里跑 ``call``，主线程转事件循环等它完。``events=False`` = 界面线程卡住了，不处理事件。"""
    box = {}
    worker = threading.Thread(target=lambda: box.update(out=call()), daemon=True)
    worker.start()
    deadline = time.monotonic() + WAIT
    while worker.is_alive() and time.monotonic() < deadline:
        if events:
            app.processEvents()
        worker.join(0.005)
    assert not worker.is_alive(), "the request never came back"
    return box["out"]


def _version(stack) -> str:
    return api.read(stack.config, "work_briefing")["version"]


def _disk(stack) -> dict:
    return json.loads(stack.config.path.read_text(encoding="utf-8"))["work_briefing"]


# ───────────────────────── 读 ─────────────────────────

def test_reading_a_group_goes_through_the_gui_thread(stack, monkeypatch):
    threads = []
    real = api.read
    monkeypatch.setattr(api, "read", lambda config, group: (threads.append(threading.current_thread() is threading.main_thread()),
                                                            real(config, group))[1])
    status, body = _pump(stack.app, lambda: _send(stack.server, "GET", "/api/settings/work_briefing"))
    assert status == 200 and body["group"] == "work_briefing" and len(body["settings"]) == 14
    assert threads == [True]                                             # Config 只在界面线程上被碰


def test_an_unknown_group_is_404_and_settings_need_the_token(stack):
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/settings/nope")) == (404, {"error": "unknown_group"})
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/settings/work_briefing", token=False))[0] == 401
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/audit", token=False))[0] == 401


# ───────────────────────── 写 ─────────────────────────

def test_a_write_from_the_page_lands_on_disk_is_applied_and_audited(stack):
    body = {"base": _version(stack), "changes": {"enabled": True, "time": "09:30"}}
    status, out = _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))
    assert status == 200 and out["changed"] == ["enabled", "time"] and out["version"] == _version(stack)
    assert _disk(stack)["enabled"] is True and _disk(stack)["time"] == "09:30"
    assert stack.applied == [True]                                       # 应用链调了一次，在界面线程上
    status, audit = _pump(stack.app, lambda: _send(stack.server, "GET", "/api/audit"))
    assert status == 200 and [(e["setting"], e["new"]) for e in audit["entries"]] == [("time", "09:30"), ("enabled", True)]


@pytest.mark.parametrize("kwargs, status, code", [
    ({"token": False}, 401, "bad_token"),
    ({"origin": False}, 403, "origin_required"),
    ({"origin": "http://evil.example"}, 403, "bad_origin"),
    ({"content_type": "text/plain"}, 415, "json_only"),
    ({"raw": b"{not json"}, 400, "bad_json"),
    ({"raw": b"[1, 2]"}, 400, "bad_request"),
])
def test_a_write_that_fails_the_door_checks_never_touches_the_config(stack, kwargs, status, code):
    before = stack.config.path.read_bytes()
    body = {"base": _version(stack), "changes": {"enabled": True}}
    got, out = _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body, **kwargs))
    assert (got, out["error"]) == (status, code)
    assert stack.config.path.read_bytes() == before and stack.applied == []


def test_a_stale_write_gets_409_with_the_current_values_and_an_invalid_one_422_with_the_fields(stack):
    stale = _version(stack)
    _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", {"base": stale, "changes": {"time": "09:30"}}))
    status, out = _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing",
                                                 {"base": stale, "changes": {"time": "10:00"}}))
    assert status == 409 and out["error"] == "stale" and out["current"]["version"] == _version(stack)
    status, out = _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing",
                                                 {"base": _version(stack), "changes": {"model": "x; rm -rf ~", "effort": "ultra"}}))
    assert status == 422 and out["error"] == "invalid"
    assert {(e["id"], e["code"]) for e in out["errors"]} == {("model", "rejected"), ("effort", "not_a_choice")}
    assert _disk(stack)["time"] == "09:30" and _disk(stack)["model"] == "sonnet" and len(stack.applied) == 1


def test_a_write_to_another_method_or_path_does_not_exist(stack):
    body = {"base": _version(stack), "changes": {"enabled": True}}
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/settings/work_briefing", body))[0] == 405
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing/extra", body))[0] == 404
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/..", body))[0] == 404
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/audit", body))[0] == 405


# ───────────────────────── 转到界面线程 ─────────────────────────

def test_when_the_gui_thread_is_stuck_the_write_is_refused_and_does_not_happen_later(stack):
    """界面线程没空（卡在一个长操作里）：请求等到超时，回「忙」。之后界面线程缓过来，这次写入也不能再悄悄补上。"""
    stack.service.GUI_TIMEOUT = 0.3
    before = stack.config.path.read_bytes()
    body = {"base": _version(stack), "changes": {"enabled": True}}
    status, out = _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body), events=False)
    assert (status, out) == (503, {"error": "busy"})
    for _ in range(20):
        stack.app.processEvents()                                        # 排着队的那个调用现在轮到了：它已经被作废
    assert stack.config.path.read_bytes() == before and stack.applied == []


def test_called_from_the_gui_thread_itself_the_work_runs_inline(stack):
    assert stack.service.on_gui(lambda: threading.current_thread() is threading.main_thread()) is True


def test_an_unexpected_error_in_the_gui_thread_is_a_500_without_details(stack, monkeypatch):
    def boom(config, group):
        raise RuntimeError(SECRET_PROMPT)

    monkeypatch.setattr(api, "read", boom)
    status, out = _pump(stack.app, lambda: _send(stack.server, "GET", "/api/settings/work_briefing"))
    assert (status, out) == (500, {"error": "internal_error"})


# ───────────────────────── 改完之后 ─────────────────────────

def test_after_a_write_the_open_page_is_told_and_the_feature_tile_shows_the_new_values(stack, tmp_path):
    facts = samples.facts(wsl="absent")
    stack.service._publish(facts, tmp_path)                              # 页面开着：之前发布过一轮
    before = stack.service._feed.revision
    body = {"base": _version(stack), "changes": {"enabled": True, "time": "09:30", "effort": "low"}}
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))[0] == 200
    assert stack.service._feed.revision == before + 1
    graph = json.loads(stack.service.graph_payload())
    tile = next(n for n in graph["nodes"] if n["id"] == "f_briefing")
    assert tile["state"] == "ok" and "09:30" in tile["sub"] and "low" in tile["sub"]


def test_a_write_before_any_page_was_published_just_saves(stack):
    body = {"base": _version(stack), "changes": {"time": "09:30"}}
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))[0] == 200
    assert stack.service.graph_payload() is None and _disk(stack)["time"] == "09:30"


def test_a_failing_apply_chain_does_not_fail_the_write(stack):
    stack.service._apply = lambda: 1 / 0
    body = {"base": _version(stack), "changes": {"time": "09:30"}}
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))[0] == 200
    assert _disk(stack)["time"] == "09:30"


def test_the_prompt_text_never_reaches_the_log(stack, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    body = {"base": _version(stack), "changes": {"prompt_zh": SECRET_PROMPT}}
    assert _pump(stack.app, lambda: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))[0] == 200
    assert _disk(stack)["prompt_zh"] == SECRET_PROMPT and SECRET_PROMPT not in caplog.text


def test_the_server_the_service_starts_for_itself_carries_the_settings_routes(stack):
    """肥鱼里页面是这样来的：服务第一次要开页面时自己起本机服务。那个服务必须带着设置接口，并且把写入交给同一个服务对象。"""
    url = stack.service._page_target("unused-snapshot-path")
    own = stack.service._server
    assert url.startswith(f"http://127.0.0.1:{own.port}/#") and own is not stack.server
    status, body = _pump(stack.app, lambda: _send(own, "GET", "/api/settings/work_briefing"))
    assert status == 200
    change = {"base": body["version"], "changes": {"weekdays_only": False}}
    assert _pump(stack.app, lambda: _send(own, "PATCH", "/api/settings/work_briefing", change))[0] == 200
    assert _disk(stack)["weekdays_only"] is False and stack.applied == [True]


def test_without_a_settings_port_the_routes_do_not_exist():
    feed = Feed()
    server = srv.PanoramaServer(routes.build_router(feed), poll_seconds=0.02)
    server.start()
    try:
        assert _send(server, "GET", "/api/settings/work_briefing")[0] == 404
        assert _send(server, "GET", "/api/audit")[0] == 404
    finally:
        feed.close()
        server.stop()


def test_audit_limit_is_bounded(stack):
    for minute in ("09:30", "10:00", "08:00"):
        body = {"base": _version(stack), "changes": {"time": minute}}
        assert _pump(stack.app, lambda body=body: _send(stack.server, "PATCH", "/api/settings/work_briefing", body))[0] == 200
    assert len(_pump(stack.app, lambda: _send(stack.server, "GET", "/api/audit?limit=2"))[1]["entries"]) == 2
    assert len(_pump(stack.app, lambda: _send(stack.server, "GET", "/api/audit?limit=abc"))[1]["entries"]) == 3
    assert len(_pump(stack.app, lambda: _send(stack.server, "GET", "/api/audit?limit=-5"))[1]["entries"]) == 3


# ───────────────────────── 动作 ─────────────────────────

def test_an_action_runs_its_handler_on_the_gui_thread_and_answers_with_its_result(stack):
    from pet.panorama.actions import ActionError

    seen = []

    def echo(body):
        seen.append(threading.current_thread() is threading.main_thread())
        if body.get("boom"):
            raise ActionError(400, "bad_agent")
        return {"state": "installed", "got": body}

    stack.service.actions["echo"] = echo
    status, out = _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/echo", {"agent": "claude"}))
    assert (status, out) == (200, {"state": "installed", "got": {"agent": "claude"}}) and seen == [True]
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/echo", {"boom": 1})) == (400, {"error": "bad_agent"})
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/nope", {})) == (404, {"error": "unknown_action"})
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/echo", {}, token=False))[0] == 401
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/echo", {}, origin=False))[0] == 403


def test_a_handler_that_blows_up_is_a_500_not_a_dead_connection(stack):
    stack.service.actions["bad"] = lambda body: 1 / 0
    assert _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/bad", {})) == (500, {"error": "action_failed"})
