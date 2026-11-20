# -*- coding: utf-8 -*-
"""应用里的「打开配置全景」：后台采集、分两段发布、在 GUI 线程打开浏览器。

点一下之后：
1. 第一段采 Windows 这一侧（约 0.15 秒），WSL 那一侧先用上一轮的结果（没有就显示「正在探测…」），
   发布出去并打开浏览器——用户几乎立刻看到图。
2. 第二段去 WSL 里探测（``claude mcp list`` 逐个体检，6 秒上下），探完再发布一次。

**发布**是两件事：把数据交给本机服务（页面带着令牌向 ``/api/graph`` 要），同时写一份离线快照
（``panorama.html``，肥鱼没开时也能看）。浏览器打开的是本机服务的网址；服务起不来时退回打开快照文件。

两段都在一条 daemon 线程里；结果经信号排队回 GUI 线程（``ConfigBackupSync`` 同一个模式）。
配置在 GUI 线程上拷贝一份再交给线程，线程不碰活的 ``Config``。本机服务有自己的线程，只从发布台
（``feed.Feed``）取数据、等数据；每次发布是整份替换，不原地改。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from . import features, probes, render, settings_api, sources
from .actions import ActionError
from .feed import Feed
from .settings_api import Busy

log = logging.getLogger(__name__)
OUT_SUBDIR = "panorama"


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-panorama").start()


def _open_in_browser(target: str) -> bool:
    """``target`` 是本机服务的网址，或者快照文件的路径。"""
    url = QUrl(target) if target.startswith("http://") else QUrl.fromLocalFile(target)
    return QDesktopServices.openUrl(url)


def _secret_get(ref: str) -> str:
    from ..chat.models import SecretStore

    return SecretStore().get(ref)


def _known_group(group_id: str) -> bool:
    """这个组 id 在设置表里吗（网址里只放认识的组名）。"""
    from .. import settings_table

    try:
        settings_table.group(group_id)
    except KeyError:
        return False
    return True


class _GuiCall:
    """请求线程交给界面线程办的一件事，和等它办完用的那把锁。见 ``PanoramaService.on_gui``。"""

    def __init__(self, work: Callable[[], object]) -> None:
        self.work = work
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.started = False
        self.cancelled = False
        self.result: object = None
        self.error: BaseException | None = None


class PanoramaService(QObject):
    """``finished(成功?, 快照路径或出错说明)``：一轮（含 WSL 那一段）结束。"""

    finished = Signal(bool, str)
    _stage = Signal(int, str, str)           # worker 线程 → GUI 线程：(第几轮, "page" | "done" | "error", 路径或说明)
    _call = Signal(object)                   # 请求线程 → GUI 线程：一个 _GuiCall
    GUI_TIMEOUT = 10.0                       # 请求线程等界面线程办一件事，最多等这么久

    def __init__(self, config, *, health: Callable[[], tuple[str, str]] | None = None,
                 secret_get: Callable[[str], str] | None = None, windows: Callable[..., dict] | None = None,
                 wsl: Callable[[], dict] | None = None, write: Callable[[dict, Path], Path] | None = None,
                 open_page: Callable[[str], object] | None = None, spawn: Callable | None = None,
                 server=None, apply: Callable[[], object] | None = None, audit=None,
                 actions: dict | None = None, reports: dict | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._health = health or (lambda: ("unknown", ""))
        self._secret_get = secret_get or _secret_get
        self._windows = windows or probes.windows_side
        self._wsl = wsl or probes.wsl_side
        self._write = write or (lambda facts, out_dir: render.write(sources.build(facts), out_dir))
        self._open_page = open_page or _open_in_browser
        self._spawn = spawn or _spawn_thread
        self._server = server                   # 第一次要开页面时才创建（见 _page_target）
        self._feed = Feed()                     # 发布台：采集线程往上放，本机服务的请求线程来取、来等
        self._generation = 0
        self._busy = False
        self._last_wsl: dict | None = None      # 上一轮 WSL 的结果：下一次打开先拿它垫着
        self._last_wsl_seconds: float | None = None
        self._apply = apply                     # 设置改完之后要跑的应用链（应用传进来：_apply_external_config_change）
        self._audit = audit                     # 审计记录；不给就用数据目录里那一份（第一次用到时才建）
        self.actions: dict = dict(actions or {})   # 页面上的动作：名字 → 处理器（见 actions.py），应用登记
        self._reports: dict = dict(reports or {})  # 报告页：名字 → provider（见 reports.py），应用登记
        self._report_feeds = {name: Feed() for name in self._reports}   # 每份报告自己的发布台（页面挂在上面等更新）
        self._last_published: tuple[dict, Path] | None = None       # 上一次发布用的事实和快照目录：设置改了之后拿它重画
        self._settings_dirty = False            # 设置在一轮采集途中被改过：那一轮回来时要按新设置再发布一次
        self._focus = ""                        # 这次打开要直接翻到的那一组设置（只用一次）
        self._stage.connect(self._on_stage)
        self._call.connect(self._run_call)      # 从别的线程 emit 时自动排队到本对象所在的界面线程
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    @property
    def page_path(self) -> Path:
        return Path(self._config.dir) / OUT_SUBDIR / render.PAGE_NAME

    def is_busy(self) -> bool:
        return self._busy

    def graph_payload(self) -> bytes | None:
        """最近一次发布的数据；还没发布过是 ``None``。"""
        return self._feed.latest()

    def stop(self) -> None:
        """应用要退出：在跑的那一轮作废（它写完的文件留着，只是不再打开浏览器、不再报完成），本机服务停掉。

        先关发布台：页面挂着的「等新数据」请求立刻放回去，服务才停得干净。
        """
        self._generation += 1
        self._busy = False
        self._feed.close()
        for feed in self._report_feeds.values():
            feed.close()
        if self._server is not None:
            try:
                self._server.stop()
            except Exception:  # noqa: BLE001 - 退出路径上不抛
                log.exception("配置全景：停本机服务失败")

    def open(self, focus: str = "") -> bool:
        """采一轮并打开页面；返回是否真的发起了新一轮。上一轮还没跑完时只把现有页面再打开一次。

        ``focus``：页面画完就直接翻到的那一组设置（设置表里的组 id）。不在设置表里的不认，当没给。
        """
        self._focus = focus if focus and _known_group(focus) else ""
        if self._busy:
            if self._feed.latest() is not None or self.page_path.is_file():
                self._open_page(self._page_target(str(self.page_path)))
            return False
        try:
            cfg = copy.deepcopy(self._config.data)
            cfg_path, out_dir = Path(self._config.path), self.page_path.parent
            health = tuple(self._health())
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让菜单项抛异常
            log.exception("配置全景：读取配置失败")
            return False
        self._generation += 1
        generation = self._generation
        previous, previous_seconds = self._last_wsl, self._last_wsl_seconds
        self._busy = True

        def emit(stage: str, text: str) -> None:
            try:
                self._stage.emit(generation, stage, text)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        def run() -> None:
            try:
                # 本机服务的模块在这条后台线程上先载入（首次约 30 毫秒）：等 GUI 线程要起服务时已经在缓存里了
                from . import routes, server  # noqa: F401

                facts = self._windows(cfg, cfg_path=cfg_path, secret_get=self._secret_get, api_health=health)
                if previous is not None:
                    facts["wsl"], facts["refreshing"] = previous, True
                    if previous_seconds is not None:
                        facts["timing"]["wsl_s"] = previous_seconds
                else:
                    facts["wsl"] = {"pending": True}
                emit("page", self._publish(facts, out_dir))
            except Exception as exc:  # noqa: BLE001 - 第一段就失败：没有页面可看
                log.exception("配置全景：采集失败")
                emit("error", f"{type(exc).__name__}: {exc}")
                return
            started = time.perf_counter()
            try:
                wsl = self._wsl()
            except Exception as exc:  # noqa: BLE001 - 探针自己把失败折成了字典；这里兜住意料之外的
                log.exception("配置全景：WSL 探测失败")
                wsl = {"error": f"{type(exc).__name__}: {exc}"}
            seconds = round(time.perf_counter() - started, 2)
            facts.pop("refreshing", None)
            facts["wsl"] = wsl
            facts["timing"]["wsl_s"] = seconds
            try:
                path = self._publish(facts, out_dir)
            except Exception as exc:  # noqa: BLE001
                log.exception("配置全景：写页面失败")
                emit("error", f"{type(exc).__name__}: {exc}")
                return
            if generation == self._generation:      # 作废的那一轮不留结果给下一次垫底
                self._last_wsl, self._last_wsl_seconds = wsl, seconds
            emit("done", path)

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("配置全景：启动线程失败")
            self._busy = False
            return False
        return True

    def _publish(self, facts: dict, out_dir: Path) -> str:
        """（worker 线程）写离线快照，再把同一份事实交给本机服务。返回快照路径。

        先写文件后发布：页面看到新的 ``revision`` 时，快照也已经是新的了。发布会叫醒页面挂着的「等新数据」请求。
        """
        path = str(self._write(facts, out_dir))
        self._feed.publish(lambda revision: render.payload(sources.build(facts), revision=revision))
        self._last_published = (dict(facts), Path(out_dir))
        return path

    # ------------------------------------------------------------ 设置：读、改、审计（本机服务的请求线程来调）

    def on_gui(self, work: Callable[[], object]):
        """在界面线程上跑 ``work`` 并把结果带回来。``Config`` 只许界面线程碰，请求线程要读写设置都经这里。

        已经在界面线程上就直接跑。否则排一个队列信号，在这里等，最多 ``GUI_TIMEOUT`` 秒：

        - 等到了：返回结果，或者把 ``work`` 抛的异常原样抛出来；
        - 没等到、而且那边还没开始：把这次调用作废，抛 ``Busy``。作废之后界面线程轮到它也不会再跑——
          不然页面以为没改成，过一会儿设置却自己变了；
        - 没等到、但那边已经在跑了：接着等它跑完（一次落盘是毫秒级的），不撒手。
        """
        if QThread.currentThread() is self.thread():
            return work()
        call = _GuiCall(work)
        try:
            self._call.emit(call)
        except RuntimeError:                        # 应用正在退出：本对象已销毁
            raise Busy() from None
        if not call.done.wait(self.GUI_TIMEOUT):
            with call.lock:
                call.cancelled = not call.started
            if call.cancelled or not call.done.wait(self.GUI_TIMEOUT):
                raise Busy()
        if call.error is not None:
            raise call.error
        return call.result

    def _run_call(self, call: "_GuiCall") -> None:
        """（界面线程）跑一个排过来的调用；已经被等的人作废了就不跑。"""
        with call.lock:
            if call.cancelled:
                return
            call.started = True
        try:
            call.result = call.work()
        except BaseException as exc:  # noqa: BLE001 - 原样带回给等着的请求线程
            call.error = exc
        finally:
            call.done.set()

    def _audit_log(self):
        if self._audit is None:
            from ..settings_audit import FILE_NAME, AuditLog

            self._audit = AuditLog(Path(self._config.dir) / FILE_NAME)
        return self._audit

    def read_settings(self, group_id: str) -> dict:
        return self.on_gui(lambda: settings_api.read(self._config, group_id))

    def write_settings(self, group_id: str, body) -> dict:
        return self.on_gui(lambda: self._write_settings(group_id, body))

    def read_audit(self, limit: int) -> list[dict]:
        """审计记录只读文件，不碰 ``Config``：就在请求线程上读。"""
        return self._audit_log().read(limit)

    def run_action(self, name: str, body) -> dict:
        """页面上的一个动作（``POST /api/actions/<名字>``）：在界面线程上跑登记好的处理器。不认识的名字 404；
        处理器自己的拒绝（``ActionError``）原样回去；意料之外的异常记日志、回 500。"""
        return self.on_gui(lambda: self._run_action(name, body))

    def _run_action(self, name: str, body) -> dict:
        handler = self.actions.get(str(name))
        if handler is None:
            raise ActionError(404, "unknown_action")
        try:
            out = handler(body)
        except ActionError:
            raise
        except Exception:  # noqa: BLE001 - 处理器出错不能把连接挂死；页面要一个明确的回答
            log.exception("配置全景：动作 %s 出错", name)
            raise ActionError(500, "action_failed") from None
        log.info("配置全景：动作 %s 完成（%s）", name, out.get("state", "ok") if isinstance(out, dict) else "ok")
        return out

    def refresh(self, side: str) -> bool:
        """（界面线程）只重探一侧、不开浏览器，再发布一次。装完 hooks 之后用：那条断线要变回来，而 hooks 在不在是探针
        读文件得来的，``_republish`` 只重读功能、不重探。返回是否发起了。

        一轮完整采集正在路上就不另起（它回来时自带新状态）；还没发布过也不起（没有页面在看）。``win`` 一侧重探完
        接上上一次的 WSL 结果和它的耗时；``wsl`` 一侧只换那一半。
        """
        if side not in ("win", "wsl") or self._busy or self._last_published is None:
            return False
        facts, out_dir = self._last_published
        try:
            cfg = copy.deepcopy(self._config.data)
            cfg_path, health = Path(self._config.path), tuple(self._health())
        except Exception:  # noqa: BLE001
            log.exception("配置全景：读取配置失败")
            return False
        generation = self._generation

        def run() -> None:
            try:
                if side == "win":
                    fresh = self._windows(cfg, cfg_path=cfg_path, secret_get=self._secret_get, api_health=health)
                    fresh["wsl"] = facts.get("wsl", {"pending": True})
                    if "wsl_s" in facts.get("timing", {}):
                        fresh.setdefault("timing", {})["wsl_s"] = facts["timing"]["wsl_s"]
                else:
                    fresh = {**facts, "wsl": self._wsl()}
                if generation != self._generation:      # 期间开了新的一轮：它的结果更新
                    return
                self._publish(fresh, out_dir)
                log.info("配置全景：重探了 %s 一侧，页面已更新", side)
            except Exception:  # noqa: BLE001 - 重探失败：页面留着上一份
                log.exception("配置全景：重探 %s 一侧失败", side)

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("配置全景：启动线程失败")
            return False
        return True

    def _write_settings(self, group_id: str, body) -> dict:
        """（界面线程）改一组设置。真的改了东西之后：跑应用链，再把图上的功能磁贴换成新值发布出去。"""
        out = settings_api.write(self._config, group_id, body, audit=self._audit_log())
        if out["changed"]:
            log.info("配置全景：改了设置 %s（%s）", group_id, "、".join(out["changed"]))      # 只记是哪几项，不记值
            if self._apply is not None:
                try:
                    self._apply()
                except Exception:  # noqa: BLE001 - 设置已经存好了；应用链出错不该让页面以为没存上
                    log.exception("配置全景：应用设置改动时出错")
            self._settings_dirty = self._busy       # 有一轮采集正在路上：它是拿旧设置开的头，回来时要再盖一次
            self._republish()
        return out

    def _republish(self) -> None:
        """（界面线程）设置变了：拿上一次发布用的事实，把「功能」那一段按现在的配置重读，再发布一次。不重新探测。"""
        last = self._last_published
        if last is None:
            return
        facts, out_dir = last
        try:
            fresh = {**facts, "features": features.read_all(copy.deepcopy(self._config.data))}
            self._publish(fresh, out_dir)
        except Exception:  # noqa: BLE001 - 重画失败不影响已经存好的设置
            log.exception("配置全景：设置改动后重新发布失败")

    # ------------------------------------------------------------ 报告页（见 reports.py）

    def has_report(self, name: str) -> bool:
        return name in self._reports

    def report(self, name: str, after: int | None, wait_seconds: float) -> bytes | None:
        """（请求线程）一份报告的数据。``after`` 是 None：要现成的，还没有就先到界面线程上做一份；
        否则等比 ``after`` 更新的那份，最多 ``wait_seconds`` 秒，没有就 None。不认识的名字抛 ``ActionError(404)``。"""
        feed = self._report_feeds.get(name)
        if feed is None:
            raise ActionError(404, "unknown_report")
        if after is None:
            if feed.latest() is None:
                self.on_gui(lambda: self.publish_report(name, force=True))
            return feed.latest()
        return feed.wait_newer(after, wait_seconds)

    def publish_report(self, name: str, *, force: bool = False) -> bool:
        """（界面线程）重做一份报告的数据并发布，页面挂着的「等更新的」请求立刻拿到。

        ``force`` 为假时只在这份报告发布过（有人打开过页面）时才做：生成结束的信号每次都来，没有页面在看就不白做。"""
        feed, provider = self._report_feeds.get(name), self._reports.get(name)
        if feed is None or provider is None or (not force and feed.latest() is None):
            return False
        data = provider()
        feed.publish(lambda revision: render.report_payload(data, revision=revision))
        return True

    def report_watched(self, name: str) -> bool:
        """有没有页面正挂在这份报告上等更新（= 用户正开着那一页看）。"""
        feed = self._report_feeds.get(name)
        return feed is not None and feed.waiting > 0

    def open_report(self, name: str) -> bool:
        """（界面线程）在浏览器里打开一份报告：起本机服务（**不**采集全景那一轮），开 ``/report/<名字>``。
        没登记这个名字、或服务起不来返回 False（报告没有离线快照可退）。"""
        if name not in self._reports:
            return False
        self.publish_report(name, force=True)
        url = self._server_url(f"/report/{name}")
        if not url:
            return False
        self._open_page(url)
        return True

    # ------------------------------------------------------------ 本机服务

    def _server_url(self, path: str) -> str:
        """（GUI 线程）起本机服务（第一次要用时才建），返回带令牌的网址；起不来返回空串（已记日志）。"""
        try:
            if self._server is None:
                from .files import Reader
                from .routes import build_router
                from .server import PanoramaServer

                from ..claude_hooks import run_wsl

                reader = Reader(config_dir=self._config.dir, home=Path.home(), run_wsl=run_wsl)
                self._server = PanoramaServer(build_router(self._feed, files=reader, settings=self))
            self._server.start()
            return self._server.page_url() if path == "/" else self._server.page_url(path)
        except Exception:  # noqa: BLE001 - 端口绑不上之类
            log.exception("配置全景：本机服务起不来")
            return ""

    def _page_target(self, snapshot: str) -> str:
        """（GUI 线程）浏览器该打开什么：本机服务的网址；服务起不来就退回快照文件。"""
        url = self._server_url("/")
        if not url:
            log.warning("配置全景：改开离线快照")
            return snapshot
        # 组名跟在令牌后面，也在 # 片段里：不发给服务器、不进日志；页面取走令牌后整段从地址栏抹掉
        focus, self._focus = self._focus, ""
        return url + (f"&settings={focus}" if focus else "")

    def _on_stage(self, generation: int, stage: str, text: str) -> None:
        if generation != self._generation:
            return
        if self._settings_dirty and stage in ("page", "done"):
            self._republish()                   # 这一轮是拿旧设置开的头：它刚发布的那份按现在的设置再盖一次
        if stage != "page":
            self._settings_dirty = False
        if stage == "page":
            target = self._page_target(text)
            # 网址里的 # 片段是令牌，不进日志
            log.info("配置全景：Windows 一侧已发布，打开浏览器 %s", target.split("#")[0])
            self._open_page(target)
            return
        self._busy = False
        if stage == "error":
            log.warning("配置全景没有生成：%s", text)
        else:
            log.info("配置全景：WSL 一侧探完，页面已更新（WSL 用了 %s 秒）", self._last_wsl_seconds)
        self.finished.emit(stage == "done", text)
