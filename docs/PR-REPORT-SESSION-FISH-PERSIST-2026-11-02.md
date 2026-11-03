# PR 报告：会话小鱼一直在——认领开着的会话、最近 X 天的对话冻结、「关闭」落盘

> **分支**：`feature/session-fish-persist`（基于 main）　**日期**：2026-11-02
> **提交**：`bd4338e2`、`0f34be12`、`9de284bf`、`a8443261`、`<报告>`
> **范围**：实现 15 个文件（1 新）+ 测试 7 个文件（1 新）
> **过程**：用户 2026-11-02 先要调查结论（见「实机运行记录」1），再逐条拍板语义，然后「开始吧，同时把最大显示数量设成 10」

## 一、核心特性

用户的问题：重启大肥鱼后，空闲状态的会话小鱼都消失了，只剩工作中的那只。要求**小鱼一直在，除非我主动关闭**；
鱼代表「一个开着的对话」；主动关闭的鱼在会话又活跃时要能再正常显示。

| 层 | 来源 | 鱼 | 姿势 / 标签 | 离场 |
|---|---|---|---|---|
| 被动层（开着的会话） | Claude Code 自己的运行中会话清单 `~/.claude/sessions/<pid>.json`（本机 + WSL） | 有 | 按清单 `status`：idle → 休息中、busy → 工作中、waiting → 等你批准 | 进程没了 → 转冻结 |
| 主动层（最近 X 天开过的对话） | 「最近的对话」`claude-session-history.json` | 有 | **冻结**（灰标签；没有「冻结」素材时停在休息姿势不动） | 超过 X 天且进程仍不在 → 自动离场并忘掉 |
| 用户的决定 | `session-fish.json` | 无 | — | 会话再活跃（提问 / 等批准）即作废；离开名册即忘 |

- 之前的行为是设计出来的：小鱼只靠 hook 事件（tailer 启动时跳到文件末尾，不重放），第一次看到「休息中」的会话故意
  不生鱼（注释原话「没赶上它干活：不凭空生一只」）；`dismiss` 只在内存。
- 现在：`ClaudeCodeMonitor` 第一轮 + 每 60 s 从清单**认领**活着的、还没出场的会话（`ClaudeSessionTracker.adopt`，更新里带
  `adopted="1"`，呈现层据此允许以休息中出场；hook 事件那条「不凭空生鱼」的规则照旧）；已出场的会话顺便补上只有清单里才有的
  事实（桌面版那边的会话 id、入口）。
- 冻结鱼的右键菜单：恢复那一项**按入口说清在哪里重开**——**在 Claude 桌面版重开这个对话**（走
  `claude://claude.ai/epitaxy/<hostSessionId>` 深链）/ **在 VS Code 里重开这个对话**（聚焦或 `code` 打开它的工作区，再发插件深链
  `vscode://anthropic.claude-code/open?session=<id>`，插件对已关掉的对话也认这个链接）/ **在终端里恢复这个对话**（在那个目录开终端
  `claude --resume <id>`）；另有**在 Claude 桌面版打开**（非桌面版入口却记有桌面版会话 id 时）、详情 / 目录 / 复制、**关闭这只**。
  点冻结鱼（原来的「跳转」）等价于恢复。
  「跳到这个对话」对冻结鱼等价于恢复。
- 活的会话要出场而上限满了：最旧的冻结鱼让位。上限仍是 `session_pets_max`；保留天数新设置 `session_fish_keep_days`
  （1–30，默认 3），和上限一样放在右键「会话小鱼设置」里（不进设置页——与上限同一归属；见 `docs/SETTINGS-CHANGE-GATES.md`
  「高频命令留在右键菜单」）。

