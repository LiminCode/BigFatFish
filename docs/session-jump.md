# 跳到对话与外部程序入口

> 在会话小鱼 / 灵动岛的会话卡片上点「跳到对话」：活着的会话，把承载它的窗口调到前台并切到那个对话；进程已不在的会话，在它当时所在的地方重开。右键菜单另有三条入口：「VS Code 工作区」「Claude Desktop」「Claude Code（WSL）」。小鱼本身（出场、冻结、认领）见 [会话小鱼](session-fish.md)。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/claude_session_jump.py` | 找窗口、跳转、重开的全部逻辑（零 Qt）：`jump`、`resume_in_vscode`、`raise_desktop`、`opened_workspaces`、`workspace_from_storage`、`select_terminal_tab` |
| `pet/claude_session_info.py` | 读运行清单 / transcript，给出 `SessionDetail`（`entrypoint`、`extra["start_cwd"]`、`extra["host_session"]`） |
| `pet/claude_session_history.py` | 「最近的对话」的记录：`HistoryEntry.workspace` / `host_session`，`terminal_resume_argv` |
| `pet/session_history_service.py` | 活着时后台认工作区（`WORKSPACE_RECHECK_S`）、`note_workspace`；`SessionHistoryActions`（列表里点一行） |
| `pet/session_pet_ui.py` | `SessionPetActions.resume_key`：冻结鱼按入口分流；`resume_label` 菜单文案 |
| `pet/vscode_workspaces.py` | 菜单「VS Code 工作区」：三个来源、合并排序、`activate`；WSL 发行版列表 |
| `pet/settings_vscode.py` | 设置页「VS Code 工作区」一节（本机目录 + 每个发行版一行 + 条数） |
| `pet/claude_launchers.py` | 「Claude Desktop」「Claude Code（WSL）」：找程序、拼命令行、拉起、摆新终端窗口（零 Qt） |
| `pet/context_menus/shared.py` | 三个菜单叶子：`add_vscode_workspaces_menu`、`add_claude_desktop`、`add_wsl_claude_code` |
| `pet/sprite_menu_facade.py` | `vscode_workspace_entries` / `open_vscode_workspace`：后台线程 + `_NoticeBridge` 回 GUI 线程冒泡 |

## 机制与不变量

### 分流：活着没有 × 在哪开的

入口取自运行清单 / transcript 的 `entrypoint`。

| 入口 | 活着：`jump()` | 进程已不在：`resume_key()` |
|---|---|---|
| `claude-vscode` | 调对窗口，再发 `vscode://anthropic.claude-code/open?session=<id>` | `resume_in_vscode()`：聚焦 / 重开记住的工作区，再发同一条链接（插件对已关的对话也认，会重开它） |
| `claude-desktop` | 有 `host_session` 就开 `claude://claude.ai/epitaxy/<id>`；没有或打不开，顺进程链调桌面版窗口 | 有 id 同左；没有 id 走 `raise_desktop()` 抬窗 |
| 其余（终端） | 调宿主终端窗口；Windows Terminal 再选中标签页 | 在那个目录开终端跑 `claude --resume <id>` |

- 都会阻塞几百毫秒到一两秒，只在后台线程里调，结果经信号回 GUI 线程。
- 对别家程序的文件全部只读（sqlite 以 `mode=ro` 打开）；找窗口、认工作区都不读对话内容。
- 每次跳转现读现用，不缓存：读 VS Code 的记录约 15～20 ms，不值得为它引入失效问题。

### VS Code：活着的会话找窗口

VS Code 所有窗口同属一个主进程，窗口只能靠标题分辨；而标题里是**工作区名**，不一定是会话所在的文件夹名（多文件夹工作区叫 `<工作区文件名> (Workspace)`）。所以先问 VS Code 自己的记录，再去标题里找。`_jump_vscode` 用线索的顺序：

1. **状态库**（`session_windows`）：每个窗口的 `state.vscdb` 记着打开的标签页，Claude 会话的标签页带会话 ID。「是开着的标签页」2 分、「只在插件状态里出现」1 分，最高分正好一个窗口才采信。最准：同一文件夹被两个工作区包含、会话中途 cd 到工作区外，只有它分得清。它隔一阵才落盘，刚开的会话可能查不到。
2. **目录归属**（`owning_workspaces`）：`storage.json` 的窗口清单 + 工作区文件里的文件夹，取包含会话目录且最深的窗口。
3. **标题**（`vscode_candidates`）：按归属窗口的名字找；标题对得上的正好一个就用它。多文件夹那一段括号里的词随界面语言变，只认「名字 + 一对括号」。
4. **当前标签页**（`_shows_session`）：哪个窗口标题里有一段等于会话标题，或是它被截断的前缀（`前缀…`，至少 8 个字符）。
5. **启动目录**（`narrow_by_start`）：插件把进程起在工作区的第一个文件夹里，运行清单的 `cwd` 记着它；用来在几个候选里再筛。
6. **`code` 命令**：标题仍分不清时，把**确切的**文件夹 / 工作区文件交给 `code [--remote wsl+<发行版>]`，VS Code 按目标去重，已开着的只会被聚焦。之后等 1.2 s。

