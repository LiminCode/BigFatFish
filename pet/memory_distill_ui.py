# -*- coding: utf-8 -*-
"""会话记忆蒸馏的独立页面（Metro、白天 / 黑夜跟简报窗口同一份偏好）：让整条流程**看得见**。

用户 2026-10-30 要的：一个单独页面，有功能说明和流程图、每个 Claude 环境的记忆库快捷入口、Obsidian 入口、
「现在总结」入口、统计入口，设置也要看得见，原始候选库要有链接并注明（本地、不进 git、保留 N 天）。

三页：「流程」（说明 + 六格流程图 + 入口磁贴 + 当前设置）、「候选」（最近抽到的原话，点一条看前后文）、
「统计」。流程图六格里前三格是第一期（会话 → 抽取 → 候选库），后三格（蒸馏 → 审核 → 落盘）标「第二期」，
数字在格子里实时写。点格子就打开它对应的目录。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

import datetime as dt
import html
from typing import Iterable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QScrollArea, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import memory_distill as md
from . import memory_distill_run as run
from . import memory_distill_service as svc
from .i18n import t
from .settings_widgets import TiltButton
from .work_briefing_ui import THEMES, briefing_tokens, resolve_dark, save_theme_preference, theme_preference

STAGES = ("source", "extract", "store", "distill", "review", "sink")
STAGE_PHASE = {"source": 1, "extract": 1, "store": 1, "distill": 2, "review": 2, "sink": 2}   # 第二期做完：都实装了，样式上不再区分
#: 点格子打开什么
STAGE_PLACE = {"source": svc.PLACE_TRANSCRIPTS, "store": svc.PLACE_CANDIDATES, "sink": svc.PLACE_GLOBAL_CLAUDE_MD}
TILE_H = 96
TILE_GAP = 26
COLUMNS = 3
TAG_KEYS = {md.TAG_RULE: "distill.tag.rule", md.TAG_DECISION: "distill.tag.decision",
            md.TAG_CORRECTION: "distill.tag.correction", md.TAG_TASK: "distill.tag.task"}
SIDE_KEYS = {md.SIDE_PERSONAL: "distill.side.personal", md.SIDE_WORK: "distill.side.work", "shared": "distill.side.shared"}
REASON_KEYS = {md.REASON_WSL: "distill.side.reason_wsl", md.REASON_WORK_ROOT: "distill.side.reason_work_root",
               md.REASON_PERSONAL: "distill.side.reason_personal"}
PLACE_KEYS = {
    svc.PLACE_PERSONAL_VAULT: "distill.place.personal_vault", svc.PLACE_WORK_VAULT: "distill.place.work_vault",
    svc.PLACE_WINDOWS_CLAUDE: "distill.place.windows_claude", svc.PLACE_WSL_CLAUDE: "distill.place.wsl_claude",
    svc.PLACE_GLOBAL_CLAUDE_MD: "distill.place.global_claude_md", svc.PLACE_TRANSCRIPTS: "distill.place.transcripts",
    svc.PLACE_CANDIDATES: "distill.place.candidates",
}

_QSS = """
QWidget#memoryDistill {{
    background: {page}; color: {text};
    font-family: "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "PingFang SC", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}}
QLabel#briefingTitle {{ color: {muted}; font-size: 12px; font-weight: 600; letter-spacing: 1px; }}
QLabel#distillIntro, QLabel#briefingStatus, QLabel#distillCaption {{ color: {muted}; font-size: 12px; }}
QLabel#distillSettings {{ background: {tile}; color: {text}; padding: 10px 12px; font-size: 12px; }}
QScrollArea#distillFlowScroll, QWidget#distillFlowBody {{ background: transparent; border: 0; }}
QTabWidget#briefingTabs::pane {{ border: 0; background: transparent; }}
QTabWidget#briefingTabs > QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {muted}; font-size: 28px; font-weight: 300;
    padding: 0 0 6px 0; margin: 0 22px 0 0; border: 0; border-radius: 0;
}}
QTabBar::tab:selected {{ color: {title}; }}
QTabBar::tab:hover:!selected {{ color: {text}; }}
QTextBrowser#briefingBody, QTextBrowser#notesDetail, QListWidget#notesList {{
    background: {tile}; color: {text}; border: 0; border-radius: 0; padding: 12px 14px; font-size: 13px;
}}
QSplitter#notesSplitter::handle {{ background: transparent; height: 8px; }}
QLineEdit#notesInput, QPlainTextEdit#notesInput {{
    background: {field}; color: {text}; border: 2px solid transparent; border-radius: 0; padding: 6px 8px; font-size: 13px;
}}
QLineEdit#notesInput:focus, QPlainTextEdit#notesInput:focus {{ border: 2px solid {accent}; }}
QLabel#distillHead {{ color: {muted}; font-size: 12px; }}
QLabel#distillEvidence {{ background: {tile}; color: {text}; padding: 8px 10px; font-size: 12px; }}
QListWidget#notesList::item {{ padding: 8px 6px; border-radius: 0; }}
QListWidget#notesList::item:selected {{ background: {selected}; color: {selected_text}; }}
QListWidget#notesList::item:hover:!selected {{ background: {tile_hover}; }}
QPushButton {{
    background: transparent; color: {text}; border: 2px solid {outline}; border-radius: 0;
    min-height: 26px; padding: 2px 14px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background: {tile_hover}; }}
