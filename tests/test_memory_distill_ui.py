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
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFontMetrics, QMouseEvent
from PySide6.QtTest import QTest
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


def test_wsl_place_is_probed_when_window_opens_even_if_extraction_is_off(tmp_path):
    """抽取没开、这个进程里一次也没抽过：开流程页也要去问 WSL 的 ~/.claude，入口按钮才能亮；只问一次。"""
    calls: list[int] = []
    service = _service(tmp_path, enabled=False)

    def runner(args, **_k):
        if "find" not in args[-1]:           # 只数「~/.claude 在哪」那一问；抽取时列 WSL 清单是另一回事
            calls.append(1)
        return 0, r"\\wsl.localhost\Ubuntu\home\me\.claude"

    service._wsl_runner = runner
    assert service.place(svc.PLACE_WSL_CLAUDE).path == ""
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    assert service.place(svc.PLACE_WSL_CLAUDE).path == r"\\wsl.localhost\Ubuntu\home\me\.claude"
    button = controller.window.place_buttons[svc.PLACE_WSL_CLAUDE]
    assert button.isEnabled() and button.toolTip() == r"\\wsl.localhost\Ubuntu\home\me\.claude"
    controller.open_window()
    assert service.refresh_now() and calls == [1], "再开窗、再抽取都不重复问 wsl.exe"
    controller.window.close()


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


def test_wsl_place_stays_unknown_when_probe_fails(tmp_path):
    """没装 WSL / wslpath 失败：按钮灰着、提示「还不知道在哪」，而且不会反复去问。"""
    calls: list[int] = []
    service = _service(tmp_path, enabled=False)
    service._wsl_runner = lambda *_a, **_k: calls.append(1) or (1, "")
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    button = controller.window.place_buttons[svc.PLACE_WSL_CLAUDE]
    assert not button.isEnabled() and button.toolTip().startswith("还不知道")
    controller.open_window()
    assert calls == [1]
    controller.window.close()


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
        assert window.tabs.count() == 4 and [window.tabs.tabText(i) for i in range(4)] == ["流程", "候选", "提案", "统计"]
        assert window.diagram.value("store").startswith("今天 0 条 · 共 0 条")
        assert window.diagram.value("distill") == "还没跑过" and window.distill_btn.isEnabled()
        assert window.diagram.value("review") == "待审 0 · 已接受 0 · 已拒 0" and window.diagram.value("sink") == "全局 0 条 · 项目 0 条"
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
        assert buttons[svc.PLACE_WSL_CLAUDE].isEnabled() and buttons[svc.PLACE_WSL_CLAUDE].toolTip().startswith("\\\\wsl.localhost"), \
            "开窗就问到了 WSL 的路径（UNC 不 stat，直接当存在）"
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


def test_flow_diagram_tiles_are_solid_metro_colors():
    """用户 2026-10-31：流程图的框要 Windows Phone 磁贴（实色、白字），不是只画一道边。"""
    diagram = ui.FlowDiagram(ui.briefing_tokens(False))
    diagram.resize(640, diagram.height())
    image = diagram.grab().toImage()
    assert set(ui.STAGE_COLORS) == set(ui.STAGES) and len(set(ui.STAGE_COLORS.values())) == len(ui.STAGES), "六格六色"
    for stage, rect in diagram.tile_rects().items():
        for x, y in ((rect.left() + 1, rect.top() + 1), (rect.right() - 1, rect.bottom() - 1), (rect.left() + 3, rect.center().y())):
            assert image.pixelColor(x, y).name() == ui.tile_fill(ui.STAGE_COLORS[stage]).name(), (stage, x, y, "边上也是实色，没有描边")


