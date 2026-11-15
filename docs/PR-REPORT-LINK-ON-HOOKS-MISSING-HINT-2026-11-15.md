# PR 报告：Claude Code 联动开着、hooks 却不在时，肥鱼说出来，并给一条走同意弹窗的修复项

> **基线**：`dbc69f6f`（PR #50，测试不再起真的 wsl.exe）
> **分支**：`feature/link-on-hooks-missing-hint`　**日期**：2026-11-15
> **范围**：10 个文件（实现 4、文字表 2、测试 4）+ 本报告与索引
> **关联**：[`PR-REPORT-SESSION-FISH-DESKTOP-JUMP-THAW-2026-11-14.md`](PR-REPORT-SESSION-FISH-DESKTOP-JUMP-THAW-2026-11-14.md)（两个 Claude Code 联动改成默认开）；PR #50（那轮把 hooks 卸掉的测试的修复）

## 一、核心特性

2026-11-14 一轮全量测试把开发机 WSL 发行版里肥鱼的 9 个 Claude Code hooks 卸掉了（PR #50 修的是测试）。之后联动开关一直开着，肥鱼一声不吭：WSL 里的会话小鱼还在（靠运行清单认领），但阶段停在认领那一刻，不再有「干活中 / 等你回复」的切换、待批准提醒和收工气泡。用户能看到的只是「小鱼不动了」，看不出原因。

同一个状态还有一条正常的来路：#43 之后两个 Claude Code 联动默认是开的，而注入 hooks 要经用户同意（`AgentLinkManager.set_enabled` 的弹窗，`apply_config` 从不写）。所以全新安装的用户一开始就处在「开着但从没注入过」。

这个 PR 让肥鱼在这个状态下说出来，并把修复放到手边。它不代用户注入。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 通道起来后查一次 hooks 在不在 | 联动开着的 Claude Code 通道（本机 / WSL）启动 5 秒后，在后台线程只读地看一眼那边的 `settings.json`：9 个事件里哪些没有肥鱼的条目 |
| 2 | 缺了就冒一条气泡 | 「Claude Code (WSL) 联动开着，但它的 settings.json 里缺肥鱼的 hooks（9 个事件），状态收不全。右键 → Agent 联动 里可以重新配置。」气泡经壳的 `show_bubble`，所以也进岛的消息记录，错过了还能翻到 |
| 3 | 菜单里多一条修复项 | 右键 → Agent 联动，缺 hooks 的那个通道下面紧跟一条「缺 hooks，点此重新配置…」。没缺的时候菜单和以前一样 |
| 4 | 修复仍然走同意弹窗 | 修复项调 `AgentLinkManager.repair_hooks`，它就是 `set_enabled(通道, True)`：弹的是开启联动时那个同意框。点「否」什么都不写，联动也不会因此被关掉 |
| 5 | 判断不了就不说 | 那一侧没有 `~/.claude`（没用过 Claude Code）、WSL 没响应、`settings.json` 读不出或不是合法 JSON：不提示 |

**红线 / 不变量**：

