# -*- coding: utf-8 -*-
"""设置表：每一项能在配置全景页面上改的设置声明一次（决定见 docs/adr/0014-panorama-becomes-the-console.md）。

**只有声明和几个纯函数，不碰 Qt，不读写任何文件。** 谁用它：

- 本机服务按它回答「这一组有哪些设置、各用什么控件、现在是什么值」，页面照着画通用控件——页面里没有任何一项设置的名字；
- 写入链路按它校验页面提交的改动（``check_changes``：哪一项、什么类型、在不在可选值里、功能自己认不认）；
- 测试拿它当守卫：功能多读了一个设置键却没登记，``tests/test_settings_table.py`` 就红。

**搬一组设置到页面上 = 在 ``GROUPS`` 里加一个 ``Group``。** 读和校验不另写：一律走那个功能自己的 ``normalize``，
所以表里的默认值就是 ``normalize({})`` 的结果，页面上看到的就是功能实际生效的值。

一项设置要声明的东西对应 ``docs/settings-and-menu.md`` 里「准入记录」要求的字段：

- ``id``：组内标识，也是它在那一组配置字典里的位置；点号表示下一层（``sources.jira``）；
- ``control``：页面上用哪种控件（``CONTROLS``）。``lines`` 是字符串列表，页面上一行一个（会话记忆蒸馏的公司目录）；
- ``choices``：下拉的可选值。``choice`` 只能选其中之一，``choice_or_text`` 还可以自己填；
- ``commit``：什么时候算存上。不写就按控件定——开关和下拉一动就存（``immediate``），文本框和列表等用户点保存（``on_finish``）；
- ``disclosure``：``primary`` 直接露出，``advanced`` 收在「高级」里；
- ``depends_on``：同组的一个开关；它关着时这一项变灰；
- ``builtin``：只给长文本用——留空时功能实际用的那段内置文字（给页面当底稿显示，也是「恢复内置」的目标）。
  它是个函数，参数是这一组当前生效的值：内置提示词会随别的设置变（勾了哪些来源）；
- ``bounds``：只给数字用——``(下限, 上限)``，抄功能自己 ``normalize`` 夹值用的那一对。页面拿它画输入框的范围，
  写入时超出范围报 ``out_of_range``（不然 ``normalize`` 会悄悄夹到边上，用户以为存的是 3，其实是 5）；
- ``unit``：数字后面的单位（文案键），比如「分钟」；
- ``labels``：只给下拉用——``((可选值, 文案键), ...)``，选项上显示的文字。没写的选项照原样显示值；写了的显示「文字 · 值」，
  值是空串时只显示文字（个人助理的「跟 AI 对话一致」就是存空串）；
- ``action``：这一项旁边放一个动作按钮（``ACTIONS`` 里的一个名字，页面 ``POST /api/actions/<名字>``，带上组、项和此刻的值）。
  现在只有 ``preview_sound``：试听一项音效设置选中的声音。动作不是改设置，处理器在 ``pet/panorama/actions.py``。

文字不在这里：标题和说明在字表里，键由 ``title_key`` / ``hint_key`` 给出（默认 ``settings.<组>.<id>`` 和它加 ``_hint``；
从 Qt 设置窗口搬过来的那些直接沿用原来的键，不抄第二份）。
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from . import capture_organize as co
from . import claude_hooks
from . import memory_distill as md
from .click_sound import BUILTIN_AGENT_SOUNDS      # 导入时不碰 Qt（QtMultimedia 在它里面是惰性的）
from . import session_card_themes as sct
from . import personal_vault as pv
from . import slack_watch as sw
from . import vault_sync as vs
from . import work_briefing as wb
from . import work_notes as wn

ZONES = ("personal", "work")                # 这一组设置管的是哪个账号那一侧的功能
CONTROLS = ("toggle", "choice", "choice_or_text", "number", "text", "long_text", "lines", "records")
COMMITS = ("immediate", "on_finish", "confirm")
DISCLOSURES = ("primary", "advanced")
ACTIONS = ("preview_sound",)                # 一项设置旁边能放的动作按钮
_TEXT_CONTROLS = ("text", "long_text")


@dataclass(frozen=True)
class Setting:
    id: str
    control: str
    choices: tuple = ()
    commit: str = ""                        # 空 = 按控件定，见 commit_policy
    disclosure: str = "primary"
    depends_on: str = ""
    builtin: Callable[[dict], str] | None = None
    text: str = ""                          # 标题的文案键；空 = settings.<组>.<id>
    hint: str = ""                          # 说明的文案键；空 = 标题的键加 _hint
    bounds: tuple = ()                      # 数字的 (下限, 上限)；空 = 不限
    unit: str = ""                          # 数字的单位（文案键）
    labels: tuple = ()                      # 下拉选项上显示的文字：((值, 文案键), ...)
    fields: tuple = ()                      # records 的列：((字段 id, 文案键), ...)；值是这些字段组成的字典的列表
    action: str = ""                        # 旁边的动作按钮（ACTIONS 之一）；空 = 没有

    @property
    def commit_policy(self) -> str:
        return self.commit or ("on_finish" if self.control in (*_TEXT_CONTROLS, "lines", "records") else "immediate")


@dataclass(frozen=True)
class Group:
    id: str
    domain: str                             # 归哪个能力域（和 Qt 设置窗口的域同名）
    config_key: str                         # 这一组存在 config.json 的哪个顶层键下
    zone: str
    normalize: Callable[[Any], dict]        # 那个功能自己的归一化：读、默认值、校验都靠它
    settings: tuple[Setting, ...]
    title_key: str = ""                     # 这一组叫什么
    available: Callable[[], bool] | None = None     # 这台机器上用不用得了；None = 总能用
    unavailable_text: str = ""              # 用不了时的说明（文案键）
    not_editable: dict = field(default_factory=dict)    # normalize 给出、但有意不放到页面上改的键 → 为什么


def title_key(group: Group, setting: Setting) -> str:
    return setting.text or f"settings.{group.id}.{setting.id}"


def hint_key(group: Group, setting: Setting) -> str:
    return setting.hint or title_key(group, setting) + "_hint"


# ───────────────────────── 在嵌套字典里按点号取放 ─────────────────────────

def flatten(value: dict, prefix: str = "") -> dict:
    """``{"a": 1, "b": {"c": 2}}`` → ``{"a": 1, "b.c": 2}``。只展开字典，列表当作一个值。"""
    out: dict = {}
    for key, item in value.items():
        path = f"{prefix}{key}"
        if isinstance(item, dict):
            out.update(flatten(item, path + "."))
        else:
            out[path] = item
    return out


def get_path(value: dict, path: str, default: Any = None) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set_path(value: dict, path: str, item: Any) -> dict:
    """返回一份改过的副本；原来那份不动。"""
    out = copy.deepcopy(value) if isinstance(value, dict) else {}
    current = out
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = item
    return out


# ───────────────────────── 读一组设置 ─────────────────────────

def values(group: Group, raw: Any) -> dict:
    """这一组每一项现在生效的值（按表里声明的顺序）。``raw`` 是配置里那个键下存着的东西，可以是任何样子。"""
    effective = group.normalize(raw)
    return {setting.id: get_path(effective, setting.id) for setting in group.settings}


def defaults(group: Group) -> dict:
    """什么都没配时的值：就是功能对空配置给出的结果。"""
    return values(group, {})


def version(group: Group, raw: Any) -> str:
    """这一组当前值的指纹。页面读的时候带上它，写的时候交回来：对不上就是页面看到的值已经旧了。

    按**生效值**算，不按配置文件里的原样：配置里多一个没用的键、或者少写一个等于默认的键，版本不变。
    """
    canonical = json.dumps(group.normalize(raw), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def is_available(group: Group) -> bool:
    """这一组在这台机器上用不用得了。条件自己出错按用不了算，不往外抛。"""
    if group.available is None:
        return True
    try:
        return bool(group.available())
    except Exception:  # noqa: BLE001 - 探测条件失败不该让读设置的接口报错
        return False


# ───────────────────────── 校验一次改动 ─────────────────────────

def _type_error(setting: Setting, value: Any) -> str:
    """这个值装不装得进这种控件；装不进返回错误代码。"""
    if setting.control == "toggle":
        return "" if isinstance(value, bool) else "type"
    if setting.control == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "type"
        return "out_of_range" if setting.bounds and not setting.bounds[0] <= value <= setting.bounds[1] else ""
    if setting.control == "choice":
        return "" if value in setting.choices else "not_a_choice"
    if setting.control == "lines":
        return "" if isinstance(value, list) and all(isinstance(item, str) for item in value) else "type"
    if setting.control == "records":
        names = [name for name, _key in setting.fields]
        return "" if isinstance(value, list) and all(
            isinstance(item, dict) and all(isinstance(item.get(name, ""), str) for name in names) for item in value) else "type"
    return "" if isinstance(value, str) else "type"


def check_changes(group: Group, raw: Any, changes: Any) -> tuple[dict | None, list[dict]]:
    """页面提交的改动 ``{项: 新值}`` 能不能存。能：返回（整组的新值，``[]``）；不能：返回（``None``，错误清单）。

    错误清单一项一条 ``{"id", "code"}``：``unknown`` 表里没有这一项；``type`` 类型不对；``not_a_choice`` 不在可选值里；
    ``out_of_range`` 数字超出声明的上下限；``rejected`` 功能自己的校验不认。只要有一条错误，整次改动都不存。

    **``rejected`` 是这里最要紧的一条。** 功能的 ``normalize`` 遇到不合法的值不报错，而是悄悄换成默认值（时间写错 → 09:00，
    模型名里有空格 → sonnet）。读配置时这样是对的；写的时候不行——用户以为存上了，其实存的是默认值。所以把改动合进去、
    过一遍 ``normalize``，再逐项比：存下去的和提交的不一样，就是被改掉了，拒。文本只容许去掉首尾空白这一种差别。
    连「9」被规范成「09:00」也算不一样：写接口要的是规范的写法，由页面去给。
    """
    if not isinstance(changes, dict) or not changes:
        return None, [{"id": "", "code": "empty"}]
    by_id = {setting.id: setting for setting in group.settings}
    errors: list[dict] = []
    merged = group.normalize(raw)
    passed: list[str] = []
    for key, value in changes.items():
        setting = by_id.get(key) if isinstance(key, str) else None
        code = "unknown" if setting is None else _type_error(setting, value)
        if code:
            errors.append({"id": str(key), "code": code})
            continue
        merged = set_path(merged, key, value)
        passed.append(key)
    final = group.normalize(merged)
    for key in passed:
        wanted = _as_stored(by_id[key], changes[key])
        if get_path(final, key) != wanted:
            errors.append({"id": key, "code": "rejected"})
    return (None, errors) if errors else (final, [])


def _as_stored(setting: Setting, value: Any) -> Any:
    """提交的值存下去应该是什么样：文本去掉首尾空白；列表每行去掉首尾空白、空行不要。其余原样。"""
    if setting.control in _TEXT_CONTROLS:
        return value.strip()
    if setting.control == "lines":
        return [item.strip() for item in value if item.strip()]
    if setting.control == "records":
        # 每个字段去掉首尾空白；全空的行不要。别的差别（大小写、缺字段补默认）都是功能自己的事，被它改了就是 rejected
        rows = [{name: str(item.get(name, "")).strip() for name, _key in setting.fields} for item in value]
        return [row for row in rows if any(row.values())]
    return value


def group(group_id: str) -> Group:
    for item in GROUPS:
        if item.id == group_id:
            return item
    raise KeyError(group_id)


def group_for_config_key(config_key: str) -> str:
    """配置里这个顶层键下的设置已经搬到页面上了吗：搬了返回那一组的 id，没搬是空串。
    配置全景的功能磁贴靠它决定出「设置」按钮，还是写「去设置窗口哪一页」。"""
    return next((item.id for item in GROUPS if item.config_key == config_key), "")


# ───────────────────────── 自检 ─────────────────────────

def _fits(control: str, default: Any) -> bool:
    if control == "toggle":
        return isinstance(default, bool)
    if control == "number":
        return isinstance(default, (int, float)) and not isinstance(default, bool)
    if control in ("text", "long_text", "choice_or_text"):
        return isinstance(default, str)
    if control in ("lines", "records"):
        return isinstance(default, list)
    return True


def validate(groups: tuple[Group, ...] | None = None) -> None:
    """表里有不自洽的地方就抛 ``ValueError``（导入时不跑，测试里跑）。"""
    groups = GROUPS if groups is None else groups
    seen_groups = set()
    for item in groups:
        def bad(message: str, item=item) -> ValueError:
            return ValueError(f"settings group {item.id!r}: {message}")

        if item.id in seen_groups:
            raise bad("duplicate group id")
        seen_groups.add(item.id)
        if item.zone not in ZONES or not item.config_key or not item.settings:
            raise bad("zone, config_key and settings are required")
        produced = flatten(item.normalize({}))
        by_id: dict[str, Setting] = {}
        for setting in item.settings:
            if setting.id in by_id:
                raise bad(f"{setting.id} is declared twice")
            by_id[setting.id] = setting
            if setting.control not in CONTROLS or setting.disclosure not in DISCLOSURES or setting.commit_policy not in COMMITS:
                raise bad(f"{setting.id}: unknown control, disclosure or commit policy")
            if setting.control in ("choice", "choice_or_text") and not setting.choices:
                raise bad(f"{setting.id}: a choice needs choices")
            if (setting.control == "records") != bool(setting.fields):
                raise bad(f"{setting.id}: records need fields and only records have them")
            if setting.action and setting.action not in ACTIONS:
                raise bad(f"{setting.id}: unknown action {setting.action!r}")
            if setting.id not in produced:
                raise bad(f"{setting.id}: the feature's normalize() does not produce this key")
            if not _fits(setting.control, produced[setting.id]):
                raise bad(f"{setting.id}: a {setting.control} cannot hold the default {produced[setting.id]!r}")
            if (setting.bounds or setting.unit) and setting.control != "number":
                raise bad(f"{setting.id}: only a number has bounds or a unit")
            if setting.labels and (setting.control not in ("choice", "choice_or_text")
                                   or any(value not in setting.choices for value, _key in setting.labels)):
                raise bad(f"{setting.id}: labels belong to a choice and must name its choices")
            if setting.bounds and (len(setting.bounds) != 2 or not setting.bounds[0] <= produced[setting.id] <= setting.bounds[1]):
                raise bad(f"{setting.id}: bounds must be (low, high) around the default {produced[setting.id]!r}")
        for setting in item.settings:
            if setting.depends_on and (setting.depends_on not in by_id or by_id[setting.depends_on].control != "toggle"):
                raise bad(f"{setting.id}: depends_on must name a toggle in the same group")


# ───────────────────────── 表 ─────────────────────────

_MODEL_CHOICES = ("sonnet", "haiku", "opus")
_FOLLOW_CHAT = "personal.settings.same_as_chat"

#: 会话记忆蒸馏两组共用一个配置键：一组的键在另一组里写明去哪改
_DISTILL_WORK = ("work_distill", "work_daily_at", "work_model", "work_effort", "work_mirror_to_vault", "work_prompt_zh",
                 "work_prompt_en")
_DISTILL_PERSONAL = ("enabled", "scan_wsl", "keep_days", "work_roots", "daily_at", "model", "effort", "mirror_to_vault",
                     "prompt_zh", "prompt_en")


def _briefing_prompt(language: str) -> Setting:
    return Setting(f"prompt_{language}", "long_text", disclosure="advanced",
                   builtin=lambda effective: wb.default_prompt_template(language, effective.get("sources")),
                   text=f"settings.work_briefing.prompt_{language}", hint="briefing.settings.prompt_hint")


def _distill_prompt(prefix: str, language: str) -> Setting:
    hint = "distill.settings.work_prompt_hint" if prefix else "distill.settings.prompt_hint"
    side = "distill_work" if prefix else "distill_personal"
    return Setting(f"{prefix}prompt_{language}", "long_text", disclosure="advanced",
                   builtin=lambda _effective: md.default_prompt_template(language),
                   text=f"settings.{side}.prompt_{language}", hint=hint)


def _notes_prompt(language: str) -> Setting:
    return Setting(f"prompt_{language}", "long_text", disclosure="advanced",
                   builtin=lambda _effective: wn.default_prompt_template(language),
                   text=f"settings.work_notes.prompt_{language}", hint="notes.settings.prompt_hint")


#: ``agent_link`` 一个配置键分五组，按配置全景的账号带和磁贴分：本机联动 / WSL 联动（公司带）/ 会话小鱼 / 最近的对话 /
#: 会话提示音（2026-11-21 从设置窗口「互动」搬来）。每组的 ``not_editable`` = 其余四组的键 + 五组都不给改的（见 _AGENT_LINK_ELSEWHERE）。
_AGENT_LINK_GROUPS = {
    "link_win": ("claude", "cursor", "opencode", "custom_agents"),
    "link_wsl": ("claude_wsl",),
    "session_fish": ("session_pets", "session_pets_max", "session_fish_keep_days", "crown_models", "session_card_theme",
                     "session_card_text_size"),
    "session_history": ("session_history", "session_history_rows", "session_history_days", "session_history_max"),
    "link_sounds": ("sound_enabled", "sound_start_enabled", "sound_start_path", "sound_attention_enabled", "sound_attention_path",
                    "sound_done_enabled", "sound_done_path", "sound_error_enabled", "sound_error_path", "sound_volume",
                    "sound_cooldown_seconds"),
}
_AGENT_LINK_ELSEWHERE = {
    "dsh": "DSH 联动的菜单项 2026-10-14 下线；从页面打开只会起一个没有桥接插件的监视器，所以不给开（要不要整个删掉另议）",
}

#: 提示音的可选值：内置的几个（``builtin:<id>``，表在 click_sound）；「自定义…」填音频文件的完整路径。
_SOUND_EVENTS = ("start", "attention", "done", "error")
_SOUND_CHOICES = tuple(f"builtin:{sound_id}" for sound_id, _file in BUILTIN_AGENT_SOUNDS)
# 文案键不能带连字符（i18n 的键名规则），所以 agent-start 的文字在 settings.link_sounds.builtin.agent_start
_SOUND_LABELS = tuple((f"builtin:{sound_id}", f"settings.link_sounds.builtin.{sound_id.replace('-', '_')}")
                      for sound_id, _file in BUILTIN_AGENT_SOUNDS)


def _sound_event(event: str, title: str, hint: str) -> tuple[Setting, Setting]:
    """一个时刻的两项：响不响（挂在总开关下）、用哪个声音（挂在这个时刻的开关下，旁边一个「试听」）。"""
    return (Setting(f"sound_{event}_enabled", "toggle", depends_on="sound_enabled", text=title, hint=hint),
            Setting(f"sound_{event}_path", "choice_or_text", choices=_SOUND_CHOICES, labels=_SOUND_LABELS,
                    depends_on=f"sound_{event}_enabled", action="preview_sound",
                    text=f"settings.link_sounds.sound_{event}_path", hint="settings.link_sounds.path_hint"))


#: 会话小鱼上限的硬顶，抄自 ``config.SESSION_PETS_MAX_CAP``（不能导入 ``pet.config``：它经 speech_bubble_text 带进 Qt，
#: 而本模块要在没有 Qt 的进程里能用）。两边对不上时 ``tests/test_settings_table.py`` 会红。
_SESSION_PETS_MAX_CAP = 40


def _agent_link_normalize(raw: Any) -> dict:
    """``config._clean_agent_link_data``：读、默认值、校验都是它。惰性导入，理由见上。"""
    from .config import _clean_agent_link_data

    return _clean_agent_link_data(raw)


def _agent_link_not_editable(own: str) -> dict:
    out = dict(_AGENT_LINK_ELSEWHERE)
    for group_id, keys in _AGENT_LINK_GROUPS.items():
        if group_id != own:
            out.update({key: f"「{group_id}」那一组里改" for key in keys})
    return out


def _agent_link_group(group_id: str, zone: str, settings: tuple, title_key: str, **extra) -> Group:
    assert tuple(s.id for s in settings) == _AGENT_LINK_GROUPS[group_id]
    return Group(group_id, "automation", "agent_link", zone, _agent_link_normalize, settings, title_key=title_key,
                 not_editable=_agent_link_not_editable(group_id), **extra)


GROUPS: tuple[Group, ...] = (
    # 工作简报：到点让 WSL 里公司账号的 Claude Code 只读地汇总几个来源。模型名和 effort 会拼进 shell 命令、
    # 提示词会交给带工具的 AI：这一组的每一项写入都要过 work_briefing.normalize 的白名单。
    Group("work_briefing", "briefing", wb.CONFIG_KEY, "work", wb.normalize, (
        Setting("enabled", "toggle", text="briefing.settings.enabled"),
        # 时间和模型在 Qt 窗口里是「下拉 + 自定义」：功能本身收任何 HH:MM、任何合规的模型名，所以这里是可自填的下拉
        Setting("time", "choice_or_text", choices=wb.TIME_CHOICES, text="briefing.settings.time"),
        Setting("weekdays_only", "toggle", text="briefing.settings.weekdays"),
        Setting("model", "choice_or_text", choices=_MODEL_CHOICES, text="briefing.settings.model"),
        Setting("effort", "choice", choices=wb.EFFORT_CHOICES, text="briefing.settings.effort"),
        *(Setting(f"sources.{source}", "toggle", text=f"briefing.settings.source.{source}") for source in wb.SOURCES),
        # 「当前 Sprint」查哪些工单：一行 JQL 片段，只进提示词；写入过 normalize_sprint_scope（取第一行、最多 300 字）
        Setting("sprint_scope", "text", text="briefing.settings.sprint_scope", hint="briefing.settings.sprint_scope_hint"),
        _briefing_prompt("zh"),
        _briefing_prompt("en"),
        Setting("priority_rules", "long_text", text="briefing.settings.priority_rules"),
        # 额外放行的工具：连接器换名 / 多一条时用户自己补一行；写入过 normalize_tools（只认 mcp__ 开头的名字或 * 结尾的前缀）
        Setting("extra_allowed_tools", "lines", disclosure="advanced", text="briefing.settings.extra_tools",
                hint="briefing.settings.extra_tools_hint"),
    ), title_key="briefing.settings.section", available=lambda: bool(claude_hooks.wsl_exe()),
        unavailable_text="briefing.settings.no_wsl"),
    # Slack 关注：电脑在用时每隔一阵让 WSL 里公司账号的 Claude Code 经 Slack 连接器只读地看一眼。模型名、effort 同样拼进
    # shell 命令，过 slack_watch.normalize（它借用工作简报的白名单）。两个分钟数由它夹在范围里，范围照抄在这里给页面看。
    Group("slack_watch", "briefing", sw.CONFIG_KEY, "work", sw.normalize, (
        Setting("enabled", "toggle", text="settings.slack.check_automatically_while_i_m", hint="settings.slack.enabled_hint"),
        Setting("interval_minutes", "number", bounds=sw.INTERVAL_RANGE, unit="settings.unit.minutes",
                text="settings.slack.check_interval", hint="settings.slack.interval_hint"),
        Setting("idle_minutes", "number", bounds=sw.IDLE_RANGE, unit="settings.unit.minutes",
                text="settings.slack.away_after", hint="settings.slack.idle_hint"),
        Setting("model", "choice_or_text", choices=_MODEL_CHOICES, text="settings.slack.model"),
        Setting("effort", "choice", choices=wb.EFFORT_CHOICES, text="settings.slack.effort"),
        Setting("prompt", "long_text", disclosure="advanced", builtin=lambda _effective: sw.default_prompt_template(),
                text="settings.slack.prompt"),
    ), title_key="settings.dlg.slack_watch", available=lambda: bool(claude_hooks.wsl_exe()),
        unavailable_text="settings.slack.no_wsl_hint"),
    # 工作笔记：每记一条，让 WSL 里公司账号的 Claude Code 只读地读链接、写摘要；笔记存进仓库副本目录。模型名、effort
    # 拼进 shell 命令，过 work_notes.normalize（同样借工作简报的白名单）。目录清空会被它退回默认目录，所以清空算 rejected。
    Group("work_notes", "briefing", wn.CONFIG_KEY, "work", wn.normalize, (
        Setting("enabled", "toggle", text="notes.settings.enabled"),
        Setting("repo_dir", "text", text="notes.settings.repo_dir"),
        Setting("model", "choice_or_text", choices=_MODEL_CHOICES, text="notes.settings.model"),
        Setting("effort", "choice", choices=wb.EFFORT_CHOICES, text="notes.settings.effort"),
        _notes_prompt("zh"),
        _notes_prompt("en"),
    ), title_key="notes.settings.section", available=lambda: bool(claude_hooks.wsl_exe()),
        unavailable_text="notes.settings.no_wsl"),
    # 个人助理：肥鱼自己的 Claude（个人 key）读 AI-Base 克隆写简报。不靠 WSL；没有 Windows 的 git 时简报照样能用，所以总是可用。
    # 模型和 effort 存空串 = 跟 AI 对话一致，下拉上用 labels 写出来。
    Group("personal", "briefing", pv.CONFIG_KEY, "personal", pv.normalize, (
        Setting("enabled", "toggle", text="personal.settings.enabled"),
        Setting("repo_dir", "text", text="personal.settings.repo_dir"),
        Setting("time", "choice_or_text", choices=pv.TIME_CHOICES, text="personal.settings.time"),
        Setting("model", "choice_or_text", choices=("", *pv.MODEL_CHOICES), labels=(("", _FOLLOW_CHAT),),
                text="personal.settings.model"),
        Setting("effort", "choice", choices=("", *pv.EFFORT_LEVELS),
                labels=(("", _FOLLOW_CHAT), *((level, f"personal.settings.effort.{level}") for level in pv.EFFORT_LEVELS)),
                text="personal.settings.effort"),
    ), title_key="personal.settings.section"),
    # 随手记的整理：个人 key 照知识库里那份规矩把 0-Inbox 整理成 9-Learning/Notes 下的笔记（ADR 0021）。生来就在页面上。
    # 开关只管自动的几种（记下后、启动后、每小时），「现在整理」不看它。仓库在哪是个人助理那一组的「仓库副本目录」。
    Group("capture", "briefing", co.CONFIG_KEY, "personal", co.normalize, (
        Setting("enabled", "toggle"),
        Setting("delay_minutes", "number", bounds=co.DELAY_RANGE, unit="settings.unit.minutes", depends_on="enabled"),
        Setting("max_per_run", "number", bounds=co.BATCH_RANGE),
        Setting("model", "choice_or_text", choices=("", *pv.MODEL_CHOICES), labels=(("", _FOLLOW_CHAT),)),
        Setting("effort", "choice", choices=("", *pv.EFFORT_LEVELS),
                labels=(("", _FOLLOW_CHAT), *((level, f"personal.settings.effort.{level}") for level in pv.EFFORT_LEVELS))),
        Setting("prompt", "long_text", disclosure="advanced", builtin=lambda _effective: co.default_prompt_template()),
        # 复习：每天定点提醒（时刻挂在它的开关下）、一轮几条（复习页也用）、白天随机冒一条
        Setting("review_enabled", "toggle"),
        Setting("review_time", "choice_or_text", choices=co.REVIEW_TIME_CHOICES, depends_on="review_enabled"),
        Setting("review_batch", "number", bounds=co.REVIEW_BATCH_RANGE),
        Setting("review_random", "toggle"),
    ), title_key="settings.capture.section"),
    # 知识库定时同步：每隔一阵、停笔后，把个人知识库的克隆和远端对齐。不调模型、不靠 WSL。默认关：它会替用户提交和推送。
    # 克隆在哪是个人助理那一组的「仓库副本目录」，这里不重复放。两个分钟数由 vault_sync.normalize 夹在范围里。
    Group("vault_sync", "automation", vs.CONFIG_KEY, "personal", vs.normalize, (
        Setting("enabled", "toggle"),
        Setting("mode", "choice", choices=vs.MODES, depends_on="enabled",
                labels=tuple((mode, f"settings.vault_sync.mode.{mode}") for mode in vs.MODES)),
        Setting("interval_minutes", "number", bounds=vs.INTERVAL_RANGE, unit="settings.unit.minutes", depends_on="enabled"),
        Setting("idle_minutes", "number", bounds=vs.IDLE_RANGE, unit="settings.unit.minutes", depends_on="enabled"),
    ), title_key="settings.vault_sync.section"),
    # 会话记忆蒸馏：一个配置键（memory_distill）分两组，和配置全景上的两块磁贴一一对应。
    # 个人侧这组还管抽取（总开关、扫不扫 WSL、保留几天、哪些目录算公司）：抽取在 Windows 这边跑，不靠 WSL。
    # 个人侧的模型存空串 = 跟 AI 对话一致；公司侧的模型名拼进 shell 命令（claude -p --model），过 normalize 的白名单。
    Group("distill_personal", "briefing", md.CONFIG_KEY, "personal", md.normalize, (
        Setting("enabled", "toggle", text="distill.settings.enabled"),
        Setting("scan_wsl", "toggle", text="distill.settings.scan_wsl_label", hint="distill.settings.scan_wsl_hint"),
        Setting("keep_days", "number", bounds=md.KEEP_DAYS_RANGE, unit="settings.unit.days",
                text="distill.settings.keep_days_label", hint="distill.settings.keep_days_hint"),
        Setting("work_roots", "lines", text="distill.settings.work_roots_label", hint="distill.settings.work_roots_hint"),
        Setting("daily_at", "choice_or_text", choices=md.TIME_CHOICES, text="distill.settings.daily_at_label",
                hint="distill.settings.daily_at_hint"),
        Setting("model", "choice_or_text", choices=("", *md.MODEL_CHOICES), labels=(("", "distill.settings.same_as_chat"),),
                text="distill.settings.model_label", hint="distill.settings.model_hint"),
        Setting("effort", "choice", choices=wb.EFFORT_CHOICES, text="distill.settings.effort_label",
                hint="distill.settings.effort_hint"),
        Setting("mirror_to_vault", "toggle", text="distill.settings.mirror_label", hint="distill.settings.mirror_hint"),
        _distill_prompt("", "zh"),
        _distill_prompt("", "en"),
    ), title_key="distill.settings.section_personal",
        not_editable={key: "公司侧那一组（distill_work）里改" for key in _DISTILL_WORK}),
    Group("distill_work", "briefing", md.CONFIG_KEY, "work", md.normalize, (
        Setting("work_distill", "toggle", text="distill.settings.work_distill_label", hint="distill.settings.work_distill_hint"),
        Setting("work_daily_at", "choice_or_text", choices=md.TIME_CHOICES, text="distill.settings.work_daily_at_label",
                hint="distill.settings.work_daily_at_hint"),
        Setting("work_model", "choice_or_text", choices=md.WORK_MODEL_CHOICES, text="distill.settings.work_model_label",
                hint="distill.settings.work_model_hint"),
        Setting("work_effort", "choice", choices=wb.EFFORT_CHOICES, text="distill.settings.work_effort_label",
                hint="distill.settings.work_effort_hint"),
        Setting("work_mirror_to_vault", "toggle", text="distill.settings.work_mirror_label",
                hint="distill.settings.work_mirror_hint"),
        _distill_prompt("work_", "zh"),
        _distill_prompt("work_", "en"),
    ), title_key="distill.settings.section_work", available=lambda: bool(claude_hooks.wsl_exe()),
        unavailable_text="distill.settings.work_no_wsl",
        not_editable={key: "个人侧那一组（distill_personal）里改；总开关也在那里，它同时管抽取" for key in _DISTILL_PERSONAL}),
    # Claude Code 联动：开关只是启停监视器，写 ~/.claude/settings.json 的 hooks 另要用户同意（ADR 0006），所以这里没有「装 hooks」
    # 这一项——它是图上的一个动作，不是设置。cursor / opencode 只读监听别的工具的事件文件，用得少，收在「高级」。
    _agent_link_group("link_win", "personal", (
        Setting("claude", "toggle", text="settings.link_win.claude"),
        Setting("cursor", "toggle", disclosure="advanced", text="settings.link_win.cursor"),
        Setting("opencode", "toggle", disclosure="advanced", text="settings.link_win.opencode"),
        # 自定义联动 Agent：{key, name, path} 的列表（records 控件）。写入过 config._clean_custom_agents：key 小写、不和内置键重复、
        # path 非空，不合规的条目会被它丢掉 → check_changes 判 rejected，页面那一行标红。改了就热生效（AgentLinkManager.apply_config）。
        Setting("custom_agents", "records", disclosure="advanced", text="settings.link_win.custom_agents",
                fields=(("key", "settings.link_win.custom_agents.key"), ("name", "settings.link_win.custom_agents.name"),
                        ("path", "settings.link_win.custom_agents.path"))),
    ), "panorama.feature.link_win"),
    _agent_link_group("link_wsl", "work", (
        Setting("claude_wsl", "toggle", text="settings.link_wsl.claude_wsl"),
    ), "panorama.feature.link_wsl", available=lambda: bool(claude_hooks.wsl_exe()), unavailable_text="settings.link_wsl.no_wsl"),
    # 会话小鱼：数字的范围照抄 _clean_agent_link_data 夹值用的那几对；桂冠片段由 session_crown.normalize_tokens 小写去重，
    # 大写会被判 rejected；配色 / 字号的可选值直接取功能自己的表，字号是整数下拉。
    _agent_link_group("session_fish", "personal", (
        Setting("session_pets", "toggle", text="menu.shared.one_fish_per_session", hint="settings.session_fish.session_pets_hint"),
        Setting("session_pets_max", "number", bounds=(1, _SESSION_PETS_MAX_CAP), unit="settings.unit.fish",
                text="menu.shared.session_fish_limit", hint="settings.session_fish.session_pets_max_hint"),
        Setting("session_fish_keep_days", "number", bounds=(1, 30), unit="settings.unit.days",
                text="menu.shared.session_fish_keep_days", hint="settings.session_fish.session_fish_keep_days_hint"),
        Setting("crown_models", "lines", text="menu.shared.laurel_which_model", hint="settings.session_fish.crown_models_hint"),
        Setting("session_card_theme", "choice", choices=tuple(sct.CARD_THEMES),
                labels=tuple((theme_id, f"menu.card_theme.{theme_id}") for theme_id in sct.CARD_THEMES),
                text="menu.shared.detail_card_colors", hint="settings.session_fish.session_card_theme_hint"),
        Setting("session_card_text_size", "choice", choices=sct.TEXT_SIZES,
                labels=tuple((size, f"menu.card_text_size.{sct.text_size_name(size)}") for size in sct.TEXT_SIZES),
                text="menu.shared.detail_card_text_size", hint="settings.session_fish.session_card_text_size_hint"),
    ), "panorama.feature.session_fish"),
    # 会话提示音：四个时刻各一个开关 + 一个声音（内置几个或自填路径，旁边「试听」是页面上的动作 preview_sound，不改设置）。
    # 音量 0~1、冷却 0~30 秒照抄 _clean_agent_link_data 夹值的范围。播放点在 AgentLinkManager._emit_sound，读的是配置的当前值，
    # 所以存了就生效。标题沿用设置窗口原来的文案键；只有「等批准」这个时刻（2026-11-21 新增）和「用哪个声音」几行是新键。
    _agent_link_group("link_sounds", "personal", (
        Setting("sound_enabled", "toggle", text="settings.dlg.agent_sound_effects", hint="settings.dlg.play_sound_when_agent_starts"),
        *_sound_event("start", "settings.dlg.start_sound", "settings.dlg.played_when_agent_starts_working"),
        *_sound_event("attention", "settings.link_sounds.attention_sound", "settings.link_sounds.attention_sound_hint"),
        *_sound_event("done", "settings.dlg.done_sound", "settings.dlg.played_when_agent_finishes_task"),
        *_sound_event("error", "settings.dlg.error_sound", "settings.dlg.played_when_agent_runs_into"),
        Setting("sound_volume", "number", bounds=(0.0, 1.0), depends_on="sound_enabled", text="settings.dlg.sound_volume",
                hint="settings.link_sounds.volume_hint"),
        Setting("sound_cooldown_seconds", "number", bounds=(0.0, 30.0), unit="settings.unit.seconds", disclosure="advanced",
                depends_on="sound_enabled", text="settings.dlg.cooldown", hint="settings.dlg.keeps_sounds_from_firing_too"),
    ), "panorama.feature.link_sounds"),
    # 灵动岛「最近的对话」：保留几天、最多几条这两项以前只能手改 config.json，这次一起露出来。
    _agent_link_group("session_history", "personal", (
        Setting("session_history", "toggle", text="menu.shared.remember_recent_chats", hint="settings.session_history.session_history_hint"),
        Setting("session_history_rows", "number", bounds=(3, 20), unit="settings.unit.rows",
                text="menu.shared.recent_chats_rows", hint="settings.session_history.session_history_rows_hint"),
        Setting("session_history_days", "number", bounds=(1, 30), unit="settings.unit.days",
                text="settings.session_history.session_history_days"),
        Setting("session_history_max", "number", bounds=(1, 200), unit="settings.unit.items",
                text="settings.session_history.session_history_max"),
    ), "panorama.feature.session_history"),
)
