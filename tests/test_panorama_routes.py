# -*- coding: utf-8 -*-
"""配置全景的路由表：页面外壳和静态文件不要令牌，数据要令牌。走真实的本机服务。"""
from __future__ import annotations

import http.client
import json

import pytest

from pet import i18n
from pet.panorama import render, routes, sources
from pet.panorama import server as srv
from tests import panorama_samples as samples


@pytest.fixture
def served():
    i18n.set_language("zh")
    box = {"payload": None}
    instance = srv.PanoramaServer(routes.build_router(lambda: box["payload"]), poll_seconds=0.02)
    instance.start()
    yield instance, box
    instance.stop()


def _get(instance, path, *, token=True, headers=None):
    send = {"Host": f"127.0.0.1:{instance.port}", **(headers or {})}
    if token:
        send[srv.TOKEN_HEADER] = instance.token
    connection = http.client.HTTPConnection("127.0.0.1", instance.port, timeout=15)
    try:
        connection.request("GET", path, headers=send)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type", ""), response.read()
    finally:
        connection.close()


def test_shell_and_static_files_are_served_without_a_token(served):
    instance, _box = served
    status, content_type, body = _get(instance, "/", token=False, headers={"Sec-Fetch-Site": "none"})
    assert status == 200 and content_type.startswith("text/html") and body.decode("utf-8") == render.shell()
    for name, expected in render.ASSETS.items():
        status, content_type, body = _get(instance, f"/{name}", token=False, headers={"Sec-Fetch-Site": "same-origin"})
        assert (status, content_type) == (200, expected) and body == render.asset(name)


def test_graph_needs_the_token_and_is_not_ready_before_the_first_publish(served):
    instance, box = served
    assert _get(instance, "/api/graph", token=False)[0] == 401
    status, _type, body = _get(instance, "/api/graph")
    assert status == 503 and json.loads(body) == {"error": "not_ready"}
    box["payload"] = render.payload(sources.build(samples.facts()), revision=4)
    status, content_type, body = _get(instance, "/api/graph")
    assert status == 200 and content_type.startswith("application/json") and body == box["payload"]
    assert json.loads(body)["revision"] == 4


def test_ping_answers_and_nothing_else_is_reachable(served):
    instance, _box = served
    status, _type, body = _get(instance, "/api/ping")
    assert status == 200 and json.loads(body)["ok"] is True
    for path in ("/shell.html", "/render.py", "/page/app.js", "/../render.py", "/favicon.ico", "/api/graph/extra"):
        assert _get(instance, path)[0] in (400, 404), path