- **不绕过同意流程**。检查只读；写 `settings.json` 的仍然只有 `set_enabled` 弹窗之后的那一条路（和迁移数据目录时的 `_refresh_moved_hooks`，没动）。
- **不卡界面**。本机读文件和 WSL 那一次 `wsl.exe` 都在后台线程，结果经信号回 GUI 线程。
- **不反复打扰**。一个通道从「没在跑」变成「在跑」时才查一次；别的设置变了重新 `apply_config` 不会再查、再弹。
- **不误报**。用户同意并装好之后，在那之前发起的检查即使迟到也不算数（按轮次丢弃）。
- **测试不读真机**。`CHECK_HOOKS_PRESENT` 在 `conftest` 里关掉，要测这项检查的用例自己打开，并把 `settings.json` 的路径指到临时目录。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_hooks.py` | +30 / −0 | 纯函数 `missing_hook_events(data)`：按 `HOOK_EVENTS` 的顺序列出没有肥鱼条目的事件（认标记，也认没有标记的旧条目；形状不对的 settings 按「一条都没装」算）。`WslSettingsStore.peek()`：同 `read()`，但发行版里连 `~/.claude` 都没有时也返回 None，一次 `wsl.exe`、只读 |
| `pet/agent_link.py` | +126 / −0 | `ClaudeCodeMonitor.missing_hooks()` / `missing_wsl_hooks(runner=…)`：两侧各自的只读检查，判断不了返回 None。`AgentLinkManager`：`apply_config` 在通道启动时 `_schedule_hooks_check`、停下时 `_forget_hooks_state`；单发定时器 → 后台线程 `<通道>-hooks-check` → 信号 `hooks_checked` → `_on_hooks_checked`（记状态、写日志、冒气泡）；公开面 `hooks_missing(通道)` 与 `repair_hooks(通道)`；两处安装成功的地方记 `_note_hooks_installed`（清标记、轮次加一） |
| `pet/context_menus/shared.py` | +6 / −0 | `add_agent_link_menu`：通道勾着、宿主有 `agent_hooks_missing` / `repair_agent_hooks` 且报缺时，紧跟一条修复项 |
| `pet/sprite_menu_facade.py` | +13 / −0 | overlay 拓扑的 `agent_hooks_missing`（问共享管理器）与 `repair_agent_hooks`（交给管理器；本机通道装好后冒一条「配置好了」，WSL 的由管理器在后台装完后自己冒） |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +3 / −0 | 气泡、菜单项、修复完成三条文案 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_claude_hooks_missing.py` | +366 / −0（新增） | 管理器公开面：缺了冒一条气泡并报出缺的事件、检查不写文件；联动不重启就不重复查；都在则安静；三种「判断不了」不提示；有 `~/.claude` 没有 settings 算缺；联动关着不读；修复被拒绝什么都不写且联动不被关；同意后装好并清标记；迟到的旧结论不算数；关掉联动忘掉标记；WSL 检查一次读、零次写、在后台线程；WSL 后台安装完成后清标记；菜单多出 / 不多出修复项 |
| `tests/test_claude_hooks.py` | +19 / −0 | `missing_hook_events`：顺序、别人的 hook 不算、旧条目算、脏形状 |
| `tests/test_sprite_menu_parity.py` | +33 / −0 | overlay 的真菜单里点修复项落到共享管理器的 `repair_hooks`；管理器没有这个能力时菜单照常 |
| `tests/conftest.py` | +3 / −0 | 在已有夹具 `_no_real_session_history_scan` 里关掉 `CHECK_HOOKS_PRESENT`（没有新增 autouse 夹具） |

### 未改动

- `pet/window.py`（旧 `PetWindow`）：按工程约定只修崩溃。它的菜单宿主没有 `agent_hooks_missing`，所以不出修复项；气泡经管理器照常出现，修复可以用「关掉再打开」。
- `set_enabled` 的同意弹窗文案、`install_hooks` / `install_wsl_hooks` / 卸载：没动。
- 配置全景（`pet/panorama`）已经把这个状态标成地图上的一条待办；这里是肥鱼自己的提示，两者各读各的。

## 三、实现要点

- **什么时候查**：`apply_config` 里，一个 Claude Code 通道的监视器从「没在跑」变成「在跑」的那一刻（启动肥鱼、从设置里打开联动）。已经在跑的通道不查。刚经同意弹窗装好的通道也不查（`_hooks_state` 里已经是「没缺」）。
- **为什么等 5 秒**：气泡只发给可见的窗（`MultiWindowProxy.show_bubble`）。本机的检查不到 1 毫秒就有结论，那时肥鱼可能还没出场，气泡会被丢掉。等 5 秒也让那一次 `wsl.exe` 不和启动抢。
- **线程模型**：GUI 线程上的单发定时器 → 起一条 daemon 线程 → 线程里只读 → `hooks_checked` 信号排队回 GUI 线程。和 `install_finished` 是同一个模式；管理器已经销毁时 `emit` 抛 `RuntimeError`，吞掉。
- **轮次**：每个通道一个计数，「装好了」和「通道停了」时加一。检查发起时带着当时的轮次，定时器到点和结果回来时各核对一次，对不上就丢。这样「检查还在 WSL 里跑、用户已经点了同意并装好」不会再冒出一条过期的提示。
- **「判断不了」和「没缺」存成同一个值**（`()`）：对菜单和气泡来说都是「没什么可说的」。没查过 / 通道关着是 None。
- **取舍：只在通道启动时查，不周期性查**。运行中被别的东西卸掉（11-14 那次就是）要到下次启动肥鱼才提示。周期性查 WSL 意味着每次起一个 `wsl.exe`；本机可以看文件修改时间，但两侧行为不一致。先做便宜且确定的这一半。
- **取舍：缺一个也提示**。升级后 `HOOK_EVENTS` 多了一个事件，旧用户也会看到提示——这是对的：`apply_config` 不写，新事件只有重新同意一次才会装上。

