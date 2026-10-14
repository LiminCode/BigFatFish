# -*- coding: utf-8 -*-
"""Windows 通知中心里的通知（第一期只认 Slack）：读出来、合并、跳回去。

为什么要有它：Windows 一次只弹一条 toast，叠不起来，Slack 连着来几条就只剩最后一条；通知中心
里虽然都在，但要先点开再找。灵动岛把它们按卡片铺开，点一条就跳到 Slack 里那条消息。

三件事，三层：

- **读**（``read_toasts``）：Windows 的 ``UserNotificationListener``（WinRT）给出通知中心里现有的
  toast：应用名、两段文字（Slack：标题是频道或对方的名字，正文是「发送人: 消息」）、创建时间、
  一个整数 id。它不给频道 id、消息时间戳，也不给 Slack 自己点击时用的启动参数。没有包身份
  的进程订阅不了变更事件（实测报「Element not found」），所以只能隔几秒读一次。
- **合并**（``merge``，纯函数）：这次读到的是通知中心里**现有**的；用户在 Windows 那边划掉的、
  我们这边跳过的会从里面消失，但卡片里还留着（``in_center=False``），只是跳不回原消息了。
- **跳**（``activate``）：按名字的 ``slack://channel`` 深链接只认频道 id，给名字不跳还把 Slack
  弄成报错页（2026-10-14 实测）。可行的是：打开通知中心（``ms-actioncenter:``），用 UI 自动化找到
  那条通知并 Invoke——Windows 把激活交给 Slack，Slack 带着自己的参数跳到那条消息（实测 0.3 秒
  找到、跳转成功，Slack 窗口标题换成那个频道）。通知中心里已经没有它了就退一步：
  ``slack://open?team=<id>`` 打开 Slack（team id 读 Slack 自己的 ``root-state.json``）。

本模块不碰 Qt。所有 Windows 调用都设计成在工作线程里跑（WinRT 走 ``asyncio.run``，UIA 的 COM
在线程里自己初始化）；缺包、非 Windows、没权限时读出来是空列表，不抛。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from typing import Callable, Iterable

log = logging.getLogger(__name__)

CONFIG_KEY = "notifications"
POLL_RANGE = (2, 60)            # 秒
KEEP_RANGE = (5, 200)           # 卡片里最多留几条
DEFAULT_APPS = ("slack",)
DEFAULTS = {"enabled": True, "poll_seconds": 3, "keep": 50, "apps": list(DEFAULT_APPS)}

#: Slack 两种安装方式的本地状态文件（里面有 workspace 的 id / 名字 / 域名）
_SLACK_STATE_FILES = (
    (r"%LOCALAPPDATA%\Packages\91750D7E.Slack_8she8kybcnzg4\LocalCache\Roaming\Slack\storage\root-state.json"),
    (r"%APPDATA%\Slack\storage\root-state.json"),
)
_SENDER_RE = re.compile(r"^(?P<sender>[^\n:]{1,48}): (?P<message>.+)$", re.S)
_CENTER_URI = "ms-actioncenter:"
_CENTER_WAIT_S = 2.0
_BODY_PROBE_CHARS = 30


# ---------------------------------------------------------------- 配置
def _clamp(value, default: int, bounds: tuple[int, int]) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(bounds[0], min(bounds[1], number))


def normalize(raw) -> dict:
    """配置里的 ``notifications``：缺的补默认、脏的夹回去。``apps`` 是应用名片段（小写、去空）。"""
    data = dict(raw) if isinstance(raw, dict) else {}
    apps = data.get("apps", DEFAULTS["apps"])
    if isinstance(apps, str):
        apps = apps.split(",")
    cleaned: list[str] = []
    for item in apps if isinstance(apps, (list, tuple)) else DEFAULTS["apps"]:
        text = str(item or "").strip().lower()
        if text and text not in cleaned:
            cleaned.append(text)
    return {
        "enabled": bool(data.get("enabled", DEFAULTS["enabled"])) if not isinstance(data.get("enabled"), str)
        else data["enabled"].strip().lower() in ("1", "true", "yes", "on"),
        "poll_seconds": _clamp(data.get("poll_seconds"), DEFAULTS["poll_seconds"], POLL_RANGE),
        "keep": _clamp(data.get("keep"), DEFAULTS["keep"], KEEP_RANGE),
        "apps": cleaned or list(DEFAULT_APPS),
    }


def matches_app(name: str, app_id: str, fragments: Iterable[str]) -> bool:
    """应用名或 AUMID 里含任一片段（不分大小写）。"""
    haystack = f"{name or ''}\n{app_id or ''}".lower()
    return any(fragment and fragment in haystack for fragment in fragments)


# ---------------------------------------------------------------- 数据
@dataclass(frozen=True)
class Notice:
    """通知中心里的一条。``uid`` 是 Windows 给的整数 id（同一进程会话内稳定）。"""

    uid: int
    app: str                 # 应用显示名（Slack）
    app_id: str              # AUMID
    title: str               # Slack：频道（#name / 私密频道不带 #）或私聊对方
    body: str                # Slack：「发送人: 消息」或消息本身
    created: float           # epoch 秒
    in_center: bool = True   # 还在 Windows 通知中心里（能从那里激活）

    @property
    def kind(self) -> str:
        return "slack" if "slack" in f"{self.app}\n{self.app_id}".lower() else "other"

    @property
    def sender(self) -> str:
        return split_body(self.body)[0]

    @property
    def message(self) -> str:
        return split_body(self.body)[1]


def split_body(body: str) -> tuple[str, str]:
    """「发送人: 消息」拆成两段；拆不出来发送人为空、整段当消息。"""
    text = str(body or "").strip()
    match = _SENDER_RE.match(text)
    if match is None:
        return "", text
    return match.group("sender").strip(), match.group("message").strip()


def merge(known: Iterable[Notice], fresh: Iterable[Notice], *, keep: int,
          hidden: Iterable[int] = ()) -> tuple[list[Notice], list[int]]:
    """这次读到的（``fresh``，通知中心里现有的）并进已知的（``known``）。

    返回 (新列表（新到旧，最多 ``keep`` 条）, 这次新出现的 uid)。已知但这次没读到的保留下来，
    标成 ``in_center=False``；``hidden`` 里的（用户在卡片里移除过的）不再出现。
    """
    hidden_set = set(hidden)
    fresh_by_uid = {n.uid: replace(n, in_center=True) for n in fresh if n.uid not in hidden_set}
    known_list = [n for n in known if n.uid not in hidden_set]
    known_uids = {n.uid for n in known_list}
    merged = list(fresh_by_uid.values())
    merged += [replace(n, in_center=False) for n in known_list if n.uid not in fresh_by_uid]
    merged.sort(key=lambda n: (n.created, n.uid), reverse=True)
    new_uids = [n.uid for n in fresh_by_uid.values() if n.uid not in known_uids]
    return merged[:max(1, int(keep))], new_uids


# ---------------------------------------------------------------- 读（WinRT）
def _import_winrt():
    """惰性导入；缺包 / 非 Windows 返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
    except ImportError:
        return None
    return UserNotificationListener, UserNotificationListenerAccessStatus, NotificationKinds


