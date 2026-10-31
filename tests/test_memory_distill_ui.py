# -*- coding: utf-8 -*-
"""会话记忆蒸馏的 Qt 侧：服务（线程 / 定时 / 入口）、独立流程页（Metro、流程图数字、候选列表、入口按钮）、
设置页一节、菜单入口。

纪律：不起真的 wsl.exe、不碰真实 ``~/.claude``、不真的打开资源管理器 / Obsidian——都用替身。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import memory_distill as md
from pet import memory_distill_service as svc
from pet import memory_distill_ui as ui
from pet.config import Config
from pet.settings_theme_qss import METRO_TOKENS

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _pump(predicate, budget: float = 5.0) -> bool:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _transcript(home, name: str, *rows: str) -> None:
    folder = home / ".claude" / "projects" / "C--Users-me-Github-Pet"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.jsonl").write_text("".join(r + "\n" for r in rows), encoding="utf-8")


def _rec(kind: str, content, *, n: int = 0, cwd: str = r"C:\Users\me\Github\Pet", **extra) -> str:
    record = {"type": kind, "isSidechain": False, "uuid": f"{kind}-{n}", "sessionId": "sess-1",
              "timestamp": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=n)).isoformat().replace("+00:00", "Z"),
              "cwd": cwd, "entrypoint": "claude-desktop", "gitBranch": "main",
              "message": {"role": kind, "content": content}}
    record.update(extra)
    return json.dumps(record, ensure_ascii=False)


class _Host:
    """壳的替身：气泡与设置入口都只记参数。"""

    def __init__(self) -> None:
        self.bubbles: list[str] = []
        self.settings_opened = 0
        self.sprite = object()

    def show_bubble(self, text: str, _ms: int) -> None:
        self.bubbles.append(text)

    def open_settings_for(self, _sprite) -> None:
        self.settings_opened += 1


def _sync_spawn(target) -> None:
    target()


def _service(tmp_path, *, enabled: bool = True, opener=None, spawn=_sync_spawn):
    config = Config(tmp_path / "appdata")
    config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": enabled})
    home = tmp_path / "home"
    _transcript(home, "s1", _rec("assistant", [{"type": "text", "text": "用等宽字体？"}], n=1),
                _rec("user", "要，以后分支也用", n=2),
                _rec("user", "不对，字太大了", n=3, cwd="/home/me/corp"))
    opened: list[str] = []
    service = svc.MemoryDistillService(config, spawn=spawn, roots=[home / ".claude" / "projects"],
                                       wsl_runner=lambda *_a, **_k: (0, r"\\wsl.localhost\Ubuntu\home\me\.claude"),
                                       opener=opener or (lambda target: opened.append(target) or True))
    service._opened = opened
    return service


# ---------------------------------------------------------------- 服务


def test_service_refresh_runs_in_thread_and_reports_back(tmp_path):
    service = _service(tmp_path, spawn=None)       # 真线程
    service._spawn = svc._spawn_thread
    got: list[int] = []
    service.refreshed.connect(got.append)
    assert service.refresh_now() is True
    assert service.busy and service.refresh_now() is False, "忙着不叠加"
    assert _pump(lambda: got == [2])
    assert not service.busy and service.last_error == "" and service.last_refresh_at
    stats = service.stats()
    assert stats["total"] == 2 and stats["by_side"] == {md.SIDE_PERSONAL: 1, md.SIDE_WORK: 1}
    assert [r["text"] for r in service.recent()] == ["不对，字太大了", "要，以后分支也用"], "按时间新的在前"
    assert service.place(svc.PLACE_WSL_CLAUDE).path.startswith("\\\\wsl.localhost"), "第一次抽取顺便问了 WSL 的路径"
    assert service.refresh_now() and _pump(lambda: got == [2, 0]), "第二次没新内容"


def test_service_check_only_refreshes_when_enabled(tmp_path):
    service = _service(tmp_path, enabled=False)
    service.check()
    assert service.stats()["total"] == 0
    service._config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": True})
    service.check()
    assert service.stats()["total"] == 2


def test_service_reports_extraction_errors(tmp_path, monkeypatch):
    service = _service(tmp_path)
    errors: list[str] = []
    service.failed.connect(errors.append)

    def boom(self, *_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(md.CandidateStore, "refresh", boom)
    service.refresh_now()
    assert errors == ["OSError: disk gone"] and not service.busy
    assert service.stats()["error"] == "OSError: disk gone"


def test_service_places_and_opening(tmp_path):
    service = _service(tmp_path)
    keys = [p.key for p in service.places()]
    assert keys == list(svc.PLACE_ORDER)
    assert service.open_place(svc.PLACE_WSL_CLAUDE) == ("missing", ""), "没问过 WSL 之前不知道在哪"
    how, target = service.open_place(svc.PLACE_CANDIDATES)
    assert how == "folder" and target == str(service.store.candidates_dir) and os.path.isdir(target), "候选库目录不存在就建出来"
    assert service.open_place(svc.PLACE_GLOBAL_CLAUDE_MD)[0] in ("file", "missing")
    vault = tmp_path / "vault"
    vault.mkdir()
    service._config.set("personal", {"repo_dir": str(vault)})
    how, target = service.open_place(svc.PLACE_PERSONAL_VAULT)
    assert how == "folder" and target == str(vault), "Obsidian 没登记就开文件夹"
    assert service._opened[-1] == str(vault)


def test_wsl_claude_dir_is_empty_without_wsl_or_on_failure(monkeypatch):
    monkeypatch.setattr(svc.claude_hooks, "wsl_exe", lambda: None)
    assert svc.wsl_claude_dir(lambda *a, **k: (0, r"\\wsl.localhost\U\home\me\.claude")) == ""
    monkeypatch.setattr(svc.claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")
    assert svc.wsl_claude_dir(lambda *a, **k: (0, r"\\wsl.localhost\U\home\me\.claude")) == r"\\wsl.localhost\U\home\me\.claude"
    assert svc.wsl_claude_dir(lambda *a, **k: (1, "boom")) == ""
    assert svc.wsl_claude_dir(lambda *a, **k: (0, "/home/me/.claude")) == "", "不是 UNC 就不要"


# ---------------------------------------------------------------- 页面


@pytest.mark.parametrize("dark", [False, True])
def test_window_is_metro_square_and_uses_theme_tokens(dark):
    qss = ui._QSS.format(**ui.briefing_tokens(dark))
    assert "border-radius: 0" in qss
    for line in qss.splitlines():
        if "border-radius" in line:
            value = line.split("border-radius:")[1].split(";")[0].strip()
            assert value == "0", line
    key = "dark" if dark else "light"
    assert METRO_TOKENS[key]["page"] in qss and METRO_TOKENS[key]["tile"] in qss


def test_window_shows_numbers_on_the_flow_tiles_and_lists_candidates(tmp_path):
    service = _service(tmp_path)
    host = _Host()
    controller = ui.MemoryDistillController(host, service)
    controller.open_window()
    window = controller.window
    try:
        assert window.windowTitle() == "会话记忆蒸馏"
        assert window.tabs.count() == 3 and [window.tabs.tabText(i) for i in range(3)] == ["流程", "候选", "统计"]
        assert window.diagram.value("store").startswith("今天 0 条 · 共 0 条")
        assert window.diagram.value("distill") == "第二期" and not window.distill_btn.isEnabled()
        assert window.list.count() == 0 and "还没有候选" in window.detail.toPlainText()
        window.refresh_btn.click()
        assert _pump(lambda: window.diagram.value("store").startswith("今天 2 条 · 共 2 条"))
        assert "规则 / 决定 / 纠正 2" in window.diagram.value("store")
        assert window.diagram.value("extract").startswith("上次 ")
        assert window.status_label.text() == "抽取完成：新增 2 条"
        assert window.list.count() == 2
        assert window.list.item(1).text().startswith(dt.datetime.now().strftime("%m-%d"))
        assert "规则 · 个人 · Pet · 要，以后分支也用" in window.list.item(1).text()
        assert "纠正 · 公司（WSL 路径） · corp" in window.list.item(0).text(), "公司侧要写出为什么"
        assert "个人 1 条、公司 1 条" in window.sides_label.text() and "WorkSpace" in window.sides_label.text()
        window.list.setCurrentRow(1)
        detail = window.detail.toPlainText()
        assert "Claude 当时说" in detail and "用等宽字体？" in detail and "要，以后分支也用" in detail
        assert "项目 C:\\Users\\me\\Github\\Pet · 分支 main" in detail
        assert "候选总数" in window.stats_body.toPlainText() and "2" in window.stats_body.toPlainText()
        assert "候选库：" in window.settings_label.text() and "自动抽取：开" in window.settings_label.text()
        assert "本机、不进 git" in window.candidates_note.text()
    finally:
        window.close()
        window.deleteLater()


def test_window_place_buttons_and_tiles_open_places(tmp_path):
    service = _service(tmp_path)
    host = _Host()
    controller = ui.MemoryDistillController(host, service)
    controller.open_window()
    window = controller.window
    try:
        buttons = window.place_buttons
        assert set(buttons) == set(svc.PLACE_ORDER)
        assert not buttons[svc.PLACE_WSL_CLAUDE].isEnabled() and buttons[svc.PLACE_WSL_CLAUDE].toolTip().startswith("还不知道")
        assert buttons[svc.PLACE_CANDIDATES].isEnabled(), "候选库目录还没建也能点（点了就建）"
        assert buttons[svc.PLACE_CANDIDATES].text() == "原始候选库（本地）"
        buttons[svc.PLACE_CANDIDATES].click()
        assert service._opened[-1] == str(service.store.candidates_dir)
        # 点流程图的「候选库」格子也一样
        rect = window.diagram.tile_rects()["store"]
        spot = QPointF(rect.center())
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, spot, QPointF(window.diagram.mapToGlobal(rect.center())),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(window.diagram, press)
        assert service._opened[-2:] == [str(service.store.candidates_dir)] * 2
        assert window.diagram.stage_at(QPoint(rect.center())) == "store"
        assert window.diagram.stage_at(QPoint(-5, -5)) == ""
        # 不存在的目录：气泡说明
        service._config.set("work_notes", {"repo_dir": str(tmp_path / "nope")})
        controller.open_place(svc.PLACE_WORK_VAULT)
        assert host.bubbles and host.bubbles[-1].startswith("还没有这个目录")
        window.settings_btn.click()
        assert host.settings_opened == 1
    finally:
        window.close()
        window.deleteLater()


def test_window_theme_toggle_saves_the_shared_preference(tmp_path):
    service = _service(tmp_path)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        before = window.is_dark
        window.theme_btn.click()
        assert window.is_dark != before
        saved = service._config.get("context_menu_appearance")["theme"]
        assert saved == ("dark" if window.is_dark else "light")
        assert window.theme_btn.text() == ("☀" if window.is_dark else "☾")
    finally:
        window.close()
        window.deleteLater()


def test_window_in_english(tmp_path):
    service = _service(tmp_path)
    i18n.set_language("en")      # Config() 构造会把语言设回配置里的中文，所以放在建服务之后
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        assert window.windowTitle() == "Session Memory Distill"
        assert [window.tabs.tabText(i) for i in range(3)] == ["Flow", "Candidates", "Stats"]
        assert window.diagram.value("distill") == "phase 2"
        assert window.place_buttons[svc.PLACE_CANDIDATES].text() == "Raw candidate pool (local)"
    finally:
        window.close()
        window.deleteLater()


def test_flow_page_scrolls_instead_of_squashing_the_diagram(tmp_path):
    """实机截图（2026-10-31）：窗口不够高时入口按钮画到了流程图第二行上。流程图定高、整页滚动。"""
    window = ui.MemoryDistillWindow()
    try:
        window.resize(600, 500)
        window.show()
        app.processEvents()
        assert window.diagram.height() == ui.TILE_H * 2 + ui.TILE_GAP + 8
        assert window.flow_scroll.verticalScrollBar().maximum() > 0, "内容比窗口高就能滚"
        assert window.refresh_btn.isVisible(), "按钮行在滚动区外，一直看得见"
    finally:
        window.close()
        window.deleteLater()


def test_flow_diagram_layout_is_two_rows_of_three_and_paints():
    diagram = ui.FlowDiagram(ui.briefing_tokens(False))
    diagram.resize(600, 240)
    rects = diagram.tile_rects()
    assert list(rects) == list(ui.STAGES)
    assert rects["source"].top() == rects["extract"].top() == rects["store"].top()
    assert rects["distill"].top() > rects["store"].bottom()
    assert rects["source"].left() == rects["distill"].left()
    diagram.set_values({"store": "x", "bogus": "y"})
    assert diagram.value("store") == "x"
    from PySide6.QtGui import QImage, QPainter
    image = QImage(diagram.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    diagram.render(image)
    assert image.pixelColor(rects["source"].center()).alpha() > 0


# ---------------------------------------------------------------- 设置页一节


class _Dialog:
    def __init__(self, config) -> None:
        self.config = config


def test_settings_rows_round_trip(tmp_path):
    from pet import settings_memory_distill as sd
    from PySide6.QtWidgets import QWidget

    config = Config(tmp_path / "appdata")
    config.set(md.CONFIG_KEY, {**md.normalize(None), "keep_days": 60, "work_roots": [r"D:\Corp", r"E:\Work"]})
    dialog = QWidget()
    dialog.config = config
    rows = sd.distill_rows(dialog)
    assert [row.objectName() for row in rows] == [f"settingRow_distill_{k}" for k in (
        "enabled", "keep_days", "work_roots", "daily_at", "model", "model_custom", "effort", "prompt")]
    assert dialog.distill_model_select.currentData() == "" and dialog.distill_model_edit.isHidden()
    assert dialog.distill_keep_days_select.currentData() == 60
    assert dialog.distill_roots_edit.text() == r"D:\Corp;E:\Work"
    assert dialog.distill_time_select.currentData() == "21:30"
    assert "{candidates}" in dialog.distill_prompt_editor.edit.toPlainText()
    dialog.distill_enabled_check.setChecked(True)
    dialog.distill_roots_edit.setText(r" F:\Only ; ")
    dialog.distill_model_select.setCurrentIndex(dialog.distill_model_select.findData("claude-haiku-5-5"))
    dialog.distill_keep_days_select.setCurrentIndex(dialog.distill_keep_days_select.findData(180))
    sd.save_distill_settings(dialog)
    saved = config.get(md.CONFIG_KEY)
    assert saved["enabled"] is True and saved["work_roots"] == [r"F:\Only"] and saved["model"] == "claude-haiku-5-5"
    assert saved["keep_days"] == 180 and saved["prompt_zh"] == "", "没改提示词就存空串（= 内置）"
    dialog.distill_model_select.setCurrentIndex(dialog.distill_model_select.findData(sd.CUSTOM))
    assert not dialog.distill_model_edit.isHidden()
    dialog.distill_model_edit.setText("claude-opus-5-5[1m]")
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["model"] == "", "不合法的名字退回「跟 AI 对话一致」"
    dialog.distill_model_edit.setText("my-custom-model")
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["model"] == "my-custom-model"
    section = sd.flow_section(dialog)
    assert section is dialog.distill_flow_section and "抽取" in dialog.distill_flow_label.text()
    dialog.deleteLater()


def test_prompt_template_follows_language_and_user_override():
    assert "{candidates}" in md.default_prompt_template("zh") and "{memory}" in md.default_prompt_template("en")
    assert md.prompt_template({"prompt_zh": "自定义 {candidates}"}, "zh") == "自定义 {candidates}"
    assert md.prompt_template({"prompt_zh": ""}, "zh") == md.default_prompt_template("zh")