QPushButton:pressed {{ background: {outline}; color: {page}; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {disabled}; border-color: {disabled}; }}
QPushButton#placeButton {{ text-align: left; padding: 6px 12px; min-height: 34px; font-weight: 400; }}
QPushButton#themeToggle {{ border: 2px solid transparent; font-size: 16px; min-width: 30px; padding: 0 6px; }}
QPushButton#themeToggle:hover {{ border-color: {outline}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {divider}; min-height: 24px; border-radius: 0; }}
QScrollBar::handle:vertical:hover {{ background: {outline}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def _when(stamp: str, fmt: str = "%m-%d %H:%M") -> str:
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if when.tzinfo is not None:
        when = when.astimezone()
    return when.strftime(fmt)


def stage_values(stats: dict) -> dict[str, str]:
    """每格写什么数字：第一期三格来自候选库统计；第二期三格写「第二期」。"""
    today, total = int(stats.get("today", 0)), int(stats.get("total", 0))
    by_tag = stats.get("by_tag") or {}
    return {
        "source": t("distill.stage.source_value", files=int(stats.get("files", 0))),
        "extract": (t("distill.stage.extract_busy") if stats.get("busy")
                    else t("distill.stage.extract_value", when=_when(stats.get("last_refresh") or "")
                           if stats.get("last_refresh") else t("distill.never"))),
        "store": t("distill.stage.store_value", today=today, total=total,
                   rules=int(by_tag.get(md.TAG_RULE, 0)) + int(by_tag.get(md.TAG_DECISION, 0))
                   + int(by_tag.get(md.TAG_CORRECTION, 0))),
        "distill": _distill_value(stats.get("distill") or {}),
        "review": t("distill.stage.review_value", **{k: int((stats.get("proposals") or {}).get(k, 0))
                                                   for k in ("pending", "accepted", "rejected")}),
        "sink": _sink_value(stats),
    }


def _distill_value(state: dict) -> str:
    if state.get("busy"):
        return t("distill.stage.distill_busy")
    if state.get("last_error"):
        return t("distill.stage.distill_error", error=str(state["last_error"])[:60])
    if not state.get("last_run_at"):
        return t("distill.never")
    last = state.get("last_result") or {}
    return t("distill.stage.distill_value", when=_when(str(state["last_run_at"])), n=int(last.get("proposals", 0)))


def _sink_value(stats: dict) -> str:
    entries = stats.get("entries") or {}
    vault = stats.get("vault") or {}
    text = t("distill.stage.sink_value", g=int(entries.get("global", 0)), p=int(entries.get("project", 0)))
    if vault.get("state") == "pushing":
        text += " · " + t("distill.vault.pushing")
    elif vault.get("state") == "failed":
        text += " · " + t("distill.vault.failed")
    return text


def run_line(stats: dict) -> str:
    """提案页顶上那行：上次总结的模型 / 强度 / token / 秒 / 候选数 → 提案数，或失败原因。"""
    state = stats.get("distill") or {}
    if state.get("busy"):
        return t("distill.run.busy")
    if state.get("last_error"):
        return t("distill.run.error", error=str(state["last_error"])[-160:])
    if not state.get("last_run_at"):
        return t("distill.run.never")
    last = state.get("last_result") or {}
    return t("distill.run.line", when=_when(str(state["last_run_at"]), "%Y-%m-%d %H:%M"), model=last.get("model") or "?",
             effort=last.get("effort") or "?", tokens_in=f"{int(last.get('tokens_in', 0)):,}",
             tokens_out=f"{int(last.get('tokens_out', 0)):,}", seconds=f"{float(last.get('seconds', 0)):.0f}",
             candidates=int(last.get("candidates", 0)), proposals=int(last.get("proposals", 0)))


def proposal_label(item: run.Proposal) -> str:
    scope = t("distill.scope.global") if item.scope == "global" else md.posix_home_label(item.project) or t("distill.scope.project")
    return f"{t(f'distill.action.{item.action}')} · {scope} · {item.title}"


def side_text(row: dict, work_roots: Iterable[str]) -> str:
    """「公司（WSL 路径）」「公司（公司目录）」「个人」——按当前设置现算，改了公司目录列表就跟着变。"""
    reason = md.side_reason(str(row.get("project") or ""), work_roots)
    side = t(SIDE_KEYS[md.SIDE_PERSONAL if reason == md.REASON_PERSONAL else md.SIDE_WORK])
    return side if reason == md.REASON_PERSONAL else t("distill.side.with_reason", side=side, reason=t(REASON_KEYS[reason]))


def row_label(row: dict, work_roots: Iterable[str] = ()) -> str:
    """候选列表里的一行：时间 · 标签 · 侧（为什么） · 项目名 · 原话开头。"""
    text = " ".join(str(row.get("text") or "").split())
    return (f"{_when(row.get('time') or '')} · {t(TAG_KEYS.get(row.get('tag'), 'distill.tag.task'))} · "
            f"{side_text(row, work_roots)} · "
            f"{md.posix_home_label(str(row.get('project') or ''))} · {text[:60]}{'…' if len(text) > 60 else ''}")


def detail_html(row: dict, colors: dict, work_roots: Iterable[str] = ()) -> str:
    """点开一条：Claude 问了什么、我说了什么、在哪个项目 / 会话 / 入口 / 分支、算哪一侧为什么。"""
    esc = html.escape
    muted = colors.get("muted", "#777")
    parts = [f"<p style='color:{muted};font-size:12px;margin:0 0 6px 0'>"
             f"{esc(_when(row.get('time') or '', '%Y-%m-%d %H:%M'))} · "
             f"{esc(t(TAG_KEYS.get(row.get('tag'), 'distill.tag.task')))} · "
             f"{esc(side_text(row, work_roots))}</p>"]
    if row.get("before"):
        parts.append(f"<p style='color:{muted};margin:0 0 4px 0'><b>{esc(t('distill.detail.before'))}</b></p>"
                     f"<p style='margin:0 0 10px 0;white-space:pre-wrap'>{esc(str(row['before']))}</p>")
    parts.append(f"<p style='color:{muted};margin:0 0 4px 0'><b>{esc(t('distill.detail.text'))}</b></p>"
                 f"<p style='margin:0 0 10px 0;white-space:pre-wrap'>{esc(str(row.get('text') or ''))}</p>")
    session = str(row.get("session_id") or "")
    parts.append(f"<p style='color:{muted};font-size:12px;margin:0'>"
                 f"{esc(t('distill.detail.where', project=str(row.get('project') or ''), branch=str(row.get('branch') or '—'), entry=str(row.get('entrypoint') or '—'), session=session[:8]))}</p>")
    return "".join(parts)


def stats_html(stats: dict, colors: dict) -> str:
    esc = html.escape
    muted = colors.get("muted", "#777")
    by_tag = stats.get("by_tag") or {}
    by_side = stats.get("by_side") or {}

    def cell(label: str, value) -> str:
        return (f"<tr><td style='color:{muted};padding:4px 18px 4px 0'>{esc(label)}</td>"
                f"<td style='padding:4px 0'><b>{esc(str(value))}</b></td></tr>")

    rows = [
        cell(t("distill.stats.total"), stats.get("total", 0)),
        cell(t("distill.stats.today"), stats.get("today", 0)),
        cell(t("distill.stats.days"), t("distill.stats.days_value", days=stats.get("days", 0), first=stats.get("first_day") or "—")),
        cell(t("distill.stats.files"), stats.get("files", 0)),
        cell(t("distill.stats.last_refresh"), _when(stats.get("last_refresh") or "", "%Y-%m-%d %H:%M") if stats.get("last_refresh") else t("distill.never")),
        cell(t("distill.side.personal"), by_side.get(md.SIDE_PERSONAL, 0)),
        cell(t("distill.side.work"), by_side.get(md.SIDE_WORK, 0)),
    ]
    rows.extend(cell(t(TAG_KEYS[tag]), by_tag.get(tag, 0)) for tag in md.TAGS)
    rows.append(cell(t("distill.stats.retention"), t("distill.stats.retention_value", days=stats.get("keep_days", md.DEFAULT_KEEP_DAYS))))
    rows.append(cell(t("distill.stats.root"), stats.get("root", "")))
    note = f"<p style='color:{muted};font-size:12px;margin:12px 0 0 0'>{esc(t('distill.candidates.note'))}</p>"
    return f"<table cellspacing='0'>{''.join(rows)}</table>{note}"


def sides_html(settings: dict, stats: dict) -> str:
    """「个人 / 公司怎么分」：三条规则、当前公司目录、两侧各多少条、分开之后各自去哪。"""
    esc = html.escape
    by_side = stats.get("by_side") or {}
    roots = "；".join(settings.get("work_roots") or []) or "—"
    lines = [
        f"<b>{esc(t('distill.sides.title'))}</b>",
        esc(t("distill.sides.rule_wsl")),
        esc(t("distill.sides.rule_root", roots=roots)),
        esc(t("distill.sides.rule_personal")),
        esc(t("distill.sides.counts", personal=by_side.get(md.SIDE_PERSONAL, 0), work=by_side.get(md.SIDE_WORK, 0))),
        esc(t("distill.sides.where")),
    ]
    return "<br>".join(lines)


def settings_html(settings: dict, root: str) -> str:
    esc = html.escape
    lines = [
        f"<b>{esc(t('distill.settings.title'))}</b>",
        esc(t("distill.settings.enabled_on") if settings["enabled"] else t("distill.settings.enabled_off")),
        esc(t("distill.settings.daily_at", time=settings["daily_at"])),
        esc(t("distill.settings.keep_days", days=settings["keep_days"])),
        esc(t("distill.settings.work_roots", roots="; ".join(settings["work_roots"]))),
        esc(t("distill.settings.model", model=settings["model"] or t("distill.settings.same_as_chat"), effort=settings["effort"])),
        esc(t("distill.settings.root", path=root)),
    ]
    return "<br>".join(lines)


class FlowDiagram(QWidget):
    """六格流程图（两行三列），格子里写实时数字；第二期的格子虚线框。``stage_clicked(str)``。"""

    stage_clicked = Signal(str)

    def __init__(self, colors: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = dict(colors)
        self._values: dict[str, str] = {s: "" for s in STAGES}
        self._hover = ""
        self.setMouseTracking(True)
        self.setFixedHeight(TILE_H * 2 + TILE_GAP + 8)      # 固定高：页面不够高时宁可滚动，也不让格子被压扁
        self.setAccessibleName(t("distill.flow.name"))

    def apply_theme(self, colors: dict) -> None:
        self._colors = dict(colors)
        self.update()

    def set_values(self, values: dict[str, str]) -> None:
        self._values.update({k: str(v) for k, v in values.items() if k in self._values})
        self.update()

    def value(self, stage: str) -> str:
        return self._values.get(stage, "")

    def tile_rects(self) -> dict[str, QRect]:
        width = max(1, (self.width() - TILE_GAP * (COLUMNS - 1)) // COLUMNS)
        rects: dict[str, QRect] = {}
        for index, stage in enumerate(STAGES):
            row, col = divmod(index, COLUMNS)
            rects[stage] = QRect(col * (width + TILE_GAP), row * (TILE_H + TILE_GAP), width, TILE_H)
        return rects

    def stage_at(self, pos: QPoint) -> str:
        return next((s for s, r in self.tile_rects().items() if r.contains(pos)), "")

    # -- 画 --
    def paintEvent(self, _event) -> None:  # noqa: N802
        c = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rects = self.tile_rects()
        base = self.font()
        title_font = QFont(base)
        title_font.setPointSizeF(base.pointSizeF() + 1)
        title_font.setWeight(QFont.Weight.DemiBold)
        small = QFont(base)
        small.setPointSizeF(max(7.0, base.pointSizeF() - 1.5))
        for stage in STAGES:
            rect = rects[stage]
            later = STAGE_PHASE[stage] == 2
            hovered = stage == self._hover and stage in STAGE_PLACE
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["tile_hover"] if hovered else c["tile"]))
            painter.drawRect(rect)
            pen = QPen(QColor(c["muted"] if later else c["accent"]), 2)
            if later:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            inner = rect.adjusted(12, 10, -12, -8)
            painter.setFont(small)
            painter.setPen(QColor(c["muted"]))
            painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             f"{STAGES.index(stage) + 1:02d}  {t(f'distill.stage.{stage}_caption')}")
            painter.setFont(title_font)
            painter.setPen(QColor(c["muted"] if later else c["title"]))
            painter.drawText(inner.adjusted(0, 18, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             t(f"distill.stage.{stage}"))
            painter.setFont(small)
            painter.setPen(QColor(c["muted"] if later else c["text"]))
            painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
                             self._values.get(stage, ""))
        # 箭头：同一行相邻格之间一条短线；第一行末到第二行首一条折线
        painter.setPen(QPen(QColor(c["outline"]), 2))
        painter.setBrush(QColor(c["outline"]))
        for index in range(len(STAGES) - 1):
            a, b = rects[STAGES[index]], rects[STAGES[index + 1]]
            if a.top() == b.top():
                y = a.center().y()
                self._arrow(painter, QPoint(a.right() + 3, y), QPoint(b.left() - 3, y))
            else:
                mid_y = a.bottom() + TILE_GAP // 2
                painter.drawLine(a.center().x(), a.bottom() + 3, a.center().x(), mid_y)
                painter.drawLine(a.center().x(), mid_y, b.center().x(), mid_y)
                self._arrow(painter, QPoint(b.center().x(), mid_y), QPoint(b.center().x(), b.top() - 3))
        painter.end()

    @staticmethod
    def _arrow(painter: QPainter, start: QPoint, end: QPoint) -> None:
        painter.drawLine(start, end)
        if start.y() == end.y():
            head = [QRectF(end.x() - 7, end.y() - 5, 7, 10)]
            painter.drawPolygon([head[0].topLeft().toPoint(), head[0].bottomLeft().toPoint(), end])
        else:
            painter.drawPolygon([QPoint(end.x() - 5, end.y() - 7), QPoint(end.x() + 5, end.y() - 7), end])

    # -- 鼠标 --
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        stage = self.stage_at(event.position().toPoint())
        self.setCursor(Qt.CursorShape.PointingHandCursor if stage in STAGE_PLACE else Qt.CursorShape.ArrowCursor)
        if stage != self._hover:
            self._hover = stage
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        stage = self.stage_at(event.position().toPoint())
        if stage:
            self.stage_clicked.emit(stage)
            event.accept()
            return
        super().mousePressEvent(event)


class MemoryDistillWindow(QWidget):
    """独立窗口。信号：``refresh_requested`` / ``distill_requested`` / ``settings_requested`` /
    ``place_requested(key)`` / ``theme_changed(theme)``。"""

    refresh_requested = Signal()
    distill_requested = Signal()
    settings_requested = Signal()
    place_requested = Signal(str)
    review_requested = Signal(str, str, str, str, str)     # id, status, title, why, how
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, theme: str = "system") -> None:
        super().__init__(parent, Qt.Window)
        self.setObjectName("memoryDistill")
        self.setWindowTitle(t("distill.app"))
        self._theme = theme if theme in THEMES else "system"
        self._colors = briefing_tokens(resolve_dark(self._theme))
        self._rows: list[dict] = []
        self._proposals: list[run.Proposal] = []
        self._work_roots: tuple[str, ...] = ()
        self.resize(700, 900)
        self.setMinimumSize(520, 480)

        self.title_label = QLabel(t("distill.app"), self)
        self.title_label.setObjectName("briefingTitle")
        self.theme_btn = TiltButton("", self)
        self.theme_btn.setObjectName("themeToggle")
        self.theme_btn.setToolTip(t("briefing.theme.toggle"))
        self.theme_btn.setAccessibleName(t("briefing.theme.toggle"))
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.theme_btn, 0, Qt.AlignmentFlag.AlignRight)

        # ---- 流程页
        self.intro_label = QLabel(t("distill.intro"), self)
        self.intro_label.setObjectName("distillIntro")
        self.intro_label.setWordWrap(True)
        self.intro_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diagram = FlowDiagram(self._colors, self)
        self.diagram.stage_clicked.connect(self._on_stage)
        self.places_caption = QLabel(t("distill.places.caption"), self)
        self.places_caption.setObjectName("distillCaption")
        self.place_buttons: dict[str, TiltButton] = {}
        places = QGridLayout()
        places.setHorizontalSpacing(10)
        places.setVerticalSpacing(8)
        for index, key in enumerate(svc.PLACE_ORDER):
            button = TiltButton(t(PLACE_KEYS[key]), self)
            button.setObjectName("placeButton")
            button.setAccessibleName(t(PLACE_KEYS[key]))
            button.clicked.connect(lambda _checked=False, key=key: self.place_requested.emit(key))
            self.place_buttons[key] = button
            places.addWidget(button, index // 2, index % 2)
        self.candidates_note = QLabel(t("distill.candidates.note"), self)
        self.candidates_note.setObjectName("distillCaption")
        self.candidates_note.setWordWrap(True)
        # 「个人 / 公司怎么分」（用户 2026-10-31：这个区别要讲细）：规则 + 当前公司目录 + 两侧各多少条
        self.sides_label = QLabel("", self)
        self.sides_label.setObjectName("distillSettings")
        self.sides_label.setTextFormat(Qt.TextFormat.RichText)
        self.sides_label.setWordWrap(True)
        self.sides_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.settings_label = QLabel("", self)
        self.settings_label.setObjectName("distillSettings")
        self.settings_label.setTextFormat(Qt.TextFormat.RichText)
        self.settings_label.setWordWrap(True)
        self.settings_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("briefingStatus")
        self.status_label.setWordWrap(True)
        self.refresh_btn = TiltButton(t("distill.button.refresh"), self)
        self.refresh_btn.setAccessibleDescription(t("distill.button.refresh_hint"))
        self.refresh_btn.clicked.connect(self.refresh_requested)
        self.distill_btn = TiltButton(t("distill.button.distill"), self)
        self.distill_btn.setToolTip(t("distill.button.distill_hint"))
        self.distill_btn.setAccessibleDescription(t("distill.button.distill_hint"))
        self.distill_btn.clicked.connect(self.distill_requested)
        self.settings_btn = TiltButton(t("distill.button.settings"), self)
        self.settings_btn.clicked.connect(self.settings_requested)
        self.close_btn = TiltButton(t("briefing.button.close"), self)
        self.close_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.refresh_btn)
        buttons.addWidget(self.distill_btn)
        buttons.addWidget(self.settings_btn)
        buttons.addWidget(self.close_btn)
        # 流程页内容比窗口高时整页滚动（底部的按钮行固定在滚动区外）
        flow_body = QWidget(self)
        flow_body.setObjectName("distillFlowBody")
        flow = QVBoxLayout(flow_body)
        flow.setContentsMargins(0, 8, 8, 0)
        flow.setSpacing(10)
        flow.addWidget(self.intro_label)
        flow.addWidget(self.diagram)
        flow.addWidget(self.places_caption)
        flow.addLayout(places)
        flow.addWidget(self.candidates_note)
        flow.addWidget(self.sides_label)
        flow.addWidget(self.settings_label)
        flow.addStretch(1)
        self.flow_scroll = QScrollArea(self)
        self.flow_scroll.setObjectName("distillFlowScroll")
        self.flow_scroll.setWidgetResizable(True)
        self.flow_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.flow_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.flow_scroll.setWidget(flow_body)
        flow_page = QWidget(self)
        page = QVBoxLayout(flow_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(8)
        page.addWidget(self.flow_scroll, 1)
        page.addLayout(buttons)

        # ---- 候选页
        self.list = QListWidget(self)
        self.list.setObjectName("notesList")
        self.list.setAccessibleName(t("distill.tab.candidates"))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.currentRowChanged.connect(self._show_row)
        self.detail = QTextBrowser(self)
        self.detail.setObjectName("notesDetail")
        self.detail.setOpenExternalLinks(False)
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setObjectName("notesSplitter")
        splitter.addWidget(self.list)
        splitter.addWidget(self.detail)
        splitter.setSizes([420, 260])
        candidates_page = QWidget(self)
        cand = QVBoxLayout(candidates_page)
        cand.setContentsMargins(0, 8, 0, 0)
        cand.setSpacing(8)
        self.candidates_caption = QLabel("", self)
        self.candidates_caption.setObjectName("distillCaption")
        cand.addWidget(self.candidates_caption)
        cand.addWidget(splitter, 1)

        # ---- 统计页
        self.stats_body = QTextBrowser(self)
        self.stats_body.setObjectName("briefingBody")
        stats_page = QWidget(self)
        stats = QVBoxLayout(stats_page)
        stats.setContentsMargins(0, 8, 0, 0)
        stats.addWidget(self.stats_body, 1)

        # ---- 提案页（第二期）：左边待审列表，右边可改的标题 / 为什么 / 怎么用 + 证据 + 接受 / 拒 / 跳过
        self.run_label = QLabel("", self)
        self.run_label.setObjectName("distillHead")
        self.run_label.setWordWrap(True)
        self.proposal_list = QListWidget(self)
        self.proposal_list.setObjectName("notesList")
        self.proposal_list.setAccessibleName(t("distill.tab.proposals"))
        self.proposal_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.proposal_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.proposal_list.setWordWrap(False)
        self.proposal_list.currentRowChanged.connect(self._show_proposal)
        self.proposal_head = QLabel("", self)
        self.proposal_head.setObjectName("distillHead")
        self.proposal_head.setWordWrap(True)
        self.title_edit = QLineEdit(self)
        self.title_edit.setObjectName("notesInput")
        self.title_edit.setAccessibleName(t("distill.proposal.title"))
        self.why_edit = QPlainTextEdit(self)
        self.why_edit.setObjectName("notesInput")
        self.why_edit.setPlaceholderText(t("distill.proposal.why"))
        self.why_edit.setAccessibleName(t("distill.proposal.why"))
        self.why_edit.setFixedHeight(64)
        self.how_edit = QPlainTextEdit(self)
        self.how_edit.setObjectName("notesInput")
        self.how_edit.setPlaceholderText(t("distill.proposal.how"))
        self.how_edit.setAccessibleName(t("distill.proposal.how"))
        self.how_edit.setFixedHeight(64)
        self.evidence_label = QLabel("", self)
        self.evidence_label.setObjectName("distillEvidence")
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.accept_btn = TiltButton(t("distill.button.accept"), self)
        self.accept_btn.setAccessibleDescription(t("distill.button.accept_hint"))
        self.accept_btn.clicked.connect(lambda: self._review(run.STATUS_ACCEPTED))
        self.reject_btn = TiltButton(t("distill.button.reject"), self)
        self.reject_btn.setAccessibleDescription(t("distill.button.reject_hint"))
        self.reject_btn.clicked.connect(lambda: self._review(run.STATUS_REJECTED))
        self.skip_btn = TiltButton(t("distill.button.skip"), self)
        self.skip_btn.setAccessibleDescription(t("distill.button.skip_hint"))
        self.skip_btn.clicked.connect(lambda: self._review(run.STATUS_SKIPPED))
        self.review_status = QLabel("", self)
        self.review_status.setObjectName("briefingStatus")
        self.review_status.setWordWrap(True)
        review_buttons = QHBoxLayout()
        review_buttons.setSpacing(8)
        review_buttons.addWidget(self.review_status, 1)
        review_buttons.addWidget(self.accept_btn)
        review_buttons.addWidget(self.reject_btn)
        review_buttons.addWidget(self.skip_btn)
        editor = QWidget(self)
        form = QVBoxLayout(editor)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        form.addWidget(self.proposal_head)
        form.addWidget(self.title_edit)
        form.addWidget(self.why_edit)
        form.addWidget(self.how_edit)
        form.addWidget(self.evidence_label)
        form.addLayout(review_buttons)
        proposal_split = QSplitter(Qt.Orientation.Vertical, self)
        proposal_split.setObjectName("notesSplitter")
        proposal_split.addWidget(self.proposal_list)
        proposal_split.addWidget(editor)
        proposal_split.setSizes([300, 380])
        proposals_page = QWidget(self)
        prop = QVBoxLayout(proposals_page)
        prop.setContentsMargins(0, 8, 0, 0)
        prop.setSpacing(8)
        prop.addWidget(self.run_label)
        prop.addWidget(proposal_split, 1)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("briefingTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(flow_page, t("distill.tab.flow"))
        self.tabs.addTab(candidates_page, t("distill.tab.candidates"))
        self.tabs.addTab(proposals_page, t("distill.tab.proposals"))
        self.tabs.addTab(stats_page, t("distill.tab.stats"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)
        self.apply_theme(self._theme)

    # ---------------------------------------------------------- 主题
    @property
    def colors(self) -> dict:
        return self._colors

    @property
    def is_dark(self) -> bool:
        return bool(self.property("settingsDark"))

    def apply_theme(self, theme: str) -> None:
        self._theme = theme if theme in THEMES else "system"
        dark = resolve_dark(self._theme)
        self._colors = briefing_tokens(dark)
        self.setProperty("settingsDark", dark)
        self.setStyleSheet(_QSS.format(**self._colors))
        self.theme_btn.setText("☀" if dark else "☾")
        self.diagram.apply_theme(self._colors)
        self._show_row(self.list.currentRow())

    def toggle_theme(self) -> None:
        theme = "light" if resolve_dark(self._theme) else "dark"
        self.apply_theme(theme)
        self.theme_changed.emit(theme)

    # ---------------------------------------------------------- 内容
    def show_stats(self, stats: dict, settings: dict) -> None:
        self._work_roots = tuple(settings.get("work_roots") or ())
        self.diagram.set_values(stage_values(stats))
        self.stats_body.setHtml(stats_html(stats, self._colors))
        self.settings_label.setText(settings_html(settings, str(stats.get("root") or "")))
        self.sides_label.setText(sides_html(settings, stats))
        self.run_label.setText(run_line(stats))
        self.distill_btn.setEnabled(not (stats.get("distill") or {}).get("busy"))
        self.refresh_btn.setEnabled(not stats.get("busy"))
        if stats.get("error"):
            self.status_label.setText(t("distill.status.error", error=str(stats["error"])[-160:]))
        elif stats.get("busy"):
            self.status_label.setText(t("distill.status.busy"))
        else:
            self.status_label.setText("")

    def show_places(self, places: list) -> None:
        for place in places:
            button = self.place_buttons.get(place.key)
            if button is None:
                continue
            if place.path:
                button.setToolTip(place.path if place.exists else t("distill.place.missing", path=place.path))
                button.setEnabled(place.exists or place.key == svc.PLACE_CANDIDATES)
            else:
                button.setToolTip(t("distill.place.unknown"))
                button.setEnabled(False)

    def show_candidates(self, rows: list[dict]) -> None:
        self._rows = list(rows)
        self.list.blockSignals(True)
        self.list.clear()
        for row in self._rows:
            item = QListWidgetItem(row_label(row, self._work_roots))
            item.setToolTip(" ".join(str(row.get("text") or "").split())[:300])
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.candidates_caption.setText(t("distill.candidates.caption", n=len(self._rows)))
        if self._rows:
            self.list.setCurrentRow(0)
        else:
            self.detail.setPlainText(t("distill.candidates.empty"))

    def show_status(self, text: str) -> None:
        self.status_label.setText(text)

    def select_tab(self, label: str) -> bool:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == label:
                self.tabs.setCurrentIndex(index)
                return True
        return False

    def _show_row(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            self.detail.setHtml(detail_html(self._rows[index], self._colors, self._work_roots))

    def show_proposals(self, items: list) -> None:
        """待审的提案，新一轮的在前。"""
        current = self.current_proposal_id()
        self._proposals = list(items)
        self.proposal_list.blockSignals(True)
        self.proposal_list.clear()
        for item in self._proposals:
            self.proposal_list.addItem(QListWidgetItem(proposal_label(item)))
        self.proposal_list.blockSignals(False)
        index = next((i for i, p in enumerate(self._proposals) if p.id == current), 0)
        if self._proposals:
            self.proposal_list.setCurrentRow(index)
            self._show_proposal(index)
        else:
            self._show_proposal(-1)
        if self.tabs.count() > 2:
            self.tabs.setTabText(2, t("distill.tab.proposals_n", n=len(self._proposals)) if self._proposals else t("distill.tab.proposals"))

    def current_proposal_id(self) -> str:
        index = self.proposal_list.currentRow()
        return self._proposals[index].id if 0 <= index < len(self._proposals) else ""

    def _show_proposal(self, index: int) -> None:
        has = 0 <= index < len(self._proposals)
        for widget in (self.title_edit, self.why_edit, self.how_edit, self.accept_btn, self.reject_btn, self.skip_btn):
            widget.setEnabled(has)
        if not has:
            self.proposal_head.setText(t("distill.proposal.empty"))
            self.title_edit.clear()
            self.why_edit.clear()
            self.how_edit.clear()
            self.evidence_label.setText("")
            return
        item = self._proposals[index]
        where = t("distill.scope.global") if item.scope == "global" else item.project or t("distill.scope.project")
        self.proposal_head.setText(t("distill.proposal.head", action=t(f"distill.action.{item.action}"), where=where,
                                     kind=item.type, when=_when(item.run_at or "", "%m-%d %H:%M"))
                                   + (f"  ·  {t('distill.proposal.replaces', title=item.replaces)}" if item.replaces else ""))
        self.title_edit.setText(item.title)
        self.why_edit.setPlainText(item.why)
        self.how_edit.setPlainText(item.how)
        self.evidence_label.setText(t("distill.proposal.evidence") + "\n" + "\n".join(f"· {e}" for e in item.evidence)
                                    if item.evidence else t("distill.proposal.no_evidence"))

    def _review(self, status: str) -> None:
        pid = self.current_proposal_id()
        if pid:
            self.review_requested.emit(pid, status, self.title_edit.text(), self.why_edit.toPlainText(),
                                       self.how_edit.toPlainText())

    def show_review_status(self, text: str) -> None:
        self.review_status.setText(text)

    def _on_stage(self, stage: str) -> None:
        if stage == "review":
            self.tabs.setCurrentIndex(2)
            return
        if stage == "distill":
            self.distill_requested.emit()
            return
        key = STAGE_PLACE.get(stage)
        if key:
            self.place_requested.emit(key)


class MemoryDistillController(QObject):
    """把服务接到窗口与宿主（气泡）上。窗口按需建一次。"""

    def __init__(self, host, service: svc.MemoryDistillService, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self.window: MemoryDistillWindow | None = None
        service.changed.connect(self._refresh_window)
        service.refreshed.connect(self._on_refreshed)
        service.failed.connect(self._on_failed)
        service.distilled.connect(self._on_distilled)
        service.reviewed.connect(self._on_reviewed)
        service.synced.connect(self._on_synced)

    # ---------------------------------------------------------- 动作
    def refresh_now(self) -> None:
        # 先写「正在扫」再起线程：测试里线程是同步替身，抽完的结果会在 refresh_now 返回前就写好，不能被盖掉
        if self.window is not None and not self.service.busy:
            self.window.show_status(t("distill.status.busy"))
            self.window.refresh_btn.setEnabled(False)
        self.service.refresh_now()

    def open_place(self, key: str) -> None:
        how, target = self.service.open_place(key)
        if how == "missing":
            self._bubble(t("distill.bubble.missing", path=target or t("distill.place.unknown")), 6000)
        elif how == "failed":
            self._bubble(t("distill.bubble.open_failed", path=target), 5000)
        elif how == "folder" and self.service.place(key) is not None and self.service.place(key).kind == "vault":
            self._bubble(t("distill.bubble.obsidian_hint", path=target), 9000)

    def open_settings(self) -> None:
        opener = getattr(self._host, "open_settings_for", None)
        sprite = getattr(self._host, "sprite", None)
        if callable(opener):
            opener(sprite)

    def open_window(self, tab: str = "") -> None:
        if self.window is None:
            config = self.service._config
            self.window = MemoryDistillWindow(theme=theme_preference(config))
            self.window.theme_changed.connect(lambda theme: save_theme_preference(config, theme))
            self.window.refresh_requested.connect(self.refresh_now)
            self.window.place_requested.connect(self.open_place)
            self.window.settings_requested.connect(self.open_settings)
            self.window.distill_requested.connect(self.distill_now)
            self.window.review_requested.connect(self.review)
        self._refresh_window()
        if tab:
            self.window.select_tab(tab)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    # ---------------------------------------------------------- 回调
    def _refresh_window(self) -> None:
        if self.window is None:
            return
        self.window.show_stats(self.service.stats(), self.service.settings())
        self.window.show_places(self.service.places())
        self.window.show_candidates(self.service.recent())
        self.window.show_proposals(self.service.proposals().pending())

    def distill_now(self) -> None:
        if self.service.distilling:
            return
        if self.window is not None:
            self.window.show_status(t("distill.run.busy"))
        self.service.distill_now(manual=True)

    def review(self, pid: str, status: str, title: str, why: str, how: str) -> None:
        self.service.review(pid, status, title=title, why=why, how=how)

    def _on_distilled(self, result, manual: bool) -> None:
        if result.ok:
            text = t("distill.run.done", candidates=result.candidates, proposals=result.proposals, added=result.added)
            if getattr(result, "truncated", False):
                text += " " + t("distill.run.truncated")
        else:
            text = t("distill.run.error", error=result.error[-160:])
        if self.window is not None:
            self.window.show_status(text)
            if manual and result.ok and result.added:
                self.window.tabs.setCurrentIndex(2)
        if not manual and result.ok and result.added:
            self._bubble(t("distill.bubble.proposals", n=result.added), 9000)
        elif not manual and not result.ok:
            self._bubble(t("distill.run.error", error=result.error[-100:]), 6000)

    def _on_reviewed(self, pid: str, applied) -> None:
        if self.window is None:
            return
        if applied is None:
            self.window.show_review_status(t("distill.review.noted"))
        elif applied.error:
            self.window.show_review_status(t("distill.review.failed", error=applied.error[-160:]))
        else:
            targets = []
            if applied.claude_md:
                targets.append(t("distill.review.to_claude_md"))
            if applied.project_file:
                targets.append(t("distill.review.removed" if applied.removed else "distill.review.to_project", path=applied.project_file))
            if applied.vault_written:
                targets.append(t("distill.review.to_vault"))
            self.window.show_review_status(t("distill.review.applied", targets="、".join(targets) or "—"))

    def _on_synced(self, ok: bool, reason: str) -> None:
        if self.window is not None and not ok:
            self.window.show_review_status(t("distill.vault.push_failed", error=reason[-160:]))

    def _on_refreshed(self, added: int) -> None:
        if self.window is not None:
            self.window.show_status(t("distill.status.refreshed", n=added))

    def _on_failed(self, error: str) -> None:
        if self.window is not None:
            self.window.show_status(t("distill.status.error", error=error[-160:]))

    def _bubble(self, text: str, ms: int) -> None:
        show = getattr(self._host, "show_bubble", None)
        if callable(show):
            show(text, ms)
