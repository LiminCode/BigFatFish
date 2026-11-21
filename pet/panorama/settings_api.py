# -*- coding: utf-8 -*-
"""读、改一组设置（配置全景页面经本机服务来调）。

这里是写入链路里**碰配置**的那一段，必须在主进程的界面线程上跑（``PanoramaService`` 负责把请求线程的活儿转过来）。
本身不碰 Qt：拿到的是一个活的 ``Config``（``get`` / ``set`` / ``save`` / ``reload``）和一个审计记录，测试直接喂真的。

一次写入按顺序过这几步，哪一步不过就停在那里、配置一个字不动：

1. 这一组在设置表里吗（``unknown_group`` / 404）；请求长得对吗（``bad_request`` / 400）；
2. **先 ``reload()``**：设置窗口是另一个进程，它可能刚存过别的键，主进程内存里还是旧的。不重读就整份写回去，会把它的改动盖掉；
3. 页面交回来的版本和现在的对得上吗（``stale`` / 409，顺带把现在的值给它）；
4. 这一组在这台机器上用得了吗（``unavailable`` / 409）；
5. 每一项改动过设置表和功能自己的校验吗（``invalid`` / 422，指出是哪几项）——见 ``settings_table.check_changes``；
6. ``set`` + ``save``；存不上就把内存里的值退回去（``save_failed`` / 500）；
7. 记审计。
"""
from __future__ import annotations

import copy

from .. import settings_table as st
from ..i18n import t


class Busy(Exception):
    """界面线程没空，这次没办成（请求等到了超时，排着的那个调用已经作废，不会之后再补上）。"""


class SettingsError(Exception):
    """写不了 / 读不了。``status`` 和 ``code`` 给页面；``detail`` 是随错误一起回去的东西（哪几项不对、现在的值）。"""

    def __init__(self, status: int, code: str, **detail) -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


def _group(group_id: str) -> st.Group:
    try:
        return st.group(str(group_id))
    except KeyError:
        raise SettingsError(404, "unknown_group") from None


def _text(key: str) -> str:
    """字表里有就给，没有就是空串（``t()`` 找不到键会把键名原样还回来）。"""
    text = t(key) if key else ""
    return "" if text == key else text


def _labels(setting: st.Setting) -> list[str]:
    """和 ``choices`` 一一对应的显示文字；空串 = 照原样显示值。一个都没写就是空列表。"""
    if not setting.labels:
        return []
    named = dict(setting.labels)
    return [_text(named.get(value, "")) for value in setting.choices]


def describe(group: st.Group, raw) -> dict:
    """页面画这一组表单要的全部东西：每一项用什么控件、叫什么、现在是什么值、默认是什么，外加这一组的版本。"""
    effective = group.normalize(raw)
    current, default = st.values(group, raw), st.defaults(group)
    available = st.is_available(group)
    return {
        "group": group.id, "title": _text(group.title_key), "zone": group.zone, "available": available,
        "unavailable": "" if available else _text(group.unavailable_text), "version": st.version(group, raw),
        "settings": [{
            "id": setting.id, "control": setting.control, "title": _text(st.title_key(group, setting)),
            "hint": _text(st.hint_key(group, setting)), "value": current[setting.id], "default": default[setting.id],
            "choices": list(setting.choices), "commit": setting.commit_policy, "disclosure": setting.disclosure,
            "depends_on": setting.depends_on, "builtin": setting.builtin(effective) if setting.builtin else None,
            "min": setting.bounds[0] if setting.bounds else None, "max": setting.bounds[1] if setting.bounds else None,
            "unit": _text(setting.unit),
            "labels": _labels(setting),
            "fields": [{"id": name, "title": _text(key)} for name, key in setting.fields],
            "action": setting.action,
        } for setting in group.settings],
    }


def read(config, group_id: str) -> dict:
    group = _group(group_id)
    return describe(group, config.get(group.config_key))


def write(config, group_id: str, body, *, audit, source: str = "page") -> dict:
    """按页面提交的 ``{"base": 版本, "changes": {项: 值}}`` 改这一组。成功返回新的描述，外加 ``changed``（真的变了的那几项）。"""
    group = _group(group_id)
    if not isinstance(body, dict) or not isinstance(body.get("base"), str) or not isinstance(body.get("changes"), dict) \
            or not body["changes"]:
        raise SettingsError(400, "bad_request")
    config.reload()                                         # 先吸收盘上别的进程存下的改动
    raw = config.get(group.config_key)
    if body["base"] != st.version(group, raw):
        raise SettingsError(409, "stale", current=describe(group, raw))
    if not st.is_available(group):
        raise SettingsError(409, "unavailable")
    new_raw, errors = st.check_changes(group, raw, body["changes"])
    if errors:
        raise SettingsError(422, "invalid", errors=errors)
    before, after = st.values(group, raw), st.values(group, new_raw)
    changed = [key for key in body["changes"] if before[key] != after[key]]
    if changed:
        previous = copy.deepcopy(raw)
        config.set(group.config_key, new_raw)
        if not config.save():
            config.set(group.config_key, previous)          # 没存上：内存里的值退回去，免得运行中的功能用上没落盘的设置
            raise SettingsError(500, "save_failed")
        audit.append([{"group": group.id, "setting": key, "old": before[key], "new": after[key], "source": source} for key in changed])
    return {"changed": changed, **describe(group, config.get(group.config_key))}
