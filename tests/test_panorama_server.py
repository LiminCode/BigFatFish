# -*- coding: utf-8 -*-
"""配置全景的本机回环服务：生命周期与拒绝矩阵。

用真实的回环套接字测（``http.client`` 能随意改 Host / Origin，正好冒充浏览器里的坏页面）。
等事件不用固定 sleep，预算给宽。
"""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from pet.panorama import server as srv

WAIT = 15.0     # 等事件的预算（CI 慢机器上也够）；正常几十毫秒就到


def _router() -> srv.Router:
    router = srv.Router()
    router.add("GET", "/api/ping", lambda request: srv.Response.json({"ok": True}))
    router.add("POST", "/api/echo", lambda request: srv.Response.json({"got": request.json()}))
    router.add("GET", "/api/items/{item_id}", lambda request: srv.Response.json(request.params))
    router.add("GET", "/api/boom", _boom)
    router.static("/", b"<!doctype html><title>shell</title>", "text/html; charset=utf-8")
    return router


def _boom(request: srv.Request) -> srv.Response:
    raise RuntimeError("secret detail that must not leak")


@pytest.fixture
def server():
    instance = srv.PanoramaServer(_router(), poll_seconds=0.02)
    instance.start()
    yield instance
    instance.stop()


def _call(server, method="GET", path="/api/ping", *, host="", token="", origin=None, headers=None, body=None,
          port=None):
    """发一个请求，返回 (状态码, 响应头字典, 正文字节)。Host / 令牌 / Origin 都可以单独弄错。"""
    send = {"Host": host or f"127.0.0.1:{server.port}"}
    if token is not None:
        send[srv.TOKEN_HEADER] = token or server.token
    if origin is not None:
        send["Origin"] = origin
    if body is not None and "Content-Type" not in (headers or {}):
        send["Content-Type"] = "application/json"
    send.update(headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", port or server.port, timeout=WAIT)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        payload = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode("utf-8")
        if payload is not None and "Content-Length" not in send:
            send["Content-Length"] = str(len(payload))
        for name, value in send.items():
            connection.putheader(name, value)
        connection.endheaders(payload)
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


# ---------------------------------------------------------------- 生命周期

def test_start_binds_loopback_only_on_a_random_port(server):
    assert server.running
    assert server.bound_address[0] == "127.0.0.1"
    assert server.port > 0
    assert server.base_url == f"http://127.0.0.1:{server.port}"


def test_start_is_idempotent_and_stop_closes_the_port(server):
    first = (server.base_url, server.token)
    assert server.start() == first[0]
    assert (server.base_url, server.token) == first
    port = server.port
    server.stop()
    server.stop()                                   # 再停一次不出错
    assert not server.running
    with pytest.raises(OSError):
        _call(server, port=port)


def test_stop_does_not_wait_for_the_poll_interval():
    """退出应用时 stop() 在 GUI 线程上：服务线程哪怕要睡 60 秒才醒，stop 也得马上回来。"""
    import time

    instance = srv.PanoramaServer(_router(), poll_seconds=60.0)
    instance.start()
    started = time.monotonic()
    instance.stop()
    assert not instance.running
    assert time.monotonic() - started < WAIT        # 没有唤醒的话这里是 60 秒


def test_every_launch_gets_a_new_long_token():
    seen = set()
    for _ in range(3):
        instance = srv.PanoramaServer(_router(), poll_seconds=0.02)
        instance.start()
        try:
            assert len(instance.token) >= 32
            seen.add(instance.token)
        finally:
            instance.stop()
    assert len(seen) == 3


def test_restart_after_stop_issues_a_new_token(server):
    old = server.token
    server.stop()
    server.start()
    assert server.running and server.token != old


def test_page_url_carries_the_token_in_the_fragment_only(server):
    url = server.page_url()
    head, _, fragment = url.partition("#")
    assert head == f"http://127.0.0.1:{server.port}/"
    assert fragment == server.token                 # 片段不会发给服务器，也不进 Referer
    assert "?" not in url


def test_server_keeps_running_however_long_nobody_asks():
    """不再空闲自停：标签页在后台放一晚上，回来时服务还在、令牌还认。"""
    import time

    instance = srv.PanoramaServer(_router(), poll_seconds=0.01)
    instance.start()
    try:
        assert not hasattr(instance, "_idle")       # 没有空闲计时这回事了
        deadline = time.monotonic() + 0.3           # 让服务线程空转几十轮：没有哪一轮会让它停
        while time.monotonic() < deadline:
            time.sleep(0.02)
        assert instance.running and _call(instance)[0] == 200
    finally:
        instance.stop()


# ---------------------------------------------------------------- 会话文件：令牌和端口跨重启

def test_with_a_session_file_a_restart_keeps_the_same_port_and_token(tmp_path):
    """肥鱼重启后旧标签页还认得路：同一个端口、同一个令牌。"""
    session = tmp_path / "panorama-session.json"
    first = srv.PanoramaServer(_router(), poll_seconds=0.02, session=session)
    first.start()
    port, token = first.port, first.token
    first.stop()
    assert json.loads(session.read_text("utf-8")) == {"port": port, "token": token}

    second = srv.PanoramaServer(_router(), poll_seconds=0.02, session=session)
    second.start()
    try:
        assert (second.port, second.token) == (port, token)
        assert _call(second, token=token)[0] == 200
    finally:
        second.stop()


def test_a_taken_port_falls_back_to_a_free_one_and_the_file_follows(tmp_path):
    import socket

    session = tmp_path / "panorama-session.json"
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    taken = squatter.getsockname()[1]
    session.write_text(json.dumps({"port": taken, "token": "t" * 43}), "utf-8")
    instance = srv.PanoramaServer(_router(), poll_seconds=0.02, session=session)
    try:
        instance.start()
        assert instance.running and instance.port != taken
        assert instance.token == "t" * 43                                   # 令牌照旧：换的只是端口
        assert json.loads(session.read_text("utf-8")) == {"port": instance.port, "token": "t" * 43}
    finally:
        instance.stop()
        squatter.close()


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"port": 80, "token": "' + "a" * 43 + '"}',
                                     '{"port": 50000, "token": "short"}', '{"port": 50000, "token": "bad token with spaces!!!!!!!!!!!!!!!"}',
                                     '{"port": "50000", "token": 7}'])