## 二、修改文件说明

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `pet/claude_session_info.py` | `REGISTRY_PHASES`、`adoptable_sessions`、`local_registry_sessions`、`wsl_registry_sessions`：清单条目 → 可认领的会话（阶段、用户起的标题、目录名、cwd、transcript、入口、桌面版会话 id）；进程明确已死的不要 | 认领的数据源；WSL 复用同一段 `WSL_SCRIPT` |
| `pet/claude_hooks.py` | `_PhaseText` 多 `frozen`；`ClaudeSessionTracker.adopt` / `note_registry` | 认领进收敛器的会话表（只管呈现，不进 `_busy`：Agent 级状态仍由事件决定） |
| `pet/agent_link.py` | `ClaudeCodeMonitor._adopt_registry_sessions`（第一轮 + 每 60 s）、`adopt_from_registry` 开关 | 重启后空闲的会话马上回来；测试里关掉别读真机清单 |
| `pet/overlay_session_pets.py` | 构造多 `decisions / keep_days / clock`；`attach_history`、`reconcile`（名册 = 在用 ∪ 最近 X 天）、冻结鱼的生灭、`_make_room`、`history_entry`、`is_frozen`；`dismiss` 落盘；`on_session_update` 认领例外、活跃即作废、冻结 ↔ 活的切换；第一次核对延后 `FIRST_RECONCILE_MS`；冻结鱼的详情带 `distro` | 两层合一处；接线在壳的 `__init__` 里，立刻生鱼会用到还没建好的屏幕路由（实机启动失败，见记录 4）；WSL 会话 `code --remote` 要发行版名（记录 5） |
| `pet/session_fish_decisions.py`（新） | 「关闭」决定：dismiss / revive / prune / load / save（原子写） | 跨重启；只存会话 ID、通道、时间、标题 |
| `pet/session_pet_ui.py` | `resume` / `resume_key`（桌面版深链 / **VS Code：后台线程 `resume_in_vscode`** / 终端）、`open_in_desktop`、`resume_label`；`jump_key` 冻结分支；菜单冻结分支按入口给文案，桌面版入口不再重复给「在 Claude 桌面版打开」；详情带上 `host_session` / `entrypoint` / `distro`；设置子菜单多「冻结小鱼保留天数」 | 用户 2026-11-02：冻结的 VS Code 会话点下去只开了工作区文件夹，看到的是空的新对话（记录 5）；文案要说清在哪里重开，别叫「跳转」 |
| `pet/claude_session_history.py`、`pet/session_history_service.py` | 历史行多 `host_session`，记录时连 `entrypoint` / `host_session` 一起记 | 桌面版会话 id 只有进程活着时拿得到，冻结后靠它深链 |
| `pet/claude_session_jump.py` | `resume_in_vscode`（读窗口记录 → `_jump_vscode`）；`_jump_vscode` 多 `done` 文案参数 | 冻结的 VS Code 会话复用活会话跳转那套「聚焦对的窗口 → 发会话深链」，只是成功文案说「重开」而不是「跳到」 |
| `pet/config.py`（`SESSION_PETS_MAX_CAP`）、`pet/sprite_menu_facade.py`（`ask_session_pets_max`）、`pet/session_pet_ui.py` / `pet/context_menus/shared.py`（上限子菜单） | 上限硬顶 24 → 40；两处上限子菜单多「自定义…」弹数字框（1–40），当前值不在预设里也列出来并勾上 | 用户 2026-11-02 第五轮：要设 20，预设里没有、硬顶又贴着 24 |
| `pet/overlay_shell.py` | 控制器带决定文件（和历史同目录）与保留天数；`session_history.start()` 之后 `attach_history` | 接线 |
| `pet/config.py`、`pet/sprite_menu_facade.py`、`pet/context_menus/shared.py` | `session_fish_keep_days` 默认 3、clamp 1–30；facade setter；主肥鱼「Agent 联动」子菜单同样多这一项 | 设置项 |
| `pet/pet_sprite.py` | 标签色调 `frozen`（灰） | 一眼分清冻结 |
| `pet/locale/zh.json`、`en.json` | `session.phase.frozen`、`menu.session.*`（三种入口的重开文案 / 正在让 VS Code 重开 / 没能重开 / 桌面版打开 / 关闭这只 / 没记录 / 天数）、`menu.shared.*`（天数）、`session_jump.ui.reopened_conversation_vs_code` | 文案 |
| `tests/test_session_fish_decisions.py`（新） | 落盘 / 重载 / 作废 / 忘掉 / 坏文件 | — |
| `tests/test_claude_hooks.py`、`tests/test_session_pet_details.py`、`tests/test_overlay_session_pets.py`、`tests/test_claude_session_history.py`、`tests/test_claude_link.py`、`tests/test_sprite_menu_parity.py` | 认领（收敛器 / 清单 / 监视器）、认领来的休息中出场、冻结、解冻、关闭跨重启且再活跃作废、离开名册即忘、活的优先、冻结菜单与深链、天数设置、历史新字段、建壳不炸；**第四轮**：`resume_in_vscode` 先开工作区再发会话链接 / 工作区开着只聚焦、冻结的 WSL VS Code 鱼菜单文案 + 点下去交出带发行版名的详情、冻结的终端会话文案；旧测试「关到会话关闭为止」按新语义改成「关到再活跃为止」；`_monitor` 辅助默认不读真机清单；菜单清单允许项多一条 | — |

