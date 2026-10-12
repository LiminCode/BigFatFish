# -*- coding: utf-8 -*-
"""跳到对话：会话所在的 VS Code 窗口开的是多文件夹工作区时，不许新开一个窗口。

现场（2026-10-12；项目名和标题都换成了编的）：会话的工作目录是 ``…/Github/shop_cloud``，承载它的 VS Code 窗口开的
是一个多文件夹工作区，标题是 ``ops-check (Workspace) [WSL: …] - <当前标签页>``——里面
没有 ``shop_cloud`` 这个名字。按文件夹名认不出窗口，就退到「用 code 命令打开这个文件夹」，
而没有哪个窗口单独开着这个文件夹，于是 VS Code 新开了一个。用户看到的是：点「跳到对话」，
冒出一个新窗口，而正确的那个明明就在主屏幕上。

同一台机器上还有三个标题都叫 ``core-lib [WSL: …]`` 的窗口（三个不同的父目录）：按名字只能
蒙最靠前的那个。

改法：VS Code 自己记着每个窗口开的是哪个文件夹 / 工作区（``storage.json``），工作区文件里
写着它包含哪些文件夹。先据此知道会话属于哪个窗口，再去找它。

纪律：不读真实的 VS Code 数据目录，不起真的 code 命令。
"""
from __future__ import annotations

import json
from dataclasses import replace

from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet.claude_session_jump import OpenWorkspace, Window

SID = "0f0e0d0c-1111-2222-3333-444455556666"
CODE = "code.exe"
WSL = "vscode-remote://wsl%2Bubuntu-24.04"
WORKSPACE_FILE = "/home/u/workspace/ops-check.code-workspace"
WORKSPACE_JSON = """{
    // 注释和行尾逗号在 .code-workspace 里都是合法的
    "folders": [
        {"name": "gateway", "path": "../Github/api-gateway"},
        {"path": "../Github/shop_cloud"},   /* 相对路径相对工作区文件所在目录 */
        {"path": "/srv/shared/charts"},
        {"uri": "vscode-remote://wsl+ubuntu-24.04/home/u/odd//name"},
    ],
    "settings": {"note": "看起来像注释的字符串 // 不能被删掉"},
}"""
STATE = {"windowsState": {
    "lastActiveWindow": {"folder": "file:///c%3A/Users/me/Github/BigFatFish"},
    "openedWindows": [
        {"folder": "file:///c%3A/Users/me/Github/BigFatFish"},
        {"workspaceIdentifier": {"id": "a3", "configURIPath": WSL + WORKSPACE_FILE},
         "remoteAuthority": "wsl+ubuntu-24.04"},
        {"folder": WSL + "/home/u/Github/core-lib", "remoteAuthority": "wsl+ubuntu-24.04"},
        {"folder": WSL + "/home/u/Github-2/core-lib", "remoteAuthority": "wsl+Ubuntu-24.04"},
        {"folder": "vscode-remote://ssh-remote%2Bbox/home/u/Github/shop_cloud"},
        {"folder": "file:///c%3A/Users/me/My%20Notes"},
    ]}}


def _read(path: str, distro: str) -> str | None:
    return WORKSPACE_JSON if (path, distro.lower()) == (WORKSPACE_FILE, "ubuntu-24.04") else None


def _known() -> list[OpenWorkspace]:
    return sj.workspaces_from_state(STATE, _read)


# ---------------------------------------------------------------- VS Code 自己记的窗口清单

