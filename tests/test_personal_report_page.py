# -*- coding: utf-8 -*-
"""个人简报搬到报告页（2026-11-20，M4b 第二项）：同一张报告页多登记一项——provider、「记灵感…」动作、
``PersonalController`` 走浏览器（Qt 壳只剩灵感页）、页面上的副按钮。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import personal_briefing as pb
from pet.panorama import actions, reports
from pet.personal_ui import ALERT_ID, PersonalController
from tests.test_personal_ui import _Fakes, _Host, _service

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


@pytest.fixture
def vault(tmp_path):
    folder = tmp_path / "AI-Base"
    (folder / ".git").mkdir(parents=True)
    (folder / "INDEX.md").write_text("# map", encoding="utf-8")
    return folder


def _config():
    return type("C", (), {"get": staticmethod(lambda key, default=None: {"theme": "light"} if key == "context_menu_appearance" else default)})()


class _Service:
    busy, busy_model, busy_effort = False, "", ""

    def __init__(self, briefing=None, *, error=""):
        self._briefing, self._error, self.asked = briefing, error, 0

    def latest(self):
        return self._briefing

    def last_error(self):
        return self._error

    def generate_now(self):
        self.asked += 1
        return True


BRIEFING = pb.PersonalBriefing(ok=True, summary="先补周五的扫描。", markdown="## 待复习\n- ★★ 风险观察（到期 09-20）\n\n## 今天\n无\n",
                               generated_at="2026-11-20T08:30:00", seconds=63.4, turns=6, model="claude-sonnet-5", effort="medium",
                               tokens_in=48210, tokens_out=1130, files_read=["INDEX.md", "5-Daily/2026-11-20.md"], pull_note="")


# ---------------------------------------------------------------- provider

def test_the_personal_briefing_is_a_second_report_on_the_same_page():
    data = reports.personal_briefing(lambda: _Service(BRIEFING), _config())()
    assert data["id"] == "personal_briefing" and data["title"] == "个人助理" and data["available"] is True and data["theme"] == "light"
    assert data["summary"] == "先补周五的扫描。" and data["generated"].startswith("生成于 11-20 08:30")
    assert [u["key"] for u in data["usage"]] == ["model", "effort", "time", "tokens_in", "tokens_out"], "自己的 key：没有花费这一项"
    assert [(s["source"], s["title"], s["count"]) for s in data["sections"]] == [("other", "待复习", 1), ("other", "今天", 0)]
    assert data["action"] == {"name": "generate_report", "report": "personal_briefing", "label": "重新生成",
                              "hint": "让你自己的 Claude 重新读一遍 AI-Base 并写一份，一两分钟"}
    assert data["actions"] == [{"name": "open_inspiration", "report": "personal_briefing", "label": "记灵感…",
                                "hint": "在肥鱼里打开灵感页：一句话，Ctrl+Enter 记进 AI-Base 并推到 GitHub"}]
    assert data["settings_focus"] == "personal" and data["busy"] is False and data["error"] == ""
    (detail,) = data["details"]
    assert detail["title"] == "这次是怎么生成的（11-20 08:30）"
    assert detail["html"] == ("<p>肥鱼用你自己的 API key 直连 Anthropic，只读本地克隆，没有连接器</p><p>工具 6 轮 · 读了 2 个文件</p>"
                              "<ul><li><code>INDEX.md</code></li><li><code>5-Daily/2026-11-20.md</code></li></ul>")


def test_busy_error_pull_note_and_no_service():
    service = _Service(BRIEFING, error="认证失败")
    service.busy, service.busy_model, service.busy_effort = True, "claude-haiku-5-5", "low"
    data = reports.personal_briefing(lambda: service, _config())()
    assert data["busy"] is True and data["busy_text"] == "正在让 claude-haiku-5-5（思考 low）读 AI-Base，通常一两分钟…"
    assert data["error"] == "上一次没生成出来：认证失败"
    noted = reports.personal_details(pb.PersonalBriefing(ok=True, markdown="x", generated_at="2026-11-20T08:30:00", turns=1,
                                                         pull_note="fatal: could not <read> remote"))
    assert noted[0]["html"].endswith('<p class="bad">git pull 没成功（fatal: could not &lt;read&gt; remote），用的是本地副本</p>')
    gone = reports.personal_briefing(lambda: None, _config())()
    assert gone["available"] is False and gone["html"] == "" and gone["details"] == []


def test_the_actions_dispatch_regenerate_and_open_inspiration_by_report_name():
    service, opened = _Service(), []
    controller = type("Ctl", (), {"open_inspiration": lambda self: opened.append(1)})()
    generate = actions.generate_report({"work_briefing": lambda: "busy", "personal_briefing": reports.generate_briefing(lambda: service)})
    assert generate({"report": "personal_briefing"}) == {"report": "personal_briefing", "state": "started"} and service.asked == 1
    assert generate({"report": "work_briefing"})["state"] == "busy"
    assert reports.generate_briefing(lambda: None)() == "unavailable"
    open_it = actions.generate_report({"personal_briefing": reports.open_inspiration(lambda: controller)})
    assert open_it({"report": "personal_briefing"}) == {"report": "personal_briefing", "state": "opened"} and opened == [1]
    assert reports.open_inspiration(lambda: None)() == "unavailable"
    with pytest.raises(actions.ActionError):
        open_it({"report": "work_briefing"})
    assert reports.generate_work_briefing is reports.generate_briefing


# ---------------------------------------------------------------- 控制器走浏览器

def _controller(tmp_path, vault, *, opened=True, watched=False, fakes=None):
    service = _service(tmp_path, vault, fakes or _Fakes())
    host, opens = _Host(), []
    controller = PersonalController(host, service, open_report=lambda: (opens.append(1), opened)[1], report_watched=lambda: watched)
    return controller, host, service, opens


def test_view_opens_the_browser_page_and_counts_as_read(tmp_path, vault):
    controller, host, service, opens = _controller(tmp_path, vault)
    states = []
    controller.state_changed.connect(states.append)
    service.generate_now()
    app.processEvents()
    assert controller.island_state == "unread" and len(host.alerts) == 1

    controller.open_window()
    assert opens == [1] and controller.window is None, "开的是浏览器里的页，不是 Qt 窗口"
    assert controller.island_state == "idle" and states == ["unread", "idle"] and host.bubbles == []

    (_text, kwargs), = host.alerts
    dict(kwargs["buttons"])["查看"]()
    assert opens == [1, 1] and host.resolved == [ALERT_ID], "提醒上的「查看」走同一条路"


def test_a_page_that_cannot_open_says_so_and_no_alert_while_the_page_is_watched(tmp_path, vault):
    controller, host, _service_, opens = _controller(tmp_path, vault, opened=False)
    controller.open_window()
    assert opens == [1] and host.bubbles == ["简报页打不开：本机服务起不来，看日志里「配置全景」那几行"]

    controller, host, service, _opens = _controller(tmp_path, vault, watched=True)
    service.generate_now()
    app.processEvents()
    assert host.alerts == [] and controller.island_state == "idle", "页面开着：它自己原地换成新的"


def test_the_qt_window_keeps_only_the_inspiration_tab_and_the_page_action_opens_it(tmp_path, vault):
    controller, _host, _service_, opens = _controller(tmp_path, vault)
    controller.open_inspiration()
    try:
        assert opens == [], "灵感页还在 Qt 里"
        tabs = controller.window.tabs
        assert [tabs.tabText(i) for i in range(tabs.count())] == ["灵感"] and controller.window.briefing_page.isHidden()
        assert tabs.tabText(tabs.currentIndex()) == "灵感" and controller.obsidian_btn.text() == "在 Obsidian 打开 AI-Base"
        assert reports.open_inspiration(lambda: controller)() == "opened"
    finally:
        controller.window.close()