窗口到前台后再等 `_URI_DELAY_S`（0.35 s）才发链接：链接由「最后活跃的 VS Code 窗口」处理。

不变量：

- **活着的会话不新开窗口。** 记录读得到、却没有窗口包含这个目录时，回答「没认出在哪个窗口」，不跑 `code`。
- **链接只发给调对了的窗口。** 会话不属于当前聚焦窗口的工作区时，插件会新开一个空对话。
- **分不清就交给 `code`，不取最靠前的。** 三个同名窗口取最靠前的有三分之二是错的，错了就在错的窗口里冒出空对话。只有连归属都不知道时才取最近用过的。
- **只给文件夹不够。** 目录属于多文件夹工作区时 `code <文件夹>` 会新开窗口；知道归属就必须传工作区文件（`vscode_target`）。
- WSL 与本机不互相冒充：标题只认带 / 不带 `[WSL: …]` 的那一段，归属按 `wsl` 标志分开。
- VS Code 的记录完全读不到时退回老路：按文件夹名找标题，找不到 `code <文件夹>`。新线索只让结果更准，不让原来能跳的变成不能跳。

### VS Code：进程已不在的会话重开

- **活着时记下工作区**：`HistoryEntry.workspace = {label, target, multi_root, roots}`。`target` 是交给 `code` 就能聚焦的路径；`roots` 是它包含的文件夹，**必须记**，因为未命名的多文件夹工作区一关，VS Code 就删掉它的工作区文件，只剩这份列表能重建（`code 目录1 目录2 …` 开成一个未命名多文件夹窗口）。
- 三处写入、一个入口：详情卡 / 跳转读详情时认出的、历史服务每会话每 10 分钟后台认一次的、从状态库回填的，都经 `SessionHistoryService.note_workspace`。它只改工作区、不动 `last_seen`，补记老会话不会把它顶到列表最前。
- **重开先认记录**（`resume_in_vscode`，列表点一行的 `vscode_target` 同理）：记录的工作区开着（`open_workspace_matching`：按 `target` 对；未命名的重开后文件名会变，按文件夹集合对）→ 只在那个窗口里找（`pinned`）；没开 → `reopen_targets`：工作区文件还在开文件，没了开文件夹列表，单文件夹开那个文件夹。状态库的唯一记录仍可压过 `pinned`。
- **老会话回填**（`workspace_from_storage`）：VS Code 关掉的窗口也留着状态库。翻 30 天内动过的、提到过这个会话 ID 的，按（标签页 > 插件状态，落盘时间新 → 旧）排序，头一个还原得出文件夹的算数并记进历史。扫一遍约 23 ms，有记录后不再扫。
- **不借别的工作区**（红线）：进程已不在的会话，「现在开着的窗口里谁包含这个目录」说明不了它当时在哪。`attach_workspace` 对 `alive is False` 或 `phase == "frozen"` 的会话只认状态库，不按目录猜；否则卡片会显示借来的工作区，还会把它记进历史、盖掉正确的记录。按目录只剩最后一步：既没记录、状态库也回填不到时。
- 未命名的 WSL 工作区在窗口清单里是本机路径的 `workspace.json` 加 `remoteAuthority: wsl+<发行版>`；`workspaces_from_state` 靠 `remoteAuthority` 把它认成 WSL 窗口，否则整个窗口是隐形的。

### Claude 桌面版

- 运行清单里的 `hostSessionId` 是桌面版那边的会话 id，只收 `^local_[A-Za-z0-9-]{1,64}$`（与桌面版自己的校验一致），不像 id 的不拼链接。
- 这个 id **只在活着时的运行清单里有**，扫 transcript 回填的历史只知道入口。所以小鱼层认领活会话时要把 `host_session` 记进历史，冻结后才能深链回去。
- 冻结且没有 id：`raise_desktop()` 聚焦标题为 `Claude` 的 `claude.exe` 窗口（没有就任一 `claude.exe` 窗口），一个都没有就开 `claude://` 把它拉起来，气泡提示在侧栏里自己选。**无论如何不开终端**：那个对话在桌面版里。

