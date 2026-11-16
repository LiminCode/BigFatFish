# -*- coding: utf-8 -*-
"""配置全景的路由表：页面外壳和静态文件不要令牌，数据要令牌；「等新数据」会把请求挂到有为止。走真实的本机服务。"""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from pet import i18n
from pet.panorama import render, routes, sources
from pet.panorama import server as srv
from pet.panorama.feed import Feed
from tests import panorama_samples as samples

WAIT = 15.0


def _serve(feed, **kwargs):
    instance = srv.PanoramaServer(routes.build_router(feed, **kwargs), poll_seconds=0.02)
    instance.start()
    return instance


@pytest.fixture
def served():
    i18n.set_language("zh")
    feed = Feed()
    instance = _serve(feed, wait_seconds=0.05)
    yield instance, feed
    feed.close()
    instance.stop()


def _get(instance, path, *, token=True, headers=None):
    send = {"Host": f"127.0.0.1:{instance.port}", **(headers or {})}
    if token:
        send[srv.TOKEN_HEADER] = instance.token
    connection = http.client.HTTPConnection("127.0.0.1", instance.port, timeout=WAIT)
    try:
        connection.request("GET", path, headers=send)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type", ""), response.read()
    finally:
        connection.close()


def _publish(feed, **facts_kwargs):
    return feed.publish(lambda revision: render.payload(sources.build(samples.facts(**facts_kwargs)), revision=revision))


def test_shell_and_static_files_are_served_without_a_token(served):
    instance, _feed = served
    status, content_type, body = _get(instance, "/", token=False, headers={"Sec-Fetch-Site": "none"})
    assert status == 200 and content_type.startswith("text/html") and body.decode("utf-8") == render.shell()
    for name, expected in render.ASSETS.items():
        status, content_type, body = _get(instance, f"/{name}", token=False, headers={"Sec-Fetch-Site": "same-origin"})
        assert (status, content_type) == (200, expected) and body == render.asset(name)


def test_graph_needs_the_token_and_is_not_ready_before_the_first_publish(served):
    instance, feed = served
    assert _get(instance, "/api/graph", token=False)[0] == 401
    status, _type, body = _get(instance, "/api/graph")
    assert status == 503 and json.loads(body) == {"error": "not_ready"}
    _publish(feed)
    status, content_type, body = _get(instance, "/api/graph")
    assert status == 200 and content_type.startswith("application/json") and body == feed.latest()
    assert json.loads(body)["revision"] == 1


def test_ping_answers_and_nothing_else_is_reachable(served):
    instance, _feed = served
    status, _type, body = _get(instance, "/api/ping")
    assert status == 200 and json.loads(body)["ok"] is True
    for path in ("/shell.html", "/render.py", "/page/app.js", "/../render.py", "/favicon.ico", "/api/graph/extra"):
        assert _get(instance, path)[0] in (400, 404), path


# ---------------------------------------------------------------- 等新数据

def test_asking_for_something_newer_gets_it_at_once_when_it_exists(served):
    instance, feed = served
    _publish(feed)
    _publish(feed)
    status, _type, body = _get(instance, "/api/graph?after=1")
    assert status == 200 and json.loads(body)["revision"] == 2
    assert _get(instance, "/api/graph?after=0")[0] == 200


def test_asking_for_something_newer_comes_back_empty_after_the_wait(served):
    instance, feed = served
    _publish(feed)
    status, _type, body = _get(instance, "/api/graph?after=1")
    assert status == 204 and body == b""
    assert _get(instance, "/api/graph?after=1", token=False)[0] == 401          # 等也要令牌


@pytest.mark.parametrize("after", ["abc", "", "1.5", "1;drop"])
def test_a_revision_that_is_not_a_number_is_refused(served, after):
    instance, _feed = served
    assert _get(instance, f"/api/graph?after={after}")[0] == 400


def test_a_held_request_is_answered_the_moment_new_data_is_published():
    """请求先到、数据后到：不用等满，发布的那一刻就回。"""
    i18n.set_language("zh")
    feed = Feed()
    instance = _serve(feed, wait_seconds=WAIT)
    try:
        _publish(feed)
        box = {}
        thread = threading.Thread(target=lambda: box.update(result=_get(instance, "/api/graph?after=1")), daemon=True)
        thread.start()
        _publish(feed, wsl="absent")
        thread.join(WAIT)
        assert not thread.is_alive()
        status, _type, body = box["result"]
        assert status == 200 and json.loads(body)["revision"] == 2
    finally:
        feed.close()
        instance.stop()


def test_closing_the_feed_lets_held_requests_go():
    """退出应用：挂着的请求马上放回去（204），不拖着线程等满。"""
    feed = Feed()
    instance = _serve(feed, wait_seconds=60.0)
    try:
        _publish(feed)
        box = {}
        thread = threading.Thread(target=lambda: box.update(result=_get(instance, "/api/graph?after=1")), daemon=True)
        thread.start()
        feed.close()
        thread.join(WAIT)
        assert not thread.is_alive() and box["result"][0] == 204
    finally:
        instance.stop()
