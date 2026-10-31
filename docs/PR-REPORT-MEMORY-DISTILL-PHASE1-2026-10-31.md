# PR 报告：会话记忆蒸馏·第一期——把我在 Claude Code 里说过的话抽进本地候选库，独立流程页让整条流程看得见

> **基线**：`60d546ff`
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-31
> **提交**：`efaca6cc`、`b4f20155`、`8332c2e6`
> **范围**：实现 12 个文件（含文案 2 个）+ 测试 2 个（新）/ 2 个（改）
> **过程**：2026-10-30 用户提出设计想法，评审两轮后逐条拍板（见下「设计决定」）；本 PR 是三期里的第一期

## 一、核心特性

用户 2026-10-30 的想法：每个会话里我发给 Claude 的消息里藏着决定、偏好、纠正，应该收起来、定期总结成文件、
让以后所有 Claude 都遵守。评审后定下的流程：

```
Claude Code 会话记录 ──► 增量抽取（规则打标）──► 本地候选库 ──► 每日蒸馏（模型）──► 逐条审核 ──► 落盘
     ~/.claude/projects          每小时               不进 git        第二期            第二期      CLAUDE.md + 知识库
```

**第一期只做前三步**，不调模型、不写任何记忆文件：

| # | 内容 | 现在 |
|---|---|---|
| 1 | 数据源 | **不另做记录**：Claude Code 自己把每条消息落在 `~/.claude/projects/<目录编码>/<会话>.jsonl`。只增量读这些文件（按字节游标，每个文件记读到哪）。`~/.claude/history.jsonl` 桌面版 / VS Code 不写（本机只有 94 行），不能当源 |
| 2 | 抽什么 | 主链（非 `isSidechain`）上**人敲的** user 记录：剥掉系统注入块（`<system-reminder>`、`<ide_opened_file>`、`<task-notification>`…）、图片 / 粘贴占位行、斜杠命令、监视器消息（`[Ticket watch]`）、压缩摘要（「This session is being continued…」）、只是一声「好 / ok」的；带上 **Claude 上一条正文**（截 500 字）作为「当时问了什么」。`AskUserQuestion` 的回答直接从 tool_result 记录的 `toolUseResult.answers` 取，算「决定」 |
| 3 | 打标 | 不用模型，按词：**规则**（以后 / 从现在起 / always / never / 记住…）> **决定**（决定 / 同意 / 就用 / go with…、AskUserQuestion 的回答）> **纠正**（不对 / 改回 / wrong / don't…）> **任务**（其余） |
| 4 | 个人 / 公司分流 | **按目录分，不按入口分**（见「实现要点」）：POSIX 路径一律公司侧，Windows 路径在设置里的「公司目录」下也算。抽取时就写进每条候选的 `side`，第二期蒸馏按侧各走各的账号，公司侧的话**根本不进**个人 key |
| 5 | 候选库 | `%APPDATA%\big-fat-fish\memory-distill\candidates\<本地日期>.jsonl`，**本地、不进 git**，滚动保留 N 天（默认 90）；`cursors.json` 记每个 transcript 的字节偏移、大小、开头指纹、上一条正文 |
| 6 | 独立流程页 | 右键 → Agent 联动 → 「会话记忆蒸馏」，托盘也有。Metro、白天 / 黑夜跟简报窗口同一份偏好。三页：**流程**（说明 + 六格流程图，前三格实时数字、后三格标「第二期」，点格子开对应目录；每个 Claude 环境的记忆库入口：AI-Base、AI-Base-Memory、Windows 与 WSL 的 `~/.claude`、全局 CLAUDE.md、会话记录目录、**原始候选库并注明本地不进 git**；当前设置一块磁贴）、**候选**（最近 200 条按时间新的在前，点一条看 Claude 当时说了什么、项目 / 分支 / 入口 / 会话）、**统计** |
| 7 | 服务 | 开着每小时增量抽一次（后台线程），第一次顺便问一次 WSL 里 `~/.claude` 的 Windows 路径（`wslpath -w`）。「现在抽取」手动触发；忙着不叠加 |
| 8 | 设置 | 设置页「自动化与联动」新一节：开关（默认关）、保留天数、公司目录、每日蒸馏时刻、模型、思考强度、**提示词明文**（第二期才用，按规矩一开始就摆出来）+ 折叠的流程说明 |

**设计决定**（用户 2026-10-30 逐条拍板）：开始阶段全人工审核，要改成自动化时提醒他；频率每日一次 + 手动；全局偏好落
`~/.claude/CLAUDE.md` 受管块，同时镜像进各自知识库；公司侧和个人侧都要（公司侧存 AI-Base-Memory）；原始候选库本地 90 天、
不进 git（我的建议，用户同意：git 里「滚动删除」删不掉历史，而且原话含公司内容 / 路径）；代码放肥鱼里，流程页单开一个窗口。