def test_open_windows_are_read_from_vscodes_own_record():
    known = {w.label: w for w in _known()}
    assert set(known) == {"BigFatFish", "ops-check", "core-lib", "My Notes"}, "SSH 远程窗口不是我们的会话"

    workspace = known["ops-check"]
    assert workspace.multi_root and workspace.wsl
    assert workspace.target == WORKSPACE_FILE, "交给 code 命令的是工作区文件，不是其中某个文件夹"
    assert workspace.roots == ("/home/u/Github/api-gateway", "/home/u/Github/shop_cloud",
                               "/srv/shared/charts", "/home/u/odd/name")

    local = known["BigFatFish"]
    assert not local.wsl and not local.multi_root and local.roots == ("c:/Users/me/Github/BigFatFish",)
    assert known["My Notes"].roots == ("c:/Users/me/My Notes",), "地址里的转义要还原"
    assert [w.target for w in _known() if w.label == "core-lib"] == [
        "/home/u/Github/core-lib", "/home/u/Github-2/core-lib"], "重复的那条 lastActiveWindow 不算两次"


def test_a_workspace_file_that_cannot_be_read_is_skipped_not_fatal():
    labels = [w.label for w in sj.workspaces_from_state(STATE, lambda path, distro: None)]
    assert "ops-check" not in labels and "core-lib" in labels


def test_garbage_state_reads_as_nothing():
    assert sj.workspaces_from_state({}, _read) == []
    assert sj.workspaces_from_state({"windowsState": {"openedWindows": ["x", {"folder": 3}]}}, _read) == []


def test_the_record_is_looked_up_under_each_editors_data_folder(tmp_path):
    storage = tmp_path / "Code" / "User" / "globalStorage" / "storage.json"
    storage.parent.mkdir(parents=True)
    storage.write_text(json.dumps(STATE), encoding="utf-8")
    (tmp_path / "Cursor" / "User" / "globalStorage").mkdir(parents=True)
    (tmp_path / "Cursor" / "User" / "globalStorage" / "storage.json").write_text("{broken", encoding="utf-8")

    labels = [w.label for w in sj.opened_workspaces(appdata=tmp_path, read_text=_read)]
    assert "ops-check" in labels and "BigFatFish" in labels
    assert sj.opened_workspaces(appdata=tmp_path / "nowhere", read_text=_read) == []


# ---------------------------------------------------------------- 会话属于哪个窗口

def test_the_session_belongs_to_the_workspace_that_contains_its_folder():
    owner = sj.owning_workspace(_known(), "/home/u/Github/shop_cloud", wsl=True)
    assert owner.label == "ops-check"
    assert sj.owning_workspace(_known(), "/home/u/Github/shop_cloud/src/deep", wsl=True).label == "ops-check"
    assert sj.owning_workspace(_known(), "/home/u/Github/shop_cloud2", wsl=True) is None, "前缀相同不等于在里面"


def test_same_named_folders_under_different_parents_are_told_apart():
    assert sj.owning_workspace(_known(), "/home/u/Github-2/core-lib", wsl=True).target == "/home/u/Github-2/core-lib"
    assert sj.owning_workspace(_known(), "/home/u/Github/core-lib/x", wsl=True).target == "/home/u/Github/core-lib"


def test_windows_and_wsl_projects_do_not_stand_in_for_each_other():
    assert sj.owning_workspace(_known(), r"C:\Users\me\Github\BigFatFish\pet", wsl=False).label == "BigFatFish"
    assert sj.owning_workspace(_known(), r"C:\Users\me\Github\BigFatFish", wsl=True) is None
    assert sj.owning_workspace(_known(), "/home/u/Github/shop_cloud", wsl=False) is None
    assert sj.owning_workspace(_known(), "", wsl=True) is None


# ---------------------------------------------------------------- 找到它的窗口

WINDOWS = [
    Window(1, 10, "BigFatFish - 别的对话", CODE),
    Window(2, 10, "ops-check (Workspace) [WSL: Ubuntu-24.04] - Incident and config rou…", CODE),
    Window(3, 10, "core-lib [WSL: Ubuntu-24.04] - Parser bugfix", CODE),
    Window(4, 10, "core-lib [WSL: Ubuntu-24.04] - Reduce memory use in the i…", CODE),
    Window(5, 20, "Ubuntu-24.04", "windowsterminal.exe"),
]
TITLE = "Incident and config routes for staging"


