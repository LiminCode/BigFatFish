# -*- coding: utf-8 -*-
"""报告页整条路：服务里的登记与发布（``PanoramaService.report`` / ``publish_report`` / ``open_report``）、真实本机服务上的
两个网址（``/report/<名字>`` 公开外壳、``/api/report/<名字>`` 要令牌、``?after=`` 等更新的）、页面脚本本身（QJSEngine）。

页面脚本和配置全景的 ``boot.js`` 共用 ``client.js``（取令牌、带令牌的 fetch）。
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.panorama import actions, render, routes
from pet.panorama import server as srv
from pet.panorama.service import PanoramaService
from tests import panorama_samples as samples
from tests.test_panorama_page import FAKE_BROWSER, FAKE_DOM, _evaluate

WAIT = 30.0


@pytest.fixture(autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    i18n.set_language("zh")
    yield app
    i18n.set_language("zh")


def _config(tmp_path):
    return SimpleNamespace(data=samples.all_on_config(), path=tmp_path / "config.json", dir=tmp_path)


def _report(counter, **over):
    counter["n"] += 1
    return {"id": "demo", "title": "示例", "theme": "dark", "available": True, "summary": f"第 {counter['n']} 份", "generated": "生成于 x",
            "usage": [{"key": "time", "text": "3 秒", "tip": "t"}], "html": "<h3>A</h3>", "busy": False, "busy_text": "忙",
            "empty_text": "空", "error": "", "action": {"name": "generate_report", "report": "demo", "label": "重做", "hint": ""}, **over}


def _service(tmp_path, opened=None, server=None, **kwargs):
    counter = {"n": 0}
    service = PanoramaService(_config(tmp_path), windows=lambda *a, **k: {}, wsl=dict, write=lambda facts, out_dir: out_dir / "p.html",
                              open_page=(opened if opened is not None else []).append, spawn=lambda run: None, server=server,
                              reports={"demo": lambda: _report(counter)},
                              actions={"generate_report": actions.generate_report({"demo": lambda: "started"})}, **kwargs)
    return service, counter


class _FakeServer:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True
        return "http://127.0.0.1:1/"

    def page_url(self, path="/"):
        return f"http://127.0.0.1:1{path}#TOKEN"

    def stop(self):
        self.running = False


# ───────────────────────── 服务 ─────────────────────────

def test_publishing_only_happens_once_someone_has_looked(tmp_path):
    service, counter = _service(tmp_path)
    assert service.has_report("demo") and not service.has_report("nope")
    assert service.publish_report("demo") is False and counter["n"] == 0, "没人打开过页面：生成结束的信号不白做"
    assert service.publish_report("demo", force=True) is True and counter["n"] == 1
    assert service.publish_report("demo") is True and counter["n"] == 2, "看过一次之后每次都重做"
    assert json.loads(service.report("demo", None, 0.0))["report"]["summary"] == "第 2 份"
    assert service.report("demo", 2, 0.01) is None and service.report_watched("demo") is False
    with pytest.raises(actions.ActionError):
        service.report("nope", None, 0.0)


def test_the_first_request_makes_the_report_on_the_gui_thread(tmp_path):
    service, counter = _service(tmp_path)
    data = json.loads(service.report("demo", None, 0.0))          # 在界面线程上：on_gui 直接跑
    assert counter["n"] == 1 and data["revision"] == 1 and data["page"] == {"lang": "zh-CN", "title": "示例 · 大肥鱼"}
    assert data["report"]["summary"] == "第 1 份" and data["strings"]["report_lost"].startswith("和肥鱼的连接断了")


def test_opening_a_report_starts_the_server_and_opens_its_page_not_the_panorama(tmp_path):
    opened = []
    service, counter = _service(tmp_path, opened, server=_FakeServer())
    assert service.open_report("demo") is True
    assert opened == ["http://127.0.0.1:1/report/demo#TOKEN"] and counter["n"] == 1 and service.is_busy() is False
    assert service.open_report("nope") is False and len(opened) == 1


def test_a_server_that_cannot_start_means_the_report_cannot_open(tmp_path):
    class Dead(_FakeServer):
        def start(self):
            raise OSError("no port")

    opened = []
    service, _counter = _service(tmp_path, opened, server=Dead())
    assert service.open_report("demo") is False and opened == []


def test_stop_releases_pages_waiting_on_a_report(tmp_path):
    service, _counter = _service(tmp_path)
    service.publish_report("demo", force=True)
    box = {}
    thread = threading.Thread(target=lambda: box.update(out=service.report("demo", 1, WAIT)), daemon=True)
    thread.start()
    deadline = time.monotonic() + WAIT
    while not service.report_watched("demo") and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.report_watched("demo"), "有页面挂着等 = 用户正开着看"
    service.stop()
    thread.join(WAIT)
    assert not thread.is_alive() and box["out"] is None


# ───────────────────────── 真实本机服务上的两个网址 ─────────────────────────

@pytest.fixture
def stack(tmp_path):
    app = QApplication.instance()
    service, counter = _service(tmp_path)
    server = srv.PanoramaServer(routes.build_router(service._feed, settings=service, wait_seconds=0.2), poll_seconds=0.02)
    server.start()
    yield SimpleNamespace(app=app, service=service, server=server, counter=counter)
    service.stop()
    server.stop()


def _send(server, method, path, body=None, *, token=True):
    headers = {"Host": f"127.0.0.1:{server.port}"}
    if token:
        headers[srv.TOKEN_HEADER] = server.token
    payload = None
    if body is not None:
        headers.update({"Origin": f"http://127.0.0.1:{server.port}", "Content-Type": "application/json"})
        payload = json.dumps(body).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=WAIT)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, response.getheader("Content-Type", ""), data
    finally:
        connection.close()


def _pump(app, call):
    box = {}
    worker = threading.Thread(target=lambda: box.update(out=call()), daemon=True)
    worker.start()
    deadline = time.monotonic() + WAIT
    while worker.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        worker.join(0.005)
    assert not worker.is_alive(), "the request never came back"
    return box["out"]


def test_the_shell_is_public_for_known_reports_only(stack):
    status, content_type, body = _pump(stack.app, lambda: _send(stack.server, "GET", "/report/demo", token=False))
    assert status == 200 and content_type.startswith("text/html") and b'src="/report.js"' in body and "示例".encode() not in body
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/report/nope", token=False))[0] == 404
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/report.js", token=False))[0] == 200
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/client.js", token=False))[0] == 200
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/report.css", token=False))[0] == 200


def test_the_data_needs_the_token_and_is_made_on_first_ask(stack):
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/demo", token=False))[0] == 401
    status, _type, body = _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/demo"))
    data = json.loads(body)
    assert status == 200 and data["revision"] == 1 and data["report"]["summary"] == "第 1 份" and stack.counter["n"] == 1
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/nope"))[0] == 404
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/demo?after=x"))[0] == 400


def test_waiting_for_a_newer_report_gets_it_when_the_service_publishes(stack):
    _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/demo"))
    assert _pump(stack.app, lambda: _send(stack.server, "GET", "/api/report/demo?after=1"))[0] == 204
    box = {}
    thread = threading.Thread(target=lambda: box.update(out=_send(stack.server, "GET", "/api/report/demo?after=1")), daemon=True)
    thread.start()
    deadline = time.monotonic() + WAIT
    while not stack.service.report_watched("demo") and time.monotonic() < deadline:
        time.sleep(0.005)
    stack.service.publish_report("demo")                       # 生成结束：主进程发布，挂着的请求立刻拿到
    thread.join(WAIT)
    status, _type, body = box["out"]
    assert status == 200 and json.loads(body)["revision"] == 2 and json.loads(body)["report"]["summary"] == "第 2 份"


def test_the_regenerate_action_goes_through_the_action_route(stack):
    status, _type, body = _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/generate_report", {"report": "demo"}))
    assert (status, json.loads(body)) == (200, {"report": "demo", "state": "started"})
    status, _type, body = _pump(stack.app, lambda: _send(stack.server, "POST", "/api/actions/generate_report", {"report": "nope"}))
    assert (status, json.loads(body)) == (400, {"error": "bad_report"})


# ───────────────────────── render ─────────────────────────

def test_report_shell_and_assets_hold_no_data_and_no_inline_script():
    shell = render.report_shell()
    assert re.findall(r"<script[^>]*>", shell) == ['<script type="module" src="/report.js">'] and "<style" not in shell
    assert '<html lang="zh-CN">' in shell and "连接断了" in shell and not re.search(r"__[A-Z]+__", shell)
    for name in render.REPORT_MODULES + render.REPORT_STYLES:
        assert name in render.ASSETS
    assert "report.js" not in render.MODULES, "报告页的入口不能拼进全景的离线快照里"
    text = render.bundle(render.REPORT_MODULES)
    assert not re.search(r"^\s*(import|export)\b", text, re.M) and "function takeToken(" in text and "/api/report/" in text


def test_report_payload_carries_the_revision_page_and_strings():
    data = json.loads(render.report_payload({"title": "工作简报", "html": "<p>x</p>"}, revision=4))
    assert data["revision"] == 4 and data["page"] == {"lang": "zh-CN", "title": "工作简报 · 大肥鱼"}
    assert data["report"] == {"title": "工作简报", "html": "<p>x</p>"} and set(data["strings"]) == set(render.REPORT_KEYS)


# ───────────────────────── 页面脚本 ─────────────────────────

@pytest.fixture(scope="module")
def engine():
    app = QApplication.instance() or QApplication([])
    js = QJSEngine()
    yield js
    del js, app


REPORT_DOM = """
document.documentElement.dataset = {};
location.pathname = '/report/demo';
location.origin = 'http://127.0.0.1:1';
var dom = function () { var el = document.getElementById; return {title: el('title').textContent, generated: el('generated').textContent,
  summary: el('summary').textContent, summaryHidden: el('summary').hidden, usage: el('usage').innerHTML, body: el('body').innerHTML,
  status: el('status').textContent, statusClass: el('status').className, button: el('action').textContent, buttonHidden: el('action').hidden,
  buttonDisabled: el('action').disabled, lost: el('lost').hidden, theme: document.documentElement.dataset.theme, title_tag: document.title,
  details: el('details').innerHTML}; };
