# -*- coding: utf-8 -*-
"""工作简报摆在哪：一个带按钮的气泡（一句话概要）+ 一个看全文的窗口。

``WorkBriefingController`` 的宿主是 overlay 壳（只用它的 ``show_alert`` /
``resolve_alert`` / ``show_bubble``），数据来自 ``WorkBriefingService``。

概要用提醒气泡而不是普通气泡：普通气泡几秒就消失，早上那一下人不一定在看；提醒气泡
留到用户点「查看」或「知道了」为止。气泡文字不送语音合成，简报内容也不进聊天窗。

窗口是 **Windows Phone / Metro** 风格（2026-10-15 起，和设置页同一套令牌
``settings_theme_qss.METRO_TOKENS``）：小字的应用名 + 大而轻的 pivot 页头（「简报 / 笔记」）、
平铺的磁贴、方角、2px 描边的倾斜按钮；白天 / 黑夜跟随「外观」里的主题（system / light /
dark），右上角一个按钮可以当场切换并写回那个偏好；文字全部走 ``i18n.t``。
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from . import work_briefing as wb
from .i18n import t
from .settings_theme_qss import METRO_TOKENS
from .settings_widgets import TiltButton, _system_dark

ALERT_ID = "work-briefing"
THEMES = ("system", "light", "dark")

#: 简报窗口在设置页令牌之外多用的几个：链接色、行内代码的小标签
_EXTRA_TOKENS = {
    "light": {"link": "#0a6fd6", "chip": "#e6e6e8", "chip_text": "#1f1f1f"},
    "dark": {"link": "#6cb4ff", "chip": "#38383f", "chip_text": "#e6e6ea"},
}


def briefing_tokens(dark: bool) -> dict:
    key = "dark" if dark else "light"
    return {**METRO_TOKENS[key], **_EXTRA_TOKENS[key]}


#: 兼容：旧名字（按明暗取色板）
_PALETTES = {False: briefing_tokens(False), True: briefing_tokens(True)}


def resolve_dark(theme: str) -> bool:
    """``system`` 跟随系统；别的按字面。"""
    return theme == "dark" or (theme not in ("light",) and _system_dark())


_QSS = """
QWidget#workBriefing {{
    background: {page}; color: {text};
    font-family: "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "PingFang SC", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}}
