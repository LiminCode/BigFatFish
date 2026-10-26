# -*- coding: utf-8 -*-
"""试 Metro 通知弹窗：示例通知、通知中心里已有的、或者一直盯着新来的。

    .venv\\Scripts\\python.exe tools\\notification_toast_demo.py --list-screens
    .venv\\Scripts\\python.exe tools\\notification_toast_demo.py --sample 4 --corner bottom_left --screen 2
    .venv\\Scripts\\python.exe tools\\notification_toast_demo.py --replay 3 --live

``--screen`` 收 ``primary`` / ``cursor`` / 序号（``--list-screens`` 列出的那个）/ 屏幕名。
``--live`` 每隔 ``--poll`` 秒读一次 Windows 通知中心（所有应用），新来的弹出来；点卡片会经通知中心
跳回原应用（``notification_center.activate``）。Ctrl+C 或 ``--quit-after`` 秒后退出。
``--snap`` 在 ``--snap-after`` 毫秒后把那块屏截下来存成 PNG（自己核对样子用，别提交）。
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import notification_center as nc  # noqa: E402
from pet import notification_toast as nt  # noqa: E402

SAMPLES = [
    ("Mail", "Weekly sync moved", "The weekly sync is now on Thursday at 10:00. Agenda is unchanged."),
    ("Calendar", "Design review in 10 minutes", "Room 3 · bring the latest mockups"),
    ("Chat", "#general", "Alex: lunch at noon? There is a new noodle place right around the corner, "
                         "reviews say the broth is excellent and the queue is short before 12."),
    ("Build", "Pipeline finished", "main · 312 tests passed in 4m 12s"),
    ("Music", "Now playing", "Track 7 — a very long title that should be elided at the end of the second line "
                             "because it simply does not fit"),
]


class Poller(QObject):
    """后台线程读通知中心，结果排队回 GUI 线程。"""

    got = Signal(object, object)

    def __init__(self, seconds: float, apps: list[str]):
        super().__init__()
        self._seconds = seconds
        self._apps = apps or [nc.ALL_APPS]
        self._known: list[nc.Notice] = []
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self.got.connect(self._store)        # 从工作线程发出，自动排队回 GUI 线程

    def start(self):
        self.poll()
        self._timer.start(int(self._seconds * 1000))

    def poll(self):
        if self._busy:
            return
        self._busy = True
        known = list(self._known)

        def run():
            started = time.perf_counter()
            notices, logos = nc.read_toasts(self._apps, want_logos=_all_app_ids(known), known=known)
            print(f"[poll] {len(notices)} in center, {(time.perf_counter() - started) * 1000:.0f} ms", flush=True)
            self.got.emit(notices, logos)

        threading.Thread(target=run, daemon=True).start()

    def _store(self, notices, _logos):
        self._known = notices
        self._busy = False


class _AllIds(set):
    """``want_logos`` 用：认所有应用（每个应用只取一次图标）。"""

    def __contains__(self, item):  # noqa: D105
        return True


def _all_app_ids(_known):
    return _AllIds()


def _screen_choice(raw: str) -> str:
    screens = QApplication.screens()
    if raw.isdigit() and 1 <= int(raw) <= len(screens):
        return screens[int(raw) - 1].name()
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-screens", action="store_true")
    parser.add_argument("--corner", choices=nt.CORNERS, default=nt.DEFAULTS["corner"])
    parser.add_argument("--screen", default=nt.DEFAULTS["screen"])
    parser.add_argument("--theme", choices=nt.THEMES, default="system")
    parser.add_argument("--seconds", type=int, default=nt.DEFAULTS["seconds"])
    parser.add_argument("--max", type=int, default=nt.DEFAULTS["max_visible"])
    parser.add_argument("--sample", type=int, default=0, help="弹几条示例通知")
    parser.add_argument("--stagger", type=int, default=600, help="示例之间隔几毫秒")
    parser.add_argument("--replay", type=int, default=0, help="先把通知中心里最新的几条弹出来")
    parser.add_argument("--live", action="store_true", help="一直盯着通知中心，新来的弹出来")
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--apps", default=nc.ALL_APPS, help="只认这些应用（逗号分隔的名字片段；* = 全部）")
    parser.add_argument("--quit-after", type=float, default=0.0)
    parser.add_argument("--snap", default="")
    parser.add_argument("--snap-after", type=int, default=1500)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.start(200)                 # 让 Python 有机会处理 Ctrl+C
    keepalive.timeout.connect(lambda: None)

    if args.list_screens:
        primary = QApplication.primaryScreen()
        for index, screen in enumerate(QApplication.screens()):
            g = screen.availableGeometry()
            mark = "  (primary)" if screen is primary else ""
            print(f"{nt.screen_label(index, screen)}  name={screen.name()}  "
                  f"available={g.x()},{g.y()} {g.width()}x{g.height()}  dpr={screen.devicePixelRatio()}{mark}")
        return 0

    stack = nt.ToastStack()
    stack.apply_settings({"corner": args.corner, "screen": _screen_choice(args.screen), "theme": args.theme,
                          "seconds": args.seconds, "max_visible": args.max})
    target = stack.target_screen()
    print(f"[toast] corner={args.corner} screen={target.name()} ({target.model()}) "
          f"available={target.availableGeometry().getRect()}", flush=True)

    def on_activated(notice):
        print(f"[toast] clicked uid={notice.uid} app={notice.app}", flush=True)
        if notice.uid < 0:
            return
        threading.Thread(target=lambda: print("[toast] activate ->", nc.activate(notice), flush=True),
                         daemon=True).start()

    stack.activated.connect(on_activated)
    stack.dismissed.connect(lambda notice, reason: print(f"[toast] {reason} uid={notice.uid}", flush=True))

    for index in range(args.sample):
        app_name, title, body = SAMPLES[index % len(SAMPLES)]
        notice = nc.Notice(uid=-(index + 1), app=app_name, app_id="", title=title, body=body, created=time.time())
        QTimer.singleShot(index * args.stagger, lambda n=notice: stack.push(n))

    if args.replay or args.live:
        poller = Poller(args.poll, [a.strip().lower() for a in args.apps.split(",") if a.strip()])
        logos: dict[str, bytes] = {}
        state = {"first": True}

        def on_got(notices, new_logos):
            logos.update({k: v for k, v in new_logos.items() if v})
            if state["first"]:
                state["first"] = False
                latest = sorted(notices, key=lambda n: n.created)[-args.replay:] if args.replay else []
                for n in notices:
                    if n not in latest:
                        stack._seen.add(n.uid)   # 已经在通知中心里的不弹（除了要重放的那几条）
                for n in latest:
                    stack.push(n, logos.get(n.app_id, b""))
                if not args.live:
                    poller._timer.stop()
                return
            for n in sorted(notices, key=lambda n: n.created):
                if stack.push(n, logos.get(n.app_id, b"")):
                    print(f"[live] new from {n.app}", flush=True)

        poller.got.connect(on_got)
        poller.start()

    if args.snap:
        def snap():
            # 只截卡片那一块（外扩一圈），不截整屏：整屏会把后面的窗口内容一起截进来
            cards = stack.visible_cards()
            if not cards:
                print("[snap] no cards on screen", flush=True)
                return
            box = cards[0].frameGeometry()
            for card in cards[1:]:
                box = box.united(card.frameGeometry())
            screen = stack.target_screen()
            box = box.adjusted(-24, -24, 24, 24).intersected(screen.geometry())
            origin = screen.geometry().topLeft()
            screen.grabWindow(0, box.x() - origin.x(), box.y() - origin.y(), box.width(), box.height()).save(args.snap)
            print(f"[snap] {args.snap} {box.getRect()}", flush=True)
        QTimer.singleShot(args.snap_after, snap)

    if args.quit_after > 0:
        QTimer.singleShot(int(args.quit_after * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