def test_a_multi_folder_workspace_window_is_recognised_by_its_workspace_name():
    owner = sj.owning_workspace(_known(), "/home/u/Github/shop_cloud", wsl=True)
    assert [w.hwnd for w in sj.vscode_candidates(WINDOWS, "/home/u/Github/shop_cloud", wsl=True, owner=owner)] == [2]
    assert sj.vscode_candidates(WINDOWS, "/home/u/Github/shop_cloud", wsl=True) == [], \
        "不知道它属于哪个工作区时，标题里确实没有这个文件夹名"

    translated = [Window(9, 10, "ops-check (工作区) [WSL: Ubuntu-24.04]", CODE)]
    assert [w.hwnd for w in sj.vscode_candidates(translated, "/x", wsl=True, owner=owner)] == [9], \
        "界面语言不是英文时括号里的词会变"


class _Desk:
    def __init__(self, windows=WINDOWS, known=None, focus_ok=True, code_ok=True):
        self.log: list = []
        self.kwargs = dict(
            windows=lambda: list(windows),
            focus=lambda hwnd: (self.log.append(("focus", hwnd)), focus_ok)[1],
            chain=lambda pid: [],
            uri=lambda uri: (self.log.append(("uri", uri)), True)[1],
            vscode=lambda detail, target="": (self.log.append(("code", target or detail.cwd)), code_ok)[1],
            workspaces=lambda: list(_known() if known is None else known),
            sleep=lambda seconds: None)


def _detail(**over) -> si.SessionDetail:
    return si.SessionDetail(**{"agent": "claude_wsl", "session_id": SID, "entrypoint": "claude-vscode",
                               "cwd": "/home/u/Github/shop_cloud", "distro": "Ubuntu-24.04",
                               "title": TITLE, "alive": True, **over})


URI = ("uri", f"vscode://anthropic.claude-code/open?session={SID}")


def test_jumping_to_a_session_in_a_multi_folder_workspace_focuses_that_window():
    desk = _Desk()
    result = sj.jump(_detail(), **desk.kwargs)
    assert result.ok and desk.log == [("focus", 2), URI], "不许去跑 code 命令——那会新开一个窗口"


def test_among_same_named_windows_the_one_showing_this_conversation_wins():
    desk = _Desk()
    detail = _detail(cwd="/home/u/Github-2/core-lib", title="Reduce memory use in the importer")
    assert sj.jump(detail, **desk.kwargs).ok and desk.log == [("focus", 4), URI]


def test_when_the_title_cannot_tell_them_apart_vscode_is_asked_for_the_exact_folder():
    """两个窗口标题一样、当前标签页又都不是这个对话：不蒙最靠前的那个，让 code 命令按确切的
    文件夹去聚焦（VS Code 按文件夹去重，已经开着的不会新开）。"""
    desk = _Desk()
    detail = _detail(cwd="/home/u/Github-2/core-lib", title="某个不在前台的对话")
    assert sj.jump(detail, **desk.kwargs).ok
    assert desk.log == [("code", "/home/u/Github-2/core-lib"), URI]


def test_a_workspace_whose_title_was_customised_away_is_still_reached_through_vscode():
    windows = [Window(2, 10, "随便起的窗口标题", CODE)]
    desk = _Desk(windows=windows)
    assert sj.jump(_detail(title="不在前台"), **desk.kwargs).ok
    assert desk.log == [("code", WORKSPACE_FILE), URI], "打开的是工作区文件，不是其中的文件夹"


def test_a_live_session_never_makes_a_new_window_when_vscode_has_no_window_for_it():
    """VS Code 的记录读得到，可里面没有哪个窗口包含这个目录：活着的会话一定有个窗口，
    只是我们认不出——说认不出，不要新开。"""
    desk = _Desk()
    result = sj.jump(_detail(cwd="/home/u/elsewhere/project", title="不在前台"), **desk.kwargs)
    assert not result.ok and desk.log == [] and "没认出" in result.message