### 未改动

- Agent 级状态机、灵动岛汇总（冻结的不算「在用的会话」）、hook 脚本、历史回填扫描、跳转的窗口匹配。

## 三、实现要点

- **身份**：`(通道, sessionId)`；sessionId 跨肥鱼重启、跨 `--resume` 稳定（进程号变，id 不变），所以关闭决定按它记。
- **活跃 = 提问或等批准**（`working` / `waiting`）：只有这两种让关闭决定作废；认领来的休息中、冻结都不算——否则一重启就全回来。
- **名册与遗忘**：每次核对把不在名册（在用 ∪ 最近 X 天）里的决定丢掉，新会话永远不会继承旧决定。
- **清单条目的可信度**：清单是 Claude Code 自己按进程写的；`process_alive` 用 pid + 进程启动时间核对（pid 被复用也认得出）；
  判断不了（没 psutil）就照认——条目本来就是它自己写的。
- **冻结的动画**：`FROZEN_CLIPS = ("冻结",)`，素材库里没有就 `hold(REST_CLIPS)` + `pause_clip`——静止就是冻结；用户生成素材后放进角色包即生效，不改代码。

## 四、性能分析

实测（本机，真实清单 5 条 / WSL 12 条，各 20 次取均值）：

| 路径 | 成本 | 频率 |
|---|---|---|
| `local_registry_sessions()`（读 5 个 json + 每条一次 `projects/*/<id>.jsonl` glob + psutil 核对） | **4.0 ms / 次** | 监视器 worker 线程，第一轮 + 每 60 s |
| `wsl_registry_sessions()`（一次 `wsl.exe`，脚本里读清单 + `/proc`） | **164 ms / 次** | 同上，仅 WSL 通道开着时；worker 线程，不卡 GUI |
| 决定文件 dismiss + revive（两次原子写） | 2.3 ms | 用户点一次 |
| `reconcile()`（历史 ≤ 30 行、集合运算、prune） | 微秒级（无新 I/O：历史在内存） | 每次会话更新后 + 每 60 s + 历史变化时 |

- **稳态**：多两个周期任务（认领 60 s、名册核对 60 s），都在已有线程 / 定时器上；无新线程、网络；磁盘只多一个小 JSON（决定变了才写）。
- **内存**：每只冻结鱼 = 一只会话小鱼（既有实测每只约 3–4 MB、9% 单核播放成本——冻结的停了播放节拍，CPU 更低）；总数仍受
  `session_pets_max` 约束，用户设为 10。
- **启动**：第一轮认领在监视器第一次轮询时完成（实机 15:46:43.6，启动后 ~2 s），17 个会话认领 + 10 只鱼出场共 0.6 s（含每只
  建素材库）。

## 五、实机运行记录

本机 Windows 11、三屏；Claude 桌面版 Code 标签页若干 + WSL（Ubuntu-24.04）里的 Claude Code；桌宠从源码跑。

1. **调查**（动手前）：读 `overlay_session_pets` / `claude_hooks.ClaudeSessionTracker` / `agent_link._reap_dead_sessions` 确认机制；
   看本机 `~/.claude/sessions`：5 条，进程全活着（`claude.exe`，父进程是桌面版宿主），状态 4 idle + 1 busy，最老的空闲 23.7 h
   ——这 4 条就是重启后「消失」的鱼。结论先给用户，用户拍板语义后再开工。
2. **红 → 绿**：15 条新测试（决定文件 4、收敛器 2、清单 2、监视器 1、呈现层 7+1、历史 1、设置 2；见「测试与验证」），修前分别
   `AttributeError: adopt / sprite_of None / 没有 frozen 阶段` 等；旧测试「关到会话关闭为止」与新语义矛盾，按用户要求改为
   「关到再活跃为止」。
