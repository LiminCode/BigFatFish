# -*- coding: utf-8 -*-
"""配置全景的后台服务：两段写盘、打开浏览器的时机、忙时与退出时的行为。

线程用注入的 ``spawn`` 换成「当场跑」或「先存着」，信号同线程直连，所以不用等。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.panorama import render
from pet.panorama.service import PanoramaService
from tests import panorama_samples as samples


@pytest.fixture(autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    i18n.set_language("zh")
    yield app


def _config(tmp_path, data=None):
    return SimpleNamespace(data=data if data is not None else samples.all_on_config(), path=tmp_path / "config.json", dir=tmp_path)


def _windows_facts(cfg, *, cfg_path, secret_get, api_health):
    facts = samples.facts(cfg=cfg, health=api_health[0])
    del facts["wsl"], facts["timing"]["wsl_s"]
    return facts


class _FakeServer:
    """记账的假本机服务：不开端口。``fail`` 为真时起不来。"""

    URL = "http://127.0.0.1:54321/#TOKEN-NOT-FOR-LOGS"

    def __init__(self, log=None, *, fail=False):
        self.log, self.fail, self.running = log if log is not None else [], fail, False

    def start(self):
        if self.fail:
            raise OSError("no port for you")
        if not self.running:
            self.log.append("serve")
        self.running = True
        return self.URL.split("/#")[0]

    def page_url(self):
        return self.URL

    def stop(self):
        if self.running:
            self.log.append("unserve")
        self.running = False


class _Harness:
    """把服务的每个边界换成记账的假货；``log`` 是事件发生的先后。"""

    def __init__(self, tmp_path, *, spawn=None, wsl=None, windows=None, data=None, server_fails=False):
        self.log, self.pages, self.pending_runs, self.finished, self.opened = [], [], [], [], []
        self.config = _config(tmp_path, data)
        self.wsl_result = samples.wsl_home()
        self.server = _FakeServer(self.log, fail=server_fails)

        def default_wsl():
            self.log.append("wsl")
            return self.wsl_result

        def write(facts, out_dir):
            self.log.append("write")
            self.pages.append(json.loads(json.dumps(facts, default=str)))
            return out_dir / render.PAGE_NAME

        self.service = PanoramaService(
            self.config, health=lambda: ("ok", "fine"), secret_get=lambda ref: "", windows=windows or _windows_facts,
            wsl=wsl or default_wsl, write=write, open_page=self._opened,
            spawn=spawn or (lambda run: run()), server=self.server)
        self.service.finished.connect(lambda ok, text: self.finished.append((ok, text)))

    def _opened(self, target):
        self.log.append("open")
        self.opened.append(target)

    def published(self) -> dict:
        return json.loads(self.service.graph_payload())


def test_first_open_shows_the_windows_half_then_fills_in_wsl(tmp_path):
    h = _Harness(tmp_path)
    assert h.service.open() is True
    assert h.log == ["write", "serve", "open", "wsl", "write"]           # 先出图、起服务、开浏览器，再去探 WSL
    assert h.pages[0]["wsl"] == {"pending": True} and "wsl_s" not in h.pages[0]["timing"]
    assert h.pages[1]["wsl"]["distro"] == "Ubuntu-24.04" and "wsl_s" in h.pages[1]["timing"]
    assert h.pages[1]["api_health"]["state"] == "ok"                     # 体检结论取自岛上的体检器
    assert h.finished == [(True, str(tmp_path / "panorama" / render.PAGE_NAME))] and not h.service.is_busy()


def test_second_open_pads_with_the_last_wsl_result_while_it_checks_again(tmp_path):
    h = _Harness(tmp_path)
    h.service.open()
    h.wsl_result = samples.wsl_home(hooks={})
    h.log.clear(), h.pages.clear()
    h.service.open()
    assert h.log == ["write", "open", "wsl", "write"]                    # 服务已经开着：不再起第二次
    assert h.pages[0]["refreshing"] is True and h.pages[0]["wsl"]["hooks"] == samples.FISH_HOOKS    # 垫的是上一轮的
    assert "refreshing" not in h.pages[1] and h.pages[1]["wsl"]["hooks"] == {}                      # 换成这一轮的


def test_opening_again_while_a_round_is_running_does_not_collect_twice(tmp_path):
    held = []
    h = _Harness(tmp_path, spawn=held.append)
    assert h.service.open() is True and h.service.is_busy()
    assert h.service.open() is False and h.log == []                     # 页面还没写出来：什么也不做
    page = tmp_path / "panorama" / render.PAGE_NAME
    page.parent.mkdir()
    page.write_text("x", encoding="utf-8")
    assert h.service.open() is False and h.log == ["serve", "open"]      # 已经有页面：只是再打开一次
    assert len(held) == 1
    held[0]()
    assert not h.service.is_busy() and h.log.count("write") == 2


def test_a_round_that_ends_after_quit_neither_opens_the_browser_nor_reports(tmp_path):
    held = []
    h = _Harness(tmp_path, spawn=held.append)
    h.service.open()
    h.service.stop()                                                     # aboutToQuit
    held[0]()
    assert "open" not in h.log and h.finished == []
    h.log.clear(), h.pages.clear()
    h2 = _Harness(tmp_path)
    h2.service.open()
    assert h2.pages[0]["wsl"] == {"pending": True}                       # 作废那一轮没留下垫底的结果


def test_wsl_probe_blowing_up_still_ends_with_a_page_that_stops_waiting(tmp_path):
    def boom():
        raise OSError("wsl went away")

    h = _Harness(tmp_path, wsl=boom)
    h.service.open()
    assert h.pages[-1]["wsl"] == {"error": "OSError: wsl went away"}
    assert h.finished and h.finished[0][0] is True and not h.service.is_busy()


def test_windows_side_failing_reports_failure_and_frees_the_service(tmp_path):
    def boom(cfg, **_kwargs):
        raise ValueError("bad config")

    h = _Harness(tmp_path, windows=boom)
    assert h.service.open() is True
    assert h.log == [] and h.finished == [(False, "ValueError: bad config")] and not h.service.is_busy()
    assert h.service.open() is True                                      # 下一次还能再试


def test_worker_sees_a_copy_of_the_config_not_the_live_one(tmp_path):
    held, seen = [], {}

    def windows(cfg, **kwargs):
        seen["enabled"] = cfg["work_briefing"]["enabled"]
        return _windows_facts(cfg, **kwargs)

    h = _Harness(tmp_path, spawn=held.append, windows=windows)
    h.service.open()
    h.config.data["work_briefing"]["enabled"] = False                    # 用户在采集途中改了设置
    held[0]()
    assert seen["enabled"] is True


def test_real_pages_land_on_disk_and_the_last_one_is_no_longer_pending(tmp_path):
    written = []

    def keep(facts, out_dir):
        from pet.panorama import sources
        path = render.write(sources.build(facts), out_dir)
        written.append(path.read_text(encoding="utf-8"))
        return path

    service = PanoramaService(_config(tmp_path), windows=_windows_facts, wsl=samples.wsl_home, write=keep,
                              open_page=lambda path: None, spawn=lambda run: run(), server=_FakeServer())
    service.open()
    assert '"pending": true' in written[0] and '"pending": false' in written[1]
    assert service.page_path.is_file() and not list(service.page_path.parent.glob("*.tmp"))


# ---------------------------------------------------------------- 本机服务这一侧

def test_browser_is_sent_to_the_local_service_not_to_the_file(tmp_path):
    h = _Harness(tmp_path)
    assert not h.server.running                                          # 不点就不起
    h.service.open()
    assert h.opened == [_FakeServer.URL]


def test_each_stage_publishes_the_data_with_a_new_revision(tmp_path):
    held = []
    h = _Harness(tmp_path, spawn=held.append)
    assert h.service.graph_payload() is None                             # 还没发布过
    h.service.open()
    seen = []

    def wsl():
        seen.append(h.published())                                       # 探 WSL 的时候，页面已经能要到第一份
        return samples.wsl_home()

    h.service._wsl = wsl
    held[0]()
    assert seen[0]["revision"] == 1 and seen[0]["meta"]["pending"] is True
    final = h.published()
    assert final["revision"] == 2 and final["meta"]["pending"] is False
    assert any(n["region"] == "wsl" for n in final["nodes"]) and final["strings"]["title"]


def test_opening_again_keeps_counting_revisions_up(tmp_path):
    h = _Harness(tmp_path)
    h.service.open()
    h.service.open()
    assert h.published()["revision"] == 4                                # 页面靠它变没变来判断要不要重读


def test_when_the_service_cannot_start_the_snapshot_file_is_opened_instead(tmp_path):
    h = _Harness(tmp_path, server_fails=True)
    h.service.open()
    assert h.opened == [str(tmp_path / "panorama" / render.PAGE_NAME)]
    assert h.finished and h.finished[0][0] is True


def test_quitting_stops_the_local_service(tmp_path):
    h = _Harness(tmp_path)
    h.service.open()
    h.service.stop()
    assert not h.server.running and h.log[-1] == "unserve"


def test_the_token_never_reaches_the_log(tmp_path, caplog):
    h = _Harness(tmp_path)
    with caplog.at_level("DEBUG"):
        h.service.open()
    assert "http://127.0.0.1:54321/" in caplog.text and "TOKEN-NOT-FOR-LOGS" not in caplog.text


def test_real_service_serves_what_was_published_and_stops_on_quit(tmp_path):
    """不换假货：真的起本机服务，用页面的方式（带令牌的请求头）把数据要回来。"""
    import http.client

    opened = []
    service = PanoramaService(_config(tmp_path), windows=_windows_facts, wsl=samples.wsl_home,
                              open_page=opened.append, spawn=lambda run: run())
    try:
        service.open()
        base, _, token = opened[0].partition("/#")
        port = int(base.rsplit(":", 1)[1])
        assert base == f"http://127.0.0.1:{port}" and len(token) >= 32

        def get(path, headers):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
            try:
                connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **headers})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        status, body = get("/api/graph", {"X-Panorama-Token": token})
        data = json.loads(body)
        assert status == 200 and data["revision"] == 2 and data["meta"]["pending"] is False
        assert get("/api/graph", {})[0] == 401
        status, shell = get("/", {})
        assert status == 200 and b'src="/boot.js"' in shell and token.encode() not in shell
        assert service.page_path.is_file()                               # 离线快照照样写了
    finally:
        service.stop()
    assert not service._server.running