def test_without_vscodes_record_the_tab_title_alone_can_still_find_the_window():
    desk = _Desk(known=[])
    assert sj.jump(_detail(), **desk.kwargs).ok and desk.log == [("focus", 2), URI]


def test_without_any_clue_the_old_fallback_still_opens_the_folder():
    desk = _Desk(known=[])
    result = sj.jump(_detail(title="不在前台"), **desk.kwargs)
    assert result.ok and desk.log == [("code", "/home/u/Github/shop_cloud"), URI]


def test_a_short_or_unrelated_tab_title_is_not_mistaken_for_the_session():
    windows = [Window(7, 10, "other [WSL: Ubuntu-24.04] - In…", CODE),
               Window(8, 10, "other [WSL: Ubuntu-24.04] - Incident report", CODE)]
    desk = _Desk(windows=windows, known=[])
    assert [step[0] for step in (sj.jump(_detail(), **desk.kwargs), desk.log)[1]] == ["code", "uri"]


def test_a_folder_open_both_alone_and_inside_a_workspace_is_a_tie_settled_by_the_tab_or_recency():
    """同一个文件夹既单独开着一个窗口、又是工作区的一员：路径分不出会话在哪个里。
    看谁的当前标签页是这个对话；都不是就取最近用过的那个——两种情况都不新开窗口。"""
    known = [*_known(), OpenWorkspace("api-gateway", ("/home/u/Github/api-gateway",),
                                      "/home/u/Github/api-gateway", wsl=True)]
    windows = [Window(6, 10, "api-gateway [WSL: Ubuntu-24.04] - notes.md", CODE), *WINDOWS]
    cwd = "/home/u/Github/api-gateway"
    assert sj.owning_workspace(known, cwd, wsl=True) is None
    assert [w.label for w in sj.owning_workspaces(known, cwd, wsl=True)] == ["ops-check", "api-gateway"]

    desk = _Desk(windows=windows, known=known)
    assert sj.jump(_detail(cwd=cwd), **desk.kwargs).ok and desk.log == [("focus", 2), URI], "标签页认出来了"

    desk = _Desk(windows=windows, known=known)
    assert sj.jump(_detail(cwd=cwd, title="不在前台"), **desk.kwargs).ok
    assert desk.log == [("focus", 6), URI], "认不出：取最靠前的那个候选"


def test_two_workspaces_sharing_a_folder_are_told_apart_by_where_the_session_started():
    """实机上就有：两个多文件夹工作区都包含同一个文件夹。插件把会话进程起在工作区的
    第一个文件夹里，运行清单记着那个启动目录——哪个工作区的第一个文件夹是它，就是哪个。"""
    other = OpenWorkspace("deploy", ("/home/u/Github/charts", "/home/u/Github/shop_cloud"),
                          "/home/u/workspace/deploy.code-workspace", wsl=True, multi_root=True)
    known = [other, *_known()]
    windows = [Window(6, 10, "deploy (Workspace) [WSL: Ubuntu-24.04] - values.yaml", CODE), *WINDOWS]
    assert len(sj.owning_workspaces(known, "/home/u/Github/shop_cloud", wsl=True)) == 2

    started_in_gateway = _detail(title="不在前台", extra={"start_cwd": "/home/u/Github/api-gateway"})
    desk = _Desk(windows=windows, known=known)
    assert sj.jump(started_in_gateway, **desk.kwargs).ok and desk.log == [("focus", 2), URI], \
        "ops-check 的第一个文件夹是 api-gateway；最靠前的 deploy 窗口不是它"

    started_in_charts = _detail(title="不在前台", extra={"start_cwd": "/home/u/Github/charts"})
    desk = _Desk(windows=windows, known=known)
    assert sj.jump(started_in_charts, **desk.kwargs).ok and desk.log == [("focus", 6), URI]

    unknown_start = _detail(title="不在前台")
    desk = _Desk(windows=windows, known=known)
    assert sj.jump(unknown_start, **desk.kwargs).ok and desk.log == [("focus", 6), URI], "没有线索：最近用过的"