3. **第一次实机（pid 44652）**：**启动失败**——`attach_history` 在 `OverlayShell.__init__` 里立刻 `reconcile()`，历史里有 23 条
   近 3 天的对话，第一只冻结鱼生成时用到还没建好的 `_screens` → `AttributeError`，壳没建起来。修：第一次核对延后 1.5 s、生鱼 /
   保持动画出错兜住；回归测试 `test_a_shell_built_over_an_existing_history_does_not_spawn_during_its_own_init`。
4. **第二次实机（pid 55800，`session_pets_max` 按用户要求设成 10）**：日志 0 条 ERROR；启动后 2 s 认领 17 个会话（本机 5：4 休息
   + 1 工作；WSL 12：全休息）；冻结鱼先按历史出场 9 只、随后活的会话逐只进来、最旧的冻结鱼逐只让位，终态 **10 只活鱼
   （本机 5 + WSL 5）、0 只冻结**，另 7 个 WSL 会话超上限只在汇总里。主屏截图右下一排 10 只带「· 休息中」标签的小鱼（截图含
   用户工作内容，不入库）。
5. **用户实机反馈（2026-11-02 18:10，pid 55800）**：用户关掉一个 WSL 里 VS Code 开的会话标签页，鱼如期变「冻结」
   （日志 `冻结的会话小鱼出场 agent=claude_wsl`），点下去却「不是之前的对话」。原因：`resume_key` 对 VS Code 入口走的是
   `default_action` = 只用 `code --remote wsl+<发行版>` 打开工作区文件夹——那只是一个空的新对话。**探针**（本机，Windows 侧
   VS Code 2.1.296 插件；`scratchpad/probe_vscode_reopen.py`）：对一个进程已不在 27 h 的本机 VS Code 会话，先 `code <文件夹>`、
   1.55 s 后 `os.startfile("vscode://anthropic.claude-code/open?session=<id>")`：VS Code 窗口标题随即变成
   `<文件夹> - <那个对话的名字>`；再发一次链接后 1 s，`~/.claude/sessions` 里出现这个 sessionId 的新进程条目
   （`status=idle, entrypoint=claude-vscode`）——插件对已关掉的对话也认这个链接（插件源码里 `handleUri` 的 `/open` 分支把
   `session` 直接交给 `claude-vscode.primaryEditor.open`）。修：VS Code 入口的恢复改走 `claude_session_jump.resume_in_vscode`
   （复用活会话跳转的「聚焦对的窗口 / `code` 打开工作区 → 等 1.2 s → 发会话链接」），后台线程里跑，结果走 `_jump_done`；
   冻结鱼详情带上 `distro`（之前缺它，WSL 会话连 `--remote` 都组不出来）；菜单文案按入口分成三条，不再叫「恢复 / 跳到」。
   第一次发链接时运行清单 20 s 内没出现条目、第二次 1 s 就有，怀疑新窗口冷启动时插件把对话打开了但进程是懒起的；
   不影响用户看到的结果（对话已重开），记在这里。
6. **第五轮（上限可随便填）**：用户开着 20 个会话、要把上限设成 20，而菜单只有六档预设、硬顶 24。改完后把本机
   `agent_link.session_pets_max` 设成 20 重启（pid 49424）：日志 0 错误；启动 3 s 内认领 18 个开着的会话（本机 6 + WSL 12），
   冻结鱼先按历史出场 19 只、被活的顶掉 17 只，终态 **18 只活鱼 + 2 只冻结 = 20**，正好满上限——冻结鱼第一次在实机上留在了场上。
7. **仍没在实机上点过的**：右键「关闭这只」→ 重启 → 不回来 → 再提问回来（只有单元测试：决定文件 round trip + 控制器语义）；
   桌面版入口的冻结鱼深链（`claude://…`，调查结论里就标明未验证）；以及修完后从鱼上点「在 VS Code 里重开这个对话」
   这一整条（探针验证的是同一组命令，但不是从菜单点出去的）——请用户各点一次，结果补进下一期。

## 六、测试与验证

- 新增 / 改动的测试全部先红后绿；`ruff check pet/ tests/` 过。
- 相关族（决定 / hooks / 详情 / 会话小鱼 / 历史 / 历史服务 / 联动 / 配置 / i18n / 岛上历史 / 菜单 facade / 菜单一致性 / 架构守卫 /
  生成）：**354 passed**；三次迭代期间曾撞上一次已知的间歇原生崩溃（见 memory 里的记录），修掉 KeyError 路径后三族 108 条连跑 0 崩。
- 全量：见文末「数字」。

## 七、已知限制与后续

