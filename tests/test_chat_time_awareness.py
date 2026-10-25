# -*- coding: utf-8 -*-
"""对话时间感知（移植上游 fa6b7423，落点按本仓库改过）：

- 历史用户消息与**本轮**用户消息前面都带「[日期 周X 时:分]」发送时间标记；
- system 末尾附一段说明 + 距上条消息的间隔（10 分钟以内视为连续对话，不写）；
- **当前时间不写进 system**：本仓库的 Claude 通道对 system / 消息前缀开着提示缓存，system 每分钟
  变一次会让整段历史每轮都重新写缓存；现在的时间由本轮用户消息上的标记带过去，system 只在
  出现新的间隔时才变。
- 文案跟界面语言走（中 / 英）。

时间来自已落盘的 ChatMessage.created_at（旧会话文件本来就有该字段），只在发给模型时附加，不改写会话文件。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from pet import i18n
from pet.chat.models import ChatMessage, ChatSettings
from pet.chat.prompt import PromptBuilder, format_elapsed, format_time
from pet.chat.session_store import SessionStore

TZ8 = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 2, 30, tzinfo=TZ8)


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _local(dt):
    """测试按本机时区格式化期望值（被测代码统一转本地时区）。"""
    local = dt.astimezone()
    return f"{local:%Y-%m-%d} 周{'一二三四五六日'[local.weekday()]} {local:%H:%M}"


def _settings():
    return ChatSettings(default_system_prompt="你是桌宠")


def test_history_and_current_messages_are_stamped_and_system_knows_the_gap():
    sent = datetime(2026, 9, 12, 11, 13, tzinfo=timezone.utc)
    replied = sent + timedelta(seconds=20)
    history = [
        ChatMessage("user", "早上好", sent.isoformat()),
        ChatMessage("assistant", "早呀", replied.isoformat()),
    ]
    messages = PromptBuilder().build_messages(_settings(), "cat", history, "我回来啦", now=NOW)

    system = messages[0]["content"]
    assert system.startswith("你是桌宠\n\n【时间信息】")
    gap = format_elapsed((NOW - replied).total_seconds())
    assert f"距离上一条消息（{_local(replied)}）已经过去约 {gap}" in system
    assert gap.startswith("29 天")
    assert "当前时间" not in system, "现在的时间不进 system（提示缓存），由本轮消息的标记带"
    # 用户历史消息带时间标记；助手消息原样（防止模型模仿标记）；本轮输入带现在的时间
    assert messages[1] == {"role": "user", "content": f"[{_local(sent)}] 早上好"}
    assert messages[2] == {"role": "assistant", "content": "早呀"}
    assert messages[3] == {"role": "user", "content": f"[{_local(NOW)}] 我回来啦"}


def test_continuous_conversation_keeps_the_system_prompt_stable():
    """10 分钟以内没有间隔句：连续对话里 system 逐字不变，前缀缓存才命中。"""
    history = [ChatMessage("user", "hi", (NOW - timedelta(minutes=3)).isoformat())]
    first = PromptBuilder().build_messages(_settings(), "cat", history, "again", now=NOW)[0]["content"]
    later = PromptBuilder().build_messages(_settings(), "cat", history, "again", now=NOW + timedelta(minutes=5))[0]["content"]
    assert "【时间信息】" in first and "已经过去" not in first
    assert first == later


def test_about_user_stays_between_persona_and_time_note():
    settings = ChatSettings(default_system_prompt="你是桌宠", about_user="我叫小明")
    system = PromptBuilder().build_messages(settings, "cat", [], "hi", now=NOW)[0]["content"]
    assert system.startswith("你是桌宠\n\n我叫小明\n\n【时间信息】")


def test_new_session_and_unparseable_timestamps_degrade_gracefully():
    messages = PromptBuilder().build_messages(_settings(), "cat", [], "hi", now=NOW)
    assert "【时间信息】" in messages[0]["content"] and "已经过去" not in messages[0]["content"]
    assert messages[-1]["content"] == f"[{_local(NOW)}] hi"

    broken = [ChatMessage("user", "旧消息", "not-a-date")]
    messages = PromptBuilder().build_messages(_settings(), "cat", broken, "hi", now=NOW)
    assert messages[1] == {"role": "user", "content": "旧消息"}


def test_format_elapsed():
    assert format_elapsed(5 * 60) == "5 分钟"
    assert format_elapsed(3 * 3600) == "3 小时"
    assert format_elapsed(3 * 3600 + 15 * 60) == "3 小时 15 分钟"
    assert format_elapsed(2 * 86400 + 3600) == "2 天 1 小时"


def test_english_interface_stamps_and_notes_in_english():
    i18n.set_language("en")
    sent = NOW - timedelta(days=2)
    history = [ChatMessage("user", "hello", sent.isoformat())]
    messages = PromptBuilder().build_messages(ChatSettings(default_system_prompt="You are a pet"), "cat", history,
                                              "back", now=NOW)
    local_now = NOW.astimezone()
    assert format_time(local_now) == f"{local_now:%Y-%m-%d} {'Mon Tue Wed Thu Fri Sat Sun'.split()[local_now.weekday()]} {local_now:%H:%M}"
    assert messages[0]["content"].startswith("You are a pet\n\n[Time]")
    assert "2 days" in messages[0]["content"] and "since the last message" in messages[0]["content"]
    assert "【时间信息】" not in messages[0]["content"]
    assert messages[-1]["content"] == f"[{format_time(local_now)}] back"
    assert format_elapsed(3 * 3600 + 15 * 60) == "3 hours 15 minutes"


def test_existing_session_file_gets_timestamps_without_being_rewritten(tmp_path):
    """升级前写下的会话文件（与用户磁盘上格式一致）直接可用，且构建消息不改写文件。"""
    path = tmp_path / "sessions" / "cat" / "abc.json"
    path.parent.mkdir(parents=True)
    raw = {
        "session_id": "abc", "character_id": "cat", "provider_id": "p", "system_prompt": "s",
        "created_at": "2026-09-12T08:31:40.200080+00:00", "updated_at": "2026-09-12T08:32:00+00:00",
        "title": "", "pinned": False,
        "messages": [
            {"role": "user", "content": "旧问题", "created_at": "2026-09-12T08:31:40.200080+00:00", "message_id": "m1"},
            {"role": "assistant", "content": "旧回答", "created_at": "2026-09-12T08:31:50.000000+00:00", "message_id": "m2"},
        ],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()

    session = SessionStore(tmp_path).load("abc")
    assert session is not None
    messages = PromptBuilder().build_messages(_settings(), "cat", session.messages, "新问题", now=NOW)
    stamp = _local(datetime(2026, 9, 12, 8, 31, 40, tzinfo=timezone.utc))
    assert messages[1]["content"] == f"[{stamp}] 旧问题"
    assert "已经过去约 29 天" in messages[0]["content"]
    assert path.read_bytes() == before
    assert session.messages[0].content == "旧问题"


def test_new_messages_record_timestamps():
    msg = ChatMessage("user", "hi")
    parsed = datetime.fromisoformat(msg.created_at)
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60