### 终端

- 本机会话：顺进程链往上，第一个有可见窗口的祖先（`find_host_window`）。WSL 会话的进程链在发行版里，改看它的环境变量 `TERM_PROGRAM`（`vscode` = VS Code 内置终端）/ `WT_SESSION`。
- Windows Terminal：调到前台后用 UI 自动化找 `TabItem`，`pick_tab` 去掉标题前的状态符号后先找等于线索的、再找包含线索的，线索依次是会话标题、会话名，至少 3 个字。**WSL 发行版名不当线索**：它会对上随便哪个同发行版的标签页。
- UI 自动化出任何错都退回「自己选标签页」，不影响窗口已经到前台。别的终端和 VS Code 内置终端的标签页从外面够不着。
- `focus_window` 逐级加码（`SetForegroundWindow` → 借前台线程输入队列 → 按一下 Alt → `SwitchToThisWindow`），成败一律看前台窗口是不是它：被拒绝时返回值也可能是真。

### 菜单「VS Code 工作区」

- 三个来源：开着的窗口（`opened_workspaces`）；最近用过的（`workspaceStorage/<id>/` 里 `state.vscdb` 的修改时间，只看 60 天内；本机文件夹已删的不列，WSL 里的没法便宜地查，照列）；用户目录里的 `*.code-workspace`。
- 按 `(wsl, target)` 去重后排序：**开着的**（保持 VS Code 清单里的顺序）→ **用户目录里的** → 其余按最后活动时间。用户目录单列一档，是因为开着的加最近的就能占满上限（默认 12，可设 3～30），把特意配的目录整个挤出去。
- 同名条目加后缀：文件夹带父目录名，工作区文件标「工作区」。只改显示名。
- 点一条：开着且标题正好对上一个窗口 → 聚焦；否则 `code [--remote wsl+<发行版>] <路径>`。WSL 条目不知道发行版时不猜，直接说明。
- 条目在菜单弹出时现算（GUI 线程，约 30 ms，读 60 来个小文件），不常驻、不加定时器。点击在后台线程；结果信号的 `QObject` 挂在壳上长期存活，因为菜单门面随菜单建了又丢。
- 配置 `vscode_workspaces = {workspace_dir, wsl_dirs: {发行版: 目录}, menu_limit}`。WSL 目录按发行版分行填发行版里的原生路径；老值里的 `/home/…` 或 UNC 写法在 `normalize` 里搬进 `wsl_dirs`。保存时本机暂时没列出的发行版的目录原样保留。
- 新版菜单用图标区分 WSL / 本机，开着的在图标右下角加绿点（`OPEN_BADGE_COLOR`）；旧版菜单无图标，用文字标记。只有提供这两个回调的宿主（overlay）出这一项。

### 菜单「Claude Desktop」「Claude Code（WSL）」

- **只拉起，不送内容**：不传提示词、不传 `--model`，不加配置键，不进托盘和灵动岛。
- Claude Desktop：老式安装器的 `%LOCALAPPDATA%\AnthropicClaude\claude.exe` 优先；否则是商店版，它没有可执行路径，从注册表的包仓库里找 `Claude_` 开头的包全名，转成家族名，`os.startfile("shell:AppsFolder\<家族名>!Claude")`。不用 `Get-AppxPackage`：要起 PowerShell（上百毫秒），枚举注册表是 0.4 ms。
- Claude Code（WSL）：`wt -w new wsl.exe -d <默认发行版> --cd ~/workspace -- bash -lic "claude\; exec bash"`（登录 shell PATH 才齐，退出后留在 shell 里）；没有 `wt` 退到 `cmd /c start`。
- **`wt` 把 `;` 当子命令分隔符，引号不保护**：不转义就劈成两个标签，第二个报 `0x80070002`。经 `wt` 的命令行一律过 `wt_script()` 写成 `\;`；`cmd /c start` 那条不经 `wt`，不能转义。`terminal_resume_argv` 同此。
- 起始目录是常量 `WSL_START_DIR`，不是家目录：Claude Code 的「信任此文件夹」按目录记，在没信任过的目录每次都停在确认框上，而信任整个家目录等于放开里面的一切。
- 新窗口摆位（`fit_new_window`）：`wt` 自己开的新窗口尺寸不稳（有时比工作区还高，有时套用上一个窗口的尺寸叠在原位），`wt --size` 按字符格计、换算不稳。所以 `-w new` 强制新窗口，等它**显示出来**后 `SetWindowPos` 到主屏左半边，0.3 s 后核对，不对再摆，最多 3 次。不要在窗口刚枚举到时摆：终端显示时会再套一次它记住的尺寸，把摆位盖掉。
- 可用性在叶子里查（没找到就 `setEnabled(False)` + 提示）：注册表项的 `enabled=` 只对新版菜单生效。两个目标合计约 2 ms，每次右键现查不缓存，装 / 卸之后下一次右键就反映。启动失败（`OSError`）写日志并冒一句气泡。
- 三条入口在新版模板与旧版建造器里都登记；菜单编排的通用规则见 [设置与右键菜单](settings-and-menu.md)。

