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
- ``control``：页面上用哪种控件（``CONTROLS``）；
- ``choices``：下拉的可选值。``choice`` 只能选其中之一，``choice_or_text`` 还可以自己填；
- ``commit``：什么时候算存上。不写就按控件定——开关和下拉一动就存（``immediate``），文本框等用户点保存（``on_finish``）；
- ``disclosure``：``primary`` 直接露出，``advanced`` 收在「高级」里；
- ``depends_on``：同组的一个开关；它关着时这一项变灰；
- ``builtin``：只给长文本用——留空时功能实际用的那段内置文字（给页面当底稿显示，也是「恢复内置」的目标）。
  它是个函数，参数是这一组当前生效的值：内置提示词会随别的设置变（勾了哪些来源）；
- ``bounds``：只给数字用——``(下限, 上限)``，抄功能自己 ``normalize`` 夹值用的那一对。页面拿它画输入框的范围，
  写入时超出范围报 ``out_of_range``（不然 ``normalize`` 会悄悄夹到边上，用户以为存的是 3，其实是 5）；
- ``unit``：数字后面的单位（文案键），比如「分钟」。

文字不在这里：标题和说明在字表里，键由 ``title_key`` / ``hint_key`` 给出（默认 ``settings.<组>.<id>`` 和它加 ``_hint``；
从 Qt 设置窗口搬过来的那些直接沿用原来的键，不抄第二份）。
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from . import claude_hooks
from . import slack_watch as sw
from . import work_briefing as wb
from . import work_notes as wn

ZONES = ("personal", "work")                # 这一组设置管的是哪个账号那一侧的功能
CONTROLS = ("toggle", "choice", "choice_or_text", "number", "text", "long_text")
COMMITS = ("immediate", "on_finish", "confirm")
DISCLOSURES = ("primary", "advanced")
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

    @property
    def commit_policy(self) -> str:
        return self.commit or ("on_finish" if self.control in _TEXT_CONTROLS else "immediate")


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
        wanted = changes[key].strip() if by_id[key].control in _TEXT_CONTROLS else changes[key]
        if get_path(final, key) != wanted:
            errors.append({"id": key, "code": "rejected"})
    return (None, errors) if errors else (final, [])


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
            if setting.id not in produced:
                raise bad(f"{setting.id}: the feature's normalize() does not produce this key")
            if not _fits(setting.control, produced[setting.id]):
                raise bad(f"{setting.id}: a {setting.control} cannot hold the default {produced[setting.id]!r}")
            if (setting.bounds or setting.unit) and setting.control != "number":
                raise bad(f"{setting.id}: only a number has bounds or a unit")
            if setting.bounds and (len(setting.bounds) != 2 or not setting.bounds[0] <= produced[setting.id] <= setting.bounds[1]):
                raise bad(f"{setting.id}: bounds must be (low, high) around the default {produced[setting.id]!r}")
        for setting in item.settings:
            if setting.depends_on and (setting.depends_on not in by_id or by_id[setting.depends_on].control != "toggle"):
                raise bad(f"{setting.id}: depends_on must name a toggle in the same group")


# ───────────────────────── 表 ─────────────────────────

_MODEL_CHOICES = ("sonnet", "haiku", "opus")


def _briefing_prompt(language: str) -> Setting:
    return Setting(f"prompt_{language}", "long_text", disclosure="advanced",
                   builtin=lambda effective: wb.default_prompt_template(language, effective.get("sources")),
                   text=f"settings.work_briefing.prompt_{language}", hint="briefing.settings.prompt_hint")


def _notes_prompt(language: str) -> Setting:
    return Setting(f"prompt_{language}", "long_text", disclosure="advanced",
                   builtin=lambda _effective: wn.default_prompt_template(language),
                   text=f"settings.work_notes.prompt_{language}", hint="notes.settings.prompt_hint")


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
        _briefing_prompt("zh"),
        _briefing_prompt("en"),
        Setting("priority_rules", "long_text", text="briefing.settings.priority_rules"),
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
)
