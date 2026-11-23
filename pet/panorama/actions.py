# -*- coding: utf-8 -*-
"""配置全景页面上的**动作**：不是改一项设置，而是请主进程做一件事：给联动通道装 hooks、重新生成报告、试听一个提示音……

一个动作 = 一个处理器 ``handler(body) -> dict``，由应用构造 ``PanoramaService`` 时登记（``actions={"名字": handler}``），
页面 ``POST /api/actions/<名字>`` 来调；服务把它转到界面线程上跑（和改设置同一条路，见 ``PanoramaService.on_gui``）。
要联网、会等很久的动作给处理器标 ``off_gui = True``：服务就在请求线程上直接调它，由它自己在需要时回界面线程（``check_remote``）。
处理器自己校验参数，拒绝就抛 ``ActionError``（状态码 + 代码），意料之外的异常由服务翻成 500 ``action_failed``。

**装 hooks 每次都要用户同意（ADR 0006）。** 同意框在页面上（``repair.js`` 的 ``confirm()``，文案同右键菜单那条路的 Qt 弹框）；
这里拿到的请求就是「用户点了是」，于是只调管理器的「装」那一半（``install_hooks_consented``），不再弹 Qt 的问题框。
打开通道的开关永远只是起监视器，装 hooks 永远是这另一次明确的点击——所以它是独立的 POST，不藏在 PATCH 设置里。
"""
from __future__ import annotations

import contextlib
import logging
import threading
import weakref
from pathlib import Path
from typing import Callable

from .. import personal_vault
from .. import settings_table as st
from ..click_sound import play_sound, resolve_builtin_sound

log = logging.getLogger(__name__)

#: 要靠 hooks 的两条通道 → 它们在图上的哪一侧（装完重探那一侧）
HOOKED_SIDES = {"claude": "win", "claude_wsl": "wsl"}
#: 待处理里「现在核对」走的动作名（``sources.repositories`` 写在那条待处理的 action 里）
CHECK_REMOTE_ACTION = "check_remote"
#: 「现在核对」在运行记录里的任务名
CHECK_JOB = "vault_check"
#: 待处理和磁贴详情里「现在同步」走的动作名
SYNC_VAULT_ACTION = "sync_vault"
#: 设置表里 ``Setting.action`` 写的名字：一项音效设置旁边的「试听」
PREVIEW_SOUND_ACTION = "preview_sound"


def preview_sound(config_of: Callable[[], object | None], play: Callable[..., object] = play_sound) -> Callable[[object], dict]:
    """「试听」：请求体 ``{group, id, value?}``——哪一组、哪一项、页面上此刻选着的值（不给就放存着的）。

    值是 ``builtin:<id>`` 就按内置表找文件，否则当作音频文件的路径；文件不在回 ``missing``（页面说一句，不算错误），
    放了回 ``played``。音量取那一组存着的 ``sound_volume``（没有这一项的组按 1.0）。只认设置表里标了 ``action="preview_sound"``
    的项，别的项 400。**不存配置、不碰联动的冷却**：它和 ``AgentLinkManager._emit_sound`` 只共用 ``play_sound`` 这一个出口。
    必须在界面线程上跑（服务的 ``on_gui`` 保证）：``play_sound`` 退到 QtMultimedia 时只能在那条线程上建对象。"""
    def run(body) -> dict:
        if not isinstance(body, dict):
            raise ActionError(400, "bad_request")
        try:
            group = st.group(str(body.get("group")))
        except KeyError:
            raise ActionError(404, "unknown_group") from None
        setting = next((item for item in group.settings if item.id == body.get("id")), None)
        if setting is None or setting.action != PREVIEW_SOUND_ACTION:
            raise ActionError(400, "bad_setting")
        config = config_of()
        if config is None:
            raise ActionError(503, "no_config")
        values = st.values(group, config.get(group.config_key))
        value = body.get("value", values[setting.id])
        if not isinstance(value, str):
            raise ActionError(400, "bad_value")
        value = value.strip()
        if value.startswith("builtin:"):
            path = resolve_builtin_sound(value)
        else:
            path = Path(value).expanduser() if value else None
        if path is None or not path.is_file():
            return {"group": group.id, "id": setting.id, "state": "missing"}
        volume = values.get("sound_volume", 1.0)
        play(path, volume=float(volume))
        return {"group": group.id, "id": setting.id, "state": "played"}

    return run