## 设计取舍

- **只做一键拉起，不做对话转发。** 肥鱼自己的聊天走个人 key、只有只读工具；缺的是工具与账号，不是模型。转发需要一条现在不存在的通路（WSL 通道只有固定提示词的单向任务），往交互式 Claude Code 的 TUI 里塞字也明确没做。
- **不自己记「最近打开」。** 要监听窗口、落盘、处理已删项目，而 VS Code 已经记了；代价是依赖它的内部目录结构。
- **不读 Claude 桌面版的私有会话库**（里面有 CLI 会话 id → `local_…` 的对应）：没有文档、单个文件几百 KB、随时可能变形。宁可抬窗让用户自己点。
- **商店版用 `shell:AppsFolder` 拉起，不用 `claude://`**：协议打开后的行为没有文档。`raise_desktop` 只在没有窗口时拿裸 `claude://` 兜底。
- 找 VS Code 窗口没采用的路：顺 WSL 进程树找扩展宿主（每次多起一次 `wsl.exe`，且宿主到窗口的对应没有公开）；拿窗口位置对 `storage.json`（最大化的窗口位置都一样）；新开之后再关掉（会闪）。
- 回填出来的工作区可能不是最后那个：未命名工作区的文件已删时退到下一个提到过它的窗口。这是它真实开过的窗口，比借一个没开过的诚实。
- 新终端窗口取主屏左半边而不是「和现有窗口一样大」：会盖住用户正在看的那个。要换位置改 `left_half` 一处。

## 外部格式依赖

都是别家没有承诺的内部格式，升级后先核对这里。读不到时的设计是「少一条线索」，不报错。

**VS Code**（`Code - Insiders` / `Cursor` / `Windsurf` / `VSCodium` 按同一结构读，没有实测）

- `%APPDATA%/Code/User/globalStorage/storage.json`：`windowsState.lastActiveWindow`、`windowsState.openedWindows[]`；每条是 `folder`（地址），或 `workspaceIdentifier.configURIPath`（工作区文件）加可选的 `remoteAuthority`（`wsl+<发行版>`）。
- 地址写法：`file:///c%3A/…`、`vscode-remote://wsl%2B<发行版>/…`。同一发行版名有时全小写，会各建一个状态库目录。
- 工作区文件 `*.code-workspace`：JSONC（注释、行尾逗号），`folders[].path`（相对工作区文件）或 `folders[].uri`。未命名工作区是 `%APPDATA%/Code/Workspaces/<id>/workspace.json`，窗口关掉即删。
- `%APPDATA%/Code/User/workspaceStorage/<id>/workspace.json`：`folder`，或 `workspace`（字符串或 `{configPath}`）。
- 同目录的 `state.vscdb`：sqlite，表 `ItemTable(key, value)`；键 `memento/workbench.parts.editor`（编辑器区标签页）与 `Anthropic.claude-code`（插件状态）的值里以子串出现会话 ID。文件修改时间被当作「最后用过」。
- 全局 `state.vscdb` 里**没有** `history.recentlyOpenedPathsList`（2026-10-13 实测），所以「最近」才取状态目录的修改时间。
- 窗口标题：按 ` - ` 分段，一段是 `名字`、`名字 [WSL: 发行版]` 或 `名字 (Workspace)`，另一段是当前标签页标题（过长截成 `前缀…`）。用户把 `window.title` 改得不带 `rootName` 时标题线索全失效。
- `code` 命令：按文件夹 / 工作区文件去重；给多个文件夹开成一个未命名多文件夹窗口。`--remote wsl+… <工作区文件>` 这一种没有亲手验证过。
- 进程名：`VSCODE_PROCESSES`。

**Claude Code**

