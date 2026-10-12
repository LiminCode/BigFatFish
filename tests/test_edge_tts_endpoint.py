# -*- coding: utf-8 -*-
"""语音合成的服务端点：握手被拒时换到另一个端点再试。

现场（2026-10-10 起，edge-tts 上游 issue #490）：微软的旧端点
``speech.platform.bing.com/…/readaloud/edge/v1`` 对合成请求一律握手 403，音色列表仍
正常；桌宠每个整点都弹「语音合成失败」。同一份请求发到新端点
``api.msedgeservices.com/tts/cognitiveservices/websocket/v1`` 能成功。

边界用替身：一个假的 ``edge_tts`` 包，按当前 ``communicate.WSS_URL`` 决定成功还是 403。
不打网络。
"""
from __future__ import annotations

import sys
import types

import pytest

from pet import edge_tts_endpoint as endpoint
from pet import voice_chime_service as svc_mod

LEGACY = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=TOKEN"
NEW_HOST = "api.msedgeservices.com"


class _Rejected(Exception):
    """aiohttp.WSServerHandshakeError 的替身：握手阶段的 HTTP 状态码在 ``status`` 上。"""

    def __init__(self, status: int) -> None:
        super().__init__(f"{status}, message='Invalid response status'")
        self.status = status


@pytest.fixture
def fake_edge_tts(monkeypatch):
    """装一个假的 edge_tts：``works`` 里的主机能合成，其余主机握手 ``status``。"""
    state = types.SimpleNamespace(works={NEW_HOST}, status=403, urls=[], error=None)
    communicate = types.ModuleType("edge_tts.communicate")
    communicate.WSS_URL = LEGACY
    constants = types.ModuleType("edge_tts.constants")
    constants.TRUSTED_CLIENT_TOKEN = "TOKEN"

    class Communicate:
        def __init__(self, text, voice, **_kwargs):
            self.text, self.voice = text, voice

        async def save(self, path):
            url = communicate.WSS_URL
            state.urls.append(url)
            if state.error is not None:
                raise state.error
            if not any(host in url for host in state.works):
                with open(path, "wb") as handle:      # 真库失败时也会留下半截文件
                    handle.write(b"")
                raise _Rejected(state.status)
            with open(path, "wb") as handle:
                handle.write(b"\xff\xf3mp3")

    package = types.ModuleType("edge_tts")
    package.Communicate, package.communicate, package.constants = Communicate, communicate, constants
    for name, module in (("edge_tts", package), ("edge_tts.communicate", communicate),
                         ("edge_tts.constants", constants)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(svc_mod, "refresh_voice_list", lambda *a, **k: None)
    monkeypatch.setattr(svc_mod, "EDGE_RETRY_DELAY_S", 0)
    endpoint.reset()
    state.module = communicate
    yield state
    endpoint.reset()


def _speak(tmp_path, name="chime.mp3"):
    """跑一次合成（同步执行工作线程的 run），返回 (产物路径, 错误文字)。"""
    done: list = []
    out = tmp_path / name
    worker = svc_mod._TTSWorker("现在是零点整。", "zh-CN-XiaoyiNeural", "+0%", "+0Hz", out,
                                lambda path, text, error: done.append((path, text, error)))
    worker.run()
    assert len(done) == 1
    return out, done[0][2]


def test_a_rejected_handshake_moves_to_the_other_endpoint_and_the_chime_still_plays(fake_edge_tts, tmp_path):
    out, error = _speak(tmp_path)

    assert error == "", "用户不该再看到「语音合成失败」"
    assert out.read_bytes() == b"\xff\xf3mp3"
    assert [NEW_HOST in url for url in fake_edge_tts.urls] == [False, True], "先试原端点，被拒后换一个"
    assert "Ocp-Apim-Subscription-Key=TOKEN" in fake_edge_tts.urls[1]


def test_the_endpoint_that_worked_is_kept_for_the_rest_of_the_run(fake_edge_tts, tmp_path):
    _speak(tmp_path, "first.mp3")
    fake_edge_tts.urls.clear()

    _out, error = _speak(tmp_path, "second.mp3")

    assert error == "" and len(fake_edge_tts.urls) == 1 and NEW_HOST in fake_edge_tts.urls[0], \
        "第二次起不再白撞一次已知不通的端点"


def test_it_switches_back_if_the_other_endpoint_is_the_one_that_gets_rejected_later(fake_edge_tts, tmp_path):
    _speak(tmp_path, "first.mp3")
    fake_edge_tts.works = {"speech.platform.bing.com"}        # 服务端又变了：新端点不通、旧端点恢复
    fake_edge_tts.urls.clear()

    _out, error = _speak(tmp_path, "second.mp3")

    assert error == "" and [NEW_HOST in url for url in fake_edge_tts.urls] == [True, False]


def test_a_working_default_endpoint_is_left_alone(fake_edge_tts, tmp_path):
    """上游发了修复版之后默认端点就是通的：一次成功，什么都不换。"""
    fake_edge_tts.works = {"speech.platform.bing.com"}

    _out, error = _speak(tmp_path)

    assert error == "" and fake_edge_tts.urls == [LEGACY]
    assert fake_edge_tts.module.WSS_URL == LEGACY


def test_when_both_endpoints_refuse_the_failure_is_reported_and_no_empty_file_is_left(fake_edge_tts, tmp_path):
    fake_edge_tts.works = set()

    out, error = _speak(tmp_path)

    assert "合成失败" in error and "403" in error
    assert not out.exists(), "半截文件留在缓存目录会被下次当成已有缓存"
    assert len(fake_edge_tts.urls) <= 2 * 2 * svc_mod.EDGE_RETRY_TIMES, "两个端点 × 两个候选音色 × 重试次数，不会无限试"


@pytest.mark.parametrize("failure", [_Rejected(500), TimeoutError("timed out"), ValueError("bad voice")])
def test_other_failures_do_not_trigger_an_endpoint_switch(fake_edge_tts, tmp_path, failure):
    """只有握手被拒（401 / 403）才说明是端点的问题；超时、5xx、参数错换端点没有意义。"""
    fake_edge_tts.error = failure

    _out, error = _speak(tmp_path)

    assert "合成失败" in error
    assert all(url == LEGACY for url in fake_edge_tts.urls)


def test_only_handshake_refusals_count_as_rejected():
    assert endpoint.is_rejected(_Rejected(403)) and endpoint.is_rejected(_Rejected(401))
    for other in (_Rejected(500), _Rejected(503), TimeoutError(), ValueError("x"), Exception("403 somewhere in text")):
        assert not endpoint.is_rejected(other)