def test_a_broken_session_file_is_replaced_with_a_fresh_one(tmp_path, content):
    session = tmp_path / "panorama-session.json"
    session.write_text(content, "utf-8")
    instance = srv.PanoramaServer(_router(), poll_seconds=0.02, session=session)
    instance.start()
    try:
        saved = json.loads(session.read_text("utf-8"))
        assert saved == {"port": instance.port, "token": instance.token} and len(instance.token) >= 32
    finally:
        instance.stop()


def test_without_a_session_file_every_start_still_gets_a_new_token(tmp_path):
    instance = srv.PanoramaServer(_router(), poll_seconds=0.02)
    instance.start()
    old = instance.token
    instance.stop()
    instance.start()
    try:
        assert instance.token != old
    finally:
        instance.stop()
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- 放行

def test_request_with_host_and_token_is_served(server):
    status, headers, body = _call(server)
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body) == {"ok": True}


def test_same_origin_post_with_json_body_reaches_the_handler(server):
    status, _headers, body = _call(server, "POST", "/api/echo", origin=server.base_url, body={"a": 1})
    assert status == 200 and json.loads(body) == {"got": {"a": 1}}


def test_path_parameters_are_passed_to_the_handler(server):
    status, _headers, body = _call(server, path="/api/items/briefing")
    assert status == 200 and json.loads(body) == {"item_id": "briefing"}


def test_static_shell_needs_no_token_but_still_needs_the_right_host(server):
    status, headers, body = _call(server, path="/", token=None, headers={"Sec-Fetch-Site": "none"})
    assert status == 200 and body.startswith(b"<!doctype html>")
    assert headers["content-type"].startswith("text/html")
    assert _call(server, path="/", token=None, host="evil.example")[0] == 421


# ---------------------------------------------------------------- 拒绝矩阵

@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "127.0.0.1", "localhost", "127.0.0.1:1"])
def test_wrong_host_header_is_rejected(server, host):
    """DNS 重绑定：浏览器连的是回环地址，Host 却是攻击者的域名。"""
    assert _call(server, host=host)[0] == 421


def test_localhost_with_the_right_port_is_still_not_the_expected_host(server):
    assert _call(server, host=f"localhost:{server.port}")[0] == 421


@pytest.mark.parametrize("token", ["wrong", "x" * 43])
def test_wrong_token_is_rejected(server, token):
    assert _call(server, token=token)[0] == 401


def test_missing_token_is_rejected(server):
    assert _call(server, token=None)[0] == 401


def test_token_in_the_query_string_does_not_count(server):
    assert _call(server, path=f"/api/ping?token={server.token}", token=None)[0] == 401


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://127.0.0.1:1", "http://localhost"])
def test_foreign_origin_is_rejected_even_with_a_valid_token(server, origin):
    assert _call(server, origin=origin)[0] == 403


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
def test_api_call_not_marked_same_origin_by_the_browser_is_rejected(server, site):
    assert _call(server, headers={"Sec-Fetch-Site": site})[0] == 403


