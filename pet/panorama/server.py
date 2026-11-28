# -*- coding: utf-8 -*-
"""配置全景的本机回环服务：页面今后经它读写肥鱼（决定见 docs/adr/0014-panorama-becomes-the-console.md）。

**只用标准库、不碰 Qt。** 这个模块只管三件事：

1. 生命周期：只绑 ``127.0.0.1``；跟着肥鱼起停，不空闲自停。给了会话文件（``session``）就把端口和令牌记在里面，
   肥鱼重启后用回同一个端口、同一个令牌——开着的标签页自己重连得上；端口被别人占了就换一个空的，令牌照旧。
   没给会话文件时端口由系统随机给、每次启动换一个令牌。
2. 守门：每个请求先过同一串检查（见 ``PanoramaServer._check``），通过了才交给路由表里的处理函数。
3. 路由表 ``Router``：一条 = (方法, 路径模板) → 处理函数。以后的接口（读图、读写设置、读写文件、动作）
   都往表里加，不改这里的守门逻辑。

为什么查得这么严：页面能改的东西里有提示词，提示词会交给带工具的 AI 执行。浏览器里任何一个网页都能往
回环地址发请求，所以「只听本机」不构成边界——

- Host 必须正好是 ``127.0.0.1:<端口>``：挡 DNS 重绑定（浏览器连的是回环地址，Host 却是攻击者的域名）；
- 接口必须带自定义请求头里的令牌：跨站请求带不上自定义头（要先发预检，而预检我们一律不答应）；
- 带了 Origin 就必须是自己；浏览器标了 ``Sec-Fetch-Site`` 就必须是 same-origin；写请求必须有 Origin；
- 写请求只收 JSON：普通表单能跨站直接提交，JSON 不能；
- 不发任何 CORS 头；页面带只许同源的内容策略。

令牌放在页面网址的 ``#`` 片段里交给页面：片段不发给服务器、不进 Referer、不进访问日志。会话文件在肥鱼的数据目录里：
浏览器里的网页读不到磁盘，所以记在那里不放宽上面任何一道门；本机别的程序本来就读得到肥鱼的配置。
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
TOKEN_HEADER = "X-Panorama-Token"
MAX_BODY = 17 << 20                 # 写请求正文上限 17 MiB：随手记一次最多 4 张图、每张 3 MB（base64 胀 4/3）；
                                    # 设置和记忆文件都远小于它。只认本机回环、要令牌，正文读进内存一次就丢
POLL_SECONDS = 2.0                  # 服务线程多久醒一次看「该不该停」；stop() 会敲门叫醒它，这个间隔只是兜底
REQUEST_TIMEOUT = 10.0              # 一条连接最多占一个线程这么久（挡只连不发的慢连接）

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
WRITE_METHODS = frozenset(METHODS) - {"GET"}
JSON_TYPE = "application/json; charset=utf-8"

#: 每个响应都带（包括被拒的）。没有任何 Access-Control-* 头是有意的。
HARDENING_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    # 脚本、样式表、图片、连接一律只许同源。唯一放开的是「内联 style 属性」：页面脚本用它给磁贴定位、
    # 传颜色变量。样式属性执行不了代码，而外部资源已被 default-src 挡住，所以它也带不走数据。
    "Content-Security-Policy": ("default-src 'self'; style-src-attr 'unsafe-inline'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
}

_SEGMENT = r"[A-Za-z0-9_-][A-Za-z0-9._-]*"          # 路径参数：一段，不含 / % \，不能以点开头（所以不会是 ..）
_PATTERN = re.compile(r"^/[A-Za-z0-9._/{}-]*$")
_PARAM = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")     # secrets.token_urlsafe 的字母表；会话文件里的令牌不合这个就换新的


def load_session(path: Path) -> tuple[int, str] | None:
    """会话文件里记的 (端口, 令牌)；文件不在、读不了、内容不像样都是 ``None``（调用方换新的）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    port, token = data.get("port"), data.get("token")
    if type(port) is not int or not 1024 <= port <= 65535 or not isinstance(token, str) or not _TOKEN.match(token):
        return None
    return port, token