def available() -> bool:
    """这台机器上能不能用（Windows + 装了 WinRT 通知包）。不碰系统。"""
    return _import_winrt() is not None


def access_status() -> str:
    """``allowed`` / ``denied`` / ``unavailable``：Windows「让应用访问通知」的开关。"""
    mods = _import_winrt()
    if mods is None:
        return "unavailable"
    listener_cls, status_enum, _kinds = mods

    async def ask():
        return await listener_cls.current.request_access_async()

    try:
        status = asyncio.run(ask())
    except Exception:  # noqa: BLE001 - 系统侧任何失败都当不可用
        log.debug("通知中心：询问权限失败", exc_info=True)
        return "unavailable"
    return "allowed" if status == status_enum.ALLOWED else "denied"


def _texts_of(notification) -> list[str]:
    binding = notification.visual.get_binding("ToastGeneric")
    if binding is None:
        return []
    return [str(element.text or "") for element in binding.get_text_elements()]


async def _read_async(fragments: tuple[str, ...], want_logos: set[str],
                      known: dict[int, Notice]) -> tuple[list[Notice], dict[str, bytes]]:
    listener_cls, status_enum, kinds = _import_winrt()
    listener = listener_cls.current
    if await listener.request_access_async() != status_enum.ALLOWED:
        return [], {}
    items = await listener.get_notifications_async(kinds.TOAST)
    notices: list[Notice] = []
    logos: dict[str, bytes] = {}
    for item in items:
        uid = int(item.id)
        cached = known.get(uid)
        if cached is not None and (cached.app_id not in want_logos or cached.app_id in logos):
            notices.append(cached)      # 上一轮读过的：应用信息与文字不会变，省掉逐条取（这是大头）
            continue
        try:
            info = item.app_info
            name = str(info.display_info.display_name or "")
            app_id = str(info.app_user_model_id or "")
        except Exception:  # noqa: BLE001 - 个别通知没有应用信息：跳过
            continue
        if not matches_app(name, app_id, fragments):
            continue
        texts = _texts_of(item.notification)
        title = texts[0] if texts else ""
        body = "\n".join(texts[1:]) if len(texts) > 1 else ""
        try:
            created = item.creation_time.timestamp()
        except Exception:  # noqa: BLE001
            created = time.time()
        notices.append(Notice(uid=uid, app=name, app_id=app_id, title=title, body=body, created=created))
        if app_id in want_logos and app_id not in logos:
            try:
                logos[app_id] = await _logo_bytes(info)
            except Exception:  # noqa: BLE001 - 没有图标就没有，卡片用手绘记号
                logos[app_id] = b""
    return notices, logos


