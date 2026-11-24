# -*- coding: utf-8 -*-
"""大肥鱼自己的 AI 功能表：配置全景上「大肥鱼」那一框里的每一块都来自这里的一行。

加一项功能 = 在 ``FEATURES`` 里加一行（外加 ``panorama.feature.<id>`` 两条文字），页面和走线不用动。

``route`` 决定这项功能的主路画到哪：
- ``personal``：走 HTTP 模型服务（使用中的那个服务 + 个人 key）；
- ``work``：过桥到 WSL，由公司账号的 ``claude -p`` 跑；
- ``link``：不调模型——Claude Code 的 hooks，和吃联动事件的会话小鱼 / 最近的对话。

``settings`` 把配置字典读成统一的五项（开关 / 模型 / effort / 时间 / 自定义提示词字数），读法一律走各功能
自己的 ``normalize``，所以图上显示的就是功能实际生效的值，而不是 config.json 里碰巧写了什么。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from .. import memory_distill as md
from .. import personal_vault as pv
from .. import slack_watch
from .. import vault_sync
from .. import work_briefing as wb
from .. import work_notes

ROUTES = ("personal", "work", "link")


def _settings(enabled, model="", effort="", when="", every_minutes=0, prompt_chars=0) -> dict:
    return {"enabled": bool(enabled), "model": str(model or ""), "effort": str(effort or ""), "when": str(when or ""),
            "every_minutes": int(every_minutes or 0), "prompt_chars": int(prompt_chars)}


def _chars(section: dict, *keys: str) -> int:
    return sum(len(str(section.get(key) or "")) for key in keys)


def _section(cfg: dict, key: str) -> dict:
    value = cfg.get(key)
    return value if isinstance(value, dict) else {}


def _chat(cfg):
    chat = _section(cfg, "chat")
    return _settings(chat.get("enabled", True) is not False, prompt_chars=_chars(chat, "default_system_prompt", "about_user"))


def _distill(side):
    def read(cfg):
        s = md.side_settings(md.normalize(cfg.get(md.CONFIG_KEY)), side)
        return _settings(s["enabled"], s["model"], s["effort"], s["daily_at"], prompt_chars=_chars(s, "prompt_zh", "prompt_en"))
    return read


def _personal(cfg):
    s = pv.normalize(cfg.get(pv.CONFIG_KEY))
    return _settings(s["enabled"], s["model"], s["effort"], s["time"])


def _vault_sync(cfg):
    s = vault_sync.normalize(cfg.get(vault_sync.CONFIG_KEY))
    return _settings(s["enabled"], every_minutes=s["interval_minutes"])


def _briefing(cfg):
    s = wb.normalize(cfg.get(wb.CONFIG_KEY))
    return _settings(s["enabled"], s["model"], s["effort"], s["time"], prompt_chars=_chars(s, "prompt_zh", "prompt_en", "priority_rules"))


def _slack(cfg):
    s = slack_watch.normalize(cfg.get(slack_watch.CONFIG_KEY))
    return _settings(s["enabled"], s["model"], s["effort"], every_minutes=s["interval_minutes"], prompt_chars=_chars(s, "prompt"))


def _notes(cfg):
    s = work_notes.normalize(cfg.get(work_notes.CONFIG_KEY))
    return _settings(s["enabled"], s["model"], s["effort"], prompt_chars=_chars(s, "prompt_zh", "prompt_en"))


def _link(key, default):
    """agent_link 里的一个开关：缺键按默认（2026-11-14 起两条 Claude Code 联动默认开，WSL 那条只在 Windows 上）。"""
    def read(cfg):
        value = _section(cfg, "agent_link").get(key, default)
        return _settings(value is not False if default else value is True)
    return read


def _always(_cfg) -> bool:
    return True


def _distill_flag(key):
    return lambda cfg: bool(md.normalize(cfg.get(md.CONFIG_KEY)).get(key))


def _chat_uses_github(cfg) -> bool:
    chat = _section(cfg, "chat")
    return bool(chat.get("knowledge_base_enabled") or chat.get("github_connector"))


@dataclass(frozen=True)
class Feature:
    id: str
    route: str
    icon: str
    config_key: str                       # 详情里显示的「config.json → 这个键」
    settings: Callable[[dict], dict]
    page: str = ""                        # 在哪改：``panorama.page.<page>``
    writes: tuple = ()                    # (目标节点 id, 连线种类, 生效条件 cfg→bool)
    note: str = ""                        # 额外一行说明：``panorama.note.<note>``
    follows_provider: bool = False        # 没有自己的模型，跟随使用中的模型服务
    settings_group: str = ""              # 设置表里的哪一组；空 = 按 config_key 找（一个键分了几组的才要写）
    jobs: tuple = ()                      # 它在运行记录里的任务名：有了才有磁贴上的历史条和「上次运行」
    late: str = ""                        # 该跑没跑怎么算（LATE_RULES）；空 = 不判断（Slack 关注只在人在的时候跑）
    report: str = ""                      # 它在浏览器里那张页（PanoramaService 登记的报告名）：有了磁贴正面就有「查看」；
                                          # activity = 时间轴，在右栏里看


#: ``Feature.late``：``interval`` = 超过两个周期没跑（周期是那项功能的「每 N 分钟」）；``daily`` = 每天一次的，超过四天没跑
#: （工作日才跑的简报，周五到周一隔三天是正常的）
LATE_RULES = ("interval", "daily")


FEATURES: tuple[Feature, ...] = (
    # agent_link 一个配置键分四组（settings_table）：两块联动磁贴各开自己那组，会话小鱼和最近的对话各自一块磁贴
    Feature("link_win", "link", "link", "agent_link.claude", _link("claude", True), settings_group="link_win",
            writes=(("set_win", "config", _always),), note="link_win"),
    Feature("session_fish", "link", "fish", "agent_link.session_*", _link("session_pets", True), settings_group="session_fish",
            note="session_fish"),
    Feature("session_history", "link", "stack", "agent_link.session_history*", _link("session_history", True),
            settings_group="session_history", note="session_history"),
    # 会话提示音：开始干活 / 等批准 / 停下来 / 出错各一声。不调模型，吃的是联动事件，所以和会话小鱼一样走 link 这条路
    Feature("link_sounds", "link", "bell", "agent_link.sound_*", _link("sound_enabled", False), settings_group="link_sounds",
            note="link_sounds"),
    Feature("chat", "personal", "chat", "chat", _chat, page="ai_chat", follows_provider=True,
            writes=(("gh_personal", "github", _chat_uses_github),)),
    # 会话记忆蒸馏的设置也搬到了配置全景；一个配置键分两组，所以两块磁贴各自写明是哪一组
    Feature("distill_personal", "personal", "funnel", "memory_distill", _distill(md.SIDE_PERSONAL), settings_group="distill_personal",
            writes=(("md_win", "memory", _always), ("mem_win", "memory", _always),
                    ("vault_personal", "memory", _distill_flag("mirror_to_vault")))),
    Feature("assistant", "personal", "user", "personal", _personal, note="assistant",
            writes=(("vault_personal", "memory", _always),), jobs=("personal_briefing",), late="daily",
            report="personal_briefing"),
    # 知识库定时同步：不调模型，肥鱼自己的 git 把个人知识库的克隆和远端对齐。磁贴上的节奏、上次 / 下次、运行历史条
    # 由 sources.vault_schedule 补上（它们来自运行记录，不是配置）。
    Feature("vault_sync", "link", "repo", "vault_sync", _vault_sync, note="vault_sync",
            writes=(("vault_personal", "github", _always),), jobs=(vault_sync.JOB, vault_sync.CHECK_JOB), late="interval",
            report="activity"),
    Feature("link_wsl", "link", "link", "agent_link.claude_wsl", _link("claude_wsl", sys.platform == "win32"),
            settings_group="link_wsl", writes=(("set_wsl", "config", _always),), note="link_wsl"),
    # 设置已经搬到配置全景（settings_table 里登记了这个键）：磁贴上是「设置」按钮，不再指向设置窗口的哪一页
    Feature("briefing", "work", "news", "work_briefing", _briefing, jobs=("work_briefing",), late="daily", report="work_briefing"),
    Feature("slack", "work", "hash", "slack_watch", _slack, jobs=("slack_watch",), report="slack_watch"),
    Feature("notes", "work", "note", "work_notes", _notes,
            writes=(("vault_work", "memory", _always),), report="work_notes"),
    Feature("distill_work", "work", "funnel", "memory_distill.work_*", _distill(md.SIDE_WORK), settings_group="distill_work",
            writes=(("md_wsl", "memory", _always), ("mem_wsl", "memory", _always),
                    ("vault_work", "memory", _distill_flag("work_mirror_to_vault")))),
)


def read_all(cfg: dict) -> dict:
    """``{功能 id: 五项设置 + writes（这次生效的 [目标, 连线种类]）}``——来源只吃这个，不直接碰配置。"""
    out = {}
    for feature in FEATURES:
        row = feature.settings(cfg)
        row["writes"] = [[target, line] for target, line, active in feature.writes if active(cfg)]
        out[feature.id] = row
    return out