## 二、修改文件说明

> 行数来自 `git diff --numstat 60d546ff..8332c2e6`。

### 实现

| 文件 | + / − | 改了什么 | 为什么 |
|---|---|---|---|
| `pet/memory_distill.py`（新） | 588 / 0 | 纯函数与文件读写：`classify_side`、`clean_text`、`is_noise`、`tag_for`、`is_human_turn`、`extract(text, state)`（按字节游标只处理以换行结尾的整行）、`CandidateStore`（`refresh` / `append` / `read_day` / `read_all` / `prune` / `stats`）、配置节 `normalize`、蒸馏提示词模板（中 / 英） | 抽取不依赖 Qt、可以用合成 transcript 测；游标让每小时的扫描只读新字节 |
| `pet/memory_distill_service.py`（新） | 246 / 0 | `MemoryDistillService(QObject)`：每小时 `QTimer` → 后台线程 `store.refresh` + `prune`；`refreshed / failed / changed` 信号回 GUI；`places()` / `open_place()`（Obsidian 先试 `obsidian://open?path=`，没登记退回文件夹）；`wsl_claude_dir()` | 阻塞的读文件 / 起 wsl.exe 不能在 GUI 线程；入口的「在哪、能不能打开」集中一处 |
| `pet/memory_distill_ui.py`（新） | 611 / 0 | `FlowDiagram`（QPainter 画六格两行三列、箭头、虚线标第二期、悬停手形、点格子发信号）、`MemoryDistillWindow`（三页、整页滚动、Metro QSS）、`MemoryDistillController`（服务 ↔ 窗口 ↔ 宿主气泡） | 用户要「流程可见、设置可见」的独立页面 |
| `pet/settings_memory_distill.py`（新） | 112 / 0 | 设置页一节：开关、保留天数下拉、公司目录（分号隔开）、每日时刻、模型、effort、`PromptEditor`；`flow_section` 折叠说明；`save_distill_settings` | 和工作笔记 / 个人助理那两节同一写法 |
| `pet/config.py` | 6 / 0 | 注册 `memory_distill`：默认值、reload 白名单、`set()` 触发归一化、加载时归一化 | 配置节入场的四个固定位置 |
| `pet/app.py` | 16 / 0 | `_start_memory_distill()`：建服务 + 控制器挂到 overlay 壳（`shell.memory_distill`），紧跟个人助理之后启动 | 可选服务，异常不阻断启动 |
| `pet/context_menus/shared.py` | 3 / 0 | Agent 联动菜单加「会话记忆蒸馏」（壳上挂了控制器才显示） | 入口 |
| `pet/overlay_shell.py` | 2 / 0 | 托盘菜单「肥鱼设置」上面加同一项 | 入口 |
| `pet/sprite_menu_facade.py` | 6 / 0 | `open_memory_distill()` | 菜单动作经门面 |
| `pet/modern_settings_dialog.py` | 5 / 2 | 「自动化与联动」页插入新一节与流程说明；保存时调 `save_distill_settings` | 设置页入场 |
| `pet/locale/zh.json`、`en.json` | 96 / 1 ×2 | `distill.*` 95 个键 | 新功能文案中英文都要 |

### 测试

| 文件 | + / − | 覆盖 |
|---|---|---|
| `tests/test_memory_distill.py`（新） | 259 / 0 | 分流（POSIX / 公司目录 / 目录边界 / 大小写）、15 种噪音、注入块剥离、图片 / 粘贴占位行、8 条打标、主链人敲的才抽且带前文、AskUserQuestion → 决定、前文截断与半行等待、跨次扫描续游标、公司侧标记；候选库增量 / 重写后重扫 / 过期清理 / 统计 / 坏行；配置归一化 |
| `tests/test_memory_distill_ui.py`（新） | 348 / 0 | 服务真线程回报、开关控制定时、抽取出错回报、入口与打开（候选库目录不存在就建、Obsidian 没登记退回文件夹）、`wsl_claude_dir` 三种情况；页面 Metro 方角与配色、流程图数字与候选列表、入口按钮与点格子、主题切换存共用偏好、英文、页面不够高时整页滚动而不是压扁流程图、流程图两行三列能画；设置页一节往返、提示词按语言与用户覆盖 |
| `tests/test_config_schema.py` | 1 / 0 | 顶层键清单加 `memory_distill` |
| `tests/test_sprite_menu_parity.py` | 3 / 1 | overlay 独有条目加「会话记忆蒸馏」 |

### 未改动

- 不碰 `~/.claude` 下任何文件、不碰两个知识库仓库：第一期只读 transcript，只写自己的候选库目录。
- 没有模型调用；`daily_at` / `model` / `effort` / 提示词已存配置，这一期不用。
- 会话小鱼、简报、工作笔记、个人助理的逻辑没动；流程页只复用了简报窗口的配色令牌、主题偏好和 `TiltButton`。

