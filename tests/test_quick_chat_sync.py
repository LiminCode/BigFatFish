# -*- coding: utf-8 -*-
"""快速对话气泡 ↔ 完整聊天窗：点「去聊天窗」后对话要在聊天窗里，气泡放大到两倍。

实机：从灵动岛点「聊天」弹出气泡，聊了几句再点「去聊天窗」，聊天窗打开了但里面
没有刚才的对话——聊天窗是隐藏后复用的，重新打开时不重读存档，手里还是旧快照。

纪律：offscreen；不发真实请求（``ChatService`` 用替身）；同步直调，不 sleep。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet.chat.models import ChatMessage
from pet.chat.session_store import SessionStore
from pet.config import Config
from pet.quick_chat import QUICK_CHAT_BASE_SCALE, QuickChatBubble, quick_chat_scale

app = QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path):
    return Config(tmp_path)


@pytest.fixture
def widgets():
    made = []
    yield made
    for widget in made:
        widget.close()
        widget.deleteLater()


def _window(kind, config, widgets):
    if kind == "classic":
        from pet.chat.legacy_widgets import ChatWindow
    else:
        from pet.chat.widgets import ChatWindow
    window = ChatWindow(config, "shenshen")
    widgets.append(window)
    return window


def _bubble(config, widgets):
    bubble = QuickChatBubble(config)
    widgets.append(bubble)
    return bubble


def _texts(window) -> list[str]:
    return [m.content for m in window.session.messages]


def _shown(window) -> int:
    return len(window._bubbles)


def _talk_elsewhere(config, session, *pairs):
    """别的入口（气泡）往同一个会话里追加问答——走的是它自己那份 SessionStore。"""
    store = SessionStore(config.dir, getattr(config, "instance_id", ""))
    for question, answer in pairs:
        session, _ = store.append_messages(
            session, [ChatMessage("user", question), ChatMessage("assistant", answer)])
    return session


# ---------------------------------------------------------------- 聊天窗重读存档
@pytest.mark.parametrize("kind", ["classic", "modern"])
def test_chat_window_picks_up_what_was_said_in_the_bubble(kind, config, widgets):
    window = _window(kind, config, widgets)
    assert _shown(window) == 0
    _talk_elsewhere(config, window.session, ("在吗", "在的"))
    assert _shown(window) == 0, "前提：聊天窗手里是旧快照"

    window.sync_from_store()

    assert _texts(window) == ["在吗", "在的"]
    assert _shown(window) == 2


@pytest.mark.parametrize("kind", ["classic", "modern"])
def test_chat_window_switches_to_the_session_the_bubble_is_talking_in(kind, config, widgets):
    window = _window(kind, config, widgets)
    first = window.session
    _talk_elsewhere(config, first, ("旧话题", "嗯"))
    window.sync_from_store()
    window.new_session()                       # 用户在聊天窗里另开了一个会话
    assert window.session.session_id != first.session_id

    window.sync_from_store(first.session_id)   # 气泡里点「去聊天窗」

    assert window.session.session_id == first.session_id
    assert _texts(window) == ["旧话题", "嗯"]
    assert _shown(window) == 2


@pytest.mark.parametrize("kind", ["classic", "modern"])
def test_sync_is_a_no_op_when_nothing_changed_or_while_generating(kind, config, widgets):
    window = _window(kind, config, widgets)
    _talk_elsewhere(config, window.session, ("a", "b"))
    window.sync_from_store()
    rendered = list(window._bubbles)

    window.sync_from_store()
    assert window._bubbles == rendered, "存档没变：不重建消息气泡"

    _talk_elsewhere(config, window.session, ("c", "d"))
    window.service = SimpleNamespace(busy=True, stop=lambda: None)
    window.sync_from_store()
    assert window._bubbles == rendered, "自己正在生成：流式输出还挂在现有气泡上，不动"


# ---------------------------------------------------------------- 气泡 → 聊天窗
def test_go_to_chat_window_opens_it_and_points_it_at_this_session(config, widgets):
    bubble = _bubble(config, widgets)
    calls = []
    bubble.open_chat_callback = lambda: calls.append("open")
    bubble.chat_sync_callback = lambda sid, focus=False: calls.append((sid, focus))

    bubble.open_chat_btn.click()

    assert calls == ["open", (bubble.session.session_id, True)]


def test_saved_reply_is_announced_so_an_open_chat_window_can_reload(config, widgets):
    bubble = _bubble(config, widgets)
    announced = []
    bubble.chat_sync_callback = lambda sid, focus=False: announced.append((sid, focus))
    bubble._active_request_id = "r1"

    bubble._finished("r1", "回答")

    assert announced == [(bubble.session.session_id, False)]
    stored = SessionStore(config.dir, getattr(config, "instance_id", "")).load(
        bubble.session.session_id, bubble.character_id)
    assert [m.content for m in stored.messages] == ["回答"], "通知发出时回答已经落库"


def test_going_to_the_chat_window_mid_answer_does_not_cut_the_answer_off(config, widgets):
    """聊天窗一激活气泡就失焦关闭；回答还在生成时关气泡不能把这一轮掐掉。"""
    bubble = _bubble(config, widgets)
    stopped = []
    service = SimpleNamespace(busy=True, stop=lambda: stopped.append(True))
    bubble.service = service
    bubble.open_chat_callback = lambda: None

    bubble.open_chat_btn.click()
    bubble.close()
    assert stopped == [], "交接中：让回答在后台跑完并落库"

    bubble._active_request_id = "r1"
    bubble._finished("r1", "完整回答")
    bubble.close()
    assert stopped == [True], "这一轮结束后恢复原语义：关气泡 = 停止生成"


def test_closing_the_bubble_normally_still_stops_generation(config, widgets):
    bubble = _bubble(config, widgets)
    stopped = []
    bubble.service = SimpleNamespace(busy=True, stop=lambda: stopped.append(True))
    bubble.close()
    assert stopped == [True]


def test_instance_refreshes_only_the_window_that_should_follow():
    from pet.app import PetInstance

    def window(session_id, visible):
        synced = []
        return SimpleNamespace(
            session=SimpleNamespace(session_id=session_id), synced=synced,
            isVisible=lambda: visible, sync_from_store=lambda sid=None: synced.append(sid))

    current, other = window("b", True), window("a", True)
    hidden = window("a", False)
    inst = SimpleNamespace(legacy_chat_window=current, modern_chat_window=other,
                           chat_window=current)

    PetInstance.sync_chat_windows(inst, "a", focus=True)
    assert current.synced == ["a"], "点了「去聊天窗」：当前聊天窗切到气泡的会话"
    assert other.synced == [None], "另一只窗口正停在这个会话上：原地重读"

    current.synced.clear()
    other.synced.clear()
    PetInstance.sync_chat_windows(inst, "a")
    assert current.synced == [], "后台落库：不把用户正在看的别的会话换掉"
    assert other.synced == [None]

    inst.modern_chat_window = hidden
    PetInstance.sync_chat_windows(inst, "a")
    assert hidden.synced == [], "没开着的窗口不管——它重新打开时自己会重读"


# ---------------------------------------------------------------- 尺寸
def test_bubble_is_twice_its_old_size(config, widgets):
    assert QUICK_CHAT_BASE_SCALE == 2.0 and quick_chat_scale(config) == 2.0
    bubble = _bubble(config, widgets)
    room = app.primaryScreen().availableGeometry().width() - 16   # 不许比屏幕宽
    assert (bubble.minimumWidth(), bubble.maximumWidth()) == (min(640, room), min(920, room))
    assert bubble.output_scroll.maximumHeight() == 440
    assert bubble.close_btn.size().width() == 48
    assert bubble.input.font().pointSizeF() == pytest.approx(app.font().pointSizeF() * 2)
    margins = bubble.layout().contentsMargins()
    assert (margins.left(), margins.top()) == (28, 24)


def test_bubble_follows_the_bubble_text_size_setting(config):
    config.set("bubble_text_scale", 150)
    assert quick_chat_scale(config) == 3.0
    config.set("bubble_text_scale", 50)
    assert quick_chat_scale(config) == 1.0
    config.set("bubble_text_scale", 300)
    assert quick_chat_scale(config) == 4.0, "封顶 4 倍"


def test_island_bubble_is_enlarged_too(config, widgets):
    from pet.island_chat import IslandChatBubble

    bubble = IslandChatBubble(config)
    widgets.append(bubble)
    assert bubble.minimumWidth() == min(640, app.primaryScreen().availableGeometry().width() - 16)
    assert bubble.show_pet_btn.font().pointSizeF() == pytest.approx(app.font().pointSizeF() * 2)