def test_static_shell_refuses_cross_site_embedding(server):
    assert _call(server, path="/", token=None, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403


def test_write_without_an_origin_header_is_rejected(server):
    assert _call(server, "POST", "/api/echo", body={"a": 1})[0] == 403


def test_write_that_is_not_json_is_rejected(server):
    """普通表单能跨站直接提交；只收 JSON 就逼着浏览器先发预检，而预检我们一律不答应。"""
    status = _call(server, "POST", "/api/echo", origin=server.base_url, body=b"a=1",
                   headers={"Content-Type": "application/x-www-form-urlencoded"})[0]
    assert status == 415


def test_write_with_a_broken_json_body_is_rejected(server):
    assert _call(server, "POST", "/api/echo", origin=server.base_url, body=b"{not json")[0] == 400


def test_oversized_body_is_rejected_before_it_is_read(server):
    status = _call(server, "POST", "/api/echo", origin=server.base_url, body=b"{}",
                   headers={"Content-Length": str(srv.MAX_BODY + 1)})[0]
    assert status == 413


def test_write_without_a_length_is_rejected(server):
    status = _call(server, "POST", "/api/echo", origin=server.base_url,
                   headers={"Content-Type": "application/json"})[0]
    assert status == 411


@pytest.mark.parametrize("method", ["OPTIONS", "HEAD", "TRACE", "DELETE"])
def test_methods_without_a_route_are_refused(server, method):
    status, headers, _body = _call(server, method, origin=server.base_url)
    assert status == 405
    assert not any(name.startswith("access-control-") for name in headers)   # 预检拿不到任何许可


def test_unknown_path_and_wrong_method(server):
    assert _call(server, path="/api/nope")[0] == 404
    assert _call(server, "POST", "/api/ping", origin=server.base_url, body={})[0] == 405


@pytest.mark.parametrize("path", ["/api/../api/ping", "/api/items/a/b", "/api/items/..", "/%2e%2e/api/ping",
                                  "/api/items/a%2Fb", "//evil.example/api/ping", "/api\\ping"])
def test_paths_that_are_not_an_exact_route_are_not_served(server, path):
    assert _call(server, path=path)[0] in (400, 404)


def test_handler_failure_returns_a_plain_500_without_details(server):
    status, _headers, body = _call(server, path="/api/boom")
    assert status == 500
    assert b"secret detail" not in body and b"Traceback" not in body


def test_every_response_carries_the_hardening_headers_and_no_cors(server):
    for kwargs in ({}, {"token": "wrong"}, {"host": "evil.example"}, {"path": "/", "token": None}):
        _status, headers, _body = _call(server, **kwargs)
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cache-control"] == "no-store"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in headers["content-security-policy"]
        assert not any(name.startswith("access-control-") for name in headers)
        assert "python" not in headers.get("server", "").lower()


def test_content_policy_relaxes_inline_style_attributes_and_nothing_else():
    """页面脚本靠内联 style 属性给磁贴定位；脚本、样式表、图片、连接仍然只许同源。"""
    policy = srv.HARDENING_HEADERS["Content-Security-Policy"]
    directives = dict(part.strip().split(" ", 1) for part in policy.split(";"))
    assert directives["default-src"] == "'self'"
    assert directives["style-src-attr"] == "'unsafe-inline'"
    assert policy.count("unsafe") == 1 and "script-src" not in directives and "*" not in policy


def test_server_module_stays_stdlib_only():
    """这一层不碰 Qt：它要能在没有界面的进程里起，也不能把线程规则搅进来。"""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(srv.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(__import__("sys").stdlib_module_names) | {"__future__"}, sorted(imported)
    assert all(not (isinstance(node, ast.ImportFrom) and node.level) for node in ast.walk(tree))


# ---------------------------------------------------------------- 路由表

def test_router_rejects_duplicate_routes_and_bad_patterns():
    router = srv.Router()
    router.add("GET", "/api/a", lambda request: srv.Response.json({}))
    with pytest.raises(ValueError):
        router.add("GET", "/api/a", lambda request: srv.Response.json({}))
    with pytest.raises(ValueError):
        router.add("GET", "api/no-leading-slash", lambda request: srv.Response.json({}))
    with pytest.raises(ValueError):
        router.add("FETCH", "/api/b", lambda request: srv.Response.json({}))
