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
- **启动参数**（``launch_targets``，2026-10-26）：通知自己点开时用的参数（toast XML 根上的
  ``launch`` / ``activationType``）监听接口不给，但 Windows 的通知数据库
  （``%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db``）里有，而且数据库的
  ``Notification.Id`` 就是监听接口给的 id（实测 22/22 对上）。数据库被系统服务开着、一直在写：
  只把三个文件复制到临时目录查副本（约 20 ms），只读、查完删掉；只在有新通知的那一轮查一次，
  结果记在 ``Notice`` 上，通知中心里没了也还能跳。Slack 的是 ``activationType="protocol"``、
  ``launch="slack://channel?id=…&message=…&team=…"``：直接打开就跳到那条消息。
- **跳**（``activate``）：有协议型的启动参数就直接打开它（不弹通知中心），再像系统一样把那条
  从通知中心拿掉。没有的（应用走 COM 激活，如 Teams）退回老办法：打开通知中心
  （``ms-actioncenter:``），用 UI 自动化找到那条通知并 Invoke（实测 0.3 秒）。通知中心里也没有了
  就再退一步：``slack://open?team=<id>`` 打开 Slack（team id 读 Slack 自己的 ``root-state.json``）。

本模块不碰 Qt。所有 Windows 调用都设计成在工作线程里跑（WinRT 走 ``asyncio.run``，UIA 的 COM
在线程里自己初始化）；缺包、非 Windows、没权限时读出来是空列表，不抛。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Callable, Iterable

log = logging.getLogger(__name__)

CONFIG_KEY = "notifications"
POLL_RANGE = (2, 60)            # 秒
KEEP_RANGE = (5, 200)           # 卡片里最多留几条
DEFAULT_APPS = ("slack",)
ALL_APPS = "*"                  # apps 里写它 = 所有应用
#: 我们自己弹的通知（``notification_toast``）：哪个角、哪块屏、留几秒、最多同时几条
TOAST_CORNERS = ("top_right", "top_left", "bottom_right", "bottom_left")
TOAST_SCREEN_PRIMARY = "primary"
TOAST_SCREEN_CURSOR = "cursor"
TOAST_SECONDS_RANGE = (2, 60)
TOAST_MAX_RANGE = (1, 10)
TOAST_DEFAULTS = {"enabled": False, "corner": "top_right", "screen": TOAST_SCREEN_PRIMARY, "seconds": 6,
                  "max_visible": 5}
DEFAULTS = {"enabled": True, "poll_seconds": 3, "keep": 50, "apps": list(DEFAULT_APPS), "toast": TOAST_DEFAULTS}

_DB_DIR = r"%LOCALAPPDATA%\Microsoft\Windows\Notifications"
_DB_NAME = "wpndatabase.db"
_SCHEME_RE = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]+):", re.I)
_UNSAFE_SCHEMES = {"file", "javascript", "vbscript", "data"}

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


def _flag(value, default: bool) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default if value is None else bool(value)


def normalize_toast(raw) -> dict:
    """``notifications.toast``：缺的补默认、脏的夹回去。``screen`` 是 ``primary`` / ``cursor`` / 屏幕名。"""
    data = dict(raw) if isinstance(raw, dict) else {}
    corner = str(data.get("corner") or "").strip()
    screen = str(data.get("screen") or "").strip()
    return {
        "enabled": _flag(data.get("enabled"), TOAST_DEFAULTS["enabled"]),
        "corner": corner if corner in TOAST_CORNERS else TOAST_DEFAULTS["corner"],
        "screen": screen or TOAST_DEFAULTS["screen"],
        "seconds": _clamp(data.get("seconds"), TOAST_DEFAULTS["seconds"], TOAST_SECONDS_RANGE),
        "max_visible": _clamp(data.get("max_visible"), TOAST_DEFAULTS["max_visible"], TOAST_MAX_RANGE),
    }


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
        "toast": normalize_toast(data.get("toast")),
    }


def matches_app(name: str, app_id: str, fragments: Iterable[str]) -> bool:
    """应用名或 AUMID 里含任一片段（不分大小写）；片段 ``*`` 认所有应用。"""
    haystack = f"{name or ''}\n{app_id or ''}".lower()
    return any(fragment == ALL_APPS or (fragment and fragment in haystack) for fragment in fragments)


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
    launch: str = ""         # 通知自己的启动参数（数据库里读的；Slack 是 slack://channel?… 深链接）
    activation: str = ""     # 启动参数的类型：protocol / foreground / background；"none" = 查过没有；"" = 还没查

    @property
    def launchable(self) -> bool:
        """能不经通知中心直接跳（协议型的启动参数，且是正常的 URI）。"""
        return self.activation == "protocol" and launchable_uri(self.launch)

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