def test_place_tiles_are_metro_tiles_with_title_description_and_vscode_chip(tmp_path):
    """入口磁贴：实色 + 白字大标题 + 小字说明目录里是什么；路径在提示里；目录在 WSL 里时右下角「VS Code ▸」，
    点角标发 ``vscode_requested``、点别处发 ``place_requested``；灰掉的磁贴一律灰色。"""
    service = _service(tmp_path, enabled=False)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        window.resize(700, 900)
        app.processEvents()
        tile = window.place_buttons[svc.PLACE_CANDIDATES]
        assert isinstance(tile, ui.PlaceTile) and tile.color == ui.PLACE_COLORS[svc.PLACE_CANDIDATES]
        assert tile.description == i18n.t("distill.place.candidates_desc") and tile.description and tile.description != tile.text()
        assert tile.height() >= ui.PLACE_TILE_H and ui.PLACE_TITLE_PX > ui.PLACE_DESC_PX
        image = tile.grab().toImage()
        for x, y in ((1, 1), (tile.width() - 2, 1), (1, tile.height() - 2)):
            assert image.pixelColor(x, y).name() == ui.tile_fill(tile.color).name(), "实色磁贴，没有边框"
        wsl = window.place_buttons[svc.PLACE_WSL_CLAUDE]
        assert wsl.isEnabled() and wsl.action == i18n.t("distill.place.vscode")
        assert window.place_buttons[svc.PLACE_WINDOWS_CLAUDE].action == "", "不在 WSL 里的目录没有角标"
        asked: list[str] = []
        opened: list[str] = []
        window.vscode_requested.connect(asked.append)
        window.place_requested.connect(opened.append)
        QTest.mouseClick(wsl, Qt.MouseButton.LeftButton, pos=wsl.action_rect().center())
        assert asked == [svc.PLACE_WSL_CLAUDE] and opened == []
        QTest.mouseClick(wsl, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        assert asked == [svc.PLACE_WSL_CLAUDE] and opened == [svc.PLACE_WSL_CLAUDE]
        window.resize(520, 700)                       # 最窄：说明折成三行，磁贴得跟着长高；整页不许横向溢出
        app.processEvents()
        body = window.flow_scroll.widget()
        assert body.width() <= window.flow_scroll.viewport().width(), (body.width(), window.flow_scroll.viewport().width())
        assert body.minimumSizeHint().width() <= window.flow_scroll.viewport().width()
        for key, each in window.place_buttons.items():
            metrics = QFontMetrics(ui._tile_font(each.font(), ui.PLACE_DESC_PX))
            needed = metrics.boundingRect(QRect(0, 0, each._desc_width(each.width()), 1000),
                                          Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, each.description).height()
            assert each.height() >= 36 + needed + 6, (key, each.height(), needed)
        window.resize(700, 900)
        app.processEvents()
        service._config.set("work_notes", {"repo_dir": str(tmp_path / "nope")})
        window.show_places(service.places())
        grey = window.place_buttons[svc.PLACE_WORK_VAULT]
        assert not grey.isEnabled() and grey.grab().toImage().pixelColor(1, 1).name() == ui.DISABLED_TILE
    finally:
        window.close()
        window.deleteLater()


def test_service_opens_a_wsl_place_by_running_code_inside_wsl(tmp_path):
    """「用 VS Code 打开」= 在 WSL 里 cd 到那个目录 code .（wsl.exe -d 发行版 -e sh -c）；后台线程，结果走 vscode_done。"""
    unc = r"\\wsl.localhost\Ubuntu\home\me\.claude"
    calls: list[list[str]] = []
    answer = {"code": 0, "out": ""}

    def runner(args, **_kw):
        calls.append(list(args))
        return (0, unc) if "wslpath" in " ".join(args) else (answer["code"], answer["out"])

    service = _service(tmp_path, enabled=False)
    service._wsl_runner = runner
    results: list[tuple] = []
    service.vscode_done.connect(lambda ok, path, why: results.append((ok, path, why)))
    assert service.open_in_vscode(svc.PLACE_WSL_CLAUDE) == ("missing", ""), "没问过 WSL 之前不知道在哪"
    service.probe_wsl()
    assert service.open_in_vscode(svc.PLACE_WSL_CLAUDE) == ("launching", unc)
    assert calls[-1] == ["-d", "Ubuntu", "-e", "sh", "-c", "cd /home/me/.claude && code ."]
    assert results == [(True, unc, "")]
    windows_home = service.place(svc.PLACE_WINDOWS_CLAUDE).path
    assert service.open_in_vscode(svc.PLACE_WINDOWS_CLAUDE) == ("not_wsl", windows_home)
    answer.update(code=127, out="sh: 1: code: not found\n")
    service.open_in_vscode(svc.PLACE_WSL_CLAUDE)
    assert results[-1] == (False, unc, "sh: 1: code: not found")
    assert not service.place(svc.PLACE_WINDOWS_CLAUDE).wsl and service.place(svc.PLACE_WSL_CLAUDE).wsl


def test_tile_colors_are_softened_metro_accents():
    """用户 2026-10-31：磁贴颜色偏淡一点、别刺眼——底色是 accent 色降饱和后的版本，白字仍然够对比。"""
    from PySide6.QtGui import QColor
    for color in list(ui.STAGE_COLORS.values()) + list(ui.PLACE_COLORS.values()):
        raw, soft = QColor(color), ui.tile_fill(color)
        assert soft.hsvSaturationF() < raw.hsvSaturationF() * 0.8, (color, soft.name())
        assert soft.name() != raw.name()
        luminance = 0.2126 * soft.redF() + 0.7152 * soft.greenF() + 0.0722 * soft.blueF()
        assert luminance < 0.56, (color, soft.name(), "太亮的话白字就看不清")
    assert ui.tile_fill("#0050ef", enabled=False).name() == ui.DISABLED_TILE


def test_window_is_rebuilt_in_the_new_language_after_a_switch(tmp_path):
    """用户 2026-10-31：切到英文后页面上还有中文——窗口是切换前建的、被控制器缓存。重开时语言变了就重建。"""
    service = _service(tmp_path)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    first = controller.window
    assert first.tabs.tabText(0) == "流程"
    i18n.set_language("en")
    try:
        controller.open_window("Proposals")      # select_tab 按标签文字匹配
        window = controller.window
        assert window is not first and window.tabs.tabText(0) == "Flow" and window.tabs.currentIndex() == 2
        assert window.place_buttons[svc.PLACE_CANDIDATES].text() == "Raw candidate pool (local)"
        assert window.diagram.value("distill") == "never"
        controller.open_window()
        assert controller.window is window, "语言没变就复用"
        window.close()
    finally:
        i18n.set_language("zh")


def test_window_in_english(tmp_path):
    service = _service(tmp_path)
    i18n.set_language("en")      # Config() 构造会把语言设回配置里的中文，所以放在建服务之后
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        assert window.windowTitle() == "Session Memory Distill"
        assert [window.tabs.tabText(i) for i in range(4)] == ["Flow", "Candidates", "Proposals", "Stats"]
        assert window.diagram.value("distill") == "never"
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
        "enabled", "scan_wsl", "keep_days", "work_roots", "daily_at", "model", "model_custom", "effort", "mirror", "prompt",
        "work_distill", "work_daily_at", "work_model", "work_model_custom", "work_effort", "work_mirror", "work_prompt")]
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