## 四、性能分析

**方法（可复现）**：在仓库根目录跑下面这段（只读；输出只有「缺几个」和耗时，不含文件内容）。环境：Windows 11（10.0.26300）、Python 3.13.15、PySide6 6.12.0；WSL 发行版已在运行（热）。

```
.venv\Scripts\python.exe -c "
import statistics, time
from pet.agent_link import ClaudeCodeMonitor as M
def bench(fn, n):
    ms = []
    for _ in range(n):
        t0 = time.perf_counter(); out = fn(); ms.append((time.perf_counter() - t0) * 1000)
    return f'missing={None if out is None else len(out)} n={n} median={statistics.median(ms):.2f}ms min={min(ms):.2f} max={max(ms):.2f}'
print('local', bench(M.missing_hooks, 200))
print('wsl  ', bench(M.missing_wsl_hooks, 20))
"
local missing=0 n=200 median=0.09ms min=0.08 max=0.31
wsl   missing=9 n=20 median=88.69ms min=84.34 max=96.37
```

| 指标 | 实测 | 归属 |
|---|---|---|
| 本机检查一次（判断目录 / 文件 + 读 + 解析） | 中位 0.09 ms（n=200，0.08–0.31） | 新增，后台线程，每次通道启动一次 |
| WSL 检查一次（一次 `wsl.exe`，发行版已在运行） | 中位 88.69 ms（n=20，84.34–96.37） | 新增，后台线程，每次通道启动一次 |
| WSL 检查起的 `wsl.exe` 次数 / 其中带输入（= 写）的次数 | 20 次检查起 20 次 / 0 次（另一次计数探针，包住 `subprocess.run` 数的） | 新增 |
| 从桌宠拿到单实例锁到两条检查结论落日志 | 约 5 秒（下面实机记录的时间戳：11:34:46 拿到锁 → 11:34:51.332 本机、11:34:51.428 WSL；5 秒是有意的延迟，WSL 比本机晚 96 ms） | 新增 |
| 受影响测试族总耗时 | 125 个文件 281.63 秒 | 测试 |

**结论**：

1. **稳态开销**：没有变化。没有新的定时器在转、没有轮询；检查做完就结束。每次打开右键菜单，两个 Claude Code 项各多一次 `dict.get`，不读盘、不起进程。
2. **新增路径的成本与频率**：每个开着的 Claude Code 通道在「从没在跑变成在跑」时一次——启动肥鱼时一次，之后只有关掉再打开联动才会再有。成本见上表。发行版冷启动时的耗时没有测（不能为了测量关掉正在用的 WSL）；`run_wsl` 的超时是 30 秒，超时按「判断不了」处理，不提示。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：没有网络。本机一次目录判断、一次文件判断、一次读文件。WSL 一次 `wsl.exe` 进程。每次检查一条 daemon 线程（`claude-hooks-check` / `claude_wsl-hooks-check`），跑完即退。这不是 WSL 通道第一次在启动时起 `wsl.exe`：运行清单认领（`_adopt_registry_sessions`）在监视器第一轮轮询就起，之后每 60 秒一次，所以这次检查不会唤醒一个本来不会被唤醒的发行版。**没有任何写盘**：WSL 的 `settings.json` 在实机运行前后修改时间相同（见下）。
4. **内存**：管理器多两个字典，各最多 2 个键（两个通道）；值是最多 9 个事件名的元组和一个整数。不随运行时间增长。

## 五、实机运行记录

本机真实环境（开发机，Windows + WSL，两个 Claude Code 联动都开着；WSL 那一侧的 hooks 自 11-14 起确实不在）。

**1. 前提的现场复现（只读探针）**。上面性能一节的命令同时就是现场：本机 `missing=0`，WSL `missing=9`——问题此刻真实存在。

**2. 从这个分支起肥鱼**（结束主进程，`Start-Process .venv\Scripts\BigFish.exe -m pet`，工作目录是本分支的工作区；真实 `APPDATA`）：