def generate_report(generators: dict) -> Callable[[object], dict]:
    """报告页上的「重新生成」。``generators``：报告名 → 返回 ``started`` / ``busy`` / ``failed`` / ``unavailable`` 的函数
    （工作简报的在 ``reports.generate_work_briefing``）。不认识的报告名 400 ``bad_report``。"""
    def run(body) -> dict:
        report = body.get("report") if isinstance(body, dict) else None
        if not isinstance(report, str) or report not in generators:
            raise ActionError(400, "bad_report")
        return {"report": report, "state": str(generators[report]())}
    return run


def check_remote(repos: dict, on_gui: Callable[[Callable[[], object]], object], refresh: Callable[[str], object], *,
                 fetch: Callable[..., "tuple[bool, str]"] = personal_vault.fetch,
                 token: Callable[[], str] = personal_vault.github_token, journal=None,
                 state: Callable[[str], dict] = personal_vault.upstream_state, lock=None) -> Callable[[object], dict]:
    """「现在核对」：让一个本地克隆去问一次远端（``git fetch``，不动工作区和本地分支），然后重探本机一侧，磁贴上的
    「领先 / 落后几个提交」才是此刻的。请求体 ``{repo}``；``repos``：名字 → 返回克隆目录的函数（读配置，所以经 ``on_gui`` 调）。

    **不在界面线程上跑**（处理器标了 ``off_gui``，服务就在请求线程上直接调它）：fetch 要联网，可能等上几十秒。它只在两处
    回界面线程——读克隆目录、让服务重探（``refresh`` 要碰 ``Config``）。

    回 ``checked`` / ``failed``（没连上）/ ``missing``（目录不是克隆，不 fetch）/ ``busy``（上一次还没回来）。**没连上也重探**：
    git 已经把 ``FETCH_HEAD`` 清空了，磁贴要改口说「上次核对没连上」。重探没发起（界面线程正忙、还没有页面在看）不算核对
    失败，记一行日志。失败原因只进日志（末 200 个字符，是 git 的报错，不含仓库内容）。

    给了 ``journal``（``run_journal.Journal``）就把这次核对记成运行记录里的一行（任务 ``vault_check``、触发 ``manual``）：
    fetch 前后各问一次 ``state``（远端分支指向哪、差几个提交），远端分支动了 = ``ok``，没动 = ``noop``，没连上 = ``failed``。
    真的 fetch 了才记；``busy`` / ``missing`` 什么都没跑，不记。没给 ``journal`` 时不多问那两次。

    ``lock``：和同步器共用的那把锁（``VaultSync.lock``）——同一个克隆上核对和同步不同时跑；不给就自己一把。
    """
    running = lock if lock is not None else threading.Lock()

    def run(body) -> dict:
        repo = body.get("repo") if isinstance(body, dict) else None
        if not isinstance(repo, str) or repo not in repos:
            raise ActionError(400, "bad_repo")
        if not running.acquire(blocking=False):
            return {"repo": repo, "state": "busy"}
        try:
            repo_dir = str(on_gui(repos[repo]))
            if not personal_vault.repo_ready(repo_dir):
                return {"repo": repo, "state": "missing"}
            record = journal.start(CHECK_JOB, "manual") if journal is not None else None
            before = state(repo_dir) if record else {}
            with record.step("fetch") if record else contextlib.nullcontext():
                ok, reason = fetch(repo_dir, token=token())
            if not ok:
                log.warning("配置全景：核对 %s 没连上远端：%s", repo, reason[-200:])
            if record:
                after = state(repo_dir)
                record.effect("git", op="fetch", repo=repo, before=before.get("head", ""), after=after.get("head", ""),
                              behind=after.get("behind"), ahead=after.get("ahead"))
                record.finish("failed" if not ok else "ok" if after.get("head") != before.get("head") else "noop", "" if ok else reason)
            try:
                on_gui(lambda: refresh("win"))
            except Exception:  # noqa: BLE001 - 重探没发起：页面留着旧图，下次打开会是新的
                log.info("配置全景：核对 %s 之后没能重探本机一侧", repo, exc_info=True)
            return {"repo": repo, "state": "checked" if ok else "failed"}
        finally:
            running.release()

    run.off_gui = True
    return run