## 三、实现要点

1. **公司 / 个人按目录分，不按入口分。** 实测本机 `~/.claude/projects` 里有 5 个 `ssh-<uuid>/` 目录，是桌面版开的 WSL 会话：
   记录的 `entrypoint` 是 `claude-desktop`、`cwd` 是 `/home/...`。原设计「按入口分流」会把这些公司会话归到个人侧。改成
   `classify_side(cwd, work_roots)`：POSIX 路径一律公司侧；Windows 路径按路径段比较（`WorkSpaceX` 不算 `WorkSpace` 下面）。
2. **游标 + 开头指纹。** transcript 只追加，所以记字节偏移就够；但文件被整个重写（变短、或恰好变长）时得从头再来——游标里
   存前 256 字节的指纹，变了就重扫。只处理以 `\n` 结尾的整行，正在写的半行留到下次。
3. **「Claude 当时问了什么」跨次扫描也记得。** 上一条 assistant 正文存在游标里（`before`），下次从中间续扫时第一条候选照样有前文。
4. **候选去重键是 user 记录的 `uuid`。** AskUserQuestion 一次问多题时后缀 `#1`、`#2`。
5. **流程页整页滚动、流程图定高。** 第一版截图里窗口不够高时入口按钮画到了流程图第二行上（`QVBoxLayout` 把最小高度压没了）；
   改成流程图 `setFixedHeight`，页面内容放 `QScrollArea`，底部按钮行固定在滚动区外。
6. **UNC 路径不 stat。** WSL 的 `\\wsl.localhost\...` 在发行版没起来时 `Path.exists()` 会卡几秒甚至报权限错（测试里用假路径就报了
   `WinError 1326`）；路径本来就是问 `wslpath` 得来的，直接当存在。
7. **信号顺序。** 服务先发 `changed`（页面重摆数字，会清状态行）再发 `refreshed`（写「新增 N 条」），否则结果行被重摆盖掉。
8. 设置页的 `work_roots` 是列表，手写成一个字符串算写错、退回默认——避免 `"x"` 被当成一个目录。

## 四、性能分析

> 环境：Windows 11，本机 `.venv` Python 3.13，PySide6；数据是本机真实 `~/.claude/projects`（30 个 transcript，112.2 MB）。
> 命令：scratchpad 里的两个脚本（`capture_distill.py` 建页抓图；一段 `psutil` 计时），`QT_QPA_PLATFORM=windows`。

| 路径 | 实测 | 说明 |
|---|---|---|
| 首次全量抽取 | **310 条候选，0.87 s**（另一次 0.98 s）；RSS **+2.4 MB** | 后台线程；一台机器只发生一次（之后都是增量） |
| 无变化复扫（每小时那次） | 20 次：**p50 9.9 ms，最大 11.7 ms**；RSS +0.1 MB | 30 个文件各 `stat` + 读 256 字节指纹；不读正文 |
| 候选库体积 | **392 KB**（310 条，17 天） | 一天几十条，90 天不过几 MB |
| `stats()` / `recent()` / `places()` | **5.5 ms / 3.8 ms / 0.2 ms** | 每次打开页面、每次抽完各一次 |
| 打开流程页 | 进程里 Qt 已热：第一次 **285 ms**，之后 **72–80 ms**；其中 `_refresh_window` 28 ms | 冷进程（字体库 / 平台插件未加载）1.37 s，桌宠里不会是冷的 |
| 问 WSL 路径（`wslpath -w`） | 一次 `wsl.exe`：3 次实测 **108 / 110 / 117 ms** | 只在第一次抽取时做一次（在抽取线程里），结果缓存在服务里 |
| 服务空闲 | 一个 `QTimer`（60 分钟）；默认关时定时器照跑但 `check()` 只读一次配置就返回 | 没有新线程常驻、没有网络、没有写盘（除候选库） |

逐条回答：

- **稳态开销**：开着 = 每小时约 10 ms 的文件 `stat`；关着 = 每小时一次配置读取。无常驻线程。
- **新增路径成本与触发频率**：首扫 ~1 s / 一次；增量 ~10 ms / 小时（有新内容时按新字节量线性，100 MB 对应 ~0.9 s）；
  打开页面 ~80 ms / 次。
- **新的系统调用 / 网络 / 磁盘 / 线程**：读 transcript（原来会话小鱼只读尾部 512 KiB，这里首扫读全文一次）；写候选库目录；
  一次 `wsl.exe`；抽取时起一个 daemon 线程、结束即退。无网络。
- **内存**：首扫 +2.4 MB（候选行在内存里过一遍再写盘），之后不增长；页面持有最近 200 条候选的 dict（< 1 MB）。

## 五、实机运行记录

