# -*- coding: utf-8 -*-
"""README 的功能截图：真实的组件 + 演示数据，中 / 英各一套。

用法：``python scripts/capture_readme_shots.py [输出目录] [--only 名字,名字]``，默认输出到
``docs/images/readme/``。

- 只用演示数据：会话标题、简报、通知、提案都是写在本文件里的样例，不读真实的 Claude Code
  记录、通知中心或知识库；数据目录是临时目录（``APPDATA`` 指过去）。
- 用 Qt 的 ``windows`` 平台渲染（离屏平台没有中文字体），窗口先挪到屏幕外再显示，抓完就关，
  不会在桌面上闪一下。
- 肥鱼用角色包里的一帧真画面，经 ``PetSprite`` 自己的绘制（头顶标签、桂冠都是它画的）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_SCALE_FACTOR", "2")       # 2 倍像素：README 里按一半宽度显示，字更清楚
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-readme-")

ROOT = Path(__file__).resolve().parents[1]
#: 用哪份代码渲染：默认本检出；``BFF_CODE_ROOT`` 可指向另一个检出（截还没合进来的界面时用）
CODE_ROOT = Path(os.environ.get("BFF_CODE_ROOT") or ROOT)
sys.path.insert(0, str(CODE_ROOT))

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from pet import i18n  # noqa: E402

OFFSCREEN = QPoint(-20000, -20000)
LANGS = ("en", "zh")


def pump(seconds: float = 0.05) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def grab(widget: QWidget) -> QImage:
    """挪到屏幕外显示、等它排好版，抓下来（带透明）。"""
    widget.move(OFFSCREEN)
    widget.show()
    pump(0.15)
    image = widget.grab().toImage()
    return image


def save(image: QImage, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    image.save(str(path))
    return path


def desktop(width: int, height: int, dpr: float) -> QImage:
    """一块干净的「桌面」：上浅下深的蓝灰渐变。"""
    image = QImage(int(width * dpr), int(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0.0, QColor("#dfe8f1"))
    gradient.setColorAt(1.0, QColor("#a9bccf"))
    painter.fillRect(QRectF(0, 0, width, height), gradient)
    painter.end()
    return image


# ---------------------------------------------------------------- 肥鱼
class _StillClip(QObject):
    """只放一帧的 clip：接口对齐 ``WebMClip`` 里 ``PetSprite`` 用到的那几样。"""

    frameChanged = Signal(int)
    finished = Signal()

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self.image = image

    def currentFrameNumber(self):
        return 0

    def currentImage(self):
        return self.image

    def frameCount(self):
        return 1

    def duration(self):
        return 1.0

    def start(self):
        return True

    def stop(self):
        pass

    def jumpToFrame(self, _index):
        return True

    def set_playback_speed(self, _speed):
        pass


class _StillLibrary:
    def __init__(self, character_id: str, image: QImage) -> None:
        self.character_id = character_id
        self.no_mirror: set[str] = set()
        self._clip = _StillClip(image)

    def movie(self, _name):
        return self._clip


def character_frame(character_id: str, folder: str, index: int = 1) -> QImage:
    """角色包帧序列里的一帧。帧序列是肥鱼第一次运行时从 webm 生成的、不进 git：本检出没有时
    用 ``BFF_FRAMES_ROOT`` 指向一个跑过肥鱼的检出。"""
    roots = [ROOT, Path(os.environ["BFF_FRAMES_ROOT"])] if os.environ.get("BFF_FRAMES_ROOT") else [ROOT]
    base = next((r / "assets" / "characters" / character_id / "frameseq" / folder for r in roots
                 if (r / "assets" / "characters" / character_id / "frameseq" / folder).is_dir()), None)
    if base is None:
        raise SystemExit("找不到帧序列：先在这个检出里跑一次肥鱼，或设 BFF_FRAMES_ROOT 指向跑过的检出")
    clip_dir = sorted(p for p in base.iterdir() if p.is_dir())[0]
    image = QImage(str(clip_dir / f"f_{index:04d}.webp"))
    assert not image.isNull(), clip_dir
    return image


def make_sprite(image: QImage, *, x: float, y: float, scale: float, facing: str, dpr: float,
                caption: str = "", tone: str = "", badge: str = ""):
    from pet.pet_sprite import PetSprite

    sprite = PetSprite(_StillLibrary("shenshen", image), pos=QPointF(x, y), facing=facing, scale=scale)
    sprite.set_dpr(dpr)
    sprite.bind_clip("idle")
    sprite.caption, sprite.caption_tone, sprite.caption_badge = caption, tone, badge
    return sprite


def fish_scene(lang: str, out: Path) -> list[Path]:
    """大肥鱼 + 四只会话小肥鱼（四种状态的头顶标签，一只戴桂冠）。"""
    from pet import catalog

    dpr = 2.0
    width, height = 1000, 350
    image = desktop(width, height, dpr)
    frame = character_frame("shenshen", "idle")
    big = catalog.DEFAULT_SCALE
    small = big / 2
    t = i18n.t
    fish = [
        # (x, y, 缩放, 朝向, 标签, 配色, 记号)
        (0, 70, big, "right", "", "", ""),
        (420, 0, small, "left", f"{DEMO[lang]['s1']} · {t('session.phase.working')}", "working", "crown"),
        (720, 10, small, "right", f"{DEMO[lang]['s2']} · {t('session.phase.waiting')}", "", ""),
        (440, 170, small, "right", f"{DEMO[lang]['s3']} · {t('session.phase.review')}", "review", ""),
        (740, 180, small, "left", f"{DEMO[lang]['s4']} · {t('session.phase.resting')}", "", ""),
    ]
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for x, y, scale, facing, caption, tone, badge in fish:
        sprite = make_sprite(frame, x=x, y=y, scale=scale, facing=facing, dpr=dpr,
                             caption=caption, tone=tone, badge=badge)
        sprite.paint(painter)
    painter.end()
    return [save(image, out, f"fish-{lang}")]


def avatar_pixmap() -> QPixmap:
    from pet.overlay_shell import _crop_icon_pixmap

    return _crop_icon_pixmap(QPixmap.fromImage(character_frame("shenshen", "idle")), 64)


def letter_logo(letter: str, color: str) -> bytes:
    """演示用的应用图标：一块纯色方块上一个字母（不放真实品牌图标）。"""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QFont

    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    font = QFont("Segoe UI")
    font.setPixelSize(38)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRect(0, 0, 64, 64), int(Qt.AlignmentFlag.AlignCenter), letter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def demo_logos() -> dict[str, bytes]:
    return {"Slack": letter_logo("S", "#4a154b"), "Google Chrome": letter_logo("G", "#1a73e8")}


def demo_sessions(lang: str) -> list[dict]:
    phases = ("working", "waiting", "review", "resting")
    return [{"agent": "claude", "sessionId": f"demo-{i}", "title": DEMO[lang][f"s{i + 1}"], "phase": phase}
            for i, phase in enumerate(phases)]


def island_card(lang: str, out: Path) -> list[Path]:
    """灵动岛（Metro 样式）展开后的卡片：会话汇总、最近的对话、通知。"""
    from pet import claude_hooks
    from pet.config import Config
    from pet.dynamic_island import DynamicIsland

    config = Config(base=Path(tempfile.mkdtemp(prefix="bff-island-")))
    config.set("ui_language", lang)
    config.set("dynamic_island", {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
                                  "info_mode": "usage_today", "show_status": True, "style": "metro",
                                  "x": 400, "y": 300})
    config.set("character", "shenshen")
    config.set_character_alias("shenshen", DEMO[lang]["fish"])
    island = DynamicIsland(config)
    avatar = avatar_pixmap()
    island.set_icon_provider(lambda: avatar)
    sessions = demo_sessions(lang)
    island.set_api_status("ok")
    island.set_usage_info(DEMO[lang]["usage"])
    island.set_session_counts(claude_hooks.session_counts(sessions))
    island.set_briefing_state("unread")
    island.set_personal_state("idle")
    island.set_notification_count(2)
    headline, detail = claude_hooks.summarize_sessions(sessions)
    island.set_balance_info(detail, headline)
    island.set_last_message(DEMO[lang]["last_message"])
    hosts = ("vscode", "terminal", "wsl", "desktop")
    island.set_session_history([
        {"key": ("claude", f"demo-{i}"), "label": DEMO[lang][f"s{i + 1}"], "where": "",
         "host": hosts[i], "path": DEMO[lang]["paths"][i], "ago": DEMO[lang]["ago"][i],
         "live": i < 3, "pinned": i == 0}
        for i in range(4)], is_open=True, max_rows=10)
    island.set_notifications([
        {"key": i + 1, "title": title, "app": app_name, "app_id": app_name, "sender": sender, "message": message,
         "ago": ago, "unread": i == 0, "in_center": True}
        for i, (app_name, title, sender, message, ago) in enumerate(DEMO[lang]["notices"])], is_open=True,
        logos=demo_logos())
    island.set_pet_visible(True)
    island.move(OFFSCREEN)
    island.show()
    pump(0.2)
    island.expand_card()
    pump(1.2)
    shot = island.grab().toImage()
    island.hide()
    dpr = shot.devicePixelRatio()
    margin = 28
    w, h = int(shot.width() / dpr) + 2 * margin, int(shot.height() / dpr) + 2 * margin
    image = desktop(w, h, dpr)
    painter = QPainter(image)
    painter.drawImage(QPointF(margin, margin), shot)
    painter.end()
    return [save(image, out, f"island-{lang}")]


def on_desktop(shots: list[QImage], *, margin: int = 28, gap: int = 16, vertical: bool = False) -> QImage:
    """把几张带透明的抓图并排（或竖排）贴到一块「桌面」上。"""
    dpr = max(s.devicePixelRatio() for s in shots)
    sizes = [(s.width() / s.devicePixelRatio(), s.height() / s.devicePixelRatio()) for s in shots]
    if vertical:
        w = max(sw for sw, _ in sizes) + 2 * margin
        h = sum(sh for _, sh in sizes) + gap * (len(shots) - 1) + 2 * margin
    else:
        w = sum(sw for sw, _ in sizes) + gap * (len(shots) - 1) + 2 * margin
        h = max(sh for _, sh in sizes) + 2 * margin
    image = desktop(int(w), int(h), dpr)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    x = y = margin
    for shot, (sw, sh) in zip(shots, sizes):
        painter.drawImage(QRectF(x, y, sw, sh), shot)
        if vertical:
            y += sh + gap
        else:
            x += sw + gap
    painter.end()
    return image


def session_card(lang: str, out: Path) -> list[Path]:
    """单击会话小鱼弹出的详情卡（Metro）。"""
    from pet.claude_session_info import SessionDetail
    from pet.config import Config
    from pet.session_pet_ui import SessionDetailCard

    config = Config(base=Path(tempfile.mkdtemp(prefix="bff-card-")))
    config.set("ui_language", lang)
    card = SessionDetailCard(config)
    detail = SessionDetail(agent="claude", session_id="0b6c1d2e-demo", title=DEMO[lang]["s1"], project="demo-app",
                           cwd=DEMO[lang]["paths"][0], phase="working", tool="Edit",
                           last_prompt=DEMO[lang]["prompt"], git_branch="feature/settings-save",
                           entrypoint="claude-vscode", model="claude-opus-5-5", effort="high",
                           context_tokens=86000)
    card.show_detail(detail, time.time() - 23 * 60)
    shot = grab(card)
    card.hide()
    return [save(on_desktop([shot]), out, f"session-card-{lang}")]


def toasts(lang: str, out: Path) -> list[Path]:
    """自家的通知弹窗：Slack 同一频道叠成一摞（收起 / 展开），Chrome 一条。"""
    from pet import notification_center as nc
    from pet.notification_toast import ToastCard

    now = time.time()
    logos = demo_logos()
    channel, lines = DEMO[lang]["slack_stack"]
    slack = [nc.Notice(uid=10 + i, app="Slack", app_id="Slack", title=channel, body=line, created=now - (len(lines) - i) * 40,
                       launch=f"slack://channel?team=T0&id=C0&message={i}", activation="protocol")
             for i, line in enumerate(lines)]
    chrome = nc.Notice(uid=20, app="Google Chrome", app_id="Google Chrome", title=DEMO[lang]["chrome"][0],
                       body=DEMO[lang]["chrome"][1], created=now - 300)
    shots = []
    for notices, logo, expanded in ((slack, logos["Slack"], False), (slack, logos["Slack"], True),
                                    ([chrome], logos["Google Chrome"], False)):
        card = ToastCard(notices, logo=logo, theme="dark", seconds=0, animate=False)
        if expanded:
            card.set_expanded(True)
        shots.append(grab(card))
        card.hide()
    return [save(on_desktop(shots, vertical=False), out, f"toasts-{lang}")]


def window_shot(window: QWidget, width: int, height: int) -> QImage:
    window.resize(width, height)
    shot = grab(window)
    window.close()
    return shot


def work_briefing(lang: str, out: Path) -> list[Path]:
    """工作简报窗口：WSL 里登录工作账号的 Claude Code 只读汇总 Jira / PR / Slack / 日程。"""
    from pet import work_briefing as wb
    from pet.work_briefing_ui import WorkBriefingWindow

    summary, markdown = DEMO[lang]["briefing"]
    briefing = wb.Briefing(ok=True, summary=summary, markdown=markdown,
                           generated_at=dt.datetime.now().replace(hour=9, minute=2).isoformat(timespec="seconds"),
                           seconds=52, turns=14, model="claude-sonnet-5-5", effort="medium",
                           tokens_in=48210, tokens_out=1320, cost_usd=0.06)
    window = WorkBriefingWindow(theme="light")
    window.show_briefing(briefing)
    return [save(window_shot(window, 860, 700), out, f"briefing-{lang}")]


def personal_briefing(lang: str, out: Path) -> list[Path]:
    """个人助理的个人简报：肥鱼自己的 Claude 只读地读本地知识库副本。"""
    from pet import personal_briefing as pb
    from pet.personal_ui import meta_line
    from pet.work_briefing_ui import WorkBriefingWindow

    summary, markdown = pb.parse_text(DEMO[lang]["personal"])
    briefing = pb.PersonalBriefing(ok=True, summary=summary, markdown=markdown,
                                   generated_at=dt.datetime.now().replace(hour=8, minute=30).isoformat(timespec="seconds"),
                                   seconds=71.2, turns=7, model="claude-sonnet-5-5", effort="medium",
                                   tokens_in=52340, tokens_out=1480,
                                   files_read=["INDEX.md", "Decisions/2026-10 log.md", "Reading/queue.md"])
    t = i18n.t
    window = WorkBriefingWindow(title=t("personal.app"), regenerate_label=t("personal.button.regenerate"),
                                empty_text=t("personal.empty"), page_label=t("personal.tab.briefing"), theme="dark")
    window.add_action_button(t("personal.button.obsidian"))
    window.show_briefing(briefing, meta=meta_line(briefing))
    return [save(window_shot(window, 860, 700), out, f"personal-{lang}")]


def dashboard(lang: str, out: Path) -> list[Path]:
    """点岛上「今日用量」弹出的近 7 天仪表盘。"""
    from pet import activity_log, claude_week
    from pet.usage_dashboard import DashboardData, build_tiles, footer_text
    from pet.usage_dashboard_ui import UsageDashboardWindow

    today = dt.date.today()
    usage, activity = [], []
    tokens = (1.1, 2.4, 0.6, 3.2, 2.0, 0.3, 2.38)
    prompts = (34, 61, 18, 85, 52, 9, 47)
    spans = ((9.2, 18.6, 410, 150), (8.8, 19.4, 470, 210), (10.1, 16.0, 260, 90), (9.0, 20.5, 520, 240),
             (9.4, 18.1, 400, 160), (None, None, 0, 0), (9.1, 15.4, 300, 120))
    for i in range(7):
        day = today - dt.timedelta(days=6 - i)
        total = int(tokens[i] * 1_000_000)
        usage.append(claude_week.DayUsage(day=day, input=total // 10, output=total // 20,
                                          cache_write=total - total // 10 - total // 20, cache_read=total * 6,
                                          prompts=prompts[i]))
        start, end, active, focus = spans[i]
        origin = activity_log.day_origin(day)
        activity.append(activity_log.DaySummary(
            day=day, start=None if start is None else origin + (start - activity_log.DAY_START_HOUR) * 3600,
            end=None if end is None else origin + (end - activity_log.DAY_START_HOUR) * 3600,
            active_minutes=active, focus_minutes=focus))
    data = DashboardData(usage=usage, activity=activity, recording_since=today - dt.timedelta(days=30))
    window = UsageDashboardWindow()
    window.apply_theme("dark")
    window.set_content(build_tiles(data), footer_text(data))
    window.adjustSize()
    return [save(grab(window), out, f"dashboard-{lang}")]


def memory_distill(lang: str, out: Path) -> list[Path]:
    """会话记忆蒸馏的流程页：从会话记录抽「我说过的话」→ 候选 → 每日蒸馏成提案 → 审核后写进记忆。"""
    from pet import memory_distill as md
    from pet import memory_distill_service as svc
    from pet.memory_distill_ui import MemoryDistillWindow

    now = dt.datetime.now().replace(microsecond=0)
    stats = {"total": 214, "today": 17, "days": 9, "files": 38, "by_side": {md.SIDE_PERSONAL: 131, md.SIDE_WORK: 83},
             "by_tag": {md.TAG_RULE: 22, md.TAG_DECISION: 47, md.TAG_CORRECTION: 31, md.TAG_TASK: 114},
             "last_refresh": (now - dt.timedelta(minutes=12)).isoformat(), "first_day": "", "root": "",
             "keep_days": 90, "enabled": True, "busy": False, "error": "",
             "distill": {"busy": False, "last_run_at": now.replace(hour=21, minute=0).isoformat() if now.hour >= 21
                         else (now - dt.timedelta(days=1)).replace(hour=21, minute=0).isoformat(),
                         "last_error": "", "attempts": 1,
                         "last_result": {"model": "claude-sonnet-5-5", "effort": "medium", "tokens_in": 38211,
                                         "tokens_out": 2410, "seconds": 41, "candidates": 23, "proposals": 4}},
             "proposals": {"pending": 4}, "entries": {"global": 12, "project": 7, "retired": 2},
             "vault": {"state": "", "error": "", "dir": ""}}
    settings = {**md.normalize(None), "work_roots": [r"C:\Users\me\WorkSpace"]}
    window = MemoryDistillWindow(theme="light")
    window.show_stats(stats, settings)
    folder = tempfile.mkdtemp(prefix="bff-place-")         # 入口磁贴要一个存在的目录才是可点的样子
    window.show_places([svc.Place(key, "personal", "folder", folder) for key in svc.PLACE_ORDER])
    rows = [{"time": (now - dt.timedelta(minutes=5 * i)).isoformat(), "tag": tag, "project": project, "text": text,
             "side": md.SIDE_PERSONAL}
            for i, (tag, project, text) in enumerate(DEMO[lang]["candidates"])]
    window.show_candidates(rows)
    return [save(window_shot(window, 700, 900), out, f"distill-{lang}")]


DEMO = {
    "en": {"s1": "Refactor settings page", "s2": "Fix login white screen", "s3": "Write release notes",
           "s4": "Upgrade dependencies", "usage": "Today 2.38M", "fish": "Big Fat Fish",
           "last_message": "Done — the settings page now saves without closing.",
           "paths": [r"C:\Users\me\Github\demo-app", r"C:\Users\me\Github\demo-api", "/home/me/workspace/docs",
                     r"C:\Users\me\Github\demo-app"],
           "ago": ["now", "now", "12 min ago", "2 h ago"],
           "notices": [("Slack", "#release", "Amy", "Build 2.3.0 is green, ready to ship?", "2 min ago"),
                       ("Google Chrome", "mail.example.com", "", "Weekly report is due on Friday", "25 min ago")],
           "prompt": "Add a Save button that writes the config without closing the window, and bind it to Ctrl+S.",
           "slack_stack": ("#release", ["Amy: Build 2.3.0 is green", "Amy: QA signed off on the login fix",
                                        "Ben: Ready to ship?"]),
           "chrome": ("Weekly report", "mail.example.com · Due on Friday, please send it to Amy"),
           "briefing": ("Reply to Ben first; the platform sync is at 15:00.",
                        "## Jira\n"
                        "- 🐞 [DEMO-12](https://example.atlassian.net/browse/DEMO-12) Login page sometimes goes blank · "
                        "`In progress` · High · **updated**\n"
                        "  - QA scenario: Safari, click Sign in twice → blank page; expected the home page.\n"
                        "- [DEMO-9](https://example.atlassian.net/browse/DEMO-9) Rate-limit rollout plan · `In review`\n\n"
                        "## Pull requests\n- [team/api#88](https://github.com/team/api/pull/88) Move /connect behind "
                        "the gateway · review requested\n\n"
                        "## Slack\n- **Waiting on you**: Ben asks how many replicas before the rollout "
                        "[open](https://example.slack.com/archives/C1/p1)\n\n"
                        "## Calendar\n- 15:00 Platform sync\n\n"
                        "## Suggested order\n1. Reply to Ben\n2. Read the new comment on DEMO-12\n3. Review team/api#88\n"),
           "personal": ("Summary: Two reviews are due and the reading list is piling up.\n\n"
                        "## To review\n- 2026-10-20 decision: switch the blog to static hosting — check back today\n\n"
                        "## Reading\n- Chapter 4 of the book on your queue (last opened 9 days ago)\n\n"
                        "## Ideas\n- Motion-sensor light for the balcony\n- Sort old books on the weekend\n\n"
                        "## Suggestions\n1. Spend 20 minutes on the review\n2. Read one chapter after dinner\n"),
           "candidates": [("decision", r"C:\Users\me\Github\demo-app", "Yes, ship the toast stack with Slack grouped by channel."),
                          ("rule", r"C:\Users\me\Github\demo-app", "Always reply in English and keep commits small."),
                          ("correction", r"C:\Users\me\Github\demo-api", "No, don't mock the database in these tests."),
                          ("task", r"C:\Users\me\Github\demo-app", "Add screenshots of the key features to the README.")]},
    "zh": {"s1": "重构设置页", "s2": "修登录页白屏", "s3": "写发布说明", "s4": "升级依赖", "usage": "今日 2.38M", "fish": "大肥鱼",
           "last_message": "改好了——设置页现在可以只保存不关窗。",
           "paths": [r"C:\Users\me\Github\demo-app", r"C:\Users\me\Github\demo-api", "/home/me/workspace/docs",
                     r"C:\Users\me\Github\demo-app"],
           "ago": ["刚刚", "刚刚", "12 分钟前", "2 小时前"],
           "notices": [("Slack", "#发布", "Amy", "2.3.0 构建通过了，可以发吗？", "2 分钟前"),
                       ("Google Chrome", "mail.example.com", "", "周报周五前交", "25 分钟前")],
           "prompt": "加一个「保存」按钮：写入配置但不关窗口，绑定 Ctrl+S。",
           "slack_stack": ("#发布", ["Amy: 2.3.0 构建通过了", "Amy: 登录页的修复 QA 验过了", "Ben: 可以发了吗？"]),
           "chrome": ("周报", "mail.example.com · 周五前发给 Amy"),
           "briefing": ("先回 Ben 的私信，下午三点有平台例会。",
                        "## Jira\n"
                        "- 🐞 [DEMO-12](https://example.atlassian.net/browse/DEMO-12) 登录页偶发白屏 · `进行中` · 高 · **有更新**\n"
                        "  - QA 报的场景：Safari 里连点两次「登录」，页面白屏，预期跳到首页。\n"
                        "- [DEMO-9](https://example.atlassian.net/browse/DEMO-9) 限流上线方案 · `待评审`\n\n"
                        "## PR\n- [team/api#88](https://github.com/team/api/pull/88) 把 /connect 挪到网关后面 · 等你评审\n\n"
                        "## Slack\n- **等你回复**：Ben 问上线前要几个副本 [打开](https://example.slack.com/archives/C1/p1)\n\n"
                        "## 日程\n- 15:00 平台例会\n\n"
                        "## 建议先做\n1. 回 Ben\n2. 看 DEMO-12 的新评论\n3. 评审 team/api#88\n"),
           "personal": ("概要：有两项复盘到期，待读清单越攒越多。\n\n"
                        "## 待复盘\n- 2026-10-20 决定：博客改成静态托管——今天回看\n\n"
                        "## 阅读\n- 清单里那本书的第 4 章（上次打开是 9 天前）\n\n"
                        "## 灵感\n- 阳台换感应灯\n- 周末整理旧书\n\n"
                        "## 建议\n1. 花 20 分钟做复盘\n2. 晚饭后读一章\n"),
           "candidates": [("decision", r"C:\Users\me\Github\demo-app", "好，通知弹窗按 Slack 频道叠放就这么定。"),
                          ("rule", r"C:\Users\me\Github\demo-app", "以后都用中文回复，提交拆小。"),
                          ("correction", r"C:\Users\me\Github\demo-api", "不对，这些测试别 mock 数据库。"),
                          ("task", r"C:\Users\me\Github\demo-app", "README 给关键功能加上截图。")]},
}

SHOTS = {
    "fish": fish_scene,
    "island": island_card,
    "card": session_card,
    "toasts": toasts,
    "briefing": work_briefing,
    "personal": personal_briefing,
    "dashboard": dashboard,
    "distill": memory_distill,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", default=str(ROOT / "docs" / "images" / "readme"))
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    wanted = [name for name in args.only.split(",") if name] or list(SHOTS)
    out = Path(args.out)
    for lang in LANGS:
        i18n.set_language(lang)
        for name in wanted:
            for path in SHOTS[name](lang, out):
                print(path, path.stat().st_size)
    i18n.set_language("zh")


if __name__ == "__main__":
    main()
