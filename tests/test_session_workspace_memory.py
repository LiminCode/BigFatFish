# -*- coding: utf-8 -*-
"""跳到对话 / 重开对话：记住会话当时开在哪个 VS Code 工作区，冻结后按它重开。

现场（2026-11-08，用户实机）：一个 WSL 会话的目录是 ``…/Github/aella_cloud``，它当时开在一个**未命名**的
多文件夹工作区里；那个窗口关掉后（VS Code 顺手删掉了未命名工作区的文件），另一个开着的工作区
``connect-check`` 恰好也包含 ``aella_cloud``。「最近的对话」只记了目录，详情卡上的工作区那一行是按
「现在开着的窗口里谁包含这个目录」现算的——于是卡片说它在 ``connect-check``，点「跳到对话」就把对话
重开到了 ``connect-check`` 里；要是没有哪个开着的工作区包含它，就只开文件夹新开一个窗口。

改法：
- 会话活着时把它的工作区（文件 / 文件夹、名字、**包含的文件夹列表**）记进「最近的对话」；
- 重开时先认记录：开着就聚焦那个窗口；没开就按记录开它（工作区文件还在就开文件，没了就把当时的
  文件夹一起开成一个多文件夹窗口），不去借别的恰好也包含这个目录的工作区；
- 改之前就冻结的老会话：VS Code 关掉的窗口留下的状态库里还能找到它当时在哪个窗口，顺手补记。

纪律：不读真实的 VS Code 数据目录，不起真的 code 命令。
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet import claude_session_history as hist
from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet.claude_session_jump import OpenWorkspace, Window
from pet.session_history_service import SessionHistoryActions, SessionHistoryService
from tests.test_session_jump_workspaces import (
    CODE, PLUGIN_KEY, SID, TAB_KEY, URI, WINDOWS, WORKSPACE_FILE, WSL, _Desk, _detail, _known, _read, _state_db)

DEPLOY_FILE = "/home/u/workspace/deploy.code-workspace"
DEPLOY = OpenWorkspace("deploy", ("/home/u/Github/charts", "/home/u/Github/shop_cloud"), DEPLOY_FILE,
                       wsl=True, multi_root=True)
DEPLOY_WINDOW = Window(6, 10, "deploy (Workspace) [WSL: Ubuntu-24.04] - values.yaml", CODE)
UNTITLED_FILE = "c:/Users/me/AppData/Roaming/Code/Workspaces/1793934561968/workspace.json"
UNTITLED_ROOTS = ["/home/u/Github-2/ath-core", "/home/u/Github/shop_cloud"]


def _record(owner: OpenWorkspace) -> dict:
    return sj.workspace_record(owner)


def _resume_kwargs(desk, *, exists=lambda path, wsl, distro: True):
    kwargs = {k: v for k, v in desk.kwargs.items() if k not in ("chain", "select_tab")}
    return {**kwargs, "exists": exists}


def _frozen(**over) -> si.SessionDetail:
    return _detail(alive=False, title="不在前台", **over)


# ---------------------------------------------------------------- 记录的形状

def test_the_workspace_record_carries_the_folder_list():
    record = sj.recorded_workspace(_frozen(extra={"workspace": _record(DEPLOY)}))
    assert record == {"label": "deploy", "target": DEPLOY_FILE, "multi_root": True,
                      "roots": ["/home/u/Github/charts", "/home/u/Github/shop_cloud"]}
    assert sj.recorded_workspace(_frozen()) == {} and sj.recorded_workspace(_frozen(extra={"workspace": "x"})) == {}
    assert sj.recorded_workspace(_frozen(extra={"workspace": {"label": "只有名字"}})) == {}, "没有路径的记录没用"


def test_history_keeps_the_workspace_and_an_empty_one_never_erases_it(tmp_path):
    store = hist.SessionHistory(tmp_path / "h.json", clock=lambda: 1000.0)
    store.record("claude_wsl", SID, cwd="/home/u/Github/shop_cloud", entrypoint="claude-vscode",
                 workspace=_record(DEPLOY))
    store.record("claude_wsl", SID, cwd="/home/u/Github/shop_cloud", workspace={})
    store.record("claude_wsl", SID, cwd="/home/u/Github/shop_cloud", workspace=None)
    store.save()
    again = hist.SessionHistory(tmp_path / "h.json", clock=lambda: 1000.0)
    again.load()
    (entry,) = again.entries()
    assert entry.workspace == {"label": "deploy", "target": DEPLOY_FILE, "multi_root": True,
                               "roots": ["/home/u/Github/charts", "/home/u/Github/shop_cloud"]}
    assert "folders" not in entry.workspace, "只存认得的几项"


def test_noting_a_workspace_later_does_not_move_the_row_in_time():
    clock = {"now": 1000.0}
    store = hist.SessionHistory(None, clock=lambda: clock["now"])
    store.record("claude_wsl", SID, cwd="/home/u/Github/shop_cloud")
    clock["now"] = 5000.0
    assert store.note_workspace(("claude_wsl", SID), _record(DEPLOY)) is True
    assert store.note_workspace(("claude_wsl", SID), _record(DEPLOY)) is False, "没变化就不落盘"
    assert store.note_workspace(("claude_wsl", "nobody"), _record(DEPLOY)) is False
    (entry,) = store.entries()
    assert entry.last_seen == 1000.0 and entry.workspace["target"] == DEPLOY_FILE


# ---------------------------------------------------------------- 重开：先认记录

def test_resume_prefers_the_recorded_workspace_over_another_that_also_contains_the_folder():
    """两个开着的工作区都包含这个目录、对话又不在前台：记录说是 deploy，就去 deploy，不管 ops-check 排得多靠前。"""
    known = [*_known(), DEPLOY]
    windows = [*WINDOWS, DEPLOY_WINDOW]
    desk = _Desk(windows=windows, known=known)
    result = sj.resume_in_vscode(_frozen(extra={"workspace": _record(DEPLOY)}), **_resume_kwargs(desk))
    assert result.ok and desk.log == [("focus", 6), URI]

    ops = next(w for w in known if w.label == "ops-check")
    desk = _Desk(windows=windows, known=known)
    assert sj.resume_in_vscode(_frozen(extra={"workspace": _record(ops)}), **_resume_kwargs(desk)).ok
    assert desk.log == [("focus", 2), URI]


def test_resume_reopens_the_recorded_workspace_when_it_is_closed_instead_of_borrowing_another():
    """现场：记录里的工作区关了，另一个开着的 ops-check 也包含这个目录——以前会把对话重开到 ops-check 里。"""
    desk = _Desk()                                   # 只开着 ops-check 等几个窗口
    result = sj.resume_in_vscode(_frozen(extra={"workspace": _record(DEPLOY)}), **_resume_kwargs(desk))
    assert result.ok and "deploy" in result.message
    assert desk.log == [("code", [DEPLOY_FILE]), URI], "开的是记录里的工作区文件，而不是聚焦 ops-check"


def test_an_untitled_workspace_whose_file_is_gone_is_rebuilt_from_its_folders():
    """未命名的多文件夹工作区关掉时 VS Code 会删掉它的文件：按记下的文件夹列表一起开，VS Code 会开成一个窗口。"""
    record = {"label": "Untitled", "target": UNTITLED_FILE, "multi_root": True, "roots": UNTITLED_ROOTS}
    desk = _Desk()
    result = sj.resume_in_vscode(_frozen(extra={"workspace": record}),
                                 **_resume_kwargs(desk, exists=lambda path, wsl, distro: False))
    assert result.ok and desk.log == [("code", UNTITLED_ROOTS), URI]


def test_an_untitled_workspace_reopened_under_a_new_file_name_is_matched_by_its_folders():
    reopened = OpenWorkspace("Untitled", tuple(UNTITLED_ROOTS), "c:/Users/me/AppData/Roaming/Code/Workspaces/9/workspace.json",
                             wsl=True, multi_root=True)
    record = {"label": "Untitled", "target": UNTITLED_FILE, "multi_root": True, "roots": UNTITLED_ROOTS}
    assert sj.open_workspace_matching([*_known(), reopened], record, wsl=True) is reopened
    assert sj.open_workspace_matching(_known(), record, wsl=True) is None
    assert sj.open_workspace_matching([replace(reopened, wsl=False)], record, wsl=True) is None, "本机 / WSL 不互认"

    windows = [*WINDOWS, Window(7, 10, "Untitled (Workspace) [WSL: Ubuntu-24.04] - a.py", CODE)]
    desk = _Desk(windows=windows, known=[*_known(), reopened])
    assert sj.resume_in_vscode(_frozen(extra={"workspace": record}), **_resume_kwargs(desk)).ok
    assert desk.log == [("focus", 7), URI]


def test_a_single_folder_record_reopens_that_folder():
    record = {"label": "shop_cloud", "target": "/home/u/Github/shop_cloud", "multi_root": False,
              "roots": ["/home/u/Github/shop_cloud"]}
    desk = _Desk(known=[])
    assert sj.resume_in_vscode(_frozen(extra={"workspace": record}), **_resume_kwargs(desk)).ok
    assert desk.log == [("code", ["/home/u/Github/shop_cloud"]), URI]


def test_without_a_record_resume_still_guesses_from_the_open_windows():
    desk = _Desk()
    assert sj.resume_in_vscode(_frozen(), **_resume_kwargs(desk)).ok and desk.log == [("focus", 2), URI], \
        "照旧：ops-check 包含这个目录、标题也认得出，就聚焦它"
    desk = _Desk(known=[], windows=[])
    assert sj.resume_in_vscode(_frozen(), **_resume_kwargs(desk)).ok
    assert desk.log == [("code", "/home/u/Github/shop_cloud"), URI], "照旧：什么线索都没有才只开文件夹"


def test_a_failed_code_command_is_reported_with_the_workspace_name():
    desk = _Desk(code_ok=False)
    result = sj.resume_in_vscode(_frozen(extra={"workspace": _record(DEPLOY)}), **_resume_kwargs(desk))
    assert not result.ok and "deploy" in result.message and desk.log == [("code", [DEPLOY_FILE])]


# ---------------------------------------------------------------- code 命令

def test_the_code_command_can_open_several_folders_at_once():
    wsl = si.SessionDetail(agent="claude_wsl", cwd="/x", distro="Ubuntu-24.04")
    assert sj.vscode_command(wsl, UNTITLED_ROOTS, code="code.cmd") == [
        "code.cmd", "--remote", "wsl+Ubuntu-24.04", *UNTITLED_ROOTS]
    local = si.SessionDetail(agent="claude", cwd=r"C:\code\proj")
    assert sj.vscode_command(local, ["c:/a/b", r"D:\c"], code="code.cmd") == ["code.cmd", r"c:\a\b", r"D:\c"]
    assert sj.vscode_command(local, [], code="code.cmd") == ["code.cmd", r"C:\code\proj"]
    assert sj.vscode_command(si.SessionDetail(agent="claude"), [], code="code.cmd") is None


def test_the_recent_conversations_list_also_follows_the_record():
    """「最近的对话」里点一行走 code 命令：有记录就按记录（开着 → 那个窗口；没开 → 重开它），没记录才按目录猜。"""
    detail = _frozen(extra={"workspace": _record(DEPLOY)})
    assert sj.vscode_target(detail, lambda: [*_known(), DEPLOY]) == DEPLOY_FILE
    assert sj.vscode_target(detail, _known, exists=lambda path, wsl, distro: True) == [DEPLOY_FILE]
    assert sj.vscode_target(detail, _known, exists=lambda path, wsl, distro: False) == list(DEPLOY.roots)
    assert sj.vscode_target(_frozen(), _known) == WORKSPACE_FILE, "没记录：照旧按目录"


# ---------------------------------------------------------------- 详情卡：冻结的会话不按目录猜

def test_a_frozen_session_s_card_does_not_borrow_an_open_workspace_that_merely_contains_its_folder():
    """现场：卡片上写着 connect-check · 7 个文件夹——那只是现在开着、恰好包含这个目录的工作区。"""
    detail = sj.attach_workspace(_frozen(), workspaces=_known, mentions=lambda folder, sid: 0)
    assert "workspace" not in detail.extra

    kept = sj.attach_workspace(_frozen(extra={"workspace": _record(DEPLOY)}), workspaces=_known,
                               mentions=lambda folder, sid: 0)
    assert kept.extra["workspace"]["target"] == DEPLOY_FILE, "历史里记的那份照留"

    alive = sj.attach_workspace(_detail(), workspaces=_known, mentions=lambda folder, sid: 0)
    assert alive.extra["workspace"]["label"] == "ops-check", "活着的会话照旧按目录认"


def test_a_frozen_session_still_trusts_vscodes_own_record_of_its_tab():
    ops = replace(next(w for w in _known() if w.label == "ops-check"), storage=("/state/ops",))
    detail = sj.attach_workspace(_frozen(), workspaces=lambda: [ops],
                                 mentions=lambda folder, sid: 2 if (folder, sid) == ("/state/ops", SID) else 0)
    assert detail.extra["workspace"]["target"] == WORKSPACE_FILE


def test_loading_a_frozen_card_backfills_the_workspace_from_vscodes_state(monkeypatch):
    from pet import session_pet_ui

    monkeypatch.setattr(session_pet_ui.claude_session_info, "load", lambda detail: detail)
    monkeypatch.setattr(sj, "opened_workspaces", lambda: [])
    asked: list = []
    monkeypatch.setattr(sj, "workspace_from_storage",
                        lambda sid, **kw: asked.append((sid, kw)) or _record(DEPLOY))
    loaded = session_pet_ui.load_detail(_frozen())
    assert loaded.extra["workspace"]["target"] == DEPLOY_FILE
    assert asked == [(SID, {"wsl": True, "distro": "Ubuntu-24.04"})]

    asked.clear()
    session_pet_ui.load_detail(_detail())
    assert asked == [], "活着的会话不用翻状态库"


# ---------------------------------------------------------------- 未命名的 WSL 工作区

UNTITLED_JSON = json.dumps({"folders": [{"uri": WSL + "/home/u/Github-2/ath-core"},
                                        {"uri": "vscode-remote://wsl+ubuntu-24.04/home/u/Github/shop_cloud"}],
                            "remoteAuthority": "wsl+ubuntu-24.04", "settings": {}})


def _read_untitled(path: str, distro: str) -> str | None:
    if (path, distro) == (UNTITLED_FILE, ""):
        return UNTITLED_JSON
    return _read(path, distro)


def test_an_open_untitled_wsl_workspace_is_recognised_through_its_remote_authority():
    """实机：未命名的 WSL 工作区在窗口记录里是 ``file:///c:/…/Code/Workspaces/<id>/workspace.json`` +
    ``remoteAuthority: wsl+…``，里面的文件夹是 WSL 地址。以前按本机路径读、发行版对不上，整个窗口被跳过。"""
    state = {"windowsState": {"openedWindows": [
        {"workspaceIdentifier": {"id": "u1", "configURIPath": "file:///c%3A/Users/me/AppData/Roaming/Code/Workspaces/1793934561968/workspace.json"},
         "remoteAuthority": "wsl+ubuntu-24.04"}]}}
    (found,) = sj.workspaces_from_state(state, _read_untitled)
    assert found.wsl and found.multi_root and found.label == "Untitled" and found.target == UNTITLED_FILE
    assert found.roots == tuple(UNTITLED_ROOTS)
    assert sj.owning_workspace([found], "/home/u/Github/shop_cloud/src", wsl=True) is found


# ---------------------------------------------------------------- 从 VS Code 关掉的窗口找回

def _appdata(tmp_path, **stores):
    """``workspaceStorage/<名字>/`` 各一份：(workspace.json 的内容, state.vscdb 里的键值)。"""
    user = tmp_path / "Code" / "User"
    for name, (meta, items) in stores.items():
        folder = user / "workspaceStorage" / name
        _state_db(folder, **items)
        (folder / "workspace.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_a_closed_windows_state_still_tells_which_workspace_held_the_session(tmp_path):
    appdata = _appdata(
        tmp_path,
        ws=({"workspace": {"id": "a3", "configPath": WSL + WORKSPACE_FILE}}, {TAB_KEY: '{"tabs":["%s"]}' % SID}),
        folder=({"folder": WSL + "/home/u/Github/shop_cloud"}, {PLUGIN_KEY: '{"recent":["%s"]}' % SID}),
        other=({"folder": WSL + "/home/u/Github/core-lib"}, {TAB_KEY: '{"tabs":["some-other"]}'}))
    found = sj.workspace_from_storage(SID, wsl=True, distro="Ubuntu-24.04", appdata=appdata, read_text=_read)
    assert (found["label"], found["target"], found["multi_root"]) == ("ops-check", WORKSPACE_FILE, True)
    assert found["roots"] == ["/home/u/Github/api-gateway", "/home/u/Github/shop_cloud",
                              "/srv/shared/charts", "/home/u/odd/name"], "开着的标签页压过插件状态里的一条"
    assert sj.workspace_from_storage(SID, wsl=False, appdata=appdata, read_text=_read) == {}, "本机会话不认 WSL 的窗口"
    assert sj.workspace_from_storage(SID, wsl=True, distro="Debian", appdata=appdata, read_text=_read) == {}
    assert sj.workspace_from_storage("", wsl=True, appdata=appdata, read_text=_read) == {}
    assert sj.workspace_from_storage(SID, wsl=True, appdata=tmp_path / "nowhere", read_text=_read) == {}


def test_when_the_best_window_s_workspace_file_is_gone_the_next_candidate_is_used(tmp_path):
    """未命名工作区关掉即删文件：那条记录还原不出文件夹，退到下一个提到过这个会话的窗口（单文件夹的）。"""
    appdata = _appdata(
        tmp_path,
        gone=({"workspace": {"id": "u", "configPath": "file:///c%3A/Users/me/AppData/Roaming/Code/Workspaces/1/workspace.json"}},
              {TAB_KEY: '{"tabs":["%s"]}' % SID}),
        folder=({"folder": WSL + "/home/u/Github/shop_cloud"}, {PLUGIN_KEY: '{"recent":["%s"]}' % SID}))
    found = sj.workspace_from_storage(SID, wsl=True, distro="Ubuntu-24.04", appdata=appdata,
                                      read_text=lambda path, distro: None)
    assert found == {"label": "shop_cloud", "target": "/home/u/Github/shop_cloud", "multi_root": False,
                     "roots": ["/home/u/Github/shop_cloud"], "folders": 1}


def test_an_untitled_wsl_workspace_whose_file_still_exists_is_recovered_with_its_folders(tmp_path):
    appdata = _appdata(
        tmp_path,
        untitled=({"workspace": {"id": "u", "configPath": "file:///c%3A/Users/me/AppData/Roaming/Code/Workspaces/1793934561968/workspace.json"}},
                  {TAB_KEY: '{"tabs":["%s"]}' % SID}))
    found = sj.workspace_from_storage(SID, wsl=True, distro="Ubuntu-24.04", appdata=appdata, read_text=_read_untitled)
    assert (found["label"], found["target"], found["roots"]) == ("Untitled", UNTITLED_FILE, UNTITLED_ROOTS)
    assert sj.workspace_from_storage(SID, wsl=False, appdata=appdata, read_text=_read_untitled) == {}, \
        "本机会话读这个文件：文件夹都是 WSL 地址，没有一个算数"


def test_windows_that_went_quiet_long_ago_are_not_searched(tmp_path):
    appdata = _appdata(tmp_path, ws=({"workspace": {"id": "a3", "configPath": WSL + WORKSPACE_FILE}},
                                     {TAB_KEY: '{"tabs":["%s"]}' % SID}))
    far_future = os.path.getmtime(appdata / "Code" / "User" / "workspaceStorage" / "ws" / "state.vscdb") + 40 * 86400
    assert sj.workspace_from_storage(SID, wsl=True, appdata=appdata, read_text=_read, now=far_future) == {}


# ---------------------------------------------------------------- 接线：活着时记下

def _service(resolve, clock, spawn=lambda fn: fn()):
    store = hist.SessionHistory(None, clock=lambda: 1000.0)
    service = SessionHistoryService(store, spawn=spawn, clock=clock, resolve_workspace=resolve)
    return service


def test_a_live_vscode_session_gets_its_workspace_resolved_and_recorded():
    asked: list = []
    clock = {"now": 100.0}

    def resolve(detail):
        asked.append((detail.agent, detail.session_id, detail.cwd, detail.is_wsl))
        return _record(DEPLOY)

    service = _service(resolve, lambda: clock["now"])
    update = {"sessionId": SID, "phase": "working", "cwd": "/home/u/Github/shop_cloud", "entrypoint": "claude-vscode"}
    service.on_session_update("claude_wsl", update)
    (entry,) = service.entries()
    assert asked == [("claude_wsl", SID, "/home/u/Github/shop_cloud", True)]
    assert entry.workspace["target"] == DEPLOY_FILE and entry.workspace["roots"] == list(DEPLOY.roots)

    for _ in range(5):
        service.on_session_update("claude_wsl", {**update, "tool": "Bash"})
    assert len(asked) == 1, "每次工具调用都来一条更新：十分钟内不再读 VS Code 的记录"
    clock["now"] += SessionHistoryService.WORKSPACE_RECHECK_S + 1
    service.on_session_update("claude_wsl", update)
    assert len(asked) == 2, "过了一阵再认一次（状态库落盘晚；用户也可能改了工作区）"


def test_terminal_and_gone_sessions_are_not_asked_about_workspaces():
    asked: list = []
    service = _service(lambda detail: asked.append(detail) or {}, lambda: 0.0)
    service.on_session_update("claude", {"sessionId": SID, "phase": "working", "cwd": "C:\\\\x", "entrypoint": "cli"})
    service.on_session_update("claude", {"sessionId": SID, "phase": "gone", "cwd": "C:\\\\x", "entrypoint": "claude-vscode"})
    assert asked == []


def test_a_resolver_that_finds_nothing_or_fails_leaves_the_row_alone():
    def boom(_detail):
        raise OSError("storage.json 读坏了")

    service = _service(boom, lambda: 0.0)
    service.on_session_update("claude", {"sessionId": SID, "phase": "working", "cwd": "C:\\\\x", "entrypoint": "claude-vscode"})
    (entry,) = service.entries()
    assert entry.workspace == {}


# ---------------------------------------------------------------- 接线：最近的对话里点一行

def _actions(**over):
    log = SimpleNamespace(vscode=[], found=[], noted=[])
    acts = SessionHistoryActions(
        popen=lambda argv: True, open_vscode=lambda detail: log.vscode.append(dict(detail.extra.get("workspace") or {})) or True,
        open_path=lambda p: True, which=lambda name: None, wsl=None,
        find_workspace=lambda sid, **kw: log.found.append((sid, kw)) or over.get("found", {}),
        note_workspace=lambda key, ws: log.noted.append((key, ws)))
    acts.log = log
    return acts


def _entry(**fields):
    store = hist.SessionHistory(None)
    store.record("claude_wsl", SID, cwd="/home/u/Github/shop_cloud", entrypoint="claude-vscode", distro="Ubuntu-24.04",
                 **fields)
    return store.entries()[0]


def test_clicking_a_row_hands_the_recorded_workspace_to_the_code_command():
    acts = _actions()
    message = acts.activate(_entry(workspace=_record(DEPLOY)))
    assert acts.log.vscode[0]["target"] == DEPLOY_FILE and acts.log.found == [] and "deploy" in message


def test_clicking_an_old_row_without_a_record_looks_in_vscodes_state_and_notes_what_it_finds():
    acts = _actions(found=_record(DEPLOY))
    acts.activate(_entry())
    assert acts.log.found == [(SID, {"wsl": True, "distro": "Ubuntu-24.04"})]
    assert acts.log.vscode[0]["target"] == DEPLOY_FILE
    assert acts.log.noted == [(("claude_wsl", SID), _record(DEPLOY))]

    acts = _actions(found={})
    acts.activate(_entry())
    assert acts.log.vscode == [{}] and acts.log.noted == [], "找不到就照旧，别编一个"