# ---------------------------------------------------------------- 启动参数（通知数据库的副本）
def parse_launch(payload) -> tuple[str, str]:
    """toast XML 根上的 (``activationType``, ``launch``)；类型缺省是 ``foreground``。解析不了返回 ("", "")。"""
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8", "replace")
    try:
        root = ET.fromstring(str(payload or ""))
    except ET.ParseError:
        return "", ""
    return str(root.get("activationType") or "foreground"), str(root.get("launch") or "")


def launchable_uri(uri: str) -> bool:
    """能交给系统直接打开的启动参数：有正经的协议名（至少两个字母，排除 ``C:\\…`` 这种盘符路径），
    且不是 file / 脚本类。"""
    match = _SCHEME_RE.match(str(uri or ""))
    return bool(match) and match.group("scheme").lower() not in _UNSAFE_SCHEMES


def launch_targets(uids: Iterable[int], *, source_dir: str = _DB_DIR) -> dict[int, tuple[str, str]]:
    """这些通知 id 的 (activationType, launch)。数据库被系统服务开着：复制到临时目录查副本，查完删掉。

    查不到的 id 不在结果里；数据库不在 / 读坏了返回 ``{}``。在工作线程里调用。
    """
    wanted = sorted({int(uid) for uid in uids})
    folder = os.path.expandvars(source_dir)
    if not wanted or not os.path.isfile(os.path.join(folder, _DB_NAME)):
        return {}
    found: dict[int, tuple[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="bff-wpn-") as scratch:
        try:
            for suffix in ("", "-wal", "-shm"):
                source = os.path.join(folder, _DB_NAME + suffix)
                if os.path.isfile(source):
                    shutil.copyfile(source, os.path.join(scratch, _DB_NAME + suffix))
            db = sqlite3.connect(os.path.join(scratch, _DB_NAME))
            try:
                marks = ",".join("?" * len(wanted))
                rows = db.execute(f"SELECT Id, Payload FROM Notification WHERE Id IN ({marks})", wanted).fetchall()
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            log.debug("通知中心：读通知数据库副本失败", exc_info=True)
            return {}
    for uid, payload in rows:
        kind, launch = parse_launch(payload)
        if kind:
            found[int(uid)] = (kind, launch)
    return found


def with_launch(notices: list[Notice], lookup: Callable[[list[int]], dict] = launch_targets) -> list[Notice]:
    """给还没查过启动参数的那几条补上（一次查一批）；查不到的记成 ``none``，以后不再查。"""
    missing = [n.uid for n in notices if not n.activation]
    if not missing:
        return notices
    try:
        found = lookup(missing)
    except Exception:  # noqa: BLE001 - 查不到就当没有，跳转走老路
        log.debug("通知中心：查启动参数失败", exc_info=True)
        found = {}
    out = []
    for notice in notices:
        if not notice.activation:
            kind, launch = found.get(notice.uid, ("none", ""))
            notice = replace(notice, activation=kind or "none", launch=launch)
        out.append(notice)
    return out


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
    才几十毫秒），启动参数也只给新来的查一次（``with_launch``）。在工作线程里调用（里面是 ``asyncio.run``）。不可用 / 没权限 / 出错都返回 ``([], {})``。
    """
    if _import_winrt() is None:
        return [], {}
    try:
        notices, logos = asyncio.run(_read_async(tuple(fragments), set(want_logos), {n.uid: n for n in known}))
    except Exception:  # noqa: BLE001 - 读失败这一轮算空，下一轮再来
        log.debug("通知中心：读取失败", exc_info=True)
        return [], {}
    return with_launch(notices), logos


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
             open_url: Callable[[str], None] | None = None, remove: Callable[[int], object] | None = None) -> str:
    """跳到这条通知对应的消息。返回：``launched``（直接打开了通知自己的启动参数）/ ``activated``
    （经通知中心交给了应用）/ ``opened_app``（通知中心里没有了，改为打开应用）/ ``gone``（没有了、
    也不知道怎么打开）/ ``failed``。"""
    invoke = invoke or _invoke_in_center
    open_url = open_url or os.startfile
    remove = remove or remove_from_center
    if notice.launchable:
        try:
            open_url(notice.launch)
        except OSError:
            log.debug("通知中心：打开启动参数失败", exc_info=True)
        else:
            if notice.in_center:
                remove(notice.uid)          # 系统点开一条也会把它从通知中心拿掉
            return "launched"
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