# ---------------------------------------------------------------- VS Code 记着会话开在哪个窗口

def _state_db(folder, **items) -> str:
    """造一个窗口的状态库（``workspaceStorage/<id>/state.vscdb``）。"""
    import sqlite3

    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "state.vscdb")
    connection.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    connection.executemany("INSERT INTO ItemTable VALUES (?, ?)", list(items.items()))
    connection.commit()
    connection.close()
    return str(folder)


TAB_KEY, PLUGIN_KEY = "memento/workbench.parts.editor", "Anthropic.claude-code"


def test_the_window_whose_open_tabs_mention_the_session_is_the_one(tmp_path):
    with_tab = _state_db(tmp_path / "a", **{TAB_KEY: '{"editors":[{"session":"%s"}]}' % SID})
    in_plugin_state = _state_db(tmp_path / "b", **{PLUGIN_KEY: '{"recent":["%s"]}' % SID})
    unrelated = _state_db(tmp_path / "c", **{TAB_KEY: '{"editors":[]}', "other": SID})
    empty_dir = str(tmp_path / "no-db")
    a, b, c, d = (OpenWorkspace(name, ("/x/" + name,), "/x/" + name, wsl=True, storage=(folder,))
                  for name, folder in (("a", with_tab), ("b", in_plugin_state), ("c", unrelated), ("d", empty_dir)))

    assert sj.session_windows([b, c, a, d], SID) == [a], "开着的标签页压过插件状态里的一条旧记录"
    assert sj.session_windows([b, c, d], SID) == [b]
    assert sj.session_windows([c, d], SID) == [], "别的键里碰巧出现这串字符不算"
    assert sj.session_windows([a], "") == []


def test_each_open_window_is_paired_with_its_state_folder(tmp_path):
    user = tmp_path / "Code" / "User"
    (user / "globalStorage").mkdir(parents=True)
    (user / "globalStorage" / "storage.json").write_text(json.dumps(STATE), encoding="utf-8")
    for name, meta in (("id-ws", {"workspace": WSL.replace("ubuntu", "Ubuntu") + WORKSPACE_FILE}),
                       ("id-core2", {"folder": WSL + "/home/u/Github-2/core-lib"}),
                       ("id-core2-again", {"folder": "vscode-remote://wsl+Ubuntu-24.04/home/u/Github-2/core-lib"}),
                       ("id-closed", {"folder": WSL + "/home/u/Github/long-closed"}),
                       ("id-broken", None)):
        (user / "workspaceStorage" / name).mkdir(parents=True)
        (user / "workspaceStorage" / name / "workspace.json").write_text(
            json.dumps(meta) if meta else "{broken", encoding="utf-8")

    known = {w.target: w for w in sj.opened_workspaces(appdata=tmp_path, read_text=_read)}
    names = lambda target: sorted(folder.rsplit("id-", 1)[1] for folder in known[target].storage)  # noqa: E731
    assert names(WORKSPACE_FILE) == ["ws"]
    assert names("/home/u/Github-2/core-lib") == ["core2", "core2-again"], "发行版名大小写不同会各有一个目录"
    assert known["/home/u/Github/core-lib"].storage == ()


