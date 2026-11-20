# -*- coding: utf-8 -*-
"""配置全景页面上的**动作**：不是改一项设置，而是请主进程做一件事。现在只有一个——给联动通道装 hooks。

一个动作 = 一个处理器 ``handler(body) -> dict``，由应用构造 ``PanoramaService`` 时登记（``actions={"名字": handler}``），
页面 ``POST /api/actions/<名字>`` 来调；服务把它转到界面线程上跑（和改设置同一条路，见 ``PanoramaService.on_gui``）。
处理器自己校验参数，拒绝就抛 ``ActionError``（状态码 + 代码），意料之外的异常由服务翻成 500 ``action_failed``。

**装 hooks 每次都要用户同意（ADR 0006）。** 同意框在页面上（``repair.js`` 的 ``confirm()``，文案同右键菜单那条路的 Qt 弹框）；
这里拿到的请求就是「用户点了是」，于是只调管理器的「装」那一半（``install_hooks_consented``），不再弹 Qt 的问题框。
打开通道的开关永远只是起监视器，装 hooks 永远是这另一次明确的点击——所以它是独立的 POST，不藏在 PATCH 设置里。
"""
from __future__ import annotations

import weakref
from typing import Callable

#: 要靠 hooks 的两条通道 → 它们在图上的哪一侧（装完重探那一侧）
HOOKED_SIDES = {"claude": "win", "claude_wsl": "wsl"}


def generate_report(generators: dict) -> Callable[[object], dict]:
    """报告页上的「重新生成」。``generators``：报告名 → 返回 ``started`` / ``busy`` / ``failed`` / ``unavailable`` 的函数
    （工作简报的在 ``reports.generate_work_briefing``）。不认识的报告名 400 ``bad_report``。"""
    def run(body) -> dict:
        report = body.get("report") if isinstance(body, dict) else None
        if not isinstance(report, str) or report not in generators:
            raise ActionError(400, "bad_report")
        return {"report": report, "state": str(generators[report]())}
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