def save_session(path: Path, port: int, token: str) -> None:
    """先写临时文件再替换：写到一半断电，留下的也是旧的那一份。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    os.replace(temp, path)


class HttpError(Exception):
    """处理函数或守门检查用它提前结束：状态码 + 给页面看的短代码（不带任何内部细节）。"""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: str
    headers: Mapping[str, str]
    body: bytes = b""
    params: Mapping[str, str] = field(default_factory=dict)

    def json(self):
        """写请求的正文（已经保证是 JSON 类型）；解析不了报 400。"""
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HttpError(400, "bad_json") from exc


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = JSON_TYPE

    @classmethod
    def json(cls, data, status: int = 200) -> "Response":
        return cls(status, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), JSON_TYPE)

    @classmethod
    def error(cls, status: int, code: str) -> "Response":
        return cls.json({"error": code}, status)


Handler = Callable[[Request], Response]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    handler: Handler
    public: bool                    # True = 不要令牌（只给不含数据的静态外壳用）
    regex: re.Pattern


class Router:
    """路由表。路径只按登记的模板**整条**匹配，不映射到文件系统，所以没有路径穿越这回事。"""

    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Handler, *, public: bool = False) -> None:
        if method not in METHODS:
            raise ValueError(f"不支持的方法：{method}")
        if not _PATTERN.match(pattern) or "//" in pattern:
            raise ValueError(f"路径模板不合法：{pattern!r}")
        if any(route.method == method and route.pattern == pattern for route in self._routes):
            raise ValueError(f"重复的路由：{method} {pattern}")
        parts = _PARAM.split(pattern)           # 偶数位是字面量，奇数位是参数名
        regex = "".join(re.escape(part) if index % 2 == 0 else f"(?P<{part}>{_SEGMENT})"
                        for index, part in enumerate(parts))
        self._routes.append(Route(method, pattern, handler, public, re.compile(f"^{regex}$")))

    def static(self, path: str, content: bytes | Callable[[], bytes], content_type: str) -> None:
        """不要令牌的静态内容（页面外壳、脚本、样式）。**里面不能有用户数据**——数据一律走要令牌的接口。"""
        produce = content if callable(content) else (lambda: content)
        self.add("GET", path, lambda request: Response(200, produce(), content_type), public=True)

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]]:
        """找不到路径报 404；路径有、方法不对报 405。"""
        known = False
        for route in self._routes:
            found = route.regex.match(path)
            if not found:
                continue
            if route.method == method:
                return route, found.groupdict()
            known = True
        raise HttpError(405 if known else 404, "method_not_allowed" if known else "not_found")


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 上 SO_REUSEADDR 的意思是「别的进程可以再绑同一个端口」，等于让人顶替；不要它。
    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if sys.platform == "win32" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def handle_error(self, request, client_address) -> None:    # 对端中途断开之类：不往 stderr 打堆栈
        log.debug("配置全景服务：连接出错", exc_info=True)


class PanoramaServer:
    """``start()`` 起服务并返回根网址；``stop()`` 停。两者都可重复调用，线程安全。

    ``on_stop`` 在服务停下后调用一次，**在服务线程或调用 stop 的线程上**，里面不要碰 Qt 对象——需要的话发信号。
    ``session``：会话文件的路径（见模块说明）；不给就每次启动随机端口、新令牌。
    """

    def __init__(self, router: Router, *, poll_seconds: float = POLL_SECONDS, session: Path | None = None,
                 on_stop: Callable[[], None] | None = None) -> None:
        self._router = router
        self._poll = float(poll_seconds)
        self._session = Path(session) if session is not None else None
        self._on_stop = on_stop
        self._lock = threading.Lock()
        self._httpd: _Httpd | None = None
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()
        self._token = ""

    # ------------------------------------------------------------ 状态

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    @property
    def bound_address(self) -> tuple[str, int]:
        return tuple(self._httpd.server_address[:2]) if self._httpd else ("", 0)

    @property
    def token(self) -> str:
        return self._token

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}" if self._httpd else ""

    def page_url(self, path: str = "/") -> str:
        """交给浏览器打开的网址：令牌在 ``#`` 片段里。"""
        return f"{self.base_url}{path}#{self._token}"

    # ------------------------------------------------------------ 起停

    def start(self) -> str:
        with self._lock:
            if self._httpd is not None:
                return self.base_url
            owner = self

            class Handler(_RequestHandler):
                server_ref = owner

            remembered = load_session(self._session) if self._session is not None else None
            httpd = None
            if remembered is not None:
                try:
                    httpd = _Httpd((HOST, remembered[0]), Handler)
                except OSError:                     # 上次的端口被别的程序占了：换一个空的，令牌照旧
                    log.info("配置全景服务：上次的端口 %d 被占了，换一个", remembered[0])
            if httpd is None:
                httpd = _Httpd((HOST, 0), Handler)
            httpd.timeout = self._poll
            halt = threading.Event()
            self._httpd, self._halt = httpd, halt
            self._token = remembered[1] if remembered is not None else secrets.token_urlsafe(32)
            if self._session is not None and remembered != (self.port, self._token):
                try:
                    save_session(self._session, self.port, self._token)
                except OSError:                     # 记不下来只是重启后旧标签页接不上，服务照开
                    log.warning("配置全景服务：会话文件写不进去", exc_info=True)
            self._thread = threading.Thread(target=self._serve, args=(httpd, halt), daemon=True,
                                            name="pet-panorama-server")
            self._thread.start()
            log.info("配置全景服务已启动：%s（%s）", self.base_url, "接着上次的端口和令牌" if remembered == (self.port, self._token) else "新端口或新令牌")
            return self.base_url

    def stop(self) -> None:
        with self._lock:
            thread, halt, port = self._thread, self._halt, self.port
        halt.set()
        if thread is None or thread is threading.current_thread():
            return
        if port:
            # 服务线程正睡在「等下一个连接」里，最长要睡满 poll 秒。敲一下门让它立刻醒来看到停止标志——
            # 退出应用时 stop() 在 GUI 线程上，不能让它白等半秒。
            try:
                socket.create_connection((HOST, port), timeout=1.0).close()
            except OSError:
                pass                                # 已经停了，或者刚好在关：都不用管
        thread.join(timeout=max(2.0, self._poll * 2))

    def _serve(self, httpd: _Httpd, halt: threading.Event) -> None:
        try:
            while not halt.is_set():
                httpd.handle_request()              # 最多等 poll 秒；来了请求就另起线程处理
        finally:
            httpd.server_close()
            with self._lock:
                if self._httpd is httpd:
                    self._httpd, self._thread, self._token = None, None, ""
            if self._on_stop is not None:
                try:
                    self._on_stop()
                except Exception:  # noqa: BLE001 - 回调坏了不能让服务线程带着异常退出
                    log.exception("配置全景服务：on_stop 回调出错")

    # ------------------------------------------------------------ 守门与分发

    def handle(self, method: str, target: str, headers: Mapping[str, str], read_body: Callable[[int], bytes],
               httpd: _Httpd) -> Response:
        """一个请求的全部处理；任何出口都是一个 ``Response``。"""
        try:
            route, request = self._check(method, target, headers, read_body, httpd)
            response = route.handler(request)
        except HttpError as exc:
            return Response.error(exc.status, exc.code)
        except Exception:  # noqa: BLE001 - 处理函数的异常不外泄，只进日志
            log.exception("配置全景服务：处理 %s 时出错", method)
            return Response.error(500, "internal_error")
        return response

    def _check(self, method: str, target: str, headers: Mapping[str, str], read_body: Callable[[int], bytes],
               httpd: _Httpd) -> tuple[Route, Request]:
        port = httpd.server_address[1]
        origin = f"http://{HOST}:{port}"
        if headers.get("Host", "") != f"{HOST}:{port}":
            raise HttpError(421, "bad_host")
        if method not in METHODS:
            raise HttpError(405, "method_not_allowed")
        path, _, query = target.partition("?")
        if not path.startswith("/") or path.startswith("//"):
            raise HttpError(400, "bad_path")
        route, params = self._router.match(method, path)

        sent_origin = headers.get("Origin")
        if sent_origin is not None and sent_origin != origin:
            raise HttpError(403, "bad_origin")
        if method in WRITE_METHODS and sent_origin is None:
            raise HttpError(403, "origin_required")
        site = headers.get("Sec-Fetch-Site")
        # 外壳是用户从系统里打开的（none）或页面自己加载的（same-origin）；接口只能是页面自己调的。
        if site is not None and site not in (("same-origin", "none") if route.public else ("same-origin",)):
            raise HttpError(403, "cross_site")
        if not route.public:
            sent = headers.get(TOKEN_HEADER, "")
            token = self._token
            if not token or not hmac.compare_digest(sent.encode("utf-8"), token.encode("utf-8")):
                raise HttpError(401, "bad_token")

        body = b""
        if method in WRITE_METHODS:
            if headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise HttpError(415, "json_only")
            try:
                length = int(headers.get("Content-Length", ""))
            except ValueError:
                raise HttpError(411, "length_required") from None
            if length < 0 or length > MAX_BODY:
                raise HttpError(413, "too_large")
            body = read_body(length)
        return route, Request(method, path, query, headers, body, params)


class _RequestHandler(BaseHTTPRequestHandler):
    server_ref: PanoramaServer
    timeout = REQUEST_TIMEOUT
    server_version = "panorama"
    sys_version = ""
    protocol_version = "HTTP/1.0"                   # 一问一答就关连接：没有连接复用要管

    def _respond(self) -> None:
        response = self.server_ref.handle(self.command, self.path, self.headers, self.rfile.read, self.server)
        self._send(response)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _respond
    do_OPTIONS = do_HEAD = do_TRACE = do_CONNECT = _respond     # 都会在守门里得到 405

    def _send(self, response: Response) -> None:
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for name, value in HARDENING_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)
        except OSError:
            log.debug("配置全景服务：对端提前断开", exc_info=True)

    def send_error(self, code, message=None, explain=None) -> None:
        """请求行都解析不了时基类会走这里；换成和别的出口一样的朴素响应。"""
        self._send(Response.error(int(code), "bad_request"))

    def log_message(self, format, *args) -> None:   # noqa: A002 - 基类的参数名
        log.debug("配置全景服务：%s", format % args)   # 只有请求行和状态码，没有请求头（令牌在头里）