def test_vscodes_record_of_the_session_beats_guessing_from_folders(tmp_path):
    """两个工作区都包含这个文件夹、第一个文件夹还一样、对话又不在前台——路径和标题都分不出
    来（实机上正是这样）。VS Code 的状态库记着它是哪个窗口的标签页。"""
    mine = _state_db(tmp_path / "mine", **{TAB_KEY: '{"tabs":["%s"]}' % SID})
    theirs = _state_db(tmp_path / "theirs", **{TAB_KEY: '{"tabs":["some-other-session"]}'})
    ops = replace(next(w for w in _known() if w.label == "ops-check"), storage=(mine,))
    deploy = OpenWorkspace("deploy", ("/home/u/Github/api-gateway", "/home/u/Github/shop_cloud"),
                           "/home/u/workspace/deploy.code-workspace", wsl=True, multi_root=True, storage=(theirs,))
    windows = [Window(6, 10, "deploy (Workspace) [WSL: Ubuntu-24.04] - values.yaml", CODE), *WINDOWS]
    detail = _detail(title="不在前台", extra={"start_cwd": "/home/u/Github/api-gateway"})

    desk = _Desk(windows=windows, known=[deploy, ops])
    assert sj.jump(detail, **desk.kwargs).ok and desk.log == [("focus", 2), URI]


def test_a_session_that_wandered_outside_its_workspace_is_still_found_through_the_record(tmp_path):
    mine = _state_db(tmp_path / "mine", **{TAB_KEY: '{"tabs":["%s"]}' % SID})
    ops = replace(next(w for w in _known() if w.label == "ops-check"), storage=(mine,))
    desk = _Desk(known=[ops])
    result = sj.jump(_detail(cwd="/tmp/scratch", title="不在前台"), **desk.kwargs)
    assert result.ok and desk.log == [("focus", 2), URI]


def test_the_registry_start_folder_is_kept_even_after_the_session_moved_elsewhere():
    detail = si.SessionDetail(agent="claude_wsl", cwd="/home/u/Github/shop_cloud")
    si.apply_registry(detail, {"pid": 7, "cwd": "/home/u/Github/api-gateway", "entrypoint": "claude-vscode"})
    assert detail.cwd == "/home/u/Github/shop_cloud" and detail.extra["start_cwd"] == "/home/u/Github/api-gateway"


def test_a_wsl_terminal_inside_a_workspace_window_is_found_the_same_way():
    detail = _detail(entrypoint="cli")
    owner = sj.owning_workspace(_known(), detail.cwd, wsl=True)
    found = sj.find_wsl_terminal_window(WINDOWS, detail, {"TERM_PROGRAM": "vscode"}, owner=owner)
    assert found is not None and found.hwnd == 2


# ---------------------------------------------------------------- code 命令

def test_opening_a_project_reuses_the_workspace_window_it_is_part_of():
    """「最近的对话」里点一行也走 code 命令：项目是某个开着的工作区的一员时，
    该聚焦那个工作区，而不是为这个文件夹单独再开一个窗口。"""
    assert sj.vscode_target(_detail(), _known) == WORKSPACE_FILE
    assert sj.vscode_target(_detail(cwd="/home/u/Github-2/core-lib/src"), _known) == "/home/u/Github-2/core-lib"
    assert sj.vscode_target(_detail(cwd="/home/u/not/open"), _known) == ""

    def broken():
        raise OSError("storage.json 读坏了")

    assert sj.vscode_target(_detail(), broken) == ""


def test_the_code_command_targets_the_workspace_file_in_the_right_distro():
    detail = _detail()
    assert sj.vscode_command(detail, WORKSPACE_FILE, code="code.cmd") == [
        "code.cmd", "--remote", "wsl+Ubuntu-24.04", WORKSPACE_FILE]
    assert sj.vscode_command(detail, "", code="code.cmd")[-1] == "/home/u/Github/shop_cloud"
    local = si.SessionDetail(agent="claude", cwd=r"C:\code\proj")
    assert sj.vscode_command(local, "", code="code.cmd") == ["code.cmd", r"C:\code\proj"]
    assert sj.vscode_command(si.SessionDetail(agent="claude_wsl", cwd="/x"), "", code="code.cmd") is None, \
        "不知道是哪个发行版就不猜"
