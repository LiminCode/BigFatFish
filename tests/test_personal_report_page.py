# -*- coding: utf-8 -*-
"""个人简报在报告页上（2026-11-20，M4b 第二项；11-21 收尾）：同一张报告页多登记一项——provider、顶部的灵感输入区
（``composer`` + ``add_inspiration`` 动作）、副按钮「在 Obsidian 打开 AI-Base」（``open_obsidian`` 动作）、
``PersonalController`` 走浏览器（Qt 窗口删了）。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import personal_briefing as pb
from pet import personal_vault as pv
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
    sync_state, sync_error, pushed_at = "idle", "", ""

    def __init__(self, briefing=None, *, error=""):
        self._briefing, self._error, self.asked, self.ideas = briefing, error, 0, []

    def latest(self):
        return self._briefing

    def last_error(self):
        return self._error

    def generate_now(self):
        self.asked += 1
        return True

    def add_inspiration(self, text):
        self.ideas.append(text)
        self.sync_state, self.pushed_at = "pushed", "09:00"
        return Path("x")


BRIEFING = pb.PersonalBriefing(ok=True, summary="先补周五的扫描。", markdown="## 待复习\n- ★★ 风险观察（到期 09-20）\n\n## 今天\n无\n",
                               generated_at="2026-11-20T08:30:00", seconds=63.4, turns=6, model="claude-sonnet-5", effort="medium",
                               tokens_in=48210, tokens_out=1130, files_read=["INDEX.md", "5-Daily/2026-11-20.md"], pull_note="")
COMPOSER = {"placeholder": "一句灵感、一个念头……Ctrl+Enter 记下，直接推到 GitHub", "label": "记下",
            "hint": "每条记进 AI-Base 的 User/灵感 Inspiration.md，按日期分节；不经 AI，只 commit + push。", "status": "", "failed": False,
            "action": {"name": "add_inspiration", "report": "personal_briefing"}}


# ---------------------------------------------------------------- provider

def test_the_personal_briefing_is_a_second_report_on_the_same_page():
    data = reports.personal_briefing(lambda: _Service(BRIEFING), _config())()
    assert data["id"] == "personal_briefing" and data["title"] == "个人助理" and data["available"] is True and data["theme"] == "light"
    assert data["summary"] == "先补周五的扫描。" and data["generated"] == "生成于 11-20 08:30 · 由你自己的 Claude 读本地 AI-Base 克隆写成"
    assert [u["key"] for u in data["usage"]] == ["model", "effort", "time", "tokens_in", "tokens_out"], "自己的 key：没有花费这一项"
    assert [(s["source"], s["title"], s["count"]) for s in data["sections"]] == [("other", "待复习", 1), ("other", "今天", 0)]
    assert data["action"] == {"name": "generate_report", "report": "personal_briefing", "label": "重新生成",
                              "hint": "让你自己的 Claude 重新读一遍 AI-Base 并写一份，一两分钟"}
    assert data["actions"] == [{"name": "open_obsidian", "report": "personal_briefing", "label": "在 Obsidian 打开 AI-Base",
                                "hint": "克隆目录已登记成 Obsidian 库就直接打开；没登记就打开文件夹"}]
    assert data["composer"] == COMPOSER, "记灵感在页面顶部的输入区（Qt 的灵感页 11-21 删了）"
    assert data["settings_focus"] == "personal" and data["busy"] is False and data["error"] == ""
    (detail,) = data["details"]
    assert detail["title"] == "这次是怎么生成的（11-20 08:30）"
    assert detail["html"] == ("<p>肥鱼用你自己的 API key 直连 Anthropic，只读本地克隆，没有连接器</p><p>工具 6 轮 · 读了 2 个文件</p>"
                              "<ul><li><code>INDEX.md</code></li><li><code>5-Daily/2026-11-20.md</code></li></ul>")
    assert reports.work_briefing(lambda: None, _config())()["composer"] is None, "工作简报没有输入区"


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
    assert gone["available"] is False and gone["html"] == "" and gone["details"] == [] and gone["composer"]["status"] == ""


def test_the_composer_status_follows_the_push_state():
    service = _Service()
    assert reports.inspiration_status(service) == ""
    service.sync_state = "pushing"
    assert reports.inspiration_status(service) == "已写进 灵感 Inspiration.md，正在提交并推送…"
    service.sync_state, service.pushed_at = "pushed", "09:00"
    assert reports.inspiration_status(service) == "已推送到 GitHub（09:00）"
    service.sync_state, service.sync_error = "failed", "remote:  Permission\ndenied"
    assert reports.inspiration_status(service) == "已写进本地文件，但没推上去：remote: Permission denied"
    composer = reports.personal_briefing(lambda: service, _config())()["composer"]
    assert composer["failed"] is True and composer["status"].startswith("已写进本地文件")


def test_the_actions_dispatch_regenerate_and_open_obsidian_by_report_name_and_add_inspiration_posts_text():
    service, opened = _Service(), []
    controller = type("Ctl", (), {"open_obsidian": lambda self: opened.append(1)})()
    generate = actions.generate_report({"work_briefing": lambda: "busy", "personal_briefing": reports.generate_briefing(lambda: service)})
    assert generate({"report": "personal_briefing"}) == {"report": "personal_briefing", "state": "started"} and service.asked == 1
    assert generate({"report": "work_briefing"})["state"] == "busy"
    assert reports.generate_briefing(lambda: None)() == "unavailable"
    open_it = actions.generate_report({"personal_briefing": reports.open_obsidian(lambda: controller)})
    assert open_it({"report": "personal_briefing"}) == {"report": "personal_briefing", "state": "opened"} and opened == [1]
    assert reports.open_obsidian(lambda: None)() == "unavailable"
    with pytest.raises(actions.ActionError):
        open_it({"report": "work_briefing"})
    assert reports.generate_work_briefing is reports.generate_briefing

    add = reports.add_inspiration(lambda: service)
    assert add({"report": "personal_briefing", "text": "  周末整理旧书 "}) == {"report": "personal_briefing", "state": "saved",
                                                                              "status": "已推送到 GitHub（09:00）"}
    assert service.ideas == ["  周末整理旧书 "], "原样交给服务（它自己 strip）"
    assert add({"report": "personal_briefing", "text": "   "}) == {"report": "personal_briefing", "state": "empty", "status": ""}
    assert add({"report": "personal_briefing"})["state"] == "empty" and add({"report": "personal_briefing", "text": 3})["state"] == "empty"
    with pytest.raises(actions.ActionError) as bad:
        add({"report": "work_briefing", "text": "x"})
    assert (bad.value.status, bad.value.code) == (400, "bad_report")
    with pytest.raises(actions.ActionError) as gone:
        reports.add_inspiration(lambda: None)({"report": "personal_briefing", "text": "x"})
    assert (gone.value.status, gone.value.code) == (503, "unavailable")


# ---------------------------------------------------------------- 真实服务：记下 → 推送 → 状态

def test_the_composer_saves_an_idea_and_the_status_follows_the_push(tmp_path, vault):
    fakes = _Fakes()
    service = _service(tmp_path, vault, fakes)
    add = reports.add_inspiration(lambda: service)
    out = add({"report": "personal_briefing", "text": "周末把旧书整理出来"})
    assert out["state"] == "saved" and fakes.syncs and "周末把旧书整理出来" in pv.inspiration_path(vault).read_text(encoding="utf-8")
    assert out["status"] == "已推送到 GitHub（09:00）", "sync 是同步的假函数：记下即推完"
    assert reports.personal_briefing(lambda: service, _config())()["composer"]["status"] == "已推送到 GitHub（09:00）"
    service._sync = _Fakes(sync_ok=False).sync
    out = add({"report": "personal_briefing", "text": "再一条"})
    assert out["state"] == "saved" and out["status"].startswith("已写进本地文件，但没推上去：")
    assert reports.personal_briefing(lambda: service, _config())()["composer"]["failed"] is True
    missing = _service(tmp_path / "b", tmp_path / "missing", _Fakes())
    out = reports.add_inspiration(lambda: missing)({"report": "personal_briefing", "text": "x"})
    assert out["state"] == "failed" and "missing" in out["status"], "仓库副本不在：没记下，原因在状态里"
    assert Path(pv.INSPIRATION_FILE).name == "灵感 Inspiration.md"


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
    assert opens == [1] and not hasattr(controller, "window"), "开的是浏览器里的页，Qt 窗口没有了"
    assert controller.island_state == "idle" and states == ["unread", "idle"] and host.bubbles == []

    (_text, kwargs), = host.alerts
    dict(kwargs["buttons"])["查看"]()
    assert opens == [1, 1] and host.resolved == [ALERT_ID], "提醒上的「查看」走同一条路"


def test_a_page_that_cannot_open_says_so_and_no_alert_while_the_page_is_watched(tmp_path, vault):
    controller, host, _service_, opens = _controller(tmp_path, vault, opened=False)
    controller.open_window()
    assert opens == [1] and host.bubbles == ["简报页打不开：本机服务起不来，看日志里「配置全景」那几行"]
    assert controller.island_state == "idle"

    controller, host, service, _opens = _controller(tmp_path, vault, watched=True)
    service.generate_now()
    app.processEvents()
    assert host.alerts == [] and controller.island_state == "idle", "页面开着：它自己原地换成新的"

    host = _Host()
    PersonalController(host, _service(tmp_path / "c", vault, _Fakes())).open_window()
    assert host.bubbles == ["简报页打不开：本机服务起不来，看日志里「配置全景」那几行"], "没接页面（旧接线、测试）：也只能这么说"


def test_a_failed_push_is_a_bubble_only_while_nobody_has_the_page_open(tmp_path, vault):
    controller, host, service, _opens = _controller(tmp_path, vault, fakes=_Fakes(sync_ok=False))
    service.add_inspiration("x")
    app.processEvents()
    assert host.bubbles and host.bubbles[-1].startswith("已写进本地文件，但没推上去：")

    controller, host, service, _opens = _controller(tmp_path / "w", vault, watched=True, fakes=_Fakes(sync_ok=False))
    service.add_inspiration("x")
    app.processEvents()
    assert host.bubbles == [], "页面开着：输入区下面那行已经写着原因"
    assert controller.island_state == "idle"