def sync_vault(repos: dict, on_gui: Callable[[Callable[[], object]], object], refresh: Callable[[str], object],
               syncer) -> Callable[[object], dict]:
    """「现在同步」：把一个本地克隆和远端对齐一次——提交本地改动、拉取、推送（``vault_sync.VaultSync.sync``）。

    请求体 ``{repo}``。页面在发之前已经 ``confirm()`` 过，所以这里带 ``approved=True``：有删除、改动很多也照提交
    （点之前待处理里写着几个文件、其中删除几个）。和「现在核对」一样不占界面线程（``off_gui``），只回去读克隆目录和重探。

    回 ``{repo, state, files, deletions, pulled, pushed, conflicts}``，``state`` 就是同步器的结果：``synced`` / ``noop`` /
    ``conflict``（有冲突、已撤回，本地提交留着）/ ``blocked``（克隆在半截状态）/ ``failed`` / ``busy`` / ``missing``。
    真的跑过（不是 ``busy`` / ``missing``）就重探本机一侧。失败原因在运行记录和日志里，不回给页面。
    """
    def run(body) -> dict:
        repo = body.get("repo") if isinstance(body, dict) else None
        if not isinstance(repo, str) or repo not in repos:
            raise ActionError(400, "bad_repo")
        out = syncer.sync(str(on_gui(repos[repo])), repo=repo, trigger="manual", approved=True)
        if out.state == "failed":
            log.warning("配置全景：同步 %s 没办成：%s", repo, out.error[-200:])
        if out.state not in ("busy", "missing"):
            try:
                on_gui(lambda: refresh("win"))
            except Exception:  # noqa: BLE001 - 重探没发起：页面留着旧图，下次打开会是新的
                log.info("配置全景：同步 %s 之后没能重探本机一侧", repo, exc_info=True)
        return {"repo": repo, "state": out.state, "files": out.files, "deletions": out.deletions, "pulled": out.pulled,
                "pushed": out.pushed, "conflicts": out.conflicts}

    run.off_gui = True
    return run


class ActionError(Exception):
    """动作没办成。``status`` 和 ``code`` 给页面。"""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


def repair_hooks(manager_of: Callable[[], object | None], refresh: Callable[[str], object]) -> Callable[[object], dict]:
    """「修复」动作的处理器。``manager_of()`` 给当前的 ``AgentLinkManager``（没有就是 None）；``refresh(side)`` 让服务只重探那一侧。

    本机那条当场写完 → ``installed``，马上重探本机一侧（那条断线要变回来，而 hooks 在不在是探针读文件得来的）。
    WSL 那条要起 wsl.exe，管理器后台装 → ``pending``；装完它发 ``install_finished``，接到成功的那一下再重探 WSL 一侧。
    同一个管理器只接一次信号（WeakSet 记着），免得点两次修复、装完重探两遍。写不进去 → ``failed``，什么都不重探。
    """
    watched: "weakref.WeakSet" = weakref.WeakSet()

    def on_finished(agent_key: str, ok: bool, _message: str, _token: int) -> None:
        if ok and agent_key == "claude_wsl":
            refresh("wsl")

    def run(body) -> dict:
        agent = body.get("agent") if isinstance(body, dict) else None
        if not isinstance(agent, str) or agent not in HOOKED_SIDES:
            raise ActionError(400, "bad_agent")
        manager = manager_of()
        if manager is None:
            raise ActionError(503, "no_manager")
        state = str(manager.install_hooks_consented(agent))
        if state == "installed":
            refresh(HOOKED_SIDES[agent])
        elif state == "pending" and manager not in watched:
            watched.add(manager)
            manager.install_finished.connect(on_finished)
        return {"agent": agent, "state": state}

    return run