```
before: WSL settings.json mtime/size = 2026-11-15 01:16:23.841278655 -0800 13287
running: pid=37448 settings=False started=11/15/2026 03:21:42
gate: 2026-11-15 11:34:46 acquired pid=15912 lock=…ig-fat-fish\overlay-instance.lock
2026-11-15 11:34:51,332 INFO Claude Code 联动：hooks 都在
2026-11-15 11:34:51,428 WARNING Claude Code (WSL) 联动开着，但 settings.json 里缺肥鱼的 hooks（9 个事件）：PreToolUse, PostToolUse, PostToolUseFailure, Stop, StopFailure, SessionStart, SessionEnd, UserPromptSubmit, Notification
after: WSL settings.json mtime/size = 2026-11-15 01:16:23.841278655 -0800 13287
```

`pet-15912.log` 里 WARNING / ERROR 级的行只有上面那一条。

**3. 用户可见行为：气泡**。气泡经 `OverlayShell.show_bubble` 发出，那里同时写岛的消息记录。`message-log.json` 里对应的一条（时间戳与日志同一秒）：

```
{"uid":1309,"text":"Claude Code (WSL) 联动开着，但它的 settings.json 里缺肥鱼的 hooks（9 个事件），状态收不全。右键 → Agent 联动 里可以重新配置。","kind":"bubble",…}
```

**4. 边界：没缺的那一侧不说话**。本机通道的结论是「hooks 都在」（上面 INFO 那行），消息记录里没有本机的提示，只有 WSL 那一条。

**5. 没有自动验证的部分，以及为什么**：

- **真机上点修复项并同意**。点了「是」就会改 WSL 里的 `settings.json`——这一步必须是用户本人的同意，不能由验证脚本代点。它在测试里走的是真的菜单构建器和真的管理器（`test_menu_repair_item_goes_through_the_shared_manager`、`test_repair_installs_after_consent_and_clears_the_mark`、`test_wsl_repair_clears_the_mark_once_the_background_install_lands`），只有弹窗的回答和 `wsl.exe` 是替身。留给用户在真机上点一次，点完用性能一节的命令复查应为 `wsl missing=0`。
- **气泡的画面**。没有截图：截全屏会带进屏幕上别的窗口。用消息记录里的那一条代替（同一次 `show_bubble` 调用写的）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests` | All checks passed |
| 先红 | 产品代码没改时跑新测试 | 14 failed、14 errors（`AgentLinkManager` 没有 `CHECK_HOOKS_PRESENT`、`claude_hooks` 没有 `missing_hook_events`、菜单没有修复项） |
| 新测试 + 文字表守卫 | `pytest tests/test_claude_hooks_missing.py tests/test_claude_hooks.py tests/test_i18n.py tests/test_menu_english.py tests/test_sprite_menu_parity.py::test_menu_repair_item_goes_through_the_shared_manager` | 102 passed |
| 受影响的测试族 | 提到联动管理器 / hooks / 右键菜单 / overlay 菜单宿主 / 文字表 / 共享子系统的 125 个测试文件（含 `test_architecture.py`、`test_pr_report_discipline.py`）（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指到临时目录） | 2515 passed、5 skipped、5 failed |

5 个失败都不是这次改动带来的：

- 本机环境基线 3 个：`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`（路径过长）、`test_capture_window_rect_coordinates_and_clamping`（多显示器负原点）、`test_host_icons_are_warmed_at_the_cards_size`。
- main 上既有 2 个：`test_modern_context_menu_has_compact_semantic_groups`、`test_compact_ai_provider_controls_stay_inside_their_setting_row`（在 `dbc69f6f` 上同样失败，PR #50 的描述里记过）。

**没有跑全量**：改动集中在联动管理器、hooks 纯逻辑、「Agent 联动」子菜单和两张文字表；上面的测试族覆盖了所有会建管理器、建这个菜单或读文字表的测试。检查在测试里默认关闭（`conftest`），所以别的测试的行为不变。

## 七、已知限制

- **只在通道启动时查**。肥鱼运行中 hooks 被卸掉，要到下次启动（或关掉再打开联动）才提示。
- **旧 `PetWindow` 菜单没有修复项**（只修崩溃的约定），气泡有。
- **只看「有没有肥鱼的条目」**，不核对条目指向的脚本 / 事件文件路径对不对；路径搬家由既有的 `_refresh_moved_hooks` 管。
