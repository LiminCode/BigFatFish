# -*- coding: utf-8 -*-
"""本机服务的路由表：哪些网址存在、各自交给谁。守门检查不在这里（见 ``server.py``）。

现在有的：

- ``/`` 和 ``render.ASSETS`` 里登记的静态文件：页面外壳、样式、脚本模块，不含用户数据，不要令牌；
- ``GET /api/ping``：探活；
- ``GET /api/graph``：页面要画的那份数据（图 + 界面文字），要令牌。
  带 ``?after=<编号>`` 就是「等比这一份更新的」：有就立刻给，没有就把请求挂住，最多 ``LONG_POLL_SECONDS`` 秒，
  到时还没有就回 204，页面再来问。页面靠它在数据变了的时候马上知道，而不用隔几秒问一次。

- ``GET /api/files?store=<存储>``、``GET /api/file?store=<存储>&path=<相对路径>``：只读地列出、读取一项存储名下的
  文件，要令牌。能读哪些由 ``files.py`` 把关；这里只把它的拒绝翻成状态码（``not_viewable`` / ``not_found`` → 404，
  ``bad_path`` → 400）。没给读取器（``files=None``）时这两个网址不存在。

以后加接口（读写设置、写文件、动作）就在 ``build_router`` 里多登记一条，或者拆成各自的登记函数在这里汇总。
"""
from __future__ import annotations

from urllib.parse import parse_qs

from . import render
from .feed import Feed
from .files import FileError
from .server import JSON_TYPE, HttpError, Request, Response, Router

#: 一次「等新数据」最多挂多久。比常见的中间环节的空闲超时（30 秒起）短；页面拿到 204 会立刻再来。
LONG_POLL_SECONDS = 25.0


_FILE_ERROR_STATUS = {"not_viewable": 404, "not_found": 404, "bad_path": 400}


def _add_file_routes(router: Router, reader) -> None:
    def one(request: Request, name: str) -> str:
        values = parse_qs(request.query, keep_blank_values=True).get(name)
        return values[-1] if values else ""

    def guarded(call) -> Response:
        try:
            return Response.json(call())
        except FileError as exc:
            raise HttpError(_FILE_ERROR_STATUS.get(exc.code, 400), exc.code) from None

    router.add("GET", "/api/files", lambda request: guarded(lambda: reader.listing(one(request, "store"))))
    router.add("GET", "/api/file", lambda request: guarded(lambda: reader.read(one(request, "store"), one(request, "path"))))


def build_router(feed: Feed, *, files=None, wait_seconds: float = LONG_POLL_SECONDS) -> Router:
    router = Router()
    router.static("/", lambda: render.shell().encode("utf-8"), "text/html; charset=utf-8")
    for name, content_type in render.ASSETS.items():
        router.static(f"/{name}", lambda name=name: render.asset(name), content_type)

    def ping(request: Request) -> Response:
        return Response.json({"ok": True, "app": "big-fat-fish"})

    def graph(request: Request) -> Response:
        after = parse_qs(request.query, keep_blank_values=True).get("after")
        if after is None:
            body = feed.latest()
            if body is None:
                raise HttpError(503, "not_ready")
            return Response(200, body, JSON_TYPE)
        try:
            revision = int(after[-1])
        except ValueError:
            raise HttpError(400, "bad_revision") from None
        body = feed.wait_newer(revision, wait_seconds)
        return Response(200, body, JSON_TYPE) if body is not None else Response(204, b"", JSON_TYPE)

    router.add("GET", "/api/ping", ping)
    router.add("GET", "/api/graph", graph)
    if files is not None:
        _add_file_routes(router, files)
    return router