async def _logo_bytes(info) -> bytes:
    """应用自己的图标（PNG 字节，32px）。"""
    from winrt.windows.foundation import Size
    from winrt.windows.storage.streams import DataReader

    stream = await info.display_info.get_logo(Size(32, 32)).open_read_async()
    size = int(stream.size)
    if size <= 0:
        return b""
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(size)
    buffer = bytearray(size)
    reader.read_bytes(buffer)
    return bytes(buffer)


def read_toasts(fragments: Iterable[str], *, want_logos: Iterable[str] = (),
                known: Iterable[Notice] = ()) -> tuple[list[Notice], dict[str, bytes]]:
    """通知中心里现有的、应用名匹配的 toast，以及 ``want_logos`` 里那些应用的图标字节。

    ``known`` 是上一轮的结果：同一 id 直接复用，不再逐条取应用信息（一条约 10 ms，列表本身
    才几十毫秒）。在工作线程里调用（里面是 ``asyncio.run``）。不可用 / 没权限 / 出错都返回 ``([], {})``。
    """
    if _import_winrt() is None:
        return [], {}
    try:
        return asyncio.run(_read_async(tuple(fragments), set(want_logos), {n.uid: n for n in known}))
    except Exception:  # noqa: BLE001 - 读失败这一轮算空，下一轮再来
        log.debug("通知中心：读取失败", exc_info=True)
        return [], {}


def remove_from_center(uid: int) -> bool:
    """把一条从 Windows 通知中心里拿掉（用户在卡片里「移除」时顺手同步）。"""
    mods = _import_winrt()
    if mods is None:
        return False
    try:
        mods[0].current.remove_notification(int(uid))
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 跳（UIA + 深链接）
def slack_team_id(*, files: Iterable[str] = _SLACK_STATE_FILES) -> str:
    """Slack 本地状态里第一个 workspace 的 id（``T…``）；读不到返回空。"""
    for raw in files:
        path = os.path.expandvars(raw)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        workspaces = data.get("workspaces") if isinstance(data, dict) else None
        if isinstance(workspaces, dict):
            for key, value in workspaces.items():
                team = str((value or {}).get("id") or key) if isinstance(value, dict) else str(key)
                if team.startswith("T"):
                    return team
    return ""


def fallback_url(notice: Notice, team_id: str = "") -> str:
    """通知中心里已经没有这条时退一步打开的地址；不认识的应用返回空。"""
    if notice.kind != "slack":
        return ""
    return f"slack://open?team={team_id}" if team_id else "slack://open"


def _center_probe(notice: Notice) -> tuple[str, str]:
    """在通知中心的 UIA 树里认这条用的两段文字。"""
    body = " ".join(notice.body.split())
    return notice.title.strip(), body[:_BODY_PROBE_CHARS]


def _invoke_in_center(notice: Notice, *, wait_s: float = _CENTER_WAIT_S) -> bool:
    """打开通知中心，找到这条通知并激活。找不到返回 False（通知中心留给系统自己收）。"""
    import comtypes
    import comtypes.client

    comtypes.CoInitialize()
    try:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        root = uia.GetRootElement()
        os.startfile(_CENTER_URI)  # noqa: S606 - 系统 URI，打开通知中心
        core_cond = uia.CreatePropertyCondition(UIA.UIA_ClassNamePropertyId, "Windows.UI.Core.CoreWindow")
        list_cond = uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, "MainListView")
        item_cond = uia.CreatePropertyCondition(UIA.UIA_ClassNamePropertyId, "ListViewItem")
        title, probe = _center_probe(notice)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            time.sleep(0.1)
            windows = root.FindAll(UIA.TreeScope_Children, core_cond)
            for index in range(windows.Length):
                window = windows.GetElement(index)
                if window.CurrentIsOffscreen or window.FindFirst(UIA.TreeScope_Descendants, list_cond) is None:
                    continue
                items = window.FindAll(UIA.TreeScope_Descendants, item_cond)
                for j in range(items.Length):
                    element = items.GetElement(j)
                    name = " ".join(str(element.CurrentName or "").split())
                    if probe and probe in name and (not title or title in name):
                        element.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(
                            UIA.IUIAutomationInvokePattern).Invoke()
                        return True
                return False      # 通知中心开着、列表里没有它：别再等
        return False
    finally:
        comtypes.CoUninitialize()


def activate(notice: Notice, *, team_id: str | None = None, invoke: Callable[[Notice], bool] | None = None,
             open_url: Callable[[str], None] | None = None) -> str:
    """跳到这条通知对应的消息。返回：``activated``（经通知中心交给了应用）/ ``opened_app``
    （通知中心里没有了，改为打开应用）/ ``gone``（没有了、也不知道怎么打开）/ ``failed``。"""
    invoke = invoke or _invoke_in_center
    open_url = open_url or os.startfile
    if notice.in_center:
        try:
            if invoke(notice):
                return "activated"
        except Exception:  # noqa: BLE001 - UIA 失败走退路
            log.debug("通知中心：激活失败", exc_info=True)
    url = fallback_url(notice, slack_team_id() if team_id is None else team_id)
    if not url:
        return "gone"
    try:
        open_url(url)
    except OSError:
        return "failed"
    return "opened_app"