- **上限**：开着的会话比上限多时（实机 17 > 10），超出的既没鱼也不冻结，只在灵动岛汇总里；排序 活的 > 冻结的，冻结里最近的
  优先。想全看见就调大上限（预设几档，或「自定义…」填 1–40；用户 2026-11-02 第五轮设成 20）或关掉用不着的 WSL 会话。
- **认领只认运行清单写了的版本**：老版本 Claude Code 不写清单的会话仍只能靠事件出场。
- **冻结 → 活的切换**最多等一轮认领（60 s）；恢复命令起的进程发了第一条 hook 事件会更快。
- **冻结素材**：用户稍后生成；在此之前是静止的休息姿势。
- 第一轮认领会让冻结鱼先出场再被活的会话顶掉（0.4 s 内生 9 只退 8 只，日志可见）：可以把第一次核对再推后到认领之后，没做。

## 八、风险与回滚

- 风险：桌面上会多出不少鱼（每个开着的会话一只，直到上限）——这正是用户要的；嫌多就关会话、关鱼或调上限 / 天数。
- 决定文件只增不减地记录会话 ID（最多等于名册大小，prune 清理），无隐私内容。
- 回滚：revert 两个实现提交；`session-fish.json` 可直接删；`agent_link.session_fish_keep_days` 多余的键被 normalize 忽略。

## 数字

| 文件 | +/− |
|---|---|
| `pet/overlay_session_pets.py` | 151 / 14，第四轮 +2 / −1 |
| `pet/session_fish_decisions.py`（新） | 126 / 0 |
| `pet/session_pet_ui.py` | 67 / 2，第四轮 +40 / −5 |
| `pet/claude_session_info.py` | 47 / 0 |
| `pet/agent_link.py` | 37 / 0 |
| `pet/claude_hooks.py` | 28 / 1 |
| `pet/context_menus/shared.py` | 12 / 0 |
| `pet/locale/zh.json`、`en.json` | 11 / 0 ×2，第四轮 +6 / −1 ×2 |
| `pet/claude_session_jump.py` | 第四轮 +25 / −2 |
| 第五轮：`pet/sprite_menu_facade.py` 17 / 0、`pet/config.py` 4 / 1、`pet/context_menus/shared.py` 4 / 0、`pet/session_pet_ui.py` 3 / 1、`pet/overlay_shell.py` 2 / 1、`pet/locale/zh.json`、`en.json` 5 / 0 ×2、`tests/test_overlay_session_pets.py` 43 / 1 | |
| `pet/sprite_menu_facade.py` | 10 / 0 |
| `pet/overlay_shell.py` | 8 / 1 |
| `pet/config.py` | 3 / 1 |
| `pet/claude_session_history.py`、`pet/session_history_service.py`、`pet/pet_sprite.py` | 2 / 1 ×3 |
| `tests/test_overlay_session_pets.py` | 180 / 0，第四轮 +47 / −1 |
| `tests/test_session_pet_details.py` | 76 / 3，第四轮 +17 / 0 |
| `tests/test_session_fish_decisions.py`（新） | 53 / 0 |
| `tests/test_claude_hooks.py` | 30 / 0 |
| `tests/test_claude_session_history.py` | 14 / 1 |
| `tests/test_claude_link.py`、`tests/test_sprite_menu_parity.py` | 1 / 0、1 / 1 |

全量测试（隔离 worktree、`QT_QPA_PLATFORM=offscreen`、临时 `APPDATA`，Git Bash 启动，提交 `a8443261`）：**5949 过、14 跳过、5 失败，609 s**；
5 条失败全是本机既有基线（路径超 260 的图片目录抽屉、子进程输出按 cp1252 解码的 3 条、多显示器负原点的截屏矩形），与本改动无关。
第一轮（提交 `bd4338e2`）另有 3 条快照测试没跟上新设置项 / 新阶段 / 新菜单项，已更新（`9de284bf`、`a8443261`）。
第五轮（上限自定义）：1 条新测试先红后绿、normalize 参数化多两例；相关族过。
第四轮（VS Code 重开）：3 条新测试先红后绿；相关 8 族 **212 passed**，`ruff` 过；只改了会话小鱼这一条路径的恢复分流与文案，
接口 / 持久数据 / 生命周期 / 平台分派都没动，按 AGENTS.md 的风险门只跑焦点 + 相关族，没重跑全量。
