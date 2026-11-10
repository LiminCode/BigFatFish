# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——WSL 里的会话也抽进候选库。

WSL 是替身：``wsl.exe`` 的调用换成假 runner，它「列出来」的文件放在 tmp_path 里（产品里那是
``\\\\wsl.localhost\\<发行版>\\…`` 共享）。候选库、游标、服务都是真的。
"""
from __future__ import annotations

import datetime as dt
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import memory_distill as md
from pet import memory_distill_service as svc
from pet import memory_distill_wsl as wsl
from pet.config import Config

app = QApplication.instance() or QApplication([])

T0 = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.timezone.utc)
LIST_V = "  NAME              STATE           VERSION\n* Ubuntu-24.04      Running         2\n  docker-desktop    Running         2\n"
LIST_V_STOPPED = "  NAME              STATE           VERSION\n* Ubuntu-24.04      Stopped         2\n  docker-desktop    Running         2\n"


def _rec(text: str, n: int, *, cwd: str = "/home/me/corp", uuid: str | None = None, kind: str = "user") -> str:
    return json.dumps({"type": kind, "isSidechain": False, "uuid": uuid or f"w-{n}", "sessionId": "sess-w",
                       "timestamp": (T0 + dt.timedelta(minutes=n)).isoformat().replace("+00:00", "Z"),
                       "cwd": cwd, "entrypoint": "cli", "gitBranch": "main",
                       "message": {"role": kind, "content": text}}, ensure_ascii=False)


def _write(folder, name: str, *records: str):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.writelines(r + "\n" for r in records)
    return path


def _listing(root) -> md.RemoteListing:
    files = tuple((p.relative_to(root).as_posix(), p.stat().st_size) for p in sorted(root.glob("*/*.jsonl")))
    return md.RemoteListing(root=str(root), files=files)


class _Wsl:
    """假的 wsl.exe：``-l -v`` 报默认发行版在不在跑，``-e sh -c <列清单>`` 照 ``root`` 下的文件回答。"""

    def __init__(self, root, *, running: bool = True, fail: bool = False) -> None:
        self.root, self.running, self.fail = root, running, fail
        self.calls: list[list[str]] = []

    def __call__(self, args, *, input_text=None, timeout=30.0):
        self.calls.append(list(args))
        if args[:2] == ["-l", "-v"]:
            return 0, LIST_V if self.running else LIST_V_STOPPED
        if args[:3] == ["-e", "sh", "-c"] and "find" in args[3]:
            if self.fail:
                return 1, ""
            lines = [str(self.root)] + [f"{p.stat().st_size}\t{p.relative_to(self.root).as_posix()}"
                                        for p in sorted(self.root.glob("*/*.jsonl"))]
            return 0, "\n".join(lines) + "\n"
        return 1, ""

    @property
    def listed(self) -> int:
        return sum(1 for call in self.calls if call[:3] == ["-e", "sh", "-c"] and "find" in call[3])


# ---------------------------------------------------------------- 问 WSL


def test_default_distro_running_reads_the_starred_line():
    assert wsl.default_distro_running(lambda args, **k: (0, LIST_V)) is True
    assert wsl.default_distro_running(lambda args, **k: (0, LIST_V_STOPPED)) is False, "别的发行版在跑不算"
    assert wsl.default_distro_running(lambda args, **k: (1, "")) is False
    assert wsl.default_distro_running(lambda args, **k: (0, "no distributions")) is False


def test_list_transcripts_parses_root_and_sizes(tmp_path):
    root = tmp_path / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    _write(root / "-home-me-other", "b.jsonl", _rec("x", 2), _rec("y", 3))
    listing = wsl.list_transcripts(_Wsl(root))
    assert listing is not None and listing.root == str(root)
    assert [rel for rel, _size in listing.files] == ["-home-me-corp/a.jsonl", "-home-me-other/b.jsonl"]
    assert listing.files[0][1] == (root / "-home-me-corp" / "a.jsonl").stat().st_size
    assert wsl.list_transcripts(_Wsl(root, fail=True)) is None, "列不出来 ≠ 没有文件"
    assert wsl.list_transcripts(lambda args, **k: (0, "garbage\n12\tx/y.jsonl\n")) is None, "第一行得是目录"
    empty = wsl.list_transcripts(lambda args, **k: (0, "\\\\wsl.localhost\\U\\home\\me\\.claude\\projects\nnot-a-row\n"))
    assert empty is not None and empty.files == ()


# ---------------------------------------------------------------- 候选库


def test_remote_files_are_extracted_as_work_side_and_only_changed_ones_are_opened(tmp_path):
    root = tmp_path / "projects"
    first = _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1), _rec("没写目录的一条规矩", 2, cwd=""))
    other = _write(root / "-home-me-other", "b.jsonl", _rec("这个接口先别动", 3))
    store = md.CandidateStore(tmp_path / "store")
    assert store.refresh([], work_roots=[], remote=_listing(root)) == 3
    rows = store.read_all()
    assert {r["side"] for r in rows} == {md.SIDE_WORK}, "WSL 里的会话一律公司侧，连没写 cwd 的也是（不能漏到个人侧）"
    assert sorted(store.load_cursors()) == ["wsl:-home-me-corp/a.jsonl", "wsl:-home-me-other/b.jsonl"]

    listing = _listing(root)
    other.unlink()                      # 大小没变的文件不该再被打开：删掉它，读就会失败
    _write(root / "-home-me-corp", "a.jsonl", _rec("再加一条：提交信息用英文", 4))
    grown = tuple((rel, first.stat().st_size if rel.endswith("a.jsonl") else size) for rel, size in listing.files)
    assert store.refresh([], work_roots=[], remote=md.RemoteListing(root=str(root), files=grown)) == 1
    assert [r["text"] for r in store.read_all()][-1] == "再加一条：提交信息用英文"
    assert "wsl:-home-me-other/b.jsonl" in store.load_cursors(), "清单里还有它，游标留着"


def test_remote_cursors_survive_when_wsl_is_not_listed_and_go_when_the_file_is_gone(tmp_path):
    root = tmp_path / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    store = md.CandidateStore(tmp_path / "store")
    store.refresh([], work_roots=[], remote=_listing(root))
    assert store.refresh([], work_roots=[]) == 0, "这一轮没问 WSL（发行版没起来）"
    assert "wsl:-home-me-corp/a.jsonl" in store.load_cursors(), "没列清单就不动 WSL 的游标，更不去 stat 共享"
    assert store.refresh([], work_roots=[], remote=_listing(root)) == 0, "游标还在，不会重抽一遍"
    assert store.refresh([], work_roots=[], remote=md.RemoteListing(root=str(root), files=())) == 0
    assert store.load_cursors() == {}, "清单里没有了才清"


def test_remote_file_that_shrank_is_rescanned(tmp_path):
    root = tmp_path / "projects"
    path = _write(root / "-home-me-corp", "a.jsonl", _rec("第一条规矩要长一点", 1), _rec("第二条", 2))
    store = md.CandidateStore(tmp_path / "store")
    store.refresh([], work_roots=[], remote=_listing(root))
    path.write_text(_rec("重写后的", 5, uuid="w-new") + "\n", encoding="utf-8", newline="\n")
    assert store.refresh([], work_roots=[], remote=_listing(root)) == 1
    assert [r["text"] for r in store.read_all()] == ["第一条规矩要长一点", "第二条", "重写后的"]


def test_the_same_record_seen_in_two_places_is_stored_once(tmp_path):
    """桌面版开的 WSL 会话在 Windows 的 ``projects/ssh-*`` 和 WSL 里各有一份（实机 27 条重复）。"""
    home = tmp_path / "home" / ".claude" / "projects"
    _write(home / "ssh-1234", "s.jsonl", _rec("以后都写英文文档", 1, uuid="same"), _rec("只在 Windows 这份里", 2, uuid="win"))
    root = tmp_path / "projects"
    _write(root / "-home-me-corp", "s.jsonl", _rec("以后都写英文文档", 1, uuid="same"), _rec("只在 WSL 这份里", 3, uuid="wsl"))
    store = md.CandidateStore(tmp_path / "store")
    assert store.refresh([home], work_roots=[], remote=_listing(root)) == 3
    assert sorted(r["id"] for r in store.read_all()) == ["same", "win", "wsl"]
    (root / "-home-me-corp" / "s.jsonl").write_text(
        _rec("开头变了", 0, uuid="head") + "\n" + _rec("以后都写英文文档", 1, uuid="same") + "\n", encoding="utf-8", newline="\n")
    assert store.refresh([home], work_roots=[], remote=_listing(root)) == 1, "整份重扫也不会把旧的再存一遍"


# ---------------------------------------------------------------- 服务


def _service(tmp_path, runner, *, scan_wsl: bool = True):
    config = Config(tmp_path / "appdata")
    config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": True, "scan_wsl": scan_wsl})
    home = tmp_path / "home" / ".claude" / "projects"
    _write(home / "C--Users-me-Pet", "p.jsonl", _rec("以后回复用中文", 1, cwd=r"C:\Users\me\Pet", uuid="p-1"))
    return svc.MemoryDistillService(config, spawn=lambda target: target(), roots=[home], wsl_runner=runner,
                                    opener=lambda target: True)


def test_manual_refresh_scans_wsl_and_counts_it(tmp_path):
    root = tmp_path / "wsl" / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    runner = _Wsl(root, running=False)
    service = _service(tmp_path, runner)
    got: list[int] = []
    service.refreshed.connect(got.append)
    assert service.refresh_now() and got == [2], "手动抽取：发行版没起来也去问（会把它拉起来）"
    stats = service.stats()
    assert stats["by_side"] == {md.SIDE_PERSONAL: 1, md.SIDE_WORK: 1}
    assert stats["wsl"] == {"state": "ok", "files": 1}
    assert not any(call[:2] == ["-l", "-v"] for call in runner.calls)


def test_scheduled_refresh_does_not_wake_a_stopped_distro(tmp_path):
    root = tmp_path / "wsl" / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    runner = _Wsl(root, running=False)
    service = _service(tmp_path, runner)
    service.check()
    assert runner.listed == 0 and service.stats()["by_side"] == {md.SIDE_PERSONAL: 1}
    assert service.stats()["wsl"]["state"] == "asleep"
    runner.running = True
    service.check()
    assert runner.listed == 1 and service.stats()["by_side"] == {md.SIDE_PERSONAL: 1, md.SIDE_WORK: 1}


def test_wsl_scan_can_be_switched_off_and_failures_do_not_break_the_windows_scan(tmp_path):
    root = tmp_path / "wsl" / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    off = _Wsl(root)
    service = _service(tmp_path / "off", off, scan_wsl=False)
    service.refresh_now()
    assert off.listed == 0 and service.stats()["wsl"]["state"] == "off"
    broken = _Wsl(root, fail=True)
    service = _service(tmp_path / "broken", broken)
    got: list[int] = []
    service.refreshed.connect(got.append)
    service.refresh_now()
    assert got == [1] and service.last_error == "" and service.stats()["wsl"]["state"] == "failed"


def test_scan_wsl_setting_defaults_on_and_round_trips(tmp_path):
    from PySide6.QtWidgets import QWidget

    from pet import settings_memory_distill as sd

    assert md.normalize(None)["scan_wsl"] is True
    assert md.normalize({"scan_wsl": False})["scan_wsl"] is False
    config = Config(tmp_path / "appdata")
    dialog = QWidget()
    dialog.config = config
    rows = sd.distill_rows(dialog)
    assert [row.objectName() for row in rows][:2] == ["settingRow_distill_enabled", "settingRow_distill_scan_wsl"]
    assert dialog.distill_scan_wsl_check.isChecked() and dialog.distill_scan_wsl_check.accessibleName() == "也扫 WSL 里的会话"
    dialog.distill_scan_wsl_check.setChecked(False)
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["scan_wsl"] is False
    dialog.deleteLater()


class _Host:
    sprite = None

    def show_bubble(self, _text: str, _ms: int) -> None:
        pass

    def open_settings_for(self, _sprite) -> None:
        pass


def test_page_shows_how_many_files_came_from_wsl_and_says_when_wsl_did_not_answer(tmp_path):
    from pet import i18n
    from pet import memory_distill_ui as ui

    root = tmp_path / "wsl" / "projects"
    _write(root / "-home-me-corp", "a.jsonl", _rec("以后都写英文文档", 1))
    runner = _Wsl(root)
    service = _service(tmp_path, runner)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        window.refresh_btn.click()
        assert window.status_label.text() == "抽取完成：新增 2 条"
        assert window.diagram.value("source") == "~/.claude/projects · 2 个文件（其中 WSL 1 个）"
        assert "WSL 里的会话：扫（公司侧）" in window.settings_label.text()
        runner.fail = True
        window.refresh_btn.click()
        assert window.status_label.text() == "抽取完成：新增 0 条（WSL 那边没问到，这次只扫了 Windows 这边）"
        assert window.diagram.value("source") == "~/.claude/projects · 2 个文件（其中 WSL 1 个）", "没问到不等于没有了"
        i18n.set_language("en")
        assert ui.stage_values(service.stats())["source"] == "~/.claude/projects · 2 files (1 from WSL)"
    finally:
        i18n.set_language("zh")
        window.close()
        window.deleteLater()