- 运行清单 `~/.claude/sessions/<pid>.json`：`pid`、`entrypoint`（`cli` / `claude-vscode` / `claude-desktop` / `sdk-cli`）、`cwd`（进程启动目录）、`hostSessionId`、`status`、`name` + `nameSource`、`startedAt`、`version`。会留下进程早已不在的陈旧文件，「活着」要拿进程号 + 启动时间核对。
- 插件深链 `vscode://anthropic.claude-code/open?session=<id>`：由聚焦窗口处理；对已关的对话会重开。VS Code 插件把进程起在工作区的第一个文件夹里。
- 终端标题默认是对话标题，前面带状态符号（`✳`、转圈的盲文点）。
- 「信任此文件夹」记在 `~/.claude/.config.json` 的 `projects[<路径>].hasTrustDialogAccepted`（代码不读，只是 `WSL_START_DIR` 的由来）。

**Claude 桌面版**

- 会话外链 `claude://claude.ai/epitaxy/<hostSessionId>`；裸 `claude://` 拉起 / 前置程序。
- 主窗口：进程 `claude.exe`、标题 `Claude`（Claude Code 自己的 `claude.exe` 没有可见窗口）。
- 商店版：`HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages` 下的子键名 `Claude_<版本>_<架构>__<发布者 id>` → 家族名 `Claude_<发布者 id>`，应用 id `Claude`。

**Windows Terminal / WSL**

- 顶层窗口类名 `CASCADIA_HOSTING_WINDOW_CLASS`；标签页是 UIA 的 `TabItem`，支持 `SelectionItemPattern`。
- 发行版列表：`HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss` 各子键的 `DistributionName`，`DefaultDistribution` 指向默认的；Docker / Rancher 的内部发行版不列。
- 读 WSL 里的文件走 `\\wsl.localhost\<发行版>\…`（不分大小写）；发行版没开着时这一读会把它拉起来，慢几秒。

## 排障

| 症状 | 原因 / 先查什么 |
|---|---|
| 点「跳到对话」新开了一个 VS Code 窗口 | 走到了 `code <文件夹>`，而目录其实属于某个多文件夹工作区。看 `opened_workspaces()` 的返回里有没有承载它的窗口：`storage.json` 的键变了、或是没认出的窗口类型 |
| VS Code 里冒出一个空的新对话 | 链接被别的窗口处理了：窗口没调对，或没到前台就发了链接 |
| 「没认出这个对话在哪个 VS Code 窗口里」 | 记录读得到但没有窗口包含会话目录：多半是会话 cd 到了工作区外、状态库还没落盘，过一会再点 |
| 冻结鱼重开到了别的工作区 / 卡片上的工作区不对 | 历史里那条没有 `workspace`（看 `claude-session-history.json`），状态库也回填不到，于是按目录找。改动前就关掉的未命名工作区救不回来 |
| 重开的未命名工作区少 / 多一个文件夹 | 工作区每 10 分钟才认一次，刚改过文件夹的记录是旧的 |
| 活着的桌面版会话只调窗口、没切到对话 | 运行清单里没有 `hostSessionId` 或形状不合；或 `claude:` 协议打不开 |
| 桌面版的对话被开进了终端 | 冻结鱼不该如此（应抬窗）。「最近的对话」列表里点一行走 `default_action`，只分 VS Code / 其余，桌面版会话在那里仍是终端 `claude --resume` |
| Windows Terminal 调到了前台但没选标签页 | 标签页标题与会话标题 / 会话名都对不上（被改过标题），或 UIA / `comtypes` 不可用；设计上退回「自己选」 |
| 点「Claude Code（WSL）」多出一个报 `0x80070002` 的标签 | 交给 `wt` 的脚本里有没转义的 `;` |
| WSL 新会话每次停在「信任此文件夹」 | `WSL_START_DIR` 指的目录在那个发行版里没被信任过（它是写死的常量，换机器要核对） |
| 新终端窗口没摆到左半边 | `fit_new_window` 8 s 内没等到新窗口，或摆了 3 次都被改回（日志有警告）；`cmd` 退路不摆 |
| 「Claude Desktop」置灰 | 两处都没找到：包名前缀或包仓库的注册表路径变了 |
| 「VS Code 工作区」只剩开着的和目录里的 | `workspaceStorage` 的结构变了，「最近」读不到 |
| 「VS Code 工作区」里未命名的 WSL 工作区列得不对 | `recent_entries` 仍把它当本机路径的 `workspace.json` 列（已知，未修；`opened_workspaces` 那边已经认得） |
| 右键主菜单偶尔卡几秒 | 配了 WSL 目录或有 WSL 窗口记录，而发行版没开着 |