QLabel#briefingTitle {{ color: {muted}; font-size: 12px; font-weight: 600; letter-spacing: 1px; }}
QLabel#briefingMeta, QLabel#briefingStatus, QLabel#notesHint, QLabel#notesStatus {{ color: {muted}; font-size: 12px; }}
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
QPlainTextEdit#notesInput {{
    background: {field}; color: {text}; border: 2px solid transparent; border-radius: 0;
    padding: 6px 8px; font-size: 13px;
}}
QPlainTextEdit#notesInput:focus {{ border: 2px solid {accent}; }}
QSplitter#notesSplitter::handle {{ background: transparent; width: 8px; }}
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
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#themeToggle {{ border: 2px solid transparent; font-size: 16px; min-width: 30px; padding: 0 6px; }}
QPushButton#themeToggle:hover {{ border-color: {outline}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {divider}; min-height: 24px; border-radius: 0; }}
QScrollBar::handle:vertical:hover {{ background: {outline}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def _meta_line(briefing: wb.Briefing) -> str:
    try:
        when = f"{dt.datetime.fromisoformat(briefing.generated_at):%m-%d %H:%M}"
    except ValueError:
        when = "?"
    return t("briefing.meta", when=when, seconds=f"{briefing.seconds:.0f}")


class WorkBriefingWindow(QWidget):
    """看全文的窗口。``regenerate_requested``：用户点了「重新生成」；``theme_changed(str)``：
    用户点了右上角的白天 / 黑夜（已经应用到窗口，调用方负责存偏好）。"""

    regenerate_requested = Signal()
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, title: str = "", regenerate_label: str = "",
                 empty_text: str = "", busy_text: str = "", page_label: str = "", theme: str = "system") -> None:
        super().__init__(parent, Qt.Window)
        self.setObjectName("workBriefing")
        title = title or t("briefing.app")
        self.setWindowTitle(title)
        self._empty_text, self._busy_text = empty_text or t("briefing.empty"), busy_text or t("briefing.busy")
        self._theme = theme if theme in THEMES else "system"
        self._colors = briefing_tokens(resolve_dark(self._theme))
        self.resize(620, 680)
        self.setMinimumSize(400, 340)

        self.title_label = QLabel(title.upper() if title.isascii() else title, self)
        self.title_label.setObjectName("briefingTitle")
        self.theme_btn = TiltButton("", self)
        self.theme_btn.setObjectName("themeToggle")
        self.theme_btn.setToolTip(t("briefing.theme.toggle"))
        self.theme_btn.setAccessibleName(t("briefing.theme.toggle"))
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.meta_label = QLabel("", self)
        self.meta_label.setObjectName("briefingMeta")
        self.meta_label.setWordWrap(True)
        self.body = QTextBrowser(self)
        self.body.setObjectName("briefingBody")
        self.body.setOpenExternalLinks(True)   # 工单 / PR / 消息的链接交给系统浏览器
        self.body.setAccessibleName(t("briefing.body_name"))
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("briefingStatus")
        self.status_label.setWordWrap(True)
        self.regenerate_btn = TiltButton(regenerate_label or t("briefing.button.regenerate"), self)
        self.regenerate_btn.setAccessibleDescription(t("briefing.button.regenerate_hint"))
        self.regenerate_btn.clicked.connect(self.regenerate_requested)
        self.close_btn = TiltButton(t("briefing.button.close"), self)
        self.close_btn.clicked.connect(self.close)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.theme_btn, 0, Qt.AlignmentFlag.AlignRight)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.regenerate_btn)
        buttons.addWidget(self.close_btn)
        self.buttons_layout = buttons
        # 简报那一页；别的功能（工作笔记）用 add_tab 挂成第二页。pivot 页头一直显示（哪怕只有一页）
        self.briefing_page = QWidget(self)
        page = QVBoxLayout(self.briefing_page)
        page.setContentsMargins(0, 8, 0, 0)
        page.setSpacing(8)
        page.addWidget(self.meta_label)
        page.addWidget(self.body, 1)
        page.addLayout(buttons)
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("briefingTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.briefing_page, page_label or t("briefing.tab.briefing"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)
        self.apply_theme(self._theme)

    # ---------------------------------------------------------- 页
    def add_action_button(self, label: str, hint: str = "") -> TiltButton:
        """简报页底部、「重新生成」左边再加一个按钮（个人助理的「在 Obsidian 打开」）。"""
        button = TiltButton(label, self)
        if hint:
            button.setAccessibleDescription(hint)
        self.buttons_layout.insertWidget(self.buttons_layout.indexOf(self.regenerate_btn), button)
        return button

    def add_tab(self, label: str, widget: QWidget) -> None:
        self.tabs.addTab(widget, label)
        apply = getattr(widget, "apply_theme", None)
        if callable(apply):
            apply(self._colors)

    def select_tab(self, label: str) -> bool:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == label:
                self.tabs.setCurrentIndex(index)
                return True
        return False

    # ---------------------------------------------------------- 主题
    @property
    def theme(self) -> str:
        return self._theme

    @property
    def is_dark(self) -> bool:
        return bool(self.property("settingsDark"))

    @property
    def colors(self) -> dict:
        return self._colors

    def apply_theme(self, theme: str) -> None:
        """换色板：整扇窗口的样式表、正文里的链接 / 小标签、挂上来的页。"""
        self._theme = theme if theme in THEMES else "system"
        dark = resolve_dark(self._theme)
        self._colors = briefing_tokens(dark)
        self.setProperty("settingsDark", dark)
        self.setStyleSheet(_QSS.format(**self._colors))
        link_palette = self.body.palette()
        link_palette.setColor(QPalette.ColorRole.Link, QColor(self._colors["link"]))
        self.body.setPalette(link_palette)
        self.theme_btn.setText("☀" if dark else "☾")
        self._decorate()
        for index in range(self.tabs.count()):
            apply = getattr(self.tabs.widget(index), "apply_theme", None)
            if callable(apply):
                apply(self._colors)

    def toggle_theme(self) -> None:
        theme = "light" if resolve_dark(self._theme) else "dark"
        self.apply_theme(theme)
        self.theme_changed.emit(theme)

    # ---------------------------------------------------------- 内容
    def show_briefing(self, briefing: wb.Briefing | None, *, busy: bool = False, error: str = "",
                      meta: str | None = None, busy_text: str = "") -> None:
        """摆上最近一份；``busy`` 时按钮变灰，``error`` 是最近一次失败的原因。

        ``meta`` 覆盖顶部那行元信息（个人助理写模型 / token / 读过的文件），``busy_text`` 覆盖忙碌文案
        （写明正在让哪个模型读）；不传就是建窗口时给的那两句。"""
        busy_text = busy_text or self._busy_text
        if briefing is None:
            self.meta_label.setText("")
            self.body.setPlainText(busy_text if busy else self._empty_text)
        else:
            self.meta_label.setText(meta if meta is not None else _meta_line(briefing))
            self.body.setMarkdown(f"**{briefing.summary}**\n\n{briefing.markdown}")
            self._decorate()
        self.regenerate_btn.setEnabled(not busy)
        if busy:
            self.status_label.setText(busy_text)
        else:
            self.status_label.setText(t("briefing.status.failed", error=error) if error else "")

    def _decorate(self) -> None:
        """排好版之后再上色：链接用主题的链接色，行内代码（工单状态）画成小标签。

        ``setMarkdown`` 之后做而不是靠样式表——Qt 的文档样式表只在导入 HTML 时生效。"""
        document = self.body.document()
        chips, links = [], []
        block = document.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                if fmt.isAnchor():
                    links.append((fragment.position(), fragment.length()))
                elif fmt.fontFixedPitch():
                    chips.append((fragment.position(), fragment.length()))
                it += 1
            block = block.next()
        chip = QTextCharFormat()
        chip.setBackground(QColor(self._colors["chip"]))
        chip.setForeground(QColor(self._colors["chip_text"]))
        chip.setFontFamilies(self.font().families())
        chip.setFontFixedPitch(False)
        link = QTextCharFormat()
        link.setForeground(QColor(self._colors["link"]))
        link.setFontUnderline(False)
        cursor = QTextCursor(document)
        for fmt, spans in ((chip, chips), (link, links)):
            for position, length in spans:
                cursor.setPosition(position)
                cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(fmt)


def theme_preference(config) -> str:
    """「外观」里的主题（system / light / dark）——简报窗口跟它走。"""
    try:
        return str((config.get("context_menu_appearance") or {}).get("theme") or "system")
    except Exception:  # noqa: BLE001
        return "system"


def save_theme_preference(config, theme: str) -> None:
    """窗口上切了白天 / 黑夜：写回同一个偏好（设置页、菜单也跟着变）。"""
    try:
        current = dict(config.get("context_menu_appearance") or {})
        current["theme"] = theme
        config.set("context_menu_appearance", current)
        config.save()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("保存主题偏好失败")


class WorkBriefingController(QObject):
    """把服务的结果摆到宿主上；菜单的几个动作也落在这里。

    ``state_changed(str)``：灵动岛上那个按钮该是什么样——``idle`` 或 ``unread``
    （有一份生成好了、用户还没打开看过）。"""

    state_changed = Signal(str)

    def __init__(self, host, service, parent: QObject | None = None) -> None:
        super().__init__(parent or service)
        self._host = host
        self.service = service
        self.window: WorkBriefingWindow | None = None
        self._unread = False
        #: 建窗口时挂上的别的页：每个回调返回 [(标签, 部件)]（工作笔记用）
        self.tab_providers: list = []
        service.started.connect(self._on_started)
        service.finished.connect(self._on_finished)

    # ---------------------------------------------------------- 菜单动作
    def generate_now(self) -> None:
        if self.service.busy:
            self._host.show_bubble(t("briefing.bubble.busy"), 3200)
        elif self.service.generate_now():
            self._host.show_bubble(t("briefing.bubble.started"), 4000)

    def _make_window(self) -> WorkBriefingWindow:
        return WorkBriefingWindow(theme=theme_preference(self.service._config))

    def open_window(self, tab: str = "") -> None:
        """开窗口；``tab`` 是要切到的标签（空 = 保持原样）。"""
        if self.window is None:
            self.window = self._make_window()
            self.window.regenerate_requested.connect(self.service.generate_now)
            self.window.theme_changed.connect(lambda theme: save_theme_preference(self.service._config, theme))
            for provider in self.tab_providers:
                for label, widget in provider():
                    self.window.add_tab(label, widget)
        self._refresh_window()
        if tab:
            self.window.select_tab(tab)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._set_unread(False)

    @property
    def island_state(self) -> str:
        """灵动岛上的按钮：没开自动生成、也从没生成过的人看不到它（``hidden``）。"""
        if self._unread:
            return "unread"
        if self.service.settings()["enabled"] or self.service.latest() is not None:
            return "idle"
        return "hidden"

    def refresh_state(self) -> None:
        """设置变了（菜单里开 / 关了自动生成）：让岛重新问一次按钮该不该在。"""
        self.state_changed.emit(self.island_state)

    def _set_unread(self, unread: bool) -> None:
        if unread != self._unread:
            self._unread = unread
            self.state_changed.emit(self.island_state)

    # ---------------------------------------------------------- 服务回调
    def _refresh_window(self) -> None:
        if self.window is not None:
            self.window.show_briefing(self.service.latest(), busy=self.service.busy,
                                      error=self.service.last_error())

    def _on_started(self, _manual: bool) -> None:
        self._refresh_window()

    def _on_finished(self, briefing, _manual: bool) -> None:
        self._refresh_window()
        if not briefing.ok:
            self._host.show_bubble(t("briefing.bubble.failed", error=briefing.error), 8000)
            return
        if self.window is not None and self.window.isVisible():
            return  # 用户正开着窗口看：内容已经换成新的了，不用再冒气泡
        self._set_unread(True)   # 点「知道了」只是收起气泡；打开看过才算读了
        self._host.show_alert(
            briefing.summary, subtitle=t("briefing.alert.subtitle"), sticky=True,
            buttons=[(t("briefing.alert.view"), self._on_view), (t("briefing.alert.dismiss"), self._on_dismiss)],
            alert_id=ALERT_ID, priority=1, alert_type="work_briefing",
        )

    def _on_view(self) -> None:
        self._host.resolve_alert(ALERT_ID)
        self.open_window()

    def _on_dismiss(self) -> None:
        self._host.resolve_alert(ALERT_ID)
