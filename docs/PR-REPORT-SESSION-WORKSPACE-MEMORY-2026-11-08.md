# PR 报告：「跳到对话」记住会话当时的 VS Code 工作区（冻结后按它重开，不借别的工作区）

> **基线**：`132a8c18`（main，Merge PR #29）
> **分支**：main 工作树（未提交）　**日期**：2026-11-08
> **范围**：13 个文件（实现 7、测试 4、文档 2）
> **关联**：[`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md)（冻结鱼、`resume_in_vscode`）、
> `tests/test_session_jump_workspaces.py` 模块说明（2026-10-12 多文件夹工作区的找窗口规则）

## 一、核心特性

用户 2026-11-08 看「最近的对话」/ 冻结小鱼的卡片时发现：一个 WSL 会话（`Api-gateway removal in 7.2.0`，目录
`/home/limin/Github/aella_cloud`）的卡片写着 **connect-check · 多文件夹工作区 · 7 个文件夹**，可它当时根本不是开在
connect-check 里。核对代码与实机数据后确认了用户的判断，而且比想的更糟：

- 「最近的对话」（`HistoryEntry`）只存目录，**没有工作区**；
- 卡片上的工作区那一行是打开卡片时**现算**的（`attach_workspace`）：先查现在开着的窗口的状态库有没有提到这个会话，
  查不到就退到「现在开着的窗口里谁包含这个目录」——它回答的是「现在谁装得下它」，不是「它当时在哪」；
- 「跳到对话」（冻结鱼走 `resume_in_vscode`，列表里点一行走 `open_in_vscode`）用的是同一套现算：原工作区关了、另一个开着的
  工作区恰好也包含这个目录 → 对话被重开到**别人的工作区**里；没有哪个开着的工作区包含它 → `code --remote … <目录>`
  只开文件夹**新开一个窗口**，工作区丢了。
- 实机：这条会话最后开在一个**未命名**的多文件夹工作区（`Code/Workspaces/1793934561968/workspace.json`，状态库 11-08 00:15
  落盘）里；那个窗口关掉后 VS Code 把未命名工作区的文件删了，现在开着的 connect-check 包含 `aella_cloud`，于是卡片把它算成了
  connect-check，点「跳到对话」就会在 connect-check 里重开。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 活着时记下工作区 | `HistoryEntry.workspace = {label, target, multi_root, roots}`。来源有三：详情卡 / 跳转读详情时认出的（`SessionPetActions._on_detail_ready` → `SessionPetController.note_workspace`）；`SessionHistoryService` 收到 VS Code 会话的更新后在后台认一次（每会话 10 分钟一次，`WORKSPACE_RECHECK_S`）；从 VS Code 状态库找回的（见 3）。**文件夹列表必须记**：未命名工作区关掉即删文件，之后只能靠列表重建 |
| 2 | 重开先认记录 | `resume_in_vscode`：记录里的工作区**开着**（按工作区文件 / 文件夹对，未命名的按文件夹集合对）→ 只在那个窗口里找（`_jump_vscode(pinned=…)`）；**没开** → 按记录把它开回来再发插件深链：工作区文件还在就 `code <文件>`，文件没了（未命名）就 `code 目录1 目录2 …`（VS Code 开成一个多文件夹窗口），单文件夹就开那个文件夹。**不再借**别的恰好也包含这个目录的工作区。「最近的对话」里点一行（`vscode_target`）同样先认记录 |
| 3 | 老会话回填 | 改之前就冻结、历史里没记工作区的会话：`workspace_from_storage` 翻 VS Code **关掉的窗口**留下的状态库（`workspaceStorage/<id>/state.vscdb` 提到过这个会话 ID 的，「开着的标签页」压过「只在插件状态里」、再按落盘时间新到旧），旁边的 `workspace.json` 指着当时的工作区；还原得出文件夹的头一个算数，顺手记进历史（不动最后活动时间）。详情卡读详情、冻结鱼重开、列表点一行三处都会试 |
| 4 | 冻结的会话不再按目录猜 | `attach_workspace` 对进程已不在的会话只认「VS Code 自己记着这个会话是它的标签页」的开着的窗口；历史里记的那份照留。否则卡片会继续显示借来的工作区，还会被 1 记进历史、把正确的记录覆盖掉 |
| 5 | 未命名的 WSL 工作区能被认出 | 窗口记录里它是 `file:///c:/…/Code/Workspaces/<id>/workspace.json` + `remoteAuthority: wsl+…`，里面的文件夹是 WSL 地址。以前按本机路径读、发行版对不上，整个窗口被跳过（实机：现在开着的 ath-core + generic-api-gateway 那个窗口以前就是隐形的）。`workspaces_from_state` 认 `remoteAuthority`，`opened_workspaces` 给它配上状态库目录 |

**红线 / 不变量**：活着的会话的跳转规则不变（VS Code 状态库 → 目录 → 启动目录 → 标题 / 当前标签页 → `code` 命令）；
历史文件只多一个 `workspace` 键，老文件照读；`code` 命令仍只在「认不出 / 没开着」时才跑；不读对话内容。

## 二、修改文件说明

`git diff --numstat`（基线 `132a8c18`）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_session_history.py` | +37 / −4 | `HistoryEntry.workspace: dict`；`normalize_workspace()`（只认 label / target / multi_root / roots，截长度）；`record(workspace=)` 非空才覆盖；`note_workspace(key, ws)` 只改工作区不动 `last_seen`；`load()` 带上 `workspace` |
| `pet/claude_session_jump.py` | +210 / −24 | `workspace_record` / `recorded_workspace` / `open_workspace_matching` / `reopen_targets` / `_workspace_file_exists`；`vscode_command` 接受一列路径；`vscode_target` 先认记录；`_jump_vscode(pinned=)`；`resume_in_vscode` 三分支（记录开着 / 记录没开 / 没记录）；`workspace_from_storage` + `_storage_workspace`（关掉的窗口回填）；`attach_workspace` 对冻结会话只认状态库；`workspaces_from_state` 认 `remoteAuthority`、`opened_workspaces` 按本机路径也能配到状态库目录；模块说明补一条 |
| `pet/session_history_service.py` | +82 / −5 | `SessionHistoryService`：`_maybe_resolve_workspace`（后台线程认工作区，`_workspace_found` 信号排队回 GUI 线程，每会话 `WORKSPACE_RECHECK_S` 一次，`gone` 不认）、`note_workspace` 槽、`resolve_workspace` 可注入；`SessionHistoryActions._detail` 带上记录，`_do_vscode` 没记录时查状态库并回写（`find_workspace` / `note_workspace` 可注入），结果文案用工作区名 |
| `pet/session_pet_ui.py` | +24 / −3 | `_detail_for_key` 把历史里的工作区放进 `extra`（冻结鱼）；`_on_detail_ready` 把认出的工作区交给控制器记历史；`resume_key` 的线程里没记录就 `workspace_finder` 回填并经 `_detail_ready` 记进历史；`load_detail` 对冻结会话回填；卡片文件夹数没有 `folders` 时按 `roots` 算 |
| `pet/overlay_session_pets.py` | +13 / −1 | `_frozen_info` 带上 `workspace`；`note_workspace(key, ws)` 转给历史服务并同步冻结鱼的信息（用历史归一过的那份） |
| `pet/locale/zh.json` / `en.json` | +2 / +2 | `session_jump.ui.reopened_conversation_in_workspace`、`session_jump.ui.could_not_reopen_workspace` |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_session_workspace_memory.py` | 新增，27 条 | 记录的形状与落盘；重开先认记录（开着 → 聚焦那个窗口而不是更靠前的 ops-check；关了 → 开工作区文件而不是借 ops-check；未命名文件没了 → 按文件夹列表开；换了文件名的未命名工作区按文件夹集合对上；单文件夹；没记录照旧；code 命令失败的文案）；`code` 命令多路径；`vscode_target` 认记录；冻结会话的卡片不借工作区但认状态库、`load_detail` 回填；未命名 WSL 工作区按 `remoteAuthority` 认出；`workspace_from_storage`（标签页压过插件状态、本机 / WSL / 发行版不互认、文件没了退到下一个候选、未命名 WSL 工作区文件还在时还原文件夹、30 天外不看）；服务层活着时认一次并 10 分钟内不重复、终端 / gone 不认、认失败不动记录；列表点一行带记录 / 查状态库并回写 |
| `tests/test_overlay_session_pets.py` | +75 / −0 | 冻结 VS Code 鱼的详情带着历史里的工作区（有记录就不翻状态库）；老冻结鱼从状态库回填并记进历史（`last_seen` 不动、`describe` 跟着变）；活鱼详情卡认出的工作区记进历史；既有重开用例改为不读真实状态库 |
| `tests/test_claude_session_history.py` | +1 / −1 | 落盘字段清单加 `workspace` |
| `tests/test_session_card_metro.py` | +2 / −1 | `attach_workspace` 的记录多了 `roots`，断言跟上 |

### 未改动

`vscode_workspaces.py`（右键菜单「VS Code 工作区」：列最近用过的工作区时未命名 WSL 工作区仍按本机路径列，另案）；
`claude_session_info.py`（运行清单 / transcript 的读取没变）；活着的会话的 `jump()` 路径；历史文件的其余字段与裁剪规则。

## 三、实现要点

- **记录的形状**：`{"label", "target", "multi_root", "roots": [...]}`。`target` 是交给 `code` 就能聚焦到那个窗口的路径
  （工作区文件或文件夹）；`roots` 是它包含的文件夹——未命名工作区的 `target` 是 `Code/Workspaces/<id>/workspace.json`，
  窗口一关文件就没了，只有 `roots` 能把它重建出来（`code --remote wsl+<发行版> 目录1 目录2`，VS Code 开成一个未命名的多文件夹窗口）。
  `normalize_workspace` 丢掉 `folders` 这类展示用的键、截长度，历史文件里只有这四项。
- **三处写入、一个入口**：详情卡 / 跳转读详情（`load_detail` → `attach_workspace`）、历史服务收到会话更新后的后台认领、
  状态库回填，最终都经 `SessionHistoryService.note_workspace` → `SessionHistory.note_workspace`。它只改工作区、不动 `last_seen`，
  所以补记老会话不会把它顶到列表最前；有变化才启动落盘定时器。
- **重开的优先级**：历史记录 > VS Code 状态库（开着的窗口里哪个记着这个会话的标签页）> 目录 / 启动目录 > 标题 / 当前标签页 >
  `code` 命令。记录开着时 `_jump_vscode(pinned=那个窗口)`：候选只剩它，标题独一无二就直接调前台，同名的还有别的窗口（或标题被
  自定义掉）就 `code <它的 target>`——VS Code 按文件夹 / 工作区文件去重，只会聚焦。状态库的唯一记录仍可压过 `pinned`
  （它是 VS Code 自己记的）。
- **冻结的会话不按目录猜**（第四项）是这次最关键的一刀：活着的会话一定开在某个窗口里，按目录找是对的；进程已不在的会话，
  「现在开着的窗口里谁包含这个目录」说明不了任何事——那正是把对话重开到别的工作区里的来由。`attach_workspace` 按
  `detail.alive is False or detail.phase == "frozen"` 分流。
- **状态库回填的顺序**：候选按（提到的方式：2 = 开着的标签页 / 1 = 只在插件状态里，落盘时间）排序，逐个还原，**头一个还原得出
  文件夹的算数**。实机这条会话：第一候选是已删文件的未命名工作区（还原不出），退到 11-05 的单文件夹窗口 `aella_cloud`——
  这是它真实开过的窗口，比借 connect-check 诚实；原来那个未命名工作区的文件夹列表已无从得知，改之后新开的会话才会记。
- **线程**：历史服务的认领在 `spawn`（默认真线程）里跑，结果经 `_workspace_found` 信号排队回 GUI 线程；`SessionPetActions` 的
  重开线程经既有的 `_detail_ready` 信号回来。读 VS Code 的都是只读（`sqlite3` 以 `mode=ro` 打开，`timeout=1.0`）。

## 四、性能分析

**方法（可复现）**：本机 `.venv` Python 3.13.15、Windows 11 26300，`timeit`，对真实的 `%APPDATA%\Code`
（`workspaceStorage` 65 个目录、2 个开着的窗口）；脚本内容见本报告实机记录一节的命令（直接 `python -` 喂入）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `opened_workspaces()`（读 storage.json + 2 个工作区文件 + 配状态库目录） | 均值 18.6 ms / 最好 18.0 ms（20 次） | 既有路径；多了一次 `remoteAuthority` 判断与一次字典查找 |
| `attach_workspace(活着的会话)` | 均值 19.4 ms / 最好 17.5 ms（20 次） | 既有路径（详情卡 / 跳转，后台线程）；历史服务新增的后台认领也走它，**每会话每 10 分钟 1 次** |
| `attach_workspace(冻结的会话)` | 均值 25.9 ms / 最好 16.5 ms（20 次） | 既有路径；少了按目录猜，多了只查状态库 |
| `workspace_from_storage(实机会话)` | 均值 23.1 ms / 最好 22.9 ms（10 次） | **新增**：65 个状态库各查一次小库（`instr` 两个键）；只在冻结会话没记录时触发（详情卡 / 重开在后台线程；列表点一行在 GUI 线程，一次点击一次） |
| `workspace_from_storage(没人提到的 id)` | 均值 22.5 ms / 最好 18.5 ms（10 次） | 同上，找不到时的成本 |
| 单元测试（6 个相关文件 222 条） | 2.9 s | — |

**结论**：① 稳态开销：每次会话更新多一次字典查找与时间比较（`_maybe_resolve_workspace` 的节流判断），无感；② 新增路径：活着的
VS Code 会话每 10 分钟一次 ~20 ms 的后台读取；冻结会话没记录时一次 ~23 ms 的状态库扫描，之后有记录就不再扫；③ 新的系统调用：
只有读文件与只读打开 sqlite，没有网络；新增线程只在历史服务认领时起一个短命线程（与回填扫描同一套 `spawn`）；④ 内存：每条历史
多一个最多 50 项路径的列表（实机 7 项），`_workspace_checked` 每个活着的会话一个浮点数。

## 五、实机运行记录

本机真实数据（只读探针，没起 `code` 命令，没动肥鱼的历史文件）：

**根因复现**（改之前）：

```
# VS Code 现在开着的窗口（storage.json）
vscode-remote://wsl%2Bubuntu-24.04/home/limin/workspace/connect-check.code-workspace | wsl+ubuntu-24.04
file:///c%3A/Users/limin/AppData/Roaming/Code/Workspaces/1793351401937/workspace.json | wsl+ubuntu-24.04

# 哪些窗口的状态库提到过这条会话（6eb3828f）
11-08 00:15 multi  file:///c%3A/Users/limin/AppData/Roaming/Code/Workspaces/1793934561968/workspace.json
     key: Anthropic.claude-code / memento/workbench.parts.editor      ← 最后把它当标签页的窗口：未命名工作区，文件已被 VS Code 删掉
11-05 19:09 folder vscode-remote://wsl%2Bubuntu-24.04/home/limin/Github/aella_cloud
     key: Anthropic.claude-code

# 肥鱼历史里的那一行：只有目录
{"agent": "claude_wsl", "session_id": "6eb3828f-…", "cwd": "/home/limin/Github/aella_cloud", "entrypoint": "claude-vscode", …}
```

connect-check.code-workspace 的 7 个文件夹里有 `../Github/aella_cloud` → 卡片把它算成 connect-check（与截图一致）。

**改之后的探针**（同一份数据）：

```
现在开着的窗口（VS Code 自己记的）：
   connect-check | wsl | multi | target: /home/limin/workspace/connect-check.code-workspace | roots: (…7 个…) | storage: 1
   Untitled      | wsl | multi | target: c:/Users/limin/AppData/Roaming/Code/Workspaces/1793351401937/workspace.json
                 | roots: ('/home/limin/Github-2/ath-core', '/home/limin/Github/generic-api-gateway') | storage: 1   ← 改之前这个窗口是隐形的
截图那条会话从关掉的窗口状态库里找回的工作区：
   {'label': 'aella_cloud', 'target': '/home/limin/Github/aella_cloud', 'multi_root': False, 'roots': ['/home/limin/Github/aella_cloud'], 'folders': 1}
活着时认出的工作区: connect-check | 冻结时: None    ← 冻结的会话不再按目录猜
```

**用户可见行为**（推演，未在本机点过——点下去会真的重开对话、改动 VS Code 窗口）：现在点这条冻结鱼的「跳到对话」会按回填到的
`aella_cloud` 单文件夹窗口重开（`code --remote wsl+Ubuntu-24.04 /home/limin/Github/aella_cloud` + 插件深链），而不是在 connect-check
里重开；卡片上的工作区行显示 `aella_cloud · VS Code 工作区`。原来那个未命名工作区的文件夹列表已经丢了（VS Code 删的），
救不回来；**改之后新开的 VS Code 会话**活着时就会把工作区（含文件夹列表）记进历史，关掉工作区后重开能原样重建。

**边界 / 失败路径**：`workspace_from_storage` 对一个没人提到的会话 ID 返回 `{}`（上表 22.5 ms）；冻结会话 `attach_workspace`
返回 `None`（不借）。

**为什么没有点击实测**：重开会真的往用户的 VS Code 里发深链、可能新开窗口，属于改动用户桌面的操作，本轮未经用户要求不做；
跑着的肥鱼实例用的还是旧代码，要重启后才生效。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv\Scripts\python -m ruff check pet tests` | All checks passed |
| 聚焦 | `pytest -q tests/test_session_workspace_memory.py tests/test_session_jump_workspaces.py tests/test_claude_session_history.py tests/test_session_history_service.py tests/test_session_pet_details.py tests/test_overlay_session_pets.py` | 222 passed（2.9 s） |
| 全量 | `pytest -q tests --ignore=tests/test_persona_presets_english.py` | 一个进程跑整套在这台机器上跑不完（见下方追记）；改为**逐文件各起一个进程**：353 个文件，345 个全绿，8 个有失败的文件与**未改动的 main 基线逐文件对照数目一致**（`git stash` 后同命令复测），都不在本改动的路径上 |
| 报告纪律 | `pytest -q tests/test_pr_report_discipline.py` | 139 passed（本报告已登记在 `docs/INDEX.md`） |

**追记：全量为什么不是一个数字**。同一进程跑整套，第一遍（`-x`）531 passed、1 skipped 后在
`test_bubble_image_natural_size.py` 停下（该文件单独跑 20 passed）；第二遍不带 `-x`，在 `test_alert_queue.py` 的
`win` fixture 处先出现 `Windows fatal exception: code 0x8001010d`（RPC_E_CANTCALLOUT_ININPUTSYNCCALL，真窗口与桌面
消息循环之间的），到 `test_session_card_metro.py::test_hovering_or_clicking_the_row_icon_shows_the_whole_value`
（卡片悬停 `reveal`，本次没改的代码）时 access violation 把进程带崩，没有汇总。这套测试里有一批要真窗口、真前台、
真鼠标输入的用例（`QT_QPA_PLATFORM` 没设 offscreen），和桌面上正在发生的事互相干扰。于是逐文件各起一个进程：

| 单独跑有失败的文件 | 带本改动 | main 基线（stash 后） | 判定 |
|---|---|---|---|
| `test_session_card_metro.py` | 1 failed / 51 passed（`test_host_icons_are_warmed_at_the_cards_size`：预热尺寸 `[21, 14]` vs 期望 `[21]`） | 1 failed / 51 passed | 基线就挂：11-02 小鱼标签图标那次多预热了 14 px 的胶囊尺寸，这条 10-28 的断言没跟上。另一条 `test_attach_workspace_only_touches_vscode_sessions_and_survives_bad_records` 是本改动让记录多了 `roots`，已更新断言 |
| `test_island_history_panel.py` | 1 failed / 22 passed（`test_header_and_rows_are_painted_as_tiles_not_bare_text`，画出来的缝隙颜色 alpha） | 同 | 基线就挂，绘制相关 |
| `test_drag_move_coalescing.py` | 6 failed / 7 passed | 同 | 基线就挂 |
| `test_pet_interaction_locks.py` | 3 failed / 14 passed | 同 | 基线就挂 |
| `test_module_level_validation.py` | 2 failed / 3 passed | 同 | 基线就挂 |
| `test_desktop_pet_features.py` | 2 failed / 93 passed | 同 | 基线就挂 |
| `test_island_usage_polish.py` | 2 failed / 12 passed | 同 | 基线就挂 |
| `test_proactive.py` | 1 failed / 68 passed | 同 | 基线就挂 |
| `test_foreground_steal.py` | 逐文件那轮 1 failed / 1 passed，随后单独重跑两次都 2 passed | 2 passed | 真鼠标输入 + 真前台的用例，跑的时候桌面上还有别的 pytest 窗口在起落；与本改动无关（`PetWindow` 的扩展样式） |

本改动直接相关的 7 个测试文件（`test_session_workspace_memory.py`、`test_session_jump_workspaces.py`、
`test_claude_session_history.py`、`test_session_history_service.py`、`test_session_pet_details.py`、
`test_overlay_session_pets.py`、`test_session_card_metro.py` 去掉上面那条基线就挂的）全绿。

## 七、已知限制与后续

- 未命名工作区**关掉后**才装肥鱼（或改之前就关了）的会话：VS Code 已删文件、肥鱼没记列表，只能退到状态库里下一个提到过它的窗口；
  没有就照旧按目录。
- 未命名工作区开着、但标题分不出（两个 `Untitled (Workspace)`）且状态库还没落盘时，退路 `code --remote … <本机路径的 workspace.json>`
  不一定能聚焦到它；实机上同时开两个未命名 WSL 工作区的情形暂未遇到。
- 历史服务每 10 分钟认一次工作区：用户刚把文件夹加进工作区的前 10 分钟里，记录是旧的；冻结后重开会少 / 多一个文件夹。
- 右键菜单「VS Code 工作区」（`vscode_workspaces.recent_entries`）列最近用过的工作区时仍不认未命名的 WSL 工作区，另案。

## 八、风险与回滚

- 影响面：冻结鱼的「跳到对话」、「最近的对话」里点 VS Code 会话、详情卡的工作区行、历史文件多一个键。活着的会话的跳转不变。
- 配置：没有新增配置键；历史文件 `claude-session-history.json` 多出 `workspace` 字段，回滚后旧代码 `load()` 只取 `_FIELDS` 里的
  字符串字段，这个键被忽略、下次落盘即消失，无残留。
- 回滚：`git revert` 本次提交即可；没有迁移。
