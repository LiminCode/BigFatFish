# -*- coding: utf-8 -*-
"""本机服务的路由表：哪些网址存在、各自交给谁。守门检查不在这里（见 ``server.py``）。

现在有的：

- ``/``、``/app.css``、``/app.js``、``/boot.js``：页面外壳与静态文件，不含用户数据，不要令牌；
- ``GET /api/ping``：探活，也用来告诉服务「页面还开着」；
- ``GET /api/graph``：页面要画的那份数据（图 + 界面文字），要令牌。

以后加接口（读写设置、读写文件、动作）就在 ``build_router`` 里多登记一条，或者拆成各自的登记函数在这里汇总。
"""
from __future__ import annotations

from typing import Callable

from . import render
from .server import JSON_TYPE, HttpError, Request, Response, Router


def build_router(graph_payload: Callable[[], bytes | None]) -> Router:
    """``graph_payload()`` 返回最近一次发布的 ``/api/graph`` 正文；还没有就返回 ``None``。"""
    router = Router()
    router.static("/", lambda: render.shell().encode("utf-8"), "text/html; charset=utf-8")
    for name, content_type in render.ASSETS.items():
        router.static(f"/{name}", lambda name=name: render.asset(name), content_type)

    def ping(request: Request) -> Response:
        return Response.json({"ok": True, "app": "big-fat-fish"})

    def graph(request: Request) -> Response:
        body = graph_payload()
        if body is None:
            raise HttpError(503, "not_ready")
        return Response(200, body, JSON_TYPE)

    router.add("GET", "/api/ping", ping)
    router.add("GET", "/api/graph", graph)
    return router