**2026-10-30 ～ 10-31，本机真实环境。**

1. **数据形状探查**（决定设计的依据）：
   - `~/.claude/history.jsonl` 94 行，而 `projects` 下 user 记录数千条 → history 不能当源。
   - 6 个最近 transcript 里 user 记录的 `origin.kind` 有 `human` / `task-notification` / `peer`，`turnOrigin` 有 `human` / `scheduled` /
     `task_notification` / `sdk`；文本开头的系统标签 16 种（`<task-notification>` 35 次、`[Upgrade channel watch]` 32 次、
     `<ide_opened_file>` 10 次…）→ `is_human_turn` + `clean_text` + `is_noise` 三道过滤。
   - AskUserQuestion 的 tool_result 记录带 `toolUseResult.answers`（问 → 答的 dict）→ 直接取，不回头找 tool_use。
   - 5 个 `ssh-<uuid>/` 目录共 591 条 user 记录、`entrypoint=claude-desktop`、cwd 为 POSIX → 按目录分流。
2. **干跑真实 transcript**（候选库写在 scratchpad，不碰真实数据目录）：第一版 364 条；加了图片占位行过滤后 318 条；加了压缩摘要过滤后
   **310 条**：个人 247 / 公司 63；规则 18、决定 25、纠正 8、任务 259；覆盖 17 天（最早 2026-09-28）；339/364 条带「当时问了什么」。
3. **建页抓图**（`QT_QPA_PLATFORM=windows`，真实配置只读）：七个入口全部认出并存在——AI-Base 克隆、AI-Base-Memory 副本、
   `C:\Users\<user>\.claude`、`\\wsl.localhost\<发行版>\home\<user>\.claude`（`wslpath -w` 问到的）、全局 CLAUDE.md、`projects`、候选库。
   第一版截图发现入口按钮压在流程图上 → 改整页滚动后重抓，白天 / 黑夜 × 三页正常。候选列表里看到两处打标要修（压缩摘要被当
   规则、「同意…」被当任务）→ 已修并加用例。
4. **桌宠重启**：`2026-10-31 00:07:19 acquired pid=52996`，主检出 `feature/claude-session-fish` 快进到 `8332c2e6`。
   新进程日志无「会话记忆蒸馏接线失败」、无 Traceback。（用户在实机上点开页面的确认见下。）
5. **用户确认**：待填。

> 报告与测试里不引用候选的内容（那是用户的原话，含公司项目）；统计只给计数。

## 六、测试与验证

- 新用例在修之前都是红的（纯函数模块先写测试再写实现；页面的「整页滚动」用例对着第一版截图写、改前红）。
- 聚焦：`tests/test_memory_distill.py` 42 个、`tests/test_memory_distill_ui.py` 15 个，加 i18n（键对齐 + 代码用键）、
  配置 schema、菜单对齐、设置页布局、简报 Metro、个人助理、工作笔记——212 个全过；`ruff check pet tests` 干净；`git diff --check` 干净。
- 全量（`8332c2e6`，独立 worktree，PowerShell 启动，`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指到临时目录）：
  **5923 passed，14 skipped，4 failed，10 分 41 秒**。4 个失败都是本机既有的环境性基线（基线提交上同样失败）：
  `test_image_directory_picker_opens_right_drawer_with_three_column_masonry`（路径超 260）、`test_festival_id_guard_survives_optimize`、
  `test_real_second_process_refused_on_overlay_topology`（子进程输出 cp1252 解码）、`test_capture_window_rect_coordinates_and_clamping`
  （多显示器负原点）。没有新失败。

## 七、已知限制与后续

- **第二期**（蒸馏 + 审核 + 落盘）：每日定时 + 手动，个人侧走 `anthropic_provider.complete`，提案 → 审核窗（接受 / 改 / 拒，
  拒的进「别再提」名单）→ CLAUDE.md 受管块 / 项目 memory / AI-Base 镜像。页面上「现在总结」按钮和后三格已留位。
- **第三期**（公司侧）：WSL 里独立抽取、公司账号 `claude -p` 蒸馏、落 AI-Base-Memory；流程页分两条泳道。
- 现在只读 Windows 这边的 `~/.claude/projects`（含桌面版的 WSL 会话）；WSL 自己终端里开的会话在发行版里，第三期再接。
- 打标是词表，会有漏判（「要，用 X」这类没关键词的决定算任务）；第二期蒸馏时模型看全文，不靠标签过滤，标签只决定预算不够时先丢谁。
- 候选页会显示公司侧的原话（这是用户自己的机器上的本地页面）；它们不进任何模型调用。

## 八、风险与回滚

- 默认关，不开就只有菜单里多一项、设置里多一节；候选库目录只在抽取时创建。
- 回滚 = revert 三个提交；候选库目录 `%APPDATA%\big-fat-fish\memory-distill` 可直接删。