var clicks = {};
document.getElementById('action').addEventListener = function (type, fn) { clicks[type] = fn; };
"""

def _payload(revision=1, **over):
    counter = {"n": revision - 1}
    return json.dumps(json.loads(render.report_payload(_report(counter, **over), revision=revision)), ensure_ascii=False)


def _page(engine, responses: list[str], steps: str = "") -> dict:
    setup = REPORT_DOM + "location.hash = '#tok-1';\nresponses = [" + ",".join(responses) + "];\n"
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.bundle(render.REPORT_MODULES) + steps +
                     "\nreturn JSON.stringify({dom: dom(), requests: requests.map(function (r) { return {path: r.path, method: r.method, "
                     "token: r.headers['X-Panorama-Token'], body: r.body}; }), timers: timers.length, hash: location.hash, store: store});")


def _ok(data: str) -> str:
    return '{"status": 200, "data": ' + data + "}"


def test_the_page_takes_the_token_asks_for_its_report_and_lays_it_out(engine):
    out = _page(engine, [_ok(_payload()), '{"hang": true}'])
    assert out["requests"][0] == {"path": "/api/report/demo", "method": "GET", "token": "tok-1"}
    assert out["requests"][1]["path"] == "/api/report/demo?after=1", "拿到第一份就带着编号去等更新的"
    assert out["hash"] == "" and out["store"] == {"report-token": "tok-1"}, "令牌从地址栏抹掉、存进 sessionStorage"
    dom = out["dom"]
    assert dom["title"] == "示例" and dom["title_tag"] == "示例 · 大肥鱼" and dom["theme"] == "dark" and dom["generated"] == "生成于 x"
    assert dom["summary"] == "第 1 份" and dom["summaryHidden"] is False and dom["body"] == "<h3>A</h3>"
    assert dom["usage"] == '<span class="u" title="t">3 秒</span>'
    assert dom["button"] == "重做" and dom["buttonHidden"] is False and dom["buttonDisabled"] is False and dom["lost"] is True


def test_the_run_record_is_laid_out_as_collapsible_sections_with_the_settings_link_filled_in(engine):
    details = [{"title": "怎么生成的 <b>", "html": '<p>x</p><a class="settings" href="__SETTINGS_URL__">改</a>'}, {"title": "命令", "html": "<pre>c</pre>"}]
    out = _page(engine, [_ok(_payload(details=details, settings_focus="work_briefing")), '{"hang": true}'])
    assert out["dom"]["details"] == ('<details open><summary>怎么生成的 &lt;b&gt;</summary><div class="d"><p>x</p>'
                                     '<a class="settings" href="http://127.0.0.1:1/#tok-1&settings=work_briefing">改</a></div></details>'
                                     '<details><summary>命令</summary><div class="d"><pre>c</pre></div></details>')
    assert _page(engine, [_ok(_payload()), '{"hang": true}'])["dom"]["details"] == "", "没有记录就什么都不摆"


def test_busy_empty_unavailable_and_error_states(engine):
    busy = _page(engine, [_ok(_payload(html="", summary="", busy=True)), '{"hang": true}'])["dom"]
    assert busy["body"] == '<p class="note">忙</p>' and busy["status"] == "忙" and busy["buttonDisabled"] is True and busy["summaryHidden"] is True
    empty = _page(engine, [_ok(_payload(html="", summary="")), '{"hang": true}'])["dom"]
    assert empty["body"] == '<p class="note">空</p>' and empty["status"] == "" and empty["buttonDisabled"] is False
    gone = _page(engine, [_ok(_payload(available=False, html="")), '{"hang": true}'])["dom"]
    assert gone["body"].startswith('<p class="note">这台机器上没有这项功能') and gone["buttonHidden"] is True
    failed = _page(engine, [_ok(_payload(error="上一次没生成出来：boom")), '{"hang": true}'])["dom"]
    assert failed["status"] == "上一次没生成出来：boom" and failed["statusClass"] == "status bad" and failed["body"] == "<h3>A</h3>"


def test_a_newer_report_redraws_in_place_and_nothing_new_retries_later(engine):
    out = _page(engine, [_ok(_payload()), _ok(_payload(revision=2)), '{"status": 204}'])
    assert out["dom"]["summary"] == "第 2 份" and [r["path"] for r in out["requests"]][1:] == ["/api/report/demo?after=1", "/api/report/demo?after=2"]
    assert out["timers"] == 1, "204 之后隔一会儿再去等"


def test_losing_the_service_says_so_and_disables_the_button(engine):
    out = _page(engine, [_ok(_payload())])                      # 第二个请求没有回答 = 连不上
    assert out["dom"]["lost"] is False and out["dom"]["buttonDisabled"] is True


def test_the_regenerate_button_posts_and_leaves_the_redraw_to_the_started_signal(engine):
    click = "\nclicks.click();"
    out = _page(engine, [_ok(_payload()), '{"hang": true}', _ok('{"report": "demo", "state": "started"}')], click)
    post = out["requests"][2]
    assert post == {"path": "/api/actions/generate_report", "method": "POST", "token": "tok-1", "body": '{"report":"demo"}'}
    assert out["dom"]["buttonDisabled"] is True and out["dom"]["status"] == "已出发，大约一分钟…"

    busy = _page(engine, [_ok(_payload()), '{"hang": true}', _ok('{"report": "demo", "state": "busy"}')], click)["dom"]
    assert busy["buttonDisabled"] is True and busy["status"] == "正在生成，等它完成。"
    failed = _page(engine, [_ok(_payload()), '{"hang": true}', _ok('{"report": "demo", "state": "failed"}')], click)["dom"]
    assert failed["buttonDisabled"] is False and failed["status"] == "没能发起，看肥鱼的日志。"
    lost = _page(engine, [_ok(_payload()), '{"hang": true}'], click)["dom"]
    assert lost["buttonDisabled"] is False and lost["status"] == "连不上肥鱼。"
