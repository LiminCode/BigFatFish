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
  ``bad_path`` → 400，``unavailable`` → 503：要去 WSL 里读而那边没回话）。没给读取器（``files=None``）时这两个网址不存在。

- ``POST /api/actions/<动作>``：页面上的一个动作（现在只有 ``repair_hooks``：给联动通道装 hooks），要令牌。处理器在
  ``actions.py``，由应用登记进服务；这里只把 ``ActionError`` 翻成状态码。没给设置入口时这个网址也不存在。

- ``GET /report/<名字>``（公开的外壳，不含数据）和 ``GET /api/report/<名字>``（要令牌）：报告页——在浏览器里读一份生成
  出来的内容（现在只有工作简报 ``work_briefing``）。数据接口和 ``/api/graph`` 一样认 ``?after=<编号>`` 等更新的。
  报告由应用登记进服务（``reports.py``）；没登记的名字两个网址都是 404。没给设置入口时这两个网址也不存在。

- ``GET /api/settings/<组>``、``PATCH /api/settings/<组>``、``GET /api/audit``：读、改一组设置，翻审计记录，都要令牌。
  这是本机服务第一批**会改东西**的接口。守门检查（来源、令牌、JSON、大小）在 ``server.py``；改之前的每一道校验在
  ``settings_api.py``；这里只把结果和拒绝翻成响应。拒绝时除了代码还带着页面用得上的东西（哪几项不对、现在的值）。
  没给设置入口（``settings=None``）时这三个网址不存在。

以后加接口（写文件、动作）就在 ``build_router`` 里多登记一条，或者拆成各自的登记函数在这里汇总。
"""
from __future__ import annotations

from urllib.parse import parse_qs

from . import render
from .actions import ActionError
from .feed import Feed
from .files import FileError
from .settings_api import Busy, SettingsError
from .server import JSON_TYPE, HttpError, Request, Response, Router

#: 一次「等新数据」最多挂多久。比常见的中间环节的空闲超时（30 秒起）短；页面拿到 204 会立刻再来。
LONG_POLL_SECONDS = 25.0


_FILE_ERROR_STATUS = {"not_viewable": 404, "not_found": 404, "bad_path": 400, "unavailable": 503}


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


AUDIT_DEFAULT, AUDIT_MAX = 100, 500


def _add_settings_routes(router: Router, port) -> None:
    """``port`` 有三个方法：``read_settings(组)``、``write_settings(组, 请求体)``、``read_audit(条数)``。
    前两个它自己负责转到界面线程上去办（``PanoramaService.on_gui``）。"""
    def guarded(call) -> Response:
        try:
            return Response.json(call())
        except SettingsError as exc:
            return Response.json({"error": exc.code, **exc.detail}, exc.status)
        except Busy:
            return Response.error(503, "busy")

    def audit(request: Request) -> Response:
        asked = parse_qs(request.query).get("limit", [""])[-1]
        limit = int(asked) if asked.isdigit() and 1 <= int(asked) <= AUDIT_MAX else AUDIT_DEFAULT
        return Response.json({"entries": port.read_audit(limit)})

    router.add("GET", "/api/settings/{group}", lambda request: guarded(lambda: port.read_settings(request.params["group"])))
    router.add("PATCH", "/api/settings/{group}",
               lambda request: guarded(lambda: port.write_settings(request.params["group"], request.json())))
    router.add("GET", "/api/audit", audit)


def _add_action_routes(router: Router, port) -> None:
    """``port.run_action(名字, 请求体)``：它自己转到界面线程上去办。"""
    def run(request: Request) -> Response:
        try:
            return Response.json(port.run_action(request.params["name"], request.json()))
        except ActionError as exc:
            return Response.error(exc.status, exc.code)
        except Busy:
            return Response.error(503, "busy")

    router.add("POST", "/api/actions/{name}", run)


def _add_report_routes(router: Router, port, wait_seconds: float) -> None:
    """``port.has_report(名字)``、``port.report(名字, after, 等多久)``：后者自己负责第一次时到界面线程上做一份。"""
    def shell(request: Request) -> Response:
        if not port.has_report(request.params["name"]):
            raise HttpError(404, "not_found")
        return Response(200, render.report_shell().encode("utf-8"), "text/html; charset=utf-8")

    def data(request: Request) -> Response:
        name = request.params["name"]
        if not port.has_report(name):
            raise HttpError(404, "unknown_report")
        after = parse_qs(request.query, keep_blank_values=True).get("after")
        try:
            if after is None:
                body = port.report(name, None, 0.0)
                if body is None:
                    raise HttpError(503, "not_ready")
                return Response(200, body, JSON_TYPE)
            try:
                revision = int(after[-1])
            except ValueError:
                raise HttpError(400, "bad_revision") from None
            body = port.report(name, revision, wait_seconds)
        except ActionError as exc:
            return Response.error(exc.status, exc.code)
        except Busy:
            return Response.error(503, "busy")
        return Response(200, body, JSON_TYPE) if body is not None else Response(204, b"", JSON_TYPE)

    router.add("GET", "/report/{name}", shell, public=True)
    router.add("GET", "/api/report/{name}", data)


def build_router(feed: Feed, *, files=None, settings=None, wait_seconds: float = LONG_POLL_SECONDS) -> Router:
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
    if settings is not None:
        _add_settings_routes(router, settings)
        _add_action_routes(router, settings)
        _add_report_routes(router, settings, wait_seconds)
    return router
